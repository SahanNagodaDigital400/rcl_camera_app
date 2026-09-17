/**
 * The login screen's own behaviour, with the session context stubbed.
 *
 * What is asserted here is what a staff member on a phone actually needs: the
 * labels reach the inputs, the password is masked, a rejection is announced
 * rather than only coloured, the address survives a typo in the password, and
 * nothing on this screen offers a route to a self-provisioned account.
 */
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { ApiRequestError } from '../api/client';
import type { SessionContextValue } from '../auth/SessionProvider';
import { LoginScreen } from '../screens/LoginScreen';

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

function renderLogin(
  signIn: SessionContextValue['signIn'],
  sessionEnded: boolean = false,
): void {
  session.value = {
    status: 'signed-out',
    user: null,
    signIn,
    changePassword: vi.fn(async () => undefined),
    // Story 1.7's self-service change. Never called from this screen — it is
    // Account Settings' — and present because the context is one object.
    changeOwnPassword: vi.fn(async () => undefined),
    signOut: vi.fn(async () => undefined),
    sessionEnded,
  };
  render(<LoginScreen />);
}

function fill(email: string, password: string): void {
  fireEvent.change(screen.getByLabelText(/email/i), { target: { value: email } });
  fireEvent.change(screen.getByLabelText(/password/i), { target: { value: password } });
}

/** Click the one button on the screen — its label changes while in flight. */
function submit(): void {
  fireEvent.click(screen.getByRole('button'));
}

const accepted = (): SessionContextValue['signIn'] => vi.fn(async () => undefined);

const rejected = (): SessionContextValue['signIn'] =>
  vi.fn(async () => {
    throw new ApiRequestError('unauthorized', 'Email or password is incorrect.', 401);
  });

/**
 * FR-4's lockout, as the API sends it: a 429 with its own code and its own
 * sentence — and, on the wire, a `Retry-After` header the screen never sees
 * because `ApiRequestError` deliberately does not carry one.
 */
const lockedOut = (): SessionContextValue['signIn'] =>
  vi.fn(async () => {
    throw new ApiRequestError(
      'account_locked',
      'Too many sign-in attempts. This account is temporarily locked.',
      429,
    );
  });

const unreachable = (): SessionContextValue['signIn'] =>
  vi.fn(async () => {
    throw new ApiRequestError(
      'network_error',
      'Could not reach the server. Check your connection and try again.',
      0,
    );
  });

describe('the login screen', () => {
  it('associates every label with its input', () => {
    renderLogin(accepted());

    expect(screen.getByLabelText(/email/i).tagName).toBe('INPUT');
    expect(screen.getByLabelText(/password/i).tagName).toBe('INPUT');
  });

  it('masks the password field', () => {
    renderLogin(accepted());

    expect(screen.getByLabelText(/password/i).getAttribute('type')).toBe('password');
  });

  it('asks the browser for the right autofill entries', () => {
    // Without these a password manager offers nothing, and staff sign in on a
    // shared shop-floor phone where typing a password is the slow part.
    renderLogin(accepted());

    expect(screen.getByLabelText(/email/i).getAttribute('autocomplete')).toBe('username');
    expect(screen.getByLabelText(/password/i).getAttribute('autocomplete')).toBe(
      'current-password',
    );
  });

  it('renders no app bar and no navigation', () => {
    // DESIGN.md: the app bar is present on authenticated screens only, and nav
    // is role-conditional — neither can exist before a role does.
    renderLogin(accepted());

    expect(screen.queryByTestId('app-bar')).toBeNull();
    expect(screen.queryByRole('navigation')).toBeNull();
  });

  it('offers exactly one primary action and no self-provisioning affordance', () => {
    // FR-1. A link here would promise a flow the product deliberately lacks —
    // as would a "forgot password" link, which is an Administrator's job.
    renderLogin(accepted());

    expect(screen.getAllByRole('button')).toHaveLength(1);
    expect(screen.queryByRole('link')).toBeNull();
    expect(document.body.textContent?.toLowerCase()).not.toContain('forgot');
  });

  it('submits the typed credential once', async () => {
    const signIn = accepted();
    renderLogin(signIn);

    fill('kasun@rocell.lk', 'a-long-enough-password');
    submit();

    await waitFor(() => expect(signIn).toHaveBeenCalledTimes(1));
    expect(signIn).toHaveBeenCalledWith('kasun@rocell.lk', 'a-long-enough-password');
  });

  it('shows the session-ended notice only when a session actually ended', () => {
    // The default arrival at this screen — never signed in, or signed out
    // deliberately — says nothing. A notice here would tell a user who has
    // lost nothing that they have.
    renderLogin(vi.fn(async () => undefined));
    expect(screen.queryByRole('status')).toBeNull();

    cleanup();
    renderLogin(vi.fn(async () => undefined), true);

    // `role="status"`, not `role="alert"`: a session reaching its 12-hour idle
    // window or its 7-day ceiling is not a failure of anything the user just
    // did, and an assertive interruption would frame it as one.
    const notice = screen.getByRole('status');
    expect(notice.textContent).toMatch(/session has ended/i);
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('never names which way the session ended', () => {
    // Expiry, revocation and deactivation are indistinguishable by design —
    // the API answers all three with one 401 and one message. A screen that
    // guessed between them would say more than the server did.
    renderLogin(vi.fn(async () => undefined), true);

    expect(screen.getByRole('status').textContent).not.toMatch(
      /expir|revok|deactivat|disabled|inactive|locked/i,
    );
  });

  it('shows no error before anything is submitted', () => {
    renderLogin(accepted());

    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('announces a rejection through a live region', async () => {
    renderLogin(rejected());

    fill('kasun@rocell.lk', 'wrong');
    submit();

    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toBe('Email or password is incorrect.');
  });

  it('keeps the address and clears only the password', async () => {
    renderLogin(rejected());

    fill('kasun@rocell.lk', 'wrong');
    submit();

    await screen.findByRole('alert');
    expect((screen.getByLabelText(/email/i) as HTMLInputElement).value).toBe('kasun@rocell.lk');
    expect((screen.getByLabelText(/password/i) as HTMLInputElement).value).toBe('');
  });

  it('leaves focus inside the form after a rejection', async () => {
    renderLogin(rejected());

    fill('kasun@rocell.lk', 'wrong');
    submit();

    await screen.findByRole('alert');
    expect(document.activeElement).toBe(screen.getByLabelText(/password/i));
  });

  it('points the inputs at the error message once there is one', async () => {
    renderLogin(rejected());

    fill('kasun@rocell.lk', 'wrong');
    submit();

    const alert = await screen.findByRole('alert');
    expect(screen.getByLabelText(/password/i).getAttribute('aria-describedby')).toBe(alert.id);
  });

  it('marks both fields invalid when the credential itself was refused', () => {
    // The API deliberately will not say which half was wrong, so marking both
    // is the honest representation of what it told us.
    renderLogin(rejected());

    fill('kasun@rocell.lk', 'wrong');
    submit();

    return waitFor(() => {
      expect(screen.getByLabelText(/email/i).getAttribute('aria-invalid')).toBe('true');
      expect(screen.getByLabelText(/password/i).getAttribute('aria-invalid')).toBe('true');
    });
  });

  it('keeps what was typed when the server could not be reached', async () => {
    // The mirror of the `aria-invalid` rule above, and the same reasoning:
    // nothing the user typed was at fault, so wiping a password that was
    // probably correct — and yanking focus to retype it — contradicts what the
    // same failure just told assistive technology. The retry costs one click.
    renderLogin(unreachable());
    const before = document.activeElement;

    fill('kasun@rocell.lk', 'a-long-enough-password');
    submit();

    await screen.findByRole('alert');
    expect((screen.getByLabelText(/password/i) as HTMLInputElement).value).toBe(
      'a-long-enough-password',
    );
    expect(document.activeElement).toBe(before);
  });

  it('marks no field invalid when the server could not be reached', async () => {
    // Nothing the user typed was malformed. Reporting two invalid fields to a
    // screen reader because the network dropped is a lie told to assistive
    // technology, and it sends the user to retype a correct address.
    renderLogin(unreachable());

    fill('kasun@rocell.lk', 'a-long-enough-password');
    submit();

    await screen.findByRole('alert');
    expect(screen.getByLabelText(/email/i).getAttribute('aria-invalid')).toBe('false');
    expect(screen.getByLabelText(/password/i).getAttribute('aria-invalid')).toBe('false');
  });

  describe('a locked account', () => {
    it("shows the server's own sentence", async () => {
      renderLogin(lockedOut());

      fill('kasun@rocell.lk', 'a-long-enough-password');
      submit();

      const alert = await screen.findByRole('alert');
      expect(alert.textContent).toBe(
        'Too many sign-in attempts. This account is temporarily locked.',
      );
    });

    it('marks neither field invalid', async () => {
      // The credential was never looked at — the API refused before reading it
      // — so nothing the user typed was malformed. Marking both inputs, as a
      // refused credential does, would send them to retype a correct address
      // and tell assistive technology something untrue.
      renderLogin(lockedOut());

      fill('kasun@rocell.lk', 'a-long-enough-password');
      submit();

      await screen.findByRole('alert');
      expect(screen.getByLabelText(/email/i).getAttribute('aria-invalid')).toBe('false');
      expect(screen.getByLabelText(/password/i).getAttribute('aria-invalid')).toBe('false');
    });

    it('keeps what was typed and leaves focus alone', async () => {
      renderLogin(lockedOut());
      const before = document.activeElement;

      fill('kasun@rocell.lk', 'a-long-enough-password');
      submit();

      await screen.findByRole('alert');
      expect((screen.getByLabelText(/password/i) as HTMLInputElement).value).toBe(
        'a-long-enough-password',
      );
      expect((screen.getByLabelText(/email/i) as HTMLInputElement).value).toBe('kasun@rocell.lk');
      expect(document.activeElement).toBe(before);
    });

    it('renders no countdown', async () => {
      // EXPERIENCE.md's Login-lockout row: a different message from a
      // wrong-password rejection, and no countdown. The API sends
      // `Retry-After`; it is machine-facing, and a number in *this message*
      // would be that header leaking into the UI — or a duration restated in
      // the copy, which the same row forbids.
      //
      // Scoped to the alert rather than to `document.body`: a digit anywhere on
      // the screen is not the thing being banned, and a body-wide check would
      // fail the day unrelated copy gains a number.
      renderLogin(lockedOut());

      fill('kasun@rocell.lk', 'a-long-enough-password');
      submit();

      const alert = await screen.findByRole('alert');
      expect(alert.textContent ?? '').not.toMatch(/\d/);
    });
  });

  describe('an empty field', () => {
    it('is refused here rather than by the API', async () => {
      // The form is noValidate, so `required` does nothing. Without this check
      // a blank submit comes back as "The request was not in the expected
      // shape" — true of the request, useless to the person who left a box
      // empty.
      const signIn = accepted();
      renderLogin(signIn);

      submit();

      expect((await screen.findByRole('alert')).textContent).toBe(
        'Enter your email address and password.',
      );
      expect(signIn).not.toHaveBeenCalled();
    });

    it('names the one field that is missing', async () => {
      const signIn = accepted();
      renderLogin(signIn);

      fill('kasun@rocell.lk', '');
      submit();

      expect((await screen.findByRole('alert')).textContent).toBe('Enter your password.');
      expect(screen.getByLabelText(/password/i).getAttribute('aria-invalid')).toBe('true');
      expect(screen.getByLabelText(/email/i).getAttribute('aria-invalid')).toBe('false');
      expect(signIn).not.toHaveBeenCalled();
    });

    it('treats whitespace as empty', async () => {
      const signIn = accepted();
      renderLogin(signIn);

      fill('   ', '   ');
      submit();

      await screen.findByRole('alert');
      expect(signIn).not.toHaveBeenCalled();
    });

    it('puts focus on the field that has to be filled', async () => {
      renderLogin(accepted());

      fill('', 'a-long-enough-password');
      submit();

      await screen.findByRole('alert');
      expect(document.activeElement).toBe(screen.getByLabelText(/email/i));
    });
  });

  it('disables the submit button while a sign-in is in flight', async () => {
    let release: (() => void) | undefined;
    const signIn = vi.fn(
      async () =>
        await new Promise<void>((resolve) => {
          release = resolve;
        }),
    );
    renderLogin(signIn);

    fill('kasun@rocell.lk', 'a-long-enough-password');
    submit();

    const button = screen.getByRole('button');
    await waitFor(() => expect(button.hasAttribute('disabled')).toBe(true));
    expect(button.textContent).toContain('Signing in');

    release?.();
    await waitFor(() => expect(button.hasAttribute('disabled')).toBe(false));
  });

  it('submits at most once while one attempt is still in flight', async () => {
    let release: (() => void) | undefined;
    const signIn = vi.fn(
      async () =>
        await new Promise<void>((resolve) => {
          release = resolve;
        }),
    );
    renderLogin(signIn);

    fill('kasun@rocell.lk', 'a-long-enough-password');
    submit();
    submit();

    await waitFor(() => expect(signIn).toHaveBeenCalledTimes(1));
    release?.();
  });

  it('is operable by keyboard alone', async () => {
    // Native controls and a real submit: the form submits on Enter in a field
    // because the button is `type="submit"` inside a `<form>`, not because a
    // click handler happens to be wired to it.
    const signIn = accepted();
    renderLogin(signIn);

    const form = screen.getByRole('button').closest('form');
    expect(form).not.toBeNull();
    expect(screen.getByRole('button').getAttribute('type')).toBe('submit');
    for (const field of [screen.getByLabelText(/email/i), screen.getByLabelText(/password/i)]) {
      // A positive tabindex would reorder the whole page's tab sequence; a
      // negative one would take the field out of it entirely.
      expect(field.getAttribute('tabindex')).toBeNull();
    }

    fill('kasun@rocell.lk', 'a-long-enough-password');
    fireEvent.submit(form as HTMLFormElement);

    await waitFor(() => expect(signIn).toHaveBeenCalledTimes(1));
  });

  it('reports a network failure factually rather than as a wrong password', async () => {
    const signIn = vi.fn(async () => {
      throw new ApiRequestError(
        'network_error',
        'Could not reach the server. Check your connection and try again.',
        0,
      );
    });
    renderLogin(signIn);

    fill('kasun@rocell.lk', 'a-long-enough-password');
    submit();

    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain('Could not reach the server');
  });
});
