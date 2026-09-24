"""The two bulk routes — Story 2.4's I/O matrix, driven through the real endpoints.

Driven against a real PostgreSQL with the shipped migrations and a real object
store, for `test_add_tile.py`'s reason: every claim here is about the seam
between them. What this file adds is the property that seam did not have to
have before — that one row's outcome is independent of every other row's.

**The batch is one request per image, and that is what shapes this file.** The
caller asks for a plan, then sends one row at a time; `run()` below is that
driver, so a test reads the report the way the screen assembles it while every
assertion still lands on one route's real answer. Three groups, and they fail
differently:

* **The plan.** Every decision that can be made without an image byte is made
  before one is sent: which row takes which file, which rows nothing can be
  found for, which files no row names. There is one item per line the report
  will carry, in the order it will carry them, and nothing is written.
* **The rows.** N valid pairs become N Tiles and N lines, and a failure takes
  only its own row down. A batch mixing a zero-byte file, an unreadable file, a
  duplicate Code and a row naming an image nobody uploaded still creates every
  valid row beside them — and a row that failed can be sent again on its own,
  which is the whole reason the transfer is split this way.
* **The classification** (AD-18, epic context). A Category that cannot be
  recovered and a Code with no trailing number are **flags on a Tile that was
  created**, never refusals. A zero-byte or unreadable file is a **failure**.
  Two rows sharing a Size and a Category are two distinct Tiles. Conflating any
  pair of those is the defect this story exists to avoid, and none of them
  raises.

**Where a refusal lives is itself asserted.** A batch-wide condition — a
manifest that cannot be read, a batch over the cap, a missing model artifact, a
stale generation stamp — is an envelope from the *plan*, because that is the
phase that costs no image transfer. One row's own defect is a `200` from the
row route carrying a report line, because the caller is going to finish the
report either way. Swapping those two is a silent regression in how a hundred-row
batch behaves, and each group below pins its own side of it.

The tests that embed for real are marked `needs_model` and are the slow ones —
16 forward passes per image, per row. Every batch here is therefore two or
three rows: the claim is about independence between rows, and three rows make
it exactly as well as thirty.
"""

from __future__ import annotations

import csv
import io
import struct
import zlib
from collections.abc import Callable
from dataclasses import dataclass, field
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

BULK_PLAN = "/admin/tiles/bulk/plan"
BULK_ROW = "/admin/tiles/bulk/row"
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


def ask_plan(
    client: TestClient,
    *,
    sheet: bytes | None,
    names: list[str],
) -> Any:
    """`POST /admin/tiles/bulk/plan`, with the manifest part omitted when None.

    The names go up as repeated form fields and the bytes stay here, which is
    the phase's whole point: the pairing is decided for a batch that has not
    been transferred.
    """
    files: list[tuple[str, tuple[str, bytes, str]]] = []
    if sheet is not None:
        files.append(("manifest", ("codes.csv", sheet, "text/csv")))
    # A list value is how `httpx` writes one form field twice, which is how a
    # multipart body expresses a list — the same shape `add_tile`'s `images`
    # arrives in.
    return client.post(BULK_PLAN, files=files or None, data={"names": names})


def send_row(
    client: TestClient,
    *,
    code: str | None = None,
    size: str | None = None,
    category: str | None = None,
    row: int | None = None,
    image: tuple[str, bytes] | None = None,
) -> Any:
    """`POST /admin/tiles/bulk/row` — one image and the row it belongs to."""
    data: dict[str, str] = {}
    if code is not None:
        data["code"] = code
    if size is not None:
        data["size"] = size
    if category is not None:
        data["category"] = category
    if row is not None:
        data["row"] = str(row)
    files = [("image", (image[0], image[1], "image/jpeg"))] if image is not None else None
    return client.post(BULK_ROW, data=data or None, files=files)


def send_item(client: TestClient, item: dict[str, Any], data: bytes) -> Any:
    """One plan item, sent the way the driver sends it: the item's own fields."""
    return send_row(
        client,
        code=item["code"] or "",
        size=item["size"] or "",
        category=item["category"] or "",
        row=item["row"],
        image=(item["upload"], data),
    )


@dataclass(slots=True)
class Batch:
    """A whole batch driven to the end, as the screen would drive it.

    `rows` is the assembled report — one entry per plan item, in plan order,
    carrying the item's `row`, `file` and `code` beside the outcome. It is the
    shape the streamed report used to carry, composed here rather than on the
    wire, so an assertion about the report reads the same as it always did.
    """

    plan: Any
    rows: list[dict[str, Any]] = field(default_factory=list)
    #: Every row request's raw response, in the order they were sent. For the
    #: tests that are about the route rather than about the report.
    responses: list[Any] = field(default_factory=list)

    @property
    def counts(self) -> dict[str, int]:
        tally = {"created": 0, "flagged": 0, "failed": 0}
        for line in self.rows:
            tally[line["status"]] += 1
        return tally


def run(
    client: TestClient,
    *,
    sheet: bytes | None,
    images: list[tuple[str, bytes]],
) -> Batch:
    """Plan the batch, then send it one row at a time. The driver, in a helper.

    Faithful to what the screen does, which is what makes the assertions in
    this file about the product rather than about a test: it declares the names
    it is holding, takes the plan's word for the pairing, sends one request per
    item the plan paired, and keeps the items the plan already decided as the
    report lines they are.
    """
    batch = Batch(plan=ask_plan(client, sheet=sheet, names=[name for name, _ in images]))
    if batch.plan.status_code != 200:
        return batch

    bytes_for = {name: data for name, data in images}
    for item in batch.plan.json()["items"]:
        line = {"row": item["row"], "file": item["file"], "code": item["code"] or None}
        if item["upload"] is None:
            # Already decided, and there is nothing to send. The item *is* the
            # report line — exactly one of `upload` and `error` is ever set.
            assert item["error"] is not None, item
            batch.rows.append({**line, "status": "failed", "tile_id": None, "flags": [], **item})
            continue

        response = send_item(client, item, bytes_for[item["upload"]])
        batch.responses.append(response)
        assert response.status_code == 200, response.text
        batch.rows.append({**line, **response.json()})

    return batch


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
    batch = run(client, sheet=manifest(THREE_ROWS), images=THREE_IMAGES)

    assert batch.plan.status_code == 200, batch.plan.text
    # Catalogue data on the wire, like every other authenticated response — on
    # the plan, which names every Code in the sheet, and on each row.
    assert batch.plan.headers["cache-control"] == "no-store"
    assert all(response.headers["cache-control"] == "no-store" for response in batch.responses)

    report = batch.rows
    assert [line["status"] for line in report] == ["created"] * 3
    assert [line["row"] for line in report] == [1, 2, 3]
    assert [line["file"] for line in report] == ["a.jpg", "b.jpg", "c.jpg"]
    assert [line["code"] for line in report] == [row["code"] for row in THREE_ROWS]
    assert all(line["flags"] == [] and line["error"] is None for line in report)
    assert all(line["tile_id"] is not None for line in report)

    assert batch.counts == {"created": 3, "flagged": 0, "failed": 0}

    assert count(conn, TILES) == 3
    assert count(conn, IMAGES) == 3
    # AD-13: sixteen views per image, as separate rows, never pooled.
    assert count(conn, EMBEDDINGS) == 3 * shared_vision.VIEWS_PER_IMAGE == 48
    # Two objects per image: the retained source and AD-17's capped derivative.
    assert len(stored_objects(storage_root)) == 6


@needs_model
def test_one_image_travels_per_request(client: TestClient, administrator: Any) -> None:
    # EXPERIENCE.md:94 asks for the rows to arrive as they complete, and this
    # is the structural fact that delivers it: a row *is* a request, so its
    # outcome is known when that request answers and the caller has something
    # to paint before the batch ends. There is no long-lived body to read
    # incrementally and nothing to buffer.
    #
    # **And it is what makes a hundred-image range survivable.** A dropped
    # connection costs the one row that was in flight; every row already
    # answered is in the catalogue, and the rest are still sendable.
    batch = run(client, sheet=manifest(THREE_ROWS[:2]), images=THREE_IMAGES[:2])

    assert len(batch.responses) == 2
    # One `image` part per request, and one row's worth of body back.
    for response in batch.responses:
        body = response.json()
        assert set(body) == {"status", "tile_id", "flags", "error"}


@needs_model
def test_the_plan_names_every_line_the_report_will_carry(
    client: TestClient, administrator: Any
) -> None:
    # The whole reason the plan phase exists: a caller needs a denominator, and
    # the pairing, before it spends a single image transfer. One item per line
    # the report will carry — not per manifest row, which is a different number
    # for exactly the batch a report is most needed for.
    batch = run(client, sheet=manifest(THREE_ROWS), images=THREE_IMAGES)

    items = batch.plan.json()["items"]
    assert len(items) == len(batch.rows) == 3
    # Nothing else rides on the plan. A batch id, an estimate of how long this
    # will take or an echo of the sheet would each be a second thing for a
    # caller to trust — and a batch id in particular would be the job state
    # this design does not have.
    assert set(batch.plan.json()) == {"items"}


@needs_model
def test_the_plan_counts_a_file_no_row_names(client: TestClient, administrator: Any) -> None:
    # The plan is a count of *report lines*, and this is the batch that tells
    # that apart from the sheet's length: one row in the sheet, two files
    # chosen. A caller that had guessed its denominator from either number
    # alone would have been wrong here, which is why the server states it.
    rows = [{"file": "a.jpg", "code": STRUCTURED_CODE, "size": SIZE, "category": CATEGORY}]
    images = [THREE_IMAGES[0], ("stray.jpg", jpeg_bytes(a_tile_photograph(9)))]

    batch = run(client, sheet=manifest(rows), images=images)

    assert len(batch.plan.json()["items"]) == len(batch.rows) == 2


@needs_model
def test_the_plan_counts_a_name_that_was_blank(client: TestClient, administrator: Any) -> None:
    # The third kind of line the plan has to include. A declared name that is
    # empty cannot be paired — nothing can name it — but dropping it silently
    # is exactly the failure `image_unmatched` exists to prevent, so it is an
    # item like any other.
    rows = [{"file": "a.jpg", "code": "", "size": SIZE, "category": CATEGORY}]

    response = ask_plan(client, sheet=manifest(rows), names=["a.jpg", ""])
    assert response.status_code == 200, response.text

    items = response.json()["items"]
    assert len(items) == 2
    assert items[1]["file"] == ""
    assert items[1]["row"] is None
    assert items[1]["upload"] is None
    assert items[1]["error"]["code"] == "image_unmatched"
    assert items[1]["error"]["message"] == catalogue.UNNAMED_UPLOAD


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

    batch = run(client, sheet=manifest(rows), images=images)

    report = batch.rows
    assert [line["status"] for line in report] == ["flagged"] * 3
    assert [line["flags"] for line in report] == [
        ["unknown_category"],
        ["unknown_face_number"],
        ["low_quality_image"],
    ]
    assert all(line["tile_id"] is not None and line["error"] is None for line in report)
    assert batch.counts["flagged"] == 3

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

    report = run(client, sheet=manifest(rows), images=[THREE_IMAGES[0]]).rows

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

    report = run(client, sheet=manifest(rows), images=[("a.jpg", jpeg_bytes())]).rows

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
    batch = run(client, sheet=manifest(THREE_ROWS[:2]), images=THREE_IMAGES[:2])

    assert [line["status"] for line in batch.rows] == ["created", "created"]
    assert count(conn, TILES) == 2
    # One `tile_size` row and one `tile_category` row between them: the
    # groupings are shared lookups, resolved create-if-missing, and a second
    # row for the same name would be the near-duplicate the shared resolver
    # exists to prevent — across two requests now, which is where a resolver
    # that raced would show it.
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

    report = run(client, sheet=sheet, images=[THREE_IMAGES[0]]).rows

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

    assert [line["status"] for line in run(client, sheet=sheet, images=[THREE_IMAGES[0]]).rows] == [
        "created"
    ]


@needs_model
def test_a_manifest_with_no_category_column_files_every_row_under_the_sentinel(
    client: TestClient, conn: psycopg.Connection, administrator: Any
) -> None:
    # The column is optional, and its absence is the same fact as a blank cell.
    sheet = manifest(
        [{"file": "a.jpg", "code": STRUCTURED_CODE, "size": SIZE}],
        header=["file", "code", "size"],
    )

    report = run(client, sheet=sheet, images=[THREE_IMAGES[0]]).rows

    assert report[0]["status"] == "flagged"
    assert report[0]["flags"] == ["unknown_category"]
    filed = conn.execute(
        "SELECT c.name AS category FROM tile t LEFT JOIN tile_category c ON c.id = t.category_id"
    ).fetchone()
    assert filed is not None and filed["category"] == UNKNOWN_CATEGORY


# --- The pairing, decided in the plan -----------------------------------------
# Every rule about which file belongs to which row lives in the plan and only
# there. `apps/web` sends names and takes the answer, so a second reader of the
# sheet — which is what a browser-side pairing would be — cannot exist to
# disagree with this one.


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

    batch = run(client, sheet=manifest(rows), images=[("a.jpg", jpeg_bytes())])

    assert [line["status"] for line in batch.rows] == ["created"]
    assert count(conn, TILES) == 1


@needs_model
def test_a_path_qualified_cell_pairs_on_its_base_name(
    client: TestClient, administrator: Any
) -> None:
    # `45X90/POLISH/a.jpg` is how the source tree names a file and what a sheet
    # built from a directory listing carries. The name the caller declares is
    # `a.jpg`, because that is what a file picker gives it.
    rows = [
        {
            "file": "45X90/POLISH/a.jpg",
            "code": STRUCTURED_CODE,
            "size": SIZE,
            "category": CATEGORY,
        }
    ]

    batch = run(client, sheet=manifest(rows), images=[THREE_IMAGES[0]])

    assert [line["status"] for line in batch.rows] == ["created"]
    # The item quotes the cell as written, not the base name it was paired on:
    # that is what the Administrator will look for in their sheet. `upload` is
    # the other half — the name to send — and the two differ here on purpose.
    item = batch.plan.json()["items"][0]
    assert item["file"] == "45X90/POLISH/a.jpg"
    assert item["upload"] == "a.jpg"


@needs_model
def test_a_pairing_survives_a_difference_of_case(
    client: TestClient, conn: psycopg.Connection, administrator: Any
) -> None:
    # A sheet exported on one machine routinely spells `IMG_1.JPG` where the
    # file on disk is `img_1.jpg`. Matched exactly, that pair costs two lines
    # of report — the row `image_not_paired` and the image `image_unmatched` —
    # for a difference the Administrator cannot see.
    rows = [{"file": "IMG_1.JPG", "code": STRUCTURED_CODE, "size": SIZE, "category": CATEGORY}]

    batch = run(client, sheet=manifest(rows), images=[("img_1.jpg", THREE_IMAGES[0][1])])

    assert [line["status"] for line in batch.rows] == ["created"]
    # And the image is not *also* reported as unmatched, which is the second
    # half of the same defect.
    assert batch.counts == {"created": 1, "flagged": 0, "failed": 0}
    assert count(conn, TILES) == 1
    # The name to send is the caller's own spelling, not the sheet's: a driver
    # that had to guess which of the two to put in the request would be pairing
    # for itself again.
    assert batch.plan.json()["items"][0]["upload"] == "img_1.jpg"


@needs_model
def test_two_rows_naming_one_file_are_two_tiles_and_no_orphan(
    client: TestClient, conn: psycopg.Connection, administrator: Any
) -> None:
    # Nothing is merged and nothing is deduplicated (AD-18). Two Codes against
    # one image is a sheet the Administrator wrote that way, and the answer is
    # two Tiles — not one, and not a conflict. The file is named by a row, so
    # it is not an orphan either: a trailing `image_unmatched` item here would
    # report a file that was in fact used.
    rows = [
        {"file": "a.jpg", "code": STRUCTURED_CODE, "size": SIZE, "category": CATEGORY},
        {"file": "a.jpg", "code": BARE_CODE, "size": SIZE, "category": CATEGORY},
    ]

    batch = run(client, sheet=manifest(rows), images=[("a.jpg", jpeg_bytes())])

    assert [line["status"] for line in batch.rows] == ["created", "created"]
    assert batch.counts == {"created": 2, "flagged": 0, "failed": 0}
    # The same file sent twice, which is what "two tiles from one image" means
    # once the transfer is per row.
    assert [item["upload"] for item in batch.plan.json()["items"]] == ["a.jpg", "a.jpg"]
    assert count(conn, TILES) == 2


@needs_model
def test_two_files_sharing_a_name_refuse_the_row_rather_than_guessing(
    client: TestClient, conn: psycopg.Connection, administrator: Any
) -> None:
    # Picking one of the two would put the wrong image under a Code with
    # nothing raised — a tile that scans to somebody else's reference. Decided
    # in the plan, so neither file is sent at all.
    rows = [{"file": "a.jpg", "code": STRUCTURED_CODE, "size": SIZE, "category": CATEGORY}]
    images = [
        ("a.jpg", jpeg_bytes(a_tile_photograph(1))),
        ("a.jpg", jpeg_bytes(a_tile_photograph(2))),
    ]

    batch = run(client, sheet=manifest(rows), images=images)

    assert batch.rows[0]["status"] == "failed"
    assert batch.rows[0]["error"]["code"] == "image_not_paired"
    assert "a.jpg" in batch.rows[0]["error"]["message"]
    assert batch.responses == []
    assert count(conn, TILES) == 0


@needs_model
def test_two_files_differing_only_by_case_are_still_a_collision(
    client: TestClient, conn: psycopg.Connection, administrator: Any
) -> None:
    # Folding the key must not make a real ambiguity disappear. Picking one of
    # the two would put the wrong image under a Code with nothing raised.
    rows = [{"file": "a.jpg", "code": STRUCTURED_CODE, "size": SIZE, "category": CATEGORY}]
    images = [("a.jpg", THREE_IMAGES[0][1]), ("A.JPG", THREE_IMAGES[1][1])]

    batch = run(client, sheet=manifest(rows), images=images)

    assert batch.rows[0]["status"] == "failed"
    assert batch.rows[0]["error"]["code"] == "image_not_paired"
    assert count(conn, TILES) == 0


@needs_model
def test_a_file_no_row_names_is_reported_rather_than_silently_ignored(
    client: TestClient, conn: psycopg.Connection, administrator: Any
) -> None:
    # A file the Administrator chose and that nothing indexed is a tile they
    # believe is in the catalogue. The item is keyed by the file name and
    # carries no Code, because no row gave it one — and it is decided before
    # the file is sent, which is the improvement over reporting it afterwards.
    rows = [{"file": "a.jpg", "code": STRUCTURED_CODE, "size": SIZE, "category": CATEGORY}]
    images = [THREE_IMAGES[0], ("stray.jpg", jpeg_bytes(a_tile_photograph(9)))]

    batch = run(client, sheet=manifest(rows), images=images)
    report = batch.rows

    assert [line["status"] for line in report] == ["created", "failed"]
    assert report[1]["file"] == "stray.jpg"
    assert report[1]["code"] is None
    assert report[1]["error"]["code"] == "image_unmatched"
    # **No row number**, because there is no row. `row` is a position in the
    # sheet the Administrator is holding, and counting on past the manifest's
    # end would send them to row 2 of a sheet that has one.
    assert report[1]["row"] is None
    assert batch.counts == {"created": 1, "flagged": 0, "failed": 1}
    # One request, for the one row that paired. The stray never travelled.
    assert len(batch.responses) == 1
    assert count(conn, TILES) == 1


@needs_model
def test_a_row_naming_no_file_at_all_is_told_so(
    client: TestClient, conn: psycopg.Connection, administrator: Any, storage_root: Path
) -> None:
    row = {"file": "", "code": STRUCTURED_CODE, "size": SIZE, "category": CATEGORY}

    batch = run(client, sheet=manifest([row]), images=[THREE_IMAGES[0]])

    assert batch.rows[0]["error"]["code"] == "image_not_paired"
    # The sentence is about the row rather than about a file called nothing.
    assert batch.rows[0]["error"]["message"] == catalogue.NO_FILE_NAMED
    nothing_was_written(conn, storage_root)


@needs_model
def test_an_unpairable_row_names_the_file_it_could_not_find(
    client: TestClient, administrator: Any
) -> None:
    # The one thing the Administrator has to go and find, in the sentence. A
    # row refused for want of an image is otherwise a hunt through the sheet.
    rows = [{"file": "absent.jpg", "code": STRUCTURED_CODE, "size": SIZE, "category": CATEGORY}]

    batch = run(client, sheet=manifest(rows), images=[])

    assert batch.rows[0]["error"]["code"] == "image_not_paired"
    assert "absent.jpg" in batch.rows[0]["error"]["message"]


def test_the_plan_is_decided_from_names_alone_and_writes_nothing(
    client: TestClient,
    conn: psycopg.Connection,
    administrator: Any,
    storage_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # **The claim the whole phase rests on.** The plan takes file names and no
    # bytes, so asking for one costs the Administrator nothing but the sheet —
    # which is what makes a batch-wide refusal cheap and an unpairable row
    # something they learn in a second rather than after a gigabyte.
    #
    # Asserted by removing the pixel pipeline from under it: a plan that
    # decoded, embedded or stored anything would fail rather than answer.
    def never(*_: object, **__: object) -> None:
        raise AssertionError("the plan reached the pixel pipeline")

    monkeypatch.setattr(catalogue, "_accept", never)
    monkeypatch.setattr(catalogue, "_prepare", never)

    response = ask_plan(
        client,
        sheet=manifest(THREE_ROWS),
        names=[name for name, _ in THREE_IMAGES],
    )

    assert response.status_code == 200, response.text
    assert [item["upload"] for item in response.json()["items"]] == ["a.jpg", "b.jpg", "c.jpg"]
    assert all(item["error"] is None for item in response.json()["items"])
    nothing_was_written(conn, storage_root)


@needs_model
def test_every_plan_item_is_either_sendable_or_already_decided(
    client: TestClient, administrator: Any
) -> None:
    # The invariant a driver is written against: exactly one of `upload` and
    # `error` is set on every item. An item with both would leave the caller
    # deciding whether to send a row the server had already refused; an item
    # with neither would be a line of the report nobody can finish.
    rows = [
        {"file": "a.jpg", "code": STRUCTURED_CODE, "size": SIZE, "category": CATEGORY},
        {"file": "absent.jpg", "code": BARE_CODE, "size": SIZE, "category": CATEGORY},
    ]
    images = [THREE_IMAGES[0], ("stray.jpg", jpeg_bytes(a_tile_photograph(9)))]

    items = ask_plan(client, sheet=manifest(rows), names=[name for name, _ in images]).json()[
        "items"
    ]

    assert len(items) == 3
    for item in items:
        assert (item["upload"] is None) != (item["error"] is None), item
        # Every key on every item, `null` included: a caller that had to test
        # for a key's presence as well as its value has two ways to be wrong.
        assert set(item) == {"row", "file", "code", "size", "category", "upload", "error"}


# --- Per-row failures ---------------------------------------------------------
# Each of these is a `200` from the row route carrying a report line, not a
# status on the response. The caller is working through a plan and is going to
# finish the report either way, so a 4xx per bad row would make it choose
# between stopping and treating a refusal as a transport failure.


@needs_model
def test_a_failure_takes_only_its_own_row_down(
    client: TestClient,
    conn: psycopg.Connection,
    administrator: Any,
    storage_root: Path,
) -> None:
    # The acceptance criterion in one batch: a zero-byte file, an unreadable
    # file, a duplicate Code and a row naming an image nobody chose, each
    # reported on its own line with its own code, with every valid row beside
    # them still created.
    rows = [
        {"file": "good.jpg", "code": STRUCTURED_CODE, "size": SIZE, "category": CATEGORY},
        {"file": "empty.jpg", "code": "RP.CMA.0011DJ.SM.0T", "size": SIZE, "category": CATEGORY},
        {"file": "text.jpg", "code": "RP.CMA.0012DJ.SM.0T", "size": SIZE, "category": CATEGORY},
        # The same Code as row 1, which the first row has already claimed by
        # the time this one is sent.
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

    batch = run(client, sheet=manifest(rows), images=images)

    report = batch.rows
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

    # Every request that was sent answered `200`, including the four refused
    # rows: a refusal here is a line of a report, not a broken request.
    assert [response.status_code for response in batch.responses] == [200] * 5
    assert batch.counts == {"created": 2, "flagged": 0, "failed": 4}

    # Nothing was written for any of the four, and the two valid rows are whole.
    assert count(conn, TILES) == 2
    assert count(conn, IMAGES) == 2
    assert count(conn, EMBEDDINGS) == 32
    assert len(stored_objects(storage_root)) == 4
    codes = {row["code"] for row in conn.execute("SELECT code FROM tile").fetchall()}
    assert codes == {STRUCTURED_CODE, "RP.CMA.0014DJ.SM.0T"}


@needs_model
def test_a_row_that_failed_can_be_sent_again_on_its_own(
    client: TestClient, conn: psycopg.Connection, administrator: Any
) -> None:
    # **The reason the transfer is split at all.** A row that failed for
    # something the Administrator can fix — or for nothing they can see, which
    # is what a dropped connection looks like — is one request, and sending it
    # again costs one image rather than the range. Nothing about the first
    # attempt has to be undone first and nothing on the server remembers it.
    rows = [{"file": "a.jpg", "code": STRUCTURED_CODE, "size": SIZE, "category": CATEGORY}]
    plan = ask_plan(client, sheet=manifest(rows), names=["a.jpg"])
    item = plan.json()["items"][0]

    # First attempt: the file is not a readable image, so the row fails.
    refused = send_item(client, item, b"this is not an image")
    assert refused.status_code == 200, refused.text
    assert refused.json()["status"] == "failed"
    assert refused.json()["error"]["code"] == "unreadable_image"
    assert count(conn, TILES) == 0

    # Second attempt, same item, the file re-exported. The Code was never
    # claimed, so nothing stands in the way of the retry.
    added = send_item(client, item, jpeg_bytes())
    assert added.status_code == 200, added.text
    assert added.json()["status"] == "created"
    assert added.json()["tile_id"] is not None
    assert count(conn, TILES) == 1


@needs_model
def test_a_row_that_already_landed_is_refused_rather_than_duplicated(
    client: TestClient, conn: psycopg.Connection, administrator: Any
) -> None:
    # The other half of the retry, and the one a driver has to survive: the
    # request that answered was the request that committed, so a caller that
    # retried a row it could not read the answer to gets `code_already_exists`
    # rather than a second Tile. The Code is the identity (AD-18) and the
    # unique index is what says so.
    rows = [{"file": "a.jpg", "code": STRUCTURED_CODE, "size": SIZE, "category": CATEGORY}]
    item = ask_plan(client, sheet=manifest(rows), names=["a.jpg"]).json()["items"][0]

    assert send_item(client, item, jpeg_bytes()).json()["status"] == "created"
    again = send_item(client, item, jpeg_bytes())

    assert again.status_code == 200, again.text
    assert again.json()["status"] == "failed"
    assert again.json()["error"]["code"] == "code_already_exists"
    assert count(conn, TILES) == 1


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
    report = run(client, sheet=manifest(rows), images=[THREE_IMAGES[0]]).rows

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
    # sees it — through whichever of the two catches it. **Nothing in the plan
    # notices**, deliberately: two rows claiming a Code is not a pairing
    # problem, and a plan that pre-refused it would be a second decision about
    # a Code that only the index can make.
    rows = [
        {"file": "a.jpg", "code": STRUCTURED_CODE, "size": SIZE, "category": CATEGORY},
        {"file": "b.jpg", "code": STRUCTURED_CODE, "size": SIZE, "category": CATEGORY},
    ]

    batch = run(client, sheet=manifest(rows), images=THREE_IMAGES[:2])

    assert all(item["error"] is None for item in batch.plan.json()["items"])
    assert [line["status"] for line in batch.rows] == ["created", "failed"]
    assert batch.rows[1]["error"]["code"] == "code_already_exists"
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

    report = run(client, sheet=manifest(rows), images=[("big.jpg", big), ("small.jpg", small)]).rows

    assert report[0]["status"] == "failed"
    # A report line and a `200`, not the `413` the single add answers: the
    # caller has a report to finish, and one file the Administrator has to
    # re-export is one line of it.
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
    # gates in different places — the byte ceiling stops the read, the pixel
    # ceiling is read off the header inside `_accept`. The real catalogue holds
    # images at 19276x9638, so this is the half it actually meets.
    rows = [
        {"file": "bomb.png", "code": STRUCTURED_CODE, "size": SIZE, "category": CATEGORY},
        {"file": "ok.jpg", "code": BARE_CODE, "size": SIZE, "category": CATEGORY},
    ]
    images = [
        ("bomb.png", a_png_header_claiming(20_000, 20_001)),
        ("ok.jpg", jpeg_bytes()),
    ]

    report = run(client, sheet=manifest(rows), images=images).rows

    assert report[0]["status"] == "failed"
    assert report[0]["error"]["code"] == "image_too_large"
    # And the batch went on, which is the claim: a bomb takes its own row.
    assert report[1]["status"] == "created"
    assert count(conn, TILES) == 1


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
    # costing sixteen forward passes. **Refused by the row route and not by the
    # plan**, deliberately: the plan pairs, and a Size the product will not
    # store is not a pairing problem. The `needs_model` mark is still required
    # because the plan pre-flights the artifact.
    row = {"file": "a.jpg", "code": STRUCTURED_CODE, "size": SIZE, "category": CATEGORY, **cell}

    batch = run(client, sheet=manifest([row]), images=[THREE_IMAGES[0]])

    assert batch.plan.json()["items"][0]["error"] is None
    assert batch.rows[0]["status"] == "failed"
    assert batch.rows[0]["error"]["code"] == expected
    nothing_was_written(conn, storage_root)


@needs_model
def test_an_unexpected_failure_takes_one_row_and_answers_it(
    client: TestClient,
    conn: psycopg.Connection,
    administrator: Any,
    storage_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A row raising something this handler cannot explain. The line says
    # `row_failed` with a fixed sentence that leaks nothing — an exception's
    # text can carry a path, a query fragment or a credential, and this
    # response goes to the browser — and the request still answers `200`, so
    # the driver reports the row and carries on with the batch.
    def broken(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("postgresql://rocell:hunter2@db.internal/rocell is unreachable")

    monkeypatch.setattr(catalogue, "_bulk_row", broken)
    rows = [{"file": "a.jpg", "code": STRUCTURED_CODE, "size": SIZE, "category": CATEGORY}]
    item = ask_plan(client, sheet=manifest(rows), names=["a.jpg"]).json()["items"][0]

    response = send_item(client, item, THREE_IMAGES[0][1])

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "failed"
    assert body["error"]["code"] == "row_failed"
    assert body["error"]["message"] == catalogue.ROW_FAILED_MESSAGE
    assert "hunter2" not in response.text
    assert "postgresql" not in response.text
    nothing_was_written(conn, storage_root)


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

    report = run(client, sheet=manifest(THREE_ROWS[:1]), images=[THREE_IMAGES[0]]).rows

    assert report[0]["status"] == "failed"
    assert report[0]["error"]["code"] == "row_failed"
    assert stored_objects(storage_root) == []


@needs_model
def test_the_row_route_refuses_a_request_carrying_no_image(
    client: TestClient, conn: psycopg.Connection, administrator: Any, storage_root: Path
) -> None:
    # A Tile with no reference image is a catalogue row a Scan can never return
    # and a member of staff can never verify (FR-7), so this is refused as a
    # *request* rather than reported as a row: the plan never produces an item
    # to send without a file, so nothing a driver does can reach it, and a
    # report line for it would describe a row that does not exist in any sheet.
    response = send_row(client, code=STRUCTURED_CODE, size=SIZE, category=CATEGORY)

    assert response.status_code == 422, response.text
    assert refusal(response)["code"] == "invalid_image"
    nothing_was_written(conn, storage_root)


# --- The batch-wide refusals ---------------------------------------------------
# Every one of these is decided by the *plan*, which is the phase that costs no
# image transfer — so an Administrator holding a sheet the server cannot read,
# or a range longer than the cap, learns it in a second rather than after a
# gigabyte. Each asserts the envelope **and** that no plan came back: a handler
# that answered a plan and then reported the same condition once per row would
# be back to a hundred lines saying one thing.


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
def test_a_manifest_that_is_not_one_is_refused_with_no_plan(
    client: TestClient,
    conn: psycopg.Connection,
    administrator: Any,
    storage_root: Path,
    sheet: bytes | None,
) -> None:
    response = ask_plan(client, sheet=sheet, names=["a.jpg"])

    assert response.status_code == 422, response.text
    assert refusal(response)["code"] == "invalid_manifest"
    # An envelope, not a plan: there is nothing on this response to drive.
    assert "items" not in response.text
    assert response.headers["cache-control"] == "no-store"
    nothing_was_written(conn, storage_root)


def test_the_refusal_for_a_workbook_names_the_fix_rather_than_the_problem(
    client: TestClient, administrator: Any
) -> None:
    # EXPERIENCE.md's register: somebody who attached a workbook needs to know
    # to export it, not that the bytes did not decode.
    response = ask_plan(client, sheet=b"PK\x03\x04\x14\x00", names=[])

    assert "CSV" in refusal(response)["message"]


def test_a_manifest_over_the_row_cap_is_refused_before_any_image_is_sent(
    client: TestClient, conn: psycopg.Connection, administrator: Any, storage_root: Path
) -> None:
    # **And "before any image is sent" is now literally true**, which it was
    # not when the whole batch travelled in one body: the plan carries file
    # names, so a sheet over the cap is refused for the price of the sheet.
    rows = [
        {"file": f"{n}.jpg", "code": f"RP.CMA.{n:04d}DJ.SM.0T", "size": SIZE, "category": CATEGORY}
        for n in range(MAX_BULK_ROWS + 1)
    ]

    response = ask_plan(client, sheet=manifest(rows), names=["0.jpg"])

    assert response.status_code == 422
    assert refusal(response)["code"] == "too_many_rows"
    # The number is in the sentence: an Administrator holding a longer sheet
    # needs to know where to split it.
    assert str(MAX_BULK_ROWS) in refusal(response)["message"]
    assert "items" not in response.text
    nothing_was_written(conn, storage_root)


@needs_model
def test_a_manifest_exactly_at_the_row_cap_is_not_refused(
    client: TestClient, administrator: Any
) -> None:
    # The boundary, from the other side. Every row is unpairable — this is
    # about the cap, not about the batch — and a refusal here would be the
    # off-by-one that makes the bound one smaller than it says.
    rows = [
        {"file": f"{n}.jpg", "code": f"RP.CMA.{n:04d}DJ.SM.0T", "size": SIZE, "category": CATEGORY}
        for n in range(MAX_BULK_ROWS)
    ]

    response = ask_plan(client, sheet=manifest(rows), names=[])

    assert response.status_code == 200
    assert len(response.json()["items"]) == MAX_BULK_ROWS


def test_more_names_than_the_cap_are_refused(
    client: TestClient, conn: psycopg.Connection, administrator: Any, storage_root: Path
) -> None:
    # **The cap is on the files as well as on the rows, and this is the hole it
    # closes.** A one-row manifest declared alongside `MAX_BULK_ROWS + 1` names
    # passes a row-count check trivially and would produce a plan of four
    # hundred items for a batch that can create one Tile — and the screen would
    # then render every one of them. `MAX_BULK_ROWS`'s own docstring claims to
    # bound the report, and counting only one side would make that claim false.
    rows = [{"file": "a.jpg", "code": STRUCTURED_CODE, "size": SIZE, "category": CATEGORY}]

    response = ask_plan(
        client, sheet=manifest(rows), names=[f"{n}.jpg" for n in range(MAX_BULK_ROWS + 1)]
    )

    assert response.status_code == 422
    assert refusal(response)["code"] == "too_many_rows"
    assert "items" not in response.text
    nothing_was_written(conn, storage_root)


@needs_model
def test_exactly_the_cap_in_names_is_not_refused(client: TestClient, administrator: Any) -> None:
    # The boundary from the other side, so the bound cannot quietly become one
    # smaller than it says. Every name but the first is unmatched, which is the
    # plan saying so rather than a refusal.
    rows = [{"file": "a.jpg", "code": STRUCTURED_CODE, "size": SIZE, "category": CATEGORY}]
    names = ["a.jpg"] + [f"extra-{n}.jpg" for n in range(MAX_BULK_ROWS - 1)]

    response = ask_plan(client, sheet=manifest(rows), names=names)

    assert response.status_code == 200, response.text
    assert len(response.json()["items"]) == MAX_BULK_ROWS


@needs_model
def test_a_blank_line_in_the_sheet_is_not_a_row(client: TestClient, administrator: Any) -> None:
    # A trailing newline and the empty line a hand-edited sheet leaves behind
    # are not tiles the Administrator has to be told about.
    sheet = b"file,code,size,category\na.jpg,RP.CMA.0008DJ.SM.0T,45X90,CREMA MARMOL\n,,,\n\n"

    response = ask_plan(client, sheet=sheet, names=[])

    assert len(response.json()["items"]) == 1


def test_a_server_with_no_model_artifact_refuses_the_whole_batch(
    client: TestClient,
    conn: psycopg.Connection,
    administrator: Any,
    storage_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Pre-flighted in the plan rather than discovered on row 1, because
    # otherwise every row of a hundred fails identically — a report saying one
    # thing that belongs in an envelope.
    monkeypatch.setattr(shared_vision, "MODEL_PATH", tmp_path / "absent.onnx")

    response = ask_plan(
        client, sheet=manifest(THREE_ROWS), names=[name for name, _ in THREE_IMAGES]
    )

    assert response.status_code == 503
    assert refusal(response)["code"] == "matching_unavailable"
    assert "items" not in response.text
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

    response = ask_plan(
        client, sheet=manifest(THREE_ROWS), names=[name for name, _ in THREE_IMAGES]
    )

    assert response.status_code == 503
    assert refusal(response)["code"] == "pipeline_stamp_mismatch"
    assert "items" not in response.text
    for statement in (TILES, IMAGES, EMBEDDINGS):
        assert count(conn, statement) == 0, statement
    assert stored_objects(storage_root) == []


@needs_model
def test_a_stamp_that_goes_stale_mid_batch_is_answered_as_itself(
    client: TestClient, conn: psycopg.Connection, administrator: Any
) -> None:
    # The condition the plan pre-flights can still arrive *during* a batch —
    # a re-index started while an Administrator is a third of the way through
    # a range. It is answered as an envelope rather than as a report line,
    # because it will refuse every remaining row identically and the driver
    # should be told that once instead of a hundred times.
    rows = THREE_ROWS[:2]
    items = ask_plan(client, sheet=manifest(rows), names=["a.jpg", "b.jpg"]).json()["items"]

    assert send_item(client, items[0], THREE_IMAGES[0][1]).json()["status"] == "created"
    conn.execute(
        "UPDATE embedding_generation SET pipeline_version = %s WHERE is_active",
        ("not-this-pipeline",),
    )

    response = send_item(client, items[1], THREE_IMAGES[1][1])

    assert response.status_code == 503, response.text
    assert refusal(response)["code"] == "pipeline_stamp_mismatch"
    # The row that already landed is untouched: a batch-wide refusal is not a
    # rollback of the rows before it.
    assert count(conn, TILES) == 1


def test_a_cell_past_the_csv_field_limit_is_a_refusal_and_not_a_crash(
    client: TestClient, conn: psycopg.Connection, administrator: Any, storage_root: Path
) -> None:
    # `csv` raises `csv.Error` — not a `ValueError` anything would think to
    # catch — for a field past `csv.field_size_limit()`. Unguarded it escapes
    # the handler and becomes a `500`, where a spreadsheet this endpoint cannot
    # read is a `422` whatever shape the defect takes.
    enormous = "x" * (csv.field_size_limit() + 1)
    sheet = f'file,code,size,category\n"{enormous}",CODE,45X90,POLISH\n'.encode()

    response = ask_plan(client, sheet=sheet, names=[])

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

    response = ask_plan(client, sheet=sheet, names=[])

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

    response = ask_plan(client, sheet=sheet, names=[])

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

    batch = run(client, sheet=sheet, images=[THREE_IMAGES[0]])

    assert batch.plan.status_code == 200, batch.plan.text
    assert [line["status"] for line in batch.rows] == ["created"]
    # The Code came through without the mark attached to it either.
    assert batch.rows[0]["code"] == STRUCTURED_CODE


# --- What the two paths share -------------------------------------------------


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
    real_accept = catalogue._accept
    real_prepare = catalogue._prepare

    def watched_accept(upload: Any) -> Any:
        seen.append("accept")
        return real_accept(upload)

    def watched_prepare(tile_id: Any, accepted: Any) -> Any:
        seen.append("prepare")
        return real_prepare(tile_id, accepted)

    monkeypatch.setattr(catalogue, "_accept", watched_accept)
    monkeypatch.setattr(catalogue, "_prepare", watched_prepare)

    run(client, sheet=manifest(THREE_ROWS[:2]), images=THREE_IMAGES[:2])

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
    report = run(client, sheet=manifest(rows), images=[("a.jpg", image)]).rows
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
def test_neither_response_carries_a_similarity_value_or_a_storage_reference(
    client: TestClient, administrator: Any
) -> None:
    # AD-20 and AD-9, asserted on the wire. These are the newest surfaces in
    # the product and the easiest place for a score or a storage key to arrive
    # unnoticed, because neither shape is a declared contract the way `Tile`
    # is.
    batch = run(client, sheet=manifest(THREE_ROWS[:1]), images=[THREE_IMAGES[0]])

    assert set(batch.plan.json()["items"][0]) == {
        "row",
        "file",
        "code",
        "size",
        "category",
        "upload",
        "error",
    }
    assert set(batch.responses[0].json()) == {"status", "tile_id", "flags", "error"}
    for response in (batch.plan, *batch.responses):
        rendered = response.text.lower()
        for forbidden in (
            "score",
            "similarity",
            "confidence",
            "source_key",
            "derivative_key",
            "http",
        ):
            assert forbidden not in rendered, forbidden


@needs_model
def test_neither_response_leaves_the_domains_own_words(
    client: TestClient, administrator: Any
) -> None:
    # AD-18 retires `Product` and `Face`. `face_number` survives as a column
    # name and nothing on either of these carries it — the flag is
    # `unknown_face_number`, which is the exception the vocabulary rule makes
    # for the one permitted survivor, and no free prose here says either word.
    rows = [{"file": "a.jpg", "code": "", "size": SIZE, "category": CATEGORY}]

    batch = run(client, sheet=manifest(rows), images=[THREE_IMAGES[0]])

    for response in (batch.plan, *batch.responses):
        body = response.text.lower()
        # All three banned words, not just the one. `design` is the rename
        # AD-18 made and the easiest to reintroduce by habit; `face` is checked
        # as free prose only, since `unknown_face_number` is the permitted
        # survivor and is the one spelling that may appear.
        assert "product" not in body
        assert "design" not in body
        assert "face" not in body.replace("unknown_face_number", "").replace("face_number", "")


@needs_model
def test_a_tile_id_that_is_returned_is_the_one_that_was_written(
    client: TestClient, conn: psycopg.Connection, administrator: Any
) -> None:
    # The id on a created line is the handle the screen would use, so it has to
    # name the row that exists rather than a value invented for the report.
    report = run(client, sheet=manifest(THREE_ROWS[:1]), images=[THREE_IMAGES[0]]).rows

    written = conn.execute("SELECT id FROM tile").fetchone()
    assert written is not None
    assert report[0]["tile_id"] == str(written["id"])
    # And it is a real UUID on the wire rather than a string that happens to match.
    assert str(UUID(report[0]["tile_id"])) == report[0]["tile_id"]
