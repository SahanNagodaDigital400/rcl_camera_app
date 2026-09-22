"""`POST /admin/tiles/bulk` — every row of Story 2.4's I/O matrix, through the real route.

Driven against a real PostgreSQL with the shipped migrations and a real object
store, for `test_add_tile.py`'s reason: every claim here is about the seam
between them. What this file adds is the property that seam did not have to
have before — that one row's outcome is independent of every other row's.

Three groups, and they fail differently:

* **The report.** N valid pairs become N Tiles and N lines, and a failure takes
  only its own row down. A batch mixing a zero-byte file, an unreadable file, a
  duplicate Code and a row naming an image nobody uploaded still creates every
  valid row beside them.
* **The classification** (AD-18, epic context). A Category that cannot be
  recovered and a Code with no trailing number are **flags on a Tile that was
  created**, never refusals. A zero-byte or unreadable file is a **failure**.
  Two rows sharing a Size and a Category are two distinct Tiles. Conflating any
  pair of those is the defect this story exists to avoid, and none of them
  raises.
* **The pre-stream refusals.** The HTTP status is committed at the first byte,
  so a manifest that cannot be read, a batch over the row cap, a missing model
  artifact and a stale generation stamp all have to be decided *before* the
  generator yields anything. Each is asserted as an envelope **and** as the
  absence of a stream.

The tests that embed for real are marked `needs_model` and are the slow ones —
16 forward passes per image, per row. Every batch here is therefore two or
three rows: the claim is about independence between rows, and three rows make
it exactly as well as thirty.
"""

from __future__ import annotations

import csv
import io
import json
import struct
import tempfile
import zlib
from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import UUID

import numpy as np
import psycopg
import pytest
import shared_vision
from api import catalogue
from fastapi.testclient import TestClient
from PIL import Image
from shared_schema.tile import MAX_BULK_ROWS, UNKNOWN_CATEGORY
from shared_schema.user import Role
from shared_vision import pipeline

MakeUser = Callable[..., Any]
AuditRows = Callable[[psycopg.Connection], list[dict[str, object]]]

BULK_UPLOAD = "/admin/tiles/bulk"
ADD_TILE = "/admin/tiles"
LOGIN = "/auth/login"

#: A Code from each of the naming conventions the real tree holds. The first
#: yields a trailing number; the third is the dash-delimited shape that yields
#: none at all and is flagged for it.
STRUCTURED_CODE = "RP.CMA.0008DJ.SM.0T"
BARE_CODE = "1Jk"
DASHED_CODE = "RC-001-OHA-156-MA-J2"

SIZE = "45X90"
CATEGORY = "CREMA MARMOL"

needs_model = pytest.mark.skipif(
    not pipeline.MODEL_PATH.exists(),
    reason="model not downloaded; run `make model`",
)


# --- Fixtures and helpers -----------------------------------------------------


def a_tile_photograph(seed: int = 5, size: tuple[int, int] = (320, 320)) -> Image.Image:
    """A textured patch. `test_add_tile.py`'s fixture — flat colour is `featureless`."""
    rng = np.random.default_rng(seed)
    return Image.fromarray(rng.integers(0, 255, (size[1], size[0], 3), dtype=np.uint8), "RGB")


def jpeg_bytes(image: Image.Image | None = None) -> bytes:
    buf = io.BytesIO()
    (image or a_tile_photograph()).save(buf, format="JPEG", quality=92)
    return buf.getvalue()


def a_featureless_photograph() -> bytes:
    """Flat *neutral grey*, which is what FR-19's texture threshold measures.

    `test_add_tile.py` argues the colour at length and it matters here too: the
    measure is the standard deviation of the whole RGB array, so the spread
    between a tile's channels counts towards it exactly as spatial texture
    does. A flat but coloured patch — `(182, 176, 168)` measures 6.1 — sits
    above the threshold and is not flagged, however featureless it looks.
    """
    buf = io.BytesIO()
    Image.new("RGB", (320, 320), (176, 176, 176)).save(buf, format="JPEG", quality=92)
    return buf.getvalue()


def a_png_header_claiming(width: int, height: int) -> bytes:
    """A PNG whose IHDR says it is enormous and whose pixel data never arrives.

    `test_add_tile.py`'s helper, unchanged. The pixel gate reads the *header*
    and refuses before allocating anything, so the only honest way to test it is
    a file that could never be decoded at all — 400 megapixels of real image
    data is not something a test can produce, and a gate tested with a file
    small enough to decode is a gate tested after the fact.
    """

    def chunk(kind: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + kind
            + payload
            + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"\x00"))
        + chunk(b"IEND", b"")
    )


def manifest(rows: list[dict[str, str]], header: list[str] | None = None) -> bytes:
    """A CSV manifest, written the way a spreadsheet export writes one.

    Assembled by hand rather than through `csv.writer` so that a test can put a
    header in an odd case, leave a column out, or write a blank line — all of
    which are things the real sheets do and none of which a writer would let
    through.
    """
    columns = header if header is not None else ["file", "code", "size", "category"]
    lines = [",".join(columns)]
    lines.extend(",".join(row.get(column, "") for column in columns) for row in rows)
    return ("\n".join(lines) + "\n").encode("utf-8")


def sign_in(client: TestClient, account: Any) -> None:
    assert (
        client.post(LOGIN, json={"email": account.email, "password": account.password}).status_code
        == 200
    )


@pytest.fixture
def administrator(client: TestClient, make_user: MakeUser) -> Any:
    account = make_user(role=Role.ADMIN, name="Nadeesha Silva")
    sign_in(client, account)
    return account


def bulk(
    client: TestClient,
    *,
    sheet: bytes | None,
    images: list[tuple[str, bytes]],
) -> Any:
    """`POST /admin/tiles/bulk` as multipart, with the manifest part omitted when None."""
    files: list[tuple[str, tuple[str, bytes, str]]] = []
    if sheet is not None:
        files.append(("manifest", ("codes.csv", sheet, "text/csv")))
    files.extend(("images", (name, data, "image/jpeg")) for name, data in images)
    return client.post(BULK_UPLOAD, files=files)


#: A multipart boundary for the bodies assembled by hand below. Fixed rather
#: than generated: nothing here is sent over a network and a stable value makes
#: a failing assertion reproducible.
BOUNDARY = "----rocell-bulk-test-boundary"


def raw_multipart(parts: list[tuple[str, str | None, bytes]]) -> tuple[bytes, dict[str, str]]:
    """A multipart body built by hand, with `(field, filename, data)` parts.

    Needed because `httpx` will not build the two shapes below: a part carrying
    a `filename` parameter that is *empty*, and a part carrying bytes with no
    usable name. Given `("", ...)` it drops the parameter entirely, which makes
    the part an ordinary form field rather than a file — so the request is
    refused as malformed and the handler under test is never reached.

    `filename=None` omits the parameter; a string emits it, empty or not.
    """
    body = b""
    for field, filename, data in parts:
        disposition = f'form-data; name="{field}"'
        if filename is not None:
            disposition += f'; filename="{filename}"'
        body += f"--{BOUNDARY}\r\n".encode()
        body += f"Content-Disposition: {disposition}\r\n".encode()
        body += b"Content-Type: application/octet-stream\r\n\r\n"
        body += data + b"\r\n"
    body += f"--{BOUNDARY}--\r\n".encode()
    return body, {"content-type": f"multipart/form-data; boundary={BOUNDARY}"}


def lines(response: Any) -> list[dict[str, Any]]:
    """The report, parsed. One JSON object per line, and the last one is the summary."""
    parsed = [json.loads(line) for line in response.text.splitlines() if line.strip()]
    assert parsed, response.text
    return parsed


def rows_of(response: Any) -> list[dict[str, Any]]:
    return [line for line in lines(response) if line["kind"] == "row"]


def summary_of(response: Any) -> dict[str, Any]:
    closing = lines(response)[-1]
    assert closing["kind"] == "summary", closing
    return closing


def count(conn: psycopg.Connection, statement: str) -> int:
    row = conn.execute(statement).fetchone()
    assert row is not None
    return int(row["total"])


TILES = "SELECT count(*) AS total FROM tile"
IMAGES = "SELECT count(*) AS total FROM reference_image"
EMBEDDINGS = "SELECT count(*) AS total FROM reference_embedding"
SIZES = "SELECT count(*) AS total FROM tile_size"


def stored_objects(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("*") if path.is_file())


def nothing_was_written(conn: psycopg.Connection, storage_root: Path) -> None:
    for statement in (TILES, IMAGES, EMBEDDINGS):
        assert count(conn, statement) == 0, statement
    assert stored_objects(storage_root) == []


THREE_ROWS = [
    {"file": "a.jpg", "code": STRUCTURED_CODE, "size": SIZE, "category": CATEGORY},
    {"file": "b.jpg", "code": "RP.CMA.0009DJ.SM.0T", "size": SIZE, "category": CATEGORY},
    {"file": "c.jpg", "code": "RP.CMA.0010DJ.SM.0T", "size": SIZE, "category": CATEGORY},
]

THREE_IMAGES = [
    ("a.jpg", jpeg_bytes(a_tile_photograph(1))),
    ("b.jpg", jpeg_bytes(a_tile_photograph(2))),
    ("c.jpg", jpeg_bytes(a_tile_photograph(3))),
]


# --- The happy path -----------------------------------------------------------


@needs_model
def test_n_valid_pairs_become_n_tiles_and_n_lines(
    client: TestClient,
    conn: psycopg.Connection,
    administrator: Any,
    storage_root: Path,
) -> None:
    response = bulk(client, sheet=manifest(THREE_ROWS), images=THREE_IMAGES)

    assert response.status_code == 200, response.text
    # NDJSON, not JSON: one object per line, flushed as each row finishes. A
    # JSON array could only be parsed once it was closed, which is the whole
    # thing EXPERIENCE.md:94 rules out.
    assert response.headers["content-type"].startswith(catalogue.NDJSON)
    # Catalogue data on the wire, like every other authenticated response.
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"

    report = rows_of(response)
    assert [line["status"] for line in report] == ["created"] * 3
    assert [line["row"] for line in report] == [1, 2, 3]
    assert [line["file"] for line in report] == ["a.jpg", "b.jpg", "c.jpg"]
    assert [line["code"] for line in report] == [row["code"] for row in THREE_ROWS]
    assert all(line["flags"] == [] and line["error"] is None for line in report)
    assert all(line["tile_id"] is not None for line in report)

    assert summary_of(response) == {"kind": "summary", "created": 3, "flagged": 0, "failed": 0}

    assert count(conn, TILES) == 3
    assert count(conn, IMAGES) == 3
    # AD-13: sixteen views per image, as separate rows, never pooled.
    assert count(conn, EMBEDDINGS) == 3 * shared_vision.VIEWS_PER_IMAGE == 48
    # Two objects per image: the retained source and AD-17's capped derivative.
    assert len(stored_objects(storage_root)) == 6


@needs_model
def test_the_rows_arrive_as_they_complete_rather_than_at_the_end(
    client: TestClient, administrator: Any
) -> None:
    # EXPERIENCE.md:94, at the surface this suite can reach: the body is NDJSON,
    # one object per line, in completion order, with the rows before the
    # summary — so a reader that consumes it a line at a time has rows to paint
    # before the batch ends.
    #
    # **What this cannot see is the timing.** `TestClient` runs the app in a
    # portal and the whole body may be produced before the first read returns,
    # so a "collect the rows and return them" refactor would leave this green.
    # The per-chunk arrival is held one layer out, by `bulk-upload.test.tsx`,
    # which feeds `apiStream` a real `ReadableStream` a line at a time and
    # asserts *between* the pushes.
    files: list[tuple[str, tuple[str, bytes, str]]] = [
        ("manifest", ("codes.csv", manifest(THREE_ROWS[:2]), "text/csv"))
    ]
    files.extend(("images", (name, data, "image/jpeg")) for name, data in THREE_IMAGES[:2])

    seen: list[str] = []
    with client.stream("POST", BULK_UPLOAD, files=files) as response:
        assert response.status_code == 200
        for line in response.iter_lines():
            if line.strip():
                seen.append(json.loads(line)["kind"])
                # The first thing on the stream is a row, not the summary:
                # the report is written as the batch runs rather than
                # composed from its result.
                if len(seen) == 1:
                    assert seen == ["row"]

    assert seen == ["row", "row", "summary"]


@needs_model
def test_a_flagged_row_is_a_created_row_and_says_so(
    client: TestClient, conn: psycopg.Connection, administrator: Any
) -> None:
    # The three flags, each on its own row and all three in one batch. Every
    # one of these is a Tile in the catalogue: AD-18 and the epic context are
    # explicit that an unrecoverable Category or a missing trailing number is
    # "not an error — index it with an explicit unknown marker and flag it".
    rows = [
        # No Category column value at all.
        {"file": "a.jpg", "code": STRUCTURED_CODE, "size": SIZE, "category": ""},
        # A Code the four patterns cannot read a trailing number from.
        {"file": "b.jpg", "code": DASHED_CODE, "size": SIZE, "category": CATEGORY},
        # A flat image, below FR-19's texture threshold.
        {"file": "c.jpg", "code": BARE_CODE, "size": SIZE, "category": CATEGORY},
    ]
    images = [
        ("a.jpg", jpeg_bytes(a_tile_photograph(1))),
        ("b.jpg", jpeg_bytes(a_tile_photograph(2))),
        ("c.jpg", a_featureless_photograph()),
    ]

    response = bulk(client, sheet=manifest(rows), images=images)

    report = rows_of(response)
    assert [line["status"] for line in report] == ["flagged"] * 3
    assert [line["flags"] for line in report] == [
        ["unknown_category"],
        ["unknown_face_number"],
        ["low_quality_image"],
    ]
    assert all(line["tile_id"] is not None and line["error"] is None for line in report)
    assert summary_of(response)["flagged"] == 3

    # All three are really in the catalogue, with the marker each flag names.
    assert count(conn, TILES) == 3
    unknown = conn.execute(
        "SELECT t.code, t.face_number, c.name AS category FROM tile t "
        "LEFT JOIN tile_category c ON c.id = t.category_id ORDER BY t.code"
    ).fetchall()
    filed = {row["code"]: row for row in unknown}
    assert filed[STRUCTURED_CODE]["category"] == UNKNOWN_CATEGORY
    assert filed[DASHED_CODE]["face_number"] is None
    # The other two recovered one, which is what makes the flag above a fact
    # about that Code rather than about the column never being written.
    assert filed[STRUCTURED_CODE]["face_number"] == "8"
    assert filed[BARE_CODE]["face_number"] == "1"

    featureless = conn.execute(
        "SELECT featureless FROM reference_image ri JOIN tile t ON t.id = ri.tile_id "
        "WHERE t.code = %s",
        (BARE_CODE,),
    ).fetchone()
    assert featureless is not None and featureless["featureless"] is True


@needs_model
def test_one_row_can_carry_several_flags_in_a_stable_order(
    client: TestClient, administrator: Any
) -> None:
    # A blank Category *and* a Code with no trailing number. Both on one line,
    # in the order the handler declares rather than in whichever order a set
    # happened to iterate — a screen rendering two flags must render them the
    # same way twice.
    rows = [{"file": "a.jpg", "code": DASHED_CODE, "size": SIZE, "category": "  "}]

    report = rows_of(bulk(client, sheet=manifest(rows), images=[THREE_IMAGES[0]]))

    assert len(report) == 1
    assert report[0]["status"] == "flagged"
    assert report[0]["flags"] == ["unknown_category", "unknown_face_number"]


@needs_model
def test_a_category_cell_spelling_the_sentinel_is_flagged_like_a_blank_one(
    client: TestClient, conn: psycopg.Connection, administrator: Any
) -> None:
    # A sheet that writes `UNKNOWN` in the column says the same thing a blank
    # cell says: this Tile has no recoverable Category. Both are filed under
    # the sentinel, so both are follow-up — flagging only the blank one would
    # let a Tile land in `UNKNOWN` and be reported as a clean success, which is
    # the one outcome the flag exists to prevent.
    rows = [{"file": "a.jpg", "code": STRUCTURED_CODE, "size": SIZE, "category": "unknown"}]

    response = bulk(client, sheet=manifest(rows), images=[("a.jpg", jpeg_bytes())])

    report = rows_of(response)
    assert report[0]["status"] == "flagged"
    assert report[0]["flags"] == ["unknown_category"]
    assert report[0]["tile_id"] is not None
    filed = conn.execute(
        "SELECT c.name AS category FROM tile t "
        "LEFT JOIN tile_category c ON c.id = t.category_id WHERE t.code = %s",
        (STRUCTURED_CODE,),
    ).fetchone()
    assert filed is not None and filed["category"] == UNKNOWN_CATEGORY


@needs_model
def test_two_rows_sharing_a_size_and_category_are_two_distinct_tiles(
    client: TestClient, conn: psycopg.Connection, administrator: Any
) -> None:
    # AD-18, and the failure mode the epic names directly: "two rows sharing a
    # Size and Category are two distinct Tiles — never merged, deduplicated, or
    # reported as a conflict". The 22 files in `45X90/POLISH` are 22 tiles.
    rows = THREE_ROWS[:2]

    response = bulk(client, sheet=manifest(rows), images=THREE_IMAGES[:2])

    assert [line["status"] for line in rows_of(response)] == ["created", "created"]
    assert count(conn, TILES) == 2
    # One `tile_size` row and one `tile_category` row between them: the
    # groupings are shared lookups, resolved create-if-missing, and a second
    # row for the same name would be the near-duplicate the shared resolver
    # exists to prevent.
    assert count(conn, SIZES) == 1
    shared = conn.execute(
        "SELECT count(DISTINCT size_id) AS sizes, count(DISTINCT category_id) AS categories "
        "FROM tile"
    ).fetchone()
    assert shared is not None
    assert shared["sizes"] == 1 and shared["categories"] == 1


@needs_model
def test_the_header_is_matched_case_and_whitespace_insensitively(
    client: TestClient, administrator: Any
) -> None:
    # What a hand-maintained sheet actually contains. Refusing `File ` would be
    # refusing the data this endpoint exists to load.
    sheet = manifest(
        [{"File ": "a.jpg", "CODE": STRUCTURED_CODE, " Size": SIZE, "Category": CATEGORY}],
        header=["File ", "CODE", " Size", "Category"],
    )

    report = rows_of(bulk(client, sheet=sheet, images=[THREE_IMAGES[0]]))

    assert [line["status"] for line in report] == ["created"]


@needs_model
def test_a_column_the_endpoint_does_not_know_is_ignored_rather_than_refused(
    client: TestClient, administrator: Any
) -> None:
    # A real export carries notes, counts and a column somebody added last
    # week. Refusing the file over one of them would refuse the whole range.
    sheet = manifest(
        [
            {
                "file": "a.jpg",
                "code": STRUCTURED_CODE,
                "size": SIZE,
                "category": CATEGORY,
                "notes": "re-shoot in March",
            }
        ],
        header=["file", "code", "size", "category", "notes"],
    )

    assert [
        line["status"] for line in rows_of(bulk(client, sheet=sheet, images=[THREE_IMAGES[0]]))
    ] == ["created"]


@needs_model
def test_a_manifest_with_no_category_column_files_every_row_under_the_sentinel(
    client: TestClient, conn: psycopg.Connection, administrator: Any
) -> None:
    # The column is optional, and its absence is the same fact as a blank cell.
    sheet = manifest(
        [{"file": "a.jpg", "code": STRUCTURED_CODE, "size": SIZE}],
        header=["file", "code", "size"],
    )

    report = rows_of(bulk(client, sheet=sheet, images=[THREE_IMAGES[0]]))

    assert report[0]["status"] == "flagged"
    assert report[0]["flags"] == ["unknown_category"]
    filed = conn.execute(
        "SELECT c.name AS category FROM tile t LEFT JOIN tile_category c ON c.id = t.category_id"
    ).fetchone()
    assert filed is not None and filed["category"] == UNKNOWN_CATEGORY


# --- Per-row failures ---------------------------------------------------------


@needs_model
def test_a_failure_takes_only_its_own_row_down(
    client: TestClient,
    conn: psycopg.Connection,
    administrator: Any,
    storage_root: Path,
) -> None:
    # The acceptance criterion in one batch: a zero-byte file, an unreadable
    # file, a duplicate Code and a row naming an image nobody uploaded, each
    # reported on its own line with its own code, with every valid row beside
    # them still created.
    rows = [
        {"file": "good.jpg", "code": STRUCTURED_CODE, "size": SIZE, "category": CATEGORY},
        {"file": "empty.jpg", "code": "RP.CMA.0011DJ.SM.0T", "size": SIZE, "category": CATEGORY},
        {"file": "text.jpg", "code": "RP.CMA.0012DJ.SM.0T", "size": SIZE, "category": CATEGORY},
        # The same Code as row 1, which the first row has already claimed by
        # the time this one is processed.
        {"file": "twin.jpg", "code": STRUCTURED_CODE, "size": SIZE, "category": CATEGORY},
        {"file": "absent.jpg", "code": "RP.CMA.0013DJ.SM.0T", "size": SIZE, "category": CATEGORY},
        {
            "file": "also-good.jpg",
            "code": "RP.CMA.0014DJ.SM.0T",
            "size": SIZE,
            "category": CATEGORY,
        },
    ]
    images = [
        ("good.jpg", jpeg_bytes(a_tile_photograph(1))),
        # Zero bytes. Two of these are in the real source tree (`poc/README.md`).
        ("empty.jpg", b""),
        # A renamed text file: the name says JPEG and the content does not, and
        # content is what decides (AGENTS.md Policy).
        ("text.jpg", b"this is not an image, whatever the extension says"),
        ("twin.jpg", jpeg_bytes(a_tile_photograph(4))),
        ("also-good.jpg", jpeg_bytes(a_tile_photograph(5))),
    ]

    response = bulk(client, sheet=manifest(rows), images=images)

    report = rows_of(response)
    assert [line["status"] for line in report] == [
        "created",
        "failed",
        "failed",
        "failed",
        "failed",
        "created",
    ]
    assert [None if line["error"] is None else line["error"]["code"] for line in report] == [
        None,
        "unreadable_image",
        "unreadable_image",
        "code_already_exists",
        "image_not_paired",
        None,
    ]
    # Every failed line carries a sentence, not only a code: the screen renders
    # the message and an empty one is a row that says nothing happened.
    assert all(line["error"]["message"].strip() for line in report if line["error"] is not None)
    # The unpaired row's sentence names which file is missing, because that is
    # the one thing the Administrator has to go and find.
    assert "absent.jpg" in report[4]["error"]["message"]

    assert summary_of(response) == {"kind": "summary", "created": 2, "flagged": 0, "failed": 4}

    # Nothing was written for any of the four, and the two valid rows are whole.
    assert count(conn, TILES) == 2
    assert count(conn, IMAGES) == 2
    assert count(conn, EMBEDDINGS) == 32
    assert len(stored_objects(storage_root)) == 4
    codes = {row["code"] for row in conn.execute("SELECT code FROM tile").fetchall()}
    assert codes == {STRUCTURED_CODE, "RP.CMA.0014DJ.SM.0T"}


@needs_model
def test_a_duplicate_code_leaves_the_existing_tile_and_its_objects_alone(
    client: TestClient,
    conn: psycopg.Connection,
    administrator: Any,
    storage_root: Path,
) -> None:
    # The Code is the identity (AD-18), so a row naming one already in the
    # catalogue is a genuine conflict — and the existing Tile must come through
    # it untouched, bytes included.
    first = client.post(
        ADD_TILE,
        data={"code": STRUCTURED_CODE, "size": SIZE, "category": CATEGORY},
        files=[("images", ("reference.jpg", jpeg_bytes(a_tile_photograph(7)), "image/jpeg"))],
    )
    assert first.status_code == 201, first.text
    before = {path: path.read_bytes() for path in stored_objects(storage_root)}

    rows = [{"file": "a.jpg", "code": STRUCTURED_CODE, "size": SIZE, "category": CATEGORY}]
    report = rows_of(bulk(client, sheet=manifest(rows), images=[THREE_IMAGES[0]]))

    assert report[0]["status"] == "failed"
    assert report[0]["error"]["code"] == "code_already_exists"
    assert report[0]["tile_id"] is None
    assert count(conn, TILES) == 1
    assert count(conn, EMBEDDINGS) == 16
    # The same objects, byte for byte: the refused row wrote none of its own
    # and removed none of the survivor's.
    assert {path: path.read_bytes() for path in stored_objects(storage_root)} == before


@needs_model
def test_a_duplicate_code_inside_one_batch_is_decided_by_the_unique_index(
    client: TestClient, conn: psycopg.Connection, administrator: Any
) -> None:
    # The pre-flight `SELECT` is an optimisation; `tile_code_key` is the
    # decision. Both rows are in one batch, so the first commits and the second
    # sees it — through whichever of the two catches it.
    rows = [
        {"file": "a.jpg", "code": STRUCTURED_CODE, "size": SIZE, "category": CATEGORY},
        {"file": "b.jpg", "code": STRUCTURED_CODE, "size": SIZE, "category": CATEGORY},
    ]

    report = rows_of(bulk(client, sheet=manifest(rows), images=THREE_IMAGES[:2]))

    assert [line["status"] for line in report] == ["created", "failed"]
    assert report[1]["error"]["code"] == "code_already_exists"
    assert count(conn, TILES) == 1


@needs_model
def test_an_oversized_file_is_refused_without_the_rest_of_it_being_read(
    client: TestClient,
    conn: psycopg.Connection,
    administrator: Any,
    storage_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The real ceiling is 128 MB, which is not a file a test can produce without
    # spending the transfer. Lowered to sit exactly on the smaller of these two
    # files, so the bound exercised is the handler's own rather than a smaller
    # one written for the occasion — and so the row *under* the ceiling proves
    # the bound is a ceiling and not a floor.
    small = jpeg_bytes(a_tile_photograph(1, (64, 64)))
    big = jpeg_bytes(a_tile_photograph(8, (640, 640)))
    assert len(small) < len(big), "the fixture no longer straddles the bound"
    monkeypatch.setattr(catalogue, "MAX_IMAGE_BYTES", len(small))

    rows = [
        {"file": "big.jpg", "code": STRUCTURED_CODE, "size": SIZE, "category": CATEGORY},
        {"file": "small.jpg", "code": "RP.CMA.0009DJ.SM.0T", "size": SIZE, "category": CATEGORY},
    ]

    report = rows_of(
        bulk(client, sheet=manifest(rows), images=[("big.jpg", big), ("small.jpg", small)])
    )

    assert report[0]["status"] == "failed"
    assert report[0]["error"]["code"] == "image_too_large"
    # And the next row proceeded, which is the whole claim about a bounded read
    # in a batch: one oversized file does not end the upload.
    assert report[1]["status"] == "created"
    assert count(conn, TILES) == 1


@needs_model
def test_an_image_claiming_more_pixels_than_the_ceiling_fails_its_own_row(
    client: TestClient, conn: psycopg.Connection, administrator: Any
) -> None:
    # The other half of the oversized row. A press file is refused for its
    # *dimensions* as well as for its byte count, and the two are different
    # gates in different places — the byte ceiling stops the copy, the pixel
    # ceiling is read off the header inside `_accept_bytes`. The real
    # catalogue holds images at 19276x9638, so this is the half it actually
    # meets.
    rows = [
        {"file": "bomb.png", "code": STRUCTURED_CODE, "size": SIZE, "category": CATEGORY},
        {"file": "ok.jpg", "code": BARE_CODE, "size": SIZE, "category": CATEGORY},
    ]
    images = [
        ("bomb.png", a_png_header_claiming(20_000, 20_001)),
        ("ok.jpg", jpeg_bytes()),
    ]

    report = rows_of(bulk(client, sheet=manifest(rows), images=images))

    assert report[0]["status"] == "failed"
    assert report[0]["error"]["code"] == "image_too_large"
    # And the batch went on, which is the claim: a bomb takes its own row.
    assert report[1]["status"] == "created"
    assert count(conn, TILES) == 1


@needs_model
def test_a_sheet_written_on_windows_pairs_on_the_same_base_name(
    client: TestClient, conn: psycopg.Connection, administrator: Any
) -> None:
    # The `file` cell carries a path because the sheet was built from a
    # directory listing, and the listing was taken on a Windows machine. The
    # server splits on `/`, so an unfolded backslash form would pair with
    # nothing and cost two report lines — the row refused and its image
    # reported unmatched — for a difference the Administrator cannot see.
    rows = [
        {
            "file": "45X90\\POLISH\\a.jpg",
            "code": STRUCTURED_CODE,
            "size": SIZE,
            "category": CATEGORY,
        }
    ]

    response = bulk(client, sheet=manifest(rows), images=[("a.jpg", jpeg_bytes())])

    report = rows_of(response)
    assert [line["status"] for line in report] == ["created"]
    assert count(conn, TILES) == 1


@needs_model
def test_two_rows_naming_one_upload_are_two_tiles_and_no_orphan(
    client: TestClient, conn: psycopg.Connection, administrator: Any
) -> None:
    # Nothing is merged and nothing is deduplicated (AD-18). Two Codes against
    # one image is a sheet the Administrator wrote that way, and the answer is
    # two Tiles — not one, and not a conflict. The upload is named by a row, so
    # it is not an orphan either: a trailing `image_unmatched` line here would
    # report a file that was in fact used.
    rows = [
        {"file": "a.jpg", "code": STRUCTURED_CODE, "size": SIZE, "category": CATEGORY},
        {"file": "a.jpg", "code": BARE_CODE, "size": SIZE, "category": CATEGORY},
    ]

    response = bulk(client, sheet=manifest(rows), images=[("a.jpg", jpeg_bytes())])

    report = rows_of(response)
    assert [line["status"] for line in report] == ["created", "created"]
    closing = summary_of(response)
    assert (closing["created"], closing["flagged"], closing["failed"]) == (2, 0, 0)
    assert count(conn, TILES) == 2


@needs_model
def test_two_uploads_sharing_a_name_refuse_the_row_rather_than_guessing(
    client: TestClient, conn: psycopg.Connection, administrator: Any
) -> None:
    # Picking one of the two would put the wrong image under a Code with
    # nothing raised — a tile that scans to somebody else's reference.
    rows = [{"file": "a.jpg", "code": STRUCTURED_CODE, "size": SIZE, "category": CATEGORY}]
    images = [
        ("a.jpg", jpeg_bytes(a_tile_photograph(1))),
        ("a.jpg", jpeg_bytes(a_tile_photograph(2))),
    ]

    report = rows_of(bulk(client, sheet=manifest(rows), images=images))

    assert report[0]["status"] == "failed"
    assert report[0]["error"]["code"] == "image_not_paired"
    assert "a.jpg" in report[0]["error"]["message"]
    assert count(conn, TILES) == 0


@needs_model
def test_an_image_no_row_names_is_reported_rather_than_silently_ignored(
    client: TestClient, conn: psycopg.Connection, administrator: Any
) -> None:
    # An upload that travelled and was not indexed is a tile the Administrator
    # believes is in the catalogue. The line is keyed by the file name and
    # carries no Code, because no row gave it one.
    rows = [{"file": "a.jpg", "code": STRUCTURED_CODE, "size": SIZE, "category": CATEGORY}]
    images = [THREE_IMAGES[0], ("stray.jpg", jpeg_bytes(a_tile_photograph(9)))]

    response = bulk(client, sheet=manifest(rows), images=images)
    report = rows_of(response)

    assert [line["status"] for line in report] == ["created", "failed"]
    assert report[1]["file"] == "stray.jpg"
    assert report[1]["code"] is None
    assert report[1]["error"]["code"] == "image_unmatched"
    # **No row number**, because there is no row. `row` is a position in the
    # sheet the Administrator is holding, and counting on past the manifest's
    # end would send them to row 2 of a sheet that has one.
    assert report[1]["row"] is None
    assert summary_of(response) == {"kind": "summary", "created": 1, "flagged": 0, "failed": 1}
    assert count(conn, TILES) == 1


# `needs_model` although nothing here embeds: the route pre-flights the
# artifact before it opens the stream, so a batch that would fail every row
# for a reason of its own is still refused as `matching_unavailable` on a
# machine without it. The check is the point; this mark is its consequence.
@pytest.mark.parametrize(
    ("cell", "expected"),
    [
        ({"code": ""}, "invalid_code"),
        ({"code": "with\x00nul"}, "invalid_code"),
        ({"size": ""}, "invalid_size"),
        ({"size": "x" * 200}, "invalid_size"),
        ({"category": "y" * 300}, "invalid_category"),
    ],
)
@needs_model
def test_a_cell_the_product_will_not_store_fails_its_own_row(
    client: TestClient,
    conn: psycopg.Connection,
    administrator: Any,
    storage_root: Path,
    cell: dict[str, str],
    expected: str,
) -> None:
    # Every one of these is refused before a byte is decoded, which is the
    # ordering the handler is written for and is what keeps a blank Size from
    # costing sixteen forward passes. The mark above is still required: the
    # route pre-flights the model artifact before it opens the stream, so
    # without it there is no stream to read a row out of.
    row = {"file": "a.jpg", "code": STRUCTURED_CODE, "size": SIZE, "category": CATEGORY, **cell}

    report = rows_of(bulk(client, sheet=manifest([row]), images=[THREE_IMAGES[0]]))

    assert report[0]["status"] == "failed"
    assert report[0]["error"]["code"] == expected
    nothing_was_written(conn, storage_root)


@needs_model
def test_a_row_naming_no_file_at_all_is_told_so(
    client: TestClient, conn: psycopg.Connection, administrator: Any, storage_root: Path
) -> None:
    row = {"file": "", "code": STRUCTURED_CODE, "size": SIZE, "category": CATEGORY}

    report = rows_of(bulk(client, sheet=manifest([row]), images=[THREE_IMAGES[0]]))

    assert report[0]["error"]["code"] == "image_not_paired"
    # The sentence is about the row rather than about a file called nothing.
    assert report[0]["error"]["message"] == catalogue.NO_FILE_NAMED
    nothing_was_written(conn, storage_root)


@needs_model
def test_an_unexpected_failure_takes_one_row_and_never_the_stream(
    client: TestClient,
    conn: psycopg.Connection,
    administrator: Any,
    storage_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A row raising something this handler cannot explain. The line says
    # `row_failed` with a fixed sentence that leaks nothing — an exception's
    # text can carry a path, a query fragment or a credential, and this
    # response goes to the browser — and the batch continues.
    real = catalogue._bulk_row
    calls = {"n": 0}

    def sometimes_broken(*args: Any, **kwargs: Any) -> Any:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("postgresql://rocell:hunter2@db.internal/rocell is unreachable")
        return real(*args, **kwargs)

    monkeypatch.setattr(catalogue, "_bulk_row", sometimes_broken)
    rows = [
        {"file": "a.jpg", "code": STRUCTURED_CODE, "size": SIZE, "category": CATEGORY},
        {"file": "b.jpg", "code": "", "size": SIZE, "category": CATEGORY},
    ]

    response = bulk(client, sheet=manifest(rows), images=THREE_IMAGES[:2])
    report = rows_of(response)

    assert response.status_code == 200
    assert report[0]["status"] == "failed"
    assert report[0]["error"]["code"] == "row_failed"
    assert report[0]["error"]["message"] == catalogue.ROW_FAILED_MESSAGE
    assert "hunter2" not in response.text
    assert "postgresql" not in response.text
    # The stream was not torn down: the second row was still processed and the
    # summary still closed the report.
    assert len(report) == 2
    assert summary_of(response)["failed"] == 2
    nothing_was_written(conn, storage_root)


# --- The pre-stream refusals --------------------------------------------------
# Each of these is decided while a real envelope under a 4xx or 5xx is still
# possible, which is the whole reason they are checked where they are. Every
# one asserts the *absence* of a stream as well as the status: a handler that
# opened the stream and then reported the same condition as a row would answer
# `200` and look fine to a test reading only the body.


def refusal(response: Any) -> dict[str, str]:
    body = response.json()
    assert set(body) == {"error"}
    assert set(body["error"]) == {"code", "message"}
    error: dict[str, str] = body["error"]
    return error


@pytest.mark.parametrize(
    "sheet",
    [
        # No part at all.
        None,
        # A part with no bytes in it.
        b"",
        # A header and nothing under it.
        b"file,code,size,category\n",
        # A workbook rather than a CSV: `.xlsx` is a ZIP archive, and its first
        # bytes do not decode as text.
        b"PK\x03\x04\x14\x00\x00\x00\x08\x00",
        # A CSV without the columns the rows are read from.
        b"filename,identifier\na.jpg,RP.CMA.0008DJ.SM.0T\n",
    ],
)
def test_a_manifest_that_is_not_one_is_refused_with_no_stream(
    client: TestClient,
    conn: psycopg.Connection,
    administrator: Any,
    storage_root: Path,
    sheet: bytes | None,
) -> None:
    response = bulk(client, sheet=sheet, images=[THREE_IMAGES[0]])

    assert response.status_code == 422, response.text
    assert refusal(response)["code"] == "invalid_manifest"
    # An envelope, not a report: nothing on this response is a row.
    assert '"kind"' not in response.text
    assert response.headers["cache-control"] == "no-store"
    nothing_was_written(conn, storage_root)


def test_the_refusal_for_a_workbook_names_the_fix_rather_than_the_problem(
    client: TestClient, administrator: Any
) -> None:
    # EXPERIENCE.md's register: somebody who attached a workbook needs to know
    # to export it, not that the bytes did not decode.
    response = bulk(client, sheet=b"PK\x03\x04\x14\x00", images=[])

    assert "CSV" in refusal(response)["message"]


def test_a_manifest_over_the_row_cap_is_refused_before_anything_is_spooled(
    client: TestClient, conn: psycopg.Connection, administrator: Any, storage_root: Path
) -> None:
    # **Before anything is *spooled*, not before anything is read.** Starlette
    # has parsed the whole multipart body before this handler is entered, so by
    # the time the cap is checked the images have travelled and are in
    # Starlette's own spool. What the check comes before is this handler's copy
    # of them, the decode and the sixteen forward passes — and the honest
    # statement of what a pre-stream refusal buys is that nothing of ours was
    # written, which is what the assertion below makes.
    rows = [
        {"file": f"{n}.jpg", "code": f"RP.CMA.{n:04d}DJ.SM.0T", "size": SIZE, "category": CATEGORY}
        for n in range(MAX_BULK_ROWS + 1)
    ]

    response = bulk(client, sheet=manifest(rows), images=[THREE_IMAGES[0]])

    assert response.status_code == 422
    assert refusal(response)["code"] == "too_many_rows"
    # The number is in the sentence: an Administrator holding a longer sheet
    # needs to know where to split it.
    assert str(MAX_BULK_ROWS) in refusal(response)["message"]
    nothing_was_written(conn, storage_root)


@needs_model
def test_a_manifest_exactly_at_the_row_cap_is_not_refused(
    client: TestClient, administrator: Any
) -> None:
    # The boundary, from the other side. Every row fails for want of an image —
    # this is about the cap, not about the batch — and a refusal here would be
    # the off-by-one that makes the bound one smaller than it says.
    rows = [
        {"file": f"{n}.jpg", "code": f"RP.CMA.{n:04d}DJ.SM.0T", "size": SIZE, "category": CATEGORY}
        for n in range(MAX_BULK_ROWS)
    ]

    response = bulk(client, sheet=manifest(rows), images=[])

    assert response.status_code == 200
    assert len(rows_of(response)) == MAX_BULK_ROWS


@needs_model
def test_a_blank_line_in_the_sheet_is_not_a_row(client: TestClient, administrator: Any) -> None:
    # A trailing newline and the empty line a hand-edited sheet leaves behind
    # are not tiles the Administrator has to be told about.
    sheet = b"file,code,size,category\na.jpg,RP.CMA.0008DJ.SM.0T,45X90,CREMA MARMOL\n,,,\n\n"

    response = bulk(client, sheet=sheet, images=[])

    assert len(rows_of(response)) == 1


def test_a_server_with_no_model_artifact_refuses_the_whole_batch(
    client: TestClient,
    conn: psycopg.Connection,
    administrator: Any,
    storage_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Pre-flighted rather than discovered on row 1, because otherwise every row
    # of a hundred fails identically — a report saying one thing that belongs
    # in an envelope.
    monkeypatch.setattr(shared_vision, "MODEL_PATH", tmp_path / "absent.onnx")

    response = bulk(client, sheet=manifest(THREE_ROWS), images=THREE_IMAGES)

    assert response.status_code == 503
    assert refusal(response)["code"] == "matching_unavailable"
    assert '"kind"' not in response.text
    nothing_was_written(conn, storage_root)


@needs_model
def test_a_stale_generation_stamp_refuses_the_whole_batch(
    client: TestClient,
    conn: psycopg.Connection,
    administrator: Any,
    storage_root: Path,
) -> None:
    # AD-14: an embedding written by one pipeline and one read by another are
    # not comparable, so a mismatch is a hard error rather than a degraded
    # write. Checked once for the batch, not once per row.
    conn.execute(
        "INSERT INTO embedding_generation (pipeline_version, config_hash, is_active) "
        "VALUES (%s, %s, true)",
        ("not-this-pipeline", "0" * 64),
    )

    response = bulk(client, sheet=manifest(THREE_ROWS), images=THREE_IMAGES)

    assert response.status_code == 503
    assert refusal(response)["code"] == "pipeline_stamp_mismatch"
    assert '"kind"' not in response.text
    for statement in (TILES, IMAGES, EMBEDDINGS):
        assert count(conn, statement) == 0, statement
    assert stored_objects(storage_root) == []


# --- What is left behind ------------------------------------------------------


@needs_model
def test_the_spool_does_not_outlive_the_batch(
    client: TestClient, administrator: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The handler copies every upload to a temporary directory it owns, because
    # under a streaming response the multipart form is closed before the body
    # runs. What must not happen is that directory surviving the request: a
    # hundred reference images is gigabytes, and a leak here fills the disk one
    # batch at a time.
    spool_parent = tmp_path / "spools"
    spool_parent.mkdir()
    # `tempfile.tempdir`, not the environment: `gettempdir()` caches its answer
    # the first time it is asked, so a `TMPDIR` set after any other test has
    # made a temporary file would be read by nothing.
    monkeypatch.setattr(tempfile, "tempdir", str(spool_parent))

    response = bulk(client, sheet=manifest(THREE_ROWS[:1]), images=[THREE_IMAGES[0]])

    assert response.status_code == 200
    assert list(spool_parent.iterdir()) == []


@needs_model
def test_a_refused_row_leaves_no_object_behind(
    client: TestClient, administrator: Any, storage_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The storage-before-database ordering the add path uses, in a batch: the
    # objects go down first, so a transaction that then fails has to take them
    # with it. Without the `_discard`, the store would fill with bytes no row
    # points at, one refused row at a time.
    def fail_the_entry(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("the audit entry could not be written")

    monkeypatch.setattr(catalogue.audit, "record", fail_the_entry)

    report = rows_of(bulk(client, sheet=manifest(THREE_ROWS[:1]), images=[THREE_IMAGES[0]]))

    assert report[0]["status"] == "failed"
    assert report[0]["error"]["code"] == "row_failed"
    assert stored_objects(storage_root) == []


@needs_model
def test_the_bulk_row_uses_the_single_adds_own_intake_and_embedding(
    client: TestClient, administrator: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    # "No shortcut for bulk" (AD-7, epic context), observed at run time rather
    # than over the source. `tests/test_source_guards.py` makes the structural
    # half of this claim; this is the half that would catch a helper that
    # called the pipeline through a name the guard's allowlist happened to
    # permit.
    seen: list[str] = []
    real_accept = catalogue._accept_bytes
    real_prepare = catalogue._prepare

    def watched_accept(data: bytes) -> Any:
        seen.append("accept")
        return real_accept(data)

    def watched_prepare(tile_id: Any, accepted: Any) -> Any:
        seen.append("prepare")
        return real_prepare(tile_id, accepted)

    monkeypatch.setattr(catalogue, "_accept_bytes", watched_accept)
    monkeypatch.setattr(catalogue, "_prepare", watched_prepare)

    bulk(client, sheet=manifest(THREE_ROWS[:2]), images=THREE_IMAGES[:2])

    assert seen == ["accept", "prepare", "accept", "prepare"]


@needs_model
def test_the_same_image_through_both_paths_stores_identical_bytes_and_vectors(
    client: TestClient, conn: psycopg.Connection, administrator: Any, storage_root: Path
) -> None:
    # The acceptance criterion in its strongest form: one image submitted twice
    # — once through the single add and once as a row of a batch — produces the
    # same stored source, the same stored derivative and the same 16 vectors.
    # Any asymmetry between the two paths is invisible to every other test in
    # this suite and shows up in Epic 3 as unexplained accuracy loss (AD-1).
    image = jpeg_bytes(a_tile_photograph(11))

    added = client.post(
        ADD_TILE,
        data={"code": STRUCTURED_CODE, "size": SIZE, "category": CATEGORY},
        files=[("images", ("reference.jpg", image, "image/jpeg"))],
    )
    assert added.status_code == 201, added.text

    rows = [{"file": "a.jpg", "code": "RP.CMA.0009DJ.SM.0T", "size": SIZE, "category": CATEGORY}]
    report = rows_of(bulk(client, sheet=manifest(rows), images=[("a.jpg", image)]))
    assert report[0]["status"] == "created", report

    stored = conn.execute(
        "SELECT t.code, ri.id, ri.source_key, ri.derivative_key, ri.sha256, ri.width, "
        "       ri.height, ri.pixel_std, ri.featureless "
        "  FROM reference_image ri JOIN tile t ON t.id = ri.tile_id ORDER BY t.code"
    ).fetchall()
    assert len(stored) == 2
    one, two = stored
    # The digest is of the bytes as uploaded and the same file went both ways.
    assert one["sha256"] == two["sha256"]
    assert (one["width"], one["height"]) == (two["width"], two["height"])
    assert one["pixel_std"] == two["pixel_std"]
    assert one["featureless"] == two["featureless"]

    root = storage_root
    for column in ("source_key", "derivative_key"):
        assert (root / one[column]).read_bytes() == (root / two[column]).read_bytes(), column

    vectors = {
        row["id"]: [
            (r["view_kind"], r["view_index"], r["embedding"])
            for r in conn.execute(
                "SELECT view_kind, view_index, embedding FROM reference_embedding "
                "WHERE reference_image_id = %s ORDER BY view_index",
                (row["id"],),
            ).fetchall()
        ]
        for row in stored
    }
    assert vectors[one["id"]] == vectors[two["id"]]


@needs_model
def test_the_report_carries_no_similarity_value_and_no_storage_reference(
    client: TestClient, administrator: Any
) -> None:
    # AD-20 and AD-9, asserted on the wire. The report is the newest surface in
    # the product and the easiest place for a score or a storage key to arrive
    # unnoticed, because nothing about a row's shape is a declared contract the
    # way `Tile` is.
    response = bulk(client, sheet=manifest(THREE_ROWS[:1]), images=[THREE_IMAGES[0]])
    rendered = response.text.lower()

    assert set(rows_of(response)[0]) == {
        "kind",
        "row",
        "file",
        "code",
        "status",
        "tile_id",
        "flags",
        "error",
    }
    for forbidden in ("score", "similarity", "confidence", "source_key", "derivative_key", "http"):
        assert forbidden not in rendered, forbidden


@needs_model
def test_the_report_uses_the_domains_own_words(client: TestClient, administrator: Any) -> None:
    # AD-18 retires `Product` and `Face`. `face_number` survives as a column
    # name and nothing on this stream carries it — the flag is
    # `unknown_face_number`, which is the exception the vocabulary rule makes
    # for the one permitted survivor, and no free prose here says either word.
    rows = [{"file": "a.jpg", "code": "", "size": SIZE, "category": CATEGORY}]

    response = bulk(client, sheet=manifest(rows), images=[THREE_IMAGES[0]])

    body = response.text.lower()
    # All three banned words, not just the one. `design` is the rename AD-18
    # made and the easiest to reintroduce by habit; `face` is checked as free
    # prose only, since `unknown_face_number` is the permitted survivor and is
    # the one spelling that may appear.
    assert "product" not in body
    assert "design" not in body
    assert "face" not in body.replace("unknown_face_number", "").replace("face_number", "")


@needs_model
def test_a_tile_id_that_is_returned_is_the_one_that_was_written(
    client: TestClient, conn: psycopg.Connection, administrator: Any
) -> None:
    # The id on a created line is the handle the screen would use, so it has to
    # name the row that exists rather than a value invented for the report.
    report = rows_of(bulk(client, sheet=manifest(THREE_ROWS[:1]), images=[THREE_IMAGES[0]]))

    written = conn.execute("SELECT id FROM tile").fetchone()
    assert written is not None
    assert report[0]["tile_id"] == str(written["id"])
    # And it is a real UUID on the wire rather than a string that happens to match.
    assert str(UUID(report[0]["tile_id"])) == report[0]["tile_id"]


# --- The bounds and the defects the review found ------------------------------


def test_more_image_parts_than_the_cap_are_refused_before_anything_is_spooled(
    client: TestClient,
    conn: psycopg.Connection,
    administrator: Any,
    storage_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # **The cap is on the images as well as on the rows, and this is the hole
    # it closes.** A one-row manifest sent with `MAX_BULK_ROWS + 1` image parts
    # passes a row-count check trivially and would then be spooled in full — a
    # copy of every part at up to `MAX_IMAGE_BYTES`, for a batch that can
    # produce one Tile. `MAX_BULK_ROWS`'s own docstring claims to bound the
    # spool, and counting only one side would make that claim false.
    def never(*_: object, **__: object) -> None:
        raise AssertionError("a refused batch was spooled")

    monkeypatch.setattr(catalogue, "_spool", never)
    rows = [{"file": "a.jpg", "code": STRUCTURED_CODE, "size": SIZE, "category": CATEGORY}]
    images = [(f"{n}.jpg", b"x") for n in range(MAX_BULK_ROWS + 1)]

    response = bulk(client, sheet=manifest(rows), images=images)

    assert response.status_code == 422
    assert refusal(response)["code"] == "too_many_rows"
    assert '"kind"' not in response.text
    nothing_was_written(conn, storage_root)


@needs_model
def test_exactly_the_cap_in_image_parts_is_not_refused(
    client: TestClient, administrator: Any
) -> None:
    # The boundary from the other side, so the bound cannot quietly become one
    # smaller than it says. Every part but the first is unmatched, which is the
    # report saying so rather than a refusal.
    rows = [{"file": "a.jpg", "code": STRUCTURED_CODE, "size": SIZE, "category": CATEGORY}]
    images = [THREE_IMAGES[0]] + [(f"extra-{n}.jpg", b"x") for n in range(MAX_BULK_ROWS - 1)]

    response = bulk(client, sheet=manifest(rows), images=images)

    assert response.status_code == 200, response.text
    assert len(rows_of(response)) == MAX_BULK_ROWS


# `needs_model` although nothing here embeds: the route pre-flights the
# artifact before the stream opens, so without it this is a `503` rather
# than the `200` and report below.
@needs_model
def test_a_picker_with_nothing_chosen_counts_as_nothing(
    client: TestClient, administrator: Any
) -> None:
    # An `images` part with neither a name nor any bytes is a file input the
    # Administrator never used, which `add_tile` filters the same way. It must
    # not count against the cap and it must not be reported — an empty picker
    # is not an image that went missing.
    rows = [{"file": "a.jpg", "code": "", "size": SIZE, "category": CATEGORY}]
    body, headers = raw_multipart([("manifest", "codes.csv", manifest(rows)), ("images", "", b"")])

    response = client.post(BULK_UPLOAD, content=body, headers=headers)

    assert response.status_code == 200, response.text
    # One line, for the one manifest row. No line for the empty part.
    assert len(rows_of(response)) == 1


# `needs_model` although nothing here embeds: the route pre-flights the
# artifact before the stream opens, so without it this is a `503` rather
# than the `200` and report below.
@needs_model
def test_a_part_with_bytes_and_no_name_is_reported_rather_than_dropped(
    client: TestClient, administrator: Any
) -> None:
    # It cannot be paired — nothing can name it — but dropping it silently is
    # exactly the failure `image_unmatched` exists to prevent: an image that
    # travelled, was not indexed, and that the Administrator believes is in the
    # catalogue.
    rows = [{"file": "a.jpg", "code": "", "size": SIZE, "category": CATEGORY}]
    body, headers = raw_multipart(
        [("manifest", "codes.csv", manifest(rows)), ("images", "", b"not nothing")]
    )

    response = client.post(BULK_UPLOAD, content=body, headers=headers)
    assert response.status_code == 200, response.text
    report = rows_of(response)

    unnamed = [line for line in report if line["error"]["code"] == "image_unmatched"]
    assert len(unnamed) == 1
    assert unnamed[0]["file"] == ""
    assert unnamed[0]["row"] is None
    assert unnamed[0]["error"]["message"] == catalogue.UNNAMED_UPLOAD
    assert summary_of(response)["failed"] == 2


@needs_model
def test_a_pairing_survives_a_difference_of_case(
    client: TestClient, conn: psycopg.Connection, administrator: Any
) -> None:
    # A sheet exported on one machine routinely spells `IMG_1.JPG` where the
    # file on disk is `img_1.jpg`. Matched exactly, that pair costs two lines
    # of report — the row `image_not_paired` and the image `image_unmatched` —
    # for a difference the Administrator cannot see.
    rows = [{"file": "IMG_1.JPG", "code": STRUCTURED_CODE, "size": SIZE, "category": CATEGORY}]

    response = bulk(client, sheet=manifest(rows), images=[("img_1.jpg", THREE_IMAGES[0][1])])
    report = rows_of(response)

    assert [line["status"] for line in report] == ["created"]
    # And the image is not *also* reported as unmatched, which is the second
    # half of the same defect.
    assert summary_of(response) == {"kind": "summary", "created": 1, "flagged": 0, "failed": 0}
    assert count(conn, TILES) == 1


@needs_model
def test_a_path_qualified_cell_pairs_on_its_base_name(
    client: TestClient, administrator: Any
) -> None:
    # `45X90/POLISH/a.jpg` is how the source tree names a file and what a sheet
    # built from a directory listing carries. The multipart part is `a.jpg`,
    # because that is what a browser sends.
    rows = [
        {
            "file": "45X90/POLISH/a.jpg",
            "code": STRUCTURED_CODE,
            "size": SIZE,
            "category": CATEGORY,
        }
    ]

    report = rows_of(bulk(client, sheet=manifest(rows), images=[THREE_IMAGES[0]]))

    assert [line["status"] for line in report] == ["created"]
    # The line quotes the cell as written, not the base name it was paired on:
    # that is what the Administrator will look for in their sheet.
    assert report[0]["file"] == "45X90/POLISH/a.jpg"


@needs_model
def test_two_uploads_differing_only_by_case_are_still_a_collision(
    client: TestClient, conn: psycopg.Connection, administrator: Any
) -> None:
    # Folding the key must not make a real ambiguity disappear. Picking one of
    # the two would put the wrong image under a Code with nothing raised.
    rows = [{"file": "a.jpg", "code": STRUCTURED_CODE, "size": SIZE, "category": CATEGORY}]
    images = [("a.jpg", THREE_IMAGES[0][1]), ("A.JPG", THREE_IMAGES[1][1])]

    report = rows_of(bulk(client, sheet=manifest(rows), images=images))

    assert report[0]["status"] == "failed"
    assert report[0]["error"]["code"] == "image_not_paired"
    assert count(conn, TILES) == 0


@needs_model
def test_an_unmatched_upload_carries_no_manifest_row_number(
    client: TestClient, administrator: Any
) -> None:
    # `row` is a position in the *sheet*. Counting on past the manifest's end
    # would send an Administrator to row 3 of a sheet that has two.
    rows = THREE_ROWS[:1]
    images = [THREE_IMAGES[0], ("z-stray.jpg", jpeg_bytes(a_tile_photograph(9)))]

    report = rows_of(bulk(client, sheet=manifest(rows), images=images))

    assert report[0]["row"] == 1
    assert report[1]["error"]["code"] == "image_unmatched"
    assert report[1]["row"] is None


def test_a_cell_past_the_csv_field_limit_is_a_refusal_and_not_a_crash(
    client: TestClient, conn: psycopg.Connection, administrator: Any, storage_root: Path
) -> None:
    # `csv` raises `csv.Error` — not a `ValueError` anything would think to
    # catch — for a field past `csv.field_size_limit()`. Unguarded it escapes
    # the handler and becomes a `500`, where a spreadsheet this endpoint cannot
    # read is a `422` whatever shape the defect takes.
    enormous = "x" * (csv.field_size_limit() + 1)
    sheet = f'file,code,size,category\n"{enormous}",CODE,45X90,POLISH\n'.encode()

    response = bulk(client, sheet=sheet, images=[])

    assert response.status_code == 422, response.text
    assert refusal(response)["code"] == "invalid_manifest"
    nothing_was_written(conn, storage_root)


def test_a_header_past_the_csv_field_limit_is_a_refusal_and_not_a_crash(
    client: TestClient, conn: psycopg.Connection, administrator: Any, storage_root: Path
) -> None:
    # The same `csv.Error`, raised from the other of the two places that parse.
    # `DictReader.fieldnames` reads the header lazily, so a defect in the first
    # line escapes a guard placed only on the row iteration — which is why
    # `_manifest_rows` guards both, and why the sibling above is not enough on
    # its own.
    enormous = "x" * (csv.field_size_limit() + 1)
    sheet = f'"{enormous}",code,size,category\na.jpg,CODE,45X90,POLISH\n'.encode()

    response = bulk(client, sheet=sheet, images=[])

    assert response.status_code == 422, response.text
    assert refusal(response)["code"] == "invalid_manifest"
    nothing_was_written(conn, storage_root)


def test_a_manifest_over_its_own_byte_ceiling_is_refused(
    client: TestClient, conn: psycopg.Connection, administrator: Any, storage_root: Path
) -> None:
    # The manifest has a ceiling of its own, and deliberately not
    # `MAX_IMAGE_BYTES`: a hundred rows of four short cells is a few kilobytes,
    # and a bound sized for a 128 MB press file would let an unbounded read
    # masquerade as a bounded one.
    sheet = b"file,code,size,category\n" + b"a.jpg,CODE,45X90,POLISH\n" * 60000
    assert len(sheet) > catalogue.MAX_MANIFEST_BYTES

    response = bulk(client, sheet=sheet, images=[])

    assert response.status_code == 422
    assert refusal(response)["code"] == "invalid_manifest"
    nothing_was_written(conn, storage_root)


@needs_model
def test_a_manifest_carrying_a_byte_order_mark_is_read_normally(
    client: TestClient, administrator: Any
) -> None:
    # A sheet exported from Excel carries a BOM. Decoded as plain UTF-8 its
    # first header becomes `﻿file` — a column named `file` that no lookup
    # matches — so every real export would be refused for missing the column it
    # plainly has. `utf-8-sig` is argued at length in `_manifest_rows`; this is
    # the assertion behind the argument.
    sheet = b"\xef\xbb\xbf" + manifest(THREE_ROWS[:1])

    response = bulk(client, sheet=sheet, images=[THREE_IMAGES[0]])

    assert response.status_code == 200, response.text
    report = rows_of(response)
    assert [line["status"] for line in report] == ["created"]
    # The Code came through without the mark attached to it either.
    assert report[0]["code"] == STRUCTURED_CODE


@needs_model
def test_a_batch_that_stops_still_closes_its_report(
    client: TestClient,
    conn: psycopg.Connection,
    administrator: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A failure outside any one row — a pool with no free connection, a
    # database that went away between rows — happens after the response has
    # started, so there is no status left to change. Unguarded, the client is
    # left holding a `200` with a truncated body: no row saying what went
    # wrong, no summary, and rows that really were created looking like rows
    # that never ran.
    # Raised from `_row_line` rather than from `_bulk_row`, and deliberately:
    # a failure *inside* a row is already caught and reported as that row's
    # own `row_failed`, so it would prove the wrong guard. This one is outside
    # every row's handling, which is where a pool timeout or a connection that
    # went away lands.
    real = catalogue._row_line
    calls = {"n": 0}

    def then_break(*args: Any, **kwargs: Any) -> Any:
        calls["n"] += 1
        # Exactly once. The line that *reports* the batch stopping goes through
        # here too, and a patch that kept raising would take that down with it
        # — which is the very state this test exists to say cannot happen.
        if calls["n"] == 2:
            raise MemoryError("the batch cannot continue")
        return real(*args, **kwargs)

    monkeypatch.setattr(catalogue, "_row_line", then_break)

    response = bulk(client, sheet=manifest(THREE_ROWS), images=THREE_IMAGES)
    report = rows_of(response)

    assert response.status_code == 200
    # Row 1 landed and is reported as itself; the batch then stopped, and the
    # last line says so rather than the body simply ending.
    assert [line["status"] for line in report] == ["created", "failed"]
    assert report[-1]["error"]["code"] == "row_failed"
    assert report[-1]["error"]["message"] == catalogue.BATCH_STOPPED_MESSAGE
    assert report[-1]["row"] is None

    # And the summary still closes it, counting the stop among the failures.
    #
    # **`created` is two, not one**, and the difference is the point of having
    # a summary at all: row 2 was written — the failure here is in *reporting*
    # it — so the Tile exists and there is no line describing it. An
    # Administrator reading two created against one visible row knows to look,
    # which is strictly more than a body that simply ended would have told
    # them.
    assert summary_of(response) == {"kind": "summary", "created": 2, "flagged": 0, "failed": 1}

    # And the claim above, checked rather than asserted in a comment: row 2's
    # Tile really is in the catalogue, which is the whole reason the count and
    # the visible list are allowed to disagree. A regression that rolled row 2
    # back would leave the summary lying and every assertion above it green.
    assert count(conn, TILES) == 2
    stored = {row["code"] for row in conn.execute("SELECT code FROM tile").fetchall()}
    assert stored == {THREE_ROWS[0]["code"], THREE_ROWS[1]["code"]}


def test_an_abandoned_batch_still_removes_its_spool(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # `_bulk_stream`'s `finally` claims an abandoned batch leaves nothing on
    # disk, and every other spool test drains the response to completion — so
    # the claim was the one thing untested. Driven against the generator
    # directly, because a `TestClient` cannot hang up mid-stream: one line is
    # consumed and the generator is then closed, which is what a client
    # disconnecting does.
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    spool = tempfile.TemporaryDirectory(prefix="rocell-bulk-")
    directory = Path(spool.name)
    assert directory.exists()

    rows = [
        catalogue._ManifestRow(number=1, file="a.jpg", code="CODE", size="45X90", category=None)
    ]
    stream = catalogue._bulk_stream(
        pool=None,  # type: ignore[arg-type]
        store=None,  # type: ignore[arg-type]
        administrator=None,  # type: ignore[arg-type]
        source_ip=None,
        rows=rows,
        spooled={},
        unnamed=0,
        spool=spool,
    )

    # One line, then hang up. The pool is `None`, so opening a connection
    # raises inside the guard and the batch reports itself as stopped — which
    # is a line, which is all this needs to have started the generator.
    assert json.loads(next(stream))["kind"] == "row"
    stream.close()

    assert not directory.exists()
