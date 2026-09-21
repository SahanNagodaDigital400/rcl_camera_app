"""The runner's file planning, without a database.

These run everywhere, with or without PostgreSQL: a `down` file that does not
exist, or a migration that would sort into the wrong place, is a defect the
plan can catch on its own.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from psycopg import errors as pg_errors
from rocell_infra.migrate import (
    MIGRATIONS_DIR,
    PYTHON_STEPS,
    MigrationError,
    describe_target,
    discover_migrations,
    ensure_ledger,
    has_sql,
    python_step,
)


def write_pair(
    directory: Path, version: str, up: str = "SELECT 1;", down: str = "SELECT 1;"
) -> None:
    (directory / f"{version}.up.sql").write_text(up, encoding="utf-8")
    (directory / f"{version}.down.sql").write_text(down, encoding="utf-8")


def test_the_repository_migrations_are_a_valid_plan() -> None:
    plan = discover_migrations()

    assert [migration.version for migration in plan] == [
        "20260917T1200_create_users",
        "20260917T1210_seed_administrator",
        "20260917T1300_create_sessions",
        "20260917T1400_track_session_activity",
        "20260918T1000_add_login_throttling",
        "20260921T1000_create_audit_log",
    ]
    assert all(migration.up_path.is_file() for migration in plan)
    assert all(migration.down_path.is_file() for migration in plan)
    assert plan[0].up_path.parent == MIGRATIONS_DIR


def test_migrations_are_planned_in_lexicographic_order(tmp_path: Path) -> None:
    # Written out of order on purpose: a timestamp prefix only orders the plan
    # if the runner sorts by it rather than by directory iteration order.
    for version in ("20260917T1210_seed_administrator", "20260101T0900_create_users"):
        write_pair(tmp_path, version)

    assert [migration.version for migration in discover_migrations(tmp_path)] == [
        "20260101T0900_create_users",
        "20260917T1210_seed_administrator",
    ]


def test_an_empty_directory_plans_nothing(tmp_path: Path) -> None:
    assert discover_migrations(tmp_path) == ()


def test_a_gitkeep_is_not_a_migration(tmp_path: Path) -> None:
    (tmp_path / ".gitkeep").write_text("", encoding="utf-8")
    write_pair(tmp_path, "20260917T1200_create_users")

    assert len(discover_migrations(tmp_path)) == 1


def test_an_up_without_a_down_is_refused(tmp_path: Path) -> None:
    # Reversible is not optional; a missing `down` is found here rather than
    # halfway through a rollback.
    (tmp_path / "20260917T1200_create_users.up.sql").write_text("SELECT 1;", encoding="utf-8")

    with pytest.raises(MigrationError, match="no .down.sql file"):
        discover_migrations(tmp_path)


def test_a_down_without_an_up_is_refused(tmp_path: Path) -> None:
    (tmp_path / "20260917T1200_create_users.down.sql").write_text("SELECT 1;", encoding="utf-8")

    with pytest.raises(MigrationError, match="no matching .up.sql file"):
        discover_migrations(tmp_path)


@pytest.mark.parametrize(
    "name",
    [
        "create_users.up.sql",
        "1_create_users.up.sql",
        "20260917_create_users.up.sql",
        "20260917T1200.up.sql",
        "20260917T1200_CreateUsers.up.sql",
        "20260917t1200_create_users.up.sql",
    ],
)
def test_a_misnamed_migration_is_refused(tmp_path: Path, name: str) -> None:
    (tmp_path / name).write_text("SELECT 1;", encoding="utf-8")
    (tmp_path / name.replace(".up.sql", ".down.sql")).write_text("SELECT 1;", encoding="utf-8")

    with pytest.raises(MigrationError, match="misnamed"):
        discover_migrations(tmp_path)


@pytest.mark.parametrize("name", ["20260917T1200_create_users.sql", "notes.txt", "rollback.sql"])
def test_a_file_that_is_not_a_migration_is_refused(tmp_path: Path, name: str) -> None:
    # Silently ignoring it is the dangerous option: a file named `.sql` instead
    # of `.up.sql` would simply never run, and nothing would say so.
    (tmp_path / name).write_text("SELECT 1;", encoding="utf-8")

    with pytest.raises(MigrationError, match="is not a migration"):
        discover_migrations(tmp_path)


def test_a_missing_directory_is_refused(tmp_path: Path) -> None:
    with pytest.raises(MigrationError, match="No migrations directory"):
        discover_migrations(tmp_path / "nowhere")


def test_a_directory_inside_migrations_is_ignored(tmp_path: Path) -> None:
    (tmp_path / "archive").mkdir()
    write_pair(tmp_path, "20260917T1200_create_users")

    assert len(discover_migrations(tmp_path)) == 1


def test_plain_sql_names_no_python_step() -> None:
    assert python_step("CREATE TABLE users (id uuid);") is None
    assert python_step("-- calls rocell_infra.seed.seed_administrator\nSELECT 1;") is None


def test_the_seed_marker_names_its_step() -> None:
    body = (MIGRATIONS_DIR / "20260917T1210_seed_administrator.up.sql").read_text(encoding="utf-8")

    assert python_step(body) == "seed_administrator"
    assert python_step(body) in PYTHON_STEPS


def test_the_create_users_migration_is_plain_sql() -> None:
    body = (MIGRATIONS_DIR / "20260917T1200_create_users.up.sql").read_text(encoding="utf-8")

    assert python_step(body) is None
    assert "CREATE TABLE IF NOT EXISTS users" in body


@pytest.mark.parametrize("name", [".DS_Store", ".gitkeep", ".keep"])
def test_a_dotfile_is_not_a_migration(tmp_path: Path, name: str) -> None:
    # A stray .DS_Store — this repository has collected them before — would
    # otherwise make every command, `status` included, fail to plan at all.
    (tmp_path / name).write_text("", encoding="utf-8")
    write_pair(tmp_path, "20260917T1200_create_users")

    assert len(discover_migrations(tmp_path)) == 1


def test_a_body_of_only_comments_holds_no_sql() -> None:
    assert has_sql("-- just a note\n\n--another\n   \n") is False


@pytest.mark.parametrize(
    "body",
    ["SELECT 1;", "-- a note\nSELECT 1;", "\n\nCREATE TABLE t (id int);\n-- trailing\n"],
)
def test_a_body_with_a_statement_holds_sql(body: str) -> None:
    assert has_sql(body) is True


def test_the_seed_marker_carries_no_sql() -> None:
    body = (MIGRATIONS_DIR / "20260917T1210_seed_administrator.up.sql").read_text(encoding="utf-8")

    assert has_sql(body) is False


# --- Comments are comments, and a marker names one step ----------------------


def test_a_block_comment_header_is_not_sql() -> None:
    # `has_sql` decides whether a directive file also carries SQL that would be
    # silently skipped. Reading a `/* ... */` header as SQL refuses a legitimate
    # marker file with a message that is simply untrue.
    body = "/* An Argon2id digest cannot be computed in SQL,\n   so this file is a marker. */\n"
    assert has_sql(body + "-- rocell:python seed_administrator\n") is False


def test_a_block_comment_does_not_hide_real_sql() -> None:
    assert has_sql("/* a header */\nCREATE TABLE widgets (id int);\n") is True


def test_an_unterminated_block_comment_still_reads_as_sql() -> None:
    # Nothing closes it, so the substitution does not fire and the line stands.
    assert has_sql("/* opened and never closed\nCREATE TABLE widgets (id int);\n") is True


def test_a_directive_inside_a_block_comment_names_no_step() -> None:
    # `has_sql` strips block comments and the directive match did not, so the
    # two halves of the `_run_body` guard read the same file differently: a
    # marker commented out this way still named its step, and `has_sql` then
    # saw nothing, so the step ran anyway.
    body = "/* Not yet.\n-- rocell:python seed_administrator\n*/\n"

    assert python_step(body) is None
    assert has_sql(body) is False


def test_a_directive_quoted_beside_real_sql_names_no_step() -> None:
    # The same asymmetry from the other side: a plain SQL migration whose header
    # explains the marker convention was refused as "both a directive and SQL".
    body = "/* the seed uses\n-- rocell:python seed_administrator\n*/\nSELECT 1;\n"

    assert python_step(body) is None
    assert has_sql(body) is True


def test_two_directives_one_of_them_commented_out_is_not_a_conflict() -> None:
    body = "/* superseded:\n-- rocell:python other_step\n*/\n-- rocell:python seed_administrator\n"

    assert python_step(body) == "seed_administrator"


def test_a_body_naming_two_python_steps_is_refused() -> None:
    # Only the first would run and the ledger row would still be written — the
    # same silent partial application the directive-plus-SQL guard refuses.
    body = "-- rocell:python seed_administrator\n-- rocell:python seed_administrator\n"
    with pytest.raises(MigrationError, match="names 2 `rocell:python` steps"):
        python_step(body)


def test_the_refusal_names_the_file_when_the_caller_supplies_one() -> None:
    body = "-- rocell:python seed_administrator\n-- rocell:python other_step\n"
    with pytest.raises(MigrationError, match="20260101T0900_two_steps.up.sql"):
        python_step(body, "20260101T0900_two_steps.up.sql")


# --- The ledger's catalogue race ---------------------------------------------


class _FakeCursor:
    def __init__(self, row: tuple[object, ...] | None) -> None:
        self._row = row

    def fetchone(self) -> tuple[object, ...] | None:
        return self._row


class _RacingConnection:
    """Fails the ledger DDL the way a lost `CREATE TABLE` race does."""

    def __init__(self, *, table_exists: bool) -> None:
        self._table_exists = table_exists
        self.statements: list[str] = []

    def execute(self, statement: str, params: object = None) -> _FakeCursor:
        self.statements.append(statement)
        if "CREATE TABLE" in statement:
            raise pg_errors.DuplicateTable("relation already exists")
        return _FakeCursor(("schema_migrations",) if self._table_exists else (None,))


def test_a_lost_ledger_create_race_is_tolerated_when_the_table_is_there() -> None:
    # `CREATE TABLE IF NOT EXISTS` is not atomic against a concurrent one: both
    # sessions pass the existence check and the loser fails in the catalogue
    # with an error that says nothing about migrations. The table exists either
    # way, which is all `ensure_ledger` promises.
    conn = _RacingConnection(table_exists=True)
    ensure_ledger(conn)  # type: ignore[arg-type]
    assert any("to_regclass" in statement for statement in conn.statements)


def test_a_ledger_create_failure_with_no_table_still_raises() -> None:
    conn = _RacingConnection(table_exists=False)
    with pytest.raises(pg_errors.DuplicateTable):
        ensure_ledger(conn)  # type: ignore[arg-type]


# --- The console says which database it acted on -----------------------------


def test_the_target_description_names_host_and_database() -> None:
    url = "postgresql://rocell@db.internal:5432/rocell"
    assert describe_target(url) == "db.internal:5432/rocell"


def test_the_target_description_never_carries_the_password() -> None:
    # Every command here is destructive in proportion to which database it is
    # pointed at, so the target is printed — but a password on the console
    # reaches CI logs and scrollback.
    described = describe_target("postgresql://rocell:hunter2@db.internal:5432/rocell")
    assert "hunter2" not in described
    assert described == "db.internal:5432/rocell"


def test_an_unparseable_url_describes_itself_generically() -> None:
    assert describe_target("not a connection string") == "the configured database"
