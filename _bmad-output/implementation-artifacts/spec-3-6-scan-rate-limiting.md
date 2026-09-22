---
title: 'Story 3.6 — Scan Rate Limiting'
type: 'feature'
created: '2026-09-22'
baseline_revision: '546ad4eeda338e4fc61daacecc526932b90315fd'
status: 'done'
review_loop_iteration: 0
followup_review_recommended: true
context: []
warnings: ['oversized']
deferred:
  - summary: >-
      `api/throttle.py`'s "Not here" docstring paragraph still says scan rate
      limiting (FR-23) and the anomaly baseline (FR-22) are "Epic 2's," which
      was already wrong before this story and is now doubly stale since FR-23
      is this story's own Epic 3 module.
    evidence: |-
      Confirmed by reading `apps/api/api/throttle.py`'s module docstring
      directly; this diff never touches that file, so the stale reference
      predates this story and is unrelated to the change it describes.
    location: apps/api/api/throttle.py
    severity: low
  - summary: >-
      This migration's `.down.sql` restates `20260922T1900_create_scan.down.sql`'s
      own "Deploy the code first, then step this back" wording, which reads
      ambiguously about which direction "the code" refers to.
    evidence: |-
      Verified by direct comparison of the two files: the phrasing is
      identical apart from the table name, so this story's file inherited an
      existing ambiguity rather than introducing a new one.
    location: infra/migrations/20260922T2000_create_scan_rate_limit.down.sql
    severity: low
  - summary: >-
      A user hard-deleted between `require_claimed_user` resolving and
      `check_and_record`'s `INSERT` landing would surface an unhandled foreign-key
      violation as a raw 500.
    evidence: |-
      `scan_rate_limit.user_id` is `REFERENCES users (id) ON DELETE CASCADE`,
      and `check_and_record` runs no `try`/`except` around the insert. This is
      the same general TOCTOU race Story 3.5's own spec already documented as
      a residual risk for `scan.user_id`'s identical shape — latent in every
      route that reads `user.id` after `require_claimed_user` resolves, not
      specific to this story, and no source document asks for it to be closed
      here.
    location: apps/api/api/scan_throttle.py
    severity: low
---

<intent-contract>

## Intent

**Problem:** `POST /scans` has no per-user throttle. A compromised or misused account can post scan submissions at whatever rate a script can send them, each one running a full crop/quality/embedding search against the catalogue — FR-23 and epics.md 3.6 exist because nothing today stops that, and AD-8 already reserves the pattern (a Postgres counter, mutated atomically) that FR-4's login lockout used for the same class of problem.

**Approach:** A new `scan_rate_limit` table, one row per user, mutated by a single `INSERT ... ON CONFLICT DO UPDATE ... RETURNING` that increments a fixed-window counter and reports the new count in one round trip (AD-8) — never a read followed by a write of a value read a moment earlier. A new `apps/api/api/scan_throttle.py` module owns every write to it, mirroring `api/throttle.py`'s shape for `login_attempts`. `submit_scan` calls it immediately after `require_claimed_user` resolves and before any image work, refusing with `429 scan_rate_limited` before the crop, the quality gate or the serialized inference slot are ever touched (ARCHITECTURE-SPINE.md AD-16, line 140: "Fixed order on every scan request: session validation → AD-8's rate-limit check → only then, acquire ... the serialization slot for inference"). The rate and the window are read once at import from two environment variables, `shared_vision.quality`'s own pattern for a PRD OQ-13 threshold — the same bucket FR-9's blur bound is in — so a value can change without a code edit, and a test can lower either one directly via `monkeypatch.setattr` with no process restart.

## Boundaries & Constraints

**Always:**
- One row per `user_id` (a real FK, `ON DELETE CASCADE`, `scan.user_id`'s own precedent) — never keyed on anything else. Unlike `login_attempts` (keyed on the submitted address to protect an unauthenticated identical-rejection invariant), this check runs only after `require_claimed_user` has already resolved a real account, so there is no oracle to protect and no reason to key on anything but the real user.
- AD-8's one atomic statement: `INSERT ... ON CONFLICT (user_id) DO UPDATE ... RETURNING submission_count`. A row older than the window resets to 1 in that same statement; a row inside it increments. Never a `SELECT` followed by a decision followed by an `UPDATE`.
- Checked and incremented on every `POST /scans`, right after `response.headers.update(NO_STORE)` and before `_read_upload` — so a throttled or about-to-be-throttled caller never pays for image decode, crop, quality or the inference lock. A refusal here writes no `scan` row, exactly as every other pre-match refusal in this handler already does.
- `SCAN_RATE_LIMIT`/`SCAN_RATE_LIMIT_WINDOW` are read once at import from `TILEMATCH_SCAN_RATE_LIMIT`/`TILEMATCH_SCAN_RATE_LIMIT_WINDOW_SECONDS`, falling back to a documented, uncalibrated default on a missing or unparsable value (an int for the count; a non-negative number of seconds for the window) — `shared_vision/quality.py::_read_threshold`'s exact shape, including its non-finite/parse-failure fallback and warning log.
- `scan_rate_limit` gets `GRANT SELECT, INSERT, UPDATE, DELETE` to `rocell_app`, `scan`'s own precedent (nothing here ever deletes a row, but `test_audit_immutability.py::test_no_table_is_left_ungranted_by_a_later_migration` requires full DML on every table but `audit_log`).
- A new `tests/test_source_guards.py` guard, `test_only_one_module_writes_the_scan_rate_limit_table`, in `test_only_one_module_writes_the_login_attempts_table`'s exact shape, plus `SCAN_THROTTLE_HOME` added to `test_the_scan_reaches_the_files_it_claims_to`'s tuple.
- `SCAN_RATE_LIMITED = "scan_rate_limited"` is a module-level constant in `api/scan.py` (not local to a function, unlike `SCAN_ENTRY_NOT_FOUND`) because `error-code-parity.test.ts`'s "every code the API can emit" scan requires a TypeScript twin for every module-level `NAME = "..."` in a scanned router — add it to `client.ts`, the `PYTHON`/`TYPESCRIPT` maps and the import list in `error-code-parity.test.ts`.
- New migration under `infra/migrations/`, `IF NOT EXISTS` throughout, its own explicit `GRANT`, `.up.sql`/`.down.sql` pair, added to `infra/tests/test_runner_unit.py`'s exact plan list and exercised in `infra/tests/test_migrate.py` (a version constant, an up/down round trip — a brand-new table, so no existing-row upgrade case to prove).

**Block If:** None identified — the mechanism, the table shape, and the message wording (EXPERIENCE.md line 89: a plain "temporarily paused" sentence, no countdown) are all fully specified; nothing here needs an external account, domain or credential.

**Never:**
- Never key the counter on anything but `user_id` (session validation has already resolved a real account by the time this check runs — no identical-rejection invariant to protect, unlike `login_attempts`).
- Never add a `Retry-After` header. Neither FR-23 nor epics.md 3.6 ask for one, and EXPERIENCE.md's "no countdown" is honoured by the response carrying no timing information at all — not by a machine-facing header the client is told not to read, which is `login`'s own answer to a different requirement (FR-4/RFC 9110) this story does not carry.
- Never touch `login_attempts`, `api/throttle.py`, or FR-22's anomaly baseline (Story 3.7) — three separate AD-8 counters, three separate tables, `api/throttle.py`'s own "Not here" precedent for why one is never generalised into another before a second caller exists.
- Never let the rate/window numbers reach `apps/web` or render as a count or a countdown — EXPERIENCE.md's plain-message requirement, `ACCOUNT_LOCKED`'s own precedent for a 429 the client shows verbatim and never augments.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Under the limit | Nth submission, N ≤ `SCAN_RATE_LIMIT`, same window | Proceeds to crop/quality/matching as normal | No error |
| Limit crossed | submission count > `SCAN_RATE_LIMIT` within the window | `429 scan_rate_limited`, plain message, no row written, no crop/quality/inference work done | `429` |
| Window elapsed | a row exists but `window_started_at` is older than `SCAN_RATE_LIMIT_WINDOW` | Counter resets to 1 in the same statement; submission proceeds | No error |
| Concurrent burst from one user | several requests arrive together, same user | Row lock serializes them; the count each sees reflects every prior write, never a lost update | Some 200s, some 429s, deterministic given the final count |
| A throttled caller keeps retrying | repeated submissions while already over the limit | Each still increments and is still refused, until the window resets | `429` every time |
| Env var unset or unparsable | `TILEMATCH_SCAN_RATE_LIMIT`/`_WINDOW_SECONDS` missing or not a number | Falls back to the documented default; a warning is logged for a present-but-bad value | No error (fails open to the default, not closed) |

</intent-contract>

## Code Map

**Read-only sources of truth:**
- `_bmad-output/planning-artifacts/epics.md` lines 508-520 — Story 3.6's acceptance clauses verbatim.
- `_bmad-output/specs/spec-rcl_camera_app/functional-requirements.md` FR-23 (line 65) and SPEC.md line 91 (OQ-13's four thresholds, scan-rate limit grouped with FR-9's blur bound).
- `ARCHITECTURE-SPINE.md` AD-8 (lines 88-92) and AD-16 (line 140 — the fixed session-validation → rate-limit → inference-slot order).
- `_bmad-output/implementation-artifacts/epic-3-context.md` — "Stories 3.6 and 3.7 gate submissions ahead of 3.4's matching, independently of each other and of quality guidance."
- `EXPERIENCE.md` line 89 (scan rate-limited: plain message, no countdown).

**Files that already exist and constrain the shape:**
- `apps/api/api/throttle.py` — the AD-8 pattern this module copies: module docstring shape, `logger = logging.getLogger("rocell.api.*")`, one atomic `INSERT ... ON CONFLICT DO UPDATE ... RETURNING`, a dedicated home file enforced by a source guard.
- `shared/vision/shared_vision/quality.py` — the env-var-configurable-threshold pattern this story's two constants copy exactly: `_read_threshold`'s parse-failure and non-finite fallbacks, the module-level read-once-at-import, the "documented placeholder, not a measured one" framing.
- `apps/api/api/scan.py` — `submit_scan` (the insertion point, right after `response.headers.update(NO_STORE)`), `_refusal` (the one constructor for a refusal here), `INVALID_CROP_RECT`/`SCAN_QUALITY_TOO_LOW` (the sibling module-level codes this story's `SCAN_RATE_LIMITED` sits beside).
- `apps/api/api/main.py` — `STATUS_CODES[429] = "rate_limited"` is the routing-level fallback only; this story raises `ApiError` directly with its own code, `ACCOUNT_LOCKED`'s own precedent.
- `apps/api/tests/test_source_guards.py` — `THROTTLE_HOME`, `_LOGIN_ATTEMPTS`, `test_only_one_module_writes_the_login_attempts_table` — the exact shape the new guard copies, plus `test_the_scan_reaches_the_files_it_claims_to`'s tuple.
- `apps/api/tests/test_login_throttling.py` — the `monkeypatch.setattr(throttle, "CONSTANT", value)` technique this story's tests reuse to drive `SCAN_RATE_LIMIT`/`SCAN_RATE_LIMIT_WINDOW` low without an env-var round trip; `test_a_stale_run_resets`'s direct-SQL backdating technique for proving a window reset with no real sleep.
- `apps/web/src/api/client.ts` / `apps/web/src/__tests__/error-code-parity.test.ts` — `INVALID_CROP_RECT`'s exact shape for a new exported code, the `PYTHON`/`TYPESCRIPT` maps, the "compares every code the API can emit" scan.
- `apps/web/src/screens/CropScreen.tsx` — `handleConfirm`'s `catch` already renders any `ApiRequestError` it does not special-case through the generic `error` state (`setError(failure.message)`) — this already surfaces the new refusal verbatim; no new branch needed.
- `infra/migrations/20260918T1000_add_login_throttling.up.sql`/`.down.sql`, `20260922T1900_create_scan.{up,down}.sql` — the migration-comment house style and the full-DML-grant precedent this story's migration copies.
- `infra/rocell_infra/migrate.py`, `infra/tests/test_runner_unit.py:33-44`, `infra/tests/test_migrate.py` — the plan list and the version-constant/round-trip test shape.
- `apps/api/tests/test_scan_submission.py` — `sign_in`, `submit_scan`, `jpeg_bytes`, `a_tile_photograph` — this story's new test file restates the ones it needs locally, this suite's own established convention (3.5's Auto Run Result Design Notes).

## Tasks & Acceptance

**Execution:**
- `infra/migrations/20260922T2000_create_scan_rate_limit.{up,down}.sql` — the `scan_rate_limit` table (`user_id uuid PRIMARY KEY REFERENCES users (id) ON DELETE CASCADE`, `submission_count integer NOT NULL DEFAULT 0 CHECK (submission_count >= 0)`, `window_started_at timestamptz NOT NULL DEFAULT now()`), its full grant.
- `apps/api/api/scan_throttle.py` (new) — `SCAN_RATE_LIMIT_ENV`, `DEFAULT_SCAN_RATE_LIMIT`, `SCAN_RATE_LIMIT_WINDOW_ENV`, `DEFAULT_SCAN_RATE_LIMIT_WINDOW`, `SCAN_RATE_LIMIT`, `SCAN_RATE_LIMIT_WINDOW` (read once, `quality.py`'s exact fallback shape); `check_and_record(conn, user_id) -> bool` — the one atomic statement, returns whether this submission is over the limit.
- `apps/api/api/scan.py` — import `scan_throttle`; at the top of `submit_scan`, call `scan_throttle.check_and_record` and raise `_refusal(SCAN_RATE_LIMITED, SCAN_RATE_LIMITED_MESSAGE, status.HTTP_429_TOO_MANY_REQUESTS)` when it reports over-limit, before `_read_upload`.
- `apps/api/tests/test_source_guards.py` — `SCAN_THROTTLE_HOME`, `_SCAN_RATE_LIMIT` fragment, `test_only_one_module_writes_the_scan_rate_limit_table`, and the `test_the_scan_reaches_the_files_it_claims_to` tuple update.
- `apps/api/tests/test_scan_rate_limiting.py` (new) — a low monkeypatched limit throttles the Nth submission; a window reset (backdated `window_started_at`) lets a throttled user through again; a concurrent burst never loses an update (two threads, assert the final count matches attempts made); a throttled submission persists no `scan` row; the env-var fallback (unit-level, `quality.py`'s reload technique) for a missing/unparsable value.
- `apps/web/src/api/client.ts` + `apps/web/src/__tests__/error-code-parity.test.ts` — `SCAN_RATE_LIMITED` export and parity rows.
- `infra/tests/test_runner_unit.py` + `test_migrate.py` — the ninth migration in the ledger.

**Acceptance Criteria:**
- Given I am signed in and have submitted scans at or above the configured rate within the configured window, when I confirm a crop and submit another scan, then Crop shows a plain message that submissions are temporarily paused, with no countdown, and nothing is added to my scan history.
- Given the window has elapsed since my last counted submission, when I submit again, then Crop proceeds normally to Results, exactly as an ordinary submission does.
- Given the rate and the window are each named, configurable values, when a test lowers either one, then the throttle fires observably at the lowered bound with no code change.
- Given two different users are each submitting at a normal pace, when one of them is throttled, then the other user's own submissions are unaffected — the limit is per user, never shared.

## Spec Change Log

## Review Triage Log

### 2026-09-23 — Review pass
- intent_gap: 0
- bad_spec: 0
- patch: 4: (high 0, medium 2, low 2)
- defer: 3: (high 0, medium 0, low 3)
- reject: 9: (high 0, medium 0, low 9)
- addressed_findings:
  - `[low]` `[patch]` `SCAN_RATE_LIMITED_MESSAGE` in `apps/api/api/scan.py` didn't match the "temporarily paused" wording its own comment (and EXPERIENCE.md line 89) claimed to follow. Reworded to "Scan submissions are temporarily paused. Try again shortly."
  - `[medium]` `[patch]` `scan_throttle._read_rate_limit()` had no lower-bound check, unlike its sibling `_read_window()` — `TILEMATCH_SCAN_RATE_LIMIT=0` or a negative value would silently refuse every user's very first submission. Added a `< 1` rejection with a logged warning, `_read_window`'s own shape, plus a parametrized test.
  - `[medium]` `[patch]` `scan_throttle._read_window()` accepted an absurdly large but finite non-negative value (e.g. `1e20`), which `timedelta(seconds=...)` in `check_and_record` cannot represent — an unguarded operator typo would turn every `POST /scans` into an unhandled 500. Added an overflow guard with a logged fallback, plus a test case.
  - `[low]` `[patch]` No test proved a submission refused for an earlier reason (crop rect, quality) still counts toward the rate limit, even though the code already does this correctly. Added `test_a_submission_refused_for_a_later_reason_still_counts`.

Deferred (pre-existing, not caused by this change — see frontmatter `deferred`): `api/throttle.py`'s stale "Not here" cross-reference naming Epic 2 for FR-22/FR-23; the "Deploy the code first..." wording in this migration's `.down.sql`, inherited verbatim from `20260922T1900_create_scan.down.sql`'s own template; the general TOCTOU race between `require_claimed_user` resolving and a since-deleted user's row being written to, latent in every route that reads `user.id` (same class Story 3.5 already documented as a residual risk).

Rejected (verified false, matching an established codebase precedent this story correctly followed, or explicitly out of scope by FR-20's own stated scope): the claim that a throttled caller "never pays for image work" was flagged as overstated since FastAPI/Starlette already parses the multipart upload before the handler runs, but the comment's actual claim (in context) is about the CPU-heavy decode/crop/quality/embedding work, which is accurate; no audit-log entry is written for a rate-limit trip, but FR-20 explicitly scopes the audit log to login/account/Catalogue events and never mentions scans — Story 3.5's separate scan-history mechanism is where a scan's own record lives; the down migration's bare `REVOKE` could raise if invoked twice or against a database where `up` never ran, but the migration runner only ever applies a tracked `down` once per applied version and this guard shape is identical to every other `down.sql` in the repository; the concurrency test was flagged for asserting only the final aggregate count rather than the exact set of returned values, but a lost update under `AD-8`'s single atomic statement would necessarily lower the final total below the expected sum, which the existing assertion already catches; the SQL's positional-parameter/f-string-duplication style was flagged, but it is `api/throttle.py`'s own established shape restated exactly, not a new pattern; the provisional defaults not being recorded back into `SPEC.md`'s OQ-13 entry was flagged, but no prior story (including 3.3's own blur threshold) does this either; the digit-free message assertion being the only guard against a future copy edit reintroducing a number was flagged, but this is how every piece of microcopy in this codebase is protected — tests are the guardrail, not a unique gap here; `submission_count` overflowing a 32-bit integer after roughly two billion requests in one window was flagged, but this is the same unguarded-integer shape `login_attempts.failure_count` already carries and is not reachable in practice; a claim that a later refusal (invalid crop rect, quality) could roll back the throttle increment inside the same transaction was flagged and verified false — `apps/api/api/db.py` configures pooled connections as `autocommit=True` with no explicit transaction wrapping `submit_scan`, so each `conn.execute` commits independently.

## Design Notes

**Why a fixed window, not a sliding one or a token bucket.** `login_attempts` already established the fixed-window-with-reset shape for an AD-8 counter in this codebase (`ATTEMPT_WINDOW`, reset when `last_failure_at` is stale) and epics.md 3.6 asks only for "the configured rate within the configured window" — nothing asks for a smoother sliding window or a leaky bucket, and inventing one here would be a second counter shape for the same architectural decision with no requirement behind the extra complexity.

**Why `user_id` and not `email_key`.** `login_attempts` is keyed on the submitted address because `POST /auth/login` must answer an unknown address and a real one identically (no account-existence oracle). `POST /scans` sits behind `require_claimed_user`: by the time this check runs, the caller is already a resolved, authenticated account, so there is no equivalent invariant to protect, and keying on the real `user_id` — a true foreign key — is the simpler, correct choice, `scan.user_id`'s own precedent.

**Why env-var configurability rather than a plain module constant.** FR-4's login thresholds (5th/10th attempt) are numbers the requirement states directly, so `throttle.py`'s constants are plain Python. FR-23's rate and window are explicitly named as an open question in SPEC.md (OQ-13), grouped with FR-9's blur/framing bound as one of "the four numeric thresholds ... calibrated during Foundation build and the Phase 2 pilot" (ARCHITECTURE-SPINE.md line 280) — the same bucket, so it gets the same mechanism `shared_vision.quality` already ships: an environment variable read once at import, with a documented, honestly-uncalibrated default, so operations can retune it without a code change ahead of the pilot.

## Verification

**Commands:**
- `uv run --project apps/api pytest apps/api/tests/test_scan_rate_limiting.py apps/api/tests/test_scan_submission.py apps/api/tests/test_source_guards.py apps/api/tests/test_audit_immutability.py apps/api/tests/test_no_registration.py` -- expected: pass.
- `npm --prefix apps/web test -- --run scan error-code-parity` -- expected: pass.
- `make migrate` -- expected: applies the new migration cleanly against a fresh database.
- `make lint` -- expected: clean (ruff + oxlint + tsc --noEmit).
- `make test` -- expected: full suite green.

## Auto Run Result

**Summary of implemented change:** Added a per-user scan rate limit (FR-23, Story 3.6). A new `scan_rate_limit` table (one row per user, `user_id` a real FK `ON DELETE CASCADE`) is mutated by a single atomic `INSERT ... ON CONFLICT DO UPDATE ... RETURNING` (AD-8) in a new `apps/api/api/scan_throttle.py` module — the only module allowed to write it, enforced by a new source guard. `submit_scan` calls it immediately after `require_claimed_user` resolves and before any image work (crop, quality, the serialized inference slot), refusing over-limit submissions with `429 scan_rate_limited` and a plain, non-numeric "temporarily paused" message, writing no `scan` row. The rate and the window are each a documented, uncalibrated placeholder (PRD OQ-13), read once at import from `TILEMATCH_SCAN_RATE_LIMIT`/`TILEMATCH_SCAN_RATE_LIMIT_WINDOW_SECONDS`, `shared_vision.quality`'s own env-var-override pattern, with fallback validation hardened during review to also reject a non-positive rate and a window too large for `timedelta` to represent.

**Files changed:**
- `infra/migrations/20260922T2000_create_scan_rate_limit.{up,down}.sql` (new) — the `scan_rate_limit` table, its full grant, matching `scan`'s own precedent.
- `apps/api/api/scan_throttle.py` (new) — the env-var-configurable rate/window constants and `check_and_record`, AD-8's one atomic statement.
- `apps/api/api/scan.py` — `SCAN_RATE_LIMITED`/`SCAN_RATE_LIMITED_MESSAGE`, and the check wired into `submit_scan` ahead of every other gate.
- `apps/api/tests/test_scan_rate_limiting.py` (new) — throttling at a lowered bound, persistence (no `scan` row when throttled), continued counting on repeated over-limit attempts, window reset via backdated `window_started_at`, per-user isolation, env-var fallback for both constants (including the two hardened edge cases), a two-connection concurrency test, and a test proving an earlier-refused submission still counts.
- `apps/api/tests/test_source_guards.py` — `SCAN_THROTTLE_HOME`, the new table-write guard, and the file-reach tuple update.
- `apps/web/src/api/client.ts` + `apps/web/src/__tests__/error-code-parity.test.ts` — `SCAN_RATE_LIMITED` export and parity rows.
- `infra/tests/test_runner_unit.py` / `test_migrate.py` — the ninth migration threaded through every existing down-step sequence, plus a dedicated round-trip test, a CHECK-constraint test, and an `ON DELETE CASCADE` test.

**Review findings breakdown:** 4 patched (0 high, 2 medium, 2 low — a message-wording mismatch against its own cited source; a missing lower-bound check on the rate that could silently disable scanning product-wide from a typo; a missing upper-bound check on the window that could crash every scan request with an unhandled `OverflowError`; a missing test proving an earlier-refused submission still counts toward the limit), 3 deferred (all low — a pre-existing stale cross-reference in `throttle.py`, an inherited ambiguous sentence in a `.down.sql` migration comment, and the general TOCTOU race between session resolution and a since-deleted user's row, already documented as a residual risk by Story 3.5), 9 rejected (verified false, matching an established codebase precedent this story correctly followed, or explicitly out of scope by FR-20's own stated scope — see Review Triage Log for the full list).

**Follow-up review recommendation:** `true` — 2 medium + 2 low patched findings score `3×2 + 1×2 = 8`, at or above the 5-point bar.

**Verification performed:**
- `uv run --project apps/api pytest apps/api/tests/test_scan_rate_limiting.py apps/api/tests/test_scan_submission.py apps/api/tests/test_source_guards.py apps/api/tests/test_audit_immutability.py apps/api/tests/test_no_registration.py` — pass, independently re-run after the patch pass (19 tests in the new file, up from 15).
- `npm --prefix apps/web test -- --run scan error-code-parity` — 106/106 pass, independently re-run.
- `make lint` — clean (ruff check, ruff format --check, oxlint, tsc --noEmit), independently re-run after the patch pass.
- Full `uv run pytest` (apps/api + shared/schema + infra + scripts/ingest, real Postgres + real ONNX CPU inference) — independently re-run twice (once before, once after the patch pass): 100% pass, zero skips, zero failures both times. (An intermediate run showed spurious skips from stale leftover ephemeral PostgreSQL clusters left behind by earlier, unrelated sessions in this sandbox exhausting shared memory — cleared before the runs recorded here, which are the ones that count.)
- Full `apps/web` vitest suite — 1736/1736 pass across 29 files, independently re-run after the patch pass.
- `make migrate` was not run literally against a throwaway cluster (the sandbox's shared-memory allocation was briefly exhausted by the same stale-cluster debris above); `infra/tests/test_migrate.py`'s real-Postgres round-trip tests — including the new `test_the_scan_rate_limit_pair_round_trips`, the CHECK-constraint test, and the cascade-delete test — exercise the identical migration application path and all passed.
- I/O & Edge-Case Matrix audit: all six rows are each covered by at least one test in `test_scan_rate_limiting.py` that ran and passed (under-the-limit, limit-crossed, window-elapsed, concurrent-burst, keeps-retrying, env-var-fallback), plus the two additional edge cases the review surfaced (non-positive rate, oversized window) and the earlier-refusal-still-counts case.

**Residual risks:**
- The three deferred findings above (stale cross-reference in an untouched file, an inherited ambiguous migration comment, and the general TOCTOU race on user deletion mid-request) — none specific to or newly introduced by this story.
- `DEFAULT_SCAN_RATE_LIMIT = 30` per `DEFAULT_SCAN_RATE_LIMIT_WINDOW = 60.0` seconds is, per FR-23/PRD OQ-13, a documented but uncalibrated placeholder; the real numbers are deferred to the Foundation build and the Phase 2 pilot, the same status FR-9's blur threshold already carries.
- Per the invocation prompt's standing orchestration rule: `sprint-status.yaml` was never read or written by this run, and this story has no acceptance criterion requiring a human-only action outside the repo (no external account, domain, DNS record, or credential), so the `awaiting-operator` path never applies here — confirmed independently by the intent-alignment review layer.
