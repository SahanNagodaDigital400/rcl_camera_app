/**
 * Account Settings — the screen, and the door the app bar opens onto it.
 *
 * Two halves, deliberately tested through two different roots. The screen's own
 * behaviour runs against a stubbed session context, the way
 * `forced-password-change.test.tsx` does it; whether the app *reaches* the
 * screen at all runs through `App` against a stubbed `fetch`, the way
 * `auth-gating.test.tsx` does, because the section state and the focus swap live
 * in the gate and not in the screen.
 *
 * The assertion this file exists for is the one nothing else can see: which
 * field a failure marks. `invalid_current_password` and `weak_password` are both
 * rejections of a form with two boxes in it, and a screen that marked the wrong
 * one would send the user to correct something that is perfectly fine — with
 * every other test in the suite green.
 */
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import App from '../App';
import {
  ApiRequestError,
  INVALID_CURRENT_PASSWORD,
  NETWORK_ERROR,
  WEAK_PASSWORD,
} from '../api/client';
import type { SessionContextValue } from '../auth/SessionProvider';
import { AccountSettingsScreen } from '../screens/AccountSettingsScreen';
import type { User } from '@rocell/schema/user';

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  // The stub outlives the test that installed it otherwise, so a case added to
  // the real-provider block below that forgot its own `session.value = null`
  // would silently run against the previous test's `vi.fn()` and pass for a
  // reason that has nothing to do with what it asserts.
  session.value = null;
});

const session = vi.hoisted(() => ({ value: null as SessionContextValue | null }));

vi.mock('../auth/SessionProvider', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../auth/SessionProvider')>();
  return {
    ...actual,
    useSession: (): SessionContextValue => {
      if (session.value === null) return actual.useSession();
      return session.value;
    },
  };
});

const STAFF: User = {
  id: '3f1a6b2c-9d4e-4f70-8a11-5c2e7b9d0a34',
  name: 'Kasun Perera',
  email: 'kasun@rocell.lk',
  role: 'staff',
  active: true,
  must_change_password: false,
  temp_credential_expires_at: null,
  last_login_at: '2026-09-17T08:00:00Z',
  locked_until: null,
  created_at: '2026-09-17T08:00:00Z',
  updated_at: '2026-09-17T08:00:00Z',
};

/**
 * `CURRENT_PASSWORD_WRONG` in `apps/api/api/auth.py`, character for character.
 *
 * Restated rather than imported because nothing crosses that boundary at build
 * time — `error-code-parity.test.ts` pins the *codes* and not the sentences. If
 * this drifts from the Python constant, the API's sentence is still what the
 * screen renders at run time; what stops being true is this file's claim to be
 * asserting it.
 */
const WRONG_CURRENT = 'Your current password is incorrect.';

/**
 * What a failed sign-out puts on screen here.
 *
 * `App.tsx` renders an `ApiRequestError`'s own message and falls back to its
 * `SIGN_OUT_FAILED` only for a failure that is not one; a `500` with no envelope
 * reaches it as the client's malformed-response sentence. Either way the test
 * below is about whether the alert *survives*, not which sentence it holds.
 */
const SIGN_OUT_FAILED = 'The server returned an unexpected response.';

const CURRENT = 'the-current-password';
const NEXT = 'a-long-enough-password';

function renderScreen(
  changeOwnPassword: SessionContextValue['changeOwnPassword'],
  onBack: () => void = (): void => undefined,
): void {
  session.value = {
    status: 'signed-in',
    user: STAFF,
    signIn: vi.fn(async () => undefined),
    changePassword: vi.fn(async () => undefined),
    changeOwnPassword,
    signOut: vi.fn(async () => undefined),
    // Story 1.10's self-edit adoption. Never called from this screen — it is
    // the edit screen's, through `App` — and present because the context is one
    // object.
    adoptUser: vi.fn(),
    sessionEnded: false,
  };
  render(<AccountSettingsScreen onBack={onBack} />);
}

function fill(current: string, next: string): void {
  fireEvent.change(screen.getByLabelText(/current password/i), { target: { value: current } });
  fireEvent.change(screen.getByLabelText(/new password/i), { target: { value: next } });
}

function submit(): void {
  fireEvent.click(screen.getByRole('button', { name: /^change password$/i }));
}

const accepted = (): SessionContextValue['changeOwnPassword'] => vi.fn(async () => undefined);

const refusedWith = (
  code: string,
  message: string,
  status: number,
): SessionContextValue['changeOwnPassword'] =>
  vi.fn(async () => {
    throw new ApiRequestError(code, message, status);
  });

/** Stands in for the resolver until the promise below hands over the real one. */
const NOT_YET = (): void => undefined;

/** A change that stays in flight until it is released — the in-flight state. */
function pending(): {
  changeOwnPassword: SessionContextValue['changeOwnPassword'];
  release: () => void;
} {
  let release = NOT_YET;
  const changeOwnPassword = vi.fn(
    async () =>
      new Promise<void>((resolve) => {
        release = resolve;
      }),
  );
  return { changeOwnPassword, release: () => release() };
}

describe('the account settings screen', () => {
  it('shows who is signed in, read-only', () => {
    // FR-11 puts editing a name or an address with an Administrator (Story
    // 1.10). Rendering them as text rather than as disabled inputs is what keeps
    // this screen from inviting a click that will never do anything.
    renderScreen(accepted());

    expect(screen.getByText('Kasun Perera')).toBeTruthy();
    expect(screen.getByText('kasun@rocell.lk')).toBeTruthy();
    expect(screen.queryByLabelText(/^name$/i)).toBeNull();
    expect(screen.queryByLabelText(/^email$/i)).toBeNull();
  });

  it('associates both labels with their inputs', () => {
    // `getByLabelText` succeeding is the assertion: without the association, an
    // assistive technology reads two unlabelled boxes and cannot tell them apart.
    renderScreen(accepted());

    expect(screen.getByLabelText(/current password/i)).toBeTruthy();
    expect(screen.getByLabelText(/new password/i)).toBeTruthy();
  });

  it('masks both fields', () => {
    renderScreen(accepted());

    expect(screen.getByLabelText(/current password/i).getAttribute('type')).toBe('password');
    expect(screen.getByLabelText(/new password/i).getAttribute('type')).toBe('password');
  });

  it('asks the password manager for the right entry in each box', () => {
    // `new-password` on the current field would offer a generated suggestion
    // where the stored credential belongs, and `current-password` on the new
    // field would offer back the very password being replaced.
    renderScreen(accepted());

    expect(screen.getByLabelText(/current password/i).getAttribute('autocomplete')).toBe(
      'current-password',
    );
    expect(screen.getByLabelText(/new password/i).getAttribute('autocomplete')).toBe(
      'new-password',
    );
  });

  it('has no confirm field, no reveal toggle and no strength meter', () => {
    // The same three absences the forced-change screen documents. Two controls
    // on this screen: the primary action and Back.
    renderScreen(accepted());

    expect(screen.queryByLabelText(/confirm/i)).toBeNull();
    expect(screen.getAllByRole('button')).toHaveLength(2);
    expect(screen.queryByRole('meter')).toBeNull();
    expect(screen.queryByRole('progressbar')).toBeNull();
  });

  it('offers no recovery affordance for a signed-out user', () => {
    // FR-5's second clause on the one screen a reader might expect to find it:
    // a user who has forgotten their password cannot get here at all, and their
    // way back is an Administrator, not a link.
    renderScreen(accepted());

    expect(screen.queryByRole('link')).toBeNull();
    const copy = document.body.textContent?.toLowerCase() ?? '';
    expect(copy).not.toContain('forgot');
    expect(copy).not.toContain('email me');
  });

  it('sends both fields exactly once', async () => {
    const changeOwnPassword = accepted();
    renderScreen(changeOwnPassword);

    fill(CURRENT, NEXT);
    submit();

    await waitFor(() => expect(changeOwnPassword).toHaveBeenCalledTimes(1));
    expect(changeOwnPassword).toHaveBeenCalledWith(CURRENT, NEXT);
  });

  it('clears both fields and says so, without navigating', async () => {
    const onBack = vi.fn();
    renderScreen(accepted(), onBack);

    fill(CURRENT, NEXT);
    submit();

    await screen.findByText('Saved.');
    expect((screen.getByLabelText(/current password/i) as HTMLInputElement).value).toBe('');
    expect((screen.getByLabelText(/new password/i) as HTMLInputElement).value).toBe('');
    // No navigation and no toast: the screen stays exactly where it is.
    expect(onBack).not.toHaveBeenCalled();
    expect(screen.getByRole('heading', { level: 1 }).textContent).toBe('Account');
  });

  it('carries the save indicator on a status region beside the action', async () => {
    // `role="alert"` would interrupt a screen-reader user assertively, which is
    // right for "your password was refused" and wrong for "saved".
    renderScreen(accepted());

    fill(CURRENT, NEXT);
    submit();

    const saved = await screen.findByText('Saved.');
    expect(saved.getAttribute('role')).toBe('status');
  });

  it('disables the action while the change is in flight', async () => {
    const { changeOwnPassword, release } = pending();
    renderScreen(changeOwnPassword);

    fill(CURRENT, NEXT);
    submit();

    const action = screen.getByRole('button', { name: /^change password$/i });
    await waitFor(() => expect((action as HTMLButtonElement).disabled).toBe(true));
    expect(screen.getByText('Saving…')).toBeTruthy();

    release();
    await waitFor(() => expect((action as HTMLButtonElement).disabled).toBe(false));
  });

  it('marks the current-password field for a wrong current password', async () => {
    const message = 'Your current password is incorrect.';
    renderScreen(refusedWith(INVALID_CURRENT_PASSWORD, message, 403));

    fill(CURRENT, NEXT);
    submit();

    // The API's own sentence, verbatim.
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toBe(message);

    const current = screen.getByLabelText(/current password/i);
    const next = screen.getByLabelText(/new password/i);
    expect(current.getAttribute('aria-invalid')).toBe('true');
    expect(next.getAttribute('aria-invalid')).toBe('false');
    expect(document.activeElement).toBe(current);
    // Both typed values are kept: the new password was never the problem.
    expect((current as HTMLInputElement).value).toBe(CURRENT);
    expect((next as HTMLInputElement).value).toBe(NEXT);
  });

  it('marks the new-password field for a refused new password', async () => {
    const message = 'A password must be at least 12 characters.';
    renderScreen(refusedWith(WEAK_PASSWORD, message, 422));

    fill(CURRENT, 'short');
    submit();

    const alert = await screen.findByRole('alert');
    // The rule the server named, not a generic verdict this screen composed
    // (EXPERIENCE.md:87).
    expect(alert.textContent).toBe(message);

    const current = screen.getByLabelText(/current password/i);
    const next = screen.getByLabelText(/new password/i);
    expect(next.getAttribute('aria-invalid')).toBe('true');
    expect(current.getAttribute('aria-invalid')).toBe('false');
    expect(document.activeElement).toBe(next);
  });

  it('describes the error from the offending field alone', async () => {
    // A form with two boxes and one error parked under both leaves a
    // screen-reader user on the second box hearing a sentence about the first.
    renderScreen(refusedWith(INVALID_CURRENT_PASSWORD, 'Your current password is incorrect.', 403));

    fill(CURRENT, NEXT);
    submit();

    const alert = await screen.findByRole('alert');
    const current = screen.getByLabelText(/current password/i);
    const next = screen.getByLabelText(/new password/i);

    expect(current.getAttribute('aria-describedby')).toBe(alert.id);
    expect(next.getAttribute('aria-describedby')).toBeNull();
    // And it sits below the field it is about, not below both of them.
    expect(alert.compareDocumentPosition(next)).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
  });

  it('places a refused new password below the new-password field', async () => {
    renderScreen(refusedWith(WEAK_PASSWORD, 'A password must be at least 12 characters.', 422));

    fill(CURRENT, 'short');
    submit();

    const alert = await screen.findByRole('alert');
    const next = screen.getByLabelText(/new password/i);

    expect(next.getAttribute('aria-describedby')).toBe(alert.id);
    expect(screen.getByLabelText(/current password/i).getAttribute('aria-describedby')).toBeNull();
    expect(next.compareDocumentPosition(alert)).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
  });

  it('shows exactly one alert at a time', async () => {
    // The error node has three possible slots and only one of them may ever be
    // filled; two live regions would announce the same sentence twice.
    renderScreen(refusedWith(NETWORK_ERROR, 'Could not reach the server.', 0));

    fill(CURRENT, NEXT);
    submit();

    await screen.findByRole('alert');
    expect(screen.getAllByRole('alert')).toHaveLength(1);
  });

  it('marks neither field when the request never reached the API', async () => {
    // Marking an input invalid because the network dropped tells a
    // screen-reader user their typing was malformed when it was not.
    renderScreen(refusedWith(NETWORK_ERROR, 'Could not reach the server.', 0));

    fill(CURRENT, NEXT);
    submit();

    const alert = await screen.findByRole('alert');
    expect(screen.getByLabelText(/current password/i).getAttribute('aria-invalid')).toBe('false');
    expect(screen.getByLabelText(/new password/i).getAttribute('aria-invalid')).toBe('false');
    expect(screen.queryByText('Saved.')).toBeNull();
    // And it lands *after* both fields rather than under one of them. This is
    // the third of the three slots and the only one whose position nothing
    // checked: parked under the current-password box, a sentence about the
    // network would read as a verdict on what was typed there, which is the
    // whole reason `fieldAtFault` exists.
    const newField = screen.getByLabelText(/new password/i);
    expect(newField.compareDocumentPosition(alert) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('refuses a blank field before it sends anything', async () => {
    const changeOwnPassword = accepted();
    renderScreen(changeOwnPassword);

    fill('', NEXT);
    submit();

    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain('current password');
    expect(changeOwnPassword).not.toHaveBeenCalled();
    expect(document.activeElement).toBe(screen.getByLabelText(/current password/i));
  });

  it('refuses a blank new password before it sends anything', async () => {
    const changeOwnPassword = accepted();
    renderScreen(changeOwnPassword);

    fill(CURRENT, '   ');
    submit();

    await screen.findByRole('alert');
    expect(changeOwnPassword).not.toHaveBeenCalled();
    expect(document.activeElement).toBe(screen.getByLabelText(/new password/i));
  });

  it('retires the confirmation as soon as a field is edited again', async () => {
    // "Saved." describes a change that has landed. The moment a box is edited it
    // is sitting beside something that has not, which reads as though the new
    // typing had been saved too.
    renderScreen(accepted());

    fill(CURRENT, NEXT);
    submit();
    await screen.findByText('Saved.');

    fireEvent.change(screen.getByLabelText(/current password/i), {
      target: { value: 'something-else-entirely' },
    });

    expect(screen.queryByText('Saved.')).toBeNull();
  });

  it('retires the confirmation when the new-password field is edited too', async () => {
    renderScreen(accepted());

    fill(CURRENT, NEXT);
    submit();
    await screen.findByText('Saved.');

    fireEvent.change(screen.getByLabelText(/new password/i), { target: { value: 'another-one' } });

    expect(screen.queryByText('Saved.')).toBeNull();
  });

  it('disables Back while the change is in flight', async () => {
    // Left live, a click unmounts the screen with the request still open: the
    // change lands or fails and the user sees neither.
    const { changeOwnPassword, release } = pending();
    renderScreen(changeOwnPassword);

    fill(CURRENT, NEXT);
    submit();

    const back = screen.getByRole('button', { name: /^back$/i });
    await waitFor(() => expect((back as HTMLButtonElement).disabled).toBe(true));

    release();
    await waitFor(() => expect((back as HTMLButtonElement).disabled).toBe(false));
  });

  it('drops a previous success the moment a new attempt starts', async () => {
    // Left up, "Saved." would sit beside the next rejection and read as though
    // something had landed.
    const { changeOwnPassword, release } = pending();
    renderScreen(changeOwnPassword);

    fill(CURRENT, NEXT);
    submit();
    release();
    await screen.findByText('Saved.');

    fill(CURRENT, NEXT);
    submit();

    await waitFor(() => expect(screen.queryByText('Saved.')).toBeNull());
  });

  it('drops a previous success when the next press is refused before it sends', async () => {
    // The reachable half of the rule above, in two clicks: a successful change
    // empties both boxes, so pressing the button again is a blank-field
    // refusal — and that path returns before the request is ever made. With
    // "Saved." cleared only at the point a request starts, the screen showed
    // "Enter your current password." and "Saved." side by side.
    const { changeOwnPassword, release } = pending();
    renderScreen(changeOwnPassword);

    fill(CURRENT, NEXT);
    submit();
    release();
    await screen.findByText('Saved.');

    submit();

    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain('current password');
    expect(screen.queryByText('Saved.')).toBeNull();
    expect(changeOwnPassword).toHaveBeenCalledTimes(1);
  });
});

// --- Reaching it, and leaving it ---------------------------------------------

interface Reply {
  status: number;
  body?: unknown;
}

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

describe('reaching account settings from the shell', () => {
  it('opens on the app bar control and returns on Back', async () => {
    // The real provider, so this exercises the gate's section state rather than
    // a stub of it.
    session.value = null;
    stubFetch({ '/api/auth/session': [{ status: 200, body: STAFF }] });
    render(<App />);

    fireEvent.click(await screen.findByRole('button', { name: /^account$/i }));

    expect(await screen.findByRole('heading', { level: 1, name: 'Account' })).toBeTruthy();
    // The shell stays around it: the app bar, and therefore the way out of the
    // app, is never taken away by opening a screen.
    expect(screen.getByTestId('app-bar')).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: /^back$/i }));

    expect(await screen.findByText(/Signed in as Kasun Perera/)).toBeTruthy();
    expect(screen.queryByLabelText(/current password/i)).toBeNull();
  });

  it('moves focus to the main region on the swap', async () => {
    // Swapping one surface for another unmounts whatever had focus, which would
    // otherwise leave a keyboard user on `<body>` at the top of a page they did
    // not ask to be at the top of.
    session.value = null;
    stubFetch({ '/api/auth/session': [{ status: 200, body: STAFF }] });
    render(<App />);

    fireEvent.click(await screen.findByRole('button', { name: /^account$/i }));

    await waitFor(() => expect(document.activeElement).toBe(screen.getByTestId('app-main')));
  });

  it('posts both fields to the change endpoint and stores what comes back', async () => {
    // `changeOwnPassword` is the only code that calls this endpoint, and every
    // screen test above mocks the provider — so without this the suite asserts a
    // `vi.fn()`'s arguments and nothing at all about what goes on the wire.
    // Renaming the body keys to camelCase, or pointing the call at
    // `/auth/password`, would ship with all of it green.
    const renamed = { ...STAFF, name: 'Kasun P. Perera', updated_at: '2026-09-18T09:00:00Z' };
    session.value = null;
    const { calls } = stubFetch({
      '/api/auth/session': [{ status: 200, body: STAFF }],
      '/api/auth/password/change': [{ status: 200, body: renamed }],
    });
    render(<App />);

    fireEvent.click(await screen.findByRole('button', { name: /^account$/i }));
    await screen.findByLabelText(/current password/i);
    fill(CURRENT, NEXT);
    submit();
    await screen.findByText('Saved.');

    const change = calls.filter(([url]) => url === '/api/auth/password/change');
    expect(change).toHaveLength(1);
    expect(change[0]?.[1].method).toBe('POST');
    // The cookie is what authenticates it; nothing else is sent.
    expect(change[0]?.[1].credentials).toBe('same-origin');
    expect(change[0]?.[1].headers).toEqual({ 'content-type': 'application/json' });
    // Snake case, both fields, and nothing else — the API forbids an extra key.
    expect(JSON.parse(String(change[0]?.[1].body))).toEqual({
      current_password: CURRENT,
      new_password: NEXT,
    });

    // And the `User` the server returned replaced the cached one: the home panel
    // greets the name that came back, without a second session request.
    fireEvent.click(screen.getByRole('button', { name: /^back$/i }));
    expect(await screen.findByText(/Signed in as Kasun P. Perera/)).toBeTruthy();
  });

  it('reports a refusal that comes back from the real endpoint', async () => {
    // The point of `changeOwnPassword` is the one thing nothing drove through
    // it: the screen's whole failure branch — the API's sentence, the invalid
    // field, the focus move, and *no* "Saved." — is reached only if the real
    // method rejects. Every failure case above hands the screen a mocked
    // provider that throws a hand-built error, so wrapping the `apiRequest` call
    // in `try { … } catch { return; }` leaves the entire suite green while the
    // screen confirms a password change that the server refused.
    session.value = null;
    stubFetch({
      '/api/auth/session': [{ status: 200, body: STAFF }],
      '/api/auth/password/change': [
        {
          status: 403,
          body: { error: { code: 'invalid_current_password', message: WRONG_CURRENT } },
        },
      ],
    });
    render(<App />);

    fireEvent.click(await screen.findByRole('button', { name: /^account$/i }));
    await screen.findByLabelText(/current password/i);
    fill(CURRENT, NEXT);
    submit();

    expect((await screen.findByRole('alert')).textContent).toBe(WRONG_CURRENT);
    expect(screen.queryByText('Saved.')).toBeNull();
    const current = screen.getByLabelText(/current password/i);
    expect(current.getAttribute('aria-invalid')).toBe('true');
    expect(document.activeElement).toBe(current);
    // Neither value is thrown away: the user retypes one field, not both.
    expect((current as HTMLInputElement).value).toBe(CURRENT);
    expect((screen.getByLabelText(/new password/i) as HTMLInputElement).value).toBe(NEXT);
  });

  it('does not report a change as saved when the body that comes back is not a user', async () => {
    // `changeOwnPassword` stores the response through `asUser`, which throws on
    // a body it does not recognise. That throw has to reach the screen as a
    // failure like any other — swallowed, the screen would say "Saved." while
    // the cached user still describes the account as it was.
    session.value = null;
    stubFetch({
      '/api/auth/session': [{ status: 200, body: STAFF }],
      '/api/auth/password/change': [{ status: 200, body: { id: STAFF.id } }],
    });
    render(<App />);

    fireEvent.click(await screen.findByRole('button', { name: /^account$/i }));
    await screen.findByLabelText(/current password/i);
    fill(CURRENT, NEXT);
    submit();

    // The sentence, not merely a node: blanked, `asUser`'s refusal would render
    // as an empty red paragraph after a failed change and a presence-only
    // assertion would still pass. Every other failure case here pins its words.
    expect((await screen.findByRole('alert')).textContent).toBe(
      'The server returned an unexpected response.',
    );
    expect(screen.queryByText('Saved.')).toBeNull();
  });

  it('keeps a sign-out failure up when Account is pressed on the account screen', async () => {
    // The bar keeps its Account control here, so the control is pressable while
    // its own screen is showing. That press changes nothing on screen, and it
    // must not quietly clear the alert either — a dismissal nobody can see
    // coming, reachable only through a button that otherwise looks broken.
    session.value = null;
    stubFetch({
      '/api/auth/session': [{ status: 200, body: STAFF }],
      '/api/auth/logout': [{ status: 500, body: null }],
    });
    render(<App />);

    fireEvent.click(await screen.findByRole('button', { name: /^account$/i }));
    await screen.findByLabelText(/current password/i);
    fireEvent.click(screen.getByRole('button', { name: /sign out/i }));
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toBe(SIGN_OUT_FAILED);

    fireEvent.click(screen.getByRole('button', { name: /^account$/i }));

    // Still on the account screen, and still holding the failure.
    expect(screen.getByLabelText(/current password/i)).toBeTruthy();
    expect(screen.getByRole('alert').textContent).toBe(SIGN_OUT_FAILED);
  });

  it('is not still open for the next person after a sign-out and a fresh sign-in', async () => {
    // `Gate` is one component with conditional returns, so nothing unmounts the
    // section on the way out. Left set, the next person to sign in on a shared
    // shop-floor handset lands on a password form.
    session.value = null;
    stubFetch({
      '/api/auth/session': [{ status: 200, body: STAFF }],
      '/api/auth/logout': [{ status: 204 }],
      '/api/auth/login': [{ status: 200, body: STAFF }],
    });
    render(<App />);

    fireEvent.click(await screen.findByRole('button', { name: /^account$/i }));
    await screen.findByRole('heading', { level: 1, name: 'Account' });

    fireEvent.click(screen.getByRole('button', { name: /sign out/i }));
    await screen.findByLabelText(/^password$/i);

    fireEvent.change(screen.getByLabelText(/email/i), { target: { value: 'kasun@rocell.lk' } });
    fireEvent.change(screen.getByLabelText(/^password$/i), { target: { value: NEXT } });
    fireEvent.click(screen.getByRole('button', { name: /^sign in$/i }));

    expect(await screen.findByRole('heading', { name: /^scan$/i })).toBeTruthy();
    expect(screen.queryByRole('heading', { level: 1, name: 'Account' })).toBeNull();
    expect(screen.queryByLabelText(/current password/i)).toBeNull();
  });

  it('shows a failed sign-out on the screen the click was made on', async () => {
    // The app bar's sign-out is forwarded here too, so a failure raised here has
    // to be visible here. Reported only on the home panel it was silent, and
    // pressing Back then showed an alert about a click made on another screen.
    session.value = null;
    stubFetch({
      '/api/auth/session': [{ status: 200, body: STAFF }],
      '/api/auth/logout': [
        {
          status: 500,
          body: { error: { code: 'internal_error', message: 'An unexpected error occurred.' } },
        },
      ],
    });
    render(<App />);

    fireEvent.click(await screen.findByRole('button', { name: /^account$/i }));
    await screen.findByRole('heading', { level: 1, name: 'Account' });

    fireEvent.click(screen.getByRole('button', { name: /sign out/i }));

    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain('An unexpected error occurred.');
    // Still here — the failed revocation left the session alive, so the screen
    // must not have moved.
    expect(screen.getByRole('heading', { level: 1, name: 'Account' })).toBeTruthy();
  });

  it('leaves the failure behind when the surface changes', async () => {
    // The other half of the same rule: an alert about a click made on Account
    // must not follow the user to the home panel.
    session.value = null;
    stubFetch({
      '/api/auth/session': [{ status: 200, body: STAFF }],
      '/api/auth/logout': [
        {
          status: 500,
          body: { error: { code: 'internal_error', message: 'An unexpected error occurred.' } },
        },
      ],
    });
    render(<App />);

    fireEvent.click(await screen.findByRole('button', { name: /^account$/i }));
    fireEvent.click(await screen.findByRole('button', { name: /sign out/i }));
    await screen.findByRole('alert');

    fireEvent.click(screen.getByRole('button', { name: /^back$/i }));

    expect(await screen.findByText(/Signed in as Kasun Perera/)).toBeTruthy();
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('renders no second main landmark inside the shell', async () => {
    // The screen deliberately carries no `<main>` of its own — `AppShell`
    // already provides the one the focus effect above targets.
    session.value = null;
    stubFetch({ '/api/auth/session': [{ status: 200, body: STAFF }] });
    render(<App />);

    fireEvent.click(await screen.findByRole('button', { name: /^account$/i }));
    await screen.findByRole('heading', { level: 1, name: 'Account' });

    expect(screen.getAllByRole('main')).toHaveLength(1);
  });
});
