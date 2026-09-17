/**
 * @vitest-environment node
 *
 * UX-DR1 and UX-DR3, enforced mechanically rather than by review.
 *
 * Walks every source file under `src` and fails on a raw styling value. The
 * token layer (`src/styles/tokens.css`) is the one file allowed to hold
 * literals — it is the source everything else references — so it is the one
 * file skipped by the walk.
 *
 * Two rules about writing checks in here:
 *
 *  1. A pattern must not match this file's own source. Every one below has
 *     been checked against it; check any you add.
 *  2. A failure message must not spell out a custom-property reference in CSS
 *     syntax, because the dangling-reference check collects those from every
 *     file including this one.
 */
import { readFileSync, readdirSync } from 'node:fs';
import { join, relative } from 'node:path';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

const SRC = fileURLToPath(new URL('..', import.meta.url));
const TOKEN_LAYER = join(SRC, 'styles', 'tokens.css');
const TOKENS_CSS = readFileSync(TOKEN_LAYER, 'utf8');
// Every source extension that can carry a styling value, not only the three
// the app happens to use today: a single `.jsx` or `.mjs` file added later
// would otherwise be invisible to every check below.
const EXTENSIONS = ['.css', '.ts', '.tsx', '.js', '.jsx', '.mjs', '.cjs'];

/**
 * CSS named colours, held as one space-separated string rather than an array
 * of quoted words so the quoted-colour pattern below cannot match this list.
 */
const NAMED_COLORS =
  'white black red orange navy blue green yellow purple pink brown gray grey ' +
  'silver gold beige cyan magenta maroon olive teal lime aqua fuchsia indigo ' +
  'violet crimson coral salmon khaki tan ivory snow azure plum orchid turquoise';

const COLOR_WORDS = NAMED_COLORS.split(' ');

/** Length units. `%` is included and handled by the trailing guard, not `\b`. */
const UNITS = 'px|rem|em|vh|vw|dvh|dvw|svh|svw|lvh|lvw|ch|ex|pt|pc|cm|mm|in|q|%';

/** Units for which the value 100 means "fill", not a design decision. */
const FULL_EXTENT = new Set(['%', 'vh', 'vw', 'dvh', 'dvw', 'svh', 'svw', 'lvh', 'lvw']);

interface SourceFile {
  path: string;
  label: string;
  /** Original text, used for the failure message. */
  text: string;
  /** Text with comment bodies blanked out, line structure preserved. */
  code: string;
}

/**
 * Blank out comment bodies, keeping every line and column in place.
 *
 * The rule is about values a file *uses*, not words it writes down: a prose
 * mention of a dimension in a doc comment is not a raw value, and neither is a
 * commented-out one.
 */
function stripComments(text: string, isCss: boolean): string {
  const blocks = text.replace(/\/\*[\s\S]*?\*\//g, (block) => block.replace(/[^\n]/g, ' '));

  // CSS has no line-comment syntax, so blanking from `//` onwards there would
  // erase real declarations — `background: url(//host/x.png)` takes the rest
  // of its line with it, literals and all.
  if (isCss) return blocks;

  return blocks.replace(/(^|[^:])\/\/[^\n]*/gm, (hit: string, prefix: string) =>
    prefix.concat(' '.repeat(hit.length - prefix.length)),
  );
}

function isCssPath(path: string): boolean {
  return path.endsWith('.css');
}

function collect(dir: string, found: SourceFile[] = []): SourceFile[] {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    // A symlinked directory pointing at an ancestor would recurse until the
    // process dies. Nothing under src is a link, so skip links outright.
    if (entry.isSymbolicLink()) continue;

    const path = join(dir, entry.name);
    if (entry.isDirectory()) {
      collect(path, found);
      continue;
    }
    if (!EXTENSIONS.some((ext) => entry.name.endsWith(ext))) continue;
    if (path === TOKEN_LAYER) continue;

    const text = readFileSync(path, 'utf8');
    found.push({
      path,
      label: relative(SRC, path),
      text,
      code: stripComments(text, isCssPath(path)),
    });
  }
  return found;
}

const FILES = collect(SRC);
const CASES = FILES.map((file) => [file.label, file] as [string, SourceFile]);

function isStyleSheet(file: SourceFile): boolean {
  return isCssPath(file.path);
}

/** Blank a media query's prelude; its breakpoint has a check of its own. */
function withoutMediaPreludes(code: string): string {
  return code.replace(/@media[^{]*\{/g, (prelude) => prelude.replace(/[^\n]/g, ' '));
}

/** Report every code line of `file` matching `pattern`, optionally skipping some. */
function offences(
  file: SourceFile,
  pattern: RegExp,
  options: { code?: string; allow?: (match: RegExpExecArray) => boolean } = {},
): string[] {
  const hits: string[] = [];
  const source = file.text.split('\n');
  const allow = options.allow ?? (() => false);

  (options.code ?? file.code).split('\n').forEach((line, index) => {
    const scan = new RegExp(pattern.source, pattern.flags.includes('g') ? pattern.flags : 'g');
    let matched = scan.exec(line);
    while (matched) {
      if (!allow(matched)) {
        hits.push(`${matched[0]}  ->  ${(source[index] ?? line).trim()}`);
        break;
      }
      matched = scan.exec(line);
    }
  });

  return hits;
}

describe('no raw styling values outside the token layer', () => {
  it('finds source files to check', () => {
    expect(FILES.length).toBeGreaterThan(0);
  });

  it.each(CASES)('%s holds no colour literal', (label, file) => {
    const hex = offences(file, /#[0-9a-fA-F]{3,8}\b/);
    const functional = offences(
      file,
      /\b(?:rgba?|hsla?|hwb|lab|lch|oklab|oklch|color-mix|light-dark)\(/,
    );

    expect([...hex, ...functional], `${label} must reference a --color-* property`).toEqual([]);
  });

  it.each(CASES)('%s names no colour by keyword', (label, file) => {
    // `color: white` on accent orange is the exact 2.63:1 AA failure DESIGN.md
    // forbids, and it would sail past a hex-only check.
    //
    // Anchored at a declaration boundary rather than at the start of a line: a
    // rule written on one line puts its first declaration after `{`, so a `^`
    // anchor waved `.x { color: white; }` through untouched.
    const hits = isStyleSheet(file)
      ? offences(
          file,
          new RegExp(String.raw`(?:^|[{;])\s*[-a-z]+\s*:[^;{}]*\b(?:${COLOR_WORDS.join('|')})\b`),
        )
      : offences(file, new RegExp(`['"](?:${COLOR_WORDS.join('|')})['"]`));

    expect(hits, `${label} must reference a --color-* property`).toEqual([]);
  });

  it.each(CASES)('%s holds no dimension literal', (label, file) => {
    const hits = offences(file, new RegExp(String.raw`\b(\d+(?:\.\d+)?)(${UNITS})(?![\w%])`), {
      code: withoutMediaPreludes(file.code),
      allow: (matched) => {
        const value = Number(matched[1]);
        const unit = matched[2] ?? '';
        // Zero is zero, and 100 of a viewport unit means "fill" — neither is a
        // design decision the token layer could express better.
        return value === 0 || (value === 100 && FULL_EXTENT.has(unit));
      },
    });

    expect(hits, `${label} must reference a --space-* or --radius-* property`).toEqual([]);
  });

  it.each(CASES)('%s passes no bare number to a JSX inline style', (label, file) => {
    // React appends px to a unitless number, so style={{ padding: 8 }} is a
    // raw dimension that no CSS-shaped pattern would ever see.
    const hits: string[] = [];
    const blocks = file.code.matchAll(/style=\{\{([\s\S]*?)\}\}/g);

    for (const block of blocks) {
      const numeric = /[:,]\s*-?\d/.exec(block[1] ?? '');
      if (numeric) hits.push(`${numeric[0].trim()}  ->  ${(block[0] ?? '').trim()}`);
    }

    expect(hits, `${label} must style through a CSS module, not an inline number`).toEqual([]);
  });

  it.each(CASES.filter(([, file]) => file.path.endsWith('.tsx')))(
    '%s passes no bare dimension to a component prop',
    (label, file) => {
      // A sizing prop is the other route a dimension takes into a component
      // without ever appearing in CSS: `<Scan size={24} />` is a raw value
      // that no stylesheet-shaped pattern can see. AppBar sizes its icon from
      // a token in CSS precisely to avoid this, and until now only its comment
      // said so.
      const hits = offences(file, /\b(?:size|width|height|gap|padding|margin|radius|spacing|strokeWidth|thickness)\s*=\s*\{-?\d/);

      expect(hits, `${label} must take its dimensions from the token layer`).toEqual([]);
    },
  );

  it.each(CASES)('%s names no font family directly', (label, file) => {
    const stacks = offences(file, /font-family\s*:\s*(?!\s*var\()/);

    expect(stacks, `${label} must reference a --font-* property`).toEqual([]);
  });

  it.each(CASES)('%s uses Phosphor icons at regular weight only', (label, file) => {
    // UX-DR3: outline icons throughout. No filled, duotone, bold, thin or
    // light weight anywhere — the default weight is regular, so the correct
    // usage passes no weight at all.
    const weights = offences(file, /\bweight\s*=\s*["'{]/);

    expect(weights, `${label} must not set a Phosphor icon weight`).toEqual([]);
  });
});

describe('the one breakpoint', () => {
  const declared = /^\s*--breakpoint-md:\s*([^;]+);/m.exec(TOKENS_CSS)?.[1]?.trim();

  it('is declared in the token layer', () => {
    expect(declared, 'tokens.css no longer declares the breakpoint').toBeTruthy();
  });

  it.each(CASES.filter(([, file]) => isStyleSheet(file)))(
    '%s writes every media query at the declared breakpoint',
    (label, file) => {
      // CSS cannot read a custom property inside a media query, so the number
      // is written out. That makes it the one place the stylesheet and the
      // token layer can silently disagree — hence this check.
      //
      // Every length in a prelude is checked, whatever syntax it arrives in:
      // matching `min-width:` alone would wave through the range form
      // (`@media (width >= 900px)`), which the dimension check above cannot
      // see either because it blanks preludes wholesale.
      const lengths = new RegExp(String.raw`\b\d+(?:\.\d+)?(?:${UNITS})(?![\w%])`, 'g');
      const wrong = [...file.code.matchAll(/@media([^{]*)\{/g)]
        .flatMap((query) => [...(query[1] ?? '').matchAll(lengths)].map((hit) => hit[0]))
        .filter((width) => width !== declared);

      expect(wrong, `${label} uses a breakpoint the token layer does not declare`).toEqual([]);
    },
  );
});

describe('no dangling custom-property references', () => {
  const declaredNames = new Set(
    [...TOKENS_CSS.matchAll(/^\s*(--[A-Za-z0-9-]+)\s*:/gm)].map((match) => match[1]),
  );

  // The token layer references itself now (DEFAULT radius), so it is read for
  // references as well as declarations.
  const referencing = [...CASES, ['styles/tokens.css', { code: TOKENS_CSS }] as const];

  it('reads the declared token names', () => {
    expect(declaredNames.size).toBeGreaterThan(0);
  });

  it.each(referencing)('%s references only declared tokens', (label, file) => {
    // Renaming a token used to be completely silent: lint, typecheck and every
    // render test stayed green while the styling it drove quietly vanished.
    const referenced = [...file.code.matchAll(/var\(\s*(--[A-Za-z0-9-]+)/g)].map(
      (match) => match[1],
    );
    const dangling = [...new Set(referenced.filter((name) => !declaredNames.has(name)))];

    expect(dangling, `${label} references a token tokens.css does not declare`).toEqual([]);
  });
});
