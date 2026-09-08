---
status: draft
created: 2026-09-08
updated: 2026-09-08
name: Rocell Tile Scanner
sources:
  - _bmad-output/planning-artifacts/prds/prd-rcl_camera_app-2026-08-25/prd.md
  - _bmad-output/planning-artifacts/architecture/architecture-rcl_camera_app-2026-08-30/ARCHITECTURE-SPINE.md
  - _bmad-output/planning-artifacts/epics.md
---

# Rocell Tile Scanner — Experience Spine

## Foundation

Multi-surface PWA, installable to the home screen. Mobile-first for the Staff scan flow — camera access requires a phone in hand. Responsive up to desktop/tablet for Admin screens (user management, catalogue management, audit log), which are dense and benefit from more horizontal space than a phone gives. Online-only; no offline mode (PRD Non-Goal). No native UI kit is inherited — `DESIGN.md` is the visual identity reference; this spine is the behavior.

Two roles shape navigation, not just permissions: **Staff** sees only Scan and Scan History. **Administrator** sees those plus every admin surface. The nav itself is role-conditional, not a single menu with disabled items — a Staff user should never see an Admin entry they can't use.

## Information Architecture

| Surface | Reached from | Purpose | Role |
|---|---|---|---|
| Login | App open, unauthenticated | Email/password entry | All |
| Force Password Change | Gates every screen on a temporary credential | Set a real password before anything else | All (first login only) |
| Scan | Nav (default landing for Staff) | Capture/upload entry point | Staff, Admin |
| Crop | After capture/upload | Isolate the tile face before submission | Staff, Admin |
| Results | After crop confirm + processing | Up to 3 ranked Candidates | Staff, Admin |
| Scan History | Nav | Past scans, own only | Staff, Admin |
| Account Settings | Nav (avatar/profile entry) | Change own password (FR-5) | Staff, Admin |
| User List | Nav (Admin) | All accounts, status, last login | Admin |
| Create/Edit User | User List row / "+ Add User" | Account fields, role | Admin |
| Catalogue | Nav (Admin) | Search/browse Products | Admin |
| Add/Edit Product | Catalogue row / "+ Add Product" | Code + Reference Images | Admin |
| Bulk Upload | Catalogue | Image set + spreadsheet, per-row report | Admin |
| Audit Log | Nav (Admin) | Chronological account/catalogue history, with a Flagged filter surfacing FR-22 anomaly reviews | Admin |

Bottom tab bar on mobile (Scan / History, plus Admin sections collapsed into a "More" tab for Admins — a phone-width nav can't hold 6 top-level items). Sidebar nav on desktop/tablet widths, all sections visible flat. No drawer on mobile; the tab bar is the whole nav. Modal/sheet stacks one level deep — Crop is a full-screen sheet over Scan, never a sheet-over-a-sheet.

→ Composition reference: mockups produced at Finalize. Spine wins on conflict.

## Voice and Tone

Microcopy. Brand voice and aesthetic posture live in `DESIGN.md`.

| Do | Don't |
|---|---|
| "Best match" | "98% confidence" — the PRD explicitly rejects a calibrated-confidence framing (no absolute threshold means the number would be misleading) |
| "Fill the frame with the tile face." | "Let's find your tile! 📸" |
| "No confident match — retake, or ask a colleague." | "Oops! We couldn't find anything 😕" |
| "This photo's a little blurry — try again." | "Error: low quality image" |
| "Deactivate this account?" + consequence stated plainly | "Are you sure?" with no context |
| Short, factual sentences | Exclamation marks, encouragement, gamified language |

## Component Patterns

Behavioral. Visual specs live in `DESIGN.md.Components`.

| Component | Use | Behavioral rules |
|---|---|---|
| Force password change form | Force Password Change | The only thing on screen — no nav, no way to dismiss it. Validates against the same password policy as any other password field; a rejected password states which rule failed. |
| Role badge / Status badge | User List rows | Display-only — no tap target, no interaction. Never used as a button. |
| Framing guide overlay | Scan (live capture) | Fixed guide rectangle over the camera viewfinder; doesn't block the shutter control. |
| Crop selector | Crop | Free-form rectangle, drag corners/edges to resize, drag body to move. Pre-filled to a best-guess selection. Confirm required before proceeding. |
| Candidate card | Results | Reference image, Code (`{typography.code}`), Size · Design line. Top card uses `candidate-card-best-match` styling; tapping any card opens its reference image full-screen. |
| Retake prompt | After Crop confirm, before Results | Inline message + a single "Retake" action — never a blocking modal the user has to dismiss twice. Fires only on the cropped region (AD-12) — a blurry background outside the crop never triggers it. |
| Data table row | User List, Catalogue | Dense (`{spacing.2}`–`{spacing.3}`). Row click opens detail; destructive actions live in a row-end menu, never a bare icon with no label. |
| Confirmation dialog | Any destructive action | States the object and the consequence by name ("Deactivate Kasun Perera? He will be signed out immediately.") — never a bare "Are you sure?" |
| Per-row upload report | Bulk Upload | Success/failure/flagged-for-review per row, scrollable list, not a single pass/fail summary. |
| Save indicator | Any form | Cycles `Saving…` → `Saved.`, inline near the action that triggered it, not a corner toast. |
| Audit log row | Audit Log | Read-only, always — no edit or delete affordance anywhere in this surface's UI, at any role (FR-21). The one table in the product with zero row-end actions. |
| Flagged-activity row | Audit Log → Flagged filter | Same read-only row treatment as any audit entry, distinguished only by a visual flag indicator — reviewing a flag is not itself an action with a workflow (no "resolve"/"dismiss" state exists in FR-22); an Administrator investigates and acts elsewhere (e.g. deactivating a user) if warranted. |

## State Patterns

| State | Surface | Treatment |
|---|---|---|
| Camera permission not yet granted | Scan | Explain why (to scan a tile) before the browser prompt fires; fallback to "Choose a photo" always visible, never gated behind granting camera access. |
| Processing | Results (pending) | Lightweight spinner, not a skeleton — the budget is under 3 seconds, too short for a skeleton to earn its complexity. |
| No confident match | Results | Show whatever Candidates exist (even if unconvincing) plus the retake prompt — never an empty state with nothing to look at. |
| Submission/matching failure | Results | Distinct from "no confident match" — this is the request itself failing (network, server, timeout), not a low-quality match. Plain message + a single "Try again" action; the crop and captured image are preserved so the user isn't sent back to Scan to start over. |
| Empty history | Scan History | "No scans yet." — same register as the empty catalogue-search state, no illustration or onboarding tour. |
| Weak/mismatched password | Force Password Change | Inline error naming which rule failed (length, reuse of the temporary password) — never a generic "invalid password." |
| Password set successfully | Force Password Change | Immediate transition to Scan (or the surface the user was headed to) — no separate "success" screen to click through. |
| Scan rate-limited | Scan | Plain message that submissions are temporarily paused; no countdown timer (the exact threshold is intentionally unset per PRD OQ-13). |
| Session expired mid-flow | Any | Redirect to Login preserving no in-progress Scan state (a Scan is fast enough to redo) but never silently dropping an in-progress admin form — warn before navigating away from unsaved catalogue/user edits. |
| Empty catalogue search | Catalogue | "No products match — try a different code." No suggested alternatives (nothing to suggest from). |
| Deactivated account login attempt | Login | Same generic rejection as a wrong password — never confirm the account exists or its status (AGENTS.md server-side-authz spirit extends to not leaking account state). |
| Login lockout (10th failed attempt) | Login | A different message from a plain wrong-password rejection — tells the user the account is temporarily locked, without a countdown (progressive delay already started at attempt 6; no need to restate the mechanic to the person triggering it). |
| Bulk upload in progress | Bulk Upload | Per-row status updates as they complete, not a single spinner until the whole batch finishes. |
| Role changed while signed in | Any (mid-session) | Takes effect on the very next request (FR-12/AD-3) — the nav updates to match the new role on that next request/navigation, with no toast or interruption. If a permission is revoked mid-action (e.g. an Admin demoted while on an Admin screen), the next navigation redirects to the highest surface the new role can reach, not a dead screen. |

## Interaction Primitives

- Tap to capture; tap to open the file picker for upload. Both lead to the same Crop step.
- Drag to adjust crop — corners resize, body moves. No pinch-zoom gesture layered on top (one interaction model per step).
- Tap a Candidate to view its reference image full-screen (this is *the* verification moment — staff confirm the match by eye).
- Every destructive action requires an explicit confirmation step naming the object — never a single tap with no undo path.
- **Banned:** infinite scroll novelty, gamified elements (badges, streaks, point counts — this is an internal tool with no engagement problem to solve), auto-advancing carousels, decorative animation on open.

## Accessibility Floor

Behavioral. Visual contrast lives in `DESIGN.md`.

- Tap targets ≥ 44×44px on every mobile surface, including candidate cards and crop-handle grab areas.
- Every interactive element has a visible focus state and a keyboard path — the admin surfaces are desktop-first and will get real keyboard use.
- Destructive actions are never color-only: the destructive button carries a label ("Deactivate," "Delete") and, where space allows, an icon — red alone isn't the signal.
- Camera permission denial has a first-class fallback (upload), never a dead end.
- Contrast verified against `DESIGN.md`'s exact tokens (WCAG relative-luminance formula): navy-on-cream 14.93:1, white-on-destructive-red 4.87:1, muted-text-on-background 4.65:1 all pass. White-on-accent-orange measured 2.63:1 and **failed** — this is why the accent button's foreground is navy (5.94:1), not white; see `DESIGN.md` Colors for the full table.

## Key Flows

### Flow 1 — Kasun identifies a tile mid-sale (mirrors PRD UJ-1)

1. Kasun opens the installed PWA — already authenticated, session persisted through his shift.
2. Scan is the default landing surface. He taps the capture control.
3. The framing guide helps him fill the frame; he takes the photo.
4. Crop opens, pre-filled to a best-guess selection; he adjusts it slightly and confirms.
5. The cropped region passes quality guidance (FR-9/AD-12) — sharp enough, well-framed — so no retake prompt fires.
6. A brief processing spinner (under 3 seconds).
7. **Climax:** Results shows three candidates; the top card's reference image visually matches the tile in his hand within a second of looking at it.
8. He taps the top card to confirm the reference image full-screen, then reads the Code to the customer.

Failure: none of the three look right → he taps Retake, recaptures with better framing, or falls back to asking a colleague.

### Flow 2 — Nadeesha adds a new tile range (mirrors PRD UJ-2)

1. Nadeesha opens Catalogue, taps "+ Add Product."
2. Enters the product code, uploads reference images.
3. Saves — sees a `Saved.` confirmation inline.
4. She switches to Scan and photographs the physical sample.
5. **Climax:** the just-added product appears as a Candidate, same session — no ticket filed with engineering.

Edge case: an uploaded reference image is flagged below the quality threshold — she sees the flag on the product detail screen, not buried in a report she'd have to go looking for.

### Flow 3 — Ruwan deactivates a departing staff member (mirrors PRD UJ-3)

1. Ruwan opens User List, finds the account, opens the row-end menu.
2. Taps "Deactivate."
3. Confirmation dialog names the person and states the consequence: "Deactivate Kasun Perera? His session ends immediately, even if he's still logged in."
4. Confirms.
5. **Climax:** the row's status updates to Deactivated inline — no page reload needed to see it took effect.

Edge case: the account Ruwan is trying to deactivate is the last remaining active Administrator — the confirmation dialog itself is replaced by a refusal message stating why (FR-13), and no destructive action fires. Ruwan must activate or create a second Administrator first.

## Responsive & Platform

- **Mobile (Scan, Crop, Results, History):** single column, full-bleed camera/crop views, bottom tab nav, generous spacing (`DESIGN.md` mobile spacing tier).
- **Desktop/tablet (Admin surfaces):** sidebar nav replaces the tab bar at the same breakpoint the design system's card/table density shift kicks in; multi-column layout permitted for user/catalogue tables, denser spacing.
- **Both:** Scan itself is technically reachable from a desktop browser (an Administrator could scan from a laptop with a webcam) — the flow doesn't hard-block that, but it isn't the designed-for case and isn't optimized for it.
