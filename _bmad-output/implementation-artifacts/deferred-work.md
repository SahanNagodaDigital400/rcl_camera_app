### DW-1: apps/web's ESLint config parses .ts/.tsx with the default JS parser (typescript-eslint is dropped, incompatible with the architecture-pinned TypeScript 7.0.x) and has no automated enforcement of the
origin: spec-deferred c8a4a56b45af
location: apps/web/eslint.config.js
source_spec: `spec-1-1-project-scaffold-design-token-foundation.md`
severity: medium
reason: typescript-eslint's stable line refuses to load against a TypeScript major >= 7 (tracked upstream: typescript-eslint/typescript-eslint#10940); TS 7.0 ships no programmatic compiler API until 7.1. Confirmed no npm alias/override can give it a separate TS6 copy since "typescript" is a shared peerDependency. Documented in a comment block at the top of apps/web/eslint.config.js. ESLint's default parser currently works only because no file yet uses TypeScript-only syntax (interfaces, generics, type annotations) -- it will fail to parse those files once real typed code lands, starting with Story 1.2.
status: open

### DW-2: No CI workflow runs `make lint`/`make test` automatically on push or PR.
origin: spec-deferred 93cc851a4b8e
location: n/a
source_spec: `spec-1-1-project-scaffold-design-token-foundation.md`
severity: low
reason: ARCHITECTURE-SPINE.md's Deferred section explicitly defers the hosting/deployment provider and CI/CD pipeline choice -- no provider is picked yet, so a concrete CI workflow can't be written. Until one exists, the "every later story starts from a green baseline" goal is enforced only by local developer discipline (running `make lint`/`make test` by hand), not automatically.
status: open

### DW-3: No PWA manifest, service worker, icons, or favicon exist yet, despite the product being described everywhere as a "React PWA."
origin: spec-deferred 0290f86cbbaa
location: n/a
source_spec: `spec-1-1-project-scaffold-design-token-foundation.md`
severity: low
reason: CLAUDE.md, ARCHITECTURE-SPINE.md, and this app's own package.json description all call it a PWA, but installability (manifest.json, icons, offline shell) isn't named in this story's AC and isn't yet assigned to any specific future story.
status: open

### DW-4: No CORS configuration on apps/api and no Vite dev proxy wired for apps/web -> apps/api local calls.
origin: spec-deferred c542af16cc1a
location: n/a
source_spec: `spec-1-1-project-scaffold-design-token-foundation.md`
severity: low
reason: `make dev` runs both servers concurrently but nothing in this story calls the API from the web app yet, so the gap is unexercised. It will surface as soon as the first real fetch call is added in a later story.
status: open

### DW-5: `make dev`'s bash job orchestration has two latent robustness gaps.
origin: spec-deferred 4cb4af07d887
location: Makefile:8-12
source_spec: `spec-1-1-project-scaffold-design-token-foundation.md`
severity: low
reason: Bare `wait` in the Makefile's `dev` target always returns 0 regardless of whether uvicorn or vite crashed, so a crash wouldn't be reported as failure. `trap 'kill 0' EXIT` signals the whole process group rather than just this recipe's own child jobs, which could affect unrelated processes sharing that group in unusual invocation contexts. Neither is exercised by any test or by the make lint/test AC gate -- dev-ergonomics only.
status: open

### DW-6: apps/web's eslint.config.js applies `globals.browser` uniformly, including to Node-context files (vite.config.ts, eslint.config.js itself); Node globals like `process`/`__dirname` would trip
origin: spec-deferred b3299fee7e79
location: apps/web/eslint.config.js
source_spec: `spec-1-1-project-scaffold-design-token-foundation.md`
severity: low
reason: Verified vite.config.ts and eslint.config.js use no Node globals today, so make lint currently passes -- this is a latent risk that would surface only once one of those files needs a Node-context value.
status: open

### DW-7: infra/migrate.py has no advisory-lock or other concurrency protection against two simultaneous `make migrate` invocations against the same database.
origin: spec-deferred 9d1a0e33ba4e
location: infra/migrate.py
source_spec: `spec-1-2-user-schema-seeded-administrator.md`
severity: low
reason: A race would cause one process to fail cleanly on the `schema_migrations` unique-constraint insert (each migration runs in its own transaction, so no partial/corrupt state results) rather than corrupting data -- but it's still an unhandled race. Not exercised today: no deploy pipeline exists yet (hosting/CI/CD is explicitly Deferred in ARCHITECTURE-SPINE.md), so concurrent invocation isn't a realistic scenario until one does.
status: open

### DW-8: No database constraint ties `must_change_password` to `temp_credential_expires_at` -- a row could in principle carry one flag without the other in a mutually inconsistent state.
origin: spec-deferred f944f01d3abe
location: infra/migrations/0001_create_users.py
source_spec: `spec-1-2-user-schema-seeded-administrator.md`
severity: low
reason: This story's only writer (the seed migration) always sets both consistently, so no inconsistent row exists today. But the exact semantics of forced-password-change outside the migration-seeded case (e.g. can an Administrator force a password change with no expiry?) are Story 1.4's or 1.8's decision to make, not this story's -- adding a CHECK constraint now would fabricate scope neither story has defined yet.
status: open
