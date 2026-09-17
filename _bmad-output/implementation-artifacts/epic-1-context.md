# Epic 1 Context: Access & Account Management

<!-- Generated from planning artifacts. Regenerate with compile-epic-context if planning docs change. -->

## Goal

Stand up the product's foundation and its entire access model: the monorepo skeleton and design-token layer every later story builds on, then secure, admin-provisioned accounts for Staff and Administrators with no public sign-up path anywhere. Users authenticate, are forced off temporary credentials, hold sessions that survive a shift without leaving them exposed, and are protected by login throttling. Administrators create, edit, deactivate and delete accounts, and every login, failed login and account change lands in an append-only audit log they can read in-app. This epic is both the scaffold and the security spine — the catalogue and scanning epics have nothing to authenticate against, and no audit trail to write to, until it exists, and an independent penetration test gates general staff rollout.

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

- **No public entry.** No registration endpoint or UI, no social login, no app-sent email. Administrators distribute temporary credentials manually; a signed-out user with a forgotten password goes through an Administrator, never a reset email.
- **One seeded Administrator, by migration only** — the only account in the product's lifetime not created by an Administrator. Seeded must-change-password; re-running migrations never produces a second.
- **Temporary credentials are a gate.** A user on one reaches only the password-change screen; every other navigation redirects back. Unclaimed ones expire after 72 hours and must be reissued.
- **Session bounds:** 12h inactivity, 7-day absolute regardless of activity.
- **Login throttling:** measurable progressive delay from the 6th failed attempt; the 10th cumulative failure locks the account, visible to Administrators in that user's status.
- **Role and status changes take effect on the user's very next request**, not at next login.
- **At least two active Administrators must always exist** — deactivating or deleting the last one is refused. With only the seeded account present this refusal fires; that is the rule working, not a defect.
- **Authorization is server-side on every endpoint**, independent of what the UI hides.
- **Audit coverage:** every login, failed login, and user create/edit/deactivate/delete records who, what, when, source IP — with no update or delete path from code or UI.
- **Account state is never leaked** — wrong password, missing account and deactivated account reject identically. Lockout is the one exception and gets its own message.
- Argon2id only; secrets from environment or secret store, never committed, including in test fixtures. Security paths need failure-case tests. `make lint`/`make test` must exist and pass against the empty skeleton.

## Technical Decisions

- **Structure:** six hand-built directories — `apps/web`, `apps/api`, `shared/vision`, `shared/schema`, `infra`, `scripts/ingest`; no generator exists for this stack. `apps/web` is presentation only, talks to nothing but `apps/api`, and holds no database or storage credential. This epic touches web/api/schema/infra; vision and ingest need only runnable skeletons.
- **Pinned stack:** React 19.2.x / Vite 8.0.x / TypeScript 7.0.x (strict, no unexplained `any`); FastAPI 0.141.x / Python 3.12+ (ruff, type hints, no bare `except`); PostgreSQL 18.x. No component library is inherited. Flag any new dependency before adding it.
- **Sessions are Postgres rows** validated through one shared lookup function, never a per-route check. That lookup re-reads role and active status every request — neither is cached at login, which is what makes role edits and deactivations immediate. No Redis or second stateful store.
- **The session token lives only in an HTTP-only / Secure / SameSite=Strict cookie**, never reachable from page script or browser storage, stored hashed at rest.
- **Counters are Postgres rows** mutated by a single atomic increment-and-check (one `UPDATE ... RETURNING`, never read-then-write) — they must survive a restart and a second API instance, and must not be outrun by a concurrent burst.
- **Audit immutability is enforced at the database-role level** — INSERT and SELECT granted, UPDATE and DELETE not. App-code discipline alone is insufficient; a bad entry is corrected by inserting a corrective entry. `source_ip` comes only from the trusted reverse-proxy forwarded header.
- **Audit entries carry no enforced foreign keys** to catalogue objects — anything naming a Tile or Reference Image is a denormalized snapshot, so later hard deletes can't corrupt or block the log.
- **Naming:** glossary terms verbatim as PascalCase entities across api/schema/web (`User`, `Session`, `AuditLogEntry`, `Staff`, `Administrator`). `Product` and `Face` are retired and must not appear in new code. UUIDv4 ids, ISO 8601 UTC timestamps, one API error envelope: `{ "error": { "code", "message" } }`.
- `User` carries at least role, active, must-change-password, and temporary-credential-expiry. Migrations are forward-only and reversible; never edit an applied one.
- **Open infrastructure decisions that block deployment and should be resolved early here:** hosting provider and environments, CI/CD, object storage, secrets management, backup/DR, monitoring. Also confirm pgvector's PostgreSQL 18 compatibility at build time — verified testing covered 16/17 only.

## UX & Interaction Patterns

The design and experience spines are the binding contract and win over any mockup. Invoke the `ui-ux-pro-max` skill and run its pre-delivery checklist before calling any UI story done.

- **The token layer is the only styling source** — no raw hex in components. Plus Jakarta Sans across five roles plus a monospace role for product codes, each with a declared fallback; Phosphor outline icons only.
- **Color discipline:** navy is chrome (app bar, admin badge), orange is the single primary action per screen, red means destructive and nothing else. The primary button's foreground is navy — white on orange fails contrast.
- **Nav is role-conditional**, not a shared menu with disabled items. Bottom tab bar on mobile with admin sections behind a "More" tab; sidebar at desktop/tablet, where admin table density also shifts. Sheets never stack more than one level.
- **Force-password-change is the only thing on screen** — no nav chrome, no dismissal. Errors name the specific rule that failed; success goes straight to the destination with no interstitial.
- **Admin tables** are dense rows with hover and hairline separators, no card wrapper. Role and status badges are display-only. Destructive actions live in a labelled row-end menu, and the audit log is the one table with zero row-end actions at any role.
- **Destructive actions confirm by naming the object and its consequence**; the last-Administrator case replaces the dialog with a refusal rather than a confirm. The save indicator is inline near its trigger, never a corner toast.
- **State patterns this epic owes:** deactivated-account login, lockout, weak/mismatched password, password set, session expired mid-flow (warn before dropping an unsaved admin form), and live role change mid-session (nav updates next request; a revoked permission redirects to the highest surface the new role can reach).
- **Accessibility floor:** ≥44×44px touch targets, visible focus state and keyboard path on every interactive element, destructive actions never signalled by color alone. Microcopy is short and factual.

## Cross-Story Dependencies

- **1.1 gates everything** — no UI story can begin before the scaffold and tokens exist.
- **1.2 → 1.3 → 1.4.** Login has nothing to authenticate against without the schema and seeded Administrator, and that account is seeded must-change-password so the forced-change gate is exercised on the first sign-in. This ordering is deliberately why login does not circularly depend on Create User (1.8).
- **1.5 underpins 1.10 and 1.11** — the shared session lookup's live role/active re-read is the mechanism behind their immediacy requirement; neither works with a session-cached role.
- **1.6 and 1.12 share substrate** — a failed login both increments the atomic counter and writes an audit entry.
- **1.12 → 1.13** — the read surface renders what the write path records; both must agree on the entry shape.
- **1.11 depends on 1.2's seeding behavior** for its last-Administrator guard to be testable.
- **Forward:** Epics 2 and 3 extend this audit write path with catalogue and scan events, and every Epic 2 admin surface sits behind this epic's server-side role check — the database-level grant model must be in place first.
