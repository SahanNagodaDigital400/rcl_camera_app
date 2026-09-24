/**
 * Shrinking an oversized reference image on the device.
 *
 * Two claims live here and nothing else in the suite can make either:
 *
 * * **A colour-managed or CMYK image is never re-encoded.** CLAUDE.md is
 *   explicit that most reference images are CMYK press files and that a naive
 *   RGB conversion silently discards the embedded profile — which corrupts the
 *   embedding, not just the colour, and does it invisibly: the row would still
 *   report `created`. The screen test above can only see the refusal; this
 *   file is the only place the *reason* for it is asserted, byte by byte.
 * * **The whole frame is drawn.** `downscaleToBlob` takes an optional source
 *   rectangle and the capture path passes one; a shrink that passed one too
 *   would crop the tile's edge off and the result would look entirely
 *   reasonable. `drawImage`'s argument count is the only place that is
 *   observable.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';

import { SHRINK_MAX_EDGE, isColourManaged, shrinkImage } from '../upload/shrinkImage';

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

/** A JPEG built segment by segment: `[marker, ...payload]` pairs after `FFD8`. */
function jpeg(segments: [number, number[]][]): Uint8Array {
  const bytes: number[] = [0xff, 0xd8];
  for (const [marker, payload] of segments) {
    const length = payload.length + 2;
    bytes.push(0xff, marker, (length >> 8) & 0xff, length & 0xff, ...payload);
  }
  // Start of scan, which is where the marker walk stops looking.
  bytes.push(0xff, 0xda, 0x00, 0x02);
  return new Uint8Array(bytes);
}

function ascii(text: string): number[] {
  return [...text].map((char) => char.charCodeAt(0));
}

/**
 * A baseline frame header: precision, height, width, component count.
 * Three components is RGB; four is CMYK or YCCK.
 */
function frame(components: number): [number, number[]] {
  return [0xc0, [0x08, 0x01, 0x00, 0x01, 0x00, components]];
}

function asFile(bytes: Uint8Array, type = 'image/jpeg'): File {
  // Copied into a plain `ArrayBuffer` rather than handed straight to `File`:
  // a `Uint8Array` built from a number array is typed over `ArrayBufferLike`,
  // which `BlobPart` does not accept.
  const buffer = new ArrayBuffer(bytes.length);
  new Uint8Array(buffer).set(bytes);
  return new File([buffer], 'reference.jpg', { type });
}

describe('what a canvas round trip would change', () => {
  it('leaves a plain three-channel JPEG alone', async () => {
    // The one case that may be shrunk: no profile, no Adobe marker, three
    // channels. Anything the sniffer is unsure about must not land here.
    expect(await isColourManaged(asFile(jpeg([frame(3)])))).toBe(false);
  });

  it('refuses a JPEG carrying an embedded ICC profile', async () => {
    // AD-15: the profile is what makes the stored colour and the embedding
    // right, and `toBlob` writes an untagged sRGB JPEG that no longer has it.
    const withProfile = jpeg([[0xe2, [...ascii('ICC_PROFILE'), 0x00, 0x01, 0x01]], frame(3)]);

    expect(await isColourManaged(asFile(withProfile))).toBe(true);
  });

  it('refuses a four-channel JPEG', async () => {
    // CMYK, which CLAUDE.md puts at ~60% of a working POC's catalogue. A
    // browser that decodes it at all converts it with its own assumptions.
    expect(await isColourManaged(asFile(jpeg([frame(4)])))).toBe(true);
  });

  it('refuses a JPEG tagged by the Adobe marker', async () => {
    // APP14 is what distinguishes YCCK from plain CMYK and is on essentially
    // every press file — worth catching on its own, because a four-channel
    // frame header can sit past the probe window when a large thumbnail does
    // not.
    expect(await isColourManaged(asFile(jpeg([[0xee, ascii('Adobe')], frame(3)])))).toBe(true);
  });

  it('refuses anything that is not a JPEG or a PNG', async () => {
    // A `.tif`, which the real source tree carries and no browser decodes.
    // The safe answer and the true one are the same here.
    expect(await isColourManaged(asFile(jpeg([frame(3)]), 'image/tiff'))).toBe(true);
  });

  it('refuses bytes that do not start like a JPEG at all', async () => {
    // **Every uncertain answer is "yes".** A marker chain that cannot be
    // walked is a file whose colour nobody here can vouch for, and a wrong
    // "no" is an invisibly corrupted embedding.
    expect(await isColourManaged(asFile(new Uint8Array([0x00, 0x01, 0x02, 0x03])))).toBe(true);
  });

  it('refuses a PNG declaring a profile and allows one that does not', async () => {
    const signature = [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a];
    const chunk = (name: string): number[] => [0x00, 0x00, 0x00, 0x00, ...ascii(name), 0, 0, 0, 0];
    const profiled = new Uint8Array([...signature, ...chunk('iCCP'), ...chunk('IDAT')]);
    const plain = new Uint8Array([...signature, ...chunk('IDAT')]);

    expect(await isColourManaged(asFile(profiled, 'image/png'))).toBe(true);
    expect(await isColourManaged(asFile(plain, 'image/png'))).toBe(false);
  });
});

/** Stub the decode and the canvas, and report what was drawn. */
function stubCanvas(source: { width: number; height: number }): {
  drawImage: ReturnType<typeof vi.fn>;
  close: ReturnType<typeof vi.fn>;
} {
  const close = vi.fn();
  vi.stubGlobal(
    'createImageBitmap',
    vi.fn(() => Promise.resolve({ ...source, close })),
  );

  const drawImage = vi.fn();
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({
    drawImage,
  } as unknown as CanvasRenderingContext2D);
  vi.spyOn(HTMLCanvasElement.prototype, 'toBlob').mockImplementation(function toBlob(
    this: HTMLCanvasElement,
    callback: BlobCallback,
  ) {
    callback(new Blob(['much smaller'], { type: 'image/jpeg' }));
  });

  return { drawImage, close };
}

describe('the redraw', () => {
  it('draws the whole frame and never a region of it', async () => {
    // **The assertion this file exists for, beside the colour one.** A crop
    // would look perfectly reasonable on screen and would silently index a
    // different tile: a reference image *is* the tile, edge included. The
    // capture path passes a centre square to the very same function, so
    // nothing about the call site makes this impossible by construction.
    const { drawImage } = stubCanvas({ width: 19276, height: 9638 });

    await shrinkImage(asFile(jpeg([frame(3)])));

    // Five arguments is `(source, 0, 0, width, height)`. The nine-argument
    // form is the one that takes a source rectangle.
    expect(drawImage).toHaveBeenCalledTimes(1);
    expect(drawImage.mock.calls[0]).toHaveLength(5);
  });

  it('caps the long edge and keeps the aspect ratio', async () => {
    const { drawImage } = stubCanvas({ width: 19276, height: 9638 });

    await shrinkImage(asFile(jpeg([frame(3)])));

    const [, , , width, height] = drawImage.mock.calls[0] as number[];
    expect(width).toBe(SHRINK_MAX_EDGE);
    // Half the long edge, because the source is twice as wide as it is tall.
    expect(height).toBe(SHRINK_MAX_EDGE / 2);
  });

  it('keeps the file name, because the manifest pairs on it', async () => {
    // A sheet naming `reference.jpg` has to go on naming it. A row that
    // stopped matching its image is a row this step broke on the way out.
    stubCanvas({ width: 8000, height: 8000 });

    const shrunk = await shrinkImage(asFile(jpeg([frame(3)])));

    expect(shrunk?.name).toBe('reference.jpg');
  });

  it('answers null rather than throwing when the browser cannot decode it', async () => {
    vi.stubGlobal(
      'createImageBitmap',
      vi.fn(() => Promise.reject(new Error('unsupported'))),
    );

    expect(await shrinkImage(asFile(jpeg([frame(3)])))).toBeNull();
  });

  it('answers null when the redraw came back no smaller', async () => {
    // A file that is huge because it is huge, not because it is oversampled.
    // Sending a re-encode of it would spend a generation of JPEG artefacts to
    // save nothing.
    const bytes = jpeg([frame(3)]);
    const file = asFile(bytes);
    Object.defineProperty(file, 'size', { value: 1 });
    stubCanvas({ width: 8000, height: 8000 });

    expect(await shrinkImage(file)).toBeNull();
  });

  it('never decodes an image whose colour it would change', async () => {
    // The order matters: the sniff comes first, so a 96 MB CMYK press file is
    // not decoded into memory only to be handed straight back.
    const { drawImage } = stubCanvas({ width: 8000, height: 8000 });

    expect(await shrinkImage(asFile(jpeg([frame(4)])))).toBeNull();
    expect(drawImage).not.toHaveBeenCalled();
  });

  it('releases the decoded frame either way', async () => {
    // Up to 186 megapixels, a hundred times over in one batch.
    const { close } = stubCanvas({ width: 8000, height: 8000 });

    await shrinkImage(asFile(jpeg([frame(3)])));

    expect(close).toHaveBeenCalledTimes(1);
  });
});
