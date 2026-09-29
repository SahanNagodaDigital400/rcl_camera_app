/**
 * The `Marker` contract — the TypeScript twin of `shared_schema/marker.py`.
 *
 * A Marker is a physical object of known size laid on a tile before it is
 * photographed: the scale reference the pixels cannot carry. It is reference
 * data, not catalogue data — it names no Tile, no Size and no Category — and a
 * measurement taken with one is a *suggestion* that pre-fills the Scan
 * screen's Size picker, never a value wired straight into the search.
 *
 * These two files are one contract in two languages; change them together.
 */

import { isUtcTimestamp, isUuid } from './user';

/**
 * The fiducial families a Marker may declare.
 *
 * Four, and deliberately not every family OpenCV ships — each is a card an
 * Administrator has to print and a staff member has to carry, and each extra
 * family is another way for two sites to print incompatible cards that both
 * "work". Mirrors `ArucoDictionary` in the Python twin.
 */
export type ArucoDictionary =
  | 'DICT_4X4_50'
  | 'DICT_5X5_100'
  | 'DICT_6X6_250'
  | 'DICT_APRILTAG_36h11';

/** Every dictionary the product accepts. Iterable, so a narrowing check cannot miss one. */
export const ARUCO_DICTIONARIES: readonly ArucoDictionary[] = [
  'DICT_4X4_50',
  'DICT_5X5_100',
  'DICT_6X6_250',
  'DICT_APRILTAG_36h11',
];

/**
 * How many distinct ids each family carries — the exclusive upper bound on a
 * Marker's `aruco_id`, mirroring `ARUCO_DICTIONARY_SIZES` on the Python side.
 *
 * The form refuses an out-of-range id before sending, so an Administrator is
 * told which family they are outside of rather than being handed a generic
 * rejection. The server's copy remains the authority.
 */
export const ARUCO_DICTIONARY_SIZES: Readonly<Record<ArucoDictionary, number>> = {
  DICT_4X4_50: 50,
  DICT_5X5_100: 100,
  DICT_6X6_250: 250,
  'DICT_APRILTAG_36h11': 587,
};

export interface Marker {
  /** UUIDv4. */
  id: string;
  name: string;
  /**
   * The printed size of the marker itself, in millimetres. For a fiducial this
   * is the **black square's** outer edge, not the paper around it — the
   * detector returns the black square's corners, and measuring to the paper
   * would scale every result by the width of the quiet zone.
   */
  width_mm: number;
  height_mm: number;
  /** Null together with `aruco_id` for a plain object measured by tapping. */
  aruco_dictionary: ArucoDictionary | null;
  aruco_id: number | null;
  /** ISO 8601 UTC. */
  created_at: string;
  updated_at: string;
}

/** One corner, in normalized image coordinates — 0.0–1.0 on each axis (AD-11's rule). */
export interface Point {
  x: number;
  y: number;
}

/**
 * What one measurement concluded.
 *
 * `matched_size` is null whenever nothing in the catalogue sits within
 * tolerance of the measured millimetres — it is never "the nearest Size
 * anyway", because a 300mm-out nearest is a wrong answer wearing a right
 * answer's clothes.
 */
export interface Measurement {
  /** Sorted short-edge-first, so a reader never has to know which way the tile lay. */
  short_mm: number;
  long_mm: number;
  matched_size: string | null;
  /** Whether the fiducial was found automatically, or the corners were tapped. */
  auto_detected: boolean;
}

const REQUIRED_NUMBER_KEYS = ['width_mm', 'height_mm'] as const;
const TIMESTAMP_KEYS = ['created_at', 'updated_at'] as const;

const CONTRACT_KEYS: readonly (keyof Marker)[] = [
  'id',
  'name',
  'aruco_dictionary',
  'aruco_id',
  ...REQUIRED_NUMBER_KEYS,
  ...TIMESTAMP_KEYS,
];

/** Sorted, because `isMarker` compares it against a sorted `Object.keys`. */
export const MARKER_KEYS: readonly (keyof Marker)[] = [...CONTRACT_KEYS].sort();

const MEASUREMENT_KEYS: readonly (keyof Measurement)[] = [
  'auto_detected',
  'long_mm',
  'matched_size',
  'short_mm',
];

/** Narrow an unknown value to an `ArucoDictionary`. */
export function isArucoDictionary(value: unknown): value is ArucoDictionary {
  return typeof value === 'string' && (ARUCO_DICTIONARIES as readonly string[]).includes(value);
}

/**
 * Narrow an unknown response body to the shared `Marker`.
 *
 * Strict in `isUser`'s style: exactly what `shared_schema/marker.py` produces
 * and nothing more. The both-or-neither rule on the fiducial pair is checked
 * here too — half a declaration is a card the detector will never find, and
 * the Python model refuses to store one, so accepting it here would leave the
 * two halves disagreeing about what a Marker is.
 */
export function isMarker(value: unknown): value is Marker {
  if (!isPlainObject(value)) return false;

  const keys = Object.keys(value).sort();
  if (keys.length !== MARKER_KEYS.length) return false;
  if (keys.some((key, index) => key !== MARKER_KEYS[index])) return false;

  if (typeof value['name'] !== 'string') return false;
  if (!REQUIRED_NUMBER_KEYS.every((key) => isFiniteNumber(value[key]))) return false;
  if (!TIMESTAMP_KEYS.every((key) => isUtcTimestamp(value[key]))) return false;
  if (!isUuid(value['id'])) return false;

  const dictionary = value['aruco_dictionary'];
  const arucoId = value['aruco_id'];
  if (dictionary === null && arucoId === null) return true;
  if (!isArucoDictionary(dictionary)) return false;
  return (
    typeof arucoId === 'number' &&
    Number.isInteger(arucoId) &&
    arucoId >= 0 &&
    arucoId < ARUCO_DICTIONARY_SIZES[dictionary]
  );
}

/** Narrow an unknown response body to a `Measurement`. */
export function isMeasurement(value: unknown): value is Measurement {
  if (!isPlainObject(value)) return false;

  const keys = Object.keys(value).sort();
  if (keys.length !== MEASUREMENT_KEYS.length) return false;
  if (keys.some((key, index) => key !== MEASUREMENT_KEYS[index])) return false;

  if (!isFiniteNumber(value['short_mm']) || !isFiniteNumber(value['long_mm'])) return false;
  if (typeof value['auto_detected'] !== 'boolean') return false;
  const matched = value['matched_size'];
  return matched === null || typeof matched === 'string';
}

/**
 * A finite, non-negative number.
 *
 * `typeof === 'number'` alone would accept `NaN` and `Infinity`, which the
 * pydantic twin's `clean_edge_mm` rejects outright — and a `NaN` width would
 * render as "NaNmm" on screen rather than failing anywhere a reader could see.
 */
function isFiniteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0;
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}
