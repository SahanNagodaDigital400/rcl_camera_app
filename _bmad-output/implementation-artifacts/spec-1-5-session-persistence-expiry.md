---
title: 'Story 1.5 — Session Persistence & Expiry'
type: 'feature'
created: '2026-09-17'
baseline_revision: '1ff8bfccc057a6bbd6bbe7c99556df2b0b8f3675'
status: 'done'
review_loop_iteration: 0
followup_review_recommended: true # score 9 (0 high patched); see Auto Run Result
context:
  - '{project-root}/AGENTS.md'
  - '{project-root}/_bmad-output/planning-artifacts/architecture/architecture-rcl_camera_app-2026-08-30/ARCHITECTURE-SPINE.md'
  - '{project-root}/_bmad-output/planning-artifacts/ux-designs/ux-rcl_camera_app-2026-09-08/EXPERIENCE.md'
  - '{project-root}/_bmad-output/planning-artifacts/ux-designs/ux-rcl_camera_app-2026-09-08/DESIGN.md'
warnings: ['oversized']
deferred:
  - summary: >-
      The rule that renewal can never extend a session's 7-day ceiling is a
      property of the call sites, not of the table: nothing at the database
      level stops a future writer from updating `sessions.issued_at` or
      `sessions.expires_at`.
    evidence: |-
      The whole security argument for the two-column shape is that
      `_TOUCH_SESSION` writes `last_seen_at` and only `last_seen_at`, so the
      absolute bound read from `issued_at` is unreachable from the renewal
      path. That holds today because `api/sessions.py` is the one module
      allowed to touch the table and its only `UPDATE` is the touch — an
      invariant currently guarded by one Python test. A `BEFORE UPDATE`
      trigger, or a `CHECK` tying `expires_at` to `issued_at`, would make it
      true of the table itself. That is a migration and a decision about
      whether any story ever needs to move either column (Story 1.11's
      deactivation currently ends sessions by deleting rows, not by updating
      them), which is out of scope for a story whose acceptance clauses are
      about behaviour rather than schema hardening.
    location: >-
      infra/migrations/20260917T1400_track_session_activity.up.sql
    severity: low
  - summary: >-
      `visibilitychange` is the only revalidation trigger, and on iOS Safari a
      page restored from the back-forward cache can come back without one — the
      exact "tab backgrounded for hours" case, on the platform this PWA is
      built for.
    evidence: |-
      `SessionProvider`'s second effect listens for `visibilitychange` alone.
      A bfcache restore fires `pageshow` with `persisted: true`, and whether
      `visibilitychange` also fires is implementation-specific and has moved
      between Safari versions. If it does not, a phone left on the login-adjacent
      shell overnight comes back to a shell rendering over a dead session until
      the user's first action fails — a narrower version of DW-37 rather than a
      regression of it, since the action itself still drops to login.
      Adding a `pageshow` listener beside the existing one is small, but it is a
      behaviour change whose whole value is on a device this suite cannot drive:
      jsdom has no bfcache, so a vitest case would assert only that a listener
      was registered. It wants verification on a real iOS device, which is a
      different kind of task from the rest of this story.
    location: >-
      apps/web/src/auth/SessionProvider.tsx:182
    severity: low
  - summary: >-
      The revalidation on `visibilitychange` is itself an authenticated
      request, so foregrounding a tab slides the 12-hour idle window forward
      without the user having done anything in the app.
    evidence: |-
      `SessionProvider`'s second effect issues `GET /auth/session` whenever the
      tab becomes visible, and that request goes through `lookup_session` ->
      `_touch_session` like any other. On a phone, the OS fires
      `visibilitychange` every time the PWA is foregrounded — so picking the
      handset up and putting it down buys another 12 hours, with no
      interaction. The comment above the effect says "Nothing in this app may
      keep a session alive on its owner's behalf", and the matrix row it
      implements says a hidden tab makes no request at all; both hold
      literally, and the property they exist to protect is still reachable
      from the visible side. Closing it means a "revalidate at most every N
      minutes" rule, or reading the session without touching it, and both are
      behaviour the intent's matrix does not describe — the matrix requires
      the revalidation unconditionally. That makes it a decision about what
      counts as activity, not a defect in the code as specified.
    location: >-
      apps/web/src/auth/SessionProvider.tsx (the visibilitychange effect)
    severity: low
  - summary: >-
      `ARCHITECTURE-SPINE.md`'s `SESSION` ERD block does not carry
      `last_seen_at`, so the spine now describes a narrower table than the one
      the product has.
    evidence: |-
      The block lists `id`, `user_id`, `token_hash`, `issued_at` and
      `expires_at`. AD-3's rule is untouched by this story — it says the
      lookup is shared, not that it is read-only — but the ERD is a column
      list and is now incomplete, and `infra/README.md` points at that block
      by name as the description of the table. Amending a planning artifact
      from inside a story is a scope question this story has no authority to
      settle on its own; recording it here is the cheaper half.
    location: >-
      _bmad-output/planning-artifacts/architecture/architecture-rcl_camera_app-2026-08-30/ARCHITECTURE-SPINE.md:243
    severity: low
  - summary: >-
      The `apps/web` suite failed twice during this review pass with a
      `findByLabelText`/`findByTestId` timing out at ~1s, and did not
      reproduce in eleven subsequent runs including a cold-cache one.
    evidence: |-
      Both failures were in `session-expiry.test.tsx` and both were a
      `findBy*` exhausting testing-library's default 1000ms timeout rather
      than an assertion reporting a wrong value; the runs that failed were
      also the slowest overall (3.1s vs a steady 1.8s). Clearing
      `node_modules/.vite`, touching every source file and re-running did not
      reproduce it, so the cold-transform explanation is unconfirmed. Left
      alone it is a test that fails for one person, once, on the story's
      central assertion — worth either raising the timeout for the async
      screen-swap cases or finding the real cause before it is dismissed as
      noise.
    location: >-
      apps/web/src/__tests__/session-expiry.test.tsx
    severity: low
---

<intent-contract>

## Intent

**Problem:** Half of FR-3 is missing. `sessions` carries one deadline — `expires_at`, set to
`issued_at + 7 days` — and `lookup_session` checks it, so the **absolute** bound holds. The
**12-hour inactivity** bound does not exist anywhere: a session issued on Monday authenticates on
Sunday with no request in between, which is the exposure the idle window exists to close. On the
front end the mirror gap is DW-37: `SessionProvider` bootstraps once and never revalidates, so the
shell keeps rendering after the server has stopped honouring the cookie, and EXPERIENCE.md line 90's
"Session expired mid-flow → redirect to Login" has no implementation.

**Approach:** Give a session a second, independent bound. `sessions.last_seen_at` records the last
authenticated request; the one AD-3 lookup refuses a row idle longer than `SESSION_IDLE_TIMEOUT` and
slides that window forward as a side effect of authenticating, throttled so traffic does not become
one write per request. `expires_at` keeps its meaning untouched — the absolute ceiling, derived from
`issued_at`, that no amount of activity moves. On the front end, any `401` from any request drops the
app to the login screen with a factual notice, and returning to a backgrounded tab revalidates.

## Boundaries & Constraints

**Always:**
- Exactly ONE session-lookup function (AD-3). The idle bound, the slide and the absolute bound are
  all conditions inside `api.sessions`; no route grows its own check.
  `test_source_guards.py::test_only_one_module_reads_the_sessions_table` enforces the absence of a
  second reader.
- **The absolute bound is enforced from `issued_at`, never from a column the slide writes.** A
  sliding window that could push the 7-day ceiling is the one way this story can break a security
  requirement, and the only structural defence is that the two bounds read different columns and one
  of them is immutable.
- Parameterized SQL only; every interval is a bound parameter, never interpolated into the statement.
- Migrations are forward-only, reversible, and an applied one is **never edited** — including its
  comments (AGENTS.md Conventions).
- The session token stays in the HTTP-only / `Secure` / `SameSite=Strict` cookie and hashed at rest;
  nothing in this story adds a second place it can live.
- Every value in new `apps/web` CSS comes from `src/styles/tokens.css` (UX-DR1); the `no-raw-values`
  guard enforces it.
- Copy follows EXPERIENCE.md's tone — short, factual, no exclamation marks — and never tells the user
  *why* the session ended: expiry, revocation and deactivation are deliberately indistinguishable.
- Security paths get failure-case tests, not just the happy path (AGENTS.md).

**Block If:**
- Enforcing the idle window cannot be expressed without a second query against `sessions` outside
  `api/sessions.py` (AD-3 violation).
- The absolute 7-day bound cannot be kept independent of the slide — i.e. the only workable shape
  makes renewal able to extend it.

**Never:**
- A second stateful store for sessions — no Redis, no in-process cache (AD-3).
- Refresh tokens, a second cookie, or any token material in the response body or browser storage.
- **Session listing, or an Administrator revoking another user's sessions.** Epic 1 delivers
  immediate revocation through Story 1.11's deactivation and the existing `ON DELETE CASCADE`; no
  story asks for a session-management surface, and building one here invents scope.
- A background polling timer in `apps/web` that re-checks the session on an interval. A poll is
  itself a request, so it would keep an unattended tab's session alive forever and defeat the very
  window this story adds.
- Failed-attempt counters, progressive delay or lockout (Story 1.6); audit entries (Story 1.12); a
  "your session expires in N minutes" warning or countdown (named nowhere in EXPERIENCE.md).
- An unsaved-admin-form warning. EXPERIENCE.md line 90 requires one before dropping an in-progress
  admin form; no admin form exists until Stories 1.8–1.11, so there is nothing to warn about and a
  generic beforeunload guard would fire on every screen in the product.
- Editing `20260917T1300_create_sessions.up.sql`. Its comments forward-reference this story and are
  now stale; the correction goes in the new migration's comments, not by touching an applied one.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Active within the window | any authenticated route, `last_seen_at` under `SESSION_IDLE_TIMEOUT` old | the route runs; no re-authentication | No error expected |
| Idle past the window | `last_seen_at` older than `SESSION_IDLE_TIMEOUT`, `expires_at` still in the future | `401 unauthorized`, `NO_SESSION`, stale cookie cleared | The existing `not_signed_in()` |
| Activity slides the window | a request at hour 11, then another at hour 17 | both succeed — the second is 6h after the first, not 17h after the issue | No error expected |
| Sliding cannot outrun the ceiling | a session touched every hour since it was issued, now 7 days old | `401` — `issued_at + SESSION_ABSOLUTE_LIFETIME` has passed regardless of activity | Refused by the lookup's own condition on `issued_at` |
| Renewal is throttled | two authenticated requests inside `SESSION_TOUCH_INTERVAL` | `last_seen_at` is written once; the second request reads and does not write | No error expected |
| Renewal write fails | the touch raises `psycopg.Error` | the request still succeeds — the caller is authenticated; a warning is logged | Swallowed and logged, as the login sweep already is |
| A dead session cannot be revived | the row expires between the lookup's read and its touch | the touch matches no row; the next request is `401` | The touch re-asserts every liveness condition |
| Sweep clears idle-dead rows | a sign-in with idle-dead rows present | they are deleted alongside absolutely-expired ones, still bounded by `EXPIRED_SWEEP_LIMIT` | Failure swallowed and logged, unchanged |
| Cookie attributes | any response that sets the session cookie | `HttpOnly`, `Secure`, `SameSite=Strict`, `Path=/`, `Max-Age` = the absolute lifetime | — |
| Web, 401 on any request while signed in | any `apiRequest` fails with code `unauthorized` | the app drops to the login screen carrying a factual "your session has ended" notice | The originating caller still sees its own error |
| Web, 401 from the sign-in attempt itself | wrong credential at `POST /auth/login` | the login screen's own rejection renders; **no** session-ended notice | The notice is only for a session that existed |
| Web, tab returns to visible | `document.visibilityState` becomes `visible` while signed in | one `GET /auth/session`; `200` keeps the shell and refreshes the cached `User`, `401` drops to login | A network failure leaves the current state alone |
| Web, tab hidden | the tab is backgrounded for hours | no request is made at all — nothing keeps the session alive on the user's behalf | — |

</intent-contract>

## Code Map

**Read-only sources of truth (do not edit):**
- `_bmad-output/planning-artifacts/epics.md` **lines 231–243** — Story 1.5's acceptance clauses
  verbatim. Also 244–256 (1.6 owns throttling), 296–307 (1.10 edits users), 309–321 (**1.11 owns
  deactivation, where "his session ends immediately" lives**), 322–334 (1.12 owns audit).
- `_bmad-output/specs/spec-rcl_camera_app/functional-requirements.md` **FR-3** — "12h inactivity /
  7-day absolute expiry … never accessible to page script or client-side storage … stored hashed".
- `ARCHITECTURE-SPINE.md` **AD-3** (lines 58–62) — one shared lookup, `role`/`active` re-read every
  request, cookie-only transport. **AD-8** (line 92) — counters are one atomic `UPDATE … RETURNING`,
  never read-then-write; the renewal below is deliberately *not* a counter and the Design Notes say
  why that rule does not make it read-then-write.
- `EXPERIENCE.md` **line 90** (Session expired mid-flow → redirect to Login, warn before dropping an
  unsaved admin form), **line 95** (role change takes effect on the next request), lines 50–57 (voice).
- `AGENTS.md` — "Never let deactivating a user leave a session live"; "Never store session tokens
  outside HTTP-only, Secure, SameSite=Strict cookies"; migrations forward-only and never edited.
- `_bmad-output/implementation-artifacts/deferred-work.md` — **DW-37** (`apps/web` never revalidates;
  its `reason` names this story as the owner of the trigger), **DW-42** (an unclaimed holder keeps a
  live session past the credential's death — the idle window shortens the exposure but does not close
  it; it is Story 1.12/1.10 territory and stays open), **DW-17** (`updated_at` has no trigger — not
  reached here, `sessions` has no such column), **DW-21** (no migration checksum — why a comment-only
  edit to an applied migration is still forbidden), **DW-33** (`/health` and pool errors).

**Files that already exist and constrain the shape:**
- `apps/api/api/sessions.py` — **the only file allowed to read `sessions`** (`test_source_guards.py`'s
  `SESSIONS_HOME`). Carries `SESSION_ABSOLUTE_LIFETIME = timedelta(days=7)`, `SESSION_COOKIE_NAME`,
  `COOKIE_PATH`, `COOKIE_SAMESITE`, `TOKEN_BYTES`, `EXPIRED_SWEEP_LIMIT = 100`, `_INSERT_SESSION`,
  `_SELECT_SESSION` (the ten `User` columns, `expires_at > now()`, `u.active`), `_DELETE_SESSION`,
  `_DELETE_USER_SESSIONS`, `_DELETE_EXPIRED` (keyed on the primary key, `FOR UPDATE SKIP LOCKED`,
  `LIMIT`), `generate_token`, `hash_token`, `issue_session`, `lookup_session`, `delete_session`,
  `delete_sessions_for_user`, `delete_expired_sessions`, `set_session_cookie`, `clear_session_cookie`,
  `cleared_cookie_headers`. **Four comments in this file forward-reference Story 1.5** (module
  docstring line 25, line 56, the `_DELETE_EXPIRED` `ctid` note at line 121, `delete_sessions_for_user`
  at line 210) — the `ctid` note predicted exactly the `UPDATE sessions` this story adds, and that
  prediction landing is why the primary-key form stays.
- `apps/api/api/dependencies.py` — `current_user` wraps `lookup_session` and is the only caller on the
  request path; `require_claimed_user` wraps that. Neither queries `sessions`. `not_signed_in()`
  carries `AUTH_CHALLENGE`, `NO_STORE` and `cleared_cookie_headers()` — the 401 this story reuses
  unchanged.
- `apps/api/api/auth.py` — `login` (issues the session, then calls `delete_expired_sessions` *outside*
  the transaction and swallows `psycopg.Error` with a `logger.warning` — **the precedent the renewal's
  error handling copies**), `read_session`, `logout`, `set_password`. Line 328 and line 384 point at
  Story 1.5 for bulk revocation; line 601 for "session management".
- `apps/api/api/db.py` — pooled connections are `autocommit=True` with `dict_row`, so a bare
  `conn.execute` commits on its own and `row` is a mutable `dict`.
- `shared_schema/user.py` — `User` is `extra="forbid"`, so `_SELECT_SESSION` cannot simply grow
  columns: anything extra must be removed from the row before `User.model_validate`.
- `infra/migrations/20260917T1300_create_sessions.up.sql` — the shipped `sessions` shape: `id`,
  `user_id` (`ON DELETE CASCADE`), `token_hash` (unique index), `issued_at timestamptz NOT NULL
  DEFAULT now()`, `expires_at timestamptz NOT NULL`, plus `sessions_user_id_idx` and
  `sessions_expires_at_idx`. **Applied — read-only.**
- `infra/rocell_infra/migrate.py` — `VERSION_PATTERN = ^\d{8}T\d{4}_[a-z0-9]+(_[a-z0-9]+)*$`; every
  `.up.sql` needs a matching `.down.sql`; the plan is filename-sorted.
- `infra/tests/test_runner_unit.py:32–43` — `test_the_repository_migrations_are_a_valid_plan` asserts
  the shipped version list **exactly**; a new migration must be added to it.
- `apps/api/tests/conftest.py` — `conn`, `client` (https `base_url` so the `Secure` cookie survives),
  `make_user(role=, active=, must_change_password=, temp_credential_expires_at=, name=)` → `Account`;
  `migrated_url` applies every migration except `SEED_MIGRATION_VERSION` and asserts the filter
  removed exactly one.
- `apps/api/tests/test_session_lookup.py` — the AD-3 suite: `_sign_in` helper, the expired-row case,
  the deactivated-owner case, the role-change case, and direct `lookup_session` calls. The idle cases
  belong beside these or in the new file; do not duplicate the helper in three places.
- `apps/api/tests/test_login.py` — `_sessions(conn, user_id)`, `_cookie_attributes(response)`,
  `test_the_session_cookie_carries_every_required_flag` (asserts `max-age` equals
  `SESSION_ABSOLUTE_LIFETIME`), `test_the_session_lifetime_is_the_week_the_addendum_specifies`
  (**deliberately written with literals, independent of the constant — it must keep passing
  unchanged**), and the two sweep tests.
- `apps/web/src/api/client.ts` — `apiRequest`, `ApiRequestError` (carries `code`), `UNAUTHORIZED`,
  `API_PREFIX`, `REQUEST_TIMEOUT_MS`. Every request in the app goes through this one function.
- `apps/web/src/auth/SessionProvider.tsx` — `status`/`user`/`signIn`/`changePassword`/`signOut`, the
  `live` teardown guard in the bootstrap effect, `asUser` narrowing, and `changePassword`'s existing
  `unauthorized` branch which already sets `signed-out` (it must not double-report the notice).
- `apps/web/src/App.tsx` — `currentScreen(status, user)`, the four-way `Screen` union and the
  focus-on-swap effect keyed on the screen.
- `apps/web/src/screens/LoginScreen.tsx` + `.module.css` — `useId`, `noValidate`, the inserted
  `role="alert"` paragraph, `.panel`/`.lede`/`.error` classes. The notice goes beside `.lede` and is
  `role="status"`, not `role="alert"` — it is information, not a failure of what the user just did.
- `apps/web/src/__tests__/auth-gating.test.tsx` — `STAFF`/`UNCLAIMED` fixtures, the `unauthorized`
  reply, and `stubFetch(replies)` keyed by path returning `{ calls }`. New web tests reuse this shape.
- `apps/web/src/__tests__/no-client-token-storage.test.ts`, `no-raw-values.test.ts`,
  `styling-wiring.test.ts` — the three guards new front-end code must keep green.
- `README.md` lines 74–98 (the operator account of the cookie) and `infra/README.md` line 48's
  migration table and §"The 72-hour expiry".

## Tasks & Acceptance

**Execution:**

- `infra/migrations/20260917T1400_track_session_activity.up.sql` / `.down.sql` — add
  `last_seen_at timestamptz NOT NULL DEFAULT now()` to `sessions`; `down` drops the column. Comment
  what the column is for and, critically, what it is **not**: `expires_at` remains the absolute
  ceiling and this column is the idle bound, so neither can be mistaken for the other by the next
  reader. State that the two bounds are deliberately two columns. Deliberately **no index** on it —
  see Design Notes. `IF NOT EXISTS` / `IF EXISTS`, matching the existing pair's replay behaviour.
- `infra/tests/test_runner_unit.py` — add the new version to the expected plan in
  `test_the_repository_migrations_are_a_valid_plan`.
- `apps/api/api/sessions.py` — the whole of the server-side change:
  - `SESSION_IDLE_TIMEOUT = timedelta(hours=12)` and `SESSION_TOUCH_INTERVAL = timedelta(minutes=1)`,
    each documented with why the value is what it is.
  - `_SELECT_SESSION` gains `AND s.last_seen_at > now() - %s` alongside the existing
    `s.expires_at > now()`, plus `AND s.issued_at + %s > now()` — the absolute bound read from the
    immutable column, not from `expires_at` — and selects `s.id AS session_id` and
    `(s.last_seen_at <= now() - %s) AS needs_touch`.
  - `lookup_session` pops `session_id` and `needs_touch` off the row before `User.model_validate`
    (`User` is `extra="forbid"`), and when `needs_touch` runs `_TOUCH_SESSION`:
    `UPDATE sessions SET last_seen_at = now() WHERE id = %s AND expires_at > now() AND
    last_seen_at > now() - %s` — every liveness condition re-asserted so a row that died in between
    is not revived. `psycopg.Error` is caught, logged at warning level, and the lookup still returns
    the `User`; the module needs a `logger` for it, named like `api.auth`'s.
  - `_DELETE_EXPIRED` also takes idle-dead rows: `WHERE expires_at <= now() OR last_seen_at <= now() - %s`,
    with `delete_expired_sessions` passing the idle window. The `LIMIT`, the `FOR UPDATE SKIP LOCKED`
    and the primary-key keying are unchanged.
  - Update the module docstring and the four stale Story-1.5 comments: the idle window is now here;
    `SESSION_ABSOLUTE_LIFETIME` is one of two bounds, not the only one; the `ctid` note's predicted
    `UPDATE sessions` has arrived, which is why the primary-key form stays; and session listing /
    admin-initiated revocation are **not** this story's — revocation on deactivation is Story 1.11's
    through the cascade, and listing is in no story.
- `apps/api/api/auth.py` — retarget the three Story-1.5 forward references (lines ~328, ~384, ~601) to
  what actually owns them now. No behaviour change: the cookie's `max_age` stays the absolute
  lifetime, because the browser must keep presenting a token for as long as the session could still
  be alive.
- `apps/api/tests/test_session_lifetime.py` — new; the matrix's server rows. Idle just inside and just
  outside the window; activity sliding it; the absolute ceiling refusing a 7-day-old session that has
  been touched throughout (the test that proves the slide cannot outrun it); the throttle writing
  once inside `SESSION_TOUCH_INTERVAL` and again after it; `_TOUCH_SESSION` matching no row for an
  expired session; the sweep taking idle-dead rows while staying bounded; and a direct assertion of
  `set_session_cookie`'s full attribute set, so a third cookie-setting path cannot drift from the two
  that exist. Drive idle by writing `last_seen_at`/`issued_at` backwards in SQL, never by sleeping.
- `apps/api/tests/test_session_lookup.py` — extend: `lookup_session` refuses an idle row and returns
  the `User` unchanged in shape (still exactly the ten `User` keys — the guard that the two extra
  selected columns never reach the model).
- `apps/web/src/api/client.ts` — `onUnauthorized(handler)`: register one module-level observer that
  `apiRequest` invokes when — and only when — it is about to throw an `ApiRequestError` whose code is
  `UNAUTHORIZED`. Document that it exists so **every** caller is covered, including the Epic 2 screens
  that will call `apiRequest` without going through `SessionProvider`, and that it observes rather
  than handles: the originating caller still gets its own rejection.
- `apps/web/src/auth/SessionProvider.tsx` — register the observer in an effect (deregistering on
  teardown, as the bootstrap's `live` flag does); on a 401 while `status` is `signed-in`, clear the
  user, set `signed-out` and raise a `sessionEnded` flag exposed on the context. Add a
  `visibilitychange` listener that re-fetches `/auth/session` when the tab becomes visible and the
  status is `signed-in`, updating the cached `User` on success and letting the observer above handle a
  401; a network failure changes nothing. **No interval, ever** — say why in a comment.
  `changePassword`'s existing `unauthorized` branch keeps working and must not raise the notice twice.
- `apps/web/src/screens/LoginScreen.tsx` + `.module.css` — when `sessionEnded` is set, render one
  factual `role="status"` line above the form: the session ended, sign in again. Never says which of
  expiry, revocation or deactivation it was. A `.notice` class in `--color-muted-text`, distinct from
  `.error`'s `--color-destructive` — nothing the user did failed.
- `apps/web/src/__tests__/session-expiry.test.tsx` — new; the matrix's web rows, on `stubFetch`: a 401
  from a non-login request while signed in swaps the shell for the login screen and shows the notice;
  a 401 from the sign-in attempt itself shows the credential rejection and **no** notice; becoming
  visible issues exactly one `/auth/session` call and keeps the shell on `200`, drops to login on
  `401`; staying hidden issues none; and advancing timers with no interaction issues none — the guard
  that no poll was added.
- `apps/web/src/__tests__/styling-wiring.test.ts` — assert the notice element's class resolves and is
  the muted colour, not the destructive one, beside the existing per-screen colour block.
- `infra/README.md` — the migration table gains the new row; §"Sessions" (or the nearest existing
  operator section) states the two bounds in operator terms: 12 hours idle, 7 days absolute, the
  second unaffected by activity.
- `README.md` — one short paragraph beside the cookie account: a session survives a shift, dies after
  12 hours without a request, and dies at 7 days however busy its owner was; there is no warning
  before either, and signing in again is the whole of the recovery.

**Acceptance Criteria:**
- Given a signed-in user whose last authenticated request was under 12 hours ago, when they make
  another request, then it succeeds with no re-authentication and no new sign-in.
- Given a session issued 7 days ago that has been used continuously throughout, when its holder makes
  a request, then it is refused — the absolute bound is read from `issued_at`, so no amount of
  activity moves it.
- Given the `sessions` table after a burst of authenticated requests from one session inside
  `SESSION_TOUCH_INTERVAL`, when the row is inspected, then `last_seen_at` was written at most once —
  authenticating is a read that occasionally writes, not a write per request.
- Given any authenticated route and a session that is idle-dead, revoked, absolutely expired, or whose
  owner has been deactivated, when it is called, then all four answer the same `401 unauthorized` with
  the stale cookie cleared, and none of them reveals which.
- Given `apps/web` rendering the shell, when any request to the API answers `401`, then the login
  screen replaces the shell carrying a factual notice that the session ended, and the notice never
  appears for a rejected sign-in attempt.
- Given a backgrounded tab whose session has expired, when the user returns to it, then one
  `GET /auth/session` is made and the login screen replaces the shell; and given the tab is left
  hidden, then no request is made at all and nothing keeps the session alive on the user's behalf.
- Given the whole front-end source, when it is searched, then no interval timer revalidates the
  session, no file touches `localStorage`, `sessionStorage`, `document.cookie` or `indexedDB`, and
  every new CSS value resolves to a design token.
- Given every response that sets the session cookie, when its `Set-Cookie` header is read, then it
  carries `HttpOnly`, `Secure`, `SameSite=Strict`, `Path=/` and a `Max-Age` equal to the absolute
  lifetime; and given the row behind it, then the stored value is the token's SHA-256 and never the
  token.
- Given the new code, when it is searched, then no SQL is assembled by concatenation or
  interpolation, no second module reads the `sessions` table, and no applied migration has been
  edited.
- Given `make lint` and `make test` on a clean checkout, when both are run, then both exit 0.

## Spec Change Log

## Review Triage Log

### 2026-09-18 — Review pass (follow-up 2)
- intent_gap: 0
- bad_spec: 0
- patch: 7: (high 0, medium 1, low 6)
- defer: 3: (high 0, medium 0, low 3)
- reject: 17: (high 0, medium 0, low 17)
- addressed_findings:
  - `[medium]` `[patch]` A sign-out refused with `401` left "Not signed in." latched into the shell. `apiRequest` notifies the observer before it throws, so the app is already on the login screen when `handleSignOut`'s `catch` runs — but `Gate` is one component with conditional returns, not a tree that unmounts, so the message survived the swap and reappeared on the next sign-in, telling a signed-in user they were not. `App.tsx` now leaves the `401` case to the observer that owns it and words every other failure as before. Proven load-bearing: restoring the old catch fails the new test in `session-expiry.test.tsx` and only that test.
  - `[low]` `[patch]` The story gave the request path its first *write* to `sessions`, and `test_only_one_module_reads_the_sessions_table` is matched on `FROM sessions` — it catches a SELECT and a DELETE and cannot see an UPDATE or an INSERT. The security argument for the two-column shape is a claim about which statements exist, so it is only as good as the guard over them. Added `test_only_one_module_writes_the_sessions_table`. Proven non-vacuous: the pattern matches `api/sessions.py`, the one file it exempts.
  - `[low]` `[patch]` `test_a_failing_renewal_is_logged` counted `caplog.records` whole. The fixture's handler sits on the root logger, so a warning from psycopg, the pool or any future `rocell.api.*` logger raised during the same call would have failed the test for something that is not the renewal. Now filtered to the module's own logger before counting.
  - `[low]` `[patch]` `test_activity_slides_the_window_forward` carried a comment saying the second stage "carries forward what the slide just wrote, moved back with the clock" — which contradicts the comment fifteen lines above it, and the code: `_age` writes `last_seen_at` absolutely. Reworded to say what the second stage actually stages and which assertion is the load-bearing one.
  - `[low]` `[patch]` The deploy-ordering requirement — migrate before rolling the code forward, roll back before stepping the schema down — existed only in the two migration files' comments. It is the one genuinely dangerous operational fact in this change and it was absent from `infra/README.md`, which is what an operator reads. Added to the migrations section.
  - `[low]` `[patch]` `infra/tests/test_migrate.py` asserts `idle_for < timedelta(hours=12)` to prove the migration did not backfill from `issued_at`; `infra` cannot import `apps/api`, so nothing tied that literal to `SESSION_IDLE_TIMEOUT`. Shorten the constant and the assertion keeps passing while no longer testing the property it names. Named the coupling in a comment.
  - `[low]` `[patch]` The spec's own manual check — run `ui-ux-pro-max`'s pre-delivery checklist against the login screen's new notice — was unrecorded, on a story marked done with new UI carrying a colour-semantics and a live-region decision. Run this pass: the notice takes all four of its values from `tokens.css`, `role="status"` is the correct non-assertive choice against the screen's separate `role="alert"`, colour is not the only carrier of the meaning, and `--color-muted-text` on `--color-background` is 4.65:1 — AA for body text, and already pinned by a comment in the token file. No finding.

### 2026-09-18 — Review pass (follow-up)
- intent_gap: 0
- bad_spec: 0
- patch: 8: (high 0, medium 1, low 7)
- defer: 1: (high 0, medium 0, low 1)
- reject: 24: (high 0, medium 0, low 24)
- addressed_findings:
  - `[medium]` `[patch]` The acceptance clause names **four** refusals that must be indistinguishable — idle-dead, revoked, absolutely expired, deactivated owner — and `test_an_idle_refusal_says_nothing_a_deactivation_does_not` compared two while its own comment said four. Replaced with `test_the_four_refusals_are_indistinguishable`, which stages all four and asserts one status and one body across them. They share `not_signed_in()` today, so nothing structural was stopping a later branch from wording its own refusal into an oracle.
  - `[low]` `[patch]` `test_activity_slides_the_window_forward` did not exercise the scenario it names. `_age` writes `last_seen_at` absolutely, so the second `200` came from the test's own UPDATE rather than from the first request's touch, and `issued_at` was never aged — the session was seconds old throughout, so the "17 hours after the issue" half was never staged. Now ages `issued_at` alongside and asserts the slide landed between the two requests. Proven load-bearing: with `_touch_session` skipped the old body passed and the new one fails.
  - `[low]` `[patch]` `test_the_two_bounds_are_the_figures_fr_3_names` pins 12 hours and 7 days to literals precisely so a shortened bound cannot hide, then checked only `SESSION_TOUCH_INTERVAL < SESSION_IDLE_TIMEOUT` — which an eleven-hour interval satisfies, making "at most one write a minute" false in three files with the suite green. Pinned to `timedelta(minutes=1)`.
  - `[low]` `[patch]` `signOut`'s `setSessionEnded(false)` was pinned by nothing: one sign-out test never raises the notice, and the other signs in first, which clears it. The state that makes the line necessary is a revalidation 401 landing during a forced change that then succeeds — the app returns to signed-in with the flag latched. Added that case, which needed `stubFetch` to be able to hold one reply behind a promise. Proven load-bearing: removing the clear fails the new test and only the new test.
  - `[low]` `[patch]` `onUnauthorized`'s single slot means a second registrant silently disables the first, and the only symptom would be the shell rendering over a dead session again — the exact regression the observer exists to prevent. The replacement contract is now stated in its docstring, directing a later consumer to compose into the provider's handler.
  - `[low]` `[patch]` The revalidation's `.catch` was documented as "anything else is the network"; it also swallows a body `asUser` rejects, which is a broken contract with our own API. The treatment stays the same and the comment now says so and why.
  - `[low]` `[patch]` `signOut`'s comment said the login screen it lands on "says nothing about" the sign-out, which is true only on the way through — a logout refused with `401` never reaches those lines, and the notice stands. That case is the suite's own first test, so the code asserted one thing and the tests another. Documented.
  - `[low]` `[patch]` `20260917T1400_track_session_activity.down.sql` states the ordering the revert needs; the `.up.sql` was silent on the mirror requirement, which is the direction that happens on every release. Without it, a revision shipped ahead of its migration fails every authenticated request and every sign-in on an undefined column.

### 2026-09-18 — Review pass
- intent_gap: 0
- bad_spec: 0
- patch: 12: (high 0, medium 3, low 9)
- defer: 1: (high 0, medium 0, low 1)
- reject: 21: (high 0, medium 0, low 21)
- addressed_findings:
  - `[medium]` `[patch]` `apps/web/src/api/client.ts` notified the unauthorized observer only when the 401 body parsed as the shared envelope, so a proxy or gateway answering 401 with HTML or an empty body left the shell rendering over a dead session — the exact case the observer exists for. The notification now fires on `response.status === 401` before either throw, with a test driving a 401 carrying `<html>504…</html>`.
  - `[medium]` `[patch]` Nothing applied `20260917T1400_track_session_activity` to a `sessions` table holding rows: every test created an empty database and applied the whole plan at once, so the one path the migration exists for was never executed. `infra/tests/test_migrate.py` now applies the plan sliced to `20260917T1300_create_sessions`, inserts a session issued three days earlier, applies the rest, and asserts the `ALTER` landed and the pre-existing row is live and inside the idle window. Proven load-bearing both ways — dropping `DEFAULT now()` fails it with `NotNullViolation`, and a `last_seen_at = issued_at` backfill fails it too.
  - `[medium]` `[patch]` `SessionProvider`'s claim that a session dying mid-forced-change raises the notice once was pinned by no test, and the user it concerns is the one with no sign-out and no dismissal on screen. `session-expiry.test.tsx` now covers a 401 from `POST /auth/password` (login, with the notice, exactly once) and a 409 `password_change_not_required` (login, no notice).
  - `[low]` `[patch]` Every 401 in the new web suite arrived from an auth route, so nothing held the claim that an arbitrary `apiRequest` caller inherits the behaviour. Added a case driving a 401 from a non-auth path.
  - `[low]` `[patch]` The three tests asserting an *absence* of requests flushed a single microtask, so a request issued one tick later would have gone unseen. Replaced with a `settle()` helper — microtasks only, so the story's own `setInterval|setTimeout` grep keeps reading true.
  - `[low]` `[patch]` `test_a_failing_renewal_is_logged` asserted only the log level, which passes for exactly the silent record its comment says it exists to prevent. It now asserts one record, the cause, and that `exc_info` is present.
  - `[low]` `[patch]` The observer was invoked unguarded, so a throwing handler would have replaced the `ApiRequestError` the caller branches on. Wrapped, with two tests — the mutation check showed the suite was green without them.
  - `[low]` `[patch]` The down migration's comment called the revert benign; it is not while the current code is deployed, since three statements reference the dropped column. It now states the ordering requirement: roll the application back and confirm it is serving before stepping the schema down.
  - `[low]` `[patch]` The justification for leaving `last_seen_at` unindexed rested on the sweep being "bounded by `LIMIT`". `LIMIT` bounds rows returned, not rows read, and the widened `OR` cannot use `sessions_expires_at_idx`. Corrected in `sessions.py`, the migration header and `infra/README.md`; the decision stands and is now stated as the bet on row count that it is.
  - `[low]` `[patch]` The migration header asserted that `expires_at` is written as `issued_at + 7 days`; `_INSERT_SESSION` writes `now() + %s`. Reworded to what the statement does.
  - `[low]` `[patch]` `README.md` promised the notice on "the next request anywhere in the app", which a cold page load cannot deliver — the cookie is HTTP-only, so a fresh tab cannot tell an expired session from one that never existed. Narrowed to an open tab, with the reason.
  - `[low]` `[patch]` Stray double blank line in `SessionProvider.tsx`.

## Design Notes

**Why two columns rather than one sliding deadline.** The tempting shape is to slide `expires_at`
forward to `LEAST(now() + 12h, issued_at + 7d)` and keep one column. It is smaller — no migration at
all — and it is wrong for this codebase for one reason: it makes the 7-day security bound a property
of *arithmetic performed on every request* rather than of an immutable column. Get the `LEAST` wrong
once, or lose the cap in a later refactor, and sessions become immortal with every test still green,
because every other assertion about the lifetime derives from the same expression. With two columns
the absolute bound is `s.issued_at + SESSION_ABSOLUTE_LIFETIME > now()` — `issued_at` is written once
at INSERT and nothing in the product ever updates it — and the renewal path physically cannot reach
it. It also keeps `test_the_session_lifetime_is_the_week_the_addendum_specifies` meaningful: that test
was written with literals precisely so a shortened lifetime could not hide, and the one-column shape
would have forced it to be rewritten in terms of the new semantics.

**Why `last_seen_at` is not indexed.** It is written on most authenticated requests. An index on it
would be updated on every one of those writes and would block HOT updates, and the only reader is the
login sweep, which is bounded by `LIMIT` against a table holding roughly one row per live session for
an internal tool with tens of staff. If that ever stops being true, the measurement comes first —
the same standing rule CLAUDE.md applies to swapping out `pgvector`.

**Why the touch is a separate statement, and why that is not AD-8's read-then-write.** AD-8 forbids
read-then-write for *counters*, where the new value depends on the old one and a lost update is a
correctness bug — that is what its "one `UPDATE … RETURNING`" is for. `last_seen_at = now()` depends
on nothing it read: two concurrent touches write near-identical values, and the worst case of losing
one entirely is that the window is extended a minute later instead. Folding it into the lookup's
SELECT would mean writing on *every* request (an `UPDATE … RETURNING` cannot conditionally skip the
write and still return the user), which is the cost the throttle exists to avoid. The liveness
conditions are repeated in the `WHERE` so the separation cannot resurrect a session that died in
between.

**Why a failed touch does not fail the request.** The caller authenticated; the lookup succeeded. A
tidy-up write that cannot land must not turn a valid request into a 500. It fails in the safe
direction — the window simply does not extend, and the session dies 12 hours after its last
successful touch — and it is logged, because a touch that keeps failing is a product that signs
everyone out at noon. `login`'s sweep already established exactly this handling.

**Why the front end observes 401 centrally rather than in each screen.** DW-37's gap is not that one
screen forgot to handle expiry; it is that nothing in the app ever learns the server stopped
honouring the cookie. Putting the observer in `api/client.ts` means the first Epic 2 screen that
calls `apiRequest` directly inherits the behaviour instead of having to remember it — the same
argument `require_claimed_user` makes on the server, one layer up.

```sql
-- apps/api/api/sessions.py — the shape of the two bounds, not the code.
 WHERE s.token_hash = %s
   AND s.expires_at > now()                       -- the row's own deadline
   AND s.issued_at + %s > now()                   -- absolute: immutable column, unmovable
   AND s.last_seen_at > now() - %s                -- idle: what activity slides
   AND u.active
```

## Verification

**Commands:**
- `make lint` — expected: exit 0 (ruff check, ruff format --check, oxlint --deny-warnings, tsc --noEmit).
- `make test` — expected: exit 0; the `apps/api` database tests run against the ephemeral cluster or
  skip with the same "no PostgreSQL available" reason (DW-18/DW-39).
- `uv run pytest apps/api/tests/test_session_lifetime.py apps/api/tests/test_session_lookup.py -q` —
  expected: exit 0.
- `uv run pytest infra/tests -q` — expected: exit 0, including the extended migration plan list and a
  full `up`/`down` round trip over the new pair.
- `npm --prefix apps/web run test` — expected: exit 0, including the new session-expiry cases.
- `git grep -nE "setInterval|setTimeout" apps/web/src` — expected: matches only the request timeout in
  `api/client.ts`; nothing that re-checks the session on a schedule.
- `git status --porcelain infra/migrations/20260917T1300_create_sessions.up.sql` — expected: empty.
  The applied migration is untouched.
- Prove each new guard load-bearing by removing what it guards: drop the `last_seen_at` condition from
  `_SELECT_SESSION` (the idle case fails), replace the `issued_at` condition with one on `expires_at`
  (the 7-day-with-activity case fails), remove the `needs_touch` throttle (the write-once case fails),
  and unregister the web observer (the 401-drops-to-login case renders the shell).

**Manual checks (if no CLI):**
- Invoke the `ui-ux-pro-max` skill and run its pre-delivery checklist against the login screen's new
  notice before calling this story done (epic context: required for every UI story).
- `make migrate`, then `make dev`: sign in, then `UPDATE sessions SET last_seen_at = now() -
  interval '13 hours'`. The next action drops to the login screen with the notice; signing in again
  works. Background the tab, expire the row, return to it — the swap happens without a click.


## Auto Run Result

Status: done

**Implemented change.** A session is now bounded twice. `sessions.last_seen_at` records the last
authenticated request; the one AD-3 lookup refuses a row idle longer than `SESSION_IDLE_TIMEOUT`
(12 hours) and slides that window forward as a side effect of authenticating, throttled by
`SESSION_TOUCH_INTERVAL` (1 minute) so traffic does not become one write per request. The absolute
7-day bound is read from `issued_at` — a column nothing in the product writes — so the renewal path
physically cannot extend it. On the front end, `api/client.ts` notifies a single observer on any
`401`, `SessionProvider` turns that into a drop to the login screen carrying a factual notice, and a
tab returning to visible revalidates once. No interval anywhere.

**Files changed**

| File | What |
|---|---|
| `infra/migrations/20260917T1400_track_session_activity.{up,down}.sql` | Adds `last_seen_at timestamptz NOT NULL DEFAULT now()`; no index, with the reasoning and both deploy-ordering requirements stated |
| `infra/tests/test_migrate.py` | The new version in the expected plan, an apply against a `sessions` table already holding rows, and the idle-bound literal tied by comment to `SESSION_IDLE_TIMEOUT` |
| `infra/tests/test_runner_unit.py` | The new version in the exact plan list |
| `apps/api/api/sessions.py` | The two constants, the four lookup conditions, `needs_touch`, `_TOUCH_SESSION`, the widened sweep, a module logger, and the stale Story-1.5 comments retargeted |
| `apps/api/api/auth.py` | The three Story-1.5 forward references retargeted; no behaviour change |
| `apps/api/tests/test_session_lifetime.py` | New — the idle window, the ceiling, the slide, the throttle, the failing renewal, the sweep, the cookie attributes |
| `apps/api/tests/test_session_lookup.py` | The idle refusal, and that the two extra selected columns never reach `User` |
| `apps/api/tests/test_source_guards.py` | `test_only_one_module_writes_the_sessions_table` — the write half of AD-3, which the `FROM sessions` guard cannot see |
| `apps/web/src/api/client.ts` | `onUnauthorized` / `notifyUnauthorized`, fired on `response.status === 401` before either throw |
| `apps/web/src/auth/SessionProvider.tsx` | The observer effect, the `visibilitychange` effect, `sessionEnded` on the context |
| `apps/web/src/App.tsx` | A sign-out refused with `401` is left to the observer rather than worded twice |
| `apps/web/src/screens/LoginScreen.{tsx,module.css}` | The `role="status"` notice and its muted-token class |
| `apps/web/src/__tests__/session-expiry.test.tsx` | New — the web rows of the matrix, plus the refused-sign-out case |
| `apps/web/src/__tests__/{styling-wiring,login-screen,forced-password-change}.test*` | The notice's class and role, and the context's new field |
| `README.md`, `infra/README.md` | The two bounds in operator terms, the migration table row, and the migrate-before-deploy ordering |

**Review findings breakdown (this pass).** 7 patches applied (1 medium, 6 low), 3 items deferred
(all low), 17 rejected. No `intent_gap` and no `bad_spec`: the diff implements the contract, and the
intent-alignment layer's divergences were readings selected and argued rather than requirements
missed. One patch changed behaviour — the refused-sign-out message no longer follows the user back
into the shell — and the rest were guard strength, a comment that contradicted its own code, and an
operator doc. Details per finding are in the Review Triage Log above.

Rejected and worth recording, because each was argued confidently and each is wrong here: broadening
`_touch_session`'s `except psycopg.Error` to bare `Exception` (the connection is already acquired, so
a pool timeout cannot arrive inside it, and the docstring's three cases are all `psycopg.Error`);
`ALTER TABLE ... ADD COLUMN IF NOT EXISTS` masking a pre-existing column of the wrong type (no other
migration creates one, and the guard suggested is the one already in the file); a `SAVEPOINT` around
the touch (`api/db.py` opens the pool `autocommit=True`, so there is no outer transaction to abort);
and the `sprint-status.yaml` / spec status disagreement, which is the orchestrator's bookkeeping and
not this story's to reconcile.

**Follow-up review recommended: true.** Patched this pass: 0 high, 1 medium, 6 low →
`3 × 1 + 1 × 6 = 9`, which is at or above 5. No high-severity finding was patched.

**Verification performed**

- `make lint` — exit 0 (ruff check, ruff format --check, oxlint --deny-warnings, tsc --noEmit).
  The first shape of the `App.tsx` fix was an effect that reset the message on a screen change;
  oxlint's `react(set-state-in-effect)` refused it, and the event-driven form that replaced it is
  both smaller and closer to where the decision belongs.
- `make test` — exit 0: 428 passed (`apps/api` + `infra`, against a live PostgreSQL — no skips),
  479 passed (`apps/web` vitest, 13 files).
- `git grep -nE "setInterval|setTimeout" apps/web/src` — two hits, both expected: the request timeout
  in `api/client.ts` and the prose in the test file explaining why there is no second one.
- `git status --porcelain infra/migrations/20260917T1300_create_sessions.up.sql` — empty. The applied
  migration is untouched.
- `ui-ux-pro-max` pre-delivery checklist against the login screen's notice (the spec's manual check,
  unrecorded until this pass): all four declared values come from `tokens.css`; `role="status"` is
  the correct non-assertive counterpart to the screen's `role="alert"`; the meaning is carried by the
  text rather than by colour; and `--color-muted-text` on `--color-background` measures 4.65:1,
  which is AA for body text and already pinned by a comment in the token file. Dark mode is not a
  finding here — the product declares no `prefers-color-scheme` block at all. No issues.
- Load-bearing proofs by mutation, both run and both confirmed:
  - Restoring `App.tsx`'s old `catch` fails the new `carries no refused-sign-out message back into
    the shell` case, and only that case, across three runs.
  - The new write guard's pattern matches `api/sessions.py` — the one file it exempts — so it is not
    a guard over an empty set.

**Residual risks**

- The idle window is never exercised against a real clock; every case writes timestamps backwards in
  SQL. That is deliberate and stated in the suite's docstring, but it means a defect that only shows
  across a genuine 12-hour elapse would not be caught here.
- `_SELECT_SESSION` and `_TOUCH_SESSION` are two statements on an autocommit connection, so each
  takes its own transaction timestamp. The touch re-asserts every liveness condition, so a row that
  died in between is not revived; nothing tests behaviour exactly at that boundary because the two
  statements run microseconds apart and the window cannot be staged.
- The `apps/web` suite failed twice during this pass on a `findBy*` timing out at ~1s and then
  passed eleven consecutive runs, including one with the Vite cache cleared and every source file
  touched. The cold-transform explanation is plausible and unproven; deferred above rather than
  dismissed.
- `visibilitychange` is the only revalidation trigger, and that revalidation is itself a request that
  renews the idle window — both deferred above, the first needing a real iOS device and the second a
  decision about what counts as activity.
- The two-column security argument is now guarded at the Python level in both directions (no second
  reader, no second writer) but still not by the table itself — the standing deferred item at the top
  of this spec.
