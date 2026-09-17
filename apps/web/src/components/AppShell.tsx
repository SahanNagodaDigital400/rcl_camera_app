import type { JSX, ReactNode } from 'react';

import { AppBar } from './AppBar';
import styles from './AppShell.module.css';

/**
 * The id of the main region, and the element the gate moves focus to when it
 * swaps one screen for another. The login screen carries the same id for the
 * same reason — see `App.tsx`.
 */
export const MAIN_REGION_ID = 'main';

interface AppShellProps {
  children: ReactNode;
  /** Forwarded to the app bar; see `AppBar`. Omitted, no control is rendered. */
  onSignOut?: (() => void) | undefined;
}

/**
 * The application frame: app bar above, a main region below, and the
 * responsive grid the navigation will slot into.
 *
 * Rendered on authenticated screens only — `App` chooses between this and the
 * login screen, which carries no chrome at all (DESIGN.md).
 *
 * Navigation itself is deliberately still absent. It is role-conditional
 * (Staff sees Scan and History; an Administrator also sees the admin sections)
 * and arrives with the surfaces it points at. What exists here is the frame:
 * below `--breakpoint-md` a single column with room for a bottom tab bar, at
 * and above it a leading sidebar column.
 */
export function AppShell({ children, onSignOut }: AppShellProps): JSX.Element {
  return (
    <div className={styles.shell}>
      <a className={styles.skipLink} href={`#${MAIN_REGION_ID}`}>
        Skip to main content
      </a>
      <AppBar onSignOut={onSignOut} />
      <div className={styles.body}>
        <main className={styles.main} id={MAIN_REGION_ID} tabIndex={-1} data-testid="app-main">
          {children}
        </main>
      </div>
    </div>
  );
}
