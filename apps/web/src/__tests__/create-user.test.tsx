/**
 * Create user — the screen, and the route the app takes to reach it.
 *
 * Two halves, deliberately driven through two different roots, the way
 * `account-settings.test.tsx` splits them. The screen's own behaviour runs
 * against a stubbed `fetch` with the screen rendered directly, because it calls
 * `apiRequest` itself rather than going through `SessionProvider`; whether the
 * app *reaches* the screen at all runs through `App` against a stubbed `fetch`,
 * because the role condition and the section state live in the gate.
 *
 * Since Story 1.9 that route is two steps: the home panel's one admin entry is
 * **Users**, and Create user is reached from the list's "+ Add user"
 * (EXPERIENCE.md line 34). The block at the bottom of this file keeps every
 * role-reconciler subject it had — a Staff user is offered no door, a demotion
 * mid-screen lands on the home panel, a promotion leaves the user where it found
 * them — driven through the surface that door now opens.
 *
 * Three assertions here are the ones nothing else in the suite can make: that a
 * Staff user is offered no door at all, that a Staff user whose section state
 * somehow says otherwise still lands on the home panel, and that no control
 * anywhere on this screen offers to send the credential — which is AGENTS.md
 * Policy and FR-11, and which a screenshot review would have to catch otherwise.
 */
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import App from '../App';
import { EMAIL_ALREADY_EXISTS, INVALID_EMAIL, WEAK_PASSWORD } from '../api/client';
import { CreateUserScreen } from '../screens/CreateUserScreen';
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

/** What the API answers on a `201`: the row it just wrote. */
const CREATED: User = {
  id: 'b41d8e06-5a72-4f39-9c88-0d3e1f7a2b65',
  name: 'Nadeesha Silva',
  email: 'nadeesha@rocell.lk',
  role: 'staff',
  active: true,
  must_change_password: true,
  temp_credential_expires_at: '2026-09-21T09:30:00Z',
  last_login_at: null,
  locked_until: null,
  created_at: '2026-09-18T09:30:00Z',
  updated_at: '2026-09-18T09:30:00Z',
};

const TEMPORARY = 'a-long-enough-password';

/**
 * What `GET /admin/users` answers for the block at the bottom of this file.
 *
 * The list is now on the path between the home panel and Create user, so every
 * test that walks that path needs it to resolve. Its own behaviour — ordering,
 * badges, the lock line, the failure and the retry — is `user-list.test.tsx`'s.
 */
const ROSTER: User[] = [ADMIN, STAFF];

/**
 * `NOT_AN_ADDRESS`, `ADDRESS_ALREADY_IN_USE` and `PASSWORD_RULES['too_short']`
 * in the Python source, character for character.
 *
 * Restated rather than imported because nothing crosses that boundary at build
 * time — `error-code-parity.test.ts` pins the *codes* and not the sentences. If
 * one of these drifts, the API's sentence is still what the screen renders at
 * run time; what stops being true is this file's claim to be asserting it.
 */
const NOT_AN_ADDRESS = 'An email address must have exactly one @ sign, with text on each side.';
const ALREADY_IN_USE = 'A user with that email address already exists.';
const TOO_SHORT = 'A password must be at least 12 characters.';

interface Reply {
  status: number;
  body?: unknown;
}

const unauthorized: Reply = {
  status: 401,
  body: { error: { code: 'unauthorized', message: 'Not signed in.' } },
};

/**
 * Replace `fetch` with a queue keyed by **method and path**, and record every call.
 *
 * The method is part of the key because since Story 1.9 `GET /admin/users` and
 * `POST /admin/users` are two different routes over one path: keyed on the path
 * alone, the first test that submits this form through the `App` root would be
 * handed the user list as its create response and would fail for a reason that
 * has nothing to do with the code under test.
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

/** Stands in for the resolver until the promise below hands over the real one. */
const NOT_YET = (): void => undefined;

const refusal = (code: string, message: string, status: number): Reply => ({
  status,
  body: { error: { code, message } },
});

/** The row a person's name is in, so a cell assertion cannot read another row's. */
function rowFor(name: string): HTMLElement {
  const row = screen.getByText(name).closest('tr');
  expect(row, `${name} is not in a table row`).toBeTruthy();
  return row as HTMLElement;
}

function renderScreen(onBack: () => void = (): void => undefined): void {
  render(<CreateUserScreen onBack={onBack} />);
}

function fill({
  name = 'Nadeesha Silva',
  email = 'nadeesha@rocell.lk',
  password = TEMPORARY,
}: { name?: string; email?: string; password?: string } = {}): void {
  fireEvent.change(screen.getByLabelText(/^name$/i), { target: { value: name } });
  fireEvent.change(screen.getByLabelText(/^email$/i), { target: { value: email } });
  fireEvent.change(screen.getByLabelText(/^temporary password$/i), {
    target: { value: password },
  });
}

function submit(): void {
  fireEvent.click(screen.getByRole('button', { name: /^create user$/i }));
}

/** Every role a control on this screen could take. `option` is covered separately. */
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
  'menuitem',
  'menuitemcheckbox',
  'menuitemradio',
] as const;

/** Every control this screen is allowed to have, by accessible name. */
const EXPECTED_CONTROLS: readonly [(typeof CONTROL_ROLES)[number], RegExp][] = [
  ['textbox', /^name$/i],
  ['textbox', /^email$/i],
  ['textbox', /^temporary password$/i],
  ['combobox', /^role$/i],
  ['button', /^create user$/i],
  ['button', /^back$/i],
];

/** The one sentence on this screen allowed to mention mail at all. */
const NO_MAIL_SENTENCE = 'This app sends no mail.';

describe('the create user form', () => {
  it('sends exactly the body the API contract names', async () => {
    const { calls } = stubFetch({ 'POST /api/admin/users': [{ status: 201, body: CREATED }] });
    renderScreen();

    fill();
    fireEvent.change(screen.getByLabelText(/^role$/i), { target: { value: 'admin' } });
    submit();

    await screen.findByText(/user added/i);
    const [path, init] = calls[0] ?? ['', {}];
    expect(path).toBe('/api/admin/users');
    expect(init.method).toBe('POST');
    // The cookie is what carries the session. Nothing else does.
    expect(init.credentials).toBe('same-origin');
    expect((init.headers as Record<string, string>)['content-type']).toBe('application/json');
    expect(JSON.parse(String(init.body))).toEqual({
      name: 'Nadeesha Silva',
      email: 'nadeesha@rocell.lk',
      role: 'admin',
      temporary_password: TEMPORARY,
    });
  });

  it('defaults the role to Staff', async () => {
    const { calls } = stubFetch({ 'POST /api/admin/users': [{ status: 201, body: CREATED }] });
    renderScreen();

    fill();
    submit();

    await screen.findByText(/user added/i);
    expect(JSON.parse(String(calls[0]?.[1].body)).role).toBe('staff');
  });

  it('offers exactly the two roles the product has', () => {
    stubFetch({});
    renderScreen();

    const options = screen.getAllByRole('option').map((option) => option.textContent);

    expect(options).toEqual(['Staff', 'Administrator']);
  });

  it('sends the password exactly as typed, untrimmed', async () => {
    const { calls } = stubFetch({ 'POST /api/admin/users': [{ status: 201, body: CREATED }] });
    renderScreen();

    fill({ password: ` ${TEMPORARY} ` });
    submit();

    await screen.findByText(/user added/i);
    // Whitespace is part of a password. Trimming it here would hand over a
    // credential different from the one the login form would later send.
    expect(JSON.parse(String(calls[0]?.[1].body)).temporary_password).toBe(` ${TEMPORARY} `);
  });

  it('shows the credential and its deadline for transcription', async () => {
    stubFetch({ 'POST /api/admin/users': [{ status: 201, body: CREATED }] });
    renderScreen();

    fill();
    submit();

    await screen.findByText(/user added/i);
    expect(screen.getByText('Nadeesha Silva')).toBeTruthy();
    expect(screen.getByText('nadeesha@rocell.lk')).toBeTruthy();
    // Scoped to the panel's own `<dd>`: the role picker above it carries a
    // `Staff` option too, and an unscoped query would pass on that alone.
    expect(screen.getByText('Staff', { selector: 'dd' })).toBeTruthy();
    expect(screen.getByText(TEMPORARY)).toBeTruthy();
    // Rendered from the response, never computed here: the deadline is set by
    // Postgres's clock and a browser that added 72 hours to its own would show a
    // time the server does not honour.
    const expected = new Date(String(CREATED.temp_credential_expires_at)).toLocaleString(
      undefined,
      { timeZoneName: 'short' },
    );
    expect(screen.getByText(expected)).toBeTruthy();
  });

  it('names the zone the deadline is in', async () => {
    // A bare wall-clock time on a note handed over hours later, possibly in
    // another room, is a deadline nobody can check. `toLocaleString` already
    // renders in the reader's own zone; the zone name is what says which.
    stubFetch({ 'POST /api/admin/users': [{ status: 201, body: CREATED }] });
    renderScreen();

    fill();
    submit();

    await screen.findByText(/user added/i);
    const withZone = new Date(String(CREATED.temp_credential_expires_at)).toLocaleString(
      undefined,
      { timeZoneName: 'short' },
    );
    const withoutZone = new Date(String(CREATED.temp_credential_expires_at)).toLocaleString();
    // The two spellings must actually differ, or this asserts nothing.
    expect(withZone).not.toBe(withoutZone);
    expect(screen.getByText(withZone)).toBeTruthy();
  });

  it('renders no deadline at all when the body carries none', async () => {
    // Not reachable for a row this endpoint wrote — `_INSERT_USER` sets the flag
    // and the deadline in one statement — but the `User` contract allows null,
    // and the alternative to rendering nothing is rendering "Invalid Date"
    // beside a credential somebody is about to copy onto a note.
    stubFetch({
      'POST /api/admin/users': [
        { status: 201, body: { ...CREATED, temp_credential_expires_at: null } },
      ],
    });
    renderScreen();

    fill();
    submit();

    await screen.findByText(/user added/i);
    expect(screen.getByText('Expires')).toBeTruthy();
    expect(screen.queryByText(/invalid date/i)).toBeNull();
    expect(screen.queryByText(/NaN/)).toBeNull();
  });

  it('says the app sends nothing on the Administrator’s behalf', async () => {
    stubFetch({ 'POST /api/admin/users': [{ status: 201, body: CREATED }] });
    renderScreen();

    fill();
    submit();

    expect(await screen.findByText(/sends no mail/i)).toBeTruthy();
  });

  it('offers no control that would send the credential', async () => {
    // AGENTS.md Policy and FR-11: the Administrator distributes it manually.
    //
    // An exhaustive inventory rather than a keyword filter, and that is the
    // point of it. A filter has to guess the wording somebody would use, and it
    // reads whatever properties it happened to be written against — so a
    // checkbox named "Send this to them", or a control whose accessible name
    // comes from a `<label htmlFor>` rather than from its own text, walks past
    // one. This asserts *which controls exist*, by the accessible name
    // testing-library computes, across every role a control could take. Anything
    // added to this screen fails here until it is listed and argued for.
    stubFetch({ 'POST /api/admin/users': [{ status: 201, body: CREATED }] });
    renderScreen();

    fill();
    submit();
    await screen.findByText(/user added/i);

    for (const [role, name] of EXPECTED_CONTROLS) {
      expect(screen.getAllByRole(role, { name }), `${role} ${String(name)}`).toHaveLength(1);
    }
    const found = CONTROL_ROLES.flatMap((role) => screen.queryAllByRole(role));
    expect(found).toHaveLength(EXPECTED_CONTROLS.length);

    // And the prose, because a control is not the only way to offer something:
    // a link, or an instruction to press a key. The one sentence this screen is
    // allowed to say about mail is removed first, then nothing of the kind may
    // remain. `Email` survives as a field label and is deliberately not matched
    // — it names a field, it does not offer an action.
    const text = (document.body.textContent ?? '').replace(NO_MAIL_SENTENCE, '');
    expect(text).toContain('Nadeesha Silva');
    expect(text).not.toMatch(
      /\b(send|sends|sending|sent|e-?mailed|e-?mailing|invite|invites|invitation|notify|notifies|notification)\b/i,
    );
  });

  it('does not report a user as added when the body that comes back is not one', async () => {
    // The `201` is narrowed through `asUser`, which throws on a body it does not
    // recognise. That throw has to reach the screen as a failure like any other:
    // swallowed — or replaced by a cast — the panel renders with a blank name
    // and "Invalid Date" where the deadline goes, beside a credential somebody
    // is about to write down and hand over.
    stubFetch({ 'POST /api/admin/users': [{ status: 201, body: { id: CREATED.id } }] });
    renderScreen();

    fill();
    submit();

    // The sentence, not merely a node: blanked, `asUser`'s refusal would render
    // as an empty red paragraph and a presence-only assertion would still pass.
    expect((await screen.findByRole('alert')).textContent).toBe(
      'The server returned an unexpected response.',
    );
    expect(screen.queryByText(/user added/i)).toBeNull();
    // And nothing is cleared, because nothing landed.
    expect((screen.getByLabelText(/^name$/i) as HTMLInputElement).value).toBe('Nadeesha Silva');
  });

  it('clears the form once the user has been added, the role picker included', async () => {
    // The picker is the one field whose leftover value is a *privilege*: an
    // Administrator who provisions an admin and then a staff member in one
    // sitting would otherwise submit the second with `admin` still selected, and
    // the server has no reason to refuse it — a role granted by form state
    // nobody looked at. Set to Administrator before submitting, so deleting the
    // reset fails here rather than passing on a field the test never touched.
    stubFetch({ 'POST /api/admin/users': [{ status: 201, body: CREATED }] });
    renderScreen();

    fill();
    fireEvent.change(screen.getByLabelText(/^role$/i), { target: { value: 'admin' } });
    submit();

    await screen.findByText(/user added/i);
    expect((screen.getByLabelText(/^name$/i) as HTMLInputElement).value).toBe('');
    expect((screen.getByLabelText(/^email$/i) as HTMLInputElement).value).toBe('');
    expect((screen.getByLabelText(/^temporary password$/i) as HTMLInputElement).value).toBe('');
    expect((screen.getByLabelText(/^role$/i) as HTMLSelectElement).value).toBe('staff');
  });

  it('stays on the screen, with no toast and no navigation', async () => {
    const onBack = vi.fn();
    stubFetch({ 'POST /api/admin/users': [{ status: 201, body: CREATED }] });
    renderScreen(onBack);

    fill();
    submit();

    await screen.findByText(/user added/i);
    expect(onBack).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: /^create user$/i })).toBeTruthy();
  });

  it('retires the result panel as soon as a field is edited', async () => {
    // A credential sitting beside a half-filled form reads as though it belonged
    // to what is being typed — the exact transcription error the panel exists to
    // prevent.
    stubFetch({ 'POST /api/admin/users': [{ status: 201, body: CREATED }] });
    renderScreen();

    fill();
    submit();
    await screen.findByText(/user added/i);

    fireEvent.change(screen.getByLabelText(/^name$/i), { target: { value: 'K' } });

    expect(screen.queryByText(/user added/i)).toBeNull();
  });

  it('keeps the result panel through a submit that types nothing', async () => {
    // The form is empty after a success, so a stray Enter or a second click on
    // Create user refuses on the blank name — and until this was fixed that
    // refusal cleared the panel holding the one copy of the credential, which
    // nothing in the product can show again. Nothing was typed, so there is
    // nothing for the panel to be describing incorrectly.
    stubFetch({ 'POST /api/admin/users': [{ status: 201, body: CREATED }] });
    renderScreen();

    fill();
    submit();
    await screen.findByText(/user added/i);

    submit();

    expect(await screen.findByText(/enter the person/i)).toBeTruthy();
    expect(screen.getByText(/user added/i)).toBeTruthy();
    expect(screen.getByText(TEMPORARY)).toBeTruthy();
  });

  it.each([
    ['name', /^name$/i, '200'],
    ['email', /^email$/i, '320'],
    ['temporary password', /^temporary password$/i, '4096'],
  ])('bounds the %s field the way the server bounds it', (_label, label, bound) => {
    // The server's bound is the authority — `CreateUserRequest` refuses anything
    // past it whatever this file says. What the attribute buys is that the
    // refusal never has to be *shown*: an over-long value comes back as
    // `422 validation_error`, one generic sentence that names no field, so
    // nothing is marked and nothing is focused. That is the outcome
    // `invalid_email` was given its own code to avoid.
    stubFetch({});
    renderScreen();

    expect(screen.getByLabelText(label).getAttribute('maxlength')).toBe(bound);
  });

  it('shows the temporary password rather than masking it', () => {
    // It is not the Administrator's own secret: it is a value they must
    // transcribe verbatim, and masking it makes a typing error invisible until
    // the new user cannot sign in.
    stubFetch({});
    renderScreen();

    const field = screen.getByLabelText(/^temporary password$/i);

    expect(field.getAttribute('type')).toBe('text');
    expect(field.getAttribute('autocomplete')).toBe('off');
  });
});

describe('a refusal names the field the Administrator has to fix', () => {
  it.each([
    ['invalid_email', refusal(INVALID_EMAIL, NOT_AN_ADDRESS, 422), NOT_AN_ADDRESS, /^email$/i],
    [
      'email_already_exists',
      refusal(EMAIL_ALREADY_EXISTS, ALREADY_IN_USE, 409),
      ALREADY_IN_USE,
      /^email$/i,
    ],
    [
      'weak_password',
      refusal(WEAK_PASSWORD, TOO_SHORT, 422),
      TOO_SHORT,
      /^temporary password$/i,
    ],
  ])('marks and focuses the right field for %s', async (_code, reply, message, label) => {
    stubFetch({ 'POST /api/admin/users': [reply] });
    renderScreen();

    fill();
    submit();

    // The API's own sentence, which names the rule that failed — never a
    // generic one composed here (EXPERIENCE.md:87).
    expect(await screen.findByRole('alert')).toHaveProperty('textContent', message);
    const field = screen.getByLabelText(label);
    expect(field.getAttribute('aria-invalid')).toBe('true');
    expect(document.activeElement).toBe(field);
  });

  it('keeps every typed value across a refusal', async () => {
    stubFetch({ 'POST /api/admin/users': [refusal(EMAIL_ALREADY_EXISTS, ALREADY_IN_USE, 409)] });
    renderScreen();

    fill();
    submit();

    await screen.findByRole('alert');
    expect((screen.getByLabelText(/^name$/i) as HTMLInputElement).value).toBe('Nadeesha Silva');
    expect((screen.getByLabelText(/^temporary password$/i) as HTMLInputElement).value).toBe(
      TEMPORARY,
    );
  });

  it('marks no field for a refusal that belongs to none of them', async () => {
    // `administrator_required` is the realistic case: an Administrator demoted
    // between two requests. Nothing they typed is at fault, so nothing is marked.
    stubFetch({
      'POST /api/admin/users': [
        refusal('administrator_required', 'Only an Administrator can do this.', 403),
      ],
    });
    renderScreen();

    fill();
    submit();

    expect(await screen.findByRole('alert')).toHaveProperty(
      'textContent',
      'Only an Administrator can do this.',
    );
    for (const label of [/^name$/i, /^email$/i, /^temporary password$/i]) {
      expect(screen.getByLabelText(label).getAttribute('aria-invalid')).toBe('false');
    }
  });

  it.each([
    ['name', { name: '  ' }, /^name$/i],
    ['email', { email: ' ' }, /^email$/i],
    ['temporary password', { password: '  ' }, /^temporary password$/i],
  ])('refuses a blank %s without a request', async (_field, values, label) => {
    const { calls } = stubFetch({ 'POST /api/admin/users': [{ status: 201, body: CREATED }] });
    renderScreen();

    fill(values);
    submit();

    expect(await screen.findByRole('alert')).toBeTruthy();
    expect(document.activeElement).toBe(screen.getByLabelText(label));
    expect(calls).toEqual([]);
  });

  it('renders exactly one alert', async () => {
    stubFetch({ 'POST /api/admin/users': [refusal(INVALID_EMAIL, NOT_AN_ADDRESS, 422)] });
    renderScreen();

    fill();
    submit();

    await screen.findByRole('alert');
    expect(screen.getAllByRole('alert')).toHaveLength(1);
  });
});

describe('the form while a request is in flight', () => {
  /** A request that stays open until it is released. */
  function pending(): { release: () => void } {
    let release = NOT_YET;
    vi.stubGlobal('fetch', () =>
      new Promise<Response>((resolve) => {
        release = () =>
          resolve({
            ok: true,
            status: 201,
            json: () => Promise.resolve(CREATED),
          } as Response);
      }),
    );
    return { release: () => release() };
  }

  it('disables both controls until the request settles', async () => {
    const { release } = pending();
    renderScreen();

    fill();
    submit();

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /^create user$/i })).toHaveProperty(
        'disabled',
        true,
      );
    });
    // Back too: a click that unmounted the screen mid-request would add the user
    // and never show the Administrator the credential, which nothing can recover.
    expect(screen.getByRole('button', { name: /^back$/i })).toHaveProperty('disabled', true);
    expect(screen.getByRole('status').textContent).toBe('Creating…');

    release();
    await screen.findByText(/user added/i);
  });
});

describe('Back', () => {
  it('returns to where the screen was opened from', () => {
    const onBack = vi.fn();
    stubFetch({});
    renderScreen(onBack);

    fireEvent.click(screen.getByRole('button', { name: /^back$/i }));

    expect(onBack).toHaveBeenCalledTimes(1);
  });
});

describe('the door on the home panel', () => {
  /** The session plus the list behind the door, which every path here now crosses. */
  function stubShell(sessions: Reply[]): { calls: [string, RequestInit][] } {
    return stubFetch({
      'GET /api/auth/session': sessions,
      'GET /api/admin/users': [{ status: 200, body: ROSTER }],
    });
  }

  it('is offered to an Administrator', async () => {
    stubShell([{ status: 200, body: ADMIN }]);
    render(<App />);

    expect(await screen.findByRole('button', { name: /^users$/i })).toBeTruthy();
  });

  it('is the one door to this collection, and Create user is not a second', async () => {
    // EXPERIENCE.md's nav has one entry for *this* collection — User List — and
    // reaches Create/Edit User from a row or from "+ Add User" on it (line 34).
    // Leaving Story 1.8's door beside it would be a second entry to one
    // collection, which the spine does not have, and would leave Story 1.10's
    // Edit User nowhere to go.
    //
    // The home panel does carry two admin entries since Story 1.13 — Users and
    // Audit log — and that is not what this asserts: those are line 33 and line
    // 38, two collections with two nav entries. `audit-log.test.tsx` owns the
    // second one.
    stubShell([{ status: 200, body: ADMIN }]);
    render(<App />);

    await screen.findByRole('button', { name: /^users$/i });
    expect(screen.queryByRole('button', { name: /^create user$/i })).toBeNull();
  });

  it('is not rendered anywhere for a Staff user', async () => {
    // EXPERIENCE.md line 18: the nav is role-conditional, not a menu with
    // disabled items — a Staff user never sees an Admin entry at all.
    stubShell([{ status: 200, body: STAFF }]);
    render(<App />);

    await screen.findByTestId('app-bar');
    expect(screen.queryByRole('button', { name: /^users$/i })).toBeNull();
    expect(screen.queryByRole('button', { name: /^create user$/i })).toBeNull();
  });

  it('opens the list and comes back again', async () => {
    stubShell([{ status: 200, body: ADMIN }]);
    render(<App />);

    fireEvent.click(await screen.findByRole('button', { name: /^users$/i }));

    expect(await screen.findByRole('heading', { name: /^users$/i })).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: /^back$/i }));
    expect(await screen.findByText(/signed in as/i)).toBeTruthy();
  });

  it('shows every account with its status and last login — the story’s own clause', async () => {
    // Story 1.9's acceptance sentence, end to end: an authenticated
    // Administrator opens the user list and sees every account with its
    // active/deactivated status and its last-login timestamp. Every other content
    // assertion in the suite is a direct render of the screen with no session
    // behind it (`user-list.test.tsx`), so without this nothing proves the clause
    // through the real gate, the real shell and the real role condition.
    const deactivated: User = {
      ...STAFF,
      id: '7b2c4d1e-8a35-4c62-9f04-1e5a3b7d2c98',
      name: 'Amal Perera',
      email: 'amal@rocell.lk',
      active: false,
    };
    // Provisioned and not yet handed over: the account with no sign-in behind it.
    const unclaimed: User = { ...CREATED, name: 'Nadeesha Silva' };

    stubFetch({
      'GET /api/auth/session': [{ status: 200, body: ADMIN }],
      'GET /api/admin/users': [{ status: 200, body: [ADMIN, deactivated, unclaimed] }],
    });
    render(<App />);

    fireEvent.click(await screen.findByRole('button', { name: /^users$/i }));
    await screen.findByRole('table');

    // The caller's own row — an Administrator auditing access is one of the
    // people who has it — with its role, its status word and its last sign-in.
    const mine = within(rowFor(ADMIN.name));
    expect(mine.getByText('Administrator')).toBeTruthy();
    expect(mine.getByText('Active')).toBeTruthy();
    expect(rowFor(ADMIN.name).textContent).toContain(
      new Date(ADMIN.last_login_at ?? '').toLocaleString(),
    );

    // The deactivated account is marked, not missing.
    expect(within(rowFor(deactivated.name)).getByText('Deactivated')).toBeTruthy();

    // And the one that has never signed in says so.
    expect(within(rowFor(unclaimed.name)).getByText('Never')).toBeTruthy();
  });

  it('reaches Create user from the list, and Back returns to the list', async () => {
    // The two-step route EXPERIENCE.md line 34 describes, end to end — and the
    // reason Back points at the list rather than at the home panel: the list is
    // where "+ Add user" was pressed, and where the new row belongs.
    stubShell([{ status: 200, body: ADMIN }]);
    render(<App />);

    fireEvent.click(await screen.findByRole('button', { name: /^users$/i }));
    fireEvent.click(await screen.findByRole('button', { name: /add user/i }));

    expect(await screen.findByRole('heading', { name: /^create user$/i })).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: /^back$/i }));
    expect(await screen.findByRole('heading', { name: /^users$/i })).toBeTruthy();

    // And a second Back goes home, so nobody is stranded one surface in.
    fireEvent.click(screen.getByRole('button', { name: /^back$/i }));
    expect(await screen.findByText(/signed in as/i)).toBeTruthy();
  });

  it('refetches the list on the way back from Create user', async () => {
    // The screen mounts fresh each time the section swaps to it, so a user
    // provisioned a moment ago is on the list that comes back rather than on a
    // cached one that is already out of date.
    const { calls } = stubShell([{ status: 200, body: ADMIN }]);
    render(<App />);

    fireEvent.click(await screen.findByRole('button', { name: /^users$/i }));
    await screen.findByRole('heading', { name: /^users$/i });
    await waitFor(() => {
      expect(calls.filter(([path]) => path === '/api/admin/users')).toHaveLength(1);
    });

    fireEvent.click(await screen.findByRole('button', { name: /add user/i }));
    await screen.findByRole('heading', { name: /^create user$/i });
    fireEvent.click(screen.getByRole('button', { name: /^back$/i }));
    await screen.findByRole('heading', { name: /^users$/i });

    await waitFor(() => {
      expect(calls.filter(([path]) => path === '/api/admin/users')).toHaveLength(2);
    });
  });

  it('keeps the shell around the screen', async () => {
    // Inside the shell, in place of the home panel: the app bar stays, so Sign
    // out and Account stay with it.
    stubShell([{ status: 200, body: ADMIN }]);
    render(<App />);

    fireEvent.click(await screen.findByRole('button', { name: /^users$/i }));

    await screen.findByRole('heading', { name: /^users$/i });
    expect(screen.getByTestId('app-bar')).toBeTruthy();
    expect(screen.getByRole('button', { name: /^sign out$/i })).toBeTruthy();
  });

  it('keeps the app bar’s Account control working from this screen', async () => {
    // The users branch renders its own `AppShell` and passes its own
    // `onOpenAccount`; `AppBar` renders the control only when that prop is
    // defined. Asserting the app bar is present does not reach either, so
    // dropping the prop — or pointing it at the home panel — would leave the one
    // surface an Administrator spends time on without a way to their own account
    // and the suite green.
    stubShell([{ status: 200, body: ADMIN }]);
    render(<App />);

    fireEvent.click(await screen.findByRole('button', { name: /^users$/i }));
    await screen.findByRole('heading', { name: /^users$/i });

    fireEvent.click(screen.getByRole('button', { name: /^account$/i }));

    expect(await screen.findByRole('heading', { name: /^account$/i })).toBeTruthy();
  });

  it('is not reachable at all by a user whose role is not admin', async () => {
    // The redirect EXPERIENCE.md line 95 asks for, expressed as a pure function
    // of role: an Administrator demoted while standing on this screen renders the
    // home panel on the very next render, not a dead screen. Driven by signing an
    // Administrator in, opening the screen, and letting a revalidation return the
    // same person as Staff — which is exactly the mid-session demotion.
    stubShell([
      { status: 200, body: ADMIN },
      { status: 200, body: { ...ADMIN, role: 'staff' } },
    ]);
    render(<App />);

    fireEvent.click(await screen.findByRole('button', { name: /^users$/i }));
    await screen.findByRole('heading', { name: /^users$/i });

    // The visibility revalidation `SessionProvider` registers is what re-reads
    // the role (AD-3); this is that request arriving with the new one.
    document.dispatchEvent(new Event('visibilitychange'));

    expect(await screen.findByText(/signed in as/i)).toBeTruthy();
    expect(screen.queryByRole('heading', { name: /^users$/i })).toBeNull();
    expect(screen.queryByRole('button', { name: /^users$/i })).toBeNull();
    // And nothing of the list survives the swap — not a stale table, not a row.
    expect(screen.queryByRole('table')).toBeNull();
  });

  it('leaves the door working after a demotion and a promotion', async () => {
    // The round trip, end to end. It has to assert the home panel *before* the
    // click, and that ordering is the whole test: with the section left at
    // `'users'`, the promotion re-renders the screen by itself and a
    // click-then-assert would pass while testing something else entirely.
    stubShell([
      { status: 200, body: ADMIN },
      { status: 200, body: { ...ADMIN, role: 'staff' } },
      { status: 200, body: ADMIN },
    ]);
    render(<App />);

    fireEvent.click(await screen.findByRole('button', { name: /^users$/i }));
    await screen.findByRole('heading', { name: /^users$/i });

    // Demoted, then promoted back — two visibility revalidations (AD-3).
    document.dispatchEvent(new Event('visibilitychange'));
    await screen.findByText(/signed in as/i);
    document.dispatchEvent(new Event('visibilitychange'));
    await screen.findByRole('button', { name: /^users$/i });

    // Still the home panel, with the door on it and the screen not showing.
    expect(screen.getByText(/signed in as/i)).toBeTruthy();
    expect(screen.queryByRole('heading', { name: /^users$/i })).toBeNull();

    // And the door still opens — the section was cleared, not merely read past.
    fireEvent.click(screen.getByRole('button', { name: /^users$/i }));
    expect(await screen.findByRole('heading', { name: /^users$/i })).toBeTruthy();
  });

  it('does not reopen the screen by itself when the role comes back', async () => {
    // The second consequence, and the worse one: with the section left at
    // `'users'`, restoring the role re-renders the admin screen unbidden over
    // whatever the user was actually looking at. A demotion and a promotion
    // within one shift is two clicks on Story 1.10's screen.
    stubShell([
      { status: 200, body: ADMIN },
      { status: 200, body: { ...ADMIN, role: 'staff' } },
      { status: 200, body: ADMIN },
    ]);
    render(<App />);

    fireEvent.click(await screen.findByRole('button', { name: /^users$/i }));
    await screen.findByRole('heading', { name: /^users$/i });

    document.dispatchEvent(new Event('visibilitychange'));
    await screen.findByText(/signed in as/i);
    document.dispatchEvent(new Event('visibilitychange'));
    await screen.findByRole('button', { name: /^users$/i });

    // The home panel, still — the user is taken nowhere they did not ask to go.
    expect(screen.getByText(/signed in as/i)).toBeTruthy();
    expect(screen.queryByRole('heading', { name: /^users$/i })).toBeNull();
  });

  it('leaves a promotion where it found the user', async () => {
    // A role change is not by itself a reason to move somebody. A promotion
    // arrives through the same revalidation as a demotion, and clearing the
    // section for every change takes a Staff user standing on Account Settings —
    // a surface both roles reach — back to the home panel the moment they are
    // made an Administrator, discarding whatever they had typed into it. The
    // reconciler clears only a section the *new* role cannot reach.
    const { calls } = stubShell([
      { status: 200, body: STAFF },
      { status: 200, body: { ...STAFF, role: 'admin' } },
    ]);
    render(<App />);

    fireEvent.click(await screen.findByRole('button', { name: /^account$/i }));
    await screen.findByRole('heading', { name: /^account$/i });

    // Promoted, through the visibility revalidation that re-reads the role (AD-3).
    document.dispatchEvent(new Event('visibilitychange'));
    await waitFor(() => {
      expect(calls.filter(([path]) => path === '/api/auth/session')).toHaveLength(2);
    });

    // Still where they were, and nothing typed there was thrown away.
    expect(screen.getByRole('heading', { name: /^account$/i })).toBeTruthy();
    expect(screen.queryByText(/signed in as/i)).toBeNull();

    // And the promotion did land — the door is on the home panel they go back to.
    fireEvent.click(screen.getByRole('button', { name: /^back$/i }));
    expect(await screen.findByRole('button', { name: /^users$/i })).toBeTruthy();
  });

  it('is gone once the session is', async () => {
    stubFetch({ 'GET /api/auth/session': [unauthorized] });
    render(<App />);

    await screen.findByLabelText(/password/i);
    expect(screen.queryByRole('button', { name: /^users$/i })).toBeNull();
  });
});
