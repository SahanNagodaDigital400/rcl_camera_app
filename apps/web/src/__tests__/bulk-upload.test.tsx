/**
 * Bulk upload — the screen, the stream it paints, and the route the app takes
 * to reach it.
 *
 * Two halves, driven through two different roots, the way `add-tile.test.tsx`
 * splits them. The screen's own behaviour runs against a stubbed `fetch` with
 * the screen rendered directly, because it calls `apiStream` itself rather than
 * going through `SessionProvider`; whether the app *reaches* the screen at all
 * runs through `App`, because the role condition and the section state live in
 * the gate.
 *
 * The assertions here that nothing else in the suite can make:
 *
 * * **Rows paint as they arrive, not when the batch ends.** The stub hands the
 *   response body out one chunk at a time and this file asserts *between*
 *   chunks — which is the only way to tell a streamed report from one that was
 *   buffered and rendered in a single frame. Every other check in the suite
 *   would pass just as happily against `await response.json()`, which is
 *   exactly the single spinner EXPERIENCE.md:94 forbids. The API suite cannot
 *   make this one: `TestClient` may produce the whole body before the first
 *   read returns, so it holds the stream's *shape* and this file holds its
 *   timing.
 * * **Each outcome carries a word, not only a colour.** `vite.config.ts` sets
 *   `css: false`, so jsdom applies no stylesheet: the colours are held by
 *   `styling-wiring.test.ts` and the words are held here, and neither file can
 *   see the other half. A report that signalled by colour alone would be
 *   invisible to both unless this file reads the text.
 * * **A pre-stream refusal renders the server's sentence and no report.** Once
 *   the stream opens the status is `200` and every outcome is a row, so this is
 *   the only shape of failure that can leave the list absent entirely.
 * * **The client-side refusals ask the server nothing.**
 */
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import App from '../App';
import { BulkUploadScreen } from '../screens/BulkUploadScreen';
import type { User } from '@rocell/schema/user';

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const ADMIN: User = {
  id: '9c2f1e4a-7b3d-4c58-9e10-2a6f8d4b1c07',
  name: 'Nadeesha Silva',
  email: 'nadeesha@rocell.lk',
  role: 'admin',
  active: true,
  must_change_password: false,
  temp_credential_expires_at: null,
  last_login_at: '2026-09-18T08:00:00Z',
  locked_until: null,
  created_at: '2026-09-17T08:00:00Z',
  updated_at: '2026-09-18T08:00:00Z',
};

const STAFF: User = {
  ...ADMIN,
  id: '3f1a6b2c-9d4e-4f70-8a11-5c2e7b9d0a34',
  name: 'Kasun Perera',
  email: 'kasun@rocell.lk',
  role: 'staff',
};

const BULK = '/api/admin/tiles/bulk';

/**
 * The server's own bounds and sentences, restated character for character.
 *
 * Restated rather than imported because nothing crosses that boundary at build
 * time — `error-code-parity.test.ts` pins the codes and the numbers against
 * their Python twins, which is what makes these literals safe to write down
 * here rather than merely convenient.
 */
const MAX_BULK_ROWS = 100;
const MAX_IMAGE_BYTES = 134217728;
const NO_MANIFEST_SENTENCE = 'Export the sheet as CSV and upload that.';

/** One NDJSON line, in the shape the endpoint streams. */
function rowLine(
  row: number,
  file: string,
  status: 'created' | 'flagged' | 'failed',
  extra: Record<string, unknown> = {},
): string {
  return JSON.stringify({
    kind: 'row',
    row,
    file,
    code: file.replace(/\.[a-z]+$/i, ''),
    status,
    tile_id: status === 'failed' ? null : 'b41d8e06-5a72-4f39-9c88-0d3e1f7a2b65',
    flags: [],
    error: null,
    ...extra,
  });
}

function summaryLine(created: number, flagged: number, failed: number): string {
  return JSON.stringify({ kind: 'summary', created, flagged, failed });
}

/** The opening line: how many row lines this report will carry. */
function startLine(total: number): string {
  return JSON.stringify({ kind: 'start', total });
}

/**
 * Replace `fetch` with one that answers a `200` whose body this test drives.
 *
 * A real `ReadableStream`, fed a chunk at a time by the returned `push`, is
 * what makes "rows appear as they complete" assertable: a stub that resolved
 * the whole body at once could not tell a streamed report from a buffered one.
 *
 * `json` and `text` reject deliberately. Both are paths `apiStream` must not
 * take on a `200` with a body — `json` would be the whole-body read this
 * function exists to avoid, and `text` is the no-streams fallback, which is a
 * different test below. Rejecting rather than returning makes a regression into
 * either one a failure here rather than a report that still happens to pass.
 */
function stubStreamingFetch(): {
  calls: [string, RequestInit][];
  push: (line: string) => void;
  close: () => void;
} {
  const calls: [string, RequestInit][] = [];
  const encoder = new TextEncoder();
  let feed: ReadableStreamDefaultController<Uint8Array> | null = null;

  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      feed = controller;
    },
  });

  vi.stubGlobal('fetch', (input: string, init: RequestInit = {}) => {
    calls.push([input, init]);
    return Promise.resolve({
      ok: true,
      status: 200,
      body,
      json: () => Promise.reject(new Error('a streamed body is never read as JSON')),
      text: () => Promise.reject(new Error('a streamed body is never read whole')),
    } as unknown as Response);
  });

  return {
    calls,
    push: (line: string) => feed?.enqueue(encoder.encode(`${line}\n`)),
    close: () => feed?.close(),
  };
}

/** Replace `fetch` with one that answers a refusal envelope, or a whole body. */
function stubFetch(reply: {
  status: number;
  body?: unknown;
  text?: string;
}): { calls: [string, RequestInit][] } {
  const calls: [string, RequestInit][] = [];

  vi.stubGlobal('fetch', (input: string, init: RequestInit = {}) => {
    calls.push([input, init]);
    return Promise.resolve({
      ok: reply.status >= 200 && reply.status < 300,
      status: reply.status,
      // Absent, which is what jsdom's own `fetch` looks like and what sends
      // `apiStream` down its `response.text()` fallback.
      body: undefined,
      json: () => Promise.resolve(reply.body ?? null),
      text: () => Promise.resolve(reply.text ?? ''),
    } as unknown as Response);
  });

  return { calls };
}

/**
 * Answer the session probe with `user`, the Catalogue's browse with an empty
 * catalogue, and every other request with a 404.
 *
 * Two requests matter in this describe since Story 2.5: the gate's own, and the
 * Catalogue's — this screen is reached *through* that surface now, so a browse
 * left answering 404 would put the Catalogue on its failure state and the
 * control this test presses would still be there (it is in the actions row, not
 * in the table) but the test would be driving a screen in the wrong state.
 * Pressing the control opens a screen that asks the server nothing until a
 * batch is submitted.
 */
function stubSession(user: User | null): void {
  vi.stubGlobal('fetch', (input: string, init: RequestInit = {}) => {
    const key = `${init.method ?? 'GET'} ${input}`;
    if (key === 'GET /api/auth/session') {
      return Promise.resolve({
        ok: user !== null,
        status: user === null ? 401 : 200,
        json: () =>
          Promise.resolve(
            user === null ? { error: { code: 'unauthorized', message: 'Not signed in.' } } : user,
          ),
      } as unknown as Response);
    }
    if (key === 'GET /api/admin/tiles?q=') {
      return Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve([]),
      } as unknown as Response);
    }
    return Promise.resolve({
      ok: false,
      status: 404,
      json: () => Promise.resolve({ error: { code: 'not_found', message: 'No such route.' } }),
    } as unknown as Response);
  });
}

function renderScreen(onBack: () => void = (): void => undefined): void {
  render(<BulkUploadScreen onBack={onBack} />);
}

function aSheet(name = 'codes.csv'): File {
  return new File(['file,code,size\nrow-1.jpg,RP.CMA.0001DJ.SM.0T,45X90\n'], name, {
    type: 'text/csv',
  });
}

function anImage(name = 'row-1.jpg', size?: number): File {
  const file = new File([new Uint8Array([1, 2, 3, 4])], name, { type: 'image/jpeg' });
  // `File` computes its own size from the parts, and a test cannot hand it a
  // hundred megabytes. Redefined rather than faked with real bytes, which is
  // the only way to reach the ceiling the screen refuses at.
  if (size !== undefined) Object.defineProperty(file, 'size', { value: size });
  return file;
}

/**
 * An oversized image the device *can* shrink: a real three-channel JPEG header
 * with no profile and no Adobe marker, which is what `shrinkImage` requires
 * before it will re-encode anything. `anImage`'s four arbitrary bytes are not
 * a JPEG at all, and are deliberately left that way — they are the file the
 * screen must refuse.
 */
function aPlainJpeg(name: string, size: number): File {
  const bytes = new Uint8Array([
    // SOI.
    0xff, 0xd8,
    // SOF0, length 8: precision, height, width, and a component count of
    // three — RGB, no profile, nothing an Adobe marker would tag.
    0xff, 0xc0, 0x00, 0x08, 0x08, 0x01, 0x00, 0x01, 0x00, 0x03,
    // SOS, where the marker walk stops.
    0xff, 0xda, 0x00, 0x02,
  ]);
  const file = new File([bytes], name, { type: 'image/jpeg' });
  Object.defineProperty(file, 'size', { value: size });
  return file;
}

/** Stub the decode and canvas steps `shrinkImage` runs. Returns the encoded size. */
function stubRedraw(): number {
  const shrunk = new Blob(['a much smaller press file'], { type: 'image/jpeg' });
  vi.stubGlobal(
    'createImageBitmap',
    vi.fn(() => Promise.resolve({ width: 19276, height: 9638, close: vi.fn() })),
  );
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({
    drawImage: vi.fn(),
  } as unknown as CanvasRenderingContext2D);
  vi.spyOn(HTMLCanvasElement.prototype, 'toBlob').mockImplementation(function toBlob(
    this: HTMLCanvasElement,
    callback: BlobCallback,
  ) {
    callback(shrunk);
  });
  return shrunk.size;
}

function chooseSheet(file: File | null = aSheet()): void {
  fireEvent.change(screen.getByLabelText(/sheet of codes/i), {
    target: { files: file === null ? [] : [file] },
  });
}

function chooseImages(files: File[] = [anImage()]): void {
  fireEvent.change(screen.getByLabelText(/reference images/i), { target: { files } });
}

function submit(): void {
  fireEvent.click(screen.getByRole('button', { name: /^upload$/i }));
}

/** Every role a control on this screen could take. */
const CONTROL_ROLES = [
  'button',
  'link',
  'textbox',
  'searchbox',
  'combobox',
  'listbox',
  'checkbox',
  'radio',
  'switch',
  'slider',
  'spinbutton',
] as const;

/** The report's rows, in document order. */
function reportedRows(): HTMLElement[] {
  return screen.queryAllByRole('listitem');
}

describe('the report streams', () => {
  it('sends a multipart body with exactly the parts the endpoint names', async () => {
    const stream = stubStreamingFetch();
    renderScreen();

    chooseSheet();
    chooseImages([anImage('row-1.jpg'), anImage('row-2.jpg')]);
    submit();

    stream.push(rowLine(1, 'row-1.jpg', 'created'));
    await screen.findByText('row-1.jpg');

    const [path, init] = stream.calls[0] ?? ['', {}];
    expect(path).toBe(BULK);
    expect(init.method).toBe('POST');
    // A `FormData`, not JSON. `JSON.stringify(formData)` is `'{}'` — not an
    // error, just an empty object — so a body of files would arrive as nothing
    // at all with every type check in the app satisfied.
    expect(init.body).toBeInstanceOf(FormData);

    const body = init.body as FormData;
    // As a set, so the assertion is about which parts were sent and not about
    // the order `FormData` happened to keep them in.
    expect(new Set(body.keys())).toEqual(new Set(['manifest', 'images']));
    expect((body.get('manifest') as File).name).toBe('codes.csv');
    expect(body.getAll('images')).toHaveLength(2);

    stream.close();
  });

  it('paints each row as it completes, not when the batch ends', async () => {
    // **The assertion this whole file exists for.** Each chunk is pushed and
    // the report is read *before the next one is pushed*, so a screen that
    // buffered the body and painted once at the end fails here and nowhere
    // else — every other check in this suite would pass against a report
    // rendered in a single frame after the stream closed.
    const stream = stubStreamingFetch();
    renderScreen();

    chooseSheet();
    chooseImages([anImage('row-1.jpg'), anImage('row-2.jpg'), anImage('row-3.jpg')]);
    submit();

    stream.push(rowLine(1, 'row-1.jpg', 'created'));
    await screen.findByText('row-1.jpg');
    expect(reportedRows()).toHaveLength(1);
    // The batch is plainly not over: two of its three rows have not been
    // reported, and the screen is already showing the one that has.
    expect(screen.queryByText('row-2.jpg')).toBeNull();

    stream.push(rowLine(2, 'row-2.jpg', 'flagged', { flags: ['unknown_category'] }));
    await screen.findByText('row-2.jpg');
    expect(reportedRows()).toHaveLength(2);
    expect(screen.queryByText('row-3.jpg')).toBeNull();

    stream.push(rowLine(3, 'row-3.jpg', 'failed', {
      error: { code: 'unreadable_image', message: 'That file is not a readable image.' },
    }));
    await screen.findByText('row-3.jpg');
    expect(reportedRows()).toHaveLength(3);

    // Only now does the batch end, and only now does the report close — which
    // is the other half of the same claim: nothing above waited for this.
    stream.push(summaryLine(1, 1, 1));
    stream.close();
    await screen.findByText(/finished/i);
  });

  it('keeps the rows in the order they arrived', async () => {
    // Never sorted, never grouped and never collapsed by outcome. The order
    // rows arrive in is the order the server processed them in, and an
    // Administrator who watched a row appear must be able to find it where they
    // saw it.
    const stream = stubStreamingFetch();
    renderScreen();

    chooseSheet();
    chooseImages([anImage(), anImage('b.jpg'), anImage('c.jpg')]);
    submit();

    stream.push(rowLine(1, 'c.jpg', 'failed', {
      error: { code: 'unreadable_image', message: 'That file is not a readable image.' },
    }));
    stream.push(rowLine(2, 'a.jpg', 'created'));
    stream.push(rowLine(3, 'b.jpg', 'flagged', { flags: ['low_quality_image'] }));
    await screen.findByText('b.jpg');

    expect(reportedRows().map((row) => row.textContent)).toEqual([
      expect.stringContaining('c.jpg'),
      expect.stringContaining('a.jpg'),
      expect.stringContaining('b.jpg'),
    ]);

    stream.close();
  });

  it.each([
    ['created', 'Added'],
    ['flagged', 'Flagged'],
    ['failed', 'Failed'],
  ] as const)('gives a %s row the word "%s", never colour alone', async (status, word) => {
    // EXPERIENCE.md's accessibility floor: a state is never signalled by colour
    // alone. `vite.config.ts` sets `css: false` so jsdom paints nothing, which
    // means a report relying on its three colours would read here as three
    // identical rows — and to a colour-blind Administrator reading a hundred of
    // them, as very nearly that.
    const stream = stubStreamingFetch();
    renderScreen();

    chooseSheet();
    chooseImages();
    submit();

    stream.push(rowLine(1, 'row-1.jpg', status));
    await screen.findByText('row-1.jpg');

    const [only] = reportedRows();
    expect(only).toBeTruthy();
    expect(within(only!).getByText(word)).toBeTruthy();

    stream.close();
  });

  it('reports a flagged row as added and says what the flag means', async () => {
    // A flagged row *was* created (AD-18): it has a tile id and it is in the
    // index. Reporting it as a failure would send an Administrator to re-upload
    // a tile that is already in the catalogue.
    const stream = stubStreamingFetch();
    renderScreen();

    chooseSheet();
    chooseImages();
    submit();

    stream.push(
      rowLine(1, 'plain.jpg', 'flagged', {
        code: 'RC-001-OHA-156-MA-J2',
        flags: ['unknown_category', 'unknown_face_number'],
      }),
    );
    await screen.findByText('plain.jpg');

    const [only] = reportedRows();
    expect(within(only!).getByText('Flagged')).toBeTruthy();
    expect(within(only!).queryByText('Failed')).toBeNull();
    // Both flags, in the order the server sent them, each as a sentence rather
    // than as the slug it arrived as.
    expect(only!.textContent).toMatch(/UNKNOWN/);
    expect(only!.textContent).toMatch(/no trailing number/i);
    // The Code is on the row: it is the tile's identity and the value an
    // Administrator compares against the sheet in front of them.
    expect(within(only!).getByText('RC-001-OHA-156-MA-J2')).toBeTruthy();

    stream.close();
  });

  it('carries the server’s own sentence on a failed row', async () => {
    const stream = stubStreamingFetch();
    renderScreen();

    chooseSheet();
    chooseImages();
    submit();

    stream.push(
      rowLine(1, 'broken.jpg', 'failed', {
        error: { code: 'unreadable_image', message: 'That file is not a readable image.' },
      }),
    );
    await screen.findByText('That file is not a readable image.');

    stream.close();
  });

  it('reports an upload no row named, rather than ignoring it', async () => {
    // A trailing line keyed by the file name, with no manifest row behind it.
    // An upload silently dropped is an image an Administrator believes is in
    // the catalogue and is not — a defect nobody finds until a scan fails to
    // return it.
    const stream = stubStreamingFetch();
    renderScreen();

    chooseSheet();
    chooseImages([anImage(), anImage('stray.jpg')]);
    submit();

    stream.push(
      JSON.stringify({
        kind: 'row',
        row: null,
        file: 'stray.jpg',
        code: null,
        status: 'failed',
        tile_id: null,
        flags: [],
        error: { code: 'image_unmatched', message: 'No row in the sheet names this image.' },
      }),
    );
    await screen.findByText('stray.jpg');

    const [only] = reportedRows();
    expect(within(only!).getByText('Failed')).toBeTruthy();
    expect(only!.textContent).toMatch(/No row in the sheet names this image\./);

    stream.close();
  });

  it('announces progress while the batch runs and when it is over', async () => {
    const stream = stubStreamingFetch();
    renderScreen();

    // In the document at rest, so what gets announced is the change of text
    // rather than the arrival of a whole new node.
    const progress = screen.getByRole('status');
    expect(progress.textContent).toBe('');

    chooseSheet();
    chooseImages();
    submit();

    await waitFor(() => expect(progress.textContent).toMatch(/uploading/i));

    stream.push(rowLine(1, 'row-1.jpg', 'created'));
    await waitFor(() => expect(progress.textContent).toMatch(/1 reported/i));

    stream.push(summaryLine(1, 0, 0));
    stream.close();
    await waitFor(() => expect(progress.textContent).toMatch(/finished/i));
  });

  it('shows an indeterminate bar until the server says how many rows there are', async () => {
    // **The bar has no denominator of its own and must not invent one**
    // (AD-20). The rows live in a sheet only the server reads, so the number
    // of images chosen here is the wrong number for exactly the batch this
    // report exists for — the one whose rows and uploads do not line up. ARIA
    // defines a progressbar with no `aria-valuenow` as indeterminate, which is
    // the true shape of "the images are still going up".
    const stream = stubStreamingFetch();
    renderScreen();

    chooseSheet();
    chooseImages([anImage('a.jpg'), anImage('b.jpg')]);
    submit();

    const bar = await screen.findByRole('progressbar');
    expect(bar.getAttribute('aria-valuenow')).toBeNull();
    expect(bar.getAttribute('aria-valuemax')).toBeNull();

    // Two images were chosen and the sheet has three rows. A screen that had
    // guessed would now be showing a denominator of two.
    stream.push(startLine(3));
    await waitFor(() => expect(bar.getAttribute('aria-valuemax')).toBe('3'));
    expect(bar.getAttribute('aria-valuenow')).toBe('0');

    stream.close();
  });

  it('counts whole rows against the server’s total as they arrive', async () => {
    const stream = stubStreamingFetch();
    renderScreen();

    chooseSheet();
    chooseImages();
    submit();

    stream.push(startLine(3));
    const bar = await screen.findByRole('progressbar');

    stream.push(rowLine(1, 'a.jpg', 'created'));
    await waitFor(() => expect(bar.getAttribute('aria-valuenow')).toBe('1'));
    stream.push(rowLine(2, 'b.jpg', 'flagged', { flags: ['low_quality_image'] }));
    stream.push(rowLine(3, 'c.jpg', 'failed'));
    await waitFor(() => expect(bar.getAttribute('aria-valuenow')).toBe('3'));

    // The three counts beside it, each with its word — the colours are held by
    // `styling-wiring.test.ts` and jsdom paints none of them, so a bar that
    // signalled by colour alone would be invisible to the whole suite.
    expect(screen.getByText('1 added')).toBeTruthy();
    expect(screen.getByText('1 flagged')).toBeTruthy();
    expect(screen.getByText('1 failed')).toBeTruthy();
    expect(screen.getByText(/3 of 3 rows/)).toBeTruthy();

    stream.close();
  });

  it('never lets the bar overrun its own total when the batch stops', async () => {
    // A batch that stops part-way writes one failed line *past* the total the
    // opening line promised, because the total counts a clean run. Without the
    // guard the bar would read 3 of 2 on the one batch whose reader is looking
    // hardest at it.
    const stream = stubStreamingFetch();
    renderScreen();

    chooseSheet();
    chooseImages();
    submit();

    stream.push(startLine(1));
    stream.push(rowLine(1, 'a.jpg', 'created'));
    stream.push(
      JSON.stringify({
        kind: 'row',
        row: null,
        file: '',
        code: null,
        status: 'failed',
        tile_id: null,
        flags: [],
        error: { code: 'row_failed', message: 'The upload stopped before every row ran.' },
      }),
    );
    const bar = await screen.findByRole('progressbar');
    await waitFor(() => expect(bar.getAttribute('aria-valuenow')).toBe('2'));

    expect(bar.getAttribute('aria-valuemax')).toBe('2');

    stream.close();
  });

  it('opens the report as soon as the batch starts, before any row', async () => {
    // The minutes before the first row are exactly when there is nothing else
    // on screen to say the batch is alive.
    const stream = stubStreamingFetch();
    renderScreen();

    expect(screen.queryByRole('progressbar')).toBeNull();

    chooseSheet();
    chooseImages();
    submit();

    expect(await screen.findByRole('progressbar')).toBeTruthy();
    expect(reportedRows()).toEqual([]);

    stream.close();
  });

  it('stamps each line with the time it arrived', async () => {
    // A batch runs for minutes and the rows do not arrive evenly — a 96 MB
    // press file takes tens of seconds to embed. The gap between two stamps is
    // the only evidence an Administrator has of where the time went. Nothing
    // is derived from it: there is no rate here and no projected finish, which
    // would be invented numbers (AD-20).
    const stream = stubStreamingFetch();
    renderScreen();

    chooseSheet();
    chooseImages();
    submit();

    stream.push(rowLine(1, 'row-1.jpg', 'created'));
    await screen.findByText('row-1.jpg');

    const [only] = reportedRows();
    expect(only!.textContent).toMatch(/\d{2}:\d{2}:\d{2}/);

    stream.close();
  });

  it('closes the report with the summary', async () => {
    const stream = stubStreamingFetch();
    renderScreen();

    chooseSheet();
    chooseImages([anImage(), anImage('b.jpg'), anImage('c.jpg')]);
    submit();

    stream.push(rowLine(1, 'a.jpg', 'created'));
    stream.push(rowLine(2, 'b.jpg', 'flagged', { flags: ['low_quality_image'] }));
    stream.push(rowLine(3, 'c.jpg', 'failed', {
      error: { code: 'unreadable_image', message: 'That file is not a readable image.' },
    }));
    stream.push(summaryLine(1, 1, 1));
    stream.close();

    expect(await screen.findByText(/1 added, 1 flagged, 1 failed\./i)).toBeTruthy();
    // The summary is *in addition to* the rows, never instead of them
    // (EXPERIENCE.md:73 — a per-row list, not a single pass/fail summary).
    expect(reportedRows()).toHaveLength(3);
  });

  it('re-enables its controls once the batch is over', async () => {
    const stream = stubStreamingFetch();
    renderScreen();

    chooseSheet();
    chooseImages();
    submit();

    await waitFor(() =>
      expect(screen.getByRole('button', { name: /^upload$/i })).toHaveProperty('disabled', true),
    );
    // Back too: a click that unmounted this screen mid-batch would leave the
    // Administrator unsure which rows had landed.
    expect(screen.getByRole('button', { name: /^back$/i })).toHaveProperty('disabled', true);
    // And both pickers. Choosing a different sheet mid-run clears the report
    // and then refills it from the batch that is still going, so the list
    // would describe one upload under the heading of another.
    expect(screen.getByLabelText(/sheet of codes/i)).toHaveProperty('disabled', true);
    expect(screen.getByLabelText(/reference images/i)).toHaveProperty('disabled', true);

    stream.push(rowLine(1, 'row-1.jpg', 'created'));
    stream.push(summaryLine(1, 0, 0));
    stream.close();

    await waitFor(() =>
      expect(screen.getByRole('button', { name: /^upload$/i })).toHaveProperty('disabled', false),
    );
    expect(screen.getByRole('button', { name: /^back$/i })).toHaveProperty('disabled', false);
    expect(screen.getByLabelText(/sheet of codes/i)).toHaveProperty('disabled', false);
    expect(screen.getByLabelText(/reference images/i)).toHaveProperty('disabled', false);
  });

  it('paints the report where the runtime has no streams at all', async () => {
    // `apiStream`'s `response.text()` fallback. jsdom's own `fetch` is a stub
    // with no `body`, and a screen that only worked against a real
    // `ReadableStream` would be a screen no test in this suite could drive —
    // so the fallback is not test scaffolding, it is what keeps the report
    // renderable wherever the streams API is missing.
    stubFetch({
      status: 200,
      text: [
        rowLine(1, 'a.jpg', 'created'),
        rowLine(2, 'b.jpg', 'failed', {
          error: { code: 'row_failed', message: 'That row could not be processed.' },
        }),
        summaryLine(1, 0, 1),
        '',
      ].join('\n'),
    });
    renderScreen();

    chooseSheet();
    chooseImages([anImage(), anImage('b.jpg')]);
    submit();

    await screen.findByText(/1 added, 0 flagged, 1 failed\./i);
    expect(reportedRows()).toHaveLength(2);
  });
});

describe('a refusal before the stream opens', () => {
  it('renders the server’s own sentence and no report at all', async () => {
    // Everything refusable is refused before the first byte, which is the only
    // window in which a real envelope under a real status is still possible.
    // Once the stream opens the status is `200` and every outcome is a row.
    stubFetch({
      status: 422,
      body: {
        error: {
          code: 'invalid_manifest',
          message: `That sheet could not be read. ${NO_MANIFEST_SENTENCE}`,
        },
      },
    });
    renderScreen();

    chooseSheet();
    chooseImages();
    submit();

    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain(NO_MANIFEST_SENTENCE);
    // Rendered next to the sheet picker, which is the control it is about: a
    // manifest the server cannot read is an answer about that file. Parked
    // under both pickers instead, it leaves a screen-reader user on the wrong
    // one hearing a sentence about the other.
    const sheet = screen.getByLabelText(/sheet of codes/i);
    expect(sheet.getAttribute('aria-invalid')).toBe('true');
    expect(sheet.getAttribute('aria-describedby')).toContain(alert.id);
    expect(document.activeElement).toBe(sheet);
    // No list, no summary, no partial report: nothing was processed, so there
    // is nothing to report per row.
    expect(reportedRows()).toEqual([]);
    expect(screen.queryByRole('heading', { name: /^report$/i })).toBeNull();
  });

  it.each([
    [
      'too_many_rows',
      422,
      'That sheet has too many rows. Upload at most 100 at a time.',
      'marks the sheet',
    ],
    [
      'matching_unavailable',
      503,
      'The image pipeline is not installed on this server. Run `make model`.',
      'marks nothing',
    ],
    [
      'pipeline_stamp_mismatch',
      503,
      'The catalogue index was built by a different version of the image pipeline.',
      'marks nothing',
    ],
    [
      'administrator_required',
      403,
      'You need to be an administrator to do that.',
      'marks nothing',
    ],
  ])(
    'renders the %s sentence unchanged and %s',
    async (code, status, message, treatment) => {
      // The screen never restates a rule the server owns (EXPERIENCE.md:87).
      // Driven at the status each refusal really carries, so a screen that had
      // come to depend on `422` is a failure here rather than in a browser.
      //
      // Only the row cap marks a control: it is an answer about the sheet in
      // that picker. Nothing the Administrator chose is at fault for a missing
      // model artifact, a stale stamp or a role, and marking one of those tells
      // a screen-reader user their choice was wrong when it was not.
      stubFetch({ status, body: { error: { code, message } } });
      renderScreen();

      chooseSheet();
      chooseImages();
      submit();

      expect((await screen.findByRole('alert')).textContent).toBe(message);
      expect(screen.getByLabelText(/sheet of codes/i).getAttribute('aria-invalid')).toBe(
        treatment === 'marks the sheet' ? 'true' : 'false',
      );
      expect(screen.getByLabelText(/reference images/i).getAttribute('aria-invalid')).toBe(
        'false',
      );
      expect(reportedRows()).toEqual([]);
    },
  );
});

describe('the refusals it makes itself', () => {
  it('refuses a submit with no sheet chosen, and focuses the picker', async () => {
    const { calls } = stubFetch({ status: 200, text: '' });
    renderScreen();

    chooseImages();
    submit();

    expect(await screen.findByRole('alert')).toHaveProperty(
      'textContent',
      'Choose the sheet of codes.',
    );
    expect(document.activeElement).toBe(screen.getByLabelText(/sheet of codes/i));
    // Nothing was uploaded: a missing sheet must not cost a file transfer to be
    // told a picker is empty.
    expect(calls).toHaveLength(0);
  });

  it('refuses a submit with no images chosen', async () => {
    const { calls } = stubFetch({ status: 200, text: '' });
    renderScreen();

    chooseSheet();
    submit();

    expect(await screen.findByRole('alert')).toHaveProperty(
      'textContent',
      'Choose the reference images.',
    );
    expect(document.activeElement).toBe(screen.getByLabelText(/reference images/i));
    expect(calls).toHaveLength(0);
  });

  it('refuses more images than the endpoint takes without uploading them', async () => {
    // A hundred reference images is comfortably gigabytes. Refusing after the
    // upload would make the Administrator watch it finish and then be told the
    // batch was never going to be accepted.
    const { calls } = stubFetch({ status: 200, text: '' });
    renderScreen();

    chooseSheet();
    chooseImages(
      Array.from({ length: MAX_BULK_ROWS + 1 }, (_unused, index) => anImage(`${index}.jpg`)),
    );
    submit();

    expect((await screen.findByRole('alert')).textContent).toMatch(
      new RegExp(`at most ${MAX_BULK_ROWS}`, 'i'),
    );
    expect(calls).toHaveLength(0);
    expect(screen.getByLabelText(/reference images/i).getAttribute('aria-invalid')).toBe('true');
  });

  it('refuses an oversized image it could not shrink, and names it', async () => {
    // Over the ceiling is no longer refused on sight — it is redrawn whole and
    // sent. This is what is left when that cannot be done: `anImage`'s bytes
    // are not a JPEG the sniffer can vouch for, so re-encoding it might change
    // its colour, and a changed colour is a corrupted embedding nobody would
    // ever see (CLAUDE.md, AD-15).
    const { calls } = stubFetch({ status: 200, text: '' });
    renderScreen();

    chooseSheet();
    chooseImages([anImage('small.jpg'), anImage('huge.jpg', MAX_IMAGE_BYTES + 1)]);
    submit();

    const refusal = (await screen.findByRole('alert')).textContent ?? '';
    // The file, so a batch of a hundred with one bad one is not a hunt.
    expect(refusal).toMatch(/huge\.jpg/);
    // The bound, and the fix — which is a re-export, not a retry.
    expect(refusal).toMatch(/128 MB/);
    expect(refusal).toMatch(/sRGB/i);
    // The one that was fine is not named, and nothing travelled.
    expect(refusal).not.toMatch(/small\.jpg/);
    expect(calls).toHaveLength(0);
  });

  it('shrinks an oversized image on the device and sends the smaller one', async () => {
    // The request the Administrator no longer has to make by hand: a 96 MB
    // press file is oversampled by an order of magnitude against the 2048 px
    // the server decodes to, so the whole frame is redrawn smaller and sent
    // rather than refused.
    const encoded = stubRedraw();
    const stream = stubStreamingFetch();
    renderScreen();

    chooseSheet();
    chooseImages([anImage('small.jpg'), aPlainJpeg('huge.jpg', MAX_IMAGE_BYTES + 1)]);
    submit();

    stream.push(rowLine(1, 'small.jpg', 'created'));
    await screen.findByText('small.jpg');

    const body = (stream.calls[0]?.[1].body ?? new FormData()) as FormData;
    const sent = body.getAll('images') as File[];
    expect(sent).toHaveLength(2);
    // The name is untouched, because the manifest pairs on it.
    expect(sent.map((file) => file.name)).toEqual(['small.jpg', 'huge.jpg']);
    // The oversized one shrank; the one that already fitted travelled as
    // chosen, byte for byte — re-encoding it would spend a generation of JPEG
    // artefacts on a problem it does not have.
    expect(sent[1]?.size).toBe(encoded);
    expect(sent[0]?.size).toBe(4);

    stream.close();
  });

  it('says what it did to the oversized images rather than doing it quietly', async () => {
    // The bytes indexed are not the bytes chosen. An Administrator comparing a
    // stored reference image against the file on their disk deserves to know
    // why the two differ.
    stubRedraw();
    const stream = stubStreamingFetch();
    renderScreen();

    chooseSheet();
    chooseImages([aPlainJpeg('huge.jpg', MAX_IMAGE_BYTES + 1)]);
    submit();

    const note = await screen.findByText(/huge\.jpg.*MB sent as.*MB/);
    expect(note).toBeTruthy();

    stream.close();
  });

  it('retires the report when a different batch is chosen', async () => {
    // The report describes a batch that has already run; the moment a different
    // sheet is chosen it is describing something that is no longer on screen.
    const stream = stubStreamingFetch();
    renderScreen();

    chooseSheet();
    chooseImages();
    submit();

    stream.push(rowLine(1, 'row-1.jpg', 'created'));
    stream.push(summaryLine(1, 0, 0));
    stream.close();
    await screen.findByText('row-1.jpg');

    chooseSheet(aSheet('other.csv'));

    await waitFor(() => expect(reportedRows()).toEqual([]));
  });
});

describe('the screen’s controls', () => {
  it('has exactly the controls it is meant to have', () => {
    renderScreen();

    const found = CONTROL_ROLES.flatMap((role) =>
      screen.queryAllByRole(role).map((element) => `${role}: ${element.textContent ?? ''}`),
    );

    // Two buttons and one link, and nothing else. The two file inputs are
    // deliberately not in this count: `<input type="file">` has no implicit
    // ARIA role, so each is unreachable by role and is asserted by its label
    // instead — which is also why those labels have to be right.
    //
    // There is no text field at all on this screen, and that is the design: the
    // Code, the Size and the Category arrive in the manifest, and a box to
    // retype one of them here would be a second way to state what the sheet
    // already says. A third *button* would be a control nobody specified, and
    // on a screen limited to one accent fill it is how a second primary
    // arrives — which is why the template is a link and is counted as one: it
    // saves a file, it sends nothing, and it is not an action of this form.
    expect(found).toHaveLength(3);
    expect(screen.getByRole('button', { name: /^upload$/i })).toBeTruthy();
    expect(screen.getByRole('button', { name: /^back$/i })).toBeTruthy();
    expect(screen.getByRole('link', { name: /template/i })).toBeTruthy();
    expect(screen.getByLabelText(/sheet of codes/i).getAttribute('type')).toBe('file');
    expect(screen.getByLabelText(/reference images/i).getAttribute('type')).toBe('file');
  });

  it('takes one sheet and many images', () => {
    renderScreen();

    // The manifest is one file; `multiple` on it would let an Administrator
    // choose two sheets and leave the server to decide which one a batch is.
    expect(screen.getByLabelText(/sheet of codes/i).getAttribute('multiple')).toBeNull();
    expect(screen.getByLabelText(/reference images/i).getAttribute('multiple')).not.toBeNull();
  });

  it('does not narrow the image picker to one format', () => {
    // The real catalogue holds `.tif` alongside `.jpg`, and content decides,
    // not the extension (AGENTS.md Policy). A narrower `accept` would hide
    // files that are perfectly valid.
    renderScreen();

    expect(screen.getByLabelText(/reference images/i).getAttribute('accept')).toBe('image/*');
  });

  it('describes each picker by its limits, and by the refusal as well', async () => {
    // The row cap and the byte ceiling are stated in that hint and nowhere
    // else. Unbound, a screen-reader user meets both as a refusal after
    // choosing the files — and when the refusal arrives it must be added to the
    // description, not put in the hint's place.
    stubFetch({ status: 200, text: '' });
    renderScreen();

    const input = screen.getByLabelText(/reference images/i);
    const hintId = input.getAttribute('aria-describedby');
    expect(hintId).toBeTruthy();
    expect(document.getElementById(hintId ?? '')?.textContent).toMatch(/at a time/i);

    chooseSheet();
    chooseImages(
      Array.from({ length: MAX_BULK_ROWS + 1 }, (_unused, index) => anImage(`${index}.jpg`)),
    );
    submit();

    await screen.findByRole('alert');
    const described = screen.getByLabelText(/reference images/i).getAttribute('aria-describedby');
    expect(described?.split(' ')).toHaveLength(2);
    expect(described).toContain(hintId ?? '');
  });

  it('goes back when Back is pressed', () => {
    const onBack = vi.fn();
    renderScreen(onBack);

    fireEvent.click(screen.getByRole('button', { name: /^back$/i }));

    expect(onBack).toHaveBeenCalledTimes(1);
  });

  it('uses the domain’s own words and none of the retired ones', () => {
    // AD-18 retires `Product` and `Face`. The rendered text is where they would
    // come back first, and a label is what an Administrator learns the
    // vocabulary from. A bulk report listing "products" would be the clearest
    // possible statement of the identity model AD-18 rejects.
    const { container } = render(<BulkUploadScreen onBack={(): void => undefined} />);
    const text = container.textContent ?? '';

    expect(text).toMatch(/Bulk upload/);
    expect(text).toMatch(/code/i);
    expect(/\bproducts?\b/i.test(text)).toBe(false);
    expect(/\bfaces?\b/i.test(text)).toBe(false);
  });

  it('renders no main landmark of its own', () => {
    // `AppShell` provides the one `<main>` and the focus target the gate moves
    // focus to on a screen swap. A second one here would be two main landmarks
    // on every render of this surface.
    const { container } = render(<BulkUploadScreen onBack={(): void => undefined} />);

    expect(container.querySelector('main')).toBeNull();
  });
});

/** The template as the browser would save it, decoded from the offered URL. */
function templateCsv(): string {
  const href = screen.getByRole('link', { name: /template/i }).getAttribute('href') ?? '';
  const [scheme, encoded] = href.split(',', 2);

  // Asserted rather than assumed: a `blob:` href would decode to nothing here
  // and every check below would then be reading an empty string.
  expect(scheme).toBe('data:text/csv;charset=utf-8');
  return decodeURIComponent(encoded ?? '');
}

describe('the template sheet', () => {
  it('is offered as a file to save, under a name that says what it is', () => {
    renderScreen();

    const link = screen.getByRole('link', { name: /template/i });

    // `download` is what makes this a save rather than a navigation. Without
    // it the browser renders four lines of CSV in place of the screen and the
    // batch in flight — if there is one — goes with it.
    expect(link.getAttribute('download')).toMatch(/\.csv$/);
  });

  it('asks the server for nothing', () => {
    // The bytes are this screen's own source, so the template is available to
    // an Administrator whose session has just expired and costs the API
    // nothing per press. A `/api/` href would be a second endpoint nobody
    // specified; an object URL would be a leak per press.
    //
    // Asserted on the href rather than by clicking it: jsdom implements no
    // navigation, so a click here cannot tell a `data:` URL from an `/api/`
    // one — it logs "Not implemented" for both and no request is made in
    // either case. The scheme is the thing that decides, and `templateCsv`
    // pins it on every check below.
    const stub = stubFetch({ status: 200, text: '' });
    renderScreen();

    expect(templateCsv()).toBeTruthy();
    expect(stub.calls).toHaveLength(0);
  });

  it('carries the header the server parses, and only that', () => {
    renderScreen();

    const [header] = templateCsv().split('\n');

    // The three columns `_manifest_rows` requires plus the one it may take.
    // `error-code-parity.test.ts` is what holds this against `catalogue.py`;
    // this one holds it against the file an Administrator actually receives,
    // which is the assembled string rather than the constant behind it.
    expect(header).toBe('file,code,size,category');
  });

  it('shows a row per file, each one a shape the catalogue really holds', () => {
    renderScreen();

    const lines = templateCsv().trimEnd().split('\n');
    const rows = lines.slice(1);

    // Four examples, every one of them four cells wide. A row short of a cell
    // in the file the product hands out is a row the server refuses by the
    // rule the template exists to teach.
    expect(rows.length).toBeGreaterThan(1);
    for (const row of rows) expect(row.split(',')).toHaveLength(4);

    // One Code per line and no line standing for a range: AD-18's identity
    // model, stated in the one artefact an Administrator copies before they
    // have read a word of it. Two example lines share neither their Size nor
    // their Code.
    const codes = rows.map((row) => row.split(',')[1]);
    expect(new Set(codes).size).toBe(rows.length);
  });

  it('leaves one example Category empty, because an empty one is legal', () => {
    // AD-18: a row with no recoverable Category is filed under `UNKNOWN` and
    // flagged, never refused. It is the one rule about this sheet nobody
    // guesses, and a template whose every row is filled in teaches the
    // opposite — an Administrator inventing a Category to fill a cell is how a
    // catalogue acquires a range that does not exist.
    renderScreen();

    const rows = templateCsv().trimEnd().split('\n').slice(1);

    expect(rows.some((row) => row.endsWith(','))).toBe(true);
  });
});

describe('the route from the Catalogue', () => {
  // Retargeted by Story 2.5 rather than deleted. This screen had a door of its
  // own on the home panel while there was no Catalogue to reach it from;
  // EXPERIENCE.md line 37 always reached Bulk Upload *from* the Catalogue, and
  // that surface now exists — so it is an outlined control beside "+ Add Tile"
  // there, and the home panel carries one Catalogue door instead of three tile
  // ones. What this block still proves is the same two things: an
  // Administrator can get here, and a Staff user cannot.
  it('is reached from the Catalogue by an Administrator', async () => {
    stubSession(ADMIN);
    render(<App />);

    fireEvent.click(await screen.findByRole('button', { name: /^catalogue$/i }));
    await screen.findByRole('heading', { name: /^catalogue$/i });

    fireEvent.click(screen.getByRole('button', { name: /^bulk upload$/i }));

    expect(await screen.findByRole('heading', { name: /^bulk upload$/i })).toBeTruthy();
  });

  it('has no door of its own on the home panel any more', async () => {
    // Two ways to reach one screen is the thing Story 2.5 removed — and an
    // orange door onto *this* screen was the least defensible of the three,
    // since it is the one place in the product where the accent is also a
    // status colour (DESIGN.md:144-149).
    stubSession(ADMIN);
    render(<App />);

    await screen.findByRole('heading', { name: /^scan$/i });

    expect(screen.queryByRole('button', { name: /^bulk upload$/i })).toBeNull();
    expect(screen.getByRole('button', { name: /^catalogue$/i })).toBeTruthy();
  });

  it('is not reachable by a Staff user at all', async () => {
    // EXPERIENCE.md line 18: the nav is role-conditional, not a menu with
    // disabled items — a Staff user should never see an entry they cannot use.
    // The server refuses them regardless (AGENTS.md Policy); this is the
    // courtesy on top of the control.
    stubSession(STAFF);
    render(<App />);

    await screen.findByRole('heading', { name: /^scan$/i });

    expect(screen.queryByRole('button', { name: /^catalogue$/i })).toBeNull();
    expect(screen.queryByRole('button', { name: /^bulk upload$/i })).toBeNull();
  });

  it('returns to the Catalogue from Back, not to the home panel', async () => {
    // The Catalogue is where the control was pressed, and `CatalogueScreen`
    // refetches on mount — so returning to it lists the whole batch that just
    // landed.
    stubSession(ADMIN);
    render(<App />);

    fireEvent.click(await screen.findByRole('button', { name: /^catalogue$/i }));
    await screen.findByRole('heading', { name: /^catalogue$/i });
    fireEvent.click(screen.getByRole('button', { name: /^bulk upload$/i }));
    await screen.findByRole('heading', { name: /^bulk upload$/i });

    fireEvent.click(screen.getByRole('button', { name: /^back$/i }));

    expect(await screen.findByRole('heading', { name: /^catalogue$/i })).toBeTruthy();
    expect(screen.queryByText(/signed in as nadeesha silva/i)).toBeNull();
  });
});

describe('what the report says when things go wrong around it', () => {
  it('names the manifest row on every line that has one', async () => {
    // The row number is what an Administrator uses to find the offending line
    // in the sheet in front of them — a file name alone means scrolling a
    // hundred-row spreadsheet looking for it. The server sends it and the
    // screen parsed it long before it rendered it, which is the shape of gap
    // this asserts away.
    const stream = stubStreamingFetch();
    renderScreen();

    chooseSheet();
    chooseImages();
    submit();

    stream.push(rowLine(7, 'row-7.jpg', 'created'));
    await screen.findByText('row-7.jpg');

    const [only] = reportedRows();
    expect(within(only!).getByText(/^Row 7$/)).toBeTruthy();

    stream.close();
  });

  it('gives an unmatched upload no row number at all', async () => {
    // `row` is a position in the *sheet*. A number here would send somebody to
    // a line that does not exist.
    const stream = stubStreamingFetch();
    renderScreen();

    chooseSheet();
    chooseImages();
    submit();

    stream.push(
      JSON.stringify({
        kind: 'row',
        row: null,
        file: 'stray.jpg',
        code: null,
        status: 'failed',
        tile_id: null,
        flags: [],
        error: { code: 'image_unmatched', message: 'No row in the sheet names this image.' },
      }),
    );
    await screen.findByText('stray.jpg');

    const [only] = reportedRows();
    expect(within(only!).queryByText(/^Row \d+$/)).toBeNull();

    stream.close();
  });

  it('says the report stopped early when the stream ends with no summary', async () => {
    // The server writes a summary even when a batch stops part-way, so
    // reaching this means the connection itself went. The rows on screen are
    // real and stay; what has to be said is that the ones after them never
    // ran. Blanking the progress line instead reads exactly like a batch that
    // finished cleanly.
    const stream = stubStreamingFetch();
    renderScreen();

    chooseSheet();
    chooseImages();
    submit();

    stream.push(rowLine(1, 'row-1.jpg', 'created'));
    await screen.findByText('row-1.jpg');
    stream.close();

    await waitFor(() => expect(screen.getByRole('status').textContent).toMatch(/stopped early/i));
    // The row that did land is still there. Clearing it would report a tile
    // that is in the catalogue as one that is not.
    expect(reportedRows()).toHaveLength(1);
  });

  it('says the report stopped early when the server says the batch stopped', async () => {
    // The other way a report ends short, and the one the server can still
    // speak on: the status was committed at the first byte, so a failure
    // outside any row arrives as a failed line with no manifest row number and
    // the summary is written anyway. A summary is therefore not proof of a
    // clean finish, and "Finished." above a row saying the upload stopped is
    // the screen contradicting its own report.
    const stream = stubStreamingFetch();
    renderScreen();

    chooseSheet();
    chooseImages();
    submit();

    stream.push(rowLine(1, 'row-1.jpg', 'created'));
    await screen.findByText('row-1.jpg');
    stream.push(
      JSON.stringify({
        kind: 'row',
        row: null,
        file: '',
        code: null,
        status: 'failed',
        tile_id: null,
        flags: [],
        error: {
          code: 'row_failed',
          message:
            'The upload stopped before every row was processed. ' +
            'The rows above were finished; send the rest again.',
        },
      }),
    );
    stream.push(summaryLine(1, 0, 1));
    stream.close();

    await waitFor(() => expect(screen.getByRole('status').textContent).toMatch(/stopped early/i));
    // Both lines are on screen: the batch-stopped line is an ordinary report
    // row and belongs in the list like any other.
    expect(reportedRows()).toHaveLength(2);
  });

  it('renders a flag this build has no sentence for rather than dropping it', async () => {
    // A flag the screen cannot word is still a flag an Administrator has to
    // see. Dropped, the row would paint orange, say "Flagged" and give no
    // reason — which reads as a clean success with a stray colour on it.
    const stream = stubStreamingFetch();
    renderScreen();

    chooseSheet();
    chooseImages();
    submit();

    stream.push(rowLine(1, 'row-1.jpg', 'flagged', { flags: ['something_the_server_added'] }));
    await screen.findByText('row-1.jpg');

    const [only] = reportedRows();
    expect(within(only!).getByText('Flagged')).toBeTruthy();
    expect(only!.textContent).toMatch(/something_the_server_added/);

    stream.close();
  });

  it('carries list semantics even with no markers', async () => {
    // Safari with VoiceOver strips list semantics from a list whose
    // `list-style` is `none` — the rows stop being announced as a list at all
    // and "row 4 of 30" goes with them, which on a report this long is the one
    // piece of orientation a screen-reader user has.
    const stream = stubStreamingFetch();
    renderScreen();

    chooseSheet();
    chooseImages();
    submit();

    stream.push(rowLine(1, 'row-1.jpg', 'created'));
    await screen.findByText('row-1.jpg');

    const list = screen.getByRole('list');
    expect(list.tagName).toBe('OL');
    expect(list.getAttribute('role')).toBe('list');

    stream.close();
  });

  it('paints nothing more after the screen has gone', async () => {
    // A batch runs for minutes and the screen can go inside that: a session
    // expiring drops the shell to the login screen, a sign-out unmounts
    // everything. Without the guard this asserts, every line still in flight
    // is a `setState` on a component that does not exist.
    const stream = stubStreamingFetch();
    const { unmount } = render(<BulkUploadScreen onBack={(): void => undefined} />);

    chooseSheet();
    chooseImages();
    submit();

    stream.push(rowLine(1, 'row-1.jpg', 'created'));
    await screen.findByText('row-1.jpg');

    // **What this can and cannot see.** React 19 dropped the
    // "state update on an unmounted component" warning, and a `setState` on a
    // detached fiber is a silent no-op — so no assertion here can distinguish
    // the guard being present from it being absent by watching React. What is
    // checked is what remains observable: the lines that arrive after the
    // screen has gone are consumed without the callback throwing, without the
    // stream failing, and without anything reaching the console. The guard
    // keeps the work itself from running; this pins the contract around it.
    const complained = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    try {
      unmount();
      stream.push(rowLine(2, 'row-2.jpg', 'created'));
      stream.push(summaryLine(2, 0, 0));
      stream.close();
      await waitFor(() => expect(true).toBe(true));

      expect(complained).not.toHaveBeenCalled();
    } finally {
      complained.mockRestore();
    }
  });

  it('abandons the stream when the screen unmounts mid-batch', async () => {
    // Stopping the painting is only half of it: the server goes on processing
    // a hundred rows into a connection nobody is draining. The abort is what
    // closes it, and the request's own signal is where that is observable.
    const stream = stubStreamingFetch();
    const { unmount } = render(<BulkUploadScreen onBack={(): void => undefined} />);

    chooseSheet();
    chooseImages();
    submit();

    stream.push(rowLine(1, 'row-1.jpg', 'created'));
    await screen.findByText('row-1.jpg');

    const [, init] = stream.calls[0] ?? ['', {}];
    expect(init.signal?.aborted).toBe(false);

    unmount();

    expect(init.signal?.aborted).toBe(true);
  });

  it('drops to the login screen when the batch is refused as signed out', async () => {
    // Every other test of the 401 hook drives `apiRequest`; this is the one
    // path that reaches it through `apiStream`, and a stream that refused
    // without telling the observer would leave the shell rendering over a dead
    // session — the exact failure that hook exists to catch.
    let asked = 0;
    vi.stubGlobal('fetch', (input: string, init: RequestInit = {}) => {
      const key = `${init.method ?? 'GET'} ${input}`;
      if (key === 'GET /api/auth/session') {
        asked += 1;
        return Promise.resolve({
          ok: asked === 1,
          status: asked === 1 ? 200 : 401,
          json: () =>
            Promise.resolve(
              asked === 1
                ? ADMIN
                : { error: { code: 'unauthorized', message: 'Not signed in.' } },
            ),
        } as unknown as Response);
      }
      // Scan is the landing surface, and it reads the sizes its filter may
      // offer on arrival. It has to succeed for the same reason the browse
      // below does: this stub answers 401 to anything it does not recognise,
      // and that would drop the app to the login screen before the batch this
      // test is about is ever submitted.
      if (key === 'GET /api/scans/sizes') {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: () => Promise.resolve([]),
        } as unknown as Response);
      }
      // The Catalogue is the route to this screen since Story 2.5, and its
      // browse has to succeed or the app drops to the login screen before the
      // batch this test is about is ever submitted.
      if (key === 'GET /api/admin/tiles?q=') {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: () => Promise.resolve([]),
        } as unknown as Response);
      }
      return Promise.resolve({
        ok: false,
        status: 401,
        body: undefined,
        json: () =>
          Promise.resolve({ error: { code: 'unauthorized', message: 'Not signed in.' } }),
        text: () => Promise.resolve(''),
      } as unknown as Response);
    });

    render(<App />);
    fireEvent.click(await screen.findByRole('button', { name: /^catalogue$/i }));
    await screen.findByRole('heading', { name: /^catalogue$/i });
    fireEvent.click(screen.getByRole('button', { name: /^bulk upload$/i }));
    await screen.findByRole('heading', { name: /^bulk upload$/i });

    chooseSheet();
    chooseImages();
    submit();

    // The shell is gone and the login screen is in its place, with the notice
    // that says why — a 401 that only rejected the caller would leave the app
    // rendering an admin surface over a session the server has stopped
    // honouring.
    expect(
      await screen.findByText(/your session has ended\. sign in again to continue\./i),
    ).toBeTruthy();
    expect(screen.queryByRole('heading', { name: /^bulk upload$/i })).toBeNull();
  });
});
