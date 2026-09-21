/**
 * The `Tile` and `ReferenceImage` contracts — the TypeScript twin of
 * `shared_schema/tile.py`.
 *
 * **The Code is the identity** (AD-18). One catalogue entry per file; two
 * tiles from the same Category folder are two different tiles and a list of
 * them is never collapsed, deduplicated or diversified by Category.
 * `face_number` is a display hint and nothing else.
 *
 * **`Product` and `Face` are retired words** and must not appear here, in a
 * screen, or in a label. They encoded the identity model AD-18 corrects.
 *
 * **No similarity value has a field here, and none ever may** (AD-20). A
 * correct top-1 medians 0.918 and a wrong one 0.907, and a JPEG of pure noise
 * still scores two candidates above 0.80 — the number reads as confidence and
 * carries almost none. It stays server-side.
 *
 * **No storage URL either** (AD-9). A reference image is fetched from
 * `GET /admin/tiles/{tileId}/images/{imageId}`, which re-checks authorization
 * and proxies the bytes; the id below is the only handle the client gets, and
 * the contract deliberately has nowhere to put anything else.
 *
 * These two files are one contract in two languages; change them together.
 */

/** The AD-18 sentinel, as a value — the twin of Python's `UNKNOWN_CATEGORY`. */
export const UNKNOWN_CATEGORY = 'UNKNOWN';

export interface ReferenceImage {
  /** UUIDv4. Builds the proxied image path; never a storage key. */
  id: string;
  /** Of the colour-managed, 2048px-capped asset, not of the upload. */
  width: number;
  height: number;
  /** FR-19: below the texture threshold, so it cannot be reliably retrieved. */
  featureless: boolean;
  /** ISO 8601 UTC. */
  created_at: string;
}

export interface Tile {
  /** UUIDv4. */
  id: string;
  /** The answer a Scan returns. The identity (AD-18). */
  code: string;
  /** The resolved, normalized Size name — a grouping, never an identity. */
  size: string;
  /** The resolved Category name, or null. `UNKNOWN` when nothing was recovered. */
  category: string | null;
  /** A nullable display hint. Nothing keys, groups or matches on it (AD-18). */
  face_number: string | null;
  reference_images: ReferenceImage[];
  /** ISO 8601 UTC. */
  created_at: string;
  /** ISO 8601 UTC. */
  updated_at: string;
}

/**
 * `keyof` rather than `string`, exactly as `user.ts` does it: the compiler then
 * refuses a key in any array below that the interface does not declare, so a
 * typo is a build failure here rather than a runtime surprise.
 */
const IMAGE_NUMBER_KEYS = ['width', 'height'] as const;

const IMAGE_CONTRACT_KEYS: readonly (keyof ReferenceImage)[] = [
  'id',
  'featureless',
  'created_at',
  ...IMAGE_NUMBER_KEYS,
];

/** Sorted, because `isReferenceImage` compares it against a sorted `Object.keys`. */
export const REFERENCE_IMAGE_KEYS: readonly (keyof ReferenceImage)[] = [
  ...IMAGE_CONTRACT_KEYS,
].sort();

const TILE_STRING_KEYS = ['code', 'size'] as const;
const TILE_NULLABLE_STRING_KEYS = ['category', 'face_number'] as const;
const TILE_TIMESTAMP_KEYS = ['created_at', 'updated_at'] as const;

const TILE_CONTRACT_KEYS: readonly (keyof Tile)[] = [
  'id',
  'reference_images',
  ...TILE_STRING_KEYS,
  ...TILE_NULLABLE_STRING_KEYS,
  ...TILE_TIMESTAMP_KEYS,
];

/** Sorted, because `isTile` compares it against a sorted `Object.keys`. */
export const TILE_KEYS: readonly (keyof Tile)[] = [...TILE_CONTRACT_KEYS].sort();

/**
 * UUIDv4, canonical dashed form, and ISO 8601 with an explicit UTC designator.
 *
 * Restated here rather than imported from `user.ts`: that file is the `User`
 * contract and importing its private patterns would make one contract depend
 * on another's internals. `shared_schema/tests/test_tile.py` pins both
 * spellings against the Python side, which is what actually holds them
 * together.
 */
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const UTC_TIMESTAMP_PATTERN = /^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]00:?00)$/i;

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isUuid(value: unknown): value is string {
  return typeof value === 'string' && UUID_PATTERN.test(value);
}

function isUtcTimestamp(value: unknown): value is string {
  return (
    typeof value === 'string' &&
    UTC_TIMESTAMP_PATTERN.test(value) &&
    Number.isFinite(Date.parse(value))
  );
}

/** A whole, finite, non-negative pixel count. */
function isPixelCount(value: unknown): value is number {
  return typeof value === 'number' && Number.isInteger(value) && value >= 0;
}

/**
 * Narrow an unknown body to the shared `ReferenceImage`.
 *
 * Deliberately strict, in the style of `isUser`: it accepts exactly what
 * `shared_schema/tile.py` produces and nothing more. An object carrying an
 * extra key is rejected rather than trimmed — a `source_key` or a `score`
 * arriving from a future change must be a loud failure and not a field the
 * screen quietly ignores (AD-9, AD-20).
 */
export function isReferenceImage(value: unknown): value is ReferenceImage {
  if (!isPlainObject(value)) return false;

  const keys = Object.keys(value).sort();
  if (keys.length !== REFERENCE_IMAGE_KEYS.length) return false;
  if (keys.some((key, index) => key !== REFERENCE_IMAGE_KEYS[index])) return false;

  return (
    isUuid(value['id']) &&
    IMAGE_NUMBER_KEYS.every((key) => isPixelCount(value[key])) &&
    typeof value['featureless'] === 'boolean' &&
    isUtcTimestamp(value['created_at'])
  );
}

/** Narrow an unknown response body to the shared `Tile`. */
export function isTile(value: unknown): value is Tile {
  if (!isPlainObject(value)) return false;

  const keys = Object.keys(value).sort();
  if (keys.length !== TILE_KEYS.length) return false;
  if (keys.some((key, index) => key !== TILE_KEYS[index])) return false;

  if (!TILE_STRING_KEYS.every((key) => typeof value[key] === 'string')) return false;
  if (
    !TILE_NULLABLE_STRING_KEYS.every(
      (key) => value[key] === null || typeof value[key] === 'string',
    )
  ) {
    return false;
  }
  if (!TILE_TIMESTAMP_KEYS.every((key) => isUtcTimestamp(value[key]))) return false;

  const images = value['reference_images'];
  if (!Array.isArray(images) || !images.every(isReferenceImage)) return false;

  return isUuid(value['id']);
}
