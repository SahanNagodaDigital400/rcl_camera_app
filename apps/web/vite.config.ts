/// <reference types="vitest/config" />
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
    css: false,
    restoreMocks: true,
  },
});
