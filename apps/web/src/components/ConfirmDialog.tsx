import { useCallback, useEffect, useId, useRef } from 'react';
import type { JSX, KeyboardEvent, MouseEvent } from 'react';

import styles from './ConfirmDialog.module.css';

/** What the dismissing control says in each state. */
const CANCEL = 'Cancel';
const CLOSE = 'Close';

/**
 * Every control the trap cycles between.
 *
 * Disabled ones are deliberately out — a frozen control is not a tab stop — and
 * that is exactly why `handleKeyDown` below has to cope with the list being
 * empty: while a confirmed request is in flight *both* controls are disabled.
 */
const FOCUSABLE = 'button:not([disabled])';

interface CommonProps {
  /** The question or the refusal, as a heading. It is the dialog's accessible name. */
  heading: string;
  /**
   * The body: who this is about and what happens to them
   * (EXPERIENCE.md:72, :144), or the rule that refused it (EXPERIENCE.md:87).
   * It is the dialog's accessible description.
   */
  body: string;
  /** Cancel, `Escape`, or a click on the scrim. Never a write. */
  onClose: () => void;
}

interface ConfirmProps extends CommonProps {
  kind: 'confirm';
  /** The word on the destructive control — "Deactivate", "Delete". Never "Yes". */
  confirmLabel: string;
  onConfirm: () => void;
  /** Whether the confirmed request is in flight. Freezes every way out. */
  busy: boolean;
}

interface RefusalProps extends CommonProps {
  kind: 'refusal';
}

export type ConfirmDialogProps = ConfirmProps | RefusalProps;

/**
 * The product's first modal — a confirmation, or the refusal that replaces it.
 *
 * EXPERIENCE.md's `Confirmation dialog` row and DESIGN.md's
 * `confirmation-dialog` block, built for the one surface that has a destructive
 * action: the Users list. It has **two states and no third**.
 *
 * - **`confirm`** names the person and the consequence in its body — "Deactivate
 *   Kasun Perera?" over "Kasun Perera is signed out immediately, even if they
 *   are using the app right now, and cannot sign in again until the account is
 *   activated." — never a bare "Are you sure?" (EXPERIENCE.md:56, :72, :144).
 *   Its confirm control is `button-destructive` and carries a *word*, because
 *   red alone is never the signal (EXPERIENCE.md:111, DESIGN.md:206). Cancel
 *   beside it is the navy outline.
 * - **`refusal`** is what EXPERIENCE.md:148 asks for when the operation was
 *   never going to be honoured: the dialog opens *as* the refusal rather than
 *   walking the Administrator through a confirm that would have failed.
 *   **No destructive control is rendered at all** — there is nothing to press —
 *   and the body is `role="alert"`, so the sentence is announced rather than
 *   sitting silently on screen.
 *
 * **Hand-rolled, not `<dialog>`/`showModal()`.** The native element would give a
 * focus trap, `Escape`, the top layer and `::backdrop` for nothing. It is not
 * available here: jsdom 30.1.0 — pinned in `apps/web/package.json` — does not
 * implement `HTMLDialogElement.showModal`, so every test of the first modal in
 * the product would be testing a stub of the DOM API under test. So the four
 * behaviours it would have given are written out below.
 *
 * **Focus.** Moved onto the panel on open, moved there again whenever the state
 * changes, restored to whatever held it when the dialog closes, and cycled
 * between the panel's first and last enabled controls while it is open. Three
 * of those are load-bearing in ways that are easy to miss:
 *
 * - The cycle is a `keydown` handler rather than a pair of focusable sentinel
 *   nodes: jsdom moves focus on `Tab` for neither design, so both are simulated
 *   in a test — and the handler is the one that does not put tab stops in the
 *   document that announce nothing to a screen reader.
 * - **It holds with nothing enabled to cycle between.** While a confirmed
 *   request is in flight both controls are disabled, and a trap that gave up
 *   there would let `Tab` walk onto the page the scrim exists to make
 *   unreachable — at the one moment a destructive write is actually happening.
 *   With no enabled control, focus goes back to the panel.
 * - **The panel itself is a position in the cycle**, not a hole in it. It holds
 *   focus immediately after open and after a state change, and it is neither
 *   the first control nor the last, so without a case of its own `Shift+Tab`
 *   from there escapes backwards out of the dialog.
 *
 * **Every way out is frozen together while a request is in flight.** Cancel is
 * disabled, and `Escape` and a scrim click are refused for the same reason: none
 * of the three cancels the request, so a dialog dismissed mid-flight would
 * reappear the moment the request failed and the caller rendered the refusal
 * into it.
 *
 * **Depth is one level, by construction** (EXPERIENCE.md:42). This component
 * renders nothing that can open another dialog, and `UserListScreen` renders at
 * most one of it.
 *
 * Copy is the caller's: this component states no rule and names no person, so a
 * refusal always carries the API's own sentence where there is one.
 */
export function ConfirmDialog(props: ConfirmDialogProps): JSX.Element {
  const headingId = useId();
  const bodyId = useId();
  const panelRef = useRef<HTMLDivElement>(null);
  /**
   * Where focus was when this dialog mounted, and where it goes back to.
   *
   * Read once, in the same effect that arranges the restore, because by the
   * time the dialog closes the answer is inside the dialog. A keyboard or
   * screen-reader Administrator who cancels must land back on the row-end
   * control they pressed, not at the top of the document — which is also why
   * this capture must survive a confirm → refusal swap, and therefore why
   * `UserListScreen` keeps one instance across that swap rather than keying the
   * two states apart into two mounts.
   */
  const opener = useRef<Element | null>(null);
  /**
   * Which state the panel was last focused for, or `null` for "not yet".
   *
   * A string rather than the `kind` alone because there are three states worth
   * moving focus for, not two: the confirm, the confirm with its request in
   * flight (which disables the control that held focus), and the refusal. See
   * the effect below.
   */
  const shown = useRef<string | null>(null);
  /**
   * Where the gesture that is about to produce a `click` began.
   *
   * `click` is dispatched on the nearest common ancestor of the press and the
   * release, so a drag that starts on the person's name in the body and ends
   * anywhere outside the panel arrives at the scrim handler with the *scrim* as
   * its target — indistinguishable, on the `click` alone, from a deliberate
   * click on the backdrop. The press location is the only thing that separates
   * them, so it is recorded here and `handleScrimClick` decides on it.
   */
  const pressedOn = useRef<EventTarget | null>(null);

  const { kind, onClose } = props;
  /**
   * Whether every way out is frozen.
   *
   * True only while a confirmed request is in flight. The refusal state has no
   * request behind it and is always dismissible.
   */
  const locked = props.kind === 'confirm' && props.busy;

  useEffect(() => {
    opener.current = document.activeElement;

    return () => {
      const previous = opener.current;
      // Only if it is still in the document. After a successful write the row
      // that held the opener has been replaced — or, on a delete, removed — so
      // the caller moves focus itself in that case and this must not fight it.
      //
      // And never `<body>`, which is what `document.activeElement` answers when
      // the dialog was opened by a mouse rather than from the keyboard. There
      // was nothing to return focus *to*, and calling `focus()` on the body
      // would be a way to take it away from whatever has it by then.
      // Cleared here, not in the effect below, because this cleanup is what
      // takes focus *out* of the panel: whatever runs next has to be free to
      // put it back. `StrictMode` (`main.tsx`) mounts, tears down and remounts
      // in one go, so without this the restore below wins and the remount's
      // focus move is suppressed as already-done — the dialog would open with
      // focus on the row-end control behind the scrim, where neither `Escape`
      // nor the `Tab` trap (both listeners on the scrim) can reach it.
      shown.current = null;

      if (previous === document.body) return;
      if (previous instanceof HTMLElement && previous.isConnected) previous.focus();
    };
  }, []);

  useEffect(() => {
    // The panel rather than its first control: the heading and the body are
    // what a screen-reader user needs to hear first, and focusing the
    // destructive button would put the pointer on the irreversible action.
    // `tabIndex={-1}` below is what makes the panel focusable at all.
    //
    // On mount **and on every change of state**. Two of those changes take
    // focus off an element that is about to stop being focusable, and a browser
    // answers that by dropping focus to `<body>` — outside the scrim, and
    // therefore outside both the `Escape` handler and the `Tab` trap, which are
    // listeners on it:
    //
    // - A confirm the server refuses swaps this component to its refusal state
    //   in place, unmounting the control that held focus.
    // - Confirming disables both controls for the duration of the request, and
    //   the one the Administrator just pressed is normally the one holding
    //   focus. jsdom does not blur a disabled element, so no test can observe
    //   this by pressing Confirm; a browser does, and the modal would spend the
    //   whole in-flight window with nothing trapping `Tab` — at the one moment
    //   a destructive write is actually happening.
    //
    // Guarded on what was last shown as well as on the dependency list, because
    // the dependency list alone does not say "once per state": React re-runs an
    // effect whenever any dependency changes, and a second `focus()` for a
    // state already settled would fight whatever the Administrator moved to.
    const state = `${kind}:${String(locked)}`;
    if (shown.current === state) return;
    shown.current = state;
    panelRef.current?.focus();
  }, [kind, locked]);

  const controls = useCallback((): HTMLElement[] => {
    return [...(panelRef.current?.querySelectorAll<HTMLElement>(FOCUSABLE) ?? [])];
  }, []);

  function handleKeyDown(event: KeyboardEvent<HTMLDivElement>): void {
    if (event.key === 'Escape') {
      // Refused while a request is open, so the three dismissal paths agree:
      // Cancel is disabled, and neither of the other two silently abandons a
      // write that is already happening.
      if (locked) return;
      // Stopped as well as handled: the key would otherwise keep travelling up
      // to whatever else on the page listens for it.
      event.stopPropagation();
      onClose();
      return;
    }

    if (event.key !== 'Tab') return;

    // Wrapped by hand in every direction. Without this, Tab off the last
    // control lands on the browser chrome or on the page behind the scrim —
    // which is the page this dialog exists to make unreachable.
    const focusable = controls();
    const first = focusable[0];
    const last = focusable[focusable.length - 1];

    if (!first || !last) {
      // Nothing enabled to cycle between: the confirmed request froze both
      // controls. The trap still holds, and the panel is where focus waits.
      event.preventDefault();
      panelRef.current?.focus();
      return;
    }

    const active = document.activeElement;

    if (active === panelRef.current) {
      // The panel holds focus on open and after a state change. Forward enters
      // at the first control; backward enters at the last, which is the
      // direction a browser would otherwise take straight out of the dialog.
      event.preventDefault();
      (event.shiftKey ? last : first).focus();
      return;
    }

    if (event.shiftKey && active === first) {
      event.preventDefault();
      last.focus();
      return;
    }
    if (!event.shiftKey && active === last) {
      event.preventDefault();
      first.focus();
    }
  }

  function handleScrimMouseDown(event: MouseEvent<HTMLDivElement>): void {
    pressedOn.current = event.target;
  }

  function handleScrimClick(event: MouseEvent<HTMLDivElement>): void {
    const began = pressedOn.current;
    pressedOn.current = null;

    // Refused while a request is open, for `Escape`'s reason above.
    if (locked) return;
    // Only the scrim itself. A click that landed inside the panel and bubbled
    // out of it is not a dismissal.
    if (event.target !== event.currentTarget) return;
    // And only a gesture that *began* on the scrim. Dragging to select the
    // person's name in the body and releasing outside the panel produces a
    // `click` on the scrim, which the target check above cannot tell from a
    // real backdrop click — see `pressedOn`. A `null` here is a click with no
    // press behind it (a synthesised one, or a keyboard activation), which has
    // no origin to disagree with.
    if (began !== null && began !== event.currentTarget) return;
    onClose();
  }

  return (
    // The scrim is the overlay *and* the dismiss target. It is not a control:
    // it carries no role and no tab stop, because `Escape` and Cancel are the
    // keyboard paths and a focusable backdrop would be a third one that
    // announces nothing.
    <div
      className={styles.scrim}
      onClick={handleScrimClick}
      onKeyDown={handleKeyDown}
      onMouseDown={handleScrimMouseDown}
    >
      <div
        aria-describedby={bodyId}
        aria-labelledby={headingId}
        aria-modal="true"
        className={styles.panel}
        ref={panelRef}
        role="dialog"
        tabIndex={-1}
      >
        <h2 className={styles.heading} id={headingId}>
          {props.heading}
        </h2>
        {props.kind === 'refusal' ? (
          // `role="alert"`, because this state *is* the answer: the
          // Administrator pressed a destructive control and the product is
          // refusing, which has to be announced rather than discovered.
          //
          // Inserted rather than re-labelled: the two variants carry distinct
          // keys so React unmounts one and mounts the other instead of reusing
          // the node and merely adding the role to it — a `role="alert"` added
          // to an element already in the tree is not reliably announced. This
          // is the same rule the form screens state for their own alert slots.
          <p className={styles.body} id={bodyId} key="refusal" role="alert">
            {props.body}
          </p>
        ) : (
          <p className={styles.body} id={bodyId} key="confirm">
            {props.body}
          </p>
        )}
        <div className={styles.actions}>
          {props.kind === 'confirm' && (
            // Rendered in this state and in no other. The refusal has no
            // destructive control to disable or hide — it has none at all,
            // which is the only version of "no destructive action fires"
            // (EXPERIENCE.md:148) that cannot be defeated by a stray click.
            <button
              className={styles.confirm}
              disabled={props.busy}
              onClick={props.onConfirm}
              type="button"
            >
              {props.confirmLabel}
            </button>
          )}
          <button
            className={styles.dismiss}
            disabled={locked}
            onClick={onClose}
            type="button"
          >
            {props.kind === 'confirm' ? CANCEL : CLOSE}
          </button>
        </div>
      </div>
    </div>
  );
}
