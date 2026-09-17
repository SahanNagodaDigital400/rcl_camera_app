---
title: 'Story 1.4 — Forced Password Change on First Login'
type: 'feature'
created: '2026-09-17'
baseline_revision: 'a739221d4ef0c1bd5f91c60c808bd59859f95061'
status: 'done'
review_loop_iteration: 0
followup_review_recommended: true # score 8 (0 high patched); see Auto Run Result
context:
  - '{project-root}/AGENTS.md'
  - '{project-root}/_bmad-output/planning-artifacts/architecture/architecture-rcl_camera_app-2026-08-30/ARCHITECTURE-SPINE.md'
  - '{project-root}/_bmad-output/planning-artifacts/ux-designs/ux-rcl_camera_app-2026-09-08/EXPERIENCE.md'
  - '{project-root}/_bmad-output/planning-artifacts/ux-designs/ux-rcl_camera_app-2026-09-08/DESIGN.md'
warnings: ['oversized']
deferred:
  - summary: >-
      `POST /auth/password` is a second Argon2id-backed endpoint that the
      forced-change gate must leave open, so a signed-in user on a temporary
      credential can spend two ~100ms hashes per request against a pool of ten
      connections with no throttle anywhere.
    evidence: |-
      The handler verifies the candidate against the stored digest (the reuse
      rule) and then hashes the accepted one, so each call costs two 64 MiB
      Argon2id operations. `require_claimed_user` cannot gate it — that is the
      point of the endpoint — and Story 1.6's counters are scoped to login by
      epics.md. Combined with DW-34 (POOL_MAX_SIZE = 10 behind a 40-worker sync
      threadpool) a modest burst from one authenticated account queues every
      other request behind it. Bounding it means choosing whether the counter
      is per-account or per-session and whether it shares Story 1.6's substrate,
      which is that story's decision to take.
    location: >-
      apps/api/api/auth.py
    severity: medium
  - summary: >-
      `make reseed-admin` refuses an account with a recorded sign-in, so an
      Administrator who signs in on the temporary credential and lets the 72
      hours lapse without claiming has no console path back in at all.
    evidence: |-
      `_SELECT_UNCLAIMED_ADMINISTRATOR` carries `AND last_login_at IS NULL`, so
      the reissue treats a sign-in as a claim. After the deadline passes, login
      refuses the credential (Story 1.3), `POST /auth/password` refuses it and
      revokes the sessions riding on it, and the reissue refuses the account —
      on a database whose only Administrator is in that state the product is
      unreachable and recovery is a manual `UPDATE`. Pre-existing: the
      predicate and the login refusal both predate this story, which only
      narrowed the window rather than opening it. `infra/rocell_infra/seed.py`
      is marked read-only by this spec's Code Map, and widening the reissue is
      a decision about what counts as a claim — the same judgement Story 1.8's
      account creation has to make.
    location: >-
      infra/rocell_infra/seed.py:54
    severity: high
  - summary: >-
      Nothing revokes a session when a temporary credential's deadline passes;
      only an attempt to use it does, so an unclaimed holder keeps a live
      session for the session's full seven days.
    evidence: |-
      `_SELECT_SESSION` joins on `s.expires_at > now() AND u.active` and never
      reads `temp_credential_expires_at`. A holder who signs in at hour 1 and
      never posts to `/auth/password` still gets `200` from `GET /auth/session`
      with the flag set, `204` from logout, and `403` rather than `401` from
      every gated route, for four days past the credential's death. Closing it
      means either widening the one AD-3 session lookup (which this story is
      forbidden to fork) or a sweep job, and Story 1.5 owns session lifetimes.
    location: >-
      apps/api/api/sessions.py
    severity: medium
  - summary: >-
      `apps/web` has no state, microcopy or test for the expired-credential
      path, so the most likely real failure lands the user on the login screen
      with a message that reads as a typo.
    evidence: |-
      `changePassword`'s `unauthorized` branch sets `signed-out` and rethrows
      with nothing shown; the login screen then answers the generic
      `INVALID_CREDENTIALS` sentence, which says "you typed it wrong" rather
      than "your 72 hours are up, ask an Administrator". The server side is
      right and tested; the screen has no row in this story's I/O matrix for
      it, and writing one is a copy decision under EXPERIENCE.md's tone rules
      that also depends on the reseed question above.
    location: >-
      apps/web/src/auth/SessionProvider.tsx
    severity: medium
  - summary: >-
      A `must_change_password` row with a NULL `temp_credential_expires_at` is
      permanently unusable by design, and nothing warns the Administrator who
      will be able to create one.
    evidence: |-
      `credential_expired` fails closed, deliberately and correctly: such a row
      is refused at login, 403s on every gated route and 401s at
      `POST /auth/password`. Today only the seeder writes the flag and it always
      writes an expiry, so the shape is unreachable. Story 1.10 edits users and
      "force a password change" is the obvious next control; an admin who sets
      the flag without an expiry would brick the account with no feedback. The
      fix is a constraint or a default on `users`, which is a migration and a
      decision for the story that adds the control.
    location: >-
      apps/api/api/auth.py:125
    severity: medium
  - summary: >-
      `ForcedPasswordChangeScreen` duplicates `LoginScreen`'s form machinery and
      stylesheet almost exactly; Story 1.7's change form will be the third copy.
    evidence: |-
      Stripped of comments the two stylesheets differ only in `.panel`'s card
      declarations — `.screen`, `.title`, `.lede`, `.form`, `.field`, `.label`,
      `.input`, `.submit`, `.submit:disabled` and `.error` are identical — and
      the component repeats the same `useId` / `noValidate` / `aria-describedby`
      / inserted-`role="alert"` / `submitting` pattern. The cost is already
      visible in `styling-wiring.test.ts`, which had to be parameterised over
      two files. Extracting it is a component-API decision better taken with
      the third caller in hand than guessed at now.
    location: >-
      apps/web/src/screens/ForcedPasswordChangeScreen.tsx
    severity: medium
  - summary: >-
      The boundary of every text input is `--color-border` on its container at
      roughly 1.2:1, under WCAG 1.4.11's 3:1 floor for a control boundary.
    evidence: |-
      `#ECE6DB` on the panel's `#FFFFFF` is about 1.24:1, and on the login
      screen's `#FAFAF8` about 1.19:1 — the new screen is marginally the better
      of the two, so this is not something this story introduced. It affects
      every form surface the product will grow. Fixing it means darkening
      `--color-border` or giving inputs their own border token, which is a
      DESIGN.md change, not a code change.
    location: >-
      apps/web/src/styles/tokens.css:32
    severity: low
  - summary: >-
      A login that commits a session between `delete_sessions_for_user` and the
      password change's COMMIT survives the credential rotation.
    evidence: |-
      The change runs in one transaction, but the DELETE does not block an
      INSERT of a row that does not exist yet, so under read-committed a
      concurrent login on the still-valid temporary password can land a session
      that outlives the rotation. It needs a second party who knows the
      temporary credential and races a ~100ms window. Closing it properly means
      locking the user row for the duration of the change, which is a
      concurrency decision that touches login as well.
    location: >-
      apps/api/api/auth.py
    severity: low
  - summary: >-
      Request-validation rejections carry no `cache-control` at all, against the
      rule that every auth response carries `NO_STORE`.
    evidence: |-
      `validation_error_handler` passes no headers to `_envelope`, so the
      `422 validation_error` from a malformed or absurd body ships bare — on
      `POST /auth/login` since Story 1.3 and now on `POST /auth/password` too.
      The bodies say nothing about an account, so the exposure is small, but the
      invariant is stated absolutely and this is the one hole in it. The fix is
      one shared default in the handler, which touches every endpoint's
      rejections at once.
    location: >-
      apps/api/api/main.py:104
    severity: low
  - summary: >-
      A whitespace-only password of twelve or more characters is accepted by
      `POST /auth/password` but can never be submitted at the login screen.
    evidence: |-
      `LoginScreen`'s blank guard tests `.trim()` and refuses to send, so a user
      who set twelve spaces as their password would be locked out of the UI by
      the client, with a valid digest in the database. The guard predates this
      story. Refusing it at the API means a third rule message where
      EXPERIENCE.md names two, so it is a policy decision rather than a fix.
    location: >-
      shared/schema/shared_schema/passwords.py
    severity: low
---

<intent-contract>

## Intent

**Problem:** Story 1.3 deliberately issues a session to a user holding an admin-issued temporary credential and reports `must_change_password: true` — and then nothing acts on it. `api/sessions.py`'s `lookup_session` docstring records the obligation in terms ("the first route that serves real data must refuse a `must_change_password` user"), but no gate exists, no endpoint can set a password, and `apps/web` renders the authenticated shell to anyone whose credential was handed to them on a sticky note. AGENTS.md Policy forbids granting further access on a temporary credential before the forced change.

**Approach:** Deliver the change itself and the gate that makes it unavoidable. `POST /auth/password` sets a real password for the signed-in holder of a temporary credential, enforcing the password rules and rejecting reuse of the temporary one; a shared `require_claimed_user` dependency refuses every other authenticated route with `403 password_change_required`, enforced by a route-table guard test so a future route cannot forget it; and `apps/web` renders a chrome-less single-field change screen in place of the shell for as long as the flag is set, so there is nowhere else to navigate to.

## Boundaries & Constraints

**Always:**
- Argon2id only, through `shared_schema.passwords` — never a second hasher (AGENTS.md Policy; `apps/api/tests/test_source_guards.py::test_only_one_module_builds_a_password_hasher`).
- Exactly ONE session-lookup function (AD-3). The new dependency **wraps** `api.sessions.lookup_session`; it does not query `sessions` itself — `test_only_one_module_reads_the_sessions_table` enforces this.
- The gate is server-side and independent of what the UI hides (AGENTS.md Policy): the front-end trap is a convenience, the dependency is the control.
- Every rejection uses the shared envelope via `ApiError`, and every auth response carries `NO_STORE` like the three that exist.
- A rejected password **names the rule that failed** — length, or reuse of the temporary password — and never a generic "invalid password" (EXPERIENCE.md:87).
- The password rules live in `shared/schema` so Story 1.7 reuses them rather than restating them.
- Parameterized SQL only; `updated_at` set by hand (DW-17 — `users` has no trigger).
- Every value in new `apps/web` CSS comes from `src/styles/tokens.css` (UX-DR1); the `no-raw-values` guard enforces it.
- No new secret, password or connection string committed, including in fixtures — the test fixtures generate passwords at runtime, as `apps/api/tests/conftest.py` already does.
- Migrations are forward-only and never edit an applied one.

**Block If:**
- Enforcing "the new password is not the temporary one" would require reading `users.password_hash` outside `apps/api`'s auth path or a second `PasswordHasher`.
- Gating `must_change_password` cannot be expressed without adding a second session query (AD-3 violation).

**Never:**
- A `current_password` field, or a password change for a user whose `must_change_password` is already `false` — that is Story 1.7's endpoint and its own decision about re-authentication. `POST /auth/password` refuses a claimed account with `409 password_change_not_required`.
- Failed-attempt counters, progressive delay or lockout (Story 1.6 / AD-8).
- Audit-log writes (Story 1.12). Record the gap in a comment; do not build a private log path.
- Sliding inactivity renewal, the 12-hour idle window, session listing, or bulk revocation as a feature (Story 1.5). Deleting *this user's* sessions as part of their own password change is credential rotation, not session management — see Design Notes.
- A router library. The trap is a conditional render in `App.tsx`; the screen is the only thing that can be rendered while the flag is set, so there is no navigation to intercept.
- A password **composition** rule (one digit, one symbol). `shared_schema.passwords` states why length is the only strength rule.
- An in-app Administrator reissue screen or endpoint — Story 1.8 creates accounts with temporary credentials and 1.10 edits them. The only account that exists at this point in the epic is the seeded Administrator, whose reissue path is `make reseed-admin` (`infra/README.md` §"The 72-hour expiry").
- A confirm-password second field. DESIGN.md:219 specifies "a single-field form (new password)".
- A success interstitial. EXPERIENCE.md:88: the transition is immediate.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Forced change succeeds | `POST /auth/password` with a valid cookie for a `must_change_password` user and an acceptable `new_password` | `200` with the shared `User`, now `must_change_password: false` and `temp_credential_expires_at: null`; `password_hash` replaced; `updated_at` advanced; every prior session row for that user gone and **one** new row issued; a fresh `Set-Cookie` with the full attribute set | No error expected |
| New password too short | same, `new_password` under `MIN_PASSWORD_LENGTH` | `422`, code `weak_password`, a message naming the length rule; nothing written | Password unchanged, session untouched |
| New password too long | `new_password` over `MAX_PASSWORD_LENGTH` | `422`, code `weak_password`, a message naming the length rule; **nothing is hashed** for it | Refused by request validation before the handler |
| New password reuses the temporary one | `new_password` equals the credential just signed in with | `422`, code `weak_password`, a message naming reuse; nothing written | The one rule that costs an Argon2id verify |
| Already claimed | valid cookie, `must_change_password = false` | `409`, code `password_change_not_required`; nothing written | Story 1.7 owns the claimed-account change |
| No session | no cookie, unknown token, expired row, or deactivated owner | `401`, code `unauthorized`, the `NO_SESSION` message, stale cookie cleared | The existing `_not_signed_in()` |
| Gate refuses a claims-required route | valid cookie, `must_change_password = true`, any route declaring `require_claimed_user` | `403`, code `password_change_required`, a message telling the caller to set a password | Never `200`; never partial data |
| Gate passes | valid cookie, `must_change_password = false` | the route runs and receives the `User` | No error expected |
| Session read while gated | `GET /auth/session`, `must_change_password = true` | `200` with the flag set — deliberately **not** gated, this is how the front end learns to show the screen | No error expected |
| Logout while gated | `POST /auth/logout`, `must_change_password = true` | `204` — deliberately not gated; a user must always be able to leave | Idempotent |
| Expired temporary credential | credential past `temp_credential_expires_at`, unclaimed | login answers the generic `401` (Story 1.3), so the change screen is unreachable and the credential must be reissued | Reissue is `make reseed-admin` for the seeded Administrator |
| Web, flag set | bootstrap or sign-in returns `must_change_password: true` | The change screen replaces the shell: no app bar, no nav, no sign-out, no dismissal | — |
| Web, weak password | the API answers `422 weak_password` | The API's own message inline in `--color-destructive` with `role="alert"`, focus kept in the form, the field retained | A non-`ApiRequestError` failure shows a generic factual message |
| Web, change succeeds | the API answers `200` with the cleared flag | The shell renders immediately, with no success screen to click through | — |

</intent-contract>

## Code Map

**Read-only sources of truth (do not edit):**
- `_bmad-output/planning-artifacts/epics.md` lines 218–230 — Story 1.4's acceptance clauses verbatim; 231–243 (1.5 owns lifetimes), 244–256 (1.6 owns throttling), 257–268 (**1.7 owns the signed-in self-service change, with a current password**), 270–281 (1.8 creates accounts with temporary credentials), 296–307 (1.10 edits users), 322–334 (1.12 owns audit).
- `_bmad-output/planning-artifacts/ux-designs/ux-rcl_camera_app-2026-09-08/DESIGN.md` — **line 219**: "a single-field form (new password) using standard input styling; error text in `{colors.destructive}`, the 'your password is set' success transition in `{colors.primary}`; submit button is `button-primary`. No navigation chrome around it — it's the only thing on screen until it's done." Lines 134–137 (`force-password-change-form` token block); line 207 (the app bar is on authenticated screens only); lines 172–182 (navy on orange; white on orange is banned). **No mockup exists** — `mockups/` holds scan, crop, results and user-list only. Author the microcopy.
- `_bmad-output/planning-artifacts/ux-designs/ux-rcl_camera_app-2026-09-08/EXPERIENCE.md` — line 25 (IA row: "Gates every screen on a temporary credential"); line 65 ("The only thing on screen — no nav, no way to dismiss it. Validates against the same password policy as any other password field; a rejected password states which rule failed."); **line 87** (the rejected-password state names the rule — "length, reuse of the temporary password"); **line 88** (success transitions immediately, no success screen); lines 50–57 (voice: short, factual, no exclamation marks).
- `AGENTS.md` line 18 — "Never skip the forced password change on an admin-issued temporary credential before granting further access; temporary credentials expire after 72 hours." Policy lines 8–24 for hashing, server-side authz, cookies, parameterized SQL, committed secrets.
- `ARCHITECTURE-SPINE.md` — **AD-3** (one shared session lookup; role/active re-read per request), **AD-6** (web holds no DB credential), Consistency Conventions (UUIDv4, ISO 8601 UTC, the single error envelope).
- `_bmad-output/implementation-artifacts/deferred-work.md` — **DW-17** (`users.updated_at` has no trigger; this story's `UPDATE` must set it), **DW-19** (no rehash path), **DW-36** (no CSRF defence on `POST /auth/login` — this story adds a second unauthenticated-shaped POST and closes nothing; `SameSite=Strict` is what stands in the meantime), **DW-37** (`apps/web` never revalidates a session the server stopped honouring).

**Files that already exist and constrain the shape:**
- `apps/api/api/auth.py` — the router, `INVALID_CREDENTIALS`, `UNAUTHORIZED`, `NO_SESSION`, `NO_STORE`, `AUTH_CHALLENGE`, `_rejected()`, `_not_signed_in()`, and the `Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)]` parameter pattern every auth handler uses. **`_RECORD_LOGIN`'s `RETURNING` list is the exact ten-column shape `User.model_validate` wants** — the password update's `RETURNING` must match it. Handlers are `def`, not `async def` (psycopg is sync and Argon2id is CPU-bound).
- `apps/api/api/sessions.py` — `lookup_session` (the one AD-3 lookup; **its docstring carries the obligation this story discharges and must be updated**), `issue_session`, `delete_session`, `set_session_cookie`, `clear_session_cookie`, `cleared_cookie_headers`, `SESSION_COOKIE_NAME`, `SESSION_ABSOLUTE_LIFETIME`. There is **no** "delete every session for a user" helper — this story adds one.
- `apps/api/api/main.py` — `create_app()`, `STATUS_CODES` (already maps `403 → "forbidden"` and `409 → "conflict"`), the four exception handlers, `app.include_router(auth.router)`. Routes are declared inside `create_app`; the route-table guard test reads `app.routes`.
- `apps/api/api/db.py` — `get_connection` dependency and the lifespan; the new dependency composes with it.
- `shared/schema/shared_schema/passwords.py` — `MIN_PASSWORD_LENGTH = 12`, `MAX_PASSWORD_LENGTH = 128`, `hash_password` (raises `ValueError` with rule-naming text), `verify_password` (returns `False` for empty/oversized before hashing), `verify_dummy_password`, `warm_password_verifier`, one module-level `_HASHER`. The length messages are **already** written as rule-naming prose — extract them rather than restating them.
- `shared/schema/shared_schema/__init__.py` — the single import surface; anything added to `passwords.py` is re-exported here and added to `__all__`.
- `shared/schema/shared_schema/user.py` + `ts/user.ts` — the closed ten-key `User` contract; `isUser`, `USER_KEYS`. **No new shared type is needed** — the change endpoint returns a `User`.
- `shared/schema/shared_schema/errors.py` — `ApiError(code, message, status_code, headers)`.
- `apps/api/tests/conftest.py` — `conn`, `client` (https `base_url` so the `Secure` cookie survives the jar), and **`make_user(role=, active=, must_change_password=, temp_credential_expires_at=, name=)` returning `Account(id, email, password, name)`** with a runtime-generated password. Everything this story tests is built from that factory.
- `apps/api/tests/test_source_guards.py` — `SCANNED` roots, `test_only_one_module_builds_a_password_hasher`, `test_only_one_module_reads_the_sessions_table` (excludes `SESSIONS_HOME` and anything under `tests`). New API code must satisfy both.
- `apps/api/tests/test_no_registration.py` — scans source for register/signup surfaces; new files must not use those words.
- `apps/web/src/App.tsx` — the `Gate` component: `loading` → placeholder, `signed-out`/`user === null` → `LoginScreen`, else `AppShell`. **The new branch goes between them**, before the shell. Focus is moved to `MAIN_REGION_ID` on every status change except the first resolution of `loading` — the new screen must carry the same id and `tabIndex={-1}`.
- `apps/web/src/auth/SessionProvider.tsx` — `status`/`user`/`signIn`/`signOut`, `asUser` narrowing via `isUser`, errors deliberately propagate to the screen. `changePassword` joins it with the same shape.
- `apps/web/src/screens/LoginScreen.tsx` + `.module.css` — **the pattern to follow**: `useId` for label/error association, `noValidate` with client-side blank checks, `aria-invalid`/`aria-describedby`, the inserted (not refilled) `role="alert"` paragraph, `submitting` disabling, `main#MAIN_REGION_ID tabIndex={-1}`, `.panel`/`.field`/`.label`/`.input`/`.submit`/`.error` classes composed entirely from tokens.
- `apps/web/src/api/client.ts` — `apiRequest`, `ApiRequestError` (carries `code`), `UNAUTHORIZED`, `MALFORMED_RESPONSE`. Screens branch on `code`, never on the message.
- `apps/web/src/styles/tokens.css` — the only file allowed literals. Already carries `--color-destructive`, `--color-primary`, `--color-accent`, `--color-accent-foreground`, `--color-muted-text`, `--measure-form`, `--radius-sm`, `--border-hairline`, `--disabled-opacity`, the six type roles and the spacing scale. **Adding a derived token is allowed; contradicting a DESIGN.md value is not.**
- `apps/web/src/styles/global.css` — already gives every `button` and non-checkbox `input` the 44px floor and `:focus-visible` an accent ring. Do not restate.
- `apps/web/src/__tests__/styling-wiring.test.ts` — asserts every `styles.x` reference resolves to a real class in that module, and (lines 189–218) that the error element's class is coloured `--color-destructive` **on both screens**; a third screen belongs in the same block.
- `apps/web/src/__tests__/auth-gating.test.tsx` — the `STAFF` fixture and the `stubFetch` path-keyed queue; the forced-change gating cases extend this file's machinery.
- `apps/web/src/__tests__/no-client-token-storage.test.ts` — scans `apps/web` for `localStorage`/`sessionStorage`/`document.cookie`/`indexedDB`. The new code must keep it green.
- `infra/README.md` §"The 72-hour expiry, and `make reseed-admin`" (line 143) and `README.md` lines 89–90 — the operator-facing account of reissue. They describe the mechanism; neither yet says what the user then *does* with the reissued credential.
- `infra/rocell_infra/seed.py` — `TEMP_CREDENTIAL_LIFETIME_HOURS = 72`, `reseed_administrator` (refuses a claimed account — `must_change_password` cleared **or** a recorded sign-in). Read-only here; it is the reissue half of the AC.

## Tasks & Acceptance

**Execution:**

- `shared/schema/shared_schema/passwords.py` — add `PASSWORD_RULES` messages and `password_rule_violation(password: str) -> str | None`, returning the rule-naming message for an empty/short/long password and `None` otherwise. Refactor `hash_password` to raise `ValueError(password_rule_violation(...))` so the length rules have exactly one statement, and Story 1.7 inherits them. No composition rule.
- `shared/schema/shared_schema/__init__.py` — re-export `password_rule_violation` and extend `__all__`.
- `shared/schema/tests/test_passwords.py` — extend: each rule's message names the rule it enforces (length, not "invalid"); `password_rule_violation` returns `None` for an acceptable password and agrees with `hash_password`'s raise at both boundaries (exactly `MIN_PASSWORD_LENGTH` and `MAX_PASSWORD_LENGTH` are accepted, one either side is not).
- `apps/api/api/sessions.py` — add `delete_sessions_for_user(conn, user_id) -> int` (parameterized `DELETE ... WHERE user_id = %s`), and **update `lookup_session`'s docstring**: the obligation it records is discharged by `api.dependencies.require_claimed_user`, which is the thing future routes must declare.
- `apps/api/api/dependencies.py` — the authorization dependencies, both built on `lookup_session` and neither querying `sessions`: `current_user` (401 via the existing `_not_signed_in()` shape when there is no usable session) and `require_claimed_user` (`current_user`, then `403 password_change_required` when `must_change_password`). This is the gate AGENTS.md line 18 requires, and every route added after this story that serves real data declares it.
- `apps/api/api/auth.py` — add `POST /auth/password`: a pydantic body (`extra="forbid"`, `new_password` bounded `1..MAX_PASSWORD_LENGTH` so an oversized candidate is refused before anything is hashed), `current_user` for the session, `409 password_change_not_required` when the flag is already clear, `password_rule_violation` then a reuse check via `verify_password(row["password_hash"], new_password)` → `422 weak_password` naming the rule, then in one transaction: `UPDATE users SET password_hash, must_change_password = false, temp_credential_expires_at = NULL, updated_at = now() ... RETURNING` the ten `User` columns, `delete_sessions_for_user`, `issue_session`; set the new cookie and return the `User`. `NO_STORE` on every response. A comment recording that Story 1.12 owes this endpoint an audit entry.
- `apps/api/tests/test_password_change.py` — the matrix's `POST /auth/password` rows: success clears the flag and the expiry and advances `updated_at`; the old cookie stops working and the new one works; exactly one session row survives; too-short, too-long and reuse each answer `422 weak_password` with a message naming the rule and leave the digest, the flag and the session row untouched; an oversized candidate is refused by validation; a claimed account answers `409`; no cookie answers `401`; the old password no longer signs in and the new one does.
- `apps/api/tests/test_forced_change_gate.py` — the gate as a unit: mount `require_claimed_user` on a throwaway route inside a test-built app (no fake route ships) and drive it — `must_change_password = true` → `403 password_change_required`, cleared → the route runs, no cookie → `401`, deactivated owner → `401`. Plus the guard that makes the obligation self-enforcing: **every route in `create_app()`'s route table outside an explicit allowlist (`/health`, `POST /auth/login`, `GET /auth/session`, `POST /auth/logout`, `POST /auth/password`) declares `require_claimed_user`**, with the allowlist's reason stated per entry, so a future route cannot silently serve a user on a temporary credential.
- `apps/api/tests/test_login.py` — extend with the AC's second clause end to end: a user whose `temp_credential_expires_at` has passed is refused by login with the generic rejection, so the change screen is unreachable and the credential must be reissued; and a valid unclaimed credential signs in and `POST /auth/password` then completes the claim.
- `apps/web/src/api/client.ts` — export the two new codes (`WEAK_PASSWORD`, `PASSWORD_CHANGE_REQUIRED`) alongside `UNAUTHORIZED`, so screens branch on a constant rather than a string literal.
- `apps/web/src/auth/SessionProvider.tsx` — add `changePassword(newPassword: string): Promise<void>` posting to `/auth/password` and narrowing the reply with the existing `asUser`; on success set the returned user, which clears the flag and lets the gate fall through. Errors propagate to the screen, as `signIn` does.
- `apps/web/src/screens/ForcedPasswordChangeScreen.tsx` + `.module.css` — the chrome-less single-field screen: no app bar, no nav, no sign-out, no dismissal; a heading, one factual line saying why it is here, one labelled password field (`type="password"`, `autoComplete="new-password"`), one primary accent submit with navy foreground and a disabled in-flight state, and one inserted `role="alert"` paragraph in `--color-destructive` carrying the API's own rule-naming message. Same `main#MAIN_REGION_ID tabIndex={-1}` as the other two screens. Microcopy under EXPERIENCE.md's tone rules.
- `apps/web/src/App.tsx` — add the branch: `signed-in` **and** `user.must_change_password` → `ForcedPasswordChangeScreen`, before the shell. This is the navigation trap — with no router, the shell is not reachable while the flag is set. Update the component docstring, which currently says Story 1.4 is where the routing-dependency question gets forced: it does not, and the reason belongs on the record.
- `apps/web/src/styles/tokens.css` — only if the screen needs a derived token, with a comment naming what it derives from.
- `apps/web/src/__tests__/forced-password-change.test.tsx` — the screen's own behaviour: the label is associated with its input, the input is `type="password"`, no app bar and no nav render, a blank submit is refused without a request, submitting calls the API once, a `422` renders the rule-naming message in a `role="alert"` element, the button is disabled in flight, and the form is operable by keyboard alone.
- `apps/web/src/__tests__/auth-gating.test.tsx` — extend: a bootstrap returning `must_change_password: true` renders the change screen and **not** the shell (asserted by the absence of the app bar and the sign-out control); a successful change swaps straight to the shell with no interstitial; a sign-in that returns the flag goes to the change screen rather than the shell.
- `apps/web/src/__tests__/styling-wiring.test.ts` — extend the existing destructive-colour block to the third screen, and assert the class the new alert element actually carries.
- `infra/README.md` — under §"The 72-hour expiry", state what happens after a reissue: the reissued credential signs in and lands on the forced-change screen, which is the only thing it can reach until a real password is set.
- `README.md` — one line in the operator account: a new account's first sign-in lands on the password-change screen and reaches nothing else until it is done.

**Acceptance Criteria:**
- Given a user holding a valid unclaimed temporary credential, when they sign in and then call any route declaring `require_claimed_user`, then the route answers `403 password_change_required` and returns no data; and when they complete `POST /auth/password`, then the same route answers normally on the very next request.
- Given `create_app()`'s route table, when every route is inspected, then each one outside the stated allowlist declares `require_claimed_user`, so a route added later cannot serve a user on a temporary credential by omission.
- Given a completed forced change, when the database is inspected, then `must_change_password` is `false`, `temp_credential_expires_at` is `NULL`, `password_hash` differs from its previous value, `updated_at` has advanced, exactly one session row exists for that user, and the cookie the caller held before the change no longer authenticates.
- Given a signed-in user whose `must_change_password` is already `false`, when they call `POST /auth/password`, then it answers `409 password_change_not_required` and nothing is written — the claimed-account change is Story 1.7's.
- Given a user on a temporary credential, when they submit a new password that is too short, too long, or identical to the temporary one, then the response is `422 weak_password` with a message naming the failing rule, and the stored digest, the flag and the session are unchanged.
- Given a temporary credential whose `temp_credential_expires_at` has passed, when it is presented at `POST /auth/login`, then the generic rejection is returned, no session is issued, and the change screen cannot be reached — the credential has to be reissued (`make reseed-admin` for the seeded Administrator).
- Given `apps/web` with a session whose `must_change_password` is `true`, when the app renders, then the change screen is the only thing on screen — no app bar, no navigation, no sign-out control and no dismissal — and the shell is not in the document.
- Given a successful change in `apps/web`, when the API answers, then the shell renders immediately with no success screen in between.
- Given the new code, when it is searched, then no SQL is assembled by concatenation or interpolation, no second `PasswordHasher` exists outside `shared/schema/shared_schema/passwords.py`, no second module reads the `sessions` table, and no password or connection string is committed in any test or fixture.
- Given `make lint` and `make test` on a clean checkout, when both are run, then both exit 0.

## Spec Change Log

## Review Triage Log

### 2026-09-17 — Review pass

- intent_gap: 0
- bad_spec: 0
- patch: 14: (high 1, medium 6, low 7)
- defer: 1: (high 0, medium 1, low 0)
- reject: 8
- addressed_findings:
  - `[high]` `[patch]` An expired temporary credential could still claim the account through a session issued before it expired — `set_password` read only `must_change_password`, and a 7-day session outlived a 72-hour credential by up to four days. The endpoint now reads login's own `credential_expired` expression, revokes every session of that user and answers 401; `infra/README.md`, which asserted the opposite in prose, was corrected.
  - `[medium]` `[patch]` The claim was check-then-act: `_SET_PASSWORD` carried no `AND must_change_password`, so two concurrent posts both wrote and the second revoked the first's session. The predicate moved into the statement and a zero-row `RETURNING` now raises the 409.
  - `[medium]` `[patch]` Focus was dropped on the change-screen-to-shell swap although three comments claimed otherwise — the gate's effect keyed on `status`, which is `signed-in` on both sides. `App.tsx` now derives a `Screen` and keys render and focus on it.
  - `[medium]` `[patch]` A 401 or 409 from `POST /auth/password` trapped the user on a screen with no way out. `changePassword` now drops to `signed-out` on both before rethrowing, and the 409's code gained a TypeScript constant.
  - `[medium]` `[patch]` Two of the three password rules could not reach a user: the request model's bounds answered an empty and an oversized candidate with the generic `validation_error`, against the I/O matrix and EXPERIENCE.md:87. The bounds were replaced with a 4096-character absurd-body ceiling so both now get their rule-naming sentence.
  - `[medium]` `[patch]` Nothing asserted that `delete_sessions_for_user` leaves another user's rows alone — a two-user test and a `rowcount` test were added.
  - `[medium]` `[patch]` The route-table guard silently ignored any route that was not an `APIRoute`, so a future WebSocket or `Mount` could bypass it. It now fails naming the type.
  - `[low]` `[patch]` `aria-invalid` was set for network and timeout failures, telling assistive technology the typing was malformed when it was not; it is now driven by the `weak_password` code alone.
  - `[low]` `[patch]` The blank-submit guard used `=== ''` where `LoginScreen` uses `.trim()`, so a whitespace-only password was submitted. Matched, with the untrimmed value still sent.
  - `[low]` `[patch]` Two docstrings claimed `apps/web` branches on `PASSWORD_CHANGE_REQUIRED` when nothing imports it; both now say what is true.
  - `[low]` `[patch]` The new envelope codes were duplicated across Python and TypeScript with no parity test, unlike `User` and `ErrorEnvelope`. `error-code-parity.test.ts` added.
  - `[low]` `[patch]` The audit deferral named only the password change; the silent revocation of every session a user holds is a separate security event and now says so.
  - `[low]` `[patch]` DESIGN.md's `force-password-change-form` block names `background: {colors.surface}` and no rule applied it. Applied and asserted; the block's `success-foreground` contradiction with EXPERIENCE.md:88 is now recorded rather than resolved silently.
  - `[low]` `[patch]` A README sentence was appended to an existing line, leaving a 176-character line in a block wrapped at ~98. Reflowed.

### 2026-09-17 — Review pass (follow-up)

- intent_gap: 0
- bad_spec: 0
- patch: 10: (high 0, medium 1, low 9)
- defer: 9: (high 1, medium 4, low 4)
- reject: 12
- addressed_findings:
  - `[medium]` `[patch]` `README.md` and `infra/README.md` both told an operator that a
    lapsed credential "has to be reissued" with `make reseed-admin` — for the exact sequence
    (`signs in on day one, comes back on day four`) that `reseed_administrator` refuses, since
    it counts a recorded sign-in as a claim. Both files now say the change has to be finished
    in the sitting it starts in, name the one sequence nothing rescues, and point at the
    deferred `seed.py` work rather than promising a command that declines.
  - `[low]` `[patch]` The previous pass recorded the over-long `README.md` line as reflowed; it
    was not — the new sentences were wrapped and the pre-existing `Full operator notes —` clause
    was left glued to the end at 162 characters. Reflowed for real; the block is now 88–99.
  - `[low]` `[patch]` The `409 password_change_not_required` was the one response on this
    endpoint whose `no-store` nothing asserted, and `api_error_handler` rebuilds the response
    from `ApiError.headers`, so the dependency's header never reaches a rejection. Assertion
    added; proven by deleting `headers=NO_STORE` from `_already_claimed()` and watching the
    test fail.
  - `[low]` `[patch]` `MAX_PASSWORD_FIELD_LENGTH`'s comment claimed it "refuses a body sent to
    occupy memory". Pydantic's `max_length` runs after Starlette has read the whole body and
    after JSON parsing, so it bounds what gets hashed, not what gets received. The comment now
    says which of the two it is, and that a real body limit belongs at an edge that does not
    exist yet.
  - `[low]` `[patch]` An `APIRoute` declared with only `HEAD`/`OPTIONS` was filtered down to an
    empty method list and dropped from `_api_routes` entirely — neither gate-checked nor
    allowlisted, the silent omission the guard's own docstring says cannot happen. It now fails
    naming the route, with a negative control (`test_the_walk_refuses_a_route_that_declares_only_framework_methods`)
    proven by disabling the raise.
  - `[low]` `[patch]` The same docstring justified its `original_router` recursion with
    "FastAPI wraps an included router rather than flattening its routes". `create_app()` uses
    `include_router`, which copies routes into the parent, so that branch never runs. Rewritten
    to say what the recursion is actually defence against (a *mounted* router).
  - `[low]` `[patch]` `error-code-parity.test.ts`'s completeness check extracted constants with
    `/^export const ([A-Z_]+) = '([a-z_]+)';$/gm`, so a constant the formatter rewrapped, or one
    written with double quotes, was silently dropped from the comparison — the "passes forever"
    failure the file's first test exists to prevent, one level up. Pattern broadened to any
    exported string constant.
  - `[low]` `[patch]` `test_the_update_itself_refuses_an_already_claimed_row` patched
    `auth.password_rule_violation` by hand with two `type: ignore`s and a `try/finally` that does
    not cover every teardown path, in a suite that already takes `monkeypatch`. Moved to
    `monkeypatch.setattr`.
  - `[low]` `[patch]` `test_the_rule_table_cannot_be_edited_in_place` justified the
    `MappingProxyType` with "imported by `apps/api` and by `infra`'s seed … three packages".
    `PASSWORD_RULES` is imported by two test suites and no production module. The guard is worth
    keeping; the comment now states the reason that applies.
  - `[low]` `[patch]` `App.tsx`'s `if (screen === 'login' || user === null)` carries a disjunct
    that is unreachable at runtime and exists only to narrow `user` for TypeScript. Nothing said
    so, and deleting it as redundant breaks the build. Commented.

**Rejected, with reasons worth keeping.** That `require_claimed_user` is declared by no shipped
route is this epic's shape, not an omission — the five routes that exist are the five the
allowlist names, and the guard exists to bind Epic 2's first real route. `PASSWORD_CHANGE_REQUIRED`
being exported but unbranched in `apps/web` is recorded in its own docstring for the same reason.
The absent confirm field and the absent hidden `username` input are DESIGN.md:219's single-field
form, not defects. The I/O matrix's expired-credential row now under-describes an endpoint that
checks the deadline itself, but the matrix is inside the frozen `<intent-contract>` and the
divergence is the previous pass's deliberate `[high]` security fix, recorded there. The remaining
rejects were a sub-second TOCTOU between the expiry read and the UPDATE (closing it would turn a
401 into a 409), a duplicated `NO_STORE` that is harmless, a focus assertion whose replacement
covers the same mechanism through a longer chain, and a docstring's "no committed credential"
claim against test strings that are not credentials.

**Not touched, by instruction.** Two findings land in `deferred-work.md`, which this run does not
own: DW-40's heading is truncated mid-sentence at "against a" (the full sentence survives in this
spec's frontmatter `summary`), and DW-36 still names only `POST /auth/login` although
`POST /auth/password` is now a second cookie-authenticated, account-mutating POST behind nothing
but `SameSite=Strict`. Both are recorded here instead.

### 2026-09-17 — Review pass (third)

- intent_gap: 0
- bad_spec: 0
- patch: 6: (high 0, medium 1, low 5)
- defer: 0
- reject: 19
- addressed_findings:
  - `[medium]` `[patch]` `infra/README.md` named the one unrecoverable sequence — sign in on the
    temporary credential, come back after the deadline — and then withheld the recovery, saying
    only that it is "a manual `UPDATE` by someone with database access". An operator runbook that
    names a trap has to carry the way out of it. It now gives the statement
    (`UPDATE users SET last_login_at = NULL … AND must_change_password`), verified against
    `_SELECT_UNCLAIMED_ADMINISTRATOR`'s predicate, says why the `AND must_change_password` is
    load-bearing rather than decoration, and says that the write has no audit trail behind it.
  - `[low]` `[patch]` The `409` was driven only from an account that was never flagged and from a
    monkeypatched race. The duplicate request a browser actually produces — a second
    `POST /auth/password` on the fresh cookie the first one returned — was untested, and it is the
    path that reaches the guard rather than the `UPDATE`'s predicate. Test added, asserting the
    refusal costs the caller neither the password they just set nor their session.
  - `[low]` `[patch]` `set_password`'s `row is None` branch (the row deleted between the session
    lookup and the credential read) was a phantom: no test reached it, and deleting the three
    lines turned the case into a `500` with a traceback and a cookie the server no longer honours,
    on the one screen with no sign-out control. The `sessions` foreign key cascades, so the branch
    cannot be reached by deleting a user before the request — the test narrows the statement
    instead. Proven load-bearing by disabling the branch and watching it fail.
  - `[low]` `[patch]` `test_the_guard_catches_a_route_that_forgets_the_gate` re-implemented the
    offender comprehension instead of calling it, so the negative control did not exercise the
    expression the real guard runs. Extracted `_ungated_routes`, called by both.
  - `[low]` `[patch]` `ForcedPasswordChangeScreen.module.css` claimed `.panel`'s radius, padding
    and hairline were "DESIGN.md's Card treatment". DESIGN.md:208's Card also carries the
    navy-tinted shadow (`--elevation-card`, which `AppShell` uses) and is defined as the container
    for candidates, products and table rows — not a form panel. The comment now says what is
    borrowed, what is not, and that reaching for the shadow here would be a design change rather
    than a completion.
  - `[low]` `[patch]` `error-code-parity.test.ts`'s `invented` set exempts `API_PREFIX` while the
    comment above it accounted only for "network, timeout, malformed" — the exemption that is not
    an error code at all was the one left unexplained. Comment corrected.

**Rejected, with reasons worth keeping.** Three findings restated decisions already taken and
recorded: the sub-second TOCTOU between the expiry read and the `UPDATE` (closing it turns a `401`
into a `409`), the absence of a shipped route declaring the gate (this epic's shape — the five
routes that exist are the five the allowlist names), and `POST /auth/password`'s CSRF exposure
(DW-36). Four more are already in the ledger as deferred work and were reported again as if new:
the unthrottled Argon2id cost (DW-40), the expired-credential copy on the login screen (DW-43),
the `LoginScreen` duplication (DW-45), and a client-side expiry check, which is the same copy
decision seen from the other end.

The rest did not survive checking. `changePassword` mapping `409` to `signed-out` was reported as
signing a user out of a good session after their own successful change — but a successful change
revokes every other session, so a second actor gets `401`, not `409`, and this tab has already
swapped to the shell. `read(join(API, where?.file ?? ''))` was reported as an `EISDIR` on a
missing row; `expect(where).toBeTruthy()` runs first and `it.each` iterates `PYTHON`'s own keys, so
the branch is unreachable TypeScript narrowing. "Nothing asserts an allowlisted route still
requires a session" is true of that file and false of the suite — `test_session_lookup.py` pins it.
`PASSWORD_RULES` not being re-exported from `shared_schema/__init__.py` follows the convention
`MIN_PASSWORD_LENGTH` and `MAX_PASSWORD_LENGTH` already set: callables and types are re-exported,
constants are read from the submodule. `infra/rocell_infra/config.py` restating the length rules in
operator-facing prose reads the same two constants, so the boundary cannot drift from the API's.
The parity test checking only TypeScript→Python was left as it is: the reverse needs a heuristic
that can tell a code constant from a message constant in Python source, and `INVALID_CREDENTIALS`,
`NO_SESSION` and `ALREADY_CLAIMED` sit side by side in the same files. The remaining rejects asked
the screen for things nothing specifies and DESIGN.md:219 argues against — a sign-out control on a
screen whose whole point is that it has none, the account's own email, a password-rule hint before
the first attempt, a notice that other sessions were revoked, and a success signal EXPERIENCE.md:88
forbids.

## Design Notes

**Why the gate is a dependency plus a route-table test, not a middleware.** Middleware would have to know which paths are exempt by string matching, and `/auth/session` and `/auth/logout` *must* stay reachable while the flag is set — the first is how the front end learns to show the screen at all, the second is how a user leaves. A path list inside middleware is a second copy of the routing table that drifts the day someone adds a route. A dependency states the requirement where the route is declared, and the guard test inverts it: the allowlist is written down once, in a test, and everything else must opt in. That is what makes `lookup_session`'s docstring obligation enforceable rather than aspirational.

**Why every session of the user is deleted on a successful change.** A temporary credential travels by whatever channel an Administrator used — spoken, written down, messaged. The password change is the moment that credential stops being trusted, and any session issued on it has to go with it, including one opened on another device by someone who saw the note. This is credential rotation scoped to one user acting on their own account, not the session listing and bulk revocation Story 1.5 owns. The caller gets a fresh token in the same response, so the change does not bounce them to the login screen.

**Why reuse of the temporary password is refused but reuse of an older one is not.** EXPERIENCE.md:87 names exactly two rules: length and reuse of the temporary password. A general password-history rule needs a history table, a retention policy and a decision about how many — none of which the epic asks for, and all of which are cheap to add later against a schema that does not yet exist. The check here is one `verify_password` call against the digest already in hand.

**Why a single field.** DESIGN.md:219 specifies a single-field form. EXPERIENCE.md:87's heading says "Weak/mismatched password", but its body enumerates the rules as "length, reuse of the temporary password" — no mismatch rule is stated anywhere, and a confirm field with no rule behind it is a second thing to type for no enforcement. The input is `type="password"` per the component spec; a reveal toggle is not specified and is not invented here.

```python
# apps/api/api/dependencies.py — the shape, not the code.
PASSWORD_CHANGE_REQUIRED = "password_change_required"

def require_claimed_user(user: Annotated[User, Depends(current_user)]) -> User:
    """Every route that serves real data declares this (AGENTS.md line 18)."""
    if user.must_change_password:
        raise ApiError(PASSWORD_CHANGE_REQUIRED, SET_A_PASSWORD_FIRST, status_code=403,
                       headers=NO_STORE)
    return user
```

## Verification

**Commands:**
- `make lint` — expected: exit 0 (ruff check, ruff format --check, oxlint --deny-warnings, tsc --noEmit).
- `make test` — expected: exit 0; the new `apps/api` database tests run against the ephemeral cluster or skip with the same "no PostgreSQL available" reason (DW-18/DW-39).
- `uv run pytest apps/api/tests/test_password_change.py apps/api/tests/test_forced_change_gate.py -q` — expected: exit 0.
- `uv run pytest apps/api/tests/test_source_guards.py shared/schema/tests -q` — expected: exit 0, including the one-hasher and one-sessions-reader guards over the new modules.
- `npm --prefix apps/web run test` — expected: exit 0, including the forced-change screen, the extended gating cases and the styling-wiring colour assertions.
- `git grep -nE "localStorage|sessionStorage|document\.cookie|indexedDB" apps/web/src` — expected: matches only inside the guard test that forbids them.
- Prove each new guard load-bearing by removing what it guards: drop `require_claimed_user` from the test route (the 403 case fails), clear the `temp_credential_expires_at = NULL` from the update (the database assertion fails), remove `delete_sessions_for_user` (the old-cookie assertion fails), and delete the `App.tsx` branch (the gating test renders the shell).

**Manual checks (if no CLI):**
- Invoke the `ui-ux-pro-max` skill and run its pre-delivery checklist against the new screen before calling this story done (epic context: required for every UI story).
- `make migrate` with `SEED_ADMIN_*`, then `make dev`: sign in as the seeded Administrator. The change screen is the only thing rendered — no app bar, no nav, no sign-out — a short password shows the rule-naming inline error, and an accepted one lands on the shell with no interstitial. Reload: the shell is still there and the screen does not return.

## Auto Run Result

Status: done
Blocking condition: none

### What the story delivers

The forced password change, and the gate that makes it unavoidable. `POST /auth/password` lets the
holder of an admin-issued temporary credential set a real password — enforcing the length rules
from `shared_schema`, refusing reuse of the temporary one, refusing a credential whose 72 hours
have passed, rotating every session the user held, and answering `409` for an account that is
already claimed. `require_claimed_user` refuses every other authenticated route with
`403 password_change_required`, and a route-table guard test makes that self-enforcing: anything
outside a written-down allowlist must declare the gate, and a route the walk cannot classify fails
the run rather than being skipped. `apps/web` renders a chrome-less single-field change screen in
place of the shell for as long as the flag is set — no app bar, no navigation, no sign-out, no
dismissal, and with no router there is nowhere else to navigate to.

### Files changed

- `apps/api/api/auth.py` — `POST /auth/password`: rule check, reuse check, deadline re-check, the
  single-transaction update, session rotation and the fresh cookie.
- `apps/api/api/dependencies.py` — new: `current_user`, `require_claimed_user`, and the 401
  primitives both auth modules now share.
- `apps/api/api/sessions.py` — `delete_sessions_for_user`; `lookup_session`'s docstring now names
  the dependency that discharges its obligation.
- `apps/api/api/main.py` — the new envelope statuses wired through the existing handlers.
- `shared/schema/shared_schema/passwords.py`, `__init__.py` — `PASSWORD_RULES` and
  `password_rule_violation`, so the length rules have exactly one statement.
- `apps/web/src/screens/ForcedPasswordChangeScreen.tsx` + `.module.css` — the change screen.
- `apps/web/src/App.tsx` — the gate branch and the screen-keyed focus effect.
- `apps/web/src/auth/SessionProvider.tsx`, `api/client.ts` — `changePassword` and the new codes.
- Tests: `test_password_change.py`, `test_forced_change_gate.py`, extensions to `test_login.py`,
  `auth-gating.test.tsx`, `styling-wiring.test.ts`, `test_passwords.py`, and new
  `forced-password-change.test.tsx` and `error-code-parity.test.ts`.
- `README.md`, `infra/README.md` — the operator account of what a reissued credential is good for,
  the one sequence `make reseed-admin` cannot rescue, and the manual statement that clears it.

### Review findings

Three passes. The first applied 14 patches (1 high, 6 medium, 7 low) and deferred 1. The second
applied 10 (0 high, 1 medium, 9 low), deferred 9 and rejected 12. This third pass applied 6
(0 high, 1 medium, 5 low), deferred nothing and rejected 19 — see the Review Triage Log for all
three. Nothing was triaged `intent_gap` or `bad_spec` in any pass, so the spec was never amended
and the code was never re-derived.

The third pass produced no new deferrals because the findings that were real and out of scope were
already in the ledger (DW-40, DW-43, DW-45) or already adjudicated in the second pass's rejects.
Its one substantive change is the operator recovery in `infra/README.md`: the previous pass
correctly stopped promising `make reseed-admin` for a lapsed, signed-in Administrator, but left the
runbook naming an unrecoverable state without the statement that recovers it.

Follow-up review recommendation: **true**. Counting only this pass's patched findings — high 0,
medium 1, low 5 — the score is `3 × 1 + 1 × 5 = 8`, at or above the threshold of 5.

### Verification performed

- `make lint` — exit 0 (ruff check, ruff format --check, oxlint --deny-warnings, tsc --noEmit).
- `make test` — exit 0: 407 pytest (up from 405, the two tests this pass added), 443 vitest across
  12 files. PostgreSQL was available, so the database tests ran rather than skipping.
- `uv run pytest apps/api/tests/test_password_change.py apps/api/tests/test_forced_change_gate.py`
  — exit 0, 57 tests.
- The new deleted-row test proven load-bearing by disabling the branch it covers (`if row is None`
  → `if False`): `test_a_row_that_disappears_before_the_credential_read_is_refused` fails with the
  500 the branch exists to prevent. Mutation reverted and the suite re-run green.
- Frontmatter re-parsed as YAML after this pass: `deferred` is unchanged at 10 items, `status` is
  `done`, `followup_review_recommended` is `true`.

### Residual risks

- **An Administrator can still lock themselves out** by signing in on the seeded temporary
  credential and not finishing the change within 72 hours: login refuses the expired credential,
  the change screen refuses the password, and `make reseed-admin` refuses the account because a
  sign-in was recorded. `infra/README.md` now carries the statement that clears the recorded
  sign-in so the reissue can run, but it is a raw `UPDATE` with no audit trail behind it (Story
  1.12) and it needs database access. The code fix is deferred against `infra/rocell_infra/seed.py`,
  which this spec marks read-only.
- The gate has no shipped route to refuse yet. Its behaviour is exercised only on routes declared
  inside the test file, and the route-table guard iterates an empty candidate set today. Epic 2's
  first route that serves real data is where it stops being theoretical.
- `apps/web` does not revalidate a session the server stopped honouring (DW-37), and nothing
  branches on `403 password_change_required` client-side, so an Administrator re-flagging a
  signed-in user leaves the shell mounted until a reload. The server-side control is unaffected.
- The expired-credential path still answers the generic `401 unauthorized`, so a user whose 72
  hours lapse mid-change lands on the login screen reading a sentence about a typo (DW-43). The
  server side is correct; the copy is the open half.
- `deferred-work.md` is owned by the orchestrator and was not touched by this run.
