---
title: 'User Schema & Seeded Administrator'
type: 'feature'
created: '2026-09-10'
status: 'done'
baseline_revision: '63f6a23faba52c602c4e38005402f15475c8fbca'
review_loop_iteration: 0
followup_review_recommended: false
context: []
warnings: [oversized]
deferred:
  - summary: >-
      infra/migrate.py has no advisory-lock or other concurrency protection
      against two simultaneous `make migrate` invocations against the same
      database.
    evidence: |-
      A race would cause one process to fail cleanly on the
      `schema_migrations` unique-constraint insert (each migration runs in
      its own transaction, so no partial/corrupt state results) rather than
      corrupting data -- but it's still an unhandled race. Not exercised
      today: no deploy pipeline exists yet (hosting/CI/CD is explicitly
      Deferred in ARCHITECTURE-SPINE.md), so concurrent invocation isn't a
      realistic scenario until one does.
    location: infra/migrate.py
    severity: low
  - summary: >-
      No database constraint ties `must_change_password` to
      `temp_credential_expires_at` -- a row could in principle carry one
      flag without the other in a mutually inconsistent state.
    evidence: |-
      This story's only writer (the seed migration) always sets both
      consistently, so no inconsistent row exists today. But the exact
      semantics of forced-password-change outside the migration-seeded case
      (e.g. can an Administrator force a password change with no expiry?)
      are Story 1.4's or 1.8's decision to make, not this story's -- adding
      a CHECK constraint now would fabricate scope neither story has
      defined yet.
    location: infra/migrations/0001_create_users.py
    severity: low
---

<intent-contract>

## Intent

**Problem:** No database schema exists yet, so there is nothing to authenticate against — Story 1.3 (login) needs a `User` table and at least one account to sign in as, without ever opening a public registration path.

**Approach:** Add a minimal forward-only migration runner (`infra/`, first use of this directory beyond its Story 1.1 placeholder README) with two migrations: one creating the `users` table per the architecture spine's ERD, one seeding exactly one Administrator account whose credentials come from environment variables, never hardcoded.

## Boundaries & Constraints

**Always:** `users` table carries `id` (uuid, `gen_random_uuid()` default), `name`, `email` (unique), `password_hash`, `role` (`staff`|`admin`, matching AGENTS.md Policy's literal values), `active` (default true), `must_change_password`, `temp_credential_expires_at` (nullable), `created_at`. Migrations are forward-only Python modules under `infra/migrations/`, tracked in a `schema_migrations` table, applied in filename order, each run inside its own transaction — a second `make migrate` run is a no-op. Passwords hashed with Argon2id (`argon2-cffi`'s default `PasswordHasher`) only. The seeded Administrator is created with `must_change_password = true` and `temp_credential_expires_at = now() + 72h` (FR-2's window), sourced from `SEED_ADMIN_EMAIL` / `SEED_ADMIN_NAME` / `SEED_ADMIN_PASSWORD` env vars — never a literal in code or migration source (AGENTS.md: never hardcode secrets; brief addendum.md: secrets via env/secret store only).

**Block If:** Nothing in this story requires a human decision outside the repo — no hosting/provider choice is needed to create a local schema and seed migration.

**Never:** No `Session` or `AuditLogEntry` tables this story — `epics.md`'s AC for this story names only the `User` table; those land in Stories 1.5 and 1.12. No `apps/api` auth endpoints (Story 1.3). No ORM (SQLAlchemy/Alembic) — raw SQL executed via `psycopg` from small Python migration modules, not introduced elsewhere in the stack table. No pgvector extension work (catalogue epic only).

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Fresh DB, seed env vars set | Empty DB; `SEED_ADMIN_EMAIL`/`NAME`/`PASSWORD` set | `users` table created; exactly one row, `role='admin'`, `must_change_password=true`, `temp_credential_expires_at` ≈ now+72h | No error expected |
| Re-run after already applied | `schema_migrations` already has both migrations recorded | No-op; still exactly one admin row | No error expected |
| Missing seed env var | Fresh DB; `SEED_ADMIN_PASSWORD` unset | Seed migration aborts before inserting any row | Clear error naming the missing variable; migration not recorded as applied |
| Reseed attempted on non-empty DB | DB already has a user with the seed email | Insert fails on the `email` unique constraint rather than duplicating | DB-level unique-violation error surfaces as a migration failure |

</intent-contract>

## Code Map

- `_bmad-output/planning-artifacts/architecture/architecture-rcl_camera_app-2026-08-30/ARCHITECTURE-SPINE.md:222-228` -- `USER` ERD box: authoritative field list (`role`, `active`, `must_change_password`, `temp_credential_expires_at`)
- `_bmad-output/planning-artifacts/epics.md:187-202` -- Story 1.2's exact Given/When/Then AC text (idempotency, seed-by-migration-not-app-code, `must_change_password` gate)
- `infra/README.md` -- states migrations start here, forward-only/reversible convention, notes `make migrate` doesn't exist yet -- both need updating by this story
- `AGENTS.md` -- Argon2id-only hashing; never hardcode secrets; migrations forward-only and reversible; "Never add roles beyond `staff` and `admin`" (literal role values to use)
- `_bmad-output/planning-artifacts/briefs/brief-rcl_camera_app-2026-08-25/addendum.md:26` -- "Secrets in a managed secret store or environment variables — never committed to the repo"
- `pyproject.toml` (root) -- `[tool.uv.workspace]` members, `[tool.pytest.ini_options]` testpaths, `[tool.ruff] src` -- add `infra`
- `Makefile` -- `lint`/`test`/`PY_DIRS` -- add `infra`; add new `migrate` target

## Tasks & Acceptance

**Execution:**
- `infra/pyproject.toml` -- new `rcl-infra` package, deps `psycopg[binary]>=3.2`, `argon2-cffi>=23` -- no ORM, mirrors the project's avoid-unneeded-infra stance
- `infra/migrate.py` -- runner: reads `DATABASE_URL` (fails clearly if unset), creates `schema_migrations` (`id serial pk`, `name text unique`, `applied_at timestamptz default now()`) if absent, applies pending `infra/migrations/NNNN_*.py` modules in filename order, each in its own transaction, recording `name` on success
- `infra/migrations/__init__.py` -- empty, makes migrations a discoverable/importable package
- `infra/migrations/0001_create_users.py` -- `up(cur)` creates `users` table with the columns listed in Boundaries & Constraints, `role` CHECK constraint `IN ('staff','admin')`
- `infra/migrations/0002_seed_administrator.py` -- `up(cur)` reads the three `SEED_ADMIN_*` env vars (raises a clear error naming any missing one before touching the DB), hashes the password with `argon2-cffi`'s `PasswordHasher`, inserts one row (`role='admin'`, `active=true`, `must_change_password=true`, `temp_credential_expires_at=now()+72h`)
- `infra/tests/test_migrate.py` -- against a real Postgres (`DATABASE_URL`): fresh schema → migrate → assert table shape + exactly one seeded admin with correct flags/expiry; migrate again → still exactly one; missing `SEED_ADMIN_PASSWORD` → asserts the abort and that no partial row was inserted
- `infra/README.md` -- document `make migrate`, the four required env vars (`DATABASE_URL` + three `SEED_ADMIN_*`), the local-Postgres test prerequisite; remove the now-stale "No `make migrate` target exists yet" line
- `Makefile` -- add `migrate` target (`uv run --project infra python -m infra.migrate` or equivalent); add `infra` to `PY_DIRS`
- `pyproject.toml` (root) -- add `infra` to `[tool.uv.workspace] members`, `[tool.uv.sources]`, root `dependencies`, `[tool.pytest.ini_options] testpaths`, `[tool.ruff] src`

**Acceptance Criteria:**
- Given a clean Postgres database, when `make migrate` runs, then the `users` table exists with the columns above and exactly one row exists with `role='admin'` and `must_change_password=true`
- Given `make migrate` has already been run once, when it is run again, then it exits 0 and exactly one admin row still exists
- Given any of `SEED_ADMIN_EMAIL`/`SEED_ADMIN_NAME`/`SEED_ADMIN_PASSWORD` is unset, when `make migrate` runs, then it fails with a clear error and inserts no admin row
- Given the repo root with a reachable `DATABASE_URL`, when `make lint` and `make test` run, then both exit 0

## Spec Change Log

## Review Triage Log

### 2026-09-10 — Review pass

- intent_gap: 0
- bad_spec: 0
- patch: 9 (high 0, medium 3, low 6)
- defer: 2 (high 0, medium 0, low 2)
- reject: 9 (high 0, medium 0, low 9)
- addressed_findings:
  - `[medium]` `[patch]` `Makefile`'s `test` target ran `uv run pytest` then `cd apps/web && npm test` sequentially, so a Postgres-related pytest failure (the new, now-common case of `DATABASE_URL` being unset) aborted the recipe before the `apps/web` suite ever ran — a real frontend regression could pass `make test` silently whenever Postgres wasn't provisioned. Decoupled the two so both always run and the target fails if either does, verified live by breaking a vitest assertion with `DATABASE_URL` unset: `apps/web`'s failure is now reported.
  - `[medium]` `[patch]` `infra/migrations/0001_create_users.py`'s `email UNIQUE` constraint was case-sensitive, so `Admin@x.com` and `admin@x.com` could both be seeded/created as distinct accounts — added a case-insensitive unique index (`lower(email)`) and lowercased the seed migration's insert; verified live that inserting a case-variant of the seeded admin's email now fails on the new index.
  - `[medium]` `[patch]` `infra/tests/test_migrate.py`'s fixture unconditionally ran `DROP TABLE IF EXISTS users`/`schema_migrations` against whatever `DATABASE_URL` pointed at, so an operator accidentally running `make test` against a real/shared database would silently destroy its user table — added a guard requiring the database name to look disposable/test-only before the fixture will reset it; verified it refuses and fails clearly against a non-test-named database.
  - `[low]` `[patch]` `0002_seed_administrator.py` treated a whitespace-only `SEED_ADMIN_*` value as present (Python truthiness) — now stripped before the presence check, so `" "` is treated as missing; verified live.
  - `[low]` `[patch]` `infra/migrate.py`'s `psycopg.connect` had no timeout, so an unreachable `DATABASE_URL` would hang indefinitely instead of failing fast — added `connect_timeout=10`.
  - `[low]` `[patch]` A migration file whose name didn't match the `NNNN_*.py` glob would silently never run with no error — added a check that raises clearly if any non-`__init__.py` file in `infra/migrations/` doesn't match the expected pattern.
  - `[low]` `[patch]` `infra/pyproject.toml` declared `py-modules = ["migrate"]`, but nothing imports `migrate` as an installed module (tests invoke it via subprocess by file path) — removed the dead/misleading declaration.
  - `[low]` `[patch]` No test exercised `infra/migrate.py`'s own `DATABASE_URL`-unset early-exit path (only the seed-var-missing path was tested) — added a test asserting it exits non-zero with a clear stderr message.
  - `[low]` `[patch]` `infra/README.md`'s new Migrations section dropped the word "reversible" from AGENTS.md's own "forward-only and reversible" convention it cites — restored it.
  - `[low]` `[defer]` No advisory-lock/concurrency protection against two simultaneous `make migrate` invocations — relevant once a real deploy pipeline exists; hosting/CI/CD is explicitly Deferred in `ARCHITECTURE-SPINE.md` and no pipeline exists yet to make concurrent invocation likely.
  - `[low]` `[defer]` No constraint ties `must_change_password` to `temp_credential_expires_at` consistency — the exact semantics of forced-password-change outside the migration-seeded case belong to Story 1.4 or 1.8, not this one.
  - `[reject]` Findings mooted by the architecture's pinned stack or explicit existing scope decisions: `gen_random_uuid()` needing `pgcrypto`/version docs (PostgreSQL is pinned to 18.x, where it's a core builtin); no docker-compose/CI to provision `DATABASE_URL` for `make test` (duplicates the already-tracked `DW-2` / `ARCHITECTURE-SPINE.md`'s explicitly Deferred CI/CD pipeline); no secrets-manager location documented for non-local `SEED_ADMIN_*` values (secrets management approach is itself explicitly Deferred in `ARCHITECTURE-SPINE.md`).
  - `[reject]` Findings with no requirement basis anywhere in the PRD/architecture: password strength/complexity or email-format validation on seed credentials (operator-trusted input, not attacker-facing, and no FR specifies such rules); a speculative `updated_at` column on `users`.
  - `[reject]` Test-coverage nit that doesn't correspond to distinct logic: the missing-env-var test covers only `SEED_ADMIN_PASSWORD`, but all three `SEED_ADMIN_*` vars share one identical validation loop, so one covering test already exercises the shared code path.
  - `[reject]` Cosmetic/unactionable: a hardcoded `ARCHITECTURE-SPINE.md:222-228` line-range reference in a docstring that could go stale; no documented runbook for migration-failure recovery beyond the already-stated "never edit an applied migration, add a new one" convention.

### 2026-09-10 — Review pass (follow-up)

- intent_gap: 0
- bad_spec: 0
- patch: 8 (high 0, medium 1, low 7)
- defer: 0
- reject: 22 (high 0, medium 0, low 22)
- addressed_findings:
  - `[medium]` `[patch]` The seeded Administrator's `password_hash` was never verified against the plaintext `SEED_ADMIN_PASSWORD` in any test -- a broken hash (wrong source value, wrong hasher) could ship undetected and lock out the only account able to sign in. Added `test_seeded_password_hash_verifies_against_the_seed_password`, asserting `PasswordHasher().verify()` succeeds against the stored hash.
  - `[low]` `[patch]` The case-insensitive `users_email_lower_key` index (added last pass specifically to catch `Admin@x.com`/`admin@x.com` collisions) had no test that actually inserts a case-variant duplicate -- the existing reseed test's duplicate used the identical-case email, so a plain column-level `UNIQUE` alone would have satisfied it. Added `test_case_variant_duplicate_email_violates_unique_index`, inserting an upper-cased duplicate of the seeded email and asserting a `UniqueViolation`.
  - `[low]` `[patch]` The seed migration's `email.lower()` normalization was untested with mixed-case input -- the fixture's seed email was already all-lowercase, so removing that line would not have failed any test. Added `test_seed_email_is_lowercased_when_given_mixed_case`, seeding with `Admin@Rocell.Test` and asserting the stored value is lowercase.
  - `[low]` `[patch]` The `role CHECK (role IN ('staff','admin'))` constraint, called out in `0001_create_users.py`'s own docstring as "never add a third," had no test attempting an invalid role. Added `test_invalid_role_violates_check_constraint`, asserting a `CheckViolation` on an out-of-enum insert.
  - `[low]` `[patch]` `_assert_database_looks_disposable` only checked that the database *name* contained `test`, so a test-named database hosted on a non-local (e.g. staging/production) host would still pass the guard and get its `users` table dropped. Extended the guard to also require the host resolve to a local address (`localhost`/`127.0.0.1`/`::1`/unspecified); verified live that a non-local host now fails the guard regardless of database name.
  - `[low]` `[patch]` `_discover_migrations` guarded against a malformed `NNNN_*.py` filename but had no test proving it; also had no guard at all against two migration files sharing the same 4-digit ordinal (they would silently apply in alphabetical tie-break order instead of raising). Added both a duplicate-ordinal check (mirroring the existing malformed-filename check) and two unit tests (`test_discover_migrations_rejects_malformed_filename`, `test_discover_migrations_rejects_duplicate_ordinal`) that monkeypatch `MIGRATIONS_DIR` to a `tmp_path` fixture.
  - `[low]` `[patch]` `main()`'s `DATABASE_URL` check used plain truthiness, so a whitespace-only value would pass the "is it set" check and fail later with an opaque `psycopg` connection error instead of the intended clear "DATABASE_URL is not set" message (the same class of bug already fixed for `SEED_ADMIN_*` last pass). Stripped before the check.
  - `[reject]` (22 findings, all low/none-impact, dropped silently) -- duplicates of already-deferred/-rejected items from the prior pass (concurrent-`make migrate` locking = DW-7; `must_change_password`/`temp_credential_expires_at` consistency CHECK = DW-8; password-strength/email-format validation on operator-trusted seed credentials; `gen_random_uuid()` PG-version/`pgcrypto` prerequisite -- PostgreSQL is pinned to 18.x where it's core); findings that contradict the intent-contract itself (`PasswordHasher()` using library defaults is exactly what "argon2-cffi's default `PasswordHasher`" requires; an audit-log entry for the seed action is explicitly excluded by this story's "Never" list); already-deliberate, already-documented decisions revisited (README's "reversible" wording is inherited AGENTS.md convention, not a code claim; `make test` requiring a live Postgres and the case-insensitive email index were both explicit, reasoned decisions from the prior review pass, not oversights); test-design nits with no distinct-logic gap (reseed test's manual-insert path, idempotency test re-running vs. priming state); the hardcoded `users_email_key` string in one assertion's `or` clause (already covered by its `"unique" in stderr.lower()` fallback); and speculative edge cases with no realistic trigger given the current fixed repo layout and no-production-environment state (empty migrations directory, a `users` table existing with no `schema_migrations` row, `up(cur)` not receiving the connection, missing success logging, unused `pyproject.toml` packaging config, no `sslmode` enforcement, redundant `UNIQUE` alongside the `lower(email)` index, no fast unit tests isolating pure logic from a live database).

### 2026-09-10 — Review pass (fresh follow-up)

- intent_gap: 0
- bad_spec: 0
- patch: 2 (high 0, medium 0, low 2)
- defer: 0
- reject: 23 (high 0, medium 0, low 23)
- addressed_findings:
  - `[low]` `[patch]` `Makefile`'s `migrate` help line named only `DATABASE_URL` as required, omitting `SEED_ADMIN_EMAIL`/`SEED_ADMIN_NAME`/`SEED_ADMIN_PASSWORD`, which `0002_seed_administrator.py` also requires on first run -- updated the help text to list all four; verified via `make lint`.
  - `[low]` `[patch]` `infra/migrate.py`'s `AttributeError` guard for a migration module defining no `up(cur)` had zero test coverage (confirmed by a reviewer who neutered the guard and saw all tests still pass) -- added `test_run_raises_when_migration_defines_no_up`, exercising `run()` directly against a `tmp_path`-overridden `MIGRATIONS_DIR` containing a migration with no `up`, asserting the raise and that nothing is recorded in `schema_migrations`; verified live against a local Postgres (`infra/tests/test_migrate.py`: 12/12 passed, up from 11).
  - `[reject]` (23 findings, all low, dropped silently) -- duplicates of items already deferred (`DW-7` concurrent-`make migrate` locking, incl. a lock/statement-timeout variant of the same underlying race; `DW-8` `must_change_password`/`temp_credential_expires_at` consistency) or already rejected in the two prior passes (password-strength/email-format validation on operator-trusted seed credentials; `PasswordHasher()` using library defaults, which is exactly what the intent-contract requires; speculative `updated_at` column; redundant `UNIQUE` alongside the `lower(email)` index; unused `pyproject.toml` packaging scope; hardcoded `ARCHITECTURE-SPINE.md` line-range doc reference; `make test` requiring a live local Postgres and its `pytest.fail`-not-skip behavior, both deliberate documented decisions; idempotency achieved via `schema_migrations`-skip rather than idempotent `up()` bodies, also a deliberate documented decision per Design Notes; the reseed test's manual-insert construction path; missing-env-var test coverage for `SEED_ADMIN_EMAIL`/`NAME` given all three share one validation loop; no docker-compose/CI to provision `DATABASE_URL`, duplicating the already-tracked `DW-2`); plus newly surfaced but out-of-scope or no-realistic-trigger findings (no `down()`/explicit migration-rollback function -- AGENTS.md's "reversible" is already defined, and restored in pass 1, as "add a new migration, never edit an applied one," not a `down()` mechanism; no credential-rotation runbook for the seeded admin, outside this story's scope and Story 1.4/1.8's to define; missing-migrations-directory and async/no-op `up()` guards, with no realistic trigger given the fixed repo layout; a `sha256` content-drift check against the "never edit an applied migration" convention, which is a process guard by design, not a code one; an additional destructive-test-fixture env-flag gate beyond the name+host guard already hardened twice; and intent-alignment observations about test-invocation surface (`subprocess` vs. `make migrate` itself, a trivial wrapper) that name no distinct defect).
  - See `## Auto Run Result` below for full verification details.

## Design Notes

- **Role values are lowercase `staff`/`admin`**, not the PascalCase `Staff`/`Administrator` used for prose/entity naming elsewhere in the spine — AGENTS.md's Policy line names the roles with literal backticks (`` `staff` ``/`` `admin` ``), and Story 1.1's UX Design Notes already named components `badge-role-admin`/`badge-role-staff`. The spine's PascalCase convention governs type/entity names, not this stored enum value.
- **Migrations are Python modules, not `.sql` files** — seeding needs Argon2id hashing, which plain SQL can't do. Keeping every migration in one format (Python, executed via `psycopg`) avoids running two different migration mechanisms side by side for what is otherwise the same forward-only, tracked-in-`schema_migrations` pattern.
- **`make test` now requires a reachable local Postgres** (`DATABASE_URL`) — an unavoidable, new dev-environment prerequisite once DB-backed schema exists, not scope creep. Documented in `infra/README.md`.
- **New dependencies** (flagging per AGENTS.md): `psycopg[binary]>=3.2` (Postgres driver; no ORM chosen — mirrors the project's stance against unneeded infrastructure), `argon2-cffi>=23` (Argon2id hashing via its default `PasswordHasher`).
- Idempotency (AC: "re-running migrations is idempotent") falls directly out of the runner design — `0002_seed_administrator` is recorded in `schema_migrations` after its first successful run and is never re-executed — no separate "does an admin already exist" check is needed or added.

## Verification

**Commands:**
- `uv sync` -- expected: installs `infra`'s new dependencies with no errors
- `DATABASE_URL=<local-test-db-url> make migrate` -- expected: exit 0; `users` table exists with exactly one `role='admin'` row, `must_change_password=true`
- Re-run the same `make migrate` command -- expected: exit 0; still exactly one admin row (no duplicate)
- `make lint` -- expected: exit 0 (ruff clean across Python dirs including `infra`; eslint/`tsc -b` clean in `apps/web`, unchanged from Story 1.1)
- `make test` -- expected: exit 0, requires `DATABASE_URL` to point at a reachable local Postgres per `infra/README.md`

## Auto Run Result

**Summary:** This run performed a fresh review pass (per the `bmad-build-auto` `done`-status re-entry rule) over the already-implemented user schema + seeded Administrator migration. No new implementation was requested; the pass ran four parallel review layers (blind-hunter, edge-case-hunter, verification-gap, intent-alignment) against the diff since `baseline_revision`, triaged 25 findings, and applied the two that survived triage as trivial patches.

**Files changed this pass:**
- `Makefile` -- `migrate` help text now lists all four required env vars (`DATABASE_URL`, `SEED_ADMIN_EMAIL`, `SEED_ADMIN_NAME`, `SEED_ADMIN_PASSWORD`), not just `DATABASE_URL`.
- `infra/tests/test_migrate.py` -- added `test_run_raises_when_migration_defines_no_up`, closing a verification gap on the "migration defines no `up(cur)`" guard in `infra/migrate.py`.

**Review findings breakdown:** patch: 2 (low, low) applied; defer: 0; reject: 23 (all low) -- see Review Triage Log entry above for the full list, mostly duplicates of items already deferred (`DW-7`, `DW-8`) or rejected in the two prior review passes.

**Follow-up review recommendation:** `false` -- this pass's patched findings were 2 low, 0 medium, 0 high (score `3*0 + 1*2 = 2`, below the `5` threshold; no high-severity patch).

**Verification performed** (against a local disposable Postgres, `rcl_camera_app_test`, created for this run):
- `uv sync` -- exit 0, no errors.
- `make migrate` (fresh DB) -- exit 0; `users` table created; exactly one `role='admin'` row, `must_change_password=true`.
- `make migrate` re-run -- exit 0; still exactly one admin row.
- `make lint` -- exit 0 (ruff clean across all `PY_DIRS` including `infra`; eslint/`tsc -b` clean in `apps/web`).
- `make test` -- exit 0; 16 passed (12 in `infra/tests/test_migrate.py`, up from 11, plus the pre-existing `apps/api`/`shared/vision`/`shared/schema`/`scripts/ingest` import smoke tests) and 5 `apps/web` vitest tests passed.

**Residual risks:** None new. The two items already tracked in `deferred` (concurrent-`make migrate` locking; no DB constraint tying `must_change_password` to `temp_credential_expires_at`) remain open and unchanged by this pass -- both require decisions (a deploy pipeline; Story 1.4/1.8's forced-password-change semantics) outside this story's scope.

