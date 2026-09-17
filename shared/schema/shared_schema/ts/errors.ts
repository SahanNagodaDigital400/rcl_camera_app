/**
 * The API error envelope — the TypeScript twin of `shared_schema/errors.py`.
 *
 * The architecture spine's Consistency Conventions table fixes one error shape
 * for the whole service: `{ "error": { "code": string, "message": string } }`.
 * These two files are one contract in two languages; change them together.
 */

export interface ErrorBody {
  code: string;
  message: string;
}

export interface ErrorEnvelope {
  error: ErrorBody;
}

/**
 * Narrow an unknown response body to the shared error envelope.
 *
 * Deliberately strict: it accepts exactly what `shared_schema/errors.py`
 * produces and nothing more. An array, and an object carrying keys beyond the
 * contract, are both rejected here as the Python model rejects them, so the
 * two halves agree on what "is an error envelope" means.
 */
export function isErrorEnvelope(value: unknown): value is ErrorEnvelope {
  if (!isPlainObject(value)) return false;

  const keys = Object.keys(value);
  if (keys.length !== 1 || keys[0] !== 'error') return false;

  const body: unknown = value['error'];
  if (!isPlainObject(body)) return false;

  const bodyKeys = Object.keys(body).sort();
  if (bodyKeys.length !== 2 || bodyKeys[0] !== 'code' || bodyKeys[1] !== 'message') return false;

  return typeof body['code'] === 'string' && typeof body['message'] === 'string';
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}
