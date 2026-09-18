---
title: 'Story 1.9 — View User List'
type: 'feature'
created: '2026-09-18'
baseline_revision: '67ab364bea305e58a5bf6faa5b66882e57015849'
status: 'done'
review_loop_iteration: 0
followup_review_recommended: false # score 4 (0 high, 1 medium, 1 low patched this pass); see Auto Run Result
context:
  - '{project-root}/AGENTS.md'
  - '{project-root}/_bmad-output/planning-artifacts/architecture/architecture-rcl_camera_app-2026-08-30/ARCHITECTURE-SPINE.md'
  - '{project-root}/_bmad-output/planning-artifacts/ux-designs/ux-rcl_camera_app-2026-09-08/EXPERIENCE.md'
  - '{project-root}/_bmad-output/planning-artifacts/ux-designs/ux-rcl_camera_app-2026-09-08/DESIGN.md'
warnings: ['oversized']
deferred:
  - summary: >-
      An outstanding or lapsed temporary credential is invisible on the user
      list, so "Last login: Never" reads the same for a colleague who has not
      opened their note yet and one whose 72 hours ran out.
    evidence: |-
      `GET /admin/users` returns `must_change_password` and
      `temp_credential_expires_at` on every row and
      `tests/test_user_list.py::test_an_unclaimed_account_is_listed_with_its_deadline`
      asserts both reach the wire, but the screen renders five columns and
      neither is one of them. FR-10 names status and last login only, so this
      story's acceptance clause does not ask for it; what makes it real is that
      the product's own README calls the 72-hour deadline load-bearing and
      nothing in the product can now tell an Administrator that a deadline has
      passed. Stories 1.10/1.11, which could reissue or remove the row, are the
      natural owners.
    location: >-
      apps/web/src/screens/UserListScreen.tsx
    severity: medium
  - summary: >-
      An Administrator demoted while the user list is open sees the refusal and
      can press "Try again" forever, with the Users door still on the shell,
      until something else revalidates the session.
    evidence: |-
      `SessionProvider` revalidates only on `visibilitychange`, so the cached
      `User` keeps saying `admin` after the server has stopped agreeing. The
      screen words `403 administrator_required` as an ordinary failure and
      offers a retry of a request that can only be refused again. This is
      DW-68's shape on a second surface — that entry is the same gap for
      `403 password_change_required` on Account Settings — and the fix belongs
      with whatever teaches `apiRequest`'s observer about a role refusal, not
      with this screen.
    location: >-
      apps/web/src/screens/UserListScreen.tsx
    severity: medium
  - summary: >-
      Account Settings always returns to the home panel, so an Administrator who
      opens it from the user list is put somewhere they did not come from.
    evidence: |-
      `App.tsx` passes `onBack={() => showSection('home')}` to
      `AccountSettingsScreen` from every branch, and the app bar's Account
      control is rendered on the admin surfaces too. It predates this story —
      the same round trip from Create user has landed on the home panel since
      Story 1.8 — and it is more visible now that the list is a surface people
      stand on. Fixing it means remembering where the section was opened from,
      which is state the gate does not keep yet.
    location: >-
      apps/web/src/App.tsx
    severity: low
---

<intent-contract>

## Intent

**Problem:** FR-10 — an Administrator has no way to see who has access. The product can
*create* users (Story 1.8) and nothing can read the collection it writes to: every account,
its active/deactivated status and its last sign-in exist only as columns nobody can reach
without `DATABASE_URL`. FR-4's lockout is in the same position — `users.locked_until` is
written by the throttle and rendered by nothing (DW-64) — so "visible to Administrators on
that user's status" is a promise the product does not keep.

**Approach:** One read route beside the write that already exists — `GET /admin/users`,
Administrator-only through the same `require_administrator` dependency, returning every
`users` row as the shared `User` contract — and one new screen that renders them as
EXPERIENCE.md's dense admin table: name, email, role badge, status badge, last login. The
home panel's interim admin door becomes the User List (EXPERIENCE.md's own nav entry), and
Create user moves behind its "+ Add user" control, which is where EXPERIENCE.md line 34
reaches it from.

## Boundaries & Constraints

**Always:**
- The route lives under `/admin/` and declares `require_administrator`, so
  `test_admin_authorization.py` reads the authorization off the path in both directions.
  Authorization is server-side and independent of what the UI hides (AGENTS.md Policy).
- Every account is returned — the caller's own row, deactivated rows, locked rows, unclaimed
  rows. "Every account with its status" is the acceptance clause; a filter is a lie about who
  has access.
- The response body is the shared `User` contract, eleven keys, validated by
  `User.model_validate` on the way out and by `isUser` on the way in. `password_hash` does
  not exist on that model and cannot be added to this response.
- The `SELECT` column list is identical, character for character, to `_INSERT_USER`'s
  `RETURNING` list and to `auth._SET_PASSWORD`'s — one shape, held by a test.
- A deactivated account is distinguishable on the list at a glance and never by colour alone
  (EXPERIENCE.md accessibility floor): the badge carries the word.
- Every value in the new stylesheet is a `var(--token)` from `tokens.css`; the screen has
  exactly one `--color-accent` control (DESIGN.md).

**Block If:**
- Nothing here is a human decision. Proceed unattended.

**Never:**
- No pagination, cursor, page-size parameter, search box or sort control. FR-18 is catalogue
  search and belongs to Epic 2; this is tens of rows in an internal tool.
- No edit, deactivate, delete, unlock, reissue or row-end menu — Stories 1.10 and 1.11 own
  every verb on a row, and DW-64's "something to press" is theirs. Rows are display-only here,
  and the role and status badges are display-only everywhere (EXPERIENCE.md line 66).
- No change to `shared/schema` — the contract already carries `active`, `last_login_at` and
  `locked_until`. No new error code, so no `client.ts` constant and no parity row.
- No second session-lookup, no query of `sessions`, no SQL assembled from a value, no
  `async def` handler (AD-3, `test_source_guards.py`, psycopg is synchronous).
- Never gate anything on the cached `User` in `SessionProvider` — it is a render cache
  (AGENTS.md Policy); the role-conditional door is a convenience and the server refuses a
  Staff caller regardless.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Administrator lists users | claimed Administrator session; 4 rows incl. one deactivated, one never signed in | `200`, JSON array of 4 `User` objects, ordered case-insensitively by name then email, `cache-control: no-store` | No error expected |
| Staff caller | claimed Staff session | `403 administrator_required`, from the dependency, before the handler runs | Envelope only, no rows |
| Unclaimed Administrator | Administrator still on a temporary credential | `403 password_change_required` — the gate fires before the role check | Envelope only |
| No session / deactivated mid-session | no cookie, or `active` flipped false between requests | `401 unauthorized`, cookie cleared | `notifyUnauthorized` drops `apps/web` to the login screen |
| Locked account rendered | a row whose `locked_until` is in the future | status cell shows the deactivated/active badge **and** a muted "Locked until \<time\>" line | None — display only, nothing gates on it |
| Lock already lapsed | `locked_until` in the past | no lock line; the column is history, not state | None |
| Never signed in | `last_login_at` is null | the cell reads "Never" | None |
| Screen load fails | `GET /admin/users` answers 403/500, or the network drops | one `role="alert"` carrying the API's own sentence, plus a "Try again" control that refetches | No table rendered, no partial list |
| Malformed body | body is not an array of `User` | the same alert, from a `malformed_response` `ApiRequestError` | Nothing is rendered from a partially-understood body |
| Staff user in `apps/web` | Staff session, shell renders | no Users entry anywhere on the home panel; a section state that says otherwise falls through to the home panel | None |

</intent-contract>

## Code Map

**Read-only sources of truth (do not edit):**
- `_bmad-output/planning-artifacts/epics.md` **lines 286–294** — Story 1.9's clauses verbatim;
  also **296–318** (1.10/1.11, which own every verb on a row this story must not build).
- `_bmad-output/specs/spec-rcl_camera_app/functional-requirements.md` — **FR-10** (line 40:
  "All users with status (active/deactivated) and last login; a deactivated user is visually
  distinct, no separate screen needed"), **FR-4** (line 15, the lock "visible to
  Administrators").
- `AGENTS.md` — server-side authorization on every endpoint; parameterized SQL; no third role;
  security paths need failure-case tests.
- `ARCHITECTURE-SPINE.md` **AD-3** (role and `active` re-read per request through the one
  session lookup) and the Consistency Conventions table (UUIDv4, ISO 8601 UTC, one error
  envelope).
- `EXPERIENCE.md` — **line 33** (User List: "All accounts, status, last login", Admin,
  reached from Nav), **line 34** (Create/Edit User is reached from "User List row / '+ Add
  User'"), **line 18** (role-conditional nav, never disabled items), **line 66** (role and
  status badges are display-only, never a button), **line 71** (data table row: dense,
  `{spacing.2}`–`{spacing.3}`; row-end menus are 1.10/1.11's), **line 95** (a revoked
  permission redirects to the highest surface the new role can reach), **line 113** (contrast:
  white-on-accent fails; accent foreground is navy).
- `DESIGN.md` — the `badge-role-admin` / `badge-role-staff` / `badge-status-deactivated` /
  `data-table-row` blocks (**lines 94–110**), **line 198** (`{rounded.full}` for badges and
  pills only), **line 190** (admin density tier), **lines 210–212** (badge and table-row
  component rules).
- `_bmad-output/implementation-artifacts/deferred-work.md` — **DW-64** (FR-4's lock is handed
  to 1.9 and FR-5's unlock to 1.10; this story closes the *rendering* half and not the
  unlock), **DW-59** (an email change strands the lock string — 1.10's), **DW-79**
  (a consumed address needs 1.10/1.11), **DW-83** (route-table walkers disagree about rigour
  — `test_admin_authorization.py` is the strict one and the one this story extends),
  **DW-46**, **DW-10** (contrast is asserted by no test).

**Files that already exist and constrain the shape:**
- `apps/api/api/users.py` — **the module this route joins.** `router` (L76), `EMAIL_UNIQUE_INDEX`
  (L115), `_INSERT_USER` (L293) whose eleven-column `RETURNING` list the new `SELECT` must
  match character for character, `create_user` (L329) for the handler conventions: sync `def`,
  `response.headers.update(NO_STORE)` first, `Annotated[...]` dependencies, `#:` blocks above
  every module-level constant arguing *why*, SQL as an `_UPPER_SNAKE` triple-quoted constant
  directly above its handler. The module docstring's "**Not here.** No list…" paragraph (L37)
  is now half wrong and must be rewritten.
- `apps/api/api/dependencies.py` — `require_administrator` (L74) and `NO_STORE` (L78). **Not
  edited**; its docstring already states the both-directions rule this story's second route
  inherits.
- `apps/api/api/db.py` — `get_connection` (L121); autocommit, `dict_row`, so a `SELECT` needs
  no transaction.
- `apps/api/api/main.py` — `create_app()` already includes `users.router` (L177) with the
  comment about `/admin/` being an authorization boundary. **Not edited.**
- `shared/schema/shared_schema/user.py` — `User` (L52), eleven fields, `extra="forbid"`,
  `AwareDatetime`, the UTC JSON serializer. `locked_until`'s docstring already says "status,
  never enforcement" and "a client that treats a past value as locked is reading it wrong" —
  that is the rule the status cell implements. **Not edited.**
- `shared/schema/shared_schema/ts/user.ts` — `isUser`, `USER_KEYS`, `isUtcTimestamp`, `ROLES`,
  `Role`. **Not edited**; `isUser` per element is the whole of the response check.
- `apps/api/tests/test_admin_authorization.py` — `ADMIN_PREFIX` (L54), `CREATE_USER` (L57) and
  its "the only one until Story 1.9" comment, `_declares` (L81), `_api_routes` (L98),
  `_admin_routes` (L146), and **`test_the_admin_route_table_is_the_one_route_this_story_serves`
  (L379)**, which says in its own comment that it is *meant* to fail the moment this story
  adds `GET /admin/users`. That is the one assertion in the file this story changes.
- `apps/api/tests/test_no_registration.py` — `test_the_route_table_is_the_five_auth_routes_health_and_the_admin_writer`
  (L166) asserts the served **path** set (L176–184). `/admin/users` is already in it and a
  second method on the same path does not change it: **no edit**, and the spec says so rather
  than leaving the next reader to check.
- `apps/api/tests/test_source_guards.py` — `users.py` is already in the list
  `test_the_scan_reaches_the_files_it_claims_to` names (L100), so the new SQL is provably
  scanned: **no edit**.
- `apps/api/tests/conftest.py` — `conn`, `client`, `make_user(role=, active=,
  must_change_password=, temp_credential_expires_at=, name=)` → `Account(id, email, password,
  name)`. `name=` is what makes an ordering test possible; **no fixture change is needed**.
  `make_user` cannot set `locked_until` — a test that needs one `UPDATE`s it through `conn`,
  as `test_admin_authorization.py` flips `role` and `active`.
- `apps/web/src/api/client.ts` — `apiRequest(path)` (L266), `ApiRequestError` (L160),
  `MALFORMED_RESPONSE` (L141), `notifyUnauthorized` on **status 401 only** (L328). No new
  constant: this route invents no code.
- `apps/web/src/App.tsx` — `Section` (L29), `Screen` (L42), `reachableBy` (L55) — *the one
  statement of which surfaces a role reaches*, `currentScreen` (L60), the two render-phase
  reconcilers (L107, L131), `showSection` (L255) with its `next === section` early return,
  `signOutFailure` (L276), the `create-user` branch (L283) and the home panel's door (L329).
- `apps/web/src/App.module.css` — `.createUser` (L50): the navy-outline door. `App.module.css`
  declares **no** `--color-accent` and a test asserts that count is zero.
- `apps/web/src/screens/CreateUserScreen.tsx` — the screen this one sits beside: `asUser`
  (L146) is the shape `asUsers` mirrors, `FormError`/`fieldFor` (L113–128), the one-alert
  treatment, `.submit`(accent)/`.back`(navy outline)/`.indicator` rhythm, and `expiry()` (L460)
  — the locale-rendered timestamp the "Last login" cell copies. Edited only for its `onBack`
  destination comment; its own behaviour does not change.
- `apps/web/src/screens/CreateUserScreen.module.css` — the stylesheet the new one is modelled
  on: `.screen`, `.title`, `.error`, `.actions`, `.submit`, `.back`, `.result` (card), `.value`
  (`overflow-wrap: anywhere` for an address).
- `apps/web/src/auth/SessionProvider.tsx` — the bootstrap effect (L106–132) with its `live`
  flag: the StrictMode-safe mount fetch this screen copies. **Not edited.**
- `apps/web/src/components/AppShell.tsx` — `MAIN_REGION_ID`; the screen renders no `<main>` of
  its own. **Not edited.**
- `apps/web/src/__tests__/create-user.test.tsx` — `ADMIN`/`STAFF`/`CREATED` fixtures (L30–65),
  the local `stubFetch` keyed by path (L100), and the **`describe('the door on the home
  panel')`** block (L618–800), which drives the role reconciler through the door this story
  moves. Retargeted, not deleted.
- `apps/web/src/__tests__/styling-wiring.test.ts` — `read`/`rule`/`declaration`, the
  `.error`-colour cases (L238–290), the alert-element `it.each` (L308–320), the
  one-accent-per-screen describes (L332, L364, L385), and **L433–441**, which reads
  `.createUser` off `App.module.css` by name.
- `apps/web/src/__tests__/no-raw-values.test.ts` — walks every file under `src`: no colour or
  dimension literal outside `tokens.css`, `@media` preludes must read exactly `768px`.
- `README.md` **lines 140–177** — "Listing, editing and deactivating users are Stories 1.9 to
  1.11; until they land, provisioning is the one thing the admin surface can do" and "it says
  nothing about the person until you check the user list": both become untrue with this change.

## Tasks & Acceptance

**Execution:**

- `apps/api/api/users.py` — add the read beside the write.
  - `_SELECT_USERS`: `SELECT <the eleven columns, in `_INSERT_USER`'s `RETURNING` order,
    character for character> FROM users ORDER BY lower(name), email`. A `#:` block saying why
    the order is `lower(name)` (a list read by a human, and Postgres's default collation would
    file `ruwan` after `Zoya`), why `email` is the tie-break (it is the table's only unique
    non-opaque column, so the order is total and a test can assert it), and why there is no
    `LIMIT`, no `WHERE` and no parameter at all: FR-10 is every account, and a filter on a
    surface whose job is "who has access" hides the row somebody is looking for.
  - `@router.get("/admin/users", response_model=list[User])` →
    `def list_users(response, administrator: Annotated[User, Depends(require_administrator)],
    conn)`. Sync `def`. `response.headers.update(NO_STORE)` first, then
    `[User.model_validate(row) for row in conn.execute(_SELECT_USERS)]`.
  - Docstring: FR-10; that `administrator` is the authorization and not a value; why a bare
    JSON array rather than an envelope (there is no cursor to carry and one consumer in the
    product — the shape changes when pagination does, on both sides at once); that the caller's
    own row is in the list on purpose; that every row is returned including deactivated and
    locked ones; that `locked_until` is rendered and never decided from (`shared_schema`'s own
    rule); and that this list is the surface FR-4 meant by "visible to Administrators on that
    user's status", which closes DW-64's rendering half and not its unlock half.
  - Rewrite the module docstring's "**Not here.**" paragraph: the list has arrived, 1.10/1.11
    still own every verb on a row, and the no-mail / no-audit-entry paragraphs stand. Retitle
    the module summary line — it is no longer one route.
- `apps/api/tests/test_user_list.py` — **new.** Every row of the I/O matrix that is an API row,
  plus: that a deactivated account, the caller's own account and an account that has never
  signed in all appear; that `last_login_at` is null before a sign-in and populated after;
  that a `locked_until` written directly to the row comes back as a UTC ISO 8601 string; that
  ordering is case-insensitive by name with email as the tie-break, driven by rows inserted in
  the wrong order and by two users sharing a name; that no element carries a `password_hash`
  key and every element's key set is exactly `User.model_fields`; that `_SELECT_USERS`'s column
  list is identical to `_INSERT_USER`'s `RETURNING` list (parse both from the module's own
  source, do not retype them); that a Staff caller is refused `403 administrator_required` and
  an unclaimed Administrator `403 password_change_required`; and that the response carries
  `cache-control: no-store`.
- `apps/api/tests/test_admin_authorization.py` — update the exact-set assertion at L379 to both
  routes, compared **sorted** so the assertion does not silently depend on declaration order,
  and update `CREATE_USER`'s "the only one until Story 1.9" comment. Nothing else in the file
  changes: both direction guards, the negative controls and the gate-chaining test now cover
  two routes without being touched, which is the property they were written for.
- `apps/web/src/screens/UserListScreen.tsx` + `.module.css` — **new.** Props
  `{ onBack: () => void; onAddUser: () => void }`.
  - Mount-time `apiRequest('/admin/users')` through `SessionProvider`'s `live`-flag pattern,
    in a `load()` the "Try again" control can call again. Three states and no fourth: loading
    (`role="status"`, "Loading users…"), failed (one `role="alert"` carrying the API's own
    sentence, or a local sentence for a non-`ApiRequestError`), loaded.
  - `asUsers(body)`: `Array.isArray(body) && body.every(isUser)` or a `MALFORMED_RESPONSE`
    `ApiRequestError`, mirroring `CreateUserScreen.asUser` — a partially-understood body must
    not be rendered as an authoritative answer to "who has access".
  - Title "Users", the "+ Add user" primary (the screen's **one** accent control) and a
    navy-outline "Back".
  - A `<table>` with a header row: Name, Email, Role, Status, Last login. Role cell: a
    display-only pill — Administrator navy fill / white text, Staff transparent with a hairline
    and muted text, both `--radius-full`, labels from the glossary. Status cell: "Active"
    (outline, muted) or "Deactivated" (`--color-destructive` fill, `--color-destructive-foreground`
    text), plus a muted "Locked until \<time\>" line when `locked_until` parses to an instant in
    the future. Last login: the locale string, or "Never" when null. A deactivated row also
    carries a muted row class, so the distinction survives a monochrome screen *and* is never
    colour-only.
  - The table sits in a scroll container with `role="region"`, `tabIndex={0}` and
    `aria-labelledby` the title, so the last column is reachable at 375px by keyboard and the
    page never scrolls sideways. Dense padding (`--space-2`/`--space-3`), hairline
    `--color-border` between rows, `--color-background` on hover, no card wrapper and no shadow
    (DESIGN.md `data-table-row`).
  - An empty array renders one muted "No users." line rather than a bare header. Unreachable in
    the product — the caller is themselves a row — and said so in the comment.
- `apps/web/src/App.tsx` — widen `Section` and `Screen` with `'users'`; `reachableBy` returns
  `role === 'admin'` for `'users'` as it does for `'create-user'`; `currentScreen` routes
  `'users'` through the same `reachableBy` fall-through to `'shell'`. Render the new screen in
  its own `AppShell` branch beside the create-user one, with `onBack` to `'home'` and
  `onAddUser` to `'create-user'`, and point `CreateUserScreen`'s `onBack` at `'users'` — the
  list is where it was opened from and where a new row should appear (the screen refetches on
  mount, so returning shows it). The home panel's door becomes **Users**, still
  role-conditional, with its comment updated: this is EXPERIENCE.md's own nav entry standing in
  for a nav that does not exist, and Create user is now reached from the list as line 34 says.
- `apps/web/src/App.module.css` — rename `.createUser` to `.userList`, same declarations,
  comment updated to say what it now opens. The file must still declare no `--color-accent`.
- `apps/web/src/screens/CreateUserScreen.tsx` — comment-only: the screen's docstring says the
  door is on the home panel and that "no user list" exists. Both are now false. Its behaviour,
  props and markup do not change.
- `apps/web/src/__tests__/user-list.test.tsx` — **new.** Every `apps/web` row of the I/O
  matrix, driven against a stubbed `fetch` with the screen rendered directly; plus the request
  shape (`GET /api/admin/users`, `credentials: 'same-origin'`, no body); that a deactivated
  account renders the word "Deactivated" and not only a class; that a lock in the future
  renders and a lock in the past does not; that "Never" appears for a null `last_login_at`;
  that "Try again" refetches and clears the alert on success; that "+ Add user" and "Back" call
  their props; that no control on the screen edits, deactivates, deletes or unlocks anything
  (Stories 1.10/1.11) — asserted over the rendered button names, not by eye.
- `apps/web/src/__tests__/create-user.test.tsx` — retarget the `describe('the door on the home
  panel')` block: the home-panel door is now **Users**, and Create user is reached from the
  list's "+ Add user". Every role-reconciler test in that block keeps its subject — a Staff
  user is offered no door, a demotion mid-screen lands on the home panel, a promotion leaves
  the user where it found them, the section is cleared rather than read past — and gains a
  `'/api/admin/users'` reply in its `stubFetch`. Back from Create user now returns to the list;
  a second Back returns home.
- `apps/web/src/__tests__/styling-wiring.test.ts` — point the home-panel-entry test at
  `.userList`; add `UserListScreen` to the alert-element `it.each` and give it an
  `.error`-colour case; add a describe for the new screen asserting `.add` is the accent fill
  with the navy foreground, `.back` is the navy outline, the stylesheet carries exactly one
  `--color-accent`, the deactivated badge is `--color-destructive` on
  `--color-destructive-foreground`, the Administrator badge is `--color-primary` on
  `--color-primary-foreground`, both badges are `--radius-full`, and the row carries the
  hairline `--color-border` separator and the `--color-background` hover DESIGN.md's
  `data-table-row` names.
- `README.md` — replace the "Listing, editing and deactivating users are Stories 1.9 to 1.11"
  sentence and add the operator paragraph: where the list is (**Users** on the home panel,
  Administrators only), what it shows, that a deactivated account is marked rather than hidden,
  that a lock shows on the account's status and still clears itself with nothing to press
  (Story 1.10), that last login is blank until the person first signs in, and that nothing on
  the list can yet be edited or deactivated.

**Acceptance Criteria:**

- Given a claimed Administrator and a `users` table holding their own row plus a deactivated
  account, an account that has never signed in and an account whose `locked_until` is in the
  future, when `GET /admin/users` is handled, then the response is `200` with all four rows as
  eleven-key `User` objects, ordered case-insensitively by name with email as the tie-break,
  carrying `cache-control: no-store` and no `password_hash` key anywhere in the body.
- Given a claimed **Staff** session, when it requests the same route, then the response is
  `403 administrator_required` from a dependency rather than from a check inside the handler,
  no row is disclosed, and the refusal is never a `401`.
- Given an Administrator still holding an admin-issued temporary credential, when they request
  the route, then the response is `403 password_change_required` — the forced-change gate fires
  before the role check — and `test_forced_change_gate.py` passes with no allowlist entry added.
- Given the served route table, when `apps/api/tests/test_admin_authorization.py` runs, then
  both `/admin/users` methods declare `require_administrator`, no route outside `/admin/`
  declares it, the checked set is non-empty, and both negative controls still fail the walker.
- Given `_SELECT_USERS` and `_INSERT_USER` read from `apps/api/api/users.py`'s own source, when
  their column lists are compared, then they are identical and name exactly `User.model_fields`
   — so a future column cannot reach one statement and not the other.
- Given an Administrator signed in to `apps/web`, when the shell renders, then a **Users** entry
  appears on the home panel and opens a list of every account with its status and last login;
  and given a Staff user, when the shell renders, then no Users entry appears anywhere and a
  section state that says otherwise still renders the home panel.
- Given the list is open and `GET /admin/users` fails, when the screen renders, then one
  `role="alert"` carries the API's own sentence, no table and no partial row is shown, and
  "Try again" refetches and replaces the alert with the table on success.
- Given the Create user screen opened from the list's "+ Add user", when Back is pressed, then
  the list is shown again and has refetched — so a user provisioned a moment ago is on it.
- Given `make lint` and `make test`, when they are run over the finished change, then both exit
  0 with every pre-existing test in `apps/api`, `apps/web`, `shared/schema` and `infra` passing.

## Spec Change Log

## Review Triage Log

### 2026-09-18 — Review pass
- intent_gap: 0
- bad_spec: 0
- patch: 12: (high 0, medium 3, low 9)
- defer: 3: (high 0, medium 2, low 1)
- reject: 7: (high 0, medium 0, low 7)
- addressed_findings:
  - `[medium]` `[patch]` Nothing asserted which class a rendered row or badge carried: inverting `user.active ? styles.statusOff : styles.statusActive` painted every active account in the destructive fill and left the whole suite green, because the styling tests only parse the stylesheet as text and the render tests only read the word. The mapping is now pinned at the rendered element against the CSS module itself, for the row, the status badge and the role badge.
  - `[medium]` `[patch]` The `generation` ref was documented at length and tested by nothing — every test settled its replies in order, so deleting the guard changed no result. Added a hand-settled stub and two tests: two reads open at once with the stale one settled last, and an unmount mid-flight.
  - `[medium]` `[patch]` The story's own acceptance sentence was never exercised end to end — the App-level tests reached the heading and stopped, and every content assertion rendered the screen with no session. Added an App-level test that signs an Administrator in, opens Users, and reads a row's status and last login through the real gate and shell.
  - `[low]` `[patch]` The column-drift guard compared the two lists whitespace and all, so it failed on a re-indent and was the reason `_SELECT_USERS` carried a continuation indent that did not align under its own `SELECT`. Both sides now normalise whitespace, and the statement is indented as a `SELECT` normally would be.
  - `[low]` `[patch]` `.deactivatedRow` restated `.row`'s background, border and hover verbatim and the markup picked one or the other, so a change to the row treatment would have applied to active rows only. The row now always carries `.row` and the variant holds only the muting.
  - `[low]` `[patch]` `.statusActive` was the commonest badge on the screen and the only one with no assertion between it and an accidental fill. Added beside the other three.
  - `[low]` `[patch]` The no-filter statement guard missed the shapes it names: `FETCH FIRST n ROWS ONLY`, and a named placeholder, which uppercases to `%(ROLE)S` and so contains no `%S`. Both now fail it, proved by mutation.
  - `[low]` `[patch]` The README's new paragraph said "Last login is blank — it reads 'Never'", contradicting itself and the constant's own reason for existing; "(Story 1.10)" read as though 1.10 removed a control rather than adding an unlock; and the rewrap had left an orphan line.
  - `[low]` `[patch]` The web fetch stub keyed its reply queue on the path alone, and `GET` and `POST` now share `/admin/users` — the first test to submit the form through the `App` root would have received the roster array as its create response. Keyed on method plus path.
  - `[low]` `[patch]` The screen's module docstring sat between the imports and the first constant, attached to nothing. Moved onto the export, as `CreateUserScreen` has it.
  - `[low]` `[patch]` `lockNotice` guarded its parse while `lastLogin` did not, although `isUser` had already required `Number.isFinite(Date.parse(...))` of both. One statement now says why neither needs it.
  - `[low]` `[patch]` The `.catch` comment claimed "a 401 never lands here as something to render", which is true of the app and false of the component in isolation. Bounded to the app, with a test recording what the screen on its own actually does.

### 2026-09-18 — Review pass
- intent_gap: 0
- bad_spec: 0
- patch: 2: (high 0, medium 1, low 1)
- defer: 0
- reject: 16: (high 0, medium 0, low 16)
- addressed_findings:
  - `[medium]` `[patch]` "Try again" removed itself on the press — the failure block it sits in is replaced by the in-flight line — so the browser dropped focus to `<body>` and a keyboard or screen-reader Administrator was left several tabs above the screen they had just acted on. It was the only control in the product that unmounts under the reader: every other screen moves focus deliberately after a refusal (`LoginScreen`, `CreateUserScreen`, `AccountSettingsScreen` each focus the field at fault), and this screen has no field. The heading now takes focus first, before the state change unmounts the button, with `tabIndex={-1}` so it adds no tab stop. Proved load-bearing by mutation.
  - `[low]` `[patch]` The screen's two prose lines — the muted in-flight line and the destructive refusal — were the only status text in `apps/web` with no colour assertion between them, although that is the pair `styling-wiring.test.ts` exists to hold apart: red is destructive-or-failed in this system and nothing else, so painting `.pending` with it would read a routine wait as a failure while every render test stayed green (those read the words and the roles, not the stylesheet). Both are now pinned. Proved load-bearing by mutation.

## Design Notes

**Why a second route on one path rather than a `users` module split.** `/admin/users` is the
collection; `GET` reads it and `POST` writes it. Keeping both in `api/users.py` is what lets
`_SELECT_USERS` sit next to `_INSERT_USER` where a reader compares the two column lists by eye,
and it leaves `test_no_registration.py`'s served-**path** set unchanged — a second path would
have needed that assertion edited for a route that creates nothing, which is exactly the kind
of edit that erodes a guard nobody wants eroded.

**Why a bare JSON array.** There is no cursor, no total and no page to carry, and inventing
`{"users": [...]}` to leave room for one is a shape the product would have to keep honouring
after pagination never arrives. `GET /auth/session` already returns a bare `User`; this returns
bare `User`s. The classic argument against a top-level array — JSON hijacking through
`<script src>` — needs an overridable `Array` constructor, which no browser has had since ES5,
and this response is `no-store`, cookie-gated and `SameSite=Strict` besides. When a cursor is
genuinely needed both halves change together, which is one commit in a two-file contract.

**Why no `LIMIT`.** The clause is "every account", and a list that silently stopped at 100
would be a surface that answers "who has access" with "some of them". The table is tens of rows
in an internal tool with no self-service registration — the row count is bounded by the number
of people an Administrator has personally provisioned. That is the same bet `login_attempts`
makes and it is stated here rather than talked down: if the list ever gets large, measure
before reaching for pagination.

**Why the lock is rendered as a line of text and not a third badge.** DESIGN.md names three
badge treatments — admin role, staff role, deactivated status — and no locked one. Inventing a
fourth is a decision for the design spine, not for this story, and the obvious candidate colour
is the accent, which would put a second orange thing on a screen whose "+ Add user" is meant to
be the only one. A muted "Locked until \<time\>" line under the status badge is factual, is
never the only signal, and satisfies FR-4's "visible to Administrators on that user's status"
without spending a token the system does not have. It is display-only in the strongest sense:
`shared_schema`'s own comment says a client that decides anything from this column is reading a
copy, and the comparison to "now" is made against the *browser's* clock, so a badly-skewed
device can show a lapsed lock or miss a live one — which changes nothing, because nothing is
gated on it and the throttle reads its own `login_attempts` row.

**Why the table scrolls at phone width instead of becoming cards.** DESIGN.md's `data-table-row`
note says the row "inherits Card styling" below the breakpoint, cross-referencing an
EXPERIENCE.md section that does not actually say so. The usual way to get there —
`display: block` on the table's parts with `::before` labels — strips the table semantics that
associate every cell with its column header, which is a real accessibility loss on an admin
surface EXPERIENCE.md itself calls desktop-first. One `<table>` at every width, inside a
labelled, focusable scroll container, keeps the header association and keeps the page from
scrolling sideways. The card treatment remains available to whoever builds the Catalogue table
in Epic 2 and can be applied to both at once.

**Why the home panel's door moves rather than multiplies.** EXPERIENCE.md's nav has one admin
entry for this collection — User List — and reaches Create/Edit User from a row or from "+ Add
User" on it (line 34). Story 1.8 put Create user on the home panel as an explicit stand-in for
that nav entry and said so: "when the nav lands the entry moves and `CreateUserScreen` does not
change." The list is that surface arriving. Leaving both doors on the landing panel would be
two admin entries the spine does not have, and would leave 1.10's Edit User with nowhere
obvious to go.

```python
# apps/api/api/users.py — the shape of the read, not the code.
_SELECT_USERS = """
SELECT id, name, email, role, active, must_change_password,
       temp_credential_expires_at, last_login_at, locked_until,
       created_at, updated_at
FROM users
ORDER BY lower(name), email
"""
# The column list is `_INSERT_USER`'s RETURNING list, character for character --
# one shape for every statement `User.model_validate` is handed. No WHERE, no
# LIMIT and no parameter: FR-10 is every account, and a filter here hides the
# row somebody opened the screen to find.
```

## Verification

**Commands:**
- `make lint` — expected: exit 0 (ruff check, ruff format --check, oxlint --deny-warnings,
  tsc --noEmit).
- `make test` — expected: exit 0; the `apps/api` database tests run against the ephemeral
  cluster or skip with the same "no PostgreSQL available" reason (DW-18/DW-39).
- `uv run pytest apps/api/tests/test_user_list.py apps/api/tests/test_admin_authorization.py -q`
  — expected: exit 0.
- `uv run pytest apps/api/tests/test_forced_change_gate.py apps/api/tests/test_no_registration.py apps/api/tests/test_source_guards.py apps/api/tests/test_create_user.py -q`
  — expected: exit 0, **with none of those four files modified**.
- `npm --prefix apps/web run test` — expected: exit 0, including the retargeted create-user door
  block and the new screen's styling-wiring describe.
- `git status --porcelain infra/migrations shared/schema` — expected: empty. This story ships no
  migration and no contract change.
- `git diff --stat apps/web/src/api/client.ts` — expected: empty. This route invents no error
  code.
- Prove each new guard load-bearing by removing what it guards, then restoring it: drop
  `require_administrator` from the new route (the admin guard and the Staff-refusal test fail),
  add a `LIMIT` to `_SELECT_USERS` (the every-account test fails), reverse the `ORDER BY` (the
  ordering test fails), change one column in `_SELECT_USERS` (the drift guard fails), return
  `body` unchecked instead of `asUsers(body)` (the malformed-body test fails), and drop the
  `reachableBy` arm for `'users'` (the Staff-cannot-reach-it test fails).

**Manual checks (if no CLI):**
- Invoke the `ui-ux-pro-max` skill and run its pre-delivery checklist against the User List
  screen before calling this story done (epic context: required for every UI story).
- `make migrate`, then `make dev`: sign in as the seeded Administrator, claim the account, open
  Users from the home panel, add a user from "+ Add user", press Back and confirm the new row is
  on the list with "Never" under Last login. Deactivate one directly in the database and reload
  — it is marked, not hidden. Fail a sign-in ten times against one address, then reload the list
  and confirm the lock shows on that account's status. Sign in as a Staff user and confirm no
  Users entry exists anywhere.
- At 375px: the page does not scroll sideways, the table's own container does, and every control
  is at least 44×44px.


## Auto Run Result

Status: done

**Implemented change.** FR-10's read beside the write that already existed: `GET /admin/users`,
Administrator-only through the same `require_administrator` dependency, returning every `users`
row as the shared eleven-key `User` contract in one ordered array with no filter, no page and no
parameter — and `UserListScreen`, which renders them as EXPERIENCE.md's dense admin table (name,
email, role badge, status badge, last login, with FR-4's lock as a muted "Locked until" line under
the status badge). The home panel's interim admin door became **Users**, and Create user moved
behind the list's "+ Add user", with `Back` returning to the list so the row just provisioned is on
the list that comes back.

**Files changed.**
- `apps/api/api/users.py` — `_SELECT_USERS` and the `list_users` handler beside the existing write.
- `apps/api/tests/test_user_list.py` — the route's 23 tests: every account including the caller's
  own, deactivated, locked and never-signed-in rows, the ordering, the bare-array shape,
  `no-store`, the four refusals, and the column-drift guard against `_INSERT_USER`.
- `apps/api/tests/test_admin_authorization.py` — the exhaustive route enumeration now carries two
  methods on one path, compared sorted.
- `apps/web/src/screens/UserListScreen.tsx`, `.module.css` — the new screen and its stylesheet.
- `apps/web/src/App.tsx`, `App.module.css` — the `'users'` section, its reachability arm, the
  renamed home-panel door, and Create user's `Back` retargeted to the list.
- `apps/web/src/screens/CreateUserScreen.tsx` — docstring only: where it is now opened from.
- `apps/web/src/__tests__/user-list.test.tsx` — 32 tests for the screen and the route to it.
- `apps/web/src/__tests__/create-user.test.tsx` — the list is now on the path to Create user, and
  the fetch stub is keyed on method plus path because `GET` and `POST` share the address.
- `apps/web/src/__tests__/styling-wiring.test.ts` — the new screen's stylesheet guards.
- `README.md` — the Users screen, the "Never" cell, the lock line, and the absence of row verbs.

**Review findings breakdown (this pass).** 2 patches applied (1 medium, 1 low), 0 items deferred,
16 items rejected. Both patches are recorded in the Review Triage Log entry above and were each
proved load-bearing by mutation. The four review layers ran in parallel: blind hunter, edge-case
hunter, verification-gap reviewer, intent-alignment auditor. The verification-gap layer traced
every behavioural part of the diff to the tests that observe it and reported no verification gaps,
mutation-confirming the `reachableBy` arm, Create user's `Back` target and the `generation` guard.
The intent-alignment layer found the diff implements a defensible reading of every clause in the
contract, with no "Never" clause breached; its divergences are documented deviations (the
column-identity guard normalises whitespace and reaches `auth._SET_PASSWORD` transitively through
`test_create_user.py`) or coverage that lives at shared surfaces this story inherits rather than
re-asserts (the 401 drop to login, the cleared cookie, the stylesheet's repo-wide token guard).

**Follow-up review recommendation: false.** Patched this pass: 0 high, 1 medium, 1 low. Score =
3 × 1 + 1 × 1 = 4, which is below 5, and nothing patched was high severity.

**Verification performed.**
- `make lint` — exit 0 (ruff check, ruff format --check, oxlint --deny-warnings, tsc --noEmit).
- `make test` — exit 0: 691 passed (pytest workspace), 713 passed in 16 files (apps/web vitest).
- `uv run pytest apps/api/tests/test_user_list.py apps/api/tests/test_admin_authorization.py -q`
  — exit 0, 42 passed.
- `test_forced_change_gate.py`, `test_no_registration.py`, `test_source_guards.py` and
  `test_create_user.py` confirmed unmodified since `{baseline_revision}` by
  `git diff --name-only` (empty).
- `git status --porcelain infra/migrations shared/schema` — empty. No migration, no contract change.
- `git diff --stat apps/web/src/api/client.ts` — empty. No new error code.
- Both patches mutation-proved: removing the focus call fails
  `leaves the reader on the screen when Try again removes itself`; repainting `.pending` with
  `--color-destructive` fails `keeps the wait muted and the refusal destructive`.

**Residual risks.**
- `ORDER BY lower(name)` folds ASCII only under Postgres's default `C` collation, so an accented
  or non-Latin name still files by code point relative to the rest. Rejected rather than patched:
  the fix is a collation decision (`COLLATE "und-x-icu"` raises on a cluster built without ICU, and
  would turn the whole list into a `500`), the roster the product actually holds is romanized, and
  the acceptance clause — case-insensitive by name then email — is met for that script. `email` as
  the tie-break needs no fold: `_INSERT_USER` writes `lower(%s)` and the table carries
  `CHECK (email = lower(email))`, so every stored address is already folded.
- The list is a mount-time snapshot: it refetches when the screen is opened, and nothing
  revalidates it while it stays open, so an access change made elsewhere is not reflected until
  the Administrator navigates back to it. Nothing in the product is gated on the list, and
  refetch-on-mount is what makes the row just provisioned appear.
- A "Locked until" line is derived from the browser's clock at render and is not re-evaluated as
  the deadline passes, so a lock that lapses while the screen is open stays on it until the next
  load. Display only — `shared_schema.user` makes `locked_until` status and never enforcement, and
  nothing on this screen or behind it decides from the answer.
- `must_change_password` and `temp_credential_expires_at` reach the wire and are rendered by no
  column, so an unclaimed account whose 72 hours lapsed reads exactly like one handed over an hour
  ago. Already carried as the first `deferred` entry on this spec; Stories 1.10/1.11 are the
  natural owners.
