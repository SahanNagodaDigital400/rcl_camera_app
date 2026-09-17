# infra

Infrastructure-as-code, database migrations and deployment configuration.

Nothing is provisioned yet. This directory exists so the conventions below are
recorded before the first migration is written, not after.

## Migrations — `migrations/`

- **Forward-only and reversible.** Every migration has a `down` that actually
  restores the previous shape. An applied migration is never edited; a mistake
  is corrected by a new migration (AGENTS.md Conventions).
- **One concern per migration**, named with a UTC timestamp prefix and a short
  verb phrase (`20260917T1030_create_tile.sql`).
- The audit log table is **append-only**: no migration may add an `UPDATE` or
  `DELETE` path to it, and neither may application code (AGENTS.md Policy).
- pgvector's floor is **≥ 0.8.2** — load-bearing, not cosmetic: CVE-2026-3172
  (buffer overflow in parallel HNSW index builds) affects 0.6.0–0.8.1 and AD-5
  mandates HNSW.

Migration *content* is Story 1.2 and later. This story creates the directory and
its rules only.

## Open infrastructure decisions (deferred by the architecture spine)

- **Object storage provider** — S3-compatible API is fixed; the provider is not.
- **PostgreSQL 18.x + pgvector compatibility** — verified pgvector testing as of
  the spine's writing covers PostgreSQL 16 and 17. Confirm 18 at build time
  before pinning the deployment.
- **Deployment target and topology** — not chosen.
- **CI pipeline** — not set up; `make lint` and `make test` are the contract a
  pipeline will eventually run.
- **Secrets management** — environment or a secret store; never committed, never
  hardcoded, not even in test fixtures (AGENTS.md Policy).
