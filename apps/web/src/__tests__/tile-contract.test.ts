/**
 * @vitest-environment node
 *
 * apps/web compiles and runs against the TypeScript half of shared/schema, so
 * the Tile contract cannot drift from its Python twin
 * (shared/schema/shared_schema/tile.py) without something failing here.
 *
 * `isTile` is the only structural guard on the body of `POST /admin/tiles`:
 * `AddTileScreen` turns a rejection into `MALFORMED_RESPONSE` and renders
 * nothing. Every other test that reaches it feeds it a well-formed body, so
 * until this file existed the narrower could be weakened to `isUuid(id)` with
 * the suite green — and a `score` or a `source_key` arriving from a future
 * change would be accepted and rendered, which is the AD-20/AD-9 leak these
 * functions exist to make impossible.
 */
import { describe, expect, it } from 'vitest';

import {
  REFERENCE_IMAGE_KEYS,
  TILE_KEYS,
  UNKNOWN_CATEGORY,
  isReferenceImage,
  isTile,
} from '@rocell/schema/tile';

function anImage(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    id: '8a1f0c2e-5b3d-4e6f-9a0b-1c2d3e4f5a6b',
    width: 2048,
    height: 1365,
    featureless: false,
    created_at: '2026-09-21T12:00:00Z',
    ...overrides,
  };
}

function aTile(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    id: '3f1c0f4e-6c1a-4a2f-9a1b-7d2e5c8f0a11',
    code: 'RP.CMA.0001DJ.SM.0T',
    size: '45X90',
    category: 'CREMA MARMOL',
    face_number: null,
    reference_images: [anImage()],
    created_at: '2026-09-21T12:00:00Z',
    updated_at: '2026-09-21T12:00:00Z',
    ...overrides,
  };
}

describe('the shared ReferenceImage', () => {
  it('accepts the shape apps/api returns', () => {
    expect(isReferenceImage(anImage())).toBe(true);
    expect(isReferenceImage(anImage({ featureless: true }))).toBe(true);
  });

  it('rejects a body carrying a key the contract does not declare', () => {
    // AD-9: a storage key must never become a field the screen quietly
    // ignores. The rejection is what makes it a loud failure.
    expect(isReferenceImage(anImage({ derivative_key: 'tiles/x/y.jpg' }))).toBe(false);
    expect(isReferenceImage(anImage({ source_key: 'tiles/x/y.jpg' }))).toBe(false);
  });

  it.each(REFERENCE_IMAGE_KEYS)('rejects a body missing %s', (key) => {
    const image = anImage();
    delete image[key];
    expect(isReferenceImage(image)).toBe(false);
  });

  it.each([
    ['a non-uuid id', anImage({ id: '8a1f0c2e' })],
    ['a numeric id', anImage({ id: 1 })],
    ['a fractional width', anImage({ width: 2048.5 })],
    ['a negative height', anImage({ height: -1 })],
    ['a stringified width', anImage({ width: '2048' })],
    ['a non-boolean featureless', anImage({ featureless: 'false' })],
    ['a naive timestamp', anImage({ created_at: '2026-09-21T12:00:00' })],
    ['an unparseable timestamp', anImage({ created_at: '2026-13-45T99:00:00Z' })],
  ])('rejects %s', (_label, image) => {
    expect(isReferenceImage(image)).toBe(false);
  });

  it.each([
    ['null', null],
    ['an array', [anImage()]],
    ['a string', 'image'],
    ['undefined', undefined],
  ])('rejects %s', (_label, value) => {
    expect(isReferenceImage(value)).toBe(false);
  });
});

describe('the shared Tile', () => {
  it('accepts the shape apps/api returns', () => {
    expect(isTile(aTile())).toBe(true);
  });

  it('accepts the nullable fields as null', () => {
    // AD-18: `face_number` is a display hint, and a Category that was never
    // recovered is the sentinel rather than a dropped tile.
    expect(isTile(aTile({ face_number: null, category: null }))).toBe(true);
    expect(isTile(aTile({ category: UNKNOWN_CATEGORY }))).toBe(true);
  });

  it('accepts a tile with more than one reference image', () => {
    const images = [anImage(), anImage({ id: '11111111-2222-4333-8444-555555555555' })];
    expect(isTile(aTile({ reference_images: images }))).toBe(true);
  });

  it('rejects a body carrying a key the contract does not declare', () => {
    // AD-20: the similarity value stays server-side, and the contract has
    // nowhere to put it. This is what proves nothing put one there anyway.
    expect(isTile(aTile({ score: 0.918 }))).toBe(false);
    expect(isTile(aTile({ design: 'CREMA MARMOL' }))).toBe(false);
  });

  it.each(TILE_KEYS)('rejects a body missing %s', (key) => {
    const tile = aTile();
    delete tile[key];
    expect(isTile(tile)).toBe(false);
  });

  it.each([
    ['a non-uuid id', aTile({ id: 'not-a-uuid' })],
    ['a null code', aTile({ code: null })],
    ['a numeric size', aTile({ size: 4590 })],
    ['a numeric face_number', aTile({ face_number: 3 })],
    ['a naive created_at', aTile({ created_at: '2026-09-21 12:00:00' })],
    ['reference_images as an object', aTile({ reference_images: anImage() })],
    ['a malformed member of reference_images', aTile({ reference_images: [anImage({ id: 1 })] })],
    [
      'an over-supplied member of reference_images',
      aTile({ reference_images: [anImage({ source_key: 'tiles/x/y.jpg' })] }),
    ],
  ])('rejects %s', (_label, tile) => {
    expect(isTile(tile)).toBe(false);
  });

  it('rejects an empty reference_images array only by not rejecting it', () => {
    // Stated rather than left implicit: the narrower is a shape check, and a
    // tile whose images all failed is refused by the server before a body
    // exists. Nothing here should read as the client enforcing that rule.
    expect(isTile(aTile({ reference_images: [] }))).toBe(true);
  });

  it.each([
    ['null', null],
    ['an array', [aTile()]],
    ['a string', 'tile'],
    ['undefined', undefined],
  ])('rejects %s', (_label, value) => {
    expect(isTile(value)).toBe(false);
  });
});
