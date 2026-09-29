/**
 * The shared `Marker` and `Measurement`, as the TypeScript half sees them.
 *
 * Nobody can change the contract on one side (shared/schema/shared_schema/marker.py)
 * without something failing here.
 *
 * The narrowing these guards do is not a formality. A `Marker` is a **ruler**:
 * its two dimensions scale every measurement taken with it, so a body carrying
 * a `NaN` width, or half a fiducial declaration, is not a cosmetic problem — it
 * is a measurement that comes back confident and wrong, or a card the detector
 * will never find with nothing on screen to say why. Both are rejected here as
 * the Python model rejects them.
 */

import { describe, expect, it } from 'vitest';

import {
  ARUCO_DICTIONARIES,
  ARUCO_DICTIONARY_SIZES,
  isArucoDictionary,
  isMarker,
  isMeasurement,
  MARKER_KEYS,
} from '@rocell/schema/marker';
import type { Marker, Measurement } from '@rocell/schema/marker';

/** A registered bank card: ISO/IEC 7810 ID-1, and no printed fiducial. */
function aMarker(overrides: Partial<Record<keyof Marker, unknown>> = {}): unknown {
  return {
    id: '3f8c1e5a-9b2d-4c7e-8a1f-6d0b4e2c9a37',
    name: 'Bank card',
    width_mm: 85.6,
    height_mm: 53.98,
    aruco_dictionary: null,
    aruco_id: null,
    created_at: '2026-09-28T09:00:00Z',
    updated_at: '2026-09-28T09:00:00Z',
    ...overrides,
  };
}

function aMeasurement(overrides: Partial<Record<keyof Measurement, unknown>> = {}): unknown {
  return {
    short_mm: 301.4,
    long_mm: 598.2,
    matched_size: '60X30',
    auto_detected: true,
    ...overrides,
  };
}

describe('the shared Marker', () => {
  it('is the eight fields the contract declares', () => {
    // The count is in the name on purpose: a field added here has to be a
    // deliberate edit in both twins, not a shape that quietly grew.
    expect(MARKER_KEYS).toHaveLength(8);
    expect(new Set(MARKER_KEYS)).toEqual(
      new Set<keyof Marker>([
        'id',
        'name',
        'width_mm',
        'height_mm',
        'aruco_dictionary',
        'aruco_id',
        'created_at',
        'updated_at',
      ]),
    );
  });

  it('accepts a plain object with no fiducial', () => {
    expect(isMarker(aMarker())).toBe(true);
  });

  it('accepts a fiducial card', () => {
    expect(isMarker(aMarker({ aruco_dictionary: 'DICT_4X4_50', aruco_id: 7 }))).toBe(true);
  });

  it('rejects half a fiducial declaration, in both directions', () => {
    // A card the detector will never find. The Python model refuses to store
    // one, so accepting it here would leave the two halves disagreeing about
    // what a Marker is.
    expect(isMarker(aMarker({ aruco_dictionary: 'DICT_4X4_50', aruco_id: null }))).toBe(false);
    expect(isMarker(aMarker({ aruco_dictionary: null, aruco_id: 7 }))).toBe(false);
  });

  it('rejects an id its own family does not hold', () => {
    // `DICT_4X4_50` holds 0–49. A card printed with 60 in that family does not
    // exist, and a Marker declaring one is undetectable with no way to tell
    // that from bad lighting.
    expect(isMarker(aMarker({ aruco_dictionary: 'DICT_4X4_50', aruco_id: 49 }))).toBe(true);
    expect(isMarker(aMarker({ aruco_dictionary: 'DICT_4X4_50', aruco_id: 50 }))).toBe(false);
    expect(isMarker(aMarker({ aruco_dictionary: 'DICT_4X4_50', aruco_id: -1 }))).toBe(false);
  });

  it('rejects a fractional marker id', () => {
    expect(isMarker(aMarker({ aruco_dictionary: 'DICT_4X4_50', aruco_id: 7.5 }))).toBe(false);
  });

  it('rejects an unknown dictionary', () => {
    expect(isMarker(aMarker({ aruco_dictionary: 'DICT_NOPE', aruco_id: 1 }))).toBe(false);
  });

  it.each([Number.NaN, Number.POSITIVE_INFINITY, -1, '85.6', null])(
    'rejects %p as a dimension',
    (value) => {
      // A `NaN` width renders as "NaNmm" and scales every measurement to
      // `NaN`; a string scales nothing at all. Neither fails anywhere a reader
      // would see it, which is why both are refused at the boundary.
      expect(isMarker(aMarker({ width_mm: value }))).toBe(false);
    },
  );

  it('rejects an id that is not a UUID', () => {
    expect(isMarker(aMarker({ id: 'not-a-uuid' }))).toBe(false);
  });

  it('rejects a timestamp that is not ISO 8601 UTC', () => {
    expect(isMarker(aMarker({ created_at: '2026-09-28T09:00:00+05:30' }))).toBe(false);
    expect(isMarker(aMarker({ updated_at: 'nope' }))).toBe(false);
  });

  it('rejects a body carrying a key beyond the contract', () => {
    // Closed shape, in `isUser`'s style: pydantic's default is to accept and
    // silently discard, and this half must not be laxer than that one.
    expect(isMarker({ ...(aMarker() as object), size: '60X30' })).toBe(false);
  });

  it('rejects a body missing a key', () => {
    const { name: _name, ...missing } = aMarker() as Record<string, unknown>;
    expect(isMarker(missing)).toBe(false);
  });

  it.each([null, undefined, 'a marker', 42, [aMarker()]])('rejects %p', (value) => {
    expect(isMarker(value)).toBe(false);
  });
});

describe('the fiducial dictionaries', () => {
  it('is the four families the product offers', () => {
    // Four, and deliberately not every family OpenCV ships: each is a card an
    // Administrator has to print and a staff member has to carry.
    expect(ARUCO_DICTIONARIES).toHaveLength(4);
    expect(new Set(Object.keys(ARUCO_DICTIONARY_SIZES))).toEqual(new Set(ARUCO_DICTIONARIES));
  });

  it('narrows a known family and refuses an invented one', () => {
    for (const dictionary of ARUCO_DICTIONARIES) expect(isArucoDictionary(dictionary)).toBe(true);
    expect(isArucoDictionary('DICT_9X9_1')).toBe(false);
    expect(isArucoDictionary(null)).toBe(false);
  });

  it('carries an id count for every family', () => {
    for (const dictionary of ARUCO_DICTIONARIES) {
      expect(ARUCO_DICTIONARY_SIZES[dictionary]).toBeGreaterThan(0);
    }
  });
});

describe('the shared Measurement', () => {
  it('accepts a measurement that matched a catalogue size', () => {
    expect(isMeasurement(aMeasurement())).toBe(true);
  });

  it('accepts a measurement that matched nothing', () => {
    // `null` is a first-class answer, not an error: the screen renders the
    // millimetres with no Size pre-filled. It is never "the nearest Size
    // anyway", because a wrong Size makes the true Tile unreachable (AD-19).
    expect(isMeasurement(aMeasurement({ matched_size: null }))).toBe(true);
  });

  it('accepts a measurement taken from tapped corners', () => {
    expect(isMeasurement(aMeasurement({ auto_detected: false }))).toBe(true);
  });

  it.each([Number.NaN, Number.POSITIVE_INFINITY, '598', null])(
    'rejects %p as a measured edge',
    (value) => {
      expect(isMeasurement(aMeasurement({ long_mm: value }))).toBe(false);
    },
  );

  it('rejects a non-boolean detection flag', () => {
    expect(isMeasurement(aMeasurement({ auto_detected: 'yes' }))).toBe(false);
  });

  it('rejects a body carrying a key beyond the contract', () => {
    // Notably `score`: no similarity value has a field in any contract and
    // none ever may (AD-20).
    expect(isMeasurement({ ...(aMeasurement() as object), score: 0.91 })).toBe(false);
  });

  it('rejects a body missing a key', () => {
    const { short_mm: _short, ...missing } = aMeasurement() as Record<string, unknown>;
    expect(isMeasurement(missing)).toBe(false);
  });

  it.each([null, undefined, '60X30', 42])('rejects %p', (value) => {
    expect(isMeasurement(value)).toBe(false);
  });
});
