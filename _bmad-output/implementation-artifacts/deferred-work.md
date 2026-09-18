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
resolution: `spec-1-5-session-persistence-expiry.md`. `api/client.ts` gained `onUnauthorized`, a module-level observer `apiRequest` invokes for every `unauthorized` rejection, and SessionProvider registers it while signed in — so any request's 401 drops the shell to the login screen with a factual notice. A `visibilitychange` listener revalidates once when a backgrounded tab returns. Deliberately no interval: a poll is itself an authenticated request and would keep an unattended tab's session alive forever.
status: resolved

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

### DW-50: The rule that renewal can never extend a session's 7-day ceiling is a property of the call sites, not of the table: nothing at the database level stops a future writer from updating
origin: spec-deferred 88171b208b31
location: infra/migrations/20260917T1400_track_session_activity.up.sql
source_spec: `spec-1-5-session-persistence-expiry.md`
severity: low
reason: The whole security argument for the two-column shape is that `_TOUCH_SESSION` writes `last_seen_at` and only `last_seen_at`, so the absolute bound read from `issued_at` is unreachable from the renewal path. That holds today because `api/sessions.py` is the one module allowed to touch the table and its only `UPDATE` is the touch — an invariant currently guarded by one Python test. A `BEFORE UPDATE` trigger, or a `CHECK` tying `expires_at` to `issued_at`, would make it true of the table itself. That is a migration and a decision about whether any story ever needs to move either column (Story 1.11's deactivation currently ends sessions by deleting rows, not by updating them), which is out of scope for a story whose acceptance clauses are about behaviour rather than schema hardening.
status: open

### DW-51: `visibilitychange` is the only revalidation trigger, and on iOS Safari a page restored from the back-forward cache can come back without one — the exact "tab backgrounded for hours" case, on the
origin: spec-deferred c717335cc4a7
location: apps/web/src/auth/SessionProvider.tsx:182
source_spec: `spec-1-5-session-persistence-expiry.md`
severity: low
reason: `SessionProvider`'s second effect listens for `visibilitychange` alone. A bfcache restore fires `pageshow` with `persisted: true`, and whether `visibilitychange` also fires is implementation-specific and has moved between Safari versions. If it does not, a phone left on the login-adjacent shell overnight comes back to a shell rendering over a dead session until the user's first action fails — a narrower version of DW-37 rather than a regression of it, since the action itself still drops to login. Adding a `pageshow` listener beside the existing one is small, but it is a behaviour change whose whole value is on a device this suite cannot drive: jsdom has no bfcache, so a vitest case would assert only that a listener was registered. It wants verification on a real iOS device, which is a different kind of task from the rest of this story.
status: open

### DW-52: The revalidation on `visibilitychange` is itself an authenticated request, so foregrounding a tab slides the 12-hour idle window forward without the user having done anything in the app.
origin: spec-deferred 68769bc471c0
location: apps/web/src/auth/SessionProvider.tsx (the visibilitychange effect)
source_spec: `spec-1-5-session-persistence-expiry.md`
severity: low
reason: `SessionProvider`'s second effect issues `GET /auth/session` whenever the tab becomes visible, and that request goes through `lookup_session` -> `_touch_session` like any other. On a phone, the OS fires `visibilitychange` every time the PWA is foregrounded — so picking the handset up and putting it down buys another 12 hours, with no interaction. The comment above the effect says "Nothing in this app may keep a session alive on its owner's behalf", and the matrix row it implements says a hidden tab makes no request at all; both hold literally, and the property they exist to protect is still reachable from the visible side. Closing it means a "revalidate at most every N minutes" rule, or reading the session without touching it, and both are behaviour the intent's matrix does not describe — the matrix requires the revalidation unconditionally. That makes it a decision about what counts as activity, not a defect in the code as specified.
status: open

### DW-53: `ARCHITECTURE-SPINE.md`'s `SESSION` ERD block does not carry `last_seen_at`, so the spine now describes a narrower table than the one the product has.
origin: spec-deferred ed8957beceab
location: _bmad-output/planning-artifacts/architecture/architecture-rcl_camera_app-2026-08-30/ARCHITECTURE-SPINE.md:243
source_spec: `spec-1-5-session-persistence-expiry.md`
severity: low
reason: The block lists `id`, `user_id`, `token_hash`, `issued_at` and `expires_at`. AD-3's rule is untouched by this story — it says the lookup is shared, not that it is read-only — but the ERD is a column list and is now incomplete, and `infra/README.md` points at that block by name as the description of the table. Amending a planning artifact from inside a story is a scope question this story has no authority to settle on its own; recording it here is the cheaper half.
status: open

### DW-54: The `apps/web` suite failed twice during this review pass with a `findByLabelText`/`findByTestId` timing out at ~1s, and did not reproduce in eleven subsequent runs including a cold-cache one.
origin: spec-deferred c140d1990821
location: apps/web/src/__tests__/session-expiry.test.tsx
source_spec: `spec-1-5-session-persistence-expiry.md`
severity: low
reason: Both failures were in `session-expiry.test.tsx` and both were a `findBy*` exhausting testing-library's default 1000ms timeout rather than an assertion reporting a wrong value; the runs that failed were also the slowest overall (3.1s vs a steady 1.8s). Clearing `node_modules/.vite`, touching every source file and re-running did not reproduce it, so the cold-transform explanation is unconfirmed. Left alone it is a test that fails for one person, once, on the story's central assertion — worth either raising the timeout for the async screen-swap cases or finding the real cause before it is dismissed as noise.
status: open

### DW-55: A password spray — one password tried across every staff address — trips no counter at all, while every attempt still buys a full Argon2id verify.
origin: spec-deferred 052f5bbfcc32
location: apps/api/api/throttle.py
source_spec: `spec-1-6-login-rate-limiting.md`
severity: medium
reason: `api/throttle.py` keys the counter on the submitted address, which is what removes the account-existence oracle a per-account ladder would create. The cost is that the per-address counter is blind to the attack that uses each address once. FR-4 is written per account and the architecture spine's review-security.md already raised this against it, so closing it means a second counter — per source IP, or a global failure rate — and a decision about what to key it on that FR-4 does not make. `throttle.py`'s "Not here" section names FR-22, FR-23 and DW-40 and is silent on this one.
status: open

### DW-56: `AttemptState.retry_after()` subtracts a Postgres-produced timestamp from the API host's clock, in a module whose whole argument is that every decision is made against the database clock.
origin: spec-deferred bb27b144e021
location: apps/api/api/throttle.py (AttemptState.retry_after)
source_spec: `spec-1-6-login-rate-limiting.md`
severity: low
reason: `locked_until` is written by `now()` inside `_RECORD_FAILURE` and read back through `RETURNING`; `retry_after()` then compares it to `datetime.now(UTC)`. Skew between the two hosts mis-states the `Retry-After` header in either direction. Nothing in the product reads that header — `apps/web` is forbidden to render it — so the consequence is confined to a conforming third-party client. The fix is to have Postgres compute the remaining seconds alongside the lock, which means another column in the `RETURNING` list and a second value threaded through `AttemptState`, for a header nothing currently consumes.
status: open

### DW-57: `make reseed-admin` issues a fresh credential that the lock then refuses, and clears neither the `login_attempts` row nor `users.locked_until`.
origin: spec-deferred 2f148bff9084
location: infra/rocell_infra/seed.py
source_spec: `spec-1-6-login-rate-limiting.md`
severity: low
reason: `infra/rocell_infra/seed.py`'s reissue updates `password_hash`, `must_change_password`, `temp_credential_expires_at` and `updated_at` only. An Administrator locked out by ten failures who reaches for the one console tool they have gets a credential that is refused for the remainder of `LOCKOUT_DURATION`, and an account whose status still reads locked afterwards. Bounded at fifteen minutes, so it is an inconvenience rather than the unreachable-product hazard DW-41 describes — but it is the same recovery path, and widening the reissue to clear the throttle is a decision about what `reseed-admin` is for.
status: open

### DW-58: `login_attempts` grows one row per invented address for a full `ATTEMPT_WINDOW`, and those rows are exactly the ones the sweep is forbidden to delete.
origin: spec-deferred 9e2e1b69082a
location: infra/migrations/20260918T1000_add_login_throttling.up.sql
source_spec: `spec-1-6-login-rate-limiting.md`
severity: low
reason: `_SWEEP_ATTEMPTS` only removes rows whose `last_failure_at` is older than `ATTEMPT_WINDOW`, so a dictionary run against thousands of addresses leaves every row it creates untouchable for an hour — and `last_failure_at` carries no index, so each subsequent failed attempt scans them. The migration comment and `infra/README.md` now say this honestly rather than claiming a backlog never accumulates. Bounding it means either an index paid on every failure or a row-count ceiling with a policy for what to evict, and both are measurements this story has no numbers for.
status: open

### DW-59: Changing a user's email address (Story 1.10) leaves the lock on the old address string and a stale `users.locked_until` on the account.
origin: spec-deferred 2ae5330307f1
location: apps/api/api/throttle.py (_MIRROR_LOCK)
source_spec: `spec-1-6-login-rate-limiting.md`
severity: low
reason: The counter's primary key is the submitted address, and `_MIRROR_LOCK` matches on `lower(email)`. After an edit, the old string keeps its live lock — reachable by anyone who still tries it, which is harmless — while the new address starts from zero, which is a lock-evasion path that requires an Administrator to walk it. The mirror is never cleared either, so the account's status keeps reporting a lock that no longer corresponds to anything. Deciding whether a rename carries its counter is Story 1.10's to make; nothing here can settle it.
status: open

### DW-60: The progressive delay is per-attempt only when attempts are serial: a burst that arrives together all reads the same count and pays one rung between them.
origin: spec-deferred cf1acabbac1c
location: apps/api/api/auth.py (login)
source_spec: `spec-1-6-login-rate-limiting.md`
severity: medium
reason: `login` reads `attempt_state`, sleeps, and only then does the credential work that records the failure, so ten simultaneous guesses at a count of five all see rung one and all sleep one `DELAY_STEP` in parallel instead of paying 1+2+3+4+4 seconds between them. The lockout at `FAILURES_BEFORE_LOCKOUT` is unaffected — the increment is AD-8's single atomic statement and every failure still lands — and the re-read added after the sleep now stops any of them authenticating once the lock is written. What is left is that the ladder's *cost* is per round trip rather than per attempt. Closing it means making the delay a property of the request rather than of the row it read — a queue, a per-address semaphore, or counting the attempt before it is processed rather than after — and each of those is a different design from the one FR-4's "delay before it's processed" describes.
status: open

### DW-61: `_MIRROR_LOCK` moves `users.updated_at` on an account nobody edited, so the column stops meaning "an Administrator changed this".
origin: spec-deferred 438c8fde6b20
location: apps/api/api/throttle.py (_MIRROR_LOCK)
source_spec: `spec-1-6-login-rate-limiting.md`
severity: low
reason: The mirror sets `updated_at = now()` alongside `locked_until` because DW-17 leaves the column to be maintained by hand, and the spec's task list asks for exactly that. The consequence is that ten wrong guesses from a stranger now bump a timestamp that Stories 1.9 and 1.10 are the most likely readers of — a "recently changed" sort, or an optimistic concurrency check on the edit form, would both be driven by an attacker. Separating them means either a second column or a rule that the mirror is not an edit, and which one is right depends on what 1.10 decides `updated_at` is for.
status: open

### DW-62: DW-54's `session-expiry.test.tsx` flake reproduced twice in three full `apps/web` runs during this pass, and not once in six runs of that file on its own.
origin: spec-deferred 790a080b9cfa
location: apps/web/src/__tests__/session-expiry.test.tsx:237
source_spec: `spec-1-6-login-rate-limiting.md`
severity: low
reason: Recorded here as new evidence for an entry that already exists, not as a new defect: this pass changed no `apps/web` source. Both failures were `findByLabelText(/password/i)` at line 237 exhausting testing-library's default 1000ms, and both were on the slow runs (2.78s and 3.12s against a steady 1.78s for the 13-file suite). Running the file alone passed 6/6 at a flat 1.17s. That points at worker contention across the parallel suite rather than at anything in `SessionProvider`, and it narrows DW-54's open question — "raise the timeout or find the real cause" — to the first option, but raising an async timeout across another story's suite is a decision about the harness that this story has no authority to make.
status: open

### DW-63: A lockout is a free, repeatable denial of service against a named member of staff, and nothing in the product limits or records it.
origin: spec-deferred 89c5eb0409bb
location: apps/api/api/throttle.py
source_spec: `spec-1-6-login-rate-limiting.md`
severity: medium
reason: A locked attempt is refused before any Argon2id work, any counter write and any sleep, so holding a colleague out costs an attacker ten cheap guesses per quarter hour and nothing else. There is no unlock to reach for (FR-5 sends the person to an Administrator; no story gives that Administrator a button until 1.10) and no audit entry until Story 1.12. This is the mirror image of DW-55 and the direct cost of keying the counter on the submitted address — the design note argues the other direction only. Closing it means something the requirement does not describe: a per-source-IP dimension, a shorter lock for a first offence, or an unlock surface. `README.md` now states the exposure plainly; the mitigation is a product decision.
status: open

### DW-64: FR-4's "visible to Administrators" and FR-5's recovery route are handed to Stories 1.9 and 1.10, whose acceptance clauses mention neither.
origin: spec-deferred 462d4be7651d
location: _bmad-output/planning-artifacts/epics.md:286-307
source_spec: `spec-1-6-login-rate-limiting.md`
severity: medium
reason: `throttle.py`, `auth.py`, both READMEs and this spec all say Story 1.9 renders the lock and Story 1.10 gives an Administrator something to press. `epics.md` 1.9 (lines 286-294) asks only for active/deactivated status and a last-login timestamp; 1.10 (296-307) is scoped to name, email and role. Neither names a lock or an unlock, so as the epic stands the column ships and nothing renders it, and FR-5's "goes through an Administrator" has no owner. This story cannot widen another story's acceptance clauses, and the `User` contract work here is complete either way.
status: open

### DW-65: Every sign-in now takes two pooled connections instead of one, including the overwhelming majority that never sleep.
origin: spec-deferred 665a05f86748
location: apps/api/api/auth.py (login)
source_spec: `spec-1-6-login-rate-limiting.md`
severity: medium
reason: `login` opens one `pool.connection()` for `attempt_state`, closes it, and opens a second for `_authenticate` whether or not `delay` is truthy. The split exists so the sleep holds nothing, which only the delayed path needs; against `POOL_MAX_SIZE = 10` and DW-34 it doubles acquisition pressure on the hottest unauthenticated path in the product to buy something the undelayed path does not use. Merging the two blocks when `delay` is falsy is straightforward, but it restructures the handler's connection lifetime around a cost nobody has measured, and CLAUDE.md is explicit that this is the order to do those things in.
status: open

### DW-66: An address holding a control character is the one rejection that is never counted, and it still spends a full Argon2id decoy each time.
origin: spec-deferred 33025746a118
location: apps/api/api/auth.py (_is_addressable)
source_spec: `spec-1-6-login-rate-limiting.md`
severity: low
reason: `_is_addressable` refuses before the counter is ever reached — necessarily, since the counter's key *is* the string Postgres cannot accept — but it pays `verify_dummy_password` first, so appending a NUL to every guess buys unlimited unthrottled Argon2id work and leaves no row behind. The decoy predates this story; what is new is that this is now the only path with no counter behind it. There is no oracle in it (the caller already knows the address is malformed, and no account can hold one), so the exposure is CPU only, and it is the same class DW-55 records for a spray across real addresses. Dropping the decoy on this path alone would close it, but the decoy's placement is an identical-rejection decision this story should not make on its own.
status: open

### DW-67: `_CHANGE_PASSWORD` pins the claimed flag but not the digest it just verified, so two concurrent changes both write and the loser is told the change succeeded.
origin: spec-deferred 7a26d9e1c0a0
location: apps/api/api/auth.py (_CHANGE_PASSWORD)
source_spec: `spec-1-7-self-service-password-reset.md`
severity: medium
reason: `_SELECT_PASSWORD_HASH` runs outside `conn.transaction()`, and the write's only predicate is `AND NOT must_change_password`. Two posts arriving together verify the same stored digest, both match the row, and the last writer wins — the first caller gets a `200` and a `User` body for a password that is not the live one. The same argument the `_CHANGE_PASSWORD` comment makes for the flag ("a property of the statement rather than of a check taken earlier") applies to the digest, and `AND password_hash = %s` would give it. Closing it means deciding what a third empty-`RETURNING` arm answers, which is a contract decision this story's intent does not make; the realistic second trigger — an Administrator resetting a password under the user — arrives with Story 1.10.
status: open

### DW-68: A `403 password_change_required` from the write's race arm renders on Account Settings as a neutral form error, with no route to the forced-change screen and no refresh of the cached user.
origin: spec-deferred 89c4ad0f094c
location: apps/web/src/screens/AccountSettingsScreen.tsx (fieldFor)
source_spec: `spec-1-7-self-service-password-reset.md`
severity: medium
reason: `fieldFor()` in `AccountSettingsScreen.tsx` maps that code to `null`, so the gate's sentence appears as an unattributed form error while `currentScreen()` keeps the user on Account Settings — the cached `must_change_password` is still false until the next `/auth/session` revalidation. It is honest and actionable copy, and the branch is currently unreachable in the product: nothing sets `must_change_password` back to true except a manual UPDATE. Stories 1.8 and 1.10 are what make an Administrator able to reissue, and whether the front end should re-fetch the session or route to the forced-change screen is a decision that belongs with them.
status: open

### DW-69: DW-40 is now a three-endpoint problem — `POST /auth/password/change` adds a 64 MiB Argon2id verify plus a hash per call, reachable by any live session and bounded by nothing.
origin: spec-deferred c8a25df7d33a
location: apps/api/api/auth.py (change_password)
source_spec: `spec-1-7-self-service-password-reset.md`
severity: medium
reason: The handler spends one `verify_password` on every call and one `hash_password` on every success, and is sync, so FastAPI runs it in a threadpool defaulting to 40 workers against `POOL_MAX_SIZE = 10` (DW-34). epics.md scopes Story 1.6's counters to login, so the spec forbids closing it here and the docstring records it — but DW-40's own text names two endpoints and predates this one. Recorded as new evidence for that entry: the memory amplification is now three deep and no test or ceiling acknowledges it.
status: open

### DW-70: The two-field form gives a password manager no username to associate, so managers routinely fail to offer to update the stored credential.
origin: spec-deferred 6c56033268fb
location: apps/web/src/screens/AccountSettingsScreen.tsx
source_spec: `spec-1-7-self-service-password-reset.md`
severity: medium
reason: The form carries `autocomplete="current-password"` and `"new-password"` and no field carrying the identity. Chrome, Safari and 1Password commonly need an associated username — a visually-hidden readonly input with `autocomplete="username"` — before they offer to *update* a saved entry rather than save a second one. The user then changes their password and the manager keeps serving the old one, which is the friction FR-5 exists to remove. `hidden` is not the fix (managers skip it) and jsdom cannot verify any of it, so the correct shape wants checking on a real browser — the same kind of task as DW-51.
status: open

### DW-71: The change signs the user out on every other device and the screen never says so.
origin: spec-deferred 19a3d780168b
location: apps/web/src/screens/AccountSettingsScreen.tsx
source_spec: `spec-1-7-self-service-password-reset.md`
severity: medium
reason: `test_every_other_device_is_signed_out` proves the server does it and README calls it "the point of it", but the whole of what the user is told is "Saved." — the save indicator EXPERIENCE.md specifies. Someone changing a password because they believe a colleague has it gets no confirmation that the thing they actually wanted has happened. Adding a factual line is small and in EXPERIENCE.md's register, but it is copy no file in the pair specifies, and the Save indicator row is what the surface was built to.
status: open

### DW-72: Anyone holding a live session cookie can guess `current_password` without limit, so a borrowed unlocked phone is a path to permanent account takeover rather than only to CPU burn.
origin: spec-deferred e6f61953baa0
location: apps/api/api/auth.py (change_password)
source_spec: `spec-1-7-self-service-password-reset.md`
severity: medium
reason: `change_password` spends a `verify_password` per call and answers `403 invalid_current_password`. Nothing counts the failures: no `login_attempts` row, no `users.locked_until` check, no ceiling, and no record anywhere until Story 1.12's audit log. The existing DW-40 note frames this endpoint as the third Argon2id consumer — a memory-amplification problem — which is a different property from the one here: login refuses an attacker after ten tries and this route refuses them never. The intent's Never list forbids throttling in this story ("Story 1.6 scoped throttling to login"), so it cannot be closed here, but a counter keyed on the session or the user is a smaller decision than DW-40's address-vs-account question and could land ahead of it.
status: open

### DW-73: "The API's sentence, verbatim" is asserted only against sentences retyped into the test files, so the API's copy and the strings the suite checks can drift apart with everything green.
origin: spec-deferred 795103637527
location: apps/web/src/__tests__/error-code-parity.test.ts
source_spec: `spec-1-7-self-service-password-reset.md`
severity: low
reason: `error-code-parity.test.ts` spans the API/web boundary for error *codes* and nothing spans it for *messages*. `account-settings.test.tsx` builds its `ApiRequestError`s from literals authored in that file, and the new real-provider case stubs `WRONG_CURRENT`, also a literal. At run time the screen does render whatever the API sent, so this is a test-fidelity gap rather than a product defect: change `CURRENT_PASSWORD_WRONG` or `MIN_PASSWORD_LENGTH` in Python and the suite keeps passing while its claim to be checking the API's wording stops being true. Closing it wants a message row in the parity test, which is a decision about how much of EXPERIENCE.md's copy belongs under a build-time guard.
status: open

### DW-74: `ROUTE_WORDS` is three words, so a recovery surface named anything but reset, forgot or recover passes the route-table guard.
origin: spec-deferred 3ec5e752085f
location: apps/api/tests/test_no_password_reset.py (ROUTE_WORDS)
source_spec: `spec-1-7-self-service-password-reset.md`
severity: low
reason: `/auth/magic-link`, `/auth/otp` and `/auth/unlock` would all serve exactly the signed-out recovery FR-5 forbids and clear `test_the_route_table_holds_no_recovery_path`. The vocabulary was not widened in this pass on purpose: `reissue` is the obvious next candidate and is also the correct name for the Administrator route Stories 1.8 and 1.10 add, so a wider list risks the same false accusation the bare `boto3` pattern was just narrowed to avoid. Widening it safely means deciding the word list against the routes those stories will actually serve.
status: open

### DW-75: A change can land on the server while the screen reports it as failed, leaving the user typing a password that is no longer theirs.
origin: spec-deferred 527196708cdc
location: apps/web/src/auth/SessionProvider.tsx (changeOwnPassword)
source_spec: `spec-1-7-self-service-password-reset.md`
severity: medium
reason: `changeOwnPassword` stores the response through `asUser`, which throws on a body it does not recognise — and `apiRequest` throws on a transport failure. Either way the write, the revocation and the fresh cookie have already happened: the browser holds the new session, the digest is the new one, and the screen shows a rejection. The user then retypes the *old* password and is answered `invalid_current_password`, with no way to tell which of the two passwords is live. Closing it means re-fetching `/auth/session` on a failure whose status is not 401 — which the spec's own task list forecloses ("Errors propagate untouched … nothing has to be rescued here"), so it is a contract decision rather than a patch. The window is narrow today: the only reachable trigger is a transport failure between the commit and the response.
status: open

### DW-76: The mail-transport guard reads only a fixed extension set and a fixed package vocabulary, so a transport reached for in a Dockerfile, a shell script or an SMS SDK passes it.
origin: spec-deferred 0e93ca3c5b56
location: apps/api/tests/test_no_password_reset.py (SCANNED_EXTENSIONS, _TRANSPORTS)
source_spec: `spec-1-7-self-service-password-reset.md`
severity: low
reason: `SCANNED_EXTENSIONS` has no `.tf`, no `.sh`, and cannot match an extensionless file at all — `Dockerfile`, `Makefile`, a compose override — although `CLAUDE.md` puts IaC in `infra/`, which is the same argument the file already makes for `.yml`/`.yaml`. Separately, `_TRANSPORTS` is a mail vocabulary and FR-5's clause is about *recovery*: an SMS one-time code (`twilio`, `vonage`, `messagebird`, `publish_sms`) is exactly the signed-out path the clause forbids and reads clean through every check in the file. Both are the same decision as DW-74's: widening a word list safely means deciding it against the surfaces later stories will actually build, and a list widened on a guess is the false accusation the bare `boto3` pattern was already narrowed to avoid.
status: open

### DW-77: Provisioning a user writes no audit entry, so the product's first privileged write has no record of who granted whose access.
origin: spec-deferred bc85a1da746b
location: apps/api/api/users.py (create_user)
source_spec: `spec-1-8-create-user-account.md`
severity: medium
reason: AGENTS.md Policy requires the append-only log to cover user changes, and `POST /admin/users` is the clearest one there is. Story 1.12 owns the write path and this endpoint's docstring names the entry it owes; no private log path was built in the meantime. Until that log exists the only trace is the row's own `created_at`, which does not say by whom.
status: open

### DW-78: DW-69 is now a four-endpoint problem — `POST /admin/users` adds a 64 MiB Argon2id hash per call, reachable by any Administrator session and bounded by nothing.
origin: spec-deferred 087e6af07b3d
location: apps/api/api/users.py (create_user)
source_spec: `spec-1-8-create-user-account.md`
severity: medium
reason: The handler hashes on every request that gets past the length rules, and no counter keys on the calling Administrator. FastAPI admits ~40 concurrent sync handlers, so one account can hold ~40 hashes at once. DW-40 and DW-69 are both open and are decisions about what a counter would be keyed on; Story 1.6 scoped throttling to login, and this story could not settle it.
status: open

### DW-79: A mistyped address is permanently consumed by the unique index, and nothing in the product can edit, reissue or remove the row until Stories 1.10/1.11.
origin: spec-deferred 12c9f10f8e76
location: apps/api/api/users.py (_INSERT_USER)
source_spec: `spec-1-8-create-user-account.md`
severity: medium
reason: `users_email_lower_key` refuses the corrected second attempt with `409 email_already_exists`, and the only remaining surface is `POST /admin/users` itself. README.md states the workaround as advice — provision them afresh under a different address — which leaves an unusable row behind with no way to reach it. Story 1.10 owns the edit and 1.11 the delete.
status: open

### DW-80: A `201` whose body or transport fails after the row is committed is reported to the Administrator as a failure, and nothing in the product can tell them which it was.
origin: spec-deferred 720bbb51db01
location: apps/web/src/screens/CreateUserScreen.tsx (handleSubmit)
source_spec: `spec-1-8-create-user-account.md`
severity: medium
reason: `asUser` throws `ApiRequestError(MALFORMED_RESPONSE, ..., 201)` after the INSERT has committed, and the screen's `catch` treats it exactly like a refusal; a timeout or dropped connection after the commit does the same. The retry answers `409 email_already_exists`, and with no user list until Story 1.9 there is no surface that shows whether the row exists. This is DW-75's shape on a new endpoint and needs the same decision.
status: open

### DW-81: Back, Account, Sign out and a mid-session demotion all unmount the screen with no warning, discarding a half-typed form and a result panel holding a credential nothing can recover.
origin: spec-deferred b10777d62e53
location: apps/web/src/App.tsx (showSection), apps/web/src/screens/CreateUserScreen.tsx
source_spec: `spec-1-8-create-user-account.md`
severity: medium
reason: EXPERIENCE.md line 90 asks for exactly this warning — "never silently dropping an in-progress admin form — warn before navigating away from unsaved catalogue/user edits". The temporary password is held only in this screen's state; the API never returns it and no screen can show it again. Building the guard means an unsaved-changes convention the product does not have yet, and it lands on every admin form from Story 1.10 on.
status: open

### DW-82: The request seam between the screen and the endpoint is asserted twice against hand-written literals and never crossed, so renaming a body field on either side leaves both suites green.
origin: spec-deferred 37c462b37f47
location: apps/web/src/__tests__/create-user.test.tsx, apps/api/tests/test_create_user.py
source_spec: `spec-1-8-create-user-account.md`
severity: medium
reason: `create-user.test.tsx` checks the body against a stubbed `fetch`; `test_create_user.py` checks it against its own `_body()`. The *response* is pinned across languages (`user-contract.test.ts` against `User.model_fields`) and so are the error codes (`error-code-parity.test.ts`), but the request body is not. The repository has no e2e harness and no `e2e` make target, so this is structural rather than a choice this story made.
status: open

### DW-83: The three route-table walkers disagree about rigour, and the two weaker ones would pass a sub-application mounted under `/admin/`.
origin: spec-deferred 2ca7d2a162c7
location: apps/api/tests/test_no_registration.py, apps/api/tests/test_forced_change_gate.py
source_spec: `spec-1-8-create-user-account.md`
severity: low
reason: `test_admin_authorization._api_routes` raises `AssertionError` on any route type it does not understand. `test_no_registration._routes()` — whose exact served-path set this story extended — and `test_forced_change_gate`'s own third copy both skip a `Mount`, a `WebSocketRoute` or a static handler silently. Consolidating them is a change to guards three stories already depend on.
status: open

### DW-84: `max_length` runs before the stripping validator, so a name of exactly the bound submitted with surrounding whitespace is refused with the generic `validation_error` although the value that would be
origin: spec-deferred 06f61d30df15
location: apps/api/api/users.py (CreateUserRequest)
source_spec: `spec-1-8-create-user-account.md`
severity: low
reason: Pydantic applies `Field(max_length=MAX_NAME_LENGTH)` to the raw value and `_named` strips afterwards. The parametrized test covers only `"x" * (MAX_NAME_LENGTH + 1)`. Moving the bound into the validator changes which refusal shape the field produces, which is a contract decision rather than a fix.
status: open

### DW-85: The API suite's ephemeral cluster runs a `C.UTF-8` collation whose `lower()` folds ASCII only, so no test can exercise a Python/Postgres case-folding disagreement.
origin: spec-deferred 6d81c2a44e15
location: apps/api/tests/conftest.py
source_spec: `spec-1-8-create-user-account.md`
severity: low
reason: `conftest.py` builds the cluster with `initdb`'s default. A probe of ~12k codepoints against that cluster found zero disagreements, so the behavioural non-ASCII test passes with or without `_INSERT_USER`'s `lower(%s)`; a statement-level pin holds the hardening instead. Running the suite on a full Unicode collation is an `initdb` flag and a separate decision affecting every database test.
status: open

### DW-86: An address whose Python fold and Postgres fold differ can be provisioned successfully and can then never sign in, because the login lookup compares the two folds against each other.
origin: spec-deferred 20eff5189c8c
location: apps/api/api/auth.py (_SELECT_CREDENTIAL, login)
source_spec: `spec-1-8-create-user-account.md`
severity: medium
reason: `_INSERT_USER` stores `lower(%s)` — the Postgres fold — while `auth._SELECT_CREDENTIAL` matches `WHERE lower(email) = %s` against `payload.email.strip().lower()`, the Python fold. The two are equal only where `lower()` agrees across the two implementations, which is exactly the condition `lower(%s)` was added because it can fail. Where it fails the `201`, the response body and the row are all correct and the account is unreachable, with no error anywhere. The lookup is in `auth.py`, which this story's intent forbids changing, and DW-85 records that the suite's `C.UTF-8` cluster cannot observe either half.
status: open

### DW-87: An outstanding or lapsed temporary credential is invisible on the user list, so "Last login: Never" reads the same for a colleague who has not opened their note yet and one whose 72 hours ran out.
origin: spec-deferred 0790cd0bacf1
location: apps/web/src/screens/UserListScreen.tsx
source_spec: `spec-1-9-view-user-list.md`
severity: medium
reason: `GET /admin/users` returns `must_change_password` and `temp_credential_expires_at` on every row and `tests/test_user_list.py::test_an_unclaimed_account_is_listed_with_its_deadline` asserts both reach the wire, but the screen renders five columns and neither is one of them. FR-10 names status and last login only, so this story's acceptance clause does not ask for it; what makes it real is that the product's own README calls the 72-hour deadline load-bearing and nothing in the product can now tell an Administrator that a deadline has passed. Stories 1.10/1.11, which could reissue or remove the row, are the natural owners.
status: open

### DW-88: An Administrator demoted while the user list is open sees the refusal and can press "Try again" forever, with the Users door still on the shell, until something else revalidates the session.
origin: spec-deferred 50a50067a5a3
location: apps/web/src/screens/UserListScreen.tsx
source_spec: `spec-1-9-view-user-list.md`
severity: medium
reason: `SessionProvider` revalidates only on `visibilitychange`, so the cached `User` keeps saying `admin` after the server has stopped agreeing. The screen words `403 administrator_required` as an ordinary failure and offers a retry of a request that can only be refused again. This is DW-68's shape on a second surface — that entry is the same gap for `403 password_change_required` on Account Settings — and the fix belongs with whatever teaches `apiRequest`'s observer about a role refusal, not with this screen.
status: open

### DW-89: Account Settings always returns to the home panel, so an Administrator who opens it from the user list is put somewhere they did not come from.
origin: spec-deferred 7aac51a28737
location: apps/web/src/App.tsx
source_spec: `spec-1-9-view-user-list.md`
severity: low
reason: `App.tsx` passes `onBack={() => showSection('home')}` to `AccountSettingsScreen` from every branch, and the app bar's Account control is rendered on the admin surfaces too. It predates this story — the same round trip from Create user has landed on the home panel since Story 1.8 — and it is more visible now that the list is a surface people stand on. Fixing it means remembering where the section was opened from, which is state the gate does not keep yet.
status: open

### DW-90: The Administrator floor counts Administrator rows nobody can currently sign in as, so the last *usable* Administrator can still be demoted.
origin: spec-deferred 2b24761e9f4e
location: apps/api/api/users.py (_UPDATE_USER, the floor predicate)
source_spec: `spec-1-10-edit-user.md`
severity: medium
reason: `_UPDATE_USER`'s predicate is `other.role = 'admin' AND other.active`. It ignores `must_change_password` / `temp_credential_expires_at`, and `api/auth.py` refuses a login whose temporary credential has lapsed (a NULL expiry counts as lapsed, DW-44), so an active `admin` row holding an unclaimed, expired credential satisfies the floor while being unusable by anyone. A locked-out Administrator is the same hole with a 15-minute lifetime, and this epic ships no unlock. Widening the predicate here would make it a different rule from the one Story 1.11 states for deactivate and delete, and 1.11 is meant to reuse this predicate — so the two must be decided together, by whoever owns that clause.
status: open

### DW-91: Correcting a mistyped address onto an address that already carries a live lockout hands that lock to the account, with nothing anywhere to end it.
origin: spec-deferred 15520af38f79
location: apps/api/api/throttle.py (carry_failures)
source_spec: `spec-1-10-edit-user.md`
severity: medium
reason: `_CARRY_FAILURES` merges with `GREATEST`, which is the conservative direction for the rename-evasion case DW-59 is about, and the new mirror keeps `users.locked_until` honest about it. The cost runs the other way: an address guessed at while it belonged to nobody carries a run, and an Administrator correcting a typo onto it locks the account for `LOCKOUT_DURATION`. There is no unlock in Epic 1 (DW-64), so the whole of the recovery is waiting 15 minutes — which sits awkwardly beside README's new claim that a mistyped address is no longer a dead end. Closing it means either an unlock surface or a rule that a carry never imports a run the account did not make, and both are product decisions.
status: open

### DW-92: A 403 on save leaves an Administrator demoted mid-edit sitting on an editor they can no longer use, until something else revalidates the session.
origin: spec-deferred e5ce4b975642
location: apps/web/src/screens/EditUserScreen.tsx
source_spec: `spec-1-10-edit-user.md`
severity: medium
reason: `fieldFor` returns `null` for `administrator_required` and the screen renders the server's sentence, but nothing revalidates the session or leaves the screen, so every subsequent Save fails the same way until the tab is backgrounded and brought back (the only thing that triggers `SessionProvider`'s revalidation). This is the same shape as Story 1.9's deferred "Try again forever" finding on `UserListScreen`, and the fix is the same one: a shared answer to "the server says you are no longer an Administrator" that neither screen currently has.
status: open

### DW-93: The unsaved-changes warning guards only the screen's own Back control; every other way off the screen still discards a half-typed edit silently.
origin: spec-deferred 7477bdcdac88
location: apps/web/src/App.tsx (showSection) and screens/EditUserScreen.tsx
source_spec: `spec-1-10-edit-user.md`
severity: low
reason: `handleBack` warns, but `App.showSection` clears `editing` unconditionally, so the app bar's Account control, Sign out and the role reconciler's demotion drop all leave without a word, and there is no `beforeunload` handler for a closed tab. EXPERIENCE.md line 90 asks for the general rule — never silently drop an in-progress admin form — and DW-81 records that the convention the product does not have lands on every admin form. This story built the narrow guard; the general one is still owed, and it belongs with whichever story introduces the second admin form.
status: open

### DW-94: A demotion body sent against an id that names no row still locks every active Administrator row for the life of the transaction.
origin: spec-deferred da50389df385
location: apps/api/api/users.py (edit_user, the lock ordering)
source_spec: `spec-1-10-edit-user.md`
severity: low
reason: `_LOCK_ACTIVE_ADMINISTRATORS` is issued whenever the requested role is `staff`, ahead of `_SELECT_USER_FOR_UPDATE`, so a loop of `PATCH {"role": "staff"}` at a bogus id serialises every user edit in the product while writing nothing — and this endpoint carries no throttle (DW-40/DW-69). The caller must already be an Administrator, which bounds the damage. The obvious fix, reading the row first, is what the lock ordering was chosen to avoid: locking the target before the Administrator set is the deadlock cycle two concurrent demotions would take. Closing it safely means a non-locking pre-read whose answer the `UPDATE` predicate still overrules, which is a trade-off worth making deliberately rather than as a review patch.
status: open

### DW-95: A refusal raised by request-model validation carries no `cache-control`, on this endpoint and on every other one in the product.
origin: spec-deferred 462b8909a7e3
location: apps/api/api/main.py (validation_error_handler)
source_spec: `spec-1-10-edit-user.md`
severity: low
reason: `api/main.py`'s `validation_error_handler` builds its own response and sets no headers, so every `422 validation_error` — the empty body, the explicit null, the unknown field, the malformed UUID — answers without `no-store` while every other answer this handler produces carries it. `test_every_answer_this_handler_produces_carries_no_store` says so in its own comment and excludes those rows. The bodies carry no account data, so nothing sensitive is cacheable today; the hole is that the rule "every authenticated response is `no-store`" has an exception nothing states outside one test comment. Fixing it is a change to the shared handler and therefore to every endpoint at once, which is not this story's to make.
status: open

### DW-96: The refusal sentences a screen renders are pinned in TypeScript literals, so the two languages can drift on wording without a test noticing.
origin: spec-deferred 1a876124fec7
location: apps/web/src/__tests__ (edit-user, create-user, error-code-parity)
source_spec: `spec-1-10-edit-user.md`
severity: low
reason: `error-code-parity.test.ts` compares the envelope *codes* and the numeric bounds across the boundary, which is what the story's Always clause asks for. The *sentences* are different: `edit-user.test.tsx` asserts against hand-copied copies of `NOT_AN_ADDRESS`, `ALREADY_IN_USE`, `NO_SUCH_USER` and `LAST_ACTIVE_ADMINISTRATOR`, and says so in its own docstring. The same is already true of `create-user.test.tsx`, so this predates the story and is a property of how every screen in the product is tested; a rule change here belongs with whatever first needs the wording pinned.
status: open

### DW-97: The parameterized-SQL guard inspects one line at a time, so no multi-line f-string statement in the product has ever been looked at.
origin: spec-deferred 8ab260a11ad4
location: apps/api/tests/test_source_guards.py (INTERPOLATED_SQL)
source_spec: `spec-1-10-edit-user.md`
severity: medium
reason: `INTERPOLATED_SQL`'s first pattern is `f["'].*\bVERB\b[^"']*\{` matched per line, so it only fires where the `f"` opener, a SQL verb and a substitution all sit on one line. Every SQL constant in `api/throttle.py` is a triple-quoted f-string whose opener line is bare, so `_SELECT_ATTEMPTS` and `_RECORD_FAILURE` were already invisible to it at this story's baseline and `_CARRY_FAILURES` joins them. Nothing is injectable today — every interpolated name is a module-level constant, and `_RUN_ENDED`'s own comment says so — but AGENTS.md Policy's parameterized-SQL line is held by this guard, and the guard cannot see the shape the product actually uses. Closing it means teaching the check to read a statement rather than a line, in `tests/test_source_guards.py` — one of the six files this spec's Verification pins as unmodified, and a change that re-scores every module at once.
status: open

### DW-98: A throttle test still describes the Story 1.10 unlock in the future tense, in a file this story may not modify.
origin: spec-deferred 66095f9eca72
location: apps/api/tests/test_login_throttling.py:689
source_spec: `spec-1-10-edit-user.md`
severity: low
reason: `apps/api/tests/test_login_throttling.py:689` reasons that "the way that gets noticed for real is Story 1.10 growing an 'unlock' that clears the mirror". Story 1.10 has now shipped without one, and every other copy of that prediction — `throttle.py`, `auth.py`, `README.md`, and `infra/README.md` this pass — was corrected. This one was not, because this spec's Verification pins that file as unmodified precisely to prove the story changed no existing throttle behaviour. Correcting a docstring there is safe but breaks a stated verification, so it is a call for whoever next has reason to open the file.
status: open
