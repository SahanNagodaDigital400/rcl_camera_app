# Functional Requirements

Granular, testable detail underneath each capability in `SPEC.md`. IDs are stable (carried over from the PRD) — cite them, don't renumber.

## CAP-1 — Auth & Session Management

**FR-1 Admin-provisioned login only.** A user authenticates with email/password only if an Administrator created the account. No registration endpoint or UI exists anywhere in the product; social login is not offered.

**FR-2 Forced password change on first login.** A temporary, admin-issued credential can reach only the password-change screen until replaced. Any navigation away redirects back. An unclaimed temporary credential stops working after 72 hours and must be reissued.

**FR-3 Session persistence and expiry.** A signed-in user stays authenticated through a shift (12h inactivity / 7-day absolute expiry). No re-auth prompt within the inactivity window; a session past absolute expiry is rejected regardless of activity. The session token is never accessible to page script or client-side storage — cookie only. It's never accessible in raw form even in Postgres — stored hashed.

**FR-4 Login rate limiting.** Progressive delay from the 6th failed attempt; the 10th cumulative failed attempt locks the account (visible to Administrators), blocking further attempts.

**FR-5 Self-service password reset.** A signed-in user can change their own password at any time. No reset emails — a locked-out or forgotten-password user goes through an Administrator.

## CAP-2 — Tile Scanning & Identification

**FR-6 Capture or upload a scan.** Live camera capture (with on-screen framing guide) or photo upload, as the input to a Scan. Both paths produce an equivalent submission and proceed to the crop step (FR-24).

**FR-7 Ranked candidate results with images.** Up to three Candidates, ranked by visual similarity, each with Reference Image, Code, Size, Design. Never fewer than available, never a single "confidence-gated" answer. Candidates are not deduplicated by Product — different Faces of the same Product may both appear.

**FR-8 Scan history.** A user views their own past scans, each with the result as shown at scan time (denormalized snapshot — see the architecture spine AD-10; unaffected by a later Reference Image deletion).

**FR-9 Capture quality guidance.** A materially blurry or poorly-framed *cropped region* (runs after FR-24, per architecture spine AD-12) triggers a retake prompt before matching proceeds. Exact threshold: open question, see `SPEC.md`.

**FR-24 Crop before submit.** After capture/upload, the user adjusts a crop selection to isolate the tile face before submission. The submitted Scan is the cropped region, never the original full frame. Crop execution is server-side (architecture spine AD-11) — the client sends the full (already downscaled) image plus a normalized 0–1 crop rectangle, never a pre-cropped image or absolute pixel coordinates. Confirming the crop is currently assumed mandatory, free-form (no fixed aspect ratio), pre-filled to a best-guess selection — all three assumptions are open questions, see `SPEC.md`.

*Out of scope:* identifying tiles already installed (grouted, angled, partially obscured).

## CAP-3 — Admin User Management

**FR-10 User list.** All users with status (active/deactivated) and last login; a deactivated user is visually distinct, no separate screen needed.

**FR-11 Create user.** Name, email, role, initial (temporary) password. No email sent — Administrator communicates it manually. User can authenticate immediately, gated by FR-2.

**FR-12 Edit user.** Name, email, or role. A role change takes effect on the user's *live* session, not only at next authentication.

**FR-13 Deactivate or delete user.** Revokes live sessions immediately, not just future logins — a session token valid before deactivation is rejected on the very next request. Deactivating/deleting the last remaining active Administrator is refused.

## CAP-4 — Admin Catalogue Management

**FR-14 Add product.** Code + one or more Reference Images. Matchable against new Scans immediately, no developer/re-import — a Product added mid-session is a Candidate for a Scan submitted later that same session.

**FR-15 Edit product.** Change code, add/replace/remove Reference Images. A removed image is never returned as a Candidate after the edit, even if it was before.

**FR-16 Remove product.** Removed from the Catalogue; never returned as a Candidate after removal, regardless of visual similarity (hard delete, architecture spine AD-5 — no soft-delete filter to forget).

**FR-17 Bulk upload.** Image set + spreadsheet of codes, for initial load and large new ranges. Per-row success/failure report; all valid pairs individually searchable.

**FR-18 Catalogue search.** Search/filter by product code; partial matches included, not just exact.

**FR-19 Automatic re-index.** Any Catalogue change is reflected in match results with no separate manual re-indexing step. Admin-added reference images below a quality threshold should be flagged for re-shoot (mirrors FR-9) — threshold is an open question, see `SPEC.md`. No equivalent crop step for admin uploads (resolved, not deferred — see `SPEC.md` Non-goals).

## CAP-5 — Audit Log & Anomaly/Rate-Limit Defense

**FR-20 Immutable audit log.** Every login/failed login, user account change, and Catalogue change, with who/what/when/source IP. No update or delete path exists, from application code or the admin UI, or at the database-role level.

**FR-21 Audit log visibility.** Administrators view it in-app; no edit/delete control anywhere in that UI.

**FR-22 Anomaly flagging.** Unusual login times/locations or scanning volume consistent with scraping — flagged for admin review. Baseline/window/multiplier: open question, see `SPEC.md`.

**FR-23 Scan rate limiting.** Per-user throttle on scan submissions, independent of whether the pattern also triggers FR-22. Threshold: open question, see `SPEC.md`. Counters are mutated atomically (architecture spine AD-8) — never a stale read-then-write that a concurrent burst could outrun.
