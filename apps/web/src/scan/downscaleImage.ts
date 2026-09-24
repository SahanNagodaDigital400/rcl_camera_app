/**
 * The one place capture and upload converge on identical bytes.
 *
 * Story 3.1's whole meaning of "equivalent submission": a live-camera capture
 * and a chosen file both end up here, and both call the same two functions in
 * the same order before Crop ever sees a pixel. Nothing downstream of this
 * module can tell which path an image took, because nothing about it differs.
 *
 * **This is not the shared/vision pipeline, and it must never be confused with
 * it.** CLAUDE.md's single most important invariant — index-time and
 * query-time preprocessing must be byte-for-byte identical — is about the
 * server-side embedding pipeline in `shared/vision/`, which this file never
 * touches, imports from, or reimplements. This is a client-only bandwidth
 * step: a ~1024px long edge is comfortably above the 224px the model actually
 * consumes, and exists so a 96 MB CMYK press file's phone-camera cousin (a
 * modern phone photo is routinely 12+ MP) is not uploaded at full resolution
 * over a shop-floor connection. The server decodes whatever arrives to its own
 * cap (`DECODE_MAX_EDGE`, `shared/vision/shared_vision/pipeline.py`) before
 * its own preprocessing begins, independent of what this file does.
 */

/** A width and a height, in pixels. */
export interface Dimensions {
  width: number;
  height: number;
}

/** A rectangle in the source image's own pixels. */
export interface SourceRect {
  x: number;
  y: number;
  width: number;
  height: number;
}

/**
 * The centre square of a frame's short edge — the region the shutter submits.
 *
 * This is the POC's capture, transcribed: `side = Math.min(vw, vh)`, taken
 * from the middle (`poc/tilematch/web/index.html`). Two reasons it is a
 * square of the short edge rather than the whole frame, both the POC's own:
 *
 * * It is the region the square viewfinder shows, so what the staff member
 *   framed is exactly what reaches the model — see `ScanScreen.module.css`.
 * * It spends the ~1024px budget below on the tile instead of on pixels the
 *   server's own centre crop would discard anyway: `shared_vision.preprocess`
 *   resizes the short edge to 256 and centre-crops 224, so frame that never
 *   sat in the middle of a square was never going to be embedded.
 *
 * Pure, so `downscale-image.test.ts` can assert the arithmetic without a
 * canvas — which matters because jsdom performs no layout and draws nothing.
 */
export function computeCentreSquare(width: number, height: number): SourceRect {
  const side = Math.min(width, height);
  return {
    x: Math.round((width - side) / 2),
    y: Math.round((height - side) / 2),
    width: side,
    height: side,
  };
}

/**
 * The size to draw an image at so its long edge is at most `maxEdge`,
 * preserving aspect ratio.
 *
 * A downscale only, never an upscale: an image already within bounds is
 * returned unchanged, dimensions untouched — there is no reason to re-encode
 * a frame that is already small, and doing so would needlessly cost a
 * generation of JPEG artefacts for nothing.
 *
 * Pure, and deliberately so: this is the half of the story's convergence that
 * has nothing to do with a canvas, and it is what `downscale-image.test.ts`
 * can assert against without touching the DOM at all.
 */
export function computeDownscaledDimensions(
  width: number,
  height: number,
  maxEdge = 1024,
): Dimensions {
  const longEdge = Math.max(width, height);
  if (longEdge <= maxEdge) return { width, height };

  const scale = maxEdge / longEdge;
  return {
    width: Math.round(width * scale),
    height: Math.round(height * scale),
  };
}

/**
 * Draw `source` at `width`×`height` and encode the result as a JPEG blob.
 *
 * The one function both `ScanScreen` paths call — a `<video>` frame for a live
 * capture, an `ImageBitmap` decoded from a chosen file for an upload — so
 * their output is identical by construction rather than by two
 * implementations kept in step by hand. Quality is fixed at 0.9: this is a
 * bandwidth step, not the place to trade quality against size per call site.
 *
 * `region` narrows *what is read from the source*, never how it is written:
 * the capture path passes `computeCentreSquare`'s rectangle, so the crop
 * happens at full sensor resolution and only the tile spends the 1024px
 * budget. Omitted — the upload path, where a gallery photo was framed
 * somewhere else entirely and the POC leaves it alone for that reason — the
 * whole source is drawn.
 */
export async function downscaleToBlob(
  source: CanvasImageSource,
  width: number,
  height: number,
  region?: SourceRect,
): Promise<Blob> {
  const canvas = document.createElement('canvas');
  canvas.width = width;
  canvas.height = height;

  const context = canvas.getContext('2d');
  if (context === null) {
    throw new Error('Could not get a 2D canvas context to downscale the image.');
  }
  if (region === undefined) {
    context.drawImage(source, 0, 0, width, height);
  } else {
    context.drawImage(source, region.x, region.y, region.width, region.height, 0, 0, width, height);
  }

  return new Promise<Blob>((resolve, reject) => {
    canvas.toBlob(
      (blob) => {
        if (blob === null) {
          reject(new Error('Could not encode the downscaled image.'));
          return;
        }
        resolve(blob);
      },
      'image/jpeg',
      0.9,
    );
  });
}
