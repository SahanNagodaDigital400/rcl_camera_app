"""FR-1 as a test: there is no way to create an account from inside the product.

Accounts are provisioned by an Administrator, and the very first one is written
by the migration runner outside the application entirely. "We just did not
write a sign-up endpoint" is not a guarantee — this file is.

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


def test_the_route_table_is_the_four_auth_routes_and_health() -> None:
    # Stated positively as well as negatively: a route table listed in full
    # makes an addition a visible diff rather than something a word-match has
    # to anticipate.
    #
    # `/auth/password` sets a password on an *existing* account signed in on an
    # admin-issued temporary credential (Story 1.4). It creates nothing, and
    # `test_forced_change_gate.py` holds the same table to the forced-change
    # allowlist.
    assert {path for path, _ in _routes()} == {
        "/health",
        "/auth/login",
        "/auth/session",
        "/auth/logout",
        "/auth/password",
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
