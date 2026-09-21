-- Reverts 20260921T1500_create_catalogue.up.sql: no Catalogue, no vector
-- index, and no grants on either.
--
-- **Deploy the code first, then step this back — never the other way round.**
-- `apps/api/api/catalogue.py` names all six tables, so with the current code
-- running a revert makes `POST /admin/tiles` and every catalogue read fail on
-- an undefined relation. Roll the application back to a revision that names
-- none of them, confirm it is serving, then run this.
--
-- Once that ordering is respected the revert costs two things that cannot be
-- recovered from the database, and they are stated rather than implied:
--
--   * **every Tile and its metadata**, and
--   * **every embedding** — which is the whole index. Rebuilding it is not a
--     replay of this file; it is a re-embed of every Reference Image, which is
--     hours of CPU (AD-14's "complete new generation").
--
-- The stored objects are *not* touched: `OBJECT_STORAGE_ROOT` still holds
-- every source asset and derivative after this runs, orphaned. That is
-- deliberate — a migration may not reach outside the database — and it is what
-- makes a rebuild possible at all. Clearing them is an operator decision.
--
-- **`DROP EXTENSION vector` is deliberately absent**, for the reason the audit
-- migration's `down` does not `DROP ROLE`: the extension may have been
-- installed before this migration ever ran, and dropping it would remove the
-- `vector` type from every other object in the database that uses it. Nothing
-- in this database depends on it once the tables below are gone, and re-running
-- the `up` is a no-op against an extension that is already there.
--
-- Indexes are named explicitly rather than left to fall with their tables, so
-- a reader can see what this file removes without opening the `up`.

-- Guarded on the role existing, exactly as the audit migration's `down` is: a
-- bare REVOKE raises outright when the role is absent, and a `down` that
-- raises is a `down` that does not restore the previous shape.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'rocell_app') THEN
        REVOKE ALL PRIVILEGES ON reference_embedding FROM rocell_app;
        REVOKE ALL PRIVILEGES ON embedding_generation FROM rocell_app;
        REVOKE ALL PRIVILEGES ON reference_image FROM rocell_app;
        REVOKE ALL PRIVILEGES ON tile FROM rocell_app;
        REVOKE ALL PRIVILEGES ON tile_category FROM rocell_app;
        REVOKE ALL PRIVILEGES ON tile_size FROM rocell_app;
    END IF;
END
$$;

DROP INDEX IF EXISTS reference_embedding_hnsw_idx;
DROP INDEX IF EXISTS reference_embedding_generation_idx;
DROP INDEX IF EXISTS reference_embedding_image_idx;
DROP TABLE IF EXISTS reference_embedding;

DROP INDEX IF EXISTS embedding_generation_active_key;
DROP TABLE IF EXISTS embedding_generation;

DROP INDEX IF EXISTS reference_image_tile_id_idx;
DROP TABLE IF EXISTS reference_image;

DROP INDEX IF EXISTS tile_category_id_idx;
DROP INDEX IF EXISTS tile_size_id_idx;
DROP TABLE IF EXISTS tile;

DROP TABLE IF EXISTS tile_category;
DROP TABLE IF EXISTS tile_size;
