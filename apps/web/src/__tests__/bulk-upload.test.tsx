/**
 * Bulk upload — the screen, the batch it drives, and the route the app takes to reach it.
 *
 * Two halves, driven through two different roots, the way `add-tile.test.tsx`
 * splits them. The screen's own behaviour runs against a stubbed `fetch` with
 * the screen rendered directly, because it calls `apiRequest` itself rather
 * than going through `SessionProvider`; whether the app *reaches* the screen at
 * all runs through `App`, because the role condition and the section state live
 * in the gate.
 *
 * **The stub answers nothing until a test says so**, and that is the whole
 * apparatus here. A batch is a plan request followed by one request per image,
 * driven by this screen — so a stub that resolved on its own could only ever
 * show the finished report. Holding every request open and answering them one
 * at a time is what makes the claims below assertable at all:
 *
 * * **Every row is on screen before its image is sent.** The plan pairs the
 *   sheet against the file names and this screen paints the whole list from it,
 *   waiting; each line resolves in place as its own request answers. A screen
 *   that rendered rows only as they completed would pass a report test and fail
 *   this one.
 * * **One request at a time, and one image in each.** Sixteen forward passes
 *   per row on the server's CPU (AD-13, AD-16) means concurrency buys nothing
 *   and costs the peak transfer it was split to avoid. Observable only by
 *   counting requests while one is unanswered.
 * * **A dropped connection costs one row, not the range.** This is the reason
 *   the transfer is split at all, and it is the one failure the previous
 *   single-request shape could not survive. The stub rejects one row's request
 *   the way the platform does and the batch has to carry on.
 * * **Each state carries a word, not only a colour.** `vite.config.ts` sets
 *   `css: false`, so jsdom applies no stylesheet: the colours are held by
 *   `styling-wiring.test.ts` and the words are held here, and neither file can
 *   see the other half. A report that signalled by colour alone would be
 *   invisible to both unless this file reads the text.
 * * **A batch-wide refusal renders the server's sentence and no report.**
 *   Everything that is about the batch rather than one row is refused by the
 *   plan, before an image has been sent.
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

const PLAN = '/api/admin/tiles/bulk/plan';
const ROW = '/api/admin/tiles/bulk/row';

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

/** One item of the plan, in the shape the endpoint answers. */
interface PlanItem {
  row: number | null;
  file: string;
  code: string | null;
  size: string | null;
  category: string | null;
  upload: string | null;
  error: { code: string; message: string } | null;
}

/** A plan item for `file`, paired with the upload of the same name. */
function paired(file: string, overrides: Partial<PlanItem> = {}): PlanItem {
  return {
    row: 1,
    file,
    code: file.replace(/\.[a-z]+$/i, ''),
    size: '45X90',
    category: 'CREMA MARMOL',
    upload: file,
    error: null,
    ...overrides,
  };
}

/** A plan item the server already decided, so nothing is sent for it. */
function decided(file: string, code: string, message: string, row: number | null = null): PlanItem {
  return {
    row,
    file,
    code: null,
    size: null,
    category: null,
    upload: null,
    error: { code, message },
  };
}

/** One row response, in the shape the endpoint answers. */
function outcome(
  status: 'created' | 'flagged' | 'failed',
  extra: Record<string, unknown> = {},
): Record<string, unknown> {
  return {
    status,
    tile_id: status === 'failed' ? null : 'b41d8e06-5a72-4f39-9c88-0d3e1f7a2b65',
    flags: [],
    error: null,
    ...extra,
  };
}

/** One request the screen made, held open until a test answers it. */
interface Sent {
  path: string;
  init: RequestInit;
  /** Answer it, the way the API does. */
  answer: (status: number, body: unknown) => void;
  /** Drop the connection, the way a lost Wi-Fi hop does. */
  drop: () => void;
}

/**
 * Replace `fetch` with one that records every request and answers none.
 *
 * **Nothing resolves on its own**, which is the point: a batch is a plan
 * followed by one request per row, and holding each one open is what lets a
 * test look at the screen *between* two of them. A stub that answered
 * immediately could only ever show the finished report, which is precisely the
 * state every one of these assertions has to be able to distinguish from.
 */
function stubBatch(): Sent[] {
  const sent: Sent[] = [];

  vi.stubGlobal(
    'fetch',
    (path: string, init: RequestInit = {}) =>
      new Promise<Response>((resolve, reject) => {
        sent.push({
          path,
          init,
          answer: (status, body) =>
            resolve({
              ok: status >= 200 && status < 300,
              status,
              json: () => Promise.resolve(body),
            } as Response),
          // A `TypeError`, which is what the platform throws for a request that
          // never reached the server — and what `apiRequest` turns into
          // `network_error`.
          drop: () => reject(new TypeError('Failed to fetch')),
        });
        init.signal?.addEventListener('abort', () => {
          reject(new DOMException('The operation was aborted.', 'AbortError'));
        });
      }),
  );

  return sent;
}

/** The request at `index`, once the screen has made it. */
async function request(sent: Sent[], index: number): Promise<Sent> {
  await waitFor(() => {
    expect(sent.length).toBeGreaterThan(index);
  });
  return sent[index] as Sent;
}

/** Answer the plan request with `items`. */
async function answerPlan(sent: Sent[], items: PlanItem[]): Promise<void> {
  (await request(sent, 0)).answer(200, { items });
}

/**
 * Answer the plan and then every row, in order.
 *
 * For the tests whose subject is the finished report rather than the sequence
 * that produced it. `results` is one entry per item the plan paired.
 */
async function runBatch(
  sent: Sent[],
  items: PlanItem[],
  results: Record<string, unknown>[],
): Promise<void> {
  await answerPlan(sent, items);
  for (const [index, result] of results.entries()) {
    // Sequential on purpose: the screen sends the next row only once this one
    // has answered, so a parallel loop here would wait on requests that do not
    // exist yet.
    // eslint-disable-next-line no-await-in-loop
    (await request(sent, index + 1)).answer(200, result);
  }
}

/** Replace `fetch` with one that answers every request the same way. */
function stubFetch(reply: { status: number; body?: unknown }): { calls: [string, RequestInit][] } {
  const calls: [string, RequestInit][] = [];

  vi.stubGlobal('fetch', (input: string, init: RequestInit = {}) => {
    calls.push([input, init]);
    return Promise.resolve({
      ok: reply.status >= 200 && reply.status < 300,
      status: reply.status,
      json: () => Promise.resolve(reply.body ?? null),
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

/** The state word each row carries, in document order. */
function reportedStates(): string[] {
  return reportedRows().map((row) => {
    for (const word of ['Waiting', 'Uploading', 'Added', 'Flagged', 'Failed']) {
      if (within(row).queryByText(word) !== null) return word;
    }
    return '(none)';
  });
}

describe('the plan', () => {
  it('sends the sheet and the file names, and not one image byte', async () => {
    // **The whole reason this phase exists.** The pairing is the server's — it
    // is the only reader of the manifest — so this screen asks for it with the
    // names alone, and a sheet the server cannot use costs the Administrator
    // the sheet rather than a gigabyte of reference images.
    const sent = stubBatch();
    renderScreen();

    chooseSheet();
    chooseImages([anImage('row-1.jpg'), anImage('row-2.jpg')]);
    submit();

    const plan = await request(sent, 0);
    expect(plan.path).toBe(PLAN);
    expect(plan.init.method).toBe('POST');
    // A `FormData`, not JSON. `JSON.stringify(formData)` is `'{}'` — not an
    // error, just an empty object — so a body of files would arrive as nothing
    // at all with every type check in the app satisfied.
    expect(plan.init.body).toBeInstanceOf(FormData);

    const body = plan.init.body as FormData;
    // As a set, so the assertion is about which parts were sent and not about
    // the order `FormData` happened to keep them in.
    expect(new Set(body.keys())).toEqual(new Set(['manifest', 'names']));
    expect((body.get('manifest') as File).name).toBe('codes.csv');
    // Strings, not files. A `File` here would be the whole batch travelling to
    // be told which row wants it.
    expect(body.getAll('names')).toEqual(['row-1.jpg', 'row-2.jpg']);
    expect(body.getAll('names').every((name) => typeof name === 'string')).toBe(true);
  });

  it('paints every row of the report before their images are sent', async () => {
    // **The assertion this whole split buys.** The plan names one item per line
    // the report will carry, so the Administrator sees the pairing — every row,
    // its number, its file and its Code — while the images are still on their
    // own machine. A screen that rendered rows only as they completed would
    // show an empty list here.
    const sent = stubBatch();
    renderScreen();

    chooseSheet();
    chooseImages([anImage('row-1.jpg'), anImage('row-2.jpg'), anImage('row-3.jpg')]);
    submit();

    await answerPlan(sent, [
      paired('row-1.jpg', { row: 1 }),
      paired('row-2.jpg', { row: 2 }),
      paired('row-3.jpg', { row: 3 }),
    ]);

    await waitFor(() => {
      expect(reportedRows()).toHaveLength(3);
    });
    expect(screen.getByText('row-2.jpg')).toBeTruthy();
    expect(screen.getByText('row-3.jpg')).toBeTruthy();
    // One row in flight and two still waiting — so two of the three are on
    // screen with nothing of theirs yet sent, which is the claim.
    await waitFor(() => {
      expect(reportedStates()).toEqual(['Uploading', 'Waiting', 'Waiting']);
    });
    expect(sent).toHaveLength(2);
  });

  it('gives the bar a real denominator from the moment the plan lands', async () => {
    // The plan's length is the server's own count of report lines — one per
    // manifest row, one per file no row names — rather than a guess from the
    // number of files chosen, which is a different number for exactly the batch
    // a report is most needed for: one file, two rows naming it.
    const sent = stubBatch();
    renderScreen();

    chooseSheet();
    chooseImages([anImage('row-1.jpg')]);
    submit();

    await answerPlan(sent, [
      paired('row-1.jpg', { row: 1 }),
      paired('row-1.jpg', { row: 2, code: 'RP.CMA.0002DJ.SM.0T' }),
    ]);

    const bar = await screen.findByRole('progressbar');
    await waitFor(() => {
      expect(bar.getAttribute('aria-valuemax')).toBe('2');
    });
    expect(bar.getAttribute('aria-valuenow')).toBe('0');
    expect(screen.getByText('0 of 2 rows')).toBeTruthy();
  });

  it('never sends an image for an item the plan already decided', async () => {
    // A row nothing could be paired with, and a file no row names. Both are
    // report lines the server settled from the sheet alone, so sending either
    // would be spending a transfer on an answer already in hand.
    const sent = stubBatch();
    renderScreen();

    chooseSheet();
    chooseImages([anImage('row-1.jpg'), anImage('stray.jpg')]);
    submit();

    await answerPlan(sent, [
      decided('absent.jpg', 'image_not_paired', 'No image in this upload is named absent.jpg.', 1),
      decided('stray.jpg', 'image_unmatched', 'No row of the sheet names this image.'),
    ]);

    await waitFor(() => {
      expect(reportedStates()).toEqual(['Failed', 'Failed']);
    });
    // The plan, and nothing after it: neither line had anything to send.
    expect(sent).toHaveLength(1);
    expect(screen.getByText('No image in this upload is named absent.jpg.')).toBeTruthy();
    expect(screen.getByText('No row of the sheet names this image.')).toBeTruthy();
  });

  it('renders the server’s own sentence and no report when the batch is refused', async () => {
    // Everything that is about the batch rather than one row is refused here,
    // which is the only window in which a real envelope under a real status is
    // possible *and* nothing has been transferred.
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
    await waitFor(() => {
      expect(document.activeElement).toBe(sheet);
    });
    // No list, no summary, no partial report: nothing was planned, so there is
    // nothing to report per row.
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
    ['administrator_required', 403, 'You need to be an administrator to do that.', 'marks nothing'],
  ])('renders the %s sentence unchanged and %s', async (code, status, message, treatment) => {
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
    expect(screen.getByLabelText(/reference images/i).getAttribute('aria-invalid')).toBe('false');
    expect(reportedRows()).toEqual([]);
  });
});

describe('the rows', () => {
  it('sends one image per request, and one request at a time', async () => {
    // **Sequential, and this is where that is observable.** Each row is sixteen
    // forward passes on the server's CPU (AD-13, AD-16): four in flight at once
    // oversubscribe the same cores, so the batch finishes no sooner and every
    // individual row takes longer to report — and the peak transfer is four
    // times what splitting it was meant to avoid.
    const sent = stubBatch();
    renderScreen();

    chooseSheet();
    chooseImages([anImage('row-1.jpg'), anImage('row-2.jpg')]);
    submit();

    await answerPlan(sent, [paired('row-1.jpg', { row: 1 }), paired('row-2.jpg', { row: 2 })]);

    const first = await request(sent, 1);
    expect(first.path).toBe(ROW);
    expect(first.init.method).toBe('POST');

    const body = first.init.body as FormData;
    // The item's own fields, straight back from the plan, and exactly one
    // image. The screen decides none of these: the Code, the Size and the
    // Category are the sheet's, read by the server.
    expect(new Set(body.keys())).toEqual(new Set(['code', 'size', 'category', 'row', 'image']));
    expect(body.get('code')).toBe('row-1');
    expect(body.get('size')).toBe('45X90');
    expect(body.get('category')).toBe('CREMA MARMOL');
    expect(body.get('row')).toBe('1');
    expect((body.get('image') as File).name).toBe('row-1.jpg');

    // The second row has not been sent, and will not be until this one
    // answers. Given a chance to, so this is not merely a claim about
    // synchronous ordering.
    await waitFor(() => {
      expect(reportedStates()[0]).toBe('Uploading');
    });
    expect(sent).toHaveLength(2);

    first.answer(200, outcome('created'));
    expect((await request(sent, 2)).path).toBe(ROW);
  });

  it('resolves each row as its own request answers, not when the batch ends', async () => {
    // EXPERIENCE.md:94 — per-row status updates as they complete, not a single
    // spinner until the batch finishes. Asserted *between* two answers, which
    // is the only way to tell that from a report composed at the end.
    const sent = stubBatch();
    renderScreen();

    chooseSheet();
    chooseImages([anImage('row-1.jpg'), anImage('row-2.jpg'), anImage('row-3.jpg')]);
    submit();

    await answerPlan(sent, [
      paired('row-1.jpg', { row: 1 }),
      paired('row-2.jpg', { row: 2 }),
      paired('row-3.jpg', { row: 3 }),
    ]);

    (await request(sent, 1)).answer(200, outcome('created'));
    await waitFor(() => {
      expect(reportedStates()).toEqual(['Added', 'Uploading', 'Waiting']);
    });

    (await request(sent, 2)).answer(200, outcome('flagged', { flags: ['unknown_category'] }));
    await waitFor(() => {
      expect(reportedStates()).toEqual(['Added', 'Flagged', 'Uploading']);
    });

    (await request(sent, 3)).answer(200, outcome('created'));
    await waitFor(() => {
      expect(reportedStates()).toEqual(['Added', 'Flagged', 'Added']);
    });
  });

  it('keeps the rows in the plan’s order, whatever order they resolve in', async () => {
    // The plan states the order the report is read in — it is the sheet's own
    // order, which is the order the Administrator is holding. A list that
    // re-sorted as rows landed would move a line out from under a reader
    // mid-batch.
    const sent = stubBatch();
    renderScreen();

    chooseSheet();
    chooseImages([anImage('row-1.jpg'), anImage('row-2.jpg'), anImage('row-3.jpg')]);
    submit();

    await runBatch(
      sent,
      [
        paired('row-1.jpg', { row: 1 }),
        paired('row-2.jpg', { row: 2 }),
        paired('row-3.jpg', { row: 3 }),
      ],
      [
        outcome('failed', {
          error: { code: 'unreadable_image', message: 'Not a readable image.' },
        }),
        outcome('created'),
        outcome('flagged', { flags: ['unknown_category'] }),
      ],
    );

    await waitFor(() => {
      expect(reportedStates()).toEqual(['Failed', 'Added', 'Flagged']);
    });
    expect(reportedRows().map((row) => within(row).getByText(/row-\d\.jpg/).textContent)).toEqual([
      'row-1.jpg',
      'row-2.jpg',
      'row-3.jpg',
    ]);
  });

  it('reports a flagged row as added and says what the flag means', async () => {
    // AD-18: a flag is follow-up on a Tile that *was* created, never a softer
    // word for a refusal. The server sends a slug and no sentence, because
    // there is nothing to refuse — wording it is labelling, not deciding.
    const sent = stubBatch();
    renderScreen();

    chooseSheet();
    chooseImages();
    submit();

    await runBatch(
      sent,
      [paired('row-1.jpg', { row: 1 })],
      [outcome('flagged', { flags: ['unknown_category', 'unknown_face_number'] })],
    );

    const row = (await waitFor(() => reportedRows()))[0] as HTMLElement;
    expect(within(row).getByText('Flagged')).toBeTruthy();
    expect(within(row).getByText(/filed under UNKNOWN/i)).toBeTruthy();
    expect(within(row).getByText(/no trailing number/i)).toBeTruthy();
  });

  it('carries the server’s own sentence on a failed row', async () => {
    const sent = stubBatch();
    renderScreen();

    chooseSheet();
    chooseImages();
    submit();

    await runBatch(
      sent,
      [paired('row-1.jpg', { row: 1 })],
      [
        outcome('failed', {
          error: { code: 'code_already_exists', message: 'A tile with that code already exists.' },
        }),
      ],
    );

    expect(await screen.findByText('A tile with that code already exists.')).toBeTruthy();
  });

  it('renders a flag this build has no sentence for rather than dropping it', async () => {
    // A flag with no wording here is still a flag an Administrator has to see;
    // a row silently missing one reads as a clean success.
    const sent = stubBatch();
    renderScreen();

    chooseSheet();
    chooseImages();
    submit();

    await runBatch(
      sent,
      [paired('row-1.jpg', { row: 1 })],
      [outcome('flagged', { flags: ['some_new_marker'] })],
    );

    expect(await screen.findByText('some_new_marker')).toBeTruthy();
  });

  it('names the manifest row on every line that has one', async () => {
    // The row number is what an Administrator uses to find the offending line
    // in the sheet in front of them — a file name alone means scrolling a
    // hundred-row spreadsheet looking for it.
    const sent = stubBatch();
    renderScreen();

    chooseSheet();
    chooseImages([anImage('row-1.jpg'), anImage('row-2.jpg')]);
    submit();

    await runBatch(
      sent,
      [paired('row-1.jpg', { row: 1 }), paired('row-2.jpg', { row: 2 })],
      [outcome('created'), outcome('created')],
    );

    await waitFor(() => {
      expect(reportedRows()).toHaveLength(2);
    });
    const [first, second] = reportedRows() as [HTMLElement, HTMLElement];
    expect(within(first).getByText('Row 1')).toBeTruthy();
    expect(within(second).getByText('Row 2')).toBeTruthy();
  });

  it('gives a file no row named no row number at all', async () => {
    // `row` is a position in the *sheet*. Counting on past the manifest's end
    // would send an Administrator to row 2 of a sheet that has one.
    const sent = stubBatch();
    renderScreen();

    chooseSheet();
    chooseImages([anImage('row-1.jpg'), anImage('stray.jpg')]);
    submit();

    await runBatch(
      sent,
      [
        paired('row-1.jpg', { row: 1 }),
        decided('stray.jpg', 'image_unmatched', 'No row of the sheet names this image.'),
      ],
      [outcome('created')],
    );

    await waitFor(() => {
      expect(reportedRows()).toHaveLength(2);
    });
    const [, orphan] = reportedRows() as [HTMLElement, HTMLElement];
    expect(within(orphan).getByText('stray.jpg')).toBeTruthy();
    expect(within(orphan).queryByText(/^Row \d+$/)).toBeNull();
  });

  it('announces progress while the batch runs and when it is over', async () => {
    // A contextual sentence, not a bare number: "40" announced on its own tells
    // a screen-reader user nothing about what forty is.
    const sent = stubBatch();
    renderScreen();

    chooseSheet();
    chooseImages([anImage('row-1.jpg'), anImage('row-2.jpg')]);
    submit();

    const live = screen.getByRole('status');
    expect(live.textContent).toBe('Reading the sheet…');

    await answerPlan(sent, [paired('row-1.jpg', { row: 1 }), paired('row-2.jpg', { row: 2 })]);
    await waitFor(() => {
      expect(live.textContent).toBe('0 of 2 rows reported.');
    });

    (await request(sent, 1)).answer(200, outcome('created'));
    await waitFor(() => {
      expect(live.textContent).toBe('1 of 2 rows reported.');
    });

    (await request(sent, 2)).answer(200, outcome('created'));
    await waitFor(() => {
      expect(live.textContent).toBe('Finished.');
    });
  });

  it('counts whole rows against the plan’s total as they resolve', async () => {
    const sent = stubBatch();
    renderScreen();

    chooseSheet();
    chooseImages([anImage('row-1.jpg'), anImage('row-2.jpg')]);
    submit();

    await answerPlan(sent, [paired('row-1.jpg', { row: 1 }), paired('row-2.jpg', { row: 2 })]);
    (await request(sent, 1)).answer(200, outcome('created'));

    const bar = await screen.findByRole('progressbar');
    await waitFor(() => {
      expect(bar.getAttribute('aria-valuenow')).toBe('1');
    });
    expect(bar.getAttribute('aria-valuemax')).toBe('2');
    expect(bar.getAttribute('aria-valuetext')).toBe('1 of 2 rows reported.');
    expect(screen.getByText('1 added')).toBeTruthy();
  });

  it('opens the report as soon as the batch starts, before any row', async () => {
    // The bar is the thing that has something to say during the seconds before
    // the plan arrives.
    stubBatch();
    renderScreen();

    chooseSheet();
    chooseImages();
    submit();

    expect(await screen.findByRole('heading', { name: /^report$/i })).toBeTruthy();
    const bar = screen.getByRole('progressbar');
    // Indeterminate while there is no plan at all, which is exactly what ARIA
    // defines that to be — and the honest shape for "the sheet is still being
    // read".
    expect(bar.getAttribute('aria-valuenow')).toBeNull();
    expect(bar.getAttribute('aria-valuemax')).toBeNull();
    expect(reportedRows()).toEqual([]);
  });

  it('stamps each line with the time it resolved, and not before', async () => {
    // The gap between two stamps is the only evidence an Administrator has of
    // where a slow batch is spending its minutes. A stamp on a waiting row
    // would be the time the plan arrived dressed up as the time that row
    // finished.
    const sent = stubBatch();
    renderScreen();

    chooseSheet();
    chooseImages([anImage('row-1.jpg'), anImage('row-2.jpg')]);
    submit();

    await answerPlan(sent, [paired('row-1.jpg', { row: 1 }), paired('row-2.jpg', { row: 2 })]);
    (await request(sent, 1)).answer(200, outcome('created'));

    await waitFor(() => {
      expect(reportedStates()[0]).toBe('Added');
    });
    const [first, second] = reportedRows() as [HTMLElement, HTMLElement];
    expect(within(first).getByText(/^\d{2}:\d{2}:\d{2}$/)).toBeTruthy();
    expect(within(second).queryByText(/^\d{2}:\d{2}:\d{2}$/)).toBeNull();
  });

  it('closes the report with the counts it actually reported', async () => {
    // A summary *of* the list rather than instead of it (EXPERIENCE.md:73). It
    // states three counts and nothing derived from them — no rate, no
    // percentage, no verdict.
    const sent = stubBatch();
    renderScreen();

    chooseSheet();
    chooseImages([anImage('row-1.jpg'), anImage('row-2.jpg')]);
    submit();

    await runBatch(
      sent,
      [paired('row-1.jpg', { row: 1 }), paired('row-2.jpg', { row: 2 })],
      [outcome('created'), outcome('flagged', { flags: ['unknown_category'] })],
    );

    expect(await screen.findByText('1 added, 1 flagged, 0 failed.')).toBeTruthy();
  });

  it('re-enables its controls once the batch is over', async () => {
    // Both pickers and both buttons are disabled in flight: choosing a
    // different sheet mid-run would clear the report and then refill it from
    // the batch that is still going.
    const sent = stubBatch();
    renderScreen();

    chooseSheet();
    chooseImages();
    submit();

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /^upload$/i })).toHaveProperty('disabled', true);
    });
    expect(screen.getByLabelText(/sheet of codes/i)).toHaveProperty('disabled', true);

    await runBatch(sent, [paired('row-1.jpg', { row: 1 })], [outcome('created')]);

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /^upload$/i })).toHaveProperty('disabled', false);
    });
    expect(screen.getByLabelText(/reference images/i)).toHaveProperty('disabled', false);
    expect(screen.getByRole('button', { name: /^back$/i })).toHaveProperty('disabled', false);
  });

  it('carries list semantics even with no markers', async () => {
    // Safari and VoiceOver drop list semantics from an `<ol>` whose
    // `list-style` is `none`, and "row 4 of 30" goes with them — which on a
    // report this long is the one piece of orientation a screen-reader user
    // has.
    const sent = stubBatch();
    renderScreen();

    chooseSheet();
    chooseImages();
    submit();

    await answerPlan(sent, [paired('row-1.jpg', { row: 1 })]);
    await screen.findByText('row-1.jpg');

    const list = screen.getByRole('list');
    expect(list.tagName).toBe('OL');
    expect(list.getAttribute('role')).toBe('list');
  });
});

describe('a row that failed', () => {
  it('costs one row rather than the range when the connection drops', async () => {
    // **The failure the single-request shape could not survive**, and the whole
    // reason the transfer is split. A dropped Wi-Fi hop during a run of minutes
    // used to lose every row; here it loses the one image in flight and the
    // batch carries on.
    const sent = stubBatch();
    renderScreen();

    chooseSheet();
    chooseImages([anImage('row-1.jpg'), anImage('row-2.jpg'), anImage('row-3.jpg')]);
    submit();

    await answerPlan(sent, [
      paired('row-1.jpg', { row: 1 }),
      paired('row-2.jpg', { row: 2 }),
      paired('row-3.jpg', { row: 3 }),
    ]);

    (await request(sent, 1)).answer(200, outcome('created'));
    (await request(sent, 2)).drop();
    (await request(sent, 3)).answer(200, outcome('created'));

    await waitFor(() => {
      expect(reportedStates()).toEqual(['Added', 'Failed', 'Added']);
    });
    // The API client's own sentence, and a real one: a failed row with nothing
    // under it is a line that says something went wrong and not what.
    expect(screen.getByText(/could not reach the server/i)).toBeTruthy();
    expect(screen.getByText('2 added, 0 flagged, 1 failed.')).toBeTruthy();
  });

  it('offers to send exactly the rows that did not land', async () => {
    // Error recovery with a next step, not an error to re-read. The rows that
    // landed are untouched — they are in the catalogue, and sending them again
    // would answer `code_already_exists` for every one of them.
    const sent = stubBatch();
    renderScreen();

    chooseSheet();
    chooseImages([anImage('row-1.jpg'), anImage('row-2.jpg')]);
    submit();

    await answerPlan(sent, [paired('row-1.jpg', { row: 1 }), paired('row-2.jpg', { row: 2 })]);
    (await request(sent, 1)).answer(200, outcome('created'));
    (await request(sent, 2)).drop();

    const again = await screen.findByRole('button', { name: /send the remaining 1 row/i });
    fireEvent.click(again);

    // One further request, for the one row that failed, carrying that row's
    // own image.
    const retried = await request(sent, 3);
    expect(retried.path).toBe(ROW);
    expect(((retried.init.body as FormData).get('image') as File).name).toBe('row-2.jpg');

    retried.answer(200, outcome('created'));
    await waitFor(() => {
      expect(reportedStates()).toEqual(['Added', 'Added']);
    });
    // Two rows, two requests each way round — nothing was sent twice and no
    // row was duplicated in the report.
    expect(sent).toHaveLength(4);
    expect(screen.queryByRole('button', { name: /send the remaining/i })).toBeNull();
  });

  it('re-sends the shrunk file, not the oversized original', async () => {
    // **The retry has to reach the files as they were *sent*, not as they were
    // chosen.** A 96 MB press file is redrawn before it goes up; a second
    // attempt that read back from the picker would send the original and be
    // told `image_too_large` for a row that had been shrunk successfully
    // minutes earlier — a retry that can only ever fail.
    const encoded = stubRedraw();
    const sent = stubBatch();
    renderScreen();

    chooseSheet();
    chooseImages([aPlainJpeg('huge.jpg', MAX_IMAGE_BYTES + 1)]);
    submit();

    await answerPlan(sent, [paired('huge.jpg', { row: 1 })]);
    const first = await request(sent, 1);
    expect(((first.init.body as FormData).get('image') as File).size).toBe(encoded);
    first.drop();

    fireEvent.click(await screen.findByRole('button', { name: /send the remaining 1 row/i }));

    const retried = await request(sent, 2);
    const image = (retried.init.body as FormData).get('image') as File;
    expect(image.name).toBe('huge.jpg');
    expect(image.size).toBe(encoded);
  });

  it('does not offer to send a row the plan itself refused', async () => {
    // A row nothing could be paired with is refused by the same plan on the
    // same files, so a second attempt cannot change it — the fix is a
    // different sheet or a different selection. Offering it would be a control
    // that is guaranteed to do nothing.
    const sent = stubBatch();
    renderScreen();

    chooseSheet();
    chooseImages([anImage('row-1.jpg')]);
    submit();

    await runBatch(
      sent,
      [
        paired('row-1.jpg', { row: 1 }),
        decided(
          'absent.jpg',
          'image_not_paired',
          'No image in this upload is named absent.jpg.',
          2,
        ),
      ],
      [outcome('created')],
    );

    await waitFor(() => {
      expect(reportedStates()).toEqual(['Added', 'Failed']);
    });
    expect(screen.queryByRole('button', { name: /send the remaining/i })).toBeNull();
  });

  it('counts the plural of the offer', async () => {
    const sent = stubBatch();
    renderScreen();

    chooseSheet();
    chooseImages([anImage('row-1.jpg'), anImage('row-2.jpg')]);
    submit();

    await answerPlan(sent, [paired('row-1.jpg', { row: 1 }), paired('row-2.jpg', { row: 2 })]);
    (await request(sent, 1)).drop();
    (await request(sent, 2)).drop();

    expect(await screen.findByRole('button', { name: /send the remaining 2 rows/i })).toBeTruthy();
  });

  it('stops the whole batch on a refusal that is not about one row', async () => {
    // A model artifact that went away, an index a generation ahead, a session
    // that ended: each refuses every remaining row identically, so the loop
    // stops rather than spending a hundred requests collecting the same
    // sentence. The rows already reported are real and stay.
    const sent = stubBatch();
    renderScreen();

    chooseSheet();
    chooseImages([anImage('row-1.jpg'), anImage('row-2.jpg'), anImage('row-3.jpg')]);
    submit();

    await answerPlan(sent, [
      paired('row-1.jpg', { row: 1 }),
      paired('row-2.jpg', { row: 2 }),
      paired('row-3.jpg', { row: 3 }),
    ]);
    (await request(sent, 1)).answer(200, outcome('created'));
    (await request(sent, 2)).answer(503, {
      error: {
        code: 'pipeline_stamp_mismatch',
        message: 'The catalogue index was built by a different version of the image pipeline.',
      },
    });

    // Twice, and on purpose: once beside the pickers as the batch's own
    // refusal, and once on the row it happened to — a report whose failed line
    // said nothing would leave the Administrator matching an alert at the top
    // of the screen to a row in the middle of a hundred.
    expect(
      await screen.findAllByText(
        'The catalogue index was built by a different version of the image pipeline.',
      ),
    ).toHaveLength(2);
    expect(screen.getByRole('alert').textContent).toBe(
      'The catalogue index was built by a different version of the image pipeline.',
    );
    // Row 3 was never sent: the plan, two rows, and nothing after.
    await waitFor(() => {
      expect(screen.getByRole('status').textContent).toMatch(/the upload stopped/i);
    });
    expect(sent).toHaveLength(3);
    // The row that landed is still reported as itself; the row that met the
    // refusal says so rather than reading "Uploading" for ever; and the row
    // that was never sent is still waiting rather than being painted as a
    // failure it did not have.
    expect(reportedStates()).toEqual(['Added', 'Failed', 'Waiting']);
    // And both of the two that did not land are offered together: a control
    // that re-sent only the failed one would leave the rest of the range
    // needing a whole second upload.
    expect(await screen.findByRole('button', { name: /send the remaining 2 rows/i })).toBeTruthy();
  });
});

describe('the refusals it makes itself', () => {
  it('refuses a submit with no sheet chosen, and focuses the picker', async () => {
    const { calls } = stubFetch({ status: 200 });
    renderScreen();

    chooseImages();
    submit();

    expect(await screen.findByRole('alert')).toHaveProperty(
      'textContent',
      'Choose the sheet of codes.',
    );
    await waitFor(() => {
      expect(document.activeElement).toBe(screen.getByLabelText(/sheet of codes/i));
    });
    // Nothing was uploaded: a missing sheet must not cost a file transfer to be
    // told a picker is empty.
    expect(calls).toHaveLength(0);
  });

  it('refuses a submit with no images chosen', async () => {
    const { calls } = stubFetch({ status: 200 });
    renderScreen();

    chooseSheet();
    submit();

    expect(await screen.findByRole('alert')).toHaveProperty(
      'textContent',
      'Choose the reference images.',
    );
    await waitFor(() => {
      expect(document.activeElement).toBe(screen.getByLabelText(/reference images/i));
    });
    expect(calls).toHaveLength(0);
  });

  it('refuses more images than the endpoint takes without planning them', async () => {
    // A hundred reference images is comfortably gigabytes. The plan would
    // refuse this batch too, and refusing here saves even that round trip.
    const { calls } = stubFetch({ status: 200 });
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
    const { calls } = stubFetch({ status: 200 });
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
    const sent = stubBatch();
    renderScreen();

    chooseSheet();
    chooseImages([anImage('small.jpg'), aPlainJpeg('huge.jpg', MAX_IMAGE_BYTES + 1)]);
    submit();

    // The names are untouched, because the plan pairs on them — a shrink that
    // renamed anything would unpair the very row it was trying to help.
    const plan = await request(sent, 0);
    expect((plan.init.body as FormData).getAll('names')).toEqual(['small.jpg', 'huge.jpg']);

    await answerPlan(sent, [paired('small.jpg', { row: 1 }), paired('huge.jpg', { row: 2 })]);

    // The one that already fitted travels as chosen, byte for byte —
    // re-encoding it would spend a generation of JPEG artefacts on a problem it
    // does not have.
    const first = await request(sent, 1);
    expect(((first.init.body as FormData).get('image') as File).size).toBe(4);
    first.answer(200, outcome('created'));

    const second = await request(sent, 2);
    expect(((second.init.body as FormData).get('image') as File).size).toBe(encoded);
    expect(((second.init.body as FormData).get('image') as File).name).toBe('huge.jpg');
  });

  it('says what it did to the oversized images rather than doing it quietly', async () => {
    // The bytes indexed are not the bytes chosen. An Administrator comparing a
    // stored reference image against the file on their disk deserves to know
    // why the two differ.
    stubRedraw();
    stubBatch();
    renderScreen();

    chooseSheet();
    chooseImages([aPlainJpeg('huge.jpg', MAX_IMAGE_BYTES + 1)]);
    submit();

    expect(await screen.findByText(/huge\.jpg.*MB sent as.*MB/)).toBeTruthy();
  });

  it('retires the report when a different batch is chosen', async () => {
    // The report describes a batch that has already run; the moment a different
    // sheet is chosen it is describing something that is no longer on screen.
    const sent = stubBatch();
    renderScreen();

    chooseSheet();
    chooseImages();
    submit();

    await runBatch(sent, [paired('row-1.jpg', { row: 1 })], [outcome('created')]);
    await screen.findByText('row-1.jpg');

    chooseSheet(aSheet('other.csv'));

    await waitFor(() => {
      expect(reportedRows()).toEqual([]);
    });
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
    //
    // The two conditional controls — "Jump to latest" and the retry — are
    // absent at rest by construction, and each of them has a test above that
    // says when it appears.
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
    stubFetch({ status: 200 });
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
    const stub = stubFetch({ status: 200 });
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

describe('when the screen goes mid-batch', () => {
  it('paints nothing more after the screen has gone', async () => {
    // A batch runs for minutes and the screen can go inside that: a session
    // expiring drops the shell to the login screen, a sign-out unmounts
    // everything. Without the guard this asserts, every answer still in flight
    // is a `setState` on a component that does not exist.
    const sent = stubBatch();
    const { unmount } = render(<BulkUploadScreen onBack={(): void => undefined} />);

    chooseSheet();
    chooseImages([anImage('row-1.jpg'), anImage('row-2.jpg')]);
    submit();

    await answerPlan(sent, [paired('row-1.jpg', { row: 1 }), paired('row-2.jpg', { row: 2 })]);
    (await request(sent, 1)).answer(200, outcome('created'));
    await screen.findByText('row-1.jpg');

    // **What this can and cannot see.** React 19 dropped the
    // "state update on an unmounted component" warning, and a `setState` on a
    // detached fiber is a silent no-op — so no assertion here can distinguish
    // the guard being present from it being absent by watching React. What is
    // checked is what remains observable: the answers that arrive after the
    // screen has gone are consumed without anything throwing and without
    // anything reaching the console.
    const complained = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    try {
      unmount();
      sent[2]?.answer(200, outcome('created'));
      await waitFor(() => {
        expect(true).toBe(true);
      });

      expect(complained).not.toHaveBeenCalled();
    } finally {
      complained.mockRestore();
    }
  });

  it('abandons the request in flight when the screen unmounts', async () => {
    // Stopping the painting is only half of it: the server goes on embedding a
    // row for a request nobody will read — sixteen forward passes and two
    // object writes, spent on a screen that has gone. The abort is what closes
    // it, and the request's own signal is where that is observable.
    const sent = stubBatch();
    const { unmount } = render(<BulkUploadScreen onBack={(): void => undefined} />);

    chooseSheet();
    chooseImages();
    submit();

    await answerPlan(sent, [paired('row-1.jpg', { row: 1 })]);
    const row = await request(sent, 1);
    expect(row.init.signal?.aborted).toBe(false);

    unmount();

    expect(row.init.signal?.aborted).toBe(true);
  });

  it('drops to the login screen when the batch is refused as signed out', async () => {
    // A batch runs for minutes, which makes it the likeliest place in the
    // product for a session to expire under a request. A refusal that only
    // rejected the caller would leave the shell rendering an admin surface
    // over a session the server has stopped honouring.
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
              asked === 1 ? ADMIN : { error: { code: 'unauthorized', message: 'Not signed in.' } },
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
        json: () => Promise.resolve({ error: { code: 'unauthorized', message: 'Not signed in.' } }),
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

    expect(
      await screen.findByText(/your session has ended\. sign in again to continue\./i),
    ).toBeTruthy();
    expect(screen.queryByRole('heading', { name: /^bulk upload$/i })).toBeNull();
  });
});
