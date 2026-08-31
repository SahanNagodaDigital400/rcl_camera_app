---
stepsCompleted: ["step-01-validate-prerequisites", "step-02-design-epics"]
inputDocuments:
  - _bmad-output/specs/spec-rcl_camera_app/SPEC.md
  - _bmad-output/specs/spec-rcl_camera_app/functional-requirements.md
  - _bmad-output/planning-artifacts/architecture/architecture-rcl_camera_app-2026-08-30/ARCHITECTURE-SPINE.md
  - _bmad-output/planning-artifacts/prds/prd-rcl_camera_app-2026-08-25/prd.md
---

# Rocell Tile Identification App - Epic Breakdown

## Overview

This document provides the complete epic and story breakdown for the Rocell Tile Identification App, decomposing the requirements from `SPEC.md` (primary, cross-checked against the raw PRD) and the architecture spine into implementable stories. No UX design contract exists (`bmad-ux` was not run) — flow shape comes from the PRD's User Journeys; UI detail is an assumption until/unless that skill runs.

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
- 12 binding architecture invariants (AD-1 through AD-12) govern implementation; the dev agent must read `ARCHITECTURE-SPINE.md` directly, not just this summary. Notably: `shared/vision`'s preprocessing/embedding is called identically by the live API and the batch ingest script, never forked (AD-1); crop executes server-side only, client sends the full downscaled image plus normalized coordinates, never a pre-cropped image (AD-11); sessions and rate-limit counters live in Postgres, not Redis (AD-3, AD-8); audit-log immutability is enforced at the DB-role level, not just app code (AD-4); scan history is a denormalized snapshot, never a live foreign key to Reference Image (AD-10).
- Five infrastructure decisions are Deferred with no answer yet: hosting/deployment provider & environments (dev/staging/prod)/CI-CD, S3-compatible object storage provider, secrets management approach, backup/DR strategy, monitoring/observability stack. These block real deployment work and should be resolved early in Epic 1, even though architecture didn't pin them.
- Phase 0 dataset consolidation — migrating reference images off personal Gmail accounts onto a Rocell-owned store — is a named prerequisite in both the brief and the architecture spine's rollout phasing. Likely its own epic or an early story, not incidental cleanup.

### UX Design Requirements

None. `bmad-ux` has not been run — no design contract exists. Story-level UI/interaction detail (exact crop-UI behavior, framing-guide presentation, admin screen layouts) will be reasonable assumptions grounded in the PRD's User Journeys until/unless that skill runs.

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
