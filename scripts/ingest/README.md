# scripts/ingest

The offline batch adapter: Drive -> index catalogue ingestion. Calls
`shared/vision` and `shared/schema` -- the same domain core `apps/api`
calls -- so index-time preprocessing/embedding stays byte-for-byte
identical to the query-time path (AD-1).

**Scope: pre-launch, one-time Phase 0 dataset migration only**
(ARCHITECTURE-SPINE.md Design Paradigm). It runs before there's a live
staff/admin population or an audit trail to protect, under its own
operator-scoped database credentials -- separate from `apps/api`'s
runtime role. It is never invoked from `apps/api` or triggered by any
in-app action. Any post-launch bulk load goes through FR-17's
`apps/api`-mediated endpoint instead, which is within AD-4's live
audit-log coverage; this script is not that path.

Uses the shared upload-intake function (content-sniff, re-encode,
EXIF-strip -- AD-7) for every file it loads, and flags a zero-byte or
unreadable image per-row rather than silently producing a garbage
embedding from a corrupt file.

This package is intentionally empty as of Story 1.1 (project scaffold).
Ingestion logic (Drive traversal, the five file-naming conventions,
per-row success/failure reporting) is out of scope for this story --
see `CLAUDE.md` Source data quirks.
