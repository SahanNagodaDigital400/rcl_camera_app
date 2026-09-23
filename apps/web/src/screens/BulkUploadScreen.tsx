import { CheckCircle, Warning, XCircle } from '@phosphor-icons/react';
import { useEffect, useId, useRef, useState } from 'react';
import type { ChangeEvent, FormEvent, JSX } from 'react';

import {
  ApiRequestError,
  INVALID_MANIFEST,
  MALFORMED_RESPONSE,
  ROW_FAILED,
  TOO_MANY_ROWS,
  apiStream,
} from '../api/client';
import styles from './BulkUploadScreen.module.css';

/**
 * Bulk upload — a whole range in one pass, reported row by row (FR-17).
 *
 * Rendered *inside* the shell, in place of the home panel, so it carries no
 * `<main>` of its own: `AppShell` already provides the one main landmark and
 * the focus target the gate moves focus to on a screen swap. It is modelled on
 * `AddTileScreen` — same form rhythm, same one-alert-in-one-slot treatment,
 * same accent submit beside a navy-outlined Back — because an Administrator
 * moving between the two catalogue upload surfaces should not read them as two
 * different applications.
 *
 * **The report is the deliverable, not the spinner.** EXPERIENCE.md:73 asks for
 * a scrollable per-row list and explicitly not a single pass/fail summary, and
 * EXPERIENCE.md:94 asks for the rows to arrive *as they complete*. That is why
 * this screen calls `apiStream` rather than `apiRequest`: a body read with
 * `await response.json()` does not return until the batch ends, and a report
 * that appears all at once when the batch ends is the single spinner both those
 * lines exist to forbid.
 *
 * **Three outcomes, three colours, and a word beside each** (DESIGN.md:144-149
 * and :221 — the one screen in the product where all three brand colours appear
 * as status indicators together). Navy for created, orange for flagged, red for
 * failed. The word is not decoration: EXPERIENCE.md's accessibility floor says
 * a state is never signalled by colour alone, and a colour-blind Administrator
 * reading a hundred-row report is precisely who that rule is for.
 *
 * **A flagged row is a success.** It was created, it has a tile id, and it is in
 * the index; the flag is follow-up (AD-18) — a Category nothing could recover,
 * a Code with no trailing number, a reference image with very little texture.
 * Painting it as a failure would tell an Administrator to re-upload a tile that
 * is already in the catalogue.
 *
 * **Every rule belongs to the server.** This screen does not parse the
 * manifest, does not derive a trailing number from a Code, and does not decide
 * what makes a row a failure rather than a flag. It renders what the stream
 * says. A second implementation of any of those rules here is the asymmetry
 * AD-1 is about, one level up from the pixels — and the manifest parser is the
 * one the real catalogue's five naming conventions would break first.
 *
 * **The role-conditional door that opens this screen is a convenience, never
 * the control.** `App` renders it only for an Administrator, but the cached
 * `User` is a render cache and never an authorization decision (AGENTS.md
 * Policy): the server refuses a Staff caller at `POST /admin/tiles/bulk`
 * through `require_administrator`, which re-reads the role from Postgres on
 * every request (AD-3).
 *
 * Deliberately absent:
 *
 * - **No dry run, no resume, no retry-failed-rows.** A failed row is a row to
 *   fix and send again, and a second verb that re-sent a subset would be a
 *   second way into the same endpoint with its own rules about what a batch is.
 * - **No per-row progress percentage.** A row is either reported or it is not;
 *   a percentage inside one would be an invented number, and this product has
 *   a standing rule against those (AD-20).
 * - **No ZIP or folder upload.** The images are a file list, which is what a
 *   file input gives and what a multipart body carries.
 * - **No similarity value, in any form** (AD-20). There is nothing to show one
 *   for on this screen and there never will be.
 */

/** Shown for a failure that arrives as something other than an `ApiRequestError`. */
const UNEXPECTED = 'The batch could not be uploaded. Try again.';

/**
 * Refuse an empty picker here rather than letting the API answer for it.
 *
 * The form is `noValidate` — the browser's own bubble is unstyled, untestable
 * and disappears on the next keystroke — so these are what `required` would
 * otherwise have done. Without them a blank submit opens a stream that can only
 * report that nothing was sent.
 */
const NO_MANIFEST = 'Choose the sheet of codes.';
const NO_FILES = 'Choose the reference images.';

/**
 * The server's own bounds, mirrored onto this screen.
 *
 * **The server's copy is the authority** — `shared_schema.tile` bounds both and
 * the endpoint answers with a named refusal past them, whatever this file says.
 * These exist to keep a transfer that was never going to be accepted off the
 * wire: a hundred reference images is comfortably gigabytes, and an
 * Administrator who watched that upload finish only to be told the row cap was
 * never going to be honoured has lost the transfer, not a rule check.
 *
 * Written down here rather than imported because nothing crosses that boundary
 * at build time; `error-code-parity.test.ts` pins each against its Python twin,
 * so a drift is a failing test rather than a silent divergence.
 */
const MAX_BULK_ROWS = 100;
const MAX_IMAGE_BYTES = 134217728;

/**
 * The count refusal.
 *
 * One ceiling bounds a bulk upload on both counts — the manifest's rows and
 * the uploaded images — and the server enforces it on both. This screen never
 * reads the manifest, so images is the count it has; refusing on that one is
 * therefore stating the server's own rule rather than a second one, and the
 * server refuses the same batch with `too_many_rows` whatever this says.
 * Worded about the images, because that is what the Administrator is holding
 * when this fires.
 */
const TOO_MANY_FILES =
  `Upload at most ${MAX_BULK_ROWS} reference images at a time. ` +
  'Split a larger range into two batches.';
const FILE_TOO_LARGE = `Each reference image must be under ${
  MAX_IMAGE_BYTES / (1024 * 1024)
} MB.`;

/**
 * The starter sheet this screen hands out, and the name it saves under.
 *
 * **A template is not a second reader.** The columns are the three
 * `catalogue.py` requires (`MANIFEST_COLUMNS`) plus the one it may take
 * (`MANIFEST_OPTIONAL_COLUMN`); nothing here parses, validates or infers
 * anything, and a sheet built from this template is read by the server exactly
 * as a hand-made one is. `error-code-parity.test.ts` pins the header line
 * against those two Python constants, so a column renamed on the server fails a
 * test rather than leaving a template that quietly teaches the wrong header.
 *
 * The example lines are shapes the source tree really carries rather than
 * `foo,bar`: a structured Code, an underscore-suffixed one, a bare one whose
 * case is part of it (`1Jk`), a `.tif` beside the `.jpg`s, and a last line that
 * leaves the Category empty — which is not an error (AD-18) and is the one
 * thing about this sheet nobody guesses unprompted.
 *
 * No value here contains a comma or a quotation mark, so the lines are written
 * out rather than assembled by an escaper this screen would otherwise have to
 * own. A Code that needed one is the Administrator's to quote in their own
 * spreadsheet, which is what a spreadsheet does on export.
 */
const TEMPLATE_COLUMNS = ['file', 'code', 'size', 'category'];
const TEMPLATE_LINES = [
  'RP.CMA.0008DJ.SM.0T.jpg,RP.CMA.0008DJ.SM.0T,45X90,CREMA MARMOL',
  '77DH.MA_F3.jpg,77DH.MA_F3,60X60,ASTORIA',
  '1Jk.jpg,1Jk,45X90,POLISH',
  '279.tif,279,40X40,',
];
const TEMPLATE_NAME = 'rocell-bulk-upload-template.csv';
const TEMPLATE_CSV = `${[TEMPLATE_COLUMNS.join(','), ...TEMPLATE_LINES].join('\n')}\n`;

/**
 * The template as something a browser will save, built once at module scope.
 *
 * **A `data:` URL rather than a `Blob` and `URL.createObjectURL`.** The bytes
 * are five lines of text known at build time, so the blob apparatus — a
 * creation per click, an object URL to revoke, a lifetime tied to the document
 * — buys nothing and leaks something: an unrevoked object URL is held until the
 * page goes away, and this is a control an Administrator may press twice.
 *
 * Nothing is fetched and no request leaves the app, which is how this keeps
 * AD-6 ("apps/web talks to nothing but apps/api") — by talking to nobody. It is
 * also why the download needs no session: the file is this screen's own source,
 * not catalogue data, and it says nothing a signed-out visitor could not read
 * off the hint above it.
 */
const TEMPLATE_HREF = `data:text/csv;charset=utf-8,${encodeURIComponent(TEMPLATE_CSV)}`;

/** The spoken states of the progress line. See `progress` below. */
const UPLOADING = 'Uploading…';
const FINISHED = 'Finished.';

/**
 * The report did not run to the end of the batch.
 *
 * Two ways in. The connection itself went — a proxy timing out, the process
 * going away mid-report — and the closing line never arrived. Or the server
 * said it stopped: it writes a summary even when a batch stops part-way, so a
 * summary alone is not proof of a clean finish and the line it sent saying so
 * is. The rows already on screen are real and stay; what
 * this says is that the ones after them never ran. Blanking the progress line
 * instead would read exactly like a batch that finished cleanly.
 */
const CUT_SHORT = 'The report stopped early. The rows below were finished; send the rest again.';

/** Which picker a failure is about — and therefore which one is marked and focused. */
type Field = 'manifest' | 'images';

/**
 * What went wrong, and which picker is at fault.
 *
 * `fieldAtFault` is not decoration: it drives `aria-invalid` and focus. Marking
 * a control invalid because the model artifact is missing on the server tells a
 * screen-reader user their choice was wrong when it was not.
 */
interface FormError {
  message: string;
  fieldAtFault: Field | null;
}

/**
 * The three outcomes the stream reports, and the three DESIGN.md paints.
 *
 * Exactly these: a `status` this screen does not recognise is a server speaking
 * a protocol this build does not know, which `asRow` refuses loudly rather than
 * painting in a fourth, undefined treatment.
 */
type Outcome = 'created' | 'flagged' | 'failed';

/** One line of the report, as the screen holds it. */
interface ReportRow {
  /**
   * The position this line arrived at, assigned on arrival. React's list key,
   * and it is carried on the row rather than taken from the render index
   * because none of the fields the server sends can serve: two lines may
   * legitimately name one file — that is the `image_not_paired` case — and a
   * trailing line for an unmatched upload has no manifest row number at all.
   */
  seq: number;
  /**
   * The line's number in the *manifest*, or `null`.
   *
   * Rendered on the row, because it is what an Administrator uses to find the
   * offending line in the sheet in front of them — a file name alone means
   * scrolling a hundred-row spreadsheet looking for it. `null` on the lines
   * that have no manifest row at all: an upload no row named, and the line
   * that reports the batch stopping.
   */
  row: number | null;
  /** The file name, which is the one field every line carries. */
  file: string;
  /** The Code, or `null` on a line that never reached one. */
  code: string | null;
  status: Outcome;
  /** Follow-up markers on a row that *was* created (AD-18). */
  flags: string[];
  /** The `{code, message}` of a refusal, in the envelope's own shape. */
  error: { code: string; message: string } | null;
}

/** The closing line: how the batch came out. */
interface Summary {
  created: number;
  flagged: number;
  failed: number;
}

/** The word beside each indicator. Never the colour alone — see the docstring. */
const WORD: Record<Outcome, string> = {
  created: 'Added',
  flagged: 'Flagged',
  failed: 'Failed',
};

/**
 * What a flag means, in words.
 *
 * The server sends a slug and no sentence for a flagged row, because a flag is
 * not a refusal and there is nothing to refuse. Wording it is labelling, not
 * deciding — the screen states what the server already concluded, and states
 * nothing the server did not.
 *
 * An unrecognised slug falls through to itself rather than being dropped: a
 * flag this build has no sentence for is still a flag an Administrator has to
 * see, and a row silently missing one reads as a clean success.
 */
const FLAG_WORDS: Record<string, string> = {
  unknown_category: 'No category could be recovered — filed under UNKNOWN.',
  unknown_face_number: 'The code carries no trailing number.',
  low_quality_image: 'Very little visible texture, so scans may not find this tile reliably.',
};

function flagSentence(flag: string): string {
  return FLAG_WORDS[flag] ?? flag;
}

/**
 * The row's colour class, named one branch at a time.
 *
 * `styles[row.status]` would be shorter and would read the same three classes,
 * and it is deliberately not used: `styling-wiring.test.ts` finds a stylesheet's
 * consumers by matching `styles.<name>` in the source, so a class reached only
 * through a computed key is a class that test reports as declared and
 * unreferenced. Naming them is what keeps the stylesheet and this file held
 * together.
 */
function outcomeClass(status: Outcome): string | undefined {
  if (status === 'created') return styles.created;
  if (status === 'flagged') return styles.flagged;
  return styles.failed;
}

/**
 * The indicator glyph. Phosphor at `regular` (outline) weight, which is the
 * library default — no `weight` prop is passed here or anywhere, and
 * `no-raw-values.test.ts` fails the build if one ever is (UX-DR3).
 *
 * `aria-hidden`, because the word beside it carries the state. Announced as
 * well, it would read every row's outcome twice.
 */
function outcomeIcon(status: Outcome): JSX.Element {
  if (status === 'created') return <CheckCircle className={styles.icon} aria-hidden="true" />;
  if (status === 'flagged') return <Warning className={styles.icon} aria-hidden="true" />;
  return <XCircle className={styles.icon} aria-hidden="true" />;
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

/** The rejection thrown when the stream stops speaking the protocol mid-report. */
function malformed(): ApiRequestError {
  return new ApiRequestError(
    MALFORMED_RESPONSE,
    'The server returned an unexpected response.',
    200,
  );
}

/**
 * Narrow one `kind: "row"` line, or fail loudly.
 *
 * **Deliberately not closed the way `isTile` is.** That contract rejects any
 * extra key, because an extra key there is how a storage reference (AD-9) or a
 * similarity score (AD-20) would arrive unnoticed. Here the cost of the same
 * strictness is different in kind: an added server field would make the screen
 * refuse *every* batch, including the hundred rows that were about to be
 * created, and a field this screen does not read is a field it cannot render.
 * So the fields that are painted are checked and the rest is ignored — with the
 * one thing that decides a row's treatment, `status`, checked hardest.
 */
function asRow(line: Record<string, unknown>, seq: number): ReportRow {
  const status = line['status'];
  const file = line['file'];
  if (
    typeof file !== 'string' ||
    (status !== 'created' && status !== 'flagged' && status !== 'failed')
  ) {
    throw malformed();
  }

  const code = line['code'];
  const row = line['row'];
  const flags = line['flags'];
  const failure = line['error'];

  return {
    seq,
    row: typeof row === 'number' ? row : null,
    file,
    code: typeof code === 'string' ? code : null,
    status,
    flags: Array.isArray(flags)
      ? flags.filter((flag): flag is string => typeof flag === 'string')
      : [],
    error:
      isObject(failure) &&
      typeof failure['code'] === 'string' &&
      typeof failure['message'] === 'string'
        ? { code: failure['code'], message: failure['message'] }
        : null,
  };
}

/**
 * Which picker a server refusal belongs to, if any.
 *
 * `AddTileScreen.fieldFor`'s job on this form. The two refusals that are about
 * the sheet mark the sheet: a manifest the server cannot read and a manifest
 * over the row cap are both answers about the file in that picker, and the
 * matrix asks for the sentence to be rendered next to it. `matching_unavailable`,
 * `pipeline_stamp_mismatch` and `administrator_required` land at `null`
 * deliberately — nothing the Administrator chose is at fault for a missing
 * model artifact, a stale stamp or a role, and marking a control for one of
 * those tells a screen-reader user their choice was wrong when it was not.
 */
function fieldFor(failure: unknown): Field | null {
  if (!(failure instanceof ApiRequestError)) return null;
  if (failure.code === INVALID_MANIFEST || failure.code === TOO_MANY_ROWS) return 'manifest';
  return null;
}

/** Narrow one `kind: "summary"` line, or fail loudly. */
function asSummary(line: Record<string, unknown>): Summary {
  const created = line['created'];
  const flagged = line['flagged'];
  const failed = line['failed'];
  if (typeof created !== 'number' || typeof flagged !== 'number' || typeof failed !== 'number') {
    throw malformed();
  }
  return { created, flagged, failed };
}

export function BulkUploadScreen({ onBack }: { onBack: () => void }): JSX.Element {
  const manifestId = useId();
  const imagesId = useId();
  const errorId = useId();
  const manifestHintId = useId();
  const imagesHintId = useId();
  const reportId = useId();

  const [manifest, setManifest] = useState<File | null>(null);
  const [files, setFiles] = useState<File[]>([]);
  const [rows, setRows] = useState<ReportRow[]>([]);
  const [summary, setSummary] = useState<Summary | null>(null);
  /** The stream ended with no closing line. See `CUT_SHORT`. */
  const [cutShort, setCutShort] = useState(false);
  const [error, setError] = useState<FormError | null>(null);
  const [running, setRunning] = useState(false);

  const manifestRef = useRef<HTMLInputElement>(null);
  const imagesRef = useRef<HTMLInputElement>(null);

  /**
   * Whether this screen is still mounted, and the handle that stops the batch.
   *
   * A batch runs for minutes, and in that time the screen can go: a session
   * expiring drops the shell to the login screen, a sign-out unmounts
   * everything. Without these, `onLine` would go on calling `setRows` on a
   * component that no longer exists, and — worse — the server would go on
   * processing a hundred rows into a stream nobody is reading. The guard stops
   * the first and the abort stops the second.
   *
   * A ref, not state: it is read inside a callback that closes over its own
   * render, and a state value there would be the value at the time the batch
   * started rather than the value now.
   */
  const alive = useRef(true);
  const runningBatch = useRef<AbortController | null>(null);

  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      runningBatch.current?.abort();
    };
  }, []);

  function focus(field: Field): void {
    (field === 'manifest' ? manifestRef : imagesRef).current?.focus();
  }

  /**
   * A control to focus once the form is interactive again.
   *
   * Both pickers are `disabled` while a batch streams, and `focus()` on a
   * disabled control does nothing at all — so a server refusal, which arrives
   * while the run is still ending, would mark the sheet and leave focus on the
   * Upload button. Recorded here and spent by the effect below, once the
   * render that re-enables the control has happened.
   */
  const focusWhenIdle = useRef<Field | null>(null);

  useEffect(() => {
    if (running) return;
    const pending = focusWhenIdle.current;
    focusWhenIdle.current = null;
    // The picker is reached through its ref rather than through `focus` above,
    // which is redeclared every render and would make this effect depend on a
    // new function each time.
    if (pending !== null) (pending === 'manifest' ? manifestRef : imagesRef).current?.focus();
  }, [running]);

  function refuse(message: string, field: Field | null): void {
    setError({ message, fieldAtFault: field });
    if (field === null) return;
    // Straight away when nothing is in flight — the screen's own refusals are
    // decided before the request — and deferred when a batch is still ending.
    // Read off the batch handle rather than off `running`, which in a submit's
    // own closure is the value it had when the button was pressed: `false`,
    // however long the batch has been going since.
    if (runningBatch.current !== null) focusWhenIdle.current = field;
    else focus(field);
  }

  /**
   * Take a new choice, and retire the report beside it.
   *
   * The report describes a batch that has already run; the moment a different
   * sheet or a different set of images is chosen it is describing something
   * that is no longer on screen.
   */
  function chooseManifest(event: ChangeEvent<HTMLInputElement>): void {
    setError(null);
    setRows([]);
    setSummary(null);
    setCutShort(false);
    setManifest(event.target.files?.[0] ?? null);
  }

  function chooseFiles(event: ChangeEvent<HTMLInputElement>): void {
    setError(null);
    setRows([]);
    setSummary(null);
    setCutShort(false);
    setFiles([...(event.target.files ?? [])]);
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    if (running) return;

    if (manifest === null) {
      refuse(NO_MANIFEST, 'manifest');
      return;
    }
    if (files.length === 0) {
      refuse(NO_FILES, 'images');
      return;
    }
    if (files.length > MAX_BULK_ROWS) {
      refuse(TOO_MANY_FILES, 'images');
      return;
    }
    if (files.some((file) => file.size > MAX_IMAGE_BYTES)) {
      refuse(FILE_TOO_LARGE, 'images');
      return;
    }

    setRunning(true);
    setError(null);
    setRows([]);
    setSummary(null);
    setCutShort(false);

    const batch = new AbortController();
    runningBatch.current = batch;
    /** Whether the closing line arrived. See the check after the stream ends. */
    let closed = false;
    /**
     * The server said it stopped before every row was processed.
     *
     * It says so on a line and then still writes a summary, because the status
     * was committed at the first byte and a summary that never came would be
     * indistinguishable from a dropped connection. So the summary arriving is
     * not proof the batch finished, and the progress line may not read it that
     * way — "Finished." above a row saying the upload stopped is the screen
     * contradicting its own report.
     */
    let stoppedEarly = false;
    /**
     * How many lines have been painted, counted here rather than inside the
     * `setRows` updater below.
     *
     * A local, so a second batch — which clears the list — numbers from zero
     * again with nothing to reset. Counted out here because `asRow` throws on
     * a line this build cannot paint, and a throw inside a state updater
     * surfaces during React's render rather than at this call site: past the
     * `catch` below, past `apiStream`'s cancellation of the body, and into the
     * app as an unhandled render failure. Narrowing before the dispatch is
     * what keeps that refusal on the path written for it.
     */
    let arrived = 0;

    // Multipart, because the request carries files. The part names are the
    // endpoint's parameter names; `images` repeats once per file, which is how
    // a multipart body expresses a list.
    const body = new FormData();
    body.append('manifest', manifest);
    for (const file of files) body.append('images', file);

    try {
      await apiStream(
        '/admin/tiles/bulk',
        { method: 'POST', body, signal: batch.signal },
        (line) => {
          if (!isObject(line)) throw malformed();
          // Nothing is painted after the screen has gone. The abort above has
          // already asked the server to stop; this is what keeps the lines
          // still in flight from reaching a component that is not there.
          if (!alive.current) return;
          // `kind` discriminates the two shapes. A line that is neither is the
          // same protocol failure a malformed line is: this screen paints rows
          // and one summary, and there is no third thing it could do with one.
          if (line['kind'] === 'row') {
            const painted = asRow(line, arrived);
            arrived += 1;
            // The batch stopping is reported as a failed row with no manifest
            // row number, because by then there is no status left to carry it.
            // Read here rather than rendered specially: the line is a real
            // report row and belongs in the list like any other — what it
            // changes is only what the progress line is allowed to say.
            if (painted.error?.code === ROW_FAILED && painted.row === null) stoppedEarly = true;
            // Appended, never sorted or grouped. The order rows arrive in is
            // the order they were processed in, and that is the order an
            // Administrator watched them appear in.
            setRows((already) => [...already, painted]);
            return;
          }
          if (line['kind'] === 'summary') {
            setSummary(asSummary(line));
            closed = true;
            return;
          }
          throw malformed();
        },
      );
      // The body ended. If the closing line never came the connection went
      // rather than the batch finishing, and if the server said it stopped
      // then it stopped — either way, say so instead of letting the progress
      // line report a clean finish (see `CUT_SHORT`). Tracked on locals rather
      // than read off `summary` and `rows`, which are this render's values and
      // are still empty here however many lines arrived.
      if (alive.current && (!closed || stoppedEarly)) setCutShort(true);
    } catch (failure) {
      // The API's own message, so the screen cannot state a rule the server
      // does not enforce. Whatever rows arrived before the failure stay on
      // screen: they were created, and clearing them would report a tile that
      // is in the catalogue as one that is not.
      //
      // A pre-stream refusal — no manifest, too many rows, no model artifact, a
      // stale stamp — lands here with no rows behind it, which is what leaves
      // the report list absent entirely.
      if (alive.current) {
        refuse(
          failure instanceof ApiRequestError ? failure.message : UNEXPECTED,
          fieldFor(failure),
        );
      }
    } finally {
      if (runningBatch.current === batch) runningBatch.current = null;
      if (alive.current) setRunning(false);
    }
  }

  // One expression rather than a nested ternary in the markup. The live region
  // is in the document at rest so the change of text is what gets announced,
  // rather than the arrival of a whole new node.
  //
  // There is no "row 4 of 30" here because this screen does not know the
  // denominator: the manifest is the server's to read, and inventing a total
  // from the number of images chosen would be wrong for every batch whose rows
  // and files do not line up — which is exactly the batch this report is for.
  let progress = '';
  if (running) progress = rows.length === 0 ? UPLOADING : `${rows.length} reported.`;
  else if (cutShort) progress = CUT_SHORT;
  else if (summary !== null) progress = FINISHED;

  // One node, rendered directly below whichever picker is at fault — and after
  // both when the failure belongs to neither. A form with two controls and one
  // error parked under both leaves a screen-reader user on the wrong one
  // hearing a sentence about the other. Only one of the three slots below is
  // ever filled, so this screen never renders a second alert.
  const alert =
    error === null ? null : (
      <p className={styles.error} id={errorId} role="alert">
        {error.message}
      </p>
    );

  return (
    <section className={styles.screen}>
      <h1 className={styles.title}>Bulk upload</h1>

      <form className={styles.form} onSubmit={(event) => void handleSubmit(event)} noValidate>
        <div className={styles.field}>
          <label className={styles.label} htmlFor={manifestId}>
            Sheet of codes
          </label>
          {/* `accept` is a *hint to the file picker*, never a check: the server
              reads the bytes and answers `invalid_manifest` for anything it
              cannot parse. A screen that refused by extension would be
              validating nothing, and the sentence the server sends names the
              fix rather than describing the problem. */}
          <input
            className={styles.file}
            id={manifestId}
            name="manifest"
            type="file"
            accept=".csv,text/csv"
            ref={manifestRef}
            // Disabled in flight, like both buttons. Choosing a different
            // sheet mid-run clears the report and then refills it from the
            // batch that is still going, so the list would describe one
            // upload under the heading of another.
            disabled={running}
            aria-invalid={error?.fieldAtFault === 'manifest'}
            aria-describedby={
              error?.fieldAtFault === 'manifest' ? `${manifestHintId} ${errorId}` : manifestHintId
            }
            onChange={chooseManifest}
          />
          <p className={styles.hint} id={manifestHintId}>
            One CSV, with a header row and a column for the file name, the code and the size.
            Up to {MAX_BULK_ROWS} rows — the sheet is read on the server, so a longer one is
            refused only after it has been sent. Category is optional — a row without one is filed
            under UNKNOWN and flagged. Export a spreadsheet as CSV and upload that.
          </p>
          {/* The template. An anchor and not a button: there is nothing to
              fetch and nothing to generate, and saving a file is what a browser
              already knows how to do with one — no click handler, no state, and
              it keeps working under a middle-click or a right-click Save as.
              Navy rather than accent: Upload is this screen's one orange action
              (DESIGN.md), and the budget here is tighter than anywhere else
              because orange is also the flagged-row signal below. */}
          <a className={styles.template} href={TEMPLATE_HREF} download={TEMPLATE_NAME}>
            Download a template sheet
          </a>
          {error?.fieldAtFault === 'manifest' && alert}
        </div>

        <div className={styles.field}>
          <label className={styles.label} htmlFor={imagesId}>
            Reference images
          </label>
          {/* `image/*` deliberately wide, for `AddTileScreen`'s reason: content
              decides and only the server can sniff it (AGENTS.md Policy), and
              the real catalogue holds `.tif` alongside `.jpg`. */}
          <input
            className={styles.file}
            id={imagesId}
            name="images"
            type="file"
            accept="image/*"
            multiple
            ref={imagesRef}
            disabled={running}
            aria-invalid={error?.fieldAtFault === 'images'}
            aria-describedby={
              error?.fieldAtFault === 'images' ? `${imagesHintId} ${errorId}` : imagesHintId
            }
            onChange={chooseFiles}
          />
          <p className={styles.hint} id={imagesHintId}>
            One image per row, named as the sheet names it. Up to {MAX_BULK_ROWS} at a time, each
            under {MAX_IMAGE_BYTES / (1024 * 1024)} MB. A batch can take several minutes — each
            image is indexed before it is stored, and rows are reported as they finish.
          </p>
          {error?.fieldAtFault === 'images' && alert}
        </div>

        {/* A failure that belongs to neither picker — the request never reached
            the API, the server has no image pipeline installed, or the stream
            was refused before it opened. Inserted rather than emptied and
            refilled: a `role="alert"` node appearing in the document is what
            announces it. */}
        {error !== null && error.fieldAtFault === null && alert}

        <div className={styles.actions}>
          {/* The screen's one accent control (DESIGN.md: exactly one per
              screen). Back is the secondary, navy-outlined one. */}
          <button className={styles.submit} type="submit" disabled={running}>
            Upload
          </button>
          {/* Disabled in flight, exactly as the submit is: a click that
              unmounted this screen mid-batch would leave the Administrator
              unsure which rows had landed — and the rows already created stay
              created, because each one is its own transaction. */}
          <button className={styles.back} type="button" onClick={onBack} disabled={running}>
            Back
          </button>
          <span className={styles.indicator} role="status">
            {progress}
          </span>
        </div>
      </form>

      {rows.length > 0 && (
        // A labelled region, deliberately **not** a second live region. The
        // progress line above already announces that rows are arriving;
        // marking the list `role="status"` as well would read every row out in
        // full as it appeared, which on a hundred-row batch is the report
        // narrated twice over. A screen reader reaches it by its heading,
        // which is what a region is for.
        <section className={styles.report} aria-labelledby={reportId}>
          <h2 className={styles.subtitle} id={reportId}>
            Report
          </h2>
          {/* `role="list"` restated on a list that has no markers. Safari and
              VoiceOver drop list semantics from an `<ol>` whose `list-style`
              is `none` — the rows stop being announced as "list, 30 items" and
              "row 4 of 30" goes with them, which on a report this long is the
              one piece of orientation a screen-reader user has. Redundant in
              every other browser and harmless there. */}
          <ol className={styles.rows} role="list">
            {rows.map((row) => (
              <li key={row.seq} className={`${styles.row} ${outcomeClass(row.status)}`}>
                <span className={styles.outcome}>
                  {outcomeIcon(row.status)}
                  <span className={styles.word}>{WORD[row.status]}</span>
                </span>
                {/* The manifest row, where there is one. This is what an
                    Administrator looks up in the sheet in front of them, so it
                    leads the line rather than sitting after the file name.
                    Absent on the lines that have no row — an upload nothing
                    named, and the one that reports the batch stopping. */}
                {row.row !== null && <span className={styles.rowNumber}>Row {row.row}</span>}
                {/* Empty on a line that reports a part which declared no file
                    name at all; its message says so, and an empty element here
                    would be a gap with nothing in it. */}
                {row.file !== '' && <span className={styles.fileName}>{row.file}</span>}
                {row.code !== null && <span className={styles.codeValue}>{row.code}</span>}
                {row.error !== null && <span className={styles.detail}>{row.error.message}</span>}
                {row.flags.map((flag) => (
                  <span className={styles.detail} key={flag}>
                    {flagSentence(flag)}
                  </span>
                ))}
              </li>
            ))}
          </ol>
          {summary !== null && (
            // The closing line, and a summary *of* the list rather than
            // instead of it (EXPERIENCE.md:73). It states three counts and
            // nothing derived from them — no rate, no percentage, no verdict.
            <p className={styles.summary}>
              {summary.created} added, {summary.flagged} flagged, {summary.failed} failed.
            </p>
          )}
        </section>
      )}
    </section>
  );
}
