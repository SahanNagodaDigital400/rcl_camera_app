/**
 * @vitest-environment node
 *
 * The envelope *codes* are a contract in two languages, like `User` and
 * `ErrorEnvelope` — but unlike those two they are plain string constants with
 * no shared definition and no structural check, so nothing but this file stops
 * them drifting.
 *
 * The failure is quiet in exactly the way that matters. Rename
 * `weak_password` on the Python side and every API test still passes (they
 * import the constant), every web test still passes (they hardcode the string
 * as a stub fixture), and the screen silently stops recognising the one
 * rejection it exists to show — falling back to marking the field valid and
 * treating a refused password as a network failure.
 *
 * Read from source rather than imported: `apps/web`'s test runner cannot import
 * a Python module, and the point is to compare the two spellings that actually
 * ship.
 */
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

import {
  ACCOUNT_LOCKED,
  PASSWORD_CHANGE_NOT_REQUIRED,
  PASSWORD_CHANGE_REQUIRED,
  UNAUTHORIZED,
  WEAK_PASSWORD,
} from '../api/client';

const REPO_ROOT = fileURLToPath(new URL('../../../..', import.meta.url));
const API = join(REPO_ROOT, 'apps', 'api', 'api');

function read(path: string): string {
  return readFileSync(path, 'utf8').replace(/\r\n?/g, '\n');
}

/** The value of a module-level `NAME = "..."` assignment in a Python source file. */
function pythonConstant(source: string, name: string): string | null {
  const found = new RegExp(String.raw`^${name}\s*=\s*"([^"]*)"`, 'm').exec(source);
  return found?.[1] ?? null;
}

const PYTHON: Record<string, { file: string; name: string }> = {
  unauthorized: { file: 'dependencies.py', name: 'UNAUTHORIZED' },
  password_change_required: { file: 'dependencies.py', name: 'PASSWORD_CHANGE_REQUIRED' },
  weak_password: { file: 'auth.py', name: 'WEAK_PASSWORD' },
  password_change_not_required: { file: 'auth.py', name: 'PASSWORD_CHANGE_NOT_REQUIRED' },
  account_locked: { file: 'auth.py', name: 'ACCOUNT_LOCKED' },
};

const TYPESCRIPT: Record<string, string> = {
  unauthorized: UNAUTHORIZED,
  password_change_required: PASSWORD_CHANGE_REQUIRED,
  weak_password: WEAK_PASSWORD,
  password_change_not_required: PASSWORD_CHANGE_NOT_REQUIRED,
  account_locked: ACCOUNT_LOCKED,
};

describe('the envelope codes are one contract in two languages', () => {
  it('finds every Python constant it claims to compare', () => {
    // A parity check that silently compares against `null` passes forever. A
    // renamed or moved Python constant has to fail here as a missing constant,
    // not as a match against nothing.
    const missing = Object.entries(PYTHON)
      .filter(([, where]) => pythonConstant(read(join(API, where.file)), where.name) === null)
      .map(([code, where]) => `${where.name} in api/${where.file} (for ${code})`);

    expect(missing).toEqual([]);
  });

  it.each(Object.keys(PYTHON))('%s has the same spelling on both sides', (code) => {
    const where = PYTHON[code];
    expect(where).toBeTruthy();
    const python = pythonConstant(read(join(API, where?.file ?? '')), where?.name ?? '');

    expect(python).toBe(code);
    expect(TYPESCRIPT[code]).toBe(python);
  });

  it('compares every code the client exports', () => {
    // Two kinds of export are exempt below. The codes this app invents for
    // itself (network, timeout, malformed) have no Python twin by design —
    // they describe a request that never reached the API. `API_PREFIX` is not a
    // code at all; it is the URL prefix every request is built from, and it
    // matches the pattern only because it is an exported string constant.
    // Everything else is the API's, and a new one added to `client.ts` without
    // a row above would be unchecked.
    //
    // Matched loosely on purpose. A pattern that also pinned the quote style,
    // the trailing semicolon and the line break would drop a constant the
    // formatter rewrapped instead of reporting it — the same "compares against
    // nothing and passes forever" failure the first test in this file exists
    // to prevent, one level up. The cost of matching loosely is that every
    // exported string constant has to be accounted for by name below, which is
    // the point: a new one is a decision, not a silent omission.
    const client = read(join(fileURLToPath(new URL('..', import.meta.url)), 'api', 'client.ts'));
    const invented = new Set(['NETWORK_ERROR', 'TIMEOUT', 'MALFORMED_RESPONSE', 'API_PREFIX']);
    const exported = [...client.matchAll(/^export const ([A-Z_][A-Z0-9_]*)\s*=\s*(['"`])/gm)]
      .map((match) => match[1] ?? '')
      .filter((name) => !invented.has(name));

    expect(new Set(exported)).toEqual(
      new Set(Object.values(PYTHON).map((where) => where.name)),
    );
  });
});
