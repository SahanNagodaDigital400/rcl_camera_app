### DW-1: No PWA scaffolding exists — no web app manifest, icons, theme-color meta, or service worker — in a product whose delivery model is an installable phone app.
origin: spec-deferred 358c5c93aa3f
location: apps/web/index.html
source_spec: `spec-1-1-project-scaffold-design-token-foundation.md`
severity: medium
reason: apps/web/index.html links no manifest and apps/web/package.json carries no PWA plugin. EXPERIENCE.md describes a "multi-surface PWA, installable to the home screen" as the delivery model. Story 1.1's acceptance criteria do not mention it, so it is out of scope here, but nothing later claims it either.
status: open

### DW-2: No CI workflow runs make lint / make test, so every guard this story ships is enforced only when a human remembers to run them.
origin: spec-deferred 2c579e6c6d66
location: n/a
source_spec: `spec-1-1-project-scaffold-design-token-foundation.md`
severity: medium
reason: The token contract test, the no-raw-values guard and the make-target honesty tests all exist and pass locally, and nothing runs them on push. The architecture spine lists CI/CD as an unresolved infrastructure decision blocking deployment work.
status: open

### DW-3: make lint type-checks TypeScript with tsc but runs no Python type checker, although every Python file is fully annotated and AGENTS.md mandates type hints throughout.
origin: spec-deferred 2fe345d2ddbf
location: Makefile
source_spec: `spec-1-1-project-scaffold-design-token-foundation.md`
severity: medium
reason: Makefile lint runs ruff check and ruff format --check only. Adding mypy or pyright is a new dependency and would likely surface new findings, so it is a decision rather than a patch.
status: open

### DW-4: The Vite dev proxy rewrites /api/x to /x against the API root, and no production path convention is fixed, so dev and production can disagree about the API prefix.
origin: spec-deferred 9fd473e902d6
location: apps/web/vite.config.ts
source_spec: `spec-1-1-project-scaffold-design-token-foundation.md`
severity: medium
reason: apps/web/vite.config.ts proxies /api with a rewrite; README.md describes production as a same-origin path. Whether the production reverse proxy strips the same prefix is undecided. Related: the dev proxy runs over plain HTTP, which will collide with the mandated Secure / SameSite=Strict session cookie when Story 1.3 lands.
status: open

### DW-5: apps/web's test suite reads DESIGN.md through a hardcoded, date-stamped planning-artifact path, coupling the front end to _bmad-output.
origin: spec-deferred 2bd66f5882cf
location: apps/web/src/__tests__/tokens.test.ts
source_spec: `spec-1-1-project-scaffold-design-token-foundation.md`
severity: low
reason: apps/web/src/__tests__/tokens.test.ts resolves _bmad-output/planning-artifacts/ux-designs/ux-rcl_camera_app-2026-09-08/DESIGN.md. A later UX run produces a differently-dated directory and the whole web suite fails, and the package cannot be tested from a checkout that excludes planning artifacts. Reading DESIGN.md at test time is deliberately stronger than copying its values, so the fix is an indirection, not a removal.
status: open

### DW-6: Ruff's rule selection omits flake8-bandit (S) and pycodestyle warnings (W) in a repository whose security requirements are declared non-negotiable.
origin: spec-deferred fb750e88086c
location: pyproject.toml
source_spec: `spec-1-1-project-scaffold-design-token-foundation.md`
severity: low
reason: pyproject.toml selects E, F, I, UP, B only. Enabling S will produce findings on the auth and upload code that Stories 1.2+ add, so it is better turned on deliberately than as a drive-by.
status: open

### DW-7: apps/web has no React error boundary, so any render throw yields a blank page with no recovery path.
origin: spec-deferred f4662a58b600
location: apps/web/src/main.tsx
source_spec: `spec-1-1-project-scaffold-design-token-foundation.md`
severity: low
reason: apps/web/src/main.tsx mounts App directly. The shell currently renders static content so the risk is latent, but every later UI story raises it.
status: open

### DW-8: apps/api sets no security response headers and no request body size limit, on a service whose stated primary threat is catalogue exfiltration.
origin: spec-deferred 7c817759c1e0
location: apps/api/api/main.py
source_spec: `spec-1-1-project-scaffold-design-token-foundation.md`
severity: medium
reason: create_app() installs the error handlers and disables /docs, /redoc and /openapi.json, but adds no middleware for X-Content-Type-Options, Referrer-Policy, frame-ancestors/CSP or HSTS, no TrustedHostMiddleware, and no upload size ceiling. Choosing a CSP and an HSTS max-age is a deployment decision (the spine leaves the deployment target open), and the body limit belongs with the upload path in Epic 2, so this is a decision rather than a drive-by patch.
status: open

### DW-9: oxlint never lints shared/schema/shared_schema/ts, the one source directory outside apps/web/src that apps/web compiles against.
origin: spec-deferred ba6362b08897
location: apps/web/package.json
source_spec: `spec-1-1-project-scaffold-design-token-foundation.md`
severity: low
reason: The lint script runs from apps/web and oxlint refuses a path containing "..": `Error: PATH must not contain ".."`. Covering it means either invoking oxlint from the repository root in the Makefile with an explicit node_modules/.bin path, or restructuring the lint target — a shape change, not a one-line fix. tsc does type-check the file (it is in tsconfig include) and vitest exercises it, so the gap is lint rules only.
status: open

### DW-10: The contrast ratios the token layer cites are never computed by a test, so a DESIGN.md colour change can drop the UI below WCAG AA silently.
origin: spec-deferred fff3ea2dec8c
location: apps/web/src/__tests__/tokens.test.ts
source_spec: `spec-1-1-project-scaffold-design-token-foundation.md`
severity: low
reason: tokens.css comments state 5.94:1 for navy-on-accent, 4.65:1 for muted text on the background and 2.63:1 for the white-on-accent failure. tokens.test.ts asserts provenance and an identity between two tokens; no test derives a ratio. Change --color-muted-text in DESIGN.md to a failing pair and the whole suite stays green. The fix is a relative-luminance helper plus a decision about which pairs are load-bearing.
status: open

### DW-11: CLAUDE.md's testing policy calls `make eval-real` "the only number that decides anything", but it is neither a Makefile target nor one of the not-implemented targets this story enumerates.
origin: spec-deferred a99cd1d75661
location: CLAUDE.md:126
source_spec: `spec-1-1-project-scaffold-design-token-foundation.md`
severity: medium
reason: CLAUDE.md line 126 names `make eval-real`. The Makefile's .PHONY list is help setup dev lint format test build migrate ingest eval, and the curated "not implemented yet" block in both the Makefile and CLAUDE.md lists only migrate, ingest and eval. The line predates this story and was not touched by it, but the Commands rewrite made that block the authoritative list, so the omission now reads as a contradiction. Resolving it needs a decision on whether eval-real is a separate target or a mode of `make eval`.
status: open

### DW-12: Nothing configures logging output, so apps/api's records reach a destination only through Python's last-resort stderr handler.
origin: spec-deferred 5a360ecc054f
location: apps/api/api/main.py
source_spec: `spec-1-1-project-scaffold-design-token-foundation.md`
severity: medium
reason: api/main.py takes logging.getLogger("rocell.api") and calls logger.exception in the unhandled handler, and the 500 body tells the user the incident has been logged. No basicConfig or dictConfig exists anywhere in the workspace, and uvicorn's default log config does not configure the root logger. The record is still emitted — logging's lastResort handler writes ERROR and above to stderr with the traceback — so the promise holds, but with no timestamp, no logger name, no level control and no destination. Choosing a log configuration is a deployment decision this story has no requirement for.
status: open

### DW-13: The error envelope is a closed shape with no correlation identifier, so adding one later is a breaking change on both halves of the contract.
origin: spec-deferred e6e602349301
location: shared/schema/shared_schema/errors.py
source_spec: `spec-1-1-project-scaffold-design-token-foundation.md`
severity: medium
reason: shared_schema/errors.py sets extra="forbid" on ErrorBody and ErrorEnvelope, and isErrorEnvelope in the TypeScript twin rejects any key beyond code and message — both deliberately, and both tested. The consequence is that a request_id, which the generic 500 message gives the user nothing to quote and gives the log nothing to correlate against, cannot be added without changing and redeploying both sides together. Worth deciding before Epic 3, not after.
status: open

### DW-14: make dev's cleanup trap does not reach uvicorn's --reload worker, which can keep API_PORT bound after the developer stops the run.
origin: spec-deferred 8ee5c36927cb
location: Makefile:37
source_spec: `spec-1-1-project-scaffold-design-token-foundation.md`
severity: low
reason: The trap runs `pkill -P $api_pid; kill $api_pid`, which reaches the uv wrapper and its direct children. uvicorn --reload runs the actual server in a grandchild, so it can survive and hold the port; the next `make dev` then fails the health gate with the misleading "port busy, or an import error" message. The usual fix is to start the API in its own process group and signal the group, but macOS ships no setsid, so this needs a portable approach rather than a one-line change.
status: open

### DW-15: The two halves of shared/schema are each asserted against the contract independently; nothing checks them against each other.
origin: spec-deferred 6f88bfaec97f
location: shared/schema/shared_schema/ts/errors.ts
source_spec: `spec-1-1-project-scaffold-design-token-foundation.md`
severity: low
reason: shared/schema/tests/test_errors.py and apps/web/src/__tests__/error-envelope.test.ts each encode the same closed shape separately, and README.md claims the two files "cannot drift apart unnoticed". No test feeds a Python-produced envelope through isErrorEnvelope or compares the two definitions, so the parity holds by review rather than by test. Closing it means running a JS runtime from pytest or fixturing generated bodies — a cross-language test harness decision.
status: open

### DW-16: `status` reports only the migrations it finds on disk, so a version recorded as applied whose `.sql` files were deleted or renamed is invisible in the one command an operator reaches for first.
origin: spec-deferred c678823254b2
location: infra/rocell_infra/migrate.py
source_spec: `spec-1-2-user-schema-seeded-administrator.md`
severity: low
reason: infra/rocell_infra/migrate.py's status iterates the plan and reports each file's applied flag. `down` raises a hard error for exactly that condition, so the diagnostic command stays silent about the state the destructive command refuses on.
status: open

### DW-17: `updated_at` has a DEFAULT but no trigger, so every future writer (Stories 1.3, 1.5, 1.10, 1.11) has to remember to set it by hand and nothing catches the first one that forgets.
origin: spec-deferred 06373583f408
location: infra/migrations/20260917T1200_create_users.up.sql
source_spec: `spec-1-2-user-schema-seeded-administrator.md`
severity: medium
reason: 20260917T1200_create_users.up.sql declares `updated_at timestamptz NOT NULL DEFAULT now()` with no BEFORE UPDATE trigger. Only the reseed path sets it explicitly today. Adding a trigger is a schema decision that touches every later write path, so it is better taken deliberately than as a drive-by.
status: open

### DW-18: The entire database-backed suite skips itself where PostgreSQL is absent, and no CI pipeline exists to guarantee it ever runs.
origin: spec-deferred 5f792af9eacb
location: infra/tests/conftest.py
source_spec: `spec-1-2-user-schema-seeded-administrator.md`
severity: medium
reason: infra/tests/conftest.py falls back to `pytest.skip("no PostgreSQL available")` when TEST_DATABASE_URL is unset and initdb/pg_ctl are not on PATH. Every assertion about seeding, idempotency, the 72-hour expiry and the guarded `down` lives behind that fixture, so on such a machine a green `make test` proves none of them. It runs here (PostgreSQL 16.15 is on PATH). Story 1.1 already deferred the CI decision this depends on.
status: open

### DW-19: `verify_password` has no rehash path, so digests stay at the old cost forever if the pinned Argon2id parameters are ever raised.
origin: spec-deferred 0d02ae33fa83
location: shared/schema/shared_schema/passwords.py
source_spec: `spec-1-2-user-schema-seeded-administrator.md`
severity: low
reason: shared/schema/shared_schema/passwords.py pins the parameters explicitly so a library upgrade cannot change them silently, but offers no `check_needs_rehash` equivalent. Who owns re-hashing on next login is a Story 1.3 decision, not a patch here.
status: open

### DW-20: The migrations directory is resolved relative to the installed package, so a non-editable install would ship the runner without any migrations.
origin: spec-deferred a566173bbc49
location: infra/rocell_infra/migrate.py
source_spec: `spec-1-2-user-schema-seeded-administrator.md`
severity: low
reason: infra/pyproject.toml packages `rocell_infra` only; the runner resolves `migrations/` as a sibling of the package directory. That holds for the uv workspace's editable install and for `make migrate` here, and breaks for a wheel-based deployment. The deployment target is itself still undecided (architecture spine, Deferred).
status: open

### DW-21: The ledger stores no checksum, so editing an already-applied migration leaves two databases silently divergent.
origin: spec-deferred 766c26e0fab9
location: infra/rocell_infra/migrate.py
source_spec: `spec-1-2-user-schema-seeded-administrator.md`
severity: low
reason: `schema_migrations` records version and applied_at only. AGENTS.md's "never edit an applied migration" is the stated control, and a checksum column would make a violation detectable rather than conventional.
status: open

### DW-22: A migration whose version sorts before an already-applied one is applied out of order with no warning.
origin: spec-deferred 51c0ac767d8f
location: infra/rocell_infra/migrate.py
source_spec: `spec-1-2-user-schema-seeded-administrator.md`
severity: low
reason: `up` applies every unapplied file in lexicographic order regardless of what is already in the ledger, so a branch merged with a backdated timestamp lands after migrations it was written before. `down` now reverts in applied_at order, which contains the damage but does not prevent it. Refusing a backdated version is a workflow decision.
status: open

### DW-23: `users` constrains `role` and the case of `email`, but nothing stops an empty or malformed `name` or `email` at the database level.
origin: spec-deferred 7ef00c0de205
location: infra/migrations/20260917T1200_create_users.up.sql
source_spec: `spec-1-2-user-schema-seeded-administrator.md`
severity: low
reason: 20260917T1200_create_users.up.sql carries CHECK (email = lower(email)) and the role CHECK, so the database holds its own copy of those rules. `''` passes both. The seed path is protected only because config.py validates the address before it gets there; Story 1.5's admin-created users have no such guard, and the file's own comment argues the database should not have to trust application code.
status: open

### DW-24: `verify_password` offers no constant-time path for an unknown email, so Story 1.3's login can leak account existence by timing.
origin: spec-deferred f0f95424e456
location: shared/schema/shared_schema/passwords.py
source_spec: `spec-1-2-user-schema-seeded-administrator.md`
severity: low
reason: shared/schema/shared_schema/passwords.py exists precisely so the seed and the login verifier cannot drift apart, but exposes only hash_password and verify_password. A login endpoint that skips hashing when no user matches answers measurably faster for an unknown address. The usual fix is a dummy verify against a fixed decoy digest — and adding it in apps/api later would recreate the second-hasher problem this module prevents, so it belongs here. Story 1.3 owns the decision.
status: open

### DW-25: The seed migration's `down` deletes "the one unclaimed Administrator", which is not necessarily the one it created.
origin: spec-deferred 122a525156a2
location: infra/migrations/20260917T1210_seed_administrator.down.sql
source_spec: `spec-1-2-user-schema-seeded-administrator.md`
severity: low
reason: 20260917T1210_seed_administrator.down.sql matches on role, unclaimed and exactly-one-admin rather than on an identity it recorded. If the seeded row is already gone and exactly one admin-created, still-unclaimed Administrator remains, `down` deletes that one. Recording the seeded id would need a marker the ledger does not carry today.
status: open

### DW-26: `down` prints "reverted <version>" even when the seed migration's down SQL deliberately deleted nothing.
origin: spec-deferred 11a7383c1b1a
location: infra/rocell_infra/migrate.py
source_spec: `spec-1-2-user-schema-seeded-administrator.md`
severity: low
reason: main() reports the version `down` returns, and the seed down is a no-op on a live system by design (claimed account, or a second Administrator) — infra/tests/test_migrate.py asserts exactly that. The ledger row is still removed, so the report is not wrong, but the operator is told a revert happened when the product state is unchanged. Reporting affected rows per migration is a runner-wide output decision.
status: open

### DW-27: A `TEST_DATABASE_URL` whose role cannot CREATE DATABASE errors every test instead of skipping, unlike the ephemeral-cluster path.
origin: spec-deferred c61584dd2ffd
location: infra/tests/conftest.py
source_spec: `spec-1-2-user-schema-seeded-administrator.md`
severity: low
reason: infra/tests/conftest.py's `database_url` fixture creates a database per test. When TEST_DATABASE_URL is set the fixture uses it unconditionally, so an InsufficientPrivilege surfaces as an error in every database test rather than the single honest skip the no-PostgreSQL path produces.
status: open

### DW-28: Putting the Argon2id hasher in `shared/schema` makes `argon2-cffi` a hard dependency of every consumer of the shared *type* contracts, including `shared/vision` and `scripts/ingest`, which will never
origin: spec-deferred dc3be46e28f7
location: shared/schema/shared_schema/passwords.py
source_spec: `spec-1-2-user-schema-seeded-administrator.md`
severity: medium
reason: `shared_schema/__init__.py` re-exports `hash_password` / `verify_password`, so the import is eager and no consumer can opt out; `shared/schema/pyproject.toml` declares the dependency for the whole package. The intent requires one shared hashing module and `shared/*` is the only direction both callers may depend on, but it does not fix which shared package — a `shared/security` would carry it without widening the type package's dependency surface. Splitting it once `shared/vision` exists is cheaper than splitting it now against one caller.
status: open

### DW-29: The ephemeral test cluster runs `initdb --auth=trust` on a TCP listener, and a genuine `pg_ctl` misconfiguration is reported as "no PostgreSQL available", which is untrue.
origin: spec-deferred effd1d9832d9
location: infra/tests/conftest.py
source_spec: `spec-1-2-user-schema-seeded-administrator.md`
severity: low
reason: infra/tests/conftest.py starts the cluster with `--auth=trust` on 127.0.0.1, so any local user can connect as `postgres` for the life of the run; and `give_up` turns every initdb/pg_ctl failure into `pytest.skip`, after up to five start attempts, so a broken environment reads as an absent one. Both are test-harness hardening that depends on the still-open CI decision (Story 1.1) for where these tests are expected to run.
status: open

### DW-30: The version prefix is validated as a shape but never parsed as an instant, and `discover_migrations` refuses any non-migration file, so `infra/migrations/README.md` cannot exist.
origin: spec-deferred 449020ac972f
location: infra/rocell_infra/migrate.py
source_spec: `spec-1-2-user-schema-seeded-administrator.md`
severity: low
reason: VERSION_PATTERN is `^\d{8}T\d{4}_...`, so `99999999T9999_do_things` plans happily while two migrations written in the same minute cannot be ordered against each other. Separately, every file that is not `.up.sql`/`.down.sql` and not a dotfile raises, which keeps a stray `.DS_Store` from breaking `status` but also blocks the natural home for the naming rules the runner enforces. Both are workflow decisions about the migrations directory.
status: open

### DW-31: `schema_migrations` is created outside the migration set and has no `down`, so stepping every migration back leaves the ledger table behind.
origin: spec-deferred 495071dae99e
location: infra/rocell_infra/migrate.py
source_spec: `spec-1-2-user-schema-seeded-administrator.md`
severity: low
reason: `ensure_ledger` creates it on demand and no migration owns it, so after `down --yes` twice `users` is gone and `schema_migrations` remains — verified live. "Reversible" therefore holds for what the migrations created, not for the runner's own bookkeeping. Whether the ledger should be a migration of its own is a runner-wide decision.
status: open

### DW-32: The two subprocess suites sit in the default `testpaths` with no marker, and `--strict-markers` means introducing one is itself a config change, so there is no way to run the fast suite alone.
origin: spec-deferred 29565dac5187
location: pyproject.toml
source_spec: `spec-1-2-user-schema-seeded-administrator.md`
severity: low
reason: tests/test_make_targets.py and infra/tests/test_make_targets_database.py each spawn `make` then `uv run` with 300s timeouts, and several cases hash or verify 64 MiB Argon2 digests. `make test` is the command CLAUDE.md says to run before considering any change complete, so its cost matters; adding a `slow`/`db` marker also decides how CI will select tests, which Story 1.1 left open.
status: open

### DW-33: `/health` answers 200 against an unreachable or wrong database, and `PoolTimeout`/`OperationalError` surface as a generic 500 rather than a 503, so `make dev`'s health gate can pass against a database
origin: spec-deferred 73eedefaa78e
location: apps/api/api/db.py
source_spec: `spec-1-3-admin-provisioned-login.md`
severity: medium
reason: apps/api/api/db.py opens the pool with POOL_MIN_SIZE = 0 and pool.open(wait=False), so no connection is attempted at startup, and /health in api/main.py deliberately touches nothing. The startup guard catches an *unset* DATABASE_URL only. Adding a readiness endpoint and a 503 mapping (main.py's STATUS_CODES has no 503 entry) means choosing probe semantics and a Retry-After policy, which is a deployment decision the architecture spine still lists as open.
status: open

### DW-34: The connection pool's max size is smaller than Starlette's sync threadpool, so concurrent logins can each allocate a 64 MiB Argon2id hash while most of them queue for a connection and then time out.
origin: spec-deferred 1a6f908bcbef
location: apps/api/api/db.py
source_spec: `spec-1-3-admin-provisioned-login.md`
severity: medium
reason: apps/api/api/db.py sets POOL_MAX_SIZE = 10; FastAPI runs the sync `login` handler in a threadpool defaulting to 40 workers, and the endpoint is unauthenticated. Bounding this is login throttling, which epics.md assigns to Story 1.6 over AD-8's Postgres counters, so the fix belongs with that story rather than as a drive-by limit here.
status: open

### DW-35: `apps/api/tests/conftest.py` duplicates ~110 lines of `infra/tests/conftest.py`'s initdb/pg_ctl cluster handling, and the two copies must now be changed in lockstep with nothing enforcing it.
origin: spec-deferred 5c77ce34ab28
location: apps/api/tests/conftest.py
source_spec: `spec-1-3-admin-provisioned-login.md`
severity: low
reason: Both files carry their own _free_port, _with_database and _start_ephemeral_cluster. The standard fix is an importable test-support module referenced through pytest_plugins, or a root conftest.py — either one relocates Story 1.2's fixtures, which is a test-layout decision rather than a patch to this story's code.
status: open

### DW-36: `POST /auth/login` has no CSRF defence, so a cross-site form post can sign a victim's browser into an attacker-controlled account.
origin: spec-deferred f99df62523c0
location: apps/api/api/auth.py
source_spec: `spec-1-3-admin-provisioned-login.md`
severity: low
reason: SameSite=Strict protects the authenticated routes but not login itself, which is unauthenticated by definition. Subsequent scans would then be attributed to the attacker's account. For an internal-only tool this may be an acceptable risk, but unlike every other security decision in this change it is currently neither mitigated nor written down; the independent penetration test AGENTS.md requires will raise it.
status: open

### DW-37: `apps/web` never revalidates a session the server has stopped honouring, so the shell keeps rendering after an expiry or a deactivation until the page is reloaded.
origin: spec-deferred e76ef8673aec
location: apps/web/src/auth/SessionProvider.tsx
source_spec: `spec-1-3-admin-provisioned-login.md`
severity: low
reason: SessionProvider bootstraps once on mount and changes status only on an explicit sign-in or sign-out. EXPERIENCE.md line 90 owes a "session expired mid-flow" pattern, and epics.md Story 1.5 owns session persistence and expiry, so the revalidation trigger belongs there. No other authenticated route exists yet, so nothing observes the gap today.
status: open

### DW-38: The API sets no security response headers at all, so the login screen — the product's only unauthenticated surface — can be framed, and no response carries `X-Content-Type-Options` or a
origin: spec-deferred 89a3b1d0ecaa
location: apps/api/api/main.py
source_spec: `spec-1-3-admin-provisioned-login.md`
severity: medium
reason: apps/api/api/main.py installs four exception handlers and no middleware. A clickjacking overlay over the sign-in form is free, and a MIME sniff on any response is unrestricted. The fix is one middleware, but its content is a deployment decision rather than a drive-by: apps/web is served as static files by something other than this API, so `frame-ancestors` belongs to that server, and a CSP needs the web app's real script and style sources — which Vite's dev server and a production build do not agree about yet. DW-4's unresolved production path is the same decision.
status: open

### DW-39: The whole apps/api database suite skips itself where PostgreSQL is absent, so `make test` reports green with zero coverage of login, logout, session lookup and the seeded-administrator composition.
origin: spec-deferred 1202c238f1fe
location: apps/api/tests/conftest.py
source_spec: `spec-1-3-admin-provisioned-login.md`
severity: medium
reason: apps/api/tests/conftest.py calls pytest.skip from a session-scoped fixture when initdb/pg_ctl are not on PATH, mirroring the pattern infra/tests/conftest.py established in Story 1.2. On this machine all 320 tests run, but a CI image without PostgreSQL would report success for a suite that asserted nothing about the story. Fixing it means choosing a policy — an opt-in REQUIRE_POSTGRES that fails instead of skipping, or a floor on how many database tests must have run — and applying it to both packages at once, which is the same test-layout decision the conftest-duplication entry above is waiting on.
status: open

### DW-40: `POST /auth/password` is a second Argon2id-backed endpoint that the forced-change gate must leave open, so a signed-in user on a temporary credential can spend two ~100ms hashes per request against a
origin: spec-deferred 5c9857b72c61
location: apps/api/api/auth.py
source_spec: `spec-1-4-forced-password-change-on-first-login.md`
severity: medium
reason: The handler verifies the candidate against the stored digest (the reuse rule) and then hashes the accepted one, so each call costs two 64 MiB Argon2id operations. `require_claimed_user` cannot gate it — that is the point of the endpoint — and Story 1.6's counters are scoped to login by epics.md. Combined with DW-34 (POOL_MAX_SIZE = 10 behind a 40-worker sync threadpool) a modest burst from one authenticated account queues every other request behind it. Bounding it means choosing whether the counter is per-account or per-session and whether it shares Story 1.6's substrate, which is that story's decision to take.
status: open

### DW-41: `make reseed-admin` refuses an account with a recorded sign-in, so an Administrator who signs in on the temporary credential and lets the 72 hours lapse without claiming has no console path back in at
origin: spec-deferred a3b730ae080b
location: infra/rocell_infra/seed.py:54
source_spec: `spec-1-4-forced-password-change-on-first-login.md`
severity: high
reason: `_SELECT_UNCLAIMED_ADMINISTRATOR` carries `AND last_login_at IS NULL`, so the reissue treats a sign-in as a claim. After the deadline passes, login refuses the credential (Story 1.3), `POST /auth/password` refuses it and revokes the sessions riding on it, and the reissue refuses the account — on a database whose only Administrator is in that state the product is unreachable and recovery is a manual `UPDATE`. Pre-existing: the predicate and the login refusal both predate this story, which only narrowed the window rather than opening it. `infra/rocell_infra/seed.py` is marked read-only by this spec's Code Map, and widening the reissue is a decision about what counts as a claim — the same judgement Story 1.8's account creation has to make.
status: open

### DW-42: Nothing revokes a session when a temporary credential's deadline passes; only an attempt to use it does, so an unclaimed holder keeps a live session for the session's full seven days.
origin: spec-deferred 3c1125563c1d
location: apps/api/api/sessions.py
source_spec: `spec-1-4-forced-password-change-on-first-login.md`
severity: medium
reason: `_SELECT_SESSION` joins on `s.expires_at > now() AND u.active` and never reads `temp_credential_expires_at`. A holder who signs in at hour 1 and never posts to `/auth/password` still gets `200` from `GET /auth/session` with the flag set, `204` from logout, and `403` rather than `401` from every gated route, for four days past the credential's death. Closing it means either widening the one AD-3 session lookup (which this story is forbidden to fork) or a sweep job, and Story 1.5 owns session lifetimes.
status: open

### DW-43: `apps/web` has no state, microcopy or test for the expired-credential path, so the most likely real failure lands the user on the login screen with a message that reads as a typo.
origin: spec-deferred 30de9405ee67
location: apps/web/src/auth/SessionProvider.tsx
source_spec: `spec-1-4-forced-password-change-on-first-login.md`
severity: medium
reason: `changePassword`'s `unauthorized` branch sets `signed-out` and rethrows with nothing shown; the login screen then answers the generic `INVALID_CREDENTIALS` sentence, which says "you typed it wrong" rather than "your 72 hours are up, ask an Administrator". The server side is right and tested; the screen has no row in this story's I/O matrix for it, and writing one is a copy decision under EXPERIENCE.md's tone rules that also depends on the reseed question above.
status: open

### DW-44: A `must_change_password` row with a NULL `temp_credential_expires_at` is permanently unusable by design, and nothing warns the Administrator who will be able to create one.
origin: spec-deferred d7d147eca4b0
location: apps/api/api/auth.py:125
source_spec: `spec-1-4-forced-password-change-on-first-login.md`
severity: medium
reason: `credential_expired` fails closed, deliberately and correctly: such a row is refused at login, 403s on every gated route and 401s at `POST /auth/password`. Today only the seeder writes the flag and it always writes an expiry, so the shape is unreachable. Story 1.10 edits users and "force a password change" is the obvious next control; an admin who sets the flag without an expiry would brick the account with no feedback. The fix is a constraint or a default on `users`, which is a migration and a decision for the story that adds the control.
status: open

### DW-45: `ForcedPasswordChangeScreen` duplicates `LoginScreen`'s form machinery and stylesheet almost exactly; Story 1.7's change form will be the third copy.
origin: spec-deferred 347ecf4d1aed
location: apps/web/src/screens/ForcedPasswordChangeScreen.tsx
source_spec: `spec-1-4-forced-password-change-on-first-login.md`
severity: medium
reason: Stripped of comments the two stylesheets differ only in `.panel`'s card declarations — `.screen`, `.title`, `.lede`, `.form`, `.field`, `.label`, `.input`, `.submit`, `.submit:disabled` and `.error` are identical — and the component repeats the same `useId` / `noValidate` / `aria-describedby` / inserted-`role="alert"` / `submitting` pattern. The cost is already visible in `styling-wiring.test.ts`, which had to be parameterised over two files. Extracting it is a component-API decision better taken with the third caller in hand than guessed at now.
status: open

### DW-46: The boundary of every text input is `--color-border` on its container at roughly 1.2:1, under WCAG 1.4.11's 3:1 floor for a control boundary.
origin: spec-deferred f4f4816c429c
location: apps/web/src/styles/tokens.css:32
source_spec: `spec-1-4-forced-password-change-on-first-login.md`
severity: low
reason: `#ECE6DB` on the panel's `#FFFFFF` is about 1.24:1, and on the login screen's `#FAFAF8` about 1.19:1 — the new screen is marginally the better of the two, so this is not something this story introduced. It affects every form surface the product will grow. Fixing it means darkening `--color-border` or giving inputs their own border token, which is a DESIGN.md change, not a code change.
status: open

### DW-47: A login that commits a session between `delete_sessions_for_user` and the password change's COMMIT survives the credential rotation.
origin: spec-deferred 02e93cca950f
location: apps/api/api/auth.py
source_spec: `spec-1-4-forced-password-change-on-first-login.md`
severity: low
reason: The change runs in one transaction, but the DELETE does not block an INSERT of a row that does not exist yet, so under read-committed a concurrent login on the still-valid temporary password can land a session that outlives the rotation. It needs a second party who knows the temporary credential and races a ~100ms window. Closing it properly means locking the user row for the duration of the change, which is a concurrency decision that touches login as well.
status: open

### DW-48: Request-validation rejections carry no `cache-control` at all, against the rule that every auth response carries `NO_STORE`.
origin: spec-deferred d37acf206b60
location: apps/api/api/main.py:104
source_spec: `spec-1-4-forced-password-change-on-first-login.md`
severity: low
reason: `validation_error_handler` passes no headers to `_envelope`, so the `422 validation_error` from a malformed or absurd body ships bare — on `POST /auth/login` since Story 1.3 and now on `POST /auth/password` too. The bodies say nothing about an account, so the exposure is small, but the invariant is stated absolutely and this is the one hole in it. The fix is one shared default in the handler, which touches every endpoint's rejections at once.
status: open

### DW-49: A whitespace-only password of twelve or more characters is accepted by `POST /auth/password` but can never be submitted at the login screen.
origin: spec-deferred 15da4b84179a
location: shared/schema/shared_schema/passwords.py
source_spec: `spec-1-4-forced-password-change-on-first-login.md`
severity: low
reason: `LoginScreen`'s blank guard tests `.trim()` and refuses to send, so a user who set twelve spaces as their password would be locked out of the UI by the client, with a valid digest in the database. The guard predates this story. Refusing it at the API means a third rule message where EXPERIENCE.md names two, so it is a policy decision rather than a fix.
status: open
