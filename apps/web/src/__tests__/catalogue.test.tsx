/**
 * Catalogue — the surface FR-18's search lives on, and the route the app takes
 * to reach it.
 *
 * Two halves, driven through two roots, the way `edit-tile.test.tsx` splits
 * them: the screen's own behaviour runs against a stubbed `fetch` with the
 * screen rendered directly, because it calls `apiRequest` itself rather than
 * going through `SessionProvider`; whether the app *reaches* it at all runs
 * through `App`, because the role condition and the section state live in the
 * gate.
 *
 * Six assertions here are the ones nothing else in the suite can make: that the
 * request carries `q` and nothing else, that every row paints its Size, its
 * Category and its proxied thumbnail, that the two empty states are two
 * different sentences, that a row *and* its `Edit` control both open the same
 * tile, that a stale answer is discarded, and that the screen has exactly the
 * controls it is meant to have — no removal, no sort, no pagination and no Size
 * or Category filter.
 */
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { StrictMode } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import App from '../App';
import { CatalogueScreen } from '../screens/CatalogueScreen';
// The same module the screen imports, so a class assertion names the *mapping*
// rather than a hashed string: `vite.config.ts` sets `css: false`, so a
// CSS-module key resolves to a generated name.
import styles from '../screens/CatalogueScreen.module.css';
import type { JSX } from 'react';
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

/** `tile-contract.test.ts`'s own literals, reused rather than invented. */
const CODE = 'RP.CMA.0001DJ.SM.0T';
const SIBLING_CODE = 'RP.CMA.0011DJ.SM.0T';

const FIRST_IMAGE = '2c9a0f13-6b48-4d27-9e5a-1b3c7d8e0f45';
const SECOND_IMAGE = '7d1e4b90-3c26-4a85-91f7-5e0b2d6c8a13';

const TILE: Tile = {
  id: 'b41d8e06-5a72-4f39-9c88-0d3e1f7a2b65',
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

/**
 * The same Size and the same Category, a different Code — and therefore a
 * different Tile (AD-18).
 *
 * Its own id, because React keys a row on it and two rows sharing one id is a
 * duplicate-key warning and a reconciler free to reuse one row's cells for the
 * other.
 */
const SIBLING: Tile = {
  ...TILE,
  id: 'c58e2a91-6d04-4b73-8f21-9a7c3e5d0b16',
  code: SIBLING_CODE,
  reference_images: [
    {
      id: '4a7c1e93-8b52-4d06-a1f8-6e2b0d5c9a37',
      width: 2048,
      height: 1365,
      featureless: false,
      created_at: '2026-09-21T09:32:00Z',
    },
  ],
};

/** The bare-face-number convention, filed under the AD-18 sentinel. */
const BARE: Tile = {
  ...TILE,
  id: '7f1b3c85-2e49-4a07-b6d3-5c80a9e4f217',
  code: '61M',
  size: '60X60',
  category: 'UNKNOWN',
  reference_images: [
    {
      id: 'd2f8a614-9c37-4e51-b0a6-3d7e1c8b520f',
      width: 1024,
      height: 1024,
      featureless: false,
      created_at: '2026-09-21T09:33:00Z',
    },
  ],
};

/**
 * A tile whose Category arrived as `null`.
 *
 * The contract types the field `string | null` because the ERD's column is
 * nullable; the API resolves every Category to the `UNKNOWN` sentinel, so this
 * is the shape the screen must survive rather than one it will meet.
 */
const NULL_CATEGORY: Tile = {
  ...TILE,
  id: '1d6f8b47-3a20-4c95-8e71-4f0c2a9d6b83',
  code: 'RP.CMA.0014DJ.SM.0T',
  category: null,
};

/** A tile whose reference images all went, which the API cannot produce (FR-7). */
const IMAGELESS: Tile = { ...TILE, id: '0a5e7c21-4b93-4d18-8f60-2c9a1e3b7d54', reference_images: [] };

const BROWSE = '/api/admin/tiles?q=';

/** The path one search produces, so a test names the request rather than guessing it. */
function searchPath(query: string): string {
  return `/api/admin/tiles?${new URLSearchParams({ q: query }).toString()}`;
}

interface Reply {
  status: number;
  body?: unknown;
}

/**
 * Replace `fetch` with a queue keyed by the full path, and record every call.
 *
 * `user-list.test.tsx`'s own stub. A local copy rather than a shared helper, as
 * every other suite here keeps theirs — a stub shared across files is a fixture
 * two tests can change under each other.
 */
function stubFetch(replies: Record<string, Reply[]>): { calls: [string, RequestInit][] } {
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
 * Replace `fetch` with one whose replies the test settles by hand.
 *
 * `stubFetch` answers immediately and in order, which cannot express the case
 * the screen's generation counter exists for: two searches open at once, the
 * older answering last.
 */
function stubDeferred(): { settle: (nth: number, reply: Reply) => void; calls: string[] } {
  const settlers: ((reply: Reply) => void)[] = [];
  const calls: string[] = [];

  vi.stubGlobal('fetch', (input: string) => {
    calls.push(input);
    return new Promise<Response>((resolve) => {
      settlers.push((reply) =>
        resolve({
          ok: reply.status >= 200 && reply.status < 300,
          status: reply.status,
          json: () => Promise.resolve(reply.body ?? null),
        } as Response),
      );
    });
  });

  return {
    calls,
    settle: (nth, reply) => {
      const settler = settlers[nth];
      expect(settler, `request ${nth} was never made`).toBeTruthy();
      settler?.(reply);
    },
  };
}

/** The browse answer, reused for every call. */
function stubList(tiles: readonly Tile[]): { calls: [string, RequestInit][] } {
  return stubFetch({ [BROWSE]: [{ status: 200, body: tiles }] });
}

const refusal = (code: string, message: string, status: number): Reply => ({
  status,
  body: { error: { code, message } },
});

function renderScreen(
  props: {
    onBack?: () => void;
    onAddTile?: () => void;
    onBulkUpload?: () => void;
    onEditTile?: (tile: Tile) => void;
    onSearch?: (query: string) => void;
    query?: string;
  } = {},
): {
  onBack: () => void;
  onAddTile: () => void;
  onBulkUpload: () => void;
  onEditTile: (tile: Tile) => void;
  onSearch: (query: string) => void;
  unmount: () => void;
} {
  const onBack = props.onBack ?? ((): void => undefined);
  const onAddTile = props.onAddTile ?? ((): void => undefined);
  const onBulkUpload = props.onBulkUpload ?? ((): void => undefined);
  const onEditTile = props.onEditTile ?? ((): void => undefined);
  const onSearch = props.onSearch ?? ((): void => undefined);
  const { unmount } = render(
    <CatalogueScreen
      onAddTile={onAddTile}
      onBack={onBack}
      onBulkUpload={onBulkUpload}
      onEditTile={onEditTile}
      onSearch={onSearch}
      query={props.query ?? ''}
    />,
  );
  return { onBack, onAddTile, onBulkUpload, onEditTile, onSearch, unmount };
}

/** The screen as a bare element, for the two tests that read its own container. */
function aScreen(): JSX.Element {
  return (
    <CatalogueScreen
      onAddTile={(): void => undefined}
      onBack={(): void => undefined}
      onBulkUpload={(): void => undefined}
      onEditTile={(): void => undefined}
      onSearch={(): void => undefined}
      query=""
    />
  );
}

/** The row a Code is in, so a cell assertion cannot read another row's. */
function rowFor(code: string): HTMLElement {
  const cell = screen.getByText(code);
  const row = cell.closest('tr');
  expect(row, `${code} is not in a table row`).toBeTruthy();
  return row as HTMLElement;
}

/** Type into the search box and submit, the way an Administrator does. */
function searchFor(query: string): void {
  fireEvent.change(screen.getByLabelText(/search by code/i), { target: { value: query } });
  fireEvent.click(screen.getByRole('button', { name: /^search$/i }));
}

// --- The request --------------------------------------------------------------

describe('the request', () => {
  it('browses the whole catalogue on mount, with no query and no body', async () => {
    // EXPERIENCE.md line 35 is "search/**browse**": the screen opens on the
    // full list. A blank `q` is the request, not the absence of one.
    const { calls } = stubList([TILE]);
    renderScreen();

    await screen.findByRole('table');

    const reads = calls.filter(([path]) => path === BROWSE);
    expect(reads).toHaveLength(1);
    expect(reads[0]?.[1].method ?? 'GET').toBe('GET');
    expect(reads[0]?.[1].body).toBeUndefined();
    expect(reads[0]?.[1].credentials).toBe('same-origin');
  });

  it('carries what was typed as q, encoded', async () => {
    const { calls } = stubFetch({
      [BROWSE]: [{ status: 200, body: [TILE, SIBLING] }],
      [searchPath('cma')]: [{ status: 200, body: [TILE] }],
    });
    renderScreen();

    await screen.findByRole('table');
    searchFor('cma');

    await waitFor(() => {
      expect(calls.map(([path]) => path)).toContain(searchPath('cma'));
    });
  });

  it('encodes a query the URL would otherwise eat', async () => {
    // A Code holds `.`, the real catalogue holds free text after the code, and
    // a fragment can hold `%` or `&` — all of which a raw template literal
    // would send as something else. `URLSearchParams` is what stops that, and
    // nothing else in the suite would notice if it went.
    const { calls } = stubFetch({ [BROWSE]: [{ status: 200, body: [TILE] }] });
    renderScreen();

    await screen.findByRole('table');
    searchFor('6LD.MA Quarry & 100%');

    await waitFor(() => {
      expect(calls.map(([path]) => path)).toContain(searchPath('6LD.MA Quarry & 100%'));
    });
  });

  it('sends the query unfolded and untrimmed — the server owns those rules', async () => {
    // `clean_query` has no TypeScript twin: the case is folded at the database
    // and the trimming is the server's. A screen that lowercased or trimmed
    // here would be a second set of answers about what a search is, and would
    // quietly disagree the day either rule changed.
    const { calls } = stubFetch({ [BROWSE]: [{ status: 200, body: [TILE] }] });
    renderScreen();

    await screen.findByRole('table');
    searchFor('  CmA  ');

    await waitFor(() => {
      expect(calls.map(([path]) => path)).toContain(searchPath('  CmA  '));
    });
  });

  it('goes back to the whole catalogue when the box is cleared', async () => {
    const { calls } = stubFetch({
      [BROWSE]: [{ status: 200, body: [TILE, SIBLING] }],
      [searchPath('cma')]: [{ status: 200, body: [TILE] }],
    });
    renderScreen();

    await screen.findByRole('table');
    searchFor('cma');
    await waitFor(() => {
      expect(calls.map(([path]) => path)).toContain(searchPath('cma'));
    });

    searchFor('');

    await waitFor(() => {
      expect(calls.filter(([path]) => path === BROWSE)).toHaveLength(2);
    });
  });
});

// --- The rows -----------------------------------------------------------------

describe('the rows', () => {
  it('paints every tile in the order the API sent, with its size and category', async () => {
    stubList([BARE, TILE, SIBLING]);
    renderScreen();

    await screen.findByRole('table');

    const codes = screen.getAllByRole('row').slice(1).map((row) => {
      const cells = within(row).getAllByRole('cell');
      return cells[1]?.textContent ?? '';
    });
    expect(codes).toEqual(['61M', CODE, SIBLING_CODE]);

    const first = rowFor(CODE);
    expect(within(first).getByText('45X90')).toBeTruthy();
    expect(within(first).getByText('CREMA MARMOL')).toBeTruthy();
  });

  it('lists two tiles of one range as two rows, never merged', async () => {
    // AD-18: the varying numeric segment distinguishes different tiles, not
    // faces of one. Both rows carry the same Size and the same Category, which
    // is exactly the pair a "tidy" list would collapse on — and collapsing it
    // would hide the correct answer half the time.
    stubList([TILE, SIBLING]);
    renderScreen();

    await screen.findByRole('table');

    expect(screen.getAllByRole('row')).toHaveLength(3);
    expect(screen.getByText(CODE)).toBeTruthy();
    expect(screen.getByText(SIBLING_CODE)).toBeTruthy();
    expect(screen.getAllByText('CREMA MARMOL')).toHaveLength(2);
  });

  it('shows a tile filed under the sentinel exactly as it is written', async () => {
    // AD-18: a tile whose Category could not be recovered is in the catalogue
    // under UNKNOWN. Hiding it, or rendering the cell blank, would make a real
    // tile look like a row that failed to load.
    stubList([BARE]);
    renderScreen();

    await screen.findByRole('table');

    expect(within(rowFor('61M')).getByText('UNKNOWN')).toBeTruthy();
  });

  it('writes the sentinel itself when the Category arrived as null', async () => {
    // The contract allows `null`; a bare `{tile.category}` renders it as an
    // empty cell, which is exactly the blank the sentinel exists to prevent —
    // a value that failed to load rather than a tile filed under UNKNOWN
    // (AD-18). Unreachable through the API today, which is precisely why only
    // a test holds it.
    stubList([NULL_CATEGORY]);
    renderScreen();

    await screen.findByRole('table');
    const cells = within(rowFor(NULL_CATEGORY.code)).getAllByRole('cell');

    expect(cells[3]?.textContent).toBe('UNKNOWN');
    expect(cells[3]?.textContent).not.toBe('');
  });

  it('fetches each row’s thumbnail through the proxy route, never a storage URL', async () => {
    // AD-9. Same origin, so the session cookie travels with it and the server
    // re-checks the Administrator role on every one. The `alt` names the Code,
    // because a picture with no name is a picture a screen-reader user cannot
    // match to the row it belongs to.
    stubList([TILE, SIBLING]);
    renderScreen();

    await screen.findByRole('table');

    const image = screen.getByAltText(`Reference image of ${CODE}`);
    expect(image.getAttribute('src')).toBe(`/api/admin/tiles/${TILE.id}/images/${FIRST_IMAGE}`);
    // The **first** image, so the picture beside a Code is the same one every
    // time the screen is painted and the same one Edit tile shows first.
    expect(image.getAttribute('src')).not.toContain(SECOND_IMAGE);
    expect(image.getAttribute('loading')).toBe('lazy');

    for (const forbidden of ['http', 's3', 'signature', 'x-amz', 'presigned']) {
      expect(document.body.innerHTML.toLowerCase()).not.toContain(forbidden);
    }
  });

  it('says so in words when a tile carries no reference image', async () => {
    // Unreachable through the product — the API refuses an edit that would
    // leave a tile without one (FR-7) — and handled anyway, because a row that
    // threw would take the whole catalogue down over one tile.
    stubList([IMAGELESS]);
    renderScreen();

    await screen.findByRole('table');

    expect(within(rowFor(CODE)).getByText(/^no image$/i)).toBeTruthy();
  });

  it('names its columns and offers no more of them', async () => {
    // Reference image, Code, Size, Category, Actions — and nothing else. A
    // low-quality flag column belongs on the tile's own screen (FR-19), and
    // `face_number` is a display hint nothing may key, group or match on.
    stubList([TILE]);
    renderScreen();

    await screen.findByRole('table');

    expect(screen.getAllByRole('columnheader').map((cell) => cell.textContent)).toEqual([
      'Reference image',
      'Code',
      'Size',
      'Category',
      'Actions',
    ]);
  });
});

// --- Searching ----------------------------------------------------------------

describe('a search', () => {
  it('narrows the rows to what came back', async () => {
    stubFetch({
      [BROWSE]: [{ status: 200, body: [TILE, SIBLING, BARE] }],
      [searchPath('cma')]: [{ status: 200, body: [TILE, SIBLING] }],
    });
    renderScreen();

    await screen.findByRole('table');
    expect(screen.getByText('61M')).toBeTruthy();

    searchFor('cma');

    await waitFor(() => {
      expect(screen.queryByText('61M')).toBeNull();
    });
    expect(screen.getByText(CODE)).toBeTruthy();
    expect(screen.getByText(SIBLING_CODE)).toBeTruthy();
  });

  it('sits in a search landmark with a searchbox', async () => {
    // A landmark of its own, so a screen-reader user can jump to the search
    // rather than tabbing a table of a few hundred rows to reach it.
    stubList([TILE]);
    renderScreen();

    await screen.findByRole('table');

    const form = screen.getByRole('search');
    expect(within(form).getByRole('searchbox')).toBeTruthy();
    expect(within(form).getByRole('button', { name: /^search$/i })).toBeTruthy();
  });

  it('is submitted by Enter in the field, not only by the button', async () => {
    const { calls } = stubFetch({ [BROWSE]: [{ status: 200, body: [TILE] }] });
    renderScreen();

    await screen.findByRole('table');
    fireEvent.change(screen.getByLabelText(/search by code/i), { target: { value: 'cma' } });
    fireEvent.submit(screen.getByRole('search'));

    await waitFor(() => {
      expect(calls.map(([path]) => path)).toContain(searchPath('cma'));
    });
  });

  it('says what part of a code means and how to get back to everything', async () => {
    // The hint is bound to the field, so a screen-reader user meets it. It is
    // the one place that says an empty box lists every tile — an Administrator
    // who has narrowed the list has no other way to learn it.
    stubList([TILE]);
    renderScreen();

    await screen.findByRole('table');

    const box = screen.getByLabelText(/search by code/i);
    const hint = box.getAttribute('aria-describedby');
    expect(hint).toBeTruthy();
    expect(document.getElementById(hint ?? '')?.textContent).toMatch(/part of a code/i);
    expect(document.getElementById(hint ?? '')?.textContent).toMatch(/every tile/i);
  });
});

// --- The two empty states -----------------------------------------------------

describe('nothing to show', () => {
  it('reads EXPERIENCE.md’s own sentence when a search matches nothing', async () => {
    // Verbatim, and with no suggested alternatives beside it (EXPERIENCE.md
    // line 91): the match is a substring of the Code, so the only thing a
    // suggestion could do is invent a Code that does not exist.
    stubFetch({
      [BROWSE]: [{ status: 200, body: [TILE] }],
      [searchPath('zzzz')]: [{ status: 200, body: [] }],
    });
    renderScreen();

    await screen.findByRole('table');
    searchFor('zzzz');

    expect(
      await screen.findByText('No tiles match — try a different code.'),
    ).toBeTruthy();
    expect(screen.queryByRole('table')).toBeNull();
    expect(screen.queryByRole('alert')).toBeNull();
    // No suggestion of any kind, and no list of near misses.
    expect(screen.queryByText(/did you mean/i)).toBeNull();
  });

  it('keeps the no-match sentence when the box is cleared without submitting', async () => {
    // The sentence is about the query that *produced* the listing, not about
    // what is in the box now. Branching on the live input flips it to "No tiles
    // yet." the moment somebody clears a fragment that matched nothing — a
    // sentence claiming the catalogue is empty while it is full.
    stubFetch({
      [BROWSE]: [{ status: 200, body: [TILE] }],
      [searchPath('zzzz')]: [{ status: 200, body: [] }],
    });
    renderScreen();

    await screen.findByRole('table');
    searchFor('zzzz');
    await screen.findByText('No tiles match — try a different code.');

    // Cleared, and **not** submitted: nothing has been asked of the server, so
    // nothing about the answer on screen has changed.
    fireEvent.change(screen.getByLabelText(/search by code/i), { target: { value: '' } });

    expect(screen.getByText('No tiles match — try a different code.')).toBeTruthy();
    expect(screen.queryByText(/^no tiles yet\.$/i)).toBeNull();
  });

  it('keeps the empty-catalogue sentence when a fragment is typed but not submitted', async () => {
    // The other direction of the same rule.
    stubList([]);
    renderScreen();

    await screen.findByText(/^no tiles yet\.$/i);

    fireEvent.change(screen.getByLabelText(/search by code/i), { target: { value: 'zzzz' } });

    expect(screen.getByText(/^no tiles yet\.$/i)).toBeTruthy();
    expect(screen.queryByText(/try a different code/i)).toBeNull();
  });

  it('reads the user list’s register when the catalogue itself is empty', async () => {
    // A different fact from the one above, and a different sentence. Telling an
    // Administrator who has just installed the product to try a different code
    // would send them looking for a typo they did not make.
    stubList([]);
    renderScreen();

    expect(await screen.findByText(/^no tiles yet\.$/i)).toBeTruthy();
    expect(screen.queryByText(/try a different code/i)).toBeNull();
    expect(screen.queryByRole('table')).toBeNull();
  });
});

// --- What the live region says ------------------------------------------------

describe('the live region', () => {
  it('stays in the document and carries the count once an answer lands', async () => {
    // A region that is unmounted when the request answers announces the *wait*
    // and never the outcome: a screen-reader user who submits a search hears
    // "Loading tiles…", then silence. The table's rows are there to be read one
    // by one; "did that narrow anything" is the question the submit asked, and
    // the count is the only place it is answered.
    stubList([TILE, SIBLING]);
    renderScreen();

    await screen.findByRole('table');

    expect(screen.getByRole('status').textContent).toBe('2 tiles listed.');
  });

  it('says one tile in the singular', async () => {
    stubList([TILE]);
    renderScreen();

    await screen.findByRole('table');

    expect(screen.getByRole('status').textContent).toBe('1 tile listed.');
  });

  it('carries the no-match sentence itself, so it is announced as well as seen', async () => {
    // The empty sentence *is* this element rather than a second one beside it,
    // which is what keeps the screen to one live region and the copy to one
    // place.
    stubFetch({
      [BROWSE]: [{ status: 200, body: [TILE] }],
      [searchPath('zzzz')]: [{ status: 200, body: [] }],
    });
    renderScreen();

    await screen.findByRole('table');
    searchFor('zzzz');

    await waitFor(() => {
      expect(screen.getByRole('status').textContent).toBe(
        'No tiles match — try a different code.',
      );
    });
  });

  it('says nothing at all when the request failed', async () => {
    // The failure is spoken by its own `role="alert"`, which interrupts
    // assertively. A second live region repeating it would speak twice, and
    // leaving the previous count standing under the alert would be worse: a
    // sentence about rows that are no longer on screen.
    stubFetch({ [BROWSE]: [refusal('internal_error', 'Something went wrong.', 500)] });
    renderScreen();

    await screen.findByRole('alert');

    expect(screen.getByRole('status').textContent).toBe('');
  });
});

// --- Failure ------------------------------------------------------------------

describe('a failure', () => {
  it('renders the server’s own sentence in one alert, with no table beside it', async () => {
    stubFetch({
      [BROWSE]: [refusal('administrator_required', 'Administrator access is required.', 403)],
    });
    renderScreen();

    const alert = await screen.findByRole('alert');

    expect(alert.textContent).toBe('Administrator access is required.');
    expect(screen.getAllByRole('alert')).toHaveLength(1);
    expect(screen.queryByRole('table')).toBeNull();
  });

  it('renders a refused query in the server’s words rather than a rule of its own', async () => {
    // `invalid_query`. The screen runs no length or character check, so this
    // sentence is the only thing an Administrator who pasted a paragraph sees —
    // and it has to be the server's, which names the bound and the way through.
    stubFetch({
      [BROWSE]: [{ status: 200, body: [TILE] }],
      [searchPath('x'.repeat(201))]: [
        refusal(
          'invalid_query',
          'A search must be at most 200 characters. Search for part of a code, or clear the box to browse the whole catalogue.',
          422,
        ),
      ],
    });
    renderScreen();

    await screen.findByRole('table');
    searchFor('x'.repeat(201));

    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toMatch(/at most 200 characters/);
    expect(alert.textContent).toMatch(/part of a code/);
  });

  it('renders nothing from a body it could not understand', async () => {
    // `asTiles` refuses an array with one malformed element, so a
    // partially-understood catalogue is never rendered as the catalogue: a row
    // this screen could not parse is a tile nobody would know to look for.
    stubFetch({ [BROWSE]: [{ status: 200, body: [TILE, { code: 'SOMETHING' }] }] });
    renderScreen();

    await screen.findByRole('alert');

    expect(screen.queryByRole('table')).toBeNull();
    expect(screen.queryByText(CODE)).toBeNull();
  });

  it('refuses a body carrying a key the contract does not have', async () => {
    // How a storage reference (AD-9) or a similarity value (AD-20) would
    // announce itself: `isTile` rejects any extra key rather than ignoring it.
    stubFetch({
      [BROWSE]: [{ status: 200, body: [{ ...TILE, similarity: 0.918 }] }],
    });
    renderScreen();

    await screen.findByRole('alert');

    expect(screen.queryByRole('table')).toBeNull();
  });

  it('words a failure that is not an ApiRequestError itself', async () => {
    vi.stubGlobal('fetch', () => Promise.resolve(null));
    renderScreen();

    const alert = await screen.findByRole('alert');

    expect(alert.textContent).toMatch(/could not be loaded/i);
  });

  it('refetches on Try again and replaces the alert with the table', async () => {
    const { calls } = stubFetch({
      [BROWSE]: [
        refusal('internal_error', 'Something went wrong.', 500),
        { status: 200, body: [TILE] },
      ],
    });
    renderScreen();

    await screen.findByRole('alert');

    fireEvent.click(screen.getByRole('button', { name: /^try again$/i }));

    expect(await screen.findByRole('table')).toBeTruthy();
    expect(screen.queryByRole('alert')).toBeNull();
    await waitFor(() => {
      expect(calls.filter(([path]) => path === BROWSE)).toHaveLength(2);
    });
  });

  it('retries the search that failed, not the whole catalogue', async () => {
    // Try again repeats what was asked for. Refetching everything instead
    // would silently widen the list the Administrator had narrowed, which reads
    // as a search box that forgot what was in it.
    const { calls } = stubFetch({
      [BROWSE]: [{ status: 200, body: [TILE, SIBLING] }],
      [searchPath('cma')]: [
        refusal('internal_error', 'Something went wrong.', 500),
        { status: 200, body: [TILE] },
      ],
    });
    renderScreen();

    await screen.findByRole('table');
    searchFor('cma');
    await screen.findByRole('alert');

    fireEvent.click(screen.getByRole('button', { name: /^try again$/i }));

    await screen.findByRole('table');
    await waitFor(() => {
      expect(calls.filter(([path]) => path === searchPath('cma'))).toHaveLength(2);
    });
  });

  it('sends one request for two presses of Try again', async () => {
    // Two clicks in one tick both read the state from before the first
    // `setListing`, and the button is still in the document for the second —
    // so without a synchronous guard the second sends a duplicate request
    // against a failure that is already being retried. The guard sits *above*
    // the focus call, so the press it declines does not also pull focus off
    // the control that was pressed — which is the next test's claim, made
    // where focus is actually read; this one counts requests and nothing else.
    const { calls } = stubFetch({
      [BROWSE]: [
        refusal('internal_error', 'Something went wrong.', 500),
        { status: 200, body: [TILE] },
      ],
    });
    renderScreen();

    await screen.findByRole('alert');
    const control = screen.getByRole('button', { name: /^try again$/i });

    fireEvent.click(control);
    fireEvent.click(control);

    await screen.findByRole('table');
    // The mount browse plus exactly one retry.
    expect(calls.filter(([path]) => path === BROWSE)).toHaveLength(2);
  });

  it('leaves the reader on the screen when Try again removes itself', async () => {
    // The press unmounts the control that was pressed, and a browser answers
    // that by dropping focus to `<body>` — several tabs above the screen the
    // Administrator just acted on. jsdom moves focus for real, so this is
    // observable.
    stubFetch({
      [BROWSE]: [
        refusal('internal_error', 'Something went wrong.', 500),
        { status: 200, body: [TILE] },
      ],
    });
    renderScreen();

    await screen.findByRole('alert');

    fireEvent.click(screen.getByRole('button', { name: /^try again$/i }));

    expect(document.activeElement).toBe(screen.getByRole('heading', { name: 'Catalogue' }));
    expect(document.activeElement).not.toBe(document.body);
  });

  it('offers Try again only while there is something to retry', async () => {
    stubList([TILE]);
    renderScreen();

    await screen.findByRole('table');

    expect(screen.queryByRole('button', { name: /^try again$/i })).toBeNull();
  });
});

// --- Two requests open at once ------------------------------------------------

describe('a stale answer', () => {
  it('never overwrites a newer one', async () => {
    // StrictMode mounts, tears down and mounts again, so two reads are open at
    // once and the *first* is the stale one. Settled last, it must not replace
    // what the second returned — the whole job of the screen's generation
    // counter. Delete the counter and this renders the previous search over the
    // current one.
    const { settle, calls } = stubDeferred();
    render(aScreen(), { wrapper: StrictMode });

    // Asserted first, so the test fails loudly rather than passing vacuously if
    // the effect ever stops running twice.
    await waitFor(() => {
      expect(calls).toHaveLength(2);
    });

    settle(1, { status: 200, body: [TILE] });
    await screen.findByText(CODE);

    settle(0, { status: 200, body: [BARE] });

    await waitFor(() => {
      expect(screen.getByText(CODE)).toBeTruthy();
    });
    expect(screen.queryByText('61M')).toBeNull();
  });

  it('is superseded rather than blocking the newer search', async () => {
    // A submit while a request is open is a *newer question*, not a duplicate
    // of the one being asked. Swallowed, it leaves the box saying one thing and
    // the table another with nothing on screen to explain why pressing Enter
    // did nothing — so it is sent, and `generation` retires the older answer.
    const { settle, calls } = stubDeferred();
    renderScreen();

    await waitFor(() => {
      expect(calls).toHaveLength(1);
    });

    // The mount browse is still open when this is submitted — by the button,
    // which is not disabled while a request is in flight precisely so that it
    // obeys the same rule as pressing Enter in the field.
    searchFor('cma');
    await waitFor(() => {
      expect(calls).toHaveLength(2);
    });
    expect(calls[1]).toBe(searchPath('cma'));

    // And Enter in the field, the path a `disabled` button could never have
    // guarded, does the same thing rather than vanishing.
    fireEvent.change(screen.getByLabelText(/search by code/i), { target: { value: 'astoria' } });
    fireEvent.submit(screen.getByRole('search'));
    await waitFor(() => {
      expect(calls).toHaveLength(3);
    });
    expect(calls[2]).toBe(searchPath('astoria'));

    // The newest answers first, then the two it superseded.
    settle(2, { status: 200, body: [TILE] });
    await screen.findByText(CODE);

    settle(1, { status: 200, body: [SIBLING] });
    settle(0, { status: 200, body: [TILE, SIBLING, BARE] });

    await waitFor(() => {
      expect(screen.getByText(CODE)).toBeTruthy();
    });
    expect(screen.queryByText('61M')).toBeNull();
    expect(screen.queryByText(SIBLING_CODE)).toBeNull();
    expect(screen.getByRole('status').textContent).toBe('1 tile listed.');
  });

  it('is dropped rather than written to a screen that has gone', async () => {
    const complaints = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    const { settle } = stubDeferred();
    const { unmount } = renderScreen();

    unmount();
    settle(0, { status: 200, body: [TILE] });
    await waitFor(() => {
      expect(complaints).not.toHaveBeenCalled();
    });

    expect(screen.queryByText(CODE)).toBeNull();
    complaints.mockRestore();
  });
});

// --- The controls -------------------------------------------------------------

describe('the controls', () => {
  it('hands Add tile, Bulk upload and Back straight to their props', async () => {
    const onAddTile = vi.fn();
    const onBulkUpload = vi.fn();
    const onBack = vi.fn();
    stubList([TILE]);
    renderScreen({ onAddTile, onBulkUpload, onBack });

    await screen.findByRole('table');

    fireEvent.click(screen.getByRole('button', { name: /add tile/i }));
    fireEvent.click(screen.getByRole('button', { name: /^bulk upload$/i }));
    fireEvent.click(screen.getByRole('button', { name: /^back$/i }));

    expect(onAddTile).toHaveBeenCalledTimes(1);
    expect(onBulkUpload).toHaveBeenCalledTimes(1);
    expect(onBack).toHaveBeenCalledTimes(1);
  });

  it('opens the tile from the row’s own Edit control, named for its code', async () => {
    // EXPERIENCE.md line 71: a row-end action is labelled, never a bare icon.
    // The *accessible* name carries the Code, because "Edit" read three times
    // out of context says nothing about which tile is about to change.
    const onEditTile = vi.fn();
    stubList([TILE, SIBLING]);
    renderScreen({ onEditTile });

    await screen.findByRole('table');
    const control = within(rowFor(SIBLING_CODE)).getByRole('button', {
      name: `Edit ${SIBLING_CODE}`,
    });
    expect(control.tagName).toBe('BUTTON');
    expect(control.textContent).toBe('Edit');

    fireEvent.click(control);

    // The whole `Tile`, not an id: the edit screen is seeded from what this
    // list already holds, which is why the product serves no
    // `GET /admin/tiles/{tile_id}`.
    expect(onEditTile).toHaveBeenCalledTimes(1);
    expect(onEditTile).toHaveBeenCalledWith(SIBLING);
  });

  it('opens the tile from a click on the row itself', async () => {
    // EXPERIENCE.md line 71's row click, as a mouse convenience. Asserted by
    // clicking, not by reading an attribute: React attaches handlers through
    // its own synthetic event system and emits no `onclick` attribute, so an
    // attribute check could never fail.
    const onEditTile = vi.fn();
    stubList([TILE]);
    renderScreen({ onEditTile });

    await screen.findByRole('table');

    fireEvent.click(rowFor(CODE));

    expect(onEditTile).toHaveBeenCalledTimes(1);
    expect(onEditTile).toHaveBeenCalledWith(TILE);
  });

  it('stands down when the click is the end of a drag-selection', async () => {
    // An Administrator highlighting a Code to copy it releases the mouse over
    // the row, and that click lands on the row's own handler: without this
    // guard they are navigated into Edit Tile and lose both the selection and
    // the list. `getSelection` is stubbed rather than driven, because jsdom
    // performs no layout and a real drag cannot produce a range here.
    const onEditTile = vi.fn();
    stubList([TILE]);
    renderScreen({ onEditTile });

    await screen.findByRole('table');

    const dragged = vi
      .spyOn(window, 'getSelection')
      .mockReturnValue({ isCollapsed: false } as unknown as Selection);
    fireEvent.click(rowFor(CODE));
    expect(onEditTile).not.toHaveBeenCalled();

    // And the row-end control still works while text is selected — it is the
    // deliberate path, not the convenience, so the guard must not reach it.
    fireEvent.click(screen.getByRole('button', { name: `Edit ${CODE}` }));
    expect(onEditTile).toHaveBeenCalledTimes(1);

    // A collapsed selection is a plain caret, which is what an ordinary click
    // leaves behind — so the convenience is back the moment nothing is
    // selected.
    dragged.mockReturnValue({ isCollapsed: true } as unknown as Selection);
    fireEvent.click(rowFor(CODE));
    expect(onEditTile).toHaveBeenCalledTimes(2);

    dragged.mockRestore();
  });

  it('opens it once, not twice, when the Edit control inside the row is used', async () => {
    // The control stops the event reaching the row. Without that the row's own
    // handler fires second and the same tile is opened twice — harmless today
    // and not tomorrow, since the callback is what sets the app's section.
    const onEditTile = vi.fn();
    stubList([TILE]);
    renderScreen({ onEditTile });

    await screen.findByRole('table');

    fireEvent.click(screen.getByRole('button', { name: `Edit ${CODE}` }));

    expect(onEditTile).toHaveBeenCalledTimes(1);
  });

  it('claims no role on the row and takes no focus there', async () => {
    // The row is a mouse convenience and never the keyboard path — the
    // labelled control at the row end is. A `<tr>` announcing itself as a
    // button it cannot be focused as would be worse than no row click at all.
    stubList([TILE]);
    renderScreen();

    await screen.findByRole('table');
    const row = rowFor(CODE);

    expect(row.getAttribute('tabindex')).toBeNull();
    expect(row.getAttribute('role')).toBeNull();
    expect(row.className).toBe(styles.row);
  });

  it('has exactly the controls it is meant to have', async () => {
    // Asserted over the rendered control names, so a removal verb, a sort
    // control, a row-end menu, a bulk-select column or a Size/Category picker
    // added later fails here. Removal in particular is deliberately absent:
    // it lives on Edit tile behind a confirmation that names the tile, because
    // a destructive verb on a dense row is one mis-click from a catalogue entry
    // nobody can restore.
    stubList([TILE, SIBLING]);
    renderScreen();

    await screen.findByRole('table');

    expect(screen.getAllByRole('button').map((control) => control.textContent)).toEqual([
      '+ Add Tile',
      'Bulk upload',
      'Back',
      'Search',
      'Edit',
      'Edit',
    ]);
    for (const verb of [/remove/i, /delete/i, /sort/i, /next/i, /previous/i, /filter/i]) {
      expect(screen.queryByRole('button', { name: verb })).toBeNull();
    }
    expect(screen.queryByRole('link')).toBeNull();
    expect(screen.queryByRole('menuitem')).toBeNull();
    expect(screen.queryByRole('checkbox')).toBeNull();
    expect(screen.queryByRole('dialog')).toBeNull();
    // One text control, and it is the search box. A Size or Category picker
    // would be a `combobox` or a second field, and neither may exist: a
    // `size + category` filter hides the very row somebody came here to find.
    expect(screen.queryByRole('combobox')).toBeNull();
    expect(screen.getAllByRole('searchbox')).toHaveLength(1);
    expect(screen.queryByRole('textbox')).toBeNull();
  });

  it('announces the wait on a status region while a search is open', async () => {
    stubDeferred();
    renderScreen();

    const status = await screen.findByRole('status');

    expect(status.textContent).toMatch(/loading tiles/i);
  });

  it('sits the table in a labelled region a keyboard can scroll', async () => {
    // One `<table>` at every width, so every cell keeps its column-header
    // association; the container takes the overflow and takes focus, so the
    // last column is reachable without a mouse and the page never scrolls
    // sideways.
    stubList([TILE]);
    renderScreen();

    await screen.findByRole('table');
    const region = screen.getByRole('region');

    expect(region.getAttribute('tabindex')).toBe('0');
    expect(region.getAttribute('aria-labelledby')).toBe(
      screen.getByRole('heading', { name: /^catalogue$/i }).id,
    );
  });

  it('renders no main landmark of its own', () => {
    // `AppShell` provides the one `<main>` and the focus target the gate moves
    // focus to on a screen swap. A second one here would be two main landmarks
    // on every render of this surface.
    stubList([TILE]);
    const { container } = render(aScreen());

    expect(container.querySelector('main')).toBeNull();
  });

  it('uses the domain’s own words and none of the retired ones', async () => {
    // AD-18 retires `Product` and `Face`. The rendered text is where they would
    // come back first, and a label is what an Administrator learns the
    // vocabulary from — a catalogue listing "products" would be the clearest
    // possible statement of the identity model AD-18 rejects.
    stubList([TILE]);
    const { container } = render(aScreen());

    await screen.findByRole('table');
    const text = container.textContent ?? '';

    expect(text).toMatch(/Catalogue/);
    expect(text).toMatch(/Code/);
    expect(text).toMatch(/Size/);
    expect(text).toMatch(/Category/);
    expect(/\bproducts?\b/i.test(text)).toBe(false);
    expect(/\bfaces?\b/i.test(text)).toBe(false);
    // AD-20: no similarity value, in any form, and no word derived from one.
    for (const banned of [/similarity/i, /confidence/i, /\bscore\b/i, /best match/i]) {
      expect(banned.test(text)).toBe(false);
    }
  });
});

// --- The door on the home panel -----------------------------------------------

describe('the door on the home panel', () => {
  function stubSession(user: User | null, tiles: readonly Tile[] = [TILE]): void {
    stubFetch({
      '/api/auth/session': [
        user === null
          ? refusal('unauthorized', 'Not signed in.', 401)
          : { status: 200, body: user },
      ],
      [BROWSE]: [{ status: 200, body: tiles }],
    });
  }

  it('is offered to an Administrator and opens the screen', async () => {
    stubSession(ADMIN);
    render(<App />);

    fireEvent.click(await screen.findByRole('button', { name: /^catalogue$/i }));

    expect(await screen.findByRole('heading', { name: /^catalogue$/i })).toBeTruthy();
  });

  it('is not offered to a Staff user at all', async () => {
    // EXPERIENCE.md line 18: the nav is role-conditional, not a menu with
    // disabled items. The server refuses them regardless (AGENTS.md Policy);
    // this is the courtesy on top of the control.
    stubSession(STAFF);
    render(<App />);

    await screen.findByText(/signed in as kasun perera/i);

    expect(screen.queryByRole('button', { name: /^catalogue$/i })).toBeNull();
  });

  it('is gone, with the surface and the search, after a mid-session demotion', async () => {
    // The redirect EXPERIENCE.md line 95 asks for, expressed as a pure function
    // of role: `reachableBy` is what puts `'catalogue'` behind `admin`, and the
    // gate's role reconciler is what clears a section the new role cannot
    // reach. Neither is exercised by the door-presence tests above — those are
    // satisfied by the JSX condition around the panel's buttons alone — so
    // without this the whole role-conditional half of the new section could be
    // deleted and ship green, leaving a demoted Administrator looking at the
    // catalogue table.
    //
    // The search goes with it, and the second revalidation is what proves it:
    // a promotion inside one shift is two clicks since Story 1.10, and a
    // Catalogue that reopened narrowed by a search made under a role that no
    // longer applied would be handing the fragment straight back.
    const { calls } = stubFetch({
      '/api/auth/session': [
        { status: 200, body: ADMIN },
        { status: 200, body: { ...ADMIN, role: 'staff' } },
        { status: 200, body: ADMIN },
      ],
      [BROWSE]: [{ status: 200, body: [TILE] }, { status: 200, body: [TILE] }],
      [searchPath('cma')]: [{ status: 200, body: [TILE] }],
    });
    render(<App />);

    fireEvent.click(await screen.findByRole('button', { name: /^catalogue$/i }));
    await screen.findByRole('table');

    fireEvent.change(screen.getByLabelText(/search by code/i), { target: { value: 'cma' } });
    fireEvent.click(screen.getByRole('button', { name: /^search$/i }));
    await waitFor(() => {
      expect(calls.some(([path]) => path === searchPath('cma'))).toBe(true);
    });

    // The visibility revalidation `SessionProvider` registers is what re-reads
    // the role (AD-3); this is that request arriving with the new one.
    document.dispatchEvent(new Event('visibilitychange'));

    expect(await screen.findByText(/signed in as/i)).toBeTruthy();
    expect(screen.queryByRole('heading', { name: /^catalogue$/i })).toBeNull();
    expect(screen.queryByRole('button', { name: /^catalogue$/i })).toBeNull();
    // And nothing of the catalogue survives the swap — not a stale table, not
    // a row, not a Code.
    expect(screen.queryByRole('table')).toBeNull();
    expect(screen.queryByText(CODE)).toBeNull();

    // Promoted back, the Catalogue opens on the full list rather than on the
    // search the demotion interrupted.
    document.dispatchEvent(new Event('visibilitychange'));
    fireEvent.click(await screen.findByRole('button', { name: /^catalogue$/i }));
    await screen.findByRole('table');

    expect(screen.getByLabelText(/search by code/i)).toHaveProperty('value', '');
    expect(calls.filter(([path]) => path === searchPath('cma'))).toHaveLength(1);
    expect(calls.filter(([path]) => path === BROWSE)).toHaveLength(2);
  });

  it('replaced the three tile doors rather than joining them', async () => {
    // Story 2.5's own change to this panel. Add tile, Edit tile and Bulk upload
    // stood here while there was nothing to reach them from; leaving them
    // beside a fourth Catalogue door would ship two ways to reach one screen
    // and a panel that contradicts EXPERIENCE.md lines 36-37.
    stubSession(ADMIN);
    render(<App />);

    await screen.findByText(/signed in as nadeesha silva/i);

    expect(screen.getByRole('button', { name: /^catalogue$/i })).toBeTruthy();
    for (const gone of [/^add tile$/i, /^edit tile$/i, /^bulk upload$/i]) {
      expect(screen.queryByRole('button', { name: gone })).toBeNull();
    }
  });

  it('returns to the home panel from Back', async () => {
    stubSession(ADMIN);
    render(<App />);

    fireEvent.click(await screen.findByRole('button', { name: /^catalogue$/i }));
    await screen.findByRole('heading', { name: /^catalogue$/i });

    fireEvent.click(screen.getByRole('button', { name: /^back$/i }));

    expect(await screen.findByText(/signed in as nadeesha silva/i)).toBeTruthy();
  });

  it('opens Add tile from the Catalogue, and Back comes back to it', async () => {
    stubSession(ADMIN);
    render(<App />);

    fireEvent.click(await screen.findByRole('button', { name: /^catalogue$/i }));
    await screen.findByRole('heading', { name: /^catalogue$/i });

    fireEvent.click(screen.getByRole('button', { name: /add tile/i }));
    await screen.findByRole('heading', { name: /^add tile$/i });

    fireEvent.click(screen.getByRole('button', { name: /^back$/i }));

    expect(await screen.findByRole('heading', { name: /^catalogue$/i })).toBeTruthy();
  });

  it('opens Bulk upload from the Catalogue, and Back comes back to it', async () => {
    stubSession(ADMIN);
    render(<App />);

    fireEvent.click(await screen.findByRole('button', { name: /^catalogue$/i }));
    await screen.findByRole('heading', { name: /^catalogue$/i });

    fireEvent.click(screen.getByRole('button', { name: /^bulk upload$/i }));
    await screen.findByRole('heading', { name: /^bulk upload$/i });

    fireEvent.click(screen.getByRole('button', { name: /^back$/i }));

    expect(await screen.findByRole('heading', { name: /^catalogue$/i })).toBeTruthy();
  });

  it('opens Edit tile on the row’s own tile, with no code to type', async () => {
    // The whole point of handing the screen a `Tile`: a row opens straight onto
    // the edit stage, pre-filled, with **no lookup request made** and nothing
    // for the Administrator to transcribe.
    //
    // The Code lookup field is still in the document, and deliberately: it is
    // the door for a tile nobody handed over, its suite stays green, and
    // weakening it was out of scope for this story. What must not happen is a
    // request — a screen that adopted the prop through an effect, or re-fetched
    // by Code to "confirm" it, would paint the empty stage for a frame and ask
    // the server for something it was already holding.
    const { calls } = stubFetch({
      '/api/auth/session': [{ status: 200, body: ADMIN }],
      [BROWSE]: [{ status: 200, body: [TILE] }],
    });
    render(<App />);

    fireEvent.click(await screen.findByRole('button', { name: /^catalogue$/i }));
    await screen.findByRole('table');

    fireEvent.click(screen.getByRole('button', { name: `Edit ${CODE}` }));

    await screen.findByRole('heading', { name: /^edit tile$/i });
    expect((await screen.findByLabelText(/^code$/i)).getAttribute('value')).toBe(CODE);
    expect(screen.getByLabelText(/^size$/i).getAttribute('value')).toBe(TILE.size);
    expect(screen.getByLabelText(/^category$/i).getAttribute('value')).toBe(TILE.category);
    // The lookup box is there and empty — nothing was typed into it, because
    // nothing had to be.
    expect(screen.getByLabelText(/find a tile by code/i).getAttribute('value')).toBe('');
    expect(calls.map(([path]) => path).some((path) => path.includes('/lookup'))).toBe(false);
  });

  it('keeps the search in place across a trip to Edit tile and back', async () => {
    // The acceptance clause: `Back` returns to the Catalogue **with the search
    // still in place**. `App` swaps the surface rather than stacking one, so a
    // query held only inside `CatalogueScreen` is gone by the time Back brings
    // it home — the box would be empty and the whole catalogue re-browsed.
    //
    // **Two different bodies are queued for the search URL**, so a cached
    // render cannot pass this: the rows on screen after Back are the second
    // reply, which proves the preserved query was re-requested rather than
    // re-displayed. The refetch is the point — a tile added or renamed one
    // surface away has to show up — and what it refetches is the search.
    const { calls } = stubFetch({
      '/api/auth/session': [{ status: 200, body: ADMIN }],
      [BROWSE]: [{ status: 200, body: [TILE, SIBLING, BARE] }],
      [searchPath('cma')]: [
        { status: 200, body: [TILE] },
        { status: 200, body: [SIBLING] },
      ],
    });
    render(<App />);

    fireEvent.click(await screen.findByRole('button', { name: /^catalogue$/i }));
    await screen.findByRole('table');

    searchFor('cma');
    await waitFor(() => {
      expect(screen.queryByText('61M')).toBeNull();
    });

    fireEvent.click(screen.getByRole('button', { name: `Edit ${CODE}` }));
    await screen.findByRole('heading', { name: /^edit tile$/i });

    fireEvent.click(screen.getByRole('button', { name: /^back$/i }));
    await screen.findByRole('table');

    // The box still holds it.
    expect(screen.getByLabelText(/search by code/i).getAttribute('value')).toBe('cma');
    // The rows are still narrowed, and they are the *second* answer.
    expect(screen.getByText(SIBLING_CODE)).toBeTruthy();
    expect(screen.queryByText('61M')).toBeNull();
    // The request after Back carried the query rather than browsing.
    expect(calls.filter(([path]) => path === searchPath('cma'))).toHaveLength(2);
    expect(calls.filter(([path]) => path === BROWSE)).toHaveLength(1);
  });

  it('keeps the search in place across Add tile and Bulk upload too', async () => {
    // The same clause for the other two surfaces the Catalogue reaches: all
    // three unmount it, so all three would lose the query.
    const { calls } = stubFetch({
      '/api/auth/session': [{ status: 200, body: ADMIN }],
      [BROWSE]: [{ status: 200, body: [TILE, BARE] }],
      [searchPath('cma')]: [{ status: 200, body: [TILE] }],
    });
    render(<App />);

    fireEvent.click(await screen.findByRole('button', { name: /^catalogue$/i }));
    await screen.findByRole('table');
    searchFor('cma');
    await waitFor(() => {
      expect(screen.queryByText('61M')).toBeNull();
    });

    // Written out rather than looped: these two round trips are strictly
    // sequential — the second starts from the screen the first returned to —
    // so a loop would be a loop of awaits that cannot be parallelised.
    fireEvent.click(screen.getByRole('button', { name: /add tile/i }));
    await screen.findByRole('heading', { name: /^add tile$/i });
    fireEvent.click(screen.getByRole('button', { name: /^back$/i }));
    await screen.findByRole('table');

    expect(screen.getByLabelText(/search by code/i).getAttribute('value')).toBe('cma');
    expect(screen.queryByText('61M')).toBeNull();

    fireEvent.click(screen.getByRole('button', { name: /^bulk upload$/i }));
    await screen.findByRole('heading', { name: /^bulk upload$/i });
    fireEvent.click(screen.getByRole('button', { name: /^back$/i }));
    await screen.findByRole('table');

    expect(screen.getByLabelText(/search by code/i).getAttribute('value')).toBe('cma');
    expect(screen.queryByText('61M')).toBeNull();

    // Three requests for the search — the submit and one per return — and the
    // single mount browse from before it was typed.
    expect(calls.filter(([path]) => path === searchPath('cma'))).toHaveLength(3);
    expect(calls.filter(([path]) => path === BROWSE)).toHaveLength(1);
  });

  it('forgets the search when the session ends', async () => {
    // A view preference survives a move between surfaces; it does not survive a
    // sign-out. On a shared shop-floor handset even a fragment of a Code is
    // catalogue data the next person did not type.
    let asked = 0;
    vi.stubGlobal('fetch', (input: string, init: RequestInit = {}) => {
      const key = `${init.method ?? 'GET'} ${input}`;
      if (key === 'GET /api/auth/session') {
        asked += 1;
        return Promise.resolve({
          ok: asked === 1,
          status: asked === 1 ? 200 : 401,
          json: () =>
            Promise.resolve(
              asked === 1 ? ADMIN : { error: { code: 'unauthorized', message: 'Not signed in.' } },
            ),
        } as unknown as Response);
      }
      if (key === 'POST /api/auth/logout') {
        return Promise.resolve({ ok: true, status: 204, json: () => Promise.resolve(null) } as unknown as Response);
      }
      return Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve([TILE]),
      } as unknown as Response);
    });
    render(<App />);

    fireEvent.click(await screen.findByRole('button', { name: /^catalogue$/i }));
    await screen.findByRole('table');
    searchFor('cma');
    await waitFor(() => {
      expect(screen.getByLabelText(/search by code/i).getAttribute('value')).toBe('cma');
    });

    fireEvent.click(screen.getByRole('button', { name: /^sign out$/i }));

    await screen.findByLabelText(/password/i);
    expect(screen.queryByLabelText(/search by code/i)).toBeNull();
  });

  it('lands back on the Catalogue when a row’s tile is removed', async () => {
    // The end-to-end half of the removal fix. A tile opened from a row and then
    // removed leaves nothing for Edit tile to be about, so the app returns to
    // the Catalogue — whose refetch on mount is what shows the row gone. The
    // browse is queued twice, so the empty list after the removal is a fresh
    // answer rather than a cached render.
    const { calls } = stubFetch({
      '/api/auth/session': [{ status: 200, body: ADMIN }],
      [BROWSE]: [
        { status: 200, body: [TILE] },
        { status: 200, body: [] },
      ],
      [`/api/admin/tiles/${TILE.id}`]: [{ status: 204 }],
    });
    render(<App />);

    fireEvent.click(await screen.findByRole('button', { name: /^catalogue$/i }));
    await screen.findByRole('table');
    fireEvent.click(screen.getByRole('button', { name: `Edit ${CODE}` }));
    await screen.findByRole('heading', { name: /^edit tile$/i });

    // The row-end control on the form, not the one inside the sheet it opens.
    const remove = screen
      .getAllByRole('button', { name: /^remove tile$/i })
      .find((control) => control.closest('[role="dialog"]') === null);
    fireEvent.click(remove as HTMLElement);
    fireEvent.click(
      within(screen.getByRole('dialog')).getByRole('button', { name: /^remove tile$/i }),
    );

    // Back on the Catalogue, and the tile is gone from it — not a code-entry
    // stage for a Code that no longer names anything.
    expect(await screen.findByText(/^no tiles yet\.$/i)).toBeTruthy();
    expect(screen.getByRole('heading', { name: /^catalogue$/i })).toBeTruthy();
    expect(screen.queryByLabelText(/find a tile by code/i)).toBeNull();
    expect(calls.filter(([path]) => path === BROWSE)).toHaveLength(2);
  });

  it('returns from Edit tile to the Catalogue', async () => {
    stubSession(ADMIN);
    render(<App />);

    fireEvent.click(await screen.findByRole('button', { name: /^catalogue$/i }));
    await screen.findByRole('table');
    fireEvent.click(screen.getByRole('button', { name: `Edit ${CODE}` }));
    await screen.findByRole('heading', { name: /^edit tile$/i });

    fireEvent.click(screen.getByRole('button', { name: /^back$/i }));

    expect(await screen.findByRole('heading', { name: /^catalogue$/i })).toBeTruthy();
  });
});
