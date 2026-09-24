/**
 * Shrink a reference image that is over the upload ceiling, on the device.
 *
 * **Why this exists.** A reference image in the real catalogue runs to 96 MB
 * and 19276×9638 px (CLAUDE.md, Source data quirks). A batch of those is
 * gigabytes over a shop-floor connection, and the alternative this replaces
 * was a flat refusal that left an Administrator to re-export a hundred files
 * by hand. Shrinking is the same answer `scan/downscaleImage.ts` gives on the
 * query side, for the same reason, and it reuses that module rather than
 * growing a second one.
 *
 * **The whole frame, always.** `downscaleToBlob` is called with no `region`,
 * so every pixel of the source is drawn into the smaller canvas. Nothing is
 * cropped and no edge is discarded: a reference image is the tile, and a tile
 * with its border cut off is a different reference image. The capture path
 * crops to a centre square because a *phone photo* has framing to spend; a
 * press file has none.
 *
 * **It never touches an image that already fits.** `shrinkImage` is only
 * called for a file over the ceiling, and a file that is under it travels
 * byte-for-byte as chosen — a needless re-encode would cost a generation of
 * JPEG artefacts for nothing.
 *
 * **It refuses rather than guesses when colour is at stake.** This is the one
 * rule in this file that is not about bandwidth. CLAUDE.md is explicit that
 * most reference images are CMYK press files, that a naive RGB conversion
 * silently discards the embedded profile, and that the conversion belongs in
 * `shared/vision` under a fixed intent (AD-15). A canvas re-encode is exactly
 * that naive conversion: whatever the browser did with the profile on the way
 * in, `toBlob` writes an untagged sRGB JPEG on the way out, and the profile is
 * gone. The damage would be invisible — the tile would be indexed, the row
 * would report `created`, and only the embedding would be wrong. So an image
 * that declares a profile, or that is CMYK, is handed back unshrunk and the
 * screen refuses it in words. Re-exporting it is the Administrator's call to
 * make in a tool that knows what the intent should be.
 *
 * **This is not the `shared/vision` pipeline** and must never be read as a
 * second copy of it, for `scan/downscaleImage.ts`'s reason: the server decodes
 * whatever arrives to its own `DECODE_MAX_EDGE` (2048 px) before any
 * preprocessing begins, independently of anything here.
 */
import { computeDownscaledDimensions, downscaleToBlob } from '../scan/downscaleImage';

/**
 * The long edge a shrunk image is redrawn to.
 *
 * **Twice the server's own decode cap**, and that is the whole argument. The
 * pipeline resizes everything it is given to a 2048 px long edge before it
 * does anything else (`shared_vision.pipeline.DECODE_MAX_EDGE`), so a source
 * at 4096 px is still oversampled by a factor of two when the server's own
 * resampler runs — nothing the model will ever look at is lost, and the
 * resampling that matters still happens where it always did rather than being
 * quietly moved into a browser.
 *
 * A 19276 px press file comes down by a factor of 4.7 on each edge, which is
 * 22× the pixels and takes a 96 MB file to single-digit megabytes.
 */
export const SHRINK_MAX_EDGE = 4096;

/**
 * How much of a file's head is read to decide whether it is colour-managed.
 *
 * An ICC profile and the frame header both sit near the front of a JPEG, but
 * "near" is not a guarantee: a large EXIF thumbnail or a multi-segment profile
 * can push the frame header a long way in. Two megabytes is far past any of
 * those and is nothing against a file that is over the ceiling to begin with.
 * A walk that runs off the end of this window returns "managed" — see
 * `isColourManaged`.
 */
const PROBE_BYTES = 2 * 1024 * 1024;

/** JPEG start-of-frame markers, every variant. A frame header is where the component count lives. */
const SOF_MARKERS = new Set([
  0xc0, 0xc1, 0xc2, 0xc3, 0xc5, 0xc6, 0xc7, 0xc9, 0xca, 0xcb, 0xcd, 0xce, 0xcf,
]);

/** Markers that stand alone: no length, no payload. */
const STANDALONE = new Set([0x01, 0xd0, 0xd1, 0xd2, 0xd3, 0xd4, 0xd5, 0xd6, 0xd7, 0xd8]);

/** The number of colour channels that makes a JPEG CMYK or YCCK rather than RGB. */
const CMYK_COMPONENTS = 4;

/** Does `bytes` carry `text` at `at`, as ASCII? */
function matches(bytes: Uint8Array, at: number, text: string): boolean {
  if (at < 0 || at + text.length > bytes.length) return false;
  for (let i = 0; i < text.length; i += 1) {
    if (bytes[at + i] !== text.charCodeAt(i)) return false;
  }
  return true;
}

/**
 * Is this JPEG colour-managed or CMYK — that is, would a canvas round trip
 * change its colour?
 *
 * Walks the marker segments rather than searching the bytes for `ICC_PROFILE`,
 * because compressed scan data will eventually contain any short string you
 * care to look for and a false positive here refuses a file that was perfectly
 * safe to shrink.
 *
 * **Every uncertain answer is "yes".** A malformed marker chain, a frame
 * header past the probe window, a file that is not a JPEG at all — each
 * returns `true`, so the outcome is a refusal an Administrator can act on
 * rather than a silently wrong embedding they will never see.
 */
function jpegIsColourManaged(bytes: Uint8Array): boolean {
  if (bytes[0] !== 0xff || bytes[1] !== 0xd8) return true;

  let at = 2;
  while (at + 1 < bytes.length) {
    // Segments are byte-aligned and each begins `FF xx`; fill bytes are `FF`.
    if (bytes[at] !== 0xff) return true;
    const marker = bytes[at + 1] ?? 0;
    if (marker === 0xff) {
      at += 1;
      continue;
    }
    if (STANDALONE.has(marker)) {
      at += 2;
      continue;
    }
    // Start of scan, or end of image: the frame header is behind us if it was
    // ever coming, and everything past here is entropy-coded data.
    if (marker === 0xda || marker === 0xd9) return false;

    const high = bytes[at + 2];
    const low = bytes[at + 3];
    if (high === undefined || low === undefined) return true;
    const length = (high << 8) | low;
    // A segment length counts its own two bytes, so anything under two is
    // nonsense and the chain cannot be trusted from here on.
    if (length < 2) return true;

    const payload = at + 4;
    // APP2 carrying an embedded ICC profile.
    if (marker === 0xe2 && matches(bytes, payload, 'ICC_PROFILE')) return true;
    // APP14 `Adobe`, which is what tags a four-channel JPEG as YCCK rather
    // than plain CMYK — present on essentially every press file.
    if (marker === 0xee && matches(bytes, payload, 'Adobe')) return true;
    if (SOF_MARKERS.has(marker)) {
      // Frame header: precision (1), height (2), width (2), component count (1).
      const components = bytes[payload + 5];
      if (components === undefined) return true;
      if (components === CMYK_COMPONENTS) return true;
    }

    at += 2 + length;
  }

  // The walk ran out of probe before it reached a frame. Unknown, so managed.
  return true;
}

/** A PNG declaring an embedded profile, which a canvas round trip would drop. */
function pngIsColourManaged(bytes: Uint8Array): boolean {
  for (let at = 8; at + 8 <= bytes.length; ) {
    const high = bytes[at];
    if (high === undefined) return true;
    const length =
      (high << 24) | ((bytes[at + 1] ?? 0) << 16) | ((bytes[at + 2] ?? 0) << 8) | (bytes[at + 3] ?? 0);
    if (length < 0) return true;
    if (matches(bytes, at + 4, 'iCCP')) return true;
    // `IDAT` is the pixel data: every ancillary chunk that matters is behind it.
    if (matches(bytes, at + 4, 'IDAT')) return false;
    at += 12 + length;
  }
  return true;
}

/**
 * Would re-encoding this file through a canvas change its colour?
 *
 * Only JPEG and PNG are answered at all. Anything else — a TIFF, which the
 * real source tree carries and which no browser decodes — is `true`, which is
 * both the safe answer and the true one: it is not going to shrink either way.
 */
export async function isColourManaged(file: File): Promise<boolean> {
  if (file.type !== 'image/jpeg' && file.type !== 'image/png') return true;

  const head = new Uint8Array(await file.slice(0, PROBE_BYTES).arrayBuffer());
  return file.type === 'image/jpeg' ? jpegIsColourManaged(head) : pngIsColourManaged(head);
}

/**
 * Redraw `file` at `SHRINK_MAX_EDGE`, or answer `null` if it cannot be done
 * safely.
 *
 * `null` — never a throw and never a partially converted file — for three
 * reasons, all of which are the caller's to word: the image carries colour the
 * canvas would discard, the browser cannot decode it, or the result came back
 * no smaller than the original (a file that is huge because it is huge, not
 * because it is oversampled).
 *
 * The returned `File` keeps the **original name**, because the manifest pairs
 * on it: a sheet naming `RP.CMA.0008DJ.SM.0T.tif` has to keep naming it, and a
 * row that stopped matching its image is a row this screen broke on the way
 * out. Only the bytes and the media type change.
 */
export async function shrinkImage(file: File): Promise<File | null> {
  if (await isColourManaged(file)) return null;

  let bitmap: ImageBitmap;
  try {
    bitmap = await createImageBitmap(file);
  } catch {
    // A format this browser will not decode, or a frame past its texture
    // limits. Either way there is nothing to redraw.
    return null;
  }

  try {
    const { width, height } = computeDownscaledDimensions(
      bitmap.width,
      bitmap.height,
      SHRINK_MAX_EDGE,
    );
    // No `region`: the whole frame is drawn. See the module docstring.
    const shrunk = await downscaleToBlob(bitmap, width, height);
    if (shrunk.size >= file.size) return null;

    return new File([shrunk], file.name, { type: shrunk.type, lastModified: file.lastModified });
  } catch {
    return null;
  } finally {
    // The decoded frame is up to 186 megapixels and there may be a hundred of
    // them in a batch. Released here rather than left to the collector, which
    // has no idea how much memory sits behind this handle.
    bitmap.close();
  }
}
