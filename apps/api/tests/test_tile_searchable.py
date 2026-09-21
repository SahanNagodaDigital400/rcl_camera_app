"""FR-19's acceptance, folded in: a Tile added now is findable now.

The epic states it as "an Administrator adds a tile and a Scan submitted in
the same session returns it as a Candidate, with no manual re-index step, no
ticket and no data re-import". The Scan surface arrives in Epic 3, so the
testable form of the claim here is the query itself — `catalogue.find_candidates`,
which is the function that endpoint will call rather than a second one written
beside it.

What "no re-index step" means mechanically is AD-5's HNSW index: an insert
joins the searchable graph immediately. Nothing in this file rebuilds,
reindexes, vacuums or analyses anything between the write and the read, and
that absence is the assertion.
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
from shared_schema.errors import ApiError
from shared_schema.user import Role
from shared_vision import pipeline

MakeUser = Callable[..., Any]

ADD_TILE = "/admin/tiles"
LOGIN = "/auth/login"

pytestmark = pytest.mark.skipif(
    not pipeline.MODEL_PATH.exists(),
    reason="model not downloaded; run `make model`",
)


#: Edge length of a generated reference. Large enough that the augmented crops
#: (25-60% of the short edge) still carry structure at 224px input.
TILE_SIZE = 384


def a_tile(seed: int) -> Image.Image:
    """A tile face with visible structure. Different seeds look different.

    **Not random noise**, and the difference matters. Per-pixel noise is not a
    texture to a vision model: every such image embeds to roughly the same
    place, so a catalogue of them makes retrieval a coin toss and this file
    would be measuring the fixture rather than the index. Real tiles have
    colour, pattern and scale, so these have stripes, rings or diagonals at a
    per-seed period over a per-seed ground, with a little grain on top.
    """
    rng = np.random.default_rng(seed)
    face = Image.new("RGB", (TILE_SIZE, TILE_SIZE), tuple(int(v) for v in rng.integers(30, 220, 3)))
    pen = ImageDraw.Draw(face)
    ink = tuple(int(v) for v in rng.integers(30, 220, 3))
    period = int(rng.integers(12, 48))
    for offset in range(0, TILE_SIZE, period):
        if seed % 3 == 0:
            pen.rectangle([offset, 0, offset + period // 2, TILE_SIZE], fill=ink)
        elif seed % 3 == 1:
            pen.ellipse([offset, offset, offset + period, offset + period], outline=ink, width=4)
        else:
            pen.line([(0, offset), (TILE_SIZE, offset + period)], fill=ink, width=5)

    grain = np.asarray(face, dtype=np.int16) + rng.integers(-12, 12, (TILE_SIZE, TILE_SIZE, 3))
    return Image.fromarray(np.clip(grain, 0, 255).astype(np.uint8), "RGB")


def as_upload(image: Image.Image) -> bytes:
    buf = io.BytesIO()
    image.save(buf, format="JPEG", quality=92)
    return buf.getvalue()


def a_photograph_of(image: Image.Image) -> Image.Image:
    """A perturbed copy: cropped, warmed, softened and recompressed.

    Not the reference image itself. Matching a file against itself proves the
    index stores bytes; the claim here is that a Scan of the physical tile
    finds it, and the nearest honest stand-in inside a unit test is a copy that
    no longer has the same pixels.
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


def add_tile(client: TestClient, code: str, image: Image.Image, size: str = "45X90") -> Any:
    response = client.post(
        ADD_TILE,
        data={"code": code, "size": size, "category": "POLISH"},
        files=[("images", (f"{code}.jpg", as_upload(image), "image/jpeg"))],
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_a_tile_added_in_this_session_is_a_candidate_with_no_reindex(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser
) -> None:
    sign_in_as_administrator(client, make_user)
    reference = a_tile(41)
    add_tile(client, "RP.CMA.0001DJ.SM.0T", reference)
    # Deliberately nothing here. No REINDEX, no VACUUM, no ANALYZE, no restart:
    # whatever the query below finds, it finds in the graph the insert joined.

    candidates = catalogue.find_candidates(conn, a_photograph_of(reference))

    assert [candidate.code for candidate in candidates] == ["RP.CMA.0001DJ.SM.0T"]
    assert candidates[0].size == "45X90"
    assert candidates[0].category == "POLISH"


def test_the_right_tile_is_in_the_top_three_of_a_populated_catalogue(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser
) -> None:
    sign_in_as_administrator(client, make_user)
    tiles = {f"TILE-{seed}": a_tile(seed) for seed in (11, 12, 13, 14)}
    for code, image in tiles.items():
        add_tile(client, code, image)

    wanted = "TILE-13"
    candidates = catalogue.find_candidates(conn, a_photograph_of(tiles[wanted]))

    assert len(candidates) == catalogue.TOP_K == 3
    assert wanted in [candidate.code for candidate in candidates]
    assert [candidate.rank for candidate in candidates] == [1, 2, 3]
    # Ranked best first. `<#>` is the negative inner product, so the ordering
    # in SQL is ascending on it and descending on the score; a sign error here
    # would return the *least* similar three and nothing else would notice.
    assert candidates == sorted(candidates, key=lambda c: -c.score)


def test_candidates_are_one_per_tile_and_never_collapsed_by_category(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser
) -> None:
    # AD-18: three candidates from `45X90/POLISH` are three distinct answers
    # competing on merit. Collapsing or diversifying by Category would hide
    # correct ones, and every tile in this test shares a Size and a Category.
    sign_in_as_administrator(client, make_user)
    for seed in (21, 22, 23):
        add_tile(client, f"POLISH-{seed}", a_tile(seed))

    candidates = catalogue.find_candidates(conn, a_photograph_of(a_tile(22)))

    assert len(candidates) == 3
    assert len({candidate.tile_id for candidate in candidates}) == 3
    assert {candidate.category for candidate in candidates} == {"POLISH"}


def test_a_tile_with_several_images_still_occupies_one_candidate_slot(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser
) -> None:
    # AD-13's pooling extended one level up: where a Tile carries several
    # images they are views of one identity, so its score is the max across
    # them and it is still one Candidate.
    sign_in_as_administrator(client, make_user)
    reference = a_tile(31)
    response = client.post(
        ADD_TILE,
        data={"code": "MANY", "size": "60X60"},
        files=[
            ("images", ("a.jpg", as_upload(reference), "image/jpeg")),
            ("images", ("b.jpg", as_upload(a_photograph_of(reference)), "image/jpeg")),
        ],
    )
    assert response.status_code == 201

    candidates = catalogue.find_candidates(conn, a_photograph_of(reference))

    assert [candidate.code for candidate in candidates] == ["MANY"]


def test_fewer_than_three_tiles_returns_fewer_than_three_candidates(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser
) -> None:
    # Never padded. A catalogue of two answers two, and an empty one answers
    # nothing rather than raising.
    sign_in_as_administrator(client, make_user)
    assert catalogue.find_candidates(conn, a_tile(1)) == []

    add_tile(client, "ONLY", a_tile(51))

    assert len(catalogue.find_candidates(conn, a_tile(1))) == 1


def test_searching_an_empty_catalogue_writes_nothing(conn: psycopg.Connection) -> None:
    """A read must not be a writer.

    `find_candidates` resolves the active generation, and an earlier draft
    *created* one when there was none — so every scan of an unpopulated
    catalogue opened a row, and the read path needed the write privileges and
    the transaction it otherwise does not. Epic 3 puts this behind a
    staff-facing endpoint, where that would be a row written by anyone who can
    photograph a tile.
    """
    before = conn.execute("SELECT count(*) AS total FROM embedding_generation").fetchone()
    assert before is not None and before["total"] == 0

    assert catalogue.find_candidates(conn, a_tile(1)) == []

    after = conn.execute("SELECT count(*) AS total FROM embedding_generation").fetchone()
    assert after is not None and after["total"] == 0


def test_a_search_against_a_foreign_stamp_is_still_refused(
    conn: psycopg.Connection,
) -> None:
    # Read-only does not mean lenient: AD-14's mismatch is a hard error on the
    # read side too, which is where the AD puts it.
    conn.execute(
        "INSERT INTO embedding_generation (pipeline_version, config_hash, is_active) "
        "VALUES (%s, %s, true)",
        ("dinov2b-224-something-else", "0000000000000000"),
    )

    with pytest.raises(ApiError) as refused:
        catalogue.find_candidates(conn, a_tile(1))

    assert refused.value.code == "pipeline_stamp_mismatch"


def test_the_query_scores_the_max_over_views_and_not_the_average(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser
) -> None:
    """AD-13, asserted against the arithmetic rather than against the ranking.

    An averaging query would still rank plausibly on a small catalogue, so the
    ordering alone cannot tell the two apart. What can: the score the search
    reports must equal the single best view's similarity, and on a set of 16
    views covering four rotations and twelve distorted crops the best is
    comfortably above the mean.
    """
    sign_in_as_administrator(client, make_user)
    reference = a_tile(61)
    add_tile(client, "MAXPOOL", reference)
    query = a_photograph_of(reference)

    reported = catalogue.find_candidates(conn, query)[0].score

    vector = pipeline.embed(pipeline.preprocess(query))[0]
    stored = [
        np.array([float(value) for value in row["embedding"].strip("[]").split(",")])
        for row in conn.execute("SELECT embedding FROM reference_embedding").fetchall()
    ]
    similarities = [float(vector @ candidate) for candidate in stored]

    assert reported == pytest.approx(max(similarities), abs=1e-5)
    assert reported > float(np.mean(similarities)) + 1e-3


def test_the_query_path_embeds_through_the_same_function_as_the_write_path(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser
) -> None:
    """AD-1, at the level this story can see it.

    `shared/vision/tests/test_pipeline.py` proves the two halves produce
    bit-identical vectors. This proves the *catalogue* is wired to them: the
    first of a reference image's 16 stored views is the unmodified frame, so
    embedding that same frame as a query must reproduce the stored vector
    exactly. A query path that resized, re-cropped or re-converted on its way
    in would still rank fine and would fail here.
    """
    sign_in_as_administrator(client, make_user)
    reference = a_tile(71)
    add_tile(client, "SYMMETRY", reference)

    row = conn.execute("SELECT embedding FROM reference_embedding WHERE view_index = 0").fetchone()
    assert row is not None
    stored = np.array([float(value) for value in row["embedding"].strip("[]").split(",")])

    # The bytes the write path saw are the intake's output, not the upload, so
    # the query side has to start from the same place: decode the same JPEG
    # through the same loader.
    as_intaken = pipeline.load_image(as_upload(reference))
    query = pipeline.embed(pipeline.preprocess(as_intaken))[0]

    # `vector(1536)` stores float4, so the round trip through the column is
    # what the tolerance is for — not a difference between the two paths.
    np.testing.assert_allclose(stored, query, atol=1e-6)
