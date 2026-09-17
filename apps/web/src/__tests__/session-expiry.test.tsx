/**
 * What the app does when the server stops honouring the cookie.
 *
 * DW-37's gap was not that one screen forgot about expiry — it was that
 * nothing in the app ever found out. Two mechanisms close it, and both are
 * driven here through the real `SessionProvider` and the real `api/client`
 * against a stubbed `fetch`:
 *
 *  1. `onUnauthorized` in `api/client`, so *any* request's 401 drops the shell.
 *  2. `visibilitychange`, so a tab brought back from hours in the background
 *     finds out without the user having to click something first.
 *
 * The last test in the file is the one that has to keep failing if a poll is
 * ever added: a timer that re-checks the session is itself an authenticated
 * request, so it would slide `last_seen_at` forward forever and keep an
 * unattended tab signed in — defeating the 12-hour idle window these tests
 * exist to surface.
 */
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { User } from '@rocell/schema/user';

import { ApiRequestError, UNAUTHORIZED, apiRequest, onUnauthorized } from '../api/client';
import App from '../App';

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.useRealTimers();
  visible('visible');
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

/** The same account before it has claimed its admin-issued temporary credential. */
const UNCLAIMED: User = {
  ...STAFF,
  must_change_password: true,
  temp_credential_expires_at: '2026-09-20T08:00:00Z',
};

interface Reply {
  status: number;
  body?: unknown;
  /**
   * Hold this reply until the promise settles.
   *
   * One test needs two requests in flight at once with a decided order between
   * their answers. Everything else leaves it unset and is answered immediately.
   */
  after?: Promise<unknown>;
}

/** What the API answers for an expired, revoked or deactivated session alike. */
const unauthorized: Reply = {
  status: 401,
  body: { error: { code: 'unauthorized', message: 'Not signed in.' } },
};

/** The sentence the login screen shows when a session that existed has ended. */
const NOTICE = /your session has ended/i;

/**
 * Replace `fetch` with a queue keyed by path, and record every call.
 *
 * The same shape `auth-gating.test.tsx` uses: a single reply is answered
 * forever, a queue of several is consumed one per call.
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

    const answer = {
      ok: reply.status >= 200 && reply.status < 300,
      status: reply.status,
      json: () => Promise.resolve(reply.body ?? null),
    } as Response;

    return reply.after ? reply.after.then(() => answer) : Promise.resolve(answer);
  });

  return { calls };
}

/**
 * Drain the promise chain a request would have to travel to be recorded.
 *
 * The three tests below assert that **no** request was made, and a single
 * `await Promise.resolve()` drains one microtask turn — a request issued from
 * a `.then` two links down would land after the assertion had already passed,
 * and the absence would mean nothing. A revalidation travels `apiRequest` ->
 * `fetch` -> `response.json()`, so five turns is comfortably past the point
 * where one would have shown up in `calls`.
 *
 * Deliberately microtasks only, with no `setTimeout` anywhere in this file:
 * the story's own verification greps `apps/web/src` for timers and expects one
 * hit, the request timeout in `api/client.ts`. A flush helper written with a
 * timer would put a second hit in that grep and make a reviewer's one-line
 * check for "does anything poll the session" read false. The macrotask case is
 * covered where it belongs — by the fake-timer test at the bottom of this
 * file, which advances an hour and asserts nothing fires.
 */
async function settle(): Promise<void> {
  // Written out rather than looped: each turn has to follow the last, so
  // `Promise.all` would collapse them into one and defeat the point.
  await Promise.resolve();
  await Promise.resolve();
  await Promise.resolve();
  await Promise.resolve();
  await Promise.resolve();
}

/** jsdom's `visibilityState` is read-only; this is the supported way to move it. */
function visible(state: DocumentVisibilityState): void {
  Object.defineProperty(document, 'visibilityState', {
    configurable: true,
    get: () => state,
  });
}

/** Fill and submit the forced-change screen's one field. */
function setNewPassword(value: string): void {
  fireEvent.change(screen.getByLabelText(/new password/i), { target: { value } });
  fireEvent.click(screen.getByRole('button', { name: /^set password$/i }));
}

function sessionCalls(calls: [string, RequestInit][]): [string, RequestInit][] {
  return calls.filter(([url]) => url === '/api/auth/session');
}

describe('a 401 from any request drops the app to the login screen', () => {
  it('swaps the shell for the login screen and says the session ended', async () => {
    // Bootstrap succeeds, so the shell renders; the sign-out that follows is
    // refused with the same 401 an expired session gets. Any request would do
    // — that is the point of observing centrally rather than per screen.
    stubFetch({
      '/api/auth/session': [{ status: 200, body: STAFF }],
      '/api/auth/logout': [unauthorized],
    });
    render(<App />);
    await screen.findByTestId('app-bar');

    fireEvent.click(screen.getByRole('button', { name: /sign out/i }));

    expect(await screen.findByLabelText(/password/i)).toBeTruthy();
    expect(screen.queryByTestId('app-bar')).toBeNull();
    expect((await screen.findByText(NOTICE)).textContent).toMatch(NOTICE);
  });

  it('writes the notice as information rather than as a failure', async () => {
    // `role="status"`, not `role="alert"`. Nothing the user did went wrong, and
    // an assertive interruption would frame a routine expiry as an error.
    stubFetch({
      '/api/auth/session': [{ status: 200, body: STAFF }],
      '/api/auth/logout': [unauthorized],
    });
    render(<App />);
    await screen.findByTestId('app-bar');

    fireEvent.click(screen.getByRole('button', { name: /sign out/i }));
    await screen.findByLabelText(/password/i);

    expect(screen.getByRole('status').textContent).toMatch(NOTICE);
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('never says which of expiry, revocation or deactivation it was', async () => {
    // The API answers all three with one 401 and one message, on purpose. A
    // screen that guessed between them would leak what the server refused to
    // say.
    stubFetch({
      '/api/auth/session': [{ status: 200, body: STAFF }],
      '/api/auth/logout': [unauthorized],
    });
    render(<App />);
    await screen.findByTestId('app-bar');

    fireEvent.click(screen.getByRole('button', { name: /sign out/i }));
    const notice = await screen.findByText(NOTICE);

    expect(notice.textContent).not.toMatch(/expir|revok|deactivat|disabled|inactive/i);
  });

  it('drops to the login screen for a 401 that is not the shared envelope', async () => {
    // A proxy or a gateway answering 401 with its own HTML, or with nothing at
    // all, is still the server refusing the cookie. Keyed on the envelope's
    // *code* instead of the status, this case throws `malformed_response`, the
    // observer never fires, and the shell keeps rendering over a dead session
    // — the exact failure the observer exists to catch.
    stubFetch({
      '/api/auth/session': [{ status: 200, body: STAFF }],
      '/api/auth/logout': [{ status: 401, body: '<html>504 Gateway Timeout</html>' }],
    });
    render(<App />);
    await screen.findByTestId('app-bar');

    fireEvent.click(screen.getByRole('button', { name: /sign out/i }));

    expect(await screen.findByLabelText(/password/i)).toBeTruthy();
    expect(await screen.findByText(NOTICE)).toBeTruthy();
  });

  it('is inherited by a caller that never goes through the session context', async () => {
    // The claim the central registration makes: the first Epic 2 screen to
    // call `apiRequest` directly gets this behaviour without remembering it.
    // Every other case in this file drives an auth endpoint, so scoping the
    // notification to `/auth/*` would leave them all green and this one red.
    stubFetch({
      '/api/auth/session': [{ status: 200, body: STAFF }],
      '/api/catalogue/tiles': [unauthorized],
    });
    render(<App />);
    await screen.findByTestId('app-bar');

    await expect(apiRequest('/catalogue/tiles')).rejects.toThrow();

    expect(await screen.findByLabelText(/password/i)).toBeTruthy();
    expect(await screen.findByText(NOTICE)).toBeTruthy();
  });

  it('shows no notice for a rejected sign-in', async () => {
    // A wrong credential is an `unauthorized` too. The notice is only for a
    // session that *existed*: telling someone who mistyped their password that
    // they have been signed out is a lie about what just happened.
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

    fireEvent.change(screen.getByLabelText(/email/i), { target: { value: 'kasun@rocell.lk' } });
    fireEvent.change(screen.getByLabelText(/password/i), { target: { value: 'wrong-password' } });
    fireEvent.click(screen.getByRole('button', { name: /^sign in$/i }));

    expect((await screen.findByRole('alert')).textContent).toBe(
      'Email or password is incorrect.',
    );
    expect(screen.queryByText(NOTICE)).toBeNull();
  });

  it('shows no notice when the bootstrap simply finds no session', async () => {
    // Arriving signed out is the ordinary case, not an event. The 401 that
    // answers the bootstrap must not be reported as a session ending.
    stubFetch({ '/api/auth/session': [unauthorized] });
    render(<App />);

    await screen.findByLabelText(/password/i);
    expect(screen.queryByText(NOTICE)).toBeNull();
  });

  it('clears the notice once the user signs in again', async () => {
    // Left set, it would be on the login screen the next time the same user
    // signed out deliberately.
    stubFetch({
      '/api/auth/session': [{ status: 200, body: STAFF }],
      '/api/auth/logout': [unauthorized, { status: 204 }],
      '/api/auth/login': [{ status: 200, body: STAFF }],
    });
    render(<App />);
    await screen.findByTestId('app-bar');

    fireEvent.click(screen.getByRole('button', { name: /sign out/i }));
    await screen.findByText(NOTICE);

    fireEvent.change(screen.getByLabelText(/email/i), { target: { value: 'kasun@rocell.lk' } });
    fireEvent.change(screen.getByLabelText(/password/i), {
      target: { value: 'a-long-enough-password' },
    });
    fireEvent.click(screen.getByRole('button', { name: /^sign in$/i }));
    await screen.findByTestId('app-bar');

    fireEvent.click(screen.getByRole('button', { name: /sign out/i }));

    await screen.findByLabelText(/password/i);
    expect(screen.queryByText(NOTICE)).toBeNull();
  });

  it('carries no refused-sign-out message back into the shell', async () => {
    // The sign-out above is refused with a `401`, so two things happen to the
    // same click: the observer drops the app to login, and `signOut` rejects,
    // which is what `App`'s `handleSignOut` words as a message beside the
    // greeting. `Gate` is one component with conditional returns — nothing
    // unmounts on the swap — so without a reset that message is still there
    // when the user signs in again and the shell comes back, telling someone
    // who has just signed in that they are not signed in.
    stubFetch({
      '/api/auth/session': [{ status: 200, body: STAFF }],
      '/api/auth/logout': [unauthorized],
      '/api/auth/login': [{ status: 200, body: STAFF }],
    });
    render(<App />);
    await screen.findByTestId('app-bar');

    fireEvent.click(screen.getByRole('button', { name: /sign out/i }));
    await screen.findByText(NOTICE);

    fireEvent.change(screen.getByLabelText(/email/i), { target: { value: 'kasun@rocell.lk' } });
    fireEvent.change(screen.getByLabelText(/password/i), {
      target: { value: 'a-long-enough-password' },
    });
    fireEvent.click(screen.getByRole('button', { name: /^sign in$/i }));
    await screen.findByTestId('app-bar');

    expect(screen.queryByRole('alert')).toBeNull();
    expect(screen.queryByText(/not signed in/i)).toBeNull();
  });

  it('shows no notice when the user signs out deliberately', async () => {
    stubFetch({
      '/api/auth/session': [{ status: 200, body: STAFF }],
      '/api/auth/logout': [{ status: 204 }],
    });
    render(<App />);
    await screen.findByTestId('app-bar');

    fireEvent.click(screen.getByRole('button', { name: /sign out/i }));

    await screen.findByLabelText(/password/i);
    expect(screen.queryByText(NOTICE)).toBeNull();
  });

  it('carries no notice raised a screen ago into a deliberate sign-out', async () => {
    // The two cases above both reach `signOut` with the flag already down —
    // one never raises it, and the other signs in first, which clears it. So
    // neither holds `signOut`'s own `setSessionEnded(false)`, and a cleanup
    // that read that line as redundant would be green.
    //
    // It is not redundant, because one state latches the notice into a
    // *signed-in* app: a revalidation 401 lands while the forced change is in
    // flight, the observer raises the notice and drops the app to login, and
    // the change then succeeds and puts it straight back to signed-in with the
    // flag still set. `changePassword`'s success path does not clear it — and
    // must not clear it from the catch either, for the reason the pair of
    // tests above this block records.
    //
    // Without the clear, this user's next deliberate sign-out reports a
    // session ending that happened before they had even signed in.
    let release!: () => void;
    const held = new Promise<unknown>((resolve) => {
      release = () => resolve(null);
    });
    stubFetch({
      '/api/auth/session': [{ status: 200, body: UNCLAIMED }, unauthorized],
      '/api/auth/password': [{ status: 200, body: STAFF, after: held }],
      '/api/auth/logout': [{ status: 204 }],
    });
    render(<App />);
    await screen.findByLabelText(/new password/i);

    setNewPassword('a-long-enough-password');

    // The change is held. The tab comes back, the revalidation is refused, and
    // the notice goes up.
    visible('visible');
    fireEvent(document, new Event('visibilitychange'));
    await screen.findByText(NOTICE);

    // Now the held change answers, and the app is signed in again — carrying
    // the flag.
    release();
    await screen.findByTestId('app-bar');

    fireEvent.click(screen.getByRole('button', { name: /sign out/i }));

    await screen.findByLabelText(/^password$/i);
    expect(screen.queryByText(NOTICE)).toBeNull();
  });
});

describe('returning to a backgrounded tab', () => {
  it('revalidates once and keeps the shell when the session is still good', async () => {
    const { calls } = stubFetch({ '/api/auth/session': [{ status: 200, body: STAFF }] });
    render(<App />);
    await screen.findByTestId('app-bar');
    expect(sessionCalls(calls)).toHaveLength(1);

    visible('visible');
    fireEvent(document, new Event('visibilitychange'));

    await waitFor(() => expect(sessionCalls(calls)).toHaveLength(2));
    expect(screen.getByTestId('app-bar')).toBeTruthy();
  });

  it('refreshes the cached user from that one call', async () => {
    // The revalidation is also the request AD-3 makes a role change land on:
    // the server re-reads `role` and `active` every time, and this is the call
    // that brings the new one back.
    const { calls } = stubFetch({
      '/api/auth/session': [
        { status: 200, body: STAFF },
        { status: 200, body: { ...STAFF, name: 'Kasun P. Perera' } },
      ],
    });
    render(<App />);
    await screen.findByText(/Kasun Perera/);

    fireEvent(document, new Event('visibilitychange'));

    expect(await screen.findByText(/Kasun P\. Perera/)).toBeTruthy();
    expect(sessionCalls(calls)).toHaveLength(2);
  });

  it('drops to the login screen when the session died while the tab was hidden', async () => {
    stubFetch({
      '/api/auth/session': [{ status: 200, body: STAFF }, unauthorized],
    });
    render(<App />);
    await screen.findByTestId('app-bar');

    fireEvent(document, new Event('visibilitychange'));

    expect(await screen.findByLabelText(/password/i)).toBeTruthy();
    expect(await screen.findByText(NOTICE)).toBeTruthy();
    expect(screen.queryByTestId('app-bar')).toBeNull();
  });

  it('makes no request at all while the tab is hidden', async () => {
    // Nothing keeps a session alive on the user's behalf. A backgrounded tab
    // is silent, which is exactly what lets the 12-hour idle window mean
    // something.
    const { calls } = stubFetch({ '/api/auth/session': [{ status: 200, body: STAFF }] });
    render(<App />);
    await screen.findByTestId('app-bar');

    visible('hidden');
    fireEvent(document, new Event('visibilitychange'));
    fireEvent(document, new Event('visibilitychange'));

    await settle();
    expect(sessionCalls(calls)).toHaveLength(1);
  });

  it('leaves the shell alone when the revalidation cannot reach the server', async () => {
    // A tab brought back on a dead connection is not a session that ended, and
    // signing the user out for it would throw away a cookie that still works.
    const failing = vi
      .fn()
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: () => Promise.resolve(STAFF),
      } as Response)
      .mockRejectedValue(new Error('offline'));
    vi.stubGlobal('fetch', failing);
    render(<App />);
    await screen.findByTestId('app-bar');

    fireEvent(document, new Event('visibilitychange'));

    await waitFor(() => expect(failing).toHaveBeenCalledTimes(2));
    expect(screen.getByTestId('app-bar')).toBeTruthy();
    expect(screen.queryByText(NOTICE)).toBeNull();
  });

  it('makes no revalidation request while signed out', async () => {
    // The login screen is not a session. A `visibilitychange` there would be a
    // request nobody asked for, answered 401, telling the app something it
    // already knows.
    const { calls } = stubFetch({ '/api/auth/session': [unauthorized] });
    render(<App />);
    await screen.findByLabelText(/password/i);

    fireEvent(document, new Event('visibilitychange'));

    await settle();
    expect(sessionCalls(calls)).toHaveLength(1);
  });

  it('stops listening once the provider is gone', async () => {
    const { calls } = stubFetch({ '/api/auth/session': [{ status: 200, body: STAFF }] });
    render(<App />);
    await screen.findByTestId('app-bar');
    cleanup();

    fireEvent(document, new Event('visibilitychange'));

    await settle();
    expect(sessionCalls(calls)).toHaveLength(1);
  });
});

describe('a session that dies on the forced-change screen', () => {
  // The user least able to recover: the change screen carries no sign-out
  // control and no dismissal by design, so a 401 that left them on it would
  // make clearing cookies the only way out of the app.
  //
  // These two cases are a pair, and the pair is the point. Adding
  // `setSessionEnded(false)` to `changePassword`'s catch — the natural edit for
  // someone making sure the 409 below shows no notice — would silently take the
  // notice off the genuine expiry above, and nothing else in the suite would
  // see it: `auth-gating.test.tsx` only asserts which screen renders, and
  // `forced-password-change.test.tsx` hard-codes `sessionEnded: false`.

  it('lands on the login screen carrying the notice when the session expired', async () => {
    stubFetch({
      '/api/auth/session': [{ status: 200, body: UNCLAIMED }],
      '/api/auth/password': [unauthorized],
    });
    render(<App />);
    await screen.findByLabelText(/new password/i);

    setNewPassword('a-long-enough-password');

    expect(await screen.findByLabelText(/^password$/i)).toBeTruthy();
    expect(await screen.findByText(NOTICE)).toBeTruthy();
  });

  it('reports the notice once, not twice', async () => {
    // Two paths set `'signed-out'` for this one failure — the central observer
    // and `changePassword`'s own `unauthorized` branch — and the user must see
    // one sentence, not two stacked live regions.
    stubFetch({
      '/api/auth/session': [{ status: 200, body: UNCLAIMED }],
      '/api/auth/password': [unauthorized],
    });
    render(<App />);
    await screen.findByLabelText(/new password/i);

    setNewPassword('a-long-enough-password');
    await screen.findByLabelText(/^password$/i);

    expect(screen.getAllByText(NOTICE)).toHaveLength(1);
  });

  it('shows no notice when the account was simply already claimed', async () => {
    // `password_change_not_required` is a stale cached user, not a session
    // ending: the session is still perfectly good and the account now has a
    // real password. Login is where one is used, and nothing was lost.
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
    expect(screen.queryByText(NOTICE)).toBeNull();
  });
});

describe('the observer cannot change what the caller sees', () => {
  // It runs on the way to a rejection the caller is written to branch on. If it
  // were invoked unguarded and threw, *that* error would propagate in place of
  // the `ApiRequestError`, and `LoginScreen`'s `unauthorized` branch — the one
  // that words a refused credential and clears the password field — would
  // simply never run. The user would be told "Sign-in failed. Try again."
  // whatever actually happened.
  //
  // Driven against `apiRequest` directly, because no rendered flow can see it:
  // the observer sets its state *before* throwing, so every screen still swaps
  // and every assertion about which screen is showing stays green.

  it('still rejects with the API error when the observer throws', async () => {
    stubFetch({ '/api/whatever': [unauthorized] });
    const stop = onUnauthorized(() => {
      throw new Error('the observer blew up');
    });

    try {
      const failure = await apiRequest('/whatever').then(
        () => null,
        (error: unknown) => error,
      );

      expect(failure).toBeInstanceOf(ApiRequestError);
      expect((failure as ApiRequestError).code).toBe(UNAUTHORIZED);
      expect((failure as ApiRequestError).status).toBe(401);
    } finally {
      stop();
    }
  });

  it('still rejects with the API error when a non-401 rides past a throwing observer', async () => {
    // The observer is not consulted at all here; the guard must not have
    // changed the ordinary failure path on its way in.
    stubFetch({
      '/api/whatever': [
        { status: 500, body: { error: { code: 'internal_error', message: 'Something broke.' } } },
      ],
    });
    const stop = onUnauthorized(() => {
      throw new Error('the observer blew up');
    });

    try {
      const failure = await apiRequest('/whatever').then(
        () => null,
        (error: unknown) => error,
      );

      expect(failure).toBeInstanceOf(ApiRequestError);
      expect((failure as ApiRequestError).code).toBe('internal_error');
    } finally {
      stop();
    }
  });
});

describe('nothing re-checks the session on a schedule', () => {
  it('issues no request when time passes and the user does nothing', async () => {
    // The guard against a poll being added. A timer re-checking the session is
    // itself an authenticated request, so it would slide the idle window
    // forward on an unattended tab forever — a session that never dies because
    // the app kept it alive.
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const { calls } = stubFetch({ '/api/auth/session': [{ status: 200, body: STAFF }] });
    render(<App />);
    await screen.findByTestId('app-bar');
    expect(sessionCalls(calls)).toHaveLength(1);

    await vi.advanceTimersByTimeAsync(60 * 60 * 1000);

    expect(sessionCalls(calls)).toHaveLength(1);
  });
});
