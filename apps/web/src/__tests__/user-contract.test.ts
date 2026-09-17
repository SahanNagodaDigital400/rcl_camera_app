/**
 * @vitest-environment node
 *
 * apps/web compiles and runs against the TypeScript half of shared/schema, so
 * the User contract cannot drift from its Python twin
 * (shared/schema/shared_schema/user.py) without something failing here.
 */
import { describe, expect, it } from 'vitest';

import { ROLES, USER_KEYS, isRole, isUser, isUtcTimestamp, isUuid } from '@rocell/schema/user';
import type { Role, User } from '@rocell/schema/user';

function aUser(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    id: '3f1c0f4e-6c1a-4a2f-9a1b-7d2e5c8f0a11',
    name: 'Ruwan Perera',
    email: 'ruwan@rocell.lk',
    role: 'admin',
    active: true,
    must_change_password: true,
    temp_credential_expires_at: '2026-09-20T12:00:00Z',
    last_login_at: null,
    locked_until: null,
    created_at: '2026-09-17T12:00:00Z',
    updated_at: '2026-09-17T12:00:00Z',
    ...overrides,
  };
}

describe('the shared Role', () => {
  it('is exactly Staff and Administrator', () => {
    // AGENTS.md Policy: never a third role.
    expect(new Set(ROLES)).toEqual(new Set<Role>(['staff', 'admin']));
    expect(ROLES).toHaveLength(2);
  });

  it.each([
    ['manager', false],
    ['Admin', false],
    ['', false],
    ['staff', true],
    ['admin', true],
  ])('narrows %s to %s', (value, expected) => {
    expect(isRole(value)).toBe(expected);
  });
});

describe('the shared User', () => {
  it('accepts the shape apps/api returns', () => {
    const user = aUser();

    expect(isUser(user)).toBe(true);

    if (isUser(user)) {
      const role: Role = user.role;
      const narrowed: User = user;
      expect(role).toBe('admin');
      expect(narrowed.last_login_at).toBeNull();
    }
  });

  it('accepts a Staff account that has signed in', () => {
    expect(
      isUser(
        aUser({
          role: 'staff',
          must_change_password: false,
          temp_credential_expires_at: null,
          last_login_at: '2026-09-18T08:30:00Z',
        }),
      ),
    ).toBe(true);
  });

  it('rejects a body carrying a password hash', () => {
    // The Python twin has no such field at all; extra="forbid" refuses it
    // there, and the closed-shape check has to refuse it here.
    expect(isUser(aUser({ password_hash: '$argon2id$v=19$m=65536,t=3,p=4$...' }))).toBe(false);
  });

  it.each([
    ['null', null],
    ['a bare string', 'ruwan@rocell.lk'],
    ['an array', [aUser()]],
    ['an empty object', {}],
  ])('rejects %s', (_label, body) => {
    expect(isUser(body)).toBe(false);
  });

  it.each([
    ['an unknown role', { role: 'manager' }],
    ['a non-string id', { id: 7 }],
    ['a non-boolean active', { active: 'true' }],
    ['a non-boolean must_change_password', { must_change_password: 1 }],
    ['a non-string created_at', { created_at: 1758110400 }],
    ['a null name', { name: null }],
    ['a null created_at', { created_at: null }],
  ])('rejects %s', (_label, overrides) => {
    expect(isUser(aUser(overrides))).toBe(false);
  });

  // The Python twin parses these fields, so a value that is the right *type*
  // and the wrong *shape* has to fail on both sides or the contract is only
  // half a contract.
  it.each([
    ['an id that is not a UUID', { id: 'not-a-uuid' }],
    ['an id with a stray suffix', { id: '3f1c0f4e-6c1a-4a2f-9a1b-7d2e5c8f0a11x' }],
    ['a created_at that is not a timestamp', { created_at: 'nope' }],
    ['a created_at that is only a date', { created_at: '2026-09-17' }],
    ['an updated_at with no UTC designator', { updated_at: '2026-09-17T12:00:00' }],
    ['a last_login_at that is not a timestamp', { last_login_at: 'yesterday' }],
    ['a temp_credential_expires_at that is empty', { temp_credential_expires_at: '' }],
    ['a locked_until that is not a timestamp', { locked_until: 'in a bit' }],
    ['a locked_until with no UTC designator', { locked_until: '2026-09-18T12:00:00' }],
  ])('rejects %s', (_label, overrides) => {
    expect(isUser(aUser(overrides))).toBe(false);
  });

  it('accepts the offset form of UTC as well as Z', () => {
    expect(isUser(aUser({ created_at: '2026-09-17T12:00:00+00:00' }))).toBe(true);
    expect(isUser(aUser({ created_at: '2026-09-17T12:00:00.123456Z' }))).toBe(true);
  });

  // Every key, not a hand-picked subset: a field that only one of the two
  // halves requires is exactly the drift this file exists to catch.
  it.each([...USER_KEYS])('rejects a body missing %s', (key) => {
    const body = aUser();
    delete body[key];

    expect(isUser(body)).toBe(false);
  });

  it('checks every key the contract declares', () => {
    expect(USER_KEYS).toHaveLength(11);
    expect(new Set(Object.keys(aUser()))).toEqual(new Set(USER_KEYS));
  });
});

describe('the value checks behind the User contract', () => {
  it.each([
    ['3f1c0f4e-6c1a-4a2f-9a1b-7d2e5c8f0a11', true],
    ['3F1C0F4E-6C1A-4A2F-9A1B-7D2E5C8F0A11', true],
    ['3f1c0f4e6c1a4a2f9a1b7d2e5c8f0a11', false],
    ['not-a-uuid', false],
    ['', false],
    [7, false],
    [null, false],
  ])('isUuid(%s) is %s', (value, expected) => {
    expect(isUuid(value)).toBe(expected);
  });

  it.each([
    ['2026-09-17T12:00:00Z', true],
    ['2026-09-17T12:00:00.5Z', true],
    ['2026-09-17T12:00:00+0000', true],
    ['2026-09-17T12:00:00+05:30', false],
    ['2026-09-17T12:00:00', false],
    ['2026-09-17', false],
    ['nope', false],
    [1758110400, false],
  ])('isUtcTimestamp(%s) is %s', (value, expected) => {
    expect(isUtcTimestamp(value)).toBe(expected);
  });
});
