"""Story 1.3's three structural acceptance clauses, as a test rather than a grep.

The AC reads "Given `grep` over the new code, when it is inspected, then no SQL
is assembled by string concatenation or interpolation of a value ... and no
second `PasswordHasher` exists outside
`shared/schema/shared_schema/passwords.py`". Inspection by eye discharges that
once; this file discharges it on every run, which is the only version of it
that survives the next person to add a query.

A third clause comes from AD-3: **exactly one session-lookup function for the
whole service.** A second implementation is the divergence AD-3 names, and it
would arrive as a bespoke `FROM sessions` in whichever route needed one first —
not as an edit to `api/sessions.py`, where somebody might notice.

**The patterns are assembled from fragments** so this file cannot match itself,
the same way `test_no_registration.py` does it.

Scope is this story's own surface — the API package and the shared schema
package. `infra/` is the migration runner, whose entire job is composing DDL
from identifiers it owns, and holding it to a rule written for value
interpolation would be a guard that has to be argued with rather than obeyed.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]

#: This file, resolved the same way every scanned path is. Unresolved, a
#: symlinked checkout or a `/private`-prefixed temp path makes the two spellings
#: differ, this file scans itself, and its own deliberately-bad fixtures below
#: fail the guard they exist to prove.
SELF = Path(__file__).resolve()

#: This story's surface. Tests included: a test that interpolates a value into
#: SQL is the same defect as a route that does, and it is where the habit
#: usually starts.
SCANNED = (
    REPO_ROOT / "apps" / "api",
    REPO_ROOT / "shared" / "schema",
)

SKIPPED_DIRECTORIES = {"__pycache__", ".venv", ".pytest_cache"}

#: The one file allowed to build a `PasswordHasher`. AGENTS.md Policy: Argon2id
#: with these parameters, in one place, so a second set of parameters cannot be
#: introduced by a file that merely looks like it needs one.
HASHER_HOME = REPO_ROOT / "shared" / "schema" / "shared_schema" / "passwords.py"

#: The one file allowed to read the `sessions` table (AD-3).
SESSIONS_HOME = REPO_ROOT / "apps" / "api" / "api" / "sessions.py"

#: The one file allowed to *write* the `login_attempts` table (AD-8).
THROTTLE_HOME = REPO_ROOT / "apps" / "api" / "api" / "throttle.py"

# Never spelled out in one piece. See the module docstring.
_HASHER = "Password" + "Hasher"
_SESSIONS = "sessions"
_LOGIN_ATTEMPTS = "login_" + "attempts"

#: A verb followed, on the same line, by an f-string or a `+`/`%` join. Matches
#: `f"SELECT ... {value}"` and `"DELETE FROM " + table`; does not match a
#: parameterized query, which carries `%s` and no interpolation at all.
_VERBS = r"(?:SELECT|INSERT\s+INTO|UPDATE|DELETE\s+FROM|FROM|WHERE|VALUES)"

INTERPOLATED_SQL = (
    # An f-string whose text contains a SQL verb and a substitution.
    re.compile(r"""f["'].*\b""" + _VERBS + r"""\b[^"']*\{""", re.IGNORECASE),
    # A quoted fragment containing a SQL verb, glued to something with + or %.
    re.compile(r"""["'][^"']*\b""" + _VERBS + r"""\b[^"']*["']\s*[+%]\s*\w""", re.IGNORECASE),
)


def _sources() -> list[Path]:
    found: list[Path] = []
    for root in SCANNED:
        for path in sorted(root.rglob("*.py")):
            if SKIPPED_DIRECTORIES.isdisjoint(part for part in path.parts):
                found.append(path)
    return found


def test_the_scan_reaches_the_files_it_claims_to() -> None:
    # A guard over an empty file list passes forever. These three are the ones
    # the clauses are about, so their absence means the scan has drifted off
    # the code rather than that the code became clean.
    sources = _sources()
    assert len(sources) > 20
    for expected in (
        HASHER_HOME,
        SESSIONS_HOME,
        THROTTLE_HOME,
        REPO_ROOT / "apps" / "api" / "api" / "auth.py",
    ):
        assert expected in sources


def test_no_sql_is_assembled_from_a_value() -> None:
    offenders = [
        f"{path.relative_to(REPO_ROOT)}:{number}: {line.strip()}"
        for path in _sources()
        if path != SELF
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1)
        for pattern in INTERPOLATED_SQL
        if pattern.search(line)
    ]

    assert offenders == [], (
        "SQL assembled from a value. Pass it as a parameter — psycopg's `%s` is "
        "not string formatting and never becomes part of the statement:\n" + "\n".join(offenders)
    )


def test_only_one_module_builds_a_password_hasher() -> None:
    # Two hashers means two sets of parameters, and the weaker one wins for
    # every account it touches.
    offenders = [
        str(path.relative_to(REPO_ROOT))
        for path in _sources()
        if path not in (HASHER_HOME, SELF)
        and re.search(_HASHER + r"\s*\(", path.read_text(encoding="utf-8"))
    ]

    assert offenders == [], (
        f"A second {_HASHER} outside {HASHER_HOME.relative_to(REPO_ROOT)}: " + ", ".join(offenders)
    )


def test_only_one_module_reads_the_sessions_table() -> None:
    # AD-3: one shared lookup, or a route quietly grows its own and stops
    # re-reading `role` and `active` with it.
    pattern = re.compile(r"\bFROM\s+" + _SESSIONS + r"\b", re.IGNORECASE)
    offenders = [
        str(path.relative_to(REPO_ROOT))
        for path in _sources()
        if path not in (SESSIONS_HOME, SELF)
        and "tests" not in path.parts
        and pattern.search(path.read_text(encoding="utf-8"))
    ]

    assert offenders == [], (
        f"A second session query outside {SESSIONS_HOME.relative_to(REPO_ROOT)} (AD-3): "
        + ", ".join(offenders)
    )


def test_only_one_module_writes_the_sessions_table() -> None:
    # The read guard above is matched on `FROM sessions`, which catches a
    # SELECT and a DELETE and cannot see an INSERT or an UPDATE. Story 1.5 gave
    # the request path its first write to this table (`_TOUCH_SESSION` slides
    # `last_seen_at`), and the security argument for the two-column shape is
    # that the touch writes `last_seen_at` and nothing else — so the absolute
    # bound, read from `issued_at`, is unreachable from the renewal path. That
    # argument is about which statements exist, and it survives only while they
    # all live in the one module somebody would think to check.
    pattern = re.compile(r"\b(?:UPDATE\s+|INSERT\s+INTO\s+)" + _SESSIONS + r"\b", re.IGNORECASE)
    offenders = [
        str(path.relative_to(REPO_ROOT))
        for path in _sources()
        if path not in (SESSIONS_HOME, SELF)
        and "tests" not in path.parts
        and pattern.search(path.read_text(encoding="utf-8"))
    ]

    assert offenders == [], (
        f"A session write outside {SESSIONS_HOME.relative_to(REPO_ROOT)} (AD-3): "
        + ", ".join(offenders)
    )


def test_only_one_module_writes_the_login_attempts_table() -> None:
    # AD-8: the failed-login counter is mutated by ONE atomic
    # increment-and-check. That property is about which statements exist — an
    # `UPDATE ... SET failure_count = %s` written somewhere else from a value
    # read a moment earlier is the lost update AD-8 names, and it would look
    # perfectly reasonable in the file that needed it. It survives only while
    # every write lives in the one module somebody would think to check.
    #
    # Reads are deliberately **not** guarded. Story 1.9 has to join this table
    # to render an account's lockout status, and a guard that forced that join
    # through here would be a guard argued with rather than obeyed.
    pattern = re.compile(
        r"\b(?:INSERT\s+INTO\s+|UPDATE\s+|DELETE\s+FROM\s+)" + _LOGIN_ATTEMPTS + r"\b",
        re.IGNORECASE,
    )
    offenders = [
        str(path.relative_to(REPO_ROOT))
        for path in _sources()
        if path not in (THROTTLE_HOME, SELF)
        and "tests" not in path.parts
        and pattern.search(path.read_text(encoding="utf-8"))
    ]

    assert offenders == [], (
        f"A failed-login counter write outside {THROTTLE_HOME.relative_to(REPO_ROOT)} (AD-8): "
        + ", ".join(offenders)
    )


@pytest.mark.parametrize(
    "line",
    [
        'conn.execute(f"SELECT * FROM users WHERE email = {email}")',
        'conn.execute("DELETE FROM " + table)',
        'query = "SELECT id FROM users WHERE name = %s" % name',
    ],
)
def test_the_sql_patterns_catch_what_they_are_for(line: str) -> None:
    # A guard nobody has seen fail is a guard nobody knows works.
    assert any(pattern.search(line) for pattern in INTERPOLATED_SQL)


@pytest.mark.parametrize(
    "line",
    [
        'conn.execute("SELECT id FROM users WHERE lower(email) = %s", (email,))',
        '_INSERT = "INSERT INTO sessions (user_id, token_hash) VALUES (%s, %s)"',
        'logger.info("selected %s rows from the catalogue", count)',
    ],
)
def test_the_sql_patterns_leave_parameterized_queries_alone(line: str) -> None:
    assert not any(pattern.search(line) for pattern in INTERPOLATED_SQL)
