"""`PATCH /admin/users/{user_id}` — FR-12, every API row of Story 1.10's matrix.

The authorization *guard* lives in `test_admin_authorization.py`, which holds the
role check to the route table in both directions and covers this route without
having been taught about it — that is the property it was written for — and which
also carries the live Staff refusal against this path. The forced-change gate is
inherited through `require_administrator` and needs no allowlist entry in
`test_forced_change_gate.py`; the one test here proves it rather than leaving the
next reader to check.

This file is about the write: which columns move, which do not, what the two
refusals are, and the half of FR-12 that is not this story's code at all —
**a role change takes effect on the target's very next request**, which AD-3's
one session lookup already does. That half is proved here rather than built, and
the way it is proved is the only way that means anything: one signed-in target,
one cookie, a request before and a request after, with no sign-out in between.

The throttle counter's half of a rename is `test_edit_user_throttle_carry.py`.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest
from api import users
from api.dependencies import PASSWORD_CHANGE_REQUIRED, UNAUTHORIZED
from api.main import create_app
from api.sessions import SESSION_COOKIE_NAME
from api.users import (
    EMAIL_ALREADY_EXISTS,
    INVALID_EMAIL,
    LAST_ADMINISTRATOR,
    MAX_NAME_LENGTH,
    NOT_AN_ADDRESS,
    USER_NOT_FOUND,
)
from fastapi.testclient import TestClient
from psycopg import errors as pg_errors
from psycopg.rows import dict_row
from shared_schema.user import Role, User

LIST_USERS = "/admin/users"
LOGIN = "/auth/login"
SESSION = "/auth/session"

MakeUser = Callable[..., Any]

#: How long the concurrency test below will wait for the transaction it holds
#: open, before failing rather than hanging the suite.
HELD_TRANSACTION_TIMEOUT = 10.0

#: How long that transaction stays open once the live request has started. Long
#: enough that the request is genuinely waiting on the lock; short enough that
#: this is a second of one test rather than a habit.
OVERLAP_SECONDS = 1.0


def _edit_path(user_id: Any) -> str:
    return f"/admin/users/{user_id}"


def _sign_in(client: TestClient, account: Any) -> None:
    response = client.post(LOGIN, json={"email": account.email, "password": account.password})
    assert response.status_code == 200


@pytest.fixture
def their_client(client: TestClient) -> Any:
    """A second client, on the same database, for the *target* of an edit.

    Its own app instance rather than a second `TestClient` over `client`'s: the
    lifespan builds the connection pool and tears it down, so a nested client
    over one app would close the pool the outer one is still using. `client`'s
    fixture has already pointed `DATABASE_URL` at this test's database, and
    `create_app()` reads it at startup.

    A separate cookie jar is the whole point — this is the person whose role is
    being changed under them, holding the cookie they already had.
    """

    def factory() -> Any:
        return TestClient(create_app(), base_url="https://testserver")

    return factory


@pytest.fixture
def administrator(client: TestClient, make_user: MakeUser) -> Any:
    """A claimed Administrator, signed in on `client`.

    `make_user(role=Role.ADMIN)` already produces one — `must_change_password`
    defaults to `False` there — so the fixture is only the sign-in.
    """
    account = make_user(role=Role.ADMIN, name="Ruwan Jayasuriya")
    _sign_in(client, account)
    return account


def _row(conn: psycopg.Connection, user_id: Any) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM users WHERE id = %s", (user_id,)).fetchone()
    assert row is not None, f"{user_id} is not in the table"
    return dict(row)


def _edit(client: TestClient, user_id: Any, body: dict[str, Any]) -> Any:
    return client.patch(_edit_path(user_id), json=body)


# --- What the edit writes -----------------------------------------------------


def test_a_rename_stores_the_stripped_name_and_moves_nothing_else(
    client: TestClient, conn: psycopg.Connection, administrator: Any, make_user: MakeUser
) -> None:
    # The matrix's first row, and the one that states the shape of every other:
    # one column moves, `updated_at` moves with it, and the other nine are
    # byte-identical afterwards. Asserted over the whole row rather than over the
    # columns this test happens to think of, so a statement that quietly cleared
    # `locked_until` or re-flagged `must_change_password` fails here.
    target = make_user(name="Kasun Perera")
    before = _row(conn, target.id)

    response = _edit(client, target.id, {"name": "  Kasun Perera Jr  "})

    assert response.status_code == 200
    assert response.json()["name"] == "Kasun Perera Jr"

    after = _row(conn, target.id)
    assert after["name"] == "Kasun Perera Jr"
    assert after["updated_at"] > before["updated_at"]
    assert after["created_at"] == before["created_at"]
    assert {key: value for key, value in after.items() if key not in {"name", "updated_at"}} == {
        key: value for key, value in before.items() if key not in {"name", "updated_at"}
    }


def test_the_address_is_folded_by_the_database(
    client: TestClient, conn: psycopg.Connection, administrator: Any, make_user: MakeUser
) -> None:
    # `users` carries `CHECK (email = lower(email))` and its only unique index is
    # `ON (lower(email))`. The statement writes `lower(%s)` so the constraint is
    # unfailable by construction — see `_UPDATE_USER`.
    target = make_user(name="Kasun Perera")

    response = _edit(client, target.id, {"email": "  RUWAN@ROCELL.LK  "})

    assert response.status_code == 200
    assert response.json()["email"] == "ruwan@rocell.lk"
    assert _row(conn, target.id)["email"] == "ruwan@rocell.lk"


def test_the_account_signs_in_at_the_new_address_and_not_the_old_one(
    client: TestClient, administrator: Any, make_user: MakeUser, their_client: Any
) -> None:
    # The only assertion that proves a readdress actually moved the *login*
    # rather than a column somebody renders. DW-79 is closed by this: a mistyped
    # address is recoverable.
    target = make_user(name="Kasun Perera")
    old_address = target.email

    assert _edit(client, target.id, {"email": "kasun.perera@rocell.lk"}).status_code == 200

    # A separate client, so the Administrator's own cookie is not what is being
    # tested. `TestClient` keeps a cookie jar per instance.
    with their_client() as theirs:
        refused = theirs.post(LOGIN, json={"email": old_address, "password": target.password})
        assert refused.status_code == 401

        accepted = theirs.post(
            LOGIN, json={"email": "kasun.perera@rocell.lk", "password": target.password}
        )
        assert accepted.status_code == 200


def test_the_targets_live_session_survives_a_readdress(
    client: TestClient, administrator: Any, make_user: MakeUser, their_client: Any
) -> None:
    # **An address change revokes nothing**, and this is the only thing that says
    # so. The role-change half of FR-12 is tested either side of the same cookie
    # above; without this the readdress half is unpinned, and a later change that
    # started revoking sessions on a corrected typo would ship green.
    #
    # It is deliberate rather than an omission: a corrected typo is an
    # Administrator fixing their own mistake, not evidence the account is
    # compromised, and signing somebody out of a shift for it would make the
    # correction cost more than the mistake. Revocation belongs to the events
    # that are about the credential — a password change, and Story 1.11's
    # deactivation.
    target = make_user(name="Kasun Perera")

    with their_client() as theirs:
        _sign_in(theirs, target)
        assert theirs.get(SESSION).status_code == 200

        assert _edit(client, target.id, {"email": "kasun.perera@rocell.lk"}).status_code == 200

        # The very next request, on the cookie they already held.
        still_signed_in = theirs.get(SESSION)
        assert still_signed_in.status_code == 200
        # And it reports the new address, because the session lookup re-reads the
        # row on every request (AD-3) rather than caching what it was issued for.
        assert still_signed_in.json()["email"] == "kasun.perera@rocell.lk"


def test_an_unclaimed_account_is_readdressed_and_keeps_its_temporary_credential(
    client: TestClient, administrator: Any, make_user: MakeUser, their_client: Any
) -> None:
    # **DW-79's closure, end to end.** The realistic mistake is an address
    # mistyped at provisioning time, caught before the credential is handed over.
    # Correcting it has to leave the account usable: the same temporary password
    # signs in at the new address, and still lands on the forced-change screen
    # and nothing else.
    #
    # Without this the README's rewritten "a mistyped address is no longer a dead
    # end" rests on a rename test against an account that had already claimed
    # itself — which is not the case anybody hits.
    unclaimed = make_user(
        must_change_password=True,
        temp_credential_expires_at=datetime.now(UTC) + timedelta(hours=72),
        name="Nadeesha Silva",
    )

    assert _edit(client, unclaimed.id, {"email": "nadeesha@rocell.lk"}).status_code == 200

    with their_client() as theirs:
        # The old address is gone, credential or not.
        assert (
            theirs.post(
                LOGIN, json={"email": unclaimed.email, "password": unclaimed.password}
            ).status_code
            == 401
        )

        signed_in = theirs.post(
            LOGIN, json={"email": "nadeesha@rocell.lk", "password": unclaimed.password}
        )
        assert signed_in.status_code == 200
        # Still unclaimed: the rename touched neither the flag nor the deadline,
        # so Story 1.4's gate is exactly where it was.
        assert signed_in.json()["must_change_password"] is True
        assert signed_in.json()["temp_credential_expires_at"] is not None

        # And the credential still reaches the password-change screen and
        # nothing else.
        gated = theirs.get(LIST_USERS)
        assert gated.status_code == 403
        assert gated.json()["error"]["code"] == PASSWORD_CHANGE_REQUIRED


def test_all_three_fields_are_written_in_one_statement(
    client: TestClient, conn: psycopg.Connection, administrator: Any, make_user: MakeUser
) -> None:
    # One `updated_at`, not three: the statement is one `UPDATE` with three
    # `COALESCE`s, so there is no ordering between the columns and no partial
    # write to be left behind by a failure halfway down a list of statements.
    target = make_user(name="Kasun Perera")

    response = _edit(
        client,
        target.id,
        {"name": "Kasun Perera", "email": "kp@rocell.lk", "role": Role.ADMIN.value},
    )

    assert response.status_code == 200
    body = response.json()
    assert (body["name"], body["email"], body["role"]) == (
        "Kasun Perera",
        "kp@rocell.lk",
        Role.ADMIN.value,
    )

    after = _row(conn, target.id)
    assert (after["name"], after["email"], after["role"]) == (
        "Kasun Perera",
        "kp@rocell.lk",
        Role.ADMIN.value,
    )
    # One statement, so one `updated_at` — the value the response carried is the
    # value in the column, not one of three written in sequence. Parsed rather
    # than compared as text: the contract's wire format is ISO 8601 UTC and the
    # column is `timestamptz`, and this assertion is about the *instant*.
    assert datetime.fromisoformat(body["updated_at"]) == after["updated_at"]


def test_an_administrator_may_edit_their_own_row(
    client: TestClient, conn: psycopg.Connection, administrator: Any
) -> None:
    # Nothing protects the caller from their own row: it is theirs, and the floor
    # below still refuses the one change that would leave nobody in charge.
    response = _edit(client, administrator.id, {"name": "Ruwan J."})

    assert response.status_code == 200
    assert response.json()["id"] == str(administrator.id)
    assert _row(conn, administrator.id)["name"] == "Ruwan J."


# --- FR-12's live-session half, which is AD-3's and not this story's code ------


def test_a_promoted_staff_user_is_served_as_an_administrator_on_the_next_request(
    client: TestClient, administrator: Any, make_user: MakeUser, their_client: Any
) -> None:
    # The acceptance clause, end to end and on one cookie. `lookup_session`
    # re-reads `role` from Postgres on every request (AD-3), so the promotion
    # lands on the target's *next* request with no sign-out, no new sign-in and
    # no change to `api/sessions.py`.
    target = make_user(role=Role.STAFF, name="Kasun Perera")

    with their_client() as theirs:
        _sign_in(theirs, target)
        assert theirs.get(LIST_USERS).status_code == 403

        assert _edit(client, target.id, {"role": Role.ADMIN.value}).status_code == 200

        # The very next request, on the cookie they already held.
        assert theirs.get(LIST_USERS).status_code == 200


def test_a_demoted_administrator_is_refused_on_the_next_request(
    client: TestClient, administrator: Any, make_user: MakeUser, their_client: Any
) -> None:
    # The same clause in the other direction, which is the one that matters for
    # access: a revoked permission is revoked on the request immediately after
    # the change, not at the next sign-in.
    target = make_user(role=Role.ADMIN, name="Kasun Perera")

    with their_client() as theirs:
        _sign_in(theirs, target)
        assert theirs.get(LIST_USERS).status_code == 200

        assert _edit(client, target.id, {"role": Role.STAFF.value}).status_code == 200

        refused = theirs.get(LIST_USERS)
        assert refused.status_code == 403
        assert refused.json()["error"]["code"] == "administrator_required"


def test_a_self_demotion_lands_on_the_callers_own_next_request(
    client: TestClient, administrator: Any, make_user: MakeUser
) -> None:
    # The caller demoting themselves is the same mechanism pointed inward. The
    # response to the demotion itself is a `200` — it was made as an
    # Administrator — and the request after it is not theirs to make.
    make_user(role=Role.ADMIN, name="Nadeesha Silva")

    assert _edit(client, administrator.id, {"role": Role.STAFF.value}).status_code == 200

    refused = client.get(LIST_USERS)
    assert refused.status_code == 403
    assert refused.json()["error"]["code"] == "administrator_required"

    # And the session itself is untouched: a demotion is not a sign-out.
    assert client.get(SESSION).status_code == 200


# --- The Administrator floor --------------------------------------------------


def test_demoting_the_last_active_administrator_is_refused(
    client: TestClient, conn: psycopg.Connection, administrator: Any, make_user: MakeUser
) -> None:
    # The seeded shape: exactly one active Administrator in the product, and a
    # room full of Staff. Demoting them leaves nobody who can promote anybody,
    # recoverable only with `DATABASE_URL` in hand — which is the dependency
    # Epic 1 exists to remove.
    make_user(role=Role.STAFF, name="Kasun Perera")
    before = _row(conn, administrator.id)

    response = _edit(client, administrator.id, {"role": Role.STAFF.value})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == LAST_ADMINISTRATOR
    assert _row(conn, administrator.id) == before


def test_the_refusal_writes_nothing_at_all(
    client: TestClient, conn: psycopg.Connection, administrator: Any
) -> None:
    # Including the two columns that arrived beside the role. One statement means
    # the floor refuses the whole request rather than the role half of it, so a
    # rename smuggled in alongside a refused demotion does not land either.
    before = _row(conn, administrator.id)

    response = _edit(
        client,
        administrator.id,
        {"name": "Somebody Else", "email": "somebody@rocell.lk", "role": Role.STAFF.value},
    )

    assert response.status_code == 409
    assert _row(conn, administrator.id) == before


def test_the_same_demotion_succeeds_once_a_second_administrator_exists(
    client: TestClient, conn: psycopg.Connection, administrator: Any, make_user: MakeUser
) -> None:
    # The other half of the clause, and the one that proves the predicate is a
    # count of *other* active Administrators rather than a rule against demoting
    # anybody at all.
    make_user(role=Role.ADMIN, name="Nadeesha Silva")

    response = _edit(client, administrator.id, {"role": Role.STAFF.value})

    assert response.status_code == 200
    assert response.json()["role"] == Role.STAFF.value
    assert _row(conn, administrator.id)["role"] == Role.STAFF.value


def test_a_deactivated_administrator_does_not_count_toward_the_floor(
    client: TestClient, conn: psycopg.Connection, administrator: Any, make_user: MakeUser
) -> None:
    # A deactivated account cannot sign in, so it is not one of the active
    # Administrators the floor counts — on either side of the predicate. Here it
    # is the *target*, and demoting it is allowed.
    #
    # **Which arm of the predicate allows it, stated honestly.** It is the
    # `EXISTS`, not `NOT active`: the caller reached this route through
    # `require_administrator`, whose session lookup carries `AND u.active`, so
    # there is always at least one active Administrator — the caller — and when
    # the target is a *different*, deactivated row the `EXISTS` is already true.
    # `_UPDATE_USER`'s `OR NOT active` arm therefore decides nothing on any path
    # this route can reach, and deleting it fails no test here. It is kept
    # deliberately: Story 1.11 is meant to reuse this predicate for deactivate
    # and delete, where the target and the actor are not constrained the same
    # way, and the arm is what makes the rule "never zero *active*" rather than
    # "never zero rows". Widening or dropping it is that story's call to make
    # with DW-90, not a thing to trim because today's caller cannot exercise it.
    deactivated = make_user(role=Role.ADMIN, active=False, name="Amal Perera")

    response = _edit(client, deactivated.id, {"role": Role.STAFF.value})

    assert response.status_code == 200
    assert _row(conn, deactivated.id)["role"] == Role.STAFF.value


def test_a_deactivated_administrator_does_not_keep_the_floor_up(
    client: TestClient, conn: psycopg.Connection, administrator: Any, make_user: MakeUser
) -> None:
    # The same rule from the other side, and the one that would be missed by a
    # predicate written as `EXISTS (... role = 'admin')` with no `active`: a
    # deactivated Administrator must not be what allows the last *active* one to
    # be demoted.
    make_user(role=Role.ADMIN, active=False, name="Amal Perera")

    response = _edit(client, administrator.id, {"role": Role.STAFF.value})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == LAST_ADMINISTRATOR
    assert _row(conn, administrator.id)["role"] == Role.ADMIN.value


def test_promoting_is_never_refused_by_the_floor(
    client: TestClient, administrator: Any, make_user: MakeUser
) -> None:
    # The predicate's first arm. A change that ends with the row an
    # Administrator can only raise the count, so it is allowed whatever the
    # count is — including re-sending `admin` to somebody who already is one.
    target = make_user(role=Role.STAFF, name="Kasun Perera")

    assert _edit(client, target.id, {"role": Role.ADMIN.value}).status_code == 200
    assert _edit(client, target.id, {"role": Role.ADMIN.value}).status_code == 200


def test_the_only_administrator_can_still_be_renamed(
    client: TestClient, administrator: Any
) -> None:
    # The floor predicate reads the *resulting* role, so an edit that carries no
    # role at all coalesces to the row's own and passes. Without that this would
    # be a 409, and the only Administrator in a new deployment could never fix a
    # typo in their own name.
    assert _edit(client, administrator.id, {"name": "Ruwan Jayasuriya Jr"}).status_code == 200


# --- The refusals -------------------------------------------------------------


def test_an_unknown_id_is_a_404(client: TestClient, administrator: Any) -> None:
    # Told rather than silently ignored: the Administrator is acting on a list
    # they fetched a moment ago, and a `200` would report a change to an account
    # that no longer exists.
    missing = "d3a1f7b2-5c48-4e9a-8b60-1f2e3d4c5b6a"

    response = _edit(client, missing, {"name": "Nobody"})

    assert response.status_code == 404
    assert response.json()["error"]["code"] == USER_NOT_FOUND


def test_a_malformed_id_is_a_422_and_reads_no_row(
    client: TestClient, conn: psycopg.Connection, administrator: Any, make_user: MakeUser
) -> None:
    # FastAPI's own path parsing, before the handler is entered. The generic
    # envelope is right here: there is no field on a form to mark.
    target = make_user(name="Kasun Perera")
    before = _row(conn, target.id)

    response = client.patch("/admin/users/not-a-uuid", json={"name": "Nobody"})

    assert response.status_code == 422
    assert set(response.json()) == {"error"}
    # The second half of this test's own name. A path parameter that never
    # parsed cannot name a row, so nothing in the table may have moved —
    # including `updated_at`, which is the column a write would touch even if it
    # changed no value anybody reads.
    assert _row(conn, target.id) == before


def test_an_address_already_in_use_is_a_409(
    client: TestClient, conn: psycopg.Connection, administrator: Any, make_user: MakeUser
) -> None:
    # Built from `users_email_lower_key` by name, exactly as the provisioning
    # write's is. The database is what decides, because a `SELECT` first is a
    # race that hands two people one login.
    target = make_user(name="Kasun Perera")
    before = _row(conn, target.id)

    response = _edit(client, target.id, {"email": administrator.email.upper()})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == EMAIL_ALREADY_EXISTS
    assert _row(conn, target.id) == before


def test_a_clash_on_another_index_is_not_described_as_a_duplicate_address(
    client: TestClient, conn: psycopg.Connection, administrator: Any, make_user: MakeUser
) -> None:
    # The `EMAIL_UNIQUE_INDEX` narrowing in the handler's `except`, exercised
    # rather than read. The test above cannot reach it: every clash it makes is
    # on the address index, so answering *every* `UniqueViolation` with `409`
    # would leave it green. `test_create_user.py` pins the same branch on the
    # provisioning write, and this handler's comment says it is "`_INSERT_USER`'s
    # reasoning, unchanged" — one rule, so both sites hold it.
    conn.execute("CREATE UNIQUE INDEX users_name_key ON users (name)")
    target = make_user(name="Kasun Perera")

    with pytest.raises(pg_errors.UniqueViolation) as raised:
        _edit(client, target.id, {"name": administrator.name})

    # Propagated, so `api.main` answers it as a 500 — honest about a clash this
    # endpoint cannot explain, rather than marking and focusing an email field
    # the Administrator got right.
    assert raised.value.diag.constraint_name == "users_name_key"


@pytest.mark.parametrize(
    "address",
    ["ruwan.rocell.lk", "a@b@c", "@rocell.lk", "ruwan@", "ru wan@rocell.lk", "ruwan\x00@x.lk"],
)
def test_an_address_that_is_not_one_is_refused_with_the_rule(
    client: TestClient, administrator: Any, make_user: MakeUser, address: str
) -> None:
    target = make_user(name="Kasun Perera")

    response = _edit(client, target.id, {"email": address})

    assert response.status_code == 422
    assert response.json()["error"] == {"code": INVALID_EMAIL, "message": NOT_AN_ADDRESS}


@pytest.mark.parametrize("name", ["   ", "", "Kasun\x00Perera", "a" * (MAX_NAME_LENGTH + 1)])
def test_a_name_the_write_would_refuse_is_refused_here_too(
    client: TestClient, administrator: Any, make_user: MakeUser, name: str
) -> None:
    # `_clean_name` is shared with `CreateUserRequest`, so a name that cannot be
    # created cannot be edited into place either.
    target = make_user(name="Kasun Perera")

    response = _edit(client, target.id, {"name": name})

    assert response.status_code == 422
    assert set(response.json()) == {"error"}


@pytest.mark.parametrize(
    "body",
    [
        {"name": None},
        {"email": None},
        {"role": None},
        # The cases the "at least one field" validator cannot catch, and
        # therefore the ones that actually need the `mode="before"` refusal: one
        # real field beside one explicit `null`. Without it the request is
        # accepted as though the `null` had never been sent, and a client that
        # believes it is clearing a column is told it succeeded.
        {"name": "Kasun P.", "email": None},
        {"role": Role.ADMIN.value, "name": None},
    ],
)
def test_an_explicit_null_is_refused(
    client: TestClient,
    conn: psycopg.Connection,
    administrator: Any,
    make_user: MakeUser,
    body: dict[str, Any],
) -> None:
    # Absent and `null` are not the same request. Without the `mode="before"`
    # refusal a `null` reads as "leave it alone", and a client bug becomes a
    # silent no-op nobody can see.
    target = make_user(name="Kasun Perera")
    before = _row(conn, target.id)

    assert _edit(client, target.id, body).status_code == 422
    assert _row(conn, target.id) == before


def test_an_empty_body_is_refused(
    client: TestClient, conn: psycopg.Connection, administrator: Any, make_user: MakeUser
) -> None:
    # So that no request in the product moves `updated_at` for nothing.
    target = make_user(name="Kasun Perera")
    before = _row(conn, target.id)

    assert _edit(client, target.id, {}).status_code == 422
    assert _row(conn, target.id) == before


@pytest.mark.parametrize(
    "body",
    [
        {"active": False},
        {"must_change_password": True},
        {"password_hash": "x"},
        {"locked_until": None},
        {"id": "d3a1f7b2-5c48-4e9a-8b60-1f2e3d4c5b6a"},
        {"name": "Kasun", "temporary_password": "x" * 24},
    ],
)
def test_a_field_this_route_does_not_write_is_refused(
    client: TestClient, conn: psycopg.Connection, administrator: Any, make_user: MakeUser, body: Any
) -> None:
    # `extra="forbid"`. A body naming `active` is a caller who believes this
    # endpoint deactivates accounts; answering `200` would be the product
    # reporting a deactivation it never performed.
    target = make_user(name="Kasun Perera")
    before = _row(conn, target.id)

    assert _edit(client, target.id, body).status_code == 422
    assert _row(conn, target.id) == before


@pytest.mark.parametrize("role", ["owner", "superuser", "ADMIN", ""])
def test_a_role_the_product_does_not_have_is_refused(
    client: TestClient, administrator: Any, make_user: MakeUser, role: str
) -> None:
    # AGENTS.md Policy: never a role beyond `staff` and `admin`. Refused by the
    # shared `Role` enum before the handler runs, with the database's own CHECK
    # as the second, independent copy.
    target = make_user(name="Kasun Perera")

    assert _edit(client, target.id, {"role": role}).status_code == 422


def test_an_unclaimed_administrator_is_refused_by_the_gate(
    client: TestClient, make_user: MakeUser
) -> None:
    # `require_administrator` chains on `require_claimed_user`, so this route
    # needs no entry in `test_forced_change_gate.py`'s allowlist — an
    # Administrator still holding a note-borne temporary credential cannot use it
    # to promote anybody, including themselves.
    unclaimed = make_user(
        role=Role.ADMIN,
        must_change_password=True,
        temp_credential_expires_at=datetime.now(UTC) + timedelta(hours=72),
        name="Ruwan Jayasuriya",
    )
    target = make_user(name="Kasun Perera")
    _sign_in(client, unclaimed)

    response = _edit(client, target.id, {"role": Role.ADMIN.value})

    assert response.status_code == 403
    assert response.json()["error"]["code"] == PASSWORD_CHANGE_REQUIRED


def test_no_session_is_refused_as_unauthenticated(client: TestClient, make_user: MakeUser) -> None:
    target = make_user(name="Kasun Perera")

    response = _edit(client, target.id, {"name": "Nobody"})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == UNAUTHORIZED
    assert "WWW-Authenticate" in response.headers
    # And the clearance half of it. A 401 that leaves a stale cookie in place
    # sends the browser back with the same dead credential on the next request,
    # which is the loop `dependencies._unauthorized` carries the headers to
    # break — so the challenge alone is only half of what this row promises.
    assert SESSION_COOKIE_NAME in response.headers["set-cookie"]


# --- The response itself ------------------------------------------------------


def test_the_response_is_the_eleven_key_user_and_nothing_else(
    client: TestClient, administrator: Any, make_user: MakeUser
) -> None:
    target = make_user(name="Kasun Perera")

    body = _edit(client, target.id, {"name": "Kasun P."}).json()

    assert set(body) == set(User.model_fields)
    assert "password_hash" not in body


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ({"name": "Kasun P."}, 200),
        ({"email": "not-an-address"}, 422),
    ],
)
def test_every_answer_this_handler_produces_carries_no_store(
    client: TestClient, administrator: Any, make_user: MakeUser, body: Any, expected: int
) -> None:
    # Refusals included. This body names a member of staff, and a cached identity
    # served to the next person on a shared shop-floor tablet is the failure mode
    # `no-store` exists for.
    #
    # Scoped to what this *handler* answers. A body the request model refuses —
    # `{}`, an unknown field, a role the product does not have — never reaches
    # the handler at all and is rendered by `api.main.validation_error_handler`,
    # which carries no `no-store` on any endpoint in the product. That is a
    # pre-existing property of the generic 422 rather than something this route
    # does differently, and widening it is a change to the error contract that
    # belongs to whoever owns that handler, not to this story.
    target = make_user(name="Kasun Perera")

    response = _edit(client, target.id, body)

    assert response.status_code == expected
    assert response.headers["cache-control"] == "no-store"


def test_the_404_and_409_carry_no_store(
    client: TestClient, administrator: Any, make_user: MakeUser
) -> None:
    make_user(role=Role.STAFF, name="Kasun Perera")

    missing = client.patch(
        "/admin/users/d3a1f7b2-5c48-4e9a-8b60-1f2e3d4c5b6a", json={"name": "Nobody"}
    )
    floor = _edit(client, administrator.id, {"role": Role.STAFF.value})

    assert missing.status_code == 404
    assert missing.headers["cache-control"] == "no-store"
    assert floor.status_code == 409
    assert floor.headers["cache-control"] == "no-store"


# --- The statement itself -----------------------------------------------------


#: Both readers collapse runs of whitespace before comparing, for the reason
#: `test_user_list.py` gives at length: the guard is about *column drift*, not
#: about layout, and `RETURNING` and `SELECT` are different lengths so a
#: continuation line aligned under one cannot also be aligned under the other.
def _normalized(clause: str) -> str:
    """A column list with every run of whitespace collapsed to one space."""
    return " ".join(clause.split())


def _returning(statement: str) -> str:
    """The `RETURNING` clause of a statement, normalized."""
    head, separator, clause = statement.partition("RETURNING")
    assert separator, "the statement has no RETURNING clause"
    return _normalized(clause)


def _selected(statement: str) -> str:
    """The column list of a `SELECT`, normalized."""
    head, separator, rest = statement.partition("SELECT")
    assert separator, "the statement has no SELECT"
    columns, separator, _ = rest.partition("FROM")
    assert separator, "the statement has no FROM"
    return _normalized(columns)


def test_the_returned_columns_have_not_drifted_from_the_other_two_statements() -> None:
    # Parsed from the module's own source rather than retyped, so this cannot
    # pass by three lists being wrong in the same way. They are repeated in the
    # source rather than shared through a constant because
    # `test_source_guards.py` forbids a statement assembled from a value — this
    # is what holds them together instead.
    assert _returning(users._UPDATE_USER) == _returning(users._INSERT_USER)
    assert _returning(users._UPDATE_USER) == _selected(users._SELECT_USERS)


def test_the_returned_columns_name_exactly_the_contract() -> None:
    # Identical to the other two is worth nothing if all three are wrong. `User`
    # has no `password_hash` field, so a column added here that the contract does
    # not carry would fail `model_validate` at run time — this fails it at
    # collection time instead.
    columns = {column.strip() for column in _returning(users._UPDATE_USER).split(",")}

    assert columns == set(User.model_fields)


def test_the_write_sets_updated_at_by_hand() -> None:
    # DW-17: `users` carries no BEFORE UPDATE trigger, so nothing catches the
    # first writer that forgets. The behavioural test above can only see it on a
    # cluster where the two timestamps differ measurably; this one fails anywhere.
    assert "updated_at = now()" in _normalized(users._UPDATE_USER)


def test_the_write_folds_the_address_in_postgres() -> None:
    # `str.lower()` and Postgres's `lower()` are not guaranteed to agree on
    # non-ASCII input, and where they disagree the row fails its own
    # `CHECK (email = lower(email))` as an unexplained 500.
    assert "email = COALESCE(lower(%s::text), email)" in _normalized(users._UPDATE_USER)


def test_the_floor_is_a_predicate_inside_the_write() -> None:
    # Not a `SELECT count(*)` in Python. A count read a moment earlier is the
    # read-then-write AD-8 rejects for the throttle, and it fails the same way
    # here: two Administrators demoting each other each see the other and both
    # succeed.
    statement = _normalized(users._UPDATE_USER)

    assert "EXISTS" in statement
    assert "other.role = 'admin'" in statement
    assert "other.active" in statement


def test_a_concurrent_demotion_cannot_slip_past_the_floor(
    client: TestClient,
    conn: psycopg.Connection,
    migrated_url: str,
    administrator: Any,
    make_user: MakeUser,
) -> None:
    """Two Administrators demoting each other at the same instant. The real race.

    The other Administrator's demotion is driven over a second connection, using
    this module's own statements, and **held open** while the live route is asked
    to demote the remaining one. That is the only arrangement in which the two
    requests genuinely overlap, and it is what `_LOCK_ACTIVE_ADMINISTRATORS`
    exists for.

    The held transaction deliberately takes **only the target row's** lock, not
    the Administrator lock — it is standing in for a handler that had one and
    used it, and locking every Administrator row here would make the request
    below block whether or not the handler takes a lock of its own, which would
    make this test pass against the bug.

    Without the handler's lock the request never waits: `_UPDATE_USER`'s `EXISTS`
    reads the other Administrator's *pre-update* row under READ COMMITTED, finds
    them still an Administrator, and writes — leaving the product with nobody who
    can promote anybody. With it the request waits for the other transaction,
    re-evaluates against its committed result, and is refused.
    """
    second = make_user(role=Role.ADMIN, name="Nadeesha Silva")
    demoted = threading.Event()
    release = threading.Event()
    failure: list[BaseException] = []

    def demote_the_other() -> None:
        try:
            with psycopg.connect(migrated_url, autocommit=True, row_factory=dict_row) as other:
                with other.transaction():
                    other.execute(users._SELECT_USER_FOR_UPDATE, (second.id,))
                    row = other.execute(
                        users._UPDATE_USER,
                        (None, None, Role.STAFF.value, second.id, Role.STAFF.value),
                    ).fetchone()
                    assert row is not None, "the first demotion should be allowed: two exist"
                    demoted.set()
                    # Held until the request below has had time to reach the
                    # lock. Bounded, so a failure here is a failed assertion
                    # rather than a suite that never finishes.
                    release.wait(timeout=HELD_TRANSACTION_TIMEOUT)
        except BaseException as raised:  # pragma: no cover - reported below
            failure.append(raised)
            demoted.set()

    holder = threading.Thread(target=demote_the_other, daemon=True)
    holder.start()
    try:
        assert demoted.wait(timeout=HELD_TRANSACTION_TIMEOUT), "the held demotion never ran"
        assert failure == [], f"the held demotion failed: {failure}"

        # Released a moment after the request below starts, so the request is
        # genuinely waiting on the lock rather than arriving after the commit.
        #
        # The clock is read **before** the timer is armed, never after: the
        # assertion below compares the request's elapsed time against
        # `OVERLAP_SECONDS`, so a timer armed first would be counting from an
        # instant this measurement never saw and could fire fractionally early.
        # Reading first makes the elapsed window a superset of the held one,
        # which is the direction that cannot produce a false failure.
        started_at = time.monotonic()
        timer = threading.Timer(OVERLAP_SECONDS, release.set)
        timer.start()
        try:
            response = _edit(client, administrator.id, {"role": Role.STAFF.value})
        finally:
            timer.cancel()
        elapsed = time.monotonic() - started_at
    finally:
        release.set()
        holder.join(timeout=HELD_TRANSACTION_TIMEOUT)

    assert failure == [], f"the held demotion failed: {failure}"
    # **That it waited is half the claim, and the half a status code cannot
    # make.** A request that arrived after the holder had already committed
    # would be refused for the same `409` while proving nothing about the lock —
    # so this test would pass against a handler that takes none. The holder was
    # released `OVERLAP_SECONDS` after the request started, so a request that
    # returned sooner than that did not queue behind it.
    assert elapsed >= OVERLAP_SECONDS, (
        f"the request finished in {elapsed:.3f}s, sooner than the {OVERLAP_SECONDS}s the "
        "held transaction was kept open — it never waited on the Administrator lock"
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == LAST_ADMINISTRATOR
    assert _row(conn, administrator.id)["role"] == Role.ADMIN.value
    assert _row(conn, second.id)["role"] == Role.STAFF.value


def test_the_administrator_lock_is_ordered() -> None:
    # `ORDER BY id` is what keeps two concurrent demotions from deadlocking: both
    # lock the same rows, so they must lock them in the same order.
    statement = _normalized(users._LOCK_ACTIVE_ADMINISTRATORS)

    assert "ORDER BY id" in statement
    assert "FOR UPDATE" in statement


def test_the_locking_read_takes_the_row_lock() -> None:
    # Without `FOR UPDATE` the `UPDATE` below can be raced between the two
    # statements, and a row deleted in between reports as the Administrator
    # floor rather than as the `404` it is.
    assert "FOR UPDATE" in _normalized(users._SELECT_USER_FOR_UPDATE)
