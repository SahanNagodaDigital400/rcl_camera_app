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

### What is in `migrations/` today

| Version | What it creates |
|---|---|
| `20260917T1200_create_users` | the `users` table and its `lower(email)` unique index |
| `20260917T1210_seed_administrator` | the one seeded Administrator (a marker, see below) |
| `20260917T1300_create_sessions` | the `sessions` table — the architecture spine's `SESSION` ERD block, with `ON DELETE CASCADE` from `users` so deleting an account ends its sessions rather than orphaning them, a unique index on `token_hash` and an index on `user_id` |

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
  deactivated. Reissuing a credential is not a reactivation.

It changes the password, the expiry and nothing else. It runs at the console,
with the same environment access `make migrate` needs.

### Stepping the seed migration back

`down --yes` on the seed migration runs the file below.
`20260917T1210_seed_administrator.down.sql` deletes only an Administrator that
is still unclaimed *and* still the only one. On a live system it therefore
deletes nothing: a `down` must restore the previous shape, not take the
product's last way in with it.

### Not audited yet

Seeding and reissuing are user changes made outside the application, and
AGENTS.md Policy requires the append-only audit log to cover user changes. That
log arrives with Story 1.12, which owes these two paths their entries. Until
then the only record of either is the console output and `created_at` /
`updated_at` on the row.

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
