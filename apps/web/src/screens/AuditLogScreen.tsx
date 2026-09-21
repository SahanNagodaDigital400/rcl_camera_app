import { useCallback, useEffect, useId, useRef, useState } from 'react';
import type { JSX } from 'react';

import { ApiRequestError, MALFORMED_RESPONSE, apiRequest } from '../api/client';
import styles from './AuditLogScreen.module.css';
import {
  AUDIT_CURSOR_PARAM,
  AUDIT_PAGE_SIZE,
  isAuditAction,
  isAuditLogEntry,
} from '@rocell/schema/audit';
import type { AuditAction, AuditLogEntry } from '@rocell/schema/audit';

/**
 * The collection this screen reads.
 *
 * The one query parameter it ever sends is `AUDIT_CURSOR_PARAM`, which is not
 * spelled here: it is half of a wire contract and lives in the shared one, so
 * a rename on the server that this file does not follow fails a test rather
 * than silently re-fetching the first page on every Load more.
 */
const AUDIT_PATH = '/admin/audit';

/** Shown for a failure that arrives as something other than an `ApiRequestError`. */
const UNEXPECTED = 'The audit log could not be loaded. Try again.';

/** The in-flight lines. `role="status"`, so the wait is announced rather than silent. */
const LOADING = 'Loading the audit log…';
const LOADING_MORE = 'Loading more entries…';

/**
 * Unreachable in the product — the reader's own sign-in is an entry, so by the
 * time this screen can be opened there is at least one row. Rendered anyway,
 * because a bare header row with nothing under it looks like a screen that
 * failed rather than a screen with nothing to say.
 */
const NO_ENTRIES = 'No entries.';

/** The visible word on each control. There is no primary action on this screen. */
const BACK = 'Back';
const TRY_AGAIN = 'Try again';
const LOAD_MORE = 'Load more';

/** The six columns, in order. */
const COLUMNS = ['When', 'Who', 'What', 'Target', 'Source IP', 'Details'] as const;

/**
 * What a null cell reads.
 *
 * **Never a blank cell, and never a substitute principal.** An entry whose
 * actor is null is an unknown-account sign-in attempt: nobody is known, and
 * rendering the target there — or the word "System" — would be the screen
 * asserting something the log was never told. A blank cell is worse again,
 * because it reads as a value that failed to load.
 */
const NO_ACTOR = 'No actor';
const NO_TARGET = 'No target';
const UNKNOWN_ADDRESS = 'Not recorded';

/** And what an entry with an empty `details` object reads. */
const NO_DETAILS = 'None';

/**
 * The stored action in the reader's own words.
 *
 * `Record<AuditAction, string>` rather than a lookup with a default, so the
 * compiler refuses the map when the shared union gains a member — a new action
 * from Epic 2 or 3 is then a build failure here rather than a row that renders
 * under its raw column value forever.
 *
 * The phrases are EXPERIENCE.md's register: short, factual, no exclamation
 * marks, and they name what happened rather than editorialising about it.
 */
const ACTION_LABELS: Record<AuditAction, string> = {
  login_succeeded: 'Signed in',
  login_failed: 'Sign-in failed',
  login_refused_locked: 'Sign-in refused, account locked',
  logged_out: 'Signed out',
  password_claimed: 'Temporary credential claimed',
  password_changed: 'Password changed',
  password_change_refused: 'Password change refused',
  sessions_revoked: 'Sessions revoked',
  user_provisioned: 'User provisioned',
  user_edited: 'User edited',
  user_deactivated: 'User deactivated',
  user_activated: 'User activated',
  user_deleted: 'User deleted',
  // Epic 2's entries. "Tile", never "Product" — AD-18 retires that word, and a
  // label is one of the places it would come back.
  //
  // **Symmetric, deliberately.** Both name the same object in the same log and
  // sit in the same column of the same table, so the pair has to read as a pair
  // — "Tile added to catalogue" beside "Tile edited" made one look like a
  // different kind of event from the other. The account entries above are the
  // same shape for the same reason: subject, then verb.
  catalogue_tile_added: 'Tile added',
  catalogue_tile_edited: 'Tile edited',
};

/**
 * The label for one entry's action, falling back to the stored value.
 *
 * **The fallback is the point, not a lenience.** `action` is `string` on the
 * wire because the column has no CHECK, the vocabulary grows every epic, and
 * AD-4's way of correcting a wrong entry is to insert one by hand. A screen
 * that refused to render an entry it did not recognise would make the one
 * table that can never be rewritten have a viewer that hides parts of it. The
 * raw value is readable even when it is not recognised.
 *
 * **Narrowed with `isAuditAction`, never indexed-then-defaulted.** A bare
 * `ACTION_LABELS[action as AuditAction] ?? action` reads through
 * `Object.prototype` for a stored action of `toString`, `constructor`,
 * `valueOf` or `__proto__`: the lookup yields a *function*, which is not
 * nullish, so the fallback never fires and a function reaches React as a
 * child. `action` is a free-text column with no CHECK and corrective entries
 * are inserted by hand as the owner (AD-4), so a value shaped like a prototype
 * key is a thing the log can really hold — and the surface that must render
 * every entry is exactly the wrong place to throw on one. The narrower checks
 * membership of `AUDIT_ACTIONS` instead of reaching into the object at all.
 */
function actionLabel(action: string): string {
  return isAuditAction(action) ? ACTION_LABELS[action] : action;
}

/**
 * Narrow the response body to an array of the shared `AuditLogEntry`, or fail
 * loudly.
 *
 * `UserListScreen.asUsers`'s sibling. `isAuditLogEntry` rejects a missing key,
 * a malformed UUID, a non-UTC timestamp — and any extra key, which is how a
 * column that stopped matching the contract would announce itself. A
 * partially-understood body must not be rendered as an authoritative record:
 * an entry this screen could not parse is an event an Administrator would
 * never know to look for.
 */
function asEntries(body: unknown): readonly AuditLogEntry[] {
  if (Array.isArray(body)) {
    const rows: unknown[] = body;
    if (rows.every(isAuditLogEntry)) return rows;
  }
  throw new ApiRequestError(MALFORMED_RESPONSE, 'The server returned an unexpected response.', 200);
}

/**
 * The instant in the reader's own locale.
 *
 * No second parse guard: `asEntries` has already run every element through
 * `isAuditLogEntry`, whose `isUtcTimestamp` accepts a value only if it matches
 * the ISO 8601 UTC shape *and* `Number.isFinite(Date.parse(value))`. A guard
 * here would be dead code reading as though an unparseable timestamp were a
 * case this screen expects — and the honest way to widen what can arrive is to
 * widen the contract, not to re-validate behind it.
 *
 * **Seconds and the zone are both explicit, and both are load-bearing.** A
 * bare `toLocaleString()` prints neither in most locales. Without seconds, the
 * two entries one request writes — a deactivation and the revocation beside it
 * — render as the same instant, which is the very collision the statement's
 * `id DESC` tiebreaker exists to order; the column would then contradict the
 * order the rows are in. Without the zone, "was this password changed on
 * Tuesday?" is answered in whatever zone the reading browser happens to be
 * set to, with nothing on screen saying which — and this product's staff and
 * its servers are not guaranteed to agree.
 *
 * The reader's own locale still decides the *format*: the options ask for a
 * medium date and a long time, not for a written-out pattern.
 *
 * Not monospaced, despite being a column of aligned values: DESIGN.md:186
 * scopes the `code` type role to product Codes and flags it as an unconfirmed
 * assumption, and stretching an unconfirmed role onto timestamps is a design
 * decision this screen has no mandate to make.
 */
const WHEN_FORMAT: Intl.DateTimeFormatOptions = { dateStyle: 'medium', timeStyle: 'long' };

/**
 * One formatter for the whole column, not one per cell.
 *
 * `toLocaleString(undefined, options)` builds an `Intl.DateTimeFormat` on
 * every call, and building it is the expensive half — the formatting itself is
 * cheap. This column renders one cell per entry and the table only grows:
 * every Load more re-renders every row already on screen, so a per-cell
 * construction is quadratic in presses for no gain. The locale is the
 * runtime's default, read once here rather than re-resolved per row, which is
 * the same answer it would give every time: nothing in this product changes
 * the browser's locale while it is open.
 */
const WHEN_FORMATTER = new Intl.DateTimeFormat(undefined, WHEN_FORMAT);

function when(entry: AuditLogEntry): string {
  return WHEN_FORMATTER.format(new Date(entry.created_at));
}

/** One `details` value as text. Strings as themselves, everything else as JSON. */
function detailValue(value: unknown): string {
  if (typeof value === 'string') return value;
  // `JSON.stringify` returns `undefined` for `undefined` itself, which cannot
  // arrive from a JSON body but is what the type says; `String` is the honest
  // fallback rather than an empty cell.
  return JSON.stringify(value) ?? String(value);
}

/**
 * The whole `details` object as one deterministic line.
 *
 * **Sorted by key**, so two entries carrying the same facts read the same way
 * — object key order in JSON is insertion order, which is whichever order the
 * writing call site happened to build the dict in, and a record whose rows
 * reorder themselves between actions is harder to scan than one that does not.
 *
 * Rendered generically rather than per action: the payload's shape differs by
 * action and grows with every epic, and a per-action renderer would be a
 * second vocabulary to keep in step with `AuditAction` — with an unrecognised
 * action falling through to a blank cell, which is the one thing this surface
 * may not do.
 */
function detailsText(entry: AuditLogEntry): string {
  // `Array#toSorted` is the rule's own suggestion and is an ES2023 method the
  // project's `lib` does not declare (`tsconfig.json` targets ES2022), so it
  // does not typecheck here. The mutation the rule guards against cannot
  // happen either way: `Object.keys` returns a fresh array that nothing else
  // holds a reference to.
  // oxlint-disable-next-line unicorn/no-array-sort
  const keys = Object.keys(entry.details).sort();
  if (keys.length === 0) return NO_DETAILS;
  return keys.map((key) => `${key}: ${detailValue(entry.details[key])}`).join(', ');
}

/**
 * What this screen is showing.
 *
 * Three states. A page being appended is **not** a fourth: the table stays on
 * screen and stays readable throughout, so the append is held beside this as a
 * flag and a message rather than folded in here.
 *
 * `exhausted` is the end of the log, and it is decided by counting the page
 * just received against `AUDIT_PAGE_SIZE` — the size the shared contract
 * publishes, not the length of the first page. Inferring it would read a log
 * of five entries as a full page of five, so every short log would offer a
 * Load more that fetches nothing; counting against the published number makes
 * a short *first* page the end of the log, with no press at all.
 */
type Listing =
  | { kind: 'loading' }
  | { kind: 'failed'; message: string }
  | { kind: 'loaded'; entries: readonly AuditLogEntry[]; exhausted: boolean };

interface AuditLogScreenProps {
  onBack: () => void;
}

/**
 * Audit log — the chronological record of who did what, when, and from where
 * (FR-21).
 *
 * EXPERIENCE.md line 38's own nav entry, standing on the home panel until
 * there is a nav to hold it. Rendered *inside* the shell, in place of the home
 * panel, exactly as Users is: it carries no `<main>` of its own, because
 * `AppShell` already provides the one main landmark the gate moves focus to on
 * a screen swap.
 *
 * **The one table in the product with zero row-end actions, at any role**
 * (EXPERIENCE.md:75, UX-DR8). There is no edit control, no delete control, no
 * row-end menu, no checkbox and no row click — not hidden for Staff, not
 * disabled, simply not built. The rule is not a UI preference: `rocell_app`
 * holds `SELECT, INSERT` on the table and nothing else, so no route exists for
 * such a control to call and none can be added without a migration AD-4
 * forbids.
 *
 * **It calls `apiRequest` directly rather than going through
 * `SessionProvider`**, for `UserListScreen`'s reason: that context is the
 * caller's own session, and reading the log changes nothing about it.
 *
 * **The role-conditional entry that opens this screen is a convenience, never
 * the control.** `App` renders it only for an Administrator and falls back to
 * the home panel if the cached role stops being `admin` — but the cached
 * `User` is a render cache and never an authorization decision (AGENTS.md
 * Policy). The server refuses a Staff caller at `GET /admin/audit` regardless,
 * through `require_administrator`, which re-reads the role from Postgres on
 * every request (AD-3).
 *
 * Deliberately absent:
 *
 * - **No Flagged filter.** EXPERIENCE.md:38 and :76 put one on this surface,
 *   and it renders FR-22's anomaly flagging — which is not in Epic 1, has no
 *   column behind it and no data to filter. A control over a field that does
 *   not exist is a dead control, so it is recorded as deferred instead.
 * - **No search, no date range, no source-IP filter, no sort control and no
 *   column filters.** None is in FR-21, and the order is the statement's
 *   (`ORDER BY created_at DESC, id DESC`); a second opinion here is how the
 *   two halves start disagreeing about what row three is.
 * - **No client-chosen page size.** The server picks it. A caller-supplied
 *   limit is a denial-of-service knob on the one table nobody may prune.
 * - **No export.** Nothing in Epic 1 asks for one, and a CSV of the whole
 *   record is a copy of the log outside every protection the log has.
 *
 * Copy follows EXPERIENCE.md's tone rules: short, factual, no exclamation
 * marks.
 */
export function AuditLogScreen({ onBack }: AuditLogScreenProps): JSX.Element {
  const titleId = useId();
  const [listing, setListing] = useState<Listing>({ kind: 'loading' });
  /** Whether a Load more request is open. Also the re-entrancy guard's mirror. */
  const [appending, setAppending] = useState(false);
  /**
   * The same fact as `appending`, a commit earlier.
   *
   * `appending` is what the render reads; two presses in one tick are batched
   * and both read the value from before the first `setAppending`, so the guard
   * that actually holds is a ref written synchronously.
   */
  const inFlight = useRef(false);
  /** A failed append, as the API worded it. The rendered rows stay on screen. */
  const [appendFailure, setAppendFailure] = useState<string | null>(null);
  /**
   * Where focus goes when the control holding it is about to be unmounted.
   *
   * Two controls do that here: "Try again", whose failure block is replaced by
   * the in-flight line, and "Load more", which removes itself the moment the
   * page it fetched turns out to be the last one. A browser answers an
   * unmounted active element by dropping focus to `<body>`, which would leave
   * a keyboard or screen-reader Administrator at the top of the document. Try
   * again is rescued to the heading (there is nothing else left where it was);
   * Load more is rescued to the scroll region, which is where the rows it just
   * appended are.
   */
  const titleRef = useRef<HTMLHeadingElement>(null);
  const regionRef = useRef<HTMLDivElement>(null);
  const moreRef = useRef<HTMLButtonElement>(null);
  /** Whether the region is owed focus, until the effect below gives it. */
  const rescueFocus = useRef(false);
  /**
   * Which fetch is allowed to write the answer.
   *
   * `UserListScreen`'s generation counter, and needed for the same two
   * reasons: "Try again" can start a second read while the first is open, and
   * StrictMode runs the mount effect twice. Bumping it invalidates everything
   * in flight — including an append, which must not land on a listing that has
   * since been replaced by a fresh first page.
   */
  const generation = useRef(0);

  const load = useCallback(() => {
    const mine = generation.current + 1;
    generation.current = mine;

    apiRequest(AUDIT_PATH)
      .then((body) => {
        if (generation.current !== mine) return;
        const entries = asEntries(body);
        setAppendFailure(null);
        setListing({
          kind: 'loaded',
          entries,
          // The same rule as an appended page, applied to the first one: a
          // first page shorter than `AUDIT_PAGE_SIZE` — which includes an
          // empty one — is the whole log, and offers nothing to load more of.
          exhausted: entries.length < AUDIT_PAGE_SIZE,
        });
      })
      .catch((failure: unknown) => {
        // The API's own sentence, so the screen cannot state a rule the server
        // does not enforce — `administrator_required` from a demotion between
        // two requests reads exactly as the server worded it.
        //
        // A 401 is worded here like any other refusal. *Inside the app* nobody
        // sees it: `apiRequest` notifies the unauthorized observer before it
        // rejects, and `SessionProvider` answers by dropping the shell to the
        // login screen, so this screen is unmounted by the time the alert
        // would paint. Nothing in this file arranges that, which is why it is
        // worded rather than special-cased.
        if (generation.current !== mine) return;
        setAppendFailure(null);
        setListing({
          kind: 'failed',
          message: failure instanceof ApiRequestError ? failure.message : UNEXPECTED,
        });
      });
  }, []);

  useEffect(() => {
    load();

    return () => {
      generation.current += 1;
    };
  }, [load]);

  useEffect(() => {
    // After the commit, so the region is focused once the Load more control
    // that was pressed has gone. A ref rather than a dependency on state: the
    // request is "move focus once", which is an event.
    if (!rescueFocus.current) return;
    rescueFocus.current = false;
    regionRef.current?.focus();
  });

  function retry(): void {
    // Focus first, while the button pressed is still in the document: the
    // state change below unmounts it, and the heading is where the reader is
    // left instead of on `<body>`.
    titleRef.current?.focus();
    // The state moves to `loading` here rather than inside `load`, so the
    // alert clears on the click rather than a frame later — and so nothing
    // adjusts state synchronously from inside the effect above, which is what
    // `oxlint`'s `react/set-state-in-effect` rule exists to stop.
    setListing({ kind: 'loading' });
    load();
  }

  function loadMore(): void {
    // The guard that actually holds. See `inFlight`.
    if (inFlight.current) return;
    if (listing.kind !== 'loaded' || listing.exhausted) return;
    const oldest = listing.entries[listing.entries.length - 1];
    if (oldest === undefined) return;

    inFlight.current = true;
    setAppending(true);
    setAppendFailure(null);

    // **Not a new generation.** An append belongs to the listing it extends,
    // so it is invalidated by a refetch or an unmount rather than starting a
    // fresh one — the counter is read, never bumped.
    const mine = generation.current;

    // The cursor goes into the path: `RequestOptions` carries no query helper.
    // `isUuid` has already refused anything that is not a canonical UUID, so
    // `encodeURIComponent` has nothing left to do today — it is here so the
    // safety is local to this line rather than conditional on a narrower two
    // files away staying exactly as strict as it is now.
    apiRequest(`${AUDIT_PATH}?${AUDIT_CURSOR_PARAM}=${encodeURIComponent(oldest.id)}`)
      .then((body) => {
        if (generation.current !== mine) return;
        const page = asEntries(body);
        // A short page is the last one. A page that is exactly
        // `AUDIT_PAGE_SIZE` long leaves the control up, which costs one press
        // answering `[]` when the log's length is an exact multiple of it —
        // the one case the published size cannot settle in advance, and a
        // press rather than a defect.
        const exhausted = page.length < AUDIT_PAGE_SIZE;
        // Rescued only when the control is about to disappear, which is the
        // only case where focus would fall to `<body>` — and only when the
        // reader has not already moved somewhere else in the meantime. The
        // control stays focusable throughout the request (see `aria-disabled`
        // below), so a keyboard Administrator can tab from it to Back while a
        // page is in flight; moving them off Back when that page lands would
        // be this screen taking focus away rather than saving it. Focus on
        // `<body>` counts as owed: that is where a pointer press in a browser
        // that does not focus buttons leaves it, and it is the state the
        // rescue exists for.
        const active = document.activeElement;
        const owed = active === null || active === document.body || active === moreRef.current;
        if (exhausted && owed) rescueFocus.current = true;
        setListing((current) =>
          current.kind === 'loaded'
            ? { kind: 'loaded', entries: [...current.entries, ...page], exhausted }
            : current,
        );
      })
      .catch((failure: unknown) => {
        if (generation.current !== mine) return;
        // The rows already on screen stay: a record is not made better by
        // being hidden because its next page failed. The control stays too, so
        // the alert needs no "Try again" of its own — pressing Load more again
        // is the retry.
        setAppendFailure(failure instanceof ApiRequestError ? failure.message : UNEXPECTED);
      })
      .finally(() => {
        // **Both cleared unconditionally.** Guarding the flag on
        // `generation.current === mine` — as the two handlers above are
        // guarded, because they write an *answer* that a newer read has
        // superseded — would leave the wait line up and the control inert
        // forever if a listing were ever invalidated while an append was open.
        // This is not reachable today, because the only thing that bumps the
        // counter mid-append is `retry`, which exists solely in the failed
        // state where there is no control to press. "Unreachable because of
        // where a button happens to be rendered" is not a property worth
        // depending on, and clearing a flag nobody is waiting on costs
        // nothing.
        inFlight.current = false;
        setAppending(false);
      });
  }

  return (
    <section className={styles.screen}>
      <h1 className={styles.title} id={titleId} ref={titleRef} tabIndex={-1}>
        Audit log
      </h1>

      <div className={styles.actions}>
        {/* Back is the only control up here, and it is the navy outline. This
            screen has no primary action: it is a record, and painting a
            control accent-orange would make "fetch more rows" the most
            important thing on an Administrator's security surface. */}
        <button className={styles.back} type="button" onClick={onBack}>
          {BACK}
        </button>
      </div>

      {listing.kind === 'loading' && (
        <p className={styles.pending} role="status">
          {LOADING}
        </p>
      )}

      {listing.kind === 'failed' && (
        // One alert, and no table beside it: a record that is missing rows is
        // worse than no record at all, because the entry somebody opened the
        // screen to find is exactly the one that would be gone.
        <div className={styles.failure}>
          <p className={styles.error} role="alert">
            {listing.message}
          </p>
          <button className={styles.retry} type="button" onClick={retry}>
            {TRY_AGAIN}
          </button>
        </div>
      )}

      {listing.kind === 'loaded' &&
        (listing.entries.length === 0 ? (
          <p className={styles.empty}>{NO_ENTRIES}</p>
        ) : (
          /* One `<table>` at every width, inside a labelled focusable scroll
             container — `UserListScreen`'s treatment and its argument: the
             usual phone reflow strips the semantics that associate every cell
             with its column header, which is a real loss on a surface
             EXPERIENCE.md itself calls desktop-first. This keeps the header
             association and keeps the *page* from scrolling sideways at 375px;
             the container scrolls instead, and takes focus so the last column
             is reachable from the keyboard. */
          <div
            className={styles.scroller}
            ref={regionRef}
            role="region"
            aria-labelledby={titleId}
            tabIndex={0}
          >
            <table className={styles.table}>
              <thead>
                <tr>
                  {COLUMNS.map((column) => (
                    <th className={styles.heading} key={column} scope="col">
                      {column}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {/* Rendered in the order the array arrived in. The statement
                    states the order (`ORDER BY created_at DESC, id DESC`); a
                    sort here would be a second opinion about it, and the two
                    would disagree the first time two entries shared a
                    `created_at`. */}
                {listing.entries.map((entry) => (
                  <tr className={styles.row} key={entry.id}>
                    <td className={styles.cell}>{when(entry)}</td>
                    <td className={styles.cell}>{entry.actor_email ?? NO_ACTOR}</td>
                    <td className={styles.cell}>{actionLabel(entry.action)}</td>
                    <td className={styles.cell}>{entry.target_email ?? NO_TARGET}</td>
                    <td className={styles.cell}>{entry.source_ip ?? UNKNOWN_ADDRESS}</td>
                    {/* The one cell allowed to wrap: a `details` payload is a
                        sentence's worth of facts, and forcing it onto one line
                        would make the table scroll sideways for every row. */}
                    <td className={styles.details}>{detailsText(entry)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ))}

      {appendFailure !== null && (
        <p className={styles.error} role="alert">
          {appendFailure}
        </p>
      )}

      {appending && (
        <p className={styles.pending} role="status">
          {LOADING_MORE}
        </p>
      )}

      {/* EXPERIENCE.md:103 bans infinite scroll; an explicit control is what
          it leaves. It disappears once a page comes back shorter than
          `AUDIT_PAGE_SIZE` — the oldest entry has been reached — rather than
          sitting there inert, because a control that can never do anything
          again is not a control.

          **`aria-disabled` while a page is in flight, never `disabled`.** A
          `disabled` button is removed from the tab order, and the browser
          answers that by blurring it — so a keyboard Administrator who pressed
          Load more would be dropped to `<body>` for the length of every
          request and have to tab back in from the top of the document, on
          every page but the last. EXPERIENCE.md:110 asks for a keyboard path
          on these surfaces, and that is not one. `aria-disabled` announces the
          same state, keeps the control focusable, and leaves the press itself
          refused by `inFlight` in `loadMore` — which was always the guard that
          actually held (see `inFlight`; the attribute never was one, because
          two presses in one task both run before React commits). The one press
          that *does* move focus is the one that removes the control, and
          `rescueFocus` sends that reader to the rows it just appended. */}
      {listing.kind === 'loaded' && !listing.exhausted && (
        <button
          ref={moreRef}
          aria-disabled={appending}
          className={styles.more}
          type="button"
          onClick={loadMore}
        >
          {LOAD_MORE}
        </button>
      )}
    </section>
  );
}
