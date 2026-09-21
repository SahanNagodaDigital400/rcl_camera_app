"""`DELETE /admin/tiles/{tile_id}` — every row of Story 2.3's I/O matrix, through the route.

Driven against a real PostgreSQL with the shipped migrations and a real object
store, for `test_add_tile.py`'s reason: every claim here is about the seam
between them, and this story's claims are almost all about *absence* — what is
no longer in three tables, what is no longer in the store, and what is still
there when the removal is refused.

Three properties are easy to get wrong and are each pinned below:

* the removal is **one** `DELETE`, and the migration's cascades carry
  `reference_image` and `reference_embedding` out with it (AD-5) — nothing here
  deletes a child by hand, so a story that drops a cascade fails here;
* the objects go **after** the commit, best effort, so a store that will not
  delete leaves an orphan rather than turning a committed removal into a `500`;
* an unknown id is a `404` and not a courteous `204` — a caller told "removed"
  about a Tile that was never there has been told they removed something they
  did not.

`test_removed_tile_unsearchable.py` is the other half: this file counts rows,
that one asks the search.
"""

from __future__ import annotations

import io
import logging
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import uuid4

import numpy as np
import psycopg
import pytest
from api import audit as audit_module
from api import catalogue, storage
from fastapi.testclient import TestClient
from PIL import Image
from shared_schema.user import Role
from shared_vision import pipeline

MakeUser = Callable[..., Any]
AuditRows = Callable[[psycopg.Connection], list[dict[str, object]]]

ADD_TILE = "/admin/tiles"
LOGIN = "/auth/login"

CODE = "RP.CMA.0001DJ.SM.0T"
OTHER_CODE = "RP.CMA.0002DJ.SM.0T"
SIZE = "45X90"
CATEGORY = "CREMA MARMOL"

REMOVED_ACTION = "catalogue_tile_removed"

needs_model = pytest.mark.skipif(
    not pipeline.MODEL_PATH.exists(),
    reason="model not downloaded; run `make model`",
)

#: How long the lock test waits before deciding the removal really is blocked,
#: and how long it then allows for the answer once the lock is released. The
#: first is short because a *passing* run pays it every time; the second is
#: generous because a slow machine failing it would be a flake rather than a
#: finding.
LOCK_WAIT_SECONDS = 0.75
LOCK_RELEASE_SECONDS = 30.0

#: How long the winner of two concurrent removals is held inside its
#: transaction, so that the loser really does arrive while the row lock is still
#: taken rather than tidily after the commit. Without it the two would usually
#: just follow one another and the test would assert nothing about contention.
LOCK_OVERLAP_SECONDS = 0.25


# --- Fixtures and helpers -----------------------------------------------------


def a_tile_photograph(seed: int = 5, size: tuple[int, int] = (320, 320)) -> Image.Image:
    """A textured patch. Deliberately not flat — a plain colour is `featureless`."""
    rng = np.random.default_rng(seed)
    return Image.fromarray(rng.integers(0, 255, (size[1], size[0], 3), dtype=np.uint8), "RGB")


def jpeg_bytes(image: Image.Image | None = None, **save: Any) -> bytes:
    buf = io.BytesIO()
    (image or a_tile_photograph()).save(buf, format="JPEG", quality=92, **save)
    return buf.getvalue()


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
    images: int = 1,
) -> Any:
    """One Tile, through the real add path, as the thing a removal then takes out."""
    response = client.post(
        ADD_TILE,
        data={"code": code, "size": size, "category": category},
        files=[
            (
                "images",
                (f"reference-{index}.jpg", jpeg_bytes(a_tile_photograph(index)), "image/jpeg"),
            )
            for index in range(images)
        ],
    )
    assert response.status_code == 201, response.text
    return response.json()


def remove(client: TestClient, tile_id: str) -> Any:
    return client.delete(f"{ADD_TILE}/{tile_id}")


def stored_objects(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("*") if path.is_file())


def count(conn: psycopg.Connection, table_query: str) -> int:
    row = conn.execute(table_query).fetchone()
    assert row is not None
    return int(row["total"])


TILES = "SELECT count(*) AS total FROM tile"
IMAGES = "SELECT count(*) AS total FROM reference_image"
EMBEDDINGS = "SELECT count(*) AS total FROM reference_embedding"

#: Every embedding count below is a multiple of this: AD-13 embeds sixteen
#: views of each Reference Image, so a Tile holding two images holds 32 rows.
VIEWS_PER_IMAGE = 16
SIZES = "SELECT count(*) AS total FROM tile_size"
CATEGORIES = "SELECT count(*) AS total FROM tile_category"


def named(conn: psycopg.Connection, statement: str, name: str) -> bool:
    """Whether a lookup row with that exact name is still there."""
    return conn.execute(statement, (name,)).fetchone() is not None


def removal_entries(conn: psycopg.Connection, rows: AuditRows) -> list[dict[str, object]]:
    return [row for row in rows(conn) if row["action"] == REMOVED_ACTION]


# --- The happy path -----------------------------------------------------------


@needs_model
def test_an_administrator_removes_a_tile(
    client: TestClient,
    conn: psycopg.Connection,
    administrator: Any,
    storage_root: Path,
    audit_rows: AuditRows,
) -> None:
    created = add(client, images=2)
    assert count(conn, EMBEDDINGS) == 32
    assert len(stored_objects(storage_root)) == 4

    response = remove(client, created["id"])

    assert response.status_code == 204, response.text
    # No body at all: there is no row left to describe, and answering with the
    # one that was deleted would be the product describing something gone.
    assert response.content == b""
    # Catalogue data's own header, on a refusal and on a success alike — a copy
    # left in a shared proxy cache is a copy outside the audit trail.
    assert response.headers["cache-control"] == "no-store"

    # One `DELETE`, three levels of rows. `reference_image` cascades from
    # `tile` and `reference_embedding` from `reference_image` (AD-5), so a
    # story that drops either cascade fails here rather than silently leaving
    # 32 vectors in the searchable graph.
    assert count(conn, TILES) == 0
    assert count(conn, IMAGES) == 0
    assert count(conn, EMBEDDINGS) == 0
    # And every object went with them, after the commit.
    assert stored_objects(storage_root) == []


@needs_model
def test_the_shared_size_and_category_rows_survive(
    client: TestClient, conn: psycopg.Connection, administrator: Any
) -> None:
    # `tile_size` and `tile_category` are referenced *by* `tile` and never the
    # other way, so a removal cannot cascade into them — and must not, because
    # they are shared lookups rather than the Tile's property. The second Tile
    # under the same Size is what makes that visible.
    first = add(client, code=CODE)
    add(client, code=OTHER_CODE)
    sizes, categories = count(conn, SIZES), count(conn, CATEGORIES)

    assert remove(client, first["id"]).status_code == 204

    # Not a count of zero removals but the same lookups, still named and still
    # there — the next Tile filed under `45X90` finds it rather than making it.
    assert count(conn, SIZES) == sizes
    assert count(conn, CATEGORIES) == categories
    assert named(conn, "SELECT id FROM tile_size WHERE name = %s", SIZE)
    assert named(conn, "SELECT id FROM tile_category WHERE name = %s", CATEGORY)


@needs_model
def test_another_tile_keeps_its_rows_its_embeddings_and_its_objects(
    client: TestClient, conn: psycopg.Connection, administrator: Any, storage_root: Path
) -> None:
    doomed = add(client, code=CODE)
    survivor = add(client, code=OTHER_CODE, images=2)

    assert remove(client, doomed["id"]).status_code == 204

    assert count(conn, TILES) == 1
    assert count(conn, IMAGES) == 2
    assert count(conn, EMBEDDINGS) == 32
    assert len(stored_objects(storage_root)) == 4
    # And it is still readable as the Tile it was.
    found = client.get(f"{ADD_TILE}/lookup", params={"code": OTHER_CODE})
    assert found.status_code == 200
    assert found.json()["id"] == survivor["id"]


@needs_model
def test_only_the_removed_tiles_embeddings_go(
    client: TestClient, conn: psycopg.Connection, administrator: Any
) -> None:
    # The mechanism under the behaviour above, stated as the absence of orphans:
    # nothing is left pointing at a `reference_image` that is gone, and nothing
    # belonging to the survivor was touched.
    doomed = add(client, code=CODE)
    add(client, code=OTHER_CODE)
    doomed_image = doomed["reference_images"][0]["id"]

    assert remove(client, doomed["id"]).status_code == 204

    orphans = conn.execute(
        "SELECT count(*) AS total FROM reference_embedding WHERE reference_image_id = %s",
        (doomed_image,),
    ).fetchone()
    assert orphans is not None and orphans["total"] == 0
    assert count(conn, EMBEDDINGS) == 16


@needs_model
def test_the_code_is_free_again_afterwards(client: TestClient, administrator: Any) -> None:
    # The Code is the identity (AD-18) and the unique index is over the column
    # itself, so a removed Tile's Code is available again. A soft delete would
    # keep the row and refuse the re-add with `409 code_already_exists`, which
    # is exactly the state AD-5 exists to prevent.
    created = add(client)

    assert remove(client, created["id"]).status_code == 204

    assert client.get(f"{ADD_TILE}/lookup", params={"code": CODE}).status_code == 404
    readded = add(client)
    assert readded["id"] != created["id"]


@needs_model
def test_a_tile_with_no_category_is_removed_and_the_entry_records_the_absence(
    client: TestClient, conn: psycopg.Connection, administrator: Any, audit_rows: AuditRows
) -> None:
    """The entry's degenerate shape, which is the one nothing can be re-read from.

    `category_id` is nullable in the ERD and `_SELECT_TILE_FOR_UPDATE` reaches it
    through a LEFT JOIN, so `details["category"]` can legitimately be JSON null.
    The add path never produces that — a blank Category resolves to the UNKNOWN
    sentinel (AD-18) — so it is arranged directly here; `edit_tile` carries a
    branch for a Tile in exactly this state, and `scripts/ingest` writes rows
    this endpoint did not.

    It matters because the removal's `details` is the *only* surviving record:
    there is no row left to re-read the Category from, so an entry that dropped
    the key, or raised on the way to writing it, would lose the fact for good.
    """
    created = add(client)
    conn.execute("UPDATE tile SET category_id = NULL WHERE id = %s", (created["id"],))

    assert remove(client, created["id"]).status_code == 204

    details = removal_entries(conn, audit_rows)[0]["details"]
    assert isinstance(details, dict)
    # Present and null, never absent: a reader has to be able to tell "this Tile
    # had no Category" from "this build did not record one".
    assert "category" in details
    assert details["category"] is None
    assert details["code"] == CODE
    assert details["size"] == SIZE
    assert count(conn, TILES) == 0


# --- The refusals -------------------------------------------------------------


@needs_model
def test_an_unknown_id_is_a_404_and_removes_nothing(
    client: TestClient,
    conn: psycopg.Connection,
    administrator: Any,
    storage_root: Path,
    audit_rows: AuditRows,
) -> None:
    # Not idempotent, on purpose: a silent `204` for a Tile that was never there
    # tells an Administrator they removed something they did not. Decided by the
    # locking read, never by a zero-row `DELETE`.
    add(client)

    response = remove(client, str(uuid4()))

    assert response.status_code == 404
    assert response.json()["error"]["code"] == catalogue.TILE_NOT_FOUND
    assert response.json()["error"]["message"] == catalogue.NO_SUCH_TILE
    assert response.headers["cache-control"] == "no-store"
    assert count(conn, TILES) == 1
    assert count(conn, IMAGES) == 1
    assert count(conn, EMBEDDINGS) == 16
    assert len(stored_objects(storage_root)) == 2
    assert removal_entries(conn, audit_rows) == []


@needs_model
def test_removing_the_same_tile_twice_refuses_the_second_time(
    client: TestClient, conn: psycopg.Connection, administrator: Any, audit_rows: AuditRows
) -> None:
    created = add(client)

    assert remove(client, created["id"]).status_code == 204
    second = remove(client, created["id"])

    assert second.status_code == 404
    assert second.json()["error"]["code"] == catalogue.TILE_NOT_FOUND
    # And the second attempt recorded nothing: it changed nothing.
    assert len(removal_entries(conn, audit_rows)) == 1


def test_a_malformed_id_is_refused_by_the_path_parameter(
    client: TestClient, conn: psycopg.Connection, administrator: Any, storage_root: Path
) -> None:
    # FastAPI's own `422`, as on the edit. Nothing in the handler runs, so
    # nothing can have been deleted — and no model artifact is needed to prove
    # it, which is why this one is not marked `needs_model`.
    response = client.delete(f"{ADD_TILE}/not-a-uuid")

    assert response.status_code == 422
    assert count(conn, TILES) == 0
    assert stored_objects(storage_root) == []


# --- Storage is last, and best effort -----------------------------------------


@needs_model
def test_storage_refusing_to_delete_does_not_undo_a_committed_removal(
    client: TestClient,
    conn: psycopg.Connection,
    administrator: Any,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The post-commit `_discard`, one level up from the edit's.

    The rows are already gone when this runs, so a store that will not delete
    leaves an orphaned object — which an operator can remove — while raising
    would turn a removal the catalogue has already accepted into a `500` the
    Administrator cannot act on and cannot retry.
    """
    created = add(client, images=2)

    refused: list[str] = []

    def will_not_delete(self: Any, key: str) -> None:
        refused.append(key)
        raise OSError("storage is read-only")

    monkeypatch.setattr(storage.FilesystemObjectStore, "delete", will_not_delete)

    with caplog.at_level(logging.WARNING, logger=catalogue.logger.name):
        response = remove(client, created["id"])

    assert response.status_code == 204, response.text
    # The removal stands: the rows are gone from the index, which is what the
    # commit already recorded.
    assert count(conn, TILES) == 0
    assert count(conn, EMBEDDINGS) == 0
    # And it really did try — a `_discard` call that was quietly skipped would
    # satisfy every assertion above. Two objects per image, both images.
    assert len(refused) == 4

    warnings = [
        record.getMessage() for record in caplog.records if record.levelno >= logging.WARNING
    ]
    assert len(warnings) == 4
    # **Each warning names its key.** The count alone would pass a log line that
    # said only "an object could not be removed", and the key is the operator's
    # single route back to bytes no row points at any more — there is no query
    # left that can produce it.
    for key in refused:
        assert any(key in message for message in warnings), key
    # `why` reaches the log line and nothing else, so without this the two
    # constants could be swapped and the operator reading the warning would be
    # told a committed removal was a write that rolled back. The sentence is
    # deliberately about the rows rather than about a Reference Image: two call
    # sites pass it, and only one of them is removing an image.
    assert all(catalogue.DISCARD_REMOVED in message for message in warnings)
    assert not any(catalogue.DISCARD_ROLLED_BACK in message for message in warnings)


@needs_model
def test_the_objects_are_still_there_when_the_transaction_fails(
    client: TestClient,
    conn: psycopg.Connection,
    administrator: Any,
    storage_root: Path,
    audit_rows: AuditRows,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Database first, storage second — proved by breaking the database half.

    The inverse of the add's ordering and the same rule read backwards: deleting
    the bytes before the commit would leave a live row pointing at nothing if
    the transaction then rolled back. A Tile that exists without its bytes is
    unrecoverable from inside the product; an orphaned object is a file an
    operator deletes.
    """

    created = add(client, images=2)

    # Patched *after* the Tile is in place: the add writes an entry of its own,
    # and a refusal that reached it would leave nothing here to remove.
    def refuse(*_: Any, **__: Any) -> None:
        raise psycopg.errors.InsufficientPrivilege("no INSERT on the audit table")

    monkeypatch.setattr(audit_module, "record", refuse)

    # The `TestClient` re-raises an unhandled server exception rather than
    # rendering the 500 a browser would see, which is the right default here:
    # what is asserted is the state the failure left behind.
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        remove(client, created["id"])

    assert count(conn, TILES) == 1
    assert count(conn, IMAGES) == 2
    assert count(conn, EMBEDDINGS) == 32
    # Nothing was deleted from storage: the `_discard` is after the commit, and
    # there was no commit.
    assert len(stored_objects(storage_root)) == 4
    assert removal_entries(conn, audit_rows) == []


# --- Under the lock -----------------------------------------------------------


@needs_model
def test_an_edit_arriving_after_the_removal_is_told_the_tile_is_gone(
    client: TestClient, conn: psycopg.Connection, administrator: Any, storage_root: Path
) -> None:
    # The serialized outcome, asserted at its observable end: whichever commits
    # second sees the other. The removal committed, so the edit's locking read
    # finds nothing and answers `404` — and every object it wrote on the way is
    # discarded by its own `except`, so no orphan is left behind either.
    created = add(client)

    assert remove(client, created["id"]).status_code == 204

    late = client.patch(
        f"{ADD_TILE}/{created['id']}",
        files=[("images", ("late.jpg", jpeg_bytes(a_tile_photograph(31)), "image/jpeg"))],
    )

    assert late.status_code == 404
    assert late.json()["error"]["code"] == catalogue.TILE_NOT_FOUND
    assert count(conn, TILES) == 0
    assert stored_objects(storage_root) == []


@needs_model
def test_an_edit_already_in_flight_when_the_removal_commits_is_refused_and_leaves_no_object(
    client: TestClient,
    conn: psycopg.Connection,
    administrator: Any,
    storage_root: Path,
    audit_rows: AuditRows,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The matrix's concurrent edit, arranged rather than approximated.

    The sequential test above cannot make this claim. There the removal has
    already committed before the `PATCH` is sent, so the edit refuses at its
    *cheap* pre-flight `_SELECT_TILE` — before any decode, before any embed and
    before a single `store.put`. Its `stored_objects(...) == []` therefore says
    only that nothing was ever written, not that anything written was discarded.

    This one puts the edit genuinely in flight: it passes the pre-flight while
    the Tile is still there, embeds, writes both of its objects, and only then
    meets the removal. So it exercises the two halves of the matrix row that
    nothing else does — the locking read inside the transaction is what refuses
    it, and `_discard` takes back every object it had already written.

    The overlap is arranged rather than hoped for: the edit is held at its last
    `store.put`, which is the statement immediately before `BEGIN`, and released
    only once the removal has answered `204`.
    """
    created = add(client)
    assert len(stored_objects(storage_root)) == 2

    original_put = storage.FilesystemObjectStore.put
    written: list[str] = []
    at_the_gate = threading.Event()
    removal_done = threading.Event()

    def put_then_wait(self: Any, key: str, data: bytes) -> None:
        original_put(self, key, data)
        written.append(key)
        # Two objects per image (AD-17's source and derivative), so the second
        # is the edit's last write and the transaction is the next thing it does.
        if len(written) == 2:
            at_the_gate.set()
            assert removal_done.wait(LOCK_RELEASE_SECONDS), "the removal never answered"

    monkeypatch.setattr(storage.FilesystemObjectStore, "put", put_then_wait)

    answers: list[tuple[int, str | None]] = []
    failures: list[BaseException] = []

    def edit() -> None:
        try:
            response = client.patch(
                f"{ADD_TILE}/{created['id']}",
                files=[("images", ("late.jpg", jpeg_bytes(a_tile_photograph(31)), "image/jpeg"))],
            )
            body = None if response.status_code == 200 else response.json()["error"]["code"]
            answers.append((response.status_code, body))
        except BaseException as raised:  # noqa: BLE001 - re-reported below
            failures.append(raised)
        finally:
            at_the_gate.set()

    worker = threading.Thread(target=edit)
    worker.start()
    try:
        # The edit has written its bytes and is about to open its transaction.
        assert at_the_gate.wait(LOCK_RELEASE_SECONDS), "the edit never reached its last put"
        assert failures == [], failures
        assert len(stored_objects(storage_root)) == 4, "the edit wrote nothing to discard"

        assert remove(client, created["id"]).status_code == 204
    finally:
        removal_done.set()
        worker.join(LOCK_RELEASE_SECONDS)

    assert failures == [], failures
    # Refused by the locking read, not by the pre-flight: the pre-flight ran
    # while the Tile was still there.
    assert answers == [(404, catalogue.TILE_NOT_FOUND)]
    assert count(conn, TILES) == 0
    assert count(conn, IMAGES) == 0
    assert count(conn, EMBEDDINGS) == 0
    # Both of the edit's objects went back, and so did the removal's own two.
    # An edit that kept its writes would leave bytes no row will ever name.
    assert stored_objects(storage_root) == []
    assert len(removal_entries(conn, audit_rows)) == 1


@needs_model
def test_the_removal_waits_on_a_concurrent_holder_of_the_tiles_row_lock(
    client: TestClient, administrator: Any, migrated_url: str
) -> None:
    """The removal waits on a row lock another transaction already holds.

    This is what serializes a `PATCH` on the same Tile against the removal
    rather than letting an edit add an image into a row that is going.

    **What this cannot claim:** that `remove_tile`'s *read* takes the lock. The
    blocker holds a lock `_DELETE_TILE` must acquire anyway, so a handler whose
    read took no lock at all would still wait here and still answer `204`. The
    assertion that `FOR UPDATE OF t` is on the read is
    `test_two_overlapping_removals_of_one_tile_answer_204_and_404` below, which
    puts two handlers on one Tile. This test is the cheaper, narrower one: the
    request blocks on contention rather than failing or racing past it.
    """
    created = add(client)

    answered = threading.Event()
    statuses: list[int] = []
    failures: list[BaseException] = []

    def run() -> None:
        try:
            statuses.append(remove(client, created["id"]).status_code)
        except BaseException as raised:  # noqa: BLE001 - re-reported below
            # Captured rather than allowed to die inside the thread. A worker
            # that raised would leave `statuses` empty and this test would fail
            # as `[] == [204]`, reporting nothing about what actually went
            # wrong — which is exactly the shape of failure a concurrency test
            # can least afford to be vague about.
            failures.append(raised)
        finally:
            answered.set()

    blocker = psycopg.connect(migrated_url)
    try:
        # The removal's own statement, from a transaction that does not end.
        blocker.execute(catalogue._SELECT_TILE_FOR_UPDATE, (created["id"],)).fetchone()

        worker = threading.Thread(target=run)
        worker.start()
        try:
            # Blocked on the row lock, not merely slow: nothing else in this
            # request touches the model or the store.
            assert not answered.wait(LOCK_WAIT_SECONDS)
            blocker.rollback()
            assert answered.wait(LOCK_RELEASE_SECONDS)
        finally:
            worker.join(LOCK_RELEASE_SECONDS)
    finally:
        blocker.close()

    assert failures == []
    assert statuses == [204]


@needs_model
def test_two_overlapping_removals_of_one_tile_answer_204_and_404(
    client: TestClient,
    conn: psycopg.Connection,
    administrator: Any,
    audit_rows: AuditRows,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two removals of the same Tile, genuinely overlapping. One wins; one is told.

    The lock test above cannot make this claim: a blocker holding the row would
    stall the `DELETE` itself, so a handler whose read took no lock at all would
    still wait and still answer `204`. This one puts two *handlers* on one Tile
    and asserts the losing one takes the documented path — `404 tile_not_found`
    from its own locking read — rather than sailing past it into
    `assert deleted == 1` and answering `500` to an Administrator who did
    nothing wrong.

    The overlap is arranged rather than hoped for: the winner is held inside its
    transaction, at `audit.record`, with the row lock taken, and the loser is
    released into its locking read at exactly that moment.
    """
    created = add(client)

    holding = threading.Event()
    original_record = audit_module.record

    def record_then_hold(*args: Any, **kwargs: Any) -> None:
        original_record(*args, **kwargs)
        # Still inside the winner's transaction and still holding the lock.
        holding.set()
        time.sleep(LOCK_OVERLAP_SECONDS)

    monkeypatch.setattr(audit_module, "record", record_then_hold)

    answers: list[tuple[int, str | None]] = []
    failures: list[BaseException] = []

    def send(wait: bool) -> None:
        try:
            if wait:
                assert holding.wait(LOCK_RELEASE_SECONDS), (
                    "the first removal never reached its entry"
                )
            response = remove(client, created["id"])
            body = None if response.status_code == 204 else response.json()["error"]["code"]
            answers.append((response.status_code, body))
        except BaseException as raised:  # noqa: BLE001 - re-reported below
            failures.append(raised)

    threads = [threading.Thread(target=send, args=(late,)) for late in (False, True)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(LOCK_RELEASE_SECONDS)

    # Reported rather than swallowed: an `AssertionError` from the handler's own
    # `assert deleted == 1` is precisely the regression this test exists for, and
    # a thread that died silently would fail below with nothing to read.
    assert failures == [], failures
    assert {status for status, _ in answers} == {204, 404}
    assert [code for status, code in answers if status == 404] == [catalogue.TILE_NOT_FOUND]
    # And one removal happened, so one entry exists. Two would mean the loser
    # recorded a withdrawal it did not perform.
    assert len(removal_entries(conn, audit_rows)) == 1
    assert count(conn, TILES) == 0


# --- No second way to express the rule ----------------------------------------


@needs_model
def test_no_table_the_removal_touches_carries_a_soft_delete_marker(
    client: TestClient, conn: psycopg.Connection, administrator: Any
) -> None:
    """AD-5, as an absence in the shipped schema rather than in one handler.

    A soft-delete column is the one implementation of this story that would pass
    every behavioural test above on the day it was written and fail silently on
    the day Epic 3's scan forgot the predicate. There is no such column to
    forget, and this is where that is checked — against the migrated database,
    so a later migration that adds one fails here rather than at the scan.

    The guard is a name test, so it is only ever as good as its list of
    spellings: it names the ones a soft delete is actually written in rather
    than claiming to catch every possible column. A marker under some other
    name would still slip past, which is why AD-5 is also asserted
    behaviourally above and in `test_removed_tile_unsearchable.py` — this is
    the schema-level backstop, not the only lock on the door.
    """
    add(client)

    marked = conn.execute(
        """
        SELECT table_name, column_name
          FROM information_schema.columns
         WHERE table_schema = 'public'
           AND table_name IN ('tile', 'reference_image', 'reference_embedding')
           AND (column_name LIKE '%deleted%'
                OR column_name LIKE '%removed%'
                OR column_name LIKE '%archived%'
                OR column_name LIKE '%retired%'
                OR column_name LIKE '%withdrawn%'
                OR column_name LIKE '%hidden%'
                OR column_name LIKE '%visible%'
                OR column_name LIKE '%active%')
        """
    ).fetchall()

    assert marked == []
