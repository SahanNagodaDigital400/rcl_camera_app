import { useCallback, useEffect, useId, useRef, useState } from 'react';
import type { FormEvent, JSX } from 'react';

import { API_PREFIX, ApiRequestError, MALFORMED_RESPONSE, apiRequest } from '../api/client';
import styles from './CatalogueScreen.module.css';
import { isTile, UNKNOWN_CATEGORY } from '@rocell/schema/tile';
import type { Tile } from '@rocell/schema/tile';

/**
 * Catalogue — search and browse the Tiles (FR-18, EXPERIENCE.md line 35).
 *
 * Rendered *inside* the shell, in place of the home panel, so it carries no
 * `<main>` of its own: `AppShell` already provides the one main landmark and
 * the focus target the gate moves focus to on a screen swap.
 *
 * **This is the surface the three tile doors moved onto.** EXPERIENCE.md line
 * 36 reaches Add Tile from "+ Add Tile" *or* a Catalogue row and Edit Tile from
 * a row alone; line 37 reaches Bulk Upload from the Catalogue. Stories 2.1, 2.2
 * and 2.4 stood all three on the home panel and said in their own stylesheets
 * what this story does with them: `+ Add Tile` takes the one accent fill here,
 * `Bulk upload` stands beside it outlined, and `Edit tile` became the row-end
 * control. The home panel keeps one outlined `Catalogue` door in their place.
 *
 * **The search is substrings of the Code, and the server owns that rule.** `q`
 * is sent as typed: no trimming, no case folding, and **no bound of its own**.
 * `clean_query` has no TypeScript twin and this screen declares no
 * `MAX_CODE_LENGTH` — unlike Add tile and Edit tile, which mirror the bound
 * because they refuse a file before uploading megabytes of it. There is
 * nothing to save here: an over-long query is a few hundred bytes, the server
 * answers `invalid_query` with a sentence naming the rule and the way through,
 * and this screen renders it. A second copy of the rule would be a second set
 * of answers about what a search is. Size and Category are **displayed** on
 * every row and are never
 * searched, filtered, faceted or grouped by: they are groupings rather than the
 * identity (AD-18), and a `size + category` filter would hide the very row
 * somebody opened this screen to find.
 *
 * **A blank search browses the whole catalogue.** The screen's own first
 * request carries no query at all, and clearing the box and pressing Search
 * goes back to the full list.
 *
 * **Two Tiles that share a Size and a Category are two rows.** Never merged,
 * never deduplicated, never collapsed into one — the varying numeric segment
 * in a Code distinguishes different tiles (AD-18), and every one of them has
 * its own reference image to verify it by.
 *
 * **Reference images are proxied, never linked** (AD-9). Each row's thumbnail
 * `src` is `GET /admin/tiles/{id}/images/{imageId}` on this same origin, so the
 * session cookie travels with it and the server re-checks the Administrator
 * role on every one. `apps/web` holds no storage URL, presigned or otherwise,
 * and the `ReferenceImage` contract has nowhere to put one.
 *
 * **The row opens the tile, and so does a control at the end of it.**
 * EXPERIENCE.md line 71 asks for row click; lines 109-113 require a keyboard
 * path and a visible focus state on every interactive element. Both hold: the
 * `<tr>` takes the click as a mouse convenience, and the labelled `Edit`
 * button — which stops the event reaching the row — is the focusable, 44px
 * path to the same action. A row that could only be reached with a mouse would
 * fail the accessibility floor on a surface EXPERIENCE.md itself calls
 * desktop-first.
 *
 * **The role-conditional door that opens this screen is a convenience, never
 * the control.** `App` renders it only for an Administrator, but the cached
 * `User` is a render cache and never an authorization decision (AGENTS.md
 * Policy): the server refuses a Staff caller at `GET /admin/tiles` through
 * `require_administrator`, which re-reads the role from Postgres on every
 * request (AD-3), and it refuses them whatever this renders.
 *
 * **The answer is paged on this screen, not by the server.** A browse of the
 * whole catalogue is a few hundred rows and as many proxied thumbnails, each
 * one a request against a route that re-reads the role — so `PAGE_SIZE` rows
 * are painted at a time and the rest wait behind `Previous` and `Next`. The
 * slicing is the only part of this that is client-side: the search is still
 * the server's rule, the array it answers with is still *every* match, and the
 * live region still counts all of them rather than the slice. Because paging
 * is presentation and not a question anybody asked, it goes back to the first
 * page every time a new answer lands — a page 7 carried across a search that
 * narrowed the list to nine rows would paint an empty table under a count that
 * said nine.
 *
 * Deliberately absent:
 *
 * - **No Size or Category filter, facet, picker or grouping.** See above. Epic
 *   3's proposed scan-side Size pre-filter is `[PROPOSED, PRD OQ-15]` and not
 *   adopted.
 * - **No server cursor, no `page` parameter, no caller-chosen page size and no
 *   result cap.** The API answers every match in one ordered array, and the
 *   catalogue is a few hundred rows; `api/users.py` already argued this once
 *   for the user list. A server-side cap would need a "showing the first N"
 *   sentence that stops being true the moment somebody narrows the search,
 *   and a page the server owned would make the count in the live region a
 *   count of the page rather than of the search.
 * - **No sort control.** The API answers in one order and it is the same order
 *   every time; a column that could be re-sorted would also have to say which
 *   sort the page boundaries were drawn against.
 * - **No removal, no bulk selection and no row-end menu.** Removal lives on
 *   Edit Tile, behind a confirmation that names the tile — a destructive verb
 *   on a dense row of a list is one mis-click from a catalogue entry nobody can
 *   restore. Two controls is two controls, not a popup with its own keyboard
 *   contract.
 * - **No low-quality flag column and no face-number column.** FR-19's flag is
 *   shown on the tile's own screen, which is where the epic asks for it, and
 *   `face_number` is a display hint that nothing may key, group or match on.
 * - **No similarity value, in any form** (AD-20). Nothing here ranks anything.
 * - **No debounce and no search-as-you-type.** The form submits; a request per
 *   keystroke is a request per keystroke against a route that reads the whole
 *   catalogue, and nothing in EXPERIENCE.md asks for it.
 *
 * Copy follows EXPERIENCE.md's tone rules: short, factual, no exclamation
 * marks.
 */

/** Shown for a failure that arrives as something other than an `ApiRequestError`. */
const UNEXPECTED = 'The catalogue could not be loaded. Try again.';

/** The in-flight line, in the one live region this screen keeps (see `announce`). */
const LOADING = 'Loading tiles…';

/**
 * How many rows are painted at once.
 *
 * **This screen's number, not the server's** — the opposite of the audit log,
 * where `AUDIT_PAGE_SIZE` lives in the shared contract because the API decides
 * how much of the log a request returns and the client has to know the size to
 * tell a short last page from the end. Nothing is negotiated here: the answer
 * is already in hand, whole, and the slicing is a layout decision about how
 * many proxied thumbnails to ask the browser for at once. Putting it in
 * `shared/schema` would publish a contract that no request carries.
 */
const PAGE_SIZE = 25;

/**
 * How many pages a result of `total` rows is, never fewer than one.
 *
 * The floor of one is what keeps `page 1 of 0` off the screen for the empty
 * result — though nothing paints the controls at that size, the clamp in the
 * body reads this on every render and a zero here would clamp the page to -1.
 */
function pageCount(total: number): number {
  return Math.max(1, Math.ceil(total / PAGE_SIZE));
}

/**
 * What the live region says once an answer lands and there is something to see.
 *
 * A **count**, because that is the outcome of a search that a screen-reader
 * user cannot otherwise get: the table's rows are there to be read one by one,
 * and "did that narrow anything" is the question the submit just asked. No
 * similarity value and nothing derived from one (AD-20) — a count of rows is
 * not a statement about how good any of them is.
 *
 * **The count is of the whole answer, and the range is said after it.** The
 * search matched what it matched; the page is how much of that is on screen.
 * Reporting the slice as the count would tell an Administrator who searched a
 * range of forty tiles that there are twenty-five. The second sentence is
 * appended only when there is more than one page — and it is also what makes a
 * page turn audible, since pressing `Next` changes nothing else in this
 * region.
 */
function listed(count: number, page: number): string {
  const total = count === 1 ? '1 tile listed.' : `${String(count)} tiles listed.`;
  const pages = pageCount(count);
  if (pages === 1) return total;
  const first = page * PAGE_SIZE + 1;
  const last = Math.min(count, first + PAGE_SIZE - 1);
  return `${total} Showing ${String(first)}–${String(last)}, page ${String(page + 1)} of ${String(pages)}.`;
}

/**
 * The empty-search sentence, verbatim from EXPERIENCE.md line 91.
 *
 * **No suggested alternatives**, because there is nothing to suggest from: the
 * match is a substring of the Code, so the only thing a suggestion could do is
 * invent a Code that does not exist.
 */
const NO_MATCH = 'No tiles match — try a different code.';

/**
 * And the register the empty *catalogue* reads in — Scan History's "No scans
 * yet." and the user list's "No users.", not a failure.
 *
 * Distinct from the sentence above on purpose: "nothing matches that" and
 * "there is nothing here yet" are different facts, and telling an
 * Administrator who has just installed the product to try a different code
 * would send them looking for a typo they did not make.
 */
const NO_TILES = 'No tiles yet.';

/** The word on the row-end control, and the visible label of the accent one. */
const EDIT = 'Edit';
const ADD = '+ Add Tile';

/** The two page controls. Words rather than arrows: an arrow glyph has no
 *  accessible name, and `‹`/`›` are announced as punctuation or not at all. */
const PREVIOUS = 'Previous';
const NEXT = 'Next';

/**
 * What this screen is showing.
 *
 * `UserListScreen`'s three states, unchanged, and still no fourth: the search
 * being in flight is the `loading` state, because a table left on screen under
 * a new search would be the *previous* answer sitting under the box that has
 * already been changed.
 */
type Listing =
  | { kind: 'loading'; query: string }
  | { kind: 'failed'; query: string; message: string }
  | { kind: 'loaded'; query: string; tiles: readonly Tile[] };

/**
 * Every state carries **the query it is about**, which is not the same string
 * as the one in the box.
 *
 * The box is live — it changes on every keystroke — and the listing is the
 * answer to a query that was submitted. Branching the empty sentence on the
 * box would say "No tiles yet." about a full catalogue the moment somebody
 * cleared a fragment that had matched nothing, and `Try again` would retry a
 * search nobody had asked for. It is also what makes the state's own sentence
 * true rather than a guess about what the reader last typed.
 */
function announce(listing: Listing, page: number): string {
  if (listing.kind === 'loading') return LOADING;
  // Nothing: the failure is spoken by its own `role="alert"`, which interrupts
  // assertively. A second live region repeating it would speak twice.
  if (listing.kind === 'failed') return '';
  if (listing.tiles.length > 0) return listed(listing.tiles.length, page);
  return listing.query.trim() === '' ? NO_TILES : NO_MATCH;
}

/**
 * Narrow the response body to an array of the shared `Tile`, or fail loudly.
 *
 * `EditTileScreen.asTile`'s sibling, per element. `isTile` rejects a missing
 * key, a malformed UUID, a non-UTC timestamp — and any extra key, which is how
 * a storage reference (AD-9) or a similarity value (AD-20) would announce
 * itself rather than being quietly ignored. A partially-understood body must
 * not be rendered as the catalogue: a row this screen could not parse is a tile
 * an Administrator would never know to look for.
 */
function asTiles(body: unknown): readonly Tile[] {
  if (Array.isArray(body)) {
    const rows: unknown[] = body;
    if (rows.every(isTile)) return rows;
  }
  throw new ApiRequestError(MALFORMED_RESPONSE, 'The server returned an unexpected response.', 200);
}

/**
 * The path for one row's thumbnail, or `null` when the tile carries no image.
 *
 * The **first** image, which is the one `_SEARCH_TILE_IMAGES` orders to the
 * front — so the picture beside a Code is the same picture every time the
 * screen is painted, and the same one Edit Tile shows first.
 *
 * `null` is not reachable through the product — the API refuses an edit that
 * would leave a tile with no reference image (FR-7) — and is handled anyway,
 * because a row that threw would take the whole catalogue down over one tile.
 */
function thumbnail(tile: Tile): string | null {
  const image = tile.reference_images[0];
  if (image === undefined) return null;
  return `${API_PREFIX}/admin/tiles/${tile.id}/images/${image.id}`;
}

/**
 * Whether a click on a row should open its tile.
 *
 * `false` while the reader has text selected, because the click that ends a
 * drag-selection lands on the row: an Administrator highlighting a Code to copy
 * it would be navigated into Edit Tile instead, losing both the selection and
 * the list. The row click is a mouse *convenience* (EXPERIENCE.md line 71) and
 * the labelled control at the row end is the real path, so declining it here
 * costs nothing.
 *
 * A collapsed selection is a plain caret and not a selection at all, which is
 * what an ordinary click leaves behind — so this is `true` for every click that
 * is a click rather than the end of a drag.
 */
function opensFromRow(): boolean {
  const selection = window.getSelection();
  return selection === null || selection.isCollapsed;
}

export function CatalogueScreen({
  onBack,
  onAddTile,
  onBulkUpload,
  onEditTile,
  onSearch,
  query: opened,
}: {
  onBack: () => void;
  onAddTile: () => void;
  onBulkUpload: () => void;
  onEditTile: (tile: Tile) => void;
  /**
   * Told the query every time one is *answered*, so it outlives this screen.
   *
   * The Catalogue is unmounted whenever a row, "+ Add Tile" or Bulk upload is
   * pressed — `App` swaps the surface rather than stacking one — so a search
   * held only here would be gone by the time `Back` brought the screen home,
   * and an Administrator working through a range of twenty tiles would retype
   * the fragment twenty times. `App` holds it for the same reason it holds the
   * row being edited.
   *
   * On the answer rather than on the submit, because a refused query is not a
   * search anybody would want returned to: see `load`.
   */
  onSearch: (query: string) => void;
  /**
   * The query this screen opens on: the one that was last submitted, or `''`.
   *
   * Read **once**, at mount, both as the initial contents of the box and as
   * what the mount request asks for. The refetch on mount is the point — a
   * tile just added, renamed or removed has to show up — and what it refetches
   * is *the search that was in place*, not the whole catalogue.
   */
  query: string;
}): JSX.Element {
  const titleId = useId();
  const searchId = useId();
  const [listing, setListing] = useState<Listing>({ kind: 'loading', query: opened });
  /** What is in the box. The request carries this verbatim. */
  const [query, setQuery] = useState(opened);
  /**
   * Which slice of the answer is painted, zero-based.
   *
   * **Not part of `Listing`**, because it is not part of the answer: the
   * listing is what the server said and this is where the reader is in it. It
   * is reset to the first page wherever a new answer is written — see `load` —
   * and clamped again in the body, so nothing can paint a page that is past
   * the end of the rows it is a page of.
   *
   * Deliberately **not** carried out to `App` the way the query is. A search
   * survives leaving the screen because retyping a fragment twenty times is
   * the cost of not keeping it; a scroll position through a list that may have
   * gained or lost the very tile that was just edited is not the same kind of
   * thing, and returning somebody to page 7 of a refetched catalogue would put
   * them somewhere they never chose.
   */
  const [page, setPage] = useState(0);
  /**
   * The re-entrancy guard for `Try again`, written synchronously.
   *
   * `UserListScreen.inFlight`'s reason, narrowed to the one control here whose
   * press can be repeated before the commit that removes it: two clicks in one
   * tick both read the state from before the first `setListing`, so the second
   * would send a second identical request against a failure that is already
   * being retried.
   *
   * **Deliberately not on the submit.** A second search is not a duplicate of
   * the first — it asks a different question — so swallowing it would leave the
   * box saying one thing and the table another, with nothing on screen to
   * explain why pressing Enter did nothing. `generation` is what makes the
   * newer one win instead.
   */
  const inFlight = useRef(false);
  /**
   * The query the mount request asks for, captured at mount.
   *
   * A ref rather than a dependency, so the effect below runs exactly once per
   * mount. `opened` changes when this screen tells `App` about a submit, and an
   * effect that watched it would answer that by fetching the same query a
   * second time.
   */
  const openedWith = useRef(opened);
  /**
   * Where focus goes when the control holding it is about to be unmounted.
   *
   * `Try again` is such a control — the failure block it sits in is replaced by
   * the in-flight line — and the heading is the nearest thing that keeps a
   * keyboard or screen-reader reader where they were, rather than dropping
   * them to `<body>` at the top of the document. `tabIndex={-1}` makes it
   * focusable without adding a tab stop.
   */
  const titleRef = useRef<HTMLHeadingElement>(null);
  /**
   * The table's scroll container, so a page turn can put its first row back in
   * view.
   *
   * `Previous` and `Next` sit *below* a screenful of rows, which means the
   * reader is at the bottom of the old page when they press one — and without
   * this they would be at the bottom of the new one, looking at row 50 of a
   * page that starts at row 26.
   */
  const scrollerRef = useRef<HTMLDivElement>(null);
  /**
   * Which fetch is allowed to write the answer.
   *
   * `UserListScreen.generation`'s counter, and this screen is where it earns
   * its keep: a second search really can be submitted while the first is open
   * — that is exactly what `submit` allows rather than swallowing — and the
   * slower of the two must not paint over the newer. Bumping it invalidates
   * everything in flight, on every submit, on `Try again`, on StrictMode's
   * second effect run and on unmount.
   */
  const generation = useRef(0);
  /**
   * `onSearch` held where `load` can reach it without becoming a dependency.
   *
   * The query is told to `App` from inside the answer below rather than from
   * `submit`, and `load` is the `useCallback` the mount effect depends on — so
   * naming `onSearch` in its closure would re-create it whenever `App`
   * re-renders and fetch the catalogue again on every one of them. A ref is
   * read at call time instead, which is what the effect's single run needs.
   *
   * Seeded at the first render and kept current from an effect, not from the
   * render body: `oxlint`'s `react/no-access-ref-during-render` forbids the
   * assignment, and the seed is what covers the gap — the mount request is
   * already in flight before any effect has re-written it, and the prop it
   * would be re-written to is the same one.
   *
   * Declared **above** the mount effect so it commits first, in the order React
   * runs them.
   */
  const keep = useRef(onSearch);

  useEffect(() => {
    keep.current = onSearch;
  }, [onSearch]);

  const load = useCallback((wanted: string) => {
    const mine = generation.current + 1;
    generation.current = mine;
    inFlight.current = true;

    // `URLSearchParams` rather than a template literal: a Code holds `.`, the
    // real catalogue holds free text after the code, and a fragment can hold a
    // `%` or a `&` — a raw interpolation would send `6LD.MA Quarry` with a bare
    // space in it and `%` as the start of an escape.
    const search = new URLSearchParams({ q: wanted });

    apiRequest(`/admin/tiles?${search.toString()}`)
      .then((body) => {
        if (generation.current === mine) {
          setListing({ kind: 'loaded', query: wanted, tiles: asTiles(body) });
          // A new answer is a new list, so it opens at its first page — for a
          // narrowed search, for `Try again`, and for the refetch that every
          // mount does. The clamp in the body covers the same ground defensively;
          // this is what makes the reset the *intent* rather than a side effect
          // of the new array being shorter.
          setPage(0);
          // **Only a search the server answered is worth keeping.** What
          // survives this screen is the search that produced what is on it, and
          // a refused one produced nothing: persisting a pasted paragraph that
          // came back `422 invalid_query` would re-issue it on the next visit,
          // so the Catalogue would reopen on an alert whose `Try again` repeats
          // the same refusal for as long as the search is held.
          keep.current(wanted);
        }
      })
      .catch((failure: unknown) => {
        // The API's own sentence, so the screen cannot state a rule the server
        // does not enforce — `administrator_required` from a demotion between
        // two requests, or `invalid_query` from a pasted paragraph, reads
        // exactly as the server worded it.
        //
        // A 401 is worded here like any other refusal and nobody inside the app
        // sees it: `apiRequest` notifies the unauthorized observer before it
        // rejects, and `SessionProvider` answers that by dropping the shell to
        // the login screen, so this screen is unmounted by the time the alert
        // would paint.
        if (generation.current === mine) {
          setListing({
            kind: 'failed',
            query: wanted,
            message: failure instanceof ApiRequestError ? failure.message : UNEXPECTED,
          });
        }
      })
      .finally(() => {
        if (generation.current === mine) inFlight.current = false;
      });
  }, []);

  useEffect(() => {
    // The search that was in place, which on a first visit is the empty string
    // — and the empty string is a request, not the absence of one:
    // EXPERIENCE.md line 35 is "search/**browse**", so a screen with nothing
    // typed browses the whole catalogue. The refetch happens on every mount,
    // so a tile added, renamed or removed one surface away is reflected the
    // moment `Back` lands here.
    load(openedWith.current);

    return () => {
      generation.current += 1;
    };
  }, [load]);

  function submit(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    // **No in-flight guard.** A submit while a request is open is a *newer
    // question*, not a duplicate of the one being asked, and dropping it on
    // the floor would leave the box and the table disagreeing with nothing on
    // screen to say why. `generation` retires the older answer instead.
    setListing({ kind: 'loading', query });
    // Told to `App` once the answer lands rather than on every keystroke, and
    // from inside `load` rather than here: what has to survive this screen
    // being unmounted is the search that produced what is on it — not a
    // half-typed fragment, and not one the server refused.
    load(query);
  }

  function retry(): void {
    // Guarded before the focus moves, not after: a retry that is going to do
    // nothing must not also pull focus off the control that was pressed.
    if (inFlight.current) return;
    // Then focus, while the button pressed is still in the document: the state
    // change below unmounts it, and the heading is where the reader is left
    // instead of on `<body>`.
    titleRef.current?.focus();
    // The state moves here rather than inside `load`, so the alert clears on
    // the click rather than a frame later. `listing.query` rather than the box:
    // `Try again` repeats the search that failed, and refetching whatever has
    // been typed since would silently answer a different question.
    setListing({ kind: 'loading', query: listing.query });
    load(listing.query);
  }

  // The whole answer, which is what the count is of. Empty in every state but
  // `loaded`, so the paging below is inert while a search is open or refused
  // and there is nothing to slice.
  const tiles = listing.kind === 'loaded' ? listing.tiles : [];
  const pages = pageCount(tiles.length);
  // Clamped on every render rather than trusted. `setPage(0)` runs where the
  // answer is written, but a render happens between a listing that has shrunk
  // and the state that acknowledges it, and one frame of `.slice()` past the
  // end is an empty table under a count that says there are rows.
  const current = Math.min(page, pages - 1);
  const visible = tiles.slice(current * PAGE_SIZE, current * PAGE_SIZE + PAGE_SIZE);

  function goTo(wanted: number): void {
    // The refusal that makes `aria-disabled` honest: the first page's
    // `Previous` and the last page's `Next` stay focusable and stay in the tab
    // order, and this is what stops the press from doing anything. Same reason
    // the audit log's `Load more` is never `disabled` — a `disabled` control is
    // dropped from the tab order and blurred, which would throw a keyboard
    // reader to `<body>` at the exact moment they reached the end of the list.
    if (wanted < 0 || wanted >= pages) return;
    setPage(wanted);
    // Back to the top of the table, because the control that was just pressed
    // is below the rows. Optional-called: `scrollIntoView` is absent in jsdom,
    // and a page turn must not throw in a test that never had a viewport.
    scrollerRef.current?.scrollIntoView?.({ block: 'start' });
  }

  return (
    <section className={styles.screen}>
      <div className={styles.header}>
        <h1 className={styles.title} id={titleId} ref={titleRef} tabIndex={-1}>
          Catalogue
        </h1>

        <div className={styles.actions}>
          {/* The screen's one accent control (DESIGN.md: exactly one per screen),
            and EXPERIENCE.md line 36's own route to Add Tile. Bulk upload and
            Back are the navy-outlined secondaries — bulk upload especially,
            since the screen it opens is the one place in the product where the
            accent is also a *status* colour. */}
          <button className={styles.add} type="button" onClick={onAddTile}>
            {ADD}
          </button>
          <button className={styles.bulk} type="button" onClick={onBulkUpload}>
            Bulk upload
          </button>
          <button className={styles.back} type="button" onClick={onBack}>
            Back
          </button>
        </div>
      </div>

      {/* A landmark of its own, so a screen-reader user can jump to the search
          rather than tabbing the table to reach it. `noValidate` for the reason
          every other form here carries it: the browser's own bubble is
          unstyled, untestable and gone on the next keystroke — and there is
          nothing to validate anyway, since a blank query is a legal search. */}
      <form className={styles.search} role="search" onSubmit={submit} noValidate>
        <label className={styles.label} htmlFor={searchId}>
          Search by code
        </label>
        {/* `type="search"`, so it is announced as a searchbox, and set in the
            monospace role DESIGN.md reserves for a value read character by
            character: a Code is transcribed from a physical tile and 0/O must
            not be confusable while it is typed. Case is preserved — the match
            folds it server-side, and folding it here would suggest the stored
            Code had been folded too. */}
        <input
          className={styles.code}
          id={searchId}
          name="q"
          type="search"
          autoComplete="off"
          autoCapitalize="none"
          autoCorrect="off"
          spellCheck={false}
          value={query}
          aria-describedby={`${searchId}-hint`}
          onChange={(event) => setQuery(event.target.value)}
        />
        {/* Part of the Code, not the whole of it — the difference between this
            box and Edit Tile's, which needs the whole Code exactly as filed.
            And it says what an empty box does, because an Administrator who has
            narrowed the list needs a way back to all of it. */}
        <p className={styles.hint} id={`${searchId}-hint`}>
          Part of a code is enough. Leave it empty to list every tile.
        </p>
        {/* Outlined, not a second accent control: "+ Add Tile" is what this
            screen is *for*, and narrowing a list is not.

            **Not disabled while a request is open.** Pressing Enter in the
            field submits the form without consulting this button at all, so a
            `disabled` here would make the two paths to one action obey
            different rules — Enter would narrow the list and the button beside
            it would do nothing, with nothing on screen to say why. A second
            search is a newer question rather than a duplicate; `submit` sends
            it and `generation` retires the older answer. */}
        <button className={styles.submit} type="submit">
          Search
        </button>
      </form>

      {/* **One live region, always in the document** — not a line that appears
          while a request is open and is unmounted the moment it answers. A
          region that comes and goes announces the *wait* and never the
          outcome: a screen-reader user who submits a search hears "Loading
          tiles…", then silence, with no count and no empty sentence, because
          the only element that would have spoken had already gone. Kept
          mounted, it speaks whatever the search that just landed came back
          with, and the empty sentence is this element rather than a second one
          — which is also what keeps it to one live region and one copy of the
          sentence.

          It carries the muted line treatment while it is a wait or a count,
          and the empty treatment when it is one of the two empty sentences;
          neither is alarming, because neither is a failure. */}
      <p
        className={
          listing.kind === 'loaded' && listing.tiles.length === 0 ? styles.empty : styles.pending
        }
        role="status"
      >
        {announce(listing, current)}
      </p>

      {listing.kind === 'failed' && (
        // One alert, and no table beside it: a catalogue missing rows is worse
        // than no catalogue, because a tile that is absent reads as a tile that
        // is not there to be found. "Try again" refetches rather than asking
        // for a page reload, which would cost the whole session bootstrap.
        <div className={styles.failure}>
          <p className={styles.error} role="alert">
            {listing.message}
          </p>
          <button className={styles.retry} type="button" onClick={retry}>
            Try again
          </button>
        </div>
      )}

      {listing.kind === 'loaded' && listing.tiles.length > 0 && (
        /* One `<table>` at every width, inside a labelled focusable scroll
             container — `UserListScreen`'s own argument: the usual phone
             treatment strips the semantics that associate every cell with its
             column header, which is a real loss on a surface EXPERIENCE.md
             calls desktop-first. The container scrolls instead of the page, and
             takes focus so the last column is reachable from the keyboard. */
        <div
          className={styles.scroller}
          role="region"
          aria-labelledby={titleId}
          ref={scrollerRef}
          tabIndex={0}
        >
          <table className={styles.table} role="table">
            <thead className={styles.head} role="rowgroup">
              <tr role="row">
                <th className={styles.heading} role="columnheader" scope="col">
                  Reference image
                </th>
                <th className={styles.heading} role="columnheader" scope="col">
                  Code
                </th>
                <th className={styles.heading} role="columnheader" scope="col">
                  Size
                </th>
                <th className={styles.heading} role="columnheader" scope="col">
                  Category
                </th>
                {/* A column of its own rather than a control tucked into the
                      last data cell: a header is what associates the button
                      with what it is for. */}
                <th className={styles.heading} role="columnheader" scope="col">
                  Actions
                </th>
              </tr>
            </thead>
            <tbody className={styles.body} role="rowgroup">
              {visible.map((tile) => {
                const source = thumbnail(tile);
                return (
                  // Keyed on the tile's id. Two tiles of one range are two
                  // rows with two ids (AD-18), so nothing here can collapse
                  // them and React cannot reuse one row's cells for the
                  // other.
                  //
                  // The click on the `<tr>` is the mouse convenience
                  // EXPERIENCE.md line 71 asks for; it is never the only way
                  // in — the labelled control at the row end is the keyboard
                  // path, and the row itself takes no focus and claims no
                  // role, so nothing announces it as a control it is not.
                  <tr
                    role="row"
                    className={styles.row}
                    key={tile.id}
                    onClick={() => {
                      if (opensFromRow()) onEditTile(tile);
                    }}
                  >
                    <td className={styles.cell} data-label="Reference image" role="cell">
                      {source === null ? (
                        <span className={styles.noImage}>No image</span>
                      ) : (
                        // Proxied through the authenticated endpoint, never a
                        // storage URL (AD-9). Same origin, so the session
                        // cookie travels with it and the role is re-checked
                        // per request. `loading="lazy"` because a browse of
                        // the whole catalogue is a few hundred pictures and
                        // only the first screenful is being looked at.
                        <img
                          alt={`Reference image of ${tile.code}`}
                          className={styles.image}
                          loading="lazy"
                          src={source}
                        />
                      )}
                    </td>
                    {/* The monospace role again: this is the value a member
                          of staff reads out and checks against a physical
                          tile. */}
                    <td
                      className={`${styles.cell} ${styles.codeCell}`}
                      data-label="Code"
                      role="cell"
                    >
                      {tile.code}
                    </td>
                    <td className={styles.cell} data-label="Size" role="cell">
                      {tile.size}
                    </td>
                    {/* Rendered as written, sentinel and all: a tile filed
                          under UNKNOWN is in the catalogue and has to read that
                          way rather than as a blank cell, which looks like a
                          value that failed to load (AD-18).

                          **And the sentinel is written here when the field is
                          `null`.** The contract types `category` as
                          `string | null` because the ERD's column is nullable,
                          and a bare `{tile.category}` renders `null` as an
                          empty cell — the exact blank the comment above says
                          must never appear. The API resolves every Category to
                          `UNKNOWN` today, which is what makes this the branch
                          nothing exercises in production and everything would
                          exercise the day a row slipped through with a NULL. */}
                    <td className={styles.cell} data-label="Category" role="cell">
                      {tile.category ?? UNKNOWN_CATEGORY}
                    </td>
                    <td className={styles.cell} data-label="Actions" role="cell">
                      <div className={styles.rowActions}>
                        {/* A real `<button>`, labelled, never a bare icon and
                              never only the `<tr>`. The accessible name carries
                              the Code, so a screen reader hears which tile the
                              control belongs to — the visible word is the verb,
                              which keeps the column narrow without making the
                              control ambiguous out of context.

                              `stopPropagation`, or the row's own handler fires
                              second and opens the same tile twice. */}
                        <button
                          aria-label={`${EDIT} ${tile.code}`}
                          className={styles.edit}
                          type="button"
                          onClick={(event) => {
                            event.stopPropagation();
                            onEditTile(tile);
                          }}
                        >
                          {EDIT}
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* The page controls, and only when there is more than one page: a
          `Previous`/`Next` pair over a catalogue of nine rows is two controls
          that can never do anything. A `<nav>` so a screen-reader user can
          jump to them past the table, named because this screen has a second
          landmark already (the search) and an unnamed one would be announced
          as "navigation" with nothing to tell them apart.

          **The position is a sentence, not a row of numbered links.** Sixteen
          page numbers is sixteen tab stops between the table and the rest of
          the screen, and a numbered page is not something anybody knows they
          want — the way to reach a particular tile here is the search box
          above, which is what this screen is for.

          No count of rows here: the live region above already says it, and
          this is the one place it could be repeated into a second, quieter
          copy that disagrees with the first. */}
      {listing.kind === 'loaded' && pages > 1 && (
        <nav className={styles.pagination} aria-label="Catalogue pages">
          <button
            aria-disabled={current === 0}
            className={styles.page}
            type="button"
            onClick={() => {
              goTo(current - 1);
            }}
          >
            {PREVIOUS}
          </button>
          {/* Not a live region of its own. It changes in the same commit as
              the sentence in `role="status"` above, which already names the
              page — two regions would say the same page twice. */}
          <p className={styles.position}>
            Page {String(current + 1)} of {String(pages)}
          </p>
          <button
            aria-disabled={current === pages - 1}
            className={styles.page}
            type="button"
            onClick={() => {
              goTo(current + 1);
            }}
          >
            {NEXT}
          </button>
        </nav>
      )}
    </section>
  );
}
