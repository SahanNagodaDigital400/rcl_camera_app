# CLAUDE.md

Guidance for Claude Code when working in this repository. Cross-agent policy, security requirements, and known pitfalls are in `AGENTS.md` — read that first; this file adds Claude-facing implementation depth: stack, layout, commands, domain model, and testing approach.

## What this is

Rocell Tile Scanner — an internal PWA that identifies a ceramic tile from a phone camera photo and returns the matching product file name, reference image, size and design.

Internal Rocell staff only. No public sign-up. Online-only (no offline scanning).

## Core architecture

This is an **image retrieval** system, not a classifier. Do not propose or implement a trained classification model over product categories — the catalogue changes constantly and retraining per change is a non-starter.

Two pipelines share one vector index:

```
Index time:  reference image → preprocess → embed → pgvector
Scan time:   phone photo     → preprocess → embed → search → top 3
```

**The single most important invariant in this codebase:** index-time and query-time preprocessing and embedding must be byte-for-byte identical. They live in one shared module (`shared/vision/`) and are called by both paths. Never fork, never reimplement, never "optimise" one side only. Any asymmetry silently destroys accuracy and will not show up as an error. (Standing rule — see `AGENTS.md` Known pitfalls.)

## Stack

| Layer | Choice |
|---|---|
| Front end | React PWA, TypeScript, Vite |
| Camera | `getUserMedia`, canvas downscale to ~1024px before upload |
| API | Python, FastAPI |
| Model serving | ONNX Runtime (DINOv2 backbone), CPU inference |
| Database | Postgres + `pgvector` |
| Object storage | S3-compatible |
| Auth | Argon2id, HTTP-only session cookies |

**Do not add a dedicated vector database.** ~10k vectors is small. `pgvector` handles this comfortably. Pinecone, Milvus, Qdrant and friends add an operational dependency for zero gain here. If you think the index has outgrown Postgres, measure first and raise it rather than swapping it out.

## Repo layout

```
apps/web/          React PWA
apps/api/          FastAPI service
shared/vision/     Preprocessing + embedding (used by BOTH pipelines)
shared/schema/     Shared types
infra/             IaC, migrations
scripts/ingest/    Drive → index ingestion
```

## Commands

```bash
make setup          # uv workspace venv + apps/web npm install
make dev            # api + web with hot reload
make lint           # ruff check + ruff format --check, oxlint, tsc --noEmit
make format         # apply ruff's formatting and import fixes
make test           # full suite (pytest workspace + apps/web vitest)
make build          # production build of apps/web
```

Not implemented yet — each names the story or epic that delivers it and exits non-zero rather
than reporting success:

```bash
make migrate        # apply migrations                    -- Story 1.2
make ingest         # run catalogue ingestion             -- Epic 2
make eval           # accuracy harness                    -- Epic 2
```

Run `make lint` and `make test` before considering any change complete.

`make lint` runs **oxlint**, not ESLint: TypeScript 7.0.x no longer exports the compiler API
`typescript-eslint` is built on, so ESLint cannot lint this stack at all. Full rationale in
`README.md` ("A note on ESLint"). `poc/` has its own `Makefile` and venv and is outside this
workspace — none of the targets above touch it.

## Domain vocabulary

Get these right — they are not interchangeable.

- **Size** — e.g. `45X90`, `60X60`. The top-level folder.
- **Category** — a range or pattern name, e.g. `CREMA MARMOL`, `ASTORIA`, `POLISH`. The second-level folder. Previously called "design"; the field in `meta.json` is still `design`/`product` for index compatibility.
- **Tile** — **one file. The unit of identity.** Every file inside a category folder is a different tile, and each tile has exactly one reference image.
- **Code** — the file name, cleaned. `RP.CMA.0001DJ.SM.0T`. This identifies the tile, and it is the answer the app returns.

The tree is exactly three levels deep: `<SIZE>/<CATEGORY>/<file>`. 381 files = 381 tiles in 76 category folders; 96% of files live in folders holding 2–26 siblings.

**The varying numeric segment in a code (`0011`, `0013`, `0014` in `45X90/POLISH`) distinguishes different tiles, not faces of one tile.** Earlier revisions of this file described a "Face — one manufactured surface variation within a product" and defined Product as `size + design`. That was wrong, confirmed against the source tree and with Rocell. Do not reintroduce it:

- Never treat two files in one folder as the same thing.
- Never deduplicate or group candidates by `size + category` — that hides correct answers.
- An eval that scores `size + category` as the truth is counting "found a different tile from the same range" as correct. Score against the exact file.

## Source data quirks

The reference set comes from a Google Drive tree with real inconsistencies. The ingestion pipeline must **validate, not assume**.

- Top level mixes size folders (`40X40`, `45X90`) with category folders (`Cement`, `Earthen`, `Fashion`, `Mono Colour`, `Randomness`, `Speckled`). Depth is not uniform.
- **Five** naming conventions coexist, not two — verified against real files and pinned in a working POC (`poc/tests/test_catalog.py`):
  - `Copy of RP.CMA.0008DJ.SM.0T.jpg` — structured code, face embedded as a segment
  - `Copy of 77DH.MA_F3.jpg` — face as an underscore-`F` suffix
  - `Copy of 1Jk.jpg` / `Copy of 61M.jpg` — bare face number, no code
  - `Copy of 279.jpg` — bare integer
  - `Copy of 6LD.MA Quarry Stone Natural.jpg` — free text trailing the code
  - Dash-delimited names (`RC-001-OHA-156-MA-J2`) carry **no recoverable trailing number** — return `None` rather than guessing; the Code is still kept, and the Code alone identifies the tile.
- File extensions include `.tif` alongside `.jpg` — not mentioned in earlier planning docs, confirmed present in the real source tree.
- Strip the `Copy of ` prefix and the extension before storing or displaying.
- Reference images range **384 KB to 96 MB** (up to 19276×9638 px) — not "2–6.5 MB," which understated the real range by more than an order of magnitude; decode to a capped long edge (2048px) before any further processing. Query images are phone photos. This domain gap is the main accuracy risk — apply aggressive augmentation at index time (lighting, white balance, blur, perspective).
- **Most reference images are CMYK press files, not sRGB photographs** (~60% of a working POC's catalogue) — a naive RGB conversion silently discards the embedded color profile and corrupts both the displayed color and the embedding. Color management (ICC profile → sRGB, relative colorimetric intent) is mandatory in `shared/vision`, before any other step. See `ARCHITECTURE-SPINE.md` AD-15.

## Product rules

**Always return three candidates, never one.** Size and finish are not recoverable from a photo — `MONO COLOUR GLOSSY` and `MONO COLOUR MATT` are visually identical. A single answer will be confidently wrong. Do not add a "confidence threshold that shows only one result" feature.

**Always show the reference image with each candidate.** Staff cannot verify a code they don't recognise; they can verify a picture instantly. The image is what makes the result usable.

**Always show size and category alongside the file name.** Where the file name is only a short code (`1Jk`), the folder-derived size and category is what makes it readable — but the file name is still the tile's identity, not a label on a shared product.

## Security

Non-negotiable requirements — see `AGENTS.md` Policy for the full list (password hashing, server-side authz, session handling, upload validation, audit log, secrets). Do not relax any of them for convenience during development. If a task seems to require breaking one, stop and raise it rather than working around it.

## Testing

- The accuracy eval harness (`make eval`) runs against a held-out set of **real staff phone photos**, not studio assets. Studio-to-studio accuracy is meaningless and will flatter any change.
- Report both top-1 and top-3 accuracy. Top-3 is the metric that reflects real usefulness.
- **Score against the exact tile — the file.** A candidate from the right category folder but the wrong file is a miss. There is no leave-one-out option: a tile has one reference image, so removing it deletes the only correct answer rather than forcing generalisation. That makes `make eval` a robustness upper bound, and `make eval-real` the only number that decides anything.
- Any change to `shared/vision/` requires an eval run. Preprocessing changes invalidate the existing index — a re-index is required, and this must be stated in the PR.
- Security-relevant code paths (auth, authz, upload handling) need tests for the failure case, not just the happy path.

## Conventions

See `AGENTS.md` — Conventions that differ from defaults.

## Scope boundaries

See `AGENTS.md` — Policy. v1 excludes offline scanning, price/stock/spec data, customer/dealer access, app-sent email, and roles beyond `staff`/`admin`. Don't build a `size + category → code` mapping — the file name is the answer, and it is the tile's identity.
