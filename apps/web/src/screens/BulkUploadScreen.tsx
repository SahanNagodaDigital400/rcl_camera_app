import {
  ArrowDown,
  ArrowsClockwise,
  CheckCircle,
  CircleDashed,
  UploadSimple,
  Warning,
  XCircle,
} from '@phosphor-icons/react';
import { useEffect, useId, useRef, useState } from 'react';
import type { ChangeEvent, FormEvent, JSX, UIEvent } from 'react';

import {
  ADMINISTRATOR_REQUIRED,
  ApiRequestError,
  INVALID_MANIFEST,
  MALFORMED_RESPONSE,
  MATCHING_UNAVAILABLE,
  PIPELINE_STAMP_MISMATCH,
  TOO_MANY_ROWS,
  UNAUTHORIZED,
  UPLOAD_TIMEOUT_MS,
  apiRequest,
} from '../api/client';
import { shrinkImage } from '../upload/shrinkImage';
import styles from './BulkUploadScreen.module.css';

/**
 * Bulk upload — a whole range, sent one image at a time and reported row by row (FR-17).
 *
 * Rendered *inside* the shell, in place of the home panel, so it carries no
 * `<main>` of its own: `AppShell` already provides the one main landmark and
 * the focus target the gate moves focus to on a screen swap. It is modelled on
 * `AddTileScreen` — same form rhythm, same one-alert-in-one-slot treatment,
 * same accent submit beside a navy-outlined Back — because an Administrator
 * moving between the two catalogue upload surfaces should not read them as two
 * different applications.
 *
 * **One request per image, and this screen is what drives them.** A hundred
 * reference images in one multipart body is gigabytes on one connection: a
 * proxy's idle bound, a dropped Wi-Fi hop or a reloaded tab loses the whole
 * range, and there is no way to send back only the part that did not land. So
 * a batch is two phases against `apps/api`, and the loop between them lives
 * here:
 *
 * 1. `POST /admin/tiles/bulk/plan` takes the sheet and the *names* this device
 *    is holding — names only, no bytes — and answers one item per line the
 *    report will carry, in the order it will carry them.
 * 2. `POST /admin/tiles/bulk/row` takes one item and its one image, and
 *    answers that row's outcome. Once per item the plan paired, in order.
 *
 * **The manifest is still read on the server and nowhere else.** That is what
 * the plan buys: this screen sends file names and takes the pairing back, so
 * no CSV is parsed in a browser and the rule that `45X90\POLISH\a.JPG` names
 * `a.jpg` has exactly one implementation. A screen that paired for itself
 * would be a second reader of the sheet, and the two would disagree on the
 * first real export.
 *
 * **The report is the deliverable, not the spinner.** EXPERIENCE.md:73 asks
 * for a scrollable per-row list and explicitly not a single pass/fail summary,
 * and EXPERIENCE.md:94 asks for the rows to arrive *as they complete*. The
 * plan is what lets this screen do better than either: the whole list is on
 * screen — every row, its file and its Code — before a single image is sent,
 * and each line resolves in place as its own request answers. There is no
 * indeterminate phase and no invented denominator.
 *
 * **Three outcomes, three colours, and a word beside each** (DESIGN.md:144-149
 * and :221 — the one screen in the product where all three brand colours
 * appear as status indicators together). Navy for created, orange for flagged,
 * red for failed. A row that has not been sent yet, or is in flight, is
 * **neither an outcome nor a colour**: it is painted in the muted text colour
 * with its own word, because giving "waiting" a brand colour would make four
 * things look like statuses when the product has three. The word is not
 * decoration either: EXPERIENCE.md's accessibility floor says a state is never
 * signalled by colour alone, and a colour-blind Administrator reading a
 * hundred rows needs the word.
 *
 * **The rows that did not land can be sent again, and nothing else can.** That
 * is the whole point of splitting the transfer: a dropped connection, a file
 * that needed re-exporting, a Code that was in the way until the clashing tile
 * was removed — each of those is one request, and re-sending it costs one image
 * rather than the range. The rows that landed are never re-sent, because they
 * are in the catalogue and would answer `code_already_exists`; rows the *plan*
 * refused are not offered either, because nothing paired them, so the same
 * sheet and the same files would produce the same answer and the fix is a
 * different sheet or a different selection.
 *
 * Nothing here parses a manifest, decides a Category, derives a trailing
 * number from a Code or judges an image. Every one of those is a rule, the
 * rules live on the server, and a screen that restated one would be a second
 * place for it to drift — which is what AD-1 is about, one level up from the
 * pixels.
 */

/**
 * What a blank picker is told, before anything is sent.
 *
 * The form is `noValidate` — the browser's own bubble is unstyled, untestable
 * and disappears on the next keystroke — so these are what `required` would
 * otherwise have done.
 */
const NO_MANIFEST = 'Choose the sheet of codes.';
const NO_FILES = 'Choose the reference images.';

/**
 * The server's own bounds, mirrored onto this screen.
 *
 * **The server's copy is the authority** — `shared_schema.tile` bounds both and
 * the plan answers with a named refusal past them, whatever this file says.
 * These exist to keep a batch that was never going to be accepted out of the
 * loop below.
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
 * the file names sent with them — and the server enforces it on both. This
 * screen never reads the manifest, so images is the count it has; refusing on
 * that one is therefore stating the server's own rule rather than a second
 * one, and the plan refuses the same batch with `too_many_rows` whatever this
 * says. Worded about the images, because that is what the Administrator is
 * holding when this fires.
 */
const TOO_MANY_FILES =
  `Upload at most ${MAX_BULK_ROWS} reference images at a time. ` +
  'Split a larger range into two batches.';
const MEGABYTE = 1024 * 1024;

/** A byte count as an Administrator reads it, to one decimal place. */
function megabytes(bytes: number): string {
  return (bytes / MEGABYTE).toFixed(1);
}

/**
 * The refusal for an image over the ceiling that this device could not shrink.
 *
 * **Reached only after `shrinkImage` has tried.** A file over the ceiling is
 * no longer refused on sight: it is redrawn whole at `SHRINK_MAX_EDGE` and
 * sent, because a 96 MB press file is oversampled by an order of magnitude
 * against the 2048 px the server decodes to, and making an Administrator
 * re-export a hundred of those by hand is work this screen can do for them.
 *
 * This is what is left when that fails, and the sentence has to say *which*
 * failure it is, because the two have different fixes. A CMYK or
 * profile-carrying image is refused deliberately and not for want of trying:
 * a canvas re-encode would drop the profile and corrupt both the colour and
 * the embedding, invisibly (CLAUDE.md, AD-15), so the fix is a re-export in a
 * tool that knows the rendering intent. Anything else the browser could not
 * decode — a `.tif`, which the real source tree carries — has the same fix for
 * a different reason.
 *
 * Names the files, because a batch of a hundred with two bad ones is otherwise
 * a hunt.
 */
function cannotShrink(names: string[]): string {
  return (
    `Over ${MAX_IMAGE_BYTES / MEGABYTE} MB and could not be made smaller here: ${names.join(', ')}. ` +
    'Re-export each one as an sRGB JPEG under that size — a CMYK or colour-profiled ' +
    'image cannot be shrunk in the browser without changing its colour.'
  );
}

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
const SHRINKING = 'Making oversized images smaller…';
const PLANNING = 'Reading the sheet…';
const FINISHED = 'Finished.';

/**
 * How close to the foot of the log still counts as being at the foot.
 *
 * A console that only followed at exactly zero would stop following on a
 * half-pixel rounding or a rubber-band overscroll, and an Administrator who
 * never touched the wheel would watch it silently stop keeping up. A few
 * pixels of slack is what makes "am I at the bottom" answerable at all.
 *
 * Unitless because it is compared against `scrollTop`, which is a number: this
 * is arithmetic on a measurement, not a styling value the token layer could
 * express.
 */
const AT_FOOT_SLACK = 24;

/**
 * The batch stopped on something that was not about one row.
 *
 * A model artifact that went away, an index a generation ahead, a session that
 * ended. Each of those refuses every row that is left in exactly the same way,
 * so the loop stops on the first one rather than spending a hundred requests
 * collecting the same sentence — and the rows already reported are real and
 * stay. The message the server sent is rendered beside the pickers; this is
 * what the progress line says instead of "Finished.", which above a list with
 * unsent rows in it would be the screen contradicting its own report.
 */
const CUT_SHORT = 'The upload stopped. The rows below were finished; send the rest again.';

/**
 * The refusals that end a batch rather than failing one row.
 *
 * `apps/api` answers `200` with a report line for anything that is about the
 * tile in front of it, and a real status only for the things that would refuse
 * every remaining row identically — so in principle this list is the server's
 * to decide and the screen could stop on any non-`200`. It is written out
 * anyway, because the opposite case is the one that matters: a request that
 * *failed to reach* the server is a dropped connection, and a dropped
 * connection is the single most likely thing to happen during a batch that
 * runs for minutes. That has to be one failed, retryable row and not the end
 * of the range, which is exactly what sending one image per request is for.
 */
const STOPS_THE_BATCH = new Set<string>([
  MATCHING_UNAVAILABLE,
  PIPELINE_STAMP_MISMATCH,
  ADMINISTRATOR_REQUIRED,
  UNAUTHORIZED,
]);

/** What a failure with no message of its own is called. */
const UNEXPECTED = 'Something went wrong. Try again.';

/**
 * The clock beside each line of the log.
 *
 * **The time the line *resolved*, not a duration and not an estimate.** A
 * batch runs for minutes and the rows do not finish evenly — a 96 MB press
 * file takes tens of seconds to embed and a small one takes two — so the gap
 * between two stamps is the one piece of evidence an Administrator has for
 * where a slow batch is actually spending its time. Nothing derives anything
 * from it: there is no rate here and no projection of when the batch will end,
 * which would be an invented number (AD-20).
 *
 * Built once at module scope rather than per row: a hundred rows resolving
 * over minutes would otherwise construct a hundred formatters. `h23` so a log
 * read at a glance never has to be scanned for am/pm.
 */
const CLOCK = new Intl.DateTimeFormat(undefined, {
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hourCycle: 'h23',
});

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
 * The three outcomes the server reports, and the two states a row is in before
 * it has one.
 *
 * `created`, `flagged` and `failed` are exactly the server's own words and are
 * the only three DESIGN.md paints; a `status` this screen does not recognise
 * is a server speaking a protocol this build does not know, which `asResult`
 * refuses loudly rather than painting in a fourth, undefined treatment.
 *
 * `waiting` and `sending` are this screen's, because the row exists here
 * before it exists anywhere else — that is what the plan is for — and neither
 * is an outcome. Neither carries a brand colour.
 */
type Outcome = 'created' | 'flagged' | 'failed';
type RowState = Outcome | 'waiting' | 'sending';

/** The `{code, message}` of a refusal, in the envelope's own shape. */
interface Refusal {
  code: string;
  message: string;
}

/**
 * One line of the report: a plan item, plus whatever became of it.
 *
 * The two halves are deliberately one object. The plan states the row number,
 * the file and the Code before anything is sent, and the outcome fills in
 * later — a screen holding them apart would have to join them to render a line
 * and would have somewhere for the join to go wrong.
 */
interface ReportRow {
  /**
   * The item's position in the plan, assigned on arrival. React's list key,
   * and it is carried on the row rather than taken from the render index
   * because none of the fields the server sends can serve: two items may
   * legitimately name one file — that is the "two Codes, one image" case — and
   * a trailing item for an unmatched upload has no manifest row number at all.
   */
  seq: number;
  /**
   * The line's number in the *manifest*, or `null`.
   *
   * Rendered on the row, because it is what an Administrator uses to find the
   * offending line in the sheet in front of them — a file name alone means
   * scrolling a hundred-row spreadsheet looking for it. `null` on the items
   * that have no manifest row at all: a file no row named, and a name that was
   * blank.
   */
  row: number | null;
  /** The file name as the *sheet* spells it, which is the one field every item carries. */
  file: string;
  /** The Code, or `null` on an item that has none. */
  code: string | null;
  size: string | null;
  category: string | null;
  /**
   * The name of the file this device is to send for this row, or `null` when
   * the plan already decided it.
   *
   * **The server's answer, not this screen's guess.** The sheet may spell a
   * file `45X90/POLISH/a.JPG` where the picker gave `a.jpg`; the plan pairs
   * them and hands back the name to send, which is what keeps the pairing
   * rules in one place. Exactly one of this and `error` is set on arrival.
   */
  upload: string | null;
  state: RowState;
  /** Follow-up markers on a row that *was* created (AD-18). */
  flags: string[];
  /** Why this row is refused, or `null`. */
  error: Refusal | null;
  /** When this line resolved, already formatted — or `null` while it has not. */
  at: string | null;
}

/** The word beside each indicator. Never the colour alone — see the docstring. */
const WORD: Record<RowState, string> = {
  waiting: 'Waiting',
  sending: 'Uploading',
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
 * `styles[row.state]` would be shorter and would read the same classes, and it
 * is deliberately not used: `styling-wiring.test.ts` finds a stylesheet's
 * consumers by matching `styles.<name>` in the source, so a class reached only
 * through a computed key is a class that test reports as declared and
 * unreferenced. Naming them is what keeps the stylesheet and this file held
 * together.
 *
 * `waiting` and `sending` share `.pending`: neither is an outcome, so neither
 * gets a brand colour, and one muted treatment for "no answer yet" is what
 * keeps the three colours meaning exactly three things.
 */
function outcomeClass(state: RowState): string | undefined {
  if (state === 'created') return styles.created;
  if (state === 'flagged') return styles.flagged;
  if (state === 'failed') return styles.failed;
  return styles.pending;
}

/**
 * The indicator glyph. Phosphor at `regular` (outline) weight, which is the
 * library default — no `weight` prop is passed here or anywhere, and
 * `no-raw-values.test.ts` fails the build if one ever is (UX-DR3).
 *
 * `aria-hidden`, because the word beside it carries the state. Announced as
 * well, it would read every row's state twice.
 */
function outcomeIcon(state: RowState): JSX.Element {
  if (state === 'created') return <CheckCircle className={styles.icon} aria-hidden="true" />;
  if (state === 'flagged') return <Warning className={styles.icon} aria-hidden="true" />;
  if (state === 'failed') return <XCircle className={styles.icon} aria-hidden="true" />;
  if (state === 'sending') return <UploadSimple className={styles.icon} aria-hidden="true" />;
  return <CircleDashed className={styles.icon} aria-hidden="true" />;
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

/** The rejection thrown when a response is not the contract. */
function malformed(): ApiRequestError {
  return new ApiRequestError(
    MALFORMED_RESPONSE,
    'The server returned an unexpected response.',
    200,
  );
}

/** One `{code, message}`, or `null`. Used for both a plan item and a row result. */
function asRefusal(value: unknown): Refusal | null {
  if (!isObject(value)) return null;
  if (typeof value['code'] !== 'string' || typeof value['message'] !== 'string') return null;
  return { code: value['code'], message: value['message'] };
}

function asText(value: unknown): string | null {
  return typeof value === 'string' ? value : null;
}

/**
 * Narrow one plan item into the report row it becomes, or fail loudly.
 *
 * **Deliberately not closed the way `isTile` is.** That contract rejects any
 * extra key, because an extra key there is how a storage reference (AD-9) or a
 * similarity score (AD-20) would arrive unnoticed. Here the cost of the same
 * strictness is different in kind: an added server field would make the screen
 * refuse *every* batch, including the hundred rows that were about to be
 * created, and a field this screen does not read is a field it cannot render.
 * So the fields that are painted are checked and the rest is ignored — with
 * the one thing that decides what happens next, the `upload`/`error` pair,
 * checked hardest.
 *
 * `file` and the exclusive-or between `upload` and `error` are the contract:
 * an item with both would leave this screen deciding whether to send a row the
 * server had already refused, and an item with neither would be a line of the
 * report nothing can finish.
 */
function asPlanRow(item: unknown, seq: number): ReportRow {
  if (!isObject(item)) throw malformed();

  const file = item['file'];
  if (typeof file !== 'string') throw malformed();

  const upload = asText(item['upload']);
  const error = asRefusal(item['error']);
  if ((upload === null) === (error === null)) throw malformed();

  const row = item['row'];
  return {
    seq,
    row: typeof row === 'number' ? row : null,
    file,
    code: asText(item['code']),
    size: asText(item['size']),
    category: asText(item['category']),
    upload,
    state: error === null ? 'waiting' : 'failed',
    flags: [],
    error,
    // The plan's own refusals are decided before anything is sent, so they
    // carry the moment the plan arrived — which is the moment they became
    // true.
    at: error === null ? null : CLOCK.format(new Date()),
  };
}

/** Narrow the plan, or fail loudly. */
function asPlan(body: unknown): ReportRow[] {
  if (!isObject(body) || !Array.isArray(body['items'])) throw malformed();
  return body['items'].map((item, index) => asPlanRow(item, index));
}

/** What one row request answered: the outcome, its flags and its refusal. */
interface RowResult {
  state: Outcome;
  flags: string[];
  error: Refusal | null;
}

/**
 * Narrow one row response, or fail loudly.
 *
 * `status` is checked hardest, for `asPlanRow`'s reason inverted: it is the
 * one field that decides a row's treatment, and a fourth value would be
 * painted in no treatment at all.
 */
function asResult(body: unknown): RowResult {
  if (!isObject(body)) throw malformed();
  const status = body['status'];
  if (status !== 'created' && status !== 'flagged' && status !== 'failed') throw malformed();
  const flags = body['flags'];
  return {
    state: status,
    flags: Array.isArray(flags)
      ? flags.filter((flag): flag is string => typeof flag === 'string')
      : [],
    error: asRefusal(body['error']),
  };
}

/**
 * Whether this row could still be landed by another attempt.
 *
 * One predicate, read by the control's count and by the control's handler, so
 * the button can never offer a number it then does not send. A row the plan
 * refused has no `upload` and is excluded: nothing paired it, so the same
 * sheet and the same files would answer the same way.
 */
function unfinished(row: ReportRow): boolean {
  return row.upload !== null && row.state !== 'created' && row.state !== 'flagged';
}

/** How many rows of each state are in the report so far. */
function tally(rows: ReportRow[]): Record<RowState, number> {
  const counts: Record<RowState, number> = {
    waiting: 0,
    sending: 0,
    created: 0,
    flagged: 0,
    failed: 0,
  };
  for (const row of rows) counts[row.state] += 1;
  return counts;
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
  /** What this device did to the oversized images before sending them. */
  const [notes, setNotes] = useState<string[]>([]);
  /** The redraw pass runs before the plan is asked for. See `prepare`. */
  const [shrinking, setShrinking] = useState(false);
  /** The loop stopped on something that was not about one row. See `CUT_SHORT`. */
  const [cutShort, setCutShort] = useState(false);
  /** A pass has run to the end, so the report is a finished report. */
  const [settled, setSettled] = useState(false);
  const [error, setError] = useState<FormError | null>(null);
  const [running, setRunning] = useState(false);
  /**
   * Whether the log is still following its own tail.
   *
   * True until the reader scrolls up, and true again the moment they scroll
   * back down — a console that stopped following for good the first time
   * somebody looked at row 12 would need a reload to start again. Only ever
   * false on a viewport where the console scrolls at all, which is at and
   * above the breakpoint; below it the page owns the scroll and there is
   * nothing here to follow.
   */
  const [follow, setFollow] = useState(true);

  const manifestRef = useRef<HTMLInputElement>(null);
  const imagesRef = useRef<HTMLInputElement>(null);
  const consoleRef = useRef<HTMLDivElement>(null);

  /**
   * Whether this screen is still mounted, and the handle that stops the batch.
   *
   * A batch runs for minutes, and in that time the screen can go: a session
   * expiring drops the shell to the login screen, a sign-out unmounts
   * everything. Without these, the loop would go on calling `setRows` on a
   * component that no longer exists, and — worse — the server would go on
   * embedding a row into a request nobody is reading. The guard stops the
   * first and the abort stops the second.
   *
   * A ref, not state: it is read inside a loop that closes over its own
   * render, and a state value there would be the value at the time the batch
   * started rather than the value now.
   */
  const alive = useRef(true);
  const runningBatch = useRef<AbortController | null>(null);

  /**
   * Whether a submit is in flight, readable from inside one.
   *
   * The mirror of `running` that the loop can trust. `running` closes over the
   * render that started the batch, where it is `false` however long the batch
   * has been going since — and there are phases *before* any request exists
   * (the redraw pass), so the abort handle is no longer a stand-in for "busy"
   * either.
   */
  const busy = useRef(false);

  /**
   * The files as they will actually be *sent*, which is not always the files
   * that were chosen.
   *
   * `prepare` redraws anything over the byte ceiling and the redrawn copy is
   * what goes up; a retry that reached back to `files` would re-send the 96 MB
   * original and be told `image_too_large` for a row that had been shrunk
   * successfully minutes earlier. A ref rather than state because it is read
   * inside a loop that closes over its own render, and because nothing renders
   * from it.
   */
  const sendable = useRef<File[]>([]);

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
   * Both pickers are `disabled` while a batch runs, and `focus()` on a
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
    // Straight away when nothing is in flight — the screen's own pre-flight
    // refusals are decided before anything starts — and deferred while a
    // submit is still unwinding, because both pickers are `disabled` then and
    // `focus()` on a disabled control does nothing at all. Read off the ref
    // and not off `running`, which in a submit's own closure is the value it
    // had when the button was pressed.
    if (busy.current) focusWhenIdle.current = field;
    else focus(field);
  }

  /**
   * Keep the newest resolved line in view while the log is following.
   *
   * `scrollTop` rather than `scrollTo`: the assignment is a no-op on an
   * element that does not scroll — which is every viewport below the
   * breakpoint, where the console has no height cap and the page owns the
   * axis — so nothing here has to know which layout is in force.
   *
   * Depends on how many rows have *resolved* rather than on the array: the
   * whole list is on screen from the moment the plan arrives, so a row count
   * would not change once and the log would never follow anything.
   */
  const resolved = rows.filter((row) => row.at !== null).length;
  useEffect(() => {
    const log = consoleRef.current;
    if (!follow || resolved === 0 || log === null) return;
    log.scrollTop = log.scrollHeight;
  }, [resolved, follow]);

  /** Stop following when the reader scrolls up; resume when they come back. */
  function watchScroll(event: UIEvent<HTMLDivElement>): void {
    const log = event.currentTarget;
    setFollow(log.scrollHeight - log.scrollTop - log.clientHeight <= AT_FOOT_SLACK);
  }

  function jumpToLatest(): void {
    const log = consoleRef.current;
    if (log !== null) log.scrollTop = log.scrollHeight;
    setFollow(true);
  }

  /**
   * Take a new choice, and retire the report beside it.
   *
   * The report describes a batch that has already run; the moment a different
   * sheet or a different set of images is chosen it is describing something
   * that is no longer on screen.
   */
  function retireReport(): void {
    setError(null);
    setRows([]);
    setNotes([]);
    setCutShort(false);
    setSettled(false);
    setFollow(true);
  }

  function chooseManifest(event: ChangeEvent<HTMLInputElement>): void {
    retireReport();
    setManifest(event.target.files?.[0] ?? null);
  }

  function chooseFiles(event: ChangeEvent<HTMLInputElement>): void {
    retireReport();
    setFiles([...(event.target.files ?? [])]);
  }

  /**
   * Make the oversized images small enough to send, or refuse the ones that
   * cannot be.
   *
   * Answers the list to upload, or `null` when it has already refused.
   *
   * **A file within the ceiling is never touched.** It travels as chosen,
   * byte for byte: re-encoding it would cost a generation of JPEG artefacts to
   * solve a problem it does not have. Only the oversized ones are redrawn, and
   * they are redrawn *whole* — `shrinkImage` crops nothing, because a
   * reference image is the tile and a tile with its edge cut off is a
   * different reference image.
   *
   * **The redrawn file keeps its name**, which is not incidental: the name is
   * what the plan pairs on, so a shrink that renamed anything would unpair the
   * row it was trying to help.
   *
   * **One refusal for all of them, at the end.** A batch with two bad files in
   * a hundred should be told about both at once, rather than refusing on the
   * first and making the Administrator discover the second on the next
   * attempt.
   */
  async function prepare(chosen: File[]): Promise<File[] | null> {
    const oversized = chosen.filter((file) => file.size > MAX_IMAGE_BYTES);
    if (oversized.length === 0) return chosen;

    setShrinking(true);
    const smaller = new Map<File, File>();
    const beyondUs: string[] = [];
    const done: string[] = [];

    for (const file of oversized) {
      // **Sequential on purpose, and `Promise.all` would be wrong here.** Each
      // call holds a decoded frame of up to 186 megapixels; a hundred of those
      // in flight at once is a tab that dies rather than a batch that finishes
      // sooner, and the decoding is the browser's single image thread either
      // way.
      // oxlint-disable-next-line no-await-in-loop
      const shrunk = await shrinkImage(file);
      // The screen went while a 96 MB file was decoding. Nothing left to send
      // it to, and nothing left to paint.
      if (!alive.current) return null;
      if (shrunk === null) {
        beyondUs.push(file.name);
        continue;
      }
      smaller.set(file, shrunk);
      done.push(`${file.name} — ${megabytes(file.size)} MB sent as ${megabytes(shrunk.size)} MB.`);
    }

    setShrinking(false);
    if (beyondUs.length > 0) {
      refuse(cannotShrink(beyondUs), 'images');
      return null;
    }

    // Said out loud rather than done quietly: the bytes indexed are not the
    // bytes chosen, and an Administrator comparing a stored reference image
    // against the file on their disk deserves to know why they differ.
    setNotes(done);
    return chosen.map((file) => smaller.get(file) ?? file);
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    if (busy.current) return;

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

    busy.current = true;
    setRunning(true);
    retireReport();

    const batch = new AbortController();
    runningBatch.current = batch;
    try {
      const sending = await prepare(files);
      if (sending === null) return;
      sendable.current = sending;

      const planned = await plan(manifest, sending, batch.signal);
      if (planned === null) return;

      await drive(planned, sending, batch.signal);
    } finally {
      busy.current = false;
      if (runningBatch.current === batch) runningBatch.current = null;
      if (alive.current) {
        setRunning(false);
        setShrinking(false);
      }
    }
  }

  /**
   * Ask for the plan and paint it as the whole report, before anything is sent.
   *
   * Answers the rows, or `null` when the batch was refused — which is every
   * batch-wide condition there is: a sheet the server cannot read, a range
   * over the cap, a missing model artifact, a stale stamp, a role. All of them
   * cost the Administrator the sheet and no image bytes at all, which is what
   * this phase is for.
   */
  async function plan(
    sheet: File,
    sending: File[],
    signal: AbortSignal,
  ): Promise<ReportRow[] | null> {
    // Multipart, because the request carries a file. `names` repeats once per
    // image, which is how a multipart body expresses a list — and it carries
    // the *names* alone: the bytes stay here until the plan says which row
    // wants them.
    const body = new FormData();
    body.append('manifest', sheet);
    for (const file of sending) body.append('names', file.name);

    try {
      const planned = asPlan(
        await apiRequest('/admin/tiles/bulk/plan', {
          method: 'POST',
          body,
          signal,
        }),
      );
      if (!alive.current) return null;
      setRows(planned);
      return planned;
    } catch (failure) {
      // The API's own message, so the screen cannot state a rule the server
      // does not enforce.
      if (alive.current) {
        refuse(
          failure instanceof ApiRequestError ? failure.message : UNEXPECTED,
          fieldFor(failure),
        );
      }
      return null;
    }
  }

  /**
   * Send every row the plan paired, one request at a time, and paint each
   * answer as it lands.
   *
   * **Sequentially, and `Promise.all` would be wrong.** Each row is sixteen
   * forward passes on the server's CPU (AD-13, AD-16): four in flight at once
   * oversubscribe the same cores, so the batch finishes no sooner and every
   * individual row takes longer to report — which is the one thing this screen
   * exists to show. It would also multiply the peak transfer by four, undoing
   * the reason the batch is split at all.
   *
   * **A failure is one row's, until the server says otherwise.** A dropped
   * connection or a timeout is the single most likely thing to happen during a
   * run of minutes, and it must cost the row in flight rather than the range —
   * so it is painted as a failed, retryable line and the loop goes on. Only
   * `STOPS_THE_BATCH` ends it, because those refuse every remaining row
   * identically.
   */
  async function drive(planned: ReportRow[], sending: File[], signal: AbortSignal): Promise<void> {
    const bytesFor = new Map(sending.map((file) => [file.name, file]));

    for (const row of planned) {
      if (!alive.current || signal.aborted) return;
      if (row.upload === null) continue;
      const file = bytesFor.get(row.upload);
      // The plan named a file this device is not holding. Unreachable through
      // the form — the names came from these very files — and reported rather
      // than skipped, because a row silently absent from the report is a tile
      // the Administrator believes is in the catalogue.
      if (file === undefined) {
        mark(row.seq, { state: 'failed', flags: [], error: null });
        continue;
      }

      setRows((already) =>
        already.map((line) => (line.seq === row.seq ? { ...line, state: 'sending' } : line)),
      );

      // oxlint-disable-next-line no-await-in-loop
      const stopped = await send(row, file, signal);
      if (stopped) {
        if (alive.current) setCutShort(true);
        return;
      }
    }

    if (alive.current) setSettled(true);
  }

  /**
   * Send one row. Answers whether the whole batch has to stop.
   *
   * Lifted out of the loop so the `await` has one statement to own and the
   * two failure shapes — this row's, and the batch's — are decided in one
   * place rather than inside a loop body.
   */
  async function send(row: ReportRow, file: File, signal: AbortSignal): Promise<boolean> {
    const body = new FormData();
    body.append('code', row.code ?? '');
    body.append('size', row.size ?? '');
    body.append('category', row.category ?? '');
    if (row.row !== null) body.append('row', String(row.row));
    body.append('image', file);

    try {
      const result = asResult(
        await apiRequest('/admin/tiles/bulk/row', {
          method: 'POST',
          body,
          signal,
          // One row is one image decoded, colour-managed and embedded sixteen
          // times: the default 15 seconds is wrong for it by an order of
          // magnitude, and an abort fired while the server is still working
          // would report a tile that is about to exist as one that failed.
          timeoutMs: UPLOAD_TIMEOUT_MS,
        }),
      );
      mark(row.seq, result);
      return false;
    } catch (failure) {
      const refusal = failure instanceof ApiRequestError ? failure : null;
      if (refusal !== null && STOPS_THE_BATCH.has(refusal.code)) {
        // **The row in flight is marked too, and not only the form.** It was
        // not added, so a line left reading "Uploading" for the rest of the
        // session would be the report's one outright false statement — and it
        // is a row the Administrator will want re-sent once the deployment is
        // fixed, which the control below can only offer for a row that is not
        // still pretending to be in flight. The alert beside the pickers is
        // the same sentence, said about the batch.
        mark(row.seq, {
          state: 'failed',
          flags: [],
          error: { code: refusal.code, message: refusal.message },
        });
        if (alive.current) refuse(refusal.message, fieldFor(refusal));
        return true;
      }
      // This row's own failure, and the thing the whole split exists for: a
      // dropped connection costs one image, the line says so, and the control
      // below offers to send it again. The API's own code and sentence, so the
      // line cannot state a rule the server does not enforce.
      mark(row.seq, {
        state: 'failed',
        flags: [],
        error: refusal === null ? null : { code: refusal.code, message: refusal.message },
      });
      return false;
    }
  }

  /**
   * Write one row's outcome into the report.
   *
   * **A failed row always ends up with a sentence.** The server sends one on
   * every refusal it makes, and a transport failure carries the API client's
   * own — but a `failed` with nothing behind it would be a line saying
   * something went wrong and not what, which on a hundred-row report is a row
   * an Administrator can only stare at. `UNEXPECTED` is the last resort here,
   * never the ordinary case.
   */
  function mark(seq: number, result: RowResult): void {
    if (!alive.current) return;
    // Named `refusal` rather than `error`: the form's own `error` state is in
    // scope here, and two things called the same word one line apart is how a
    // row's sentence ends up beside the pickers.
    const refusal =
      result.error ??
      (result.state === 'failed' ? { code: MALFORMED_RESPONSE, message: UNEXPECTED } : null);
    setRows((already) =>
      already.map((line) =>
        line.seq === seq
          ? {
              ...line,
              state: result.state,
              flags: result.flags,
              error: refusal,
              at: CLOCK.format(new Date()),
            }
          : line,
      ),
    );
  }

  /**
   * Send the rows that have not landed. Nothing else.
   *
   * **This is what one request per image buys.** A file that needed
   * re-exporting, a Code that was in the way until the clashing tile was
   * removed, a connection that dropped on row 40 of 100 — each is one request,
   * and this re-sends exactly those rather than the range. The rows that
   * already landed are untouched: they are in the catalogue, and sending them
   * again would answer `code_already_exists` for every one of them.
   *
   * **`waiting` as well as `failed`**, because a batch that stopped leaves
   * both: the row that met the refusal is failed and the rows after it were
   * never sent. "The remaining rows" is one thing to an Administrator looking
   * at that report, and a control that offered only the failed one would leave
   * the rest of the range needing a whole second upload.
   *
   * Only rows the plan *paired* are offered: a row nothing could be found for
   * would be refused by the same plan on the same files, so the fix is a
   * different sheet or a different selection rather than a second attempt.
   */
  async function retry(): Promise<void> {
    if (busy.current) return;
    const again = rows.filter(unfinished);
    if (again.length === 0) return;

    busy.current = true;
    setRunning(true);
    setError(null);
    setCutShort(false);
    setSettled(false);
    // Back to `waiting` before anything is sent, so the failure that is about
    // to be re-attempted is not still on screen as a settled answer.
    setRows((already) =>
      already.map((line) =>
        again.some((row) => row.seq === line.seq)
          ? { ...line, state: 'waiting', flags: [], error: null, at: null }
          : line,
      ),
    );

    const batch = new AbortController();
    runningBatch.current = batch;
    try {
      // The prepared files, not the chosen ones. See `sendable`.
      await drive(again, sendable.current, batch.signal);
    } finally {
      busy.current = false;
      if (runningBatch.current === batch) runningBatch.current = null;
      if (alive.current) setRunning(false);
    }
  }

  const counts = tally(rows);
  /**
   * The denominator, and it is exact from the moment the plan lands.
   *
   * The plan states one item per line the report will carry — one per manifest
   * row, one per file no row names, one per name that was blank — so this is
   * the server's own count rather than a guess from the number of files
   * chosen, which is a different number for exactly the batch a report is most
   * needed for.
   */
  const scale = rows.length;
  const answered = counts.created + counts.flagged + counts.failed;
  /** The rows a second attempt could still land. See `retry` and `unfinished`. */
  const remaining = rows.filter(unfinished).length;

  // One expression rather than a nested ternary in the markup. The live region
  // is in the document at rest so the change of text is what gets announced,
  // rather than the arrival of a whole new node — and it is a *sentence* with
  // its subject in it rather than a bare number, because "40" announced on its
  // own tells a screen-reader user nothing about what forty is.
  let progress = '';
  if (shrinking) progress = SHRINKING;
  // **`scale === 0` and not `planning`**, because there is a gap between the
  // submit and the plan request going out — the redraw pass is async whether
  // or not it has anything to redraw — and "0 of 0 rows reported." is what a
  // reader would have been told during it. No plan is no plan, however the
  // screen got there.
  else if (running && scale === 0) progress = PLANNING;
  else if (running) progress = `${answered} of ${scale} rows reported.`;
  else if (cutShort) progress = CUT_SHORT;
  else if (settled) progress = FINISHED;

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
            One CSV, with a header row and a column for the file name, the code and the size. Up to{' '}
            {MAX_BULK_ROWS} rows — the sheet is read on the server before any image is sent, so a
            sheet it cannot use costs nothing but the sheet. Category is optional — a row without
            one is filed under UNKNOWN and flagged. Export a spreadsheet as CSV and upload that.
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
            image is sent on its own and indexed before the next one goes, so a row that fails can
            be sent again without the rest.
          </p>
          {error?.fieldAtFault === 'images' && alert}
        </div>

        {/* A failure that belongs to neither picker — the request never reached
            the API, the server has no image pipeline installed, or the batch
            was stopped by something that is not about one row. Inserted rather
            than emptied and refilled: a `role="alert"` node appearing in the
            document is what announces it. */}
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
              created, because each one is its own request and its own
              transaction. */}
          <button className={styles.back} type="button" onClick={onBack} disabled={running}>
            Back
          </button>
          <span className={styles.indicator} role="status" aria-atomic="true">
            {progress}
          </span>
        </div>
      </form>

      {(running || rows.length > 0) && (
        // A labelled region, deliberately **not** a second live region. The
        // progress line above already announces that rows are resolving;
        // marking the list `role="status"` as well would read every row out in
        // full as it changed, which on a hundred-row batch is the report
        // narrated twice over. A screen reader reaches it by its heading,
        // which is what a region is for.
        //
        // Opened as soon as the batch starts rather than when the first row
        // lands, because the bar is the thing that has something to say during
        // the seconds before the plan arrives.
        <section className={styles.report} aria-labelledby={reportId}>
          <h2 className={styles.subtitle} id={reportId}>
            Report
          </h2>

          {/* The bar. **Determinate the moment the plan lands**, which is
              before a single image has been sent —`aria-valuenow` and
              `aria-valuemax` are omitted only while there is no plan at all,
              which is precisely what ARIA defines an indeterminate progressbar
              to be and is the honest shape for "the sheet is still being
              read".

              The fill is three segments in the three outcome colours rather
              than one bar in one colour: the same report, at a glance, in the
              same navy/orange/red this screen already uses row by row. The
              colours come from the row classes themselves — `.segment` paints
              with `currentColor` — so there is exactly one place that decides
              what "flagged" looks like here. The rows still waiting are the
              unpainted remainder of the track, which is what a progress bar's
              empty part already means. */}
          <div className={styles.progress}>
            <div
              className={styles.track}
              role="progressbar"
              aria-label="Rows reported"
              aria-valuetext={progress === '' ? PLANNING : progress}
              aria-valuemin={0}
              aria-valuemax={scale === 0 ? undefined : scale}
              aria-valuenow={scale === 0 ? undefined : answered}
            >
              {scale === 0 ? (
                <span className={styles.waiting} />
              ) : (
                <>
                  <span
                    className={`${styles.segment} ${styles.created}`}
                    style={{ width: `${(counts.created / scale) * 100}%` }}
                  />
                  <span
                    className={`${styles.segment} ${styles.flagged}`}
                    style={{ width: `${(counts.flagged / scale) * 100}%` }}
                  />
                  <span
                    className={`${styles.segment} ${styles.failed}`}
                    style={{ width: `${(counts.failed / scale) * 100}%` }}
                  />
                </>
              )}
            </div>
            {/* The counts, in the same three colours and never colour alone —
                each carries its word, for the reason every row does. Not a
                live region: the one `role="status"` beside the buttons is what
                speaks, and a second announcer would read the batch twice. */}
            <p className={styles.counts}>
              <span className={styles.created}>{counts.created} added</span>
              <span className={styles.flagged}>{counts.flagged} flagged</span>
              <span className={styles.failed}>{counts.failed} failed</span>
              {scale > 0 && (
                <span className={styles.ofTotal}>
                  {answered} of {scale} rows
                </span>
              )}
            </p>
          </div>

          {/* What this device did before the batch left. Paragraphs rather
              than a list: the report below is the one list on this screen, and
              a second one would be a second thing to navigate for what is a
              footnote about bytes. */}
          {notes.length > 0 && (
            <div className={styles.notes}>
              {notes.map((note) => (
                <p className={styles.note} key={note}>
                  {note}
                </p>
              ))}
            </div>
          )}
          {/* `role="list"` restated on a list that has no markers. Safari and
              VoiceOver drop list semantics from an `<ol>` whose `list-style`
              is `none` — the rows stop being announced as "list, 30 items" and
              "row 4 of 30" goes with them, which on a report this long is the
              one piece of orientation a screen-reader user has. Redundant in
              every other browser and harmless there. */}
          {rows.length > 0 && (
            <div className={styles.console} ref={consoleRef} onScroll={watchScroll}>
              <ol className={styles.rows} role="list">
                {rows.map((row) => (
                  <li key={row.seq} className={`${styles.row} ${outcomeClass(row.state)}`}>
                    {/* The line's own head: everything that identifies it, on
                        one wrapping line, so a hundred of them read as a log
                        and not as a hundred paragraphs. The sentences beneath
                        are what only some rows have. */}
                    <span className={styles.head}>
                      {/* When this line resolved. See `CLOCK`: the gap between
                          two stamps is the only evidence of where a slow batch
                          is spending its minutes. Empty while the row is still
                          waiting — a stamp there would be the time the plan
                          arrived, dressed up as the time this row finished. */}
                      <span className={styles.time}>{row.at ?? ''}</span>
                      <span className={styles.outcome}>
                        {outcomeIcon(row.state)}
                        <span className={styles.word}>{WORD[row.state]}</span>
                      </span>
                      {/* The manifest row, where there is one. This is what an
                          Administrator looks up in the sheet in front of them.
                          Absent on the lines that have no row — a file nothing
                          named, and a name that was blank. */}
                      {row.row !== null && <span className={styles.rowNumber}>Row {row.row}</span>}
                      {/* Empty on a line that reports a file which declared no
                          name at all; its message says so, and an empty
                          element here would be a gap with nothing in it. */}
                      {row.file !== '' && <span className={styles.fileName}>{row.file}</span>}
                      {row.code !== null && row.code !== '' && (
                        <span className={styles.codeValue}>{row.code}</span>
                      )}
                    </span>
                    {row.error !== null && (
                      <span className={styles.detail}>{row.error.message}</span>
                    )}
                    {row.flags.map((flag) => (
                      <span className={styles.detail} key={flag}>
                        {flagSentence(flag)}
                      </span>
                    ))}
                  </li>
                ))}
              </ol>
            </div>
          )}

          {/* The way back to the tail, and only when there is one to offer: the
              console has scrolled away from its foot while rows are still
              resolving. Absent at rest, which is what keeps this screen's
              control count what it says it is — and absent entirely below the
              breakpoint, where the console does not scroll and the page's own
              scroll is the reader's. */}
          {running && !follow && (
            <button className={styles.follow} type="button" onClick={jumpToLatest}>
              <ArrowDown className={styles.followIcon} aria-hidden="true" />
              Jump to latest
            </button>
          )}

          {/* The recovery path, and the reason the transfer is split at all
              (UX: an error without a next step is an error the reader can only
              re-read). Offered once the pass has stopped and only while there
              is a row a second attempt could still land — a row the plan could
              not pair is refused by the same plan on the same files, so it is
              not counted here and not re-sent.

              Navy-outlined like Back rather than accent: Upload is still this
              screen's one orange control, and the report below it is already
              spending orange on flagged rows. */}
          {!running && remaining > 0 && (
            <button className={styles.retry} type="button" onClick={() => void retry()}>
              <ArrowsClockwise className={styles.followIcon} aria-hidden="true" />
              Send the remaining {remaining} {remaining === 1 ? 'row' : 'rows'}
            </button>
          )}

          {(settled || cutShort) && (
            // The closing line, and a summary *of* the list rather than
            // instead of it (EXPERIENCE.md:73). It states three counts and
            // nothing derived from them — no rate, no percentage, no verdict.
            <p className={styles.summary}>
              {counts.created} added, {counts.flagged} flagged, {counts.failed} failed.
            </p>
          )}
        </section>
      )}
    </section>
  );
}
