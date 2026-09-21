"""An edit lands in the index immediately — including the half that takes things out.

`test_tile_searchable.py` makes this claim for the add. The edit has three
versions of it and they fail in different ways:

* a **renamed** Code is live at once, because nothing about the vectors moved
  and the Code is read off the joined row rather than copied into it;
* an **added** image makes the Tile findable *from that image*, because its 16
  views joined the HNSW graph on insert (AD-5);
* a **removed** image stops being a way to reach the Tile at all, because the
  row was really deleted and its embeddings cascaded out (AD-5, epic context) —
  the one of the three a soft-delete flag would quietly not do.

Nothing here rebuilds, reindexes, vacuums or analyses anything between a write
and a read, and that absence is the assertion.
"""

from __future__ import annotations

import io
from collections.abc import Callable
from typing import Any

import numpy as np
import psycopg
import pytest
from api import catalogue
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter
from shared_schema.user import Role
from shared_vision import pipeline

MakeUser = Callable[..., Any]

ADD_TILE = "/admin/tiles"
LOGIN = "/auth/login"

pytestmark = pytest.mark.skipif(
    not pipeline.MODEL_PATH.exists(),
    reason="model not downloaded; run `make model`",
)

#: Edge length of a generated reference. `test_tile_searchable.py`'s value, and
#: for its reason: large enough that the augmented crops (25–60% of the short
#: edge) still carry structure at 224px input.
TILE_SIZE = 384


def a_tile(seed: int) -> Image.Image:
    """A tile surface with visible structure. `test_tile_searchable.py`'s fixture.

    **Not random noise.** Per-pixel noise is not a texture to a vision model:
    every such image embeds to roughly the same place, so a catalogue of them
    makes retrieval a coin toss and this file would be measuring the fixture
    rather than the index.
    """
    rng = np.random.default_rng(seed)
    ground = tuple(int(v) for v in rng.integers(30, 220, 3))
    surface = Image.new("RGB", (TILE_SIZE, TILE_SIZE), ground)
    pen = ImageDraw.Draw(surface)
    ink = tuple(int(v) for v in rng.integers(30, 220, 3))
    period = int(rng.integers(12, 48))
    for offset in range(0, TILE_SIZE, period):
        if seed % 3 == 0:
            pen.rectangle([offset, 0, offset + period // 2, TILE_SIZE], fill=ink)
        elif seed % 3 == 1:
            pen.ellipse([offset, offset, offset + period, offset + period], outline=ink, width=4)
        else:
            pen.line([(0, offset), (TILE_SIZE, offset + period)], fill=ink, width=5)

    grain = np.asarray(surface, dtype=np.int16) + rng.integers(-12, 12, (TILE_SIZE, TILE_SIZE, 3))
    return Image.fromarray(np.clip(grain, 0, 255).astype(np.uint8), "RGB")


def as_upload(image: Image.Image) -> bytes:
    buf = io.BytesIO()
    image.save(buf, format="JPEG", quality=92)
    return buf.getvalue()


def a_photograph_of(image: Image.Image) -> Image.Image:
    """A perturbed copy: cropped, warmed, softened and recompressed.

    Not the reference image itself — matching a file against itself proves the
    index stores bytes, and the claim here is that a Scan of the physical tile
    finds it.
    """
    width, height = image.size
    crop = image.crop((width // 8, height // 8, width * 7 // 8, height * 7 // 8))
    crop = ImageEnhance.Brightness(crop).enhance(1.12)
    crop = crop.filter(ImageFilter.GaussianBlur(radius=0.8))
    buf = io.BytesIO()
    crop.save(buf, format="JPEG", quality=62)
    buf.seek(0)
    return Image.open(buf).convert("RGB")


def sign_in_as_administrator(client: TestClient, make_user: MakeUser) -> Any:
    account = make_user(role=Role.ADMIN, name="Nadeesha Silva")
    response = client.post(LOGIN, json={"email": account.email, "password": account.password})
    assert response.status_code == 200
    return account


def add_tile(client: TestClient, code: str, *images: Image.Image, size: str = "45X90") -> Any:
    response = client.post(
        ADD_TILE,
        data={"code": code, "size": size, "category": "POLISH"},
        files=[
            ("images", (f"{code}-{index}.jpg", as_upload(image), "image/jpeg"))
            for index, image in enumerate(images)
        ],
    )
    assert response.status_code == 201, response.text
    return response.json()


def scores(conn: psycopg.Connection, query: Image.Image) -> dict[str, float]:
    return {
        candidate.code: candidate.score
        for candidate in catalogue.find_candidates(conn, query, limit=10)
    }


def test_a_renamed_code_reaches_the_search_at_once(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser
) -> None:
    sign_in_as_administrator(client, make_user)
    reference = a_tile(41)
    created = add_tile(client, "RP.CMA.0001DJ.SM.0T", reference)

    response = client.patch(f"{ADD_TILE}/{created['id']}", data={"code": "RP.CMA.0002DJ.SM.0T"})
    assert response.status_code == 200, response.text
    # Deliberately nothing here. No REINDEX, no VACUUM, no ANALYZE, no restart.

    candidates = catalogue.find_candidates(conn, a_photograph_of(reference))

    assert [candidate.code for candidate in candidates] == ["RP.CMA.0002DJ.SM.0T"]
    # The same Tile, under a new Code, with the same embeddings behind it.
    assert str(candidates[0].tile_id) == created["id"]


def test_an_added_image_makes_the_tile_findable_from_that_image(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser
) -> None:
    sign_in_as_administrator(client, make_user)
    # Two visibly different reference images of one Tile — the second one is
    # only reachable after the edit adds it.
    first, second = a_tile(11), a_tile(12)
    created = add_tile(client, "TWO-IMAGES", first)
    # A distractor so the answer is not the only row in the table.
    add_tile(client, "SOMETHING-ELSE", a_tile(13))

    before = scores(conn, a_photograph_of(second))

    response = client.patch(
        f"{ADD_TILE}/{created['id']}",
        files=[("images", ("second.jpg", as_upload(second), "image/jpeg"))],
    )
    assert response.status_code == 200, response.text

    after = scores(conn, a_photograph_of(second))

    assert after["TWO-IMAGES"] > before["TWO-IMAGES"]
    assert max(after, key=lambda code: after[code]) == "TWO-IMAGES"


def test_a_removed_image_is_no_longer_a_way_to_reach_the_tile(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser
) -> None:
    """The half a soft-delete flag would quietly not do.

    The Tile keeps a second image, so it is still in the catalogue and still a
    Candidate — which is what makes the claim checkable: its score for a
    photograph of the *removed* image must fall back to what the surviving image
    alone can offer, and the surviving image's own score must not move at all.
    """
    sign_in_as_administrator(client, make_user)
    kept, doomed = a_tile(21), a_tile(22)
    created = add_tile(client, "LOSES-AN-IMAGE", kept, doomed)
    add_tile(client, "SOMETHING-ELSE", a_tile(23))

    doomed_query = a_photograph_of(doomed)
    kept_query = a_photograph_of(kept)
    before_doomed = scores(conn, doomed_query)["LOSES-AN-IMAGE"]
    before_kept = scores(conn, kept_query)["LOSES-AN-IMAGE"]

    # The image to remove is the one whose row is not the kept one's.
    images = created["reference_images"]
    assert len(images) == 2
    response = client.patch(
        f"{ADD_TILE}/{created['id']}", data={"remove_image_ids": images[1]["id"]}
    )
    assert response.status_code == 200, response.text
    assert len(response.json()["reference_images"]) == 1

    after_doomed = scores(conn, doomed_query)["LOSES-AN-IMAGE"]
    after_kept = scores(conn, kept_query)["LOSES-AN-IMAGE"]

    # The removed image no longer contributes, so the Tile's score for it drops
    # to what the remaining image alone scores.
    assert after_doomed < before_doomed
    # And the surviving image is untouched — a removal that re-embedded or
    # disturbed the rest would move this.
    assert after_kept == pytest.approx(before_kept, abs=1e-6)


def test_a_removed_images_embeddings_are_gone_from_the_table(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser
) -> None:
    # The mechanism under the behaviour above: `DELETE FROM reference_image`
    # cascades to `reference_embedding`. No flag, no query-time predicate — a
    # predicate is a thing exactly one call site has to remember, and Epic 3's
    # scan is the call site that must not forget.
    sign_in_as_administrator(client, make_user)
    created = add_tile(client, "CASCADE", a_tile(31), a_tile(32))
    doomed = created["reference_images"][0]["id"]

    total = conn.execute("SELECT count(*) AS n FROM reference_embedding").fetchone()
    assert total is not None and total["n"] == 32

    response = client.patch(f"{ADD_TILE}/{created['id']}", data={"remove_image_ids": doomed})
    assert response.status_code == 200, response.text

    survived = conn.execute("SELECT count(*) AS n FROM reference_embedding").fetchone()
    assert survived is not None and survived["n"] == 16
    orphans = conn.execute(
        "SELECT count(*) AS n FROM reference_embedding WHERE reference_image_id = %s",
        (doomed,),
    ).fetchone()
    assert orphans is not None and orphans["n"] == 0


def test_a_replacement_image_is_searchable_and_the_old_one_is_not(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser
) -> None:
    # The two halves in one request, which is the shape an Administrator
    # replacing a bad asset actually uses.
    sign_in_as_administrator(client, make_user)
    old, new = a_tile(41), a_tile(42)
    created = add_tile(client, "REPLACED", old)
    add_tile(client, "SOMETHING-ELSE", a_tile(43))

    before_old = scores(conn, a_photograph_of(old))["REPLACED"]

    response = client.patch(
        f"{ADD_TILE}/{created['id']}",
        data={"remove_image_ids": created["reference_images"][0]["id"]},
        files=[("images", ("new.jpg", as_upload(new), "image/jpeg"))],
    )
    assert response.status_code == 200, response.text

    after_old = scores(conn, a_photograph_of(old))["REPLACED"]
    after_new = scores(conn, a_photograph_of(new))

    assert after_old < before_old
    assert max(after_new, key=lambda code: after_new[code]) == "REPLACED"
