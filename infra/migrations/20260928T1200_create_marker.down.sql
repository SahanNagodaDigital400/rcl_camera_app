-- Reverts 20260928T1200_create_marker.up.sql: no Markers, and no grant on them.
-- `20260923T1000_create_anomaly_baseline.down.sql`'s own shape.
--
-- **Deploy the code first, then step this back — never the other way round.**
-- `apps/api/api/markers.py` names `marker` in every statement it holds, and
-- `api.scan`'s `GET /scans/markers` reads the same table, so with the current
-- code running a revert makes both the Administrator's marker surface and the
-- Scan screen's picker fail on an undefined relation. Roll the application back
-- to a revision that names neither, confirm it is serving, then run this.
--
-- Once that ordering is respected the revert costs exactly the registered
-- rulers: their names and printed dimensions, which an Administrator retypes
-- from the cards themselves. **No measurement and no Scan is lost**, because
-- nothing here is referenced by either — a measurement is a suggestion that
-- pre-fills the Size picker for one submission and is never stored, and the
-- Size a staff member actually declared lives on the Scan row, which this
-- migration does not touch. There is no foreign key in either direction, so
-- nothing cascades and nothing blocks.
--
-- Guarded on the role existing, exactly as every other `down` in this
-- directory is: a bare `REVOKE` raises outright when the role is absent, and a
-- `down` that raises is a `down` that does not restore the previous shape.

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'rocell_app') THEN
        REVOKE ALL PRIVILEGES ON marker FROM rocell_app;
    END IF;
END
$$;

DROP TABLE IF EXISTS marker;
