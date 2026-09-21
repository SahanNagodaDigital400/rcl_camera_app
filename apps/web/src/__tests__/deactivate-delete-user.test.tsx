/**
 * Deactivate, activate and delete — the row-end verbs and the product's first modal (FR-13).
 *
 * Two halves, driven through two different roots, the way `edit-user.test.tsx`
 * splits its own. The screen's behaviour runs against a stubbed `fetch` with
 * `UserListScreen` rendered directly, because it calls `apiRequest` itself
 * rather than going through `SessionProvider`; what happens to the *shell* when
 * an Administrator deactivates themselves runs through `App`, because the
 * unauthorized observer and the section state both live in the gate.
 *
 * `user-list.test.tsx` owns the list: which columns exist, what a badge says,
 * and that a row carries exactly three controls. This file owns what pressing
 * one does — the dialog, its copy, its two states, the request, and the row
 * changing without a reload.
 *
 * The assertions here that nothing else in the suite can make:
 *
 * * **The dialog is a pre-flight refusal on the last active Administrator**
 *   (EXPERIENCE.md:148) — it opens with no destructive control at all and sends
 *   no request. The server refuses the same operation independently, which is
 *   `apps/api/tests/test_deactivate_user.py`'s and `test_delete_user.py`'s
 *   claim; this is the one that says the Administrator is never walked through
 *   a confirm that was never going to be honoured.
 * * **Nothing is written until Confirm.** Cancel, `Escape` and a scrim click
 *   each close the dialog having made no request, and each put focus back on
 *   the control that opened it.
 * * **A `409` from a stale list lands in the open dialog**, carrying the API's
 *   own sentence, rather than replacing the table or being swallowed.
 */
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { StrictMode } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import App from '../App';
import { LAST_ADMINISTRATOR, USER_NOT_FOUND } from '../api/client';
import { UserListScreen } from '../screens/UserListScreen';
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

/** A second Administrator, so the floor never refuses what a test is about. */
const SECOND_ADMIN: User = {
  ...ADMIN,
  id: 'b41d8e06-5a72-4f39-9c88-0d3e1f7a2b65',
  name: 'Nadeesha Silva',
  email: 'nadeesha@rocell.lk',
};

const STAFF: User = {
  ...ADMIN,
  id: '3f1a6b2c-9d4e-4f70-8a11-5c2e7b9d0a34',
  name: 'Kasun Perera',
  email: 'kasun@rocell.lk',
  role: 'staff',
};

/** Deactivated, and therefore carrying Activate where the others carry Deactivate. */
const DEACTIVATED: User = {
  ...STAFF,
  id: '7b2c4d1e-8a35-4c62-9f04-1e5a3b7d2c98',
  name: 'Amal Perera',
  email: 'amal@rocell.lk',
  active: false,
};

const LIST = '/api/admin/users';
const DEACTIVATE_STAFF = `/api/admin/users/${STAFF.id}/deactivate`;
const ACTIVATE_DEACTIVATED = `/api/admin/users/${DEACTIVATED.id}/activate`;
const DELETE_STAFF = `/api/admin/users/${STAFF.id}`;

/**
 * `api/users.py`'s `LAST_ACTIVE_ADMINISTRATOR` and `NO_SUCH_USER`, character for
 * character.
 *
 * Restated rather than imported because nothing crosses that boundary at build
 * time. On its own that would be one TypeScript literal compared against
 * another, which is the failure `error-code-parity.test.ts` exists to prevent —
 * so the chain is closed at the other end: that file pins
 * `UserListScreen`'s `LAST_ACTIVE_ADMINISTRATOR` against the Python constant of
 * the same name, and the pre-flight assertions below compare *what the screen
 * renders* against the literal here. Reword either side and one of the two
 * fails.
 *
 * `NO_SUCH_USER` is only ever rendered from an envelope the stub supplies, so
 * it is a fixture rather than a claim about the server's copy.
 */
const LAST_ACTIVE_ADMINISTRATOR =
  'There must always be at least one active Administrator. ' +
  'Make somebody else an Administrator, or activate one, first.';
const NO_SUCH_USER = 'That user no longer exists. Reload the list.';

interface Reply {
  status: number;
  body?: unknown;
}

/**
 * Replace `fetch` with a queue keyed by **method and path**, and record every call.
 *
 * `edit-user.test.tsx`'s harness: the method is part of the key because
 * `GET /api/admin/users` and `DELETE /api/admin/users/<id>` are different
 * routes on paths that differ only by a segment, and every test here walks from
 * the list to a verb and back to the list.
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

/** The list as the API answers it, one reply per call in order. */
function stubList(...lists: (readonly User[])[]): Record<string, Reply[]> {
  return { [`GET ${LIST}`]: lists.map((users) => ({ status: 200, body: users })) };
}

/**
 * The screen on its own, optionally under `StrictMode`.
 *
 * `main.tsx` mounts the whole app inside `StrictMode`, which in development
 * mounts every component, tears it down and mounts it again in one go. That is
 * not a detail for a component whose effects move focus: the teardown runs
 * `ConfirmDialog`'s restore, so the remount has to move focus in again. Every
 * other test here renders without it, because the wrapper doubles every fetch
 * and would say nothing about the behaviour under test.
 */
function renderScreen(wrapper?: typeof StrictMode): void {
  render(
    <UserListScreen
      onAddUser={(): void => undefined}
      onBack={(): void => undefined}
      onEditUser={(): void => undefined}
    />,
    wrapper === undefined ? undefined : { wrapper },
  );
}

/** The row a person's name is in, so a cell assertion cannot read another row's. */
function rowFor(name: string): HTMLElement {
  const cell = screen.getByText(name);
  const row = cell.closest('tr');
  expect(row, `${name} is not in a table row`).toBeTruthy();
  return row as HTMLElement;
}

function control(verb: string, user: User): HTMLElement {
  return within(rowFor(user.name)).getByRole('button', { name: `${verb} ${user.name}` });
}

/** Every request that was not the list itself. */
function writes(calls: readonly [string, RequestInit][]): [string, RequestInit][] {
  return calls.filter(([path, init]) => !(path === LIST && (init.method ?? 'GET') === 'GET'));
}

async function openList(replies: Record<string, Reply[]>): Promise<{
  calls: [string, RequestInit][];
}> {
  const stub = stubFetch(replies);
  renderScreen();
  await screen.findByRole('table');
  return stub;
}

/**
 * A `fetch` that answers the list at once and holds every *write* open.
 *
 * `stubFetch` above answers immediately and in order, which is enough for every
 * behavioural case and cannot express the one the freeze exists for: a request
 * that is genuinely still in flight while the screen is inspected. The settler
 * is kept on an object rather than in a `let` because TypeScript does not know
 * the promise executor runs synchronously, and a plain binding narrows to
 * `undefined` at every call site after it.
 */
function stubHeldWrite(users: readonly User[]): {
  settle: (reply: Reply) => void;
  writes: () => number;
} {
  const settlers: ((reply: Reply) => void)[] = [];
  const held = { count: 0 };

  vi.stubGlobal('fetch', (input: string, init: RequestInit = {}) => {
    if (input === LIST && (init.method ?? 'GET') === 'GET') {
      return Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve(users),
      } as Response);
    }
    held.count += 1;
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
    settle: (reply) => {
      for (const settler of settlers) settler(reply);
    },
    writes: () => held.count,
  };
}

/** The dialog's own confirm control, whatever verb it is confirming. */
function dialogConfirm(verb: RegExp): HTMLButtonElement {
  return within(screen.getByRole('dialog')).getByRole('button', {
    name: verb,
  }) as HTMLButtonElement;
}

// --- The dialog the destructive verbs open ------------------------------------

describe('the confirmation dialog', () => {
  it('opens naming the person and the consequence, never a bare “Are you sure?”', async () => {
    // EXPERIENCE.md:56, :72 and :144. The heading names the object; the body
    // says what it costs — and the deactivation's cost is the one that is not
    // obvious, because it lands on a session that is open right now.
    await openList(stubList([ADMIN, STAFF]));

    fireEvent.click(control('Deactivate', STAFF));

    const dialog = screen.getByRole('dialog');
    expect(within(dialog).getByRole('heading').textContent).toBe(`Deactivate ${STAFF.name}?`);
    expect(dialog.textContent).toMatch(new RegExp(STAFF.name));
    expect(dialog.textContent).toMatch(/signed out immediately/i);
    expect(dialog.textContent).not.toMatch(/are you sure/i);
  });

  it('says what a delete costs, including that the address is freed', async () => {
    await openList(stubList([ADMIN, STAFF]));

    fireEvent.click(control('Delete', STAFF));

    const dialog = screen.getByRole('dialog');
    expect(within(dialog).getByRole('heading').textContent).toBe(`Delete ${STAFF.name}?`);
    expect(dialog.textContent).toMatch(/cannot be restored/i);
    expect(dialog.textContent).toMatch(new RegExp(STAFF.email));
    // The *body* names the person, not only the heading: the body is what
    // `aria-describedby` points at, and both verbs owe the same sentence shape.
    const body = document.getElementById(dialog.getAttribute('aria-describedby') ?? '');
    expect(body?.textContent).toContain(STAFF.name);
    // Read as a sentence, not only for its keywords. This is the one sentence
    // an Administrator reads before an irreversible write, and an earlier
    // draft — "Any session Kasun Perera has ends immediately" — sent the
    // reader down the garden path at "has ends" before they recovered.
    expect(dialog.textContent).toContain('Any session they have open ends immediately');
  });

  it('is a labelled, described, modal dialog', async () => {
    // The four attributes a hand-rolled modal owes a screen reader, since this
    // product cannot use `<dialog>`/`showModal()` — jsdom does not implement
    // it, so the native element would be untestable here.
    await openList(stubList([ADMIN, STAFF]));

    fireEvent.click(control('Deactivate', STAFF));
    const dialog = screen.getByRole('dialog');

    expect(dialog.getAttribute('aria-modal')).toBe('true');
    const labelId = dialog.getAttribute('aria-labelledby');
    const describedId = dialog.getAttribute('aria-describedby');
    expect(document.getElementById(labelId ?? '')?.textContent).toBe(
      `Deactivate ${STAFF.name}?`,
    );
    expect(document.getElementById(describedId ?? '')?.textContent).toMatch(/signed out/i);
  });

  it('carries the destructive verb as a word, not as a colour alone', async () => {
    // EXPERIENCE.md:111. The confirm control says "Delete", never "Yes" or
    // "OK" — which is the half of the signal that survives a monochrome screen.
    await openList(stubList([ADMIN, STAFF]));

    fireEvent.click(control('Delete', STAFF));
    const dialog = screen.getByRole('dialog');

    expect(within(dialog).getByRole('button', { name: /^delete$/i })).toBeTruthy();
    expect(within(dialog).getByRole('button', { name: /^cancel$/i })).toBeTruthy();
    expect(within(dialog).queryByRole('button', { name: /^(yes|ok|confirm)$/i })).toBeNull();
  });

  it('moves focus into itself on open', async () => {
    await openList(stubList([ADMIN, STAFF]));

    fireEvent.click(control('Deactivate', STAFF));

    expect(screen.getByRole('dialog').contains(document.activeElement)).toBe(true);
  });

  it('moves focus into itself on open under StrictMode, which is how the app mounts', async () => {
    // `main.tsx` wraps the app in `StrictMode`, so in development the dialog
    // mounts, is torn down and mounts again before the Administrator sees it.
    // The teardown restores focus to the row-end control that opened it — so
    // without something clearing the "already focused for this state" guard,
    // the remount decides the move is done and the dialog opens with focus
    // behind its own scrim, where neither `Escape` nor the `Tab` trap (both
    // listeners on the scrim) can reach it.
    //
    // Two lists: the wrapper runs the screen's load effect twice.
    stubFetch(stubList([ADMIN, STAFF], [ADMIN, STAFF]));
    renderScreen(StrictMode);
    await screen.findByRole('table');

    // Focused first, because that is the opener the restore has something to
    // give focus back to. A browser focuses a button it is clicked on and a
    // keyboard Administrator arrives on it by `Tab`; `fireEvent.click` does
    // neither, and against `<body>` the restore is skipped and this test would
    // pass without looking at anything.
    const opener = control('Deactivate', STAFF);
    opener.focus();
    fireEvent.click(opener);

    expect(screen.getByRole('dialog').contains(document.activeElement)).toBe(true);
  });

  it('takes focus back when confirming disables the control that held it', async () => {
    // Confirming freezes both controls for the duration of the request, and the
    // one the Administrator just pressed is the one holding focus. A browser
    // answers a disabled focused element by dropping focus to `<body>` — which
    // is outside the scrim, and therefore outside the `Escape` handler and the
    // `Tab` trap both. jsdom does not blur on `disabled`, so the focus has to
    // be placed by hand here for the assertion to mean anything.
    const held = stubHeldWrite([ADMIN, STAFF]);
    renderScreen();
    await screen.findByRole('table');

    fireEvent.click(control('Delete', STAFF));
    const confirm = dialogConfirm(/^delete$/i);
    confirm.focus();
    expect(document.activeElement).toBe(confirm);

    fireEvent.click(confirm);

    const dialog = screen.getByRole('dialog');
    await waitFor(() => {
      expect(document.activeElement).toBe(dialog);
    });

    held.settle({ status: 204 });
    await waitFor(() => {
      expect(screen.queryByRole('dialog')).toBeNull();
    });
  });

  it('opens only one level deep, and only one at a time', async () => {
    // EXPERIENCE.md:42. Pressing a second row-end verb while a dialog is open
    // must not stack a second dialog over the first.
    await openList(stubList([ADMIN, STAFF, DEACTIVATED]));

    fireEvent.click(control('Deactivate', STAFF));
    fireEvent.click(control('Delete', STAFF));

    expect(screen.getAllByRole('dialog')).toHaveLength(1);
  });

  it('cycles focus between its first and last controls rather than off the page', async () => {
    // The trap. jsdom moves focus on `Tab` for no design, hand-rolled or
    // native, so the handler is simulated — but it is the handler a real
    // browser runs too, and without it Tab walks straight onto the page the
    // scrim exists to make unreachable.
    await openList(stubList([ADMIN, STAFF]));
    fireEvent.click(control('Delete', STAFF));
    const dialog = screen.getByRole('dialog');
    const confirm = within(dialog).getByRole('button', { name: /^delete$/i });
    const cancel = within(dialog).getByRole('button', { name: /^cancel$/i });

    confirm.focus();
    fireEvent.keyDown(confirm, { key: 'Tab', shiftKey: true });
    expect(document.activeElement).toBe(cancel);

    fireEvent.keyDown(cancel, { key: 'Tab' });
    expect(document.activeElement).toBe(confirm);
  });

  it('cycles from the panel itself, in both directions', async () => {
    // The panel holds focus immediately after open, and it is neither the
    // first control nor the last — so without a case of its own, `Shift+Tab`
    // from where the Administrator *starts* walks straight out of the dialog
    // backwards. Forward from the panel enters at the first control.
    await openList(stubList([ADMIN, STAFF]));
    fireEvent.click(control('Delete', STAFF));
    const dialog = screen.getByRole('dialog');
    const confirm = within(dialog).getByRole('button', { name: /^delete$/i });
    const cancel = within(dialog).getByRole('button', { name: /^cancel$/i });
    expect(document.activeElement).toBe(dialog);

    fireEvent.keyDown(dialog, { key: 'Tab', shiftKey: true });
    expect(document.activeElement).toBe(cancel);

    dialog.focus();
    fireEvent.keyDown(dialog, { key: 'Tab' });
    expect(document.activeElement).toBe(confirm);
  });
});

// --- Closing it writes nothing ------------------------------------------------

describe('closing the dialog', () => {
  it.each([
    [
      'Cancel',
      (): void => {
        fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: /cancel/i }));
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
        fireEvent.click(scrim as HTMLElement);
      },
    ],
  ])('%s writes nothing and gives focus back to the control that opened it', async (
    _label,
    close,
  ) => {
    const { calls } = await openList(stubList([ADMIN, STAFF]));
    const opener = control('Deactivate', STAFF);
    opener.focus();
    fireEvent.click(opener);

    close();

    expect(screen.queryByRole('dialog')).toBeNull();
    expect(writes(calls)).toEqual([]);
    // The row is where the Administrator was, and it is where they are left.
    expect(document.activeElement).toBe(control('Deactivate', STAFF));
  });

  it('is not dismissed by a click that landed inside the panel', async () => {
    // A click on the panel bubbles out to the scrim, which is the dismiss
    // target. Only the scrim *itself* closes it.
    await openList(stubList([ADMIN, STAFF]));
    fireEvent.click(control('Deactivate', STAFF));

    fireEvent.click(screen.getByRole('dialog'));

    expect(screen.getByRole('dialog')).toBeTruthy();
  });

  it('is not dismissed by a drag that started inside the panel and ended outside it', async () => {
    // The gesture the check above cannot see, and the one an Administrator
    // actually makes: dragging to select the person's name in the body and
    // releasing past the panel's edge. `click` is dispatched on the nearest
    // common ancestor of the press and the release — the scrim — so its
    // `target` is the scrim and a target-only guard dismisses the dialog
    // mid-read. Only where the press began separates the two.
    await openList(stubList([ADMIN, STAFF]));
    fireEvent.click(control('Deactivate', STAFF));
    const dialog = screen.getByRole('dialog');
    const scrim = dialog.parentElement as HTMLElement;

    // The body, by the id the dialog is described by: the heading names the
    // person too, and the body is where the text being selected is.
    const body = document.getElementById(dialog.getAttribute('aria-describedby') ?? '');
    expect(body?.textContent, 'the dialog body names the person').toContain(STAFF.name);

    fireEvent.mouseDown(body as HTMLElement);
    fireEvent.click(scrim);

    expect(screen.getByRole('dialog')).toBeTruthy();

    // And a press that really did begin on the scrim still closes it, so the
    // guard above is not simply "never dismiss".
    fireEvent.mouseDown(scrim);
    fireEvent.click(scrim);

    expect(screen.queryByRole('dialog')).toBeNull();
  });
});

// --- Confirming --------------------------------------------------------------

describe('confirming a deactivation', () => {
  it('fires exactly one request, to the deactivate route, with no body', async () => {
    const { calls } = await openList({
      ...stubList([ADMIN, STAFF], [ADMIN, { ...STAFF, active: false }]),
      [`POST ${DEACTIVATE_STAFF}`]: [{ status: 200, body: { ...STAFF, active: false } }],
    });

    fireEvent.click(control('Deactivate', STAFF));
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: /deactivate/i }));

    await waitFor(() => {
      expect(writes(calls)).toHaveLength(1);
    });
    const [path, init] = writes(calls)[0] ?? ['', {}];
    expect(path).toBe(DEACTIVATE_STAFF);
    expect(init.method).toBe('POST');
    // No request model on the server side, so nothing to send — and the session
    // travels in an HTTP-only cookie, which is the only thing that authenticates
    // this.
    expect(init.body).toBeUndefined();
    expect(init.credentials).toBe('same-origin');
  });

  it('updates the row inline, with no page reload', async () => {
    // EXPERIENCE.md:146. The row comes back from a refetch rather than from a
    // local edit of the array: this list is "who has access", and a copy of it
    // maintained on the client is a second opinion about that.
    await openList({
      ...stubList([ADMIN, STAFF], [ADMIN, { ...STAFF, active: false }]),
      [`POST ${DEACTIVATE_STAFF}`]: [{ status: 200, body: { ...STAFF, active: false } }],
    });

    expect(within(rowFor(STAFF.name)).getByText('Active')).toBeTruthy();

    fireEvent.click(control('Deactivate', STAFF));
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: /deactivate/i }));

    expect(await within(rowFor(STAFF.name)).findByText('Deactivated')).toBeTruthy();
    expect(screen.queryByRole('dialog')).toBeNull();
    // And the row now offers the inverse verb where it offered the destructive
    // one, so the undo is one press away.
    expect(control('Activate', STAFF)).toBeTruthy();
  });

  it('freezes every row’s controls, and the dialog’s own, while the request is open', async () => {
    // One verb can be in flight at a time, so a control left enabled on
    // another row would be a control that does nothing when pressed, with no
    // feedback saying why. The dialog's confirm goes with them: it is the
    // control most likely to be pressed twice.
    const held = stubHeldWrite([ADMIN, STAFF]);
    renderScreen();
    await screen.findByRole('table');

    fireEvent.click(control('Deactivate', STAFF));
    fireEvent.click(dialogConfirm(/deactivate/i));

    await waitFor(() => {
      expect((control('Delete', STAFF) as HTMLButtonElement).disabled).toBe(true);
    });
    expect((control('Edit', STAFF) as HTMLButtonElement).disabled).toBe(true);
    // Every other row too, not only the one being acted on.
    expect((control('Delete', ADMIN) as HTMLButtonElement).disabled).toBe(true);
    expect((control('Deactivate', ADMIN) as HTMLButtonElement).disabled).toBe(true);
    expect((control('Edit', ADMIN) as HTMLButtonElement).disabled).toBe(true);
    // And both of the dialog's own controls.
    expect(dialogConfirm(/deactivate/i).disabled).toBe(true);
    expect(
      (within(screen.getByRole('dialog')).getByRole('button', {
        name: /cancel/i,
      }) as HTMLButtonElement).disabled,
    ).toBe(true);

    held.settle({ status: 200, body: { ...STAFF, active: false } });
    await waitFor(() => {
      expect(screen.queryByRole('dialog')).toBeNull();
    });
  });

  it('sends exactly one request when Confirm is pressed twice in one tick', async () => {
    // **The `disabled` attribute is not the whole guard.** Between two presses
    // in two separate tasks React has committed `setPending` and the control
    // really is unpressable — that is the ordinary double-click, and it is
    // covered. Two dispatches inside *one* task are the case it cannot cover:
    // React batches them, nothing re-renders in between, and the second
    // handler runs against a control that is still enabled. Two requests would
    // mean a second answered `404` for a delete that had already succeeded,
    // rendered to the Administrator as a failure for a write that worked.
    //
    // Driven through one `act` scope rather than two `fireEvent` calls
    // precisely because `fireEvent` closes its own scope and flushes: it would
    // reproduce the covered case and not this one.
    const held = stubHeldWrite([ADMIN, STAFF]);
    renderScreen();
    await screen.findByRole('table');

    fireEvent.click(control('Delete', STAFF));
    const confirm = dialogConfirm(/^delete$/i);
    act(() => {
      confirm.click();
      confirm.click();
      confirm.click();
    });

    await waitFor(() => {
      expect(dialogConfirm(/^delete$/i).disabled).toBe(true);
    });
    expect(held.writes()).toBe(1);
  });

  it('is unpressable again by the time a second, separate press arrives', async () => {
    // The ordinary double-click, and the other half of the same guarantee: the
    // commit has landed between the two events, so the control the second
    // press lands on is disabled and its handler never runs.
    const held = stubHeldWrite([ADMIN, STAFF]);
    renderScreen();
    await screen.findByRole('table');

    fireEvent.click(control('Delete', STAFF));
    const confirm = dialogConfirm(/^delete$/i);
    fireEvent.click(confirm);
    fireEvent.click(confirm);

    expect(confirm.disabled).toBe(true);
    expect(held.writes()).toBe(1);
  });

  it('refuses Escape and a scrim click while the request is open', async () => {
    // None of the three ways out cancels the request, so they have to agree:
    // Cancel is disabled, and dismissing by key or by scrim would abandon a
    // write that is already happening — and the dialog would then reappear the
    // moment that write failed and its refusal was rendered into it.
    const held = stubHeldWrite([ADMIN, STAFF]);
    renderScreen();
    await screen.findByRole('table');

    fireEvent.click(control('Delete', STAFF));
    fireEvent.click(dialogConfirm(/^delete$/i));
    await waitFor(() => {
      expect(dialogConfirm(/^delete$/i).disabled).toBe(true);
    });

    fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape' });
    expect(screen.getByRole('dialog')).toBeTruthy();

    const scrim = screen.getByRole('dialog').parentElement;
    fireEvent.click(scrim as HTMLElement);
    expect(screen.getByRole('dialog')).toBeTruthy();

    // And the refusal lands in the dialog the Administrator could not dismiss,
    // rather than in one that reopened under them.
    held.settle(refusal(USER_NOT_FOUND, NO_SUCH_USER, 404));
    expect((await within(screen.getByRole('dialog')).findByRole('alert')).textContent).toBe(
      NO_SUCH_USER,
    );
  });

  it('keeps focus inside the dialog when every control is frozen', async () => {
    // The trap's hardest moment: with both controls disabled there is nothing
    // to cycle between, and a trap that gave up here would let Tab walk onto
    // the page the scrim exists to make unreachable — while a destructive write
    // is actually happening.
    const held = stubHeldWrite([ADMIN, STAFF]);
    renderScreen();
    await screen.findByRole('table');

    fireEvent.click(control('Delete', STAFF));
    fireEvent.click(dialogConfirm(/^delete$/i));
    await waitFor(() => {
      expect(dialogConfirm(/^delete$/i).disabled).toBe(true);
    });

    const dialog = screen.getByRole('dialog');
    // Focus is dropped first, which is what a browser does when the element
    // holding it is disabled. Without that this would assert nothing: focus is
    // already on the panel, so a handler that did nothing at all would look
    // identical to one that put it back.
    (document.activeElement as HTMLElement | null)?.blur();
    expect(document.activeElement).not.toBe(dialog);

    for (const shiftKey of [false, true]) {
      // `fireEvent` answers `false` when the handler called `preventDefault`,
      // which is the half a focus assertion cannot make: jsdom moves focus on
      // `Tab` for nobody, so in a real browser it is the prevented default —
      // not the `focus()` call — that stops the walk onto the page behind the
      // scrim.
      expect(fireEvent.keyDown(dialog, { key: 'Tab', shiftKey })).toBe(false);
      expect(document.activeElement).toBe(dialog);
      (document.activeElement as HTMLElement | null)?.blur();
    }

    held.settle({ status: 204 });
    await waitFor(() => {
      expect(screen.queryByRole('dialog')).toBeNull();
    });
  });
});

describe('confirming a delete', () => {
  it('sends DELETE to the member path and drops the row from the list', async () => {
    const { calls } = await openList({
      ...stubList([ADMIN, STAFF], [ADMIN]),
      [`DELETE ${DELETE_STAFF}`]: [{ status: 204 }],
    });

    fireEvent.click(control('Delete', STAFF));
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: /^delete$/i }));

    await waitFor(() => {
      expect(screen.queryByText(STAFF.name)).toBeNull();
    });
    expect(writes(calls).map(([path, init]) => [path, init.method])).toEqual([
      [DELETE_STAFF, 'DELETE'],
    ]);
    expect(screen.queryByRole('dialog')).toBeNull();
    // `apiRequest` returns null for a 204 rather than trying to parse an empty
    // body, which is why this route can answer with nothing at all.
    expect(screen.getByText(ADMIN.name)).toBeTruthy();
  });

  it('leaves focus on the heading rather than on nothing', async () => {
    // The row that held the control that deleted it has gone, and a browser
    // answers that by dropping focus to `<body>` — several tabs from the screen
    // the Administrator just acted on.
    await openList({
      ...stubList([ADMIN, STAFF], [ADMIN]),
      [`DELETE ${DELETE_STAFF}`]: [{ status: 204 }],
    });

    fireEvent.click(control('Delete', STAFF));
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: /^delete$/i }));

    await waitFor(() => {
      expect(screen.queryByText(STAFF.name)).toBeNull();
    });
    // Retried for the reason the swap test gives: `rescueFocus` is spent in a
    // passive effect, and the row's disappearance — what the wait above sees —
    // is committed before that effect runs.
    await waitFor(() => {
      expect(document.activeElement).toBe(screen.getByRole('heading', { name: /^users$/i }));
    });
  });
});

describe('activating a deactivated account', () => {
  it('fires straight away, with no confirmation dialog', async () => {
    // A confirmation guards a *destructive* action (EXPERIENCE.md's
    // Interaction Primitives). Giving an account its access back is the undo,
    // not the damage, so asking about it would be a click for nothing.
    const { calls } = await openList({
      ...stubList([ADMIN, DEACTIVATED], [ADMIN, { ...DEACTIVATED, active: true }]),
      [`POST ${ACTIVATE_DEACTIVATED}`]: [{ status: 200, body: { ...DEACTIVATED, active: true } }],
    });

    fireEvent.click(control('Activate', DEACTIVATED));

    expect(screen.queryByRole('dialog')).toBeNull();
    expect(await within(rowFor(DEACTIVATED.name)).findByText('Active')).toBeTruthy();
    expect(writes(calls).map(([path, init]) => [path, init.method])).toEqual([
      [ACTIVATE_DEACTIVATED, 'POST'],
    ]);
  });

  it('reports a failure in a refusal dialog headed for the verb that failed', async () => {
    // Activate is the one verb with no confirmation step, which makes the
    // refusal dialog the *only* thing that can report it failing — this screen
    // has no page-level alert slot for a row verb. Narrow `run`'s catch to skip
    // `activate` and the row silently keeps reading Deactivated with nothing
    // saying why; take the `activate` arm out of `refusalHeading` and the
    // dialog that does appear is headed "Cannot deactivate …" over an
    // activation. Neither mutation fails anything else in the suite.
    await openList({
      ...stubList([ADMIN, DEACTIVATED]),
      [`POST ${ACTIVATE_DEACTIVATED}`]: [refusal(USER_NOT_FOUND, NO_SUCH_USER, 404)],
    });

    fireEvent.click(control('Activate', DEACTIVATED));

    const dialog = await screen.findByRole('dialog');
    expect((await within(dialog).findByRole('alert')).textContent).toBe(NO_SUCH_USER);
    expect(within(dialog).getByRole('heading').textContent).toBe(
      `Cannot activate ${DEACTIVATED.name}`,
    );
    // The refusal state and no other: nothing to press but Close.
    expect(within(dialog).getAllByRole('button').map((button) => button.textContent)).toEqual([
      'Close',
    ]);
  });
});

// --- The floor ----------------------------------------------------------------

describe('the last active Administrator', () => {
  it.each(['Deactivate', 'Delete'])(
    '%s opens the dialog as a refusal, with no destructive control and no request',
    async (verb) => {
      // EXPERIENCE.md:148, in as many words: "the confirmation dialog itself is
      // replaced by a refusal message stating why (FR-13), and no destructive
      // action fires." Computed from the list already in hand — the only place
      // the answer can come from before a request is made.
      const { calls } = await openList(stubList([ADMIN, STAFF, DEACTIVATED]));

      fireEvent.click(control(verb, ADMIN));

      const dialog = screen.getByRole('dialog');
      expect(within(dialog).getByRole('alert').textContent).toBe(LAST_ACTIVE_ADMINISTRATOR);
      expect(within(dialog).queryByRole('button', { name: new RegExp(`^${verb}$`, 'i') })).toBeNull();
      // One control, and it is the way out.
      expect(within(dialog).getAllByRole('button').map((b) => b.textContent)).toEqual(['Close']);
      expect(writes(calls)).toEqual([]);
    },
  );

  it('names the account the refusal is about', async () => {
    await openList(stubList([ADMIN, STAFF]));

    fireEvent.click(control('Delete', ADMIN));

    expect(
      within(screen.getByRole('dialog')).getByRole('heading').textContent,
    ).toBe(`Cannot delete ${ADMIN.name}`);
  });

  it('does not refuse once a second active Administrator is on the list', async () => {
    // The floor is one survivor, not two — FR-13's own wording. With two
    // Administrators the dialog is an ordinary confirm.
    await openList(stubList([ADMIN, SECOND_ADMIN]));

    fireEvent.click(control('Deactivate', ADMIN));

    const dialog = screen.getByRole('dialog');
    expect(within(dialog).getByRole('button', { name: /^deactivate$/i })).toBeTruthy();
    expect(within(dialog).queryByRole('alert')).toBeNull();
  });

  it('does not count a deactivated Administrator as the survivor', async () => {
    // The server's `other.active` arm, read off the list: a deactivated
    // Administrator is not one of the active Administrators the floor counts.
    await openList(stubList([ADMIN, { ...SECOND_ADMIN, active: false }]));

    fireEvent.click(control('Deactivate', ADMIN));

    expect(within(screen.getByRole('dialog')).getByRole('alert').textContent).toBe(
      LAST_ACTIVE_ADMINISTRATOR,
    );
  });

  it('never refuses a Staff row, whoever else is on the list', async () => {
    await openList(stubList([ADMIN, STAFF]));

    fireEvent.click(control('Delete', STAFF));

    expect(within(screen.getByRole('dialog')).queryByRole('alert')).toBeNull();
  });
});

// --- When the server disagrees with the list ----------------------------------

describe('a refusal that only the server can see', () => {
  it('swaps the open dialog to the refusal state, carrying the API’s own sentence', async () => {
    // The stale list: the client thought a second Administrator was active and
    // the server says otherwise. The dialog stays where the Administrator is
    // looking and renders the `409` verbatim, so the screen can never state a
    // rule the server does not enforce.
    await openList({
      ...stubList([ADMIN, SECOND_ADMIN]),
      [`POST /api/admin/users/${ADMIN.id}/deactivate`]: [
        refusal(LAST_ADMINISTRATOR, LAST_ACTIVE_ADMINISTRATOR, 409),
      ],
    });

    fireEvent.click(control('Deactivate', ADMIN));
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: /deactivate/i }));

    const alert = await within(screen.getByRole('dialog')).findByRole('alert');
    expect(alert.textContent).toBe(LAST_ACTIVE_ADMINISTRATOR);
    expect(
      within(screen.getByRole('dialog')).queryByRole('button', { name: /^deactivate$/i }),
    ).toBeNull();
    // The table is still there: a refused write is not a failed read.
    expect(screen.getByRole('table')).toBeTruthy();
  });

  it('leaves focus inside the dialog after the swap, with Escape still working', async () => {
    // The swap unmounts the control that held focus. Without the component
    // re-focusing its panel, focus falls to `<body>` — which also takes
    // `Escape` with it, because the handler is a listener on the scrim, and
    // leaves a keyboard Administrator with a refusal they cannot dismiss.
    await openList({
      ...stubList([ADMIN, SECOND_ADMIN]),
      [`POST /api/admin/users/${ADMIN.id}/deactivate`]: [
        refusal(LAST_ADMINISTRATOR, LAST_ACTIVE_ADMINISTRATOR, 409),
      ],
    });

    const opener = control('Deactivate', ADMIN);
    opener.focus();
    fireEvent.click(opener);
    const confirm = within(screen.getByRole('dialog')).getByRole('button', {
      name: /deactivate/i,
    });
    // Focused before it is pressed, which is where a keyboard Administrator
    // actually is — and what makes the swap remove the element holding focus.
    // Without that this assertion is vacuous: focus starts on the panel, which
    // survives the swap whether or not anything puts it back.
    confirm.focus();
    expect(document.activeElement).toBe(confirm);
    fireEvent.click(confirm);
    await within(screen.getByRole('dialog')).findByRole('alert');

    expect(confirm.isConnected, 'the confirm control should be gone').toBe(false);
    // Retried rather than sampled once. The focus is put back by a passive
    // effect on the state change, and the wait above observes a DOM mutation —
    // the alert node — which React commits *before* it flushes that effect. On
    // a loaded machine the gap between the two is wide enough to read, so a
    // single `expect` here asserts how fast focus moves rather than where it
    // lands. `waitFor` still fails if it never arrives.
    await waitFor(() => {
      expect(screen.getByRole('dialog').contains(document.activeElement)).toBe(true);
    });

    fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape' });
    expect(screen.queryByRole('dialog')).toBeNull();
    // And the opener the dialog captured before the swap is still the one it
    // gives focus back to — which is why the two states share one instance.
    expect(document.activeElement).toBe(control('Deactivate', ADMIN));
  });

  it('inserts the alert node rather than adding the role to the one already there', async () => {
    // A `role="alert"` added to an element already in the tree is not reliably
    // announced. The two body variants carry distinct keys so React unmounts
    // one and mounts the other, which is asserted here as "not the same node".
    await openList({
      ...stubList([ADMIN, SECOND_ADMIN]),
      [`POST /api/admin/users/${ADMIN.id}/deactivate`]: [
        refusal(LAST_ADMINISTRATOR, LAST_ACTIVE_ADMINISTRATOR, 409),
      ],
    });

    fireEvent.click(control('Deactivate', ADMIN));
    const dialog = screen.getByRole('dialog');
    const before = dialog.querySelector('p');
    expect(before, 'the confirm state renders no body').toBeTruthy();

    fireEvent.click(within(dialog).getByRole('button', { name: /deactivate/i }));
    const alert = await within(screen.getByRole('dialog')).findByRole('alert');

    expect(alert).not.toBe(before);
  });

  it('renders a 404 from a row somebody else already removed', async () => {
    await openList({
      ...stubList([ADMIN, STAFF]),
      [`DELETE ${DELETE_STAFF}`]: [refusal(USER_NOT_FOUND, NO_SUCH_USER, 404)],
    });

    fireEvent.click(control('Delete', STAFF));
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: /^delete$/i }));

    expect((await within(screen.getByRole('dialog')).findByRole('alert')).textContent).toBe(
      NO_SUCH_USER,
    );
  });

  it('renders a sentence rather than a stack for a failure that is not an ApiRequestError', async () => {
    // The fallback for a bug rather than for a reachable state: a body that is
    // not the shared envelope arrives wrapped, and anything else would put a
    // stack-shaped string in front of an Administrator.
    vi.stubGlobal('fetch', (input: string, init: RequestInit = {}) => {
      if (input === LIST && (init.method ?? 'GET') === 'GET') {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: () => Promise.resolve([ADMIN, STAFF]),
        } as Response);
      }
      return Promise.reject(new TypeError('the network went away'));
    });
    render(
      <UserListScreen
        onAddUser={(): void => undefined}
        onBack={(): void => undefined}
        onEditUser={(): void => undefined}
      />,
    );
    await screen.findByRole('table');

    fireEvent.click(control('Delete', STAFF));
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: /^delete$/i }));

    const alert = await within(screen.getByRole('dialog')).findByRole('alert');
    expect(alert.textContent).toBeTruthy();
    expect(alert.textContent).not.toMatch(/TypeError|at Object|stack/i);
  });
});

// --- Through the real gate ----------------------------------------------------

describe('an Administrator who takes away their own access', () => {
  it('lands on the login screen on the next request, with no reload', async () => {
    // The clause nothing else in the suite can make, and the reason
    // `UserListScreen` special-cases nothing: the answer lands, the refetch
    // behind it is a `401`, `apiRequest` notifies the unauthorized observer,
    // and `SessionProvider` drops the shell to Login — the same path an expiry
    // and a revocation from another device already take.
    stubFetch({
      'GET /api/auth/session': [{ status: 200, body: ADMIN }],
      'GET /api/admin/users': [
        { status: 200, body: [ADMIN, SECOND_ADMIN] },
        refusal('unauthorized', 'Sign in to continue.', 401),
      ],
      [`POST /api/admin/users/${ADMIN.id}/deactivate`]: [
        { status: 200, body: { ...ADMIN, active: false } },
      ],
    });
    render(<App />);

    fireEvent.click(await screen.findByRole('button', { name: /^users$/i }));
    fireEvent.click(await screen.findByRole('button', { name: `Deactivate ${ADMIN.name}` }));
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: /deactivate/i }));

    expect(await screen.findByText(/your session has ended/i)).toBeTruthy();
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(screen.queryByRole('table')).toBeNull();
    // The whole shell, not only the table: the app bar and its Sign out go
    // with the session, so there is no admin surface left to be stranded on.
    expect(screen.queryByTestId('app-bar')).toBeNull();
    expect(screen.queryByRole('button', { name: /^sign out$/i })).toBeNull();
  });

  it('lands there for a self-delete too, which takes a different path out', async () => {
    // The same clause for the other verb, and not a duplicate of the test
    // above: a self-delete answers `204` with no body, and `run` sets the
    // delete-only focus rescue before the refetch — so the shell is being torn
    // down while this screen is moving focus to a heading inside it. The
    // acceptance criterion names both verbs; only deactivate was driven at the
    // surface it names.
    stubFetch({
      'GET /api/auth/session': [{ status: 200, body: ADMIN }],
      'GET /api/admin/users': [
        { status: 200, body: [ADMIN, SECOND_ADMIN] },
        refusal('unauthorized', 'Sign in to continue.', 401),
      ],
      [`DELETE /api/admin/users/${ADMIN.id}`]: [{ status: 204 }],
    });
    render(<App />);

    fireEvent.click(await screen.findByRole('button', { name: /^users$/i }));
    fireEvent.click(await screen.findByRole('button', { name: `Delete ${ADMIN.name}` }));
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: /^delete$/i }));

    expect(await screen.findByText(/your session has ended/i)).toBeTruthy();
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(screen.queryByRole('table')).toBeNull();
    expect(screen.queryByTestId('app-bar')).toBeNull();
    expect(screen.queryByRole('button', { name: /^sign out$/i })).toBeNull();
  });

  it('keeps the shell around the list while somebody else is the target', async () => {
    // The control case for the one above: deactivating a colleague changes
    // nothing about the caller's own session, so the screen stays exactly where
    // it was.
    stubFetch({
      'GET /api/auth/session': [{ status: 200, body: ADMIN }],
      'GET /api/admin/users': [
        { status: 200, body: [ADMIN, STAFF] },
        { status: 200, body: [ADMIN, { ...STAFF, active: false }] },
      ],
      [`POST ${DEACTIVATE_STAFF}`]: [{ status: 200, body: { ...STAFF, active: false } }],
    });
    render(<App />);

    fireEvent.click(await screen.findByRole('button', { name: /^users$/i }));
    fireEvent.click(await screen.findByRole('button', { name: `Deactivate ${STAFF.name}` }));
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: /deactivate/i }));

    expect(await within(rowFor(STAFF.name)).findByText('Deactivated')).toBeTruthy();
    expect(screen.getByTestId('app-bar')).toBeTruthy();
    expect(screen.getByRole('button', { name: /^sign out$/i })).toBeTruthy();
    expect(screen.getByRole('heading', { name: /^users$/i })).toBeTruthy();
  });
});
