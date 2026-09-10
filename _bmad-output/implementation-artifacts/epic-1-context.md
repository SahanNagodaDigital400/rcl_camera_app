# Epic 1 Context: Access & Account Management

<!-- Generated from planning artifacts. Regenerate with compile-epic-context if planning docs change. -->

## Goal

Staff and Administrators can be provisioned with secure, admin-controlled accounts — no self-registration or SSO anywhere in the product (Rocell has no existing identity provider) — and every account and access event is immutably logged and visible to Administrators. This is the foundation epic: it also delivers the monorepo scaffold and design token layer every later UI story builds on, and the session/authz mechanics every later endpoint (catalogue, scanning) depends on. The app is a gatekeeper to Rocell's full catalogue and staff account list and must survive an independent penetration test before general rollout, so this epic's security behavior is not cosmetic.

## Stories

- Story 1.1: Project Scaffold & Design Token Foundation
- Story 1.2: User Schema & Seeded Administrator
- Story 1.3: Admin-Provisioned Login
- Story 1.4: Forced Password Change on First Login
- Story 1.5: Session Persistence & Expiry
- Story 1.6: Login Rate Limiting
- Story 1.7: Self-Service Password Reset
- Story 1.8: Create User Account
- Story 1.9: View User List
- Story 1.10: Edit User
- Story 1.11: Deactivate or Delete User
- Story 1.12: Immutable Audit Log (write path)
- Story 1.13: View Audit Log

## Requirements & Constraints

- Accounts exist only when an Administrator creates them — no registration endpoint, no social login, no SSO/IdP integration (confirmed not applicable, not deferred).
- A temporary, admin-issued credential can reach only the password-change screen until replaced; any navigation attempt elsewhere redirects back; an unclaimed temporary credential expires after 72 hours and must be reissued by an Administrator.
- Sessions persist 12h on inactivity / 7 days absolute; the token lives only in an HTTP-only, Secure, SameSite=Strict cookie, stored hashed at rest — never in `localStorage`/readable by page script.
- Login lockout: progressive delay from the 6th consecutive failed attempt; the 10th cumulative failed attempt locks the account, visible to Administrators on that user's status.
- Signed-in users can change their own password anytime; there is no reset-email flow anywhere — a locked-out or forgotten-password user must go through an Administrator.
- Administrators create/edit/deactivate/delete users (name, email, role, temp password); no in-app email of credentials — communicated manually. A role or deactivation change takes effect on the user's very next request, not next login.
- At least two active Administrator accounts must always exist — deactivating/deleting the last one is refused.
- Every login, failed login, and user create/edit/deactivate/delete is written to an immutable audit log (who/what/when/source IP); no update or delete path exists anywhere for it; `source_ip` comes only from the trusted reverse-proxy header, never a raw client-supplied one. Administrators can view it in-app, read-only.
- Roles: **Staff** — scan, view results, view own scan history. **Administrator** — Staff capabilities plus user management and Catalogue management.
- Every privileged action is authorized server-side independent of what the UI hides or shows; no credential/secret is ever stored or transmitted in recoverable form (Argon2id hashing).
- General staff rollout is gated on an independent penetration test passing — this epic's auth/session/audit behavior is what that test exercises most directly.

## Technical Decisions

- This epic stands up the monorepo by hand (no scaffolding generator exists for this stack): `apps/web`, `apps/api`, `shared/vision`, `shared/schema`, `infra`, `scripts/ingest`. `make lint` and `make test` must exist and pass against the empty skeleton so every later story starts from a green baseline.
- Sessions are Postgres rows (not Redis), validated through one shared session-lookup function — never a bespoke per-route check. That lookup re-reads role and active status from Postgres on every request (never cached at login), which is what makes a role edit or deactivation take effect on the very next request.
- Failed-login counts and lockout state are Postgres rows mutated through a single atomic increment-and-check operation (e.g. one `UPDATE ... RETURNING`) — never in-process memory, never a separate read then write.
- Audit-log immutability is enforced at the database-role level: the application's DB role has INSERT and SELECT on the audit table only, no UPDATE/DELETE grant — holds even against a bug, not just a reviewed PR. A bad entry is corrected by inserting a new corrective entry, never by mutation.
- `apps/web` holds no database or storage credential; every read/write goes through an authenticated `apps/api` endpoint.
- ERD fields this epic's schema must carry: `User` (role, active, must_change_password, temp_credential_expires_at), `Session` (token_hash, issued_at, expires_at), `AuditLogEntry` (action, source_ip, created_at).
- Exactly one Administrator is seeded by a migration — not application code, not any UI — the only account in the product's lifetime that exists without an Administrator having created it; seeded already in `must_change_password` state; re-running migrations must never produce a second seeded Administrator.
- Naming/formats: PRD glossary terms used verbatim as PascalCase entity/type names (`User`, `Session`, `AuditLogEntry`) — no synonyms. IDs are UUIDv4, timestamps ISO 8601 UTC, API errors shaped `{ "error": { "code": string, "message": string } }`.
- Design tokens, fonts, and icon set (Story 1.1) are the single styling source for every later story: 11 color tokens / 6 type roles / 4 radii + `full` / 10-step spacing scale / navy-tinted elevation, no raw hex values in components; Plus Jakarta Sans (400–800) + JetBrains Mono for the `code` role; Phosphor icons at `regular` weight only.
- Stack: React 19.2.x / Vite 8.0.x / TypeScript 7.0.x (`apps/web`); FastAPI 0.141.x / Python 3.12+ (`apps/api`); PostgreSQL 18.x (pgvector's 18-compatibility is unconfirmed as of authoring — verify at build time).

## UX & Interaction Patterns

- Build against `DESIGN.md` (visual spec) + `EXPERIENCE.md` (IA/behavior/state/accessibility) — these win on any conflict with a mockup. Invoke the `ui-ux-pro-max` skill and run its pre-delivery checklist before calling any UI story in this epic done.
- Components this epic introduces: `button-primary` (accent fill, navy foreground — never white; white-on-orange fails contrast at 2.63:1), `button-secondary`, `button-destructive`; `app-bar` (navy fill, white content, accent stripe, present on every authenticated screen); `force-password-change-form` (single field, no nav chrome, destructive-colored inline errors naming the failed rule); `save-indicator` (muted at rest → navy on "Saved.", inline near its trigger, never a toast, never orange); `confirmation-dialog` (sheet over scrim, names the object and consequence, destructive actions styled `button-destructive`) for deactivate/delete; `badge-role-admin`/`badge-role-staff`/`badge-status-deactivated` (display-only, never interactive); `data-table-row` and `audit-log-row` (dense desktop table, hairline separators, no card wrapper).
- Accessibility floor: ≥44×44px touch targets everywhere, visible keyboard focus states on admin surfaces, no color-only signaling on destructive actions (label + icon, not red alone).
- Responsive: bottom tab bar on mobile (Admin sections behind a "More" tab), sidebar nav at desktop/tablet; no drawer on mobile; modal/sheet depth never exceeds one level.
- Microcopy: plain factual errors, no exclamation marks, no gamified language.
- State patterns this epic's stories are responsible for (of `EXPERIENCE.md`'s full set): session-expired mid-flow, deactivated-account login, login lockout, weak/mismatched password, and live role-change mid-session.

## Cross-Story Dependencies

- 1.1 (scaffold + tokens) must land first — every later UI story consumes its token/font/icon layer.
- 1.2 (schema + seeded Administrator) precedes 1.3 (login) — there is nothing to authenticate against otherwise; the seeded account's `must_change_password` state is what routes even the very first sign-in through 1.4.
- 1.8 (Create User) depends on 1.4 existing, since every newly created account is gated through the forced-change screen the same way.
- 1.10 (Edit User role change) and 1.11 (Deactivate/Delete) both depend on the live session-lookup behavior established alongside 1.5 — it's what makes their effect immediate rather than next-login-only.
- With only one Administrator seeded by 1.2, 1.11's last-active-Administrator guard will correctly block deactivating it until a second Administrator is created via 1.8 — expected behavior, not a defect to fix.
- 1.12 (audit log write path) is a dependency of 1.3, 1.6, 1.8, 1.10, and 1.11 — each of those actions must produce an audit entry; 1.13 (view audit log) has nothing to render until 1.12 exists.
- Epics 2 and 3 both build on this epic's session/authz foundation (every endpoint they add requires it) and extend this epic's audit-log write path for catalogue and scan events respectively.
