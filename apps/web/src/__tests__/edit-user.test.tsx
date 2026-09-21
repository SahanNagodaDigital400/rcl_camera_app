/**
 * Edit user — the screen, and the route the app takes to reach it (FR-12).
 *
 * Two halves, deliberately driven through two different roots, the way
 * `create-user.test.tsx` splits its own. The screen's own behaviour runs against
 * a stubbed `fetch` with the screen rendered directly, because it calls
 * `apiRequest` itself rather than going through `SessionProvider`; whether the
 * app *reaches* the screen at all, and what happens to the shell when an
 * Administrator edits themselves, runs through `App` — because the section
 * state, the role reconciler and `adoptUser` all live in the gate.
 *
 * Three assertions here are the ones nothing else in the suite can make: that
 * the body carries **only the fields that changed** — the whole of this story's
 * answer to two Administrators editing one row at once — that Back with unsaved
 * edits warns before it leaves (EXPERIENCE.md line 90, DW-81), and that no
 * control anywhere on this screen deactivates, deletes, unlocks or sets a
 * password, which is Story 1.11's scope and, for the unlock, nobody's (DW-64).
 */
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import App from '../App';
import {
  EMAIL_ALREADY_EXISTS,
  INVALID_EMAIL,
  LAST_ADMINISTRATOR,
  USER_NOT_FOUND,
} from '../api/client';
import { EditUserScreen } from '../screens/EditUserScreen';
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

/** A second Administrator, so a self-demotion is not refused by the floor. */
const SECOND_ADMIN: User = {
  ...ADMIN,
  id: 'b41d8e06-5a72-4f39-9c88-0d3e1f7a2b65',
  name: 'Nadeesha Silva',
  email: 'nadeesha@rocell.lk',
};

const EDIT_PATH = `/api/admin/users/${STAFF.id}`;

/**
 * `NO_SUCH_USER`, `LAST_ACTIVE_ADMINISTRATOR`, `NOT_AN_ADDRESS` and
 * `ADDRESS_ALREADY_IN_USE` in the Python source, character for character.
 *
 * Restated rather than imported because nothing crosses that boundary at build
 * time — `error-code-parity.test.ts` pins the *codes* and not the sentences. If
 * one of these drifts, the API's sentence is still what the screen renders at
 * run time; what stops being true is this file's claim to be asserting it.
 */
const NOT_AN_ADDRESS = 'An email address must have exactly one @ sign, with text on each side.';
const ALREADY_IN_USE = 'A user with that email address already exists.';
const NO_SUCH_USER = 'That user no longer exists. Reload the list.';
const LAST_ACTIVE_ADMINISTRATOR =
  'There must always be at least one active Administrator. ' +
  'Make somebody else an Administrator, or activate one, first.';

interface Reply {
  status: number;
  body?: unknown;
}

/**
 * Replace `fetch` with a queue keyed by **method and path**, and record every call.
 *
 * The method is part of the key for `create-user.test.tsx`'s reason, one path
 * deeper: `GET /api/admin/users` and `PATCH /api/admin/users/<id>` are different
 * routes, and a test that walks from the list to the editor needs both.
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

/** The saved row, as the API answers it. */
function saved(changes: Partial<User>): Reply {
  return { status: 200, body: { ...STAFF, ...changes, updated_at: '2026-09-18T10:00:00Z' } };
}

function renderScreen(
  props: { user?: User; onSaved?: (user: User) => void; onBack?: () => void } = {},
): { onSaved: (user: User) => void; onBack: () => void } {
  const onSaved = props.onSaved ?? ((): void => undefined);
  const onBack = props.onBack ?? ((): void => undefined);
  render(<EditUserScreen onBack={onBack} onSaved={onSaved} user={props.user ?? STAFF} />);
  return { onSaved, onBack };
}

function nameBox(): HTMLInputElement {
  return screen.getByLabelText(/^name$/i) as HTMLInputElement;
}

function emailBox(): HTMLInputElement {
  return screen.getByLabelText(/^email$/i) as HTMLInputElement;
}

function roleBox(): HTMLSelectElement {
  return screen.getByLabelText(/^role$/i) as HTMLSelectElement;
}

function save(): void {
  fireEvent.click(screen.getByRole('button', { name: /^save changes$/i }));
}

function back(): void {
  fireEvent.click(screen.getByRole('button', { name: /^back$/i }));
}

/** The body of the nth request, parsed. */
function bodyOf(calls: [string, RequestInit][], nth = 0): unknown {
  const init = calls[nth]?.[1];
  expect(init, 'no request was made').toBeTruthy();
  return JSON.parse(String(init?.body));
}

// --- The form as it opens -----------------------------------------------------

describe('the form', () => {
  it('opens pre-filled from the row it was given', async () => {
    stubFetch({});
    renderScreen();

    await waitFor(() => {
      expect(nameBox().value).toBe(STAFF.name);
    });
    expect(emailBox().value).toBe(STAFF.email);
    expect(roleBox().value).toBe(STAFF.role);
  });

  it('says whose account is being changed', () => {
    // The screen must never be ambiguous about which row is about to change —
    // the fields themselves are being edited, so they cannot be the answer.
    stubFetch({});
    renderScreen();

    expect(screen.getByText(STAFF.email)).toBeTruthy();
  });

  it('offers both roles in the glossary’s own words, and no third', () => {
    stubFetch({});
    renderScreen();

    const options = within(roleBox())
      .getAllByRole('option')
      .map((option) => option.textContent);

    expect(options).toEqual(['Staff', 'Administrator']);
  });

  it('bounds the fields the way the server bounds them', () => {
    // The mirrored `MAX_*` constants, rendered as `maxLength` so the one refusal
    // this screen cannot act on — the generic 422, which names no field — never
    // has to be shown. `error-code-parity.test.ts` holds each constant to the
    // Python one it mirrors; without that half this compares two TypeScript
    // literals.
    stubFetch({});
    renderScreen();

    expect(nameBox().maxLength).toBe(200);
    expect(emailBox().maxLength).toBe(320);
  });

  it('makes no request of its own on mount', () => {
    // The row is already in hand — the list passed it — which is why the product
    // serves no `GET /admin/users/{id}` for this screen to call.
    const { calls } = stubFetch({});
    renderScreen();

    expect(calls).toEqual([]);
  });
});

// --- What it sends ------------------------------------------------------------

describe('the request', () => {
  it('sends a PATCH to the row’s own path, with the session cookie and JSON', async () => {
    const { calls } = stubFetch({ [`PATCH ${EDIT_PATH}`]: [saved({ name: 'Kasun P.' })] });
    renderScreen();

    fireEvent.change(nameBox(), { target: { value: 'Kasun P.' } });
    save();

    await screen.findByText(/^saved\.$/i);
    const [path, init] = calls[0] ?? ['', {}];
    expect(path).toBe(EDIT_PATH);
    expect(init.method).toBe('PATCH');
    // The session travels in an HTTP-only cookie (AGENTS.md Policy), so the
    // credential mode is the only thing that carries it.
    expect(init.credentials).toBe('same-origin');
    expect(init.headers).toEqual({ 'content-type': 'application/json' });
  });

  it('carries only the field that changed', async () => {
    // The whole of this story's answer to two Administrators editing one row at
    // once: last write wins, but it wins over one field rather than over the
    // whole account. Send all three and the other Administrator's rename is
    // silently reverted by somebody who only touched the role.
    const { calls } = stubFetch({ [`PATCH ${EDIT_PATH}`]: [saved({ role: 'admin' })] });
    renderScreen();

    fireEvent.change(roleBox(), { target: { value: 'admin' } });
    save();

    await screen.findByText(/^saved\.$/i);
    expect(bodyOf(calls)).toEqual({ role: 'admin' });
  });

  it('carries every field that changed when several did', async () => {
    const { calls } = stubFetch({
      [`PATCH ${EDIT_PATH}`]: [saved({ name: 'Kasun P.', email: 'kp@rocell.lk', role: 'admin' })],
    });
    renderScreen();

    fireEvent.change(nameBox(), { target: { value: 'Kasun P.' } });
    fireEvent.change(emailBox(), { target: { value: 'kp@rocell.lk' } });
    fireEvent.change(roleBox(), { target: { value: 'admin' } });
    save();

    await screen.findByText(/^saved\.$/i);
    expect(bodyOf(calls)).toEqual({
      name: 'Kasun P.',
      email: 'kp@rocell.lk',
      role: 'admin',
    });
  });

  it('sends nothing at all when nothing was edited', async () => {
    const { calls } = stubFetch({});
    renderScreen();

    save();

    expect(await screen.findByRole('alert')).toHaveProperty(
      'textContent',
      'Nothing has changed.',
    );
    expect(calls).toEqual([]);
  });

  it('sends nothing when the same address is retyped in another case', async () => {
    // The API folds the address in Postgres, so `KASUN@ROCELL.LK` is the same
    // login and the same lockout counter key. Sending it would spend a write and
    // — worse — would look like a rename to the counter carry behind it.
    const { calls } = stubFetch({});
    renderScreen();

    fireEvent.change(emailBox(), { target: { value: '  KASUN@ROCELL.LK  ' } });
    save();

    expect(await screen.findByRole('alert')).toHaveProperty(
      'textContent',
      'Nothing has changed.',
    );
    expect(calls).toEqual([]);
  });

  it('sends nothing when only surrounding space was added to the name', async () => {
    const { calls } = stubFetch({});
    renderScreen();

    fireEvent.change(nameBox(), { target: { value: `  ${STAFF.name}  ` } });
    save();

    await screen.findByRole('alert');
    expect(calls).toEqual([]);
  });

  it('diffs against the server’s answer, not against the row it opened with', async () => {
    // After a save the server's row is the truth. Compared against the original
    // prop, the second Save would send the name again — a write for a change
    // that already landed, and a second `updated_at` for nothing.
    const { calls } = stubFetch({
      [`PATCH ${EDIT_PATH}`]: [saved({ name: 'Kasun P.' }), saved({ role: 'admin' })],
    });
    renderScreen();

    fireEvent.change(nameBox(), { target: { value: 'Kasun P.' } });
    save();
    await screen.findByText(/^saved\.$/i);

    fireEvent.change(roleBox(), { target: { value: 'admin' } });
    save();

    await waitFor(() => {
      expect(calls).toHaveLength(2);
    });
    expect(bodyOf(calls, 1)).toEqual({ role: 'admin' });
  });

  it.each([
    ['name', 'Enter the person’s name.'],
    ['email', 'Enter an email address.'],
  ] as const)(
    'refuses a blank %s here rather than asking the API about it',
    async (field, message) => {
      // Both fields, because both branches exist and only one of them was
      // covered. With no test that empties the email box, deleting its branch
      // ships green and the generic `422 validation_error` reaches the screen
      // instead — the one refusal that names no field, so nothing is marked and
      // nothing is focused.
      const { calls } = stubFetch({});
      renderScreen();

      fireEvent.change(field === 'name' ? nameBox() : emailBox(), { target: { value: '   ' } });
      save();

      const alert = await screen.findByRole('alert');
      expect(alert.textContent).toBe(message);
      expect(calls).toEqual([]);

      const marked = field === 'name' ? nameBox() : emailBox();
      expect(marked.getAttribute('aria-invalid')).toBe('true');
      expect(marked.getAttribute('aria-describedby')).toBe(alert.id);
      expect(document.activeElement).toBe(marked);
    },
  );
});

// --- The save indicator -------------------------------------------------------

describe('the save indicator', () => {
  it('reads Saving… in flight and Saved. afterwards, inline', async () => {
    // EXPERIENCE.md's Save indicator row: `Saving…` → `Saved.`, inline beside the
    // control that triggered it, never a corner toast.
    // Held on an object rather than in a `let`: TypeScript narrows a local
    // assigned only inside a callback to `never` at the call site below, and the
    // holder is the smallest way to keep the assertion honest without an `as`.
    const gate: { settle: (() => void) | null } = { settle: null };
    vi.stubGlobal('fetch', () => {
      return new Promise<Response>((resolve) => {
        gate.settle = (): void =>
          resolve({
            ok: true,
            status: 200,
            json: () => Promise.resolve({ ...STAFF, name: 'Kasun P.' }),
          } as Response);
      });
    });
    renderScreen();

    fireEvent.change(nameBox(), { target: { value: 'Kasun P.' } });
    save();

    const indicator = await screen.findByRole('status');
    expect(indicator.textContent).toBe('Saving…');

    await waitFor(() => {
      expect(gate.settle).not.toBeNull();
    });
    gate.settle?.();

    await waitFor(() => {
      expect(indicator.textContent).toBe('Saved.');
    });
  });

  it('freezes every field while the save is in flight', async () => {
    // The success path replaces all three fields with the server's row, so a
    // field left live during the request is a field whose edits are silently
    // discarded — the Administrator watches their own typing vanish into a
    // `Saved.` that was about something else. Frozen, there is nothing to lose.
    const gate: { settle: (() => void) | null } = { settle: null };
    vi.stubGlobal('fetch', () => {
      return new Promise<Response>((resolve) => {
        gate.settle = (): void =>
          resolve({
            ok: true,
            status: 200,
            json: () => Promise.resolve({ ...STAFF, name: 'Kasun P.' }),
          } as Response);
      });
    });
    renderScreen();

    fireEvent.change(nameBox(), { target: { value: 'Kasun P.' } });
    save();

    await waitFor(() => {
      expect(gate.settle).not.toBeNull();
    });

    for (const control of [nameBox(), emailBox(), roleBox()]) {
      expect(control.disabled).toBe(true);
    }

    gate.settle?.();
    await screen.findByText(/^saved\.$/i);

    // And they come back, so the screen is usable for a second edit.
    for (const control of [nameBox(), emailBox(), roleBox()]) {
      expect(control.disabled).toBe(false);
    }
  });

  it('freezes Save and Back too, so the screen cannot be left mid-save', async () => {
    // The field freeze above is only half of it. Back unmounts this screen, and
    // a press while the request is open drops the response on the floor: no
    // `Saved.`, no refusal, no `onSaved` — a `409 last_administrator` would be
    // discarded entirely and the Administrator would return to a list refetched
    // in a race with a write whose outcome nobody saw.
    const gate: { settle: (() => void) | null } = { settle: null };
    vi.stubGlobal('fetch', () => {
      return new Promise<Response>((resolve) => {
        gate.settle = (): void =>
          resolve({
            ok: true,
            status: 200,
            json: () => Promise.resolve({ ...STAFF, name: 'Kasun P.' }),
          } as Response);
      });
    });
    const onBack = vi.fn();
    renderScreen({ onBack });

    fireEvent.change(nameBox(), { target: { value: 'Kasun P.' } });
    save();

    await waitFor(() => {
      expect(gate.settle).not.toBeNull();
    });

    const saveControl = screen.getByRole('button', { name: /^save changes$/i });
    const backControl = screen.getByRole('button', { name: /^back$/i });
    expect((saveControl as HTMLButtonElement).disabled).toBe(true);
    expect((backControl as HTMLButtonElement).disabled).toBe(true);

    // And the disable is the guard, not decoration: a press lands on nothing.
    back();
    expect(onBack).not.toHaveBeenCalled();

    gate.settle?.();
    await screen.findByText(/^saved\.$/i);

    expect((screen.getByRole('button', { name: /^back$/i }) as HTMLButtonElement).disabled).toBe(
      false,
    );
  });

  it('still marks and focuses the field a refusal names, after the freeze lifts', async () => {
    // The freeze and the focus interact: a refusal arrives in the same batch
    // that re-enables the fields, and a `focus()` made before that commit runs
    // against a disabled element, which takes no focus at all. The screen-reader
    // user would then be told a field is invalid and not taken to it.
    stubFetch({ [`PATCH ${EDIT_PATH}`]: [refusal(INVALID_EMAIL, NOT_AN_ADDRESS, 422)] });
    renderScreen();

    fireEvent.change(emailBox(), { target: { value: 'nope' } });
    save();

    await screen.findByRole('alert');

    expect(emailBox().disabled).toBe(false);
    expect(document.activeElement).toBe(emailBox());
  });

  it('does not navigate away on success', async () => {
    const onBack = vi.fn();
    stubFetch({ [`PATCH ${EDIT_PATH}`]: [saved({ name: 'Kasun P.' })] });
    renderScreen({ onBack });

    fireEvent.change(nameBox(), { target: { value: 'Kasun P.' } });
    save();

    await screen.findByText(/^saved\.$/i);
    expect(onBack).not.toHaveBeenCalled();
    expect(screen.getByRole('heading', { name: /^edit user$/i })).toBeTruthy();
  });

  it('hands the saved row to onSaved', async () => {
    const onSaved = vi.fn();
    stubFetch({ [`PATCH ${EDIT_PATH}`]: [saved({ role: 'admin' })] });
    renderScreen({ onSaved });

    fireEvent.change(roleBox(), { target: { value: 'admin' } });
    save();

    await screen.findByText(/^saved\.$/i);
    expect(onSaved).toHaveBeenCalledTimes(1);
    expect(onSaved).toHaveBeenCalledWith(
      expect.objectContaining({ id: STAFF.id, role: 'admin' }),
    );
  });

  it('retires Saved. the moment a field is edited again', async () => {
    // "Saved." describes a change that has landed; beside a freshly edited field
    // it is describing something that is no longer on screen.
    stubFetch({ [`PATCH ${EDIT_PATH}`]: [saved({ name: 'Kasun P.' })] });
    renderScreen();

    fireEvent.change(nameBox(), { target: { value: 'Kasun P.' } });
    save();
    await screen.findByText(/^saved\.$/i);

    fireEvent.change(nameBox(), { target: { value: 'Kasun Q.' } });

    expect(screen.queryByText(/^saved\.$/i)).toBeNull();
  });
});

// --- The refusals -------------------------------------------------------------

describe('a refusal', () => {
  it.each([
    [INVALID_EMAIL, NOT_AN_ADDRESS, 422, 'email'],
    [EMAIL_ALREADY_EXISTS, ALREADY_IN_USE, 409, 'email'],
    [LAST_ADMINISTRATOR, LAST_ACTIVE_ADMINISTRATOR, 409, 'role'],
  ] as const)(
    '%s carries the API’s own sentence and marks the %s field',
    async (code, message, status, field) => {
      stubFetch({ [`PATCH ${EDIT_PATH}`]: [refusal(code, message, status)] });
      renderScreen();

      // Something has to change or nothing is sent; the role is the field the
      // last refusal is about and is harmless for the other two.
      fireEvent.change(roleBox(), { target: { value: 'admin' } });
      fireEvent.change(emailBox(), { target: { value: 'kp@rocell.lk' } });
      save();

      const alert = await screen.findByRole('alert');
      expect(alert.textContent).toBe(message);

      const marked = field === 'email' ? emailBox() : roleBox();
      expect(marked.getAttribute('aria-invalid')).toBe('true');
      expect(marked.getAttribute('aria-describedby')).toBe(alert.id);
      expect(document.activeElement).toBe(marked);
    },
  );

  it.each([
    [USER_NOT_FOUND, NO_SUCH_USER, 404],
    ['administrator_required', 'Only an Administrator can do this.', 403],
  ] as const)('%s marks no field at all', async (code, message, status) => {
    // Nothing on the form is wrong: the row is gone, or the caller was demoted
    // between two requests. Pointing at a field would send the Administrator to
    // correct something that is perfectly fine.
    stubFetch({ [`PATCH ${EDIT_PATH}`]: [refusal(code, message, status)] });
    renderScreen();

    fireEvent.change(nameBox(), { target: { value: 'Kasun P.' } });
    save();

    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toBe(message);
    for (const control of [nameBox(), emailBox(), roleBox()]) {
      expect(control.getAttribute('aria-invalid')).toBe('false');
    }
  });

  it('renders exactly one alert, never one under every field', async () => {
    stubFetch({ [`PATCH ${EDIT_PATH}`]: [refusal(INVALID_EMAIL, NOT_AN_ADDRESS, 422)] });
    renderScreen();

    fireEvent.change(emailBox(), { target: { value: 'nope' } });
    save();

    await screen.findByRole('alert');
    expect(screen.getAllByRole('alert')).toHaveLength(1);
  });

  it('keeps what was typed, so one field can be corrected', async () => {
    stubFetch({ [`PATCH ${EDIT_PATH}`]: [refusal(EMAIL_ALREADY_EXISTS, ALREADY_IN_USE, 409)] });
    renderScreen();

    fireEvent.change(nameBox(), { target: { value: 'Kasun P.' } });
    fireEvent.change(emailBox(), { target: { value: 'ruwan@rocell.lk' } });
    save();

    await screen.findByRole('alert');
    expect(nameBox().value).toBe('Kasun P.');
    expect(emailBox().value).toBe('ruwan@rocell.lk');
  });

  it('words a save whose response does not match the contract', async () => {
    // A `200` whose body is not a `User`. `apiRequest` turns that into an
    // `ApiRequestError(MALFORMED_RESPONSE)` with a sentence of its own, so what
    // is pinned here is that the screen renders *that* sentence rather than an
    // empty alert — not the `UNEXPECTED` fallback beside it, which only a
    // rejection that is not an `ApiRequestError` at all can reach and which
    // nothing on this path can produce.
    stubFetch({ [`PATCH ${EDIT_PATH}`]: [{ status: 200, body: { nonsense: true } }] });
    renderScreen();

    fireEvent.change(nameBox(), { target: { value: 'Kasun P.' } });
    save();

    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toBeTruthy();
    expect(screen.queryByText(/^saved\.$/i)).toBeNull();
  });
});

// --- Back, and unsaved edits --------------------------------------------------

describe('Back', () => {
  it('leaves straight away when nothing was edited', () => {
    const onBack = vi.fn();
    stubFetch({});
    renderScreen({ onBack });

    back();

    expect(onBack).toHaveBeenCalledTimes(1);
  });

  it('warns once with edits outstanding, and leaves on the second press', () => {
    // EXPERIENCE.md line 90: never silently drop an in-progress admin form
    // (DW-81). One warning, then Back works — a control that refuses twice is a
    // control that is broken.
    const onBack = vi.fn();
    stubFetch({});
    renderScreen({ onBack });

    fireEvent.change(nameBox(), { target: { value: 'Kasun P.' } });
    back();

    expect(onBack).not.toHaveBeenCalled();
    expect(screen.getByRole('alert').textContent).toContain('have not been saved');

    back();
    expect(onBack).toHaveBeenCalledTimes(1);
  });

  it('warns again after a further edit', () => {
    // The warning is about *these* edits. Having been shown it once, an
    // Administrator who then types something new has unsaved work again.
    const onBack = vi.fn();
    stubFetch({});
    renderScreen({ onBack });

    fireEvent.change(nameBox(), { target: { value: 'Kasun P.' } });
    back();
    fireEvent.change(nameBox(), { target: { value: 'Kasun Q.' } });
    back();

    expect(onBack).not.toHaveBeenCalled();
    expect(screen.getByRole('alert').textContent).toContain('have not been saved');
  });

  it('leaves without warning once the edits have been saved', async () => {
    const onBack = vi.fn();
    stubFetch({ [`PATCH ${EDIT_PATH}`]: [saved({ name: 'Kasun P.' })] });
    renderScreen({ onBack });

    fireEvent.change(nameBox(), { target: { value: 'Kasun P.' } });
    save();
    await screen.findByText(/^saved\.$/i);

    back();

    expect(onBack).toHaveBeenCalledTimes(1);
  });
});

// --- What the screen deliberately does not offer ------------------------------

describe('the controls', () => {
  it('offers Save changes and Back, and nothing else', async () => {
    stubFetch({});
    renderScreen();

    await waitFor(() => {
      expect(nameBox().value).toBe(STAFF.name);
    });
    const names = screen.getAllByRole('button').map((control) => control.textContent ?? '');

    expect(names).toEqual(['Save changes', 'Back']);
  });

  it('offers nothing that deactivates, deletes, unlocks or sets a password', () => {
    // Asserted over the rendered control names rather than by eye. Story 1.11
    // owns deactivate and delete; the unlock has no owner in Epic 1 at all
    // (DW-64); and this endpoint writes three columns, of which none is
    // `password_hash`.
    stubFetch({});
    renderScreen();

    for (const verb of [/deactivate/i, /delete/i, /unlock/i, /remove/i, /password/i, /reset/i]) {
      expect(screen.queryByRole('button', { name: verb })).toBeNull();
    }
    expect(screen.queryByLabelText(/password/i)).toBeNull();
    expect(screen.queryByRole('checkbox')).toBeNull();
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('offers exactly the three fields the endpoint writes', () => {
    stubFetch({});
    renderScreen();

    expect(screen.getAllByRole('textbox')).toHaveLength(2);
    expect(screen.getAllByRole('combobox')).toHaveLength(1);
  });
});

// --- Through the real gate ----------------------------------------------------

describe('the route from the list', () => {
  /** The session, the list behind the door, and the edit behind a row. */
  function stubShell(
    sessions: Reply[],
    lists: Reply[],
    edits: Record<string, Reply[]> = {},
  ): { calls: [string, RequestInit][] } {
    return stubFetch({
      'GET /api/auth/session': sessions,
      'GET /api/admin/users': lists,
      ...edits,
    });
  }

  it('opens the editor pre-filled from the row that was pressed', async () => {
    stubShell([{ status: 200, body: ADMIN }], [{ status: 200, body: [ADMIN, STAFF] }]);
    render(<App />);

    fireEvent.click(await screen.findByRole('button', { name: /^users$/i }));
    fireEvent.click(await screen.findByRole('button', { name: `Edit ${STAFF.name}` }));

    expect(await screen.findByRole('heading', { name: /^edit user$/i })).toBeTruthy();
    expect((screen.getByLabelText(/^name$/i) as HTMLInputElement).value).toBe(STAFF.name);
    expect((screen.getByLabelText(/^email$/i) as HTMLInputElement).value).toBe(STAFF.email);
  });

  it('keeps the shell around the editor', async () => {
    stubShell([{ status: 200, body: ADMIN }], [{ status: 200, body: [ADMIN, STAFF] }]);
    render(<App />);

    fireEvent.click(await screen.findByRole('button', { name: /^users$/i }));
    fireEvent.click(await screen.findByRole('button', { name: `Edit ${STAFF.name}` }));
    await screen.findByRole('heading', { name: /^edit user$/i });

    expect(screen.getByTestId('app-bar')).toBeTruthy();
    expect(screen.getByRole('button', { name: /^sign out$/i })).toBeTruthy();
    expect(screen.getByRole('button', { name: /^account$/i })).toBeTruthy();
  });

  it('saves, and Back shows the list refetched with the change on it', async () => {
    const renamed = { ...STAFF, name: 'Kasun P.' };
    const { calls } = stubShell(
      [{ status: 200, body: ADMIN }],
      [
        { status: 200, body: [ADMIN, STAFF] },
        { status: 200, body: [ADMIN, renamed] },
      ],
      { [`PATCH ${EDIT_PATH}`]: [{ status: 200, body: renamed }] },
    );
    render(<App />);

    fireEvent.click(await screen.findByRole('button', { name: /^users$/i }));
    fireEvent.click(await screen.findByRole('button', { name: `Edit ${STAFF.name}` }));
    await screen.findByRole('heading', { name: /^edit user$/i });

    fireEvent.change(screen.getByLabelText(/^name$/i), { target: { value: 'Kasun P.' } });
    fireEvent.click(screen.getByRole('button', { name: /^save changes$/i }));
    await screen.findByText(/^saved\.$/i);

    fireEvent.click(screen.getByRole('button', { name: /^back$/i }));
    await screen.findByRole('table');

    expect(screen.getByText('Kasun P.')).toBeTruthy();
    // Refetched rather than rendered from a cached array that is already stale.
    await waitFor(() => {
      expect(calls.filter(([path]) => path === '/api/admin/users')).toHaveLength(2);
    });
  });

  it('is offered to nobody whose role is not admin', async () => {
    // The role condition is one statement (`reachableBy`), shared by the screen
    // selector and the reconciler, so the editor is unreachable for the same
    // reason the list is. A Staff user is offered no door at all.
    stubShell([{ status: 200, body: STAFF }], [{ status: 200, body: [ADMIN, STAFF] }]);
    render(<App />);

    await screen.findByTestId('app-bar');

    expect(screen.queryByRole('button', { name: /^users$/i })).toBeNull();
    expect(screen.queryByRole('heading', { name: /^edit user$/i })).toBeNull();
  });

  it('drops a mid-edit demotion to the home panel rather than a dead screen', async () => {
    // EXPERIENCE.md line 95, with the editor open. A revalidation returning the
    // same person as Staff is exactly the mid-session demotion.
    stubShell(
      [
        { status: 200, body: ADMIN },
        { status: 200, body: { ...ADMIN, role: 'staff' } },
      ],
      [{ status: 200, body: [ADMIN, STAFF] }],
    );
    render(<App />);

    fireEvent.click(await screen.findByRole('button', { name: /^users$/i }));
    fireEvent.click(await screen.findByRole('button', { name: `Edit ${STAFF.name}` }));
    await screen.findByRole('heading', { name: /^edit user$/i });

    document.dispatchEvent(new Event('visibilitychange'));

    expect(await screen.findByText(/signed in as/i)).toBeTruthy();
    expect(screen.queryByRole('heading', { name: /^edit user$/i })).toBeNull();
    expect(screen.queryByRole('button', { name: /^users$/i })).toBeNull();
  });

  it('lands a self-demotion on the home panel with no Users door, and no reload', async () => {
    // The acceptance clause `adoptUser` exists for. The API answers with the
    // caller's own row carrying the new role; the provider adopts it because the
    // id matches; the role reconciler then does what it does for any demotion.
    // Nothing reloads and nothing announces it (EXPERIENCE.md line 95).
    const demoted = { ...ADMIN, role: 'staff' as const };
    stubShell(
      [{ status: 200, body: ADMIN }],
      [{ status: 200, body: [ADMIN, SECOND_ADMIN] }],
      { [`PATCH /api/admin/users/${ADMIN.id}`]: [{ status: 200, body: demoted }] },
    );
    render(<App />);

    fireEvent.click(await screen.findByRole('button', { name: /^users$/i }));
    fireEvent.click(await screen.findByRole('button', { name: `Edit ${ADMIN.name}` }));
    await screen.findByRole('heading', { name: /^edit user$/i });

    fireEvent.change(screen.getByLabelText(/^role$/i), { target: { value: 'staff' } });
    fireEvent.click(screen.getByRole('button', { name: /^save changes$/i }));

    expect(await screen.findByText(/signed in as/i)).toBeTruthy();
    expect(screen.queryByRole('button', { name: /^users$/i })).toBeNull();
    expect(screen.queryByRole('heading', { name: /^edit user$/i })).toBeNull();
  });

  it('adopts a self-rename into the app bar without a reload', async () => {
    // The other half of `adoptUser`, and the visible one: the shell greets the
    // caller by name, and without the adoption it goes on greeting them by the
    // old one until the tab is backgrounded and brought back.
    const renamed = { ...ADMIN, name: 'Ruwan J.' };
    stubShell(
      [{ status: 200, body: ADMIN }],
      [
        { status: 200, body: [ADMIN, SECOND_ADMIN] },
        { status: 200, body: [renamed, SECOND_ADMIN] },
      ],
      { [`PATCH /api/admin/users/${ADMIN.id}`]: [{ status: 200, body: renamed }] },
    );
    render(<App />);

    fireEvent.click(await screen.findByRole('button', { name: /^users$/i }));
    fireEvent.click(await screen.findByRole('button', { name: `Edit ${ADMIN.name}` }));
    await screen.findByRole('heading', { name: /^edit user$/i });

    fireEvent.change(screen.getByLabelText(/^name$/i), { target: { value: 'Ruwan J.' } });
    fireEvent.click(screen.getByRole('button', { name: /^save changes$/i }));
    await screen.findByText(/^saved\.$/i);

    fireEvent.click(screen.getByRole('button', { name: /^back$/i }));
    fireEvent.click(await screen.findByRole('button', { name: /^back$/i }));

    expect(await screen.findByText(/signed in as ruwan j\./i)).toBeTruthy();
  });

  it('does not write somebody else’s row into the caller’s session', async () => {
    // The id guard in `adoptUser`. Editing a colleague hands their row to the
    // provider, which must ignore it — otherwise an Administrator who promotes
    // a Staff member becomes that Staff member as far as the shell is concerned.
    const promoted = { ...STAFF, role: 'admin' as const };
    stubShell(
      [{ status: 200, body: ADMIN }],
      [{ status: 200, body: [ADMIN, STAFF] }],
      { [`PATCH ${EDIT_PATH}`]: [{ status: 200, body: promoted }] },
    );
    render(<App />);

    fireEvent.click(await screen.findByRole('button', { name: /^users$/i }));
    fireEvent.click(await screen.findByRole('button', { name: `Edit ${STAFF.name}` }));
    await screen.findByRole('heading', { name: /^edit user$/i });

    fireEvent.change(screen.getByLabelText(/^role$/i), { target: { value: 'admin' } });
    fireEvent.click(screen.getByRole('button', { name: /^save changes$/i }));
    await screen.findByText(/^saved\.$/i);

    fireEvent.click(screen.getByRole('button', { name: /^back$/i }));
    fireEvent.click(await screen.findByRole('button', { name: /^back$/i }));

    // Still the Administrator who did the editing, by name and by door.
    expect(await screen.findByText(new RegExp(`signed in as ${ADMIN.name}`, 'i'))).toBeTruthy();
    expect(screen.getByRole('button', { name: /^users$/i })).toBeTruthy();
  });
});
