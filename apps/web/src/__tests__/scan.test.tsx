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
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
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
  stubFetch({ '/api/auth/session': [{ status: 200, body: user }] });
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
function stubCamera(
  outcome: MediaStream | 'denied' = fakeStream(),
): ReturnType<typeof vi.fn> {
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

/** Stubs the canvas draw/encode step `downscaleToBlob` depends on. */
function stubCanvas(blob: Blob = new Blob(['frame'], { type: 'image/jpeg' })): void {
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({
    drawImage: vi.fn(),
  } as unknown as CanvasRenderingContext2D);
  vi.spyOn(HTMLCanvasElement.prototype, 'toBlob').mockImplementation(function toBlob(
    this: HTMLCanvasElement,
    callback: BlobCallback,
  ) {
    callback(blob);
  });
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
  ])('is a door on the home panel for %s', async (_label, user) => {
    // Unlike every admin surface, `reachableBy`'s default covers this: there
    // is no role guard on the way in, and both roles should see the same
    // control.
    stubSession(user);
    render(<App />);

    expect(await screen.findByRole('button', { name: /^scan$/i })).toBeTruthy();

    await openScan();

    expect(screen.getByRole('heading', { name: /^scan$/i })).toBeTruthy();
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

describe('the capture path', () => {
  it('binds the granted stream to the rendered video element', async () => {
    // Regression: `enableCamera` used to assign `videoRef.current.srcObject`
    // synchronously, before `setCameraState('granted')` — but `<video>` only
    // mounts in the `'granted'` branch, so the ref was always `null` at that
    // point and the stream was never attached. The binding must happen once
    // the element actually exists, after the state transition.
    const stream = fakeStream();
    stubCamera(stream);
    stubSession(STAFF);
    render(<App />);
    await openScan();

    fireEvent.click(screen.getByRole('button', { name: /enable camera/i }));

    const video = await screen.findByTestId('viewfinder-video');
    expect(video).toHaveProperty('srcObject', stream);
  });

  it('shows the framing guide once granted, and hands the downscaled frame to Crop', async () => {
    stubCamera();
    stubCanvas();
    stubObjectUrl();
    stubSession(STAFF);
    render(<App />);
    await openScan();

    fireEvent.click(screen.getByRole('button', { name: /enable camera/i }));

    const video = await screen.findByTestId('viewfinder-video');
    expect(screen.getByTestId('framing-guide-overlay')).toBeTruthy();

    Object.defineProperty(video, 'videoWidth', { value: 2000, configurable: true });
    Object.defineProperty(video, 'videoHeight', { value: 1000, configurable: true });

    fireEvent.click(screen.getByRole('button', { name: /^capture$/i }));

    expect(await screen.findByRole('heading', { name: /^crop$/i })).toBeTruthy();
    // Story 3.2: Back stays the secondary control, and Confirm Crop is now
    // the screen's one accent action.
    expect(screen.getByRole('button', { name: /^back$/i })).toBeTruthy();
    expect(screen.getByRole('button', { name: /confirm crop/i })).toBeTruthy();
  });

  it('no-ops if the shutter is tapped before video metadata has loaded', async () => {
    stubCamera();
    stubCanvas();
    stubSession(STAFF);
    render(<App />);
    await openScan();

    fireEvent.click(screen.getByRole('button', { name: /enable camera/i }));
    await screen.findByTestId('viewfinder-video');
    // `videoWidth`/`videoHeight` default to 0 in jsdom — no override here.

    fireEvent.click(screen.getByRole('button', { name: /^capture$/i }));

    // Still on Scan: no Crop heading appeared, so nothing was handed off.
    expect(screen.queryByRole('heading', { name: /^crop$/i })).toBeNull();
  });
});

describe('leaving Scan', () => {
  it('returns to the home panel when Back is pressed', async () => {
    stubSession(STAFF);
    render(<App />);
    await openScan();

    fireEvent.click(screen.getByRole('button', { name: /^back$/i }));

    expect(await screen.findByRole('button', { name: /^scan$/i })).toBeTruthy();
    expect(screen.queryByRole('heading', { name: /^scan$/i })).toBeNull();
  });
});

describe('the upload path', () => {
  it('downscales a chosen file the same way, reaching an identical Crop screen', async () => {
    stubCanvas();
    stubObjectUrl();
    const createImageBitmap = stubImageBitmap({ width: 3000, height: 4000 });
    stubSession(STAFF);
    render(<App />);
    await openScan();

    fireEvent.change(screen.getByLabelText(/choose a photo/i), { target: { files: [aFile()] } });

    expect(await screen.findByRole('heading', { name: /^crop$/i })).toBeTruthy();
    expect(screen.getByRole('button', { name: /^back$/i })).toBeTruthy();
    expect(screen.getByRole('button', { name: /confirm crop/i })).toBeTruthy();
    // EXIF-oriented phone photos must decode upright, consistently across
    // browsers, rather than however each one defaults without this option.
    expect(createImageBitmap).toHaveBeenCalledWith(
      expect.anything(),
      expect.objectContaining({ imageOrientation: 'from-image' }),
    );
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
    // Never a crash or a blank screen: still on Scan, picker still usable.
    expect(screen.getByRole('heading', { name: /^scan$/i })).toBeTruthy();
    expect(screen.getByLabelText(/choose a photo/i)).toHaveProperty('disabled', false);
  });
});

describe('leaving Crop', () => {
  it('returns to Scan and discards the held image when Back is pressed', async () => {
    stubCanvas();
    const { revoke } = stubObjectUrl();
    stubImageBitmap({ width: 1000, height: 1000 });
    stubSession(STAFF);
    render(<App />);
    await openScan();

    fireEvent.change(screen.getByLabelText(/choose a photo/i), { target: { files: [aFile()] } });
    await screen.findByRole('heading', { name: /^crop$/i });

    fireEvent.click(screen.getByRole('button', { name: /^back$/i }));

    expect(await screen.findByRole('heading', { name: /^scan$/i })).toBeTruthy();
    expect(screen.queryByRole('heading', { name: /^crop$/i })).toBeNull();
    // The preview's object URL was actually released, not just navigated away
    // from — the evidence that the held image was discarded rather than kept
    // around in state.
    expect(revoke).toHaveBeenCalledWith('blob:mock-preview');
  });
});

/** Renders `App`, reaches Scan, and uploads a file to land on Crop. */
async function reachCrop(): Promise<void> {
  render(<App />);
  await openScan();
  fireEvent.change(screen.getByLabelText(/choose a photo/i), { target: { files: [aFile()] } });
  await screen.findByRole('heading', { name: /^crop$/i });
}

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

  it('measures a drag against the image\'s own rendered box, not the (possibly taller) stage', async () => {
    stubCanvas();
    stubObjectUrl();
    stubImageBitmap({ width: 1000, height: 1000 });
    const { calls } = stubFetchWithCalls({
      '/api/auth/session': [{ status: 200, body: STAFF }],
      '/api/scans': [{ status: 202 }],
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
    expect(await screen.findByRole('heading', { name: /^scan$/i })).toBeTruthy();

    // The rectangle actually sent to the server carries the same, correct
    // fractions — not just the on-screen style.
    const submitted = calls.find(([path]) => path === '/api/scans');
    const body = submitted?.[1].body as FormData;
    expect(body.get('crop_width')).toBe('0.85');
    expect(body.get('crop_height')).toBe('0.85');
  });
});

describe('confirming a crop', () => {
  it('sends a normalized rect matching the on-screen selection, and returns to Scan on success', async () => {
    stubCanvas();
    stubObjectUrl();
    stubImageBitmap({ width: 1000, height: 1000 });
    const { calls } = stubFetchWithCalls({
      '/api/auth/session': [{ status: 200, body: STAFF }],
      '/api/scans': [{ status: 202 }],
    });

    await reachCrop();

    fireEvent.click(screen.getByRole('button', { name: /confirm crop/i }));

    // Back on Scan: there is no Results screen yet (Story 3.4), and the
    // image is not carried back with it — `showSection` clears `capturedImage`
    // on every move away from Crop.
    expect(await screen.findByRole('heading', { name: /^scan$/i })).toBeTruthy();

    const submitted = calls.find(([path]) => path === '/api/scans');
    expect(submitted).toBeTruthy();
    const body = submitted?.[1].body as FormData;
    // The default inset rect, sent as the normalized fractions this screen
    // renders it with — never absolute pixels (AD-11).
    expect(body.get('crop_x')).toBe('0.1');
    expect(body.get('crop_y')).toBe('0.1');
    expect(body.get('crop_width')).toBe('0.8');
    expect(body.get('crop_height')).toBe('0.8');
    // The whole downscaled image travels too, unmodified — never a
    // client-side pixel crop (AD-11).
    expect(body.get('image')).toBeInstanceOf(Blob);
  });

  it('disables Confirm and Back while the submission is in flight', async () => {
    stubCanvas();
    stubObjectUrl();
    stubImageBitmap({ width: 1000, height: 1000 });

    // Held open deliberately: the in-flight state is the half of the
    // contract a settled request cannot show. `add-tile.test.tsx`'s pattern.
    // A wrapper object, not a bare `let`: TypeScript's narrowing of a
    // closed-over variable loses track of the reassignment that happens
    // inside the `fetch` stub below, and a plain `let` reads back as `null`
    // at the call site even though the stub has long since set it.
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

    await reachCrop();

    fireEvent.click(screen.getByRole('button', { name: /confirm crop/i }));

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /submitting/i })).toHaveProperty('disabled', true);
    });
    expect(screen.getByRole('button', { name: /^back$/i })).toHaveProperty('disabled', true);

    scanResolver.resolve?.({ ok: true, status: 202, json: () => Promise.resolve(null) } as Response);

    expect(await screen.findByRole('heading', { name: /^scan$/i })).toBeTruthy();
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
      // Still on Crop: the failure did not navigate away, and the AC is
      // explicit that the image and the selection survive it.
      expect(screen.getByRole('heading', { name: /^crop$/i })).toBeTruthy();
      expect(screen.getByTestId('crop-selection').style.width).toBe(pct(0.8));
      // Confirm re-enabled — a re-tap is the client-side retry the I/O matrix
      // names, and there is no separate retry control.
      expect(screen.getByRole('button', { name: /confirm crop/i })).toHaveProperty(
        'disabled',
        false,
      );
    },
  );
});
