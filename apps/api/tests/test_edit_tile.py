"""`PATCH /admin/tiles/{tile_id}` — every row of Story 2.2's I/O matrix, through the route.

Driven against a real PostgreSQL with the shipped migrations and a real object
store, for `test_add_tile.py`'s reason: every claim here is about the seam
between them. What is written, what is *not* written when the request is
refused, and — the half this story adds — what is **removed**, both from the
index and from storage.

Three properties are easy to get wrong and are each pinned below:

* a rename touches no embedding row (re-embedding what was not uploaded is a
  re-index by another name, AD-14);
* a removal is a real `DELETE` whose embeddings cascade, and whose objects go
  **after** the commit, never before;
* an edit whose net effect is zero Reference Images is refused (FR-7), even
  though the removal and the replacement travel in one request.
"""

from __future__ import annotations

import io
import logging
import struct
import zlib
from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import numpy as np
import psycopg
import pytest
import shared_vision
from api import catalogue, storage
from fastapi.testclient import TestClient
from PIL import Image
from shared_schema.tile import (
    MAX_CATEGORY_LENGTH,
    MAX_CODE_LENGTH,
    MAX_IMAGES_PER_REQUEST,
    MAX_SIZE_LENGTH,
    UNKNOWN_CATEGORY,
)
from shared_schema.user import Role
from shared_vision import pipeline

MakeUser = Callable[..., Any]
AuditRows = Callable[[psycopg.Connection], list[dict[str, object]]]

ADD_TILE = "/admin/tiles"
LOGIN = "/auth/login"

CODE = "RP.CMA.0001DJ.SM.0T"
RENAMED = "RP.CMA.0002DJ.SM.0T"
SIZE = "45X90"
CATEGORY = "CREMA MARMOL"

needs_model = pytest.mark.skipif(
    not pipeline.MODEL_PATH.exists(),
    reason="model not downloaded; run `make model`",
)


# --- Fixtures and helpers -----------------------------------------------------


def a_tile_photograph(seed: int = 5, size: tuple[int, int] = (320, 320)) -> Image.Image:
    """A textured patch. Deliberately not flat — a plain colour is `featureless`."""
    rng = np.random.default_rng(seed)
    return Image.fromarray(rng.integers(0, 255, (size[1], size[0], 3), dtype=np.uint8), "RGB")


def jpeg_bytes(image: Image.Image | None = None, **save: Any) -> bytes:
    buf = io.BytesIO()
    (image or a_tile_photograph()).save(buf, format="JPEG", quality=92, **save)
    return buf.getvalue()


def png_bytes(image: Image.Image | None = None) -> bytes:
    buf = io.BytesIO()
    (image or a_tile_photograph()).save(buf, format="PNG")
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


def _after(before: Callable[[], None], original: Callable[..., Any]) -> Callable[..., Any]:
    """`original`, with `before` run first — a hook into a call the handler makes.

    `test_add_tile.py`'s helper, unchanged. Substituted for `catalogue._prepare`
    it fires after this request has passed its pre-flights and before its own
    `UPDATE`, which is precisely where a concurrent writer lands.
    """

    def hooked(*args: Any, **kwargs: Any) -> Any:
        before()
        return original(*args, **kwargs)

    return hooked


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


def add(
    client: TestClient,
    *,
    code: str = CODE,
    size: str = SIZE,
    category: str = CATEGORY,
    files: list[tuple[str, tuple[str, bytes, str]]] | None = None,
) -> Any:
    """One Tile, through the real add path, as the thing an edit then corrects."""
    if files is None:
        files = [("images", ("reference.jpg", jpeg_bytes(), "image/jpeg"))]
    response = client.post(
        ADD_TILE, data={"code": code, "size": size, "category": category}, files=files
    )
    assert response.status_code == 201, response.text
    return response.json()


def edit(
    client: TestClient,
    tile_id: str,
    *,
    files: list[tuple[str, tuple[str, bytes, str]]] | None = None,
    **fields: Any,
) -> Any:
    """`PATCH /admin/tiles/{id}` as a form. An omitted field is an absent part.

    A list value becomes one repeated part per item, which is how a multipart
    body expresses a list — `remove_image_ids` arrives exactly the way the
    screen's `FormData` sends it.
    """
    data: dict[str, Any] = {
        key: ([str(item) for item in value] if isinstance(value, list) else str(value))
        for key, value in fields.items()
        if value is not None
    }
    if files:
        return client.patch(f"{ADD_TILE}/{tile_id}", data=data, files=files)
    return client.patch(f"{ADD_TILE}/{tile_id}", data=data)


def stored_objects(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("*") if path.is_file())


def count(conn: psycopg.Connection, table_query: str) -> int:
    row = conn.execute(table_query).fetchone()
    assert row is not None
    return int(row["total"])


TILES = "SELECT count(*) AS total FROM tile"
IMAGES = "SELECT count(*) AS total FROM reference_image"
EMBEDDINGS = "SELECT count(*) AS total FROM reference_embedding"


def embedding_ids(conn: psycopg.Connection) -> set[UUID]:
    return {row["id"] for row in conn.execute("SELECT id FROM reference_embedding").fetchall()}


def edited_entries(conn: psycopg.Connection, rows: AuditRows) -> list[dict[str, object]]:
    return [row for row in rows(conn) if row["action"] == "catalogue_tile_edited"]


# --- Metadata: the rename, the Size, the Category -----------------------------


@needs_model
def test_renaming_the_code_moves_the_row_and_touches_no_embedding(
    client: TestClient,
    conn: psycopg.Connection,
    administrator: Any,
    audit_rows: AuditRows,
) -> None:
    created = add(client)
    before = embedding_ids(conn)

    response = edit(client, created["id"], code=RENAMED)

    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert body["code"] == RENAMED
    assert body["id"] == created["id"]
    # `updated_at` is set by hand — this schema has no BEFORE UPDATE trigger.
    assert body["updated_at"] > created["updated_at"]
    assert body["created_at"] == created["created_at"]

    # **No embedding row was rewritten.** Changing a Code changes no pixels,
    # and a rebuild of untouched embeddings is a re-index by another name.
    # Compared by row id rather than by count: a delete-and-reinsert of the
    # same sixteen vectors keeps the count identical and is exactly the thing
    # this asserts against.
    assert embedding_ids(conn) == before
    assert count(conn, IMAGES) == 1

    entries = edited_entries(conn, audit_rows)
    assert len(entries) == 1
    details = entries[0]["details"]
    assert isinstance(details, dict)
    assert details["changed"] == {"code": {"from": CODE, "to": RENAMED}}


@needs_model
def test_renaming_the_code_re_derives_the_trailing_number_it_carries(
    client: TestClient, conn: psycopg.Connection, administrator: Any
) -> None:
    # `face_number` is read off the Code and off nothing else, so the moment a
    # Code changes the stored hint is about a Code the Tile no longer carries.
    # Reachable since the bulk path started writing the column: a Tile added as
    # `...0008DJ...` (hint `8`) and renamed to a dash-delimited Code would go on
    # showing `8` for a Code that yields no number at all.
    created = add(client)
    # Autocommit — see the fixture. The column is arranged by hand because the
    # only writer of it is the bulk route, which is another story's suite.
    conn.execute("UPDATE tile SET face_number = %s WHERE id = %s", ("1", created["id"]))

    assert edit(client, created["id"], code=RENAMED).json()["face_number"] == "2"

    # And a Code that yields none clears it rather than leaving the old one.
    assert edit(client, created["id"], code="RC-001-OHA-156-MA-J2").json()["face_number"] is None


@needs_model
def test_an_edit_that_sends_no_code_leaves_the_trailing_number_alone(
    client: TestClient, conn: psycopg.Connection, administrator: Any
) -> None:
    # The mirror of the rule above, and the reason it is written as "re-derived
    # whenever the Code is" rather than "re-derived on every edit": an absent
    # part means unchanged for this column exactly as it does for every other
    # one, so renaming a Size may not quietly rewrite a hint nothing touched.
    created = add(client)
    conn.execute("UPDATE tile SET face_number = %s WHERE id = %s", ("7", created["id"]))

    assert edit(client, created["id"], size="60X60").json()["face_number"] == "7"


@needs_model
def test_the_size_and_category_resolve_through_the_same_normalized_lookup(
    client: TestClient, conn: psycopg.Connection, administrator: Any
) -> None:
    # The add's resolver, reused. Two writers resolving the same string through
    # two lookups is how `45X90`, `45x90` and `" 45X90 "` become three sizes
    # nothing can join on.
    created = add(client)

    body = edit(client, created["id"], size=" 60x60 ", category="Astoria").json()

    assert body["size"] == "60X60"
    assert body["category"] == "ASTORIA"
    # One row each, never a near-duplicate.
    assert count(conn, "SELECT count(*) AS total FROM tile_size WHERE name = '60X60'") == 1
    assert count(conn, "SELECT count(*) AS total FROM tile_category WHERE name = 'ASTORIA'") == 1


@needs_model
def test_a_blanked_category_resolves_to_the_sentinel_rather_than_being_dropped(
    client: TestClient, administrator: Any
) -> None:
    # AD-18. A Category that cannot be recovered is grouped under UNKNOWN and
    # flagged for follow-up; dropping the Tile over a grouping attribute that
    # is not its identity is the failure this sentinel exists to prevent.
    created = add(client)

    body = edit(client, created["id"], category="").json()

    assert body["category"] == UNKNOWN_CATEGORY


@needs_model
def test_an_absent_part_leaves_its_field_alone(client: TestClient, administrator: Any) -> None:
    # A multipart body has no `null` on the wire, so "absent" is the only way to
    # say "unchanged" — and a present-but-blank `code` has to stay a refusal.
    created = add(client)

    body = edit(client, created["id"], code=RENAMED).json()

    assert body["code"] == RENAMED
    assert body["size"] == SIZE
    assert body["category"] == CATEGORY


@needs_model
def test_a_patch_carrying_no_parts_at_all_changes_nothing(
    client: TestClient, conn: psycopg.Connection, administrator: Any, audit_rows: AuditRows
) -> None:
    # The degenerate case of "an absent part means unchanged", and the one that
    # says the rule holds when *every* part is absent. A handler that resolved
    # an absent field to its own default rather than to the stored value would
    # blank the Tile here and nowhere else.
    created = add(client)

    response = edit(client, created["id"])

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["code"] == CODE
    assert body["size"] == SIZE
    assert body["category"] == CATEGORY
    assert [image["id"] for image in body["reference_images"]] == [
        image["id"] for image in created["reference_images"]
    ]
    assert count(conn, EMBEDDINGS) == 16

    details = edited_entries(conn, audit_rows)[0]["details"]
    assert isinstance(details, dict)
    assert details["changed"] == {}


@needs_model
def test_a_tile_with_no_category_keeps_none_when_the_part_is_absent(
    client: TestClient, conn: psycopg.Connection, administrator: Any, audit_rows: AuditRows
) -> None:
    """A NULL `category_id` is a stored value, and "unchanged" has to mean it.

    `clean_category(None)` is the `UNKNOWN` sentinel, so a handler that resolved
    the stored Category unconditionally would refile such a Tile under the
    sentinel on an edit that only renamed it — and `details.changed` would
    report a move nobody asked for.

    The column is nullable in the ERD, and the endpoint never writes NULL
    itself, so the state is set up directly here.
    """
    created = add(client)
    conn.execute("UPDATE tile SET category_id = NULL WHERE id = %s", (created["id"],))

    response = edit(client, created["id"], code=RENAMED)

    assert response.status_code == 200, response.text
    assert response.json()["category"] is None
    row = conn.execute("SELECT category_id FROM tile WHERE id = %s", (created["id"],)).fetchone()
    assert row is not None and row["category_id"] is None

    details = edited_entries(conn, audit_rows)[0]["details"]
    assert isinstance(details, dict)
    assert details["changed"] == {"code": {"from": CODE, "to": RENAMED}}


@needs_model
def test_a_tile_with_no_category_takes_one_when_the_part_is_sent(
    client: TestClient, conn: psycopg.Connection, administrator: Any
) -> None:
    # The other half: leaving NULL alone is about the *absent* part, not about
    # the column being unwritable. A Category that is sent still lands.
    created = add(client)
    conn.execute("UPDATE tile SET category_id = NULL WHERE id = %s", (created["id"],))

    assert edit(client, created["id"], category="Astoria").json()["category"] == "ASTORIA"


@needs_model
def test_an_edit_that_changes_nothing_is_accepted_and_recorded_as_nothing(
    client: TestClient, conn: psycopg.Connection, administrator: Any, audit_rows: AuditRows
) -> None:
    # The honest record of an accepted edit that moved nothing. An entry
    # claiming a change that did not happen is worse than a terse one, because
    # nothing downstream can tell it from a real one.
    created = add(client)

    response = edit(client, created["id"], code=CODE, size=SIZE, category=CATEGORY)

    assert response.status_code == 200
    entries = edited_entries(conn, audit_rows)
    assert len(entries) == 1
    details = entries[0]["details"]
    assert isinstance(details, dict)
    assert details["changed"] == {}
    assert details["images_added"] == 0
    assert details["images_removed"] == 0


@needs_model
def test_saving_an_untouched_code_is_not_a_conflict_with_the_tile_itself(
    client: TestClient, administrator: Any
) -> None:
    # The screen's form is prefilled, so it sends the Code on every save. A
    # duplicate pre-flight that did not exclude the row being edited would
    # answer `409` against the very Tile the Administrator is correcting.
    created = add(client)

    assert edit(client, created["id"], code=CODE, size="60X60").status_code == 200


# --- Adding a Reference Image -------------------------------------------------


@needs_model
def test_a_new_image_is_intaken_embedded_and_stored_like_any_other(
    client: TestClient, conn: psycopg.Connection, administrator: Any, storage_root: Path
) -> None:
    created = add(client)
    assert count(conn, EMBEDDINGS) == shared_vision.VIEWS_PER_IMAGE == 16
    assert len(stored_objects(storage_root)) == 2
    before = embedding_ids(conn)

    response = edit(
        client,
        created["id"],
        files=[("images", ("second.jpg", jpeg_bytes(a_tile_photograph(9)), "image/jpeg"))],
    )

    assert response.status_code == 200, response.text
    assert len(response.json()["reference_images"]) == 2
    assert count(conn, IMAGES) == 2
    # 16 more, in the same active generation — never pooled (AD-13).
    assert count(conn, EMBEDDINGS) == 32
    # By id, not only by count, for the rename test's reason one story on: a
    # delete-and-reinsert of the first image's sixteen vectors keeps the count
    # at 32 and is still the re-index this endpoint must never perform. Only the
    # uploaded image's rows are new.
    assert before < embedding_ids(conn)
    generations = conn.execute("SELECT count(*) AS total FROM embedding_generation").fetchone()
    assert generations is not None and generations["total"] == 1
    # Two objects per image: the retained source and AD-17's capped derivative.
    assert len(stored_objects(storage_root)) == 4


@needs_model
def test_a_png_named_jpg_is_accepted_and_an_executable_named_jpg_is_not(
    client: TestClient, conn: psycopg.Connection, administrator: Any, storage_root: Path
) -> None:
    # Content decides, never the extension or the client's `content-type`
    # (AGENTS.md Policy). The same rule the add path applies, through the same
    # intake function — this is what "reuse `_accept`" buys.
    created = add(client)
    before = stored_objects(storage_root)

    accepted = edit(
        client, created["id"], files=[("images", ("lying.jpg", png_bytes(), "image/jpeg"))]
    )
    assert accepted.status_code == 200, accepted.text
    assert count(conn, IMAGES) == 2

    refused = edit(
        client,
        created["id"],
        files=[("images", ("lying.jpg", b"MZ\x90\x00not an image at all", "image/jpeg"))],
    )
    assert refused.status_code == 422
    assert refused.json()["error"]["code"] == "unreadable_image"
    # The accepted one is still there; the refused one left nothing behind.
    assert count(conn, IMAGES) == 2
    assert len(stored_objects(storage_root)) == len(before) + 2


@needs_model
def test_more_new_images_than_the_endpoint_accepts_are_refused(
    client: TestClient, conn: psycopg.Connection, administrator: Any, storage_root: Path
) -> None:
    created = add(client)
    before = stored_objects(storage_root)

    response = edit(
        client,
        created["id"],
        files=[
            ("images", (f"{index}.jpg", jpeg_bytes(), "image/jpeg"))
            for index in range(MAX_IMAGES_PER_REQUEST + 1)
        ],
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "too_many_images"
    assert str(MAX_IMAGES_PER_REQUEST) in response.json()["error"]["message"]
    assert count(conn, IMAGES) == 1
    assert stored_objects(storage_root) == before


@needs_model
def test_an_oversized_image_is_refused_before_it_is_decoded(
    client: TestClient,
    conn: psycopg.Connection,
    administrator: Any,
    storage_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # `_read_upload`'s ceiling, reached through the edit. Lowered rather than
    # allocating 128 MB in a unit test: what is under test is the comparison.
    #
    # **"Before" is the claim, so it is the thing asserted.** One byte past the
    # ceiling is enough to refuse and nothing reads the rest — so the bytes
    # never reach `intake_image` and therefore never reach the embedder either.
    # A status code alone would pass just as well for a gate that decoded the
    # file first and checked its size afterwards.
    created = add(client)

    def refuse(*_: Any, **__: Any) -> None:
        raise AssertionError("an oversized file reached shared_vision")

    monkeypatch.setattr(catalogue, "MAX_IMAGE_BYTES", 1024)
    monkeypatch.setattr(shared_vision, "intake_image", refuse)
    monkeypatch.setattr(shared_vision, "embed_images", refuse)

    response = edit(
        client, created["id"], files=[("images", ("big.jpg", b"x" * 4096, "image/jpeg"))]
    )

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "image_too_large"
    assert count(conn, IMAGES) == 1
    assert len(stored_objects(storage_root)) == 2


@needs_model
def test_an_image_claiming_too_many_pixels_is_refused_off_its_header(
    client: TestClient,
    conn: psycopg.Connection,
    administrator: Any,
    storage_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The other half of the ceiling. `MAX_IMAGE_BYTES` bounds the *file*; this
    # bounds what decoding it would cost, and it has to be answered off the
    # header — the file below is a few hundred bytes and claims 400 megapixels,
    # so a gate that decoded first would allocate 1.2 GB before it found out.
    created = add(client)

    def refuse(*_: object, **__: object) -> None:
        raise AssertionError("an oversized image reached the embedder")

    monkeypatch.setattr(shared_vision, "embed_images", refuse)

    response = edit(
        client,
        created["id"],
        files=[("images", ("huge.png", a_png_header_claiming(20_000, 20_001), "image/png"))],
    )

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "image_too_large"
    # The tile is exactly as it was: one image, its sixteen views, its two
    # objects. A refusal that had already written the new image's bytes would
    # leave the third and fourth object behind.
    assert count(conn, IMAGES) == 1
    assert count(conn, EMBEDDINGS) == shared_vision.VIEWS_PER_IMAGE
    assert len(stored_objects(storage_root)) == 2


# --- Removing a Reference Image -----------------------------------------------


@needs_model
def test_removing_an_image_removes_its_row_its_embeddings_and_its_objects(
    client: TestClient, conn: psycopg.Connection, administrator: Any, storage_root: Path
) -> None:
    created = add(
        client,
        files=[
            ("images", ("a.jpg", jpeg_bytes(a_tile_photograph(1)), "image/jpeg")),
            ("images", ("b.jpg", jpeg_bytes(a_tile_photograph(2)), "image/jpeg")),
        ],
    )
    assert count(conn, EMBEDDINGS) == 32
    assert len(stored_objects(storage_root)) == 4
    doomed = created["reference_images"][0]["id"]

    response = edit(client, created["id"], remove_image_ids=[doomed])

    assert response.status_code == 200, response.text
    assert [image["id"] for image in response.json()["reference_images"]] == [
        created["reference_images"][1]["id"]
    ]
    assert count(conn, IMAGES) == 1
    # Real removal (AD-5): the 16 embeddings cascaded out of the index rather
    # than being filtered at query time by a predicate a call site can forget.
    assert count(conn, EMBEDDINGS) == 16
    # And both of its stored objects went with it, after the commit.
    assert len(stored_objects(storage_root)) == 2


@needs_model
def test_storage_refusing_to_delete_does_not_undo_a_committed_edit(
    client: TestClient,
    conn: psycopg.Connection,
    administrator: Any,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The post-commit `_discard`, which is the whole reason `why` exists.

    The rows are already gone when this runs, so a store that will not delete
    leaves an orphaned object — recoverable — while raising would turn an edit
    the Administrator's catalogue has already accepted into a `500` they cannot
    act on and cannot retry. Asserted through a store whose `delete` raises,
    because a passing filesystem store never reaches the `except`.
    """
    created = add(
        client,
        files=[
            ("images", ("a.jpg", jpeg_bytes(a_tile_photograph(1)), "image/jpeg")),
            ("images", ("b.jpg", jpeg_bytes(a_tile_photograph(2)), "image/jpeg")),
        ],
    )
    doomed = created["reference_images"][0]["id"]

    refused: list[str] = []

    def will_not_delete(self: Any, key: str) -> None:
        refused.append(key)
        raise OSError("storage is read-only")

    monkeypatch.setattr(storage.FilesystemObjectStore, "delete", will_not_delete)

    with caplog.at_level(logging.WARNING, logger=catalogue.logger.name):
        response = edit(client, created["id"], remove_image_ids=[doomed])

    # The edit stands: the row and its embeddings are gone from the index, which
    # is what the Administrator asked for and what the commit already recorded.
    assert response.status_code == 200, response.text
    assert count(conn, IMAGES) == 1
    assert count(conn, EMBEDDINGS) == 16
    # And it really did try — a `_discard` call that was quietly skipped would
    # satisfy every assertion above.
    assert len(refused) == 2
    # The warning says *which* orphan this is. `why` reaches the log line and
    # nothing else, so without this the two constants could be swapped, or the
    # third argument dropped at the post-commit call site, and every other
    # assertion in the suite would still pass — while the operator reading the
    # warning would be told a committed removal was a write that rolled back.
    warnings = [
        record.getMessage() for record in caplog.records if record.levelno >= logging.WARNING
    ]
    assert len(warnings) == 2
    assert all(catalogue.DISCARD_REMOVED in message for message in warnings)
    assert not any(catalogue.DISCARD_ROLLED_BACK in message for message in warnings)


@needs_model
def test_a_removal_and_a_replacement_travel_in_one_request(
    client: TestClient, conn: psycopg.Connection, administrator: Any, storage_root: Path
) -> None:
    # The whole reason the two halves are one endpoint. Removing the only image
    # is refused on its own (below) and accepted here, because the net is one.
    created = add(client)
    only = created["reference_images"][0]["id"]
    old_embeddings = embedding_ids(conn)

    response = edit(
        client,
        created["id"],
        remove_image_ids=[only],
        files=[("images", ("replacement.jpg", jpeg_bytes(a_tile_photograph(7)), "image/jpeg"))],
    )

    assert response.status_code == 200, response.text
    images = response.json()["reference_images"]
    assert len(images) == 1
    assert images[0]["id"] != only
    assert count(conn, IMAGES) == 1
    assert count(conn, EMBEDDINGS) == 16
    # The old sixteen are gone and the new sixteen are not them.
    assert embedding_ids(conn).isdisjoint(old_embeddings)
    assert len(stored_objects(storage_root)) == 2


@needs_model
def test_naming_the_same_image_twice_removes_it_once(
    client: TestClient, conn: psycopg.Connection, administrator: Any
) -> None:
    # A repeated id is a request for that image to be gone, which is what the
    # caller gets. Refusing it would be refusing a well-formed intention.
    created = add(
        client,
        files=[
            ("images", ("a.jpg", jpeg_bytes(a_tile_photograph(1)), "image/jpeg")),
            ("images", ("b.jpg", jpeg_bytes(a_tile_photograph(2)), "image/jpeg")),
        ],
    )
    doomed = created["reference_images"][0]["id"]

    response = edit(client, created["id"], remove_image_ids=[doomed, doomed])

    assert response.status_code == 200, response.text
    assert count(conn, IMAGES) == 1


@needs_model
def test_an_id_padded_with_whitespace_still_names_its_image(
    client: TestClient, conn: psycopg.Connection, administrator: Any
) -> None:
    # A Code pasted with padding is trimmed by `clean_code`; an id pasted the
    # same way must not refuse the whole edit over whitespace nobody can see.
    created = add(
        client,
        files=[
            ("images", ("a.jpg", jpeg_bytes(a_tile_photograph(1)), "image/jpeg")),
            ("images", ("b.jpg", jpeg_bytes(a_tile_photograph(2)), "image/jpeg")),
        ],
    )
    doomed = created["reference_images"][0]["id"]

    response = edit(client, created["id"], remove_image_ids=[f"  {doomed}\n"])

    assert response.status_code == 200, response.text
    assert count(conn, IMAGES) == 1


@needs_model
def test_removing_the_last_image_is_refused_and_writes_nothing(
    client: TestClient,
    conn: psycopg.Connection,
    administrator: Any,
    storage_root: Path,
    audit_rows: AuditRows,
) -> None:
    # FR-7. A Tile with no Reference Image is a catalogue row no member of staff
    # can verify and no Scan can return.
    created = add(client)
    before = stored_objects(storage_root)
    only = created["reference_images"][0]["id"]

    response = edit(client, created["id"], code=RENAMED, remove_image_ids=[only])

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "last_reference_image"
    # Nothing at all: not the image, not the rename that travelled with it.
    assert count(conn, IMAGES) == 1
    assert count(conn, EMBEDDINGS) == 16
    assert stored_objects(storage_root) == before
    row = conn.execute("SELECT code FROM tile WHERE id = %s", (created["id"],)).fetchone()
    assert row is not None and row["code"] == CODE
    assert edited_entries(conn, audit_rows) == []


@needs_model
def test_removing_every_image_of_a_two_image_tile_is_refused(
    client: TestClient, conn: psycopg.Connection, administrator: Any
) -> None:
    created = add(
        client,
        files=[
            ("images", ("a.jpg", jpeg_bytes(a_tile_photograph(1)), "image/jpeg")),
            ("images", ("b.jpg", jpeg_bytes(a_tile_photograph(2)), "image/jpeg")),
        ],
    )

    response = edit(
        client,
        created["id"],
        remove_image_ids=[image["id"] for image in created["reference_images"]],
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "last_reference_image"
    assert count(conn, IMAGES) == 2


@needs_model
def test_a_concurrent_removal_cannot_leave_a_tile_with_no_image(
    client: TestClient,
    conn: psycopg.Connection,
    administrator: Any,
    storage_root: Path,
    audit_rows: AuditRows,
) -> None:
    """FR-7's floor, under the lock rather than under the pre-flight.

    Two edits of one two-image Tile, each removing a different image and neither
    uploading a replacement: both pass the pre-flight, because neither can see
    the other's uncommitted `DELETE`, and a handler that trusted its pre-flight
    would commit both and leave the Tile with no Reference Image at all.

    The window is opened the way the rename clash opens its own — by hooking
    `catalogue._prepare`, which runs after the pre-flights and before the
    transaction. There is nothing to prepare on an edit that uploads nothing, so
    the hook rides `_removals` instead: it is called once outside the
    transaction and once inside it, and the delete lands between them.
    """
    created = add(
        client,
        files=[
            ("images", ("a.jpg", jpeg_bytes(a_tile_photograph(1)), "image/jpeg")),
            ("images", ("b.jpg", jpeg_bytes(a_tile_photograph(2)), "image/jpeg")),
        ],
    )
    mine, sibling = (image["id"] for image in created["reference_images"])
    before = stored_objects(storage_root)

    real = catalogue._removals
    seen: list[int] = []

    def racing(*args: Any, **kwargs: Any) -> Any:
        # Counted *before* the call, not after: the whole point is that the
        # second call raises, so a counter incremented afterwards would never
        # record it and this test would pass for the wrong reason.
        seen.append(1)
        outcome = real(*args, **kwargs)
        if len(seen) == 1:
            # The pre-flight has just passed. The concurrent delete lands here,
            # so the re-check inside the transaction is the call that has to
            # refuse.
            conn.execute("DELETE FROM reference_image WHERE id = %s", (sibling,))
        return outcome

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(catalogue, "_removals", racing)
        response = edit(client, created["id"], remove_image_ids=[mine])

    assert len(seen) == 2, "the removal set is checked once outside the lock and once inside it"
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "last_reference_image"
    # The survivor is still there, and the losing edit wrote nothing.
    assert count(conn, IMAGES) == 1
    row = conn.execute(
        "SELECT count(*) AS total FROM reference_image WHERE id = %s", (mine,)
    ).fetchone()
    assert row is not None and row["total"] == 1
    assert stored_objects(storage_root) == before
    assert edited_entries(conn, audit_rows) == []


@needs_model
def test_another_tiles_image_is_a_404_that_names_neither_tile(
    client: TestClient, conn: psycopg.Connection, administrator: Any
) -> None:
    # One answer for "no such image" and "that image belongs to another tile":
    # they are the same fact to a caller holding an id that names nothing of
    # *this* Tile, and telling them apart would confirm which ids exist.
    mine = add(client)
    theirs = add(client, code="SOMEBODY-ELSE")
    borrowed = theirs["reference_images"][0]["id"]

    response = edit(client, mine["id"], remove_image_ids=[borrowed])

    assert response.status_code == 404
    body = response.json()["error"]
    assert body["code"] == "image_not_found"
    assert mine["id"] not in body["message"]
    assert theirs["id"] not in body["message"]
    assert borrowed not in body["message"]
    # And the other Tile's image is untouched.
    assert count(conn, IMAGES) == 2


@needs_model
@pytest.mark.parametrize("value", ["not-a-uuid", "00000000-0000-4000-8000-000000000000"])
def test_an_id_that_names_no_image_of_this_tile_is_a_404(
    client: TestClient, conn: psycopg.Connection, administrator: Any, value: str
) -> None:
    # A malformed id and an unknown one are the same fact. A malformed one must
    # not fall through to the generic `422 validation_error`, which names no
    # field and tells the Administrator nothing they can act on.
    created = add(client)

    response = edit(client, created["id"], remove_image_ids=[value])

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "image_not_found"
    assert count(conn, IMAGES) == 1


# --- The refusals -------------------------------------------------------------


def test_an_unknown_tile_is_a_404_refused_before_any_decode(
    client: TestClient,
    conn: psycopg.Connection,
    administrator: Any,
    storage_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def refuse(*_: object, **__: object) -> None:
        raise AssertionError("an unknown tile's bytes reached shared_vision")

    monkeypatch.setattr(shared_vision, "intake_image", refuse)

    response = edit(
        client,
        str(uuid4()),
        code=RENAMED,
        files=[("images", ("x.jpg", jpeg_bytes(), "image/jpeg"))],
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "tile_not_found"
    assert count(conn, TILES) == 0
    assert stored_objects(storage_root) == []


@needs_model
@pytest.mark.parametrize(
    ("label", "fields", "code"),
    [
        ("a blank code", {"code": ""}, "invalid_code"),
        ("an overlong code", {"code": "X" * (MAX_CODE_LENGTH + 1)}, "invalid_code"),
        ("a blank size", {"size": ""}, "invalid_size"),
        ("an overlong size", {"size": "X" * (MAX_SIZE_LENGTH + 1)}, "invalid_size"),
        # A Category cannot be refused for being *blank* — that resolves to the
        # UNKNOWN sentinel (AD-18) — so the length ceiling is the only way this
        # code is ever reached, and without a row here nothing drives the
        # `except ValueError` that turns it into a named 422 instead of a 500.
        ("an overlong category", {"category": "X" * (MAX_CATEGORY_LENGTH + 1)}, "invalid_category"),
    ],
)
def test_a_field_the_endpoint_will_not_store_is_refused_by_name(
    client: TestClient,
    conn: psycopg.Connection,
    administrator: Any,
    label: str,
    fields: dict[str, str],
    code: str,
) -> None:
    # A code of its own rather than the generic `validation_error`, so the
    # screen can mark the one control the Administrator has to fix.
    created = add(client)

    response = edit(client, created["id"], **fields)

    assert response.status_code == 422, label
    assert response.json()["error"]["code"] == code, label
    row = conn.execute("SELECT code FROM tile WHERE id = %s", (created["id"],)).fetchone()
    assert row is not None and row["code"] == CODE


@needs_model
def test_renaming_onto_a_taken_code_is_refused_and_removes_what_it_wrote(
    client: TestClient,
    conn: psycopg.Connection,
    administrator: Any,
    storage_root: Path,
    audit_rows: AuditRows,
) -> None:
    add(client, code="TAKEN")
    mine = add(client)
    before = stored_objects(storage_root)

    response = edit(
        client,
        mine["id"],
        code="TAKEN",
        files=[("images", ("extra.jpg", jpeg_bytes(a_tile_photograph(3)), "image/jpeg"))],
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "code_already_exists"
    assert count(conn, IMAGES) == 2
    # Every object this request wrote was removed with the transaction.
    assert stored_objects(storage_root) == before
    assert edited_entries(conn, audit_rows) == []


@needs_model
def test_the_unique_constraint_is_still_what_decides_a_rename_clash(
    client: TestClient, conn: psycopg.Connection, administrator: Any, storage_root: Path
) -> None:
    """The pre-flight is an optimisation; the index is the decision.

    Two requests claiming one Code can both pass the `SELECT` — neither can see
    the other's uncommitted row — so the `UniqueViolation` catch is what
    actually separates them. Driven by writing the clashing row *after* this
    request's pre-flight and before its `UPDATE`, which is exactly the window a
    concurrent writer occupies.
    """
    mine = add(client)
    clash_id = uuid4()

    def insert_the_clash() -> None:
        conn.execute(
            "INSERT INTO tile (id, code, size_id) "
            "VALUES (%s, %s, (SELECT id FROM tile_size LIMIT 1))",
            (clash_id, RENAMED),
        )

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(catalogue, "_prepare", _after(insert_the_clash, catalogue._prepare))
        response = edit(
            client,
            mine["id"],
            code=RENAMED,
            files=[("images", ("extra.jpg", jpeg_bytes(a_tile_photograph(4)), "image/jpeg"))],
        )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "code_already_exists"
    row = conn.execute("SELECT code FROM tile WHERE id = %s", (mine["id"],)).fetchone()
    assert row is not None and row["code"] == CODE
    assert count(conn, IMAGES) == 1
    assert len(stored_objects(storage_root)) == 2


@needs_model
def test_a_tile_removed_under_the_lock_is_a_404_and_not_a_500(
    client: TestClient,
    conn: psycopg.Connection,
    administrator: Any,
    storage_root: Path,
    audit_rows: AuditRows,
) -> None:
    """The locked read is the decision, and it has to be driven to prove it.

    The `404` above is the pre-flight's, reached before anything is decoded. The
    handler makes the same refusal a second time inside the transaction, under
    the Tile's own row lock, precisely because the pre-flight can be overtaken —
    and that branch is what stands between "the tile went while you were
    uploading" and an `assert` firing two statements later as a `500`. The
    screen tells the two apart: only `tile_not_found` tears the edit form down
    and hands focus back to the lookup.

    Driven the way the rename clash above is: by writing the concurrent change
    after this request's pre-flight and before its `UPDATE`.
    """
    mine = add(client)
    before = stored_objects(storage_root)

    def delete_the_tile() -> None:
        conn.execute("DELETE FROM tile WHERE id = %s", (mine["id"],))

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(catalogue, "_prepare", _after(delete_the_tile, catalogue._prepare))
        response = edit(
            client,
            mine["id"],
            code=RENAMED,
            files=[("images", ("extra.jpg", jpeg_bytes(a_tile_photograph(5)), "image/jpeg"))],
        )

    assert response.status_code == 404, response.text
    assert response.json()["error"]["code"] == "tile_not_found"
    # The upload was already on disk when the lock answered, so the rollback has
    # to take it back out: an orphaned object is this endpoint's one unforced
    # error.
    assert stored_objects(storage_root) == before
    assert edited_entries(conn, audit_rows) == []


@needs_model
def test_a_corrupt_second_file_leaves_no_partial_edit(
    client: TestClient,
    conn: psycopg.Connection,
    administrator: Any,
    storage_root: Path,
    audit_rows: AuditRows,
) -> None:
    # "Nothing stored, nothing removed, no partial edit" — the removal in the
    # same request must not land either.
    created = add(
        client,
        files=[
            ("images", ("a.jpg", jpeg_bytes(a_tile_photograph(1)), "image/jpeg")),
            ("images", ("b.jpg", jpeg_bytes(a_tile_photograph(2)), "image/jpeg")),
        ],
    )
    before = stored_objects(storage_root)

    response = edit(
        client,
        created["id"],
        code=RENAMED,
        remove_image_ids=[created["reference_images"][0]["id"]],
        files=[
            ("images", ("good.jpg", jpeg_bytes(a_tile_photograph(8)), "image/jpeg")),
            ("images", ("bad.jpg", b"", "image/jpeg")),
        ],
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "unreadable_image"
    assert count(conn, IMAGES) == 2
    assert count(conn, EMBEDDINGS) == 32
    assert stored_objects(storage_root) == before
    row = conn.execute("SELECT code FROM tile WHERE id = %s", (created["id"],)).fetchone()
    assert row is not None and row["code"] == CODE
    assert edited_entries(conn, audit_rows) == []


@needs_model
def test_a_bad_second_file_is_refused_before_the_first_is_embedded(
    client: TestClient, administrator: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Cost, not correctness: every file is read and taken through intake before
    # any of them is embedded, so the refusal lands in milliseconds instead of
    # after sixteen forward passes on the good file that are then thrown away.
    created = add(client)

    def refuse(*_: Any, **__: Any) -> None:
        raise AssertionError("the good image was embedded before the bad one was refused")

    monkeypatch.setattr(shared_vision, "embed_images", refuse)

    response = edit(
        client,
        created["id"],
        files=[
            ("images", ("good.jpg", jpeg_bytes(), "image/jpeg")),
            ("images", ("bad.jpg", b"", "image/jpeg")),
        ],
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "unreadable_image"


@needs_model
def test_an_audit_failure_takes_the_whole_edit_down_with_it(
    client: TestClient,
    conn: psycopg.Connection,
    administrator: Any,
    storage_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The edit and its entry are one unit of work, proved by breaking one half.

    A Tile changed without a record of who changed it is the state AD-4 and
    FR-20 exist to prevent, and it is not visible from the outside — the only
    way to assert the transaction is really shared is to make the second write
    fail and check the first did not survive.
    """
    created = add(
        client,
        files=[
            ("images", ("a.jpg", jpeg_bytes(a_tile_photograph(1)), "image/jpeg")),
            ("images", ("b.jpg", jpeg_bytes(a_tile_photograph(2)), "image/jpeg")),
        ],
    )
    before = stored_objects(storage_root)

    def refuse(*_: Any, **__: Any) -> None:
        raise psycopg.errors.InsufficientPrivilege("no INSERT on the audit table")

    monkeypatch.setattr(catalogue.audit, "record", refuse)

    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        edit(
            client,
            created["id"],
            code=RENAMED,
            remove_image_ids=[created["reference_images"][0]["id"]],
        )

    row = conn.execute("SELECT code FROM tile WHERE id = %s", (created["id"],)).fetchone()
    assert row is not None and row["code"] == CODE
    assert count(conn, IMAGES) == 2
    assert count(conn, EMBEDDINGS) == 32
    # The removed image's objects are still there: they are deleted only after
    # a commit that never happened.
    assert stored_objects(storage_root) == before


# --- The model is a prerequisite only where pixels are ------------------------


@needs_model
def test_a_missing_model_artifact_refuses_an_edit_that_uploads(
    client: TestClient,
    conn: psycopg.Connection,
    administrator: Any,
    storage_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    created = add(client)
    before = stored_objects(storage_root)

    monkeypatch.setattr(pipeline, "_session", None)
    monkeypatch.setattr(pipeline, "MODEL_PATH", tmp_path / "absent" / "model.onnx")

    response = edit(
        client, created["id"], files=[("images", ("x.jpg", jpeg_bytes(), "image/jpeg"))]
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "matching_unavailable"
    assert "make model" in response.json()["error"]["message"]
    assert count(conn, IMAGES) == 1
    assert stored_objects(storage_root) == before


@needs_model
def test_a_rename_does_not_need_the_model_at_all(
    client: TestClient,
    conn: psycopg.Connection,
    administrator: Any,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # A rename embeds nothing, so it must not need the artifact. An edit path
    # that resolved the session unconditionally — or re-embedded what it did not
    # receive — would fail here and nowhere else.
    created = add(client)

    monkeypatch.setattr(pipeline, "_session", None)
    monkeypatch.setattr(pipeline, "MODEL_PATH", tmp_path / "absent" / "model.onnx")

    response = edit(client, created["id"], code=RENAMED)

    assert response.status_code == 200, response.text
    assert response.json()["code"] == RENAMED
    assert count(conn, EMBEDDINGS) == 16


@needs_model
def test_a_foreign_stamp_refuses_the_edit_before_anything_is_embedded(
    client: TestClient,
    conn: psycopg.Connection,
    administrator: Any,
    storage_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # AD-14: a mismatch is a hard error, not a degraded write — and it is
    # refused in milliseconds rather than after sixteen forward passes.
    created = add(client)
    before = stored_objects(storage_root)
    conn.execute(
        "UPDATE embedding_generation SET pipeline_version = %s",
        ("dinov2b-224-something-else",),
    )

    def refuse(*_: Any, **__: Any) -> None:
        raise AssertionError("the stamp mismatch reached the embedding path")

    monkeypatch.setattr(shared_vision, "embed_images", refuse)

    response = edit(
        client, created["id"], files=[("images", ("x.jpg", jpeg_bytes(), "image/jpeg"))]
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "pipeline_stamp_mismatch"
    assert count(conn, IMAGES) == 1
    assert stored_objects(storage_root) == before


# --- The response shape -------------------------------------------------------


@needs_model
def test_the_response_carries_no_similarity_value_and_no_storage_reference(
    client: TestClient, administrator: Any
) -> None:
    # AD-20 and AD-9, asserted on the wire rather than on the model.
    created = add(client)

    body = edit(client, created["id"], code=RENAMED).json()
    rendered = str(body).lower()

    assert set(body) == set(created)
    assert set(body["reference_images"][0]) == set(created["reference_images"][0])
    for forbidden in ("score", "similarity", "source_key", "derivative_key", "url", "http"):
        assert forbidden not in rendered, rendered
