/**
 * @vitest-environment node
 *
 * The install identity — the manifest, the icons, and the links in the
 * document head that reach them — is the one part of this app no test renders
 * and no type checks. It fails silently and late: a broken icon path is a
 * grey placeholder on a staff member's home screen, discovered by the person
 * who installed it, not by CI. Four ways it can break, each closed below:
 *
 *  1. An icon is renamed, moved, or never regenerated. `vite build` copies
 *     `public/` verbatim and resolves nothing inside a manifest, so a `src`
 *     pointing at a file that does not exist builds clean and 404s on a phone.
 *  2. A declared `sizes` stops matching the file's real pixels. The browser
 *     picks an icon by its declared size and scales whatever arrives, so the
 *     only symptom is a soft or cropped icon.
 *  3. The maskable icon is dropped, or an `any` icon is relabelled `maskable`.
 *     Android then crops the mark to its own shape and cuts the wordmark in
 *     half. See `scripts/generate_brand_icons.py` for why the two families
 *     are drawn differently.
 *  4. The manifest's colours drift from the token layer. `theme_color` paints
 *     the phone's status bar and `background_color` the launch screen, so
 *     drift shows up as a flash of the wrong brand colour before the first
 *     paint — with nothing else in the app disagreeing.
 *
 * iOS ignores the manifest altogether, so the `apple-touch-icon` link is
 * checked on its own terms rather than through it.
 */
import { existsSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

const WEB_ROOT = fileURLToPath(new URL('../..', import.meta.url));
const PUBLIC_DIR = join(WEB_ROOT, 'public');

function read(path: string): string {
  return readFileSync(path, 'utf8').replace(/\r\n?/g, '\n');
}

const INDEX_HTML = read(join(WEB_ROOT, 'index.html'));
const TOKENS_CSS = read(join(WEB_ROOT, 'src', 'styles', 'tokens.css'));

/**
 * The file a root-relative URL from the manifest or the head resolves to once
 * `public/` is copied to the site root.
 */
function served(url: string): string {
  expect(url.startsWith('/'), `${url} must be root-relative`).toBe(true);
  return join(PUBLIC_DIR, url.slice(1));
}

/**
 * A PNG's real dimensions, from its IHDR header.
 *
 * Read from the bytes rather than from a decoder: the assertion is about what
 * the browser will be handed, and adding an image dependency to the front end
 * to check six static files would cost more than it guards.
 */
function pngSize(path: string): { width: number; height: number } {
  const bytes = readFileSync(path);
  const signature = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);
  expect(bytes.subarray(0, 8).equals(signature), `${path} is not a PNG`).toBe(true);
  expect(bytes.subarray(12, 16).toString('ascii'), `${path} has no IHDR`).toBe('IHDR');
  return { width: bytes.readUInt32BE(16), height: bytes.readUInt32BE(20) };
}

/** The declared value of a custom property in the token layer. */
function token(name: string): string {
  const declaration = new RegExp(`^\\s*${name}\\s*:\\s*([^;]+);`, 'm').exec(TOKENS_CSS);
  expect(declaration?.[1], `${name} is missing from tokens.css`).toBeTruthy();
  return (declaration?.[1] ?? '').trim();
}

/** The `href` of the first `<link>` carrying this `rel`. */
function linkHref(rel: string): string {
  const link = new RegExp(`<link[^>]*rel="${rel}"[^>]*>`).exec(INDEX_HTML)?.[0];
  expect(link, `index.html has no <link rel="${rel}">`).toBeTruthy();
  const href = /href="([^"]+)"/.exec(link ?? '')?.[1];
  expect(href, `<link rel="${rel}"> has no href`).toBeTruthy();
  return href ?? '';
}

/** The `content` of a named `<meta>`. */
function meta(name: string): string {
  const tag = new RegExp(`<meta[^>]*name="${name}"[^>]*>`).exec(INDEX_HTML)?.[0];
  expect(tag, `index.html has no <meta name="${name}">`).toBeTruthy();
  const content = /content="([^"]+)"/.exec(tag ?? '')?.[1];
  expect(content, `<meta name="${name}"> has no content`).toBeTruthy();
  return content ?? '';
}

interface ManifestIcon {
  src: string;
  sizes: string;
  type: string;
  purpose: string;
}

interface Manifest {
  id: string;
  name: string;
  short_name: string;
  start_url: string;
  scope: string;
  display: string;
  background_color: string;
  theme_color: string;
  icons: ManifestIcon[];
}

const MANIFEST_URL = linkHref('manifest');
const MANIFEST_PATH = served(MANIFEST_URL);
const manifest = JSON.parse(readFileSync(MANIFEST_PATH, 'utf8')) as Manifest;

describe('the manifest', () => {
  it('is served from public/, so vite build ships it', () => {
    expect(existsSync(MANIFEST_PATH), `${MANIFEST_URL} is not in public/`).toBe(true);
  });

  it('declares an installable app scoped to the whole origin', () => {
    // apps/web is one screen tree behind one entry point — App.tsx says why it
    // is not a router — so every surface lives under the one scope, and a
    // launch lands on the same root a sign-in does.
    expect(manifest.id).toBe('/');
    expect(manifest.start_url).toBe('/');
    expect(manifest.scope).toBe('/');
    expect(manifest.display).toBe('standalone');
    expect(manifest.name).toBe('Rocell Tile Scanner');
    expect(manifest.short_name.length).toBeLessThanOrEqual(12);
  });

  it('paints the status bar and the launch screen in the token colours', () => {
    expect(manifest.theme_color.toUpperCase()).toBe(token('--color-primary').toUpperCase());
    expect(manifest.background_color.toUpperCase()).toBe(
      token('--color-background').toUpperCase(),
    );
    // The head's own theme-color is what a browser tab reads before the
    // manifest is fetched; disagreeing with the manifest changes colour mid
    // load.
    expect(meta('theme-color').toUpperCase()).toBe(manifest.theme_color.toUpperCase());
  });
});

describe('the manifest icons', () => {
  it('cover both purposes at both install sizes', () => {
    const declared = manifest.icons.map((icon) => `${icon.purpose} ${icon.sizes}`);
    expect(declared).toContain('any 192x192');
    expect(declared).toContain('any 512x512');
    expect(declared).toContain('maskable 192x192');
    expect(declared).toContain('maskable 512x512');
  });

  it.each(manifest.icons.map((icon) => [icon.src, icon] as const))(
    '%s exists at the size and type it declares',
    (_src, icon) => {
      const path = served(icon.src);
      expect(existsSync(path), `${icon.src} is declared but not in public/`).toBe(true);
      expect(icon.type).toBe('image/png');

      const [width, height] = icon.sizes.split('x').map(Number);
      expect(pngSize(path)).toEqual({ width, height });
    },
  );

  it('draws a maskable icon differently from the icon of the same size', () => {
    // Same bytes for both purposes means the padded variant was never
    // generated and Android will crop the mark. Comparing the files is the
    // only check that catches a copy.
    const any = readFileSync(served('/icons/icon-512.png'));
    const masked = readFileSync(served('/icons/icon-maskable-512.png'));
    expect(masked.equals(any)).toBe(false);
  });
});

describe('the iOS install path', () => {
  it('links an apple-touch-icon at the size iOS asks for', () => {
    const path = served(linkHref('apple-touch-icon'));
    expect(existsSync(path), 'the apple-touch-icon link points at no file').toBe(true);
    expect(pngSize(path)).toEqual({ width: 180, height: 180 });
  });

  it('names the home screen shortcut and launches without browser chrome', () => {
    expect(meta('apple-mobile-web-app-title')).toBe(manifest.short_name);
    expect(meta('mobile-web-app-capable')).toBe('yes');
  });
});

describe('the favicon', () => {
  it('is linked and present, so a bare /favicon.ico request is not a 404', () => {
    expect(linkHref('icon')).toBe('/favicon.ico');
    expect(existsSync(join(PUBLIC_DIR, 'favicon.ico'))).toBe(true);
  });
});
