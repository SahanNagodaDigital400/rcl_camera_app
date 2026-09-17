/**
 * The shell must actually mount — every later authenticated UI story renders
 * inside it.
 *
 * Rendered directly rather than through `App`: since Story 1.3, `App` gates on
 * the session and renders the login screen when there is none, so a test that
 * asserted the app bar through `App` would be asserting the *gate*, not the
 * shell. The gate has its own file (`auth-gating.test.tsx`).
 */
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { AppShell } from '../components/AppShell';

afterEach(cleanup);

describe('the app shell', () => {
  beforeEach(() => {
    render(
      <AppShell>
        <h1>Rocell Tile Scanner</h1>
      </AppShell>,
    );
  });

  it('renders the app bar', () => {
    expect(screen.getByTestId('app-bar').tagName).toBe('HEADER');
  });

  it('renders the app bar accent stripe', () => {
    // The stripe is decoration, not an affordance: it carries no label and is
    // hidden from assistive technology.
    const stripe = screen.getByTestId('app-bar-stripe');
    expect(stripe.getAttribute('aria-hidden')).toBe('true');
  });

  it('names the application in the app bar', () => {
    expect(screen.getByTestId('app-bar').textContent).toContain('Rocell Tile Scanner');
  });

  it('renders a main region', () => {
    expect(screen.getByTestId('app-main').tagName).toBe('MAIN');
  });

  it('offers a skip link as the first tab stop, pointing at the main region', () => {
    const skip = screen.getByRole('link', { name: /skip to main content/i });
    const main = screen.getByTestId('app-main');

    expect(skip.getAttribute('href')).toBe(`#${main.id}`);
    expect(main.id).toBeTruthy();
    // It must precede the app bar in the document, or it is not a skip link.
    expect(skip.compareDocumentPosition(screen.getByTestId('app-bar'))).toBe(
      Node.DOCUMENT_POSITION_FOLLOWING,
    );
  });

  it('lets the skip target take focus', () => {
    expect(screen.getByTestId('app-main').getAttribute('tabindex')).toBe('-1');
  });

  it('renders exactly one main landmark', () => {
    expect(screen.getAllByRole('main')).toHaveLength(1);
  });

  it('renders no sign-out control when none is supplied', () => {
    // A bar that offered a way out on a screen with nothing to sign out of
    // would be a control that does nothing.
    expect(screen.queryByRole('button', { name: /sign out/i })).toBeNull();
  });
});

describe('the app bar sign-out control', () => {
  it('appears only when a handler is given, and calls it', () => {
    const onSignOut = vi.fn();
    render(<AppShell onSignOut={onSignOut}>content</AppShell>);

    fireEvent.click(screen.getByRole('button', { name: /sign out/i }));

    expect(onSignOut).toHaveBeenCalledTimes(1);
  });

  it('is a real button, so the keyboard reaches it without a tabindex', () => {
    render(<AppShell onSignOut={() => undefined}>content</AppShell>);

    const control = screen.getByRole('button', { name: /sign out/i });
    expect(control.tagName).toBe('BUTTON');
    expect(control.getAttribute('type')).toBe('button');
    expect(control.getAttribute('tabindex')).toBeNull();
  });
});

describe('rendering the shell', () => {
  it('logs no console error', () => {
    const spy = vi.spyOn(console, 'error').mockImplementation(() => undefined);

    render(<AppShell>content</AppShell>);
    cleanup();

    expect(spy.mock.calls).toEqual([]);
  });
});
