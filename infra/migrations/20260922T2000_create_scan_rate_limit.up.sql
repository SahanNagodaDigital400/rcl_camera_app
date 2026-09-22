-- Story 3.6 — FR-23's per-user scan throttle. AD-8's counter shape again,
-- for a third caller: `login_attempts` (Story 1.6) and this table are two
-- separate AD-8 counters, never generalised into one another
-- (`api/throttle.py`'s own "Not here").
--
-- **Keyed on `user_id`, and a real foreign key — unlike `login_attempts`.**
-- `POST /scans` sits behind `require_claimed_user`: by the time this check
-- runs, the caller is already a resolved, authenticated account, so there is
-- no identical-rejection invariant to protect and no reason to key on a
-- submitted value rather than the real user. `scan.user_id`'s own precedent
-- (`20260922T1900_create_scan.up.sql`): `ON DELETE CASCADE`, so a hard-deleted
-- user's own counter row goes with them rather than dangling.
--
-- `submission_count` carries its own CHECK for the reason `login_attempts.
-- failure_count` does: the one statement that writes this table can only ever
-- produce 1 or n+1, and the constraint is what says so to the next statement
-- somebody adds.
--
-- `window_started_at` is the fixed-window anchor `apps/api/api/scan_throttle.py`
-- reads and resets — a row older than `SCAN_RATE_LIMIT_WINDOW` resets to 1 in
-- the same atomic statement that would otherwise increment it.
--
-- **Full DML granted, unlike `audit_log`.** `test_audit_immutability.py::
-- test_no_table_is_left_ungranted_by_a_later_migration` expects every table but
-- `audit_log` to be fully granted, and nothing here needs delete/update
-- protection at the database level — `scan`'s own precedent.
--
-- `IF NOT EXISTS` throughout, matching every migration before it: a truncated
-- ledger must be able to replay the whole set.
--
-- **Apply this before deploying the code that reads or writes it.**
-- `apps/api/api/scan_throttle.py` names this table in its one write, so a
-- revision that ships ahead of this migration cannot serve `POST /scans` at
-- all.

CREATE TABLE IF NOT EXISTS scan_rate_limit (
    user_id           uuid        PRIMARY KEY REFERENCES users (id) ON DELETE CASCADE,
    submission_count  integer     NOT NULL DEFAULT 0 CHECK (submission_count >= 0),
    window_started_at timestamptz NOT NULL DEFAULT now()
);

GRANT SELECT, INSERT, UPDATE, DELETE ON scan_rate_limit TO rocell_app;
