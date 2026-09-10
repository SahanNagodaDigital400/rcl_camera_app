# shared/vision

Crop (AD-11) + colour management (AD-15) + preprocessing + embedding
(AD-1, AD-13), including the shared upload-intake path (content-sniff,
re-encode, EXIF-strip -- AD-7).

Called identically by `apps/api` (scan pipeline) and `scripts/ingest`
(index pipeline). **The single most important invariant in this
codebase:** index-time and query-time preprocessing and embedding must
be byte-for-byte identical -- see `CLAUDE.md` and `AGENTS.md` Known
pitfalls. Neither caller may fork, wrap-and-diverge, or reimplement any
part of this module.

This package is intentionally empty as of Story 1.1 (project scaffold).
The real implementation is ported from `poc/tilematch/vision.py`
unchanged, in a later story -- that file was written there specifically
to be lifted into this module, not as a reference to reimplement from.

A change to this module requires a `make eval` run and invalidates the
existing index (AD-1, AD-14).
