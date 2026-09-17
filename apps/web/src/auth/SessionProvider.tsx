import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import type { JSX, ReactNode } from 'react';

import { isUser } from '@rocell/schema/user';
import type { User } from '@rocell/schema/user';

import { ApiRequestError, MALFORMED_RESPONSE, apiRequest } from '../api/client';

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
    () => ({ status, user, signIn, signOut }),
    [status, user, signIn, signOut],
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
