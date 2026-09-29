/**
 * Marker measurement, from the three screens that make it usable.
 *
 * Driven against a stubbed `fetch` with each screen rendered directly, which is
 * `create-user.test.tsx`'s split: these screens call `apiRequest` themselves
 * rather than going through `SessionProvider`, and the one thing that genuinely
 * lives in the gate — whether a Staff user is offered the door at all — runs
 * through `App`.
 *
 * Three assertions here are the ones nothing else in the suite can make:
 *
 * * That a Staff user is offered no door to the Markers register. The
 *   dimensions typed there scale every measurement every staff member takes,
 *   and the server refuses them regardless — but a door that renders and then
 *   403s is a worse screen than no door.
 * * That `marker_not_detected` is treated as a **fallback**, not a failure. It
 *   is the ordinary outcome of a creased card or a glare, and a screen that
 *   rendered it as a rejection would leave the manual path unreachable.
 * * That the measured Size leaves this screen through `onUseSize` and reaches
 *   nothing else. AD-19 makes a declared Size a hard pre-filter, so a
 *   measurement wired straight into the search would make a mis-measured tile
 *   unreachable rather than merely lower-ranked.
 */
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import App from '../App';
import { MarkerFormScreen } from '../screens/MarkerFormScreen';
import { MarkerListScreen } from '../screens/MarkerListScreen';
import { MeasureScreen } from '../screens/MeasureScreen';
import { ResultsScreen } from '../screens/ResultsScreen';
import type { Marker } from '@rocell/schema/marker';
import type { User } from '@rocell/schema/user';

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const CARD: Marker = {
  id: '3f8c1e5a-9b2d-4c7e-8a1f-6d0b4e2c9a37',
  name: 'Bank card',
  width_mm: 85.6,
  height_mm: 53.98,
  aruco_dictionary: null,
  aruco_id: null,
  created_at: '2026-09-28T09:00:00Z',
  updated_at: '2026-09-28T09:00:00Z',
};

const FIDUCIAL: Marker = {
  ...CARD,
  id: 'b41d8e06-5a72-4f39-9c88-0d3e1f7a2b65',
  name: 'Rocell marker card',
  width_mm: 100,
  height_mm: 100,
  aruco_dictionary: 'DICT_4X4_50',
  aruco_id: 7,
};

const ADMIN: User = {
  id: '9c2f1e4a-7b3d-4c58-9e10-2a6f8d4b1c07',
  name: 'Ruwan Jayasuriya',
  email: 'ruwan@rocell.lk',
  role: 'admin',
  active: true,
  must_change_password: false,
  temp_credential_expires_at: null,
  last_login_at: '2026-09-18T08:00:00Z',
  locked_until: null,
  created_at: '2026-09-17T08:00:00Z',
  updated_at: '2026-09-18T08:00:00Z',
};

const STAFF: User = { ...ADMIN, id: '3f1a6b2c-9d4e-4f70-8a11-5c2e7b9d0a34', role: 'staff' };

interface Reply {
  status: number;
  body?: unknown;
}

/** `create-user.test.tsx`'s stub, keyed by method and path. A local copy, as
 *  every other suite keeps its own: a stub shared across files is a fixture two
 *  tests can change under each other. */
function stubFetch(replies: Record<string, Reply[]>): { calls: [string, RequestInit][] } {
  const calls: [string, RequestInit][] = [];

  vi.stubGlobal('fetch', (input: string, init: RequestInit = {}) => {
    calls.push([input, init]);
    const queued = replies[`${init.method ?? 'GET'} ${input}`];
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

const refusal = (code: string, message: string, status: number): Reply => ({
  status,
  body: { error: { code, message } },
});

const noop = (): void => undefined;



/** The body of the nth request, parsed. */
function jsonBody(calls: [string, RequestInit][], index: number): Record<string, unknown> {
  return JSON.parse(String(calls[index]?.[1].body)) as Record<string, unknown>;
}

describe('the Markers register', () => {
  it('lists every registered marker with its dimensions', async () => {
    stubFetch({ 'GET /api/admin/markers': [{ status: 200, body: [CARD, FIDUCIAL] }] });

    render(<MarkerListScreen onBack={noop} onAdd={noop} onEdit={noop} />);

    expect(await screen.findByText('Bank card')).toBeTruthy();
    // The millimetres, because they are what a reader checks against the card
    // in their hand — not a name alone.
    expect(screen.getByText('85.6 × 53.98 mm')).toBeTruthy();
    expect(screen.getByText('Rocell marker card')).toBeTruthy();
  });

  it('says how each marker is found, including the ones that are not', async () => {
    // "Nothing here" on a plain object would read as a value that failed to
    // load rather than as the ordinary, supported case it is.
    stubFetch({ 'GET /api/admin/markers': [{ status: 200, body: [CARD, FIDUCIAL] }] });

    render(<MarkerListScreen onBack={noop} onAdd={noop} onEdit={noop} />);

    expect(await screen.findByText(/no printed fiducial/i)).toBeTruthy();
    expect(screen.getByText(/DICT_4X4_50, id 7/)).toBeTruthy();
  });

  it('says what an empty register means for the Scan screen', async () => {
    stubFetch({ 'GET /api/admin/markers': [{ status: 200, body: [] }] });

    render(<MarkerListScreen onBack={noop} onAdd={noop} onEdit={noop} />);

    expect(await screen.findByText(/no markers are registered/i)).toBeTruthy();
  });

  it("renders the API's own sentence when the read fails", async () => {
    // EXPERIENCE.md:87 — the screen never composes its own version of a rule
    // it does not own.
    stubFetch({
      'GET /api/admin/markers': [refusal('administrator_required', 'Administrators only.', 403)],
    });

    render(<MarkerListScreen onBack={noop} onAdd={noop} onEdit={noop} />);

    expect((await screen.findByRole('alert')).textContent).toContain('Administrators only.');
  });

  it('confirms before removing, and says no scan is affected', async () => {
    const { calls } = stubFetch({
      'GET /api/admin/markers': [{ status: 200, body: [CARD] }, { status: 200, body: [] }],
      [`DELETE /api/admin/markers/${CARD.id}`]: [{ status: 204 }],
    });

    render(<MarkerListScreen onBack={noop} onAdd={noop} onEdit={noop} />);
    fireEvent.click(await screen.findByRole('button', { name: /Remove Bank card/ }));

    // The sentence that matters: removing a ruler changes no past scan,
    // because a measurement is never stored.
    expect(await screen.findByText(/No scan or catalogue entry is affected/)).toBeTruthy();
    // Nothing is written until the dialog is confirmed.
    expect(calls.some(([, init]) => init.method === 'DELETE')).toBe(false);

    fireEvent.click(screen.getByRole('button', { name: 'Remove' }));

    await waitFor(() => {
      expect(calls.some(([url, init]) => init.method === 'DELETE' && url.endsWith(CARD.id))).toBe(
        true,
      );
    });
  });
});

describe('registering and correcting a marker', () => {
  it('sends the four fields, with the fiducial pair explicitly empty', async () => {
    const { calls } = stubFetch({ 'POST /api/admin/markers': [{ status: 201, body: CARD }] });

    render(<MarkerFormScreen marker={null} onSaved={noop} onCancel={noop} />);
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Bank card' } });
    fireEvent.change(screen.getByLabelText('Width (mm)'), { target: { value: '85.6' } });
    fireEvent.change(screen.getByLabelText('Height (mm)'), { target: { value: '53.98' } });
    fireEvent.click(screen.getByRole('button', { name: 'Register marker' }));

    await waitFor(() => {
      expect(calls.length).toBe(1);
    });
    expect(jsonBody(calls, 0)).toEqual({
      name: 'Bank card',
      width_mm: 85.6,
      height_mm: 53.98,
      // Sent as `null` rather than omitted: on the edit path an omitted key
      // means "keep", and a form that could not distinguish the two would be
      // unable to clear a fiducial.
      aruco_dictionary: null,
      aruco_id: null,
    });
  });

  it('warns that the black square is what gets measured, not the paper', () => {
    // The one hint on this form that carries real risk: measuring the paper
    // inflates every result by the quiet zone's width, silently.
    stubFetch({});

    render(<MarkerFormScreen marker={null} onSaved={noop} onCancel={noop} />);

    expect(screen.getByText(/printed black square itself, not the paper/i)).toBeTruthy();
  });

  it('asks for a marker id only once a dictionary is chosen', () => {
    stubFetch({});

    render(<MarkerFormScreen marker={null} onSaved={noop} onCancel={noop} />);
    expect(screen.queryByLabelText('Marker id')).toBeNull();

    fireEvent.change(screen.getByLabelText('Dictionary'), { target: { value: 'DICT_4X4_50' } });

    expect(screen.getByLabelText('Marker id')).toBeTruthy();
    // And it states the range that family actually holds, because an
    // Administrator has to pick the number before they print the card.
    expect(screen.getByText(/holds ids 0 to 49/)).toBeTruthy();
  });

  it('corrects an existing marker with a PATCH to its own id', async () => {
    const { calls } = stubFetch({
      [`PATCH /api/admin/markers/${FIDUCIAL.id}`]: [{ status: 200, body: FIDUCIAL }],
    });

    render(<MarkerFormScreen marker={FIDUCIAL} onSaved={noop} onCancel={noop} />);
    // The form opens on what is stored, so a correction is an edit rather than
    // a retype.
    expect((screen.getByLabelText('Name') as HTMLInputElement).value).toBe('Rocell marker card');
    expect((screen.getByLabelText('Marker id') as HTMLInputElement).value).toBe('7');

    fireEvent.change(screen.getByLabelText('Width (mm)'), { target: { value: '99' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }));

    await waitFor(() => {
      expect(calls.length).toBe(1);
    });
    expect(calls[0]?.[1].method).toBe('PATCH');
    expect(jsonBody(calls, 0)['width_mm']).toBe(99);
  });

  it("renders the API's own sentence when the save is refused", async () => {
    stubFetch({
      'POST /api/admin/markers': [
        refusal('duplicate_marker_name', 'A marker with that name is already registered.', 409),
      ],
    });

    render(<MarkerFormScreen marker={null} onSaved={noop} onCancel={noop} />);
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Bank card' } });
    fireEvent.change(screen.getByLabelText('Width (mm)'), { target: { value: '85.6' } });
    fireEvent.change(screen.getByLabelText('Height (mm)'), { target: { value: '53.98' } });
    fireEvent.click(screen.getByRole('button', { name: 'Register marker' }));

    expect((await screen.findByRole('alert')).textContent).toContain(
      'A marker with that name is already registered.',
    );
  });
});

/**
 * Wait until the proposal has seeded the quad.
 *
 * Measure stays disabled until four corners exist, so waiting for the marker
 * picker is not enough — the click would land on a disabled button and the
 * test would assert against a request that was never made.
 */
async function waitForCorners(container: HTMLElement): Promise<void> {
  await waitFor(() => {
    expect(container.querySelector('polygon')).toBeTruthy();
  });
}

/** The quad the server proposes, normalized — deliberately *not* the tile. */
const PROPOSAL = {
  corners: [
    { x: 0.2, y: 0.2 },
    { x: 0.8, y: 0.2 },
    { x: 0.8, y: 0.8 },
    { x: 0.2, y: 0.8 },
  ],
  detected: true,
  marker: [
    { x: 0.45, y: 0.45 },
    { x: 0.55, y: 0.45 },
    { x: 0.55, y: 0.55 },
    { x: 0.45, y: 0.55 },
  ],
  // A plain scale — 1 normalized unit to 1000 mm on each axis — so the
  // proposal's 0.2–0.8 quad reads as 600 × 600 mm and the assertions below can
  // be checked by hand.
  homography: [1000, 0, 0, 0, 1000, 0, 0, 0, 1],
};

const MEASURED = {
  short_mm: 301.4,
  long_mm: 598.2,
  matched_size: '60X30',
  auto_detected: true,
};


function surface(): HTMLElement {
  return screen.getByRole('application', { name: /tile being measured/i });
}

/** Drag the corner nearest the start point over to the end point. */
function dragCorner(from: [number, number], to: [number, number]): void {
  const el = surface();
  fireEvent.pointerDown(el, { clientX: from[0], clientY: from[1], pointerId: 1 });
  fireEvent.pointerMove(el, { clientX: to[0], clientY: to[1], pointerId: 1 });
  fireEvent.pointerUp(el, { pointerId: 1 });
}

const photo = (): Blob => new Blob(['photo'], { type: 'image/jpeg' });

describe('measuring a tile', () => {
  /**
   * jsdom lays nothing out, so a pointer would divide by a zero-sized box and
   * the screen's own guard would discard it. This gives the photo a size, so
   * the normalized coordinates a drag produces are the ones a phone produces —
   * and stubs `setPointerCapture`, which jsdom does not implement.
   */
  function layOutTheCanvas(): void {
    vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({
      left: 0,
      top: 0,
      width: 400,
      height: 300,
      right: 400,
      bottom: 300,
      x: 0,
      y: 0,
      toJSON: () => ({}),
    } as DOMRect);
    Element.prototype.setPointerCapture = vi.fn();
    vi.stubGlobal('URL', {
      ...URL,
      createObjectURL: () => 'blob:photo',
      revokeObjectURL: noop,
    });
  }



  it('opens on the corners the server proposes, ready to measure', async () => {
    layOutTheCanvas();
    stubFetch({
      'GET /api/scans/markers': [{ status: 200, body: [FIDUCIAL] }],
      'POST /api/scans/propose': [{ status: 200, body: PROPOSAL }],
    });

    const { container } = render(
      <MeasureScreen initialImage={photo()} onUseSize={noop} onBack={noop} />,
    );

    // Four handles, from the proposal, without a single tap.
    await waitFor(() => {
      expect(container.querySelectorAll('span[style*="left"]').length).toBeGreaterThanOrEqual(4);
    });
    // And the copy never claims the proposal is right — on real showroom
    // photos it usually is not.
    expect(screen.getByText(/Drag each corner onto the tile’s corner/)).toBeTruthy();
    expect(screen.queryByText(/found your tile/i)).toBeNull();
  });

  it('draws the marker it is scaled by, and says why', async () => {
    // Everything downstream is scaled by this quadrilateral. A detector that
    // locked onto something other than the printed square produces
    // millimetres wrong by that ratio, and nothing else on the screen would
    // show it — so it is drawn, and labelled.
    layOutTheCanvas();
    stubFetch({
      'GET /api/scans/markers': [{ status: 200, body: [FIDUCIAL] }],
      'POST /api/scans/propose': [{ status: 200, body: PROPOSAL }],
    });

    const { container } = render(
      <MeasureScreen initialImage={photo()} onUseSize={noop} onBack={noop} />,
    );
    await waitForCorners(container);

    const shapes = [...container.querySelectorAll('polygon')].map((p) => p.getAttribute('points'));
    expect(shapes).toContain('45.00,45.00 55.00,45.00 55.00,55.00 45.00,55.00');
    expect(screen.getByText(/outline is the marker the measurement is scaled by/i)).toBeTruthy();
  });

  it('shows what the corners currently measure, and follows a drag', async () => {
    // The point of the readout: drag until it says the size on the sticker,
    // rather than pressing Measure to find out whether you are close.
    layOutTheCanvas();
    stubFetch({
      'GET /api/scans/markers': [{ status: 200, body: [FIDUCIAL] }],
      'POST /api/scans/propose': [{ status: 200, body: PROPOSAL }],
    });

    const { container } = render(
      <MeasureScreen initialImage={photo()} onUseSize={noop} onBack={noop} />,
    );
    await waitForCorners(container);

    // 0.2–0.8 of the unit square, scaled by 1000 mm, is 600 × 600.
    expect(screen.getByText('Currently 600 × 600 mm')).toBeTruthy();

    // Pull the top-left corner out to the origin and the readout follows —
    // which is the whole point of it being there.
    dragCorner([84, 64], [0, 0]);

    expect(screen.queryByText('Currently 600 × 600 mm')).toBeNull();
    expect(screen.getByText(/^Currently \d+ × \d+ mm$/)).toBeTruthy();
  });

  it('measures a tap against the photo, not the box around it', async () => {
    // **The letterbox bug, pinned.** A portrait photo inside a full-width box
    // is painted narrower than the box. Reading a tap off the box then puts
    // every corner somewhere it was not placed — no error at the centre,
    // growing toward the edges, which is where a tile's corners are. It reads
    // as a measurement that is wrong for no visible reason.
    vi.stubGlobal('URL', {
      ...URL,
      createObjectURL: () => 'blob:photo',
      revokeObjectURL: noop,
    });
    Element.prototype.setPointerCapture = vi.fn();
    // The container is 400 wide; the picture inside it is 200 wide, offset by
    // 100 — exactly what `object-fit: contain` does to a portrait photo.
    vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (
      this: HTMLElement,
    ) {
      const picture = this.tagName === 'IMG';
      return {
        left: picture ? 100 : 0,
        top: 0,
        width: picture ? 200 : 400,
        height: 300,
        right: picture ? 300 : 400,
        bottom: 300,
        x: picture ? 100 : 0,
        y: 0,
        toJSON: () => ({}),
      } as DOMRect;
    });
    stubFetch({
      'GET /api/scans/markers': [{ status: 200, body: [FIDUCIAL] }],
      'POST /api/scans/propose': [{ status: 200, body: PROPOSAL }],
    });

    const { container } = render(
      <MeasureScreen initialImage={photo()} onUseSize={noop} onBack={noop} />,
    );
    await waitForCorners(container);

    // Tap the picture's own left edge. Against the picture that is x = 0;
    // against the container it would be 100/400 = 0.25.
    fireEvent.pointerDown(surface(), { clientX: 100, clientY: 0, pointerId: 1 });
    fireEvent.pointerUp(surface(), { pointerId: 1 });

    const points = container.querySelector('polygon')?.getAttribute('points') ?? '';
    expect(points).toContain('0.00,0.00');
    expect(points).not.toContain('25.00,0.00');
  });

  it('falls back to a default quad when the proposal is refused', async () => {
    // A refusal is not surfaced: the staff member would be dragging corners
    // either way, and a rejection they cannot act on is noise.
    layOutTheCanvas();
    stubFetch({
      'GET /api/scans/markers': [{ status: 200, body: [FIDUCIAL] }],
      'POST /api/scans/propose': [
        refusal('marker_not_detected', 'The marker was not found in the photo.', 422),
      ],
    });

    const { container } = render(
      <MeasureScreen initialImage={photo()} onUseSize={noop} onBack={noop} />,
    );

    await waitFor(() => {
      expect(container.querySelectorAll('span[style*="left"]').length).toBeGreaterThanOrEqual(4);
    });
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('moves the nearest corner to a tap, and keeps moving it on a drag', async () => {
    layOutTheCanvas();
    stubFetch({
      'GET /api/scans/markers': [{ status: 200, body: [FIDUCIAL] }],
      'POST /api/scans/propose': [{ status: 200, body: PROPOSAL }],
    });

    const { container } = render(
      <MeasureScreen initialImage={photo()} onUseSize={noop} onBack={noop} />,
    );
    await waitFor(() => {
      expect(container.querySelector('polygon')).toBeTruthy();
    });
    const before = container.querySelector('polygon')?.getAttribute('points');

    // 0.2,0.2 of a 400x300 box is (80, 60); drag that corner to (10, 10).
    dragCorner([84, 64], [10, 10]);

    const after = container.querySelector('polygon')?.getAttribute('points');
    expect(after).not.toBe(before);
    expect(after).toContain('2.50,3.33');
  });

  it('measures the corners as adjusted, and offers the matched size', async () => {
    layOutTheCanvas();
    const used: string[] = [];
    const { calls } = stubFetch({
      'GET /api/scans/markers': [{ status: 200, body: [FIDUCIAL] }],
      'POST /api/scans/propose': [{ status: 200, body: PROPOSAL }],
      'POST /api/scans/measure': [{ status: 200, body: MEASURED }],
    });

    const { container } = render(
      <MeasureScreen initialImage={photo()} onUseSize={(size) => used.push(size)} onBack={noop} />,
    );
    await waitForCorners(container);
    fireEvent.click(screen.getByRole('button', { name: 'Measure' }));

    expect(await screen.findByText('301 × 598 mm')).toBeTruthy();
    expect(screen.getByText('Matches 60X30')).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: 'Use 60X30' }));

    // The Size leaves through the callback and nowhere else — nothing here
    // submits a scan (AD-19).
    expect(used).toEqual(['60X30']);
    expect(calls.every(([url]) => !url.endsWith('/scans'))).toBe(true);
  });

  it('treats a missing fiducial as a fallback, not a failure', async () => {
    layOutTheCanvas();
    stubFetch({
      'GET /api/scans/markers': [{ status: 200, body: [FIDUCIAL] }],
      'POST /api/scans/propose': [{ status: 200, body: PROPOSAL }],
      'POST /api/scans/measure': [
        refusal(
          'marker_not_detected',
          'The marker was not found in the photo. Tap its four corners instead.',
          422,
        ),
        { status: 200, body: { ...MEASURED, auto_detected: false } },
      ],
    });

    const { container } = render(
      <MeasureScreen initialImage={photo()} onUseSize={noop} onBack={noop} />,
    );
    await waitForCorners(container);
    fireEvent.click(screen.getByRole('button', { name: 'Measure' }));

    // Rendered as the next instruction rather than as a rejection: a creased
    // or glared-out card is ordinary, and the manual path exists for it.
    expect(await screen.findByText(/Tap the marker’s four corners too/)).toBeTruthy();
    expect(screen.queryByRole('alert')).toBeNull();

    for (const [x, y] of [
      [40, 30],
      [360, 30],
      [360, 270],
      [40, 270],
    ]) {
      fireEvent.pointerDown(surface(), { clientX: x, clientY: y, pointerId: 1 });
      fireEvent.pointerUp(surface(), { pointerId: 1 });
    }
    fireEvent.click(screen.getByRole('button', { name: 'Measure' }));

    expect(await screen.findByText('Matches 60X30')).toBeTruthy();
    expect(screen.getByText(/corners you tapped/i)).toBeTruthy();
  });

  it('reports millimetres even when no catalogue size matches', async () => {
    layOutTheCanvas();
    stubFetch({
      'GET /api/scans/markers': [{ status: 200, body: [FIDUCIAL] }],
      'POST /api/scans/propose': [{ status: 200, body: PROPOSAL }],
      'POST /api/scans/measure': [
        {
          status: 200,
          body: { short_mm: 812, long_mm: 1620, matched_size: null, auto_detected: true },
        },
      ],
    });

    const { container } = render(
      <MeasureScreen initialImage={photo()} onUseSize={noop} onBack={noop} />,
    );
    await waitForCorners(container);
    fireEvent.click(screen.getByRole('button', { name: 'Measure' }));

    // Never "the nearest size anyway" — a 300mm-out nearest is a wrong answer
    // wearing a right answer's clothes.
    expect(await screen.findByText(/No catalogue size matches/)).toBeTruthy();
    expect(screen.getByText('812 × 1620 mm')).toBeTruthy();
    expect(screen.queryByRole('button', { name: /^Use / })).toBeNull();
  });

  it("renders the API's own sentence when the geometry is refused", async () => {
    layOutTheCanvas();
    stubFetch({
      'GET /api/scans/markers': [{ status: 200, body: [FIDUCIAL] }],
      'POST /api/scans/propose': [{ status: 200, body: PROPOSAL }],
      'POST /api/scans/measure': [
        refusal(
          'measurement_refused',
          'That does not measure as a rectangle. The marker has to lie flat on the tile.',
          422,
        ),
      ],
    });

    const { container } = render(
      <MeasureScreen initialImage={photo()} onUseSize={noop} onBack={noop} />,
    );
    await waitForCorners(container);
    fireEvent.click(screen.getByRole('button', { name: 'Measure' }));

    expect((await screen.findByRole('alert')).textContent).toContain('lie flat on the tile');
  });

  it('asks for a photograph when there is no frame to inherit', async () => {
    layOutTheCanvas();
    stubFetch({ 'GET /api/scans/markers': [{ status: 200, body: [FIDUCIAL] }] });

    render(<MeasureScreen initialImage={null} onUseSize={noop} onBack={noop} />);
    await screen.findByRole('option', { name: /Rocell marker card/ });

    expect(screen.getByText(/Lay the marker flat on the tile/)).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Take a photo' })).toBeTruthy();
    expect(screen.queryByRole('application', { name: /tile being measured/i })).toBeNull();
  });

  it('says so when nothing is registered to measure against', async () => {
    layOutTheCanvas();
    stubFetch({ 'GET /api/scans/markers': [{ status: 200, body: [] }] });

    render(<MeasureScreen initialImage={null} onUseSize={noop} onBack={noop} />);

    expect(await screen.findByText(/no markers are registered/i)).toBeTruthy();
  });
});

describe('the door to Measure on the Results screen', () => {
  const CANDIDATE = {
    tile_id: '7c1d2e3f-4a5b-4c6d-8e9f-0a1b2c3d4e5f',
    code: 'RP.CMA.0001DJ.SM.0T',
    size: '60X30',
    category: 'CREMA MARMOL',
    image_id: '8d2e3f4a-5b6c-4d7e-9f0a-1b2c3d4e5f60',
  };

  it('is offered when a frame is held', () => {
    // This is where the ambiguity a ruler resolves becomes visible: `45X90`
    // and `60X30` are both 2:1, so candidates disagreeing about Size are the
    // moment to reach for one.
    const pressed: string[] = [];
    render(
      <ResultsScreen
        candidates={[CANDIDATE]}
        onBack={noop}
        onMeasure={() => pressed.push('measure')}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: /Measure the tile/ }));

    expect(pressed).toEqual(['measure']);
  });

  it('is not offered when no frame is held', () => {
    // `onAdjustCrop`'s own arrangement: a control that would measure nothing
    // is not rendered rather than rendered and refused.
    render(<ResultsScreen candidates={[CANDIDATE]} onBack={noop} />);

    expect(screen.queryByRole('button', { name: /Measure the tile/ })).toBeNull();
  });
});

describe('who is offered the Markers register', () => {
  it('offers an Administrator the door from the home panel', async () => {
    stubFetch({
      'GET /api/auth/session': [{ status: 200, body: ADMIN }],
      'GET /api/admin/markers': [{ status: 200, body: [CARD] }],
    });

    render(<App />);
    fireEvent.click(await screen.findByRole('button', { name: 'Home' }));
    fireEvent.click(await screen.findByRole('button', { name: /Manage measuring markers/ }));

    expect(await screen.findByRole('heading', { name: 'Markers' })).toBeTruthy();
  });

  it('offers a Staff user no door at all', async () => {
    // A convenience, not the control: the server refuses a Staff caller at
    // every `/admin/markers` route regardless (AGENTS.md Policy). A door that
    // renders and then 403s is a worse screen than no door.
    stubFetch({ 'GET /api/auth/session': [{ status: 200, body: STAFF }] });

    render(<App />);
    fireEvent.click(await screen.findByRole('button', { name: 'Home' }));

    await screen.findByText(/Signed in as/);
    expect(screen.queryByRole('button', { name: /Manage measuring markers/ })).toBeNull();
  });
});
