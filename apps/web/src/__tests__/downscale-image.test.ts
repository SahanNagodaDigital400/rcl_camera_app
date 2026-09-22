/**
 * `computeDownscaledDimensions` is pure and asserted directly. `downscaleToBlob`
 * touches the DOM — a canvas, its 2D context, and `toBlob` — none of which
 * jsdom implements (`vite.config.ts` sets no canvas polyfill), so every test
 * of it stubs `HTMLCanvasElement.prototype.getContext` and `.toBlob` rather
 * than exercising a real canvas.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';

import { computeDownscaledDimensions, downscaleToBlob } from '../scan/downscaleImage';

afterEach(() => {
  vi.restoreAllMocks();
});

describe('computeDownscaledDimensions', () => {
  it('halves a landscape image whose long edge is over the cap', () => {
    expect(computeDownscaledDimensions(2048, 1024)).toEqual({ width: 1024, height: 512 });
  });

  it('halves a portrait image whose long edge is over the cap', () => {
    expect(computeDownscaledDimensions(1024, 2048)).toEqual({ width: 512, height: 1024 });
  });

  it('leaves an already-small image untouched — a downscale only, never an upscale', () => {
    expect(computeDownscaledDimensions(800, 600)).toEqual({ width: 800, height: 600 });
  });

  it('leaves an image exactly at the cap untouched', () => {
    expect(computeDownscaledDimensions(1024, 768)).toEqual({ width: 1024, height: 768 });
  });

  it('honours a caller-supplied cap instead of the default long edge', () => {
    expect(computeDownscaledDimensions(2000, 1000, 500)).toEqual({ width: 500, height: 250 });
  });

  it('rounds to whole pixels', () => {
    // 1024 / 3000 * 2000 = 682.66...
    expect(computeDownscaledDimensions(3000, 2000, 1024)).toEqual({ width: 1024, height: 683 });
  });
});

/** A stand-in 2D context recording every `drawImage` call it receives. */
function stubCanvas(options: { context?: object | null; blob?: Blob | null } = {}): {
  drawImage: ReturnType<typeof vi.fn>;
} {
  const drawImage = vi.fn();
  const context = options.context === undefined ? { drawImage } : options.context;

  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(
    context as CanvasRenderingContext2D | null,
  );
  vi.spyOn(HTMLCanvasElement.prototype, 'toBlob').mockImplementation(function toBlob(
    this: HTMLCanvasElement,
    callback: BlobCallback,
  ) {
    callback(options.blob === undefined ? new Blob(['x'], { type: 'image/jpeg' }) : options.blob);
  });

  return { drawImage };
}

describe('downscaleToBlob', () => {
  it('draws the source at the requested size and resolves with the encoded blob', async () => {
    const { drawImage } = stubCanvas();
    const source = {} as CanvasImageSource;

    const blob = await downscaleToBlob(source, 512, 384);

    expect(drawImage).toHaveBeenCalledWith(source, 0, 0, 512, 384);
    expect(blob).toBeInstanceOf(Blob);
  });

  it('encodes as a JPEG at quality 0.9, whichever path called it', async () => {
    stubCanvas();
    const toBlob = vi.mocked(HTMLCanvasElement.prototype.toBlob);

    await downscaleToBlob({} as CanvasImageSource, 100, 100);

    expect(toBlob).toHaveBeenCalledWith(expect.any(Function), 'image/jpeg', 0.9);
  });

  it('sizes the canvas itself to the requested dimensions', async () => {
    stubCanvas();
    let sizedWidth = 0;
    let sizedHeight = 0;
    const createElement = document.createElement.bind(document);
    vi.spyOn(document, 'createElement').mockImplementation((tag: string) => {
      const element = createElement(tag);
      if (tag === 'canvas') {
        const canvas = element as HTMLCanvasElement;
        Object.defineProperty(canvas, 'width', {
          get: () => sizedWidth,
          set: (value: number) => {
            sizedWidth = value;
          },
        });
        Object.defineProperty(canvas, 'height', {
          get: () => sizedHeight,
          set: (value: number) => {
            sizedHeight = value;
          },
        });
      }
      return element;
    });

    await downscaleToBlob({} as CanvasImageSource, 640, 360);

    expect(sizedWidth).toBe(640);
    expect(sizedHeight).toBe(360);
  });

  it('rejects rather than silently returning nothing when the context is unavailable', async () => {
    stubCanvas({ context: null });

    await expect(downscaleToBlob({} as CanvasImageSource, 100, 100)).rejects.toThrow(
      /2D canvas context/,
    );
  });

  it('rejects when the canvas cannot encode the image', async () => {
    stubCanvas({ blob: null });

    await expect(downscaleToBlob({} as CanvasImageSource, 100, 100)).rejects.toThrow(
      /encode/,
    );
  });
});
