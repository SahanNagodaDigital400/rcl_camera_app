import { useId, useRef, useState } from 'react';
import type { FormEvent, JSX } from 'react';

import { ApiRequestError, WEAK_PASSWORD } from '../api/client';
import { useSession } from '../auth/SessionProvider';
import { MAIN_REGION_ID } from '../components/AppShell';
import styles from './ForcedPasswordChangeScreen.module.css';

/**
 * The forced password change. The only thing on screen until it is done.
 *
 * Deliberately absent, and each for a reason:
 *
 * - **No app bar, no nav, no sign-out control.** DESIGN.md:219 — "No navigation
 *   chrome around it — it's the only thing on screen until it's done." With no
 *   router, `App` rendering this instead of the shell *is* the navigation trap:
 *   there is nothing to intercept, because there is nowhere to go.
 * - **No dismissal.** EXPERIENCE.md line 65: no way to skip it. The server
 *   agrees — every route that serves real data answers
 *   `403 password_change_required` until the change lands — so hiding the shell
 *   here is a convenience, not the control.
 * - **No confirm-password field.** DESIGN.md:219 specifies a single-field form,
 *   and no mismatch rule is stated anywhere; a second box with no rule behind it
 *   is another thing to type for no enforcement.
 * - **No success screen.** EXPERIENCE.md line 88: the transition is immediate.
 *   The shell replaces this screen the moment the session context reports the
 *   cleared flag.
 * - **No reveal toggle and no strength meter.** Neither is specified, and a
 *   meter would state a policy the server does not enforce.
 *
 * The rejection text is the API's own sentence, which is what names the rule
 * that failed — length, or reuse of the temporary password (EXPERIENCE.md:87).
 * This screen never composes its own version of a rule it does not own.
 *
 * Copy follows EXPERIENCE.md's tone rules: short, factual, no exclamation
 * marks.
 */

/** Shown for a failure that arrives as something other than an `ApiRequestError`. */
const UNEXPECTED = 'The password could not be set. Try again.';

/**
 * Refuse an empty field here rather than letting the API answer for it.
 *
 * The form is `noValidate` — the browser's own bubble is unstyled, untestable
 * and disappears on the next keystroke — so this is what `required` would
 * otherwise have done. Without it a blank submit reaches the API and comes back
 * naming the length rule, which is true and beside the point for someone who
 * simply has not typed yet.
 */
const BLANK = 'Enter a new password.';

/**
 * What went wrong, and whether the field itself is at fault.
 *
 * `fieldAtFault` is not decoration: it drives `aria-invalid`, and marking the
 * input invalid because the network dropped tells a screen-reader user their
 * typing was malformed when it was not. Only a password the server actually
 * refused — or one this screen refused before sending — is the field's fault.
 * `LoginScreen` splits the same two cases for the same reason.
 */
interface FormError {
  message: string;
  fieldAtFault: boolean;
}

export function ForcedPasswordChangeScreen(): JSX.Element {
  const { changePassword } = useSession();
  const passwordId = useId();
  const errorId = useId();

  const [password, setPassword] = useState('');
  const [error, setError] = useState<FormError | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const passwordRef = useRef<HTMLInputElement>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    if (submitting) return;

    // Trimmed for the *emptiness* test only. A password of spaces is a user who
    // has not typed one, and the API would answer it by naming the length rule.
    // The value sent below is deliberately untrimmed: leading or trailing
    // whitespace is part of a password, and quietly removing it here would set
    // a credential different from the one the user typed — and different again
    // from the one the login form would later send.
    if (password.trim() === '') {
      setError({ message: BLANK, fieldAtFault: true });
      passwordRef.current?.focus();
      return;
    }

    setSubmitting(true);
    setError(null);

    try {
      await changePassword(password);
      // No navigation and no success state: the shell replaces this screen as
      // soon as the session context reports the cleared flag.
    } catch (failure) {
      // The API's own message, so the screen cannot state a rule the server
      // does not enforce — and cannot fall back to a generic "invalid
      // password", which is the one thing EXPERIENCE.md:87 forbids.
      //
      // The *code* is what decides whether the field is at fault: a refused
      // password is the user's to fix, a timeout or an unreachable server is
      // not, and marking the input invalid for the latter would be a lie told
      // to assistive technology.
      const refused = failure instanceof ApiRequestError && failure.code === WEAK_PASSWORD;
      setError({
        message: failure instanceof ApiRequestError ? failure.message : UNEXPECTED,
        fieldAtFault: refused,
      });
      // Focus stays in the form, on the field to retype. What was typed is
      // kept: the rule that failed may be fixable by adding characters, and
      // clearing it would make a too-short password cost the whole passphrase.
      passwordRef.current?.focus();
    } finally {
      setSubmitting(false);
    }
  }

  return (
    // The same id and focus target the shell's main region carries, so the gate
    // can move focus here on the swap between screens without knowing which one
    // it landed on.
    <main className={styles.screen} id={MAIN_REGION_ID} tabIndex={-1}>
      <div className={styles.panel}>
        <h1 className={styles.title}>Set your password</h1>
        <p className={styles.lede}>
          Your account is on a temporary password an Administrator issued. Set your own password
          to continue.
        </p>

        <form className={styles.form} onSubmit={(event) => void handleSubmit(event)} noValidate>
          <div className={styles.field}>
            <label className={styles.label} htmlFor={passwordId}>
              New password
            </label>
            <input
              className={styles.input}
              id={passwordId}
              name="new-password"
              type="password"
              autoComplete="new-password"
              autoCapitalize="none"
              autoCorrect="off"
              spellCheck={false}
              ref={passwordRef}
              value={password}
              aria-invalid={error?.fieldAtFault ?? false}
              aria-describedby={error === null ? undefined : errorId}
              onChange={(event) => setPassword(event.target.value)}
            />
          </div>

          {/* Inserted rather than emptied and refilled: a `role="alert"` node
              appearing in the document is what announces it. */}
          {error !== null && (
            <p className={styles.error} id={errorId} role="alert">
              {error.message}
            </p>
          )}

          <button className={styles.submit} type="submit" disabled={submitting}>
            {submitting ? 'Setting password…' : 'Set password'}
          </button>
        </form>
      </div>
    </main>
  );
}
