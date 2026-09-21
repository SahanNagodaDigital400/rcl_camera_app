-- Reverts 20260921T1000_create_audit_log.up.sql, restoring the previous shape:
-- no audit log anywhere, and no application role holding anything.
--
-- **Deploy the code first, then step this back — never the other way round.**
-- `apps/api/api/db.py` asks for `role=rocell_app` at connection startup, so
-- with the current code running a revert that revoked its grants would break
-- *every* statement the product runs, and `api/audit.py` would fail on an
-- undefined relation before that. The order is: roll the application back to a
-- revision that names neither the table nor the role, confirm it is serving,
-- then run this.
--
-- Once that ordering is respected the revert costs one thing that cannot be
-- recovered, and it is stated rather than implied: **every audit entry is
-- destroyed**. The log is the record of who did what, and a `down` is the only
-- thing in the product that can remove one — which is precisely why AD-4 puts
-- immutability in the grant model and not in a migration's good manners. Take
-- a dump first if the entries matter.
--
-- **`DROP ROLE` is deliberately absent.** `rocell_app` is cluster-scoped while
-- these grants are database-scoped: every database in the cluster shares the
-- role, and `apps/api/tests/conftest.py` alone builds hundreds of databases
-- against one cluster. Dropping it here would revoke it out from under all of
-- them, and PostgreSQL would refuse the drop anyway while any other database
-- still held a grant to it. The role left behind holds nothing in this
-- database once the revokes below have run, which is the shape a revert is
-- supposed to restore.
--
-- Indexes are named explicitly rather than left to fall with the table, so a
-- reader can see what this file removes without opening the `up`.

-- Guarded on the role existing, for the mirror of the reason the `up` guards
-- its `CREATE ROLE`. A bare `REVOKE ... FROM rocell_app` raises outright when
-- the role is absent, and it can be: another database in this cluster may
-- have stepped its own copy of this migration down and dropped nothing, but
-- an operator who removed the role by hand, or a database restored from a
-- dump taken before it existed, both reach this file with no role to revoke
-- from. A `down` that raises is a `down` that does not restore the previous
-- shape, which is the one thing every migration pair in this directory
-- promises.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'rocell_app') THEN
        REVOKE ALL PRIVILEGES ON users FROM rocell_app;
        REVOKE ALL PRIVILEGES ON sessions FROM rocell_app;
        REVOKE ALL PRIVILEGES ON login_attempts FROM rocell_app;
        REVOKE ALL PRIVILEGES ON SCHEMA public FROM rocell_app;
        -- The membership the `up` granted, so this file does what its header
        -- says: after it the role holds nothing in this database *and* the
        -- owner is no longer one of its members. Without this the `up` is
        -- only half reverted, and on a cluster where the role outlives every
        -- database that used it the membership is the last thing left
        -- pointing at it.
        --
        -- **Membership is cluster-scoped, like the role itself**, so this one
        -- statement reaches every other database on the server: an
        -- application still running against a sibling database loses its
        -- ability to adopt the role the moment this runs. That is not a new
        -- hazard — the ordering rule at the top of this file already says to
        -- roll the application back first — but on a shared cluster "the
        -- application" means every one of them. Re-running the `up` in any
        -- database restores it.
        EXECUTE format('REVOKE rocell_app FROM %I', current_user);
    END IF;
END
$$;

DROP INDEX IF EXISTS audit_log_created_at_idx;

DROP TABLE IF EXISTS audit_log;
