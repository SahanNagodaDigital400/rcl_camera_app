import { useId, useRef, useState } from 'react';
import type { ChangeEvent, FormEvent, JSX } from 'react';

import {
  ApiRequestError,
  CODE_ALREADY_EXISTS,
  IMAGE_TOO_LARGE,
  INVALID_CATEGORY,
  INVALID_CODE,
  INVALID_IMAGE,
  INVALID_SIZE,
  MALFORMED_RESPONSE,
  TOO_MANY_IMAGES,
  UNREADABLE_IMAGE,
  UPLOAD_TIMEOUT_MS,
  apiRequest,
} from '../api/client';
import styles from './AddTileScreen.module.css';
import { isTile, UNKNOWN_CATEGORY } from '@rocell/schema/tile';
import type { Tile } from '@rocell/schema/tile';

/**
 * Add tile — where an Administrator puts a Tile into the Catalogue (FR-14).
 *
 * Rendered *inside* the shell, in place of the home panel, so it carries no
 * `<main>` of its own: `AppShell` already provides the one main landmark and
 * the focus target the gate moves focus to on a screen swap. It is modelled on
 * `CreateUserScreen` — same form rhythm, same one-alert-in-one-slot treatment,
 * same accent submit beside a navy-outlined Back — and on
 * `AccountSettingsScreen` for the `Saving…` → `Saved.` indicator, which is the
 * thing this screen has that Create user does not (EXPERIENCE.md Flow 2 step
 * 3: "Saves — sees a `Saved.` confirmation inline").
 *
 * **The Code is the tile's identity** (AD-18), and the vocabulary follows:
 * Tile, Code, Size, Category, Reference image. `Product` and `Face` are
 * retired words and appear nowhere on this screen or in its stylesheet.
 *
 * **It sends a `FormData`, which is why `apiRequest` had to learn one.** The
 * request carries files, and a multipart body's `content-type` holds the
 * boundary token that separates the parts — only the browser that assembled
 * the body knows it, so the header must be left for `fetch` to write.
 *
 * **It calls `apiRequest` directly rather than going through
 * `SessionProvider`**, for `CreateUserScreen`'s reason: that context is the
 * caller's *own* session, and adding a Tile changes nothing about it.
 *
 * **The role-conditional door that opens this screen is a convenience, never
 * the control.** `App` renders it only for an Administrator, but the cached
 * `User` is a render cache and never an authorization decision (AGENTS.md
 * Policy): the server refuses a Staff caller at `POST /admin/tiles` through
 * `require_administrator`, which re-reads the role from Postgres on every
 * request (AD-3).
 *
 * Deliberately absent:
 *
 * - **No similarity value, in any form** (AD-20). There is nothing to show one
 *   for on this screen, and there never will be: a bar, a percentage or a word
 *   derived from a score is banned product-wide.
 * - **No crop step.** AD-11 resolved it explicitly: the server-side crop
 *   exists and is exercised only by the Scan path. An admin upload is a studio
 *   asset that is already framed.
 * - **No client-side check of what the file is.** Content decides, and only
 *   the server can sniff content (AGENTS.md Policy). A screen that refused a
 *   `.tif` would refuse files the real catalogue is full of, and one that
 *   accepted by extension would be validating nothing.
 * - **No list here.** Editing (2.2), removal (2.3) and bulk upload (2.4) have
 *   screens of their own; the catalogue list is Story 2.5.
 */

/** Shown for a failure that arrives as something other than an `ApiRequestError`. */
const UNEXPECTED = 'The tile could not be added. Try again.';

/**
 * Refuse an empty field here rather than letting the API answer for it.
 *
 * The form is `noValidate` — the browser's own bubble is unstyled, untestable
 * and disappears on the next keystroke — so these are what `required` would
 * otherwise have done. Without them a blank submit uploads a file and spends
 * tens of seconds of server CPU to be told a field is empty.
 */
const BLANK_CODE = 'Enter the tile’s code.';
const BLANK_SIZE = 'Enter the tile’s size.';
const NO_FILES = 'Choose at least one reference image.';


/** The save indicator's two spoken states (DESIGN.md's `save-indicator`). */
const SAVING = 'Saving…';
const SAVED = 'Saved.';

/**
 * The server's own bounds, mirrored onto the inputs.
 *
 * **The server's copy is the authority** — `shared_schema.tile` bounds all
 * three and the endpoint answers with a named `422` past them, whatever this
 * file says. These exist only to keep the one refusal the Administrator cannot
 * act on off the screen, and, for the file count, to say the limit before
 * nine files have been uploaded rather than after.
 *
 * Written down here rather than imported because nothing crosses that boundary
 * at build time; `error-code-parity.test.ts` pins each against its Python
 * twin, so a drift is a failing test rather than a silent divergence.
 */
const MAX_CODE_LENGTH = 200;
const MAX_SIZE_LENGTH = 100;
const MAX_CATEGORY_LENGTH = 200;
const MAX_IMAGES_PER_REQUEST = 8;
const MAX_IMAGE_BYTES = 134217728;

/**
 * The two bounds worth refusing *before* the upload rather than after it.
 *
 * Unlike the blank-field refusals above, these are not about saving the server
 * a rule check — they are about not sending the bytes. Nine reference images
 * is comfortably hundreds of megabytes, and a file over the ceiling is refused
 * whole; in both cases the Administrator would otherwise watch a long upload
 * finish and *then* be told the count or the size was never going to be
 * accepted. The server still refuses both, with its own codes, whatever this
 * says (`too_many_images`, `image_too_large`).
 */
const TOO_MANY_FILES =
  `Choose at most ${MAX_IMAGES_PER_REQUEST} reference images at a time. ` +
  'Add the rest as separate tiles.';
const FILE_TOO_LARGE = `Each reference image must be under ${
  MAX_IMAGE_BYTES / (1024 * 1024)
} MB.`;

/** Which field a failure is about — and therefore which one is marked and focused. */
type Field = 'code' | 'size' | 'category' | 'images';

/**
 * What went wrong, and which field is at fault.
 *
 * `fieldAtFault` is not decoration: it drives `aria-invalid` and focus.
 * Marking an input invalid because the model artifact is missing on the server
 * tells a screen-reader user their typing was malformed when it was not.
 */
interface FormError {
  message: string;
  fieldAtFault: Field | null;
}

/** The API's code, mapped to the field the Administrator has to fix. */
function fieldFor(failure: unknown): Field | null {
  if (!(failure instanceof ApiRequestError)) return null;
  if (failure.code === INVALID_CODE || failure.code === CODE_ALREADY_EXISTS) return 'code';
  if (failure.code === INVALID_SIZE) return 'size';
  if (failure.code === INVALID_CATEGORY) return 'category';
  if (
    failure.code === INVALID_IMAGE ||
    failure.code === UNREADABLE_IMAGE ||
    failure.code === IMAGE_TOO_LARGE ||
    failure.code === TOO_MANY_IMAGES
  ) {
    return 'images';
  }
  // `matching_unavailable` and `administrator_required` land here,
  // deliberately: nothing the Administrator chose is at fault, and pointing at
  // a field would be a lie. The screen renders the server's sentence, which in
  // the first case names the setup step an operator has to run.
  return null;
}

/**
 * Narrow the response body to the shared `Tile`, or fail loudly.
 *
 * `isTile` rejects a missing key, a malformed UUID, a non-UTC timestamp — and
 * any extra key, which is how a storage reference (AD-9) or a similarity score
 * (AD-20) would announce itself rather than being quietly ignored.
 */
function asTile(body: unknown): Tile {
  if (!isTile(body)) {
    throw new ApiRequestError(
      MALFORMED_RESPONSE,
      'The server returned an unexpected response.',
      201,
    );
  }
  return body;
}

export function AddTileScreen({ onBack }: { onBack: () => void }): JSX.Element {
  const codeId = useId();
  const sizeId = useId();
  const categoryId = useId();
  const imagesId = useId();
  const errorId = useId();
  const imagesHintId = useId();
  const resultId = useId();

  const [code, setCode] = useState('');
  const [size, setSize] = useState('');
  const [category, setCategory] = useState('');
  const [files, setFiles] = useState<File[]>([]);
  const [error, setError] = useState<FormError | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [added, setAdded] = useState<Tile | null>(null);

  const codeRef = useRef<HTMLInputElement>(null);
  const sizeRef = useRef<HTMLInputElement>(null);
  const categoryRef = useRef<HTMLInputElement>(null);
  const imagesRef = useRef<HTMLInputElement>(null);

  /**
   * Take what was typed, and retire the result panel beside it.
   *
   * The panel describes a Tile that has already been added; the moment a field
   * is edited it is describing something that is no longer on screen.
   */
  function typed<T>(set: (value: T) => void): (value: T) => void {
    return (value) => {
      setAdded(null);
      set(value);
    };
  }

  function focus(field: Field): void {
    const target =
      field === 'code'
        ? codeRef
        : field === 'size'
          ? sizeRef
          : field === 'category'
            ? categoryRef
            : imagesRef;
    target.current?.focus();
  }

  function refuse(message: string, field: Field | null): void {
    setAdded(null);
    setError({ message, fieldAtFault: field });
    if (field !== null) focus(field);
  }

  function chooseFiles(event: ChangeEvent<HTMLInputElement>): void {
    setAdded(null);
    setError(null);
    setFiles([...(event.target.files ?? [])]);
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    if (submitting) return;

    // Trimmed for the *emptiness* test only. The values sent are untrimmed:
    // the API normalizes the Size and the Category itself and strips the Code,
    // and doing it twice in two places is how the two come to disagree.
    if (code.trim() === '') {
      refuse(BLANK_CODE, 'code');
      return;
    }
    if (size.trim() === '') {
      refuse(BLANK_SIZE, 'size');
      return;
    }
    if (files.length === 0) {
      refuse(NO_FILES, 'images');
      return;
    }
    if (files.length > MAX_IMAGES_PER_REQUEST) {
      refuse(TOO_MANY_FILES, 'images');
      return;
    }
    if (files.some((file) => file.size > MAX_IMAGE_BYTES)) {
      refuse(FILE_TOO_LARGE, 'images');
      return;
    }

    setSubmitting(true);
    setError(null);
    setAdded(null);

    // Multipart, because the request carries files. The part names are the
    // endpoint's parameter names; `images` repeats once per file, which is how
    // a multipart body expresses a list.
    const body = new FormData();
    body.append('code', code);
    body.append('size', size);
    body.append('category', category);
    for (const file of files) body.append('images', file);

    try {
      // `UPLOAD_TIMEOUT_MS`, not the default. This request makes the server
      // embed every image — 16 forward passes each (AD-13) — and the default
      // 15s would abort a request the server then commits anyway, leaving the
      // Administrator looking at a network error for a tile that exists.
      setAdded(
        asTile(
          await apiRequest('/admin/tiles', {
            method: 'POST',
            body,
            timeoutMs: UPLOAD_TIMEOUT_MS,
          }),
        ),
      );
      // The form clears and the indicator says so. No navigation: an
      // Administrator adding a range adds several in a row, and a surface that
      // moved out from under them would cost a trip back for every one.
      setCode('');
      setSize('');
      setCategory('');
      setFiles([]);
      if (imagesRef.current) imagesRef.current.value = '';
    } catch (failure) {
      // The API's own message, so the screen cannot state a rule the server
      // does not enforce. Nothing typed is cleared: a duplicate Code is one
      // field to change, and re-choosing the files would be the Administrator
      // doing the work twice.
      refuse(failure instanceof ApiRequestError ? failure.message : UNEXPECTED, fieldFor(failure));
    } finally {
      setSubmitting(false);
    }
  }

  // One expression rather than a nested ternary in the markup: three states,
  // and the empty one is the default.
  let indicator = '';
  if (submitting) indicator = SAVING;
  else if (added !== null) indicator = SAVED;

  // One node, rendered directly below whichever field is at fault — and after
  // all four when the failure belongs to none of them. A form with four
  // controls and one error parked under all of them leaves a screen-reader
  // user on the wrong one hearing a sentence about another. Only one of the
  // five slots below is ever filled, so this screen never renders a second
  // alert.
  const alert =
    error === null ? null : (
      <p className={styles.error} id={errorId} role="alert">
        {error.message}
      </p>
    );

  return (
    <section className={styles.screen}>
      <h1 className={styles.title}>Add tile</h1>

      <form className={styles.form} onSubmit={(event) => void handleSubmit(event)} noValidate>
        <div className={styles.field}>
          <label className={styles.label} htmlFor={codeId}>
            Code
          </label>
          {/* The identity (AD-18), and the answer a scan returns. Set in the
              monospace role DESIGN.md reserves for a value read character by
              character: `RP.CMA.0001DJ.SM.0T` is transcribed from a physical
              tile, and 0/O and 1/I must not be confusable while it is typed.
              Case is preserved — `1Jk` is not `1JK`. */}
          <input
            className={styles.code}
            id={codeId}
            name="code"
            maxLength={MAX_CODE_LENGTH}
            type="text"
            autoComplete="off"
            autoCapitalize="none"
            autoCorrect="off"
            spellCheck={false}
            ref={codeRef}
            value={code}
            aria-invalid={error?.fieldAtFault === 'code'}
            aria-describedby={error?.fieldAtFault === 'code' ? errorId : undefined}
            onChange={(event) => typed(setCode)(event.target.value)}
          />
          {error?.fieldAtFault === 'code' && alert}
        </div>

        <div className={styles.field}>
          <label className={styles.label} htmlFor={sizeId}>
            Size
          </label>
          <input
            className={styles.input}
            id={sizeId}
            name="size"
            maxLength={MAX_SIZE_LENGTH}
            type="text"
            autoComplete="off"
            autoCapitalize="characters"
            autoCorrect="off"
            spellCheck={false}
            ref={sizeRef}
            value={size}
            aria-invalid={error?.fieldAtFault === 'size'}
            aria-describedby={error?.fieldAtFault === 'size' ? errorId : undefined}
            onChange={(event) => typed(setSize)(event.target.value)}
          />
          <p className={styles.hint}>The top-level folder, such as 45X90.</p>
          {error?.fieldAtFault === 'size' && alert}
        </div>

        <div className={styles.field}>
          <label className={styles.label} htmlFor={categoryId}>
            Category (optional)
          </label>
          <input
            className={styles.input}
            id={categoryId}
            name="category"
            maxLength={MAX_CATEGORY_LENGTH}
            type="text"
            autoComplete="off"
            autoCorrect="off"
            spellCheck={false}
            ref={categoryRef}
            value={category}
            aria-invalid={error?.fieldAtFault === 'category'}
            aria-describedby={error?.fieldAtFault === 'category' ? errorId : undefined}
            onChange={(event) => typed(setCategory)(event.target.value)}
          />
          {/* AD-18: a Category that cannot be recovered is recorded as UNKNOWN
              and flagged for follow-up, never dropped — so leaving this empty
              is a supported answer rather than an omission to apologise for. */}
          <p className={styles.hint}>
            The range or pattern, such as CREMA MARMOL. Left empty, the tile is filed under
            UNKNOWN.
          </p>
          {error?.fieldAtFault === 'category' && alert}
        </div>

        <div className={styles.field}>
          <label className={styles.label} htmlFor={imagesId}>
            Reference images
          </label>
          {/* The hint below is bound to this input, and bound first: the count
              and the size ceiling are stated nowhere else, so a screen-reader
              user who never sees that paragraph would meet both as a refusal.
              A refusal adds its sentence to the description, it does not
              replace this one.

              `accept` is a *hint to the file picker*, never a check: the server
              decides by content and nothing else (AGENTS.md Policy), and the
              real catalogue holds `.tif` alongside `.jpg`, so `image/*` is
              deliberately wide. A narrower list would hide files that are
              perfectly valid. */}
          <input
            className={styles.file}
            id={imagesId}
            name="images"
            type="file"
            accept="image/*"
            multiple
            ref={imagesRef}
            aria-invalid={error?.fieldAtFault === 'images'}
            aria-describedby={
              error?.fieldAtFault === 'images' ? `${imagesHintId} ${errorId}` : imagesHintId
            }
            onChange={chooseFiles}
          />
          <p className={styles.hint} id={imagesHintId}>
            One image per tile is normal. Up to {MAX_IMAGES_PER_REQUEST} at a time, each under{' '}
            {MAX_IMAGE_BYTES / (1024 * 1024)} MB. Saving can take a minute or two — each image is
            indexed before it is stored.
          </p>
          {error?.fieldAtFault === 'images' && alert}
        </div>

        {/* A failure that belongs to no field — the request never reached the
            API, or the server has no image pipeline installed. Inserted rather
            than emptied and refilled: a `role="alert"` node appearing in the
            document is what announces it. */}
        {error !== null && error.fieldAtFault === null && alert}

        <div className={styles.actions}>
          {/* The screen's one accent control (DESIGN.md: exactly one per
              screen). Back is the secondary, navy-outlined one. */}
          <button className={styles.submit} type="submit" disabled={submitting}>
            Save
          </button>
          {/* Disabled in flight, exactly as the submit is: a click that
              unmounted this screen mid-request would leave the Administrator
              unsure whether the tile was added. */}
          <button className={styles.back} type="button" onClick={onBack} disabled={submitting}>
            Back
          </button>
          {/* Inline, beside the control that triggered it — never a corner
              toast (EXPERIENCE.md's Save indicator row). The live region is in
              the document at rest so the change of text is what gets
              announced, rather than the arrival of a whole new node. */}
          <span
            className={added !== null ? `${styles.indicator} ${styles.saved}` : styles.indicator}
            role="status"
          >
            {indicator}
          </span>
        </div>
      </form>

      {added !== null && (
        // A labelled region, deliberately **not** a second live region. The
        // indicator above already announces the outcome as `Saved.`; marking
        // this panel `role="status"` too made a successful save announce
        // twice, the second time by reading out the whole summary. A screen
        // reader reaches it by its heading, which is what a region is for.
        <section className={styles.result} aria-labelledby={resultId}>
          <h2 className={styles.subtitle} id={resultId}>
            Tile added
          </h2>
          <dl className={styles.summary}>
            <dt className={styles.term}>Code</dt>
            <dd className={styles.codeValue}>{added.code}</dd>
            <dt className={styles.term}>Size</dt>
            <dd className={styles.value}>{added.size}</dd>
            <dt className={styles.term}>Category</dt>
            {/* `category` is nullable on the wire. The endpoint resolves a
                blank one to the AD-18 sentinel and so never sends null today,
                but the contract permits it and Story 2.2's edit path will
                read the same field — an empty `<dd>` under a `<dt>` is the
                one outcome this panel must not produce. */}
            <dd className={styles.value}>{added.category ?? UNKNOWN_CATEGORY}</dd>
            <dt className={styles.term}>Reference images</dt>
            <dd className={styles.value}>{added.reference_images.length}</dd>
          </dl>
          {/* FR-19: a reference image below the texture threshold matches any
              washed-out photo and can never be reliably retrieved itself. The
              epic asks for the flag on the tile's own screen rather than
              buried in a report, and this is that screen until Story 2.2's
              detail view exists. Stated in plain words, not as a score. */}
          {added.reference_images.some((image) => image.featureless) && (
            <p className={styles.flag}>
              One of these images has very little visible texture, so scans may not find this
              tile reliably. Consider re-shooting it.
            </p>
          )}
        </section>
      )}
    </section>
  );
}
