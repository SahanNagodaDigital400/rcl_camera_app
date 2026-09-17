/**
 * @vitest-environment node
 *
 * The token contract, asserted against its source rather than against a copy.
 *
 * This test re-reads DESIGN.md's YAML frontmatter and checks that every value
 * in it is declared in `src/styles/tokens.css`. It deliberately holds no
 * literal token values of its own: a transcription error in tokens.css and a
 * drift in DESIGN.md both surface here, and this file stays subject to the
 * no-raw-values guard like every other file under `src`.
 */
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

/** Read a file with line endings normalised — a CRLF checkout must not fail. */
function read(url: URL): string {
  return readFileSync(fileURLToPath(url), 'utf8').replace(/\r\n?/g, '\n');
}

const TOKENS_CSS = read(new URL('../styles/tokens.css', import.meta.url));

const DESIGN_MD = read(
  new URL(
    '../../../../_bmad-output/planning-artifacts/ux-designs/ux-rcl_camera_app-2026-09-08/DESIGN.md',
    import.meta.url,
  ),
);

type Section = Record<string, string | Record<string, string>>;

function unquote(value: string): string {
  return value.trim().replace(/^['"]/, '').replace(/['"]$/, '');
}

function frontmatter(markdown: string): string {
  const matched = /^---\n([\s\S]*?)\n---/.exec(markdown);
  if (!matched?.[1]) {
    throw new Error('DESIGN.md has no YAML frontmatter to read tokens from.');
  }
  return matched[1];
}

/** Read one top-level frontmatter section, one or two levels deep. */
function readSection(name: string): Section {
  const lines = frontmatter(DESIGN_MD).split('\n');
  const start = lines.indexOf(`${name}:`);
  if (start < 0) {
    throw new Error(`DESIGN.md frontmatter has no "${name}" section.`);
  }

  const section: Section = {};
  let nested: string | null = null;

  for (let i = start + 1; i < lines.length; i += 1) {
    const line = lines[i] ?? '';
    if (line.trim() === '') continue;
    if (!line.startsWith('  ')) break;

    const deep = /^ {4}([^:\s]+):\s*(.*)$/.exec(line);
    if (deep?.[1] && nested) {
      (section[nested] as Record<string, string>)[unquote(deep[1])] = unquote(deep[2] ?? '');
      continue;
    }

    const shallow = /^ {2}([^:\s]+):\s*(.*)$/.exec(line);
    if (!shallow?.[1]) continue;

    const key = unquote(shallow[1]);
    const value = (shallow[2] ?? '').trim();
    if (value === '') {
      nested = key;
      section[key] = {};
    } else {
      nested = null;
      section[key] = unquote(value);
    }
  }

  return section;
}

/**
 * The declared value of a custom property in tokens.css, or null.
 *
 * A token may point at another token (DESIGN.md's DEFAULT radius is md), so
 * references are followed to the literal they resolve to.
 */
function token(name: string, seen: ReadonlySet<string> = new Set()): string | null {
  const escaped = name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const matched = new RegExp(`^\\s*${escaped}\\s*:\\s*([^;]+);`, 'm').exec(TOKENS_CSS);
  const value = matched?.[1]?.trim();
  if (value === undefined) return null;

  const reference = /^var\(\s*(--[A-Za-z0-9-]+)\s*\)$/.exec(value);
  if (!reference?.[1]) return value;
  if (seen.has(name)) throw new Error(`tokens.css has a circular reference at ${name}`);

  return token(reference[1], new Set([...seen, name]));
}

function scalars(section: Section): Array<[string, string]> {
  return Object.entries(section).filter((entry): entry is [string, string] => {
    return typeof entry[1] === 'string';
  });
}

const colors = readSection('colors');
const typography = readSection('typography');
const rounded = readSection('rounded');
const spacing = readSection('spacing');

describe('colors', () => {
  it('declares all eleven DESIGN.md colors', () => {
    expect(scalars(colors)).toHaveLength(11);
  });

  it.each(scalars(colors))('--color-%s matches DESIGN.md', (name, value) => {
    expect(token(`--color-${name}`), `--color-${name} is missing from tokens.css`).toBe(value);
  });

  it("the accent's foreground is navy, never white", () => {
    // White on accent orange is 2.63:1 and fails AA; navy is 5.94:1 and passes.
    // Asserted as an identity against the primary (navy) token so this test
    // still holds no literal of its own.
    expect(token('--color-accent-foreground')).toBe(token('--color-primary'));
  });
});

describe('typography', () => {
  const roles = Object.entries(typography).filter(
    (entry): entry is [string, Record<string, string>] => typeof entry[1] === 'object',
  );

  it('declares all six DESIGN.md type roles', () => {
    expect(roles).toHaveLength(6);
  });

  it.each(roles)('--type-%s-* matches DESIGN.md', (role, spec) => {
    expect(token(`--type-${role}-size`), `--type-${role}-size is missing`).toBe(spec['fontSize']);
    expect(token(`--type-${role}-weight`), `--type-${role}-weight is missing`).toBe(
      spec['fontWeight'],
    );
    expect(token(`--type-${role}-line`), `--type-${role}-line is missing`).toBe(spec['lineHeight']);

    const tracking = spec['letterSpacing'];
    if (tracking !== undefined) {
      expect(token(`--type-${role}-tracking`), `--type-${role}-tracking is missing`).toBe(tracking);
    }
  });

  it.each([
    ['--font-sans', 'display'],
    ['--font-mono', 'code'],
  ])('%s names its DESIGN.md family and a non-empty fallback stack', (name, role) => {
    const stack = token(name);
    const family = (typography[role] as Record<string, string>)['fontFamily'];

    expect(stack, `${name} is missing from tokens.css`).not.toBeNull();
    expect(family).toBeTruthy();

    const families = (stack ?? '').split(',').map((part) => unquote(part));
    expect(families[0], `${name} must lead with ${String(family)}`).toBe(family);
    // UX-DR2: a self-hosted family that has not loaded must still fall back.
    expect(families.slice(1).filter(Boolean).length, `${name} declares no fallback`).toBeGreaterThan(
      0,
    );
  });
});

describe('radii', () => {
  it('declares every DESIGN.md radius, with DEFAULT as the bare --radius', () => {
    for (const [name, value] of scalars(rounded)) {
      const custom = name === 'DEFAULT' ? '--radius' : `--radius-${name}`;
      expect(token(custom), `${custom} is missing from tokens.css`).toBe(value);
    }
    expect(scalars(rounded)).toHaveLength(5);
  });
});

describe('spacing', () => {
  it('declares all ten DESIGN.md spacing steps', () => {
    expect(scalars(spacing)).toHaveLength(10);
  });

  it.each(scalars(spacing))('--space-%s matches DESIGN.md', (step, value) => {
    expect(token(`--space-${step}`), `--space-${step} is missing from tokens.css`).toBe(value);
  });
});

describe('elevation', () => {
  it('declares the one navy-tinted shadow from DESIGN.md', () => {
    // Read out of the Elevation & Depth section specifically, so a backticked
    // span elsewhere in the document cannot be mistaken for the shadow.
    const section = /\n## Elevation & Depth\n([\s\S]*?)(?:\n## |$)/.exec(DESIGN_MD);
    expect(section?.[1], 'DESIGN.md no longer has an Elevation & Depth section').toBeTruthy();

    const declared = /`(0 [^`]*\brgba\([^)]*\))`/.exec(section?.[1] ?? '');
    expect(declared?.[1], 'DESIGN.md no longer states an elevation shadow').toBeTruthy();
    expect(token('--elevation-card')).toBe(declared?.[1]);
  });
});
