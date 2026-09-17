/**
 * @vitest-environment node
 *
 * AGENTS.md Policy, enforced mechanically: the session token lives in an
 * HTTP-only cookie and nowhere else. No source file this app ships may read or
 * write browser storage, and none may touch `document.cookie` — an HTTP-only
 * cookie is invisible to page script by design, so any code reaching for it is
 * either reading a *different* cookie the token should never be in, or was
 * written expecting the token to be readable.
 *
 * This is broader than the token on purpose. A rule with an exception for
 * "just a UI preference" is a rule the next person reads as negotiable, and
 * the exception is where the token ends up.
 *
 * **The whole of `apps/web` is scanned, not just `src`.** Page script is not
 * only what the bundler compiles: an inline `<script>` in `index.html`, a file
 * dropped in `public/` and served verbatim, and the service worker this PWA
 * will eventually register all run on the same origin with the same access to
 * browser storage. A guard that stopped at `src` would be a guard with the
 * three most obvious places to put the token outside it.
 *
 * **Every forbidden name below is assembled from fragments**, so this file
 * does not match its own source and the check cannot pass by exempting itself.
 */
import { readFileSync, readdirSync } from 'node:fs';
import { join, relative } from 'node:path';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

/** Everything this app is built from, `src` included. See the module comment. */
const WEB_ROOT = fileURLToPath(new URL('../..', import.meta.url));

const EXTENSIONS = ['.ts', '.tsx', '.js', '.jsx', '.mjs', '.cjs', '.css', '.html'];

/**
 * Directories that hold nothing this app ships.
 *
 * `node_modules` is other people's code, and the build outputs are the same
 * source again after bundling — scanning either turns a guard about our own
 * code into a guard about a dependency's minifier.
 */
const NOT_OURS = new Set(['node_modules', 'dist', 'coverage', '.vite']);

/**
 * Assemble a forbidden name from fragments at runtime, so the literal is never
 * written down here and this file cannot match its own source.
 */
function assemble(...parts: readonly string[]): string {
  return parts.join('');
}

/** The forbidden APIs, and what each one is. */
const FORBIDDEN: readonly [string, string][] = [
  [assemble('local', 'Storage'), 'browser storage'],
  [assemble('session', 'Storage'), 'browser storage'],
  [assemble('document.', 'cookie'), 'the cookie jar'],
  [assemble('indexed', 'DB'), 'browser storage'],
  [assemble('IDB', 'Factory'), 'browser storage'],
  [assemble('Cookie', 'Store'), 'the cookie jar'],
];

interface SourceFile {
  label: string;
  code: string;
}

/**
 * Blank comment bodies, keeping every line in place.
 *
 * The rule is about what a file *does*, not what it writes down: a doc comment
 * naming the thing it forbids is not a use of it.
 */
function stripComments(text: string, isCss: boolean): string {
  const blocks = text.replace(/\/\*[\s\S]*?\*\//g, (block) => block.replace(/[^\n]/g, ' '));
  if (isCss) return blocks;
  return blocks.replace(/(^|[^:])\/\/[^\n]*/gm, (hit: string, prefix: string) =>
    prefix.concat(' '.repeat(hit.length - prefix.length)),
  );
}

function collect(dir: string, found: SourceFile[] = []): SourceFile[] {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    if (entry.isSymbolicLink()) continue;
    const path = join(dir, entry.name);
    if (entry.isDirectory()) {
      if (NOT_OURS.has(entry.name)) continue;
      collect(path, found);
      continue;
    }
    if (!EXTENSIONS.some((ext) => entry.name.endsWith(ext))) continue;

    const text = readFileSync(path, 'utf8');
    found.push({
      label: relative(WEB_ROOT, path),
      code: stripComments(text, path.endsWith('.css')),
    });
  }
  return found;
}

const FILES = collect(WEB_ROOT);

describe('the session token is never held by page script', () => {
  it('finds source files to check', () => {
    // A walk that found nothing would pass every assertion below without
    // reading a byte.
    expect(FILES.length).toBeGreaterThan(0);
  });

  it('reaches outside src, where the unbundled files live', () => {
    // The widening is the point of this guard's scope, and a walk that quietly
    // stopped at `src` again would take every assertion below with it.
    const labels = FILES.map((file) => file.label);

    expect(labels, 'the page shell is not being scanned').toContain('index.html');
    expect(labels.some((label) => !label.startsWith(join('src', '')))).toBe(true);
  });

  it.each(FORBIDDEN)('no file in apps/web uses %s', (name) => {
    const offenders = FILES.filter((file) => file.code.includes(name)).map((file) => file.label);

    expect(offenders, 'the session token belongs in an HTTP-only cookie only').toEqual([]);
  });

  it('sends no bearer credential as a header of its own', () => {
    // The cookie is attached by the browser. A header built in this app would
    // mean the token had to be readable here first. Assembled from fragments
    // like everything else above.
    const header = assemble('author', 'ization');
    const scheme = assemble('Bea', 'rer ');
    const offenders = FILES.filter(
      (file) => file.code.toLowerCase().includes(header) || file.code.includes(scheme),
    ).map((file) => file.label);

    expect(offenders).toEqual([]);
  });

  it('asks for the session cookie by asking the browser to send it', () => {
    // The positive half: `credentials` is what carries the cookie, and without
    // it every authenticated request silently goes out anonymous.
    const client = FILES.find((file) => file.label.endsWith(join('src', 'api', 'client.ts')));

    expect(client, 'src/api/client.ts is gone or renamed').toBeTruthy();
    expect(client?.code).toContain("credentials: 'same-origin'");
  });
});
