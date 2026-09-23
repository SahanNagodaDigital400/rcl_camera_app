/**
 * The gate: which screen `App` renders, and what it takes to move between them.
 *
 * This is the only test in the suite that drives the real
 * `SessionProvider` and the real `api/client` against a stubbed `fetch`, so it
 * is where the `/api` prefix, the same-origin credential mode and the `isUser`
 * narrowing are actually exercised.
 */
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { User } from '@rocell/schema/user';

import App from '../App';

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const STAFF: User = {
  id: '3f1a6b2c-9d4e-4f70-8a11-5c2e7b9d0a34',
  name: 'Kasun Perera',
  email: 'kasun@rocell.lk',
  role: 'staff',
  active: true,
  must_change_password: false,
  temp_credential_expires_at: null,
  last_login_at: null,
  locked_until: null,
  created_at: '2026-09-17T08:00:00Z',
  updated_at: '2026-09-17T08:00:00Z',
};

/**
 * The same account before it has claimed its temporary credential.
 *
 * `must_change_password` is the only difference, and it is the whole of what
 * decides which screen renders.
 */
const UNCLAIMED: User = {
  ...STAFF,
  must_change_password: true,
  temp_credential_expires_at: '2026-09-20T08:00:00Z',
};

interface Reply {
  status: number;
  body?: unknown;
}

const unauthorized: Reply = {
  status: 401,
  body: { error: { code: 'unauthorized', message: 'Not signed in.' } },
};

/**
 * Replace `fetch` with a queue keyed by path, and record every call.
 *
 * `vi.stubGlobal` rather than assigning: jsdom does not implement `fetch`, so
 * the global may not be there to spy on in the first place.
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

function fillAndSubmit(): void {
  fireEvent.change(screen.getByLabelText(/email/i), {
    target: { value: 'kasun@rocell.lk' },
  });
  fireEvent.change(screen.getByLabelText(/password/i), {
    target: { value: 'a-long-enough-password' },
  });
  fireEvent.click(screen.getByRole('button', { name: /^sign in$/i }));
}

function setNewPassword(value: string): void {
  fireEvent.change(screen.getByLabelText(/new password/i), { target: { value } });
  fireEvent.click(screen.getByRole('button', { name: /^set password$/i }));
}

describe('the session gate', () => {
  it('renders the login screen while signed out', async () => {
    stubFetch({ '/api/auth/session': [unauthorized] });
    render(<App />);

    expect(await screen.findByLabelText(/password/i)).toBeTruthy();
    expect(screen.queryByTestId('app-bar')).toBeNull();
  });

  it('bootstraps from the session endpoint behind the /api prefix', async () => {
    const { calls } = stubFetch({ '/api/auth/session': [unauthorized] });
    render(<App />);

    await screen.findByLabelText(/password/i);
    expect(calls[0]?.[0]).toBe('/api/auth/session');
    // The cookie is what carries the session. Nothing else does.
    expect(calls[0]?.[1].credentials).toBe('same-origin');
  });

  it('renders the shell once the session is real', async () => {
    stubFetch({ '/api/auth/session': [{ status: 200, body: STAFF }] });
    render(<App />);

    expect(await screen.findByTestId('app-bar')).toBeTruthy();
    expect(screen.queryByLabelText(/password/i)).toBeNull();
  });

  it('greets the signed-in user by name', async () => {
    // If this name is right, the cookie, the session row and the per-request
    // lookup all worked.
    stubFetch({ '/api/auth/session': [{ status: 200, body: STAFF }] });
    render(<App />);

    // Scan is the landing surface; the greeting lives on the home panel,
    // one press of the nav's Home entry away.
    fireEvent.click(await screen.findByRole('button', { name: /^home$/i }));

    expect(await screen.findByText(/Kasun Perera/)).toBeTruthy();
  });

  it('moves from the login screen to the shell on a successful sign-in', async () => {
    stubFetch({
      '/api/auth/session': [unauthorized],
      '/api/auth/login': [{ status: 200, body: STAFF }],
    });
    render(<App />);
    await screen.findByLabelText(/password/i);

    fillAndSubmit();

    expect(await screen.findByTestId('app-bar')).toBeTruthy();
  });

  it('stays on the login screen when the credential is rejected', async () => {
    stubFetch({
      '/api/auth/session': [unauthorized],
      '/api/auth/login': [
        {
          status: 401,
          body: { error: { code: 'unauthorized', message: 'Email or password is incorrect.' } },
        },
      ],
    });
    render(<App />);
    await screen.findByLabelText(/password/i);

    fillAndSubmit();

    expect((await screen.findByRole('alert')).textContent).toBe('Email or password is incorrect.');
    expect(screen.queryByTestId('app-bar')).toBeNull();
  });

  it('refuses a body that is not the shared User contract', async () => {
    // A partial render of a body the contract rejects is how a field the API
    // stopped sending becomes `undefined` on screen instead of an error.
    stubFetch({
      '/api/auth/session': [unauthorized],
      '/api/auth/login': [{ status: 200, body: { id: STAFF.id, name: STAFF.name } }],
    });
    render(<App />);
    await screen.findByLabelText(/password/i);

    fillAndSubmit();

    expect(await screen.findByRole('alert')).toBeTruthy();
    expect(screen.queryByTestId('app-bar')).toBeNull();
  });

  it('returns to the login screen after signing out', async () => {
    stubFetch({
      '/api/auth/session': [{ status: 200, body: STAFF }],
      '/api/auth/logout': [{ status: 204 }],
    });
    render(<App />);
    await screen.findByTestId('app-bar');

    fireEvent.click(screen.getByRole('button', { name: /sign out/i }));

    expect(await screen.findByLabelText(/password/i)).toBeTruthy();
    expect(screen.queryByTestId('app-bar')).toBeNull();
  });

  it('revokes the session on the server when signing out', async () => {
    // The product's only server-side revocation. Dropping the method — or the
    // call — would leave the login screen showing and the cookie live, and a
    // check that only looked at which screen is rendered would not notice.
    const { calls } = stubFetch({
      '/api/auth/session': [{ status: 200, body: STAFF }],
      '/api/auth/logout': [{ status: 204 }],
    });
    render(<App />);
    await screen.findByTestId('app-bar');

    fireEvent.click(screen.getByRole('button', { name: /sign out/i }));
    await screen.findByLabelText(/password/i);

    const logout = calls.filter(([url]) => url === '/api/auth/logout');
    expect(logout).toHaveLength(1);
    expect(logout[0]?.[1].method).toBe('POST');
    expect(logout[0]?.[1].credentials).toBe('same-origin');
  });

  it('stays signed in when the server did not accept the sign-out', async () => {
    // The session is the server's row. Clearing local state on a failed
    // revocation shows the login screen to someone still holding a valid
    // cookie, and one reload signs them straight back in.
    stubFetch({
      '/api/auth/session': [{ status: 200, body: STAFF }],
      '/api/auth/logout': [
        {
          status: 500,
          body: { error: { code: 'internal_error', message: 'Sign-out could not be recorded.' } },
        },
      ],
    });
    render(<App />);
    await screen.findByTestId('app-bar');

    fireEvent.click(screen.getByRole('button', { name: /sign out/i }));

    expect((await screen.findByRole('alert')).textContent).toBe('Sign-out could not be recorded.');
    expect(screen.getByTestId('app-bar')).toBeTruthy();
    expect(screen.queryByLabelText(/password/i)).toBeNull();
  });

  it('posts the typed credential as JSON when signing in', async () => {
    const { calls } = stubFetch({
      '/api/auth/session': [unauthorized],
      '/api/auth/login': [{ status: 200, body: STAFF }],
    });
    render(<App />);
    await screen.findByLabelText(/password/i);

    fillAndSubmit();
    await screen.findByTestId('app-bar');

    const login = calls.filter(([url]) => url === '/api/auth/login');
    expect(login).toHaveLength(1);
    expect(login[0]?.[1].method).toBe('POST');
    // The content type belongs with the method and the body: the API's request
    // model refuses a body labelled anything else, so dropping this header
    // turns every sign-in into a 422 that no other assertion here would see.
    expect(login[0]?.[1].headers).toEqual({ 'content-type': 'application/json' });
    expect(JSON.parse(String(login[0]?.[1].body))).toEqual({
      email: 'kasun@rocell.lk',
      password: 'a-long-enough-password',
    });
  });

  it('keeps a main landmark on screen while the session is being checked', async () => {
    // The bootstrap is the first thing anybody arriving at the app meets. An
    // explicit `role` replaces an element's implicit one, so a `role="status"`
    // <main> is not a main landmark and there is nothing for a screen reader
    // to skip to for the whole of the request.
    stubFetch({ '/api/auth/session': [unauthorized] });
    render(<App />);

    expect(screen.getByRole('main')).toBeTruthy();
    expect(screen.getByRole('status').textContent).toMatch(/checking your session/i);

    await screen.findByLabelText(/password/i);
  });

  it('moves focus to the main region on every screen swap', async () => {
    // Every swap unmounts whatever had focus — the submit button on the way in,
    // the sign-out button on the way out — and focus would otherwise fall to
    // <body>, stranding a keyboard or screen-reader user at the top of a page
    // they did not navigate to.
    //
    // The middle hop is the one an effect keyed on `status` cannot see: the
    // change screen and the shell are both `'signed-in'`, so only
    // `must_change_password` changes and the status never fires the effect.
    stubFetch({
      '/api/auth/session': [unauthorized],
      '/api/auth/login': [{ status: 200, body: UNCLAIMED }],
      '/api/auth/password': [{ status: 200, body: STAFF }],
      '/api/auth/logout': [{ status: 204 }],
    });
    render(<App />);
    await screen.findByLabelText(/^password$/i);

    // login -> forced change
    fillAndSubmit();
    await screen.findByLabelText(/new password/i);
    await waitFor(() => expect(document.activeElement?.tagName).toBe('MAIN'));

    // forced change -> shell
    setNewPassword('a-long-enough-password');
    const main = await screen.findByTestId('app-main');
    await waitFor(() => expect(document.activeElement).toBe(main));

    // shell -> login
    fireEvent.click(screen.getByRole('button', { name: /sign out/i }));
    await screen.findByLabelText(/^password$/i);
    await waitFor(() => expect(document.activeElement?.tagName).toBe('MAIN'));
  });

  it('does not steal focus when the bootstrap resolves', async () => {
    // The page has just loaded. Moving focus on arrival is its own failure.
    stubFetch({ '/api/auth/session': [unauthorized] });
    render(<App />);

    await screen.findByLabelText(/password/i);
    expect(document.activeElement).toBe(document.body);
  });

  it('announces the bootstrap wait rather than only marking it busy', () => {
    // `aria-busy` says a region is changing and nothing about what is
    // happening; `role="status"` is what reads the sentence out. They sit on
    // different elements on purpose — see the landmark test above.
    stubFetch({ '/api/auth/session': [unauthorized] });
    render(<App />);

    expect(screen.getByRole('status').textContent).toContain('Checking your session');
    expect(screen.getByRole('main').getAttribute('aria-busy')).toBe('true');
  });

  it('logs no console error while gating', async () => {
    // The root-level guard the shell test used to carry. Without it a React
    // warning from App, SessionProvider or the gate itself is invisible.
    const spy = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    stubFetch({
      '/api/auth/session': [unauthorized],
      '/api/auth/login': [{ status: 200, body: STAFF }],
    });

    render(<App />);
    await screen.findByLabelText(/password/i);
    fillAndSubmit();
    await screen.findByTestId('app-bar');
    cleanup();

    expect(spy.mock.calls).toEqual([]);
  });

  it('shows the login screen, not a blank page, when the bootstrap fails outright', async () => {
    // A network failure at boot must not leave the app with nothing on screen
    // and no way forward.
    vi.stubGlobal('fetch', () => Promise.reject(new Error('offline')));
    render(<App />);

    expect(await screen.findByLabelText(/password/i)).toBeTruthy();
  });

  it('never leaves the loading placeholder on screen', async () => {
    stubFetch({ '/api/auth/session': [unauthorized] });
    render(<App />);

    await screen.findByLabelText(/password/i);
    await waitFor(() => expect(document.querySelector('[aria-busy]')).toBeNull());
  });
});

describe('the forced password change traps the app', () => {
  it('renders the change screen when the bootstrap reports the flag', async () => {
    stubFetch({ '/api/auth/session': [{ status: 200, body: UNCLAIMED }] });
    render(<App />);

    expect(await screen.findByLabelText(/new password/i)).toBeTruthy();
  });

  it('does not put the shell in the document while the flag is set', async () => {
    // Not "hides it" — with no router the shell is simply not rendered, so
    // there is nothing to navigate to and nothing to intercept. The app bar and
    // the sign-out control are what the shell brings with it, and neither is
    // here.
    stubFetch({ '/api/auth/session': [{ status: 200, body: UNCLAIMED }] });
    render(<App />);

    await screen.findByLabelText(/new password/i);
    expect(screen.queryByTestId('app-bar')).toBeNull();
    expect(screen.queryByTestId('app-main')).toBeNull();
    expect(screen.queryByRole('button', { name: /sign out/i })).toBeNull();
  });

  it('goes to the change screen when a sign-in returns the flag', async () => {
    // The other way in: a user who was signed out, signing in on a temporary
    // credential. The login screen must not hand them the shell.
    stubFetch({
      '/api/auth/session': [unauthorized],
      '/api/auth/login': [{ status: 200, body: UNCLAIMED }],
    });
    render(<App />);
    await screen.findByLabelText(/^password$/i);

    fillAndSubmit();

    expect(await screen.findByLabelText(/new password/i)).toBeTruthy();
    expect(screen.queryByTestId('app-bar')).toBeNull();
  });

  it('posts the new password to the API', async () => {
    const { calls } = stubFetch({
      '/api/auth/session': [{ status: 200, body: UNCLAIMED }],
      '/api/auth/password': [{ status: 200, body: STAFF }],
    });
    render(<App />);
    await screen.findByLabelText(/new password/i);

    setNewPassword('a-long-enough-password');
    await screen.findByTestId('app-bar');

    const change = calls.filter(([url]) => url === '/api/auth/password');
    expect(change).toHaveLength(1);
    expect(change[0]?.[1].method).toBe('POST');
    // The cookie is what authenticates it; nothing else is sent.
    expect(change[0]?.[1].credentials).toBe('same-origin');
    expect(change[0]?.[1].headers).toEqual({ 'content-type': 'application/json' });
    expect(JSON.parse(String(change[0]?.[1].body))).toEqual({
      new_password: 'a-long-enough-password',
    });
  });

  it('swaps straight to the shell on success, with no interstitial', async () => {
    // EXPERIENCE.md line 88: the transition is immediate — no "your password is
    // set" screen to click through.
    stubFetch({
      '/api/auth/session': [{ status: 200, body: UNCLAIMED }],
      '/api/auth/password': [{ status: 200, body: STAFF }],
    });
    render(<App />);
    await screen.findByLabelText(/new password/i);

    setNewPassword('a-long-enough-password');

    expect(await screen.findByTestId('app-bar')).toBeTruthy();
    expect(screen.queryByLabelText(/new password/i)).toBeNull();
  });

  it('stays on the change screen when the password is refused', async () => {
    stubFetch({
      '/api/auth/session': [{ status: 200, body: UNCLAIMED }],
      '/api/auth/password': [
        {
          status: 422,
          body: {
            error: {
              code: 'weak_password',
              message: 'A password must be at least 12 characters.',
            },
          },
        },
      ],
    });
    render(<App />);
    await screen.findByLabelText(/new password/i);

    setNewPassword('short');

    // The API's own sentence, naming the rule (EXPERIENCE.md:87).
    expect((await screen.findByRole('alert')).textContent).toBe(
      'A password must be at least 12 characters.',
    );
    expect(screen.queryByTestId('app-bar')).toBeNull();
  });

  it('refuses a body that is not the shared User contract', async () => {
    // The same failure mode the sign-in path has: a partial render of a body the
    // contract rejects is how a field the API stopped sending becomes
    // `undefined` on screen instead of an error.
    stubFetch({
      '/api/auth/session': [{ status: 200, body: UNCLAIMED }],
      '/api/auth/password': [{ status: 200, body: { id: STAFF.id, name: STAFF.name } }],
    });
    render(<App />);
    await screen.findByLabelText(/new password/i);

    setNewPassword('a-long-enough-password');

    expect(await screen.findByRole('alert')).toBeTruthy();
    expect(screen.queryByTestId('app-bar')).toBeNull();
  });

  it('falls back to the login screen when the session dies mid-change', async () => {
    // The change screen carries no sign-out control and no dismissal by design,
    // so a 401 that left the user on it would leave clearing cookies as the only
    // way out of the app. EXPERIENCE.md's state table sends an expired session
    // to Login.
    stubFetch({
      '/api/auth/session': [{ status: 200, body: UNCLAIMED }],
      '/api/auth/password': [unauthorized],
    });
    render(<App />);
    await screen.findByLabelText(/new password/i);

    setNewPassword('a-long-enough-password');

    expect(await screen.findByLabelText(/^password$/i)).toBeTruthy();
    expect(screen.queryByLabelText(/new password/i)).toBeNull();
  });

  it('falls back to the login screen when the account was already claimed', async () => {
    // `password_change_not_required` means the cached user is stale — its
    // `must_change_password` is a lie, so keeping it would re-render the screen
    // that just failed, forever. The account has a real password now, and Login
    // is where one is used.
    stubFetch({
      '/api/auth/session': [{ status: 200, body: UNCLAIMED }],
      '/api/auth/password': [
        {
          status: 409,
          body: {
            error: {
              code: 'password_change_not_required',
              message: 'This account already has a password of its own.',
            },
          },
        },
      ],
    });
    render(<App />);
    await screen.findByLabelText(/new password/i);

    setNewPassword('a-long-enough-password');

    expect(await screen.findByLabelText(/^password$/i)).toBeTruthy();
  });

  it('keeps the user on the change screen for a failure they can retry', async () => {
    // The mirror image, and why the two above are a branch rather than a blanket
    // reset: a refused password is fixable in place, and dropping to the login
    // screen would throw away a session that is still perfectly good.
    stubFetch({
      '/api/auth/session': [{ status: 200, body: UNCLAIMED }],
      '/api/auth/password': [
        {
          status: 422,
          body: {
            error: { code: 'weak_password', message: 'A password must be at least 12 characters.' },
          },
        },
      ],
    });
    render(<App />);
    await screen.findByLabelText(/new password/i);

    setNewPassword('short');

    await screen.findByRole('alert');
    expect(screen.getByLabelText(/new password/i)).toBeTruthy();
    expect(screen.queryByLabelText(/^password$/i)).toBeNull();
  });

  it('logs no console error while trapped', async () => {
    const spy = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    stubFetch({
      '/api/auth/session': [{ status: 200, body: UNCLAIMED }],
      '/api/auth/password': [{ status: 200, body: STAFF }],
    });

    render(<App />);
    await screen.findByLabelText(/new password/i);
    setNewPassword('a-long-enough-password');
    await screen.findByTestId('app-bar');
    cleanup();

    expect(spy.mock.calls).toEqual([]);
  });
});
