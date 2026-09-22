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
 *
 * The same machinery pins two more kinds of contract further down: the request
 * *bounds* the admin forms mirror onto their inputs, and the one refusal
 * *sentence* a screen states in its own words before asking the server. Neither
 * of those two is a code, but all three are the same shape of problem — a value
 * written down twice in two languages with nothing structural holding the
 * copies together — and the same reading of the two sources is what stops them
 * drifting.
 */
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

import {
  ACCOUNT_LOCKED,
  ADMINISTRATOR_REQUIRED,
  CODE_ALREADY_EXISTS,
  EMAIL_ALREADY_EXISTS,
  IMAGE_NOT_FOUND,
  IMAGE_NOT_PAIRED,
  IMAGE_TOO_LARGE,
  IMAGE_UNMATCHED,
  INVALID_CATEGORY,
  INVALID_CODE,
  INVALID_CROP_RECT,
  INVALID_CURRENT_PASSWORD,
  INVALID_EMAIL,
  INVALID_IMAGE,
  INVALID_MANIFEST,
  INVALID_QUERY,
  INVALID_SIZE,
  LAST_ADMINISTRATOR,
  LAST_REFERENCE_IMAGE,
  MATCHING_UNAVAILABLE,
  PASSWORD_CHANGE_NOT_REQUIRED,
  PASSWORD_CHANGE_REQUIRED,
  PIPELINE_STAMP_MISMATCH,
  ROW_FAILED,
  TILE_NOT_FOUND,
  TOO_MANY_IMAGES,
  TOO_MANY_ROWS,
  UNAUTHORIZED,
  UNREADABLE_IMAGE,
  USER_NOT_FOUND,
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

/** The value of a module-level `NAME = 123` assignment in a Python source file. */
function pythonInteger(source: string, name: string): number | null {
  const found = new RegExp(String.raw`^${name}\s*=\s*(\d+)\s*$`, 'm').exec(source);
  // `exec` answers `null`, never `undefined`, for no match — written as `null`
  // so the next reader does not take the check for dead code and "simplify" it
  // into `found[1]`, which throws instead of returning the `null` the callers
  // assert on.
  return found === null || found[1] === undefined ? null : Number(found[1]);
}

/** The value of a module-level `const NAME = 123;` declaration in a TypeScript source file. */
function typescriptInteger(source: string, name: string): number | null {
  const found = new RegExp(String.raw`^const ${name}\s*=\s*(\d+);`, 'm').exec(source);
  return found === null || found[1] === undefined ? null : Number(found[1]);
}

/**
 * Every string literal in a fragment of source, concatenated.
 *
 * A sentence long enough to matter is written as adjacent literals across two
 * lines in Python and as `'…' + '…'` in TypeScript, and both are one value.
 * Joining the parts is what lets the two be compared as the sentence they
 * become rather than as the lines they happen to be wrapped into — so a
 * reflow on either side is not a failure and a reword is.
 */
function joinLiterals(body: string, quote: string): string | null {
  const parts = [...body.matchAll(new RegExp(`${quote}([^${quote}]*)${quote}`, 'g'))].map(
    (match) => match[1] ?? '',
  );
  return parts.length === 0 ? null : parts.join('');
}

/** The value of a module-level `NAME = (\n "…"\n "…"\n)` assignment in Python. */
function pythonSentence(source: string, name: string): string | null {
  const found = new RegExp(String.raw`^${name}\s*=\s*\(([\s\S]*?)\)\s*$`, 'm').exec(source);
  const body = found?.[1];
  return body === undefined ? null : joinLiterals(body, '"');
}

/** The value of a module-level `const NAME = '…' + '…';` declaration in TypeScript. */
function typescriptSentence(source: string, name: string): string | null {
  const found = new RegExp(String.raw`^const ${name}\s*=\s*([\s\S]*?);$`, 'm').exec(source);
  const body = found?.[1];
  return body === undefined ? null : joinLiterals(body, "'");
}

const PYTHON: Record<string, { file: string; name: string }> = {
  unauthorized: { file: 'dependencies.py', name: 'UNAUTHORIZED' },
  administrator_required: { file: 'dependencies.py', name: 'ADMINISTRATOR_REQUIRED' },
  password_change_required: { file: 'dependencies.py', name: 'PASSWORD_CHANGE_REQUIRED' },
  weak_password: { file: 'auth.py', name: 'WEAK_PASSWORD' },
  password_change_not_required: { file: 'auth.py', name: 'PASSWORD_CHANGE_NOT_REQUIRED' },
  account_locked: { file: 'auth.py', name: 'ACCOUNT_LOCKED' },
  invalid_current_password: { file: 'auth.py', name: 'INVALID_CURRENT_PASSWORD' },
  invalid_email: { file: 'users.py', name: 'INVALID_EMAIL' },
  email_already_exists: { file: 'users.py', name: 'EMAIL_ALREADY_EXISTS' },
  user_not_found: { file: 'users.py', name: 'USER_NOT_FOUND' },
  last_administrator: { file: 'users.py', name: 'LAST_ADMINISTRATOR' },
  // Epic 2's catalogue routes. Nineteen codes rather than one generic
  // `validation_error`, because the screen decides which of its controls to
  // mark from the code alone — eleven from Story 2.1's add and image read, two
  // more from Story 2.2's edit and lookup, five from Story 2.4's bulk upload,
  // and one from Story 2.5's catalogue search.
  //
  // Story 2.5's `invalid_query` is deliberately *not* `invalid_code` reused: a
  // query is not a Code, a blank one browses the whole catalogue rather than
  // being refused, and a screen marking its search box from the add form's
  // code refusal would be marking it for a rule it does not have. The search
  // adds no numeric bound of its own, so there is no `BOUNDS` row below for
  // it — `q` is bounded by `MAX_CODE_LENGTH`, which already has one.
  //
  // Story 2.4's five are not all the same kind of thing, and the map
  // deliberately does not distinguish them: `invalid_manifest` and
  // `too_many_rows` arrive as ordinary envelopes under a `422` before the
  // stream opens, while `image_not_paired`, `image_unmatched` and `row_failed`
  // arrive *inside* a report line's `error` object, under a `200`. What this
  // file pins is the spelling, and a per-row code that drifted would be exactly
  // as invisible as an envelope code that did — more so, since no status
  // carries it.
  invalid_code: { file: 'catalogue.py', name: 'INVALID_CODE' },
  invalid_size: { file: 'catalogue.py', name: 'INVALID_SIZE' },
  invalid_query: { file: 'catalogue.py', name: 'INVALID_QUERY' },
  invalid_category: { file: 'catalogue.py', name: 'INVALID_CATEGORY' },
  invalid_image: { file: 'catalogue.py', name: 'INVALID_IMAGE' },
  unreadable_image: { file: 'catalogue.py', name: 'UNREADABLE_IMAGE' },
  image_too_large: { file: 'catalogue.py', name: 'IMAGE_TOO_LARGE' },
  too_many_images: { file: 'catalogue.py', name: 'TOO_MANY_IMAGES' },
  code_already_exists: { file: 'catalogue.py', name: 'CODE_ALREADY_EXISTS' },
  matching_unavailable: { file: 'catalogue.py', name: 'MATCHING_UNAVAILABLE' },
  pipeline_stamp_mismatch: { file: 'catalogue.py', name: 'PIPELINE_STAMP_MISMATCH' },
  image_not_found: { file: 'catalogue.py', name: 'IMAGE_NOT_FOUND' },
  tile_not_found: { file: 'catalogue.py', name: 'TILE_NOT_FOUND' },
  last_reference_image: { file: 'catalogue.py', name: 'LAST_REFERENCE_IMAGE' },
  invalid_manifest: { file: 'catalogue.py', name: 'INVALID_MANIFEST' },
  too_many_rows: { file: 'catalogue.py', name: 'TOO_MANY_ROWS' },
  image_not_paired: { file: 'catalogue.py', name: 'IMAGE_NOT_PAIRED' },
  image_unmatched: { file: 'catalogue.py', name: 'IMAGE_UNMATCHED' },
  row_failed: { file: 'catalogue.py', name: 'ROW_FAILED' },
  // Story 3.2's one — the crop-only `POST /scans` router's own module.
  invalid_crop_rect: { file: 'scan.py', name: 'INVALID_CROP_RECT' },
};

const TYPESCRIPT: Record<string, string> = {
  unauthorized: UNAUTHORIZED,
  administrator_required: ADMINISTRATOR_REQUIRED,
  password_change_required: PASSWORD_CHANGE_REQUIRED,
  weak_password: WEAK_PASSWORD,
  password_change_not_required: PASSWORD_CHANGE_NOT_REQUIRED,
  account_locked: ACCOUNT_LOCKED,
  invalid_current_password: INVALID_CURRENT_PASSWORD,
  invalid_email: INVALID_EMAIL,
  email_already_exists: EMAIL_ALREADY_EXISTS,
  user_not_found: USER_NOT_FOUND,
  last_administrator: LAST_ADMINISTRATOR,
  invalid_code: INVALID_CODE,
  invalid_size: INVALID_SIZE,
  invalid_query: INVALID_QUERY,
  invalid_category: INVALID_CATEGORY,
  invalid_image: INVALID_IMAGE,
  unreadable_image: UNREADABLE_IMAGE,
  image_too_large: IMAGE_TOO_LARGE,
  too_many_images: TOO_MANY_IMAGES,
  code_already_exists: CODE_ALREADY_EXISTS,
  matching_unavailable: MATCHING_UNAVAILABLE,
  pipeline_stamp_mismatch: PIPELINE_STAMP_MISMATCH,
  image_not_found: IMAGE_NOT_FOUND,
  tile_not_found: TILE_NOT_FOUND,
  last_reference_image: LAST_REFERENCE_IMAGE,
  invalid_manifest: INVALID_MANIFEST,
  too_many_rows: TOO_MANY_ROWS,
  image_not_paired: IMAGE_NOT_PAIRED,
  image_unmatched: IMAGE_UNMATCHED,
  row_failed: ROW_FAILED,
  invalid_crop_rect: INVALID_CROP_RECT,
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

  it('compares every code the API can emit', () => {
    // The other direction, and the one that was missing: the test above
    // accounts for every constant `client.ts` exports, so a code added on the
    // Python side with no TypeScript twin was simply absent from both maps and
    // therefore unchecked — which is how `pipeline_stamp_mismatch` and
    // `image_not_found` shipped without a name here.
    //
    // An envelope code is recognised by the property every one of them has and
    // no message constant does: the value is exactly the constant's own name,
    // lowercased. `CODE_UNIQUE_INDEX = "tile_code_key"` and the refusal
    // sentences are not codes and do not match.
    const routers = ['auth.py', 'catalogue.py', 'dependencies.py', 'scan.py', 'users.py'];
    const declared = routers.flatMap((file) =>
      [...read(join(API, file)).matchAll(/^([A-Z_][A-Z0-9_]*)\s*=\s*"([a-z0-9_]+)"/gm)]
        .filter((match) => match[1]?.toLowerCase() === match[2])
        .map((match) => match[2] ?? ''),
    );

    const unaccounted = declared.filter((code) => !(code in PYTHON));

    expect(unaccounted).toEqual([]);
  });
});

/**
 * The refusal sentences a screen states in its own words.
 *
 * Everywhere else in the product a refusal is rendered from the API's own
 * message: the request is made, the envelope comes back, and the screen paints
 * whatever sentence it carries. Two screens have an exception, and both are
 * deliberate and the same one. EXPERIENCE.md:148 asks for a refusal that was
 * never going to be honoured to *replace* the confirmation dialog rather than
 * follow it — Story 1.11's last-Administrator deactivation, and Story 2.2's
 * save that would leave a tile with no reference image — which can only be
 * decided **before** a request is made, so on those paths no envelope ever
 * arrives and the screen's own copy is the only sentence the Administrator
 * sees.
 *
 * That is the failure this file exists to prevent, in its purest form. Reword
 * the Python constant and every web test still passes while the pre-flight goes
 * on stating the rule in words the server no longer uses — and the behavioural
 * test in `deactivate-delete-user.test.tsx` cannot catch it, because it
 * compares one TypeScript literal against another. This is the row that closes
 * the chain: Python constant ↔ screen constant, with the behavioural test's own
 * literal pinned against the rendered output at the far end of it.
 *
 * Compared as sentences rather than as source lines — see `joinLiterals` — so a
 * reflow on either side is not a failure.
 */
const USER_LIST_SCREEN = 'UserListScreen.tsx';
// Declared here rather than with the three below, because `SENTENCES` reads it
// and `BOUNDS` further down reads it too — a `const` is not hoisted, so the
// first reader is where it has to live.
const EDIT_TILE_SCREEN = 'EditTileScreen.tsx';

const SENTENCES: {
  screen: string;
  python: { file: string; name: string };
  typescript: string;
}[] = [
  {
    screen: USER_LIST_SCREEN,
    python: { file: 'users.py', name: 'LAST_ACTIVE_ADMINISTRATOR' },
    typescript: 'LAST_ACTIVE_ADMINISTRATOR',
  },
  // Story 2.2's floor (FR-7). The Edit tile screen refuses a save whose net
  // effect is zero reference images *instead of* confirming it, so this
  // sentence is stated before any request — and the server still answers the
  // same one as `409 last_reference_image` if the check is ever wrong, which is
  // exactly why the two spellings have to be held together.
  {
    screen: EDIT_TILE_SCREEN,
    python: { file: 'catalogue.py', name: 'LAST_IMAGE' },
    typescript: 'MUST_KEEP_AN_IMAGE',
  },
];

describe('the one refusal a screen states before asking the server', () => {
  it.each(SENTENCES.map((row) => [`${row.screen}: ${row.typescript}`, row] as const))(
    '%s is the same sentence on both sides',
    (_name, row) => {
      const python = pythonSentence(read(join(API, row.python.file)), row.python.name);
      const typescript = typescriptSentence(read(screenPath(row.screen)), row.typescript);

      // Both halves asserted non-null first, for the reason the codes above
      // give: a comparison of `null` with `null` passes forever, so a renamed
      // or moved constant has to fail here as a missing one rather than as a
      // match against nothing.
      expect(python, `${row.python.name} is missing from api/${row.python.file}`).not.toBeNull();
      expect(typescript, `${row.typescript} is missing from ${row.screen}`).not.toBeNull();
      expect(typescript).toBe(python);
    },
  );
});

/**
 * The request bounds the two admin forms mirror onto their inputs.
 *
 * Each screen writes the server's bounds down a second time, in TypeScript, and
 * renders them as `maxLength` so that the one refusal it cannot act on — the
 * generic `422 validation_error`, which names no field, so nothing is marked and
 * nothing is focused — never has to be shown. `create-user.test.tsx` and
 * `edit-user.test.tsx` assert the attribute matches their screen's constant;
 * this asserts each screen's constant matches the server's. Without both halves
 * the tests named "bounds the field the way the server bounds it" compare one
 * TypeScript literal against another and would pass with the Python bound set to
 * anything at all.
 *
 * **The screen is per row, not one path for the whole table.** Story 1.10 added
 * a second screen with its own mirrored bounds; with a single `SCREEN` constant
 * those two literals would be compared against nothing at all, which is the
 * "passes forever" failure this file exists to prevent.
 */
function screenPath(file: string): string {
  return join(fileURLToPath(new URL('..', import.meta.url)), 'screens', file);
}

const CREATE_USER_SCREEN = 'CreateUserScreen.tsx';
const EDIT_USER_SCREEN = 'EditUserScreen.tsx';
const ADD_TILE_SCREEN = 'AddTileScreen.tsx';
const BULK_UPLOAD_SCREEN = 'BulkUploadScreen.tsx';

/**
 * Where a bound's Python twin lives, when it is not in `apps/api/api`.
 *
 * Story 2.1's bounds are in `shared/schema`, not in the route module: `Tile`
 * is a contract both `apps/api` and `scripts/ingest` write against, so the
 * numbers that say what a Code or a Size may be belong with the contract
 * rather than with one of its two writers. The reader below joins against
 * this when a row supplies it and against `API` when it does not.
 */
const SHARED_SCHEMA = join(REPO_ROOT, 'shared', 'schema', 'shared_schema');

const BOUNDS: {
  screen: string;
  python: { file: string; name: string; root?: string };
  typescript: string;
}[] = [
  {
    screen: CREATE_USER_SCREEN,
    python: { file: 'users.py', name: 'MAX_NAME_LENGTH' },
    typescript: 'MAX_NAME_LENGTH',
  },
  {
    screen: CREATE_USER_SCREEN,
    python: { file: 'auth.py', name: 'MAX_EMAIL_LENGTH' },
    typescript: 'MAX_EMAIL_LENGTH',
  },
  {
    screen: CREATE_USER_SCREEN,
    python: { file: 'auth.py', name: 'MAX_PASSWORD_FIELD_LENGTH' },
    typescript: 'MAX_TEMPORARY_PASSWORD_LENGTH',
  },
  // Story 1.10's screen. It carries no password field — the endpoint behind it
  // writes three columns and `password_hash` is not among them — so it mirrors
  // two bounds rather than three.
  {
    screen: EDIT_USER_SCREEN,
    python: { file: 'users.py', name: 'MAX_NAME_LENGTH' },
    typescript: 'MAX_NAME_LENGTH',
  },
  {
    screen: EDIT_USER_SCREEN,
    python: { file: 'auth.py', name: 'MAX_EMAIL_LENGTH' },
    typescript: 'MAX_EMAIL_LENGTH',
  },
  // Story 2.1's screen. Five mirrored bounds: three `maxLength` attributes,
  // a count and a byte ceiling. The last two are also rendered in the hint
  // under the file input, so a drift there is a sentence telling the
  // Administrator the wrong limit, not only an attribute that stops bounding.
  {
    screen: ADD_TILE_SCREEN,
    python: { file: 'tile.py', name: 'MAX_CODE_LENGTH', root: SHARED_SCHEMA },
    typescript: 'MAX_CODE_LENGTH',
  },
  {
    screen: ADD_TILE_SCREEN,
    python: { file: 'tile.py', name: 'MAX_SIZE_LENGTH', root: SHARED_SCHEMA },
    typescript: 'MAX_SIZE_LENGTH',
  },
  {
    screen: ADD_TILE_SCREEN,
    python: { file: 'tile.py', name: 'MAX_CATEGORY_LENGTH', root: SHARED_SCHEMA },
    typescript: 'MAX_CATEGORY_LENGTH',
  },
  {
    screen: ADD_TILE_SCREEN,
    python: { file: 'tile.py', name: 'MAX_IMAGES_PER_REQUEST', root: SHARED_SCHEMA },
    typescript: 'MAX_IMAGES_PER_REQUEST',
  },
  // The byte ceiling. Mirrored for a stronger reason than the three above:
  // the screen refuses a file over it *before* uploading, so a drift here is
  // not a missing convenience — it is the screen refusing a file the server
  // would have taken, or letting hundreds of megabytes travel to be refused
  // at the far end.
  {
    screen: ADD_TILE_SCREEN,
    python: { file: 'tile.py', name: 'MAX_IMAGE_BYTES', root: SHARED_SCHEMA },
    typescript: 'MAX_IMAGE_BYTES',
  },
  // Story 2.2's screen. The same five bounds as Add tile, because it writes the
  // same three fields and uploads through the same endpoint's limits — and
  // mirrored separately rather than shared, for the reason the Edit user row
  // above gives: a single `SCREEN` constant would compare one screen's literals
  // against nothing at all.
  {
    screen: EDIT_TILE_SCREEN,
    python: { file: 'tile.py', name: 'MAX_CODE_LENGTH', root: SHARED_SCHEMA },
    typescript: 'MAX_CODE_LENGTH',
  },
  {
    screen: EDIT_TILE_SCREEN,
    python: { file: 'tile.py', name: 'MAX_SIZE_LENGTH', root: SHARED_SCHEMA },
    typescript: 'MAX_SIZE_LENGTH',
  },
  {
    screen: EDIT_TILE_SCREEN,
    python: { file: 'tile.py', name: 'MAX_CATEGORY_LENGTH', root: SHARED_SCHEMA },
    typescript: 'MAX_CATEGORY_LENGTH',
  },
  {
    screen: EDIT_TILE_SCREEN,
    python: { file: 'tile.py', name: 'MAX_IMAGES_PER_REQUEST', root: SHARED_SCHEMA },
    typescript: 'MAX_IMAGES_PER_REQUEST',
  },
  {
    screen: EDIT_TILE_SCREEN,
    python: { file: 'tile.py', name: 'MAX_IMAGE_BYTES', root: SHARED_SCHEMA },
    typescript: 'MAX_IMAGE_BYTES',
  },
  // Story 2.4's screen. Two mirrored bounds rather than the other screens'
  // five: it carries no text field at all, so there is no `maxLength` to keep
  // in step — the Code, the Size and the Category arrive in the manifest, and
  // reading it is the server's job.
  //
  // Both are here for the stronger of the two reasons the Add tile rows give:
  // the screen refuses past either bound *before* uploading, so a drift is not
  // a missing convenience — it is the screen refusing a batch the server would
  // have taken, or letting gigabytes travel to be refused at the far end.
  //
  // `MAX_BULK_ROWS` bounds a bulk upload on both counts — the manifest's rows
  // and the uploaded images — and the server enforces it on both, which is
  // what lets this screen refuse on the count it *can* see without stating a
  // rule the product does not have. It never reads the manifest, so images is
  // the number it has; the server checks that one too and refuses the same
  // batch with `too_many_rows` whatever this says.
  {
    screen: BULK_UPLOAD_SCREEN,
    python: { file: 'tile.py', name: 'MAX_BULK_ROWS', root: SHARED_SCHEMA },
    typescript: 'MAX_BULK_ROWS',
  },
  {
    screen: BULK_UPLOAD_SCREEN,
    python: { file: 'tile.py', name: 'MAX_IMAGE_BYTES', root: SHARED_SCHEMA },
    typescript: 'MAX_IMAGE_BYTES',
  },
];

describe('the admin form bounds are one contract in two languages', () => {
  it.each(BOUNDS.map((bound) => [`${bound.screen}: ${bound.typescript}`, bound] as const))(
    '%s is the same number on both sides',
    (_name, bound) => {
      const python = pythonInteger(
        read(join(bound.python.root ?? API, bound.python.file)),
        bound.python.name,
      );
      const typescript = typescriptInteger(read(screenPath(bound.screen)), bound.typescript);

      // Both halves asserted non-null first, for the reason the codes above give:
      // a comparison of `null` with `null` passes forever, so a renamed or moved
      // constant has to fail here as a missing one rather than as a match.
      expect(python).not.toBeNull();
      expect(typescript).not.toBeNull();
      expect(typescript).toBe(python);
    },
  );
});
