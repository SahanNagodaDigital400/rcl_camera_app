"""`POST /admin/users/{id}/deactivate` and `.../activate` — FR-13's two state verbs.

The authorization *guard* lives in `test_admin_authorization.py`, which holds the
role check to the route table in both directions — it covers these routes without
having been taught about them, which is the property it was written for — and
which also carries the live Staff refusal against both paths. The forced-change
gate is inherited through `require_administrator` and needs no allowlist entry in
`test_forced_change_gate.py`; the one test here proves it rather than leaving the
next reader to check.

This file is about the write, and about the clause that is not this story's code
at all. **A session valid a moment before the deactivation is refused on the very
next request** — AD-3's one session lookup already joins `AND u.active`, so that
half is *proved* here rather than built. It is proved the only way that means
anything: one signed-in target, one cookie, a request before and a request after,
with no sign-out in between. The other half — that the rows are *gone* and not
merely ignored — is asserted separately and deliberately, because the two fail
apart: delete the sweep and the `401` still passes while a later reactivation
hands the session back.

The delete verb is `test_delete_user.py`.
"""

from __future__ import annotations

import inspect
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
from api.users import LAST_ACTIVE_ADMINISTRATOR, LAST_ADMINISTRATOR, NO_SUCH_USER, USER_NOT_FOUND
from fastapi.testclient import TestClient
from psycopg.rows import dict_row
from shared_schema.user import Role, User

LOGIN = "/auth/login"
SESSION = "/auth/session"

MakeUser = Callable[..., Any]

#: How long the concurrency test below will wait for the transaction it holds
#: open, before failing rather than hanging the suite. `test_edit_user.py`'s
#: bounds, for the same test shape and the same reason.
HELD_TRANSACTION_TIMEOUT = 10.0

#: How long that transaction stays open once the live request has started. Long
#: enough that the request is genuinely waiting on the lock; short enough that
#: this is a second of one test rather than a habit.
OVERLAP_SECONDS = 1.0


def _deactivate_path(user_id: Any) -> str:
    return f"/admin/users/{user_id}/deactivate"


def _activate_path(user_id: Any) -> str:
    return f"/admin/users/{user_id}/activate"


def _sign_in(client: TestClient, account: Any) -> None:
    response = client.post(LOGIN, json={"email": account.email, "password": account.password})
    assert response.status_code == 200


@pytest.fixture
def their_client(client: TestClient) -> Any:
    """A second client, on the same database, for the *target* of a deactivation.

    Its own app instance rather than a second `TestClient` over `client`'s: the
    lifespan builds the connection pool and tears it down, so a nested client
    over one app would close the pool the outer one is still using. `client`'s
    fixture has already pointed `DATABASE_URL` at this test's database, and
    `create_app()` reads it at startup.

    A separate cookie jar is the whole point — this is the person whose access is
    being taken away under them, holding the cookie they already had.
    """

    def factory() -> Any:
        return TestClient(create_app(), base_url="https://testserver")

    return factory


@pytest.fixture
def administrator(client: TestClient, make_user: MakeUser) -> Any:
    """A claimed Administrator, signed in on `client`."""
    account = make_user(role=Role.ADMIN, name="Ruwan Jayasuriya")
    _sign_in(client, account)
    return account


def _row(conn: psycopg.Connection, user_id: Any) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM users WHERE id = %s", (user_id,)).fetchone()
    assert row is not None, f"{user_id} is not in the table"
    return dict(row)


def _session_count(conn: psycopg.Connection, user_id: Any) -> int:
    row = conn.execute(
        "SELECT count(*) AS total FROM sessions WHERE user_id = %s", (user_id,)
    ).fetchone()
    assert row is not None
    return int(row["total"])


# --- What the deactivation writes ---------------------------------------------


def test_deactivating_a_staff_user_answers_the_row_with_active_false(
    client: TestClient, conn: psycopg.Connection, administrator: Any, make_user: MakeUser
) -> None:
    target = make_user(role=Role.STAFF, name="Kasun Perera")

    response = client.post(_deactivate_path(target.id))

    assert response.status_code == 200
    assert response.json()["active"] is False
    assert response.json()["id"] == str(target.id)
    assert _row(conn, target.id)["active"] is False


def test_the_deactivation_moves_active_and_updated_at_and_nothing_else(
    client: TestClient, conn: psycopg.Connection, administrator: Any, make_user: MakeUser
) -> None:
    # Every other column, by comparison rather than by naming the ones that
    # matter: a deactivation that quietly cleared `must_change_password`, reset
    # `locked_until` or reissued a credential would pass an `active is False`
    # assertion and fail this one.
    target = make_user(role=Role.STAFF, must_change_password=True)
    before = _row(conn, target.id)

    assert client.post(_deactivate_path(target.id)).status_code == 200

    after = _row(conn, target.id)
    moved = {column for column, value in after.items() if before[column] != value}
    assert moved == {"active", "updated_at"}


def test_the_deactivation_takes_no_body_and_needs_none(
    client: TestClient, administrator: Any, make_user: MakeUser
) -> None:
    # No request model, so nothing to send and nothing to forbid. Stated as a
    # test because the alternative this story refused — `active` on
    # `EditUserRequest` — would have made the body the contract.
    target = make_user(role=Role.STAFF)

    assert client.post(_deactivate_path(target.id)).status_code == 200


@pytest.mark.parametrize("path", [_deactivate_path, _activate_path])
def test_a_body_sent_to_these_bodyless_routes_is_ignored(
    client: TestClient, conn: psycopg.Connection, administrator: Any, make_user: MakeUser, path: Any
) -> None:
    # **The design argument for three separate routes is that none of them
    # takes a body**, so none adds an `extra="forbid"` surface and none can be
    # sent `{"active": …}` and be believed. That claim is only half made by
    # never sending one — this is the other half, and it pins what the code
    # actually does rather than what a reader might assume.
    #
    # FastAPI builds no request model for a handler that declares no body
    # parameter, so the payload is never read and never validated: the answer
    # is the ordinary `200` and the verb does exactly what its route says. It
    # is deliberately **not** a `422`. Refusing it would mean inventing a
    # request model whose only job is to reject every shape, which is the
    # surface these routes exist without — and a caller who sends a body here
    # has misunderstood the route, not asked for something dangerous: there is
    # no field they could send that would change what the verb does. The role
    # in the body below is the proof of that: it is ignored, not applied.
    target = make_user(role=Role.STAFF, name="Kasun Perera")
    before = _row(conn, target.id)

    response = client.post(path(target.id), json={"role": Role.ADMIN.value, "name": "Somebody"})

    assert response.status_code == 200
    after = _row(conn, target.id)
    assert after["role"] == before["role"]
    assert after["name"] == before["name"]


def test_deactivating_an_already_deactivated_account_is_idempotent(
    client: TestClient, conn: psycopg.Connection, administrator: Any, make_user: MakeUser
) -> None:
    # `200` and not a `409`: the Administrator asked for the account to be off
    # and it is off. The `NOT active` arm of the floor predicate is what lets the
    # statement match a row that is already deactivated.
    target = make_user(role=Role.STAFF, active=False)

    response = client.post(_deactivate_path(target.id))

    assert response.status_code == 200
    assert response.json()["active"] is False
    assert _row(conn, target.id)["active"] is False


def test_a_second_deactivation_still_sweeps_a_stray_session(
    client: TestClient,
    conn: psycopg.Connection,
    administrator: Any,
    make_user: MakeUser,
    their_client: Any,
) -> None:
    # A row that survived an earlier failure is a live credential, and the second
    # press is exactly when somebody would notice. The account is deactivated
    # *after* it signs in, directly in the table, so the row is there to sweep.
    target = make_user(role=Role.STAFF)
    with their_client() as theirs:
        _sign_in(theirs, target)
    conn.execute("UPDATE users SET active = false WHERE id = %s", (target.id,))
    assert _session_count(conn, target.id) == 1

    assert client.post(_deactivate_path(target.id)).status_code == 200

    assert _session_count(conn, target.id) == 0


# --- FR-13's own clause: the live session ------------------------------------


def test_the_targets_very_next_request_is_refused(
    client: TestClient, administrator: Any, make_user: MakeUser, their_client: Any
) -> None:
    # The clause FR-13 states in as many words: "a session token valid before
    # deactivation is rejected on the very next request", not at the next
    # sign-in. One cookie, a request before and a request after, no sign-out in
    # between. `401` and not `403`: the session itself is no longer usable, so
    # there is no caller left to have a role.
    target = make_user(role=Role.STAFF)
    with their_client() as theirs:
        _sign_in(theirs, target)
        assert theirs.get(SESSION).status_code == 200

        assert client.post(_deactivate_path(target.id)).status_code == 200

        # The very next request, on the cookie they already held.
        refused = theirs.get(SESSION)
        assert refused.status_code == 401
        assert refused.json()["error"]["code"] == UNAUTHORIZED


def test_the_session_rows_are_deleted_and_not_merely_ignored(
    client: TestClient,
    conn: psycopg.Connection,
    administrator: Any,
    make_user: MakeUser,
    their_client: Any,
) -> None:
    # **Asserted separately from the `401` above, and that separation is the
    # point.** `_SELECT_SESSION`'s `AND u.active` makes the next request a `401`
    # whether or not the rows go, so a handler that forgot
    # `delete_sessions_for_user` would pass the test above untouched. What the
    # deletion buys is durability: without it a reactivation resurrects every
    # still-unexpired session the Administrator believed they had revoked.
    target = make_user(role=Role.STAFF)
    with their_client() as theirs:
        _sign_in(theirs, target)
        assert _session_count(conn, target.id) == 1

        assert client.post(_deactivate_path(target.id)).status_code == 200

        assert _session_count(conn, target.id) == 0


def test_a_reactivation_does_not_bring_the_old_session_back(
    client: TestClient, administrator: Any, make_user: MakeUser, their_client: Any
) -> None:
    # The reason the rows are deleted rather than left to `u.active`, driven end
    # to end: deactivate, reactivate, and the cookie that worked before is still
    # refused. With the sweep removed this is the test that fails.
    target = make_user(role=Role.STAFF)
    with their_client() as theirs:
        _sign_in(theirs, target)

        assert client.post(_deactivate_path(target.id)).status_code == 200
        assert client.post(_activate_path(target.id)).status_code == 200

        assert theirs.get(SESSION).status_code == 401


def test_only_the_targets_sessions_go(
    client: TestClient,
    conn: psycopg.Connection,
    administrator: Any,
    make_user: MakeUser,
    their_client: Any,
) -> None:
    # `_DELETE_USER_SESSIONS` is keyed on `user_id`, and a statement that lost
    # its `WHERE` would sign the whole product out while every assertion about
    # the target stayed green.
    target = make_user(role=Role.STAFF)
    bystander = make_user(role=Role.STAFF)
    with their_client() as theirs, their_client() as others:
        _sign_in(theirs, target)
        _sign_in(others, bystander)

        assert client.post(_deactivate_path(target.id)).status_code == 200

        assert _session_count(conn, bystander.id) == 1
        assert others.get(SESSION).status_code == 200


# --- The Administrator floor --------------------------------------------------


def test_deactivating_the_last_active_administrator_is_refused(
    client: TestClient, conn: psycopg.Connection, administrator: Any
) -> None:
    # The caller is the only active Administrator in the table, and the target is
    # themselves. `409`, never a `403`: nothing is wrong with their authority —
    # what refuses them is the product's own state.
    response = client.post(_deactivate_path(administrator.id))

    assert response.status_code == 409
    assert response.json()["error"] == {
        "code": LAST_ADMINISTRATOR,
        "message": LAST_ACTIVE_ADMINISTRATOR,
    }


def test_the_refusal_writes_nothing_at_all(
    client: TestClient,
    conn: psycopg.Connection,
    administrator: Any,
    make_user: MakeUser,
    their_client: Any,
) -> None:
    # Every column compared before and after, `updated_at` included, **and** the
    # session left alone: the refusal happens inside the transaction, so the
    # rollback is what makes "nothing was written" true rather than the handler
    # having been careful about the order it did things in.
    with their_client() as theirs:
        _sign_in(theirs, administrator)
        before = _row(conn, administrator.id)
        sessions_before = _session_count(conn, administrator.id)
        assert sessions_before > 0

        assert client.post(_deactivate_path(administrator.id)).status_code == 409

        assert _row(conn, administrator.id) == before
        assert _session_count(conn, administrator.id) == sessions_before
        assert theirs.get(SESSION).status_code == 200


def test_the_same_deactivation_succeeds_once_a_second_administrator_exists(
    client: TestClient, conn: psycopg.Connection, administrator: Any, make_user: MakeUser
) -> None:
    # **The floor is one survivor, not two.** epics.md's em-dash gloss reads
    # "at least two active Administrator accounts must always exist", which
    # taken literally would refuse this. FR-13 is the canonical wording and says
    # only "the last remaining active Administrator is refused", epics.md's own
    # worked example says the guard refuses "until a second Administrator is
    # created", and `users.py` has shipped "There must always be at least one
    # active Administrator" since Story 1.10. This test is where that reading
    # lives.
    make_user(role=Role.ADMIN, name="Nadeesha Silva")

    response = client.post(_deactivate_path(administrator.id))

    assert response.status_code == 200
    assert response.json()["active"] is False
    assert _row(conn, administrator.id)["active"] is False


def test_a_deactivated_administrator_does_not_hold_the_floor_up(
    client: TestClient, conn: psycopg.Connection, administrator: Any, make_user: MakeUser
) -> None:
    # The `other.active` arm of the predicate. A deactivated Administrator is not
    # one of the active Administrators the floor counts, so they cannot be the
    # survivor that lets the last active one be switched off.
    make_user(role=Role.ADMIN, active=False)

    assert client.post(_deactivate_path(administrator.id)).status_code == 409
    assert _row(conn, administrator.id)["active"] is True


def test_a_staff_target_is_never_refused_by_the_floor(
    client: TestClient, conn: psycopg.Connection, administrator: Any, make_user: MakeUser
) -> None:
    # The `role = 'staff'` arm: deactivating a Staff account cannot change how
    # many Administrators there are, so the floor has nothing to say about it
    # even when the caller is the only one left.
    target = make_user(role=Role.STAFF)

    assert client.post(_deactivate_path(target.id)).status_code == 200
    assert _row(conn, target.id)["active"] is False


def test_an_administrator_may_deactivate_their_own_row(
    client: TestClient, conn: psycopg.Connection, administrator: Any, make_user: MakeUser
) -> None:
    # There is nothing to protect them from: the row is theirs, the floor still
    # refuses the one that would leave nobody in charge, and an Administrator who
    # wants to close their own account should not need a colleague to do it. The
    # answer lands, and their own next request is the `401` they just created.
    make_user(role=Role.ADMIN, name="Nadeesha Silva")

    assert client.post(_deactivate_path(administrator.id)).status_code == 200

    assert client.get(SESSION).status_code == 401
    assert _row(conn, administrator.id)["active"] is False


# --- Reactivation -------------------------------------------------------------


def test_reactivating_answers_the_row_with_active_true(
    client: TestClient, conn: psycopg.Connection, administrator: Any, make_user: MakeUser
) -> None:
    target = make_user(role=Role.STAFF, active=False)

    response = client.post(_activate_path(target.id))

    assert response.status_code == 200
    assert response.json()["active"] is True
    assert _row(conn, target.id)["active"] is True


def test_the_reactivation_moves_active_and_updated_at_and_nothing_else(
    client: TestClient, conn: psycopg.Connection, administrator: Any, make_user: MakeUser
) -> None:
    # No credential is reissued and no password is set: `must_change_password`
    # and `temp_credential_expires_at` come back exactly as they went, so an
    # account that was claimed resumes claimed and one that never was resumes
    # with whatever is left of its 72 hours.
    target = make_user(role=Role.STAFF, active=False, must_change_password=True)
    before = _row(conn, target.id)

    assert client.post(_activate_path(target.id)).status_code == 200

    after = _row(conn, target.id)
    moved = {column for column, value in after.items() if before[column] != value}
    assert moved == {"active", "updated_at"}


def test_reactivating_restores_no_session(
    client: TestClient, conn: psycopg.Connection, administrator: Any, make_user: MakeUser
) -> None:
    target = make_user(role=Role.STAFF, active=False)

    assert client.post(_activate_path(target.id)).status_code == 200

    assert _session_count(conn, target.id) == 0


def test_the_reactivated_account_signs_in_again_with_the_password_it_had(
    client: TestClient, administrator: Any, make_user: MakeUser, their_client: Any
) -> None:
    # The whole of what a reactivation gives back: the flag. The credential was
    # never touched, so the person signs in with what they already had — and
    # they do have to sign in, because the session did not come back.
    target = make_user(role=Role.STAFF)
    with their_client() as theirs:
        _sign_in(theirs, target)

        assert client.post(_deactivate_path(target.id)).status_code == 200
        # EXPERIENCE.md's "Deactivated account login attempt" row: the same
        # generic rejection as a wrong password, never a statement that the
        # account exists or what state it is in.
        refused = theirs.post(LOGIN, json={"email": target.email, "password": target.password})
        assert refused.status_code == 401

        assert client.post(_activate_path(target.id)).status_code == 200

        _sign_in(theirs, target)
        assert theirs.get(SESSION).status_code == 200


def test_reactivating_an_active_account_is_idempotent(
    client: TestClient, conn: psycopg.Connection, administrator: Any, make_user: MakeUser
) -> None:
    target = make_user(role=Role.STAFF)

    response = client.post(_activate_path(target.id))

    assert response.status_code == 200
    assert response.json()["active"] is True
    assert _row(conn, target.id)["active"] is True


def test_reactivating_is_never_refused_by_the_floor(
    client: TestClient, conn: psycopg.Connection, administrator: Any, make_user: MakeUser
) -> None:
    # Raising the number of active Administrators can never reduce it, so
    # `_ACTIVATE_USER` carries no predicate at all — and this is the case a
    # copied predicate would wrongly refuse if it were written the way the other
    # two are, with the caller the only active Administrator in the table.
    target = make_user(role=Role.ADMIN, active=False)

    assert client.post(_activate_path(target.id)).status_code == 200
    assert _row(conn, target.id)["active"] is True


# --- The refusals every verb shares -------------------------------------------


@pytest.mark.parametrize("path", [_deactivate_path, _activate_path])
def test_an_unknown_id_is_a_404(client: TestClient, administrator: Any, path: Any) -> None:
    response = client.post(path("0f9c1d2e-3a4b-4c5d-8e6f-7a8b9c0d1e2f"))

    assert response.status_code == 404
    assert response.json()["error"] == {"code": USER_NOT_FOUND, "message": NO_SUCH_USER}


@pytest.mark.parametrize("path", [_deactivate_path, _activate_path])
def test_a_malformed_id_is_a_422_and_reads_no_row(
    client: TestClient, administrator: Any, path: Any
) -> None:
    # FastAPI refuses the path parameter before the handler is entered, so the
    # id never reaches a statement and the Administrator lock is never taken.
    response = client.post(path("not-a-uuid"))

    assert response.status_code == 422
    assert set(response.json()) == {"error"}


@pytest.mark.parametrize("path", [_deactivate_path, _activate_path])
def test_an_unclaimed_administrator_is_refused_by_the_gate(
    client: TestClient, make_user: MakeUser, path: Any
) -> None:
    # `require_administrator` chains on `require_claimed_user`, so an
    # Administrator still holding a temporary credential is refused by Story
    # 1.4's gate before the role is looked at — a note-borne credential cannot
    # take somebody else's access away. Proved here rather than left to
    # `test_forced_change_gate.py`'s allowlist, which gains nothing.
    caller = make_user(
        role=Role.ADMIN,
        must_change_password=True,
        temp_credential_expires_at=datetime.now(UTC) + timedelta(hours=72),
        name="Ruwan Jayasuriya",
    )
    target = make_user(role=Role.STAFF)
    _sign_in(client, caller)

    response = client.post(path(target.id))

    assert response.status_code == 403
    assert response.json()["error"]["code"] == PASSWORD_CHANGE_REQUIRED


@pytest.mark.parametrize("path", [_deactivate_path, _activate_path])
def test_no_session_is_refused_as_unauthenticated(
    client: TestClient, make_user: MakeUser, path: Any
) -> None:
    target = make_user(role=Role.STAFF)

    response = client.post(path(target.id))

    assert response.status_code == 401
    assert response.json()["error"]["code"] == UNAUTHORIZED


# --- The response shape -------------------------------------------------------


def test_the_response_is_the_eleven_key_user_and_nothing_else(
    client: TestClient, administrator: Any, make_user: MakeUser
) -> None:
    # `User` has no `password_hash` field, and a route that answered with a raw
    # row would leak one. Asserted against the contract rather than a written
    # list, so a field added to `shared_schema` fails here until this route is
    # looked at.
    target = make_user(role=Role.STAFF)

    body = client.post(_deactivate_path(target.id)).json()

    assert set(body) == set(User.model_fields)


def test_every_answer_these_handlers_produce_carries_no_store(
    client: TestClient, administrator: Any, make_user: MakeUser
) -> None:
    target = make_user(role=Role.STAFF)

    assert client.post(_deactivate_path(target.id)).headers["cache-control"] == "no-store"
    assert client.post(_activate_path(target.id)).headers["cache-control"] == "no-store"


def test_the_404_and_409_carry_no_store(client: TestClient, administrator: Any) -> None:
    missing = client.post(_deactivate_path("0f9c1d2e-3a4b-4c5d-8e6f-7a8b9c0d1e2f"))
    refused = client.post(_deactivate_path(administrator.id))

    assert missing.headers["cache-control"] == "no-store"
    assert refused.headers["cache-control"] == "no-store"


# --- The statements themselves ------------------------------------------------


def _normalized(clause: str) -> str:
    """A column list with every run of whitespace collapsed to one space."""
    return " ".join(clause.split())


def _returning(statement: str) -> str:
    """The `RETURNING` clause of a statement, normalized."""
    _head, separator, clause = statement.partition("RETURNING")
    assert separator, "the statement has no RETURNING clause"
    return _normalized(clause)


def test_the_returned_columns_have_not_drifted_from_the_other_statements() -> None:
    # Parsed from the module's own source rather than retyped, so this cannot
    # pass by the lists being wrong in the same way. They are repeated in the
    # source rather than shared through a constant because
    # `test_source_guards.py` forbids a statement assembled from a value — this
    # is what holds them together instead.
    assert _returning(users._DEACTIVATE_USER) == _returning(users._INSERT_USER)
    assert _returning(users._ACTIVATE_USER) == _returning(users._INSERT_USER)


def test_the_returned_columns_name_exactly_the_contract() -> None:
    for statement in (users._DEACTIVATE_USER, users._ACTIVATE_USER):
        columns = {column.strip() for column in _returning(statement).split(",")}

        assert columns == set(User.model_fields)


def test_both_writes_set_updated_at_by_hand() -> None:
    # DW-17: `users` carries no BEFORE UPDATE trigger — it names this story
    # explicitly — so nothing catches the first writer that forgets. The
    # behavioural tests above can only see it on a cluster where the two
    # timestamps differ measurably; this one fails anywhere.
    assert "updated_at = now()" in _normalized(users._DEACTIVATE_USER)
    assert "updated_at = now()" in _normalized(users._ACTIVATE_USER)


def test_the_floor_is_a_predicate_inside_the_deactivation() -> None:
    # Not a `SELECT count(*)` in Python. A count read a moment earlier is the
    # read-then-write AD-8 rejects for the throttle, and it fails the same way
    # here: two Administrators deactivating each other each see the other and
    # both succeed.
    statement = _normalized(users._DEACTIVATE_USER)

    assert "EXISTS" in statement
    assert "other.role = 'admin'" in statement
    assert "other.active" in statement


def test_the_deactivation_carries_story_1_10s_arms_verbatim() -> None:
    # One rule across demote, deactivate and delete. The three arms are lifted
    # from `_UPDATE_USER`, which Story 1.10 shipped, and a second copy that
    # drifted would refuse a different set of operations from the same code and
    # the same sentence.
    statement = _normalized(users._DEACTIVATE_USER)

    for arm in ("role = 'staff'", "NOT active", "other.id <> users.id"):
        assert arm in statement
        assert arm in _normalized(users._UPDATE_USER)


def test_the_deactivation_locks_the_administrator_set_before_it_reads_the_target() -> None:
    """The lock order the handler's own docstring calls load-bearing, pinned.

    `_LOCK_ACTIVE_ADMINISTRATORS` takes every active Administrator row in
    `ORDER BY id`; the target's own `FOR UPDATE` takes one row in whatever order
    the request happens to name. Taking the single row *first* is the lock-order
    inversion the `ORDER BY` exists to rule out — a demotion holding A and
    waiting for B against a deactivation holding B and waiting for A is a deadlock
    cycle, which Postgres breaks with `40P01` and the caller sees as a `500`
    rather than the `409` the floor is supposed to answer with.

    Asserted on the source rather than by racing two handlers, because the race
    only ever loses *sometimes*: the concurrency test in this module passes with
    the two statements swapped (the live request still blocks, on the other lock,
    and still answers `409`), so it cannot be the thing that holds the order.
    `edit_user` is checked alongside because the invariant is agreement between
    the handlers, not a property of any one of them.
    """
    for handler in (users.deactivate_user, users.edit_user):
        source = inspect.getsource(handler)
        # The calls, not the names: both statements are argued for by name in a
        # comment above the code that issues them, and matching the bare name
        # would compare the order of the prose instead.
        lock = source.index("conn.execute(_LOCK_ACTIVE_ADMINISTRATORS)")
        target = source.index("conn.execute(_SELECT_USER_FOR_UPDATE")
        assert lock < target, f"{handler.__name__} reads the target before it takes the lock"


def test_the_reactivation_carries_no_floor_at_all() -> None:
    # Deliberate, and the one statement in this story that is defined by what it
    # does not have. Raising the number of active Administrators cannot reduce
    # it, so a predicate here would be a guard that can never fire.
    statement = _normalized(users._ACTIVATE_USER)

    assert "EXISTS" not in statement
    assert statement.endswith(
        "RETURNING id, name, email, role, active, must_change_password, "
        "temp_credential_expires_at, last_login_at, locked_until, created_at, updated_at"
    )
    assert "WHERE id = %s" in statement


def test_a_concurrent_deactivation_cannot_slip_past_the_floor(
    client: TestClient,
    conn: psycopg.Connection,
    migrated_url: str,
    administrator: Any,
    make_user: MakeUser,
) -> None:
    """Two Administrators deactivating each other at the same instant. The real race.

    `test_edit_user.py`'s concurrent-demotion test, one verb over. The other
    Administrator's deactivation is driven over a second connection, using this
    module's own statements, and **held open** while the live route is asked to
    deactivate the remaining one. That is the only arrangement in which the two
    requests genuinely overlap, and it is what `_LOCK_ACTIVE_ADMINISTRATORS`
    exists for.

    The held transaction deliberately takes **only the target row's** lock, not
    the Administrator lock — it is standing in for a handler that had one and
    used it, and locking every Administrator row here would make the request
    below block whether or not the handler takes a lock of its own, which would
    make this test pass against the bug.

    Without the handler's lock the request never waits: `_DEACTIVATE_USER`'s
    `EXISTS` reads the other Administrator's *pre-update* row under READ
    COMMITTED, finds them still active, and writes — leaving the product with
    nobody who can sign in and promote anybody. With it the request waits for the
    other transaction, re-evaluates against its committed result, and is refused.
    """
    second = make_user(role=Role.ADMIN, name="Nadeesha Silva")
    deactivated = threading.Event()
    release = threading.Event()
    failure: list[BaseException] = []

    def deactivate_the_other() -> None:
        try:
            with psycopg.connect(migrated_url, autocommit=True, row_factory=dict_row) as other:
                with other.transaction():
                    other.execute(users._SELECT_USER_FOR_UPDATE, (second.id,))
                    row = other.execute(users._DEACTIVATE_USER, (second.id,)).fetchone()
                    assert row is not None, "the first deactivation should be allowed: two exist"
                    deactivated.set()
                    # Held until the request below has had time to reach the
                    # lock. Bounded, so a failure here is a failed assertion
                    # rather than a suite that never finishes.
                    release.wait(timeout=HELD_TRANSACTION_TIMEOUT)
        except BaseException as raised:  # pragma: no cover - reported below
            failure.append(raised)
            deactivated.set()

    holder = threading.Thread(target=deactivate_the_other, daemon=True)
    holder.start()
    try:
        assert deactivated.wait(timeout=HELD_TRANSACTION_TIMEOUT), "the held write never ran"
        assert failure == [], f"the held deactivation failed: {failure}"

        # Released a moment after the request below starts, so the request is
        # genuinely waiting on the lock rather than arriving after the commit.
        # The clock is read **before** the timer is armed, never after: the
        # assertion below compares the request's elapsed time against
        # `OVERLAP_SECONDS`, so a timer armed first would be counting from an
        # instant this measurement never saw and could fire fractionally early.
        started_at = time.monotonic()
        timer = threading.Timer(OVERLAP_SECONDS, release.set)
        timer.start()
        try:
            response = client.post(_deactivate_path(administrator.id))
        finally:
            timer.cancel()
        elapsed = time.monotonic() - started_at
    finally:
        release.set()
        holder.join(timeout=HELD_TRANSACTION_TIMEOUT)

    assert failure == [], f"the held deactivation failed: {failure}"
    # **That it waited is half the claim, and the half a status code cannot
    # make.** A request that arrived after the holder had already committed
    # would be refused for the same `409` while proving nothing about the lock —
    # so this test would pass against a handler that takes none.
    assert elapsed >= OVERLAP_SECONDS, (
        f"the request finished in {elapsed:.3f}s, sooner than the {OVERLAP_SECONDS}s the "
        "held transaction was kept open — it never waited on the Administrator lock"
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == LAST_ADMINISTRATOR
    assert _row(conn, administrator.id)["active"] is True
    assert _row(conn, second.id)["active"] is False
