/// <reference types="vitest/config" />
import { readFileSync, existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

/**
 * Where apps/api is listening. The Makefile's `API_PORT` is overridable
 * (`make dev API_PORT=9000`), so hardcoding 8000 here would start the API on
 * one port, health-check it there, and then proxy the front end to a port
 * nothing is listening on. `make dev` exports this.
 */
const API_PORT = process.env['API_PORT'];
const API_ORIGIN = `http://127.0.0.1:${API_PORT && /^\d+$/.test(API_PORT) ? API_PORT : '8000'}`;

/**
 * Dev TLS, when `make certs` has produced a certificate on this machine.
 *
 * The session cookie is `Secure` with no development exemption (AGENTS.md
 * Policy, and `api/sessions.py` says why). Chrome and Firefox exempt
 * `http://localhost` from the `Secure` requirement, so plain HTTP worked there
 * — but **Safari does not**: it drops the cookie without a word, and the only
 * symptom is that every request after a successful sign-in answers `401`. The
 * forced password change is where it bites first, because that is the first
 * authenticated write anyone makes after a first sign-in.
 *
 * Serving the dev origin over HTTPS fixes it for every browser instead of
 * weakening the flag for one. It is also what a handset needs twice over: a
 * LAN IP is not a trustworthy origin, so the cookie is discarded there by every
 * browser, and `getUserMedia` — the whole point of this app — refuses to run
 * outside a secure context.
 *
 * Absent certs this is `undefined` and the dev server falls back to HTTP, so a
 * fresh checkout, CI and `vitest` all behave exactly as before.
 */
const CERT_DIR = fileURLToPath(new URL('./certs', import.meta.url));
const KEY_PATH = `${CERT_DIR}/server.key`;
const CRT_PATH = `${CERT_DIR}/server.crt`;
const https =
  existsSync(KEY_PATH) && existsSync(CRT_PATH)
    ? { key: readFileSync(KEY_PATH), cert: readFileSync(CRT_PATH) }
    : undefined;

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      // The TypeScript half of shared/schema — one contract in two languages.
      '@rocell/schema': fileURLToPath(
        new URL('../../shared/schema/shared_schema/ts', import.meta.url),
      ),
    },
  },
  server: {
    https,
    // AD-6: apps/web talks to nothing but apps/api. In dev that is this proxy;
    // in production it is a same-origin path. No other host is ever contacted,
    // and no database or storage credential exists in this app.
    proxy: {
      '/api': {
        target: API_ORIGIN,
        changeOrigin: true,
        rewrite: (path: string) => path.replace(/^\/api/, ''),
      },
    },
  },
  test: {
    environment: 'jsdom',
    include: ['src/**/*.test.ts', 'src/**/*.test.tsx'],
    // Runs before every test file; see the file's own comment for why the
    // Testing Library async budget is raised for this parallel suite.
    setupFiles: ['./src/test-setup.ts'],
    css: false,
    restoreMocks: true,
  },
});
