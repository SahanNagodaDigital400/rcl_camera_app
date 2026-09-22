-- Reverts 20260922T2000_create_scan_rate_limit.up.sql: no scan rate-limit
-- counter, and no grant on it. `20260922T1900_create_scan.down.sql`'s own
-- shape.
--
-- **Deploy the code first, then step this back — never the other way round.**
-- `apps/api/api/scan_throttle.py` names `scan_rate_limit` in its one write, so
-- with the current code running a revert makes `POST /scans` fail on an
-- undefined relation. Roll the application back to a revision that names
-- neither, confirm it is serving, then run this.
--
-- Once that ordering is respected the revert costs one thing: every user's
-- in-progress rate-limit window is forgotten, so the first submission after
-- a re-migrate starts a fresh count from zero. Nothing else depends on this
-- table.
--
-- Guarded on the role existing, exactly as every other `down` in this
-- directory is: a bare `REVOKE` raises outright when the role is absent, and
-- a `down` that raises is a `down` that does not restore the previous shape.

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'rocell_app') THEN
        REVOKE ALL PRIVILEGES ON scan_rate_limit FROM rocell_app;
    END IF;
END
$$;

DROP TABLE IF EXISTS scan_rate_limit;
