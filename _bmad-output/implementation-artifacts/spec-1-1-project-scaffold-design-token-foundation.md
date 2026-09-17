---
title: 'Story 1.1 — Project Scaffold & Design Token Foundation'
type: 'feature'
created: '2026-09-17'
baseline_revision: 'ab386f44d0a6ae65d9a313011d6ea33a03ee406a'
status: 'done'
review_loop_iteration: 0
followup_review_recommended: true # score 17 (3x4 medium + 1x5 low); see Auto Run Result
context:
  - '{project-root}/AGENTS.md'
  - '{project-root}/CLAUDE.md'
  - '{project-root}/_bmad-output/planning-artifacts/ux-designs/ux-rcl_camera_app-2026-09-08/DESIGN.md'
  - '{project-root}/_bmad-output/planning-artifacts/architecture/architecture-rcl_camera_app-2026-08-30/ARCHITECTURE-SPINE.md'
warnings: ['oversized']
deferred:
  - summary: >-
      No PWA scaffolding exists — no web app manifest, icons, theme-color meta,
      or service worker — in a product whose delivery model is an installable
      phone app.
    evidence: |-
      apps/web/index.html links no manifest and apps/web/package.json carries no
      PWA plugin. EXPERIENCE.md describes a "multi-surface PWA, installable to
      the home screen" as the delivery model. Story 1.1's acceptance criteria do
      not mention it, so it is out of scope here, but nothing later claims it
      either.
    location: >-
      apps/web/index.html
    severity: medium
  - summary: >-
      No CI workflow runs make lint / make test, so every guard this story ships
      is enforced only when a human remembers to run them.
    evidence: |-
      The token contract test, the no-raw-values guard and the make-target
      honesty tests all exist and pass locally, and nothing runs them on push.
      The architecture spine lists CI/CD as an unresolved infrastructure
      decision blocking deployment work.
    severity: medium
  - summary: >-
      make lint type-checks TypeScript with tsc but runs no Python type checker,
      although every Python file is fully annotated and AGENTS.md mandates type
      hints throughout.
    evidence: |-
      Makefile lint runs ruff check and ruff format --check only. Adding mypy or
      pyright is a new dependency and would likely surface new findings, so it
      is a decision rather than a patch.
    location: >-
      Makefile
    severity: medium
  - summary: >-
      The Vite dev proxy rewrites /api/x to /x against the API root, and no
      production path convention is fixed, so dev and production can disagree
      about the API prefix.
    evidence: |-
      apps/web/vite.config.ts proxies /api with a rewrite; README.md describes
      production as a same-origin path. Whether the production reverse proxy
      strips the same prefix is undecided. Related: the dev proxy runs over
      plain HTTP, which will collide with the mandated Secure / SameSite=Strict
      session cookie when Story 1.3 lands.
    location: >-
      apps/web/vite.config.ts
    severity: medium
  - summary: >-
      apps/web's test suite reads DESIGN.md through a hardcoded, date-stamped
      planning-artifact path, coupling the front end to _bmad-output.
    evidence: |-
      apps/web/src/__tests__/tokens.test.ts resolves
      _bmad-output/planning-artifacts/ux-designs/ux-rcl_camera_app-2026-09-08/DESIGN.md.
      A later UX run produces a differently-dated directory and the whole web
      suite fails, and the package cannot be tested from a checkout that
      excludes planning artifacts. Reading DESIGN.md at test time is
      deliberately stronger than copying its values, so the fix is an
      indirection, not a removal.
    location: >-
      apps/web/src/__tests__/tokens.test.ts
    severity: low
  - summary: >-
      Ruff's rule selection omits flake8-bandit (S) and pycodestyle warnings
      (W) in a repository whose security requirements are declared
      non-negotiable.
    evidence: |-
      pyproject.toml selects E, F, I, UP, B only. Enabling S will produce
      findings on the auth and upload code that Stories 1.2+ add, so it is
      better turned on deliberately than as a drive-by.
    location: >-
      pyproject.toml
    severity: low
  - summary: >-
      apps/web has no React error boundary, so any render throw yields a blank
      page with no recovery path.
    evidence: |-
      apps/web/src/main.tsx mounts App directly. The shell currently renders
      static content so the risk is latent, but every later UI story raises it.
    location: >-
      apps/web/src/main.tsx
    severity: low
  - summary: >-
      apps/api sets no security response headers and no request body size
      limit, on a service whose stated primary threat is catalogue
      exfiltration.
    evidence: |-
      create_app() installs the error handlers and disables /docs, /redoc and
      /openapi.json, but adds no middleware for X-Content-Type-Options,
      Referrer-Policy, frame-ancestors/CSP or HSTS, no TrustedHostMiddleware,
      and no upload size ceiling. Choosing a CSP and an HSTS max-age is a
      deployment decision (the spine leaves the deployment target open), and
      the body limit belongs with the upload path in Epic 2, so this is a
      decision rather than a drive-by patch.
    location: >-
      apps/api/api/main.py
    severity: medium
  - summary: >-
      oxlint never lints shared/schema/shared_schema/ts, the one source
      directory outside apps/web/src that apps/web compiles against.
    evidence: |-
      The lint script runs from apps/web and oxlint refuses a path containing
      "..": `Error: PATH must not contain ".."`. Covering it means either
      invoking oxlint from the repository root in the Makefile with an
      explicit node_modules/.bin path, or restructuring the lint target — a
      shape change, not a one-line fix. tsc does type-check the file (it is in
      tsconfig include) and vitest exercises it, so the gap is lint rules only.
    location: >-
      apps/web/package.json
    severity: low
  - summary: >-
      The contrast ratios the token layer cites are never computed by a test,
      so a DESIGN.md colour change can drop the UI below WCAG AA silently.
    evidence: |-
      tokens.css comments state 5.94:1 for navy-on-accent, 4.65:1 for muted
      text on the background and 2.63:1 for the white-on-accent failure.
      tokens.test.ts asserts provenance and an identity between two tokens; no
      test derives a ratio. Change --color-muted-text in DESIGN.md to a failing
      pair and the whole suite stays green. The fix is a relative-luminance
      helper plus a decision about which pairs are load-bearing.
    location: >-
      apps/web/src/__tests__/tokens.test.ts
    severity: low
  - summary: >-
      CLAUDE.md's testing policy calls `make eval-real` "the only number that
      decides anything", but it is neither a Makefile target nor one of the
      not-implemented targets this story enumerates.
    evidence: |-
      CLAUDE.md line 126 names `make eval-real`. The Makefile's .PHONY list is
      help setup dev lint format test build migrate ingest eval, and the
      curated "not implemented yet" block in both the Makefile and CLAUDE.md
      lists only migrate, ingest and eval. The line predates this story and was
      not touched by it, but the Commands rewrite made that block the
      authoritative list, so the omission now reads as a contradiction.
      Resolving it needs a decision on whether eval-real is a separate target
      or a mode of `make eval`.
    location: >-
      CLAUDE.md:126
    severity: medium
  - summary: >-
      Nothing configures logging output, so apps/api's records reach a
      destination only through Python's last-resort stderr handler.
    evidence: |-
      api/main.py takes logging.getLogger("rocell.api") and calls
      logger.exception in the unhandled handler, and the 500 body tells the
      user the incident has been logged. No basicConfig or dictConfig exists
      anywhere in the workspace, and uvicorn's default log config does not
      configure the root logger. The record is still emitted — logging's
      lastResort handler writes ERROR and above to stderr with the traceback —
      so the promise holds, but with no timestamp, no logger name, no level
      control and no destination. Choosing a log configuration is a deployment
      decision this story has no requirement for.
    location: >-
      apps/api/api/main.py
    severity: medium
  - summary: >-
      The error envelope is a closed shape with no correlation identifier, so
      adding one later is a breaking change on both halves of the contract.
    evidence: |-
      shared_schema/errors.py sets extra="forbid" on ErrorBody and
      ErrorEnvelope, and isErrorEnvelope in the TypeScript twin rejects any key
      beyond code and message — both deliberately, and both tested. The
      consequence is that a request_id, which the generic 500 message gives the
      user nothing to quote and gives the log nothing to correlate against,
      cannot be added without changing and redeploying both sides together.
      Worth deciding before Epic 3, not after.
    location: >-
      shared/schema/shared_schema/errors.py
    severity: medium
  - summary: >-
      make dev's cleanup trap does not reach uvicorn's --reload worker, which
      can keep API_PORT bound after the developer stops the run.
    evidence: |-
      The trap runs `pkill -P $api_pid; kill $api_pid`, which reaches the uv
      wrapper and its direct children. uvicorn --reload runs the actual server
      in a grandchild, so it can survive and hold the port; the next `make dev`
      then fails the health gate with the misleading "port busy, or an import
      error" message. The usual fix is to start the API in its own process
      group and signal the group, but macOS ships no setsid, so this needs a
      portable approach rather than a one-line change.
    location: >-
      Makefile:37
    severity: low
  - summary: >-
      The two halves of shared/schema are each asserted against the contract
      independently; nothing checks them against each other.
    evidence: |-
      shared/schema/tests/test_errors.py and
      apps/web/src/__tests__/error-envelope.test.ts each encode the same closed
      shape separately, and README.md claims the two files "cannot drift apart
      unnoticed". No test feeds a Python-produced envelope through
      isErrorEnvelope or compares the two definitions, so the parity holds by
      review rather than by test. Closing it means running a JS runtime from
      pytest or fixturing generated bodies — a cross-language test harness
      decision.
    location: >-
      shared/schema/shared_schema/ts/errors.ts
    severity: low
---

<intent-contract>

## Intent

**Problem:** The repository holds only planning documents and a standalone POC — none of the six directories the architecture spine's Structural Seed names exist, there is no `Makefile`, and no styling source. Every later story in every epic is blocked on that foundation, and without a single token layer each UI story would invent its own colors and type scale.

**Approach:** Hand-build the six-directory monorepo (`apps/web`, `apps/api`, `shared/vision`, `shared/schema`, `infra`, `scripts/ingest`), each with a runnable, honestly-stubbed skeleton; render an `apps/web` app shell whose every style value comes from a CSS custom-property token layer generated from `DESIGN.md`; and wire a root `Makefile` whose `lint` and `test` targets pass green against that skeleton.

## Boundaries & Constraints

**Always:**
- The token layer (`apps/web/src/styles/tokens.css`) is the **only** place a raw color literal, font stack, radius, spacing step or shadow may appear. Components reference `var(--…)` (UX-DR1). A guard test enforces this.
- Token values are transcribed verbatim from `DESIGN.md` frontmatter: 11 colors, 6 type roles, 4 radii + DEFAULT, 10 spacing steps, the single navy-tinted elevation `0 2px 8px rgba(19, 27, 94, 0.08)`.
- Plus Jakarta Sans and JetBrains Mono are self-hosted (`@fontsource/*`) and each declares a fallback stack in the token layer (UX-DR2). Phosphor icons come from `@phosphor-icons/react` at `regular` weight only (UX-DR3).
- App bar is navy fill, white foreground, with a 3–4px accent-orange bottom stripe. Accent orange's foreground is navy (`#131B5E`), never white — white on orange is 2.63:1 and fails WCAG AA.
- Stack versions honour the spine: React 19.2.x, Vite 8.0.x, TypeScript 7.0.x, Python 3.12+, FastAPI 0.141.x.
- Glossary terms are PascalCase verbatim; `Product` and `Face` never appear in new code.
- `apps/web` holds no database or storage credential and no network call to anything but `apps/api` (AD-6).
- Every stub that is not yet implemented says so and exits non-zero — no stub silently reports success.
- Interactive elements meet the ≥44×44px touch-target floor and carry a visible focus state.

**Block If:**
- A pinned stack version cannot be installed at all (not merely a patch-level drift within the pinned minor).
- Honouring the token layer would require contradicting a `DESIGN.md` value rather than adding one.

**Never:**
- No auth, user schema, migration content, session handling, login UI, nav items, camera, or API business endpoint — those are Stories 1.2+ and Epics 2–3. Only a `/health` endpoint and an unauthenticated shell.
- No component library, no CSS framework, no second accent hue, no `localStorage`/`sessionStorage` usage.
- No port of `poc/tilematch/vision.py` into `shared/vision` in this story — the skeleton records the AD-1 invariant, it does not implement the pipeline.
- No PWA manifest/service worker, no CI pipeline, no IaC resources — all deferred by the spine or out of this story's ACs.
- No `size + category → code` mapping anywhere.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Token contract complete | `tokens.css` parsed | All 11 colors, 6 type roles, 5 radii, 10 spacing steps and the elevation shadow are defined as custom properties | Test fails naming each missing token |
| Raw hex in a component | Any file under `apps/web/src` except `tokens.css` containing a `#RRGGBB`/`#RGB` literal or an `rgb(`/`rgba(` literal | Guard test fails | Failure message names the offending file and matched text |
| Font fallback declared | `tokens.css` font-family tokens | Both families are followed by a non-empty fallback stack | Test fails naming the family with no fallback |
| App shell renders | `App` mounted in jsdom | App bar renders with its accent stripe element and the product name; main region renders | Render throw fails the test |
| Icon weight | Any Phosphor usage in `apps/web/src` | Uses `regular` weight (no `weight="fill"|"duotone"|"bold"|"thin"|"light"`) | Guard test fails naming the file |
| API health check | `GET /health` on the FastAPI app | `200` with `{"status": "ok"}` | Any other status fails the test |
| API error envelope | A raised `ApiError` handled by the app | Body is exactly `{"error": {"code": ..., "message": ...}}` | Shape mismatch fails the test |
| Vision skeleton import | `import shared_vision` | Imports and exposes the AD-1 invariant docstring plus `PIPELINE_VERSION` | ImportError fails the test |
| Ingest entrypoint | `python -m ingest` | Exits non-zero with an explicit "not implemented yet" message | — |
| Unimplemented make target | `make migrate` / `make ingest` / `make eval` | Prints which story delivers it and exits non-zero | — |
| Lint on a clean tree | `make lint` | Exit 0 | Non-zero exit; offending files named by ruff / oxlint / tsc |

</intent-contract>

## Code Map

The repository contains **no product code** — `apps/`, `shared/`, `infra/` and `scripts/` do not exist. Every path below is either read-only source-of-truth or a file this story creates.

**Read-only sources of truth (do not edit):**
- `_bmad-output/planning-artifacts/ux-designs/ux-rcl_camera_app-2026-09-08/DESIGN.md` -- YAML frontmatter is the literal token source: `colors` (11), `typography` (6 roles), `rounded` (sm/md/lg/full/DEFAULT), `spacing` (1–16), plus the Elevation & Depth section's `0 2px 8px rgba(19, 27, 94, 0.08)`. Body sections carry the navy-chrome / one-orange-action / red-is-destructive discipline and the verified contrast table.
- `_bmad-output/planning-artifacts/ux-designs/ux-rcl_camera_app-2026-09-08/EXPERIENCE.md` -- lines 42 and 150–153: bottom tab bar on mobile, sidebar at desktop/tablet, the same breakpoint as the table-density shift. Nav itself is role-conditional and arrives with auth; this story only establishes the shell's responsive frame.
- `_bmad-output/planning-artifacts/architecture/architecture-rcl_camera_app-2026-08-30/ARCHITECTURE-SPINE.md` -- lines 192–209 Structural Seed (the six directories and their one-line charters); lines ~178–190 Stack table (pinned versions); Consistency Conventions table (PascalCase glossary names, UUIDv4, ISO 8601 UTC, error envelope `{"error":{"code","message"}}`); AD-1 (`shared/vision` symmetry), AD-6 (web talks only to api).
- `_bmad-output/planning-artifacts/epics.md` -- lines 174–186: this story's three acceptance clauses verbatim.
- `AGENTS.md` -- Policy list and the Conventions block (ruff, type hints, no bare `except`; TS strict, no unexplained `any`; Conventional Commits; flag new dependencies).
- `poc/Makefile` -- the house style for a target list with a `help` default goal; mirror its shape, not its targets.
- `poc/pyproject.toml` -- shows the existing Python packaging idiom (`[project]`, `requires-python = ">=3.12"`, `[dependency-groups] dev`). `poc/` stays untouched and outside the new workspace.
- `poc/tilematch/vision.py` -- the future source for `shared/vision` (AD-1 says port it unchanged, later). Referenced only in the skeleton's docstring; **not** ported here.
- `.gitignore` -- already ignores `node_modules/`, `__pycache__/`, `.pytest_cache/`, `poc/*`; needs `dist/`, `.venv/`, `.ruff_cache/`, `*.egg-info/`, `coverage/`.

**Verified environment facts (probed in a scratchpad, 2026-09-17):**
- Available and installing cleanly: `react@19.2.8`, `react-dom@19.2.8`, `vite@8.0.16`, `typescript@7.0.2`, `vitest@5.0.1`, `jsdom@30.1.0`, `@testing-library/react@16.3.3`, `@vitejs/plugin-react@6.1.1`, `@phosphor-icons/react@2.1.10`, `@fontsource/plus-jakarta-sans@5.3.0`, `@fontsource/jetbrains-mono@5.3.0`, `oxlint@1.83.0`, `fastapi@0.141.1`, `ruff@0.16.8`. A Vite 8 build of React 19 + Phosphor + Fontsource and a Vitest 5 + jsdom render both pass.
- **ESLint cannot be used for TypeScript here.** `typescript@7.0.2` no longer exports the classic JS compiler API (its `exports` map is `./lib/version.cjs` plus `./unstable/*`), and `typescript-eslint@8.70.0` declares `peer typescript ">=4.8.4 <6.1.0"` — install fails outright, and ESLint core cannot parse `.ts` (`Parsing error: Unexpected token :`, verified). `oxlint` parses TS/TSX natively with no `typescript` dependency and flags real defects. See Design Notes.
- The developer machine's shared npm cache (`~/.npm/_cacache`) contains root-owned directories that make `npm install @phosphor-icons/react` fail with `EACCES`. This is a machine-level defect, not a repository one; `npm_config_cache` pointed at a writable directory installs cleanly. No workaround is committed.

**Files this story creates:** root `Makefile`, `pyproject.toml`, `.python-version`, `README.md`, `.gitignore` (edit); `apps/web/*`; `apps/api/*`; `shared/vision/*`; `shared/schema/*`; `infra/*`; `scripts/ingest/*`.

## Tasks & Acceptance

**Execution:**
- `.gitignore` -- add `dist/`, `.venv/`, `.ruff_cache/`, `*.egg-info/`, `coverage/`, `node_modules/` (keep existing entries) -- build output and virtualenvs must not enter version control.
- `pyproject.toml` (root) -- declare a `uv` workspace over `apps/api`, `shared/vision`, `shared/schema`, `scripts/ingest`, with shared `[tool.ruff]` (line length, `E,F,I,UP,B` + no-bare-except) and `[tool.pytest.ini_options]` collecting all member `tests/` directories -- one venv and one lint/test configuration for the whole Python side; `poc/` is deliberately excluded.
- `.python-version` -- pin `3.12` -- the spine's floor, so `uv` does not silently resolve a newer interpreter.
- `shared/schema/` -- `pyproject.toml`, `shared_schema/__init__.py`, `shared_schema/errors.py` defining the `{"error": {"code", "message"}}` envelope model and an `ApiError` exception; `shared_schema/ts/errors.ts` with the matching TypeScript type; `tests/test_errors.py` -- the cross-layer contract both `apps/api` and `apps/web` compile against.
- `shared/vision/` -- `pyproject.toml`, `shared_vision/__init__.py` carrying the AD-1 invariant as a module docstring, `PIPELINE_VERSION`, and a pointer to `poc/tilematch/vision.py` as the port source; `tests/test_skeleton.py` -- a runnable, importable skeleton that states the invariant without implementing the pipeline.
- `apps/api/` -- `pyproject.toml`, `api/__init__.py`, `api/main.py` (FastAPI app, `GET /health`, `ApiError` handler rendering the shared envelope), `tests/test_health.py`, `tests/test_error_envelope.py` -- a runnable service skeleton with the cross-cutting error contract already honoured.
- `scripts/ingest/` -- `pyproject.toml`, `ingest/__init__.py`, `ingest/__main__.py` whose `main()` prints that ingestion arrives with Epic 2 and returns exit code 1; `tests/test_entrypoint.py` -- runnable and honest about being unimplemented.
- `infra/` -- `README.md` (forward-only reversible migrations; the spine's deferred infra decisions listed as open), `migrations/.gitkeep` -- the directory exists with its conventions recorded, no IaC invented.
- `apps/web/package.json` -- React 19.2.x / Vite 8.0.x / TypeScript 7.0.x, `@phosphor-icons/react`, both `@fontsource` families; scripts `dev`, `build`, `test`, `lint`, `typecheck` -- the pinned front-end toolchain.
- `apps/web/tsconfig.json`, `apps/web/vite.config.ts` -- TS strict mode, bundler resolution, `react-jsx`; Vite with the React plugin and the Vitest jsdom environment -- strict types and a single config for build and test.
- `apps/web/.oxlintrc.json`, `apps/web/index.html`, `apps/web/src/main.tsx` -- lint config, document shell, and the React root that imports the font faces and the token layer once.
- `apps/web/src/styles/tokens.css` -- every `DESIGN.md` token as a `:root` custom property (colors, type roles as font-size/weight/line-height/letter-spacing triples, radii, spacing, elevation, font stacks with fallbacks) -- the single styling source; the only file allowed to hold literal values.
- `apps/web/src/styles/global.css` -- reset plus base typography wired to the tokens -- no component invents a base style.
- `apps/web/src/components/AppBar.tsx` + `AppBar.module.css` -- navy bar, white foreground, a Phosphor `regular` icon, and the 3–4px accent stripe along the bottom edge -- UX-DR4/DR5's first render, token-only styling.
- `apps/web/src/components/AppShell.tsx` + `AppShell.module.css` -- app bar plus a main region and the mobile/desktop breakpoint frame the later nav slots into -- the shell every subsequent UI story mounts inside.
- `apps/web/src/App.tsx` -- compose `AppShell` with a placeholder main region naming the app -- something real to render and test.
- `apps/web/src/__tests__/tokens.test.ts` -- assert every `DESIGN.md` token is present in `tokens.css`, that both font families declare a fallback, and that the accent's foreground token is navy -- makes the token contract a failing test rather than a convention.
- `apps/web/src/__tests__/no-raw-values.test.ts` -- walk `apps/web/src`, excluding `tokens.css`, and fail on any hex, `rgb(`/`rgba(`, or non-`regular` Phosphor weight -- UX-DR1 and UX-DR3 enforced mechanically.
- `apps/web/src/__tests__/app-shell.test.tsx` -- render `App` in jsdom and assert the app bar, its stripe element, and the main region are present -- proves the shell actually mounts.
- `Makefile` -- `help` (default goal), `setup`, `dev`, `lint`, `test`, plus `migrate`/`ingest`/`eval` that name the story delivering them and exit 1 -- the commands `CLAUDE.md` promises, with unimplemented ones failing loudly.
- `README.md` -- the six directories and their charters, the setup/lint/test commands, and the ESLint-vs-TypeScript-7 note -- orientation for the next developer.

**Acceptance Criteria:**
- Given a clean checkout, when the repository is listed, then `apps/web`, `apps/api`, `shared/vision`, `shared/schema`, `infra` and `scripts/ingest` all exist, and each Python member is importable and each has at least one passing test.
- Given a clean checkout, when `make setup` then `make lint` is run, then it exits 0 having run ruff (check and format) over the Python workspace and oxlint plus `tsc --noEmit` over `apps/web`.
- Given a clean checkout, when `make setup` then `make test` is run, then it exits 0 having run the full pytest workspace suite and the `apps/web` Vitest suite, with zero skipped-because-unimplemented tests.
- Given the running dev server, when `apps/web` is loaded, then the app shell paints with the navy app bar, its accent-orange stripe, Plus Jakarta Sans applied, and no console error.
- Given `apps/web/src`, when any file other than `tokens.css` is inspected, then it contains no color literal and no font/radius/spacing literal — only `var(--…)` references.
- Given `make migrate`, `make ingest` or `make eval`, when run, then each prints the story or epic that delivers it and exits non-zero rather than reporting success.

## Design Notes

**Why oxlint instead of ESLint.** `CLAUDE.md` describes `make lint` as "ruff + eslint + tsc". ESLint is not available for this stack: the spine pins TypeScript 7.0.x, whose npm package no longer exports the compiler API that `typescript-eslint` is built on, and `typescript-eslint@8.70.0` refuses to install against it (`peer typescript ">=4.8.4 <6.1.0"`). ESLint core cannot parse TypeScript unaided. `oxlint` parses TS/TSX natively, needs no `typescript` dependency, and was verified to catch real defects (`no-unused-vars`, `no-constant-condition`) in this exact tree. It runs with `--deny-warnings` so warnings gate the build. Revisit when `typescript-eslint` ships TS-7 support; the `Makefile` target is the only place that changes.

**Why plain CSS custom properties, not Tailwind.** `DESIGN.md` explicitly marks Tailwind as an implementation-choice assumption, not a constraint, and `AGENTS.md` asks that new dependencies be flagged. A `:root` custom-property layer plus CSS Modules satisfies "the token layer is the only styling source" with zero extra dependencies, and the no-raw-values guard test is the enforcement Tailwind's config would otherwise imply.

**Token shape.** Each type role is emitted as a group so a component consumes one role, never four loose values:

```css
:root {
  --color-accent: #F58025;
  --color-accent-foreground: #131B5E; /* navy: 5.94:1. White is 2.63:1 and fails. */
  --font-sans: 'Plus Jakarta Sans', ui-sans-serif, system-ui, 'Segoe UI', sans-serif;
  --type-heading-size: 18px;
  --type-heading-weight: 700;
  --type-heading-line: 1.3;
  --elevation-card: 0 2px 8px rgba(19, 27, 94, 0.08);
}
```

**Honest stubs.** `shared/vision`, `scripts/ingest`, and the `migrate`/`ingest`/`eval` targets are deliberately non-functional. Each states what it is waiting on and fails rather than returning success, so a later story cannot mistake an empty stub for working code.

## Verification

**Commands:**
- `make setup` -- expected: `uv sync` resolves the workspace on Python 3.12 and `npm install` completes in `apps/web`.
- `make lint` -- expected: exit 0; ruff check + ruff format --check clean, oxlint clean with `--deny-warnings`, `tsc --noEmit` clean.
- `make test` -- expected: exit 0; every pytest member suite and the Vitest suite pass, none skipped.
- `make -n migrate` / `make migrate` -- expected: non-zero exit with a message naming the delivering story.
- `npm --prefix apps/web run build` -- expected: a production bundle builds with no error.

**Manual checks (if no CLI):**
- `apps/web/src/styles/tokens.css` holds every `DESIGN.md` value and no component file holds any literal — the guard test asserts this, but confirm the token values themselves match `DESIGN.md` character for character.

## Spec Change Log

No entries — no `bad_spec` finding was raised, so the spec was never amended and the code was never re-derived.

## Review Triage Log

### 2026-09-17 — Review pass

- intent_gap: 0
- bad_spec: 0
- patch: 22: (high 3, medium 6, low 13)
- defer: 7: (high 0, medium 4, low 3)
- reject: 6: (high 0, medium 1, low 5)
- addressed_findings:
  - `[high]` `[patch]` `apps/api` claimed in its docstring and in `README.md` that every error response is the shared envelope, but only `ApiError` was handled — 404/405/422 and unhandled exceptions still returned FastAPI's `{"detail": ...}`. Registered handlers for `StarletteHTTPException`, `RequestValidationError` and bare `Exception`, with a fixed generic 500 message that never echoes internal text; added tests for 404, 405, 422 and 500, two of which assert a planted secret never reaches the response body.
  - `[high]` `[patch]` The UX-DR1 guard had holes that let through exactly what it exists to stop — `color: white` (the documented 2.63:1 AA failure on accent orange), every length unit outside px/rem/em, unitless JSX inline-style numbers, and any value on a line containing `@media`. Extended the colour and dimension patterns, added JSX inline-style detection, and replaced the `@media` exemption with an assertion that each `min-width` equals `--breakpoint-md`. The first fix attempt was itself vacuous (anchored to line start); caught and corrected by re-injecting the violation.
  - `[high]` `[patch]` `.gitignore` carried no secret or junk patterns despite AGENTS.md's no-committed-secrets policy and this repo's own history of committing `.DS_Store`. Added `.env`, `.env.*`, `*.pem`, `*.key`, `*.p12`, `*.pfx`, `.DS_Store`, `*.log`.
  - `[medium]` `[patch]` `/docs`, `/redoc` and `/openapi.json` were exposed unauthenticated on a service whose primary stated threat is catalogue exfiltration. Disabled all three and asserted they 404.
  - `[medium]` `[patch]` A dangling `var(--…)` reference shipped fully green — renaming `--icon-size` left lint, typecheck and all tests passing while the app bar icon broke. Every `var(--…)` referenced under `apps/web/src` is now checked against the declarations in `tokens.css`.
  - `[medium]` `[patch]` The API tests built their own app via `create_app()`, so the module-level `app` that `make dev` serves was exercised by nothing. `api.main.app` is now tested directly.
  - `[medium]` `[patch]` `make dev` used `trap 'kill 0'`, which signals the whole process group and would take down a parent `make` or CI shell, and never noticed a dead backend. Now traps only the API's own pid and its children, polls `/health`, and refuses to start Vite against a backend that did not come up.
  - `[medium]` `[patch]` `CLAUDE.md` was made stale by this change — it still said no `Makefile` existed and described `make lint` as "ruff + eslint + tsc". Rewritten to the real target list, with the oxlint rationale pointed at from where an agent will actually read it.
  - `[medium]` `[patch]` The 44×44px touch-target floor was a no-op for links (`min-height` does not apply to inline elements) while the comment above it asserted the floor held. Links are now `inline-flex`.
  - `[low]` `[patch]` `--radius` restated `--radius-md`'s literal instead of referencing it; now `var(--radius-md)`.
  - `[low]` `[patch]` `tokens.test.ts` hardening — CRLF normalisation, escaped regex metacharacters in token names, and the elevation shadow anchored to the `## Elevation & Depth` section instead of the first matching backticked span in the document.
  - `[low]` `[patch]` `tests/test_make_targets.py` launched a nested `make` inheriting `MAKEFLAGS` and the jobserver fds; now strips `MAKEFLAGS`/`MAKELEVEL`, skips cleanly without `make` on PATH, and fails rather than errors on timeout.
  - `[low]` `[patch]` The ingest entrypoint test could pass for the wrong reason, since `ModuleNotFoundError` also exits non-zero. Now pins `cwd` and asserts `returncode == 1` exactly alongside the message.
  - `[low]` `[patch]` Five pytest testpaths with no `__init__.py` would collide on the first shared basename. Added `--import-mode=importlib --strict-markers --strict-config`.
  - `[low]` `[patch]` `ApiError` accepted a blank code or message, producing an envelope a client cannot branch on. Now rejected.
  - `[low]` `[patch]` `isErrorEnvelope` narrowed bodies the Python side rejects (arrays, extra keys). Tightened, with five new rejection cases.
  - `[low]` `[patch]` The source walk followed symbolic links and could recurse until the test run died. Symlinks are now skipped.
  - `[low]` `[patch]` `index.html` set `viewport-fit=cover` but nothing consumed `env(safe-area-inset-*)`, so the app bar rendered under the status bar on a notched phone — this product's primary device. Added token-driven inset-aware padding.
  - `[low]` `[patch]` Node's version was pinned in prose only while Python got `.python-version`. Added `engines.node` and a root `.nvmrc`.
  - `[low]` `[patch]` `apps/api` declared a dependency on `shared-vision` that nothing imported. Removed.
  - `[low]` `[patch]` `README.md` credited `shared/vision` with the shared upload-intake path while the module never mentioned it. AD-7's intake path is now recorded in the module docstring.
  - `[low]` `[patch]` No `<noscript>` and no skip-to-main link despite the shell already establishing a `header`/`main` structure. Both added, with the skip link tested for order, target and focusability.


### 2026-09-17 — Review pass (follow-up)

- intent_gap: 0
- bad_spec: 0
- patch: 16: (high 0, medium 9, low 7)
- defer: 3: (high 0, medium 1, low 2)
- reject: 19: (high 0, medium 5, low 14)
- addressed_findings:
  - `[medium]` `[patch]` The 500 body told the user "The incident has been logged" while `apps/api` imported no logging, configured no logger and wrote nothing anywhere — the one message a user gets was false, and the traceback (withheld from the response on purpose) was lost outright. Added a `rocell.api` logger, `logger.exception` in the unhandled handler, and a test that plants a marker in the exception and asserts it reaches the log while staying out of the response body.
  - `[medium]` `[patch]` `http_exception_handler` rebuilt the response from scratch and dropped `exc.headers`, so Starlette's `Allow` vanished from every 405 (RFC 9110 makes it mandatory) and the `WWW-Authenticate` challenge on Story 1.3's 401s would have vanished the same way. Headers are now carried through, with tests for both.
  - `[medium]` `[patch]` The two halves of the error contract disagreed: `errors.ts` documents that extra keys are "rejected here as the Python model rejects them", but `ErrorBody`/`ErrorEnvelope` were plain models with pydantic's default `extra='ignore'`, and the existing test only inspected `model_dump()` output, which drops extras. Both models are now `extra="forbid"`, with three rejection tests.
  - `[medium]` `[patch]` The 44×44px touch-target floor was both too broad and half-implemented: `a[href] { min-height; display: inline-flex }` caught every link in running prose (turning it into a 44px box that cannot wrap) and every checkbox and radio, while `min-height` alone makes a 44×1 target, not the 44×44 the spec states. The floor now applies on both axes to controls that are genuinely tap targets, prose links are excluded by name with the reason recorded, and the skip link — the one link that *is* an affordance — opts in via `composes: touchTarget from global`.
  - `[medium]` `[patch]` `vite.config.ts` hardcoded the dev proxy target at `:8000` while the Makefile exposes `API_PORT ?= 8000`, so `make dev API_PORT=9000` started the API on 9000, health-checked it there, and then served a front end proxying to a dead port. The Makefile now exports `API_PORT` and Vite reads it (verified: `make _probe API_PORT=9000` reached the child process).
  - `[medium]` `[patch]` Deleting `import './styles/tokens.css'` from `main.tsx` shipped a completely unstyled app with lint, typecheck, all tests and the production build green — nothing imports `main.tsx` in a test, and the two token tests read the file off disk rather than through the entry point. `styling-wiring.test.ts` now asserts the entry point imports both stylesheets and mounts into the element `index.html` actually provides.
  - `[medium]` `[patch]` Renaming a class in a CSS module shipped green too: a module is typed as an index signature, so `styles.appBar` silently becomes `undefined` and the rule is simply not applied. The new suite cross-checks `styles.X` references against declared class names in both directions, so a rename and a dead rule each fail.
  - `[medium]` `[patch]` The app bar's colours — the intent's one explicit appearance constraint — were asserted nowhere: the dangling-reference check only asks whether a token exists, never whether a rule uses the right one, so swapping `--color-primary` for `--color-accent` would have rendered white-on-orange (2.63:1, the documented AA failure) with a fully green suite. The fill, foreground and stripe tokens are now asserted.
  - `[medium]` `[patch]` `--touch-target-min` and `--app-bar-stripe-height` carry the two numeric constraints the spec states verbatim (≥44px, 3–4px) and no test read either value — they sit outside `tokens.test.ts`'s DESIGN.md walk, so the stripe could become 40px and only the dangling-reference check would run. Both are now bounded, written as bare numbers so the assertions do not themselves trip the no-raw-values guard.
  - `[low]` `[patch]` `ApiError` validated its code and message but not its status, so `status_code=200` constructed fine and returned an error envelope under a success status that `apps/web` would read as success. Now restricted to 4xx/5xx, same reasoning as the existing blank-string rejection.
  - `[low]` `[patch]` `FALLBACK_CODE` was dead as far as the suite knew — only mapped statuses were exercised. Added a 503 case.
  - `[low]` `[patch]` A dimension entering through a component prop (`<Scan size={24} />`) was invisible to every CSS-shaped pattern in the guard; `AppBar.tsx`'s docstring claimed the convention was held while only the comment held it. Sizing props on `.tsx` files are now checked.
  - `[low]` `[patch]` Media-query range syntax (`@media (width >= 900px)`) evaded both guard checks at once — the dimension check blanks preludes wholesale and the breakpoint check matched only `min-width:`/`max-width:`. Every length in every prelude is now checked against the declared breakpoint, whatever syntax it arrives in.
  - `[low]` `[patch]` Both token readers resolve a custom property by its *first* declaration while the browser applies the last, so a duplicate would make every assertion about that token describe a value nothing renders with. Added a no-duplicates check over `tokens.css`.
  - `[low]` `[patch]` `stripComments` blanked from `//` to end of line in CSS, where `//` is not a comment — `background: url(//host/x.png) #ABCDEF` took its own literal out of the guard's view. Line-comment stripping now applies to `.ts`/`.tsx` only.
  - `[low]` `[patch]` `.shell` was not a positioned ancestor for the absolutely-positioned skip link, which therefore resolved against the initial containing block and would have drifted the moment anything above it gained a position or transform. Added `position: relative` with the reason recorded.
  - Also corrected during this pass: the new wiring helpers initially ran at describe-collection time, so a missing rule removed eleven tests from the run instead of failing one. Caught by injecting the rename; the lookups moved into the test bodies. Every patch above was verified by re-injecting the defect and confirming a named test fails.


### 2026-09-17 — Review pass (second follow-up)

- intent_gap: 0
- bad_spec: 0
- patch: 9: (high 0, medium 4, low 5)
- defer: 5: (high 0, medium 3, low 2)
- reject: 30: (high 0, medium 11, low 19)
- addressed_findings:
  - `[medium]` `[patch]` `composes: touchTarget from global` was resolved by nobody. CSS modules append the literal name and never check that a rule declares it; `styling-wiring.test.ts` only walks `*.module.css`, and the dangling-reference check only follows `var()`. Deleting `.touchTarget` from `global.css` stripped the skip link — the shell's one interactive affordance — of its 44×44 floor with lint, typecheck, the production build and all 170 tests green. Every `composes: … from global` is now checked against `global.css`, and that file's two unasserted rules (the touch-target floor on both axes, the `:focus-visible` outline) are pinned. Three separate injections confirmed.
  - `[medium]` `[patch]` The named-colour guard — the check that exists specifically to stop `color: white` on accent orange, the documented 2.63:1 AA failure — was anchored to the start of a line, so a rule written on one line (`.x { color: white; }`) put its first declaration after `{` and sailed straight past. Re-anchored to a declaration boundary; verified by injecting exactly that line.
  - `[medium]` `[patch]` `main.tsx` hand-imports one `@fontsource` stylesheet per weight and `tokens.css` declares six type roles at five sans weights and one mono weight, with nothing tying the two together. Drop an import, or add a role at a weight nothing imports, and the browser synthesises the face — visibly wrong type, no error, no failing test. The weights imported per family are now compared against the weights the type roles ask for.
  - `[medium]` `[patch]` `ApiError` could not carry response headers while `HTTPException` could, and `api_error_handler` built its own response instead of going through `_envelope` — the exact drift `http_exception_handler`'s docstring warns about two functions below. Story 1.3's obvious idiom, `raise ApiError(code="unauthorized", …, status_code=401)`, would have produced a 401 with no `WWW-Authenticate` challenge. `ApiError` now takes `headers`, the handler routes through `_envelope`, and the challenge is asserted end to end.
  - `[low]` `[patch]` `magnitude()` discarded the unit, so the two constraints stated in px — the ≥44×44px touch floor and the 3–4px stripe — were asserted as bare numbers and `44ch` or `4%` would have passed. The unit is now required to be `px`.
  - `[low]` `[patch]` `token()` followed `var()` references with no cycle guard, so a circular chain in `tokens.css` recursed until the worker died, taking every test in the file down instead of failing the one assertion that asked for the value. Same class as the collection-time lookups fixed in the previous pass.
  - `[low]` `[patch]` The no-raw-values walk collected `.css`, `.ts` and `.tsx` only, while the rule it enforces is about any source file under `apps/web/src`. A `.js`, `.jsx`, `.mjs` or `.cjs` file added later would have been invisible to every check. Extended, with line-comment stripping still correctly withheld from plain CSS.
  - `[low]` `[patch]` `vite.config.ts` read the proxy port as `process.env['API_PORT'] ?? '8000'`, and `??` does not fall back for an empty string, so `make dev API_PORT=` yielded the invalid target `http://127.0.0.1:`. Now validated as digits before use.
  - `[low]` `[patch]` `index.html` opts into `viewport-fit=cover` and `AppBar.module.css` offsets for the insets, but the skip link — the first tab stop on every screen — sat at `inset-block-start: 0` with a flat margin and would land under the status bar on a notched phone, this product's primary device. Its offset is now inset-aware.
  - Also examined and not patched: a claim that `.5rem` evades the dimension guard (disproved — `\b` matches after the dot, and the literal is caught), and a claim that an `HTTPException` outside 4xx/5xx returns a bare unenveloped 500 (disproved by injection — `unhandled_error_handler` is registered for `Exception` and catches the raise from inside the other handler). The second was kept as a test, since that recovery is what makes the module's "every error response is the envelope" claim true and nothing had pinned it. Every patch above was verified by re-injecting the defect and confirming a named test fails.

## Auto Run Result

Status: done

**Summary.** Story 1.1 was already implemented and reviewed twice; this run was the follow-up review pass its `followup_review_recommended: true` asked for. No intent gap and no spec defect were found — the scaffold, the token layer and the six directories all match the contract — so no code was re-derived. Nine patches were applied, all of them to guards and contracts rather than to the shell itself, and five items were deferred.

The theme of this pass is the same one the previous two closed repeatedly: a styling or contract link that can be broken while `make lint`, `make test` and `npm run build` all stay green. Four such links were still open — `composes: … from global`, the one-line CSS form of the named-colour rule, the `@fontsource` weight imports, and `ApiError`'s missing headers — and each is now pinned by a test that was watched to fail.

**Files changed in this pass:**

- `shared/schema/shared_schema/errors.py` — `ApiError` accepts and stores `headers`, so an error raised by our own code can carry the `WWW-Authenticate` or `Allow` its status requires.
- `apps/api/api/main.py` — `api_error_handler` routes through `_envelope` and passes the error's headers through, instead of building a header-less response of its own.
- `apps/api/tests/test_error_envelope.py` — five tests: a 401 challenge surviving to the client, a header-less error still rendering the envelope, and three statuses outside 4xx/5xx still arriving as an envelope.
- `apps/web/src/__tests__/styling-wiring.test.ts` — new `composes … from global` resolution check, the `global.css` touch-target and focus-visible rules asserted, `@fontsource` imports compared against the type roles' weights, `magnitude()` now requires px, `token()` guards against a circular reference.
- `apps/web/src/__tests__/no-raw-values.test.ts` — named-colour check re-anchored to a declaration boundary; the walk covers the JS family of extensions as well.
- `apps/web/vite.config.ts` — the dev proxy port is validated as digits before use.
- `apps/web/src/components/AppShell.module.css` — the skip link's offset accounts for the safe-area insets `index.html` opts into.

**Review findings breakdown:** 9 patches applied (4 medium, 5 low); 5 items deferred (3 medium, 2 low); 30 rejected. No finding required a spec amendment or a code re-derivation.

**Follow-up review recommendation:** `true`. Patched this pass: 0 high, 4 medium, 5 low. Score = 3 × 4 + 1 × 5 = 17, at or above the threshold of 5, so the flag stays set.

Worth reading alongside that number: this is the third consecutive pass over an implementation no pass has changed, and severity is falling (3 high, then 0, then 0) while the findings converge on one class — a link that can be broken while everything stays green. A fourth pass will most likely find more of the same, each a little narrower. The larger remaining risks are not reachable by another textual review pass at all; they are in residual risks below.

**Verification performed:**

- `make lint` — exit 0. ruff check and `ruff format --check` clean over 17 files; oxlint clean with `--deny-warnings`; `tsc --noEmit` clean.
- `make test` — exit 0. 58 pytest (was 53) and 176 vitest (was 170), none skipped.
- `npm --prefix apps/web run build` — production bundle built, 195.74 kB / 61.75 kB gzipped.
- `make migrate` — exits non-zero, naming Story 1.2.
- Each of the nine patches was verified by re-injecting the defect it fixes and confirming a named test fails, then restoring: `.touchTarget` renamed, `min-width` removed, the `:focus-visible` outline removed, a `@fontsource` weight import deleted, `--touch-target-min` given a `ch` unit, `color: white` written as a one-line rule, and `api_error_handler` reverted to its own response. The two findings that did not survive injection were dropped rather than patched, and are recorded in the triage log.
- `API_PORT` fallback checked directly against the expression: empty → `:8000`, `9000` → `:9000`.

**Residual risks:**

- The styling assertions remain textual. `vite.config.ts` sets `css: false`, so jsdom applies no stylesheet and nothing in the suite parses CSS or reads a computed style. A syntactically broken `tokens.css`, a rule whose selector matches nothing, and anything cascade- or specificity-dependent still pass every check. This is the ceiling of the current approach, not a gap within it, and moving past it is a test-infrastructure decision.
- `make lint` and `make test` are the whole contract and nothing runs them automatically — already deferred, and it is what makes each of this pass's guards worth only as much as a developer's discipline.
- The safe-area fix and the app-bar colours are verified as source text, never rendered on a device. The notched-phone behaviour this pass corrected has not been seen on a notched phone.
