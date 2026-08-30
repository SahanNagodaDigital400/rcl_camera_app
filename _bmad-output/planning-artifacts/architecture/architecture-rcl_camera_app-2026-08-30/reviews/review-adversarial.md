---
title: Adversarial Review — Architecture Spine
type: review
target: architecture-rcl_camera_app-2026-08-30/ARCHITECTURE-SPINE.md
sources:
  - '_bmad-output/planning-artifacts/architecture/architecture-rcl_camera_app-2026-08-30/ARCHITECTURE-SPINE.md'
  - '_bmad-output/planning-artifacts/prds/prd-rcl_camera_app-2026-08-25/prd.md'
method: 'Construct two engineers, each building a different feature/epic against the spine, each honoring every cited AD to the letter, who still ship incompatible systems.'
created: '2026-08-30'
---

# Adversarial Review — Architecture Spine

## Verdict

The spine is well-formed at the level it operates (module ownership, cross-cutting mechanism choice) but under-specifies **entity lifecycle and shape** at the seams between features. Five concrete two-engineer collisions are constructed below. All five are letter-compliant with every cited AD; none is caught by the Consistency Conventions table, because that table governs naming and formats, not schema shape, referential integrity, or operation ordering. Three of the five are severe enough to block Foundation-phase parallel work (Findings 1, 2, 4); the other two are latent until Phase 3+ (Findings 3, 5).

---

## Finding 1 — `Candidate`/Scan-history shape vs. AD-5 hard delete

**Units:** Engineer A builds FR-8 (Scan history: "each with the result shown at scan time"). Engineer B builds FR-15/FR-16 (Edit/Remove product, bound by AD-5: "hard delete from the embedding index, not a soft-delete flag").

**Engineer A's implementation:** The spine's own ER diagram models this as `SCAN }o--o{ REFERENCE_IMAGE : "returns up to 3 as Candidates"` — a bare many-to-many relationship, no columns of its own. Engineer A follows the diagram literally: a `scan_candidates` join table storing `(scan_id, reference_image_id, rank, score)`, with the Code/Size/Design/image shown on the history screen fetched live by joining to the current `REFERENCE_IMAGE`/`PRODUCT` rows. This is the natural reading of the diagram and satisfies the naming convention (`Candidate`, `Scan`, `ReferenceImage` used verbatim).

**Engineer B's implementation:** Builds FR-16 exactly as AD-5 mandates — `DELETE FROM reference_image WHERE id = ...`, no soft-delete flag, no filter anywhere to forget. Fully compliant with AD-5's letter, including the invariant's own stated purpose ("no filter to forget").

**The collision:** Once Engineer B hard-deletes a `ReferenceImage`, Engineer A's live-join history view for every past `Scan` that ever returned it as a `Candidate` now shows a broken join — missing image, missing code, missing size/design, or a fetch error — for a scan that may be months old. This directly violates FR-8's tested consequence ("the result shown at scan time") and FR-15/16's own intent, which only promises that removed items stop appearing in **new** results, not that history gets silently rewritten. Neither engineer is out of spec: AD-5 says nothing about what else references `REFERENCE_IMAGE`, and the ER diagram gives Engineer A no signal that `Candidate` needs to be a denormalized snapshot rather than a live relationship.

**Why no AD catches it:** AD-5's "Prevents" clause is scoped to *catalogue query correctness* (a removed product resurfacing as a fresh candidate) — it says nothing about entities that must **outlive** the row it deletes. The Consistency Conventions table's naming row treats `Candidate` as a name to reuse, not a data-shape decision.

**Close with:** A new AD pinning `Candidate` (and any other FR-8-visible record) as an **immutable snapshot** written at scan time — denormalized code, size, design, and an image reference that survives hard deletion of the source `ReferenceImage` (either a copy of the image at scan time, or an explicit "source removed" fallback state) — never a live foreign-key join. State explicitly that AD-5's hard delete must not be blocked by, nor silently corrupt, any FR-8 history record.

---

## Finding 2 — Audit-log referential shape vs. AD-5 hard delete (AD-4 vs. AD-5 in direct tension)

**Units:** Engineer A builds `infra` migrations for the audit table under AD-4 ("permanent," DB role has INSERT/SELECT only, no UPDATE/DELETE grant). Engineer B builds `infra` migrations for `Product`/`ReferenceImage` under AD-5 (hard delete).

**Engineer A's implementation:** To satisfy FR-20's "who, what, when" and to keep the audit view (FR-21) queryable/joinable rather than a bag of opaque UUIDs, Engineer A adds a real foreign key from `audit_log.entity_id` to `reference_image.id` / `product.id` — ordinary, defensible schema practice for an audit trail, and nothing in AD-4 forbids it. AD-4 only constrains grants and the absence of UPDATE/DELETE *on the audit table itself*.

**Engineer B's implementation:** Executes FR-16 (Remove product) as AD-5 requires — a hard `DELETE` against `product`/`reference_image`.

**The collision:** With Engineer A's FK in place, Engineer B's mandatory hard delete now fails a foreign-key constraint the moment any audit entry has ever referenced that product or image (which, per FR-20, is guaranteed — every catalogue change is audited). Rocell cannot remove a discontinued range without either (a) the delete erroring in production, breaking FR-16 outright, or (b) someone "fixing" it with `ON DELETE CASCADE` / `SET NULL` — but CASCADE means the database itself executes a DELETE against `audit_log`, which AD-4's own Rule says the application's DB role isn't even granted, and which directly violates "no update or delete path against the audit log exists ... from application code **or a migration**" in spirit (AD-4's stated purpose is to survive exactly this kind of accidental path). `SET NULL` silently destroys the "what" in a "permanent" audit entry (FR-20/NFR: "audit entries are write-once ... enforced independent of any admin-facing permission").

**Why no AD catches it:** AD-4 and AD-5 both list `infra` as a bind, and both are individually airtight, but neither says how audit references to hard-deletable entities should be modeled. This is a Rule-vs-Rule contradiction that only appears when the two are composed on the same schema.

**Close with:** A new AD stating audit-log entity references are **denormalized value columns, never DB-enforced foreign keys** — store `entity_type`, `entity_id` (as data, no constraint) plus a snapshot of the salient fields at the time of the action, so AD-5's hard delete can never be blocked by, or forced to cascade into, AD-4's immutable log.

---

## Finding 3 — Scan-rate counter race condition undermines AD-8's own stated purpose

**Units:** Engineer A (Auth, AD-3) builds session validation. Engineer B (Audit/rate-limit, FR-23, bound by AD-8) builds the scan-submission throttle.

**Engineer A's implementation:** Per AD-3's letter, a single `SELECT` per request against the sessions table, re-reading role/active status — no locking implied or needed, since it's read-only.

**Engineer B's implementation:** AD-8's Rule says only that counters are "rows in Postgres, read and written through shared counter logic — never in-process memory." Engineer B builds the shared counter function as the obvious, letter-compliant read-then-write: `SELECT count FROM scan_counters WHERE user_id=... AND window=...`, compare to threshold in application code, then `UPDATE ... SET count = count + 1`. This is "shared counter logic," it's in Postgres, it's not in-process memory — fully AD-8-compliant.

**The collision:** FR-23 exists specifically to bound "the volume achievable by a single **compromised or misused account**" — i.e., its threat model is an actor issuing many concurrent requests as fast as possible. Read-then-write with no row lock or atomic increment (`UPDATE ... SET count = count + 1 RETURNING count`, or `SELECT ... FOR UPDATE`) is exactly the classic TOCTOU race: N concurrent scan requests can each read the same pre-increment count, each see "under threshold," and all proceed, letting a scraping burst blow through the limit by a factor proportional to concurrency. The same shape of bug applies to AD-8's login-lockout counter (FR-4) and anomaly baseline (FR-22) — all three share "shared counter logic" per AD-8, so the same race, if built this way once, propagates to all three controls.

**Why no AD catches it:** AD-8's Rule specifies *where* counters live (Postgres, not memory) and that logic is shared, but not *how* the read-modify-write must be made atomic under concurrency — the exact dimension the FR it serves (a concurrency-based attack) depends on.

**Close with:** Tighten AD-8's Rule to mandate a single atomic statement for increment-and-check (`UPDATE ... SET count = count + 1 WHERE ... RETURNING count`, evaluated against the threshold from the returned value, or equivalent row-level locking) — never separate read then write — for all three consumers (FR-4, FR-22, FR-23).

---

## Finding 4 — Bulk-upload presigned-URL path vs. AD-6 letter and AD-7's mandatory intake function

**Units:** Engineer A builds FR-6 (Scan submission). Engineer B builds FR-17 (Bulk upload — "a set of images plus a spreadsheet of codes").

**Engineer A's implementation:** Scan photos POST their bytes to an `apps/api` endpoint, which internally calls AD-7's shared upload-intake function (content-type sniff → re-encode → EXIF-strip) before anything touches object storage or `shared/vision`.

**Engineer B's implementation:** Bulk catalogue loads can be large (hundreds of studio images, 2–6.5MB each per `CLAUDE.md`'s own source-data note). To avoid proxying multi-GB payloads through a single FastAPI process, Engineer B has `apps/api` mint short-lived, scoped presigned PUT URLs and has the admin's browser upload each file directly to object storage, then calls `apps/api` only to register the resulting object keys against `Product`/`ReferenceImage` rows. Engineer B can defend this against AD-6's literal Rule — "`apps/web` holds no database or storage credential" — because a presigned URL is scoped and time-limited, not a stored, reusable credential; nothing in AD-6's text says "no direct network path," only "no credential."

**The collision:** Every byte that goes through Engineer B's path never passes through AD-7's shared intake function — no content-type sniff, no re-encode, no EXIF strip. That is a direct violation of AD-7's Rule ("No code path writes an image to object storage without passing through it first") and of PRD §6 Privacy ("every uploaded or scanned image is stripped of EXIF metadata ... before storage") and §5 Security ("every image upload ... validated by content inspection, never by file extension"). It also means bulk-loaded reference images can diverge from scan-path images in exactly the re-encoding step AD-1 depends on for embedding symmetry — if `shared/vision`'s preprocessing assumes AD-7's re-encode already normalized color profile/format upstream, index-time images built via the presigned path silently differ from what AD-1 assumes, without either engineer's code being individually "wrong."

**Why no AD catches it:** AD-6's Rule is written in terms of *credentials*, not *data paths*; AD-7 names `apps/api` endpoints and `scripts/ingest` as the required callers of the shared function but doesn't foreclose an upload transport (presigned URL) that never invokes any endpoint code at all until after the bytes already sit in object storage.

**Close with:** Tighten AD-6 to state explicitly that no image byte may reach object storage by any transport — presigned URL included — without first passing through AD-7's shared intake function; if presigned URLs are used for large bulk loads, the object must land in a quarantine/staging prefix invisible to `shared/vision` and only get promoted after the intake function has run against it server-side.

---

## Finding 5 — `Product`/`Size`/`Design` normalization split between the catalogue-admin path and the ingest path

**Units:** Engineer A builds FR-14/FR-15/FR-18 (Add/Edit Product, Catalogue search) in `apps/api`. Engineer B builds FR-17/`scripts/ingest` (bulk load from the Drive tree described in `CLAUDE.md` — inconsistent depth, two file-naming conventions, `Copy of` prefixes to strip).

**Engineer A's implementation:** Building an interactive Add-Product form (UJ-2: "enters the product code, captures reference images"), Engineer A naturally normalizes `Size` and `Design` into their own lookup tables (dropdowns need a canonical list; FR-18's "partial code match" is easiest against a normalized code column) — `PRODUCT.size_id`, `PRODUCT.design_id` as foreign keys.

**Engineer B's implementation:** Ingest walks a Drive tree where "top level mixes size folders with category folders" and "depth is not uniform" (`CLAUDE.md`, Source data quirks) — the ingestion Rule (per `CLAUDE.md`) is to *validate, not assume* structure, and folder-derived size/design strings can't be reliably resolved against a pre-seeded lookup table before the batch runs (a folder like `Randomness` isn't a size at all). Engineer B stores `size`/`design` as free-text columns captured directly from folder names, resolved against the lookup table only as a best-effort, nullable link.

**The collision:** Both engineers are honoring the Consistency Conventions table's naming row to the letter — both call the entity `Product`, both use `Size`/`Design` as PascalCase terms — but the convention governs *names*, not *shape*. The two migrations produce structurally incompatible `product` tables (FK-normalized vs. free-text). Whichever lands second either breaks the other's code (FR-18 search, FR-7's "folder-derived Size and Design" display) or forces a reconciliation migration mid-build that neither the spine nor `AGENTS.md` assigns to either engineer. This also collides with FR-17's own consequence — "a per-row success/failure report for any that fail validation" — since "validation" now means two different things depending on which normalization the reconciled schema settled on.

**Why no AD catches it:** No AD assigns ownership of the `Product`/`Size`/`Design` physical schema, and the Consistency Conventions table's only schema-adjacent entry is IDs/timestamps/error-envelope formatting — it never addresses normalization strategy for the one entity both a live admin path and a batch path must write through identically.

**Close with:** A new AD naming a single owner (likely `shared/schema` plus one `infra` migration authored before either feature starts) for the `Product`/`Size`/`Design`/`Face` physical schema, explicitly requiring both the catalogue-admin path and the ingest path to write through the same normalization — including how a folder value that doesn't resolve to a known `Size`/`Design` is handled (reject, or create-on-write) — before either engineer starts building against it.

---

## Recommended AD additions/tightenings (summary)

| # | Gap | Fix |
| --- | --- | --- |
| 1 | `Candidate`/history shape vs. hard delete | New AD: Candidate/scan-history rows are immutable snapshots, never live FKs into `ReferenceImage`/`Product`. |
| 2 | Audit references vs. hard delete | New AD: audit-log entity references are denormalized values, never DB-enforced foreign keys. |
| 3 | Counter race | Tighten AD-8: increment-and-check must be one atomic statement/row-lock, not read-then-write, for FR-4, FR-22, FR-23 alike. |
| 4 | Presigned-URL bypass of AD-7 | Tighten AD-6: no transport, including presigned URLs, may deliver bytes to object storage without first passing AD-7's intake function; require a quarantine prefix for any indirect upload. |
| 5 | Product/Size/Design schema split | New AD: single named owner for the Product/Size/Design/Face physical schema and its normalization rule, bound by both the catalogue-admin path and `scripts/ingest`. |
