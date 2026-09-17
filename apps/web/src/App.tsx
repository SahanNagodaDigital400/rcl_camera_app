import { useEffect, useRef, useState } from 'react';
import type { JSX } from 'react';

import styles from './App.module.css';
import { ApiRequestError, HTTP_UNAUTHORIZED } from './api/client';
import { useSession, SessionProvider } from './auth/SessionProvider';
import type { SessionStatus } from './auth/SessionProvider';
import { AppShell, MAIN_REGION_ID } from './components/AppShell';
import { ForcedPasswordChangeScreen } from './screens/ForcedPasswordChangeScreen';
import { LoginScreen } from './screens/LoginScreen';
import type { User } from '@rocell/schema/user';

/** Shown when signing out fails as something other than an `ApiRequestError`. */
const SIGN_OUT_FAILED = 'Could not sign out. Try again.';

/**
 * Which of the four screens the session state selects.
 *
 * Named separately from `SessionStatus` because the two are not the same shape:
 * `'signed-in'` covers both the forced-change screen and the shell, and the
 * move between them is a screen swap that the status cannot see. Focus
 * management keys off this, not off the status.
 */
type Screen = 'loading' | 'login' | 'password-change' | 'shell';

function currentScreen(status: SessionStatus, user: User | null): Screen {
  if (status === 'loading') return 'loading';
  if (status === 'signed-out' || user === null) return 'login';
  return user.must_change_password ? 'password-change' : 'shell';
}

/**
 * The application root: the session gate, and nothing else yet.
 *
 * The split is a conditional render, not a router. Nothing in the architecture
 * spine, DESIGN.md or EXPERIENCE.md names a routing library, and the navigation
 * this needs is "signed out", "signed in but unclaimed", or "signed in".
 *
 * Story 1.3 left a note here saying the forced password change would be what
 * forced the routing-library question. It did not, and the reason belongs on
 * the record: a trap only needs intercepting if there is somewhere to navigate
 * *to*. With no router, rendering the change screen instead of the shell means
 * the shell is not in the document at all — nothing to reach, nothing to
 * intercept, no history entry to guard. A router would have added the very
 * surface the trap then has to defend.
 *
 * The trap is a convenience either way. The control is server-side: every route
 * that serves real data declares `require_claimed_user` and answers
 * `403 password_change_required` until the change lands (AGENTS.md Policy —
 * authorization is never gated by what the UI hides).
 */
function Gate(): JSX.Element {
  const { status, user, signOut } = useSession();
  const [signOutError, setSignOutError] = useState<string | null>(null);
  const screen = currentScreen(status, user);
  const previous = useRef<Screen>('loading');

  useEffect(() => {
    // Swapping one screen for the other unmounts whatever had focus — the
    // submit button on the way in, the sign-out button on the way out — and
    // focus falls to `<body>`, which leaves a keyboard or screen-reader user
    // at the top of a page they did not ask to be at the top of. Every screen
    // exposes the same focusable main region for this.
    //
    // Keyed on which screen is rendered, not on `status`. The forced change
    // moves from the change screen to the shell without `status` ever leaving
    // `'signed-in'` — only `must_change_password` changes — so an effect
    // watching the status alone silently skips that one swap, and the user who
    // just pressed a button that no longer exists is left on `<body>`.
    //
    // Deliberately not on the first resolution of `loading`: the page has just
    // loaded, and moving focus on arrival is its own accessibility failure.
    const from = previous.current;
    previous.current = screen;
    if (from !== 'loading' && from !== screen) {
      document.getElementById(MAIN_REGION_ID)?.focus();
    }
  }, [screen]);

  if (screen === 'loading') {
    // The bootstrap request is in flight. Deliberately quiet — a spinner here
    // would flash on every reload for a request that usually beats the paint,
    // and showing the login screen instead reads as "you have been signed out"
    // to anyone who has not been.
    //
    // `role="status"` so the wait is announced: `aria-busy` alone marks a
    // region as changing and says nothing about what is happening. It goes on
    // the paragraph, not on the `<main>`: an explicit role replaces an
    // element's implicit one, so a `role="status"` main is not a main landmark,
    // and the page would spend its whole bootstrap with nothing for a screen
    // reader to jump to.
    return (
      <main className={styles.pending} aria-busy="true">
        <p className={styles.lede} role="status">
          Checking your session…
        </p>
      </main>
    );
  }

  if (screen === 'login' || user === null) {
    // `user === null` is unreachable at runtime — `currentScreen` already maps
    // it to `'login'`. It is here so TypeScript narrows `user` to non-null for
    // the two branches below, which read `user.must_change_password` and
    // `user.name`. Removing it as redundant breaks the build, so it says why.
    return <LoginScreen />;
  }

  if (screen === 'password-change') {
    // Before the shell, and instead of it. The account is signed in and holding
    // an admin-issued temporary credential: AGENTS.md line 18 gives it no
    // further access until a real password is set, and the API enforces that
    // independently. `changePassword` clears the flag by storing the `User` the
    // API returns, so this branch stops being taken on the very next render —
    // with no success screen in between (EXPERIENCE.md line 88).
    return <ForcedPasswordChangeScreen />;
  }

  function handleSignOut(): void {
    setSignOutError(null);
    // The session is the server's row, not this component's state: if the
    // revocation did not land, the cookie is still live and saying "signed
    // out" would be false. `SessionProvider` clears nothing until the row is
    // gone, so all this has to do is show why the screen did not change.
    signOut().catch((failure: unknown) => {
      if (failure instanceof ApiRequestError && failure.status === HTTP_UNAUTHORIZED) {
        // The session had already ended before the click. `apiRequest` notified
        // the observer before it threw, so the app is on the login screen
        // carrying the session-ended notice by the time this runs — and this
        // message would be written onto a shell that is no longer rendered.
        //
        // It would not stay unrendered, either: `Gate` is one component with
        // conditional returns rather than a tree that unmounts, so the state
        // survives the swap and the next sign-in brings the shell back with
        // "Not signed in." on it, over a user who is. The observer owns this
        // case; every other failure is still this site's to word.
        return;
      }
      setSignOutError(failure instanceof ApiRequestError ? failure.message : SIGN_OUT_FAILED);
    });
  }

  return (
    <AppShell onSignOut={handleSignOut}>
      <h1 className={styles.title}>Rocell Tile Scanner</h1>
      {/* The session made visible: if this name is right, the cookie, the
          session row and the per-request lookup all worked. */}
      <p className={styles.greeting}>Signed in as {user.name}.</p>
      {signOutError !== null && (
        <p className={styles.error} role="alert">
          {signOutError}
        </p>
      )}
      <p className={styles.lede}>
        Internal staff tool. Photograph a tile and get the three closest matches from the
        catalogue, each with its reference image, Size and Category.
      </p>
    </AppShell>
  );
}

export default function App(): JSX.Element {
  return (
    <SessionProvider>
      <Gate />
    </SessionProvider>
  );
}
