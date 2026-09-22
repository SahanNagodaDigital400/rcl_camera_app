import { useId, useRef, useState } from 'react';
import type { ChangeEvent, FormEvent, JSX } from 'react';

import {
  API_PREFIX,
  ApiRequestError,
  CODE_ALREADY_EXISTS,
  IMAGE_NOT_FOUND,
  IMAGE_TOO_LARGE,
  INVALID_CATEGORY,
  INVALID_CODE,
  INVALID_IMAGE,
  INVALID_SIZE,
  LAST_REFERENCE_IMAGE,
  MALFORMED_RESPONSE,
  TILE_NOT_FOUND,
  TOO_MANY_IMAGES,
  UNREADABLE_IMAGE,
  UPLOAD_TIMEOUT_MS,
  apiRequest,
} from '../api/client';
import { ConfirmDialog } from '../components/ConfirmDialog';
import styles from './EditTileScreen.module.css';
import { isTile, UNKNOWN_CATEGORY } from '@rocell/schema/tile';
import type { Tile } from '@rocell/schema/tile';

/**
 * Edit tile — where an Administrator corrects one (FR-15).
 *
 * Rendered *inside* the shell, in place of the home panel, so it carries no
 * `<main>` of its own: `AppShell` already provides the one main landmark and
 * the focus target the gate moves focus to on a screen swap. It is modelled on
 * `AddTileScreen` — same form rhythm, same one-alert-in-one-slot treatment,
 * same accent primary beside a navy-outlined Back, same `Saving…` → `Saved.`
 * indicator — because an Administrator moving between the two catalogue forms
 * should not read them as two different applications.
 *
 * **Two stages, one screen, and nothing in the app opens the first any more.**
 * EXPERIENCE.md line 36 opens Edit Tile from a Catalogue row, and Story 2.5
 * built that surface: a row hands this screen the whole `Tile` it already
 * holds, so the form is on screen from the first render with no Code to type
 * and no request made. `App` renders this screen only with a tile — its
 * `currentScreen` answers `'catalogue'` for an `'edit-tile'` section holding
 * none — so the Code lookup stage is **not an entry point**.
 *
 * It is the state this screen falls back to, and it is still reachable: a save
 * or a removal refused `404` (the tile was renamed or removed from under the
 * form) clears the tile and leaves the Administrator here with the refusal and
 * a way to find another one, and the screen rendered on its own without a
 * `tile` prop starts here too. It is a plain `GET` against
 * `/admin/tiles/lookup`, an **exact** match by design, so a partial Code finds
 * nothing here and substring searching is the Catalogue's. Exactly one of the
 * two primary actions is on screen at a time, so the screen still has exactly
 * one accent control (DESIGN.md).
 *
 * **The Code is the tile's identity** (AD-18), and the vocabulary follows:
 * Tile, Code, Size, Category, Reference image. `Product` and `Face` are retired
 * words and appear nowhere on this screen or in its stylesheet.
 *
 * **An absent part means "unchanged", so this form sends all three.** The
 * fields are prefilled from the tile that was found, so a save that touched
 * nothing sends what is already stored and the API records a change set of
 * `{}` — which is the honest record of an accepted edit that moved nothing.
 *
 * **Two live regions, one per stage, and never both speaking.** Each action row
 * carries its own `role="status"` beside the control that triggers it — the
 * lookup's `Finding…` and the save's `Saving…` → `Saved.` — because an
 * indicator that sat in one row would describe a press made in the other. They
 * cannot overlap: both buttons are disabled while either request is open, so
 * only one of the two is ever non-empty.
 *
 * **Removal is confirmed, never quiet.** Marking a reference image is a toggle
 * and nothing happens when it is pressed; the removal travels with the save,
 * and a save that removes anything goes through a `ConfirmDialog` that names
 * the tile and the consequence first (EXPERIENCE.md's Confirmation dialog row).
 * A tile must keep at least one reference image — the server refuses an edit
 * that would empty it (FR-7), and this screen renders that refusal in the
 * server's own words rather than restating a rule it does not own.
 *
 * **The tile itself can be removed here too** (FR-16), and this is the only
 * door in the product that reaches one — deliberately not a verb on a
 * Catalogue row, where one mis-click on a dense list would take out an entry
 * nobody can restore. It is also what closes the loop the last-image refusal
 * opens, since its own sentence tells the Administrator to "remove the tile
 * instead". The control is
 * destructive-filled and carries the word, never the accent: Save is this
 * screen's one accent action once a tile is loaded. It confirms in the same
 * `ConfirmDialog`, and where a confirmed removal leaves depends on how the
 * screen was opened: a tile handed over by a Catalogue row has nowhere to stay,
 * so the screen leaves through `onRemoved`; a tile this screen found for itself
 * returns to the lookup stage with the removal announced, because that is where
 * it came from. There is no undo, no restore and no trash state — the
 * confirmation is the safeguard.
 *
 * **Reference images are proxied, never linked** (AD-9). Each thumbnail's `src`
 * is `GET /admin/tiles/{id}/images/{imageId}` on this same origin, so the
 * session cookie travels with it and the server re-checks the Administrator
 * role on every one. `apps/web` holds no storage URL, presigned or otherwise,
 * and the `ReferenceImage` contract has nowhere to put one.
 *
 * **The role-conditional door that opens this screen is a convenience, never
 * the control.** `App` renders it only for an Administrator, but the cached
 * `User` is a render cache and never an authorization decision (AGENTS.md
 * Policy): the server refuses a Staff caller at both routes through
 * `require_administrator`, which re-reads the role from Postgres on every
 * request (AD-3).
 *
 * Deliberately absent:
 *
 * - **No similarity value, in any form** (AD-20).
 * - **No catalogue list and no substring search.** `CatalogueScreen` is that
 *   surface, and the lookup here is deliberately not a second, narrower copy
 *   of it: it answers one exact Code, and a prefix match returning "the" tile
 *   would hand the Administrator whichever row sorted first to edit.
 * - **No undo after a removal**, and no restore, trash state or grace period.
 *   The confirmation is the safeguard; a tile that should come back is added
 *   again.
 * - **No client-side check of what a file is.** Content decides, and only the
 *   server can sniff content (AGENTS.md Policy).
 */

/** Shown for a failure that arrives as something other than an `ApiRequestError`. */
const UNEXPECTED = 'The tile could not be saved. Try again.';
const LOOKUP_FAILED = 'The tile could not be looked up. Try again.';
const REMOVE_FAILED = 'The tile could not be removed. Try again.';

/**
 * Refuse an empty field here rather than letting the API answer for it.
 *
 * The forms are `noValidate` — the browser's own bubble is unstyled, untestable
 * and disappears on the next keystroke — so these are what `required` would
 * otherwise have done.
 */
const BLANK_LOOKUP = 'Enter the tile’s code.';
const BLANK_CODE = 'Enter the tile’s code.';
const BLANK_SIZE = 'Enter the tile’s size.';

/**
 * The one refusal this screen states in its own words, before asking the server.
 *
 * EXPERIENCE.md:148 asks for a refusal to *replace* the confirmation rather
 * than follow it — the pattern `UserListScreen` uses for the last-Administrator
 * case — and that can only be decided **before** a request is made. So on this
 * one path no envelope ever arrives and this copy is the only sentence the
 * Administrator sees.
 *
 * Character for character `api.catalogue.LAST_IMAGE`, and pinned to it by
 * `error-code-parity.test.ts`'s `SENTENCES`: a screen that went on stating a
 * rule in words the server no longer uses is exactly the drift that file
 * exists to catch. The server still refuses the same edit with the same
 * sentence if this check is ever wrong.
 */
const MUST_KEEP_AN_IMAGE =
  'A tile must keep at least one reference image. ' +
  'Add the replacement in the same save, or remove the tile instead.';

/** The save indicator's two spoken states (DESIGN.md's `save-indicator`). */
const SAVING = 'Saving…';
const SAVED = 'Saved.';

/**
 * The same indicator's word for the one in-flight request that is not a save.
 *
 * A removal borrows `submitting` — it freezes the same controls for the same
 * reason — but the form stays mounted behind the confirmation sheet's scrim
 * while the `DELETE` is out, so the indicator is legible the whole time. Left
 * on `SAVING`, the most destructive action on the screen would spend its whole
 * duration calling itself a save.
 */
const REMOVING = 'Removing…';

/**
 * The server's own bounds, mirrored onto the inputs.
 *
 * **The server's copy is the authority** — `shared_schema.tile` bounds all of
 * these and the endpoint answers with a named `422` past them, whatever this
 * file says. These exist only to keep the one refusal the Administrator cannot
 * act on off the screen, and, for the file count and the byte ceiling, to say
 * the limit before the bytes have travelled.
 *
 * Written down here rather than imported because nothing crosses that boundary
 * at build time; `error-code-parity.test.ts` pins each against its Python twin,
 * so a drift is a failing test rather than a silent divergence.
 */
const MAX_CODE_LENGTH = 200;
const MAX_SIZE_LENGTH = 100;
const MAX_CATEGORY_LENGTH = 200;
const MAX_IMAGES_PER_REQUEST = 8;
const MAX_IMAGE_BYTES = 134217728;

/** The two bounds worth refusing *before* the upload rather than after it. */
const TOO_MANY_FILES =
  `Add at most ${MAX_IMAGES_PER_REQUEST} reference images at a time. ` +
  'Save, then add the rest.';
const FILE_TOO_LARGE = `Each reference image must be under ${
  MAX_IMAGE_BYTES / (1024 * 1024)
} MB.`;

/** Which field a failure is about — and therefore which one is marked and focused. */
type Field = 'lookup' | 'code' | 'size' | 'category' | 'images';

/**
 * What went wrong, and which field is at fault.
 *
 * `fieldAtFault` is not decoration: it drives `aria-invalid` and focus. Marking
 * an input invalid because the model artifact is missing on the server tells a
 * screen-reader user their typing was malformed when it was not.
 */
interface FormError {
  message: string;
  fieldAtFault: Field | null;
}

/** The API's code, mapped to the control the Administrator has to fix. */
function fieldFor(failure: unknown, stage: 'lookup' | 'edit'): Field | null {
  if (!(failure instanceof ApiRequestError)) return null;
  if (stage === 'lookup') {
    // On the lookup there is one input, and both of its refusals are about it:
    // a Code the endpoint will not accept, and a Code nothing holds.
    if (failure.code === INVALID_CODE || failure.code === TILE_NOT_FOUND) return 'lookup';
    return null;
  }
  if (failure.code === INVALID_CODE || failure.code === CODE_ALREADY_EXISTS) return 'code';
  if (failure.code === INVALID_SIZE) return 'size';
  if (failure.code === INVALID_CATEGORY) return 'category';
  if (
    failure.code === INVALID_IMAGE ||
    failure.code === UNREADABLE_IMAGE ||
    failure.code === IMAGE_TOO_LARGE ||
    failure.code === TOO_MANY_IMAGES ||
    failure.code === LAST_REFERENCE_IMAGE ||
    failure.code === IMAGE_NOT_FOUND
  ) {
    return 'images';
  }
  // `matching_unavailable`, `pipeline_stamp_mismatch`, `tile_not_found` and
  // `administrator_required` land here, deliberately: nothing the Administrator
  // chose is at fault, and pointing at a field would be a lie. The screen
  // renders the server's sentence, which in the first case names the setup step
  // an operator has to run and in the third says the tile may have moved.
  return null;
}

/**
 * Narrow a response body to the shared `Tile`, or fail loudly.
 *
 * `isTile` rejects a missing key, a malformed UUID, a non-UTC timestamp — and
 * any extra key, which is how a storage reference (AD-9) or a similarity value
 * (AD-20) would announce itself rather than being quietly ignored.
 */
function asTile(body: unknown, status: number): Tile {
  if (!isTile(body)) {
    throw new ApiRequestError(
      MALFORMED_RESPONSE,
      'The server returned an unexpected response.',
      status,
    );
  }
  return body;
}

/**
 * `onBack` returns to whatever opened this screen — the Catalogue, when a row
 * did.
 *
 * `tile` is the Tile a Catalogue row handed over. Read **once**, at mount, as
 * the initial state and never reconciled: `App` keys this element on `tile.id`,
 * so swapping one tile for another remounts the screen rather than re-seeding a
 * form that may be half-edited. That is `EditUserScreen`'s own arrangement for
 * the same reason.
 *
 * `onRemoved` is where a **confirmed removal** leaves for, and it is only ever
 * called when a `tile` was handed over. That case has nowhere to stay: the
 * screen was opened about one tile, that tile is gone, and re-rendering as a
 * code-entry stage would leave an Administrator looking at a box for a Code
 * that no longer names anything with `Back` as the only way out. A screen that
 * found its own tile keeps the existing behaviour — it returns to its lookup
 * stage with the removal announced, because the lookup is where it came from.
 */
export function EditTileScreen({
  onBack,
  onRemoved,
  tile: opened,
}: {
  onBack: () => void;
  onRemoved?: () => void;
  tile?: Tile;
}): JSX.Element {
  const lookupId = useId();
  const codeId = useId();
  const sizeId = useId();
  const categoryId = useId();
  const imagesId = useId();
  const errorId = useId();
  const lookupHintId = useId();
  const sizeHintId = useId();
  const categoryHintId = useId();
  const imagesHintId = useId();
  const imagesLabelId = useId();
  const removalLabelId = useId();
  const removalHintId = useId();

  const [lookupCode, setLookupCode] = useState('');
  /**
   * The tile being edited, seeded from the prop when a Catalogue row opened
   * this screen.
   *
   * `opened ?? null` rather than an effect that adopts it: an effect would
   * paint the code-entry stage for one frame and replace it on the next, which
   * is a flash of a form the Administrator never asked for — and would move
   * focus and state around after the commit. As the initial value there is no
   * such frame, and a row's tile is on the edit stage from the first render
   * with nothing to look up and no request made.
   */
  const [tile, setTile] = useState<Tile | null>(opened ?? null);
  const [code, setCode] = useState(opened?.code ?? '');
  const [size, setSize] = useState(opened?.size ?? '');
  const [category, setCategory] = useState(opened?.category ?? '');
  /** The ids marked for removal. Nothing is removed until the save lands. */
  const [marked, setMarked] = useState<readonly string[]>([]);
  const [files, setFiles] = useState<File[]>([]);
  const [error, setError] = useState<FormError | null>(null);
  const [looking, setLooking] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [saved, setSaved] = useState(false);
  /**
   * What the lookup stage says once a removal has landed, and nothing else.
   *
   * Spoken by the lookup row's own live region rather than by a fourth one:
   * after a removal the edit form is gone, so its indicator is gone with it,
   * and the stage the Administrator is left looking at is the one that has to
   * say what happened. Cleared the moment anything else is typed or pressed, so
   * it can never describe a tile other than the one it named.
   */
  const [removed, setRemoved] = useState('');
  /**
   * Which sheet is open, if any.
   *
   * Four states rather than a boolean. EXPERIENCE.md:148 has the third: an
   * operation that was never going to be honoured opens the dialog *as* the
   * refusal instead of walking the Administrator through a confirm that would
   * have failed. The fourth is the tile removal, which is a different question
   * from a destructive save — it names the tile rather than a count of images,
   * and confirming it ends the form rather than submitting it. `ConfirmDialog`
   * already has both shapes, and only ever one sheet is rendered.
   */
  const [sheet, setSheet] = useState<'none' | 'confirm' | 'refusal' | 'remove'>('none');

  const lookupRef = useRef<HTMLInputElement>(null);
  const codeRef = useRef<HTMLInputElement>(null);
  const sizeRef = useRef<HTMLInputElement>(null);
  const categoryRef = useRef<HTMLInputElement>(null);
  const imagesRef = useRef<HTMLInputElement>(null);

  function focus(field: Field): void {
    const target =
      field === 'lookup'
        ? lookupRef
        : field === 'code'
          ? codeRef
          : field === 'size'
            ? sizeRef
            : field === 'category'
              ? categoryRef
              : imagesRef;
    target.current?.focus();
  }

  function refuse(message: string, field: Field | null): void {
    setSaved(false);
    setRemoved('');
    setError({ message, fieldAtFault: field });
    if (field !== null) focus(field);
  }

  /** Seed the form from a tile the API just handed back. */
  function adopt(found: Tile): void {
    setRemoved('');
    setTile(found);
    setCode(found.code);
    setSize(found.size);
    setCategory(found.category ?? '');
    setMarked([]);
    setFiles([]);
    if (imagesRef.current) imagesRef.current.value = '';
  }

  /** Take what was typed, and retire the saved indicator beside it. */
  function typed<T>(set: (value: T) => void): (value: T) => void {
    return (value) => {
      setSaved(false);
      setRemoved('');
      set(value);
    };
  }

  function chooseFiles(event: ChangeEvent<HTMLInputElement>): void {
    setSaved(false);
    setError(null);
    setFiles([...(event.target.files ?? [])]);
  }

  function toggleMarked(imageId: string): void {
    setSaved(false);
    setError(null);
    setMarked((current) =>
      current.includes(imageId)
        ? current.filter((held) => held !== imageId)
        : [...current, imageId],
    );
  }

  async function handleLookup(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    // Both, and for the mirror of `handleSave`'s reason: the Find *button* is
    // `disabled={looking || submitting}`, but the lookup field is not, and
    // pressing Enter in a text field submits the form directly without ever
    // consulting the button. Guarding only `looking` therefore lets a lookup
    // start underneath an in-flight save, and its `adopt()` would then reset
    // code, size, category, marks and files out from under the request the
    // Administrator is waiting on.
    if (looking || submitting) return;

    if (lookupCode.trim() === '') {
      refuse(BLANK_LOOKUP, 'lookup');
      return;
    }

    setLooking(true);
    setError(null);
    setSaved(false);
    // The announcement is about a tile this lookup is not looking for. Cleared
    // here and not only on the next keystroke, because pressing Find again with
    // the field untouched would otherwise leave `<code> removed.` standing
    // under `Finding…` — and wearing the navy the announcement carries.
    setRemoved('');

    try {
      // `URLSearchParams` rather than a template literal: a Code holds `.`, and
      // the real catalogue holds free text after the code — a raw interpolation
      // would send `6LD.MA Quarry Stone Natural` with a bare space in it.
      const query = new URLSearchParams({ code: lookupCode });
      adopt(asTile(await apiRequest(`/admin/tiles/lookup?${query.toString()}`), 200));
    } catch (failure) {
      // The API's own sentence, so the screen cannot state a rule the server
      // does not enforce. The form below is cleared with it: a tile that is no
      // longer on screen must not leave its fields behind to be saved.
      setTile(null);
      refuse(
        failure instanceof ApiRequestError ? failure.message : LOOKUP_FAILED,
        fieldFor(failure, 'lookup'),
      );
    } finally {
      setLooking(false);
    }
  }

  /** Every check the screen makes before it is worth sending anything. */
  function refusedLocally(): boolean {
    if (code.trim() === '') {
      refuse(BLANK_CODE, 'code');
      return true;
    }
    if (size.trim() === '') {
      refuse(BLANK_SIZE, 'size');
      return true;
    }
    if (files.length > MAX_IMAGES_PER_REQUEST) {
      refuse(TOO_MANY_FILES, 'images');
      return true;
    }
    if (files.some((file) => file.size > MAX_IMAGE_BYTES)) {
      refuse(FILE_TOO_LARGE, 'images');
      return true;
    }
    return false;
  }

  async function save(): Promise<void> {
    // `looking` as well, because the confirmation sheet calls this directly
    // rather than through `handleSave` and so does not inherit its guard.
    if (tile === null || submitting || looking) return;

    setSubmitting(true);
    setError(null);
    setSaved(false);

    // Multipart, because the request carries files. The part names are the
    // endpoint's parameter names; `images` and `remove_image_ids` each repeat
    // once per item, which is how a multipart body expresses a list.
    const body = new FormData();
    body.append('code', code);
    body.append('size', size);
    // Sent unless it would *introduce* a Category the tile never had. The
    // endpoint reads an absent part as "unchanged" and a blank one as "file it
    // under the sentinel" (AD-18) — which is right for a Category the
    // Administrator cleared, and wrong for one that was never there. Without
    // this guard the screen refiles every null-Category tile under UNKNOWN on
    // any save, including one that only fixed a Code, and writes a
    // `category: null -> UNKNOWN` line into the audit log for it. The API
    // keeps that distinction deliberately; this is the half that honours it.
    if (category !== '' || tile.category !== null) body.append('category', category);
    for (const imageId of marked) body.append('remove_image_ids', imageId);
    for (const file of files) body.append('images', file);

    try {
      // `UPLOAD_TIMEOUT_MS`, not the default. An edit that uploads makes the
      // server embed every new image — 16 forward passes each (AD-13) — and the
      // default 15s would abort a request the server then commits anyway.
      adopt(
        asTile(
          await apiRequest(`/admin/tiles/${tile.id}`, {
            method: 'PATCH',
            body,
            timeoutMs: UPLOAD_TIMEOUT_MS,
          }),
          200,
        ),
      );
      setSheet('none');
      setSaved(true);
    } catch (failure) {
      // Nothing typed is cleared and nothing stays marked-but-unexplained: the
      // dialog closes so the refusal is readable on the form it belongs to.
      setSheet('none');
      const dropped = failure instanceof ApiRequestError && failure.code === TILE_NOT_FOUND;
      if (dropped) {
        // The tile moved or went while this form was open. Everything below
        // this line would fail identically on every further Save, with no way
        // forward but Back — so the form goes with it and the lookup above is
        // the way back in, exactly as it is when a lookup misses.
        setTile(null);
        setMarked([]);
      }
      if (failure instanceof ApiRequestError && failure.code === IMAGE_NOT_FOUND) {
        // The same dead end, one level down: the marked id names an image the
        // endpoint no longer holds, so every further Save carries it again and
        // is refused again, with nothing on screen saying which mark is the
        // bad one. The marks go and the tile stays, because the tile is still
        // there and the rest of the form is still the Administrator's work.
        setMarked([]);
      }
      const field = fieldFor(failure, 'edit');
      refuse(failure instanceof ApiRequestError ? failure.message : UNEXPECTED, field);
      // `refuse` moves focus only when a control is at fault, and
      // `tile_not_found` faults none. But the form holding the focused control
      // has just been unmounted, so focus would fall to `<body>`, outside the
      // alert that explains why — and only in this branch, since every other
      // null-field refusal (`matching_unavailable`, `pipeline_stamp_mismatch`)
      // leaves the form and its focus where they were.
      if (dropped && field === null) lookupRef.current?.focus();
    } finally {
      setSubmitting(false);
    }
  }

  /**
   * FR-16 — take the whole tile out, once the sheet has been confirmed.
   *
   * **Nothing is sent until the dialog's own control is pressed**, which is
   * what makes a destructive action safe to sit one press away from the form.
   * The same `submitting`/`looking` guard the save carries, because the sheet
   * calls this directly and so inherits neither.
   *
   * On success there is no tile left for the form to be about, so the screen
   * returns to its lookup stage: the form unmounts, the removal is announced
   * beside the lookup, and focus moves to the lookup field — the one control
   * that can still do anything, and the one the announcement belongs to.
   *
   * A `404` is the dead end the save already models: the tile went while this
   * form was open, so the form goes with it and the server's own sentence is
   * what explains why. Any other refusal leaves the form standing — the tile is
   * still there, and the rest of the form is still the Administrator's work.
   */
  async function removeTile(): Promise<void> {
    if (tile === null || submitting || looking) return;

    // Read before the request, because the answer is a `204` with no body and
    // the tile is cleared from state the moment it lands: the announcement has
    // to name the Code that was removed, not whatever is loaded afterwards.
    const removedCode = tile.code;

    setSubmitting(true);
    setError(null);
    setSaved(false);
    setRemoved('');

    try {
      // `apiRequest` answers `null` for a `204` without trying to parse a body,
      // so there is nothing to narrow here and nothing to render from.
      await apiRequest(`/admin/tiles/${tile.id}`, { method: 'DELETE' });
      setSheet('none');
      setTile(null);
      setMarked([]);
      setFiles([]);
      if (imagesRef.current) imagesRef.current.value = '';
      if (opened !== undefined && onRemoved !== undefined) {
        // Handed a tile by a Catalogue row, and that tile no longer exists —
        // so this screen has nothing left to be about and leaves. The
        // Catalogue's refetch on mount is what shows the row gone; staying
        // would render a code-entry stage for a Code that names nothing, with
        // `Back` as the only way out of it.
        //
        // The state above is still cleared first, and not only for tidiness:
        // `onRemoved` is a request to the gate, not a guarantee of an unmount,
        // and a `File` staged for a tile that is gone must not survive either
        // way.
        onRemoved();
        return;
      }
      setRemoved(`${removedCode} removed.`);
      lookupRef.current?.focus();
    } catch (failure) {
      // The dialog closes either way, so the refusal is readable on the screen
      // it belongs to rather than behind a scrim.
      setSheet('none');
      const dropped = failure instanceof ApiRequestError && failure.code === TILE_NOT_FOUND;
      if (dropped) {
        // Everything the success path clears, because the outcome on screen is
        // the same one: the form is gone and the tile it described is gone.
        // Staged files and the native input's own value are the two that do not
        // unmount with it — the input is recreated empty by React, but the
        // `File` objects in state are not, and a later save would carry files
        // chosen for a tile that no longer exists.
        setTile(null);
        setMarked([]);
        setFiles([]);
        if (imagesRef.current) imagesRef.current.value = '';
      }
      refuse(failure instanceof ApiRequestError ? failure.message : REMOVE_FAILED, null);
      // `refuse` moves focus only when a control is at fault, and nothing here
      // faults one. With the form just unmounted, focus would otherwise fall to
      // `<body>` — outside the alert that explains why.
      if (dropped) lookupRef.current?.focus();
    } finally {
      setSubmitting(false);
    }
  }

  const removing = marked.length;
  /**
   * What the tile is left with if this save lands. Named in the confirmation.
   *
   * Declared above its first reader rather than beside the rest of the render's
   * derived values: `handleSave` below consults it, and a `const` is not
   * hoisted, so leaving it further down works only for as long as nothing calls
   * that handler during the render pass that defines it.
   */
  const remaining = (tile?.reference_images.length ?? 0) - removing + files.length;

  function handleSave(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    // Both, matching the submit button's own `disabled={submitting || looking}`:
    // pressing Enter in a text field submits the form directly and never
    // consults the button, so guarding only `submitting` lets a save start
    // underneath an in-flight lookup whose answer would then overwrite it.
    if (submitting || looking) return;
    if (refusedLocally()) return;
    if (marked.length > 0 && remaining < 1) {
      // EXPERIENCE.md:148: an operation that was never going to be honoured is
      // refused *instead of* being confirmed. Walking the Administrator through
      // "Remove and save" and then answering `409 last_reference_image` asks
      // them to authorise something the product had already decided against —
      // and the sheet would have promised "keeps 0 reference images" on the way
      // through. The server enforces the floor regardless (FR-7); this is the
      // courtesy on top of the control.
      setSaved(false);
      setError(null);
      setSheet('refusal');
      return;
    }
    if (marked.length > 0) {
      // Destructive, so it is confirmed in a sheet that names the tile and the
      // consequence first (EXPERIENCE.md's Confirmation dialog row) — never a
      // bare "Are you sure?".
      setSaved(false);
      setError(null);
      setSheet('confirm');
      return;
    }
    void save();
  }

  // One expression rather than a nested ternary in the markup: three states,
  // and the empty one is the default. `submitting` covers both writes, so the
  // open removal sheet is what tells them apart — it is set before the request
  // and cleared only once the answer is in, in both the success and the
  // refusal branch of `removeTile`.
  let indicator = '';
  if (submitting) indicator = sheet === 'remove' ? REMOVING : SAVING;
  else if (saved) indicator = SAVED;

  // One node, rendered directly below whichever field is at fault — and after
  // all of them when the failure belongs to none. A form with five controls and
  // one error parked under all of them leaves a screen-reader user on the wrong
  // one hearing a sentence about another. Only one slot is ever filled, so this
  // screen never renders a second alert.
  const alert =
    error === null ? null : (
      <p className={styles.error} id={errorId} role="alert">
        {error.message}
      </p>
    );

  return (
    <section className={styles.screen}>
      <h1 className={styles.title}>Edit tile</h1>

      <form className={styles.form} onSubmit={(event) => void handleLookup(event)} noValidate>
        <div className={styles.field}>
          <label className={styles.label} htmlFor={lookupId}>
            Find a tile by code
          </label>
          {/* Set in the monospace role DESIGN.md reserves for a value read
              character by character: the Code is transcribed from a physical
              tile, and 0/O and 1/I must not be confusable while it is typed.
              Case is preserved — `1Jk` is not `1JK`. */}
          <input
            className={styles.code}
            id={lookupId}
            name="lookup_code"
            maxLength={MAX_CODE_LENGTH}
            type="text"
            autoComplete="off"
            autoCapitalize="none"
            autoCorrect="off"
            spellCheck={false}
            ref={lookupRef}
            value={lookupCode}
            aria-invalid={error?.fieldAtFault === 'lookup'}
            aria-describedby={
              error?.fieldAtFault === 'lookup' ? `${lookupHintId} ${errorId}` : lookupHintId
            }
            onChange={(event) => typed(setLookupCode)(event.target.value)}
          />
          {/* The match is exact, and saying so is what stops an Administrator
              reading a `404` as "the tile is gone" when it is "that is not the
              whole code". Browsing and searching by partial code is the
              Catalogue's, and a row there opens this screen with its tile
              already loaded — so this stage is the fallback, not the way in. */}
          <p className={styles.hint} id={lookupHintId}>
            The whole code, exactly as it is filed.
          </p>
          {error?.fieldAtFault === 'lookup' && alert}
        </div>

        {/* A lookup failure that belongs to no field — the request never
            reached the API, it timed out, the session ended, or the body was
            not a Tile. Without this slot the only null-field slot on the screen
            is inside the edit form below, which is not rendered while no tile
            is loaded: Find would look like it had done nothing at all.

            Bounded on `tile === null` so it cannot fire at the same time as the
            edit form's own null slot — exactly one of the two is ever in the
            document, which is what keeps this screen to one alert. */}
        {error !== null && error.fieldAtFault === null && tile === null && alert}

        <div className={styles.actions}>
          {/* The screen's one accent control **while no tile is loaded**, and
              the navy outline once one is: Save below takes the accent then,
              and DESIGN.md allows exactly one filled primary per screen. One
              element with a conditional treatment rather than two elements,
              because two would be two tab stops of the same name whenever
              React reused neither. */}
          <button
            className={tile === null ? styles.submit : styles.back}
            type="submit"
            disabled={looking || submitting}
          >
            Find
          </button>
          <button
            className={styles.back}
            type="button"
            onClick={onBack}
            disabled={looking || submitting}
          >
            Back
          </button>
          {/* The lookup's own wait, so a slow round trip is not a screen that
              appears to have ignored the press — and, after a removal, what
              says the tile is gone. Empty at rest, and the two can never
              overlap: starting a lookup clears the announcement.

              Navy once it has something to report, never orange: this is the
              confirmation that an action fired, and DESIGN.md's
              `save-indicator` reserves the accent for one that has not. */}
          <span
            className={removed === '' ? styles.indicator : `${styles.indicator} ${styles.saved}`}
            role="status"
          >
            {looking ? 'Finding…' : removed}
          </span>
        </div>
      </form>

      {/* Rendered only when a tile has been found: an edit form with nothing to
          edit is a set of empty boxes that look like they would create one. */}
      {tile !== null && (
        <form className={styles.form} onSubmit={handleSave} noValidate>
          <div className={styles.field}>
            <label className={styles.label} htmlFor={codeId}>
              Code
            </label>
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
              aria-describedby={
                error?.fieldAtFault === 'size' ? `${sizeHintId} ${errorId}` : sizeHintId
              }
              onChange={(event) => typed(setSize)(event.target.value)}
            />
            <p className={styles.hint} id={sizeHintId}>
              The top-level folder, such as 45X90.
            </p>
            {error?.fieldAtFault === 'size' && alert}
          </div>

          <div className={styles.field}>
            <label className={styles.label} htmlFor={categoryId}>
              Category
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
              aria-describedby={
                error?.fieldAtFault === 'category' ? `${categoryHintId} ${errorId}` : categoryHintId
              }
              onChange={(event) => typed(setCategory)(event.target.value)}
            />
            {/* AD-18: a Category that cannot be recovered is recorded as
                UNKNOWN and flagged for follow-up, never dropped — so clearing
                this is a supported answer rather than an omission. */}
            <p className={styles.hint} id={categoryHintId}>
              The range or pattern, such as CREMA MARMOL. Cleared, the tile is filed under{' '}
              {UNKNOWN_CATEGORY}.
            </p>
            {error?.fieldAtFault === 'category' && alert}
          </div>

          {/* A region rather than a fieldset with a legend: the group holds
              images and a file input rather than a set of related choices, and
              a heading is what a screen-reader user navigates to. */}
          <section className={styles.field} aria-labelledby={imagesLabelId}>
            <h2 className={styles.subtitle} id={imagesLabelId}>
              Reference images
            </h2>
            <ul className={styles.gallery}>
              {tile.reference_images.map((image, index) => {
                const pending = marked.includes(image.id);
                return (
                  <li
                    className={pending ? `${styles.thumb} ${styles.pending}` : styles.thumb}
                    key={image.id}
                  >
                    {/* Proxied through the authenticated endpoint, never a
                        storage URL (AD-9). Same origin, so the session cookie
                        travels with it and the role is re-checked per request. */}
                    <img
                      alt={`Reference image ${index + 1} of ${tile.code}`}
                      className={styles.image}
                      src={`${API_PREFIX}/admin/tiles/${tile.id}/images/${image.id}`}
                    />
                    {/* FR-19: an image below the texture threshold matches any
                        washed-out photo and can never be reliably retrieved
                        itself. The epic asks for the flag on the tile's own
                        screen rather than buried in a report. Stated in plain
                        words, never as a number. */}
                    {image.featureless && (
                      <p className={styles.flag}>
                        Very little visible texture — scans may not find this tile through it.
                      </p>
                    )}
                    {/* A toggle, and nothing happens when it is pressed: the
                        removal travels with the save, which is confirmed. The
                        word is the signal, not the colour (EXPERIENCE.md's
                        accessibility floor). */}
                    <label className={styles.remove}>
                      <input
                        checked={pending}
                        onChange={() => toggleMarked(image.id)}
                        type="checkbox"
                        aria-label={`Remove reference image ${String(index + 1)} of ${tile.code}`}
                      />
                      {/* The visible word stays bare — it sits beside its own
                          thumbnail, so the position is obvious on screen. The
                          accessible name carries the distinguisher instead:
                          out of the gallery's context these are otherwise
                          three identically named checkboxes, on the one
                          destructive control *inside the form* — Remove tile
                          sits below it and ends the tile instead — and they
                          name the same image the thumbnail above already
                          names. */}
                      Remove
                    </label>
                  </li>
                );
              })}
            </ul>

            <label className={styles.label} htmlFor={imagesId}>
              Add reference images
            </label>
            {/* `accept` is a *hint to the file picker*, never a check: the
                server decides by content and nothing else (AGENTS.md Policy),
                and the real catalogue holds `.tif` alongside `.jpg`. */}
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
              Up to {MAX_IMAGES_PER_REQUEST} at a time, each under{' '}
              {MAX_IMAGE_BYTES / (1024 * 1024)} MB. A tile always keeps at least one reference
              image. Saving can take a minute or two — each new image is indexed before it is
              stored.
            </p>
            {error?.fieldAtFault === 'images' && alert}
          </section>

          {/* A failure that belongs to no field — the request never reached the
              API, the tile has moved, or the server has no image pipeline
              installed. Inserted rather than emptied and refilled: a
              `role="alert"` node appearing in the document is what announces
              it. */}
          {error !== null && error.fieldAtFault === null && alert}

          <div className={styles.actions}>
            {/* The screen's one accent control once a tile is loaded.
                Disabled during a *lookup* as well as during a save: a Find that
                is still in flight will `adopt()` whatever it finds, and a save
                pressed under it would be overwritten by that adoption — with
                both live regions speaking at once on the way. */}
            <button className={styles.submit} type="submit" disabled={submitting || looking}>
              Save
            </button>
            {/* Inline, beside the control that triggered it — never a corner
                toast (EXPERIENCE.md's Save indicator row). The live region is
                in the document at rest so the change of text is what gets
                announced, rather than the arrival of a whole new node. */}
            <span
              className={saved ? `${styles.indicator} ${styles.saved}` : styles.indicator}
              role="status"
            >
              {indicator}
            </span>
          </div>
        </form>
      )}

      {/* FR-16, outside the form and after it. Outside because nothing here
          travels with Save — everything above is the edit, and this ends the
          tile instead; after it because a destructive control placed beside the
          primary one is one slip away from the wrong outcome.

          Not a row-end menu: EXPERIENCE.md puts destructive catalogue actions
          in one on the Catalogue list, and that list is Story 2.5's. Until it
          exists this screen is the only thing that reaches a tile at all. */}
      {tile !== null && (
        <section className={styles.removal} aria-labelledby={removalLabelId}>
          <h2 className={styles.subtitle} id={removalLabelId}>
            Remove this tile
          </h2>
          <p className={styles.hint} id={removalHintId}>
            The tile and everything the catalogue indexed from it are deleted permanently. Scans
            can no longer return it, and this cannot be undone.
          </p>
          {/* Destructive fill and the word together — red is never the only
              signal (EXPERIENCE.md's accessibility floor). Disabled under an
              in-flight lookup as well as an in-flight save: a Find still in
              flight will `adopt()` whatever it finds, and a removal pressed
              under it would name whichever tile was loaded first. */}
          <button
            className={styles.destructive}
            type="button"
            aria-describedby={removalHintId}
            disabled={submitting || looking}
            onClick={() => {
              setSaved(false);
              setRemoved('');
              setError(null);
              setSheet('remove');
            }}
          >
            Remove tile
          </button>
        </section>
      )}

      {sheet === 'refusal' && tile !== null && (
        // The refusal state: **no destructive control is rendered at all**,
        // because there is nothing to press (EXPERIENCE.md:148). Its body is
        // `role="alert"`, so the sentence is announced rather than sitting
        // silently on screen.
        <ConfirmDialog
          body={MUST_KEEP_AN_IMAGE}
          heading={`${tile.code} would be left with no reference image`}
          kind="refusal"
          onClose={() => setSheet('none')}
        />
      )}

      {sheet === 'confirm' && tile !== null && (
        // Names the tile and the consequence, never a bare "Are you sure?"
        // (EXPERIENCE.md:56, :72, :144). Its confirm control carries a word as
        // well as the destructive fill, because red alone is never the signal.
        <ConfirmDialog
          body={
            `${tile.code} keeps ${String(remaining)} reference image${remaining === 1 ? '' : 's'}. ` +
            'A removed image and everything the catalogue indexed from it are deleted ' +
            'permanently, and scans can no longer match this tile through it.'
          }
          busy={submitting}
          confirmLabel="Remove and save"
          heading={`Remove ${String(removing)} reference image${
            removing === 1 ? '' : 's'
          } from ${tile.code}?`}
          kind="confirm"
          onClose={() => setSheet('none')}
          onConfirm={() => void save()}
        />
      )}

      {sheet === 'remove' && tile !== null && (
        // Names the tile and the consequence, never a bare "Are you sure?"
        // (EXPERIENCE.md:56, :72, :144). The consequence is stated as the whole
        // of it — the tile and everything the catalogue indexed from it —
        // because there is no undo behind this one and the sheet is the last
        // place to say so.
        <ConfirmDialog
          body={
            `${tile.code} and everything the catalogue indexed from it are deleted ` +
            'permanently. Scans can no longer return this tile, and this cannot be undone.'
          }
          busy={submitting}
          confirmLabel="Remove tile"
          heading={`Remove ${tile.code}?`}
          kind="confirm"
          onClose={() => setSheet('none')}
          onConfirm={() => void removeTile()}
        />
      )}
    </section>
  );
}
