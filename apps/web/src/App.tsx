import { useEffect, useRef, useState } from 'react';
import type { JSX } from 'react';

import styles from './App.module.css';
import { ApiRequestError, HTTP_UNAUTHORIZED } from './api/client';
import { useSession, SessionProvider } from './auth/SessionProvider';
import type { SessionStatus } from './auth/SessionProvider';
import { AppShell, MAIN_REGION_ID } from './components/AppShell';
import { AccountSettingsScreen } from './screens/AccountSettingsScreen';
import { CreateUserScreen } from './screens/CreateUserScreen';
import { ForcedPasswordChangeScreen } from './screens/ForcedPasswordChangeScreen';
import { LoginScreen } from './screens/LoginScreen';
import { UserListScreen } from './screens/UserListScreen';
import type { Role, User } from '@rocell/schema/user';

/** Shown when signing out fails as something other than an `ApiRequestError`. */
const SIGN_OUT_FAILED = 'Could not sign out. Try again.';

/**
 * Which surface inside the shell is showing.
 *
 * Four values because four surfaces exist. This is not a router and is not the
 * beginning of one: EXPERIENCE.md's nav is role-conditional, spans six surfaces
 * and changes shape at a breakpoint, and four of those six do not exist yet.
 * `'users'` is one of the six — EXPERIENCE.md line 33's User List, standing on
 * the home panel until there is a nav to hold it. Create user is not: line 34
 * reaches it from the list's "+ Add user", which is where its door now is.
 * When the nav arrives this becomes whatever it needs; until then it is one
 * piece of state and a swap.
 */
type Section = 'home' | 'account' | 'create-user' | 'users';

/**
 * Which of the seven screens the session state selects.
 *
 * Named separately from `SessionStatus` because the two are not the same shape:
 * `'signed-in'` covers the forced-change screen, the shell, Account Settings,
 * Users and Create user, and the moves between them are screen swaps that the
 * status cannot see. Focus management keys off this, not off the status — which is why
 * the section is folded in here rather than handled beside it: swapping the home
 * panel for another surface unmounts whatever had focus exactly as the other
 * swaps do.
 */
type Screen =
  | 'loading'
  | 'login'
  | 'password-change'
  | 'shell'
  | 'account'
  | 'create-user'
  | 'users';

/**
 * Whether `role` can reach `section` at all.
 *
 * The one statement of which surfaces a role reaches, because two places need
 * the answer and they must not disagree: `currentScreen` reads past a section
 * the role cannot reach, and `Gate`'s role reconciler clears it. A second copy
 * of the rule is how a surface added from Story 1.9 on ends up rendered by one
 * and cleared by the other.
 *
 * `null` is a signed-out caller, who reaches nothing role-conditional.
 */
function reachableBy(section: Section, role: Role | null): boolean {
  if (section === 'create-user' || section === 'users') return role === 'admin';
  return true;
}

function currentScreen(status: SessionStatus, user: User | null, section: Section): Screen {
  if (status === 'loading') return 'loading';
  if (status === 'signed-out' || user === null) return 'login';
  if (user.must_change_password) return 'password-change';
  if (section === 'account') return 'account';
  // EXPERIENCE.md line 95: a permission revoked mid-session sends the user to
  // the highest surface the new role can reach, not to a dead screen. Expressed
  // as a condition inside this pure function rather than as an effect that
  // resets the section, so an Administrator demoted while standing on this
  // screen simply renders the home panel on the very next render — there is no
  // frame in which the admin surface is painted for a Staff user, and no effect
  // to keep in step with `SessionProvider`'s revalidation.
  //
  // It is a convenience, not the control: the cached `User` is a render cache
  // and never an authorization decision (AGENTS.md Policy), and the server
  // refuses a Staff caller at `GET`/`POST /admin/users` whatever this returns.
  if (section === 'users') return reachableBy(section, user.role) ? 'users' : 'shell';
  if (section === 'create-user') return reachableBy(section, user.role) ? 'create-user' : 'shell';
  return 'shell';
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
  const [section, setSection] = useState<Section>('home');
  const [lastStatus, setLastStatus] = useState<SessionStatus>(status);
  const [lastRole, setLastRole] = useState<Role | null>(user?.role ?? null);

  if (lastStatus !== status) {
    setLastStatus(status);
    // `Gate` is one component with conditional returns rather than a tree that
    // unmounts, so nothing clears the section on the way out. `currentScreen`
    // already ignores it while there is no session — which is exactly what makes
    // a stale one invisible until somebody signs back in, and then lands the
    // next person on a shared shop-floor handset on a password form instead of
    // the home panel. Not reading it is not the same as not keeping it.
    //
    // Keyed on the status rather than done in the sign-out handler: a session
    // also ends by expiry, by revocation from another device and by
    // deactivation, and all three arrive through `onUnauthorized` without
    // anybody pressing anything on this screen.
    //
    // Adjusted during render rather than in an effect. React re-runs this
    // component immediately, before it commits anything and before any child
    // renders, so the stale section never reaches the DOM — where an effect
    // would paint it first and correct it a frame later. It is React's own
    // pattern for resetting state when the thing it belongs to changes, and it
    // is what `oxlint`'s `set-state-in-effect` rule asks for in place of the
    // effect this started as.
    if (status !== 'signed-in') setSection('home');
  }

  if (lastRole !== (user?.role ?? null)) {
    setLastRole(user?.role ?? null);
    // The role's own reconciler, beside the status's and for the same reason:
    // `currentScreen` *reads past* a section the new role cannot reach, and
    // reading past it is not the same as clearing it. What goes wrong while the
    // stale value sits in state is invisible until it isn't — if the role is
    // restored, and an Administrator demoted and promoted back within a shift is
    // a two-click operation once Story 1.10 lands, the create screen reopens by
    // itself over whatever the user was actually looking at. Nobody asked for it
    // and nothing on screen explains it.
    //
    // `showSection`'s `next === section` early return is the second reason to
    // clear rather than read past: it makes a stale section self-perpetuating
    // rather than self-correcting, so every surface added from Story 1.9 on
    // inherits the bug instead of the fix.
    //
    // EXPERIENCE.md line 95 asks for the highest surface the *new* role can
    // reach, which is a place to be sent rather than a screen to be hidden. Home
    // is that surface for both roles today.
    //
    // **Only when the new role cannot reach where they are.** A role change is
    // not by itself a reason to move somebody: a *promotion* arrives through the
    // same revalidation as a demotion, and clearing unconditionally would take a
    // Staff user standing on Account Settings — a surface both roles reach —
    // back to the home panel the moment they were made an Administrator,
    // discarding a half-typed password change for a change that granted them
    // more, not less. `reachableBy` is the one statement of what a role reaches,
    // shared with `currentScreen` so the two cannot disagree.
    //
    // Adjusted during render rather than in an effect, exactly as above: React
    // re-runs this component before it commits anything, so the stale section
    // never reaches the DOM — and `oxlint`'s `react/set-state-in-effect` forbids
    // the effect this would otherwise be.
    if (!reachableBy(section, user?.role ?? null)) setSection('home');
  }

  const screen = currentScreen(status, user, section);
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

  function showSection(next: Section): void {
    // The app bar keeps its Account control on the account screen — a bar whose
    // controls come and go as you move between surfaces is worse than one that
    // repeats itself — so this is reachable with `next` already showing. That
    // press is not a swap, and it must not behave like one: clearing the alert
    // below would make a control that visibly does nothing the only way to
    // dismiss a sign-out failure.
    if (next === section) return;
    // The sign-out failure belongs to the surface it was raised on: it describes
    // a click made *there*, and carrying it across a swap would put an alert
    // about a button pressed minutes ago on a panel the user has just arrived
    // at. Cleared in both directions, which is why both swaps go through here.
    setSignOutError(null);
    setSection(next);
  }

  // One node, rendered on whichever surface the click was made on. Written once
  // rather than twice: the account branch below forwards `handleSignOut` to the
  // same app bar, so a failure raised there has to be visible there — without
  // this it was silent, and pressing Back then showed it on the home panel,
  // describing a click made on a different screen.
  const signOutFailure =
    signOutError === null ? null : (
      <p className={styles.error} role="alert">
        {signOutError}
      </p>
    );

  if (screen === 'users') {
    // Inside the shell, in place of the home panel, exactly as the two screens
    // below are: the app bar stays, so Sign out stays, and the screen supplies
    // its own way back. It renders no `<main>` of its own — `AppShell` provides
    // the one the focus effect above moves focus to.
    return (
      <AppShell onSignOut={handleSignOut} onOpenAccount={() => showSection('account')}>
        {signOutFailure}
        <UserListScreen
          onAddUser={() => showSection('create-user')}
          onBack={() => showSection('home')}
        />
      </AppShell>
    );
  }

  if (screen === 'create-user') {
    // Inside the shell, in place of the home panel, exactly as Account Settings
    // is: the app bar stays, so Sign out stays, and the screen supplies its own
    // way back. It renders no `<main>` of its own — `AppShell` provides the one
    // the focus effect above moves focus to.
    //
    // Back goes to the list, not to the home panel: the list is where "+ Add
    // user" was pressed, and it is where the new row belongs. `UserListScreen`
    // refetches on mount, so returning to it shows the user just provisioned.
    return (
      <AppShell onSignOut={handleSignOut} onOpenAccount={() => showSection('account')}>
        {signOutFailure}
        <CreateUserScreen onBack={() => showSection('users')} />
      </AppShell>
    );
  }

  if (screen === 'account') {
    // Inside the shell, in place of the home panel — not instead of it. The app
    // bar stays, so Sign out stays, and Account Settings supplies its own way
    // back. The screen renders no `<main>` of its own: `AppShell` already
    // provides the one the focus effect above moves focus to.
    return (
      <AppShell onSignOut={handleSignOut} onOpenAccount={() => showSection('account')}>
        {signOutFailure}
        <AccountSettingsScreen onBack={() => showSection('home')} />
      </AppShell>
    );
  }

  return (
    <AppShell onSignOut={handleSignOut} onOpenAccount={() => showSection('account')}>
      <h1 className={styles.title}>Rocell Tile Scanner</h1>
      {/* The session made visible: if this name is right, the cookie, the
          session row and the per-request lookup all worked. */}
      <p className={styles.greeting}>Signed in as {user.name}.</p>
      {signOutFailure}
      <p className={styles.lede}>
        Internal staff tool. Photograph a tile and get the three closest matches from the
        catalogue, each with its reference image, Size and Category.
      </p>
      {/* The door to the admin surface, role-conditional as EXPERIENCE.md line
          18 requires: a Staff user never sees an entry they cannot use. This is
          EXPERIENCE.md line 33's own nav entry — User List — standing in for a
          nav that does not exist yet; the real one spans six surfaces of which
          four still do not. Create user is reached from the list's "+ Add user",
          which is where line 34 reaches it from, so there is one admin entry
          here rather than two.

          A convenience only. The server refuses a Staff caller at
          `GET /admin/users` regardless of what this renders (AGENTS.md Policy:
          authorization is never gated by what the UI hides), and the cached
          `user` read here is a render cache and never a decision. */}
      {user.role === 'admin' && (
        <button className={styles.userList} type="button" onClick={() => showSection('users')}>
          Users
        </button>
      )}
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
