/**
 * History — a caller's own past Scans (Story 3.5, FR-8).
 *
 * Two halves, `audit-log.test.tsx`'s own split. The screen's own behaviour
 * runs against a stubbed `fetch` with `HistoryScreen` rendered directly,
 * because it calls `apiRequest` itself rather than going through
 * `SessionProvider` — `AuditLogScreen`/`CatalogueScreen`'s own precedent for
 * a plain list read. Whether the app *reaches* the screen at all, and that it
 * is reachable by both roles, runs through `App`, because the section state
 * and the home-panel door live in the gate.
 *
 * Three assertions here are the ones nothing else in the suite can make:
 * that the "No scans yet." empty state is genuinely reachable (unlike the
 * audit log's own empty state, a fresh account really has scanned nothing);
 * that the door is offered to Staff as well as to an Administrator, unlike
 * every other door on this panel; and that tapping a Candidate card opens the
 * same tap-to-fullscreen viewer `scan.test.tsx` proves on Results.
 */
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { StrictMode } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import App from '../App';
import { HistoryScreen } from '../screens/HistoryScreen';
import { HISTORY_PAGE_SIZE } from '@rocell/schema/scan';
import type { ScanCandidate, ScanHistoryEntry } from '@rocell/schema/scan';
import type { User } from '@rocell/schema/user';

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const HISTORY = '/api/scans';
/** The denominator behind "Showing 10 of 213 scans" — `GET /scans/count`. */
const COUNT = '/api/scans/count';

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

const BEST_CANDIDATE: ScanCandidate = {
  tile_id: '11111111-1111-4111-8111-111111111111',
  code: 'RP.CMA.0001DJ.SM.0T',
  size: '45X90',
  category: 'CREMA MARMOL',
  image_id: '22222222-2222-4222-8222-222222222222',
};

const SECOND_CANDIDATE: ScanCandidate = {
  tile_id: '33333333-3333-4333-8333-333333333333',
  code: 'RP.CMA.0002DJ.SM.0T',
  size: '45X90',
  category: null,
  image_id: '44444444-4444-4444-8444-444444444444',
};

const A_SCAN: ScanHistoryEntry = {
  id: '55555555-5555-4555-8555-555555555555',
  created_at: '2026-09-22T09:30:00Z',
  candidates: [BEST_CANDIDATE, SECOND_CANDIDATE],
};

const AN_EMPTY_SCAN: ScanHistoryEntry = {
  id: '66666666-6666-4666-8666-666666666666',
  created_at: '2026-09-21T18:00:00Z',
  candidates: [],
};

interface Reply {
  status: number;
  body?: unknown;
}

/** `audit-log.test.tsx`'s own stub: a `fetch` queue keyed by full request path. */
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
 * `audit-log.test.tsx`'s own deferred stub, for the stale-answer race.
 *
 * `GET /scans/count` is answered immediately and left out of `calls`
 * entirely: every test using this stub settles its requests by ordinal, and
 * those ordinals are about *pages*. A count interleaved among them would make
 * each `settle(n)` a claim about request ordering that no test here means to
 * make, and the screen already treats the count as a subtitle that lands
 * whenever it lands.
 */
function stubDeferred(): { settle: (nth: number, reply: Reply) => void; calls: string[] } {
  const settlers: ((reply: Reply) => void)[] = [];
  const calls: string[] = [];

  vi.stubGlobal('fetch', (input: string) => {
    if (input === COUNT) {
      return Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve({ count: 0 }),
      } as Response);
    }
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

/** A `{ count }` body for `GET /scans/count`. */
const counted = (count: number): Reply => ({ status: 200, body: { count } });

/**
 * One page of history and the total behind it.
 *
 * `total` defaults to the page's own length — the ordinary case for a short
 * page, where every scan the caller has is on screen. A test that wants the
 * count to disagree with the rows, or to fail outright, stubs the two paths
 * itself.
 */
function stubPage(
  entries: readonly ScanHistoryEntry[],
  total = entries.length,
): { calls: [string, RequestInit][] } {
  return stubFetch({ [HISTORY]: [{ status: 200, body: entries }], [COUNT]: [counted(total)] });
}

const refusal = (code: string, message: string, status: number): Reply => ({
  status,
  body: { error: { code, message } },
});

function renderScreen(props: { onBack?: () => void } = {}): {
  onBack: () => void;
  unmount: () => void;
} {
  const onBack = props.onBack ?? ((): void => undefined);
  const { unmount } = render(<HistoryScreen onBack={onBack} />);
  return { onBack, unmount };
}

/** A synthetic run of scans, newest first, for the paging tests. */
function run(count: number, from = 0): ScanHistoryEntry[] {
  return Array.from({ length: count }, (_unused, index) => {
    const nth = from + index;
    return {
      ...A_SCAN,
      id: `00000000-0000-4000-8000-${String(nth).padStart(12, '0')}`,
      candidates: [{ ...BEST_CANDIDATE, code: `RP.CMA.${String(nth).padStart(4, '0')}` }],
    };
  });
}

// --- The request ----------------------------------------------------------------

describe('the request', () => {
  it('reads history on mount, with the session cookie and no body', async () => {
    const { calls } = stubPage([A_SCAN]);
    renderScreen();

    await screen.findByText(A_SCAN.candidates[0]?.code ?? '');

    const [path, init] = calls[0] ?? ['', {}];
    expect(path).toBe(HISTORY);
    expect(init.method).toBe('GET');
    expect(init.credentials).toBe('same-origin');
    expect(init.body).toBeUndefined();
  });

  it('sends no cursor on the first page, and asks for the total beside it', async () => {
    const { calls } = stubPage([A_SCAN]);
    renderScreen();

    await screen.findByText(A_SCAN.candidates[0]?.code ?? '');

    // Exactly two requests, the page first: no cursor on the first page, and
    // the count is a second request rather than a field on it — `GET /scans`
    // answers with a bare array and has nowhere to carry a total.
    expect(calls.map(([path]) => path)).toEqual([HISTORY, COUNT]);
  });

  it('announces the wait rather than showing nothing', async () => {
    stubPage([A_SCAN]);
    renderScreen();

    expect(screen.getByRole('status').textContent).toMatch(/loading your scan history/i);

    await screen.findByText(A_SCAN.candidates[0]?.code ?? '');
  });
});

// --- The entries ------------------------------------------------------------------

describe('the entries', () => {
  it('renders each scan’s timestamp above its candidates', async () => {
    const expected = new Date(A_SCAN.created_at).toLocaleString(undefined, {
      dateStyle: 'medium',
      timeStyle: 'long',
    });
    stubPage([A_SCAN]);
    renderScreen();

    expect(await screen.findByText(expected)).toBeTruthy();
  });

  it('shows every candidate, best match first, in the order the API sent', async () => {
    stubPage([A_SCAN]);
    renderScreen();

    await screen.findByText(BEST_CANDIDATE.code);

    expect(screen.getByText(SECOND_CANDIDATE.code)).toBeTruthy();
    expect(screen.getByText(/best match/i)).toBeTruthy();
    // No similarity value anywhere on screen (AD-20).
    expect(document.body.textContent).not.toMatch(/\d+%|score|confidence/i);
  });

  it('renders Size and Category, falling back to Unknown for a null Category', async () => {
    stubPage([A_SCAN]);
    renderScreen();

    await screen.findByText(BEST_CANDIDATE.code);

    expect(screen.getByText(`${BEST_CANDIDATE.size} · ${BEST_CANDIDATE.category}`)).toBeTruthy();
    expect(screen.getByText(new RegExp(`${SECOND_CANDIDATE.size}.*Unknown`, 'i'))).toBeTruthy();
  });

  it('renders a past scan with no confident match without a blank card area', async () => {
    stubPage([AN_EMPTY_SCAN]);
    renderScreen();

    expect(await screen.findByText(/no confident match/i)).toBeTruthy();
  });

  it('keeps the order the API sent, and adds none of its own', async () => {
    const second: ScanHistoryEntry = {
      ...AN_EMPTY_SCAN,
      id: '77777777-7777-4777-8777-777777777777',
      created_at: '2026-09-20T08:00:00Z',
    };
    stubPage([A_SCAN, second]);
    renderScreen();

    await screen.findByText(BEST_CANDIDATE.code);
    const timestamps = [A_SCAN, second].map((entry) =>
      new Date(entry.created_at).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'long' }),
    );

    for (const timestamp of timestamps) {
      expect(screen.getByText(timestamp)).toBeTruthy();
    }
  });
});

// --- AD-10: a removed Tile's snapshot still renders ----------------------------

describe('a candidate whose Tile has since been removed', () => {
  it('still renders its Code, Size and Category from the stored snapshot', async () => {
    // The API's own guarantee (`test_scan_history.py`'s
    // `test_a_removed_tiles_history_entry_still_renders_its_snapshot`):
    // `candidates` is a denormalized snapshot, not a live re-fetch, so a
    // Tile removed after the fact changes nothing about what this entry
    // carries. This is the same claim proved at the screen surface: the
    // fixture below names a `tile_id`/`image_id` pair no server the screen
    // could reach would recognise, and the text still renders — the image
    // request itself is not exercised or asserted on here, `apps/web`'s own
    // established convention that no image-consuming screen special-cases a
    // 404 (`ResultsScreen`, `CatalogueScreen`).
    const removedTileCandidate: ScanCandidate = {
      tile_id: '99999999-9999-4999-8999-999999999999',
      code: 'RP.CMA.0099DJ.SM.0T',
      size: '60X60',
      category: 'ASTORIA',
      image_id: '88888888-8888-4888-8888-888888888888',
    };
    const entryForRemovedTile: ScanHistoryEntry = {
      id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
      created_at: '2026-09-19T12:00:00Z',
      candidates: [removedTileCandidate],
    };
    stubPage([entryForRemovedTile]);
    renderScreen();

    expect(await screen.findByText(removedTileCandidate.code)).toBeTruthy();
    expect(
      screen.getByText(`${removedTileCandidate.size} · ${removedTileCandidate.category}`),
    ).toBeTruthy();
  });
});

// --- Failures -----------------------------------------------------------------

describe('a failed load', () => {
  it('carries the API’s own sentence in one alert', async () => {
    stubFetch({ [HISTORY]: [refusal('unauthorized', 'Not signed in.', 401)] });
    renderScreen();

    const alert = await screen.findByRole('alert');

    expect(alert.textContent).toBe('Not signed in.');
    expect(screen.queryByText(/no scans yet/i)).toBeNull();
  });

  it('offers Try again, and refetches on it', async () => {
    stubFetch({
      [HISTORY]: [
        refusal('internal_error', 'Something went wrong.', 500),
        { status: 200, body: [A_SCAN] },
      ],
    });
    renderScreen();

    await screen.findByRole('alert');
    fireEvent.click(screen.getByRole('button', { name: /^try again$/i }));

    expect(await screen.findByText(BEST_CANDIDATE.code)).toBeTruthy();
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('words a failure that is not an ApiRequestError itself', async () => {
    vi.stubGlobal('fetch', () => Promise.resolve(null));
    renderScreen();

    const alert = await screen.findByRole('alert');

    expect(alert.textContent).toMatch(/could not be loaded/i);
  });
});

// --- Two requests open at once -------------------------------------------------

describe('a stale answer', () => {
  it('never overwrites a newer one', async () => {
    const { settle, calls } = stubDeferred();
    render(<HistoryScreen onBack={(): void => undefined} />, { wrapper: StrictMode });

    await waitFor(() => {
      expect(calls).toHaveLength(2);
    });

    settle(1, { status: 200, body: [A_SCAN] });
    await screen.findByText(BEST_CANDIDATE.code);

    settle(0, { status: 200, body: [AN_EMPTY_SCAN] });

    await waitFor(() => {
      expect(screen.getByText(BEST_CANDIDATE.code)).toBeTruthy();
    });
  });
});

// --- The empty history ----------------------------------------------------------

describe('an empty history', () => {
  it('says "No scans yet." rather than a blank screen', async () => {
    stubPage([]);
    renderScreen();

    expect(await screen.findByText('No scans yet.')).toBeTruthy();
  });

  it('offers nothing to load more of', async () => {
    stubPage([]);
    renderScreen();

    await screen.findByText('No scans yet.');

    expect(screen.queryByRole('button', { name: /^load more$/i })).toBeNull();
  });
});

// --- Paging -------------------------------------------------------------------

describe('Load more', () => {
  const FULL = run(HISTORY_PAGE_SIZE);
  const AFTER_FULL = `${HISTORY}?before=${FULL[HISTORY_PAGE_SIZE - 1]?.id ?? ''}`;

  it('is not offered when the first page is short', async () => {
    stubPage(run(2));
    renderScreen();

    await screen.findByText('RP.CMA.0000');

    expect(screen.queryByRole('button', { name: /^load more$/i })).toBeNull();
  });

  it('is offered when the first page is full, and appends the next page on request', async () => {
    stubFetch({
      [HISTORY]: [{ status: 200, body: FULL }],
      [AFTER_FULL]: [{ status: 200, body: run(3, HISTORY_PAGE_SIZE) }],
    });
    renderScreen();

    await screen.findByRole('button', { name: /^load more$/i });
    fireEvent.click(screen.getByRole('button', { name: /^load more$/i }));

    await waitFor(() => {
      expect(screen.getByText(`RP.CMA.${String(HISTORY_PAGE_SIZE).padStart(4, '0')}`)).toBeTruthy();
    });
    // Nothing from the first page vanished.
    expect(screen.getByText('RP.CMA.0000')).toBeTruthy();
  });

  it('disappears once a page comes back short', async () => {
    stubFetch({
      [HISTORY]: [{ status: 200, body: FULL }],
      [AFTER_FULL]: [{ status: 200, body: run(1, HISTORY_PAGE_SIZE) }],
    });
    renderScreen();

    await screen.findByRole('button', { name: /^load more$/i });
    fireEvent.click(screen.getByRole('button', { name: /^load more$/i }));

    await waitFor(() => {
      expect(screen.queryByRole('button', { name: /^load more$/i })).toBeNull();
    });
  });

  it('keeps the rows on screen when the next page fails, and can be pressed again', async () => {
    stubFetch({
      [HISTORY]: [{ status: 200, body: FULL }],
      [AFTER_FULL]: [
        refusal('internal_error', 'Something went wrong.', 500),
        { status: 200, body: run(1, HISTORY_PAGE_SIZE) },
      ],
    });
    renderScreen();

    await screen.findByRole('button', { name: /^load more$/i });
    fireEvent.click(screen.getByRole('button', { name: /^load more$/i }));

    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toBe('Something went wrong.');
    expect(screen.getByText('RP.CMA.0000')).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: /^load more$/i }));

    expect(
      await screen.findByText(`RP.CMA.${String(HISTORY_PAGE_SIZE).padStart(4, '0')}`),
    ).toBeTruthy();
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('sends exactly one request when pressed three times in one tick', async () => {
    const { settle, calls } = stubDeferred();
    renderScreen();

    settle(0, { status: 200, body: FULL });
    await screen.findByRole('button', { name: /^load more$/i });

    const control = screen.getByRole('button', { name: /^load more$/i });
    act(() => {
      control.click();
      control.click();
      control.click();
    });

    await waitFor(() => {
      expect(screen.getByRole('status').textContent).toMatch(/loading more scans/i);
    });
    expect(calls).toHaveLength(2);
  });
});

// --- How many, out of how many -------------------------------------------------

describe('the count', () => {
  const FULL = run(HISTORY_PAGE_SIZE);
  const AFTER_FULL = `${HISTORY}?before=${FULL[HISTORY_PAGE_SIZE - 1]?.id ?? ''}`;
  /** Off the shared constant, never a literal — the page size is the server's. */
  const A_FULL_PAGE_OF = `Showing ${HISTORY_PAGE_SIZE} of 213 scans`;

  it('says how many scans are on screen, out of how many the caller has', async () => {
    stubFetch({ [HISTORY]: [{ status: 200, body: FULL }], [COUNT]: [counted(213)] });
    renderScreen();

    expect(await screen.findByText(A_FULL_PAGE_OF)).toBeTruthy();
  });

  it('counts a single scan in the singular', async () => {
    stubPage([A_SCAN], 1);
    renderScreen();

    await screen.findByText(BEST_CANDIDATE.code);

    expect(screen.getByText('Showing 1 of 1 scan')).toBeTruthy();
  });

  it('grows with the rows as pages are appended, and keeps the same total', async () => {
    stubFetch({
      [HISTORY]: [{ status: 200, body: FULL }],
      [AFTER_FULL]: [{ status: 200, body: run(3, HISTORY_PAGE_SIZE) }],
      [COUNT]: [counted(213)],
    });
    renderScreen();

    await screen.findByText(A_FULL_PAGE_OF);
    fireEvent.click(screen.getByRole('button', { name: /^load more$/i }));

    // The denominator is read once, with the first page: paging cannot change
    // how many scans exist, and a second count per page would only give the
    // number a chance to move under the reader.
    expect(
      await screen.findByText(`Showing ${HISTORY_PAGE_SIZE + 3} of 213 scans`),
    ).toBeTruthy();
  });

  it('drops the denominator rather than the history when the total does not arrive', async () => {
    stubFetch({
      [HISTORY]: [{ status: 200, body: run(2) }],
      [COUNT]: [refusal('internal_error', 'Something went wrong.', 500)],
    });
    renderScreen();

    // The rows are the screen; the total is a subtitle on them. A count that
    // failed must not cost the reader the history, and must not raise an
    // alert of its own over a page that loaded perfectly well.
    expect(await screen.findByText('Showing 2 scans')).toBeTruthy();
    expect(screen.getByText('RP.CMA.0000')).toBeTruthy();
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('never claims fewer scans than are on screen', async () => {
    // The count and the first page are two requests: a scan submitted between
    // them leaves a total the rendered rows have already passed. "Showing 2 of
    // 2" is a stale denominator; "Showing 2 of 1" is a bug on screen.
    stubPage(run(2), 1);
    renderScreen();

    await screen.findByText('RP.CMA.0000');

    expect(screen.getByText('Showing 2 of 2 scans')).toBeTruthy();
  });

  it('says nothing at all about an empty history', async () => {
    stubPage([]);
    renderScreen();

    await screen.findByText('No scans yet.');

    // "No scans yet." already is the count. A "Showing 0 of 0 scans" beneath
    // it would be a second, worse way of saying the same thing.
    expect(screen.queryByText(/^showing /i)).toBeNull();
  });
});

// --- The tap-to-fullscreen viewer -----------------------------------------------

describe('the tap-to-fullscreen viewer', () => {
  /** Renders the screen, reaches a loaded entry, and taps its best-match card. */
  async function openViewerFromCard(): Promise<HTMLElement> {
    stubPage([A_SCAN]);
    renderScreen();

    await screen.findByText(BEST_CANDIDATE.code);
    // The card is the button carrying the Candidate's own code and reference
    // image — `ImageViewer`'s own doc comment names this the "opener" focus
    // has to return to.
    const card = screen.getByRole('button', { name: new RegExp(BEST_CANDIDATE.code) });
    // jsdom's `fireEvent.click` does not focus the element the way a real
    // browser click does, so the opener has to be focused by hand —
    // `scan.test.tsx`'s own pattern, for the same reason.
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
        fireEvent.click(screen.getByRole('button', { name: /^close$/i }));
      },
    ],
  ])('%s closes the viewer and returns focus to the tapped candidate card', async (
    _label,
    close,
  ) => {
    const card = await openViewerFromCard();

    close();

    expect(screen.queryByRole('dialog')).toBeNull();
    // The card is where the tap started, and it is where it is left —
    // `ConfirmDialog`'s own focus-restore contract, restated for the one
    // control `ImageViewer` has to return to.
    expect(document.activeElement).toBe(card);
  });
});

// --- No row-end actions ---------------------------------------------------------

describe('the controls', () => {
  it('carries Back and nothing else beyond the Candidate cards themselves', async () => {
    stubPage([AN_EMPTY_SCAN]);
    renderScreen();

    await screen.findByText(/no confident match/i);

    expect(screen.getAllByRole('button').map((control) => control.textContent)).toEqual(['Back']);
  });

  it('hands Back straight to its prop', async () => {
    const onBack = vi.fn();
    stubPage([A_SCAN]);
    renderScreen({ onBack });

    await screen.findByText(BEST_CANDIDATE.code);
    fireEvent.click(screen.getByRole('button', { name: /^back$/i }));

    expect(onBack).toHaveBeenCalledTimes(1);
  });
});

// --- The door on the home panel -----------------------------------------------

describe('the door on the home panel', () => {
  function shell(user: User): { calls: [string, RequestInit][] } {
    return stubFetch({
      '/api/auth/session': [{ status: 200, body: user }],
      [HISTORY]: [{ status: 200, body: [A_SCAN] }],
    });
  }

  it.each([
    ['a Staff user', STAFF],
    ['an Administrator', ADMIN],
  ])('is offered to %s, unlike the admin-only doors', async (_label, user) => {
    shell(user);
    render(<App />);

    expect(await screen.findByRole('button', { name: /^history$/i })).toBeTruthy();
  });

  it('stands beside Scan rather than among the admin-only doors', async () => {
    shell(STAFF);
    render(<App />);

    expect(await screen.findByRole('button', { name: /^scan$/i })).toBeTruthy();
    expect(screen.getByRole('button', { name: /^history$/i })).toBeTruthy();
    // None of the admin-only doors render for Staff.
    expect(screen.queryByRole('button', { name: /^users$/i })).toBeNull();
    expect(screen.queryByRole('button', { name: /^audit log$/i })).toBeNull();
    expect(screen.queryByRole('button', { name: /^catalogue$/i })).toBeNull();
  });

  it('opens History and comes back to the home panel again', async () => {
    shell(STAFF);
    render(<App />);

    fireEvent.click(await screen.findByRole('button', { name: /^history$/i }));

    expect(await screen.findByRole('heading', { name: /^history$/i })).toBeTruthy();
    expect(await screen.findByText(BEST_CANDIDATE.code)).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: /^back$/i }));

    expect(await screen.findByText(/signed in as/i)).toBeTruthy();
    expect(screen.queryByRole('heading', { name: /^history$/i })).toBeNull();
  });
});
