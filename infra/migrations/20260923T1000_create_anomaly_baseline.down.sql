-- Reverts 20260923T1000_create_anomaly_baseline.up.sql: no anomaly-baseline
-- state, and no grant on it. `20260922T2000_create_scan_rate_limit.down.sql`'s
-- own shape.
--
-- **Deploy the code first, then step this back — never the other way round.**
-- `apps/api/api/anomaly.py` names `anomaly_baseline` in its one statement, so
-- with the current code running a revert makes both `POST /auth/login` and
-- `POST /scans` fail on an undefined relation. Roll the application back to a
-- revision that names neither, confirm it is serving, then run this.
--
-- Once that ordering is respected the revert costs one thing: every user's
-- in-progress baseline window, for both signals, is forgotten, so the first
-- sign-in or scan after a re-migrate starts a fresh count from zero with no
-- average to compare against. Nothing else depends on this table.
--
-- Guarded on the role existing, exactly as every other `down` in this
-- directory is: a bare `REVOKE` raises outright when the role is absent, and
-- a `down` that raises is a `down` that does not restore the previous shape.

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'rocell_app') THEN
        REVOKE ALL PRIVILEGES ON anomaly_baseline FROM rocell_app;
    END IF;
END
$$;

DROP TABLE IF EXISTS anomaly_baseline;
