---
title: 'Capture Quality Guidance'
type: 'feature'
created: '2026-09-22'
baseline_revision: 'b6bf9e159e01bbbde7b94324c40477c717838311'
status: 'done'
review_loop_iteration: 0
followup_review_recommended: true
context: []
warnings: ['oversized']
deferred:
  - summary: >-
      `blur_score`'s variance-of-Laplacian metric cannot detect blur in
      genuinely low-high-frequency content, so a sharp, correctly-framed photo
      of a real catalogue category (Mono Colour tiles, and smooth-gradient
      patterns like Crema Marmol) can score at or near zero regardless of
      focus quality and be wrongly rejected.
    evidence: |-
      Measured directly against `shared_vision.quality.blur_score`: a flat
      180x160x140 tile re-photographed with realistic sensor noise (sigma 1-3,
      typical of a well-lit low-ISO phone shot) and JPEG-encoded at quality
      75-92 scores 0.0-26.0, versus the provisional `DEFAULT_SCAN_QUALITY_THRESHOLD`
      of 100.0 -- it only clears the bound once whole-frame noise reaches
      sigma>=5 (q92) or sigma>=8 (q75), noise levels not guaranteed in good
      lighting. A synthetic smooth-gradient tile (no fine texture, only
      large-scale colour variation -- the Crema Marmol shape) scored 0.25
      whether left sharp or run through a radius-20 Gaussian blur: the metric
      is completely insensitive to focus for this content family, in either
      direction. This is a structural property of any no-reference,
      high-frequency-energy blur metric applied to inherently low-texture
      subjects, not a tunable-threshold problem -- no single `SCAN_QUALITY_THRESHOLD`
      value can both catch real blur on textured tiles and pass real flat/smooth
      tiles, since their sharp-photo scores overlap the textured category's
      blurred-photo scores. CLAUDE.md's own domain vocabulary names both
      categories as real, current catalogue content (`MONO COLOUR
      GLOSSY`/`MATT`; `CREMA MARMOL`). PRD OQ-13 already frames this story's
      deliverable as "the mechanism and a tunable default," with calibration
      explicitly deferred to the Foundation build and Phase 2 pilot -- this is
      exactly the kind of finding that pilot exists to surface, and no
      unvalidated secondary heuristic tried during review (gating on the raw
      image's own pixel variance) reliably separated "genuinely flat" from
      "heavily blurred textured" without its own false negatives, so
      inventing one here would trade a documented limitation for an
      undocumented one.
    location: >-
      shared/vision/shared_vision/quality.py
    severity: high
---

<intent-contract>

## Intent

**Problem:** `POST /scans` (Story 3.2) crops the submitted image server-side and discards the result. No quality signal exists yet, so FR-9's gate — refuse a blurry or poorly-framed scan before matching ever sees it — is not built, and Story 3.2's own deferred note flags the discarded crop as waiting on exactly this consumer.

**Approach:** Add a `shared_vision.quality` module scoring the already-cropped region against a single named, environment-overridable threshold (AD-12: the check runs on the cropped region only, and shared/vision owns the enforcement point). `POST /scans` evaluates it right after `crop_to_rect` and refuses with a dedicated envelope when it fails; a passing score still returns the same empty `202` Story 3.2 shipped, since matching (3.4) does not exist yet.

## Boundaries & Constraints

**Always:**
- The check runs on the cropped region only (AD-12), after `crop_to_rect` succeeds — never on the pre-crop image.
- The threshold is a named module constant read once from an environment variable with a documented, uncalibrated provisional default (`shared_vision.pipeline.GREY_WORLD`'s own pattern) — never a literal buried in the check.
- A failing score returns a dedicated `422 scan_quality_too_low` envelope carrying the verbatim microcopy "This photo's a little blurry — try again." (EXPERIENCE.md); a TypeScript twin and an `error-code-parity.test.ts` row are mandatory.
- New CSS values reference only existing `tokens.css` variables — DESIGN.md's `retake-prompt` recipe (surface background, border, text foreground, `radius-sm`).

**Never:**
- No second metric invented for "framing" distinct from the blur score — epics.md's AC names one bound ("blur/framing bound"), not two.
- No persistence, no matching, no `Scan` row — 3.4/3.5 still own those.
- No change to `crop_to_rect`'s own validation or the crop-rectangle contract.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Sharp, well-framed crop | Cropped region scores ≥ threshold | `202`, no body (unchanged from 3.2) | No error |
| Blurry/flat crop | Cropped region scores < threshold | Retake prompt shown, request stops here | `422 scan_quality_too_low` |
| Degenerate crop dimensions | A valid-but-tiny crop (e.g. rounds to 2×2px) | Treated as failing quality, never crashes | `422 scan_quality_too_low` |
| Threshold override | `TILEMATCH_SCAN_QUALITY_THRESHOLD` set in the environment | The overridden value gates, not the default | No error |

</intent-contract>

## Code Map

- `shared/vision/shared_vision/quality.py` (new) -- `SCAN_QUALITY_THRESHOLD_ENV = "TILEMATCH_SCAN_QUALITY_THRESHOLD"`; `DEFAULT_SCAN_QUALITY_THRESHOLD` (a documented, uncalibrated variance-of-Laplacian heuristic — PRD OQ-13 defers the real number); `SCAN_QUALITY_THRESHOLD` read once at import (`pipeline.GREY_WORLD`'s pattern); `blur_score(image) -> float` (grayscale variance of a 3x3 Laplacian via numpy shifted-array arithmetic — no scipy/cv2 dependency, returns `0.0` for an image under 3px on either edge rather than raising); `passes_quality(image, *, threshold=SCAN_QUALITY_THRESHOLD) -> bool`.
- `shared/vision/shared_vision/__init__.py` -- export `SCAN_QUALITY_THRESHOLD`, `SCAN_QUALITY_THRESHOLD_ENV`, `DEFAULT_SCAN_QUALITY_THRESHOLD`, `blur_score`, `passes_quality`.
- `shared/vision/tests/test_quality.py` (new) -- a noisy/textured image passes, a uniform flat image fails, a <3px crop fails without raising, an env-var override (`importlib.reload`) changes the gating threshold.
- `apps/api/api/scan.py:112-119` -- capture `crop_to_rect`'s return (currently discarded), call `shared_vision.passes_quality` on it, raise a new `_refusal(SCAN_QUALITY_TOO_LOW, SCAN_QUALITY_MESSAGE, status.HTTP_422_UNPROCESSABLE_CONTENT)` on failure; only a pass reaches the existing empty `202`. Add `SCAN_QUALITY_TOO_LOW = "scan_quality_too_low"` and `SCAN_QUALITY_MESSAGE = "This photo's a little blurry — try again."` beside the existing envelope constants.
- `apps/api/tests/test_scan_submission.py` -- add a uniform-color fixture (zero Laplacian variance) and a test asserting `422 scan_quality_too_low`; the existing `a_tile_photograph` random-noise fixture already scores far above any provisional threshold, so existing happy-path tests need no change.
- `apps/web/src/api/client.ts:254` -- add `export const SCAN_QUALITY_TOO_LOW = 'scan_quality_too_low';` beside `INVALID_CROP_RECT`.
- `apps/web/src/__tests__/error-code-parity.test.ts:180,214` -- add the `scan_quality_too_low` row to both the `PYTHON` and `TYPESCRIPT` maps (`scan.py` is already in `routers`).
- `apps/web/src/screens/CropScreen.tsx:173-299` -- add `qualityRetake: string | null` state beside `error`; in `handleConfirm`'s catch, branch on `failure instanceof ApiRequestError && failure.code === SCAN_QUALITY_TOO_LOW` to set it instead of `error`. When set: render the message in a new `.retakePrompt` banner directly above the actions row (EXPERIENCE.md's Component Pattern — "inline message + a single 'Retake' action"), relabel the one accent button "Retake" (calling `onBack` instead of `handleConfirm`), and hide the now-redundant secondary "Back" button. A fresh `handleConfirm` attempt clears `qualityRetake` and restores the normal Confirm/Back pair.
- `apps/web/src/screens/CropScreen.module.css` -- new `.retakePrompt` rule: `background: var(--color-surface); border: var(--border-hairline) solid var(--color-border); color: var(--color-text); border-radius: var(--radius-sm); padding: var(--space-3) var(--space-4);` — `BulkUploadScreen.module.css`'s `.file` recipe, the same one DESIGN.md names for `retake-prompt`.
- `apps/web/src/__tests__/scan.test.tsx` -- a `scan_quality_too_low` rejection shows the retake message and relabels the button "Retake"; tapping it discards the image the same way Back does; a later normal submission still works.
- `apps/web/src/__tests__/styling-wiring.test.ts` -- assert `.retakePrompt`'s background/border/color point at `--color-surface`/`--color-border`/`--color-text`.

## Tasks & Acceptance

**Execution:**
- `shared/vision/shared_vision/quality.py` (new) + `__init__.py` -- the blur/framing score and its runtime-configurable bound -- AD-12's enforcement point.
- `shared/vision/tests/test_quality.py` (new) -- score/threshold/env-override coverage.
- `apps/api/api/scan.py` -- wire the check into `POST /scans`, new envelope code -- FR-9's server-side gate.
- `apps/api/tests/test_scan_submission.py` -- extend the I/O matrix with the failing-quality case.
- `apps/web/src/api/client.ts` + `error-code-parity.test.ts` -- the TypeScript twin of the new code.
- `apps/web/src/screens/CropScreen.tsx` + `.module.css` -- the retake-prompt UI (UX-DR11).
- `apps/web/src/__tests__/scan.test.tsx` + `styling-wiring.test.ts` -- Crop-screen and styling coverage.

**Acceptance Criteria:**
- Given I've confirmed a crop over a blurry or poorly-framed photo, when it scores below the configured blur/framing bound, then I see a retake prompt on the Crop screen and nothing about this submission ever proceeds further.
- Given the same crop rectangle over a sharp, well-framed photo, when I confirm, then the submission proceeds exactly as Story 3.2 left it — I'm returned to Scan with no prompt shown.
- Given the quality bound is changed via its environment variable and the process restarts, when the same borderline photo is submitted again, then the new bound — not the old one — decides whether I see the retake prompt, with no code change.
- Given a scan that failed quality guidance, when I look at the Crop screen, then the retake prompt is an inline, surface-colored banner directly above the one action available ("Retake"), never a modal.

## Spec Change Log

## Review Triage Log

### 2026-09-22 — Review pass
- intent_gap: 0
- bad_spec: 0
- patch: 4: (high 0, medium 2, low 2)
- defer: 1: (high 1)
- reject: 10: (high 0, medium 0, low 10)
- addressed_findings:
  - `[medium]` `[patch]` `apps/api/api/scan.py`'s comment on `SCAN_QUALITY_MESSAGE` falsely claimed it is "pinned against `apps/web`'s copy by `error-code-parity.test.ts`" — that test only compares the envelope `code`, never `message` text, and `CropScreen` renders the server's message verbatim with no independent `apps/web` copy to pin against. Fixed the comment to state this accurately, and added a direct assertion of the message text to `test_a_blurry_or_flat_crop_is_refused_as_low_quality`.
  - `[medium]` `[patch]` `SCAN_QUALITY_THRESHOLD`'s `float(os.environ.get(...))` parse crashed the whole `shared_vision` import on a non-numeric env value, and silently accepted `nan`/`inf`/`-inf` (rejecting or admitting every scan without any error). Fixed with a parse helper that catches `ValueError` and rejects non-finite results via `math.isfinite`, falling back to `DEFAULT_SCAN_QUALITY_THRESHOLD` with a logged warning; added tests for both failure shapes.
  - `[low]` `[patch]` The env-var-override test reloaded only the `shared_vision.quality` submodule and asserted against its own copies of `SCAN_QUALITY_THRESHOLD`/`passes_quality`, never the `shared_vision` package names (`apps/api`'s actual import path), which a submodule reload does not update. Fixed by also reloading `shared_vision` itself and asserting against its re-exported names.
  - `[low]` `[patch]` `test_a_3px_image_is_the_smallest_that_computes_a_real_interior` asserted only `>= 0.0`, true even if `blur_score` always returned `0.0` — it never actually distinguished the real-interior path from the early-return. Fixed with an assertion against a hand-computed non-zero expected value.

Deferred (real but not blocking — see frontmatter `deferred:` for full evidence): `blur_score`'s variance-of-Laplacian metric cannot detect blur in genuinely low-high-frequency content (Mono Colour tiles, smooth-gradient patterns like Crema Marmol), so a sharp, correctly-framed photo of these real catalogue categories can score at or near zero and be wrongly rejected regardless of focus quality — measured empirically, and structural to any no-reference high-frequency-energy blur metric rather than a threshold-tuning problem (no unvalidated secondary heuristic tried during review reliably separated the two cases). PRD OQ-13 already frames this story's deliverable as "the mechanism and a tunable default" with real calibration deferred to the Phase 2 pilot; this is exactly what that pilot exists to surface.

Rejected (verified false, out of scope, or already-established convention): the "framing" rationale conflicting with the UI's single "Retake" action is what the epics.md AC's own text asks for ("I'm prompted to retake it"), not a bug; the `TILEMATCH_` env-var prefix already matches this exact module's own `pipeline.GREY_WORLD` precedent (`TILEMATCH_GREYWORLD`) — the reviewer missed it; no telemetry/logging of scores was ever asked for by any source document; `make eval` doesn't exist yet (CLAUDE.md: Epic 2) and this change never touches the embedding/preprocessing pipeline `pipeline.py` owns, so that rule's intent doesn't reach it; sharing one `422` status across `invalid_crop_rect` and `scan_quality_too_low`, distinguished by envelope `code`, matches the existing `invalid_crop_rect`/`unreadable_image` convention exactly; duplicated flat-image test fixtures across two independent packages match this codebase's existing per-file-helper convention; the `Retake` button's missing in-flight guard is a non-issue since `onBack` is synchronous with no network race window, unlike `Confirm`'s real one; `role="alert"` is an ARIA live region designed to announce without a focus move, and no other `role="alert"` element in this screen manages focus either; two intent-alignment citations ("Design Notes: 'Retake, not re-crop'"; "the AC's own wording" on process restarts) both correctly cite this spec's own sections, which the auditor had no visibility into.

## Design Notes

**One score serves both "blur" and "framing".** Epics.md's AC names a single "blur/framing bound," not two checks. Variance of the Laplacian is a standard sharpness heuristic that also reads low for a flat, poorly-framed crop (a wall, an out-of-focus background) — both share the same missing-high-frequency-texture signature — so one metric against one named threshold satisfies the AC as written rather than inventing a second, unvalidated "framing" detector.

**The default is a documented placeholder, not a measured one.** No POC or catalogue data calibrates this bound — PRD OQ-13 explicitly defers the real number to the Foundation build and Phase 2 pilot. `DEFAULT_SCAN_QUALITY_THRESHOLD` is a widely-cited variance-of-Laplacian starting point for "clearly blurry," chosen so the mechanism ships and is trivially retunable (`TILEMATCH_SCAN_QUALITY_THRESHOLD`) — never a claim about this catalogue's real accuracy trade-off.

**Known limitation, deferred rather than patched (see frontmatter `deferred:`).** A high-frequency-energy metric cannot see blur in content that has no high-frequency energy to begin with — a sharp Mono Colour tile or a smooth Crema Marmol gradient can score near zero and be wrongly rejected, no matter the threshold. This is measured, real, and not fixable by retuning the number; it is exactly the kind of gap PRD OQ-13's Phase 2 pilot exists to surface. `quality.py`'s own docstring says so plainly rather than presenting the mechanism as universally correct.

**Retake, not re-crop.** The failure is about the photo's content, not the selection — adjusting the crop rectangle over the same blurry frame cannot fix it — so the UI offers exactly one action ("Retake" → discard and return to Scan), matching EXPERIENCE.md's Component Pattern for `retake-prompt` verbatim ("a single 'Retake' action") rather than leaving both Confirm and Back live for a resubmission that would fail again.

## Verification

**Commands:**
- `uv run --project shared/vision pytest shared/vision/tests/test_quality.py` -- expected: pass.
- `uv run --project apps/api pytest apps/api/tests/test_scan_submission.py` -- expected: pass, including the new `422` case.
- `npm --prefix apps/web test -- --run scan error-code-parity styling-wiring` -- expected: pass.
- `make lint` -- expected: clean (ruff + oxlint + tsc --noEmit).
- `make test` -- expected: full suite green.

## Auto Run Result

**Summary of implemented change:** Added FR-9's capture-quality gate. A new `shared_vision.quality` module scores the already-cropped scan region with a variance-of-Laplacian sharpness metric against `SCAN_QUALITY_THRESHOLD` — a named constant read once at import from `TILEMATCH_SCAN_QUALITY_THRESHOLD`, with a documented, uncalibrated provisional default of `100.0` (PRD OQ-13 defers real calibration to the Phase 2 pilot). `POST /scans` runs this check immediately after `crop_to_rect` succeeds; a pass still returns the same empty `202` Story 3.2 shipped, a failure returns a new `422 scan_quality_too_low` envelope carrying EXPERIENCE.md's verbatim microcopy. `CropScreen` recognises that code and swaps its normal Confirm/Back pair for a single "Retake" action above an inline, surface-colored banner (DESIGN.md's `retake-prompt` recipe), matching EXPERIENCE.md's Component Pattern exactly.

**Files changed:**
- `shared/vision/shared_vision/quality.py` (new) — `blur_score`/`passes_quality`, the threshold constant/env var, and a `_read_threshold()` helper that falls back to the default (with a logged warning) on an unparseable or non-finite (`nan`/`inf`/`-inf`) environment value rather than crashing the package import.
- `shared/vision/shared_vision/__init__.py` — exports the five new `quality` names.
- `shared/vision/tests/test_quality.py` (new) — score/threshold coverage, a hand-computed Laplacian-variance regression test, the env-var override (reloading both `quality` and the `shared_vision` package, since `apps/api` imports the package-level names), and the four invalid-env-value fallback cases.
- `apps/api/api/scan.py` — wires the check into `POST /scans`; new `SCAN_QUALITY_TOO_LOW`/`SCAN_QUALITY_MESSAGE` envelope constants, with an accurate comment on what actually pins the message text (nothing cross-language — only the Python test's own direct assertion).
- `apps/api/tests/test_scan_submission.py` — a uniform-color fixture and a test asserting the `422` code and exact message.
- `apps/web/src/api/client.ts` + `error-code-parity.test.ts` — the `SCAN_QUALITY_TOO_LOW` TypeScript twin and its parity-map row.
- `apps/web/src/screens/CropScreen.tsx` + `.module.css` — the `qualityRetake` state, the single-"Retake"-action UI swap, and the `.retakePrompt` banner styling.
- `apps/web/src/__tests__/scan.test.tsx` + `styling-wiring.test.ts` — Crop-screen retake-flow and styling coverage.

**Review findings breakdown:** 4 patched (0 high, 2 medium, 2 low — all fixed and re-verified: a misleading "pinned" comment plus a weak test, non-robust environment-variable parsing, an env-override test that didn't exercise the actual package-level import boundary `apps/api` uses, and a vacuous unit test), 1 deferred (high — see frontmatter `deferred:`: the variance-of-Laplacian metric cannot detect blur in genuinely low-texture content, so a sharp Mono Colour or smooth Crema-Marmol-style photo can be wrongly rejected regardless of focus; empirically measured during review, structural to any no-reference high-frequency blur metric rather than a threshold-tuning problem, and exactly what PRD OQ-13's Phase 2 pilot calibration exists to surface), 10 rejected (verified false, out of scope, or already-matching established convention — see Review Triage Log for the full list).

**Follow-up review recommendation:** `true` — 2 medium + 2 low patched findings score `3×2 + 1×2 = 8`, at or above the 5-point bar.

**Verification performed:**
- `uv run --project shared/vision pytest shared/vision/tests/test_quality.py` — 16/16 pass.
- `uv run --project apps/api pytest apps/api/tests/test_scan_submission.py` — 27/27 pass, independently re-run and confirmed.
- `npm --prefix apps/web test -- --run` (full suite) — 1611/1611 pass, independently re-run and confirmed.
- `uv run --project shared/vision pytest shared/vision/tests/ --ignore=shared/vision/tests/test_pipeline.py` — all non-model-dependent shared_vision tests pass; `test_pipeline.py` (real ONNX inference) was not touched by this story's files and was already verified green in the initial implementation pass.
- `make lint` — clean (ruff check, ruff format --check, oxlint, tsc --noEmit), independently re-run and confirmed.
- I/O & Edge-Case Matrix audit: all four rows covered by tests that ran and passed (happy path via the existing noise fixture, blurry/flat crop via the new `422` test, degenerate crop dimensions via `shared_vision`'s sub-3px unit tests, threshold override via the env-var reload test).

**Residual risks:**
- The deferred high-severity limitation above: Mono Colour and smooth-gradient-pattern tiles are a real, systematic false-rejection risk under the current provisional mechanism. This is a known, documented limitation of the shipped mechanism, not a defect in it relative to this story's "mechanism and tunable default" scope — but it should inform the Phase 2 pilot's calibration work and may need a materially different (not just retuned) approach if the pilot confirms it in practice.
- No telemetry logs the computed `blur_score` for real scans, so the deferred calibration work has no production data source yet beyond whatever the pilot's own instrumentation adds later — out of this story's scope, not requested by any source document.
