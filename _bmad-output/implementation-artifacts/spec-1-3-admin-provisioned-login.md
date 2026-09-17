---
title: 'Story 1.3 — Admin-Provisioned Login'
type: 'feature'
created: '2026-09-17'
baseline_revision: '4b837ab123020597520c0c6c6b54fbc2572d3273'
status: 'done'
review_loop_iteration: 0
followup_review_recommended: true # score 17 (1x3 medium + 14x1 low); see Auto Run Result
context:
  - '{project-root}/AGENTS.md'
  - '{project-root}/_bmad-output/planning-artifacts/architecture/architecture-rcl_camera_app-2026-08-30/ARCHITECTURE-SPINE.md'
  - '{project-root}/_bmad-output/planning-artifacts/ux-designs/ux-rcl_camera_app-2026-09-08/EXPERIENCE.md'
warnings: ['oversized']
deferred:
  - summary: >-
      `/health` answers 200 against an unreachable or wrong database, and
      `PoolTimeout`/`OperationalError` surface as a generic 500 rather than a
      503, so `make dev`'s health gate can pass against a database that does
      not exist.
    evidence: |-
      apps/api/api/db.py opens the pool with POOL_MIN_SIZE = 0 and
      pool.open(wait=False), so no connection is attempted at startup, and
      /health in api/main.py deliberately touches nothing. The startup guard
      catches an *unset* DATABASE_URL only. Adding a readiness endpoint and a
      503 mapping (main.py's STATUS_CODES has no 503 entry) means choosing
      probe semantics and a Retry-After policy, which is a deployment decision
      the architecture spine still lists as open.
    location: >-
      apps/api/api/db.py
    severity: medium
  - summary: >-
      The connection pool's max size is smaller than Starlette's sync
      threadpool, so concurrent logins can each allocate a 64 MiB Argon2id hash
      while most of them queue for a connection and then time out.
    evidence: |-
      apps/api/api/db.py sets POOL_MAX_SIZE = 10; FastAPI runs the sync `login`
      handler in a threadpool defaulting to 40 workers, and the endpoint is
      unauthenticated. Bounding this is login throttling, which epics.md
      assigns to Story 1.6 over AD-8's Postgres counters, so the fix belongs
      with that story rather than as a drive-by limit here.
    location: >-
      apps/api/api/db.py
    severity: medium
  - summary: >-
      `apps/api/tests/conftest.py` duplicates ~110 lines of
      `infra/tests/conftest.py`'s initdb/pg_ctl cluster handling, and the two
      copies must now be changed in lockstep with nothing enforcing it.
    evidence: |-
      Both files carry their own _free_port, _with_database and
      _start_ephemeral_cluster. The standard fix is an importable test-support
      module referenced through pytest_plugins, or a root conftest.py — either
      one relocates Story 1.2's fixtures, which is a test-layout decision
      rather than a patch to this story's code.
    location: >-
      apps/api/tests/conftest.py
    severity: low
  - summary: >-
      `POST /auth/login` has no CSRF defence, so a cross-site form post can
      sign a victim's browser into an attacker-controlled account.
    evidence: |-
      SameSite=Strict protects the authenticated routes but not login itself,
      which is unauthenticated by definition. Subsequent scans would then be
      attributed to the attacker's account. For an internal-only tool this may
      be an acceptable risk, but unlike every other security decision in this
      change it is currently neither mitigated nor written down; the
      independent penetration test AGENTS.md requires will raise it.
    location: >-
      apps/api/api/auth.py
    severity: low
  - summary: >-
      `apps/web` never revalidates a session the server has stopped honouring,
      so the shell keeps rendering after an expiry or a deactivation until the
      page is reloaded.
    evidence: |-
      SessionProvider bootstraps once on mount and changes status only on an
      explicit sign-in or sign-out. EXPERIENCE.md line 90 owes a "session
      expired mid-flow" pattern, and epics.md Story 1.5 owns session
      persistence and expiry, so the revalidation trigger belongs there. No
      other authenticated route exists yet, so nothing observes the gap today.
    location: >-
      apps/web/src/auth/SessionProvider.tsx
    severity: low
  - summary: >-
      The API sets no security response headers at all, so the login screen —
      the product's only unauthenticated surface — can be framed, and no
      response carries `X-Content-Type-Options` or a `Referrer-Policy`.
    evidence: |-
      apps/api/api/main.py installs four exception handlers and no middleware.
      A clickjacking overlay over the sign-in form is free, and a MIME sniff on
      any response is unrestricted. The fix is one middleware, but its content
      is a deployment decision rather than a drive-by: apps/web is served as
      static files by something other than this API, so `frame-ancestors`
      belongs to that server, and a CSP needs the web app's real script and
      style sources — which Vite's dev server and a production build do not
      agree about yet. DW-4's unresolved production path is the same decision.
    location: >-
      apps/api/api/main.py
    severity: medium
  - summary: >-
      The whole apps/api database suite skips itself where PostgreSQL is
      absent, so `make test` reports green with zero coverage of login,
      logout, session lookup and the seeded-administrator composition.
    evidence: |-
      apps/api/tests/conftest.py calls pytest.skip from a session-scoped
      fixture when initdb/pg_ctl are not on PATH, mirroring the pattern
      infra/tests/conftest.py established in Story 1.2. On this machine all
      320 tests run, but a CI image without PostgreSQL would report success
      for a suite that asserted nothing about the story. Fixing it means
      choosing a policy — an opt-in REQUIRE_POSTGRES that fails instead of
      skipping, or a floor on how many database tests must have run — and
      applying it to both packages at once, which is the same test-layout
      decision the conftest-duplication entry above is waiting on.
    location: >-
      apps/api/tests/conftest.py
    severity: medium
---

<intent-contract>

## Intent

**Problem:** Story 1.2 put a `users` table and one seeded Administrator in Postgres, but nothing can authenticate against them: `apps/api` serves only `/health`, `apps/web` renders a static shell, and there is no `sessions` table, no cookie, and no login screen. Epic 1 is the security spine and everything after it needs an authenticated caller.

**Approach:** Add the credential-verification path end to end — a `sessions` migration, one shared session-lookup function in `apps/api` (AD-3), `POST /auth/login` / `GET /auth/session` / `POST /auth/logout`, and a chrome-less login screen in `apps/web` that gates the existing `AppShell`. Rejection is uniform and says nothing about which field was wrong or whether the account exists. No registration surface is created, and a guard test asserts none exists anywhere.

## Boundaries & Constraints

**Always:**
- Argon2id verification only, through `shared_schema.passwords` — never a second hasher (AGENTS.md Policy; see `shared/schema/shared_schema/passwords.py` docstring).
- The session token exists only in an HTTP-only, Secure, SameSite=Strict, Path=/ cookie and is stored hashed at rest. Never in `localStorage`/`sessionStorage`, never in a response body, never readable by page script (AGENTS.md Policy, AD-3, ERD `SESSION.token_hash`).
- Exactly ONE session-lookup function for the whole service (AD-3). It re-reads `role` and `active` from Postgres on every call and caches nothing from login time.
- Every failed login answers with the same status, the same envelope code, the same message and a comparable response time — wrong password, unknown email, deactivated account and expired temporary credential are indistinguishable to the caller (epics.md Story 1.3 AC; EXPERIENCE.md:92; DW-24).
- Parameterized SQL only. No string-concatenated or f-string-interpolated SQL (AGENTS.md Policy).
- All errors use the existing envelope `{"error": {"code", "message"}}` via `ApiError` (`shared/schema/shared_schema/errors.py`).
- Every value in new `apps/web` CSS comes from `src/styles/tokens.css` (UX-DR1) — the `no-raw-values` guard enforces this.
- Migrations are forward-only, reversible, and never edit an applied one (AGENTS.md Conventions; `infra/README.md`).
- No new secret, password or connection string is committed, including in fixtures.

**Block If:**
- The `sessions` schema cannot be built without changing `infra/migrations/20260917T1200_create_users.up.sql` (an applied migration).
- Closing the timing side-channel would require a second `PasswordHasher` outside `shared/schema`.

**Never:**
- A registration or sign-up endpoint, route, form, link or copy — anywhere in the product (FR-1).
- Progressive delay, failed-attempt counters or lockout (Story 1.6 / AD-8) — this story adds none of AD-8's counters.
- Audit-log writes (Story 1.12) — record the gap in a comment, do not build a private log path.
- The forced-password-change screen or its navigation trap (Story 1.4) — login issues a session for a `must_change_password` user and returns that flag; gating is 1.4's.
- Sliding inactivity renewal, the 12-hour idle window, session listing or bulk revocation (Story 1.5).
- A router library (`react-router` or similar) — the shell split is a conditional render; adding a routing dependency is Story 1.4's decision to take with navigation trapping.
- Any password-strength, reset or change endpoint (Stories 1.4 / 1.7).
- Returning `password_hash`, `id` of another user, or any field beyond the shared `User` contract.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Successful login | `POST /auth/login` with the correct email (any case) and password for an active account | `200` with the shared `User` body; a `Set-Cookie` carrying HttpOnly, Secure, SameSite=Strict, Path=/, Max-Age; one new `sessions` row whose `token_hash` is not the cookie value; `users.last_login_at`/`updated_at` advanced | No error expected |
| Unknown email | `POST /auth/login`, no matching `lower(email)` | `401`, code `unauthorized`, the one generic message, no cookie, no session row | Decoy Argon2id verify runs so the response time matches a wrong-password rejection |
| Wrong password | correct email, wrong password | Byte-identical body and status to the unknown-email case | Same |
| Deactivated account | correct credentials, `active = false` | Byte-identical body and status to the unknown-email case | Same |
| Expired temporary credential | correct credentials, `must_change_password = true` and `temp_credential_expires_at < now()` | Byte-identical body and status to the unknown-email case (AGENTS.md: temporary credentials expire at 72h) | Same |
| Unclaimed temporary credential, still valid | correct credentials, `must_change_password = true`, expiry in the future | `200`, session issued, `must_change_password: true` in the body for Story 1.4 to act on | No error expected |
| Malformed body | missing/blank `email` or `password`, or a password over `MAX_PASSWORD_LENGTH` | `422` validation envelope, or `401` generic — never a message naming the offending field's value; nothing hashed for an oversized candidate | Existing `validation_error_handler` |
| Session read, signed in | `GET /auth/session` with a valid cookie | `200` with the current `User`, `role` and `active` read fresh from Postgres | No error expected |
| Session read, no or invalid cookie | missing cookie, unknown token, `expires_at < now()`, or the owner deactivated | `401` generic; any stale cookie is cleared on the response | Expired or orphaned row deleted or ignored, never resurrected |
| Logout | `POST /auth/logout` with a valid cookie | `204`, the session row deleted, the cookie cleared; a second call is still `204` | Idempotent |
| Registration probe | `POST /auth/register`, `/register`, `/signup` | `404` — no such route exists in the app's route table | Existing routing envelope |
| Login screen submit failure | web form submits, API answers `401` | Inline error text in `--color-destructive`, announced to assistive tech, focus kept in the form, password field cleared, email retained | Network failure shows the same inline slot with a factual message |

</intent-contract>

## Code Map

**Read-only sources of truth (do not edit):**
- `_bmad-output/planning-artifacts/architecture/architecture-rcl_camera_app-2026-08-30/ARCHITECTURE-SPINE.md` — **AD-3** lines 58–62 (one shared session lookup; Postgres rows; role/active re-read per request; HttpOnly/Secure/SameSite=Strict cookie); **AD-6** lines 76–80 (web holds no DB credential); **AD-8** lines 88–92 (failed-login counters are Story 1.6, not here); **SESSION** ERD lines 243–249 = `uuid id`, `uuid user_id`, `string token_hash`, `timestamp issued_at`, `timestamp expires_at`; **USER** ERD lines 236–242; Consistency Conventions lines 166–173 (UUIDv4, ISO 8601 UTC, the error envelope, per-request server-side role re-verification). The spine fixes **no** endpoint prefix or versioning scheme — `/health` sets the precedent of a bare path.
- `AGENTS.md` — Policy lines 8–24: Argon2id only; server-side authz on every endpoint; session tokens only in HttpOnly/Secure/SameSite=Strict cookies; parameterized SQL; no committed secrets; temporary credentials expire at 72 hours; rate limiting is named but delivered by 1.6.
- `_bmad-output/planning-artifacts/epics.md` lines 205–216 — Story 1.3's acceptance clauses verbatim; lines 231–243 (1.5 owns lifetimes), 244–256 (1.6 owns throttling), 219–230 (1.4 owns the forced change), 322–334 (1.12 owns audit).
- `_bmad-output/planning-artifacts/prds/prd-rcl_camera_app-2026-08-25/prd.md` lines 85–91 (FR-1: no registration endpoint or UI, no social login), lines 101–109 (FR-3 bounds, owned by 1.5), FR-10 (last login is admin-visible — this story is what sets it).
- `_bmad-output/planning-artifacts/ux-designs/ux-rcl_camera_app-2026-09-08/EXPERIENCE.md` — line 24 (Login IA row: email/password, unauthenticated); line 92 (**deactivated account gets the same generic rejection as a wrong password**); line 93 (lockout is a *different* message with no countdown — Story 1.6); lines 50–57 (voice: short, factual, no exclamation marks, no "Oops!"); lines 105–113 (UX-DR17 accessibility floor). `DESIGN.md` line 207 (**the app bar appears on authenticated screens only** — login renders no chrome), line 219 (force-password-change is "the only thing on screen" — the nearest specified precedent for login's shape; inline error text in `{colors.destructive}`), lines 172–182 (navy on orange 5.94:1; white on orange is banned). **There is no login mockup and no specified login microcopy** — author it under the tone rules.
- `_bmad-output/implementation-artifacts/deferred-work.md` — **DW-24** (lines 185–191) says in terms that *"Story 1.3 owns the decision"* on the login timing side-channel and that the fix belongs in `shared/schema`, not `apps/api`. **DW-4** (lines 31–37) flags the dev proxy running plain HTTP against a `Secure` cookie. **DW-17** (lines 129–135): `users.updated_at` has no trigger, so this story's write must set it by hand.

**Files that already exist and constrain the shape:**
- `apps/api/api/main.py` — `create_app()` installs four exception handlers and the `/health` route; `STATUS_CODES` already maps `401 → "unauthorized"`. Docs/OpenAPI are off. **Routes are declared inside `create_app`**; a router for auth must be included there, and the app currently has no lifespan, no database and no dependency wiring — this story adds the first of each.
- `shared/schema/shared_schema/passwords.py` — `hash_password` / `verify_password`, `MIN_PASSWORD_LENGTH = 12`, `MAX_PASSWORD_LENGTH = 128`, `ARGON2ID_PREFIX`, one module-level `_HASHER` with pinned RFC 9106 parameters. `verify_password` already returns `False` for an empty or oversized candidate **before** hashing. The decoy path joins this module — nowhere else.
- `shared/schema/shared_schema/user.py` + `ts/user.ts` — the ten-key `User` contract, closed shape, `password_hash` absent by construction, timestamps serialized to UTC. **This is the login response body; no new shared type is needed.** `ts/user.ts` exports `isUser`, `isRole`, `isUuid`, `isUtcTimestamp`, `USER_KEYS`.
- `shared/schema/shared_schema/errors.py` + `ts/errors.ts` — `ApiError(code, message, status_code, headers)` and `isErrorEnvelope`; `ApiError` refuses an empty code/message and a non-4xx/5xx status.
- `infra/migrations/20260917T1200_create_users.up.sql` — `users` columns and the `users_email_lower_key` unique index on `lower(email)`; `email` is stored lowercase and `CHECK (email = lower(email))`. **Login must lowercase the submitted address before lookup.**
- `infra/rocell_infra/migrate.py` — `VERSION_PATTERN` (`^\d{8}T\d{4}_[a-z0-9]+(?:_[a-z0-9]+)*$`), `UP_SUFFIX`/`DOWN_SUFFIX`, lexicographic discovery, one transaction per migration, `PYTHON_DIRECTIVE` for non-SQL steps. A plain-SQL pair needs no runner change; `MIGRATIONS_DIR` is resolved from the package.
- `infra/tests/conftest.py` — `maintenance_url` (session), `database_url` (a fresh empty database per test), `conn` (autocommit). **`apps/api` tests need the same fixtures**; they live in `infra/tests/conftest.py` and are not visible to `apps/api/tests`.
- `apps/api/pyproject.toml` — depends on `fastapi`, `shared-schema`, `uvicorn`; no driver. `infra/pyproject.toml` shows the `psycopg[binary]>=3.2` precedent.
- `pyproject.toml` (root) — `testpaths` already lists `apps/api/tests`; `[tool.ruff.lint] select = ["E","F","I","UP","B"]`; dev group has `httpx` and `pytest`.
- `apps/web/src/App.tsx` — renders `<AppShell>` with a static heading; **this becomes the authenticated branch**.
- `apps/web/src/components/AppShell.tsx` / `.module.css` — the frame; its docstring already says nav "cannot exist before authentication does" and names Story 1.3.
- `apps/web/src/components/AppBar.tsx` — no props today; sized from `--icon-size`, Phosphor icons at default weight (a guard test fails on a `weight` prop).
- `apps/web/src/__tests__/app-shell.test.tsx` — **renders `<App />` and asserts the app bar is present.** Once `App` gates on authentication this test is wrong as written: repoint it at `<AppShell>` directly (it is a shell test) and cover the gating separately.
- `apps/web/src/__tests__/no-raw-values.test.ts` — walks every file under `src` except `styles/tokens.css` and fails on a colour or length literal. `styling-wiring.test.ts` additionally checks that every `styles.x` reference resolves to a real class and that rules point at the intended token.
- `apps/web/src/styles/tokens.css` — the only file allowed to hold literals; already carries `--color-surface`, `--color-border`, `--color-destructive`, `--color-accent`, `--color-accent-foreground`, `--radius-sm`, `--touch-target-min`, `--focus-ring-width`, the six type roles and the spacing scale. Derived tokens are explicitly allowed ("Adding a token is fine; contradicting a DESIGN.md value is not"); `tokens.test.ts` asserts only that DESIGN.md's values are present, so a new derived token is safe.
- `apps/web/vite.config.ts` — dev proxy `/api/*` → `http://127.0.0.1:$API_PORT/*` with the prefix **rewritten away**, so the browser calls `/api/auth/login` and the API serves `/auth/login`. `test.environment = 'jsdom'`, `restoreMocks: true`.
- `apps/web/src/styles/global.css` — already gives `button`, `[role=button]`, `select`, `summary`, `.touchTarget` and every non-checkbox `input` the 44px floor, and `:focus-visible` an accent ring. A new form inherits all of it; do not restate it.
- `README.md` §"The database" (line 47) and `infra/README.md` — the operator-facing pages that must learn about `sessions` and the new `DATABASE_URL` requirement for `make dev`.

**Verified environment facts (probed 2026-09-17):**
- `uv pip install --dry-run "psycopg[pool]>=3.2"` resolves `psycopg-pool==3.3.1` cleanly — the one new runtime dependency (`apps/api` also gains `psycopg[binary]`, already proven in `infra`).
- PostgreSQL 16.15 is on PATH; the ephemeral-cluster fixture in `infra/tests/conftest.py` works and is the model for the API's database tests.

## Tasks & Acceptance

**Execution:**

- `shared/schema/shared_schema/passwords.py` — add `verify_dummy_password(password: str) -> bool`, always `False`, verifying against a lazily-built module-level decoy digest of a runtime-generated random password. Closes **DW-24** where the ledger says it belongs, so `apps/api` never needs a second `PasswordHasher`. Lazy, not import-time: a 64 MiB Argon2id hash on import would tax every process and every test run that touches `shared_schema`.
- `shared/schema/shared_schema/__init__.py` — re-export `verify_dummy_password` and extend `__all__` — one import surface, as `hash_password`/`verify_password` already are.
- `shared/schema/tests/test_passwords.py` — extend: the decoy returns `False` for every input including the empty and oversized cases, the digest carries `ARGON2ID_PREFIX` and the same pinned parameters as `hash_password` (a cheap decoy would defeat its purpose), and repeated calls reuse one digest rather than rebuilding it.
- `infra/migrations/20260917T1300_create_sessions.up.sql` / `.down.sql` — create `sessions` (`id uuid primary key default gen_random_uuid()`, `user_id uuid not null references users(id) on delete cascade`, `token_hash text not null`, `issued_at timestamptz not null default now()`, `expires_at timestamptz not null`) plus a **unique** index on `token_hash` and an index on `user_id`; the down drops the table. The ERD's `SESSION` verbatim, nothing Story 1.5 owns. `ON DELETE CASCADE` is what makes deleting a user end their sessions rather than orphan them.
- `infra/README.md` — document the `sessions` migration under "Migrations", and that `apps/api` now needs the same `DATABASE_URL` — the operator page for a step no test performs.
- `apps/api/pyproject.toml` — add `psycopg[binary,pool]>=3.2` — flagged per AGENTS.md Conventions; the same driver `infra` already uses, plus the pool.
- `apps/api/api/db.py` — read `DATABASE_URL` from the environment (required; a named error naming the variable, never a default — a service that guesses a connection string can talk to the wrong database, the same rule `infra/rocell_infra/config.py` follows), open a `psycopg_pool.ConnectionPool` in the app lifespan, close it on shutdown, and expose a `get_connection` FastAPI dependency yielding one connection. `apps/web` never sees any of this (AD-6).
- `apps/api/api/sessions.py` — the session module: `SESSION_COOKIE_NAME`, the cookie attribute set (HttpOnly, Secure, SameSite=Strict, Path=/), `SESSION_ABSOLUTE_LIFETIME` (7 days — the addendum's absolute bound; the 12-hour idle window is Story 1.5's and must not be implemented here), `issue_session(conn, user_id) -> raw_token`, `hash_token(raw)` (SHA-256 over a 256-bit `secrets.token_urlsafe` value — see Design Notes), `delete_session(conn, raw_token)`, and **the one** `lookup_session(conn, raw_token) -> User | None` that AD-3 requires: it joins `sessions` to `users`, rejects an expired row, rejects an inactive owner, and returns `role`/`active` as Postgres holds them *now*. Every future authenticated route calls this and nothing else.
- `apps/api/api/auth.py` — an `APIRouter` with `POST /auth/login`, `GET /auth/session`, `POST /auth/logout`. Login: a pydantic request model (`extra="forbid"`), lowercase the email, one indexed lookup, then verify — and on **any** unusable outcome (no row, bad password, `active = false`, unclaimed credential past `temp_credential_expires_at`) call `verify_dummy_password` where no real verify ran and raise one shared `ApiError(401, "unauthorized", <the single message>)` built from a module-level constant so the four paths cannot drift apart. On success: `UPDATE users SET last_login_at = now(), updated_at = now()` (FR-10; `updated_at` by hand per DW-17), issue the session, set the cookie, return the `User`. Logout deletes the row and clears the cookie, idempotently.
- `apps/api/api/main.py` — install the lifespan from `db.py` and `include_router` the auth router; leave `/health` unauthenticated and the handler set untouched.
- `apps/api/tests/conftest.py` — the database fixtures for this package, mirroring `infra/tests/conftest.py`: reuse its ephemeral-cluster approach (skip with the same reason when PostgreSQL is absent), apply the real migrations through `rocell_infra.migrate` so the API is tested against the shipped schema rather than a hand-written copy, and create test users with `shared_schema.passwords.hash_password` and a **runtime-generated** password (no committed fixture secret).
- `apps/api/tests/test_login.py` — the I/O matrix's login rows. Critically: assert the unknown-email, wrong-password, deactivated and expired-credential responses are **identical** in status, body and headers; assert the `Set-Cookie` carries HttpOnly, Secure, SameSite=Strict and Path; assert the cookie value appears in no response body and is **not** the stored `token_hash`; assert exactly one `sessions` row; assert `last_login_at` advanced; assert a success for a valid unclaimed temporary credential.
- `apps/api/tests/test_session_lookup.py` — the shared lookup's failure cases: no cookie, unknown token, expired row, deactivated owner, and — the AD-3 property that matters — a role changed in Postgres after the session was issued is reflected on the very next `GET /auth/session`.
- `apps/api/tests/test_logout.py` — logout deletes the row, clears the cookie, is idempotent, and leaves other sessions of the same user alone.
- `apps/api/tests/test_no_registration.py` — FR-1 as a test: the app's route table contains no path or operation matching register/signup/join, `POST /auth/register` is `404`, and a source scan over `apps/api`, `apps/web/src` and `shared` finds no registration surface. This file must not match its own text.
- `apps/web/src/api/client.ts` — a small `fetch` wrapper for the `/api` prefix with `credentials: 'same-origin'`, parsing a failure through `isErrorEnvelope` and throwing a typed error carrying the envelope's `code`. One place that knows the prefix, so DW-4's unresolved production path is a one-line change later.
- `apps/web/src/auth/SessionProvider.tsx` — a context holding `User | null` plus a `status` of `loading | signed-out | signed-in`, bootstrapping from `GET /api/auth/session` on mount, and exposing `signIn(email, password)` and `signOut()`. The `User` type comes from `@rocell/schema/user` and every response is narrowed with `isUser` — a body that does not satisfy the contract is a failure, not a silent partial render.
- `apps/web/src/screens/LoginScreen.tsx` + `LoginScreen.module.css` — the chrome-less screen: no app bar, no nav (DESIGN.md:207), the product name, a labelled email field (`type="email"`, `autoComplete="username"`) and password field (`autoComplete="current-password"`), one primary accent submit button with navy foreground, a disabled/in-flight state, and one inline error region in `--color-destructive` carrying `role="alert"`. No "forgot password" link — reset goes through an Administrator (EXPERIENCE.md:32). Author the microcopy under the tone rules: short, factual, no exclamation marks; the rejection names neither the field nor the account's existence.
- `apps/web/src/styles/tokens.css` — add only the derived tokens the screen needs (e.g. a form measure) with a comment saying what they are derived from; contradicting a DESIGN.md value is forbidden.
- `apps/web/src/App.tsx` — wrap in `SessionProvider` and branch: `loading` → a quiet placeholder, `signed-out` → `LoginScreen`, `signed-in` → the existing `AppShell` content. Greet the signed-in user by name so the screen shows the session is real.
- `apps/web/src/components/AppBar.tsx` + `.module.css` — an optional sign-out control, rendered only when a handler is supplied, styled as a non-primary control (the single primary per screen is not this).
- `apps/web/src/__tests__/app-shell.test.tsx` — repoint at `<AppShell>` directly; it is a shell test and `App` no longer renders the shell unconditionally.
- `apps/web/src/__tests__/login-screen.test.tsx` — the screen's own behaviour: labels are associated with their inputs, the password input is `type="password"`, no app bar or nav is rendered, submitting calls the API once, a rejection renders the inline `role="alert"` message and clears only the password, the button is disabled while in flight, and the form is operable by keyboard alone.
- `apps/web/src/__tests__/auth-gating.test.tsx` — `App` renders the login screen while signed out, the shell after a successful sign-in, and the login screen again after sign-out; a failed bootstrap does not leave a blank page.
- `apps/web/src/__tests__/no-client-token-storage.test.ts` — a source scan proving `apps/web/src` never reads or writes `localStorage`, `sessionStorage`, `document.cookie` or IndexedDB (AGENTS.md Policy). The file must not match its own text.
- `README.md` — note that `make dev` now needs `DATABASE_URL` for `apps/api`, and that the session cookie is `Secure` (which browsers honour on `http://localhost`, so the dev proxy still works — DW-4).
- `Makefile` — `make dev`'s health gate prints "port busy, or an import error" for any early API exit, which is now untrue for the commonest one: a missing `DATABASE_URL`. Extend that message to name `DATABASE_URL` as a third cause, and add it to the `dev` line of `help`. `tests/test_make_targets.py` covers the target list, so keep the help block's column alignment intact.

**Acceptance Criteria:**
- Given the migrated database from Story 1.2 and a user with a known password, when `POST /auth/login` is called with that email in **mixed case** and the correct password, then it returns `200` with a body `isUser` accepts, and exactly one `sessions` row exists for that user.
- Given a successful login, when the response headers are inspected, then the session cookie carries `HttpOnly`, `Secure`, `SameSite=Strict` and `Path=/`, and the cookie's value equals no column stored in `sessions`.
- Given four rejection scenarios — unknown email, wrong password, deactivated account, and an unclaimed credential past `temp_credential_expires_at` — when each is submitted, then all four responses are identical in status code, body and headers, and none creates a session row.
- Given a signed-in session, when an Administrator changes that user's `role` or sets `active = false` directly in Postgres, then the very next `GET /auth/session` reflects the change without a new login (AD-3).
- Given a signed-in session, when `POST /auth/logout` is called and then `GET /auth/session`, then logout answers `204`, the row is gone, and the session read answers `401`.
- Given the repository, when it is searched for a registration surface, then `POST /auth/register` is `404`, the FastAPI route table holds no register/signup path, and no sign-up form, link or copy exists in `apps/web/src`.
- Given the repository, when `apps/web/src` is scanned, then no source file reads or writes `localStorage`, `sessionStorage`, `document.cookie` or IndexedDB.
- Given `grep` over the new code, when it is inspected, then no SQL is assembled by string concatenation or interpolation of a value, no password or connection string is committed in any test or fixture, and no second `PasswordHasher` exists outside `shared/schema/shared_schema/passwords.py`.
- Given the login screen rendered signed-out, when it is inspected, then it renders no app bar and no navigation, every input has an associated label, the submit button is the only primary action, and a rejection is exposed through an element with `role="alert"`.
- Given `make lint` and `make test` on a clean checkout, when both are run, then both exit 0.

## Spec Change Log

## Review Triage Log

### 2026-09-17 — Review pass

- intent_gap: 0
- bad_spec: 0
- patch: 13: (high 0, medium 4, low 9)
- defer: 2: (high 0, medium 2, low 0)
- reject: 11
- addressed_findings:
  - `[medium]` `[patch]` `_SELECT_CREDENTIAL` matched on `WHERE email = %s` while the only index on the column is the expression index `users_email_lower_key ON users (lower(email))` — which the planner will not use for a plain `email = $1`, CHECK constraint or not. Every sign-in attempt, valid or not, sequentially scanned `users` on the one endpoint reachable without a credential, and the comment above it asserted the opposite. Now `WHERE lower(email) = %s`, with the comment saying why.
  - `[medium]` `[patch]` `apiRequest` cleared its abort timer in the `finally` attached to `fetch`, which runs when the *headers* arrive — so the body read at the next line was unguarded. A response that opens and then stalls mid-stream is precisely the hung-proxy case `REQUEST_TIMEOUT_MS` exists for, and it left the bootstrap on "Checking your session…" forever. The timer now spans the body read, an abort there reports as `TIMEOUT`, and a stalled-body test drives it.
  - `[medium]` `[patch]` The web client's `content-type: application/json` header was asserted nowhere — not in `api-client.test.ts`, whose helpers ignore `init` beyond `signal`, nor in the gating test that checks method and body. Deleted, `fetch` labels a string body `text/plain` and this API's request model answers 422 to every sign-in in the product, with both suites green. Asserted now in both places.
  - `[medium]` `[patch]` `delete_expired_sessions` ran an unbounded table-wide `DELETE` *inside* the login transaction, so concurrent sign-ins queued on each other's row locks and one unlucky login paid to drain a whole outage's backlog. Moved outside the transaction and bounded — `FOR UPDATE SKIP LOCKED` with a `LIMIT`, so concurrent sweeps take disjoint rows.
  - `[low]` `[patch]` An email containing a NUL byte reached psycopg, which refuses to send one, so that one input class answered 500 where every other answers 401 — the account-existence oracle in a different costume. Confirmed by removing the guard and watching `test_every_rejection_is_indistinguishable` fail on `psycopg.DataError`. Control characters are now refused before the query, through the same decoy work and the same rejection, and the case joins the byte-for-byte rejection comparison.
  - `[low]` `[patch]` Neither auth response carried `Cache-Control: no-store`, although both return a user's name, address and role and `GET /auth/session` is a plain GET — heuristically cacheable by any intermediary and by this PWA's eventual service worker. Added to both and asserted.
  - `[low]` `[patch]` Signing in again overwrote the cookie and left the previous session row live for the rest of its seven days, reachable by nobody: the browser can no longer present it, logout revokes only the cookie it is given, and bulk revocation is Story 1.5's. Login now spends the token it was presented with. Two tests: the old row goes, another device's session stays.
  - `[low]` `[patch]` The session cookie's `Max-Age` was asserted only as a substring, so `Max-Age=7` passed — the browser would drop the cookie seconds after sign-in while the row behind it stayed valid for a week, and the server would see only a missing cookie. The value is now pinned to `SESSION_ABSOLUTE_LIFETIME`.
  - `[low]` `[patch]` `sessions_token_hash_key`'s uniqueness — which the migration's own comment calls load-bearing, and which `lookup_session` and `delete_session` are both written assuming — was asserted nowhere; downgrading it to a plain index kept every test green. A duplicate-insert test now mirrors `users`'.
  - `[low]` `[patch]` The acceptance clause "Given `grep` over the new code … no SQL is assembled by string concatenation or interpolation of a value … and no second `PasswordHasher` exists outside `shared/schema`" was discharged by eye only. `test_source_guards.py` now discharges it on every run, plus AD-3's "exactly one session-lookup function", with the patterns proven against known-bad and known-good lines and a test that the scan still reaches the files it claims to.
  - `[low]` `[patch]` `LoginScreen` cleared the password and pulled focus to it on *every* failure, including a timeout or an unreachable server — contradicting the `fields: []` the same branch had just reported to assistive technology, and making a user retype a correct password because the Wi-Fi dropped. Both are now conditional on the credential actually having been refused.
  - `[low]` `[patch]` The bootstrap placeholder put `role="status"` on its `<main>`. An explicit role replaces the implicit one, so the page had no main landmark for the whole of the session check. The role moved to the paragraph; a test asserts both the landmark and the announcement.
  - `[low]` `[patch]` `MAX_EMAIL_LENGTH` was the only thing keeping a megabyte of text out of the credential query and no test submitted an over-length address, so the bound could be deleted silently. Covered.

### 2026-09-17 — Review pass

- intent_gap: 0
- bad_spec: 0
- patch: 22: (high 0, medium 7, low 15)
- defer: 5: (high 0, medium 2, low 3)
- reject: 8
- addressed_findings:
  - `[medium]` `[patch]` `verify_password` deliberately raises `InvalidHashError` for a malformed stored digest, and `login` called it unguarded — an account with a corrupt `password_hash` answered 500 where every other account answers 401, which is precisely the account-existence oracle the story's acceptance clause forbids. Caught, logged at error level as the data-integrity fault it is, and rejected generically; "corrupt stored digest" is now one of the cases the byte-for-byte rejection comparison covers.
  - `[medium]` `[patch]` `credential_expired` was false when `temp_credential_expires_at` was NULL, so an account with `must_change_password = true` and no expiry held a temporary credential that never expired — a reachable row shape, since the flag defaults true and the column is nullable. It now fails closed, with a mirror test proving a *claimed* account (NULL expiry, flag false) still signs in.
  - `[medium]` `[patch]` `apps/api/api/db.py` was entirely untested while four documents promised the API exits at startup naming `DATABASE_URL`, and the autouse fixture in `apps/api/tests/conftest.py` made that path unreachable from the suite. `test_db.py` now drives `database_url()` against explicit environment mappings, including the blank and whitespace cases, and asserts no connection string is substituted.
  - `[medium]` `[patch]` Story 1.3's acceptance clause opens "Given an account exists — either the Administrator seeded in Story 1.2 …", and every test signed in as a hand-inserted row: the 1.2 → 1.3 composition was covered by prose only. `test_seeded_login.py` now applies the full migration set with runtime-generated `SEED_ADMIN_*` and signs in as the seeded Administrator over HTTP.
  - `[medium]` `[patch]` `signOut()` used `try/finally` with no `catch`, so a failed logout cleared local state *and* re-threw into a discarded promise — the user saw the login screen while the browser still held a valid, un-revoked cookie and a reload signed them straight back in. State is now cleared only after the revocation lands, and the failure is surfaced.
  - `[medium]` `[patch]` The login form is `noValidate`, which disables its own `required` attributes, so a blank submit reached the API and the user was shown `validation_error_handler`'s "The request was not in the expected shape." Empty fields are refused client-side with factual copy, and `LoginScreen` now branches on the envelope's `code` — which `client.ts` says is the point of carrying it, and which left the exported `UNAUTHORIZED` constant dead.
  - `[medium]` `[patch]` The web tests' `fetch` stub keyed replies on the URL alone and asserted no method or body, so deleting `{ method: 'POST' }` from the logout call — or the call itself — kept the suite green while the product's only server-side session revocation stopped happening. Method, path and parsed body are now asserted on both auth calls.
  - `[low]` `[patch]` Neither 401 carried `WWW-Authenticate`, although `api/main.py`, `shared_schema/errors.py` and `test_error_envelope.py` all say a 401 is meaningless without it — the one story that produces 401s was the one omitting the header. Added to both rejection paths, merged with the cookie clearance rather than overwriting it.
  - `[low]` `[patch]` `_RECORD_LOGIN`'s `fetchone()` could return `None` if the row was deleted between the credential read and the update, and `User.model_validate(None)` then raised a 500 after a session had been issued. Guarded, inside the transaction, so the rollback is clean.
  - `[low]` `[patch]` `delete_expired_sessions` runs on every login and `expires_at` was unindexed, so each sign-in sequentially scanned `sessions` and held the resulting locks inside the login transaction. `sessions_expires_at_idx` added to the (not yet shipped) migration and dropped in its `down`.
  - `[low]` `[patch]` `lookup_session` is the one function AD-3 says every future authenticated route will call, and it returned a `must_change_password` user with no signal — nothing is exposed today, but the next route added before Story 1.4 lands would inherit the hole silently. An explicit obligation block now names 1.4 as the owner.
  - `[low]` `[patch]` `_decoy_digest()` had no lock, and FastAPI runs sync endpoints in a threadpool, so two concurrent first-rejections could each allocate a 64 MiB Argon2id hash. Double-checked locking, with a four-thread barrier test asserting object identity.
  - `[low]` `[patch]` `aria-invalid` was driven by `error !== null`, so both inputs were reported malformed for any failure — including an unreachable server, where nothing the user typed was at fault. It is now driven by which fields are actually implicated.
  - `[low]` `[patch]` The gate swapped `LoginScreen` for `AppShell` as a bare conditional render, unmounting the focused control and dropping focus to `<body>` on both transitions; the loading placeholder carried `aria-busy` with no live region, so "Checking your session…" was never announced. Focus now moves to the main region on a screen swap, and the placeholder is a `role="status"`.
  - `[low]` `[patch]` `apiRequest` had no timeout, so a hung proxy left the bootstrap on "Checking your session…" indefinitely. An `AbortController` timeout surfaces under its own code, with the timer cleared in `finally` and a fake-timer test for the invariant.
  - `[low]` `[patch]` `migrated_url` excluded the seed migration by the substring `"seed"`, which would silently skip any future migration whose version contained it and test the API against a schema the product does not ship. It now filters on the exact version and asserts the filter removed one, so a rename is loud.
  - `[low]` `[patch]` Deleting the `warm_password_verifier()` call from the lifespan left every test green while reintroducing a once-per-process timing difference on the unknown-address path. The lifespan's effect is now asserted.
  - `[low]` `[patch]` No test named `delete_expired_sessions`, so making it a no-op stayed green while the table grew one dead row per sign-in forever. A seeded expired row — including one belonging to another user — is now asserted gone after a login.
  - `[low]` `[patch]` Repointing `app-shell.test.tsx` at `<AppShell>` dropped the `render(<App />)` console-error guard, so React warnings from the root composition no longer failed the suite. Restored in `auth-gating.test.tsx` around a full sign-out → sign-in cycle.
  - `[low]` `[patch]` The acceptance clause says no registration surface exists "anywhere in the product", and the source scan covered three directories — leaving `apps/web/index.html`, the rest of `apps/web`, `infra/` and `scripts/` unscanned. Widened to 70 files, with lockfiles skipped for a stated reason.
  - `[low]` `[patch]` The rejection test's comment claimed `Date` and `Content-Length` were both excluded from the header comparison while the code dropped only `Date` — it described a tolerance the assertion does not grant.
  - `[low]` `[patch]` `apps/api/tests/conftest.py`'s docstring justified its duplication of the cluster fixtures by saying conftest fixtures cannot be shared across test packages, which is untrue — `pytest_plugins` over an importable helper is the standard fix. The docstring now states the real reason the duplication was left in place.

### 2026-09-17 — Review pass

- intent_gap: 0
- bad_spec: 0
- patch: 15: (high 0, medium 1, low 14)
- defer: 0
- reject: 12
- addressed_findings:
  - `[medium]` `[patch]` `delete_expired_sessions` ran *after* the login transaction committed but *before* the cookie was set, so a deadlock or a statement timeout in a table tidy-up answered 500 to a sign-in that had already happened — the row there, `last_login_at` moved, the user holding no cookie and the session behind it living out its week unreachable. The cookie is now set first and the sweep cannot fail the request it rides on; proven by making it raise.
  - `[low]` `[patch]` `verify_password` parses the stored digest before it hashes anything, so the corrupt-digest branch added last pass rejected having spent none of the ~100ms every other rejection costs. The four responses stay byte-identical either way, so nothing noticed: a corrupt row answered measurably faster than a wrong password, which tells a caller the account is there. The decoy now pays the difference, and the call is asserted rather than the response — the same blind spot `test_the_unknown_address_path_spends_a_real_verify` exists for.
  - `[low]` `[patch]` `Cache-Control: no-store` was on the two 200s only. The module comment calls it load-bearing, a 204 is cacheable by default, and a rejection says something about who is *not* signed in on this tablet — but the real cost was a header three of five responses carry being a header the sixth gets written without. Now on both `ApiError` factories and on logout, with all five asserted.
  - `[low]` `[patch]` The expiry sweep deleted by `ctid`. That is safe only while nothing ever `UPDATE`s a session row: an update moves the tuple, so the captured ctid names a different row by the time the DELETE runs, and VACUUM hands the slot out again. Story 1.5 owns sliding renewal, which is exactly `UPDATE sessions SET expires_at = ...`. Keyed on the primary key instead, which carries a LIMIT the same way and costs nothing.
  - `[low]` `[patch]` `apiRequest` returned a 2xx whose body would not parse as `null` — an empty success — while the comment above it claimed the envelope check below handled the case. That check only runs on a failure. A truncated stream or a proxy's HTML under a 200 read to the caller as "no user" rather than "the server is broken"; `SessionProvider`'s `isUser` happens to mask it today and the next endpoint would not. Now `MALFORMED_RESPONSE`.
  - `[low]` `[patch]` The story's I/O matrix ends "Inline error text in `--color-destructive`", and that was the one clause of the row asserted nowhere: `css: false` means jsdom computes no style, so the render tests can see the `role="alert"`, the message and the focus but never the colour. Point either rule at `--color-text` and the rejection renders as ordinary — indeed reassuring — prose with the suite green. Now pinned in `styling-wiring.test.ts`, both screens, plus the class the live region actually carries.
  - `[low]` `[patch]` `LoginRequest`'s `extra="forbid"` and both `min_length=1` bounds were exercised only by a test asserting `status_code in {401, 422}`. Delete `extra="forbid"` and pydantic drops the unknown field, the handler looks up an address that does not exist, spends the decoy and answers 401 — which that test accepts. The contract could widen to accept any field a caller invented, exactly what the docstring says it must not. Where the *shape* of the body is what is wrong, the answer is now pinned to 422.
  - `[low]` `[patch]` `SESSION_ABSOLUTE_LIFETIME` was asserted only against itself: the `Max-Age` expectation and the expiry bound are both derived from the constant, so shortening it to five minutes left every test green while staff were bounced back to the login screen on a schedule nobody chose. A lower bound written with literals now says so — and is the only test that fails when it moves.
  - `[low]` `[patch]` `EXPIRED_SWEEP_LIMIT` is the whole point of the bounded sweep and no test seeded more than two dead rows, so dropping the `LIMIT` clause stayed green. Seeded past the bound and asserted; proven against the deletion of the clause.
  - `[low]` `[patch]` Nothing would notice a connection leaked from `get_connection`, the one dependency all database access flows through: the busiest test makes seven requests against a pool of ten and then tears the app down. In a process that stays up, request eleven blocks for `POOL_TIMEOUT_SECONDS` and every request after it fails the same way. `POOL_MAX_SIZE + 2` requests through one app now say so; proven by borrowing without returning.
  - `[low]` `[patch]` `sessions_user_id_idx` and `sessions_expires_at_idx` could both be deleted from the (not yet shipped) migration with the whole suite green, because a sequential scan returns the same rows — and the `expires_at` one exists precisely because the sweep runs on every sign-in. Asserted against `pg_indexes` alongside the uniqueness that was already covered.
  - `[low]` `[patch]` `no-client-token-storage.test.ts` scanned `src` only, leaving `index.html`, `public/` and the service worker this change repeatedly anticipates — the three most obvious places to put a token outside the bundler's reach — unscanned by the guard whose own rationale is that the exception is where the token ends up. Widened to `apps/web`, with a test that the walk still reaches outside `src`.
  - `[low]` `[patch]` `test_source_guards.py` excluded itself with an unresolved `Path(__file__)` while every scanned path came from a `.resolve()`d root; `test_no_registration.py` resolves both sides. A symlinked checkout makes the spellings differ, the file scans itself, and its own deliberately-bad fixtures fail the guard they exist to prove.
  - `[low]` `[patch]` `README.md` and `sessions.py` stated flatly that a `Secure` cookie needs no development exemption because browsers trust `http://localhost`. True on the development machine and false for the device this product is built for: a handset reaching `make dev` across the LAN by IP is not a trustworthy origin, so the browser discards the cookie without a word and sign-in never completes — the screen simply returns to itself. Written down, with what to do instead, and with the flag not up for negotiation.
  - `[low]` `[patch]` A lone surrogate in the address is the NUL byte's twin — `"\ud800"` is six ASCII characters on the wire and `json.loads` turns it into a `str` psycopg cannot encode — and the reason it is not a 500 today is that pydantic's JSON reader refuses it first, a boundary `_is_addressable` leans on without owning and which nothing recorded. Investigated as a defect, found not to be one, and closed as the verification gap it actually is: a test posting the escape as raw bytes (httpx will not encode it either) pins the 422 and that it says the same thing for an address that exists and one that does not. No guard was added — an unreachable branch asserting a failure that cannot arrive is worse than the gap.


## Design Notes

**Why SHA-256 for the session token and Argon2id for the password.** A password is low-entropy and human-chosen, so it needs a deliberately slow KDF. The session token is 256 bits of `secrets.token_urlsafe` output — there is no dictionary to run against it, and the only thing hashing at rest protects against is a database read turning into usable cookies. A fast one-way digest does that completely, while Argon2id at the pinned 64 MiB cost would be paid on **every authenticated request** rather than once per login. Different threat, different primitive; both are one-way.

**Why the rejection is built from one constant.** Four code paths reject, and the AC is that a caller cannot tell them apart. Two of them (`active = false`, expired temporary credential) are states a maintainer will one day be tempted to explain to the user "to be helpful". Constructing all four from a single module-level `ApiError` factory makes divergence a visible edit rather than an accident, and the test asserts the four responses byte-for-byte.

**Why the expired-temporary-credential check is here and not in Story 1.4.** 1.4 owns the forced-change *screen* and the reissue flow. But AGENTS.md states without exception that a temporary credential stops working after 72 hours, and the only place a credential is presented is this endpoint. Leaving it to 1.4 would ship a window in which an expired credential authenticates. The check is three lines and rejects with the same generic error; everything else about 1.4 stays 1.4's.

**Why no router.** Nothing in the spine, DESIGN.md or EXPERIENCE.md names a routing library, and the only navigation this story needs is "signed out or signed in". A conditional render costs nothing and defers a dependency decision to Story 1.4, which is where navigation trapping actually forces the question. `react-router` added here would be a dependency chosen before the requirement that justifies it.

**Why logout is in scope even though the AC does not name it.** Issuing a session with no revocation path leaves the only exit as clearing browser cookies, and `delete_session` is the counterpart of `issue_session` in the same module. No epic story delivers it. It is ~20 lines of endpoint and the same shared lookup; excluding it would be a gap rather than a boundary.

```python
# apps/api/api/auth.py — the shape, not the code.
INVALID_CREDENTIALS = "Email or password is incorrect."

def _rejected() -> ApiError:
    # One constructor for all four rejection paths, so they cannot drift.
    return ApiError("unauthorized", INVALID_CREDENTIALS, status_code=401)
```

## Verification

**Commands:**
- `make lint` -- expected: exit 0 (ruff check, ruff format --check, oxlint, tsc --noEmit).
- `make test` -- expected: exit 0; the new `apps/api` database tests run against the ephemeral cluster, or skip with the same "no PostgreSQL available" reason `infra/tests` uses.
- `uv run pytest apps/api/tests -q` -- expected: exit 0, with the four-identical-rejections test and the registration-absence test passing.
- `npm --prefix apps/web run test` -- expected: exit 0, including the login screen, gating and client-token-storage guards.
- `git grep -nE "localStorage|sessionStorage|document\.cookie|indexedDB" apps/web/src` -- expected: matches only inside the guard test that forbids them.
- `uv run python -m rocell_infra.migrate status` (with `DATABASE_URL`) -- expected: the sessions migration listed and applied; `down --yes` then `up` returns the database to the same state.

**Manual checks (if no CLI):**
- `make dev`, sign in as the seeded Administrator: the login screen shows no app bar, a wrong password shows the inline error, a correct one lands on the shell, and the browser's devtools show the session cookie flagged HttpOnly and Secure and **not** reachable from `document.cookie` in the console.

## Auto Run Result

Status: done

**Summary.** Third review pass over the Story 1.3 change on `development` (`a45e07d`, `353979e`), driven because the previous pass set `followup_review_recommended: true`. Four independent review layers ran against the full diff since `4b837ab`; 27 distinct findings survived deduplication, of which 15 were patched here, 0 deferred and 12 rejected. No `intent_gap` and no `bad_spec`: nothing found required a spec amendment or a re-derivation, so the implementation was patched in place and `review_loop_iteration` stayed at 0.

One finding was investigated as a defect and turned out not to be one. An address carrying a lone surrogate was reported as reaching psycopg and answering 500 — the NUL byte's twin. A guard was written for it, and the test built to prove the guard load-bearing showed instead that pydantic's JSON reader refuses the escape first and answers 422. The guard was reverted rather than left as an unreachable branch; what survives is a test pinning the boundary `_is_addressable` had been leaning on without owning.

**Files changed in this pass:**

- `apps/api/api/auth.py` — the cookie is set before the expired-session sweep, and the sweep can no longer fail a sign-in that has already committed; the corrupt-digest branch spends the decoy it was skipping; `Cache-Control: no-store` on both rejection factories and on logout.
- `apps/api/api/sessions.py` — the expiry sweep deletes by primary key rather than by `ctid`; the `Secure`-on-localhost comment says where that exemption stops.
- `apps/api/tests/test_login.py` — a failing sweep does not undo a committed sign-in; the corrupt-digest path's decoy asserted as a call, not a response; `no-store` on all five auth responses; the sweep's bound; an independent lower bound on the session lifetime; 422 pinned where the body's shape is what is wrong; the lone-surrogate boundary, posted as raw bytes; the header comparison extracted to one helper.
- `apps/api/tests/test_db.py` — `POOL_MAX_SIZE + 2` requests through one application, so a connection leaked from `get_connection` is not invisible.
- `apps/api/tests/test_source_guards.py` — the self-exclusion resolved the same way every scanned path is.
- `infra/tests/test_migrate.py` — `sessions_user_id_idx` and `sessions_expires_at_idx` asserted against `pg_indexes`.
- `apps/web/src/api/client.ts` — a 2xx whose body will not parse is `MALFORMED_RESPONSE`, not an empty success.
- `apps/web/src/__tests__/api-client.test.ts` — that case driven.
- `apps/web/src/__tests__/no-client-token-storage.test.ts` — the scan widened from `src` to `apps/web`, with a test that it still reaches outside `src`.
- `apps/web/src/__tests__/styling-wiring.test.ts` — the inline error's `--color-destructive`, on both screens, and the class the live region carries.
- `README.md` — the `Secure` cookie's development exemption is `localhost` only, which is not where a phone-first PWA gets tested.

**Findings breakdown.** 15 patched (0 high, 1 medium, 14 low). 0 deferred — everything real this pass was fixable here, and the two items the previous pass deferred are already in the ledger. 12 rejected: three were about ledger bookkeeping the orchestrator owns (truncated entry headings, DW-24/DW-4 not closed, DW-39 duplicating DW-18); scoping login's `delete_session` to the authenticating user, where the proposed fix breaks the shared-tablet case the current behaviour is written for; the `must_change_password` obligation having no ledger entry (it is a docstring obligation and the ledger is not this session's to write); `MAIN_REGION_ID`'s import coupling and the spec's own frontmatter-versus-triage-log reading, both rejected in a previous pass on unchanged grounds; the three endpoints being undocumented outside their source (OpenAPI is off by design); growing test cost (DW-32); an unparseable `DATABASE_URL` starting cleanly and failing every request (the same decision as the already-deferred `/health` entry); `signIn` leaving a live cookie when a 200 body fails `isUser` (speculative recovery from an API contract violation); and the web/API seam repeating the envelope code and message in two languages (a design note, not a defect).

**Follow-up review recommendation: true.** Patched this pass: 0 high, 1 medium, 14 low → score `3 x 1 + 1 x 14 = 17`, at or above the threshold of 5. Worth reading with the trend in mind: 13 patches, then 22, now 15, and the severity has fallen from 7 medium to 4 medium to 1. What this pass found is almost entirely tests that would not have failed, not behaviour that is wrong.

**Verification performed:**

- `make lint` — exit 0 (ruff check, ruff format --check on 40 files, oxlint --deny-warnings, tsc --noEmit).
- `make test` — exit 0: 330 pytest tests passed against the ephemeral PostgreSQL 16 cluster (no skips on this machine; 320 before this pass), 365 vitest tests across 10 files (360 before).
- Every new guard was proven load-bearing by removing what it guards and watching it fail: the sweep's `try/except` (the sign-in answered 500), the corrupt-digest decoy, `no-store` on the rejection factories, the `LIMIT` clause in the sweep, `extra="forbid"`, `SESSION_ABSOLUTE_LIFETIME` shortened to five minutes (one test failed — the new one), `sessions_expires_at_idx` deleted from the migration, `--color-destructive` swapped for `--color-text`, the malformed-2xx throw, a connection borrowed without being returned, and `localStorage` added to `apps/web/index.html`.
- `uv run pytest apps/api/tests/test_source_guards.py apps/api/tests/test_no_registration.py` — 19 passed.
- `git grep -nE "localStorage|sessionStorage|document\.cookie|indexedDB" apps/web/src` — matches only `no-client-token-storage.test.ts`, the guard that forbids them.

**Residual risks.**

- The `ctid` → `id` change in the expiry sweep closes a hazard that is latent rather than live: nothing `UPDATE`s a session row today, so no test can distinguish the two forms. It is correct by construction, not by assertion, and Story 1.5's sliding renewal is what would have made it observable.
- The sweep-bound test catches the bound being removed, not the constant being changed — its expectation is derived from `EXPIRED_SWEEP_LIMIT`. Changing the value is a deliberate edit; deleting the clause is the accident.
- The `Secure`-cookie limitation on a LAN address is now written down but not worked around: there is still no supported way to sign in from a real handset against `make dev`. That is a development-environment decision (a tunnel, a local certificate) nobody has taken, and it sits next to DW-4.
- Both previously deferred items remain open and neither is closed by this pass: until a security-headers middleware lands the login screen is framable, and until the suite refuses to skip, a CI image without PostgreSQL reports green for untested authentication.
- `make eval` and `make ingest` remain unimplemented (Epic 2) and no `shared/vision/` code was touched, so no re-index is implied by this pass.
