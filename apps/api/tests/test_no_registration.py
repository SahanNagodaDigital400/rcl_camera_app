"""FR-1 as a test: nobody can bring their own account into existence.

Accounts are provisioned by an Administrator — since Story 1.8 through
`POST /admin/users`, which is authenticated and Administrator-only — and the
very first one is written by the migration runner outside the application
entirely. What FR-1 forbids is a *self*-provisioning path: an unauthenticated
caller, or any caller acting on their own behalf, creating the credential they
then sign in with. "We just did not write a sign-up endpoint" is not a guarantee
— this file is.

Three independent checks, because each misses what the others catch:

* the route table, which catches a router included without a test of its own;
* a live request, which catches a path served by something other than a route
  (a mount, a catch-all, a static handler); and
* a scan of the source tree, which catches the front end growing a link or a
  form long before any Python notices. The AC says "anywhere in the product",
  so the scan covers the whole repository's own source — `apps/web/index.html`
  and everything else outside `src/`, `infra/` (a migration could seed one),
  and `scripts/` — not only the three directories this story happened to
  touch.

**The patterns are assembled from fragments** so this file cannot match itself.
Written out whole, every check below would find its own source and fail.

The scan reads whole files, comments included, and does not try to tell prose
from code. That is deliberate: a comment describing the feature the product
does not have is the first draft of building it, and a guard with an exemption
for "it is only a comment" is a guard with a hole in exactly the shape of the
thing it forbids. Say "self-provisioning" in prose where the forbidden wording
would otherwise appear.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from api.main import create_app
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[3]

SCANNED = (
    REPO_ROOT / "apps",
    REPO_ROOT / "infra",
    REPO_ROOT / "scripts",
    REPO_ROOT / "shared",
)

SCANNED_EXTENSIONS = {".py", ".ts", ".tsx", ".css", ".html", ".sql", ".json"}

#: Not this repository's source: vendored dependencies, build output and
#: caches. `poc/` is outside `SCANNED` entirely — it is a standalone proof of
#: concept with its own toolchain and ships nothing.
SKIPPED_DIRECTORIES = {"__pycache__", "node_modules", "dist", ".venv", ".vite", "coverage"}

#: A lockfile is a record of third-party package names, not this product's
#: source. `@babel/register` would be a `/{_REGISTER}` match and a build broken
#: for a reason that has nothing to do with FR-1.
SKIPPED_FILES = {"package-lock.json", "uv.lock"}

# The words, never spelled out in one piece. See the module docstring.
_REGISTER = "regi" + "ster"
_SIGNUP = "sign" + "up"
_JOIN = "jo" + "in"
_ACCOUNT = "acc" + "ount"

#: Route paths that would be a registration surface.
ROUTE_WORDS = (_REGISTER, _SIGNUP, _JOIN)

#: Source patterns. Route-shaped (`/word`) and copy-shaped (`Sign up`, `Create
#: an account`) — deliberately *not* the bare word `{_REGISTER}`, which appears
#: in this repository as "registered for ApiError only" and as `.{_JOIN}(` in
#: every other TypeScript file.
SOURCE_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"/(?:" + "|".join(ROUTE_WORDS) + r")\b",
        r"\bsign[\s_-]?up\b",
        r"\bcreate\s+(?:an?\s+)?" + _ACCOUNT + r"\b",
        r"\bnew\s+" + _ACCOUNT + r"\b",
    )
)

#: Paths this scan does not read: it would otherwise find its own patterns in
#: the file that defines them.
SELF = Path(__file__).resolve()


def _routes() -> list[tuple[str, frozenset[str]]]:
    """Every path the application actually serves, including included routers."""

    def walk(router: object) -> list[tuple[str, frozenset[str]]]:
        found: list[tuple[str, frozenset[str]]] = []
        for route in getattr(router, "routes", []):
            if isinstance(route, APIRoute):
                found.append((route.path, frozenset(route.methods or ())))
            # FastAPI wraps an included router rather than flattening its
            # routes into the parent, so a check that read `app.routes` alone
            # would see this whole router as one opaque entry and pass.
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


def test_the_scan_finds_files_to_read() -> None:
    # A scan over an empty list passes every assertion below without reading a
    # byte. This is what makes the rest of the file mean something.
    assert len(_scanned_files()) > 10


def test_the_route_table_holds_no_registration_path() -> None:
    offenders = [
        (path, sorted(methods))
        for path, methods in _routes()
        if any(word in path.lower() for word in ROUTE_WORDS)
    ]

    assert offenders == [], "FR-1: accounts are provisioned by an Administrator"


def test_the_route_table_is_the_five_auth_routes_health_and_the_nine_admin_paths() -> None:
    # Stated positively as well as negatively: a route table listed in full
    # makes an addition a visible diff rather than something a word-match has
    # to anticipate.
    #
    # `/auth/password` sets a password on an *existing* account signed in on an
    # admin-issued temporary credential (Story 1.4). `/auth/password/change` is
    # the signed-in self-service change (Story 1.7, FR-5): it takes the caller's
    # current password, refuses an account that has not yet claimed its
    # temporary credential, and — like the other — creates nothing. Neither is a
    # way to bring an account into existence, and neither is reachable without a
    # session. `test_forced_change_gate.py` holds the same table to the
    # forced-change allowlist, and `test_no_password_reset.py` holds it to FR-5's
    # "no self-service option for a signed-out user".
    #
    # `/admin/users` (Story 1.8, FR-11) is the one route in the product that
    # does bring a user into existence, and it is what FR-1 *requires* rather
    # than what it forbids: FR-1 says a user authenticates only if an
    # Administrator provisioned them, which presupposes that an Administrator
    # has somewhere to do it. What FR-1 forbids is a caller provisioning
    # *themselves*, and nothing here does:
    #
    # * it is authenticated — without a session it answers `401`, so there is no
    #   unauthenticated path to it at all;
    # * it is Administrator-only, through `require_administrator`, which
    #   `test_admin_authorization.py` proves every `/admin/` route declares; and
    # * every field it takes describes somebody *else* — the caller's own row is
    #   never the one written, and the body cannot name who is acting.
    #
    # `/admin/users/{user_id}` (Story 1.10, FR-12) is a **new path**, which is
    # why this set changes where Story 1.9's added method did not. It is not a
    # registration surface either, and for a stronger reason than the collection
    # above: it can only ever change an account an Administrator already created.
    # It takes an id in the path, refuses one that names no row with a `404`, and
    # its body carries no password and no `active` — there is no shape of request
    # to it that brings a user into existence. It is authenticated and
    # Administrator-only through the same `require_administrator` every route
    # under `/admin/` declares.
    #
    # `/admin/users/{user_id}/deactivate` and `/admin/users/{user_id}/activate`
    # (Story 1.11, FR-13) are two more **new paths**, and a route that *removes*
    # access is the furthest thing there is from a registration surface: neither
    # takes a request body at all, so there is no shape of request to either one
    # that names a person, an address or a password. They act on an id that must
    # already be in the table — an id that names no row is a `404` — and the most
    # either can do is flip a column on an account an Administrator created
    # earlier through the collection above.
    #
    # Story 1.11's third verb, `DELETE /admin/users/{user_id}`, adds a **method**
    # to the path Story 1.10 already registered and so does not change this set.
    # Worth stating rather than leaving to inference: this guard is about paths,
    # and a reader counting routes against it would come up short. What makes
    # the delete safe here is the same thing twice over — it carries no body,
    # and it can only ever remove a row.
    #
    # `/admin/audit` (Story 1.13, FR-21) is the fifth admin path and the one
    # that is furthest from a registration surface of all: it is a read. It
    # takes no request body, writes nothing, and the only thing a caller may
    # send it is a cursor naming an entry that already exists. It is
    # authenticated and Administrator-only through the same
    # `require_administrator` every route under `/admin/` declares.
    #
    # `/admin/tiles` and `/admin/tiles/{tile_id}/images/{image_id}` (Story 2.1,
    # FR-14) are the sixth and seventh admin paths, and the first in the
    # product that are not about accounts at all: one adds a Tile to the
    # Catalogue and one serves that Tile's reference image. Neither can bring a
    # user into existence — no field on either names a person, an address or a
    # password, and the only rows they write are catalogue rows. They are
    # authenticated and Administrator-only through the same
    # `require_administrator` every route under `/admin/` declares.
    #
    # The image route is worth one further line, because it is the first route
    # in the product that answers with bytes rather than with the shared JSON
    # envelope. That changes nothing here — this guard is about which paths
    # exist — and it is what AD-9 requires in place of a storage URL: the bytes
    # are proxied through an endpoint that re-checks the role, rather than
    # handed to the browser as a link it could follow without one.
    #
    # `/admin/tiles/{tile_id}` and `/admin/tiles/lookup` (Story 2.2, FR-15) are
    # the eighth and ninth admin paths. The first corrects a Tile an
    # Administrator already added — an id that names no Tile is a `404`, and no
    # field on it names a person, an address or a password. The second finds one
    # Tile by an **exact** Code and writes nothing at all. Both are
    # authenticated and Administrator-only through the same
    # `require_administrator` every route under `/admin/` declares.
    #
    # `lookup` is a literal segment under `/admin/tiles`, and there is no
    # `GET /admin/tiles/{tile_id}` for it to be shadowed by — which is what
    # keeps it a path in its own right rather than a Code that happens to look
    # like a UUID.
    #
    # The seeded Administrator (`infra/rocell_infra/seed.py`) is still the only
    # row written with no Administrator behind it, and it is written by the
    # migration runner outside the application entirely.
    assert {path for path, _ in _routes()} == {
        "/health",
        "/auth/login",
        "/auth/session",
        "/auth/logout",
        "/auth/password",
        "/auth/password/change",
        "/admin/users",
        "/admin/users/{user_id}",
        "/admin/users/{user_id}/deactivate",
        "/admin/users/{user_id}/activate",
        "/admin/audit",
        "/admin/tiles",
        "/admin/tiles/lookup",
        "/admin/tiles/{tile_id}",
        "/admin/tiles/{tile_id}/images/{image_id}",
    }


@pytest.mark.parametrize(
    "path",
    ["/auth/" + _REGISTER, "/" + _REGISTER, "/" + _SIGNUP, "/auth/" + _SIGNUP, "/" + _JOIN],
)
def test_a_registration_probe_is_not_found(client: TestClient, path: str) -> None:
    response = client.post(path, json={"email": "a@b.lk", "password": "x" * 20})

    assert response.status_code == 404
    assert set(response.json()) == {"error"}


def test_no_source_file_carries_a_registration_surface() -> None:
    offenders: list[str] = []

    for path in _scanned_files():
        text = path.read_text(encoding="utf-8", errors="replace")
        for pattern in SOURCE_PATTERNS:
            match = pattern.search(text)
            if match:
                offenders.append(f"{path.relative_to(REPO_ROOT)}: {match.group(0)}")

    assert offenders == [], "FR-1: no sign-in surface may offer a way to create an account"
