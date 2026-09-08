---
stepsCompleted: ["step-01-validate-prerequisites", "step-02-design-epics", "step-03-create-stories", "step-04-final-validation"]
inputDocuments:
  - _bmad-output/specs/spec-rcl_camera_app/SPEC.md
  - _bmad-output/specs/spec-rcl_camera_app/functional-requirements.md
  - _bmad-output/planning-artifacts/architecture/architecture-rcl_camera_app-2026-08-30/ARCHITECTURE-SPINE.md
  - _bmad-output/planning-artifacts/prds/prd-rcl_camera_app-2026-08-25/prd.md
  - poc/README.md
  - _bmad-output/planning-artifacts/ux-designs/ux-rcl_camera_app-2026-09-08/DESIGN.md
  - _bmad-output/planning-artifacts/ux-designs/ux-rcl_camera_app-2026-09-08/EXPERIENCE.md
---

# Rocell Tile Identification App - Epic Breakdown

## Overview

This document provides the complete epic and story breakdown for the Rocell Tile Identification App, decomposing the requirements from `SPEC.md` (primary, cross-checked against the raw PRD), the architecture spine, and the UX design contract into implementable stories.

**UI/UX contract (binding).** The design contract is the `DESIGN.md` + `EXPERIENCE.md` spine pair at `_bmad-output/planning-artifacts/ux-designs/ux-rcl_camera_app-2026-09-08/`. `DESIGN.md` owns how it looks (tokens, component visual specs); `EXPERIENCE.md` owns how it works (IA, component behavior, state patterns, interaction primitives, accessibility floor, key flows). The four rendered mockups in that run's `mockups/` folder illustrate four surfaces — **the spines win on conflict with any mockup**. Every UI story below is built against those two files, not against a developer's own visual judgment.

**Whoever implements a UI story must invoke the `ui-ux-pro-max` skill** before and during that work — it carries the searchable UX/accessibility rule database, stack-specific implementation guidance, and the pre-delivery checklist (touch targets, focus states, contrast, icon discipline, reduced-motion, responsive breakpoints). It has already earned its place on this project: its checklist caught a 36px touch target in a mockup that violated this spine's own ≥44×44px accessibility floor. Run its `--design-system` and `--domain ux` searches against the relevant surface, then run the pre-delivery checklist before calling a UI story done. It supplements the spine pair — it never overrides it; where the two differ, `DESIGN.md`/`EXPERIENCE.md` win.

## Requirements Inventory

### Functional Requirements

FR-1: Admin-provisioned login only — a user authenticates with email/password only if an Administrator created the account; no registration endpoint or social login exists anywhere in the product.
FR-2: Forced password change on first login — a temporary, admin-issued credential can reach only the password-change screen until replaced; unclaimed temporary credentials expire after 72 hours.
FR-3: Session persistence and expiry — a signed-in user stays authenticated through a shift (12h inactivity / 7-day absolute expiry); the session token lives only in an HTTP-only/Secure/SameSite=Strict cookie, hashed at rest.
FR-4: Login rate limiting — progressive delay from the 6th failed attempt; the 10th cumulative failed attempt locks the account, visible to Administrators.
FR-5: Self-service password reset — a signed-in user can change their own password at any time; no reset emails are sent.
FR-6: Capture or upload a scan — live camera capture (with an on-screen framing guide) or photo upload as the input to a Scan; both paths proceed to the crop step.
FR-7: Ranked candidate results with images — up to three Candidates ranked by visual similarity, each with reference image, code, size, and design; never a single unverifiable answer; Candidates are not deduplicated by Product.
FR-8: Scan history — a user views their own past scans, each showing the result as it was at scan time (a snapshot, unaffected by later catalogue changes).
FR-9: Capture quality guidance — a materially blurry or poorly-framed cropped region (checked after crop) triggers a retake prompt before matching proceeds.
FR-10: User list — Administrators view all users with status (active/deactivated) and last login.
FR-11: Create user — Administrator creates a user with name/email/role/temporary password; no email sent, communicated manually.
FR-12: Edit user — Administrator edits name/email/role; a role change takes effect on the user's live session immediately.
FR-13: Deactivate or delete user — revokes live sessions immediately; the last remaining active Administrator cannot be deactivated/deleted.
FR-14: Add product — Administrator adds a new Product with a code and one or more reference images; searchable immediately, no developer involvement.
FR-15: Edit product — Administrator changes a Product's code and adds/replaces/removes its reference images; a removed image never resurfaces as a Candidate.
FR-16: Remove product — Administrator removes a Product from the Catalogue; never returned as a Candidate again (hard delete).
FR-17: Bulk upload — Administrator bulk-loads Products via an image set + spreadsheet of codes, with a per-row success/failure report.
FR-18: Catalogue search — Administrator searches/filters the Catalogue by product code, including partial matches.
FR-19: Automatic re-index — any Catalogue change is reflected in match results with no separate manual re-indexing step.
FR-20: Immutable audit log — every login, failed login, user change, and Catalogue change is logged with who/what/when/source IP; no update or delete path exists at any level.
FR-21: Audit log visibility — Administrators view the audit log in-app; no edit/delete control exists in that UI.
FR-22: Anomaly flagging — unusual login times/locations or scan volume consistent with scraping is flagged for admin review.
FR-23: Scan rate limiting — per-user throttle on scan submissions, independent of anomaly flagging, enforced via atomic counters.
FR-24: Crop before submit — after capture/upload, the user adjusts a crop selection to isolate the tile face before submission; the submitted Scan is always the cropped region, executed server-side.

### NonFunctional Requirements

NFR1 (Performance): Crop-confirmation-to-result under 3 seconds, end to end.
NFR2 (Security): Every privileged action is authorized server-side, independent of what the UI hides; no credential/secret ever stored or transmitted in recoverable form; every image (Scan or Reference Image) is content-validated, re-encoded, and EXIF-stripped before storage.
NFR3 (Security — network): No presigned or direct-to-storage URLs, upload or download — every image byte proxied through the API.
NFR4 (Auditability): Every account and Catalogue change is attributable, timestamped, and permanent; enforced at the database-role level (no UPDATE/DELETE grant on the audit table), not just app code.
NFR5 (Availability): No formal SLA for v1 — business-hours availability is the working bar (open question — confirm before general rollout).
NFR6 (Accessibility): No formal WCAG conformance target for v1, given an internal admin-provisioned audience; basic readability/tap-target sizing still expected.
NFR7 (Compliance gate): General staff rollout is gated on an independent penetration test passing.
NFR8 (Data protection): Staff PII limited to name/email/role; scanned images retained for a bounded period (duration open, ~90 days suggested) then purged automatically.

### Additional Requirements

- No starter/scaffolding template specified. Stack is pinned (React 19.2.x / Vite 8.0.x / TypeScript 7.0.x for `apps/web`; FastAPI 0.141.x / Python 3.12+ for `apps/api`; PostgreSQL 18.x + pgvector ≥0.8.2 with HNSW; ONNX Runtime 1.25.x + DINOv2 for embeddings), but there is no generator to run — Epic 1 Story 1 must scaffold the monorepo by hand per the Structural Seed (`apps/web`, `apps/api`, `shared/vision`, `shared/schema`, `infra`, `scripts/ingest`).
- pgvector's PostgreSQL-18 compatibility is unconfirmed as of authoring (verified testing covered 16/17 only) — confirm at build time before committing to Postgres 18.
- 17 binding architecture invariants (AD-1 through AD-17) govern implementation; the dev agent must read `ARCHITECTURE-SPINE.md` directly, not just this summary. Notably: `shared/vision`'s preprocessing/embedding is called identically by the live API and the batch ingest script, never forked (AD-1); crop executes server-side only, client sends the full downscaled image plus normalized coordinates, never a pre-cropped image (AD-11); sessions and rate-limit counters live in Postgres, not Redis (AD-3, AD-8); audit-log immutability is enforced at the DB-role level, not just app code (AD-4); scan history is a denormalized snapshot, never a live foreign key to Reference Image (AD-10).
- **A working POC (`poc/`) validates the core matching approach and pins five more invariants (AD-13–17), reconciled into the architecture spine on 2026-09-08.** The dev agent should port `shared/vision` directly from `poc/tilematch/vision.py` — it was written to lift into production unchanged, not to be reimplemented from. Key points affecting Epic 2/3 stories: each Reference Image needs **up to 16 embeddings** (4 rotations + 12 augmented crops), not one — `REFERENCE_IMAGE` gained a child `REFERENCE_EMBEDDING` entity in the ERD (AD-13); ICC color management is mandatory in `shared/vision` before any other step — ~60% of the real catalogue is CMYK press files, and a naive RGB conversion silently corrupts both the displayed color and the embedding (AD-15); reference images are served from a pre-generated, capped derivative, never the original or an on-demand render (AD-17); embedding inference is serialized server-side, independent of abuse-defense rate limiting — concurrent CPU-bound inference measured 12× slower under load (AD-16); the index carries a pipeline-version stamp and refuses to search a mismatched generation (AD-14).
- **Real accuracy data exists and is worse at scale than assumed.** The POC measured top-3 79.5% at 36 products, dropping to 70.0% at 76 products, on an unchanged pipeline — production targets a catalogue far larger than either measurement. This is a bigger, more concrete risk than anything in the PRD's current risk register and should inform the Epic 3 / Phase 2 pilot's accuracy targets directly, not just the architecture.
- **White balance is the single dominant measured accuracy lever** (+6.6 top-3 points, ahead of crop/perspective/blur/JPEG) — worth capture guidance beyond the existing framing guide; not yet a committed story (see Story 3.1 note).
- Five infrastructure decisions are Deferred with no answer yet: hosting/deployment provider & environments (dev/staging/prod)/CI-CD, S3-compatible object storage provider, secrets management approach, backup/DR strategy, monitoring/observability stack. These block real deployment work and should be resolved early in Epic 1, even though architecture didn't pin them.
- Phase 0 dataset consolidation — migrating reference images off personal Gmail accounts onto a Rocell-owned store — is a named prerequisite in both the brief and the architecture spine's rollout phasing. Likely its own epic or an early story, not incidental cleanup. The POC's real data audit sharpens this: of the real source tree, 2 files are zero-byte (unusable), 11 tiles have no recoverable design name, and 15 have no recoverable face number — Epic 2's bulk-upload story must treat these as expected data conditions to flag, not errors that block a whole batch.

### UX Design Requirements

Extracted from `DESIGN.md` + `EXPERIENCE.md`. Each is specific enough to carry testable acceptance criteria. Implement every one of these against the spine pair, with the `ui-ux-pro-max` skill applied per the Overview.

**Foundation — design tokens and type**

UX-DR1: Implement the full `DESIGN.md` token set as the single styling source (11 color tokens, 6 typography roles, 4 radii + `full`, 10-step spacing scale, navy-tinted elevation `0 2px 8px rgba(19,27,94,0.08)`). No raw hex values in components — every color reference resolves to a token.
UX-DR2: Load Plus Jakarta Sans (weights 400/500/600/700/800) for all six type roles, and JetBrains Mono for the `code` role used by product Codes, each with a declared fallback stack.
UX-DR3: Adopt Phosphor icons at `regular` (outline) weight, 20–24px, throughout. No filled/duotone icons, no emoji as icons.

**Reusable components — visual spec in `DESIGN.md.Components`, behavior in `EXPERIENCE.md.Component Patterns`**

UX-DR4: `button-primary` (accent fill, **navy** foreground — never white, see UX-DR17), `button-secondary` (navy outline/text, transparent fill), `button-destructive` (red fill, white text). Exactly one primary button per screen.
UX-DR5: `app-bar` — navy fill, white content, 3–4px accent stripe along the bottom edge. Present on every authenticated screen.
UX-DR6: `card` and `candidate-card-best-match` — the top-ranked Candidate takes a 2px accent border instead of the neutral hairline.
UX-DR7: `badge-role-admin`, `badge-role-staff`, `badge-status-deactivated` — display-only, never interactive, never a button.
UX-DR8: `data-table-row` (dense desktop admin table: surface bg, hover bg, hairline separators, no card wrapper/shadow), `audit-log-row` (identical treatment, zero row-end actions), `flagged-activity-row` (audit row + an accent flag glyph).
UX-DR9: `framing-guide-overlay` — accent outline rectangle over the live viewfinder, transparent fill, doesn't block the shutter control.
UX-DR10: `crop-selector` — accent border, white handles with accent border sized to satisfy the 44px touch floor, dark scrim over the deselected area, free-form (no fixed aspect ratio).
UX-DR11: `retake-prompt` — inline surface-colored banner directly above the primary action. Never a modal.
UX-DR12: `force-password-change-form` — single-field form, no surrounding nav chrome, destructive-colored inline errors naming the failed rule.
UX-DR13: `confirmation-dialog` — sheet over a scrim, names the object and its consequence in body text, confirm action styled `button-destructive` when the action is destructive.
UX-DR14: `upload-report-row` — per-row result with navy success / red failure / orange flagged-for-review indicators.
UX-DR15: `save-indicator` — muted at rest, shifts to navy on `Saved.`; inline near its triggering action, never a corner toast. Never orange.

**Behavior, states, and accessibility**

UX-DR16: Implement every one of the 13 state patterns in `EXPERIENCE.md.State Patterns` — not just happy paths. Specifically includes: camera-permission-not-granted (with always-visible upload fallback), processing, no-confident-match, submission/matching failure (distinct from no-match, preserving the crop), scan rate-limited, session-expired mid-flow, empty catalogue search, empty scan history, deactivated-account login, login lockout, bulk-upload-in-progress, weak/mismatched password, and live role-change mid-session.
UX-DR17: Accessibility floor — ≥44×44px touch targets on every mobile surface (including candidate cards and crop handles), visible focus states with a keyboard path on all admin surfaces, no color-only signaling on destructive actions (label + icon, not red alone), and the verified contrast pairs from `DESIGN.md` (navy-on-orange at 5.94:1 for the primary button — **white-on-orange fails at 2.63:1 and must not be used**).
UX-DR18: Responsive behavior — bottom tab bar on mobile (Scan / History, Admin sections behind a "More" tab), sidebar nav at desktop/tablet widths, with the spacing density shifting at the same breakpoint. No drawer on mobile; modal/sheet depth never exceeds one level.
UX-DR19: Microcopy follows `EXPERIENCE.md.Voice and Tone` verbatim where quoted ("Best match" never a percentage; "Fill the frame with the tile face."; plain factual errors; no exclamation marks, no gamified language).

### UX-DR Coverage Map

UX-DRs are covered inside the epics that first need them — no separate design-system epic, consistent with this document's "build only what the story needs" discipline.

UX-DR1, UX-DR2, UX-DR3: Epic 1, Story 1.1 — the token layer, fonts, and icon set land with the first UI ever rendered (login), then serve every later story.
UX-DR4, UX-DR5, UX-DR13, UX-DR15: Epic 1, Stories 1.1–1.9 — buttons, app bar, confirmation dialog (first needed by Story 1.9's deactivate), save indicator (first needed by Story 1.6).
UX-DR12: Epic 1, Story 1.2 — force password change form.
UX-DR7, UX-DR8: Epic 1, Stories 1.7 and 1.10–1.11 — role/status badges and the data-table/audit-log row treatments.
UX-DR14: Epic 2, Story 2.4 — per-row bulk upload report.
UX-DR6: Epic 3, Story 3.4 — card and best-match candidate card.
UX-DR9: Epic 3, Story 3.1 — framing guide overlay.
UX-DR10: Epic 3, Story 3.2 — crop selector.
UX-DR11: Epic 3, Story 3.3 — retake prompt.
UX-DR16, UX-DR17, UX-DR18, UX-DR19: cross-cutting — every story that renders UI carries the state, accessibility, responsive, and microcopy obligations for its own surface. These are acceptance criteria on each UI story, not a separate cleanup story at the end.

### FR Coverage Map

FR-1: Epic 1 - Admin-provisioned login only
FR-2: Epic 1 - Forced password change on first login
FR-3: Epic 1 - Session persistence and expiry
FR-4: Epic 1 - Login rate limiting
FR-5: Epic 1 - Self-service password reset
FR-6: Epic 3 - Capture or upload a scan
FR-7: Epic 3 - Ranked candidate results with images
FR-8: Epic 3 - Scan history
FR-9: Epic 3 - Capture quality guidance
FR-10: Epic 1 - User list
FR-11: Epic 1 - Create user
FR-12: Epic 1 - Edit user
FR-13: Epic 1 - Deactivate or delete user
FR-14: Epic 2 - Add product
FR-15: Epic 2 - Edit product
FR-16: Epic 2 - Remove product
FR-17: Epic 2 - Bulk upload
FR-18: Epic 2 - Catalogue search
FR-19: Epic 2 - Automatic re-index
FR-20: Epic 1 - Immutable audit log (infrastructure + auth/account events; extended by Epic 2 for catalogue events and Epic 3 for scan events)
FR-21: Epic 1 - Audit log visibility
FR-22: Epic 3 - Anomaly flagging
FR-23: Epic 3 - Scan rate limiting
FR-24: Epic 3 - Crop before submit

## Epic List

### Epic 1: Access & Account Management
Staff and Administrators can be provisioned with secure, admin-controlled accounts; every account and access event is immutably logged and visible to Administrators.
**FRs covered:** FR-1, FR-2, FR-3, FR-4, FR-5, FR-10, FR-11, FR-12, FR-13, FR-20, FR-21

### Epic 2: Catalogue Management
Administrators can build and maintain the tile Catalogue directly — adding, editing, removing, and bulk-loading Products and Reference Images — with changes searchable immediately and no developer involvement.
**FRs covered:** FR-14, FR-15, FR-16, FR-17, FR-18, FR-19

### Epic 3: Tile Scanning & Identification
Staff can photograph an unidentified tile, crop it to the tile face, and get up to three visually-verifiable candidate matches in seconds — with the scanning capability itself defended against abuse.
**FRs covered:** FR-6, FR-7, FR-8, FR-9, FR-24, FR-22, FR-23

## Epic 1: Access & Account Management

Staff and Administrators can be provisioned with secure, admin-controlled accounts; every account and access event is immutably logged and visible to Administrators.

**UI contract:** build against `DESIGN.md` + `EXPERIENCE.md` (ux-rcl_camera_app-2026-09-08); invoke the `ui-ux-pro-max` skill and run its pre-delivery checklist before calling any UI story here done. Covers UX-DR1–5, 7, 8, 12, 13, 15.

**Ordering note:** Login (1.1) comes before Create User (1.6) — the first Administrator account is seeded via a deployment migration (a Dev Note, not a story), so login doesn't circularly depend on the create-user feature it will later gate.

### Story 1.1: Admin-Provisioned Login

As a Staff or Administrator with an account,
I want to log in with my email and password,
So that I can access the app I'm authorized to use.

**Acceptance Criteria:**

**Given** an account was created by an Administrator (the first Administrator is seeded via a deployment migration, not this story)
**When** the user submits the correct email and password
**Then** they are authenticated and issued a session
**And** no matching account or wrong password rejects login without revealing which field was invalid, and no registration endpoint or UI exists anywhere in the product.

### Story 1.2: Forced Password Change on First Login

As a new user signing in with an admin-issued temporary password,
I want to be required to set my own password before doing anything else,
So that the temporary password doesn't linger as a standing risk.

**Acceptance Criteria:**

**Given** a user authenticates with a temporary credential
**When** they land in the app
**Then** they can reach only the password-change screen, and any attempt to navigate elsewhere redirects back to it
**And** an unclaimed temporary credential stops working after 72 hours and must be reissued by an Administrator.

### Story 1.3: Session Persistence & Expiry

As a signed-in Staff or Administrator,
I want my session to persist through a normal shift and end safely when appropriate,
So that I'm not interrupted but also not left exposed.

**Acceptance Criteria:**

**Given** a user is active within 12 hours of their last request
**When** they perform an action
**Then** no re-authentication is required
**And** a session older than 7 days is rejected regardless of activity, and the session token is never accessible to client-side JavaScript or browser storage — HTTP-only, Secure, SameSite=Strict cookie only, stored hashed at rest.

### Story 1.4: Login Rate Limiting

As the system,
I want to slow down and eventually block repeated failed login attempts against one account,
So that credential-guessing attacks are impractical.

**Acceptance Criteria:**

**Given** 5 consecutive failed attempts on one account
**When** the 6th attempt is made
**Then** a measurable delay is introduced before it's processed
**And** the 10th cumulative failed attempt locks the account, blocking further attempts, visible to Administrators on that user's status.

### Story 1.5: Self-Service Password Reset

As a signed-in Staff or Administrator,
I want to change my own password at any time,
So that I can update it without needing an Administrator.

**Acceptance Criteria:**

**Given** a signed-in user submits a valid current password and a new one
**When** the change is confirmed
**Then** the password updates immediately
**And** no self-service option exists for a signed-out user — no reset email is sent by the app; they must go through an Administrator.

### Story 1.6: Create User Account

As an Administrator,
I want to create a new Staff or Administrator account with an initial temporary password,
So that I can grant access without waiting on a developer.

**Acceptance Criteria:**

**Given** I am an authenticated Administrator
**When** I submit a name, email, role, and initial temporary password
**Then** the account is created and immediately usable to log in, gated by Story 1.2
**And** no option to email the credential exists — I communicate it manually; a Staff user attempting this action is refused server-side regardless of what the UI shows.

### Story 1.7: View User List

As an Administrator,
I want to see every user's status and last login,
So that I can audit who has access.

**Acceptance Criteria:**

**Given** I am an authenticated Administrator
**When** I open the user list
**Then** I see every account with its active/deactivated status and last-login timestamp
**And** a deactivated user's status is visually distinct, with no separate screen needed to check it.

### Story 1.8: Edit User

As an Administrator,
I want to edit a user's name, email, or role,
So that account details and access levels stay accurate.

**Acceptance Criteria:**

**Given** I am an authenticated Administrator
**When** I change a user's role
**Then** the change takes effect on that user's very next request, not only at their next login
**And** a non-Administrator attempting this action is refused server-side regardless of what the UI hides.

### Story 1.9: Deactivate or Delete User

As an Administrator,
I want to deactivate or delete a user,
So that someone who's left immediately loses access.

**Acceptance Criteria:**

**Given** a user has a live session
**When** I deactivate their account
**Then** their session token is rejected on their very next request, not just at next login
**And** deactivating or deleting the last remaining active Administrator account is refused — at least two active Administrator accounts must always exist.

### Story 1.10: Immutable Audit Log (write path)

As the system,
I want every login, failed login, and user-account change recorded permanently,
So that Rocell has a trustworthy access record.

**Acceptance Criteria:**

**Given** any login, failed login, or user create/edit/deactivate/delete occurs
**When** it completes
**Then** an audit entry is written recording who, what, when, and source IP
**And** no update or delete path against that entry exists anywhere — enforced at the database-role level, not just application code — and `source_ip` is captured only from the trusted reverse-proxy header, never a raw client-supplied one.

### Story 1.11: View Audit Log

As an Administrator,
I want to view the audit log within the app,
So that I can review access history without needing database access.

**Acceptance Criteria:**

**Given** I am an authenticated Administrator
**When** I open the audit log
**Then** entries appear in chronological order with who/what/when/source IP
**And** no edit or delete control exists anywhere in that view.

## Epic 2: Catalogue Management

Administrators can build and maintain the tile Catalogue directly — adding, editing, removing, and bulk-loading Products and Reference Images — with changes searchable immediately and no developer involvement.

**UI contract:** build against `DESIGN.md` + `EXPERIENCE.md` (ux-rcl_camera_app-2026-09-08); invoke the `ui-ux-pro-max` skill and run its pre-delivery checklist before calling any UI story here done. Covers UX-DR14 plus the cross-cutting UX-DR16–19.

**Story-shaping note:** FR-19 (automatic re-index) has no independent user action of its own — it's a property of every other operation in this epic — so it's folded as an acceptance criterion into Stories 2.1–2.4 rather than given its own story.

**POC-informed additions (architecture AD-13, AD-15, AD-17):** every Reference Image now produces up to 16 embeddings, not one, and a served reference image is a pre-generated capped derivative, never the original file. Both are implementation mechanics of "add/edit a Reference Image," not separate stories — folded into 2.1/2.2's acceptance criteria below.

### Story 2.1: Add Product

As an Administrator,
I want to add a new Product with a code and one or more reference images,
So that it becomes identifiable without developer involvement.

**Acceptance Criteria:**

**Given** I am an authenticated Administrator
**When** I submit a product code and upload/capture one or more reference images
**Then** the Product is created and every image passes through content validation, re-encoding, EXIF-stripping, and color management (any embedded ICC profile transformed to sRGB at relative colorimetric intent) before storage — never trusted by file extension, and never naively RGB-converted
**And** each Reference Image generates its full set of embeddings (rotations + augmented crops, per the architecture spine) and a pre-generated, capped-size derivative for display — never served from the original asset
**And** the Product is searchable and returned as a Candidate for a Scan submitted later in the same session, with no manual re-indexing step.

### Story 2.2: Edit Product

As an Administrator,
I want to change a Product's code and add, replace, or remove its Reference Images,
So that catalogue entries stay accurate.

**Acceptance Criteria:**

**Given** I am an authenticated Administrator
**When** I edit a Product's code or Reference Images
**Then** the change is reflected immediately with no manual re-index, and a newly added Reference Image gets the same color management, embedding generation, and derivative generation as Story 2.1
**And** a removed Reference Image is never returned as a Candidate for any Scan submitted after the edit, even if it appeared before, and its embeddings are removed with it.

### Story 2.3: Remove Product

As an Administrator,
I want to remove a Product from the Catalogue,
So that discontinued ranges stop appearing as matches.

**Acceptance Criteria:**

**Given** I am an authenticated Administrator
**When** I remove a Product
**Then** it is hard-deleted from the embedding index — not soft-flagged
**And** it never appears as a Candidate for any Scan submitted afterward, regardless of visual similarity.

### Story 2.4: Bulk Upload

As an Administrator,
I want to bulk-load Products via an image set plus a spreadsheet of codes,
So that I can populate or extend the catalogue at scale.

**Acceptance Criteria:**

**Given** I am an authenticated Administrator
**When** I submit a bulk upload of N valid product/image pairs
**Then** all N become individually searchable, with a per-row success/failure report for any that fail validation
**And** every image in the batch passes through the same content-validation/re-encode/EXIF-strip/color-management path as a single add — no shortcut for bulk
**And** a zero-byte or unreadable file in the batch is flagged in the per-row report as a failure, never silently indexed as a garbage embedding
**And** a row with no recoverable design name or face number is not treated as an error — it's indexed with an explicit unknown marker and flagged in the report for follow-up, since real catalogue data contains both (per the architecture spine's POC-informed data-shape notes).

### Story 2.5: Catalogue Search

As an Administrator,
I want to search and filter the Catalogue by product code,
So that I can find an entry quickly.

**Acceptance Criteria:**

**Given** I am an authenticated Administrator
**When** I search by a partial or full product code
**Then** all Products whose Code contains it are returned, not only exact matches.

## Epic 3: Tile Scanning & Identification

Staff can photograph an unidentified tile, crop it to the tile face, and get up to three visually-verifiable candidate matches in seconds — with the scanning capability itself defended against abuse.

**UI contract:** build against `DESIGN.md` + `EXPERIENCE.md` (ux-rcl_camera_app-2026-09-08) — this epic owns the product's hero surfaces, and [`mockups/key-scan.html`](ux-designs/ux-rcl_camera_app-2026-09-08/mockups/key-scan.html), [`key-crop.html`](ux-designs/ux-rcl_camera_app-2026-09-08/mockups/key-crop.html) and [`key-results.html`](ux-designs/ux-rcl_camera_app-2026-09-08/mockups/key-results.html) render three of them (illustrative; the spines win on conflict). Invoke the `ui-ux-pro-max` skill and run its pre-delivery checklist before calling any UI story here done. Covers UX-DR6, 9, 10, 11 plus the cross-cutting UX-DR16–19.

**POC-informed additions (architecture AD-13, AD-14, AD-15, AD-16):** matching now searches multiple embeddings per Reference Image and takes the best score (max-pool), the index refuses to search a stale generation, a Scan's own color profile is corrected the same way a Reference Image's is, and inference is serialized server-side — all implementation mechanics of Story 3.4's "matching completes," not new user-facing stories.

### Story 3.1: Capture or Upload a Scan

As a Staff or Administrator,
I want to capture a live photo with an on-screen framing guide or upload an existing photo,
So that I have something to submit for identification.

**Acceptance Criteria:**

**Given** I am authenticated
**When** I use the live camera
**Then** an on-screen framing guide is visible to help me fill the frame with the tile face
**And** uploading an existing photo produces an equivalent submission to a live capture — both proceed to the crop step (Story 3.2).

**Note (not yet an AC):** white balance is the single largest measured accuracy lever (ahead of crop, perspective, blur, and JPEG quality) — a future iteration of the framing guide should consider explicit white-balance capture guidance. No specific mechanism is validated yet, so nothing is committed here; revisit after the Phase 2 pilot.

### Story 3.2: Crop Before Submit

As a Staff or Administrator,
I want to crop my photo down to just the tile face before it's submitted,
So that background clutter doesn't affect the match.

**Acceptance Criteria:**

**Given** I've captured or uploaded a photo
**When** I'm shown the crop step
**Then** I can adjust a free-form crop selection over the image, and confirming it is required before submission proceeds
**And** the client sends the full, already-downscaled image plus a normalized 0–1 crop rectangle — never a pre-cropped image or absolute pixel coordinates — with the crop itself executed once, server-side.

### Story 3.3: Capture Quality Guidance

As a Staff or Administrator,
I want to be warned and asked to retake a blurry or poorly-framed photo,
So that I don't waste a submission on an image that can't match well.

**Acceptance Criteria:**

**Given** I've confirmed a crop (Story 3.2)
**When** the cropped region is materially blurry or poorly framed
**Then** I'm prompted to retake it before matching proceeds
**And** this check runs on the cropped region only, never the pre-crop full frame.

### Story 3.4: Ranked Candidate Results with Images

As a Staff or Administrator,
I want to see up to three ranked candidate matches with images after submitting a Scan,
So that I can visually confirm the right product instead of trusting a bare code.

**Acceptance Criteria:**

**Given** I submit a Scan that passes quality guidance
**When** matching completes
**Then** I see up to three Candidates ranked by visual similarity, each with its reference image, code, size, and design
**And** the result is never a single "confidence-gated" answer, Candidates are not deduplicated by Product, and crop-confirmation-to-result stays under 3 seconds.

**Note (not yet an AC):** a working POC found that displaying more than 3 candidates (with the top 3 still emphasized) is safe and doesn't weaken the "never one" rule — its accuracy metric and this contract's "up to three" both stay pinned at 3 regardless. Whether production should show more than 3 is an open product decision, not made here; if taken up later, keep the displayed count and the accuracy metric's count explicitly separate rather than collapsing them into one number.

### Story 3.5: Scan History

As a Staff or Administrator,
I want to view my own past scans,
So that I can refer back to a result I got earlier.

**Acceptance Criteria:**

**Given** I am signed in
**When** I open my scan history
**Then** I see my own past scans, each showing the result exactly as it was at scan time
**And** I see only my own scans, never another user's.

### Story 3.6: Scan Rate Limiting

As the system,
I want to throttle scan submissions per user,
So that a compromised or misused account can't be used to scrape the catalogue at volume.

**Acceptance Criteria:**

**Given** a user submits scans above a defined threshold within a bounded window
**When** the threshold is crossed
**Then** further submissions are throttled or blocked
**And** this is enforced via a single atomic increment-and-check operation in the database, never a stale read-then-write a concurrent burst could outrun.

### Story 3.7: Anomaly Flagging

As an Administrator,
I want unusual login times, locations, or scanning volume flagged for review,
So that I can catch misuse a hard rate limit alone wouldn't stop.

**Acceptance Criteria:**

**Given** a login or scanning pattern falls outside a user's established baseline
**When** it's detected
**Then** a flag is raised for Administrator review, distinct from and in addition to Story 3.6's hard throttle.
