-- Story 1.2 — the `User` entity from the architecture spine's ERD.
--
-- `IF NOT EXISTS` is deliberate, not defensive habit: the seed migration's
-- guarantee is that a *truncated ledger* can replay the whole set without
-- producing a second Administrator, and a replay reaches this file first.
--
-- Nothing here is newer than PostgreSQL 13 (`gen_random_uuid()` is core from
-- 13), so a 16.x test cluster and the 18.x deployment target agree.
--
-- `password_hash` lives here and only here. It is absent from the shared
-- `User` contract by construction, so it cannot reach the API boundary.

CREATE TABLE IF NOT EXISTS users (
    id                          uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    name                        text        NOT NULL,
    -- Stored lowercased, enforced here rather than by convention: uniqueness
    -- is over `lower(email)` (below), and an address kept in the case someone
    -- happened to type would oblige every lookup in the product to remember
    -- `lower(email) = lower(<address>)`. Nothing would catch the first one that
    -- forgot, and it would silently fail to find an existing account.
    email                       text        NOT NULL CHECK (email = lower(email)),
    password_hash               text        NOT NULL,
    -- AGENTS.md Policy: never a role beyond these two. The CHECK is the
    -- database's own copy of that rule, independent of any application code.
    role                        text        NOT NULL CHECK (role IN ('staff', 'admin')),
    active                      boolean     NOT NULL DEFAULT true,
    must_change_password        boolean     NOT NULL DEFAULT true,
    -- An admin-issued temporary credential expires after 72 hours.
    temp_credential_expires_at  timestamptz,
    -- PRD FR-10: last sign-in is visible to an Administrator.
    last_login_at               timestamptz,
    created_at                  timestamptz NOT NULL DEFAULT now(),
    updated_at                  timestamptz NOT NULL DEFAULT now()
);

-- Email identifies an account to a human, and humans do not type case
-- consistently. Uniqueness is therefore over `lower(email)`, so RUWAN@rocell.lk
-- and ruwan@rocell.lk cannot both exist.
CREATE UNIQUE INDEX IF NOT EXISTS users_email_lower_key ON users (lower(email));
