-- Story 1.12 — the append-only audit log, and the database role that cannot
-- rewrite it.
--
-- Two objects and one role, and the role is half the story rather than a
-- deployment detail bolted on at the end:
--
--   audit_log     the append-only record FR-20 and NFR4 require — who did
--                 what, when, and from which source address. One row per
--                 privileged action, written by `apps/api/api/audit.py` and
--                 by nothing else.
--   rocell_app    the product's first non-owner database role. `apps/api`
--                 adopts it at connection startup (`options=-c
--                 role=rocell_app`, see `apps/api/api/db.py`), so every
--                 statement the service runs runs as this role.
--
-- **Why the role is created here and not in a migration of its own.** AD-4
-- does not ask for an audit table; it asks for an audit table the application
-- cannot UPDATE or DELETE. The grant model is the invariant and the table is
-- only its subject, so splitting them would ship a window — however short — in
-- which the log exists with the owner's full DML behind it. One concern, one
-- migration: "an audit log that the application may only append to".
--
-- **A trigger was deliberately not used.** A `BEFORE UPDATE ... RAISE` trigger
-- is application-adjacent logic the table owner can drop, and this schema
-- already establishes that it does not use triggers for invariants — `users`
-- has no BEFORE UPDATE trigger and every writer sets `updated_at` by hand
-- (DW-17). AD-4 names the grant model, and the grant model is what is here.
--
-- **The role is CLUSTER-scoped; the grants are DATABASE-scoped.** `CREATE ROLE`
-- writes to `pg_authid`, which every database in the cluster shares, while
-- `GRANT ... ON TABLE` writes to the catalogue of the database it runs in.
-- Two consequences worth knowing before editing this file:
--
--   * The `DO` block below is written so a second database in the same cluster
--     replays it cleanly — `apps/api/tests/conftest.py` builds a fresh database
--     per test against one shared cluster, so this path is taken hundreds of
--     times per run.
--   * The matching `.down.sql` therefore does **not** `DROP ROLE`. Dropping it
--     would revoke it out from under every other database in the cluster.
--
-- **A table added by a later migration needs its own GRANT, in that
-- migration.** There is no `ALTER DEFAULT PRIVILEGES` here on purpose: default
-- privileges apply to objects created *afterwards* by the role that set them,
-- which quietly makes "did the application get access" depend on which role
-- ran the migration. Spelling each grant out means a forgotten one is a loud,
-- immediate failure. `apps/api/tests/test_audit_immutability.py` asserts that
-- every table in `public` except `audit_log` and `schema_migrations` is fully
-- granted to the role, so a missing `GRANT` fails there rather than in
-- production.
--
-- **No foreign key from `audit_log` to `users`, in either direction (AD-10).**
-- `DELETE /admin/users/{id}` is a hard delete, and the application role holds
-- no `DELETE` on this table — so an FK would force a choice between blocking
-- every user delete and cascading into a table nothing may delete from.
-- `actor_user_id`/`actor_email` and `target_user_id`/`target_email` are
-- therefore denormalized snapshots: the id joins while the row lives, and the
-- address is what the entry still means after it does not.
--
-- **The migrating role needs `CREATEROLE`** (or superuser). This is the first
-- migration in the product that creates a role, so it is the first that needs
-- more than write access to the database: `DATABASE_URL` pointing at an
-- ordinary owner is no longer enough. `infra/README.md` states it beside the
-- other prerequisites. On a replay where `rocell_app` already exists the
-- `CREATE ROLE` is skipped, but `GRANT rocell_app TO current_user` still needs
-- ADMIN OPTION on the role, which the role's creator holds — so the same
-- operator should run it everywhere.
--
-- Nothing here is newer than PostgreSQL 13 — `gen_random_uuid()` is core from
-- 13, `jsonb` and `format()` long predate it — so a 16.x test cluster and the
-- 18.x deployment target agree about what this file means.
--
-- `IF NOT EXISTS` throughout, matching the five migrations before it: a
-- truncated ledger must be able to replay the whole set.
--
-- **Apply this before deploying the code that reads these objects.**
-- `api/audit.py` names `audit_log` in the one statement it owns, `api/auth.py`
-- and `api/users.py` write through it on nine paths, and `api/db.py` asks for
-- `role=rocell_app` at connection startup — so a revision that ships ahead of
-- this migration cannot open a single connection, let alone serve a request.
-- Migrate, confirm the table and the role are there, then roll the application
-- forward. The `.down.sql` states the mirror of that ordering for a revert.

CREATE TABLE IF NOT EXISTS audit_log (
    id              uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    -- The database clock, never the application's. Written once and never
    -- moved: there is no `updated_at` here because there is no update.
    created_at      timestamptz NOT NULL DEFAULT now(),
    -- One of `api.audit.AuditAction`'s values. Deliberately plain `text` with
    -- no CHECK: the vocabulary grows with every epic (catalogue events in
    -- Epic 2, scan events in Epic 3), and a CHECK would make each addition a
    -- migration that must be applied before the code that writes the value.
    -- The enum in `api/audit.py` is the vocabulary; this column stores it.
    action          text        NOT NULL,
    -- Who acted. NULL only where nobody is known — a refused sign-in against
    -- an address that is not an account.
    actor_user_id   uuid,
    actor_email     text,
    -- Who it was done to. Equal to the actor for a self-directed action (a
    -- sign-in, a password change); different for every admin write.
    target_user_id  uuid,
    target_email    text,
    -- The source address, as `api.audit.source_ip` resolved it: the TCP peer,
    -- or the trusted proxy header when one is configured. NULL when neither
    -- parsed as an IP address — never a raw client-supplied string that was
    -- not validated.
    source_ip       text,
    -- Everything the action needs that is not a column: a refusal's reason, a
    -- revocation's count, an edit's before/after. Never a password, a password
    -- hash, a session token or a token hash.
    details         jsonb       NOT NULL DEFAULT '{}'::jsonb
);

-- The chronological read Story 1.13 renders, newest first. `id DESC` is the
-- tiebreaker rather than decoration: `created_at` defaults to `now()`, which
-- is the transaction timestamp, so two entries written by one request share it
-- exactly and a sort on `created_at` alone would have no total order to page
-- through.
CREATE INDEX IF NOT EXISTS audit_log_created_at_idx ON audit_log (created_at DESC, id DESC);

DO $$
BEGIN
    -- **NOLOGIN, which is the default, and deliberately so.** Adoption
    -- through libpq's `options=-c role=` needs MEMBERSHIP in the role, not
    -- the ability to log in as it — a NOLOGIN role is adopted identically,
    -- and `apps/api/tests/test_audit_immutability.py` proves it by running
    -- the product's own pool against this role. Adding LOGIN would give the
    -- cluster a passwordless login principal whose only protection is
    -- `pg_hba.conf`, which on a `trust` or `peer` cluster is a direct
    -- connection vector — for a capability nothing uses. No password either,
    -- for the same reason and because a credential belongs in the
    -- deployment's secret store and never in a file under version control
    -- (AGENTS.md Policy). The stronger form — a genuine second login role —
    -- adds `ALTER ROLE rocell_app LOGIN PASSWORD ...` at deployment time and
    -- is recorded as deferred work rather than guessed at here.
    CREATE ROLE rocell_app;
EXCEPTION
    -- The role already exists, because another database in this cluster
    -- applied this same migration. Both codes are reachable: `duplicate_object`
    -- from the ordinary sequential case, `unique_violation` from two runs
    -- racing on `pg_authid`'s index (the runner's advisory lock is
    -- per-database and cannot serialise them).
    WHEN duplicate_object OR unique_violation THEN NULL;
END
$$;

DO $$
BEGIN
    -- The owner must be a member of the role before it can adopt it: a
    -- non-superuser connection asking for `-c role=rocell_app` is refused
    -- outright without this. `format(%I)` because GRANT takes an identifier
    -- and identifiers are not parameters.
    EXECUTE format('GRANT rocell_app TO %I', current_user);
END
$$;

GRANT USAGE ON SCHEMA public TO rocell_app;

-- Full DML on the three tables the product mutates. Not `ALL PRIVILEGES`:
-- TRUNCATE, REFERENCES and TRIGGER are not things the application does, and a
-- role that may TRUNCATE `users` is a role that may empty it in one statement.
GRANT SELECT, INSERT, UPDATE, DELETE ON users TO rocell_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON sessions TO rocell_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON login_attempts TO rocell_app;

-- **The whole point of this migration.** SELECT and INSERT, and nothing else.
-- UPDATE, DELETE and TRUNCATE are refused by PostgreSQL itself, so the
-- append-only rule survives a later bug in application code rather than
-- depending on a reviewer having noticed it. A wrong entry is corrected by
-- inserting a corrective entry (AD-4).
GRANT SELECT, INSERT ON audit_log TO rocell_app;
