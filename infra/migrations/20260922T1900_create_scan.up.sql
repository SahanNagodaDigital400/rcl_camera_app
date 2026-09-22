-- Story 3.5 — persisted scan history: one row per successfully submitted
-- Scan, so a Staff or Administrator caller can revisit a past result.
--
-- **A denormalized snapshot, not a foreign key to Tile or Reference Image**
-- (AD-10). `candidates_snapshot` is the same closed `ScanCandidate` array
-- `POST /scans` already answered with, stored verbatim as `jsonb`: a Tile
-- removed later (`DELETE /admin/tiles/{tile_id}`) must not blank, cascade
-- into, or block this table, and a foreign key would force exactly that
-- choice. The snapshot is what lets a history entry's Code, Size and
-- Category keep rendering after the Tile they matched is gone — only the
-- proxied image request then 404s.
--
-- **`user_id` is the one real foreign key here**, `sessions.user_id`'s own
-- precedent (`20260917T1300_create_sessions.up.sql`): `ON DELETE CASCADE` so
-- a hard-deleted user's own scan history goes with them rather than dangling.
--
-- **Full DML granted, unlike `audit_log`.** `scan`'s append-only behaviour is
-- this story's own design choice, not a PostgreSQL-enforced invariant the way
-- AD-4 makes audit immutability — nothing in FR-8 or this story's acceptance
-- criteria asks for delete/update protection at the database level, and
-- `apps/api/tests/test_audit_immutability.py::test_every_other_table_is_fully_granted`
-- expects every table but `audit_log` to be fully granted. Granting only
-- `SELECT, INSERT` would be the locally "correct" grant and would fail that
-- existing, unrelated test for a reason a reviewer would have to go looking
-- for — see the story's Design Notes.
--
-- `IF NOT EXISTS` throughout, matching every migration before it: a truncated
-- ledger must be able to replay the whole set.
--
-- **Apply this before deploying the code that reads or writes it.**
-- `apps/api/api/scan.py` names this table on both `POST /scans` and
-- `GET /scans`, so a revision that ships ahead of this migration cannot serve
-- either request.

CREATE TABLE IF NOT EXISTS scan (
    id                  uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             uuid        NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    -- The closed `ScanCandidate` array `POST /scans` returned, byte-identical
    -- to the response body — built from the same `list[ScanCandidate]` after
    -- it is constructed, never recomputed. An empty array is a real value (no
    -- confident match), not the absence of one.
    candidates_snapshot jsonb       NOT NULL,
    created_at          timestamptz NOT NULL DEFAULT now()
);

-- The keyset-pagination index `GET /scans` reads through, `audit_log_created_at_idx`'s
-- own twin scoped per-user: a caller's history is paged newest first within
-- their own rows, never across every user's.
CREATE INDEX IF NOT EXISTS scan_user_id_created_at_idx
    ON scan (user_id, created_at DESC, id DESC);

GRANT SELECT, INSERT, UPDATE, DELETE ON scan TO rocell_app;
