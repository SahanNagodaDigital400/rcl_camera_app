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

#: The three AD-4 guards' surface, and wider than `SCANNED` on purpose.
#:
#: The interpolation rule above is written for value interpolation and `infra/`
#: is excused from it (see the module docstring). AD-4's rules are not about
#: how a statement is composed — they are about which statements exist at all,
#: and the part of the repository that most needs them is precisely the part
#: `SCANNED` leaves out: `infra/rocell_infra/migrate.py` connects with the
#: owner's own DSN and **no** `options=-c role=`, so it holds full DML on the
#: audit table and PostgreSQL will not refuse it anything. A retention purge —
#: the thing `deferred-work.md` says this table still needs — would land there
#: by default, outside both the grant and the guard.
AUDIT_SCANNED = (
    *SCANNED,
    REPO_ROOT / "infra",
    REPO_ROOT / "scripts",
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

#: The one file allowed to *write* the `scan_rate_limit` table (AD-8, Story 3.6).
SCAN_THROTTLE_HOME = REPO_ROOT / "apps" / "api" / "api" / "scan_throttle.py"

#: The one file allowed to *write* the `anomaly_baseline` table (AD-8, Story 3.7).
ANOMALY_HOME = REPO_ROOT / "apps" / "api" / "api" / "anomaly.py"

#: The one file allowed to name the audit table at all (AD-4).
#:
#: Stricter than the three above, and deliberately: `sessions` and
#: `login_attempts` are guarded against a second *write*, because a second read
#: of either is a reasonable thing a later story needs. This table's whole
#: invariant is about which statements exist against it, and the read surface
#: Story 1.13 shipped is a route and three `SELECT`s in this same module. A
#: file that merely mentions the table is a file that is about to write to it.
AUDIT_HOME = REPO_ROOT / "apps" / "api" / "api" / "audit.py"

# Never spelled out in one piece. See the module docstring.
_HASHER = "Password" + "Hasher"
_SESSIONS = "sessions"
_LOGIN_ATTEMPTS = "login_" + "attempts"
_SCAN_RATE_LIMIT = "scan_rate_" + "limit"
_ANOMALY_BASELINE = "anomaly_" + "baseline"
_AUDIT_LOG = "audit_" + "log"

#: The three verbs AD-4 forbids against the audit table, in the spellings SQL
#: writes them. `TRUNCATE` is here because it is neither an UPDATE nor a DELETE
#: and empties the table in one statement — the grant withholds it too, and a
#: guard that named only the other two would read as though it were allowed.
#:
#: **Matched against the whole file, not line by line**, which is why `\s+`
#: carries the weight it does: every SQL constant in this codebase is a
#: multi-line triple-quoted string, so the statement this guard is for would
#: almost certainly be written with its verb on one line and its table on the
#: next. A line-by-line scan reads `"""\nDELETE\n  FROM audit_log\n"""` as
#: clean, which is the shape the house style produces by default.
#:
#: `(?:public\.)?` because a schema-qualified `public.audit_log` is the same
#: table and the same violation.
_MUTATION_OF_THE_AUDIT_LOG = re.compile(
    r"\b(?:UPDATE|DELETE\s+FROM|TRUNCATE(?:\s+TABLE)?)\s+(?:public\.)?" + _AUDIT_LOG + r"\b",
    re.IGNORECASE,
)

#: Climbing back to the table owner from inside the application. `api.db` adopts
#: `rocell_app` through libpq's `options=-c role=`, which is a *startup* value —
#: so `RESET ROLE` returns to `rocell_app` rather than to the owner, and the
#: only way out is one of these three statements. None of them is parameterized
#: SQL, so no `%s` can reach them; what this guard stops is somebody writing one
#: on purpose, which is the one remaining hole in AD-4's enforcement.
#:
#: Matched against the whole file rather than line by line, for
#: `_MUTATION_OF_THE_AUDIT_LOG`'s reason: a multi-line triple-quoted
#: `"""\nSET ROLE rocell_owner\n"""` is the shape this codebase writes SQL in,
#: and a line-by-line scan reads it as clean.
#:
#: **No quote prefix, and comments are stripped before the scan instead.** An
#: earlier version required a quote earlier on the same line, so that it
#: matched only inside a string literal — this stopped `api/db.py`'s comment
#: explaining why it uses neither statement from tripping the rule it argues
#: for, since prose about a rule must not trip the rule. That is exactly the
#: narrowing a multi-line constant walks through, though, since the opening
#: quote is a line above the keyword. `_without_comments` below removes the
#: prose instead, which is both stricter and honest about what it is
#: excluding.
#:
#: `(?!\s*=)` on the first arm: `UPDATE users SET role = %s` is an ordinary
#: column write that happens to spell two of these words in a row, and the
#: statement is never followed by `=`.
_ROLE_ESCAPE = re.compile(
    r"\b(?:SET\s+ROLE\b(?!\s*=)|RESET\s+ROLE\b|SET\s+SESSION\s+AUTHORIZATION\b)",
    re.IGNORECASE,
)


def _without_comments(text: str) -> str:
    """`text` with whole-line `#` comments blanked, newlines preserved.

    Line numbers survive, so a match's offset still resolves to the line it
    is really on. Only whole-line comments go: a trailing `# ...` on a line
    of code is left alone, because a line that already carries code is a line
    the guards want to read anyway.
    """
    return "\n".join("" if line.lstrip().startswith("#") else line for line in text.splitlines())


def _at(text: str, offset: int) -> int:
    """The 1-indexed line a match at `offset` starts on.

    The two guards below read the whole file so a multi-line statement cannot
    hide from them; this is what keeps their failure messages in the
    `path:line` form every other guard here reports, which is the only form
    somebody can act on without re-grepping.
    """
    return text.count("\n", 0, offset) + 1


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


def _python_under(roots: tuple[Path, ...]) -> list[Path]:
    found: list[Path] = []
    for root in roots:
        for path in sorted(root.rglob("*.py")):
            if SKIPPED_DIRECTORIES.isdisjoint(part for part in path.parts):
                found.append(path)
    return found


def _sources() -> list[Path]:
    return _python_under(SCANNED)


def _audit_sources() -> list[Path]:
    """`_sources()` plus `infra/` and `scripts/`. See `AUDIT_SCANNED`."""
    return _python_under(AUDIT_SCANNED)


def test_the_scan_reaches_the_files_it_claims_to() -> None:
    # A guard over an empty file list passes forever. The paths below are the
    # ones every clause in this file is about — the three tables' owners, the
    # hasher, the pool that adopts the application role, and the two modules
    # that carry the most SQL — so the absence of any of them means the scan
    # has drifted off the code rather than that the code became clean.
    sources = _sources()
    assert len(sources) > 20
    for expected in (
        HASHER_HOME,
        SESSIONS_HOME,
        THROTTLE_HOME,
        SCAN_THROTTLE_HOME,
        ANOMALY_HOME,
        AUDIT_HOME,
        REPO_ROOT / "apps" / "api" / "api" / "db.py",
        # Story 1.8's provisioning write. Named for the same reason the four
        # above are: the SQL it carries is what the interpolation guard is for,
        # and a module that quietly fell outside `SCANNED` would be reported
        # clean without a byte of it being read.
        REPO_ROOT / "apps" / "api" / "api" / "users.py",
        REPO_ROOT / "apps" / "api" / "api" / "auth.py",
    ):
        assert expected in sources


def test_the_audit_scan_reaches_beyond_the_api_package() -> None:
    # The three AD-4 guards run over `AUDIT_SCANNED`, not `SCANNED`, and the
    # whole reason for the wider corpus is the migration runner: it opens its
    # connection from the owner's DSN with no `options=-c role=`, so the grant
    # model does not constrain it and only a guard can. Named here so that
    # narrowing the corpus back to the API package fails loudly instead of
    # quietly reporting `infra/` clean without reading a byte of it.
    sources = _audit_sources()
    assert set(_sources()) <= set(sources)
    for expected in (
        REPO_ROOT / "infra" / "rocell_infra" / "migrate.py",
        REPO_ROOT / "infra" / "rocell_infra" / "seed.py",
        REPO_ROOT / "scripts" / "ingest" / "ingest" / "__main__.py",
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


def test_only_one_module_writes_the_scan_rate_limit_table() -> None:
    # AD-8, Story 3.6: FR-23's scan throttle is mutated by ONE atomic
    # increment-and-check, `login_attempts`'s own shape. A second write
    # anywhere else is the same lost-update risk that guard exists to stop,
    # and it would look just as reasonable in whichever file needed one first.
    #
    # Reads are deliberately **not** guarded, for the same reason the login
    # counter's are not: a later story may need to join this table to render
    # status, and a guard forcing that join through here would be argued with
    # rather than obeyed.
    pattern = re.compile(
        r"\b(?:INSERT\s+INTO\s+|UPDATE\s+|DELETE\s+FROM\s+)" + _SCAN_RATE_LIMIT + r"\b",
        re.IGNORECASE,
    )
    offenders = [
        str(path.relative_to(REPO_ROOT))
        for path in _sources()
        if path not in (SCAN_THROTTLE_HOME, SELF)
        and "tests" not in path.parts
        and pattern.search(path.read_text(encoding="utf-8"))
    ]

    assert offenders == [], (
        f"A scan rate-limit counter write outside "
        f"{SCAN_THROTTLE_HOME.relative_to(REPO_ROOT)} (AD-8): " + ", ".join(offenders)
    )


def test_only_one_module_writes_the_anomaly_baseline_table() -> None:
    # AD-8, Story 3.7: FR-22's anomaly baseline is mutated by ONE atomic
    # increment-and-check, `test_only_one_module_writes_the_scan_rate_limit_
    # table`'s exact shape. A second write anywhere else is the same
    # lost-update risk that guard exists to stop.
    pattern = re.compile(
        r"\b(?:INSERT\s+INTO\s+|UPDATE\s+|DELETE\s+FROM\s+)" + _ANOMALY_BASELINE + r"\b",
        re.IGNORECASE,
    )
    offenders = [
        str(path.relative_to(REPO_ROOT))
        for path in _sources()
        if path not in (ANOMALY_HOME, SELF)
        and "tests" not in path.parts
        and pattern.search(path.read_text(encoding="utf-8"))
    ]

    assert offenders == [], (
        f"An anomaly-baseline write outside "
        f"{ANOMALY_HOME.relative_to(REPO_ROOT)} (AD-8): " + ", ".join(offenders)
    )


def test_only_one_module_names_the_audit_table() -> None:
    # AD-4. The immutability this story ships is a database grant, and the
    # reason it is a grant rather than a code convention is that a convention
    # cannot survive a file somebody adds later. This guard is the convention
    # anyway — belt to the grant's braces — and it is worth having because it
    # fails at `make test` rather than at 3am with an `InsufficientPrivilege`
    # from a route nobody has run yet.
    #
    # Tests are exempt: `test_audit_immutability.py` has to name the table to
    # prove PostgreSQL refuses a write to it, and `conftest.py` has to read it
    # back for every event assertion in the suite.
    pattern = re.compile(r"\b" + _AUDIT_LOG + r"\b", re.IGNORECASE)
    offenders = [
        str(path.relative_to(REPO_ROOT))
        for path in _audit_sources()
        if path not in (AUDIT_HOME, SELF)
        and "tests" not in path.parts
        and pattern.search(path.read_text(encoding="utf-8"))
    ]

    assert offenders == [], (
        f"A second file naming the audit table outside {AUDIT_HOME.relative_to(REPO_ROOT)} "
        "(AD-4): " + ", ".join(offenders)
    )


def test_nothing_mutates_the_audit_table() -> None:
    # The append-only rule, stated over the source as well as in the grant.
    # `AUDIT_HOME` is **not** exempt here — that is the whole point: the one
    # module allowed to name the table is still not allowed to update, delete
    # from or truncate it, and a corrective entry is an INSERT like any other
    # (AD-4).
    offenders = [
        f"{path.relative_to(REPO_ROOT)}:{_at(text, match.start())}"
        for path in _audit_sources()
        if path != SELF and "tests" not in path.parts
        for text in [path.read_text(encoding="utf-8")]
        for match in _MUTATION_OF_THE_AUDIT_LOG.finditer(text)
    ]

    assert offenders == [], (
        "An UPDATE, DELETE or TRUNCATE against the audit table. It is append-only "
        "(AD-4, AGENTS.md Policy) — correct a wrong entry by inserting a corrective "
        "one:\n" + "\n".join(offenders)
    )


def test_nothing_climbs_back_to_the_table_owner() -> None:
    # `api.db` adopts `rocell_app` as the connection's STARTUP role, so `RESET
    # ROLE` lands back on `rocell_app` and the grant model holds. What it does
    # not stop is a deliberate `SET ROLE <owner>` or `SET SESSION
    # AUTHORIZATION`, either of which hands the session every privilege AD-4
    # took away — including UPDATE and DELETE on the audit log. Those two
    # statements are the residual gap, and this is what keeps it closed.
    #
    # Tests are exempt for the reason they are exempt above: proving the
    # refusal means being able to stage the privileged case.
    offenders = [
        f"{path.relative_to(REPO_ROOT)}:{_at(text, match.start())}"
        for path in _audit_sources()
        if path != SELF and "tests" not in path.parts
        for text in [_without_comments(path.read_text(encoding="utf-8"))]
        for match in _ROLE_ESCAPE.finditer(text)
    ]

    assert offenders == [], (
        "A role change from application code. The pool adopts `rocell_app` at "
        "connection startup and nothing may climb out of it (AD-4):\n" + "\n".join(offenders)
    )


@pytest.mark.parametrize(
    "line",
    [
        'conn.execute("UPDATE ' + _AUDIT_LOG + ' SET action = %s", (action,))',
        'conn.execute("DELETE FROM ' + _AUDIT_LOG + ' WHERE created_at < %s", (cutoff,))',
        'conn.execute("TRUNCATE ' + _AUDIT_LOG + '")',
        'conn.execute("truncate table ' + _AUDIT_LOG + ' cascade")',
        # Schema-qualified: the same table and the same violation.
        'conn.execute("DELETE FROM public.' + _AUDIT_LOG + '")',
        'conn.execute("UPDATE public.' + _AUDIT_LOG + ' SET details = %s", (details,))',
        # **The shape this codebase would actually produce.** Every SQL
        # constant here is a multi-line triple-quoted string, so a mutation
        # written in the house style puts the verb and the table on different
        # lines — and a line-by-line guard reads all three of these as clean.
        '_PURGE = """\nDELETE\n  FROM ' + _AUDIT_LOG + '\n WHERE created_at < %s\n"""',
        '_FIX = """\nUPDATE\n    ' + _AUDIT_LOG + '\n   SET action = %s\n"""',
        '_WIPE = """\nTRUNCATE TABLE\n    public.' + _AUDIT_LOG + '\n"""',
    ],
)
def test_the_audit_mutation_pattern_catches_what_it_is_for(line: str) -> None:
    # A guard nobody has seen fail is a guard nobody knows works.
    assert _MUTATION_OF_THE_AUDIT_LOG.search(line)


@pytest.mark.parametrize(
    "line",
    [
        '_INSERT = "INSERT INTO ' + _AUDIT_LOG + ' (action) VALUES (%s)"',
        '_SELECT = "SELECT action FROM ' + _AUDIT_LOG + ' ORDER BY created_at DESC"',
        'conn.execute("UPDATE users SET active = false WHERE id = %s", (user_id,))',
        # A multi-line append and a multi-line read: the whole-file scan must
        # not start flagging the statements the grant actually permits.
        '_APPEND = """\nINSERT INTO ' + _AUDIT_LOG + ' (action)\nVALUES (%s)\n"""',
        '_READ = """\nSELECT action\n  FROM ' + _AUDIT_LOG + '\n ORDER BY created_at\n"""',
    ],
)
def test_the_audit_mutation_pattern_leaves_appends_and_reads_alone(line: str) -> None:
    assert not _MUTATION_OF_THE_AUDIT_LOG.search(line)


@pytest.mark.parametrize(
    "line",
    [
        'conn.execute("SET ROLE rocell_owner")',
        'conn.execute("reset role")',
        'conn.execute("SET SESSION AUTHORIZATION postgres")',
        '_ESCAPE = """\nSET ROLE rocell_owner\n"""',
    ],
)
def test_the_role_escape_pattern_catches_what_it_is_for(line: str) -> None:
    assert _ROLE_ESCAPE.search(line)


@pytest.mark.parametrize(
    "line",
    [
        'CONNECTION_OPTIONS = "-c role=" + APPLICATION_ROLE',
        'kwargs={"autocommit": True, "options": CONNECTION_OPTIONS}',
        'conn.execute("UPDATE users SET role = %s WHERE id = %s", (role, user_id))',
    ],
)
def test_the_role_escape_pattern_leaves_the_startup_option_alone(line: str) -> None:
    # `api.db`'s own line must read clean, or the guard is one somebody has to
    # argue with rather than obey.
    assert not _ROLE_ESCAPE.search(line)


@pytest.mark.parametrize(
    "text",
    [
        "#: `-c role=` rather than a SET ROLE in the pool's configure hook, because\n"
        "#: RESET ROLE returns to the startup value and cannot reach the owner.\n",
        "    # SET SESSION AUTHORIZATION is the residual gap this guard closes.\n",
    ],
)
def test_the_role_escape_scan_reads_past_prose_about_the_rule(text: str) -> None:
    # `api/db.py` explains at length why it uses `-c role=` and not either
    # statement, naming both. The scan strips whole-line comments so the
    # argument for a rule is never flagged by the rule — which is what makes
    # this guard one somebody can obey rather than work around by not writing
    # the comment.
    assert not _ROLE_ESCAPE.search(_without_comments(text))


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


# --- AD-7's "no shortcut for bulk" (Story 2.4) --------------------------------


#: The functions that make up the bulk path, read by `inspect.getsource`.
#:
#: Named as objects rather than matched as a slice of the file, because a slice
#: is a line range somebody has to keep in step with an edit and this is not.
#: If a helper is added to that path it belongs in this tuple, and the reader
#: who adds it is the reader who is about to be told why.
_BULK_FUNCTION_NAMES = (
    "bulk_upload",
    "_bulk_stream",
    "_bulk_row",
    "_manifest_rows",
    "_read_manifest",
    "_spool",
    "_row_line",
)

#: The only `shared_vision` attribute the bulk path may name directly.
#:
#: A path, checked for existence before the stream opens so that a deployment
#: with no model artifact refuses the whole batch with an envelope rather than
#: failing a hundred rows identically. It is not a step in the pipeline and
#: nothing about it turns bytes into pixels.
_BULK_MAY_NAME = {"MODEL_PATH"}

_SHARED_VISION_ATTRIBUTE = re.compile(r"\bshared_vision\.([A-Za-z_][A-Za-z0-9_]*)")


def test_the_bulk_path_reaches_the_pixel_pipeline_only_through_the_add_s_helpers() -> None:
    # **The story's central invariant, and the one that fails silently.**
    # Epic 2's context is explicit that every image byte is intaken the same
    # way "with no shortcut for bulk" (AD-7), and AD-1 is the same rule one
    # level down: index-time and query-time preprocessing must be identical.
    # A bulk handler that called the intake, the view generator or the embedder
    # itself would still produce embeddings, still write rows, and still pass
    # every behavioural test in the suite — while quietly indexing a second
    # pipeline's vectors alongside the first. Nothing raises. This does.
    #
    # Read off the functions' own source rather than the whole module, because
    # `_accept_bytes` and `_prepare` — the two halves the bulk path is *meant*
    # to reach the pipeline through — legitimately name it on every line.
    import inspect

    from api import catalogue

    offenders: list[str] = []
    for name in _BULK_FUNCTION_NAMES:
        function = getattr(catalogue, name, None)
        assert function is not None, (
            f"api.catalogue.{name} no longer exists, so this guard is reading nothing. "
            "Rename it here or say why the bulk path no longer has it."
        )
        source = inspect.getsource(function)
        offenders.extend(
            f"{name}: shared_vision.{attribute}"
            for attribute in _SHARED_VISION_ATTRIBUTE.findall(source)
            if attribute not in _BULK_MAY_NAME
        )

    assert offenders == [], (
        "The bulk path reaches shared_vision on its own. Every image it takes must "
        "go through _accept_bytes and _prepare — the same intake, colour management, "
        "16 views and derivative the single add uses (AD-1, AD-7). A second path is "
        "an asymmetry that destroys accuracy with nothing raised: " + ", ".join(offenders)
    )


def test_the_bulk_guard_catches_a_second_path() -> None:
    # A guard nobody has seen fail is a guard nobody knows works. This is the
    # shortcut in miniature: a handler embedding for itself rather than through
    # the add's own helpers.
    shortcut = "    accepted = shared_vision.intake_image(data)\n"

    assert [
        attribute
        for attribute in _SHARED_VISION_ATTRIBUTE.findall(shortcut)
        if attribute not in _BULK_MAY_NAME
    ] == ["intake_image"]
