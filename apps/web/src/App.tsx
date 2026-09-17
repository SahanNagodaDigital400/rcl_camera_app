import type { JSX } from 'react';

import styles from './App.module.css';
import { AppShell } from './components/AppShell';

/**
 * The application root.
 *
 * There is nothing behind this yet — no auth, no camera, no catalogue. It
 * renders the shell so the token layer has something real to paint and the
 * later stories have something real to mount inside.
 */
export default function App(): JSX.Element {
  return (
    <AppShell>
      <h1 className={styles.title}>Rocell Tile Scanner</h1>
      <p className={styles.lede}>
        Internal staff tool. Photograph a tile and get the three closest matches from the
        catalogue, each with its reference image, Size and Category.
      </p>
    </AppShell>
  );
}
