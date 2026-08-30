---
title: Rocell Tile Identification App
status: final
created: 2026-08-25
updated: 2026-08-30
---

# PRD: Rocell Tile Identification App
*Working title — confirm.*

## 0. Document Purpose

This PRD is for the team building the Rocell Tile Identification App, and for the Rocell stakeholders it's built for, to align on what the product must do before architecture and story breakdown begin. It builds on the product brief (`_bmad-output/planning-artifacts/briefs/brief-rcl_camera_app-2026-08-25/brief.md` + `addendum.md`) and the working repository conventions (`AGENTS.md` / `CLAUDE.md`) rather than repeating them — full security requirement detail, the dataset audit, and technology choices live there, not here. This PRD uses the Glossary in §3 exactly; features are grouped with functional requirements (FR-1 through FR-24) nested beneath them; inferred content is tagged `[ASSUMPTION]` inline and indexed in §13 for confirmation.

## 1. Vision

Rocell staff waste minutes — sometimes give up entirely — trying to identify a tile with no visible product code: an unlabelled showroom sample, a returned box, a piece a customer brings in, something pulled from storage. Today that knowledge lives in a handful of long-serving staff members' memory. The Tile Identification App puts that knowledge in every staff member's pocket: point a phone at a tile, and within seconds see the matching product — not as an opaque code to trust blindly, but as the actual reference photo, alongside two alternates, so the person holding the tile can be sure before they act on it.

For administrators, the app isn't just a lookup tool — it's how the catalogue itself stays current. Adding a new tile range doesn't route through IT or a data engineer; an admin adds it directly, and it's identifiable in the same session.

The system is built to survive an independent penetration test before general staff rollout, because it's the gatekeeper to both Rocell's full product catalogue and its staff account list.

## 2. Target User

### 2.1 Jobs To Be Done

- **Staff (showroom, warehouse, sales):** "When I'm holding a tile with no code I recognize, I want to identify it in seconds, so I can complete the sale, order, or return without guessing or hunting down a colleague who might remember."
- **Administrator (nominated IT/operations staff):** "When a new tile range launches or a staff member joins or leaves, I want to update the system myself, immediately, without waiting on a developer or a data re-import."

### 2.2 Non-Users (v1)

- Customers and dealers — no customer- or dealer-facing access in v1.
- The general public — no self-registration; accounts exist only when an Administrator creates them.
- Anyone trying to identify a tile already installed on a floor or wall (grouted, angled, partially obscured) — out of scope; see §9.

### 2.3 Key User Journeys

- **UJ-1. Kasun identifies an unlabelled tile mid-sale.** `[ASSUMPTION: narrated from the brief's described flow, not a user-provided session — confirm it matches reality.]`
  - **Persona + context:** Kasun, a showroom sales associate, is helping a customer who's brought in a leftover tile from a renovation and wants three more boxes of the same one.
  - **Entry state:** Already authenticated — his session has persisted through the shift. On the showroom floor, PWA installed to his home screen.
  - **Path:** Opens the app → taps Scan → on-screen framing guide helps him fill the frame with the tile face → captures the photo → adjusts the crop selection to the tile face and confirms → brief processing → results screen shows three candidates, each with its reference image, cleaned code, and size/design.
  - **Climax:** The top card's reference image visually matches the tile in his hand within a second or two of looking at it — he doesn't need to recognize a code, just recognize a picture.
  - **Resolution:** He reads the code to the customer and proceeds with the order. The scan is saved to his history.
  - **Edge case:** None of the three candidates look right — he retakes the photo with better framing, or falls back to asking a colleague (this is what Fallback Rate, §11, measures).
  - **Capability mapping:** The system must let an authenticated user capture or upload a photo → FR-6. The system must let the user crop to the tile face before submitting → FR-24. The system must return ranked candidates with images, code, size, and design → FR-7. The system must log the scan to the user's history → FR-8.

- **UJ-2. Nadeesha adds a new tile range the day it arrives.** `[ASSUMPTION: narrated from the brief's described flow, not a user-provided session — confirm it matches reality.]`
  - **Persona + context:** Nadeesha, an operations admin, receives a new tile range and needs it identifiable before it hits the showroom floor.
  - **Entry state:** Authenticated as admin, in the catalogue management screen.
  - **Path:** Opens Add Product → enters the product code → captures or uploads one or more reference images → saves.
  - **Climax:** She runs a test scan against the physical sample in the same session — the new product appears as a match. No ticket filed with engineering, no wait for the next data import.
  - **Resolution:** The catalogue is current; any staff member can now identify that product.
  - **Edge case:** The reference image she uploaded is blurry or badly lit — it's flagged as below the quality threshold so it can be re-shot before it degrades future match quality (§4.4 notes).
  - **Capability mapping:** FR-14 (add product), FR-19 (automatic re-index).

- **UJ-3. Ruwan deactivates a departing staff member.** Ruwan, IT admin, processes an exit on someone's last day: opens the user list, deactivates the account, and their session dies immediately — even if they're still logged in on their phone. → FR-13.

## 3. Glossary

- **Product** — A `Size` + `Design` pair; the unit of identity for the catalogue (e.g. `45X90 / CREMA MARMOL`). Distinct from a **Face**.
- **Design** — A pattern name (e.g. `CREMA MARMOL`, `ASTORIA`).
- **Size** — A tile dimension (e.g. `45X90`, `60X60`).
- **Face** — One manufactured surface variation within a Product. Shade-varying ranges have several Faces; not all are necessarily photographed.
- **Code** — The cleaned reference-image file name returned as the scan result (e.g. `RP.CMA.0001DJ.SM.0T`). Not a separately maintained SKU — see §9 Non-Goals.
- **Reference Image** — A catalogue photo of a Product/Face, indexed for matching. Distinct from a **Scan**.
- **Scan** — The cropped photo a Staff user submits to identify a Product — the result of capturing or uploading (FR-6), then cropping to the tile face (FR-24). The pre-crop capture/upload is an input, not itself the Scan.
- **Candidate** — One of the (up to three) results returned for a Scan: a specific Reference Image — and therefore a specific Product and Face — ranked by visual similarity. Candidates are not deduplicated by Product: two or three Candidates may represent different Faces of the same Product (resolved, OQ-12).
- **Catalogue** — The full set of indexed Products and their Reference Images.
- **Staff** — A user role that can scan, view results, and view their own scan history.
- **Administrator** — A user role with Staff capabilities plus user management and Catalogue management.
- **Session** — An authenticated period of app use, bounded by inactivity and absolute expiry (§5), and immediately revocable by an Administrator.

## 4. Features

### 4.1 Authentication & Session Management

**Description:** Every account is Administrator-provisioned; there is no self-registration or social login. A new Staff or Administrator account is created with a temporary credential that must be changed before any other screen is reachable, closing the window where a manually-distributed password sits readable in a chat thread. Sessions persist through a work shift without repeated logins, and end cleanly — on inactivity, on absolute expiry, or immediately on admin-initiated deactivation.

**Functional Requirements:**

#### FR-1: Admin-provisioned login only

A user can authenticate with email and password only if an Administrator created the account. No public sign-up path exists.

**Consequences (testable):**
- No registration endpoint or UI exists anywhere in the product.
- Social login is not offered.

#### FR-2: Forced password change on first login

A user signing in with a temporary, admin-issued credential can reach only the password-change screen until they set their own password.

**Consequences (testable):**
- Any navigation attempt away from the password-change screen, on a temporary credential, redirects back to it.
- An unclaimed temporary credential stops working after a bounded period (addendum: 72 hours) and must be reissued.

#### FR-3: Session persistence and expiry

A signed-in user stays authenticated through a normal shift without re-entering credentials, within defined inactivity and absolute expiry bounds (addendum: 12h inactivity / 7-day absolute).

**Consequences (testable):**
- No re-authentication prompt appears for actions performed within the inactivity window.
- A session older than the absolute expiry is rejected regardless of activity.
- The session token is never accessible to page script or any client-side storage mechanism — it lives only in a cookie the browser withholds from JavaScript.

#### FR-4: Login rate limiting

Repeated failed login attempts against one account trigger progressive delay, then lockout, both visible to Administrators.

**Consequences (testable):**
- Failed attempt 6+ introduces a measurable delay before the next attempt is accepted.
- The 10th cumulative failed attempt locks the account, blocking further attempts; the lockout is visible in the admin-facing account status.

#### FR-5: Self-service password reset

A signed-in Staff or Administrator user can change their own password at any time.

**Notes:** Password reset is self-service for a signed-in user only — the app does not send reset emails (§9 Non-Goals); a locked-out or forgotten-password user goes through an Administrator.

### 4.2 Tile Scanning & Identification

**Description:** The core staff-facing capability. A user captures or uploads a photo of a tile, crops it down to just the tile face, and receives up to three ranked candidate matches — never a single unverifiable answer — each shown with its reference image so the user can visually confirm before acting on it. Realizes UJ-1.

**Functional Requirements:**

#### FR-6: Capture or upload a scan

An authenticated Staff or Administrator user can capture a live photo via the device camera, with an on-screen framing guide, or upload an existing photo, as the input to a scan.

**Consequences (testable):**
- The framing guide is visible during live capture.
- Both the live-capture and upload paths produce an equivalent scan submission — both proceed to the crop step (FR-24) before submission, uploaded photos included.

#### FR-7: Ranked candidate results with images

The system returns up to three Candidates for a submitted Scan, ranked by visual similarity, each displaying its Reference Image, Code, and folder-derived Size and Design. Realizes UJ-1.

**Consequences (testable):**
- The result screen never displays fewer than the available Candidates or a single "confidence-gated" answer — always up to three (§9 Non-Goals: no confidence-threshold single-result mode).
- Every returned Candidate carries an image, a code, a size, and a design — never a code alone.
- Candidates are ranked purely by visual similarity and are not deduplicated by Product — two or three Candidates may show different Faces of the same Product (resolved, OQ-12).

**Feature-specific NFRs:**
- Crop-confirmation-to-result latency under 3 seconds (§5). Measured from crop confirmation, not initial capture — cropping is user-paced and isn't counted against system latency.

#### FR-8: Scan history

A Staff or Administrator user can view their own past scans, each with the result shown at scan time.

**Consequences (testable):**
- A signed-in user's history shows only their own scans, not other users'.

#### FR-9: Capture quality guidance

The system detects a materially blurry or poorly framed capture and prompts the user to retake it before submitting.

**Consequences (testable):**
- A test image below the blur/framing threshold triggers a retake prompt rather than proceeding to matching. `[ASSUMPTION: the exact threshold isn't set here — see OQ-13.]`

**Out of Scope:** Identifying tiles already installed (grouted, angled, partially obscured) — §9.

#### FR-24: Crop before submit

After capture or upload, the user can adjust a crop selection to isolate the tile face before the Scan is submitted for matching. Realizes UJ-1 (refined).

**Consequences (testable):**
- The submitted Scan is the cropped region, not the original full-frame capture or upload. `[ASSUMPTION: crop defaults to a pre-filled selection — the framing-guide area on a live capture, or an auto-detected best-guess on an upload — which the user can drag/resize before confirming. See OQ-14.]`
- Confirming the crop is required before submission proceeds — there is no skip path directly from capture/upload to matching. `[ASSUMPTION — see OQ-14: is a mandatory crop the right call, or should it be skippable for a photo that's already tight?]`
- The crop selection is free-form (any rectangle within the source image), not locked to a fixed aspect ratio, since tile proportions vary by Product. `[ASSUMPTION — see OQ-14.]`

**Notes:** This is a genuinely new capability, not previously in the brief or an earlier PRD draft — added by explicit request. It has an architecture consequence beyond this PRD's scope: unlike FR-9's blur check, a crop changes *what's in* the image, not just its quality, which interacts with the architecture spine's AD-1 (index/query preprocessing symmetry) and AD-2 (client-side resize is bandwidth-only, never the preprocessing boundary). Worth noting in the product's favor: reference images are already expected to be "tile face fills the frame, no background clutter" (brief `addendum.md`, Target State for the Reference Set) — so a tightened query-time crop likely *improves* index/query symmetry rather than breaking it, but the spine should say so explicitly rather than leave it implied. `[NOTE FOR PM]` Flag this FR for an architecture spine Update before or during Foundation build.

### 4.3 Admin — User Management

**Description:** Administrators manage the Staff and Administrator population entirely within the app — no external identity tooling in v1 (confirmed, OQ-6: no existing IdP to integrate with). Deactivation is immediate and revokes live access, not just future logins.

**Functional Requirements:**

#### FR-10: User list

An Administrator can view all users with status (active/deactivated) and last login.

**Consequences (testable):**
- A deactivated user's status is visually distinct from an active user's in the same list — no separate screen is required to check it.

#### FR-11: Create user

An Administrator can create a user with name, email, role, and an initial (temporary) password. The app does not email the credential — the Administrator communicates it manually (§9 Non-Goals).

**Consequences (testable):**
- The created user can authenticate immediately with the initial temporary credential, and per FR-2, reaches only the password-change screen until it's replaced.

#### FR-12: Edit user

An Administrator can edit a user's name, email, or role.

**Consequences (testable):**
- A role change takes effect on the user's live session, not only at their next authentication — consistent with FR-13's immediate-revocation precedent for deactivation.

#### FR-13: Deactivate or delete user

An Administrator can deactivate or delete a user. Deactivation revokes that user's live sessions immediately, not only their next login attempt. Realizes UJ-3.

**Consequences (testable):**
- A session token valid before deactivation is rejected on the next request after deactivation, without waiting for expiry.
- Deactivating or deleting the last remaining active Administrator account is refused — at least two active Administrator accounts must exist at all times, so a single action can't lock Rocell out of its own user management.

### 4.4 Admin — Catalogue Management

**Description:** The mechanism by which the Catalogue stays current without developer involvement. An Administrator can add, edit, remove, and bulk-load Products and their Reference Images directly; changes are searchable immediately. Realizes UJ-2.

**Functional Requirements:**

#### FR-14: Add product

An Administrator can add a new Product by entering a code and uploading or capturing one or more Reference Images. The Product becomes matchable against new Scans without developer involvement or a data re-import. Realizes UJ-2.

**Consequences (testable):**
- A Product added mid-session is returned as a Candidate for a Scan submitted later in that same session.

#### FR-15: Edit product

An Administrator can change a Product's code and add, replace, or remove its Reference Images.

**Consequences (testable):**
- A removed Reference Image is no longer returned as a Candidate for any Scan submitted after the edit, even if it was returned before.

#### FR-16: Remove product

An Administrator can remove a Product from the Catalogue (e.g. a discontinued range); it no longer appears as a Candidate.

**Consequences (testable):**
- A Scan submitted after removal never returns the removed Product as a Candidate, regardless of visual similarity.

#### FR-17: Bulk upload

An Administrator can bulk-load Products via a set of images plus a spreadsheet of codes, for initial Catalogue load and for large new ranges.

**Consequences (testable):**
- A bulk upload of N valid product/image pairs results in all N being individually searchable, with a per-row success/failure report for any that fail validation.

#### FR-18: Catalogue search

An Administrator can search and filter the Catalogue by product code to find an entry quickly.

**Consequences (testable):**
- A partial code match returns all Products whose Code contains it, not only exact matches.

#### FR-19: Automatic re-index

Any Catalogue change (add, edit, remove, bulk upload) is reflected in match results without a separate manual re-indexing step. Realizes UJ-2.

**Notes:** `[NOTE FOR PM]` Reference images added via a quick in-app capture (vs. a studio asset) may match less reliably under real showroom conditions — see Risk R-2, §7. Consider flagging admin-added images that fall below a quality threshold for later re-shooting, mirroring FR-9's capture guidance. `[ASSUMPTION: the exact quality threshold isn't set here — see OQ-13.]`

### 4.5 Audit Log & Anomaly Monitoring

**Description:** Every account and Catalogue change is attributable, timestamped, and permanent. This is the primary control against the two threats the brief identifies as realistic — catalogue exfiltration and credential sharing — and the reason a shared login would make this system's audit trail worthless.

**Functional Requirements:**

#### FR-20: Immutable audit log

The system records every login, failed login, user creation/modification/deactivation/deletion, and Catalogue change, with who, what, when, and source IP.

**Consequences (testable):**
- No update or delete operation exists against audit log entries, from application code or the admin UI.

#### FR-21: Audit log visibility

An Administrator can view the audit log within the app.

**Consequences (testable):**
- The audit log view offers no edit or delete control anywhere in its UI, consistent with FR-20's append-only guarantee.

#### FR-22: Anomaly flagging

The system flags activity patterns consistent with misuse — unusual login times, logins from unexpected locations, or scanning volume consistent with catalogue scraping — for admin review.

**Consequences (testable):**
- A login or scanning pattern outside the user's own established baseline generates a flag reviewable by an Administrator, distinct from and in addition to FR-23's hard throttle. `[ASSUMPTION: the exact baseline/window/multiplier isn't set here — see OQ-13.]`

#### FR-23: Scan rate limiting

The system rate-limits scan submissions per user, bounding the volume achievable by a single compromised or misused account. This is a preventive control alongside FR-22's detective anomaly flagging — catalogue exfiltration via a compromised account is the primary commercial threat this pair of FRs defends against.

**Consequences (testable):**
- A user submitting scans above a defined threshold within a bounded window is throttled or blocked, independent of whether the pattern also triggers an FR-22 anomaly flag. `[ASSUMPTION: the exact threshold isn't set here — see OQ-13.]`

**Feature-specific NFRs:**
- Audit entries are write-once; enforced independent of any admin-facing permission (§5 Security).

## 5. Cross-Cutting NFRs

- **Performance:** Crop-confirmation-to-result under 3 seconds, end to end (validates via SM-2). Cropping (FR-24) is user-paced and excluded from the budget — the clock starts when the user confirms the crop, not when they open the camera.
- **Security:** Every privileged action is authorized server-side, independent of what the UI hides; no credential or secret is ever stored or transmitted in recoverable form. Every image upload — a Scan (FR-6) or a catalogue Reference Image (FR-14, FR-15, FR-17) — is validated by content inspection, never by file extension, and re-encoded before storage. This PRD states the product-facing consequence of each rule inline against the relevant FR; the complete standing rule set lives in `AGENTS.md` (Policy) and the brief's `addendum.md` — this PRD does not duplicate it.
- **Auditability:** Every account and Catalogue change is attributable to a specific Administrator, timestamped, and permanent (FR-20–22).
- **Availability:** `[ASSUMPTION]` No formal SLA defined for v1 — availability during Rocell business hours is the working bar. Confirm or set a real target (§12).
- **Accessibility:** `[ASSUMPTION]` No formal WCAG conformance target for v1, given an internal, admin-provisioned audience — basic readability and tap-target sizing on mobile is still expected. Revisit if the audience broadens.

## 6. Constraints and Guardrails

**Privacy**

- Staff personal data is limited to name, email, and role — nothing else is collected.
- Every uploaded or scanned image is stripped of EXIF metadata (GPS, device identifiers) before storage.
- Scanned images are retained for a bounded period, then purged automatically. Exact duration is open — brief suggests 90 days (§12).
- Deactivated users' scan history retention/deletion policy is open (§12).

## 7. Risk and Mitigations

| ID | Risk | Impact | Mitigation |
|---|---|---|---|
| R-1 | Visually identical products (same design, different size/finish) | High — may be unresolvable from an image alone | FR-7: always return top 3 with images, user confirms |
| R-2 | Reference images are studio assets; scans are phone photos under showroom lighting | High — pilot accuracy will overstate real-world accuracy | Supplement the index with phone-captured reference images before general rollout |
| R-3 | Sparse reference coverage (~2 images/product against ~9 manufactured faces) | High — a user may scan a Face the system has never seen | Capture additional faces for high-variation, high-volume ranges before launch |
| R-4 | Canonical images live in personal accounts, not a Rocell-owned store | High business-continuity risk | Migrate to a Rocell-owned store before ingestion (Phase 0, §8) |
| R-5 | Manual credential distribution / shared logins | High | FR-2 forced first-login change; individual accounts with visible last-login (FR-10) make sharing detectable |

Full 14-item risk register: `_bmad-output/planning-artifacts/briefs/brief-rcl_camera_app-2026-08-25/addendum.md`.

## 8. Rollout and Change Management

0. **Dataset consolidation** — migrate reference images to a Rocell-owned store, audit coverage and naming. Prerequisite for a realistic accuracy estimate, not a hard blocker on starting Phase 1.
1. **Foundation** — FR-1–5 (auth), FR-20–22 (audit), FR-10–19 (admin user/catalogue management), indexing pipeline.
2. **Scanning pilot** — FR-6–9, FR-24 against a 150–200 product pilot Catalogue. Internal accuracy testing sets the SM-1 target.
3. **Full rollout** — full Catalogue ingestion, tuning from pilot findings, staff training. **Gated on an independent penetration test passing.**
4. **Refinement** — accuracy improvements from real scan data, reference-image backfill for weak products.

## 9. Non-Goals (Explicit)

- Not a native iOS/Android app — browser-based PWA only.
- Not an offline-capable product — scanning requires connectivity.
- Not a system for identifying tiles already installed (grouted, angled, partially obscured surfaces).
- Not a price, stock, or specification lookup — product code only.
- Not customer- or dealer-facing, in any form, in v1.
- Not an email-sending system — credentials are distributed by an Administrator outside the app.
- Not an ERP, POS, or inventory integration.
- Not a maintained `size + design → product code` mapping table — the returned Code is the cleaned Reference Image file name (§3).
- `[NON-GOAL for MVP]` Not a single-answer / confidence-gated result — see FR-7.

## 10. MVP Scope

### 10.1 In Scope

- Everything in FR-1 through FR-24 (FR-24, crop before submit, added in a later update — see `.memlog.md`). Both phase-blocking forks flagged during the original review are resolved: FR-7's Candidate-dedup semantics (OQ-12 — Candidates are not deduplicated by Product) and the auth approach (OQ-6 — no existing IdP, local auth per FR-1–5 stands). FR-24's own open items are non-blocking (OQ-14) but its architecture-spine consequence should land before or during Foundation build (see FR-24 Notes).

### 10.2 Out of Scope for MVP

- Native mobile apps — `[NOTE FOR PM]` revisit if adoption data from the PWA shows friction that native would solve.
- SSO / external identity provider integration — resolved, not deferred (OQ-6): Rocell has no existing IdP, so this isn't a v2 candidate pending integration, it's simply not applicable.
- Automated invitation or password-reset email.
- Any data field beyond product code (price, stock, specification).

## 11. Success Metrics

**Primary**
- **SM-1**: Top-3 accuracy — the correct Product appears among the returned Candidates. Target set after the Phase 2 pilot (§8). Validates FR-7.
- **SM-2**: Time to result — crop confirmation to displayed candidates, under 3 seconds. Validates FR-6, FR-7, FR-24.

**Secondary**
- **SM-3**: Adoption — proportion of showroom staff scanning at least weekly. Validates FR-6.
- **SM-4**: Fallback rate — proportion of scan attempts abandoned in favor of manual lookup. Validates FR-7 (inverse indicator: high fallback means results aren't trustworthy enough to act on).
- **SM-5**: Catalogue currency — time from a new range's arrival to being searchable. Validates FR-14, FR-19.
- **SM-6**: Top-1 accuracy — the correct Product is the first-ranked Candidate. Diagnostic alongside SM-1 (top-3 is the metric that reflects real-world usefulness) — tracked to catch a system that's consistently close but wrong at #1. Validates FR-7.

**Counter-metrics (do not optimize)**
- **SM-C1**: Raw scan volume per user. A spike here without a corresponding drop in Fallback Rate (SM-4), or one concentrated in a single account, is a catalogue-exfiltration signal (§7) — not evidence of adoption. Counterbalances SM-3.

## 12. Open Questions

1. Top-1 (SM-6) and top-3 (SM-1) accuracy targets — set after the Phase 2 pilot.
2. Does the source image set represent the full Catalogue, or a subset? Affects FR-17 bulk-load scope and the realism of any accuracy target.
3. Unconfirmed folder structure for the six category-based image groupings — affects ingestion validation for FR-14/17/19.
4. Can the canonical reference images move to a Rocell-owned store before Phase 0 ingestion?
5. Expected staff count, peak concurrency, and device constraints (company-issued vs. personal phones) — affects §5 Performance sizing.
6. **[RESOLVED]** Is there an existing identity provider (Microsoft 365, Google Workspace) staff already use? — No. Local auth per FR-1–5 is confirmed, not a placeholder pending SSO.
7. Exact scan-image retention period (§6 Privacy) — brief suggests 90 days.
8. Deactivated users' scan-history retention/deletion policy (§6 Privacy).
9. Launch date and budget envelope — no target set yet.
10. Does Rocell have an existing IT security or compliance policy this must align with? None is currently assumed; if one exists, §5 Security and §6 Privacy may need to expand.
11. §5 Availability: is business-hours-only availability actually acceptable, or is there a real uptime expectation?
12. **[RESOLVED]** Must the three Candidates in FR-7 be distinct Products, or can they include multiple Faces of the same Product? — Can repeat: Candidates are not deduplicated by Product. This means SM-1/SM-6 accuracy counts a Scan as correct if any returned Candidate matches the true Product, even if another Candidate is a different Face of that same Product.
13. Four functional thresholds are referenced but not numerically set: FR-9's blur/framing threshold, FR-14/19's reference-image quality threshold, FR-22's anomaly baseline (login time/location, scan-volume pattern), and FR-23's scan-rate limit. Each needs a concrete bound — calibrated during the Foundation build and the Phase 2 pilot, not prescribed here.
14. FR-24's crop UX isn't nailed down: is confirming the crop mandatory, or skippable for a photo that's already tight? Free-form rectangle or a fixed/suggested aspect ratio? Auto-detected default selection, or always starting from the full frame? Resolve during UX/build, not blocking the PRD.

## 13. Assumptions Index

- §2.3 UJ-1, UJ-2 — narrated from the brief's described flow, not a user-provided session transcript.
- §5 Availability NFR — no formal SLA assumed for v1.
- §5 Accessibility NFR — no formal WCAG conformance target assumed for v1.
- §1 Vision — the brief's own `[ASSUMPTION]` vision (extending the capability to warehouse checks, returns, and staff training) is deliberately not carried into this PRD's Vision, which scopes to the identification product only. Not an oversight — a scoping decision. Revisit as a separate initiative if Rocell wants it pursued.
- FR-9, FR-19 Notes, FR-22, FR-23 — none of the four thresholds these FRs depend on is numerically set; consolidated as OQ-13.
- FR-24 — crop-selection defaults, mandatory-vs-skippable, and free-form-vs-fixed-aspect are all inferred, not confirmed; consolidated as OQ-14.
