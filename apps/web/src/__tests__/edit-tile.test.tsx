/**
 * Edit tile — the screen, and the route the app takes to reach it.
 *
 * Two halves, driven through two different roots, the way `add-tile.test.tsx`
 * splits them. The screen's own behaviour runs against a stubbed `fetch` with
 * the screen rendered directly, because it calls `apiRequest` itself rather
 * than going through `SessionProvider`; whether the app *reaches* the screen at
 * all runs through `App`, because the role condition and the section state live
 * in the gate.
 *
 * Five assertions here are the ones nothing else in the suite can make: that
 * the lookup is a plain `GET` with the Code as a query parameter, that the save
 * is a `FormData` carrying exactly the named parts with one `remove_image_ids`
 * part per marked image, that a destructive save is confirmed in a sheet naming
 * the tile and the consequence *before* the request, that the indicator cycles
 * `Saving…` → `Saved.`, and that a Staff user is offered no door.
 */
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import App from '../App';
import {
  ADMINISTRATOR_REQUIRED,
  CODE_ALREADY_EXISTS,
  IMAGE_NOT_FOUND,
  INVALID_CODE,
  LAST_REFERENCE_IMAGE,
  MATCHING_UNAVAILABLE,
  REQUEST_TIMEOUT_MS,
  TILE_NOT_FOUND,
  UPLOAD_TIMEOUT_MS,
} from '../api/client';
import { EditTileScreen } from '../screens/EditTileScreen';
import type { Tile } from '@rocell/schema/tile';
import type { User } from '@rocell/schema/user';

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
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

const CODE = 'RP.CMA.0001DJ.SM.0T';
const RENAMED = 'RP.CMA.0002DJ.SM.0T';
const TILE_ID = 'b41d8e06-5a72-4f39-9c88-0d3e1f7a2b65';
const FIRST_IMAGE = '2c9a0f13-6b48-4d27-9e5a-1b3c7d8e0f45';
const SECOND_IMAGE = '7d1e4b90-3c26-4a85-91f7-5e0b2d6c8a13';

const LOOKUP = `/api/admin/tiles/lookup?code=${encodeURIComponent(CODE)}`;
const SAVE = `/api/admin/tiles/${TILE_ID}`;
/** The same path as the save; the queue is keyed by method, so the two differ. */
const REMOVE = SAVE;

/** What the API answers on the lookup and on a successful save. */
const FOUND: Tile = {
  id: TILE_ID,
  code: CODE,
  size: '45X90',
  category: 'CREMA MARMOL',
  face_number: null,
  reference_images: [
    {
      id: FIRST_IMAGE,
      width: 2048,
      height: 1365,
      featureless: false,
      created_at: '2026-09-21T09:30:00Z',
    },
    {
      id: SECOND_IMAGE,
      width: 2048,
      height: 1365,
      featureless: false,
      created_at: '2026-09-21T09:31:00Z',
    },
  ],
  created_at: '2026-09-21T09:30:00Z',
  updated_at: '2026-09-21T09:30:00Z',
};

const FLAGGED: Tile = {
  ...FOUND,
  reference_images: [{ ...FOUND.reference_images[0]!, featureless: true }],
};

const SAVED_TILE: Tile = { ...FOUND, code: RENAMED, updated_at: '2026-09-21T10:00:00Z' };

/**
 * The API's own sentences, character for character.
 *
 * Restated rather than imported because nothing crosses that boundary at build
 * time — `error-code-parity.test.ts` pins the *codes* and not the sentences.
 */
const NO_SUCH_TILE = 'No tile matches that. It may have been renamed or removed.';
const LAST_IMAGE =
  'A tile must keep at least one reference image. ' +
  'Add the replacement in the same save, or remove the tile instead.';
const CODE_IN_USE =
  'A tile with that code already exists. Edit that tile, or use a different code.';
const NO_SUCH_IMAGE = 'No reference image has that id.';

interface Reply {
  status: number;
  body?: unknown;
}

/**
 * Replace `fetch` with a queue keyed by **method and path**, and record every call.
 *
 * A local copy rather than a shared helper, as the other suites keep theirs — a
 * stub shared across files is a fixture two tests can change under each other.
 */
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

/** Stands in for the resolver until the promise below hands over the real one. */
const NOT_YET = (): void => undefined;

function renderScreen(onBack: () => void = (): void => undefined): void {
  render(<EditTileScreen onBack={onBack} />);
}

/** The screen as a Catalogue row opens it: a `Tile` handed over, nothing to type. */
function withTile(tile: Tile = FOUND, onRemoved?: () => void): void {
  render(
    <EditTileScreen
      onBack={(): void => undefined}
      onRemoved={onRemoved ?? ((): void => undefined)}
      tile={tile}
    />,
  );
}

function aFile(name = 'reference.jpg', type = 'image/jpeg'): File {
  return new File([new Uint8Array([1, 2, 3, 4])], name, { type });
}

function lookUp(code = CODE): void {
  fireEvent.change(screen.getByLabelText(/find a tile by code/i), { target: { value: code } });
  fireEvent.click(screen.getByRole('button', { name: /^find$/i }));
}

function save(): void {
  fireEvent.click(screen.getByRole('button', { name: /^save$/i }));
}

/**
 * The Remove tile control on the screen, never the one inside the sheet.
 *
 * Both carry the same word, deliberately: the sheet's confirm repeats the verb
 * that opened it rather than saying "Yes". `getAllByRole` would find two once
 * the dialog is open, so the trigger is taken from outside it by name and the
 * confirm is always reached `within(dialog)`.
 */
function removeControl(): HTMLElement {
  return screen
    .getAllByRole('button', { name: /^remove tile$/i })
    .find((control) => control.closest('[role="dialog"]') === null)!;
}

function confirmRemoval(): void {
  fireEvent.click(
    within(screen.getByRole('dialog')).getByRole('button', { name: /^remove tile$/i }),
  );
}

/** Everything a control's `aria-describedby` actually points at, as one string. */
function describedBy(label: RegExp): string {
  const ids = screen.getByLabelText(label).getAttribute('aria-describedby') ?? '';
  return ids
    .split(/\s+/)
    .map((id) => document.getElementById(id)?.textContent ?? '')
    .join(' ');
}

/** Find the tile, then wait for the edit form to appear. */
async function open(): Promise<void> {
  renderScreen();
  lookUp();
  await screen.findByLabelText(/^code$/i);
}

/** Every role a control on this screen could take. */
const CONTROL_ROLES = [
  'button',
  'link',
  'textbox',
  'searchbox',
  'combobox',
  'listbox',
  'checkbox',
  'radio',
  'switch',
  'slider',
  'spinbutton',
] as const;

describe('finding the tile to edit', () => {
  it('asks the lookup route for an exact code', async () => {
    const { calls } = stubFetch({ [`GET ${LOOKUP}`]: [{ status: 200, body: FOUND }] });
    await open();

    const [path, init] = calls[0] ?? ['', {}];

    expect(path).toBe(LOOKUP);
    // A `GET` with the Code as a query parameter — no body, and no substring
    // search: matching part of a code is Story 2.5's catalogue list.
    expect(init.method ?? 'GET').toBe('GET');
    expect(init.body).toBeUndefined();
    expect(calls).toHaveLength(1);
  });

  it('escapes a code that carries a space rather than sending it raw', async () => {
    // `Copy of 6LD.MA Quarry Stone Natural.jpg` is a real catalogue file, so a
    // Code with a space in it is an ordinary Code — and the one character a
    // template literal would put on the wire unescaped, which is why the screen
    // builds the query with `URLSearchParams`. The route matches exactly, so a
    // Code that arrives mangled finds nothing and reads as "no such tile".
    const spaced = '6LD.MA Quarry Stone Natural';
    const path = `/api/admin/tiles/lookup?code=${encodeURIComponent(spaced).replace(/%20/g, '+')}`;
    const { calls } = stubFetch({ [`GET ${path}`]: [{ status: 200, body: FOUND }] });
    renderScreen();
    lookUp(spaced);
    await screen.findByLabelText(/^code$/i);

    expect(calls[0]?.[0]).toBe(path);
    expect(calls[0]?.[0]).not.toContain(' ');
  });

  it('prefills the form from the tile it found', async () => {
    stubFetch({ [`GET ${LOOKUP}`]: [{ status: 200, body: FOUND }] });
    await open();

    expect(screen.getByLabelText(/^code$/i)).toHaveProperty('value', CODE);
    expect(screen.getByLabelText(/^size$/i)).toHaveProperty('value', '45X90');
    expect(screen.getByLabelText(/^category$/i)).toHaveProperty('value', 'CREMA MARMOL');
    expect(screen.getAllByRole('checkbox', { name: /remove/i })).toHaveLength(2);
  });

  it('shows each reference image proxied through the authenticated endpoint', async () => {
    // AD-9: `apps/web` never holds a storage URL, presigned or otherwise. The
    // bytes come from a route on this origin that re-checks the role, so the
    // session cookie travels with the image request.
    stubFetch({ [`GET ${LOOKUP}`]: [{ status: 200, body: FOUND }] });
    await open();

    const sources = screen.getAllByRole('img').map((image) => image.getAttribute('src') ?? '');

    expect(sources).toEqual([
      `/api/admin/tiles/${TILE_ID}/images/${FIRST_IMAGE}`,
      `/api/admin/tiles/${TILE_ID}/images/${SECOND_IMAGE}`,
    ]);
    for (const source of sources) {
      expect(source.startsWith('/api/')).toBe(true);
      expect(source).not.toMatch(/^https?:/);
    }
  });

  it('renders no form at all until a tile has been found', () => {
    stubFetch({});
    renderScreen();

    // An edit form with nothing to edit is a set of empty boxes that look like
    // they would create a tile.
    expect(screen.queryByLabelText(/^size$/i)).toBeNull();
    expect(screen.queryByRole('button', { name: /^save$/i })).toBeNull();
  });

  it('renders the API’s own sentence for a code nothing holds', async () => {
    stubFetch({
      'GET /api/admin/tiles/lookup?code=RP.CMA': [
        refusal(TILE_NOT_FOUND, NO_SUCH_TILE, 404),
      ],
    });
    renderScreen();

    lookUp('RP.CMA');

    expect(await screen.findByRole('alert')).toHaveProperty('textContent', NO_SUCH_TILE);
    expect(screen.getByLabelText(/find a tile by code/i).getAttribute('aria-invalid')).toBe(
      'true',
    );
    expect(screen.queryByRole('button', { name: /^save$/i })).toBeNull();
  });

  it.each([
    [
      'a refusal that belongs to no field',
      refusal(ADMINISTRATOR_REQUIRED, 'Only an administrator can do that.', 403),
      'Only an administrator can do that.',
    ],
    [
      'a body that is not a tile',
      { status: 200, body: { nonsense: true } },
      'The server returned an unexpected response.',
    ],
  ])('surfaces %s rather than looking like it did nothing', async (_label, reply, message) => {
    // Without a null-field slot on the lookup form, the only one on the screen
    // is inside the edit form — which is not rendered while no tile is loaded.
    // Find would then answer a network error, a timeout, a `403` or a malformed
    // body with a completely silent screen.
    stubFetch({ [`GET ${LOOKUP}`]: [reply] });
    renderScreen();

    lookUp();

    expect(await screen.findByRole('alert')).toHaveProperty('textContent', message);
    expect(screen.getAllByRole('alert')).toHaveLength(1);
    // And no field is marked: nothing the Administrator typed is at fault.
    expect(screen.getByLabelText(/find a tile by code/i).getAttribute('aria-invalid')).toBe(
      'false',
    );
  });

  it('surfaces a failure that never reached the API', async () => {
    // `LOOKUP_FAILED` is the only sentence on this screen that is not the
    // API's, and it can only appear when nothing came back to carry one.
    vi.stubGlobal('fetch', () => Promise.reject(new TypeError('offline')));
    renderScreen();

    lookUp();

    // `apiRequest` turns a dead connection into its own `ApiRequestError`, so
    // what is rendered is still a sentence and not silence.
    expect((await screen.findByRole('alert')).textContent).toMatch(/could not reach the server/i);
  });

  it('refuses a blank code before asking the server', async () => {
    const { calls } = stubFetch({});
    renderScreen();

    fireEvent.click(screen.getByRole('button', { name: /^find$/i }));

    expect(await screen.findByRole('alert')).toHaveProperty(
      'textContent',
      'Enter the tile’s code.',
    );
    expect(calls).toHaveLength(0);
  });

  it('says it is finding while the lookup is in flight', async () => {
    // The slower of the screen's two stages: the button goes disabled but says
    // nothing, so without this region a press on a slow connection looks
    // ignored. Held open deliberately — a settled request cannot show it.
    let release = NOT_YET;
    vi.stubGlobal(
      'fetch',
      () =>
        new Promise<Response>((resolve) => {
          release = (): void =>
            resolve({ ok: true, status: 200, json: () => Promise.resolve(FOUND) } as Response);
        }),
    );

    renderScreen();
    lookUp();

    await waitFor(() => {
      expect(screen.getByText('Finding…')).toBeTruthy();
    });

    release();

    await screen.findByLabelText(/^code$/i);
    expect(screen.queryByText('Finding…')).toBeNull();
  });

  it('clears a loaded tile when a later lookup misses', async () => {
    stubFetch({
      [`GET ${LOOKUP}`]: [{ status: 200, body: FOUND }],
      'GET /api/admin/tiles/lookup?code=GONE': [refusal(TILE_NOT_FOUND, NO_SUCH_TILE, 404)],
    });
    await open();

    lookUp('GONE');

    await screen.findByRole('alert');
    // A form left behind for a tile that is no longer on screen is a form whose
    // Save would write to whichever tile happened to be loaded before.
    expect(screen.queryByLabelText(/^size$/i)).toBeNull();
  });

  it('does not start a lookup underneath an in-flight save', async () => {
    // The mirror of the race the Save handler guards against. The Find *button*
    // is disabled while a save is in flight, but the lookup field is not — and
    // pressing Enter in a text field submits its form directly without ever
    // consulting the button. A lookup that started here would `adopt()` its
    // answer over the code, size, category, marks and files the Administrator
    // is still waiting on the save to write.
    const calls: string[] = [];
    vi.stubGlobal('fetch', (input: string, init: RequestInit = {}) => {
      calls.push(`${init.method ?? 'GET'} ${input}`);
      if ((init.method ?? 'GET') === 'GET') {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: () => Promise.resolve(FOUND),
        } as Response);
      }
      // Never answered: the guard only exists while the save is unanswered.
      return new Promise<Response>(() => undefined);
    });

    await open();
    save();
    await waitFor(() => {
      expect(screen.getByText('Saving…')).toBeTruthy();
    });

    const field = screen.getByLabelText(/find a tile by code/i);
    fireEvent.change(field, { target: { value: 'GONE' } });
    fireEvent.submit(field.closest('form') as HTMLFormElement);

    await waitFor(() => {
      expect(screen.getByText('Saving…')).toBeTruthy();
    });
    expect(calls).toEqual([`GET ${LOOKUP}`, `PATCH ${SAVE}`]);
    // And the form the save is about is still the one on screen.
    expect(screen.getByLabelText(/^code$/i)).toHaveProperty('value', CODE);
  });
});

describe('saving the edit', () => {
  it('sends a multipart body with exactly the parts the endpoint names', async () => {
    const { calls } = stubFetch({
      [`GET ${LOOKUP}`]: [{ status: 200, body: FOUND }],
      [`PATCH ${SAVE}`]: [{ status: 200, body: SAVED_TILE }],
    });
    await open();

    fireEvent.change(screen.getByLabelText(/^code$/i), { target: { value: RENAMED } });
    save();

    await waitFor(() => {
      expect(screen.getByText('Saved.')).toBeTruthy();
    });

    const [path, init] = calls[1] ?? ['', {}];
    expect(path).toBe(SAVE);
    expect(init.method).toBe('PATCH');
    // A `FormData`, not JSON. `JSON.stringify(formData)` is `'{}'` — not an
    // error, just an empty object — so a body of files would arrive as nothing
    // at all with every type check in the app satisfied.
    expect(init.body).toBeInstanceOf(FormData);

    const body = init.body as FormData;
    expect(new Set(body.keys())).toEqual(new Set(['code', 'size', 'category']));
    expect(body.get('code')).toBe(RENAMED);
    // Sent although they were not touched: an absent part means "unchanged" on
    // this endpoint, and the form is prefilled, so sending all three is one
    // branch fewer in the screen and the API records a change set of `{}`.
    expect(body.get('size')).toBe('45X90');
    expect(body.get('category')).toBe('CREMA MARMOL');
  });

  it('sends one remove_image_ids part per marked image', async () => {
    const { calls } = stubFetch({
      [`GET ${LOOKUP}`]: [{ status: 200, body: FOUND }],
      [`PATCH ${SAVE}`]: [
        { status: 200, body: { ...FOUND, reference_images: [FOUND.reference_images[0]] } },
      ],
    });
    await open();

    fireEvent.click(screen.getAllByRole('checkbox', { name: /remove/i })[1]!);
    save();

    fireEvent.click(await screen.findByRole('button', { name: /remove and save/i }));

    await waitFor(() => {
      expect(calls).toHaveLength(2);
    });
    const body = (calls[1]?.[1].body ?? new FormData()) as FormData;

    expect(body.getAll('remove_image_ids')).toEqual([SECOND_IMAGE]);
  });

  it('sends one images part per new file', async () => {
    const { calls } = stubFetch({
      [`GET ${LOOKUP}`]: [{ status: 200, body: FOUND }],
      [`PATCH ${SAVE}`]: [{ status: 200, body: FOUND }],
    });
    await open();

    fireEvent.change(screen.getByLabelText(/add reference images/i), {
      // A `.tif` among them, because the real catalogue holds them and the
      // screen must not pre-judge a file the server decides on by content.
      target: { files: [aFile('a.jpg'), aFile('b.tif', 'image/tiff')] },
    });
    save();

    await waitFor(() => {
      expect(calls).toHaveLength(2);
    });
    const body = (calls[1]?.[1].body ?? new FormData()) as FormData;

    expect(body.getAll('images')).toHaveLength(2);
  });

  it('lets the browser write the content type, so the boundary is right', async () => {
    const { calls } = stubFetch({
      [`GET ${LOOKUP}`]: [{ status: 200, body: FOUND }],
      [`PATCH ${SAVE}`]: [{ status: 200, body: FOUND }],
    });
    await open();

    save();

    await waitFor(() => {
      expect(calls).toHaveLength(2);
    });

    // Setting it by hand omits the boundary token that delimits the parts, and
    // the server then cannot parse a body that looks perfectly well formed.
    expect(calls[1]?.[1].headers).toBeUndefined();
  });

  it('is not given the default request timeout', async () => {
    // 15 seconds is wrong for a save that uploads by an order of magnitude: one
    // image is 16 forward passes (AD-13). The default aborts while the server
    // is still working, the server commits anyway, and the Administrator is
    // shown a network error for an edit that has already landed.
    const scheduled: unknown[] = [];
    const real = globalThis.setTimeout;
    vi.stubGlobal('setTimeout', ((handler: TimerHandler, ms?: number, ...rest: unknown[]) => {
      scheduled.push(ms);
      return real(handler, ms, ...rest);
    }) as typeof globalThis.setTimeout);

    stubFetch({
      [`GET ${LOOKUP}`]: [{ status: 200, body: FOUND }],
      [`PATCH ${SAVE}`]: [{ status: 200, body: FOUND }],
    });
    await open();
    save();

    await waitFor(() => {
      expect(scheduled).toContain(UPLOAD_TIMEOUT_MS);
    });
    // The lookup is a cheap read and takes the ordinary bound; the save does
    // not. Both numbers appear, and the assertion is that the long one does.
    expect(scheduled).toContain(REQUEST_TIMEOUT_MS);
  });

  it('cycles the indicator from Saving to Saved beside the action', async () => {
    let release = NOT_YET;
    const answers: ((value: Response) => void)[] = [];
    vi.stubGlobal('fetch', (_input: string, init: RequestInit = {}) => {
      if ((init.method ?? 'GET') === 'GET') {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: () => Promise.resolve(FOUND),
        } as Response);
      }
      // Held open deliberately: the in-flight state is the half of the contract
      // a settled request cannot show.
      return new Promise<Response>((resolve) => {
        answers.push(resolve);
        release = (): void =>
          resolve({ ok: true, status: 200, json: () => Promise.resolve(SAVED_TILE) } as Response);
      });
    });

    await open();
    save();

    await waitFor(() => {
      expect(screen.getByText('Saving…')).toBeTruthy();
    });
    expect(screen.getByRole('button', { name: /^save$/i })).toHaveProperty('disabled', true);

    release();

    await waitFor(() => {
      expect(screen.getByText('Saved.')).toBeTruthy();
    });
  });

  it('adopts the saved tile, so the form shows what actually landed', async () => {
    stubFetch({
      [`GET ${LOOKUP}`]: [{ status: 200, body: FOUND }],
      [`PATCH ${SAVE}`]: [{ status: 200, body: SAVED_TILE }],
    });
    await open();

    fireEvent.change(screen.getByLabelText(/^code$/i), { target: { value: RENAMED } });
    save();

    await waitFor(() => {
      expect(screen.getByText('Saved.')).toBeTruthy();
    });
    // From the response, not from what was typed: the API normalizes the Size
    // and resolves the Category, so the form has to show the resolved values or
    // the next save would send back an unnormalized copy of them.
    expect(screen.getByLabelText(/^code$/i)).toHaveProperty('value', RENAMED);
  });

  it('re-sends neither a removed id nor an uploaded file on a second save', async () => {
    // `adopt()` clears the marks and the chosen files, and nothing else in the
    // suite saves twice. Drop that clearing and this is the only test that
    // fails — while in the app the second save re-sends an id the first one
    // already removed (a `404`) and re-uploads files that are already stored
    // (duplicate rows, plus sixteen more vectors each).
    const survivor: Tile = { ...FOUND, reference_images: [FOUND.reference_images[0]!] };
    const { calls } = stubFetch({
      [`GET ${LOOKUP}`]: [{ status: 200, body: FOUND }],
      [`PATCH ${SAVE}`]: [
        { status: 200, body: survivor },
        { status: 200, body: survivor },
      ],
    });
    await open();

    fireEvent.click(screen.getAllByRole('checkbox', { name: /remove/i })[1]!);
    fireEvent.change(screen.getByLabelText(/add reference images/i), {
      target: { files: [aFile()] },
    });
    save();
    fireEvent.click(await screen.findByRole('button', { name: /remove and save/i }));

    await waitFor(() => {
      expect(screen.getByText('Saved.')).toBeTruthy();
    });

    // The second save moves one field and nothing else.
    fireEvent.change(screen.getByLabelText(/^size$/i), { target: { value: '60X60' } });
    save();

    await waitFor(() => {
      expect(calls).toHaveLength(3);
    });
    const second = (calls[2]?.[1].body ?? new FormData()) as FormData;

    expect(second.getAll('remove_image_ids')).toEqual([]);
    expect(second.getAll('images')).toEqual([]);
    expect(second.get('size')).toBe('60X60');
    // And no confirmation, because this save removes nothing.
    expect(screen.queryByRole('dialog')).toBeNull();
    // The surviving image is the only box, and it is unticked.
    const boxes = screen.getAllByRole('checkbox', { name: /remove/i });
    expect(boxes).toHaveLength(1);
    expect(boxes[0]).toHaveProperty('checked', false);
  });

  it('surfaces the quality flag on this screen rather than in a report', async () => {
    // FR-19: an image below the texture threshold matches any washed-out photo
    // and can never be reliably retrieved itself. The epic asks for the flag on
    // the tile's own screen, not somewhere the Administrator has to go looking.
    stubFetch({ [`GET ${LOOKUP}`]: [{ status: 200, body: FLAGGED }] });
    await open();

    expect(screen.getByText(/very little visible texture/i)).toBeTruthy();
  });

  it('names the category sentinel rather than leaving the field empty', async () => {
    stubFetch({
      [`GET ${LOOKUP}`]: [{ status: 200, body: { ...FOUND, category: null } }],
    });
    await open();

    // `category` is nullable on the wire. An empty field is the right rendering
    // — clearing it is a supported answer (AD-18) — and the hint beside it is
    // what says where a blank one is filed.
    expect(screen.getByLabelText(/^category$/i)).toHaveProperty('value', '');
    expect(screen.getByText(/filed under/i).textContent).toContain('UNKNOWN');
  });

  it('does not refile a tile that has no category at all', async () => {
    // The endpoint reads an absent `category` part as "unchanged" and a blank
    // one as the UNKNOWN sentinel, and keeps a null Category deliberately —
    // `test_a_tile_with_no_category_keeps_none_when_the_part_is_absent` on the
    // API side. Sending the empty field unconditionally would refile every
    // such tile under UNKNOWN on a save that only fixed a Code, and write a
    // `category: null -> UNKNOWN` line into the audit log for it.
    const { calls } = stubFetch({
      [`GET ${LOOKUP}`]: [{ status: 200, body: { ...FOUND, category: null } }],
      [`PATCH ${SAVE}`]: [{ status: 200, body: { ...SAVED_TILE, category: null } }],
    });
    await open();

    fireEvent.change(screen.getByLabelText(/^code$/i), { target: { value: RENAMED } });
    save();

    await waitFor(() => {
      expect(calls.some(([, init]) => init.method === 'PATCH')).toBe(true);
    });
    const body = calls.find(([, init]) => init.method === 'PATCH')![1].body as FormData;
    expect(body.has('category')).toBe(false);
    // The parts that did change still travel, so this is a guard and not a drop.
    expect(body.get('code')).toBe(RENAMED);
    expect(body.get('size')).toBe(FOUND.size);
  });

  it('still clears a category the administrator emptied', async () => {
    // The other side of the same guard: a Category the tile *has* and the
    // Administrator cleared is a blank part, which is how AD-18 files it under
    // the sentinel rather than dropping it.
    const { calls } = stubFetch({
      [`GET ${LOOKUP}`]: [{ status: 200, body: FOUND }],
      [`PATCH ${SAVE}`]: [{ status: 200, body: SAVED_TILE }],
    });
    await open();

    fireEvent.change(screen.getByLabelText(/^category$/i), { target: { value: '' } });
    save();

    await waitFor(() => {
      expect(calls.some(([, init]) => init.method === 'PATCH')).toBe(true);
    });
    const body = calls.find(([, init]) => init.method === 'PATCH')![1].body as FormData;
    expect(body.get('category')).toBe('');
  });

  it('shows no similarity value anywhere', async () => {
    stubFetch({ [`GET ${LOOKUP}`]: [{ status: 200, body: FOUND }] });
    const { container } = render(<EditTileScreen onBack={(): void => undefined} />);
    lookUp();
    await screen.findByLabelText(/^code$/i);

    // AD-20: no percentage, no bar, no star rating, no word derived from a
    // score. Asserted over the rendered text rather than over the source.
    expect(container.textContent).not.toMatch(/\d+\s*%/);
    expect(container.textContent?.toLowerCase()).not.toMatch(
      /similarity|confidence|match score/,
    );
  });
});

describe('confirming a destructive save', () => {
  it('names the tile and the consequence before anything is sent', async () => {
    const { calls } = stubFetch({
      [`GET ${LOOKUP}`]: [{ status: 200, body: FOUND }],
      [`PATCH ${SAVE}`]: [{ status: 200, body: FOUND }],
    });
    await open();

    fireEvent.click(screen.getAllByRole('checkbox', { name: /remove/i })[0]!);
    save();

    const dialog = await screen.findByRole('dialog');

    // Never a bare "Are you sure?" (EXPERIENCE.md:56, :72, :144).
    expect(within(dialog).getByRole('heading').textContent).toContain(CODE);
    expect(dialog.textContent).toMatch(/permanently/i);
    expect(dialog.textContent).toMatch(/keeps 1 reference image\./i);
    // And nothing has been sent: the lookup, and no save.
    expect(calls).toHaveLength(1);
  });

  it('sends nothing when the confirmation is cancelled', async () => {
    const { calls } = stubFetch({
      [`GET ${LOOKUP}`]: [{ status: 200, body: FOUND }],
      [`PATCH ${SAVE}`]: [{ status: 200, body: FOUND }],
    });
    await open();

    fireEvent.click(screen.getAllByRole('checkbox', { name: /remove/i })[0]!);
    save();
    fireEvent.click(await screen.findByRole('button', { name: /^cancel$/i }));

    expect(screen.queryByRole('dialog')).toBeNull();
    expect(calls).toHaveLength(1);
    // The mark survives the cancel: cancelling the save is not unmarking the
    // image, and clearing it would make the Administrator do the work twice.
    expect(screen.getAllByRole('checkbox', { name: /remove/i })[0]).toHaveProperty(
      'checked',
      true,
    );
  });

  it('refuses instead of confirming a save that would empty the tile', async () => {
    // EXPERIENCE.md:148: an operation that was never going to be honoured is
    // refused *instead of* being confirmed. Confirming first would ask the
    // Administrator to authorise something the product had already decided
    // against — and the sheet would have promised "keeps 0 reference images"
    // on the way through.
    const { calls } = stubFetch({
      [`GET ${LOOKUP}`]: [{ status: 200, body: FOUND }],
      [`PATCH ${SAVE}`]: [refusal(LAST_REFERENCE_IMAGE, LAST_IMAGE, 409)],
    });
    await open();

    for (const box of screen.getAllByRole('checkbox', { name: /remove/i })) {
      fireEvent.click(box);
    }
    save();

    const dialog = await screen.findByRole('dialog');

    // No destructive control at all — there is nothing to press.
    expect(within(dialog).queryByRole('button', { name: /remove and save/i })).toBeNull();
    expect(within(dialog).getByRole('button', { name: /^close$/i })).toBeTruthy();
    // The screen's own sentence, which `error-code-parity.test.ts` pins to the
    // server's.
    expect(dialog.textContent).toContain(LAST_IMAGE);
    expect(dialog.textContent).not.toMatch(/keeps 0 reference/i);
    // And nothing was sent: only the lookup.
    expect(calls).toHaveLength(1);
  });

  it('confirms rather than refuses when a replacement travels with the removal', async () => {
    // The floor is about the *net*, so removing the only image and uploading
    // its replacement in one save is the supported path — and it is still
    // destructive, so it is still confirmed.
    stubFetch({
      [`GET ${LOOKUP}`]: [{ status: 200, body: FOUND }],
      [`PATCH ${SAVE}`]: [{ status: 200, body: FOUND }],
    });
    await open();

    for (const box of screen.getAllByRole('checkbox', { name: /remove/i })) {
      fireEvent.click(box);
    }
    fireEvent.change(screen.getByLabelText(/add reference images/i), {
      target: { files: [aFile()] },
    });
    save();

    const dialog = await screen.findByRole('dialog');

    expect(within(dialog).getByRole('button', { name: /remove and save/i })).toBeTruthy();
    expect(dialog.textContent).toMatch(/keeps 1 reference image\./i);
  });

  it('does not confirm a save that removes nothing', async () => {
    stubFetch({
      [`GET ${LOOKUP}`]: [{ status: 200, body: FOUND }],
      [`PATCH ${SAVE}`]: [{ status: 200, body: SAVED_TILE }],
    });
    await open();

    fireEvent.change(screen.getByLabelText(/^code$/i), { target: { value: RENAMED } });
    save();

    await waitFor(() => {
      expect(screen.getByText('Saved.')).toBeTruthy();
    });
    expect(screen.queryByRole('dialog')).toBeNull();
  });
});

describe('the refusals', () => {
  it('renders the last-image refusal in the server’s own words', async () => {
    // The screen states no rule it does not own: the floor is the server's and
    // the sentence that names the way through it is the server's too.
    stubFetch({
      [`GET ${LOOKUP}`]: [{ status: 200, body: FOUND }],
      [`PATCH ${SAVE}`]: [refusal(LAST_REFERENCE_IMAGE, LAST_IMAGE, 409)],
    });
    await open();

    fireEvent.click(screen.getAllByRole('checkbox', { name: /remove/i })[0]!);
    save();
    fireEvent.click(await screen.findByRole('button', { name: /remove and save/i }));

    expect(await screen.findByRole('alert')).toHaveProperty('textContent', LAST_IMAGE);
    // The dialog is gone, so the refusal is readable on the form it belongs to.
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(screen.getByLabelText(/add reference images/i).getAttribute('aria-invalid')).toBe(
      'true',
    );
  });

  it('marks the code field for a duplicate and renders the API’s own sentence', async () => {
    stubFetch({
      [`GET ${LOOKUP}`]: [{ status: 200, body: FOUND }],
      [`PATCH ${SAVE}`]: [refusal(CODE_ALREADY_EXISTS, CODE_IN_USE, 409)],
    });
    await open();

    fireEvent.change(screen.getByLabelText(/^code$/i), { target: { value: RENAMED } });
    save();

    expect(await screen.findByRole('alert')).toHaveProperty('textContent', CODE_IN_USE);
    expect(screen.getByLabelText(/^code$/i).getAttribute('aria-invalid')).toBe('true');
    // Nothing typed is cleared: a duplicate Code is one field to change.
    expect(screen.getByLabelText(/^size$/i)).toHaveProperty('value', '45X90');
  });

  it('marks no field when the server has no image pipeline installed', async () => {
    // Nothing the Administrator typed or chose is at fault and the fix is an
    // operator's, so pointing at an input would send them to correct something
    // that is perfectly fine.
    const message = 'The embedding model is not installed. Run `make model` to download it.';
    stubFetch({
      [`GET ${LOOKUP}`]: [{ status: 200, body: FOUND }],
      [`PATCH ${SAVE}`]: [refusal(MATCHING_UNAVAILABLE, message, 503)],
    });
    await open();

    save();

    expect(await screen.findByRole('alert')).toHaveProperty('textContent', message);
    for (const label of [/^code$/i, /^size$/i, /add reference images/i]) {
      expect(screen.getByLabelText(label).getAttribute('aria-invalid')).toBe('false');
    }
  });

  it.each([
    ['a blank code', /^code$/i, 'Enter the tile’s code.'],
    ['a blank size', /^size$/i, 'Enter the tile’s size.'],
  ])('refuses %s before asking the server, and focuses the field', async (
    _label,
    field,
    message,
  ) => {
    const { calls } = stubFetch({ [`GET ${LOOKUP}`]: [{ status: 200, body: FOUND }] });
    await open();

    fireEvent.change(screen.getByLabelText(field), { target: { value: '' } });
    save();

    expect(await screen.findByRole('alert')).toHaveProperty('textContent', message);
    expect(document.activeElement).toBe(screen.getByLabelText(field));
    // Nothing was sent: a blank field must not cost a round trip to be told a
    // box is empty. Only the lookup was made.
    expect(calls).toHaveLength(1);
  });

  it('refuses more files than the endpoint accepts without uploading them', async () => {
    const { calls } = stubFetch({ [`GET ${LOOKUP}`]: [{ status: 200, body: FOUND }] });
    await open();

    fireEvent.change(screen.getByLabelText(/add reference images/i), {
      target: { files: Array.from({ length: 9 }, (_unused, index) => aFile(`${index}.jpg`)) },
    });
    save();

    expect((await screen.findByRole('alert')).textContent).toMatch(/at most 8/i);
    expect(calls).toHaveLength(1);
  });

  it('refuses a file over the byte ceiling without uploading it', async () => {
    const { calls } = stubFetch({ [`GET ${LOOKUP}`]: [{ status: 200, body: FOUND }] });
    await open();

    const huge = new File(['x'], 'huge.jpg', { type: 'image/jpeg' });
    // `File.size` is derived from the parts, so a 128 MB fixture would mean
    // allocating 128 MB in a unit test. Overridden instead: what is under test
    // is the comparison, not the browser's arithmetic.
    Object.defineProperty(huge, 'size', { value: 200 * 1024 * 1024 });
    fireEvent.change(screen.getByLabelText(/add reference images/i), {
      target: { files: [huge] },
    });
    save();

    expect((await screen.findByRole('alert')).textContent).toMatch(/under 128 MB/i);
    expect(calls).toHaveLength(1);
  });

  it.each([
    // One per slot the screen has, because the claim is about the *slots*: the
    // screen holds one error at a time, and the risk is that two of the five
    // places it can be painted render it at once. A single fault could never
    // show that.
    ['the code field', refusal(CODE_ALREADY_EXISTS, CODE_IN_USE, 409), /^code$/i],
    ['the code field, again', refusal(INVALID_CODE, 'A Code must not be blank.', 422), /^code$/i],
    [
      'the images control',
      refusal(LAST_REFERENCE_IMAGE, LAST_IMAGE, 409),
      /add reference images/i,
    ],
    [
      'no field at all',
      refusal(MATCHING_UNAVAILABLE, 'The embedding model is not installed.', 503),
      null,
    ],
  ])('renders the one alert in exactly one slot when %s is at fault', async (
    _label,
    reply,
    marked,
  ) => {
    stubFetch({
      [`GET ${LOOKUP}`]: [{ status: 200, body: FOUND }],
      [`PATCH ${SAVE}`]: [reply],
    });
    await open();

    save();
    const alert = await screen.findByRole('alert');

    expect(screen.getAllByRole('alert')).toHaveLength(1);
    if (marked === null) {
      // A failure that belongs to no field is painted after all of them, and
      // marks none: pointing at an input would send the Administrator to
      // correct something that is perfectly fine.
      for (const label of [/^code$/i, /^size$/i, /add reference images/i]) {
        expect(screen.getByLabelText(label).getAttribute('aria-invalid')).toBe('false');
      }
    } else {
      // Bound to the control it is about, so a screen-reader user on that
      // input hears the sentence about it rather than about another.
      expect(screen.getByLabelText(marked).getAttribute('aria-invalid')).toBe('true');
      expect(screen.getByLabelText(marked).getAttribute('aria-describedby')).toContain(
        alert.getAttribute('id'),
      );
    }
  });

  it('clears the loaded tile when the save says the tile is gone', async () => {
    // The tile moved or went while the form was open. Everything on that form
    // would fail identically on every further Save, with no way forward but
    // Back — so the form goes with it and the lookup is the way back in.
    stubFetch({
      [`GET ${LOOKUP}`]: [{ status: 200, body: FOUND }],
      [`PATCH ${SAVE}`]: [refusal(TILE_NOT_FOUND, NO_SUCH_TILE, 404)],
    });
    await open();

    save();

    expect(await screen.findByRole('alert')).toHaveProperty('textContent', NO_SUCH_TILE);
    expect(screen.queryByLabelText(/^size$/i)).toBeNull();
    expect(screen.queryByRole('button', { name: /^save$/i })).toBeNull();
    // Exactly one alert survives the form being torn out from under it: the
    // lookup form's own null-field slot is what paints it now.
    expect(screen.getAllByRole('alert')).toHaveLength(1);
  });

  it('leaves focus on a control when the save tears the form out', async () => {
    // `tile_not_found` faults no field, so nothing is focused by the refusal —
    // and the control that had focus has just been unmounted with the form.
    // Focus would fall to `<body>`, outside the alert that explains why, which
    // is the one place a keyboard or screen-reader user cannot read it from.
    stubFetch({
      [`GET ${LOOKUP}`]: [{ status: 200, body: FOUND }],
      [`PATCH ${SAVE}`]: [refusal(TILE_NOT_FOUND, NO_SUCH_TILE, 404)],
    });
    await open();

    save();

    await screen.findByRole('alert');
    expect(document.activeElement).toBe(screen.getByLabelText(/find a tile by code/i));
    expect(document.activeElement).not.toBe(document.body);
  });

  it('drops a mark the server says it no longer holds', async () => {
    // The same dead end as `tile_not_found`, one level down: the marked id
    // names an image the endpoint has already lost, so every further Save
    // carries it again and is refused again. Nothing on screen says which mark
    // is the bad one, so the second Save has to be able to succeed.
    const { calls } = stubFetch({
      [`GET ${LOOKUP}`]: [{ status: 200, body: FOUND }],
      [`PATCH ${SAVE}`]: [
        refusal(IMAGE_NOT_FOUND, NO_SUCH_IMAGE, 404),
        { status: 200, body: SAVED_TILE },
      ],
    });
    await open();

    fireEvent.click(screen.getAllByRole('checkbox', { name: /remove/i })[0]!);
    save();
    fireEvent.click(screen.getByRole('button', { name: /remove and save/i }));

    expect(await screen.findByRole('alert')).toHaveProperty('textContent', NO_SUCH_IMAGE);
    // The tile stays — it is still there, and the rest of the form is still
    // the Administrator's work — but the dead mark does not.
    expect(screen.getByLabelText(/^size$/i)).toBeTruthy();
    expect(
      screen.getAllByRole('checkbox', { name: /remove/i }).map((box) => (box as HTMLInputElement).checked),
    ).toEqual([false, false]);

    // And the next Save carries no removal, so it is no longer the same
    // refusal every time.
    save();
    await waitFor(() => {
      expect(calls.filter(([, init]) => init.method === 'PATCH')).toHaveLength(2);
    });
    const body = calls.filter(([, init]) => init.method === 'PATCH')[1]![1].body as FormData;
    expect(body.getAll('remove_image_ids')).toEqual([]);
  });
});

describe('removing the tile', () => {
  it('offers no removal control until a tile has been found', () => {
    stubFetch({});
    renderScreen();

    // There is nothing to remove, and a destructive control on a screen with no
    // subject is a control that can only be pressed by mistake.
    expect(screen.queryByRole('button', { name: /^remove tile$/i })).toBeNull();
    expect(screen.queryByRole('heading', { name: /remove this tile/i })).toBeNull();
  });

  it('offers it once a tile is loaded, without the accent', async () => {
    stubFetch({ [`GET ${LOOKUP}`]: [{ status: 200, body: FOUND }] });
    await open();

    expect(removeControl()).toBeTruthy();
    // Save is still the screen's one primary action: the removal is a second
    // *action*, never a second primary. The fill is asserted in
    // `styling-wiring.test.ts`; what belongs here is that the two are distinct
    // controls with distinct words.
    expect(screen.getByRole('button', { name: /^save$/i })).toBeTruthy();
  });

  it('names the tile and the consequence before anything is requested', async () => {
    const { calls } = stubFetch({
      [`GET ${LOOKUP}`]: [{ status: 200, body: FOUND }],
      [`DELETE ${REMOVE}`]: [{ status: 204 }],
    });
    await open();

    fireEvent.click(removeControl());

    const dialog = await screen.findByRole('dialog');

    // Never a bare "Are you sure?" (EXPERIENCE.md:56, :72, :144).
    expect(within(dialog).getByRole('heading').textContent).toContain(CODE);
    expect(dialog.textContent).toContain(CODE);
    expect(dialog.textContent).toMatch(/permanently/i);
    expect(dialog.textContent).toMatch(/cannot be undone/i);
    // The confirm carries a word as well as the destructive fill — red is never
    // the only signal.
    expect(within(dialog).getByRole('button', { name: /^remove tile$/i })).toBeTruthy();
    // And nothing has been sent: the lookup, and no removal.
    expect(calls).toHaveLength(1);
  });

  it.each([
    [
      'Cancel',
      (): void => {
        fireEvent.click(
          within(screen.getByRole('dialog')).getByRole('button', { name: /^cancel$/i }),
        );
      },
    ],
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
        fireEvent.mouseDown(scrim as HTMLElement);
        fireEvent.click(scrim as HTMLElement);
      },
    ],
  ])('requests nothing when the sheet is dismissed by %s', async (_label, dismiss) => {
    // All three, because all three are ways out of a sheet that has not been
    // confirmed — and a removal is the one action on this screen with nothing
    // behind it to undo, so a dismissal that leaked a request would be
    // unrecoverable rather than merely surprising.
    const { calls } = stubFetch({
      [`GET ${LOOKUP}`]: [{ status: 200, body: FOUND }],
      [`DELETE ${REMOVE}`]: [{ status: 204 }],
    });
    await open();

    fireEvent.click(removeControl());
    await screen.findByRole('dialog');
    dismiss();

    expect(screen.queryByRole('dialog')).toBeNull();
    // Only the lookup. No removal was sent.
    expect(calls).toHaveLength(1);
    expect(calls.some(([, init]) => init.method === 'DELETE')).toBe(false);
    // The form is exactly as it was: dismissing the sheet is not an edit.
    expect(screen.getByLabelText(/^code$/i)).toHaveProperty('value', CODE);
    expect(screen.getByLabelText(/^size$/i)).toHaveProperty('value', '45X90');
    expect(screen.getByLabelText(/^category$/i)).toHaveProperty('value', 'CREMA MARMOL');
  });

  it('issues a DELETE with no body once it is confirmed', async () => {
    const { calls } = stubFetch({
      [`GET ${LOOKUP}`]: [{ status: 200, body: FOUND }],
      [`DELETE ${REMOVE}`]: [{ status: 204 }],
    });
    await open();

    fireEvent.click(removeControl());
    confirmRemoval();

    await waitFor(() => {
      expect(calls.filter(([, sent]) => sent.method === 'DELETE')).toHaveLength(1);
    });
    const [path, sent] = calls.find(([, each]) => each.method === 'DELETE')!;

    expect(path).toBe(REMOVE);
    // A `DELETE` names its subject in the path; a body would be a second way to
    // say which tile, and the two could disagree.
    expect(sent.body).toBeUndefined();
  });

  it('returns to the lookup stage, announces the removal and focuses the field', async () => {
    stubFetch({
      [`GET ${LOOKUP}`]: [{ status: 200, body: FOUND }],
      [`DELETE ${REMOVE}`]: [{ status: 204 }],
    });
    await open();

    fireEvent.click(removeControl());
    confirmRemoval();

    // The form goes with the tile: there is nothing left for it to be about.
    await waitFor(() => {
      expect(screen.queryByLabelText(/^size$/i)).toBeNull();
    });
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(screen.queryByRole('button', { name: /^remove tile$/i })).toBeNull();
    // Announced by name, in the live region beside the lookup — the only stage
    // still on screen. A `204` carries no body, so the Code has to have been
    // read before the request.
    expect(screen.getByRole('status').textContent).toBe(`${CODE} removed.`);
    // And focus lands on the one control that can still do anything.
    expect(document.activeElement).toBe(screen.getByLabelText(/find a tile by code/i));
  });

  it('clears the announcement as soon as another code is typed', async () => {
    stubFetch({
      [`GET ${LOOKUP}`]: [{ status: 200, body: FOUND }],
      [`DELETE ${REMOVE}`]: [{ status: 204 }],
    });
    await open();

    fireEvent.click(removeControl());
    confirmRemoval();
    await waitFor(() => {
      expect(screen.getByRole('status').textContent).toBe(`${CODE} removed.`);
    });

    fireEvent.change(screen.getByLabelText(/find a tile by code/i), {
      target: { value: 'SOMETHING-ELSE' },
    });

    // A sentence naming one tile, left standing beside a field holding another,
    // is a sentence about the wrong tile.
    expect(screen.getByRole('status').textContent).toBe('');
  });

  it('clears the announcement when Find is pressed without the field being retyped', async () => {
    // The field still holds the removed tile's Code, so nothing is typed and
    // the keystroke clear never fires. Without a clear in the lookup itself the
    // screen would render `Finding…` beside — and in the colour of — a sentence
    // announcing a removal that has already happened.
    stubFetch({
      [`GET ${LOOKUP}`]: [
        { status: 200, body: FOUND },
        refusal(TILE_NOT_FOUND, NO_SUCH_TILE, 404),
      ],
      [`DELETE ${REMOVE}`]: [{ status: 204 }],
    });
    await open();

    fireEvent.click(removeControl());
    confirmRemoval();
    await waitFor(() => {
      expect(screen.getByRole('status').textContent).toBe(`${CODE} removed.`);
    });

    fireEvent.click(screen.getByRole('button', { name: /^find$/i }));

    // The lookup is now the only thing that region is about.
    expect(screen.getByRole('status').textContent).not.toContain('removed.');
    expect(await screen.findByRole('alert')).toHaveProperty('textContent', NO_SUCH_TILE);
    expect(screen.getByRole('status').textContent).toBe('');
  });

  it('renders the server’s own sentence and closes the form when the tile is already gone', async () => {
    stubFetch({
      [`GET ${LOOKUP}`]: [{ status: 200, body: FOUND }],
      [`DELETE ${REMOVE}`]: [refusal(TILE_NOT_FOUND, NO_SUCH_TILE, 404)],
    });
    await open();

    fireEvent.click(removeControl());
    confirmRemoval();

    expect(await screen.findByRole('alert')).toHaveProperty('textContent', NO_SUCH_TILE);
    // The same dead end a failed save already models: everything on that form
    // would fail identically on every further press, so the form goes.
    expect(screen.queryByLabelText(/^size$/i)).toBeNull();
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(screen.getAllByRole('alert')).toHaveLength(1);
    expect(document.activeElement).toBe(screen.getByLabelText(/find a tile by code/i));
    // Nothing is announced: the tile was not removed by this Administrator.
    expect(screen.getByRole('status').textContent).toBe('');
  });

  it('leaves the form standing for a refusal that is not the tile being gone', async () => {
    stubFetch({
      [`GET ${LOOKUP}`]: [{ status: 200, body: FOUND }],
      [`DELETE ${REMOVE}`]: [
        refusal(ADMINISTRATOR_REQUIRED, 'Only an administrator can do that.', 403),
      ],
    });
    await open();

    fireEvent.click(removeControl());
    confirmRemoval();

    expect(await screen.findByRole('alert')).toHaveProperty(
      'textContent',
      'Only an administrator can do that.',
    );
    // The tile is still there, and so is the Administrator's work on it.
    expect(screen.getByLabelText(/^size$/i)).toBeTruthy();
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('surfaces a failure that never reached the API', async () => {
    stubFetch({ [`GET ${LOOKUP}`]: [{ status: 200, body: FOUND }] });
    await open();
    vi.stubGlobal('fetch', () => Promise.reject(new TypeError('offline')));

    fireEvent.click(removeControl());
    confirmRemoval();

    // `apiRequest` turns a dead connection into its own `ApiRequestError`, so
    // what is rendered is a sentence rather than silence — and `REMOVE_FAILED`
    // is only reachable when nothing came back to carry one of the API's.
    expect((await screen.findByRole('alert')).textContent).toMatch(/could not reach the server/i);
    expect(screen.getByLabelText(/^size$/i)).toBeTruthy();
  });

  it('is frozen while a save is in flight', async () => {
    // A removal started underneath a save would race a request the
    // Administrator is still waiting on, and would win — leaving a `404` for
    // the save and no way to tell which press caused it.
    vi.stubGlobal('fetch', (_input: string, init: RequestInit = {}) => {
      if ((init.method ?? 'GET') === 'GET') {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: () => Promise.resolve(FOUND),
        } as Response);
      }
      return new Promise<Response>(() => undefined);
    });

    await open();
    save();

    await waitFor(() => {
      expect(screen.getByText('Saving…')).toBeTruthy();
    });
    expect((removeControl() as HTMLButtonElement).disabled).toBe(true);
  });

  it('is frozen while a lookup is in flight', async () => {
    // A Find still in flight will `adopt()` whatever it finds, so a removal
    // pressed under it would name whichever tile was loaded first.
    let release = NOT_YET;
    let answered = 0;
    vi.stubGlobal('fetch', () => {
      answered += 1;
      if (answered === 1) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: () => Promise.resolve(FOUND),
        } as Response);
      }
      return new Promise<Response>((resolve) => {
        release = (): void =>
          resolve({ ok: true, status: 200, json: () => Promise.resolve(FOUND) } as Response);
      });
    });

    await open();
    lookUp('SOMETHING-ELSE');

    await waitFor(() => {
      expect(screen.getByText('Finding…')).toBeTruthy();
    });
    expect((removeControl() as HTMLButtonElement).disabled).toBe(true);

    release();
    await waitFor(() => {
      expect(screen.queryByText('Finding…')).toBeNull();
    });
  });

  it('freezes every way out of the sheet while the removal is in flight', async () => {
    // `ConfirmDialog`'s own rule, at this call site: none of Cancel, `Escape`
    // or the scrim cancels the request, so a sheet dismissed mid-flight would
    // reappear the moment the request failed.
    vi.stubGlobal('fetch', (_input: string, init: RequestInit = {}) => {
      if ((init.method ?? 'GET') === 'GET') {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: () => Promise.resolve(FOUND),
        } as Response);
      }
      return new Promise<Response>(() => undefined);
    });

    await open();
    fireEvent.click(removeControl());
    confirmRemoval();

    const dialog = await screen.findByRole('dialog');
    await waitFor(() => {
      expect(
        (within(dialog).getByRole('button', { name: /^cancel$/i }) as HTMLButtonElement).disabled,
      ).toBe(true);
    });
    fireEvent.keyDown(dialog, { key: 'Escape' });
    expect(screen.getByRole('dialog')).toBeTruthy();
  });

  it('says it is removing, not saving, while the removal is in flight', async () => {
    // The form stays mounted behind the sheet's scrim, so its save indicator is
    // on screen for the whole of the `DELETE`. `submitting` drives both writes,
    // and left undifferentiated the most destructive action on the screen would
    // spend its entire duration announcing itself as a save.
    vi.stubGlobal('fetch', (_input: string, init: RequestInit = {}) => {
      if ((init.method ?? 'GET') === 'GET') {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: () => Promise.resolve(FOUND),
        } as Response);
      }
      return new Promise<Response>(() => undefined);
    });

    await open();
    fireEvent.click(removeControl());
    confirmRemoval();

    await waitFor(() => {
      expect(screen.getByText('Removing…')).toBeTruthy();
    });
    expect(screen.queryByText('Saving…')).toBeNull();
  });

  it('sends one removal however many times the confirm is pressed', async () => {
    // Two presses on one confirm is an ordinary double-click, and the second
    // would otherwise send a `DELETE` for a tile the first is already removing
    // — answered `404`, and rendered as a refusal for an action that in fact
    // succeeded. `ConfirmDialog`'s `busy` freezes the control and
    // `removeTile`'s own `submitting` guard is the belt behind it; this asserts
    // the outcome both exist for.
    const calls: [string, RequestInit][] = [];
    vi.stubGlobal('fetch', (input: string, init: RequestInit = {}) => {
      calls.push([input, init]);
      if ((init.method ?? 'GET') === 'GET') {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: () => Promise.resolve(FOUND),
        } as Response);
      }
      // Never answered: the guard only exists while the removal is unanswered.
      return new Promise<Response>(() => undefined);
    });

    await open();
    fireEvent.click(removeControl());
    const dialog = await screen.findByRole('dialog');

    const confirm = within(dialog).getByRole('button', { name: /^remove tile$/i });
    fireEvent.click(confirm);
    fireEvent.click(confirm);

    await waitFor(() => {
      expect((confirm as HTMLButtonElement).disabled).toBe(true);
    });
    expect(calls.filter(([, init]) => init.method === 'DELETE')).toHaveLength(1);
  });

  it('offers no way back after a removal', async () => {
    // No undo, no restore, no trash state and no grace period (AD-5): the
    // confirmation is the safeguard, and an "Undo" here would be a promise the
    // API has no route to keep.
    stubFetch({
      [`GET ${LOOKUP}`]: [{ status: 200, body: FOUND }],
      [`DELETE ${REMOVE}`]: [{ status: 204 }],
    });
    const { container } = render(<EditTileScreen onBack={(): void => undefined} />);
    lookUp();
    await screen.findByLabelText(/^code$/i);

    fireEvent.click(removeControl());
    confirmRemoval();

    await waitFor(() => {
      expect(screen.queryByLabelText(/^size$/i)).toBeNull();
    });
    const text = container.textContent ?? '';
    expect(/\bundo\b/i.test(text)).toBe(false);
    expect(/\brestore\b/i.test(text)).toBe(false);
    expect(screen.queryByRole('button', { name: /undo|restore/i })).toBeNull();
  });
});

describe('the screen’s controls', () => {
  it('has exactly the controls it is meant to have before a tile is found', () => {
    stubFetch({});
    renderScreen();

    const found = CONTROL_ROLES.flatMap((role) =>
      screen.queryAllByRole(role).map((element) => `${role}: ${element.textContent ?? ''}`),
    );

    // One textbox and two buttons. A third button here would be a control
    // nobody specified, and on a screen limited to one accent fill it is how a
    // second primary action arrives.
    expect(found).toHaveLength(3);
    expect(screen.getByRole('button', { name: /^find$/i })).toBeTruthy();
    expect(screen.getByRole('button', { name: /^back$/i })).toBeTruthy();
  });

  it('bounds each field the way the server bounds it', async () => {
    stubFetch({ [`GET ${LOOKUP}`]: [{ status: 200, body: FOUND }] });
    await open();

    expect(screen.getByLabelText(/find a tile by code/i).getAttribute('maxLength')).toBe('200');
    expect(screen.getByLabelText(/^code$/i).getAttribute('maxLength')).toBe('200');
    expect(screen.getByLabelText(/^size$/i).getAttribute('maxLength')).toBe('100');
    expect(screen.getByLabelText(/^category$/i).getAttribute('maxLength')).toBe('200');
  });

  it('accepts several files and does not narrow the picker to one format', async () => {
    // The real catalogue holds `.tif` alongside `.jpg`, and content decides,
    // not the extension (AGENTS.md Policy).
    stubFetch({ [`GET ${LOOKUP}`]: [{ status: 200, body: FOUND }] });
    await open();
    const input = screen.getByLabelText(/add reference images/i);

    expect(input.getAttribute('multiple')).not.toBeNull();
    expect(input.getAttribute('accept')).toBe('image/*');
  });

  it('describes the file input by its limits', async () => {
    // The count and the byte ceiling are stated in that hint and nowhere else.
    // Unbound, a screen-reader user meets both as a refusal after choosing the
    // files.
    stubFetch({ [`GET ${LOOKUP}`]: [{ status: 200, body: FOUND }] });
    await open();

    const input = screen.getByLabelText(/add reference images/i);
    const hintId = input.getAttribute('aria-describedby');

    expect(hintId).toBeTruthy();
    expect(document.getElementById(hintId!)?.textContent).toMatch(/at a time/i);
  });

  it('names each remove checkbox for the image it removes', async () => {
    // Out of the gallery's visual context these are otherwise three checkboxes
    // all called "Remove", on the one destructive control inside the form —
    // Remove tile sits below the form and ends the tile instead — and the
    // thumbnail beside each already names the image it belongs to.
    stubFetch({ [`GET ${LOOKUP}`]: [{ status: 200, body: FOUND }] });
    await open();

    const names = screen
      .getAllByRole('checkbox')
      .map((box) => box.getAttribute('aria-label') ?? box.textContent ?? '');

    expect(names).toHaveLength(FOUND.reference_images.length);
    expect(new Set(names).size).toBe(names.length);
    for (const name of names) expect(name).toContain(CODE);
  });

  it('binds every hint to the control it is about', async () => {
    // The Category hint carries the AD-18 rule — that clearing the field files
    // the tile under the sentinel rather than dropping it — and it is stated
    // there and nowhere else. Unbound, a screen-reader user never meets it.
    stubFetch({ [`GET ${LOOKUP}`]: [{ status: 200, body: FOUND }] });
    await open();

    expect(describedBy(/find a tile by code/i)).toMatch(/exactly as it is filed/i);
    expect(describedBy(/^size$/i)).toMatch(/top-level folder/i);
    expect(describedBy(/^category$/i)).toMatch(/UNKNOWN/);
    expect(describedBy(/add reference images/i)).toMatch(/at a time/i);

    // The one control on the screen whose press cannot be taken back. Its
    // consequence — permanent, and scans stop returning the tile — is stated
    // beside it and nowhere else on this stage, so unbound it reaches a
    // screen-reader user only as the two words on the button.
    const remove = screen.getByRole('button', { name: /^remove tile$/i });
    const removeHint = remove.getAttribute('aria-describedby');
    expect(removeHint).toBeTruthy();
    expect(document.getElementById(removeHint!)?.textContent).toMatch(/cannot be undone/i);
  });

  it('goes back when Back is pressed', () => {
    stubFetch({});
    const onBack = vi.fn();
    renderScreen(onBack);

    fireEvent.click(screen.getByRole('button', { name: /^back$/i }));

    expect(onBack).toHaveBeenCalledTimes(1);
  });

  it('uses the domain’s own words and none of the retired ones', async () => {
    // AD-18 retires `Product` and `Face`. The rendered text is where they would
    // come back first, and a label is what an Administrator learns the
    // vocabulary from.
    stubFetch({ [`GET ${LOOKUP}`]: [{ status: 200, body: FOUND }] });
    const { container } = render(<EditTileScreen onBack={(): void => undefined} />);
    lookUp();
    await screen.findByLabelText(/^code$/i);
    const text = container.textContent ?? '';

    expect(text).toMatch(/Edit tile/);
    expect(text).toMatch(/Reference images/);
    expect(/\bproducts?\b/i.test(text)).toBe(false);
    expect(/\bfaces?\b/i.test(text)).toBe(false);
  });
});

describe('a tile handed over by a Catalogue row', () => {
  // Story 2.5's one change to this screen: it accepts a `Tile` and adopts it as
  // the starting tile, so a row opens straight onto the edit form. The code
  // lookup stage is untouched and is proved still to work below — it is the
  // door for a tile nobody handed over.
  it('opens on the edit form, pre-filled, with no request made', async () => {
    // Adopted as the *initial* state rather than through an effect: an effect
    // would paint the empty stage for one frame and replace it on the next,
    // which is a flash of a form the Administrator never asked for. And nothing
    // is fetched — the row already carried the whole tile, which is why the
    // product serves no `GET /admin/tiles/{tile_id}`.
    const { calls } = stubFetch({});
    withTile();

    expect((await screen.findByLabelText(/^code$/i)).getAttribute('value')).toBe(CODE);
    expect(screen.getByLabelText(/^size$/i).getAttribute('value')).toBe(FOUND.size);
    expect(screen.getByLabelText(/^category$/i).getAttribute('value')).toBe(FOUND.category);
    expect(calls).toEqual([]);
  });

  it('shows the tile’s reference images without looking them up', async () => {
    stubFetch({});
    withTile();

    await screen.findByLabelText(/^code$/i);

    for (const [index, image] of FOUND.reference_images.entries()) {
      const thumbnail = screen.getByAltText(`Reference image ${index + 1} of ${CODE}`);
      expect(thumbnail.getAttribute('src')).toBe(
        `/api/admin/tiles/${TILE_ID}/images/${image.id}`,
      );
    }
  });

  it('saves that tile by its own id, with no code typed anywhere', async () => {
    // The end-to-end claim: a row opens the screen and the very next action is
    // a save against the right tile. Nothing was transcribed and nothing was
    // looked up.
    const { calls } = stubFetch({ [`PATCH ${SAVE}`]: [{ status: 200, body: SAVED_TILE }] });
    withTile();

    await screen.findByLabelText(/^code$/i);
    save();

    await screen.findByText(/^saved\.$/i);
    const writes = calls.filter(([, init]) => init.method === 'PATCH');
    expect(writes).toHaveLength(1);
    expect(writes[0]?.[0]).toBe(SAVE);
    expect(calls.some(([path]) => path.includes('/lookup'))).toBe(false);
  });

  it('leaves for the surface that opened it once a removal is confirmed', async () => {
    // A confirmed removal ends the tile this screen is about, and this screen
    // was opened *about that tile* — so it has nothing left to show. Staying
    // would re-render as a code-entry stage for a Code that no longer names
    // anything, with `Back` as the only way out; the Catalogue's refetch on
    // mount is what makes the row's absence visible instead.
    const onRemoved = vi.fn();
    stubFetch({ [`DELETE ${REMOVE}`]: [{ status: 204 }] });
    withTile(FOUND, onRemoved);

    await screen.findByLabelText(/^code$/i);
    fireEvent.click(removeControl());
    confirmRemoval();

    await waitFor(() => {
      expect(onRemoved).toHaveBeenCalledTimes(1);
    });
    // And the announcement that belongs to the lookup stage is **not** left
    // standing: the screen is leaving, not returning to a stage it never came
    // from.
    expect(screen.queryByText(`${CODE} removed.`)).toBeNull();
  });

  it('stays put and says why when the removal is refused', async () => {
    // A refusal is not a removal. The screen keeps the Administrator where the
    // alert is readable rather than leaving for a surface that would show the
    // tile still there with no explanation.
    const onRemoved = vi.fn();
    stubFetch({
      [`DELETE ${REMOVE}`]: [refusal('internal_error', 'Something went wrong.', 500)],
    });
    withTile(FOUND, onRemoved);

    await screen.findByLabelText(/^code$/i);
    fireEvent.click(removeControl());
    confirmRemoval();

    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toBe('Something went wrong.');
    expect(onRemoved).not.toHaveBeenCalled();
  });

  it('falls back to the code lookup when the tile is already gone', async () => {
    // The one refusal that is not "stay put": a `404` means the tile this
    // screen was handed no longer exists, so there is nothing for the form to
    // be about *and* nothing for `onRemoved` to return to that would explain
    // why — the Catalogue's own refetch is what shows the row gone, and it is
    // reached from `Back`. The screen therefore does what its docstring says
    // it does on a `404` from either write: clears the tile, states the
    // server's own sentence, and leaves the lookup stage standing as the way
    // to find another one.
    //
    // Reachable only since Story 2.5, because the handed-over path is: two
    // Administrators on the same row, the second confirming a removal the
    // first already made.
    const onRemoved = vi.fn();
    stubFetch({ [`DELETE ${REMOVE}`]: [refusal(TILE_NOT_FOUND, NO_SUCH_TILE, 404)] });
    withTile(FOUND, onRemoved);

    await screen.findByLabelText(/^code$/i);
    fireEvent.click(removeControl());
    confirmRemoval();

    expect(await screen.findByRole('alert')).toHaveProperty('textContent', NO_SUCH_TILE);
    // Not `onRemoved`: the gate would unmount this screen and the sentence
    // with it, leaving the Administrator on a Catalogue that simply no longer
    // has the row, with nothing saying the removal was not theirs.
    expect(onRemoved).not.toHaveBeenCalled();
    // The form is gone with the tile it described, and the lookup stage — the
    // one control that can still do anything — has the focus.
    expect(screen.queryByLabelText(/^size$/i)).toBeNull();
    expect(document.activeElement).toBe(screen.getByLabelText(/find a tile by code/i));
  });

  it('announces a removal of a tile it found for itself, rather than leaving', async () => {
    // The lookup stage is still reachable from a row-opened screen — a `404`
    // drops back to it — and a tile found *there* did not come from a Catalogue
    // row. Removing it belongs to the lookup: `onRemoved` would send the
    // Administrator to a surface that never listed the tile, and swallow the
    // confirmation on the way.
    //
    // The branch keys on which tile was removed, not on how the screen was
    // opened, which is what this pins: change it back to `opened !== undefined`
    // and this test leaves for the Catalogue with nothing said.
    const OTHER_CODE = 'RP.CMA.0011DJ.SM.0T';
    const OTHER_ID = 'c58e2a91-6d04-4b73-8f21-9a7c3e5d0b16';
    const other: Tile = { ...FOUND, id: OTHER_ID, code: OTHER_CODE };
    const onRemoved = vi.fn();
    stubFetch({
      // The tile the row handed over went while this screen was open.
      [`DELETE ${REMOVE}`]: [refusal(TILE_NOT_FOUND, NO_SUCH_TILE, 404)],
      [`GET /api/admin/tiles/lookup?code=${encodeURIComponent(OTHER_CODE)}`]: [
        { status: 200, body: other },
      ],
      [`DELETE /api/admin/tiles/${OTHER_ID}`]: [{ status: 204 }],
    });
    withTile(FOUND, onRemoved);

    await screen.findByLabelText(/^code$/i);
    fireEvent.click(removeControl());
    confirmRemoval();
    await screen.findByRole('alert');

    // Back at the lookup stage, where a different tile is found.
    lookUp(OTHER_CODE);
    await waitFor(() => {
      expect(screen.getByLabelText(/^code$/i).getAttribute('value')).toBe(OTHER_CODE);
    });

    fireEvent.click(removeControl());
    confirmRemoval();

    expect(await screen.findByText(`${OTHER_CODE} removed.`)).toBeTruthy();
    expect(onRemoved).not.toHaveBeenCalled();
    expect(document.activeElement).toBe(screen.getByLabelText(/find a tile by code/i));
  });

  it('still offers the code lookup when no tile was handed over', async () => {
    // The stage Story 2.5 deliberately did not weaken. It is what a tile
    // nobody handed the screen still needs, Story 2.2's authorization clause
    // names the route it calls, and deleting a tested route inside a search
    // story would be a separate decision.
    stubFetch({ [`GET ${LOOKUP}`]: [{ status: 200, body: FOUND }] });
    renderScreen();

    // Nothing is loaded until a Code is entered and Find is pressed.
    expect(screen.queryByLabelText(/^code$/i)).toBeNull();

    lookUp();

    expect((await screen.findByLabelText(/^code$/i)).getAttribute('value')).toBe(CODE);
  });
});

describe('the route from the Catalogue', () => {
  // Retargeted by Story 2.5 rather than deleted. This screen had a door of its
  // own on the home panel while there was no Catalogue to reach it from;
  // EXPERIENCE.md line 36 always reached Edit Tile from a Catalogue *row*, and
  // that surface now exists — so the entry is a row-end control there and the
  // home panel carries one Catalogue door instead of three tile ones.
  function stubSession(user: User | null): { calls: [string, RequestInit][] } {
    return stubFetch({
      'GET /api/auth/session': [
        user === null
          ? { status: 401, body: { error: { code: 'unauthorized', message: 'Not signed in.' } } }
          : { status: 200, body: user },
      ],
      // The Catalogue's own browse, answering with the tile whose row this
      // block presses Edit on.
      'GET /api/admin/tiles?q=': [{ status: 200, body: [FOUND] }],
      [`GET ${LOOKUP}`]: [{ status: 200, body: FOUND }],
    });
  }

  it('is reached from a Catalogue row by an Administrator', async () => {
    stubSession(ADMIN);
    render(<App />);

    fireEvent.click(await screen.findByRole('button', { name: /^catalogue$/i }));
    await screen.findByRole('table');

    fireEvent.click(screen.getByRole('button', { name: `Edit ${CODE}` }));

    expect(await screen.findByRole('heading', { name: /^edit tile$/i })).toBeTruthy();
    // On the edit form already, because the row handed the tile over.
    expect((await screen.findByLabelText(/^code$/i)).getAttribute('value')).toBe(CODE);
  });

  it('has no door of its own on the home panel any more', async () => {
    // Two ways to reach one screen is the thing Story 2.5 removed — and this
    // was the least defensible of the three doors, since EXPERIENCE.md line 36
    // reaches Edit Tile from a row and from nowhere else.
    stubSession(ADMIN);
    render(<App />);

    await screen.findByText(/signed in as nadeesha silva/i);

    expect(screen.queryByRole('button', { name: /^edit tile$/i })).toBeNull();
    expect(screen.getByRole('button', { name: /^catalogue$/i })).toBeTruthy();
  });

  it('is not reachable by a Staff user at all', async () => {
    // EXPERIENCE.md line 18: the nav is role-conditional, not a menu with
    // disabled items. The server refuses them regardless (AGENTS.md Policy);
    // this is the courtesy on top of the control.
    stubSession(STAFF);
    render(<App />);

    await screen.findByText(/signed in as kasun perera/i);

    expect(screen.queryByRole('button', { name: /^catalogue$/i })).toBeNull();
    expect(screen.queryByRole('button', { name: /^edit tile$/i })).toBeNull();
  });

  it('returns to the Catalogue from Back, not to the home panel', async () => {
    // The row is where Edit was pressed, and `CatalogueScreen` refetches on
    // mount — so returning to it shows the row as it was just saved.
    stubSession(ADMIN);
    render(<App />);

    fireEvent.click(await screen.findByRole('button', { name: /^catalogue$/i }));
    await screen.findByRole('table');
    fireEvent.click(screen.getByRole('button', { name: `Edit ${CODE}` }));
    await screen.findByRole('heading', { name: /^edit tile$/i });

    fireEvent.click(screen.getByRole('button', { name: /^back$/i }));

    expect(await screen.findByRole('table')).toBeTruthy();
    expect(screen.queryByText(/signed in as nadeesha silva/i)).toBeNull();
  });
});
