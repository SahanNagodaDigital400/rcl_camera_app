# shared/schema

Shared types and contracts for entity names used verbatim (PascalCase)
across `apps/api`, `scripts/ingest`, and -- eventually -- `apps/web`:
`Product`, `Design`, `Size`, `Face`, `Code`, `ReferenceImage`,
`ReferenceEmbedding`, `Scan`, `Candidate`, `Catalogue`, `Staff`,
`Administrator`, `Session` (ARCHITECTURE-SPINE.md Consistency
Conventions, Structural Seed ERD).

**This package starts as Python, not TypeScript.** The Structural
Seed's diagram draws solid arrows from `apps/api` and `scripts/ingest`
into `shared/schema`, but only a dotted "type contracts only" line
from `apps/web`: Python is the direct-consumer language now, and
`apps/web` picks up contracts later (e.g. via OpenAPI-generated types)
once real endpoints exist. Resolving that generation step is not in
scope for this story.

This package is intentionally empty as of Story 1.1 (project scaffold).
The actual types are defined starting with Story 1.2 onward, alongside
the database schema/migrations they mirror.
