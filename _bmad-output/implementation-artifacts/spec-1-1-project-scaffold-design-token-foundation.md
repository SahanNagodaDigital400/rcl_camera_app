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

### 2026-09-10 — Review pass (2)

- intent_gap: 0
- bad_spec: 0
- patch: 3 (high 1, medium 2, low 0)
- defer: 0
- reject: 20 (high 0, medium 0, low 20)
- addressed_findings:
  - `[high]` `[patch]` `apps/web`'s solution-style `tsconfig.json` (`"files": []` + `references`) was type-checked via plain `tsc --noEmit`, which resolves and checks zero files against a solution config -- `make lint`/`npm run build`'s type-check step was a complete no-op (verified live: an injected return-type error in `App.tsx` still exited 0). This silently defeated the Always-requirement "TypeScript strict mode" and the documented fallback for the already-deferred typescript-eslint gap (`eslint.config.js`'s own comment claims "Type-level strictness ... is enforced by `tsc --noEmit`"). Fixed by adding `"composite": true` to `tsconfig.app.json`/`tsconfig.node.json` and switching `package.json`'s `build`/`lint` scripts to `tsc -b`; re-verified live that the same injected error is now caught (exit 1). Fixing this surfaced a second, previously-masked defect: `vitest@5.0.0`'s shipped types conflict with `@testing-library/jest-dom@7.0.1`'s `Assertion` augmentation (`TS2428`), an upstream incompatibility between two just-released majors -- resolved by pinning `vitest` to `^4.1.11` (latest 4.x, still satisfies the `vite@~8.0.16` peer range); confirmed all tests and `tsc -b` pass clean. Also added `@types/node` (needed by a new Node-`fs`-based test, see below) and `apps/web/*.tsbuildinfo` to `.gitignore` (new artifact from `tsc -b`).
  - `[medium]` `[patch]` No test distinguished the Phosphor icon's `weight` prop, so a regression to `bold`/`fill`/etc. would still pass `make test` despite violating the AC's "regular-weight icon" requirement -- added a reference-render comparison in `App.test.tsx`; verified it fails when `weight` is changed to `"bold"` and passes at `"regular"`.
  - `[medium]` `[patch]` No automated check enforced "no raw hex in component files" (AC 2 / `tokens.css`'s own header comment) beyond manual review -- demonstrated live that replacing a `var(--color-primary)` reference with a raw hex literal in `global.css` still left `make lint` and `make test` green. Added `apps/web/src/styles/tokens.test.ts`, a regression test asserting no hex/`rgb(a)` literal appears in any non-`tokens.css` stylesheet; verified it fails on the injected hex literal and passes on the reverted file.
  - `[reject]` Findings duplicating items already in this spec's `deferred` list: no CORS config (matches the existing CORS/proxy entry), `typescript-eslint` dropped with no automated no-`any` enforcement (matches the existing ESLint entry, raised independently by two reviewers), no CI workflow (matches the existing CI entry), no PWA manifest/service worker (matches the existing PWA entry), `make dev`'s `wait`/`trap kill 0` robustness gaps (matches the existing Makefile entry, raised independently by two reviewers).
  - `[reject]` Findings contradicted by an explicit, already-recorded scope decision in this spec: Google Fonts CDN with no self-hosted fallback (Design Notes: an intentional choice, self-hosting is a later refinement), root `pyproject.toml` listing every workspace member as a dependency (Tasks & Acceptance: explicitly "one Python env for the whole domain core + adapters"), `infra` having only a README while other seed dirs got code (Never-list: migrations/IaC content is explicitly out of scope this story), `shared/vision`'s README mentioning a future `make eval` run and `scripts/ingest` having no `make ingest` target (Never-list explicitly excludes both targets from this story).
  - `[reject]` Cosmetic or unactionable, no functional impact: `CLAUDE.md`'s stale "no Makefile" line (not a file this story's Tasks list touches), `apps/api`/`apps/web` lacking a top-level README (convention nit only), no `package.json` `engines` field, `infra/README.md`'s "forward-only, reversible" phrasing, no API version prefix on the `/health`-only FastAPI skeleton (premature -- Never-list excludes real endpoints this story), and a `.gitignore` suggestion to also cover speculative `.vite/`/`coverage/` artifacts that don't yet exist in this skeleton.
  - `[reject]` Descriptive-only intent-alignment observations that don't identify an actual gap once checked against the full diff (the auditor was given a trimmed excerpt): the claim that `index.html`/`main.tsx`/`vite.config.ts` were missing (they exist in the actual diff), that font "loading" is declaration-only (`index.html` does include the Google Fonts `<link>` tags), and that `make lint`/`make test` passing wasn't demonstrated (the verification-gap reviewer ran them live in-repo and they passed, and they pass again after this pass's patches). Also rejected: the observation that DESIGN.md value-for-value fidelity isn't automatically verifiable from the diff -- true, but unactionable by an automated check and already covered by manual review per Design Notes.

## Design Notes

- **`shared/schema` starts as a Python package**, not TypeScript. The Structural Seed's diagram shows solid arrows from `apps/api` and `scripts/ingest` into `shared/schema` but only a dotted "type contracts only" line from `apps/web` — read as: Python is the direct-consumer language now, `apps/web` picks up contracts later (e.g. via OpenAPI-generated types) once real endpoints exist. Nothing about this AC requires resolving that generation step yet.
- **No Tailwind/CSS framework** — `DESIGN.md` states no UI kit is inherited and treats Tailwind as an implementation choice, not a requirement. Plain CSS custom properties keep the token file as the literal, greppable single source of truth for "no raw hex in components."
- **New dependencies added** (flagging per `AGENTS.md`): `@phosphor-icons/react` (the icon set is a named UX-DR, not optional); `vitest` + `@testing-library/react` + `@testing-library/jest-dom` + `jsdom` (Vite's native test runner pairing, needed to give `make test` something real to check in `apps/web`). No new Python deps beyond `fastapi`, `uvicorn`, `ruff`, `pytest`.
- **Fonts load from Google Fonts CDN**, not self-hosted — self-hosting is a performance refinement, not part of this AC's "loading with declared fallback stacks" requirement.
- If a pinned major version genuinely isn't resolvable and a nearest-compatible version is substituted, record the substitution here via a Spec Change Log entry during implementation — don't silently diverge from the Stack table.
- **`vitest` pinned to `^4.1.11`, not `^5.0.0`** — `vitest@5.0.0`'s shipped types conflict with `@testing-library/jest-dom@7.0.1`'s `Assertion` augmentation (`TS2428`, confirmed live); `4.1.11` is the latest 4.x release and still satisfies the `vite@~8.0.16` peer range. `vitest` isn't one of the architecture-pinned majors (React/Vite/TypeScript/FastAPI/Python), so this is a same-story dependency-compatibility fix, not a Stack-table deviation. See Review Triage Log, 2026-09-10 pass (2).

## Verification

**Commands:**
- `uv sync` -- expected: installs the Python workspace (`apps/api`, `shared/vision`, `shared/schema`, `scripts/ingest`) with no errors
- `cd apps/web && npm install` -- expected: installs with no errors
- `make lint` -- expected: exit 0 (ruff clean across Python dirs; eslint + `tsc -b` (project-reference build mode -- plain `tsc --noEmit` against this solution-style tsconfig is a no-op, see Review Triage Log) clean in `apps/web`)
- `make test` -- expected: exit 0 (pytest passes across the Python workspace; vitest passes in `apps/web`)
- `cd apps/web && npm run build` -- expected: production `vite build` succeeds, confirming the shell is actually runnable, not just lint-clean

## Auto Run Result

**Summary:** This run performed a fresh review pass (no code changes needed beyond review-driven patches) over the already-implemented project scaffold and design-token foundation. Three real defects surfaced during review and were patched; everything else raised by the four review layers was either already tracked in this spec's `deferred` list, explicitly authorized by an existing scope decision, or cosmetic/unactionable.

**Files changed this pass:**
- `apps/web/tsconfig.app.json`, `apps/web/tsconfig.node.json` -- added `"composite": true` so `tsc -b` (project-reference build mode) actually type-checks the project; removed the redundant/conflicting `@testing-library/jest-dom` entry from `tsconfig.app.json`'s `types` array (module-level import already supplies its types); added `"node"` to `types` for the new Node-`fs`-based test.
- `apps/web/package.json` -- `build`/`lint` scripts switched from `tsc --noEmit` (a no-op against the solution-style tsconfig) to `tsc -b`; `vitest` pinned to `^4.1.11` (was `^5.0.0`, incompatible with `@testing-library/jest-dom@7.0.1`'s types); added `@types/node` devDependency.
- `apps/web/package-lock.json` -- regenerated for the above.
- `apps/web/src/App.test.tsx` -- strengthened the icon test to assert `regular` weight via a reference-render comparison, not just "is an svg".
- `apps/web/src/styles/tokens.test.ts` (new) -- regression test asserting no raw hex/`rgb(a)` values appear outside `tokens.css`.
- `.gitignore` -- added `apps/web/*.tsbuildinfo` (new artifact from `tsc -b`).
- `_bmad-output/implementation-artifacts/spec-1-1-project-scaffold-design-token-foundation.md` -- this review pass's Review Triage Log entry, Design Notes addendum, Verification wording update, and this section; `status` set to `done`.

**Review findings breakdown:** patch 3 (high 1, medium 2, low 0) -- all applied and verified; defer 0; reject 20 (all low: 5 duplicates of already-`deferred` items, 4 contradicted by an existing explicit scope decision, 11 cosmetic/unactionable/resolved-on-closer-inspection). Full detail in Review Triage Log, "2026-09-10 — Review pass (2)".

**Follow-up review recommendation:** `true` -- one patched finding this pass was `high` severity (the `tsc --noEmit` no-op), which alone triggers recommendation regardless of the medium/low count (patched-severity score: high 1, medium 2, low 0).

**Verification performed:** All commands in `## Verification` re-run clean after patching: `uv sync` (28 packages resolved), `make lint` (ruff clean; `eslint . && tsc -b` clean in `apps/web`), `make test` (4 Python tests pass; 5 vitest tests pass, up from 3 -- the two new/strengthened tests), `cd apps/web && npm run build` (production build succeeds, 194.88 kB JS / 3.04 kB CSS bundle). Additionally live-verified during review: (1) `tsc -b` now catches an injected type error that plain `tsc --noEmit` missed; (2) the icon-weight test fails when `weight` is changed to `"bold"`; (3) the token regression test fails when a raw hex literal is reintroduced into `global.css`.

**Residual risks:** The six low-severity pre-existing deferred items from the prior review pass remain open and untouched by this pass (ESLint/TypeScript parser gap, no CI workflow, no PWA manifest, no CORS/dev-proxy, `make dev`'s job-orchestration robustness, `eslint.config.js`'s uniform `globals.browser`) -- this run did not modify, resolve, or re-litigate any of them, per this run's operating instructions. The `vitest`/`@testing-library/jest-dom` version conflict discovered this pass is an upstream incompatibility between two very recently released majors; if either package publishes a fix, revisiting the `^4.1.11` pin is a future cleanup, not a defect.
