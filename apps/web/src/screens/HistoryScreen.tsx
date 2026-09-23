import { useCallback, useEffect, useId, useRef, useState } from 'react';
import type { JSX } from 'react';

import { API_PREFIX, ApiRequestError, MALFORMED_RESPONSE, apiRequest } from '../api/client';
import { ImageViewer } from '../components/ImageViewer';
import styles from './HistoryScreen.module.css';
import { HISTORY_CURSOR_PARAM, HISTORY_PAGE_SIZE, isScanHistoryEntry } from '@rocell/schema/scan';
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
 * **No row-end actions.** `rocell_app` holds full DML on `scan` (see the
 * migration's own Design Notes), but nothing in this story asks for an edit
 * or a delete control, and none is built — `AuditLogScreen`'s own precedent
 * for a record screen with nothing to click but a card.
 */

const HISTORY_PATH = '/scans';

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
