"""Every catalogue change is attributable, permanent, and written with the change.

Story 1.12 built the append-only log and Story 1.13 the read; these are the
first entries Epic 2 writes, and the first in the product that name something
other than an account. Three properties, and the third is the one a later story
is most likely to break:

* a successful write records **exactly one** entry — `catalogue_tile_added`
  from Story 2.1, `catalogue_tile_edited` from Story 2.2, `catalogue_tile_removed`
  from Story 2.3 — with the actor, the source address and the Code;
* a refused write records **none** — a `409`, a `422` or a `413` changed
  nothing, so there is nothing to record;
* the entry and the change are in **one transaction**, so neither can exist
  without the other.

The Tile is named in `details` as a denormalized snapshot, never as a foreign
key (AD-10): the removal is a hard delete and the log may neither block it nor
be cascaded into — the entries that named the Tile outlive it, which is the
whole point of recording that it went. An edit never rewrites the add's entry
either — AD-4 makes the log append-only at every level, so a rename adds an
entry beside the one that recorded the old Code.
"""

from __future__ import annotations

import io
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import psycopg
import pytest
from api import audit as audit_module
from fastapi.testclient import TestClient
from PIL import Image
from shared_schema.user import Role
from shared_vision import pipeline

MakeUser = Callable[..., Any]
AuditRows = Callable[[psycopg.Connection], list[dict[str, object]]]

ADD_TILE = "/admin/tiles"
LOGIN = "/auth/login"
CODE = "RP.CMA.0001DJ.SM.0T"
ACTION = "catalogue_tile_added"

needs_model = pytest.mark.skipif(
    not pipeline.MODEL_PATH.exists(),
    reason="model not downloaded; run `make model`",
)


def an_image(seed: int = 4) -> bytes:
    rng = np.random.default_rng(seed)
    image = Image.fromarray(rng.integers(0, 255, (160, 160, 3), dtype=np.uint8), "RGB")
    buf = io.BytesIO()
    image.save(buf, format="JPEG")
    return buf.getvalue()


@pytest.fixture
def administrator(client: TestClient, make_user: MakeUser) -> Any:
    account = make_user(role=Role.ADMIN, name="Nadeesha Silva")
    response = client.post(LOGIN, json={"email": account.email, "password": account.password})
    assert response.status_code == 200
    return account


def add(client: TestClient, **fields: Any) -> Any:
    data = {"code": CODE, "size": "45X90", "category": "CREMA MARMOL", **fields}
    files = data.pop("files", [("images", ("reference.jpg", an_image(), "image/jpeg"))])
    return client.post(ADD_TILE, data=data, files=files)


def catalogue_entries(conn: psycopg.Connection, rows: AuditRows) -> list[dict[str, object]]:
    return [row for row in rows(conn) if row["action"] == ACTION]


@needs_model
def test_a_successful_add_writes_one_entry_naming_who_what_and_from_where(
    client: TestClient, conn: psycopg.Connection, administrator: Any, audit_rows: AuditRows
) -> None:
    created = add(client).json()

    entries = catalogue_entries(conn, audit_rows)
    assert len(entries) == 1
    entry = entries[0]

    assert entry["actor_user_id"] == administrator.id
    assert entry["actor_email"] == administrator.email
    # The `client` fixture connects from loopback; `api.audit.source_ip`
    # canonicalises and stores whatever the trust boundary resolved.
    assert entry["source_ip"] == "127.0.0.1"
    assert entry["created_at"] is not None

    details = entry["details"]
    assert isinstance(details, dict)
    assert details["code"] == CODE
    assert details["tile_id"] == created["id"]
    assert details["size"] == "45X90"
    assert details["category"] == "CREMA MARMOL"
    assert details["reference_images"] == 1


@needs_model
def test_the_entry_names_no_account_as_its_target(
    client: TestClient, conn: psycopg.Connection, administrator: Any, audit_rows: AuditRows
) -> None:
    # The target columns are an account's. A Tile is not one, and putting its
    # id in `target_user_id` would make the log's own shape a lie — and would
    # join, at some later date, against a user who does not exist.
    add(client)

    entry = catalogue_entries(conn, audit_rows)[0]
    assert entry["target_user_id"] is None
    assert entry["target_email"] is None


@needs_model
def test_the_entry_carries_no_storage_key_and_no_secret(
    client: TestClient, conn: psycopg.Connection, administrator: Any, audit_rows: AuditRows
) -> None:
    # `api.audit.record`'s standing rule about `details`, checked at this call
    # site. A storage key in the log is a reference nothing may hold outside
    # `apps/api` (AD-9), and it outlives the object it names.
    add(client)
    details = str(catalogue_entries(conn, audit_rows)[0]["details"])
    for forbidden in ("source_key", "derivative_key", "tiles/", ".jpg", "password", "token"):
        assert forbidden not in details, details


@needs_model
def test_a_second_add_writes_a_second_entry_and_leaves_the_first_alone(
    client: TestClient, conn: psycopg.Connection, administrator: Any, audit_rows: AuditRows
) -> None:
    add(client, code="FIRST")
    first = catalogue_entries(conn, audit_rows)[0]

    add(client, code="SECOND")
    entries = catalogue_entries(conn, audit_rows)

    assert len(entries) == 2
    assert first in entries
    assert {str(entry["details"]) for entry in entries} != {str(first["details"])}


# --- Refusals write nothing ---------------------------------------------------


@needs_model
def test_a_duplicate_code_writes_no_entry(
    client: TestClient, conn: psycopg.Connection, administrator: Any, audit_rows: AuditRows
) -> None:
    assert add(client).status_code == 201
    assert add(client).status_code == 409

    assert len(catalogue_entries(conn, audit_rows)) == 1


@pytest.mark.parametrize(
    ("label", "fields"),
    [
        ("a blank code", {"code": ""}),
        ("a missing size", {"size": ""}),
        ("bytes that are not an image", {"files": [("images", ("x.jpg", b"", "image/jpeg"))]}),
    ],
)
def test_a_refused_add_writes_no_entry(
    client: TestClient,
    conn: psycopg.Connection,
    administrator: Any,
    audit_rows: AuditRows,
    label: str,
    fields: Any,
) -> None:
    response = add(client, **fields)

    assert response.status_code in (413, 422), label
    assert catalogue_entries(conn, audit_rows) == []


def test_a_refused_caller_writes_no_entry(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser, audit_rows: AuditRows
) -> None:
    account = make_user(role=Role.STAFF)
    client.post(LOGIN, json={"email": account.email, "password": account.password})

    assert add(client).status_code == 403
    assert catalogue_entries(conn, audit_rows) == []


# --- One transaction ----------------------------------------------------------


@needs_model
def test_an_audit_failure_takes_the_tile_down_with_it(
    client: TestClient,
    conn: psycopg.Connection,
    administrator: Any,
    audit_rows: AuditRows,
    storage_root: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The add and its entry are one unit of work, proved by breaking one half.

    A Tile that exists without a record of who added it is the state AD-4 and
    FR-20 exist to prevent, and it is not visible from the outside — the only
    way to assert the transaction is really shared is to make the second write
    fail and check the first did not survive.
    """

    def refuse(*_: Any, **__: Any) -> None:
        raise psycopg.errors.InsufficientPrivilege("no INSERT on the audit table")

    monkeypatch.setattr(audit_module, "record", refuse)

    # The `TestClient` re-raises an unhandled server exception rather than
    # rendering the 500 a browser would see. That is the right default here:
    # what is being asserted is the state the failure left behind, and
    # swallowing the exception would hide which write failed.
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        add(client)

    row = conn.execute("SELECT count(*) AS total FROM tile").fetchone()
    assert row is not None and row["total"] == 0
    assert catalogue_entries(conn, audit_rows) == []
    # And the objects that had already been written are gone with it.
    assert [path for path in storage_root.rglob("*") if path.is_file()] == []


# --- Story 2.2's entry --------------------------------------------------------
# A member of its own, not a second `catalogue_tile_added` with a flag in
# `details`: an edit can rename the Code the earlier entry recorded, and a
# reader following a Tile through the log needs the two distinguishable without
# parsing a payload.

EDIT_ACTION = "catalogue_tile_edited"


def edit_entries(conn: psycopg.Connection, rows: AuditRows) -> list[dict[str, object]]:
    return [row for row in rows(conn) if row["action"] == EDIT_ACTION]


def edit(client: TestClient, tile_id: str, **fields: Any) -> Any:
    files = fields.pop("files", None)
    data = {
        key: ([str(item) for item in value] if isinstance(value, list) else str(value))
        for key, value in fields.items()
    }
    if files:
        return client.patch(f"{ADD_TILE}/{tile_id}", data=data, files=files)
    return client.patch(f"{ADD_TILE}/{tile_id}", data=data)


@needs_model
def test_a_successful_edit_writes_one_entry_naming_who_what_and_from_where(
    client: TestClient, conn: psycopg.Connection, administrator: Any, audit_rows: AuditRows
) -> None:
    created = add(client).json()
    doomed = created["reference_images"][0]["id"]

    response = edit(
        client,
        created["id"],
        code="RP.CMA.0002DJ.SM.0T",
        size="60X60",
        remove_image_ids=[doomed],
        files=[("images", ("replacement.jpg", an_image(7), "image/jpeg"))],
    )
    assert response.status_code == 200, response.text

    entries = edit_entries(conn, audit_rows)
    assert len(entries) == 1
    entry = entries[0]

    assert entry["actor_user_id"] == administrator.id
    assert entry["actor_email"] == administrator.email
    assert entry["source_ip"] == "127.0.0.1"
    assert entry["created_at"] is not None
    # The target columns are an account's. A Tile is not one.
    assert entry["target_user_id"] is None
    assert entry["target_email"] is None

    details = entry["details"]
    assert isinstance(details, dict)
    # The Code as it *now* stands, snapshot in `details` and never a foreign key
    # (AD-10) — `changed` carries the one it had.
    assert details["code"] == "RP.CMA.0002DJ.SM.0T"
    assert details["tile_id"] == created["id"]
    assert details["changed"] == {
        "code": {"from": CODE, "to": "RP.CMA.0002DJ.SM.0T"},
        "size": {"from": "45X90", "to": "60X60"},
    }
    assert details["images_added"] == 1
    assert details["images_removed"] == 1


@needs_model
def test_the_edit_entry_carries_no_storage_key_and_no_secret(
    client: TestClient, conn: psycopg.Connection, administrator: Any, audit_rows: AuditRows
) -> None:
    # `api.audit.record`'s standing rule about `details`, checked at this call
    # site too: a storage key in the log outlives the object it names, and is a
    # reference nothing may hold outside `apps/api` (AD-9).
    created = add(client).json()
    edit(client, created["id"], files=[("images", ("second.jpg", an_image(8), "image/jpeg"))])

    details = str(edit_entries(conn, audit_rows)[0]["details"])
    for forbidden in ("source_key", "derivative_key", "tiles/", ".jpg", "password", "token"):
        assert forbidden not in details, details


@needs_model
def test_an_edit_that_moved_nothing_records_an_empty_change_set(
    client: TestClient, conn: psycopg.Connection, administrator: Any, audit_rows: AuditRows
) -> None:
    # The honest record of an accepted edit that changed no value. An entry
    # claiming a change that did not happen is worse than a terse one, because
    # nothing downstream can tell it from a real one.
    created = add(client).json()

    assert edit(client, created["id"], code=CODE).status_code == 200

    details = edit_entries(conn, audit_rows)[0]["details"]
    assert isinstance(details, dict)
    assert details["changed"] == {}


@needs_model
def test_an_edit_leaves_the_add_entry_alone(
    client: TestClient, conn: psycopg.Connection, administrator: Any, audit_rows: AuditRows
) -> None:
    # AD-4: the log is append-only at every level. A rename does not rewrite the
    # entry that recorded the old Code — it adds one beside it.
    created = add(client).json()
    added = catalogue_entries(conn, audit_rows)[0]

    edit(client, created["id"], code="RP.CMA.0002DJ.SM.0T")

    assert catalogue_entries(conn, audit_rows) == [added]
    assert len(edit_entries(conn, audit_rows)) == 1


@needs_model
@pytest.mark.parametrize(
    ("label", "fields", "expected"),
    [
        ("a blank code", {"code": ""}, 422),
        ("a blank size", {"size": ""}, 422),
        ("bytes that are not an image", {"files": [("images", ("x.jpg", b"", "image/jpeg"))]}, 422),
    ],
)
def test_a_refused_edit_writes_no_entry(
    client: TestClient,
    conn: psycopg.Connection,
    administrator: Any,
    audit_rows: AuditRows,
    label: str,
    fields: Any,
    expected: int,
) -> None:
    created = add(client).json()

    response = edit(client, created["id"], **fields)

    assert response.status_code == expected, label
    assert edit_entries(conn, audit_rows) == [], label


@needs_model
def test_an_edit_that_would_empty_a_tile_writes_no_entry(
    client: TestClient, conn: psycopg.Connection, administrator: Any, audit_rows: AuditRows
) -> None:
    # FR-7's floor. The refusal changed nothing, so there is nothing to record.
    created = add(client).json()

    response = edit(client, created["id"], remove_image_ids=[created["reference_images"][0]["id"]])

    assert response.status_code == 409
    assert edit_entries(conn, audit_rows) == []


def test_a_refused_caller_writes_no_edit_entry(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser, audit_rows: AuditRows
) -> None:
    account = make_user(role=Role.STAFF)
    client.post(LOGIN, json={"email": account.email, "password": account.password})

    assert edit(client, "00000000-0000-4000-8000-000000000000", code=CODE).status_code == 403
    assert edit_entries(conn, audit_rows) == []


# --- Story 2.3's entry --------------------------------------------------------
# The one entry whose subject no longer exists by the time it can be read. Every
# value in `details` is an AD-10 snapshot taken from the locked read, because
# after the `DELETE` there is nothing left to take it from — and the entries
# that already named this Tile stay exactly as they are, which is the whole
# point of recording the removal beside them (AD-4).

REMOVED_ACTION = "catalogue_tile_removed"


def removal_entries(conn: psycopg.Connection, rows: AuditRows) -> list[dict[str, object]]:
    return [row for row in rows(conn) if row["action"] == REMOVED_ACTION]


def remove(client: TestClient, tile_id: str) -> Any:
    return client.delete(f"{ADD_TILE}/{tile_id}")


@needs_model
def test_a_successful_removal_writes_one_entry_naming_who_what_and_from_where(
    client: TestClient, conn: psycopg.Connection, administrator: Any, audit_rows: AuditRows
) -> None:
    created = add(client).json()

    assert remove(client, created["id"]).status_code == 204

    entries = removal_entries(conn, audit_rows)
    assert len(entries) == 1
    entry = entries[0]

    assert entry["actor_user_id"] == administrator.id
    assert entry["actor_email"] == administrator.email
    assert entry["source_ip"] == "127.0.0.1"
    assert entry["created_at"] is not None
    # The target columns are an account's. A Tile is not one, and a Tile that
    # no longer exists is emphatically not one.
    assert entry["target_user_id"] is None
    assert entry["target_email"] is None

    details = entry["details"]
    assert isinstance(details, dict)
    assert details["tile_id"] == created["id"]
    assert details["code"] == CODE
    assert details["size"] == "45X90"
    assert details["category"] == "CREMA MARMOL"
    assert details["images_removed"] == 1


@needs_model
def test_the_entry_counts_every_image_the_removed_tile_held_not_one(
    client: TestClient, conn: psycopg.Connection, administrator: Any, audit_rows: AuditRows
) -> None:
    # The count is the only part of the snapshot that is computed rather than
    # copied, and the rest of this file's removals carry a single image — so a
    # hardcoded `1`, or the length of the wrong list, reads as correct
    # everywhere else. A Tile that held three says three.
    created = add(
        client,
        files=[
            ("images", (f"reference-{seed}.jpg", an_image(seed), "image/jpeg"))
            for seed in (11, 12, 13)
        ],
    ).json()

    assert remove(client, created["id"]).status_code == 204

    details = removal_entries(conn, audit_rows)[0]["details"]
    assert isinstance(details, dict)
    assert details["images_removed"] == 3


@needs_model
def test_the_removal_entry_carries_no_storage_key_and_no_secret(
    client: TestClient, conn: psycopg.Connection, administrator: Any, audit_rows: AuditRows
) -> None:
    # `api.audit.record`'s standing rule about `details`, at the one call site
    # that reads the storage keys on its way past: they are in the handler's
    # hands here and must not reach the log, which outlives the objects (AD-9).
    created = add(client).json()

    remove(client, created["id"])

    details = str(removal_entries(conn, audit_rows)[0]["details"])
    for forbidden in ("source_key", "derivative_key", "tiles/", ".jpg", "password", "token"):
        assert forbidden not in details, details


@needs_model
def test_the_entries_that_already_named_the_tile_survive_it(
    client: TestClient, conn: psycopg.Connection, administrator: Any, audit_rows: AuditRows
) -> None:
    # `audit_log` carries no foreign key into `tile` (AD-10), so a hard delete
    # can neither be blocked by the log nor cascade into it — and AD-4 grants
    # the application no DELETE there in any case. Both earlier entries are
    # still readable, unchanged, after the Tile they name is gone.
    created = add(client).json()
    added = catalogue_entries(conn, audit_rows)[0]
    edit(client, created["id"], code="RP.CMA.0002DJ.SM.0T")
    edited = edit_entries(conn, audit_rows)[0]

    assert remove(client, created["id"]).status_code == 204

    assert catalogue_entries(conn, audit_rows) == [added]
    assert edit_entries(conn, audit_rows) == [edited]
    assert len(removal_entries(conn, audit_rows)) == 1


@needs_model
def test_a_removal_of_an_unknown_tile_writes_no_entry(
    client: TestClient, conn: psycopg.Connection, administrator: Any, audit_rows: AuditRows
) -> None:
    # The `404` changed nothing, so there is nothing to record — and an entry
    # here would say an Administrator removed a Tile that was never there.
    add(client)

    assert remove(client, "00000000-0000-4000-8000-000000000000").status_code == 404

    assert removal_entries(conn, audit_rows) == []


def test_a_refused_caller_writes_no_removal_entry(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser, audit_rows: AuditRows
) -> None:
    account = make_user(role=Role.STAFF)
    client.post(LOGIN, json={"email": account.email, "password": account.password})

    assert remove(client, "00000000-0000-4000-8000-000000000000").status_code == 403
    assert removal_entries(conn, audit_rows) == []


@needs_model
def test_an_audit_failure_leaves_the_tile_where_it_was(
    client: TestClient,
    conn: psycopg.Connection,
    administrator: Any,
    audit_rows: AuditRows,
    storage_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The removal and its entry are one unit of work, proved by breaking one half.

    A Tile that vanished without a record of who removed it is the state AD-4
    and FR-20 exist to prevent, and — unlike the add's version of this — it is
    not recoverable by re-running anything. The only way to assert the
    transaction is really shared is to make the second write fail and check the
    first did not take effect.
    """
    created = add(client).json()

    def refuse(*_: Any, **__: Any) -> None:
        raise psycopg.errors.InsufficientPrivilege("no INSERT on the audit table")

    monkeypatch.setattr(audit_module, "record", refuse)

    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        remove(client, created["id"])

    row = conn.execute("SELECT count(*) AS total FROM tile").fetchone()
    assert row is not None and row["total"] == 1
    images = conn.execute("SELECT count(*) AS total FROM reference_image").fetchone()
    assert images is not None and images["total"] == 1
    # 16, because AD-13 stores sixteen views per Reference Image — four clean
    # rotations and twelve augmented crops — and none of them moved.
    vectors = conn.execute("SELECT count(*) AS total FROM reference_embedding").fetchone()
    assert vectors is not None and vectors["total"] == 16
    assert removal_entries(conn, audit_rows) == []
    # And nothing was deleted from storage: the objects go after the commit,
    # and there was no commit.
    assert len([path for path in storage_root.rglob("*") if path.is_file()]) == 2


# --- The bulk upload (Story 2.4, FR-17) ---------------------------------------
# **No new `AuditAction`.** A Tile added by bulk is a Tile added: same actor,
# same consequence for the catalogue, same `details`. A second action naming the
# same fact is drift — the argument Story 2.3 used to refuse a second
# `tile_not_found` — and the provenance that is genuinely lost (which batch a
# Tile came from) is not something FR-20 asks for. So the claim here is not
# that the bulk path records *something*: it is that it records exactly what the
# single add records, once per created row and never for a refused one.

BULK_PLAN = "/admin/tiles/bulk/plan"
BULK_ROW = "/admin/tiles/bulk/row"


def plan(client: TestClient, sheet: bytes, images: list[tuple[str, bytes]]) -> Any:
    """`POST /admin/tiles/bulk/plan` — the sheet and the names, no bytes."""
    return client.post(
        BULK_PLAN,
        files=[("manifest", ("codes.csv", sheet, "text/csv"))],
        data={"names": [name for name, _ in images]},
    )


def bulk(client: TestClient, sheet: bytes, images: list[tuple[str, bytes]]) -> Any:
    """A whole batch, driven the way the screen drives it: plan, then one row.

    Answers the *plan's* response when it was refused, and otherwise a list of
    the report lines — which is all these tests read, since what they are about
    is the entries the batch left behind rather than the shape of the report.
    """
    planned = plan(client, sheet, images)
    if planned.status_code != 200:
        return planned

    bytes_for = dict(images)
    report: list[dict[str, Any]] = []
    for item in planned.json()["items"]:
        if item["upload"] is None:
            report.append({"status": "failed", "error": item["error"]})
            continue
        response = client.post(
            BULK_ROW,
            data={
                "code": item["code"] or "",
                "size": item["size"] or "",
                "category": item["category"] or "",
            },
            files=[("image", (item["upload"], bytes_for[item["upload"]], "image/jpeg"))],
        )
        assert response.status_code == 200, response.text
        report.append(response.json())
    return report


#: Five rows. Row 3's image is zero bytes — a defect the real source tree
#: carries — so four are created and one is refused.
_FIVE_ROWS = (
    b"file,code,size,category\n"
    b"1.jpg,RP.CMA.0001DJ.SM.0T,45X90,CREMA MARMOL\n"
    b"2.jpg,RP.CMA.0002DJ.SM.0T,45X90,CREMA MARMOL\n"
    b"3.jpg,RP.CMA.0003DJ.SM.0T,45X90,CREMA MARMOL\n"
    b"4.jpg,RP.CMA.0004DJ.SM.0T,45X90,CREMA MARMOL\n"
    b"5.jpg,RP.CMA.0005DJ.SM.0T,45X90,CREMA MARMOL\n"
)

_FIVE_IMAGES = [
    ("1.jpg", an_image(1)),
    ("2.jpg", an_image(2)),
    ("3.jpg", b""),
    ("4.jpg", an_image(4)),
    ("5.jpg", an_image(5)),
]


@needs_model
def test_a_batch_of_five_with_one_failure_writes_exactly_four_entries(
    client: TestClient, conn: psycopg.Connection, administrator: Any, audit_rows: AuditRows
) -> None:
    report = bulk(client, _FIVE_ROWS, _FIVE_IMAGES)
    assert [line["status"] for line in report] == [
        "created",
        "created",
        "failed",
        "created",
        "created",
    ]

    entries = catalogue_entries(conn, audit_rows)

    assert len(entries) == 4
    # One per *created* row, and the refused one is absent by its Code rather
    # than only by the count: a report that renumbered its rows would still
    # have four entries and the wrong four.
    assert {entry["details"]["code"] for entry in entries} == {  # type: ignore[index]
        "RP.CMA.0001DJ.SM.0T",
        "RP.CMA.0002DJ.SM.0T",
        "RP.CMA.0004DJ.SM.0T",
        "RP.CMA.0005DJ.SM.0T",
    }


@needs_model
def test_every_bulk_entry_names_the_actor_the_time_and_the_address(
    client: TestClient, conn: psycopg.Connection, administrator: Any, audit_rows: AuditRows
) -> None:
    bulk(client, _FIVE_ROWS, _FIVE_IMAGES)

    for entry in catalogue_entries(conn, audit_rows):
        assert entry["actor_user_id"] == administrator.id
        assert entry["actor_email"] == administrator.email
        # The `client` fixture connects from loopback; `api.audit.source_ip`
        # canonicalises and stores whatever the trust boundary resolved.
        assert entry["source_ip"] == "127.0.0.1"
        assert entry["created_at"] is not None
        # A Tile is not an account, so the target columns stay empty — putting
        # its id in `target_user_id` would make the log's shape a lie.
        assert entry["target_user_id"] is None
        assert entry["target_email"] is None


@needs_model
def test_a_bulk_entry_has_the_same_details_shape_the_single_add_writes(
    client: TestClient, conn: psycopg.Connection, administrator: Any, audit_rows: AuditRows
) -> None:
    # The shape three tests pin, asserted as a *comparison* rather than as a
    # second literal list of keys: a key added on one path and not the other is
    # the drift, and two independent lists of keys would both be updated by
    # whoever added it.
    add(client)
    by_hand = catalogue_entries(conn, audit_rows)[0]

    sheet = b"file,code,size,category\n1.jpg,RP.CMA.0099DJ.SM.0T,45X90,CREMA MARMOL\n"
    assert [line["status"] for line in bulk(client, sheet, [("1.jpg", an_image(1))])] == ["created"]

    in_bulk = next(
        entry
        for entry in catalogue_entries(conn, audit_rows)
        if entry["details"]["code"] == "RP.CMA.0099DJ.SM.0T"  # type: ignore[index]
    )

    assert isinstance(by_hand["details"], dict) and isinstance(in_bulk["details"], dict)
    assert set(in_bulk["details"]) == set(by_hand["details"])
    # No `bulk` marker, no batch id, no row number. The fact recorded is the
    # same fact, and a flag inside `details` would fork a shape three tests
    # pin for the sake of provenance FR-20 does not ask for.
    assert in_bulk["details"]["size"] == "45X90"
    assert in_bulk["details"]["category"] == "CREMA MARMOL"
    assert in_bulk["details"]["reference_images"] == 1


@needs_model
def test_the_vocabulary_gains_no_member_for_the_bulk_path(
    client: TestClient, conn: psycopg.Connection, administrator: Any, audit_rows: AuditRows
) -> None:
    # Stated over what the log actually holds rather than over `AuditAction`,
    # which `test_audit.py` already pins at sixteen: a batch writes
    # `catalogue_tile_added` and nothing else at all — not a `batch_started`,
    # not a `batch_finished`, and not one entry summarising the run. The plan
    # phase records nothing either: it reads a sheet and changes nothing, which
    # is `lookup_tile`'s own argument for recording no read.
    bulk(client, _FIVE_ROWS, _FIVE_IMAGES)

    # The sign-in is the fixture's, not the batch's, and is excluded by name
    # rather than by filtering to catalogue actions — the claim is that the
    # batch added *no* vocabulary, so a `batch_started` would have to show up
    # here and an over-narrow filter would hide exactly that.
    assert {row["action"] for row in audit_rows(conn)} - {"login_succeeded"} == {
        "catalogue_tile_added"
    }


def test_a_refused_plan_records_nothing(
    client: TestClient, conn: psycopg.Connection, administrator: Any, audit_rows: AuditRows
) -> None:
    # A manifest that cannot be read changed nothing, so there is nothing to
    # record — the add path's argument for a `409` or a `422`, one level up.
    assert plan(client, b"not,a,manifest\n", [("1.jpg", an_image(1))]).status_code == 422

    assert catalogue_entries(conn, audit_rows) == []


def test_a_refused_caller_writes_no_bulk_entry(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser, audit_rows: AuditRows
) -> None:
    account = make_user(role=Role.STAFF)
    client.post(LOGIN, json={"email": account.email, "password": account.password})

    assert plan(client, _FIVE_ROWS, _FIVE_IMAGES).status_code == 403

    assert catalogue_entries(conn, audit_rows) == []
