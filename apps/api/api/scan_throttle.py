"""FR-23's per-user scan throttle: the one module that writes `scan_rate_limit`.

AD-8 fixes two things about a rate-limit counter, and `login_attempts`
(`api/throttle.py`) already ships the first instance of the pattern in this
codebase. This is the second, independent one — a counter is:

* a **row in Postgres**, not in-process memory — it survives a restart and a
  second `apps/api` instance; and
* mutated by **one atomic increment-and-check**, never a read followed by a
  write of a value derived from that read. `_CHECK_AND_RECORD` below is a
  single `INSERT ... ON CONFLICT DO UPDATE ... RETURNING` that resets-or-
  increments a fixed window and hands back the new count. Two submissions
  arriving together are therefore serialised by the row lock, and neither can
  read a stale count and blow past the limit.

`tests/test_source_guards.py` holds the mutation to this one file, the way it
already does for `login_attempts`: an `INSERT`, `UPDATE` or `DELETE` against
`scan_rate_limit` anywhere but here fails the suite.

**Keyed on `user_id`, and a real foreign key — unlike `login_attempts`.**
`POST /scans` sits behind `require_claimed_user` (`api/dependencies.py`): by
the time this check runs, the caller is already a resolved, authenticated
account. `login_attempts` is keyed on the address *as submitted* because
`POST /auth/login` has to answer an unknown address and a real one
identically — there is no equivalent oracle here to protect, so the simpler,
correct key is the real `user_id`, `scan.user_id`'s own precedent.

**A fixed window, not a sliding one or a token bucket.** `login_attempts`
already established the fixed-window-with-reset shape for an AD-8 counter
(`ATTEMPT_WINDOW`, reset when a run is stale) and nothing here asks for
anything smoother — a second counter shape for the same architectural
decision would be complexity with no requirement behind it.

**`SCAN_RATE_LIMIT` and `SCAN_RATE_LIMIT_WINDOW` are documented, uncalibrated
placeholders**, read once at import, `pipeline.GREY_WORLD`'s
own pattern: PRD OQ-13 explicitly defers the real numbers to the Foundation
build and the Phase 2 pilot, grouped with FR-9's blur bound as the same
bucket of "calibrated later" thresholds. A runtime env read per request would
let the bound drift mid-process, which is not what "a process restart picks
up the new value" asks for.

**Not here.** The failed-login counter (`login_attempts`, FR-4) and the
anomaly baseline (FR-22, Story 3.7) are the other two AD-8 counters and are
not this module's statements with a different table name — three separate
tables, three separate owners, `api/throttle.py`'s own "Not here" precedent
for why one is never generalised into another before a second caller needs it.
"""

from __future__ import annotations

import logging
import math
import os
from datetime import timedelta
from uuid import UUID

import psycopg

#: Named as `api.throttle`'s own logger is — an explicit `rocell.` prefix
#: rather than `__name__` — so a deployment can filter or raise the level of
#: every `rocell.*` logger with one rule.
logger = logging.getLogger("rocell.api.scan_throttle")

#: The environment variable that overrides `DEFAULT_SCAN_RATE_LIMIT`. Changing
#: it requires a process restart to take effect (read once, below,
#: `shared_vision.pipeline.GREY_WORLD`'s own pattern) — never a per-request re-read.
SCAN_RATE_LIMIT_ENV = "TILEMATCH_SCAN_RATE_LIMIT"

#: A documented, uncalibrated placeholder — PRD OQ-13 defers the real number
#: to the Foundation build and the Phase 2 pilot, the same bucket FR-9's blur
#: bound is in. Thirty submissions in the window below is generous enough
#: that no ordinary staff member scanning tiles by hand would ever meet it,
#: and low enough to stop a script driving the endpoint at machine speed.
DEFAULT_SCAN_RATE_LIMIT = 30

#: The environment variable that overrides `DEFAULT_SCAN_RATE_LIMIT_WINDOW`.
#: Same read-once-at-import rule as the rate above.
SCAN_RATE_LIMIT_WINDOW_ENV = "TILEMATCH_SCAN_RATE_LIMIT_WINDOW_SECONDS"

#: A documented, uncalibrated placeholder, in seconds — one minute. Paired
#: with `DEFAULT_SCAN_RATE_LIMIT` above: thirty submissions a minute is the
#: uncalibrated starting bound this ships with, not a measured one.
DEFAULT_SCAN_RATE_LIMIT_WINDOW = 60.0


def _read_rate_limit() -> int:
    """`SCAN_RATE_LIMIT_ENV`'s value, falling back to the default.

    An operator's typo must not crash every import of `api.scan` — so a value
    `int()` cannot parse is caught rather than left to raise, and the default
    is used instead. Logged rather than swallowed: this is the one bound
    standing between a real refusal and a scan pipeline exposed to an
    unthrottled script.

    A parsed value below 1 is rejected the same way, `_read_window`'s own
    shape: `0` or a negative rate would refuse every user's very first
    submission on every request — a plain typo silently disabling scanning
    product-wide, with no warning to say why — so "a positive whole number"
    is the whole of what this value may be, not merely "a whole number".
    """
    raw = os.environ.get(SCAN_RATE_LIMIT_ENV)
    if raw is None:
        return DEFAULT_SCAN_RATE_LIMIT

    try:
        value = int(raw)
    except ValueError:
        logger.warning(
            "%s=%r is not a whole number; using the default rate (%s) instead",
            SCAN_RATE_LIMIT_ENV,
            raw,
            DEFAULT_SCAN_RATE_LIMIT,
        )
        return DEFAULT_SCAN_RATE_LIMIT

    if value < 1:
        logger.warning(
            "%s=%r is not a positive whole number; using the default rate (%s) instead",
            SCAN_RATE_LIMIT_ENV,
            raw,
            DEFAULT_SCAN_RATE_LIMIT,
        )
        return DEFAULT_SCAN_RATE_LIMIT

    return value


def _read_window() -> float:
    """`SCAN_RATE_LIMIT_WINDOW_ENV`'s value, falling back to the default.

    A value `float()`
    cannot parse, or one that parses to something non-finite (`nan`, `inf`,
    `-inf` are all valid input to `float()` with no error at all), falls back
    to the default rather than reaching the SQL below with a window that
    could never resolve. A negative window is rejected the same way — "a
    non-negative number of seconds" is the whole of what this value may be.

    A value so large that `timedelta(seconds=value)` cannot represent it is
    rejected too — `check_and_record` builds exactly that `timedelta` on every
    request, and an unguarded operator typo like `1e20` would turn every
    `POST /scans` into an unhandled `OverflowError` for as long as the
    variable stayed set, rather than a single logged fallback at import.
    """
    raw = os.environ.get(SCAN_RATE_LIMIT_WINDOW_ENV)
    if raw is None:
        return DEFAULT_SCAN_RATE_LIMIT_WINDOW

    try:
        value = float(raw)
    except ValueError:
        logger.warning(
            "%s=%r is not a number; using the default window (%s) instead",
            SCAN_RATE_LIMIT_WINDOW_ENV,
            raw,
            DEFAULT_SCAN_RATE_LIMIT_WINDOW,
        )
        return DEFAULT_SCAN_RATE_LIMIT_WINDOW

    if not math.isfinite(value) or value < 0:
        logger.warning(
            "%s=%r is not a non-negative finite number; using the default window (%s) instead",
            SCAN_RATE_LIMIT_WINDOW_ENV,
            raw,
            DEFAULT_SCAN_RATE_LIMIT_WINDOW,
        )
        return DEFAULT_SCAN_RATE_LIMIT_WINDOW

    try:
        timedelta(seconds=value)
    except OverflowError:
        logger.warning(
            "%s=%r is too large to use as a time window; using the default window (%s) instead",
            SCAN_RATE_LIMIT_WINDOW_ENV,
            raw,
            DEFAULT_SCAN_RATE_LIMIT_WINDOW,
        )
        return DEFAULT_SCAN_RATE_LIMIT_WINDOW

    return value


#: The limit `check_and_record` gates against. Read once at import — exactly
#: `shared_vision.pipeline.GREY_WORLD`'s own pattern — so the value
#: in effect for the life of a process is fixed at start-up.
SCAN_RATE_LIMIT = _read_rate_limit()

#: The window, in seconds, `check_and_record` measures against. Converted to a
#: `timedelta` only where it is bound into SQL — kept as a plain number here so
#: a test can compare it directly against the env var's own units.
SCAN_RATE_LIMIT_WINDOW = _read_window()

#: `window_started_at` older than the window means the run this row records
#: has ended — the next submission starts a fresh window at 1 rather than
#: n+1. `login_attempts`'s `_RUN_ENDED` fragment, one clause instead of two:
#: there is no lock to carry through here, only a count and a window.
_WINDOW_STALE = "scan_rate_limit.window_started_at <= now() - %s"

#: AD-8's single atomic increment-and-check, and the only statement in the
#: product that writes `scan_rate_limit`.
#:
#: One statement decides both things at once — whether this submission starts
#: a fresh window, and what the count becomes — from the row as it is locked
#: for update, not from a value read a moment ago by some other request.
#: `RETURNING` hands back the count that was actually written, so the caller
#: never re-reads and never guesses.
_CHECK_AND_RECORD = f"""
INSERT INTO scan_rate_limit (user_id, submission_count, window_started_at)
VALUES (%s, 1, now())
ON CONFLICT (user_id) DO UPDATE
   SET submission_count = CASE WHEN {_WINDOW_STALE} THEN 1
                               ELSE scan_rate_limit.submission_count + 1 END,
       window_started_at = CASE WHEN {_WINDOW_STALE} THEN now()
                                ELSE scan_rate_limit.window_started_at END
RETURNING submission_count
"""


def check_and_record(conn: psycopg.Connection, user_id: UUID) -> bool:
    """Count one scan submission for `user_id` and report whether it is over the limit.

    `True` means this submission itself is refused — the count it produced,
    including the one that just wrote it, exceeds `SCAN_RATE_LIMIT`. A
    throttled caller who keeps retrying keeps incrementing and keeps being
    refused, until `window_started_at` goes stale and the count resets to 1
    (the I/O matrix's own "a throttled caller keeps retrying" row).

    Reads `SCAN_RATE_LIMIT`/`SCAN_RATE_LIMIT_WINDOW` through the module rather
    than capturing them as default arguments, so a test can lower either one
    with `monkeypatch.setattr` and see it take effect on the very next call.
    """
    window = timedelta(seconds=SCAN_RATE_LIMIT_WINDOW)
    row = conn.execute(_CHECK_AND_RECORD, (user_id, window, window)).fetchone()
    if row is None:  # pragma: no cover - both upsert branches produce a row
        # Unreachable: `ON CONFLICT DO UPDATE ... RETURNING` yields a row on
        # the insert branch and on the update branch alike. Answered as "not
        # over the limit" rather than by raising, so a request already on its
        # way to being processed is not turned into a 500 by this defensive
        # branch never actually being hit.
        return False

    return row["submission_count"] > SCAN_RATE_LIMIT
