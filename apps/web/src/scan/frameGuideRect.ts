/**
 * Where the framing guide sits in the camera's own pixels.
 *
 * The viewfinder shows a `<video>` with `object-fit: cover` (see
 * `ScanScreen.module.css`), so what is on screen is already a centre crop of
 * the camera's frame: the stream is scaled up until it covers the element and
 * the overflow falls off both ends of the long axis. The framing guide is
 * positioned in that *displayed* space, in CSS pixels, while a capture draws
 * from the *source* frame, in camera pixels. This module is the one place the
 * two are reconciled.
 *
 * Pure, and deliberately so: jsdom performs no layout, so every rectangle it
 * would report at runtime is zero — the mapping is therefore asserted here
 * against handed-in boxes (`frame-guide-rect.test.ts`) rather than through a
 * rendered viewfinder.
 */

/** A rectangle in the source image's own pixels. */
export interface SourceRect {
  x: number;
  y: number;
  width: number;
  height: number;
}

/**
 * The part of a `DOMRect` this module reads. Declared rather than taking
 * `DOMRect` so a test can hand over a literal.
 */
export interface Box {
  left: number;
  top: number;
  width: number;
  height: number;
}

function clamp(value: number, max: number): number {
  return Math.min(Math.max(value, 0), max);
}

/**
 * The region of a `cover`-fitted source that the guide rectangle marks out.
 *
 * `null` whenever the answer cannot be trusted — a source or a box with no
 * area (jsdom's every-rect-is-zero default, or a viewfinder measured before
 * layout), or a guide that maps to less than a pixel of source — and the
 * caller falls back to the whole frame rather than capturing a sliver.
 *
 * `object-position` is left at its `50% 50%` default throughout the
 * stylesheet, so the scaled frame is centred on both axes; that centring is
 * what `originX`/`originY` below encode. The result is clamped to the source,
 * which matters on the axis `cover` overflows: a guide that reaches past the
 * visible edge marks source that is not there.
 */
export function computeGuideSourceRect(
  source: { width: number; height: number },
  display: Box,
  guide: Box,
): SourceRect | null {
  if (source.width <= 0 || source.height <= 0) return null;
  if (display.width <= 0 || display.height <= 0) return null;
  if (guide.width <= 0 || guide.height <= 0) return null;

  // `cover`: the larger of the two ratios, so the scaled frame covers both
  // axes and overflows the one it does not fit.
  const scale = Math.max(display.width / source.width, display.height / source.height);
  const originX = display.left + (display.width - source.width * scale) / 2;
  const originY = display.top + (display.height - source.height * scale) / 2;

  const left = clamp((guide.left - originX) / scale, source.width);
  const top = clamp((guide.top - originY) / scale, source.height);
  const right = clamp((guide.left + guide.width - originX) / scale, source.width);
  const bottom = clamp((guide.top + guide.height - originY) / scale, source.height);

  const x = Math.round(left);
  const y = Math.round(top);
  const width = Math.min(Math.round(right - left), source.width - x);
  const height = Math.min(Math.round(bottom - top), source.height - y);
  if (width < 1 || height < 1) return null;

  return { x, y, width, height };
}
