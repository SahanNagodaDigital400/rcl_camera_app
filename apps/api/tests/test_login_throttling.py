"""FR-4: the progressive delay, the lockout, and the thing both must not leak.

Story 1.6 adds the first behaviour on `POST /auth/login` that is *not* the same
for every attempt, and that is the risk this file is mostly about. The endpoint
answers an unknown address, a wrong password, a deactivated account and an
expired temporary credential identically down to the header and the elapsed
time; a delay ladder is a new, loud channel running straight through the middle
of that. It carries no signal only because the counter is keyed on the address
the caller **submitted** rather than on an account — so the long test here is
the one that drives ten attempts at a real account and ten at an address that
has never existed and compares them response for response.

The timing constants are monkeypatched per test. Left alone, proving the ladder
would cost the suite ten real seconds per case, and `LOCKOUT_DURATION` would
make the expiry case fifteen minutes long. Two different techniques, because
they answer two different questions:

* a **stub clock** substituted for `api.auth`'s `time`, which records what the
  handler asked to sleep. That is exact — it asserts the rung values and the
  cap, not an approximation of them — and it also records *when* the sleep
  happened relative to the credential work, which no wall-clock measurement
  can see.
* one **real** wall-clock case, because a stub clock would keep passing if the
  `time.sleep` call were deleted and replaced with nothing. epics.md 1.6 says
  "a measurable delay", and exactly one test here measures it.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import psycopg
import pytest
from api import auth, throttle
from api.auth import ACCOUNT_LOCKED, ACCOUNT_LOCKED_MESSAGE, INVALID_CREDENTIALS
from api.sessions import SESSION_COOKIE_NAME
from fastapi.testclient import TestClient
from psycopg.rows import dict_row

LOGIN = "/auth/login"

WRONG_PASSWORD = "definitely-not-the-password"

#: `conftest.make_user`, which returns a `conftest.Account`. A conftest is not
#: an importable module under pytest's importlib mode, so the factory is typed
#: by its shape rather than by that class.
MakeUser = Callable[..., Any]

#: The delay used by the one test that measures the clock. Well above the
#: ~100ms Argon2id verify every attempt already pays, so the gap between a
#: delayed attempt and an undelayed one is the delay rather than the noise.
MEASURABLE_STEP = timedelta(milliseconds=500)


class StubClock:
    """`time`, as far as `api.auth` is concerned: records sleeps, never sleeps.

    Substituted for the module-level `time` name in `api.auth` alone —
    `monkeypatch.setattr(auth, "time", ...)` rebinds that one namespace and
    leaves the real `time` module untouched for everything else in the process,
    which patching `time.sleep` itself would not.

    `events` is shared with the recording credential stubs below so the *order*
    of the delay and the credential work is assertable. "Before it's processed"
    is the wording of the acceptance clause, and a delay paid after the password
    was checked would satisfy every duration assertion in this file.
    """

    def __init__(self, events: list[str] | None = None) -> None:
        self.slept: list[float] = []
        self.events: list[str] = [] if events is None else events

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.events.append(f"sleep:{seconds}")


def _attempt_row(conn: psycopg.Connection, email: str) -> dict[str, Any] | None:
    return conn.execute(
        "SELECT * FROM login_attempts WHERE email_key = %s", (email.strip().lower(),)
    ).fetchone()


def _users_locked_until(conn: psycopg.Connection, user_id: Any) -> datetime | None:
    row = conn.execute("SELECT locked_until FROM users WHERE id = %s", (user_id,)).fetchone()
    assert row is not None
    return row["locked_until"]


def _sessions(conn: psycopg.Connection, user_id: Any) -> list[dict[str, Any]]:
    return conn.execute("SELECT * FROM sessions WHERE user_id = %s", (user_id,)).fetchall()


def _comparable_headers(response: httpx.Response) -> dict[str, str]:
    """Every header two responses must agree about.

    Transcribed from `test_login.py` rather than imported: a conftest is the
    only module pytest's importlib mode makes importable across test files, and
    duplicating six lines is better than moving a helper the rejection tests own.
    `Date` is dropped for the reason given there — it is the clock's, not the
    endpoint's.
    """
    return {k.lower(): v for k, v in response.headers.items() if k.lower() != "date"}


def _fail(client: TestClient, email: str, password: str = WRONG_PASSWORD) -> httpx.Response:
    return client.post(LOGIN, json={"email": email, "password": password})


def _fail_times(client: TestClient, email: str, times: int) -> httpx.Response:
    response = None
    for _ in range(times):
        response = _fail(client, email)
    assert response is not None
    return response


@pytest.fixture
def instant(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the ladder's *shape* and remove its duration.

    Every rung becomes zero, so `login` sleeps nothing at all (`if delay:` is
    false for a zero timedelta) while the thresholds, the reset rules and the
    lockout are untouched. Used by every case that is about counting rather
    than about waiting.
    """
    monkeypatch.setattr(throttle, "DELAY_STEP", timedelta(0))
    monkeypatch.setattr(throttle, "MAX_DELAY", timedelta(0))


# --- The numbers themselves --------------------------------------------------


def test_the_thresholds_are_the_ones_the_requirement_names() -> None:
    """Written with literals, on purpose, and it is the only test here that is.

    Every other assertion in this file derives its expectation from
    `api.throttle`'s constants, so all of them track those constants wherever
    they go. Set `DELAY_STEP` to a millisecond or `LOCKOUT_DURATION` to a
    second and the whole suite stays green while FR-4 becomes a no-op that
    still passes a lockout test — the same blind spot
    `test_login.py::test_the_session_lifetime_is_the_week_the_addendum_specifies`
    exists to close for the session lifetime. Only a bound written
    independently of the value under test can say the value is right.

    The figures come from FR-4 and epics.md 1.6 ("progressive delay from the
    6th failed attempt; the 10th cumulative failed attempt locks the account")
    and from this story's own design notes. Deliberately stated as ranges where
    the requirement does not name an exact number, so tuning stays possible and
    gutting does not.
    """
    # "Given 5 consecutive failed attempts, when the 6th attempt is made."
    assert throttle.FAILURES_BEFORE_DELAY == 5
    # "The 10th cumulative failed attempt locks the account."
    assert throttle.FAILURES_BEFORE_LOCKOUT == 10

    # A delay a person and a test can both measure. Below a second it is not a
    # deterrent to anything; the ladder multiplies it four times over.
    assert throttle.DELAY_STEP >= timedelta(seconds=1)
    assert throttle.DELAY_STEP <= timedelta(seconds=2)

    # The cap is a real bound on a real delay: never shorter than one rung, and
    # never so long that one attempt pins a threadpool worker for a visible
    # fraction of a minute.
    assert throttle.MAX_DELAY >= throttle.DELAY_STEP
    assert timedelta(seconds=1) <= throttle.MAX_DELAY <= timedelta(seconds=10)

    # A quarter of an hour. Long enough that ten guesses per fifteen minutes is
    # not worth continuing; short enough that a member of staff who locked
    # themselves out is not waiting on an Administrator who — per FR-5 and this
    # epic — has no unlock button to press.
    assert throttle.LOCKOUT_DURATION == timedelta(minutes=15)

    # A run of failures outlives a lock, and by a clear margin. Inverted, a
    # stale run would be what ends a live lock: the sweep and the reset would
    # both treat a locked row as finished, and the lockout would last until the
    # window rather than until its own deadline.
    assert throttle.LOCKOUT_DURATION < throttle.ATTEMPT_WINDOW
    assert throttle.ATTEMPT_WINDOW >= timedelta(minutes=30)


# --- Counting ----------------------------------------------------------------


def test_the_first_failure_creates_the_row(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser, instant: None
) -> None:
    account = make_user()

    response = _fail(client, account.email)

    assert response.status_code == 401
    assert response.json()["error"]["message"] == INVALID_CREDENTIALS
    row = _attempt_row(conn, account.email)
    assert row is not None
    assert row["failure_count"] == 1
    assert row["locked_until"] is None


def test_failures_below_the_threshold_only_increment(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser, instant: None
) -> None:
    account = make_user()

    for expected in range(1, throttle.FAILURES_BEFORE_LOCKOUT):
        response = _fail(client, account.email)

        assert response.status_code == 401, expected
        row = _attempt_row(conn, account.email)
        assert row is not None
        assert row["failure_count"] == expected
        # Nine failures and still no lock: the threshold is the tenth, not "more
        # than five", and an off-by-one here is a product that locks accounts
        # half way through the ladder it just advertised.
        assert row["locked_until"] is None


def test_the_counter_is_keyed_on_the_address_as_submitted(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser, instant: None
) -> None:
    # The same key the credential lookup is parameterized with: stripped and
    # lowercased. Without that, `  KASUN@rocell.lk ` and `kasun@rocell.lk` are
    # two counters and ten failures never become a lockout.
    account = make_user()

    _fail(client, account.email)
    _fail(client, f"  {account.email.upper()}  ")

    row = _attempt_row(conn, account.email)
    assert row is not None
    assert row["failure_count"] == 2


def test_a_successful_sign_in_forgets_the_run(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser, instant: None
) -> None:
    account = make_user()
    _fail_times(client, account.email, 3)
    assert _attempt_row(conn, account.email) is not None

    response = client.post(LOGIN, json={"email": account.email, "password": account.password})

    assert response.status_code == 200
    assert _attempt_row(conn, account.email) is None


def test_an_unaddressable_address_is_refused_without_reaching_the_counter(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser, instant: None
) -> None:
    # A NUL byte cannot be sent to Postgres at all, and the counter's key *is*
    # that string. The attempt is refused exactly as before and nothing is
    # written — asserted because the alternative is a 500 on the one endpoint
    # anybody can reach without a credential.
    account = make_user()

    response = _fail(client, f"{account.email}\x00", account.password)

    assert response.status_code == 401
    count = conn.execute("SELECT count(*) AS n FROM login_attempts").fetchone()
    assert count is not None
    assert count["n"] == 0


# --- The ladder --------------------------------------------------------------


@pytest.mark.parametrize(
    ("failures", "expected_rungs"),
    [
        pytest.param(0, 0, id="first attempt"),
        pytest.param(4, 0, id="fifth attempt"),
        pytest.param(5, 1, id="sixth attempt"),
        pytest.param(6, 2, id="seventh attempt"),
        pytest.param(7, 3, id="eighth attempt"),
        pytest.param(8, 4, id="ninth attempt"),
        pytest.param(9, 4, id="tenth attempt, capped"),
        pytest.param(40, 4, id="far past the cap"),
    ],
)
def test_the_ladder_starts_at_the_sixth_attempt_and_is_capped(
    failures: int, expected_rungs: int
) -> None:
    # The rung values themselves, with no database and no clock. The cap is the
    # assertion that matters most: uncapped, an attacker picks how long each
    # attempt pins one of Starlette's 40 threadpool workers, and every duration
    # test below would still pass. Not a bound on a held connection — `login`
    # holds none across the sleep — see `MAX_DELAY`'s own comment.
    state = throttle.AttemptState(failure_count=failures, locked_until=None)

    expected = min(throttle.DELAY_STEP * expected_rungs, throttle.MAX_DELAY)
    assert state.delay() == expected
    assert state.delay() <= throttle.MAX_DELAY


def test_the_sixth_attempt_sleeps_and_the_fifth_does_not(
    client: TestClient, make_user: MakeUser, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = StubClock()
    monkeypatch.setattr(auth, "time", clock)
    account = make_user()

    _fail_times(client, account.email, throttle.FAILURES_BEFORE_DELAY)
    assert clock.slept == []

    _fail(client, account.email)

    assert clock.slept == [throttle.DELAY_STEP.total_seconds()]


def test_the_ladder_climbs_and_then_stops_climbing(
    client: TestClient, make_user: MakeUser, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = StubClock()
    monkeypatch.setattr(auth, "time", clock)
    account = make_user()

    _fail_times(client, account.email, throttle.FAILURES_BEFORE_LOCKOUT)

    step = throttle.DELAY_STEP.total_seconds()
    cap = throttle.MAX_DELAY.total_seconds()
    # Attempts 6, 7, 8, 9 and 10: 1s, 2s, 3s, 4s, 4s — five delayed attempts,
    # and the longest any one of them waits is `MAX_DELAY`. What that bounds is
    # a threadpool worker, not a pooled connection: none is held here at all.
    assert clock.slept == [min(step * rung, cap) for rung in (1, 2, 3, 4, 5)]


def test_the_delay_is_paid_before_any_credential_work(
    client: TestClient, make_user: MakeUser, monkeypatch: pytest.MonkeyPatch
) -> None:
    # "A measurable delay is introduced before it's processed" (epics.md 1.6).
    # A delay paid *after* the password was verified satisfies every duration
    # assertion in this file and none of the requirement: the expensive work has
    # already happened, and an attacker's throughput is unchanged.
    events: list[str] = []
    clock = StubClock(events)
    monkeypatch.setattr(auth, "time", clock)
    monkeypatch.setattr(
        auth, "verify_password", lambda digest, candidate: events.append("verify") or False
    )
    monkeypatch.setattr(
        auth, "verify_dummy_password", lambda candidate: events.append("decoy") or False
    )
    account = make_user()

    _fail_times(client, account.email, throttle.FAILURES_BEFORE_DELAY + 1)

    assert events[-2:] == [f"sleep:{throttle.DELAY_STEP.total_seconds()}", "verify"]


def test_the_delay_is_paid_on_a_correct_credential_too(
    client: TestClient,
    conn: psycopg.Connection,
    make_user: MakeUser,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Skipping the delay for a correct password would make it a password
    # oracle: on the sixth attempt an instant answer would mean the guess was
    # right, before the cookie ever arrived.
    clock = StubClock()
    monkeypatch.setattr(auth, "time", clock)
    account = make_user()
    _fail_times(client, account.email, throttle.FAILURES_BEFORE_DELAY)

    response = client.post(LOGIN, json={"email": account.email, "password": account.password})

    assert response.status_code == 200
    assert clock.slept == [throttle.DELAY_STEP.total_seconds()]
    assert _attempt_row(conn, account.email) is None


def test_the_sixth_attempt_is_measurably_later_on_a_real_clock(
    client: TestClient, make_user: MakeUser, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The acceptance clause itself, on the wall clock rather than on a stub.

    Every other timing test here substitutes `api.auth`'s `time`, which means
    all of them keep passing if the `time.sleep` call is deleted outright —
    `StubClock.sleep` would simply never be reached and `slept` would be
    compared against a list nobody built. This is the one case that would fail,
    so it uses the real clock and a real sleep and pays for it once.
    """
    monkeypatch.setattr(throttle, "DELAY_STEP", MEASURABLE_STEP)
    monkeypatch.setattr(throttle, "MAX_DELAY", MEASURABLE_STEP)
    account = make_user()
    _fail_times(client, account.email, throttle.FAILURES_BEFORE_DELAY - 1)

    started = time.perf_counter()
    _fail(client, account.email)
    fifth = time.perf_counter() - started

    started = time.perf_counter()
    _fail(client, account.email)
    sixth = time.perf_counter() - started

    # Stated as a *difference*, never as a ceiling on the fifth. Both figures
    # include a real 64 MiB Argon2id verify, a TestClient round trip and an
    # ephemeral-Postgres query, and an absolute bound like `fifth < one step`
    # is an assertion about how loaded the machine is rather than about the
    # code. `sleep` never returns early, so the difference is at least one whole
    # step minus whatever the hash happened to vary by between the two attempts
    # — and half a step of slack for that is still far tighter than a delay
    # that had been halved or deleted.
    assert sixth - fifth >= MEASURABLE_STEP.total_seconds() / 2
    assert sixth >= MEASURABLE_STEP.total_seconds()


def test_the_delay_holds_no_pooled_connection(
    client: TestClient, make_user: MakeUser, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The delay must not be a denial of service against the whole product.

    `api.db` caps the pool at `POOL_MAX_SIZE` (10) and makes every other request
    wait `POOL_TIMEOUT_SECONDS` (10s) for a free connection. A handler that
    slept while holding one would let ten throttled sign-ins — primed with five
    cheap failures per address, against addresses that need not even be accounts
    — empty the pool for the length of the ladder, and *every* endpoint in the
    product, not just login, would start failing on acquisition. Capping the
    ladder bounds how long that lasts; it does not stop it happening.

    So this looks at the pool from inside the sleep itself: nothing may be
    checked out at that moment. `pool_available == pool_size` is the pool saying
    every connection it has built is idle.
    """
    observed: list[dict[str, int]] = []

    class WatchingClock:
        """A clock that inspects the pool at the instant the handler waits."""

        def sleep(self, seconds: float) -> None:
            observed.append(dict(client.app.state.pool.get_stats()))

    monkeypatch.setattr(auth, "time", WatchingClock())
    account = make_user()

    _fail_times(client, account.email, throttle.FAILURES_BEFORE_DELAY + 1)

    assert observed, "the sixth attempt never reached the delay at all"
    for stats in observed:
        # A connection was built — the counter read just used one — and it was
        # given back before the sleep started.
        assert stats["pool_size"] >= 1, stats
        assert stats["pool_available"] == stats["pool_size"], stats


# --- The lockout -------------------------------------------------------------


def test_the_tenth_failure_locks_the_address(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser, instant: None
) -> None:
    account = make_user()

    response = _fail_times(client, account.email, throttle.FAILURES_BEFORE_LOCKOUT)

    assert response.status_code == 429
    body = response.json()
    assert body["error"]["code"] == ACCOUNT_LOCKED
    assert body["error"]["message"] == ACCOUNT_LOCKED_MESSAGE
    # Not the wrong-password sentence. EXPERIENCE.md's Login-lockout row
    # requires a different message, and this is the one rejection allowed to
    # differ from it.
    assert body["error"]["message"] != INVALID_CREDENTIALS
    assert response.headers["cache-control"] == "no-store"

    row = _attempt_row(conn, account.email)
    assert row is not None
    assert row["failure_count"] == throttle.FAILURES_BEFORE_LOCKOUT
    assert row["locked_until"] > datetime.now(UTC)

    # `Retry-After` against the lock actually written, not merely "> 0" — which
    # `retry_after()`'s own `max(1, ...)` clamp guarantees on every path that
    # reaches it. Inverting the subtraction, or rounding down instead of up,
    # leaves a "> 0" assertion green while every conforming client retries a
    # second later into the same refusal, forever.
    remaining = (row["locked_until"] - datetime.now(UTC)).total_seconds()
    assert int(response.headers["retry-after"]) == pytest.approx(remaining, abs=2)


def test_the_lock_is_mirrored_onto_the_account_status(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser, instant: None
) -> None:
    # FR-4: "visible to Administrators on that user's status". The surface that
    # carries it is the shared `User` contract, and this column is what Story
    # 1.9's user list renders.
    account = make_user()
    before = conn.execute(
        "SELECT locked_until, updated_at FROM users WHERE id = %s", (account.id,)
    ).fetchone()
    assert before is not None
    assert before["locked_until"] is None

    _fail_times(client, account.email, throttle.FAILURES_BEFORE_LOCKOUT)

    after = conn.execute(
        "SELECT locked_until, updated_at FROM users WHERE id = %s", (account.id,)
    ).fetchone()
    assert after is not None
    assert after["locked_until"] > datetime.now(UTC)
    # DW-17: `users` carries no BEFORE UPDATE trigger, so the mirror sets this
    # by hand. Nothing else would catch it forgetting.
    assert after["updated_at"] > before["updated_at"]


def test_the_ninth_failure_leaves_the_account_status_alone(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser, instant: None
) -> None:
    # The mirror is one `UPDATE` on the tenth failure and nothing at all before
    # it. Written to fire on every failure it would be nine extra writes to
    # `users` per guessing run, and `updated_at` would move for an account
    # nothing happened to.
    account = make_user()

    _fail_times(client, account.email, throttle.FAILURES_BEFORE_LOCKOUT - 1)

    assert _users_locked_until(conn, account.id) is None


def test_a_locked_attempt_spends_nothing(
    client: TestClient,
    conn: psycopg.Connection,
    make_user: MakeUser,
    monkeypatch: pytest.MonkeyPatch,
    instant: None,
) -> None:
    """No hashing, no counter write, no sleep — the point of locking at all.

    A lockout that still paid for an Argon2id verify would leave the endpoint
    exactly as expensive to attack as it was before, and one that still
    incremented the counter would extend its own expiry every time it was
    tested — a lock nobody could ever wait out.
    """
    account = make_user()
    _fail_times(client, account.email, throttle.FAILURES_BEFORE_LOCKOUT)
    before = _attempt_row(conn, account.email)
    assert before is not None

    calls: list[str] = []
    monkeypatch.setattr(
        auth, "verify_password", lambda digest, candidate: calls.append("verify") or False
    )
    monkeypatch.setattr(auth, "verify_dummy_password", lambda candidate: calls.append("decoy"))
    clock = StubClock()
    monkeypatch.setattr(auth, "time", clock)

    response = _fail(client, account.email)

    assert response.status_code == 429
    assert calls == []
    assert clock.slept == []
    after = _attempt_row(conn, account.email)
    assert after is not None
    assert after["failure_count"] == before["failure_count"]
    assert after["locked_until"] == before["locked_until"]


def test_a_live_lock_is_never_re_armed(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser, instant: None
) -> None:
    """The lock has a deadline, and continuing to guess must not move it.

    `login` refuses a locked address before it reaches `record_failure`, but it
    does so one attempt at a time: a burst that all read `attempt_state` before
    the lock lands arrives at the counter *after* it, and without the
    `locked_until > now()` branch each of them would push the expiry out by
    another `LOCKOUT_DURATION`. That is a lock nobody can wait out — and since a
    locked attempt costs no credential work, holding a legitimate user out
    indefinitely would be free. With no unlock surface in the product (FR-5),
    the expiry *is* the recovery, so it has to be a fixed instant.

    Driven through `record_failure` directly because that is the only way to
    reach the statement the way a burst does; through the endpoint the lock
    branch answers first, which is the serial guard this test is not about.
    """
    account = make_user()
    _fail_times(client, account.email, throttle.FAILURES_BEFORE_LOCKOUT)
    locked = _attempt_row(conn, account.email)
    assert locked is not None
    assert locked["locked_until"] is not None

    for _ in range(3):
        state = throttle.record_failure(conn, account.email)
        assert state.locked

    row = _attempt_row(conn, account.email)
    assert row is not None
    # The deadline has not moved by so much as a microsecond...
    assert row["locked_until"] == locked["locked_until"]
    # ...and the count is still allowed to climb, which is what keeps the run
    # from being mistaken for a fresh one when the lock does lapse.
    assert row["failure_count"] == throttle.FAILURES_BEFORE_LOCKOUT + 3


def test_only_the_locking_failure_touches_the_account_status(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser, instant: None
) -> None:
    # The mirror is one `UPDATE` on the failure that writes the lock, and
    # nothing afterwards: a later attempt on an already-locked row changed
    # nothing, so moving `users.updated_at` for it would be a write recording
    # that nothing happened.
    account = make_user()
    _fail_times(client, account.email, throttle.FAILURES_BEFORE_LOCKOUT)
    after_lock = conn.execute(
        "SELECT locked_until, updated_at FROM users WHERE id = %s", (account.id,)
    ).fetchone()
    assert after_lock is not None

    for _ in range(3):
        throttle.record_failure(conn, account.email)

    later = conn.execute(
        "SELECT locked_until, updated_at FROM users WHERE id = %s", (account.id,)
    ).fetchone()
    assert later is not None
    assert later == after_lock


def test_the_lock_is_logged_without_naming_the_address(
    client: TestClient, make_user: MakeUser, caplog: pytest.LogCaptureFixture, instant: None
) -> None:
    # The brief's security addendum wants a lockout logged. Story 1.12 owes the
    # audit entry; until then this is the only operational trace outside two
    # table values. The address is deliberately absent — most of what this
    # counter holds was never an account, and a log accumulating every address
    # someone guessed is a list of candidate usernames without any of the audit
    # log's protections.
    account = make_user()

    with caplog.at_level(logging.INFO, logger="rocell.api.throttle"):
        _fail_times(client, account.email, throttle.FAILURES_BEFORE_LOCKOUT)

    # Filtered by logger as well as by level: `caplog`'s handler is attached at
    # the root, so `at_level(..., logger=...)` raises that logger's level without
    # narrowing what is captured. Counting every INFO record in the process would
    # make this assertion fail the day any other module logs one during a login.
    locked = [
        record
        for record in caplog.records
        if record.levelno == logging.INFO and record.name == "rocell.api.throttle"
    ]
    assert len(locked) == 1, [record.getMessage() for record in caplog.records]
    assert account.email not in caplog.text
    assert account.email.split("@")[0] not in caplog.text
    assert account.password not in caplog.text


def test_a_failing_status_mirror_still_answers_the_lockout(
    client: TestClient,
    conn: psycopg.Connection,
    make_user: MakeUser,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    instant: None,
) -> None:
    # The counter row has already committed by the time the mirror runs, so the
    # lock is durable whatever happens to it. Letting a failure out would answer
    # 500 to the *tenth* attempt while every other attempt answered 401 or 429 —
    # a response shape reachable at one specific count.
    monkeypatch.setattr(
        throttle, "_MIRROR_LOCK", "UPDATE no_such_table SET locked_until = %s WHERE email = %s"
    )
    account = make_user()

    with caplog.at_level(logging.WARNING, logger="rocell.api.throttle"):
        response = _fail_times(client, account.email, throttle.FAILURES_BEFORE_LOCKOUT)

    assert response.status_code == 429
    assert any(record.levelno == logging.WARNING for record in caplog.records)
    row = _attempt_row(conn, account.email)
    assert row is not None
    assert row["locked_until"] > datetime.now(UTC)
    # The enforcement survived; only the Administrator's view of it did not.
    assert _users_locked_until(conn, account.id) is None
    assert _fail(client, account.email).status_code == 429


def test_clearing_the_account_status_does_not_unlock_anything(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser, instant: None
) -> None:
    """`users.locked_until` is inert, and this is what holds it to that.

    Four docstrings and two README paragraphs say enforcement never reads this
    column. Nothing else would notice if it started to — and the way that gets
    noticed for real is Story 1.10 growing an "unlock" that clears the mirror,
    appears to work in review, and leaves the account locked out for the rest of
    `LOCKOUT_DURATION` with an Administrator insisting they already fixed it.
    """
    account = make_user()
    _fail_times(client, account.email, throttle.FAILURES_BEFORE_LOCKOUT)
    assert _users_locked_until(conn, account.id) is not None

    conn.execute("UPDATE users SET locked_until = NULL WHERE id = %s", (account.id,))

    # Still refused, with the correct password, from the counter alone.
    assert _users_locked_until(conn, account.id) is None
    refused = client.post(LOGIN, json={"email": account.email, "password": account.password})
    assert refused.status_code == 429
    assert refused.json()["error"]["code"] == ACCOUNT_LOCKED
    assert _sessions(conn, account.id) == []


def test_a_lock_that_lands_during_the_delay_still_beats_a_correct_password(
    client: TestClient,
    conn: psycopg.Connection,
    make_user: MakeUser,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The seam the delay opens: the state is read *before* the sleep.

    `login` reads the counter, gives its connection back, sleeps, and takes a
    fresh connection to do the credential work — which is what keeps a throttled
    attempt from pinning one of ten pooled connections for `MAX_DELAY`. It also
    means that on a delayed attempt the lock decision is up to `MAX_DELAY` old,
    and the attempts that put this one on the ladder are by definition still
    arriving. One of them locking the address mid-sleep must not leave this
    request free to authenticate: the matrix says the lock wins over the
    credential, and it says so about the attempt, not about the moment it was
    first looked at.

    Worse than one request slipping through, if it did: a successful sign-in
    ends the run of failures by *deleting the counter row*, so the one request
    that raced the lock would take everybody else's lockout with it.

    The stub clock is what makes the race deterministic — its `sleep` runs
    inside the handler at exactly the point the real one would, and no
    connection is held while it does, so the write below cannot deadlock
    against the request that provoked it.
    """
    account = make_user()
    _fail_times(client, account.email, throttle.FAILURES_BEFORE_DELAY)
    events: list[str] = []

    class LockingClock(StubClock):
        """A sleep that another request's tenth failure lands in the middle of."""

        def sleep(self, seconds: float) -> None:
            super().sleep(seconds)
            conn.execute(
                """
                UPDATE login_attempts
                   SET failure_count = %s,
                       locked_until = now() + %s,
                       last_failure_at = now()
                 WHERE email_key = %s
                """,
                (
                    throttle.FAILURES_BEFORE_LOCKOUT,
                    throttle.LOCKOUT_DURATION,
                    account.email,
                ),
            )

    clock = LockingClock(events)
    monkeypatch.setattr(auth, "time", clock)
    monkeypatch.setattr(
        auth, "verify_password", lambda digest, candidate: events.append("verify") or True
    )

    response = client.post(LOGIN, json={"email": account.email, "password": account.password})

    assert response.status_code == 429
    assert response.json()["error"]["code"] == ACCOUNT_LOCKED
    assert clock.slept == [throttle.DELAY_STEP.total_seconds()]
    # Refused before the credential, as every other locked attempt is.
    assert "verify" not in events
    assert SESSION_COOKIE_NAME not in client.cookies
    assert _sessions(conn, account.id) == []
    # And the lock the other request wrote is still there to refuse the next one.
    row = _attempt_row(conn, account.email)
    assert row is not None
    assert row["locked_until"] > datetime.now(UTC)


def test_an_undelayed_attempt_reads_the_counter_once(
    client: TestClient, make_user: MakeUser, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The re-read above is paid only by attempts that actually slept. An
    # ordinary sign-in acts on a state read microseconds earlier — the same
    # window every other statement in the handler runs in — and buying a second
    # lookup for it on every request would close nothing.
    reads: list[str] = []
    real_attempt_state = throttle.attempt_state
    monkeypatch.setattr(
        auth,
        "attempt_state",
        lambda conn, email: (reads.append(email), real_attempt_state(conn, email))[1],
    )
    account = make_user()

    response = client.post(LOGIN, json={"email": account.email, "password": account.password})

    assert response.status_code == 200
    assert reads == [account.email.strip().lower()]


def test_the_lock_beats_a_correct_password(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser, instant: None
) -> None:
    account = make_user()
    _fail_times(client, account.email, throttle.FAILURES_BEFORE_LOCKOUT)

    response = client.post(LOGIN, json={"email": account.email, "password": account.password})

    assert response.status_code == 429
    assert response.json()["error"]["code"] == ACCOUNT_LOCKED
    assert SESSION_COOKIE_NAME not in client.cookies
    assert _sessions(conn, account.id) == []


def test_a_lockout_sets_no_cookie_and_carries_no_challenge(
    client: TestClient, make_user: MakeUser, instant: None
) -> None:
    # No `WWW-Authenticate`: there is no credential that would work right now,
    # so challenging for one would be untrue — and a `Basic` challenge would
    # open the browser's own dialog over the login screen.
    account = make_user()

    response = _fail_times(client, account.email, throttle.FAILURES_BEFORE_LOCKOUT)

    assert "set-cookie" not in {k.lower() for k in response.headers}
    assert "www-authenticate" not in {k.lower() for k in response.headers}


def test_the_lockout_message_names_no_duration() -> None:
    # EXPERIENCE.md's Login-lockout row: a different message from a
    # wrong-password rejection, and **no countdown**. The number is in
    # `Retry-After` for a machine; the sentence has none.
    assert not any(character.isdigit() for character in ACCOUNT_LOCKED_MESSAGE)
    for leak in ("minute", "second", "hour", "15", "expire"):
        assert leak not in ACCOUNT_LOCKED_MESSAGE.lower()


# --- Runs end ----------------------------------------------------------------


def test_an_expired_lock_starts_a_fresh_run(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser, instant: None
) -> None:
    # Without the reset the eleventh failure after a lapsed lock is still "the
    # tenth or later" and re-locks immediately — one mistyped password an hour
    # later leaving a legitimate user locked out for good, with no unlock
    # surface anywhere in the product to recover it (FR-5).
    account = make_user()
    _fail_times(client, account.email, throttle.FAILURES_BEFORE_LOCKOUT)
    conn.execute(
        "UPDATE login_attempts SET locked_until = now() - %s WHERE email_key = %s",
        (timedelta(minutes=1), account.email),
    )

    response = _fail(client, account.email)

    assert response.status_code == 401
    row = _attempt_row(conn, account.email)
    assert row is not None
    assert row["failure_count"] == 1
    assert row["locked_until"] is None


def test_a_correct_password_works_once_the_lock_has_lapsed(
    client: TestClient,
    conn: psycopg.Connection,
    make_user: MakeUser,
    monkeypatch: pytest.MonkeyPatch,
    instant: None,
) -> None:
    # The lock really is waited out here rather than backdated in the table:
    # `LOCKOUT_DURATION` is shortened and the test sleeps through it, so the
    # counter and the `users` mirror lapse together exactly as they would after
    # fifteen real minutes. Backdating only `login_attempts` would leave the
    # mirror in the future and prove nothing about the pair.
    monkeypatch.setattr(throttle, "LOCKOUT_DURATION", timedelta(milliseconds=300))
    account = make_user()
    _fail_times(client, account.email, throttle.FAILURES_BEFORE_LOCKOUT)
    assert _users_locked_until(conn, account.id) is not None
    time.sleep(0.4)

    response = client.post(LOGIN, json={"email": account.email, "password": account.password})

    assert response.status_code == 200
    # The mirror is status *and history*: it is never cleared, so an
    # Administrator still sees that this account was locked, in the past.
    lapsed = _users_locked_until(conn, account.id)
    assert lapsed is not None
    assert lapsed < datetime.now(UTC)
    assert response.json()["locked_until"] == lapsed.astimezone(UTC).isoformat()


def test_a_stale_run_resets(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser, instant: None
) -> None:
    # Nine failures from before lunch are not part of this afternoon's attempt.
    # Counting them would let three mistyped passwords a month apart join up
    # into a lockout.
    account = make_user()
    _fail_times(client, account.email, throttle.FAILURES_BEFORE_LOCKOUT - 1)
    conn.execute(
        "UPDATE login_attempts SET last_failure_at = now() - %s WHERE email_key = %s",
        (throttle.ATTEMPT_WINDOW + timedelta(minutes=1), account.email),
    )

    response = _fail(client, account.email)

    assert response.status_code == 401
    row = _attempt_row(conn, account.email)
    assert row is not None
    assert row["failure_count"] == 1


def test_a_stale_run_is_not_delayed_either(
    client: TestClient,
    conn: psycopg.Connection,
    make_user: MakeUser,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The read and the write have to agree about when a run has ended. If only
    # the write reset, the attempt that resets the count would still pay the
    # top of the ladder for failures nobody is counting any more.
    clock = StubClock()
    monkeypatch.setattr(auth, "time", clock)
    account = make_user()
    _fail_times(client, account.email, throttle.FAILURES_BEFORE_LOCKOUT - 1)
    clock.slept.clear()
    conn.execute(
        "UPDATE login_attempts SET last_failure_at = now() - %s WHERE email_key = %s",
        (throttle.ATTEMPT_WINDOW + timedelta(minutes=1), account.email),
    )

    _fail(client, account.email)

    assert clock.slept == []


def test_the_sweep_clears_rows_nothing_can_reach(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser, instant: None
) -> None:
    # A guessing run against a dictionary of invented addresses leaves a row
    # per address. `attempt_state` already reads a stale row as a fresh run, so
    # this changes no behaviour — which is why nothing else would notice it
    # becoming a no-op while the table grew forever.
    account = make_user()
    conn.execute(
        """
        INSERT INTO login_attempts (email_key, failure_count, last_failure_at)
        VALUES (%s, 3, now() - %s)
        """,
        ("invented@rocell.lk", throttle.ATTEMPT_WINDOW + timedelta(minutes=5)),
    )

    _fail(client, account.email)

    assert _attempt_row(conn, "invented@rocell.lk") is None
    # The row this attempt just wrote is not swept with it.
    assert _attempt_row(conn, account.email) is not None


def test_the_sweep_leaves_a_live_lock_alone(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser, instant: None
) -> None:
    # A tidy-up must not be the thing that decides an address may try again.
    account = make_user()
    conn.execute(
        """
        INSERT INTO login_attempts (email_key, failure_count, locked_until, last_failure_at)
        VALUES (%s, 10, now() + %s, now() - %s)
        """,
        (
            "locked-long-ago@rocell.lk",
            timedelta(minutes=10),
            throttle.ATTEMPT_WINDOW + timedelta(minutes=5),
        ),
    )

    _fail(client, account.email)

    assert _attempt_row(conn, "locked-long-ago@rocell.lk") is not None


# --- The invariant the whole design is bent around ---------------------------


def test_the_sweep_is_bounded_so_one_attempt_never_drains_a_whole_backlog(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser, instant: None
) -> None:
    # The bound is the whole reason `ATTEMPT_SWEEP_LIMIT` exists, and with one
    # stale row in the table the test above passes whether the LIMIT is 100, 1
    # or absent. Seed more than the limit and one unlucky attempt's share
    # becomes observable — the same argument, and the same shape, as
    # `test_login.py::test_the_sweep_is_bounded_so_one_sign_in_never_drains_a_whole_backlog`.
    #
    # Driven with real rows rather than by shrinking the constant: `_sweep`'s
    # `limit` is a default argument bound at import, so monkeypatching
    # `throttle.ATTEMPT_SWEEP_LIMIT` would not reach it.
    account = make_user()
    stale = throttle.ATTEMPT_SWEEP_LIMIT + 5
    with conn.transaction():
        for index in range(stale):
            conn.execute(
                """
                INSERT INTO login_attempts (email_key, failure_count, last_failure_at)
                VALUES (%s, 3, now() - %s)
                """,
                (f"invented-{index}@rocell.lk", throttle.ATTEMPT_WINDOW + timedelta(minutes=5)),
            )

    _fail(client, account.email)

    left = conn.execute(
        "SELECT count(*) AS n FROM login_attempts WHERE last_failure_at <= now() - %s",
        (throttle.ATTEMPT_WINDOW,),
    ).fetchone()
    assert left is not None
    assert left["n"] == stale - throttle.ATTEMPT_SWEEP_LIMIT


def test_an_address_with_no_account_behaves_identically_at_every_step(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser, instant: None
) -> None:
    """Ten attempts against a real account and ten against an address that is not one.

    This is the test the email-keyed counter exists for. Keyed on `users.id`,
    the real account would climb the ladder and lock while the invented address
    answered instantly forever — six wrong passwords at a candidate address
    would then tell an attacker whether it is an account, which is precisely
    what `_rejected()` and `verify_dummy_password` are built to prevent.

    Compared response for response, not merely at the end: the two sequences
    have to agree at the first attempt, at the sixth and at the tenth, because a
    difference at any one of them is the whole oracle.
    """
    account = make_user()
    unknown = f"nobody-{account.email}"

    real = [_fail(client, account.email) for _ in range(throttle.FAILURES_BEFORE_LOCKOUT)]
    invented = [_fail(client, unknown) for _ in range(throttle.FAILURES_BEFORE_LOCKOUT)]

    for index, (left, right) in enumerate(zip(real, invented, strict=True), start=1):
        assert left.status_code == right.status_code, index
        assert left.json() == right.json(), index
        assert _comparable_headers(left) == _comparable_headers(right), index

    # And both really did reach the lockout, or the comparison above is two
    # identical sequences of nothing in particular.
    assert real[-1].status_code == 429
    assert invented[-1].status_code == 429

    # The mirror `UPDATE` ran for the invented address too and matched no row,
    # which is what makes the two locking responses cost the same.
    locked = conn.execute(
        "SELECT count(*) AS n FROM users WHERE locked_until IS NOT NULL"
    ).fetchone()
    assert locked is not None
    assert locked["n"] == 1
    assert _users_locked_until(conn, account.id) is not None
    assert _attempt_row(conn, unknown) is not None


def test_the_status_mirror_runs_for_an_address_that_is_not_an_account(
    client: TestClient, conn: psycopg.Connection, monkeypatch: pytest.MonkeyPatch, instant: None
) -> None:
    """The half of the test above that its own assertions cannot see.

    `test_an_address_with_no_account_behaves_identically_at_every_step` ends by
    counting locked `users` rows and finding one, and says in a comment that
    this shows the mirror ran for the invented address and matched nothing. It
    does not: a build that skipped `_mirror` entirely whenever no account
    matched produces exactly that count, exactly those bodies and exactly those
    headers, and the whole file stays green.

    What such a build would cost is the point. Guarding the mirror with a
    `SELECT 1 FROM users WHERE lower(email) = %s` reads like an obvious saving
    of a no-op write, and it makes the tenth attempt against a real address cost
    a lookup *and* a row update while the tenth against an invented one costs a
    lookup only — putting the account-existence oracle back at the one attempt
    this story is loudest about removing it from. So the call itself is asserted,
    not merely its visible effect.
    """
    calls: list[tuple[str, datetime]] = []
    mirror = throttle._mirror

    def spy(connection: psycopg.Connection, email_key: str, locked_until: datetime) -> None:
        calls.append((email_key, locked_until))
        mirror(connection, email_key, locked_until)

    monkeypatch.setattr(throttle, "_mirror", spy)
    unknown = "nobody@rocell.lk"

    response = _fail_times(client, unknown, throttle.FAILURES_BEFORE_LOCKOUT)

    assert response.status_code == 429
    # Once, on the failure that wrote the lock, and with the address as typed.
    assert len(calls) == 1
    assert calls[0][0] == unknown
    assert calls[0][1] > datetime.now(UTC)
    # It ran and matched nothing, which is the state the identical responses
    # depend on — not "it was skipped because there was nothing to match".
    locked = conn.execute(
        "SELECT count(*) AS n FROM users WHERE locked_until IS NOT NULL"
    ).fetchone()
    assert locked is not None
    assert locked["n"] == 0
    # An eleventh attempt is refused by the existing lock and writes no new one,
    # so it re-mirrors nothing either.
    assert _fail(client, unknown).status_code == 429
    assert len(calls) == 1


def test_a_lock_does_not_end_a_session_that_is_already_open(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser, instant: None
) -> None:
    """FR-4 blocks attempts. It does not sign anybody out — and this is what says so.

    `_SELECT_SESSION` now carries `u.locked_until` on every authenticated
    request, and the column sits one line away from the `AND u.active` that
    *does* end a session. Adding the matching `AND (u.locked_until IS NULL OR
    u.locked_until <= now())` reads as obviously correct next to it, and is the
    change Story 1.9 or 1.10 is most likely to reach for. Nothing in the suite
    noticed: no test in this file made an authenticated request at all, and
    every session test builds users who have never been locked.

    What it would ship is a way to sign any member of staff out of the product
    by typing ten wrong passwords at their address — a lockout that revokes
    sessions, which is Story 1.11's deactivation, not this one.

    It is also the only place the story's own acceptance clause is observable:
    a locked account cannot sign in, so the *live* lock reaches the `User`
    contract on exactly one surface, and this is it.
    """
    account = make_user()
    signed_in = client.post(LOGIN, json={"email": account.email, "password": account.password})
    assert signed_in.status_code == 200
    assert signed_in.json()["locked_until"] is None

    # Locked from elsewhere while this browser sits on the app. The cookie jar
    # keeps the session cookie throughout: a refused sign-in sets no cookie and
    # clears none.
    assert _fail_times(client, account.email, throttle.FAILURES_BEFORE_LOCKOUT).status_code == 429

    session = client.get("/auth/session")

    assert session.status_code == 200
    assert len(_sessions(conn, account.id)) == 1
    # And the lock is what an Administrator reading this account sees: a live
    # one, in the future, on the contract's own key.
    locked_until = session.json()["locked_until"]
    assert locked_until is not None
    assert datetime.fromisoformat(locked_until) > datetime.now(UTC)
    assert datetime.fromisoformat(locked_until) == _users_locked_until(conn, account.id)


def test_an_account_deleted_mid_sign_in_is_refused_like_every_other_failure(
    client: TestClient,
    conn: psycopg.Connection,
    make_user: MakeUser,
    monkeypatch: pytest.MonkeyPatch,
    instant: None,
) -> None:
    """The `_SignInVanished` branch — the handler's only `except`.

    The row is deleted between the credential read and `_RECORD_LOGIN`, so the
    write matches nothing after the password has already been verified. Rare,
    and reachable: an Administrator deleting an account at the moment its owner
    signs in. Left unhandled it is `User.model_validate(None)` and a 500 — the
    one answer this endpoint is built never to give, because it is an answer no
    other outcome produces and therefore a signal on its own.

    `_SignInVanished` is a bare `Exception` raised and caught inside one
    function, which makes it exactly the kind of thing a rename or a tidy-up
    silently disarms. Simulated by making the write match no row, which is what
    a deletion looks like to it.
    """
    monkeypatch.setattr(
        auth,
        "_RECORD_LOGIN",
        auth._RECORD_LOGIN.replace("WHERE id = %s", "WHERE id = %s AND false"),
    )
    account = make_user()

    response = client.post(LOGIN, json={"email": account.email, "password": account.password})

    # The one rejection, not a 500 and not a distinct code.
    assert response.status_code == 401
    assert response.json() == {"error": {"code": "unauthorized", "message": INVALID_CREDENTIALS}}
    assert "set-cookie" not in {k.lower() for k in response.headers}
    assert _sessions(conn, account.id) == []
    # And counted, like every other rejection — a path that did not count would
    # answer instantly at the tenth attempt while every other path answered 429.
    row = _attempt_row(conn, account.email)
    assert row is not None
    assert row["failure_count"] == 1
    # The transaction unwound cleanly: nothing was recorded on the account.
    recorded = conn.execute(
        "SELECT last_login_at FROM users WHERE id = %s", (account.id,)
    ).fetchone()
    assert recorded is not None
    assert recorded["last_login_at"] is None


def test_a_deactivated_account_and_an_expired_credential_are_counted_too(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser, instant: None
) -> None:
    # Every rejection path counts, not only the wrong-password one. A path that
    # did not count would answer instantly at the tenth attempt while every
    # other path answered 429 — the same oracle, reached from the other side.
    #
    # The corrupt-digest branch is here for that reason and not because a
    # corrupt digest is likely: it is the one rejection `api.auth` reaches from
    # an `except`, so it is the one most easily left behind by an edit, and an
    # account whose `password_hash` was damaged would then be the single address
    # in the product that never locks.
    deactivated = make_user(active=False)
    expired = make_user(
        must_change_password=True,
        temp_credential_expires_at=datetime.now(UTC) - timedelta(hours=1),
    )
    corrupt = make_user()
    conn.execute("UPDATE users SET password_hash = %s WHERE id = %s", ("not-a-digest", corrupt.id))

    for account in (deactivated, expired, corrupt):
        response = client.post(LOGIN, json={"email": account.email, "password": account.password})
        assert response.status_code == 401
        row = _attempt_row(conn, account.email)
        assert row is not None
        assert row["failure_count"] == 1


# --- AD-8's concurrency property ---------------------------------------------


def test_the_counter_survives_being_driven_from_two_connections(migrated_url: str) -> None:
    """One atomic increment-and-check, not a read followed by a write.

    Written against `record_failure` directly rather than through the endpoint,
    because what is being asserted is the statement, not the handler: twenty
    increments arriving on two connections at once must leave twenty, and a
    `SELECT` followed by an `UPDATE` would lose some of them without raising
    anything. AD-8 names exactly this — "a concurrent burst of requests each
    reading the same stale count before any of them writes back".

    An address with no account, so the mirror `UPDATE` matches nothing and the
    two threads cannot contend on a `users` row instead.
    """
    email_key = "nobody-concurrent@rocell.lk"
    per_thread = 10
    ready = threading.Barrier(2)
    # A worker that raises would otherwise surface as a barrier timeout in its
    # partner or as a count that is simply wrong, and the real failure — a
    # deadlock, a serialization error, a typo in the statement — would never be
    # printed. Collected and re-raised below, so the test fails saying what
    # actually happened.
    failures: list[BaseException] = []

    def drive() -> None:
        try:
            with psycopg.connect(migrated_url, autocommit=True, row_factory=dict_row) as conn:
                ready.wait(timeout=30)
                for _ in range(per_thread):
                    throttle.record_failure(conn, email_key)
        except BaseException as failure:  # noqa: BLE001 - re-raised on the main thread
            failures.append(failure)
            # Nothing is waiting on the barrier after this point except a
            # partner that would otherwise block for its full timeout.
            ready.abort()

    threads = [threading.Thread(target=drive) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
        assert not thread.is_alive()

    if failures:
        raise failures[0]

    with psycopg.connect(migrated_url, autocommit=True, row_factory=dict_row) as conn:
        row = conn.execute(
            "SELECT failure_count, locked_until FROM login_attempts WHERE email_key = %s",
            (email_key,),
        ).fetchone()

    assert row is not None
    assert row["failure_count"] == per_thread * 2
    assert row["locked_until"] > datetime.now(UTC)


# --- Failing in the safe direction -------------------------------------------


def test_a_failing_counter_write_leaves_the_rejection_intact(
    client: TestClient,
    make_user: MakeUser,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    instant: None,
) -> None:
    # A database fault must not make one attempt answer 500 while every other
    # answers 401 — that difference is the account-existence signal this
    # endpoint is built to remove. The attempt simply goes uncounted, and it is
    # logged, because a counter that never records anything is FR-4 silently
    # absent.
    def explode(*_: object, **__: object) -> None:
        raise psycopg.OperationalError("deadlock detected")

    monkeypatch.setattr(auth, "record_failure", explode)
    account = make_user()

    with caplog.at_level(logging.WARNING, logger="rocell.api.auth"):
        response = _fail(client, account.email)

    assert response.status_code == 401
    assert response.json()["error"]["message"] == INVALID_CREDENTIALS
    assert any(record.levelno == logging.WARNING for record in caplog.records)
    assert account.password not in caplog.text


def test_a_failing_sweep_leaves_the_rejection_intact(
    client: TestClient,
    conn: psycopg.Connection,
    make_user: MakeUser,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    instant: None,
) -> None:
    # Housekeeping does not get to fail the request it rides on — the same rule
    # `login`'s expired-session sweep already follows. Pointed at a relation
    # that does not exist, which is what a dropped or renamed table looks like
    # to a revision that shipped ahead of its migration.
    monkeypatch.setattr(
        throttle,
        "_SWEEP_ATTEMPTS",
        "DELETE FROM no_such_table WHERE last_failure_at <= now() - %s AND 1 = %s",
    )
    account = make_user()

    with caplog.at_level(logging.WARNING, logger="rocell.api.throttle"):
        response = _fail(client, account.email)

    assert response.status_code == 401
    assert any(record.levelno == logging.WARNING for record in caplog.records)
    # The failure was still counted: the sweep runs after the increment has
    # already committed on an autocommit connection.
    row = _attempt_row(conn, account.email)
    assert row is not None
    assert row["failure_count"] == 1


def test_a_failing_counter_clear_leaves_the_sign_in_standing(
    client: TestClient,
    conn: psycopg.Connection,
    make_user: MakeUser,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    instant: None,
) -> None:
    """The last counter write that could still have failed a request, and no longer can.

    `record_failure`, the status mirror and both sweeps swallow `psycopg.Error`
    so that a fault in the counter never decides the response. `clear_failures`
    runs inside the sign-in's own transaction, so unguarded it was the one
    exception: a statement timeout on that `DELETE` would have rolled the whole
    block back and answered 500 to a **correct** password — the endpoint's one
    forbidden answer, and on the single path where the caller has already proved
    who they are.

    Pointed at a relation that does not exist, which is what a dropped or
    renamed table looks like to a revision that shipped ahead of its migration,
    and which aborts the transaction for real rather than raising in Python —
    so this also proves the savepoint recovers a genuinely failed one.
    """
    account = make_user()
    _fail_times(client, account.email, 3)
    monkeypatch.setattr(
        throttle, "_CLEAR_ATTEMPTS", "DELETE FROM no_such_table WHERE email_key = %s"
    )

    with caplog.at_level(logging.WARNING, logger="rocell.api.auth"):
        response = client.post(LOGIN, json={"email": account.email, "password": account.password})

    assert response.status_code == 200
    assert SESSION_COOKIE_NAME in client.cookies
    # The session really committed — the savepoint unwound the delete alone.
    assert len(_sessions(conn, account.id)) == 1
    assert any(record.levelno == logging.WARNING for record in caplog.records)
    assert account.password not in caplog.text
    # And the count stands, which is where the unguarded version left it too:
    # the run is not forgotten, it is simply not cleared.
    row = _attempt_row(conn, account.email)
    assert row is not None
    assert row["failure_count"] == 3
