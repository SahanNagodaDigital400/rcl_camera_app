/**
 * The `AuditLogEntry` contract — the TypeScript twin of `shared_schema/audit.py`.
 *
 * Nine keys, always all nine: a nullable field is required-but-nullable on both
 * halves, so "there was no actor" and "the key never arrived" stay different
 * facts. `action` is a plain `string` rather than the `AuditAction` union, for
 * the reason the Python docstring gives at length — the column has no CHECK,
 * the vocabulary grows every epic, and a viewer that refuses to render an entry
 * it does not recognise is the one failure an append-only record may not have.
 * The union is exported anyway, because the screen's label map is keyed on it.
 *
 * These two files are one contract in two languages; change them together.
 */

/**
 * How many entries one page of the audit log carries — the twin of
 * `shared_schema/audit.py`'s `PAGE_SIZE`, pinned to it by
 * `tests/test_audit.py`.
 *
 * **The screen is told this number; it never chooses it.** `GET /admin/audit`
 * declares no `limit` parameter, so there is nothing to send: the value is
 * here so that a page shorter than it *is* the end of the log, which is the
 * only thing the bare-array response cannot say for itself. Inferring the size
 * from the length of the first page instead would read a log of five entries
 * as a full page of five, and every short log would offer a Load more that
 * fetches nothing.
 */
export const AUDIT_PAGE_SIZE = 50;

/**
 * The query parameter the keyset cursor travels in — the twin of
 * `shared_schema/audit.py`'s `CURSOR_PARAM`, pinned to it by
 * `tests/test_audit.py`.
 *
 * The value is the id of the oldest row already rendered, and the request is
 * `GET /admin/audit?before=<that id>`. Spelled here rather than at the screen
 * because it is half of a wire contract: the other half is the name of the
 * route handler's parameter, and a rename on either side that the other does
 * not follow makes the server answer the first page to every Load more.
 */
export const AUDIT_CURSOR_PARAM = 'before';

export type AuditAction =
  | 'login_succeeded'
  | 'login_failed'
  | 'login_refused_locked'
  | 'logged_out'
  | 'password_claimed'
  | 'password_changed'
  | 'password_change_refused'
  | 'sessions_revoked'
  | 'user_provisioned'
  | 'user_edited'
  | 'user_deactivated'
  | 'user_activated'
  | 'user_deleted';

/**
 * Every action the product records today. Iterable, so a label map cannot miss
 * one — and so the parity test can read the Python enum against this list.
 */
export const AUDIT_ACTIONS: readonly AuditAction[] = [
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
];

export interface AuditLogEntry {
  /** UUIDv4. */
  id: string;
  /** ISO 8601 UTC. The database clock, written once and never moved. */
  created_at: string;
  /**
   * One of `AuditAction`, typed as `string` on purpose.
   *
   * An entry written by a newer process — or inserted by hand as the owner,
   * which is how AD-4 says a wrong entry is corrected — carries a value this
   * build has never heard of, and it still has to render.
   */
  action: string;
  /** Null together with `actor_email` where nobody is known. */
  actor_user_id: string | null;
  actor_email: string | null;
  /** Who it was done to. A snapshot pair, never a foreign key (AD-10). */
  target_user_id: string | null;
  target_email: string | null;
  /** The validated, canonicalised source address, or null where none parsed. */
  source_ip: string | null;
  /** Never null — the column defaults to `{}` — and never carries a secret. */
  details: Record<string, unknown>;
}

/**
 * `keyof AuditLogEntry`, not `string`: the compiler then refuses a key in any
 * of the arrays below that the interface does not declare, so a typo is a build
 * failure here rather than a runtime assertion in the parity tests.
 */
const REQUIRED_STRING_KEYS = ['action'] as const;
const NULLABLE_STRING_KEYS = ['actor_email', 'target_email', 'source_ip'] as const;
const NULLABLE_UUID_KEYS = ['actor_user_id', 'target_user_id'] as const;
const TIMESTAMP_KEYS = ['created_at'] as const;

const CONTRACT_KEYS: readonly (keyof AuditLogEntry)[] = [
  'id',
  'details',
  ...REQUIRED_STRING_KEYS,
  ...NULLABLE_STRING_KEYS,
  ...NULLABLE_UUID_KEYS,
  ...TIMESTAMP_KEYS,
];

/** Sorted, because `isAuditLogEntry` compares it against a sorted `Object.keys`. */
export const AUDIT_LOG_ENTRY_KEYS: readonly (keyof AuditLogEntry)[] = [...CONTRACT_KEYS].sort();

/**
 * UUIDv4, canonical dashed form — what `str(UUID)` produces on the Python side
 * and therefore what the API emits. `typeof x === 'string'` alone would accept
 * `'not-a-uuid'`, which the pydantic twin rejects outright.
 */
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/**
 * ISO 8601 with an explicit UTC designator, transcribed from `user.ts`.
 *
 * Repeated rather than imported, exactly as `isPlainObject` is: each contract
 * file stands alone, and `tests/test_audit.py` transcribes this pattern again
 * so a change here that the Python half does not follow is a failure rather
 * than a quiet divergence.
 */
const UTC_TIMESTAMP_PATTERN =
  /^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]00:?00)$/i;

/** Narrow an unknown value to an `AuditAction`. */
export function isAuditAction(value: unknown): value is AuditAction {
  return typeof value === 'string' && (AUDIT_ACTIONS as readonly string[]).includes(value);
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
 * Narrow an unknown response body element to the shared `AuditLogEntry`.
 *
 * Deliberately strict, in the style of `isUser`: it accepts exactly what
 * `shared_schema/audit.py` produces and nothing more. An object carrying a key
 * beyond the contract is rejected here as the Python model rejects it, so the
 * two halves agree on what an entry is.
 *
 * The check reaches *values*, not only types — a malformed `id`, a non-UTC
 * `created_at` or a `details` that is not an object are all refused — because
 * pydantic refuses each of them too. `action` is checked only for being a
 * string: narrowing it to the known union here would reject the entry the
 * fallback label exists for.
 */
export function isAuditLogEntry(value: unknown): value is AuditLogEntry {
  if (!isPlainObject(value)) return false;

  const keys = Object.keys(value).sort();
  if (keys.length !== AUDIT_LOG_ENTRY_KEYS.length) return false;
  if (keys.some((key, index) => key !== AUDIT_LOG_ENTRY_KEYS[index])) return false;

  if (!REQUIRED_STRING_KEYS.every((key) => typeof value[key] === 'string')) return false;
  if (!NULLABLE_STRING_KEYS.every((key) => value[key] === null || typeof value[key] === 'string')) {
    return false;
  }
  if (!NULLABLE_UUID_KEYS.every((key) => value[key] === null || isUuid(value[key]))) return false;
  if (!TIMESTAMP_KEYS.every((key) => isUtcTimestamp(value[key]))) return false;

  return isUuid(value['id']) && isPlainObject(value['details']);
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}
