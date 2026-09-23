/**
 * Add tile — the screen, and the route the app takes to reach it.
 *
 * Two halves, driven through two different roots, the way
 * `create-user.test.tsx` splits them. The screen's own behaviour runs against
 * a stubbed `fetch` with the screen rendered directly, because it calls
 * `apiRequest` itself rather than going through `SessionProvider`; whether the
 * app *reaches* the screen at all runs through `App`, because the role
 * condition and the section state live in the gate.
 *
 * Four assertions here are the ones nothing else in the suite can make: that
 * the request is a `FormData` carrying exactly the named parts (a JSON body
 * would be accepted by every type in the app and rejected by the server), that
 * the indicator cycles `Saving…` → `Saved.`, that a Staff user is offered no
 * door, and that nothing on this screen shows a similarity value or says
 * "product".
 */
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import App from '../App';
import {
  CODE_ALREADY_EXISTS,
  INVALID_CODE,
  MATCHING_UNAVAILABLE,
  REQUEST_TIMEOUT_MS,
  UNREADABLE_IMAGE,
  UPLOAD_TIMEOUT_MS,
} from '../api/client';
import { AddTileScreen } from '../screens/AddTileScreen';
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

/** What the API answers on a `201`: the Tile it just wrote. */
const CREATED: Tile = {
  id: 'b41d8e06-5a72-4f39-9c88-0d3e1f7a2b65',
  code: CODE,
  size: '45X90',
  category: 'CREMA MARMOL',
  face_number: null,
  reference_images: [
    {
      id: '2c9a0f13-6b48-4d27-9e5a-1b3c7d8e0f45',
      width: 2048,
      height: 1365,
      featureless: false,
      created_at: '2026-09-21T09:30:00Z',
    },
  ],
  created_at: '2026-09-21T09:30:00Z',
  updated_at: '2026-09-21T09:30:00Z',
};

const FLAGGED: Tile = {
  ...CREATED,
  reference_images: [{ ...CREATED.reference_images[0]!, featureless: true }],
};

/**
 * The API's own sentences, character for character.
 *
 * Restated rather than imported because nothing crosses that boundary at build
 * time — `error-code-parity.test.ts` pins the *codes* and not the sentences.
 * If one drifts, the API's sentence is still what the screen renders at run
 * time; what stops being true is this file's claim to be asserting it.
 */
const CODE_IN_USE =
  'A tile with that code already exists. Edit that tile, or use a different code.';
const NOT_AN_IMAGE = 'That file is not a readable image.';

interface Reply {
  status: number;
  body?: unknown;
}

/**
 * Replace `fetch` with a queue keyed by **method and path**, and record every call.
 *
 * A local copy rather than a shared helper, as the other suites keep theirs —
 * a stub shared across files is a fixture two tests can change under each
 * other. `vi.stubGlobal` rather than assigning, because jsdom does not
 * implement `fetch` and the global may not be there to spy on.
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
  render(<AddTileScreen onBack={onBack} />);
}

function aFile(name = 'reference.jpg', type = 'image/jpeg'): File {
  return new File([new Uint8Array([1, 2, 3, 4])], name, { type });
}

function fill({
  code = CODE,
  size = '45X90',
  category = 'CREMA MARMOL',
  files = [aFile()],
}: { code?: string; size?: string; category?: string; files?: File[] } = {}): void {
  fireEvent.change(screen.getByLabelText(/^code$/i), { target: { value: code } });
  fireEvent.change(screen.getByLabelText(/^size$/i), { target: { value: size } });
  fireEvent.change(screen.getByLabelText(/category/i), { target: { value: category } });
  if (files.length > 0) {
    fireEvent.change(screen.getByLabelText(/reference images/i), { target: { files } });
  }
}

function submit(): void {
  fireEvent.click(screen.getByRole('button', { name: /^save$/i }));
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

describe('the add tile form', () => {
  it('sends a multipart body with exactly the parts the endpoint names', async () => {
    const { calls } = stubFetch({ 'POST /api/admin/tiles': [{ status: 201, body: CREATED }] });
    renderScreen();

    fill();
    submit();

    await screen.findByText(/tile added/i);
    const [path, init] = calls[0] ?? ['', {}];

    expect(path).toBe('/api/admin/tiles');
    expect(init.method).toBe('POST');
    // A `FormData`, not JSON. `JSON.stringify(formData)` is `'{}'` — not an
    // error, just an empty object — so a body of files would arrive as nothing
    // at all with every type check in the app satisfied.
    expect(init.body).toBeInstanceOf(FormData);

    const body = init.body as FormData;
    // As a set, so the assertion is about which parts were sent and not
    // about the order `FormData` happened to keep them in.
    expect(new Set(body.keys())).toEqual(new Set(['code', 'size', 'category', 'images']));
    expect(body.get('code')).toBe(CODE);
    expect(body.get('size')).toBe('45X90');
    expect(body.get('category')).toBe('CREMA MARMOL');
    expect(body.getAll('images')).toHaveLength(1);
  });

  it('is not given the default request timeout', async () => {
    // 15 seconds is wrong for this request by an order of magnitude: one
    // image is 16 forward passes (AD-13) and eight is minutes. The default
    // aborts while the server is still working, the server commits anyway,
    // and the Administrator is shown a network error for a tile that now
    // exists — so pressing Save again answers `code_already_exists` and the
    // app reads as contradicting itself.
    //
    // Observed through the timer the request schedules, because that timer
    // *is* the abort. `api-client.test.ts` holds the other half: that
    // `apiRequest` honours the bound it is given.
    const scheduled: unknown[] = [];
    const real = globalThis.setTimeout;
    vi.stubGlobal('setTimeout', ((handler: TimerHandler, ms?: number, ...rest: unknown[]) => {
      scheduled.push(ms);
      return real(handler, ms, ...rest);
    }) as typeof globalThis.setTimeout);

    const { calls } = stubFetch({ 'POST /api/admin/tiles': [{ status: 201, body: CREATED }] });
    renderScreen();

    fill();
    submit();

    await screen.findByText(/tile added/i);

    expect(calls).toHaveLength(1);
    expect(scheduled).toContain(UPLOAD_TIMEOUT_MS);
    expect(scheduled).not.toContain(REQUEST_TIMEOUT_MS);
  });

  it('lets the browser write the content type, so the boundary is right', async () => {
    const { calls } = stubFetch({ 'POST /api/admin/tiles': [{ status: 201, body: CREATED }] });
    renderScreen();

    fill();
    submit();

    await screen.findByText(/tile added/i);
    const init = calls[0]?.[1] ?? {};

    // Setting it by hand omits the boundary token that delimits the parts, and
    // the server then cannot parse a body that looks perfectly well formed.
    expect(init.headers).toBeUndefined();
  });

  it('sends one part per file when several are chosen', async () => {
    const { calls } = stubFetch({ 'POST /api/admin/tiles': [{ status: 201, body: CREATED }] });
    renderScreen();

    fill({ files: [aFile('a.jpg'), aFile('b.tif', 'image/tiff')] });
    submit();

    await screen.findByText(/tile added/i);
    const body = (calls[0]?.[1].body ?? new FormData()) as FormData;

    // A `.tif` among them, because the real catalogue holds them and the
    // screen must not pre-judge a file the server decides on by content.
    expect(body.getAll('images')).toHaveLength(2);
  });

  it('sends the category as an empty part rather than omitting it', async () => {
    const { calls } = stubFetch({ 'POST /api/admin/tiles': [{ status: 201, body: CREATED }] });
    renderScreen();

    fill({ category: '' });
    submit();

    await screen.findByText(/tile added/i);
    const body = (calls[0]?.[1].body ?? new FormData()) as FormData;

    // The endpoint resolves an absent Category to the UNKNOWN sentinel
    // (AD-18), so an empty part and a missing part mean the same thing — and
    // sending it always is one branch fewer in the screen.
    expect(body.get('category')).toBe('');
  });

  it('cycles the indicator from Saving to Saved beside the action', async () => {
    // Held open deliberately: the in-flight state is the half of the contract
    // a settled request cannot show, and a stub that resolves immediately
    // would assert only the second frame.
    let release = NOT_YET;
    const answer = (resolve: (value: Response) => void): void => {
      release = (): void =>
        resolve({ ok: true, status: 201, json: () => Promise.resolve(CREATED) } as Response);
    };
    vi.stubGlobal('fetch', () => new Promise<Response>(answer));
    renderScreen();

    fill();
    submit();

    // In flight: muted, and the submit is disabled so a second press cannot
    // add the same tile twice.
    await waitFor(() => {
      expect(screen.getByRole('status').textContent).toBe('Saving…');
    });
    expect(screen.getByRole('button', { name: /^save$/i })).toHaveProperty('disabled', true);

    release();

    // Settled: `Saved.`, inline, never a corner toast (EXPERIENCE.md's Save
    // indicator row). `getByRole` rather than `getAllByRole(...)[0]`: the
    // screen has exactly one live region, and an assertion indexed into a list
    // would pass just as well if a second one appeared and the two swapped.
    await waitFor(() => {
      expect(screen.getByRole('status').textContent).toBe('Saved.');
    });
    // The result panel is reached by its heading, not announced a second time.
    expect(screen.getByRole('region', { name: 'Tile added' })).toBeTruthy();
  });

  it('names the category sentinel rather than leaving the row empty', async () => {
    // `category` is nullable on the wire. The endpoint resolves a blank one to
    // the sentinel so it never sends null today, but the contract permits it
    // and an empty `<dd>` under a `<dt>Category</dt>` reads as a missing
    // answer rather than as the filed-under-UNKNOWN one it is.
    stubFetch({
      'POST /api/admin/tiles': [{ status: 201, body: { ...CREATED, category: null } }],
    });
    renderScreen();

    fill();
    submit();

    const panel = await screen.findByRole('region', { name: 'Tile added' });

    expect(panel.textContent).toContain('UNKNOWN');
  });

  it('clears the form after a save so the next tile can be typed', async () => {
    stubFetch({ 'POST /api/admin/tiles': [{ status: 201, body: CREATED }] });
    renderScreen();

    fill();
    submit();

    await screen.findByText(/tile added/i);

    expect(screen.getByLabelText(/^code$/i)).toHaveProperty('value', '');
    expect(screen.getByLabelText(/^size$/i)).toHaveProperty('value', '');
  });

  it('shows the added tile, and shows no similarity value anywhere', async () => {
    stubFetch({ 'POST /api/admin/tiles': [{ status: 201, body: CREATED }] });
    const { container } = render(<AddTileScreen onBack={(): void => undefined} />);

    fill();
    submit();

    await screen.findByText(/tile added/i);

    expect(screen.getByText(CODE)).toBeTruthy();
    expect(screen.getByText('45X90')).toBeTruthy();
    expect(screen.getByText('CREMA MARMOL')).toBeTruthy();
    // AD-20: no percentage, no bar, no star rating, no word derived from a
    // score. Asserted over the rendered text rather than over the source,
    // because this is what the Administrator actually sees.
    expect(container.textContent).not.toMatch(/\d+\s*%/);
    expect(container.textContent?.toLowerCase()).not.toMatch(
      /similarity|confidence|match score/,
    );
  });

  it('surfaces the quality flag on this screen rather than in a report', async () => {
    // The epic's edge case for Flow 2: an image below the quality threshold is
    // flagged where the Administrator already is, not somewhere they would
    // have to go looking. Stated in words, never as a number.
    stubFetch({ 'POST /api/admin/tiles': [{ status: 201, body: FLAGGED }] });
    renderScreen();

    fill();
    submit();

    expect(await screen.findByText(/very little visible texture/i)).toBeTruthy();
  });

  it('says nothing about texture when the image is fine', async () => {
    stubFetch({ 'POST /api/admin/tiles': [{ status: 201, body: CREATED }] });
    renderScreen();

    fill();
    submit();

    await screen.findByText(/tile added/i);

    expect(screen.queryByText(/very little visible texture/i)).toBeNull();
  });
});

describe('the refusals', () => {
  it.each([
    ['a blank code', { code: '' }, /^code$/i, 'Enter the tile’s code.'],
    ['a blank size', { size: '' }, /^size$/i, 'Enter the tile’s size.'],
  ])('refuses %s before asking the server, and focuses the field', async (
    _label,
    fields,
    label,
    message,
  ) => {
    const { calls } = stubFetch({});
    renderScreen();

    fill(fields);
    submit();

    expect(await screen.findByRole('alert')).toHaveProperty('textContent', message);
    expect(document.activeElement).toBe(screen.getByLabelText(label));
    // Nothing was uploaded: a blank field must not cost a file transfer and
    // tens of seconds of server CPU to be told a box is empty.
    expect(calls).toHaveLength(0);
  });

  it('refuses a submit with no file chosen', async () => {
    const { calls } = stubFetch({});
    renderScreen();

    fireEvent.change(screen.getByLabelText(/^code$/i), { target: { value: CODE } });
    fireEvent.change(screen.getByLabelText(/^size$/i), { target: { value: '45X90' } });
    submit();

    expect(await screen.findByRole('alert')).toHaveProperty(
      'textContent',
      'Choose at least one reference image.',
    );
    expect(calls).toHaveLength(0);
  });

  it('refuses more files than the endpoint accepts without uploading them', async () => {
    // Nine reference images is comfortably hundreds of megabytes. Refusing
    // after the upload would make the Administrator watch it finish and then
    // be told the count was never going to be accepted.
    const { calls } = stubFetch({});
    renderScreen();

    fill({ files: Array.from({ length: 9 }, (_unused, index) => aFile(`${index}.jpg`)) });
    submit();

    expect((await screen.findByRole('alert')).textContent).toMatch(/at most 8/i);
    expect(calls).toHaveLength(0);
    expect(screen.getByLabelText(/reference images/i).getAttribute('aria-invalid')).toBe('true');
  });

  it('describes the file input by its limits, and by the refusal as well', async () => {
    // The count and the byte ceiling are stated in that hint and nowhere else.
    // Unbound, a screen-reader user meets both as a refusal after choosing the
    // files — and when the refusal arrives it must be added to the
    // description, not put in the hint's place.
    const { calls } = stubFetch({});
    renderScreen();

    const input = screen.getByLabelText(/reference images/i);
    const hintId = input.getAttribute('aria-describedby');

    expect(hintId).toBeTruthy();
    expect(document.getElementById(hintId!)?.textContent).toMatch(/at a time/i);

    fill({ files: Array.from({ length: 9 }, (_unused, index) => aFile(`${index}.jpg`)) });
    submit();

    const alert = await screen.findByRole('alert');
    const described = input.getAttribute('aria-describedby')?.split(' ') ?? [];

    expect(calls).toHaveLength(0);
    expect(described).toContain(hintId);
    expect(described).toContain(alert.getAttribute('id'));
  });

  it('refuses a file over the byte ceiling without uploading it', async () => {
    const { calls } = stubFetch({});
    renderScreen();

    const huge = new File(['x'], 'huge.jpg', { type: 'image/jpeg' });
    // `File.size` is derived from the parts, so a 128 MB fixture would mean
    // allocating 128 MB in a unit test. Overridden instead: what is under
    // test is the comparison, not the browser's arithmetic.
    Object.defineProperty(huge, 'size', { value: 200 * 1024 * 1024 });
    fill({ files: [huge] });
    submit();

    expect((await screen.findByRole('alert')).textContent).toMatch(/under 128 MB/i);
    expect(calls).toHaveLength(0);
  });

  it('marks the code field for a duplicate and renders the API’s own sentence', async () => {
    stubFetch({
      'POST /api/admin/tiles': [refusal(CODE_ALREADY_EXISTS, CODE_IN_USE, 409)],
    });
    renderScreen();

    fill();
    submit();

    expect(await screen.findByRole('alert')).toHaveProperty('textContent', CODE_IN_USE);
    expect(screen.getByLabelText(/^code$/i).getAttribute('aria-invalid')).toBe('true');
    // Nothing typed is cleared: a duplicate Code is one field to change, and
    // re-choosing the files would be the Administrator doing the work twice.
    expect(screen.getByLabelText(/^size$/i)).toHaveProperty('value', '45X90');
  });

  it('marks the images control for a file the server could not read', async () => {
    stubFetch({
      'POST /api/admin/tiles': [refusal(UNREADABLE_IMAGE, NOT_AN_IMAGE, 422)],
    });
    renderScreen();

    fill();
    submit();

    expect(await screen.findByRole('alert')).toHaveProperty('textContent', NOT_AN_IMAGE);
    expect(screen.getByLabelText(/reference images/i).getAttribute('aria-invalid')).toBe('true');
  });

  it('marks no field when the server has no image pipeline installed', async () => {
    // Nothing the Administrator typed or chose is at fault and the fix is an
    // operator's, so pointing at an input would send them to correct something
    // that is perfectly fine.
    const message = 'The embedding model is not installed. Run `make model` to download it.';
    stubFetch({ 'POST /api/admin/tiles': [refusal(MATCHING_UNAVAILABLE, message, 503)] });
    renderScreen();

    fill();
    submit();

    expect(await screen.findByRole('alert')).toHaveProperty('textContent', message);
    for (const label of [/^code$/i, /^size$/i, /reference images/i]) {
      expect(screen.getByLabelText(label).getAttribute('aria-invalid')).toBe('false');
    }
  });

  it('renders exactly one alert, however many things are wrong', async () => {
    stubFetch({
      'POST /api/admin/tiles': [refusal(INVALID_CODE, 'A Code must not be blank.', 422)],
    });
    renderScreen();

    fill();
    submit();

    await screen.findByRole('alert');

    expect(screen.getAllByRole('alert')).toHaveLength(1);
  });

  it('retires the result panel when a later submit is refused', async () => {
    stubFetch({
      'POST /api/admin/tiles': [
        { status: 201, body: CREATED },
        refusal(CODE_ALREADY_EXISTS, CODE_IN_USE, 409),
      ],
    });
    renderScreen();

    fill();
    submit();
    await screen.findByText(/tile added/i);

    fill();
    submit();
    await screen.findByRole('alert');

    // The panel described a tile that was added; leaving it beside a refusal
    // reads as though the refused one had landed too.
    expect(screen.queryByText(/tile added/i)).toBeNull();
  });
});

describe('the screen’s controls', () => {
  it('has exactly the controls it is meant to have', () => {
    renderScreen();

    const found = CONTROL_ROLES.flatMap((role) =>
      screen.queryAllByRole(role).map((element) => `${role}: ${element.textContent ?? ''}`),
    );

    // Three textboxes and two buttons. The file input is deliberately not in
    // this count: `<input type="file">` has no implicit ARIA role, so it is
    // unreachable by role and is asserted by its label instead — which is also
    // why its label has to be right, and why the test below reads it that way.
    //
    // A third button here would be a control nobody specified, and on a screen
    // limited to one accent fill it is how a second primary action arrives.
    expect(found).toHaveLength(5);
    expect(screen.getByRole('button', { name: /^save$/i })).toBeTruthy();
    expect(screen.getByRole('button', { name: /^back$/i })).toBeTruthy();
    expect(screen.getByLabelText(/reference images/i).getAttribute('type')).toBe('file');
  });

  it('bounds each field the way the server bounds it', () => {
    renderScreen();

    expect(screen.getByLabelText(/^code$/i).getAttribute('maxLength')).toBe('200');
    expect(screen.getByLabelText(/^size$/i).getAttribute('maxLength')).toBe('100');
    expect(screen.getByLabelText(/category/i).getAttribute('maxLength')).toBe('200');
  });

  it('accepts several files and does not narrow the picker to one format', () => {
    // The real catalogue holds `.tif` alongside `.jpg`, and content decides,
    // not the extension (AGENTS.md Policy). A narrower `accept` would hide
    // files that are perfectly valid.
    renderScreen();
    const input = screen.getByLabelText(/reference images/i);

    expect(input.getAttribute('multiple')).not.toBeNull();
    expect(input.getAttribute('accept')).toBe('image/*');
  });

  it('goes back when Back is pressed', () => {
    const onBack = vi.fn();
    renderScreen(onBack);

    fireEvent.click(screen.getByRole('button', { name: /^back$/i }));

    expect(onBack).toHaveBeenCalledTimes(1);
  });

  it('uses the domain’s own words and none of the retired ones', () => {
    // AD-18 retires `Product` and `Face`. The rendered text is where they
    // would come back first, and a label is what an Administrator learns the
    // vocabulary from.
    const { container } = render(<AddTileScreen onBack={(): void => undefined} />);
    const text = container.textContent ?? '';

    expect(text).toMatch(/Add tile/);
    expect(text).toMatch(/Code/);
    expect(/\bproducts?\b/i.test(text)).toBe(false);
    expect(/\bfaces?\b/i.test(text)).toBe(false);
  });
});

describe('the route from the Catalogue', () => {
  // Retargeted by Story 2.5 rather than deleted. This screen had a door of its
  // own on the home panel while there was no Catalogue to reach it from;
  // EXPERIENCE.md line 36 always reached Add Tile from "+ Add Tile" on the
  // Catalogue or from a row, and that surface now exists — so the entry is a
  // control there and the home panel carries one Catalogue door instead of
  // three tile ones. What this block still proves is the same two things: an
  // Administrator can get here, and a Staff user cannot.
  function stubSession(user: User | null): { calls: [string, RequestInit][] } {
    return stubFetch({
      'GET /api/auth/session': [
        user === null
          ? { status: 401, body: { error: { code: 'unauthorized', message: 'Not signed in.' } } }
          : { status: 200, body: user },
      ],
      // The Catalogue's own browse, so the screen this is reached *through*
      // paints rather than sitting on its failure state. An empty catalogue is
      // enough: "+ Add Tile" is in the actions row, not in the table.
      'GET /api/admin/tiles?q=': [{ status: 200, body: [] }],
      'POST /api/admin/tiles': [{ status: 201, body: CREATED }],
    });
  }

  it('is reached from the Catalogue by an Administrator', async () => {
    stubSession(ADMIN);
    render(<App />);

    fireEvent.click(await screen.findByRole('button', { name: /^catalogue$/i }));
    await screen.findByRole('heading', { name: /^catalogue$/i });

    fireEvent.click(screen.getByRole('button', { name: /add tile/i }));

    expect(await screen.findByRole('heading', { name: /^add tile$/i })).toBeTruthy();
  });

  it('has no door of its own on the home panel any more', async () => {
    // Two ways to reach one screen is the thing Story 2.5 removed. Leaving the
    // old door beside the Catalogue's "+ Add Tile" would also contradict
    // EXPERIENCE.md line 36, which names the Catalogue as the only way in.
    stubSession(ADMIN);
    render(<App />);

    await screen.findByRole('heading', { name: /^scan$/i });

    expect(screen.queryByRole('button', { name: /^add tile$/i })).toBeNull();
    expect(screen.getByRole('button', { name: /^catalogue$/i })).toBeTruthy();
  });

  it('is not reachable by a Staff user at all', async () => {
    // EXPERIENCE.md line 18: the nav is role-conditional, not a menu with
    // disabled items — a Staff user should never see an entry they cannot use.
    // The server refuses them regardless (AGENTS.md Policy); this is the
    // courtesy on top of the control.
    stubSession(STAFF);
    render(<App />);

    await screen.findByRole('heading', { name: /^scan$/i });

    expect(screen.queryByRole('button', { name: /^catalogue$/i })).toBeNull();
    expect(screen.queryByRole('button', { name: /add tile/i })).toBeNull();
  });

  it('returns to the Catalogue from Back, not to the home panel', async () => {
    // The Catalogue is where "+ Add Tile" was pressed, and where the new tile
    // belongs — and `CatalogueScreen` refetches on mount, so returning to it
    // lists the tile just added.
    stubSession(ADMIN);
    render(<App />);

    fireEvent.click(await screen.findByRole('button', { name: /^catalogue$/i }));
    await screen.findByRole('heading', { name: /^catalogue$/i });
    fireEvent.click(screen.getByRole('button', { name: /add tile/i }));
    await screen.findByRole('heading', { name: /^add tile$/i });

    fireEvent.click(screen.getByRole('button', { name: /^back$/i }));

    expect(await screen.findByRole('heading', { name: /^catalogue$/i })).toBeTruthy();
    expect(screen.queryByText(/signed in as nadeesha silva/i)).toBeNull();
  });
});
