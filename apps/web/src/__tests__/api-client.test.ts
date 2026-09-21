/**
 * @vitest-environment node
 *
 * The one place `apps/web` knows how to reach `apps/api`, tested on its own.
 *
 * The timeout is the reason this file exists. A request that never settles —
 * a hung reverse proxy, a captive portal that swallows the connection — leaves
 * the bootstrap on "Checking your session…" with no error, no login screen and
 * nothing the user can do, and no render test can see that because nothing
 * ever changes on screen.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';

import {
  ACCOUNT_LOCKED,
  API_PREFIX,
  ApiRequestError,
  MALFORMED_RESPONSE,
  NETWORK_ERROR,
  REQUEST_TIMEOUT_MS,
  UPLOAD_TIMEOUT_MS,
  TIMEOUT,
  apiRequest,
  onUnauthorized,
} from '../api/client';

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

/** A `fetch` that never answers, and rejects the way the platform does on abort. */
function stubHangingFetch(): void {
  vi.stubGlobal(
    'fetch',
    (_url: string, init: RequestInit = {}) =>
      new Promise((_resolve, reject) => {
        init.signal?.addEventListener('abort', () => {
          reject(new DOMException('The operation was aborted.', 'AbortError'));
        });
      }),
  );
}

function stubReply(status: number, body: unknown): void {
  vi.stubGlobal('fetch', () =>
    Promise.resolve({
      ok: status >= 200 && status < 300,
      status,
      json: () => Promise.resolve(body),
    } as Response),
  );
}

describe('the API client', () => {
  it('gives up on a request that never answers', async () => {
    vi.useFakeTimers();
    stubHangingFetch();

    // The rejection is attached before the clock moves: a rejection with no
    // handler yet fails the run on its own.
    const code = apiRequest('/auth/session').then(
      () => 'resolved',
      (failure: unknown) => (failure instanceof ApiRequestError ? failure.code : 'other'),
    );

    await vi.advanceTimersByTimeAsync(REQUEST_TIMEOUT_MS);

    expect(await code).toBe(TIMEOUT);
  });

  it('waits as long as the caller asked rather than the default', async () => {
    // The catalogue upload makes the server embed every image — 16 forward
    // passes each (AD-13) — so the 15-second default would abort a request
    // the server then commits anyway: a network error on screen for a tile
    // that exists, and a retry that answers `code_already_exists`.
    vi.useFakeTimers();
    stubHangingFetch();

    const code = apiRequest('/admin/tiles', {
      method: 'POST',
      body: 'anything',
      timeoutMs: UPLOAD_TIMEOUT_MS,
    }).then(
      () => 'resolved',
      (failure: unknown) => (failure instanceof ApiRequestError ? failure.code : 'other'),
    );

    // Well past the default, and still waiting.
    await vi.advanceTimersByTimeAsync(REQUEST_TIMEOUT_MS * 2);
    expect(vi.getTimerCount()).toBe(1);

    // Bounded all the same: a request with no timeout at all would hang for
    // ever behind a stalled proxy, which is the failure the default exists
    // for and which a longer bound must not reintroduce.
    await vi.advanceTimersByTimeAsync(UPLOAD_TIMEOUT_MS);
    expect(await code).toBe(TIMEOUT);
  });

  it('bounds the upload generously enough for the worst request the API accepts', () => {
    // Eight images at 16 forward passes each. The number is a judgement, so
    // the guard is on its shape: comfortably longer than the default, and
    // still a bound.
    expect(UPLOAD_TIMEOUT_MS).toBeGreaterThan(REQUEST_TIMEOUT_MS * 10);
    expect(Number.isFinite(UPLOAD_TIMEOUT_MS)).toBe(true);
  });

  it('does not abort a request that answers in time', async () => {
    vi.useFakeTimers();
    stubReply(200, { ok: true });

    await expect(apiRequest('/auth/session')).resolves.toEqual({ ok: true });

    // The timer is cleared on the way out. Left pending it would keep both the
    // timer and its AbortController alive for every request the app ever makes.
    expect(vi.getTimerCount()).toBe(0);
  });

  it('reports an unreachable server distinctly from a timeout', async () => {
    vi.stubGlobal('fetch', () => Promise.reject(new TypeError('Failed to fetch')));

    await expect(apiRequest('/auth/session')).rejects.toMatchObject({ code: NETWORK_ERROR });
  });

  it('carries the API error envelope through as a typed failure', async () => {
    stubReply(401, { error: { code: 'unauthorized', message: 'Not signed in.' } });

    await expect(apiRequest('/auth/session')).rejects.toMatchObject({
      code: 'unauthorized',
      message: 'Not signed in.',
      status: 401,
    });
  });

  it('refuses a failure body that is not the shared envelope', async () => {
    // A proxy or a gateway answering in the API's place. Rendered as an empty
    // message otherwise.
    stubReply(502, '<html>Bad Gateway</html>');

    await expect(apiRequest('/auth/session')).rejects.toMatchObject({
      code: MALFORMED_RESPONSE,
    });
  });

  it('refuses a success whose body is not JSON at all', async () => {
    // A truncated stream, or a proxy's own HTML served under a 200. Reported as
    // `null` before, which the caller reads as an empty success — "no user"
    // rather than "the server is broken" — and which the module's own comment
    // claimed was already handled by the envelope check below it. That check
    // only runs on a failure.
    vi.stubGlobal('fetch', () =>
      Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.reject(new SyntaxError('Unexpected token < in JSON')),
      } as unknown as Response),
    );

    await expect(apiRequest('/auth/session')).rejects.toMatchObject({
      code: MALFORMED_RESPONSE,
      status: 200,
    });
  });

  it('returns nothing for a 204 rather than trying to parse it', async () => {
    vi.stubGlobal('fetch', () =>
      Promise.resolve({
        ok: true,
        status: 204,
        json: () => Promise.reject(new SyntaxError('Unexpected end of JSON input')),
      } as unknown as Response),
    );

    await expect(apiRequest('/auth/logout', { method: 'POST' })).resolves.toBeNull();
  });

  it('gives up on a response whose body never finishes arriving', async () => {
    // The headers land, the stream then stalls — a hung proxy, a captive
    // portal, a connection dropped mid-body. A timer cleared when `fetch`
    // resolves leaves this half of the request unguarded, and the bootstrap
    // sits on "Checking your session…" forever with nothing on screen to say so.
    vi.useFakeTimers();
    vi.stubGlobal('fetch', (_url: string, init: RequestInit = {}) =>
      Promise.resolve({
        ok: true,
        status: 200,
        json: () =>
          new Promise((_resolve, reject) => {
            init.signal?.addEventListener('abort', () => {
              reject(new DOMException('The operation was aborted.', 'AbortError'));
            });
          }),
      } as unknown as Response),
    );

    const code = apiRequest('/auth/session').then(
      () => 'resolved',
      (failure: unknown) => (failure instanceof ApiRequestError ? failure.code : 'other'),
    );

    await vi.advanceTimersByTimeAsync(REQUEST_TIMEOUT_MS);

    expect(await code).toBe(TIMEOUT);
    expect(vi.getTimerCount()).toBe(0);
  });

  it('declares the body it sends as JSON', async () => {
    // The API's request model refuses anything else: without this header
    // `fetch` labels a string body `text/plain` and every sign-in comes back
    // 422, with the login screen reporting a malformed request the user cannot
    // do anything about.
    const seen: RequestInit[] = [];
    vi.stubGlobal('fetch', (_url: string, init: RequestInit = {}) => {
      seen.push(init);
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({}) } as Response);
    });

    await apiRequest('/auth/login', { method: 'POST', body: { email: 'a@b.lk' } });

    expect(seen[0]?.headers).toEqual({ 'content-type': 'application/json' });
  });

  it('does not treat a lockout as the session ending', async () => {
    // FR-4's refusal is a 429, and the session observer keys off the **401
    // status** — deliberately, so a proxy answering 401 with its own HTML still
    // counts. Widen that condition to `!response.ok`, or key it off the
    // envelope code, and a locked-out staff member sees the shell drop to
    // "Your session has ended" over a session that is perfectly alive, with
    // their typed password wiped by a notice that is simply untrue.
    //
    // `client.ts`'s comment on `ACCOUNT_LOCKED` makes exactly this claim; this
    // is what holds it.
    const told: string[] = [];
    const deregister = onUnauthorized(() => told.push('session ended'));
    stubReply(429, {
      error: { code: ACCOUNT_LOCKED, message: 'This account is temporarily locked.' },
    });

    try {
      const code = await apiRequest('/auth/login', {
        method: 'POST',
        body: { email: 'a@b.lk', password: 'x' },
      }).then(
        () => 'resolved',
        (failure: unknown) => (failure instanceof ApiRequestError ? failure.code : 'other'),
      );

      // The caller still gets its own rejection, carrying the API's code...
      expect(code).toBe(ACCOUNT_LOCKED);
      // ...and nothing was told the session ended.
      expect(told).toEqual([]);
    } finally {
      deregister();
    }
  });

  it('still tells the observer when a 401 arrives', async () => {
    // The other half of the pair. Without it, the test above passes if the
    // observer is deleted outright.
    const told: string[] = [];
    const deregister = onUnauthorized(() => told.push('session ended'));
    stubReply(401, { error: { code: 'unauthorized', message: 'Not signed in.' } });

    try {
      await apiRequest('/auth/session').catch(() => undefined);

      expect(told).toEqual(['session ended']);
    } finally {
      deregister();
    }
  });

  it('sends every request to the API behind its one prefix', async () => {
    const seen: string[] = [];
    vi.stubGlobal('fetch', (url: string) => {
      seen.push(url);
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({}) } as Response);
    });

    await apiRequest('/auth/session');

    expect(seen).toEqual([`${API_PREFIX}/auth/session`]);
  });
});
