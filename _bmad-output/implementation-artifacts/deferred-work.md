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
