---
title: 'Capture or Upload a Scan'
type: 'feature'
created: '2026-09-22'
baseline_revision: '13efb4b38f621bdf28915f2c0e6f0122a2272c2c'
status: 'done'
review_loop_iteration: 0
followup_review_recommended: true
context: []
warnings: ['oversized']
deferred:
  - summary: >-
      The upload path has no file-size/dimension guard before decoding a chosen file.
    evidence: |-
      `chooseFile` in ScanScreen.tsx hands whatever file the user picks straight to
      `createImageBitmap`/canvas with no size check, so an unusually large photo-library
      pick could hang or strain a mobile tab's memory before the ~1024px downscale ever
      runs. No AC or I/O-matrix row in this story covers file size, and typical phone
      camera photos are far below any risky threshold, so this is a hardening item
      rather than a defect in the shipped scenarios.
    location: apps/web/src/screens/ScanScreen.tsx (chooseFile)
    severity: low
  - summary: >-
      Nothing detects the camera track ending or being revoked externally mid-session.
    evidence: |-
      If the OS/browser revokes camera access or the hardware disconnects while
      `cameraState` is `'granted'`, the viewfinder would show a frozen/black frame with
      no state change and no user-facing message. EXPERIENCE.md's State Patterns table
      doesn't call for this case, and it's rare in practice.
    location: apps/web/src/screens/ScanScreen.tsx (enableCamera)
    severity: low
---

<intent-contract>

## Intent

**Problem:** Staff and Administrators have no way to start a tile scan yet — there is no Scan surface, no live-camera capture, and no upload fallback, so nothing exists to feed Epic 3's crop/match pipeline (Stories 3.2–3.4).

**Approach:** Add a "Scan" entry point to the home panel, reachable by every authenticated role, showing a live camera viewfinder with an on-screen framing guide plus an always-visible "Choose a photo" fallback. Both paths run through one shared downscale step and hand off to a new minimal "Crop" screen — a placeholder Story 3.2 will turn into the real crop editor.

## Boundaries & Constraints

**Always:**
- Camera capture and file upload converge on one shared downscale function (canvas-based, long edge capped at 1024px) before either produces the image the Crop screen receives — that convergence is the whole meaning of "equivalent submission" in the AC.
- Explain why camera access is needed (inline copy) before calling `getUserMedia` — never let the native permission prompt fire unprompted on mount (EXPERIENCE.md State Patterns: "Camera permission not yet granted").
- "Choose a photo" stays visible and usable regardless of camera permission state (EXPERIENCE.md Accessibility Floor: camera denial is never a dead end).
- The framing guide is a decorative overlay only (`framing-guide-overlay` token: accent outline, transparent fill) — no blur/framing analysis; that is Story 3.3.
- Follow existing idioms exactly: extend `App.tsx`'s `Section`/`Screen` union plus `reachableBy`/`currentScreen`, one CSS module per screen sourced only from `tokens.css`, and make "Scan" the home panel's one `--color-accent` control (DESIGN.md names "Scan" itself as an accent-button example) — Users/Audit/Catalogue keep their existing secondary/navy-outline treatment unchanged.

**Block If:** none — no decision here needs a human.

**Never:**
- Never build the free-form crop selector, drag handles, the normalized 0–1 crop rectangle, the blur/framing check, the "Confirm Crop" action, or any backend endpoint — all later Epic 3 stories.
- Never add a persistent nav/tab bar. `AppShell` already documents that real nav arrives once enough surfaces exist (Scan + History); this story adds only the Scan surface, as a home-panel door in the same pattern Users/Audit/Catalogue used before their own nav landed.
- Never reject a selected file by extension or MIME type before use — only a genuine browser decode failure is an error.
- Never touch or reimplement anything in `shared/vision/`; the client-side ~1024px downscale is a separate, client-only bandwidth step, not the index/query embedding pipeline.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|---|---|---|---|
| Live capture happy path | Camera granted, shutter tapped | Frame downscaled (long edge ≤1024px); Crop screen shows it | — |
| Upload happy path | A valid image file chosen | Same downscale; Crop screen shows it | — |
| Permission not yet requested | Scan screen mounts | Explanatory copy + "Enable camera"; no native prompt yet; upload fallback visible | — |
| Permission denied | User denies or denied previously | Viewfinder replaced by denial copy; upload fallback still usable | Never a dead end |
| Chosen file isn't a decodable image | Renamed/corrupt file | Inline error; user can pick another file | Never a crash or blank screen |
| Back from Crop | Crop screen showing an image | Returns to Scan; held image discarded | — |

</intent-contract>

## Code Map

- `apps/web/src/App.tsx:48-172` -- `Section`/`Screen` unions, `reachableBy`, `currentScreen`; extend with `'scan'`/`'crop'`. `reachableBy`'s default `return true` already covers both — do not add them to the admin-only list.
- `apps/web/src/App.tsx:194-219` -- `Gate`'s state; add `capturedImage: Blob | null` beside `editingTile`, same clear-on-sign-out (`~267-278`) and clear-on-role-loss (`~314-325`) treatment.
- `apps/web/src/App.tsx:416-461` -- `showSection`/`showEditTile` pattern to mirror for a new `showCrop(image: Blob)`: set the image, then the section (batches in one render, avoids the fallback-to-Scan flash `currentScreen` would otherwise produce for one frame).
- `apps/web/src/App.tsx:692-754` -- home panel JSX; add the Scan door here, outside the `user.role === 'admin'` block (`728-753`) so both roles see it; give it its own accent class in `App.module.css`, not `.userList`'s pattern (those three are deliberately non-accent secondary buttons per their own comments).
- `apps/web/src/components/AppShell.tsx:28-32` -- confirms nav is intentionally deferred until enough surfaces exist; do not add a tab bar here.
- `apps/web/src/screens/AddTileScreen.tsx:62-65` -- precedent for "content decides, never extension" — apply the same spirit to the upload picker (accept image files, but only a decode failure is an error).
- `_bmad-output/planning-artifacts/ux-designs/ux-rcl_camera_app-2026-09-08/DESIGN.md:120-124,163-164,216` -- `framing-guide-overlay` token block, accent-button rule ("Scan" cited by name), overlay visual spec.
- `_bmad-output/planning-artifacts/ux-designs/ux-rcl_camera_app-2026-09-08/EXPERIENCE.md` State Patterns ("Camera permission not yet granted"), Accessibility Floor, Interaction Primitives ("Both lead to the same Crop step") -- source of the AC language above.
- `_bmad-output/planning-artifacts/ux-designs/ux-rcl_camera_app-2026-09-08/mockups/key-scan.html` -- illustrative viewfinder/controls markup (`.frame-guide`, `.controls` grid, `.choose-photo`, `.shutter`); the spine docs above win on conflict.
- `apps/web/src/styles/tokens.css` -- the only file allowed a literal value; new CSS must reference its `var(--…)` tokens (`no-raw-values.test.ts`, `tokens.test.ts` enforce this).
- `apps/web/src/__tests__/add-tile.test.tsx:147` -- `new File([bytes], name, {type})` helper pattern to reuse for the upload test.
- `apps/web/src/__tests__/auth-gating.test.tsx` -- existing pattern for "does this screen require a session" tests.
- `apps/web/vite.config.ts:33-38` -- vitest config: `environment: 'jsdom'`, no canvas polyfill — `HTMLCanvasElement.getContext`/`toBlob` need mocking in tests.
- `apps/web/src/api/client.ts` -- confirmed no scan-related call is needed for this story; nothing here changes.
- `shared/vision/shared_vision/pipeline.py:51` (`DECODE_MAX_EDGE = 2048`) -- read-only context: server-side cap, unrelated to and not to be confused with the client's 1024px bandwidth downscale.

## Tasks & Acceptance

**Execution:**
- `apps/web/src/scan/downscaleImage.ts` -- add `computeDownscaledDimensions(width, height, maxEdge = 1024)` (pure) and `downscaleToBlob(source, width, height)` (canvas draw + `toBlob`, `image/jpeg`, quality 0.9) -- one function both capture and upload call, so their output is identical by construction.
- `apps/web/src/screens/ScanScreen.tsx` + `.module.css` -- live viewfinder via `getUserMedia` (requested only after an explicit "Enable camera" tap), framing-guide overlay, shutter control, always-visible file input fallback, permission-denied and decode-failure states; both paths call `downscaleImage` then `onCaptured(blob)`.
- `apps/web/src/screens/CropScreen.tsx` + `.module.css` -- minimal placeholder: full-bleed image via `URL.createObjectURL(image)` (revoked on unmount), one secondary "Back" control, no accent button.
- `apps/web/src/App.tsx` -- wire `'scan'`/`'crop'` sections/screens, `capturedImage` state, `showCrop`, the home-panel Scan door (per Code Map above).
- `apps/web/src/App.module.css` -- add the Scan door's accent-button rule.
- `apps/web/src/__tests__/scan.test.tsx` -- reachability (both roles), permission-not-yet-requested copy before any `getUserMedia` call, capture-then-Crop, upload-then-Crop with an identical resulting screen, decode-failure inline error, Back-from-Crop discards the image.
- `apps/web/src/__tests__/downscale-image.test.ts` -- `computeDownscaledDimensions` for portrait/landscape/already-under-1024px inputs; `downscaleToBlob` smoke test against mocked `HTMLCanvasElement`.

**Acceptance Criteria:**
- Given I am authenticated (Staff or Admin), when I view the home panel, then a "Scan" control is present and is the panel's one accent-styled action.
- Given camera access has not yet been requested, when the Scan screen renders, then explanatory copy is shown and no native permission prompt has fired.
- Given I grant camera access, when I tap the shutter, then a framing-guide overlay was visible over the live viewfinder beforehand, and the captured, downscaled (≤1024px long edge) frame is what the Crop screen receives.
- Given I deny (or have denied) camera access, when I view Scan, then "Choose a photo" remains visible and usable.
- Given I choose a decodable image file, when selection completes, then the same downscale runs and Crop shows it — indistinguishable from the capture path except for the source image.
- Given I choose a file that fails to decode as an image, when selection completes, then an inline error appears and I can choose another file.
- Given I am on Crop, when I press Back, then I return to Scan and the held image is discarded.

## Spec Change Log

## Review Triage Log

### 2026-09-22 — Review pass
- intent_gap: 0
- bad_spec: 0
- patch: 9: (high 2, medium 4, low 3)
- defer: 2: (high 0, medium 0, low 2)
- reject: 4: (high 0, medium 0, low 4)
- addressed_findings:
  - `[high]` `[patch]` Live camera never actually appears: `enableCamera` sets `videoRef.current.srcObject` before `setCameraState('granted')`, but `<video>` only mounts in the `'granted'` branch, so the ref is always `null` at assignment time and the stream is never bound. Fixed by binding the stream once the video element exists (post-render), not synchronously inside `enableCamera`.
  - `[high]` `[patch]` Uploaded phone photos could decode with the wrong orientation: `createImageBitmap(file)` was called with no `imageOrientation` option. Fixed by passing `{ imageOrientation: 'from-image' }` explicitly.
  - `[medium]` `[patch]` `capture()` could encode a 0×0 frame if the shutter is tapped before video metadata loads. Fixed by guarding on `videoWidth`/`videoHeight` being non-zero.
  - `[medium]` `[patch]` A camera stream could leak open (never stopped) if the component unmounts while `getUserMedia` is still pending. Fixed by tracking mounted state and stopping tracks immediately if the promise resolves after unmount.
  - `[medium]` `[patch]` `ScanScreen` had no way back to the home panel, unlike every other home-panel-reached screen. Added an `onBack` prop wired to the home panel, matching the Audit/Catalogue pattern.
  - `[medium]` `[patch]` A `downscaleToBlob` rejection (no 2D context, or `toBlob` yielding `null`) was an unhandled promise rejection with no on-screen feedback in both `capture()` and `chooseFile()`. Fixed with try/catch and an inline error.
  - `[low]` `[patch]` No guard against a double-tap on Capture racing two concurrent captures. Fixed by disabling Capture while one is in flight.
  - `[low]` `[patch]` `CropScreen`'s object URL was created inside `useMemo`, which React does not guarantee against discarding/recomputing. Moved creation into the same `useEffect` that revokes it.
  - `[low]` `[patch]` No CSS accent-budget test existed for `ScanScreen.module.css`/`CropScreen.module.css`, unlike every other screen with `--color-accent` usage. Added matching `styling-wiring.test.ts` blocks.

## Design Notes

**Scan is the accent action, doors stay secondary.** DESIGN.md's Colors section names "Scan" itself as an accent-button example, and every existing home-panel comment (`App.module.css` `.userList`/`.auditLog`/`.catalogue`) explains that those three are deliberately *not* accent because "the home panel's job is not user management" — implying scanning is. Giving Scan the one `--color-accent` fill on the panel is therefore not a new call, just the one DESIGN.md always pointed at.

**Crop is intentionally inert.** It shows the handed-off image and a Back control and nothing else — no "Confirm Crop," which DESIGN.md reserves as Story 3.2's own accent action. Adding a placeholder confirm now would both violate "one accent per screen" ahead of schedule and hand Story 3.2 a control to rip out rather than one to build.

**Permission sequencing.** `getUserMedia` is called only from an explicit "Enable camera" tap, never on mount, so the explanatory copy always precedes the browser's native prompt regardless of past grants — simpler and more robust across browsers than feature-detecting the Permissions API (unsupported in Safari) to skip the explanation when already granted.

## Verification

**Commands:**
- `npm --prefix apps/web test -- --run scan downscale-image` -- expected: new tests pass.
- `make lint` -- expected: clean (ruff + oxlint + tsc --noEmit).
- `make test` -- expected: full suite green, including `styling-wiring`, `no-raw-values`, `tokens` and `error-code-parity` (unaffected by this story).

**Manual checks (if no CLI):**
- jsdom cannot exercise a real camera stream; smoke-test `getUserMedia` capture and the upload fallback in an actual browser (desktop Chrome plus one mobile browser) before calling this done.

## Auto Run Result

**Summary:** Added the Scan surface (Story 3.1): a home-panel "Scan" door reachable by every authenticated role, a live-camera viewfinder with a decorative framing-guide overlay and an always-visible "Choose a photo" fallback, both converging through one shared client-side downscale step (long edge capped at 1024px) onto a new, deliberately inert "Crop" placeholder screen that Story 3.2 will turn into the real crop editor.

**Files changed:**
- `apps/web/src/screens/ScanScreen.tsx` (new) -- live-camera capture + upload fallback screen; permission sequencing, decode/downscale failure handling, Back to home.
- `apps/web/src/screens/ScanScreen.module.css` (new) -- Scan's styles, token-only.
- `apps/web/src/screens/CropScreen.tsx` (new) -- inert placeholder: shows the handed-off image, Back to Scan.
- `apps/web/src/screens/CropScreen.module.css` (new) -- Crop's styles, token-only, accent-free.
- `apps/web/src/scan/downscaleImage.ts` (new) -- `computeDownscaledDimensions` (pure) + `downscaleToBlob` (canvas draw/encode), the one function both capture and upload call.
- `apps/web/src/App.tsx` (modified) -- `'scan'`/`'crop'` sections/screens, `capturedImage` state, `showCrop`, the home-panel Scan door.
- `apps/web/src/App.module.css` (modified) -- `.scan`'s accent-button rule; corrected a now-stale comment on `.catalogue` claiming the file held zero accent uses.
- `apps/web/src/styles/tokens.css` (modified) -- two derived tokens (`--viewfinder-min-height`, `--framing-guide-border-width`) not in DESIGN.md's frontmatter but not contradicting it.
- `apps/web/src/__tests__/scan.test.tsx` (new) -- covers every I/O-matrix row plus the post-review fixes (srcObject binding, Back, 0×0 guard).
- `apps/web/src/__tests__/downscale-image.test.ts` (new) -- unit + smoke tests for the shared downscale module.
- `apps/web/src/__tests__/styling-wiring.test.ts` (modified) -- extended for Scan's home-panel accent, and new accent-budget blocks for `ScanScreen.module.css`/`CropScreen.module.css`.
- `_bmad-output/implementation-artifacts/epic-3-context.md` (new) -- compiled Epic 3 planning context (this story's prerequisite, per step-01).

**Review findings breakdown:** 9 patched (2 high, 4 medium, 3 low — see Review Triage Log above for detail), 2 deferred (upload file-size guard; camera-track-ended detection — both low severity, both logged in frontmatter `deferred`), 4 rejected as noise (a factually incorrect claim about `baseline_revision`'s length; a suggested "retry" control that would contradict EXPERIENCE.md's explicit fallback-only design; folding distinct `getUserMedia` failure reasons into one message, which matches EXPERIENCE.md's own stated behavior; an unexplained-`oversized`-flag nitpick against a field designed to be a terse machine signal).

**Follow-up review recommendation:** `true` — this pass patched 2 high-severity findings (any high severity alone triggers `true`, independent of the `3×medium + 1×low` score, which was 4×3 + 1×3 = 15 here).

**Verification performed:**
- `npm --prefix apps/web test -- --run scan downscale-image` -- pass (22 tests), both before and after the patch round.
- `make lint` -- pass (ruff check, ruff format --check, oxlint --deny-warnings, tsc --noEmit), re-run after patches.
- `npm --prefix apps/web test -- --run` (full frontend suite) -- pass, 1593/1593 tests, 27/27 files, re-run after patches.
- `uv run pytest` (the Python half of `make test`) -- run directly in this sandbox (no Docker available, so `make test`'s own invocation could not be used as-is): completed 100%, all tests passing, no Python file was touched by this story so this confirms no regression rather than exercising new code.
- Matrix Test Audit: all six I/O-matrix rows have a passing, executed test (capture happy path, upload happy path, permission-not-yet-requested, permission-denied, undecodable file, Back-from-Crop discards the image).

**Residual risks:**
- No real browser/device was available in this environment to run the spec's own manual check (a live `getUserMedia` capture and the upload fallback on desktop Chrome and a mobile browser). All camera/canvas/`createObjectURL` behavior is verified against jsdom stubs, not real browser APIs — the review pass's two high-severity findings (the dead `srcObject` assignment, missing EXIF orientation handling) are exactly the class of bug this kind of manual check would have caught, so a real-device smoke test before wider rollout is still warranted.
- The two deferred items (no upload file-size guard; no camera-track-ended detection) remain open in frontmatter `deferred` for later attention.
- This story's Crop screen is an intentional placeholder with no forward action beyond Back; Story 3.2 replaces it with the real crop editor and "Confirm Crop."
