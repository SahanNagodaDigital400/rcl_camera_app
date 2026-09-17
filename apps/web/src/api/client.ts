/**
 * The one place `apps/web` knows how to reach `apps/api`.
 *
 * AD-6: this app talks to nothing but the API, holds no database or storage
 * credential, and every request goes through here. The `/api` prefix lives in
 * this file alone — the dev proxy rewrites it away (`vite.config.ts`) and the
 * production path convention is still undecided (DW-4), so keeping it in one
 * constant makes that a one-line change rather than a hunt.
 *
 * `credentials: 'same-origin'` is what carries the session cookie. It is the
 * *only* thing that does: the token is in an HTTP-only cookie the browser
 * attaches by itself, and no code in this app reads, stores or sends it
 * (AGENTS.md Policy, AD-3). There is no `Authorization` header here for the
 * same reason.
 */
import { isErrorEnvelope } from '@rocell/schema/errors';

/** Every path below is relative to this. See the module comment. */
export const API_PREFIX = '/api';

/** The envelope code the API uses for "not signed in" and "wrong credential". */
export const UNAUTHORIZED = 'unauthorized';

/**
 * The envelope code for a password the API refuses to set.
 *
 * One code for every rule — length, or reuse of the temporary password — with
 * the failing rule named in the *message*. A screen branches on this and then
 * shows the server's own sentence, which is what keeps the front end from
 * restating a policy it does not own (EXPERIENCE.md:87).
 */
export const WEAK_PASSWORD = 'weak_password';

/**
 * The envelope code for "signed in, but still on a temporary credential".
 *
 * Deliberately not `unauthorized`: the session is valid, so sending the user to
 * the login screen would loop them straight back.
 *
 * Nothing branches on it yet — no route in the product declares the gate,
 * because Story 1.4 adds no surface that serves real data. It is here for the
 * first gated surface, which Epic 2 brings, and a parity test holds it to the
 * Python spelling in the meantime.
 */
export const PASSWORD_CHANGE_REQUIRED = 'password_change_required';

/**
 * The envelope code for "this account already has a password of its own".
 *
 * Answered by `POST /auth/password` when the forced change has already been
 * done — the signed-in self-service change is a different endpoint with a
 * different contract. For the session provider it means the cached user is
 * stale, not that the request was malformed.
 */
export const PASSWORD_CHANGE_NOT_REQUIRED = 'password_change_not_required';

/** The code this module invents when the request never reached the API. */
export const NETWORK_ERROR = 'network_error';

/** The code this module invents when the request never came back. */
export const TIMEOUT = 'timeout';

/** The code this module invents when a response is not the contract. */
export const MALFORMED_RESPONSE = 'malformed_response';

/**
 * How long to wait before giving up on a request.
 *
 * Without this, a hung proxy or a captive portal leaves `fetch` pending
 * forever: the bootstrap sits on "Checking your session…" with no error, no
 * login screen and nothing the user can do. Generous enough that a slow phone
 * on a shop-floor connection finishes an Argon2id-backed login inside it.
 */
export const REQUEST_TIMEOUT_MS = 15000;

/**
 * A failed request, carrying the API's own error code.
 *
 * The code, not the message, is what calling code branches on: a message is
 * copy and will be rewritten, and a screen that keys off one is a screen that
 * breaks when someone fixes a typo.
 */
export class ApiRequestError extends Error {
  readonly code: string;
  readonly status: number;

  constructor(code: string, message: string, status: number) {
    super(message);
    this.name = 'ApiRequestError';
    this.code = code;
    this.status = status;
  }
}

interface RequestOptions {
  method?: string;
  body?: unknown;
}

/**
 * Why the request produced nothing to read.
 *
 * Timing out and failing to connect are both "the API did not answer", but they
 * are not the same advice: one asks the user to wait and retry, the other to
 * check they are online.
 */
function failed(controller: AbortController): ApiRequestError {
  if (controller.signal.aborted) {
    return new ApiRequestError(TIMEOUT, 'The server took too long to respond. Try again.', 0);
  }
  // A DNS failure, an offline device, a dropped connection. Distinct from a
  // rejection *by* the API, which the caller may want to word differently.
  return new ApiRequestError(
    NETWORK_ERROR,
    'Could not reach the server. Check your connection and try again.',
    0,
  );
}

/**
 * Send one request and return its parsed body, or throw an `ApiRequestError`.
 *
 * A `204` returns `null`: the server said "done, nothing to read", and parsing
 * an empty body as JSON would throw where nothing is wrong.
 */
export async function apiRequest(path: string, options: RequestOptions = {}): Promise<unknown> {
  const method = options.method ?? 'GET';
  const hasBody = options.body !== undefined;

  const controller = new AbortController();
  const expiry = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);

  // The timer is cleared once the *body* has been read, not once the headers
  // have arrived. A response that opens and then stalls mid-stream is exactly
  // the hung-proxy case this timeout exists for, and a timer cleared at the
  // `fetch` boundary leaves that half of the request unguarded.
  try {
    let response: Response;
    try {
      response = await fetch(`${API_PREFIX}${path}`, {
        method,
        // Same-origin only. The API is served from this origin in production and
        // through the dev proxy in development; nothing else is ever contacted.
        credentials: 'same-origin',
        headers: hasBody ? { 'content-type': 'application/json' } : undefined,
        body: hasBody ? JSON.stringify(options.body) : undefined,
        signal: controller.signal,
      });
    } catch {
      throw failed(controller);
    }

    if (response.status === 204) return null;

    let body: unknown;
    try {
      body = await response.json();
    } catch {
      // An abort here is the same timeout as an abort on the request itself.
      if (controller.signal.aborted) throw failed(controller);
      // Anything else is a body that is not JSON. On a success that is a
      // truncated stream or a proxy's HTML served under a 200, and returning
      // `null` for it would report the failure as an empty success — the
      // caller then sees "no user" rather than "the server is broken". Only
      // the failure path below can still read a non-JSON body, because its job
      // is to say what came back instead of the envelope.
      if (response.ok) {
        throw new ApiRequestError(
          MALFORMED_RESPONSE,
          'The server returned an unexpected response.',
          response.status,
        );
      }
      body = null;
    }

    if (!response.ok) {
      // Every error this API produces is the shared envelope, so anything else
      // is a proxy or a gateway answering in its place — reported as such rather
      // than rendered as an empty message.
      if (isErrorEnvelope(body)) {
        throw new ApiRequestError(body.error.code, body.error.message, response.status);
      }
      throw new ApiRequestError(
        MALFORMED_RESPONSE,
        'The server returned an unexpected response.',
        response.status,
      );
    }

    return body;
  } finally {
    // Cleared whatever happened: a pending timer holding an AbortController
    // keeps both alive, and in a test it keeps the event loop alive too.
    clearTimeout(expiry);
  }
}
