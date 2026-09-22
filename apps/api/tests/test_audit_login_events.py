"""Every entry `api.auth` writes — FR-20's login half, row by row.

The property this file is really about is the asymmetry the log exists to
create. `POST /auth/login` answers seven different situations with one
byte-identical `401`, on purpose: an unknown address, a wrong password, a
corrupt digest, a deactivated account, a lapsed temporary credential, a row
that vanished mid-request, and an address Postgres cannot hold at all. Six of
them go through `api.auth._count_and_refuse`; `malformed_address` is written
by `login` itself, because the counter's key *is* the string that cannot be
sent. The caller must not be able to tell any of them apart. The log must. So
most of the tests below drive one refusal and assert exactly one
`details.reason` — and `test_login.py` next door still asserts the responses
are indistinguishable, which is the other half of the same claim.

**Ordering within one request is not asserted, and cannot be.** `created_at`
defaults to `now()`, the transaction timestamp, so the two rows a password
write produces carry the same value to the microsecond and `id` is a random
tiebreaker. Where a request writes two entries the assertions are on the set of
actions and on each row found by its action, never on `rows[0]` and `rows[1]`.
Across requests the order is real and is used.

The audit entry on a failed sign-in is **not** an exception to the endpoint's
timing discipline: every input class now does the same amount of database work,
and the malformed-address path — which previously touched the database not at
all — does more than it used to rather than less.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest
from api import auth, throttle
from api.audit import TRUSTED_PROXY_HEADER, AuditAction
from api.auth import (
    CAUSE_CREDENTIAL_EXPIRED,
    CAUSE_PASSWORD_WRITTEN,
    REASON_ACCOUNT_VANISHED,
    REASON_CORRUPT_DIGEST,
    REASON_CREDENTIAL_EXPIRED,
    REASON_DEACTIVATED,
    REASON_MALFORMED_ADDRESS,
    REASON_UNKNOWN_ACCOUNT,
    REASON_WRONG_PASSWORD,
)
from api.sessions import SESSION_COOKIE_NAME
from fastapi.testclient import TestClient
from shared_schema.passwords import MIN_PASSWORD_LENGTH
from shared_schema.user import TEMP_CREDENTIAL_LIFETIME_HOURS, Role

LOGIN = "/auth/login"
LOGOUT = "/auth/logout"
CLAIM = "/auth/password"
SELF_CHANGE = "/auth/password/change"

WRONG_PASSWORD = "definitely-not-the-password"

#: What `conftest.client` presents as its peer, and therefore what every
#: `source_ip` in this file must be. Named rather than repeated as a literal:
#: it is asserted on one entry per handler, and eight copies of a string are
#: eight places to miss when the fixture changes.
PEER = "127.0.0.1"
REPLACEMENT = "r" * (MIN_PASSWORD_LENGTH + 8)
SECOND_REPLACEMENT = "s" * (MIN_PASSWORD_LENGTH + 8)

MakeUser = Callable[..., Any]
AuditRows = Callable[[psycopg.Connection], list[dict[str, Any]]]


@pytest.fixture(autouse=True)
def _no_trusted_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin `source_ip` to the peer for every test in this file.

    Every `source_ip` assertion below expects `PEER`. With
    `TRUSTED_PROXY_HEADER` exported — by a developer, or by a CI runner that
    sets it for an integration stage — `api.audit.source_ip` reads a header
    the test client never sends, every one of them records `NULL`, and the
    failure blames this story for the environment. `test_audit_source_ip.py`
    is where the configured-header behaviour is exercised on purpose.
    """
    monkeypatch.delenv(TRUSTED_PROXY_HEADER, raising=False)


@pytest.fixture
def instant(monkeypatch: pytest.MonkeyPatch) -> None:
    """The ladder's shape with none of its duration — `test_login_throttling`'s.

    Every rung becomes zero, so a ten-attempt run costs no wall clock while the
    thresholds and the lockout are untouched.
    """
    monkeypatch.setattr(throttle, "DELAY_STEP", timedelta(0))
    monkeypatch.setattr(throttle, "MAX_DELAY", timedelta(0))


def _sign_in(client: TestClient, email: str, password: str) -> Any:
    return client.post(LOGIN, json={"email": email, "password": password})


def _only(rows: list[dict[str, Any]], action: AuditAction) -> dict[str, Any]:
    """The one row carrying `action`, asserting there is exactly one."""
    matching = [row for row in rows if row["action"] == action]
    assert len(matching) == 1, f"expected exactly one {action}, found {len(matching)} in {rows}"
    return matching[0]


# --- A successful sign-in ------------------------------------------------------


def test_a_sign_in_writes_one_entry_naming_the_user_twice(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser, audit_rows: AuditRows
) -> None:
    account = make_user(name="Nadeesha Silva")

    assert _sign_in(client, account.email, account.password).status_code == 200

    rows = audit_rows(conn)
    assert [row["action"] for row in rows] == [AuditAction.LOGIN_SUCCEEDED]
    entry = rows[0]
    # Actor and target are the same person: a sign-in is somebody acting on
    # their own account, and both columns are filled so that "every entry
    # names who it was about" stays true for Story 1.13's read.
    assert entry["actor_user_id"] == account.id
    assert entry["actor_email"] == account.email
    assert entry["target_user_id"] == account.id
    assert entry["target_email"] == account.email
    assert entry["source_ip"] == PEER
    assert entry["details"] == {}
    assert entry["created_at"] is not None


def test_the_entry_is_written_in_the_same_transaction_as_the_session(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser, audit_rows: AuditRows
) -> None:
    # Not a timing assertion — the two rows exist together, which is what
    # "same unit of work" is observable as after the fact. A session with no
    # entry is the state FR-20 exists to prevent.
    account = make_user()
    assert _sign_in(client, account.email, account.password).status_code == 200

    sessions = conn.execute(
        "SELECT count(*) AS total FROM sessions WHERE user_id = %s", (account.id,)
    ).fetchone()
    assert sessions == {"total": 1}
    assert len(audit_rows(conn)) == 1


def test_a_flagged_sign_in_still_succeeds_and_carries_both_entries(
    client: TestClient,
    conn: psycopg.Connection,
    make_user: MakeUser,
    audit_rows: AuditRows,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Story 3.7 / FR-22: a flag never blocks the sign-in that produced it.

    `anomaly.check_and_flag` is forced `True` here rather than driven past a
    real deviation — `test_anomaly_flagging.py` already covers that module in
    isolation — so this test's own claim is narrow and behavioral: the real
    route, wired to a `True` result, still issues a session and writes both
    `LOGIN_SUCCEEDED` and `LOGIN_ANOMALY_FLAGGED` in the one transaction.
    """
    monkeypatch.setattr(auth.anomaly, "check_and_flag", lambda *_args, **_kwargs: True)
    account = make_user(name="Nadeesha Silva")

    response = _sign_in(client, account.email, account.password)

    assert response.status_code == 200
    assert response.cookies.get(SESSION_COOKIE_NAME) is not None

    rows = audit_rows(conn)
    assert {row["action"] for row in rows} == {
        AuditAction.LOGIN_SUCCEEDED,
        AuditAction.LOGIN_ANOMALY_FLAGGED,
    }
    flagged = _only(rows, AuditAction.LOGIN_ANOMALY_FLAGGED)
    assert flagged["actor_user_id"] == account.id
    assert flagged["actor_email"] == account.email
    assert flagged["target_user_id"] == account.id
    assert flagged["target_email"] == account.email
    assert flagged["source_ip"] == PEER


def test_a_failed_sign_in_never_reaches_the_anomaly_check(
    client: TestClient,
    conn: psycopg.Connection,
    make_user: MakeUser,
    audit_rows: AuditRows,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only a *successful* sign-in counts toward the login baseline (the
    module docstring's own rule) — a wrong password must never even ask.
    """

    def _fail_the_test(*_args: object, **_kwargs: object) -> bool:
        raise AssertionError("anomaly.check_and_flag must not run on a failed sign-in")

    monkeypatch.setattr(auth.anomaly, "check_and_flag", _fail_the_test)
    account = make_user()

    response = _sign_in(client, account.email, WRONG_PASSWORD)

    assert response.status_code == 401
    assert AuditAction.LOGIN_ANOMALY_FLAGGED not in {row["action"] for row in audit_rows(conn)}


def test_a_second_sign_in_writes_a_second_entry(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser, audit_rows: AuditRows
) -> None:
    # The log is append-only in the ordinary sense as well as the privileged
    # one: the second sign-in does not overwrite the first's record.
    account = make_user()
    assert _sign_in(client, account.email, account.password).status_code == 200
    assert _sign_in(client, account.email, account.password).status_code == 200

    assert [row["action"] for row in audit_rows(conn)] == [
        AuditAction.LOGIN_SUCCEEDED,
        AuditAction.LOGIN_SUCCEEDED,
    ]


# --- The seven refusals ---------------------------------------------------------
#
# Six of them below, one test each plus one that counts them. The seventh —
# `account_vanished` — needs the sign-in transaction to be made to fail, so it
# sits with the other staged-branch tests further down
# (`test_an_account_deleted_mid_sign_in_is_recorded`).


def test_an_unknown_address_is_recorded_with_no_actor(
    client: TestClient, conn: psycopg.Connection, audit_rows: AuditRows
) -> None:
    assert _sign_in(client, "nobody@rocell.lk", WRONG_PASSWORD).status_code == 401

    rows = audit_rows(conn)
    entry = _only(rows, AuditAction.LOGIN_FAILED)
    # No account, so no actor — and the submitted address is still recorded,
    # because it is the only thing that identifies the attempt. This is the
    # one place in the product where a guessed address is written down, and
    # it is the one place with AD-4's protections (`api.throttle` refuses to
    # put it in the application log for exactly that reason).
    assert entry["actor_user_id"] is None
    assert entry["actor_email"] is None
    assert entry["target_user_id"] is None
    assert entry["target_email"] == "nobody@rocell.lk"
    assert entry["details"] == {"reason": REASON_UNKNOWN_ACCOUNT}


def test_a_wrong_password_is_recorded_against_the_account(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser, audit_rows: AuditRows
) -> None:
    account = make_user()

    assert _sign_in(client, account.email, WRONG_PASSWORD).status_code == 401

    entry = _only(audit_rows(conn), AuditAction.LOGIN_FAILED)
    assert entry["actor_user_id"] == account.id
    assert entry["target_user_id"] == account.id
    assert entry["target_email"] == account.email
    assert entry["details"] == {"reason": REASON_WRONG_PASSWORD}
    assert entry["source_ip"] == PEER


def test_a_deactivated_account_is_recorded_as_such(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser, audit_rows: AuditRows
) -> None:
    # The caller is told nothing — same status, same code, same message, same
    # elapsed time as a wrong password. The log is where the difference lives.
    account = make_user(active=False)

    assert _sign_in(client, account.email, account.password).status_code == 401

    entry = _only(audit_rows(conn), AuditAction.LOGIN_FAILED)
    assert entry["actor_user_id"] == account.id
    assert entry["details"] == {"reason": REASON_DEACTIVATED}


def test_a_lapsed_temporary_credential_is_recorded_as_such(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser, audit_rows: AuditRows
) -> None:
    account = make_user(
        must_change_password=True,
        temp_credential_expires_at=datetime.now(UTC) - timedelta(hours=1),
    )

    assert _sign_in(client, account.email, account.password).status_code == 401

    entry = _only(audit_rows(conn), AuditAction.LOGIN_FAILED)
    assert entry["details"] == {"reason": REASON_CREDENTIAL_EXPIRED}


def test_a_corrupt_digest_is_recorded_as_such(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser, audit_rows: AuditRows
) -> None:
    # A data-integrity fault, answered as the one rejection like everything
    # else. Without its own reason it would be indistinguishable in the log
    # from an ordinary wrong password, and it is the only one of the six that
    # is a *bug* rather than a person.
    account = make_user()
    conn.execute("UPDATE users SET password_hash = %s WHERE id = %s", ("not-a-digest", account.id))

    assert _sign_in(client, account.email, account.password).status_code == 401

    entry = _only(audit_rows(conn), AuditAction.LOGIN_FAILED)
    assert entry["details"] == {"reason": REASON_CORRUPT_DIGEST}


def test_a_malformed_address_is_recorded_without_the_address(
    client: TestClient, conn: psycopg.Connection, audit_rows: AuditRows
) -> None:
    # A NUL byte cannot survive a Postgres `text` parameter — which is why the
    # counter cannot key on it either — so the entry carries the reason and no
    # address at all. Recorded nonetheless: "somebody is probing with
    # malformed input" is worth knowing, and silence is not.
    assert _sign_in(client, "someone\x00@rocell.lk", WRONG_PASSWORD).status_code == 401

    rows = audit_rows(conn)
    entry = _only(rows, AuditAction.LOGIN_FAILED)
    assert entry["target_email"] is None
    assert entry["actor_user_id"] is None
    assert entry["details"] == {"reason": REASON_MALFORMED_ADDRESS}
    # And nothing was counted, because there is no key to count it under.
    assert conn.execute("SELECT count(*) AS total FROM login_attempts").fetchone() == {"total": 0}


def test_every_refusal_writes_exactly_one_entry(
    client: TestClient,
    conn: psycopg.Connection,
    make_user: MakeUser,
    audit_rows: AuditRows,
    instant: None,
) -> None:
    # Six attempts, six rows, no double-counting anywhere: one refusal is one
    # event, and `_count_and_refuse` is the single funnel that makes that a
    # property of one function rather than of six call sites.
    #
    # `instant` because the sixth attempt is the first delayed one: without
    # it this test sleeps through a rung of the progressive ladder on every
    # run, for an assertion that has nothing to do with timing.
    account = make_user()
    for _ in range(6):
        assert _sign_in(client, account.email, WRONG_PASSWORD).status_code == 401

    rows = audit_rows(conn)
    assert len(rows) == 6
    assert {row["action"] for row in rows} == {AuditAction.LOGIN_FAILED}


# --- The lockout ---------------------------------------------------------------


def test_the_attempt_that_crosses_the_threshold_carries_the_lock(
    client: TestClient,
    conn: psycopg.Connection,
    make_user: MakeUser,
    audit_rows: AuditRows,
    instant: None,
) -> None:
    # DW-63: a lockout was unrecorded anywhere durable. It rides on the very
    # attempt that wrote it rather than on an entry of its own — that attempt
    # was refused for a reason, and the lock is a fact about it.
    account = make_user()
    for _ in range(throttle.FAILURES_BEFORE_LOCKOUT):
        _sign_in(client, account.email, WRONG_PASSWORD)

    rows = audit_rows(conn)
    assert len(rows) == throttle.FAILURES_BEFORE_LOCKOUT
    crossing = rows[-1]
    assert crossing["action"] == AuditAction.LOGIN_FAILED
    assert crossing["details"]["reason"] == REASON_WRONG_PASSWORD
    assert crossing["details"]["locked_until"] is not None
    # And no earlier attempt claims one.
    assert all("locked_until" not in row["details"] for row in rows[:-1])


def test_an_attempt_during_a_live_lockout_writes_its_own_action(
    client: TestClient,
    conn: psycopg.Connection,
    make_user: MakeUser,
    audit_rows: AuditRows,
    instant: None,
) -> None:
    # Not a seventh `login_failed` reason: nothing was verified and nothing
    # was counted, so calling it a failed sign-in would inflate the number an
    # operator reads this log to judge.
    account = make_user()
    for _ in range(throttle.FAILURES_BEFORE_LOCKOUT):
        _sign_in(client, account.email, WRONG_PASSWORD)

    before = len(audit_rows(conn))
    assert _sign_in(client, account.email, account.password).status_code == 429

    rows = audit_rows(conn)
    assert len(rows) == before + 1
    refusal = rows[-1]
    assert refusal["action"] == AuditAction.LOGIN_REFUSED_LOCKED
    assert refusal["target_email"] == account.email
    assert refusal["details"]["locked_until"] is not None


def test_a_lockout_refusal_still_writes_no_counter_row_change(
    client: TestClient,
    conn: psycopg.Connection,
    make_user: MakeUser,
    audit_rows: AuditRows,
    instant: None,
) -> None:
    # The refusal is free by design: one indexed lookup, no Argon2id, no
    # counter write. Adding the audit entry must not have changed that half.
    account = make_user()
    for _ in range(throttle.FAILURES_BEFORE_LOCKOUT):
        _sign_in(client, account.email, WRONG_PASSWORD)

    counter = conn.execute(
        "SELECT failure_count, locked_until FROM login_attempts WHERE email_key = %s",
        (account.email,),
    ).fetchone()

    assert _sign_in(client, account.email, WRONG_PASSWORD).status_code == 429

    assert (
        conn.execute(
            "SELECT failure_count, locked_until FROM login_attempts WHERE email_key = %s",
            (account.email,),
        ).fetchone()
        == counter
    )
    assert audit_rows(conn)[-1]["action"] == AuditAction.LOGIN_REFUSED_LOCKED


def test_the_locked_address_is_in_the_audit_row_though_never_in_the_application_log(
    client: TestClient,
    conn: psycopg.Connection,
    make_user: MakeUser,
    audit_rows: AuditRows,
    caplog: pytest.LogCaptureFixture,
    instant: None,
) -> None:
    # The sibling of `test_login_throttling.py`'s
    # `test_the_lock_is_logged_without_naming_the_address`. That assertion
    # stays exactly as it was; this one says where the address *does* go. Two
    # different files with two different protections is the whole argument.
    import logging

    account = make_user()
    with caplog.at_level(logging.INFO, logger="rocell.api.throttle"):
        for _ in range(throttle.FAILURES_BEFORE_LOCKOUT):
            _sign_in(client, account.email, WRONG_PASSWORD)

    records = [r for r in caplog.records if r.name == "rocell.api.throttle"]
    assert records
    assert all(account.email not in record.getMessage() for record in records)

    assert account.email in {row["target_email"] for row in audit_rows(conn)}


def test_an_account_deleted_mid_sign_in_is_recorded(
    client: TestClient,
    conn: psycopg.Connection,
    make_user: MakeUser,
    audit_rows: AuditRows,
    monkeypatch: pytest.MonkeyPatch,
    instant: None,
) -> None:
    """The `_SignInVanished` branch — the seventh reason, and the awkward one.

    The row is deleted between the credential read and `_RECORD_LOGIN`, so the
    write matches nothing after the password has already been verified. Its
    entry has to be written *after* the transaction has unwound, because one
    issued inside would be rolled back by the very `raise` that reports the
    failure — the same ordering `_SignInVanished` exists to force on the
    counter. This test is what pins that: move the `audit.record` call inside
    the block and the row disappears with the rollback.

    Staged the way `test_login_throttling.py` stages it, by making the write
    match no row, which is what a deletion looks like from inside the handler.
    """
    monkeypatch.setattr(
        auth,
        "_RECORD_LOGIN",
        auth._RECORD_LOGIN.replace("WHERE id = %s", "WHERE id = %s AND false"),
    )
    account = make_user()

    assert _sign_in(client, account.email, account.password).status_code == 401

    rows = audit_rows(conn)
    # One row, and it survived the rolled-back sign-in transaction.
    assert len(rows) == 1
    entry = _only(rows, AuditAction.LOGIN_FAILED)
    assert entry["details"] == {"reason": REASON_ACCOUNT_VANISHED}
    assert entry["actor_user_id"] == account.id
    assert entry["source_ip"] == PEER
    # No `login_succeeded`, although the password was correct and verified.
    assert AuditAction.LOGIN_SUCCEEDED not in {row["action"] for row in rows}


def test_a_refusal_is_recorded_even_when_the_counter_write_fails(
    client: TestClient,
    conn: psycopg.Connection,
    make_user: MakeUser,
    audit_rows: AuditRows,
    monkeypatch: pytest.MonkeyPatch,
    instant: None,
) -> None:
    # The branch where `record_failure` raised and `_count_and_refuse` carries
    # on with `state = None`. The two writes fail in opposite directions on
    # purpose: a counter fault must not turn a rejected credential into a 500
    # (that difference is the account-existence signal the endpoint removes),
    # while the entry is the record of record and is written regardless. Move
    # the `audit.record` call into the `else:` clause and this is the only
    # test that notices.
    def explode(*_: object, **__: object) -> None:
        raise psycopg.OperationalError("deadlock detected")

    monkeypatch.setattr(auth, "record_failure", explode)
    account = make_user()

    assert _sign_in(client, account.email, WRONG_PASSWORD).status_code == 401

    entry = _only(audit_rows(conn), AuditAction.LOGIN_FAILED)
    assert entry["details"] == {"reason": REASON_WRONG_PASSWORD}
    # No lock is claimed: nothing was counted, so there is no state to read
    # one from, and inventing a `locked_until` here would be the log
    # describing a lockout that does not exist.
    assert "locked_until" not in entry["details"]
    assert conn.execute("SELECT count(*) AS total FROM login_attempts").fetchone() == {"total": 0}


def test_a_lock_landing_during_the_delay_is_recorded_by_the_second_gate(
    client: TestClient,
    conn: psycopg.Connection,
    make_user: MakeUser,
    audit_rows: AuditRows,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The lockout gate *after* the sleep — the one `instant` can never reach.

    Every other lockout test here zeroes `DELAY_STEP`, so `if delay:` is false
    and the post-delay re-read never runs. Delete its `audit.record` call and
    nothing else in the suite notices, which makes this the only test holding
    the second gate in place.

    Modelled on `test_login_throttling.py`'s own race: a stub clock whose
    `sleep` writes the lock another request's tenth failure would have
    written, so the handler wakes to an address that was not locked when it
    read the counter and is locked now. Deliberately **no** `instant`
    fixture — the delay is the whole point.
    """
    account = make_user()
    for _ in range(throttle.FAILURES_BEFORE_DELAY):
        _sign_in(client, account.email, WRONG_PASSWORD)
    before = len(audit_rows(conn))

    class LockingClock:
        """A sleep another request's lockout lands in the middle of."""

        def __init__(self) -> None:
            self.slept: list[float] = []

        def sleep(self, seconds: float) -> None:
            self.slept.append(seconds)
            conn.execute(
                """
                UPDATE login_attempts
                   SET failure_count = %s,
                       locked_until = now() + %s,
                       last_failure_at = now()
                 WHERE email_key = %s
                """,
                (throttle.FAILURES_BEFORE_LOCKOUT, throttle.LOCKOUT_DURATION, account.email),
            )

    clock = LockingClock()
    monkeypatch.setattr(auth, "time", clock)

    # A *correct* password, so nothing but the second gate can produce a 429.
    assert _sign_in(client, account.email, account.password).status_code == 429
    assert clock.slept, "the handler did not sleep; this test reached the first gate instead"

    rows = audit_rows(conn)
    assert len(rows) == before + 1
    refusal = rows[-1]
    assert refusal["action"] == AuditAction.LOGIN_REFUSED_LOCKED
    assert refusal["target_email"] == account.email
    assert refusal["details"]["locked_until"] is not None
    assert refusal["source_ip"] == PEER
    # And no session was issued, although the credential was right.
    assert conn.execute(
        "SELECT count(*) AS total FROM sessions WHERE user_id = %s", (account.id,)
    ).fetchone() == {"total": 0}


# --- Signing out ----------------------------------------------------------------


def test_a_sign_out_writes_one_entry(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser, audit_rows: AuditRows
) -> None:
    account = make_user()
    assert _sign_in(client, account.email, account.password).status_code == 200

    assert client.post(LOGOUT).status_code == 204

    rows = audit_rows(conn)
    assert [row["action"] for row in rows] == [
        AuditAction.LOGIN_SUCCEEDED,
        AuditAction.LOGGED_OUT,
    ]
    entry = rows[-1]
    assert entry["actor_user_id"] == account.id
    assert entry["actor_email"] == account.email
    assert entry["source_ip"] == PEER


def test_a_sign_out_with_no_cookie_writes_nothing(
    client: TestClient, conn: psycopg.Connection, audit_rows: AuditRows
) -> None:
    # Nothing was revoked, so there is nothing to record. An entry here would
    # be the log describing an event that did not happen, which is a worse
    # defect than a missing one because nothing can tell it from a real one.
    assert client.post(LOGOUT).status_code == 204
    assert audit_rows(conn) == []


def test_a_sign_out_with_an_unknown_cookie_writes_nothing(
    client: TestClient, conn: psycopg.Connection, audit_rows: AuditRows
) -> None:
    client.cookies.set(SESSION_COOKIE_NAME, "not-a-token", domain="testserver")
    assert client.post(LOGOUT).status_code == 204
    assert audit_rows(conn) == []


def test_a_second_sign_out_writes_nothing_more(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser, audit_rows: AuditRows
) -> None:
    # `POST /auth/logout` is idempotent and the log has to be too: the second
    # call revokes nothing, so it records nothing.
    account = make_user()
    assert _sign_in(client, account.email, account.password).status_code == 200
    assert client.post(LOGOUT).status_code == 204

    before = len(audit_rows(conn))
    assert client.post(LOGOUT).status_code == 204
    assert len(audit_rows(conn)) == before


# --- Claiming a temporary credential --------------------------------------------


@pytest.fixture
def unclaimed(client: TestClient, make_user: MakeUser) -> Any:
    """An account still on its temporary credential, signed in on `client`."""
    account = make_user(
        must_change_password=True,
        temp_credential_expires_at=datetime.now(UTC)
        + timedelta(hours=TEMP_CREDENTIAL_LIFETIME_HOURS),
    )
    assert _sign_in(client, account.email, account.password).status_code == 200
    return account


def test_claiming_a_credential_writes_two_entries(
    client: TestClient, conn: psycopg.Connection, unclaimed: Any, audit_rows: AuditRows
) -> None:
    assert client.post(CLAIM, json={"new_password": REPLACEMENT}).status_code == 200

    rows = audit_rows(conn)
    # The sign-in that got here is the first row; the claim adds two.
    assert [row["action"] for row in rows[:1]] == [AuditAction.LOGIN_SUCCEEDED]
    written = {row["action"] for row in rows[1:]}
    assert written == {AuditAction.PASSWORD_CLAIMED, AuditAction.SESSIONS_REVOKED}

    claimed = _only(rows, AuditAction.PASSWORD_CLAIMED)
    assert claimed["actor_user_id"] == unclaimed.id
    assert claimed["actor_email"] == unclaimed.email
    assert claimed["details"] == {}
    # Asserted per handler, not once for the whole story: `source_ip` is a
    # defaulted keyword on `audit.record`, so a handler that stopped passing
    # it would write `NULL` and break nothing anywhere else.
    assert claimed["source_ip"] == PEER
    assert _only(rows, AuditAction.SESSIONS_REVOKED)["source_ip"] == PEER


def test_the_revocation_records_how_many_devices_it_signed_out(
    client: TestClient, conn: psycopg.Connection, unclaimed: Any, audit_rows: AuditRows
) -> None:
    # The only record of this, anywhere: `updated_at` says the row changed and
    # says nothing about the sessions that disappeared with it.
    assert client.post(CLAIM, json={"new_password": REPLACEMENT}).status_code == 200

    revoked = _only(audit_rows(conn), AuditAction.SESSIONS_REVOKED)
    assert revoked["details"] == {"cause": CAUSE_PASSWORD_WRITTEN, "count": 1}


def test_no_submitted_password_reaches_any_row(
    client: TestClient, conn: psycopg.Connection, unclaimed: Any, audit_rows: AuditRows
) -> None:
    # The rule with no runtime check behind it, asserted where it can be.
    assert client.post(CLAIM, json={"new_password": REPLACEMENT}).status_code == 200

    written = str(audit_rows(conn))
    assert REPLACEMENT not in written
    assert unclaimed.password not in written


def test_a_refused_claim_writes_nothing(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser, audit_rows: AuditRows
) -> None:
    # A claimed account is answered `409` and writes nothing, so there is
    # nothing to record.
    account = make_user()
    assert _sign_in(client, account.email, account.password).status_code == 200
    before = len(audit_rows(conn))

    assert client.post(CLAIM, json={"new_password": REPLACEMENT}).status_code == 409
    assert len(audit_rows(conn)) == before


def test_a_credential_found_lapsed_mid_request_records_its_silent_revocation(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser, audit_rows: AuditRows
) -> None:
    # The path that answers `401` and revokes every session on the way out.
    # Nothing about it is visible to the user, and before Story 1.12 nothing
    # about it was visible to anybody: no row changed, so not even
    # `updated_at` moved.
    account = make_user(
        must_change_password=True,
        temp_credential_expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    assert _sign_in(client, account.email, account.password).status_code == 200
    conn.execute(
        "UPDATE users SET temp_credential_expires_at = %s WHERE id = %s",
        (datetime.now(UTC) - timedelta(minutes=1), account.id),
    )

    assert client.post(CLAIM, json={"new_password": REPLACEMENT}).status_code == 401

    revoked = _only(audit_rows(conn), AuditAction.SESSIONS_REVOKED)
    assert revoked["details"] == {"cause": CAUSE_CREDENTIAL_EXPIRED, "count": 1}
    assert revoked["actor_user_id"] == account.id
    assert revoked["source_ip"] == PEER
    # No `password_claimed`: nothing was claimed.
    assert AuditAction.PASSWORD_CLAIMED not in {row["action"] for row in audit_rows(conn)}


# --- The self-service change -----------------------------------------------------


def test_a_self_service_change_writes_two_entries(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser, audit_rows: AuditRows
) -> None:
    account = make_user()
    assert _sign_in(client, account.email, account.password).status_code == 200

    assert (
        client.post(
            SELF_CHANGE,
            json={"current_password": account.password, "new_password": REPLACEMENT},
        ).status_code
        == 200
    )

    rows = audit_rows(conn)
    assert {row["action"] for row in rows[1:]} == {
        AuditAction.PASSWORD_CHANGED,
        AuditAction.SESSIONS_REVOKED,
    }
    assert _only(rows, AuditAction.SESSIONS_REVOKED)["details"] == {
        "cause": CAUSE_PASSWORD_WRITTEN,
        "count": 1,
    }
    assert _only(rows, AuditAction.PASSWORD_CHANGED)["source_ip"] == PEER
    assert _only(rows, AuditAction.SESSIONS_REVOKED)["source_ip"] == PEER


def test_a_wrong_current_password_is_recorded(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser, audit_rows: AuditRows
) -> None:
    # DW-72. This endpoint admits unlimited guessing at `current_password` —
    # it is deliberately not throttled (DW-40) — and before Story 1.12 a run
    # of guesses left no record anywhere in the product.
    account = make_user()
    assert _sign_in(client, account.email, account.password).status_code == 200

    assert (
        client.post(
            SELF_CHANGE,
            json={"current_password": WRONG_PASSWORD, "new_password": REPLACEMENT},
        ).status_code
        == 403
    )

    entry = _only(audit_rows(conn), AuditAction.PASSWORD_CHANGE_REFUSED)
    assert entry["actor_user_id"] == account.id
    assert entry["actor_email"] == account.email
    assert entry["target_user_id"] == account.id
    assert entry["details"] == {"reason": REASON_WRONG_PASSWORD}
    assert entry["source_ip"] == PEER
    # Deliberately *not* a `login_failed`: the session is fine, the caller is
    # already named, and nothing about the credential they signed in with is
    # in question.
    assert AuditAction.LOGIN_FAILED not in {row["action"] for row in audit_rows(conn)}


def test_a_run_of_guesses_leaves_a_run_of_rows(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser, audit_rows: AuditRows
) -> None:
    # The point of the entry above: one guess is noise, five in a row is the
    # thing somebody needs to be able to see.
    account = make_user()
    assert _sign_in(client, account.email, account.password).status_code == 200

    for _ in range(5):
        client.post(
            SELF_CHANGE,
            json={"current_password": WRONG_PASSWORD, "new_password": REPLACEMENT},
        )

    refusals = [
        row for row in audit_rows(conn) if row["action"] == AuditAction.PASSWORD_CHANGE_REFUSED
    ]
    assert len(refusals) == 5


def test_no_guessed_password_reaches_any_row(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser, audit_rows: AuditRows
) -> None:
    account = make_user()
    assert _sign_in(client, account.email, account.password).status_code == 200
    client.post(
        SELF_CHANGE,
        json={"current_password": WRONG_PASSWORD, "new_password": SECOND_REPLACEMENT},
    )

    written = str(audit_rows(conn))
    assert WRONG_PASSWORD not in written
    assert SECOND_REPLACEMENT not in written


def test_a_weak_new_password_writes_nothing(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser, audit_rows: AuditRows
) -> None:
    # A `422` changed nothing. The current password was proved, so this is not
    # a refused *attempt* at the account either — it is a body the rules
    # rejected, and the log is not a request trace.
    account = make_user()
    assert _sign_in(client, account.email, account.password).status_code == 200
    before = len(audit_rows(conn))

    assert (
        client.post(
            SELF_CHANGE,
            json={"current_password": account.password, "new_password": "short"},
        ).status_code
        == 422
    )
    assert len(audit_rows(conn)) == before


# --- No token, ever --------------------------------------------------------------


def test_no_session_token_or_digest_reaches_any_row(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser, audit_rows: AuditRows
) -> None:
    # The cookie's value and the digest stored beside it are both absent. The
    # sign-out path is the one with a real chance of leaking one, since it is
    # the only handler that is *about* a token.
    account = make_user(role=Role.STAFF)
    assert _sign_in(client, account.email, account.password).status_code == 200
    token = client.cookies.get(SESSION_COOKIE_NAME)
    assert token
    digests = [
        row["token_hash"] for row in conn.execute("SELECT token_hash FROM sessions").fetchall()
    ]
    assert client.post(LOGOUT).status_code == 204

    written = str(audit_rows(conn))
    assert token not in written
    assert all(digest not in written for digest in digests)
