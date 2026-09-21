/**
 * Audit log — the record an Administrator reviews access history from (FR-21).
 *
 * Two halves, driven through two different roots, the way `create-user.test.tsx`
 * splits them. The screen's own behaviour runs against a stubbed `fetch` with
 * the screen rendered directly, because it calls `apiRequest` itself rather than
 * going through `SessionProvider`; whether the app *reaches* the screen at all
 * runs through `App`, because the role condition and the section state live in
 * the gate.
 *
 * Three assertions here are the ones nothing else in the suite can make: that
 * the surface carries **zero** row-end controls at any role — no edit, no
 * delete, no menu, no checkbox and no clickable row, which is the whole of
 * EXPERIENCE.md:75 and which a screenshot review would have to catch otherwise;
 * that an `action` the build has never heard of still renders, under its stored
 * value; and that a page boundary appends rather than replaces and then removes
 * its own control.
 */
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { StrictMode } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import App from '../App';
import { AuditLogScreen } from '../screens/AuditLogScreen';
// The same module the screen imports, so a class assertion names the *mapping*
// rather than a hashed string: `vite.config.ts` sets `css: false`, so a
// CSS-module key resolves to a generated name.
import styles from '../screens/AuditLogScreen.module.css';
import { AUDIT_PAGE_SIZE } from '@rocell/schema/audit';
import type { AuditLogEntry } from '@rocell/schema/audit';
import type { User } from '@rocell/schema/user';

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const AUDIT = '/api/admin/audit';

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

const STAFF: User = {
  ...ADMIN,
  id: '3f1a6b2c-9d4e-4f70-8a11-5c2e7b9d0a34',
  name: 'Kasun Perera',
  email: 'kasun@rocell.lk',
  role: 'staff',
};

/** A signed-in Administrator's own entry: actor and target are the same person. */
const SIGNED_IN: AuditLogEntry = {
  id: '1a2b3c4d-5e6f-4071-8293-a4b5c6d7e8f9',
  created_at: '2026-09-21T09:30:00Z',
  action: 'login_succeeded',
  actor_user_id: ADMIN.id,
  actor_email: ADMIN.email,
  target_user_id: ADMIN.id,
  target_email: ADMIN.email,
  source_ip: '127.0.0.1',
  details: {},
};

/** An admin write: a different target, and a nested `details` payload. */
const EDITED: AuditLogEntry = {
  ...SIGNED_IN,
  id: '2b3c4d5e-6f70-4182-93a4-b5c6d7e8f901',
  created_at: '2026-09-21T09:25:00Z',
  action: 'user_edited',
  target_user_id: STAFF.id,
  target_email: STAFF.email,
  details: { changed: { role: { from: 'staff', to: 'admin' } } },
};

/**
 * An unknown-account sign-in attempt: nobody is known, so both halves of the
 * actor pair are null — and the address did not parse either.
 */
const NO_ACTOR_ENTRY: AuditLogEntry = {
  ...SIGNED_IN,
  id: '3c4d5e6f-7081-4293-a4b5-c6d7e8f90123',
  created_at: '2026-09-21T09:20:00Z',
  action: 'login_failed',
  actor_user_id: null,
  actor_email: null,
  target_user_id: null,
  target_email: null,
  source_ip: null,
  details: { reason: 'unknown_address' },
};

/**
 * Epic 2's pair. Both name the same object in the same column, and nothing but
 * `ACTION_LABELS` distinguishes "who put this tile in the catalogue" from "who
 * changed its Code" — a swap between the two values is invisible to the
 * membership tests in `audit-contract.test.ts`.
 */
const TILE_ADDED: AuditLogEntry = {
  ...SIGNED_IN,
  id: '5e6f7081-92a3-44b5-86c7-d8e9f0123456',
  created_at: '2026-09-21T09:15:00Z',
  action: 'catalogue_tile_added',
  details: { code: 'RP.CMA.0001DJ.SM.0T' },
};

const TILE_EDITED: AuditLogEntry = {
  ...SIGNED_IN,
  id: '6f708192-a3b4-45c6-97d8-e9f012345678',
  created_at: '2026-09-21T09:10:00Z',
  action: 'catalogue_tile_edited',
  details: { changed: { code: { from: 'RP.CMA.0001DJ.SM.0T', to: 'RP.CMA.0002DJ.SM.0T' } } },
};

/**
 * Story 2.3's entry — the third of the same set, and the only one whose subject
 * is gone by the time this screen renders it.
 *
 * It needs a row of its own here for the reason the pair above has one:
 * `ACTION_LABELS` is `Record<AuditAction, string>`, so the compiler forces the
 * *key* and says nothing at all about the value, and `audit-contract.test.ts`
 * never reads the map. A removal labelled "Tile edited" would type-check, pass
 * every contract test, and tell an Administrator reading the log that a tile
 * they can no longer find was merely corrected.
 */
const TILE_REMOVED: AuditLogEntry = {
  ...SIGNED_IN,
  id: '708192a3-b4c5-46d7-a8e9-f01234567890',
  created_at: '2026-09-21T09:05:00Z',
  action: 'catalogue_tile_removed',
  details: { code: 'RP.CMA.0003DJ.SM.0T' },
};

/** An action from an epic this build predates. Served and rendered verbatim. */
const UNKNOWN_ACTION: AuditLogEntry = {
  ...SIGNED_IN,
  id: '4d5e6f70-8192-43a4-b5c6-d7e8f9012345',
  created_at: '2026-09-21T09:15:00Z',
  action: 'scan_submitted',
  details: {},
};

/**
 * An action whose stored value is a property of every JavaScript object.
 *
 * Not a curiosity: `action` is free text with no CHECK, and AD-4's way of
 * correcting a wrong entry is to insert one by hand as the table owner. A
 * label map indexed with `?? action` returns `Object.prototype.toString` here
 * — a function, which is not nullish, so the fallback never fires and React
 * is handed a function as a table cell.
 */
const PROTOTYPE_ACTION: AuditLogEntry = {
  ...SIGNED_IN,
  id: '5e6f7081-9243-44b5-c6d7-e8f901234567',
  created_at: '2026-09-21T09:10:00Z',
  action: 'toString',
  details: {},
};

interface Reply {
  status: number;
  body?: unknown;
}

/**
 * Replace `fetch` with a queue keyed by the full request path, and record every
 * call.
 *
 * The cursor is in the path, so the key is what distinguishes a first page from
 * an appended one — which is exactly the thing the paging tests assert.
 *
 * `vi.stubGlobal` rather than assigning: jsdom does not implement `fetch`, so
 * the global may not be there to spy on in the first place. A local copy rather
 * than a shared helper, as the other suites keep theirs — a stub shared across
 * files is a fixture two tests can change under each other.
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
 * `stubFetch` answers immediately and in order, which is enough for every
 * behavioural case and cannot express the one the generation counter exists
 * for: two requests open at once, the older of the two answering last.
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

/** The first page as the API answers it. One reply, reused for every call. */
function stubPage(entries: readonly AuditLogEntry[]): { calls: [string, RequestInit][] } {
  return stubFetch({ [AUDIT]: [{ status: 200, body: entries }] });
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
  const { unmount } = render(<AuditLogScreen onBack={onBack} />);
  return { onBack, unmount };
}

/** A synthetic run of entries, newest first, for the paging tests. */
function run(count: number, from = 0): AuditLogEntry[] {
  return Array.from({ length: count }, (_unused, index) => {
    const nth = from + index;
    return {
      ...SIGNED_IN,
      // A valid UUIDv4 shape, because `isAuditLogEntry` checks the value and
      // not only the type — a counter dropped into a string would be refused
      // by the contract and the screen would render the failure state.
      id: `00000000-0000-4000-8000-${String(nth).padStart(12, '0')}`,
      created_at: '2026-09-21T09:30:00Z',
      details: { nth },
    };
  });
}

/** The row an entry's `details` text is in, so a cell assertion stays in one row. */
function rowForDetail(text: string): HTMLElement {
  const cell = screen.getByText(text);
  const row = cell.closest('tr');
  expect(row, `${text} is not in a table row`).toBeTruthy();
  return row as HTMLElement;
}

// --- The request --------------------------------------------------------------

describe('the request', () => {
  it('reads the log on mount, with the session cookie and no body', async () => {
    const { calls } = stubPage([SIGNED_IN]);
    renderScreen();

    await screen.findByRole('table');

    const [path, init] = calls[0] ?? ['', {}];
    expect(path).toBe(AUDIT);
    expect(init.method).toBe('GET');
    // The session travels in an HTTP-only cookie (AGENTS.md Policy), so the
    // request has to be told to send it — nothing else authenticates it.
    expect(init.credentials).toBe('same-origin');
    expect(init.body).toBeUndefined();
  });

  it('sends no cursor on the first page', async () => {
    const { calls } = stubPage([SIGNED_IN]);
    renderScreen();

    await screen.findByRole('table');

    expect(calls.map(([path]) => path)).toEqual([AUDIT]);
  });

  it('announces the wait rather than showing nothing', async () => {
    // A blank panel while the request is open reads as a screen that failed.
    // The line is `role="status"` so a screen-reader user is told too, without
    // being interrupted the way `role="alert"` would.
    stubPage([SIGNED_IN]);
    renderScreen();

    expect(screen.getByRole('status').textContent).toMatch(/loading the audit log/i);

    await screen.findByRole('table');
  });
});

// --- The rows -----------------------------------------------------------------

describe('the entries', () => {
  it('names the six columns the story asks for', async () => {
    stubPage([SIGNED_IN]);
    renderScreen();

    await screen.findByRole('table');
    const headers = screen.getAllByRole('columnheader').map((cell) => cell.textContent);

    expect(headers).toEqual(['When', 'Who', 'What', 'Target', 'Source IP', 'Details']);
  });

  it('puts each value under the column that names it', async () => {
    // The header test above pins the six labels and every other assertion in
    // this block is scoped to a *row*, which `within` satisfies wherever in
    // that row the string happens to be. Neither can see a transposition:
    // swapping the Who and Target cells leaves both of them findable and both
    // headers untouched, and the log would then name the deleted account as
    // the principal that deleted it. `EDITED` is the fixture that can tell
    // them apart — its actor and target are different people — and the
    // assertion is positional on purpose.
    stubPage([EDITED]);
    renderScreen();

    await screen.findByRole('table');
    const cells = [...(screen.getAllByRole('row')[1]?.children ?? [])].map(
      (cell) => cell.textContent,
    );

    expect(cells).toEqual([
      new Date(EDITED.created_at).toLocaleString(undefined, {
        dateStyle: 'medium',
        timeStyle: 'long',
      }),
      ADMIN.email,
      'User edited',
      STAFF.email,
      '127.0.0.1',
      'changed: {"role":{"from":"staff","to":"admin"}}',
    ]);
  });

  it('keeps the order the API sent, and adds none of its own', async () => {
    // The statement states the order — `ORDER BY created_at DESC, id DESC` — and
    // a second opinion here is how the two start disagreeing about what row
    // three is. The fixtures deliberately do **not** arrive sorted by any field
    // this screen could sort on.
    stubPage([NO_ACTOR_ENTRY, SIGNED_IN, EDITED]);
    renderScreen();

    await screen.findByRole('table');
    const details = screen
      .getAllByRole('row')
      .slice(1)
      .map((row) => row.children[5]?.textContent);

    expect(details).toEqual([
      'reason: unknown_address',
      'None',
      'changed: {"role":{"from":"staff","to":"admin"}}',
    ]);
  });

  it('renders the instant in the reader’s own locale, with seconds and a zone', async () => {
    // **Locale-independent on purpose**: the expectation is derived from the
    // same `Intl` options rather than written out, because the format belongs
    // to whoever is reading and only the *content* is this screen's claim.
    //
    // Seconds and the zone are both load-bearing. Two entries written by one
    // request share `created_at` to the microsecond — which is why the
    // statement orders on `id` as well — so without seconds those rows read
    // as the same instant and the column contradicts the order they are in.
    // Without the zone, "was this changed on Tuesday?" is answered in
    // whatever zone the browser is set to, with nothing on screen saying so.
    const expected = new Date(SIGNED_IN.created_at).toLocaleString(undefined, {
      dateStyle: 'medium',
      timeStyle: 'long',
    });
    stubPage([SIGNED_IN]);
    renderScreen();

    await screen.findByRole('table');

    expect(screen.getByText(expected)).toBeTruthy();

    // And the format really does carry both, whatever locale the run is in.
    // Asserted over `formatToParts` rather than over the rendered text: the
    // separators, the order and the words are the locale's business, the
    // presence of a seconds field and a zone field is this screen's. With the
    // options deleted the equality above would still hold — both sides would
    // simply be the bare format — so this is the half that fails.
    const parts = new Intl.DateTimeFormat(undefined, {
      dateStyle: 'medium',
      timeStyle: 'long',
    }).formatToParts(new Date(SIGNED_IN.created_at));
    const kinds = new Set(parts.map((part) => part.type));

    expect(kinds.has('second')).toBe(true);
    expect(kinds.has('timeZoneName')).toBe(true);
  });

  it('writes each action in words', async () => {
    stubPage([SIGNED_IN, EDITED, NO_ACTOR_ENTRY, TILE_ADDED, TILE_EDITED, TILE_REMOVED]);
    renderScreen();

    await screen.findByRole('table');

    expect(screen.getByText('Signed in')).toBeTruthy();
    expect(screen.getByText('User edited')).toBeTruthy();
    expect(screen.getByText('Sign-in failed')).toBeTruthy();
    // The catalogue set. Asserted by row rather than by page text so that
    // mapping two actions to one label, or swapping any of them, fails here:
    // `getByText` alone is satisfied by either string appearing anywhere.
    expect(rowForDetail('code: RP.CMA.0001DJ.SM.0T').textContent).toContain('Tile added');
    expect(
      rowForDetail(
        'changed: {"code":{"from":"RP.CMA.0001DJ.SM.0T","to":"RP.CMA.0002DJ.SM.0T"}}',
      ).textContent,
    ).toContain('Tile edited');
    expect(rowForDetail('code: RP.CMA.0003DJ.SM.0T').textContent).toContain('Tile removed');
  });

  it.each(['toString', 'constructor', 'valueOf', '__proto__'])(
    'renders %s as the text it is, not as the object property of that name',
    async (action) => {
      // `ACTION_LABELS[action] ?? action` reaches `Object.prototype` for each
      // of these and gets a *function*, which is not nullish — so the fallback
      // never fires and React is handed a function as a child. The screen
      // narrows with `isAuditAction` instead of indexing, which is a
      // membership test against `AUDIT_ACTIONS` and cannot see the prototype.
      stubPage([{ ...PROTOTYPE_ACTION, action }]);
      renderScreen();

      await screen.findByRole('table');
      const cell = screen.getByRole('table').querySelectorAll('td')[2];

      expect(cell?.textContent).toBe(action);
    },
  );

  it('renders a prototype-keyed action beside ordinary ones without throwing', async () => {
    // The same defect seen from the table rather than from the cell: one bad
    // row must not take the record down with it.
    stubPage([SIGNED_IN, PROTOTYPE_ACTION, EDITED]);
    renderScreen();

    await screen.findByRole('table');

    expect(screen.getAllByRole('row')).toHaveLength(4);
    expect(screen.getByText('toString')).toBeTruthy();
    expect(screen.getByText('Signed in')).toBeTruthy();
  });

  it('falls back to the stored value for an action it does not know', async () => {
    // The column has no CHECK, the vocabulary grows with Epics 2 and 3, and
    // AD-4's way of correcting a wrong entry is to insert one by hand. A viewer
    // that hid what it did not recognise would make the one table that can
    // never be rewritten less faithful on screen than in the database.
    stubPage([UNKNOWN_ACTION]);
    renderScreen();

    await screen.findByRole('table');

    expect(screen.getByText('scan_submitted')).toBeTruthy();
  });

  it('says there was no actor rather than leaving the cell blank', async () => {
    // And never names the target there instead: the entry does not know who
    // tried, and saying otherwise would be the log asserting something it was
    // never told.
    stubPage([NO_ACTOR_ENTRY]);
    renderScreen();

    await screen.findByRole('table');
    const row = within(rowForDetail('reason: unknown_address'));

    expect(row.getByText('No actor')).toBeTruthy();
    expect(row.getByText('No target')).toBeTruthy();
  });

  it('says the address was not recorded rather than leaving the cell blank', async () => {
    stubPage([NO_ACTOR_ENTRY]);
    renderScreen();

    await screen.findByRole('table');

    expect(within(rowForDetail('reason: unknown_address')).getByText('Not recorded')).toBeTruthy();
  });

  it('renders the actor, the target and the address when it has them', async () => {
    stubPage([EDITED]);
    renderScreen();

    await screen.findByRole('table');
    const row = within(rowForDetail('changed: {"role":{"from":"staff","to":"admin"}}'));

    expect(row.getByText(ADMIN.email)).toBeTruthy();
    expect(row.getByText(STAFF.email)).toBeTruthy();
    expect(row.getByText('127.0.0.1')).toBeTruthy();
  });

  it('writes details as sorted key-and-value text, whatever order they arrived in', async () => {
    // Object key order in JSON is insertion order, which is whichever order the
    // writing call site happened to build the dict in. Sorting here is what
    // makes two entries carrying the same facts read the same way.
    stubPage([
      { ...SIGNED_IN, details: { zulu: 'last', alpha: 'first', count: 3, ok: true } },
    ]);
    renderScreen();

    await screen.findByRole('table');

    expect(screen.getByText('alpha: first, count: 3, ok: true, zulu: last')).toBeTruthy();
  });

  it('says None for an entry carrying no details', async () => {
    stubPage([SIGNED_IN]);
    renderScreen();

    await screen.findByRole('table');

    expect(screen.getByText('None')).toBeTruthy();
  });

  it('paints every row with the audit-log-row treatment and no variant', async () => {
    // One treatment for every row, whatever it records. DESIGN.md:212 — the
    // audit row is "deliberately unremarkable", and a per-action colour here
    // would be the flagged-row treatment FR-22 owns, applied to data that does
    // not exist.
    stubPage([SIGNED_IN, NO_ACTOR_ENTRY, UNKNOWN_ACTION]);
    renderScreen();

    await screen.findByRole('table');

    for (const row of screen.getAllByRole('row').slice(1)) {
      expect(row.className).toBe(styles.row);
    }
  });
});

// --- Failures -----------------------------------------------------------------

describe('a failed load', () => {
  it('carries the API’s own sentence in one alert, with no table beside it', async () => {
    // A record missing rows is worse than no record: the entry somebody opened
    // the screen to find is exactly the one that would be gone.
    stubFetch({
      [AUDIT]: [refusal('administrator_required', 'Only an Administrator can do this.', 403)],
    });
    renderScreen();

    const alerts = await screen.findAllByRole('alert');

    expect(alerts).toHaveLength(1);
    expect(alerts[0]?.textContent).toBe('Only an Administrator can do this.');
    expect(screen.queryByRole('table')).toBeNull();
  });

  it('renders nothing from a body it could not understand', async () => {
    stubFetch({ [AUDIT]: [{ status: 200, body: [SIGNED_IN, { action: 'something' }] }] });
    renderScreen();

    await screen.findByRole('alert');

    expect(screen.queryByRole('table')).toBeNull();
    expect(screen.queryByText('Signed in')).toBeNull();
  });

  it('refuses a body that is not an array at all', async () => {
    stubFetch({ [AUDIT]: [{ status: 200, body: SIGNED_IN }] });
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
      [AUDIT]: [
        refusal('internal_error', 'Something went wrong.', 500),
        { status: 200, body: [SIGNED_IN] },
      ],
    });
    renderScreen();

    await screen.findByRole('alert');

    fireEvent.click(screen.getByRole('button', { name: /^try again$/i }));

    expect(await screen.findByRole('table')).toBeTruthy();
    expect(screen.queryByRole('alert')).toBeNull();
    await waitFor(() => {
      expect(calls.filter(([path]) => path === AUDIT)).toHaveLength(2);
    });
  });

  it('leaves the reader on the screen when Try again removes itself', async () => {
    // The press unmounts the control that was pressed, and a browser answers
    // that by dropping focus to `<body>`. jsdom moves focus for real, so this
    // is observable.
    stubFetch({
      [AUDIT]: [
        refusal('internal_error', 'Something went wrong.', 500),
        { status: 200, body: [SIGNED_IN] },
      ],
    });
    renderScreen();

    await screen.findByRole('alert');

    fireEvent.click(screen.getByRole('button', { name: /^try again$/i }));

    expect(document.activeElement).toBe(screen.getByRole('heading', { name: /^audit log$/i }));
    expect(document.activeElement).not.toBe(document.body);
  });

  it('offers Try again only while there is something to retry', async () => {
    stubPage([SIGNED_IN]);
    renderScreen();

    await screen.findByRole('table');

    expect(screen.queryByRole('button', { name: /^try again$/i })).toBeNull();
  });
});

// --- Two requests open at once -------------------------------------------------

describe('a stale answer', () => {
  it('never overwrites a newer one', async () => {
    // StrictMode mounts, tears down and mounts again, so two reads are open at
    // the same time and the *first* is the stale one. Settled last, it must not
    // replace what the second returned — which is the whole job of the
    // generation counter.
    const { settle, calls } = stubDeferred();
    render(<AuditLogScreen onBack={(): void => undefined} />, { wrapper: StrictMode });

    await waitFor(() => {
      expect(calls).toHaveLength(2);
    });

    settle(1, { status: 200, body: [SIGNED_IN] });
    await screen.findByText('Signed in');

    settle(0, { status: 200, body: [UNKNOWN_ACTION] });

    await waitFor(() => {
      expect(screen.getByText('Signed in')).toBeTruthy();
    });
    expect(screen.queryByText('scan_submitted')).toBeNull();
  });

  it('is dropped rather than written to a screen that has gone', async () => {
    const complaints = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    const { settle } = stubDeferred();
    const { unmount } = renderScreen();

    unmount();
    settle(0, { status: 200, body: [SIGNED_IN] });
    await waitFor(() => {
      expect(complaints).not.toHaveBeenCalled();
    });

    expect(screen.queryByText('Signed in')).toBeNull();
    complaints.mockRestore();
  });
});

// --- The empty log ------------------------------------------------------------

describe('an empty log', () => {
  it('says so rather than showing a bare header', async () => {
    // Unreachable in the product — the reader's own sign-in is an entry — but a
    // header row with nothing under it reads as a screen that failed.
    stubPage([]);
    renderScreen();

    expect(await screen.findByText(/^no entries\.$/i)).toBeTruthy();
    expect(screen.queryByRole('table')).toBeNull();
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('offers nothing to load more of', async () => {
    stubPage([]);
    renderScreen();

    await screen.findByText(/^no entries\.$/i);

    expect(screen.queryByRole('button', { name: /^load more$/i })).toBeNull();
  });
});

// --- Paging -------------------------------------------------------------------

describe('Load more', () => {
  /** A page the server filled to the brim: the only length that means "maybe more". */
  const FULL = run(AUDIT_PAGE_SIZE);
  const AFTER_FULL = `${AUDIT}?before=${FULL[AUDIT_PAGE_SIZE - 1]?.id ?? ''}`;

  it('is not offered at all when the first page is short', async () => {
    // **The case the published page size exists for.** The response is a bare
    // array, so nothing in it says whether more entries follow — the screen
    // counts the page against `AUDIT_PAGE_SIZE`. Inferring the size from the
    // length of the first page instead would read these five entries as a full
    // page of five, and every short log — which is every log early in this
    // product's life — would offer a control that fetches nothing.
    const { calls } = stubPage(run(5));
    renderScreen();

    await screen.findByRole('table');

    expect(screen.queryByRole('button', { name: /^load more$/i })).toBeNull();
    // And nothing was asked for beyond the one page.
    expect(calls.map(([path]) => path)).toEqual([AUDIT]);
  });

  it('is offered when the first page is full', async () => {
    // The other half of the same rule, so the test above cannot pass by the
    // control having been deleted outright.
    stubPage(FULL);
    renderScreen();

    await screen.findByRole('table');

    expect(screen.getByRole('button', { name: /^load more$/i })).toBeTruthy();
  });

  it('asks for what is older than the oldest row on screen', async () => {
    const { calls } = stubFetch({
      [AUDIT]: [{ status: 200, body: FULL }],
      [AFTER_FULL]: [{ status: 200, body: [] }],
    });
    renderScreen();

    await screen.findByRole('table');
    fireEvent.click(screen.getByRole('button', { name: /^load more$/i }));

    await waitFor(() => {
      expect(calls).toHaveLength(2);
    });
    expect(calls[1]?.[0]).toBe(AFTER_FULL);
    expect(calls[1]?.[1]?.method).toBe('GET');
  });

  it('appends the next page below the last row rather than replacing it', async () => {
    const second = run(3, AUDIT_PAGE_SIZE);
    stubFetch({
      [AUDIT]: [{ status: 200, body: FULL }],
      [AFTER_FULL]: [{ status: 200, body: second }],
    });
    renderScreen();

    await screen.findByRole('table');
    fireEvent.click(screen.getByRole('button', { name: /^load more$/i }));

    await waitFor(() => {
      expect(screen.getAllByRole('row')).toHaveLength(AUDIT_PAGE_SIZE + 3 + 1);
    });
    // Every row from both pages, in the order the two answers arrived — no
    // entry repeated and none skipped.
    const details = screen
      .getAllByRole('row')
      .slice(1)
      .map((row) => row.children[5]?.textContent);
    expect(details).toEqual(
      Array.from({ length: AUDIT_PAGE_SIZE + 3 }, (_unused, nth) => `nth: ${nth}`),
    );
  });

  it('disappears once a page comes back short', async () => {
    stubFetch({
      [AUDIT]: [{ status: 200, body: FULL }],
      [AFTER_FULL]: [{ status: 200, body: run(1, AUDIT_PAGE_SIZE) }],
    });
    renderScreen();

    await screen.findByRole('table');
    fireEvent.click(screen.getByRole('button', { name: /^load more$/i }));

    await waitFor(() => {
      expect(screen.queryByRole('button', { name: /^load more$/i })).toBeNull();
    });
    expect(screen.getByText(`nth: ${AUDIT_PAGE_SIZE}`)).toBeTruthy();
  });

  it('disappears on the empty page a log of exactly one page answers with', async () => {
    // The one press the published page size cannot settle in advance: a log
    // whose length is an exact multiple of the page size ends with a full
    // page, so the control stays up, and the press answers `[]`. A press, not
    // a defect — and cheaper than a second success-body shape.
    stubFetch({
      [AUDIT]: [{ status: 200, body: FULL }],
      [AFTER_FULL]: [{ status: 200, body: [] }],
    });
    renderScreen();

    await screen.findByRole('table');
    fireEvent.click(screen.getByRole('button', { name: /^load more$/i }));

    await waitFor(() => {
      expect(screen.queryByRole('button', { name: /^load more$/i })).toBeNull();
    });
    // And the rows already read are still there: the end of the log is not a
    // reason to take the record off the screen.
    expect(screen.getAllByRole('row')).toHaveLength(AUDIT_PAGE_SIZE + 1);
  });

  it('keeps offering while every page comes back full', async () => {
    // Two full pages in a row, so the control survives an append rather than
    // only surviving the first load.
    stubFetch({
      [AUDIT]: [{ status: 200, body: FULL }],
      [AFTER_FULL]: [{ status: 200, body: run(AUDIT_PAGE_SIZE, AUDIT_PAGE_SIZE) }],
    });
    renderScreen();

    await screen.findByRole('table');
    fireEvent.click(screen.getByRole('button', { name: /^load more$/i }));

    await waitFor(() => {
      expect(screen.getAllByRole('row')).toHaveLength(AUDIT_PAGE_SIZE * 2 + 1);
    });
    expect(screen.getByRole('button', { name: /^load more$/i })).toBeTruthy();
  });

  it('keeps the keyboard reader on the control while the page is in flight', async () => {
    // **`disabled` would blur it.** A disabled button leaves the tab order and
    // the browser drops focus to `<body>`, so a keyboard Administrator would
    // lose their place for the length of every request and have to tab back in
    // from the top of the document — on every page but the last.
    // EXPERIENCE.md:110 asks for a keyboard path on these surfaces, and that
    // is not one. `aria-disabled` says the same thing and keeps the focus.
    const { settle } = stubDeferred();
    renderScreen();

    settle(0, { status: 200, body: FULL });
    await screen.findByRole('table');

    const control = screen.getByRole('button', { name: /^load more$/i });
    control.focus();
    expect(document.activeElement).toBe(control);

    fireEvent.click(control);

    // While the append is open: still the control, still announced as busy.
    await waitFor(() => {
      expect(screen.getByRole('status').textContent).toMatch(/loading more entries/i);
    });
    expect(control.getAttribute('aria-disabled')).toBe('true');
    expect(document.activeElement).not.toBe(document.body);
    expect(document.activeElement).toBe(control);

    settle(1, { status: 200, body: run(AUDIT_PAGE_SIZE, AUDIT_PAGE_SIZE) });

    // And afterwards, with the control still on screen because the page came
    // back full: the reader has not moved at all.
    await waitFor(() => {
      expect(screen.getAllByRole('row')).toHaveLength(AUDIT_PAGE_SIZE * 2 + 1);
    });
    expect(screen.getByRole('button', { name: /^load more$/i }).getAttribute('aria-disabled')).toBe(
      'false',
    );
    expect(document.activeElement).not.toBe(document.body);
  });

  it('sends exactly one request when it is pressed three times in one tick', async () => {
    // **The attribute is not the guard.** Between two presses in two separate
    // tasks React has committed and `aria-disabled` is set — and it would not
    // stop the handler anyway, because the control is deliberately still
    // focusable and clickable. Three dispatches inside *one* task are the case
    // the render cannot cover at all: React batches them, nothing re-renders
    // in between, and each handler runs against the state from before the
    // first. Without `inFlight`, three identical cursor requests go out and
    // each appends the same page — duplicate rows under duplicate React keys.
    //
    // Driven through one `act` scope rather than three `fireEvent` calls
    // precisely because `fireEvent` closes its own scope and flushes: it would
    // reproduce the covered case and not this one.
    const { settle, calls } = stubDeferred();
    renderScreen();

    settle(0, { status: 200, body: FULL });
    await screen.findByRole('table');

    const control = screen.getByRole('button', { name: /^load more$/i });
    act(() => {
      control.click();
      control.click();
      control.click();
    });

    // One read on mount, one cursor request, and nothing else.
    await waitFor(() => {
      expect(screen.getByRole('status').textContent).toMatch(/loading more entries/i);
    });
    expect(calls).toHaveLength(2);
    expect(calls[1]).toBe(AFTER_FULL);

    settle(1, { status: 200, body: run(3, AUDIT_PAGE_SIZE) });

    // And one page was appended, not three.
    await waitFor(() => {
      expect(screen.getAllByRole('row')).toHaveLength(AUDIT_PAGE_SIZE + 3 + 1);
    });
    expect(calls).toHaveLength(2);
  });

  it('settles cleanly when the screen goes while a page is still in flight', async () => {
    // The `.finally` running against a generation the unmount has already
    // invalidated — the one condition under which the append's flags are
    // cleared for a listing nobody is looking at. Both are cleared
    // unconditionally so that "the wait line is up forever" cannot depend on
    // where a button happens to be rendered; this is the path that executes
    // it. React makes a late `setState` on an unmounted component a silent
    // no-op, so the observable claim is that nothing complains.
    const complaints = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    const { settle } = stubDeferred();
    const { unmount } = renderScreen();

    settle(0, { status: 200, body: FULL });
    await screen.findByRole('table');

    fireEvent.click(screen.getByRole('button', { name: /^load more$/i }));
    await waitFor(() => {
      expect(screen.getByRole('status').textContent).toMatch(/loading more entries/i);
    });

    unmount();
    settle(1, { status: 200, body: run(3, AUDIT_PAGE_SIZE) });

    await waitFor(() => {
      expect(complaints).not.toHaveBeenCalled();
    });
    expect(screen.queryByRole('table')).toBeNull();
    complaints.mockRestore();
  });

  it('leaves the reader beside the rows when it removes itself', async () => {
    stubFetch({
      [AUDIT]: [{ status: 200, body: FULL }],
      [AFTER_FULL]: [{ status: 200, body: [] }],
    });
    renderScreen();

    await screen.findByRole('table');
    fireEvent.click(screen.getByRole('button', { name: /^load more$/i }));

    await waitFor(() => {
      expect(screen.queryByRole('button', { name: /^load more$/i })).toBeNull();
    });
    expect(document.activeElement).toBe(screen.getByRole('region'));
    expect(document.activeElement).not.toBe(document.body);
  });

  it('leaves the reader where they moved to while the page was in flight', async () => {
    // The control keeps its focus through the request on purpose, so a
    // keyboard Administrator can tab off it while a page is loading. When that
    // page turns out to be the last one the control unmounts, and the rescue
    // fires — but only for a reader who was standing on the control, or on
    // nothing. Rescuing unconditionally would drag somebody who had already
    // tabbed to Back back into the table, which is the screen taking focus
    // rather than saving it.
    const { settle } = stubDeferred();
    renderScreen();

    settle(0, { status: 200, body: FULL });
    await screen.findByRole('table');

    const control = screen.getByRole('button', { name: /^load more$/i });
    control.focus();
    fireEvent.click(control);

    const back = screen.getByRole('button', { name: /^back$/i });
    back.focus();
    expect(document.activeElement).toBe(back);

    settle(1, { status: 200, body: [] });

    await waitFor(() => {
      expect(screen.queryByRole('button', { name: /^load more$/i })).toBeNull();
    });
    expect(document.activeElement).toBe(back);
  });

  it('keeps the rows on screen when the next page fails, and can be pressed again', async () => {
    stubFetch({
      [AUDIT]: [{ status: 200, body: FULL }],
      [AFTER_FULL]: [
        refusal('internal_error', 'Something went wrong.', 500),
        { status: 200, body: run(1, AUDIT_PAGE_SIZE) },
      ],
    });
    renderScreen();

    await screen.findByRole('table');
    fireEvent.click(screen.getByRole('button', { name: /^load more$/i }));

    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toBe('Something went wrong.');
    // The record already read stays on screen: it is not made better by being
    // hidden because its next page failed.
    expect(screen.getAllByRole('row')).toHaveLength(AUDIT_PAGE_SIZE + 1);

    fireEvent.click(screen.getByRole('button', { name: /^load more$/i }));

    expect(await screen.findByText(`nth: ${AUDIT_PAGE_SIZE}`)).toBeTruthy();
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('refuses a second page it could not understand, and keeps the first', async () => {
    // `asEntries` guards both call sites, but only the first page's guard was
    // exercised: every cursor reply in this file is well-formed, so narrowing
    // the append to `body as AuditLogEntry[]` left the whole suite green. An
    // unguarded append reaches `detailsText`, whose first statement is
    // `Object.keys(entry.details)` — an entry without `details` throws during
    // render and takes the rows already read down with it.
    stubFetch({
      [AUDIT]: [{ status: 200, body: FULL }],
      [AFTER_FULL]: [{ status: 200, body: [{ action: 'login_succeeded' }] }],
    });
    renderScreen();

    await screen.findByRole('table');
    fireEvent.click(screen.getByRole('button', { name: /^load more$/i }));

    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toBe('The server returned an unexpected response.');
    expect(screen.getAllByRole('row')).toHaveLength(AUDIT_PAGE_SIZE + 1);
  });

  it('announces the wait while a page is being appended', async () => {
    const { settle } = stubDeferred();
    renderScreen();

    settle(0, { status: 200, body: FULL });
    await screen.findByRole('table');

    fireEvent.click(screen.getByRole('button', { name: /^load more$/i }));

    await waitFor(() => {
      expect(screen.getByRole('status').textContent).toMatch(/loading more entries/i);
    });
    settle(1, { status: 200, body: [] });
  });
});

// --- The controls -------------------------------------------------------------

describe('the controls', () => {
  it('hands Back straight to its prop', async () => {
    const onBack = vi.fn();
    stubPage([SIGNED_IN]);
    renderScreen({ onBack });

    await screen.findByRole('table');
    fireEvent.click(screen.getByRole('button', { name: /^back$/i }));

    expect(onBack).toHaveBeenCalledTimes(1);
  });

  it('carries Back and nothing else on a log that fits in one page', async () => {
    // **The story's own clause, and the one nothing else can assert.**
    // EXPERIENCE.md:75 and FR-21: this is the one table in the product with
    // zero row-end actions, at any role. Asserted over the rendered control
    // names rather than by eye, so an edit, a delete, a row-end menu, a
    // bulk-select column or a "resolve" verb added later fails here.
    //
    // Three entries is a short page, so there is no Load more either — which
    // is what makes this the tightest version of the assertion: on the whole
    // screen there is exactly one control, and it goes back.
    stubPage([SIGNED_IN, EDITED, NO_ACTOR_ENTRY]);
    renderScreen();

    await screen.findByRole('table');
    const names = screen.getAllByRole('button').map((control) => control.textContent ?? '');

    expect(names).toEqual(['Back']);
    for (const verb of [/edit/i, /delete/i, /remove/i, /resolve/i, /dismiss/i, /flag/i, /export/i]) {
      expect(screen.queryByRole('button', { name: verb })).toBeNull();
    }
    expect(screen.queryByRole('link')).toBeNull();
    expect(screen.queryByRole('menuitem')).toBeNull();
    expect(screen.queryByRole('menu')).toBeNull();
    expect(screen.queryByRole('checkbox')).toBeNull();
    expect(screen.queryByRole('dialog')).toBeNull();
    // Nothing inside the table is a control at all.
    expect(screen.getByRole('table').querySelectorAll('button, a, input')).toHaveLength(0);
  });

  it('adds Load more and nothing else when there is another page', async () => {
    // The same claim on the longer log, so the exact list above cannot go
    // stale the moment a real deployment fills its first page: a full page
    // adds exactly one control, at the end of the list and not on a row.
    stubPage(run(AUDIT_PAGE_SIZE));
    renderScreen();

    await screen.findByRole('table');
    const names = screen.getAllByRole('button').map((control) => control.textContent ?? '');

    expect(names).toEqual(['Back', 'Load more']);
    expect(screen.getByRole('table').querySelectorAll('button, a, input')).toHaveLength(0);
    expect(screen.queryByRole('checkbox')).toBeNull();
    expect(screen.queryByRole('menuitem')).toBeNull();
  });

  it('offers no search box, sort control, filter or date range', async () => {
    // FR-21 asks for the log, in order. FR-22's Flagged filter renders anomaly
    // flagging, which is not in Epic 1 and has no column behind it — a control
    // over a field that does not exist is a dead control.
    stubPage([SIGNED_IN, EDITED]);
    renderScreen();

    await screen.findByRole('table');

    expect(screen.queryByRole('textbox')).toBeNull();
    expect(screen.queryByRole('searchbox')).toBeNull();
    expect(screen.queryByRole('combobox')).toBeNull();
    expect(screen.queryByRole('radio')).toBeNull();
    expect(screen.queryByRole('switch')).toBeNull();
    expect(
      screen.queryAllByRole('columnheader').every((cell) => cell.querySelector('button') === null),
    ).toBe(true);
  });

  it('does not make the row itself clickable', async () => {
    // **Asserted by clicking the row**, not by reading an `onclick` attribute:
    // React attaches handlers through its own synthetic event system and emits
    // no such attribute, so `<tr onClick={...}>` would satisfy an attribute
    // check unchanged — a guard that can never fail. The observable
    // consequence of a row handler here would be navigation, so the assertion
    // is that nothing about the screen changed.
    const onBack = vi.fn();
    stubPage([SIGNED_IN]);
    renderScreen({ onBack });

    await screen.findByRole('table');
    const row = rowForDetail('None');

    fireEvent.click(row);

    expect(onBack).not.toHaveBeenCalled();
    expect(screen.getByRole('table')).toBeTruthy();
    expect(row.getAttribute('tabindex')).toBeNull();
    expect(row.getAttribute('role')).toBeNull();
    expect(row.getAttribute('aria-selected')).toBeNull();
  });
});

// --- The table’s own container ------------------------------------------------

describe('the table at phone width', () => {
  it('sits in a labelled region a keyboard can scroll', async () => {
    stubPage([SIGNED_IN]);
    renderScreen();

    await screen.findByRole('table');
    const region = screen.getByRole('region');

    expect(region.getAttribute('tabindex')).toBe('0');
    expect(region.getAttribute('aria-labelledby')).toBe(
      screen.getByRole('heading', { name: /^audit log$/i }).id,
    );
  });

  it('keeps every cell associated with its column header', async () => {
    stubPage([SIGNED_IN]);
    renderScreen();

    await screen.findByRole('table');

    for (const header of screen.getAllByRole('columnheader')) {
      expect(header.getAttribute('scope')).toBe('col');
    }
  });
});

// --- The door on the home panel -----------------------------------------------

describe('the door on the home panel', () => {
  /**
   * The session plus the log behind the door, which every path here crosses.
   *
   * Keyed on the plain path, as the screen's own tests are: the shell's two
   * routes are both GETs on different paths, so the method adds nothing here.
   * A queue of session replies is what a mid-session role change looks like —
   * `SessionProvider` re-reads the session on `visibilitychange`.
   */
  function shell(sessions: Reply[]): { calls: [string, RequestInit][] } {
    return stubFetch({
      '/api/auth/session': sessions,
      [AUDIT]: [{ status: 200, body: [SIGNED_IN, EDITED] }],
    });
  }

  it('is offered to an Administrator', async () => {
    shell([{ status: 200, body: ADMIN }]);
    render(<App />);

    expect(await screen.findByRole('button', { name: /^audit log$/i })).toBeTruthy();
  });

  it('is not rendered anywhere for a Staff user', async () => {
    // EXPERIENCE.md line 18: the nav is role-conditional, not a menu with
    // disabled items — a Staff user never sees an Admin entry at all.
    shell([{ status: 200, body: STAFF }]);
    render(<App />);

    await screen.findByTestId('app-bar');
    expect(screen.queryByRole('button', { name: /^audit log$/i })).toBeNull();
    expect(screen.queryByRole('button', { name: /^users$/i })).toBeNull();
  });

  it('stands beside Users rather than instead of it', async () => {
    // Two of EXPERIENCE.md's six nav entries exist — line 33's User List and
    // line 38's Audit Log — and two collections is two entries. Create user and
    // Edit user are still reached from the list, not from here.
    shell([{ status: 200, body: ADMIN }]);
    render(<App />);

    expect(await screen.findByRole('button', { name: /^users$/i })).toBeTruthy();
    expect(screen.getByRole('button', { name: /^audit log$/i })).toBeTruthy();
    expect(screen.queryByRole('button', { name: /^create user$/i })).toBeNull();
  });

  it('opens the log and comes back again', async () => {
    shell([{ status: 200, body: ADMIN }]);
    render(<App />);

    fireEvent.click(await screen.findByRole('button', { name: /^audit log$/i }));

    expect(await screen.findByRole('heading', { name: /^audit log$/i })).toBeTruthy();
    expect(await screen.findByRole('table')).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: /^back$/i }));
    expect(await screen.findByText(/signed in as/i)).toBeTruthy();
  });

  it('is gone, with the surface, after a mid-session demotion', async () => {
    // The redirect EXPERIENCE.md line 95 asks for, expressed as a pure function
    // of role: an Administrator demoted while standing on this screen renders
    // the home panel on the very next render, not a dead screen — and there is
    // no frame in which the audit table is painted for a Staff user.
    shell([
      { status: 200, body: ADMIN },
      { status: 200, body: { ...ADMIN, role: 'staff' } },
    ]);
    render(<App />);

    fireEvent.click(await screen.findByRole('button', { name: /^audit log$/i }));
    await screen.findByRole('heading', { name: /^audit log$/i });

    // The visibility revalidation `SessionProvider` registers is what re-reads
    // the role (AD-3); this is that request arriving with the new one.
    document.dispatchEvent(new Event('visibilitychange'));

    expect(await screen.findByText(/signed in as/i)).toBeTruthy();
    expect(screen.queryByRole('heading', { name: /^audit log$/i })).toBeNull();
    expect(screen.queryByRole('button', { name: /^audit log$/i })).toBeNull();
    // And nothing of the record survives the swap — not a stale table, not a
    // row.
    expect(screen.queryByRole('table')).toBeNull();
  });
});
