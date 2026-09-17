-- Reverts 20260917T1210_seed_administrator.up.sql.
--
-- The inverse of "create the first Administrator if there is not one" is
-- "remove the Administrator this migration created" — and nothing more. The
-- predicates below are what make that precise rather than destructive:
--
--   role = 'admin'              only an Administrator; never a Staff account
--   must_change_password        still unclaimed — nobody has set their own
--                               password on it
--   last_login_at IS NULL       and nobody has ever signed in as it
--   exactly one admin row       it is still the *seeded* one, not one of
--                               several an Administrator has since created
--
-- So stepping this migration down on a live system, where the account has been
-- claimed or other Administrators exist, deletes nothing. That is the intended
-- behaviour: a `down` must restore the previous shape, not take the product's
-- last way in with it.

DELETE FROM users
 WHERE role = 'admin'
   AND must_change_password
   AND last_login_at IS NULL
   AND (SELECT count(*) FROM users WHERE role = 'admin') = 1;
