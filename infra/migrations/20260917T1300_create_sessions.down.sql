-- Reverts 20260917T1300_create_sessions.up.sql, restoring the previous shape:
-- no `sessions` table at all. Dropping the table drops its indexes with it;
-- they are named here anyway so the file reads as the exact inverse of the
-- `up`.
--
-- Unlike the seed migration's `down`, this one is unconditional: a session is
-- reissued by signing in again, so dropping the table costs a user one login
-- and takes nothing irrecoverable with it.

DROP INDEX IF EXISTS sessions_expires_at_idx;

DROP INDEX IF EXISTS sessions_user_id_idx;

DROP INDEX IF EXISTS sessions_token_hash_key;

DROP TABLE IF EXISTS sessions;
