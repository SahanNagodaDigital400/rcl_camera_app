import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import type { JSX, ReactNode } from 'react';

import { isUser } from '@rocell/schema/user';
import type { User } from '@rocell/schema/user';

import {
  ApiRequestError,
  MALFORMED_RESPONSE,
  PASSWORD_CHANGE_NOT_REQUIRED,
  UNAUTHORIZED,
  apiRequest,
  onUnauthorized,
} from '../api/client';

/**
 * Who is signed in, for the whole app.
 *
 * There is nothing to store here. The session token is in an HTTP-only cookie
 * the browser attaches by itself (AD-3, AGENTS.md Policy) — this context holds
 * only the `User` the API reports, and the API re-reads `role` and `active`
 * from Postgres on every call, so what is held here is a render cache and
 * never an authorization decision. Nothing in this app may gate a privileged
 * action on it.
 *
 * `status` is three-valued on purpose. Collapsing `loading` into `signed-out`
 * flashes the login screen on every reload for the entire round trip of the
 * bootstrap request, which reads as "you have been signed out" to anyone
 * looking.
 */
export type SessionStatus = 'loading' | 'signed-out' | 'signed-in';

export interface SessionContextValue {
  status: SessionStatus;
  user: User | null;
  signIn: (email: string, password: string) => Promise<void>;
  /**
   * Set a real password for a user still holding an admin-issued temporary one.
   *
   * On success the API returns the same `User` with `must_change_password`
   * cleared, so storing it is what lets the gate in `App` fall through to the
   * shell — there is no separate "done" flag to keep in step with the server.
   */
  changePassword: (newPassword: string) => Promise<void>;
  /**
   * Replace the password this user already chose, proving the current one
   * (FR-5).
   *
   * Beside `changePassword` and deliberately needing none of its two rescue
   * branches. That one runs on a screen with no sign-out control and no way out,
   * so a failure that makes the cached user wrong has to be resolved there or
   * the only escape is clearing cookies. This screen is reachable *and*
   * escapable — it sits inside the shell with a Back control — so every failure
   * is the screen's to show, and a `401` is already handled by the
   * `onUnauthorized` observer registered above.
   *
   * On success the API returns the same `User` with `updated_at` moved, and
   * storing it keeps the cached copy from going stale.
   */
  changeOwnPassword: (currentPassword: string, newPassword: string) => Promise<void>;
  signOut: () => Promise<void>;
  /**
   * Store a fresher copy of the caller's own row, which the API has just
   * returned.
   *
   * The one admin mutation that reaches this context, and only because its
   * result *is* the caller: an Administrator editing their own row at
   * `PATCH /admin/users/{id}` gets back the same `User` the visibility
   * revalidation above stores with `setUser(asUser(body))`. Without it a
   * self-rename leaves a stale name in the app bar, and a self-demotion leaves
   * the Users door on screen until the tab is backgrounded and brought back.
   *
   * **It replaces the cached user only when the ids match.** Every other admin
   * call deliberately bypasses this provider, and that stays true — this is not
   * a route into it for admin mutations. The id guard is what keeps it from
   * becoming a way to write somebody else's row into the caller's session: an
   * Administrator who edits a colleague hands that row here and nothing happens.
   *
   * It is a render cache and never an authorization decision (AGENTS.md
   * Policy). The server re-reads `role` and `active` from Postgres on every
   * request (AD-3) whatever this holds.
   */
  adoptUser: (user: User) => void;
  /**
   * A session that existed has ended — expired, revoked, or its owner
   * deactivated.
   *
   * Set only on the way out of `'signed-in'`, which is what keeps it off a
   * rejected sign-in: the login screen's own `unauthorized` is a credential
   * that was refused, not a session that ended, and a notice there would tell
   * a user who mistyped their password that they had been signed out of
   * something.
   *
   * Which of the three it was is deliberately not recorded and deliberately
   * not shown. The three are indistinguishable by design — the API answers all
   * of them with the same 401 and the same message — and a front end that
   * guessed between them would leak what the server refused to say.
   */
  sessionEnded: boolean;
}

const SessionContext = createContext<SessionContextValue | null>(null);

/**
 * Narrow a response body to the shared `User`, or fail loudly.
 *
 * A body that does not satisfy the contract is a failure, not something to
 * render partially: `isUser` rejects a missing key, a malformed UUID, a
 * non-UTC timestamp — and any extra key, which is how a `password_hash` would
 * announce itself.
 */
function asUser(body: unknown): User {
  if (!isUser(body)) {
    throw new ApiRequestError(
      MALFORMED_RESPONSE,
      'The server returned an unexpected response.',
      200,
    );
  }
  return body;
}

export function SessionProvider({ children }: { children: ReactNode }): JSX.Element {
  const [status, setStatus] = useState<SessionStatus>('loading');
  const [user, setUser] = useState<User | null>(null);
  const [sessionEnded, setSessionEnded] = useState(false);

  useEffect(() => {
    // Guards against setting state after the effect has been torn down —
    // StrictMode runs it twice in development, and a slow first response
    // landing after the second run would otherwise overwrite it.
    let live = true;

    apiRequest('/auth/session')
      .then((body) => {
        if (live) {
          setUser(asUser(body));
          setStatus('signed-in');
        }
      })
      .catch(() => {
        // Not signed in, or the API is unreachable. Both mean "show the login
        // screen": a failed bootstrap must never leave a blank page, and the
        // sign-in attempt that follows reports its own failure properly.
        if (live) {
          setUser(null);
          setStatus('signed-out');
        }
      });

    return () => {
      live = false;
    };
  }, []);

  useEffect(() => {
    // Every request in the app goes through `apiRequest`, so this is the one
    // place that always learns the server has stopped honouring the cookie
    // (DW-37). Without it the shell keeps rendering over a dead session until
    // the page is reloaded, and EXPERIENCE.md line 90's "session expired
    // mid-flow -> redirect to Login" has no implementation.
    //
    // Registered only while signed in, and keyed on `status` rather than read
    // through a ref: a ref written in an effect lags the state it mirrors by a
    // commit, so a 401 arriving in that window would be tested against the
    // *previous* status and silently dropped. Re-registering costs one
    // assignment per sign-in.
    if (status !== 'signed-in') return;

    return onUnauthorized(() => {
      // Registered only while signed in, which is what keeps the notice off
      // the two 401s that are not a session ending: the login screen's own
      // rejection and the bootstrap finding no cookie. Nothing is observing at
      // either of those moments.
      //
      // A session dying mid-forced-change *is* a session ending, and it does
      // raise the notice — once. This runs before `apiRequest` throws, so by
      // the time `changePassword`'s own `unauthorized` branch sets
      // `'signed-out'` the state is already what that branch would set, and
      // setting it again is idempotent rather than a second report.
      setUser(null);
      setStatus('signed-out');
      setSessionEnded(true);
    });
  }, [status]);

  useEffect(() => {
    // The other half of DW-37: a tab backgrounded for hours comes back to a
    // shell whose session died while nobody was looking. Returning to it is
    // the moment to find out, and it costs one request at the moment a user
    // is about to act anyway.
    //
    // **Never an interval.** A poll is itself an authenticated request, so a
    // timer re-checking the session would slide `last_seen_at` forward every
    // tick and keep an unattended tab signed in forever — defeating the very
    // 12-hour idle window this exists to surface. Nothing in this app may
    // keep a session alive on its owner's behalf.
    if (status !== 'signed-in') return;

    let live = true;

    function revalidate(): void {
      if (document.visibilityState !== 'visible') return;

      apiRequest('/auth/session')
        .then((body) => {
          // Refreshes the cached `User` as well as proving the session: a role
          // change or a deactivation lands on the next request (AD-3,
          // EXPERIENCE.md line 95), and this is that request.
          if (live) setUser(asUser(body));
        })
        .catch(() => {
          // A 401 has already been dealt with by the observer above, and a tab
          // brought back on a dead connection must not be signed out for the
          // network — the state is left exactly as it was and the user's next
          // real action reports its own failure.
          //
          // This also swallows a body `asUser` rejects, which is not the
          // network but a broken contract with our own API. Deliberately the
          // same treatment: the cached user simply stays as it was, and every
          // request after this one is still authorized server-side (AD-3), so
          // there is nothing a signed-in user could be shown here that their
          // next action would not show them better.
        });
    }

    document.addEventListener('visibilitychange', revalidate);
    return () => {
      live = false;
      document.removeEventListener('visibilitychange', revalidate);
    };
  }, [status]);

  const signIn = useCallback(async (email: string, password: string): Promise<void> => {
    // Errors propagate: the login form is what knows how to show them, and
    // swallowing one here would leave a form that submits and does nothing.
    const body = await apiRequest('/auth/login', { method: 'POST', body: { email, password } });
    setUser(asUser(body));
    setStatus('signed-in');
    // The notice has served its purpose the moment a session exists again.
    // Left set, it would be on screen the next time the user signs out
    // deliberately.
    setSessionEnded(false);
  }, []);

  const changePassword = useCallback(async (newPassword: string): Promise<void> => {
    // Errors propagate, as `signIn`'s do: the screen is what knows how to show
    // a rule-naming rejection, and swallowing one here would leave a form that
    // submits and does nothing.
    //
    // Two of them are not the screen's to show, though, and they are the two
    // that would trap the user on it. The change screen carries no sign-out
    // control and no dismissal by design, so a failure that makes the cached
    // user wrong has to be resolved here or not at all — otherwise the only way
    // out of the app is clearing cookies.
    let body: unknown;
    try {
      body = await apiRequest('/auth/password', {
        method: 'POST',
        body: { new_password: newPassword },
      });
    } catch (failure) {
      if (
        failure instanceof ApiRequestError &&
        (failure.code === UNAUTHORIZED || failure.code === PASSWORD_CHANGE_NOT_REQUIRED)
      ) {
        // `unauthorized`: the session died mid-change — expired, revoked, or
        // its owner deactivated. EXPERIENCE.md's state table sends that to
        // Login, and the server has already cleared the cookie.
        //
        // `password_change_not_required`: the account was claimed by someone
        // else holding the same temporary credential, or on another tab. Either
        // way the user this context is holding is stale and its
        // `must_change_password` is a lie, so keeping it would re-render the
        // screen that just failed. Login is where a real password is used.
        setUser(null);
        setStatus('signed-out');
      }
      throw failure;
    }

    // The server's own answer, narrowed by the same contract check as every
    // other user body. Setting it is the whole transition: the flag it carries
    // is what the gate reads.
    setUser(asUser(body));
    setStatus('signed-in');
  }, []);

  const changeOwnPassword = useCallback(
    async (currentPassword: string, newPassword: string): Promise<void> => {
      // Errors propagate untouched — no `try`, and that is the difference from
      // `changePassword` above rather than an omission. Nothing here can trap
      // the user: the screen has a Back control, the shell around it still
      // renders, and the one failure that would make the cached user wrong is a
      // `401`, which `onUnauthorized` has already turned into a sign-out by the
      // time this rejection arrives.
      const body = await apiRequest('/auth/password/change', {
        method: 'POST',
        body: { current_password: currentPassword, new_password: newPassword },
      });
      // The server's own answer, narrowed by the same contract check as every
      // other user body. The change revoked every session of this user and
      // issued this browser a fresh cookie in the same response, so the app is
      // still signed in — `status` is deliberately left alone.
      setUser(asUser(body));
    },
    [],
  );

  const signOut = useCallback(async (): Promise<void> => {
    // The server's copy is the session. If the revocation did not land, the
    // cookie is still valid and still in the browser, so clearing local state
    // here would show the login screen to someone who is *not* signed out —
    // and one reload would put them straight back in. The failure propagates
    // to the caller, which is what shows it; nothing is cleared until the row
    // is actually gone.
    await apiRequest('/auth/logout', { method: 'POST' });
    setUser(null);
    setStatus('signed-out');
    // Signing out is not a session *ending* on the user — they ended it. The
    // login screen they land on says nothing about it.
    //
    // Only on the way through, though. If the logout is itself refused with a
    // 401 the session had already ended before the click, `apiRequest` throws,
    // and none of these three lines run — the observer has raised the notice
    // and it stands, because in that case something really did end without
    // being asked to. The first test in `session-expiry.test.tsx` is that
    // path.
    //
    // Not redundant with `signIn`'s identical clear: a revalidation 401 that
    // lands during a forced change leaves the flag set on an app that
    // `changePassword` then puts back to signed-in without a sign-in ever
    // happening. This is what keeps that notice off the login screen the user
    // reaches next.
    setSessionEnded(false);
  }, []);

  const adoptUser = useCallback((updated: User): void => {
    // Guarded on the id inside the updater rather than against the `user` in
    // scope, so this callback does not have to be rebuilt on every session
    // change — and so the comparison is made against the state as it is at the
    // moment of the write rather than as it was when the caller rendered.
    setUser((cached) => (cached !== null && cached.id === updated.id ? updated : cached));
  }, []);

  const value = useMemo<SessionContextValue>(
    () => ({
      status,
      user,
      signIn,
      changePassword,
      changeOwnPassword,
      signOut,
      adoptUser,
      sessionEnded,
    }),
    [status, user, signIn, changePassword, changeOwnPassword, signOut, adoptUser, sessionEnded],
  );

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

/** The session, from anywhere inside `SessionProvider`. */
export function useSession(): SessionContextValue {
  const value = useContext(SessionContext);
  if (value === null) {
    throw new Error('useSession must be used inside a SessionProvider.');
  }
  return value;
}
