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
  signOut: () => Promise<void>;
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

  const signIn = useCallback(async (email: string, password: string): Promise<void> => {
    // Errors propagate: the login form is what knows how to show them, and
    // swallowing one here would leave a form that submits and does nothing.
    const body = await apiRequest('/auth/login', { method: 'POST', body: { email, password } });
    setUser(asUser(body));
    setStatus('signed-in');
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
  }, []);

  const value = useMemo<SessionContextValue>(
    () => ({ status, user, signIn, changePassword, signOut }),
    [status, user, signIn, changePassword, signOut],
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
