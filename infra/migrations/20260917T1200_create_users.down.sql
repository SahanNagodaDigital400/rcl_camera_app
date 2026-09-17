-- Reverts 20260917T1200_create_users.up.sql, restoring the previous shape: no
-- `users` table at all. Dropping the table drops its index with it; the index
-- is named here anyway so the file reads as the exact inverse of the `up`.

DROP INDEX IF EXISTS users_email_lower_key;

DROP TABLE IF EXISTS users;
