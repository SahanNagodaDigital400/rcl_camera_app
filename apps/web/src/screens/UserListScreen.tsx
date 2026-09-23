import { useCallback, useEffect, useId, useRef, useState } from 'react';
import type { JSX } from 'react';

import { ApiRequestError, MALFORMED_RESPONSE, apiRequest } from '../api/client';
import { ConfirmDialog } from '../components/ConfirmDialog';
import styles from './UserListScreen.module.css';
import { isUser } from '@rocell/schema/user';
import type { Role, User } from '@rocell/schema/user';

/** Shown for a failure that arrives as something other than an `ApiRequestError`. */
const UNEXPECTED = 'The user list could not be loaded. Try again.';

/**
 * And the same fallback for a row-end verb.
 *
 * Every failure `apiRequest` can produce — a refused status, a timeout, a dead
 * network — arrives wrapped, carrying a sentence written for the person reading
 * it, so this is the fallback for a bug rather than for a reachable state. It
 * exists because the alternative, rendering `String(failure)`, puts a
 * stack-shaped string in front of an Administrator.
 */
const ACTION_FAILED = 'That change could not be made. Try again.';

/** The in-flight line. `role="status"`, so the wait is announced rather than silent. */
const LOADING = 'Loading users…';

/**
 * Unreachable in the product — the caller is themselves a row on this list, so
 * the array is never empty for anyone who can read it. Rendered anyway, because
 * a bare header row with nothing under it looks like a screen that failed rather
 * than a screen with nothing to say.
 */
const NO_USERS = 'No users.';

/** The glossary's own words for the two roles (PRD Glossary, EXPERIENCE.md). */
const ROLE_LABELS: Record<Role, string> = {
  staff: 'Staff',
  admin: 'Administrator',
};

/** The word on the status badge. Never colour alone (EXPERIENCE.md's accessibility floor). */
const ACTIVE = 'Active';
const DEACTIVATED = 'Deactivated';

/** What the Last login cell reads when the account has never signed in. */
const NEVER = 'Never';

/**
 * The Administrator floor, in the API's own words.
 *
 * `api/users.py`'s `LAST_ACTIVE_ADMINISTRATOR`, character for character, and the
 * only sentence on this screen the server also owns. It is restated rather than
 * imported because nothing crosses that boundary at build time —
 * `error-code-parity.test.ts` pins the *codes*, not the copy.
 *
 * **It is used for the pre-flight only.** When the request is actually made and
 * refused, the dialog renders the API's own `409` message instead, so a drift
 * here can never make the screen state a rule the server does not enforce: the
 * worst it can do is word the *pre-flight* differently from the server, and the
 * server still refuses the same operation with the same code (AGENTS.md:13).
 */
const LAST_ACTIVE_ADMINISTRATOR =
  'There must always be at least one active Administrator. ' +
  'Make somebody else an Administrator, or activate one, first.';

/** The three row-end verbs, as the visible word on each control. */
const EDIT = 'Edit';
const DEACTIVATE = 'Deactivate';
const ACTIVATE = 'Activate';
const DELETE = 'Delete';

/** Which verb a dialog is about. `activate` never opens one to confirm. */
type Verb = 'deactivate' | 'activate' | 'delete';

/**
 * The open dialog, or `null`.
 *
 * `refusal === null` is the **confirm** state and a sentence is the **refusal**
 * state — the two EXPERIENCE.md:148 describes, and no third. The `User` is
 * carried rather than an id so the copy can name the person without a second
 * lookup into a list that may have been refetched underneath it.
 */
interface Dialog {
  verb: Verb;
  user: User;
  refusal: string | null;
}

/**
 * What this screen is showing.
 *
 * Three states, and still no fourth: a row-end verb in flight is **not** one of
 * them. The table stays on screen and stays readable throughout — no spinner
 * replaces it, no row is removed before the server has answered — so the
 * in-flight verb is held beside this as a single pending id rather than folded
 * in here.
 */
type Listing =
  | { kind: 'loading' }
  | { kind: 'failed'; message: string }
  | { kind: 'loaded'; users: readonly User[] };

/**
 * Narrow the response body to an array of the shared `User`, or fail loudly.
 *
 * `CreateUserScreen.asUser`'s sibling, per element. `isUser` rejects a missing
 * key, a malformed UUID, a non-UTC timestamp — and any extra key, which is how a
 * `password_hash` would announce itself. A partially-understood body must not be
 * rendered as an authoritative answer to "who has access": a row this screen
 * could not parse is a person an Administrator would never know to look for.
 */
function asUsers(body: unknown): readonly User[] {
  if (Array.isArray(body)) {
    const rows: unknown[] = body;
    if (rows.every(isUser)) return rows;
  }
  throw new ApiRequestError(MALFORMED_RESPONSE, 'The server returned an unexpected response.', 200);
}

/**
 * The account's last sign-in in the reader's own locale, or `Never`.
 *
 * Null is the account that has never signed in — a user provisioned a moment ago
 * and not yet handed their credential — and the word is better than a blank cell,
 * which reads as a value that failed to load.
 *
 * **Neither this nor `lockNotice` below re-checks that the string parses**, and
 * that is the one statement of why: `asUsers` has already run every element
 * through `isUser`, whose `isUtcTimestamp` accepts a value only if it matches the
 * ISO 8601 UTC shape *and* `Number.isFinite(Date.parse(value))`. A second guard
 * here would be dead code that reads as though an unparseable timestamp were a
 * case this screen expects — and the honest way to widen what can arrive is to
 * widen the contract, not to re-validate behind it.
 */
function lastLogin(user: User): string {
  const value = user.last_login_at;
  if (value === null) return NEVER;
  return new Date(value).toLocaleString();
}

/**
 * The lock line, or null when there is nothing to say.
 *
 * FR-4's lockout as an Administrator sees it. **Status, never enforcement**, and
 * `shared_schema`'s own comment is the rule: the column is never cleared, so a
 * value in the past means "locked recently" and not "locked". Nothing on this
 * screen or behind it is gated on the answer, which is what makes it safe to
 * compare against the *browser's* clock — a badly-skewed device can show a lapsed
 * lock or miss a live one, and the throttle goes on reading its own
 * `login_attempts` row either way.
 *
 * A line of muted text rather than a fourth badge: DESIGN.md names three badge
 * treatments and no locked one, and the obvious candidate colour is the accent,
 * which would put a second orange thing on a screen whose "+ Add user" is meant
 * to be the only one.
 */
function lockNotice(user: User): string | null {
  const value = user.locked_until;
  if (value === null) return null;
  const until = Date.parse(value);
  if (until <= Date.now()) return null;
  return `Locked until ${new Date(until).toLocaleString()}`;
}

/**
 * Whether taking this account away would leave the product with no Administrator.
 *
 * The server's `_DEACTIVATE_USER`/`_DELETE_USER` predicate, read off the list
 * already in hand: the row is an active Administrator and no *other* active
 * Administrator is on the list. A deactivated Administrator is not counted, on
 * either side of the comparison, exactly as the SQL's `other.active` arm does.
 *
 * **This is presentation, never a gate.** EXPERIENCE.md:148 asks for the refusal
 * to *replace* the confirmation dialog, which can only be decided before the
 * request is made — an Administrator must not be walked through a confirm that
 * was never going to be honoured. AGENTS.md:13 is satisfied because the server
 * refuses the same operation independently, with the same code and the same
 * sentence, and the dialog's refusal state renders that `409` verbatim when a
 * stale list gets this wrong.
 */
function blockedByFloor(users: readonly User[], target: User): boolean {
  if (target.role !== 'admin' || !target.active) return false;
  return !users.some((other) => other.id !== target.id && other.role === 'admin' && other.active);
}

/** The route each verb calls, and the method it calls it with. */
function requestFor(verb: Verb, user: User): [string, string] {
  if (verb === 'delete') return [`/admin/users/${user.id}`, 'DELETE'];
  return [`/admin/users/${user.id}/${verb}`, 'POST'];
}

/**
 * The dialog's heading and body for one verb on one person.
 *
 * EXPERIENCE.md:72 and :144 — the object and the consequence, by name, never a
 * bare "Are you sure?" (EXPERIENCE.md:56). The consequence sentences are the
 * only place in the product that explains what each verb costs, so they say the
 * part that is not obvious: a deactivation ends the session *now* and is
 * reversible; a delete is not reversible and frees the address.
 */
function confirmCopy(verb: Verb, user: User): { heading: string; body: string } {
  if (verb === 'delete') {
    return {
      heading: `Delete ${user.name}?`,
      body:
        `${user.name}'s account is removed for good and cannot be restored. Any session ` +
        `they have open ends immediately, and ${user.email} is free to use again.`,
    };
  }
  return {
    heading: `Deactivate ${user.name}?`,
    body:
      `${user.name} is signed out immediately, even if they are using the app right now, ` +
      'and cannot sign in again until the account is activated.',
  };
}

/** And the heading a refusal carries. The body is always the rule's own sentence. */
function refusalHeading(verb: Verb, user: User): string {
  if (verb === 'delete') return `Cannot delete ${user.name}`;
  if (verb === 'activate') return `Cannot activate ${user.name}`;
  return `Cannot deactivate ${user.name}`;
}

interface UserListScreenProps {
  onBack: () => void;
  onAddUser: () => void;
  onEditUser: (user: User) => void;
}

/**
 * Users — every account, with its status and its last sign-in (FR-10), and the
 * three verbs that change who has access (FR-13).
 *
 * EXPERIENCE.md line 33's User List, and the surface FR-4 meant by the lockout
 * being "visible to Administrators on that user's status". Rendered *inside* the
 * shell, in place of the home panel, exactly as Create user and Account Settings
 * are: it carries no `<main>` of its own, because `AppShell` already provides the
 * one main landmark the gate moves focus to on a screen swap.
 *
 * **It calls `apiRequest` directly rather than going through `SessionProvider`.**
 * That context is the *caller's own* session — its status, its cached user, and
 * the three mutations that change it. Reading somebody else's row changes none of
 * those, and routing an admin read through it would put every admin surface from
 * Story 1.10 on into the session provider. The one exception, added by that
 * story, is `SessionProvider.adoptUser` on the edit screen's save path, and it
 * is guarded on a matching id so it can only ever adopt the caller's own row —
 * see `CreateUserScreen`, which states the rule and the exception together.
 *
 * **A self-deactivation and a self-delete are deliberately not special-cased
 * here.** The answer lands, the refetch that follows it is a `401`,
 * `apiRequest` notifies the unauthorized observer, and `SessionProvider` drops
 * the shell to Login — which is the same path an expiry and a revocation from
 * another device already take. Nothing in this file arranges that, and nothing
 * in this file should: a screen that knew which row was the caller's would be a
 * second opinion about the session.
 *
 * **The role-conditional entry that opens this screen is a convenience, never the
 * control.** `App` renders it only for an Administrator and falls back to the
 * home panel if the cached role stops being `admin` — but the cached `User` is a
 * render cache and never an authorization decision (AGENTS.md Policy). The server
 * refuses a Staff caller at every route behind this screen regardless, through
 * `require_administrator`, which re-reads the role from Postgres on every request
 * (AD-3).
 *
 * Deliberately absent:
 *
 * - **No pagination, no search box, no sort control.** The API returns every
 *   account in one ordered array because FR-10 is every account; a filter on the
 *   one surface whose job is "who has access" hides the row somebody opened the
 *   screen to find. FR-18's search is catalogue search and belongs to Epic 2.
 * - **No unlock, no set-password and no credential reissue.** FR-4's lock is
 *   rendered here and ended by nothing anywhere in the product — no story in
 *   Epic 1 owns an admin unlock at all (DW-64) — and a forgotten password is
 *   handled by deleting the account and provisioning it again, which is now
 *   possible for the first time. Deleting an account deliberately does **not**
 *   clear its lockout: the counter is keyed on the address, so
 *   delete-and-recreate is not the unlock this product decided not to have.
 * - **No bulk selection and no row-end menu.** Four rows of controls is four
 *   controls, not a popup: a menu is a second widget with its own keyboard
 *   contract, and EXPERIENCE.md line 71's requirement is that a destructive
 *   action is *labelled*, which a plain labelled button satisfies directly. The
 *   role and status badges stay display-only (EXPERIENCE.md line 66) — never a
 *   button, at any width.
 * - **No view of the audit log.** All four endpoints behind this screen write
 *   an append-only entry naming the Administrator who acted and the account
 *   they acted on (Story 1.12) — a deactivation records how many sessions it
 *   revoked, a delete records the row it removed. Nothing here renders any of
 *   it, and nothing here should: the log has its own surface now
 *   (`AuditLogScreen`), reached from its own door on the home panel. A
 *   per-row "history" control would be a second, filtered view of a record
 *   whose whole value is being one chronological list.
 *
 * Copy follows EXPERIENCE.md's tone rules: short, factual, no exclamation marks.
 */
export function UserListScreen({
  onBack,
  onAddUser,
  onEditUser,
}: UserListScreenProps): JSX.Element {
  const titleId = useId();
  const [listing, setListing] = useState<Listing>({ kind: 'loading' });
  /**
   * The row whose verb is in flight, or `null`.
   *
   * One id rather than a set: the dialog is modal and the row-end controls are
   * frozen while it is open, so two verbs cannot be in flight at once. It is
   * also the re-entrancy guard — a second press while a request is open is
   * ignored rather than queued.
   */
  const [pending, setPending] = useState<string | null>(null);
  /**
   * The same fact as `pending`, a commit earlier.
   *
   * `pending` is what the *render* reads — it is what disables the controls —
   * and it is useless as a re-entrancy guard, because two presses in one tick
   * are batched and both read the value from before the first `setPending`. A
   * double-press on Confirm would then send two requests, and the second would
   * be answered `404` for a delete that had already succeeded, which the dialog
   * would render as a failure.
   *
   * So the guard is a ref, written synchronously, and `run` is where it is
   * checked: `press` guards too, but `run` is the function that actually
   * writes, and the confirm control's `disabled` cannot be relied on to have
   * committed by the time its own `onClick` fires.
   */
  const inFlight = useRef(false);
  const [dialog, setDialog] = useState<Dialog | null>(null);
  /**
   * Where focus goes when the control holding it is about to be unmounted.
   *
   * "Try again" is one such control — the failure block it sits in is replaced
   * by the in-flight line — and a deleted row is the other: the button that
   * deleted it goes with it, and a browser answers that by dropping focus to
   * `<body>`. A keyboard or screen-reader Administrator would then be back at
   * the top of the document, several tabs away from the screen they just acted
   * on. Every other screen here moves focus deliberately after a refusal
   * (`LoginScreen`, `CreateUserScreen`, `AccountSettingsScreen` all focus the
   * field at fault); this screen has no field, so the heading is the nearest
   * thing that keeps the reader where they were. `tabIndex={-1}` makes it
   * focusable without adding a tab stop.
   */
  const titleRef = useRef<HTMLHeadingElement>(null);
  /**
   * Whether the heading is owed focus, until the effect below gives it.
   *
   * A ref and an effect rather than a `focus()` inline, for `EditUserScreen`'s
   * reason one step further on: the element that should *not* keep focus is
   * removed by the same commit that would restore it. `ConfirmDialog`'s own
   * unmount puts focus back on the control that opened it, and that control is
   * exactly what a successful delete is about to remove — so the move has to
   * happen after the commit, where it is the last word rather than the first.
   */
  const rescueFocus = useRef(false);
  /**
   * Which fetch is allowed to write the answer.
   *
   * `SessionProvider`'s `live` flag, generalised to a screen whose fetch can be
   * started more than once. A plain boolean is enough for a mount-only request;
   * here "Try again" can start a second while the first is still open, and the
   * slower of the two must not overwrite the newer one. Bumping the counter
   * invalidates everything in flight — on a retry, on StrictMode's second effect
   * run, and on unmount.
   */
  const generation = useRef(0);

  const load = useCallback(() => {
    const mine = generation.current + 1;
    generation.current = mine;

    apiRequest('/admin/users')
      .then((body) => {
        if (generation.current === mine) setListing({ kind: 'loaded', users: asUsers(body) });
      })
      .catch((failure: unknown) => {
        // The API's own sentence, so the screen cannot state a rule the server
        // does not enforce — `administrator_required` from a demotion between two
        // requests reads exactly as the server worded it.
        //
        // A 401 is worded here exactly like any other refusal, and that is the
        // whole of this component's behaviour. *Inside the app* nobody sees it:
        // `apiRequest` notifies the unauthorized observer before it rejects, and
        // `SessionProvider` answers that by dropping the shell to the login
        // screen, so this screen is unmounted by the time the alert would paint.
        // That is also what a self-deactivation looks like from here. The
        // distinction matters because nothing in this file arranges it —
        // rendered on its own, this screen shows the sentence.
        if (generation.current === mine) {
          setListing({
            kind: 'failed',
            message: failure instanceof ApiRequestError ? failure.message : UNEXPECTED,
          });
        }
      });
  }, []);

  useEffect(() => {
    load();

    return () => {
      generation.current += 1;
    };
  }, [load]);

  useEffect(() => {
    // After the commit, so the heading is focused once the row that was deleted
    // — and the dialog that deleted it — have both gone. A ref rather than a
    // dependency on state: the request is "move focus once", which is an event.
    if (!rescueFocus.current) return;
    rescueFocus.current = false;
    titleRef.current?.focus();
  });

  function retry(): void {
    // Focus first, while the button pressed is still in the document: the state
    // change below unmounts it, and `titleRef` is where the reader is left
    // instead of on `<body>`.
    titleRef.current?.focus();
    // The state moves to `loading` here rather than inside `load`, so the alert
    // clears on the click rather than a frame later — and so nothing adjusts
    // state synchronously from inside the effect above, which is what `oxlint`'s
    // `react/set-state-in-effect` rule exists to stop.
    setListing({ kind: 'loading' });
    load();
  }

  async function run(verb: Verb, user: User): Promise<void> {
    // The guard that actually holds. See `inFlight` for why the disabled
    // control and the `pending` state are both a commit too late to be one.
    if (inFlight.current) return;
    inFlight.current = true;

    const [path, method] = requestFor(verb, user);
    setPending(user.id);
    try {
      await apiRequest(path, { method });
      setDialog(null);
      // The row updates inline (EXPERIENCE.md:146) rather than by a page
      // reload, and from the server's answer to a fresh list rather than from a
      // local edit of the array: the list is "who has access", and a copy of it
      // maintained on the client is a second opinion about that.
      if (verb === 'delete') rescueFocus.current = true;
      load();
    } catch (failure) {
      // The dialog stays open and swaps to its refusal state, carrying the
      // API's own sentence — a `409` from a stale list, a `404` from a row
      // somebody else already removed, or anything else. Rendering it here
      // rather than in the page's alert slot is what keeps the answer where the
      // Administrator is looking.
      setDialog({
        verb,
        user,
        refusal: failure instanceof ApiRequestError ? failure.message : ACTION_FAILED,
      });
    } finally {
      inFlight.current = false;
      setPending(null);
    }
  }

  function press(verb: Verb, user: User): void {
    // A second press while a request is open is ignored rather than queued —
    // on this row or on any other. Every row's controls are disabled to match
    // (see `frozen` below), so this is the guard behind a control that is
    // already unpressable rather than the only thing stopping it.
    if (inFlight.current) return;

    if (verb === 'activate') {
      // No confirmation: EXPERIENCE.md asks for one before a *destructive*
      // action, and giving an account back its access is the undo, not the
      // damage. A failure still lands in the dialog's refusal state.
      void run(verb, user);
      return;
    }

    if (listing.kind === 'loaded' && blockedByFloor(listing.users, user)) {
      // The dialog opens **as the refusal** (EXPERIENCE.md:148): no destructive
      // control is rendered and no request is sent.
      setDialog({ verb, user, refusal: LAST_ACTIVE_ADMINISTRATOR });
      return;
    }

    setDialog({ verb, user, refusal: null });
  }

  return (
    <section className={styles.screen}>
      <div className={styles.header}>
        <h1 className={styles.title} id={titleId} ref={titleRef} tabIndex={-1}>
          Users
        </h1>

        <div className={styles.actions}>
          {/* The screen's one accent control (DESIGN.md: exactly one per screen),
            and EXPERIENCE.md line 34's own route to Create/Edit User. Back is the
            secondary, navy-outlined one. */}
          <button className={styles.add} type="button" onClick={onAddUser}>
            + Add user
          </button>
          <button className={styles.back} type="button" onClick={onBack}>
            Back
          </button>
        </div>
      </div>

      {listing.kind === 'loading' && (
        <p className={styles.pending} role="status">
          {LOADING}
        </p>
      )}

      {listing.kind === 'failed' && (
        // One alert, and no table beside it: a list of "who has access" that is
        // missing rows is worse than no list at all, so nothing partial renders.
        // "Try again" refetches rather than asking for a page reload, which would
        // cost the whole session bootstrap for one failed request.
        <div className={styles.failure}>
          <p className={styles.error} role="alert">
            {listing.message}
          </p>
          <button className={styles.retry} type="button" onClick={retry}>
            Try again
          </button>
        </div>
      )}

      {listing.kind === 'loaded' &&
        (listing.users.length === 0 ? (
          <p className={styles.empty}>{NO_USERS}</p>
        ) : (
          /* One `<table>` at every width, inside a labelled focusable scroll
             container. The usual phone treatment — `display: block` on the
             table's parts with `::before` labels — strips the semantics that
             associate every cell with its column header, which is a real loss on
             a surface EXPERIENCE.md itself calls desktop-first. This keeps the
             header association and keeps the *page* from scrolling sideways at
             375px; the container scrolls instead, and takes focus so the last
             column is reachable from the keyboard. */
          <div className={styles.scroller} role="region" aria-labelledby={titleId} tabIndex={0}>
            <table className={styles.table} role="table">
              <thead className={styles.head} role="rowgroup">
                <tr role="row">
                  <th className={styles.heading} role="columnheader" scope="col">
                    Name
                  </th>
                  <th className={styles.heading} role="columnheader" scope="col">
                    Email
                  </th>
                  <th className={styles.heading} role="columnheader" scope="col">
                    Role
                  </th>
                  <th className={styles.heading} role="columnheader" scope="col">
                    Status
                  </th>
                  <th className={styles.heading} role="columnheader" scope="col">
                    Last login
                  </th>
                  {/* A column of its own rather than controls tucked into the
                      last data cell: a header is what associates the buttons
                      with what they are for. */}
                  <th className={styles.heading} role="columnheader" scope="col">
                    Actions
                  </th>
                </tr>
              </thead>
              <tbody className={styles.body} role="rowgroup">
                {listing.users.map((user) => {
                  const lock = lockNotice(user);
                  // **Every** row, not only the one whose request is open. One
                  // verb can be in flight at a time — `press` refuses a second
                  // — so a control left enabled on another row would be a
                  // control that does nothing when pressed, with no feedback
                  // saying why. The dialog covers the table while a *confirmed*
                  // verb runs, but Activate has no dialog, so without this
                  // there is a window where three controls a row are visibly
                  // live and inert.
                  const frozen = pending !== null;
                  return (
                    // A deactivated row is muted *as well as* badged, so the
                    // distinction survives a monochrome screen and is never
                    // carried by colour alone (EXPERIENCE.md's accessibility
                    // floor). The word on the badge is the signal that always
                    // works.
                    //
                    // `deactivatedRow` is added *on top of* `row` rather than
                    // instead of it: the row treatment — surface, hairline,
                    // hover — is DESIGN.md's `data-table-row` and belongs to
                    // every row, so a change to it must not apply to active rows
                    // only. The variant carries the muting and nothing else.
                    <tr
                      role="row"
                      className={
                        user.active ? styles.row : `${styles.row} ${styles.deactivatedRow}`
                      }
                      key={user.id}
                    >
                      <td className={styles.cell} data-label="Name" role="cell">
                        {user.name}
                      </td>
                      <td className={styles.cell} data-label="Email" role="cell">
                        {user.email}
                      </td>
                      <td className={styles.cell} data-label="Role" role="cell">
                        {/* Display-only, never a button (EXPERIENCE.md line 66).
                            Administrator is the heavier treatment on purpose —
                            it should read as the weightier role at a glance. */}
                        <span
                          className={user.role === 'admin' ? styles.roleAdmin : styles.roleStaff}
                        >
                          {ROLE_LABELS[user.role]}
                        </span>
                      </td>
                      <td className={styles.cell} data-label="Status" role="cell">
                        <span className={user.active ? styles.statusActive : styles.statusOff}>
                          {user.active ? ACTIVE : DEACTIVATED}
                        </span>
                        {lock !== null && <span className={styles.lock}>{lock}</span>}
                      </td>
                      <td className={styles.cell} data-label="Last login" role="cell">
                        {lastLogin(user)}
                      </td>
                      <td className={styles.cell} data-label="Actions" role="cell">
                        {/* Real `<button>`s at the row end, labelled, never bare
                            icons and never the `<tr>` itself (EXPERIENCE.md
                            line 71's own reading, and the accessibility floor's
                            keyboard path). Each accessible name names the
                            person, so a screen reader hears which row the
                            control belongs to — the visible word is the verb and
                            `aria-label` carries the rest, which keeps the column
                            narrow without making any of them ambiguous out of
                            context.

                            Frozen together while this row's own request is in
                            flight: pressing Delete on a row whose deactivation
                            has not answered yet is two verbs racing on one
                            account. */}
                        <div className={styles.rowActions}>
                          <button
                            aria-label={`${EDIT} ${user.name}`}
                            className={styles.edit}
                            disabled={frozen}
                            type="button"
                            onClick={() => onEditUser(user)}
                          >
                            {EDIT}
                          </button>
                          {user.active ? (
                            <button
                              aria-label={`${DEACTIVATE} ${user.name}`}
                              className={styles.destructive}
                              disabled={frozen}
                              type="button"
                              onClick={() => press('deactivate', user)}
                            >
                              {DEACTIVATE}
                            </button>
                          ) : (
                            // The inverse in the same slot, so a row carries
                            // three controls at every state and the Actions
                            // column never changes width as rows change state.
                            // The navy outline, not the destructive fill:
                            // giving access back is not destructive, and red
                            // means one thing in this system (DESIGN.md:167).
                            <button
                              aria-label={`${ACTIVATE} ${user.name}`}
                              className={styles.activate}
                              disabled={frozen}
                              type="button"
                              onClick={() => press('activate', user)}
                            >
                              {ACTIVATE}
                            </button>
                          )}
                          <button
                            aria-label={`${DELETE} ${user.name}`}
                            className={styles.destructive}
                            disabled={frozen}
                            type="button"
                            onClick={() => press('delete', user)}
                          >
                            {DELETE}
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ))}

      {/* At most one, ever: EXPERIENCE.md:42 caps modal depth at one level, and
          this is the only place in the product that renders a dialog at all.

          **The two states are deliberately not keyed apart.** Both branches
          render a `ConfirmDialog` at the same position with no `key`, so a
          confirm the server refuses swaps the props of one instance rather
          than unmounting and remounting it — which is what keeps the opener it
          captured on open, and therefore what sends focus back to the right
          row-end control when the refusal is finally closed. The component
          re-focuses its own panel on the state change, so nothing is lost by
          staying mounted. */}
      {dialog !== null &&
        (dialog.refusal === null ? (
          <ConfirmDialog
            busy={pending === dialog.user.id}
            confirmLabel={dialog.verb === 'delete' ? DELETE : DEACTIVATE}
            kind="confirm"
            onClose={() => setDialog(null)}
            onConfirm={() => void run(dialog.verb, dialog.user)}
            {...confirmCopy(dialog.verb, dialog.user)}
          />
        ) : (
          <ConfirmDialog
            body={dialog.refusal}
            heading={refusalHeading(dialog.verb, dialog.user)}
            kind="refusal"
            onClose={() => setDialog(null)}
          />
        ))}
    </section>
  );
}
