/**
 * @vitest-environment node
 *
 * apps/web compiles and runs against the TypeScript half of shared/schema, so
 * the error contract cannot drift from its Python twin
 * (shared/schema/shared_schema/errors.py) without something failing here.
 */
import { describe, expect, it } from 'vitest';

import { isErrorEnvelope } from '@rocell/schema/errors';
import type { ErrorEnvelope } from '@rocell/schema/errors';

describe('the shared error envelope', () => {
  it('accepts the shape apps/api returns', () => {
    const body: ErrorEnvelope = { error: { code: 'tile_not_found', message: 'No Tile.' } };

    expect(isErrorEnvelope(body)).toBe(true);
  });

  it.each([
    ['null', null],
    ['a bare string', 'tile_not_found'],
    ['an unwrapped error', { code: 'tile_not_found', message: 'No Tile.' }],
    ['a missing message', { error: { code: 'tile_not_found' } }],
    ['a non-string code', { error: { code: 7, message: 'No Tile.' } }],
    ['an array', [{ error: { code: 'tile_not_found', message: 'No Tile.' } }]],
    ['an empty array', []],
    ['an extra top-level key', { error: { code: 'c', message: 'm' }, detail: 'legacy' }],
    ['an extra key on the body', { error: { code: 'c', message: 'm', field: 'code' } }],
    ['a nested envelope', { error: { error: { code: 'c', message: 'm' } } }],
  ])('rejects %s', (_label, body) => {
    expect(isErrorEnvelope(body)).toBe(false);
  });
});
