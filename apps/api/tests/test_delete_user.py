"""`DELETE /admin/users/{user_id}` — FR-13's hard delete.

The authorization *guard* lives in `test_admin_authorization.py`, which holds the
role check to the route table in both directions and covers this route without
having been taught about it — that is the property it was written for — and which
also carries the live Staff refusal against this method. The forced-change gate
is inherited through `require_administrator` and needs no allowlist entry in
`test_forced_change_gate.py`; the one test here proves it rather than leaving the
next reader to check.

Three assertions here are the ones nothing else in the suite can make. **The
sessions go by cascade** — no application code deletes them on this path, so if
the `ON DELETE CASCADE` on `sessions.user_id` were ever dropped from a migration
nothing else would notice. **The address is freed**, which closes the delete half
of DW-79. And **the `login_attempts` row survives**, which is the difference
between a hard delete and an admin unlock nobody decided to build (DW-59/DW-91).

The two state verbs are `test_deactivate_user.py`.
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
from api.auth import ACCOUNT_LOCKED
from api.dependencies import PASSWORD_CHANGE_REQUIRED, UNAUTHORIZED
from api.main import create_app
from api.sessions import SESSION_COOKIE_NAME
from api.users import LAST_ACTIVE_ADMINISTRATOR, LAST_ADMINISTRATOR, NO_SUCH_USER, USER_NOT_FOUND
from fastapi.testclient import TestClient
from psycopg.rows import dict_row
from shared_schema.user import Role

CREATE_USER = "/admin/users"
LOGIN = "/auth/login"
SESSION = "/auth/session"

MakeUser = Callable[..., Any]

#: A lock long enough that it is unambiguously live when the assertion reads it.
LIVE_LOCK = timedelta(minutes=15)

#: How long the concurrency test below will wait for the transaction it holds
#: open, before failing rather than hanging the suite. `test_edit_user.py`'s
#: bounds, for the same test shape and the same reason.
HELD_TRANSACTION_TIMEOUT = 10.0

#: How long that transaction stays open once the live request has started. Long
#: enough that the request is genuinely waiting on the lock; short enough that
#: this is a second of one test rather than a habit.
OVERLAP_SECONDS = 1.0

#: The password a recreated account is provisioned with. A repeated character
#: rather than anything shaped like a credential (AGENTS.md Policy forbids a
#: committed credential in a fixture as firmly as in source); it is never signed
#: in with, only hashed and discarded with the test's database.
TEMPORARY_PASSWORD = "x" * 24


def _delete_path(user_id: Any) -> str:
    return f"/admin/users/{user_id}"


def _sign_in(client: TestClient, account: Any) -> None:
    response = client.post(LOGIN, json={"email": account.email, "password": account.password})
    assert response.status_code == 200


@pytest.fixture
def their_client(client: TestClient) -> Any:
    """A second client, on the same database, for the *target* of a delete.

    Its own app instance rather than a second `TestClient` over `client`'s: the
    lifespan builds the connection pool and tears it down, so a nested client
    over one app would close the pool the outer one is still using.

    A separate cookie jar is the whole point — this is the person whose account
    is being removed under them, holding the cookie they already had.
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


def _row(conn: psycopg.Connection, user_id: Any) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM users WHERE id = %s", (user_id,)).fetchone()
    return None if row is None else dict(row)


def _session_count(conn: psycopg.Connection, user_id: Any) -> int:
    row = conn.execute(
        "SELECT count(*) AS total FROM sessions WHERE user_id = %s", (user_id,)
    ).fetchone()
    assert row is not None
    return int(row["total"])


def _attempt_row(conn: psycopg.Connection, email: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM login_attempts WHERE email_key = %s", (email.strip().lower(),)
    ).fetchone()
    return None if row is None else dict(row)


def _plant_lock(conn: psycopg.Connection, email: str) -> None:
    """A run of failures and a live lock against one address.

    `test_edit_user_throttle_carry.py`'s `_plant`, written straight to the table
    rather than by failing sign-ins ten times: the progressive delay would make
    that a ten-second test, and what is under test here is what happens to the
    row, not how it got there.

    **The address is folded here, not left to the caller.** `api.auth.login`
    keys `login_attempts` on `payload.email.strip().lower()`, so a row planted
    verbatim is a row the product would never look up. It happens to work today
    because `make_user` generates lowercase addresses — which is exactly the
    kind of accident that makes a test pass for the wrong reason the first time
    somebody plants a mixed-case one. `_attempt_row` folds on read for the same
    reason.
    """
    conn.execute(
        """
        INSERT INTO login_attempts (email_key, failure_count, locked_until, last_failure_at)
        VALUES (%s, 10, now() + %s, now())
        """,
        (email.strip().lower(), LIVE_LOCK),
    )


# --- What the delete removes --------------------------------------------------


def test_the_row_is_gone_and_the_answer_is_an_empty_204(
    client: TestClient, conn: psycopg.Connection, administrator: Any, make_user: MakeUser
) -> None:
    # `204`, with no body: there is no row left to return, and answering with the
    # row that was deleted would be the product describing something that no
    # longer exists.
    target = make_user(role=Role.STAFF, name="Kasun Perera")

    response = client.delete(_delete_path(target.id))

    assert response.status_code == 204
    assert response.content == b""
    assert _row(conn, target.id) is None


def test_the_delete_carries_no_store(
    client: TestClient, administrator: Any, make_user: MakeUser
) -> None:
    target = make_user(role=Role.STAFF)

    assert client.delete(_delete_path(target.id)).headers["cache-control"] == "no-store"


def test_only_the_named_row_goes(
    client: TestClient, conn: psycopg.Connection, administrator: Any, make_user: MakeUser
) -> None:
    # A statement that lost its `WHERE` would empty the table while every
    # assertion about the target stayed green.
    target = make_user(role=Role.STAFF)
    bystander = make_user(role=Role.STAFF)

    assert client.delete(_delete_path(target.id)).status_code == 204

    assert _row(conn, bystander.id) is not None
    assert _row(conn, administrator.id) is not None


def test_the_targets_sessions_cascade_and_their_next_request_is_refused(
    client: TestClient,
    conn: psycopg.Connection,
    administrator: Any,
    make_user: MakeUser,
    their_client: Any,
) -> None:
    # **The cascade, not code.** `api.users.delete_user` calls nothing in
    # `api.sessions` — `ON DELETE CASCADE` on `sessions.user_id` is what ends
    # them, and the migration that wrote it says it is there for exactly this.
    # So this test is the only thing in the suite that would notice the
    # constraint being dropped.
    target = make_user(role=Role.STAFF)
    with their_client() as theirs:
        _sign_in(theirs, target)
        assert theirs.get(SESSION).status_code == 200
        assert _session_count(conn, target.id) == 1

        assert client.delete(_delete_path(target.id)).status_code == 204

        assert _session_count(conn, target.id) == 0
        # The very next request, on the cookie they already held.
        refused = theirs.get(SESSION)
        assert refused.status_code == 401
        assert refused.json()["error"]["code"] == UNAUTHORIZED


def test_the_address_is_freed_for_reuse(
    client: TestClient, conn: psycopg.Connection, administrator: Any, make_user: MakeUser
) -> None:
    # **DW-79's delete half.** The unique index is over `lower(users.email)`, so
    # once the row is gone the address can be provisioned again — a mistyped
    # address is no longer consumed forever. Driven through the live
    # provisioning route rather than by inspecting the index, because what
    # matters is that the Administrator can act on it.
    target = make_user(role=Role.STAFF, name="Kasun Perera")
    freed = target.email

    assert client.delete(_delete_path(target.id)).status_code == 204

    recreated = client.post(
        CREATE_USER,
        json={
            "name": "Kasun Perera",
            "email": freed,
            "role": Role.STAFF.value,
            "temporary_password": TEMPORARY_PASSWORD,
        },
    )

    assert recreated.status_code == 201
    assert recreated.json()["email"] == freed
    # A new row, not the old one resurrected.
    assert recreated.json()["id"] != str(target.id)


def test_the_lockout_row_survives_the_delete_with_its_lock_intact(
    client: TestClient, conn: psycopg.Connection, administrator: Any, make_user: MakeUser
) -> None:
    # **Deliberate, and the reason this route touches `api.throttle` not at all.**
    # `login_attempts` is keyed on the submitted address and is not a foreign key
    # to `users`, so the delete leaves it behind. Clearing it would make "delete
    # the account and recreate it" the admin unlock this product has decided not
    # to have — the same lock-evasion path Story 1.10 refused to open when it
    # carried a rename's run instead of clearing it (DW-59/DW-91, DW-64).
    target = make_user(role=Role.STAFF)
    _plant_lock(conn, target.email)
    before = _attempt_row(conn, target.email)
    assert before is not None

    assert client.delete(_delete_path(target.id)).status_code == 204

    after = _attempt_row(conn, target.email)
    assert after == before, "the delete moved the address's lockout counter"
    assert after is not None
    assert after["locked_until"] > datetime.now(UTC), "the lock should still be live"


def test_a_recreated_account_cannot_sign_in_under_the_lock_that_was_never_cleared(
    client: TestClient,
    conn: psycopg.Connection,
    administrator: Any,
    make_user: MakeUser,
    their_client: Any,
) -> None:
    # The consequence of the row above surviving, driven through the door
    # rather than read off the table: delete-and-recreate is not an unlock, so
    # the person holding the *correct* new credential is still refused at
    # `POST /auth/login` while the address's lock is live. Reading
    # `login_attempts` again would only restate the test above it.
    #
    # `users.locked_until` went with the deleted row — it is a mirror of the
    # counter, not the counter — so the fresh account reports no lock on the
    # Administrator's list while the counter goes on refusing. That asymmetry is
    # asserted too, because it is the one an operator would be surprised by.
    target = make_user(role=Role.STAFF)
    _plant_lock(conn, target.email)
    freed = target.email

    assert client.delete(_delete_path(target.id)).status_code == 204
    recreated = client.post(
        CREATE_USER,
        json={
            "name": "Kasun Perera",
            "email": freed,
            "role": Role.STAFF.value,
            "temporary_password": TEMPORARY_PASSWORD,
        },
    )
    assert recreated.status_code == 201
    assert recreated.json()["locked_until"] is None

    with their_client() as theirs:
        refused = theirs.post(LOGIN, json={"email": freed, "password": TEMPORARY_PASSWORD})
        signed_in = theirs.cookies.get(SESSION_COOKIE_NAME)

    # `429 account_locked`, which is FR-4's own answer: the credential is
    # correct and the *address* is what is refused.
    assert refused.status_code == 429, "the address's lock did not survive the delete"
    assert refused.json()["error"]["code"] == ACCOUNT_LOCKED
    assert signed_in is None


def test_a_body_sent_to_the_bodyless_delete_is_ignored(
    client: TestClient, conn: psycopg.Connection, administrator: Any, make_user: MakeUser
) -> None:
    # **The design argument for three separate routes is that none of them
    # takes a body**, so none of them adds an `extra="forbid"` surface and none
    # of them can be sent `{"active": false}` and be believed. That claim is
    # only half made by never sending one — this is the other half, and it
    # pins what the code actually does rather than what a reader might assume.
    #
    # FastAPI builds no request model for a handler that declares no body
    # parameter, so the payload is never read and never validated: the answer
    # is the ordinary `204` and the row is gone. It is deliberately **not** a
    # `422`. Refusing it would mean inventing a request model whose only job is
    # to reject every shape, which is the surface these routes exist without —
    # and a caller who sends a body here has misunderstood the route, not asked
    # for something dangerous: there is no field they could send that would
    # change what the verb does.
    target = make_user(role=Role.STAFF)

    response = client.request(
        "DELETE", _delete_path(target.id), json={"active": True, "role": Role.ADMIN.value}
    )

    assert response.status_code == 204
    assert _row(conn, target.id) is None


def test_deleting_a_deactivated_account_works(
    client: TestClient, conn: psycopg.Connection, administrator: Any, make_user: MakeUser
) -> None:
    target = make_user(role=Role.STAFF, active=False)

    assert client.delete(_delete_path(target.id)).status_code == 204
    assert _row(conn, target.id) is None


# --- The Administrator floor --------------------------------------------------


def test_deleting_the_last_active_administrator_is_refused(
    client: TestClient, conn: psycopg.Connection, administrator: Any
) -> None:
    # The identical rule, the identical code and the identical sentence as the
    # refused deactivation and the refused demotion. One rule across three verbs
    # is the whole point of reusing Story 1.10's predicate rather than writing a
    # second copy of it.
    response = client.delete(_delete_path(administrator.id))

    assert response.status_code == 409
    assert response.json()["error"] == {
        "code": LAST_ADMINISTRATOR,
        "message": LAST_ACTIVE_ADMINISTRATOR,
    }
    assert _row(conn, administrator.id) is not None


def test_the_refusal_leaves_the_row_and_its_sessions_untouched(
    client: TestClient,
    conn: psycopg.Connection,
    administrator: Any,
    their_client: Any,
) -> None:
    # Every column compared before and after, **and** the session left alone:
    # the refusal happens inside the transaction, so the rollback is what makes
    # "nothing was written" true rather than the handler having been careful
    # about the order it did things in.
    with their_client() as theirs:
        _sign_in(theirs, administrator)
        before = _row(conn, administrator.id)
        sessions_before = _session_count(conn, administrator.id)
        assert sessions_before > 0

        assert client.delete(_delete_path(administrator.id)).status_code == 409

        assert _row(conn, administrator.id) == before
        assert _session_count(conn, administrator.id) == sessions_before
        assert theirs.get(SESSION).status_code == 200


def test_the_same_delete_succeeds_once_a_second_administrator_exists(
    client: TestClient, conn: psycopg.Connection, administrator: Any, make_user: MakeUser
) -> None:
    # **The floor is one survivor, not two.** FR-13's canonical wording refuses
    # only "the last remaining active Administrator", and epics.md's own worked
    # example says the guard refuses "until a second Administrator is created".
    make_user(role=Role.ADMIN, name="Nadeesha Silva")

    assert client.delete(_delete_path(administrator.id)).status_code == 204
    assert _row(conn, administrator.id) is None


def test_a_deactivated_administrator_is_deleted_without_the_floor_objecting(
    client: TestClient, conn: psycopg.Connection, administrator: Any, make_user: MakeUser
) -> None:
    # The `NOT active` arm. A deactivated Administrator was never one of the
    # active Administrators the floor counts, so removing the row cannot take
    # the count to zero — even with the caller the only active one left.
    target = make_user(role=Role.ADMIN, active=False, name="Amal Perera")

    assert client.delete(_delete_path(target.id)).status_code == 204
    assert _row(conn, target.id) is None


def test_a_deactivated_administrator_does_not_hold_the_floor_up(
    client: TestClient, conn: psycopg.Connection, administrator: Any, make_user: MakeUser
) -> None:
    # The other side of the same arm: they cannot be the survivor either.
    make_user(role=Role.ADMIN, active=False)

    assert client.delete(_delete_path(administrator.id)).status_code == 409
    assert _row(conn, administrator.id) is not None


def test_a_staff_target_is_never_refused_by_the_floor(
    client: TestClient, conn: psycopg.Connection, administrator: Any, make_user: MakeUser
) -> None:
    target = make_user(role=Role.STAFF)

    assert client.delete(_delete_path(target.id)).status_code == 204
    assert _row(conn, target.id) is None


def test_an_administrator_may_delete_their_own_row(
    client: TestClient, conn: psycopg.Connection, administrator: Any, make_user: MakeUser
) -> None:
    # The same reasoning as a self-demotion and a self-deactivation: the row is
    # theirs, and the floor still refuses the one that would leave nobody in
    # charge. Their own next request is the `401` they just created.
    make_user(role=Role.ADMIN, name="Nadeesha Silva")

    assert client.delete(_delete_path(administrator.id)).status_code == 204

    assert client.get(SESSION).status_code == 401
    assert _row(conn, administrator.id) is None


# --- The refusals -------------------------------------------------------------


def test_an_unknown_id_is_a_404(client: TestClient, administrator: Any) -> None:
    response = client.delete(_delete_path("0f9c1d2e-3a4b-4c5d-8e6f-7a8b9c0d1e2f"))

    assert response.status_code == 404
    assert response.json()["error"] == {"code": USER_NOT_FOUND, "message": NO_SUCH_USER}
    assert response.headers["cache-control"] == "no-store"


def test_a_second_delete_of_the_same_id_is_a_404(
    client: TestClient, administrator: Any, make_user: MakeUser
) -> None:
    # Not idempotent in the "204 twice" sense, and deliberately so: a `404` is
    # what sends an Administrator acting on a stale list back to refetch it,
    # which is exactly the state they are in the second time.
    target = make_user(role=Role.STAFF)

    assert client.delete(_delete_path(target.id)).status_code == 204

    second = client.delete(_delete_path(target.id))
    assert second.status_code == 404
    assert second.json()["error"]["code"] == USER_NOT_FOUND


def test_a_malformed_id_is_a_422_and_reads_no_row(client: TestClient, administrator: Any) -> None:
    response = client.delete(_delete_path("not-a-uuid"))

    assert response.status_code == 422
    assert set(response.json()) == {"error"}


def test_an_unclaimed_administrator_is_refused_by_the_gate(
    client: TestClient, make_user: MakeUser
) -> None:
    # `require_administrator` chains on `require_claimed_user`, so a note-borne
    # temporary credential cannot be used to delete anybody.
    caller = make_user(
        role=Role.ADMIN,
        must_change_password=True,
        temp_credential_expires_at=datetime.now(UTC) + timedelta(hours=72),
        name="Ruwan Jayasuriya",
    )
    target = make_user(role=Role.STAFF)
    _sign_in(client, caller)

    response = client.delete(_delete_path(target.id))

    assert response.status_code == 403
    assert response.json()["error"]["code"] == PASSWORD_CHANGE_REQUIRED


def test_no_session_is_refused_as_unauthenticated(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser
) -> None:
    target = make_user(role=Role.STAFF)

    response = client.delete(_delete_path(target.id))

    assert response.status_code == 401
    assert response.json()["error"]["code"] == UNAUTHORIZED
    assert _row(conn, target.id) is not None


# --- The statement itself -----------------------------------------------------


def _normalized(statement: str) -> str:
    return " ".join(statement.split())


def test_the_delete_carries_the_same_floor_arms_as_the_other_two_verbs() -> None:
    # One rule across demote, deactivate and delete. A second copy that drifted
    # would refuse a different set of operations under the same code and the
    # same sentence.
    statement = _normalized(users._DELETE_USER)

    for arm in ("role = 'staff'", "NOT active", "other.id <> users.id"):
        assert arm in statement
        assert arm in _normalized(users._DEACTIVATE_USER)
        assert arm in _normalized(users._UPDATE_USER)


def test_the_delete_locks_the_administrator_set_before_it_reads_the_target() -> None:
    """The lock order the handler's own docstring calls load-bearing, pinned.

    `_LOCK_ACTIVE_ADMINISTRATORS` takes every active Administrator row in
    `ORDER BY id`; the target's own `FOR UPDATE` takes one row in whatever order
    the request happens to name. Taking the single row *first* is the lock-order
    inversion the `ORDER BY` exists to rule out — a demotion holding A and
    waiting for B against a delete holding B and waiting for A is a deadlock
    cycle, which Postgres breaks with `40P01` and the caller sees as a `500`
    rather than the `409` the floor is supposed to answer with.

    Asserted on the source rather than by racing two handlers, because the race
    only ever loses *sometimes*: the concurrency test in this module passes with
    the two statements swapped (the live request still blocks, on the other lock,
    and still answers `409`), so it cannot be the thing that holds the order.
    `edit_user` is checked alongside because the invariant is agreement between
    the handlers, not a property of any one of them.
    """
    for handler in (users.delete_user, users.edit_user):
        source = inspect.getsource(handler)
        # The calls, not the names: both statements are argued for by name in a
        # comment above the code that issues them, and matching the bare name
        # would compare the order of the prose instead.
        lock = source.index("conn.execute(_LOCK_ACTIVE_ADMINISTRATORS)")
        target = source.index("conn.execute(_SELECT_USER_FOR_UPDATE")
        assert lock < target, f"{handler.__name__} reads the target before it takes the lock"


def test_the_delete_returns_the_id_so_zero_rows_is_readable() -> None:
    # A bare `DELETE` reports a row count and nothing else, and zero would then
    # mean either "no such row" or "the floor refused" with no way to tell them
    # apart from inside the statement.
    assert _normalized(users._DELETE_USER).endswith("RETURNING id")


def test_a_concurrent_delete_cannot_slip_past_the_floor(
    client: TestClient,
    conn: psycopg.Connection,
    migrated_url: str,
    administrator: Any,
    make_user: MakeUser,
) -> None:
    """Two Administrators deleting each other at the same instant. The real race.

    `test_deactivate_user.py`'s concurrent-deactivation test, one verb over, and
    it is here because without it the `_LOCK_ACTIVE_ADMINISTRATORS` line in
    `delete_user` is load-bearing and unasserted: removing it leaves every other
    test in the API suite green while the floor stops being a floor.

    The race it prevents, stated as the two transactions: Tx1 locks
    Administrator A's row, evaluates `_DELETE_USER`'s `EXISTS` against a READ
    COMMITTED snapshot in which B is still an active Administrator, and deletes
    A. Tx2 locks B's row, evaluates the same `EXISTS` against a snapshot in
    which A is still active — Tx1 has not committed — and deletes B. Both
    commit, and the product has **zero** Administrators, which is the one state
    FR-13's floor exists to prevent and the one state nothing in the running
    application can recover from.

    The other Administrator's delete is driven over a second connection, using
    this module's own statements, and **held open** while the live route is
    asked to delete the remaining one. That is the only arrangement in which
    the two requests genuinely overlap.

    The held transaction deliberately takes **only the target row's** lock, not
    the Administrator lock — it is standing in for a handler that had one and
    used it, and locking every Administrator row here would make the request
    below block whether or not the handler takes a lock of its own, which would
    make this test pass against the bug.
    """
    second = make_user(role=Role.ADMIN, name="Nadeesha Silva")
    removed = threading.Event()
    release = threading.Event()
    failure: list[BaseException] = []

    def delete_the_other() -> None:
        try:
            with psycopg.connect(migrated_url, autocommit=True, row_factory=dict_row) as other:
                with other.transaction():
                    other.execute(users._SELECT_USER_FOR_UPDATE, (second.id,))
                    row = other.execute(users._DELETE_USER, (second.id,)).fetchone()
                    assert row is not None, "the first delete should be allowed: two exist"
                    removed.set()
                    # Held until the request below has had time to reach the
                    # lock. Bounded, so a failure here is a failed assertion
                    # rather than a suite that never finishes.
                    release.wait(timeout=HELD_TRANSACTION_TIMEOUT)
        except BaseException as raised:  # pragma: no cover - reported below
            failure.append(raised)
            removed.set()

    holder = threading.Thread(target=delete_the_other, daemon=True)
    holder.start()
    try:
        assert removed.wait(timeout=HELD_TRANSACTION_TIMEOUT), "the held delete never ran"
        assert failure == [], f"the held delete failed: {failure}"

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
            response = client.delete(_delete_path(administrator.id))
        finally:
            timer.cancel()
        elapsed = time.monotonic() - started_at
    finally:
        release.set()
        holder.join(timeout=HELD_TRANSACTION_TIMEOUT)

    assert failure == [], f"the held delete failed: {failure}"
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
    # The survivor, stated as the property the floor is for rather than as one
    # row's fate: whichever of the two won the race, somebody is left who can
    # sign in and administer the product.
    assert _row(conn, administrator.id) is not None
    assert _row(conn, second.id) is None
    survivors = conn.execute(
        "SELECT count(*) AS total FROM users WHERE role = 'admin' AND active"
    ).fetchone()
    assert survivors is not None
    assert survivors["total"] >= 1


def test_the_delete_touches_no_other_table() -> None:
    # `sessions` goes by cascade and `login_attempts` deliberately stays, so the
    # statement names `users` and nothing else. Read off the source because both
    # of those are absences, and an absence has nowhere else to be asserted.
    statement = _normalized(users._DELETE_USER)

    assert "sessions" not in statement
    assert "login_attempts" not in statement
