"""Drive → index batch ingestion.

Walks the reference catalogue tree (`<SIZE>/<CATEGORY>/<file>`, exactly three
levels), validates rather than assumes — five naming conventions coexist, files
are `.jpg` and `.tif`, most reference images are CMYK press files — and writes
Tiles, ReferenceImages and embeddings to the index.

Every file in a category folder is a different Tile (AD-18). Nothing here ever
groups or deduplicates by `Size + Category`.

This is the one pre-launch exception to "all mutation flows through apps/api"
(architecture spine, Design Paradigm). It calls `shared_vision` — the same
functions `apps/api` calls at scan time, never a copy (AD-1).

SKELETON: not implemented. Ingestion arrives with Epic 2.
"""
