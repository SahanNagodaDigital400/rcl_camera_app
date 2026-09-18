"""A rename carries the account's lockout counter with it — DW-59, decided here.

The counter is keyed on the submitted address (`api/throttle.py`), so before this
story an Administrator changing somebody's address left three things wrong at
once: the old string kept a live lock nobody could reach, the new address started
from zero, and `users.locked_until` reported a lock that corresponded to nothing.

Story 1.10 makes the decision DW-59 left open, and it is deliberately **carry,
not clear**. Clearing would fix the same three by making a rename an *unlock* —
a lock-evasion path an Administrator can walk, and an unlock this product does
not have (FR-5, DW-64, and no story in Epic 1 owns one). Every test here exists
to hold that direction: the lock must still be in force at the new address.

`login_attempts` is written only by `api/throttle.py` (AD-8,
`test_source_guards.py`), so the carry is a function *there* called from
`api/users.py`. These tests drive it through the live route, plant their state
through `conn` the way `test_login_throttling.py` does, and read the table back
directly — the table is the only thing that can say whether the run moved.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import psycopg
import pytest
from api import throttle, users
from api.main import create_app
from fastapi.testclient import TestClient
from shared_schema.user import Role

LOGIN = "/auth/login"

#: The address every rename in this file moves to. Written down once so a test
#: that plants a run against it and a test that renames onto it cannot drift.
NEW_ADDRESS = "kasun.perera@rocell.lk"

#: Two locks of visibly different length, for the merge cases. Both well inside
#: `ATTEMPT_WINDOW`, so neither run is stale while the other is live.
SHORT_LOCK = timedelta(minutes=5)
LONG_LOCK = timedelta(minutes=30)

MakeUser = Callable[..., Any]


def _sign_in(client: TestClient, account: Any) -> None:
    response = client.post(LOGIN, json={"email": account.email, "password": account.password})
    assert response.status_code == 200


@pytest.fixture
def administrator(client: TestClient, make_user: MakeUser) -> Any:
    account = make_user(role=Role.ADMIN, name="Ruwan Jayasuriya")
    _sign_in(client, account)
    return account


def _attempt_row(conn: psycopg.Connection, email: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM login_attempts WHERE email_key = %s", (email.strip().lower(),)
    ).fetchone()
    return None if row is None else dict(row)


def _plant(
    conn: psycopg.Connection,
    email_key: str,
    *,
    failures: int,
    locked_for: timedelta | None = None,
) -> None:
    """A run of failures, and optionally a live lock, against one address key.

    Written straight to the table rather than by failing sign-ins ten times: the
    progressive delay would make that a ten-second test, and what is under test
    here is what happens to the row, not how it got there.
    """
    conn.execute(
        """
        INSERT INTO login_attempts (email_key, failure_count, locked_until, last_failure_at)
        VALUES (%s, %s, CASE WHEN %s::interval IS NULL THEN NULL ELSE now() + %s END, now())
        """,
        (email_key, failures, locked_for, locked_for),
    )


def _users_locked_until(conn: psycopg.Connection, user_id: Any) -> Any:
    """FR-4's status column, as an Administrator's list renders it."""
    row = conn.execute("SELECT locked_until FROM users WHERE id = %s", (user_id,)).fetchone()
    assert row is not None
    return row["locked_until"]


def _rename(client: TestClient, user_id: Any, address: str) -> Any:
    return client.patch(f"/admin/users/{user_id}", json={"email": address})


def test_the_run_and_the_lock_move_to_the_new_address(
    client: TestClient, conn: psycopg.Connection, administrator: Any, make_user: MakeUser
) -> None:
    target = make_user(name="Kasun Perera")
    _plant(
        conn,
        target.email,
        failures=throttle.FAILURES_BEFORE_LOCKOUT,
        locked_for=throttle.LOCKOUT_DURATION,
    )
    old = _attempt_row(conn, target.email)
    assert old is not None

    assert _rename(client, target.id, NEW_ADDRESS).status_code == 200

    carried = _attempt_row(conn, NEW_ADDRESS)
    assert carried is not None
    assert carried["failure_count"] == old["failure_count"]
    assert carried["locked_until"] == old["locked_until"]
    assert carried["last_failure_at"] == old["last_failure_at"]


def test_the_old_key_is_gone(
    client: TestClient, conn: psycopg.Connection, administrator: Any, make_user: MakeUser
) -> None:
    # Left behind, the old string holds a lock nobody can reach and a row the
    # sweep cannot touch while the lock is live.
    target = make_user(name="Kasun Perera")
    _plant(conn, target.email, failures=4)

    assert _rename(client, target.id, NEW_ADDRESS).status_code == 200

    assert _attempt_row(conn, target.email) is None


def test_a_sign_in_at_the_new_address_is_still_refused_while_the_lock_holds(
    client: TestClient, conn: psycopg.Connection, administrator: Any, make_user: MakeUser
) -> None:
    # **The test this file exists for.** A rename must not be the unlock this
    # epic does not have: the correct password at the new address is refused
    # exactly as it was at the old one, because the lock followed the account.
    target = make_user(name="Kasun Perera")
    _plant(
        conn,
        target.email,
        failures=throttle.FAILURES_BEFORE_LOCKOUT,
        locked_for=throttle.LOCKOUT_DURATION,
    )

    assert _rename(client, target.id, NEW_ADDRESS).status_code == 200

    with TestClient(create_app(), base_url="https://testserver") as theirs:
        refused = theirs.post(LOGIN, json={"email": NEW_ADDRESS, "password": target.password})

    assert refused.status_code == 429
    assert refused.json()["error"]["code"] == "account_locked"


def test_two_runs_merge_and_the_stricter_state_survives(
    client: TestClient, conn: psycopg.Connection, administrator: Any, make_user: MakeUser
) -> None:
    # The new address was guessed at before it became anybody's login, so it
    # already carries a run of its own. `GREATEST` per column keeps whichever
    # side is stricter rather than whichever arrived second — here the longer
    # lock and the higher count are on different sides, so both halves are tested
    # at once.
    target = make_user(name="Kasun Perera")
    _plant(conn, target.email, failures=8, locked_for=SHORT_LOCK)
    _plant(conn, NEW_ADDRESS, failures=3, locked_for=LONG_LOCK)

    assert _rename(client, target.id, NEW_ADDRESS).status_code == 200

    merged = _attempt_row(conn, NEW_ADDRESS)
    assert merged is not None
    assert merged["failure_count"] == 8
    # The longer of the two locks, which was the one already at the new key.
    assert merged["locked_until"] > _now(conn) + (SHORT_LOCK + LONG_LOCK) / 2
    assert _attempt_row(conn, target.email) is None


def _now(conn: psycopg.Connection) -> Any:
    row = conn.execute("SELECT now() AS at").fetchone()
    assert row is not None
    return row["at"]


def test_a_live_lock_never_loses_to_no_lock(
    client: TestClient, conn: psycopg.Connection, administrator: Any, make_user: MakeUser
) -> None:
    # Postgres's `GREATEST` ignores NULLs, which is exactly the behaviour wanted
    # for `locked_until`: "no lock" must never win over a live one, in either
    # direction. Here the carried side has the lock and the destination has none.
    target = make_user(name="Kasun Perera")
    _plant(conn, target.email, failures=10, locked_for=throttle.LOCKOUT_DURATION)
    _plant(conn, NEW_ADDRESS, failures=1)

    assert _rename(client, target.id, NEW_ADDRESS).status_code == 200

    merged = _attempt_row(conn, NEW_ADDRESS)
    assert merged is not None
    assert merged["locked_until"] is not None


def test_a_rename_with_no_run_behind_it_writes_nothing(
    client: TestClient, conn: psycopg.Connection, administrator: Any, make_user: MakeUser
) -> None:
    # The common case: most accounts have never failed a sign-in, and the carry's
    # `INSERT ... SELECT` inserts nothing for them rather than a zeroed row the
    # sweep would then have to come back for.
    target = make_user(name="Kasun Perera")

    assert _rename(client, target.id, NEW_ADDRESS).status_code == 200

    assert _attempt_row(conn, NEW_ADDRESS) is None
    assert _attempt_row(conn, target.email) is None


def test_changing_only_the_name_leaves_the_counter_alone(
    client: TestClient, conn: psycopg.Connection, administrator: Any, make_user: MakeUser
) -> None:
    # The carry is guarded on the stored address actually changing. An edit that
    # touches only the name must not delete anybody's run — which is what an
    # unguarded `carry_failures(old, old)` followed by `_CLEAR_ATTEMPTS` would do.
    target = make_user(name="Kasun Perera")
    _plant(
        conn,
        target.email,
        failures=throttle.FAILURES_BEFORE_LOCKOUT,
        locked_for=throttle.LOCKOUT_DURATION,
    )
    before = _attempt_row(conn, target.email)

    assert client.patch(f"/admin/users/{target.id}", json={"name": "Kasun P."}).status_code == 200

    assert _attempt_row(conn, target.email) == before


def test_resending_the_same_address_in_another_case_leaves_the_counter_alone(
    client: TestClient, conn: psycopg.Connection, administrator: Any, make_user: MakeUser
) -> None:
    # The address is folded before it is compared, so `RUWAN@ROCELL.LK` and
    # `ruwan@rocell.lk` are the same stored value and the same counter key. An
    # unguarded carry here would clear the run — the rename as unlock, reached by
    # pressing Save with nothing changed but the shift key.
    target = make_user(name="Kasun Perera")
    _plant(
        conn,
        target.email,
        failures=throttle.FAILURES_BEFORE_LOCKOUT,
        locked_for=throttle.LOCKOUT_DURATION,
    )
    before = _attempt_row(conn, target.email)

    assert _rename(client, target.id, target.email.upper()).status_code == 200

    assert _attempt_row(conn, target.email) == before


def test_a_refused_rename_carries_nothing(
    client: TestClient, conn: psycopg.Connection, administrator: Any, make_user: MakeUser
) -> None:
    # The carry and the `UPDATE` are one transaction. A rename refused by the
    # unique index must leave the counter exactly where it was, or a failed edit
    # becomes the unlock a successful one deliberately is not.
    target = make_user(name="Kasun Perera")
    _plant(
        conn,
        target.email,
        failures=throttle.FAILURES_BEFORE_LOCKOUT,
        locked_for=throttle.LOCKOUT_DURATION,
    )
    before = _attempt_row(conn, target.email)

    refused = _rename(client, target.id, administrator.email)

    assert refused.status_code == 409
    assert _attempt_row(conn, target.email) == before
    assert _attempt_row(conn, administrator.email) is None


def test_the_account_keeps_the_mirror_it_already_had(
    client: TestClient, conn: psycopg.Connection, administrator: Any, make_user: MakeUser
) -> None:
    # The carry moves the run the account already owned, so the lock in force
    # afterwards is the one the mirror already reported — the rename changes the
    # key it lives under, not the deadline. Asserted as "unchanged" rather than
    # "untouched": the statement may rewrite the column, and what must not happen
    # is the value moving.
    target = make_user(name="Kasun Perera")
    _plant(
        conn,
        target.email,
        failures=throttle.FAILURES_BEFORE_LOCKOUT,
        locked_for=throttle.LOCKOUT_DURATION,
    )
    conn.execute(
        "UPDATE users SET locked_until = (SELECT locked_until FROM login_attempts "
        "WHERE email_key = %s) WHERE id = %s",
        (target.email, target.id),
    )
    before = _users_locked_until(conn, target.id)
    assert before is not None

    assert _rename(client, target.id, NEW_ADDRESS).status_code == 200

    assert _users_locked_until(conn, target.id) == before


def test_a_lock_that_was_only_on_the_destination_reaches_the_account(
    client: TestClient, conn: psycopg.Connection, administrator: Any, make_user: MakeUser
) -> None:
    # **The case the mirror was getting wrong.** The destination address was
    # guessed at while it belonged to nobody, so `_MIRROR_LOCK` matched zero rows
    # at the time and the account has never carried that lock. After the rename
    # the account *is* that address: `POST /auth/login` refuses it, so FR-4's one
    # status surface has to say so, or the enforcement and the report disagree.
    #
    # The old key deliberately has no run at all, which is also the branch where
    # `_CARRY_FAILURES` writes nothing — so nothing but an explicit read-back of
    # the destination can discover the lock.
    target = make_user(name="Kasun Perera")
    _plant(conn, NEW_ADDRESS, failures=throttle.FAILURES_BEFORE_LOCKOUT, locked_for=LONG_LOCK)
    assert _users_locked_until(conn, target.id) is None

    response = _rename(client, target.id, NEW_ADDRESS)
    assert response.status_code == 200

    enforced = _attempt_row(conn, NEW_ADDRESS)
    assert enforced is not None
    assert _users_locked_until(conn, target.id) == enforced["locked_until"]
    # And the body an Administrator reads says the same thing as the column.
    assert response.json()["locked_until"] is not None

    with TestClient(create_app(), base_url="https://testserver") as theirs:
        refused = theirs.post(LOGIN, json={"email": NEW_ADDRESS, "password": target.password})

    assert refused.status_code == 429
    assert refused.json()["error"]["code"] == "account_locked"


def test_the_merged_lock_the_destination_won_reaches_the_account(
    client: TestClient, conn: psycopg.Connection, administrator: Any, make_user: MakeUser
) -> None:
    # The same failure one step along: both keys carry a run, `GREATEST` keeps
    # the destination's longer expiry, and the account's mirror has only ever
    # held the shorter one it came with. The column must report what is enforced.
    target = make_user(name="Kasun Perera")
    _plant(conn, target.email, failures=throttle.FAILURES_BEFORE_LOCKOUT, locked_for=SHORT_LOCK)
    _plant(conn, NEW_ADDRESS, failures=2, locked_for=LONG_LOCK)
    conn.execute(
        "UPDATE users SET locked_until = (SELECT locked_until FROM login_attempts "
        "WHERE email_key = %s) WHERE id = %s",
        (target.email, target.id),
    )
    shorter = _users_locked_until(conn, target.id)
    assert shorter is not None

    assert _rename(client, target.id, NEW_ADDRESS).status_code == 200

    enforced = _attempt_row(conn, NEW_ADDRESS)
    assert enforced is not None
    assert enforced["locked_until"] > shorter, "the longer lock should have survived the merge"
    assert _users_locked_until(conn, target.id) == enforced["locked_until"]

    with TestClient(create_app(), base_url="https://testserver") as theirs:
        refused = theirs.post(LOGIN, json={"email": NEW_ADDRESS, "password": target.password})

    assert refused.status_code == 429


def test_a_lapsed_lock_is_never_mirrored_onto_the_account(
    client: TestClient, conn: psycopg.Connection, administrator: Any, make_user: MakeUser
) -> None:
    # The other direction, and the reason `_SELECT_LIVE_LOCK` compares against
    # the database clock rather than checking for a non-null value: a past
    # `locked_until` is a lapsed lock that `attempt_state` already reads as a
    # fresh run, and copying it onto the account would report a lock nothing
    # enforces. The column is left exactly as it was — never cleared either.
    target = make_user(name="Kasun Perera")
    conn.execute(
        """
        INSERT INTO login_attempts (email_key, failure_count, locked_until, last_failure_at)
        VALUES (%s, 10, now() - %s, now())
        """,
        (target.email, timedelta(minutes=1)),
    )

    assert _rename(client, target.id, NEW_ADDRESS).status_code == 200

    assert _users_locked_until(conn, target.id) is None


def _age_the_run(conn: psycopg.Connection, email_key: str) -> None:
    """Push a planted run's last failure back past `ATTEMPT_WINDOW`.

    What makes a run *ended* rather than merely old, in `_RUN_ENDED`'s own terms.
    Written as an offset from the database clock, like every other time decision
    in `api/throttle.py`, so the test and the statement judge staleness against
    the same clock.
    """
    conn.execute(
        "UPDATE login_attempts SET last_failure_at = now() - %s WHERE email_key = %s",
        (throttle.ATTEMPT_WINDOW + timedelta(minutes=1), email_key),
    )


def test_an_ended_run_does_not_arm_the_live_one_it_merges_into(
    client: TestClient, conn: psycopg.Connection, administrator: Any, make_user: MakeUser
) -> None:
    """The merge must not build a run that neither address had.

    `GREATEST` per column takes the stricter *value*, which is not the stricter
    *state*: an old key whose run ended an hour ago still holds the count it
    ended with, and pairing that count with the destination's fresh
    `last_failure_at` yields a row the whole module reads as live. The account
    would then be one mistyped password from a lockout nobody earned, and this
    epic has no unlock to undo it with.
    """
    target = make_user(name="Kasun Perera")
    _plant(conn, target.email, failures=throttle.FAILURES_BEFORE_LOCKOUT - 1)
    _age_the_run(conn, target.email)
    _plant(conn, NEW_ADDRESS, failures=1)

    assert _rename(client, target.id, NEW_ADDRESS).status_code == 200

    carried = _attempt_row(conn, NEW_ADDRESS)
    assert carried is not None
    assert carried["failure_count"] == 1, "the ended run's count must not survive the merge"
    assert carried["locked_until"] is None
    # And the state the rest of the product reads agrees: the next failure is
    # number two of a run of one, not the one that trips the threshold.
    assert throttle.attempt_state(conn, NEW_ADDRESS).failure_count == 1


def test_a_live_run_survives_a_merge_with_an_ended_one(
    client: TestClient, conn: psycopg.Connection, administrator: Any, make_user: MakeUser
) -> None:
    """The same rule in the other direction, and the reason it is not a clear.

    The destination's own run ended — a stale count, and a lapsed lock that
    `attempt_state` already reads as no lock at all. Neither may erase what the
    account is actually carrying, and neither may pretend to be a live lock: what
    comes out is the account's live run, unchanged.
    """
    target = make_user(name="Kasun Perera")
    _plant(conn, target.email, failures=3)
    conn.execute(
        """
        INSERT INTO login_attempts (email_key, failure_count, locked_until, last_failure_at)
        VALUES (%s, 10, now() - %s, now())
        """,
        (NEW_ADDRESS, timedelta(minutes=1)),
    )

    assert _rename(client, target.id, NEW_ADDRESS).status_code == 200

    carried = _attempt_row(conn, NEW_ADDRESS)
    assert carried is not None
    assert carried["failure_count"] == 3, "the account's live run is what moved"
    assert carried["locked_until"] is None, "a lapsed lock is not a lock to merge"
    assert throttle.attempt_state(conn, NEW_ADDRESS).failure_count == 3
    assert _users_locked_until(conn, target.id) is None


def _backdate(conn: psycopg.Connection, email_key: str, ago: timedelta) -> None:
    """Move a planted run's last failure back by `ago`, against the server clock.

    `_age_the_run`'s finer-grained sibling: that one pushes a run clear of
    `ATTEMPT_WINDOW`, this one places it at a chosen point *inside* the window,
    which is what the two tests below need in order to tell one run's clock from
    the other's.
    """
    conn.execute(
        "UPDATE login_attempts SET last_failure_at = now() - %s WHERE email_key = %s",
        (ago, email_key),
    )


def _last_failure_age(conn: psycopg.Connection, email_key: str) -> timedelta:
    """How long ago the row says its last failure was, by the database's clock.

    Asked as `now() - last_failure_at` in SQL rather than compared in Python, so
    the assertion never turns on this host's clock or on a timezone.
    """
    row = conn.execute(
        "SELECT now() - last_failure_at AS age FROM login_attempts WHERE email_key = %s",
        (email_key,),
    ).fetchone()
    assert row is not None
    return row["age"]


#: Where each run's last failure is placed inside `ATTEMPT_WINDOW` for the two
#: clock tests below. The live run is nearly out of window; the ended one failed
#: far more recently, which is exactly the pairing a raw `GREATEST` gets wrong.
LIVE_RUN_AGE = timedelta(minutes=55)
ENDED_RUN_AGE = timedelta(minutes=16)


def test_an_ended_runs_clock_does_not_extend_the_live_run_it_merges_with(
    client: TestClient, conn: psycopg.Connection, administrator: Any, make_user: MakeUser
) -> None:
    """The third column of the merge, and the one that decides how long a run lives.

    `last_failure_at` is what `_RUN_ENDED` reads, so taking the later of the two
    timestamps is the same fabrication the count normalisation exists to
    prevent, by another route: a lock that lapsed a minute ago failed far more
    recently than a live run near the end of its window, and handing that live
    run the fresher clock gives it another `ATTEMPT_WINDOW` it never earned —
    one more mistyped password inside it, and the account is locked with no
    unlock anywhere in this epic.

    Here the *destination* is the ended one, which is `_RUN_ENDED`'s arm of the
    expression.
    """
    target = make_user(name="Kasun Perera")
    _plant(conn, target.email, failures=3)
    _backdate(conn, target.email, LIVE_RUN_AGE)
    _plant(conn, NEW_ADDRESS, failures=throttle.FAILURES_BEFORE_LOCKOUT)
    conn.execute(
        "UPDATE login_attempts SET locked_until = now() - %s WHERE email_key = %s",
        (timedelta(minutes=1), NEW_ADDRESS),
    )
    _backdate(conn, NEW_ADDRESS, ENDED_RUN_AGE)

    assert _rename(client, target.id, NEW_ADDRESS).status_code == 200

    carried = _attempt_row(conn, NEW_ADDRESS)
    assert carried is not None
    assert carried["failure_count"] == 3, "the account's live run is what moved"
    assert carried["locked_until"] is None
    age = _last_failure_age(conn, NEW_ADDRESS)
    assert age > ENDED_RUN_AGE + timedelta(minutes=5), (
        "the merged row kept the ended run's clock, so the live run's window was "
        "restarted on failures it did not make"
    )
    assert LIVE_RUN_AGE - timedelta(minutes=5) < age < LIVE_RUN_AGE + timedelta(minutes=5)


def test_the_incoming_ended_runs_clock_does_not_extend_the_one_it_merges_into(
    client: TestClient, conn: psycopg.Connection, administrator: Any, make_user: MakeUser
) -> None:
    """The same rule asked of `EXCLUDED`, so both arms are load-bearing.

    An account carrying a lockout that lapsed a minute ago is renamed onto an
    address with a live run near the end of its own window. The account's ended
    run may no more restart that window than the other direction may.
    """
    target = make_user(name="Kasun Perera")
    _plant(conn, target.email, failures=throttle.FAILURES_BEFORE_LOCKOUT)
    conn.execute(
        "UPDATE login_attempts SET locked_until = now() - %s WHERE email_key = %s",
        (timedelta(minutes=1), target.email),
    )
    _backdate(conn, target.email, ENDED_RUN_AGE)
    _plant(conn, NEW_ADDRESS, failures=3)
    _backdate(conn, NEW_ADDRESS, LIVE_RUN_AGE)

    assert _rename(client, target.id, NEW_ADDRESS).status_code == 200

    carried = _attempt_row(conn, NEW_ADDRESS)
    assert carried is not None
    assert carried["failure_count"] == 3, "the destination's live run is what survived"
    assert carried["locked_until"] is None
    age = _last_failure_age(conn, NEW_ADDRESS)
    assert age > ENDED_RUN_AGE + timedelta(minutes=5), (
        "the carried run's ended clock restarted a window it had no failures in"
    )
    assert LIVE_RUN_AGE - timedelta(minutes=5) < age < LIVE_RUN_AGE + timedelta(minutes=5)


def test_the_carrys_old_key_is_folded_rather_than_taken_from_the_column() -> None:
    """The fold rule, pinned without asking the test cluster's collation for help.

    `test_the_run_is_found_under_the_key_sign_in_actually_uses` below proves this
    against a genuinely divergent address — but only where the cluster's
    `lower()` and Python's actually disagree, and it skips where they do not.
    Which one the suite gets is a property of the machine it runs on
    (`conftest.py` runs `initdb` with no `--locale`), so on a cluster that folds
    like Python the single assertion protecting DW-59's closure does not execute
    at all: `old_key = current["email"]` would ship green, the carry would match
    zero rows, and the run would stay on the address sign-in actually uses.

    This one always executes. It reads the assignment out of `api/users.py` and
    holds it to the shape rather than to a value, so it stays true through a
    rename of the variable it reads and fails the moment the fold is dropped.
    """
    source = (Path(users.__file__)).read_text(encoding="utf-8")
    assignments = [
        line.strip() for line in source.splitlines() if line.strip().startswith("old_key =")
    ]

    assert len(assignments) == 1, f"expected one `old_key` assignment, found {assignments}"
    assignment = assignments[0]
    assert ".lower()" in assignment, (
        f"`{assignment}` hands the carry the stored column. `users.email` is *Postgres's* "
        "fold and `api.auth.login` keys `login_attempts` on Python's, so on an address "
        "where the two disagree this names a key with no row — DW-59, reproduced by the "
        "code written to close it."
    )


#: Characters whose two case folds are allowed to disagree, most-likely first.
#:
#: What is wanted is narrower than "the folds differ": the *stored* value has to
#: be a fixed point of Postgres's `lower()` — or it could not satisfy the
#: column's own `CHECK (email = lower(email))` — while **not** being a fixed
#: point of Python's. The Unicode titlecase digraphs are exactly that shape:
#: `ǅ` (U+01C5) is unchanged by `lower()` under a `C.UTF-8` collation and becomes
#: `ǆ` (U+01C6) under `str.lower()`.
#:
#: `İ` (U+0130) is the example `_INSERT_USER`'s own comment cites and is kept
#: here as a probe, though it usually fails this narrower test: Postgres folds it
#: to a plain `i`, which Python then leaves alone. Which of these actually
#: diverges depends on the collation the test cluster was initialised with, so
#: the list is a set of chances and `_divergent_local_part` asks the database
#: which one — if any — pays off.
FOLD_PROBES = ("\u01c5", "\u01c8", "\u01cb", "\u01f2", "\u0130", "\u1e9e")


def _divergent_local_part(conn: psycopg.Connection) -> str | None:
    """A local part this cluster folds differently from Python, or `None`.

    Asked of the database rather than assumed: `conftest` runs `initdb` with no
    `--locale`, so the collation — and with it whether `lower()` touches
    non-ASCII at all — is whatever the machine running the suite provides.
    """
    for probe in FOLD_PROBES:
        row = conn.execute("SELECT lower(%s) AS folded", (probe,)).fetchone()
        assert row is not None
        folded: str = row["folded"]
        if folded.lower() != folded:
            return folded
    return None


def test_the_run_is_found_under_the_key_sign_in_actually_uses(
    client: TestClient, conn: psycopg.Connection, administrator: Any, make_user: MakeUser
) -> None:
    """The carry's old key is the *Python* fold of the stored address, not the column.

    `api.auth.login` keys `login_attempts` on `payload.email.strip().lower()` —
    Python's fold of what was typed — while `users.email` holds **Postgres's**
    fold of the same string, because `_INSERT_USER` writes `lower(%s)` to keep
    the column's own `CHECK (email = lower(email))` unfailable. The two are not
    guaranteed to agree on non-ASCII input.

    Where they disagree, handing the raw column to the carry names a key that has
    no row: the delete removes nothing, the run stays on the address sign-in
    actually uses, and DW-59 is reproduced by the code written to close it. Every
    other test in this file is ASCII, where the two folds agree and the mistake
    is invisible.
    """
    local = _divergent_local_part(conn)
    if local is None:
        pytest.skip(
            "this cluster's lower() agrees with Python's on every probe, so there is no "
            "fold divergence here to exercise"
        )

    target = make_user(name="Kasun Perera")
    # Stored exactly as `_INSERT_USER` would store it — Postgres's fold, which
    # satisfies the column's own CHECK — and deliberately not Python's.
    stored = f"{local}@rocell.lk"
    conn.execute("UPDATE users SET email = %s WHERE id = %s", (stored, target.id))
    assert stored.lower() != stored, "the probe stopped diverging between the two folds"

    # The key a sign-in at that address creates, which is where the run lives.
    _plant(
        conn,
        stored.lower(),
        failures=throttle.FAILURES_BEFORE_LOCKOUT,
        locked_for=throttle.LOCKOUT_DURATION,
    )

    assert _rename(client, target.id, NEW_ADDRESS).status_code == 200

    carried = _attempt_row(conn, NEW_ADDRESS)
    assert carried is not None, "the run was not found under the key sign-in uses"
    assert carried["failure_count"] == throttle.FAILURES_BEFORE_LOCKOUT
    assert _attempt_row(conn, stored.lower()) is None
    # And the lock reached the account, as it does on the ASCII path.
    assert _users_locked_until(conn, target.id) == carried["locked_until"]


def test_the_carry_is_a_no_op_when_the_key_does_not_change() -> None:
    # The unit, so the guard is stated where it lives rather than only observed
    # through the route. `carry_failures` is called with a connection it must not
    # touch, so a statement issued here would raise rather than pass quietly.
    class Refuses:
        def execute(self, *args: object, **kwargs: object) -> None:
            raise AssertionError("carry_failures issued a statement for an unchanged key")

    carried = throttle.carry_failures(
        Refuses(),  # type: ignore[arg-type]
        "ruwan@rocell.lk",
        "ruwan@rocell.lk",
        uuid4(),
    )

    assert carried is None
