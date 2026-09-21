"""A removed Tile leaves the index immediately — asked through the search, not the table.

`test_remove_tile.py` counts rows. This file asks `find_candidates`, which is
the function Epic 3's scan endpoint calls, because the acceptance criterion is
about what a Scan gets back and not about what a `count(*)` says. The two fail
differently: a soft-delete flag would satisfy every row count that named the
flag and would still hand the removed Tile back here.

Nothing between a removal and a read rebuilds, reindexes, vacuums or analyses
anything, and that absence is the assertion — `test_edited_tile_searchable.py`'s
shape, one level up from a Reference Image.
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

#: Edge length of a generated reference. `test_edited_tile_searchable.py`'s
#: value, and for its reason: large enough that the augmented crops (25–60% of
#: the short edge) still carry structure at 224px input.
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
    no longer finds a Tile that was withdrawn.
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


def codes(conn: psycopg.Connection, query: Image.Image) -> list[str]:
    return [candidate.code for candidate in catalogue.find_candidates(conn, query, limit=10)]


def test_a_removed_tile_is_no_longer_a_candidate_for_its_own_reference_image(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser
) -> None:
    """The acceptance criterion, asked the way a Scan asks it.

    The query is a perturbed copy of the removed Tile's *own* reference image —
    the most favourable image there could be for it — so "however visually
    similar" is not a hypothetical. A survivor is indexed alongside it so that
    the search has something to answer with, which is what makes the absence a
    result rather than an empty table.
    """
    sign_in_as_administrator(client, make_user)
    doomed_surface, kept_surface = a_tile(51), a_tile(52)
    doomed = add_tile(client, "WITHDRAWN", doomed_surface)
    add_tile(client, "STILL-HERE", kept_surface)

    query = a_photograph_of(doomed_surface)
    # Read into a name and checked for emptiness before it is indexed: an empty
    # candidate set here is a broken fixture or a broken index, and `[0]` would
    # report it as an `IndexError` that names neither.
    before = codes(conn, query)
    assert before != [], "the catalogue returned no candidates before the removal"
    assert before[0] == "WITHDRAWN"

    response = client.delete(f"{ADD_TILE}/{doomed['id']}")
    assert response.status_code == 204, response.text
    # Deliberately nothing here. No REINDEX, no VACUUM, no ANALYZE, no restart.

    after = codes(conn, query)

    assert "WITHDRAWN" not in after
    # And the search still works: the survivor answers, so the absence above is
    # the removed Tile being gone rather than the query finding nothing at all.
    assert after == ["STILL-HERE"]


def test_the_survivor_keeps_its_own_score_and_its_own_candidacy(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser
) -> None:
    # A removal that re-embedded, re-normalised or otherwise disturbed the rest
    # of the generation would move this. It is the half of "other tiles are
    # untouched" that a row count cannot see.
    sign_in_as_administrator(client, make_user)
    doomed_surface, kept_surface = a_tile(61), a_tile(62)
    doomed = add_tile(client, "WITHDRAWN", doomed_surface)
    add_tile(client, "STILL-HERE", kept_surface)

    kept_query = a_photograph_of(kept_surface)
    before = {
        candidate.code: candidate.score
        for candidate in catalogue.find_candidates(conn, kept_query, limit=10)
    }

    assert client.delete(f"{ADD_TILE}/{doomed['id']}").status_code == 204

    after = {
        candidate.code: candidate.score
        for candidate in catalogue.find_candidates(conn, kept_query, limit=10)
    }

    assert after["STILL-HERE"] == pytest.approx(before["STILL-HERE"], abs=1e-6)
    assert list(after) == ["STILL-HERE"]


def test_removing_the_last_tile_leaves_a_search_that_answers_nothing(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser
) -> None:
    # Not an error, and not a padded result: an emptied catalogue has nothing to
    # return, and `find_candidates` is never back-filled from outside the index.
    sign_in_as_administrator(client, make_user)
    surface = a_tile(71)
    only = add_tile(client, "THE-ONLY-ONE", surface)

    assert client.delete(f"{ADD_TILE}/{only['id']}").status_code == 204

    assert catalogue.find_candidates(conn, a_photograph_of(surface)) == []


def test_every_view_of_a_removed_tile_leaves_the_graph_not_just_the_first(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser
) -> None:
    # AD-13 stores 16 views per image and a Tile can carry several images, so
    # "the Tile is gone" has to mean every one of them. A removal that cascaded
    # one image's rows and not the other's would still answer the query above
    # from the surviving half.
    sign_in_as_administrator(client, make_user)
    first, second = a_tile(81), a_tile(82)
    doomed = add_tile(client, "TWO-IMAGES", first, second)
    add_tile(client, "STILL-HERE", a_tile(83))

    total = conn.execute("SELECT count(*) AS n FROM reference_embedding").fetchone()
    assert total is not None and total["n"] == 48

    assert client.delete(f"{ADD_TILE}/{doomed['id']}").status_code == 204

    for surface in (first, second):
        assert "TWO-IMAGES" not in codes(conn, a_photograph_of(surface))
    survived = conn.execute("SELECT count(*) AS n FROM reference_embedding").fetchone()
    assert survived is not None and survived["n"] == 16
