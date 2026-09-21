-- Story 2.1 — the Catalogue: Tiles, their Reference Images, and the vector
-- index a Scan searches.
--
-- Six tables and one extension. The shape follows the architecture spine's ERD
-- with two deliberate departures, both recorded in the story's Design Notes
-- and both narrowing rather than widening what the ERD allowed:
--
--   * **Size and Category are reference tables, not text columns.** The ERD
--     types them `string`; the spine's Consistency Conventions row is the
--     later and more specific statement — "normalized into their own reference
--     tables ... the same create-if-missing, case/whitespace-normalized
--     lookup". `apps/api` and `scripts/ingest` are two writers, and free text
--     is how `45X90`, `45x90` and ` 45X90 ` become three sizes nothing can
--     join on. `tile_category` additionally carries the real `UNKNOWN` row
--     AD-18 asks for, so a Tile whose Category could not be recovered is
--     grouped rather than dropped and no query has to special-case NULL.
--
--   * **The pipeline stamp lives on `embedding_generation`, not on each
--     embedding row.** AD-14 says the check is "global, not per-row", and that
--     a re-index is a complete new generation cut over atomically by a single
--     pointer. The ERD's per-row `pipeline_version` column gives per-row
--     semantics AD-14 explicitly rejects — and a half-migrated Reference Image
--     with some views on the old stamp and some on the new is exactly what it
--     forbids. One partial unique index makes "exactly one active generation"
--     the database's rule rather than the application's.
--
-- **`CREATE EXTENSION vector` is the first extension this schema has needed.**
-- pgvector's floor is >= 0.8.2 and it is load-bearing, not cosmetic:
-- CVE-2026-3172 is a buffer overflow in parallel HNSW index builds affecting
-- 0.6.0-0.8.1, and AD-5 mandates HNSW. `infra/README.md` states the
-- prerequisite; the migration cannot check a version it would then have to
-- refuse, so an older cluster fails at the `CREATE INDEX ... USING hnsw` below
-- rather than here.
--
-- **The migrating role needs the privilege to create an extension** (superuser
-- on most clusters; `vector` is not trusted). That is a new prerequisite on
-- top of the CREATEROLE that `20260921T1000_create_audit_log` introduced, and
-- `infra/README.md` names both.
--
-- **Every new table gets its own explicit GRANT at the bottom.** There is no
-- `ALTER DEFAULT PRIVILEGES` in this schema on purpose — see the audit-log
-- migration's header for why — and
-- `apps/api/tests/test_audit_immutability.py` fails the build the day a table
-- lands without one.
--
-- **No foreign key from anything here to `audit_log` or from it to here
-- (AD-10).** A catalogue entry named in an audit entry is a denormalized
-- snapshot: removal (Story 2.3) is a hard delete, and the log may not be
-- cascaded into or blocked by one.
--
-- `IF NOT EXISTS` throughout, matching the six migrations before it: a
-- truncated ledger must be able to replay the whole set.
--
-- **Apply this before deploying the code that reads these objects.**
-- `apps/api/api/catalogue.py` names all six tables and `POST /admin/tiles`
-- cannot serve a request without them.

CREATE EXTENSION IF NOT EXISTS vector;

-- --- Reference tables ---------------------------------------------------------
-- `name` is always the *normalized* form (trim, collapse internal whitespace,
-- uppercase) that `shared_schema.tile.normalize_label` produces, which is the
-- POC's `normalize_folder` rule. The UNIQUE constraint is on that normalized
-- value, so the create-if-missing lookup both writers use cannot produce a
-- near-duplicate — and a race between two writers resolves to one row rather
-- than to an error the caller has to understand.

CREATE TABLE IF NOT EXISTS tile_size (
    id          uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    name        text        NOT NULL UNIQUE,
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS tile_category (
    id          uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    name        text        NOT NULL UNIQUE,
    created_at  timestamptz NOT NULL DEFAULT now()
);

-- AD-18's sentinel, as a real row. A Tile whose Category could not be
-- recovered from the source tree is grouped under it and flagged for
-- follow-up; it is never dropped, and no read has to remember to handle NULL.
-- Seeded here rather than by the application so that the very first add can
-- resolve it without a write that races.
INSERT INTO tile_category (name) VALUES ('UNKNOWN') ON CONFLICT (name) DO NOTHING;

-- --- The unit of identity -----------------------------------------------------

CREATE TABLE IF NOT EXISTS tile (
    id           uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    -- **The identity** (AD-18). One catalogue row per file; the cleaned file
    -- name is the answer a Scan returns. UNIQUE on the Code alone and on
    -- nothing else: a uniqueness constraint over `size + category` would make
    -- two Codes in one folder collide, and the 22 files in `45X90/POLISH` are
    -- 22 different tiles, not 22 faces of one.
    code         text        NOT NULL UNIQUE,
    size_id      uuid        NOT NULL REFERENCES tile_size (id),
    -- Nullable in the ERD; in practice always resolved, to the UNKNOWN
    -- sentinel when nothing better is known. Left nullable anyway so the
    -- column states what the ERD states and a later reader is not misled into
    -- thinking the sentinel is a domain value.
    category_id  uuid        REFERENCES tile_category (id),
    -- A nullable **display hint** and nothing else (AD-18). The dash-delimited
    -- names in the real tree carry no recoverable trailing number at all, and
    -- the Code alone identifies the Tile — so nothing may key, group or match
    -- on this.
    face_number  text,
    created_at   timestamptz NOT NULL DEFAULT now(),
    -- `users` has no BEFORE UPDATE trigger and every writer sets `updated_at`
    -- by hand (DW-17). Same here, for the same reason: this schema does not
    -- use triggers for invariants.
    updated_at   timestamptz NOT NULL DEFAULT now()
);

-- Story 2.5 searches substrings of the Code, and Story 2.1's duplicate check
-- is the unique index above. This one is for the Size grouping AD-19's hard
-- pre-filter needs, and for rendering the catalogue by Size.
CREATE INDEX IF NOT EXISTS tile_size_id_idx ON tile (size_id);
CREATE INDEX IF NOT EXISTS tile_category_id_idx ON tile (category_id);

CREATE TABLE IF NOT EXISTS reference_image (
    id                uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    -- ON DELETE CASCADE because removal is real removal (AD-5): a removed
    -- Tile's images, and their embeddings below, go with it rather than being
    -- filtered out at query time by a predicate one call site can forget.
    tile_id           uuid        NOT NULL REFERENCES tile (id) ON DELETE CASCADE,
    -- Object-storage keys, resolved by `apps/api/api/storage.py`. Two objects
    -- per image and they are not interchangeable: `source_key` is the
    -- colour-managed, EXIF-stripped, 2048px-capped asset a re-index (AD-14)
    -- reads and which is **never served**; `derivative_key` is AD-17's capped
    -- display view, which is the only one `apps/web` ever sees, and then only
    -- proxied through an authenticated endpoint (AD-9).
    source_key        text        NOT NULL,
    derivative_key    text        NOT NULL,
    -- The digest of the bytes as uploaded. Also the seed `generate_views` is
    -- keyed on, which is what makes a rebuild reproduce the same 16 views.
    sha256            text        NOT NULL,
    width             integer     NOT NULL,
    height            integer     NOT NULL,
    source_bytes      bigint      NOT NULL,
    derivative_bytes  bigint      NOT NULL,
    -- FR-19's quality flag: pixel standard deviation, and whether it is below
    -- the threshold at which a reference carries no retrievable texture. Such
    -- an image matches any washed-out photo and can never be reliably
    -- retrieved itself — a real property of plain tiles, which the
    -- Administrator has to be able to see on the tile's own screen rather than
    -- only in a report.
    pixel_std         real        NOT NULL,
    featureless       boolean     NOT NULL DEFAULT false,
    created_at        timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS reference_image_tile_id_idx ON reference_image (tile_id);

-- --- The index ----------------------------------------------------------------

CREATE TABLE IF NOT EXISTS embedding_generation (
    id                uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    -- AD-14's stamp: `shared_vision.PIPELINE_VERSION` plus `config_hash()`,
    -- together identifying the exact build that produced every vector in this
    -- generation. A search compares the running pipeline's stamp against this
    -- one row, not against each embedding.
    pipeline_version  text        NOT NULL,
    config_hash       text        NOT NULL,
    is_active         boolean     NOT NULL DEFAULT false,
    created_at        timestamptz NOT NULL DEFAULT now()
);

-- **Deliberately no unique index over (pipeline_version, config_hash).** An
-- earlier draft had one, on the reasoning that two generations with the same
-- stamp make "which one am I searching" ambiguous. They do not: the partial
-- index below answers that question and is the only thing that has to. What a
-- stamp unique index actually does is forbid a re-index whose pipeline has not
-- changed — recovering from a corrupted index, re-running an ingest that
-- failed part-way, rebuilding after a bulk delete — which is a legitimate
-- operation AD-14 never asks to be blocked, and the schema would block it
-- permanently.

-- **Exactly one active generation, enforced by the database, and the only
-- uniqueness this table has.** This is the "single active-generation pointer"
-- AD-14 asks for: a cutover is one
-- transaction that clears the old flag and sets the new one, and a bug that
-- tried to leave two active is refused rather than producing a search over a
-- half-rebuilt index. A partial index rather than a CHECK, because the rule is
-- about the set of rows and not about any one of them.
CREATE UNIQUE INDEX IF NOT EXISTS embedding_generation_active_key
    ON embedding_generation (is_active) WHERE is_active;

CREATE TABLE IF NOT EXISTS reference_embedding (
    id                  uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    reference_image_id  uuid        NOT NULL
                                    REFERENCES reference_image (id) ON DELETE CASCADE,
    generation_id       uuid        NOT NULL
                                    REFERENCES embedding_generation (id) ON DELETE CASCADE,
    -- AD-5: unit-norm, so cosine similarity is a single dot product, and fixed
    -- at 1536 = concat(L2(CLS 768), L2(mean patch 768)) then L2 again — the
    -- model's own retrieval recipe.
    embedding           vector(1536) NOT NULL,
    -- AD-13's two families: 4 clean rotations of the full frame, then 12
    -- randomized augmented crops. Stored as separate rows and **never pooled
    -- at write time** — pooling gives back the scale invariance the crops
    -- exist to buy, and nothing about it would raise.
    view_kind           text        NOT NULL,
    view_index          integer     NOT NULL,
    created_at          timestamptz NOT NULL DEFAULT now(),
    UNIQUE (reference_image_id, generation_id, view_index)
);

CREATE INDEX IF NOT EXISTS reference_embedding_image_idx
    ON reference_embedding (reference_image_id);
CREATE INDEX IF NOT EXISTS reference_embedding_generation_idx
    ON reference_embedding (generation_id);

-- **HNSW, not IVFFlat, and the inner-product ops class, not L2** (AD-5). HNSW
-- is what makes "no manual re-index" true: an insert joins the searchable
-- graph immediately, which is the whole of Epic 2's "add a tile and scan it in
-- the same session". IVFFlat needs a populated table to build its lists and a
-- rebuild to stay useful, which is the manual step this product has promised
-- not to have. `vector_ip_ops` because the vectors are unit-norm, so the inner
-- product *is* the cosine similarity and `<#>` (its negative) sorts ascending
-- into best-first order.
CREATE INDEX IF NOT EXISTS reference_embedding_hnsw_idx
    ON reference_embedding USING hnsw (embedding vector_ip_ops);

-- --- Grants -------------------------------------------------------------------
-- Full DML on every one of the six. Not `ALL PRIVILEGES`: TRUNCATE, REFERENCES
-- and TRIGGER are not things the application does, and a role that may
-- TRUNCATE `tile` is a role that may empty the catalogue in one statement.
-- Spelled out per table because there is no ALTER DEFAULT PRIVILEGES to fall
-- back on.

GRANT SELECT, INSERT, UPDATE, DELETE ON tile_size TO rocell_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON tile_category TO rocell_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON tile TO rocell_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON reference_image TO rocell_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON embedding_generation TO rocell_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON reference_embedding TO rocell_app;
