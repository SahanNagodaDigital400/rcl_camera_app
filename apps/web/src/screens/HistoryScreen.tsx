import { useCallback, useEffect, useId, useRef, useState } from 'react';
import type { JSX } from 'react';

import { API_PREFIX, ApiRequestError, MALFORMED_RESPONSE, apiRequest } from '../api/client';
import { ImageViewer } from '../components/ImageViewer';
import styles from './HistoryScreen.module.css';
import {
  HISTORY_CURSOR_PARAM,
  HISTORY_PAGE_SIZE,
  isScanHistoryCount,
  isScanHistoryEntry,
} from '@rocell/schema/scan';
import { UNKNOWN_CATEGORY } from '@rocell/schema/tile';
import type { ScanCandidate, ScanHistoryEntry } from '@rocell/schema/scan';

/**
 * History — a caller's own past Scans (Story 3.5, FR-8).
 *
 * `GET /scans` is `POST /scans`' own read: `submit_scan` (Story 3.4) already
 * persists a `scan` row for every successful submission, and this screen is
 * the surface that makes those rows visible again. `AuditLogScreen`'s own
 * state machine — a `Listing` union, a generation counter, an `inFlight`
 * ref, Load more — reused here because the shape of "fetch a page, append
 * the next on request, tell a short page from a full one" is identical; only
 * what a row *is* differs.
 *
 * **Reachable by every authenticated role, unlike the admin surfaces beside
 * it on the home panel.** `GET /scans` is gated by `require_claimed_user`,
 * never `require_administrator` — a Staff caller's own scan history is
 * theirs to read exactly as an Administrator's is (EXPERIENCE.md:31).
 *
 * **Each entry's Candidates are `ResultsScreen`'s own card markup**,
 * restated here rather than imported — this file and `ResultsScreen.tsx`
 * share no component, so the card/pill/meta classes this screen's own
 * stylesheet declares are copies of that screen's rules, restated the way
 * every sibling stylesheet in this product restates shared tokens rather
 * than reaching into another screen's CSS module. Tapping a card opens the
 * same `ImageViewer` full-screen — the verification moment applies here
 * exactly as it does on Results, since a history entry's whole point is
 * confirming a past match.
 *
 * **A candidate's image can 404.** A Tile matched by a past scan may since
 * have been removed (`DELETE /admin/tiles/{tile_id}`) — the Code, Size and
 * Category still render from the stored snapshot (AD-10), because they are
 * not a foreign key to anything, but the proxied image request is not
 * special-cased here: no image-consuming screen in this codebase catches
 * that 404 (`ResultsScreen`, `CatalogueScreen`), and this one does not
 * either.
 *
 * **The page count is a second request, not a field.** `GET /scans` answers
 * with a bare array, so a full page tells this screen "at least
 * `HISTORY_PAGE_SIZE`" and nothing more — it can say how many rows it has rendered but not what it is
 * rendering them out of. `GET /scans/count` is that denominator, fetched
 * beside the first page and allowed to fail on its own: a total that does not
 * arrive costs the subtitle its "of N", never the history.
 *
 * **No row-end actions.** `rocell_app` holds full DML on `scan` (see the
 * migration's own Design Notes), but nothing in this story asks for an edit
 * or a delete control, and none is built — `AuditLogScreen`'s own precedent
 * for a record screen with nothing to click but a card.
 */

const HISTORY_PATH = '/scans';

/**
 * The denominator behind "Showing 10 of 213 scans".
 *
 * A second request rather than a field on the page above it: `GET /scans`
 * answers with a bare array (`read_scan_history`'s own docstring), so a total
 * could only travel there inside an envelope wrapping every page of history.
 * The two are fetched together and land independently — see `load`.
 */
const COUNT_PATH = '/scans/count';

/** Shown for a failure that arrives as something other than an `ApiRequestError`. */
const UNEXPECTED = 'Your scan history could not be loaded. Try again.';

const LOADING = 'Loading your scan history…';
const LOADING_MORE = 'Loading more scans…';

/** EXPERIENCE.md:86's verbatim empty-history sentence. */
const NO_SCANS = 'No scans yet.';

/** One scan's own empty result — `ResultsScreen.NO_MATCH`'s past-tense twin. */
const NO_MATCH = 'No confident match.';

const BACK = 'Back';
const TRY_AGAIN = 'Try again';
const LOAD_MORE = 'Load more';
const BEST_MATCH = 'Best match';

/**
 * The subtitle under the rendered pages: how many scans are on screen, out of
 * how many the caller has.
 *
 * `total` is `null` when `GET /scans/count` did not answer — the sentence
 * then drops the denominator rather than the whole line, because "Showing 10
 * scans" is still true and still tells a reader that what they are looking at
 * is a page and not the lot.
 */
function showing(shown: number, total: number | null): string {
  // Clamped, never trusted over the rows themselves: the count and the first
  // page are two requests, so a scan submitted between them (or in another
  // tab) leaves a total the rendered rows have already passed. "Showing 53 of
  // 53" is a stale denominator; "Showing 53 of 50" is a bug on screen.
  const denominator = total === null ? null : Math.max(total, shown);
  if (denominator === null) return `Showing ${shown} ${shown === 1 ? 'scan' : 'scans'}`;
  return `Showing ${shown} of ${denominator} ${denominator === 1 ? 'scan' : 'scans'}`;
}

function imageSrc(candidate: ScanCandidate): string {
  return `${API_PREFIX}/tiles/${candidate.tile_id}/images/${candidate.image_id}`;
}

function imageAlt(candidate: ScanCandidate): string {
  return `Reference image of ${candidate.code}`;
}

/**
 * Narrow the response body to an array of the shared `ScanHistoryEntry`, or
 * fail loudly. `AuditLogScreen.asEntries`'s own shape.
 */
function asHistoryEntries(body: unknown): readonly ScanHistoryEntry[] {
  if (Array.isArray(body)) {
    const rows: unknown[] = body;
    if (rows.every(isScanHistoryEntry)) return rows;
  }
  throw new ApiRequestError(MALFORMED_RESPONSE, 'The server returned an unexpected response.', 200);
}

/**
 * Narrow the response body to the caller's own scan total, or fail loudly.
 *
 * Thrown from rather than returning `null` on a malformed body, for
 * `asHistoryEntries`' reason — but the one caller catches it and renders the
 * sentence without a denominator, because a count nobody can parse must not
 * cost the reader the history it is only a subtitle for.
 */
function asHistoryCount(body: unknown): number {
  if (isScanHistoryCount(body)) return body.count;
  throw new ApiRequestError(MALFORMED_RESPONSE, 'The server returned an unexpected response.', 200);
}

/**
 * The instant in the reader's own locale — `AuditLogScreen.WHEN_FORMATTER`'s
 * exact options, restated: seconds and the zone are both load-bearing for
 * the same reason they are there, and one formatter for the whole screen
 * rather than one per entry.
 */
const WHEN_FORMAT: Intl.DateTimeFormatOptions = { dateStyle: 'medium', timeStyle: 'long' };
const WHEN_FORMATTER = new Intl.DateTimeFormat(undefined, WHEN_FORMAT);

function when(entry: ScanHistoryEntry): string {
  return WHEN_FORMATTER.format(new Date(entry.created_at));
}

/**
 * What this screen is showing. `AuditLogScreen.Listing`'s own shape: three
 * states, with an appended page held beside it as a flag and a message
 * rather than folded in as a fourth.
 */
type Listing =
  | { kind: 'loading' }
  | { kind: 'failed'; message: string }
  | { kind: 'loaded'; entries: readonly ScanHistoryEntry[]; exhausted: boolean };

interface HistoryScreenProps {
  onBack: () => void;
}

export function HistoryScreen({ onBack }: HistoryScreenProps): JSX.Element {
  const titleId = useId();
  const [listing, setListing] = useState<Listing>({ kind: 'loading' });
  const [appending, setAppending] = useState(false);
  /** The re-entrancy guard `appending` cannot be — see `AuditLogScreen.inFlight`. */
  const inFlight = useRef(false);
  const [appendFailure, setAppendFailure] = useState<string | null>(null);
  /** The Candidate whose reference image is open full-screen, or `null`. */
  const [viewing, setViewing] = useState<ScanCandidate | null>(null);
  /**
   * Every scan the caller has, or `null` while it is in flight or after it
   * failed. Read once per first page and never re-read by Load more: paging
   * does not change how many scans exist, and a second request per page would
   * buy nothing but a chance for the denominator to shift under the reader.
   */
  const [total, setTotal] = useState<number | null>(null);

  const titleRef = useRef<HTMLHeadingElement>(null);
  const entriesRef = useRef<HTMLDivElement>(null);
  const moreRef = useRef<HTMLButtonElement>(null);
  /** Whether the entries region is owed focus, until the effect below gives it. */
  const rescueFocus = useRef(false);
  /** `AuditLogScreen.generation`'s own guard against a stale answer. */
  const generation = useRef(0);

  const load = useCallback(() => {
    const mine = generation.current + 1;
    generation.current = mine;

    apiRequest(HISTORY_PATH)
      .then((body) => {
        if (generation.current !== mine) return;
        const entries = asHistoryEntries(body);
        setAppendFailure(null);
        setListing({
          kind: 'loaded',
          entries,
          exhausted: entries.length < HISTORY_PAGE_SIZE,
        });
      })
      .catch((failure: unknown) => {
        if (generation.current !== mine) return;
        setAppendFailure(null);
        setListing({
          kind: 'failed',
          message: failure instanceof ApiRequestError ? failure.message : UNEXPECTED,
        });
      });

    // Alongside the page, and started after it: the rows are the screen and
    // the total is a subtitle on them, so the two race deliberately and
    // whichever lands first renders. A failure here is swallowed — `showing`
    // drops the denominator and the history itself is untouched. The `401`
    // case is not swallowed with it: `apiRequest` tells the session observer
    // from inside `fetch`, before this handler ever runs.
    apiRequest(COUNT_PATH)
      .then((body) => {
        if (generation.current !== mine) return;
        setTotal(asHistoryCount(body));
      })
      .catch(() => {
        if (generation.current !== mine) return;
        setTotal(null);
      });
  }, []);

  useEffect(() => {
    load();

    return () => {
      generation.current += 1;
    };
  }, [load]);

  useEffect(() => {
    if (!rescueFocus.current) return;
    rescueFocus.current = false;
    entriesRef.current?.focus();
  });

  function retry(): void {
    titleRef.current?.focus();
    setListing({ kind: 'loading' });
    // Cleared here rather than inside `load`, which the mount effect also
    // calls: a `setState` in an effect body is a cascading render the linter
    // is right to refuse, and on mount there is nothing to clear. This is the
    // only path that re-runs `load` with a stale total behind it.
    setTotal(null);
    load();
  }

  function loadMore(): void {
    if (inFlight.current) return;
    if (listing.kind !== 'loaded' || listing.exhausted) return;
    const oldest = listing.entries[listing.entries.length - 1];
    if (oldest === undefined) return;

    inFlight.current = true;
    setAppending(true);
    setAppendFailure(null);

    const mine = generation.current;

    apiRequest(`${HISTORY_PATH}?${HISTORY_CURSOR_PARAM}=${encodeURIComponent(oldest.id)}`)
      .then((body) => {
        if (generation.current !== mine) return;
        const page = asHistoryEntries(body);
        const exhausted = page.length < HISTORY_PAGE_SIZE;
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
        setAppendFailure(failure instanceof ApiRequestError ? failure.message : UNEXPECTED);
      })
      .finally(() => {
        inFlight.current = false;
        setAppending(false);
      });
  }

  return (
    <section className={styles.screen}>
      <div className={styles.header}>
        <h1 className={styles.title} id={titleId} ref={titleRef} tabIndex={-1}>
          History
        </h1>

        <div className={styles.actions}>
          <button className={styles.back} type="button" onClick={onBack}>
            {BACK}
          </button>
        </div>
      </div>

      {listing.kind === 'loading' && (
        <p className={styles.pending} role="status">
          {LOADING}
        </p>
      )}

      {listing.kind === 'failed' && (
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
          <p className={styles.empty}>{NO_SCANS}</p>
        ) : (
          <div className={styles.entries} ref={entriesRef} tabIndex={-1}>
            {listing.entries.map((entry) => (
              <article className={styles.entry} key={entry.id}>
                <p className={styles.when}>{when(entry)}</p>
                {entry.candidates.length === 0 ? (
                  <p className={styles.noMatch}>{NO_MATCH}</p>
                ) : (
                  <div className={styles.list}>
                    {entry.candidates.map((candidate, index) => (
                      <button
                        className={index === 0 ? `${styles.card} ${styles.cardBest}` : styles.card}
                        key={candidate.tile_id}
                        type="button"
                        onClick={() => setViewing(candidate)}
                      >
                        <img
                          alt={imageAlt(candidate)}
                          className={styles.refImage}
                          src={imageSrc(candidate)}
                        />
                        <span className={styles.info}>
                          {index === 0 && <span className={styles.bestPill}>{BEST_MATCH}</span>}
                          <span className={styles.code}>{candidate.code}</span>
                          <span className={styles.meta}>
                            {candidate.size} · {candidate.category ?? UNKNOWN_CATEGORY}
                          </span>
                        </span>
                      </button>
                    ))}
                  </div>
                )}
              </article>
            ))}
          </div>
        ))}

      {listing.kind === 'loaded' && listing.entries.length > 0 && (
        /* Not a live region. The two this screen already has — the appended
         * page's status line and the failure alert — are the ones a reader
         * needs read out; a third announcing a count over them would talk
         * across both. It is text beside Load more, read on demand. */
        <p className={styles.count}>{showing(listing.entries.length, total)}</p>
      )}

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

      {viewing !== null && (
        <ImageViewer
          alt={imageAlt(viewing)}
          src={imageSrc(viewing)}
          onClose={() => setViewing(null)}
        />
      )}
    </section>
  );
}
