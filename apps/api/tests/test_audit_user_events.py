"""Every entry `api.users` writes — FR-20's "who changed whose access" half.

Five writes, five actions, and two rules that matter more than any of them:

**A refused write records nothing.** A `403`, a `404` or a `409` changed no
row, so there is nothing to record — and a log that carried attempts as well as
changes would answer "was this account ever deactivated?" with a row that says
somebody tried. Each refusal below asserts the log is exactly as long as it was.

**A deleted user's entries survive the delete.** That is the whole reason
AD-10's snapshot rule reaches this table: the id stops joining, the address
does not, and the delete is not blocked by anything. `test_delete_user.py`
proves the hard delete; this file proves it left its record behind.

`conn` is the owner connection, used to read the log back. The writes go
through the real endpoints under a real Administrator session, because the
actor is the caller and there is no other way to establish one.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from api.audit import TRUSTED_PROXY_HEADER, AuditAction
from api.db import DATABASE_URL
from api.main import create_app
from fastapi.testclient import TestClient
from shared_schema.passwords import MIN_PASSWORD_LENGTH
from shared_schema.user import Role

LOGIN = "/auth/login"
CREATE_USER = "/admin/users"

TEMPORARY = "t" * (MIN_PASSWORD_LENGTH + 8)

#: What `conftest.client` presents as its peer, and therefore what every
#: `source_ip` in this file must be.
PEER = "127.0.0.1"

MakeUser = Callable[..., Any]
AuditRows = Callable[[psycopg.Connection], list[dict[str, Any]]]


def _edit_path(user_id: Any) -> str:
    return f"/admin/users/{user_id}"


def _deactivate_path(user_id: Any) -> str:
    return f"/admin/users/{user_id}/deactivate"


def _activate_path(user_id: Any) -> str:
    return f"/admin/users/{user_id}/activate"


def _body(**overrides: Any) -> dict[str, Any]:
    submitted: dict[str, Any] = {
        "name": "Nadeesha Silva",
        "email": "nadeesha@rocell.lk",
        "role": Role.STAFF.value,
        "temporary_password": TEMPORARY,
    }
    submitted.update(overrides)
    return submitted


@pytest.fixture(autouse=True)
def _no_trusted_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin `source_ip` to the peer for every test in this file.

    Every handler below is asserted to record `PEER`. With
    `TRUSTED_PROXY_HEADER` exported — by a developer, or by a CI runner that
    sets it for an integration stage — `api.audit.source_ip` reads a header
    the test client never sends, every assertion sees `None`, and the failure
    blames this story for the environment. `test_audit_source_ip.py` is where
    the configured-header behaviour is exercised on purpose.
    """
    monkeypatch.delenv(TRUSTED_PROXY_HEADER, raising=False)


@pytest.fixture
def administrator(client: TestClient, make_user: MakeUser) -> Any:
    """A claimed Administrator, signed in on `client`."""
    account = make_user(role=Role.ADMIN, name="Ruwan Jayasuriya")
    assert (
        client.post(LOGIN, json={"email": account.email, "password": account.password}).status_code
        == 200
    )
    return account


def _writes(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The admin-write entries, with the Administrator's own sign-in dropped.

    Every test here signs in first, so every log starts with a
    `login_succeeded` that is not what the test is about.
    """
    return [row for row in rows if row["action"] != AuditAction.LOGIN_SUCCEEDED]


def _sign_in_elsewhere(migrated_url: str, account: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Open a session for `account` on a second browser, and leave it open.

    A second `TestClient` over the same database, so the session it opens is
    not the one the first client is holding. Closed immediately: the point is
    the row it left in `sessions`, not the client.
    """
    monkeypatch.setenv(DATABASE_URL, migrated_url)
    with TestClient(
        create_app(), base_url="https://elsewhere", client=("127.0.0.1", 50001)
    ) as other:
        assert (
            other.post(
                LOGIN, json={"email": account.email, "password": account.password}
            ).status_code
            == 200
        )


def _only(rows: list[dict[str, Any]], action: AuditAction) -> dict[str, Any]:
    matching = [row for row in rows if row["action"] == action]
    assert len(matching) == 1, f"expected exactly one {action}, found {len(matching)} in {rows}"
    return matching[0]


# --- Provisioning ---------------------------------------------------------------


def test_provisioning_records_who_granted_whose_access(
    client: TestClient, conn: psycopg.Connection, administrator: Any, audit_rows: AuditRows
) -> None:
    # DW-77, closed. Until this entry existed the only trace of a provisioning
    # was the row's own `created_at`, which does not say by whom.
    response = client.post(CREATE_USER, json=_body())
    assert response.status_code == 201
    created = response.json()

    entry = _only(_writes(audit_rows(conn)), AuditAction.USER_PROVISIONED)
    assert entry["actor_user_id"] == administrator.id
    assert entry["actor_email"] == administrator.email
    assert entry["target_user_id"] == UUID(created["id"])
    assert entry["target_email"] == created["email"]
    assert entry["details"] == {"role": Role.STAFF.value}
    assert entry["source_ip"] == PEER


def test_the_temporary_password_reaches_no_row(
    client: TestClient, conn: psycopg.Connection, administrator: Any, audit_rows: AuditRows
) -> None:
    assert client.post(CREATE_USER, json=_body()).status_code == 201
    assert TEMPORARY not in str(audit_rows(conn))


def test_a_duplicate_address_writes_no_entry(
    client: TestClient, conn: psycopg.Connection, administrator: Any, audit_rows: AuditRows
) -> None:
    # The `409` wrote no `users` row, so it writes no entry either — and the
    # transaction `create_user` now opens is what makes the second half follow
    # from the first rather than being remembered separately.
    assert client.post(CREATE_USER, json=_body()).status_code == 201
    before = len(audit_rows(conn))

    assert client.post(CREATE_USER, json=_body()).status_code == 409
    assert len(audit_rows(conn)) == before


def test_a_staff_caller_is_refused_and_writes_no_entry(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser, audit_rows: AuditRows
) -> None:
    # `403` from the dependency, before the handler is entered at all. There
    # is no actor's *action* to record — `require_administrator` refused a
    # request, and a refused request is not a user change.
    staff = make_user(role=Role.STAFF)
    assert (
        client.post(LOGIN, json={"email": staff.email, "password": staff.password}).status_code
        == 200
    )
    before = len(audit_rows(conn))

    assert client.post(CREATE_USER, json=_body()).status_code == 403
    assert len(audit_rows(conn)) == before


# --- Editing ----------------------------------------------------------------------


def test_an_edit_records_only_the_fields_that_moved(
    client: TestClient,
    conn: psycopg.Connection,
    administrator: Any,
    make_user: MakeUser,
    audit_rows: AuditRows,
) -> None:
    target = make_user(name="Kasun Perera")

    assert client.patch(_edit_path(target.id), json={"name": "Kasun Silva"}).status_code == 200

    entry = _only(_writes(audit_rows(conn)), AuditAction.USER_EDITED)
    assert entry["actor_user_id"] == administrator.id
    assert entry["target_user_id"] == target.id
    assert entry["details"] == {"changed": {"name": {"from": "Kasun Perera", "to": "Kasun Silva"}}}
    # Asserted per handler, not once for the whole story: `source_ip` is a
    # defaulted keyword on `audit.record`, so a handler that stopped passing
    # it would write `NULL` and break nothing anywhere else.
    assert entry["source_ip"] == PEER


def test_an_edit_records_all_three_text_columns_and_nothing_else(
    client: TestClient,
    conn: psycopg.Connection,
    administrator: Any,
    make_user: MakeUser,
    audit_rows: AuditRows,
) -> None:
    # `name`, `email`, `role` — the three columns `PATCH` may write. The
    # eight others are deliberately absent: `updated_at` moves on every edit
    # and would be noise in every entry, and `locked_until` can move through
    # the counter carry without anybody having edited it.
    target = make_user(name="Kasun Perera", role=Role.STAFF)

    assert (
        client.patch(
            _edit_path(target.id),
            json={"name": "Kasun Silva", "email": "kasun@rocell.lk", "role": Role.ADMIN.value},
        ).status_code
        == 200
    )

    entry = _only(_writes(audit_rows(conn)), AuditAction.USER_EDITED)
    assert entry["details"] == {
        "changed": {
            "name": {"from": "Kasun Perera", "to": "Kasun Silva"},
            "email": {"from": target.email, "to": "kasun@rocell.lk"},
            "role": {"from": Role.STAFF.value, "to": Role.ADMIN.value},
        }
    }


def test_an_edit_that_moved_nothing_records_an_empty_diff(
    client: TestClient,
    conn: psycopg.Connection,
    administrator: Any,
    make_user: MakeUser,
    audit_rows: AuditRows,
) -> None:
    # A `PATCH` resending the values already stored is accepted and changes
    # no column. The entry says so rather than claiming a change: an entry
    # that overstated would be indistinguishable from a real rename.
    target = make_user(name="Kasun Perera")

    assert client.patch(_edit_path(target.id), json={"name": "Kasun Perera"}).status_code == 200

    entry = _only(_writes(audit_rows(conn)), AuditAction.USER_EDITED)
    assert entry["details"] == {"changed": {}}


def test_an_edit_of_an_unknown_id_writes_no_entry(
    client: TestClient, conn: psycopg.Connection, administrator: Any, audit_rows: AuditRows
) -> None:
    before = len(audit_rows(conn))
    assert client.patch(_edit_path(uuid4()), json={"name": "Nobody"}).status_code == 404
    assert len(audit_rows(conn)) == before


def test_a_demotion_refused_by_the_floor_writes_no_entry(
    client: TestClient, conn: psycopg.Connection, administrator: Any, audit_rows: AuditRows
) -> None:
    # The `409` raises inside the transaction, which unwinds it — so "no
    # entry" is not a branch anybody had to remember, it is what the rollback
    # already does.
    before = len(audit_rows(conn))
    assert (
        client.patch(_edit_path(administrator.id), json={"role": Role.STAFF.value}).status_code
        == 409
    )
    assert len(audit_rows(conn)) == before


# --- Deactivating and reactivating --------------------------------------------------


def test_a_deactivation_records_how_many_sessions_it_revoked(
    client: TestClient,
    conn: psycopg.Connection,
    administrator: Any,
    make_user: MakeUser,
    audit_rows: AuditRows,
    migrated_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The destructive half of the operation, and the half nothing else in the
    # product records. `updated_at` says the flag moved; only this says how
    # many devices went with it.
    target = make_user()
    # The target signs in on a client of its own. Signing in on `client`
    # would put its cookie where the Administrator's was, and signing the
    # Administrator back in would then *spend* the target's session — login
    # revokes the cookie the browser arrived with — leaving nothing for the
    # deactivation to revoke and a count of 0 that proved nothing.
    _sign_in_elsewhere(migrated_url, target, monkeypatch)

    assert client.post(_deactivate_path(target.id)).status_code == 200

    entry = _only(_writes(audit_rows(conn)), AuditAction.USER_DEACTIVATED)
    assert entry["actor_user_id"] == administrator.id
    assert entry["target_user_id"] == target.id
    assert entry["target_email"] == target.email
    assert entry["details"] == {"sessions_revoked": 1}
    assert entry["source_ip"] == PEER


def test_a_second_deactivation_records_nothing_was_open(
    client: TestClient,
    conn: psycopg.Connection,
    administrator: Any,
    make_user: MakeUser,
    audit_rows: AuditRows,
) -> None:
    # Idempotent, and still recorded: "somebody pressed it again and nothing
    # was open" is a fact worth having, and a count of 0 is the honest way to
    # say it.
    target = make_user()
    assert client.post(_deactivate_path(target.id)).status_code == 200
    assert client.post(_deactivate_path(target.id)).status_code == 200

    entries = [
        row for row in _writes(audit_rows(conn)) if row["action"] == AuditAction.USER_DEACTIVATED
    ]
    assert [row["details"] for row in entries] == [
        {"sessions_revoked": 0},
        {"sessions_revoked": 0},
    ]


def test_a_reactivation_records_the_actor_and_no_details(
    client: TestClient,
    conn: psycopg.Connection,
    administrator: Any,
    make_user: MakeUser,
    audit_rows: AuditRows,
) -> None:
    target = make_user(active=False)

    assert client.post(_activate_path(target.id)).status_code == 200

    entry = _only(_writes(audit_rows(conn)), AuditAction.USER_ACTIVATED)
    assert entry["actor_user_id"] == administrator.id
    assert entry["target_user_id"] == target.id
    assert entry["target_email"] == target.email
    # Giving access back restores a flag and nothing else, so there is no
    # count of anything to report.
    assert entry["details"] == {}
    assert entry["source_ip"] == PEER


def test_a_deactivation_refused_by_the_floor_writes_no_entry(
    client: TestClient, conn: psycopg.Connection, administrator: Any, audit_rows: AuditRows
) -> None:
    before = len(audit_rows(conn))
    assert client.post(_deactivate_path(administrator.id)).status_code == 409
    assert len(audit_rows(conn)) == before


def test_a_deactivation_of_an_unknown_id_writes_no_entry(
    client: TestClient, conn: psycopg.Connection, administrator: Any, audit_rows: AuditRows
) -> None:
    before = len(audit_rows(conn))
    assert client.post(_deactivate_path(uuid4())).status_code == 404
    assert len(audit_rows(conn)) == before


# --- Deleting -----------------------------------------------------------------------


def test_a_delete_records_the_row_it_removed(
    client: TestClient,
    conn: psycopg.Connection,
    administrator: Any,
    make_user: MakeUser,
    audit_rows: AuditRows,
) -> None:
    # A delete used to leave no trace at all. The snapshot is taken from the
    # locked read a moment before the row went, so it describes what was
    # actually removed.
    target = make_user(name="Kasun Perera", role=Role.STAFF)

    assert client.delete(_edit_path(target.id)).status_code == 204

    entry = _only(_writes(audit_rows(conn)), AuditAction.USER_DELETED)
    assert entry["actor_user_id"] == administrator.id
    assert entry["target_user_id"] == target.id
    assert entry["target_email"] == target.email
    assert entry["details"] == {"role": Role.STAFF.value, "active": True}
    assert entry["source_ip"] == PEER


def test_the_delete_is_not_blocked_by_the_entries_naming_the_target(
    client: TestClient,
    conn: psycopg.Connection,
    administrator: Any,
    make_user: MakeUser,
    audit_rows: AuditRows,
) -> None:
    # AD-10's whole reason for reaching this table. The target already has
    # entries of its own — it signed in, it was edited — and none of them is
    # a foreign key, so none of them can refuse the delete or be cascaded
    # into a table the application role holds no `DELETE` on.
    target = make_user()
    assert (
        client.post(LOGIN, json={"email": target.email, "password": target.password}).status_code
        == 200
    )
    assert (
        client.post(
            LOGIN, json={"email": administrator.email, "password": administrator.password}
        ).status_code
        == 200
    )
    assert client.patch(_edit_path(target.id), json={"name": "Renamed"}).status_code == 200

    naming_target_before = [
        row
        for row in audit_rows(conn)
        if target.id in (row["actor_user_id"], row["target_user_id"])
    ]
    assert len(naming_target_before) >= 2

    assert client.delete(_edit_path(target.id)).status_code == 204
    assert conn.execute(
        "SELECT count(*) AS total FROM users WHERE id = %s", (target.id,)
    ).fetchone() == {"total": 0}

    naming_target_after = [
        row
        for row in audit_rows(conn)
        if target.id in (row["actor_user_id"], row["target_user_id"])
    ]
    # Every earlier entry survives, and the delete added one more.
    assert len(naming_target_after) == len(naming_target_before) + 1
    # And the snapshots are intact: the id still points at a row that no
    # longer exists, and the address is what the entry now means.
    assert all(
        row["target_email"] == target.email or row["actor_email"] == target.email
        for row in naming_target_after
        if row["target_email"] is not None or row["actor_email"] is not None
    )


def test_a_delete_refused_by_the_floor_writes_no_entry(
    client: TestClient, conn: psycopg.Connection, administrator: Any, audit_rows: AuditRows
) -> None:
    before = len(audit_rows(conn))
    assert client.delete(_edit_path(administrator.id)).status_code == 409
    assert len(audit_rows(conn)) == before


def test_a_delete_of_an_unknown_id_writes_no_entry(
    client: TestClient, conn: psycopg.Connection, administrator: Any, audit_rows: AuditRows
) -> None:
    before = len(audit_rows(conn))
    assert client.delete(_edit_path(uuid4())).status_code == 404
    assert len(audit_rows(conn)) == before


# --- All five, once ------------------------------------------------------------------


def test_the_five_writes_produce_the_five_actions(
    client: TestClient,
    conn: psycopg.Connection,
    administrator: Any,
    audit_rows: AuditRows,
) -> None:
    # One pass over the whole surface, so a handler that quietly stopped
    # writing its entry fails here as well as in its own test.
    created = client.post(CREATE_USER, json=_body()).json()
    user_id = created["id"]
    assert client.patch(_edit_path(user_id), json={"name": "Renamed"}).status_code == 200
    assert client.post(_deactivate_path(user_id)).status_code == 200
    assert client.post(_activate_path(user_id)).status_code == 200
    assert client.delete(_edit_path(user_id)).status_code == 204

    assert [row["action"] for row in _writes(audit_rows(conn))] == [
        AuditAction.USER_PROVISIONED,
        AuditAction.USER_EDITED,
        AuditAction.USER_DEACTIVATED,
        AuditAction.USER_ACTIVATED,
        AuditAction.USER_DELETED,
    ]
    # Every one of them names the Administrator who did it — which is the
    # question FR-20 asks of this module and the one `updated_at` never could.
    assert {row["actor_user_id"] for row in _writes(audit_rows(conn))} == {administrator.id}
