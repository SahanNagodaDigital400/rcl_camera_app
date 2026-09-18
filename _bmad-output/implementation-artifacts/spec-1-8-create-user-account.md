---
title: 'Story 1.8 — Create User Account'
type: 'feature'
created: '2026-09-18'
baseline_revision: '5e918655a60cba89813f75ba6d11d153eb4b7ca8'
status: 'done'
review_loop_iteration: 0
followup_review_recommended: true # score 15 (0 high, 2 medium, 9 low patched this pass); see Auto Run Result
context:
  - '{project-root}/AGENTS.md'
  - '{project-root}/_bmad-output/planning-artifacts/architecture/architecture-rcl_camera_app-2026-08-30/ARCHITECTURE-SPINE.md'
  - '{project-root}/_bmad-output/planning-artifacts/ux-designs/ux-rcl_camera_app-2026-09-08/EXPERIENCE.md'
  - '{project-root}/_bmad-output/planning-artifacts/ux-designs/ux-rcl_camera_app-2026-09-08/DESIGN.md'
warnings: ['oversized']
deferred:
  - summary: >-
      Provisioning a user writes no audit entry, so the product's first
      privileged write has no record of who granted whose access.
    evidence: |-
      AGENTS.md Policy requires the append-only log to cover user changes, and
      `POST /admin/users` is the clearest one there is. Story 1.12 owns the write
      path and this endpoint's docstring names the entry it owes; no private log
      path was built in the meantime. Until that log exists the only trace is the
      row's own `created_at`, which does not say by whom.
    location: >-
      apps/api/api/users.py (create_user)
    severity: medium
  - summary: >-
      DW-69 is now a four-endpoint problem — `POST /admin/users` adds a 64 MiB
      Argon2id hash per call, reachable by any Administrator session and bounded
      by nothing.
    evidence: |-
      The handler hashes on every request that gets past the length rules, and no
      counter keys on the calling Administrator. FastAPI admits ~40 concurrent
      sync handlers, so one account can hold ~40 hashes at once. DW-40 and DW-69
      are both open and are decisions about what a counter would be keyed on;
      Story 1.6 scoped throttling to login, and this story could not settle it.
    location: >-
      apps/api/api/users.py (create_user)
    severity: medium
  - summary: >-
      A mistyped address is permanently consumed by the unique index, and nothing
      in the product can edit, reissue or remove the row until Stories 1.10/1.11.
    evidence: |-
      `users_email_lower_key` refuses the corrected second attempt with `409
      email_already_exists`, and the only remaining surface is `POST
      /admin/users` itself. README.md states the workaround as advice — provision
      them afresh under a different address — which leaves an unusable row behind
      with no way to reach it. Story 1.10 owns the edit and 1.11 the delete.
    location: >-
      apps/api/api/users.py (_INSERT_USER)
    severity: medium
  - summary: >-
      A `201` whose body or transport fails after the row is committed is
      reported to the Administrator as a failure, and nothing in the product can
      tell them which it was.
    evidence: |-
      `asUser` throws `ApiRequestError(MALFORMED_RESPONSE, ..., 201)` after the
      INSERT has committed, and the screen's `catch` treats it exactly like a
      refusal; a timeout or dropped connection after the commit does the same. The
      retry answers `409 email_already_exists`, and with no user list until Story
      1.9 there is no surface that shows whether the row exists. This is DW-75's
      shape on a new endpoint and needs the same decision.
    location: >-
      apps/web/src/screens/CreateUserScreen.tsx (handleSubmit)
    severity: medium
  - summary: >-
      Back, Account, Sign out and a mid-session demotion all unmount the screen
      with no warning, discarding a half-typed form and a result panel holding a
      credential nothing can recover.
    evidence: |-
      EXPERIENCE.md line 90 asks for exactly this warning — "never silently
      dropping an in-progress admin form — warn before navigating away from
      unsaved catalogue/user edits". The temporary password is held only in this
      screen's state; the API never returns it and no screen can show it again.
      Building the guard means an unsaved-changes convention the product does not
      have yet, and it lands on every admin form from Story 1.10 on.
    location: >-
      apps/web/src/App.tsx (showSection), apps/web/src/screens/CreateUserScreen.tsx
    severity: medium
  - summary: >-
      The request seam between the screen and the endpoint is asserted twice
      against hand-written literals and never crossed, so renaming a body field
      on either side leaves both suites green.
    evidence: |-
      `create-user.test.tsx` checks the body against a stubbed `fetch`;
      `test_create_user.py` checks it against its own `_body()`. The *response*
      is pinned across languages (`user-contract.test.ts` against
      `User.model_fields`) and so are the error codes
      (`error-code-parity.test.ts`), but the request body is not. The repository
      has no e2e harness and no `e2e` make target, so this is structural rather
      than a choice this story made.
    location: >-
      apps/web/src/__tests__/create-user.test.tsx, apps/api/tests/test_create_user.py
    severity: medium
  - summary: >-
      The three route-table walkers disagree about rigour, and the two weaker
      ones would pass a sub-application mounted under `/admin/`.
    evidence: |-
      `test_admin_authorization._api_routes` raises `AssertionError` on any route
      type it does not understand. `test_no_registration._routes()` — whose exact
      served-path set this story extended — and `test_forced_change_gate`'s own
      third copy both skip a `Mount`, a `WebSocketRoute` or a static handler
      silently. Consolidating them is a change to guards three stories already
      depend on.
    location: >-
      apps/api/tests/test_no_registration.py, apps/api/tests/test_forced_change_gate.py
    severity: low
  - summary: >-
      `max_length` runs before the stripping validator, so a name of exactly the
      bound submitted with surrounding whitespace is refused with the generic
      `validation_error` although the value that would be stored fits.
    evidence: |-
      Pydantic applies `Field(max_length=MAX_NAME_LENGTH)` to the raw value and
      `_named` strips afterwards. The parametrized test covers only
      `"x" * (MAX_NAME_LENGTH + 1)`. Moving the bound into the validator changes
      which refusal shape the field produces, which is a contract decision rather
      than a fix.
    location: >-
      apps/api/api/users.py (CreateUserRequest)
    severity: low
  - summary: >-
      The API suite's ephemeral cluster runs a `C.UTF-8` collation whose `lower()`
      folds ASCII only, so no test can exercise a Python/Postgres case-folding
      disagreement.
    evidence: |-
      `conftest.py` builds the cluster with `initdb`'s default. A probe of ~12k
      codepoints against that cluster found zero disagreements, so the
      behavioural non-ASCII test passes with or without `_INSERT_USER`'s
      `lower(%s)`; a statement-level pin holds the hardening instead. Running the
      suite on a full Unicode collation is an `initdb` flag and a separate
      decision affecting every database test.
    location: >-
      apps/api/tests/conftest.py
    severity: low
  - summary: >-
      An address whose Python fold and Postgres fold differ can be provisioned
      successfully and can then never sign in, because the login lookup compares
      the two folds against each other.
    evidence: |-
      `_INSERT_USER` stores `lower(%s)` — the Postgres fold — while
      `auth._SELECT_CREDENTIAL` matches `WHERE lower(email) = %s` against
      `payload.email.strip().lower()`, the Python fold. The two are equal only
      where `lower()` agrees across the two implementations, which is exactly the
      condition `lower(%s)` was added because it can fail. Where it fails the
      `201`, the response body and the row are all correct and the account is
      unreachable, with no error anywhere. The lookup is in `auth.py`, which this
      story's intent forbids changing, and DW-85 records that the suite's
      `C.UTF-8` cluster cannot observe either half.
    location: >-
      apps/api/api/auth.py (_SELECT_CREDENTIAL, login)
    severity: medium
---

<intent-contract>

## Intent

**Problem:** FR-11 has no implementation. Every `User` row in the product's lifetime is meant to be
written by an Administrator, and the only writer that exists is `infra`'s migration-time seeder —
so granting a member of staff access today means a developer with `DATABASE_URL`, which is exactly
the wait FR-11 exists to remove. There is also no role check anywhere in `apps/api`:
`dependencies.py` has `current_user` and `require_claimed_user` and its own docstring defers "later,
a role check" to this story, so nothing yet enforces AGENTS.md's server-side-authorization rule.

**Approach:** One Administrator-only endpoint, `POST /admin/users`, in a new `api.users` module, and
the dependency that guards it — `require_administrator`, chained on `require_claimed_user` — plus a
guard test that makes "every `/admin/` route declares it" a property of the route table rather than
of each route's author. The row is written the way `infra`'s seeder writes one: claimed-later, with
`must_change_password = true` and a 72-hour `temp_credential_expires_at`, so Story 1.4's gate is what
the new user meets on first sign-in. `apps/web` gains a Create User screen reached from a
role-conditional entry on the home panel, which shows the Administrator the credential to pass on by
hand and says that the app sends no mail.

## Boundaries & Constraints

**Always:**
- **The role check is a dependency, not a line in a handler.** `require_administrator` lives in
  `api/dependencies.py` beside `require_claimed_user` and **depends on it**, so the forced-change
  gate still holds for an Administrator on a temporary credential and
  `tests/test_forced_change_gate.py` keeps passing with no allowlist entry. A new guard test asserts
  every route whose path starts `/admin/` declares it — the rule Stories 1.9–1.11 inherit.
- **The refusal for a Staff caller is `403`, never `401`.** `apps/web`'s `apiRequest` fires
  `notifyUnauthorized` on *status* 401, so a 401 here would sign an Administrator out for a race the
  server won. Its own code, `administrator_required`, distinct from `password_change_required`.
- **72 hours has exactly one statement in the repository.** `infra/rocell_infra/seed.py`'s
  `TEMP_CREDENTIAL_LIFETIME_HOURS` moves to `shared_schema` and both writers import it; `seed.py`
  re-exports it through its existing `__all__` so `infra/tests/test_migrate.py` needs no change.
  The deadline is computed by Postgres (`now() + make_interval(hours => %s)`), as the seeder does —
  never against the API host's clock.
- **The created row is `must_change_password = true` with an expiry set, and `active = true`.** A
  flagged row with a NULL expiry is permanently unusable by design (DW-44); this writer never
  produces one.
- **The password is hashed by `shared_schema.passwords.hash_password`, outside any transaction**, and
  the rules are read from `password_rule_violation` — the one statement of them. Argon2id only
  (AGENTS.md).
- Parameterized SQL only, as a module-level `%s` constant. The `INSERT ... RETURNING` list is the
  eleven-column `User` list `_RECORD_LOGIN`, `_SET_PASSWORD` and `_CHANGE_PASSWORD` already carry,
  character for character.
- **The email is normalized `strip().lower()` before the write**, because `users` carries
  `CHECK (email = lower(email))` and its only unique index is `ON (lower(email))`.
- **Uniqueness is decided by the database, not by a prior `SELECT`.** Catch
  `psycopg.errors.UniqueViolation` on that index and answer `409`; a read-then-write would be a race
  that hands two accounts the same login.
- **The response never carries a digest and never echoes the submitted password.**
  `response_model=User` (which has no `password_hash` field at all), plus `NO_STORE` — the body
  carries a name and an address.

**Block If:**
- Making `require_administrator` chain on `require_claimed_user` turns out to conflict with
  `test_forced_change_gate.py` — that would mean an admin surface reachable on an unclaimed
  credential, and neither the gate nor FR-2 may be relaxed without a human.
- The `users` table turns out to need a schema change to hold what FR-11 submits. It does not
  (name, email, role, password, flags and expiry all exist), so if one appears the reading of the
  intent is wrong, not the migration.

**Never:**
- **No self-provisioning path of any kind.** The route is authenticated, Administrator-only, and
  `tests/test_no_registration.py`'s exact served-path set grows by one entry with a written reason.
  Its source scan forbids the phrases that describe a public signup; obey it in every new file,
  comment and docstring — say "provision a user" where the forbidden wording would otherwise fall.
- **No app-sent email, ever** — not a dependency, not an import, not a stub, not a "send credential"
  control on the screen. AGENTS.md Policy and FR-11: the Administrator communicates it manually.
  `tests/test_no_password_reset.py`'s mail-transport scan stays green untouched.
- **No audit entry.** Story 1.12 owns the write path and owes this endpoint one entry. No private
  log path is built in the meantime.
- **No throttling of the new endpoint.** It is a fourth Argon2id-backed endpoint and a direct
  extension of DW-40/DW-69, which are open and are decisions about what a counter would be keyed on.
  It is also Administrator-only, so the caller is already trusted and already identified.
- **No user list, no edit, no deactivate, no delete** — Stories 1.9, 1.10 and 1.11. No
  `GET /admin/users` "so the screen has something to show".
- **No generated password, no strength meter, no reveal toggle, no confirm field.** The acceptance
  clause says the Administrator submits the temporary password.
- **No role beyond `staff` and `admin`** (AGENTS.md), and no role-conditional *nav* — the nav spans
  six surfaces of which five do not exist. One entry on the home panel is the interim door.
- No change to `apps/api/api/auth.py`, `api/sessions.py` or `shared_schema/passwords.py`.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Happy path | Administrator, claimed; valid name, email, role, temporary password | `201` with the `User` body: `active` true, `must_change_password` true, `temp_credential_expires_at` ≈ now + 72h, `last_login_at` null | No error |
| Immediately usable | the `201` has just returned | `POST /auth/login` with that email and password succeeds and returns the same `User` | — |
| Gated by Story 1.4 | that new user, now signed in | `POST /auth/password/change` answers `403 password_change_required`; `POST /auth/password` claims the account | `require_claimed_user` |
| Staff caller | a claimed Staff session | `403 administrator_required`; **no row is written and no password is hashed** | The dependency refuses before the handler runs |
| Administrator on a temporary credential | `must_change_password = true`, role admin | `403 password_change_required` | `require_claimed_user`, reached first |
| Not signed in | no cookie | `401 unauthorized`, cookie cleared | `current_user`'s existing refusal |
| Demoted mid-session | role flipped to `staff` between two requests | the very next request is refused `403 administrator_required` — the session lookup re-reads role (AD-3) | — |
| Email already in use | an address differing only in case or surrounding space | `409 email_already_exists`; nothing written | `UniqueViolation` on `users_email_lower_key`, caught; anything else re-raised |
| Email not an address | no `@`, or an empty side of it, or a control character | `422 invalid_email` with the sentence naming the rule; nothing hashed, nothing written | Refused before `hash_password` |
| Temporary password breaks a rule | empty / <12 / >128 characters | `422 weak_password` with `password_rule_violation`'s sentence verbatim | The existing code, the existing message |
| Blank or oversized name | whitespace-only, or over `MAX_NAME_LENGTH` | `422 validation_error` from the request model | Bounded before the handler |
| Unknown role | `role: "owner"` | `422 validation_error` | `Role` is a `StrEnum`; pydantic refuses it |
| Unknown body key | an extra JSON key | `422 validation_error` | `extra="forbid"` |
| `apps/web` — Staff signed in | home panel | **no Create user entry is rendered**, and the screen is unreachable from the shell | The cached role is a render cache, never the control |
| `apps/web` — refusal shown | `email_already_exists` or `invalid_email` | the API's sentence, with the **email** field marked invalid and focused; every typed value is kept | — |
| `apps/web` — refusal shown | `weak_password` | the API's sentence, with the **temporary password** field marked invalid and focused | — |
| `apps/web` — success | `201` | the form clears and a result panel shows the name, email, role, the temporary password as typed, the expiry from the response, and that the app sends no email | No navigation, no toast |
| `apps/web` — demoted while on the screen | cached `user.role` becomes `staff` | the shell renders the home panel instead — the highest surface the new role reaches, not a dead screen (EXPERIENCE.md:95) | A pure function of role, not an effect |

</intent-contract>

## Code Map

**Read-only sources of truth (do not edit):**
- `_bmad-output/planning-artifacts/epics.md` **lines 272–283** — Story 1.8's clauses verbatim; also
  **286–307** (1.9/1.10, which own the list and the edit this story must not build).
- `_bmad-output/specs/spec-rcl_camera_app/functional-requirements.md` **FR-11** (line 40) — "Name,
  email, role, initial (temporary) password. No email sent … User can authenticate immediately,
  gated by FR-2." **FR-1** (line 9) is the no-registration rule.
- `AGENTS.md` — Argon2id only; **server-side authorization on every endpoint, independent of what
  the UI hides**; no app-sent email; 72-hour temporary credentials; no third role; parameterized SQL;
  no secrets in fixtures; security paths need failure-case tests.
- `ARCHITECTURE-SPINE.md` **AD-3** (role and active are re-read per request through the one session
  lookup, never cached at login — the mechanism behind the demoted-mid-session row above) and the
  **Consistency Conventions** table ("Every privileged action re-verifies role server-side per
  request"; UUIDv4 ids, ISO 8601 UTC, one error envelope).
- `EXPERIENCE.md` **line 18** (the nav is role-conditional, not a menu with disabled items — a Staff
  user never sees an Admin entry), **line 34** (the Create/Edit User surface: "Account fields, role",
  Admin), **line 87** (a rejection names the rule that failed), **line 95** (a permission revoked
  mid-session redirects to the highest surface the new role can reach), **lines 50–57** (voice).
- `DESIGN.md` — **Button (primary)** (accent fill, navy foreground, exactly one per screen),
  **Button (secondary)** (navy outline), the **Save indicator** bullet, and the token list
  `tokens.css` mirrors.
- `deferred-work.md` — **DW-40**/**DW-69** (the Argon2id endpoints nothing throttles; this adds a
  fourth and does not close them), **DW-17** (`users` has no BEFORE UPDATE trigger — irrelevant to an
  INSERT, whose `created_at`/`updated_at` defaults apply, and worth saying so), **DW-44** (a flagged
  row with a NULL expiry is unusable — this writer cannot make one), **DW-64** (FR-4's lock has no
  rendering owner; not this story's).

**Files that already exist and constrain the shape:**
- `apps/api/api/dependencies.py` — `current_user` (L115) and `require_claimed_user` (L142) are the
  structural template: a dependency taking the previous one's `User` and raising
  `ApiError(<CODE>, <MESSAGE>, status_code=403, headers=NO_STORE)`. `NO_STORE` (L71),
  `not_signed_in()` (L99), `PASSWORD_CHANGE_REQUIRED` (L91). The module docstring opens "Two of
  them" and names the later role check — both need updating.
- `apps/api/api/auth.py` — the module conventions this new one copies and **does not change**:
  sync `def` handlers (never `async`, psycopg is synchronous), `#:` comment blocks above every
  module-level constant arguing *why*, SQL as `_UPPER_SNAKE` triple-quoted constants placed directly
  above their handler, `<Verb>Request` pydantic models with `extra="forbid"` and `Field(max_length=)`
  bounds. `MAX_EMAIL_LENGTH = 320` (L132), `MAX_PASSWORD_FIELD_LENGTH = 4096` (L219),
  `WEAK_PASSWORD` (L138), `_weak_password(rule)` (L338) and `_is_addressable(email)` (L282) — the
  control-character check that keeps a NUL out of psycopg — are the pieces to reuse or mirror.
  `_RECORD_LOGIN` (L255), `_SET_PASSWORD` (L782), `_CHANGE_PASSWORD` (L1017) carry the eleven-column
  `RETURNING` list the new statement must match exactly.
- `apps/api/api/main.py` — `create_app()` (L128) registers the four exception handlers and
  `app.include_router(auth.router)` at L170; the new router is included beside it.
  `validation_error_handler` (L104) renders **one generic sentence** for every 422 it makes — which
  is why a malformed email gets its own code rather than being left to the request model.
- `apps/api/api/db.py` — `get_connection` (L121) is how a route gets `conn`; connections are
  `autocommit=True` with `dict_row`, so a single `INSERT` needs no `with conn.transaction():`.
- `apps/api/api/sessions.py` — `lookup_session` re-reads role and active per request. **Not edited.**
- `shared/schema/shared_schema/user.py` — `Role` (L27, `STAFF`/`ADMIN`), `User` (L34) with
  `model_config = ConfigDict(extra="forbid")` and no `password_hash` field. This is where
  `TEMP_CREDENTIAL_LIFETIME_HOURS` moves.
- `shared/schema/shared_schema/passwords.py` — `password_rule_violation`, `hash_password`,
  `MIN_PASSWORD_LENGTH`/`MAX_PASSWORD_LENGTH`. **Read-only.**
- `infra/rocell_infra/seed.py` — `TEMP_CREDENTIAL_LIFETIME_HOURS` (L40), `_INSERT_ADMINISTRATOR`
  (L44) — the column list, the `now() + make_interval(hours => %s)` idiom and the
  `from psycopg import errors as pg_errors` import the new module copies — and `__all__` (L206),
  which keeps `seed.TEMP_CREDENTIAL_LIFETIME_HOURS` resolving for `infra/tests/test_migrate.py`.
- `apps/api/tests/conftest.py` — `conn`, `client` (https `base_url`), `make_user(role=, active=,
  must_change_password=, temp_credential_expires_at=, name=)` → a frozen `Account(id, email,
  password, name)`. `make_user(role=Role.ADMIN)` already yields a claimed Administrator, so **no
  fixture change is needed**; the created user's role is read off the response body.
- `apps/api/tests/test_no_registration.py` — `test_the_route_table_is_the_five_auth_routes_and_health`
  (L140) asserts the served path set **exactly** (L154–161): the set and the test's name both change.
  `ROUTE_WORDS` (L68) forbids `register`/`signup`/`join` in a path; the source scan (L74–82) forbids
  the signup phrasings in every `.py .ts .tsx .css .html .sql .json` file under `apps/ infra/
  scripts/ shared/`.
- `apps/api/tests/test_forced_change_gate.py` — `ALLOWED_WITHOUT_THE_GATE` (L55), `_declares` (L79)
  which walks the dependency tree **at any depth** and whose docstring names this exact case,
  `_api_routes` (L96), `_ungated_routes` (L155). The shape the new admin guard copies; **not edited**.
- `apps/api/tests/test_source_guards.py` — `INTERPOLATED_SQL` (L70) forbids SQL built with `+` or an
  f-string; `test_the_scan_reaches_the_files_it_claims_to` (L87) names the files that must stay
  scanned.
- `apps/web/src/api/client.ts` — `apiRequest(path, {method, body})` (L238), `ApiRequestError`
  (`code`, `status`, L132), `notifyUnauthorized` on **status 401 only** (L290), and the exported code
  constants (**every** one needs a row in the parity test). L184–186 already anticipates screens
  calling `apiRequest` directly.
- `apps/web/src/auth/SessionProvider.tsx` — `useSession()`, and L19–25: *the cached `User` is a
  render cache and never an authorization decision*. **Not edited** — see Design Notes.
- `apps/web/src/App.tsx` — `Section` (L26), `Screen` (L38), `currentScreen` (L40), `Gate` with its
  render-phase status reset (L73–95, written that way because oxlint's `react/set-state-in-effect`
  forbids the effect), the focus effect keyed on `screen` (L100), `showSection` (L185), and the two
  `AppShell` branches (L211–237). `App.module.css` declares no `--color-accent` today.
- `apps/web/src/screens/AccountSettingsScreen.tsx` / `.module.css` — the form this screen is modelled
  on: one `useId` per field plus one for the error, `noValidate`, `typed(set)` clearing the
  indicator, the blank-field guard that tests `.trim()` but sends the untrimmed value,
  `FormError { message, fieldAtFault }`, the single `role="alert"` node rendered in exactly one of
  three slots, `.submit` (accent) / `.back` (navy outline) / `.indicator`.
- `apps/web/src/components/AppBar.tsx` / `AppShell.tsx` — the optional-prop pattern
  (`onOpenAccount?: (() => void) | undefined`). **Not edited**: the new door is on the home panel.
- `apps/web/src/__tests__/no-raw-values.test.ts` — every colour and length in a new `.module.css`
  must be `var(--token)`; `@media` preludes must read exactly `768px`; no Phosphor `weight` prop; no
  bare dimension on a component prop.
- `apps/web/src/__tests__/styling-wiring.test.ts` — a module's declared classes and its neighbouring
  `.tsx`'s `styles.x` references must match **in both directions** (no dead class, no dangling one);
  the `.error`-colour cases (L238–266), the alert-element `it.each` (L300–312) and the
  one-accent-per-screen describes (L337, L368) are the lists a new screen joins.
- `apps/web/src/__tests__/error-code-parity.test.ts` — `PYTHON`/`TYPESCRIPT` maps (L48–64) and
  `'compares every code the client exports'` (L87): a new `export const X = '...'` in `client.ts`
  fails until both maps carry it and a matching `NAME = "..."` exists in the named Python module.
- `apps/web/src/__tests__/{auth-gating,account-settings}.test.tsx` — the eleven-key `User` fixture
  (there is **no admin fixture yet**), the local non-exported `stubFetch` helper, and the
  request-shape assertion pattern (method, `credentials`, headers, exact snake_case body).
- `shared/schema/shared_schema/ts/user.ts` — `Role`, `ROLES`, `isRole`, `isUser`. `ROLES` is what
  the role picker iterates. `apps/web/src/styles/global.css` already gives `select` the font reset
  and the 44×44 touch floor.
- `README.md` lines 74–100 — the operator narrative the provisioning paragraph joins.

## Tasks & Acceptance

**Execution:**

- `shared/schema/shared_schema/user.py` — add `TEMP_CREDENTIAL_LIFETIME_HOURS = 72` with the
  AGENTS.md citation seed.py's copy carries. One statement of the deadline, importable by both
  writers; `apps/api` depends on `shared-schema` and may not depend on `infra`.
- `infra/rocell_infra/seed.py` — import it from `shared_schema.user` instead of declaring it; leave
  the name in `__all__` so `seed.TEMP_CREDENTIAL_LIFETIME_HOURS` still resolves and
  `infra/tests/test_migrate.py` is untouched.
- `apps/api/api/dependencies.py` — `ADMINISTRATOR_REQUIRED = "administrator_required"` and its
  sentence (`NOT_AN_ADMINISTRATOR`), then
  `require_administrator(user: Annotated[User, Depends(require_claimed_user)]) -> User` raising
  `403` with `NO_STORE` when `user.role is not Role.ADMIN`. Document: why it chains the gate rather
  than `current_user`; why it is a 403 and not a 401 (`notifyUnauthorized` fires on status 401); and
  that AD-3's per-request re-read is what makes a demotion effective on the next request. Update the
  module docstring — it now describes three dependencies and no longer defers the role check.
- `apps/api/api/users.py` — **new.** `router = APIRouter(tags=["users"])`, and:
  - `INVALID_EMAIL = "invalid_email"` with a sentence naming the rule, and
    `EMAIL_ALREADY_EXISTS = "email_already_exists"` with one that does not reveal anything a caller
    who submitted the address does not already know. `MAX_NAME_LENGTH = 200`.
  - `class CreateUserRequest(BaseModel)` — `extra="forbid"`; `name: str` bounded
    `min_length=1, max_length=MAX_NAME_LENGTH` with a validator that strips and rejects the
    whitespace-only case; `email: str` bounded by `MAX_EMAIL_LENGTH`; `role: Role`;
    `temporary_password: str` bounded by `MAX_PASSWORD_FIELD_LENGTH` and carrying **no minimum**, so
    a short one is answered by the rule-naming 422 rather than the generic one. Docstring: why the
    email's rule lives in the handler (it needs a code an Administrator can act on) while the name's
    lives here (it has no rule beyond "present and bounded").
  - `_normalize_email(email) -> str | None` — `strip().lower()`, then refuse a control character
    (mirroring `auth._is_addressable`'s reason: Postgres text cannot carry a NUL) and anything that
    is not exactly one `@` with a non-empty side each. Deliberately the weakest check that catches a
    real typo without rejecting an internal address; say so.
  - `_INSERT_USER` — `INSERT INTO users (name, email, password_hash, role, active,
    must_change_password, temp_credential_expires_at) VALUES (%s, %s, %s, %s, true, true, now() +
    make_interval(hours => %s)) RETURNING <the eleven columns, identical to _SET_PASSWORD's>`.
    Comment: `true, true` is FR-11 + FR-2, not a default to be read from the schema; the deadline is
    Postgres's clock; `created_at`/`updated_at` take their column defaults, so DW-17 does not apply.
  - `@router.post("/admin/users", response_model=User, status_code=201)` →
    `def create_user(payload, response, administrator: Annotated[User, Depends(require_administrator)],
    conn)`. Sync `def`. Order: `NO_STORE` → normalize the email (`None` → `422 invalid_email`) →
    `password_rule_violation` (→ `422 weak_password`) → `hash_password` → `_INSERT_USER`, catching
    only `psycopg.errors.UniqueViolation` → `409 email_already_exists` → `User.model_validate`.
    Docstring: the audit entry Story 1.12 owes it; DW-40/DW-69's fourth Argon2id endpoint; that the
    `administrator` parameter is the authorization, not a value the body can supply.
- `apps/api/api/main.py` — include the new router beside `auth.router`, with a comment that
  `/admin/` is an authorization boundary the guard test reads off the path.
- `apps/api/tests/test_admin_authorization.py` — **new**, in `test_forced_change_gate.py`'s shape.
  Every served route whose path starts `/admin/` declares `require_administrator` at any depth;
  every route that declares it is under `/admin/`; a claimed Staff session is refused `403
  administrator_required` by the live route with **no row written**; and a negative control proving
  the walker actually fails a route that omits the dependency. Assert the route set is non-empty
  first — a guard over nothing passes forever.
- `apps/api/tests/test_create_user.py` — **new.** Every row of the I/O matrix, plus: that the created
  user can sign in immediately with the submitted password and is then refused by
  `require_claimed_user` on a gated route until `POST /auth/password` claims the account; that
  `temp_credential_expires_at` is 72 hours ahead within a tolerance, taken from the database clock;
  that a Staff caller spends no `hash_password` (monkeypatch it, as `test_login.py` monkeypatches the
  decoy verify) and writes no row; that a duplicate differing only by case or surrounding whitespace
  is the `409`; that the response body carries no `password_hash` key; and that `_INSERT_USER`'s
  `RETURNING` list is identical to `auth._SET_PASSWORD`'s and names exactly `User.model_fields`.
- `apps/api/tests/test_no_registration.py` — add `/admin/users` to the exact served-path set, rename
  the test, and extend the written justification: an authenticated Administrator provisioning
  somebody else is what FR-1 *requires*, not what it forbids; there is no unauthenticated path to it.
- `apps/api/tests/test_source_guards.py` — add `users.py` to the file list
  `test_the_scan_reaches_the_files_it_claims_to` names, so the new SQL is provably scanned.
- `apps/web/src/api/client.ts` — `export const INVALID_EMAIL` and `export const EMAIL_ALREADY_EXISTS`,
  each with the comment saying which field it marks. `administrator_required` gets **no** constant:
  nothing branches on it, the screen renders the server's sentence like any other failure.
- `apps/web/src/__tests__/error-code-parity.test.ts` — a row per new code in `PYTHON` (`users.py`)
  and `TYPESCRIPT`.
- `apps/web/src/screens/CreateUserScreen.tsx` + `.module.css` — **new.** Title "Create user", then
  the form: name (`autoComplete="off"`), email (`type="email"`, `autoComplete="off"`), role
  (a `<select>` built by iterating `ROLES` with a `Record<Role, string>` of the glossary labels
  "Staff" / "Administrator", defaulting to Staff), and the temporary password as
  `type="text"` with `autoComplete="off"` and `spellCheck={false}` — see Design Notes. A primary
  "Create user" button (the screen's one accent control), a secondary "Back", and the inline
  indicator ("Creating…" muted while in flight). Blank fields are refused locally with a specific
  sentence, as `AccountSettingsScreen` refuses one. `FormError` carries `fieldAtFault`:
  `invalid_email`/`email_already_exists` → email, `weak_password` → password, anything else → null.
  On `201` the fields clear and a result panel names the user, their role, the temporary password as
  typed, the expiry rendered from the response's `temp_credential_expires_at`, and one line saying
  the app sends no email and the credential must be passed on by hand. The stylesheet takes every
  value from `tokens.css` and declares exactly one `var(--color-accent)`.
- `apps/web/src/App.tsx` + `App.module.css` — widen `Section` and `Screen` with `'create-user'`;
  `currentScreen` returns it **only when `user.role === 'admin'`**, otherwise falling through to
  `'shell'` — the EXPERIENCE.md:95 redirect, expressed as a pure function so no effect is needed. A
  role-conditional navy-outline entry on the home panel opens it, with the comment that this is a
  convenience and the server refuses a Staff caller regardless. Render `CreateUserScreen` in the
  shell with its Back handler, beside the account branch.
- `apps/web/src/__tests__/create-user.test.tsx` — **new.** Every `apps/web` row of the I/O matrix;
  the request shape (POST `/api/admin/users`, `credentials: 'same-origin'`, exact snake_case body
  `{name, email, role, temporary_password}`); that the entry is absent for a Staff user and present
  for an Administrator; that a Staff user whose section state somehow says otherwise still gets the
  home panel; that the button is disabled in flight; that Back returns; and that no control anywhere
  on the screen offers to send the credential by email.
- `apps/web/src/__tests__/styling-wiring.test.ts` — the new screen joins the `.error`-colour cases,
  the alert-element `it.each`, and gets its own one-accent-per-screen describe.
- `README.md` — how an Administrator provisions a user in operator terms: where the entry is, that
  the credential is typed by the Administrator and handed over by hand because the app sends no
  mail, that it expires in 72 hours unclaimed, and that the new user must change it before reaching
  anything else.

**Acceptance Criteria:**

- Given an authenticated, claimed Administrator who submits a name, email, role and temporary
  password, when the request is handled, then the response is `201` with the created `User`, and a
  subsequent `POST /auth/login` with that email and password succeeds — with no migration, console
  command or database access in between.
- Given that newly created user immediately after signing in, when they request a route that serves
  real data, then they are refused `403 password_change_required` until `POST /auth/password` is
  used, and their `temp_credential_expires_at` is 72 hours after creation by the database clock.
- Given a claimed **Staff** session, when it posts the same body to the same route, then the
  response is `403 administrator_required`, no `users` row is written, no password is hashed, and
  the refusal comes from a dependency rather than from a check inside the handler.
- Given the served route table, when `apps/api/tests/test_admin_authorization.py` runs, then every
  route under `/admin/` declares `require_administrator`, every route declaring it is under
  `/admin/`, the checked set is non-empty, and the negative control proves the walker fails a route
  that omits it — with `test_forced_change_gate.py` passing unmodified and `/admin/users` absent
  from `ALLOWED_WITHOUT_THE_GATE`.
- Given two submissions of the same address differing only in case or surrounding whitespace, when
  the second is handled, then it is refused `409 email_already_exists` by the database's unique
  index rather than by a prior read, and exactly one row exists.
- Given a Staff user signed in to `apps/web`, when the shell renders, then no Create user entry
  appears anywhere on it; and given an Administrator, when the create succeeds, then the temporary
  password and its expiry are shown for transcription alongside the statement that the app sends no
  email, and no control on the screen offers to send it.
- Given `git grep` over the repository's own source and dependency manifests, when they are
  inspected, then no mail transport is imported or declared, and `test_no_registration.py` and
  `test_no_password_reset.py` both pass with the new route served.
- Given `make lint` and `make test`, when they are run over the finished change, then both exit 0
  with every pre-existing test in `apps/api`, `apps/web`, `shared/schema` and `infra` passing.

## Spec Change Log

## Review Triage Log

### 2026-09-18 — Review pass
- intent_gap: 0
- bad_spec: 0
- patch: 12: (high 0, medium 7, low 5)
- defer: 9: (high 0, medium 6, low 3)
- reject: 9: (high 0, medium 0, low 9)
- addressed_findings:
  - `[medium]` `[patch]` `name` was the one text column reaching psycopg unscreened — a control character raised out of `conn.execute` after a full Argon2id hash and answered `500`, the exact failure `_normalize_email`'s screen exists to prevent. Extracted `_has_control_character()` and applied it to both fields, so the two cannot drift on what a storable string is; parametrized over NUL, `\x07` and `\x7f`.
  - `[medium]` `[patch]` `_INSERT_USER` wrote the Python-lowercased address into a column carrying `CHECK (email = lower(email))`, which `str.lower()` and Postgres's `lower()` are not guaranteed to agree on. The statement now writes `lower(%s)`, making the constraint unfailable by construction rather than by two implementations agreeing, pinned at statement level.
  - `[medium]` `[patch]` "Single-use by construction" was stated in `users.py`, `README.md` and the screen and is false — the credential works for unlimited sign-ins inside the 72 hours until the account is claimed, as this story's own forced-change test demonstrates. All three reworded to what is true.
  - `[medium]` `[patch]` An over-long name, email or password was refused as the generic `422 validation_error` with no field marked and none focused — the outcome `invalid_email` was given its own code to avoid, reintroduced on the neighbouring fields. Added `maxLength` mirroring the server's bounds so the case is unreachable from the screen; `fieldFor` left alone, because `validation_error` genuinely names no field.
  - `[medium]` `[patch]` The role picker's reset after a success was unasserted: deleting `setRole('staff')` kept the whole suite green while the next person provisioned in the same sitting would silently inherit the previous role. The clears-form test now selects Administrator before submitting and reads the select back.
  - `[medium]` `[patch]` Nothing pinned `TEMP_CREDENTIAL_LIFETIME_HOURS` to 72 — both existing assertions compute their expectation from the constant they check, so a one-token edit to 168 left every test green while an AGENTS.md non-negotiable was no longer true. Added the direct assertion.
  - `[medium]` `[patch]` `currentScreen` fell back to the shell for a demoted Administrator but nothing cleared `section`, so the home-panel door became a no-op for the rest of the session and a restored role re-opened the create screen unbidden. Added a render-phase `lastRole` reconciler beside the existing `lastStatus` one.
  - `[low]` `[patch]` `asUser`'s malformed-`201` guard was never exercised — every success case stubbed a valid body, so replacing it with a cast kept the suite green while a partially-understood response would render a blank name and "Invalid Date" beside a credential about to be written down. Added the case in the sibling screen's shape.
  - `[low]` `[patch]` `_normalize_email` admitted interior whitespace, so `na me@rocell.lk` was stored and answered `201` although the check advertises itself as catching the real typos. Rejected, with three cases including an interior NBSP.
  - `[low]` `[patch]` The credential's deadline rendered with no time zone, on the one value an Administrator transcribes onto a note as a hard server-side deadline; the `null` branch was uncovered. Added `timeZoneName: 'short'` and a test that the two spellings differ, plus the null-branch case.
  - `[low]` `[patch]` The "offers no control that would send the credential" guard scanned four roles and only `textContent`/`aria-label`, so a `checkbox` named "Send this to them" — or any control named through `<label htmlFor>` — passed it. Widened to an exhaustive 14-role inventory with computed accessible names, a count check, and a scan of the screen's full text.
  - `[low]` `[patch]` A deactivated Administrator was untested at the admin boundary although AGENTS.md's "never let deactivating a user leave a session live" is the sibling of the demotion rule already covered and `lookup_session` reads `active` in the same breath as `role`. Added both cases, asserting `401` on the next request with nothing written.

### 2026-09-18 — Review pass (follow-up)
- intent_gap: 0
- bad_spec: 0
- patch: 9: (high 0, medium 2, low 7)
- defer: 0
- reject: 27: (high 0, medium 15, low 12)
- addressed_findings:
  - `[medium]` `[patch]` The role reconciler cleared the section on *every* role change, so a
    **promotion** — which arrives through the same revalidation as a demotion — took a Staff user
    standing on Account Settings back to the home panel and discarded a half-typed password change,
    for a change that granted them more access rather than less. Narrowed to clear only a section
    the new role cannot reach, through a `reachableBy` predicate now shared with `currentScreen` so
    the two cannot disagree about what a role reaches; new test, proved load-bearing.
  - `[medium]` `[patch]` `create-user.test.tsx`'s "bounds the %s field the way the server bounds it"
    compared one TypeScript literal against another — both sides of the comparison lived in
    `apps/web`, so the Python bound could be set to anything with the suite green and the screen
    would go on admitting values the server refuses with the field-less `422 validation_error` that
    `invalid_email` was given its own code to avoid. `error-code-parity.test.ts` — the file that
    already reads Python source — now pins all three bounds across the two languages.
  - `[low]` `[patch]` Nothing held the cheap-refusals-first ordering: moving `password_rule_violation`
    below `hash_password` leaves the response byte-identical, so every test passed while an
    unthrottled Argon2id endpoint (DW-40/DW-69) started paying 64 MiB for a blank field. Added the
    `hash_password` monkeypatch test; proved load-bearing by the swap.
  - `[low]` `[patch]` Nothing pinned which refusal wins when a body breaks both the address rule and
    a password rule — both are a 422 naming a rule, so swapping the two blocks was invisible, while
    the screen marks and focuses the field the *code* names. Added the two-problem case.
  - `[low]` `[patch]` `NO_STORE` was asserted only on the `201`; the `422` bodies carry the address
    somebody typed and the `409` says it is already a login here. Added the refusal cases.
  - `[low]` `[patch]` The `409` was built from the `UniqueViolation` *class*, and the comment's claim
    that no other unique constraint exists is not true — `users_pkey` is one, and Stories 1.9–1.11
    all touch this table. Narrowed to `EMAIL_UNIQUE_INDEX` by name, re-raising anything else rather
    than pointing an Administrator at an email field that is fine; pinned to the name Postgres
    actually reports.
  - `[low]` `[patch]` `test_a_missing_field_is_refused` looped over four fields, so the first
    regression hid the other three. Parametrized.
  - `[low]` `[patch]` `locked_until` and the `created_at`/`updated_at` defaults — the three columns
    `_INSERT_USER` argues about in a comment but never names — were unasserted on the row it writes.
    Pinned, so a writer that starts setting one by hand has to say so.
  - `[low]` `[patch]` The "immediately usable" matrix row says the sign-in returns the same `User`;
    the test compared ids only, so the flag, the deadline or the role could come back as anything.
    Compared field by field, excluding the two `_RECORD_LOGIN` exists to set.

### 2026-09-18 — Review pass (second follow-up)
- intent_gap: 0
- bad_spec: 0
- patch: 11: (high 0, medium 2, low 9)
- defer: 1: (high 0, medium 1, low 0)
- reject: 23: (high 0, medium 6, low 17)
- addressed_findings:
  - `[medium]` `[patch]` A submit that typed nothing destroyed the result panel holding the one copy
    of the credential. After a success the form is empty, so a stray Enter or a second click on
    Create user refused on the blank name — and `refuse` cleared `provisioned` unconditionally, so
    the value nothing in the product can show again was gone for an action that changed nothing.
    `refuse` now takes `retireResult`, false for the three blank-field guards and true everywhere
    else; a test submits twice and reads the credential back off the panel.
  - `[medium]` `[patch]` The `409`'s narrowing to `EMAIL_UNIQUE_INDEX` was never exercised through
    the endpoint — the only test naming the constant does a raw `INSERT` and asserts the index name,
    so answering `409` for *every* `UniqueViolation` kept the whole suite green. Added a test that
    creates a second unique index, clashes on it with a body whose address is fine, and asserts the
    violation propagates rather than being described to the Administrator as a duplicate address.
  - `[low]` `[patch]` The acceptance clause "`/admin/users` absent from `ALLOWED_WITHOUT_THE_GATE`"
    had nothing asserting it: the allowlist is a plain dict and no test looked at it for `/admin/`
    paths. Added `test_no_admin_route_is_exempt_from_the_gate`, stated over the prefix rather than
    the one route, so Stories 1.9–1.11 inherit it. A pure addition to that file — no entry was
    added, moved or relaxed.
  - `[low]` `[patch]` Only `name` of the request model's three bounds was exercised;
    `MAX_EMAIL_LENGTH` and `MAX_PASSWORD_FIELD_LENGTH` had no API test at all, although all three
    are mirrored onto the screen's inputs and pinned across languages. Parametrized both, asserting
    the `422` and that nothing is written — `MAX_PASSWORD_FIELD_LENGTH` most of all, because it is
    what keeps an unbounded body away from a 64 MiB Argon2id hash.
  - `[low]` `[patch]` `test_the_admin_route_table_is_not_empty` asserted exact equality with
    `["POST /admin/users"]` — a different and stricter claim than its name, which would fail for
    Story 1.9 with a message about an empty table. Split into the non-emptiness guard the comment
    argues for and a separately named test for the exact route set.
  - `[low]` `[patch]` The create-user branch passes its own `onOpenAccount`, and `AppBar` renders
    the Account control only when that prop is defined — but the shell test asserted only that the
    app bar and Sign out exist, so dropping the prop left the one surface an Administrator spends
    time on with no way to their own account and the suite green. Added a test that clicks Account
    from this screen and lands on it.
  - `[low]` `[patch]` `pythonInteger` and `typescriptInteger` tested `found === undefined`, but
    `RegExp.exec` answers `null`; they worked only through the `?.` beside it. Rewritten against
    `null`, with a note, so the dead check cannot be "simplified" into `found[1]`, which throws
    where the callers expect `null`.
  - `[low]` `[patch]` `README.md` offered "reissue the credential once Story 1.10 lands" as the
    recovery for a lost credential. Story 1.10 is editing a user's name, email or role; nothing in
    Epic 1 reissues one, and `make reseed-admin` covers only the seeded Administrator. Reworded to
    what is true, naming 1.10 and 1.11 for what they actually restore.
  - `[low]` `[patch]` Two comments in `App.tsx` said four of `EXPERIENCE.md`'s six nav surfaces do
    not exist. Its nav table lists Scan, Scan History, Account Settings, User List, Catalogue and
    Audit Log, of which only Account Settings exists — five. Create user is not one of the six; it
    is a door standing in for User List. Corrected, and the distinction written down.
  - `[low]` `[patch]` This spec's own Design Notes still ended "the credential is single-use by
    construction", the claim the previous pass reworded out of `users.py`, `README.md` and the
    screen as false. Corrected here too, so the frozen artifact does not contradict the three it
    governs.
  - `[low]` `[patch]` `REFUSED_BODY`'s comment claimed "the password is assembled at runtime rather
    than written down" of `"x" * 24`, which is written down. Reworded to the true reason it is safe
    — a repeated character, never read, in a body every caller in that file is refused before.

## Design Notes

**Why `/admin/users` and a new module rather than another route in `auth.py`.** Every verb this epic
puts on the user collection — create (1.8), list (1.9), edit (1.10), deactivate/delete (1.11) — is
Administrator-only, and there is no user-collection route that is not (`GET /auth/session` serves a
caller their own record). Putting them under one prefix lets the authorization boundary be read off
the path, which is what makes `test_admin_authorization.py` possible as a route-table property
rather than a per-route review habit — the same trick `test_forced_change_gate.py` plays, and the
reason that gate has held across five stories. `auth.py` is authentication; provisioning somebody
else is not.

**Why the role check is a dependency chained on `require_claimed_user`.** `_declares` walks the
dependency tree at any depth, so chaining satisfies the forced-change gate with no allowlist entry —
and the ordering is the one that matters: an Administrator still holding a temporary credential is
refused by the gate before the role check ever runs, so a note-borne credential cannot provision a
second account. Chaining on `current_user` instead would have opened exactly that path.

**Why the temporary password field is not masked.** It is not the Administrator's own secret. It is a
value they must transcribe verbatim onto a note or read aloud, and masking it makes a transcription
error invisible until the new user fails to sign in and comes back. Nothing here is kept from the
person at the screen: they are typing it. `autoComplete="off"` keeps a password manager from
offering to store somebody else's credential as the Administrator's own (DW-70's failure mode in
reverse). The credential is **not** single-use: inside its 72 hours it signs in as many times as it
is tried, and every time it lands on the forced-change screen and nothing else. What retires it is
claiming the account, or the deadline passing — and `users.py`, `README.md` and the screen all say
so in those words.

**Why the door is the home panel and not the app bar or the nav.** EXPERIENCE.md reaches this surface
from the User List's "+ Add User", behind a role-conditional nav — and the User List is Story 1.9
while the nav spans six surfaces of which five do not exist. The app bar was the right interim door
for Account Settings because a profile entry conventionally sits there; an admin surface does not,
and a third control crowds a 375px bar. The home panel is the shell's landing surface, it costs one
conditional, and when the nav lands the entry moves and `CreateUserScreen` does not change.

**Why `apiRequest` is called from the screen rather than through `SessionProvider`.** The context is
the *caller's own* session: its status, its cached user, and the three mutations that change it.
Creating another user changes none of those. Routing it through the context would mean every admin
mutation from 1.9 onward lands there too, and `client.ts:184` already says screens will call
`apiRequest` directly. It also keeps `SessionContextValue` — and every hand-built fixture of it in
the suite — unchanged.

```python
# apps/api/api/users.py — the shape of the write, not the code.
_INSERT_USER = """
INSERT INTO users (name, email, password_hash, role,
                   active, must_change_password, temp_credential_expires_at)
VALUES (%s, %s, %s, %s, true, true, now() + make_interval(hours => %s))
RETURNING <the same eleven columns as auth._SET_PASSWORD, character for character>
"""
# `true, true` is FR-11 and FR-2 stated at the one place that writes the row,
# not left to the column defaults: a default is a schema fact a later migration
# may change, and this is a product rule. A UniqueViolation on
# users_email_lower_key is the 409 -- the database decides, so two concurrent
# submissions of one address cannot both win.
```

## Verification

**Commands:**
- `make lint` — expected: exit 0 (ruff check, ruff format --check, oxlint --deny-warnings,
  tsc --noEmit).
- `make test` — expected: exit 0; the `apps/api` database tests run against the ephemeral cluster or
  skip with the same "no PostgreSQL available" reason (DW-18/DW-39).
- `uv run pytest apps/api/tests/test_create_user.py apps/api/tests/test_admin_authorization.py -q`
  — expected: exit 0.
- `uv run pytest apps/api/tests/test_forced_change_gate.py apps/api/tests/test_no_registration.py apps/api/tests/test_no_password_reset.py apps/api/tests/test_source_guards.py apps/api/tests/test_login.py apps/api/tests/test_password_change.py -q`
  — expected: exit 0, with only `test_no_registration.py` and `test_source_guards.py` modified.
- `uv run pytest infra/tests -q` — expected: exit 0, `infra/tests/test_migrate.py` unmodified.
- `npm --prefix apps/web run test` — expected: exit 0, including the two parity rows, the new screen
  file and the extended styling-wiring lists.
- `git status --porcelain infra/migrations` — expected: empty. This story ships no migration.
- `git grep -nE "smtplib|aiosmtplib|nodemailer|sendgrid|mailgun|postmark" -- apps shared infra scripts`
  — expected: matches in `apps/api/tests/test_no_password_reset.py` only.
- `git grep -ncE "TEMP_CREDENTIAL_LIFETIME_HOURS *= *72" -- shared infra apps` — expected: exactly
  one file, `shared/schema/shared_schema/user.py`.
- Prove each new guard load-bearing by removing what it guards: drop `require_administrator` from the
  route (the admin guard fails), chain it on `current_user` instead of `require_claimed_user` (the
  unclaimed-Administrator case fails), answer the Staff refusal with `not_signed_in()` (the 403 case
  fails), remove the `UniqueViolation` catch (the duplicate case fails), change one column in
  `_INSERT_USER`'s `RETURNING` list (the drift guard fails), and drop the `user.role === 'admin'`
  condition in `currentScreen` (the Staff-cannot-reach-it case fails).

**Manual checks (if no CLI):**
- Invoke the `ui-ux-pro-max` skill and run its pre-delivery checklist against the Create User screen
  before calling this story done (epic context: required for every UI story).
- `make migrate`, then `make dev`: sign in as the seeded Administrator, claim the account, open
  Create user from the home panel, submit a Staff user, read the credential off the result panel,
  sign out, sign in as that user and confirm the forced-change screen is all they can reach. Then
  sign back in as the Administrator and submit the same address again to see the `409`. Confirm a
  Staff session shows no Create user entry at all.



## Auto Run Result

Status: done

**Summary.** Story 1.8 was implemented and reviewed in commit `f12a101`, reviewed again in
`8051c5d`; this run is the second follow-up review pass its own `followup_review_recommended: true`
asked for. No intent gap and no spec defect were found — the implementation still matches the
`<intent-contract>` clause for clause, and the intent-alignment audit confirms it implements the
structural reading the intent states (a role check that is a property of the route table, one
statement of 72 hours, a `RETURNING` list that cannot drift). Eleven findings were patched: one
in-product data-loss path on the Create user screen, one untested refusal branch on the endpoint,
six verification gaps, and three factual corrections in prose that had gone stale. One finding was
deferred. Twenty-three were rejected.

**Files changed this pass.**
- `apps/web/src/screens/CreateUserScreen.tsx` — `refuse` gained `retireResult`; the three
  blank-field guards pass `false`, so a submit that types nothing no longer destroys the panel
  holding the credential.
- `apps/web/src/__tests__/create-user.test.tsx` — two tests: the panel survives a second submit on
  an empty form, and the app bar's Account control works from this screen.
- `apps/web/src/__tests__/error-code-parity.test.ts` — the two integer readers guard `null`, which
  is what `RegExp.exec` returns, rather than `undefined`.
- `apps/web/src/App.tsx` — two comments corrected: five of `EXPERIENCE.md`'s six nav surfaces do not
  exist, and Create user is not one of the six.
- `apps/api/tests/test_create_user.py` — a clash on a second unique index must propagate rather than
  be answered as a duplicate address; the `email` and `temporary_password` bounds are exercised.
- `apps/api/tests/test_forced_change_gate.py` — `test_no_admin_route_is_exempt_from_the_gate`, the
  acceptance clause about `ALLOWED_WITHOUT_THE_GATE` stated over the `/admin/` prefix. A pure
  addition: no entry added, moved or relaxed.
- `apps/api/tests/test_admin_authorization.py` — the route-table test split into a non-emptiness
  guard and a separately named exact-set test; `REFUSED_BODY`'s comment corrected.
- `README.md` — the lost-credential recovery no longer promises a reissue at Story 1.10.
- `_bmad-output/implementation-artifacts/spec-1-8-create-user-account.md` — the stale "single-use by
  construction" claim in Design Notes corrected; one deferred entry added; this pass's triage log.

No production code changed except `CreateUserScreen.tsx`. `apps/api/api/users.py` is untouched this
pass — every API finding was a missing test over behaviour that was already correct.

**Review findings breakdown.** 11 patched (0 high, 2 medium, 9 low); 1 deferred (medium — the login
lookup folds with Python while the column is folded by Postgres, so an address where the two
disagree can be provisioned and can never sign in; the lookup is in `auth.py`, which this story's
intent forbids changing); 23 rejected, of which 8 restated entries already on this spec's `deferred`
list or the orchestrator's ledger, 4 were artifacts the orchestrator owns, and the rest were
spec-sanctioned decisions, unreachable branches or noise.

**Follow-up review recommendation:** `true`. Score 15 — patched this pass: 0 high, 2 medium, 9 low
→ `3 × 2 + 1 × 9 = 15`, at or above 5. No high-severity finding was patched.

**Verification performed.**
- `make lint` — exit 0 (ruff check, ruff format --check, oxlint --deny-warnings, tsc --noEmit).
  `make format` was run once; it fixed one import order and reformatted one file.
- `make test` — exit 0: 668 passed in `apps/api`/`infra`/`shared` (was 663), 639 passed across 15
  files in `apps/web` (was 637). The API database tests ran against the ephemeral cluster, not
  skipped.
- Each new guard proved load-bearing by removing what it guards, then restoring it: answering `409`
  for every `UniqueViolation` fails the new clash test; dropping `max_length` from `email` or
  `temporary_password` fails the two bounds rows; an `("POST", "/admin/users")` entry in
  `ALLOWED_WITHOUT_THE_GATE` fails the new exemption guard; reverting `refuse(BLANK_NAME, 'name',
  false)` fails the panel-survives test; dropping `onOpenAccount` from the create-user branch fails
  the Account-control test.
- The spec's frontmatter was parsed as YAML after the append: one `deferred` key, ten items, the
  nine prior ones intact.
- `git status --porcelain infra/migrations` — empty; this story still ships no migration.

**Residual risks.** Unchanged from the previous passes and all on the `deferred` list, plus the one
added this pass. The credential is still unrecoverable once the screen is left — this pass closed
the accidental-submit path to losing it, not the navigation paths (DW-81), and a `201` whose
transport fails after the commit still reports as a refusal (DW-75's shape). No audit entry until
Story 1.12; no throttle on the fourth Argon2id-backed endpoint (DW-40/DW-69); a mistyped address
permanently consumes the unique index until Stories 1.10/1.11. The non-ASCII case-folding hardening
in `_INSERT_USER` remains pinned at statement level only, and the newly deferred finding is the
sharper consequence of the same collation question: on a full Unicode collation, an address where
Python's `lower()` and Postgres's `lower()` disagree is provisioned successfully and can never sign
in, with no error anywhere and nothing in the suite able to observe it.
