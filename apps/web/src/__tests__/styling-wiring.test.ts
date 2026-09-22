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

/**
 * The selector group *and* the body of the first rule naming `className`.
 *
 * `rulesFor` throws the selector away, which is fine when the claim is about
 * the declarations. It is not fine when the claim is that some *other* selector
 * shares the rule — a grouped selector is the only thing carrying the rule to
 * the elements that never name the class.
 */
function ruleGroupFor(css: string, className: string): [string, string] {
  const block = [...css.matchAll(/([^{}]*)\{([^}]*)\}/g)].find((candidate) =>
    new RegExp(String.raw`(^|[\s,])\.${className}(?![\w-])`).test(candidate[1] ?? ''),
  );

  expect(block, `no rule found for .${className}`).toBeTruthy();
  // The selector capture runs from the previous `}`, so it carries whatever
  // comment sits above the rule — and these stylesheets argue for their rules
  // at length, in prose with commas in it. Stripped, so a caller may split the
  // group on `,` and get selectors rather than sentence fragments.
  return [(block?.[1] ?? '').replace(/\/\*[\s\S]*?\*\//g, '').trim(), block?.[2] ?? ''];
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

  it('colours the edit user rejection the same way', () => {
    // The newest screen to carry a rejection, and the one whose alert slot is
    // also where the unsaved-changes warning lands — the one thing on that
    // screen that can lose work. Point `.error` at `--color-text` and a refused
    // demotion, and a Back about to discard a half-typed edit, both render as
    // ordinary prose beside a form that looks fine.
    const css = read(join(SRC, 'screens', 'EditUserScreen.module.css'));

    expect(declaration(rule(css, '.error'), 'color')).toBe('var(--color-destructive)');
  });

  it('colours the add tile rejection the same way', () => {
    // The screen with four controls and one alert slot, and the one whose
    // refusals include a file the server could not read. Point `.error` at
    // `--color-text` and a corrupt reference image reads as a note beside a
    // form that looks fine.
    const css = read(join(SRC, 'screens', 'AddTileScreen.module.css'));

    expect(declaration(rule(css, '.error'), 'color')).toBe('var(--color-destructive)');
  });

  it('colours the bulk upload rejection the same way', () => {
    // The screen whose refusals are the *pre-stream* ones — an unreadable
    // manifest, a batch over the row cap, a server with no pixel pipeline. Once
    // the stream opens the status is `200` and every outcome is a row, so this
    // rule paints the only failure on the screen that is not a row: the one
    // that means the batch never started. Point `.error` at `--color-text` and
    // "nothing was uploaded" reads as a note beside a form that looks fine.
    const css = read(join(SRC, 'screens', 'BulkUploadScreen.module.css'));

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
    ['LoginScreen', join('screens', 'LoginScreen.tsx'), 'error'],
    ['ForcedPasswordChangeScreen', join('screens', 'ForcedPasswordChangeScreen.tsx'), 'error'],
    ['AccountSettingsScreen', join('screens', 'AccountSettingsScreen.tsx'), 'error'],
    ['CreateUserScreen', join('screens', 'CreateUserScreen.tsx'), 'error'],
    ['EditUserScreen', join('screens', 'EditUserScreen.tsx'), 'error'],
    ['UserListScreen', join('screens', 'UserListScreen.tsx'), 'error'],
    ['AddTileScreen', join('screens', 'AddTileScreen.tsx'), 'error'],
    ['BulkUploadScreen', join('screens', 'BulkUploadScreen.tsx'), 'error'],
    // Story 2.5's Catalogue. One alert slot, carrying the server's own
    // sentence — a refused `q`, a demotion between two requests, a dead
    // network — with no table rendered beside it.
    ['CatalogueScreen', join('screens', 'CatalogueScreen.tsx'), 'error'],
    // Widened past `screens/` by Story 1.11: the confirmation dialog is a
    // component, and its refusal state is the one alert in the product that is
    // not on a screen at all. Its alert class is `body` rather than `error`
    // because the same element carries the consequence sentence in the confirm
    // state — one node, two states, and only the refusal is announced.
    ['ConfirmDialog', join('components', 'ConfirmDialog.tsx'), 'body'],
  ])('is the class %s\'s alert element actually carries', (_label, file, className) => {
    // The rules above are inert if the element points somewhere else. The
    // dangling-reference check upstream proves the class resolves to a declared
    // one; this proves it is the class on the live region.
    //
    // **Matched on one element, not as two independent substrings.** A file may
    // carry the same class on more than one node — `ConfirmDialog` puts
    // `styles.body` on both its alert paragraph and its non-alert one — so two
    // `toContain` calls pass with the class and the role on different elements,
    // which is precisely the arrangement this check exists to catch. `[^<>]*`
    // is the "same tag" constraint: no element boundary may sit between them.
    const source = read(join(SRC, file));
    const attribute = String.raw`className=\{styles\.${className}\}`;
    const onOneElement = new RegExp(
      `(?:${attribute}[^<>]*role="alert")|(?:role="alert"[^<>]*${attribute})`,
    );

    expect(
      onOneElement.test(source),
      `${_label} must carry styles.${className} and role="alert" on the same element`,
    ).toBe(true);
  });
});

describe("the Crop screen's retake prompt paints DESIGN.md's retake-prompt block", () => {
  // Story 3.3 (FR-9/AD-12): a `scan_quality_too_low` refusal is a surface-
  // colored banner, never the destructive red the ordinary `.error` rule uses
  // — a quality gate is not the same failure category as a rejected request.
  // Point any of the three at the wrong token and the render tests (which
  // apply no stylesheet at all — `vite.config.ts` sets `css: false`) stay
  // green while the banner paints invisibly-on-white or destructive red.
  it('uses the surface background, hairline border and body text tokens', () => {
    const css = read(join(SRC, 'screens', 'CropScreen.module.css'));
    const body = rule(css, '.retakePrompt');

    expect(declaration(body, 'background')).toBe('var(--color-surface)');
    expect(declaration(body, 'border')).toContain('var(--color-border)');
    expect(declaration(body, 'color')).toBe('var(--color-text)');
  });
});

describe('the confirmation dialog paints DESIGN.md\'s confirmation-dialog block', () => {
  // The product's first modal, and the first reference to `--scrim` — declared
  // in `tokens.css` for exactly this and pointed at by nothing until now.
  // Nothing else in the suite can see any of it: `vite.config.ts` sets
  // `css: false`, so jsdom applies no stylesheet and there is no computed style
  // to read.
  const css = (): string => read(join(SRC, 'components', 'ConfirmDialog.module.css'));

  it('lays the scrim over the whole viewport in the declared scrim colour', () => {
    // A scrim the app bar sits on top of is not a scrim, so `fixed` and the
    // stacking level are as load-bearing as the colour. Point `background` at
    // any other token and the dialog floats over a fully usable page with every
    // render test still green.
    const scrim = rule(css(), '.scrim');

    expect(declaration(scrim, 'background')).toBe('var(--scrim)');
    expect(declaration(scrim, 'position')).toBe('fixed');
    expect(declaration(scrim, 'z-index')).toBe('var(--z-modal)');
  });

  it('gives the panel the surface and the sheet radius DESIGN.md names', () => {
    // `{colors.surface}` and `{rounded.lg}` — DESIGN.md reserves the large
    // radius for a full-screen sheet, which is what this becomes at phone
    // width.
    const panel = rule(css(), '.panel');

    expect(declaration(panel, 'background')).toBe('var(--color-surface)');
    expect(declaration(panel, 'border-radius')).toBe('var(--radius-lg)');
  });

  it('uses the scrim as its depth, never a second elevation tier', () => {
    // DESIGN.md's Elevation & Depth section: one tier, and a modal uses a scrim
    // instead of a heavier shadow. Counted over the whole stylesheet so a later
    // rule cannot introduce one unseen.
    expect(css()).not.toContain('box-shadow');
    expect(css()).not.toContain('--elevation-card');
  });

  it('fills the confirm control with the destructive colour and writes on it in white', () => {
    // `confirm-button: {components.button-destructive}`. White on this red is
    // 4.87:1 and passes AA; the accent would be 2.63:1 *and* the wrong meaning.
    const confirm = rule(css(), '.confirm');

    expect(declaration(confirm, 'background')).toBe('var(--color-destructive)');
    expect(declaration(confirm, 'color')).toBe('var(--color-destructive-foreground)');
    expect(declaration(confirm, 'border-radius')).toBe('var(--radius-sm)');
  });

  it('leaves Cancel the navy outline, never a second fill', () => {
    const dismiss = rule(css(), '.dismiss');

    expect(declaration(dismiss, 'background')).toBe('transparent');
    expect(declaration(dismiss, 'color')).toBe('var(--color-primary)');
    expect(declaration(dismiss, 'border')).toBe(
      'var(--border-hairline) solid var(--color-primary)',
    );
  });

  it('paints nothing with the accent', () => {
    // Orange is the one *action* a screen is for, and a dialog is not a screen.
    // An accent control here would be a second orange thing on whatever screen
    // opened it.
    expect([...css().matchAll(/var\(--color-accent\)/g)]).toHaveLength(0);
  });

  it('leaves the touch-target floor to the one rule that states it', () => {
    // Every control here is a `<button>`, and `global.css` holds buttons at
    // `--touch-target-min` on both axes. Restating it per control is how the
    // floor ends up stated in six places and enforced in five, so this asserts
    // the *absence* — the floor is one rule, and the dialog inherits it.
    expect(css()).not.toContain('--touch-target-min');

    // Which puts the whole floor on the inheritance, so the inheritance is what
    // has to be pinned — and on the half that carries it. The rule is found by
    // its `.touchTarget` class, but nothing in this dialog uses that class:
    // every control reaches the floor through the bare `button` sharing the
    // selector group. Drop `button` from it and a class-only assertion stays
    // green while every control here loses 44×44.
    const [selector, body] = ruleGroupFor(read(join(SRC, 'styles', 'global.css')), 'touchTarget');

    expect(selector.split(',').map((part) => part.trim())).toContain('button');
    expect(declaration(body, 'min-height')).toBe('var(--touch-target-min)');
  });
});

describe('the row-end verbs on the user list', () => {
  // Story 1.11's three controls per row. The screen-level describe above counts
  // accents over the whole stylesheet; this says *which* treatment each control
  // has, which is the half a count cannot make.
  const css = (): string => read(join(SRC, 'screens', 'UserListScreen.module.css'));

  it('gives Deactivate and Delete the destructive fill', () => {
    // DESIGN.md's `button-destructive`, and DESIGN.md:167's one behavioural
    // contract: red means destructive or access-revoking and nothing else. Both
    // controls also carry their verb as a word (EXPERIENCE.md:111), which is
    // what `user-list.test.tsx` asserts — the colour is never the only signal.
    const destructive = rule(css(), '.destructive');

    expect(declaration(destructive, 'background')).toBe('var(--color-destructive)');
    expect(declaration(destructive, 'color')).toBe('var(--color-destructive-foreground)');
  });

  it('leaves Activate the navy outline, never the destructive fill', () => {
    // Giving an account its access back is the opposite of destructive, and red
    // in this system has exactly one meaning. Swap this for `.destructive` and
    // every render test stays green while the undo reads as the damage.
    const activate = rule(css(), '.activate');

    expect(declaration(activate, 'background')).toBe('transparent');
    expect(declaration(activate, 'color')).toBe('var(--color-primary)');
    expect(declaration(activate, 'border')).toBe(
      'var(--border-hairline) solid var(--color-primary)',
    );
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

describe('saving is the one action on the edit user screen', () => {
  // DESIGN.md's "exactly one per screen" for the accent-filled primary, on a
  // screen that carries two buttons: Save changes takes the accent, Back is the
  // navy outline. A second orange control would make neither of them the action.
  const css = (): string => read(join(SRC, 'screens', 'EditUserScreen.module.css'));

  it('fills the submit with the accent and writes on it in navy', () => {
    const submit = rule(css(), '.submit');

    expect(declaration(submit, 'background')).toBe('var(--color-accent)');
    expect(declaration(submit, 'color')).toBe('var(--color-accent-foreground)');
  });

  it('leaves Back as the navy outline, not a second filled control', () => {
    const back = rule(css(), '.back');

    expect(declaration(back, 'color')).toBe('var(--color-primary)');
    expect(declaration(back, 'background')).toBe('transparent');
    expect(declaration(back, 'border')).toBe(
      'var(--border-hairline) solid var(--color-primary)',
    );
  });

  it('writes the save indicator in the brand primary once it has saved', () => {
    // DESIGN.md's `save-indicator`: muted while it is working, `{colors.primary}`
    // once it has — and deliberately not orange, which stays reserved for the
    // action that has not fired yet. Point `.saved` at `--color-muted-text` and
    // the two states become indistinguishable, with every render test still
    // finding "Saved."
    expect(declaration(rule(css(), '.indicator'), 'color')).toBe('var(--color-muted-text)');
    expect(declaration(rule(css(), '.saved'), 'color')).toBe('var(--color-primary)');
  });

  it('paints nothing else with the accent', () => {
    const accents = [...css().matchAll(/var\(--color-accent\)/g)];

    expect(accents).toHaveLength(1);
  });
});

describe('saving is the one action on the add tile screen', () => {
  // DESIGN.md's "exactly one per screen" for the accent-filled primary, on a
  // screen carrying two buttons, a result card and a quality flag: Save takes
  // the accent, Back is the navy outline, the card is surface-on-hairline and
  // the flag is muted. Nothing else in the suite can see any of it —
  // `vite.config.ts` sets `css: false`, so jsdom applies no stylesheet.
  const css = (): string => read(join(SRC, 'screens', 'AddTileScreen.module.css'));

  it('fills the submit with the accent and writes on it in navy', () => {
    const submit = rule(css(), '.submit');

    expect(declaration(submit, 'background')).toBe('var(--color-accent)');
    expect(declaration(submit, 'color')).toBe('var(--color-accent-foreground)');
  });

  it('leaves Back as the navy outline, not a second filled control', () => {
    const back = rule(css(), '.back');

    expect(declaration(back, 'color')).toBe('var(--color-primary)');
    expect(declaration(back, 'background')).toBe('transparent');
    expect(declaration(back, 'border')).toBe('var(--border-hairline) solid var(--color-primary)');
  });

  it('writes the save indicator in the brand primary once it has saved', () => {
    // DESIGN.md's `save-indicator`: muted while it is working,
    // `{colors.primary}` once it has — and deliberately not orange, which
    // stays reserved for the action that has not fired yet. Point `.saved` at
    // `--color-muted-text` and the two states become indistinguishable with
    // every render test still finding "Saved."
    expect(declaration(rule(css(), '.indicator'), 'color')).toBe('var(--color-muted-text)');
    expect(declaration(rule(css(), '.saved'), 'color')).toBe('var(--color-primary)');
  });

  it('gives the result panel DESIGN.md\'s card treatment', () => {
    const result = rule(css(), '.result');

    expect(declaration(result, 'background')).toBe('var(--color-surface)');
    expect(declaration(result, 'border-radius')).toBe('var(--radius-md)');
    expect(declaration(result, 'box-shadow')).toBe('var(--elevation-card)');
  });

  it('sets the Code in the monospace role, in the field and in the summary', () => {
    // DESIGN.md reserves `code` for a value read character by character, so
    // 0/O and 1/I cannot be confused. The Code is the tile's identity (AD-18)
    // and it is transcribed off a physical tile, so this has to hold while it
    // is being *typed* and not only once it is rendered back.
    expect(declaration(rule(css(), '.code'), 'font-family')).toBe('var(--font-mono)');
    expect(declaration(rule(css(), '.codeValue'), 'font-family')).toBe('var(--font-mono)');
  });

  it('keeps the quality flag muted rather than destructive', () => {
    // FR-19's flag is a property of a plain tile, not a failure of the add:
    // the tile is in the catalogue. Red here would mean the save had failed,
    // which is the one thing it did not do — and red in this system means
    // destructive-or-failed and nothing else.
    expect(declaration(rule(css(), '.flag'), 'color')).toBe('var(--color-muted-text)');
    expect(declaration(rule(css(), '.flag'), 'color')).not.toBe('var(--color-destructive)');
  });

  it('paints nothing else with the accent', () => {
    const accents = [...css().matchAll(/var\(--color-accent\)/g)];

    expect(accents).toHaveLength(1);
  });

  /**
   * Both files with their comment bodies blanked out.
   *
   * The two checks below are about what the screen *says and does*, not about
   * what it writes down: both files argue at length for the rules, naming the
   * very words the rules forbid, and prose about a rule must never trip the
   * rule — that is how a guard becomes one people work around by not writing
   * the comment. `no-raw-values.test.ts` strips comments for the same reason.
   */
  const spoken = (): string =>
    [css(), read(join(SRC, 'screens', 'AddTileScreen.tsx'))]
      .join('\n')
      .replace(/\/\*[\s\S]*?\*\//g, ' ')
      .replace(/(^|[^:])\/\/[^\n]*/g, '$1 ');

  it('never names a similarity value, in the screen or in its stylesheet', () => {
    // AD-20, as an absence. There is nothing to show one for on this surface
    // and there never will be; a class named for a score is how one arrives.
    for (const banned of ['similarity', 'confidence', 'score']) {
      expect(spoken().toLowerCase().includes(banned), banned).toBe(false);
    }
  });

  it('uses the retired words nowhere', () => {
    // AD-18 retires `Product` and `Face`: they encoded the identity model it
    // corrects, and they come back through vocabulary before they come back
    // through code. `face_number` is the one permitted survivor and this
    // screen does not render it, so neither word may appear in a class, a
    // label or a sentence the Administrator reads.
    expect(/\bproducts?\b/i.test(spoken())).toBe(false);
    expect(/\bfaces?\b/i.test(spoken())).toBe(false);
  });
});

describe('saving is the one accented action on the edit tile screen', () => {
  // DESIGN.md's "exactly one per screen" for the accent-filled primary, on a
  // screen with two stages: Find takes the accent while no tile is loaded and
  // Save takes it once one is, they are never rendered together, and the
  // stylesheet therefore holds exactly one accent rule for both of them.
  // Nothing else in the suite can see any of this — `vite.config.ts` sets
  // `css: false`, so jsdom applies no stylesheet.
  const css = (): string => read(join(SRC, 'screens', 'EditTileScreen.module.css'));

  it('fills the submit with the accent and writes on it in navy', () => {
    const submit = rule(css(), '.submit');

    expect(declaration(submit, 'background')).toBe('var(--color-accent)');
    expect(declaration(submit, 'color')).toBe('var(--color-accent-foreground)');
  });

  it('leaves Back as the navy outline, not a second filled control', () => {
    const back = rule(css(), '.back');

    expect(declaration(back, 'color')).toBe('var(--color-primary)');
    expect(declaration(back, 'background')).toBe('transparent');
    expect(declaration(back, 'border')).toBe('var(--border-hairline) solid var(--color-primary)');
  });

  it('writes the save indicator in the brand primary once it has saved', () => {
    // DESIGN.md's `save-indicator`: muted while it is working,
    // `{colors.primary}` once it has — and deliberately not orange, which
    // stays reserved for the action that has not fired yet.
    expect(declaration(rule(css(), '.indicator'), 'color')).toBe('var(--color-muted-text)');
    expect(declaration(rule(css(), '.saved'), 'color')).toBe('var(--color-primary)');
  });

  it('keeps the refusal destructive and the quality flag muted', () => {
    // The pair this file exists to hold apart: red is destructive-or-failed in
    // this system and nothing else, so FR-19's flag painted with it would read
    // as a failed save, and a refusal painted muted would read as a note. The
    // render tests read the words and the roles, so both swaps are invisible
    // to them.
    expect(declaration(rule(css(), '.error'), 'color')).toBe('var(--color-destructive)');
    expect(declaration(rule(css(), '.flag'), 'color')).toBe('var(--color-muted-text)');
    expect(declaration(rule(css(), '.flag'), 'color')).not.toBe('var(--color-destructive)');
  });

  it('gives the removal toggle the destructive treatment', () => {
    // EXPERIENCE.md's accessibility floor: a destructive action is never
    // colour-only — the control carries the word "Remove" and a checkbox — but
    // it *is* destructive-coloured, and painting it like any other label would
    // make marking an image for deletion look like ticking a preference.
    expect(declaration(rule(css(), '.remove'), 'color')).toBe('var(--color-destructive)');
    // And the marked card is outlined in the same red, as the second signal
    // beside the checked box rather than instead of it.
    expect(declaration(rule(css(), '.pending'), 'border-color')).toBe(
      'var(--color-destructive)',
    );
  });

  it('meets the touch-target floor on the removal toggle', () => {
    // The one control on this screen that is a label rather than a button, so
    // `global.css`'s floor on `button` does not reach it.
    expect(declaration(rule(css(), '.remove'), 'min-height')).toBe('var(--touch-target-min)');
  });

  it('sizes the reference thumbnails from the token, never a literal', () => {
    // `no-raw-values.test.ts` forbids a dimension literal outside `tokens.css`,
    // and this is the rule that would otherwise carry one.
    expect(rulesFor(css(), 'gallery').join('\n')).toContain('var(--thumbnail-size)');
    expect(magnitude('--thumbnail-size')).toBeGreaterThanOrEqual(
      magnitude('--touch-target-min'),
    );
  });

  it('shows the whole tile face rather than cropping it to fill', () => {
    // The reference image is what lets a member of staff verify a code they do
    // not recognise (FR-7). A `cover` crop of a square-ish tile face is a face
    // an Administrator can no longer tell from its neighbour's.
    expect(declaration(rule(css(), '.image'), 'object-fit')).toBe('contain');
  });

  it('sets the Code in the monospace role, in both stages', () => {
    // DESIGN.md reserves `code` for a value read character by character, so
    // 0/O and 1/I cannot be confused. The Code is the tile's identity (AD-18)
    // and it is transcribed off a physical tile, in the lookup field and in
    // the edit field alike.
    expect(declaration(rule(css(), '.code'), 'font-family')).toBe('var(--font-mono)');
  });

  it('gives the tile removal the destructive fill and its own foreground', () => {
    // DESIGN.md's `button-destructive`, the same treatment `UserListScreen`
    // already writes once: white on this red is 4.87:1 and passes AA. An accent
    // fill here would be a second primary action on a screen DESIGN.md allows
    // exactly one — which is what the accent count below holds.
    const destructive = rule(css(), '.destructive');

    expect(declaration(destructive, 'background')).toBe('var(--color-destructive)');
    expect(declaration(destructive, 'color')).toBe('var(--color-destructive-foreground)');
    expect(declaration(destructive, 'border-radius')).toBe('var(--radius-sm)');
  });

  it('meets the touch-target floor on the tile removal', () => {
    // Stated on the rule rather than left to `global.css`'s floor on `button`:
    // this is the one control on the screen whose press cannot be taken back,
    // so the hit area is part of the control and not of the reset.
    expect(declaration(rule(css(), '.destructive'), 'min-height')).toBe(
      'var(--touch-target-min)',
    );
  });

  it('sets the removal apart from the form it is not part of', () => {
    // Nothing in the removal section travels with Save. The separator is what
    // says so on screen, and it is a hairline in the border token rather than a
    // second surface — DESIGN.md has one elevation tier and this is not it.
    expect(declaration(rule(css(), '.removal'), 'border-top')).toBe(
      'var(--border-hairline) solid var(--color-border)',
    );
  });

  it('paints nothing else with the accent', () => {
    const accents = [...css().matchAll(/var\(--color-accent\)/g)];

    expect(accents).toHaveLength(1);
  });

  /**
   * Both files with their comment bodies blanked out.
   *
   * The two checks below are about what the screen *says and does*, not about
   * what it writes down: both files argue at length for the rules, naming the
   * very words the rules forbid, and prose about a rule must never trip the
   * rule. `no-raw-values.test.ts` strips comments for the same reason.
   */
  const spoken = (): string =>
    [css(), read(join(SRC, 'screens', 'EditTileScreen.tsx'))]
      .join('\n')
      .replace(/\/\*[\s\S]*?\*\//g, ' ')
      .replace(/(^|[^:])\/\/[^\n]*/g, '$1 ');

  it('never names a similarity value, in the screen or in its stylesheet', () => {
    // AD-20, as an absence. There is nothing to show one for on this surface
    // and there never will be; a class named for a score is how one arrives.
    for (const banned of ['similarity', 'confidence', 'score']) {
      expect(spoken().toLowerCase().includes(banned), banned).toBe(false);
    }
  });

  it('uses the retired words nowhere', () => {
    // AD-18 retires `Product` and `Face`: they encoded the identity model it
    // corrects, and they come back through vocabulary before they come back
    // through code.
    expect(/\bproducts?\b/i.test(spoken())).toBe(false);
    expect(/\bfaces?\b/i.test(spoken())).toBe(false);
  });
});

describe('uploading is the one accented action on the bulk upload screen', () => {
  // DESIGN.md's "exactly one per screen" for the accent-filled primary, on the
  // one screen in the product that also uses the accent as a *status* colour.
  // DESIGN.md:221 is explicit that this is "the only place all three brand
  // colors appear as status indicators together, since it's the one screen
  // genuinely reporting three distinct outcomes" — which makes the accent
  // budget here tighter than anywhere else, not looser: Upload is the fill, the
  // flagged row indicator is the signal, and there is no third orange thing.
  //
  // Nothing else in the suite can see any of this — `vite.config.ts` sets
  // `css: false`, so jsdom applies no stylesheet and there is no computed style
  // to read. The render tests find the words "Added", "Flagged" and "Failed"
  // whichever colours they are painted in, so swapping two of these three rules
  // is invisible to every one of them.
  const css = (): string => read(join(SRC, 'screens', 'BulkUploadScreen.module.css'));

  it('fills the submit with the accent and writes on it in navy', () => {
    const submit = rule(css(), '.submit');

    expect(declaration(submit, 'background')).toBe('var(--color-accent)');
    expect(declaration(submit, 'color')).toBe('var(--color-accent-foreground)');
  });

  it('leaves Back as the navy outline, not a second filled control', () => {
    const back = rule(css(), '.back');

    expect(declaration(back, 'color')).toBe('var(--color-primary)');
    expect(declaration(back, 'background')).toBe('transparent');
    expect(declaration(back, 'border')).toBe('var(--border-hairline) solid var(--color-primary)');
  });

  it.each([
    // DESIGN.md:144-149's `upload-report-row`, token for token:
    // `success-indicator: {colors.primary}`, `failure-indicator:
    // {colors.destructive}`, `flagged-indicator: {colors.accent}`.
    ['.created', 'var(--color-primary)'],
    ['.flagged', 'var(--color-accent)'],
    ['.failed', 'var(--color-destructive)'],
  ])('paints %s in the colour the report-row block names', (name, expected) => {
    expect(declaration(rule(css(), name), 'color')).toBe(expected);
  });

  it('never paints a flagged row as a failure', () => {
    // The swap that would be hardest to see and worst to ship. A flagged row
    // *was* created — it has a tile id and it is in the index, and the flag is
    // follow-up (AD-18) — so painting it red tells an Administrator to
    // re-upload a tile that is already in the catalogue, and painting a failure
    // orange tells them a tile landed when nothing was written for it.
    expect(declaration(rule(css(), '.flagged'), 'color')).not.toBe('var(--color-destructive)');
    expect(declaration(rule(css(), '.failed'), 'color')).not.toBe('var(--color-accent)');
  });

  it('uses the accent for the submit fill and the flagged indicator, and nothing else', () => {
    // Counted over the whole stylesheet rather than rule by rule, so a new rule
    // cannot introduce a third orange thing unseen. **Two** here rather than
    // the one every other screen's sibling test asserts, and the second one is
    // DESIGN.md:214's flagged-activity-row exception rather than a relaxation
    // of the rule: orange is a signal on a row where nothing is clickable, so
    // it cannot be mistaken for the action that has not fired yet.
    const accents = [...css().matchAll(/var\(--color-accent\)/g)];

    expect(accents).toHaveLength(2);
    expect(declaration(rule(css(), '.submit'), 'background')).toBe('var(--color-accent)');
    expect(declaration(rule(css(), '.flagged'), 'color')).toBe('var(--color-accent)');
  });

  it('keeps the progress line muted, never destructive and never accented', () => {
    // A batch in flight is a routine wait, not a failure and not an action.
    // Red here would read as something having gone wrong while rows are landing
    // perfectly well, and orange would be a second primary competing with
    // Upload — the control it sits beside.
    const indicator = rule(css(), '.indicator');

    expect(declaration(indicator, 'color')).toBe('var(--color-muted-text)');
    expect(declaration(indicator, 'color')).not.toBe('var(--color-destructive)');
    expect(declaration(indicator, 'color')).not.toBe('var(--color-accent)');
  });

  it('gives the report DESIGN.md\'s card treatment', () => {
    const report = rule(css(), '.report');

    expect(declaration(report, 'background')).toBe('var(--color-surface)');
    expect(declaration(report, 'border-radius')).toBe('var(--radius-md)');
    expect(declaration(report, 'box-shadow')).toBe('var(--elevation-card)');
  });

  it('sets the Code in the monospace role', () => {
    // DESIGN.md reserves `code` for a value read character by character, so
    // 0/O and 1/I cannot be confused. On this screen the Code is what an
    // Administrator compares against the sheet in front of them, row by row.
    expect(declaration(rule(css(), '.codeValue'), 'font-family')).toBe('var(--font-mono)');
  });

  /**
   * Both files with their comment bodies blanked out.
   *
   * The two checks below are about what the screen *says and does*, not about
   * what it writes down: both files argue at length for the rules, naming the
   * very words the rules forbid, and prose about a rule must never trip the
   * rule. `no-raw-values.test.ts` strips comments for the same reason.
   */
  const spoken = (): string =>
    [css(), read(join(SRC, 'screens', 'BulkUploadScreen.tsx'))]
      .join('\n')
      .replace(/\/\*[\s\S]*?\*\//g, ' ')
      .replace(/(^|[^:])\/\/[^\n]*/g, '$1 ');

  it('never names a similarity value, in the screen or in its stylesheet', () => {
    // AD-20, as an absence. This screen reports three discrete outcomes and no
    // degree of anything; a per-row percentage is exactly the shape a score
    // would arrive in here.
    for (const banned of ['similarity', 'confidence', 'score']) {
      expect(spoken().toLowerCase().includes(banned), banned).toBe(false);
    }
  });

  it('uses the retired words nowhere', () => {
    // AD-18 retires `Product` and `Face`: they encoded the identity model it
    // corrects, and they come back through vocabulary before they come back
    // through code. A bulk report listing "products" would be the clearest
    // possible statement of the model AD-18 rejects — one row per range rather
    // than one row per file.
    expect(/\bproducts?\b/i.test(spoken())).toBe(false);
    expect(/\bfaces?\b/i.test(spoken())).toBe(false);
  });
});

describe('the home panel\'s admin entries', () => {
  it('are outlined, never filled', () => {
    // A door on the home panel is a secondary control: the shell's landing
    // surface has no primary action of its own beyond Scan (below), and an
    // accent button here would be a second orange thing on a screen that is
    // for neither user management nor the catalogue. Since Story 1.9 the
    // first entry is Users — EXPERIENCE.md line 33's nav entry, with Create
    // user reached from its "+ Add user" (line 34) — since Story 1.13 the
    // second is the Audit log, line 38's, and since Story 2.5 the third is the
    // Catalogue, line 35's.
    //
    // **Story 2.5 replaced three entries with one, and that is the change this
    // list records.** Add tile, Edit tile and Bulk upload each had a door here
    // while there was nothing to reach them from; EXPERIENCE.md never put any
    // of them on the nav — line 36 reaches Add Tile from "+ Add Tile" or a row,
    // Edit Tile from a row alone, and line 37 reaches Bulk Upload from the
    // Catalogue. They are controls on `CatalogueScreen` now, and the accent
    // moved with the first of them: "+ Add Tile" is that screen's one filled
    // primary, which is asserted in its own block below. Keeping a door here
    // as well would ship two ways to reach one screen.
    //
    // The Catalogue door stays outlined for the reason the Audit log's does:
    // the home panel's only primary action is Scan (Story 3.1), and an orange
    // button reading "Catalogue" would compete with it.
    const app = read(join(SRC, 'App.module.css'));

    for (const name of ['.userList', '.auditLog', '.catalogue']) {
      const entry = rule(app, name);

      expect(declaration(entry, 'background'), name).toBe('transparent');
      expect(declaration(entry, 'color'), name).toBe('var(--color-primary)');
      expect(declaration(entry, 'border'), name).toBe(
        'var(--border-hairline) solid var(--color-primary)',
      );
    }
  });
});

describe('Scan is the one accent action on the home panel', () => {
  // Story 3.1: DESIGN.md's Colors section names "Scan" itself as the canonical
  // example of "the one action per screen that matters most," and it is the
  // first primary action the home panel has ever had — Users, the Audit log
  // and the Catalogue stay outlined, asserted just above. Nothing else in the
  // suite can see any of this: `vite.config.ts` sets `css: false`, so jsdom
  // applies no stylesheet and there is no computed style to read.
  const css = (): string => read(join(SRC, 'App.module.css'));

  it('fills Scan with the accent and writes on it in navy', () => {
    // Never white on orange — 2.63:1, the one contrast pair DESIGN.md bans.
    const scan = rule(css(), '.scan');

    expect(declaration(scan, 'background')).toBe('var(--color-accent)');
    expect(declaration(scan, 'color')).toBe('var(--color-accent-foreground)');
  });

  it('paints nothing else on the home panel with the accent', () => {
    // Counted over the whole stylesheet rather than rule by rule, so a new
    // rule cannot introduce a second orange thing on this panel unseen —
    // exactly the discipline every other screen's own block in this file
    // holds itself to.
    expect([...css().matchAll(/var\(--color-accent\)/g)]).toHaveLength(1);
  });
});

describe('the accent budget on the Scan screen itself', () => {
  // Two intentional, mutually exclusive uses on this screen's own stylesheet:
  // the framing-guide overlay (`framing-guide-overlay`'s accent outline) and
  // `.primary`, the one accent-filled control — "Enable camera" before a
  // grant, "Capture" after one, never both rendered together. Every other
  // screen with `--color-accent` usage in this file pins its own count the
  // same way; Scan's own module comment is why this one is two rather than
  // one.
  const css = (): string => read(join(SRC, 'screens', 'ScanScreen.module.css'));

  it('outlines the framing guide with the accent', () => {
    expect(declaration(rule(css(), '.frameGuide'), 'border')).toContain('var(--color-accent)');
  });

  it('fills the one primary control with the accent', () => {
    const primary = rule(css(), '.primary');

    expect(declaration(primary, 'background')).toBe('var(--color-accent)');
    expect(declaration(primary, 'color')).toBe('var(--color-accent-foreground)');
  });

  it('leaves Back as the navy outline, not a third accented thing', () => {
    const back = rule(css(), '.back');

    expect(declaration(back, 'color')).toBe('var(--color-primary)');
    expect(declaration(back, 'background')).toBe('transparent');
  });

  it('uses the accent only for the frame guide and the primary control', () => {
    const accents = [...css().matchAll(/var\(--color-accent\)/g)];

    expect(accents).toHaveLength(2);
  });
});

describe('Confirm Crop is the one accent action on the Crop screen', () => {
  // Story 3.2 turns the inert placeholder into the real crop editor, and
  // "Confirm Crop" is this screen's first accent action — DESIGN.md's
  // "exactly one per screen", same as every screen's own block in this file.
  // Every handle also carries an accent *border* (DESIGN.md's crop-selector
  // treatment), which is why the count below is per-control rather than a
  // bare "zero or one" the way the placeholder's own version of this test
  // read.
  const css = (): string => read(join(SRC, 'screens', 'CropScreen.module.css'));

  it('fills Confirm Crop with the accent and writes on it in navy', () => {
    const confirm = rule(css(), '.confirm');

    expect(declaration(confirm, 'background')).toBe('var(--color-accent)');
    expect(declaration(confirm, 'color')).toBe('var(--color-accent-foreground)');
  });

  it('leaves Back as the navy outline, not a second filled control', () => {
    const back = rule(css(), '.back');

    expect(declaration(back, 'color')).toBe('var(--color-primary)');
    expect(declaration(back, 'background')).toBe('transparent');
    expect(declaration(back, 'border')).toBe(
      'var(--border-hairline) solid var(--color-primary)',
    );
  });

  it('outlines the selection and every handle with the accent, never fills them', () => {
    // DESIGN.md's crop-selector block: an accent *border* on the active
    // selection and on its handles, not a fill — a filled handle would read
    // as a second accent-filled control competing with Confirm.
    const selection = rule(css(), '.selection');
    const handle = rule(css(), '.handle');

    expect(declaration(selection, 'border')).toContain('var(--color-accent)');
    expect(declaration(handle, 'border')).toContain('var(--color-accent)');
    expect(declaration(handle, 'background')).toBe('var(--color-surface)');
  });

  it('colours a failed submission the same destructive red every other screen uses', () => {
    // `a rejection is written in the colour the matrix specifies`'s own
    // pattern, one screen later: red is destructive-or-failed in this system
    // and nothing else, so a `.error` pointed at any other token would let a
    // failed submission read as ordinary prose beside a Confirm that looks
    // like it is still waiting to be pressed.
    expect(declaration(rule(css(), '.error'), 'color')).toBe('var(--color-destructive)');
  });

  it('keeps the drag hint muted, never mistaken for the failure it sits beside', () => {
    // The hint ("Drag the corners or edges to resize…") and the error share
    // this screen's one alert slot's neighbourhood, so the two must not share
    // a colour either — `--color-muted-text` is this system's one non-brand,
    // non-signal text colour, and pointed at `--color-destructive` instead the
    // hint would read as a standing warning rather than an instruction.
    expect(declaration(rule(css(), '.hint'), 'color')).toBe('var(--color-muted-text)');
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

  it('leaves the row-end Edit control an outline, not a second accent fill', () => {
    // Story 1.10's one verb on a row. An accent fill here would be one orange
    // control per account — as many as there are rows — and "+ Add user" would
    // stop being the screen's one action by being outnumbered by its own table.
    // The rule above counts accents over the whole stylesheet, so this says
    // *which* treatment the control has rather than only that it is not orange.
    const edit = rule(css(), '.edit');

    expect(declaration(edit, 'background')).toBe('transparent');
    expect(declaration(edit, 'color')).toBe('var(--color-primary)');
    expect(declaration(edit, 'border')).toBe(
      'var(--border-hairline) solid var(--color-primary)',
    );
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

describe('adding a tile is the one action on the catalogue', () => {
  // DESIGN.md's "exactly one per screen" for the accent-filled primary, on the
  // surface Story 2.5 moved three home-panel doors onto: "+ Add Tile" takes the
  // accent, and Bulk upload, Search, Back, Try again and the row-end Edit are
  // all the navy outline. Nothing else in the suite can see any of this —
  // `vite.config.ts` sets `css: false`, so jsdom applies no stylesheet and
  // there is no computed style to read.
  const css = (): string => read(join(SRC, 'screens', 'CatalogueScreen.module.css'));

  it('fills the add control with the accent and writes on it in navy', () => {
    // EXPERIENCE.md line 36 makes "+ Add Tile" the Catalogue's primary action,
    // and `App.module.css`'s old `.addTile` door said so in its own comment
    // while standing outlined on a panel that was for none of it. This is where
    // that accent landed. Never white on orange — 2.63:1, the one contrast pair
    // DESIGN.md bans.
    const add = rule(css(), '.add');

    expect(declaration(add, 'background')).toBe('var(--color-accent)');
    expect(declaration(add, 'color')).toBe('var(--color-accent-foreground)');
  });

  it('leaves every other control the navy outline', () => {
    // Bulk upload is the one worth naming: the screen behind it is the one
    // place in the product where the accent is also a *status* colour
    // (DESIGN.md:144-149), so an orange control leading to it would be the same
    // hue meaning "press this" here and "review this row" one click later.
    // Search is the next closest call — narrowing a list is not what this
    // screen is for — and the row-end Edit would be one orange control per
    // tile, as many as there are rows.
    for (const name of ['.bulk', '.back', '.submit', '.retry', '.edit']) {
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
    // cannot introduce a second orange thing unseen.
    expect([...css().matchAll(/var\(--color-accent\)/g)]).toHaveLength(1);
  });

  it('uses the destructive colour for the refusal and for nothing else', () => {
    // Red is destructive-or-failed in this system and nothing else
    // (DESIGN.md:167). This screen has no destructive action at all — removal
    // lives on Edit tile, behind a confirmation — so the failure sentence is
    // the only place it may appear.
    expect(declaration(rule(css(), '.error'), 'color')).toBe('var(--color-destructive)');
    expect([...css().matchAll(/var\(--color-destructive\)/g)]).toHaveLength(1);
  });

  it('gives the rows DESIGN.md\'s data-table-row treatment', () => {
    // Surface background, a hairline `{colors.border}` between rows and
    // `{colors.background}` on hover — a table, not a stack of cards, and no
    // shadow anywhere on it (DESIGN.md:107,212).
    const row = rule(css(), '.row');

    expect(declaration(row, 'background')).toBe('var(--color-surface)');
    expect(declaration(row, 'border-top')).toBe(
      'var(--border-hairline) solid var(--color-border)',
    );
    expect(declaration(rule(css(), '.row:hover'), 'background')).toBe('var(--color-background)');
    expect(css()).not.toContain('box-shadow');
  });

  it('keeps the cells at the admin density tier', () => {
    // DESIGN.md:190's one deliberate density split: `{spacing.2}`-`{spacing.3}`
    // within an admin table row, not the generous mobile spacing of the scan
    // flow. A render test reads the text and cannot see this.
    expect(declaration(rule(css(), '.cell'), 'padding')).toBe('var(--space-2) var(--space-3)');
  });

  it('keeps the table itself scrolling instead of the page', () => {
    // The 375px case, and the one regression a render test cannot see: jsdom
    // performs no layout, so with the overflow rule deleted every cell is still
    // in the document and the page scrolls sideways.
    expect(declaration(rule(css(), '.scroller'), 'overflow-x')).toBe('auto');
  });

  it('sizes the row thumbnail from the token and never crops it', () => {
    // `contain` rather than `cover`, and this is the one assertion that
    // protects it: a tile face cropped to fill a square is a tile face an
    // Administrator can no longer tell from its neighbour, which is the whole
    // job of the reference image on this row (FR-7).
    const image = rule(css(), '.image');

    expect(declaration(image, 'width')).toBe('var(--thumbnail-size)');
    expect(declaration(image, 'object-fit')).toBe('contain');
  });

  it('sets the code in the monospace role', () => {
    // DESIGN.md reserves `{typography.code}` for a value read character by
    // character. The Code is transcribed from a physical tile and read back to
    // a customer, so 0/O and 1/I must not be confusable — in the search box and
    // in the cell alike.
    for (const name of ['.code', '.codeCell']) {
      expect(declaration(rule(css(), name), 'font-family'), name).toBe('var(--font-mono)');
    }
  });
});

describe('the audit log is a record, not a surface with an action', () => {
  // DESIGN.md's `audit-log-row`, which is `data-table-row` minus one key — and
  // that one absence is the whole distinction between the two components. The
  // render tests read words and roles, so every claim below is invisible to
  // them: `vite.config.ts` sets `css: false`, and jsdom applies no stylesheet.
  const css = (): string => read(join(SRC, 'screens', 'AuditLogScreen.module.css'));

  it('gives the rows DESIGN.md\'s audit-log-row treatment', () => {
    // Surface background, a hairline `{colors.border}` between rows, and
    // **`{colors.muted-text}`** as the foreground — deliberately not
    // `{colors.text}`, which is what `data-table-row` uses. DESIGN.md:212: the
    // audit row is visually identical to a data table row and deliberately
    // unremarkable.
    const row = rule(css(), '.row');

    expect(declaration(row, 'background')).toBe('var(--color-surface)');
    expect(declaration(row, 'border-top')).toBe(
      'var(--border-hairline) solid var(--color-border)',
    );
    expect(declaration(row, 'color')).toBe('var(--color-muted-text)');
  });

  it('declares no hover rule at all, and no card shadow', () => {
    // The visual half of EXPERIENCE.md:75. `audit-log-row` has no
    // `background-hover` key where `data-table-row` does, because nothing on
    // this row is clickable — a hover tint is an affordance with nothing
    // behind it. Asserted over the whole stylesheet rather than over `.row`,
    // so a hover added to any other selector fails here too.
    expect(css()).not.toContain(':hover');
    expect(css()).not.toContain('box-shadow');
  });

  it('paints nothing at all with the accent', () => {
    // **Zero, not one.** DESIGN.md's rule is one accent-filled primary action
    // per screen; this screen has no primary action, because it is a record.
    // Painting Load more orange would make "fetch fifty more rows" the most
    // important thing on an Administrator's security surface. Counted over the
    // whole stylesheet, so a new rule cannot introduce one unseen.
    expect([...css().matchAll(/var\(--color-accent\)/g)]).toHaveLength(0);
  });

  it('leaves Back, Try again and Load more as the navy outline', () => {
    for (const name of ['.back', '.retry', '.more']) {
      const control = rule(css(), name);

      expect(declaration(control, 'background'), name).toBe('transparent');
      expect(declaration(control, 'color'), name).toBe('var(--color-primary)');
      expect(declaration(control, 'border'), name).toBe(
        'var(--border-hairline) solid var(--color-primary)',
      );
    }
  });

  it('keeps the wait muted and the refusal destructive, never the other way round', () => {
    // Red is destructive-or-failed in this system and nothing else, so a
    // routine wait painted with it reads as a failure, and a failure painted
    // muted reads as a note. Both swaps are invisible to the render tests.
    expect(declaration(rule(css(), '.pending'), 'color')).toBe('var(--color-muted-text)');
    expect(declaration(rule(css(), '.error'), 'color')).toBe('var(--color-destructive)');
  });

  it('keeps the table itself scrolling instead of the page', () => {
    // The 375px case, and the one regression a render test cannot see: jsdom
    // performs no layout, so with the overflow rule deleted every cell is
    // still in the document and the page scrolls sideways on a phone.
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
