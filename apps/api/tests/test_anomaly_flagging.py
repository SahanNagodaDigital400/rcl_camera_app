"""Story 3.7 — FR-22's per-user, per-signal anomaly baseline, AD-8's counter
shape a third time.

Driven against a real PostgreSQL for `test_scan_rate_limiting.py`'s own
reason: `anomaly.check_and_flag` is one atomic `INSERT ... ON CONFLICT DO
UPDATE ... RETURNING`, and the only honest way to prove a rollover and a
deviation check behave correctly under a real row lock is to run them
against one.

Two of `test_scan_rate_limiting.py`'s own techniques carry over unchanged:
backdating `window_started_at` directly in the database to force a stale
window without a real sleep (the default window is one day), and
`monkeypatch.setattr`/`importlib.reload` against the module's own constants
for the env-var round trip.

This file tests `anomaly.check_and_flag` directly, at the unit boundary —
`test_audit_login_events.py` and `test_scan_submission.py` carry the one
behavioral test each proving the real routes are wired to it and that a flag
never blocks the request that produced it.
"""

from __future__ import annotations

import importlib
import logging
import threading
from collections.abc import Callable
from datetime import timedelta
from typing import Any

import psycopg
import pytest
from api import anomaly
from psycopg.rows import dict_row

MakeUser = Callable[..., Any]


def _row(conn: psycopg.Connection, user_id: Any, signal: str) -> dict[str, Any] | None:
    return conn.execute(
        "SELECT * FROM anomaly_baseline WHERE user_id = %s AND signal = %s",
        (user_id, signal),
    ).fetchone()


def _go_stale(conn: psycopg.Connection, user_id: Any, signal: str) -> None:
    """Backdate this row's window past `ANOMALY_BASELINE_WINDOW`.

    `test_scan_rate_limiting.py`'s own technique — a real sleep is not an
    option at the default one-day window.
    """
    conn.execute(
        "UPDATE anomaly_baseline SET window_started_at = now() - %s "
        "WHERE user_id = %s AND signal = %s",
        (timedelta(seconds=anomaly.ANOMALY_BASELINE_WINDOW + 60), user_id, signal),
    )


def _seed_average(conn: psycopg.Connection, user_id: Any, signal: str, count: int) -> None:
    """`count` attempts in one window, then a rollover.

    Leaves `baseline_average == count` and a fresh window sitting at 1 — the
    "no rollover result is ever a deviation" property `check_and_flag`'s own
    docstring names.
    """
    for _ in range(count):
        assert anomaly.check_and_flag(conn, user_id, signal) is False
    _go_stale(conn, user_id, signal)
    assert anomaly.check_and_flag(conn, user_id, signal) is False

    row = _row(conn, user_id, signal)
    assert row is not None
    assert row["baseline_average"] == pytest.approx(count)
    assert row["window_count"] == 1


# --- No baseline yet -----------------------------------------------------------


def test_the_first_ever_call_creates_a_row_and_reports_no_deviation(
    conn: psycopg.Connection, make_user: MakeUser
) -> None:
    account = make_user()

    assert anomaly.check_and_flag(conn, account.id, "login") is False

    row = _row(conn, account.id, "login")
    assert row is not None
    assert row["window_count"] == 1
    assert row["baseline_average"] is None


# --- Baseline seeded, under and past the deviation -----------------------------


def test_a_window_at_or_under_the_deviation_reports_false(
    conn: psycopg.Connection, make_user: MakeUser
) -> None:
    account = make_user()
    _seed_average(conn, account.id, "scan", 2)
    threshold = 2 * anomaly.ANOMALY_DEVIATION_MULTIPLIER

    count = 1
    while count < threshold:
        count += 1
        assert anomaly.check_and_flag(conn, account.id, "scan") is False

    row = _row(conn, account.id, "scan")
    assert row is not None
    assert row["window_count"] == count


def test_a_window_past_the_deviation_reports_true(
    conn: psycopg.Connection, make_user: MakeUser
) -> None:
    account = make_user()
    _seed_average(conn, account.id, "scan", 2)
    threshold = 2 * anomaly.ANOMALY_DEVIATION_MULTIPLIER

    count = 1
    result = False
    while not result:
        count += 1
        result = anomaly.check_and_flag(conn, account.id, "scan")

    assert count > threshold
    row = _row(conn, account.id, "scan")
    assert row is not None
    assert row["window_count"] == count


# --- The window rolls over ------------------------------------------------------


def test_a_second_rollover_averages_the_old_average_and_the_elapsed_count(
    conn: psycopg.Connection, make_user: MakeUser
) -> None:
    account = make_user()
    _seed_average(conn, account.id, "login", 4)  # baseline_average == 4

    # Two more attempts in the fresh window: window_count 2, then 3.
    for _ in range(2):
        assert anomaly.check_and_flag(conn, account.id, "login") is False

    _go_stale(conn, account.id, "login")
    result = anomaly.check_and_flag(conn, account.id, "login")

    assert result is False  # a rollover's own reset count is never a deviation
    row = _row(conn, account.id, "login")
    assert row is not None
    assert row["baseline_average"] == pytest.approx((4 + 3) / 2)
    assert row["window_count"] == 1


# --- Independence ----------------------------------------------------------------


def test_two_signals_for_one_user_are_independent(
    conn: psycopg.Connection, make_user: MakeUser
) -> None:
    account = make_user()
    _seed_average(conn, account.id, "login", 2)

    # The scan signal for the same user has never been touched.
    assert anomaly.check_and_flag(conn, account.id, "scan") is False
    scan_row = _row(conn, account.id, "scan")
    assert scan_row is not None
    assert scan_row["baseline_average"] is None

    login_row = _row(conn, account.id, "login")
    assert login_row is not None
    assert login_row["baseline_average"] == pytest.approx(2)


def test_one_users_burst_does_not_affect_another(
    conn: psycopg.Connection, make_user: MakeUser
) -> None:
    bursting = make_user()
    quiet = make_user()
    _seed_average(conn, bursting.id, "scan", 2)
    _seed_average(conn, quiet.id, "scan", 2)
    threshold = 2 * anomaly.ANOMALY_DEVIATION_MULTIPLIER

    result = False
    count = 1
    while not result:
        count += 1
        result = anomaly.check_and_flag(conn, bursting.id, "scan")
    assert count > threshold

    # The quiet user's own baseline is untouched by the other's burst.
    assert anomaly.check_and_flag(conn, quiet.id, "scan") is False
    quiet_row = _row(conn, quiet.id, "scan")
    assert quiet_row is not None
    assert quiet_row["window_count"] == 2


# --- Signal vocabulary -----------------------------------------------------------


def test_an_unrecognised_signal_is_a_programming_error(
    conn: psycopg.Connection, make_user: MakeUser
) -> None:
    # `ValueError`, not a bare `assert` — an `assert` compiles out entirely
    # under `-O`/`PYTHONOPTIMIZE`, which would let an unvalidated signal reach
    # `_CHECK_AND_FLAG` and fail as a raw, unhandled `CheckViolation` instead.
    account = make_user()

    with pytest.raises(ValueError, match="not-a-real-signal"):
        anomaly.check_and_flag(conn, account.id, "not-a-real-signal")


# --- The env-var override, at the unit level --------------------------------------


def test_the_window_and_multiplier_env_vars_are_read_once_at_import(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(anomaly.ANOMALY_BASELINE_WINDOW_ENV, "120")
    monkeypatch.setenv(anomaly.ANOMALY_DEVIATION_MULTIPLIER_ENV, "5.5")
    try:
        reloaded = importlib.reload(anomaly)
        assert reloaded.ANOMALY_BASELINE_WINDOW == pytest.approx(120)
        assert reloaded.ANOMALY_DEVIATION_MULTIPLIER == pytest.approx(5.5)
    finally:
        monkeypatch.delenv(anomaly.ANOMALY_BASELINE_WINDOW_ENV, raising=False)
        monkeypatch.delenv(anomaly.ANOMALY_DEVIATION_MULTIPLIER_ENV, raising=False)
        importlib.reload(anomaly)


@pytest.mark.parametrize("raw", ["not-a-number", "nan", "inf", "-inf", "-5", "1e20"])
def test_an_invalid_window_falls_back_to_the_default(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, raw: str
) -> None:
    """`scan_throttle._read_window`'s exact shape: unparseable, non-finite and
    negative values must all fall back rather than reach the SQL below with a
    window that could never resolve, and `1e20` is only rejected because
    `timedelta(seconds=1e20)` itself overflows.
    """
    monkeypatch.setenv(anomaly.ANOMALY_BASELINE_WINDOW_ENV, raw)
    try:
        with caplog.at_level(logging.WARNING, logger="rocell.api.anomaly"):
            reloaded = importlib.reload(anomaly)

        assert reloaded.ANOMALY_BASELINE_WINDOW == reloaded.DEFAULT_ANOMALY_BASELINE_WINDOW
        assert any(raw in record.getMessage() for record in caplog.records)
    finally:
        monkeypatch.delenv(anomaly.ANOMALY_BASELINE_WINDOW_ENV, raising=False)
        importlib.reload(anomaly)


@pytest.mark.parametrize("raw", ["not-a-number", "nan", "inf", "-inf", "-5", "0"])
def test_an_invalid_multiplier_falls_back_to_the_default(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, raw: str
) -> None:
    """A negative multiplier would flag every window with any activity at all
    from a plain operator typo, silently turning every sign-in and scan into
    a reviewed anomaly — so it falls back exactly as an unparseable or
    non-finite value does.

    **`"0"` is the boundary case, not a filler entry.** It parses cleanly as
    an ordinary non-negative float, so without the strict `> 0` check this
    value would sail through validation and then make `check_and_flag`
    return `True` on virtually every request once any baseline exists at
    all — `window_count > baseline_average * 0` is just `window_count > 0`.
    """
    monkeypatch.setenv(anomaly.ANOMALY_DEVIATION_MULTIPLIER_ENV, raw)
    try:
        with caplog.at_level(logging.WARNING, logger="rocell.api.anomaly"):
            reloaded = importlib.reload(anomaly)

        assert (
            reloaded.ANOMALY_DEVIATION_MULTIPLIER == reloaded.DEFAULT_ANOMALY_DEVIATION_MULTIPLIER
        )
        assert any(raw in record.getMessage() for record in caplog.records)
    finally:
        monkeypatch.delenv(anomaly.ANOMALY_DEVIATION_MULTIPLIER_ENV, raising=False)
        importlib.reload(anomaly)


def test_a_missing_env_var_uses_the_documented_default() -> None:
    assert anomaly.ANOMALY_BASELINE_WINDOW == anomaly.DEFAULT_ANOMALY_BASELINE_WINDOW
    assert anomaly.ANOMALY_DEVIATION_MULTIPLIER == anomaly.DEFAULT_ANOMALY_DEVIATION_MULTIPLIER


# --- AD-8's concurrency property ---------------------------------------------------


def test_the_counter_survives_being_driven_from_two_connections(
    migrated_url: str, conn: psycopg.Connection, make_user: MakeUser
) -> None:
    """One atomic increment-and-check, not a read followed by a write.

    `test_scan_rate_limiting.py`'s own concurrency test, restated against
    `anomaly.check_and_flag` directly: twenty increments arriving on two
    connections at once must leave twenty, and a `SELECT` followed by an
    `UPDATE` would lose some of them without raising anything.
    """
    account = make_user()
    per_thread = 10
    ready = threading.Barrier(2)
    failures: list[BaseException] = []

    def drive() -> None:
        try:
            with psycopg.connect(
                migrated_url, autocommit=True, row_factory=dict_row
            ) as thread_conn:
                ready.wait(timeout=30)
                for _ in range(per_thread):
                    anomaly.check_and_flag(thread_conn, account.id, "login")
        except BaseException as failure:  # noqa: BLE001 - re-raised on the main thread
            failures.append(failure)
            ready.abort()

    threads = [threading.Thread(target=drive) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
        assert not thread.is_alive()

    if failures:
        raise failures[0]

    row = _row(conn, account.id, "login")
    assert row is not None
    assert row["window_count"] == per_thread * 2
