/**
 * @vitest-environment node
 *
 * The token layer is only worth anything if it is actually wired up, and the
 * existing guards check its *contents* rather than its *connections*. Three
 * ways the styling can vanish while lint, typecheck and every render test stay
 * green, each closed by a check below:
 *
 *  1. Delete the token-layer import from the entry point. Nothing imports
 *     `main.tsx` in a test, so the app ships with every custom property
 *     undefined — no colour, no type scale, no spacing.
 *  2. Rename a class in a CSS module without renaming its reference. A CSS
 *     module is typed as an index signature, so `styles.appBar` becomes
 *     `undefined`, `className` becomes nothing, and the rule is simply not
 *     applied.
 *  3. Point a rule at the wrong existing token. The dangling-reference check
 *     only asks whether a token exists, never whether it is the right one, so
 *     the app bar can turn accent-coloured with white text — the documented
 *     contrast failure — without a single test noticing.
 *
 * Tests here read source text rather than computed style: `vite.config.ts`
 * sets `css: false`, so jsdom applies no stylesheet and there is no computed
 * style to assert against.
 */
import { readFileSync, readdirSync } from 'node:fs';
import { dirname, join, relative } from 'node:path';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

const SRC = fileURLToPath(new URL('..', import.meta.url));

function read(path: string): string {
  return readFileSync(path, 'utf8').replace(/\r\n?/g, '\n');
}

const TOKENS_CSS = read(join(SRC, 'styles', 'tokens.css'));

/** The declared value of a custom property, following references to their end. */
function token(name: string, seen: Set<string> = new Set()): string | null {
  // A token that references itself, directly or around a chain, would recurse
  // until the worker dies — taking every test in this file with it instead of
  // failing the one assertion that asked for the value.
  expect(seen.has(name), `${name} resolves in a circle in tokens.css`).toBe(false);
  seen.add(name);

  const escaped = name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const declarations = [...TOKENS_CSS.matchAll(new RegExp(`^\\s*${escaped}\\s*:\\s*([^;]+);`, 'gm'))];

  // The browser applies the last declaration; a test that read the first would
  // assert a value nothing renders with.
  expect(declarations.length, `${name} is declared more than once in tokens.css`).toBeLessThan(2);

  const value = declarations[0]?.[1]?.trim();
  if (value === undefined) return null;

  const reference = /^var\(\s*(--[A-Za-z0-9-]+)\s*\)$/.exec(value);
  return reference?.[1] ? token(reference[1], seen) : value;
}

/**
 * The numeric part of a token declared in CSS pixels.
 *
 * The unit is asserted, not discarded. Both constraints this reads are stated
 * in px by DESIGN.md and the spec ("at least 44x44px", "3-4px"), and a bare
 * magnitude comparison would pass `44ch` and `4%` — values that satisfy the
 * number and not the constraint.
 */
function magnitude(name: string): number {
  const value = token(name);
  expect(value, `${name} is missing from tokens.css`).toBeTruthy();
  const length = /^(-?\d+(?:\.\d+)?)([a-z%]*)$/.exec((value ?? '').trim());
  expect(length?.[1], `${name} is not a length`).toBeTruthy();
  expect(length?.[2], `${name} must be declared in CSS pixels`).toBe('px');
  return Number(length?.[1]);
}

/** The body of a rule, by selector, from a stylesheet's text. */
function rule(css: string, selector: string): string {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const body = new RegExp(`(?:^|\\})\\s*${escaped}\\s*\\{([^}]*)\\}`, 'm').exec(css)?.[1];
  expect(body, `no ${selector} rule found`).toBeTruthy();
  return body ?? '';
}

/** Every rule body in `css` whose selector list names `.<className>`. */
function rulesFor(css: string, className: string): string[] {
  return [...css.matchAll(/([^{}]*)\{([^}]*)\}/g)]
    .filter((block) => new RegExp(String.raw`(^|[\s,])\.${className}(?![\w-])`).test(block[1] ?? ''))
    .map((block) => block[2] ?? '');
}

/** The value of one declaration inside a rule body. */
function declaration(body: string, property: string): string {
  const value = new RegExp(`(?:^|;)\\s*${property}\\s*:\\s*([^;]+)`, 'm').exec(body)?.[1]?.trim();
  expect(value, `no ${property} declaration found`).toBeTruthy();
  return value ?? '';
}

function walk(dir: string, found: string[] = []): string[] {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    if (entry.isSymbolicLink()) continue;
    const path = join(dir, entry.name);
    if (entry.isDirectory()) walk(path, found);
    else found.push(path);
  }
  return found;
}

const FILES = walk(SRC);

describe('the entry point loads the styling', () => {
  const MAIN = read(join(SRC, 'main.tsx'));

  it.each([
    ['the token layer', './styles/tokens.css'],
    ['the base stylesheet', './styles/global.css'],
  ])('imports %s', (_label, specifier) => {
    // Nothing else imports these, and no test renders through main.tsx, so
    // dropping either line ships an unstyled app with a fully green suite.
    expect(MAIN).toContain(`import '${specifier}';`);
  });

  it('mounts into the element index.html actually provides', () => {
    const html = read(join(SRC, '..', 'index.html'));
    const mountId = /getElementById\('([^']+)'\)/.exec(MAIN)?.[1];

    expect(mountId, 'main.tsx no longer looks up a mount element').toBeTruthy();
    expect(html).toContain(`id="${String(mountId)}"`);
  });
});

describe('every CSS module class is referenced, and every reference exists', () => {
  const modules = FILES.filter((path) => path.endsWith('.module.css'));

  it('finds the CSS modules', () => {
    expect(modules.length).toBeGreaterThan(0);
  });

  it.each(modules.map((path) => [relative(SRC, path), path] as const))(
    '%s agrees with its consumers',
    (label, path) => {
      const css = read(path);
      const declared = new Set(
        [...css.matchAll(/^\.([A-Za-z_][\w-]*)/gm)].map((match) => match[1] ?? ''),
      );

      // Every .tsx beside the module that imports it is a consumer.
      const consumers = FILES.filter((file) => file.endsWith('.tsx')).filter((file) => {
        const base = path.slice(dirname(path).length + 1);
        return dirname(file) === dirname(path) && read(file).includes(base);
      });

      const referenced = new Set(
        consumers.flatMap((file) =>
          [...read(file).matchAll(/\bstyles\.([A-Za-z_][\w-]*)/g)].map((match) => match[1] ?? ''),
        ),
      );

      const missing = [...referenced].filter((name) => !declared.has(name));
      const unused = [...declared].filter((name) => !referenced.has(name));

      expect(missing, `${label} is referenced for a class it does not declare`).toEqual([]);
      expect(unused, `${label} declares a class nothing references`).toEqual([]);
    },
  );
});

describe('the app bar paints the colours DESIGN.md specifies', () => {
  // Read inside each test, never at collection time: a missing rule must fail
  // one named assertion, not abort the whole file and take the rest of these
  // checks silently out of the run with it.
  const css = (): string => read(join(SRC, 'components', 'AppBar.module.css'));

  it('fills with the primary colour and writes on it with its own foreground', () => {
    // Swapping either for another declared token leaves every other check
    // green while the bar renders accent-on-white: 2.63:1, an AA failure.
    const bar = rule(css(), '.appBar');

    expect(declaration(bar, 'background')).toBe('var(--color-primary)');
    expect(declaration(bar, 'color')).toBe('var(--color-primary-foreground)');
  });

  it('stripes the bottom edge with the accent', () => {
    expect(declaration(rule(css(), '.stripe'), 'background')).toBe('var(--color-accent)');
  });

  it('leaves both trailing controls outlined, never filled', () => {
    // DESIGN.md gives the accent-filled primary to the one action a screen is
    // for. The bar is on every authenticated screen, so an accent control here
    // is a second primary on all of them — and nothing could see it:
    // `app-shell.test.tsx` reads the label and the decorative icon, and
    // `vite.config.ts` sets `css: false`, so jsdom has no computed style.
    for (const name of ['.account', '.signOut']) {
      const control = rule(css(), name);

      expect(declaration(control, 'background'), name).toBe('transparent');
      expect(declaration(control, 'color'), name).toBe('var(--color-primary-foreground)');
      expect(declaration(control, 'border'), name).toBe(
        'var(--border-hairline) solid var(--color-primary-foreground)',
      );
    }
  });

  it('paints nothing but the stripe with the accent', () => {
    const accents = [...css().matchAll(/var\(--color-accent\)/g)];

    expect(accents).toHaveLength(1);
  });

  it('makes the brand the element that gives way on a phone', () => {
    // The 375px overflow fix, and the one regression in this file that a render
    // test cannot see: jsdom performs no layout, so with `min-width: 0` deleted
    // every button is still in the document, still in order, still clickable —
    // and Sign out is off the edge of the screen this product is built for.
    const brand = rule(css(), '.brand');
    const title = rule(css(), '.title');
    const actions = rule(css(), '.actions');

    expect(declaration(brand, 'min-width')).toBe('0');
    expect(declaration(title, 'text-overflow')).toBe('ellipsis');
    expect(declaration(title, 'white-space')).toBe('nowrap');
    // The trailing group never shrinks instead: `global.css` holds every button
    // to the touch-target floor, so a shrunk group spills its labels rather than
    // narrowing.
    expect(declaration(actions, 'flex')).toBe('none');
  });
});

describe('a rejection is written in the colour the matrix specifies', () => {
  // "Inline error text in `--color-destructive`" is a clause of the story's own
  // I/O matrix, and it was the one clause of that row asserted nowhere: the
  // render tests check the `role="alert"`, the message and the focus, none of
  // which can see a colour — `vite.config.ts` sets `css: false`, so jsdom
  // applies no stylesheet and there is no computed style to read. Point either
  // rule at `--color-text` and the alert renders as ordinary prose, indeed as
  // *reassuring* prose, with every other check green.
  it('colours the login screen error', () => {
    const css = read(join(SRC, 'screens', 'LoginScreen.module.css'));

    expect(declaration(rule(css, '.error'), 'color')).toBe('var(--color-destructive)');
  });

  it('colours the sign-out failure the same way', () => {
    const css = read(join(SRC, 'App.module.css'));

    expect(declaration(rule(css, '.error'), 'color')).toBe('var(--color-destructive)');
  });

  it('colours the forced password change rejection the same way', () => {
    // DESIGN.md's `force-password-change-form` block names
    // `error-foreground: {colors.destructive}` explicitly, and this is the one
    // screen whose rejection a user cannot get past.
    const css = read(join(SRC, 'screens', 'ForcedPasswordChangeScreen.module.css'));

    expect(declaration(rule(css, '.error'), 'color')).toBe('var(--color-destructive)');
  });

  it('colours the account settings rejection the same way', () => {
    // The newest screen to carry a rejection, and the one furthest from
    // DESIGN.md's named blocks — it has no spec block of its own, so this rule
    // is held by nothing but the convention the two screens above set.
    const css = read(join(SRC, 'screens', 'AccountSettingsScreen.module.css'));

    expect(declaration(rule(css, '.error'), 'color')).toBe('var(--color-destructive)');
  });

  it('colours the create user rejection the same way', () => {
    // The screen that refuses three different fields, and the one furthest from
    // DESIGN.md's named blocks. Point `.error` at `--color-text` and an address
    // already in use renders as ordinary prose beside a form that looks fine.
    const css = read(join(SRC, 'screens', 'CreateUserScreen.module.css'));

    expect(declaration(rule(css, '.error'), 'color')).toBe('var(--color-destructive)');
  });

  it('colours the user list failure the same way', () => {
    // The one screen whose alert replaces its whole contents: when this fires
    // there is no table beside it, so the sentence is the entire answer to "who
    // has access". Point it at `--color-text` and a failed load reads as a
    // paragraph somebody wrote on purpose.
    const css = read(join(SRC, 'screens', 'UserListScreen.module.css'));

    expect(declaration(rule(css, '.error'), 'color')).toBe('var(--color-destructive)');
  });

  it('writes the account settings save indicator in the brand primary', () => {
    // DESIGN.md's `save-indicator`: muted while it is working, `{colors.primary}`
    // once it has. Point `.saved` at `--color-muted-text` and the two states
    // become indistinguishable, with every render test still finding "Saved."
    const css = read(join(SRC, 'screens', 'AccountSettingsScreen.module.css'));

    expect(declaration(rule(css, '.indicator'), 'color')).toBe('var(--color-muted-text)');
    expect(declaration(rule(css, '.saved'), 'color')).toBe('var(--color-primary)');
  });

  it('writes the session-ended notice in muted text, not in the destructive red', () => {
    // A session reaching its idle window or its absolute ceiling is not a
    // failure of anything the user did, and red means destructive-or-failed in
    // this system and nothing else (DESIGN.md:167 — the one brand colour with a
    // hard behavioural contract). Point `.notice` at `--color-destructive` and
    // every render test stays green while a routine expiry reads as an error.
    const css = read(join(SRC, 'screens', 'LoginScreen.module.css'));

    expect(declaration(rule(css, '.notice'), 'color')).toBe('var(--color-muted-text)');
    expect(declaration(rule(css, '.notice'), 'color')).not.toBe('var(--color-destructive)');
  });

  it('carries the notice on a status region, not on an alert', () => {
    // The rule above is inert if the element is the wrong one. `role="alert"`
    // interrupts a screen-reader user assertively, which is right for "your
    // password was refused" and wrong for "sign in again".
    const screen = read(join(SRC, 'screens', 'LoginScreen.tsx'));

    expect(screen).toContain('className={styles.notice}');
    expect(screen).toContain('role="status"');
  });

  it.each([
    ['LoginScreen', 'LoginScreen.tsx'],
    ['ForcedPasswordChangeScreen', 'ForcedPasswordChangeScreen.tsx'],
    ['AccountSettingsScreen', 'AccountSettingsScreen.tsx'],
    ['CreateUserScreen', 'CreateUserScreen.tsx'],
    ['UserListScreen', 'UserListScreen.tsx'],
  ])('is the class %s\'s alert element actually carries', (_label, file) => {
    // The rules above are inert if the element points somewhere else. The
    // dangling-reference check upstream proves `styles.error` resolves to a
    // declared class; this proves it is the class on the live region.
    const screen = read(join(SRC, 'screens', file));

    expect(screen).toContain('className={styles.error}');
    expect(screen).toContain('role="alert"');
  });
});

describe('the forced password change is the one action on its screen', () => {
  // DESIGN.md: "Exactly one per screen" for the accent-filled primary button,
  // and its foreground is navy — white on orange is 2.63:1, the one contrast
  // pair the system bans.
  const css = (): string => read(join(SRC, 'screens', 'ForcedPasswordChangeScreen.module.css'));

  it('fills the submit with the accent and writes on it in navy', () => {
    const submit = rule(css(), '.submit');

    expect(declaration(submit, 'background')).toBe('var(--color-accent)');
    expect(declaration(submit, 'color')).toBe('var(--color-accent-foreground)');
  });

  it('gives the form the surface DESIGN.md names for it', () => {
    // DESIGN.md:134's `force-password-change-form` block specifies
    // `background: {colors.surface}` — the one way this screen is meant to
    // differ from the login screen it otherwise mirrors. Nothing else in the
    // suite can see a background, so without this the rule can be deleted and
    // every other check stays green.
    expect(declaration(rule(css(), '.panel'), 'background')).toBe('var(--color-surface)');
  });

  it('paints nothing else with the accent', () => {
    // A second orange element on the screen would make neither of them the one
    // action. Counted over the whole stylesheet rather than rule by rule, so a
    // new rule cannot introduce one unseen.
    const accents = [...css().matchAll(/var\(--color-accent\)/g)];

    expect(accents).toHaveLength(1);
  });
});

describe('changing a password is the one action on account settings', () => {
  // DESIGN.md's "exactly one per screen" for the accent-filled primary, on a
  // screen that carries two buttons: Change password takes the accent, Back is
  // the navy outline. A second orange control would make neither of them the
  // action.
  const css = (): string => read(join(SRC, 'screens', 'AccountSettingsScreen.module.css'));

  it('fills the submit with the accent and writes on it in navy', () => {
    const submit = rule(css(), '.submit');

    expect(declaration(submit, 'background')).toBe('var(--color-accent)');
    expect(declaration(submit, 'color')).toBe('var(--color-accent-foreground)');
  });

  it('leaves Back as the navy outline, not a second filled control', () => {
    const back = rule(css(), '.back');

    expect(declaration(back, 'color')).toBe('var(--color-primary)');
    expect(declaration(back, 'background')).not.toBe('var(--color-accent)');
  });

  it('paints nothing else with the accent', () => {
    const accents = [...css().matchAll(/var\(--color-accent\)/g)];

    expect(accents).toHaveLength(1);
  });
});

describe('adding a user is the one action on the create user screen', () => {
  // DESIGN.md's "exactly one per screen" for the accent-filled primary, on a
  // screen that carries two buttons and a result card: Create user takes the
  // accent, Back is the navy outline, and the card is surface-on-hairline. A
  // second orange control would make neither of them the action.
  const css = (): string => read(join(SRC, 'screens', 'CreateUserScreen.module.css'));

  it('fills the submit with the accent and writes on it in navy', () => {
    const submit = rule(css(), '.submit');

    expect(declaration(submit, 'background')).toBe('var(--color-accent)');
    expect(declaration(submit, 'color')).toBe('var(--color-accent-foreground)');
  });

  it('leaves Back as the navy outline, not a second filled control', () => {
    const back = rule(css(), '.back');

    expect(declaration(back, 'color')).toBe('var(--color-primary)');
    expect(declaration(back, 'background')).not.toBe('var(--color-accent)');
  });

  it('gives the result panel DESIGN.md\'s card treatment', () => {
    // White surface, hairline border, `md` radius, navy-tinted shadow. Nothing
    // else in the suite can see a background, so without this the card can
    // quietly become a bare block of prose the reader scrolls past — on the one
    // panel whose contents have to be transcribed accurately.
    const result = rule(css(), '.result');

    expect(declaration(result, 'background')).toBe('var(--color-surface)');
    expect(declaration(result, 'border-radius')).toBe('var(--radius-md)');
    expect(declaration(result, 'box-shadow')).toBe('var(--elevation-card)');
  });

  it('sets the temporary password in the monospace role', () => {
    // DESIGN.md reserves `code` for a value read character by character, so 0/O
    // and 1/I cannot be confused — which is the whole job of this one field.
    const credential = rule(css(), '.credential');

    expect(declaration(credential, 'font-family')).toBe('var(--font-mono)');
  });

  it('paints nothing else with the accent', () => {
    const accents = [...css().matchAll(/var\(--color-accent\)/g)];

    expect(accents).toHaveLength(1);
  });

});

describe('the home panel\'s one admin entry', () => {
  it('is outlined, never filled', () => {
    // The door on the home panel is a secondary control: the shell's landing
    // surface has no primary action, and an accent button there would be the one
    // orange thing on a screen that is not for user management. Since Story 1.9
    // the entry is Users — EXPERIENCE.md line 33's nav entry — and Create user is
    // reached from the list's "+ Add user" (line 34).
    const app = read(join(SRC, 'App.module.css'));
    const entry = rule(app, '.userList');

    expect(declaration(entry, 'background')).toBe('transparent');
    expect(declaration(entry, 'color')).toBe('var(--color-primary)');
    expect([...app.matchAll(/var\(--color-accent\)/g)]).toHaveLength(0);
  });
});

describe('adding a user is the one action on the user list', () => {
  // DESIGN.md's "exactly one per screen" for the accent-filled primary, on a
  // screen carrying three buttons and two families of badge: "+ Add user" takes
  // the accent, Back and Try again are the navy outline, and every badge is a
  // pill in the colours DESIGN.md names for it. Nothing else in the suite can
  // see any of this — `vite.config.ts` sets `css: false`, so jsdom applies no
  // stylesheet and there is no computed style to read.
  const css = (): string => read(join(SRC, 'screens', 'UserListScreen.module.css'));

  it('fills the add control with the accent and writes on it in navy', () => {
    const add = rule(css(), '.add');

    expect(declaration(add, 'background')).toBe('var(--color-accent)');
    expect(declaration(add, 'color')).toBe('var(--color-accent-foreground)');
  });

  it('leaves Back and Try again as the navy outline, not second filled controls', () => {
    for (const name of ['.back', '.retry']) {
      const control = rule(css(), name);

      expect(declaration(control, 'background'), name).toBe('transparent');
      expect(declaration(control, 'color'), name).toBe('var(--color-primary)');
      expect(declaration(control, 'border'), name).toBe(
        'var(--border-hairline) solid var(--color-primary)',
      );
    }
  });

  it('paints nothing else with the accent', () => {
    // Counted over the whole stylesheet rather than rule by rule, so a new rule
    // — a lock badge, say — cannot introduce a second orange thing unseen.
    const accents = [...css().matchAll(/var\(--color-accent\)/g)];

    expect(accents).toHaveLength(1);
  });

  it('keeps the wait muted and the refusal destructive, never the other way round', () => {
    // The two prose lines on the screen, and the pair this file exists to hold
    // apart: red is destructive-or-failed in this system and nothing else, so a
    // routine wait painted with it reads as a failure, and a failure painted
    // muted reads as a note. The render tests read the words and the roles, so
    // both swaps are invisible to them.
    expect(declaration(rule(css(), '.pending'), 'color')).toBe('var(--color-muted-text)');
    expect(declaration(rule(css(), '.error'), 'color')).toBe('var(--color-destructive)');
  });

  it('gives the Administrator badge DESIGN.md\'s navy fill', () => {
    // `badge-role-admin`: navy fill, its own foreground, pill. Deliberately the
    // heavier of the two roles, so it reads as the weightier one at a glance.
    const badge = rule(css(), '.roleAdmin');

    expect(declaration(badge, 'background')).toBe('var(--color-primary)');
    expect(declaration(badge, 'color')).toBe('var(--color-primary-foreground)');
    expect(declaration(badge, 'border-radius')).toBe('var(--radius-full)');
  });

  it('leaves the Staff badge an outline, as DESIGN.md asks', () => {
    const badge = rule(css(), '.roleStaff');

    expect(declaration(badge, 'background')).toBe('transparent');
    expect(declaration(badge, 'color')).toBe('var(--color-muted-text)');
    expect(declaration(badge, 'border-radius')).toBe('var(--radius-full)');
  });

  it('leaves the Active badge an outline, never a fill', () => {
    // The commonest badge on the screen, and the one with the most to lose: an
    // accidental fill here paints every working account in a colour that means
    // destructive-or-revoked in this system, and the render tests — which read
    // the word — would stay green through it.
    const badge = rule(css(), '.statusActive');

    expect(declaration(badge, 'background')).toBe('transparent');
    expect(declaration(badge, 'color')).toBe('var(--color-muted-text)');
    expect(declaration(badge, 'border-radius')).toBe('var(--radius-full)');
  });

  it('gives the deactivated badge the destructive treatment', () => {
    // `badge-status-deactivated`: destructive fill, its own foreground, pill.
    // Red here is a revoked-access state, which is the one behavioural contract
    // colour carries in this system — and it is never the only signal, because
    // the badge also carries the word.
    const badge = rule(css(), '.statusOff');

    expect(declaration(badge, 'background')).toBe('var(--color-destructive)');
    expect(declaration(badge, 'color')).toBe('var(--color-destructive-foreground)');
    expect(declaration(badge, 'border-radius')).toBe('var(--radius-full)');
  });

  it('mutes a deactivated row as well as badging it', () => {
    // EXPERIENCE.md's accessibility floor: the distinction is never carried by
    // colour alone. The word on the badge is one signal and the muted row is the
    // other, and neither is the whole of it.
    expect(declaration(rule(css(), '.deactivatedRow'), 'color')).toBe('var(--color-muted-text)');
  });

  it('gives the rows DESIGN.md\'s data-table-row treatment', () => {
    // Surface background, a hairline `{colors.border}` between rows and
    // `{colors.background}` on hover — a table, not a stack of cards, and no
    // shadow anywhere on it.
    const row = rule(css(), '.row');

    expect(declaration(row, 'background')).toBe('var(--color-surface)');
    expect(declaration(row, 'border-top')).toBe(
      'var(--border-hairline) solid var(--color-border)',
    );
    expect(declaration(rule(css(), '.row:hover'), 'background')).toBe('var(--color-background)');
    expect(css()).not.toContain('box-shadow');
  });

  it('keeps the table itself scrolling instead of the page', () => {
    // The 375px case, and the one regression a render test cannot see: jsdom
    // performs no layout, so with the overflow rule deleted every cell is still
    // in the document and the page scrolls sideways on the phone this product is
    // built for.
    expect(declaration(rule(css(), '.scroller'), 'overflow-x')).toBe('auto');
  });
});

describe('the token layer declares each property once', () => {
  it('has no repeated custom property', () => {
    // Both token readers in this suite resolve a property by its first
    // declaration; the browser applies the last. A duplicate makes every
    // assertion about that token describe a value nothing renders with.
    const seen = new Map<string, number>();
    for (const [, name] of TOKENS_CSS.matchAll(/^\s*(--[A-Za-z0-9-]+)\s*:/gm)) {
      seen.set(name ?? '', (seen.get(name ?? '') ?? 0) + 1);
    }

    const repeated = [...seen].filter(([, count]) => count > 1).map(([name]) => name);

    expect(repeated, 'tokens.css declares a custom property more than once').toEqual([]);
  });
});

describe('the two numeric constraints stated in prose', () => {
  it('holds the touch-target floor at or above the platform minimum', () => {
    // Written as a bare number so this assertion does not itself trip the
    // no-raw-values guard, which matches a number only when a unit follows it.
    expect(magnitude('--touch-target-min')).toBeGreaterThanOrEqual(44);
  });

  it('keeps the app bar stripe inside the range DESIGN.md gives', () => {
    const height = magnitude('--app-bar-stripe-height');

    expect(height).toBeGreaterThanOrEqual(3);
    expect(height).toBeLessThanOrEqual(4);
  });
});

describe('the base stylesheet backs what the CSS modules compose from it', () => {
  // A fourth way the styling vanishes green. `composes: X from global` is
  // resolved by literal name: the bundler appends the string `X` to the class
  // list and never checks that any rule declares it. The module check above
  // cannot see this — global.css is not a `.module.css` — and the
  // dangling-reference check only follows `var()`. So deleting a global class
  // leaves lint, typecheck, the build and every render test green while the
  // rule it carried stops applying.
  const global = (): string => read(join(SRC, 'styles', 'global.css'));

  const composed = FILES.filter((path) => path.endsWith('.module.css')).flatMap((path) =>
    [...read(path).matchAll(/composes:\s*([^;]+?)\s+from\s+global\s*;/g)].flatMap((match) =>
      (match[1] ?? '')
        .split(/\s+/)
        .filter(Boolean)
        .map((name) => [relative(SRC, path), name] as const),
    ),
  );

  it('finds the composed class names', () => {
    expect(composed.length).toBeGreaterThan(0);
  });

  it.each(composed)('%s composes %s, which global.css declares', (_label, name) => {
    expect(rulesFor(global(), name).length).toBeGreaterThan(0);
  });

  it('holds the touch-target floor on both axes in the rule .touchTarget opts into', () => {
    // The floor is a token assertion elsewhere; this is the rule that applies
    // it. min-height alone is a 44x1 target, which is not the constraint.
    const body = rulesFor(global(), 'touchTarget')[0] ?? '';

    expect(declaration(body, 'min-height')).toBe('var(--touch-target-min)');
    expect(declaration(body, 'min-width')).toBe('var(--touch-target-min)');
  });

  it('paints a visible focus state', () => {
    // "Interactive elements carry a visible focus state" is stated in the spec
    // and implemented once, here. Nothing else would notice its removal.
    expect(declaration(rule(global(), ':focus-visible'), 'outline')).toContain('var(--color-accent)');
  });
});

describe('the entry point loads a font face for every weight the type roles ask for', () => {
  // @fontsource ships one stylesheet per weight. Drop an import, or add a type
  // role at a weight nothing imports, and the browser synthesises the face or
  // falls back — no error, no failing test, visibly wrong type.
  const MAIN = read(join(SRC, 'main.tsx'));

  /** `code` is the one monospace role; every other role is set in the sans face. */
  const MONO_ROLES = new Set(['code']);

  function weightsWanted(mono: boolean): Set<string> {
    return new Set(
      [...TOKENS_CSS.matchAll(/^\s*--type-([a-z]+)-weight:\s*([0-9]+);/gm)]
        .filter((match) => MONO_ROLES.has(match[1] ?? '') === mono)
        .map((match) => match[2] ?? ''),
    );
  }

  function weightsImported(family: string): Set<string> {
    return new Set(
      [...MAIN.matchAll(new RegExp(String.raw`@fontsource/${family}/([0-9]+)\.css`, 'g'))].map(
        (match) => match[1] ?? '',
      ),
    );
  }

  it.each([
    ['plus-jakarta-sans', false],
    ['jetbrains-mono', true],
  ] as const)('imports exactly the %s weights the token layer uses', (family, mono) => {
    // Compared as sets so neither side depends on declaration order.
    const wanted = weightsWanted(mono);

    expect(wanted.size, `no type role resolves to ${family}`).toBeGreaterThan(0);
    expect(weightsImported(family)).toEqual(wanted);
  });
});
