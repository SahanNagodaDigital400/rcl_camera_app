import { useCallback, useEffect, useId, useRef, useState } from 'react';
import type { JSX } from 'react';

import { ApiRequestError, MALFORMED_RESPONSE, apiRequest } from '../api/client';
import styles from './UserListScreen.module.css';
import { isUser } from '@rocell/schema/user';
import type { Role, User } from '@rocell/schema/user';

/** Shown for a failure that arrives as something other than an `ApiRequestError`. */
const UNEXPECTED = 'The user list could not be loaded. Try again.';

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

/** What this screen is showing. Three states, and deliberately no fourth. */
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

interface UserListScreenProps {
  onBack: () => void;
  onAddUser: () => void;
}

/**
 * Users — every account, with its status and its last sign-in (FR-10).
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
 * Story 1.10 on into the session provider.
 *
 * **The role-conditional entry that opens this screen is a convenience, never the
 * control.** `App` renders it only for an Administrator and falls back to the
 * home panel if the cached role stops being `admin` — but the cached `User` is a
 * render cache and never an authorization decision (AGENTS.md Policy). The server
 * refuses a Staff caller at `GET /admin/users` regardless, through
 * `require_administrator`, which re-reads the role from Postgres on every request
 * (AD-3).
 *
 * Deliberately absent:
 *
 * - **No pagination, no search box, no sort control.** The API returns every
 *   account in one ordered array because FR-10 is every account; a filter on the
 *   one surface whose job is "who has access" hides the row somebody opened the
 *   screen to find. FR-18's search is catalogue search and belongs to Epic 2.
 * - **No edit, deactivate, delete, unlock or row-end menu.** Stories 1.10 and
 *   1.11 own every verb on a row, and DW-64's "something to press" for a lock is
 *   theirs. Rows here are display-only, and so are the role and status badges
 *   (EXPERIENCE.md line 66) — never a button, at any width.
 *
 * Copy follows EXPERIENCE.md's tone rules: short, factual, no exclamation marks.
 */
export function UserListScreen({ onBack, onAddUser }: UserListScreenProps): JSX.Element {
  const titleId = useId();
  const [listing, setListing] = useState<Listing>({ kind: 'loading' });
  /**
   * Where focus goes when the control holding it is about to be unmounted.
   *
   * "Try again" is the one control in the product that removes itself on the
   * press — the failure block it sits in is replaced by the in-flight line — and
   * a browser answers that by dropping focus to `<body>`. A keyboard or
   * screen-reader Administrator would then be back at the top of the document,
   * several tabs away from the screen they just acted on. Every other screen
   * here moves focus deliberately after a refusal (`LoginScreen`,
   * `CreateUserScreen`, `AccountSettingsScreen` all focus the field at fault);
   * this screen has no field, so the heading is the nearest thing that keeps the
   * reader where they were. `tabIndex={-1}` makes it focusable without adding a
   * tab stop.
   */
  const titleRef = useRef<HTMLHeadingElement>(null);
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
        // The distinction matters because nothing in this file arranges that —
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

  return (
    <section className={styles.screen}>
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
          <div
            className={styles.scroller}
            role="region"
            aria-labelledby={titleId}
            tabIndex={0}
          >
            <table className={styles.table}>
              <thead>
                <tr>
                  <th className={styles.heading} scope="col">
                    Name
                  </th>
                  <th className={styles.heading} scope="col">
                    Email
                  </th>
                  <th className={styles.heading} scope="col">
                    Role
                  </th>
                  <th className={styles.heading} scope="col">
                    Status
                  </th>
                  <th className={styles.heading} scope="col">
                    Last login
                  </th>
                </tr>
              </thead>
              <tbody>
                {listing.users.map((user) => {
                  const lock = lockNotice(user);
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
                      className={
                        user.active ? styles.row : `${styles.row} ${styles.deactivatedRow}`
                      }
                      key={user.id}
                    >
                      <td className={styles.cell}>{user.name}</td>
                      <td className={styles.cell}>{user.email}</td>
                      <td className={styles.cell}>
                        {/* Display-only, never a button (EXPERIENCE.md line 66).
                            Administrator is the heavier treatment on purpose —
                            it should read as the weightier role at a glance. */}
                        <span className={user.role === 'admin' ? styles.roleAdmin : styles.roleStaff}>
                          {ROLE_LABELS[user.role]}
                        </span>
                      </td>
                      <td className={styles.cell}>
                        <span className={user.active ? styles.statusActive : styles.statusOff}>
                          {user.active ? ACTIVE : DEACTIVATED}
                        </span>
                        {lock !== null && <span className={styles.lock}>{lock}</span>}
                      </td>
                      <td className={styles.cell}>{lastLogin(user)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ))}
    </section>
  );
}
