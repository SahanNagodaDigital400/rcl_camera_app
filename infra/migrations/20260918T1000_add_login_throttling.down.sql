-- Reverts 20260918T1000_add_login_throttling.up.sql, restoring the previous
-- shape: no failed-attempt counters anywhere, and the eleven-column `users`
-- table `20260917T1200_create_users` defines.
--
-- **Deploy the code first, then step this back — never the other way round.**
-- `api/throttle.py` names `login_attempts` in every statement it owns,
-- `api/auth.py` returns `users.locked_until` from `_RECORD_LOGIN` and
-- `_SET_PASSWORD`, and `api/sessions.py` selects it in `_SELECT_SESSION`. With
-- the current code running, dropping either object makes *every authenticated
-- request* and *every sign-in* fail on an undefined relation or column — the
-- whole product, not a degraded corner of it. The order is: roll the
-- application back to a revision that names neither, confirm it is serving,
-- then run this.
--
-- Once that ordering is respected the revert costs nothing irrecoverable, but
-- it is not free either, and the cost is stated rather than implied: every
-- in-progress lockout is released and every recorded failure is forgotten, so
-- an attack in flight gets its full ladder back from zero. `users.locked_until`
-- goes with it, taking the record of which accounts were locked and when.
-- Nothing else depends on either — no foreign key points at `login_attempts`,
-- by design, because most of what it holds has no account behind it.

DROP TABLE IF EXISTS login_attempts;

ALTER TABLE users
    DROP COLUMN IF EXISTS locked_until;
