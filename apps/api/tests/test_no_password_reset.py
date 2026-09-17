"""FR-5's second clause as a test: there is no self-service path for a signed-out user.

"No reset emails — a locked-out or forgotten-password user goes through an
Administrator" (FR-5), and AGENTS.md Policy puts app-sent email outside v1
entirely. `test_no_registration.py` is the same shape for FR-1; this file is the
half of Story 1.7 that is about what the story deliberately does *not* build.

Four checks, and **each covers a different surface** — the distinction matters,
because two of them are narrower than they sound:

* **the route table**, checked for a recovery word (`reset`, `forgot`,
  `recover`). This catches a router included without a test of its own. It is
  applied to *served paths only* and to nothing else.
* **live requests**, which catch a path served by something other than a route
  (a mount, a catch-all, a static handler) — and which also pin the one route
  this story *does* add to "signed in only": `POST /auth/password/change`
  answers `401` with no cookie, so it is not a signed-out surface either.
* **a scan of the repository's own source for a mail transport**, which catches
  a helper growing an import long before any route notices.
* **a scan of the dependency manifests for the same transports**, which catches
  the step before that — a mail package declared but not yet used is the first
  half of building the thing, and it would pass a source scan for as long as
  nobody imported it.

**The recovery words are not scanned over the source tree, deliberately.** Only
`MAIL_PATTERNS` reach the files; `ROUTE_WORDS` never leave the route table. A
word scan across the repository would fail on honest prose that has every right
to be there — `LoginScreen.tsx` explains that a forgotten password goes through
an Administrator, and several comments in `apps/api` name the same rule — so it
would be a guard argued with rather than obeyed. **The web half of FR-5's clause
is therefore not asserted here.** It lives in
`apps/web/src/__tests__/login-screen.test.tsx`, whose "no self-provisioning
affordance" case pins the login screen to one button, no links, and no
occurrence of "forgot" in its rendered copy. That is the screen a signed-out
user actually sees; this file is the API-side half.

**The mail patterns are assembled from fragments** so this file cannot match
itself, the same way `test_no_registration.py` does it. `SELF` is excluded from
the scan for the same reason, and both are belt and braces: either alone would
leave this file's own deliberately-bad fixtures failing the guard they exist to
prove.

The scan reads whole files, comments included. A comment describing the mail
transport the product does not have is the first draft of adding it.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from api.main import create_app
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[3]

CHANGE = "/auth/password/change"

#: This repository's own source. `poc/` is outside it entirely — a standalone
#: proof of concept with its own toolchain that ships nothing.
SCANNED = (
    REPO_ROOT / "apps",
    REPO_ROOT / "infra",
    REPO_ROOT / "scripts",
    REPO_ROOT / "shared",
)

#: `.js`/`.mjs`/`.cjs` and `.yml`/`.yaml` are here although the repository holds
#: none of them today: a transport reached for first in a build script or a
#: deployment manifest is exactly the case a source-only extension set cannot
#: see, and `infra/` is where the second of those would land.
SCANNED_EXTENSIONS = {
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".mjs",
    ".cjs",
    ".css",
    ".html",
    ".sql",
    ".json",
    ".toml",
    ".yml",
    ".yaml",
}

SKIPPED_DIRECTORIES = {
    "__pycache__",
    "node_modules",
    "dist",
    ".venv",
    ".vite",
    "coverage",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
}

#: A lockfile is a transitive record of third-party package names, not a
#: declaration this repository made. The manifests below are what this product
#: chose; a lockfile entry pulled in by something else is not a decision anyone
#: here took, and holding it to this rule would be a guard argued with rather
#: than obeyed.
#:
#: `uv.lock` is deliberately **not** listed: its suffix is not in
#: `SCANNED_EXTENSIONS`, so naming it would be a skip rule that never fires —
#: an entry a reader would take for protection that is doing nothing. If the
#: extension set ever grows to reach it, add it back here with this comment.
SKIPPED_FILES = {"package-lock.json"}

#: Every dependency declaration in the repository, scanned whether or not the
#: package is imported anywhere. Listed explicitly rather than globbed so that a
#: manifest added later has to be added here too, visibly.
MANIFESTS = (
    REPO_ROOT / "pyproject.toml",
    REPO_ROOT / "apps" / "api" / "pyproject.toml",
    REPO_ROOT / "infra" / "pyproject.toml",
    REPO_ROOT / "scripts" / "ingest" / "pyproject.toml",
    REPO_ROOT / "shared" / "schema" / "pyproject.toml",
    REPO_ROOT / "shared" / "vision" / "pyproject.toml",
    REPO_ROOT / "apps" / "web" / "package.json",
)

# The words, never spelled out in one piece. See the module docstring.
_RESET = "re" + "set"
_FORGOT = "for" + "got"
_RECOVER = "re" + "cover"

#: Route paths that would be a signed-out recovery surface.
ROUTE_WORDS = (_RESET, _FORGOT, _RECOVER)

#: Probe paths a client — or an attacker — would try first.
PROBE_PATHS = (
    "/auth/password/" + _RESET,
    "/auth/" + _FORGOT + "-password",
    "/auth/" + _RECOVER,
    "/password-" + _RESET,
)

#: Each path under both verbs. A `POST`-only probe would miss the likelier half
#: of the feature: the surface a forgotten-password link leads to is a page, and
#: a page is served on `GET`. Answering `405` to one verb and a form to the other
#: would have read as clean here.
PROBES = tuple((method, path) for path in PROBE_PATHS for method in ("GET", "POST"))

# Mail transports, in the two languages this repository is written in. Every one
# of them is a way to send a message from the product, which is the thing FR-5
# and AGENTS.md Policy forbid: an Administrator distributes a credential by hand.
#
# The list is the names somebody would reach for *first*, not an exhaustive
# catalogue — a determined addition can always be spelled a way no list
# anticipates. What it has to cover is the accident and the shortcut: the
# transport library, the hosted API client, and the framework mailer that comes
# one `uv add` away.
#
# **No bare `ses`, and no bare `boto3` either.** Amazon's mail service shares
# three letters with `sessions`, which appears in half this repository, so `ses`
# on its own is unusable. `boto3` fails for the opposite reason: it is the client
# for *every* AWS service, and `CLAUDE.md` commits this product to S3-compatible
# object storage for the reference images. The first Epic 2 story to declare it
# would fail a test called `test_no_manifest_declares_a_mail_transport`, which is
# a false accusation and the kind of guard people delete rather than read. SES is
# matched through the spellings that actually reach *mail* instead — the client
# handle, the boto3 service name, and the operations themselves.
_TRANSPORTS = (
    # SMTP, spoken directly.
    "smtp" + "lib",
    "aio" + "smtplib",
    "email" + ".mime",
    "send" + "mail",
    "node" + "mailer",
    # Hosted senders, by the name their SDK ships under.
    "send" + "grid",
    "mail" + "gun",
    "post" + "mark",
    "re" + "send",
    "mail" + "jet",
    "bre" + "vo",
    # Its Python SDK imports under an underscore, which the trailing edge above
    # correctly refuses to match from the bare name — so the import spelling is
    # listed in its own right, exactly as the framework mailers below are.
    "bre" + "vo_python",
    "mail" + "chimp",
    "email" + "js",
    # SES, in the spellings that name the mail service rather than AWS at large.
    '"' + "ses" + '"',
    "'" + "ses" + "'",
    "SES" + "Client",
    "send_raw_" + "email",
    "send_templated_" + "email",
    "sendRaw" + "Email",
    "@aws-sdk/client-" + "ses",
    # Framework mailers, in both spellings each ships with.
    "fastapi-" + "mail",
    "fastapi_" + "mail",
    "flask-" + "mail",
    "flask_" + "mail",
    # And the function somebody writes when they have none of the above.
    "send_" + "email",
)

#: Lookarounds rather than `\b`, because `\b` is defined against word characters
#: and half of these names do not start or end with one. `\b@aws-sdk/...` never
#: matches at all: the character before `@` in `"@aws-sdk/client-ses"` is a quote,
#: and two non-word characters in a row are not a boundary — so the pattern would
#: have been silently dead. These assert the same intent (not glued to a longer
#: identifier) for every spelling, hyphens and sigils included.
_EDGE = r"(?<![A-Za-z0-9_])"
_TRAILING_EDGE = r"(?![A-Za-z0-9_])"

MAIL_PATTERNS = tuple(
    re.compile(_EDGE + re.escape(transport) + _TRAILING_EDGE, re.IGNORECASE)
    for transport in _TRANSPORTS
)

#: This file, resolved the same way every scanned path is. Unresolved, a
#: symlinked checkout or a `/private`-prefixed temp path makes the two spellings
#: differ and this file scans itself.
SELF = Path(__file__).resolve()


def _routes() -> list[tuple[str, frozenset[str]]]:
    """Every path the application actually serves, including included routers."""

    def walk(router: object) -> list[tuple[str, frozenset[str]]]:
        found: list[tuple[str, frozenset[str]]] = []
        for route in getattr(router, "routes", []):
            if isinstance(route, APIRoute):
                found.append((route.path, frozenset(route.methods or ())))
            # FastAPI wraps an included router rather than flattening its routes
            # into the parent, so a check that read `app.routes` alone would see
            # a whole router as one opaque entry and pass.
            inner = getattr(route, "original_router", None)
            if inner is not None:
                found.extend(walk(inner))
        return found

    return walk(create_app())


def _scanned_files() -> list[Path]:
    files: list[Path] = []
    for root in SCANNED:
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix not in SCANNED_EXTENSIONS:
                continue
            if SKIPPED_DIRECTORIES & set(path.parts):
                continue
            if path.name in SKIPPED_FILES:
                continue
            if path.resolve() == SELF:
                continue
            files.append(path)
    return files


#: Files the scan must actually reach, one per root and one per extension that
#: carries a real risk. A floor on the count alone is not enough: the repository
#: yields around a hundred files, so a `SCANNED` that drifted off a directory, a
#: dropped extension or an over-matching skip rule would still clear a floor of
#: ten while reading none of the code anybody would put a transport in.
MUST_BE_SCANNED = (
    REPO_ROOT / "apps" / "api" / "api" / "auth.py",
    REPO_ROOT / "apps" / "web" / "src" / "api" / "client.ts",
    # `App.tsx` rather than any one screen: the named files are a floor on the
    # scan's reach, so each has to be a file that outlives the story that added
    # it. A screen renamed in a later epic would otherwise fail a mail-transport
    # guard for a reason that has nothing to do with mail.
    REPO_ROOT / "apps" / "web" / "src" / "App.tsx",
    REPO_ROOT / "apps" / "web" / "package.json",
    REPO_ROOT / "infra" / "pyproject.toml",
    REPO_ROOT / "scripts" / "ingest" / "ingest" / "__main__.py",
    REPO_ROOT / "shared" / "schema" / "shared_schema" / "passwords.py",
)


def test_the_scan_reaches_the_files_it_claims_to() -> None:
    # A guard over an empty — or merely thin — file list passes forever. The
    # named files are what make "the scan covers this repository's source" a
    # statement the run can check rather than one this file asserts about itself.
    scanned = _scanned_files()

    assert len(scanned) > 60
    missing = [str(path.relative_to(REPO_ROOT)) for path in MUST_BE_SCANNED if path not in scanned]
    assert missing == [], (
        "the mail-transport scan no longer reads files it is written to cover: "
        + ", ".join(missing)
    )


def test_the_scan_reaches_the_manifests_it_claims_to() -> None:
    # A manifest renamed or moved would otherwise leave this guard reading
    # nothing and reporting clean.
    missing = [str(path.relative_to(REPO_ROOT)) for path in MANIFESTS if not path.is_file()]

    assert missing == []


def test_the_manifest_list_is_every_manifest_in_the_repository() -> None:
    # `MANIFESTS` is listed explicitly "so that a manifest added later has to be
    # added here too, visibly" — which was a comment and nothing more. Nothing
    # made it visible: a new `pyproject.toml` or `package.json` was simply
    # unscanned, and `test_no_manifest_declares_a_mail_transport` reported clean
    # over the seven it already knew. This is the half that makes the sentence
    # true, and the reason the list can stay explicit rather than becoming a
    # glob at the point of use: a glob reads whatever is there, so it can never
    # tell anybody that what is there has changed.
    found: set[Path] = set()
    for root in SCANNED:
        for path in root.rglob("*"):
            if not path.is_file() or path.name not in ("pyproject.toml", "package.json"):
                continue
            if SKIPPED_DIRECTORIES & set(path.parts):
                continue
            if path.name in SKIPPED_FILES:
                continue
            found.add(path)
    # The workspace root's own manifest sits outside every scanned directory.
    for name in ("pyproject.toml", "package.json"):
        if (REPO_ROOT / name).is_file():
            found.add(REPO_ROOT / name)

    unlisted = sorted(str(path.relative_to(REPO_ROOT)) for path in found - set(MANIFESTS))

    assert unlisted == [], (
        "a dependency manifest exists that the mail-transport guard does not "
        "read: add it to MANIFESTS"
    )


def test_the_route_table_holds_no_recovery_path() -> None:
    offenders = [
        (path, sorted(methods))
        for path, methods in _routes()
        if any(word in path.lower() for word in ROUTE_WORDS)
    ]

    assert offenders == [], "FR-5: a forgotten password goes through an Administrator"


@pytest.mark.parametrize(("method", "path"), PROBES)
def test_a_recovery_probe_is_not_found(client: TestClient, method: str, path: str) -> None:
    response = client.request(method, path, json={"email": "a@b.lk"})

    assert response.status_code == 404
    # The shared envelope, not FastAPI's `{"detail": ...}` — a probe must not be
    # the one response in the product with a different shape.
    assert set(response.json()) == {"error"}


def test_the_self_service_change_is_not_a_signed_out_surface(client: TestClient) -> None:
    # The route this story adds is the only new password write in the product,
    # and it is authenticated. Without a cookie it answers 401, so it cannot be
    # the self-service option FR-5's second clause forbids: there is nothing a
    # signed-out caller can do with it.
    response = client.post(CHANGE, json={"current_password": "x" * 20, "new_password": "y" * 20})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


def test_no_source_file_carries_a_mail_transport() -> None:
    offenders: list[str] = []

    for path in _scanned_files():
        text = path.read_text(encoding="utf-8", errors="replace")
        for pattern in MAIL_PATTERNS:
            match = pattern.search(text)
            if match:
                offenders.append(f"{path.relative_to(REPO_ROOT)}: {match.group(0)}")

    assert offenders == [], (
        "FR-5 / AGENTS.md Policy: the app sends no email — an Administrator "
        "distributes credentials manually"
    )


def test_no_manifest_declares_a_mail_transport() -> None:
    offenders: list[str] = []

    for path in MANIFESTS:
        text = path.read_text(encoding="utf-8", errors="replace")
        for pattern in MAIL_PATTERNS:
            match = pattern.search(text)
            if match:
                offenders.append(f"{path.relative_to(REPO_ROOT)}: {match.group(0)}")

    assert offenders == [], "A mail package declared is a mail path half-built"


@pytest.mark.parametrize(
    "line",
    [
        "import smtplib",
        "import aiosmtplib",
        "from email.mime.text import MIMEText",
        "const transport = require('nodemailer');",
        'import sgMail from "@sendgrid/mail";',
        '"mailgun.js": "^10.2.1"',
        '"postmark": "^4.0.5"',
        "def send_email(to: str, body: str) -> None: ...",
        "subprocess.run(['/usr/sbin/sendmail', '-t'])",
        '"resend": "^4.0.0"',
        '"node-mailjet": "^6.0.0"',
        "from brevo_python import TransactionalEmailsApi",
        '"@mailchimp/mailchimp_transactional": "^1.0.59"',
        "import emailjs from '@emailjs/browser';",
        '"fastapi-mail>=1.4.1",',
        "from fastapi_mail import FastMail",
        '"flask-mail>=0.10.0",',
        "from flask_mail import Mail",
        'ses = boto3.client("ses", region_name="ap-south-1")',
        "ses = boto3.client('ses')",
        "ses.send_raw_email(RawMessage={...})",
        'import { SESClient } from "@aws-sdk/client-ses";',
    ],
)
def test_the_mail_patterns_catch_what_they_are_for(line: str) -> None:
    # A guard nobody has seen fail is a guard nobody knows works. Each line is a
    # real first step towards the feature this file forbids.
    assert any(pattern.search(line) for pattern in MAIL_PATTERNS)


@pytest.mark.parametrize(
    "line",
    [
        "email: str = Field(min_length=1, max_length=MAX_EMAIL_LENGTH)",
        'assert body["email"] == account.email',
        "SELECT id FROM users WHERE lower(email) = %s",
        # The reason there is no bare `ses` pattern: it would match every one of
        # these, and `sessions` is named in half this repository.
        "DELETE FROM sessions WHERE user_id = %s",
        "def delete_sessions_for_user(conn, user_id) -> int:",
        "from api.sessions import SESSION_COOKIE_NAME",
        # Nor may a transport name match a longer identifier it merely sits
        # inside: these are the edge assertions doing their job.
        "const resended = false;",
        "prepostmarked = True",
        # And `boto3` is not a mail transport. The architecture routes reference
        # images through S3-compatible object storage, so the day this line is
        # written for real it must not be read as an attempt to send email.
        '"boto3>=1.35.0",',
        's3 = boto3.client("s3", endpoint_url=settings.s3_endpoint)',
        'import { S3Client } from "@aws-sdk/client-s3";',
    ],
)
def test_the_mail_patterns_leave_the_email_column_alone(line: str) -> None:
    # `users.email` is an address the product stores, not a message it sends.
    # A pattern that could not tell those apart would be unusable on day one.
    assert not any(pattern.search(line) for pattern in MAIL_PATTERNS)
