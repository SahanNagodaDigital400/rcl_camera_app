/** The shell must actually mount — every later UI story renders inside it. */
import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import App from '../App';

afterEach(cleanup);

describe('the app shell', () => {
  beforeEach(() => {
    render(<App />);
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
});

describe('rendering the shell', () => {
  it('logs no console error', () => {
    const spy = vi.spyOn(console, 'error').mockImplementation(() => undefined);

    render(<App />);
    cleanup();

    expect(spy.mock.calls).toEqual([]);
  });
});
