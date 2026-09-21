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
 * The envelope code for "signed in, but not an Administrator".
 *
 * A `403` from any `/admin/` route. No screen branches on it — an admin-only
 * door is not rendered for a Staff session — but an account demoted between
 * two requests receives it, and every such screen renders the API's sentence
 * unchanged. Named here so that the code the server can emit is accounted for
 * on this side rather than living only as a literal in test fixtures.
 */
export const ADMINISTRATOR_REQUIRED = 'administrator_required';

/**
 * The status that means the session is gone, whatever body came with it.
 *
 * Read alongside `UNAUTHORIZED` rather than instead of it: the *code* is what a
 * screen branches on, and the *status* is what the session observer keys off,
 * because a proxy answering 401 with its own HTML carries no code at all.
 */
export const HTTP_UNAUTHORIZED = 401;

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

/**
 * The envelope code for "the current password you typed is not the right one".
 *
 * Answered by `POST /auth/password/change` alone, and it arrives as a **403**,
 * not a 401 — which is the whole reason it exists as a code of its own.
 * `notifyUnauthorized` below fires on *status* 401, and `SessionProvider`
 * answers that by dropping the shell to the login screen; a 401 here would
 * therefore sign a user out for mistyping a field, and hand them a login form
 * asking for the very password they have just failed to remember. At 403 no
 * observer watches, and the screen is free to treat it as what it is: one field
 * to retype.
 *
 * **The field at fault is the *current* password, not the new one.** That is the
 * difference from `WEAK_PASSWORD`, which is always about the new one. A screen
 * that marked the wrong box would send the user to correct something that is
 * perfectly fine.
 */
export const INVALID_CURRENT_PASSWORD = 'invalid_current_password';

/**
 * The envelope code for "too many failed sign-ins against this address".
 *
 * Deliberately **not** `unauthorized`, and the distinction is behavioural, not
 * cosmetic: the credential is not what was refused — it was never looked at —
 * so nothing the user typed is at fault. The login screen therefore marks
 * neither field invalid, keeps the typed password and leaves focus alone, which
 * is the same treatment it gives a network failure and the opposite of what it
 * does to a rejected credential.
 *
 * It also arrives as a `429`, so `notifyUnauthorized` does not fire for it: the
 * session observer keys off the 401 status, and a lockout is not a session
 * ending.
 *
 * **No countdown is ever rendered from it.** The API sends `Retry-After`
 * alongside this code; that header is machine-facing, and EXPERIENCE.md's
 * Login-lockout row is explicit that the screen shows the message without one.
 * The API's own sentence is the whole of what the user is told.
 */
export const ACCOUNT_LOCKED = 'account_locked';

/**
 * The envelope code for an address `POST /admin/users` will not store.
 *
 * Answered when what was typed is not an address at all — no `@`, an empty side
 * of one, a control character. The API's own sentence names the rule
 * (EXPERIENCE.md:87), so a screen branches on this only to decide **which field
 * to mark and focus**, which is the *email* field, and renders the server's
 * wording rather than restating a rule it does not own.
 *
 * It arrives as a `422` with a code of its own rather than the generic
 * `validation_error`, precisely so that decision is possible: the generic one
 * carries one sentence for every malformed body in the product and names no
 * field at all.
 */
export const INVALID_EMAIL = 'invalid_email';

/**
 * The envelope code for an address that is already somebody's login.
 *
 * Also the **email** field — nothing is wrong with the rest of the form, and the
 * person may simply already have access. Distinct from `invalid_email` because
 * what the Administrator does about it is different: one is a typo to correct,
 * the other is a user who already exists.
 *
 * A `409`, so no observer watches it and nothing about the session changes.
 */
export const EMAIL_ALREADY_EXISTS = 'email_already_exists';

/**
 * The envelope code for an id `PATCH /admin/users/{id}` found no row behind.
 *
 * It marks **no field**. Nothing on the form is wrong — the account itself is
 * gone, deleted from another tab or another device since the list was fetched —
 * so pointing at an input would send the Administrator to correct something that
 * is perfectly fine. The screen renders the API's own sentence, which tells them
 * the thing they can act on: reload the list.
 *
 * A `404`, so no observer watches it and nothing about the session changes.
 */
export const USER_NOT_FOUND = 'user_not_found';

/**
 * The envelope code for a demotion that would leave nobody in charge.
 *
 * The **role** control is what it marks: the role is the field that was refused,
 * and the other two would have been written had they arrived alone. The API's
 * own sentence names the rule and the way out of it, which is to make somebody
 * else an Administrator first.
 *
 * A `409`, deliberately not a `403`: nothing is wrong with the caller's
 * authority — they are an Administrator — so no observer watches it, the session
 * is untouched, and the screen treats it as one control to change.
 */
export const LAST_ADMINISTRATOR = 'last_administrator';

/**
 * The envelope code for a Code `POST /admin/tiles` will not store.
 *
 * Blank, over the length bound, or carrying a control character. The **code**
 * field is what it marks: the API's own sentence names the rule that failed
 * (EXPERIENCE.md:87), and the screen renders it rather than restating a rule
 * it does not own.
 *
 * A `422` with a code of its own rather than the generic `validation_error`,
 * precisely so that decision is possible: the generic one carries one sentence
 * for every malformed body in the product and names no field at all.
 */
export const INVALID_CODE = 'invalid_code';

/** The envelope code for a blank or missing Size. Marks the **size** field. */
export const INVALID_SIZE = 'invalid_size';

/**
 * The envelope code for a Category the endpoint will not store.
 *
 * Only ever a length or a control character: an *absent* Category is not an
 * error at all — it resolves to the `UNKNOWN` sentinel (AD-18) — so this
 * cannot fire on an empty field.
 */
export const INVALID_CATEGORY = 'invalid_category';

/**
 * The envelope code for a request that carried no reference image.
 *
 * Marks the **images** control. A Tile with no reference image is a catalogue
 * row no Scan can return and no member of staff can verify, which is why this
 * is a refusal rather than a Tile saved without one.
 */
export const INVALID_IMAGE = 'invalid_image';

/**
 * The envelope code for bytes that are not a readable image.
 *
 * Zero bytes, a truncated file, or something that was never an image — decided
 * by **content**, never by the file name or by the type the browser declared
 * (AGENTS.md Policy). The real catalogue genuinely holds `.tif` files behind
 * `.jpg` names, so a screen must not pre-judge either.
 */
export const UNREADABLE_IMAGE = 'unreadable_image';

/**
 * The envelope code for a file above the byte or pixel ceiling.
 *
 * A `413`. One code for both ceilings because the Administrator's answer is
 * the same either way, and the API's sentence carries both numbers.
 */
export const IMAGE_TOO_LARGE = 'image_too_large';

/** The envelope code for more files in one request than the endpoint accepts. */
export const TOO_MANY_IMAGES = 'too_many_images';

/**
 * The envelope code for a Code that is already a tile's.
 *
 * Marks the **code** field. A `409`: nothing is wrong with the caller's
 * authority and nothing about the session changes, so no observer watches it.
 * The Code *is* the tile's identity (AD-18), so this is a real conflict and
 * not a near-miss to be resolved by adding a suffix.
 */
export const CODE_ALREADY_EXISTS = 'code_already_exists';

/**
 * The envelope code for "the image pipeline is not available on this server".
 *
 * A `503`, and it marks **no field**: nothing the Administrator typed or chose
 * is at fault, and the fix is an operator's. The API's sentence names the
 * setup step, so the screen renders it and offers no retry of its own — a
 * retry against a server missing its model artifact fails identically.
 */
export const MATCHING_UNAVAILABLE = 'matching_unavailable';

/**
 * The envelope code for "this server's pixel pipeline is not the one the index
 * was built with" (AD-14).
 *
 * A `503` from either catalogue route, and like `MATCHING_UNAVAILABLE` it
 * marks no field: an embedding written by one pipeline and one read by another
 * are not comparable, and the answer is a re-index, not a retry. Exported so
 * that the code the API can emit has a name here rather than reaching the
 * screen as a string nothing accounts for.
 */
export const PIPELINE_STAMP_MISMATCH = 'pipeline_stamp_mismatch';

/**
 * The envelope code for "no such reference image under that tile".
 *
 * A `404` from `GET /admin/tiles/{tileId}/images/{imageId}`, which is also the
 * answer to a mismatched-but-existing pair — the route never confirms that an
 * id exists under a tile the caller did not name correctly.
 */
export const IMAGE_NOT_FOUND = 'image_not_found';

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
 * How long to wait on a request that has to embed images before it can answer.
 *
 * **15 seconds is wrong for `POST /admin/tiles` by an order of magnitude, and
 * the failure it produces is the worst kind.** One reference image is 16
 * forward passes (AD-13) at roughly half a second each on a CPU; eight of them
 * is minutes. The default abort fires while the server is still working, the
 * request completes anyway and commits, and the Administrator is shown a
 * network error for a tile that now exists — so the obvious response, pressing
 * Save again, answers `code_already_exists` and reads as the app contradicting
 * itself.
 *
 * Sized for the worst request the endpoint accepts — eight images — with room
 * for a slower machine than this one. A bound this long is only tolerable
 * because the screen shows `Saving…` throughout and disables both its
 * controls: nothing here is a silent wait.
 */
export const UPLOAD_TIMEOUT_MS = 600000;

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
  /**
   * The request body. A `FormData` is sent as it is; anything else is JSON.
   *
   * The distinction is not a convenience. A multipart body's `content-type`
   * carries the boundary token that delimits its parts, and only the runtime
   * that built the `FormData` knows what that token is — so setting the header
   * by hand produces a body the server cannot parse, and the failure is a
   * `422` about a shape rather than anything that points at the header.
   * `fetch` sets it correctly when, and only when, the header is absent.
   */
  body?: unknown;
  /**
   * How long to wait before aborting, in milliseconds.
   *
   * Defaults to `REQUEST_TIMEOUT_MS`, which is right for every request that
   * reads or writes a row. A request that makes the server *compute* — today
   * only the catalogue upload, tomorrow the scan — passes its own, because a
   * timeout shorter than the work is an abort in the middle of a write and
   * not a diagnosis.
   */
  timeoutMs?: number;
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
 * Told whenever a request is refused with `unauthorized`. See `onUnauthorized`.
 *
 * Module-level and single, not a list: there is one session in the app, so
 * there is one thing that needs to know it ended. A set of subscribers would
 * invite two of them to disagree about what to do about it.
 */
let unauthorizedObserver: (() => void) | null = null;

/**
 * Watch for the API refusing a request because the session is gone.
 *
 * Registered here rather than handled per screen. The gap this closes (DW-37)
 * is not that one screen forgot about expiry — it is that nothing in the app
 * ever learns the server stopped honouring the cookie. Every request in the
 * product goes through `apiRequest`, so this is the one place that always
 * finds out, and the first Epic 2 screen that calls `apiRequest` directly
 * inherits the behaviour instead of having to remember it.
 *
 * **It observes; it does not handle.** The originating caller still gets its
 * own rejection and still decides what to show — the login screen's own
 * "email or password is incorrect" is an `unauthorized` too, and swallowing it
 * here would leave a form that submits and does nothing.
 *
 * **Registering replaces whatever was registered before, silently.** There is
 * one slot, and the app has one registrant — `SessionProvider`, which
 * re-registers on each sign-in after its own teardown has cleared the slot. A
 * second consumer added later would not sit alongside the first; it would
 * disable it, and the only symptom would be the shell quietly rendering over a
 * dead session again. Whatever needs to know next must be composed into the
 * provider's handler rather than registered here beside it.
 *
 * Returns the deregistration, so an effect can tear it down.
 */
export function onUnauthorized(handler: () => void): () => void {
  unauthorizedObserver = handler;
  return () => {
    // Only if it is still ours. Under StrictMode the effect runs, tears down
    // and runs again; clearing unconditionally would drop the *second*
    // registration and leave the app with no observer at all.
    if (unauthorizedObserver === handler) unauthorizedObserver = null;
  };
}

/**
 * Tell the observer, and never let it change what the caller sees.
 *
 * The observer runs on the way to a rejection the caller is written to branch
 * on. If it threw, *that* error would propagate instead of the
 * `ApiRequestError`, and `LoginScreen`'s `unauthorized` branch — the one that
 * words a refused credential — would simply not run. An observer is a
 * notification, so its failure is its own.
 */
function notifyUnauthorized(): void {
  try {
    unauthorizedObserver?.();
  } catch {
    // Deliberately swallowed, and deliberately not logged through anything
    // this module would have to import: the caller's own rejection is about to
    // be thrown and is the thing that matters.
  }
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
  // `typeof` guarded because this module is also read in a node test
  // environment, where `FormData` may not be defined at all — an unguarded
  // `instanceof` against a missing global is a `ReferenceError`, not `false`.
  const isFormData = typeof FormData !== 'undefined' && options.body instanceof FormData;

  const controller = new AbortController();
  const expiry = setTimeout(() => controller.abort(), options.timeoutMs ?? REQUEST_TIMEOUT_MS);

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
        // Deliberately absent for a `FormData`: see `RequestOptions.body`.
        // `fetch` then writes `multipart/form-data` with the boundary it
        // generated, which is the only value that can be right.
        headers: hasBody && !isFormData ? { 'content-type': 'application/json' } : undefined,
        // Passed through unstringified. `JSON.stringify(formData)` is `'{}'` —
        // not an error, just an empty object — so a body of files would arrive
        // as nothing at all with every type check satisfied.
        body: hasBody
          ? isFormData
            ? (options.body as FormData)
            : JSON.stringify(options.body)
          : undefined,
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
      // Keyed on the **status**, not on the envelope's code, and told before
      // either throw below. A 401 answered by a proxy or a gateway — HTML, an
      // empty body, anything that is not the shared envelope — is still the
      // server refusing the cookie, and reading the code first would let
      // exactly that case leave the shell rendering over a dead session: the
      // one failure this observer exists to catch.
      //
      // Still only a real answer from the network. A timeout or an unreachable
      // server never reaches this line — both throw out of the `fetch` above —
      // so a dropped connection cannot sign anyone out.
      if (response.status === HTTP_UNAUTHORIZED) notifyUnauthorized();

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
