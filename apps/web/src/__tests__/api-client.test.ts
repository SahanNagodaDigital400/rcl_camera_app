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
  STREAM_IDLE_TIMEOUT_MS,
  UPLOAD_TIMEOUT_MS,
  TIMEOUT,
  apiRequest,
  apiStream,
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

/**
 * A `fetch` answering `200` with a body a test drives chunk by chunk.
 *
 * Returns the handles: `push` writes one chunk, `close` ends the body, and
 * `cancelled` records whether the reader cancelled the stream — which is how
 * "an early exit stops the server" is observable at all, since nothing else
 * about it changes on this side.
 */
function stubStream(): {
  push: (text: string) => void;
  /** One chunk as raw bytes, for the case where a character straddles two. */
  pushBytes: (bytes: Uint8Array) => void;
  close: () => void;
  cancelled: () => boolean;
  aborted: () => boolean;
} {
  interface Pending {
    resolve: (value: ReadableStreamReadResult<Uint8Array>) => void;
    reject: (reason: unknown) => void;
  }
  const waiting: Pending[] = [];
  const queued: ReadableStreamReadResult<Uint8Array>[] = [];
  let cancelled = false;
  let signal: AbortSignal | null = null;

  function settle(chunk: ReadableStreamReadResult<Uint8Array>): void {
    const next = waiting.shift();
    if (next) next.resolve(chunk);
    else queued.push(chunk);
  }

  const reader = {
    read: () =>
      new Promise<ReadableStreamReadResult<Uint8Array>>((resolve, reject) => {
        const ready = queued.shift();
        if (ready) resolve(ready);
        else waiting.push({ resolve, reject });
      }),
    cancel: () => {
      cancelled = true;
      return Promise.resolve();
    },
    releaseLock: () => undefined,
  };

  vi.stubGlobal('fetch', (_url: string, init: RequestInit = {}) => {
    signal = init.signal ?? null;
    // A real body rejects its pending read when the request is aborted, and
    // a stub that did not would make an abandoned stream simply hang — which
    // is the behaviour the idle clock exists to prevent and would make the
    // test for it pass by never finishing.
    signal?.addEventListener('abort', () => {
      while (waiting.length > 0) {
        waiting.shift()?.reject(new DOMException('The operation was aborted.', 'AbortError'));
      }
    });
    return Promise.resolve({
      ok: true,
      status: 200,
      body: { getReader: () => reader },
    } as unknown as Response);
  });

  return {
    push: (text: string) => settle({ done: false, value: new TextEncoder().encode(text) }),
    pushBytes: (bytes: Uint8Array) => settle({ done: false, value: bytes }),
    close: () => settle({ done: true, value: undefined }),
    cancelled: () => cancelled,
    aborted: () => signal?.aborted ?? false,
  };
}

describe('the streamed report', () => {
  it('stays alive as long as chunks keep arriving, however long the batch runs', async () => {
    // **The bound is idle, not total, and this is the difference.** A hundred
    // rows of 16 forward passes each (AD-13) is comfortably an hour; any total
    // bound generous enough for that is no bound at all for a hung stream. So
    // the clock measures the gap between chunks, and a batch that is still
    // producing rows is a batch that is working.
    vi.useFakeTimers();
    const stream = stubStream();
    const seen: unknown[] = [];

    const done = apiStream('/admin/tiles/bulk', { method: 'POST' }, (line) => {
      seen.push(line);
    }).then(
      () => 'resolved',
      (failure: unknown) => (failure instanceof ApiRequestError ? failure.code : 'other'),
    );

    // Six rows, each arriving just inside the window — six times the bound in
    // total elapsed time, and never once idle for a whole one.
    for (let row = 1; row <= 6; row += 1) {
      // eslint-disable-next-line no-await-in-loop -- the chunks are sequential by construction
      await vi.advanceTimersByTimeAsync(STREAM_IDLE_TIMEOUT_MS - 1000);
      stream.push(`{"kind":"row","row":${row}}\n`);
      // eslint-disable-next-line no-await-in-loop -- let the reader drain it
      await vi.advanceTimersByTimeAsync(0);
    }
    stream.push('{"kind":"summary","created":6,"flagged":0,"failed":0}\n');
    await vi.advanceTimersByTimeAsync(0);
    stream.close();

    expect(await done).toBe('resolved');
    expect(seen).toHaveLength(7);
  });

  it('gives up on a stream that goes silent past the bound', async () => {
    vi.useFakeTimers();
    const stream = stubStream();

    const code = apiStream('/admin/tiles/bulk', { method: 'POST' }, () => undefined).then(
      () => 'resolved',
      (failure: unknown) => (failure instanceof ApiRequestError ? failure.code : 'other'),
    );

    stream.push('{"kind":"row","row":1}\n');
    await vi.advanceTimersByTimeAsync(0);
    // And then nothing at all. A batch that has stopped answering is the
    // failure the clock exists for, and it is bounded by one row's worth of
    // silence rather than by the batch's whole length.
    await vi.advanceTimersByTimeAsync(STREAM_IDLE_TIMEOUT_MS);

    expect(await code).toBe(TIMEOUT);
  });

  it('does not run the upload itself under the idle clock', async () => {
    // The clock is armed before `fetch`, because nothing else can bound a
    // connection that never opens — but everything between arming it and the
    // response headers is the *request* going out, which for a bulk batch is a
    // hundred reference images and no chunks coming back. Unrestarted at the
    // headers, a large upload is aborted mid-transfer and reported as an
    // unreachable server.
    vi.useFakeTimers();
    // Held in an array rather than a `let`: the assignment happens inside a
    // callback, and TypeScript's flow analysis narrows a `let` the compiler
    // never sees written to `null` and then refuses to call it.
    const answer: ((response: Response) => void)[] = [];
    const reader = {
      read: () => Promise.resolve({ done: true, value: undefined }),
      cancel: () => Promise.resolve(),
      releaseLock: () => undefined,
    };
    vi.stubGlobal(
      'fetch',
      (_url: string, init: RequestInit = {}) =>
        new Promise<Response>((resolve, reject) => {
          answer.push(resolve);
          init.signal?.addEventListener('abort', () => {
            reject(new DOMException('The operation was aborted.', 'AbortError'));
          });
        }),
    );

    const outcome = apiStream('/admin/tiles/bulk', { method: 'POST' }, () => undefined).then(
      () => 'resolved',
      (failure: unknown) => (failure instanceof ApiRequestError ? failure.code : 'other'),
    );

    // The headers arrive with almost no window left; the upload before them is
    // what took the time.
    await vi.advanceTimersByTimeAsync(STREAM_IDLE_TIMEOUT_MS - 1);
    answer[0]?.({
      ok: true,
      status: 200,
      body: { getReader: () => reader },
    } as unknown as Response);
    await vi.advanceTimersByTimeAsync(0);

    // Restarted at the headers, so the millisecond that was left does not end
    // the batch.
    await vi.advanceTimersByTimeAsync(2);

    expect(await outcome).toBe('resolved');
  });

  it('joins a line split across two chunks, and splits a chunk carrying two', async () => {
    // **The reason this function buffers at all.** Every other test here hands
    // the reader exactly one whole line per chunk, which is the one thing a
    // real network never promises: a chunk boundary falls wherever the network
    // puts it. Drop the carry-over and a report line split mid-object reaches
    // `JSON.parse` as two fragments, the batch dies as `malformed_response`,
    // and every other assertion in this file still passes.
    vi.useFakeTimers();
    const stream = stubStream();
    const seen: unknown[] = [];

    const done = apiStream('/admin/tiles/bulk', { method: 'POST' }, (line) => {
      seen.push(line);
    }).then(
      () => 'resolved',
      (failure: unknown) => (failure instanceof ApiRequestError ? failure.code : 'other'),
    );

    // One line arriving in three pieces, then two lines arriving in one.
    stream.push('{"kind":"row","ro');
    await vi.advanceTimersByTimeAsync(0);
    expect(seen).toEqual([]);
    stream.push('w":1,"file":"caf');
    await vi.advanceTimersByTimeAsync(0);
    stream.push('é.jpg"}\n{"kind":"row","row":2}\n{"kind":"summary","created":2}\n');
    await vi.advanceTimersByTimeAsync(0);
    stream.close();

    expect(await done).toBe('resolved');
    expect(seen).toEqual([
      { kind: 'row', row: 1, file: 'café.jpg' },
      { kind: 'row', row: 2 },
      { kind: 'summary', created: 2 },
    ]);
  });

  it('holds a multi-byte character split across two chunks', async () => {
    // `{ stream: true }` on the decode is what makes this work: the two bytes
    // of `é` arriving in different chunks decode to a replacement character
    // without it, and a file name is what an Administrator matches against the
    // sheet in front of them.
    vi.useFakeTimers();
    const stream = stubStream();
    const seen: unknown[] = [];

    const done = apiStream('/admin/tiles/bulk', { method: 'POST' }, (line) => {
      seen.push(line);
    }).then(
      () => 'resolved',
      (failure: unknown) => (failure instanceof ApiRequestError ? failure.code : 'other'),
    );

    const whole = new TextEncoder().encode('{"kind":"row","file":"café.jpg"}\n');
    const split = whole.indexOf(0xc3);
    expect(split).toBeGreaterThan(0);
    stream.pushBytes(whole.slice(0, split + 1));
    await vi.advanceTimersByTimeAsync(0);
    stream.pushBytes(whole.slice(split + 1));
    await vi.advanceTimersByTimeAsync(0);
    stream.close();

    expect(await done).toBe('resolved');
    expect(seen).toEqual([{ kind: 'row', file: 'café.jpg' }]);
  });

  it('cancels the body and aborts when a line is refused', async () => {
    // A malformed line — or a caller whose narrowing refuses one — leaves a
    // batch that may still have ninety rows to process. Releasing the reader's
    // lock is not enough: the server goes on producing them into a connection
    // nobody is draining, with the idle clock cleared so nothing will end it.
    vi.useFakeTimers();
    const stream = stubStream();

    const code = apiStream('/admin/tiles/bulk', { method: 'POST' }, () => undefined).then(
      () => 'resolved',
      (failure: unknown) => (failure instanceof ApiRequestError ? failure.code : 'other'),
    );

    stream.push('this is not json\n');
    await vi.advanceTimersByTimeAsync(0);

    expect(await code).toBe(MALFORMED_RESPONSE);
    expect(stream.cancelled()).toBe(true);
    expect(stream.aborted()).toBe(true);
  });

  it('lets the caller’s own rejection through rather than relabelling it', async () => {
    // The `try` in `deliver` covers the parse and nothing else. Wrapped around
    // the callback too, a caller's own narrowing failure would come back as
    // this module's "unexpected response" and the screen would state the wrong
    // reason for it.
    vi.useFakeTimers();
    const stream = stubStream();

    const code = apiStream('/admin/tiles/bulk', { method: 'POST' }, () => {
      throw new ApiRequestError('mine', 'The caller refused this line.', 200);
    }).then(
      () => 'resolved',
      (failure: unknown) => (failure instanceof ApiRequestError ? failure.code : 'other'),
    );

    stream.push('{"kind":"row"}\n');
    await vi.advanceTimersByTimeAsync(0);

    expect(await code).toBe('mine');
    expect(stream.cancelled()).toBe(true);
  });

  it('refuses before the stream with a real envelope, and tells the observer on a 401', async () => {
    // The status is committed at the first byte, so everything refusable — the
    // manifest, the row cap, a missing model artifact — is answered as an
    // ordinary envelope. A 401 among them is the session ending, and it has to
    // reach the one observer that knows what to do about it; every other test
    // of that hook drives `apiRequest`, so this path had nothing holding it.
    const told: string[] = [];
    const deregister = onUnauthorized(() => told.push('session ended'));
    try {
      stubReply(401, { error: { code: 'unauthorized', message: 'Not signed in.' } });

      const code = await apiStream('/admin/tiles/bulk', { method: 'POST' }, () => undefined).then(
        () => 'resolved',
        (failure: unknown) => (failure instanceof ApiRequestError ? failure.code : 'other'),
      );

      expect(code).toBe('unauthorized');
      expect(told).toEqual(['session ended']);
    } finally {
      deregister();
    }
  });

  it('reads the whole body when the runtime has no streams', async () => {
    // jsdom's `fetch` is a stub with no `ReadableStream` at all. The fallback
    // paints every row at once — a worse experience and an identical outcome,
    // which is the right trade for a test environment.
    vi.stubGlobal('fetch', () =>
      Promise.resolve({
        ok: true,
        status: 200,
        body: undefined,
        text: () =>
          Promise.resolve('{"kind":"row","row":1}\n{"kind":"summary","created":1}\n'),
      } as unknown as Response),
    );
    const seen: unknown[] = [];

    await apiStream('/admin/tiles/bulk', { method: 'POST' }, (line) => {
      seen.push(line);
    });

    expect(seen).toHaveLength(2);
  });

  it('does not put a total bound on the fallback path either', async () => {
    // The fallback awaits the *whole* body, so a clock left running across it
    // is a total bound wearing an idle bound's name — and it would abort the
    // very batches this function exists for. Disarmed before the await, there
    // is no timer left to fire.
    vi.useFakeTimers();
    const finish: ((text: string) => void)[] = [];
    vi.stubGlobal('fetch', () =>
      Promise.resolve({
        ok: true,
        status: 200,
        body: undefined,
        text: () =>
          new Promise<string>((resolve) => {
            finish.push(resolve);
          }),
      } as unknown as Response),
    );

    const outcome = apiStream('/admin/tiles/bulk', { method: 'POST' }, () => undefined).then(
      () => 'resolved',
      (failure: unknown) => (failure instanceof ApiRequestError ? failure.code : 'other'),
    );

    await vi.advanceTimersByTimeAsync(STREAM_IDLE_TIMEOUT_MS * 3);
    expect(vi.getTimerCount()).toBe(0);

    finish[0]?.('{"kind":"summary","created":0,"flagged":0,"failed":0}\n');

    expect(await outcome).toBe('resolved');
  });
});
