import {
  Camera,
  CaretRight,
  ClockCounterClockwise,
  ListBullets,
  Scan,
  SquaresFour,
  Users,
} from '@phosphor-icons/react';
import { useEffect, useRef, useState } from 'react';
import type { JSX } from 'react';

import styles from './App.module.css';
import { ApiRequestError, HTTP_UNAUTHORIZED, submitScan } from './api/client';
import type { NormalizedCropRect } from './api/client';
import { useSession, SessionProvider } from './auth/SessionProvider';
import type { SessionStatus } from './auth/SessionProvider';
import { AppShell, MAIN_REGION_ID } from './components/AppShell';
import type { NavKey } from './components/AppShell';
import { AccountSettingsScreen } from './screens/AccountSettingsScreen';
import { AddTileScreen } from './screens/AddTileScreen';
import { AuditLogScreen } from './screens/AuditLogScreen';
import { BulkUploadScreen } from './screens/BulkUploadScreen';
import { CatalogueScreen } from './screens/CatalogueScreen';
import { CreateUserScreen } from './screens/CreateUserScreen';
import { CropScreen } from './screens/CropScreen';
import { EditTileScreen } from './screens/EditTileScreen';
import { EditUserScreen } from './screens/EditUserScreen';
import { ForcedPasswordChangeScreen } from './screens/ForcedPasswordChangeScreen';
import { HistoryScreen } from './screens/HistoryScreen';
import { LoginScreen } from './screens/LoginScreen';
import { ResultsScreen } from './screens/ResultsScreen';
import { ScanScreen } from './screens/ScanScreen';
import { UserListScreen } from './screens/UserListScreen';
import type { ScanCandidate } from '@rocell/schema/scan';
import type { Tile } from '@rocell/schema/tile';
import type { Role, User } from '@rocell/schema/user';

/** Shown when signing out fails as something other than an `ApiRequestError`. */
const SIGN_OUT_FAILED = 'Could not sign out. Try again.';

/**
 * The whole downscaled frame, as the crop rectangle a capture is submitted
 * with. Cropping is optional: a scan goes straight from the shutter to
 * matching, and `CropScreen` is reached only when the staff member asks for
 * it (from Results, or after a quality refusal). `shared_vision.crop_to_rect`
 * accepts this rectangle as it accepts any other — the origin is in range and
 * `x + width` does not exceed the image — so the server path is one path.
 */
const FULL_FRAME: NormalizedCropRect = { x: 0, y: 0, width: 1, height: 1 };

/** Where the crop editor was opened from, and therefore where its Back returns. */
type CropOrigin = 'scan' | 'results';

/**
 * Which surface inside the shell is showing.
 *
 * Fourteen values because fourteen surfaces exist. This is not a router and is
 * not the beginning of one: EXPERIENCE.md's nav is role-conditional, spans six
 * top-level surfaces and changes shape at a breakpoint, and several of those
 * six do not exist yet. Five sections have a door of their own on the home
 * panel: `'scan'` is Story 3.1's own entry point, reachable by every
 * authenticated role and the panel's one accent control; `'history'` is Story
 * 3.5's own door, standing beside `'scan'` and reachable by the same every
 * role — a caller's own scan history is theirs to read whatever their role;
 * `'users'` is EXPERIENCE.md line 33's User List, `'audit'` is line 38's
 * Audit Log, and `'catalogue'` is line 35's Catalogue — all five standing on
 * the home panel until there is a nav to hold them. Create user is not a
 * door: line 34 reaches it from the list's "+ Add user", and `'edit-user'`
 * from a row's own Edit control on the same line.
 *
 * **`'crop'` and `'results'` are reached only from Scan and from Crop**, the
 * way `'edit-tile'` is reached only from a Catalogue row: `showCrop` sets the
 * captured image and the section together, and Back returns to Scan with the
 * image discarded. A confirmed crop (Story 3.2) now matches against the
 * catalogue and lands on Results (Story 3.4) — `showResults`' own version of
 * the same pattern — which carries no further surfaces of its own and whose
 * own Back also returns to Scan.
 *
 * **The three catalogue surfaces are reached from the Catalogue, not from the
 * home panel** — which is what line 36 and line 37 always said, and what
 * Stories 2.1, 2.2 and 2.4 stood their doors on the panel *in lieu of* until
 * this surface existed. `'add-tile'` is line 36's "+ Add Tile", the Catalogue's
 * one accent control; `'edit-tile'` is line 36's other half, opened from a row
 * with the whole `Tile` that row already holds; `'bulk-upload'` is line 37's,
 * an outlined control beside "+ Add Tile". Back from any of the three returns
 * to the Catalogue, because that is where each was pressed.
 */
type Section =
  | 'home'
  | 'account'
  | 'scan'
  | 'crop'
  | 'results'
  | 'history'
  | 'create-user'
  | 'users'
  | 'edit-user'
  | 'audit'
  | 'catalogue'
  | 'add-tile'
  | 'edit-tile'
  | 'bulk-upload';

/**
 * Which of the seventeen screens the session state selects.
 *
 * Named separately from `SessionStatus` because the two are not the same shape:
 * `'signed-in'` covers the forced-change screen, the shell, Account Settings,
 * Scan, Crop, Results, History, Users, Create user, Edit user, the Audit log,
 * the Catalogue, Add tile, Edit tile and Bulk upload, and the moves between
 * them are screen swaps that the status cannot see. Focus management keys off
 * this, not off the status — which is why the section is folded in here
 * rather than handled beside it: swapping the home panel for another surface
 * unmounts whatever had focus exactly as the other swaps do.
 */
type Screen =
  | 'loading'
  | 'login'
  | 'password-change'
  | 'shell'
  | 'account'
  | 'scan'
  | 'crop'
  | 'results'
  | 'history'
  | 'create-user'
  | 'users'
  | 'edit-user'
  | 'audit'
  | 'catalogue'
  | 'add-tile'
  | 'edit-tile'
  | 'bulk-upload';

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
  if (
    section === 'create-user' ||
    section === 'users' ||
    section === 'edit-user' ||
    section === 'audit' ||
    section === 'catalogue' ||
    section === 'add-tile' ||
    section === 'edit-tile' ||
    section === 'bulk-upload'
  ) {
    return role === 'admin';
  }
  return true;
}

function currentScreen(
  status: SessionStatus,
  user: User | null,
  section: Section,
  editing: User | null,
  editingTile: Tile | null,
  capturedImage: Blob | null,
  candidates: ScanCandidate[] | null,
): Screen {
  if (status === 'loading') return 'loading';
  if (status === 'signed-out' || user === null) return 'login';
  if (user.must_change_password) return 'password-change';
  if (section === 'account') return 'account';
  if (section === 'scan') return 'scan';
  // Reachable by every role — `reachableBy`'s default covers it, `'scan'`'s
  // own precedent — so there is no captured-state precondition and no
  // admin-gated fallback to `'shell'` the way `'audit'`/`'catalogue'` need
  // below.
  if (section === 'history') return 'history';
  if (section === 'crop') {
    // `showCrop` sets the image and the section together in one render, so
    // this branch with nothing captured is reached only by Back discarding it
    // and a stale section somehow surviving — `showSection` already prevents
    // that by clearing `capturedImage` on every move away from Crop. Falling
    // back to Scan rather than defending inside `CropScreen` is the same
    // choice `'edit-tile'` makes below: a screen with nothing to show answers
    // with the surface that produces one.
    return capturedImage === null ? 'scan' : 'crop';
  }
  if (section === 'results') {
    // `showResults`' own twin of `showCrop`'s reasoning above: candidates and
    // section are set together in one render, so nothing captured here means
    // a stale section outlived the answer it belonged to. `candidates` is
    // `null` only before a first result ever landed — an *empty* array (no
    // confident match) is a real Results state and renders as one, never
    // falls back to Scan.
    return candidates === null ? 'scan' : 'results';
  }
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
  // refuses a Staff caller at every route under `/admin/` whatever this
  // returns — the three collection reads these sections open (the user list,
  // the audit log and the catalogue), the five account writes reached from
  // them (provision, edit, delete, deactivate, activate) and the five
  // catalogue routes (search, add, edit, remove, bulk).
  if (section === 'users') return reachableBy(section, user.role) ? 'users' : 'shell';
  if (section === 'audit') return reachableBy(section, user.role) ? 'audit' : 'shell';
  if (section === 'catalogue') return reachableBy(section, user.role) ? 'catalogue' : 'shell';
  if (section === 'add-tile') return reachableBy(section, user.role) ? 'add-tile' : 'shell';
  if (section === 'edit-tile') {
    // The tile being edited is read here for the reason `'edit-user'` below
    // reads its row: a section that says `'edit-tile'` with nothing being
    // edited answers the **Catalogue** instead, which is where the
    // Administrator pressed Edit and where they can press it again.
    //
    // `null` is not the dead end it is for Edit user, though, and that is why
    // this falls back rather than defending inside the screen: Edit tile keeps
    // its Code lookup stage for exactly this case. Falling back to the
    // Catalogue is still the better answer — a list with the tile on it beats a
    // box to retype its Code into — and it is the one path by which this
    // section can hold no tile at all, since `showEditTile` sets the tile
    // first.
    if (!reachableBy(section, user.role)) return 'shell';
    return editingTile === null ? 'catalogue' : 'edit-tile';
  }
  if (section === 'bulk-upload') return reachableBy(section, user.role) ? 'bulk-upload' : 'shell';
  if (section === 'create-user') return reachableBy(section, user.role) ? 'create-user' : 'shell';
  if (section === 'edit-user') {
    // The row being edited is part of what makes this section renderable, so it
    // is read here rather than defended inside the screen. A section that says
    // `'edit-user'` with nothing being edited answers the list instead of an
    // empty editor — which is where the Administrator pressed Edit, and where
    // they can press it again.
    if (!reachableBy(section, user.role)) return 'shell';
    return editing === null ? 'users' : 'edit-user';
  }
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
  const { status, user, signOut, adoptUser } = useSession();
  const [signOutError, setSignOutError] = useState<string | null>(null);
  // Scan, not the home panel: EXPERIENCE.md's Information Architecture makes
  // Scan the default landing surface, and the nav reaches everything else.
  const [section, setSection] = useState<Section>('scan');
  /**
   * The row the edit screen is editing, or `null`.
   *
   * Held beside the section rather than inside it because the screen needs the
   * whole `User` — the list already has it, and a second `GET /admin/users/{id}`
   * to fetch what is in hand would be a route the product does not serve. It is
   * cleared by `showSection` on every move, so it can never be a stale row an
   * `'edit-user'` section renders later.
   */
  const [editing, setEditing] = useState<User | null>(null);
  /**
   * The Catalogue row the edit screen is editing, or `null`.
   *
   * `editing`'s twin, one surface over, and held for the same reason: the
   * screen needs the whole `Tile` — the Catalogue's answer already carries it,
   * images and all — and a second `GET /admin/tiles/{id}` to fetch what is in
   * hand would be a route the product does not serve. Cleared by `showSection`
   * on every move, so it can never be a stale tile an `'edit-tile'` section
   * renders later.
   */
  const [editingTile, setEditingTile] = useState<Tile | null>(null);
  /**
   * The downscaled Blob `ScanScreen` handed off, or `null`.
   *
   * `editingTile`'s twin, one surface over, and held for the same reason:
   * `CropScreen` needs the whole image and there is no route to fetch it back
   * — a captured frame that was not stored anywhere is gone the moment
   * `ScanScreen` unmounts. Cleared by `showSection` on every move, so a later
   * `'crop'` section — set by a stale value surviving a role or session
   * change — can never render an image from a scan somebody already left.
   */
  const [capturedImage, setCapturedImage] = useState<Blob | null>(null);
  /**
   * The Size the next scan declares, or `null` for "All sizes".
   *
   * **Held here rather than in `ScanScreen`, and deliberately not in the
   * browser.** A staff member working through a pallet of one size declares
   * it once; keeping it on this component is what carries the declaration
   * across the Scan → Results → Scan round trip that unmounts the screen
   * between every scan. The POC persists the same choice in `localStorage`,
   * which `no-client-token-storage.test.ts` forbids anywhere in this app —
   * so this resets on a reload, and that is the price of the storage rule.
   *
   * Not cleared by `showSection`, unlike `capturedImage` and `candidates`:
   * those are one scan's data and stale after it, while this is a standing
   * declaration about the tiles in front of the person holding the phone.
   */
  const [declaredSize, setDeclaredSize] = useState<string | null>(null);
  /**
   * Which surface opened the crop editor. `'results'` keeps the candidates
   * and the frame in place so Back can return to them; `'scan'` has nothing
   * to return to but the viewfinder.
   */
  const [cropOrigin, setCropOrigin] = useState<CropOrigin>('scan');
  /**
   * `submitScan`'s answer to the crop just confirmed, or `null`.
   *
   * `capturedImage`'s twin, one surface over: `ResultsScreen` needs the whole
   * ranked array and there is no route to fetch it back — a match that was
   * not persisted anywhere is gone the moment the request that produced it
   * resolves (no `Scan` table exists yet — Story 3.5). Cleared by
   * `showSection` on every move, so a later `'results'` section — set by a
   * stale value surviving a role or session change — can never render a match
   * from a scan somebody already left. `null` is "no result yet"; an *empty*
   * array is a real answer (no confident match) and is never confused with
   * the absence above.
   */
  const [candidates, setCandidates] = useState<ScanCandidate[] | null>(null);
  /**
   * The Catalogue's last submitted search, held here so it outlives the screen.
   *
   * `CatalogueScreen` is unmounted the moment a row, "+ Add Tile" or Bulk
   * upload is pressed — this gate swaps the surface rather than stacking one —
   * so a query held inside it would be gone by the time `Back` brought the
   * screen home. The acceptance clause is that `Back` returns to the Catalogue
   * *with the search still in place*, and an Administrator working through a
   * range of twenty tiles would otherwise retype the fragment twenty times.
   *
   * **Deliberately not cleared by `showSection`**, unlike the two selections
   * above, and the difference is what each one is: `editing` and `editingTile`
   * are a person's record and a catalogue row, which have no business
   * surviving a move to another surface, while this is a view preference —
   * where the reader had got to in a list. It *is* cleared on sign-out, below,
   * because on a shared shop-floor handset even a Code fragment is catalogue
   * data the next person did not type.
   */
  const [catalogueQuery, setCatalogueQuery] = useState('');
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
    // The row the edit screen was holding goes with the section, and for the
    // same reason: it is somebody's name, address and role, and leaving it in
    // state across a sign-out means the next person on a shared shop-floor
    // handset is one stale section away from seeing it.
    if (status !== 'signed-in') {
      setSection('scan');
      setEditing(null);
      // The tile goes with the row, and for a weaker version of the same
      // reason: a Code and a Size are not somebody's name and address, but
      // they are catalogue data, and catalogue exfiltration through a shared
      // handset is what AGENTS.md names as the primary commercial threat.
      setEditingTile(null);
      // The captured image goes with them, for a stronger version of the same
      // reason: it is a photo of the shop floor and whatever tile was in
      // frame, taken on a handset the next shift also uses.
      setCapturedImage(null);
      // The match goes with the image that produced it, for the same
      // reason one step further along: a ranked Candidate carries the same
      // catalogue data — Codes, Sizes, Categories, reference images — that
      // `editingTile` above is cleared for.
      setCandidates(null);
      // And the search with them, for the same reason one step smaller: a
      // fragment of a Code is still something the next person on the handset
      // did not type.
      setCatalogueQuery('');
    }
  }

  if (lastRole !== (user?.role ?? null)) {
    setLastRole(user?.role ?? null);
    // The role's own reconciler, beside the status's and for the same reason:
    // `currentScreen` *reads past* a section the new role cannot reach, and
    // reading past it is not the same as clearing it. What goes wrong while the
    // stale value sits in state is invisible until it isn't — if the role is
    // restored, and an Administrator demoted and promoted back within a shift is
    // a two-click operation since Story 1.10 shipped the editor, the create screen reopens by
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
    if (!reachableBy(section, user?.role ?? null)) {
      setSection('scan');
      setEditing(null);
      setEditingTile(null);
      // Scan, Crop and Results are reachable by every role, so this branch
      // cannot actually be taken for any of the three today — but the
      // capture and the match belong with the two selections above for the
      // same reason, and stating it here rather than only in `showSection`
      // is what keeps a future role-gated surface from inheriting a gap
      // instead of the fix.
      setCapturedImage(null);
      setCandidates(null);
      // And the search, for the reason the sign-out reconciler above clears it:
      // a fragment of a Code is catalogue data, and a demotion is the moment
      // the Catalogue stops being this person's to read. Leaving it in state
      // would also hand it straight back — a demotion and a promotion within
      // one shift is two clicks since Story 1.10 — so the Catalogue would
      // reopen narrowed by a search made under a role that no longer applies.
      setCatalogueQuery('');
    }
  }

  const screen = currentScreen(
    status,
    user,
    section,
    editing,
    editingTile,
    capturedImage,
    candidates,
  );
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
    // The row being edited belongs to the edit screen and to nothing else.
    // Cleared on every move away from it, so a later `'edit-user'` section — set
    // by a press of Edit that has not yet chosen a row, or left behind by a
    // reconciler — can never render somebody the Administrator looked at minutes
    // ago. `showEditUser` below is the one path that sets it, and it sets the
    // row before the section.
    setEditing(null);
    // The tile being edited belongs to the edit screen and to nothing else,
    // exactly as the row above does. Cleared on every move away from it, so a
    // later `'edit-tile'` section can never render a tile the Administrator
    // looked at minutes ago — which on this surface would be an edit form
    // pre-filled with one tile's Code under another tile's picture.
    setEditingTile(null);
    // The captured image belongs to Crop and to nothing else, exactly as the
    // row and the tile above do. Cleared on every move away from it, so a
    // later `'crop'` section can never render an image from a scan the user
    // already left — which on this surface would be Crop opening on somebody
    // else's photo taken minutes ago.
    setCapturedImage(null);
    // The match belongs to Results and to nothing else, the same reason one
    // step further along: a later `'results'` section can never render a
    // scan's Candidates after the user has already left them.
    setCandidates(null);
    setSection(next);
  }

  function showEditTile(target: Tile): void {
    // The tile first, then the section, for `showEditUser`'s reason:
    // `currentScreen` reads both, and setting the section first would give it
    // one render with `'edit-tile'` and no tile — which it answers with the
    // Catalogue, so the screen would flicker back to where it came from. React
    // batches these two, and the order says why it may not be relied on to.
    setSignOutError(null);
    // The *other* selections go, exactly as `showSection` clears all four:
    // these four functions are the only paths that set one, so without this
    // a row, a capture or a match from another surface survives a move to
    // Edit tile and back, and `showSection`'s stated invariant — that no
    // selection outlives the screen it belongs to — would be true of one
    // path and not of the four that matter.
    setEditing(null);
    setCapturedImage(null);
    setCandidates(null);
    setEditingTile(target);
    setSection('edit-tile');
  }

  function showEditUser(target: User): void {
    // The row first, then the section: `currentScreen` reads both, and setting
    // the section first would give it one render with `'edit-user'` and no row —
    // which it answers with the list, so the screen would flicker back to where
    // it came from. React batches these two, and the order says why it may not
    // be relied on to.
    setSignOutError(null);
    // See `showEditTile`: the other selections go with the move.
    setEditingTile(null);
    setCapturedImage(null);
    setCandidates(null);
    setEditing(target);
    setSection('edit-user');
  }

  function showCrop(image: Blob, origin: CropOrigin): void {
    // The image first, then the section — `showEditTile`'s reason:
    // `currentScreen` reads both, and setting the section first would give it
    // one render with `'crop'` and no image, which it answers with Scan, so
    // the screen would flicker back to where the shutter was just pressed.
    setSignOutError(null);
    // The other selections go with the move, exactly as `showEditTile` clears
    // them for its own — except the candidates when the crop is refining a
    // Result, which Back has to be able to return to.
    setEditing(null);
    setEditingTile(null);
    if (origin === 'scan') setCandidates(null);
    setCropOrigin(origin);
    setCapturedImage(image);
    setSection('crop');
  }

  function showResults(result: ScanCandidate[], image: Blob): void {
    // The candidates first, then the section — `showCrop`'s own reason:
    // `currentScreen` reads both, and setting the section first would give it
    // one render with `'results'` and nothing captured, which it answers with
    // Scan, so the screen would flicker back to where the shutter was just
    // pressed.
    setSignOutError(null);
    // The other selections go with the move, exactly as `showCrop` clears
    // them for its own. **The frame stays**: it is what "Adjust crop" on
    // Results opens, and it goes with the candidates the moment the user
    // leaves them (`showSection` clears both).
    setEditing(null);
    setEditingTile(null);
    setCapturedImage(image);
    setCandidates(result);
    setSection('results');
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

  // Captured once past the sign-in guard above, so the closures below read a
  // `Role` rather than re-narrowing `user`.
  const role = user.role;

  /**
   * The nav's own entry point. Every `NavKey` is a `Section` of the same
   * name — the nav points at the six top-level surfaces and at nothing else —
   * so this is `showSection` with the type saying which six.
   */
  function navigate(key: NavKey): void {
    showSection(key);
  }

  /**
   * The props every `AppShell` below shares: the app bar's two controls and
   * the role-conditional nav, with `current` naming the entry the screen
   * belongs to (Crop and Results are Scan's; Create/Edit user are Users'; the
   * three tile surfaces are the Catalogue's) or `null` for Account, which is
   * reached from the app bar rather than the nav.
   */
  function frame(current: NavKey | null): {
    onSignOut: () => void;
    onOpenAccount: () => void;
    nav: {
      role: Role;
      current: NavKey | null;
      onNavigate: (key: NavKey) => void;
    };
  } {
    return {
      onSignOut: handleSignOut,
      onOpenAccount: () => showSection('account'),
      nav: { role, current, onNavigate: navigate },
    };
  }

  if (screen === 'scan') {
    // Inside the shell, in place of the home panel, exactly as every other
    // surface reached from a home-panel door is: the app bar stays, so Sign
    // out stays, and `AppShell` provides the one `<main>` the focus effect
    // above moves focus to. Reachable by every authenticated role —
    // `reachableBy`'s default covers it — so there is no role guard here, the
    // one difference from every screen below it.
    return (
      <AppShell {...frame('scan')}>
        {signOutFailure}
        <ScanScreen
          // The whole frame, straight to matching: `submitScan` runs the
          // request and `showResults` lands once it resolves. A rejection
          // propagates back to `ScanScreen`, which renders it beside a live
          // viewfinder — the retake is the shutter, and the crop is offered.
          onCaptured={async (image) => {
            const result = await submitScan(image, FULL_FRAME, declaredSize);
            showResults(result, image);
          }}
          onCrop={(image) => showCrop(image, 'scan')}
          declaredSize={declaredSize}
          onDeclareSize={setDeclaredSize}
        />
      </AppShell>
    );
  }

  if (screen === 'crop' && capturedImage !== null) {
    // **The false branch is what is unreachable**: `currentScreen` already
    // answers `'scan'` for a `'crop'` section with nothing captured, so this
    // condition never fails at runtime. It is written anyway because it is
    // what narrows `capturedImage` for the prop below — removing it as
    // redundant breaks the build, so it says why, exactly as the `edit-tile`
    // branch below does for `editingTile`.
    //
    // Back returns to wherever the editor was opened from: the Results it is
    // refining (candidates and frame still held), or the viewfinder. Retake
    // after a quality refusal always goes to the viewfinder — the answer to a
    // blurry frame is the camera, not the result it came from.
    return (
      <AppShell {...frame('scan')}>
        {signOutFailure}
        <CropScreen
          image={capturedImage}
          onBack={() =>
            cropOrigin === 'results' && candidates !== null
              ? setSection('results')
              : showSection('scan')
          }
          onRetake={() => showSection('scan')}
          // `submitScan` runs the request; `showResults` only runs once it
          // resolves — a rejection propagates straight back to `CropScreen`,
          // which is what leaves the image and the selection in place with
          // Confirm re-enabled rather than this function clearing them on a
          // failed request.
          // The same declaration travels with a cropped resubmission: the
          // crop changes which pixels are matched, never which tile is in the
          // staff member's hand.
          onConfirm={async (rect) => {
            const result = await submitScan(capturedImage, rect, declaredSize);
            showResults(result, capturedImage);
            return result;
          }}
        />
      </AppShell>
    );
  }

  if (screen === 'results' && candidates !== null) {
    // **The false branch is what is unreachable**: `currentScreen` already
    // answers `'scan'` for a `'results'` section with nothing captured, so
    // this condition never fails at runtime. It is written anyway because it
    // is what narrows `candidates` for the prop below — removing it as
    // redundant breaks the build, so it says why, exactly as the `crop`
    // branch above does for `capturedImage`.
    //
    // Back goes to Scan, not to the home panel: Scan is where a fresh capture
    // is made, and Results has nothing of its own to return to.
    return (
      <AppShell {...frame('scan')}>
        {signOutFailure}
        <ResultsScreen
          candidates={candidates}
          onBack={() => showSection('scan')}
          // The optional crop, on the frame these candidates came from. The
          // frame is always held alongside a result today; the guard is what
          // narrows it for the call.
          onAdjustCrop={
            capturedImage === null ? undefined : () => showCrop(capturedImage, 'results')
          }
        />
      </AppShell>
    );
  }

  if (screen === 'history') {
    // Inside the shell, in place of the home panel, exactly as Users is: the
    // app bar stays, so Sign out stays, and the screen supplies its own way
    // back. It renders no `<main>` of its own — `AppShell` provides the one
    // the focus effect above moves focus to.
    //
    // Back goes to the home panel rather than to Scan: History is a
    // top-level nav entry of its own (Story 3.5, EXPERIENCE.md line 31), not
    // a surface reached from Scan the way Crop and Results are.
    return (
      <AppShell {...frame('history')}>
        {signOutFailure}
        <HistoryScreen onBack={() => showSection('home')} />
      </AppShell>
    );
  }

  if (screen === 'users') {
    // Inside the shell, in place of the home panel, exactly as the two screens
    // below are: the app bar stays, so Sign out stays, and the screen supplies
    // its own way back. It renders no `<main>` of its own — `AppShell` provides
    // the one the focus effect above moves focus to.
    return (
      <AppShell {...frame('users')}>
        {signOutFailure}
        <UserListScreen
          onAddUser={() => showSection('create-user')}
          onBack={() => showSection('home')}
          onEditUser={showEditUser}
        />
      </AppShell>
    );
  }

  if (screen === 'audit') {
    // Inside the shell, in place of the home panel, exactly as Users is: the
    // app bar stays, so Sign out stays, and the screen supplies its own way
    // back. It renders no `<main>` of its own — `AppShell` provides the one the
    // focus effect above moves focus to.
    //
    // Back goes to the home panel rather than to the list: this is a top-level
    // nav entry of its own (EXPERIENCE.md line 38), not a surface reached from
    // another one.
    return (
      <AppShell {...frame('audit')}>
        {signOutFailure}
        <AuditLogScreen onBack={() => showSection('home')} />
      </AppShell>
    );
  }

  if (screen === 'catalogue') {
    // Inside the shell, in place of the home panel, exactly as Users and the
    // Audit log are: the app bar stays, so Sign out stays, and the screen
    // supplies its own way back. It renders no `<main>` of its own —
    // `AppShell` provides the one the focus effect above moves focus to.
    //
    // Back goes to the home panel: this is a top-level nav entry of its own
    // (EXPERIENCE.md line 35), not a surface reached from another one. The
    // three surfaces *it* reaches are below, and each of them goes back here.
    return (
      <AppShell {...frame('catalogue')}>
        {signOutFailure}
        <CatalogueScreen
          onAddTile={() => showSection('add-tile')}
          onBack={() => showSection('home')}
          onBulkUpload={() => showSection('bulk-upload')}
          onEditTile={showEditTile}
          // Told on every submit, so the query survives this screen being
          // unmounted by the very controls it renders. Not keyed on it: the
          // screen reads it once at mount, and remounting on each keystroke
          // would throw the table away.
          onSearch={setCatalogueQuery}
          query={catalogueQuery}
        />
      </AppShell>
    );
  }

  if (screen === 'add-tile') {
    // Inside the shell, in place of the home panel, exactly as the Catalogue
    // is. It renders no `<main>` of its own — `AppShell` provides the one the
    // focus effect above moves focus to.
    //
    // Back goes to the Catalogue, not to the home panel: the Catalogue is
    // where "+ Add Tile" was pressed (EXPERIENCE.md line 36), and it is where
    // the new tile belongs. `CatalogueScreen` refetches on mount, so returning
    // to it lists the catalogue as it now stands — under whatever search was
    // in place, which is the point of keeping it: an Administrator adding a
    // run of `RP.CMA.*` tiles comes back to that run rather than to all 381.
    // A tile whose Code does not contain the fragment is therefore not on
    // screen; emptying the box lists it.
    return (
      <AppShell {...frame('catalogue')}>
        {signOutFailure}
        <AddTileScreen onBack={() => showSection('catalogue')} />
      </AppShell>
    );
  }

  if (screen === 'edit-tile' && editingTile !== null) {
    // **The false branch is what is unreachable**: `currentScreen` already
    // answers `'catalogue'` for an `'edit-tile'` section with no tile, so this
    // condition never fails at runtime. It is written anyway because it is
    // what narrows `editingTile` for the prop below — removing it as redundant
    // breaks the build, so it says why.
    //
    // Back goes to the Catalogue, not to the home panel: a row is where Edit
    // was pressed, and `CatalogueScreen` refetches on mount, so returning to
    // it shows the row as it was just saved.
    return (
      <AppShell {...frame('catalogue')}>
        {signOutFailure}
        <EditTileScreen
          // Keyed on the tile, because the screen seeds its form from `tile`
          // at mount and never reconciles the prop — `EditUserScreen`'s own
          // arrangement, and for the same reason. Today nothing can swap one
          // tile for another without a trip through the Catalogue, which
          // unmounts it, but that is a property of `showSection` rather than
          // of this screen, and a keyless element would turn a later change
          // there into a form showing one tile's Code under another's picture.
          key={editingTile.id}
          onBack={() => showSection('catalogue')}
          // A confirmed removal ends the tile this screen is about, and this
          // screen was opened *about that tile* — so there is nothing left for
          // it to show. It leaves for the Catalogue, whose refetch on mount is
          // what makes the row's absence visible; staying would re-render as a
          // code-entry stage for a Code that no longer names anything, with
          // Back as the only way out.
          onRemoved={() => showSection('catalogue')}
          tile={editingTile}
        />
      </AppShell>
    );
  }

  if (screen === 'bulk-upload') {
    // Inside the shell, in place of the home panel, exactly as Add tile and
    // Edit tile are. It renders no `<main>` of its own — `AppShell` provides
    // the one the focus effect above moves focus to.
    //
    // Back goes to the Catalogue: EXPERIENCE.md line 37 reaches Bulk Upload
    // *from* the Catalogue, so that is where its control lives and where Back
    // returns to — and the Catalogue refetches on mount, so the batch is on
    // screen on arrival, narrowed by whatever search was in place. A batch
    // wider than the search is listed in full by emptying the box.
    return (
      <AppShell {...frame('catalogue')}>
        {signOutFailure}
        <BulkUploadScreen onBack={() => showSection('catalogue')} />
      </AppShell>
    );
  }

  if (screen === 'edit-user' && editing !== null) {
    // `editing !== null` is unreachable at runtime — `currentScreen` already
    // answers `'users'` for an `'edit-user'` section with no row — and it is here
    // so TypeScript narrows the prop below. Removing it as redundant breaks the
    // build, so it says why.
    //
    // Inside the shell, in place of the home panel, exactly as the two screens
    // below are. Back goes to the list, not to the home panel: the list is where
    // Edit was pressed, and `UserListScreen` refetches on mount, so returning to
    // it shows the row as it was just saved.
    return (
      <AppShell {...frame('users')}>
        {signOutFailure}
        <EditUserScreen
          // Keyed on the row, because the screen seeds all of its state from
          // `user` at mount and never reconciles the prop. Today nothing can
          // swap one row for another without a trip through the list, which
          // unmounts it — but that is a property of `showSection`, not of this
          // screen, and a keyless element would turn a later change there into
          // an editor showing one person's fields under another's name.
          key={editing.id}
          onBack={() => showSection('users')}
          // The API has just returned a fresher copy of a row. `adoptUser`
          // stores it **only when it is the caller's own** (the id guard is in
          // `SessionProvider`), which is what keeps the app bar's name and the
          // home panel's Users door in step after a self-rename or a
          // self-demotion — a demotion then falls straight through the role
          // reconciler above, with no reload and no toast (EXPERIENCE.md line
          // 95). For anybody else's row it does nothing, and the refetch on the
          // way back to the list is what shows the change.
          onSaved={adoptUser}
          user={editing}
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
      <AppShell {...frame('users')}>
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
      <AppShell {...frame(null)}>
        {signOutFailure}
        <AccountSettingsScreen onBack={() => showSection('home')} />
      </AppShell>
    );
  }

  // The home panel — no longer the landing surface (Scan is), but still the
  // place Back returns to from every top-level screen and the brand leads to.
  // A greeting, the one thing the product does as a navy hero with the one
  // accent control, and the rest of the nav as outlined quick links. Each
  // quick link's name is a phrase ("Manage users") rather than the nav
  // entry's own word ("Users"), so no destination is ever in the document
  // twice under one name.
  return (
    <AppShell {...frame('home')}>
      <section className={styles.home}>
        <div className={styles.intro}>
          <h1 className={styles.title}>Rocell Tile Scanner</h1>
          {/* The session made visible: if this name is right, the cookie, the
              session row and the per-request lookup all worked. */}
          <p className={styles.greeting}>Signed in as {user.name}.</p>
        </div>
        {signOutFailure}
        <div className={styles.hero}>
          <Scan className={styles.heroIcon} aria-hidden="true" />
          <div className={styles.heroCopy}>
            <h2 className={styles.heroTitle}>Identify a tile</h2>
            <p className={styles.heroText}>
              Photograph a tile and get the three closest matches from the catalogue, each with its
              reference image, Size and Category.
            </p>
          </div>
          {/* The door to Scan (Story 3.1), reachable by every authenticated role
              and the panel's one `--color-accent` control: DESIGN.md names
              "Scan" itself as an accent-button example. */}
          <button className={styles.scan} type="button" onClick={() => showSection('scan')}>
            <Camera className={styles.buttonIcon} aria-hidden="true" />
            Scan a tile
          </button>
        </div>
        <h2 className={styles.sectionTitle}>Go to</h2>
        <div className={styles.quickLinks}>
          {/* History (Story 3.5): a caller's own scan history is theirs to
              read whatever their role — `reachableBy`'s default covers it. */}
          <button className={styles.history} type="button" onClick={() => showSection('history')}>
            <ClockCounterClockwise className={styles.quickIcon} aria-hidden="true" />
            <span className={styles.quickLabel}>Your scan history</span>
            <CaretRight className={styles.quickCaret} aria-hidden="true" />
          </button>
          {/* The admin surfaces, role-conditional as EXPERIENCE.md line 18
              requires: a Staff user never sees an entry they cannot use. One
              guard for the whole group. A convenience only — the server
              refuses a Staff caller at every `/admin/` route regardless of
              what this renders (AGENTS.md Policy), and the cached `user` read
              here is a render cache and never a decision. */}
          {role === 'admin' && (
            <>
              <button
                className={styles.catalogue}
                type="button"
                onClick={() => showSection('catalogue')}
              >
                <SquaresFour className={styles.quickIcon} aria-hidden="true" />
                <span className={styles.quickLabel}>Browse the catalogue</span>
                <CaretRight className={styles.quickCaret} aria-hidden="true" />
              </button>
              <button
                className={styles.userList}
                type="button"
                onClick={() => showSection('users')}
              >
                <Users className={styles.quickIcon} aria-hidden="true" />
                <span className={styles.quickLabel}>Manage users</span>
                <CaretRight className={styles.quickCaret} aria-hidden="true" />
              </button>
              <button
                className={styles.auditLog}
                type="button"
                onClick={() => showSection('audit')}
              >
                <ListBullets className={styles.quickIcon} aria-hidden="true" />
                <span className={styles.quickLabel}>Review the audit log</span>
                <CaretRight className={styles.quickCaret} aria-hidden="true" />
              </button>
            </>
          )}
        </div>
      </section>
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
