/**
 * The `User` contract — the TypeScript twin of `shared_schema/user.py`.
 *
 * Roles are `Staff` and `Administrator`, on the wire as `staff` and `admin`;
 * AGENTS.md Policy forbids a third. `password_hash` is absent from both halves
 * by construction, not by an exclusion rule, so no serializer change can ever
 * put a digest on the wire.
 *
 * These two files are one contract in two languages; change them together.
 */

export type Role = 'staff' | 'admin';

/** Every role the product has. Iterable, so a narrowing check cannot miss one. */
export const ROLES: readonly Role[] = ['staff', 'admin'];

export interface User {
  /** UUIDv4. */
  id: string;
  name: string;
  email: string;
  role: Role;
  active: boolean;
  must_change_password: boolean;
  /** ISO 8601 UTC, or null when no temporary credential is outstanding. */
  temp_credential_expires_at: string | null;
  /** ISO 8601 UTC, or null when the account has never signed in. */
  last_login_at: string | null;
  created_at: string;
  updated_at: string;
}

/**
 * `keyof User`, not `string`: the compiler then refuses a key in any of the
 * arrays below that the interface does not declare, so a typo is a build
 * failure here rather than a runtime assertion in the parity tests.
 */
const REQUIRED_STRING_KEYS = ['name', 'email'] as const;
const BOOLEAN_KEYS = ['active', 'must_change_password'] as const;
const TIMESTAMP_KEYS = ['created_at', 'updated_at'] as const;
const NULLABLE_TIMESTAMP_KEYS = ['temp_credential_expires_at', 'last_login_at'] as const;

const CONTRACT_KEYS: readonly (keyof User)[] = [
  'id',
  'role',
  ...REQUIRED_STRING_KEYS,
  ...BOOLEAN_KEYS,
  ...TIMESTAMP_KEYS,
  ...NULLABLE_TIMESTAMP_KEYS,
];

/** Sorted, because `isUser` compares it against a sorted `Object.keys`. */
export const USER_KEYS: readonly (keyof User)[] = [...CONTRACT_KEYS].sort();

/**
 * UUIDv4, canonical dashed form — what `str(UUID)` produces on the Python side
 * and therefore what the API emits. `typeof x === 'string'` alone would accept
 * `'not-a-uuid'`, which the pydantic twin rejects outright.
 */
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/**
 * ISO 8601 with an explicit UTC designator. The spine's Consistency
 * Conventions fix timestamps as ISO 8601 UTC, and the columns behind them are
 * `timestamptz` read as UTC; a bare `'nope'` is not a timestamp and the
 * pydantic twin will not accept one.
 *
 * The twin holds up its end: `User`'s fields are `AwareDatetime`, so a naive
 * value is refused there, and a JSON serializer converts whatever offset the
 * driver returned to UTC before it reaches the wire. Without that, an API
 * process whose session time zone was not UTC would emit `+05:30` and this
 * check would reject a body pydantic had just validated.
 */
const UTC_TIMESTAMP_PATTERN =
  /^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]00:?00)$/i;

/** Narrow an unknown value to a `Role`. */
export function isRole(value: unknown): value is Role {
  return typeof value === 'string' && (ROLES as readonly string[]).includes(value);
}

/** Whether a value is a UUID in the form the API emits. */
export function isUuid(value: unknown): value is string {
  return typeof value === 'string' && UUID_PATTERN.test(value);
}

/** Whether a value is an ISO 8601 UTC timestamp the runtime can also parse. */
export function isUtcTimestamp(value: unknown): value is string {
  return (
    typeof value === 'string' &&
    UTC_TIMESTAMP_PATTERN.test(value) &&
    Number.isFinite(Date.parse(value))
  );
}

/**
 * Narrow an unknown response body to the shared `User`.
 *
 * Deliberately strict, in the style of `isErrorEnvelope`: it accepts exactly
 * what `shared_schema/user.py` produces and nothing more. An object carrying
 * `password_hash` — or any other key beyond the contract — is rejected here as
 * the Python model rejects it, so the two halves agree on what a `User` is.
 *
 * The check reaches *values*, not only types: pydantic rejects an `id` that is
 * not a UUID and a `created_at` that is not a timestamp, so `typeof === 'string'`
 * alone would leave "one contract in two languages" untrue at value level.
 */
export function isUser(value: unknown): value is User {
  if (!isPlainObject(value)) return false;

  const keys = Object.keys(value).sort();
  if (keys.length !== USER_KEYS.length) return false;
  if (keys.some((key, index) => key !== USER_KEYS[index])) return false;

  if (!REQUIRED_STRING_KEYS.every((key) => typeof value[key] === 'string')) return false;
  if (!BOOLEAN_KEYS.every((key) => typeof value[key] === 'boolean')) return false;
  if (!TIMESTAMP_KEYS.every((key) => isUtcTimestamp(value[key]))) return false;
  if (!NULLABLE_TIMESTAMP_KEYS.every((key) => value[key] === null || isUtcTimestamp(value[key]))) {
    return false;
  }

  return isUuid(value['id']) && isRole(value['role']);
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}
