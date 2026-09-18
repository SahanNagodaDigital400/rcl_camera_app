import { useId, useRef, useState } from 'react';
import type { FormEvent, JSX } from 'react';

import {
  ApiRequestError,
  EMAIL_ALREADY_EXISTS,
  INVALID_EMAIL,
  MALFORMED_RESPONSE,
  WEAK_PASSWORD,
  apiRequest,
} from '../api/client';
import styles from './CreateUserScreen.module.css';
import { ROLES, isRole, isUser } from '@rocell/schema/user';
import type { Role, User } from '@rocell/schema/user';

/**
 * Create user — where an Administrator provisions somebody else's login (FR-11).
 *
 * Rendered *inside* the shell, in place of the home panel, so it carries no
 * `<main>` of its own: `AppShell` already provides the one main landmark and the
 * focus target the gate moves focus to on a screen swap. It is modelled on
 * `AccountSettingsScreen` — same form rhythm, same one-alert-in-one-slot
 * treatment, same accent submit beside a navy-outlined Back.
 *
 * **It calls `apiRequest` directly rather than going through `SessionProvider`.**
 * That context is the *caller's own* session: its status, its cached user, and
 * the three mutations that change it. Provisioning somebody else changes none of
 * those, and routing it through the context would mean every admin mutation from
 * Story 1.10 on lands there too.
 *
 * **It is opened from the User List's "+ Add user"** (EXPERIENCE.md line 34), and
 * `onBack` returns there rather than to the home panel: the list is where the
 * screen was opened from and where the new row belongs. `UserListScreen` refetches
 * on mount, so the user provisioned a moment ago is on the list that comes back.
 *
 * **The role-conditional entry that opens that list is a convenience, never
 * the control.** `App` renders it only for an Administrator and falls back to the
 * home panel if the cached role stops being `admin` — but the cached `User` is a
 * render cache and never an authorization decision (AGENTS.md Policy). The
 * server refuses a Staff caller at `POST /admin/users` regardless, through
 * `require_administrator`, which re-reads the role from Postgres on every request
 * (AD-3).
 *
 * Deliberately absent:
 *
 * - **No control that offers to send the credential.** AGENTS.md Policy and
 *   FR-11: this app sends no mail, ever, and an Administrator hands the
 *   credential over themselves. The result panel says so in as many words.
 * - **No generated password, no strength meter, no reveal toggle, no confirm
 *   field.** The acceptance clause has the Administrator submit the temporary
 *   password; none of the rest is specified, and each would be a rule the server
 *   does not enforce.
 * - **No list, and no editing.** Story 1.9's `UserListScreen` reads the
 *   collection this screen writes to, and it is one surface away — Back. Stories
 *   1.10 and 1.11 own editing and deactivating; nothing here does either, and
 *   nothing here reads a row.
 *
 * The rejection text is always the API's own sentence, which names the rule that
 * failed (EXPERIENCE.md:87). Copy follows EXPERIENCE.md's tone rules: short,
 * factual, no exclamation marks.
 */

/** Shown for a failure that arrives as something other than an `ApiRequestError`. */
const UNEXPECTED = 'The user could not be added. Try again.';

/**
 * Refuse an empty field here rather than letting the API answer for it.
 *
 * The form is `noValidate` — the browser's own bubble is unstyled, untestable
 * and disappears on the next keystroke — so these are what `required` would
 * otherwise have done. Without them a blank submit spends an Argon2id hash to be
 * told a length rule, which is true and beside the point for someone who simply
 * has not typed yet.
 */
const BLANK_NAME = 'Enter the person’s name.';
const BLANK_EMAIL = 'Enter an email address.';
const BLANK_PASSWORD = 'Enter a temporary password.';

/** The in-flight indicator. One state, because success is the panel below it. */
const CREATING = 'Creating…';

/**
 * The server's own bounds, mirrored onto the inputs.
 *
 * **The server's copy is the authority** — `CreateUserRequest` bounds all three
 * and `api.main` answers `422 validation_error` for anything past them, whatever
 * this file says. These exist only to keep that particular refusal off the
 * screen, because it is the one the Administrator cannot act on: it carries one
 * generic sentence for every malformed body in the product and names no field,
 * so nothing is marked and nothing is focused — exactly the outcome
 * `invalid_email` was given a code of its own to avoid, reintroduced on the
 * fields either side of it. A `maxLength` stops the over-long value being typed
 * at all, which is a better answer than explaining it afterwards.
 *
 * They are written down here rather than imported because nothing crosses that
 * boundary at build time; if one drifts, the server still refuses correctly and
 * what is lost is only this convenience.
 */
const MAX_NAME_LENGTH = 200;
const MAX_EMAIL_LENGTH = 320;
const MAX_TEMPORARY_PASSWORD_LENGTH = 4096;

/** The glossary's own words for the two roles (PRD Glossary, EXPERIENCE.md). */
const ROLE_LABELS: Record<Role, string> = {
  staff: 'Staff',
  admin: 'Administrator',
};

/** Which field a failure is about — and therefore which one is marked and focused. */
type Field = 'name' | 'email' | 'password';

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
  if (failure.code === WEAK_PASSWORD) return 'password';
  // `administrator_required` lands here, deliberately: nothing the Administrator
  // typed is at fault, and the screen renders the server's sentence like any
  // other failure. It is also a race they cannot have caused — a demotion
  // between two requests — so pointing at a field would be a lie.
  return null;
}

/** The provisioned user, as the result panel renders them. */
interface Provisioned {
  user: User;
  /** The temporary password exactly as it was typed — never re-read from the API. */
  temporaryPassword: string;
}

/**
 * Narrow the response body to the shared `User`, or fail loudly.
 *
 * `isUser` rejects a missing key, a malformed UUID, a non-UTC timestamp — and
 * any extra key, which is how a `password_hash` would announce itself. The
 * result panel reads `temp_credential_expires_at` off this body, so rendering a
 * partially-understood one would put a wrong deadline in front of somebody about
 * to write it on a note.
 */
function asUser(body: unknown): User {
  if (!isUser(body)) {
    throw new ApiRequestError(
      MALFORMED_RESPONSE,
      'The server returned an unexpected response.',
      201,
    );
  }
  return body;
}

export function CreateUserScreen({ onBack }: { onBack: () => void }): JSX.Element {
  const nameId = useId();
  const emailId = useId();
  const roleId = useId();
  const passwordId = useId();
  const errorId = useId();

  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [role, setRole] = useState<Role>('staff');
  const [temporaryPassword, setTemporaryPassword] = useState('');
  const [error, setError] = useState<FormError | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [provisioned, setProvisioned] = useState<Provisioned | null>(null);
  const nameRef = useRef<HTMLInputElement>(null);
  const emailRef = useRef<HTMLInputElement>(null);
  const passwordRef = useRef<HTMLInputElement>(null);

  /**
   * Take what was typed, and retire the result panel beside it.
   *
   * The panel describes a user who has already been added, and the moment a
   * field is edited it is describing something that is no longer on screen — a
   * credential sitting beside a half-filled form reads as though *it* belonged
   * to what is being typed, which is exactly the transcription error the panel
   * exists to prevent.
   */
  function typed<T>(set: (value: T) => void): (value: T) => void {
    return (value) => {
      setProvisioned(null);
      set(value);
    };
  }

  function focus(field: Field): void {
    const target = field === 'name' ? nameRef : field === 'email' ? emailRef : passwordRef;
    target.current?.focus();
  }

  /**
   * Show a refusal, and retire the result panel beside it.
   *
   * `retireResult` is false for the blank-field refusals below, and that is not
   * a detail. After a success the form is empty and the panel holds a
   * credential nothing in the product can show again (DW-75, DW-81) — so a
   * stray Enter or a second click on Create user, which types nothing and
   * changes nothing, must not be what destroys it. Every other refusal follows
   * a submitted body, by which point something *was* typed and the panel is
   * already describing a user who is no longer on screen.
   */
  function refuse(message: string, field: Field | null, retireResult = true): void {
    if (retireResult) setProvisioned(null);
    setError({ message, fieldAtFault: field });
    if (field !== null) focus(field);
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    if (submitting) return;

    // Trimmed for the *emptiness* test only. The values sent below are
    // deliberately untrimmed: the API normalizes the address and the name
    // itself, and trailing whitespace is part of a password — quietly removing
    // it here would hand over a credential different from the one that was
    // typed, and different again from the one the login form would later send.
    if (name.trim() === '') {
      refuse(BLANK_NAME, 'name', false);
      return;
    }
    if (email.trim() === '') {
      refuse(BLANK_EMAIL, 'email', false);
      return;
    }
    if (temporaryPassword.trim() === '') {
      refuse(BLANK_PASSWORD, 'password', false);
      return;
    }

    setSubmitting(true);
    setError(null);
    setProvisioned(null);

    try {
      const body = await apiRequest('/admin/users', {
        method: 'POST',
        body: { name, email, role, temporary_password: temporaryPassword },
      });
      // The form clears and the panel takes its place. No navigation and no
      // toast: the Administrator has a credential to transcribe before they go
      // anywhere, and a surface that moved out from under them would take it
      // with it.
      setProvisioned({ user: asUser(body), temporaryPassword });
      setName('');
      setEmail('');
      setRole('staff');
      setTemporaryPassword('');
    } catch (failure) {
      // The API's own message, so the screen cannot state a rule the server does
      // not enforce. Nothing typed is cleared: an address already in use is one
      // field to change, and a refused password is fixable by adding characters.
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

  return (
    <section className={styles.screen}>
      <h1 className={styles.title}>Create user</h1>

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
              have cannot be forgotten. Defaults to Staff: it is the commoner
              case by a wide margin, and the safer one to land on by accident. */}
          <select
            className={styles.select}
            id={roleId}
            name="role"
            value={role}
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
        </div>

        <div className={styles.field}>
          <label className={styles.label} htmlFor={passwordId}>
            Temporary password
          </label>
          {/* `type="text"`, deliberately. This is not the Administrator's own
              secret: it is a value they must transcribe verbatim onto a note or
              read aloud, and masking it makes a typing error invisible until the
              new user fails to sign in and comes back. Nothing is being kept
              from the person at the screen — they are typing it. It is not a
              one-use code either: inside its 72 hours it signs in as many times
              as it is tried, and every time it lands on the forced-change
              screen and nothing else. Claiming the account is what retires it.

              `autoComplete="off"` keeps a password manager from offering to
              store somebody else's credential as the Administrator's own, and
              `spellCheck={false}` keeps a random string from being underlined
              and autocorrected. */}
          <input
            className={styles.input}
            id={passwordId}
            name="temporary-password"
            maxLength={MAX_TEMPORARY_PASSWORD_LENGTH}
            type="text"
            autoComplete="off"
            autoCapitalize="none"
            autoCorrect="off"
            spellCheck={false}
            ref={passwordRef}
            value={temporaryPassword}
            aria-invalid={error?.fieldAtFault === 'password'}
            aria-describedby={error?.fieldAtFault === 'password' ? errorId : undefined}
            onChange={(event) => typed(setTemporaryPassword)(event.target.value)}
          />
          {error?.fieldAtFault === 'password' && alert}
        </div>

        {/* A failure that belongs to no field — the request never reached the
            API, or it came back with a code this screen does not recognise.
            Inserted rather than emptied and refilled: a `role="alert"` node
            appearing in the document is what announces it. */}
        {error !== null && error.fieldAtFault === null && alert}

        <div className={styles.actions}>
          {/* The screen's one accent control (DESIGN.md: exactly one per
              screen). Back is the secondary, navy-outlined one. */}
          <button className={styles.submit} type="submit" disabled={submitting}>
            Create user
          </button>
          {/* Disabled in flight, exactly as the submit is. Leaving it live lets a
              click unmount this screen while the request is open: the user is
              still added and the Administrator never sees the credential, which
              cannot be recovered from anywhere. */}
          <button className={styles.back} type="button" onClick={onBack} disabled={submitting}>
            Back
          </button>
          {/* Inline, beside the control that triggered it — never a corner toast
              (EXPERIENCE.md's Save indicator row). The live region is in the
              document at rest so the change of text is what gets announced. */}
          <span className={styles.indicator} role="status">
            {submitting ? CREATING : ''}
          </span>
        </div>
      </form>

      {provisioned !== null && (
        // The whole point of the screen. `role="status"` rather than `alert`:
        // this is the outcome the Administrator asked for, not an interruption.
        <div className={styles.result} role="status">
          <h2 className={styles.subtitle}>User added</h2>
          <dl className={styles.summary}>
            <dt className={styles.term}>Name</dt>
            <dd className={styles.value}>{provisioned.user.name}</dd>
            <dt className={styles.term}>Email</dt>
            <dd className={styles.value}>{provisioned.user.email}</dd>
            <dt className={styles.term}>Role</dt>
            <dd className={styles.value}>{ROLE_LABELS[provisioned.user.role]}</dd>
            <dt className={styles.term}>Temporary password</dt>
            {/* Shown as typed, from this screen's own state rather than from the
                response — the API never returns it, and never should. */}
            <dd className={styles.credential}>{provisioned.temporaryPassword}</dd>
            <dt className={styles.term}>Expires</dt>
            <dd className={styles.value}>{expiry(provisioned.user)}</dd>
          </dl>
          <p className={styles.note}>
            This app sends no mail. Give the temporary password to {provisioned.user.name}{' '}
            yourself. They must change it the first time they sign in, and it stops working after
            the deadline above.
          </p>
        </div>
      )}
    </section>
  );
}

/**
 * The credential's deadline, in the reader's own locale.
 *
 * Rendered from the response rather than computed here: the deadline is set by
 * Postgres's clock, and a front end that added 72 hours to its own would show a
 * time the server does not honour on any device whose clock had drifted.
 *
 * Null is not reachable for a row this endpoint wrote — `_INSERT_USER` sets the
 * flag and the deadline in one statement — but the contract allows it, and a
 * blank where a deadline should be is better than the word "null" on a note.
 */
function expiry(user: User): string {
  const value = user.temp_credential_expires_at;
  if (value === null) return '';
  // The zone is named, not implied. This is the one value in the product whose
  // whole point is a hard deadline set by a server somewhere else, and it is
  // read off the screen onto a note that may be handed over hours later in a
  // different room — a bare wall-clock time there is a deadline nobody can
  // check. `toLocaleString` already renders in the reader's own zone; this says
  // which one that was.
  return new Date(value).toLocaleString(undefined, { timeZoneName: 'short' });
}
