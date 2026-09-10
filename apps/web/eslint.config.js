import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'

// NOTE: typescript-eslint is intentionally NOT used here. TypeScript is
// pinned to 7.0.x (architecture-pinned, ARCHITECTURE-SPINE.md Stack
// table) and TS 7.0 ships no programmatic compiler API (the Microsoft
// TS7 announcement is explicit: "TypeScript 7.0 does not ship with an
// API" until 7.1). typescript-eslint's current stable line (8.70.0)
// hard-refuses to load against a TypeScript major >= 7 (see
// typescript-eslint/typescript-eslint#10940 -- no workaround exists;
// confirmed no npm alias/override can give it a separate TS6 copy
// because "typescript" is a peerDependency, which npm resolves as a
// single shared version project-wide, not per-branch).
//
// Type-level strictness (the substantive part of "no `any` without a
// comment", unused locals, etc.) is enforced by `tsc --noEmit`
// (real TS7, native compiler) in both `npm run lint` and `npm run
// build` -- see package.json. This config covers JS-level lint rules
// (unused vars, hooks rules, fast-refresh) via ESLint's default
// parser, which parses our current .tsx/.ts sources fine since none
// of them use TypeScript-only syntax (interfaces, type annotations,
// generics) yet. Revisit and reinstate typescript-eslint once it
// ships TS7 support.
export default [
  { ignores: ['dist'] },
  js.configs.recommended,
  {
    files: ['**/*.{js,jsx,ts,tsx}'],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: 'module',
      parserOptions: {
        ecmaFeatures: { jsx: true },
      },
      globals: globals.browser,
    },
    plugins: {
      'react-hooks': reactHooks,
      'react-refresh': reactRefresh,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      ...reactRefresh.configs.vite.rules,
      'no-unused-vars': 'error',
    },
  },
]
