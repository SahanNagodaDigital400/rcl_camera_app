# Rocell Tile Scanner

Internal PWA that identifies a ceramic tile from a phone camera photo and returns the matching
Code (the catalogue file name), its reference image, Size and Category. Rocell staff only,
admin-provisioned accounts, online-only.

This is an **image retrieval** system, not a classifier: the catalogue changes constantly, so
nothing here is trained over product categories.

```
Index time:  ReferenceImage -> preprocess -> embed -> pgvector
Scan time:   phone photo    -> preprocess -> embed -> search -> top 3
```

Both paths call the *same* code in `shared/vision`. See AD-1 below.

## Layout

| Directory | Charter |
|---|---|
| `apps/web` | React PWA — capture UI, results, scan history, admin screens. Talks only to `apps/api`, holds no database or storage credential (AD-6). |
| `apps/api` | FastAPI service — auth, scan submission, admin user/catalogue endpoints, audit log. Every live mutation flows through here. |
| `shared/vision` | Crop, colour management, preprocessing and embedding, plus the shared upload-intake path. Called identically by `apps/api` and `scripts/ingest`. |
| `shared/schema` | Types and contracts shared between `apps/web` and `apps/api` — today, the API error envelope, defined once in Python and once in TypeScript. `apps/web` compiles against the TypeScript half (imported as `@rocell/schema/*`), so the two halves cannot drift apart unnoticed. |
| `infra` | IaC, migrations, deployment config. See `infra/README.md`. |
| `scripts/ingest` | Drive → index batch ingestion. The one pre-launch exception to "all mutation flows through `apps/api`". |

`poc/` is a standalone proof of concept with its own venv, Makefile and data. It is not part of
this workspace and is not linted, tested or built by the commands below.

## Getting started

Requires [uv](https://docs.astral.sh/uv/), Node 22.12+ (`.nvmrc`) and Python 3.12
(`.python-version`; uv will fetch the interpreter if it is missing).

```bash
make setup    # uv workspace venv + apps/web npm install
make dev      # apps/api on :8000, apps/web on :5173
make lint     # ruff check + ruff format --check, oxlint, tsc --noEmit
make test     # pytest workspace suite + apps/web vitest suite
make build    # production build of apps/web
```

`make migrate`, `make ingest` and `make eval` exist but are not implemented; each names the story
or epic that delivers it and exits non-zero. Run `make` with no target for the full list.

## Design tokens

`apps/web/src/styles/tokens.css` is the **only** file in `apps/web/src` allowed to hold a literal
colour, font stack, radius, spacing step or shadow. Every component references `var(--…)`.

The values are transcribed from the YAML frontmatter of
`_bmad-output/planning-artifacts/ux-designs/ux-rcl_camera_app-2026-09-08/DESIGN.md`, and two tests
keep it that way:

- `src/__tests__/tokens.test.ts` re-reads `DESIGN.md` and asserts every colour, type role, radius,
  spacing step and the elevation shadow is declared, that both font families carry a fallback
  stack, and that the accent's foreground is navy (white on orange is 2.63:1 and fails WCAG AA).
- `src/__tests__/no-raw-values.test.ts` walks `src` and fails on a colour literal (hex, `rgb()`
  and friends, or a named colour such as `white`), a dimension literal, a bare number in a JSX
  inline style, a font family named directly, or a Phosphor icon given a `weight` — icons are
  `regular` (outline) weight throughout, which is the library default. It also fails on a
  `var()` reference to a token `tokens.css` does not declare, and on a media query written at a
  width the token layer does not declare, since CSS cannot read a custom property inside one.

Fonts are self-hosted through `@fontsource`; nothing is fetched from a third-party font CDN.

## A note on ESLint

`make lint` runs **oxlint**, not ESLint, over `apps/web`. The architecture spine pins TypeScript
7.0.x, whose npm package no longer exports the classic JS compiler API that `typescript-eslint` is
built on — `typescript-eslint@8.70.0` declares `peer typescript ">=4.8.4 <6.1.0"` and refuses to
install against it, and ESLint core cannot parse `.ts` unaided. oxlint parses TS/TSX natively,
needs no `typescript` dependency, and runs with `--deny-warnings` so warnings gate the build.
Revisit when `typescript-eslint` ships TypeScript 7 support; the `Makefile` target and
`apps/web/package.json` are the only places that change.

## The invariant that matters most (AD-1)

Index-time and query-time preprocessing and embedding must be **byte-for-byte identical**. They
live in one module, `shared/vision`, and both pipelines call it unwrapped. Never fork it, never
reimplement it, never optimise one side only — an asymmetry raises no error and fails no test that
is not looking for it; it just quietly destroys match accuracy.

Any change to `shared/vision` invalidates the stored index: bump `PIPELINE_VERSION`, re-index, and
say so in the pull request.

## Further reading

- `CLAUDE.md` — stack, domain vocabulary, source-data quirks, testing approach.
- `AGENTS.md` — security policy (non-negotiable), conventions, known pitfalls.
- `_bmad-output/planning-artifacts/architecture/` — the architecture spine and its decisions.
- `_bmad-output/planning-artifacts/ux-designs/` — `DESIGN.md` (tokens) and `EXPERIENCE.md` (flows).
