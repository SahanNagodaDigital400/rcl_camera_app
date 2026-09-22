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
import { isScanCandidate } from '@rocell/schema/scan';
import type { ScanCandidate } from '@rocell/schema/scan';

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
 * The envelope code for a catalogue search `GET /admin/tiles` will not run.
 *
 * A `422`, and **not** `INVALID_CODE`: a query is not a Code. A blank one is
 * legal and browses the whole catalogue (EXPERIENCE.md line 35), so the only
 * two ways to earn this are a query longer than any Code can be or one
 * carrying a control character — the second of which would otherwise surface
 * as a `500` from the driver rather than as a refusal.
 *
 * Rendered by `CatalogueScreen` in the server's own words, in its one alert
 * slot, beside `Try again`. The client runs no length or character check of
 * its own: the server owns the rule, and a second copy here would be a second
 * set of answers about what a search is.
 */
export const INVALID_QUERY = 'invalid_query';

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
 * The envelope code for a crop rectangle `POST /scans` refuses to apply.
 *
 * Zero or negative width/height, an origin outside `[0, 1)`, or a rectangle
 * that extends past the image's far edge — `shared_vision.crop_to_rect`'s own
 * three conditions (AD-11). Marks nothing on `CropScreen`: the rectangle it
 * sends is computed straight from the drag state the screen already keeps
 * inside the image's own bounds, so a caller that sees this has a bug in that
 * translation rather than a selection to fix by hand.
 */
export const INVALID_CROP_RECT = 'invalid_crop_rect';

/**
 * The envelope code for a cropped scan that scored below the quality gate.
 *
 * FR-9 / AD-12: the check runs on `POST /scans`' own cropped region, after
 * `crop_to_rect` succeeds — a rectangle can be perfectly valid and still
 * enclose a blurry or poorly-framed photo. `CropScreen` recognises this code
 * and swaps its actions for a single "Retake" rather than leaving Confirm
 * live for a resubmission of the same photo, which could only fail again.
 */
export const SCAN_QUALITY_TOO_LOW = 'scan_quality_too_low';

/**
 * The envelope code for "this account has submitted too many scans recently".
 *
 * Story 3.6 / FR-23, AD-8's per-user counter. A `429`, and like `ACCOUNT_LOCKED`
 * it carries no timing information for the client to render — EXPERIENCE.md's
 * plain "temporarily paused" wording, with no countdown. Unlike the login
 * lockout there is no `Retry-After` either: neither FR-23 nor epics.md 3.6 ask
 * for one, so `CropScreen` has nothing to read but the server's own sentence.
 */
export const SCAN_RATE_LIMITED = 'scan_rate_limited';

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

/**
 * The envelope code for "no tile has that id, or that code".
 *
 * A `404` from `GET /admin/tiles/lookup`, from `PATCH /admin/tiles/{id}` and
 * from `DELETE /admin/tiles/{id}`, and it marks **no field**: on the lookup the
 * Code the Administrator typed is a perfectly well-formed Code that nothing
 * holds, and on the edit and the removal the id came from this app rather than
 * from them. The API's own sentence says the tile may have been renamed or
 * removed, which is the thing they can act on.
 *
 * The lookup is an **exact** match, so this is also the answer to a partial
 * Code. Substring search is Story 2.5's catalogue list, not this route.
 */
export const TILE_NOT_FOUND = 'tile_not_found';

/**
 * The envelope code for an edit that would leave a tile with no reference image.
 *
 * Marks the **reference images** region. A `409`: nothing is wrong with the
 * caller's authority and nothing about the session changes. A tile without a
 * reference image is a catalogue row no member of staff can verify and no scan
 * can return (FR-7) — so the API's sentence names the way through, which is to
 * send the replacement in the same save.
 */
export const LAST_REFERENCE_IMAGE = 'last_reference_image';

/**
 * The envelope code for a manifest `POST /admin/tiles/bulk` cannot read.
 *
 * Missing, empty, not a CSV, without a header row, without a data row, or
 * missing a required column. Marks the **sheet** control, and it is one of the
 * refusals that arrive *before* the stream opens — so it is a real envelope
 * under a `422`, and the screen renders the server's own sentence, which names
 * the fix ("Export the sheet as CSV and upload that.") rather than describing
 * the problem.
 *
 * The client never parses the manifest to pre-empt this. The server owns every
 * rule about what a row is, and a second parser here would be a second set of
 * answers about which rows a batch has.
 */
export const INVALID_MANIFEST = 'invalid_manifest';

/**
 * The envelope code for a manifest carrying more rows than the endpoint takes.
 *
 * A `422`, marking the **sheet** control, and pre-stream like the one above:
 * the rows are counted before a single image is read, so nothing is written and
 * no row is reported. The screen refuses an over-long batch before uploading
 * it as well (see `MAX_BULK_ROWS`), which is about not sending gigabytes — this
 * is the server's own bound and the one that decides.
 */
export const TOO_MANY_ROWS = 'too_many_rows';

/**
 * The per-row code for a manifest row whose image was not uploaded.
 *
 * **Never an envelope.** This and the three below arrive inside a report line's
 * `error` object, which reuses the envelope's `{code, message}` shape so a
 * per-row failure reads the same as any other refusal. The status is already
 * `200` by the time a row is reported, which is why they are codes and not
 * statuses.
 *
 * Also the answer when two uploads share the file name a row names — the
 * message says which, because the Administrator's fix is different in each
 * case: send the missing file, or rename one of the two.
 */
export const IMAGE_NOT_PAIRED = 'image_not_paired';

/**
 * The per-row code for an uploaded image no manifest row names.
 *
 * Reported on a trailing line keyed by the file name rather than by a row
 * number, because there is no row — which is the whole point of reporting it.
 * An upload silently ignored is an image the Administrator believes is in the
 * catalogue and is not, and that is a defect nobody finds until a Scan fails
 * to return it.
 */
export const IMAGE_UNMATCHED = 'image_unmatched';

/**
 * The per-row code for a row that failed in a way nothing anticipated.
 *
 * The catch-all, carrying a fixed sentence that leaks nothing: the exception is
 * logged server-side and the batch continues. It exists so that one unexpected
 * row cannot tear the stream down and take every later row's outcome with it —
 * the report is the deliverable, and a report that stops halfway tells an
 * Administrator nothing about the rows it never reached.
 */
export const ROW_FAILED = 'row_failed';

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
 * The rejection a non-`ok` response becomes — told the observer on the way.
 *
 * Extracted so that `apiRequest` and `apiStream` cannot disagree about what a
 * refusal is. They differ in everything about the *success* path and in nothing
 * about this one: the same statuses, the same envelope, the same 401 hook, and
 * a stream that is refused before its first byte is refused exactly as an
 * ordinary request is.
 *
 * `body` is whatever the caller managed to parse, which may be `null` when the
 * response was not JSON at all — a proxy or a gateway answering in the API's
 * place, reported as such rather than rendered as an empty message.
 */
function refusal(response: Response, body: unknown): ApiRequestError {
  // Keyed on the **status**, not on the envelope's code, and told before
  // either return below. A 401 answered by a proxy or a gateway — HTML, an
  // empty body, anything that is not the shared envelope — is still the
  // server refusing the cookie, and reading the code first would let exactly
  // that case leave the shell rendering over a dead session: the one failure
  // this observer exists to catch.
  //
  // Still only a real answer from the network. A timeout or an unreachable
  // server never reaches this line — both throw out of the `fetch` — so a
  // dropped connection cannot sign anyone out.
  if (response.status === HTTP_UNAUTHORIZED) notifyUnauthorized();

  // Every error this API produces is the shared envelope, so anything else is
  // a proxy or a gateway answering in its place.
  if (isErrorEnvelope(body)) {
    return new ApiRequestError(body.error.code, body.error.message, response.status);
  }
  return new ApiRequestError(
    MALFORMED_RESPONSE,
    'The server returned an unexpected response.',
    response.status,
  );
}

/**
 * Send one request and return its parsed body, or throw an `ApiRequestError`.
 *
 * A `204` returns `null` — there is nothing to return, and parsing that body
 * as JSON would throw where nothing is wrong. `POST /scans` (Story 3.2)
 * answered `202` with an empty body for the same reason before Story 3.4 gave
 * it a real one; it now resolves the match before answering and returns `200`
 * with a body like every other synchronous route, so this shortcut no longer
 * applies to it.
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

    if (response.status === 204 || response.status === 202) return null;

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

    // See `refusal`: the observer, the envelope and the proxy case, in the one
    // copy `apiStream` shares.
    if (!response.ok) throw refusal(response, body);

    return body;
  } finally {
    // Cleared whatever happened: a pending timer holding an AbortController
    // keeps both alive, and in a test it keeps the event loop alive too.
    clearTimeout(expiry);
  }
}

/**
 * `CropScreen`'s confirmed selection, normalized 0-1 against the *uploaded*
 * image's own width/height — never absolute pixels (AD-11).
 */
export interface NormalizedCropRect {
  x: number;
  y: number;
  width: number;
  height: number;
}

/**
 * Narrow the response body to an array of the shared `ScanCandidate`, or fail
 * loudly.
 *
 * `CatalogueScreen.asTiles`'s shape, per element: `isScanCandidate` rejects a
 * missing key, a malformed UUID — and any extra key, which is how a `score`
 * (AD-20) or a storage reference (AD-9) would announce itself rather than
 * being quietly ignored. A partially-understood body must not be rendered as
 * a Result: a candidate this screen could not parse is a match a member of
 * staff would never know to look for.
 */
function asScanCandidates(body: unknown): ScanCandidate[] {
  if (Array.isArray(body)) {
    const rows: unknown[] = body;
    if (rows.every(isScanCandidate)) return rows;
  }
  throw new ApiRequestError(MALFORMED_RESPONSE, 'The server returned an unexpected response.', 200);
}

/**
 * Send the Crop screen's confirmed selection to the server, crop it there,
 * match it against the catalogue, and return the ranked Candidates.
 *
 * `CropScreen`'s own submission path (Stories 3.2-3.4, AD-11): the request
 * carries the same downscaled image `ScanScreen` produced, unmodified, plus
 * the on-screen selection expressed as a fraction of that image's own pixel
 * dimensions — never a pixel rectangle, and never an image already cropped on
 * this side. The pixel crop itself runs exactly once, server-side, in
 * `shared_vision`.
 *
 * A `FormData`, `AddTileScreen`'s own reason: the body carries a file, and
 * only `fetch` — never this module — may set the multipart boundary that
 * delimits its parts. `UPLOAD_TIMEOUT_MS`, not the default: intake decodes,
 * colour-manages, re-encodes and now matches the image server-side, which the
 * 15s default is sized wrong for in exactly the way it is wrong for
 * `POST /admin/tiles`.
 *
 * Resolves to up to three ranked Candidates, or an empty array when nothing
 * in the catalogue matched — never a similarity value, and never more than
 * three (AD-20). `POST /scans` answers `200` now, not the old `202`: the
 * request fully resolves the match before answering, so this no longer takes
 * `apiRequest`'s `204`/`202` shortcut and reads a real body instead.
 */
export async function submitScan(
  image: Blob,
  rect: NormalizedCropRect,
): Promise<ScanCandidate[]> {
  const body = new FormData();
  body.append('image', image, 'scan.jpg');
  body.append('crop_x', String(rect.x));
  body.append('crop_y', String(rect.y));
  body.append('crop_width', String(rect.width));
  body.append('crop_height', String(rect.height));
  return asScanCandidates(
    await apiRequest('/scans', { method: 'POST', body, timeoutMs: UPLOAD_TIMEOUT_MS }),
  );
}

/**
 * How long a stream may go without a byte before it is abandoned.
 *
 * **Idle, not total, and that distinction is the whole reason this constant is
 * not `UPLOAD_TIMEOUT_MS`.** A bulk batch is N rows of 16 forward passes each
 * (AD-13), processed one at a time — a hundred rows is comfortably an hour, and
 * any total bound generous enough for the largest batch is no bound at all for
 * a hung one. What a stalled stream actually looks like is silence: the rows
 * stop arriving. So the clock measures the gap between chunks and is restarted
 * by every one of them, which makes a batch that is *working* unbounded and a
 * batch that has stopped answering bounded by the time one row takes.
 *
 * Sized for the worst single row — a 96 MB CMYK press file, colour-managed,
 * embedded sixteen times — with room for a slower machine than this one.
 */
export const STREAM_IDLE_TIMEOUT_MS = 180000;

interface StreamOptions {
  method?: string;
  /** As `RequestOptions.body`: a `FormData` is sent as it is, anything else JSON. */
  body?: unknown;
  /**
   * How long to wait **between chunks** before aborting, in milliseconds.
   *
   * Defaults to `STREAM_IDLE_TIMEOUT_MS`. Not a bound on the whole request —
   * see that constant for why a streamed report cannot have one.
   */
  idleTimeoutMs?: number;
  /**
   * A caller's own abort, linked to this request's.
   *
   * For the one case the idle clock cannot cover: the screen reading the
   * report going away — unmounted by a sign-out, a session loss, or a swap to
   * another surface — while the batch is still running. Nothing is reading the
   * stream after that, and without this the server would go on producing rows
   * into a connection held open by a component that no longer exists.
   *
   * The rejection a caller's abort produces is worded as a timeout, because
   * from inside this function an aborted signal is an aborted signal. That is
   * fine for the case it exists for: whoever aborted is, by definition, no
   * longer rendering the result.
   */
  signal?: AbortSignal;
}

/**
 * Send one request and hand each NDJSON line to `onLine` as it arrives.
 *
 * The sibling of `apiRequest`, and the difference is one line of it:
 * `apiRequest` does `await response.json()`, which does not return until the
 * whole body has arrived. A per-row report delivered that way is a report that
 * appears all at once when the batch ends, which is the single spinner
 * EXPERIENCE.md:94 exists to forbid — so this reads the body incrementally and
 * calls back per complete line.
 *
 * Everything else is shared on purpose: the same `ApiRequestError`, the same
 * `failed()` wording for a timeout or an unreachable server, the same
 * `notifyUnauthorized()` 401 hook, and the same envelope parse for a non-`ok`
 * response (`refusal`). A bulk request refused before its stream opens — no
 * manifest, too many rows, no model artifact, a stale stamp — is refused
 * exactly as any other request is, because until the first byte a real envelope
 * under a real status is still possible.
 *
 * **Nothing is interpreted here.** A line is parsed as JSON and passed on as
 * `unknown`; what a row means, which outcomes exist and which flags are
 * possible are the caller's and ultimately the server's. This function knows
 * about newlines and nothing else.
 *
 * Resolves when the body ends. It does not resolve early on a `summary` line —
 * this layer cannot see one — so a caller that wants to know the batch is over
 * reads that from the line, or from this promise, or both.
 */
export async function apiStream(
  path: string,
  options: StreamOptions,
  onLine: (line: unknown) => void,
): Promise<void> {
  const method = options.method ?? 'GET';
  const hasBody = options.body !== undefined;
  // `typeof` guarded for `apiRequest`'s reason: this module is also read in a
  // node test environment where `FormData` may not be defined at all.
  const isFormData = typeof FormData !== 'undefined' && options.body instanceof FormData;
  const idle = options.idleTimeoutMs ?? STREAM_IDLE_TIMEOUT_MS;

  const controller = new AbortController();
  let expiry = setTimeout(() => controller.abort(), idle);

  // The caller's abort, forwarded to this request's. Checked first as well as
  // subscribed to: a signal that was already aborted fires no event, and a
  // request started after the caller gave up must not run.
  if (options.signal !== undefined) {
    if (options.signal.aborted) controller.abort();
    else options.signal.addEventListener('abort', () => controller.abort(), { once: true });
  }

  /** Restart the idle clock. Called by every chunk — see `STREAM_IDLE_TIMEOUT_MS`. */
  function stillAlive(): void {
    clearTimeout(expiry);
    expiry = setTimeout(() => controller.abort(), idle);
  }

  /**
   * Parse one complete line and hand it over. Blank lines are skipped.
   *
   * A line that is not JSON is the server having stopped speaking the protocol
   * mid-stream — a truncated body, or a proxy that injected something. Reported
   * as `malformed_response` rather than skipped, because a report quietly
   * missing a row is a row an Administrator believes landed.
   */
  function deliver(line: string): void {
    const text = line.trim();
    if (text === '') return;

    // **The `try` covers the parse and nothing else.** Wrapped around the
    // callback as well, any rejection the caller raises — its own narrowing of
    // a line it does not recognise, a render that threw — would be caught here
    // and relabelled `malformed_response` with this module's own sentence. The
    // caller's rejection is the more specific one and is the one it wrote, so
    // it propagates untouched.
    let parsed: unknown;
    try {
      parsed = JSON.parse(text);
    } catch {
      throw new ApiRequestError(
        MALFORMED_RESPONSE,
        'The server returned an unexpected response.',
        200,
      );
    }
    onLine(parsed);
  }

  try {
    let response: Response;
    try {
      response = await fetch(`${API_PREFIX}${path}`, {
        method,
        credentials: 'same-origin',
        // Deliberately absent for a `FormData`: only the runtime that built the
        // body knows the boundary token that delimits its parts.
        headers: hasBody && !isFormData ? { 'content-type': 'application/json' } : undefined,
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

    // **The headers restart the clock, and that matters most for an upload.**
    // The timer is armed before `fetch` because nothing else can bound a
    // connection that never opens — but everything between arming it and this
    // line is the *request* going out, which for a bulk batch is a hundred
    // reference images and no chunks coming back to keep the clock alive. Left
    // unrestarted, a large upload is aborted mid-transfer and reported as an
    // unreachable server. This is the first moment there is evidence the far
    // end is answering, so it is where the idle window properly begins.
    stillAlive();

    if (!response.ok) {
      // The refusal path reads the whole body, which is right: a refusal is one
      // envelope and is never streamed. Once the status is `200` every outcome
      // is a row, so this branch is the only place a status other than `200`
      // can be answered at all.
      let body: unknown = null;
      try {
        body = await response.json();
      } catch {
        // An abort here is the same timeout as an abort on the request itself.
        if (controller.signal.aborted) throw failed(controller);
        // Anything else is a body that is not the envelope. `refusal` says so.
      }
      throw refusal(response, body);
    }

    let buffered = '';

    // `response.body` is a `ReadableStream` in a browser and is absent under
    // jsdom, whose `fetch` is a stub that has no streams at all. The fallback
    // reads the whole body and splits it, which paints every row at once — a
    // worse experience and an identical outcome, which is exactly the right
    // trade for a test environment and for any runtime old enough to lack the
    // API. The streaming path is the one that ships.
    const body: unknown = response.body;
    const readable =
      body !== null &&
      body !== undefined &&
      typeof (body as ReadableStream).getReader === 'function'
        ? (body as ReadableStream<Uint8Array>)
        : null;

    if (readable === null) {
      // **Disarmed before the await, not after it.** `response.text()` does
      // not return until the whole batch has finished, so a clock left running
      // across it is a *total* bound wearing an idle bound's name — and it
      // would abort the very batches this function exists for. There are no
      // chunks to restart it on this path, so there is nothing for it to
      // measure: the fallback trades the timeout away along with the
      // row-by-row report, and says so.
      clearTimeout(expiry);
      let whole: string;
      try {
        whole = await response.text();
      } catch {
        throw failed(controller);
      }
      for (const line of whole.split('\n')) deliver(line);
      return;
    }

    const reader = readable.getReader();
    const decoder = new TextDecoder();
    /** Whether the loop reached the end of the body rather than leaving early. */
    let finished = false;

    try {
      for (;;) {
        let chunk: ReadableStreamReadResult<Uint8Array>;
        try {
          // The rule's advice — collect the promises and `Promise.all` them —
          // is exactly what a stream cannot do: the next chunk does not exist
          // until this one has been consumed, and a report that arrives row by
          // row is the entire point of reading it this way (EXPERIENCE.md:94).
          // oxlint-disable-next-line no-await-in-loop
          chunk = await reader.read();
        } catch {
          // A stream that dies mid-flight is the same two cases as a request
          // that never arrived: aborted by the idle clock, or the connection
          // dropped. `failed` tells them apart by the signal.
          throw failed(controller);
        }
        if (chunk.done) break;

        // Every chunk restarts the clock. A batch that is still producing rows
        // is a batch that is working, however long it has been running.
        stillAlive();

        // `{ stream: true }` so a multi-byte character split across two chunks
        // is held until its remaining bytes arrive rather than decoded into a
        // replacement character.
        buffered += decoder.decode(chunk.value, { stream: true });

        // Only *complete* lines. The last element is whatever follows the final
        // newline — a partial line, or an empty string — and is kept for the
        // next chunk, which is the whole reason this function buffers at all.
        const lines = buffered.split('\n');
        buffered = lines.pop() ?? '';
        for (const line of lines) deliver(line);
      }
      finished = true;
    } finally {
      // **An early exit has to stop the server, not just stop reading it.** A
      // malformed line, or a rejection out of `onLine`, leaves a batch that may
      // still have ninety rows to process — and releasing the lock alone leaves
      // it producing them into a connection nobody is draining, with the idle
      // clock cleared below so nothing will ever end it. Cancelling the body
      // and aborting the controller is what closes the connection and lets the
      // server notice.
      if (!finished) {
        // Best effort, and deliberately not awaited: this runs while an
        // exception is on its way out, and a rejection from the cancel would
        // replace the failure the caller is about to be told about.
        void reader.cancel().catch(() => undefined);
        controller.abort();
      }
      // Releases the lock whether the loop ended, threw, or was abandoned by
      // the caller. A stream left locked cannot be cancelled by anything else.
      reader.releaseLock();
    }

    // The tail. A well-formed NDJSON body ends with a newline and this is
    // empty; one that does not still has a last line to report, and losing it
    // would lose the summary.
    buffered += decoder.decode();
    deliver(buffered);
  } finally {
    // Cleared whatever happened: a pending timer holding an AbortController
    // keeps both alive, and in a test it keeps the event loop alive too.
    clearTimeout(expiry);
  }
}
