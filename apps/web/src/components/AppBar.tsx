import { Scan, SignOut, UserCircle } from '@phosphor-icons/react';
import type { JSX } from 'react';

import styles from './AppBar.module.css';

const PRODUCT_NAME = 'Rocell Tile Scanner';

interface AppBarProps {
  /**
   * Sign the current user out. Rendered as a control only when supplied, so
   * the bar stays exactly what it was on any screen that has no session to
   * end — and so no screen can show a sign-out that does nothing.
   */
  onSignOut?: (() => void) | undefined;
  /**
   * Open Account Settings. Optional on exactly the same terms as `onSignOut`:
   * absent, no control is rendered. EXPERIENCE.md line 32 puts Account
   * Settings behind the nav's profile entry; the app bar's trailing avatar
   * control is that entry (`mockups/key-scan.html`'s `.avatar-btn`).
   */
  onOpenAccount?: (() => void) | undefined;
  /**
   * Return to the home panel. Supplied, the brand becomes a button — the
   * conventional place a product name leads home, and on a phone the only
   * way there, since the tab bar has no Home tab. Absent, the brand is plain
   * text.
   */
  onHome?: (() => void) | undefined;
}

/**
 * The app bar: navy fill, white foreground, and a 3–4px accent-orange stripe
 * along its bottom edge (DESIGN.md, UX-DR4/DR5).
 *
 * The orange here is chrome, not an action — it is the one deliberate
 * exception to "orange is the single call to action per screen", and nothing
 * on the stripe is clickable.
 *
 * Present on authenticated screens only. The login screen renders no bar at
 * all, which is why the sign-out control below can be optional without a
 * second variant of this component.
 *
 * Both trailing controls carry an icon *and* a word. Below `--breakpoint-md`
 * the word is visually hidden so the bar fits a 375px phone with room for
 * the product name; it stays in the document, so the accessible name of each
 * control is unchanged at every width.
 *
 * Icons are Phosphor at `regular` weight, which is the library default: no
 * `weight` prop is passed anywhere, and a guard test fails the build if one
 * ever is (UX-DR3). The icon is sized from `--icon-size` in CSS rather than
 * through the `size` prop, so no dimension literal lives in this file.
 */
export function AppBar({ onSignOut, onOpenAccount, onHome }: AppBarProps = {}): JSX.Element {
  const brand = (
    <>
      <Scan className={styles.icon} aria-hidden="true" />
      <span className={styles.title}>{PRODUCT_NAME}</span>
    </>
  );

  return (
    <header className={styles.appBar} data-testid="app-bar">
      {onHome === undefined ? (
        <div className={styles.brand}>{brand}</div>
      ) : (
        <button className={styles.brand} type="button" onClick={onHome}>
          {brand}
        </button>
      )}
      {/* One trailing group rather than two independently right-aligned
          controls: with `margin-inline-start: auto` on each, the free space
          would be split between them and they would drift apart as the bar
          widened. */}
      <div className={styles.actions}>
        {onOpenAccount !== undefined && (
          // Before the sign-out, and in the same outlined secondary treatment:
          // going to a screen is a lesser action than leaving the app, and both
          // are lesser than whatever the screen itself is for.
          <button className={styles.account} type="button" onClick={onOpenAccount}>
            <UserCircle className={styles.icon} aria-hidden="true" />
            <span className={styles.label}>Account</span>
          </button>
        )}
        {onSignOut !== undefined && (
          // Not the primary action: DESIGN.md allows exactly one accent control
          // per screen, and on an authenticated screen that is whatever the
          // screen is for — never the way out of it.
          <button className={styles.signOut} type="button" onClick={onSignOut}>
            <SignOut className={styles.icon} aria-hidden="true" />
            <span className={styles.label}>Sign out</span>
          </button>
        )}
      </div>
      <span className={styles.stripe} data-testid="app-bar-stripe" aria-hidden="true" />
    </header>
  );
}
