import type { JSX, ReactNode } from 'react';

import { AppBar } from './AppBar';
import styles from './AppShell.module.css';

interface AppShellProps {
  children: ReactNode;
}

/**
 * The application frame: app bar above, a main region below, and the
 * responsive grid the navigation will slot into.
 *
 * Navigation itself is deliberately absent. It is role-conditional (Staff sees
 * Scan and History; an Administrator also sees the admin sections) and so it
 * cannot exist before authentication does. What exists here is the frame:
 * below `--breakpoint-md` a single column with room for a bottom tab bar,
 * at and above it a leading sidebar column.
 */
export function AppShell({ children }: AppShellProps): JSX.Element {
  return (
    <div className={styles.shell}>
      <a className={styles.skipLink} href="#main">
        Skip to main content
      </a>
      <AppBar />
      <div className={styles.body}>
        <main className={styles.main} id="main" tabIndex={-1} data-testid="app-main">
          {children}
        </main>
      </div>
    </div>
  );
}
