---
title: Rocell Tile Identification App
status: draft
created: 2026-08-25
updated: 2026-08-25
---

# Product Brief: Rocell Tile Identification App

## Executive Summary

Rocell staff regularly encounter a tile with no known product code — an unlabelled showroom sample, a returned box, a leftover piece a customer brings in, something pulled from storage. Today, identifying it means flipping through the catalogue or finding a colleague who happens to remember. That's slow, error-prone, and it means catalogue knowledge lives in a few long-serving people's heads rather than being available to everyone on the floor.

This project delivers a browser-based PWA: a staff member points their phone at a tile, and the app returns the matching product code — with a reference photo to confirm it's right. Accounts are admin-provisioned only; there is no public access.

The matching approach is image-embedding similarity search rather than a trained classifier, chosen specifically because the catalogue is large (2,000+ codes) and changes regularly — adding a new tile means adding one entry to the index in seconds, not retraining a model.

## The Problem

- Staff can't identify an unlabelled tile without manual catalogue search or asking someone who remembers.
- Misidentification leads to wrong orders and returns.
- Catalogue knowledge is concentrated in long-serving staff, not accessible to junior staff.
- As new tile ranges launch, the burden of "knowing the catalogue by memory" only grows.

## The Solution

A staff member opens the installed PWA, logs in with an admin-issued account, and either captures a live photo (with an on-screen framing guide) or uploads an existing one. The image is sent server-side, converted to an embedding, and compared against a vector index of reference images. The app returns the **top 3 candidate matches**, each shown with its reference image, its file-name/code, and its folder-derived size and design — so the user can visually confirm a match rather than trust an unverifiable code. Scans are logged to the user's history.

Administrators manage the system from within the app: creating and deactivating staff accounts, and — critically — adding, editing, and bulk-uploading catalogue entries directly, so a new tile range becomes identifiable in the same session it's added, with no developer involvement or data re-import.

## Why This Approach

**Embedding search over a trained classifier.** A classifier needs retraining every time the catalogue changes; with 2,000+ codes and new ranges arriving regularly, that's a recurring cost this design avoids entirely. Embedding search makes adding a product a database insert, not a retraining cycle.

**Top 3 with images, not one bare code.** This is a direct response to a hard limit in the data, not a hedge: some products are visually identical from a photo alone (the same design sold across multiple sizes, or a glossy/matte pair of the same finish). No model can resolve that ambiguity from pixels — a person holding the tile can, instantly, if shown a picture. A staff member can verify a photo they don't recognize in under a second; they can't verify a code the same way. This also means the "just return a code" framing in the original ask undersells what actually makes the tool usable.

## Who This Serves

| Role | Who | Capabilities |
|---|---|---|
| **Staff user** | Showroom, warehouse, and sales staff | Log in, scan a tile, view identified candidates, view own scan history |
| **Administrator** | Nominated Rocell IT/operations staff | Everything staff can do, plus user account management and full catalogue management (add/edit/remove products, bulk upload, re-index) |

No self-registration or social login — accounts exist only when an administrator creates them.

## Scope

**In for v1:**
- Admin-provisioned email/password login, forced password change on first use, session persistence through a shift.
- Live camera capture or photo upload, framing guide, server-side matching, top-3 results with images.
- Per-user scan history.
- In-app admin tools: user management (add/edit/deactivate/delete, status, last login) and catalogue management (add/edit/remove products, bulk upload with a spreadsheet of codes, search/filter, automatic re-indexing).

**Out for v1:**
- Native iOS/Android apps; offline scanning.
- Identifying tiles already installed (grouted, angled, partially obscured).
- Any data beyond product code (price, stock, specs).
- Customer- or dealer-facing access.
- Automated invitation/reset emails (credentials are communicated by the admin manually).
- ERP/POS/inventory integration.

## Security & Trust Posture

This app grants access to Rocell's full product catalogue and staff account list, so security is a build requirement from day one, not a hardening pass at the end. The non-negotiables: passwords hashed with Argon2id, forced password change on first login (closes the window where an admin-chosen password sits readable in a chat thread), server-side authorization on every request regardless of what the UI hides, session tokens in HTTP-only cookies with defined expiry, uploaded files validated by content inspection (not extension) and stripped of EXIF data, and a full audit trail of logins, account changes, and catalogue modifications that admins can view but not edit. General staff rollout is gated on an independent penetration test.

The realistic threat here isn't external attack so much as **catalogue exfiltration** — a compromised or departing staff account used to scrape the product catalogue — and **credential sharing** via a shared "showroom" login, which would make the audit log meaningless. Both are addressed by individual accounts with visible last-login data, rate limiting, and a defined offboarding owner.

Full requirement detail (authentication, authorization, transport, input handling, audit, data retention, and threat notes) is in `addendum.md`.

## Key Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Visually identical products (same design, different size/finish) | High — may be unresolvable from an image alone | Top-3 results with images; user confirms |
| Reference images are studio assets; live queries are phone photos under showroom lighting | High — testing accuracy will overstate real-world accuracy | Supplement the index with phone-captured reference images |
| Sparse reference coverage (~2 images/product against ~9 manufactured faces) | High — a staff member may scan a face the system has never seen | Capture additional faces for high-variation, high-volume ranges before launch |
| Canonical images live in personal Gmail accounts, not a Rocell-owned Drive | High business-continuity risk | Migrate to a Rocell-owned Shared Drive before ingestion |
| Catalogue size/taxonomy uncertain (folder audit suggests hundreds of combinations, not 2,000+ SKUs) | Medium — affects both scope and accuracy targets | Reconcile the Drive against the master product list before estimating |

Full risk register (12 risks) is in `addendum.md`.

## Success Criteria

- **Top-1 accuracy** and **top-3 accuracy** (the latter reflects real-world usefulness) — numeric targets set after the pilot.
- **Time to result** under 3 seconds, capture to display.
- **Adoption**: proportion of showroom staff scanning at least weekly.
- **Fallback rate**: how often staff abandon a scan and revert to manual lookup.

## Suggested Phasing

0. **Dataset consolidation** — migrate images to a Rocell-owned Drive, audit coverage and naming, confirm code segment meanings. No longer a hard blocker on launch, but the prerequisite for a realistic estimate.
1. **Foundation** — auth, server-side authorization, audit logging, admin user/catalogue management, indexing pipeline.
2. **Scanning pilot** — camera capture and matching against a 150–200 product pilot index, internal accuracy testing.
3. **Full rollout** — full catalogue ingestion, scan history, tuning from pilot findings, staff training. **Gated on an independent penetration test.**
4. **Refinement** — improve accuracy from real scan data, backfill weak reference images, review misidentification reports.

## Open Questions

The biggest unknowns are about the source dataset, and they directly affect scope and estimate:

1. Does the Google Drive folder represent the full catalogue, or a subset? (Observed structure suggests hundreds of size+design combinations, not the 2,000+ SKUs previously assumed.)
2. What do the category folders (Cement, Earthen, Fashion, Mono Colour, Randomness, Speckled) actually contain — size folders, design folders, or loose images?
3. Can the canonical image set move to a Rocell-owned Shared Drive before ingestion starts?
4. What's the expected staff count, peak concurrency, and are there device constraints (company phones vs. personal devices)?
5. Is there an existing identity provider (Microsoft 365, Google Workspace) staff already use? SSO would remove the manual-password-distribution problem entirely — worth evaluating before building separate credentials.

Eleven further open questions (code segment meanings, colourway handling, retention policy, offboarding ownership, launch date/budget, and more) are in `addendum.md`.

## Vision

[ASSUMPTION] As the reference index matures and accuracy data comes in from real showroom use, the same matching capability is a natural fit for adjacent internal problems beyond showroom identification — warehouse stock checks, returns processing, training new staff on the catalogue — without material rework, since the core (embedding index + admin-managed catalogue) doesn't change, only who's using it and where. Confirm or strike this — the source material doesn't state a multi-year vision explicitly.
