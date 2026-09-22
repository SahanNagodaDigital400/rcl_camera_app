---
title: 'Ranked Candidate Results with Images'
type: 'feature'
created: '2026-09-22'
baseline_revision: '22cb39c8624298fb0d2c730ecb0717e5eaaaed08'
status: 'done'
review_loop_iteration: 0
followup_review_recommended: true
context: []
warnings: ['oversized']
deferred: []
---

<intent-contract>

## Intent

**Problem:** `POST /scans` (Story 3.3) ends at the quality gate and answers an empty `202` — Epic 2 already built a fully tested, populated vector search (`catalogue.find_candidates`, HNSW-indexed) that nothing outside a test file has ever called, so a passing scan has nowhere to send its cropped image and no screen to show a result on.

**Approach:** Wire `submit_scan` to call `catalogue.find_candidates` on the cropped image and answer `200` with up to three ranked candidates (tile_id, code, size, category, image_id — never a score); add a non-admin, session-gated reference-image route candidate cards can fetch from; build a Results screen (`apps/web`) reached only from a successful Crop confirm, rendering candidate cards with a tap-to-fullscreen viewer.

## Boundaries & Constraints

**Always:**
- Matching runs on `cropped` (post-crop, post-quality) — never the pre-crop frame — through `shared_vision.embed`/`preprocess` with no second implementation (AD-1).
- Embedding inference at scan time is serialized server-wide, one forward pass at a time (AD-16) — a `threading.Lock` around only the `shared_vision.embed(...)` call inside `find_candidates`, acquired after `require_claimed_user` resolves.
- The response is a bare JSON array of up to three candidates, each carrying `tile_id`, `code`, `size`, `category`, `image_id` — never `score`, `rank`, or any derived confidence wording (AD-20). Order in the array is the rank; the client paints the first as "Best match" and never re-derives or displays the ordinal.
- Each candidate is a distinct Tile; never deduplicated, collapsed, or diversified by Category (AD-18) — `_SELECT_CANDIDATES`'s existing `GROUP BY t.id` already guarantees this and must not change.
- A candidate's image is proxied through a new authenticated route, never a storage URL (AD-9) — `GET /tiles/{tile_id}/images/{image_id}`, gated by `require_claimed_user`, reusing `read_reference_image`'s lookup/response logic via one shared internal helper (no second implementation of the derivative-key lookup).
- The image shown is the tile's earliest reference image (`ORDER BY created_at, id`, `LIMIT 1` per tile) — the same "first image" rule `CatalogueScreen.thumbnail` already uses, so a tile's picture is consistent across both surfaces.
- Results is reached only from a successful `CropScreen` confirm (mirrors `showCrop`'s own pattern: set the data, then the section, in one render); a failed submission stays on Crop with the image and crop rectangle intact (already-built generic-error behavior — no change needed there).
- New `ScanCandidate` contract lives in `shared_schema` (Python + TS twin), closed-shape (`extra="forbid"` / exact-key TS guard), matching `tile.py`/`tile.ts`'s existing pattern and parity test shape.

**Block If:** None identified — no human-only action (external account, domain, credential) is needed; this story is fully buildable and verifiable inside the repo.

**Never:**
- No `Scan` table, no persistence of a result (Story 3.5).
- No rate limiting or anomaly flagging (Stories 3.6/3.7, AD-8) — the fixed order AD-16 asks for ("auth → rate-limit → inference slot") collapses to "auth → inference slot" until 3.6 lands; do not invent a rate limiter here.
- No size pre-filter (AD-19, not adopted in this epic).
- No threshold-based expansion beyond three or "no confident match" gating (PRD OQ-17, unanswered) — always return whatever `find_candidates` gives, up to three, including zero.
- No change to `_SELECT_CANDIDATES`, `Candidate`, or `find_candidates`'s tested return shape beyond adding the one serialization lock.
- No extension of the new inference lock to index-time embedding (`add_tile`/bulk-upload) — AD-16 scopes this to scan-time concurrency only.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Populated catalogue, good scan | Cropped image passes quality; catalogue has matches | `200`, up to 3 candidates ranked best-first, each with a fetchable image | No error |
| Empty catalogue | No tile ever indexed (no active generation) | `200`, empty array; Results shows "No confident match — retake, or ask a colleague." + a single Retake action | No error |
| Model missing | `shared_vision` model file absent | `503 matching_unavailable`; Crop's existing generic-error path shows the server's message, crop/image preserved | `503` |
| Stale index | Running pipeline stamp ≠ active generation's stamp | `503 pipeline_stamp_mismatch`; same generic-error handling as above | `503` |
| Mismatched image route ids | `GET /tiles/{tileId}/images/{imageId}` with an id pair naming no row | `404 image_not_found`, names neither id | `404` |

</intent-contract>

## Code Map

- `shared/schema/shared_schema/scan.py` (new) -- `ScanCandidate(BaseModel)`: `tile_id: UUID`, `code: str`, `size: str`, `category: str | None`, `image_id: UUID`; `model_config = ConfigDict(extra="forbid")`; docstring states the AD-20/AD-9 absences (`tile.py`'s own pattern).
- `shared/schema/shared_schema/ts/scan.ts` (new) -- `ScanCandidate` interface + `isScanCandidate`/`SCAN_CANDIDATE_KEYS`, `tile.ts`'s exact shape (sorted key-set guard, `isUuid` reused pattern restated per that file's own stated reason for not cross-importing).
- `shared/schema/tests/test_scan.py` (new) -- `test_tile.py`'s shape: valid body round-trips, extra key rejected, each field's wrong-type rejected, TS source cross-check, and explicit absence assertions for `score`/`rank`/`similarity`.
- `apps/api/api/catalogue.py` -- add `import threading`; add `require_claimed_user` to the `api.dependencies` import; add `_inference_lock = threading.Lock()` near `TOP_K`; in `find_candidates` (~885-936), keep `shared_vision.preprocess(image)` outside the lock and wrap only `shared_vision.embed(...)` with `with _inference_lock:`; add `_SELECT_PRIMARY_IMAGES` (`SELECT DISTINCT ON (tile_id) tile_id, id AS image_id FROM reference_image WHERE tile_id = ANY(%s) ORDER BY tile_id, created_at, id`) and `primary_reference_image_ids(conn, tile_ids: list[UUID]) -> dict[UUID, UUID]` (returns `{}` on an empty list without querying); extract `read_reference_image`'s body (~2841-2897) into `_serve_reference_image(conn, store, tile_id, image_id) -> Response`, keep the existing `@router.get("/admin/tiles/{tile_id}/images/{image_id}")` as a thin `require_administrator`-gated wrapper, and add `@router.get("/tiles/{tile_id}/images/{image_id}")` as a thin `require_claimed_user`-gated wrapper over the same helper.
- `apps/api/api/scan.py` -- add imports: `psycopg`; `from api.db import get_connection`; `from api.catalogue import find_candidates, primary_reference_image_ids`; `from shared_schema.scan import ScanCandidate`. Add `response: Response` and `conn: Annotated[psycopg.Connection, Depends(get_connection)]` params to `submit_scan`; drop `status_code=status.HTTP_202_ACCEPTED` from the decorator (defaults to `200`) and set `response_model=list[ScanCandidate]`; call `response.headers.update(NO_STORE)` as the first line (matches `search_tiles`'s convention); replace line 146's bare `Response(...)` return with: call `find_candidates(conn, cropped)`, resolve `primary_reference_image_ids` for the returned `tile_id`s, and return the mapped `list[ScanCandidate]`. Update the module and handler docstrings' now-stale "202 with no body — nothing to hand back" passages to describe the real response.
- `apps/api/tests/test_scan_submission.py` -- extend with `needs_model`-marked tests for the happy path (seed a tile via the existing `add_tile` test helper, submit a matching photo, assert the tile's `code` appears in the response) and the empty-catalogue case (no tile added, assert `200` + `[]`); note in a comment that the module docstring's "nothing here needs the ONNX model" claim no longer holds for these new cases.
- `apps/api/tests/test_catalogue_authorization.py` -- add a case for `GET /tiles/{tile_id}/images/{image_id}`: a claimed Staff or Administrator session succeeds, an unauthenticated request is refused, and a mismatched id pair is `404 image_not_found` (mirrors the existing admin-route coverage in this file).
- `apps/web/src/api/client.ts` -- add `export interface ScanCandidate` (or import the twin from `@rocell/schema/scan` the way `CatalogueScreen` imports `Tile` from `@rocell/schema/tile`) plus an `asScanCandidates(body: unknown)` validator (`asTiles`'s shape: `Array.isArray` + `every(isScanCandidate)`, else throw `MALFORMED_RESPONSE`); change `submitScan`'s return type to `Promise<ScanCandidate[]>`, returning `asScanCandidates(await apiRequest(...))`; update the doc comment above it and above `apiRequest`'s `204`/`202` shortcut (lines ~605-608, ~714-716) — both now stale, since `POST /scans` answers `200` with a body.
- `apps/web/src/screens/ResultsScreen.tsx` (new) -- renders `candidates: ScanCandidate[]` as up to three cards (image via `${API_PREFIX}/tiles/{tile_id}/images/{image_id}`, monospace Code, "Size · Category" line), first card gets `candidate-card-best-match` styling + "Best match" pill (UX-DR6); tapping a card opens `ImageViewer`; `candidates.length === 0` renders the verbatim "No confident match — retake, or ask a colleague." message plus a single "Retake" action calling `onBack`; a normal "Back" control otherwise. Props: `candidates: ScanCandidate[]`, `onBack: () => void`.
- `apps/web/src/screens/ResultsScreen.module.css` (new) -- `mockups/key-results.html`'s classes translated to tokens: `.card`/`.cardBest` (`--color-surface`, `--border-hairline` vs 2px `--color-accent`, `--radius-md`, one elevation tier), `.refImage` (68×68px, `--radius-sm`), `.bestPill` (accent bg/fg, `--radius-full`), `.code` (monospace type token), `.meta` (muted text), each card a `<button>` (≥44×44px) for the tap-to-fullscreen affordance.
- `apps/web/src/components/ImageViewer.tsx` (new) -- a minimal scrim+panel overlay (not `ConfirmDialog`: single "Close" control, no confirm/refusal states, so no multi-control Tab-cycle is needed) showing one `<img>` full-viewport (`object-fit: contain`) at the same `src` the card used; `Escape`, a scrim click, and Close all dismiss; focus moves to the panel on open and restores to the opener on close (`ConfirmDialog`'s open/restore effect, without its `busy`/cycle machinery). Props: `src: string`, `alt: string`, `onClose: () => void`.
- `apps/web/src/components/ImageViewer.module.css` (new) -- reuses `--scrim`, `--z-modal`, `--radius-lg` exactly as `ConfirmDialog.module.css` does.
- `apps/web/src/screens/CropScreen.tsx` -- change `onConfirm` prop type from `(rect) => Promise<void>` to `(rect) => Promise<ScanCandidate[]>` (return value unused inside this component, forwarded by `App`); add a small inline spinner beside the existing "Submitting…" button text (EXPERIENCE.md's "processing: lightweight spinner, no skeleton" — the wait for matching now happens inside this same request).
- `apps/web/src/screens/CropScreen.module.css` -- add a `.spinner` rule: a small `--color-accent`-bordered rotating ring, one `@keyframes` (first spinner in this codebase — `App.module.css`'s `.pending` comment is about the one-time session-bootstrap placeholder and does not apply here).
- `apps/web/src/App.tsx` -- add `'results'` to `Section` and `Screen`; add `candidates: ScanCandidate[] | null` state (`capturedImage`'s twin, same doc-comment shape, cleared by `showSection` alongside it); add `showResults(candidates: ScanCandidate[]): void` (`showCrop`'s pattern: candidates first, then section); in `currentScreen`, add `if (section === 'results') return candidates === null ? 'scan' : 'results';`; change the `crop` branch's `onConfirm` from `await submitScan(...); showSection('scan');` to `const result = await submitScan(...); showResults(result);`; add a `screen === 'results' && candidates !== null` render branch (the `crop` branch's shape) rendering `ResultsScreen` inside `AppShell`, `onBack={() => showSection('scan')}`.
- `apps/web/src/__tests__/scan.test.tsx` -- update the "sends a normalized rect ... and returns to Scan on success" test (~653-683) to assert navigation to Results and candidate rendering instead; add cases for the empty-candidates message + Retake, and for `matching_unavailable`/network failure staying on Crop (extends the existing generic-failure test at ~791-832, which already covers this shape for other codes).

## Tasks & Acceptance

**Execution:**
- `shared/schema/shared_schema/scan.py` + `ts/scan.ts` + `tests/test_scan.py` -- the `ScanCandidate` contract, both languages, parity-tested.
- `apps/api/api/catalogue.py` -- AD-16 serialization lock, the shared image-serving helper, the new non-admin image route, `primary_reference_image_ids`.
- `apps/api/api/scan.py` -- wire `find_candidates` into `POST /scans`, change its response shape and status.
- `apps/api/tests/test_scan_submission.py` + `test_catalogue_authorization.py` -- matching + empty-catalogue coverage, new route's authorization coverage.
- `apps/web/src/api/client.ts` -- `submitScan`'s new return type and validator.
- `apps/web/src/screens/ResultsScreen.tsx` + `.module.css` -- the results surface (UX-DR6).
- `apps/web/src/components/ImageViewer.tsx` + `.module.css` -- the tap-to-fullscreen verification moment.
- `apps/web/src/screens/CropScreen.tsx` + `.module.css` -- the processing spinner, updated `onConfirm` type.
- `apps/web/src/App.tsx` -- Results wiring (section/screen/state/navigation).
- `apps/web/src/__tests__/scan.test.tsx` -- Results-flow coverage.

**Acceptance Criteria:**
- Given I submit a Scan that passes quality guidance and the catalogue holds matches, when matching completes, then I see up to three Candidates ranked by visual similarity, each with its reference image, code, size, and category, and no similarity value anywhere on screen.
- Given two Candidates come from the same Category folder, when the results render, then both keep their own slot — nothing deduplicates, collapses, or diversifies the list by Category.
- Given the catalogue holds no matches (nothing ever indexed), when matching completes, then I see the verbatim "No confident match — retake, or ask a colleague." message and a single Retake action, never an empty screen with nothing to look at.
- Given I tap a Candidate card, when the tap registers, then its reference image opens full-screen, dismissible by Escape, a scrim click, or a Close control, with focus returned to the card afterward.
- Given matching itself fails (model missing or a stale index), when I confirm the crop, then I stay on Crop with the image and crop rectangle preserved and a plain "Try again" message, exactly as an existing generic submission failure already behaves.
- Given two scan requests arrive concurrently, when both reach the embedding step, then one waits for the other rather than running its forward pass in parallel (AD-16).

## Spec Change Log

## Review Triage Log

### 2026-09-22 — Review pass
- intent_gap: 0
- bad_spec: 0
- patch: 7: (high 0, medium 4, low 3)
- defer: 0
- reject: 9: (high 0, medium 1, low 8)
- addressed_findings:
  - `[medium]` `[patch]` `apps/api/api/scan.py`'s `image_ids[candidate.tile_id]` bracket lookup raised an unhandled `KeyError` (a raw 500) if a tile was removed between `find_candidates` and `primary_reference_image_ids` within the same request — a real race the cited FR-7 invariant doesn't cover (it guards an existing tile's image count, not the tile's own removal). Fixed with `.get()` and filtering out any candidate with no resolved image; comment corrected to describe the real race.
  - `[medium]` `[patch]` No test drove `POST /scans` itself into `503 matching_unavailable` — only `find_candidates` via other routes, and a frontend test that mocks the HTTP layer. Added `test_a_missing_model_artifact_refuses_the_scan_through_the_real_route`, monkeypatching the model path the way `test_edit_tile.py` does, against the real route.
  - `[medium]` `[patch]` AD-16's `_inference_lock` had no test proving two concurrent scans actually serialize. Added `test_two_concurrent_scans_serialize_through_the_inference_lock`, in `test_remove_tile.py`/`test_login_throttling.py`'s `threading.Event`/`threading.Thread` shape, asserting the recorded enter/exit order.
  - `[medium]` `[patch]` `isScanCandidate`'s rejection path (extra key, wrong type) was untested, unlike every sibling contract (`tile-contract.test.ts`, `user-contract.test.ts`, `audit-contract.test.ts`). Added `scan-contract.test.ts` with direct pass/reject assertions.
  - `[low]` `[patch]` The `_inference_lock` docstring/comment claimed "service-wide" serialization, which a `threading.Lock` only provides within one process. Reworded to state the guarantee precisely.
  - `[low]` `[patch]` `catalogue.py`'s module docstring header ("Nine routes and two functions") undercounted the diff's own additions (one new route, two new non-route functions: `primary_reference_image_ids` and `_serve_reference_image`). Fixed to "Eight routes and three functions that are not routes" with the missing bullet added.
  - `[low]` `[patch]` `ImageViewer`'s focus-restore-on-close behavior was asserted by its docstring but not by any test, unlike `ConfirmDialog`'s equivalent coverage. Added focus-restore assertions across Escape/scrim/Close in `scan.test.tsx`.

Rejected (verified false, out of scope by the architecture's own explicit design, or redundant with an already-established codebase pattern): `shared_vision.preprocess` moving outside the `try/except FileNotFoundError` block was flagged as a risk, but `preprocess` never touches the model file or raises that exception — verified false by direct inspection; no timeout/circuit-breaker around `_inference_lock` was proposed, but AD-16's own text explicitly specifies a second scan *waits* rather than being rejected or timed out — adding one would contradict the cited architecture decision, not fix a gap; an end-to-end test for `category: null` through `POST /scans` → `ResultsScreen` was proposed, but the DB layer resolves every tile's category to the `UNKNOWN` sentinel at write time (matches `Tile.category`'s own "always populated in practice" precedent), making a true-`null` path effectively unreachable and already covered at the shared-schema layer; unhandled `<img>` `onError` on both the candidate card and `ImageViewer` was flagged, but no image-consuming screen anywhere in this codebase (including `CatalogueScreen`'s own thumbnail) handles a broken image specially — not a regression this story introduces; `ResultsScreen`'s empty-match state offering only a single "Retake" action was flagged as a possible gap, but this is the same deliberate one-action pattern Story 3.3's `qualityRetake` banner already established for an analogous state; no logging/metrics around scan matching was proposed, but Story 3.3's own review already established (and this review re-confirms) that no source document asks for scan telemetry; a client-side cap enforcing at most 3 candidates in `asScanCandidates` was proposed, but the server's own `TOP_K = 3` `LIMIT` already makes a same-origin, session-authenticated response of more than 3 candidates unreachable in practice; `primary_reference_image_ids`'s "no query on an empty list" docstring claim being untested was flagged, but it is an implementation detail with no observable behavior difference (`ANY('{}')` is a valid, harmless query) and is already indirectly exercised by the empty-catalogue test.

## Design Notes

**Matching is not a second endpoint.** `scan.py`'s own docstring already frames 3.4 as extending `submit_scan` in place; this spec keeps that — one handler, one request, now with a real body on success. The status code moves from `202` to `200` because the request is no longer "accepted for later" — it fully resolves the match before answering, which is what `200` means and what `search_tiles`, `add_tile`, and every other synchronous route in this codebase already use.

**"Results (pending)" is read as the sub-3-second gap between pressing Confirm and the screen swapping, not a second async phase.** The alternative reading — navigate to Results immediately and let it show its own spinner while `POST /scans` is still in flight — would require Results to own a retry/refetch lifecycle nothing in EXPERIENCE.md's failure-state text actually asks for ("the crop and captured image are preserved" already holds under the simpler reading, because Crop stays mounted for the whole request). The lightweight-spinner requirement is honored on the Confirm button itself, where the in-flight state already lives.

**Why a second query for the image id, not a join in `_SELECT_CANDIDATES`.** That query is AD-13's tested max-pool search; folding in "which reference image represents this tile" would couple two independent concerns (ranking vs. display) inside one query already carrying review history. A single `DISTINCT ON (tile_id)` batched by the (≤3) returned tile ids is one extra indexed round trip, well inside the 3-second budget, and reuses `_SELECT_TILE_IMAGES`'s exact ordering so the picture shown always matches `CatalogueScreen`'s own "first image."

**Why a new route instead of loosening the admin one.** `GET /admin/tiles/{tile_id}/images/{image_id}` is deliberately `require_administrator`-gated; changing that gate would open an admin surface to Staff. A second, thin route over the same lookup helper keeps both authorization boundaries exactly where they are.

## Verification

**Commands:**
- `uv run --project shared/schema pytest shared/schema/tests/test_scan.py` -- expected: pass.
- `uv run --project apps/api pytest apps/api/tests/test_scan_submission.py apps/api/tests/test_catalogue_authorization.py` -- expected: pass, including the new matching/empty-catalogue/route-authorization cases.
- `npm --prefix apps/web test -- --run scan error-code-parity styling-wiring` -- expected: pass.
- `make lint` -- expected: clean (ruff + oxlint + tsc --noEmit).
- `make test` -- expected: full suite green.

## Auto Run Result

**Summary of implemented change:** Wired Epic 2's already-tested vector search into `POST /scans`: a passing scan now embeds the cropped region (through the same `shared_vision.embed`/`preprocess` calls the catalogue write path uses), searches the HNSW-indexed catalogue via `catalogue.find_candidates`, and answers `200` with up to three ranked `ScanCandidate`s (`tile_id`, `code`, `size`, `category`, `image_id` — never a score or rank number, AD-20) — replacing the old empty `202`. Embedding inference at scan time is now serialized within one server process via a `threading.Lock` (AD-16), acquired only after `require_claimed_user` resolves. A new non-admin `GET /tiles/{tile_id}/images/{image_id}` route (gated by `require_claimed_user`, sharing its lookup logic with the existing admin-only route through one helper) lets Candidate cards fetch reference images. `apps/web` gained a `ResultsScreen` (candidate cards, best-match styling, an empty-catalogue "no confident match" state) and a minimal `ImageViewer` for the tap-to-fullscreen verification moment, reached from a successful Crop confirm; a submission or matching failure still leaves the user on Crop with the image and crop rectangle intact, unchanged from Story 3.3's behavior.

**Files changed:**
- `shared/schema/shared_schema/scan.py`, `ts/scan.ts`, `tests/test_scan.py` (new) — the `ScanCandidate` contract, both languages, parity-tested, closed-shape (no `score`/`rank`).
- `apps/api/api/catalogue.py` — `_inference_lock` (AD-16, scoped to the `embed` call only), `primary_reference_image_ids` (batched "which image represents this tile" lookup), `_serve_reference_image` (shared helper behind both the admin and the new non-admin image route), the new `GET /tiles/{tile_id}/images/{image_id}` route.
- `apps/api/api/scan.py` — `POST /scans` now calls `find_candidates`, returns `200` + `list[ScanCandidate]` instead of `202` + empty body; a candidate with no resolved image (a rare mid-request tile-removal race) is filtered out rather than raising.
- `apps/api/tests/test_scan_submission.py` — matching happy path, category-diversity (AD-18), empty-catalogue, a direct `503 matching_unavailable` test through the real route, and a concurrency test proving `_inference_lock` actually serializes two overlapping scans.
- `apps/api/tests/test_catalogue_authorization.py` — the new image route's success/refusal/mismatched-pair cases.
- `apps/api/tests/test_no_registration.py` — route-table assertion updated for the new route (18 routes total).
- `apps/web/src/api/client.ts` — `submitScan` now returns `Promise<ScanCandidate[]>` via a validating `asScanCandidates`; stale `202`-era doc comments corrected.
- `apps/web/src/__tests__/scan-contract.test.ts` (new) — direct `isScanCandidate` pass/reject unit tests, mirroring `tile-contract.test.ts`.
- `apps/web/src/screens/ResultsScreen.tsx` / `.module.css` (new) — the Results surface, candidate cards, best-match styling (UX-DR6), empty-match message.
- `apps/web/src/components/ImageViewer.tsx` / `.module.css` (new) — the tap-to-fullscreen viewer.
- `apps/web/src/screens/CropScreen.tsx` / `.module.css` — `onConfirm` now returns `Promise<ScanCandidate[]>`; a processing spinner added beside "Submitting…".
- `apps/web/src/App.tsx` — `results` section/screen, `candidates` state (cleared everywhere `capturedImage` is), `showResults`.
- `apps/web/src/styles/tokens.css` — three derived tokens for the best-match border, candidate image size, and spinner.
- `apps/web/src/__tests__/scan.test.tsx` — Results-flow coverage (navigation, candidate rendering, empty state, matching-failure-stays-on-Crop) plus `ImageViewer` focus-restore assertions.

**Review findings breakdown:** 7 patched (0 high, 4 medium, 3 low — all fixed and re-verified: an unhandled `KeyError` on a mid-request tile-removal race, a missing direct test of `POST /scans`' own `503 matching_unavailable` propagation, a missing concurrency test for the AD-16 lock, a missing direct `isScanCandidate` rejection test, an over-claiming "service-wide" lock comment, a miscounted module-docstring route/function tally, and a missing `ImageViewer` focus-restore test), 0 deferred, 9 rejected (verified false, out of scope by the architecture's own explicit design, or redundant with an already-established codebase convention — see Review Triage Log for the full list).

**Follow-up review recommendation:** `true` — 4 medium + 3 low patched findings score `3×4 + 1×3 = 15`, at or above the 5-point bar.

**Verification performed:**
- `uv run --project shared/schema pytest shared/schema/tests/test_scan.py` — 16/16 pass, independently re-run and confirmed.
- `uv run --project apps/api pytest apps/api/tests/test_scan_submission.py apps/api/tests/test_catalogue_authorization.py` — 63/63 pass, independently re-run and confirmed, including the two new patch-added tests running against the real ONNX model (not skipped).
- `npm --prefix apps/web test -- --run scan error-code-parity styling-wiring` — 264/264 pass, independently re-run and confirmed.
- `make lint` — clean (ruff check, ruff format --check, oxlint, tsc --noEmit), independently re-run and confirmed.
- `make test` — full suite green: `apps/web`'s full vitest suite 1681/1681 pass (independently re-run, no flakes on the verification run), and the full `uv run pytest` workspace suite (apps/api + shared/schema + infra + scripts/ingest, real Postgres + real ONNX CPU inference) independently re-run to completion with an explicitly captured `EXITCODE:0` and zero failure/error markers in its output.
- I/O & Edge-Case Matrix audit: all five rows covered by tests that ran and passed — populated-catalogue happy path and empty-catalogue via `test_scan_submission.py`'s dedicated tests; model-missing and stale-index via the shared `find_candidates`/`_verify_stamp` tests already covering that code path (`test_add_tile.py`, `test_edit_tile.py`, `test_bulk_upload.py`, `test_tile_searchable.py`) plus the review-added direct `POST /scans` test and the frontend's generic-failure test; the mismatched-image-route-ids row via `test_a_mismatched_pair_is_not_found_on_the_scan_image_route`.

**Residual risks:**
- `_inference_lock` serializes embedding inference within one server process only, not across processes — correctly documented after this review pass, but a future move to a multi-worker deployment would need a cross-process mechanism (e.g. a DB-backed lock) to preserve AD-16's guarantee; out of this story's scope, no source document asks for multi-worker support today.
- No telemetry logs scan volume, match rate, or `_inference_lock` contention — out of scope (no source document asks for it, consistent with Story 3.3's own review finding), but would be the natural signal to watch if AD-16 contention ever becomes a real operational question.
- A broken candidate image (network failure, session expiry mid-view) renders the browser's default broken-image treatment with no in-app message — matches this codebase's existing convention everywhere else images are shown (e.g. `CatalogueScreen`), not a regression this story introduces, but worth revisiting product-wide if it ever becomes a real complaint.

