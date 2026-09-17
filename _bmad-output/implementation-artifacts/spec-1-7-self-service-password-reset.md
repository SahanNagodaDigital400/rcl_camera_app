---
title: 'Story 1.7 — Self-Service Password Reset'
type: 'feature'
created: '2026-09-18'
baseline_revision: '68c0d876f809a5c3f9b796ba3e76d2da6b4b1248'
status: 'done'
review_loop_iteration: 0
followup_review_recommended: true # score 14 (0 high, 1 medium, 11 low patched this pass); see Auto Run Result
context:
  - '{project-root}/AGENTS.md'
  - '{project-root}/_bmad-output/planning-artifacts/architecture/architecture-rcl_camera_app-2026-08-30/ARCHITECTURE-SPINE.md'
  - '{project-root}/_bmad-output/planning-artifacts/ux-designs/ux-rcl_camera_app-2026-09-08/EXPERIENCE.md'
  - '{project-root}/_bmad-output/planning-artifacts/ux-designs/ux-rcl_camera_app-2026-09-08/DESIGN.md'
warnings: ['oversized']
deferred:
  - summary: >-
      `_CHANGE_PASSWORD` pins the claimed flag but not the digest it just
      verified, so two concurrent changes both write and the loser is told the
      change succeeded.
    evidence: |-
      `_SELECT_PASSWORD_HASH` runs outside `conn.transaction()`, and the write's
      only predicate is `AND NOT must_change_password`. Two posts arriving
      together verify the same stored digest, both match the row, and the last
      writer wins — the first caller gets a `200` and a `User` body for a password
      that is not the live one. The same argument the `_CHANGE_PASSWORD` comment
      makes for the flag ("a property of the statement rather than of a check
      taken earlier") applies to the digest, and `AND password_hash = %s` would
      give it. Closing it means deciding what a third empty-`RETURNING` arm
      answers, which is a contract decision this story's intent does not make;
      the realistic second trigger — an Administrator resetting a password under
      the user — arrives with Story 1.10.
    location: >-
      apps/api/api/auth.py (_CHANGE_PASSWORD)
    severity: medium
  - summary: >-
      A `403 password_change_required` from the write's race arm renders on
      Account Settings as a neutral form error, with no route to the forced-change
      screen and no refresh of the cached user.
    evidence: |-
      `fieldFor()` in `AccountSettingsScreen.tsx` maps that code to `null`, so the
      gate's sentence appears as an unattributed form error while
      `currentScreen()` keeps the user on Account Settings — the cached
      `must_change_password` is still false until the next `/auth/session`
      revalidation. It is honest and actionable copy, and the branch is currently
      unreachable in the product: nothing sets `must_change_password` back to true
      except a manual UPDATE. Stories 1.8 and 1.10 are what make an Administrator
      able to reissue, and whether the front end should re-fetch the session or
      route to the forced-change screen is a decision that belongs with them.
    location: >-
      apps/web/src/screens/AccountSettingsScreen.tsx (fieldFor)
    severity: medium
  - summary: >-
      DW-40 is now a three-endpoint problem — `POST /auth/password/change` adds a
      64 MiB Argon2id verify plus a hash per call, reachable by any live session
      and bounded by nothing.
    evidence: |-
      The handler spends one `verify_password` on every call and one
      `hash_password` on every success, and is sync, so FastAPI runs it in a
      threadpool defaulting to 40 workers against `POOL_MAX_SIZE = 10` (DW-34).
      epics.md scopes Story 1.6's counters to login, so the spec forbids closing
      it here and the docstring records it — but DW-40's own text names two
      endpoints and predates this one. Recorded as new evidence for that entry:
      the memory amplification is now three deep and no test or ceiling
      acknowledges it.
    location: >-
      apps/api/api/auth.py (change_password)
    severity: medium
  - summary: >-
      The two-field form gives a password manager no username to associate, so
      managers routinely fail to offer to update the stored credential.
    evidence: |-
      The form carries `autocomplete="current-password"` and `"new-password"` and
      no field carrying the identity. Chrome, Safari and 1Password commonly need
      an associated username — a visually-hidden readonly input with
      `autocomplete="username"` — before they offer to *update* a saved entry
      rather than save a second one. The user then changes their password and the
      manager keeps serving the old one, which is the friction FR-5 exists to
      remove. `hidden` is not the fix (managers skip it) and jsdom cannot verify
      any of it, so the correct shape wants checking on a real browser — the same
      kind of task as DW-51.
    location: >-
      apps/web/src/screens/AccountSettingsScreen.tsx
    severity: medium
  - summary: >-
      The change signs the user out on every other device and the screen never
      says so.
    evidence: |-
      `test_every_other_device_is_signed_out` proves the server does it and
      README calls it "the point of it", but the whole of what the user is told is
      "Saved." — the save indicator EXPERIENCE.md specifies. Someone changing a
      password because they believe a colleague has it gets no confirmation that
      the thing they actually wanted has happened. Adding a factual line is small
      and in EXPERIENCE.md's register, but it is copy no file in the pair
      specifies, and the Save indicator row is what the surface was built to.
    location: >-
      apps/web/src/screens/AccountSettingsScreen.tsx
    severity: medium
  - summary: >-
      Anyone holding a live session cookie can guess `current_password` without
      limit, so a borrowed unlocked phone is a path to permanent account
      takeover rather than only to CPU burn.
    evidence: |-
      `change_password` spends a `verify_password` per call and answers
      `403 invalid_current_password`. Nothing counts the failures: no
      `login_attempts` row, no `users.locked_until` check, no ceiling, and no
      record anywhere until Story 1.12's audit log. The existing DW-40 note
      frames this endpoint as the third Argon2id consumer — a memory-amplification
      problem — which is a different property from the one here: login refuses an
      attacker after ten tries and this route refuses them never. The intent's
      Never list forbids throttling in this story ("Story 1.6 scoped throttling
      to login"), so it cannot be closed here, but a counter keyed on the session
      or the user is a smaller decision than DW-40's address-vs-account question
      and could land ahead of it.
    location: >-
      apps/api/api/auth.py (change_password)
    severity: medium
  - summary: >-
      "The API's sentence, verbatim" is asserted only against sentences retyped
      into the test files, so the API's copy and the strings the suite checks can
      drift apart with everything green.
    evidence: |-
      `error-code-parity.test.ts` spans the API/web boundary for error *codes*
      and nothing spans it for *messages*. `account-settings.test.tsx` builds its
      `ApiRequestError`s from literals authored in that file, and the new
      real-provider case stubs `WRONG_CURRENT`, also a literal. At run time the
      screen does render whatever the API sent, so this is a test-fidelity gap
      rather than a product defect: change `CURRENT_PASSWORD_WRONG` or
      `MIN_PASSWORD_LENGTH` in Python and the suite keeps passing while its
      claim to be checking the API's wording stops being true. Closing it wants
      a message row in the parity test, which is a decision about how much of
      EXPERIENCE.md's copy belongs under a build-time guard.
    location: >-
      apps/web/src/__tests__/error-code-parity.test.ts
    severity: low
  - summary: >-
      `ROUTE_WORDS` is three words, so a recovery surface named anything but
      reset, forgot or recover passes the route-table guard.
    evidence: |-
      `/auth/magic-link`, `/auth/otp` and `/auth/unlock` would all serve exactly
      the signed-out recovery FR-5 forbids and clear
      `test_the_route_table_holds_no_recovery_path`. The vocabulary was not
      widened in this pass on purpose: `reissue` is the obvious next candidate
      and is also the correct name for the Administrator route Stories 1.8 and
      1.10 add, so a wider list risks the same false accusation the bare `boto3`
      pattern was just narrowed to avoid. Widening it safely means deciding the
      word list against the routes those stories will actually serve.
    location: >-
      apps/api/tests/test_no_password_reset.py (ROUTE_WORDS)
    severity: low
  - summary: >-
      A change can land on the server while the screen reports it as failed,
      leaving the user typing a password that is no longer theirs.
    evidence: |-
      `changeOwnPassword` stores the response through `asUser`, which throws on
      a body it does not recognise — and `apiRequest` throws on a transport
      failure. Either way the write, the revocation and the fresh cookie have
      already happened: the browser holds the new session, the digest is the new
      one, and the screen shows a rejection. The user then retypes the *old*
      password and is answered `invalid_current_password`, with no way to tell
      which of the two passwords is live. Closing it means re-fetching
      `/auth/session` on a failure whose status is not 401 — which the spec's
      own task list forecloses ("Errors propagate untouched … nothing has to be
      rescued here"), so it is a contract decision rather than a patch. The
      window is narrow today: the only reachable trigger is a transport failure
      between the commit and the response.
    location: >-
      apps/web/src/auth/SessionProvider.tsx (changeOwnPassword)
    severity: medium
  - summary: >-
      The mail-transport guard reads only a fixed extension set and a fixed
      package vocabulary, so a transport reached for in a Dockerfile, a shell
      script or an SMS SDK passes it.
    evidence: |-
      `SCANNED_EXTENSIONS` has no `.tf`, no `.sh`, and cannot match an
      extensionless file at all — `Dockerfile`, `Makefile`, a compose override —
      although `CLAUDE.md` puts IaC in `infra/`, which is the same argument the
      file already makes for `.yml`/`.yaml`. Separately, `_TRANSPORTS` is a mail
      vocabulary and FR-5's clause is about *recovery*: an SMS one-time code
      (`twilio`, `vonage`, `messagebird`, `publish_sms`) is exactly the
      signed-out path the clause forbids and reads clean through every check in
      the file. Both are the same decision as DW-74's: widening a word list
      safely means deciding it against the surfaces later stories will actually
      build, and a list widened on a guess is the false accusation the bare
      `boto3` pattern was already narrowed to avoid.
    location: >-
      apps/api/tests/test_no_password_reset.py (SCANNED_EXTENSIONS, _TRANSPORTS)
    severity: low
---

<intent-contract>

## Intent

**Problem:** FR-5 has no implementation. The product's only password write is
`POST /auth/password`, which exists to exchange an admin-issued *temporary* credential for a real
one and refuses a claimed account with `409 password_change_not_required` — its own docstring names
Story 1.7 as the owner of the missing half. A member of staff who wants to change a password they
already chose has no route, no screen, and no option but to ask an Administrator to reissue a
temporary credential, which is the escalation FR-5 exists to remove.

**Approach:** A second, gated endpoint — `POST /auth/password/change` — that takes the caller's
current password and a new one, proves the current one against the stored digest before it does
anything else, and replaces the digest. It reuses `shared_schema.passwords` for the rules and
`api.sessions` for the revoke-and-reissue that `POST /auth/password` already performs, so the two
password writes differ in their contract and not in their consequences. `apps/web` gains an Account
Settings surface reached from the app bar, and the "no signed-out path" half of the clause is made
enforceable by a guard test rather than by the absence of code.

## Boundaries & Constraints

**Always:**
- **The current password is proved first.** `verify_password` against the stored digest runs before
  the new password's rules are read, before any comparison between the two, and before
  `hash_password`. A caller who has not proved the current password learns nothing about the new
  one, and no write is reachable without it.
- **A wrong current password is never a `401`.** `apps/web`'s `apiRequest` fires
  `notifyUnauthorized` on *status* 401, and `SessionProvider` answers it by dropping the shell to
  the login screen — so answering 401 here would sign a user out for mistyping a field.
  `403 invalid_current_password`, which no observer watches.
- **The route declares `require_claimed_user`**, so it is not added to
  `ALLOWED_WITHOUT_THE_GATE`. A user still holding a temporary credential belongs on
  `POST /auth/password`; answering both from one place would make the forced change skippable.
- **The change revokes every session of its user and issues the caller a fresh one**, inside the
  same transaction as the digest write — `POST /auth/password`'s behaviour exactly. A password
  changed because it may be known to somebody else must not leave that somebody else's session
  alive, and the caller must not be bounced to the login screen by their own change.
- **The rules stay in `shared_schema.passwords`.** `password_rule_violation` is the one statement
  of them (its docstring already names this story), answered with the existing `WEAK_PASSWORD`
  code and the rule-naming message EXPERIENCE.md:87 requires.
- Parameterized SQL only, and the new statement's `RETURNING` list is the `User` column list
  `_RECORD_LOGIN` and `_SET_PASSWORD` already carry, character for character.

**Block If:**
- Making the new route pass `test_forced_change_gate.py` turns out to require an entry in
  `ALLOWED_WITHOUT_THE_GATE` — that would mean a password write reachable on an unclaimed
  credential, and neither the gate nor FR-2 may be relaxed without a human.
- Revoking sibling sessions turns out to require changing what `POST /auth/login` or
  `POST /auth/password` *return*, rather than being expressible through the existing
  `delete_sessions_for_user` / `issue_session` pair.

**Never:**
- **No signed-out recovery of any kind.** No reset route, no token, no link, no mail transport —
  not a dependency, not an import, not a stub. FR-5 and AGENTS.md: a user who has forgotten their
  password goes through an Administrator. The login screen's existing "no forgot-password link"
  test stands; this story adds the API-side half.
- **No throttling of the new endpoint.** It is a second Argon2id-backed authenticated endpoint and
  therefore a direct extension of **DW-40**, which is still open and explicitly a decision about
  what a counter would be keyed on. Story 1.6 scoped throttling to login.
- **No audit entry.** Story 1.12 owns the write path and owes this endpoint two entries (the change
  and the silent revocation), exactly as it owes `POST /auth/password` two. No private log path is
  built in the meantime.
- **No clearing of `login_attempts` or `users.locked_until`.** A lock is a property of the address
  under attack, not of the credential, and a signed-in user clearing it would hand an attacker a
  way to reset the ladder (see DW-57 for the related reissue gap).
- No schema change, no migration, no new `User` field. Nothing about this story is persisted beyond
  `users.password_hash` and `updated_at`.
- **No confirm-password field, no reveal toggle, no strength meter** — the same three absences
  `ForcedPasswordChangeScreen` documents, for the same reasons.
- No role-conditional navigation. The app-bar entry below is the interim door to the one surface
  that exists; the tab bar and sidebar arrive with the surfaces they point at.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Happy path | claimed user, correct current password, valid new one | `200` with the `User` body; digest replaced; `updated_at` moved; a fresh session cookie is set | No error |
| Immediacy | the change has just returned `200` | the old password is refused at `POST /auth/login` and the new one is accepted, with no sign-out in between | — |
| Wrong current password | claimed user, bad `current_password` | `403` `invalid_current_password`; nothing is written; no session is touched; no `hash_password` runs | The distinct 403, never `unauthorized` |
| New password breaks a length rule | current password correct, new one empty / <12 / >128 | `422` `weak_password` with the sentence naming the rule; nothing written | `password_rule_violation`'s message verbatim |
| New password equals the current one | both fields identical and correct | `422` `weak_password`, "must be different from your current one"; nothing written | A rule, answered before any hashing |
| Rule check order | wrong current password **and** a 4-character new one | `403` `invalid_current_password` — the new password is never assessed | The unproven request is refused first |
| Not signed in | no cookie | `401` `unauthorized`, cookie cleared | `current_user`'s existing refusal |
| Signed in on a temporary credential | `must_change_password = true` | `403` `password_change_required` — the forced change is the route for that account | `require_claimed_user` |
| Row vanished mid-request | user deleted between the session lookup and the write | `401` `unauthorized`; the transaction unwinds having written nothing | `not_signed_in()` |
| Flag flipped mid-request | an Administrator reissues a temporary credential between the gate and the write | `403` `password_change_required`; nothing written | The statement's `AND NOT must_change_password` matches no row |
| Other devices | the user holds sessions on two devices | both are revoked; the caller's request returns holding a new cookie and stays signed in | — |
| Oversized field | either field over `MAX_PASSWORD_FIELD_LENGTH` | `422 validation_error` from the request model; nothing is hashed | Bounded before the handler |
| Unknown body key | an extra JSON key | `422 validation_error` (`extra="forbid"`) | — |
| `apps/web` shows the refusal | `invalid_current_password` | the API's sentence, with **the current-password field** marked invalid and focused; the new-password field keeps its value | — |
| `apps/web` shows the refusal | `weak_password` | the API's sentence, with **the new-password field** marked invalid and focused | — |
| `apps/web` on success | `200` | both fields clear, the inline save indicator reads "Saved.", and the screen stays where it is | No navigation, no toast |

</intent-contract>

## Code Map

**Read-only sources of truth (do not edit):**
- `_bmad-output/planning-artifacts/epics.md` **lines 257–268** — Story 1.7's acceptance clauses
  verbatim. Also 244–256 (1.6, which fixed the login-only scope of throttling) and 296–307 (1.10,
  which owns an Administrator editing someone else's account).
- `_bmad-output/specs/spec-rcl_camera_app/functional-requirements.md` **FR-5** (line 15) — "A
  signed-in user can change their own password at any time. No reset emails — a locked-out or
  forgotten-password user goes through an Administrator." **FR-2** (line 9) is the gate.
- `EXPERIENCE.md` **line 32** (the Account Settings IA row: reached from the nav's profile entry,
  purpose "Change own password (FR-5)", Staff and Admin), **line 87** (a rejected password names
  the rule that failed, never a generic message), **lines 50–57** (voice: short, factual, no
  exclamation marks).
- `DESIGN.md` **line 219** (the force-change form, whose single-field shape this screen deliberately
  does *not* copy — it has two fields because it proves one), the **Save indicator** bullet
  (muted at rest, `{colors.primary}` on "Saved.", inline near its trigger and never a corner
  toast), **Button (primary)** (accent fill, navy foreground, exactly one per screen) and
  **Button (secondary)** (navy outline — the Back control).
- `AGENTS.md` — Argon2id only; server-side authorization on every endpoint; no committed
  credentials in fixtures; security paths need failure-case tests.
- `deferred-work.md` — **DW-40** (`POST /auth/password` is an Argon2id endpoint the gate cannot
  close; this story adds a second one and does not close it), **DW-34** (`POOL_MAX_SIZE = 10`
  behind a 40-worker threadpool), **DW-17** (`users` has no BEFORE UPDATE trigger, so `updated_at`
  is set by hand), **DW-57** (a reissue does not clear a lock — the reason this story clears
  nothing either).

**Files that already exist and constrain the shape:**
- `apps/api/api/auth.py` — the module this grows. `set_password` (line ~755) is the template for
  everything below: `response.headers.update(NO_STORE)`, a `_SELECT_*` by `user.id`, the
  rule check before any verify, `hash_password` **outside** the transaction, then
  `with conn.transaction():` → `UPDATE ... RETURNING` → `delete_sessions_for_user` →
  `issue_session` → `set_session_cookie` → `User.model_validate`. `_weak_password(rule)` (line 338)
  is the one constructor for a refused password and is reused unchanged. `WEAK_PASSWORD`,
  `PASSWORD_CHANGE_NOT_REQUIRED`, `ACCOUNT_LOCKED`, `MAX_PASSWORD_FIELD_LENGTH` are the
  module-level `NAME = "..."` constants the parity test reads by regex. `_RECORD_LOGIN` (line 200)
  and `_SET_PASSWORD` (line 724) carry the eleven-column `RETURNING` list — the new statement's
  must match both exactly.
- `apps/api/api/dependencies.py` — `require_claimed_user` (the gate the new route declares),
  `current_user`, `not_signed_in()`, `NO_STORE`, `PASSWORD_CHANGE_REQUIRED`. The 401 primitives
  live here because both modules need them.
- `apps/api/api/sessions.py` — `delete_sessions_for_user(conn, user_id) -> int`,
  `issue_session(conn, user_id) -> str`, `set_session_cookie(response, raw_token)`. Used as-is; no
  change to this module.
- `shared/schema/shared_schema/passwords.py` — `password_rule_violation` (its docstring already
  says "Story 1.7 reuses it … rather than restating the rules"), `verify_password`,
  `hash_password`, `MIN_PASSWORD_LENGTH`/`MAX_PASSWORD_LENGTH`. **Read-only** — no new rule is
  added here; "different from the current one" is about one account's digest, not about the string,
  exactly as the temporary-reuse rule is.
- `apps/api/api/main.py` — `STATUS_CODES` maps `403: "forbidden"`; that is the *routing* fallback
  and is not this story's code. `ApiError` carries `headers` through `api_error_handler`.
- `apps/api/tests/test_no_registration.py` — `test_the_route_table_is_the_four_auth_routes_and_health`
  asserts the served path set **exactly**; adding a route means editing that set and its name. Its
  fragment-assembled patterns and `SELF` exclusion are the shape the new guard file copies.
- `apps/api/tests/test_forced_change_gate.py` — `ALLOWED_WITHOUT_THE_GATE` (the new route is
  **not** added), `_ungated_routes`, `test_the_allowlist_names_only_routes_that_exist`. The new
  route passing `test_every_route_outside_the_allowlist_declares_the_gate` unmodified is the proof
  the gate is declared.
- `apps/api/tests/test_source_guards.py` — `INTERPOLATED_SQL` forbids a statement assembled with
  `+` or an f-string, which is why the `RETURNING` list is repeated rather than shared through a
  constant; `test_the_scan_reaches_the_files_it_claims_to` names the files that must stay scanned.
- `apps/api/tests/conftest.py` — `conn`, `client` (https `base_url`), `make_user(role=, active=,
  must_change_password=, temp_credential_expires_at=, name=)` → `Account` with a runtime-generated
  password. `database_url` is function-scoped, so nothing leaks between tests.
- `apps/api/tests/test_password_change.py` — the forced change's suite; the new file mirrors its
  structure and must keep passing untouched.
- `apps/web/src/api/client.ts` — `ApiRequestError` (`code`, `status`), the exported code constants
  (**every** one needs a row in the parity test), `notifyUnauthorized` firing on **status 401
  only** — the reason the wrong-current-password answer is a 403.
- `apps/web/src/auth/SessionProvider.tsx` — `SessionContextValue`, `changePassword` (the forced
  change; the new method sits beside it and deliberately needs none of its two rescue branches,
  because a 401 here is already handled by the `onUnauthorized` observer), `asUser`, the `useMemo`
  whose dependency list every new context member joins.
- `apps/web/src/App.tsx` — `Screen`, `currentScreen(status, user)`, and the focus effect keyed on
  the rendered screen. The shell branch is where the account section is selected.
- `apps/web/src/components/AppBar.tsx` / `.module.css` — the optional-prop pattern (`onSignOut`
  renders a control only when supplied), `.signOut`'s outlined secondary treatment on navy, `.icon`
  sized from `--icon-size`. Phosphor icons are imported from `@phosphor-icons/react` and **never**
  given a `weight` prop (`no-raw-values.test.ts:226`).
- `apps/web/src/screens/ForcedPasswordChangeScreen.tsx` / `.module.css` — the form this screen is
  modelled on: `useId` for label/error wiring, `noValidate`, the blank-field guard, `FormError`
  with `fieldAtFault` driving `aria-invalid`, the inserted `role="alert"` paragraph, the
  token-only stylesheet. **No raw styling value may appear in any new file**
  (`no-raw-values.test.ts`), and every class referenced must exist in its module
  (`styling-wiring.test.ts`).
- `apps/web/src/__tests__/error-code-parity.test.ts` — `PYTHON` / `TYPESCRIPT` maps plus
  `it('compares every code the client exports')`: a new exported code without a row fails it.
- `apps/web/src/__tests__/login-screen.test.tsx:122–127` — already asserts the login screen offers
  no forgotten-password affordance. That is the signed-out half of the clause on the web side and
  needs no change; the API half is new.
- `apps/web/src/__tests__/{auth-gating,app-shell}.test.tsx` — the `User` fixture shape (eleven
  keys) and the app-bar control conventions the new cases follow.
- `README.md` lines 74–98 — the operator account of the cookie and the session deadlines, where the
  self-service change and the Administrator-only recovery rule belong.

## Tasks & Acceptance

**Execution:**

- `apps/api/api/auth.py` — the endpoint and its parts. Nothing else in the module changes.
  - `INVALID_CURRENT_PASSWORD = "invalid_current_password"` as a module-level constant (the parity
    test reads that exact assignment shape), with `CURRENT_PASSWORD_WRONG` as its sentence in
    EXPERIENCE.md's register. Document why it is not `unauthorized`: the session is fine, and a 401
    would sign the user out through `notifyUnauthorized` for a mistyped field.
  - `PASSWORD_UNCHANGED = "The new password must be different from your current one."` — a
    `WEAK_PASSWORD` *message*, not a new code, for the same reason
    `PASSWORD_REUSES_TEMPORARY` is one.
  - `class PasswordSelfChangeRequest(BaseModel)` — `model_config = ConfigDict(extra="forbid")`,
    `current_password` and `new_password`, each `Field(max_length=MAX_PASSWORD_FIELD_LENGTH)` and
    neither carrying a *minimum*, so a short password is answered by the rule-naming 422 and not by
    a generic `validation_error` (EXPERIENCE.md:87). Document why this body has the
    `current_password` that `PasswordChangeRequest` deliberately omits.
  - `_SELECT_PASSWORD_HASH` — `SELECT password_hash FROM users WHERE id = %s`. By id, from the
    session the caller already presented; no `credential_expired` expression, because the gate has
    already established this account is not on a temporary credential.
  - `_CHANGE_PASSWORD` — `UPDATE users SET password_hash = %s, updated_at = now() WHERE id = %s AND
    NOT must_change_password RETURNING <the eleven-column list, identical to `_SET_PASSWORD`'s>`.
    Comment: `updated_at` by hand (DW-17); `must_change_password` and `temp_credential_expires_at`
    are **not** touched, because this account has no temporary credential to clear; and
    `AND NOT must_change_password` is the same trick `_SET_PASSWORD`'s `AND must_change_password`
    plays — it makes "the gate's fact is still true at the moment of the write" a property of the
    statement rather than of a check taken some microseconds earlier.
  - `_invalid_current_password()` — a factory beside `_weak_password`, returning `403` with
    `NO_STORE`.
  - `@router.post("/auth/password/change", response_model=User)` →
    `def change_password(payload, response, user: Annotated[User, Depends(require_claimed_user)],
    conn)`. A **separate path** from `/auth/password`, not a second method on it: the route-table
    guard, the gate allowlist and any future counter all address a route by name, and two
    contracts sharing a path would have to be told apart by method in three places. Sync, not
    `async def`, for the same reason `set_password` is. Order: `NO_STORE` →
    read the digest (`None` → `not_signed_in()`) → `verify_password(row, current_password)` false →
    `_invalid_current_password()` → `password_rule_violation(new_password)` → new equals current →
    `_weak_password(PASSWORD_UNCHANGED)` → `hash_password` **outside** the transaction → in one
    transaction: `_CHANGE_PASSWORD` (`None` → re-read `must_change_password` for that id; row gone
    → `not_signed_in()`, flag true → the gate's `403 password_change_required`),
    `delete_sessions_for_user`, `issue_session` → `set_session_cookie` → `User.model_validate`.
    Docstring: the two audit entries Story 1.12 owes it, and DW-40's second Argon2id endpoint
    becoming a third.
- `apps/api/tests/test_no_registration.py` — add `/auth/password/change` to the exact path set and
  rename `test_the_route_table_is_the_four_auth_routes_and_health` to match, with a sentence saying
  what the new route is and that it creates nothing.
- `apps/api/tests/test_no_password_reset.py` — **new.** FR-5's second clause as a test, in
  `test_no_registration.py`'s three-check shape (route table, live probe, source scan) with
  fragment-assembled patterns and a `SELF` exclusion:
  - no served path carries a recovery word; probes at `/auth/password/reset`,
    `/auth/forgot-password`, `/auth/recover` answer `404` with the error envelope;
  - the new route answers `401` with no cookie, so it is not a signed-out surface;
  - **no mail transport exists anywhere** — scan the repository's own source *and* every
    `pyproject.toml` / `apps/web/package.json` for `smtplib`, `aiosmtplib`, `email.mime`,
    `sendmail`, `nodemailer`, `sendgrid`, `mailgun`, `postmark`, `send_email`. A guard over an
    empty file list passes forever, so assert the scan reached files first, and prove the patterns
    fire against a deliberately-bad fixture line.
- `apps/api/tests/test_self_service_password_change.py` — **new.** Every row of the I/O matrix,
  plus: that the old password stops working and the new one starts working at `POST /auth/login`
  with no sign-out in between; that a second device's session is dead on its next request while the
  caller's own request comes back holding a usable cookie; that a wrong current password spends no
  `hash_password` (monkeypatch it, as `test_login.py` monkeypatches the decoy verify) and leaves
  `password_hash` and `updated_at` untouched; that the three `RETURNING` lists in `api/auth.py`
  (`_RECORD_LOGIN`, `_SET_PASSWORD`, `_CHANGE_PASSWORD`) are identical and name exactly
  `User.model_fields` — the drift the module's comments warn about but nothing has checked; and
  that flipping `must_change_password` to true between the gate and the write yields the gate's 403
  rather than a write (drive it by monkeypatching `_CHANGE_PASSWORD`'s `WHERE` as
  `test_login_throttling.py:1178` already does).
- `apps/web/src/api/client.ts` — `export const INVALID_CURRENT_PASSWORD = 'invalid_current_password';`
  with the comment explaining why it is a 403 and not an `unauthorized`, and that the field at
  fault is the *current* password rather than the new one.
- `apps/web/src/__tests__/error-code-parity.test.ts` — the `invalid_current_password` row in
  `PYTHON` (`auth.py`) and `TYPESCRIPT`.
- `apps/web/src/auth/SessionProvider.tsx` — `changeOwnPassword(currentPassword, newPassword)` on
  `SessionContextValue`, added to the `useMemo` dependency list. Errors propagate untouched: unlike
  `changePassword`, this screen is reachable *and* escapable, so nothing has to be rescued here —
  and a 401 is already handled by the `onUnauthorized` observer. On success, store the returned
  `User` through `asUser`.
- `apps/web/src/screens/AccountSettingsScreen.tsx` + `.module.css` — **new.** Title "Account",
  the signed-in user's name and email as read-only lines, then the form: current password
  (`autoComplete="current-password"`) and new password (`autoComplete="new-password"`), a primary
  "Change password" button (the screen's one accent control), a secondary "Back" button, and the
  inline save indicator — nothing at rest, "Saving…" in muted text while in flight, "Saved." in
  `--color-primary` after a success — rendered next to the button, never as a toast. A blank field
  is refused locally, as `ForcedPasswordChangeScreen` refuses one. `FormError` carries which field
  is at fault so `aria-invalid` and focus land on the right input: `invalid_current_password` → the
  current field, `weak_password` → the new field, anything else → neither. Both fields clear on
  success; neither clears on a failure. The stylesheet takes every value from `tokens.css`.
- `apps/web/src/components/AppBar.tsx` + `.module.css` — an optional `onOpenAccount` prop rendering
  an "Account" control with a Phosphor `UserCircle` icon (no `weight` prop; sized from `--icon-size`
  in CSS), in the same outlined secondary treatment as `.signOut` and before it. Absent when the
  prop is, exactly as the sign-out control is.
- `apps/web/src/components/AppShell.tsx` — forward `onOpenAccount` to `AppBar`, with the same
  optional-prop comment the sign-out handler carries.
- `apps/web/src/App.tsx` — a `section` state (`'home' | 'account'`) in `Gate`, folded into `Screen`
  and `currentScreen` so the existing focus effect moves focus to the main region on the swap.
  The shell branch passes `onOpenAccount` and renders `AccountSettingsScreen` with its Back
  handler in place of the home panel. Reset to `'home'` is not needed on sign-out — `Gate` renders
  the login screen instead — but the swap back must be reachable from the screen itself.
- `apps/web/src/__tests__/account-settings.test.tsx` — **new.** Reachable from the app bar and
  returnable from Back; a successful change sends both fields, clears them and shows "Saved.";
  `invalid_current_password` marks the current field invalid, keeps both values and focuses it;
  `weak_password` marks the new field invalid and shows the API's sentence verbatim; a network
  failure marks neither field invalid; the button is disabled while in flight; and the screen
  offers no recovery-for-a-signed-out-user affordance.
- `apps/web/src/__tests__/app-shell.test.tsx` — the account control appears only when a handler is
  supplied and calls it, mirroring the existing sign-out cases.
- `README.md` — the self-service change in operator terms: where it lives, that it needs the
  current password, that it signs every other device out and keeps the caller signed in, and that
  a forgotten password has no self-service path at all and is an Administrator's job.

**Acceptance Criteria:**

- Given a signed-in Staff user who submits their correct current password and a valid new one, when
  the change is confirmed, then the response is `200`, and a subsequent `POST /auth/login` accepts
  the new password and refuses the old one — with no sign-out or re-login between the change and
  the first of those attempts.
- Given the same user holding a session on a second device, when the change succeeds, then the
  second device's next request is refused `401` while the caller's own session remains usable on
  the response's fresh cookie.
- Given a signed-in user who submits a wrong current password, when the request is handled, then
  the response is `403` `invalid_current_password`, `users.password_hash` and `users.updated_at`
  are unchanged, and no session row is deleted or created.
- Given a signed-in user still holding an admin-issued temporary credential, when they post to the
  self-service route, then they are refused `403 password_change_required` by
  `require_claimed_user`, and `apps/api/tests/test_forced_change_gate.py` passes with the new route
  absent from `ALLOWED_WITHOUT_THE_GATE`.
- Given `git grep` over the repository's own source and dependency manifests, when they are
  inspected, then no mail-transport package or module is imported or declared anywhere, and no
  route serves a password recovery path to an unauthenticated caller.
- Given the Account Settings screen receives `invalid_current_password`, when it renders the
  failure, then the API's own sentence is shown, only the current-password field is marked invalid
  and focused, both typed values are preserved, and no navigation occurs.
- Given `make lint` and `make test`, when they are run over the finished change, then both exit 0
  with every pre-existing test in `apps/api`, `apps/web`, `shared/schema` and `infra` passing —
  `test_password_change.py` and `test_login.py` unmodified.

## Spec Change Log

## Review Triage Log

### 2026-09-18 — Review pass (follow-up 2)
- intent_gap: 0
- bad_spec: 0
- patch: 12: (high 0, medium 1, low 11)
- defer: 2: (high 0, medium 1, low 1)
- reject: 17: (high 0, medium 5, low 12)
- addressed_findings:
  - `[medium]` `[patch]` "Saved." outlived a refusal after all. Both blank-field guards `return` before the `setSaved(false)` that `handleSubmit` runs at the point a request starts — and a successful change empties both boxes, so the very next press *is* a blank refusal. Two clicks after a success the screen read "Enter your current password." and "Saved." side by side, which is exactly the state the file's own comment says must not happen. `refuse()` now retires the confirmation, so every way out of the form clears it; a new test drives the two-click sequence and fails on the old code.
  - `[low]` `[patch]` `test_the_lock_ladder_is_not_cleared` set and re-read `users.locked_until` only — the column the throttling migration's own header calls a mirror that "reports; it never decides". Its `login_attempts` row carried `failure_count` and a NULL `locked_until`, so a build that cleared the deciding column passed a test named for not clearing the ladder. Both columns are now set and asserted; a `SET locked_until = NULL` planted in the handler fails it.
  - `[low]` `[patch]` Nothing read `.account` or `.signOut`. `app-shell.test.tsx`'s case was titled "carries no accent fill" and asserted a label and an `aria-hidden`; `vite.config.ts` sets `css: false`, so it could not see a colour. An accent fill on the app bar is a second primary control on *every* authenticated screen. `styling-wiring.test.ts` now pins both controls' background, colour and border and counts `--color-accent` in `AppBar.module.css` at exactly one (the stripe).
  - `[low]` `[patch]` The 375px overflow fix from the previous pass was held by nothing. Deleting `min-width: 0` from `.brand` pushes Sign out off a phone viewport with all 562 web tests green, because jsdom performs no layout. `.brand`'s `min-width`, `.title`'s `text-overflow`/`white-space` and `.actions`'s `flex: none` are now asserted, each with the sentence for why the brand is the element that gives way.
  - `[low]` `[patch]` `app-shell.test.tsx`'s accent case renamed to what it actually checks — the label and the hidden icon — with a pointer to where the accent rule is now enforced. A test titled for a property it cannot observe is worse than no test.
  - `[low]` `[patch]` `does not report a change as saved when the body that comes back is not a user` asserted `findByRole('alert')` was truthy and nothing about its text, so blanking `asUser`'s message would leave an empty red paragraph after a failed change and keep the suite green. It now pins the sentence, as every other failure case in the file does.
  - `[low]` `[patch]` The neutral-failure alert is the third of the screen's three slots and the only one whose position nothing checked. Parked under the current-password box, a sentence about the network reads as a verdict on what was typed there — the whole reason `fieldAtFault` exists. Its placement after both fields is now asserted.
  - `[low]` `[patch]` No 401 from the new route was pinned to `cache-control: no-store`. The handler sets it on `response` before it can raise and both 403 factories carry it on their own `ApiError`; the vanished-row 401 leaves through neither, so it was the one arm where the header could go missing unnoticed — on an endpoint whose success body carries a name, an address and a role.
  - `[low]` `[patch]` `MANIFESTS` is listed explicitly "so that a manifest added later has to be added here too, visibly", and nothing made it visible: a new `pyproject.toml` or `package.json` was simply unscanned while `test_no_manifest_declares_a_mail_transport` reported clean over the seven it knew. A completeness test now globs the repository and names anything absent from the list; planting `apps/api/extra/package.json` fails it.
  - `[low]` `[patch]` `test_the_caller_stays_signed_in_on_a_fresh_cookie` captured the pre-change cookie and only asserted the new one differed — so a handler that issued a second session and revoked none satisfied every assertion in it. The old token is now replayed and must answer 401; neutering `delete_sessions_for_user` in the handler fails exactly that line.
  - `[low]` `[patch]` `_returning()` split the clause on commas with no check that the result was a column list. A trailing comment, a second `RETURNING` or an expression containing a comma would have turned a misread into a reported drift — a guard that fails for the wrong reason is one people edit around. It now asserts each parsed token is an identifier and says so in the message.
  - `[low]` `[patch]` `AccountSettingsScreen`'s comment claimed "there is never a second alert in the document". True of the screen, false of the surface: `App` renders a failed sign-out as a sibling above it, because the app bar that raised it is still there. The claim is now scoped, with the reason the two can be live together and the note that `getByRole('alert')` on the composed surface sees both.

### 2026-09-18 — Review pass (follow-up)
- intent_gap: 0
- bad_spec: 0
- patch: 12: (high 0, medium 3, low 9)
- defer: 3: (high 0, medium 1, low 2)
- reject: 10: (high 0, medium 3, low 7)
- addressed_findings:
  - `[medium]` `[patch]` Nothing drove `changeOwnPassword`'s failure branch through the real provider: every failure case mocked the session context, so wrapping its `apiRequest` call in `try { … } catch { return; }` left all 549 web tests green while the screen showed "Saved." for a change the server had refused. Two real-provider cases now stub `fetch` with a `403 invalid_current_password` and with a `200` carrying a body `asUser` rejects; the mutation that used to pass now fails.
  - `[medium]` `[patch]` `_TRANSPORTS` banned a bare `boto3` over the source tree *and* every manifest. `CLAUDE.md` commits this product to S3-compatible object storage, so the first Epic 2 story to declare it would have failed `test_no_manifest_declares_a_mail_transport` — a false accusation, and the kind of guard people delete rather than read. SES is now matched through the spellings that name the mail service (`"ses"`, `SESClient`, `send_raw_email`, `sendRawEmail`, `@aws-sdk/client-ses`), with three S3 lines added as negative fixtures.
  - `[medium]` `[patch]` The empty-`RETURNING` arm selected `must_change_password` and never looked at it, under a comment claiming the branch was "decided by the database rather than by this comment". The statement now asks the question it actually needs — `SELECT 1`, renamed `_SELECT_ROW_EXISTS` — and the comment says plainly that the predicate, not a later re-read, is what decides.
  - `[low]` `[patch]` `styling-wiring.test.ts` never named the new screen, so `AccountSettingsScreen.module.css` could point `.error` at `--color-text` or `.saved` at the muted grey with every render test green. It now carries the destructive-red row, the save-indicator's two states, the alert-element row, and the one-accent-per-screen block the forced-change screen already had.
  - `[low]` `[patch]` `account-settings.test.tsx` left `session.value` set between tests, so a case added to the real-provider block without its own reset would have run against the previous test's `vi.fn()`. Cleared in `afterEach`.
  - `[low]` `[patch]` `MUST_BE_SCANNED` anchored the mail guard's floor on `AccountSettingsScreen.tsx`, a file this story invented — renaming it in a later epic would fail a mail-transport guard for a reason unrelated to mail. Anchored on `App.tsx` instead.
  - `[low]` `[patch]` `showSection` cleared the sign-out alert unconditionally, and the app bar keeps its Account control on the account screen — so a control that visibly did nothing was the only way to dismiss a sign-out failure. A same-section press is now a no-op, with a test that drives the whole sequence.
  - `[low]` `[patch]` The cookie assertion normalised the attribute *name* (`.replace("samesite", "SameSite")`, a no-op against what `http.cookies` emits) and would still have failed on a conformant `SameSite=Strict`. Case-folded on both sides instead.
  - `[low]` `[patch]` `PROBES` issued `POST` only, so a `GET`-served recovery page would have passed. Each path is now probed under both verbs.
  - `[low]` `[patch]` `_password_change_required()` carries `headers=NO_STORE` and nothing asserted it — removing it kept 63 tests green. The reissue-race test now pins the code, the sentence and `cache-control: no-store` together.
  - `[low]` `[patch]` `PasswordSelfChangeRequest`'s docstring stated its reasoning backwards, reading as a description of what the endpoint does rather than of why neither field carries a minimum.
  - `[low]` `[patch]` README told operators the change signs every other device out without saying that nothing records it having happened — which is exactly the situation in which someone later asks when and by whom. The absence, and Story 1.12 as its answer, are now stated.

### 2026-09-18 — Review pass
- intent_gap: 0
- bad_spec: 0
- patch: 13: (high 0, medium 4, low 9)
- defer: 5: (high 0, medium 5, low 0)
- reject: 12: (high 0, medium 2, low 10)
- addressed_findings:
  - `[medium]` `[patch]` `section` survived a sign-out, so signing out of Account Settings and signing back in on the same handset landed the next person on a password form. It is now reset whenever `status` leaves `'signed-in'`, with a test driving the whole sign-out/sign-in sequence.
  - `[medium]` `[patch]` A failed sign-out taken from Account Settings rendered nothing at all, then surfaced on the home panel describing a click made elsewhere. The alert is now one node rendered on both surfaces and cleared on every swap.
  - `[medium]` `[patch]` Nothing pinned the request the front end actually sends: every screen test stubbed the session context, so a camelCase body or the wrong path would have shipped green. A real-provider test now asserts the recorded `fetch` — path, method, credentials, headers, body keys — and that the returned `User` replaces the cached one.
  - `[medium]` `[patch]` The app bar overflowed a 375px viewport once Account joined Sign out and the brand. `.brand` is now the element that gives way (`min-width: 0`, ellipsis on the title), so neither control is pushed off a phone.
  - `[low]` `[patch]` "Saved." outlived the change it described — editing a field after a success left it beside two freshly filled boxes. Both `onChange` handlers now retire it.
  - `[low]` `[patch]` Back stayed live while a change was in flight, so clicking it lost the outcome. It is disabled while submitting, with a matching `:disabled` rule.
  - `[low]` `[patch]` `_SET_PASSWORD`'s comment still said "ten-column" two comments away from `_CHANGE_PASSWORD` calling the byte-identical list eleven. Corrected.
  - `[low]` `[patch]` README claimed the screen shows name, email **and role**; it renders name and email. The claim is dropped rather than the field added — a role badge is DESIGN.md's own component and belongs with the story that needs it.
  - `[low]` `[patch]` README introduced the lockout exception one paragraph above the paragraph that introduces lockouts, so the reader met the exception before the rule and read "the lock clears itself" twice. Reordered.
  - `[low]` `[patch]` `test_no_password_reset.py`'s meta-guard asserted only `> 10` files and named none, so a drifted scan root would still have reported clean. It now asserts a real floor and seven named files, one per root and per risky extension, following `test_source_guards.py`.
  - `[low]` `[patch]` The mail-transport vocabulary missed the names most likely to be reached for first. `_TRANSPORTS` grew to twenty (resend, mailjet, brevo, mailchimp, emailjs, fastapi-mail, flask-mail, boto3, `@aws-sdk/client-ses`, …) with no bare `ses`, and `SCANNED_EXTENSIONS` gained `.js/.mjs/.cjs/.yml/.yaml`, each proven by a new fixture.
  - `[low]` `[patch]` The same file's docstring claimed a source-tree scan for recovery wording that only ever ran over the route table. Corrected to state what each check actually covers, and to point at `login-screen.test.tsx` as where the web half of that clause lives.
  - `[low]` `[patch]` `auth.py`'s module docstring said a password change "leaves only `updated_at` behind"; `_RECORD_LOGIN` overwrites that on the next sign-in, so it leaves nothing durable until Story 1.12. Said plainly.

## Design Notes

**Why a separate path rather than a second method on `/auth/password`.** `PUT /auth/password` is
tempting and wrong twice over. It is not idempotent — a replay fails, because the current password
it proved is no longer current — and, more practically, three separate guards in this repository
address a route by `(method, path)` or by path alone: `ALLOWED_WITHOUT_THE_GATE`, the exact path
set in `test_no_registration.py`, and any counter DW-40 eventually brings. Two contracts sharing a
path means each of those has to be taught the distinction, and the one that forgets fails open.

**Why the current password is verified before the new one is assessed.** Both orderings "work". The
cost of checking rules first is that a caller who cannot prove the current password still learns
whether a candidate satisfies the policy, and — more to the point — gets a *decision* out of an
endpoint they have not authenticated to. The cost of verifying first is one Argon2id verify on a
request that was going to be refused anyway. On an endpoint whose whole purpose is to prove the
actor before it changes their credential, the refusal belongs first.

**Why "different from the current one" is a rule here and not in `shared_schema`.** It is the exact
twin of `PASSWORD_REUSES_TEMPORARY`: a rule about one account's stored digest, not about the string,
so `password_rule_violation` cannot decide it. It costs nothing extra to check — the current
password has already been proved correct at that point, so a plain string comparison against it is
equivalent to a verify against the stored digest, and no second hash is spent.

**Why the change revokes every session.** The forced change revokes because the temporary credential
may have travelled by note. A self-service change revokes because the *reason* people change a
password they already chose is that they think somebody else has it — and a change that leaves that
somebody's session alive has not done the thing the user asked for. Making the two paths agree also
means `delete_sessions_for_user` has one meaning in this module rather than two.

**Why the app bar and not the nav.** EXPERIENCE.md puts Account Settings behind a nav profile entry,
and the nav is role-conditional, spans six surfaces, and is a bottom tab bar below `--breakpoint-md`
and a sidebar above it. Five of those six surfaces do not exist. Building the nav to hold one entry
would mean guessing at the other five and rebuilding it when they arrive; the app bar is already
present on every authenticated screen, already carries a secondary control, and is where a profile
entry conventionally sits. When the nav lands, the entry moves and `AccountSettingsScreen` does not
change.

```python
# apps/api/api/auth.py — the shape of the write, not the code.
_CHANGE_PASSWORD = """
UPDATE users
   SET password_hash = %s,
       updated_at = now()
 WHERE id = %s
   AND NOT must_change_password
RETURNING <the same eleven columns as _SET_PASSWORD, character for character>
"""
# No row => either the account is gone (401) or an Administrator reissued a
# temporary credential in the microseconds since the gate ran (403). One
# re-read tells them apart; neither writes.
```

## Verification

**Commands:**
- `make lint` — expected: exit 0 (ruff check, ruff format --check, oxlint --deny-warnings,
  tsc --noEmit).
- `make test` — expected: exit 0; the `apps/api` database tests run against the ephemeral cluster
  or skip with the same "no PostgreSQL available" reason (DW-18/DW-39).
- `uv run pytest apps/api/tests/test_self_service_password_change.py apps/api/tests/test_password_change.py apps/api/tests/test_login.py -q`
  — expected: exit 0, with the two pre-existing files unmodified.
- `uv run pytest apps/api/tests/test_forced_change_gate.py apps/api/tests/test_no_registration.py apps/api/tests/test_no_password_reset.py apps/api/tests/test_source_guards.py -q`
  — expected: exit 0.
- `npm --prefix apps/web run test` — expected: exit 0, including the parity row, the new account
  screen file and the extended app-shell cases.
- `git status --porcelain infra/migrations` — expected: empty. This story ships no migration.
- `git grep -nE "smtplib|aiosmtplib|nodemailer|sendgrid|mailgun|postmark" -- apps shared infra scripts`
  — expected: matches in `apps/api/tests/test_no_password_reset.py` only.
- Prove each new guard load-bearing by removing what it guards: drop `require_claimed_user` from
  the new route (the gate guard fails), answer the wrong current password with `not_signed_in()`
  (the 403 case and the web case fail), delete the `verify_password` call (the wrong-password case
  fails), remove `delete_sessions_for_user` (the second-device case fails), and change one column
  in `_CHANGE_PASSWORD`'s `RETURNING` list (the drift guard fails).

**Manual checks (if no CLI):**
- Invoke the `ui-ux-pro-max` skill and run its pre-delivery checklist against the Account Settings
  screen before calling this story done (epic context: required for every UI story).
- `make migrate`, then `make dev`: sign in, open Account from the app bar, submit a wrong current
  password and confirm the screen reports it without signing you out; submit a 6-character new
  password and read the rule-naming sentence; change it successfully, watch "Saved." appear inline,
  then sign in again with the new password and confirm the old one is refused.


## Auto Run Result

Status: done

**What was implemented.** FR-5's self-service half: `POST /auth/password/change`, a gated second
password write that proves the caller's current password against the stored digest before it reads
the new one's rules, replaces the digest, and — in the same transaction — revokes every session the
user holds and issues the caller a fresh one. `apps/web` gains an Account Settings screen reached
from the app bar. The "no signed-out recovery" half of the clause is enforced by a guard file
rather than by the absence of code: no recovery route is served under either verb, and no mail
transport is imported or declared anywhere in the repository.

**Files changed** (19 since `68c0d87`, excluding the planning artifacts):

| File | What it does |
|---|---|
| `apps/api/api/auth.py` | The endpoint, its request model, its three statements and its two error factories |
| `apps/api/tests/test_self_service_password_change.py` | New — every row of the I/O matrix plus the `RETURNING`-drift guard |
| `apps/api/tests/test_no_password_reset.py` | New — FR-5's second clause: route table, live probes, source scan, manifest scan |
| `apps/api/tests/test_no_registration.py` | The exact served-path set grows by one route |
| `apps/web/src/api/client.ts` | `INVALID_CURRENT_PASSWORD`, and why it is a 403 |
| `apps/web/src/auth/SessionProvider.tsx` | `changeOwnPassword` on the context |
| `apps/web/src/screens/AccountSettingsScreen.tsx` / `.module.css` | New — the two-field form, the save indicator, the Back control |
| `apps/web/src/App.tsx` | A `section` state in `Gate`, and the swap between home and account |
| `apps/web/src/components/AppBar.tsx` / `.module.css` / `AppShell.tsx` | The optional Account control, and a bar that survives 375px |
| `apps/web/src/__tests__/account-settings.test.tsx` | New — the screen, and reaching it through the real provider |
| `apps/web/src/__tests__/{app-shell,error-code-parity,styling-wiring,forced-password-change,login-screen}.test.*` | The new control, the parity row, the new screen's and the app bar's tokens |
| `README.md` | The operator account of the change, and of what it does not record |

**Review findings, this pass** (the third; two review passes preceded it). 12 patched (0 high,
1 medium, 11 low), 2 deferred (1 medium, 1 low), 17 rejected. Four review layers ran in parallel —
blind hunter, edge-case hunter, verification-gap, intent alignment. No `intent_gap` and no
`bad_spec`: nothing found required a human decision or a spec amendment, so `review_loop_iteration`
stays at 0. Each patch is listed under **Review Triage Log → 2026-09-18 — Review pass (follow-up
2)**. The pass has one shape: eleven of the twelve are guards that were not load-bearing, and the
twelfth is the one user-visible defect left in the screen — "Saved." standing beside "Enter your
current password.", two clicks after a success, because both blank-field guards return before the
line that retires it.

Rejected, and why, for the ones most likely to be raised again. The unthrottled guess surface, the
concurrent-change race, the `password_change_required` rendering, the password-manager `username`
field and the unannounced sibling-session revocation are already deferred items in this spec's
frontmatter — re-reporting them is not a new finding. A missing `AND active` predicate is shared
with `_SET_PASSWORD` and unreachable until Story 1.10 builds deactivation. The endpoint resetting
Story 1.5's absolute session ceiling is not a defect: that ceiling exists to force periodic
re-authentication, and this route cannot be reached without proving the current password, which is
re-authentication. Two `role="alert"` regions on the composed account surface is legal ARIA between
two different actions — the overclaiming comment was corrected instead of the markup. A `maxLength`
on the inputs would replace the `422 validation_error` the I/O matrix specifies for an oversized
field. An error surviving an edit of the field it marked matches `ForcedPasswordChangeScreen`
exactly, and diverging on this screen alone would be the inconsistency. `deferred-work.md` and
`sprint-status.yaml` are the orchestrator's, not this story's.

**Follow-up review recommended: `true`.** Patched this pass: 0 high, 1 medium, 11 low →
`3 x 1 + 1 x 11 = 14`, which is at or above the threshold of 5.

**Verification performed.**

- `make lint` — exit 0 (ruff check, ruff format --check, oxlint --deny-warnings, tsc --noEmit).
- `make test` — exit 0. **580 passed** in `apps/api`/`shared`/`infra` (the database tests ran
  against a live cluster rather than skipping), **562 passed** in `apps/web` across 14 files.
- `git status --porcelain infra/migrations` — empty. This story ships no migration.
- `git grep -nE "smtplib|aiosmtplib|nodemailer|sendgrid|mailgun|postmark" -- apps shared infra
  scripts` — matches in `apps/api/tests/test_no_password_reset.py` only.
- Every guard added this pass was proved load-bearing by mutation, not by inspection:
  - removing `setSaved(false)` from `refuse()` fails `drops a previous success when the next press
    is refused before it sends`;
  - `background: var(--color-accent)` on `.account` fails two styling-wiring cases;
  - deleting `min-width: 0` from `.brand` fails `makes the brand the element that gives way on a
    phone` — and nothing else, which was the point;
  - `UPDATE login_attempts SET locked_until = NULL` planted in the handler fails
    `test_the_lock_ladder_is_not_cleared`;
  - an `apps/api/extra/package.json` fails `test_the_manifest_list_is_every_manifest_in_the_repository`;
  - replacing `delete_sessions_for_user(conn, user.id)` with `pass` fails
    `test_the_caller_stays_signed_in_on_a_fresh_cookie` on the replayed-token line specifically,
    with every pre-existing assertion in that test still passing.
  Each mutation was reverted and the full suite re-run green afterwards.

**Residual risks.**

- The ten entries in this spec's `deferred` frontmatter are the honest list. The two that matter
  most: the endpoint is an unbounded Argon2id guess surface for anyone holding a live session
  cookie (the intent's Never list forbids closing it here), and a change can land on the server
  while the screen reports it as failed, because errors propagate untouched by design.
- Both new guard files are lexical. `ROUTE_WORDS` is three words and `_TRANSPORTS` is a mail
  vocabulary with no SMS spelling in it; a recovery surface named `/auth/magic-link`, or one built
  on an SMS one-time code, reads clean through the whole of `test_no_password_reset.py`. Widening
  either safely is a decision about the routes Stories 1.8 and 1.10 will actually serve.
- The screen's copy is asserted against sentences retyped into the test files. At run time it
  renders whatever the API sent; what can drift silently is the suite's claim to be checking it.
- No manual browser pass was possible in this unattended run. The password-manager association, the
  375px layout and the focus order remain checked only through jsdom and through the stylesheet
  assertions above.
