import { useEffect, useRef, useState } from 'react';
import type { JSX } from 'react';

import styles from './App.module.css';
import { ApiRequestError } from './api/client';
import { useSession, SessionProvider } from './auth/SessionProvider';
import { AppShell, MAIN_REGION_ID } from './components/AppShell';
import { LoginScreen } from './screens/LoginScreen';
import type { SessionStatus } from './auth/SessionProvider';

/** Shown when signing out fails as something other than an `ApiRequestError`. */
const SIGN_OUT_FAILED = 'Could not sign out. Try again.';

/**
 * The application root: the session gate, and nothing else yet.
 *
 * The split is a conditional render, not a router. Nothing in the architecture
 * spine, DESIGN.md or EXPERIENCE.md names a routing library, and the only
 * navigation this story needs is "signed out or signed in". Story 1.4's forced
 * password change is where navigation trapping actually forces the question,
 * so that is where the dependency decision belongs.
 */
function Gate(): JSX.Element {
  const { status, user, signOut } = useSession();
  const [signOutError, setSignOutError] = useState<string | null>(null);
  const previous = useRef<SessionStatus>('loading');

  useEffect(() => {
    // Swapping one screen for the other unmounts whatever had focus — the
    // submit button on the way in, the sign-out button on the way out — and
    // focus falls to `<body>`, which leaves a keyboard or screen-reader user
    // at the top of a page they did not ask to be at the top of. Both screens
    // expose the same focusable main region for this.
    //
    // Deliberately not on the first resolution of `loading`: the page has just
    // loaded, and moving focus on arrival is its own accessibility failure.
    const from = previous.current;
    previous.current = status;
    if (from !== 'loading' && from !== status) {
      document.getElementById(MAIN_REGION_ID)?.focus();
    }
  }, [status]);

  if (status === 'loading') {
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

  if (status === 'signed-out' || user === null) {
    return <LoginScreen />;
  }

  function handleSignOut(): void {
    setSignOutError(null);
    // The session is the server's row, not this component's state: if the
    // revocation did not land, the cookie is still live and saying "signed
    // out" would be false. `SessionProvider` clears nothing until the row is
    // gone, so all this has to do is show why the screen did not change.
    signOut().catch((failure: unknown) => {
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
