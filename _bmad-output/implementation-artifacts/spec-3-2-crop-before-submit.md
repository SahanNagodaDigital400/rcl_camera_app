---
title: 'Crop Before Submit'
type: 'feature'
created: '2026-09-22'
baseline_revision: '8a5e20515bdfb86b85a35cff76a3737d311c5f1f'
status: 'done'
review_loop_iteration: 0
followup_review_recommended: true
context: []
warnings: ['oversized']
deferred:
  - summary: >-
      `POST /scans` computes the server-side crop via `crop_to_rect` purely to
      validate it, then discards the cropped image — no consumer exists until
      Story 3.3/3.4.
    evidence: |-
      `apps/api/api/scan.py`'s `submit_scan` calls `shared_vision.crop_to_rect(...)`
      and never assigns or uses the returned `Image`. Every valid request pays
      for a real PIL crop of a decoded, up-to-2048px-capped image with the
      result thrown away. Deliberate per this story's own scope (no
      persistence, no matching yet), but worth revisiting once 3.3/3.4 give
      the result a consumer.
    location: >-
      apps/api/api/scan.py
    severity: low
  - summary: >-
      Sign Out is not disabled while a scan submission is in flight, so a tap
      could unmount `CropScreen` mid-request.
    evidence: |-
      `AppShell`'s Sign Out control is not told about `CropScreen`'s
      `confirming` state. This mirrors a pre-existing pattern across other
      in-flight admin actions in the app (none of them disable Sign Out
      either), so it is not unique to this story.
    location: >-
      apps/web/src/screens/CropScreen.tsx
    severity: low
  - summary: >-
      `apiRequest`'s widened `204 || 202` no-body handling is global rather
      than scoped to `/scans`.
    evidence: |-
      A future endpoint that legitimately returns `202` with a real JSON body
      would have that body silently discarded by `apiRequest`. The only
      current `202` caller (`POST /scans`) is genuinely bodyless, so there is
      no live bug today.
    location: >-
      apps/web/src/api/client.ts
    severity: low
  - summary: >-
      `apps/api/api/scan.py` imports `catalogue._read_upload`, a
      leading-underscore "module-private" helper, across module boundaries.
    evidence: |-
      Reuse is well-motivated (avoids a second read-bytes implementation) and
      was the spec's own suggested approach, but the naming still signals
      "not for external use" and invites future drift; a public, unprefixed
      helper would match the intent better.
    location: >-
      apps/api/api/scan.py
    severity: low
  - summary: >-
      `scan.test.tsx`'s `stubFetchWithCalls` duplicates most of the existing
      `stubFetch` helper's shape (queue draining, default-404 fallback,
      response shape) instead of extending it to optionally capture calls.
    evidence: |-
      Two near-identical fetch stubs now exist in the same test file and can
      drift out of sync with each other over time. Low risk, test-code only.
    location: >-
      apps/web/src/__tests__/scan.test.tsx
    severity: low
  - summary: >-
      `CropScreen`'s `rect` state is not reset in response to the `image` prop
      changing, and no `key` is passed to force a remount.
    evidence: |-
      Currently safe only because `App.tsx` always fully unmounts and
      remounts `CropScreen` between photos (no code path holds it mounted
      across two different `image` values), but nothing in `CropScreen` itself
      guards against that assumption changing later.
    location: >-
      apps/web/src/screens/CropScreen.tsx
    severity: low
  - summary: >-
      `onDragMove` does not stop an already-active drag when a submission
      begins mid-gesture, only `beginDrag` checks `confirming`.
    evidence: |-
      A very tight multi-touch race (one finger still dragging while another
      taps Confirm) could let `rect` keep changing after submission starts.
      Low probability and low impact — the submitted rect is read once at
      confirm time, not re-read after.
    location: >-
      apps/web/src/screens/CropScreen.tsx
    severity: low
  - summary: >-
      The crop selector's drag handles have no keyboard alternative (no
      `tabIndex`/`role`/arrow-key nudging) for a Staff/Admin user who cannot
      use touch or a mouse drag.
    evidence: |-
      Verified against the source of truth: epics.md's UX-DR17 scopes
      "visible focus states with a keyboard path" explicitly to "all admin
      surfaces," not the mobile-first Scan/Crop flow — the touch-target-size
      half of the same accessibility floor (which this screen does meet) is
      the only part stated for mobile surfaces. This is a legitimate future
      accessibility improvement, not a violation of a stated AC.
    location: >-
      apps/web/src/screens/CropScreen.tsx
    severity: low
---

<intent-contract>

## Intent

**Problem:** `CropScreen` (Story 3.1) is an inert placeholder — it shows the captured/uploaded image and a "Back" control only. Nothing lets Staff/Admin actually crop to the tile face, and no submission path exists at all.

**Approach:** Turn `CropScreen` into a real free-form crop selector (drag corners/edges to resize, drag body to move, pre-filled best-guess selection) with a "Confirm Crop" accent action. Add a new authenticated `POST /scans` endpoint that takes the client's already-downscaled image plus a normalized 0–1 crop rectangle and executes the pixel crop exactly once, server-side, in `shared/vision`.

## Boundaries & Constraints

**Always:**
- The crop rectangle sent to the server is normalized (0–1, relative to the *uploaded* image's own width/height), never absolute pixels, and never a pre-cropped image (AD-11).
- The pixel crop itself executes exactly once, server-side, in `shared/vision` — never client-side canvas manipulation.
- `POST /scans` requires an authenticated, claimed session (Staff or Admin) via `require_claimed_user` — the same dependency Scan surfaces use generally, not `require_administrator` (this is not an admin-only surface).
- The uploaded image goes through the existing AD-7 intake path (`shared_vision.intake_image`) with `UPLOAD_MAX_PIXELS` (untrusted query upload), never `REFERENCE_MAX_PIXELS`.
- Crop handles are ≥44×44px touch targets; new colors/dimensions are new tokens in `tokens.css`, never literals (`no-raw-values.test.ts`).
- "Confirm Crop" is this screen's one accent-styled action; "Back" stays the existing secondary control.
- Any new API error code gets a TypeScript twin in `client.ts` and a row in `error-code-parity.test.ts`, or that test fails.

**Never:**
- No quality/blur check (Story 3.3), no matching/candidates (Story 3.4), no `Scan` DB persistence (no such table exists yet — confirmed absent from `infra/migrations`). `POST /scans` in this story crops and responds; it does not store a row.
- No crop-detection ML for the "best-guess" default selection — a fixed inset default is sufficient.
- No pinch-zoom gesture on the crop stage.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Happy path | Valid image + rect within [0,1], non-degenerate | `POST /scans` runs intake, crops server-side, responds `202` | No error |
| Degenerate rect | `width`/`height` ≤ 0, or `x+width`>1, or `y+height`>1, or `x`/`y` outside [0,1) | Refused before crop | `422 invalid_crop_rect` |
| Oversized/unreadable image | Corrupt bytes, or over `UPLOAD_MAX_PIXELS` | Refused by existing intake path | `422 unreadable_image` / `413 image_too_large` |
| Signed-out caller | No/invalid session cookie | Refused, no crop attempted | `401 unauthorized` |
| Submission network/server failure | `apiRequest` rejects | Inline error on Crop screen; image and selection preserved, Confirm re-enabled | Client-side retry via re-tap |

</intent-contract>

## Code Map

- `apps/web/src/screens/CropScreen.tsx:24-77` -- replace the inert placeholder with a real crop selector: pointer-driven drag body (move) + 8 handles (resize), default rect inset ~10% on each side, dark scrim (`--scrim`, already in `tokens.css`) over the deselected area, accent border. Keep the existing `useEffect` object-URL pattern (`:48-60`) unchanged. Add `onConfirm: (rect: NormalizedCropRect) => Promise<void>` alongside existing `onBack`; add in-flight/error state around the Confirm button, mirroring `ScanScreen`'s disable-while-in-flight and inline-error patterns from the Story 3.1 review.
- `apps/web/src/screens/CropScreen.module.css` -- new rules for `.stage`, `.handle` (corner + edge, `--touch-target-min: 44px`), a new `--crop-border-width` token (no existing accent-border-width token to reuse — `--framing-guide-border-width` is Scan-specific), and Confirm's accent-button treatment (mirror `App.module.css`'s Scan-door pattern from Story 3.1's Code Map).
- `apps/web/src/App.tsx:531-543,583-588` -- `showCrop`/the `CropScreen` render call: add a `handleConfirmCrop` (or similar) that calls the new API client function, then on success calls `showSection('scan')` (no Results screen exists yet — mirrors Story 3.1's own precedent of leaving the next hand-off inert). `capturedImage` clearing already happens via the existing sign-out/role-loss paths (`:314-325`); no change needed there.
- `apps/web/src/api/client.ts:19,231,239,411,584,590,606-610` -- add `submitScan(image: Blob, rect: NormalizedCropRect): Promise<void>` following the `AddTileScreen`-style `FormData` + `apiRequest('/scans', { method: 'POST', body, timeoutMs: UPLOAD_TIMEOUT_MS })` pattern; add `export const INVALID_CROP_RECT = 'invalid_crop_rect';` beside the existing `IMAGE_TOO_LARGE`/`UNREADABLE_IMAGE` exports (`:231-239`).
- `apps/api/api/scan.py` (new) -- `router = APIRouter(tags=["scan"])`; `POST /scans` with `Depends(require_claimed_user)` (`api/dependencies.py:170`), form fields `crop_x/crop_y/crop_width/crop_height: float` + `image: UploadFile`. Reuse `catalogue._read_upload`-equivalent bound-read (or import if made reusable) then `shared_vision.intake_image(data, max_pixels=shared_vision.UPLOAD_MAX_PIXELS)`, catching `ImageTooLarge`/`UnreadableImage` exactly as `catalogue._accept_bytes` does (`apps/api/api/catalogue.py:1024-1036`) — import `IMAGE_TOO_LARGE`/`UNREADABLE_IMAGE`/`TOO_LARGE`/`NOT_AN_IMAGE` from `catalogue` rather than redefining. Validate the rect (raise local `INVALID_CROP_RECT = "invalid_crop_rect"` as an `ApiError` 422 on violation) before calling the new `shared_vision` crop function. Respond `Response(status_code=status.HTTP_202_ACCEPTED)` — no body, no persistence.
- `apps/api/api/main.py:170-189` -- `app.include_router(scan.router)`.
- `shared/vision/shared_vision/intake.py:97-105,194` -- add `class InvalidCropRect(IntakeRefused)` beside `UnreadableImage`/`ImageTooLarge`, and `crop_to_rect(image: Image.Image, x: float, y: float, width: float, height: float) -> Image.Image`, placed beside `display_derivative` (post-intake `PIL.Image` transform, not part of the symmetric `pipeline.py` index/query path per that module's own docstring warning). Validates bounds/non-degenerate area, computes the pixel box from `image.width/height`, returns the cropped `Image.Image`.
- `apps/web/src/__tests__/error-code-parity.test.ts:272,126-178,180-211` -- add `'scan.py'` to `routers`; add an `invalid_crop_rect` row to both `PYTHON` and `TYPESCRIPT` maps.
- `apps/api/tests/test_catalogue_authorization.py` -- pattern to imitate for `apps/api/tests/test_scan_submission.py` (new): happy-path 202, `401` signed-out, `422 invalid_crop_rect`, `422 unreadable_image`/`413 image_too_large`.
- `apps/web/src/__tests__/scan.test.tsx` -- extend with Crop-screen tests: default inset selection renders, drag-to-resize/move updates the rect, Confirm calls the API with a normalized rect matching the on-screen selection, Confirm-in-flight disables the button, a failed submission preserves image+selection and shows inline error, Back still discards as before. First pointer/drag-gesture tests in the repo — no existing helper to reuse; use `PointerEvent` dispatch directly.

## Tasks & Acceptance

**Execution:**
- `shared/vision/shared_vision/intake.py` -- add `InvalidCropRect` + `crop_to_rect` -- the one server-side crop execution point (AD-11).
- `apps/api/api/scan.py` (new) + `apps/api/api/main.py` -- add `POST /scans`: auth, intake, rect validation, crop, `202` -- the Scan submission path AD-11 requires, sized to exactly this story (3.3/3.4 extend it later, not built now).
- `apps/web/src/api/client.ts` -- `submitScan` + `INVALID_CROP_RECT` export -- client-side call the crop screen uses.
- `apps/web/src/screens/CropScreen.tsx` + `.module.css` -- real crop selector + Confirm action -- the FR-24 UI.
- `apps/web/src/App.tsx` -- wire Confirm through to `submitScan` and back to Scan on success.
- `apps/web/src/__tests__/error-code-parity.test.ts` -- add `scan.py`/`invalid_crop_rect` -- keeps the two-language contract intact.
- `apps/api/tests/test_scan_submission.py` (new) -- I/O matrix coverage.
- `apps/web/src/__tests__/scan.test.tsx` -- Crop-screen drag/confirm coverage.

**Acceptance Criteria:**
- Given I've captured or uploaded a photo, when I'm shown the Crop screen, then a pre-filled free-form crop selection is visible over the image and I can drag corners/edges to resize or drag the body to move it.
- Given I have not confirmed a crop, when I try to proceed, then submission does not happen — Confirm is the only path forward from Crop.
- Given I tap Confirm Crop, then the client sends the full downscaled image plus a normalized 0–1 crop rectangle (computed from the on-screen selection against the image's actual pixel dimensions) to the server, and the server executes the crop exactly once.
- Given a submission fails (network or server error), when I'm back on Crop, then the image and my crop selection are preserved and I can retry.

</intent-contract>

## Spec Change Log

## Review Triage Log

### 2026-09-22 — Review pass
- intent_gap: 0
- bad_spec: 0
- patch: 6: (high 1, medium 3, low 2)
- defer: 8: (high 0, medium 0, low 8)
- reject: 5: (high 0, medium 0, low 5)
- addressed_findings:
  - `[high]` `[patch]` The normalized crop rectangle was measured against `.stage`'s own `getBoundingClientRect()`, but `.stage` carries a 360px `min-height` while `.image` flows at the top without stretching to fill it — for an ordinary landscape phone photo under 360px rendered tall at typical mobile widths, the stage's box no longer equals the image's own box, so the crop sent to the server would diverge from what the user saw and dragged. Fixed by adding a `.frame` wrapper around only the `<img>` (no min-height of its own) and measuring `normalizedPoint` against it instead of `.stage`; added a test giving `.stage` and `<img>` distinct boxes and asserting the submitted rect matches the image's box.
  - `[medium]` `[patch]` `crop_to_rect` let `nan`/`inf` width/height/x/y bypass every bounds check (NaN comparisons are always `False`) and reach `round()`, which raises an uncaught `ValueError` — a malformed request produced a `500` instead of `422 invalid_crop_rect`. Fixed with an unconditional `math.isfinite` check first; added nan/inf cases to both test suites.
  - `[medium]` `[patch]` The `max(left + 1, ...)` pixel-rounding guard in `crop_to_rect` assumed `left + 1 <= image.width`, but `x` close enough to 1.0 can round `left` up to `image.width` itself, silently producing a zero-width crop instead of raising — contradicting the function's own "raise rather than clamp" design. Fixed by raising `InvalidCropRect` when `right <= left or bottom <= top`; added a boundary-rounding test.
  - `[medium]` `[patch]` `CropScreen`'s `beginDrag` had no guard against a second pointer starting a new drag while one was active, silently orphaning the first pointer's capture. Fixed with an early return when `dragRef.current !== null`; added a mid-drag second-pointer test.
  - `[low]` `[patch]` `_CROP_ORIGIN_CEILING` was defined but the `x + width > 1` / `y + height > 1` checks still used the bare literal `1`. Fixed to use the named constant in both places.
  - `[low]` `[patch]` `.error` and `.hint`, the two new classes in `CropScreen.module.css`, had no `styling-wiring.test.ts` coverage unlike every other class in that file. Added matching assertions.

Deferred (real but low-severity, not blocking): the crop_to_rect result in `scan.py` is computed then discarded (no consumer until Story 3.3/3.4); Sign Out is not disabled during an in-flight scan submission (pre-existing pattern across other in-flight admin actions); `apiRequest`'s widened `204 || 202` no-body handling is global rather than scoped to `/scans`; `_read_upload` is imported across modules despite its underscore-privacy convention; `stubFetchWithCalls` duplicates `stubFetch`'s shape in the test file; `CropScreen`'s `rect` state is not reset via a `key` prop (currently safe only because the screen always fully unmounts between images); `onDragMove` does not stop an already-active drag when a submission begins mid-gesture; no keyboard alternative exists for the crop selector's drag handles (verified against epics.md UX-DR17: the keyboard-path requirement is explicitly scoped to admin surfaces, not the mobile Scan/Crop flow, so this is a best-practice gap rather than an AC violation).

Rejected (verified false or out of scope): the route-table test's "ten admin paths" naming was verified correct against the actual route list (10 pre-existing `/admin/` paths, unrelated to this story, plus `/scans` counted separately) — the reviewer miscounted; the rendered selection's inline `%` style strings were flagged for float noise, but the values that are actually submitted (`rect.x`/`y`/`width`/`height`) are already rounded in state before that multiplication, so this is cosmetic-only; the hardcoded `'scan.jpg'` filename is safe because `downscaleToBlob` (Story 3.1) is contractually always JPEG; missing rate limiting on `POST /scans` is explicitly Story 3.6's scope, not this one's; a malformed/missing multipart field was flagged as bypassing the shared `ApiError` envelope, but `apps/api/api/main.py` already installs a global `RequestValidationError` handler that normalizes FastAPI's own validation errors into the same envelope — verified in source, no gap exists.

## Design Notes

**Crop stays the one place this executes.** `shared_vision.crop_to_rect` is written as a standalone, reusable function (not inlined into `scan.py`) precisely because AD-11 flags it as reusable later for admin-added Reference Images — even though that path isn't adopted in this epic (spine's own Deferred section confirms it, resolved as "no" for now).

**Endpoint intentionally does less than "Scan submission" eventually will.** `POST /scans` today is crop-only: no quality check (3.3), no matching (3.4), no persisted `Scan` row (3.5, no table exists). It responds `202` with an empty body — there is nothing yet to hand back, and inventing a response shape now that 3.3/3.4 will just replace is exactly the kind of fantasized scope this workflow avoids. Story 3.3 is expected to insert its check between crop and response in this same handler.

**Default crop inset, not full-frame.** The UX mockup (`key-crop.html`) shows an inset "best-guess" selection, not the full frame — matching that spirit (not its exact pixel values, which are illustrative) avoids a first-time user having to shrink from the edges every time.

## Verification

**Commands:**
- `npm --prefix apps/web test -- --run scan error-code-parity` -- expected: new + existing tests pass.
- `uv run --project apps/api pytest apps/api/tests/test_scan_submission.py` -- expected: pass.
- `make lint` -- expected: clean (ruff + oxlint + tsc --noEmit).
- `make test` -- expected: full suite green, including `no-raw-values`, `tokens`, `styling-wiring`.

**Manual checks (if no CLI):**
- jsdom cannot exercise real pointer drag physics on a live device; smoke-test drag-to-resize/move on an actual touchscreen (desktop Chrome + one mobile browser) before calling this done.

## Auto Run Result

**Summary of implemented change:** Turned `CropScreen` (Story 3.1's inert placeholder) into a real free-form crop selector — drag the body to move it, drag any of 8 corner/edge handles to resize it, a pre-filled 10%-inset default selection, and a "Confirm Crop" accent action. Added `POST /scans`, a new authenticated (`require_claimed_user`, Staff or Admin) FastAPI endpoint that takes the client's downscaled image plus a normalized 0–1 crop rectangle, runs it through the existing AD-7 intake path at `UPLOAD_MAX_PIXELS`, and executes the pixel crop exactly once server-side via a new `shared_vision.crop_to_rect` function — scoped deliberately to crop-only, since no quality check (3.3), matching (3.4), or `Scan` persistence (3.5) exist yet.

**Files changed:**
- `shared/vision/shared_vision/intake.py` (+`__init__.py`) — new `crop_to_rect` (AD-11's one server-side crop execution point) and `InvalidCropRect` exception; validates bounds (finite, non-degenerate, in-image) and raises rather than clamps.
- `apps/api/api/scan.py` (new) — `POST /scans`: auth, intake, crop-rect validation via `crop_to_rect`, `202` with an empty body.
- `apps/api/api/main.py` — registers `scan.router`.
- `apps/api/tests/test_scan_submission.py` (new) — I/O-matrix coverage: happy path (both roles), degenerate/out-of-bounds/nan/inf rects, full-frame edge case, oversized/unreadable/empty image, signed-out, temporary-credential.
- `apps/api/tests/test_no_registration.py` — route-table assertion extended with `/scans` and why it isn't a registration surface.
- `apps/web/src/screens/CropScreen.tsx` + `.module.css` — the real crop editor: drag/resize state machine, pointer capture, a `.frame` wrapper so the normalized rect is measured against the image's own box (not the taller `.stage`), in-flight/error handling.
- `apps/web/src/App.tsx` — wires `CropScreen`'s `onConfirm` to `submitScan`, returning to Scan on success (no Results screen exists yet).
- `apps/web/src/api/client.ts` — `submitScan`, `NormalizedCropRect`, `INVALID_CROP_RECT`; widened `apiRequest`'s no-body handling to `204 || 202`.
- `apps/web/src/styles/tokens.css` — new tokens: `--crop-border-width`, `--crop-scrim-spread`, `--crop-handle-mid`, `--crop-handle-offset`.
- `apps/web/src/__tests__/scan.test.tsx` — Crop-screen selection/drag/confirm/error coverage, including the multi-touch and stage-vs-image regression tests added during review.
- `apps/web/src/__tests__/error-code-parity.test.ts` — `scan.py` + `invalid_crop_rect` added to the two-language contract check.
- `apps/web/src/__tests__/styling-wiring.test.ts` — Crop's accent-budget test rewritten for the real Confirm/Back/selection/handle styling, plus `.error`/`.hint` coverage added in review.
- `shared/vision/tests/test_intake.py` — direct unit coverage for `crop_to_rect`/`InvalidCropRect`, extended in review with nan/inf and rounding-boundary cases.

**Review findings breakdown:** 6 patched (1 high, 3 medium, 2 low — all fixed and re-verified), 8 deferred (all low), 5 rejected (verified false or out of scope). See the Review Triage Log above for the full list and reasoning.

**Follow-up review recommendation:** `true` — one patched finding was high severity (the stage/image crop-rectangle misalignment).

**Verification performed:**
- `npm --prefix apps/web test -- --run scan error-code-parity` — pass.
- `uv run --project apps/api pytest apps/api/tests/test_scan_submission.py` — 26/26 pass.
- `make lint` — clean (ruff check + format, oxlint, tsc --noEmit).
- Full `apps/api` pytest suite (all 42 files, run in batches due to per-file ephemeral-Postgres startup cost exceeding a single 10-minute tool call) — all pass, independently re-verified after the review patches.
- Full `shared/vision` pytest suite — pass, independently re-verified.
- Full `apps/web` vitest suite — 1608/1608 pass, independently re-verified.
- I/O & Edge-Case Matrix audit: all 5 rows covered by tests that ran and passed (happy path, degenerate rect, oversized/unreadable image, signed-out, submission failure).

**Residual risks:**
- Manual on-device drag testing (desktop Chrome + a mobile browser) was not performed — no device available in this environment. Flagged in the spec's own Verification section as a pre-existing gap jsdom cannot close.
- The default 10%-inset "best-guess" selection is a fixed heuristic, not derived from any tile-detection signal — acceptable per the spec's own Never clause (no crop-detection ML in this story).
- Eight low-severity items deferred (see frontmatter `deferred:` and the Review Triage Log) — none blocking, none affecting the shipped ACs.
