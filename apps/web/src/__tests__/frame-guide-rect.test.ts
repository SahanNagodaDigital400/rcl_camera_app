/**
 * `computeGuideSourceRect` is the arithmetic behind "the shutter captures
 * what the box marks out" — the framing guide's on-screen rectangle mapped
 * back through the viewfinder's `object-fit: cover` into the camera's own
 * pixels. Pure, and asserted directly: jsdom performs no layout, so the
 * rendered viewfinder could never produce a non-zero box to map.
 *
 * The worked case throughout: a 2000×1000 camera frame in a 400×400
 * viewfinder. `cover` scales by 0.4 (the larger of 400/2000 and 400/1000),
 * rendering 800×400, so 200 CSS pixels of frame hang off each side and one
 * displayed pixel is 2.5 camera pixels.
 */
import { describe, expect, it } from 'vitest';

import { computeGuideSourceRect } from '../scan/frameGuideRect';

const FRAME = { width: 2000, height: 1000 };
const VIEWFINDER = { left: 0, top: 0, width: 400, height: 400 };
const GUIDE = { left: 40, top: 40, width: 320, height: 240 };

describe('computeGuideSourceRect', () => {
  it('maps the guide box through a cover fit into camera pixels', () => {
    // 40px in from the left edge is 240px into the rendered frame, which is
    // 600 camera pixels; 320×240 displayed is 800×600 captured.
    expect(
      computeGuideSourceRect(FRAME, VIEWFINDER, GUIDE),
    ).toEqual({ x: 600, y: 100, width: 800, height: 600 });
  });

  it('measures the guide against the viewfinder rather than the page', () => {
    // The same guide, on a viewfinder pushed down and across the page: the
    // captured region is unchanged, because both boxes moved together.
    expect(
      computeGuideSourceRect(
        FRAME,
        { left: 100, top: 60, width: 400, height: 400 },
        { left: 140, top: 100, width: 320, height: 240 },
      ),
    ).toEqual({ x: 600, y: 100, width: 800, height: 600 });
  });

  it('clamps a guide that reaches past the frame cover has already cropped', () => {
    // Beyond the visible edge there is no source to capture, on either axis.
    expect(
      computeGuideSourceRect(FRAME, VIEWFINDER, { left: -400, top: -100, width: 1200, height: 600 }),
    ).toEqual({ x: 0, y: 0, width: 2000, height: 1000 });
  });

  it('answers null for a guide that lands wholly outside the frame', () => {
    expect(
      computeGuideSourceRect(FRAME, VIEWFINDER, { left: 1000, top: 40, width: 200, height: 240 }),
    ).toBeNull();
  });

  it('answers null for a guide that maps to less than a pixel of source', () => {
    // A tiny stream blown up to fill the viewfinder: 10 displayed pixels are
    // a quarter of a camera pixel, and a quarter-pixel capture is no capture.
    expect(
      computeGuideSourceRect({ width: 10, height: 10 }, VIEWFINDER, {
        left: 40,
        top: 40,
        width: 10,
        height: 10,
      }),
    ).toBeNull();
  });

  it('answers null for an unmeasured viewfinder — jsdom, or a first paint', () => {
    expect(
      computeGuideSourceRect(FRAME, { left: 0, top: 0, width: 0, height: 0 }, GUIDE),
    ).toBeNull();
  });

  it('answers null for an unmeasured guide', () => {
    expect(
      computeGuideSourceRect(FRAME, VIEWFINDER, { left: 0, top: 0, width: 0, height: 0 }),
    ).toBeNull();
  });

  it('answers null before the stream has reported its dimensions', () => {
    expect(
      computeGuideSourceRect({ width: 0, height: 0 }, VIEWFINDER, GUIDE),
    ).toBeNull();
  });
});
