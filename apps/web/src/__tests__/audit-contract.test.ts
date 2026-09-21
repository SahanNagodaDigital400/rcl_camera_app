/**
 * @vitest-environment node
 *
 * apps/web compiles and runs against the TypeScript half of shared/schema, so
 * the AuditLogEntry contract cannot drift from its Python twin
 * (shared/schema/shared_schema/audit.py) without something failing here.
 *
 * `user-contract.test.ts`'s sibling, and it closes the same gap for the same
 * reason: `shared/schema/tests/test_audit.py` reads `audit.ts` as *text* and
 * never executes a line of it, and `audit-log.test.tsx` feeds the screen only
 * bodies that are malformed in shape — an object where an array belongs, an
 * element missing most of its keys — each rejected on the key-count line
 * before any value check runs. So without this file, `isAuditLogEntry`'s
 * value-level and extra-key rejections have no caller at all: deleting the
 * sorted-key comparison, or the timestamp check, leaves the whole suite green,
 * and a body carrying `created_at: 'yesterday'` renders `Invalid Date` into
 * the one record in the product that can never be corrected in place.
 */
import { describe, expect, it } from 'vitest';

import {
  AUDIT_ACTIONS,
  AUDIT_CURSOR_PARAM,
  AUDIT_LOG_ENTRY_KEYS,
  AUDIT_PAGE_SIZE,
  isAuditAction,
  isAuditLogEntry,
  isUtcTimestamp,
  isUuid,
} from '@rocell/schema/audit';
import type { AuditAction, AuditLogEntry } from '@rocell/schema/audit';

function anEntry(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    id: '1a2b3c4d-5e6f-4071-8293-a4b5c6d7e8f9',
    created_at: '2026-09-21T09:30:00Z',
    action: 'user_edited',
    actor_user_id: '9c2f1e4a-7b3d-4c58-9e10-2a6f8d4b1c07',
    actor_email: 'ruwan@rocell.lk',
    target_user_id: '3f1a6b2c-9d4e-4f70-8a11-5c2e7b9d0a34',
    target_email: 'kasun@rocell.lk',
    source_ip: '127.0.0.1',
    details: { changed: { role: { from: 'staff', to: 'admin' } } },
    ...overrides,
  };
}

describe('the shared AuditAction', () => {
  it('is the thirteen actions Epic 1 writes', () => {
    expect(AUDIT_ACTIONS).toHaveLength(13);
    expect(new Set(AUDIT_ACTIONS)).toEqual(
      new Set<AuditAction>([
        'login_succeeded',
        'login_failed',
        'login_refused_locked',
        'logged_out',
        'password_claimed',
        'password_changed',
        'password_change_refused',
        'sessions_revoked',
        'user_provisioned',
        'user_edited',
        'user_deactivated',
        'user_activated',
        'user_deleted',
      ]),
    );
  });

  it.each([
    ['login_succeeded', true],
    ['user_deleted', true],
    ['catalogue_tile_added', false],
    ['LOGIN_SUCCEEDED', false],
    ['', false],
    [7, false],
    [null, false],
  ])('narrows %s to %s', (value, expected) => {
    expect(isAuditAction(value)).toBe(expected);
  });

  it.each(['toString', 'constructor', 'valueOf', '__proto__', 'hasOwnProperty'])(
    'refuses %s, which is a property of every object and an action of none',
    (key) => {
      // The narrower is what stops `ACTION_LABELS[action]` reaching
      // `Object.prototype` and handing a *function* to React as a table cell.
      // `action` is a free-text column with no CHECK and corrective entries
      // are inserted by hand (AD-4), so a value shaped like a prototype key is
      // something the log can really hold — and the screen has to render it as
      // the text it is.
      expect(isAuditAction(key)).toBe(false);
    },
  );
});

describe('the shared AuditLogEntry', () => {
  it('accepts the shape apps/api returns', () => {
    const entry = anEntry();

    expect(isAuditLogEntry(entry)).toBe(true);

    if (isAuditLogEntry(entry)) {
      const narrowed: AuditLogEntry = entry;
      expect(narrowed.action).toBe('user_edited');
      expect(narrowed.details['changed']).toEqual({ role: { from: 'staff', to: 'admin' } });
    }
  });

  it('accepts an entry with no actor, no target and no recorded address', () => {
    // An unknown-account sign-in attempt. Every nullable field null at once,
    // which is the shape the API really emits for that row.
    expect(
      isAuditLogEntry(
        anEntry({
          action: 'login_failed',
          actor_user_id: null,
          actor_email: null,
          target_user_id: null,
          target_email: null,
          source_ip: null,
          details: { reason: 'unknown_address' },
        }),
      ),
    ).toBe(true);
  });

  it('accepts an action outside the known vocabulary', () => {
    // The contract's deliberate asymmetry: writes take the enum, reads take a
    // string. The column has no CHECK, the vocabulary grows with Epics 2 and
    // 3, and a narrower that refused an entry it did not recognise would make
    // the append-only record less faithful on screen than in the table.
    expect(isAuditLogEntry(anEntry({ action: 'catalogue_tile_added' }))).toBe(true);
    expect(isAuditLogEntry(anEntry({ action: 'toString' }))).toBe(true);
  });

  it('accepts an empty details object', () => {
    expect(isAuditLogEntry(anEntry({ details: {} }))).toBe(true);
  });

  it('accepts the offset form of UTC as well as Z', () => {
    expect(isAuditLogEntry(anEntry({ created_at: '2026-09-21T09:30:00+00:00' }))).toBe(true);
    expect(isAuditLogEntry(anEntry({ created_at: '2026-09-21T09:30:00.123456Z' }))).toBe(true);
  });

  it.each([
    ['null', null],
    ['a bare string', 'user_edited'],
    ['an array', [anEntry()]],
    ['an empty object', {}],
  ])('rejects %s', (_label, body) => {
    expect(isAuditLogEntry(body)).toBe(false);
  });

  it('rejects a body carrying a key beyond the contract', () => {
    // The Python twin is `extra="forbid"`, so a column added to the table and
    // forgotten in the contract must be a loud failure on both sides rather
    // than a quiet drop on one.
    expect(isAuditLogEntry(anEntry({ password_hash: '$argon2id$v=19$...' }))).toBe(false);
    expect(isAuditLogEntry(anEntry({ flagged: true }))).toBe(false);
  });

  // Every key, not a hand-picked subset: a field that only one of the two
  // halves requires is exactly the drift this file exists to catch. Nullable
  // fields are required-but-nullable on both sides, so *missing* and *null*
  // are different answers and only the second is accepted.
  it.each([...AUDIT_LOG_ENTRY_KEYS])('rejects a body missing %s', (key) => {
    const body = anEntry();
    delete body[key];

    expect(isAuditLogEntry(body)).toBe(false);
  });

  it('checks every key the contract declares', () => {
    expect(AUDIT_LOG_ENTRY_KEYS).toHaveLength(9);
    expect(new Set(Object.keys(anEntry()))).toEqual(new Set(AUDIT_LOG_ENTRY_KEYS));
  });

  // The Python twin parses these fields, so a value that is the right *type*
  // and the wrong *shape* has to fail on both sides or the contract is only
  // half a contract. `created_at` is the one with teeth: a string the shape
  // check let through renders as `Invalid Date` in the When column.
  it.each([
    ['an id that is not a UUID', { id: 'not-a-uuid' }],
    ['an id with a stray suffix', { id: '1a2b3c4d-5e6f-4071-8293-a4b5c6d7e8f9x' }],
    ['a non-string id', { id: 7 }],
    ['a null id', { id: null }],
    ['an actor_user_id that is not a UUID', { actor_user_id: 'ruwan' }],
    ['a target_user_id that is not a UUID', { target_user_id: '' }],
    ['a created_at that is not a timestamp', { created_at: 'yesterday' }],
    ['a created_at that is only a date', { created_at: '2026-09-21' }],
    ['a created_at with no UTC designator', { created_at: '2026-09-21T09:30:00' }],
    ['a created_at at a non-UTC offset', { created_at: '2026-09-21T09:30:00+05:30' }],
    ['a null created_at', { created_at: null }],
    ['a non-string action', { action: 7 }],
    ['a null action', { action: null }],
    ['a non-string actor_email', { actor_email: 7 }],
    ['a non-string target_email', { target_email: [] }],
    ['a non-string source_ip', { source_ip: 127 }],
    ['a null details', { details: null }],
    ['a details that is an array', { details: [] }],
    ['a details that is a string', { details: 'reason: unknown_address' }],
  ])('rejects %s', (_label, overrides) => {
    expect(isAuditLogEntry(anEntry(overrides))).toBe(false);
  });
});

describe('the value checks behind the AuditLogEntry contract', () => {
  // Each contract file carries its own copy of these two narrowers by design,
  // so each is exercised where it lives rather than through the other's tests.
  it.each([
    ['1a2b3c4d-5e6f-4071-8293-a4b5c6d7e8f9', true],
    ['1A2B3C4D-5E6F-4071-8293-A4B5C6D7E8F9', true],
    ['1a2b3c4d5e6f40718293a4b5c6d7e8f9', false],
    ['not-a-uuid', false],
    ['', false],
    [7, false],
    [null, false],
  ])('isUuid(%s) is %s', (value, expected) => {
    expect(isUuid(value)).toBe(expected);
  });

  it.each([
    ['2026-09-21T09:30:00Z', true],
    ['2026-09-21T09:30:00.5Z', true],
    ['2026-09-21T09:30:00+0000', true],
    ['2026-09-21T09:30:00+05:30', false],
    ['2026-09-21T09:30:00', false],
    ['2026-09-21', false],
    ['yesterday', false],
    [1758447000, false],
  ])('isUtcTimestamp(%s) is %s', (value, expected) => {
    expect(isUtcTimestamp(value)).toBe(expected);
  });
});

describe('the published page size', () => {
  it('is a usable page the screen can count against', () => {
    // The screen decides "this is the last page" by comparing a page's length
    // against this number, so a zero or a one here is a screen that never
    // offers another page or one that offers one per entry. The Python twin
    // is pinned to the same value by `shared/schema/tests/test_audit.py`.
    expect(Number.isInteger(AUDIT_PAGE_SIZE)).toBe(true);
    expect(AUDIT_PAGE_SIZE).toBeGreaterThan(1);
    expect(AUDIT_PAGE_SIZE).toBeLessThanOrEqual(500);
  });
});

describe('the published cursor parameter', () => {
  it('is a non-empty name the screen can build a query string from', () => {
    // The value's *spelling* is pinned to the Python twin by
    // `shared/schema/tests/test_audit.py`, which reads this file's source; what
    // this side can say is that it is a usable parameter name at all. An empty
    // string would send `?=<id>`, which the server ignores — and an ignored
    // cursor is answered with the first page rather than refused, so every
    // Load more would repeat the newest entries with nothing raising.
    expect(typeof AUDIT_CURSOR_PARAM).toBe('string');
    expect(AUDIT_CURSOR_PARAM.length).toBeGreaterThan(0);
    expect(AUDIT_CURSOR_PARAM).toBe(encodeURIComponent(AUDIT_CURSOR_PARAM));
  });
});
