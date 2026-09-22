import { useEffect, useRef } from 'react';
import type { JSX, KeyboardEvent, MouseEvent } from 'react';

import styles from './ImageViewer.module.css';

const CLOSE = 'Close';

interface ImageViewerProps {
  /** The same `src` the Candidate card used — proxied, never a storage URL (AD-9). */
  src: string;
  alt: string;
  /** Escape, a scrim click, or Close. Never a write. */
  onClose: () => void;
}

/**
 * The tap-to-fullscreen verification moment (Story 3.4, EXPERIENCE.md).
 *
 * A minimal scrim-and-panel overlay showing one `<img>` at
 * `object-fit: contain` across the whole viewport — the same picture the
 * Candidate card rendered, larger. **Not `ConfirmDialog`**: there is one
 * control (Close), no confirm/refusal states and nothing in flight, so none
 * of that component's multi-control Tab-cycle or `busy` machinery applies.
 *
 * **Focus.** Moved onto the panel on open (`ConfirmDialog`'s own reasoning:
 * the image is what a screen-reader user needs announced, not a jump
 * straight to a button) and restored to whatever held it — the Candidate
 * card that was tapped — when this unmounts. `Escape`, a scrim click and
 * Close all dismiss, and every `Tab` while this is open lands back on the
 * one control there is to land on: with a single stop, there is no cycle to
 * compute the way `ConfirmDialog` computes one between two.
 */
export function ImageViewer({ src, alt, onClose }: ImageViewerProps): JSX.Element {
  const panelRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  /** Where focus was when this mounted, and where it goes back to on close. */
  const opener = useRef<Element | null>(null);

  useEffect(() => {
    opener.current = document.activeElement;
    panelRef.current?.focus();

    return () => {
      const previous = opener.current;
      // Never `<body>` — there was nothing to return focus *to* — and never a
      // node the DOM has since removed.
      if (previous === document.body) return;
      if (previous instanceof HTMLElement && previous.isConnected) previous.focus();
    };
  }, []);

  function handleKeyDown(event: KeyboardEvent<HTMLDivElement>): void {
    if (event.key === 'Escape') {
      // Stopped as well as handled, `ConfirmDialog`'s reason: the key would
      // otherwise keep travelling to whatever else on the page listens for it.
      event.stopPropagation();
      onClose();
      return;
    }

    if (event.key !== 'Tab') return;
    // One control — Close — so every Tab, in either direction, lands back on
    // it rather than escaping the scrim. `ConfirmDialog`'s trap computes a
    // first and a last control to cycle between; with a single stop there is
    // nothing to compute.
    event.preventDefault();
    closeRef.current?.focus();
  }

  function handleScrimClick(event: MouseEvent<HTMLDivElement>): void {
    // Only the scrim itself — a click that landed on the image or the Close
    // control and bubbled out of it is not a dismissal.
    if (event.target !== event.currentTarget) return;
    onClose();
  }

  return (
    <div className={styles.scrim} onClick={handleScrimClick} onKeyDown={handleKeyDown}>
      <div
        aria-label={alt}
        aria-modal="true"
        className={styles.panel}
        ref={panelRef}
        role="dialog"
        tabIndex={-1}
      >
        <button className={styles.close} ref={closeRef} type="button" onClick={onClose}>
          {CLOSE}
        </button>
        <img alt={alt} className={styles.image} src={src} />
      </div>
    </div>
  );
}
