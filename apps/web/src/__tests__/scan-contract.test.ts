/**
 * @vitest-environment node
 *
 * apps/web compiles and runs against the TypeScript half of shared/schema, so
 * the ScanCandidate contract cannot drift from its Python twin
 * (shared/schema/shared_schema/scan.py) without something failing here.
 *
 * `tile-contract.test.ts`'s sibling, and it closes the same gap for the same
 * reason. `submitScan` (`apps/web/src/api/client.ts`) turns a rejection from
 * `isScanCandidate` into `MALFORMED_RESPONSE` and renders nothing, but every
 * fixture `scan.test.tsx` feeds it is already exactly well-formed — so until
 * this file existed, the narrower could be weakened to `isUuid(tile_id)` with
 * the whole suite still green, and a `score` or a `rank` arriving from a
 * future change to `POST /scans` would be accepted and rendered straight onto
 * the Results screen, which is precisely the AD-20/AD-9 leak `isScanCandidate`
 * exists to make impossible.
 */
import { describe, expect, it } from 'vitest';

import { SCAN_CANDIDATE_KEYS, isScanCandidate } from '@rocell/schema/scan';

function aCandidate(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    tile_id: '11111111-1111-4111-8111-111111111111',
    code: 'RP.CMA.0001DJ.SM.0T',
    size: '45X90',
    category: 'CREMA MARMOL',
    image_id: '22222222-2222-4222-8222-222222222222',
    ...overrides,
  };
}

describe('the shared ScanCandidate', () => {
  it('accepts the shape apps/api returns', () => {
    expect(isScanCandidate(aCandidate())).toBe(true);
  });

  it('accepts a null category', () => {
    // AD-18: a Category that was never recovered is the `UNKNOWN` sentinel or
    // `null` from the join, the same nullable shape `Tile.category` carries.
    expect(isScanCandidate(aCandidate({ category: null }))).toBe(true);
  });

  it('checks every key the contract declares', () => {
    expect(SCAN_CANDIDATE_KEYS).toHaveLength(5);
    expect(new Set(Object.keys(aCandidate()))).toEqual(new Set(SCAN_CANDIDATE_KEYS));
  });

  it.each([...SCAN_CANDIDATE_KEYS])('rejects a body missing %s', (key) => {
    const candidate = aCandidate();
    delete candidate[key];
    expect(isScanCandidate(candidate)).toBe(false);
  });

  it('rejects a body carrying a key the contract does not declare', () => {
    // AD-20: no similarity value has a field here, and none ever may — this is
    // what proves nothing put one there anyway. A weakened narrower that only
    // checked the keys it knows about, rather than the key *count*, would let
    // an over-supplied body straight through.
    expect(isScanCandidate(aCandidate({ score: 0.918 }))).toBe(false);
    expect(isScanCandidate(aCandidate({ rank: 1 }))).toBe(false);
    expect(isScanCandidate(aCandidate({ similarity: 0.99 }))).toBe(false);
  });

  it.each([
    ['a non-uuid tile_id', aCandidate({ tile_id: 'not-a-uuid' })],
    ['a numeric tile_id', aCandidate({ tile_id: 1 })],
    ['a null tile_id', aCandidate({ tile_id: null })],
    ['a non-uuid image_id', aCandidate({ image_id: 'not-a-uuid' })],
    ['a null image_id', aCandidate({ image_id: null })],
    ['a numeric code', aCandidate({ code: 1 })],
    ['a null code', aCandidate({ code: null })],
    ['a numeric size', aCandidate({ size: 4590 })],
    ['a numeric category', aCandidate({ category: 45 })],
  ])('rejects %s', (_label, candidate) => {
    expect(isScanCandidate(candidate)).toBe(false);
  });

  it.each([
    ['null', null],
    ['an array', [aCandidate()]],
    ['a string', 'RP.CMA.0001DJ.SM.0T'],
    ['undefined', undefined],
    ['an empty object', {}],
  ])('rejects %s', (_label, value) => {
    expect(isScanCandidate(value)).toBe(false);
  });
});
