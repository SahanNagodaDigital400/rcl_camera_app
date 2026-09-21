# Epic 2 Context: Catalogue Management

<!-- Generated from planning artifacts. Regenerate with compile-epic-context if planning docs change. -->

## Goal

Give Administrators direct, developer-free ownership of the tile Catalogue: add a Tile with its reference image, edit its Code and images, remove it outright, bulk-load a whole range from an image set plus a spreadsheet of codes, and find any entry by partial Code. Every one of those writes must land in the searchable embedding index immediately — an Administrator adds a tile and a Scan submitted in the same session returns it as a Candidate, with no manual re-index step, no ticket, and no data re-import. This epic is also where the vision pipeline first goes into production: the shared image-intake, colour-management, embedding and derivative-generation path that Epic 3's scan side will call identically is built and exercised here on the write side.

## Stories

- Story 2.1: Add Product
- Story 2.2: Edit Product
- Story 2.3: Remove Product
- Story 2.4: Bulk Upload
- Story 2.5: Catalogue Search

(Story keys keep the legacy "Product" wording; read every occurrence as **Tile** — see Technical Decisions.)

## Requirements & Constraints

- **Immediate searchability is an acceptance criterion on every write story**, not a story of its own. Add, edit, remove and bulk upload all take effect in match results with no separate re-indexing action.
- **Every image byte is intaken the same way**: content-sniffed (never trusted by file extension), re-encoded, EXIF-stripped, and colour-managed before storage — the single add path, the edit path and the bulk path all use it, with no shortcut for bulk.
- **Removal is real removal.** A removed Tile or a removed Reference Image never returns as a Candidate for any Scan submitted afterwards, regardless of visual similarity. No soft-delete flag that a query site could forget to filter.
- **Bulk upload reports per row, not per batch.** N valid pairs become N individually searchable Tiles; failures are reported row by row while the rest of the batch proceeds.
- Real catalogue data contains known defects that the bulk path must classify correctly: zero-byte or unreadable files are per-row **failures** (never silently indexed as garbage embeddings); a row with no recoverable Category or no recoverable trailing number is **not** an error — index it with an explicit unknown marker and flag it for follow-up. Two rows sharing a Size and Category are two distinct Tiles — never merged, deduplicated, or reported as a conflict.
- **Catalogue search matches substrings of the Code**, not exact codes only.
- Every catalogue change is attributable and permanent — writes go through the existing audit path, which has no update or delete route at any level. Every catalogue endpoint re-verifies the Administrator role server-side, independent of what the UI hides.
- Reference images added by in-app capture rather than studio assets may match poorly; an image below the quality threshold should surface its flag on the tile's own detail screen rather than only in a report. The exact threshold value is unset and deferred.
- Image file realities: up to ~96MB and ~19276×9638 px originals, `.tif` alongside `.jpg`, and roughly 60% CMYK press files.

## Technical Decisions

- **`Tile` is the unit of identity, keyed by `Code`** — one catalogue row per file, never `Size + Category`. `Product` and `Face` are retired and must not appear as type or entity names; `Category` is a nullable grouping attribute with an UNKNOWN sentinel when unrecoverable, and `face_number` is a nullable display hint only. `Size` and `Category` resolve through shared create-if-missing, case/whitespace-normalized lookups so the API and ingest paths can't drift into near-duplicate values.
- **`shared/vision` is ported, not reimplemented** — lift it from the POC's vision module, which was written to move across unchanged. It owns colour management, preprocessing, embedding and the shared upload-intake function, and both the live API and the batch ingest script call it identically. Any change to it invalidates the index and requires an eval run plus a stated re-index.
- **Colour management runs first, before any other step**: transform any embedded ICC profile to sRGB at *relative colorimetric* intent (never perceptual, never with black-point compensation — both measured badly wrong on these press profiles); a missing profile is assumed sRGB. Validate with a test asserting hue *and* brightness. Decode to a 2048px long-edge cap before anything else.
- **Each Reference Image produces up to 16 embeddings**, not one — 4 clean rotations plus 12 randomized augmented crops — stored as separate child rows, never pooled at write time. A Tile's score is the max across its images' views.
- **Embeddings are unit-norm `vector(1536)` under a pgvector HNSW index** with the cosine/inner-product ops class: inserts join the searchable graph immediately (this is what makes "no manual re-index" true), and deletion is a hard delete that cascades from Reference Image to its embeddings.
- **Every embedding row carries a pipeline-version stamp** (version marker + preprocessing-config hash). A re-index is a complete new generation cut over atomically via a single active-generation pointer, never incremental per-row patching; a stamp mismatch is a hard error, not a degraded search.
- **A capped display derivative (~1280px long edge, ~300KB) is generated once at write time.** The original asset is never served to the web app and nothing is rendered on demand.
- **No presigned or direct-to-storage URLs, in either direction.** Every image byte is proxied through an authenticated API endpoint; the web app holds no storage or database credential.
- Audit entries and scan snapshots that name a Tile or Reference Image are denormalized, with no enforced foreign key — hard deletes must not corrupt or block them.
- `scripts/ingest` is pre-launch only, for the one-time dataset migration under its own operator credentials. Any post-launch bulk load goes through this epic's API-mediated endpoint so it stays inside the live audit trail.
- Admin catalogue uploads get **no** crop step — that capability exists but is exercised only by the scan path.
- Conventions carried forward: UUIDv4 ids, ISO 8601 UTC timestamps, one error envelope `{ "error": { "code", "message" } }`, forward-only migrations.

## UX & Interaction Patterns

The design and experience spines are binding and win over any mockup. Invoke the `ui-ux-pro-max` skill and run its pre-delivery checklist before calling any UI story here done.

- **Surfaces:** Catalogue (admin nav — search/browse Tiles), Add/Edit Tile (from a row or "+ Add Tile"), Bulk Upload. All are Administrator-only and desktop/tablet-leaning, using the same dense data-table row treatment as the user list — hover, hairline separators, no card wrapper, row click opens detail, destructive actions in a labelled row-end menu.
- **The bulk-upload report is a scrollable per-row list, never a single pass/fail summary**, with three distinct outcomes: navy success, red failure, orange flagged-for-review. Rows stream their status as they complete rather than sitting behind one spinner until the batch ends.
- **Saving shows an inline `Saved.` indicator near its trigger** — muted at rest, navy when saved, never a corner toast and never orange.
- **Destructive removal confirms in a sheet that names the tile and its consequence**, with the confirm styled destructive; no stacked sheets.
- **Empty catalogue search reads "No tiles match — try a different code."** with no suggested alternatives.
- **Never drop an in-progress catalogue edit silently** — a session expiring mid-form warns before navigating away.
- Cross-cutting obligations apply per surface: ≥44×44px touch targets, visible focus and a keyboard path on every interactive element (admin screens get real keyboard use), no colour-only signalling on destructive actions, tokens only with no raw hex, Phosphor outline icons, and plain factual microcopy.

## Cross-Story Dependencies

- **Epic 1 gates this epic entirely** — the scaffold and token layer, the server-side role check, and the audit write path must exist first; this epic extends that audit path with catalogue events.
- **2.1 is the keystone.** It builds `shared/vision`'s production intake, colour management, embedding generation and derivative generation; 2.2 and 2.4 reuse that path verbatim rather than re-deriving it.
- **2.1 → 2.5.** Search needs catalogue rows to find, and both must agree on the Code/Size/Category shape.
- **2.2 and 2.3 share the deletion semantics** — hard delete plus embedding cascade; get it right once.
- **2.4 depends on 2.1's single-add path** and adds only batching, the per-row report, and the known data-defect classifications.
- **Forward to Epic 3:** the scan path calls the same `shared/vision` functions this epic builds and searches the index this epic writes, so any asymmetry introduced here surfaces there as unexplained accuracy loss. Accuracy targets and the `make eval` / `make eval-real` harness belong to Epic 3's pilot; Epic 2 owns the index that feeds them.
