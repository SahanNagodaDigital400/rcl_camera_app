---
title: 'Story 1.2 — User Schema & Seeded Administrator'
type: 'feature'
created: '2026-09-17'
baseline_revision: '260d12f7cd1ec657013fd9ddfb2463337080f203'
status: 'done'
review_loop_iteration: 0
followup_review_recommended: true # score 19 (4x3 medium + 7x1 low); see Auto Run Result
context:
  - '{project-root}/AGENTS.md'
  - '{project-root}/infra/README.md'
  - '{project-root}/_bmad-output/planning-artifacts/architecture/architecture-rcl_camera_app-2026-08-30/ARCHITECTURE-SPINE.md'
warnings: ['oversized']
deferred:
  - summary: >-
      `status` reports only the migrations it finds on disk, so a version
      recorded as applied whose `.sql` files were deleted or renamed is
      invisible in the one command an operator reaches for first.
    evidence: |-
      infra/rocell_infra/migrate.py's status iterates the plan and reports each
      file's applied flag. `down` raises a hard error for exactly that
      condition, so the diagnostic command stays silent about the state the
      destructive command refuses on.
    location: >-
      infra/rocell_infra/migrate.py
    severity: low
  - summary: >-
      `updated_at` has a DEFAULT but no trigger, so every future writer
      (Stories 1.3, 1.5, 1.10, 1.11) has to remember to set it by hand and
      nothing catches the first one that forgets.
    evidence: |-
      20260917T1200_create_users.up.sql declares `updated_at timestamptz NOT
      NULL DEFAULT now()` with no BEFORE UPDATE trigger. Only the reseed path
      sets it explicitly today. Adding a trigger is a schema decision that
      touches every later write path, so it is better taken deliberately than
      as a drive-by.
    location: >-
      infra/migrations/20260917T1200_create_users.up.sql
    severity: medium
  - summary: >-
      The entire database-backed suite skips itself where PostgreSQL is absent,
      and no CI pipeline exists to guarantee it ever runs.
    evidence: |-
      infra/tests/conftest.py falls back to `pytest.skip("no PostgreSQL
      available")` when TEST_DATABASE_URL is unset and initdb/pg_ctl are not on
      PATH. Every assertion about seeding, idempotency, the 72-hour expiry and
      the guarded `down` lives behind that fixture, so on such a machine a
      green `make test` proves none of them. It runs here (PostgreSQL 16.15 is
      on PATH). Story 1.1 already deferred the CI decision this depends on.
    location: >-
      infra/tests/conftest.py
    severity: medium
  - summary: >-
      `verify_password` has no rehash path, so digests stay at the old cost
      forever if the pinned Argon2id parameters are ever raised.
    evidence: |-
      shared/schema/shared_schema/passwords.py pins the parameters explicitly
      so a library upgrade cannot change them silently, but offers no
      `check_needs_rehash` equivalent. Who owns re-hashing on next login is a
      Story 1.3 decision, not a patch here.
    location: >-
      shared/schema/shared_schema/passwords.py
    severity: low
  - summary: >-
      The migrations directory is resolved relative to the installed package,
      so a non-editable install would ship the runner without any migrations.
    evidence: |-
      infra/pyproject.toml packages `rocell_infra` only; the runner resolves
      `migrations/` as a sibling of the package directory. That holds for the
      uv workspace's editable install and for `make migrate` here, and breaks
      for a wheel-based deployment. The deployment target is itself still
      undecided (architecture spine, Deferred).
    location: >-
      infra/rocell_infra/migrate.py
    severity: low
  - summary: >-
      The ledger stores no checksum, so editing an already-applied migration
      leaves two databases silently divergent.
    evidence: |-
      `schema_migrations` records version and applied_at only. AGENTS.md's
      "never edit an applied migration" is the stated control, and a checksum
      column would make a violation detectable rather than conventional.
    location: >-
      infra/rocell_infra/migrate.py
    severity: low
  - summary: >-
      A migration whose version sorts before an already-applied one is applied
      out of order with no warning.
    evidence: |-
      `up` applies every unapplied file in lexicographic order regardless of
      what is already in the ledger, so a branch merged with a backdated
      timestamp lands after migrations it was written before. `down` now
      reverts in applied_at order, which contains the damage but does not
      prevent it. Refusing a backdated version is a workflow decision.
    location: >-
      infra/rocell_infra/migrate.py
    severity: low
  - summary: >-
      `users` constrains `role` and the case of `email`, but nothing stops an
      empty or malformed `name` or `email` at the database level.
    evidence: |-
      20260917T1200_create_users.up.sql carries CHECK (email = lower(email))
      and the role CHECK, so the database holds its own copy of those rules.
      `''` passes both. The seed path is protected only because config.py
      validates the address before it gets there; Story 1.5's admin-created
      users have no such guard, and the file's own comment argues the database
      should not have to trust application code.
    location: >-
      infra/migrations/20260917T1200_create_users.up.sql
    severity: low
  - summary: >-
      `verify_password` offers no constant-time path for an unknown email, so
      Story 1.3's login can leak account existence by timing.
    evidence: |-
      shared/schema/shared_schema/passwords.py exists precisely so the seed and
      the login verifier cannot drift apart, but exposes only hash_password and
      verify_password. A login endpoint that skips hashing when no user matches
      answers measurably faster for an unknown address. The usual fix is a
      dummy verify against a fixed decoy digest — and adding it in apps/api
      later would recreate the second-hasher problem this module prevents, so
      it belongs here. Story 1.3 owns the decision.
    location: >-
      shared/schema/shared_schema/passwords.py
    severity: low
  - summary: >-
      The seed migration's `down` deletes "the one unclaimed Administrator",
      which is not necessarily the one it created.
    evidence: |-
      20260917T1210_seed_administrator.down.sql matches on role, unclaimed and
      exactly-one-admin rather than on an identity it recorded. If the seeded
      row is already gone and exactly one admin-created, still-unclaimed
      Administrator remains, `down` deletes that one. Recording the seeded id
      would need a marker the ledger does not carry today.
    location: >-
      infra/migrations/20260917T1210_seed_administrator.down.sql
    severity: low
  - summary: >-
      `down` prints "reverted <version>" even when the seed migration's down SQL
      deliberately deleted nothing.
    evidence: |-
      main() reports the version `down` returns, and the seed down is a no-op on
      a live system by design (claimed account, or a second Administrator) —
      infra/tests/test_migrate.py asserts exactly that. The ledger row is still
      removed, so the report is not wrong, but the operator is told a revert
      happened when the product state is unchanged. Reporting affected rows per
      migration is a runner-wide output decision.
    location: >-
      infra/rocell_infra/migrate.py
    severity: low
  - summary: >-
      A `TEST_DATABASE_URL` whose role cannot CREATE DATABASE errors every test
      instead of skipping, unlike the ephemeral-cluster path.
    evidence: |-
      infra/tests/conftest.py's `database_url` fixture creates a database per
      test. When TEST_DATABASE_URL is set the fixture uses it unconditionally,
      so an InsufficientPrivilege surfaces as an error in every database test
      rather than the single honest skip the no-PostgreSQL path produces.
    location: >-
      infra/tests/conftest.py
    severity: low
  - summary: >-
      Putting the Argon2id hasher in `shared/schema` makes `argon2-cffi` a hard
      dependency of every consumer of the shared *type* contracts, including
      `shared/vision` and `scripts/ingest`, which will never hash a password.
    evidence: |-
      `shared_schema/__init__.py` re-exports `hash_password` / `verify_password`,
      so the import is eager and no consumer can opt out; `shared/schema/pyproject.toml`
      declares the dependency for the whole package. The intent requires one shared
      hashing module and `shared/*` is the only direction both callers may depend on,
      but it does not fix which shared package — a `shared/security` would carry it
      without widening the type package's dependency surface. Splitting it once
      `shared/vision` exists is cheaper than splitting it now against one caller.
    location: >-
      shared/schema/shared_schema/passwords.py
    severity: medium
  - summary: >-
      The ephemeral test cluster runs `initdb --auth=trust` on a TCP listener,
      and a genuine `pg_ctl` misconfiguration is reported as "no PostgreSQL
      available", which is untrue.
    evidence: |-
      infra/tests/conftest.py starts the cluster with `--auth=trust` on 127.0.0.1,
      so any local user can connect as `postgres` for the life of the run; and
      `give_up` turns every initdb/pg_ctl failure into `pytest.skip`, after up to
      five start attempts, so a broken environment reads as an absent one. Both are
      test-harness hardening that depends on the still-open CI decision (Story 1.1)
      for where these tests are expected to run.
    location: >-
      infra/tests/conftest.py
    severity: low
  - summary: >-
      The version prefix is validated as a shape but never parsed as an instant,
      and `discover_migrations` refuses any non-migration file, so
      `infra/migrations/README.md` cannot exist.
    evidence: |-
      VERSION_PATTERN is `^\d{8}T\d{4}_...`, so `99999999T9999_do_things` plans
      happily while two migrations written in the same minute cannot be ordered
      against each other. Separately, every file that is not `.up.sql`/`.down.sql`
      and not a dotfile raises, which keeps a stray `.DS_Store` from breaking
      `status` but also blocks the natural home for the naming rules the runner
      enforces. Both are workflow decisions about the migrations directory.
    location: >-
      infra/rocell_infra/migrate.py
    severity: low
  - summary: >-
      `schema_migrations` is created outside the migration set and has no `down`,
      so stepping every migration back leaves the ledger table behind.
    evidence: |-
      `ensure_ledger` creates it on demand and no migration owns it, so after
      `down --yes` twice `users` is gone and `schema_migrations` remains — verified
      live. "Reversible" therefore holds for what the migrations created, not for
      the runner's own bookkeeping. Whether the ledger should be a migration of its
      own is a runner-wide decision.
    location: >-
      infra/rocell_infra/migrate.py
    severity: low
  - summary: >-
      The two subprocess suites sit in the default `testpaths` with no marker, and
      `--strict-markers` means introducing one is itself a config change, so there
      is no way to run the fast suite alone.
    evidence: |-
      tests/test_make_targets.py and infra/tests/test_make_targets_database.py each
      spawn `make` then `uv run` with 300s timeouts, and several cases hash or verify
      64 MiB Argon2 digests. `make test` is the command CLAUDE.md says to run before
      considering any change complete, so its cost matters; adding a `slow`/`db`
      marker also decides how CI will select tests, which Story 1.1 left open.
    location: >-
      pyproject.toml
    severity: low
---

<intent-contract>

## Intent

**Problem:** The repository has a runnable skeleton but no database layer at all — no driver, no migration runner, no `User` table, and `make migrate` deliberately exits 1. Stories 1.3–1.13 have nothing to authenticate against, and the product has no first way in that does not require opening a public sign-up path.

**Approach:** Add a plain-SQL, forward-only migration runner under `infra/` (the conventions are already recorded in `infra/README.md`), the `users` table matching the spine's ERD, and a seed step that creates exactly one Administrator in the `must_change_password` state from operator-supplied environment credentials — guarded so that neither a re-run nor a reset ledger can ever produce a second.

## Boundaries & Constraints

**Always:**
- The seeded Administrator is created **by the migration runner, never by application code and never by any UI**. It is the only account in the product's lifetime that no Administrator created.
- Seeding is idempotent at two independent layers: the `schema_migrations` ledger (a migration body runs once) **and** the seed statement's own guard (it does nothing if any `admin` row already exists). Either alone must suffice.
- Argon2id only, through the single shared helper — the seed and Story 1.3's login verifier must use one module with one parameter set, or a password that seeds cannot be verified.
- Credentials come from the environment (`SEED_ADMIN_EMAIL`, `SEED_ADMIN_PASSWORD`, optional `SEED_ADMIN_NAME`). No password, hash, connection string or fixture credential is committed — including in tests.
- All SQL is parameterized. No string-concatenated values, in the runner or in tests.
- Migrations are forward-only and reversible: every `NNN_verb.up.sql` has a `NNN_verb.down.sql` that restores the previous shape, and the down path is exercised by a test rather than asserted in a comment.
- Glossary terms verbatim: the entity is `User`, roles are `Staff` / `Administrator` (stored as `staff` / `admin`). `Product` and `Face` never appear.
- IDs are UUIDv4 (`gen_random_uuid()`); timestamps are `timestamptz` and are read and compared as UTC.
- `password_hash` never crosses the API boundary — it is absent from the shared `User` contract by construction, not by a serializer exclusion.

**Block If:**
- `psycopg` or `argon2-cffi` cannot be installed at all (both are verified available — see Code Map).
- Honouring the seed would require committing a credential or weakening Argon2id.

**Never:**
- No login endpoint, session table, session cookie, password-change screen, rate-limit counter, audit table or admin UI — those are Stories 1.3–1.13. This story adds no HTTP route.
- No ORM and no Alembic: `infra/README.md` already fixes timestamped `.sql` files as the migration format.
- No `Tile`/`ReferenceImage`/`ReferenceEmbedding` tables, no pgvector extension — Epic 2.
- No failed-login counter or lockout column — AD-8's counters are Story 1.6's shape decision.
- No second seeded account, no seeding "for convenience" in tests against the real seed path's guard.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| First migrate | Empty database, seed env set | `users` + `schema_migrations` exist; exactly one `admin` row, `must_change_password` true, `active` true | Non-zero exit with the failing migration named |
| Re-run migrate | Already-migrated database | No statement re-applied, still exactly one `admin` row, exit 0 | — |
| Ledger reset | `schema_migrations` truncated, `users` intact, then migrate | Seed body re-runs but inserts nothing — still exactly one `admin` row | — |
| Seed env missing, no admin exists | `SEED_ADMIN_PASSWORD` unset | Non-zero exit naming the missing variable; nothing partially applied | Transaction rolled back |
| Seed env missing, admin exists | Env unset, one `admin` row present | Exit 0 — the guard short-circuits before the env is needed | — |
| Weak seed password | `SEED_ADMIN_PASSWORD` under the minimum length | Non-zero exit naming the rule that failed | Transaction rolled back |
| Duplicate email, different case | Second `User` insert with `RUWAN@rocell.lk` when `ruwan@rocell.lk` exists | Insert rejected by the unique index on `lower(email)` | Integrity error surfaced, not swallowed |
| Unknown role | Insert with `role = 'manager'` | Rejected by the `CHECK` constraint | Integrity error surfaced |
| Down one step | Migrated database, `down` invoked | The migration's own down SQL runs and its ledger row is deleted | Non-zero exit if no down file exists |
| Password round-trip | A password hashed by the shared helper | `verify_password` accepts it, rejects any other string, and the stored digest starts `$argon2id$` | — |
| Failed migration mid-file | A statement raises inside one migration | That migration's whole transaction rolls back and no ledger row is written | Non-zero exit, error text preserved |
| `make migrate` honesty | Target invoked | Applies migrations; it no longer claims to be unimplemented | Non-zero exit on any failure |

</intent-contract>

## Code Map

**Read-only sources of truth (do not edit):**
- `_bmad-output/planning-artifacts/architecture/architecture-rcl_camera_app-2026-08-30/ARCHITECTURE-SPINE.md` — lines 236–241 the `USER` ERD block (`id`, `role`, `active`, `must_change_password`, `temp_credential_expires_at`); lines 166–173 Consistency Conventions (UUIDv4, ISO 8601 UTC, PascalCase glossary names); AD-3 (role/active are re-read per request, never cached — nothing here may encourage caching); AD-4 (audit grants, Story 1.12); the Stack table (PostgreSQL 18.x, Argon2id).
- `AGENTS.md` — Policy: Argon2id only; parameterized SQL only; no committed secrets including test fixtures; no roles beyond `staff`/`admin`; 72-hour temporary credentials.
- `_bmad-output/planning-artifacts/epics.md` lines 188–204 — Story 1.2's four acceptance clauses verbatim, and the note that 1.11's last-Administrator guard will correctly refuse to deactivate this account.
- `_bmad-output/planning-artifacts/prds/prd-rcl_camera_app-2026-08-25/prd.md` — FR-11 (a `User` carries name, email, role), FR-10 (last login is admin-visible).

**Files that already exist and constrain the shape:**
- `infra/README.md` — already fixes the migration conventions: forward-only, reversible, one concern per migration, **UTC-timestamp-prefixed `.sql` filenames**. This is why the runner is a plain-SQL applier and not Alembic. Extend this file; do not contradict it.
- `infra/migrations/.gitkeep` — the empty directory this story fills.
- `pyproject.toml` (root) — `[tool.uv.workspace] members`, `[tool.uv.sources]`, `[tool.ruff]` (`E,F,I,UP,B`, line-length 100, `extend-exclude`), `[tool.pytest.ini_options] testpaths`. Adding `infra` as a workspace member means editing all four.
- `shared/schema/shared_schema/__init__.py` — re-exports `ApiError, ErrorBody, ErrorEnvelope` in `__all__`; its docstring already names the glossary terms used verbatim. New exports join it.
- `shared/schema/shared_schema/errors.py` + `ts/errors.ts` + `tests/test_errors.py` + `apps/web/src/__tests__/error-envelope.test.ts` — **the precedent to mirror**: one contract in two languages, each half tested on its own side. `shared/schema/pyproject.toml` declares `pydantic>=2.9` and packages `shared_schema` via hatchling.
- `apps/web/tsconfig.json` — `paths` maps `@rocell/schema/*` to `../../shared/schema/shared_schema/ts/*`, and `include` already covers that directory, so a new `ts/user.ts` is compiled and importable with no config change.
- `Makefile` — `migrate` currently echoes "not implemented yet … Story 1.2" and exits 1; the `help` block lists it under "not implemented yet". Both change here. `UV := uv`, `.PHONY` list at the bottom.
- `tests/test_make_targets.py` — `UNIMPLEMENTED = {"migrate": "Story 1.2", "ingest": ..., "eval": ...}`; asserts each exits non-zero and says "not implemented yet". **`migrate` must be removed from this map**, or the suite fails the moment the target starts working.
- `apps/api/api/main.py` — untouched. It shows the house style for module docstrings and for `STATUS_CODES`-style module constants; no DB wiring belongs here yet.
- `.gitignore` — already covers `.venv/`, `dist/`, `*.egg-info/`.

**Verified environment facts (probed 2026-09-17, in a scratchpad):**
- `psycopg[binary]` resolves to 3.3.5 and `argon2-cffi` to 25.1.0 on Python 3.12; both install cleanly.
- PostgreSQL **16.15** (Homebrew) is on PATH (`initdb`, `pg_ctl`, `psql`); Docker is absent. The deployment target is 18.x, so the migration SQL must use nothing newer than 13 — `gen_random_uuid()` is core from 13 and is confirmed working here.
- **A unix-socket cluster fails in the scratchpad**: `Unix-domain socket path … is too long (maximum 103 bytes)`. An ephemeral cluster must listen on `127.0.0.1` at a chosen free port (verified working), or place its socket under a short directory.

## Tasks & Acceptance

**Execution:**
- `shared/schema/pyproject.toml` — add `argon2-cffi>=23.1` — the one new runtime dependency on the shared side; flagged per AGENTS.md Conventions.
- `shared/schema/shared_schema/passwords.py` — `hash_password(password) -> str` and `verify_password(hash, password) -> bool` over a single module-level `PasswordHasher` with explicitly pinned Argon2id parameters, plus the minimum-length rule; reject an empty password at construction the way `ApiError` rejects an empty code — the one hashing path the seed and Story 1.3 both call, so their parameters cannot drift.
- `shared/schema/shared_schema/user.py` — `Role` (`STAFF = "staff"`, `ADMIN = "admin"`) and a `User` pydantic model (`extra="forbid"`) carrying `id`, `name`, `email`, `role`, `active`, `must_change_password`, `temp_credential_expires_at`, `last_login_at`, `created_at`, `updated_at` — the cross-layer contract, deliberately with **no** `password_hash` field.
- `shared/schema/shared_schema/ts/user.ts` — the TypeScript twin: `Role` union, `User` interface, `isUser` narrowing in the closed-shape style of `isErrorEnvelope` — `apps/web` compiles against this half.
- `shared/schema/shared_schema/__init__.py` — re-export `Role`, `User`, `hash_password`, `verify_password` and extend `__all__` — one import surface.
- `shared/schema/tests/test_passwords.py` — cover the password round-trip, the `$argon2id$` prefix, wrong-password rejection, two hashes of one password differing (salting), and the length/empty rejections.
- `shared/schema/tests/test_user.py` — assert the field set exactly, that `password_hash` is refused by `extra="forbid"`, and that a role outside `staff`/`admin` is refused.
- `apps/web/src/__tests__/user-contract.test.ts` — mirror `error-envelope.test.ts` against `@rocell/schema/user`, so the twin cannot drift unnoticed.
- `infra/pyproject.toml` — new workspace member `rocell-infra`, packaging `rocell_infra`, depending on `psycopg[binary]>=3.2` and `shared-schema` — the migration runner needs a driver and the shared hasher; `infra` may depend on `shared/*` but never on `apps/*`.
- `pyproject.toml` (root) — add `infra` to `[tool.uv.workspace] members`, `rocell-infra` to `[project] dependencies` and `[tool.uv.sources]`, and `infra/tests` to `testpaths`; keep `poc` excluded — one venv, one lint and one test configuration still covers everything.
- `infra/rocell_infra/__init__.py` — package docstring stating that `infra` holds no business logic and that this package is the migration applier only.
- `infra/rocell_infra/config.py` — read `DATABASE_URL` (required) and the `SEED_ADMIN_*` variables from the environment, returning a small frozen dataclass and raising a named error listing every missing variable — secrets come from the environment, never from a file in the tree.
- `infra/rocell_infra/migrate.py` — discover `infra/migrations/*.up.sql` in lexicographic order, create `schema_migrations (version text primary key, applied_at timestamptz not null default now())`, apply each unapplied file **and its ledger row in one transaction**, and expose `up`, `down` (one step, running the matching `.down.sql`), `status` and `reseed-admin`; `python -m rocell_infra.migrate` dispatches them with a non-zero exit on any failure.
- `infra/rocell_infra/seed.py` — the seed step invoked by the seed migration: inside the caller's transaction, `SELECT` for any existing `admin`; if one exists return without touching the environment; otherwise read the `SEED_ADMIN_*` config, hash with `shared_schema.passwords`, and insert one Administrator with `must_change_password = true`, `active = true` and `temp_credential_expires_at = now() + interval '72 hours'`. `reseed-admin` reuses this module to reissue the credential **only** while the seeded account is still unclaimed and is still the only Administrator.
- `infra/migrations/20260917T1200_create_users.up.sql` / `.down.sql` — create `users` (`id uuid pk default gen_random_uuid()`, `name text not null`, `email text not null`, `password_hash text not null`, `role text not null check (role in ('staff','admin'))`, `active boolean not null default true`, `must_change_password boolean not null default true`, `temp_credential_expires_at timestamptz`, `last_login_at timestamptz`, `created_at`/`updated_at timestamptz not null default now()`) plus the unique index on `lower(email)`; the down drops both — the ERD's `User`, with the columns FR-10/FR-11 need and nothing Stories 1.5+ own.
- `infra/migrations/20260917T1210_seed_administrator.up.sql` / `.down.sql` — the seed migration. Its up file is a marker the runner recognises as "call `seed.py` in this transaction" (the hash cannot be computed in SQL); its down deletes only the seeded Administrator row and only while it is still unclaimed — document that choice in the file header.
- `infra/tests/conftest.py` — a session fixture yielding a connection to a throwaway database: use `TEST_DATABASE_URL` when set, else `initdb` + `pg_ctl` an ephemeral cluster on a free `127.0.0.1` port (**not** a unix socket — see Code Map), else skip with the reason "no PostgreSQL available". Each test gets a freshly created empty database so ordering cannot hide a defect.
- `infra/tests/test_migrate.py` — the I/O matrix's database rows: first run, re-run, truncated ledger, missing env with and without an existing admin, weak password, case-insensitive email collision, unknown role, one-step down, and a deliberately failing migration leaving no ledger row.
- `infra/tests/test_runner_unit.py` — the runner's file-planning logic without a database: ordering, up/down pairing, a missing down file, and rejection of an unpaired or misnamed file — these run everywhere, with or without Postgres.
- `Makefile` — `migrate` runs `$(UV) run python -m rocell_infra.migrate up`; add `reseed-admin`; move `migrate` out of the "not implemented yet" help block and into the main list; update `.PHONY` — the target now does what `CLAUDE.md` promises.
- `tests/test_make_targets.py` — drop `migrate` from `UNIMPLEMENTED` and add a test that `make migrate` without `DATABASE_URL` exits non-zero naming the variable — the honesty test now guards the opposite property for this target.
- `infra/README.md` — document the runner's commands, the `DATABASE_URL` / `SEED_ADMIN_*` contract, the two-layer idempotency guarantee, the 72-hour seeded credential and `reseed-admin`; replace "Migration content is Story 1.2 and later" — the operator-facing page for a step no test can perform.
- `README.md` — add migrations and the seed environment to the setup instructions — the next developer needs a database before `make dev` is meaningful.

**Acceptance Criteria:**
- Given a clean database and the seed environment set, when `make migrate` runs, then it exits 0 and the `users` table exists with `role`, `active`, `must_change_password` and `temp_credential_expires_at` among its columns.
- Given that same database, when the count of rows with `role = 'admin'` is taken, then it is exactly 1, that row has `must_change_password = true` and `active = true`, and its `password_hash` verifies against `SEED_ADMIN_PASSWORD` through `shared_schema.passwords.verify_password`.
- Given an already-migrated database, when `make migrate` is run a second time — and again after `schema_migrations` is truncated — then it exits 0 and the `admin` row count is still exactly 1.
- Given the repository, when it is searched for the seeded password, then it appears in no source file, test, fixture or migration — every test that needs one generates it at runtime.
- Given `make lint` and `make test` on a clean checkout, when both are run, then both exit 0, with `infra` covered by ruff and by the pytest workspace.
- Given `make migrate` with no `DATABASE_URL`, when it runs, then it exits non-zero naming the missing variable and creates nothing.
- Given `grep` over the new code, when it is inspected, then no SQL is assembled by string concatenation or f-string interpolation of a value, and no role beyond `staff`/`admin` is accepted.

## Spec Change Log

## Review Triage Log

### 2026-09-17 — Review pass

- intent_gap: 0
- bad_spec: 0
- patch: 17: (high 0, medium 9, low 8)
- defer: 7: (high 0, medium 2, low 5)
- reject: 7
- addressed_findings:
  - `[medium]` `[patch]` A `-- rocell:python` directive anywhere in an `.up.sql` made the runner call the step and return without executing the file's SQL, applying nothing while writing a ledger row — a file carrying both a directive and non-comment SQL is now refused by name, with a test.
  - `[medium]` `[patch]` Two concurrent `make migrate` runs could both see no `admin` row and both insert (different seed emails evade the `lower(email)` index) — every migration transaction now opens with `pg_advisory_xact_lock` and re-reads the ledger under it; tested, including proof the lock is actually taken.
  - `[medium]` `[patch]` `reseed-admin` set `active = true`, silently re-enabling a deliberately deactivated Administrator — `active` is no longer touched; tested and the README corrected.
  - `[medium]` `[patch]` A stray `.DS_Store` in `infra/migrations/` broke every runner command including `status` — dotfiles are now skipped; tested and confirmed live.
  - `[medium]` `[patch]` Email uniqueness was over `lower(email)` while the stored value kept its original case, leaving every later lookup obliged to remember `lower()` — the seed now stores lowercase and the table carries `CHECK (email = lower(email))`.
  - `[medium]` `[patch]` `hash_password` had no length ceiling, making Story 1.3's unauthenticated login a CPU-exhaustion vector — `MAX_PASSWORD_LENGTH` added, rejected before hashing on the verify path.
  - `[medium]` `[patch]` `down` was documented as an ordinary operator command and would `DROP TABLE users` on a production URL without confirmation — it now requires an explicit `--yes`.
  - `[medium]` `[patch]` `main()` was entirely untested, so the command dispatch behind `make reseed-admin` and the documented `status`/`down` commands could break silently — 12 tests now drive `main()` including exit codes and bad invocations.
  - `[medium]` `[patch]` The Python `User` field set and the TypeScript `USER_KEYS` were each pinned to their own literal, so a one-sided field change shipped green — two tests now parse `ts/user.ts` and assert both halves equal `set(User.model_fields)`.
  - `[low]` `[patch]` `isUser` accepted a non-UUID `id` and non-ISO timestamps that the pydantic twin rejects — value-level validation added, and the web test now iterates the full key set.
  - `[low]` `[patch]` `down` reverted the lexicographically last version rather than the most recently applied one, while `applied_at` went unread — ordering is now `applied_at DESC, version DESC`, tested with a backdated migration.
  - `[low]` `[patch]` `psycopg.connect` had no `connect_timeout`, so `make migrate` against an unreachable host hung with no output — a 10s timeout, verified.
  - `[low]` `[patch]` `reseed-admin` before any migration surfaced a raw `UndefinedTable` — now a guided `SeedRefused` naming `make migrate`.
  - `[low]` `[patch]` The ephemeral test cluster's free-port probe closed its socket before `pg_ctl` bound it, turning a taken port into a confusing suite-wide skip — start now retries on a fresh port; the unused `GENERATED_PASSWORD_BYTES` constant was deleted.
  - `[low]` `[patch]` `README.md` taught putting `SEED_ADMIN_PASSWORD` on the command line, where it reaches shell history and `ps` — replaced with `read -rs`.
  - `[low]` `[patch]` Seeding and reissuing are user changes performed outside the application and AGENTS.md requires audit coverage of those — the gap is now recorded in `seed.py` and `infra/README.md` as owed by Story 1.12.
  - `[low]` `[patch]` Doc drift: the Makefile header omitted `infra` from the workspace, the new help line broke column alignment, and `CLAUDE.md` named `make reseed-admin` without its `SEED_ADMIN_*` requirement.

### 2026-09-17 — Review pass

- intent_gap: 0
- bad_spec: 0
- patch: 16: (high 0, medium 6, low 10)
- defer: 5: (high 0, medium 0, low 5)
- reject: 15
- addressed_findings:
  - `[medium]` `[patch]` `reseed-admin` required and validated `SEED_ADMIN_EMAIL` and then discarded it, so an operator who supplied a different address was told the credential was reissued and could not sign in with what they typed — it now refuses, naming the stored address; two tests.
  - `[medium]` `[patch]` `User` took bare `datetime`, so pydantic accepted a naive timestamp and a `+05:30` offset and re-emitted both verbatim, while `isUser` rejects them and `ts/user.ts` documented itself as accepting exactly what `user.py` produces — fields are `AwareDatetime` and a serializer normalises to UTC; six value-level parity tests, including the serialize-then-check round trip the key-set tests never made.
  - `[medium]` `[patch]` Neither `make migrate`'s success path nor `make reseed-admin` had any test — repointing the recipe at `status` left the suite green while three documents promise the target applies migrations; three target-level tests against the throwaway cluster, confirmed to fail under that mutation.
  - `[medium]` `[patch]` `_apply`'s under-lock ledger re-read — the documented third idempotency layer — was never reached by the test that claimed it, so deleting it kept every test passing; a test now drives `_apply` directly after a concurrent commit, confirmed to fail without the guard.
  - `[medium]` `[patch]` `pg_advisory_xact_lock` waited forever, so a runner stuck behind another turned `make migrate` into the silent hang `connect_timeout` exists to prevent — a transaction-local `lock_timeout` with a named refusal.
  - `[medium]` `[patch]` `ensure_ledger` ran outside the lock and `CREATE TABLE IF NOT EXISTS` is not atomic against a concurrent one, so two first-time runs raced in the catalogue and the loser died with a `pg_type` error naming nothing — the lost race is now tolerated when the table is really there, and still raised when it is not.
  - `[low]` `[patch]` `down` read the ledger before taking the lock, unlike `_apply`, so two concurrent runs both reverted the same version — the read moved inside the locked transaction.
  - `[low]` `[patch]` `reseed-admin` took no lock at all, so two concurrent reseeds both passed the "still unclaimed" guard and the operator holding the first password was told it works.
  - `[low]` `[patch]` `down`'s refusal for a version recorded as applied with no files on disk had no test; without it the guided message degraded to an `AttributeError` traceback — tested, confirmed to fail under that mutation.
  - `[low]` `[patch]` The concurrency test's bare `pytest.raises(MigrationError)` was satisfied by any planning failure and would have passed with the advisory lock deleted — it now matches the lock message and asserts the ledger stayed empty.
  - `[low]` `[patch]` `has_sql` read `/* … */` as SQL, so a marker migration with a block-comment header was refused with a message that was untrue; and a body naming two `rocell:python` steps silently ran only the first while its ledger row recorded the whole — both fixed, five unit tests.
  - `[low]` `[patch]` `_run_body` carried a `migration` parameter it never used, and the `#:` note about skipping dotfiles was orphaned above an unrelated regex, so it documented the wrong thing.
  - `[low]` `[patch]` `MAX_PASSWORD_LENGTH = 128` was enforced and documented nowhere — a long generated passphrase failed against an unstated rule; `infra/README.md` now states the range and `README.md` says to `unset` the password after seeding.
  - `[low]` `[patch]` Neither command said which database it acted on — the design rests on not migrating the wrong one — nor when the seeded credential expires, the most time-critical fact about the account; both are printed now, the target sanitised so no password reaches the console, and the line flushed so it cannot land after an unbuffered stderr refusal.
  - `[low]` `[patch]` The Makefile help's parenthetical named `down` but showed only the `status` command and omitted the required `--yes`, so a copy-paste of the documented command failed.
  - `[low]` `[patch]` The previous pass's own triage header recorded `medium 8, low 9` and a score of 33 while its `addressed_findings` list holds 9 medium and 8 low — the counts and the frontmatter score are corrected.

### 2026-09-17 — Review pass

- intent_gap: 0
- bad_spec: 0
- patch: 11: (high 0, medium 4, low 7)
- defer: 5: (high 0, medium 1, low 4)
- reject: 28
- addressed_findings:
  - `[medium]` `[patch]` The two halves of the marker guard read the same file differently: `has_sql` stripped `/* ... */` and the directive match did not, so a marker disabled by wrapping it in a block comment still ran `seed_administrator`, while a plain SQL migration whose header merely quoted the directive was refused as "carries both a directive and SQL". Block comments are now stripped for both, and a body holding neither SQL nor a directive is refused rather than applied as a no-op with a ledger row to show for it — 3 unit tests and 2 database tests, each confirmed to fail under the old behaviour.
  - `[medium]` `[patch]` The Argon2id cost parameters are pinned by value precisely so a library upgrade cannot move them, and nothing asserted them: dropping to `m=1024,t=1` with an 8-byte salt kept the whole suite green, because the digest still starts `$argon2id$` and still verifies against itself. Two tests now pin the encoded parameters and the salt/hash lengths; the mutation fails both.
  - `[medium]` `[patch]` `reseed-admin` exists because the seeded credential expires, and no test read `temp_credential_expires_at` after a reseed — deleting the expiry line from `_REISSUE_CREDENTIAL` left every reseed test passing while handing the operator a working password against a dead deadline. Tested, mutation confirmed.
  - `[medium]` `[patch]` The seed `down`'s four safety predicates were only ever exercised jointly — the claimed-account test sets `must_change_password = false` **and** `last_login_at` in one UPDATE, and no `down` case had a Staff row present — so each of `last_login_at IS NULL`, `must_change_password` and `role = 'admin'` could be deleted with the suite green. With the first gone, `down --yes` deletes a sole Administrator who has signed in and carries a forced password change, which is the state an admin-issued reset produces. Three tests, one per predicate, each confirmed to fail under its own mutation.
  - `[low]` `[patch]` `reseed_admin` takes the migration lock and the only lock test drove `up`, so removing `_take_lock` from it left every reseed test green. Contention test added, mirroring the `up` one.
  - `[low]` `[patch]` `SEED_ADMIN_PASSWORD`'s 128-character ceiling was enforced in `config.py` and tested nowhere; on the reseed path, which `_apply` does not wrap, deleting it lets `hash_password`'s `ValueError` escape `main` as a traceback instead of a named refusal. Tested on both paths.
  - `[low]` `[patch]` `_report_credential` advised `make reseed-admin` for whichever unclaimed Administrator sorts first, including one an Administrator created — where `reseed_administrator` refuses on the count. The advice is now given only while there is exactly one Administrator; tested and confirmed live.
  - `[low]` `[patch]` `README.md` and `infra/README.md` justified `read -rs` by saying a password on the command line is "readable from `ps`", which is untrue of the `SEED_ADMIN_PASSWORD=… make migrate` form they contrast with — that is an environment assignment, not argv. Shell history is the real reason; `ps` applies to `make migrate SEED_ADMIN_PASSWORD=…`. Both passages now say which is which.
  - `[low]` `[patch]` `make help`'s two runner commands were indented under `reseed-admin`'s description, so `status` and `down --yes` read as part of what that target does.
  - `[low]` `[patch]` `USER_KEYS` was typed `readonly string[]`, so the compiler enforced nothing about the key literals a pytest regex approximates. The literals now live in a `readonly (keyof User)[]` constant: a typo in one of them is `TS2820` naming the intended key, verified by mutation.
  - `[low]` `[patch]` `ensure_ledger`'s lost-race recovery re-reads the catalogue on the same connection, which only works under autocommit — inside an open transaction that statement aborts and masks the original error. The requirement is now stated where the function promises it.

## Design Notes

**Why a plain-SQL runner, not Alembic.** `infra/README.md` — written by Story 1.1 and unchanged since — already fixes the format: timestamp-prefixed `.sql` files, one concern each, every one with a working `down`. Alembic would replace that convention with Python revision chains and pull in SQLAlchemy, a second dependency and a second mental model, for a project whose only other SQL consumer (`apps/api`, Story 1.3+) has no ORM either. The runner is a ledger table and a loop.

**Why the hasher lives in `shared/schema`.** It is the one piece of auth logic two different callers must execute identically: the migration seed (in `infra`) and Story 1.3's login verifier (in `apps/api`). Putting it in `apps/api` would make `infra` depend on an adapter — backwards; duplicating it lets the Argon2id parameters drift, and a seeded hash that login cannot verify is exactly the silent failure AD-1 guards against on the vision side. `shared/*` is the only direction both may depend on.

**Why the seeded credential still expires in 72 hours.** AGENTS.md states the rule without exception, so the seed honours it. That creates one real hazard: if nobody claims the account within 72 hours there is no Administrator to reissue it, and the product is unreachable. `reseed-admin` is the answer, and it is deliberately narrow — it refuses once a second Administrator exists, and refuses once the account has been claimed (`must_change_password = false`), so it can never become a back door into a live system. It runs at the console with the same environment access as `make migrate` itself.

**Two-layer idempotency.** The ledger stops the migration body from running twice; the guard inside the seed stops a second Administrator from being created even if the body does run twice. The second layer is what makes the "never a second seeded Administrator" claim true against an operator who resets the ledger, restores an old dump, or points the runner at a database it has already seeded.

```sql
-- One transaction per migration: the file and its ledger row commit together,
-- so a failure halfway leaves neither.
BEGIN;
  -- <contents of NNN_verb.up.sql>
  INSERT INTO schema_migrations (version) VALUES (%s);
COMMIT;
```

## Verification

**Commands:**
- `make setup` — expected: `uv sync` resolves `infra` as a workspace member with `psycopg` and `argon2-cffi`.
- `make lint` — expected: exit 0; ruff covers `infra/`, `tsc --noEmit` covers the new `ts/user.ts`.
- `make test` — expected: exit 0; the `infra` suite runs against an ephemeral cluster (PostgreSQL 16.15 is on PATH), none of its database tests skipped on this machine.
- `DATABASE_URL=… SEED_ADMIN_EMAIL=… SEED_ADMIN_PASSWORD=… make migrate` against a scratch database — expected: exit 0, then `psql -tAc "select count(*) from users where role='admin'"` returns `1`; running it twice leaves `1`.
- `make migrate` with `DATABASE_URL` unset — expected: non-zero exit naming the variable.
- `git grep -nE "SEED_ADMIN_PASSWORD\s*=\s*['\"]"` — expected: no match outside documentation placeholders.

**Manual checks (if no CLI):**
- `infra/migrations/*.up.sql` uses no syntax newer than PostgreSQL 13, so a 16.x test cluster and an 18.x deployment agree.

## Auto Run Result

Status: done
Blocking condition: none

### Summary of implemented change

Story 1.2 gave the repository its database layer: a plain-SQL, forward-only
migration runner under `infra/`, the `users` table from the architecture
spine's ERD, and a seed step that creates exactly one Administrator in the
`must_change_password` state from operator-supplied environment credentials.
This pass was a third review of that completed work (the previous pass set
`followup_review_recommended: true`), not a re-implementation. It applied 11
patches and deferred 5 findings; no spec amendment or code re-derivation was
needed, so `review_loop_iteration` stays at 0.

The pass found one live defect and three coverage gaps that each hid a live
one. The defect: `has_sql` stripped block comments and the directive match did
not, so a marker migration disabled by wrapping it in `/* ... */` still ran
`seed_administrator`, while a plain SQL migration whose header quoted the
directive was refused with a message that was untrue. The gaps: the Argon2id
cost parameters, `reseed-admin`'s restart of the 72-hour clock, and three of
the four predicates that keep `down --yes` from deleting a live system's last
Administrator were each unasserted, and each could be removed with the whole
suite green.

### Files changed in this pass

- `infra/rocell_infra/migrate.py` — `python_step` strips block comments before matching the directive; `_run_body` refuses a body holding neither SQL nor a directive; `_report_credential` offers `make reseed-admin` only while there is exactly one Administrator; `ensure_ledger` documents that its recovery read needs autocommit.
- `infra/rocell_infra/seed.py` — `_administrator_count` is now the public `administrator_count`, because the console reporting needs the same count the reseed guard refuses on.
- `infra/tests/test_migrate.py` — 10 tests: both over-long-password paths, three `down` predicates one at a time, Staff survival, the reseed clock, the reseed lock, the remedy branches, and the two directive/block-comment cases.
- `infra/tests/test_runner_unit.py` — 3 database-free tests for the directive inside, beside and superseded by a block comment.
- `shared/schema/tests/test_passwords.py` — the encoded Argon2id parameters and the salt/hash lengths.
- `shared/schema/shared_schema/ts/user.ts` — the key literals moved into a `readonly (keyof User)[]` constant, so a typo is a compile error naming the intended key.
- `shared/schema/tests/test_user.py` — the parity scraper follows the literals to `CONTRACT_KEYS`.
- `Makefile` — the two runner commands no longer read as part of what `make reseed-admin` does.
- `README.md`, `infra/README.md` — the `read -rs` justification says which risk is shell history and which is `ps`.

### Review findings breakdown

11 patches applied (4 medium, 7 low); 5 items deferred (1 medium, 4 low); 28
rejected. Of the rejections, 8 were findings the deferred-work ledger already
tracks (the `updated_at` trigger, the PostgreSQL-conditional suite and the open
CI decision, the `verify_password` rehash path, database-level `name`/`email`
constraints, a ledger checksum, backdated versions, the `TEST_DATABASE_URL`
privilege case, and `status` reading only what is on disk). No `intent_gap` and
no `bad_spec`, so no spec amendment and no implementation loopback.

### Follow-up review recommendation

`true`. Patched this pass: 0 high, 4 medium, 7 low. Score = 3x4 + 1x7 = 19,
which is at or above the threshold of 5.

### Verification performed

- `make lint` — exit 0 (ruff check, ruff format --check, oxlint, tsc --noEmit). `make format` was run once for the new test files.
- `make test` — exit 0: 222 pytest tests (up from 207) and 237 vitest tests, no skips. PostgreSQL 16.15 is on PATH, so every database test ran.
- Mutation checks, each confirmed to fail before being reverted: lowering the Argon2id cost and salt length (2 failures), dropping the expiry from `_REISSUE_CREDENTIAL` (1), deleting each of the seed `down`'s three predicates in turn (1 each), removing `_take_lock` from `reseed_admin` (1), deleting `config.py`'s maximum-length branch (1, as the raw `ValueError` the reseed path would surface), reverting the `_report_credential` remedy guard (1), matching the directive against the raw body again (5), dropping the no-op-body guard (1), a `keyof User` typo (`TS2820`), and adding a Python field with no TypeScript twin (3).
- End to end against a throwaway PostgreSQL cluster on 127.0.0.1: `make migrate` applied both migrations, seeded 1 Administrator and printed the address, the deadline and the `make reseed-admin` remedy (exit 0); a second run applied nothing and left the count at 1; `make reseed-admin` reissued (exit 0); after inserting a second Administrator, `make migrate` printed the *other* remedy and `make reseed-admin` refused naming the count (exit 1); truncating the ledger and re-migrating left the count at 1; `make migrate` with no `DATABASE_URL` exited non-zero naming the variable; `down` without `--yes` refused; `down --yes` twice removed `users` and left `schema_migrations` behind (now deferred).
- `git grep -nE "SEED_ADMIN_PASSWORD\s*=\s*['\"]"` — no match outside `_bmad-output`; no f-string or concatenated SQL in `infra/`, `shared/` or `apps/`.

### Residual risks

- The database-backed suite still skips itself entirely where PostgreSQL is absent, and there is no CI pipeline to guarantee it ever runs (deferred, and dependent on Story 1.1's open CI decision). It runs here, and the three coverage gaps this pass closed are only as good as that.
- The parity between the two halves of the `User` contract is now compiler-enforced in one direction (a key literal must exist on the interface) and test-enforced in the other (a Python field must appear in the TypeScript source). The second half still reads `user.ts` as text, so a purely cosmetic reflow of those declarations fails the suite without a contract change.
- `updated_at` still has no `BEFORE UPDATE` trigger, so every future write path has to set it by hand (deferred; it touches Stories 1.3, 1.5, 1.10 and 1.11).
- The `User` contract's UTC normalisation is still exercised against the model, not a live API response — no HTTP route exists until Story 1.3.
- Seeding and reissuing are still unaudited; Story 1.12 owes both paths their entries.
- `argon2-cffi` is a hard dependency of everything that imports the shared type contracts (deferred); splitting the hasher into its own shared package is cheaper once a second, non-auth consumer of `shared/schema` exists.
