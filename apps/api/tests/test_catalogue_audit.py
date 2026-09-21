"""Every catalogue change is attributable, permanent, and written with the change.

Story 1.12 built the append-only log and Story 1.13 the read; this is the first
entry Epic 2 writes, and the first in the product that names something other
than an account. Three properties, and the third is the one a later story is
most likely to break:

* a successful add writes **exactly one** `catalogue_tile_added` entry, with
  the actor, the source address and the Code;
* a refused add writes **none** — a `409`, a `422` or a `413` changed nothing,
  so there is nothing to record;
* the entry and the Tile are in **one transaction**, so neither can exist
  without the other.

The Tile is named in `details` as a denormalized snapshot, never as a foreign
key (AD-10): removal (Story 2.3) is a hard delete and the log may neither
block it nor be cascaded into.
"""

from __future__ import annotations

import io
from collections.abc import Callable
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
