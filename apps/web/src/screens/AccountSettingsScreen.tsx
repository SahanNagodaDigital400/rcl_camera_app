import { useId, useRef, useState } from 'react';
import type { FormEvent, JSX } from 'react';

import { ApiRequestError, INVALID_CURRENT_PASSWORD, WEAK_PASSWORD } from '../api/client';
import { useSession } from '../auth/SessionProvider';
import styles from './AccountSettingsScreen.module.css';

/**
 * Account Settings — where a signed-in user changes their own password (FR-5).
 *
 * Rendered *inside* the shell, in place of the home panel, so it carries no
 * `<main>` of its own: `AppShell` already provides the one main landmark and the
 * focus target the gate moves focus to on a screen swap. The app bar above it
 * keeps the Account and Sign out controls, and this screen adds a Back control
 * of its own, so it is reachable and escapable — which is exactly why
 * `changeOwnPassword` needs none of `changePassword`'s rescue branches.
 *
 * Two fields, not one, and that is the whole difference from
 * `ForcedPasswordChangeScreen` (DESIGN.md:219 specifies a single-field form
 * *there*). This screen proves the current password before it changes anything:
 * a borrowed unlocked phone must not be a permanent takeover of the account.
 *
 * Deliberately absent, and each for the same reason the forced-change screen
 * gives:
 *
 * - **No confirm-password field.** No mismatch rule is stated anywhere, and a
 *   second box with no rule behind it is another thing to type for no
 *   enforcement.
 * - **No reveal toggle and no strength meter.** Neither is specified, and a
 *   meter would state a policy the server does not enforce.
 * - **No recovery affordance of any kind.** FR-5: a user who has *forgotten*
 *   their password cannot get here at all — they are signed out — and their way
 *   back is an Administrator, not a link. Nothing on this screen pretends
 *   otherwise.
 *
 * The rejection text is always the API's own sentence, which is what names the
 * rule that failed (EXPERIENCE.md:87). This screen never composes its own
 * version of a rule it does not own.
 *
 * Copy follows EXPERIENCE.md's tone rules: short, factual, no exclamation marks.
 */

/** Shown for a failure that arrives as something other than an `ApiRequestError`. */
const UNEXPECTED = 'The password could not be changed. Try again.';

/**
 * Refuse an empty field here rather than letting the API answer for it.
 *
 * The form is `noValidate` — the browser's own bubble is unstyled, untestable
 * and disappears on the next keystroke — so these are what `required` would
 * otherwise have done. Without them a blank submit spends an Argon2id verify to
 * be told a length rule, which is true and beside the point for someone who
 * simply has not typed yet.
 */
const BLANK_CURRENT = 'Enter your current password.';
const BLANK_NEW = 'Enter a new password.';

/** The save indicator's two spoken states (DESIGN.md's `save-indicator`). */
const SAVING = 'Saving…';
const SAVED = 'Saved.';

/** Which field a failure is about — and therefore which one is marked and focused. */
type Field = 'current' | 'new';

/**
 * What went wrong, and which field is at fault.
 *
 * `fieldAtFault` is not decoration: it drives `aria-invalid` and focus. Marking
 * an input invalid because the network dropped tells a screen-reader user their
 * typing was malformed when it was not — and marking the *wrong* input sends
 * them to correct something that is perfectly fine. `invalid_current_password`
 * is about the current field, `weak_password` about the new one, and anything
 * else about neither.
 */
interface FormError {
  message: string;
  fieldAtFault: Field | null;
}

/** The API's code, mapped to the field the user has to fix. */
function fieldFor(failure: unknown): Field | null {
  if (!(failure instanceof ApiRequestError)) return null;
  if (failure.code === INVALID_CURRENT_PASSWORD) return 'current';
  if (failure.code === WEAK_PASSWORD) return 'new';
  return null;
}

export function AccountSettingsScreen({ onBack }: { onBack: () => void }): JSX.Element {
  const { user, changeOwnPassword } = useSession();
  const currentId = useId();
  const newId = useId();
  const errorId = useId();

  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [error, setError] = useState<FormError | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [saved, setSaved] = useState(false);
  const currentRef = useRef<HTMLInputElement>(null);
  const newRef = useRef<HTMLInputElement>(null);

  /**
   * Take what was typed, and retire the confirmation beside it.
   *
   * "Saved." describes the change that has already landed, and the moment a
   * field is edited it is describing something that is no longer on screen — a
   * confirmation sitting beside two freshly filled boxes reads as though *they*
   * had been saved. `handleSubmit` clears it too, for the same reason one step
   * later; this is the earlier half of the same argument.
   */
  function typed(set: (value: string) => void): (value: string) => void {
    return (value) => {
      setSaved(false);
      set(value);
    };
  }

  function focus(field: Field): void {
    const target = field === 'current' ? currentRef : newRef;
    target.current?.focus();
  }

  /**
   * Show a refusal, and retire the confirmation beside it.
   *
   * Every refusal reaches this function, including the two blank-field guards
   * below that return before a request is ever made — and clearing "Saved."
   * here rather than at the point a request starts is what makes that true. A
   * successful change leaves both boxes empty, so the very next press *is* a
   * blank refusal: "Saved." left standing beside "Enter your current password."
   * reads as though the empty form had just been saved.
   */
  function refuse(message: string, field: Field | null): void {
    setSaved(false);
    setError({ message, fieldAtFault: field });
    if (field !== null) focus(field);
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    if (submitting) return;

    // Trimmed for the *emptiness* test only. The values sent below are
    // deliberately untrimmed: leading or trailing whitespace is part of a
    // password, and quietly removing it here would send a credential different
    // from the one the user typed — and different again from the one the login
    // form would later send.
    if (currentPassword.trim() === '') {
      refuse(BLANK_CURRENT, 'current');
      return;
    }
    if (newPassword.trim() === '') {
      refuse(BLANK_NEW, 'new');
      return;
    }

    setSubmitting(true);
    setError(null);
    // The previous "Saved." goes the moment a new attempt starts: left up, it
    // would sit beside a rejection and read as though something had landed.
    // `refuse` and `typed` clear it on the other two ways out; this is the
    // third, and the only one that reaches the network.
    setSaved(false);

    try {
      await changeOwnPassword(currentPassword, newPassword);
      // Both fields clear, and the screen stays exactly where it is — no
      // navigation, no toast, no success screen to click through. The indicator
      // beside the button is the whole of the confirmation (DESIGN.md's
      // `save-indicator`, EXPERIENCE.md's Save indicator row).
      setCurrentPassword('');
      setNewPassword('');
      setSaved(true);
    } catch (failure) {
      // The API's own message, so the screen cannot state a rule the server does
      // not enforce and cannot fall back to a generic "invalid password", which
      // is the one thing EXPERIENCE.md:87 forbids.
      //
      // Neither field is cleared: the rule that failed may be fixable by adding
      // characters, and a wrong current password costs the user only the one box
      // they have to retype.
      refuse(
        failure instanceof ApiRequestError ? failure.message : UNEXPECTED,
        fieldFor(failure),
      );
    } finally {
      setSubmitting(false);
    }
  }

  // One expression rather than a nested ternary in the markup: the indicator has
  // three states and the empty one is the default, which is easier to read here
  // than inline.
  let indicator = '';
  if (submitting) indicator = SAVING;
  else if (saved) indicator = SAVED;

  // One node, rendered directly below whichever field is at fault — and after
  // both of them when the failure belongs to neither (a network drop). A form
  // with two boxes and one error parked under both leaves a screen-reader user
  // on the second box hearing a sentence about the first, and leaves a sighted
  // user scanning two fields to work out which one to fix. Only one of the three
  // slots below is ever filled, so *this screen* never renders a second alert.
  // It is not the only alert on the surface: `App` renders a failed sign-out as
  // a sibling above this section, because the app bar that raised it is still
  // here. That one belongs to a different action and is announced when it
  // happens, so the two can be live together without either describing the
  // other — but `getByRole('alert')` on the composed surface can see both.
  const alert =
    error === null ? null : (
      <p className={styles.error} id={errorId} role="alert">
        {error.message}
      </p>
    );

  return (
    <section className={styles.screen}>
      <h1 className={styles.title}>Account</h1>

      {/* Read-only, and read from the session context rather than from a form:
          FR-11 puts editing a name or an address with an Administrator, which
          since Story 1.10 is Users -> Edit; this screen changes exactly one
          thing. `user` cannot be null
          here — `App` renders this branch only when it is not — and the fallback
          keeps TypeScript's narrowing honest without inventing a placeholder. */}
      <dl className={styles.identity}>
        <dt className={styles.term}>Name</dt>
        <dd className={styles.value}>{user?.name ?? ''}</dd>
        <dt className={styles.term}>Email</dt>
        <dd className={styles.value}>{user?.email ?? ''}</dd>
      </dl>

      <form className={styles.form} onSubmit={(event) => void handleSubmit(event)} noValidate>
        <h2 className={styles.subtitle}>Change password</h2>

        <div className={styles.field}>
          <label className={styles.label} htmlFor={currentId}>
            Current password
          </label>
          <input
            className={styles.input}
            id={currentId}
            name="current-password"
            type="password"
            autoComplete="current-password"
            autoCapitalize="none"
            autoCorrect="off"
            spellCheck={false}
            ref={currentRef}
            value={currentPassword}
            aria-invalid={error?.fieldAtFault === 'current'}
            // Only the field the failure is actually about. Pointed at from
            // both, the new-password box would describe itself with a sentence
            // about the current one.
            aria-describedby={error?.fieldAtFault === 'current' ? errorId : undefined}
            onChange={(event) => typed(setCurrentPassword)(event.target.value)}
          />
          {error?.fieldAtFault === 'current' && alert}
        </div>

        <div className={styles.field}>
          <label className={styles.label} htmlFor={newId}>
            New password
          </label>
          <input
            className={styles.input}
            id={newId}
            name="new-password"
            type="password"
            autoComplete="new-password"
            autoCapitalize="none"
            autoCorrect="off"
            spellCheck={false}
            ref={newRef}
            value={newPassword}
            aria-invalid={error?.fieldAtFault === 'new'}
            aria-describedby={error?.fieldAtFault === 'new' ? errorId : undefined}
            onChange={(event) => typed(setNewPassword)(event.target.value)}
          />
          {error?.fieldAtFault === 'new' && alert}
        </div>

        {/* A failure that belongs to neither field — the request never reached
            the API, or it came back with a code this screen does not recognise.
            Inserted rather than emptied and refilled: a `role="alert"` node
            appearing in the document is what announces it. */}
        {error !== null && error.fieldAtFault === null && alert}

        <div className={styles.actions}>
          {/* The screen's one accent control (DESIGN.md: exactly one per
              screen). Back is the secondary, navy-outlined one. */}
          <button className={styles.submit} type="submit" disabled={submitting}>
            Change password
          </button>
          {/* Disabled in flight, exactly as the submit is. Leaving it live lets a
              click unmount this screen while the request is open: the change
              still lands or still fails, and the user sees neither — no "Saved.",
              no rejection, and no way to tell which happened short of trying the
              old password. */}
          <button className={styles.back} type="button" onClick={onBack} disabled={submitting}>
            Back
          </button>
          {/* Inline, beside the control that triggered it — never a corner
              toast (EXPERIENCE.md's Save indicator row). The live region is in
              the document at rest so the change of text is what gets announced,
              rather than the arrival of a whole new node. */}
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
