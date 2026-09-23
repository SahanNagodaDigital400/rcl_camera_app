import {
  ClockCounterClockwise,
  House,
  ListBullets,
  Scan,
  SquaresFour,
  Users,
} from '@phosphor-icons/react';
import type { Icon } from '@phosphor-icons/react';
import type { JSX, ReactNode } from 'react';

import { AppBar } from './AppBar';
import styles from './AppShell.module.css';
import type { Role } from '@rocell/schema/user';

/**
 * The id of the main region, and the element the gate moves focus to when it
 * swaps one screen for another. The login screen carries the same id for the
 * same reason — see `App.tsx`.
 */
export const MAIN_REGION_ID = 'main';

/**
 * The six top-level destinations EXPERIENCE.md's Information Architecture
 * names for the nav. `'home'` is the landing panel `App` renders inside the
 * shell; the other five are the surfaces the nav points at.
 */
export type NavKey = 'home' | 'scan' | 'history' | 'catalogue' | 'users' | 'audit';

export interface ShellNav {
  /** Which entries render: Staff sees Scan and History, an Administrator every entry. */
  role: Role;
  /** The entry the current screen belongs to, or `null` when none does (Account). */
  current: NavKey | null;
  onNavigate: (key: NavKey) => void;
}

interface NavEntry {
  key: NavKey;
  label: string;
  Icon: Icon;
  /** Rendered for an Administrator only. */
  admin: boolean;
  /** Hidden from the phone-width tab bar (the brand in the app bar reaches it). */
  wideOnly: boolean;
}

/**
 * One list, rendered once. The same `<nav>` is a bottom tab bar below
 * `--breakpoint-md` and a sidebar at and above it — CSS moves it, so no
 * destination is ever in the document twice with the same name.
 */
const ENTRIES: readonly NavEntry[] = [
  { key: 'home', label: 'Home', Icon: House, admin: false, wideOnly: true },
  { key: 'scan', label: 'Scan', Icon: Scan, admin: false, wideOnly: false },
  { key: 'history', label: 'History', Icon: ClockCounterClockwise, admin: false, wideOnly: false },
  { key: 'catalogue', label: 'Catalogue', Icon: SquaresFour, admin: true, wideOnly: false },
  { key: 'users', label: 'Users', Icon: Users, admin: true, wideOnly: false },
  { key: 'audit', label: 'Audit log', Icon: ListBullets, admin: true, wideOnly: false },
];

interface AppShellProps {
  children: ReactNode;
  /** Forwarded to the app bar; see `AppBar`. Omitted, no control is rendered. */
  onSignOut?: (() => void) | undefined;
  /** Forwarded to the app bar; see `AppBar`. Omitted, no control is rendered. */
  onOpenAccount?: (() => void) | undefined;
  /**
   * The role-conditional navigation. Omitted, no nav is rendered — the shell
   * is then the bare frame the app-shell tests mount.
   */
  nav?: ShellNav | undefined;
}

/**
 * The application frame: app bar above, the navigation, and the main region.
 *
 * Rendered on authenticated screens only — `App` chooses between this and the
 * login screen, which carries no chrome at all (DESIGN.md).
 *
 * The nav is role-conditional rather than a single menu with disabled items
 * (EXPERIENCE.md Foundation): a Staff user never sees an Admin entry they
 * cannot use. Below `--breakpoint-md` it is a bottom tab bar — Scan and
 * History for Staff, plus the three admin sections for an Administrator,
 * five entries at most — and at and above it a sidebar with every entry flat,
 * Home included. It is a convenience only: the server refuses a Staff caller
 * at every `/admin/` route whatever this renders (AGENTS.md Policy).
 */
export function AppShell({ children, onSignOut, onOpenAccount, nav }: AppShellProps): JSX.Element {
  return (
    <div className={styles.shell}>
      <a className={styles.skipLink} href={`#${MAIN_REGION_ID}`}>
        Skip to main content
      </a>
      <AppBar
        onSignOut={onSignOut}
        onOpenAccount={onOpenAccount}
        onHome={nav === undefined ? undefined : () => nav.onNavigate('home')}
      />
      <div className={nav === undefined ? styles.body : `${styles.body} ${styles.bodyWithNav}`}>
        {nav !== undefined && (
          <nav className={styles.nav} aria-label="Main">
            <ul className={styles.navList}>
              {ENTRIES.filter((entry) => !entry.admin || nav.role === 'admin').map(
                ({ key, label, Icon: Glyph, wideOnly }) => (
                  <li
                    className={
                      wideOnly ? `${styles.navItem} ${styles.navItemWide}` : styles.navItem
                    }
                    key={key}
                  >
                    {/* A real button, named by its visible label, with the
                        current entry marked for assistive technology as well
                        as by colour. */}
                    <button
                      aria-current={nav.current === key ? 'page' : undefined}
                      className={styles.navButton}
                      type="button"
                      onClick={() => nav.onNavigate(key)}
                    >
                      <Glyph className={styles.navIcon} aria-hidden="true" />
                      <span className={styles.navLabel}>{label}</span>
                    </button>
                  </li>
                ),
              )}
            </ul>
          </nav>
        )}
        <main
          className={nav === undefined ? styles.main : `${styles.main} ${styles.mainWithNav}`}
          id={MAIN_REGION_ID}
          tabIndex={-1}
          data-testid="app-main"
        >
          {children}
        </main>
      </div>
    </div>
  );
}
