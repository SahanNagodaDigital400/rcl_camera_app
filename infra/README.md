# infra

Infrastructure-as-code, database migrations and deployment configuration.

Nothing is deployed yet. The migration runner and the `users` table are here
(Story 1.2); everything under "Open infrastructure decisions" still is not.

## Migrations — `migrations/`

- **Forward-only and reversible.** Every migration has a `down` that actually
  restores the previous shape. An applied migration is never edited; a mistake
  is corrected by a new migration (AGENTS.md Conventions).
- **One concern per migration**, named with a UTC timestamp prefix and a short
  verb phrase (`20260917T1030_create_tile.up.sql`, and its `.down.sql`).
- The audit log table is **append-only**: no migration may add an `UPDATE` or
  `DELETE` path to it, and neither may application code (AGENTS.md Policy).
  Since `20260921T1000_create_audit_log` that is enforced by PostgreSQL as
  well as by review — the role `apps/api` runs as holds `SELECT, INSERT` on
  that table and nothing else (AD-4). See "The application role" below.
- pgvector's floor is **≥ 0.8.2** — load-bearing, not cosmetic: CVE-2026-3172
  (buffer overflow in parallel HNSW index builds) affects 0.6.0–0.8.1 and AD-5
  mandates HNSW.

### File names

Every migration is a **pair**: `<version>.up.sql` and `<version>.down.sql`,
where `<version>` is a UTC timestamp and a short verb phrase
(`20260917T1200_create_users`). The runner refuses to plan a directory where
one half is missing or a name does not match that shape — a `down` that does
not exist is found at planning time, not halfway through a rollback.

### One transaction per migration

The file and its `schema_migrations` row commit together:

```sql
BEGIN;
  -- <contents of NNN_verb.up.sql>
  INSERT INTO schema_migrations (version) VALUES (%s);
COMMIT;
```

A migration that fails halfway therefore leaves neither, and the next run
retries it from a clean state rather than skipping something that only
half-applied.

**Migrate before you deploy the code that reads the new schema.** The two are
separate steps and nothing enforces their order: `api.sessions` names
`last_seen_at` in three of its statements, so a revision that ships ahead of
`20260917T1400_track_session_activity` fails *every authenticated request and
every sign-in* on an undefined column for the length of the gap.
`20260918T1000_add_login_throttling` is the same requirement again and wider —
`api.throttle` names `login_attempts` in all four of its statements, and
`users.locked_until` is selected by `api.sessions` and returned by both of
`api.auth`'s writes. A rollback is the requirement mirrored — roll the
application back first, then step the schema down, or the running code loses a
table and a column it is still selecting.

`20260921T1000_create_audit_log` is the sharpest version of that rule so far,
because the gap is not a failing endpoint but a service that cannot start:
`apps/api` asks for `role=rocell_app` at connection startup, so ahead of this
migration it cannot open a single connection. Stepping it back with the code
running is the same thing in reverse.

### What is in `migrations/` today

| Version | What it creates |
|---|---|
| `20260917T1200_create_users` | the `users` table and its `lower(email)` unique index |
| `20260917T1210_seed_administrator` | the one seeded Administrator (a marker, see below) |
| `20260917T1300_create_sessions` | the `sessions` table — the architecture spine's `SESSION` ERD block, with `ON DELETE CASCADE` from `users` so deleting an account ends its sessions rather than orphaning them (`DELETE /admin/users/{id}` relies on exactly this and deletes no session row itself), a unique index on `token_hash` and an index on `user_id` |
| `20260917T1400_track_session_activity` | `sessions.last_seen_at` — the idle half of a session's two deadlines (see below). No index on it, on purpose |
| `20260918T1000_add_login_throttling` | the `login_attempts` table — FR-4's failed-sign-in counter, keyed on the **submitted address** and never on `users.id` — plus `users.locked_until`, which mirrors a lock onto the account's status and is never read to decide anything. No index on either, on purpose (see below) |
| `20260921T1000_create_audit_log` | the `audit_log` table — FR-20's append-only record, with no foreign key to `users` (AD-10) and one index for the chronological read — **and** the `rocell_app` role the application runs as, with the grants that make the table append-only at the database level (AD-4) |

### The application role, and the append-only log

`20260921T1000_create_audit_log` creates two things that only make sense
together: the `audit_log` table, and `rocell_app` — the first database role in
this product that is not the owner.

`apps/api` adopts that role on every connection it opens (libpq's
`options=-c role=rocell_app`, in `apps/api/api/db.py`). The grants are:

| Object | `rocell_app` holds |
|---|---|
| `users`, `sessions`, `login_attempts` | `SELECT, INSERT, UPDATE, DELETE` |
| `audit_log` | `SELECT, INSERT` — **and nothing else** |
| `schema_migrations` | nothing; the runner owns the ledger and connects as the owner |

So an `UPDATE`, `DELETE` or `TRUNCATE` against the log is refused by
PostgreSQL with `InsufficientPrivilege`, whatever the application code says.
That is AD-4: the append-only rule survives a bug, a route added in a later
epic, or a migration that forgets the policy — none of which a reviewed pull
request can guarantee against. A wrong entry is corrected by inserting a
corrective entry, never by mutating the original.

Four consequences for anyone editing this directory:

1. **A new table needs its own `GRANT` in its own migration.** There is no
   `ALTER DEFAULT PRIVILEGES` here on purpose — default privileges apply only
   to objects created afterwards by the role that set them, which quietly
   makes "can the application read this" depend on who ran the migration.
   Spell it out and a forgotten grant is loud.
   `apps/api/tests/test_audit_immutability.py` asserts that every table in
   `public` except `audit_log` and `schema_migrations` is fully granted, so a
   missing one fails at `make test` rather than at the first request that
   touches it.
2. **The role is cluster-scoped; the grants are database-scoped.**
   `CREATE ROLE` writes to `pg_authid`, which every database on the server
   shares. The `up` is written so a second database replays it cleanly, and
   the `down` deliberately does **not** `DROP ROLE` — that would revoke it out
   from under every other database, and PostgreSQL would refuse while any of
   them still held a grant.
3. **The role has no password.** It is adopted over the owner's existing
   `DATABASE_URL`, so there is no second credential to store — which is the
   only honest shape while hosting and secrets management are both still
   deferred decisions. A separate login role with its own secret is the
   stronger form and is deployment-time hardening, not something a migration
   can decide.
4. **The owner must be a member of the role**, or it cannot adopt it. The
   migration grants `rocell_app` to whoever runs it. Migrate as the same role
   the application connects as, or grant it by hand.

The table itself carries `id`, `created_at`, `action`, `actor_user_id`,
`actor_email`, `target_user_id`, `target_email`, `source_ip` and a `details`
`jsonb`, with **no foreign key to `users`** (AD-10). That is not laziness: the
application role holds no `DELETE` on the log, so an FK would force a choice
between blocking every `DELETE /admin/users/{id}` and cascading into a table
nothing may delete from. The actor and target are denormalized snapshots —
the id joins while the row lives, the address is what the entry still means
after it does not. One index, `(created_at DESC, id DESC)`, for the
chronological read; `id` is the tiebreaker because `created_at` defaults to
`now()`, the transaction timestamp, so two entries written by one request
share it exactly.

`source_ip` comes from `TRUSTED_PROXY_HEADER` when that names a header and
from the connection's TCP peer when it does not — never from a raw
client-supplied header. See the root `README.md` for what to set and what
happens if you deploy behind a proxy and forget.

### The login throttle

`login_attempts` holds one row per address that has failed a sign-in recently.
The delay starts at the 6th consecutive attempt — the first one made after
five failures are already recorded — and the 10th failure locks the address
out for 15 minutes; the lock clears itself, and **no unlock command exists** —
`make migrate` has no counterpart for it, and **no story in Epic 1 owns one**.
Story 1.10 was where one was predicted; it shipped the user editor without it
(DW-64), so waiting it out remains the only recovery. It resets the run, so the
ladder is available again from the start. Two things the admin surfaces did
*not* change: an address change **carries** the run to the new address rather
than clearing it, and deactivating or **deleting** an account leaves its
address's row exactly where it was. So neither renaming, nor closing, nor
deleting and recreating an account is a way around a lock.

The key is the address as typed, lowercased and stripped — not an account.
An address that has never been a user accrues the same count, the same delays
and the same lock, which is what stops the ladder being a way to find out which
addresses are accounts. Two consequences for an operator: rows exist for
addresses that are not users and are expected, and a lock says nothing about a
person until you look at the account.

`users.locked_until` is the mirror, written on the failure that locks and never
cleared. A value in the past means "locked recently, not locked now". Nothing
enforces from it — `apps/api` reads `login_attempts` for every decision it
makes — so editing it changes what an Administrator sees and nothing else. It
goes with the row when an account is deleted, which is correct for the same
reason: it is the mirror, not the counter, and the counter stays behind.

Neither object carries an index. The primary key serves every read; the only
scan is the sweep, which runs on each failed attempt and deletes rows older
than an hour that are not under a live lock. That bounds the table's growth
over time — it does **not** bound its size during an attack. A guessing run
against a dictionary of addresses leaves a row per address that the sweep
cannot touch for an hour, and each failed attempt in the meantime scans them,
because `last_failure_at` is unindexed and the sweep's `LIMIT` bounds the rows
it returns rather than the rows it reads.

That is accepted on a bet about the steady-state row count, the same one
`sessions.last_seen_at` states. If you see the table grow, or see a run against
invented addresses, measure before adding an index on `last_failure_at` — it
would be paid on every failed sign-in.

### A session's two deadlines

A session dies at whichever of these comes first, and they are **two different
columns** because only one of them may ever move:

| Bound | Column | What extends it |
|---|---|---|
| 12 hours idle | `last_seen_at` | every authenticated request, throttled to one write a minute |
| 7 days absolute | `issued_at` | **nothing** |

`expires_at` is written once at sign-in and is never updated; the absolute
check is made against `issued_at` regardless, so no amount of activity can push
the 7-day ceiling. A user working through a shift is never signed out; a phone
left in a drawer on Friday is not a live credential on Monday; and a session
that has been used every hour for a week is still refused on the seventh day.

There is no warning before either deadline and no countdown — signing in again
is the whole of the recovery. A session refused for *any* of these reasons
answers the same `401` as a revoked one, a deactivated owner or an owner whose
account has been deleted outright, and says which it was to nobody.

`last_seen_at` carries no index deliberately: it is written on most
authenticated requests, and an index would be maintained on every one of those
writes and would block HOT updates.

What that costs, stated plainly: the sweep the login path runs matches
`expires_at <= now() OR last_seen_at <= now() - interval '12 hours'`, and a
disjunction across two columns where only one is indexed cannot use that index.
Its `LIMIT` bounds the rows *returned*, not the rows *read*, so a sweep that
finds little sequentially scans `sessions` on each sign-in. That is affordable
because of the table's size — roughly one row per live session for an internal
tool with tens of staff, swept on every sign-in so a backlog never accumulates
— and for no other reason. If `sessions` ever stops being small, measure before
adding an index.

`sessions.token_hash` holds the SHA-256 of the cookie's value, never the value
itself, so a database read yields nothing that can be presented as a session.
Passwords are Argon2id and session tokens are SHA-256 for different reasons —
see the module docstring in `apps/api/api/sessions.py`.

### The one non-SQL step

`20260917T1210_seed_administrator.up.sql` is a marker, not SQL: its body is the
directive `-- rocell:python seed_administrator`, which the runner recognises as
"call `rocell_infra.seed.seed_administrator` inside this migration's
transaction". An Argon2id digest cannot be computed in SQL, and hashing it
anywhere other than the single shared helper in `shared/schema` would let its
parameters drift from the login verifier's — producing a seeded password that
login cannot verify, with nothing raised.

## The migration runner — `rocell_infra`

```bash
make migrate                                       # apply every unapplied migration
uv run python -m rocell_infra.migrate status       # what is applied, what is pending
uv run python -m rocell_infra.migrate down --yes   # revert one step -- see the warning below
make reseed-admin                                  # see "The seeded Administrator"
```

**`down` is destructive.** It runs the migration's own down SQL, and two
invocations against a live database `DROP TABLE users` with every account in
it. It therefore refuses to run without an explicit `--yes`, and exits non-zero
saying so — a mistyped or copy-pasted `down` does nothing.

Every command needs `DATABASE_URL` and will exit non-zero naming it if it is
unset. Nothing is defaulted: a runner that guesses a connection string can
migrate the wrong database.

**The migrating role needs `CREATEROLE`** (or superuser). That is new with
`20260921T1000_create_audit_log`, which creates `rocell_app` and grants it:
until then every migration needed only write access to one database, and this
one needs a cluster-level privilege. Without it the run fails on the
`CREATE ROLE` with a plain `permission denied to create role` and applies
nothing — the migration and its ledger row commit together, so a half-created
role model is not a state you can reach. The same operator should run every
migration: `GRANT rocell_app TO current_user` needs ADMIN OPTION on the role,
which its creator holds and a second operator may not.

```bash
export DATABASE_URL=postgresql://rocell@localhost:5432/rocell
```

**`apps/api` now needs the same variable.** Since Story 1.3 the service opens a
connection pool at startup and reads `DATABASE_URL` to do it — pointed at the
database `make migrate` migrated. It is not defaulted there either, for the
same reason, and the process exits at startup naming the variable if it is
missing rather than failing at the first sign-in. `make dev` says so too.

## The seeded Administrator

The first Administrator is created **by the migration runner** — never by
application code, never through a UI. It is the only account in the product's
lifetime that no Administrator created, and it exists so the product has a way
in without ever opening a public sign-up path.

Its credentials come from the environment and are never committed:

| Variable | Required | Meaning |
|---|---|---|
| `SEED_ADMIN_EMAIL` | yes | the address the Administrator signs in with |
| `SEED_ADMIN_PASSWORD` | yes | 12 to 128 characters; hashed with Argon2id, never stored or logged in the clear |
| `SEED_ADMIN_NAME` | no | display name; defaults to `Rocell Administrator` |

```bash
export SEED_ADMIN_EMAIL=you@rocell.lk
read -rs SEED_ADMIN_PASSWORD && export SEED_ADMIN_PASSWORD
make migrate
```

Read the password with `read -rs` rather than typing it on the command line,
where it lands in shell history — and never as `make migrate
SEED_ADMIN_PASSWORD=…`, which also puts it in the process's arguments for `ps`
to show every other user on the machine.

The account is created `active`, with `must_change_password` set, so even the
very first sign-in is gated by the forced password change.

### Two independent idempotency layers

1. **The ledger.** `schema_migrations` stops the seed migration's body from
   running a second time.
2. **The guard.** The seed step itself does nothing if *any* `admin` row
   already exists — it returns before it even reads the environment.

A third layer covers the case neither of those does: each migration takes a
`pg_advisory_xact_lock` for the length of its transaction, so two concurrent
`make migrate` runs serialise instead of both observing an empty `users` table
and both inserting — which different `SEED_ADMIN_EMAIL` values would carry past
the unique index too.

Either of the first two alone would suffice against a sequential re-run. Both together are what make "never a second seeded
Administrator" true against an operator who truncates the ledger, restores an
old dump, or points the runner at a database it has already seeded. A
consequence worth knowing: on an already-seeded database, `make migrate` needs
no `SEED_ADMIN_*` variables at all.

### The 72-hour expiry, and `make reseed-admin`

The seeded credential is an admin-issued temporary credential, and AGENTS.md
gives those 72 hours without exception — so this one expires too. That leaves
one real hazard: if nobody claims the account inside that window there is no
Administrator left to reissue it, and the product is unreachable.

`make reseed-admin` is the answer. It reads the same `SEED_ADMIN_*` environment
— and `SEED_ADMIN_EMAIL` must be the address the account already carries, since
reissuing does not change it; supply a different one and the command refuses,
naming the stored address rather than handing you a credential for an account
that does not exist. It
hashes a fresh password and restarts the 72-hour clock on the *existing* row,
and it is deliberately narrow, so it can never become a back door into a live
system:

- it refuses once a **second Administrator exists** (reissue from the admin
  screens instead);
- it refuses once the account has been **claimed** — `must_change_password`
  cleared, or any recorded sign-in;
- it refuses against a database with no `users` table, naming `make migrate`
  rather than surfacing a driver error; and
- it never touches `active`, so an Administrator deactivated on purpose stays
  deactivated. Reissuing a credential is not a reactivation — reactivating is
  `POST /admin/users/{id}/activate`, in the running product, and it is another
  Administrator's to press.

It changes the password, the expiry and nothing else. It runs at the console,
with the same environment access `make migrate` needs.

**What the reissued credential is then good for.** Exactly one thing: signing
in and setting a real password. The first sign-in lands on the forced
password-change screen and reaches nothing else — no app bar, no navigation, no
way to dismiss it — and every API route that serves real data answers
`403 password_change_required` until the change is done (AGENTS.md: never grant
further access on a temporary credential before the forced change). Once the
new password is set the flag and the 72-hour expiry are both cleared, every
session opened on the temporary credential is revoked, and the account behaves
like any other. Hand the credential over accordingly: it is a one-use key to
the change screen, not an account someone can work from.

**The 72 hours are a deadline on claiming the account, not on signing in.**
Signing in inside the window does not bank the credential: a session outlives it
(seven days against three), and the change screen refuses a password once the
expiry has passed just as login refuses the credential itself — revoking the
sessions that were riding on it as it goes. Somebody who signs in on day one and
comes back on day four is locked out, and a retry will not help.

**Nor will `make reseed-admin`, in that one case.** It counts a recorded
sign-in as a claim, so the account it refuses to reissue includes the account
that signed in and never finished. There is no console path back in, and on a
database whose only Administrator is in that state the product is unreachable
until somebody with database access clears the sign-in by hand. Hand the
credential over with that in mind — the change is meant to be finished in the
same sitting as the sign-in. Making the reissue cover this case is deferred work
against `infra/rocell_infra/seed.py`, not something this story changed.

**Clearing it by hand.** The reissue selects on `must_change_password AND
last_login_at IS NULL`, and a lapsed account still carries the flag — so the
only thing standing between it and `make reseed-admin` is the recorded sign-in:

```sql
UPDATE users SET last_login_at = NULL, updated_at = now()
 WHERE email = '<the Administrator>' AND must_change_password;
```

Then run `make reseed-admin` as above; it writes a fresh password and a fresh
72-hour expiry, and the account is back to its first-sign-in state. The `AND
must_change_password` is not decoration: on an account that *did* claim itself
this statement must change nothing, because there `last_login_at` is history
rather than a lock, and blanking it would hand out a temporary credential for a
working account. Two people should watch this run. It is a database write with
no audit trail behind it — it is a `psql` write, outside the application
entirely, and the audit log only records what the application does — and it is
the one operation in this file
that can turn a claimed account back into a claimable one.

### Stepping the seed migration back

`down --yes` on the seed migration runs the file below.
`20260917T1210_seed_administrator.down.sql` deletes only an Administrator that
is still unclaimed *and* still the only one. On a live system it therefore
deletes nothing: a `down` must restore the previous shape, not take the
product's last way in with it.

### Not audited, and not an oversight

The append-only audit log exists (`20260921T1000_create_audit_log`), and
`make migrate` and `make reseed-admin` still write nothing to it. That is
deliberate rather than pending.

Both run **outside the application**, at a console, under the owner's own
database credentials. An audit entry names an actor and a source address, and
neither exists here: there is no session, no request and no signed-in
Administrator — the whole point of the seed is that it is the one account no
Administrator created. An entry for it would have to invent the actor, and a
log that invents one is worse than a log with a gap, because nothing
downstream can tell an invented actor from a real one.

So the record of a seed or a reissue remains what it always was: the console
output, and `created_at` / `updated_at` on the row. The operational control is
that both commands are narrow — the seed refuses once any Administrator
exists, the reissue refuses once the account has been claimed or a second
Administrator exists — and that running either needs database credentials
somebody had to be given. The same reasoning covers `scripts/ingest`, which
the architecture spine puts outside the audit trail by design.

## Testing

Migration SQL uses nothing newer than PostgreSQL 13, so a 16.x test cluster and
the 18.x deployment target agree about what it means.

`infra/tests` runs against a real PostgreSQL. It uses `TEST_DATABASE_URL` when
that is set, and otherwise starts a throwaway cluster with `initdb` + `pg_ctl`
on a free `127.0.0.1` port, skipping if neither is available. Each test gets a
freshly created empty database. No password appears anywhere in the suite —
every one is generated at runtime.

## Open infrastructure decisions (deferred by the architecture spine)

- **Object storage provider** — S3-compatible API is fixed; the provider is not.
- **PostgreSQL 18.x + pgvector compatibility** — verified pgvector testing as of
  the spine's writing covers PostgreSQL 16 and 17. Confirm 18 at build time
  before pinning the deployment.
- **Deployment target and topology** — not chosen.
- **CI pipeline** — not set up; `make lint` and `make test` are the contract a
  pipeline will eventually run.
- **Secrets management** — environment or a secret store; never committed, never
  hardcoded, not even in test fixtures (AGENTS.md Policy).
