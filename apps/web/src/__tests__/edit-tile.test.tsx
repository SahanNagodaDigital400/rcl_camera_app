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
    // all called "Remove", on the one destructive control of the screen — and
    // the thumbnail beside each already names the image it belongs to.
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

describe('the door on the home panel', () => {
  function stubSession(user: User | null): { calls: [string, RequestInit][] } {
    return stubFetch({
      'GET /api/auth/session': [
        user === null
          ? { status: 401, body: { error: { code: 'unauthorized', message: 'Not signed in.' } } }
          : { status: 200, body: user },
      ],
      [`GET ${LOOKUP}`]: [{ status: 200, body: FOUND }],
    });
  }

  it('is offered to an Administrator and opens the screen', async () => {
    stubSession(ADMIN);
    render(<App />);

    fireEvent.click(await screen.findByRole('button', { name: /^edit tile$/i }));

    expect(await screen.findByRole('heading', { name: /^edit tile$/i })).toBeTruthy();
  });

  it('is not offered to a Staff user at all', async () => {
    // EXPERIENCE.md line 18: the nav is role-conditional, not a menu with
    // disabled items. The server refuses them regardless (AGENTS.md Policy);
    // this is the courtesy on top of the control.
    stubSession(STAFF);
    render(<App />);

    await screen.findByText(/signed in as kasun perera/i);

    expect(screen.queryByRole('button', { name: /^edit tile$/i })).toBeNull();
  });

  it('returns to the home panel from Back', async () => {
    stubSession(ADMIN);
    render(<App />);

    fireEvent.click(await screen.findByRole('button', { name: /^edit tile$/i }));
    await screen.findByRole('heading', { name: /^edit tile$/i });

    fireEvent.click(screen.getByRole('button', { name: /^back$/i }));

    expect(await screen.findByText(/signed in as nadeesha silva/i)).toBeTruthy();
  });
});
