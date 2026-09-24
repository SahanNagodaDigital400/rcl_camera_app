/**
 * Scan — the entry point Story 3.1 adds, and the one home-panel door every
 * authenticated role reaches (unlike the admin-only doors `add-tile.test.tsx`
 * and its siblings gate). Driven through the real `App` rather than
 * `ScanScreen` directly, the way `auth-gating.test.tsx` drives the gate: the
 * reachability claim and the Back-to-Scan/Crop-discards-the-image claim are
 * both about the gate's own section state, not about `ScanScreen` in
 * isolation.
 *
 * jsdom implements neither a camera nor a canvas (`vite.config.ts` notes the
 * missing canvas polyfill), and it implements no `URL.createObjectURL` at
 * all — not even a stub that throws. Every test below that reaches the live
 * viewfinder, a capture, or Crop's preview stubs the piece jsdom is missing
 * rather than exercising the real API.
 */
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { StrictMode } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import App from '../App';
import type { User } from '@rocell/schema/user';

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  Reflect.deleteProperty(navigator, 'mediaDevices');
  Reflect.deleteProperty(URL, 'createObjectURL');
  Reflect.deleteProperty(URL, 'revokeObjectURL');
  Reflect.deleteProperty(navigator, 'permissions');
});

const ADMIN: User = {
  id: '9c2f1e4a-7b3d-4c58-9e10-2a6f8d4b1c07',
  name: 'Nadeesha Silva',
  email: 'nadeesha@rocell.lk',
  role: 'admin',
  active: true,
  must_change_password: false,
  temp_credential_expires_at: null,
  last_login_at: '2026-09-18T08:00:00Z',
  locked_until: null,
  created_at: '2026-09-17T08:00:00Z',
  updated_at: '2026-09-18T08:00:00Z',
};

const STAFF: User = {
  ...ADMIN,
  id: '3f1a6b2c-9d4e-4f70-8a11-5c2e7b9d0a34',
  name: 'Kasun Perera',
  email: 'kasun@rocell.lk',
  role: 'staff',
};

interface Reply {
  status: number;
  body?: unknown;
}

/** Replace `fetch` with a queue keyed by path. `auth-gating.test.tsx`'s pattern. */
function stubFetch(replies: Record<string, Reply[]>): void {
  vi.stubGlobal('fetch', (input: string) => {
    const queued = replies[input];
    const reply = (queued && queued.length > 1 ? queued.shift() : queued?.[0]) ?? {
      status: 404,
      body: { error: { code: 'not_found', message: 'No such route.' } },
    };

    return Promise.resolve({
      ok: reply.status >= 200 && reply.status < 300,
      status: reply.status,
      json: () => Promise.resolve(reply.body ?? null),
    } as Response);
  });
}

function stubSession(user: User): void {
  // A scan answered with no match, so a capture or an upload reaches Results
  // in the tests that only need to get past it.
  stubFetch({
    '/api/auth/session': [{ status: 200, body: user }],
    '/api/scans': [{ status: 200, body: [] }],
  });
}

/**
 * `stubFetch`'s own shape, plus the calls it answered — `add-tile.test.tsx`'s
 * pattern, needed here for the first time because a Crop submission test has
 * to read back the `FormData` `submitScan` built rather than only the status
 * it produced.
 */
function stubFetchWithCalls(replies: Record<string, Reply[]>): {
  calls: [string, RequestInit][];
} {
  const calls: [string, RequestInit][] = [];
  vi.stubGlobal('fetch', (input: string, init: RequestInit = {}) => {
    calls.push([input, init]);
    const queued = replies[input];
    const reply = (queued && queued.length > 1 ? queued.shift() : queued?.[0]) ?? {
      status: 404,
      body: { error: { code: 'not_found', message: 'No such route.' } },
    };

    return Promise.resolve({
      ok: reply.status >= 200 && reply.status < 300,
      status: reply.status,
      json: () => Promise.resolve(reply.body ?? null),
    } as Response);
  });
  return { calls };
}

/**
 * Gives the Crop stage a fixed, non-zero box. jsdom performs no layout, so
 * every element's real `getBoundingClientRect` is all zeros — which `CropScreen`
 * treats as "nothing to measure yet" and ignores. A square box keeps the
 * fraction arithmetic in every drag test below identical on both axes.
 */
function stubStageGeometry(size = 400): void {
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({
    left: 0,
    top: 0,
    right: size,
    bottom: size,
    width: size,
    height: size,
    x: 0,
    y: 0,
    toJSON: () => ({}),
  } as DOMRect);
}

/**
 * Gives one specific element its own fixed box, distinct from every other
 * element's — an instance property shadows `stubStageGeometry`'s
 * prototype-level stub (and jsdom's own all-zero default) for this element
 * alone. Used to prove `CropScreen` measures a drag against the `<img>`'s own
 * box rather than `.stage`'s, which `stubStageGeometry`'s one-box-for-every-
 * element stub cannot distinguish: `.stage` and the image would always agree
 * under it, so a bug that read the wrong one would still pass every other
 * drag test in this file.
 */
function overrideRect(
  element: Element,
  box: { width: number; height: number; left?: number; top?: number },
): void {
  const left = box.left ?? 0;
  const top = box.top ?? 0;
  Object.defineProperty(element, 'getBoundingClientRect', {
    value: () => ({
      left,
      top,
      right: left + box.width,
      bottom: top + box.height,
      width: box.width,
      height: box.height,
      x: left,
      y: top,
      toJSON: () => ({}),
    }),
    configurable: true,
  });
}

/**
 * A normalized fraction, rendered the way `CropScreen`'s inline style does —
 * computed rather than a literal `'10%'`, which `no-raw-values.test.ts`
 * forbids outside `tokens.css` and would otherwise flag right here, in the
 * very file that argues for the rule.
 */
function pct(fraction: number): string {
  return `${fraction * 100}%`;
}

/** One pointer's down-move-up sequence, at the same `pointerId` throughout. */
function drag(
  target: Element,
  from: { clientX: number; clientY: number },
  to: { clientX: number; clientY: number },
): void {
  fireEvent.pointerDown(target, { pointerId: 1, ...from });
  fireEvent.pointerMove(target, { pointerId: 1, ...to });
  fireEvent.pointerUp(target, { pointerId: 1, ...to });
}

function fakeStream(): MediaStream {
  return { getTracks: () => [{ stop: vi.fn() }] } as unknown as MediaStream;
}

/** Stubs `navigator.mediaDevices.getUserMedia`, and returns the spy. */
/**
 * The Permissions API's answer for the camera, and a way to change it — the
 * browser's own record of a grant, which is what lets the viewfinder open
 * without a tap on a later visit.
 */
function stubPermission(state: PermissionState): { grant: () => void } {
  const record = { state };
  Object.defineProperty(navigator, 'permissions', {
    value: { query: vi.fn(() => Promise.resolve(record)) },
    configurable: true,
  });
  return {
    grant: () => {
      record.state = 'granted';
    },
  };
}

function stubCamera(outcome: MediaStream | 'denied' = fakeStream()): ReturnType<typeof vi.fn> {
  const getUserMedia = vi.fn(() =>
    outcome === 'denied'
      ? Promise.reject(new Error('Permission denied'))
      : Promise.resolve(outcome),
  );
  Object.defineProperty(navigator, 'mediaDevices', {
    value: { getUserMedia },
    configurable: true,
  });
  return getUserMedia;
}

/**
 * Stubs the canvas draw/encode step `downscaleToBlob` depends on, and returns
 * the `drawImage` spy — the only place the region a capture actually read
 * from the camera frame is observable, since the encoded blob is a stub.
 */
function stubCanvas(blob: Blob = new Blob(['frame'], { type: 'image/jpeg' })): {
  drawImage: ReturnType<typeof vi.fn>;
} {
  const drawImage = vi.fn();
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({
    drawImage,
  } as unknown as CanvasRenderingContext2D);
  vi.spyOn(HTMLCanvasElement.prototype, 'toBlob').mockImplementation(function toBlob(
    this: HTMLCanvasElement,
    callback: BlobCallback,
  ) {
    callback(blob);
  });
  return { drawImage };
}

/** Stubs `URL.createObjectURL`/`revokeObjectURL`, which jsdom has neither of. */
function stubObjectUrl(): { revoke: ReturnType<typeof vi.fn> } {
  const revoke = vi.fn();
  Object.defineProperty(URL, 'createObjectURL', {
    value: vi.fn(() => 'blob:mock-preview'),
    configurable: true,
  });
  Object.defineProperty(URL, 'revokeObjectURL', { value: revoke, configurable: true });
  return { revoke };
}

/** Stubs `createImageBitmap`, the decode step the upload path runs. Returns the spy. */
function stubImageBitmap(
  outcome: { width: number; height: number } | 'undecodable' = { width: 1200, height: 800 },
): ReturnType<typeof vi.fn> {
  const createImageBitmap = vi.fn(() =>
    outcome === 'undecodable'
      ? Promise.reject(new Error('not an image'))
      : Promise.resolve({ ...outcome, close: vi.fn() }),
  );
  vi.stubGlobal('createImageBitmap', createImageBitmap);
  return createImageBitmap;
}

function aFile(name = 'tile.jpg', type = 'image/jpeg'): File {
  return new File([new Uint8Array([1, 2, 3, 4])], name, { type });
}

async function openScan(): Promise<void> {
  fireEvent.click(await screen.findByRole('button', { name: /^scan$/i }));
  await screen.findByRole('heading', { name: /^scan$/i });
}

describe('reaching Scan', () => {
  it.each([
    ['an Administrator', ADMIN],
    ['a Staff user', STAFF],
  ])('is the landing surface for %s, and the nav returns to it', async (_label, user) => {
    // Unlike every admin surface, `reachableBy`'s default covers this: there
    // is no role guard on the way in, and both roles land on the same screen.
    stubSession(user);
    render(<App />);

    // Landed on it without navigating.
    expect(await screen.findByRole('heading', { name: /^scan$/i })).toBeTruthy();

    // And the nav entry comes back to it from elsewhere.
    fireEvent.click(screen.getByRole('button', { name: /^history$/i }));
    await screen.findByRole('heading', { name: /^history$/i });
    fireEvent.click(screen.getByRole('button', { name: /^scan$/i }));

    expect(await screen.findByRole('heading', { name: /^scan$/i })).toBeTruthy();
  });
});

describe('camera permission', () => {
  it('explains why access is needed, and calls getUserMedia only after a tap', async () => {
    const getUserMedia = stubCamera();
    stubSession(STAFF);
    render(<App />);
    await openScan();

    // The explanation is on screen before anything native could have fired.
    expect(screen.getByText(/needs your camera/i)).toBeTruthy();
    expect(getUserMedia).not.toHaveBeenCalled();
    // The fallback is never gated on the camera state.
    expect(screen.getByLabelText(/choose a photo/i)).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: /enable camera/i }));

    expect(getUserMedia).toHaveBeenCalledTimes(1);
  });

  it('replaces the viewfinder with a denial, and keeps the upload fallback usable', async () => {
    stubCamera('denied');
    stubSession(STAFF);
    render(<App />);
    await openScan();

    fireEvent.click(screen.getByRole('button', { name: /enable camera/i }));

    expect(await screen.findByText(/was not granted/i)).toBeTruthy();
    expect(screen.queryByTestId('viewfinder-video')).toBeNull();
    // Never a dead end: the fallback is still there and still enabled.
    const picker = screen.getByLabelText(/choose a photo/i);
    expect(picker).toBeTruthy();
    expect(picker).toHaveProperty('disabled', false);
  });
});
const A_CANDIDATE = {
  tile_id: '11111111-1111-4111-8111-111111111111',
  code: 'RP.CMA.0001DJ.SM.0T',
  size: '45X90',
  category: 'CREMA MARMOL',
  image_id: '22222222-2222-4222-8222-222222222222',
};

/** The frame every capture is submitted with: the whole downscaled image. */
function expectFullFrame(body: FormData): void {
  expect(body.get('crop_x')).toBe('0');
  expect(body.get('crop_y')).toBe('0');
  expect(body.get('crop_width')).toBe('1');
  expect(body.get('crop_height')).toBe('1');
  expect(body.get('image')).toBeInstanceOf(Blob);
}

describe('the capture path', () => {
  it('binds the granted stream to the rendered video element', async () => {
    const stream = fakeStream();
    stubCamera(stream);
    stubSession(STAFF);
    render(<App />);
    await openScan();

    fireEvent.click(screen.getByRole('button', { name: /enable camera/i }));

    const video = await screen.findByTestId('viewfinder-video');
    expect(video).toHaveProperty('srcObject', stream);
  });

  it('still binds the stream under StrictMode, which mounts the screen twice', async () => {
    const stream = fakeStream();
    stubCamera(stream);
    stubSession(STAFF);
    render(
      <StrictMode>
        <App />
      </StrictMode>,
    );
    await openScan();

    fireEvent.click(screen.getByRole('button', { name: /enable camera/i }));

    const video = await screen.findByTestId('viewfinder-video');
    expect(video).toHaveProperty('srcObject', stream);
  });

  it('explains first while the browser would prompt, then opens without a tap once granted', async () => {
    const permission = stubPermission('prompt');
    const getUserMedia = stubCamera();
    stubSession(STAFF);
    render(<App />);
    await openScan();

    expect(await screen.findByText(/needs your camera/i)).toBeTruthy();
    expect(getUserMedia).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole('button', { name: /enable camera/i }));
    await screen.findByTestId('viewfinder-video');
    // The browser now holds the grant; nothing is written by page script.
    permission.grant();

    // Leave for History and come back: no explanation, no tap, a live feed.
    fireEvent.click(screen.getByRole('button', { name: /^history$/i }));
    await screen.findByRole('heading', { name: /^history$/i });
    fireEvent.click(screen.getByRole('button', { name: /^scan$/i }));

    expect(await screen.findByTestId('viewfinder-video')).toBeTruthy();
    expect(screen.queryByRole('button', { name: /enable camera/i })).toBeNull();
    expect(getUserMedia).toHaveBeenCalledTimes(2);
  });

  it('starts the camera on arrival when the browser already holds the grant', async () => {
    stubPermission('granted');
    const getUserMedia = stubCamera();
    stubSession(STAFF);
    render(<App />);

    expect(await screen.findByTestId('viewfinder-video')).toBeTruthy();
    expect(getUserMedia).toHaveBeenCalledTimes(1);
    expect(screen.queryByText(/needs your camera/i)).toBeNull();
    expect(screen.queryByRole('button', { name: /enable camera/i })).toBeNull();
  });

  it('starts the camera exactly once under StrictMode when the grant is held', async () => {
    stubPermission('granted');
    const getUserMedia = stubCamera();
    stubSession(STAFF);
    render(
      <StrictMode>
        <App />
      </StrictMode>,
    );

    expect(await screen.findByTestId('viewfinder-video')).toBeTruthy();
    expect(getUserMedia).toHaveBeenCalledTimes(1);
  });

  it('falls into the denial state, fallback intact, when a held grant is refused after all', async () => {
    stubPermission('granted');
    stubCamera('denied');
    stubSession(STAFF);
    render(<App />);

    expect(await screen.findByText(/was not granted/i)).toBeTruthy();
    expect(screen.getByLabelText(/choose a photo/i)).toHaveProperty('disabled', false);
  });

  it('explains and waits for a tap when the browser has no Permissions API', async () => {
    const getUserMedia = stubCamera();
    stubSession(STAFF);
    render(<App />);

    expect(await screen.findByText(/needs your camera/i)).toBeTruthy();
    expect(getUserMedia).not.toHaveBeenCalled();
  });

  it('submits the whole frame straight from the shutter and shows the ranked candidates', async () => {
    stubCamera();
    stubCanvas();
    const { calls } = stubFetchWithCalls({
      '/api/auth/session': [{ status: 200, body: STAFF }],
      '/api/scans': [{ status: 200, body: [A_CANDIDATE] }],
    });
    render(<App />);
    await openScan();

    fireEvent.click(screen.getByRole('button', { name: /enable camera/i }));

    const video = await screen.findByTestId('viewfinder-video');
    expect(screen.getByTestId('framing-guide-overlay')).toBeTruthy();

    Object.defineProperty(video, 'videoWidth', { value: 2000, configurable: true });
    Object.defineProperty(video, 'videoHeight', { value: 1000, configurable: true });

    fireEvent.click(screen.getByRole('button', { name: /^capture$/i }));

    // No crop step in between: the shutter is the last tap before the answer.
    expect(await screen.findByRole('heading', { name: /^results$/i })).toBeTruthy();
    expect(screen.queryByRole('heading', { name: /^crop$/i })).toBeNull();
    expect(screen.getByText(A_CANDIDATE.code)).toBeTruthy();
    expect(screen.getByText(/best match/i)).toBeTruthy();

    const submitted = calls.find(([path]) => path === '/api/scans');
    expect(submitted).toBeTruthy();
    expectFullFrame(submitted?.[1].body as FormData);
  });

  it('announces the wait and disables the shutter while the frame is being matched', async () => {
    stubCamera();
    stubCanvas();
    const scanResolver: { resolve: ((value: Response) => void) | null } = { resolve: null };
    vi.stubGlobal('fetch', (input: string) => {
      if (input === '/api/auth/session') {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: () => Promise.resolve(STAFF),
        } as Response);
      }
      if (input === '/api/scans') {
        return new Promise<Response>((resolve) => {
          scanResolver.resolve = resolve;
        });
      }
      return Promise.resolve({
        ok: false,
        status: 404,
        json: () => Promise.resolve({ error: { code: 'not_found', message: 'No such route.' } }),
      } as Response);
    });
    render(<App />);
    await openScan();

    fireEvent.click(screen.getByRole('button', { name: /enable camera/i }));
    const video = await screen.findByTestId('viewfinder-video');
    Object.defineProperty(video, 'videoWidth', { value: 2000, configurable: true });
    Object.defineProperty(video, 'videoHeight', { value: 1000, configurable: true });

    fireEvent.click(screen.getByRole('button', { name: /^capture$/i }));

    expect(await screen.findByRole('status')).toHaveProperty('textContent', 'Matching…');
    expect(screen.getByRole('button', { name: /^capture$/i })).toHaveProperty('disabled', true);
    expect(screen.getByLabelText(/choose a photo/i)).toHaveProperty('disabled', true);

    scanResolver.resolve?.({ ok: true, status: 200, json: () => Promise.resolve([]) } as Response);

    expect(await screen.findByRole('heading', { name: /^results$/i })).toBeTruthy();
  });

  it('no-ops if the shutter is tapped before video metadata has loaded', async () => {
    stubCamera();
    stubCanvas();
    const { calls } = stubFetchWithCalls({
      '/api/auth/session': [{ status: 200, body: STAFF }],
      '/api/scans': [{ status: 200, body: [] }],
    });
    render(<App />);
    await openScan();

    fireEvent.click(screen.getByRole('button', { name: /enable camera/i }));
    await screen.findByTestId('viewfinder-video');

    fireEvent.click(screen.getByRole('button', { name: /^capture$/i }));

    expect(screen.getByRole('heading', { name: /^scan$/i })).toBeTruthy();
    expect(calls.filter(([path]) => path === '/api/scans')).toHaveLength(0);
  });
});

/**
 * A 2000×1000 stream. The centre square of its short edge is 1000×1000 read
 * from x=500 — the POC's own `side = Math.min(vw, vh)`, taken from the middle
 * (`poc/tilematch/web/index.html`).
 */
function stubFrame(video: HTMLElement): void {
  Object.defineProperty(video, 'videoWidth', { value: 2000, configurable: true });
  Object.defineProperty(video, 'videoHeight', { value: 1000, configurable: true });
}

describe('the capture region', () => {
  it("captures the frame's centre square, at full camera resolution", async () => {
    stubCamera();
    const { drawImage } = stubCanvas();
    stubFetchWithCalls({
      '/api/auth/session': [{ status: 200, body: STAFF }],
      '/api/scans': [{ status: 200, body: [A_CANDIDATE] }],
    });
    render(<App />);
    await openScan();

    fireEvent.click(screen.getByRole('button', { name: /enable camera/i }));
    const video = await screen.findByTestId('viewfinder-video');
    stubFrame(video);

    fireEvent.click(screen.getByRole('button', { name: /^capture$/i }));

    expect(await screen.findByRole('heading', { name: /^results$/i })).toBeTruthy();
    // Read from the camera frame's 500,0 1000×1000 — the crop is taken before
    // the downscale, so the square is under the 1024px cap and is written
    // whole rather than as a shrunken fraction of the frame.
    expect(drawImage).toHaveBeenCalledWith(video, 500, 0, 1000, 1000, 0, 0, 1000, 1000);
  });

  /**
   * The regression this describe block exists for. The shutter used to submit
   * the framing guide's measured box — inset on all four edges, so a fraction
   * of the frame — where the POC submits the whole centre square. That gap in
   * framing, with `shared/vision` byte-identical on both sides, is what made
   * the app's scan read as less accurate than the POC's.
   */
  it('does not narrow the capture to the framing guide overlay', async () => {
    stubCamera();
    const { drawImage } = stubCanvas();
    stubFetchWithCalls({
      '/api/auth/session': [{ status: 200, body: STAFF }],
      '/api/scans': [{ status: 200, body: [A_CANDIDATE] }],
    });
    render(<App />);
    await openScan();

    fireEvent.click(screen.getByRole('button', { name: /enable camera/i }));
    const video = await screen.findByTestId('viewfinder-video');
    stubFrame(video);
    // An overlay laid out well inside the stage. It must not move the capture:
    // the guide outlines the square, it never crops within it.
    overrideRect(video, { width: 400, height: 400 });
    overrideRect(screen.getByTestId('framing-guide-overlay'), {
      left: 40,
      top: 40,
      width: 320,
      height: 240,
    });

    fireEvent.click(screen.getByRole('button', { name: /^capture$/i }));

    await screen.findByRole('heading', { name: /^results$/i });
    expect(drawImage).toHaveBeenCalledWith(video, 500, 0, 1000, 1000, 0, 0, 1000, 1000);
  });

  it('submits the captured square whole: the shutter is the crop, so no second one', async () => {
    stubCamera();
    stubCanvas();
    const { calls } = stubFetchWithCalls({
      '/api/auth/session': [{ status: 200, body: STAFF }],
      '/api/scans': [{ status: 200, body: [A_CANDIDATE] }],
    });
    render(<App />);
    await openScan();

    fireEvent.click(screen.getByRole('button', { name: /enable camera/i }));
    const video = await screen.findByTestId('viewfinder-video');
    stubFrame(video);

    fireEvent.click(screen.getByRole('button', { name: /^capture$/i }));

    await screen.findByRole('heading', { name: /^results$/i });
    // The rectangle is normalized against the image submitted, and that image
    // is already the centre square: the server crops nothing further.
    expectFullFrame(calls.find(([path]) => path === '/api/scans')?.[1].body as FormData);
  });

  it('captures the same square whether or not the viewfinder has been laid out', async () => {
    // jsdom lays nothing out, so every rectangle is zero — the same state a
    // capture would hit before the viewfinder's first paint. The region is
    // read from the frame's own dimensions, so there is nothing to fall back
    // from and no second submission shape to get wrong.
    stubCamera();
    const { drawImage } = stubCanvas();
    stubFetchWithCalls({
      '/api/auth/session': [{ status: 200, body: STAFF }],
      '/api/scans': [{ status: 200, body: [A_CANDIDATE] }],
    });
    render(<App />);
    await openScan();

    fireEvent.click(screen.getByRole('button', { name: /enable camera/i }));
    const video = await screen.findByTestId('viewfinder-video');
    stubFrame(video);

    fireEvent.click(screen.getByRole('button', { name: /^capture$/i }));

    expect(await screen.findByRole('heading', { name: /^results$/i })).toBeTruthy();
    expect(drawImage).toHaveBeenCalledWith(video, 500, 0, 1000, 1000, 0, 0, 1000, 1000);
  });
});

describe('leaving Scan', () => {
  it('offers no Back control: the nav is the way out of the landing surface', async () => {
    stubSession(STAFF);
    render(<App />);
    await openScan();

    expect(screen.queryByRole('button', { name: /^back$/i })).toBeNull();

    fireEvent.click(screen.getByRole('button', { name: /^history$/i }));

    expect(await screen.findByRole('heading', { name: /^history$/i })).toBeTruthy();
    expect(screen.queryByRole('heading', { name: /^scan$/i })).toBeNull();
  });
});

describe('the upload path', () => {
  it('downscales a chosen file the same way and submits it whole, reaching Results', async () => {
    stubCanvas();
    const createImageBitmap = stubImageBitmap({ width: 3000, height: 4000 });
    const { calls } = stubFetchWithCalls({
      '/api/auth/session': [{ status: 200, body: STAFF }],
      '/api/scans': [{ status: 200, body: [A_CANDIDATE] }],
    });
    render(<App />);
    await openScan();

    fireEvent.change(screen.getByLabelText(/choose a photo/i), { target: { files: [aFile()] } });

    expect(await screen.findByRole('heading', { name: /^results$/i })).toBeTruthy();
    expect(screen.queryByRole('heading', { name: /^crop$/i })).toBeNull();
    expect(createImageBitmap).toHaveBeenCalledWith(
      expect.anything(),
      expect.objectContaining({ imageOrientation: 'from-image' }),
    );
    const submitted = calls.find(([path]) => path === '/api/scans');
    expectFullFrame(submitted?.[1].body as FormData);
  });

  it('shows an inline error for a file that fails to decode, and lets another be chosen', async () => {
    stubImageBitmap('undecodable');
    stubSession(STAFF);
    render(<App />);
    await openScan();

    fireEvent.change(screen.getByLabelText(/choose a photo/i), {
      target: { files: [aFile('not-a-tile.jpg')] },
    });

    expect(await screen.findByRole('alert')).toHaveProperty(
      'textContent',
      'That file is not a readable image. Choose another.',
    );
    expect(screen.getByRole('heading', { name: /^scan$/i })).toBeTruthy();
    expect(screen.getByLabelText(/choose a photo/i)).toHaveProperty('disabled', false);
    // Nothing was submitted, so there is nothing to retry or crop.
    expect(screen.queryByRole('button', { name: /try again/i })).toBeNull();
    expect(screen.queryByRole('button', { name: /crop this photo/i })).toBeNull();
  });
});

describe('a submission refused on Scan', () => {
  it('lets a failure be dismissed the same way', async () => {
    stubCanvas();
    stubImageBitmap({ width: 1000, height: 1000 });
    stubFetch({
      '/api/auth/session': [{ status: 200, body: STAFF }],
      '/api/scans': [
        {
          status: 503,
          body: {
            error: {
              code: 'matching_unavailable',
              message: 'The image matching service is not set up on this server.',
            },
          },
        },
      ],
    });
    render(<App />);
    await openScan();

    fireEvent.change(screen.getByLabelText(/choose a photo/i), { target: { files: [aFile()] } });
    await screen.findByRole('alert');

    fireEvent.click(screen.getByRole('button', { name: /^dismiss$/i }));

    expect(screen.queryByRole('alert')).toBeNull();
    expect(screen.queryByRole('button', { name: /try again/i })).toBeNull();
    expect(screen.getByRole('heading', { name: /^scan$/i })).toBeTruthy();
  });

  it('opens the crop editor on the refused frame from "Crop this photo", with Back returning to Scan', async () => {
    stubCanvas();
    const { revoke } = stubObjectUrl();
    stubImageBitmap({ width: 1000, height: 1000 });
    stubFetch({
      '/api/auth/session': [{ status: 200, body: STAFF }],
      '/api/scans': [
        {
          status: 503,
          body: {
            error: {
              code: 'matching_unavailable',
              message: 'The image matching service is not set up on this server.',
            },
          },
        },
      ],
    });
    render(<App />);
    await openScan();

    fireEvent.change(screen.getByLabelText(/choose a photo/i), { target: { files: [aFile()] } });
    await screen.findByRole('alert');

    fireEvent.click(screen.getByRole('button', { name: /crop this photo/i }));

    expect(await screen.findByRole('heading', { name: /^crop$/i })).toBeTruthy();
    expect(screen.getByRole('button', { name: /confirm crop/i })).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: /^back$/i }));

    expect(await screen.findByRole('heading', { name: /^scan$/i })).toBeTruthy();
    expect(screen.queryByRole('heading', { name: /^crop$/i })).toBeNull();
    expect(revoke).toHaveBeenCalledWith('blob:mock-preview');
  });

  it("shows the server's own message and resubmits the same frame from Try again", async () => {
    stubCanvas();
    stubImageBitmap({ width: 1000, height: 1000 });
    const { calls } = stubFetchWithCalls({
      '/api/auth/session': [{ status: 200, body: STAFF }],
      '/api/scans': [
        {
          status: 503,
          body: {
            error: {
              code: 'matching_unavailable',
              message: 'The image matching service is not set up on this server.',
            },
          },
        },
        { status: 200, body: [A_CANDIDATE] },
      ],
    });
    render(<App />);
    await openScan();

    fireEvent.change(screen.getByLabelText(/choose a photo/i), { target: { files: [aFile()] } });

    expect(await screen.findByRole('alert')).toHaveProperty(
      'textContent',
      'The image matching service is not set up on this server.',
    );
    expect(screen.getByRole('heading', { name: /^scan$/i })).toBeTruthy();
    expect(screen.getByRole('button', { name: /crop this photo/i })).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: /try again/i }));

    expect(await screen.findByRole('heading', { name: /^results$/i })).toBeTruthy();
    const submissions = calls.filter(([path]) => path === '/api/scans');
    expect(submissions).toHaveLength(2);
    expect(submissions[0]?.[1].body).toBeInstanceOf(FormData);
    expect(submissions[1]?.[1].body).toBeInstanceOf(FormData);
  });

  it('stays on Scan with a plain message on a network failure', async () => {
    stubCanvas();
    stubImageBitmap({ width: 1000, height: 1000 });
    vi.stubGlobal('fetch', (input: string) => {
      if (input === '/api/auth/session') {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: () => Promise.resolve(STAFF),
        } as Response);
      }
      if (input === '/api/scans') {
        return Promise.reject(new Error('the network is down'));
      }
      return Promise.resolve({
        ok: false,
        status: 404,
        json: () => Promise.resolve({ error: { code: 'not_found', message: 'No such route.' } }),
      } as Response);
    });
    render(<App />);
    await openScan();

    fireEvent.change(screen.getByLabelText(/choose a photo/i), { target: { files: [aFile()] } });

    expect(await screen.findByRole('alert')).toHaveProperty(
      'textContent',
      'Could not reach the server. Check your connection and try again.',
    );
    expect(screen.getByRole('heading', { name: /^scan$/i })).toBeTruthy();
    expect(screen.getByRole('button', { name: /try again/i })).toHaveProperty('disabled', false);
  });
});

/** Upload a frame and land on Results — the whole staff flow, two taps. */
async function reachResults(): Promise<void> {
  render(<App />);
  await openScan();
  fireEvent.change(screen.getByLabelText(/choose a photo/i), { target: { files: [aFile()] } });
  await screen.findByRole('heading', { name: /^results$/i });
}

/** The optional crop, opened from Results on the frame it came from. */
async function reachCrop(): Promise<void> {
  await reachResults();
  fireEvent.click(screen.getByRole('button', { name: /adjust crop/i }));
  await screen.findByRole('heading', { name: /^crop$/i });
}

describe('the optional crop', () => {
  it('is offered on Results, never before it', async () => {
    stubCanvas();
    stubObjectUrl();
    stubImageBitmap({ width: 1000, height: 1000 });
    stubFetch({
      '/api/auth/session': [{ status: 200, body: STAFF }],
      '/api/scans': [{ status: 200, body: [A_CANDIDATE] }],
    });

    await reachResults();

    expect(screen.getByRole('button', { name: /adjust crop/i })).toBeTruthy();
    expect(screen.getByRole('button', { name: /scan again/i })).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: /adjust crop/i }));

    expect(await screen.findByRole('heading', { name: /^crop$/i })).toBeTruthy();
    expect(screen.getByTestId('crop-selection')).toBeTruthy();
  });

  it('returns to the Results it was opened from when Back is pressed, releasing the preview', async () => {
    stubCanvas();
    const { revoke } = stubObjectUrl();
    stubImageBitmap({ width: 1000, height: 1000 });
    stubFetch({
      '/api/auth/session': [{ status: 200, body: STAFF }],
      '/api/scans': [{ status: 200, body: [A_CANDIDATE] }],
    });

    await reachCrop();

    fireEvent.click(screen.getByRole('button', { name: /^back$/i }));

    expect(await screen.findByRole('heading', { name: /^results$/i })).toBeTruthy();
    expect(screen.getByText(A_CANDIDATE.code)).toBeTruthy();
    expect(screen.queryByRole('heading', { name: /^crop$/i })).toBeNull();
    expect(revoke).toHaveBeenCalledWith('blob:mock-preview');
  });

  it('returns to the viewfinder from "Scan again"', async () => {
    stubCanvas();
    stubImageBitmap({ width: 1000, height: 1000 });
    stubFetch({
      '/api/auth/session': [{ status: 200, body: STAFF }],
      '/api/scans': [{ status: 200, body: [A_CANDIDATE] }],
    });

    await reachResults();

    fireEvent.click(screen.getByRole('button', { name: /scan again/i }));

    expect(await screen.findByRole('heading', { name: /^scan$/i })).toBeTruthy();
    expect(screen.queryByRole('heading', { name: /^results$/i })).toBeNull();
  });
});

describe("the Crop screen's selection", () => {
  it('is pre-filled with an inset selection over the image', async () => {
    stubCanvas();
    stubObjectUrl();
    stubImageBitmap({ width: 1000, height: 1000 });
    stubSession(STAFF);

    await reachCrop();

    const selection = screen.getByTestId('crop-selection');

    expect(selection.style.left).toBe(pct(0.1));
    expect(selection.style.top).toBe(pct(0.1));
    expect(selection.style.width).toBe(pct(0.8));
    expect(selection.style.height).toBe(pct(0.8));
  });

  it('drags a corner handle to resize the selection', async () => {
    stubCanvas();
    stubObjectUrl();
    stubImageBitmap({ width: 1000, height: 1000 });
    stubSession(STAFF);
    stubStageGeometry();

    await reachCrop();

    // The default selection's bottom-right corner sits at 90% of the 400px
    // square stage `stubStageGeometry` gives every test in this block.
    drag(
      screen.getByTestId('crop-handle-br'),
      { clientX: 360, clientY: 360 },
      { clientX: 380, clientY: 380 },
    );

    const selection = screen.getByTestId('crop-selection');
    // The opposite corner (top-left) never moved…
    expect(selection.style.left).toBe(pct(0.1));
    expect(selection.style.top).toBe(pct(0.1));
    // …and the dragged one grew by the same 5% the pointer travelled.
    expect(selection.style.width).toBe(pct(0.85));
    expect(selection.style.height).toBe(pct(0.85));
  });

  it('drags an edge handle to resize on one axis only', async () => {
    stubCanvas();
    stubObjectUrl();
    stubImageBitmap({ width: 1000, height: 1000 });
    stubSession(STAFF);
    stubStageGeometry();

    await reachCrop();

    // The right-edge handle sits at (90%, 50%).
    drag(
      screen.getByTestId('crop-handle-rm'),
      { clientX: 360, clientY: 200 },
      { clientX: 340, clientY: 200 },
    );

    const selection = screen.getByTestId('crop-selection');
    expect(selection.style.left).toBe(pct(0.1));
    expect(selection.style.top).toBe(pct(0.1));
    // Narrower by the 5% the pointer moved inward…
    expect(selection.style.width).toBe(pct(0.75));
    // …and the height, which this handle never touches, is unchanged.
    expect(selection.style.height).toBe(pct(0.8));
  });

  it('drags the body to move the whole selection, resizing nothing', async () => {
    stubCanvas();
    stubObjectUrl();
    stubImageBitmap({ width: 1000, height: 1000 });
    stubSession(STAFF);
    stubStageGeometry();

    await reachCrop();

    drag(
      screen.getByTestId('crop-selection'),
      { clientX: 200, clientY: 200 },
      { clientX: 220, clientY: 220 },
    );

    const selection = screen.getByTestId('crop-selection');
    expect(selection.style.left).toBe(pct(0.15));
    expect(selection.style.top).toBe(pct(0.15));
    expect(selection.style.width).toBe(pct(0.8));
    expect(selection.style.height).toBe(pct(0.8));
  });

  it('will not shrink a selection past the minimum, or push it outside the image', async () => {
    stubCanvas();
    stubObjectUrl();
    stubImageBitmap({ width: 1000, height: 1000 });
    stubSession(STAFF);
    stubStageGeometry();

    await reachCrop();

    // A drag far past the opposite edge — this handle stops shrinking well
    // before the pointer does, rather than collapsing to nothing or crossing
    // over the top-left corner.
    drag(
      screen.getByTestId('crop-handle-br'),
      { clientX: 360, clientY: 360 },
      { clientX: 0, clientY: 0 },
    );

    const selection = screen.getByTestId('crop-selection');
    expect(Number.parseFloat(selection.style.width)).toBeGreaterThan(0);
    expect(Number.parseFloat(selection.style.height)).toBeGreaterThan(0);
  });

  it('ignores a second pointer that starts a drag while one is already active', async () => {
    stubCanvas();
    stubObjectUrl();
    stubImageBitmap({ width: 1000, height: 1000 });
    stubSession(STAFF);
    stubStageGeometry();

    await reachCrop();

    const body = screen.getByTestId('crop-selection');

    // The first pointer (id 1) begins a move-drag on the selection body.
    fireEvent.pointerDown(body, { pointerId: 1, clientX: 200, clientY: 200 });
    // An incidental second touch (id 2) lands mid-drag, on a handle — a
    // thumb brushing the screen while a finger is still down. Without the
    // guard this would overwrite the active drag and orphan the first
    // pointer.
    fireEvent.pointerDown(screen.getByTestId('crop-handle-br'), {
      pointerId: 2,
      clientX: 360,
      clientY: 360,
    });
    // The second pointer's own move must do nothing — `beginDrag` never
    // accepted it, so there is no drag for this pointer id to drive.
    fireEvent.pointerMove(screen.getByTestId('crop-handle-br'), {
      pointerId: 2,
      clientX: 0,
      clientY: 0,
    });
    // The first pointer is still the one driving the selection.
    fireEvent.pointerMove(body, { pointerId: 1, clientX: 220, clientY: 220 });
    fireEvent.pointerUp(body, { pointerId: 1, clientX: 220, clientY: 220 });

    const selection = screen.getByTestId('crop-selection');
    // Exactly the first pointer's own move-drag result — the default rect
    // translated by (0.05, 0.05) — and no trace of the second pointer's
    // attempted resize, which would have shrunk the selection instead.
    expect(selection.style.left).toBe(pct(0.15));
    expect(selection.style.top).toBe(pct(0.15));
    expect(selection.style.width).toBe(pct(0.8));
    expect(selection.style.height).toBe(pct(0.8));
  });

  it("measures a drag against the image's own rendered box, not the (possibly taller) stage", async () => {
    stubCanvas();
    stubObjectUrl();
    stubImageBitmap({ width: 1000, height: 1000 });
    const { calls } = stubFetchWithCalls({
      '/api/auth/session': [{ status: 200, body: STAFF }],
      '/api/scans': [{ status: 200, body: [] }],
    });

    await reachCrop();

    // `.stage`'s own `min-height` floor (360px in the token) is taller than
    // an ordinary landscape phone photo renders at this width — 400px wide,
    // 200px tall, well under the floor. Deliberately not `stubStageGeometry`,
    // which gives every element the same box and so cannot catch a bug that
    // reads the wrong one.
    overrideRect(screen.getByTestId('crop-stage'), { width: 400, height: 360 });
    overrideRect(screen.getByAltText(/captured tile/i), { width: 400, height: 200 });

    // The default selection's bottom-right corner sits at 90% of the
    // *image's* box — (360, 180) — not 90% of the stage's taller one, which
    // would be (360, 324).
    drag(
      screen.getByTestId('crop-handle-br'),
      { clientX: 360, clientY: 180 },
      { clientX: 380, clientY: 190 },
    );

    const selection = screen.getByTestId('crop-selection');
    // dx = 20/400 = 0.05 either way, but dy = 10/200 = 0.05 only when
    // measured against the image's own 200px-tall box. Measured against the
    // stage's 360px one it would be 10/360, growing the selection to a
    // visibly different (and wrong) height than what a user watching the
    // on-screen image would see.
    expect(selection.style.width).toBe(pct(0.85));
    expect(selection.style.height).toBe(pct(0.85));

    fireEvent.click(screen.getByRole('button', { name: /confirm crop/i }));
    expect(await screen.findByRole('heading', { name: /^results$/i })).toBeTruthy();

    // The rectangle actually sent to the server carries the same, correct
    // fractions — not just the on-screen style.
    const submissions = calls.filter(([path]) => path === '/api/scans');
    const body = submissions[submissions.length - 1]?.[1].body as FormData;
    expect(body.get('crop_width')).toBe('0.85');
    expect(body.get('crop_height')).toBe('0.85');
  });
});

/** A closed `ScanCandidate`, valid enough for `isScanCandidate` to accept. */
describe('confirming a crop', () => {
  it('sends a normalized rect matching the on-screen selection, and shows the ranked candidates on Results', async () => {
    stubCanvas();
    stubObjectUrl();
    stubImageBitmap({ width: 1000, height: 1000 });
    const { calls } = stubFetchWithCalls({
      '/api/auth/session': [{ status: 200, body: STAFF }],
      '/api/scans': [
        { status: 200, body: [] },
        { status: 200, body: [A_CANDIDATE] },
      ],
    });

    await reachCrop();

    fireEvent.click(screen.getByRole('button', { name: /confirm crop/i }));

    expect(await screen.findByRole('heading', { name: /^results$/i })).toBeTruthy();
    expect(screen.queryByRole('heading', { name: /^crop$/i })).toBeNull();
    expect(screen.getByText(A_CANDIDATE.code)).toBeTruthy();
    expect(screen.getByText(/best match/i)).toBeTruthy();
    expect(document.body.textContent).not.toMatch(/\d+%|score|confidence/i);

    // The first submission was the whole frame; the crop's own is the last.
    const submissions = calls.filter(([path]) => path === '/api/scans');
    expect(submissions).toHaveLength(2);
    const body = submissions[1]?.[1].body as FormData;
    expect(body.get('crop_x')).toBe('0.1');
    expect(body.get('crop_y')).toBe('0.1');
    expect(body.get('crop_width')).toBe('0.8');
    expect(body.get('crop_height')).toBe('0.8');
    expect(body.get('image')).toBeInstanceOf(Blob);
  });

  it('shows the empty-match message with Retake and the crop when nothing matches', async () => {
    stubCanvas();
    stubImageBitmap({ width: 1000, height: 1000 });
    stubFetch({
      '/api/auth/session': [{ status: 200, body: STAFF }],
      '/api/scans': [{ status: 200, body: [] }],
    });

    await reachResults();

    expect(screen.getByText('No confident match — retake, or ask a colleague.')).toBeTruthy();
    expect(screen.queryByRole('button', { name: /^back$/i })).toBeNull();
    expect(screen.getByRole('button', { name: /adjust crop/i })).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: /^retake$/i }));

    expect(await screen.findByRole('heading', { name: /^scan$/i })).toBeTruthy();
    expect(screen.queryByRole('heading', { name: /^results$/i })).toBeNull();
  });

  it('disables Confirm and Back while the submission is in flight', async () => {
    stubCanvas();
    stubObjectUrl();
    stubImageBitmap({ width: 1000, height: 1000 });

    // The first scan (the whole frame, on the way to Results) answers at once;
    // the crop's own submission is the one held open.
    const scanResolver: { resolve: ((value: Response) => void) | null } = { resolve: null };
    let scans = 0;
    vi.stubGlobal('fetch', (input: string) => {
      if (input === '/api/auth/session') {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: () => Promise.resolve(STAFF),
        } as Response);
      }
      if (input === '/api/scans') {
        scans += 1;
        if (scans === 1) {
          return Promise.resolve({
            ok: true,
            status: 200,
            json: () => Promise.resolve([]),
          } as Response);
        }
        return new Promise<Response>((resolve) => {
          scanResolver.resolve = resolve;
        });
      }
      return Promise.resolve({
        ok: false,
        status: 404,
        json: () => Promise.resolve({ error: { code: 'not_found', message: 'No such route.' } }),
      } as Response);
    });

    await reachCrop();

    fireEvent.click(screen.getByRole('button', { name: /confirm crop/i }));

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /submitting/i })).toHaveProperty('disabled', true);
    });
    expect(screen.getByRole('button', { name: /^back$/i })).toHaveProperty('disabled', true);

    scanResolver.resolve?.({ ok: true, status: 200, json: () => Promise.resolve([]) } as Response);

    expect(await screen.findByRole('heading', { name: /^results$/i })).toBeTruthy();
  });

  it(
    'shows an inline error and re-enables Confirm on a failed submission, ' +
      'keeping the image and the selection',
    async () => {
      stubCanvas();
      stubObjectUrl();
      stubImageBitmap({ width: 1000, height: 1000 });
      stubFetch({
        '/api/auth/session': [{ status: 200, body: STAFF }],
        '/api/scans': [
          { status: 200, body: [] },
          {
            status: 500,
            body: {
              error: {
                code: 'internal_error',
                message: 'An unexpected error occurred. The incident has been logged.',
              },
            },
          },
        ],
      });

      await reachCrop();

      fireEvent.click(screen.getByRole('button', { name: /confirm crop/i }));

      expect(await screen.findByRole('alert')).toHaveProperty(
        'textContent',
        'An unexpected error occurred. The incident has been logged.',
      );
      expect(screen.getByRole('heading', { name: /^crop$/i })).toBeTruthy();
      expect(screen.getByTestId('crop-selection').style.width).toBe(pct(0.8));
      expect(screen.getByRole('button', { name: /confirm crop/i })).toHaveProperty(
        'disabled',
        false,
      );
    },
  );

  it(
    "stays on Crop with the server's own message when matching is unavailable, " +
      'keeping the image and the selection',
    async () => {
      stubCanvas();
      stubObjectUrl();
      stubImageBitmap({ width: 1000, height: 1000 });
      stubFetch({
        '/api/auth/session': [{ status: 200, body: STAFF }],
        '/api/scans': [
          { status: 200, body: [] },
          {
            status: 503,
            body: {
              error: {
                code: 'matching_unavailable',
                message: 'The image matching service is not set up on this server.',
              },
            },
          },
        ],
      });

      await reachCrop();

      fireEvent.click(screen.getByRole('button', { name: /confirm crop/i }));

      expect(await screen.findByRole('alert')).toHaveProperty(
        'textContent',
        'The image matching service is not set up on this server.',
      );
      expect(screen.getByRole('heading', { name: /^crop$/i })).toBeTruthy();
      expect(screen.getByTestId('crop-selection').style.width).toBe(pct(0.8));
      expect(screen.getByRole('button', { name: /confirm crop/i })).toHaveProperty(
        'disabled',
        false,
      );
    },
  );

  it('stays on Crop on a network failure, keeping the image and the selection', async () => {
    stubCanvas();
    stubObjectUrl();
    stubImageBitmap({ width: 1000, height: 1000 });
    let scans = 0;
    vi.stubGlobal('fetch', (input: string) => {
      if (input === '/api/auth/session') {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: () => Promise.resolve(STAFF),
        } as Response);
      }
      if (input === '/api/scans') {
        scans += 1;
        if (scans === 1) {
          return Promise.resolve({
            ok: true,
            status: 200,
            json: () => Promise.resolve([]),
          } as Response);
        }
        return Promise.reject(new Error('the network is down'));
      }
      return Promise.resolve({
        ok: false,
        status: 404,
        json: () => Promise.resolve({ error: { code: 'not_found', message: 'No such route.' } }),
      } as Response);
    });

    await reachCrop();

    fireEvent.click(screen.getByRole('button', { name: /confirm crop/i }));

    expect(await screen.findByRole('alert')).toHaveProperty(
      'textContent',
      'Could not reach the server. Check your connection and try again.',
    );
    expect(screen.getByRole('heading', { name: /^crop$/i })).toBeTruthy();
    expect(screen.getByTestId('crop-selection').style.width).toBe(pct(0.8));
    expect(screen.getByRole('button', { name: /confirm crop/i })).toHaveProperty('disabled', false);
  });
});

describe('the tap-to-fullscreen viewer', () => {
  async function openViewerFromCard(): Promise<HTMLElement> {
    stubCanvas();
    stubImageBitmap({ width: 1000, height: 1000 });
    stubFetch({
      '/api/auth/session': [{ status: 200, body: STAFF }],
      '/api/scans': [{ status: 200, body: [A_CANDIDATE] }],
    });

    await reachResults();

    const card = screen.getByRole('button', { name: new RegExp(A_CANDIDATE.code) });
    card.focus();
    fireEvent.click(card);

    expect(await screen.findByRole('dialog')).toBeTruthy();
    return card;
  }

  it.each([
    [
      'Escape',
      (): void => {
        fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape' });
      },
    ],
    [
      'a scrim click',
      (): void => {
        const scrim = screen.getByRole('dialog').parentElement;
        expect(scrim, 'the dialog is not inside a scrim').toBeTruthy();
        fireEvent.click(scrim as HTMLElement);
      },
    ],
    [
      'Close',
      (): void => {
        fireEvent.click(
          within(screen.getByRole('dialog')).getByRole('button', { name: /^close$/i }),
        );
      },
    ],
  ])(
    '%s closes the viewer and returns focus to the tapped candidate card',
    async (_label, close) => {
      const card = await openViewerFromCard();

      close();

      expect(screen.queryByRole('dialog')).toBeNull();
      expect(document.activeElement).toBe(card);
    },
  );
});

describe('the other candidates', () => {
  /** Two more Tiles from the same Category folder — AD-18's own case. */
  const A_SECOND_CANDIDATE = {
    tile_id: '33333333-3333-4333-8333-333333333333',
    code: 'RP.CMA.0008DJ.SM.0T',
    size: '45X90',
    category: 'CREMA MARMOL',
    image_id: '44444444-4444-4444-8444-444444444444',
  };
  const A_THIRD_CANDIDATE = {
    tile_id: '55555555-5555-4555-8555-555555555555',
    code: 'RP.CMA.0011DJ.SM.0T',
    size: '45X90',
    category: 'CREMA MARMOL',
    image_id: '66666666-6666-4666-8666-666666666666',
  };
  const THREE = [A_CANDIDATE, A_SECOND_CANDIDATE, A_THIRD_CANDIDATE];

  async function reachResultsWith(body: unknown[]): Promise<void> {
    stubCanvas();
    stubImageBitmap({ width: 1000, height: 1000 });
    stubFetch({
      '/api/auth/session': [{ status: 200, body: STAFF }],
      '/api/scans': [{ status: 200, body }],
    });
    await reachResults();
  }

  it('shows the best match alone, with the rest one tap away', async () => {
    await reachResultsWith(THREE);

    expect(screen.getByText(A_CANDIDATE.code)).toBeTruthy();
    expect(screen.getByText(/best match/i)).toBeTruthy();
    // Held, not discarded — but not competing with the answer either.
    expect(screen.queryByText(A_SECOND_CANDIDATE.code)).toBeNull();
    expect(screen.queryByText(A_THIRD_CANDIDATE.code)).toBeNull();

    const disclosure = screen.getByRole('button', { name: /show 2 other matches/i });
    expect(disclosure.getAttribute('aria-expanded')).toBe('false');

    fireEvent.click(disclosure);

    // Every Candidate the server sent, in the order it sent them, each its own
    // card: two from one Category folder are two different Tiles (AD-18).
    expect(screen.getByText(A_SECOND_CANDIDATE.code)).toBeTruthy();
    expect(screen.getByText(A_THIRD_CANDIDATE.code)).toBeTruthy();
    expect(
      screen.getAllByAltText(/^Reference image of /).map((img) => img.getAttribute('alt')),
    ).toEqual(THREE.map((candidate) => `Reference image of ${candidate.code}`));
    // Still exactly one best match: revealing the alternatives re-ranks nothing.
    expect(screen.getAllByText(/best match/i)).toHaveProperty('length', 1);

    const hide = screen.getByRole('button', { name: /hide other matches/i });
    expect(hide.getAttribute('aria-expanded')).toBe('true');

    fireEvent.click(hide);

    expect(screen.queryByText(A_SECOND_CANDIDATE.code)).toBeNull();
  });

  it('singularises the disclosure when the server sent only one alternative', async () => {
    await reachResultsWith([A_CANDIDATE, A_SECOND_CANDIDATE]);

    expect(screen.getByRole('button', { name: /^show 1 other match$/i })).toBeTruthy();
  });

  it('offers no disclosure when the best match is the only candidate', async () => {
    await reachResultsWith([A_CANDIDATE]);

    expect(screen.getByText(A_CANDIDATE.code)).toBeTruthy();
    expect(screen.queryByRole('button', { name: /other match/i })).toBeNull();
  });
});


/**
 * Let the size read resolve, so "no picker" is an assertion about the answer
 * rather than about the request not having landed yet.
 *
 * `session-expiry.test.ts`'s own `settle`: written out rather than looped,
 * because each microtask turn has to follow the last and `Promise.all` would
 * collapse them into one.
 */
async function settleSizes(): Promise<void> {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
  });
}

describe('the size declaration', () => {
  /**
   * The POC's largest measured accuracy lever: +3.2 points of top-3 overall
   * and +8.0 on 45X90 (`poc/README.md`), for the one attribute a photo cannot
   * carry and the person holding the tile always knows.
   *
   * These tests are about the declaration reaching the server, and about the
   * default never being a guess — a *mis*-declared size makes the true tile
   * unreachable, so "All sizes" is the only safe thing to open on.
   */
  const SIZES: Reply[] = [{ status: 200, body: ['45X90', '60X30'] }];

  async function openScanWithSizes(): Promise<[string, RequestInit][]> {
    const { calls } = stubFetchWithCalls({
      '/api/auth/session': [{ status: 200, body: STAFF }],
      '/api/scans/sizes': SIZES,
      '/api/scans': [{ status: 200, body: [A_CANDIDATE] }],
    });
    render(<App />);
    await openScan();
    await screen.findByLabelText(/tile size/i);
    return calls;
  }

  it('opens on All sizes and offers every indexed size', async () => {
    stubCamera();
    stubCanvas();
    await openScanWithSizes();

    const picker = screen.getByLabelText(/tile size/i) as HTMLSelectElement;
    expect(picker.value).toBe('');
    expect([...picker.options].map((option) => option.textContent)).toEqual([
      'All sizes',
      '45X90',
      '60X30',
    ]);
  });

  it('binds the hint to the control, so its cost is not sight-only', async () => {
    // The sentence carries what a wrong declaration does — hides the right
    // tile — and that is stated nowhere else on the screen. Bound, so a
    // screen-reader user meets it at the control rather than as a scan that
    // quietly found nothing.
    stubCamera();
    stubCanvas();
    await openScanWithSizes();

    const picker = screen.getByLabelText(/tile size/i);
    const describedBy = picker.getAttribute('aria-describedby');
    expect(describedBy).toBeTruthy();
    expect(document.getElementById(describedBy as string)?.textContent).toMatch(
      /wrong size hides the right tile/i,
    );
  });

  it('freezes the declaration while a submission is in flight', async () => {
    // A control that quietly stops responding is worse than one that is
    // visibly unavailable — and the size is part of the request already on
    // its way, so changing it mid-flight would describe a scan nobody sent.
    stubCamera();
    stubCanvas();
    let release: (() => void) | undefined;
    const held = new Promise<void>((resolve) => {
      release = resolve;
    });
    stubFetchWithCalls({
      '/api/auth/session': [{ status: 200, body: STAFF }],
      '/api/scans/sizes': [{ status: 200, body: ['45X90'] }],
      '/api/scans': [{ status: 200, body: [A_CANDIDATE] }],
    });
    const realFetch = globalThis.fetch;
    vi.stubGlobal('fetch', async (input: string, init: RequestInit = {}) => {
      if (input === '/api/scans') await held;
      return realFetch(input, init);
    });
    render(<App />);
    await openScan();
    await screen.findByLabelText(/tile size/i);

    fireEvent.click(screen.getByRole('button', { name: /enable camera/i }));
    const video = await screen.findByTestId('viewfinder-video');
    stubFrame(video);
    fireEvent.click(screen.getByRole('button', { name: /^capture$/i }));

    await waitFor(() =>
      expect((screen.getByLabelText(/tile size/i) as HTMLSelectElement).disabled).toBe(true),
    );
    release?.();
    await screen.findByRole('heading', { name: /^results$/i });
  });

  it('sends no size field at all while All sizes is selected', async () => {
    stubCamera();
    stubCanvas();
    const calls = await openScanWithSizes();

    fireEvent.click(screen.getByRole('button', { name: /enable camera/i }));
    const video = await screen.findByTestId('viewfinder-video');
    Object.defineProperty(video, 'videoWidth', { value: 800, configurable: true });
    Object.defineProperty(video, 'videoHeight', { value: 800, configurable: true });
    fireEvent.click(screen.getByRole('button', { name: /^capture$/i }));

    await screen.findByRole('heading', { name: /^results$/i });
    const body = calls.find(([path]) => path === '/api/scans')?.[1].body as FormData;
    // Absent, not empty: a submission that declares nothing should look like
    // one on the wire.
    expect(body.has('size')).toBe(false);
  });

  it('sends the declared size with the scan', async () => {
    stubCamera();
    stubCanvas();
    const calls = await openScanWithSizes();

    fireEvent.change(screen.getByLabelText(/tile size/i), { target: { value: '45X90' } });
    fireEvent.click(screen.getByRole('button', { name: /enable camera/i }));
    const video = await screen.findByTestId('viewfinder-video');
    Object.defineProperty(video, 'videoWidth', { value: 800, configurable: true });
    Object.defineProperty(video, 'videoHeight', { value: 800, configurable: true });
    fireEvent.click(screen.getByRole('button', { name: /^capture$/i }));

    await screen.findByRole('heading', { name: /^results$/i });
    const body = calls.find(([path]) => path === '/api/scans')?.[1].body as FormData;
    expect(body.get('size')).toBe('45X90');
  });

  it('keeps the declaration across the round trip back from Results', async () => {
    // The behaviour the POC gets from `localStorage`, which this app forbids
    // (`no-client-token-storage.test.ts`). Lifting the value to `App` is what
    // carries it across the unmount between two scans — which is the flow
    // that matters: a staff member working through a pallet of one size.
    stubCamera();
    stubCanvas();
    await openScanWithSizes();

    fireEvent.change(screen.getByLabelText(/tile size/i), { target: { value: '60X30' } });
    fireEvent.click(screen.getByRole('button', { name: /enable camera/i }));
    const video = await screen.findByTestId('viewfinder-video');
    Object.defineProperty(video, 'videoWidth', { value: 800, configurable: true });
    Object.defineProperty(video, 'videoHeight', { value: 800, configurable: true });
    fireEvent.click(screen.getByRole('button', { name: /^capture$/i }));
    await screen.findByRole('heading', { name: /^results$/i });

    fireEvent.click(screen.getByRole('button', { name: /^scan$/i }));

    const picker = (await screen.findByLabelText(/tile size/i)) as HTMLSelectElement;
    expect(picker.value).toBe('60X30');
  });

  it('renders no picker when the catalogue has no indexed sizes', async () => {
    stubCamera();
    stubCanvas();
    stubFetchWithCalls({
      '/api/auth/session': [{ status: 200, body: STAFF }],
      '/api/scans/sizes': [{ status: 200, body: [] }],
    });
    render(<App />);
    await openScan();

    await settleSizes();
    expect(screen.queryByLabelText(/tile size/i)).toBeNull();
  });

  it('renders no picker, and no banner, when the size list cannot be read', async () => {
    // The filter is an accuracy option. A banner about it over a live
    // viewfinder would be in the way of the one thing this screen is for.
    stubCamera();
    stubCanvas();
    stubFetchWithCalls({
      '/api/auth/session': [{ status: 200, body: STAFF }],
      '/api/scans/sizes': [{ status: 500, body: null }],
    });
    render(<App />);
    await openScan();

    await settleSizes();
    expect(screen.queryByLabelText(/tile size/i)).toBeNull();
    expect(screen.getByRole('button', { name: /enable camera/i })).toBeTruthy();
  });

  it('drops a declaration the catalogue has stopped recognising', async () => {
    // Only reachable when the catalogue changed under a screen already open,
    // so the recovery is to clear the stale choice rather than to ask the
    // staff member to fix something they did not get wrong.
    stubCamera();
    stubCanvas();
    stubFetchWithCalls({
      '/api/auth/session': [{ status: 200, body: STAFF }],
      '/api/scans/sizes': [{ status: 200, body: ['45X90'] }],
      '/api/scans': [
        {
          status: 422,
          body: {
            error: { code: 'unknown_size', message: 'That size is not in the catalogue.' },
          },
        },
      ],
    });
    render(<App />);
    await openScan();
    await screen.findByLabelText(/tile size/i);

    fireEvent.change(screen.getByLabelText(/tile size/i), { target: { value: '45X90' } });
    fireEvent.click(screen.getByRole('button', { name: /enable camera/i }));
    const video = await screen.findByTestId('viewfinder-video');
    Object.defineProperty(video, 'videoWidth', { value: 800, configurable: true });
    Object.defineProperty(video, 'videoHeight', { value: 800, configurable: true });
    fireEvent.click(screen.getByRole('button', { name: /^capture$/i }));

    expect(await screen.findByText(/not in the catalogue/i)).toBeTruthy();
    await waitFor(() =>
      expect((screen.getByLabelText(/tile size/i) as HTMLSelectElement).value).toBe(''),
    );
  });
});
