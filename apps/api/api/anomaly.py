"""FR-22's per-user anomaly baseline: the one module that writes `anomaly_baseline`.

AD-8 fixes two things about a counter, and this is the third instance of the
pattern in this codebase — `login_attempts` (`api/throttle.py`) and
`scan_rate_limit` (`api/scan_throttle.py`) are the other two. A counter is:

* a **row in Postgres**, not in-process memory — it survives a restart and a
  second `apps/api` instance; and
* mutated by **one atomic increment-and-check**, never a read followed by a
  write of a value derived from that read. `_CHECK_AND_FLAG` below is a
  single `INSERT ... ON CONFLICT DO UPDATE ... RETURNING` that rolls a
  fixed window's count into a running per-user average, resets-or-increments
  the current window, and hands back what it just wrote — so two attempts
  arriving together are serialised by the row lock and neither reads a stale
  count.

`tests/test_source_guards.py` holds the mutation to this one file, the way it
already does for `login_attempts` and `scan_rate_limit`: an `INSERT`,
`UPDATE` or `DELETE` against `anomaly_baseline` anywhere but here fails the
suite.

**One shared table, discriminated by `signal`, not two near-identical
tables.** `login_attempts` and `scan_rate_limit` are separate tables because
they gate two different *resources* with two different shapes. Here both
signals — a successful sign-in and a scan submission — are the same shape end
to end: same columns, same statement, same config. `signal IN ('login',
'scan')` keeps `PRIMARY KEY (user_id, signal)` giving every AD-8 property (one
atomic statement per check, no cross-signal interference) without writing the
module twice.

**This module never writes the audit log, and never decides to.**
`check_and_flag` reports a boolean — whether the current window already
exceeds the baseline by more than `ANOMALY_DEVIATION_MULTIPLIER` — exactly as
`scan_throttle.check_and_record` reports whether the caller is over the rate
limit. The caller (`api.auth`, `api.scan`) decides whether a `True` result
becomes an `audit.record(...)` call. This module does not import `AuditAction`
and does not name the append-only audit table anywhere in its source — a fact
`test_source_guards.py` can assert directly, because the whole point of the
split is that a boolean cannot become a written entry by accident on this
side of the call.

**A flag never blocks.** Unlike `scan_throttle.check_and_record`, whose `True`
refuses the request, a `True` from `check_and_flag` changes nothing about
whether the login or scan proceeds — epics.md's own wording is "distinct from
and in addition to" Story 3.6's hard throttle. Both signals are checked on
*every* attempt, independent of each other and of the attempt's own outcome:
a throttled scan burst is still counted toward the volume baseline, and a
flagged-but-unthrottled burst still proceeds.

**`ANOMALY_BASELINE_WINDOW` and `ANOMALY_DEVIATION_MULTIPLIER` are documented,
uncalibrated placeholders**, read once at import, `scan_throttle.py`'s own
`_read_rate_limit`/`_read_window` shape (itself copied from
`scan_throttle`): PRD OQ-13 explicitly defers the real
numbers to the Foundation build and the Phase 2 pilot. Both constants are
shared across the two signals — epics.md's AC names one baseline window and
one deviation, not four.

**Not here.** The failed-login counter (`login_attempts`, FR-4) and the scan
throttle (`scan_rate_limit`, FR-23) are the other two AD-8 counters and are
not this module's statement with a different table name — three separate
tables, three separate owners, `api/throttle.py`'s own "Not here" precedent
for why one is never generalised into another.
"""

from __future__ import annotations

import logging
import math
import os
from datetime import timedelta
from uuid import UUID

import psycopg

#: Named as `api.scan_throttle`'s own logger is — an explicit `rocell.` prefix
#: rather than `__name__` — so a deployment can filter or raise the level of
#: every `rocell.*` logger with one rule.
logger = logging.getLogger("rocell.api.anomaly")

#: The environment variable that overrides `DEFAULT_ANOMALY_BASELINE_WINDOW`.
#: Changing it requires a process restart to take effect (read once, below,
#: `shared_vision.pipeline.GREY_WORLD`'s own pattern) — never a per-request re-read.
ANOMALY_BASELINE_WINDOW_ENV = "TILEMATCH_ANOMALY_BASELINE_WINDOW_SECONDS"

#: A documented, uncalibrated placeholder, in seconds — one day. PRD OQ-13
#: defers the real number to the Foundation build and the Phase 2 pilot, the
#: same bucket FR-9's blur bound and FR-23's rate limit are in.
DEFAULT_ANOMALY_BASELINE_WINDOW = 86400.0

#: The environment variable that overrides `DEFAULT_ANOMALY_DEVIATION_MULTIPLIER`.
#: Same read-once-at-import rule as the window above.
ANOMALY_DEVIATION_MULTIPLIER_ENV = "TILEMATCH_ANOMALY_DEVIATION_MULTIPLIER"

#: A documented, uncalibrated placeholder — a window's count more than three
#: times a user's own historical average is flagged for review. Not a
#: measured number; PRD OQ-13's own bucket.
DEFAULT_ANOMALY_DEVIATION_MULTIPLIER = 3.0

#: The two signals this module understands. `anomaly_baseline.signal` carries
#: the database's own copy of this constraint (`CHECK (signal IN ('login',
#: 'scan'))`); this is the application's.
_SIGNALS = ("login", "scan")


def _read_window() -> float:
    """`ANOMALY_BASELINE_WINDOW_ENV`'s value, falling back to the default.

    `scan_throttle._read_window`'s exact shape: a value `float()` cannot
    parse, or one that parses to something non-finite (`nan`, `inf`, `-inf`
    are all valid input to `float()` with no error at all), falls back to the
    default rather than reaching the SQL below with a window that could never
    resolve. A negative window is rejected the same way — "a non-negative
    number of seconds" is the whole of what this value may be.

    A value so large that `timedelta(seconds=value)` cannot represent it is
    rejected too — `check_and_flag` builds exactly that `timedelta` on every
    call, and an unguarded operator typo like `1e20` would turn every sign-in
    and scan submission into an unhandled `OverflowError` for as long as the
    variable stayed set, rather than a single logged fallback at import.
    """
    raw = os.environ.get(ANOMALY_BASELINE_WINDOW_ENV)
    if raw is None:
        return DEFAULT_ANOMALY_BASELINE_WINDOW

    try:
        value = float(raw)
    except ValueError:
        logger.warning(
            "%s=%r is not a number; using the default window (%s) instead",
            ANOMALY_BASELINE_WINDOW_ENV,
            raw,
            DEFAULT_ANOMALY_BASELINE_WINDOW,
        )
        return DEFAULT_ANOMALY_BASELINE_WINDOW

    if not math.isfinite(value) or value < 0:
        logger.warning(
            "%s=%r is not a non-negative finite number; using the default window (%s) instead",
            ANOMALY_BASELINE_WINDOW_ENV,
            raw,
            DEFAULT_ANOMALY_BASELINE_WINDOW,
        )
        return DEFAULT_ANOMALY_BASELINE_WINDOW

    try:
        timedelta(seconds=value)
    except OverflowError:
        logger.warning(
            "%s=%r is too large to use as a time window; using the default window (%s) instead",
            ANOMALY_BASELINE_WINDOW_ENV,
            raw,
            DEFAULT_ANOMALY_BASELINE_WINDOW,
        )
        return DEFAULT_ANOMALY_BASELINE_WINDOW

    return value


def _read_multiplier() -> float:
    """`ANOMALY_DEVIATION_MULTIPLIER_ENV`'s value, falling back to the default.

    Same shape as `_read_window`, minus the `timedelta` overflow guard — the
    multiplier is never built into a `timedelta`, only multiplied against a
    `baseline_average` in SQL, so there is no equivalent unbounded-construction
    hazard to guard against.

    **Strictly positive, not merely non-negative** — `scan_throttle.
    _read_rate_limit`'s own boundary, for the identical class of bug. `0`
    passes an ordinary non-negative check cleanly, and `window_count >
    baseline_average * 0` is `window_count > 0`: once any baseline exists at
    all, `check_and_flag` returns `True` on virtually every subsequent
    attempt, silently turning the feature into "flag everything" from a
    single operator typo. A negative value is rejected for the same reason
    `_read_window` rejects one: it isn't a value this parameter can mean.
    """
    raw = os.environ.get(ANOMALY_DEVIATION_MULTIPLIER_ENV)
    if raw is None:
        return DEFAULT_ANOMALY_DEVIATION_MULTIPLIER

    try:
        value = float(raw)
    except ValueError:
        logger.warning(
            "%s=%r is not a number; using the default multiplier (%s) instead",
            ANOMALY_DEVIATION_MULTIPLIER_ENV,
            raw,
            DEFAULT_ANOMALY_DEVIATION_MULTIPLIER,
        )
        return DEFAULT_ANOMALY_DEVIATION_MULTIPLIER

    if not math.isfinite(value) or value <= 0:
        logger.warning(
            "%s=%r is not a positive finite number; using the default multiplier (%s) instead",
            ANOMALY_DEVIATION_MULTIPLIER_ENV,
            raw,
            DEFAULT_ANOMALY_DEVIATION_MULTIPLIER,
        )
        return DEFAULT_ANOMALY_DEVIATION_MULTIPLIER

    return value


#: The window `check_and_flag` measures against. Read once at import — exactly
#: `scan_throttle.SCAN_RATE_LIMIT_WINDOW`'s own pattern — so the value in
#: effect for the life of a process is fixed at start-up.
ANOMALY_BASELINE_WINDOW = _read_window()

#: The deviation `check_and_flag` compares the current window's count against
#: — `baseline_average * ANOMALY_DEVIATION_MULTIPLIER`. Read once at import,
#: the same way.
ANOMALY_DEVIATION_MULTIPLIER = _read_multiplier()

#: `window_started_at` older than the window means the run this row records
#: has ended. `scan_rate_limit._WINDOW_STALE`'s own fragment.
_WINDOW_STALE = "anomaly_baseline.window_started_at <= now() - %s"

#: AD-8's single atomic increment-and-check, and the only statement in the
#: product that writes `anomaly_baseline`.
#:
#: One statement decides everything at once, from the row as it is locked for
#: update, not from a value read a moment ago by some other request:
#:
#: * on the **first-ever** call for a `(user_id, signal)` pair, the `INSERT`
#:   branch fires: `window_count` starts at 1, `baseline_average` stays NULL
#:   (nothing to compare against yet).
#: * on an **ordinary** call within a live window, the count increments and
#:   the average is untouched.
#: * on a call that finds the window **stale**, the just-elapsed window's count
#:   rolls into the average — the average of the old average and that count,
#:   or the count itself if this is the first rollover (`COALESCE`) — and
#:   `window_count` resets to 1 for the fresh window.
#:
#:
#: `RETURNING` hands back the row exactly as written, so `check_and_flag`
#: never re-reads and never guesses.
_CHECK_AND_FLAG = f"""
INSERT INTO anomaly_baseline (user_id, signal, window_count, window_started_at, baseline_average)
VALUES (%s, %s, 1, now(), NULL)
ON CONFLICT (user_id, signal) DO UPDATE
   SET window_count = CASE WHEN {_WINDOW_STALE} THEN 1
                           ELSE anomaly_baseline.window_count + 1 END,
       window_started_at = CASE WHEN {_WINDOW_STALE} THEN now()
                                ELSE anomaly_baseline.window_started_at END,
       baseline_average = CASE WHEN {_WINDOW_STALE} THEN
                                   COALESCE(
                                       (anomaly_baseline.baseline_average
                                            + anomaly_baseline.window_count) / 2.0,
                                       anomaly_baseline.window_count
                                   )
                               ELSE anomaly_baseline.baseline_average END
RETURNING window_count, baseline_average
"""


def check_and_flag(conn: psycopg.Connection, user_id: UUID, signal: str) -> bool:
    """Count one attempt for `(user_id, signal)` and report whether it deviates.

    `signal` is `"login"` or `"scan"` — anything else is a programming error
    in the caller, not a value that can arrive from outside this process, so
    it is rejected with a raised `ValueError` rather than mapped to a
    refusal. Not a bare `assert`: that statement compiles out entirely under
    `-O`/`PYTHONOPTIMIZE`, which would let an unvalidated signal reach
    `_CHECK_AND_FLAG` and fail as a raw, unhandled `CheckViolation` — a bare
    500 — instead of the clear "programming error" this docstring promises.

    `True` means the *current* window's count already exceeds
    `baseline_average * ANOMALY_DEVIATION_MULTIPLIER`. `False` covers three
    cases the caller does not need to tell apart: there is no baseline yet
    (nothing to compare against), the count is within the deviation, or the
    window just rolled over (the fresh window's count of 1 is never a
    deviation against any positive average).

    **Never writes the audit log and never imports `AuditAction`.** The caller
    decides whether a `True` result becomes a written flag — see the module
    docstring.

    Reads `ANOMALY_BASELINE_WINDOW`/`ANOMALY_DEVIATION_MULTIPLIER` through the
    module rather than capturing them as default arguments, so a test can
    lower either one with `monkeypatch.setattr` and see it take effect on the
    very next call.
    """
    if signal not in _SIGNALS:
        raise ValueError(f"unknown anomaly signal: {signal!r}")

    window = timedelta(seconds=ANOMALY_BASELINE_WINDOW)
    # `_WINDOW_STALE` appears three times in `_CHECK_AND_FLAG` — once per
    # `CASE` (`window_count`, `window_started_at`, `baseline_average`) — and
    # each occurrence is its own `%s` placeholder, so the window is passed
    # three times, `scan_throttle.check_and_record`'s own reason for passing
    # it twice against its own two-`CASE` statement.
    row = conn.execute(_CHECK_AND_FLAG, (user_id, signal, window, window, window)).fetchone()
    if row is None:  # pragma: no cover - both upsert branches produce a row
        # Unreachable: `ON CONFLICT DO UPDATE ... RETURNING` yields a row on
        # the insert branch and on the update branch alike. Answered as "no
        # deviation" rather than by raising, so a login or scan already on its
        # way to succeeding is never turned into a 500 by this defensive
        # branch never actually being hit.
        return False

    baseline_average = row["baseline_average"]
    if baseline_average is None:
        # No baseline yet — the I/O matrix's own "nothing to compare against"
        # row. This includes the very call that just wrote the first row.
        return False

    return row["window_count"] > baseline_average * ANOMALY_DEVIATION_MULTIPLIER
