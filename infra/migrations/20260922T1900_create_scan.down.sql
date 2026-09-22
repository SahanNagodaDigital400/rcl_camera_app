-- Reverts 20260922T1900_create_scan.up.sql: no scan history table, and no
-- grant on it. `20260921T1500_create_catalogue.down.sql`'s own shape.
--
-- **Deploy the code first, then step this back — never the other way round.**
-- `apps/api/api/scan.py` names `scan` on both `POST /scans` and
-- `GET /scans`, so with the current code running a revert makes both fail on
-- an undefined relation. Roll the application back to a revision that names
-- neither, confirm it is serving, then run this.
--
-- Once that ordering is respected the revert costs one thing that cannot be
-- recovered: **every Staff and Administrator member's scan history**. Unlike
-- the catalogue this is not rebuildable from anywhere else — take a dump
-- first if the history matters.
--
-- Guarded on the role existing, exactly as every other `down` in this
-- directory is: a bare `REVOKE` raises outright when the role is absent, and
-- a `down` that raises is a `down` that does not restore the previous shape.

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'rocell_app') THEN
        REVOKE ALL PRIVILEGES ON scan FROM rocell_app;
    END IF;
END
$$;

DROP INDEX IF EXISTS scan_user_id_created_at_idx;

DROP TABLE IF EXISTS scan;
