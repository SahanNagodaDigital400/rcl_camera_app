import { useEffect, useId, useRef, useState } from 'react';
import type { FormEvent, JSX } from 'react';

import {
  ApiRequestError,
  EMAIL_ALREADY_EXISTS,
  INVALID_EMAIL,
  LAST_ADMINISTRATOR,
  MALFORMED_RESPONSE,
  apiRequest,
} from '../api/client';
import styles from './EditUserScreen.module.css';
import { ROLES, isRole, isUser } from '@rocell/schema/user';
import type { Role, User } from '@rocell/schema/user';

/**
 * Edit user — where an Administrator corrects a name, an address or a role (FR-12).
 *
 * Rendered *inside* the shell, in place of the home panel, so it carries no
 * `<main>` of its own: `AppShell` already provides the one main landmark and the
 * focus target the gate moves focus to on a screen swap. It is modelled on
 * `CreateUserScreen` — same form rhythm, same one-alert-in-one-slot treatment,
 * same accent submit beside a navy-outlined Back.
 *
 * **Its own screen, not a mode of `CreateUserScreen`.** EXPERIENCE.md line 34
 * names one surface, "Create/Edit User", because the two carry the same fields —
 * not because they are one component. Create owns a temporary password, a result
 * panel holding a credential nothing in the product can show again, and a
 * `POST`; edit owns a pre-filled form, a per-field diff, a save indicator and a
 * `PATCH`. Folding them together would put every one of those behind a mode flag
 * in the screen whose credential handling is the most delicate in the product.
 *
 * **It sends only the fields that differ.** Two Administrators editing one row
 * at once is not solved here — last write wins, and DW-63 leaves what
 * `updated_at` is *for* undecided, so there is no `If-Match`, no version token
 * and no "someone else changed this" dialog. Sending one field rather than three
 * is the whole of the mitigation: the last write wins over the field that was
 * actually edited instead of over the whole account.
 *
 * **It calls `apiRequest` directly rather than going through `SessionProvider`.**
 * That context is the *caller's own* session, and editing somebody else changes
 * none of it. The one exception is the row coming back: when it is the caller's
 * own, `App` hands it to `adoptUser`, which is what keeps the app bar and the
 * admin door in step after a self-rename or a self-demotion.
 *
 * **The door that opens this screen is a convenience, never the control.** `App`
 * renders the Users list only for an Administrator and falls back to the home
 * panel if the cached role stops being `admin` — but the cached `User` is a
 * render cache and never an authorization decision (AGENTS.md Policy). The
 * server refuses a Staff caller at `PATCH /admin/users/{id}` regardless, through
 * `require_administrator`, which re-reads the role from Postgres on every
 * request (AD-3).
 *
 * Deliberately absent:
 *
 * - **No password field, and no control that sets, reissues or reveals one.**
 *   The endpoint writes three columns and `password_hash` is not among them;
 *   a forgotten password is handled by provisioning a fresh account credential,
 *   which is Create user's job.
 * - **No unlock.** FR-4's lock shows on the Users list, and nothing anywhere in
 *   the product ends one early — no story in Epic 1 owns that (DW-64). A rename
 *   carries the lock with the account rather than clearing it.
 * - **Not on this screen: deactivate, delete, and the confirmation dialog that
 *   guards them.** Since Story 1.11 all three exist — the verbs are row-end
 *   controls on `UserListScreen`, beside the Edit control that opens *this*
 *   screen, and the dialog EXPERIENCE.md describes for them is
 *   `components/ConfirmDialog`. They stay off this screen on purpose: editing
 *   is not destructive and gets no destructive treatment, and a screen that
 *   both renamed an account and deleted it would put the irreversible verb one
 *   mis-click from the routine one. `edit-user.test.tsx` asserts
 *   `queryByRole('dialog')` is null here, which is the assertion that the
 *   dialog did not leak across.
 * - **No audit entry.** Story 1.12 owns the append-only log and is owed one by
 *   the endpoint behind this screen; no private log path is built meanwhile.
 *
 * The rejection text is always the API's own sentence, which names the rule that
 * failed (EXPERIENCE.md:87). Copy follows EXPERIENCE.md's tone rules: short,
 * factual, no exclamation marks.
 */

/** Shown for a failure that arrives as something other than an `ApiRequestError`. */
/**
 * The alert for a rejection that is not an `ApiRequestError`.
 *
 * Every failure `apiRequest` can produce — a refused status, a timeout, a dead
 * network, a body that is not a `User` — arrives wrapped, carrying a sentence
 * written for the person reading it, so this is the fallback for a bug rather
 * than for a reachable state. It exists because the alternative, rendering
 * `String(failure)`, puts a stack-shaped string in front of an Administrator.
 */
const UNEXPECTED = 'The changes could not be saved. Try again.';

/**
 * Refuse an empty field here rather than letting the API answer for it.
 *
 * The form is `noValidate` — the browser's own bubble is unstyled, untestable
 * and disappears on the next keystroke — so these are what `required` would
 * otherwise have done.
 */
const BLANK_NAME = 'Enter the person’s name.';
const BLANK_EMAIL = 'Enter an email address.';

/** What a Save with nothing edited says, inline, instead of sending an empty body. */
const NOTHING_CHANGED = 'Nothing has changed.';

/** The save indicator's two spoken states (DESIGN.md's `save-indicator`). */
const SAVING = 'Saving…';
const SAVED = 'Saved.';

/**
 * What Back says the first time it is pressed with edits outstanding.
 *
 * EXPERIENCE.md line 90: never silently drop an in-progress admin form. This is
 * the first admin form in the product to carry the warning, and DW-81 is where
 * the convention was recorded as owed.
 */
const UNSAVED_CHANGES = 'Your changes have not been saved. Press Back again to discard them.';

/**
 * The server's own bounds, mirrored onto the inputs.
 *
 * **The server's copy is the authority** — `EditUserRequest` bounds both and
 * `api.main` answers `422 validation_error` for anything past them, whatever
 * this file says. These exist only to keep that particular refusal off the
 * screen, because it is the one the Administrator cannot act on: it carries one
 * generic sentence for every malformed body in the product and names no field,
 * so nothing is marked and nothing is focused.
 *
 * They are written down here rather than imported because nothing crosses that
 * boundary at build time; `error-code-parity.test.ts` is what holds each of them
 * to the Python constant it mirrors.
 */
const MAX_NAME_LENGTH = 200;
const MAX_EMAIL_LENGTH = 320;

/** The glossary's own words for the two roles (PRD Glossary, EXPERIENCE.md). */
const ROLE_LABELS: Record<Role, string> = {
  staff: 'Staff',
  admin: 'Administrator',
};

/** Which field a failure is about — and therefore which one is marked and focused. */
type Field = 'name' | 'email' | 'role';

/**
 * What went wrong, and which field is at fault.
 *
 * `fieldAtFault` is not decoration: it drives `aria-invalid` and focus. Marking
 * an input invalid because the network dropped tells a screen-reader user their
 * typing was malformed when it was not — and marking the *wrong* input sends
 * them to correct something that is perfectly fine.
 */
interface FormError {
  message: string;
  fieldAtFault: Field | null;
}

/** The API's code, mapped to the field the Administrator has to fix. */
function fieldFor(failure: unknown): Field | null {
  if (!(failure instanceof ApiRequestError)) return null;
  if (failure.code === INVALID_EMAIL || failure.code === EMAIL_ALREADY_EXISTS) return 'email';
  // The role is what was refused: the other two would have been written had they
  // arrived without it, and the way out of the refusal is to change this control
  // back or to make somebody else an Administrator first.
  if (failure.code === LAST_ADMINISTRATOR) return 'role';
  // `user_not_found` and `administrator_required` land here, deliberately.
  // Nothing on the form is wrong in either case — the row is gone, or the
  // caller was demoted between two requests — so pointing at a field would be a
  // lie. The server's own sentence says what to do instead.
  return null;
}

/**
 * Narrow the response body to the shared `User`, or fail loudly.
 *
 * `isUser` rejects a missing key, a malformed UUID, a non-UTC timestamp — and
 * any extra key, which is how a `password_hash` would announce itself. This body
 * becomes the screen's new baseline for the next diff and, when it is the
 * caller's own row, the session's cached user — so a partially-understood one
 * must not be adopted as either.
 */
function asUser(body: unknown): User {
  if (!isUser(body)) {
    throw new ApiRequestError(
      MALFORMED_RESPONSE,
      'The server returned an unexpected response.',
      200,
    );
  }
  return body;
}

interface EditUserScreenProps {
  user: User;
  onSaved: (updated: User) => void;
  onBack: () => void;
}

export function EditUserScreen({ user, onSaved, onBack }: EditUserScreenProps): JSX.Element {
  const nameId = useId();
  const emailId = useId();
  const roleId = useId();
  const errorId = useId();

  /**
   * The row as the API last reported it, and what every diff is taken against.
   *
   * Not the `user` prop: after a save the server's answer is the truth, and
   * comparing against the row this screen was opened with would send a field
   * again on the next Save that had already landed.
   */
  const [baseline, setBaseline] = useState<User>(user);
  const [name, setName] = useState(user.name);
  const [email, setEmail] = useState(user.email);
  const [role, setRole] = useState<Role>(user.role);
  const [error, setError] = useState<FormError | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [saved, setSaved] = useState(false);
  /**
   * Whether Back has already warned about unsaved edits.
   *
   * One warning, then the next press leaves (EXPERIENCE.md line 90, DW-81).
   * Story 1.11 has since built the product's modal — `components/ConfirmDialog`
   * — and this deliberately still does not use it: that dialog is for a
   * destructive action, and losing an unsaved rename is not one. An inline
   * warning plus a second press is the same guarantee without a modal, and it
   * keeps EXPERIENCE.md line 42's one level of depth for the verb that needs
   * it.
   */
  const [warned, setWarned] = useState(false);
  const nameRef = useRef<HTMLInputElement>(null);
  const emailRef = useRef<HTMLInputElement>(null);
  const roleRef = useRef<HTMLSelectElement>(null);
  /**
   * The field a refusal asked focus to be moved to, until the effect below
   * moves it. `null` when there is nothing to move.
   */
  const pendingFocus = useRef<Field | null>(null);

  /** The body to send: only the fields that differ from the loaded row. */
  function changes(): { name?: string; email?: string; role?: Role } {
    const body: { name?: string; email?: string; role?: Role } = {};
    // Trimmed before comparing, because the API stores the trimmed name: typing
    // a trailing space into a name that is otherwise unchanged is not an edit,
    // and sending it would move `updated_at` for nothing.
    if (name.trim() !== baseline.name) body.name = name;
    // Case-insensitively and space-stripped, because the API folds the address
    // in Postgres: retyping the same address in a different case is the same
    // login, and sending it would spend a write — and, worse, would look like a
    // rename to the counter carry behind it.
    if (email.trim().toLowerCase() !== baseline.email) body.email = email;
    if (role !== baseline.role) body.role = role;
    return body;
  }

  /**
   * Show a refusal, and retire the "Saved." beside it.
   *
   * The focus is *requested* here and performed by the effect below, not called
   * inline. The three fields are disabled while a request is in flight, and a
   * refusal arrives in the same batch that re-enables them — so a `focus()` made
   * here runs against the DOM as it still is, where the element is disabled and
   * takes no focus at all. The screen-reader user is then left wherever they
   * were, told a field is invalid and not taken to it.
   */
  function refuse(message: string, field: Field | null): void {
    setSaved(false);
    setError({ message, fieldAtFault: field });
    pendingFocus.current = field;
  }

  useEffect(() => {
    // After the commit, so the control being focused is the control as it now
    // is. A ref rather than a dependency on `error`: the request is "move focus
    // once", which is an event, and re-running it whenever this effect's inputs
    // happened to change would steal focus back from wherever the user had
    // since moved it.
    const field = pendingFocus.current;
    if (field === null) return;
    pendingFocus.current = null;

    const target = field === 'name' ? nameRef : field === 'email' ? emailRef : roleRef;
    target.current?.focus();
  });

  /**
   * Take what was typed, and retire the "Saved." beside it.
   *
   * "Saved." describes a change that has already landed, and the moment a field
   * is edited it is describing something that is no longer what is on screen.
   * The warning goes with it: the next Back is about these edits, not the ones
   * that were outstanding when it was last pressed.
   */
  function typed<T>(set: (value: T) => void): (value: T) => void {
    return (value) => {
      setSaved(false);
      setWarned(false);
      set(value);
    };
  }

  function handleBack(): void {
    // EXPERIENCE.md line 90: never silently drop an in-progress admin form. The
    // second press leaves, so Back is never a control that refuses to work.
    if (Object.keys(changes()).length > 0 && !warned) {
      setWarned(true);
      setSaved(false);
      setError({ message: UNSAVED_CHANGES, fieldAtFault: null });
      return;
    }
    onBack();
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    if (submitting) return;

    // Trimmed for the *emptiness* test only. The values sent below are
    // deliberately untrimmed: the API strips the name and normalizes the address
    // itself, and doing it twice is two opinions about the stored value.
    if (name.trim() === '') {
      refuse(BLANK_NAME, 'name');
      return;
    }
    if (email.trim() === '') {
      refuse(BLANK_EMAIL, 'email');
      return;
    }

    const body = changes();
    if (Object.keys(body).length === 0) {
      // No request at all. The API refuses an empty body with the generic 422
      // that names no field, so asking it would cost a round trip to be told
      // something this screen already knows.
      refuse(NOTHING_CHANGED, null);
      return;
    }

    setSubmitting(true);
    setError(null);
    setSaved(false);

    try {
      const updated = asUser(await apiRequest(`/admin/users/${user.id}`, { method: 'PATCH', body }));
      // The server's answer becomes the baseline, so a second Save sends only
      // what changed since *this* one. No navigation and no toast: the
      // Administrator stays where they are and the indicator says it landed
      // (EXPERIENCE.md's Save indicator row).
      setBaseline(updated);
      setName(updated.name);
      setEmail(updated.email);
      setRole(updated.role);
      setWarned(false);
      setSaved(true);
      onSaved(updated);
    } catch (failure) {
      // The API's own message, so the screen cannot state a rule the server does
      // not enforce. Nothing typed is cleared: an address already in use is one
      // field to change, and a refused demotion is one control to change back.
      refuse(failure instanceof ApiRequestError ? failure.message : UNEXPECTED, fieldFor(failure));
    } finally {
      setSubmitting(false);
    }
  }

  // One node, rendered directly below whichever field is at fault — and after
  // all three when the failure belongs to none of them. A form with three boxes
  // and one error parked under all of them leaves a screen-reader user on the
  // wrong box hearing a sentence about another. Only one of the four slots below
  // is ever filled, so this screen never renders a second alert.
  const alert =
    error === null ? null : (
      <p className={styles.error} id={errorId} role="alert">
        {error.message}
      </p>
    );

  let indicator = '';
  if (submitting) indicator = SAVING;
  else if (saved) indicator = SAVED;

  return (
    <section className={styles.screen}>
      <h1 className={styles.title}>Edit user</h1>
      {/* Whose account this is, from the row as it was loaded rather than from
          the fields being edited — a line that changed as the name was typed
          would stop answering the question it is here to answer. The screen must
          never be ambiguous about which row is being changed. */}
      <p className={styles.subject}>{baseline.email}</p>

      <form className={styles.form} onSubmit={(event) => void handleSubmit(event)} noValidate>
        <div className={styles.field}>
          <label className={styles.label} htmlFor={nameId}>
            Name
          </label>
          <input
            className={styles.input}
            id={nameId}
            name="name"
            maxLength={MAX_NAME_LENGTH}
            type="text"
            // Somebody else's details, never the Administrator's own: there is
            // nothing here a browser should be offering to fill or to remember.
            autoComplete="off"
            ref={nameRef}
            value={name}
            // Frozen in flight, exactly as Save and Back are. The success path
            // replaces all three fields with the server's row, so anything typed
            // while the request was open would be silently discarded — the
            // Administrator would watch their own edit disappear into a
            // `Saved.` that was about something else.
            disabled={submitting}
            aria-invalid={error?.fieldAtFault === 'name'}
            aria-describedby={error?.fieldAtFault === 'name' ? errorId : undefined}
            onChange={(event) => typed(setName)(event.target.value)}
          />
          {error?.fieldAtFault === 'name' && alert}
        </div>

        <div className={styles.field}>
          <label className={styles.label} htmlFor={emailId}>
            Email
          </label>
          <input
            className={styles.input}
            id={emailId}
            name="email"
            maxLength={MAX_EMAIL_LENGTH}
            type="email"
            autoComplete="off"
            autoCapitalize="none"
            autoCorrect="off"
            spellCheck={false}
            ref={emailRef}
            value={email}
            // Frozen in flight, for the reason the name input above gives.
            disabled={submitting}
            aria-invalid={error?.fieldAtFault === 'email'}
            aria-describedby={error?.fieldAtFault === 'email' ? errorId : undefined}
            onChange={(event) => typed(setEmail)(event.target.value)}
          />
          {error?.fieldAtFault === 'email' && alert}
        </div>

        <div className={styles.field}>
          <label className={styles.label} htmlFor={roleId}>
            Role
          </label>
          {/* Built by iterating `ROLES`, the shared contract's own list, so a
              role the product does not have cannot be offered and a role it does
              have cannot be forgotten. Pre-filled from the row rather than
              defaulted: this is an edit, and a control that opened on Staff
              would demote an Administrator for anybody who saved a rename. */}
          <select
            className={styles.select}
            id={roleId}
            name="role"
            ref={roleRef}
            value={role}
            // Frozen in flight, for the reason the name input above gives.
            disabled={submitting}
            aria-invalid={error?.fieldAtFault === 'role'}
            aria-describedby={error?.fieldAtFault === 'role' ? errorId : undefined}
            onChange={(event) => {
              // Narrowed through the shared contract's own guard rather than
              // cast: the `<option>` list is built from `ROLES`, so a value that
              // is not a `Role` cannot come out of this control — and asserting
              // that with `as` would make it true by instruction instead.
              const chosen = event.target.value;
              if (isRole(chosen)) typed(setRole)(chosen);
            }}
          >
            {ROLES.map((value) => (
              <option key={value} value={value}>
                {ROLE_LABELS[value]}
              </option>
            ))}
          </select>
          {error?.fieldAtFault === 'role' && alert}
        </div>

        {/* A failure that belongs to no field — the row is gone, the request
            never reached the API, or Back is warning about unsaved edits.
            Inserted rather than emptied and refilled: a `role="alert"` node
            appearing in the document is what announces it. */}
        {error !== null && error.fieldAtFault === null && alert}

        <div className={styles.actions}>
          {/* The screen's one accent control (DESIGN.md: exactly one per
              screen). Back is the secondary, navy-outlined one. */}
          <button className={styles.submit} type="submit" disabled={submitting}>
            Save changes
          </button>
          {/* Disabled in flight, exactly as the submit is, for the reason
              `CreateUserScreen`'s is: a click would unmount this screen while
              the request is open, and the save would land with nobody to see
              whether it had. */}
          <button className={styles.back} type="button" onClick={handleBack} disabled={submitting}>
            Back
          </button>
          {/* Inline, beside the control that triggered it — never a corner toast
              (EXPERIENCE.md's Save indicator row). The live region is in the
              document at rest so the change of text is what gets announced. */}
          <span
            className={saved ? `${styles.indicator} ${styles.saved}` : styles.indicator}
            role="status"
          >
            {indicator}
          </span>
        </div>
      </form>
    </section>
  );
}
