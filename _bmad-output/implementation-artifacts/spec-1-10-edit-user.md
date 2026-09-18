---
title: 'Story 1.10 — Edit User'
type: 'feature'
created: '2026-09-18'
baseline_revision: 'f919d807c407c03ab10111bfd2d1932c3e0e5dff'
status: 'done'
review_loop_iteration: 0
followup_review_recommended: true # score 12 (0 high, 1 medium, 9 low patched this pass); see Auto Run Result
context:
  - '{project-root}/AGENTS.md'
  - '{project-root}/_bmad-output/planning-artifacts/architecture/architecture-rcl_camera_app-2026-08-30/ARCHITECTURE-SPINE.md'
  - '{project-root}/_bmad-output/planning-artifacts/ux-designs/ux-rcl_camera_app-2026-09-08/EXPERIENCE.md'
  - '{project-root}/_bmad-output/planning-artifacts/ux-designs/ux-rcl_camera_app-2026-09-08/DESIGN.md'
warnings: ['oversized']
deferred:
  - summary: >-
      The Administrator floor counts Administrator rows nobody can currently
      sign in as, so the last *usable* Administrator can still be demoted.
    evidence: |-
      `_UPDATE_USER`'s predicate is `other.role = 'admin' AND other.active`. It
      ignores `must_change_password` / `temp_credential_expires_at`, and
      `api/auth.py` refuses a login whose temporary credential has lapsed (a NULL
      expiry counts as lapsed, DW-44), so an active `admin` row holding an
      unclaimed, expired credential satisfies the floor while being unusable by
      anyone. A locked-out Administrator is the same hole with a 15-minute
      lifetime, and this epic ships no unlock. Widening the predicate here would
      make it a different rule from the one Story 1.11 states for deactivate and
      delete, and 1.11 is meant to reuse this predicate — so the two must be
      decided together, by whoever owns that clause.
    location: >-
      apps/api/api/users.py (_UPDATE_USER, the floor predicate)
    severity: medium
  - summary: >-
      Correcting a mistyped address onto an address that already carries a live
      lockout hands that lock to the account, with nothing anywhere to end it.
    evidence: |-
      `_CARRY_FAILURES` merges with `GREATEST`, which is the conservative
      direction for the rename-evasion case DW-59 is about, and the new mirror
      keeps `users.locked_until` honest about it. The cost runs the other way: an
      address guessed at while it belonged to nobody carries a run, and an
      Administrator correcting a typo onto it locks the account for
      `LOCKOUT_DURATION`. There is no unlock in Epic 1 (DW-64), so the whole of
      the recovery is waiting 15 minutes — which sits awkwardly beside README's
      new claim that a mistyped address is no longer a dead end. Closing it means
      either an unlock surface or a rule that a carry never imports a run the
      account did not make, and both are product decisions.
    location: >-
      apps/api/api/throttle.py (carry_failures)
    severity: medium
  - summary: >-
      A 403 on save leaves an Administrator demoted mid-edit sitting on an editor
      they can no longer use, until something else revalidates the session.
    evidence: |-
      `fieldFor` returns `null` for `administrator_required` and the screen
      renders the server's sentence, but nothing revalidates the session or
      leaves the screen, so every subsequent Save fails the same way until the
      tab is backgrounded and brought back (the only thing that triggers
      `SessionProvider`'s revalidation). This is the same shape as Story 1.9's
      deferred "Try again forever" finding on `UserListScreen`, and the fix is
      the same one: a shared answer to "the server says you are no longer an
      Administrator" that neither screen currently has.
    location: >-
      apps/web/src/screens/EditUserScreen.tsx
    severity: medium
  - summary: >-
      The unsaved-changes warning guards only the screen's own Back control;
      every other way off the screen still discards a half-typed edit silently.
    evidence: |-
      `handleBack` warns, but `App.showSection` clears `editing` unconditionally,
      so the app bar's Account control, Sign out and the role reconciler's
      demotion drop all leave without a word, and there is no `beforeunload`
      handler for a closed tab. EXPERIENCE.md line 90 asks for the general rule —
      never silently drop an in-progress admin form — and DW-81 records that the
      convention the product does not have lands on every admin form. This story
      built the narrow guard; the general one is still owed, and it belongs with
      whichever story introduces the second admin form.
    location: >-
      apps/web/src/App.tsx (showSection) and screens/EditUserScreen.tsx
    severity: low
  - summary: >-
      A demotion body sent against an id that names no row still locks every
      active Administrator row for the life of the transaction.
    evidence: |-
      `_LOCK_ACTIVE_ADMINISTRATORS` is issued whenever the requested role is
      `staff`, ahead of `_SELECT_USER_FOR_UPDATE`, so a loop of `PATCH
      {"role": "staff"}` at a bogus id serialises every user edit in the product
      while writing nothing — and this endpoint carries no throttle (DW-40/DW-69).
      The caller must already be an Administrator, which bounds the damage. The
      obvious fix, reading the row first, is what the lock ordering was chosen to
      avoid: locking the target before the Administrator set is the deadlock cycle
      two concurrent demotions would take. Closing it safely means a non-locking
      pre-read whose answer the `UPDATE` predicate still overrules, which is a
      trade-off worth making deliberately rather than as a review patch.
    location: >-
      apps/api/api/users.py (edit_user, the lock ordering)
    severity: low
  - summary: >-
      A refusal raised by request-model validation carries no `cache-control`,
      on this endpoint and on every other one in the product.
    evidence: |-
      `api/main.py`'s `validation_error_handler` builds its own response and sets
      no headers, so every `422 validation_error` — the empty body, the explicit
      null, the unknown field, the malformed UUID — answers without `no-store`
      while every other answer this handler produces carries it.
      `test_every_answer_this_handler_produces_carries_no_store` says so in its
      own comment and excludes those rows. The bodies carry no account data, so
      nothing sensitive is cacheable today; the hole is that the rule "every
      authenticated response is `no-store`" has an exception nothing states
      outside one test comment. Fixing it is a change to the shared handler and
      therefore to every endpoint at once, which is not this story's to make.
    location: >-
      apps/api/api/main.py (validation_error_handler)
    severity: low
  - summary: >-
      The refusal sentences a screen renders are pinned in TypeScript literals,
      so the two languages can drift on wording without a test noticing.
    evidence: |-
      `error-code-parity.test.ts` compares the envelope *codes* and the numeric
      bounds across the boundary, which is what the story's Always clause asks
      for. The *sentences* are different: `edit-user.test.tsx` asserts against
      hand-copied copies of `NOT_AN_ADDRESS`, `ALREADY_IN_USE`, `NO_SUCH_USER`
      and `LAST_ACTIVE_ADMINISTRATOR`, and says so in its own docstring. The
      same is already true of `create-user.test.tsx`, so this predates the
      story and is a property of how every screen in the product is tested; a
      rule change here belongs with whatever first needs the wording pinned.
    location: >-
      apps/web/src/__tests__ (edit-user, create-user, error-code-parity)
    severity: low
  - summary: >-
      The parameterized-SQL guard inspects one line at a time, so no multi-line
      f-string statement in the product has ever been looked at.
    evidence: |-
      `INTERPOLATED_SQL`'s first pattern is `f["'].*\bVERB\b[^"']*\{` matched
      per line, so it only fires where the `f"` opener, a SQL verb and a
      substitution all sit on one line. Every SQL constant in `api/throttle.py`
      is a triple-quoted f-string whose opener line is bare, so `_SELECT_ATTEMPTS`
      and `_RECORD_FAILURE` were already invisible to it at this story's
      baseline and `_CARRY_FAILURES` joins them. Nothing is injectable today —
      every interpolated name is a module-level constant, and `_RUN_ENDED`'s own
      comment says so — but AGENTS.md Policy's parameterized-SQL line is held by
      this guard, and the guard cannot see the shape the product actually uses.
      Closing it means teaching the check to read a statement rather than a
      line, in `tests/test_source_guards.py` — one of the six files this spec's
      Verification pins as unmodified, and a change that re-scores every module
      at once.
    location: >-
      apps/api/tests/test_source_guards.py (INTERPOLATED_SQL)
    severity: medium
  - summary: >-
      A throttle test still describes the Story 1.10 unlock in the future tense,
      in a file this story may not modify.
    evidence: |-
      `apps/api/tests/test_login_throttling.py:689` reasons that "the way that
      gets noticed for real is Story 1.10 growing an 'unlock' that clears the
      mirror". Story 1.10 has now shipped without one, and every other copy of
      that prediction — `throttle.py`, `auth.py`, `README.md`, and
      `infra/README.md` this pass — was corrected. This one was not, because
      this spec's Verification pins that file as unmodified precisely to prove
      the story changed no existing throttle behaviour. Correcting a docstring
      there is safe but breaks a stated verification, so it is a call for
      whoever next has reason to open the file.
    location: >-
      apps/api/tests/test_login_throttling.py:689
    severity: low
---

<intent-contract>

## Intent

**Problem:** Story 1.9 shipped the list and said in as many words that nothing on a row can be
changed. FR-12 and epics.md 1.10 ask for the three fields that go stale — name, email and role —
and for a role change to land on the user's *live* session rather than at their next sign-in. Today
a mistyped address is permanently consumed (DW-79), a promotion needs a developer with
`DATABASE_URL`, and a renamed person keeps the name they were provisioned under.

**Approach:** One more route on the collection `api/users.py` already serves —
`PATCH /admin/users/{user_id}`, Administrator-only through the same `require_administrator`
dependency — writing name, email and role in one guarded `UPDATE` and returning the same eleven-key
`User` the other two routes return. The live-session half needs no mechanism: AD-3's
`lookup_session` already re-reads `role` and `active` from Postgres on every request, so this story
*proves* the immediacy rather than building it. On the screen, a row-end **Edit** control opens a
new `EditUserScreen` pre-filled from the row, which sends only the fields that changed and reports
the API's own sentence on refusal.

## Boundaries & Constraints

**Always:**

- **Authorization is the dependency, never a line in the handler.** The route lives under `/admin/`
  and declares `require_administrator`, which chains on `require_claimed_user`.
  `tests/test_admin_authorization.py` reads both directions off the route table.
- **Parameterized SQL only**, one statement per decision, no SQL assembled from a value
  (`tests/test_source_guards.py`). `users` has no `BEFORE UPDATE` trigger (DW-17), so every writer
  sets `updated_at = now()` by hand — this one included.
- **`login_attempts` is written only by `api/throttle.py`** (AD-8, enforced by
  `test_source_guards.py::test_only_one_module_writes_the_login_attempts_table`). Anything this
  story needs from that table is a function added *there* and called from `users.py`.
- **The `RETURNING` list is `_INSERT_USER`'s and `_SELECT_USERS`'s, character for character** —
  the same eleven columns in the same order, so `User.model_validate` is handed one shape by every
  statement in the product that produces it.
- **The address is folded by Postgres (`lower(%s)`), not by Python**, for the reason `_INSERT_USER`
  states: `users` carries `CHECK (email = lower(email))` and `str.lower()` and Postgres's `lower()`
  are not guaranteed to agree on non-ASCII input.
- **The epic's Administrator floor holds through this route too.** A role change that would leave
  the product with no active Administrator is refused, by a predicate inside the `UPDATE` rather
  than by a check taken a moment earlier.
- **One contract in two languages.** A new envelope code gets its TypeScript twin in
  `apps/web/src/api/client.ts` *and* a row in `error-code-parity.test.ts`, whose last test fails on
  any exported client code with no Python row.
- **The token layer is the only styling source** — no raw hex or dimension literal outside
  `tokens.css` (`no-raw-values.test.ts`), exactly one `--color-accent` control per screen,
  at least 44x44px targets, and a state never signalled by colour alone.

**Block If:**

- Honouring any part of this story appears to require relaxing an AGENTS.md Policy line (server-side
  authorization, parameterized SQL, no committed credential, no role beyond `staff`/`admin`).

**Never:**

- **No unlock, no credential reissue, no admin-set password, no `active` toggle, no delete.**
  `throttle.py`, `auth.py` and `README.md` all predict an admin unlock "in Story 1.10"; epics.md
  1.10 (lines 296–307) scopes this story to name, email and role and names neither a lock nor an
  unlock, and a story may not widen another story's acceptance clauses. This story instead makes
  those three claims *true statements about the product* by correcting them — see the Tasks. DW-64
  stays open, now with no owner in Epic 1, and this spec says so rather than leaving the next reader
  to discover it.
- **No writable `must_change_password`, `temp_credential_expires_at`, `password_hash`, `active`,
  `last_login_at`, `locked_until` or `id`.** The request body is closed (`extra="forbid"`) and names
  three fields; the other eight are not things a caller may supply.
- **No audit entry, and no private log path in the meantime.** Story 1.12 owns the append-only log
  and is owed one by this endpoint; until it exists the only trace of an edit is `updated_at`.
- **No optimistic-concurrency token, no `If-Match`, no "someone else changed this" dialog.** DW-63
  leaves what `updated_at` is *for* undecided; last write wins, and sending only the changed fields
  is this story's whole mitigation.
- **No confirmation-dialog system, no modal, no destructive treatment anywhere on these surfaces.**
  Editing is not destructive; 1.11 owns the confirm dialog EXPERIENCE.md describes.
- **No second list surface, no search, no sort control, no pagination** — FR-10's list is unchanged
  except for the door to this screen.
- **No route beyond the one**, and no separate `GET /admin/users/{id}`: the row is already in hand
  on the screen that opens the editor.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|---|---|---|---|
| Rename | Claimed Administrator; `PATCH /admin/users/{id}` with `name` padded with spaces | `200`, the eleven-key `User` with `name` stripped, `updated_at` moved, every other column untouched, `cache-control: no-store` | No error expected |
| Readdress | `{"email": "Ruwan@Rocell.LK"}` | `200`, `email` stored and returned as `ruwan@rocell.lk`; the account signs in with the new address and not the old one | No error expected |
| Promote | Target is Staff; `{"role": "admin"}` | `200` with `role: "admin"`; the target's **next** request is served as an Administrator with no re-login | No error expected |
| Demote | Target is an Administrator, another active Administrator exists; `{"role": "staff"}` | `200` with `role: "staff"`; the target's next request to an `/admin/` route is `403 administrator_required` | No error expected |
| All three at once | `{"name","email","role"}` | `200`, all three written in one statement, one `updated_at` | No error expected |
| Self-edit | Caller edits their own row | `200`; caller's own row returned, and the screen adopts it as the session's cached `User` | No error expected |
| Last Administrator demoted | Target is the only active Administrator; `{"role": "staff"}` | `409 last_administrator`, nothing written | The refusal is a predicate inside the `UPDATE`, not a check taken earlier |
| Demote a deactivated Administrator | Target `active = false`, no other active Administrator | `200` — a deactivated account is not one of the active Administrators the floor counts | No error expected |
| Unknown id | `{id}` names no row | `404 user_not_found`, nothing written | Distinguished from the refusal above by the locking read, not by guesswork |
| Malformed id | `{id}` is not a UUID | `422 validation_error` from FastAPI's own path parsing | Generic envelope; no row is read |
| Address already in use | New address is another account's, in any case | `409 email_already_exists`, nothing written | Built from `users_email_lower_key` by name; any other unique clash propagates as a 500 |
| Address is not one | `ruwan.rocell.lk`, `a@b@c`, an interior space, a control character | `422 invalid_email` with the rule-naming sentence | Reuses `_normalize_email`, `INVALID_EMAIL`, `NOT_AN_ADDRESS` |
| Blank or control-character name | `{"name": "   "}`, or a name carrying a NUL byte | `422 validation_error` | Raised by the shared `_clean_name`, the same rule `POST` applies |
| Explicit null | `{"name": null}` | `422 validation_error` | A `mode="before"` validator refuses `None`; absent and null are not the same request |
| Empty body | `{}` | `422 validation_error` | A `model_validator` requires at least one field, so no request bumps `updated_at` for nothing |
| Unknown field | `{"active": false}` | `422 validation_error` | `extra="forbid"` |
| Staff caller | Claimed Staff session | `403 administrator_required`, nothing written, never a `401` | From the dependency, before the body is validated |
| Unclaimed Administrator | Administrator still on a temporary credential | `403 password_change_required` | `require_claimed_user` fires first; no allowlist entry in `test_forced_change_gate.py` |
| No session | No cookie | `401 unauthorized` with the challenge and the cookie clearance | `current_user` |
| Rename carries the counter | Address had recorded failures and/or a live lock | The run moves to the new address: the lock still holds there and the old key is gone | `throttle.carry_failures`, inside the same transaction as the write (DW-59) |
| Rename onto a key with its own run | New address already has `login_attempts` rows (it was never an account) | The two runs merge, the stricter of the two surviving each column | Same statement, `GREATEST` on conflict |
| Screen: open the editor | Administrator presses a row's **Edit** | The edit screen opens pre-filled with that row's name, email and role | No error expected |
| Screen: no changes | Save pressed with nothing edited | Nothing is sent; an inline "Nothing has changed." | No request at all |
| Screen: partial send | Only the role was changed | Body carries `role` alone | — |
| Screen: refusal | API answers `invalid_email` / `email_already_exists` / `last_administrator` / `user_not_found` | One `role="alert"` carrying the API's own sentence; the first three mark and focus the field at fault (email, email, role) | `user_not_found` and `administrator_required` mark nothing |
| Screen: save indicator | Request in flight, then done | `Saving…` then `Saved.` inline beside the control, never a corner toast | — |
| Screen: unsaved Back | Back pressed with edits outstanding | The screen stays, warning that changes will be lost; a second press leaves | — |
| Screen: self-demotion | Administrator demotes themselves | The saved row is adopted as the cached session user; the shell drops to the home panel and the Users door disappears | — |

</intent-contract>

## Code Map

**Read-only sources of truth (do not edit):**

- `_bmad-output/planning-artifacts/epics.md` **lines 296–307** — Story 1.10's clauses verbatim;
  also **309–318** (1.11, which owns deactivate/delete and the last-Administrator refusal this
  story mirrors for a demotion).
- `_bmad-output/specs/spec-rcl_camera_app/functional-requirements.md` — **FR-12** (line 46: "Name,
  email, or role. A role change takes effect on the user's *live* session, not only at next
  authentication"), **FR-13** (line 47, the Administrator floor), **FR-10** (line 42, the list this
  edits from), **FR-5** (line 20, the recovery route with no owner — see Design Notes).
- `AGENTS.md` — server-side authorization on every endpoint; parameterized SQL; never a third role;
  security paths need failure-case tests; no committed credential in a fixture.
- `ARCHITECTURE-SPINE.md` — **AD-3** (role and `active` re-read per request through the one session
  lookup: the whole of FR-12's "live session" half) and the Consistency Conventions table (UUIDv4,
  ISO 8601 UTC, one error envelope).
- `EXPERIENCE.md` — **line 34** ("Create/Edit User | User List row / '+ Add User'"), **line 66**
  (role and status badges are display-only, never a button), **line 71** (data table row: dense,
  row click opens detail, row-end actions are labelled, never a bare icon), **line 90** (never
  silently drop an in-progress admin form), **line 92** (Save indicator cycles `Saving…` to
  `Saved.` inline, never a corner toast), **line 95** (a revoked permission redirects to the highest
  surface the new role can reach; a role change needs no toast), **line 87** (a rejection names the
  rule that failed), **line 113** (accent foreground is navy).
- `DESIGN.md` — the form, button and `data-table-row` component blocks the two admin screens already
  compose from; **line 190** (admin density tier), **line 198** (`{rounded.full}` for badges only).
- `_bmad-output/implementation-artifacts/deferred-work.md` — **DW-59** (a rename strands the lock on
  the old address string; "deciding whether a rename carries its counter is Story 1.10's to make" —
  **this story makes it**), **DW-79** (a mistyped address is consumed until this story can edit it —
  **closed by this story**), **DW-64** (FR-4's lock and FR-5's unlock; the unlock half stays open and
  loses its predicted owner), **DW-17** (`updated_at` has no trigger), **DW-63** (what `updated_at`
  is for, and whether the throttle mirror should move it), **DW-44** (`must_change_password` without
  an expiry is a bricked account — the reason this route cannot set that flag), **DW-81** (the
  unsaved-admin-form warning "lands on every admin form from Story 1.10 on"), **DW-71** (the list
  shows neither `must_change_password` nor `temp_credential_expires_at`).

**Files that already exist and constrain the shape:**

- `apps/api/api/users.py` — **the module this route joins.** `router` (L76), `INVALID_EMAIL` (L79),
  `NOT_AN_ADDRESS`, `EMAIL_ALREADY_EXISTS`, `ADDRESS_ALREADY_IN_USE`, `EMAIL_UNIQUE_INDEX` (L115),
  `MAX_NAME_LENGTH` (L121), `BLANK_NAME`/`CONTROL_IN_NAME`, `_has_control_character` (L133),
  `CreateUserRequest._named` (L186) — **the name rule to extract and share**, `_normalize_email`
  (L207), `_INSERT_USER` (L293) and `_SELECT_USERS` (L455) whose eleven-column lists the new
  statement must match character for character, `_invalid_email`/`_email_already_exists` (L316–336),
  `create_user` (L347) and `list_users` (L487) for the handler conventions: sync `def`,
  `response.headers.update(NO_STORE)` first, `Annotated[...]` dependencies, `#:` blocks above every
  module-level constant arguing *why*, SQL as an `_UPPER_SNAKE` triple-quoted constant directly
  above its handler. The module docstring's "**Not here.**" paragraph (L60) and its "Two routes over
  one path" opening both need rewriting.
- `apps/api/api/throttle.py` — **the only module that may write `login_attempts`.**
  `_CLEAR_ATTEMPTS` (L226), `clear_failures` (L394) for the shape of a public helper, `_MIRROR_LOCK`
  (L216) and the module docstring's "`login_attempts` decides, `users.locked_until` reports"
  paragraph, which is what makes carrying the run the correct direction. The new
  `carry_failures` goes here.
- `apps/api/api/dependencies.py` — `require_administrator`, `NO_STORE`, `ADMINISTRATOR_REQUIRED`.
  **Not edited**; its docstring already states the both-directions rule the third route inherits.
- `apps/api/api/sessions.py` — `lookup_session`, the one session read (AD-3). **Not edited**; it is
  what makes a role change immediate, and this story only tests it.
- `apps/api/api/db.py` — `get_connection` (L121); autocommit and `dict_row`, so a multi-statement
  unit of work needs an explicit `with conn.transaction():`.
- `apps/api/api/main.py` — `create_app()` already includes `users.router` (L177). **Not edited.**
- `shared/schema/shared_schema/user.py` + `ts/user.ts` — the eleven-field `User`, `Role`,
  `extra="forbid"`, `isUser`. **Not edited**; this story adds no field and no contract change.
- `apps/api/tests/test_admin_authorization.py` — `CREATE_USER` (L57) and the exact-set assertion
  `test_the_admin_route_table_is_the_two_routes_the_product_serves` (L379), which says in its own
  comment that 1.10 is meant to make it fail. That and the constant's comment are the only edits.
- `apps/api/tests/test_no_registration.py` — the served-**path** set (L176–184).
  `/admin/users/{user_id}` is a **new path**, so unlike Story 1.9 this assertion *does* change, and
  its surrounding comment must say why an edit route is not a registration surface.
- `apps/api/tests/test_forced_change_gate.py` — **no edit**: the new route inherits the gate through
  `require_administrator` and needs no allowlist entry. The spec says so rather than leaving the
  next reader to check.
- `apps/api/tests/test_source_guards.py` — `users.py` and `throttle.py` are both already named in
  `test_the_scan_reaches_the_files_it_claims_to` (L100): **no edit**.
- `apps/api/tests/conftest.py` — `conn`, `client`, `make_user(role=, active=,
  must_change_password=, temp_credential_expires_at=, name=)` returning `Account(id, email,
  password, name)`. A test that needs a `locked_until` or a `login_attempts` row writes it through
  `conn`, as `test_login_throttling.py` does. **No fixture change is needed.**
- `apps/api/tests/test_login_throttling.py` — L86, L851, L948 show how a counter row and a lock are
  planted and read in a test; the carry tests are written the same way.
- `apps/web/src/api/client.ts` — `apiRequest(path, {method, body})` (L266), `ApiRequestError`
  (L160), `MALFORMED_RESPONSE` (L141), `INVALID_EMAIL`, `EMAIL_ALREADY_EXISTS`, and
  `notifyUnauthorized` on **status 401 only** (L328). Two new exported codes land here.
- `apps/web/src/auth/SessionProvider.tsx` — `SessionContextValue` (L32), the revalidation effect
  (L165–208) whose `setUser(asUser(body))` is exactly what an adopted self-edit does, `asUser`
  (L90), and the `useMemo` value (L290). One new member.
- `apps/web/src/screens/UserListScreen.tsx` — the list this edits from: `Listing` (L36), `asUsers`
  (L52), `load`/`generation` (L160–200), the table and its five `<th scope="col">` headings, the row
  class logic, and the docstring's "**No edit, deactivate, delete, unlock or row-end menu**"
  paragraph, which is now half wrong.
- `apps/web/src/screens/UserListScreen.module.css` — `.screen`, `.title`, `.actions`, `.add`,
  `.back`, `.scroller`, `.table`, `.heading`, `.row`, `.cell`, the badge classes. The row-end control
  is modelled on `.back`.
- `apps/web/src/screens/CreateUserScreen.tsx` + `.module.css` — **the model for the new screen**:
  `FormError`/`fieldFor` (L113–128), the one-alert-in-one-slot treatment, `typed()`, `refuse()`,
  `asUser` (L146), the `noValidate` form, the mirrored `MAX_*` bounds (L88–100), `.submit` (accent) /
  `.back` (navy outline) / `.indicator` (`role="status"`) rhythm, and the `ROLES`-driven `<select>`.
  Edited only in its docstring, where it says Stories 1.10/1.11 own editing.
- `apps/web/src/App.tsx` — `Section` (L29), `Screen` (L42), `reachableBy` (L55) — *the one statement
  of which surfaces a role reaches* — `currentScreen` (L60), the two render-phase reconcilers (L107,
  L131), `showSection` (L255), and the `'users'`/`'create-user'` branches (L292, L310).
- `apps/web/src/__tests__/user-list.test.tsx` — the row/badge/class assertions and, critically, the
  test asserting **no control on the screen edits anything**: it is retargeted, not deleted.
- `apps/web/src/__tests__/create-user.test.tsx` — the `stubFetch` keyed on method plus path, and the
  home-panel-door block, which is the model for the new screen's App-level tests.
- `apps/web/src/__tests__/error-code-parity.test.ts` — the `PYTHON`/`TYPESCRIPT` maps (L70–91), the
  "compares every code the client exports" test (L114), and the `BOUNDS` block (L152–180), whose
  `SCREEN` constant is currently a single path and must become per-row.
- `apps/web/src/__tests__/styling-wiring.test.ts` — the `.error`-colour cases (L230–290), the
  alert-element `it.each` (L319), the one-accent-per-screen describes (L396, L461), and the
  every-class-is-referenced walker (L133).
- `README.md` **lines 109, 117–133, 151–166, 176–180, 186–190** — the operator narrative: "changing
  either is an Administrator's job (Story 1.10)", "the address they were first given stays consumed
  until Story 1.10 can edit it", "an admin unlock is Story 1.10's to add", "**The lock clears
  itself; there is no admin unlock and none is owed until Story 1.10.**", "Nothing on the list can be
  edited or deactivated yet". Every one of those sentences is false or misleading after this change.

## Tasks & Acceptance

**Execution:**

- `apps/api/api/throttle.py` — add the counter carry, and only here.
  - `_CARRY_FAILURES`: one `INSERT ... SELECT ... ON CONFLICT (email_key) DO UPDATE` that copies the
    old key's row onto the new key, taking `GREATEST` of `failure_count`, `locked_until` and
    `last_failure_at` where the new key already had a row. A `#:` block arguing the direction: the
    run belongs to the person whose address it is, `GREATEST` ignores NULLs in Postgres so "no lock"
    never wins over a live one, and a rename must not be the unlock this epic does not have.
  - `carry_failures(conn, old_key, new_key) -> None`: the carry then `_CLEAR_ATTEMPTS` on the old
    key, both inside the caller's transaction (it opens none of its own — the caller's write and
    this must commit together or not at all). A no-op when `old_key == new_key`, and harmless when
    the old key has no row. Docstring: why this is not `clear_failures` (clearing would make a
    rename a lock-evasion path an Administrator can walk, DW-59), and why `users.locked_until` is
    **not** touched — the mirror already matches the carried lock, and the column is history that is
    never cleared.
- `apps/api/api/users.py` — the edit, beside the write and the read.
  - Extract `CreateUserRequest._named`'s body into a module-level `_clean_name(value: str) -> str`
    (strip, refuse blank with `BLANK_NAME`, refuse a control character with `CONTROL_IN_NAME`) and
    call it from both request models, so there is one opinion about what a storable name is.
  - `USER_NOT_FOUND = "user_not_found"` with its sentence, and `LAST_ADMINISTRATOR =
    "last_administrator"` with its own, each carrying a `#:` block: why `404` rather than a silent
    no-op (an Administrator holding a list from before a deletion has to be told the row is gone),
    and why `409` rather than `403` (nothing is wrong with the caller's authority — the product's
    state refuses the change).
  - `EditUserRequest`: `model_config = ConfigDict(extra="forbid")`; `name: str | None`,
    `email: str | None`, `role: Role | None`, all defaulting to `None` and bounded exactly as
    `CreateUserRequest` bounds them. A `mode="before"` validator over all three refusing an explicit
    `None` (absent means "leave it"; `null` is a caller with a different idea of the contract), a
    `name` validator calling `_clean_name`, and a `model_validator(mode="after")` requiring at least
    one field — so no request in the product moves `updated_at` for nothing.
  - `_SELECT_USER_FOR_UPDATE`: `SELECT id, email, role, active FROM users WHERE id = %s FOR UPDATE`.
    It is what distinguishes `404` from the refusal below, and what hands the handler the *old*
    address the carry needs. `#:` block: PostgreSQL 18's `RETURNING OLD.*` would have replaced it and
    is deliberately not used — this repo's SQL stays inside what a 16.x test cluster also has, which
    the migrations state in as many words.
  - `_LOCK_ACTIVE_ADMINISTRATORS`: `SELECT id FROM users WHERE role = 'admin' AND active ORDER BY id
    FOR UPDATE`, issued **only** when the requested role is `staff`. `#:` block: it is what makes the
    floor guard airtight rather than nearly airtight — two Administrators demoting each other at the
    same instant would otherwise both read the other as still present — and `ORDER BY id`, taken
    before the row lock below, is what keeps two concurrent demotions from deadlocking.
  - `_UPDATE_USER`: one statement, `SET name = COALESCE(%s::text, name), email =
    COALESCE(lower(%s::text), email), role = COALESCE(%s::text, role), updated_at = now()`,
    `WHERE id = %s` **and** the floor predicate — the new role is `admin`, or the current role is
    `staff`, or the row is not active, or another active Administrator exists — with the eleven-column
    `RETURNING` list. `#:` block: why `COALESCE` rather than SQL assembled from whichever fields
    arrived (`test_source_guards.py` forbids the latter, and it is the exact shape that turns a typo
    into data loss); why `lower()` is Postgres's; why `updated_at` is by hand (DW-17); and why the
    floor is a predicate here rather than a `SELECT count(*)` in Python.
  - `_user_not_found()` and `_last_administrator()` beside `_invalid_email()`.
  - `@router.patch("/admin/users/{user_id}", response_model=User)` giving
    `def edit_user(user_id: UUID, payload, response, administrator: Annotated[User,
    Depends(require_administrator)], conn)`. Sync `def`. `response.headers.update(NO_STORE)` first,
    then the address normalized (`_normalize_email`, `422 invalid_email` on `None`) before anything
    is locked. Then, in one `with conn.transaction():` — the administrator lock when demoting, the
    locking read (`404` when it finds nothing), the `UPDATE` (zero rows now means the floor refused,
    and nothing else), and `throttle.carry_failures` when the stored address actually changed. The
    `UniqueViolation` narrowed to `EMAIL_UNIQUE_INDEX` by name becomes `409 email_already_exists`;
    any other clash propagates.
  - Docstring: FR-12; that `administrator` is the authorization and not a value; that AD-3 is what
    makes the role change land on the live session, so this handler does nothing about sessions at
    all and must never start; that a caller may edit their own row, including demoting themselves
    while another Administrator exists; that Story 1.12 is owed an audit entry here and no private
    log is built meanwhile.
  - Rewrite the module docstring: three routes over two paths, what the edit may and may not touch,
    and a corrected "**Not here.**" paragraph — deactivate, delete and *the unlock* are not this
    story's, and the unlock has no owner left in Epic 1 (DW-64).
- `apps/api/tests/test_edit_user.py` — **new.** Every API row of the I/O matrix, plus: that a rename
  leaves the other ten columns byte-identical; that `updated_at` moves and `created_at` does not;
  that the address is folded by the database (`RUWAN@ROCELL.LK` stored as `ruwan@rocell.lk`) and the
  old address no longer signs in while the new one does; that a promoted Staff user's **next**
  request to `GET /admin/users` succeeds on the same cookie with no re-login, and a demoted
  Administrator's is `403 administrator_required` on the same cookie; that the last-Administrator
  refusal fires with the seeded shape (one Administrator) and does not fire once a second active one
  exists, and that a *deactivated* Administrator does not count toward the floor; that `_UPDATE_USER`'s
  `RETURNING` list is identical to `_INSERT_USER`'s and `_SELECT_USERS`'s, parsed from the module's
  own source rather than retyped; that no response carries a `password_hash` key; and that
  `cache-control: no-store` is on every one of them, refusals included.
- `apps/api/tests/test_edit_user_throttle_carry.py` — **new**, or a clearly-named section of the file
  above. A run of failures and a live lock planted against the old address through `conn`; after the
  rename the new key carries them and the old key is gone; a sign-in at the new address is refused
  while the lock holds; a merge case where the new key already had a longer lock keeps the longer
  one; and a rename that changes only the name leaves `login_attempts` untouched.
- `apps/api/tests/test_admin_authorization.py` — extend the exact-set assertion to the three served
  routes (still compared sorted), rename and retarget that test's own name and comment, and update
  `CREATE_USER`'s comment. Both direction guards, the negative controls and the gate-chaining test
  now cover three routes without being touched — the property they were written for. Add the live
  refusal for the new route: a claimed Staff caller gets `403 administrator_required` and the target
  row is unchanged.
- `apps/api/tests/test_no_registration.py` — add `/admin/users/{user_id}` to the served-path set and
  extend the comment: an edit route changes an account an Administrator already created and cannot
  bring one into existence, so FR-1 is untouched by it.
- `apps/web/src/api/client.ts` — export `USER_NOT_FOUND` and `LAST_ADMINISTRATOR` with the same
  doc-comment register as `INVALID_EMAIL`/`EMAIL_ALREADY_EXISTS`: which field each marks (none, and
  the role control), and that neither is a 401 so no observer watches them.
- `apps/web/src/auth/SessionProvider.tsx` — add `adoptUser(user: User): void` to
  `SessionContextValue` and the memo. It replaces the cached `User` **only when the id matches the
  one already cached**, so it can never be used to write somebody else's row into the caller's
  session. Docstring: the API has just returned a fresher copy of the caller's own row, which is the
  same thing the visibility revalidation stores, and without it an Administrator who renames or
  demotes themselves keeps a stale app bar until the next revalidation. It is a render cache and
  never an authorization decision (AGENTS.md Policy).
- `apps/web/src/screens/EditUserScreen.tsx` + `.module.css` — **new.** Props
  `{ user: User; onSaved: (updated: User) => void; onBack: () => void }`.
  - Modelled on `CreateUserScreen`: `noValidate` form, three fields (Name, Email, Role) pre-filled
    from `user`, the mirrored `MAX_NAME_LENGTH`/`MAX_EMAIL_LENGTH` bounds as `maxLength`, the
    `ROLES`-driven `<select>` narrowed through `isRole`, one alert rendered in exactly one of four
    slots, `aria-invalid`/`aria-describedby` on the field at fault, and focus moved to it.
  - Title "Edit user" and, under it, a muted line naming whose account this is — the screen must
    never be ambiguous about which row is being changed.
  - Submit "Save changes" is the screen's **one** accent control; "Back" is the navy outline.
    `PATCH /admin/users/{user.id}` carries **only the fields that differ** from the loaded row
    (trimmed name compared against the stored one; address compared case-insensitively and
    space-stripped, so retyping the same address in a different case sends nothing). Nothing to send
    means no request and an inline "Nothing has changed."
  - `asUser(body)` as `CreateUserScreen` has it; on success store the returned row as the new
    baseline, call `onSaved(updated)`, and show `Saved.` in the inline `role="status"` indicator that
    read `Saving…` in flight (EXPERIENCE.md line 92) — no navigation, no toast.
  - `fieldFor`: `invalid_email` and `email_already_exists` to the email field, `last_administrator`
    to the role control, everything else to no field, with the API's own sentence rendered.
  - Back with unsaved edits does not leave: it renders one warning naming what will be lost, and the
    next press of Back leaves (EXPERIENCE.md line 90, DW-81). Back is disabled in flight for the
    reason `CreateUserScreen`'s is.
  - Deliberately-absent list in the docstring: no password field, no unlock, no deactivate, no
    delete, no audit entry, no confirm dialog.
- `apps/web/src/screens/UserListScreen.tsx` + `.module.css` — a sixth column, `<th scope="col">`
  "Actions", holding one labelled **Edit** control per row that calls `onEditUser(user)`. New prop
  `onEditUser: (user: User) => void`. The control is a real `<button>` at the row end — never a bare
  icon, never the row element itself (a `<tr>` takes no focus and announces nothing), and never the
  role or status badge (EXPERIENCE.md line 66). Its accessible name names the person, so a screen
  reader hears which row it belongs to. Update the docstring's "no edit … or row-end menu"
  paragraph: edit has arrived, deactivate, delete and unlock have not.
- `apps/web/src/App.tsx` — widen `Section` and `Screen` with `'edit-user'`; `reachableBy` returns
  `role === 'admin'` for it as it does for the other two; add `editing: User | null` state;
  `currentScreen` takes it and answers `'users'` when the section is `'edit-user'` with nothing being
  edited, so a stale section can never render an empty editor. `showSection` clears `editing`
  whenever it moves anywhere else. Render `EditUserScreen` in its own `AppShell` branch with `onBack`
  to `'users'` and an `onSaved` that calls `adoptUser` — which, for a self-demotion, is what the
  existing role reconciler then acts on. Pass `onEditUser` to `UserListScreen`.
- `apps/web/src/screens/CreateUserScreen.tsx` — comment-only: its docstring says Stories 1.10 and
  1.11 own editing and that "nothing here reads a row". Editing now exists, one screen away.
- `apps/web/src/__tests__/edit-user.test.tsx` — **new.** Every `apps/web` row of the I/O matrix
  against a stubbed `fetch`, plus the request shape (`PATCH /api/admin/users/<id>`,
  `credentials: 'same-origin'`, `content-type: application/json`, and the body carrying *only* the
  changed fields); that a same-address retype in a different case sends nothing; that each refusal
  marks and focuses the field the mapping names, asserted at the rendered element; that `Saving…`
  gives way to `Saved.`; that Back with unsaved edits warns once and leaves on the second press; and
  that the screen offers no control that deactivates, deletes, unlocks or sets a password — asserted
  over the rendered button names, not by eye. Plus App-level tests through the real gate: an
  Administrator opens Users, presses a row's Edit, saves, and comes back to a refetched list; and an
  Administrator who demotes themselves lands on the home panel with no Users door.
- `apps/web/src/__tests__/user-list.test.tsx` — retarget the "nothing on this screen edits anything"
  test to the verbs that are still absent (deactivate, delete, unlock, password) and add: one Edit
  control per row, its accessible name naming the person, and that pressing it hands `onEditUser`
  that row. Existing row, badge and class assertions keep their subjects; the new column must not
  disturb the header set they read.
- `apps/web/src/__tests__/error-code-parity.test.ts` — add `user_not_found` and `last_administrator`
  rows to `PYTHON` and `TYPESCRIPT`, and widen `BOUNDS` so each row carries its own screen path,
  adding `EditUserScreen`'s `MAX_NAME_LENGTH` and `MAX_EMAIL_LENGTH`. Without the second half the
  new screen's mirrored bounds are two TypeScript literals compared against nothing.
- `apps/web/src/__tests__/styling-wiring.test.ts` — add `EditUserScreen` to the alert-element
  `it.each` and give it an `.error`-colour case; add its own describe asserting the accent submit
  with the navy foreground, the navy-outline Back, exactly one `--color-accent` in the stylesheet,
  and the save indicator in the brand primary as Account Settings has it; and assert the list's
  row-end Edit control is an outline rather than a second accent fill, so "+ Add user" stays the
  list's one accent control.
- `README.md` — correct the five claims this change falsifies: name and email are now editable in
  the app and by whom; a mistyped address is recoverable (DW-79 closed) and the credential note no
  longer offers "provision them afresh under a different address" as the only route; a role change is
  made from the list and lands on the next request in both directions; **and there is still no admin
  unlock, which no story in Epic 1 now owns** — replacing "none is owed until Story 1.10" and "an
  admin unlock is Story 1.10's to add" with what is actually true. Add the operator paragraph for the
  edit screen: where it is, what it changes, that a rename carries the account's lockout counter with
  it, and that deactivating and deleting are still Story 1.11's.

**Acceptance Criteria:**

- Given a claimed Administrator and a Staff account, when `PATCH /admin/users/{id}` sends
  `{"role": "admin"}`, then the response is `200` with the eleven-key `User` carrying
  `role: "admin"`, `cache-control: no-store` and no `password_hash` key — and the target's very next
  request on the cookie they already held is served as an Administrator, with no sign-out, no new
  sign-in and no change to `apps/api/api/sessions.py`.
- Given an Administrator with a live session, when another Administrator demotes them, then their
  next request to any `/admin/` route is `403 administrator_required` — the same cookie, the request
  immediately after the change.
- Given the only active Administrator in the product, when a demotion of that account is attempted,
  then the response is `409 last_administrator`, the row is unchanged, and the refusal came from the
  `UPDATE`'s own predicate rather than from a count read a moment earlier; and given a second active
  Administrator, when the same demotion is attempted, then it succeeds.
- Given a claimed **Staff** session, when it sends the same request, then the response is
  `403 administrator_required` from a dependency rather than a check inside the handler, the target
  row is byte-identical afterwards, and the refusal is never a `401`; and given an Administrator
  still holding a temporary credential, then it is `403 password_change_required` with no allowlist
  entry added to `test_forced_change_gate.py`.
- Given an account with recorded failed sign-ins and a live lock against its address, when an
  Administrator changes that address, then the counter and the lock are at the new address, the old
  key is gone, and a sign-in at the new address is still refused while the lock holds — a rename is
  not a way around the lockout.
- Given `_INSERT_USER`, `_SELECT_USERS` and `_UPDATE_USER` read from `apps/api/api/users.py`'s own
  source, when their column lists are compared, then all three are identical and name exactly
  `User.model_fields`.
- Given an Administrator on the Users list, when they press a row's Edit, then the edit screen opens
  pre-filled with that row's name, email and role; and when they change one field and save, then only
  that field is sent, the inline indicator reads `Saved.`, and Back shows the list with the change on
  it.
- Given an Administrator editing their own row, when they demote themselves while another
  Administrator exists, then the saved row becomes the session's cached user and the shell renders
  the home panel with no Users entry — without a reload and without a toast.
- Given a Staff user, when the shell renders, then no Users entry and no edit surface is reachable
  anywhere, and a section state that says otherwise still renders the home panel.
- Given `make lint` and `make test`, when they are run over the finished change, then both exit 0
  with every pre-existing test in `apps/api`, `apps/web`, `shared/schema` and `infra` passing.

## Spec Change Log

## Review Triage Log

### 2026-09-18 — Review pass
- intent_gap: 0
- bad_spec: 0
- patch: 10: (high 0, medium 1, low 9)
- defer: 2: (high 0, medium 1, low 1)
- reject: 13: (high 0, medium 0, low 13)
- addressed_findings:
  - `[medium]` `[patch]` The previous pass normalised `failure_count` and `locked_until` before
    `_CARRY_FAILURES` merges two runs, but left `last_failure_at` on a raw `GREATEST` — and that is
    the column `_RUN_ENDED` reads, so it decides how long the surviving run lives. An ended run's
    clock is routinely *fresher* than a live one's: a lockout that lapsed a minute ago last failed
    16 minutes back, while a live run of four failures near the end of `ATTEMPT_WINDOW` last failed
    55 minutes back. Merging them handed that live run a window restarted on failures it never
    made — another `ATTEMPT_WINDOW` in which a fifth mistyped password locks the account, which is
    the same unearned lockout the previous pass's patch was written to prevent, on the third
    column. Both sides are now zeroed to NULL when their run has ended, with a `COALESCE` behind
    them for the `NOT NULL` case where both have. Two tests pin both arms; each fails under a
    mutation back to the raw `GREATEST`.
  - `[low]` `[patch]` `edit_user`'s `UniqueViolation` narrowing — answer `409 email_already_exists`
    only for `users_email_lower_key`, re-raise anything else — was exercised by nothing.
    `test_an_address_already_in_use_is_a_409` clashes on the address index, so deleting the
    narrowing shipped green, and the sibling `POST` branch it calls "`_INSERT_USER`'s reasoning,
    unchanged" *is* covered by `test_create_user.py`. A second unique index would have sent an
    Administrator to an email field that was correct. Now pinned by the `POST` test's own
    arrangement on this route.
  - `[low]` `[patch]` `EditUserScreen` disables Back as well as Save while a save is in flight, and
    only the three inputs were tested. Removing `disabled` from Back shipped green, while at run
    time a press unmounts the screen with the request open — a `409 last_administrator` would be
    discarded and the Administrator would return to a list refetched in a race with a write whose
    outcome nobody saw. The new test asserts both controls and that a press of Back lands on
    nothing; it fails with the attribute removed.
  - `[low]` `[patch]` `infra/README.md` still said an unlock was "not owed until Story 1.10 gives
    an Administrator a way to edit a user" — the fourth copy of the prediction this story set out
    to correct, and the one the sweep missed. It now says no story in Epic 1 owns one (DW-64), and
    adds what the editor did change: a rename carries the run rather than clearing it, so it is not
    an unlock either.
  - `[low]` `[patch]` `App.tsx`'s role-reconciler comment reasoned about a demotion being
    "a two-click operation once Story 1.10 lands", in a file this change edits and about the very
    path this story's self-demotion case walks. Present tense now.
  - `[low]` `[patch]` `CreateUserScreen` and `UserListScreen` both state the rule that admin work
    never routes through `SessionProvider` — "every admin mutation from Story 1.10 on lands there
    too" — and this story is its first exception (`adoptUser`, guarded on a matching id). The
    codebase stated the rule in two places and the exception in two others, with no pointer between
    them; both docstrings now name the exception and why it is narrow.
  - `[low]` `[patch]` `test_edit_user_throttle_carry.py` declares `NEW_ADDRESS`, `SHORT_LOCK` and
    `LONG_LOCK` with a docstring saying they exist "so a test that plants a run against it and a
    test that renames onto it cannot drift", then used bare literals in eight tests and inline
    `timedelta`s in the merge test. Half-converted is the drift the constants were introduced to
    make impossible; every use goes through them now.
  - `[low]` `[patch]` `test_no_registration.py`'s route-table test was still named
    `..._and_the_admin_writer` while its asserted set had grown to two admin paths.
    `test_admin_authorization.py` renamed its counterpart for exactly this reason; this one is
    `..._and_the_two_admin_routes` now.
  - `[low]` `[patch]` `edit-user.test.tsx`'s "words a failure that is not an `ApiRequestError`
    itself" stubs a `200` with a malformed body, which `apiRequest` wraps in
    `ApiRequestError(MALFORMED_RESPONSE)` — so it runs through `failure.message` and the
    `UNEXPECTED` fallback beside it is pinned by nothing. The test now says what it actually holds,
    and `UNEXPECTED` carries a docstring saying it is the fallback for a rejection `apiRequest`
    cannot produce, kept so a bug renders a sentence rather than a stack.
  - `[low]` `[patch]` The Code Map and the Tasks both cited **DW-76** (the mail-transport guard's
    vocabulary gap) for the unsaved-admin-form warning. The entry is **DW-81**, which is what
    `EditUserScreen` and the ledger itself cite; the spec was the one copy that was wrong.

### 2026-09-18 — Review pass
- intent_gap: 0
- bad_spec: 0
- patch: 7: (high 0, medium 2, low 5)
- defer: 2: (high 0, medium 0, low 2)
- reject: 13: (high 0, medium 0, low 13)
- addressed_findings:
  - `[medium]` `[patch]` `_CARRY_FAILURES` merged the two keys with `GREATEST` over the raw
    columns, which takes the stricter *value* per column rather than the stricter *state*. A run
    the module already considers over — a lapsed lock, or a last failure past `ATTEMPT_WINDOW` —
    still holds the count it ended with, and pairing that count with the other side's fresher
    `last_failure_at` produced a live run neither address had: four stale failures merged onto one
    fresh one left the account one mistyped password from a lockout nobody earned, with no unlock
    in this epic. Each side is now normalised by `_RUN_ENDED` (a new `_INCOMING_RUN_ENDED` twin
    asks the same question of `EXCLUDED`) before the merge, and a lapsed `locked_until` no longer
    survives as a value that reads the merged row as ended. Two tests pin both halves; each fails
    under a mutation back to the raw `GREATEST`.
  - `[medium]` `[patch]` The only assertion protecting the counter carry's old key — that it is the
    *Python* fold of the stored column, not the column, which is the whole of DW-59's closure —
    was `test_the_run_is_found_under_the_key_sign_in_actually_uses`, which skips on any cluster
    whose `lower()` agrees with Python's. `conftest.py` runs `initdb` with no `--locale`, so
    whether that test executes is a property of the machine, and on most of them
    `old_key = current["email"]` would have shipped green. A companion test now reads the
    assignment out of `api/users.py` and holds it to the shape, so the guard is exercised
    unconditionally.
  - `[low]` `[patch]` `test_a_concurrent_demotion_cannot_slip_past_the_floor` armed its release
    timer *before* reading the clock it compares against, so the measured window was a strict
    subset of the held one and the `elapsed >= OVERLAP_SECONDS` assertion could fail against
    correct code. The clock is read first now, and the timer is cancelled on the way out.
  - `[low]` `[patch]` `test_no_session_is_refused_as_unauthenticated` asserted the challenge but
    not the cookie clearance, which is the half that stops the browser returning with the same
    dead credential. Both are asserted now.
  - `[low]` `[patch]` `README.md` claimed a mistyped address "is no longer a dead end" with no
    qualification, while a deferred entry in this same change records that correcting one onto an
    address somebody had been guessing at hands that lockout to the account with no unlock
    anywhere in Epic 1. The paragraph now carries that caveat, and says plainly what a rename does
    and does not release.
  - `[low]` `[patch]` `EditUserScreen` seeds every piece of its state from `user` at mount and
    never reconciles the prop, and the element carried no `key`. Nothing can swap one row for
    another today, but only because `showSection` unmounts the screen on the way back to the list
    — a property of the gate, not of the screen. It is keyed on the row id now.
  - `[low]` `[patch]` `test_a_deactivated_administrator_does_not_count_toward_the_floor` claimed to
    pin the floor predicate's `OR NOT active` arm "even with nobody else active". The caller is
    always an active Administrator (`lookup_session` carries `AND u.active`), so the `EXISTS` arm
    is what allows the demotion and `OR NOT active` decides nothing this route can reach —
    deleting it fails no test. The comment now says which arm is load-bearing, and why the dead one
    is kept for Story 1.11 and DW-90 rather than trimmed.

### 2026-09-18 — Review pass
- intent_gap: 0
- bad_spec: 0
- patch: 9: (high 0, medium 2, low 7)
- defer: 5: (high 0, medium 3, low 2)
- reject: 8: (high 0, medium 0, low 8)
- addressed_findings:
  - `[medium]` `[patch]` `carry_failures`' docstring claimed `users.locked_until` already held whatever lock the carried row carried. False on the path the statement exists for: where the *destination* key already held a live lock — an address guessed at while it belonged to nobody, so `_MIRROR_LOCK` had updated zero rows — the account's mirror was never written, and FR-4's one status surface showed no lock while `POST /auth/login` answered `429 account_locked`. The carry now reads the resulting live lock back and mirrors it onto the account in the same transaction, `edit_user` patches the one column its `RETURNING` could be stale about, and two tests plant a lock on the destination key alone and assert the refusal and the mirror agree.
  - `[medium]` `[patch]` Two claims the change rests on were asserted by nothing: that an account still holding its temporary credential can sign in with it at a corrected address and is still gated to the forced change (the whole of DW-79's closure, and of README's rewritten paragraph), and that an email change leaves the target's live session accepted on the cookie they already held. Both are now tests, and the handler docstring states that an address change revokes nothing and why.
  - `[low]` `[patch]` The carry's old key was the Postgres-folded stored address while `api/auth.py` keys `login_attempts` on the Python fold of the submitted one — the `İ`-class divergence `_INSERT_USER`'s own comment cites — so on a diverging address the carry would look up a key with no row and strand the live run, reproducing DW-59 in the code written to close it. Both the key and the did-the-address-change guard now compare like with like, pinned by a test that probes the cluster for an address whose folds actually diverge.
  - `[low]` `[patch]` `user-list.test.tsx`'s "keeps the Edit control out of the row element itself" asserted `row.getAttribute('onclick')` is null, which React can never make false. It now clicks the `<tr>` and asserts `onEditUser` was not called.
  - `[low]` `[patch]` `test_a_malformed_id_is_a_422_and_reads_no_row` asserted only the status and the envelope shape; it now compares the whole row before and after.
  - `[low]` `[patch]` `test_the_edit_route_refuses_a_staff_caller_and_writes_nothing` proved "writes nothing" for three named columns and selected `updated_at` without asserting on it; it now compares the complete row.
  - `[low]` `[patch]` The edit screen's blank-**email** refusal was exercised by no test — no test ever emptied that input — so deleting the branch shipped green and the generic field-less `422` reached the screen instead. The blank-field test is now an `it.each` over both fields.
  - `[low]` `[patch]` The three inputs stayed live during a save while the success path overwrote them from the server's row, so anything typed in flight was discarded silently. They are `disabled` while submitting, which in turn moved the refusal's focus call into a post-commit effect so a refusal still focuses the field at fault.
  - `[low]` `[patch]` The concurrent-demotion test could pass by arriving after the held transaction committed — and would have passed against a handler taking no lock at all. It now asserts the request genuinely blocked; with the lock removed it fails on the elapsed assertion rather than on luck.

## Design Notes

**Why `PATCH` on `/admin/users/{user_id}` rather than `PUT`.** The resource a `GET` returns has
eleven fields and this route may write three; a `PUT` that took the three and left the other eight
alone would be a replace that does not replace, and the first reader to send a complete `User` to it
would be right to expect the rest to land. `PATCH` also lets the screen send only what changed, which
is the whole of this story's answer to two Administrators editing one row at once: last write wins,
but it wins over one field rather than over the whole account. The body is still closed
(`extra="forbid"`) and still requires at least one field, so "partial" never means "unspecified".

**Why one `COALESCE` statement rather than SQL built from the fields that arrived.** The obvious
implementation — collect `SET` fragments for the present fields and join them — is precisely the
shape `tests/test_source_guards.py` forbids, and it is forbidden for a reason beyond injection: a
fragment list assembled in Python is a place where a field can be dropped silently. One statement
with three `COALESCE`s has a fixed parameter list, a fixed `RETURNING` shape, and no branch that can
forget a column.

```sql
-- apps/api/api/users.py — the shape of the write, not the code.
UPDATE users
   SET name = COALESCE(%s::text, name),
       email = COALESCE(lower(%s::text), email),
       role = COALESCE(%s::text, role),
       updated_at = now()
 WHERE id = %s
   AND (COALESCE(%s::text, role) = 'admin' OR role = 'staff' OR NOT active
        OR EXISTS (SELECT 1 FROM users other
                    WHERE other.id <> users.id AND other.role = 'admin' AND other.active))
RETURNING <the eleven columns, in _INSERT_USER's order>
```

**Why the Administrator floor is enforced here at all.** epics.md gives the refusal to Story 1.11 and
words it for deactivate and delete. But demoting the last active Administrator reaches the same state
by a different verb, and it is reachable from *this* story's route — the product would be left with
nobody who can promote anybody, recoverable only with `DATABASE_URL` in hand, which is the dependency
Epic 1 exists to remove. The epic's constraint is worded as a standing property ("at least two active
Administrators must always exist"), not as a property of one handler. What is *enforced* is the same
enforceable rule 1.11 will enforce — never zero — and 1.11 should reuse
`_LOCK_ACTIVE_ADMINISTRATORS` and this predicate rather than writing a second copy.

**Why a row lock rather than a count.** `SELECT count(*) FROM users WHERE role = 'admin' AND active`
followed by an `UPDATE` is the read-then-write AD-8 rejects for the throttle, and it fails the same
way here: two Administrators demoting each other simultaneously each see the other and both succeed.
The predicate inside the `UPDATE` closes most of it, and locking the active-Administrator rows first
— `ORDER BY id`, and only when the requested role is `staff` — closes the rest, because the second
transaction re-evaluates the predicate against the first's committed result. The ordering is what
keeps two demotions from deadlocking each other; the locking read of the target row comes after it,
so a plain rename (which takes no Administrator lock at all) can never be on the other side of a
cycle.

**Why a rename carries the counter instead of clearing it (DW-59).** Three things were wrong after a
rename: the old address string kept a live lock nobody could reach, the new address started from
zero, and `users.locked_until` reported a lock that corresponded to nothing. Clearing the run fixes
the first and third by making the rename an unlock — a lock-evasion path an Administrator can walk,
and an unlock this epic deliberately does not have. Carrying it fixes all three at once: the lock
follows the account, the mirror goes on being accurate, and nothing about the recovery story changes.
Where the new address already carries its own run (an address that was guessed at before it became an
account), the two merge with `GREATEST` per column, so the stricter state survives; Postgres's
`GREATEST` ignores NULLs, which is exactly the behaviour wanted when one side has no lock.

**Why there is still no unlock, and why the README changes anyway.** `throttle.py`, `auth.py` and
`README.md` each predict one "in Story 1.10". epics.md 1.10 asks for name, email and role, and a
story cannot widen another story's acceptance clauses — DW-64 says so, and 1.9 held the same line
about the rendering half. So the unlock is not built. What this story will not do is leave three
files asserting a future that is now the past: the README statements become "no story in Epic 1 owns
it", DW-64 records that its predicted owner has shipped without it, and the decision is visible
rather than discovered.

**Why a labelled row-end button rather than a clickable row.** EXPERIENCE.md line 71 says "row click
opens detail", and the mockup shows a row-end menu. A `<tr>` with an `onClick` is not focusable, is
announced as nothing, and puts a click target under text an Administrator may be trying to select;
the accessibility floor asks for a keyboard path on every interactive element. One labelled
`<button>` at the row end satisfies both readings, is what line 71 asks for in the same breath
("never a bare icon with no label"), and leaves the row-end slot where 1.11's destructive menu
belongs. Badges stay display-only (line 66).

**Why the editor is its own screen and not a mode of `CreateUserScreen`.** EXPERIENCE.md's surface
table names one surface, "Create/Edit User", because the two carry the same fields — not because they
are one component. Create owns a temporary password, a result panel holding a credential nothing can
show again, and a `POST`; edit owns a pre-filled form, a per-field diff, a save indicator and a
`PATCH`. Folding them together would put every one of those behind a mode flag in a screen whose
credential handling is the most delicate in the product.

**Why `adoptUser` is on the session context.** Every other admin call deliberately bypasses
`SessionProvider`, and that stays true: this is not a route into the provider for admin mutations. It
is the one case where the row the API just returned *is* the caller's own — an Administrator editing
themselves — and the provider already does exactly this on its visibility revalidation
(`setUser(asUser(body))`). Guarding it on a matching id is what keeps it from becoming a way to write
somebody else's row into the session. Without it a self-rename leaves a stale name in the app bar,
and a self-demotion leaves the Users door on screen until the tab is backgrounded and brought back.

## Verification

**Commands:**

- `make lint` — expected: exit 0 (ruff check, ruff format --check, oxlint --deny-warnings,
  tsc --noEmit).
- `make test` — expected: exit 0; the `apps/api` database tests run against the ephemeral cluster or
  skip with the same "no PostgreSQL available" reason (DW-18/DW-39).
- `uv run pytest apps/api/tests/test_edit_user.py apps/api/tests/test_admin_authorization.py apps/api/tests/test_no_registration.py -q`
  — expected: exit 0.
- `uv run pytest apps/api/tests/test_forced_change_gate.py apps/api/tests/test_source_guards.py apps/api/tests/test_create_user.py apps/api/tests/test_user_list.py apps/api/tests/test_login_throttling.py apps/api/tests/test_login.py -q`
  — expected: exit 0, **with none of those six files modified**.
- `npm --prefix apps/web run test` — expected: exit 0, including the retargeted user-list assertions
  and the new screen's parity and styling rows.
- `git status --porcelain infra/migrations shared/schema` — expected: empty. This story ships no
  migration and no contract change.
- `git diff --stat apps/api/api/sessions.py apps/api/api/dependencies.py` — expected: empty. FR-12's
  live-session half is AD-3's existing behaviour, proved by a test rather than built.
- Prove each new guard load-bearing by removing what it guards, then restoring it: drop
  `require_administrator` from the new route (the admin route-table guard and the Staff-refusal test
  fail), remove the floor predicate from `_UPDATE_USER` (the last-Administrator test fails), drop
  `_LOCK_ACTIVE_ADMINISTRATORS` (the concurrent-demotion test fails), replace `carry_failures` with
  `clear_failures` (the lock-survives-a-rename test fails), send every field from the screen instead
  of only the changed ones (the partial-body test fails), drop the `mode="before"` null refusal (the
  explicit-null test fails), and drop the `reachableBy` arm for `'edit-user'` (the
  Staff-cannot-reach-it test fails).

**Manual checks (if no CLI):**

- Invoke the `ui-ux-pro-max` skill and run its pre-delivery checklist against the Edit user screen
  and the widened Users table before calling this story done (epic context: required for every UI
  story).
- `make migrate`, then `make dev`: sign in as the seeded Administrator, claim the account, add a
  second Administrator from Users then "+ Add user", then edit the first one's name and confirm the
  list shows it on return. Demote yourself and confirm the Users door disappears without a reload.
  With only one active Administrator left, attempt a demotion and confirm the refusal names the rule.
- Fail a sign-in ten times against one address, confirm the lock shows on that account's status,
  change that account's address, and confirm the lock is still on the account and that the new
  address is refused until it lapses.
- At 375px: the Users table's own container scrolls and the page does not; the Edit control and every
  control on the edit screen is at least 44x44px; the edit screen's alert is announced and focus
  lands on the field at fault.

## Auto Run Result

Status: done
Blocking condition: none

**Pass:** a second follow-up review of a spec already at `done` (`review_loop_iteration` 0, four
review layers run in parallel against the full diff since `f919d807c407c03ab10111bfd2d1932c3e0e5dff`,
tracked and untracked).

**Summary of implemented change.** Unchanged in shape: `PATCH /admin/users/{user_id}` writes name,
email and role in one guarded `UPDATE`, the Administrator floor is a predicate inside that statement
behind an ordered lock of the active Administrator rows, a readdress carries the account's
`login_attempts` run to the new key and re-mirrors `users.locked_until`, and `EditUserScreen` sends
only the fields that differ. This pass changed no behaviour an acceptance criterion names. It
corrected one real defect — the third and last unnormalised column in the counter merge — closed two
verification gaps on guards that were shipping green under mutation, and fixed six doc/test
inaccuracies, four of them stale predictions that this story itself falsified.

**Files changed this pass:**

- `apps/api/api/throttle.py` — `_CARRY_FAILURES` now normalises `last_failure_at` the way it already
  normalised `failure_count` and `locked_until`, with a `COALESCE` for the `NOT NULL` case where
  both runs have ended; `carry_failures` passes `ATTEMPT_WINDOW` four times for it.
- `apps/api/tests/test_edit_user_throttle_carry.py` — two tests pinning both arms of that
  normalisation (`_backdate`, `_last_failure_age` and the two run-age constants are new); every
  bare address and lock literal routed through the constants the file already declared for them.
- `apps/api/tests/test_edit_user.py` — a clash on a second unique index is propagated, not
  described as a duplicate address.
- `apps/web/src/__tests__/edit-user.test.tsx` — Save and Back are frozen in flight, and a press of
  Back in that state lands on nothing; the malformed-response test renamed to what it holds.
- `apps/web/src/screens/EditUserScreen.tsx` — `UNEXPECTED` documented as the fallback for a
  rejection `apiRequest` cannot produce.
- `apps/api/tests/test_no_registration.py` — route-table test renamed for the two admin routes it
  now guards.
- `infra/README.md`, `apps/web/src/App.tsx`, `apps/web/src/screens/CreateUserScreen.tsx`,
  `apps/web/src/screens/UserListScreen.tsx` — four statements this story falsified, corrected.
- `spec-1-10-edit-user.md` — DW-76 → DW-81 in the Code Map and the Tasks.

**Review findings breakdown:** 10 patches applied (0 high, 1 medium, 9 low), 2 items deferred (1
medium — the parameterized-SQL guard is per-line and has never inspected a multi-line f-string
statement, which predates this story; 1 low — a stale unlock prediction in a file this spec's
Verification pins as unmodified), 13 rejected. No intent gap, no spec repair. Of the rejections,
two named artifacts the orchestrator owns, three were duplicates of deferred entries already
recorded (DW-90, DW-91, DW-94), one was addressed by the previous pass, and the rest were noise or
descriptive observations prescribing no work.

**Follow-up review recommendation:** `true`. Patched this pass: high 0, medium 1, low 9 — score
`3x1 + 1x9 = 12`, at or above the threshold of 5.

**Verification performed:**

- `make lint` — exit 0 (ruff check, ruff format --check over 54 files, oxlint --deny-warnings,
  tsc --noEmit). One import-order error was raised on the first run and fixed by `make format`.
- `make test` — exit 0: `774 passed` in `apps/api`/`shared`/`infra` (771 before this pass, +3), and
  `796 passed` across 17 `apps/web` test files (795 before, +1).
- Mutation-proved all three new guards rather than asserting they are there: reverting
  `last_failure_at` to the raw `GREATEST` fails both
  `test_an_ended_runs_clock_does_not_extend_the_live_run_it_merges_with` and
  `test_the_incoming_ended_runs_clock_does_not_extend_the_one_it_merges_into`; deleting the
  `EMAIL_UNIQUE_INDEX` narrowing fails
  `test_a_clash_on_another_index_is_not_described_as_a_duplicate_address`; removing
  `disabled={submitting}` from Back fails `freezes Save and Back too`. Each was restored and the
  full suite re-run green afterwards.
- `git status --porcelain infra/migrations shared/schema` — empty.
- `git diff --stat apps/api/api/sessions.py apps/api/api/dependencies.py` against the baseline —
  empty.
- The six test files this spec pins as unmodified are unmodified, confirmed by
  `git diff --name-only` against the baseline over all six.

**Residual risks:**

- Nine deferred entries are now open against this story, four of them medium. Two are product
  decisions belonging with Story 1.11 and whoever owns FR-5 (the floor counting Administrator rows
  nobody can sign in as; the carried lockout with no unlock to end it), one is a shared gap with
  Story 1.9 (a 403 mid-edit leaves the screen unusable), and the newest is the source guard that
  has never inspected the SQL shape `api/throttle.py` actually uses.
- `test_the_run_is_found_under_the_key_sign_in_actually_uses` still skips where the cluster folds
  like Python; the source-level guard beside it is what holds the invariant there.
- The two new clock tests assert a database-side age within a five-minute band. That is wide enough
  for any plausible runner pause and narrow enough to fail the mutation, but it is still a
  time-shaped assertion in a suite that already has one.
