/**
 * The forced-change screen's own behaviour, with the session context stubbed.
 *
 * What is asserted here is what a staff member meets on their first sign-in:
 * the label reaches the input, the password is masked, nothing else is on
 * screen to navigate to, a rejection names the rule the server named rather
 * than a generic verdict, and the whole thing works from the keyboard.
 *
 * Which screen the app *chooses* to render is `auth-gating.test.tsx`; this file
 * is only about the screen itself.
 */
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { ApiRequestError, NETWORK_ERROR, WEAK_PASSWORD } from '../api/client';
import type { SessionContextValue } from '../auth/SessionProvider';
import { ForcedPasswordChangeScreen } from '../screens/ForcedPasswordChangeScreen';
import type { User } from '@rocell/schema/user';

afterEach(cleanup);

const session = vi.hoisted(() => ({ value: null as SessionContextValue | null }));

vi.mock('../auth/SessionProvider', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../auth/SessionProvider')>();
  return {
    ...actual,
    useSession: (): SessionContextValue => {
      if (session.value === null) throw new Error('no stubbed session');
      return session.value;
    },
  };
});

const UNCLAIMED: User = {
  id: '3f1a6b2c-9d4e-4f70-8a11-5c2e7b9d0a34',
  name: 'Kasun Perera',
  email: 'kasun@rocell.lk',
  role: 'staff',
  active: true,
  must_change_password: true,
  temp_credential_expires_at: '2026-09-20T08:00:00Z',
  last_login_at: '2026-09-17T08:00:00Z',
  locked_until: null,
  created_at: '2026-09-17T08:00:00Z',
  updated_at: '2026-09-17T08:00:00Z',
};

function renderScreen(changePassword: SessionContextValue['changePassword']): void {
  session.value = {
    status: 'signed-in',
    user: UNCLAIMED,
    signIn: vi.fn(async () => undefined),
    changePassword,
    signOut: vi.fn(async () => undefined),
    // The change screen never renders the notice — it is the login screen's,
    // and a user trapped on this one has a session, not the absence of one.
    sessionEnded: false,
  };
  render(<ForcedPasswordChangeScreen />);
}

/** Click the one button on the screen — its label changes while in flight. */
function submit(): void {
  fireEvent.click(screen.getByRole('button'));
}

function type(value: string): void {
  fireEvent.change(screen.getByLabelText(/new password/i), { target: { value } });
}

const accepted = (): SessionContextValue['changePassword'] => vi.fn(async () => undefined);

/** Stands in for the resolver until the promise below hands over the real one. */
const NOT_YET = (): void => undefined;

/**
 * A `changePassword` that stays in flight until it is released.
 *
 * The in-flight state is the whole point of the two tests that use it, and an
 * already-resolved promise never renders it.
 */
function pending(): { changePassword: SessionContextValue['changePassword']; release: () => void } {
  let release = NOT_YET;
  const changePassword = vi.fn(
    async () =>
      new Promise<void>((resolve) => {
        release = resolve;
      }),
  );
  return { changePassword, release: () => release() };
}

const weak = (message: string): SessionContextValue['changePassword'] =>
  vi.fn(async () => {
    throw new ApiRequestError(WEAK_PASSWORD, message, 422);
  });

describe('the forced password change screen', () => {
  it('associates the label with the input', () => {
    // `getByLabelText` succeeding is the assertion: without the association, an
    // assistive technology reads an unlabelled box.
    renderScreen(accepted());

    expect(screen.getByLabelText(/new password/i)).toBeTruthy();
  });

  it('masks what is typed', () => {
    renderScreen(accepted());

    expect(screen.getByLabelText(/new password/i).getAttribute('type')).toBe('password');
  });

  it('asks the password manager for a new password, not the current one', () => {
    // `current-password` here would offer the temporary credential back as the
    // suggestion — the one value the server refuses.
    renderScreen(accepted());

    expect(screen.getByLabelText(/new password/i).getAttribute('autocomplete')).toBe(
      'new-password',
    );
  });

  it('offers exactly one field', () => {
    // DESIGN.md:219 specifies a single-field form. A confirm box with no
    // mismatch rule behind it is a second thing to type for no enforcement.
    renderScreen(accepted());

    expect(document.querySelectorAll('input')).toHaveLength(1);
  });

  it('renders no app bar and no navigation', () => {
    // "No navigation chrome around it — it's the only thing on screen until
    // it's done" (DESIGN.md:219).
    renderScreen(accepted());

    expect(screen.queryByTestId('app-bar')).toBeNull();
    expect(screen.queryByRole('navigation')).toBeNull();
  });

  it('offers no way out of it', () => {
    // No sign-out, no skip, no dismissal — the submit button is the only
    // control on the screen.
    renderScreen(accepted());

    expect(screen.getAllByRole('button')).toHaveLength(1);
    expect(screen.queryByRole('button', { name: /sign out|skip|later|cancel/i })).toBeNull();
    expect(screen.queryByRole('link')).toBeNull();
  });

  it('exposes a focusable main region for the gate to move focus to', () => {
    renderScreen(accepted());
    const main = screen.getByRole('main');

    expect(main.id).toBe('main');
    expect(main.getAttribute('tabindex')).toBe('-1');
  });

  it('refuses a blank submit without calling the API', () => {
    // The form is noValidate, so this is what `required` would otherwise have
    // done. Without it a blank submit comes back naming the length rule, which
    // is true and beside the point for someone who has not typed yet.
    const changePassword = accepted();
    renderScreen(changePassword);

    submit();

    expect(screen.getByRole('alert').textContent).toMatch(/enter a new password/i);
    expect(changePassword).not.toHaveBeenCalled();
  });

  it('keeps focus in the form when a blank submit is refused', () => {
    renderScreen(accepted());

    submit();

    expect(document.activeElement).toBe(screen.getByLabelText(/new password/i));
  });

  it('submits the typed password once', async () => {
    const changePassword = accepted();
    renderScreen(changePassword);

    type('a-long-enough-password');
    submit();

    await waitFor(() => expect(changePassword).toHaveBeenCalledTimes(1));
    expect(changePassword).toHaveBeenCalledWith('a-long-enough-password');
  });

  it('renders no success state of its own', async () => {
    // EXPERIENCE.md line 88: the transition is immediate, with no success
    // screen to click through. The gate swaps this screen for the shell; this
    // component must not put anything in between.
    const changePassword = accepted();
    renderScreen(changePassword);

    type('a-long-enough-password');
    submit();

    await waitFor(() => expect(changePassword).toHaveBeenCalled());
    expect(screen.queryByRole('alert')).toBeNull();
    expect(screen.getByRole('button').textContent).toBe('Set password');
  });

  it.each([
    ['the length rule', 'A password must be at least 12 characters.'],
    ['reuse of the temporary password', 'The new password must be different from the temporary one.'],
  ])('announces the rejection naming %s', async (_label, message) => {
    // EXPERIENCE.md:87 — the rejected state names which rule failed, never a
    // generic "invalid password". The message is the API's own, so the screen
    // cannot state a rule the server does not enforce.
    renderScreen(weak(message));

    type('short');
    submit();

    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toBe(message);
  });

  it('associates the rejection with the input it is about', async () => {
    renderScreen(weak('A password must be at least 12 characters.'));

    type('short');
    submit();

    const alert = await screen.findByRole('alert');
    const input = screen.getByLabelText(/new password/i);
    expect(input.getAttribute('aria-describedby')).toBe(alert.id);
    expect(input.getAttribute('aria-invalid')).toBe('true');
  });

  it('keeps what was typed after a rejection', async () => {
    // A too-short password is fixed by adding characters. Clearing the field
    // would make the correction cost the whole passphrase.
    renderScreen(weak('A password must be at least 12 characters.'));

    type('short');
    submit();

    await screen.findByRole('alert');
    expect((screen.getByLabelText(/new password/i) as HTMLInputElement).value).toBe('short');
    expect(document.activeElement).toBe(screen.getByLabelText(/new password/i));
  });

  it('marks the field invalid only when the password itself was refused', async () => {
    renderScreen(weak('A password must be at least 12 characters.'));

    type('short');
    submit();

    await screen.findByRole('alert');
    expect(screen.getByLabelText(/new password/i).getAttribute('aria-invalid')).toBe('true');
  });

  it('does not blame the field when the server could not be reached', async () => {
    // `aria-invalid` on a network failure tells a screen-reader user their
    // typing was malformed when it was not — and what they typed may be
    // perfectly good. The message is still announced; only the field's state
    // differs.
    renderScreen(
      vi.fn(async () => {
        throw new ApiRequestError(NETWORK_ERROR, 'Could not reach the server.', 0);
      }),
    );

    type('a-long-enough-password');
    submit();

    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toBe('Could not reach the server.');
    expect(screen.getByLabelText(/new password/i).getAttribute('aria-invalid')).toBe('false');
  });

  it('refuses a whitespace-only password without calling the API', async () => {
    // A password of spaces is a user who has not typed one. Sending it would
    // come back naming the length rule, which is true and unhelpful.
    const changePassword = accepted();
    renderScreen(changePassword);

    type('   ');
    submit();

    expect(screen.getByRole('alert').textContent).toMatch(/enter a new password/i);
    expect(changePassword).not.toHaveBeenCalled();
  });

  it('sends what was typed, whitespace included', async () => {
    // The emptiness test trims; the value does not. Trimming a password sets a
    // credential different from the one the user typed — and different again
    // from the one the login form would send back later.
    const changePassword = accepted();
    renderScreen(changePassword);

    type('  a-long-enough-password  ');
    submit();

    await waitFor(() =>
      expect(changePassword).toHaveBeenCalledWith('  a-long-enough-password  '),
    );
  });

  it('shows a factual message when the failure is not an API rejection', async () => {
    // A thrown `Error` carries a message written for a developer. Rendering it
    // would put a stack-shaped sentence in front of a staff member.
    renderScreen(
      vi.fn(async () => {
        throw new Error('Cannot read properties of undefined');
      }),
    );

    type('a-long-enough-password');
    submit();

    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toBe('The password could not be set. Try again.');
    expect(screen.getByLabelText(/new password/i).getAttribute('aria-invalid')).toBe('false');
  });

  it('disables the button while the request is in flight', async () => {
    const { changePassword, release } = pending();
    renderScreen(changePassword);

    type('a-long-enough-password');
    submit();

    await waitFor(() => expect(screen.getByRole('button').hasAttribute('disabled')).toBe(true));
    expect(screen.getByRole('button').textContent).toBe('Setting password…');

    release();
    await waitFor(() => expect(screen.getByRole('button').hasAttribute('disabled')).toBe(false));
  });

  it('does not send a second request while the first is in flight', async () => {
    const { changePassword, release } = pending();
    renderScreen(changePassword);

    type('a-long-enough-password');
    submit();
    fireEvent.submit(screen.getByRole('button').closest('form') as HTMLFormElement);

    expect(changePassword).toHaveBeenCalledTimes(1);
    release();
    await waitFor(() => expect(screen.getByRole('button').hasAttribute('disabled')).toBe(false));
  });

  it('is operable by keyboard alone', async () => {
    // The admin surfaces get real keyboard use, and this screen is the first
    // thing every account meets. Tab reaches the field, Enter in the field
    // submits the form — no pointer anywhere.
    const changePassword = accepted();
    renderScreen(changePassword);

    const input = screen.getByLabelText(/new password/i) as HTMLInputElement;
    input.focus();
    expect(document.activeElement).toBe(input);

    fireEvent.change(input, { target: { value: 'a-long-enough-password' } });
    fireEvent.submit(input.closest('form') as HTMLFormElement);

    await waitFor(() => expect(changePassword).toHaveBeenCalledWith('a-long-enough-password'));
  });

  it('logs no console error', async () => {
    const spy = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    renderScreen(accepted());

    type('a-long-enough-password');
    submit();
    await waitFor(() => expect(screen.getByRole('button').hasAttribute('disabled')).toBe(false));
    cleanup();

    expect(spy.mock.calls).toEqual([]);
  });
});
