import { Scan } from '@phosphor-icons/react';
import type { JSX } from 'react';

import styles from './AppBar.module.css';

/**
 * The app bar: navy fill, white foreground, and a 3–4px accent-orange stripe
 * along its bottom edge (DESIGN.md, UX-DR4/DR5).
 *
 * The orange here is chrome, not an action — it is the one deliberate
 * exception to "orange is the single call to action per screen", and nothing
 * on the stripe is clickable.
 *
 * Icons are Phosphor at `regular` weight, which is the library default: no
 * `weight` prop is passed anywhere, and a guard test fails the build if one
 * ever is (UX-DR3). The icon is sized from `--icon-size` in CSS rather than
 * through the `size` prop, so no dimension literal lives in this file.
 */
export function AppBar(): JSX.Element {
  return (
    <header className={styles.appBar} data-testid="app-bar">
      <div className={styles.brand}>
        <Scan className={styles.icon} aria-hidden="true" />
        <span className={styles.title}>Rocell Tile Scanner</span>
      </div>
      <span className={styles.stripe} data-testid="app-bar-stripe" aria-hidden="true" />
    </header>
  );
}
