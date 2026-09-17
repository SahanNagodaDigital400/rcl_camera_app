-- Story 1.6 — FR-4's failed-attempt counters, and the status they mirror.
--
-- Two objects, and the relationship between them is one-directional:
--
--   login_attempts        the counter AD-8 requires — a row in Postgres,
--                         mutated by ONE atomic increment-and-check, never
--                         in-process memory. This is what `POST /auth/login`
--                         reads to decide a delay and a lockout. It decides
--                         everything.
--   users.locked_until    a MIRROR of that decision, for FR-4's "visible to
--                         Administrators on that user's status". It reports;
--                         it never decides. Nothing in the enforcement path
--                         reads it, and a value in the PAST means "not locked
--                         now, locked recently" rather than "locked" — the
--                         column is history as well as status, and is never
--                         cleared once written.
--
-- **The counter is keyed on the SUBMITTED ADDRESS, not on `users.id`, and that
-- is the whole reason this table exists rather than two columns on `users`.**
-- `POST /auth/login` answers an unknown address, a wrong password, a
-- deactivated account and an expired temporary credential with one identical
-- rejection, down to the headers and the elapsed time (`api/auth.py`,
-- `verify_dummy_password`, EXPERIENCE.md's deactivated-account row). A delay
-- ladder attached to an account undoes all of it: post six wrong passwords at
-- a candidate address, and a delay means the account exists while an instant
-- answer means it does not. Keyed on the address the caller submitted — the
-- same lowercased, stripped value the credential lookup is parameterized with
-- — a garbage address accrues exactly the same count, the same delay and the
-- same lock, so the ladder carries no signal. The cost is rows for addresses
-- that were never accounts, which is what `last_failure_at` and the bounded
-- sweep in `api/throttle.py` are for.
--
-- `email_key` is therefore deliberately NOT a foreign key to `users` and never
-- becomes one: most of what it holds has no account behind it, and the rest
-- must survive one being deleted.
--
-- `failure_count` carries its own CHECK rather than trusting the one statement
-- that writes it. The statement resets-or-increments and can only produce 1 or
-- n+1; the constraint is what says so to the next statement somebody adds.
--
-- Deliberately NO INDEX, on either object, and the cost of that is stated
-- honestly rather than talked down. The primary key serves every read
-- (`WHERE email_key = %s`). The only scan is the stale-row sweep, which reads
-- on the unindexed `last_failure_at`, and what the sweep bounds is the table's
-- growth over time — **not** its size during an attack. A row is eligible only
-- once it is older than the attempt window (1 hour) and not under a live lock,
-- so a guessing run against a dictionary of addresses fills this table with
-- rows the sweep deliberately cannot touch for an hour, and every failed
-- attempt in the meantime sequentially scans them. The `LIMIT` bounds the rows
-- the sweep *returns*, not the rows it reads — the same property
-- `20260917T1400_track_session_activity` states for its own sweep.
--
-- That is accepted on the same bet as `sessions.last_seen_at`, and it is a bet
-- on the steady-state row count for an internal tool with tens of staff: one
-- row per address that has failed a sign-in in the last hour. It is not a bet
-- on the plan, and it is not a claim that the table cannot get large. If it
-- does — or if a run against invented addresses is ever observed — MEASURE
-- before adding an index on `last_failure_at`, which would be paid on every
-- failed sign-in.
--
-- `users.locked_until` gets no index for a stronger reason: nothing filters on
-- it. It is selected alongside the other ten `User` columns by id or by
-- `lower(email)`, and Story 1.9's user list renders it rather than searching
-- it.
--
-- **Apply this before deploying the code that reads these objects.**
-- `api/throttle.py` names `login_attempts` in all four of its statements,
-- `api/auth.py` returns `users.locked_until` from `_RECORD_LOGIN` and
-- `_SET_PASSWORD`, and `api/sessions.py` selects it in `_SELECT_SESSION` — so
-- a revision that ships ahead of this migration fails *every authenticated
-- request and every sign-in* on an undefined column for the length of the gap.
-- Migrate, confirm both objects are there, then roll the application forward.
-- The `.down.sql` states the mirror of that ordering for a revert.
--
-- `IF NOT EXISTS` on both, matching the four before it: a truncated ledger
-- must be able to replay the whole set.

CREATE TABLE IF NOT EXISTS login_attempts (
    -- The lowercased, stripped address as submitted. See above: never a
    -- `users.id`, never a foreign key.
    email_key        text        PRIMARY KEY,
    failure_count    integer     NOT NULL DEFAULT 0 CHECK (failure_count >= 0),
    -- NULL means "no lock". A future instant means the address is locked out
    -- now; the row is reset to a fresh run on the first attempt after it
    -- lapses, so a past value never survives here.
    locked_until     timestamptz,
    -- When this run was last added to. Both the stale-run reset and the sweep
    -- are measured from it, against the database clock.
    last_failure_at  timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS locked_until timestamptz;
