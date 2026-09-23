/**
 * Users — the list an Administrator audits access from (FR-10).
 *
 * Driven against a stubbed `fetch` with the screen rendered directly, the way
 * `create-user.test.tsx` drives its own half: the screen calls `apiRequest`
 * itself rather than going through `SessionProvider`, so nothing here needs the
 * provider. Whether the app *reaches* this screen at all — the role-conditional
 * door, the reconcilers, the route on to Create user — is that file's
 * `describe('the door on the home panel')` block, and stays there.
 *
 * Three assertions here are the ones nothing else in the suite can make: that a
 * deactivated account renders the *word* "Deactivated" and not only a class,
 * that a lock in the future is shown and a lapsed one is not, and that a row
 * carries exactly three controls — Edit, the state verb, Delete — with nothing
 * that unlocks an account or sets a password, which no story in Epic 1 owns
 * (DW-64) and which a screenshot review would have to catch otherwise.
 *
 * What those three verbs *do* — the dialog, the pre-flight refusal, the request
 * and the row updating inline — is `deactivate-delete-user.test.tsx`. This file
 * stays about the list.
 */
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { StrictMode } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { UserListScreen } from '../screens/UserListScreen';
// The same module the screen imports, so the class assertions below name the
// *mapping* rather than a hashed string: `vite.config.ts` sets `css: false`, so
// a CSS-module key resolves to a generated name, and the only stable way to say
// "this element carries the deactivated variant" is to compare against the same
// key the component reads.
import styles from '../screens/UserListScreen.module.css';
import type { User } from '@rocell/schema/user';

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

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

/** Deactivated, and therefore on the list rather than missing from it (FR-10). */
const DEACTIVATED: User = {
  ...STAFF,
  id: '7b2c4d1e-8a35-4c62-9f04-1e5a3b7d2c98',
  name: 'Amal Perera',
  email: 'amal@rocell.lk',
  active: false,
};

/** Provisioned and not yet handed over: the account with no sign-in behind it. */
const UNCLAIMED: User = {
  ...STAFF,
  id: 'b41d8e06-5a72-4f39-9c88-0d3e1f7a2b65',
  name: 'Nadeesha Silva',
  email: 'nadeesha@rocell.lk',
  must_change_password: true,
  temp_credential_expires_at: '2026-09-21T09:30:00Z',
  last_login_at: null,
};

/**
 * Relative to *now*, not a written-down instant.
 *
 * The screen compares the column against the browser's clock, so a fixed
 * timestamp would be a live lock today and a lapsed one next year — the test
 * would start asserting the opposite of what it was written to assert, and
 * nothing would say so.
 */
function lockedFor(minutes: number): string {
  return new Date(Date.now() + minutes * 60_000).toISOString();
}

/**
 * Distinct rows rather than `{ ...STAFF }` with a lock added.
 *
 * `LOCKED` appears in the same list as `STAFF` below, and React keys a row on
 * `user.id` — two rows sharing one id is a duplicate-key warning and, worse, a
 * reconciler free to reuse one row's controls for the other. `LOCK_LAPSED` is
 * only ever rendered on its own today, and carries its own id anyway: the
 * hazard is not that it shares a list now, it is that adding it to one is a
 * one-line change nothing would warn about.
 */
const LOCKED: User = {
  ...STAFF,
  id: 'c58e2a91-6d04-4b73-8f21-9a7c3e5d0b16',
  name: 'Ishara Fernando',
  email: 'ishara@rocell.lk',
  locked_until: lockedFor(15),
};
const LOCK_LAPSED: User = {
  ...STAFF,
  id: '7f1b3c85-2e49-4a07-b6d3-5c80a9e4f217',
  name: 'Nimali Silva',
  email: 'nimali@rocell.lk',
  locked_until: lockedFor(-60),
};

interface Reply {
  status: number;
  body?: unknown;
}

/**
 * Replace `fetch` with a queue keyed by path, and record every call.
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
 * `stubFetch` above answers immediately and in order, which is enough for every
 * behavioural case and cannot express the one this screen's generation counter
 * exists for: two requests open at once, the older of the two answering last.
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

/** The list as the API answers it. One reply, reused for every call. */
function stubList(users: readonly User[]): { calls: [string, RequestInit][] } {
  return stubFetch({ '/api/admin/users': [{ status: 200, body: users }] });
}

const refusal = (code: string, message: string, status: number): Reply => ({
  status,
  body: { error: { code, message } },
});

function renderScreen(
  props: { onBack?: () => void; onAddUser?: () => void; onEditUser?: (user: User) => void } = {},
): {
  onBack: () => void;
  onAddUser: () => void;
  onEditUser: (user: User) => void;
  unmount: () => void;
} {
  const onBack = props.onBack ?? ((): void => undefined);
  const onAddUser = props.onAddUser ?? ((): void => undefined);
  const onEditUser = props.onEditUser ?? ((): void => undefined);
  const { unmount } = render(
    <UserListScreen onAddUser={onAddUser} onBack={onBack} onEditUser={onEditUser} />,
  );
  return { onBack, onAddUser, onEditUser, unmount };
}

/** The row a person's name is in, so a cell assertion cannot read another row's. */
function rowFor(name: string): HTMLElement {
  const cell = screen.getByText(name);
  const row = cell.closest('tr');
  expect(row, `${name} is not in a table row`).toBeTruthy();
  return row as HTMLElement;
}

// --- The request --------------------------------------------------------------

describe('the request', () => {
  it('reads the collection on mount, with the session cookie and no body', async () => {
    const { calls } = stubList([ADMIN]);
    renderScreen();

    await screen.findByRole('table');

    const [path, init] = calls[0] ?? ['', {}];
    expect(path).toBe('/api/admin/users');
    expect(init.method).toBe('GET');
    // The session travels in an HTTP-only cookie (AGENTS.md Policy), so the
    // request has to be told to send it — nothing else authenticates it.
    expect(init.credentials).toBe('same-origin');
    expect(init.body).toBeUndefined();
  });

  it('announces the wait rather than showing nothing', async () => {
    // A blank panel while the request is open reads as a screen that failed. The
    // line is `role="status"` so a screen-reader user is told too, without being
    // interrupted the way `role="alert"` would.
    stubFetch({ '/api/admin/users': [{ status: 200, body: [ADMIN] }] });
    renderScreen();

    expect(screen.getByRole('status').textContent).toMatch(/loading users/i);

    await screen.findByRole('table');
  });
});

// --- The rows -----------------------------------------------------------------

describe('the list', () => {
  it('renders every account it was given', async () => {
    stubList([ADMIN, STAFF, DEACTIVATED, UNCLAIMED]);
    renderScreen();

    await screen.findByRole('table');

    for (const user of [ADMIN, STAFF, DEACTIVATED, UNCLAIMED]) {
      expect(screen.getByText(user.name)).toBeTruthy();
      expect(screen.getByText(user.email)).toBeTruthy();
    }
  });

  it('keeps the order the API sent, and adds none of its own', async () => {
    // The ordering is `ORDER BY lower(name), email` in one statement on the
    // server (FR-10). A second opinion here — a sort in the component — is how
    // the two start disagreeing about what row three is.
    stubList([DEACTIVATED, ADMIN, UNCLAIMED]);
    renderScreen();

    await screen.findByRole('table');
    const names = screen.getAllByRole('row').slice(1).map((row) => row.children[0]?.textContent);

    expect(names).toEqual([DEACTIVATED.name, ADMIN.name, UNCLAIMED.name]);
  });

  it('names the five columns the story asks for, plus Story 1.10’s actions', async () => {
    // Story 1.9's five, in order, and the sixth Story 1.10 added at the row end.
    // The five keep their subjects: the new column must not disturb what the
    // other assertions in this file read.
    stubList([ADMIN]);
    renderScreen();

    await screen.findByRole('table');
    const headers = screen.getAllByRole('columnheader').map((cell) => cell.textContent);

    expect(headers).toEqual(['Name', 'Email', 'Role', 'Status', 'Last login', 'Actions']);
  });

  it('writes the roles in the glossary’s own words', async () => {
    stubList([ADMIN, STAFF]);
    renderScreen();

    await screen.findByRole('table');

    expect(within(rowFor(ADMIN.name)).getByText('Administrator')).toBeTruthy();
    expect(within(rowFor(STAFF.name)).getByText('Staff')).toBeTruthy();
  });

  it('paints each row and badge with the class its state maps to', async () => {
    // The mapping itself, which nothing else in the suite can see. The
    // styling-wiring tests parse the stylesheet as text and know nothing about
    // which element gets which class; the render tests read the *word* and would
    // stay green with either ternary inverted — active accounts painted in the
    // destructive fill, the deactivated one rendering as ordinary.
    stubList([ADMIN, DEACTIVATED]);
    renderScreen();

    await screen.findByRole('table');

    const active = rowFor(ADMIN.name).className.split(' ');
    const off = rowFor(DEACTIVATED.name).className.split(' ');

    // Every row carries the shared `data-table-row` treatment; the deactivated
    // one adds the muting variant on top of it rather than replacing it.
    expect(active).toContain(styles.row);
    expect(active).not.toContain(styles.deactivatedRow);
    expect(off).toContain(styles.row);
    expect(off).toContain(styles.deactivatedRow);

    expect(screen.getByText('Active').className).toBe(styles.statusActive);
    expect(screen.getByText('Deactivated').className).toBe(styles.statusOff);
    expect(screen.getByText('Administrator').className).toBe(styles.roleAdmin);
    expect(screen.getByText('Staff').className).toBe(styles.roleStaff);
  });

  it('marks a deactivated account with the word, not only a colour', async () => {
    // EXPERIENCE.md's accessibility floor: the distinction is never colour-only.
    // A class assertion would pass while the badge rendered blank, which is
    // exactly the failure the floor exists to stop.
    stubList([ADMIN, DEACTIVATED]);
    renderScreen();

    await screen.findByRole('table');

    expect(within(rowFor(DEACTIVATED.name)).getByText('Deactivated')).toBeTruthy();
    expect(within(rowFor(ADMIN.name)).getByText('Active')).toBeTruthy();
  });

  it('shows a deactivated account rather than hiding it', async () => {
    // FR-10: "a deactivated user is visually distinct, no separate screen needed"
    // — which needs the row on the list, not filtered off it.
    stubList([DEACTIVATED]);
    renderScreen();

    await screen.findByRole('table');

    expect(screen.getByText(DEACTIVATED.name)).toBeTruthy();
  });

  it('reads Never where the account has never signed in', async () => {
    stubList([UNCLAIMED]);
    renderScreen();

    await screen.findByRole('table');

    expect(within(rowFor(UNCLAIMED.name)).getByText('Never')).toBeTruthy();
  });

  it('renders a last login that exists', async () => {
    stubList([ADMIN]);
    renderScreen();

    await screen.findByRole('table');
    const row = rowFor(ADMIN.name);

    expect(within(row).queryByText('Never')).toBeNull();
    expect(row.textContent).toContain(new Date(ADMIN.last_login_at ?? '').toLocaleString());
  });
});

// --- FR-4's lock, rendered ----------------------------------------------------

describe('the lock', () => {
  it('shows on the account’s status while it holds', async () => {
    stubList([LOCKED]);
    renderScreen();

    await screen.findByRole('table');

    expect(within(rowFor(LOCKED.name)).getByText(/^locked until /i)).toBeTruthy();
  });

  it('is beside the status badge, never instead of it', async () => {
    // Being locked is not a third status: the account is still active, and an
    // Administrator reading this row has to be told both things.
    stubList([LOCKED]);
    renderScreen();

    await screen.findByRole('table');
    const row = within(rowFor(LOCKED.name));

    expect(row.getByText('Active')).toBeTruthy();
    expect(row.getByText(/^locked until /i)).toBeTruthy();
  });

  it('is gone once it has lapsed', async () => {
    // `shared_schema`'s own rule: the column is never cleared, so a value in the
    // past is history rather than state, and a client that renders it as a lock
    // is reading it wrong.
    stubList([LOCK_LAPSED]);
    renderScreen();

    await screen.findByRole('table');

    expect(screen.queryByText(/^locked until /i)).toBeNull();
  });

  it('says nothing at all for an account that has never been locked', async () => {
    stubList([ADMIN]);
    renderScreen();

    await screen.findByRole('table');

    expect(screen.queryByText(/locked/i)).toBeNull();
  });
});

// --- Failures -----------------------------------------------------------------

describe('a failed load', () => {
  it('carries the API’s own sentence in one alert, with no table beside it', async () => {
    // A list of "who has access" missing rows is worse than no list: the row
    // somebody opened the screen to find is exactly the one that would be gone.
    stubFetch({
      '/api/admin/users': [refusal('administrator_required', 'Only an Administrator can do this.', 403)],
    });
    renderScreen();

    const alerts = await screen.findAllByRole('alert');

    expect(alerts).toHaveLength(1);
    expect(alerts[0]?.textContent).toBe('Only an Administrator can do this.');
    expect(screen.queryByRole('table')).toBeNull();
  });

  it('renders nothing from a body it could not understand', async () => {
    // `asUsers` refuses an array with one malformed element, so a
    // partially-understood roster is never rendered as an authoritative answer.
    stubFetch({ '/api/admin/users': [{ status: 200, body: [ADMIN, { name: 'Somebody' }] }] });
    renderScreen();

    await screen.findByRole('alert');

    expect(screen.queryByRole('table')).toBeNull();
    expect(screen.queryByText(ADMIN.name)).toBeNull();
  });

  it('refuses a body that is not an array at all', async () => {
    stubFetch({ '/api/admin/users': [{ status: 200, body: ADMIN }] });
    renderScreen();

    await screen.findByRole('alert');

    expect(screen.queryByRole('table')).toBeNull();
  });

  it('words a failure that is not an ApiRequestError itself', async () => {
    // Nothing the API can send produces this — every refusal and every network
    // failure arrives as an `ApiRequestError`. It stands in for the platform
    // doing something `apiRequest` does not model, and the screen must still say
    // something rather than render a blank panel forever.
    vi.stubGlobal('fetch', () => Promise.resolve(null));
    renderScreen();

    const alert = await screen.findByRole('alert');

    expect(alert.textContent).toMatch(/could not be loaded/i);
  });

  it('words a 401 from the server’s own sentence, like any other refusal', async () => {
    // What this component does in isolation, written down. *Inside the app* this
    // alert is never seen: `apiRequest` notifies the unauthorized observer before
    // it rejects, and `SessionProvider` answers that by dropping the shell to the
    // login screen — but nothing in `UserListScreen` arranges that, and a comment
    // claiming the case cannot arise would be describing the app rather than the
    // file it sits in.
    stubFetch({ '/api/admin/users': [refusal('unauthorized', 'Not signed in.', 401)] });
    renderScreen();

    const alert = await screen.findByRole('alert');

    expect(alert.textContent).toBe('Not signed in.');
    expect(screen.queryByRole('table')).toBeNull();
  });

  it('refetches on Try again and replaces the alert with the table', async () => {
    const { calls } = stubFetch({
      '/api/admin/users': [
        refusal('internal_error', 'Something went wrong.', 500),
        { status: 200, body: [ADMIN] },
      ],
    });
    renderScreen();

    await screen.findByRole('alert');

    fireEvent.click(screen.getByRole('button', { name: /^try again$/i }));

    expect(await screen.findByRole('table')).toBeTruthy();
    expect(screen.queryByRole('alert')).toBeNull();
    expect(screen.getByText(ADMIN.name)).toBeTruthy();
    await waitFor(() => {
      expect(calls.filter(([path]) => path === '/api/admin/users')).toHaveLength(2);
    });
  });

  it('leaves the reader on the screen when Try again removes itself', async () => {
    // The press unmounts the control that was pressed — the failure block is
    // replaced by the in-flight line — and a browser answers that by dropping
    // focus to `<body>`. A keyboard or screen-reader Administrator would then be
    // several tabs above the screen they just acted on, which is why the heading
    // takes focus first. jsdom moves focus for real, so this is observable.
    stubFetch({
      '/api/admin/users': [
        refusal('internal_error', 'Something went wrong.', 500),
        { status: 200, body: [ADMIN] },
      ],
    });
    renderScreen();

    await screen.findByRole('alert');

    fireEvent.click(screen.getByRole('button', { name: /^try again$/i }));

    expect(document.activeElement).toBe(screen.getByRole('heading', { name: 'Users' }));
    expect(document.activeElement).not.toBe(document.body);
  });

  it('offers Try again only while there is something to retry', async () => {
    stubList([ADMIN]);
    renderScreen();

    await screen.findByRole('table');

    expect(screen.queryByRole('button', { name: /^try again$/i })).toBeNull();
  });
});

// --- Two requests open at once -------------------------------------------------

describe('a stale answer', () => {
  it('never overwrites a newer one', async () => {
    // StrictMode mounts, tears down and mounts again, so two reads of the
    // collection are open at the same time and the *first* is the stale one.
    // Settled last, it must not replace what the second returned — which is the
    // whole job of the screen's generation counter. Delete the counter and this
    // test renders yesterday's roster over today's.
    const { settle, calls } = stubDeferred();
    render(
      <UserListScreen
        onAddUser={(): void => undefined}
        onBack={(): void => undefined}
        onEditUser={(): void => undefined}
      />,
      { wrapper: StrictMode },
    );

    // Asserted before anything else, so the test fails loudly rather than
    // passing vacuously if the effect ever stops running twice.
    await waitFor(() => {
      expect(calls).toHaveLength(2);
    });

    // The current request answers first, then the abandoned one.
    settle(1, { status: 200, body: [ADMIN] });
    await screen.findByText(ADMIN.name);

    settle(0, { status: 200, body: [DEACTIVATED] });

    await waitFor(() => {
      expect(screen.getByText(ADMIN.name)).toBeTruthy();
    });
    expect(screen.queryByText(DEACTIVATED.name)).toBeNull();
  });

  it('is dropped rather than written to a screen that has gone', async () => {
    // The `live`-flag case the counter generalises: the request outlives the
    // screen. React makes a late `setState` on an unmounted component a silent
    // no-op, so this cannot fail today by rendering anything — it fails if the
    // late write starts producing a console error again, which is how React
    // reported exactly this mistake before 18 and how a concurrent-mode change
    // would report it next.
    const complaints = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    const { settle } = stubDeferred();
    const { unmount } = renderScreen();

    unmount();
    settle(0, { status: 200, body: [ADMIN] });
    await waitFor(() => {
      expect(complaints).not.toHaveBeenCalled();
    });

    expect(screen.queryByText(ADMIN.name)).toBeNull();
    complaints.mockRestore();
  });
});

// --- The empty list -----------------------------------------------------------

describe('an empty list', () => {
  it('says so rather than showing a bare header', async () => {
    // Unreachable in the product — the caller is themselves a row — but a header
    // row with nothing under it reads as a screen that failed.
    stubList([]);
    renderScreen();

    expect(await screen.findByText(/^no users\.$/i)).toBeTruthy();
    expect(screen.queryByRole('table')).toBeNull();
    expect(screen.queryByRole('alert')).toBeNull();
  });
});

// --- The controls -------------------------------------------------------------

describe('the controls', () => {
  it('hands Add user and Back straight to their props', async () => {
    const onBack = vi.fn();
    const onAddUser = vi.fn();
    stubList([ADMIN]);
    renderScreen({ onBack, onAddUser });

    await screen.findByRole('table');

    fireEvent.click(screen.getByRole('button', { name: /add user/i }));
    fireEvent.click(screen.getByRole('button', { name: /^back$/i }));

    expect(onAddUser).toHaveBeenCalledTimes(1);
    expect(onBack).toHaveBeenCalledTimes(1);
  });

  it('gives a row exactly three controls, and nothing else has appeared', async () => {
    // Retargeted by Story 1.11 rather than deleted, as Story 1.10 retargeted it
    // before: the two verbs this test used to assert the *absence* of now exist,
    // so it becomes the statement of exactly which controls a row carries.
    //
    // Asserted over the rendered control names rather than by eye, so a fourth
    // verb, a row-end menu or a bulk-select column added later fails here. The
    // order is the visual order — Edit, then the state verb, then Delete — with
    // Activate standing in for Deactivate on the deactivated row, so the Actions
    // column holds three controls whatever state a row is in.
    //
    // **The lockout is the absence that is still real.** No control anywhere in
    // the product ends a lock early: no story in Epic 1 owns an admin unlock at
    // all (DW-64), and deleting an account deliberately does not clear its
    // counter either.
    stubList([ADMIN, STAFF, DEACTIVATED, LOCKED]);
    renderScreen();

    await screen.findByRole('table');
    const names = screen.getAllByRole('button').map((control) => control.textContent ?? '');

    expect(names).toEqual([
      '+ Add user',
      'Back',
      'Edit',
      'Deactivate',
      'Delete',
      'Edit',
      'Deactivate',
      'Delete',
      'Edit',
      'Activate',
      'Delete',
      'Edit',
      'Deactivate',
      'Delete',
    ]);
    for (const verb of [/unlock/i, /remove/i, /password/i, /reset/i, /suspend/i]) {
      expect(screen.queryByRole('button', { name: verb })).toBeNull();
    }
    expect(screen.queryByRole('link')).toBeNull();
    expect(screen.queryByRole('menuitem')).toBeNull();
    expect(screen.queryByRole('checkbox')).toBeNull();
    // Nothing is open until something is pressed: the dialog is a response to a
    // press, never part of the screen's resting state.
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('gives every row one Edit control, named for the person it belongs to', async () => {
    // EXPERIENCE.md line 71: a row-end action is labelled, never a bare icon.
    // The *accessible* name carries the person, because "Edit" read four times
    // out of context says nothing about which account is about to change.
    stubList([ADMIN, STAFF, DEACTIVATED]);
    renderScreen();

    await screen.findByRole('table');

    for (const user of [ADMIN, STAFF, DEACTIVATED]) {
      const control = within(rowFor(user.name)).getByRole('button', {
        name: `Edit ${user.name}`,
      });
      expect(control.tagName).toBe('BUTTON');
      expect(control.textContent).toBe('Edit');
    }
  });

  it('hands the pressed row straight to onEditUser', async () => {
    // The row object, not an id: the edit screen is pre-filled from what the
    // list already holds, which is why the product serves no
    // `GET /admin/users/{id}`.
    const onEditUser = vi.fn();
    stubList([ADMIN, STAFF]);
    renderScreen({ onEditUser });

    await screen.findByRole('table');
    fireEvent.click(screen.getByRole('button', { name: `Edit ${STAFF.name}` }));

    expect(onEditUser).toHaveBeenCalledTimes(1);
    expect(onEditUser).toHaveBeenCalledWith(STAFF);
  });

  it('keeps the Edit control out of the row element itself', async () => {
    // A `<tr>` with an `onClick` takes no focus, announces nothing, and puts a
    // click target under text an Administrator may be trying to select. The
    // control is the button; the row is still a row.
    //
    // **Asserted by clicking the row**, not by reading an `onclick` attribute:
    // React attaches handlers through its own synthetic event system and emits
    // no such attribute, so `<tr onClick={...}>` would satisfy an attribute
    // check unchanged — a guard that can never fail.
    const onEditUser = vi.fn();
    stubList([ADMIN]);
    renderScreen({ onEditUser });

    await screen.findByRole('table');
    const row = rowFor(ADMIN.name);

    fireEvent.click(row);
    expect(onEditUser).not.toHaveBeenCalled();

    // And nothing on the row pretends to be a control.
    expect(row.getAttribute('tabindex')).toBeNull();
    // `role="row"` is the row's own implicit role, restated so the reflow to
    // cards below `--breakpoint-md` keeps the table's semantics. It is never
    // a control's role: no button, no link, nothing focusable.
    expect(row.getAttribute('role')).toBe('row');
  });

  it('leaves the role and status badges display-only', async () => {
    // EXPERIENCE.md line 66: a badge is never a tap target and never a button.
    stubList([ADMIN, DEACTIVATED]);
    renderScreen();

    await screen.findByRole('table');

    for (const label of ['Administrator', 'Staff', 'Active', 'Deactivated']) {
      const badge = screen.queryByText(label);
      if (badge === null) continue;
      expect(badge.tagName).toBe('SPAN');
      expect(badge.getAttribute('role')).toBeNull();
      expect(badge.closest('button')).toBeNull();
    }
  });

  it('offers no search box, sort control or pagination', async () => {
    // FR-10 is every account, and FR-18's search is catalogue search (Epic 2). A
    // filter on the surface whose job is "who has access" hides the row somebody
    // opened it to find.
    stubList([ADMIN, STAFF]);
    renderScreen();

    await screen.findByRole('table');

    expect(screen.queryByRole('textbox')).toBeNull();
    expect(screen.queryByRole('searchbox')).toBeNull();
    expect(screen.queryByRole('combobox')).toBeNull();
    expect(screen.queryAllByRole('columnheader').every((cell) => cell.querySelector('button') === null)).toBe(true);
  });
});

// --- The table’s own container ------------------------------------------------

describe('the table at phone width', () => {
  it('sits in a labelled region a keyboard can scroll', async () => {
    // One `<table>` at every width, so every cell keeps its column-header
    // association; the container takes the overflow and takes focus, so the last
    // column is reachable without a mouse and the page never scrolls sideways.
    stubList([ADMIN]);
    renderScreen();

    await screen.findByRole('table');
    const region = screen.getByRole('region');

    expect(region.getAttribute('tabindex')).toBe('0');
    expect(region.getAttribute('aria-labelledby')).toBe(
      screen.getByRole('heading', { name: /^users$/i }).id,
    );
  });

  it('keeps every cell associated with its column header', async () => {
    stubList([ADMIN]);
    renderScreen();

    await screen.findByRole('table');

    for (const header of screen.getAllByRole('columnheader')) {
      expect(header.getAttribute('scope')).toBe('col');
    }
  });
});
