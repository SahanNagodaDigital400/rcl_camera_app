import { useEffect, useRef, useState } from 'react';
import type { JSX, PointerEvent as ReactPointerEvent } from 'react';

import { ApiRequestError, SCAN_QUALITY_TOO_LOW } from '../api/client';
import type { NormalizedCropRect } from '../api/client';
import styles from './CropScreen.module.css';
import type { ScanCandidate } from '@rocell/schema/scan';

/**
 * Crop — the real crop editor Story 3.1 left as a placeholder (Story 3.2).
 *
 * A free-form rectangle over the handed-off image: drag the body to move it,
 * drag any of the eight handles to resize it, and "Confirm Crop" — the one
 * accent-styled action on this screen — sends the image and the selection to
 * the server, which executes the pixel crop exactly once (AD-11). Back stays
 * the secondary, navy-outline control it always was.
 *
 * **The selection is normalized, never pixels.** `rect` below lives in 0-1
 * fractions of the image's *own* rendered box — measured against the `<img>`
 * element directly (`normalizedPoint`), never against `.stage`. `.stage`
 * carries a `min-height` floor so it never collapses to a sliver before the
 * image has loaded, and `.image` is `width: 100%; height: auto` — it does
 * not stretch to fill that floor, so for a photo shorter than it `.stage`'s
 * own box is taller than the image's. `.frame`, the image's own positioning
 * parent and the one `.selection` renders into, wraps only the `<img>` in
 * normal flow and therefore always matches its box exactly, whatever
 * `.stage` does — which is what keeps the overlay a user drags, the fraction
 * this component computes, and the rectangle `submitScan` sends all
 * describing the same box.
 *
 * **No client-side pixel crop, ever.** Confirm hands the whole downscaled
 * Blob `ScanScreen` produced, unmodified, plus `rect`, to `onConfirm` — which
 * is `App`'s `submitScan` call. Cropping a canvas here would be the second
 * crop implementation AD-11 explicitly forbids.
 *
 * **Pointer Events, not mouse/touch pairs.** One handler shape covers mouse,
 * touch and pen, and `setPointerCapture` (feature-detected — jsdom implements
 * neither it nor `PointerEvent` drag physics) keeps a fast drag tracked even
 * once the pointer leaves the handle or the selection body.
 *
 * Rendered *inside* the shell, in place of the home panel, exactly as
 * `ScanScreen` is — no `<main>` of its own; `AppShell` already provides the
 * one the gate's focus effect moves focus to on a screen swap.
 *
 * **A `scan_quality_too_low` refusal (Story 3.3, FR-9/AD-12) is not an
 * ordinary `error`.** The server scored the cropped region below its
 * configured bound, and the fix is a new photo, not a nudge to the
 * rectangle — so this swaps the normal Confirm/Back pair for a single
 * "Retake" action above an inline banner, rather than leaving both live for
 * a resubmission that would only fail again (Design Notes: "Retake, not
 * re-crop").
 */

interface CropScreenProps {
  /** The downscaled Blob `ScanScreen` produced, from either path. */
  image: Blob;
  /** Discards `image` and returns to Scan. */
  onBack: () => void;
  /**
   * Sends `image` and the confirmed selection to the server, and matches it.
   *
   * Resolves to up to three ranked Candidates (Story 3.4) — the return value
   * is unused inside this component and forwarded by `App` to the Results
   * screen it navigates to on success.
   *
   * A rejection is caught here, not by the caller: the AC is explicit that a
   * failed submission leaves the image and the selection in place with
   * Confirm re-enabled, which only this component can do — `App` has already
   * discarded nothing by the time this rejects, but it has also not been
   * asked to keep anything around for a retry.
   */
  onConfirm: (rect: NormalizedCropRect) => Promise<ScanCandidate[]>;
}

/** A crop selection, normalized 0-1 against the image's own dimensions. */
interface Rect {
  x: number;
  y: number;
  width: number;
  height: number;
}

/** The four corners and four edge midpoints a selection can be resized from. */
type HandleId = 'tl' | 'tr' | 'bl' | 'br' | 'tm' | 'bm' | 'lm' | 'rm';

type DragKind = HandleId | 'move';

interface DragState {
  kind: DragKind;
  pointerId: number;
  startRect: Rect;
  /** The pointer's own normalized position at the moment the drag began. */
  startX: number;
  startY: number;
}

/** Every handle, in the order they are rendered — order has no effect on drag. */
const HANDLES: HandleId[] = ['tl', 'tr', 'bl', 'br', 'tm', 'bm', 'lm', 'rm'];

/** How far the default selection sits in from each edge. */
const DEFAULT_INSET = 0.1;

/** The pre-filled best-guess selection (Design Notes: inset, not full-frame). */
const DEFAULT_RECT: Rect = {
  x: DEFAULT_INSET,
  y: DEFAULT_INSET,
  width: 1 - DEFAULT_INSET * 2,
  height: 1 - DEFAULT_INSET * 2,
};

/** The smallest a dragged edge may shrink the selection to, on either axis. */
const MIN_DIMENSION = 0.1;

const SUBMIT_FAILURE = 'Could not submit the scan. Try again.';

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), Math.max(min, max));
}

/**
 * Rounded to a precision far finer than any image this screen handles could
 * show a difference at (a ten-thousand-pixel edge is still accurate to a
 * fraction of a pixel), so `dx`/`dy` accumulating IEEE 754 noise across a
 * drag — `0.1 + 0.05` is `0.15000000000000002` in a double — never reaches
 * the rectangle this component renders from or sends to the server.
 */
const RECT_PRECISION = 1e6;

function round(value: number): number {
  return Math.round(value * RECT_PRECISION) / RECT_PRECISION;
}

/** `start` translated by `(dx, dy)`, kept fully inside the image. */
function moveRect(start: Rect, dx: number, dy: number): Rect {
  return {
    x: round(clamp(start.x + dx, 0, 1 - start.width)),
    y: round(clamp(start.y + dy, 0, 1 - start.height)),
    width: start.width,
    height: start.height,
  };
}

/** `start` with the edges `handle` names dragged by `(dx, dy)`, floor and bounds held. */
function resizeRect(start: Rect, handle: HandleId, dx: number, dy: number): Rect {
  let { x, y, width, height } = start;

  if (handle === 'tl' || handle === 'bl' || handle === 'lm') {
    const right = x + width;
    x = clamp(x + dx, 0, right - MIN_DIMENSION);
    width = right - x;
  }
  if (handle === 'tr' || handle === 'br' || handle === 'rm') {
    width = clamp(width + dx, MIN_DIMENSION, 1 - x);
  }
  if (handle === 'tl' || handle === 'tr' || handle === 'tm') {
    const bottom = y + height;
    y = clamp(y + dy, 0, bottom - MIN_DIMENSION);
    height = bottom - y;
  }
  if (handle === 'bl' || handle === 'br' || handle === 'bm') {
    height = clamp(height + dy, MIN_DIMENSION, 1 - y);
  }

  return { x: round(x), y: round(y), width: round(width), height: round(height) };
}

/**
 * Route this pointer's future events to `target` regardless of where it
 * physically moves. Feature-detected: jsdom implements neither this nor
 * `PointerEvent` drag physics, and the tests dispatch events directly at the
 * element they mean to move rather than relying on capture at all.
 */
function capture(target: Element, pointerId: number): void {
  if (typeof target.setPointerCapture === 'function') {
    target.setPointerCapture(pointerId);
  }
}

/** `capture`'s undo, on drag end. Feature-detected for the same reason. */
function release(target: Element, pointerId: number): void {
  if (typeof target.releasePointerCapture === 'function') {
    target.releasePointerCapture(pointerId);
  }
}

export function CropScreen({ image, onBack, onConfirm }: CropScreenProps): JSX.Element {
  const imgRef = useRef<HTMLImageElement>(null);
  const dragRef = useRef<DragState | null>(null);

  const [rect, setRect] = useState<Rect>(DEFAULT_RECT);
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  /**
   * Set instead of `error` when the server's refusal is `SCAN_QUALITY_TOO_LOW`
   * (Story 3.3, FR-9/AD-12) — the API's own sentence, never a copy hardcoded
   * here. `null` is the ordinary state; a fresh `handleConfirm` attempt clears
   * it before asking again, the same way it clears `error`.
   */
  const [qualityRetake, setQualityRetake] = useState<string | null>(null);

  // Created and revoked inside the same effect, keyed on `image` — never
  // split into a `useMemo` for the create half. React does not guarantee a
  // `useMemo` computation survives being discarded and re-run (Strict Mode's
  // dev double-invoke does exactly that), which risks a URL created once and
  // never revoked. Keeping create-and-revoke as one pair in one effect means
  // there is never a URL this component created that isn't matched by
  // exactly one `revokeObjectURL` call.
  //
  // Assigned straight onto the `<img>` element rather than through state:
  // `oxlint`'s `react/set-state-in-effect` forbids calling a setter inside an
  // effect, and there is nothing here a second render would improve — the
  // element already exists (it carries no other data-dependent prop), so this
  // is the same "bind directly, once the node exists" move `ScanScreen` makes
  // for the live stream's `srcObject`.
  useEffect(() => {
    const url = URL.createObjectURL(image);
    if (imgRef.current !== null) {
      imgRef.current.src = url;
    }
    // Revoked on unmount and whenever `image` changes and a new URL replaces
    // this one, so a Blob URL never outlives the element that pointed at it —
    // the same reason a browser tab that never revoked one would leak memory
    // for the life of the session.
    return () => {
      URL.revokeObjectURL(url);
    };
  }, [image]);

  /**
   * The pointer's position as a 0-1 fraction of the *image's own* rendered
   * box, or `null`.
   *
   * Measured against `imgRef`, never `.stage`. `.stage` carries a
   * `min-height` floor so it never collapses to a sliver before the image has
   * loaded, and `.image` is `width: 100%; height: auto` — it does not stretch
   * to fill that floor. For any photo whose rendered height comes in under
   * the floor (an ordinary landscape phone photo at a typical mobile
   * viewport width routinely does), `.stage`'s box is taller than the
   * image's own, and a fraction computed against it would describe a
   * rectangle the user never saw, let alone dragged. `.frame` (the
   * `<img>`'s positioning parent, and the parent `.selection` renders into)
   * has no floor of its own and wraps the image exactly, so its box and the
   * image's are the same rect — measuring against the image directly is
   * still the one true source, in case that ever stops holding.
   */
  function normalizedPoint(event: ReactPointerEvent): { x: number; y: number } | null {
    const img = imgRef.current;
    if (img === null) return null;
    const box = img.getBoundingClientRect();
    if (box.width === 0 || box.height === 0) return null;
    return {
      x: (event.clientX - box.left) / box.width,
      y: (event.clientY - box.top) / box.height,
    };
  }

  function beginDrag(kind: DragKind, event: ReactPointerEvent): void {
    // Never while a submission is in flight: the selection this drag would
    // produce could not be sent anyway, and a mid-submit resize would leave
    // `rect` describing something other than what was just confirmed.
    if (confirming) return;
    // Never a second pointer while one is already dragging: an incidental
    // second touch mid-drag (a thumb brushing the screen while a finger is
    // still down) would otherwise overwrite `dragRef` and orphan the first
    // pointer — its own `pointerup`/`pointercancel` never matches what is in
    // `dragRef` any more, so `release` is never called for it and the
    // pointer capture it holds outlives the gesture. One pointer drives the
    // selection at a time, which is also what keeps this screen from ever
    // reading a second pointer as the start of a pinch (EXPERIENCE.md: no
    // pinch-zoom on the crop stage).
    if (dragRef.current !== null) return;
    const point = normalizedPoint(event);
    if (point === null) return;
    event.preventDefault();
    dragRef.current = {
      kind,
      pointerId: event.pointerId,
      startRect: rect,
      startX: point.x,
      startY: point.y,
    };
    capture(event.currentTarget, event.pointerId);
  }

  function onDragMove(event: ReactPointerEvent): void {
    const drag = dragRef.current;
    if (drag === null || drag.pointerId !== event.pointerId) return;
    const point = normalizedPoint(event);
    if (point === null) return;
    const dx = point.x - drag.startX;
    const dy = point.y - drag.startY;
    setRect(
      drag.kind === 'move'
        ? moveRect(drag.startRect, dx, dy)
        : resizeRect(drag.startRect, drag.kind, dx, dy),
    );
  }

  function endDrag(event: ReactPointerEvent): void {
    const drag = dragRef.current;
    if (drag === null || drag.pointerId !== event.pointerId) return;
    dragRef.current = null;
    release(event.currentTarget, event.pointerId);
  }

  async function handleConfirm(): Promise<void> {
    if (confirming) return;
    setConfirming(true);
    setError(null);
    setQualityRetake(null);
    try {
      await onConfirm(rect);
      // No further state change on success: `App`'s `onConfirm` moves the
      // section away from Crop, which unmounts this component. Clearing
      // `confirming` here as well would be a `setState` racing an unmount.
    } catch (failure) {
      if (failure instanceof ApiRequestError && failure.code === SCAN_QUALITY_TOO_LOW) {
        // The photo's content, not the selection, is what failed — adjusting
        // the rectangle over the same blurry frame cannot fix it (Design
        // Notes: "Retake, not re-crop"), so this branches away from the
        // ordinary `error` state into the one that swaps the actions row
        // below for a single "Retake" rather than leaving Confirm live for a
        // resubmission that would only fail again.
        setQualityRetake(failure.message);
      } else {
        setError(failure instanceof ApiRequestError ? failure.message : SUBMIT_FAILURE);
      }
      setConfirming(false);
    }
  }

  return (
    <section className={styles.screen}>
      <h1 className={styles.title}>Crop</h1>

      <div className={styles.stage} data-testid="crop-stage">
        {/* `.frame` wraps only the `<img>` in normal flow — `.selection` is
            absolutely positioned and so contributes nothing to its auto
            height — which is what makes `.frame`'s own box equal the image's
            rendered box exactly, whatever `.stage`'s `min-height` floor does.
            `.selection` and its handles are positioned against *this*
            element rather than `.stage`, so the overlay a user sees always
            lines up with the same box `normalizedPoint` measures. */}
        <div className={styles.frame}>
          <img className={styles.image} ref={imgRef} alt="Captured tile, not yet cropped" />
          <div
            className={styles.selection}
            style={{
              left: `${rect.x * 100}%`,
              top: `${rect.y * 100}%`,
              width: `${rect.width * 100}%`,
              height: `${rect.height * 100}%`,
            }}
            data-testid="crop-selection"
            onPointerDown={(event) => beginDrag('move', event)}
            onPointerMove={onDragMove}
            onPointerUp={endDrag}
            onPointerCancel={endDrag}
          >
            {HANDLES.map((handle) => (
              <div
                key={handle}
                className={styles.handle}
                data-pos={handle}
                data-testid={`crop-handle-${handle}`}
                onPointerDown={(event) => {
                  // Stops the selection body's own `onPointerDown` above from
                  // also starting a `'move'` drag for the same press —
                  // without this a press on a handle begins two drags, and
                  // whichever ends up in `dragRef` last decides what the
                  // gesture does.
                  event.stopPropagation();
                  beginDrag(handle, event);
                }}
                onPointerMove={onDragMove}
                onPointerUp={endDrag}
                onPointerCancel={endDrag}
              />
            ))}
          </div>
        </div>
      </div>

      <p className={styles.hint}>Drag the corners or edges to resize. Drag inside to move.</p>

      {error !== null && (
        <p className={styles.error} role="alert">
          {error}
        </p>
      )}

      {/* EXPERIENCE.md's `retake-prompt`: an inline, surface-colored banner
          directly above the one action available — never a modal. Fires only
          on the cropped region (AD-12), and only replaces the ordinary
          Confirm/Back pair below, never joins them. */}
      {qualityRetake !== null && (
        <p className={styles.retakePrompt} role="alert">
          {qualityRetake}
        </p>
      )}

      <div className={styles.actions}>
        {qualityRetake !== null ? (
          // Retake, not re-crop (Design Notes): the failure is the photo's
          // content, not the selection, so adjusting the rectangle over the
          // same blurry frame cannot fix it. One action, calling `onBack`
          // rather than `handleConfirm` — a resubmission of the same photo
          // would only fail again — and the secondary Back control is
          // redundant with it, so it is not rendered alongside this one.
          <button className={styles.confirm} type="button" onClick={onBack}>
            Retake
          </button>
        ) : (
          <>
            {/* The screen's one accent control (DESIGN.md: exactly one per
                screen). Back is the secondary, navy-outlined one. */}
            <button
              className={styles.confirm}
              type="button"
              onClick={() => void handleConfirm()}
              disabled={confirming}
            >
              {confirming ? (
                <>
                  {/* EXPERIENCE.md: "processing: lightweight spinner, no
                      skeleton" — the wait for matching (Story 3.4) now
                      happens inside this same request, so it lives beside the
                      button's own text rather than as a second element on the
                      screen. Decorative: the button's own text already says
                      "Submitting…", so a screen reader has nothing to gain
                      from a second announcement of the same state. */}
                  <span aria-hidden="true" className={styles.spinner} />
                  Submitting…
                </>
              ) : (
                'Confirm Crop'
              )}
            </button>
            {/* Disabled in flight, `AddTileScreen`'s own reason: a click that
                unmounted this screen mid-request would leave the caller unsure
                whether the scan had already been submitted. */}
            <button className={styles.back} type="button" onClick={onBack} disabled={confirming}>
              Back
            </button>
          </>
        )}
      </div>
    </section>
  );
}
