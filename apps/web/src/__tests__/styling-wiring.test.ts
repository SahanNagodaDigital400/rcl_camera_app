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

  it('is the class the alert element actually carries', () => {
    // The rule above is inert if the element points somewhere else. The
    // dangling-reference check upstream proves `styles.error` resolves to a
    // declared class; this proves it is the class on the live region.
    const screen = read(join(SRC, 'screens', 'LoginScreen.tsx'));

    expect(screen).toContain('className={styles.error}');
    expect(screen).toContain('role="alert"');
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
