/**
 * `ScanCandidate`, `ScanHistoryEntry` and `ScanHistoryCount` — the
 * TypeScript twins of `shared_schema/scan.py`.
 *
 * `ScanCandidate` is one ranked match `POST /scans` answers with, up to
 * three, best match first. **Order in the array is the rank** — there is no
 * `rank` field, and the client paints the first element as "Best match" and
 * never re-derives or displays the ordinal.
 *
 * **No similarity value has a field here, and none ever may** (AD-20). See
 * `tile.ts`'s own note on `Tile` — the reasoning is identical and the score
 * stays server-side.
 *
 * **No storage URL either** (AD-9). A candidate's picture is fetched from
 * `GET /tiles/{tileId}/images/{imageId}`, which re-checks the caller's
 * session on every request; `image_id` is the only handle this contract
 * gives a client.
 *
 * `ScanHistoryEntry` is Story 3.5's addition — one past Scan `GET /scans`
 * renders, carrying the same closed `ScanCandidate` array the original
 * `POST /scans` answered with, persisted as a denormalized snapshot (AD-10).
 *
 * `ScanHistoryCount` is what a keyset-paginated history cannot say about
 * itself — the total `GET /scans/count` answers with, so the screen can show
 * "10 of 213" rather than only "10 so far".
 *
 * These two files are one contract in two languages; change them together.
 */

export interface ScanCandidate {
  /** UUIDv4. Names the Tile. */
  tile_id: string;
  /** The answer a Scan returns. The identity (AD-18). */
  code: string;
  /** The resolved, normalized Size name — a grouping, never an identity. */
  size: string;
  /** The resolved Category name, or null. `UNKNOWN` when nothing was recovered. */
  category: string | null;
  /** UUIDv4. Builds the proxied path to the tile's earliest reference image. */
  image_id: string;
}

const CANDIDATE_STRING_KEYS = ['code', 'size'] as const;
const CANDIDATE_NULLABLE_STRING_KEYS = ['category'] as const;

const CANDIDATE_CONTRACT_KEYS: readonly (keyof ScanCandidate)[] = [
  'tile_id',
  'image_id',
  ...CANDIDATE_STRING_KEYS,
  ...CANDIDATE_NULLABLE_STRING_KEYS,
];

/** Sorted, because `isScanCandidate` compares it against a sorted `Object.keys`. */
export const SCAN_CANDIDATE_KEYS: readonly (keyof ScanCandidate)[] = [
  ...CANDIDATE_CONTRACT_KEYS,
].sort();

/**
 * UUIDv4, canonical dashed form.
 *
 * Restated here rather than imported from `tile.ts`: that file is the `Tile`
 * contract and importing its internals would make one contract depend on
 * another's, `tile.ts`'s own stated reason for not importing `user.ts`'s
 * pattern. `shared_schema/tests/test_scan.py` pins the spelling against the
 * Python side, which is what actually holds the two together.
 */
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isUuid(value: unknown): value is string {
  return typeof value === 'string' && UUID_PATTERN.test(value);
}

/**
 * Narrow an unknown response body to the shared `ScanCandidate`.
 *
 * Deliberately strict, `isTile`'s own style: it accepts exactly what
 * `shared_schema/scan.py` produces and nothing more. An object carrying an
 * extra key — a `score` or a `source_key` arriving from a future change — is
 * rejected rather than trimmed (AD-9, AD-20).
 */
export function isScanCandidate(value: unknown): value is ScanCandidate {
  if (!isPlainObject(value)) return false;

  const keys = Object.keys(value).sort();
  if (keys.length !== SCAN_CANDIDATE_KEYS.length) return false;
  if (keys.some((key, index) => key !== SCAN_CANDIDATE_KEYS[index])) return false;

  if (!CANDIDATE_STRING_KEYS.every((key) => typeof value[key] === 'string')) return false;
  if (
    !CANDIDATE_NULLABLE_STRING_KEYS.every(
      (key) => value[key] === null || typeof value[key] === 'string',
    )
  ) {
    return false;
  }

  return isUuid(value['tile_id']) && isUuid(value['image_id']);
}

/**
 * How many entries one page of a caller's own scan history carries — the
 * twin of `shared_schema/scan.py`'s `HISTORY_PAGE_SIZE`, pinned to it by
 * `shared/schema/tests/test_scan.py`.
 *
 * `audit.ts`'s `AUDIT_PAGE_SIZE`'s own reasoning: `GET /scans` declares no
 * `limit` parameter, so this is here only so a page shorter than it *is* the
 * end of a caller's history — the only thing the bare-array response cannot
 * say for itself.
 *
 * Ten, where the audit log's own page is fifty: a history row carries up to
 * three Candidate cards and their reference images, not one line of text.
 * See the Python twin for the full reasoning.
 */
export const HISTORY_PAGE_SIZE = 10;

/**
 * The query parameter the keyset cursor travels in — the twin of
 * `shared_schema/scan.py`'s `HISTORY_CURSOR_PARAM`, pinned to it by
 * `shared/schema/tests/test_scan.py`.
 *
 * `audit.ts`'s `AUDIT_CURSOR_PARAM`'s own reasoning: the value is the id of
 * the oldest row already rendered, and the request is
 * `GET /scans?before=<that id>`.
 */
export const HISTORY_CURSOR_PARAM = 'before';

/**
 * ISO 8601 with an explicit UTC designator, transcribed from `audit.ts`,
 * which transcribed it from `user.ts` in turn — each contract file stands
 * alone, so a change here that the Python half does not follow is a failure
 * rather than a quiet divergence.
 */
const UTC_TIMESTAMP_PATTERN =
  /^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]00:?00)$/i;

/** Whether a value is an ISO 8601 UTC timestamp the runtime can also parse. */
export function isUtcTimestamp(value: unknown): value is string {
  return (
    typeof value === 'string' &&
    UTC_TIMESTAMP_PATTERN.test(value) &&
    Number.isFinite(Date.parse(value))
  );
}

/**
 * `ScanHistoryEntry` — one past Scan, as `GET /scans` renders it (Story 3.5).
 *
 * A denormalized snapshot (AD-10): `candidates` is the same closed
 * `ScanCandidate` array the original `POST /scans` answered with, so a
 * history entry's Code, Size and Category keep rendering after the Tile they
 * matched is removed — only the proxied image request then 404s.
 */
export interface ScanHistoryEntry {
  /** UUIDv4. */
  id: string;
  /** ISO 8601 UTC. The database clock, written once and never moved. */
  created_at: string;
  /** Up to three, best match first — never re-sorted or re-derived here. */
  candidates: ScanCandidate[];
}

const HISTORY_ENTRY_CONTRACT_KEYS: readonly (keyof ScanHistoryEntry)[] = [
  'id',
  'created_at',
  'candidates',
];

/** Sorted, because `isScanHistoryEntry` compares it against a sorted `Object.keys`. */
export const SCAN_HISTORY_ENTRY_KEYS: readonly (keyof ScanHistoryEntry)[] = [
  ...HISTORY_ENTRY_CONTRACT_KEYS,
].sort();

/**
 * Narrow an unknown response body element to the shared `ScanHistoryEntry`.
 *
 * `isAuditLogEntry`'s own shape: deliberately strict, rejecting a missing
 * key, a malformed UUID, a non-UTC timestamp, any extra key — and a
 * `candidates` array whose elements are not each a valid `ScanCandidate`, so
 * a row this build could not fully parse is refused rather than rendered as
 * a partial, potentially misleading history entry.
 */
export function isScanHistoryEntry(value: unknown): value is ScanHistoryEntry {
  if (!isPlainObject(value)) return false;

  const keys = Object.keys(value).sort();
  if (keys.length !== SCAN_HISTORY_ENTRY_KEYS.length) return false;
  if (keys.some((key, index) => key !== SCAN_HISTORY_ENTRY_KEYS[index])) return false;

  if (!isUuid(value['id'])) return false;
  if (!isUtcTimestamp(value['created_at'])) return false;

  const candidates = value['candidates'];
  return Array.isArray(candidates) && candidates.every(isScanCandidate);
}

/**
 * `ScanHistoryCount` — how many past Scans the caller has in all, as
 * `GET /scans/count` answers (the twin of `shared_schema/scan.py`'s model).
 *
 * The one thing the paginated history cannot say about itself: `GET /scans`
 * is a bare array, so a full page means "at least `HISTORY_PAGE_SIZE`" and
 * never "ten of two hundred". `HistoryScreen` counts the rows it has
 * rendered itself and reads the denominator from here.
 *
 * A snapshot, not a live figure — a scan submitted in another tab after this
 * was read is not in it. The screen re-reads it whenever it re-reads the
 * first page, and never treats it as authority over the rows on screen: the
 * rows are what they are, and this is only what they are shown out of.
 */
export interface ScanHistoryCount {
  /** Every scan of the caller's own — a total, not a page's length. */
  count: number;
}

const HISTORY_COUNT_CONTRACT_KEYS: readonly (keyof ScanHistoryCount)[] = ['count'];

/** Sorted, because `isScanHistoryCount` compares it against a sorted `Object.keys`. */
export const SCAN_HISTORY_COUNT_KEYS: readonly (keyof ScanHistoryCount)[] = [
  ...HISTORY_COUNT_CONTRACT_KEYS,
].sort();

/**
 * Narrow an unknown response body to the shared `ScanHistoryCount`.
 *
 * `isScanHistoryEntry`'s own strictness, plus the two things `typeof
 * value === 'number'` alone would let through: a `NaN` — which `JSON.parse`
 * cannot produce but a hand-built stub can — and a fraction, neither of
 * which is a number of rows. A count that fails this is a malformed
 * response, and the screen renders no denominator rather than a wrong one.
 */
export function isScanHistoryCount(value: unknown): value is ScanHistoryCount {
  if (!isPlainObject(value)) return false;

  const keys = Object.keys(value).sort();
  if (keys.length !== SCAN_HISTORY_COUNT_KEYS.length) return false;
  if (keys.some((key, index) => key !== SCAN_HISTORY_COUNT_KEYS[index])) return false;

  const count = value['count'];
  return typeof count === 'number' && Number.isInteger(count) && count >= 0;
}
