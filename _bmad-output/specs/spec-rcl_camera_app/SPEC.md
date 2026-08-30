---
id: SPEC-rcl_camera_app
companions:
  - glossary.md
  - user-journeys.md
  - functional-requirements.md
  - rollout-phasing.md
  - ../../planning-artifacts/architecture/architecture-rcl_camera_app-2026-08-30/ARCHITECTURE-SPINE.md
  - ../../planning-artifacts/briefs/brief-rcl_camera_app-2026-08-25/addendum.md
  - ../../../AGENTS.md
sources:
  - ../../planning-artifacts/prds/prd-rcl_camera_app-2026-08-25/prd.md
  - ../../planning-artifacts/briefs/brief-rcl_camera_app-2026-08-25/brief.md
---

> **Canonical contract.** This SPEC and the files in `companions:` are the complete, preservation-validated contract for what to build, test, and validate. Source documents listed in frontmatter are for traceability — consult them only if you need narrative rationale or prose color this contract intentionally omits.

# Rocell Tile Identification App

## Why

Rocell staff regularly can't identify a tile with no visible product code — an unlabelled showroom sample, a returned box, a customer's leftover piece — and today that knowledge lives only in a few long-serving staff members' memory, costing time and causing misidentification errors. This is a pain to solve for showroom, warehouse, and sales staff, and an operational mandate for Administrators, who need the Catalogue to stay current without routing every new tile range through a developer. General staff rollout is additionally gated on passing an independent penetration test, since the app is the sole gatekeeper to Rocell's full product catalogue and staff account list.

## Capabilities

- **CAP-1 — Auth & Session Management**
  - **intent:** Staff and Administrators can authenticate only via Administrator-provisioned accounts, with sessions that persist safely through a shift and end immediately on deactivation.
  - **success:** A temporary credential reaches only the password-change screen until replaced, and expires unclaimed after 72 hours. A session token lives only in an HTTP-only, Secure, SameSite=Strict cookie. A deactivated user's live session is rejected on the very next request, not at next login.

- **CAP-2 — Tile Scanning & Identification**
  - **intent:** A Staff or Administrator user captures or uploads a tile photo, crops it to just the tile face, and receives up to three visually-ranked candidate matches to confirm by sight.
  - **success:** The submitted Scan is always the cropped region. A materially blurry cropped region prompts a retake before submission. Results always show up to three Candidates with image, code, size, and design — never a single unverifiable answer. Crop-confirmation-to-result stays under 3 seconds.

- **CAP-3 — Admin User Management**
  - **intent:** An Administrator manages the Staff/Administrator population entirely in-app — creating, editing, deactivating, or deleting accounts.
  - **success:** A role edit or deactivation takes effect on the user's very next request, not their next login. The last remaining active Administrator account cannot be deactivated or deleted.

- **CAP-4 — Admin Catalogue Management**
  - **intent:** An Administrator adds, edits, removes, or bulk-loads Products and Reference Images directly, with the Catalogue searchable immediately — no developer or re-import needed.
  - **success:** A Product added mid-session is returned as a Candidate for a Scan submitted later that same session. A bulk upload reports per-row success/failure. A removed Product or Reference Image never resurfaces as a Candidate.

- **CAP-5 — Audit Log & Anomaly/Rate-Limit Defense**
  - **intent:** Every account and Catalogue change is immutably logged and viewable by Administrators; login and scan activity are rate-limited and anomalous patterns flagged.
  - **success:** No update or delete path exists against the audit log, at the application or database-role level. A scan burst is throttled independent of whether it also triggers an anomaly flag.

## Constraints

- Local auth only, no SSO/external IdP — Rocell has none. Admin-provisioned accounts only, no self-registration.
- Server-side authorization on every privileged request, independent of what the UI hides.
- General staff rollout is gated on an independent penetration test passing.
- Two roles only in v1 (Staff, Administrator); at least two active Administrator accounts must exist at all times.
- Every image — a Scan or a Reference Image — is content-validated, re-encoded, and EXIF-stripped before storage, never trusted by file extension.
- Full architecture-level invariants (index/query preprocessing symmetry, session/audit/crop mechanisms, stack, dependency rules) are binding via the adopted `ARCHITECTURE-SPINE.md` — not restated here.
- Full standing security, privacy, and data-retention policy lives in `AGENTS.md` and `addendum.md` (both adopted) — not restated here.

## Non-goals

- No native iOS/Android app — browser-based PWA only.
- No offline scanning.
- No identifying tiles already installed (grouted, angled, partially obscured).
- No price, stock, or specification data — product code only.
- No customer- or dealer-facing access in v1.
- No app-sent email — Administrators distribute credentials manually.
- No ERP, POS, or inventory integration.
- No maintained `size + design → code` mapping table — the Code is the Reference Image's cleaned file name.
- No confidence-gated single-answer result — always up to three Candidates.
- No crop step for admin-added Reference Images (resolved during the architecture Update, not a deferred gap).

## Success signal

In the Phase 2 pilot, top-3 accuracy (SM-1: the correct Product appears among the returned Candidates) and top-1 accuracy (SM-6) both get concrete rollout targets, and crop-confirmation-to-result stays under 3 seconds (SM-2). Post-rollout, weekly-active adoption among showroom staff (SM-3) and a low fallback-to-manual-lookup rate (SM-4) demonstrate real trust in results; Catalogue currency (SM-5) demonstrates the admin-side half of the thesis. Raw scan volume (SM-C1) is deliberately *not* optimized in isolation — a spike uncorrelated with an improving fallback rate is a catalogue-exfiltration signal, not adoption.

## Assumptions

- UJ-1 and UJ-2 (`user-journeys.md`) are narrated from the brief's described flow, not user-provided session transcripts.
- No formal availability SLA for v1 — business-hours availability is the working bar.
- No formal WCAG conformance target for v1, given an internal, admin-provisioned audience.
- The brief's own longer-range vision (extending to warehouse checks, returns, staff training) is deliberately not carried into this spec's Why — scoped to the identification product only.

## Open Questions

- Does the source image set represent the full Catalogue, or a subset? Affects bulk-load scope and accuracy-target realism.
- What's the folder structure of the six category-based image groupings (Cement, Earthen, etc.)? Affects ingestion validation.
- Can canonical reference images move to a Rocell-owned store before Phase 0 ingestion?
- Expected staff count, peak concurrency, and device constraints (company-issued vs. personal phones)?
- Exact scan-image retention period (brief suggests 90 days), and deactivated users' scan-history retention/deletion policy?
- Launch date and budget envelope?
- Does Rocell have an existing IT security or compliance policy this must align with?
- Is business-hours-only availability actually acceptable, or is there a real uptime target?
- Four numeric thresholds (FR-9 blur/framing, FR-14/19 reference-image quality, FR-22 anomaly baseline, FR-23 scan-rate limit) need concrete bounds — calibrated during Foundation build and the Phase 2 pilot.
- FR-24 crop UX specifics: mandatory vs. skippable, free-form vs. fixed-aspect, default selection.
