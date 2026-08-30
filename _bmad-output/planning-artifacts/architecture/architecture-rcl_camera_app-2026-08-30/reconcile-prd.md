# Reconcile: PRD vs. ARCHITECTURE-SPINE

**PRD:** `_bmad-output/planning-artifacts/prds/prd-rcl_camera_app-2026-08-25/prd.md`
**Spine:** `_bmad-output/planning-artifacts/architecture/architecture-rcl_camera_app-2026-08-30/ARCHITECTURE-SPINE.md`

## Method

Walked FR-1 through FR-23 and the §5 NFRs / §6 Constraints against AD-1..AD-7, the Consistency Conventions, the Structural Seed, and the Capability → Architecture Map. Flagged only items with a real architectural consequence — something two independently-built units could implement incompatibly because the spine doesn't fix it. Also checked the Capability → Architecture Map's FR-range groupings against the PRD's §4 structure.

## Capability → Architecture Map FR-ranges: accurate

§4.1→FR-1–5, §4.2→FR-6–9, §4.3→FR-10–13, §4.4→FR-14–19, §4.5→FR-20–23 all match the PRD's actual `####` FR headings under each `###` section. No mis-grouping found.

## Gaps found

### Gap 1 — AD-7's shared upload-intake path doesn't reach `scripts/ingest`, but §5 Security and FR-17 require it to

§5 Security NFR: "Every image upload — a Scan (FR-6) or a catalogue Reference Image (FR-14, FR-15, FR-17) — is validated by content inspection, never by file extension, and re-encoded before storage." §6 Privacy: "Every uploaded or scanned image is stripped of EXIF metadata... before storage." Both are explicit and unconditional — FR-17 (bulk upload) is named directly in the security rule.

AD-7's rule text: "One shared upload-handling function (content-type sniff → re-encode → EXIF-strip) is used by both the Scan submission endpoint and every catalogue-image endpoint." AD-7's **Binds** line lists only `apps/api (Scan submission, catalogue image endpoints)` — `scripts/ingest` is not mentioned. The Structural Seed confirms `scripts/ingest` is a separate batch adapter that "Calls shared/vision, shared/schema" — not `apps/api` — and the top-level mermaid diagram draws `ingest --> pg` and `ingest --> obj` as direct edges, bypassing `apps/api` entirely.

This directly contradicts the Consistency Conventions table's own claim that "All Postgres/object-storage mutation flows through apps/api (AD-6)" — the diagram shows ingest writing to Postgres and object storage directly. So it's genuinely unresolved whether FR-17 bulk-loaded images get AD-7's content-inspection/re-encode/EXIF-strip treatment at all. A builder implementing `scripts/ingest` per the diagram (direct-to-storage) would ship a bulk-load path that skips the exact validation the PRD names FR-17 under. This is the sharpest gap — a security-relevant NFR with a named FR is architecturally unrouted.

**Fix direction:** either (a) add a rule that `scripts/ingest` also calls the same shared upload-intake function from `shared/vision` or a promoted `shared/` module before any object-storage write, or (b) require `scripts/ingest` to submit through `apps/api` catalogue endpoints rather than writing to `pg`/`obj` directly (which would also resolve the Consistency Conventions contradiction). Either is fine; the spine currently commits to neither.

### Gap 2 — Capability → Architecture Map omits AD-3 for FR-10–13, and AD-3's rule never states role/active must be read live

FR-12: "A role change takes effect on the user's live session, not only at their next authentication — consistent with FR-13's immediate-revocation precedent for deactivation." FR-13: "A session token valid before deactivation is rejected on the next request after deactivation, without waiting for expiry."

Both are explicit "no caching of role/active-status at session-creation time" requirements. This is exactly the kind of invariant AD-3 exists to fix ("validated through one shared session-lookup function... never a bespoke per-route check") — but AD-3's rule text never says the lookup must re-derive `role` and `active` from the live `users` row on every request rather than snapshotting them into the session row at login. The Capability → Architecture Map row for §4.3 Admin User Management (FR-10–13) lists only `AD-6` as governing it, not `AD-3` — so a builder reading the map has no signal that FR-12/FR-13's live-effect requirement is a session-validation concern at all, and could reasonably denormalize role/active into the session table for query convenience, silently breaking both FRs.

**Fix direction:** add `AD-3` to the FR-10–13 map row, and add a sentence to AD-3's rule requiring the session-lookup function to join live `role`/`active` from the user row rather than caching them at session creation.

### Gap 3 — No AD assigns where FR-4 / FR-22 / FR-23 counter/rate-limit state lives

FR-4 (login lockout: "failed attempt 6+ introduces a measurable delay... 10th cumulative failed attempt locks the account"), FR-23 (scan rate limiting per user per window), and FR-22 (anomaly baseline over login times/locations/scan volume) all require some form of counter or rolling-window state, independent of the session table AD-3 covers. No AD addresses this. AD-3's "no second stateful infrastructure dependency... at a scale that doesn't need one" is scoped explicitly to sessions — it's not clear whether that reasoning is meant to extend to rate-limit counters (i.e., a Postgres table + row-level locking) or whether an in-process/Redis counter is expected. This matters architecturally because `apps/api` presumably runs as multiple instances behind a load balancer (implied by needing a shared, not per-instance, session/rate-limit store) — an in-memory counter would silently under-enforce FR-4/23 across instances, and nothing in the spine rules this out. The Deferred section only defers the *numeric thresholds* (OQ-13), not the storage mechanism, which is a separate, unaddressed architectural question.

**Fix direction:** an AD (or an extension of AD-3) stating rate-limit/anomaly counters are rows in Postgres, validated through one shared function, mirroring AD-3's session pattern — or an explicit decision to use a different store, with the "why not a second stateful dependency" tension from AD-3 addressed.

### Gap 4 — AD-5 covers insert/searchability only; FR-15/FR-16's removal guarantee has no assigned enforcement mechanism

FR-15: "A removed Reference Image is no longer returned as a Candidate for any Scan submitted after the edit, even if it was returned before." FR-16: "A Scan submitted after removal never returns the removed Product as a Candidate, regardless of visual similarity." AD-5 is about the opposite direction — it guarantees newly-inserted embeddings are immediately searchable (HNSW, no manual reindex) — and says nothing about how removal/edit is enforced: whether a removed Reference Image's embedding is hard-deleted from the pgvector column, or soft-deleted behind an `active`/`removed_at` flag that every search query must filter on. If it's the latter (more likely, given FR-15 also supports "replace" and audit/history needs), the spine never states that the filter is applied through one shared query path — leaving open the same class of risk AD-1 exists to prevent for embeddings: a search path added later (an eval script under `make eval`, a future admin "preview match" tool) that queries pgvector directly without the removal filter would silently resurface removed/edited images as Candidates, contradicting FR-15/16's explicit "never" language.

**Fix direction:** extend AD-5 (or add a new AD) stating catalogue-search queries against the embedding table always go through one shared query function that filters on live/active status, mirroring AD-1's "never forked, never reimplemented" pattern for the embedding pipeline itself.

## Not flagged (considered, judged PRD-level detail with no architectural consequence)

- FR-3's cookie-not-accessible-to-JS requirement — already fixed as a stack choice in `CLAUDE.md` ("HTTP-only session cookies"); restating cookie flags in the spine would be redundant, not a gap.
- FR-9 vs. the Deferred section's "shared/vision for quality" line — plausible either as a same-request server-side check (image uploads, then a blur/framing verdict returns instead of match candidates) or a client-side pre-upload heuristic; the PRD's FR-9 consequence text ("triggers a retake prompt rather than proceeding to matching") is compatible with a single round-trip, so this doesn't clearly force an inconsistent build the way Gaps 1–4 do.
- Exact numeric thresholds (OQ-13), retention duration (OQ-7), SLA/WCAG targets — explicitly deferred/open in the PRD itself, not architectural omissions.
