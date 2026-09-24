"""A bulk-loaded Tile is in the index the moment its row is reported.

`test_tile_searchable.py` makes this claim for the single add and
`test_edited_tile_searchable.py` for the edit. The bulk path is where it is
easiest to lose: a batch is the natural place for somebody to reach for a
staging table, a deferred index build or a "rebuild once at the end" step, and
each of those would pass every test in `test_bulk_upload.py` — the rows are
written, the report is right — while the Tiles stayed unfindable until
something nobody has built ran.

So the claim is made through `find_candidates` rather than through a row count,
against a *perturbed copy* of the reference rather than the reference itself.
Matching a file against itself proves the index stores bytes; the epic's
acceptance criterion is that an Administrator loads a range and a Scan
submitted in the same session returns it.

Nothing here rebuilds, reindexes, vacuums or analyses anything between the
stream closing and the search, and that absence is the assertion.
"""

from __future__ import annotations

import io
import json
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

BULK_UPLOAD = "/admin/tiles/bulk"
LOGIN = "/auth/login"

pytestmark = pytest.mark.skipif(
    not pipeline.MODEL_PATH.exists(),
    reason="model not downloaded; run `make model`",
)

#: Edge length of a generated reference. `test_edited_tile_searchable.py`'s
#: value, and for its reason: large enough that the augmented crops (25-60% of
#: the short edge) still carry structure at 224px input.
TILE_SIZE = 384


def a_tile(seed: int) -> Image.Image:
    """A tile surface with visible structure. The sibling suites' fixture.

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


def manifest(rows: list[tuple[str, str]]) -> bytes:
    """A CSV naming `(file, code)` pairs, all in one Size and Category."""
    lines = ["file,code,size,category"]
    lines.extend(f"{name},{code},45X90,POLISH" for name, code in rows)
    return ("\n".join(lines) + "\n").encode("utf-8")


def upload(client: TestClient, pairs: list[tuple[str, str, Image.Image]]) -> list[dict[str, Any]]:
    """Run one batch and return its report lines."""
    files: list[tuple[str, tuple[str, bytes, str]]] = [
        (
            "manifest",
            ("codes.csv", manifest([(name, code) for name, code, _ in pairs]), "text/csv"),
        )
    ]
    files.extend(("images", (name, as_upload(image), "image/jpeg")) for name, _, image in pairs)

    response = client.post(BULK_UPLOAD, files=files)
    assert response.status_code == 200, response.text
    return [json.loads(line) for line in response.text.splitlines() if line.strip()]


def scores(conn: psycopg.Connection, query: Image.Image) -> dict[str, float]:
    return {
        candidate.code: candidate.score
        for candidate in catalogue.find_candidates(conn, query, limit=10)
    }


def test_every_row_of_a_batch_is_a_candidate_the_moment_the_stream_closes(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser
) -> None:
    sign_in_as_administrator(client, make_user)
    references = {
        "RP.CMA.0001DJ.SM.0T": a_tile(41),
        "RP.CMA.0002DJ.SM.0T": a_tile(42),
        "RP.CMA.0003DJ.SM.0T": a_tile(43),
    }

    report = upload(
        client,
        [(f"{index}.jpg", code, image) for index, (code, image) in enumerate(references.items())],
    )
    assert [line["status"] for line in report if line["kind"] == "row"] == ["created"] * 3
    # Deliberately nothing here. No REINDEX, no VACUUM, no ANALYZE, no restart,
    # and no ingestion step an operator would have to remember to run.

    for code, reference in references.items():
        candidates = catalogue.find_candidates(conn, a_photograph_of(reference))

        # The Tile this photograph is of, ranked first among all three — not
        # merely present, which a three-row catalogue would give for free.
        assert candidates[0].code == code, [c.code for c in candidates]


def test_the_middle_row_of_a_batch_is_findable_like_any_other(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser
) -> None:
    # Named separately because a batch has a shape a single add does not: the
    # first row opens the generation and the last one closes the stream, and a
    # row in between is the one that would be lost by a handler that wrote its
    # embeddings against the wrong generation or deferred them to a flush.
    sign_in_as_administrator(client, make_user)
    middle = a_tile(51)

    upload(
        client,
        [
            ("first.jpg", "RP.CMA.0010DJ.SM.0T", a_tile(50)),
            ("second.jpg", "RP.CMA.0011DJ.SM.0T", middle),
            ("third.jpg", "RP.CMA.0012DJ.SM.0T", a_tile(52)),
        ],
    )

    found = scores(conn, a_photograph_of(middle))

    assert max(found, key=lambda code: found[code]) == "RP.CMA.0011DJ.SM.0T"


def test_a_flagged_row_is_searchable_exactly_like_a_created_one(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser
) -> None:
    # AD-18: a flag is follow-up, not a lesser kind of Tile. A row filed under
    # the `UNKNOWN` Category is in the index on the same terms as any other,
    # and a handler that held flagged rows back — or wrote them somewhere to be
    # reviewed first — would pass the report tests and fail this one.
    sign_in_as_administrator(client, make_user)
    unknown = a_tile(61)
    sheet = b"file,code,size\nflagged.jpg,RC-001-OHA-156-MA-J2,45X90\n"

    response = client.post(
        BULK_UPLOAD,
        files=[
            ("manifest", ("codes.csv", sheet, "text/csv")),
            ("images", ("flagged.jpg", as_upload(unknown), "image/jpeg")),
        ],
    )
    assert response.status_code == 200, response.text
    # `[1]`, not `[0]`: the report opens with the `start` line carrying the
    # total, and the rows follow it.
    line = json.loads(response.text.splitlines()[1])
    assert line["status"] == "flagged"
    assert sorted(line["flags"]) == ["unknown_category", "unknown_face_number"]

    candidates = catalogue.find_candidates(conn, a_photograph_of(unknown))

    assert [candidate.code for candidate in candidates] == ["RC-001-OHA-156-MA-J2"]
    # The groupings ride along unchanged — the Category is the sentinel and the
    # trailing number is absent, and neither is what the search matched on.
    assert candidates[0].category == "UNKNOWN"
    assert candidates[0].face_number is None


def test_a_failed_row_leaves_no_way_to_reach_it_at_all(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser
) -> None:
    # The inverse, and the one that a partially-written row would break: a row
    # reported `failed` must be absent from the catalogue entirely, not present
    # with no embeddings or embedded with no Tile. Asserted through the search
    # as well as through the Code, because a row that reached the index without
    # reaching `tile` would be invisible to a `SELECT` on Code and would still
    # be scoring against every Scan.
    sign_in_as_administrator(client, make_user)
    good = a_tile(71)
    sheet = (
        b"file,code,size,category\n"
        b"good.jpg,RP.CMA.0020DJ.SM.0T,45X90,POLISH\n"
        b"broken.jpg,RP.CMA.0021DJ.SM.0T,45X90,POLISH\n"
    )

    response = client.post(
        BULK_UPLOAD,
        files=[
            ("manifest", ("codes.csv", sheet, "text/csv")),
            ("images", ("good.jpg", as_upload(good), "image/jpeg")),
            # Zero bytes, which is a defect the real source tree carries.
            ("images", ("broken.jpg", b"", "image/jpeg")),
        ],
    )
    assert response.status_code == 200, response.text
    report = [json.loads(line) for line in response.text.splitlines() if line.strip()]
    assert [line["status"] for line in report if line["kind"] == "row"] == ["created", "failed"]

    codes = {row["code"] for row in conn.execute("SELECT code FROM tile").fetchall()}
    assert codes == {"RP.CMA.0020DJ.SM.0T"}
    # Every embedding in the index belongs to the row that succeeded, so the
    # failed row is not a vector competing for a Candidate slot under a Code
    # nothing holds.
    found = scores(conn, a_photograph_of(good))
    assert set(found) == {"RP.CMA.0020DJ.SM.0T"}


def test_a_bulk_loaded_tile_and_a_hand_added_one_compete_on_equal_terms(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser
) -> None:
    # AD-1, from the retrieval end. If the two write paths preprocessed or
    # embedded differently, the vectors would sit in different regions and the
    # one written by the *other* path would lose to a photograph of itself —
    # which is exactly the silent accuracy loss AD-1 exists to prevent, and
    # exactly what no test of either path alone can see.
    sign_in_as_administrator(client, make_user)
    by_hand, in_bulk = a_tile(81), a_tile(82)

    added = client.post(
        "/admin/tiles",
        data={"code": "BY-HAND", "size": "45X90", "category": "POLISH"},
        files=[("images", ("hand.jpg", as_upload(by_hand), "image/jpeg"))],
    )
    assert added.status_code == 201, added.text
    upload(client, [("bulk.jpg", "IN-BULK", in_bulk)])

    assert max(scores(conn, a_photograph_of(by_hand)).items(), key=lambda p: p[1])[0] == "BY-HAND"
    assert max(scores(conn, a_photograph_of(in_bulk)).items(), key=lambda p: p[1])[0] == "IN-BULK"
