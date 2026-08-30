# Input Reconciliation: PRD vs. AGENTS.md / CLAUDE.md

**Input checked:** `AGENTS.md` + `CLAUDE.md` (repo agent-instruction files)
**Against:** `_bmad-output/planning-artifacts/prds/prd-rcl_camera_app-2026-08-25/prd.md`
**Purpose:** Verify every product-relevant rule/constraint in AGENTS.md/CLAUDE.md that should surface as an FR, NFR, or glossary term actually does — accurately and completely. Implementation-only items (stack, repo layout, make commands) are deliberately out of scope, per the PRD's own tech-agnostic design.

## Method

Read AGENTS.md (Policy, Where things are, Conventions, Known pitfalls) and CLAUDE.md (Core architecture, Stack, Domain vocabulary, Source data quirks, Product rules, Security, Testing, Scope boundaries) line by line, and traced each product-relevant statement to its expected landing spot in the PRD (§3 Glossary, an FR/NFR, §5 Cross-Cutting NFRs, §7 Risks, §9 Non-Goals, §11 Success Metrics). Below are the misses. Everything not listed was checked and found to be accurately and completely reflected — notably the three CLAUDE.md "Product rules" (always 3 candidates, always show reference image, always show size/design incl. the folder-derived fallback for bare face-number filenames) are all captured precisely in FR-7, and the full v1 scope-exclusion list (roles, customer/dealer access, offline, price/stock/spec, app-sent email) is captured precisely in §2.2/§9.

## Gaps found

### 1. Scanning is not rate-limited — only login is (HIGH)

AGENTS.md Policy: *"Rate-limit login (progressive delay after 5 failures, lockout at 10) **and scanning** — catalogue exfiltration via a compromised account is the primary commercial threat."*

The PRD's FR-4 (Login rate limiting) implements only the login half, with concrete, testable consequences. There is no equivalent FR that throttles *scan* volume per account/session. The only scanning-side controls the PRD offers are FR-22 (Anomaly flagging — "flags... for admin review") and SM-C1 (a counter-metric that watches scan volume) — both are **detective** (notice after the fact), not **preventive** (block/slow it in real time) like AGENTS.md's "rate-limit... scanning" calls for. Given AGENTS.md names this the *primary commercial threat*, the absence of any preventive FR is a real gap, not a stylistic one — a compromised staff account could still scrape the full catalogue at will before an admin ever reviews the anomaly flag.

**Suggested fix:** Add a consequence/FR under §4.2 or §4.5, e.g. "Scan requests from a single account are rate-limited; sustained high-volume scanning is throttled, not just flagged."

### 2. File-upload content validation and re-encoding are missing (HIGH)

AGENTS.md Policy: *"Never accept file uploads validated by extension — inspect content, strip EXIF, re-encode before storage."*

The PRD's §6 Privacy captures only the EXIF-stripping third of this rule: *"Every uploaded or scanned image is stripped of EXIF metadata (GPS, device identifiers) before storage."* There is no FR/NFR anywhere requiring that uploaded files be validated by actual content (not extension) or re-encoded before storage — despite file upload being central to three separate features: FR-6 (scan capture/upload), and FR-14/FR-15/FR-17 (admin catalogue image add/edit/bulk-upload). This is a security-relevant upload-handling control (defense against a malicious file disguised as an image) that the PRD silently drops two-thirds of.

**Suggested fix:** Extend the §6 Privacy bullet (or add to §5 Security) to state the product-facing consequence: uploaded images are validated by content, not file extension, and re-encoded before storage — mirroring how the PRD already states the EXIF consequence.

### 3. Session-token storage invariant has no FR/NFR trace (MEDIUM-HIGH)

AGENTS.md Policy: *"Never store session tokens outside HTTP-only, Secure, SameSite=Strict cookies — never localStorage/sessionStorage."*

This is a "Never" security invariant sitting alongside others that all made it into the PRD with explicit consequences (forced password change → FR-2, deactivation → FR-13, audit immutability → FR-20). This one has none. The closest candidate, §5 Security NFR (*"no credential or secret is ever stored or transmitted in recoverable form"*), reads as being about password/secret storage at rest, not about where the client keeps the live session token — a distinct control against session-token theft via XSS. Nothing in FR-3 (Session persistence and expiry) or elsewhere references this.

**Suggested fix:** Either fold an explicit consequence into FR-3 ("the session token is never accessible to page script or client-side storage") or broaden the §5 Security NFR wording to unambiguously cover session-token handling, not just credentials.

### 4. Top-1 accuracy is not a tracked Success Metric (MEDIUM)

CLAUDE.md Testing: *"Report both top-1 and top-3 accuracy. Top-3 is the metric that reflects real usefulness."* — an explicit instruction that both numbers matter and both should be reported.

The PRD's §11 Success Metrics defines only **SM-1: Top-3 accuracy**. Top-1 accuracy appears exactly once, in passing, inside Open Question #1: *"Top-1/top-3 accuracy targets for SM-1 — set after the Phase 2 pilot."* — but SM-1 itself is defined singularly as a top-3 metric, so this open question references a number (top-1) that isn't actually one of the defined Success Metrics. This is precisely the kind of testing/accuracy-measurement expectation that CLAUDE.md states plainly and that never made it into §11 as its own metric. Worth noting CLAUDE.md frames top-3 as "the metric that reflects real usefulness" — not the *only* one to report — so the PRD isn't wrong to prioritize top-3, but it understates the dual-metric reporting requirement.

**Suggested fix:** Add a distinct SM (or a sub-bullet under SM-1) for top-1 accuracy, even if only reported and not target-gated for v1, to match CLAUDE.md's explicit "report both" instruction.

### 5. "Candidate" is defined inconsistently against CLAUDE.md's Product/Face domain model (MEDIUM)

CLAUDE.md's Domain vocabulary explicitly separates **Product** (a Size+Design pair — the unit of identity) from **Face** (one manufactured surface variation within a Product; not all Faces are photographed; Face numbers are non-contiguous) and **Code** (the cleaned *file name*, i.e., a per-photographed-item identifier, not a per-Product one).

The PRD's own §3 Glossary preserves this distinction correctly for Product/Face/Reference Image, but then defines:

- **Candidate** — "One of the (up to three) **Reference Images** returned as a possible match to a Scan..." (Candidate = image-level)

while FR-7 operationalizes it as:

- "The system returns up to three **candidate Products** for a submitted Scan... each displaying its Reference Image, Code..." (Candidate = Product-level)

Since matching happens at image (effectively Face) granularity but Product is the stated unit of identity, this leaves a real, unresolved question the PRD should settle: if the top-3 nearest-neighbor matches happen to be two images of the *same* Product (two different Faces) and one of a different Product, do the "three candidates" dedupe to distinct Products, or can the same Product legitimately appear twice under different Codes/images? The Glossary and FR-7 currently answer this two different ways.

**Suggested fix:** Pick one definition of Candidate and make FR-7 explicit about dedup behavior (e.g., "up to three candidates, deduplicated by Product" or "up to three candidate images, which may represent fewer than three distinct Products").

### 6. Possible off-by-one in the login lockout threshold (LOW-MEDIUM, lower confidence)

AGENTS.md Policy: *"Rate-limit login (progressive delay after 5 failures, **lockout at 10**)..."*

FR-4's consequences: *"Failed attempt 6+ introduces a measurable delay... Failed attempt 11 locks the account."*

The delay threshold is translated consistently ("after 5 failures" → delay starts at attempt 6). But AGENTS.md phrases the lockout threshold differently — "lockout **at** 10", not "after 10" — which most naturally reads as: the 10th failed attempt itself triggers the lockout. The PRD applies the "after N" pattern to both numbers, producing "attempt 11 locks the account" — one attempt more permissive than what AGENTS.md specifies. This is a small but concretely testable discrepancy (10 vs. 11) worth confirming with whoever owns the exact policy number before it becomes a story acceptance criterion.

## What was checked and found accurate (no gap)

- FR-7's "three candidates, each with image + code + folder-derived size/design" — matches all three CLAUDE.md Product rules precisely, including the bare-face-number fallback rationale.
- FR-2 (72h temp credential expiry), FR-4 (progressive delay starting point), FR-13 (immediate session revocation on deactivation), FR-20 (append-only audit log with who/what/when/source IP) — all match AGENTS.md Policy items essentially verbatim.
- §9 Non-Goals / §2.2 Non-Users — fully covers AGENTS.md's "never add roles beyond staff/admin, customer/dealer access, offline scanning, price/stock/spec data, app-sent email."
- §9 "not a maintained size+design→code mapping table" — matches CLAUDE.md/AGENTS.md's pitfall note verbatim.
- §7 Risk table's "visually identical products" and "studio vs. phone-photo domain gap" risks — substantively match CLAUDE.md's Product rules rationale and Source data quirks section (the PRD's chosen mitigation — supplementing the index with phone-captured references — is a business/rollout decision layered on top of, not a contradiction of, CLAUDE.md's implementation-level suggestion of index-time augmentation; both are legitimately left to engineering to combine).
- Independent penetration test gating general rollout (not the pilot) — correctly scoped to Phase 3 in §8.
