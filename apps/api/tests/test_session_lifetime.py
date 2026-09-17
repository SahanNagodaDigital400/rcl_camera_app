"""A session's two deadlines: the idle window, the absolute ceiling, and the slide.

Story 1.5's whole risk is in one sentence: **activity must never be able to
extend the 7-day bound.** The two are enforced from different columns —
`last_seen_at`, which authenticating writes, and `issued_at`, which nothing
writes — and `test_activity_cannot_outrun_the_absolute_ceiling` below is the
test that says so. Point the absolute condition at `expires_at` and everything
else here still passes.

Idle is driven by writing timestamps backwards in SQL, never by sleeping: a
suite that waits out a 12-hour window is a suite nobody runs.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest
from api import sessions as sessions_module
from api.sessions import (
    EXPIRED_SWEEP_LIMIT,
    SESSION_ABSOLUTE_LIFETIME,
    SESSION_COOKIE_NAME,
    SESSION_IDLE_TIMEOUT,
    SESSION_TOUCH_INTERVAL,
    delete_expired_sessions,
    hash_token,
    lookup_session,
    set_session_cookie,
)
from fastapi.testclient import TestClient
from starlette.responses import Response

LOGIN = "/auth/login"
SESSION = "/auth/session"

MakeUser = Callable[..., Any]


def _sign_in(client: TestClient, account: Any) -> str:
    response = client.post(LOGIN, json={"email": account.email, "password": account.password})
    assert response.status_code == 200
    return client.cookies[SESSION_COOKIE_NAME]


def _row(conn: psycopg.Connection, raw: str) -> dict[str, Any]:
    row = conn.execute(
        "SELECT * FROM sessions WHERE token_hash = %s", (hash_token(raw),)
    ).fetchone()
    assert row is not None
    return dict(row)


def _age(conn: psycopg.Connection, raw: str, **columns: timedelta) -> None:
    """Move one session's timestamps backwards. The only clock this suite uses."""
    for column, back in columns.items():
        # The column name is a literal from this module, never a value off the
        # wire, and the interval is a bound parameter — the guard in
        # `test_source_guards.py` is about interpolating *values*, and none is
        # interpolated here.
        if column == "last_seen_at":
            conn.execute(
                "UPDATE sessions SET last_seen_at = now() - %s WHERE token_hash = %s",
                (back, hash_token(raw)),
            )
        elif column == "issued_at":
            conn.execute(
                "UPDATE sessions SET issued_at = now() - %s WHERE token_hash = %s",
                (back, hash_token(raw)),
            )
        else:  # pragma: no cover - a typo in a test, not a product state
            raise AssertionError(f"_age does not know the column {column}")


# --- The idle window -------------------------------------------------------


def test_a_session_used_within_the_window_needs_no_re_authentication(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser
) -> None:
    # Just inside. The acceptance clause in as few moving parts as it has.
    account = make_user()
    raw = _sign_in(client, account)
    _age(conn, raw, last_seen_at=SESSION_IDLE_TIMEOUT - timedelta(minutes=5))

    assert client.get(SESSION).status_code == 200


def test_a_session_idle_past_the_window_is_refused(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser
) -> None:
    # Just outside, with the absolute bound still days away: this refusal can
    # only come from the idle condition.
    account = make_user()
    raw = _sign_in(client, account)
    _age(conn, raw, last_seen_at=SESSION_IDLE_TIMEOUT + timedelta(minutes=1))

    response = client.get(SESSION)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"
    assert _row(conn, raw)["expires_at"] > datetime.now(UTC) + timedelta(days=6)


def test_an_idle_refusal_clears_the_stale_cookie(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser
) -> None:
    # The same 401 every other dead session gets, headers included. A browser
    # left holding a cookie the server has stopped honouring pays for a lookup
    # on every request that can only fail.
    account = make_user()
    raw = _sign_in(client, account)
    _age(conn, raw, last_seen_at=SESSION_IDLE_TIMEOUT + timedelta(minutes=1))

    response = client.get(SESSION)

    header = response.headers["set-cookie"]
    assert header.startswith(f"{SESSION_COOKIE_NAME}=")
    assert "max-age=0" in header.lower()
    assert response.headers["www-authenticate"] == 'Session realm="rocell"'


def test_the_four_refusals_are_indistinguishable(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser
) -> None:
    # Four ways to be refused, one answer. A caller must not be able to tell an
    # idle session from a revoked one, an absolutely expired one, or one whose
    # owner has been deactivated.
    #
    # All four are staged, not the two that are cheapest to reach. The
    # acceptance clause names four, and they are indistinguishable today only
    # because every one of them ends at the same `not_signed_in()` — nothing
    # structural stops a later branch from wording its own refusal, and this is
    # what would notice.
    def _refused() -> tuple[int, Any]:
        response = client.get(SESSION)
        return response.status_code, response.json()

    idle_account = make_user()
    idle_raw = _sign_in(client, idle_account)
    _age(conn, idle_raw, last_seen_at=SESSION_IDLE_TIMEOUT + timedelta(minutes=1))
    idle = _refused()

    client.cookies.clear()
    revoked_account = make_user()
    revoked_raw = _sign_in(client, revoked_account)
    conn.execute("DELETE FROM sessions WHERE token_hash = %s", (hash_token(revoked_raw),))
    revoked = _refused()

    client.cookies.clear()
    expired_account = make_user()
    expired_raw = _sign_in(client, expired_account)
    # Only `issued_at` moves, so `expires_at` is still in the future and
    # `last_seen_at` is a moment old: this row is refused by the absolute
    # condition and by neither of the other two.
    _age(conn, expired_raw, issued_at=SESSION_ABSOLUTE_LIFETIME + timedelta(minutes=1))
    expired = _refused()

    client.cookies.clear()
    deactivated_account = make_user()
    _sign_in(client, deactivated_account)
    conn.execute("UPDATE users SET active = false WHERE id = %s", (deactivated_account.id,))
    deactivated = _refused()

    assert idle == revoked == expired == deactivated
    assert idle[0] == 401


def test_activity_slides_the_window_forward(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser
) -> None:
    # The matrix's "a request at hour 11, then another at hour 17". The second
    # is 17 hours after the session was issued and 6 after it was last used;
    # only the second measurement may decide it.
    #
    # `issued_at` is aged alongside `last_seen_at`, or the row would be seconds
    # old throughout and the "17 hours after the issue" half of the scenario —
    # the half that makes the case worth having — would never be staged.
    #
    # And the slide is asserted *between* the two requests. `_age` writes
    # `last_seen_at` absolutely, so without that assertion the second `200`
    # would be produced by this test's own UPDATE and the case would pass with
    # the touch deleted.
    account = make_user()
    raw = _sign_in(client, account)

    _age(conn, raw, issued_at=timedelta(hours=11), last_seen_at=timedelta(hours=11))
    assert client.get(SESSION).status_code == 200
    assert _row(conn, raw)["last_seen_at"] > datetime.now(UTC) - timedelta(minutes=1)

    # Six more hours pass. `_age` writes `last_seen_at` absolutely, so this
    # second stage is staged entirely by the test's own UPDATE and does not
    # carry the slide's write forward — it is the assertion above, between the
    # two requests, that proves the touch happened at all. What this half adds
    # is the other measurement: 17 hours after the issue, 6 since the last use,
    # and only the second of those may decide the request.
    _age(conn, raw, issued_at=timedelta(hours=17), last_seen_at=timedelta(hours=6))
    assert client.get(SESSION).status_code == 200


# --- The absolute ceiling --------------------------------------------------


def test_activity_cannot_outrun_the_absolute_ceiling(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser
) -> None:
    # **The test this story exists to make pass.** A session used continuously
    # for seven days: `last_seen_at` is a moment ago, so the idle bound is wide
    # open, and the only thing that can refuse it is the condition on
    # `issued_at`. Replace that condition with one on `expires_at` — the
    # column a sliding renewal would be tempted to write — and this is the
    # single assertion in the suite that notices.
    account = make_user()
    raw = _sign_in(client, account)

    conn.execute(
        "UPDATE sessions SET issued_at = now() - %s, expires_at = now() + %s, "
        "last_seen_at = now() WHERE token_hash = %s",
        (SESSION_ABSOLUTE_LIFETIME + timedelta(minutes=1), timedelta(days=7), hash_token(raw)),
    )

    assert client.get(SESSION).status_code == 401


def test_a_session_just_inside_the_ceiling_still_works(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser
) -> None:
    # The other side of the same boundary, so the test above cannot be passed
    # by a condition that refuses everything.
    account = make_user()
    raw = _sign_in(client, account)
    _age(conn, raw, issued_at=SESSION_ABSOLUTE_LIFETIME - timedelta(hours=1))

    assert client.get(SESSION).status_code == 200


def test_the_slide_never_writes_issued_at_or_expires_at(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser
) -> None:
    # Structural, and the reason the two bounds are two columns: whatever the
    # renewal does, the ceiling must be where it was. Asserted on the row
    # rather than on a status code, because a renewal that moved `expires_at`
    # would leave every status code in this file green.
    account = make_user()
    raw = _sign_in(client, account)
    before = _row(conn, raw)

    _age(conn, raw, last_seen_at=SESSION_TOUCH_INTERVAL + timedelta(seconds=1))
    assert client.get(SESSION).status_code == 200

    after = _row(conn, raw)
    assert after["issued_at"] == before["issued_at"]
    assert after["expires_at"] == before["expires_at"]
    assert after["last_seen_at"] > before["last_seen_at"]


# --- The throttle ----------------------------------------------------------


def test_a_burst_inside_the_touch_interval_writes_last_seen_at_once(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser
) -> None:
    # Authenticating is a read that occasionally writes, not a write per
    # request. Drop the `needs_touch` throttle and this is what notices: five
    # requests, five updates, five dead tuples.
    account = make_user()
    raw = _sign_in(client, account)
    _age(conn, raw, last_seen_at=SESSION_TOUCH_INTERVAL + timedelta(seconds=1))

    assert client.get(SESSION).status_code == 200
    touched = _row(conn, raw)["last_seen_at"]

    for _ in range(4):
        assert client.get(SESSION).status_code == 200

    assert _row(conn, raw)["last_seen_at"] == touched


def test_the_window_slides_again_once_the_interval_has_passed(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser
) -> None:
    # The throttle skips a write; it must not skip it forever, or the session
    # dies 12 hours after its first request however busy its owner was.
    account = make_user()
    raw = _sign_in(client, account)

    _age(conn, raw, last_seen_at=SESSION_TOUCH_INTERVAL + timedelta(seconds=1))
    client.get(SESSION)
    first = _row(conn, raw)["last_seen_at"]

    _age(conn, raw, last_seen_at=SESSION_TOUCH_INTERVAL + timedelta(seconds=1))
    client.get(SESSION)

    assert _row(conn, raw)["last_seen_at"] > first


class _RenewalRefusingConnection:
    """A connection that answers the lookup and refuses the renewal.

    The narrowest possible failure: the SELECT runs against the real database,
    the UPDATE raises. Patching `_touch_session` itself would prove nothing —
    the swallow lives *inside* it, so a raising stand-in would only show that
    `lookup_session` does not catch, which is exactly the opposite claim.
    """

    def __init__(self, real: psycopg.Connection) -> None:
        self._real = real
        self.refusals = 0

    def execute(self, statement: str, params: object = None) -> object:
        if statement.lstrip().upper().startswith("UPDATE"):
            self.refusals += 1
            raise psycopg.OperationalError("deadlock detected")
        return self._real.execute(statement, params)


def test_a_failing_renewal_does_not_fail_the_request(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser
) -> None:
    # The caller authenticated and the lookup succeeded. A tidy-up write that
    # cannot land must not turn a valid request into a 500 — it fails in the
    # safe direction, the window does not extend, and the session dies 12 hours
    # after its last successful touch. `login`'s sweep established this
    # handling for exactly this reason.
    account = make_user()
    raw = _sign_in(client, account)
    _age(conn, raw, last_seen_at=SESSION_TOUCH_INTERVAL + timedelta(seconds=1))
    before = _row(conn, raw)["last_seen_at"]
    refusing = _RenewalRefusingConnection(conn)

    user = lookup_session(refusing, raw)  # type: ignore[arg-type]

    assert user is not None
    assert user.email == account.email
    assert refusing.refusals == 1
    # The window did not move, which is the safe direction: the session dies
    # earlier than it might have, never later.
    assert _row(conn, raw)["last_seen_at"] == before


def test_a_failing_renewal_is_logged(
    client: TestClient,
    conn: psycopg.Connection,
    make_user: MakeUser,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Swallowed silently, a renewal that keeps failing is a product that signs
    # everyone out at lunchtime with nothing in the log to say why.
    account = make_user()
    raw = _sign_in(client, account)
    _age(conn, raw, last_seen_at=SESSION_TOUCH_INTERVAL + timedelta(seconds=1))

    with caplog.at_level("WARNING", logger=sessions_module.logger.name):
        assert lookup_session(_RenewalRefusingConnection(conn), raw) is not None  # type: ignore[arg-type]

    # Filtered to this module's logger rather than counting `caplog.records`
    # whole: the fixture's handler sits on the root logger and collects every
    # warning that propagates to it, so a warning from psycopg, the pool or any
    # future `rocell.api.*` logger raised during the same call would fail this
    # test for something that is not the renewal.
    renewals = [record for record in caplog.records if record.name == sessions_module.logger.name]
    assert len(renewals) == 1
    record = renewals[0]
    assert record.levelname == "WARNING"
    # A bare "WARNING" with no message and no traceback is the very outcome
    # this test's reason for existing says to prevent: an operator watching
    # everyone get signed out at lunchtime needs to be able to tell *what*
    # failed and *why* from the log alone.
    assert "renewal" in record.getMessage()
    assert record.exc_info is not None
    assert "deadlock detected" in caplog.text


def test_a_session_that_dies_between_the_read_and_the_touch_is_not_revived(
    conn: psycopg.Connection, make_user: MakeUser
) -> None:
    # The lookup reads, then writes, in two statements — so the row can die in
    # between. Without the liveness conditions repeated in the UPDATE,
    # `last_seen_at = now()` on a dead row is a resurrection.
    account = make_user()
    conn.execute(
        "INSERT INTO sessions (user_id, token_hash, expires_at, last_seen_at) "
        "VALUES (%s, %s, now() - %s, now() - %s)",
        (
            account.id,
            hash_token("already-dead"),
            timedelta(seconds=1),
            SESSION_TOUCH_INTERVAL + timedelta(seconds=1),
        ),
    )
    row = conn.execute(
        "SELECT id FROM sessions WHERE token_hash = %s", (hash_token("already-dead"),)
    ).fetchone()
    assert row is not None
    before = conn.execute(
        "SELECT last_seen_at FROM sessions WHERE id = %s", (row["id"],)
    ).fetchone()
    assert before is not None

    sessions_module._touch_session(conn, row["id"])

    after = conn.execute("SELECT last_seen_at FROM sessions WHERE id = %s", (row["id"],)).fetchone()
    assert after is not None
    assert after["last_seen_at"] == before["last_seen_at"]
    assert lookup_session(conn, "already-dead") is None


# --- The sweep -------------------------------------------------------------


def test_the_sweep_clears_idle_dead_rows_too(conn: psycopg.Connection, make_user: MakeUser) -> None:
    # An idle-dead row is as unusable as an expired one. Swept only on
    # `expires_at`, it would occupy the table for the rest of its seven days.
    account = make_user()
    conn.execute(
        "INSERT INTO sessions (user_id, token_hash, expires_at, last_seen_at) "
        "VALUES (%s, %s, now() + %s, now() - %s)",
        (
            account.id,
            hash_token("idle-dead"),
            SESSION_ABSOLUTE_LIFETIME,
            SESSION_IDLE_TIMEOUT + timedelta(minutes=1),
        ),
    )
    conn.execute(
        "INSERT INTO sessions (user_id, token_hash, expires_at) VALUES (%s, %s, now() + %s)",
        (account.id, hash_token("alive"), SESSION_ABSOLUTE_LIFETIME),
    )

    assert delete_expired_sessions(conn) == 1

    left = conn.execute("SELECT token_hash FROM sessions").fetchall()
    assert [row["token_hash"] for row in left] == [hash_token("alive")]


def test_the_sweep_stays_bounded_with_idle_dead_rows_in_the_table(
    conn: psycopg.Connection, make_user: MakeUser
) -> None:
    # Widening the WHERE must not widen what one sign-in pays for.
    account = make_user()
    dead = EXPIRED_SWEEP_LIMIT + 5
    with conn.transaction():
        for index in range(dead):
            conn.execute(
                "INSERT INTO sessions (user_id, token_hash, expires_at, last_seen_at) "
                "VALUES (%s, %s, now() + %s, now() - %s)",
                (
                    account.id,
                    hash_token(f"idle-{index}"),
                    SESSION_ABSOLUTE_LIFETIME,
                    SESSION_IDLE_TIMEOUT + timedelta(minutes=1),
                ),
            )

    assert delete_expired_sessions(conn) == EXPIRED_SWEEP_LIMIT

    left = conn.execute("SELECT count(*) AS n FROM sessions").fetchone()
    assert left is not None
    assert left["n"] == dead - EXPIRED_SWEEP_LIMIT


# --- The cookie ------------------------------------------------------------


def test_the_cookie_helper_sets_every_attribute_itself() -> None:
    # Asserted on the helper, not only on a login response. Two paths set this
    # cookie today (`login` and the forced change) and Story 1.7 will add a
    # third; a helper whose own attribute set is pinned cannot drift from
    # whichever caller a future test forgets to cover.
    #
    # `Max-Age` is the **absolute** lifetime, never the idle window: the idle
    # bound is a condition on a row, and a cookie discarded at 12 hours would
    # sign out a session the server is still honouring.
    response = Response()

    set_session_cookie(response, "a-raw-token")

    header = response.headers["set-cookie"].lower()
    assert header.startswith(f"{SESSION_COOKIE_NAME}=")
    assert "httponly" in header
    assert "secure" in header
    assert "samesite=strict" in header
    assert "path=/" in header
    assert f"max-age={int(SESSION_ABSOLUTE_LIFETIME.total_seconds())}" in header
    assert f"max-age={int(SESSION_IDLE_TIMEOUT.total_seconds())}" not in header


def test_the_two_bounds_are_the_figures_fr_3_names() -> None:
    # Written with literals rather than derived from the constants, for the
    # same reason `test_the_session_lifetime_is_the_week_the_addendum_specifies`
    # is: every other assertion here takes its expectation from the constant, so
    # shortening either bound would leave the suite green while staff are signed
    # out on a schedule nobody chose.
    assert SESSION_IDLE_TIMEOUT == timedelta(hours=12)
    assert SESSION_ABSOLUTE_LIFETIME == timedelta(days=7)
    # Pinned to its literal for the same reason, not merely asserted to be
    # smaller than the window: `< SESSION_IDLE_TIMEOUT` is satisfied by eleven
    # hours, which would make "at most one write a minute" — the claim three
    # files make about what authenticating costs — false with the whole suite
    # green. The constant's own docstring names raising it towards the window
    # as the way this goes wrong.
    assert SESSION_TOUCH_INTERVAL == timedelta(minutes=1)
    assert SESSION_TOUCH_INTERVAL < SESSION_IDLE_TIMEOUT
