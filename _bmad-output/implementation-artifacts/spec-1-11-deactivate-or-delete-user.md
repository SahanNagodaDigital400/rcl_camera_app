---
title: 'Story 1.11 — Deactivate or Delete User'
type: 'feature'
created: '2026-09-21'
baseline_revision: '831b9527e0ef80fc837192d26d5b9daac4657ad6'
status: 'done'
review_loop_iteration: 0
followup_review_recommended: true
context:
  - '{project-root}/AGENTS.md'
  - '{project-root}/_bmad-output/planning-artifacts/architecture/architecture-rcl_camera_app-2026-08-30/ARCHITECTURE-SPINE.md'
  - '{project-root}/_bmad-output/planning-artifacts/ux-designs/ux-rcl_camera_app-2026-09-08/EXPERIENCE.md'
  - '{project-root}/_bmad-output/planning-artifacts/ux-designs/ux-rcl_camera_app-2026-09-08/DESIGN.md'
warnings: ['multiple-goals', 'oversized']
deferred:
  - summary: >-
      `session-expiry.test.tsx` fails about one run in five, independently of
      this story, by reading the DOM before the 401-to-signed-out render lands.
    evidence: |-
      Measured, not inferred. With this story's new test file removed from
      `src/__tests__` the web suite still failed 4 of 20 runs, always inside
      `session-expiry.test.tsx`; with it present the rate was 1 of 20. The file
      is byte-identical to `831b9527`, as are `SessionProvider.tsx`,
      `client.ts` and `App.tsx`. The failure is a synchronous `getByText`
      for `/your session has ended/i` returning while the app bar is still
      mounted. The fix is a suite-level decision — a shared
      `configure({ asyncUtilTimeout })`, or awaiting the transition in that
      file — and touching it from this story would edit a file this spec's
      Verification pins as unmodified.
    location: >-
      apps/web/src/__tests__/session-expiry.test.tsx
    severity: medium
  - summary: >-
      The product's first modal leaves the page behind it in the accessibility
      tree and scrollable, with `aria-modal` as the only signal.
    evidence: |-
      `ConfirmDialog` sets `aria-modal="true"` and paints a scrim, but nothing
      marks the screen root `inert` or `aria-hidden`, and nothing locks body
      scroll. Assistive technology that ignores `aria-modal` can still reach the
      user table underneath, and a wheel or touch gesture still scrolls the page
      under the scrim. Neither EXPERIENCE.md nor DESIGN.md asks for either, so
      this is the point at which the product should decide its modal
      convention rather than a defect in this story's clauses.
    location: >-
      apps/web/src/components/ConfirmDialog.tsx
    severity: medium
  - summary: >-
      Reactivating an account whose temporary credential already lapsed shows it
      as Active while nobody can sign in as it.
    evidence: |-
      `POST /admin/users/{user_id}/activate` writes `active = true` and touches
      neither `must_change_password` nor `temp_credential_expires_at`, by
      design — a reactivation is not a credential reissue. But
      `api/auth.py` refuses a login whose temporary credential has lapsed
      (DW-44), so an unclaimed account deactivated past its 72 hours and then
      reactivated reads Active on Story 1.9's list and is unusable. The route
      that would fix it is the credential reissue DW-87 says no story in Epic 1
      owns.
    location: >-
      apps/api/api/users.py (activate_user)
    severity: medium
  - summary: >-
      A destructive write that succeeds and is then followed by a failing list
      refetch replaces the whole table with a load error and never reports the
      success.
    evidence: |-
      `run()` calls `load()` after the write commits. If that refetch fails,
      `load`'s catch sets `listing` to `{ kind: 'failed' }`, so the
      Administrator sees a page-level error where a deactivation or a delete
      has in fact happened, with nothing saying so. Keeping the table and
      showing the refetch failure as a banner would separate "the write
      failed" from "the re-read failed"; the two are one message today.
    location: >-
      apps/web/src/screens/UserListScreen.tsx (run, load)
    severity: low
  - summary: >-
      After a deactivation the row-end control keeps focus while its accessible
      name and its action flip from Deactivate to Activate.
    evidence: |-
      `ConfirmDialog`'s unmount restores focus to the opener when it is still
      connected. The row-end button carries no `key`, so React patches the same
      DOM node, and the control the keyboard Administrator is returned to now
      reads "Activate Kasun Perera" and performs the inverse verb. Restoring
      focus to that position is the right behaviour; what is missing is
      anything announcing that the control under it changed.
    location: >-
      apps/web/src/screens/UserListScreen.tsx (the row-end slot)
    severity: low
  - summary: >-
      The row's Edit control is not covered by the in-flight guard, so an
      Administrator can navigate off the list while a destructive request is
      open.
    evidence: |-
      `press()` refuses a second destructive verb while `pending !== null`, and
      since the patch pass every row's destructive controls are disabled for
      the duration. `Edit` calls `onEditUser(user)` directly and is not
      disabled, so it still leaves the screen mid-request — abandoning the
      dialog and the pending state, and landing the Administrator on an editor
      for a row that may be about to disappear.
    location: >-
      apps/web/src/screens/UserListScreen.tsx (the row-end slot)
    severity: low
  - summary: >-
      `--z-modal`'s documented relationship to the skip link's stacking level is
      asserted by nothing.
    evidence: |-
      The token's comment in `tokens.css` says it sits "above AppShell's skip
      link (z-index 1) with room left between them", and
      `styling-wiring.test.ts` checks only that `.scrim` references the token.
      If the skip link's level is ever raised the scrim quietly stops covering
      the chrome, which is the exact failure the comment calls out.
    location: >-
      apps/web/src/styles/tokens.css
    severity: low
  - summary: >-
      The confirmation dialog says nothing while a destructive write is in
      flight, and nothing at all once it lands.
    evidence: |-
      While `busy`, `ConfirmDialog` disables both controls, parks focus on a
      panel whose only text is the unchanged question, and carries no
      `role="status"`. Between pressing Delete and the row disappearing a
      screen-reader Administrator gets silence. The success side is the same:
      the badge flips to Deactivated, or the row goes, with no live-region
      sentence saying so — only the refusal path is announced. This is the
      product's first modal and neither EXPERIENCE.md nor DESIGN.md states a
      pending/confirmed announcement convention, so it belongs with the other
      open modal-convention question (inert, scroll lock) rather than being
      invented here.
    location: >-
      apps/web/src/components/ConfirmDialog.tsx
    severity: medium
  - summary: >-
      Activate is the one verb whose control is disabled mid-flight with no
      dialog to restore focus from, so a keyboard Administrator is dropped to
      `<body>`.
    evidence: |-
      `press('activate', …)` goes straight to `run()` — no dialog — and `run()`
      freezes every row's controls for the duration. Disabling the focused
      button moves focus to `<body>`, and there is no unmounting dialog whose
      cleanup would put it back: `rescueFocus` is set for `delete` only. The
      keyboard Administrator resumes at the top of the document. The fix is the
      same decision as the already-deferred "the control's name and verb flip
      under the returned focus" item — where focus belongs after a row verb
      rewrites its own row-end control — and the two should be settled together.
    location: >-
      apps/web/src/screens/UserListScreen.tsx (press, run)
    severity: low
  - summary: >-
      A `404` refusal tells the Administrator to reload the list, and closing it
      leaves the same stale list on screen with no way to do that.
    evidence: |-
      `NO_SUCH_USER` is "That user no longer exists. Reload the list." `run()`'s
      catch renders it in the dialog and never refetches, and the dialog's
      `onClose` only clears the dialog — so the row somebody else already
      removed is still there, still carrying three live controls. The one-line
      fix is a `load()` on the failure path, but that widens the already-logged
      "a destructive write followed by a failing list refetch replaces the whole
      table with a load error" item: every extra `load()` is another place that
      can blank the table. The two are one decision about what a failed refetch
      is allowed to do to the screen, and should be settled together rather than
      one being patched under the other.
    location: >-
      apps/web/src/screens/UserListScreen.tsx (run, the dialog's onClose)
    severity: low
  - summary: >-
      Delete-and-recreate inherits the address's lockout while the new row reads
      unlocked, so the list says one thing and `POST /auth/login` says another.
    evidence: |-
      `login_attempts` is keyed on the submitted address and deliberately not a
      foreign key to `users`, so a delete leaves it behind — which is the point
      (DW-59: delete-and-recreate must not become the unlock this product chose
      not to build). The consequence only became reachable with this story: the
      recreated row carries `locked_until: null` and Story 1.9's list renders no
      lock notice, while `apps/api/tests/test_delete_user.py`'s own
      `test_a_recreated_account_cannot_sign_in_under_the_lock_that_was_never_cleared`
      drives the correct credential through `POST /auth/login` and gets `429`.
      The Administrator's only remedy is to wait out a lock the screen says does
      not exist. Surfacing it means either rendering the address's lock on a row
      it is not keyed to, or building the admin unlock DW-64 says no story owns
      — both product decisions, not handler ones.
    location: >-
      apps/web/src/screens/UserListScreen.tsx (lockNotice) / apps/api/api/throttle.py
    severity: medium
  - summary: >-
      "+ Add user" and "Back" stay live while an `activate` request is open —
      the one verb with no dialog covering them.
    evidence: |-
      `frozen = pending !== null` freezes every row's controls, and for a
      confirmed verb the scrim covers the rest of the screen anyway. `activate`
      fires from one press with no dialog, so during its request the two screen
      controls above the table are still pressable: leaving the screen there
      unmounts it mid-write, and the answer — including a refusal — is never
      shown. The write itself still commits. Disabling them is one attribute
      each, but it is the first time this product would disable a navigation
      control for a request that is not about navigation, which is a convention
      decision rather than a fix.
    location: >-
      apps/web/src/screens/UserListScreen.tsx (the actions block)
    severity: low
---

<intent-contract>

## Intent

**Problem:** An Administrator can create, list and edit accounts, but there is no way to take
access away. Somebody who has left Rocell keeps a working login and a live session until it
expires, and the only remedy is a developer holding `DATABASE_URL` — the dependency Epic 1 exists
to remove. FR-13 closes it: deactivate or delete a user, with the deactivation rejected on the
target's **very next request** rather than at their next sign-in, and with the last remaining
active Administrator protected from both verbs.

**Approach:** Three new Administrator-only routes on the existing `/admin/users` collection —
`POST /admin/users/{user_id}/deactivate`, `POST /admin/users/{user_id}/activate` and
`DELETE /admin/users/{user_id}` — each with no request body, each reusing Story 1.10's shipped
Administrator-floor predicate and its ordered lock rather than writing a second copy of the rule.
Deactivation flips `active` **and** deletes the target's session rows in the same transaction;
deletion is a hard delete that ends sessions through the `ON DELETE CASCADE` already on
`sessions.user_id`. On the web, the Users table's row-end slot gains the destructive verbs behind
the product's first confirmation dialog, built from DESIGN.md's `confirmation-dialog` block.

## Boundaries & Constraints

**Always:**

- **The floor is one survivor, and it is Story 1.10's predicate verbatim.** A verb is refused when
  it would leave zero active Administrators. Reuse `_LOCK_ACTIVE_ADMINISTRATORS` and the
  `role = 'staff' OR NOT active OR EXISTS (… other active administrator …)` arms from
  `apps/api/api/users.py`; reuse `LAST_ADMINISTRATOR` / `LAST_ACTIVE_ADMINISTRATOR` and the `409`.
  One rule, one code, one sentence across demote, deactivate and delete. See Design Notes for why
  epics.md's "at least two must always exist" is not a second rule.
- **Authorization is `require_administrator` declared in the signature**, never a line in a
  handler — on all three routes, exactly as the three shipped ones do.
- **Deactivation revokes sessions, it does not merely block them.** AGENTS.md line 18. Both halves:
  `_SELECT_SESSION`'s `AND u.active` is what makes the very next request a `401`, and deleting the
  rows is what makes it durable across a later reactivation.
- **Every SQL statement is a module-level `_UPPER_SNAKE` constant with a parameterized body**, sync
  `def` handlers, `response.headers.update(NO_STORE)` first, `#:` blocks arguing *why* above every
  new constant — `tests/test_source_guards.py` and the module's own conventions.
- **`updated_at` is set by hand** on every `UPDATE` (DW-17, no BEFORE UPDATE trigger).
- **The web stylesheet references only `var(--…)` tokens already declared in `tokens.css`.** A new
  non-colour token may be added (`tokens.css:110`); a new **colour** may not — `tokens.test.ts`
  pins DESIGN.md's palette at exactly 11.
- **The destructive control carries a word, never colour alone** (EXPERIENCE.md:111), the dialog
  names the object and the consequence (EXPERIENCE.md:72, :144), and modal depth never exceeds one
  level (EXPERIENCE.md:42).

**Block If:**

- A change to `shared/schema` or a new migration appears necessary. This story ships neither: every
  column it needs exists, and `ON DELETE CASCADE` is already on `sessions.user_id`.
- Closing FR-13 appears to require an audit entry. It does not — Story 1.12 owns the log and owes
  these three routes entries. Do not build a private log path in the meantime.

**Never:**

- **Never add `active` to `EditUserRequest`.** `PATCH /admin/users/{user_id}` stays three text
  columns; its `extra="forbid"` refusal of `{"active": false}` is pinned by
  `tests/test_edit_user.py` and is the contract these routes exist to keep.
- **Never clear the target's `login_attempts` row** on deactivate or delete. Deleting an account
  would then be a lockout-evasion path, which is the same reason Story 1.10 carried the run instead
  of clearing it (DW-59).
- **Never build an unlock, a credential reissue, an admin-set password, or a soft-delete marker
  column.** No story in Epic 1 owns the first two (DW-64); the last is a schema decision nothing
  asks for.
- **Never use a native `<dialog>` with `showModal()`.** Verified against this tree: jsdom 30.1.0
  does not implement it, so the dialog would be untestable. See Design Notes.
- **Never send mail**, and never add a session-listing or per-session-revocation surface.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Deactivate a Staff user | `POST /admin/users/{id}/deactivate`, caller is an Administrator | `200` with the eleven-key `User`, `active: false`; every `sessions` row for that id is gone | No error expected |
| The target's live session | Target held a valid cookie before the call | Their very next request is `401` — `_SELECT_SESSION`'s `AND u.active` plus the deleted rows | No error expected |
| Deactivate the last active Administrator | Exactly one `role='admin' AND active` row, and it is the target | `409` `last_administrator`, `LAST_ACTIVE_ADMINISTRATOR`; row unchanged, sessions untouched | `409` envelope |
| Deactivate an Administrator while another active one exists | Two active Administrators | `200`, `active: false`, sessions revoked | No error expected |
| Deactivate an already-deactivated account | `active` already `false` | `200`, `active: false`, idempotent; any stray session rows still swept | No error expected |
| Reactivate | `POST /admin/users/{id}/activate` | `200`, `active: true`; **no** session is restored, no credential is reissued, `must_change_password` untouched | No error expected |
| Delete a user | `DELETE /admin/users/{id}` | `204` with no body; the row is gone and its `sessions` rows cascade | No error expected |
| Delete the last active Administrator | As the deactivate case | `409` `last_administrator`; the row still exists | `409` envelope |
| Delete an already-deactivated Administrator | Target `role='admin'`, `active=false` | `204` — a deactivated row was never counted by the floor | No error expected |
| Any verb, unknown id | `{id}` names no row | `404` `user_not_found`, `NO_SUCH_USER` | `404` envelope |
| Any verb, Staff caller | Authenticated Staff | `403` `administrator_required`, **before** the handler runs; nothing written | `403` envelope |
| Any verb, no cookie | Unauthenticated | `401` `unauthorized` | `401` envelope |
| Any verb, unclaimed Administrator | Caller still on a temporary credential | `403` from `require_claimed_user`, chained through `require_administrator` | `403` envelope |
| Self-deactivate / self-delete | Caller is the target, another active Administrator exists | Allowed; the answer lands, then the screen's refetch is `401` and the app drops to Login | No error expected |
| A deleted user's `login_attempts` | Address had a live lock | The row survives the delete by design (keyed on the address, never `users.id`) | No error expected |
| Last-Administrator, pre-flight | Row-end **Deactivate**/**Delete** pressed on the only active Administrator | The dialog opens **as the refusal**, not as a confirm — no destructive button is rendered | Refusal text, `role="alert"` |
| Stale list races the server | Client thought another Administrator was active; server disagrees | The dialog stays open and swaps to the refusal state carrying the API's own sentence | `409` rendered in the dialog |
| Cancel / Escape / scrim | Dialog open | Closes, writes nothing, returns focus to the row-end control that opened it | No error expected |

</intent-contract>

## Code Map

**Read-only sources of truth (do not edit):**

- `_bmad-output/planning-artifacts/epics.md` **lines 309–318** — Story 1.11's clauses verbatim;
  **line 203** (the worked example that settles the floor: the guard refuses "until a second
  Administrator is created"); **line 96** (UX-DR13, the `confirmation-dialog` contract); **line 116**
  (UX-DR13 is first needed here); **lines 101–103** (UX-DR16 state patterns, UX-DR17 a11y floor
  including "no color-only signaling on destructive actions", UX-DR18 one-level modal depth).
- `_bmad-output/specs/spec-rcl_camera_app/functional-requirements.md` **line 41** — FR-13, the
  canonical wording: "Revokes live sessions immediately, not just future logins — a session token
  valid before deactivation is rejected on the very next request. Deactivating/deleting the **last
  remaining** active Administrator is refused." Also **line 35** (FR-10, the list this acts from)
  and **line 39** (FR-12, the route whose contract must not widen).
- `ARCHITECTURE-SPINE.md` — **AD-3 (lines 58–62)**, whose "Prevents" clause names FR-13 by number:
  the per-request re-read of `role` and `active` is the whole of the immediacy half. **AD-4 (68)**
  the audit role holds INSERT/SELECT only — a user delete can never cascade into the audit table.
  **AD-8 (92)** no read-then-write for a counted decision. **AD-10 (104)** snapshot-not-FK.
  **Line 171** the one error envelope. **AD-5 (70–74)** is scoped to the catalogue and does **not**
  speak to users — see Design Notes.
- `AGENTS.md` — **line 13** (server-side authz on every endpoint), **line 16** (parameterized SQL
  only), **line 18** ("Never let deactivating a user leave a session live — revoke immediately, not
  just block the next login"), **line 19** (no update/delete path on the audit log), **line 22**
  (never a third role), **line 37** (never edit an applied migration).
- `EXPERIENCE.md` — **line 42** (one level of modal depth), **line 56** (`"Deactivate this account?"`
  + consequence, never a bare "Are you sure?"), **line 66** (badges stay display-only), **line 71**
  (destructive actions live in a row-end menu, never a bare icon with no label), **line 72** (the
  dialog names the object and the consequence), **line 87** (a refusal names the rule that failed),
  **line 97** (a revoked permission redirects to the highest surface the new role can reach),
  **lines 105–113** (a11y floor: 44×44px, visible focus and a keyboard path, **line 111** destructive
  is never colour-only), **lines 140–148** (Flow 3 — the canonical script for this story, including
  **line 144** the consequence sentence and **line 146** "the row's status updates to Deactivated
  inline"), and **line 148**, which is binding on the UI shape: *"the confirmation dialog itself is
  replaced by a refusal message stating why (FR-13), and no destructive action fires."*
- `DESIGN.md` — **lines 139–143** the `confirmation-dialog` block (`{colors.surface}`,
  `{rounded.lg}`, `scrim: rgba(24,24,48,0.55)`, `confirm-button: {components.button-destructive}`);
  **lines 78–81** `button-destructive`; **line 159** and **line 167** (red means destructive and
  nothing else — "the one brand color with a hard behavioral contract"); **line 194** (a modal uses
  a scrim, not a second elevation tier); **line 198** (`{rounded.lg}` is for full-screen sheets);
  **line 206** ("Requires a confirmation step before firing — the color alone isn't the safeguard");
  **line 220**; **lines 190, 210–212** (admin density, badges, `data-table-row`).
- `_bmad-output/implementation-artifacts/deferred-work.md` — **DW-90** (714–720, *this story's to
  decide*: the floor counts Administrator rows nobody can sign in as; "1.11 is meant to reuse this
  predicate — so the two must be decided together, by whoever owns that clause" — **decided here,
  see Design Notes**), **DW-50** (394–400, "Story 1.11's deactivation currently ends sessions by
  deleting rows, not by updating them" — this story makes that true), **DW-79** (626–632, a mistyped
  address is consumed until 1.10/1.11 — **the delete half closes here**), **DW-87** (690–696, an
  outstanding temporary credential is invisible; "1.10/1.11 … are the natural owners" — this story
  ships the *remove* half only, not a reissue), **DW-94** (746–752, the unconditional
  Administrator-set lock — widened here, deliberately, see Design Notes), **DW-17** (129–135,
  `updated_at` has no trigger and names 1.11 explicitly), **DW-64** (506–512, still no unlock and
  still no owner), **DW-59**/**DW-91** (466–472, 722–728, the lockout follows the account),
  **DW-58** (458–464, `login_attempts` growth), **DW-77** (610–616, no audit entry until 1.12),
  **DW-92** (730–736, a demoted Administrator stranded on a screen they cannot use), **DW-88**
  (698–704), **DW-47** (370–376, the login-commits-during-revocation race — the same shape applies
  to a deactivation).

**Files that already exist and constrain the shape:**

- `apps/api/api/users.py` (972 lines) — **the module the three routes join.** Reuse, do not
  reimplement: `router` (L114), `USER_NOT_FOUND` (L178) / `NO_SUCH_USER` (L186) / `_user_not_found`
  (L799), `LAST_ADMINISTRATOR` (L200) / `LAST_ACTIVE_ADMINISTRATOR` (L204) / `_last_administrator`
  (L809), `_SELECT_USER_FOR_UPDATE` (L705, already returns `id, email, role, active`),
  `_LOCK_ACTIVE_ADMINISTRATORS` (L732) and its `ORDER BY id` deadlock argument,
  `_UPDATE_USER`'s floor predicate (L786–L793) — the three arms to copy — and its eleven-column
  `RETURNING` list (L794–796), which the new `UPDATE` must match **character for character**
  (`_INSERT_USER` L293, `_SELECT_USERS` L455 are the other two copies). `edit_user` (L818) is the
  handler shape: sync `def`, `NO_STORE` first, `Annotated[...]` dependencies, one explicit
  `with conn.transaction():`. **Two docstring paragraphs must be rewritten**: the module's opening
  "Three routes over two paths" (L1–7) and its "**Not here.**" paragraph (L60–62, "Story 1.11 owns
  deactivating and deleting"). `EditUserRequest`'s L216–222 paragraph (a body sending
  `{"active": false}` "is a caller who believes this endpoint deactivates accounts — it does not,
  Story 1.11 owns that verb") stays true and should now point at the route that does.
- `apps/api/api/sessions.py` — `delete_sessions_for_user` (L365) and `_DELETE_USER_SESSIONS`
  (L205). **Reused, not copied.** Both docstrings currently say this has exactly one caller and that
  1.11's deactivation is delivered "through `u.active` … and the `ON DELETE CASCADE` … not by a
  function like this one" — that is now half wrong and must be corrected. `_SELECT_SESSION` (L157)
  and its `AND u.active` (L170) are the immediacy mechanism and are **not edited**: FR-13's "very
  next request" half is proved by a test, not built.
- `apps/api/api/dependencies.py` — `require_administrator`, `require_claimed_user`, `NO_STORE`,
  `ADMINISTRATOR_REQUIRED`. **Not edited.**
- `apps/api/api/db.py` — `get_connection` (L121): autocommit + `dict_row`, so a multi-statement unit
  of work needs an explicit `with conn.transaction():`.
- `apps/api/api/throttle.py` — **not edited.** Named here so the decision is visible: nothing about
  either verb touches `login_attempts`.
- `infra/migrations/20260917T1300_create_sessions.up.sql` **lines 17–21** — the `ON DELETE CASCADE`
  comment already anticipates a hard delete of a user. **No migration is added.**
- `shared/schema/shared_schema/user.py` + `ts/user.ts` — the eleven-field `User`. **Not edited.**
- `apps/api/tests/conftest.py` — `conn`, `client`, `make_user(role=, active=,
  must_change_password=, temp_credential_expires_at=, name=)` → `Account(id, email, password,
  name)`. **No fixture change is needed**; a test that needs a planted session signs one in through
  `client` as `test_session_lifetime.py` does.
- `apps/api/tests/test_admin_authorization.py` — `CREATE_USER` (L57), `EDIT_USER` (L64), the
  exact-set assertion `test_the_admin_route_table_is_the_three_routes_the_product_serves` (L435–456,
  whose own comment says "1.11 will add its own"), and the Staff-refusal + writes-nothing pattern
  at L374–402. New path constants and three more refusal tests land here.
- `apps/api/tests/test_no_registration.py` **L186–195** — the served-**path** set. Two new paths
  join it (`…/deactivate`, `…/activate`); `DELETE /admin/users/{user_id}` adds a **method** to an
  existing path and does not. The surrounding comment must say why a verb that removes access is
  not a registration surface.
- `apps/api/tests/test_forced_change_gate.py` — **no edit.** All three routes inherit the gate
  through `require_administrator`; `ALLOWED_WITHOUT_THE_GATE` (L55) gains nothing. The spec says so
  rather than leaving the next reader to check.
- `apps/api/tests/test_source_guards.py` — **no edit.** `users.py` and `sessions.py` are both
  already inside `test_the_scan_reaches_the_files_it_claims_to` (L85–102).
- `apps/web/src/screens/UserListScreen.tsx` (392) + `.module.css` (270) — **the screen that grows.**
  `Listing` (L37–40, whose "deliberately no fourth" comment is now wrong — a per-row pending state
  is needed), `asUsers` (L51), props (L104–108), `titleRef` focus rescue (L175), `load`/`generation`
  (L186–215), `retry` (L225), the six `<th>` including **Actions** (L317, whose comment already says
  "it is where Story 1.11's destructive menu goes beside it"), the row class logic (L337–342),
  `.deactivatedRow` (CSS L172), `.statusOff` (CSS L227), and the 1.10 row-end button (L374–381) with
  `.edit` (CSS L246) — the exact model for its destructive siblings. The docstring's "Deliberately
  absent" block (L136–150) is falsified by this story and must be rewritten.
- `apps/web/src/screens/EditUserScreen.tsx` (504) — the conventions to mirror, and one claim to
  correct: **L63–65** says the dialog is Story 1.11's, **L212–219** says "a modal system this
  product does not have and which Story 1.11 owns for the destructive case". Both become past
  tense. Reuse patterns: `refuse()` (L256), the single-alert-in-one-slot treatment (L361–366), the
  in-flight `disabled={submitting}` freeze, the re-entrancy guard (L306).
- `apps/web/src/api/client.ts` — `apiRequest` (L293), and critically **L320
  `if (response.status === 204) return null;`**, which is why `DELETE` may answer `204` with no
  body. `ApiRequestError` (L187), `USER_NOT_FOUND` (L145) and `LAST_ADMINISTRATOR` (L159) are
  **already exported** — this story adds no new code constant, so `error-code-parity.test.ts`'s
  export-set assertion (L120–145) needs no new row. `notifyUnauthorized` fires on status 401 only
  (L355).
- `apps/web/src/auth/SessionProvider.tsx` — the unauthorized observer (L156–185) is what turns a
  self-deactivation's next `401` into the Login screen. **Not edited**; `adoptUser` is deliberately
  not used by this screen.
- `apps/web/src/App.tsx` — `showSection` (L304), the `'users'` branch (L350–365), the status
  reconciler (L146–175). Likely **unedited**: the new controls live on `UserListScreen`, which calls
  `apiRequest` directly, as it already does for the list itself.
- `apps/web/src/styles/tokens.css` — `--color-surface` (L23), `--color-destructive` (L30),
  `--color-destructive-foreground` (L31), `--radius-lg` (L83), `--elevation-card` (L105),
  **`--scrim` (L106), declared for exactly this and referenced by nothing yet**,
  `--touch-target-min` (L116), `--measure-form` (L128), `--disabled-opacity` (L134). **No z-index
  token exists** — add one if needed (allowed: L110 "Adding is allowed, contradicting is not"), but
  never a colour.
- `apps/web/src/__tests__/user-list.test.tsx` — the harness (`stubFetch` L106 keys on **bare path**,
  `stubList` L162, `refusal` L166, `renderScreen` L171, `rowFor` L189), the exact header array
  (L255–266), and **L610–629 `offers nothing that deactivates, deletes or unlocks a row`** — the
  test this story retargets rather than deletes, whose own comment anticipates it. Its `toEqual`
  over every button name (L622) and its `queryByRole('menuitem'|'checkbox'|'combobox')` nulls
  (L626–628, L715) constrain the control shape.
- `apps/web/src/__tests__/edit-user.test.tsx` — **L722–736** (`queryByRole('dialog')` is null on the
  edit screen — must stay null), the refusal `it.each` shape (L555–600), and the full-`App`
  integration block (L749–935) that is the model for a self-deactivation test.
- `apps/web/src/__tests__/styling-wiring.test.ts` — **the every-class-is-referenced walker
  (L133–167)**: a new `.module.css` must sit **beside** its `.tsx`, every class referenced as a
  literal `styles.x`, and no class declared-but-unused. The alert-element `it.each` (L330–345)
  currently hardcodes `join(SRC, 'screens', file)` and must be widened for a component. The
  one-accent-per-screen describes (L457–495, L513–644) and **L634 `expect(css()).not.toContain
  ('box-shadow')` for the user-list module** — which is why the dialog gets its own stylesheet.
- `apps/web/src/__tests__/no-raw-values.test.ts` — no hex/colour keyword/dimension literal
  (L150–190), no bare number in a JSX inline `style={{ }}` (L192–204), no dangling `var(--…)`
  (L264–287).
- `apps/web/src/__tests__/tokens.test.ts` **L112–115** — DESIGN.md's `colors:` block is pinned at
  exactly 11. A twelfth colour fails here.
- `README.md` **lines 136–138, 145–146, 162–163, 167–170, 176–178** and `infra/README.md`
  **lines 62, 118–123, 253–254** — every sentence predicting this story or asserting that nothing on
  the list can deactivate or delete. All of them become false or need extending.

## Tasks & Acceptance

**Execution:**

- `apps/api/api/users.py` — add the three routes and only here.
  - `_DEACTIVATE_USER`: `UPDATE users SET active = false, updated_at = now() WHERE id = %s AND (…)`
    with Story 1.10's three floor arms (`role = 'staff'`, `NOT active`, the `EXISTS` over another
    active Administrator) and the eleven-column `RETURNING` list copied character for character.
  - `_ACTIVATE_USER`: the same `UPDATE` setting `active = true`, **with no floor predicate** —
    raising the active-Administrator count can never reduce it.
  - `_DELETE_USER`: `DELETE FROM users WHERE id = %s AND (…)` with the identical three arms and
    `RETURNING id`, so a zero-row result is provably the floor and not a missing row.
  - `deactivate_user`, `activate_user`, `delete_user` — sync `def`, no request body, `user_id: UUID`
    from the path, `Annotated[User, Depends(require_administrator)]`,
    `response.headers.update(NO_STORE)` first. Each opens one `with conn.transaction():` that
    issues `_LOCK_ACTIVE_ADMINISTRATORS` (deactivate and delete only, **unconditionally** — see
    Design Notes), then `_SELECT_USER_FOR_UPDATE` to tell `404` from the floor refusal, then its own
    statement, then `_last_administrator()` on zero rows. `deactivate_user` additionally calls
    `sessions.delete_sessions_for_user(conn, user_id)` **inside that transaction**.
    Response models: `User` for the two `POST`s, `status_code=204` and `response_class`-free `None`
    for the `DELETE`.
  - Rewrite the module docstring's opening ("Three routes over two paths") and its "**Not here.**"
    paragraph, which currently hands both verbs to this story. State what is still not here: no
    unlock, no credential reissue, no admin-set password, no audit entry until 1.12.
- `apps/api/api/sessions.py` — **docstring only.** `delete_sessions_for_user` and
  `_DELETE_USER_SESSIONS` both claim one caller and explicitly predict that 1.11 would *not* use
  this function. Correct both: deactivation is the second caller, and say why the cascade alone is
  not enough (a reactivation would otherwise resurrect sessions the Administrator revoked).
- `apps/api/tests/test_deactivate_user.py` — **new.** The deactivate and activate matrix rows: the
  happy path and the returned row; **the live-session clause** (sign the target in through `client`,
  deactivate them, assert their very next request is `401` *and* that `sessions` holds no row for
  them); the floor refusal on the last active Administrator with a before/after column comparison
  proving nothing was written and no session was revoked; deactivation permitted with a second
  active Administrator; idempotence on an already-deactivated row; `404`; reactivation restoring
  neither a session nor a credential; self-deactivation; and a concurrent-deactivation test on two
  Administrators proving the ordered lock (two connections, as `test_edit_user.py` does for the
  concurrent demotion).
- `apps/api/tests/test_delete_user.py` — **new.** The row is gone; its `sessions` rows cascade and
  the target's cookie is `401` on the next request; the floor refusal leaves the row present; an
  already-deactivated Administrator deletes; `404`; the address is freed for reuse (closing DW-79's
  delete half); **and the `login_attempts` row for that address survives** with its lock intact.
- `apps/api/tests/test_admin_authorization.py` — add `DEACTIVATE_USER`, `ACTIVATE_USER` path
  constants; extend the exact-set assertion to the six routes the product now serves; add a
  Staff-caller refusal with a full-row before/after comparison for each new route, following
  L374–402.
- `apps/api/tests/test_no_registration.py` — add the two new paths to the served-path set with a
  comment stating why a route that removes access is not a registration surface.
- `apps/web/src/components/ConfirmDialog.tsx` + `ConfirmDialog.module.css` — **new.** The product's
  first modal. A hand-rolled `role="dialog" aria-modal="true"` element over a `--scrim` backdrop
  (**not** `<dialog>`/`showModal()` — see Design Notes), labelled by its heading and described by
  its body, focus moved into it on open and restored to the opener on close, `Escape` and a scrim
  click closing it, focus trapped between its first and last controls, all targets ≥
  `--touch-target-min`. Two states: **confirm** (body naming the person and the consequence, a
  `button-destructive` confirm and a navy-outline Cancel) and **refusal** (a `role="alert"` body
  carrying the sentence, a single Close, and **no destructive control rendered at all**).
- `apps/web/src/screens/UserListScreen.tsx` + `.module.css` — the row-end slot gains **Deactivate**
  (or **Activate**, on a deactivated row) and **Delete**, each a labelled `<button type="button">`
  with an `aria-label` naming the person, beside the existing Edit. Add the per-row pending state
  `Listing` deliberately does not carry; freeze the row's controls while its call is in flight; on
  success call the existing `load()` so the row updates inline (EXPERIENCE.md:146) and a
  self-action's next request drops the caller to Login; compute the last-active-Administrator
  pre-flight from the list already in hand so the dialog opens as the refusal (EXPERIENCE.md:148);
  render a server `409`/`404`/unexpected failure in the dialog's refusal state. Rewrite the
  docstring's "Deliberately absent" block. CSS: a `.destructive` row-end control (destructive fill,
  `--color-destructive-foreground`) — no `box-shadow`, and the screen keeps exactly one accent.
- `apps/web/src/screens/EditUserScreen.tsx` — **docstring only.** L63–65 and L212–219 predict this
  story's dialog; correct both to name the component that now exists.
- `apps/web/src/__tests__/deactivate-delete-user.test.tsx` — **new.** The dialog's copy names the
  person and the consequence; Cancel/Escape/scrim write nothing and restore focus; the confirm
  fires exactly one request; the row updates inline on success and disappears on delete; the
  pre-flight refusal renders instead of a confirm on the last active Administrator and offers no
  destructive control; a server `409` after confirm swaps the open dialog to the refusal; a
  self-deactivation drops the app to Login through the full-`App` harness (the model is
  `edit-user.test.tsx` L749–935).
- `apps/web/src/__tests__/user-list.test.tsx` — retarget **L610–629**: the verbs now exist, so the
  test becomes a statement of exactly which three controls a row carries and that nothing else
  (unlock, set-password, a `menuitem`, a `checkbox`, a `combobox`) has appeared. Update the
  all-button-names `toEqual`.
- `apps/web/src/__tests__/styling-wiring.test.ts` — widen the alert-element `it.each` to address a
  component directory; add a describe for the dialog stylesheet pinning `--scrim`, `--radius-lg`,
  `{colors.surface}`, the `button-destructive` fill and the touch-target floor.
- `apps/web/src/__tests__/edit-user.test.tsx` — **no change expected**; its
  `queryByRole('dialog')` null at L735 must still pass, which is the assertion that the dialog did
  not leak onto the edit screen.
- `README.md`, `infra/README.md` — correct every sentence listed in the Code Map that predicts this
  story or claims the list cannot deactivate or delete. Say plainly what the floor is, that a
  deactivation ends sessions immediately, that a delete is a hard delete whose sessions cascade,
  and that the address is freed for reuse.

**Acceptance Criteria:**

- **Given** a Staff user with a live session issued before the call, **when** an Administrator
  deactivates that account, **then** the target's very next request is refused with `401` — not
  their next sign-in — and no `sessions` row for that user remains.
- **Given** exactly one active Administrator account, **when** an Administrator attempts to
  deactivate **or** delete it, **then** the request is refused with `409 last_administrator`
  carrying `LAST_ACTIVE_ADMINISTRATOR`, every column of the row is unchanged, and the target's
  sessions are untouched.
- **Given** two active Administrator accounts, **when** one is deactivated or deleted, **then** the
  operation succeeds — the floor is one survivor, not two.
- **Given** an authenticated Staff caller, **when** they call any of the three new routes, **then**
  they are refused `403 administrator_required` before the handler runs, and a full-row comparison
  before and after shows nothing written — including `updated_at`.
- **Given** a deactivated user, **when** an Administrator reactivates them, **then** the account is
  active again and no session, temporary credential or password has been restored or reissued.
- **Given** a deleted user, **when** the same email address is submitted to `POST /admin/users`,
  **then** the account is created — the unique index no longer holds the address (DW-79).
- **Given** an Administrator viewing the Users list, **when** they press a row's Deactivate or
  Delete, **then** a single-level confirmation dialog opens naming that person and the consequence,
  nothing is written until they confirm, and Cancel, `Escape` or a scrim click closes it and
  returns focus to the control that opened it.
- **Given** the row is the last active Administrator, **when** its Deactivate or Delete is pressed,
  **then** the dialog opens as a refusal stating the rule, renders no destructive control, and
  fires no request — while the server independently refuses the same operation if it is reached by
  any other means (AGENTS.md:13).
- **Given** a successful deactivation, **when** the answer lands, **then** the row's status shows
  Deactivated without a page reload; **and given** a successful delete, the row is gone from the
  list.
- **Given** an Administrator deactivates or deletes their own account while another active
  Administrator exists, **when** the operation succeeds, **then** the app drops to the Login screen
  on its next request rather than leaving them on an admin surface they can no longer use.
- **Given** the change is complete, **when** `make lint` and `make test` are run, **then** both
  exit 0 and `git status --porcelain infra/migrations shared/schema` is empty — this story ships no
  migration and no contract change.

## Spec Change Log

## Review Triage Log

### 2026-09-21 — Review pass
- intent_gap: 0
- bad_spec: 0
- patch: 17: (high 1, medium 6, low 10)
- defer: 7: (high 0, medium 3, low 4)
- reject: 6: (high 0, medium 1, low 5)
- addressed_findings:
  - `[high]` `[patch]` The delete route's `_LOCK_ACTIVE_ADMINISTRATORS` was unverified — removing it left the whole API suite green, so two concurrent deletes emptying the Administrator set was unpinned. Added `test_a_concurrent_delete_cannot_slip_past_the_floor`, in the held-open-transaction shape the deactivate test already uses; mutation re-checked.
  - `[medium]` `[patch]` `ConfirmDialog`'s focus trap gave up whenever every control was disabled (`busy`), letting `Tab` walk out of the modal mid-write. Added a zero-enabled-controls branch and a panel-holds-focus branch, with a test for each.
  - `[medium]` `[patch]` `Escape` and a scrim click were not frozen while a request was in flight, so a dismissed dialog reappeared when the request failed. All three dismissal paths now read one `locked` value.
  - `[medium]` `[patch]` The confirm-to-refusal swap dropped focus to `<body>` (taking `Escape` with it) and added `role="alert"` to a reused node rather than inserting one. The panel is re-focused on a `kind` change and the two body variants carry distinct keys.
  - `[medium]` `[patch]` `run()` had no re-entrancy guard; `busy` was the only double-submit defence and was unpinned (`busy={false}` left 859 tests green). Added an `inFlight` ref and tests that now fail under that mutation.
  - `[medium]` `[patch]` `LAST_ACTIVE_ADMINISTRATOR` was copied into TypeScript with nothing holding the two languages together, on the one path where the server's own sentence is never fetched. Added a `SENTENCES` row to `error-code-parity.test.ts`.
  - `[medium]` `[patch]` Found while verifying the patches: the two new focus assertions sampled a passive effect once, immediately after an async wait, and flaked about three runs in six. Both now retry through `waitFor`; 20 consecutive suite runs clean.
  - `[low]` `[patch]` `styling-wiring.test.ts`'s widened alert check compared class and role as two independent substrings, so it passed with them on different elements. Now matched on one element.
  - `[low]` `[patch]` `test_no_registration.py`'s route-table test still named two admin routes while asserting four paths. Renamed.
  - `[low]` `[patch]` The delete confirmation body was a garden-path sentence ("Any session Kasun Perera has ends immediately"). Rewritten and re-pinned.
  - `[low]` `[patch]` `ConfirmDialog`'s docstring quoted copy the code does not produce, with gendered pronouns the implementation deliberately avoids. Now quotes the real sentence.
  - `[low]` `[patch]` `EditUserScreen`'s docstring contradicted itself within one bullet. Rewritten to "Not on this screen".
  - `[low]` `[patch]` `users.py`'s module docstring carried a stale Argon2id endpoint count, an ambiguous "this story" and one over-long line. Reflowed and corrected.
  - `[low]` `[patch]` Nothing pinned that a body sent to the three bodyless routes is ignored — the design argument for separate routes rested on it. Two tests added.
  - `[low]` `[patch]` `test_a_recreated_account_inherits_the_lock...` never attempted a login, so it did not test its own stated claim. Now drives it through `POST /auth/login`.
  - `[low]` `[patch]` Only the pending row's controls were disabled while `press()` refused every row's, leaving other rows enabled but inert. Every row's destructive controls now freeze together.
  - `[low]` `[patch]` `_plant_lock` took a parameter named `email_key` but every caller passed a raw address, working only because the fixture generates lowercase. Now folds on write.

### 2026-09-21 — Review pass
- intent_gap: 0
- bad_spec: 0
- patch: 8: (high 0, medium 4, low 4)
- defer: 2: (high 0, medium 1, low 1)
- reject: 14: (high 0, medium 2, low 12)
- addressed_findings:
  - `[medium]` `[patch]` `ConfirmDialog`'s scrim guard did not do what its own comment claimed. `event.target === event.currentTarget` rejects a click that *bubbles* out of the panel, but the gesture the comment names — dragging to select the person's name and releasing past the panel's edge — dispatches `click` on the nearest common ancestor, the scrim, and dismissed the dialog mid-read. The press origin is now recorded on `mousedown` and decides. The existing test fired `click` on the panel, so it only ever exercised the bubbling case; it is renamed, and a drag test added beside it.
  - `[medium]` `[patch]` Activate is the one verb with no confirmation step, which makes the refusal dialog the only thing that can report it failing — and nothing exercised that path. Both `run()`'s catch for `activate` and `refusalHeading`'s `activate` arm survived removal with 870 tests green. Added a test asserting the `role="alert"` sentence, the heading, and that the refusal renders no destructive control; mutation re-checked.
  - `[medium]` `[patch]` `LAST_ACTIVE_ADMINISTRATOR` named only the harder way out. EXPERIENCE.md:148 — cited in this spec's own Design Notes as the reason `activate` ships at all — tells the Administrator facing this refusal they "must activate or create a second Administrator first", and `README.md` already says "make somebody else an Administrator, or activate one, first". The one sentence they actually read did not. Extended in both languages and in the two test constants; `error-code-parity.test.ts` reads both sources, so it re-pins the new wording unchanged.
  - `[medium]` `[patch]` The acceptance criterion for a self-action names deactivate **and** delete, but only the self-deactivation was driven through the full-`App` harness; self-delete was covered at the HTTP surface only. It is not the same path — a `204` with no body, and the delete-only focus rescue firing while the shell is being torn down. Added the delete case and renamed the describe to cover both.
  - `[low]` `[patch]` The dialog's touch-target test asserted the floor through `rulesFor(global.css, 'touchTarget')`, which finds the rule by the one class the dialog does not use. Dropping the bare `button` from that selector group left the test green while every control in the dialog lost 44×44. Added `ruleGroupFor`, which keeps the selector (comments stripped, since these stylesheets argue in prose with commas in it), and pinned `button` in the group; mutation re-checked.
  - `[low]` `[patch]` `ConfirmDialog`'s focus effect justified its `shown` guard as stopping "a re-render that changes only the copy" — which an effect keyed on `[kind]` does not re-run for. The guard is real but for another reason (`StrictMode` re-runs the effect immediately after mount); the comment now says that.
  - `[low]` `[patch]` `error-code-parity.test.ts`'s module docstring counted the contracts it pins as both three and four in one sentence.
  - `[low]` `[patch]` `README.md` said "Both verbs ask first" in a paragraph that had just introduced three controls, and documented nowhere that **Activate** fires on one press with no confirmation — a deliberate asymmetry staff meet immediately.

### 2026-09-21 — Review pass
- intent_gap: 0
- bad_spec: 0
- patch: 5: (high 0, medium 2, low 3)
- defer: 3: (high 0, medium 1, low 2)
- reject: 21: (high 0, medium 3, low 18)
- addressed_findings:
  - `[medium]` `[patch]` `ConfirmDialog` opened with focus *outside itself* under
    `StrictMode` — which is how `main.tsx` mounts the app. The mount effect's
    cleanup restores focus to the opener, and the `shown` guard then read the
    remount's focus move as already done, so the dialog opened with focus on the
    row-end control behind its own scrim. `Escape` and the `Tab` trap are both
    listeners on the scrim, so from there the modal was neither trapped nor
    keyboard-dismissible. `shown` is now cleared in that cleanup; a test renders
    the screen under `StrictMode` and fails without the fix.
  - `[medium]` `[patch]` Confirming disabled the control holding focus without
    taking focus back, so in a browser focus dropped to `<body>` — outside the
    scrim, and outside both keyboard paths — for the whole in-flight window. No
    test could see it: jsdom does not blur a disabled element, and the existing
    frozen-trap test blurs by hand and then dispatches `keydown` on the dialog,
    which is exactly the delivery path a browser would no longer take. The panel
    focus effect is now keyed on `locked` as well as `kind`, with a test that
    places focus on Confirm first and fails without the fix.
  - `[low]` `[patch]` Nothing pinned the lock order both new handlers'
    docstrings call load-bearing. Swapping `_LOCK_ACTIVE_ADMINISTRATORS` and
    `_SELECT_USER_FOR_UPDATE` in either handler left the whole API suite green —
    the concurrency tests still block on the other lock and still answer `409` —
    while a demotion and a deactivation on two rows became a deadlock cycle
    answering `500`. Added a source-order test to each new module, checking the
    handler alongside `edit_user`, since the invariant is agreement between
    them; both fail under the swap.
  - `[low]` `[patch]` `LOCK_LAPSED` in `user-list.test.tsx` still carried
    `STAFF`'s id — the same duplicate-key hazard `LOCKED` was given its own row
    to avoid, one shared list away from returning.
  - `[low]` `[patch]` The delete confirmation body never named the person,
    though `ConfirmDialog`'s docstring states that the confirm body names who
    the action is about and the deactivate body does. The body is what
    `aria-describedby` points at. Reworded without reintroducing the garden-path
    sentence an earlier pass removed, and pinned.

## Design Notes

**Why the floor is one survivor, not two.** epics.md:320 reads "deactivating or deleting the last
remaining active Administrator account is refused — at least two active Administrator accounts must
always exist." Taken literally the em-dash gloss is a *different* rule: it would also refuse
deactivating the second-to-last Administrator, and it would contradict the shipped
`_UPDATE_USER` predicate that Story 1.10 built and that this story is told to reuse. Three things
select the primary clause over the gloss. FR-13 (functional-requirements.md:41), which is the
canonical machine contract, says only "the **last remaining** active Administrator is refused".
epics.md:203 works the case through: with one seeded Administrator the guard "will correctly refuse
to deactivate it **until a second Administrator is created**" — under a floor of two, creating a
second would change nothing. And `users.py:206` already ships the sentence "There must always be at
least one active Administrator." So the gloss is read as what it plainly means in context — you and
at least one other must exist at the moment of the action — and no predicate changes.

**Why DW-90 is decided rather than widened.** DW-90 observes that the floor counts `active`
Administrator rows that nobody can currently sign in as: an unclaimed credential past its 72 hours,
or a locked-out account with no unlock anywhere in this epic. It is a real hole and it is left open
deliberately. The epic's clause is worded in terms of an *active* Administrator, `active` is a
column, and widening the predicate to some notion of "usable" would require this story to invent a
definition (does a locked account count for fifteen minutes? does an unclaimed one count for
seventy-two hours?) that no document states, and to change Story 1.10's shipped behaviour to match.
One rule across all three verbs, matching the words the epic uses, is worth more than a better rule
that only two of the three enforce. DW-90 stays open with its decision recorded: not widened here,
and it is a product question rather than a handler question.

**Why deactivation deletes the session rows as well as flipping `active`.** `_SELECT_SESSION`
already joins `AND u.active`, so the very next request is a `401` the instant the flag lands — that
alone satisfies FR-13's literal clause and AD-3's mechanism, and it is why this story writes no new
session logic. It is not enough on its own for two reasons. A reactivation would bring every
still-unexpired row back to life, handing back sessions the Administrator believed they had revoked
— and once reactivation exists (see below) that is reachable in two clicks. And AGENTS.md line 18
says *revoke*, not *refuse*. `sessions.delete_sessions_for_user` already does exactly this and is
reused rather than copied; its docstring's claim that 1.11 would not need it is corrected in the
same change. A delete needs nothing extra: `ON DELETE CASCADE` on `sessions.user_id` was written
for this, and the migration says so in as many words.

**Why reactivation is in scope.** The story's clauses name two verbs, and a third route is a real
widening — flagged as `multiple-goals` in the frontmatter rather than hidden. It is included
because a deactivate with no inverse is a one-way door recoverable only with `DATABASE_URL` in
hand, which is the exact dependency Epic 1 exists to remove, and because the binding UX spine
already presumes the control exists: EXPERIENCE.md:148 tells the Administrator facing the
last-Administrator refusal that they must "**activate** or create a second Administrator first."
Activation carries no floor predicate and revokes nothing, so it adds one statement and no new rule.

**Why three routes rather than widening `PATCH`.** The obvious alternative is `active` on
`EditUserRequest`. It is refused for three reasons. `PATCH`'s body is closed and its refusal of
`{"active": false}` is pinned by a shipped test whose comment explains that the route does not
deactivate accounts. The floor predicate would then have to be evaluated against both
`COALESCE(role)` and `COALESCE(active)` in one statement, which is a harder rule to read and an
easier one to get wrong. And deactivation has a side effect an edit does not — revoking sessions —
which would put a destructive write inside a route the UI reaches on every name correction. Three
verbs with no request body at all also means no new request model, no new `extra="forbid"` surface,
and nothing for `error-code-parity.test.ts` to learn.

**Why the Administrator lock is unconditional here.** Story 1.10 issues
`_LOCK_ACTIVE_ADMINISTRATORS` only for a demotion, because the request body says whether the role
is moving to `staff`. Neither of these verbs carries a body: the target's role is not known until
a row is read, and reading the target first is precisely the lock-ordering inversion that
`_LOCK_ACTIVE_ADMINISTRATORS`'s `ORDER BY id` exists to prevent — the deadlock cycle two concurrent
operations would take. So the lock is taken on every deactivate and every delete, before the target
row's own `FOR UPDATE`. That widens DW-94's observation (a bogus id still serialises the
Administrator set) from one route to three, which is accepted rather than overlooked: the caller is
already an authenticated Administrator, these are rare operations, and the alternative — a
non-locking pre-read whose answer the predicate still overrules — is the deliberate trade-off DW-94
says should be made on its own terms and not as a drive-by here.

**Why the `login_attempts` row survives a delete.** The counter is keyed on the submitted address
and is deliberately not a foreign key to `users` (`infra/migrations/20260918T1000…`), so a delete
leaves it behind. Clearing it would make "delete the account and recreate it" an unlock — the same
lock-evasion path Story 1.10 refused to open when it carried a rename's run instead of clearing it
(DW-59). The row ages out through the existing sweep. `users.locked_until` goes with the row, which
is correct: it is a mirror of the counter, not the counter.

**Why not a native `<dialog>`.** `showModal()` would give a free focus trap, `Escape`, the top layer
and `::backdrop`. It is not available: **jsdom 30.1.0, pinned in `apps/web/package.json`, does not
implement `HTMLDialogElement.showModal` — verified in this tree, `typeof d.showModal` is
`undefined`** — so every test of the first modal in the product would have to stub the DOM API it
is testing. The dialog is therefore a hand-rolled `role="dialog" aria-modal="true"` element with an
explicit focus move, focus restore, `Escape` handler and a two-sentinel focus trap, over a
`--scrim` backdrop. EXPERIENCE.md:42 caps depth at one level, which this respects by construction:
the dialog is rendered by `UserListScreen` and nothing it contains can open another.

**Why the last-Administrator refusal is computed on the client *and* enforced on the server.**
EXPERIENCE.md:148 asks for the refusal to *replace* the confirmation dialog, which is a pre-flight
state: the Administrator must not be walked through a confirm that was never going to be honoured.
The list screen already holds every account, so the condition is one filter over data in hand. That
is a presentation decision, not a gate — AGENTS.md line 13 is satisfied because the server refuses
the same operation independently, with the same code and the same sentence, and the dialog's second
state renders that `409` verbatim when a stale list gets it wrong.

```sql
-- apps/api/api/users.py — the shape of the two guarded writes, not the code.
-- Both carry Story 1.10's floor arms, unchanged.
UPDATE users SET active = false, updated_at = now()
 WHERE id = %s
   AND (role = 'staff' OR NOT active
        OR EXISTS (SELECT 1 FROM users other
                    WHERE other.id <> users.id AND other.role = 'admin' AND other.active))
RETURNING <the eleven columns, in _INSERT_USER's order>;

DELETE FROM users
 WHERE id = %s
   AND (role = 'staff' OR NOT active
        OR EXISTS (SELECT 1 FROM users other
                    WHERE other.id <> users.id AND other.role = 'admin' AND other.active))
RETURNING id;
```

**What this story does not resolve, on purpose.** The audit log does not exist yet (Story 1.12,
DW-77), and these are the second, third and fourth privileged writes with no record of who
performed them. 1.12 inherits a harder version of its own problem here: AD-4 denies the application
role `DELETE` on the audit table and the spine draws `USER ||--o{ AUDIT_LOG_ENTRY` as a
relationship, so a hard user delete means the actor reference must be a denormalised snapshot —
AD-10's rule, which is currently written for Tiles and Reference Images only and will have to be
extended to Users. That is 1.12's decision to make, not this story's, and no private log path is
built in the meantime.

## Verification

**Commands:**

- `make lint` — expected: exit 0 (ruff check, ruff format --check, oxlint --deny-warnings,
  `tsc --noEmit`).
- `make test` — expected: exit 0; the `apps/api` database tests run against the ephemeral cluster or
  skip with the same "no PostgreSQL available" reason (DW-18/DW-39).
- `uv run pytest apps/api/tests/test_deactivate_user.py apps/api/tests/test_delete_user.py
  apps/api/tests/test_admin_authorization.py apps/api/tests/test_no_registration.py -q` —
  expected: exit 0.
- `uv run pytest apps/api/tests/test_edit_user.py apps/api/tests/test_edit_user_throttle_carry.py
  apps/api/tests/test_forced_change_gate.py apps/api/tests/test_source_guards.py
  apps/api/tests/test_create_user.py apps/api/tests/test_user_list.py
  apps/api/tests/test_session_lifetime.py apps/api/tests/test_session_lookup.py
  apps/api/tests/test_login.py -q` — expected: exit 0, **with none of those nine files modified**.
- `npm --prefix apps/web run test` — expected: exit 0, including the retargeted user-list
  assertions and `edit-user.test.tsx`'s still-null `queryByRole('dialog')`.
- `git status --porcelain infra/migrations shared/schema` — expected: empty. This story ships no
  migration and no contract change.
- `git diff --stat apps/api/api/sessions.py` — expected: docstring lines only, no statement change.
  `git diff --stat apps/api/api/dependencies.py apps/api/api/throttle.py` — expected: empty.
- Prove each new guard load-bearing by removing what it guards, then restoring it: drop
  `require_administrator` from each new route (the route-table guard and that route's Staff-refusal
  test fail), remove the floor predicate from `_DEACTIVATE_USER` and from `_DELETE_USER` (the
  last-Administrator tests fail, separately), drop `_LOCK_ACTIVE_ADMINISTRATORS` (the concurrent
  test fails), remove `delete_sessions_for_user` from the deactivate handler (the
  sessions-are-gone assertion fails while the `401` assertion still passes — which is the point of
  asserting both), add a floor predicate to `_ACTIVATE_USER` (nothing fails, which is why it has
  none), and remove the client-side pre-flight (the "opens as a refusal" test fails while the
  server `409` test still passes).

**Manual checks (if no CLI):**

- Invoke the `ui-ux-pro-max` skill and run its pre-delivery checklist against the confirmation
  dialog and the widened Users table before calling this story done (epic context: required for
  every UI story).
- `make migrate`, then `make dev`: sign in as the seeded Administrator, claim it, create a second
  Administrator and a Staff user. Sign the Staff user in in a second browser, then deactivate them
  from the first and confirm their next action in the second browser lands on Login. Reactivate and
  confirm they must sign in again rather than resuming. Delete them and confirm the address can be
  used to create a new account.
- With one active Administrator left, press Deactivate and then Delete on that row and confirm the
  dialog opens as a refusal naming the rule, with no destructive button and no request sent.
- Keyboard only: reach a row's Delete by `Tab`, open the dialog, confirm focus lands inside it,
  `Tab` cycles within it, `Escape` closes it, and focus returns to the Delete control.
- At 375px: the dialog fits without the page scrolling horizontally, every control is at least
  44×44px, the scrim covers the app bar, and the refusal text is announced.

## Auto Run Result

Status: done

**Implemented change.** Story 1.11 closes FR-13: three Administrator-only routes on the
existing `/admin/users` collection — `POST /admin/users/{user_id}/deactivate`,
`POST /admin/users/{user_id}/activate` and `DELETE /admin/users/{user_id}` — each with no
request body and each reusing Story 1.10's shipped Administrator-floor predicate, its ordered
lock, `LAST_ADMINISTRATOR`/`LAST_ACTIVE_ADMINISTRATOR` and the `409`. A deactivation flips
`active` and deletes the target's `sessions` rows in the same transaction, so the very next
request is a `401` and a later reactivation cannot resurrect them; a delete is a hard delete
whose sessions go by the `ON DELETE CASCADE` already on `sessions.user_id`. On the web, the
Users table's row-end slot gained the three verbs behind the product's first confirmation
dialog, with the last-Administrator refusal computed pre-flight from the list in hand and
enforced independently by the server. No migration, no `shared/schema` change, no audit path.

**Files changed** (since `831b9527e0ef80fc837192d26d5b9daac4657ad6`):

- `apps/api/api/users.py` — the three routes, their three statements, and the module docstring
  the story falsified.
- `apps/api/api/sessions.py` — docstrings only; `delete_sessions_for_user` now has two callers.
- `apps/api/tests/test_deactivate_user.py`, `apps/api/tests/test_delete_user.py` — new; the
  matrix, the live-session clause, the floor, the concurrency race and the lock order.
- `apps/api/tests/test_admin_authorization.py`, `apps/api/tests/test_no_registration.py` — the
  route table and the served-path set extended to the six routes the product now serves.
- `apps/web/src/components/ConfirmDialog.tsx` + `.module.css` — new; the hand-rolled modal.
- `apps/web/src/screens/UserListScreen.tsx` + `.module.css` — the row-end verbs, the per-row
  pending state, the pre-flight refusal.
- `apps/web/src/screens/EditUserScreen.tsx` — docstrings only.
- `apps/web/src/styles/tokens.css` — `--z-modal`, one non-colour token.
- `apps/web/src/__tests__/deactivate-delete-user.test.tsx` — new; the dialog and the shell.
- `apps/web/src/__tests__/user-list.test.tsx`, `error-code-parity.test.ts`,
  `styling-wiring.test.ts`, `edit-user.test.tsx` — retargeted and widened.
- `README.md`, `infra/README.md` — every sentence that predicted this story.

**Review findings, this pass** (the third; the first two are in the Review Triage Log above):
5 patches applied (2 medium, 3 low), 3 items deferred (1 medium, 2 low), 21 rejected. Both
medium patches were real focus defects in the product's first modal that no existing test could
observe — one under `StrictMode`, which is how `main.tsx` mounts the app, and one caused by
disabling the control that held focus, which jsdom does not simulate. Both now have tests that
fail without the fix. Rejected as noise or as settled by design: CSRF on the three new routes
(the session cookie is `SameSite=Strict`), a scrim drag that begins on the backdrop and releases
inside the panel (dismissing is the convention Radix and MUI both take), `updated_at` moving on
an idempotent no-op (that is what the column records), shipping a hard delete before the audit
log (this spec's own Block-If, with 1.12 owning it), and eight findings that restate items
already on the `deferred` list.

**Follow-up review recommendation: true.** Patched this pass: high 0, medium 2, low 3.
Score = 3 × 2 + 1 × 3 = 9, which is ≥ 5.

**Verification performed:**

- `make lint` — exit 0 (ruff check, ruff format --check, oxlint --deny-warnings, `tsc --noEmit`).
- `make test` — exit 0: 844 API tests passed against the ephemeral cluster, 872 web tests
  passed across 18 files.
- `git status --porcelain infra/migrations shared/schema` — empty.
- `git diff apps/api/api/sessions.py` — docstring prose only, no statement changed.
  `git diff --stat apps/api/api/dependencies.py apps/api/api/throttle.py` — empty.
- The nine files the Verification section pins as unmodified are all unmodified.
- Each patch re-checked by mutation: reverting `ConfirmDialog`'s two focus changes fails the two
  new focus tests and nothing else; swapping `_LOCK_ACTIVE_ADMINISTRATORS` and
  `_SELECT_USER_FOR_UPDATE` in either handler fails that handler's new source-order test.

**Residual risks:**

- Twelve items sit on the `deferred` list, three of them added this pass. The heaviest are
  product decisions this story deliberately did not take: what a modal owes the page behind it
  (`inert`, scroll lock, a pending/confirmed announcement), where focus belongs after a row verb
  rewrites its own row-end control, and whether the address's lockout should be visible on a row
  it is not keyed to.
- The last-Administrator floor counts `active` Administrator rows nobody can necessarily sign in
  as — an unclaimed credential past its 72 hours, or a locked-out account. DW-90, decided here
  rather than widened, with the reasoning in Design Notes.
- No audit entry exists for any of these three writes until Story 1.12, which inherits a harder
  problem from the hard delete: AD-4 denies the application role `DELETE` on the audit table, so
  the actor reference has to become an AD-10 snapshot, a rule currently written for Tiles and
  Reference Images only.
- `make eval` and the UI skill's pre-delivery checklist are manual checks this unattended run
  could not perform.
