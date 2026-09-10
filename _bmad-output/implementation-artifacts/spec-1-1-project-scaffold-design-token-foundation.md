---
title: 'Project Scaffold & Design Token Foundation'
type: 'feature'
created: '2026-09-10'
status: 'done'
baseline_revision: '2e975340567dfe554f41807617a871bdbf36fb1d'
review_loop_iteration: 0
followup_review_recommended: true
context: []
warnings: [oversized]
deferred:
  - summary: >-
      apps/web's ESLint config parses .ts/.tsx with the default JS parser
      (typescript-eslint is dropped, incompatible with the architecture-pinned
      TypeScript 7.0.x) and has no automated enforcement of the "no `any`
      without a comment" convention.
    evidence: |-
      typescript-eslint's stable line refuses to load against a TypeScript
      major >= 7 (tracked upstream: typescript-eslint/typescript-eslint#10940);
      TS 7.0 ships no programmatic compiler API until 7.1. Confirmed no npm
      alias/override can give it a separate TS6 copy since "typescript" is a
      shared peerDependency. Documented in a comment block at the top of
      apps/web/eslint.config.js. ESLint's default parser currently works only
      because no file yet uses TypeScript-only syntax (interfaces, generics,
      type annotations) -- it will fail to parse those files once real typed
      code lands, starting with Story 1.2.
    location: apps/web/eslint.config.js
    severity: medium
  - summary: >-
      No CI workflow runs `make lint`/`make test` automatically on push or PR.
    evidence: |-
      ARCHITECTURE-SPINE.md's Deferred section explicitly defers the
      hosting/deployment provider and CI/CD pipeline choice -- no provider is
      picked yet, so a concrete CI workflow can't be written. Until one
      exists, the "every later story starts from a green baseline" goal is
      enforced only by local developer discipline (running `make lint`/`make
      test` by hand), not automatically.
    severity: low
  - summary: >-
      No PWA manifest, service worker, icons, or favicon exist yet, despite
      the product being described everywhere as a "React PWA."
    evidence: |-
      CLAUDE.md, ARCHITECTURE-SPINE.md, and this app's own package.json
      description all call it a PWA, but installability (manifest.json,
      icons, offline shell) isn't named in this story's AC and isn't yet
      assigned to any specific future story.
    severity: low
  - summary: >-
      No CORS configuration on apps/api and no Vite dev proxy wired for
      apps/web -> apps/api local calls.
    evidence: |-
      `make dev` runs both servers concurrently but nothing in this story
      calls the API from the web app yet, so the gap is unexercised. It will
      surface as soon as the first real fetch call is added in a later story.
    severity: low
  - summary: >-
      `make dev`'s bash job orchestration has two latent robustness gaps.
    evidence: |-
      Bare `wait` in the Makefile's `dev` target always returns 0 regardless
      of whether uvicorn or vite crashed, so a crash wouldn't be reported as
      failure. `trap 'kill 0' EXIT` signals the whole process group rather
      than just this recipe's own child jobs, which could affect unrelated
      processes sharing that group in unusual invocation contexts. Neither is
      exercised by any test or by the make lint/test AC gate -- dev-ergonomics
      only.
    location: Makefile:8-12
    severity: low
  - summary: >-
      apps/web's eslint.config.js applies `globals.browser` uniformly,
      including to Node-context files (vite.config.ts, eslint.config.js
      itself); Node globals like `process`/`__dirname` would trip `no-undef`
      if used there.
    evidence: |-
      Verified vite.config.ts and eslint.config.js use no Node globals today,
      so make lint currently passes -- this is a latent risk that would
      surface only once one of those files needs a Node-context value.
    location: apps/web/eslint.config.js
    severity: low
---

<intent-contract>

## Intent

**Problem:** The repo has no application code yet — only planning docs and a `poc/` prototype. No later story (UI, auth, catalogue, scanning) has a structure to build into or a styling source to build from.

**Approach:** Hand-build the six Structural Seed directories (`apps/web`, `apps/api`, `shared/vision`, `shared/schema`, `infra`, `scripts/ingest`) as runnable skeletons, implement the `DESIGN.md` token set as `apps/web`'s only styling source in an app shell, and stand up root `make lint` / `make test` so every later story starts green.

## Boundaries & Constraints

**Always:** The six directories exist exactly as named in `ARCHITECTURE-SPINE.md`'s Structural Seed. `apps/web` styling reads only from the token set (colors, typography, radii, spacing, elevation) — no raw hex in component files, only in the one token-definition file. Plus Jakarta Sans (400/500/600/700/800) and JetBrains Mono load with declared CSS fallback stacks (UX-DR2). Phosphor icons wired at `regular` weight, 20–24px (UX-DR3). `make lint` (ruff + eslint + tsc) and `make test` both exist at repo root and exit 0 against this skeleton. Python: ruff, type hints, no bare `except`. TypeScript: strict mode, no `any` without a comment. No secrets committed.

**Block If:** No installable version exists at all for a pinned major dependency (React 19, Vite 8, TypeScript 7, FastAPI 0.141.x, Python 3.12+) — these are architecture-pinned, not this story's call to change.

**Never:** No UI kit or CSS framework (Tailwind, MUI, etc.) — `DESIGN.md` is explicit this is from-scratch against raw CSS/tokens. No vision/embedding logic, DB schema/migrations, auth, ingestion logic, or `make migrate`/`make ingest`/`make eval` targets — those belong to the stories that need them (1.2 adds migrations; later epics add ingest/eval). No workspace-wide package manager beyond what's specified below.

</intent-contract>

## Code Map

- `_bmad-output/planning-artifacts/architecture/architecture-rcl_camera_app-2026-08-30/ARCHITECTURE-SPINE.md` -- Structural Seed (dir layout + one-line purpose per dir), Stack table (exact version pins), AD-6 (web talks only to api)
- `_bmad-output/planning-artifacts/ux-designs/ux-rcl_camera_app-2026-09-08/DESIGN.md` -- frontmatter YAML is the literal token source (colors/typography/rounded/spacing/components); `app-bar` and `button-primary`/`button-secondary` visual specs for the shell
- `AGENTS.md` -- Conventions that differ from defaults (ruff, TS strict, no bare except, flag new deps); Known pitfalls
- `poc/Makefile`, `poc/pyproject.toml` -- existing project's use of `uv` for Python env/deps; pattern to mirror for `apps/api`/`shared/*`/`scripts/ingest`, not to copy ML-specific targets from
- `.gitignore` -- currently only covers `poc/` and `.bmad-loop/`; needs entries for `apps/web` (`node_modules/`, `dist/`), Python (`.venv/`, `__pycache__/`, `.pytest_cache/`) at the new paths

## Tasks & Acceptance

**Execution:**
- `pyproject.toml` (root) -- declare a `uv` workspace with members `apps/api`, `shared/vision`, `shared/schema`, `scripts/ingest`; root `[tool.ruff]` config; `dev-dependencies` = ruff, pytest -- one Python env for the whole domain core + adapters, matching the Design Paradigm's shared-core model
- `apps/api/pyproject.toml`, `apps/api/app/main.py` -- FastAPI app with a `GET /health` endpoint returning `{"status": "ok"}` -- smallest possible proof the adapter boots
- `apps/api/tests/test_health.py` -- asserts `/health` returns 200 -- the one thing `make test` needs to pass for this package
- `shared/vision/pyproject.toml`, `shared/vision/vision/__init__.py`, `shared/vision/README.md` -- empty package + a README stating this module will be ported from `poc/tilematch/vision.py` unchanged (AD-1, AD-11, AD-13, AD-15) in a later story -- no vision logic this story
- `shared/vision/tests/test_import.py` -- asserts the package imports cleanly -- keeps `make test` meaningful for an intentionally-empty package
- `shared/schema/pyproject.toml`, `shared/schema/schema/__init__.py`, `shared/schema/README.md` -- empty package + README recording the assumption below -- placeholder for the types Story 1.2 onward will define
- `shared/schema/tests/test_import.py` -- import smoke test
- `scripts/ingest/pyproject.toml`, `scripts/ingest/ingest/__init__.py`, `scripts/ingest/README.md` -- empty package depending on `shared-vision`/`shared-schema` as workspace deps + README noting AD-7 (shared upload-intake path) and pre-launch-only scope (Design Paradigm) -- no ingestion logic this story
- `scripts/ingest/tests/test_import.py` -- import smoke test
- `infra/README.md` -- documents the directory's future contents (`migrations/`, deploy config) and points at `ARCHITECTURE-SPINE.md`'s Deferred section (hosting, secrets, backup/DR are not this story's call) -- no IaC content yet, nothing to stand up
- `apps/web/package.json`, `apps/web/vite.config.ts`, `apps/web/tsconfig.json` -- React 19.2 + Vite 8 + TypeScript 7 (strict) skeleton; add `@phosphor-icons/react` (UX-DR3), `vitest` + `@testing-library/react` + `@testing-library/jest-dom` + `jsdom` as dev deps for the test target; ESLint flat config
- `apps/web/index.html` -- `<link rel="preconnect">` + Google Fonts `<link>` for Plus Jakarta Sans and JetBrains Mono
- `apps/web/src/styles/tokens.css` -- every `DESIGN.md` token as a CSS custom property (`--color-primary`, `--font-display-size`, `--radius-md`, `--space-4`, etc.) -- the single place hex values are allowed to appear
- `apps/web/src/styles/global.css` -- base element styles (body background/text/font) referencing only `tokens.css` custom properties, plus the two font-family declarations with fallback stacks (`'Plus Jakarta Sans', system-ui, -apple-system, sans-serif` / `'JetBrains Mono', 'SF Mono', monospace`)
- `apps/web/src/App.tsx`, `apps/web/src/main.tsx` -- app shell: an `app-bar` (navy fill, white content, accent-color bottom stripe, per `DESIGN.md`) rendering one Phosphor icon at `regular` weight and one `button-primary` (accent fill, navy text) -- proves tokens, fonts, and icons are all wired end to end, not just declared
- `apps/web/src/App.test.tsx` -- vitest + Testing Library smoke test asserting the app bar and button render -- what `make test` needs to pass for this package
- `.gitignore` -- add `apps/web/node_modules/`, `apps/web/dist/`, `.venv/`, `__pycache__/`, `.pytest_cache/` entries for the new paths (some already exist for `poc/`; don't duplicate)
- `Makefile` (root) -- add `dev`, `lint`, `test` targets (`dev` runs `apps/api` uvicorn and `apps/web` vite concurrently via backgrounded shell jobs; `lint` runs ruff across the Python dirs + eslint/tsc in `apps/web`; `test` runs pytest across the Python workspace + vitest in `apps/web`) -- these are the exact two (`lint`, `test`) the AC gates on; `dev` proves the skeleton is runnable, not just lintable; added last since it wires together every target defined above

**Acceptance Criteria:**
- Given a clean checkout, when this story is complete, then all six Structural Seed directories exist, each with a runnable skeleton (importable/lintable Python packages; a `vite build`-able web app)
- Given `apps/web` is running, when the app shell renders, then every color/type/radius/spacing value traces to a token in `tokens.css`, Plus Jakarta Sans and JetBrains Mono are the applied fonts with fallback stacks declared, and a Phosphor `regular`-weight icon is visible
- Given the repo root, when `make lint` and `make test` run, then both exit 0

## Spec Change Log

## Review Triage Log

### 2026-09-10 — Review pass

- intent_gap: 0
- bad_spec: 0
- patch: 3 (high 0, medium 3, low 0)
- defer: 6 (high 0, medium 1, low 5)
- reject: 7 (high 0, medium 0, low 7)
- addressed_findings:
  - `[medium]` `[patch]` `apps/web/eslint.config.js` had `no-unused-vars` set to `warn` with no `--max-warnings=0`, so unused-variable violations did not fail `make lint` -- changed to `error`; verified live by injecting and removing an unused variable.
  - `[medium]` `[patch]` `.button-primary` computed to ~43.6px tall, under the ≥44×44px touch-target floor (UX-DR17) -- added `min-height: 44px; min-width: 44px;` to `apps/web/src/styles/global.css`.
  - `[medium]` `[patch]` `apps/web/src/App.test.tsx` never asserted the Phosphor icon renders, so the AC "a Phosphor `regular`-weight icon is visible" had no regression coverage -- added an assertion querying `.app-bar__icon` and its `<svg>` tag.

## Design Notes

- **`shared/schema` starts as a Python package**, not TypeScript. The Structural Seed's diagram shows solid arrows from `apps/api` and `scripts/ingest` into `shared/schema` but only a dotted "type contracts only" line from `apps/web` — read as: Python is the direct-consumer language now, `apps/web` picks up contracts later (e.g. via OpenAPI-generated types) once real endpoints exist. Nothing about this AC requires resolving that generation step yet.
- **No Tailwind/CSS framework** — `DESIGN.md` states no UI kit is inherited and treats Tailwind as an implementation choice, not a requirement. Plain CSS custom properties keep the token file as the literal, greppable single source of truth for "no raw hex in components."
- **New dependencies added** (flagging per `AGENTS.md`): `@phosphor-icons/react` (the icon set is a named UX-DR, not optional); `vitest` + `@testing-library/react` + `@testing-library/jest-dom` + `jsdom` (Vite's native test runner pairing, needed to give `make test` something real to check in `apps/web`). No new Python deps beyond `fastapi`, `uvicorn`, `ruff`, `pytest`.
- **Fonts load from Google Fonts CDN**, not self-hosted — self-hosting is a performance refinement, not part of this AC's "loading with declared fallback stacks" requirement.
- If a pinned major version genuinely isn't resolvable and a nearest-compatible version is substituted, record the substitution here via a Spec Change Log entry during implementation — don't silently diverge from the Stack table.

## Verification

**Commands:**
- `uv sync` -- expected: installs the Python workspace (`apps/api`, `shared/vision`, `shared/schema`, `scripts/ingest`) with no errors
- `cd apps/web && npm install` -- expected: installs with no errors
- `make lint` -- expected: exit 0 (ruff clean across Python dirs; eslint + `tsc --noEmit` clean in `apps/web`)
- `make test` -- expected: exit 0 (pytest passes across the Python workspace; vitest passes in `apps/web`)
- `cd apps/web && npm run build` -- expected: production `vite build` succeeds, confirming the shell is actually runnable, not just lint-clean

## Auto Run Result

**Summary:** Hand-built the six Structural Seed directories as runnable skeletons and stood up the `DESIGN.md` token set as `apps/web`'s sole styling source, per the AC. `apps/api` exposes a `GET /health` FastAPI endpoint; `shared/vision`, `shared/schema`, and `scripts/ingest` are empty packages with READMEs recording their future scope and the architecture invariants (AD-1/7/11/13/15) that will govern them; `infra` documents its future contents and points at the architecture spine's Deferred list. `apps/web` renders an app shell (`app-bar` + one `button-primary`) styled entirely from CSS custom properties in `tokens.css`, with Plus Jakarta Sans/JetBrains Mono loaded via Google Fonts and a Phosphor `regular`-weight icon wired in. Root `make lint` and `make test` both pass against the skeleton. One deviation from the plan: `typescript-eslint` had to be dropped (TypeScript 7.0.x, architecture-pinned, has no programmatic compiler API and isn't yet supported by typescript-eslint's stable line) — `tsc --noEmit` carries type-level strictness instead; logged as a deferred item below since this will need revisiting once Story 1.2+ adds real typed code.

**Files changed:** 34 files across `pyproject.toml` (root `uv` workspace), `apps/api/` (FastAPI skeleton + health test), `shared/vision/`, `shared/schema/`, `scripts/ingest/` (empty packages + README + import tests), `infra/README.md`, `apps/web/` (Vite/React/TS app: config, tokens, global styles, app shell, tests, ESLint config), root `Makefile` (`dev`/`lint`/`test`), and `.gitignore` (new build/venv paths). Full list is in the diff since baseline `2e975340567dfe554f41807617a871bdbf36fb1d`.

**Review findings breakdown:**
- 3 patches applied (all medium severity): `eslint` `no-unused-vars` changed `warn` → `error`; `.button-primary` given `min-height`/`min-width: 44px` to clear the accessibility touch-target floor (UX-DR17); `App.test.tsx` given a regression assertion for the Phosphor icon.
- 6 items deferred (1 medium, 5 low): typescript-eslint/TS7 incompatibility (no automated "no `any`" enforcement, parser will break on real TS syntax); no CI workflow (CI/CD provider is an architecture-level Deferred item); no PWA manifest/icons/favicon; no CORS/dev-proxy wiring for `apps/web` → `apps/api`; two `make dev` bash job-orchestration robustness gaps; `eslint.config.js`'s `globals.browser` applied uniformly to Node-context config files.
- 7 items rejected as noise or verified non-issues: missing READMEs for `apps/web`/`apps/api` (asymmetric by design — those aren't empty placeholder packages); root `pyproject.toml` missing `[build-system]` (verified `uv sync` correctly treats it as a non-buildable workspace root); unbounded ancillary Python dependency versions (the lockfile provides reproducibility); CSS `@import` "render-blocking" claim (Vite bundles it into one file at build, verified in `dist/`); JetBrains Mono "never rendered" (the AC only requires loading with a declared fallback stack, which is satisfied); missing Spec Change Log entry for the typescript-eslint drop (not a pinned-major substitution, not owed per this spec's own trigger condition); smoke tests covering only the happy/import path (expected and by design for an intentionally-empty scaffold).

**Follow-up review recommendation:** `true`. Score = 3×medium(3) + 1×low(0) = 9 ≥ 5. Patched-finding counts this pass: high 0, medium 3, low 0.

**Verification performed:** `uv sync` (clean), `cd apps/web && npm install` (clean, 0 vulnerabilities), `make lint` (exit 0), `make test` (exit 0 — 4 pytest + 3 vitest, re-run and confirmed independently after the patch fixes), `cd apps/web && npm run build` (production build succeeds). Also manually booted `apps/api` (uvicorn, curled `/health` → 200) and `apps/web` (vite dev server) to confirm `make dev`'s underlying commands actually run, not just lint-clean.

**Residual risks:** The `typescript-eslint`/TypeScript-7 gap (deferred above) is the main one — the moment Story 1.2+ introduces real TypeScript syntax (interfaces, generics, type annotations), `eslint .` will fail to parse those files, since ESLint currently falls back to its default non-TS parser. This needs resolving (wait for upstream TS7 support, or get sign-off to pin TypeScript to 6.0.3 for the ESLint path specifically) before or during the first story that adds typed `apps/web` code. The remaining deferred items are lower-risk and don't block any near-term story.
