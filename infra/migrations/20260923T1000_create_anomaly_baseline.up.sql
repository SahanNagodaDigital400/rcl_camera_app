-- Story 3.7 — FR-22's per-user, per-signal anomaly baseline. AD-8's counter
-- shape a third time: `login_attempts` (Story 1.6) and `scan_rate_limit`
-- (Story 3.6) are the other two AD-8 counters, never generalised into one
-- another (`api/scan_throttle.py`'s own "Not here"). This table is not a
-- fourth rate limit — it never refuses anything — it is the rolling
-- per-user average `apps/api/api/anomaly.py`'s one atomic statement checks
-- the current window's count against.
--
-- **One row per `(user_id, signal)`, `scan_rate_limit`'s own precedent for
-- the key.** `signal` discriminates the two things this story watches — a
-- successful sign-in and a scan submission — because both are the same shape
-- end to end (same columns, same statement, same config) and a `signal`
-- column avoids duplicating one table and one nearly-identical module twice
-- for what is genuinely one mechanism applied to two call sites. `ON DELETE
-- CASCADE`, `scan_rate_limit.user_id`'s own reason: a hard-deleted user's own
-- baseline rows go with them rather than dangling.
--
-- `window_count` and `baseline_average` carry their own CHECKs for the reason
-- `scan_rate_limit.submission_count` does: the one statement that writes this
-- table can only ever produce a non-negative count and a non-negative
-- average, and the constraint is what says so to the next statement somebody
-- adds. `baseline_average` is nullable — the first-ever window for a
-- `(user_id, signal)` pair has nothing to compare against yet, and NULL says
-- so rather than a sentinel like `0`, which would read as "this user's
-- average is zero" and make every first real submission a deviation.
--
-- **Full DML granted, unlike `audit_log`.** `test_audit_immutability.py::
-- test_no_table_is_left_ungranted_by_a_later_migration` expects every table
-- but `audit_log` to be fully granted, and nothing here needs delete/update
-- protection at the database level — `scan_rate_limit`'s own precedent.
--
-- `IF NOT EXISTS` throughout, matching every migration before it: a truncated
-- ledger must be able to replay the whole set.
--
-- **Apply this before deploying the code that reads or writes it.**
-- `apps/api/api/anomaly.py` names this table in its one statement, so a
-- revision that ships ahead of this migration cannot serve a sign-in or
-- `POST /scans` at all.

CREATE TABLE IF NOT EXISTS anomaly_baseline (
    user_id           uuid             NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    signal            text             NOT NULL CHECK (signal IN ('login', 'scan')),
    window_started_at timestamptz      NOT NULL DEFAULT now(),
    window_count      integer          NOT NULL DEFAULT 0 CHECK (window_count >= 0),
    baseline_average  double precision CHECK (baseline_average IS NULL OR baseline_average >= 0),
    PRIMARY KEY (user_id, signal)
);

GRANT SELECT, INSERT, UPDATE, DELETE ON anomaly_baseline TO rocell_app;
