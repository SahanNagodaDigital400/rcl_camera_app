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

## Commands (planned — nothing below exists yet; no `Makefile` in the repo yet)

```bash
make dev            # api + web with hot reload
make test           # full suite
make lint           # ruff + eslint + tsc
make migrate        # apply migrations
make ingest         # run catalogue ingestion
make eval           # accuracy harness against held-out scans
```

Once these exist: run `make lint` and `make test` before considering any change complete.

## Domain vocabulary

Get these right — they are not interchangeable.

- **Design** — a pattern name, e.g. `CREMA MARMOL`, `ASTORIA`. A folder in the source Drive.
- **Size** — e.g. `45X90`, `60X60`. The parent folder.
- **Product** — a `size + design` pair. The unit of identity. `45X90 / CREMA MARMOL`.
- **Face** — one manufactured surface variation within a product. Shade-varying ranges have many; only some are photographed. Face numbers are non-contiguous (0001, 0002, 0008).
- **Code** — the file name, cleaned. `RP.CMA.0001DJ.SM.0T`.

## Source data quirks

The reference set comes from a Google Drive tree with real inconsistencies. The ingestion pipeline must **validate, not assume**.

- Top level mixes size folders (`40X40`, `45X90`) with category folders (`Cement`, `Earthen`, `Fashion`, `Mono Colour`, `Randomness`, `Speckled`). Depth is not uniform.
- Two naming conventions coexist:
  - `Copy of RP.CMA.0001DJ.SM.0T.jpg` — structured code
  - `Copy of 1Jk.jpg` — bare face number, no code
- Strip the `Copy of ` prefix and the extension before storing or displaying.
- Reference images are 2–6.5 MB studio assets. Query images are phone photos. This domain gap is the main accuracy risk — apply aggressive augmentation at index time (lighting, white balance, blur, perspective).

## Product rules

**Always return three candidates, never one.** Size and finish are not recoverable from a photo — `MONO COLOUR GLOSSY` and `MONO COLOUR MATT` are visually identical. A single answer will be confidently wrong. Do not add a "confidence threshold that shows only one result" feature.

**Always show the reference image with each candidate.** Staff cannot verify a code they don't recognise; they can verify a picture instantly. The image is what makes the result usable.

**Always show size and design alongside the file name.** Where the file name is only a face number (`1Jk`), the folder-derived size and design is the only meaningful identifier.

## Security

Non-negotiable requirements — see `AGENTS.md` Policy for the full list (password hashing, server-side authz, session handling, upload validation, audit log, secrets). Do not relax any of them for convenience during development. If a task seems to require breaking one, stop and raise it rather than working around it.

## Testing

- The accuracy eval harness (`make eval`) runs against a held-out set of **real staff phone photos**, not studio assets. Studio-to-studio accuracy is meaningless and will flatter any change.
- Report both top-1 and top-3 accuracy. Top-3 is the metric that reflects real usefulness.
- Any change to `shared/vision/` requires an eval run. Preprocessing changes invalidate the existing index — a re-index is required, and this must be stated in the PR.
- Security-relevant code paths (auth, authz, upload handling) need tests for the failure case, not just the happy path.

## Conventions

See `AGENTS.md` — Conventions that differ from defaults.

## Scope boundaries

See `AGENTS.md` — Policy. v1 excludes offline scanning, price/stock/spec data, customer/dealer access, app-sent email, and roles beyond `staff`/`admin`. Don't build a `size + design → product code` mapping — the file name is the answer.
