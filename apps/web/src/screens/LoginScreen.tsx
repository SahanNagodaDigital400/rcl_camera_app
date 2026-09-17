import { useId, useRef, useState } from 'react';
import type { FormEvent, JSX } from 'react';

import { ACCOUNT_LOCKED, ApiRequestError, UNAUTHORIZED } from '../api/client';
import { useSession } from '../auth/SessionProvider';
import { MAIN_REGION_ID } from '../components/AppShell';
import styles from './LoginScreen.module.css';

/**
 * The sign-in screen. The only unauthenticated surface in the product.
 *
 * Deliberately absent, and each for a reason:
 *
 * - **No app bar and no nav.** The bar is present on authenticated screens only
 *   (DESIGN.md), and nav is role-conditional, so neither can exist before a
 *   role does.
 * - **No "forgot password" link.** A reset goes through an Administrator
 *   (EXPERIENCE.md); a link here would promise a flow the product does not have.
 * - **No self-provisioning.** FR-1: accounts are issued by an Administrator,
 *   and nothing in the product mints one. A guard test asserts that absence
 *   across the whole tree — over the API's route table and over this source.
 *
 * The copy is written to EXPERIENCE.md's tone rules — short, factual, no
 * exclamation marks — and the rejection names neither the field that was wrong
 * nor whether the account exists. The API already refuses to say; repeating
 * its message verbatim is what keeps the screen from saying more than the
 * server did.
 */

/** Shown for a failure that arrives as something other than an `ApiRequestError`. */
const UNEXPECTED = 'Sign-in failed. Try again.';

/**
 * Shown when a session that existed has ended and dropped the user back here.
 *
 * States what happened and what to do, and nothing else. It never says whether
 * the session expired, was revoked, or its owner was deactivated: the API
 * answers all three with the same 401 and the same message, and a screen that
 * guessed between them would say more than the server did. EXPERIENCE.md's
 * voice rules — short, factual, no exclamation mark, no apology.
 */
const SESSION_ENDED = 'Your session has ended. Sign in again to continue.';

/**
 * What went wrong, and which fields — if any — the user can fix.
 *
 * `fields` is not decoration: it drives `aria-invalid`, and marking an input
 * invalid when the *network* failed tells a screen-reader user their typing
 * was malformed when it was not.
 */
interface FormError {
  message: string;
  fields: readonly ('email' | 'password')[];
}

/** The credential as a whole is wrong, and the API deliberately will not say which half. */
const BOTH_FIELDS = ['email', 'password'] as const;

/** Refuse an empty field here rather than letting the API answer for it. */
function missingFields(email: string, password: string): FormError | null {
  const blank = BOTH_FIELDS.filter((field) => (field === 'email' ? email : password).trim() === '');
  if (blank.length === 0) return null;

  // The form is `noValidate` — the browser's own bubble is unstyled, untestable
  // and disappears on the next keystroke — so this is what `required` would
  // otherwise have done. Without it a blank submit reaches the API and comes
  // back as "The request was not in the expected shape", which is true of the
  // request and useless to the person who left a box empty.
  const message =
    blank.length === BOTH_FIELDS.length
      ? 'Enter your email address and password.'
      : blank[0] === 'email'
        ? 'Enter your email address.'
        : 'Enter your password.';

  return { message, fields: blank };
}

/** A failed sign-in, and whether the user has to retype the password. */
interface Rejection {
  error: FormError;
  retype: boolean;
}

/**
 * Turn a failed `signIn` into what the screen shows and does about it.
 *
 * Branched on the API's own **code**, never on the status: a 401 and a 429 are
 * different situations, and a later screen keying off `status >= 400` would
 * collapse them back together. Three outcomes:
 *
 * - `unauthorized` — the credential was refused. Both fields are marked, the
 *   password is wiped and focus returns to it, because retyping it is the
 *   thing that might work.
 * - `account_locked` — FR-4's throttle. Nothing the user typed was even looked
 *   at, so neither field is marked, what they typed survives, and focus stays
 *   where it is: the same treatment a network failure gets, and the opposite of
 *   a refused credential. **No countdown**, in any form — EXPERIENCE.md's
 *   Login-lockout row forbids one, and the API's `Retry-After` header is for a
 *   machine. The server's own sentence is the whole of what is shown.
 * - anything else — a timeout, an unreachable server, or a body that was not
 *   the shared envelope. Nothing the user typed is at fault there either.
 *
 * The message is always the API's, so the screen cannot say more than the
 * server did.
 */
function rejectionFor(failure: unknown): Rejection {
  if (!(failure instanceof ApiRequestError)) {
    return { error: { message: UNEXPECTED, fields: [] }, retype: false };
  }

  switch (failure.code) {
    case UNAUTHORIZED:
      return { error: { message: failure.message, fields: BOTH_FIELDS }, retype: true };
    case ACCOUNT_LOCKED:
      return { error: { message: failure.message, fields: [] }, retype: false };
    default:
      return { error: { message: failure.message, fields: [] }, retype: false };
  }
}

export function LoginScreen(): JSX.Element {
  const { signIn, sessionEnded } = useSession();
  const emailId = useId();
  const passwordId = useId();
  const errorId = useId();

  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<FormError | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const emailRef = useRef<HTMLInputElement>(null);
  const passwordRef = useRef<HTMLInputElement>(null);

  function invalid(field: 'email' | 'password'): boolean {
    return error !== null && error.fields.includes(field);
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    if (submitting) return;

    const blank = missingFields(email, password);
    if (blank !== null) {
      setError(blank);
      // Focus the first field the user has to fill, not the last one touched.
      (blank.fields[0] === 'email' ? emailRef : passwordRef).current?.focus();
      return;
    }

    setSubmitting(true);
    setError(null);

    try {
      await signIn(email, password);
      // No navigation and no success state: the shell replaces this screen as
      // soon as the session context reports `signed-in`.
    } catch (failure) {
      // What to show, and whether anything the user typed was at fault, is
      // decided in one place — see `rejectionFor`.
      const { error: rejection, retype } = rejectionFor(failure);
      setError(rejection);
      if (retype) {
        // Only the password, and only when the credential is what was refused.
        // Retyping an address that was almost certainly correct is a punishment
        // for a typo elsewhere — and wiping a *correct* password because the
        // Wi-Fi dropped, or because the account is throttled, says the opposite
        // of what `fields: []` just told assistive technology. In those cases
        // the form keeps what the user typed, and the retry costs one click.
        setPassword('');
        // Focus stays in the form, on the field the user has to retype.
        passwordRef.current?.focus();
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    // The same id and focus target the shell's main region carries, so the
    // gate can move focus here on the swap between the two screens without
    // knowing which one it landed on.
    <main className={styles.screen} id={MAIN_REGION_ID} tabIndex={-1}>
      <div className={styles.panel}>
        <h1 className={styles.title}>Rocell Tile Scanner</h1>
        <p className={styles.lede}>
          Sign in with the email address an Administrator issued your account.
        </p>

        {/* `role="status"`, not `role="alert"`: nothing the user just did
            failed, and an assertive interruption would frame a routine expiry
            as an error. It sits above the form rather than inside it because
            it is not about either field. */}
        {sessionEnded && (
          <p className={styles.notice} role="status">
            {SESSION_ENDED}
          </p>
        )}

        <form className={styles.form} onSubmit={(event) => void handleSubmit(event)} noValidate>
          <div className={styles.field}>
            <label className={styles.label} htmlFor={emailId}>
              Email
            </label>
            <input
              className={styles.input}
              id={emailId}
              name="email"
              type="email"
              autoComplete="username"
              autoCapitalize="none"
              autoCorrect="off"
              spellCheck={false}
              ref={emailRef}
              value={email}
              aria-invalid={invalid('email')}
              aria-describedby={error === null ? undefined : errorId}
              onChange={(event) => setEmail(event.target.value)}
            />
          </div>

          <div className={styles.field}>
            <label className={styles.label} htmlFor={passwordId}>
              Password
            </label>
            <input
              className={styles.input}
              id={passwordId}
              name="password"
              type="password"
              autoComplete="current-password"
              ref={passwordRef}
              value={password}
              aria-invalid={invalid('password')}
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
            {submitting ? 'Signing in…' : 'Sign in'}
          </button>
        </form>
      </div>
    </main>
  );
}
