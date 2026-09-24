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
make model    # download the ONNX backbone shared/vision embeds with (~346 MB)
```

`make ingest` and `make eval` exist but are not implemented; each names the epic that delivers it
and exits non-zero. Run `make` with no target for the full list.

### The embedding model

`shared/vision` cannot turn a pixel into a vector without the `Xenova/dinov2-base` ONNX export,
and 346 MB of weights never enter git. Fetch it once per machine:

```bash
make model                            # pinned revision, sha256-checked
make model FROM=poc/models/model.onnx # adopt the copy the POC already pulled
```

It lands in `shared/vision/shared_vision/models/model.onnx` (gitignored). Set `ROCELL_MODEL_PATH`
if it has to live somewhere else. The revision is pinned and the digest checked on purpose: the
model is part of AD-1's pixel path, so a silently different set of weights is a silently
invalidated index. Without it, `shared/vision`'s tests **skip** rather than fail and
`POST /admin/tiles` — and `PATCH /admin/tiles/{tile_id}` when the edit uploads a reference image
— answer `503 matching_unavailable` naming this step. An edit that only changes a Code, a Size or
a Category embeds nothing and needs no artifact at all.

### Object storage

`apps/api` keeps reference images outside the database and needs somewhere to put them:

```bash
export OBJECT_STORAGE_ROOT=/var/lib/rocell/objects
```

Never defaulted, for the reason `DATABASE_URL` is not: a service that guesses where to put files
can write a catalogue into a temporary directory and report success. The S3-compatible provider is
still an open decision (`infra/README.md`), so what ships behind `api.storage.ObjectStore` today is
a filesystem driver. `apps/web` never receives a storage URL either way — every image byte is
proxied through an authenticated endpoint (AD-9).

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

**The role behind `DATABASE_URL` needs `CREATEROLE`** (or superuser) for this,
which is new and is easy to miss: the audit-log migration creates `rocell_app`,
the role the service runs as, so migrating now needs a cluster-level privilege
and not just write access to one database. Without it `make migrate` stops on
`permission denied to create role` and applies nothing.

That creates the `users` table and seeds **exactly one** Administrator, in the
`must_change_password` state — the only account in the product's lifetime that no Administrator
created. Re-running `make migrate` never produces a second one, and on an already-seeded database
it needs no `SEED_ADMIN_*` variables at all.

`make dev` needs `DATABASE_URL` too: `apps/api` opens its connection pool at startup and exits
naming the variable if it is unset, rather than starting and failing at the first sign-in. Point it
at the same database you migrated.

It needs `OBJECT_STORAGE_ROOT` as well, and that one behaves differently: it is read at the first
catalogue write rather than at startup, so a service without it boots, signs people in and then
fails on the first Add tile. `make dev` prints a note when it is unset, for exactly that reason.

**Every connection the service opens adopts the `rocell_app` database role**, which the audit-log
migration creates and grants: full read/write on `users`, `sessions` and `login_attempts`, and
`SELECT, INSERT` — and nothing else — on the audit log. That is why an `UPDATE` or `DELETE`
against the log is refused by PostgreSQL rather than by a code review (AD-4). Two things follow
for anyone working on the schema. The role is **cluster-scoped**, shared by every database on the
server, so no migration drops it. And a table added by a later migration needs its own `GRANT` in
that migration — there is no `ALTER DEFAULT PRIVILEGES` to fall back on, deliberately, and
`apps/api/tests/test_audit_immutability.py` fails the build for a table the role cannot use rather
than letting it surface as a permission error in production. The role has no password and needs
none: it is adopted over the connection `DATABASE_URL` already made.

**`TRUSTED_PROXY_HEADER` is optional and unset by default.** It names the header a trusted reverse
proxy sets with the real client address — `x-forwarded-for`, `x-real-ip`, whatever your edge layer
uses — and it is the *only* source of `source_ip` on an audit entry when it is set. Left unset,
`source_ip` is the connection's peer address, which the caller cannot forge; a client that sends
its own `X-Forwarded-For` is ignored outright. That is the safe default, and it has one
consequence worth knowing: **deploy behind a proxy without setting this and every audit entry
records the proxy's address rather than the user's.** Set it in the same breath as `DATABASE_URL`
when an edge layer goes in front. A value that does not parse as an IP address, and a configured
header the request does not carry, both record nothing — never the proxy's address as a fallback.

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

A signed-in user can change their own password at any time, from **Account** in the app bar. It
asks for the current password as well as the new one and proves the current one before it writes
anything, so an unlocked phone left on a counter is not a permanent takeover of the account — and a
wrong current password is reported on the screen without signing anybody out. The change takes
effect immediately: the old password stops working at the very next sign-in, with no sign-out or
re-login in between. It also **signs that person out on every other device** — that is the point of
it, because the usual reason for changing a password you already chose is that you think somebody
else has it — while the browser that made the change stays signed in on a fresh cookie. The screen
shows the account's name and email as well, read-only; changing either is an Administrator's job,
from **Users → Edit**.

That change is written down. Two entries land with it in the append-only audit log — the change
itself, and the revocation, carrying how many devices it signed out — each naming the account, the
time and the address the request came from. So "was this password changed on Tuesday, and how many
sessions did it end?" is a question the system can now answer, **and answer on screen**: an
Administrator opens **Audit log** from the home panel and reads it there, with no database
credential and no `psql` prompt.

**Audit log** is that surface, and it is Administrators only — a Staff user has no entry to it
anywhere, and the server refuses them even if they find the address. It shows every recorded event
**newest first**, six columns wide: when it happened, who did it, what they did, who it was done
to, the address the request came from, and whatever else the event carried. An event with no known
actor — somebody trying an address that is not an account — says **No actor** rather than naming
anyone, because the log was never told who tried; an address that could not be recorded says **Not
recorded** rather than showing a blank cell. An action this build does not recognise is still
shown, under its stored name, because a record that hid the parts it did not understand would be a
less faithful record than the table behind it.

It arrives one page at a time, newest first, and **Load more** fetches the next page and adds it
underneath; the control disappears once the oldest entry has been reached. There is no search box,
no date picker, no sort control and no export — and, most deliberately, **no way to change or
remove an entry**. Not a hidden one, not a disabled one: no edit control, no delete control, no
row-end menu and no clickable row exist on that screen at any role, and no route behind it could
serve one. The application's database role is granted `SELECT` and `INSERT` on that table and
nothing else, so an update or a delete is refused by PostgreSQL itself rather than by a rule
somebody could change. A wrong entry is corrected by appending a corrective one.

An Administrator provisions everybody else, from **Users** on the home panel and then **+ Add
user** on the list — the entry is rendered only for an Administrator, and a Staff user never sees
it. It asks for a name, an email address, a role (Staff or Administrator) and a temporary password
that the Administrator types themselves: there is no generator, because the value has to be
transcribed by hand and a password you chose is one you can read back over a counter. It is shown
in plain text on screen for the same reason — it is not the Administrator's own secret, and masking
it would hide a typing mistake until the new user came back unable to sign in.

On success the screen shows the name, address, role, the temporary password exactly as typed, and
the moment it expires. **Hand that over yourself.** The app sends no mail of any kind — no
invitation, no notification, no control on the screen that offers to send one — and the credential
is gone from the product the moment you navigate away: nothing stores it in readable form and no
screen can show it again. If it is lost before it reaches the person, provision them afresh:
nothing in Epic 1 reissues a credential for a provisioned user. **A mistyped address is no longer
a dead end** — open **Users**, press **Edit** on the row and correct it, which releases the wrong
address for reuse without releasing any lockout, and the account keeps the credential it was given.
One caveat, and it is the only one: the counter follows the address *into* the account as well as
out of it, so correcting a typo onto an address that somebody had already been guessing passwords
at hands that lockout to the account. There is no admin unlock anywhere in Epic 1, so the whole of
the recovery is waiting the 15 minutes out. Provisioning a second account under a different address
still works too, and the row it leaves behind can now be **deleted** — which releases its address
for reuse as well.

The credential is good for **72 hours**, or until it is claimed — whichever comes first. The new
user can sign in with it straight away — no migration, no console command, no developer — and the
first and only thing they can reach is the forced password-change screen; everything else answers
`403` until they set a real password. It is not a one-use code: inside those 72 hours it signs in
as many times as it is tried, and each time it lands on the same screen. Setting a real password is
what retires it, and that also ends every session the credential had opened, on every device. Left
unclaimed past 72 hours it stops working and the account needs a fresh one. The role
takes effect on that user's very next request rather than at their next sign-in, in both directions:
an Administrator you provision can provision others as soon as they claim their credential, and one
you later demote is refused on the request after the change.

Two limits worth knowing. The address must be unique, case and surrounding spaces ignored —
`Nadeesha@Rocell.LK` and `nadeesha@rocell.lk` are the same login — and a second attempt at one
already in use is refused without writing anything. And **who provisioned whom is written down**:
every successful provisioning appends an audit entry naming the Administrator who did it, the
account they created and the time — a refused one appends nothing, because nothing happened. That
entry is on the **Audit log** screen, at the top of it, the moment the user is provisioned.

**Users** is the list of everyone who has access, and it is Administrators only — a Staff user has
no entry to it anywhere, and the server refuses them even if they find the address. It shows every
account in the product with its name, email, role, status and last login, ordered by name; the
Administrator reading it is on it too. Nothing is filtered and nothing is paged, because the
question the screen answers is "who has access" and a list that quietly left somebody off would
answer it wrongly. **A deactivated account is marked, never hidden** — the row carries the word
"Deactivated" and is muted, so the distinction survives a black-and-white screen. **Last login
reads "Never" until the person first signs in** — the word rather than an empty cell, which would
read as a value that failed to load — so a credential that was handed over and never used is
visible at a glance. A lockout shows on that account's status as a "Locked until" line; as
everywhere else the lock clears itself on its own, and **there is still no control anywhere that
ends one early — no story in Epic 1 owns an admin unlock at all.** Each row ends in three controls:
**Edit**, **Deactivate** (or **Activate**, on an account that is already off) and **Delete**.

**Edit** opens that account's name, email and role, pre-filled, and saves the fields you actually
changed — press Save with nothing edited and nothing is sent. The role takes effect on that
person's very next request in both directions: promote somebody and they can reach the admin
surfaces without signing out and in, demote them and they are refused on the request immediately
after. Demoting yourself works the same way, and the Users entry simply disappears; what is refused
is the demotion that would leave the product with **no active Administrator at all**, which is
answered with the rule and the way out of it. Changing an address changes the login — the old one
stops working at the very next sign-in and the new one starts — and **it takes the account's
lockout counter with it**: a locked account is still locked at its new address, so an edit is not a
way around a lockout. And **who changed what is written down**: an edit appends an audit entry
naming the Administrator, the account and the fields that actually moved, each with its old and new
value. An edit that changes nothing says so rather than claiming a change.

**Deactivate** takes an account's access away **immediately**. Not at their next sign-in — on their
very next request: somebody using the app at that moment is signed out where they stand, on every
device, and every session they hold is deleted rather than merely ignored. The account itself stays
on the list, marked Deactivated, keeping its name, address, role and password. **Activate** gives
the access back and nothing else: no session returns, no credential is reissued and no password is
set, so the person signs in again with what they already had. A lockout is unaffected by either —
neither verb is an unlock.

**Delete** removes the account for good. There is no undo, no archive and no "deleted" state to
find it in: the row is gone, its sessions go with it, and the email address becomes free to use for
a new account. The one thing a delete does *not* remove is the address's failed-sign-in counter. A
locked address stays locked, so deleting an account and recreating it is not a way around a
lockout — which is the same reason changing an address carries the lock with it.

**Deactivate and Delete ask first; Activate does not.** Pressing either destructive verb opens a
dialog naming the person and saying what happens to them — never a bare "Are you sure?" — and
nothing is written until you confirm; Cancel, `Escape` or a click outside close it having done
nothing. **Activate** is the undo rather than the damage, so it fires on the one press and the row
updates in place; a failure still lands in the same dialog, as a refusal. **And both destructive
verbs are refused on the last remaining active Administrator.** Deactivating or deleting the only
active Administrator left would leave the product with nobody who can administer it, so the dialog
opens *as* the refusal, with no button to press: make somebody else an Administrator, or activate
one, first. The refusal is the server's, not
the screen's — the API refuses the same operation with the same rule however it is reached, exactly
as it already refuses the demotion that would do the same thing by a different verb. Doing any of
this to **your own** account is allowed while another active Administrator exists; the app drops to
the login screen on its next request.

**All three are written down.** Each appends an audit entry naming the Administrator who acted,
the account they acted on and the address the request came from; a deactivation also records how
many sessions it revoked, and a delete records the row it removed — which is why a deleted account
still has a history even though its row is gone. A refused operation appends nothing.

**A forgotten password has no self-service path at all.** There is no reset link, no reset email and
no mail transport anywhere in the product — the app sends no email, by design, and a test fails the
build if a mail package is so much as declared in a manifest. A user who cannot sign in goes to an
Administrator, who issues a fresh temporary credential and hands it over in person. Changing a
password also does **not** clear a lockout, since the lock belongs to the address under attack
rather than to the credential — see the next two paragraphs for how a lockout is reached and how it
ends.

Repeated failed sign-ins are slowed down and then blocked. From the 6th attempt — the first one
after five recorded failures — each attempt waits before it is processed, one second, then two,
three, four, and four again, so the ladder runs out exactly as the lock arrives: the 10th failed
attempt locks out further attempts for 15 minutes, answering a distinct message instead of "email or
password is incorrect". **The lock clears itself, and there is no admin unlock: no story in Epic 1
owns one, and nothing in the product ends a lock early.** Story 1.10 was where one was predicted;
it shipped with the edit it was actually scoped to — name, email and role — and no unlock, so this
is the state of it rather than a gap waiting on a story. Waiting it out is the whole of the
recovery, and it restores the full ladder: one mistyped password an hour later does not re-lock
anything. A correct password is refused while the lock holds, and any successful sign-in clears the
count outright. Changing the account's address does not clear it either — the counter moves with
the account, which is exactly so that an Administrator's edit cannot be the unlock the product does
not have.

The counter is keyed on **the address that was typed**, not on the account, which is why an address
that has never existed accrues exactly the same delays and the same lockout. That is deliberate: a
ladder attached to real accounts would answer instantly for an address that is not one, and six
wrong passwords would then be enough to tell an attacker which addresses are accounts. The cost is
that a lockout is not proof an account exists — and that a lock on `ruwan@rocell.lk` is a lock on
that *string*, so it says nothing about the person until you check **Users**. An Administrator
sees the lock there, on the account's own status (`users.locked_until`), as a "Locked until" line;
a value in the past is not rendered at all, because it means "locked recently, not locked now".

The cost runs the other way too, and it is not mitigated: a locked attempt is refused before any
work, so anyone who knows a colleague's address can spend ten wrong guesses to hold that person out
for fifteen minutes, then do it again. There is nothing to press and nothing to wait for but the
clock. That is the price of a lock that does not need an account to exist, and it is the reason the
lockout is fifteen minutes rather than a day.

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

## Brand assets and the install icon

`apps/web/brand/rocell-logo.png` is the master logo, as supplied. It is the only brand image in
the repository that is not generated, and it is not shipped — `apps/web/public/` is.

Everything under `apps/web/public/icons/`, plus `apps/web/public/favicon.ico`, is rendered from
that master by `scripts/generate_brand_icons.py`:

```bash
uv run python scripts/generate_brand_icons.py
```

The output is committed, because `apps/web` builds with npm and never runs Python. Re-run the
script after replacing the master, and commit what it writes.

Two families come out of it, and they are not interchangeable. An `any` icon is shown as given,
so it is the master resized — the master's own white frame is what a platform's corner rounding
eats into. A `maskable` icon is cropped to a shape the platform chooses, which guarantees nothing
outside a centred circle of 80% diameter, so the mark is scaled onto a white field to sit inside
it. Hand a platform an `any` icon as `maskable` and the tail of the wordmark is cut off.

`src/__tests__/pwa-icons.test.ts` guards the wiring: every icon the manifest declares exists at
the pixel size it claims, both purposes are covered at both install sizes, the maskable variant is
not a copy of its `any` twin, the `apple-touch-icon` iOS reads instead of the manifest is present
at 180×180, and the manifest's `theme_color` and `background_color` still match the token layer.

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
say so in the pull request. This is not a convention anyone has to remember — the active
`embedding_generation` row carries the pipeline version and a hash of the preprocessing config
(AD-14), and a catalogue write or a search whose running pipeline does not match that stamp is
refused outright with `503 pipeline_stamp_mismatch` rather than quietly comparing vectors from two
different pipelines. A re-index is a **complete new generation**, cut over by flipping the single
active pointer, never a per-row patch.

Since Story 2.1 the module is the port of `poc/tilematch/vision.py` it was always meant to be:
copied, not paraphrased. Its constants come verbatim from the model's own
`preprocessor_config.json`, and `shared/vision/tests/test_pipeline.py` asserts index-time and
query-time vectors are bit-identical.

## Further reading

- `CLAUDE.md` — stack, domain vocabulary, source-data quirks, testing approach.
- `AGENTS.md` — security policy (non-negotiable), conventions, known pitfalls.
- `_bmad-output/planning-artifacts/architecture/` — the architecture spine and its decisions.
- `_bmad-output/planning-artifacts/ux-designs/` — `DESIGN.md` (tokens) and `EXPERIENCE.md` (flows).
