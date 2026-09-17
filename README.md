# Rocell Tile Scanner

Internal PWA that identifies a ceramic tile from a phone camera photo and returns the matching
Code (the catalogue file name), its reference image, Size and Category. Rocell staff only,
admin-provisioned accounts, online-only.

This is an **image retrieval** system, not a classifier: the catalogue changes constantly, so
nothing here is trained over product categories.

```
Index time:  ReferenceImage -> preprocess -> embed -> pgvector
Scan time:   phone photo    -> preprocess -> embed -> search -> top 3
```

Both paths call the *same* code in `shared/vision`. See AD-1 below.

## Layout

| Directory | Charter |
|---|---|
| `apps/web` | React PWA — capture UI, results, scan history, admin screens. Talks only to `apps/api`, holds no database or storage credential (AD-6). |
| `apps/api` | FastAPI service — auth, scan submission, admin user/catalogue endpoints, audit log. Every live mutation flows through here. |
| `shared/vision` | Crop, colour management, preprocessing and embedding, plus the shared upload-intake path. Called identically by `apps/api` and `scripts/ingest`. |
| `shared/schema` | Types and contracts shared between `apps/web` and `apps/api` — today the API error envelope and the `User`, each defined once in Python and once in TypeScript, plus the one Argon2id hashing helper that the migration seed and the login verifier both call. `apps/web` compiles against the TypeScript half (imported as `@rocell/schema/*`), so the two halves cannot drift apart unnoticed. |
| `infra` | IaC, migrations and the plain-SQL migration runner (`rocell_infra`). See `infra/README.md`. |
| `scripts/ingest` | Drive → index batch ingestion. The one pre-launch exception to "all mutation flows through `apps/api`". |

`poc/` is a standalone proof of concept with its own venv, Makefile and data. It is not part of
this workspace and is not linted, tested or built by the commands below.

## Getting started

Requires [uv](https://docs.astral.sh/uv/), Node 22.12+ (`.nvmrc`) and Python 3.12
(`.python-version`; uv will fetch the interpreter if it is missing).

```bash
make setup    # uv workspace venv + apps/web npm install
make dev      # apps/api on :8000, apps/web on :5173
make lint     # ruff check + ruff format --check, oxlint, tsc --noEmit
make test     # pytest workspace suite + apps/web vitest suite
make build    # production build of apps/web
```

`make ingest` and `make eval` exist but are not implemented; each names the epic that delivers it
and exits non-zero. Run `make` with no target for the full list.

### The database

`make dev` is only meaningful against a migrated database. Point `DATABASE_URL` at a PostgreSQL
you can write to, supply the first Administrator's credentials in the environment, and migrate:

```bash
export DATABASE_URL=postgresql://rocell@localhost:5432/rocell
export SEED_ADMIN_EMAIL=you@rocell.lk
read -rs SEED_ADMIN_PASSWORD && export SEED_ADMIN_PASSWORD   # 12-128 chars, not echoed
make migrate
unset SEED_ADMIN_PASSWORD
```

`read -rs` rather than `SEED_ADMIN_PASSWORD=… make migrate`: typed on the command line the
password lands in shell history, and `make migrate SEED_ADMIN_PASSWORD=…` additionally puts it in
the process's arguments, where `ps` shows it to every other user on the machine. `unset` it
afterwards because an exported password is inherited by everything the shell runs next. `make migrate` prints the address it seeded and the deadline it has to be claimed by.

That creates the `users` table and seeds **exactly one** Administrator, in the
`must_change_password` state — the only account in the product's lifetime that no Administrator
created. Re-running `make migrate` never produces a second one, and on an already-seeded database
it needs no `SEED_ADMIN_*` variables at all.

`make dev` needs `DATABASE_URL` too: `apps/api` opens its connection pool at startup and exits
naming the variable if it is unset, rather than starting and failing at the first sign-in. Point it
at the same database you migrated.

Signing in sets an HTTP-only, `Secure`, `SameSite=Strict` session cookie. Browsers treat
`http://localhost` and `http://127.0.0.1` as trustworthy origins, so a `Secure` cookie is stored
and sent over the dev proxy's plain HTTP exactly as it is in production — `make dev` needs no
exemption on the development machine, and none is made. The token is in that cookie and nowhere
else: no code in `apps/web` reads it, and a guard test fails the build if any file under
`apps/web/src` touches browser storage or `document.cookie`.

That exemption is for `localhost` only, which matters because this is a phone-first PWA: a handset
reaching `make dev` across the LAN by IP over plain `http://` is **not** a trustworthy origin, so
the browser silently discards the `Secure` cookie and sign-in never completes — the screen simply
returns to itself. Testing on a real handset therefore needs a trustworthy origin for the dev
server: a tunnel that terminates TLS, or a locally-trusted certificate. Do not reach for an
insecure cookie to make it work.

A session has two deadlines and dies at whichever comes first: it survives a normal shift, ends
after 12 hours with no request, and ends 7 days after it was issued however busy its owner was —
activity slides the first and cannot move the second. There is no warning before either and no
countdown; signing in again is the whole of the recovery. If the API stops honouring the cookie
for any reason — either deadline, a sign-out elsewhere, or an Administrator deactivating the
account — the next request from an open tab returns the user to the login screen with a short
notice, and which of those it was is deliberately not said. Arriving cold on a dead session shows
the login screen with **no** notice, and that is correct rather than a gap: the cookie is
HTTP-only and unreadable by page script, so a freshly loaded tab genuinely cannot distinguish a
session that just ended from a browser that never had one, and guessing would tell people who
never signed in that they had been signed out.

Nothing here is defaulted and nothing is committed: every value comes from the environment, and
`make migrate` exits non-zero naming whatever is missing. The seeded credential expires after 72
hours like any other admin-issued one; `make reseed-admin` reissues it while the account is still
unclaimed — and only while nobody has signed in on it. A new account's first sign-in lands on the
password-change screen and reaches nothing else — no app bar, no navigation, no way past it —
until a real password is set. The 72 hours are a deadline on *claiming* the account, not merely on
signing in: once they pass, the change screen stops accepting a password too. Finish the change in
one sitting; signing in and coming back later is the one sequence neither the screen nor
`make reseed-admin` can rescue. Full operator notes — commands, the two idempotency layers,
stepping a migration back — are in `infra/README.md`.

## Design tokens

`apps/web/src/styles/tokens.css` is the **only** file in `apps/web/src` allowed to hold a literal
colour, font stack, radius, spacing step or shadow. Every component references `var(--…)`.

The values are transcribed from the YAML frontmatter of
`_bmad-output/planning-artifacts/ux-designs/ux-rcl_camera_app-2026-09-08/DESIGN.md`, and two tests
keep it that way:

- `src/__tests__/tokens.test.ts` re-reads `DESIGN.md` and asserts every colour, type role, radius,
  spacing step and the elevation shadow is declared, that both font families carry a fallback
  stack, and that the accent's foreground is navy (white on orange is 2.63:1 and fails WCAG AA).
- `src/__tests__/no-raw-values.test.ts` walks `src` and fails on a colour literal (hex, `rgb()`
  and friends, or a named colour such as `white`), a dimension literal, a bare number in a JSX
  inline style, a font family named directly, or a Phosphor icon given a `weight` — icons are
  `regular` (outline) weight throughout, which is the library default. It also fails on a
  `var()` reference to a token `tokens.css` does not declare, and on a media query written at a
  width the token layer does not declare, since CSS cannot read a custom property inside one.

Fonts are self-hosted through `@fontsource`; nothing is fetched from a third-party font CDN.

## A note on ESLint

`make lint` runs **oxlint**, not ESLint, over `apps/web`. The architecture spine pins TypeScript
7.0.x, whose npm package no longer exports the classic JS compiler API that `typescript-eslint` is
built on — `typescript-eslint@8.70.0` declares `peer typescript ">=4.8.4 <6.1.0"` and refuses to
install against it, and ESLint core cannot parse `.ts` unaided. oxlint parses TS/TSX natively,
needs no `typescript` dependency, and runs with `--deny-warnings` so warnings gate the build.
Revisit when `typescript-eslint` ships TypeScript 7 support; the `Makefile` target and
`apps/web/package.json` are the only places that change.

## The invariant that matters most (AD-1)

Index-time and query-time preprocessing and embedding must be **byte-for-byte identical**. They
live in one module, `shared/vision`, and both pipelines call it unwrapped. Never fork it, never
reimplement it, never optimise one side only — an asymmetry raises no error and fails no test that
is not looking for it; it just quietly destroys match accuracy.

Any change to `shared/vision` invalidates the stored index: bump `PIPELINE_VERSION`, re-index, and
say so in the pull request.

## Further reading

- `CLAUDE.md` — stack, domain vocabulary, source-data quirks, testing approach.
- `AGENTS.md` — security policy (non-negotiable), conventions, known pitfalls.
- `_bmad-output/planning-artifacts/architecture/` — the architecture spine and its decisions.
- `_bmad-output/planning-artifacts/ux-designs/` — `DESIGN.md` (tokens) and `EXPERIENCE.md` (flows).
