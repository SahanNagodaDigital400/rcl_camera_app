-- Reverts 20260917T1400_track_session_activity.up.sql, restoring the previous
-- shape: `sessions` with one deadline, the absolute `expires_at`.
--
-- **Deploy the code first, then step this back — never the other way round.**
-- `api.sessions` reads `last_seen_at` in `_SELECT_SESSION`, writes it in
-- `_TOUCH_SESSION` and sweeps on it in `_DELETE_EXPIRED`, so with the current
-- code running, dropping this column makes *every authenticated request* and
-- *every sign-in* fail on an undefined column — the whole product, not a
-- degraded corner of it. The order is: roll the application back to a revision
-- that does not name the column, confirm it is serving, then run this.
--
-- Once that ordering is respected the revert costs nothing irrecoverable. It
-- loses only the record of when each live session was last used; the absolute
-- bound is untouched, and a session whose idle window mattered is reissued by
-- signing in again.

ALTER TABLE sessions
    DROP COLUMN IF EXISTS last_seen_at;
