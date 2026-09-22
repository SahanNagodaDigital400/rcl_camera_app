/**
 * `ScanCandidate` — the TypeScript twin of `shared_schema/scan.py`.
 *
 * One ranked match `POST /scans` answers with, up to three, best match
 * first. **Order in the array is the rank** — there is no `rank` field, and
 * the client paints the first element as "Best match" and never re-derives
 * or displays the ordinal.
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
