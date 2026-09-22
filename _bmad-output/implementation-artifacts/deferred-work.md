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
resolution: `spec-1-12-immutable-audit-log-write-path.md`. `apps/api/api/audit.py` owns the only INSERT against `audit_log`, and `create_user` writes a `user_provisioned` entry naming the Administrator, the account created and the source address. Its bare autocommit INSERT gained an explicit `with conn.transaction():` so the row and its entry land together or neither does — proved by `test_audit_immutability.py`'s atomicity case, which revokes the INSERT grant and asserts no `users` row is written. A refused provisioning (409, 403) writes nothing.
status: resolved

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

### DW-99: `session-expiry.test.tsx` fails about one run in five, independently of this story, by reading the DOM before the 401-to-signed-out render lands.
origin: spec-deferred 12e0997b8f02
location: apps/web/src/__tests__/session-expiry.test.tsx
source_spec: `spec-1-11-deactivate-or-delete-user.md`
severity: medium
reason: Measured, not inferred. With this story's new test file removed from `src/__tests__` the web suite still failed 4 of 20 runs, always inside `session-expiry.test.tsx`; with it present the rate was 1 of 20. The file is byte-identical to `831b9527`, as are `SessionProvider.tsx`, `client.ts` and `App.tsx`. The failure is a synchronous `getByText` for `/your session has ended/i` returning while the app bar is still mounted. The fix is a suite-level decision — a shared `configure({ asyncUtilTimeout })`, or awaiting the transition in that file — and touching it from this story would edit a file this spec's Verification pins as unmodified.
status: open

### DW-100: The product's first modal leaves the page behind it in the accessibility tree and scrollable, with `aria-modal` as the only signal.
origin: spec-deferred 7ed8fec5d25a
location: apps/web/src/components/ConfirmDialog.tsx
source_spec: `spec-1-11-deactivate-or-delete-user.md`
severity: medium
reason: `ConfirmDialog` sets `aria-modal="true"` and paints a scrim, but nothing marks the screen root `inert` or `aria-hidden`, and nothing locks body scroll. Assistive technology that ignores `aria-modal` can still reach the user table underneath, and a wheel or touch gesture still scrolls the page under the scrim. Neither EXPERIENCE.md nor DESIGN.md asks for either, so this is the point at which the product should decide its modal convention rather than a defect in this story's clauses.
status: open

### DW-101: Reactivating an account whose temporary credential already lapsed shows it as Active while nobody can sign in as it.
origin: spec-deferred f7bafd8b90a7
location: apps/api/api/users.py (activate_user)
source_spec: `spec-1-11-deactivate-or-delete-user.md`
severity: medium
reason: `POST /admin/users/{user_id}/activate` writes `active = true` and touches neither `must_change_password` nor `temp_credential_expires_at`, by design — a reactivation is not a credential reissue. But `api/auth.py` refuses a login whose temporary credential has lapsed (DW-44), so an unclaimed account deactivated past its 72 hours and then reactivated reads Active on Story 1.9's list and is unusable. The route that would fix it is the credential reissue DW-87 says no story in Epic 1 owns.
status: open

### DW-102: A destructive write that succeeds and is then followed by a failing list refetch replaces the whole table with a load error and never reports the success.
origin: spec-deferred 6b7ce1638a16
location: apps/web/src/screens/UserListScreen.tsx (run, load)
source_spec: `spec-1-11-deactivate-or-delete-user.md`
severity: low
reason: `run()` calls `load()` after the write commits. If that refetch fails, `load`'s catch sets `listing` to `{ kind: 'failed' }`, so the Administrator sees a page-level error where a deactivation or a delete has in fact happened, with nothing saying so. Keeping the table and showing the refetch failure as a banner would separate "the write failed" from "the re-read failed"; the two are one message today.
status: open

### DW-103: After a deactivation the row-end control keeps focus while its accessible name and its action flip from Deactivate to Activate.
origin: spec-deferred 86d2a20a8047
location: apps/web/src/screens/UserListScreen.tsx (the row-end slot)
source_spec: `spec-1-11-deactivate-or-delete-user.md`
severity: low
reason: `ConfirmDialog`'s unmount restores focus to the opener when it is still connected. The row-end button carries no `key`, so React patches the same DOM node, and the control the keyboard Administrator is returned to now reads "Activate Kasun Perera" and performs the inverse verb. Restoring focus to that position is the right behaviour; what is missing is anything announcing that the control under it changed.
status: open

### DW-104: The row's Edit control is not covered by the in-flight guard, so an Administrator can navigate off the list while a destructive request is open.
origin: spec-deferred 39d24083eac4
location: apps/web/src/screens/UserListScreen.tsx (the row-end slot)
source_spec: `spec-1-11-deactivate-or-delete-user.md`
severity: low
reason: `press()` refuses a second destructive verb while `pending !== null`, and since the patch pass every row's destructive controls are disabled for the duration. `Edit` calls `onEditUser(user)` directly and is not disabled, so it still leaves the screen mid-request — abandoning the dialog and the pending state, and landing the Administrator on an editor for a row that may be about to disappear.
status: open

### DW-105: `--z-modal`'s documented relationship to the skip link's stacking level is asserted by nothing.
origin: spec-deferred 0eb3d1ba8fd9
location: apps/web/src/styles/tokens.css
source_spec: `spec-1-11-deactivate-or-delete-user.md`
severity: low
reason: The token's comment in `tokens.css` says it sits "above AppShell's skip link (z-index 1) with room left between them", and `styling-wiring.test.ts` checks only that `.scrim` references the token. If the skip link's level is ever raised the scrim quietly stops covering the chrome, which is the exact failure the comment calls out.
status: open

### DW-106: The confirmation dialog says nothing while a destructive write is in flight, and nothing at all once it lands.
origin: spec-deferred 4d9648b1a889
location: apps/web/src/components/ConfirmDialog.tsx
source_spec: `spec-1-11-deactivate-or-delete-user.md`
severity: medium
reason: While `busy`, `ConfirmDialog` disables both controls, parks focus on a panel whose only text is the unchanged question, and carries no `role="status"`. Between pressing Delete and the row disappearing a screen-reader Administrator gets silence. The success side is the same: the badge flips to Deactivated, or the row goes, with no live-region sentence saying so — only the refusal path is announced. This is the product's first modal and neither EXPERIENCE.md nor DESIGN.md states a pending/confirmed announcement convention, so it belongs with the other open modal-convention question (inert, scroll lock) rather than being invented here.
status: open

### DW-107: Activate is the one verb whose control is disabled mid-flight with no dialog to restore focus from, so a keyboard Administrator is dropped to `<body>`.
origin: spec-deferred 92c450a3d7d6
location: apps/web/src/screens/UserListScreen.tsx (press, run)
source_spec: `spec-1-11-deactivate-or-delete-user.md`
severity: low
reason: `press('activate', …)` goes straight to `run()` — no dialog — and `run()` freezes every row's controls for the duration. Disabling the focused button moves focus to `<body>`, and there is no unmounting dialog whose cleanup would put it back: `rescueFocus` is set for `delete` only. The keyboard Administrator resumes at the top of the document. The fix is the same decision as the already-deferred "the control's name and verb flip under the returned focus" item — where focus belongs after a row verb rewrites its own row-end control — and the two should be settled together.
status: open

### DW-108: A `404` refusal tells the Administrator to reload the list, and closing it leaves the same stale list on screen with no way to do that.
origin: spec-deferred 432e985845a2
location: apps/web/src/screens/UserListScreen.tsx (run, the dialog's onClose)
source_spec: `spec-1-11-deactivate-or-delete-user.md`
severity: low
reason: `NO_SUCH_USER` is "That user no longer exists. Reload the list." `run()`'s catch renders it in the dialog and never refetches, and the dialog's `onClose` only clears the dialog — so the row somebody else already removed is still there, still carrying three live controls. The one-line fix is a `load()` on the failure path, but that widens the already-logged "a destructive write followed by a failing list refetch replaces the whole table with a load error" item: every extra `load()` is another place that can blank the table. The two are one decision about what a failed refetch is allowed to do to the screen, and should be settled together rather than one being patched under the other.
status: open

### DW-109: Delete-and-recreate inherits the address's lockout while the new row reads unlocked, so the list says one thing and `POST /auth/login` says another.
origin: spec-deferred 684bcf700d47
location: apps/web/src/screens/UserListScreen.tsx (lockNotice) / apps/api/api/throttle.py
source_spec: `spec-1-11-deactivate-or-delete-user.md`
severity: medium
reason: `login_attempts` is keyed on the submitted address and deliberately not a foreign key to `users`, so a delete leaves it behind — which is the point (DW-59: delete-and-recreate must not become the unlock this product chose not to build). The consequence only became reachable with this story: the recreated row carries `locked_until: null` and Story 1.9's list renders no lock notice, while `apps/api/tests/test_delete_user.py`'s own `test_a_recreated_account_cannot_sign_in_under_the_lock_that_was_never_cleared` drives the correct credential through `POST /auth/login` and gets `429`. The Administrator's only remedy is to wait out a lock the screen says does not exist. Surfacing it means either rendering the address's lock on a row it is not keyed to, or building the admin unlock DW-64 says no story owns — both product decisions, not handler ones.
status: open

### DW-110: "+ Add user" and "Back" stay live while an `activate` request is open — the one verb with no dialog covering them.
origin: spec-deferred b441483c7e69
location: apps/web/src/screens/UserListScreen.tsx (the actions block)
source_spec: `spec-1-11-deactivate-or-delete-user.md`
severity: low
reason: `frozen = pending !== null` freezes every row's controls, and for a confirmed verb the scrim covers the rest of the screen anyway. `activate` fires from one press with no dialog, so during its request the two screen controls above the table are still pressable: leaving the screen there unmounts it mid-write, and the answer — including a refusal — is never shown. The write itself still commits. Disabling them is one attribute each, but it is the first time this product would disable a navigation control for a request that is not about navigation, which is a convention decision rather than a fix.
status: open

### DW-111: `rocell_app` is adopted over the owner's `DATABASE_URL` rather than being a login role with a credential of its own, so a compromise of the application's connection string still hands over the table owner.
origin: spec-deferred 1.12-audit-write-path
location: apps/api/api/db.py (APPLICATION_ROLE, CONNECTION_OPTIONS) / infra/migrations/20260921T1000_create_audit_log.up.sql
source_spec: `spec-1-12-immutable-audit-log-write-path.md`
severity: medium
reason: AD-4's literal reading is a second login role with its own secret in its own DSN. That was not shipped because hosting, CI/CD and secrets management are all Deferred in the architecture spine and AGENTS.md Policy forbids a committed credential — a second DSN today would mean inventing a deployment contract this story had no authority to invent. What is shipped gives the same grant model: the role is created NOLOGIN (adoption through libpq's `options=-c role=rocell_app` needs membership, not the ability to log in — proved by `test_audit_immutability.py` running the product's own pool against it) and with no password, so the cluster gains no new login principal. `-c role=` is a startup GUC, so `RESET ROLE` returns to `rocell_app` rather than to the owner. The residual gap is that the connection *authenticates* as the owner: anyone holding `DATABASE_URL` can open a session that is not role-switched and do anything, and a `SET ROLE <owner>` from inside the application would climb out (forbidden by a source guard in `tests/test_source_guards.py`, which is code discipline rather than a grant). Closing it means `ALTER ROLE rocell_app LOGIN PASSWORD '...'` at deployment time, putting that password in whichever secret store the deployment picks, and pointing `DATABASE_URL` at it — a decision that belongs with the hosting choice, not with this story. Two operational facts go with it: the migrating role now needs CREATEROLE (documented in `infra/README.md`, the root `README.md` and `make help`), and both the role and the owner's membership in it are cluster-scoped, so the `.down.sql`'s `REVOKE rocell_app FROM <owner>` reaches every database on the server — the "roll the application back first" rule means *every* application on that cluster.
status: open

### DW-112: `audit_log.created_at` defaults to `now()`, the transaction timestamp, so the two entries one request writes are indistinguishable in time and there is no total order to page through but `(created_at, id)` with a random `id`.
origin: spec-deferred 1.12-audit-write-path
location: infra/migrations/20260921T1000_create_audit_log.up.sql (created_at) / apps/api/tests/conftest.py (_audit_rows)
source_spec: `spec-1-12-immutable-audit-log-write-path.md`
severity: low
reason: `POST /auth/password` and `POST /auth/password/change` each write two entries inside one transaction — the password write and the revocation it performed — and both carry the same `created_at` to the microsecond, because `now()` is the transaction's start. The tiebreaker in the index is `id`, a `gen_random_uuid()`, so the order between them is arbitrary and stable rather than chronological. Nothing in this story depends on it: the tests select entries by `action`, and both entries describe the same instant honestly. It matters to Story 1.13, which pages the log: a keyset page on `(created_at, id)` is correct and complete, but "the claim came before the revocation" is not something the data can say. The fixes are a `clock_timestamp()` default (loses "one transaction, one instant", which is the property that makes two entries obviously atomic) or a monotonic sequence column (a schema addition this story's spec did not authorise). Settle it with 1.13, which is the first reader that has an opinion.
status: open

### DW-113: A refused admin write and a refused authenticated request leave no trace at all, so a Staff caller probing `/admin/users` or an Administrator repeatedly hitting the last-Administrator floor is invisible.
origin: spec-deferred 1.12-audit-write-path
location: apps/api/api/users.py (all five handlers) / apps/api/api/dependencies.py (require_administrator)
source_spec: `spec-1-12-immutable-audit-log-write-path.md`
severity: low
reason: The story's I/O matrix is explicit that a 403, 404 or 409 writes no row — "nothing was written, so there is nothing to record" — and that is right for a log whose job is attributing *changes*: an entry for an attempt cannot be told from an entry for a change by anything downstream. The login half does record refusals, because there the attempt is the event. The gap is the middle case: a signed-in Staff account walking the admin routes is an authorization probe, and it is exactly the anomaly FR-22 will want, yet `require_administrator` refuses before any handler is entered and nothing counts it. Recording it means either a second action class ("refused") with a rule about which refusals qualify, or FR-22's own counter — both product decisions, and DW-55's per-source-IP counter is the same question from the other side.
status: open

### DW-114: The audit log has no retention, partitioning or archival path, and the malformed-address login branch appends a row per request from an unauthenticated caller the throttle cannot count.
origin: spec-deferred 0d81423d0cba
location: apps/api/api/audit.py, apps/api/api/auth.py (login)
source_spec: `spec-1-12-immutable-audit-log-write-path.md`
severity: medium
reason: AD-4's grant model denies the application role DELETE, so no principal in the product can prune the table - `api/audit.py` states this as a virtue. The malformed-address path in `login` previously touched no database at all; it now takes a pool connection and writes an entry, and it is deliberately uncounted because the address carries a NUL and cannot be a `login_attempts` key. An attacker appending a control character to every guess therefore grows an unprunable table at request rate. Nothing (partitioning, an owner-run archival runbook, a volume alert in `infra/README.md`) answers what happens when it fills the disk.
status: open

### DW-115: There is no erasure path for the personal data the log now keeps permanently.
origin: spec-deferred 12984da52175
location: n/a
source_spec: `spec-1-12-immutable-audit-log-write-path.md`
severity: medium
reason: `details.changed` records name and email before/after values, `user_deleted` records the deleted account's address, and `target_email` survives a hard delete by design (AD-10). Combined with "no update or delete path at any level", a departed staff member's name and address become unremovable. The delete route's docstring presents this as the point of the snapshot rule without noting it is also a data-protection commitment nobody has signed off.
status: open

### DW-116: ARCHITECTURE-SPINE.md AD-4 is now narrower than the shipped design in two places, and was not amended.
origin: spec-deferred de5a21471d6c
location: _bmad-output/planning-artifacts/architecture/architecture-rcl_camera_app-2026-08-30/ARCHITECTURE-SPINE.md
source_spec: `spec-1-12-immutable-audit-log-write-path.md`
severity: medium
reason: AD-4 reads "`source_ip` is read only from the trusted reverse-proxy's forwarded-IP header"; the implementation reads the non-forgeable TCP peer when no header is configured. AD-4 also reads "the application's database role"; the implementation adopts `rocell_app` over the owner's DSN at connection startup rather than authenticating as it (DW-111). Both choices are argued at length in `api/audit.py` and `api/db.py`, but the next person implementing against AD-4 reads the unamended rule. Amending a planning artifact is an architect's call, not an unattended build's.
status: open

### DW-117: The seeded Administrator and `make reseed-admin` are user changes that still write no audit entry, and the middle path the architecture review suggests was not weighed.
origin: spec-deferred fe94c0f05ec2
location: infra/rocell_infra/seed.py
source_spec: `spec-1-12-immutable-audit-log-write-path.md`
severity: medium
reason: `infra/README.md`'s "Not audited, and not an oversight" section argues that inventing an actor is worse than a gap. The UX/architecture review rubric proposes, for the structurally identical `scripts/ingest` case, an entry "attributed to an operator/service USER row, with `source_ip` null or a documented sentinel for offline runs". That option - a NULL actor with `details.source = "cli"` - is never considered, and AGENTS.md:17 requires the log to cover user changes without exempting console ones.
status: open

### DW-118: Nothing asserts the universal "every mutating route writes an entry" at the surface where it could regress.
origin: spec-deferred 9ff26e8d194e
location: apps/api/tests
source_spec: `spec-1-12-immutable-audit-log-write-path.md`
severity: medium
reason: Coverage is per-handler HTTP tests plus one sweep over `api/users.py`'s five routes. The new source guards catch a *second* writer of the table, never an *omitted* one, so a route added in Epic 2 or 3 that forgets its entry fails nothing. The three existing route-table walkers (`test_admin_authorization.py`, `test_forced_change_gate.py`, `test_no_registration.py`) are the precedent for the missing test: walk `create_app()`'s table and require every mutating route to be either on a written allowlist or observed writing an entry.
status: open

### DW-119: `login_failed` records the targeted account in `actor_user_id` while `login_refused_locked`, written for the same unauthenticated caller, leaves the actor NULL.
origin: spec-deferred 78694ab865e0
location: apps/api/api/auth.py (_count_and_refuse)
source_spec: `spec-1-12-immutable-audit-log-write-path.md`
severity: low
reason: `_count_and_refuse` passes `actor_id=user_id` - the account being guessed at, not whoever made the request, whose identity was never proven. The matrix in this spec's frozen intent-contract prescribes exactly that, and no information is lost because `target_user_id` carries the same value, but the two unauthenticated events now disagree about what the actor column means. Story 1.13 renders one of these as "who did it" and must settle it.
status: open

### DW-120: A failed login snapshots the Python-folded address while a successful one snapshots the column Postgres stored, so two entries about one account can carry different addresses.
origin: spec-deferred 1236fb39c57a
location: apps/api/api/auth.py (_count_and_refuse)
source_spec: `spec-1-12-immutable-audit-log-write-path.md`
severity: low
reason: `_count_and_refuse` writes `actor_email`/`target_email` from `email_key` (Python `strip().lower()`); `_authenticate`'s success path writes `user_row["email"]`. `api/users.py` already documents at length, for `_INSERT_USER` and `edit_user`, that the Python fold and Postgres's `lower()` are not guaranteed to agree on non-ASCII addresses. The failure path knows the row whenever `user_id` is not None and could use the stored value there.
status: open

### DW-121: `source_ip` is stored as `text` where `inet` would make the validation a database property.
origin: spec-deferred 580000ab516b
location: infra/migrations/20260921T1000_create_audit_log.up.sql
source_spec: `spec-1-12-immutable-audit-log-write-path.md`
severity: low
reason: The column holds an `ipaddress.ip_address()`-validated string. `inet` would enforce that in the same place the grants are enforced (the migration's own argument for preferring the database over code discipline), normalize `::1` against its expanded form, and hand FR-22's anomaly work containment and CIDR operators. The cost is that psycopg3 returns `ipaddress` objects for `inet`, so every assertion comparing to a string would change - which is why it was not done under review.
status: open

### DW-122: The trusted-header reader assumes exactly one trusted hop; behind two proxies it records the inner proxy's address as the user's.
origin: spec-deferred a214946a1a50
location: apps/api/api/audit.py (source_ip)
source_spec: `spec-1-12-immutable-audit-log-write-path.md`
severity: low
reason: `source_ip` takes the last element of the last header line - correct for one trusted hop. With `client, real-client, edge1` the recorded value is the inner proxy's: a plausible but wrong address, which is the outcome the function's own docstring says the design exists to avoid. A configurable hop count would settle it; nothing in the README's "whatever your edge layer uses" guidance distinguishes the case.
status: open

### DW-123: `TRUSTED_PROXY_HEADER` is read per request with no startup validation, so a typo records NULL for the life of a deployment with nothing surfacing it.
origin: spec-deferred 9e67de298f6a
location: apps/api/api/audit.py
source_spec: `spec-1-12-immutable-audit-log-write-path.md`
severity: low
reason: Every other configuration value in this service is resolved once at startup and fails loudly (`database_url` refuses to default). A misspelt header name instead produces a silently empty column - the precise failure the root README warns about in bold. Reading it per request is what lets tests monkeypatch it, so the fix is a startup check rather than a different read.
status: open

### DW-124: An `options` parameter already present in `DATABASE_URL` is silently overridden by the pool's `kwargs`.
origin: spec-deferred 4825315b7e01
location: apps/api/api/db.py (create_pool)
source_spec: `spec-1-12-immutable-audit-log-write-path.md`
severity: low
reason: `create_pool` passes `"options": CONNECTION_OPTIONS` in `kwargs`, which libpq resolves after the connection string, so an operator who set `?options=-c statement_timeout=5s` loses it without warning. Merging the two (`conninfo_to_dict(url).get("options")` plus the role) would preserve both. No operator sets one today.
status: open

### DW-125: A sign-in that spends the cookie it arrived with deletes that session and writes no `sessions_revoked` entry.
origin: spec-deferred ff0212a6d23b
location: apps/api/api/auth.py (_authenticate)
source_spec: `spec-1-12-immutable-audit-log-write-path.md`
severity: low
reason: `_authenticate` calls `delete_session(conn, rocell_session)` before issuing the new one, so a session the log claims to cover ends with only the `login_succeeded` row to show for it. Every other revocation in this story - both password writes, the expired-credential path, a deactivation - records one. Consistency, not loss: the event is inferable from the login entry.
status: open

### DW-126: `details` is an untyped `dict[str, Any]` whose key vocabulary lives in `api/auth.py` and `api/users.py` rather than in the module that owns the log.
origin: spec-deferred f698542dfb54
location: apps/api/api/audit.py
source_spec: `spec-1-12-immutable-audit-log-write-path.md`
severity: low
reason: `api/audit.py` describes `AuditAction` as the log's whole vocabulary, but the `REASON_*` and `CAUSE_*` constants are plain module constants in `api/auth.py`, and the keys a reader must know (`reason`, `cause`, `count`, `changed`, `locked_until`, `sessions_revoked`) are declared nowhere in one place. Story 1.13's renderer has to import refusal reasons from the auth module and guess at the rest.
status: open

### DW-127: `GRANT rocell_app TO current_user` is unguarded in the shared-cluster case the surrounding `DO` block is written for.
origin: spec-deferred ba8d6e01ada1
location: infra/migrations/20260921T1000_create_audit_log.up.sql
source_spec: `spec-1-12-immutable-audit-log-write-path.md`
severity: low
reason: The `CREATE ROLE` catches `duplicate_object` because a second database in the same cluster may already hold the role - but if that database was migrated by a different owner, the unguarded `GRANT` then fails for want of ADMIN OPTION on a role this user did not create. Failing loudly is arguably right (the application cannot adopt a role it is not a member of), which is why it was not patched; the comment block argues the first half of the scenario and misses the second.
status: open

### DW-128: CLAUDE.md still describes `make migrate`'s environment contract as `DATABASE_URL` plus `SEED_ADMIN_*`, which is now incomplete.
origin: spec-deferred 629a1a7b3a74
location: CLAUDE.md
source_spec: `spec-1-12-immutable-audit-log-write-path.md`
severity: low
reason: The migration added in this story creates a database role, so the migrating role needs CREATEROLE or superuser. That prerequisite was documented in the migration header, `infra/README.md`, `README.md`, the Makefile and `make help`, but CLAUDE.md's Commands table was left alone deliberately: it is the project's own instruction file, not product documentation, and editing it is the user's call rather than an unattended run's.
status: open

### DW-129: Nothing verifies at startup that the pool's `-c role=rocell_app` was actually adopted, so a missing role or membership surfaces as a hang rather than a named failure.
origin: spec-deferred 66504778599f
location: apps/api/api/db.py (create_pool), apps/api/api/main.py (lifespan)
source_spec: `spec-1-12-immutable-audit-log-write-path.md`
severity: medium
reason: `create_pool` calls `pool.open(wait=False)`, so a DSN whose role is not a member of `rocell_app` is refused by libpq at connect time and every request instead dies on the 10-second `POOL_TIMEOUT_SECONDS` acquisition failure. That is the most likely new deployment failure this story introduces, and `api/db.py`'s own precedent is the opposite: it refuses to default `DATABASE_URL` and fails loudly. A probe in `lifespan` would settle it; the spec's Code Map pins `lifespan` as unchanged, so this was not done under review.
status: open

### DW-130: An active lockout appends a `login_refused_locked` row per request from an unauthenticated caller, with no counter and no bound.
origin: spec-deferred 9348c20d6c7b
location: apps/api/api/auth.py (login, the two lockout gates)
source_spec: `spec-1-12-immutable-audit-log-write-path.md`
severity: medium
reason: The intent-contract matrix prescribes exactly this ("Attempt during an active lockout ... One `login_refused_locked` row; no counter write"), so it is not a deviation - but it is a second unbounded-growth path beside the malformed-address branch already recorded above, and it needs no malformed input to reach. Once an address is locked, every further guess is a free append to a table no principal in the product may prune. Coalescing repeats within the lock window, or counting refusals, would settle it; either is an intent-level change.
status: open

### DW-131: `user_deleted` records no session count, while the less destructive `user_deactivated` does.
origin: spec-deferred 58a0afd84af2
location: apps/api/api/users.py (delete_user)
source_spec: `spec-1-12-immutable-audit-log-write-path.md`
severity: low
reason: `deactivate_user` calls `delete_sessions_for_user` and writes `details.sessions_revoked`; `delete_user` relies on the `ON DELETE CASCADE` at `users.py` and records nothing, so "how many devices did this delete sign out" is unrecoverable the moment the row is gone - which is the class of fact AD-10's snapshot rule exists to preserve. The matrix does not require it, which is why it was not patched.
status: open

### DW-132: Session revocation is encoded two incompatible ways, so Story 1.13 must union two shapes to answer one question.
origin: spec-deferred 9535bad30ba9
location: apps/api/api/audit.py, apps/api/api/users.py (deactivate_user)
source_spec: `spec-1-12-immutable-audit-log-write-path.md`
severity: low
reason: The two password paths write a separate `sessions_revoked` row carrying `details.count`; a deactivation instead writes `details.sessions_revoked` on the `user_deactivated` row. Both follow the matrix, which prescribes the first and is silent on the second. Neither key is declared in `api/audit.py`, the module that describes `AuditAction` as the log's whole vocabulary.
status: open

### DW-133: `login_refused_locked` leaves `target_user_id` NULL even when the locked address names a real account.
origin: spec-deferred 7180ee42fd9a
location: apps/api/api/auth.py (login, the two lockout gates)
source_spec: `spec-1-12-immutable-audit-log-write-path.md`
severity: low
reason: The first lockout gate refuses before any `users` read - that is what makes the refusal cost one indexed lookup - so the row genuinely has no id in hand. The consequence is that a lockout cannot be joined to the account it was against without matching on the email snapshot, which the entry above about the Python fold versus Postgres's `lower()` shows is not always the same string. Distinct from the actor-column disagreement already recorded above, which is about `login_failed`.
status: open

### DW-134: The down migration's `REVOKE rocell_app FROM current_user` does not revoke what its comment says, and is unguarded against a missing ADMIN OPTION.
origin: spec-deferred fd2371362364
location: infra/migrations/20260921T1000_create_audit_log.down.sql
source_spec: `spec-1-12-immutable-audit-log-write-path.md`
severity: low
reason: The header says that after the revert "the owner is no longer one of its members", but the statement names `current_user` - the role running the revert, which need not be the role the `up` granted. A revert run by a second operator silently leaves the original membership behind, and a revert run by an operator without ADMIN OPTION on the role raises. This is the mirror of the hazard already recorded above for the `up`'s unguarded `GRANT`, on the reverse path, and failing loudly is arguably right for the same reason.
status: open

### DW-135: `audit_log_created_at_idx` is the table's only index; the columns an operator and FR-22 will filter on carry none.
origin: spec-deferred 2c1178255e8b
location: infra/migrations/20260921T1000_create_audit_log.up.sql
source_spec: `spec-1-12-immutable-audit-log-write-path.md`
severity: low
reason: The index serves Story 1.13's chronological page. "Everything this Administrator did" filters `actor_user_id`, "everything that happened to this account" filters `target_user_id`, and FR-22's anomaly work filters `action` - all sequential scans today. Because nothing may prune this table, the index is only ever built against a monotonically growing relation, so deferring it gets strictly more expensive. Which indexes the read surface needs is Story 1.13's to decide, which is why this was not added here.
status: open

### DW-136: The two Python AD-4 guards treat prose inconsistently, so the rule can be explained in a `#` comment but not in a docstring.
origin: spec-deferred 88451ff34a05
location: apps/api/tests/test_source_guards.py
source_spec: `spec-1-12-immutable-audit-log-write-path.md`
severity: low
reason: `test_nothing_climbs_back_to_the_table_owner` strips whole-line `#` comments through `_without_comments`; `test_nothing_mutates_the_audit_table` strips nothing, and neither strips docstrings. A future module docstring writing "never `UPDATE audit_log`" or "never `SET ROLE`" therefore fails the build - the "guard somebody argues with rather than obeys" outcome the comments say they exist to avoid. Stripping docstrings needs an AST walk rather than a line filter, which is why it was not patched.
status: open

### DW-137: Address forms a real reverse proxy emits - a bracketed host with a port, an RFC 7239 `for=` element, a zone-suffixed link-local address - all fail `ip_address()` and record NULL.
origin: spec-deferred 43ca9175c2fc
location: apps/api/api/audit.py (source_ip)
source_spec: `spec-1-12-immutable-audit-log-write-path.md`
severity: medium
reason: `source_ip` takes the last comma-separated element and hands it straight to `ipaddress.ip_address()`. An IPv6-aware edge commonly writes `X-Forwarded-For: [2001:db8::1]:443`, `Forwarded: for="[2001:db8::1]"` carries quotes and a `for=` prefix, and `fe80::1%eth0` carries a zone - none parses, so a correctly configured deployment silently logs an empty column for every request. That is the "configured and silently empty" failure the root README warns about in bold, and it is distinct from the unvalidated-header-name entry above: here the header name is right and the value is well formed. Stripping brackets, a port and a `for=` prefix before validating would settle it; which forms to accept is a deployment contract question the README's "whatever your edge layer uses" guidance does not answer.
status: open

### DW-138: Activating an account that is already active writes a `user_activated` entry for a change that did not happen.
origin: spec-deferred c6f87a3fa565
location: apps/api/api/users.py (activate_user, deactivate_user)
source_spec: `spec-1-12-immutable-audit-log-write-path.md`
severity: medium
reason: `activate_user`'s own docstring says "Idempotent on an already-active account: 200, same row, nothing to say", and then records an entry indistinguishable from a real reactivation; `deactivate_user` has the same shape with `sessions_revoked: 0`. `logout` takes the opposite position in this very change - "a row saying otherwise would be the log recording an event that did not happen, which is a worse defect in an audit log than a missing one" - so the two halves of the story disagree. The matrix prescribes an entry for each of the five admin writes that succeeds and a 200 is a success, so resolving it means either dropping an entry the matrix requires or adding a `details` key the docstring argues against: an intent-level call.
status: open

### DW-139: `login_refused_locked` writes an explicit `locked_until: null` where `login_failed` omits the key, so one fact has two encodings in `details`.
origin: spec-deferred 273fd24f5e49
location: apps/api/api/auth.py (login, _count_and_refuse)
source_spec: `spec-1-12-immutable-audit-log-write-path.md`
severity: low
reason: Both lockout gates pass `details={"locked_until": _locked_until_iso(state)}` unconditionally, and that helper returns `None` for a state with no lock; `_count_and_refuse` instead adds the key only when it has a value. A reader of the log therefore cannot tell "no lock" from "not recorded" without knowing which action wrote the row. Distinct from the vocabulary entry above, which is about which keys exist rather than how absence is spelled.
status: open

### DW-140: The `.sql` guards duplicate `test_source_guards.py`'s scanning helpers in a second module, and live under `apps/api` though they only read `infra/migrations`.
origin: spec-deferred 302210d1210a
location: apps/api/tests/test_audit_immutability.py, apps/api/tests/test_source_guards.py
source_spec: `spec-1-12-immutable-audit-log-write-path.md`
severity: low
reason: `_at`, the comment-blanking helper and the mutation regex now exist twice - `test_source_guards.py` (`_without_comments`, whole-line `#`) and `test_audit_immutability.py` (`_statements`, truncate at `--`) - with the same intent and different implementations. A later fix to one (docstring stripping, a new verb, an `ONLY`-qualified table) will not reach the other, which is the failure mode the last two review passes both found in the line-by-line scans. Moving the `.sql` pair to `infra/tests` beside the migrations it reads would also put it where somebody editing a migration looks.
status: open

### DW-141: `api/audit.py`'s headline claim to be the only file naming `audit_log` is false as written, and `api/db.py` stays clean only by accident.
origin: spec-deferred 454d02b4fc40
location: apps/api/api/audit.py
source_spec: `spec-1-12-immutable-audit-log-write-path.md`
severity: low
reason: The migration pair, `conftest.py`, four test modules and both READMEs all name the table; the guard that is cited as enforcing the claim exempts `tests` and reads no `.sql`. `api/db.py` passes only because `create_audit_log` has no word boundary before `audit` - documented at `db.py`, so rewording that comment to "the audit_log migration" would fail the build for no substantive reason. The claim is true of the application's own modules and should say so; tightening the guard to match the sentence instead is the larger change.
status: open

### DW-142: The Flagged filter EXPERIENCE.md places on the audit log is not built, because FR-22's anomaly flagging has no column behind it.
origin: spec-deferred spec-1-13-view-audit-log
location: apps/web/src/screens/AuditLogScreen.tsx
source_spec: `spec-1-13-view-audit-log.md`
severity: low
reason: EXPERIENCE.md:38 describes this surface as "chronological account/catalogue history, with a Flagged filter surfacing FR-22 anomaly reviews", and :76 gives `flagged-activity-row` its own treatment (an audit row plus an accent flag glyph, DESIGN.md:117-121). FR-22 is Epic 3, the `audit_log` table has no flag column, and nothing in the product computes one - so the filter would be a control over a field that does not exist and the row variant would be a style nothing can ever carry. Building either now means inventing a data model for anomaly review ahead of the story that owns it. Re-read this entry when FR-22 lands: the filter is a `WHERE` on the read, which is the one thing the statement deliberately has none of today.
status: open

### DW-143: The audit log offers no search, date range or source-IP filter over a table that only grows.
origin: spec-deferred spec-1-13-view-audit-log
location: apps/api/api/audit.py (read_audit_log), apps/web/src/screens/AuditLogScreen.tsx
source_spec: `spec-1-13-view-audit-log.md`
severity: medium
reason: FR-21 asks for visibility and the acceptance clause is chronological order, so the read is the whole log, newest first, paged. That is answerable today because the log is days old. It grows by a row per sign-in, per failed sign-in and per account change, forever, in a table no principal may prune (AD-4 grants no DELETE) - so "who signed in as Nadeesha on Tuesday" becomes a lot of Load more presses within a year. `api.audit.source_ip` already canonicalises the address specifically so that grouping on it is possible. Adding a filter means adding a `WHERE` to a statement whose current tests assert it has none, and choosing which axes are filterable is a product decision rather than an implementation one.
status: open

### DW-144: The page size is fixed server-side, and the client cannot tell a full last page from the whole log, so Load more costs one empty request.
origin: spec-deferred spec-1-13-view-audit-log
location: apps/api/api/audit.py (PAGE_SIZE), apps/web/src/screens/AuditLogScreen.tsx (Listing.pageSize)
source_spec: `spec-1-13-view-audit-log.md`
severity: low
reason: The response is a bare array, so nothing on the wire says whether more entries exist - the client infers it, taking the first page's length as the page size and stopping when a later page comes back shorter. That is correct and never hides an entry, but it means Load more is offered whenever the newest page was exactly as long as the first: always once for a log smaller than one page, and once at the end of a log whose length is an exact multiple of the page size. The press costs one request that answers `[]`. Closing it means either a shaped success body (`{entries, has_more}`), which would be the only one in the API, or publishing the page size in `shared_schema.audit` so both halves agree on what "short" means. Both are contract changes rather than fixes.
resolution: `spec-1-13-view-audit-log.md`, amended to authorise the second option. `PAGE_SIZE` moved to `shared_schema/audit.py` as part of the contract, mirrored in the twin as `AUDIT_PAGE_SIZE`, and pinned to one value by `shared/schema/tests/test_audit.py`. `apps/api/api/audit.py` imports it and keeps the name, so the statement's `LIMIT` and the handler read as before. `AuditLogScreen` dropped the inferred `pageSize` from its state and counts each page against the published number, so a first page shorter than it - which is every log smaller than one page - renders no Load more control at all. The bare-array response, the keyset cursor and the refusal to accept a caller-supplied `limit` are all unchanged: the client is told the page size, never asked to choose it. What remains is the log whose length is an exact multiple of the page size, where the last press answers `[]`; that is the deliberate cost of not adding a second success-body shape, and `audit-log.test.tsx` covers it explicitly rather than leaving it as an unlogged surprise.
status: resolved

### DW-145: `details` is rendered generically as sorted `key: value` text rather than per action.
origin: spec-deferred spec-1-13-view-audit-log
location: apps/web/src/screens/AuditLogScreen.tsx (detailsText)
source_spec: `spec-1-13-view-audit-log.md`
severity: low
reason: Every entry's payload renders the same way - keys sorted, non-string values JSON-encoded - so a `user_edited` row reads `changed: {"role":{"from":"staff","to":"admin"}}` rather than "Role: Staff to Administrator", and a `sessions_revoked` row reads `revoked: 3`. It is honest, deterministic and never blank, which is what a record needs most; it is not what an Administrator scanning for one change would prefer. A per-action renderer is a second vocabulary to keep in step with `AuditAction`, and the unrecognised-action case has to fall through to this rendering anyway - so the generic path stays whatever is built on top of it. Worth revisiting once Epics 2 and 3 have added their own actions and the payload shapes that matter are known.
status: open

### DW-146: There is no mockup for the audit log, so its render was built from the token rules alone.
origin: spec-deferred spec-1-13-view-audit-log
location: _bmad-output/planning-artifacts/ux-designs/ux-rcl_camera_app-2026-09-08/mockups/
source_spec: `spec-1-13-view-audit-log.md`
severity: low
reason: DESIGN.md ships four rendered mockups - scan, crop, results, user list - and none of them is this screen. `audit-log-row` is specified only as tokens (surface background, hairline border, muted-text foreground, and deliberately no hover key) plus one line of prose calling it "deliberately unremarkable", so the six-column layout, the column order and the width behaviour of the `details` cell were decided here rather than checked against a design. `styling-wiring.test.ts` pins the token-level claims, which is the part that can be pinned; the composition is unreviewed. A second, related question is recorded with it: DESIGN.md:186 scopes the `code` type role to product Codes and flags it as an unconfirmed assumption, so timestamps and IP addresses on this screen use the normal type roles rather than monospace - a design decision this story had no mandate to make either way.
status: open

### DW-147: Reading the audit log is itself a privileged action, and this story makes it possible without recording it.
origin: spec-deferred c998da14b31f
location: apps/api/api/audit.py (read_audit_log)
source_spec: `spec-1-13-view-audit-log.md`
severity: medium
reason: `GET /admin/audit` writes nothing, `AuditAction` has no member for a read, and the module docstring's list of deliberate omissions does not mention it. FR-20 and AGENTS.md:17 enumerate logins, failed logins and account changes, so a read is outside the requirement as written - but "who read the security record, and when" is the one question this surface newly makes askable and cannot answer. Deciding it needs the retention and volume answers that are still deferred in the spine, since an entry per page of every read is a row per press in a table nobody can prune.
status: open

### DW-148: The only way to find an old event is to press Load more through 50-row pages; there is no search, date range or source-IP lookup.
origin: spec-deferred a88c329d70db
location: apps/web/src/screens/AuditLogScreen.tsx, apps/api/api/audit.py
source_spec: `spec-1-13-view-audit-log.md`
severity: medium
reason: The story's own purpose clause is "review access history", and its worked example is a lookup, not a scroll. `source_ip` is already canonicalised in `audit.py` precisely so grouping on it would be possible, and the index is `(created_at DESC, id DESC)`, so a date range is cheap and an address filter is not. Nothing in the acceptance criteria asks for either, so neither was built. Recorded as DW-143.
status: open

### DW-149: The screen never re-reads once loaded, so entries written after the first page are invisible until it is closed and reopened.
origin: spec-deferred ab402b41e41a
location: apps/web/src/screens/AuditLogScreen.tsx
source_spec: `spec-1-13-view-audit-log.md`
severity: low
reason: `Try again` renders only in the failed state and `exhausted` is sticky, so there is no refresh control. An Administrator who acts in another tab, or who leaves the log open, is reading a snapshot with nothing saying so.
status: open

### DW-150: DESIGN.md's prose and its own tokens disagree about the audit row, and nothing records that the implementation had to choose.
origin: spec-deferred a61bc4b23d16
location: _bmad-output/planning-artifacts/ux-designs/ux-rcl_camera_app-2026-09-08/DESIGN.md:212
source_spec: `spec-1-13-view-audit-log.md`
severity: low
reason: DESIGN.md:212 calls the audit row "visually identical to a data table row", while the token block at :112-115 gives `audit-log-row` a `{colors.muted-text}` foreground against `data-table-row`'s `{colors.text}` and omits `background-hover` entirely. The screen followed the tokens, which is the right call, but the prose still says otherwise and the next reader of either will not know the other exists.
status: open

### DW-151: Neither the arrival of the first page nor the appending of a later one is announced to a screen reader.
origin: spec-deferred 02547c50e700
location: apps/web/src/screens/AuditLogScreen.tsx, apps/web/src/screens/UserListScreen.tsx
source_spec: `spec-1-13-view-audit-log.md`
severity: low
reason: The `role="status"` wait line is unmounted and replaced by a freshly mounted table rather than updated in place, and a live region that is replaced is unreliable. Inherited from `UserListScreen`, so it is a shared fix rather than a defect new to this screen - but this screen's whole content is the announcement.
status: open

### DW-152: A `details` payload has no length cap, so one large entry can dominate the table.
origin: spec-deferred a4948b377b86
location: apps/web/src/screens/AuditLogScreen.tsx (detailValue)
source_spec: `spec-1-13-view-audit-log.md`
severity: low
reason: `detailValue` JSON-encodes arbitrary nested values into one cell. `--measure-prose` caps the width but not the length, and Epic 2 and 3 add actions whose payloads nobody has seen yet. DW-145 records that the rendering is generic; it does not record that it is unbounded.
status: open

### DW-153: `created_at` is the transaction timestamp, so an entry can commit with a time a paging walk has already passed.
origin: spec-deferred 03106bb94f4c
location: infra/migrations/20260921T1000_create_audit_log.up.sql:83-111
source_spec: `spec-1-13-view-audit-log.md`
severity: low
reason: `now()` is stamped at transaction start. A write that began before a reader's page and commits after it carries a `created_at` inside a range the reader has already walked, so that walk never shows it. The window is the length of a write transaction - milliseconds here - and the entry is present on any fresh load, so nothing is lost. Closing it properly means `clock_timestamp()` or a monotonic key, which is a change to an applied migration and to Story 1.12's table.
status: open

### DW-154: No mockup exists for this surface, so the column set, their order and the details cell were decided in the implementation and checked against nothing.
origin: spec-deferred 9a1038d81714
location: apps/web/src/screens/AuditLogScreen.tsx
source_spec: `spec-1-13-view-audit-log.md`
severity: low
reason: The UX pair has `mockups/key-user-list.html` and no audit equivalent, and EXPERIENCE.md's state table has no row for this surface at all - no empty, loading or error treatment. `vite.config.ts` sets `css: false` and jsdom performs no layout, so every visual claim is asserted by regex over the stylesheet's text rather than by anything that renders. Recorded as DW-146.
status: open

### DW-155: A `details` value that is not a JSON object fails validation on the read and answers `500`, taking every page that holds the row with it.
origin: spec-deferred aa1473a426e0
location: apps/api/api/audit.py (read_audit_log), infra/migrations/20260921T1000_create_audit_log.up.sql:110
source_spec: `spec-1-13-view-audit-log.md`
severity: medium
reason: The column is `jsonb NOT NULL DEFAULT '{}'` with no CHECK that the value is an object, while `AuditLogEntry.details` is `dict[str, Any]`. The only application writer passes a dict, so this is unreachable through the product - but AD-4's stated way of correcting a wrong entry is an entry inserted by hand as the table owner, which is exactly the path that can store a scalar. One such row then makes a page of the append-only record unreadable with no way to page past it. Whether to coerce on read, add a CHECK in a later migration, or leave the loud failure as the honest answer is a decision this story has no mandate to make.
status: open

### DW-156: The shared `422` envelope carries no `cache-control: no-store`, unlike every other refusal in the API.
origin: spec-deferred a15f0ffd465d
location: apps/api/api/main.py (validation_error_handler)
source_spec: `spec-1-13-view-audit-log.md`
severity: low
reason: `api/main.py`'s `validation_error_handler` calls `_envelope(422, ...)` with no `headers`, while `ApiError` refusals - including this story's own `404` - pass `NO_STORE` and are tested for it. Pre-existing and API-wide rather than anything this story introduced, and the `422` body carries no data, so it is recorded rather than fixed here: changing the shared handler is a cross-cutting edit no single story owns.
status: open

### DW-157: `--color-border` gives the audit row separator 1.24:1 against `--color-surface`, and `--disabled-opacity` puts an aria-disabled control's label at 3.74:1.
origin: spec-deferred 9c12f5042e95
location: apps/web/src/styles/tokens.css
source_spec: `spec-1-13-view-audit-log.md`
severity: low
reason: Raised by the `ui-ux-pro-max` pre-delivery checklist run in the 2026-09-21 review pass, which the screen otherwise passes. Neither is this screen's decision: `{colors.border}` is what DESIGN.md:112-115 prescribes for `audit-log-row` and every other admin surface already uses it, and `--disabled-opacity` is a product-wide token. They fall below the 3:1 non-text and 4.5:1 text thresholds respectively, and both are arguably exempt - a row separator beside text rows is decorative, and WCAG 1.4.3 exempts inactive components. The question is whether the tokens themselves should move, which is a spine decision affecting every screen at once.
status: open

### DW-158: `auth.py` still describes this screen in the future tense now that it exists.
origin: spec-deferred 8b2ea378254f
location: apps/api/api/auth.py:777
source_spec: `spec-1-13-view-audit-log.md`
severity: low
reason: `apps/api/api/auth.py:777` reads "keeps 'every entry names who it was about' true for the read Story 1.13 builds". Every other forecast of this story - in `audit.py`, `test_source_guards.py`, `UserListScreen.tsx`, `EditUserScreen.tsx` and `README.md` - was corrected to the past tense by this story, and this one was not, because `auth.py` is on the intent contract's Never-touch list and a comment-only edit is still an edit to it. Cosmetic, and safe to fold into the next change that opens the file.
status: open

### DW-159: The whole multipart body is spooled to disk before `require_administrator` runs, so an unauthenticated caller can consume disk with an oversized upload.
origin: spec-deferred 9ead5876cf5f
location: apps/api/api/catalogue.py add_tile
source_spec: `spec-2-1-add-product.md`
severity: medium
reason: FastAPI awaits `request.form()` before solving dependencies, so up to MAX_IMAGES_PER_REQUEST x MAX_IMAGE_BYTES is written to the spool file before any authz check. Fixing it needs a body-size limit at the reverse proxy or a Starlette middleware, and this spec's Never list forbids middleware.
status: open

### DW-160: `make test` is green on a machine that has never run `make model`, so AD-1's symmetry assertion and the entire catalogue write path can silently never execute.
origin: spec-deferred 289c9770041d
location: Makefile test target
source_spec: `spec-2-1-add-product.md`
severity: medium
reason: 34 tests are gated on `pipeline.MODEL_PATH.exists()`, including test_the_write_path_and_the_query_path_produce_identical_vectors. Nothing in `make test` depends on the model target or asserts the gated tests ran. There is no CI workflow in the repository (see DW-2), so a developer's `make test` is the only gate.
status: open

### DW-161: The HNSW index is built and maintained on every insert but no statement in the codebase queries through it.
origin: spec-deferred dc1a20866928
location: apps/api/api/catalogue.py _SELECT_CANDIDATES
source_spec: `spec-2-1-add-product.md`
severity: low
reason: `_SELECT_CANDIDATES` is a grouped min() scan over reference_embedding, chosen for exact max-over-views semantics. At catalogue scale that is correct and fast, but every insert pays HNSW graph maintenance for an index nothing uses, and nothing asserts a query plan. An index-friendly two-stage probe is the measurable follow-up.
status: open

### DW-162: AD-16's inference serialization and startup warm-up are absent, so concurrent catalogue adds oversubscribe the CPU exactly as the POC measured.
origin: spec-deferred cb5fde05f8e2
location: shared/vision/shared_vision/pipeline.py
source_spec: `spec-2-1-add-product.md`
severity: medium
reason: The ported session lock prevents a double model load but not concurrent forward passes. An add holds a threadpool worker for 16 passes per image; the POC measured 8 concurrent scans collapsing to 2.6s each. AD-16 binds the scan endpoint (Epic 3), which is where the shared serialization slot and the ~900ms cold start belong.
status: open

### DW-163: `pixel_std` is measured on the 2048px-capped image over the whole RGB array, so the featureless flag differs from the POC and never fires on a flat coloured tile.
origin: spec-deferred 9779b6b50bfc
location: shared/vision/shared_vision/intake.py
source_spec: `spec-2-1-add-product.md`
severity: medium
reason: The POC computes the deviation on a thumbnail; the port computes it on the full capped image, and FEATURELESS_STD = 3.0 carried over unchanged. Because the deviation is taken across all three channels, a flat coloured reference measures around 6 and is not flagged while a flat neutral one measures 0 and is. MONO COLOUR ranges are exactly the case FR-19 names, and the POC found MONO COLOUR GLOSSY 11B embedding to cosine 1.0 with RUANDA 7CM.
status: open

### DW-164: `find_candidates` takes an already-decoded PIL image, so a caller can reach the embedder without passing through AD-7 intake and AD-15 colour management.
origin: spec-deferred 32180d65aec7
location: apps/api/api/catalogue.py find_candidates
source_spec: `spec-2-1-add-product.md`
severity: low
reason: The signature mirrors the POC's Matcher.embed_query and AD-1 still holds (both paths call the same preprocess/embed pair), but the load_image step is the caller's responsibility. Epic 3's scan endpoint is the caller that must not get this wrong; taking bytes instead would make the invariant unskippable.
status: open

### DW-165: The endpoint-level AD-15 assertion hardcodes a macOS ColorSync profile path, so it never runs on Linux.
origin: spec-deferred 145e1fe0db4b
location: apps/api/tests/test_add_tile.py
source_spec: `spec-2-1-add-product.md`
severity: low
reason: test_a_cmyk_press_file_is_stored_and_embedded_in_srgb skips unless /System/Library/ColorSync/Profiles/Generic CMYK Profile.icc exists, while shared/vision/tests/test_colour_management.py solves the same problem with a candidate list that includes Linux paths. On Linux only the library-level test remains.
status: open

### DW-166: A reference image whose short edge is under 64px produces twelve black-padded crop views rather than crops.
origin: spec-deferred 075b0ac8f010
location: shared/vision/shared_vision/views.py
source_spec: `spec-2-1-add-product.md`
severity: low
reason: `side = max(64, min(side, short))` in the ported view generator exceeds the frame on a tiny reference, so img.crop pads. Inherited verbatim from the POC, and no real catalogue image is that small, but nothing in the intake path refuses one either.
status: open

### DW-167: There is a per-file byte ceiling but no aggregate bound on a request, and every source and derivative is held in memory at once.
origin: spec-deferred 19ea7289eeaa
location: apps/api/api/catalogue.py add_tile
source_spec: `spec-2-1-add-product.md`
severity: medium
reason: MAX_IMAGE_BYTES is per file and MAX_IMAGES_PER_REQUEST is 8, so one accepted request is up to ~1GB of spooled body, and _Prepared retains every source and derivative byte string plus every decoded image for the duration of the add.
status: open

### DW-168: `add_tile` holds a pooled Postgres connection for the whole embedding run, so a handful of concurrent adds can starve every other request in the product of a connection.
origin: spec-deferred e6a48ddf69e2
location: apps/api/api/catalogue.py add_tile
source_spec: `spec-2-1-add-product.md`
severity: medium
reason: `conn` is a `Depends(get_connection)` parameter, so the connection is checked out before the handler body and returned after it — across `_prepare`, which the module's own docstring calls "tens of seconds per image". `api/db.py` sets POOL_MAX_SIZE = 10 and POOL_TIMEOUT_SECONDS = 10.0 while FastAPI's threadpool admits more concurrent sync handlers than that, so ten simultaneous adds park the pool and `/auth/login` starts failing on a pool timeout. The connection is only needed for the cheap pre-flights and the final transaction. Distinct from the AD-16 entry above: that one is about CPU oversubscription, this one is about connection starvation in unrelated requests.
status: open

### DW-169: A failed ICC transform silently falls back to the naive RGB conversion AD-15 exists to prevent, with nothing logged, recorded or surfaced.
origin: spec-deferred 62accec03103
location: shared/vision/shared_vision/pipeline.py _to_srgb
source_spec: `spec-2-1-add-product.md`
severity: medium
reason: `_to_srgb` catches `(PyCMSError, OSError, ValueError)` and falls through to `img.convert("RGB")`. On the CMYK press files that are ~60% of the catalogue that is the ink inversion the POC measured at an 84-level channel shift — the tile is indexed and displayed with corrupt colour and the add still answers 201. The module has no logger, the `reference_image` row has no column for it, and `test_a_broken_profile_does_not_refuse_the_image` builds its fixture from an RGB image, so the dangerous combination (unreadable profile on a CMYK source) is untested. Inherited verbatim from `poc/tilematch/vision.py`, which the spec requires be copied unchanged, so this is a decision about the port rather than a defect in the porting.
status: open

### DW-170: EXIF orientation is silently not applied to any image carrying an ICC profile, because the colour transform runs first and returns an image with no EXIF.
origin: spec-deferred 597a6b30f5a5
location: shared/vision/shared_vision/pipeline.py load_image
source_spec: `spec-2-1-add-product.md`
severity: medium
reason: `load_image` calls `_to_srgb(img)` and then `ImageOps.exif_transpose(img)`. Verified empirically with Pillow in this workspace: `ImageCms.profileToProfile` returns a fresh image whose `info` holds only `icc_profile`, so `exif_transpose` is a no-op afterwards and a rotated phone photo or press file is indexed sideways. The I/O matrix row promises "Orientation applied, then all metadata dropped"; the metadata half holds, the orientation half holds only for profile-less images, and both orientation tests (`shared/vision/tests/test_pipeline.py`, `apps/api/tests/test_add_tile.py`) use fixtures with EXIF and no profile. Inherited verbatim from the POC, and the four clean rotations of AD-13 partly mask it at index time. Not patched here because the fix is a change to `shared/vision`, which CLAUDE.md binds to an eval run and a re-index, and because the spec's Always list requires the file be copied unchanged — that tension is a decision, not an edit.
status: open

### DW-171: `config_hash()` does not cover the identity of the ONNX artifact, so two deployments running different weights carry an identical AD-14 stamp.
origin: spec-deferred 79f363048709
location: shared/vision/shared_vision/pipeline.py config_hash
source_spec: `spec-2-1-add-product.md`
severity: medium
reason: The hash is over the preprocessing constants. `_verify_stamp` therefore passes while vectors from two different models are compared against each other — the silent accuracy failure the stamp exists to prevent. The only guard today is the pinned revision and sha256 in `scripts/fetch_model.py`, which a developer can bypass by placing a file at `ROCELL_MODEL_PATH` directly. Hashing the artifact once at session build would close it.
status: open

### DW-172: Nothing in the product can cut a new generation over, so the first `shared/vision` change refuses every add and every search with no documented recovery.
origin: spec-deferred 852ea69e7a2a
location: apps/api/api/catalogue.py ensure_active_generation
source_spec: `spec-2-1-add-product.md`
severity: medium
reason: `ensure_active_generation` only inserts when no active row exists; no code anywhere issues an `UPDATE ... SET is_active` or opens a second generation. `_verify_stamp` then answers `503 pipeline_stamp_mismatch` on both the write and the read path, and the only way out is hand-written SQL. AD-14's "cut over by a single pointer" has no operator surface and `infra/README.md` has no runbook for it. `make ingest` (Epic 2) is the natural home for the rebuild half.
status: open

### DW-173: AD-15's rendering intent is only distinguishable by tests that skip on any checkout without the gitignored `poc/Tiles` reference tree.
origin: spec-deferred 29f4d064b306
location: shared/vision/tests/test_colour_management.py
source_spec: `spec-2-1-add-product.md`
severity: medium
reason: `test_the_rendering_intent_matches_colorsync` and its two siblings are gated on `poc/Tiles/45X90/POLISH/Copy of RP.RSS.0062ST.PL.0T.jpg`, which `.gitignore` excludes. The portable half of the file states in its own comment that a generic CMYK profile carries identical tables for the two intents and would pass either way, and the remaining assertion reads the constant and the source text rather than the transform. So deleting `renderingIntent=RENDERING_INTENT` from `_to_srgb` is green on a fresh clone while every CMYK reference indexes near-black. A committed synthetic profile whose perceptual and relative-colorimetric tables differ would make the Block-If condition checkable anywhere.
status: open

### DW-174: A present-but-unloadable `model.onnx` surfaces as an opaque 500, while only an absent one gets the named 503 that says how to fix it.
origin: spec-deferred 8714c86d96af
location: apps/api/api/catalogue.py _prepare
source_spec: `spec-2-1-add-product.md`
severity: low
reason: `_prepare` catches `FileNotFoundError`. ONNX Runtime's own failures for a truncated or incompatible export (`Fail`, `InvalidProtobuf`, `NoSuchFile`) derive from `Exception` directly, so they pass straight through after the request has already spent its CPU. Naming them needs either an exception contract in `shared/vision` — which the spec requires be a verbatim copy — or an `onnxruntime` import in `apps/api`, which is a new declared dependency. Both are decisions rather than edits.
status: open

### DW-175: An unset `OBJECT_STORAGE_ROOT` fails during dependency resolution, so it reaches the caller as an unhandled 500 rather than as a named refusal.
origin: spec-deferred e69638010b65
location: apps/api/api/storage.py get_object_store
source_spec: `spec-2-1-add-product.md`
severity: low
reason: `get_object_store()` raises `ObjectStorageNotConfigured(RuntimeError)`, which no handler converts. `api.db` validates `DATABASE_URL` at startup and this could do the same; the Makefile's advisory `echo` and its comment ("a missing value is a 500 on the first `POST /admin/tiles`") acknowledge the gap instead of closing it. `test_object_storage.py` asserts the exception, never what a caller sees.
status: open

### DW-176: A client timeout after the server has already committed leaves the Administrator with no remedy but a `code_already_exists` on retry.
origin: spec-deferred a8365652bf9f
location: apps/web/src/api/client.ts
source_spec: `spec-2-1-add-product.md`
severity: low
reason: `client.ts` documents the failure precisely and answers it by widening the bound to `UPLOAD_TIMEOUT_MS`. An aborted browser request still runs to completion on the server, and there is no idempotency key, no server-side deadline matching the client's, and no way for the screen to tell "timed out, tile exists" from "timed out, nothing written". An idempotency key on the add is the shape of the fix and is a contract decision.
status: open

### DW-177: The only route serving a reference image is Administrator-only, but Epic 3 must show one beside every Candidate to a Staff caller.
origin: spec-deferred 5733725a69c9
location: apps/api/api/catalogue.py read_tile_image
source_spec: `spec-2-1-add-product.md`
severity: low
reason: `GET /admin/tiles/{tile_id}/images/{image_id}` sits under `require_administrator` and `test_a_staff_caller_is_refused_the_image_read` pins that. CLAUDE.md's product rules require the reference image beside each candidate for the staff who scan. Epic 3 will either add a second image route — the asymmetry this module's docstring warns about — or move this one out from under `/admin/`, which `test_every_route_declaring_the_role_check_is_under_admin` will then contest. Worth deciding before Epic 3 writes the scan endpoint rather than after.
status: open

### DW-178: `session-expiry.test.tsx` failed once under a full `make test` run and passed on every run since, including in isolation.
origin: spec-deferred c93f3c9963f5
location: apps/web/src/__tests__/session-expiry.test.tsx:321
source_spec: `spec-2-1-add-product.md`
severity: low
reason: One `make test` invocation during this review pass failed at `src/__tests__/session-expiry.test.tsx:321` waiting for the signed-out notice; the file is untouched by Story 2.1 and the same suite passed on the next two full runs and on a targeted run. A test that fails under load and passes alone is a real defect in the test, not noise, and is worth pinning before it is dismissed as a fluke.
status: open

### DW-179: `config_hash()` covers the preprocessing constants but not the augmentation constants, so changing how views are generated produces a different index under an identical AD-14 stamp.
origin: spec-deferred 561a6488bc65
location: shared/vision/shared_vision/pipeline.py config_hash
source_spec: `spec-2-1-add-product.md`
severity: medium
reason: The hash is built from `RESIZE_SHORTEST_EDGE`, `CROP_SIZE`, the normalization constants and `PIPELINE_VERSION`. Every stored vector also depends on `views.py` — `VIEWS_PER_IMAGE`, `CANONICAL_VIEWS`, `CROP_SCALE_MIN/MAX` and the five augmentation ranges — and none of those reach the stamp. Edit a crop range and `_verify_stamp` passes while the generation holds vectors from two different view recipes, which is precisely the silent mixing AD-14 exists to prevent. Distinct from the ONNX-artifact gap already recorded: that one is about the weights, this one is about the views. Not fixed here because widening the hash changes every stamp, which CLAUDE.md binds to an eval run and a full re-index.
status: open

### DW-180: `_get_session` publishes the ONNX session before the input and output names, so a second thread can take the fast path and embed with an empty feed name.
origin: spec-deferred b68c8dcff7cc
location: shared/vision/shared_vision/pipeline.py _get_session
source_spec: `spec-2-1-add-product.md`
severity: low
reason: `_build_session` assigns `_session` first and `_input_name`/`_output_name` after. The fast path in `_get_session` reads `_session` without the lock, by design, so a thread arriving in that window returns a usable session while `embed` reads `_output_name` as `""` and ONNX Runtime raises `Invalid Feed Input Name`. It needs two concurrent first-embeds in one process, so it is rare and non-deterministic — an intermittent 500 on the first concurrent add after a restart. Carried verbatim from `poc/tilematch/vision.py`, which the spec's Always list requires be copied unchanged, so the fix is a decision about the port rather than an edit to it.
status: open

### DW-181: An accepted image with an extreme aspect ratio expands rather than shrinks in `preprocess`, so a few-KB upload can cost hundreds of megabytes per view.
origin: spec-deferred f8f666f7b767
location: shared/vision/shared_vision/pipeline.py preprocess
source_spec: `spec-2-1-add-product.md`
severity: low
reason: `DECODE_MAX_EDGE` caps the long edge at 2048 but nothing bounds the ratio. A 2048x8 image passes every gate — small file, few pixels — and `preprocess` resizes the *shortest* edge to 256, scaling it back up to 65536x256, about 17 megapixels of float32 per view and sixteen views per image. The pixel gate reads header dimensions, which for this shape are honest and small. Inherited from the POC's `preprocess`, where the inputs were a curated catalogue rather than an upload.
status: open

### DW-182: The Code, Size and Category hints are bound to no input, and no control sets `aria-busy` while a minute-long save is in flight.
origin: spec-deferred 2ddbe8813f13
location: apps/web/src/screens/AddTileScreen.tsx
source_spec: `spec-2-1-add-product.md`
severity: low
reason: The Reference images hint is now bound through `aria-describedby` because it carries the count and byte limits, which are stated nowhere else. The other three `.hint` paragraphs — including the one explaining that a blank Category files the tile under `UNKNOWN` — are still visual-only. Separately, `disabled={submitting}` removes the just pressed Save from the tab order for the length of the request; `aria-busy` on the form would say why. Both are DESIGN.md/EXPERIENCE.md questions about the screen's pattern rather than defects in this endpoint, and the same pattern is about to be copied by Stories 2.2 and 2.4.
status: open

### DW-183: A second successful Find silently discards the Administrator's unsaved edits, removal marks and chosen files.
origin: spec-deferred 3300d2795052
location: apps/web/src/screens/EditTileScreen.tsx handleLookup
source_spec: `spec-2-2-edit-product.md`
severity: medium
reason: `handleLookup` routes a hit straight through `adopt()`, which resets `code`, `size`, `category`, `marked`, `files` and the file input with no confirmation. The suite pins only the miss case (`clears a loaded tile when a later lookup misses`). The epic's UX obligation is "never drop an in-progress catalogue edit silently", and this screen confirms every other destructive step. Not patched here because the fix is a third dialog state and a dirty-tracking rule, which is a screen-pattern decision rather than an edit.
status: open

### DW-184: Nothing bounds a Tile's total Reference Images across edits, and the same asset can be stored twice with sixteen more vectors behind it.
origin: spec-deferred 10c887f7a762
location: apps/api/api/catalogue.py edit_tile
source_spec: `spec-2-2-edit-product.md`
severity: low
reason: `MAX_IMAGES_PER_REQUEST` bounds one request, and the screen's own hint invites repetition ("Save, then add the rest"), so a Tile grows without limit over successive edits. `reference_image` carries `sha256` but has no unique index over `(tile_id, sha256)`, so re-saving an asset already on the Tile stores a second copy, a second derivative and sixteen more `reference_embedding` rows that all score the same Tile. Story 2.1 was careful to bound the add at 1-8; the cumulative bound was never decided.
status: open

### DW-185: `_SELECT_TILE_IMAGES` is documented as chronological but sorts effectively by uuid, and can disagree with the order the add response showed.
origin: spec-deferred b4808b44a65a
location: infra/migrations/20260921T1500_create_catalogue.up.sql reference_image.created_at
source_spec: `spec-2-2-edit-product.md`
severity: low
reason: `reference_image.created_at` defaults to `now()`, which in PostgreSQL is the *transaction* timestamp, and `add_tile` inserts every image of one request in one transaction. Every image of a multi-image add therefore ties on `created_at` and the tiebreak is `gen_random_uuid()`. The order is stable, which is what the screen needs, but it is arbitrary rather than chronological and differs from `add_tile`'s own response, which is built in upload order. `clock_timestamp()` as the default, or an explicit ordinal column, would make the documented intent true.
status: open

### DW-186: `GET /admin/tiles/lookup` writes no audit entry and has no throttle, on a route that confirms a Code one guess at a time.
origin: spec-deferred 1f325da1deb9
location: apps/api/api/catalogue.py lookup_tile
source_spec: `spec-2-2-edit-product.md`
severity: low
reason: The handler's docstring declines to record a read because "an entry per lookup would bury the entries that matter", which is the argument `read_reference_image` makes and is reasonable on its own. It does not engage the other half: catalogue exfiltration through a compromised account is this product's stated primary commercial threat, and this is the first route that answers "does this exact Code exist" in one cheap request. `api/throttle.py` already exists. Either the trade-off belongs in the docstring or a coarse record or limit does.
status: open

### DW-187: A save that times out after the server has already committed leaves the screen holding removal marks and files it has in fact already sent.
origin: spec-deferred 87e76ac62de4
location: apps/web/src/screens/EditTileScreen.tsx save
source_spec: `spec-2-2-edit-product.md`
severity: low
reason: `save()`'s catch clears neither `marked` nor `files`, so a retry after an `UPLOAD_TIMEOUT_MS` abort re-sends ids the server has already deleted (`404 image_not_found`) and re-uploads files it has already stored. Same shape as the add path's timeout-after-commit entry recorded against Story 2.1: there is no idempotency key and no server-side deadline matching the client's, so the screen cannot tell "timed out, the edit landed" from "timed out, nothing changed". Re-running the lookup on a timeout would recover the screen; an idempotency key would fix the class.
status: open

### DW-188: `session-expiry.test.tsx` failed once again under a full `make test` run and passed on every run since - a second sighting of the flake recorded against Story 2.1.
origin: spec-deferred fe32da5a7c16
location: apps/web/src/__tests__/session-expiry.test.tsx:476
source_spec: `spec-2-2-edit-product.md`
severity: low
reason: One `make test` invocation during this story failed at `src/__tests__/session-expiry.test.tsx:476` waiting for the second call of a failing revalidation; the same suite passed on the next three full runs. Story 2.1 recorded the same file failing at `:321` and passing on every rerun. The file is untouched by this story, and the only change to anything it imports is two added exported constants in `client.ts`. Two sightings at two different lines is a pattern rather than noise, and a test that fails under load and passes alone is a real defect in the test.
status: open

### DW-189: Two Administrators editing one Tile silently overwrite each other - the row lock serializes the writes but detects no staleness.
origin: spec-deferred c7ae0fe81cda
location: apps/api/api/catalogue.py edit_tile
source_spec: `spec-2-2-edit-product.md`
severity: medium
reason: `edit_tile` locks the Tile `FOR UPDATE`, which orders the two transactions but does not notice that the second one read its values before the first committed: the later save writes its own Code, Size and Category over the earlier one with no refusal and nothing on either screen. `updated_at` is already on the row and already returned by both the lookup and the save, so the material for an `If-Match` round-trip exists; what is missing is the contract for it - a new envelope code, the header or part that carries the stamp, and the screen's answer when it is stale. That is a concurrency contract for the catalogue rather than an edit, and it is not decidable from this story's intent, which is silent on simultaneous editors. Distinct from the already-recorded ledger item about a second Find discarding one Administrator's own unsaved work.
status: open

### DW-190: The audit entry for an edit records image counts only, so a hard-deleted Reference Image leaves no identifying trace anywhere.
origin: spec-deferred d10c19df8d72
location: apps/api/api/catalogue.py edit_tile audit details
source_spec: `spec-2-2-edit-product.md`
severity: medium
reason: `details` carries `images_added` and `images_removed` as integers, and `_EDITABLE_FIELDS`' docstring argues image ids are "not something a reader of the log can do anything with". But removal here is a real `DELETE` plus a post-commit object delete - the row, its sixteen embeddings and both stored objects are gone - so the audit entry is the only remaining trace of what was destroyed, and it records none of it. FR-20/AD-4 attributability is weakest exactly where the action is irreversible. Deferred rather than patched because what the entry should carry (the id, the dimensions, the storage keys) changes what an Administrator reads in the log and is a log-contract decision, not an edit.
status: open

### DW-191: `remove_image_ids` has no ceiling, unlike `images`, so one request can name an unbounded number of ids.
origin: spec-deferred 896e06e2c063
location: apps/api/api/catalogue.py edit_tile requested_removals
source_spec: `spec-2-2-edit-product.md`
severity: low
reason: `MAX_IMAGES_PER_REQUEST` bounds the uploads; nothing bounds the removal list. The per-id work is linear now that `_removals` is set-based, so this is no longer a quadratic burn, but an authenticated caller can still make the handler parse a hundred thousand UUIDs before answering `404`. A bound needs its own envelope code, a refusal sentence, rows in `error-code-parity.test.ts` in both directions and a mirror on the screen - the same shape as `too_many_images` - which is a contract addition rather than a patch.
status: open

### DW-192: A refusal stays painted on a field while the Administrator is correcting the very field it blames.
origin: spec-deferred 091b916c0d70
location: apps/web/src/screens/EditTileScreen.tsx typed
source_spec: `spec-2-2-edit-product.md`
severity: low
reason: `typed()` clears only `saved`, while `chooseFiles` and `toggleMarked` clear `error` as well. After a `409 code_already_exists`, typing a new Code leaves `aria-invalid="true"` and the stale sentence under the field until the next Save answers. `AddTileScreen` has the same asymmetry, so this is a copied screen pattern rather than something this story introduced - but the edit screen has five slots instead of four and the stale alert is now bound to a control the Administrator is actively fixing. Worth deciding once for both screens rather than diverging them.
status: open

### DW-193: Every edit re-resolves the Size through `ON CONFLICT DO UPDATE`, taking a write lock on the shared `tile_size` row even when the request sent no Size at all.
origin: spec-deferred 0069631766de
location: apps/api/api/catalogue.py edit_tile
source_spec: `spec-2-2-edit-product.md`
severity: low
reason: `_SELECT_TILE_FOR_UPDATE` returns the Size *name* rather than its id, so the handler runs `_RESOLVE_SIZE` unconditionally inside the transaction and writes the row back to itself. That takes a row lock held until commit, so two edits of two unrelated Tiles that happen to share a Size serialize behind each other for the length of an upload — and a pure rename, which touches no Size, pays it too. The intent requires both to be "resolved through the same normalized create-if-missing lookup the add uses", and the add genuinely does need the row; the edit needs it only when a Size was actually sent. Not patched because the fix is a column added to the locked read and a branch on `new_size`, which changes what the transaction holds and wants its own concurrency test rather than an edit.
status: open

### DW-194: The edit form's fields, Remove checkboxes and file input stay live during an in-flight save, and `adopt()` discards whatever was changed there when it lands.
origin: spec-deferred 2ef661ce2405
location: apps/web/src/screens/EditTileScreen.tsx
source_spec: `spec-2-2-edit-product.md`
severity: low
reason: Only the Save, Find and Back buttons carry `disabled={submitting || looking}`. Every input stays editable while `Saving…` is showing, and the successful response routes through `adopt()`, which resets `code`, `size`, `category`, `marked`, `files` and the file input — so a mark ticked or a character typed during the wait vanishes under "Saved." with nothing said. Same root as the already-recorded entry about a second Find discarding unsaved work: `adopt()` is unconditional. The fix is the dirty-tracking rule that entry is waiting on, applied to a second trigger, so it belongs with it rather than ahead of it.
status: open

### DW-195: A Reference Image whose stored derivative is missing renders as the browser's broken image glyph, beside a live Remove control and no explanation.
origin: spec-deferred ac06c5f18261
location: apps/web/src/screens/EditTileScreen.tsx gallery
source_spec: `spec-2-2-edit-product.md`
severity: low
reason: The gallery's `<img>` has no `onError`, so a `404` from `GET /admin/tiles/{id}/images/{imageId}` — an object an operator deleted, or one a failed `_discard` left half-removed — shows as a broken icon with the alt text behind it. The Administrator is then asked to decide whether to remove an image they cannot see, on the one screen whose whole justification is that "staff can verify a picture instantly". `AddTileScreen` renders no images at all, so there is no established treatment to copy: a placeholder, its sentence and whether Remove stays enabled are a screen-pattern decision.
status: open

### DW-196: `edit-user.test.tsx` failed once under a full `make test` run and passed alone and on the next full run - a third sighting of the web suite's under-load flake, in a new file.
origin: spec-deferred 4c74bc91f2f8
location: apps/web/src/__tests__/edit-user.test.tsx:506
source_spec: `spec-2-2-edit-product.md`
severity: low
reason: One `make test` invocation during this pass failed at `apps/web/src/__tests__/edit-user.test.tsx:506` asserting focus had returned to the email box; the same file passed alone (44/44) immediately afterwards and the next full `make test` was green at 1277/1277. Two prior sightings are already recorded against `session-expiry.test.tsx` at `:321` (Story 2.1) and `:476` (this story). Neither file is touched by this story. Three sightings across two files, all of them focus- or timing-dependent assertions that pass in isolation, is a suite-level defect rather than three separate flaky tests.
status: open

### DW-197: No `FOR UPDATE` read anywhere in the API sets a `lock_timeout`, so one stuck transaction blocks every request that touches the same row indefinitely.
origin: spec-deferred 74e63ce217a8
location: apps/api/api/catalogue.py remove_tile, edit_tile; apps/api/api/users.py delete_user
source_spec: `spec-2-3-remove-product.md`
severity: medium
reason: `catalogue.remove_tile` and `catalogue.edit_tile` take `_SELECT_TILE_FOR_UPDATE`, and `users.delete_user`/`deactivate_user` take their own locking reads, none of them under a `SET LOCAL lock_timeout`. A transaction that acquires a row lock and then hangs holds a worker per waiting request until the pool is exhausted. Not caused by this story — the pattern predates it in three handlers — and a timeout value plus the refusal it maps to is a product decision rather than an edit.
status: open

### DW-198: The `needs_model` skipif block is now written out verbatim in four test files rather than living in `conftest.py`.
origin: spec-deferred cf42c1c826b0
location: apps/api/tests/conftest.py
source_spec: `spec-2-3-remove-product.md`
severity: low
reason: `pytest.mark.skipif(not pipeline.MODEL_PATH.exists(), ...)` appears identically in `test_add_tile.py`, `test_catalogue_audit.py`, `test_remove_tile.py` and — added by this story — `test_catalogue_authorization.py`, each with its own `shared_vision` imports. `conftest.py` already supplies every other shared fixture these files use. A fourth copy is the point at which the duplication is worth collapsing, but doing it touches three files this story does not otherwise own.
status: open

### DW-199: `session-expiry.test.tsx`'s sign-out assertion is flaky under the full suite's parallel load, failing roughly one run in four while passing every time the file is run alone.
origin: spec-deferred 488bd6f73d8d
location: apps/web/src/__tests__/session-expiry.test.tsx:165
source_spec: `spec-2-3-remove-product.md`
severity: low
reason: Observed during this pass: `make test` failed once at `session-expiry.test.tsx:165` (`findByLabelText(/password/i)` timing out after the sign-out click, with the signed-in home panel still rendered), then passed on two consecutive full runs and on an isolated run of that file. Nothing in this story touches session handling or that screen — the only edits near it are comment-only lines in `App.tsx` and `api/client.ts` — so the flake predates this change and is a property of the test's waiting strategy under 23 parallel workers, not of the diff.
status: open

### DW-200: The whole multipart body is received and spooled to disk before `require_administrator` runs, so a session-holder can push a large body before being refused.
origin: spec-deferred f7c0426fbe93
location: apps/api/api/catalogue.py bulk_upload, add_tile
source_spec: `spec-2-4-bulk-upload.md`
severity: medium
reason: FastAPI reads the form before solving dependencies, so the role check fires only after every part has been written. Not caused by this story — `add_tile` has had the same property since 2.1, and the root cause is that nothing in the product bounds a request body: there is no middleware (the spine forbids adding one here), no proxy limit in `infra/`, and no aggregate ceiling anywhere. A body bound is a deployment contract this codebase has no authority to invent.
status: open

### DW-201: A batch has no aggregate byte budget, and every upload is written to disk twice.
origin: spec-deferred 7e90bc5de073
location: apps/api/api/catalogue.py _spool
source_spec: `spec-2-4-bulk-upload.md`
severity: low
reason: With the row/part cap in place the worst case is `MAX_BULK_ROWS` x `MAX_IMAGE_BYTES` of temporary files, and Starlette has already spooled each part before `_spool` copies it again. Both copies are needed as written — the second is what makes the bytes outlive the multipart form under a `StreamingResponse` — so removing the duplication means changing how the form's lifetime is held, and a total-bytes ceiling would refuse legitimate batches of the 96 MB press files this catalogue really contains. The number is a product decision.
status: open

### DW-202: `session-expiry.test.tsx`'s 401 assertion is flaky under the full suite's parallel load, failing roughly one run in four while passing every time the file is run alone.
origin: spec-deferred fd8a4c6eddcd
location: apps/web/src/__tests__/session-expiry.test.tsx
source_spec: `spec-2-4-bulk-upload.md`
severity: low
reason: Observed once during this pass: `make test` failed at `a 401 from any request drops the app to the login screen > swaps the shell for the login screen and says the session ended` (`findByLabelText(/password/i)` timing out with the signed-in shell still rendered), then passed on an isolated run of that file and on three consecutive full web-suite runs. The file is untouched by this story and nothing here reaches session handling. The same flake is already recorded on Story 2.3.
status: open

### DW-203: `EditTileScreen`'s reference-image gallery strips its list markers without restating `role="list"`, so it stops being announced as a list.
origin: spec-deferred aa5207fb4a9b
location: apps/web/src/screens/EditTileScreen.tsx:823
source_spec: `spec-2-4-bulk-upload.md`
severity: low
reason: `EditTileScreen.module.css:200` sets `list-style: none` under a comment claiming "the list is still a list to a screen reader, which is what makes 'three reference images' audible" — the exact claim this story disproved on its own report list and corrected there with an explicit `role="list"`. Safari and VoiceOver drop list semantics from a marker-less list, so on that pairing the gallery announces neither "list, 3 items" nor "image 2 of 3". Pre-existing since Story 2.2; nothing in this change touches that screen, and no test in `edit-tile.test.tsx` asserts the role or the item count.
status: open

### DW-204: Every Catalogue row downloads a full 1280px display derivative to fill a 96px thumbnail, so browsing the whole catalogue is tens of megabytes.
origin: spec-deferred 13da2e4e0efc
location: apps/web/src/screens/CatalogueScreen.tsx thumbnails; shared/vision display_derivative
source_spec: `spec-2-5-catalogue-search.md`
severity: medium
reason: AD-17 generates one capped derivative (~1280px, ~300KB) at write time and forbids rendering anything on demand, and the list is deliberately uncapped, so a browse of a few hundred Tiles fetches a few hundred full-size derivatives. `loading="lazy"` defers the offscreen ones and nothing more. The size of that one derivative was chosen by Story 2.1 for the Edit Tile gallery; this story is the first surface that shows hundreds of them at 96px. A list-sized variant or a `?size=` parameter on the image route is an AD-17 decision, not a patch this story could make.
status: open

### DW-205: The one route that can export the whole catalogue in a single request is neither rate-limited nor recorded.
origin: spec-deferred 028253f900da
location: apps/api/api/catalogue.py search_tiles
source_spec: `spec-2-5-catalogue-search.md`
severity: medium
reason: `GET /admin/tiles` with a blank `q` answers every Tile's Code, Size and Category in one body. AGENTS.md names catalogue exfiltration through a compromised account as the primary commercial threat and mandates throttling on login and on scanning, but says nothing about admin reads, and FR-20 covers changes rather than reads -- which is why this story deliberately records nothing. Whether an Administrator's catalogue reads deserve the scan throttle, or an audit entry of their own, is a product and security decision worth settling before the pen test that gates rollout.
status: open

### DW-206: Two Administrators editing the same Tile silently overwrite each other -- the edit path carries no optimistic-concurrency check.
origin: spec-deferred 450215ccedc3
location: apps/api/api/catalogue.py edit_tile
source_spec: `spec-2-5-catalogue-search.md`
severity: medium
reason: A Tile handed over by a Catalogue row is as old as the listing, and `PATCH /admin/tiles/{tile_id}` writes every column unconditionally with no `updated_at` precondition, so the second save wins and the first is lost with no warning. Pre-existing since Story 2.2 -- the lookup stage had the same staleness -- and surfaced here only because a row makes the gap between reading and saving longer and more ordinary.
status: open

### DW-207: Edit Tile's code-entry form can replace an in-progress edit without warning, dropping typed changes, queued files and pending removals.
origin: spec-deferred 9ccfa33889fa
location: apps/web/src/screens/EditTileScreen.tsx lookup form
source_spec: `spec-2-5-catalogue-search.md`
severity: medium
reason: The lookup form is rendered above the edit form at all times, and a successful Find replaces the adopted Tile and every field with no confirmation. EXPERIENCE.md:90 says never to drop an in-progress catalogue edit silently. Pre-existing since Story 2.2, when the stage was the only entry point; this story did not change that behaviour.
status: open

### DW-208: `session-expiry.test.tsx`'s 401 tests flake under CPU contention because they rely on the default 1000ms `findBy` timeout.
origin: spec-deferred 445f93576411
location: apps/web/src/__tests__/session-expiry.test.tsx
source_spec: `spec-2-5-catalogue-search.md`
severity: low
reason: Reproduced by running two full web suites concurrently: one of the two tests in `describe('a 401 from any request drops the app to the login screen')` times out at ~1015ms waiting for the login screen's password label. The same failure, in the same file, reproduces at baseline revision 87d032c74169146906de0059b26a4b5cf34cdada in a worktree built from that commit, so it predates this story. Fifteen consecutive standalone runs of that file pass, as do eight consecutive runs of the whole suite when nothing competes with it.
status: open

### DW-209: The three session-state authorization claims on the Catalogue are pinned on the add alone, so no other catalogue route proves them.
origin: spec-deferred b4d6ed2c5f5b
location: apps/api/tests/test_catalogue_authorization.py:441-487
source_spec: `spec-2-5-catalogue-search.md`
severity: low
reason: `test_an_administrator_on_an_unclaimed_temporary_credential_is_refused`, `..._deactivated_mid_session_is_refused_as_unauthenticated` and `..._demoted_mid_session_is_refused_on_the_next_request` all send `post_tile` and nothing else, while the file's own `test_every_refusal_is_uncacheable` is parametrized across all seven routes. The claims hold today because `require_administrator` is one shared dependency, but that is the thing being asserted -- a route that ever declared its guard itself would be caught on the add and nowhere else, and `GET /admin/tiles` is the route where a stale role discloses the whole catalogue in one body. Pre-existing since Story 2.1; Story 2.5 added the seventh route to the parametrized test and left these three unchanged, which is where the asymmetry became visible.
status: open

### DW-210: A row's thumbnail that fails to load renders the browser's broken-image glyph instead of the deliberate "No image" state beside it.
origin: spec-deferred af3ee9f0898e
location: apps/web/src/screens/CatalogueScreen.tsx row thumbnail; apps/web/src/screens/EditTileScreen.tsx gallery
source_spec: `spec-2-5-catalogue-search.md`
severity: low
reason: `CatalogueScreen` renders `<img>` with no `onError`, so a `404` from a derivative that never got written, a `403` or a dropped connection paints a broken glyph in a 96px cell -- next to rows whose genuinely imageless tiles say "No image" in words. CLAUDE.md makes the reference image the thing that makes a candidate verifiable, so the two failures reading differently matters. `EditTileScreen`'s gallery (Story 2.2) has the same gap and established the convention, which is why this story inherited it rather than introduced it; fixing one without the other would leave the product saying two things.
status: open

### DW-211: Every return to the Catalogue re-downloads every visible thumbnail, because the image route is `no-store` and the screen refetches on mount.
origin: spec-deferred 15f2027ddd9a
location: apps/api/api/catalogue.py tile image route; apps/web/src/screens/CatalogueScreen.tsx mount refetch
source_spec: `spec-2-5-catalogue-search.md`
severity: medium
reason: `GET /admin/tiles/{tile_id}/images/{image_id}` answers with `{**NO_STORE, **NO_SNIFF}` (Story 2.1), so no thumbnail is ever cached by the browser, and the Catalogue's refetch on mount is deliberate -- a tile just added, renamed or removed has to show up. Together they mean that Back from Add tile, Edit tile or Bulk upload re-requests the list *and* every row's image through an authenticated, role-rechecking, DB-reading route. This compounds the oversized-derivative entry above rather than duplicating it: that one is about the size of one fetch, this one is about how many times it happens. Whether a catalogue thumbnail may be privately cached is an AD-17 / AGENTS.md decision about how much catalogue data may sit in a shared handset's disk cache, not a patch this story could make.
status: open

### DW-212: The upload path has no file-size/dimension guard before decoding a chosen file.
origin: spec-deferred 6028056a0512
location: apps/web/src/screens/ScanScreen.tsx (chooseFile)
source_spec: `spec-3-1-capture-or-upload-a-scan.md`
severity: low
reason: `chooseFile` in ScanScreen.tsx hands whatever file the user picks straight to `createImageBitmap`/canvas with no size check, so an unusually large photo-library pick could hang or strain a mobile tab's memory before the ~1024px downscale ever runs. No AC or I/O-matrix row in this story covers file size, and typical phone camera photos are far below any risky threshold, so this is a hardening item rather than a defect in the shipped scenarios.
status: open

### DW-213: Nothing detects the camera track ending or being revoked externally mid-session.
origin: spec-deferred 8540ea625d43
location: apps/web/src/screens/ScanScreen.tsx (enableCamera)
source_spec: `spec-3-1-capture-or-upload-a-scan.md`
severity: low
reason: If the OS/browser revokes camera access or the hardware disconnects while `cameraState` is `'granted'`, the viewfinder would show a frozen/black frame with no state change and no user-facing message. EXPERIENCE.md's State Patterns table doesn't call for this case, and it's rare in practice.
status: open

### DW-214: `POST /scans` computes the server-side crop via `crop_to_rect` purely to validate it, then discards the cropped image — no consumer exists until Story 3.3/3.4.
origin: spec-deferred 79b14eea4615
location: apps/api/api/scan.py
source_spec: `spec-3-2-crop-before-submit.md`
severity: low
reason: `apps/api/api/scan.py`'s `submit_scan` calls `shared_vision.crop_to_rect(...)` and never assigns or uses the returned `Image`. Every valid request pays for a real PIL crop of a decoded, up-to-2048px-capped image with the result thrown away. Deliberate per this story's own scope (no persistence, no matching yet), but worth revisiting once 3.3/3.4 give the result a consumer.
status: open

### DW-215: Sign Out is not disabled while a scan submission is in flight, so a tap could unmount `CropScreen` mid-request.
origin: spec-deferred eeec5e8d3ec7
location: apps/web/src/screens/CropScreen.tsx
source_spec: `spec-3-2-crop-before-submit.md`
severity: low
reason: `AppShell`'s Sign Out control is not told about `CropScreen`'s `confirming` state. This mirrors a pre-existing pattern across other in-flight admin actions in the app (none of them disable Sign Out either), so it is not unique to this story.
status: open

### DW-216: `apiRequest`'s widened `204 || 202` no-body handling is global rather than scoped to `/scans`.
origin: spec-deferred 0379bde2347c
location: apps/web/src/api/client.ts
source_spec: `spec-3-2-crop-before-submit.md`
severity: low
reason: A future endpoint that legitimately returns `202` with a real JSON body would have that body silently discarded by `apiRequest`. The only current `202` caller (`POST /scans`) is genuinely bodyless, so there is no live bug today.
status: open

### DW-217: `apps/api/api/scan.py` imports `catalogue._read_upload`, a leading-underscore "module-private" helper, across module boundaries.
origin: spec-deferred adba0a133f48
location: apps/api/api/scan.py
source_spec: `spec-3-2-crop-before-submit.md`
severity: low
reason: Reuse is well-motivated (avoids a second read-bytes implementation) and was the spec's own suggested approach, but the naming still signals "not for external use" and invites future drift; a public, unprefixed helper would match the intent better.
status: open

### DW-218: `scan.test.tsx`'s `stubFetchWithCalls` duplicates most of the existing `stubFetch` helper's shape (queue draining, default-404 fallback, response shape) instead of extending it to optionally capture
origin: spec-deferred 0144d8a07bfa
location: apps/web/src/__tests__/scan.test.tsx
source_spec: `spec-3-2-crop-before-submit.md`
severity: low
reason: Two near-identical fetch stubs now exist in the same test file and can drift out of sync with each other over time. Low risk, test-code only.
status: open

### DW-219: `CropScreen`'s `rect` state is not reset in response to the `image` prop changing, and no `key` is passed to force a remount.
origin: spec-deferred 62946672e8d4
location: apps/web/src/screens/CropScreen.tsx
source_spec: `spec-3-2-crop-before-submit.md`
severity: low
reason: Currently safe only because `App.tsx` always fully unmounts and remounts `CropScreen` between photos (no code path holds it mounted across two different `image` values), but nothing in `CropScreen` itself guards against that assumption changing later.
status: open

### DW-220: `onDragMove` does not stop an already-active drag when a submission begins mid-gesture, only `beginDrag` checks `confirming`.
origin: spec-deferred e4cee0d7a7a0
location: apps/web/src/screens/CropScreen.tsx
source_spec: `spec-3-2-crop-before-submit.md`
severity: low
reason: A very tight multi-touch race (one finger still dragging while another taps Confirm) could let `rect` keep changing after submission starts. Low probability and low impact — the submitted rect is read once at confirm time, not re-read after.
status: open

### DW-221: The crop selector's drag handles have no keyboard alternative (no `tabIndex`/`role`/arrow-key nudging) for a Staff/Admin user who cannot use touch or a mouse drag.
origin: spec-deferred 424fde35890e
location: apps/web/src/screens/CropScreen.tsx
source_spec: `spec-3-2-crop-before-submit.md`
severity: low
reason: Verified against the source of truth: epics.md's UX-DR17 scopes "visible focus states with a keyboard path" explicitly to "all admin surfaces," not the mobile-first Scan/Crop flow — the touch-target-size half of the same accessibility floor (which this screen does meet) is the only part stated for mobile surfaces. This is a legitimate future accessibility improvement, not a violation of a stated AC.
status: open

### DW-222: `blur_score`'s variance-of-Laplacian metric cannot detect blur in genuinely low-high-frequency content, so a sharp, correctly-framed photo of a real catalogue category (Mono Colour tiles, and
origin: spec-deferred 446dc7dc0d10
location: shared/vision/shared_vision/quality.py
source_spec: `spec-3-3-capture-quality-guidance.md`
severity: high
reason: Measured directly against `shared_vision.quality.blur_score`: a flat 180x160x140 tile re-photographed with realistic sensor noise (sigma 1-3, typical of a well-lit low-ISO phone shot) and JPEG-encoded at quality 75-92 scores 0.0-26.0, versus the provisional `DEFAULT_SCAN_QUALITY_THRESHOLD` of 100.0 -- it only clears the bound once whole-frame noise reaches sigma>=5 (q92) or sigma>=8 (q75), noise levels not guaranteed in good lighting. A synthetic smooth-gradient tile (no fine texture, only large-scale colour variation -- the Crema Marmol shape) scored 0.25 whether left sharp or run through a radius-20 Gaussian blur: the metric is completely insensitive to focus for this content family, in either direction. This is a structural property of any no-reference, high-frequency-energy blur metric applied to inherently low-texture subjects, not a tunable-threshold problem -- no single `SCAN_QUALITY_THRESHOLD` value can both catch real blur on textured tiles and pass real flat/smooth tiles,
status: open
