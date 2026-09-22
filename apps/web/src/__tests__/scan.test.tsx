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
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
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
    // Crop is inert: one Back control, no accent action, no "Confirm Crop".
    expect(screen.getByRole('button', { name: /^back$/i })).toBeTruthy();
    expect(screen.queryByRole('button', { name: /confirm/i })).toBeNull();
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
    expect(screen.queryByRole('button', { name: /confirm/i })).toBeNull();
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
