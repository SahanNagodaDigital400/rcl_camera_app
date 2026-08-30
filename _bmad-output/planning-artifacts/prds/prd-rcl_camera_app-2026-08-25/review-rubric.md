# PRD Quality Review — Rocell Tile Identification App

## Overall verdict

This is a disciplined PRD with a real thesis, honest open-item tagging, and a visible reconciliation trail against both the product brief and `AGENTS.md`/`CLAUDE.md` (see `reconcile-brief.md`, `reconcile-claude-md.md`, `.memlog.md` in this same directory) — six genuine gaps from that reconciliation were fixed into the current draft (SM-6, FR-13's min-two-admin rule, FR-23, upload content-validation, the FR-4 lockout off-by-one, the Candidate ambiguity surfaced as OQ-12). What's left is narrower but concrete: three separate FRs (FR-9, FR-14/19, FR-23) assert "the threshold" for blur, image quality, and scan volume as if already defined, without ever setting or flagging one; §10.1's MVP scope statement is stale and silently drops the newly-added FR-23 (scan rate limiting — the PRD's own answer to "the primary commercial threat"); and the Candidate/Product dedup question under FR-7, the single most customer-visible requirement, is correctly surfaced as open (OQ-12) but not cross-referenced from the scope section that declares FR-7 "in scope." None of this is fatal, but a story-writer picking this up cold will trip on all three.

## Decision-readiness — adequate

Open Questions (§12, 12 items) are genuinely open, not rhetorical — OQ-6 (SSO would eliminate most of §4.1), OQ-11 (is business-hours-only availability actually acceptable), and OQ-12 (Candidate dedup semantics) are real unresolved forks, not decorative. `[NOTE FOR PM]` appears at two real tensions (FR-19's quality-threshold risk tied to Risk row 2 in §7; §10.2's native-app revisit trigger), not at safe checkpoints. FR-7 and §9 state a decision plainly and defend it ("never a single 'confidence-gated' answer") rather than hedging.

The one crack: OQ-12 leaves the definition of FR-7's core behavior (do three Candidates dedupe by Product, or can the same Product appear twice under different Faces?) unresolved, yet §10.1 declares "Everything in FR-1 through FR-22" simply "In Scope" with no caveat pointing back to OQ-12 — a reader of §10 alone would not know FR-7 has an open design fork underneath it.

### Findings
- **medium** Candidate-dedup fork not threaded into scope section (§3 Glossary / §12 OQ-12 vs §10.1) — OQ-12 is a load-bearing ambiguity in FR-7's core behavior, but §10.1's "In Scope" statement doesn't flag it, unlike OQ-6/SSO which §10.2 explicitly calls out as needing resolution before Foundation build starts. *Fix:* add the same "resolve before build" framing to OQ-12, cross-referenced from §10.1 or FR-7 itself.

## Substance over theater — strong

No persona theater: three UJs map to two roles (Kasun/staff, Nadeesha + Ruwan/admin), each driving a distinct FR cluster, not padding. No innovation/differentiation section forced in. No NFR boilerplate — §5's Performance and Auditability carry numbers and FR cross-refs, and Availability/Accessibility are honestly tagged `[ASSUMPTION]: no formal target for v1` rather than dressed up as "the system must be highly available/accessible." §1 Vision is specific to Rocell's actual problem (unlabelled tiles, catalogue knowledge concentrated in senior staff) rather than swappable boilerplate. Notably, the PRD deliberately did *not* carry forward the brief's own `[ASSUMPTION]` long-range vision (warehouse/returns/training extensibility) and logged that as a scoping decision in §13 rather than silently dropping it — good discipline, not theater.

No findings.

## Strategic coherence — strong

The thesis (visual confirmation over trusting an opaque code, plus admin self-service catalogue currency) is stated in §1 and actually drives structure: §8's rollout phases stage Foundation → pilot → pentest-gated full rollout in an order that follows from the thesis, not from what's easiest to build first. Success Metrics validate the thesis rather than measuring bare activity — SM-4 (Fallback rate) is explicitly framed as an inverse trust signal, and SM-C1 is a real counter-metric ("a spike here... is a catalogue-exfiltration signal... not evidence of adoption"), which is the kind of self-aware metric design the rubric flags as rare. SM-5 (catalogue currency) validates the admin-side half of the thesis, not just the scanning half. This reads as a coherent capability spec, not a backlog with headings.

No findings.

## Done-ness clarity — thin

Rigor is uneven. The security- and behavior-critical FRs are genuinely well-specified: FR-4 ("The 10th cumulative failed attempt locks the account"), FR-13 ("A session token valid before deactivation is rejected on the next request"), FR-17 ("a per-row success/failure report"), FR-20/23 all have bounded, testable consequences. But three separate FRs invoke an undefined bound with a definite article, as if it already exists:

- FR-9: "A test image below **the blur/framing threshold** triggers a retake prompt" — no numeric or qualitative bound given anywhere.
- FR-19's Notes / UJ-2 edge case (§4.4, §2.3): "flagged as below **the quality threshold**" — same gap.
- FR-23: "A user submitting scans above **a defined threshold**... is throttled" — same gap.

Unlike Availability/Accessibility (§5), which are honestly tagged `[ASSUMPTION]: no formal target for v1`, none of these three is tagged `[ASSUMPTION]` or listed in §12 Open Questions — they read as settled when they aren't. An engineer building FR-9 or FR-23 has no bound to implement or test against, and no signal that one is still needed.

Separately, FR-22 (Anomaly flagging) has no "Consequences (testable)" block at all and rests entirely on undefined terms — "unusual login times," "unexpected locations," "scanning volume consistent with catalogue scraping" — with no baseline, window, or multiplier given, unlike its paired FR-23 which does define one. And several CRUD FRs (FR-10, FR-11, FR-12, FR-15, FR-16, FR-18, FR-21) have no Consequences block at all, in contrast to sibling FRs in the same feature groups (FR-13, FR-14, FR-17, FR-19, FR-20) that do. FR-12 in particular ("can edit a user's name, email, or role") doesn't say whether a live role change takes effect on the user's current session or only at next login — directly relevant given FR-13 establishes immediate-revocation as the product's stated bar for account changes.

### Findings
- **high** Three FRs assert an undefined "the threshold" (FR-9 blur/framing, FR-14/19 image quality, FR-23 scan volume) — none is bounded, tagged `[ASSUMPTION]`, or listed in §12, unlike every other unresolved numeric bound in this PRD. *Fix:* either set a placeholder bound and tag it `[ASSUMPTION]`, or add explicit Open Question entries for each.
- **medium** FR-22 (Anomaly flagging) has no testable Consequences block and no baseline for "unusual"/"unexpected." *Fix:* add at least one bound, e.g. a time-of-day window or a volume multiplier over rolling baseline.
- **medium** FR-10, FR-11, FR-12, FR-15, FR-16, FR-18, FR-21 lack Consequences blocks present in sibling FRs; FR-12 specifically doesn't state whether a role edit takes effect on a live session (relevant given FR-13's immediate-revocation precedent). *Fix:* add one testable consequence per FR, even briefly — for FR-12, state whether role/permission changes apply to the live session or only on next authentication.
- **medium** AGENTS.md's "never store session tokens outside HTTP-only, Secure, SameSite=Strict cookies — never localStorage/sessionStorage" rule has no product-facing consequence anywhere in the PRD; §5 Security's "no credential or secret is ever stored... in recoverable form" covers passwords/secrets, not client-side token storage. Every other Policy "Never" rule got an explicit consequence somewhere (FR-2, FR-13, FR-20, the upload-validation Security bullet) — this is the one that didn't, and it was already flagged in this project's own `reconcile-claude-md.md` (finding #3) but wasn't carried into the fix pass reflected in `.memlog.md`. *Fix:* add to FR-3 or §5 Security: "the session token is never accessible to page script or client-side storage."

## Scope honesty — adequate

Tagging discipline is genuinely good: four inline `[ASSUMPTION]` tags all round-trip cleanly into §13; the one `[NON-GOAL for MVP]` tag sits at a real point of potential silent assumption (single-answer results); `[NOTE FOR PM]` appears at two substantive tensions, not safe checkpoints. §9's nine Non-Goals are specific, not generic filler.

But §10.1 has a stale-scope defect: "Everything in FR-1 through FR-22" — the PRD defines FR-1 through **FR-23** (§4.5 Scan rate limiting). FR-23 was added during the reconciliation pass recorded in `.memlog.md` specifically to close the gap that scanning wasn't rate-limited, which `AGENTS.md` Policy calls "the primary commercial threat." §10.1 was never updated to include it, so the MVP scope statement — read on its own, as §0 says every section should be — silently excludes the one control this project's own history treats as most load-bearing on the security side.

### Findings
- **high** §10.1 MVP Scope ("Everything in FR-1 through FR-22") omits FR-23, added later in the same reconciliation pass that produced the current draft. This silently drops a security-critical preventive control from explicit MVP scope. *Fix:* update §10.1 to "FR-1 through FR-23."

## Downstream usability — strong

FR/UJ/SM IDs are contiguous with no gaps or duplicates (FR-1–23, UJ-1–3, SM-1–6 + SM-C1), and cross-references generally resolve (UJ capability-mapping arrows land on real FRs; SM validation lines cite real FR IDs). Each feature section stands alone with its own Description + FRs, and cross-references use `§N` section numbers rather than "see above." All three UJs carry a named protagonist with inline context (Kasun, Nadeesha, Ruwan). This PRD is positioned as chain-top (§0: "before architecture and story breakdown begin"), so this rigor is doing real work.

Minor mechanical nits — a broken cross-reference, a stale Open Question, glossary case drift, and a structural asymmetry between UJs — are real but don't undercut the overall verdict; see Mechanical notes below.

No findings beyond the Mechanical notes items.

## Shape fit — strong

This is an internal, two-role tool, but the camera-capture UX (framing guide, capture-to-result latency, visual confirmation) is genuinely meaningful, not incidental — so keeping three UJs rather than collapsing to a pure capability spec is the right call, and three is well under the theater threshold. §5 Security appropriately states only the product-facing consequence of each `AGENTS.md` rule and defers the standing rule set rather than duplicating it, matching the PRD's own stated intent in §0. SM mix appropriately blends user-facing (SM-1/2/3/4/6) and operational (SM-5, catalogue currency) metrics rather than forcing a growth-product SM shape onto an internal tool.

No findings.

## Mechanical notes

- **Broken cross-reference:** FR-19's Notes (§4.4) says "see Risk R-2, §7," but the §7 risk table has no ID column — no row is labeled "R-2" anywhere in the document. (Best guess by position: the second row, "Reference images are studio assets; scans are phone photos under showroom lighting.") Either add row IDs to the §7 table or replace "R-2" with a quoted risk description.
- **Stale Open Question:** §12 OQ-1 ("Top-1/top-3 accuracy targets for SM-1") wasn't updated when SM-6 (Top-1 accuracy) was added during reconciliation — it still bundles both metrics under the single ID "SM-1," though SM-1 is now defined singularly as top-3 and SM-6 carries top-1.
- **Glossary/case drift:** §3 defines "Candidate" as a noun (a specific Reference Image result); FR-7 operationalizes it as "candidate Products" (lowercase adjective + different noun). This tracks the still-open OQ-12 ambiguity rather than being a pure typo, but is worth normalizing once OQ-12 resolves.
- **UJ structural asymmetry:** UJ-1 and UJ-2 (§2.3) follow a full template (persona+context / entry state / path / climax / resolution / edge case / capability mapping); UJ-3 is a single flattened sentence with only a capability-mapping arrow. Not wrong, but inconsistent for anyone source-extracting UJs downstream.
- **Assumptions Index roundtrip:** clean. All four inline `[ASSUMPTION]` tags (§2.3 UJ-1/UJ-2 narration, §5 Availability, §5 Accessibility, §1 Vision via §13) are indexed in §13, and no §13 entry lacks an inline tag.
- **ID continuity:** clean. FR-1–23 contiguous and unique; UJ-1–3 contiguous; SM-1–6 plus SM-C1 contiguous. No gaps, no duplicates.
- **Deferred-content accuracy:** verified, not just asserted — §7's "Full 14-item risk register" claim against `brief-rcl_camera_app-2026-08-25/addendum.md` checks out (the addendum's Full Risk Register table has exactly 14 rows).
