# Epic 3 Context: Tile Scanning & Identification

<!-- Generated from planning artifacts. Regenerate with compile-epic-context if planning docs change. -->

## Goal

Staff can photograph an unidentified tile, crop it to the tile face, and get up to three visually-verifiable candidate matches in seconds — with the scanning capability itself defended against abuse. This replaces reliance on a few long-serving staff members' memory with a fast, trustworthy visual lookup, while protecting the catalogue from scraping via a compromised or misused account.

## Stories

- Story 3.1: Capture or Upload a Scan
- Story 3.2: Crop Before Submit
- Story 3.3: Capture Quality Guidance
- Story 3.4: Ranked Candidate Results with Images
- Story 3.5: Scan History
- Story 3.6: Scan Rate Limiting
- Story 3.7: Anomaly Flagging

## Requirements & Constraints

- Live camera capture (with on-screen framing guide) and file upload must produce equivalent submissions; both proceed to the same mandatory crop step. The submitted Scan is always the cropped region, never the original frame.
- Quality guidance (blur/poor framing) runs only on the cropped region, after crop confirm, before matching. Its threshold is a named, runtime-configurable value with a documented provisional default, never a code literal.
- Results always show up to three Candidates (reference image, code, size, category) — never a single confidence-gated answer. No similarity value (percentage, bar, star, derived wording) may ever appear on screen; it stays in the API response/server log only.
- Each Candidate is one distinct Tile. Never deduplicate, collapse, or diversify Candidates by Category — two files in the same folder are two different answers, each keeping its own slot.
- Crop-confirmation-to-result latency budget: under 3 seconds end to end.
- Scan history shows only the signed-in user's own scans, rendered exactly as they appeared at scan time, unaffected by later catalogue edits/deletions.
- Scan rate limiting and anomaly flagging are independent mechanisms — a burst can trip one without the other. Both need named, configurable thresholds with provisional defaults; tests must be able to drive them low and observe the effect.
- Out of scope: identifying already-installed tiles; a maintained size+category→code mapping; confidence-gated single answers.
- Accuracy scoring: correctness means the exact Tile returned — right-category/wrong-file is a miss; no leave-one-out eval exists. Early synthetic-query POC numbers are a loose upper bound, not a target — real staff phone photos decide the pilot targets.

## Technical Decisions

- Index/query symmetry: the scan pipeline must call the exact same `shared/vision` preprocessing/embedding function the catalogue-ingest pipeline uses — never forked or reimplemented. Client-side downscale (~1024px) is a bandwidth optimization only, not part of this fixed contract.
- Crop executes exactly once, server-side, immediately before the rest of preprocessing. The client sends the full downscaled image plus a normalized 0–1 crop rectangle (relative to width/height) — never a pre-cropped image or absolute coordinates; `Scan` stores no crop-rectangle field. Crop always precedes the quality check, which evaluates only the cropped region.
- Matching searches multiple embeddings per Reference Image (up to 16 views: rotations + augmented crops) and takes the max similarity per Tile — never an average or pre-pooled vector. A Scan embeds exactly one view (the full cropped frame).
- The active index generation carries a pipeline-version stamp; a mismatch against the running pipeline is a hard error at search time, never a silent degraded result. Color management (ICC → sRGB, relative colorimetric intent) runs before any other preprocessing step, for both catalogue and scan images.
- Embedding inference is serialized server-wide (one forward pass at a time); fixed per-request order is session validation → rate-limit check → inference slot, so a throttled/unauthenticated request never occupies it.
- A removed Reference Image/Tile is hard-deleted from the embedding index — never resurfaces as a Candidate. A Scan's stored result is a denormalized snapshot, never an enforced foreign key, so later catalogue deletions never corrupt scan history.
- Rate-limit and anomaly-baseline counters are rows in Postgres, mutated via a single atomic increment-and-check — never in-process memory or a stale read-then-write.
- All image bytes are proxied through the API — no presigned/direct-to-storage URLs; uploads pass through one shared content-sniff → re-encode → EXIF-strip path.
- A staff-declared narrowing attribute (e.g. Size), if ever adopted, is a hard pre-filter before ranking, never a re-rank, with an "All sizes" default — not adopted in this epic's current scope.

## UX & Interaction Patterns

- Flow: Scan (default landing) → Crop (full-screen sheet, pre-filled best-guess selection, drag corners/edges to resize, drag body to move, no pinch-zoom) → Results (up to 3 candidate cards) → Scan History. Sheet depth never exceeds one level.
- Framing guide overlay: accent-outline rectangle over the live viewfinder, transparent fill, must not block the shutter control.
- Crop selector: accent border, white handles sized to the 44×44px touch floor, dark scrim over the deselected area, free-form (no fixed aspect ratio).
- Retake prompt: inline surface-colored banner directly above the primary action — never a modal.
- Candidate card: reference image, monospace Code, "Size · Category" line; top-ranked card gets a 2px accent border as the *only* rank signal — no numeric/visual confidence indicator anywhere. Tapping a card opens its reference image full-screen (the verification moment).
- Microcopy (verbatim where quoted): "Best match" (never a percentage); "Fill the frame with the tile face."; "No confident match — retake, or ask a colleague."; "This photo's a little blurry — try again." No exclamation marks or gamified language.
- Required states: camera-permission-not-granted (upload fallback always visible), processing (lightweight spinner, no skeleton), no-confident-match (show existing Candidates + retake prompt, never empty), matching failure distinct from no-match (plain message, "Try again," crop/image preserved), scan rate-limited (plain message, no countdown), session-expired mid-flow (redirect to Login; dropping in-progress scan state is fine), empty scan history ("No scans yet.").
- Accessibility floor: ≥44×44px touch targets everywhere on mobile including candidate cards and crop handles; visible focus + keyboard path. Mobile-first single column, full-bleed camera/crop views, bottom tab nav (Scan/History).

## Cross-Story Dependencies

- Story 3.2 depends on 3.1's captured/uploaded image.
- Story 3.3 depends on 3.2's confirmed crop and must complete (pass) before 3.4's matching proceeds.
- Story 3.4 depends on 3.1–3.3 succeeding and on Epic 2's catalogue/embedding index being current, with no separate re-index step required.
- Story 3.5 depends on 3.4's stored candidates snapshot.
- Stories 3.6 and 3.7 gate submissions ahead of 3.4's matching, independently of each other and of quality guidance; a throttled/flagged request must be rejected before occupying the serialized inference slot.
- The epic as a whole depends on Epic 1's session/auth (a Scan is per authenticated user) and Epic 2's catalogue/index being populated and auto-reindexed.
