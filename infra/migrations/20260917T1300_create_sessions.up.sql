-- Story 1.3 — the `Session` entity from the architecture spine's ERD.
--
-- The spine's SESSION block, verbatim and no wider: id, user_id, token_hash,
-- issued_at, expires_at. Nothing here belongs to Story 1.5 (the 12-hour idle
-- window, sliding renewal, session listing) — those are behaviour over these
-- columns, and adding a column for them now would freeze a decision 1.5 has
-- not taken yet.
--
-- `IF NOT EXISTS` for the same reason 20260917T1200_create_users.up.sql uses
-- it: a truncated ledger must be able to replay the whole set.
--
-- Nothing here is newer than PostgreSQL 13, so a 16.x test cluster and the
-- 18.x deployment target agree about what it means.

CREATE TABLE IF NOT EXISTS sessions (
    id          uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    -- ON DELETE CASCADE is the rule, not a convenience: AGENTS.md Policy says
    -- deactivating a user must never leave a session live, and deleting one
    -- outright must not leave rows pointing at an account that is gone. The
    -- database ends the sessions; no application code has to remember to.
    user_id     uuid        NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    -- The SHA-256 of the cookie's value, never the value itself. A database
    -- read then yields no usable cookie. Argon2id is deliberately *not* used
    -- here: the token is 256 bits of CSPRNG output with no dictionary behind
    -- it, and a 64 MiB KDF would be paid on every authenticated request.
    token_hash  text        NOT NULL,
    issued_at   timestamptz NOT NULL DEFAULT now(),
    -- No default: a session with no deliberate expiry is a session that never
    -- ends, and the caller is the only thing that knows the lifetime.
    expires_at  timestamptz NOT NULL
);

-- Unique, not merely indexed. The lookup on every authenticated request reads
-- by this column, and two rows sharing a hash would make "which session is
-- this" ambiguous — a state nothing else in the product could resolve.
CREATE UNIQUE INDEX IF NOT EXISTS sessions_token_hash_key ON sessions (token_hash);

-- Story 1.5 revokes every session of one user, and Story 1.11's deactivation
-- does the same through the cascade above. Both read by user_id.
CREATE INDEX IF NOT EXISTS sessions_user_id_idx ON sessions (user_id);

-- The login path sweeps rows past their expiry on every sign-in, and Story
-- 1.5's lifetime work will read this column too. Without an index that sweep
-- is a sequential scan of the whole table on every successful login.
CREATE INDEX IF NOT EXISTS sessions_expires_at_idx ON sessions (expires_at);
