"""The migration runner: a ledger table and a loop.

`infra/README.md` fixed the format before the first migration was written —
timestamp-prefixed plain-SQL files, one concern each, every one with a `down`
that restores the previous shape. This module is what applies them.

Not Alembic, and no ORM: that would replace the recorded convention with Python
revision chains and pull SQLAlchemy into a project whose only other SQL
consumer has no ORM either.

Each migration and its ledger row commit **together**::

    BEGIN;
      -- <contents of NNN_verb.up.sql>
      INSERT INTO schema_migrations (version) VALUES (%s);
    COMMIT;

so a failure halfway leaves neither, and the next run retries from a clean
state rather than skipping a migration that only half-applied.

Commands (`python -m rocell_infra.migrate <command>`):

``up``            apply every unapplied migration, in filename order
``down --yes``    revert the most recently applied migration, one step
``status``        list every migration and whether it is applied
``reseed-admin``  reissue the seeded Administrator's temporary credential
"""

from __future__ import annotations

import re
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC
from pathlib import Path

import psycopg
from psycopg import errors as pg_errors
from psycopg.conninfo import conninfo_to_dict

from rocell_infra import seed
from rocell_infra.config import ConfigurationError, database_url
from rocell_infra.seed import SeedRefused

#: `infra/migrations/`, resolved from this file so the runner works from any
#: working directory.
MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"

UP_SUFFIX = ".up.sql"
DOWN_SUFFIX = ".down.sql"

#: `20260917T1200_create_users` — a UTC timestamp prefix and a short verb
#: phrase, as `infra/README.md` requires. Enforced here rather than trusted, so
#: a file that would sort into the wrong place is a loud failure.
VERSION_PATTERN = re.compile(r"^\d{8}T\d{4}_[a-z0-9]+(?:_[a-z0-9]+)*$")

#: An Argon2id digest cannot be computed in SQL. A migration whose `up` file
#: carries this directive is a marker: the runner calls the named step inside
#: that migration's transaction instead of executing the file as SQL.
PYTHON_DIRECTIVE = re.compile(r"^--\s*rocell:python\s+([a-z_][a-z0-9_]*)\s*$", re.MULTILINE)

#: `/* ... */` is a comment too. Without this, `has_sql` reads a block-comment
#: header as SQL and refuses a legitimate marker file with a message that is
#: simply untrue.
BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)

#: The complete set of steps a migration may name. Anything else is an error,
#: not an import.
PYTHON_STEPS: dict[str, Callable[[psycopg.Connection], object]] = {
    "seed_administrator": seed.seed_administrator,
}

LEDGER_DDL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version text PRIMARY KEY,
    applied_at timestamptz NOT NULL DEFAULT now()
)
"""

_INSERT_LEDGER_ROW = "INSERT INTO schema_migrations (version) VALUES (%s)"
_DELETE_LEDGER_ROW = "DELETE FROM schema_migrations WHERE version = %s"
_SELECT_APPLIED = "SELECT version FROM schema_migrations ORDER BY version"
_IS_APPLIED = "SELECT 1 FROM schema_migrations WHERE version = %s"
#: The ledger records `applied_at` and this is what reads it. Stepping down the
#: *lexicographically* last version would revert the wrong migration whenever
#: one merged from a branch carries an earlier timestamp than what is already
#: applied — `down` must undo what happened last, not what sorts last.
_SELECT_LAST_APPLIED = """
SELECT version
  FROM schema_migrations
 ORDER BY applied_at DESC, version DESC
 LIMIT 1
"""

#: A session-independent lock, held for the duration of each migration's
#: transaction, so two `make migrate` runs against one database serialise
#: instead of racing. This is the **third** layer behind the ledger and the
#: seed's own guard: those two stop a *sequential* re-run from producing a
#: second Administrator, but two concurrent runners can both observe an empty
#: `users` table and both insert — and with different `SEED_ADMIN_EMAIL` values
#: the unique index on `lower(email)` does not catch it either.
MIGRATION_LOCK_ID = 0x524F43454C4C  # b"ROCELL"

_ADVISORY_LOCK = "SELECT pg_advisory_xact_lock(%s)"

#: How long to wait for that lock before giving up. `pg_advisory_xact_lock`
#: waits forever by default, so a runner stuck behind a hung migration — or an
#: `psql` session someone left holding the lock — turns `make migrate` into the
#: silent hang `CONNECT_TIMEOUT_SECONDS` exists to prevent, one layer further in.
LOCK_TIMEOUT_MS = 30_000

#: `SET` takes no parameters; `set_config` does, and the third argument makes it
#: local to the surrounding transaction.
_SET_LOCK_TIMEOUT = "SELECT set_config('lock_timeout', %s, true)"

#: Confirms the ledger is really there when a concurrent `CREATE TABLE IF NOT
#: EXISTS` lost the catalogue race. `to_regclass` returns NULL rather than
#: raising for a name that does not resolve.
_LEDGER_EXISTS = "SELECT to_regclass('schema_migrations')"

#: Without this, `make migrate` against an unreachable host hangs with no
#: output at all and no indication of which half is at fault.
CONNECT_TIMEOUT_SECONDS = 10

COMMANDS = ("up", "down", "status", "reseed-admin")

#: `down` drops tables. Requiring the flag means a mistyped or copy-pasted
#: command against a production URL does nothing.
CONFIRM_FLAG = "--yes"

USAGE = f"usage: python -m rocell_infra.migrate [up | down {CONFIRM_FLAG} | status | reseed-admin]"


class MigrationError(RuntimeError):
    """A migration could not be planned or applied."""


@dataclass(frozen=True, slots=True)
class Migration:
    """One migration: its version and the two files that make it reversible."""

    version: str
    up_path: Path
    down_path: Path


def discover_migrations(directory: Path = MIGRATIONS_DIR) -> tuple[Migration, ...]:
    """Plan the migrations in `directory`, in filename order.

    Every `.up.sql` must have a matching `.down.sql` and vice versa: forward-only
    *and reversible* is the recorded convention, and a `down` that does not exist
    is discovered here rather than at 2am with a half-applied deployment.

    Every dotfile is skipped, not just `.gitkeep`: a stray `.DS_Store` — this
    repository has collected them before — would otherwise make *every* command,
    `status` included, fail to plan at all.
    """
    if not directory.is_dir():
        raise MigrationError(f"No migrations directory at {directory}")

    ups: dict[str, Path] = {}
    downs: dict[str, Path] = {}

    for path in sorted(directory.iterdir()):
        if path.is_dir() or path.name.startswith("."):
            continue

        if path.name.endswith(UP_SUFFIX):
            bucket, version = ups, path.name[: -len(UP_SUFFIX)]
        elif path.name.endswith(DOWN_SUFFIX):
            bucket, version = downs, path.name[: -len(DOWN_SUFFIX)]
        else:
            raise MigrationError(
                f"{path.name} is not a migration: every file in {directory.name}/ must be "
                f"named <version>{UP_SUFFIX} or <version>{DOWN_SUFFIX}"
            )

        if not VERSION_PATTERN.match(version):
            raise MigrationError(
                f"{path.name} is misnamed: the version must be a UTC timestamp and a short "
                f"verb phrase, e.g. 20260917T1200_create_users{UP_SUFFIX}"
            )

        bucket[version] = path

    for version in sorted(ups):
        if version not in downs:
            raise MigrationError(
                f"{version} has no {DOWN_SUFFIX} file. Migrations are reversible; a `down` "
                f"that restores the previous shape is not optional."
            )
    for version in sorted(downs):
        if version not in ups:
            raise MigrationError(f"{version}{DOWN_SUFFIX} has no matching {UP_SUFFIX} file.")

    return tuple(
        Migration(version=version, up_path=ups[version], down_path=downs[version])
        for version in sorted(ups)
    )


def python_step(sql_text: str, source: str = "A migration body") -> str | None:
    """The name of the Python step this migration body delegates to, if any.

    Block comments are stripped first, for the same reason `has_sql` strips
    them: `/* ... */` is a comment, so a directive commented *out* inside one
    does not name a step. Matching the raw text instead made the two halves of
    the `_run_body` guard read the same file differently — a disabled marker
    still ran its step, and a real SQL migration whose block-comment header
    merely quoted the directive was refused with a message that was untrue.

    At most one: a second directive would be read and dropped, so the migration
    would run half of what it names while its ledger row recorded the whole of
    it — the same silent partial application the directive-plus-SQL guard in
    `_run_body` refuses.
    """
    matches = PYTHON_DIRECTIVE.findall(BLOCK_COMMENT.sub("", sql_text))
    if len(matches) > 1:
        raise MigrationError(
            f"{source} names {len(matches)} `rocell:python` steps ({', '.join(matches)}); "
            f"at most one is allowed. Only the first would run and the ledger row would "
            f"still be written. Split it into separate migrations."
        )
    return matches[0] if matches else None


def ensure_ledger(conn: psycopg.Connection) -> None:
    """Create `schema_migrations` if it is not there yet.

    This runs *before* any migration takes the advisory lock, because the lock
    is held per migration transaction and the ledger is what those transactions
    write to. `CREATE TABLE IF NOT EXISTS` is not atomic against a concurrent
    one: both sessions can pass the existence check and the loser fails in the
    catalogue with a `pg_type` unique violation that says nothing about
    migrations. The table exists either way, which is all this promises.

    Expects an autocommit connection — the recovery read runs on the same
    connection as the failed `CREATE TABLE`, and inside an open transaction
    that statement would abort with `InFailedSqlTransaction` and mask the
    original error. Every command here connects with `autocommit=True` and
    opens an explicit transaction per migration for exactly this reason.
    """
    try:
        conn.execute(LEDGER_DDL)
    except (pg_errors.UniqueViolation, pg_errors.DuplicateTable):
        if conn.execute(_LEDGER_EXISTS).fetchone()[0] is None:
            raise


def applied_versions(conn: psycopg.Connection) -> list[str]:
    """Every version the ledger records as applied, in order."""
    return [row[0] for row in conn.execute(_SELECT_APPLIED).fetchall()]


def has_sql(sql_text: str) -> bool:
    """Whether a migration body holds anything but comments and blank lines."""
    for line in BLOCK_COMMENT.sub("", sql_text).splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("--"):
            return True
    return False


def _run_body(conn: psycopg.Connection, path: Path) -> None:
    body = path.read_text(encoding="utf-8")
    step_name = python_step(body, path.name)

    if step_name is None:
        # Neither SQL nor a directive: an empty file, or a marker whose
        # directive was commented out. Executing it would do nothing while the
        # ledger row recorded it as applied — the silent no-op this pair of
        # guards exists to refuse, from the other side.
        if not has_sql(body):
            raise MigrationError(
                f"{path.name} holds no SQL and names no `rocell:python` step, so applying it "
                f"would do nothing while its ledger row recorded it as applied. If a directive "
                f"is commented out, remove the file or the comment."
            )
        conn.execute(body)
        return

    # A directive file is a *marker*, and a marker that also carried real SQL
    # would have that SQL silently skipped while its ledger row was still
    # written — the migration would read as applied and have done nothing. A
    # migration that needs both is two migrations.
    if has_sql(body):
        raise MigrationError(
            f"{path.name} carries both a `rocell:python` directive and SQL. A directive file "
            f"is a marker and its SQL would never run; split it into two migrations."
        )

    step = PYTHON_STEPS.get(step_name)
    if step is None:
        raise MigrationError(
            f"{path.name} names the step {step_name!r}, which the runner does not know. "
            f"Known steps: {', '.join(sorted(PYTHON_STEPS)) or '(none)'}."
        )
    step(conn)


def _take_lock(conn: psycopg.Connection) -> None:
    """Serialise this transaction against every other runner, or say why not."""
    conn.execute(_SET_LOCK_TIMEOUT, (f"{LOCK_TIMEOUT_MS}ms",))
    try:
        conn.execute(_ADVISORY_LOCK, (MIGRATION_LOCK_ID,))
    except (pg_errors.LockNotAvailable, pg_errors.QueryCanceled) as busy:
        raise MigrationError(
            f"Another migration runner has held the lock on this database for more than "
            f"{LOCK_TIMEOUT_MS}ms. Nothing was applied. Wait for it to finish and re-run."
        ) from busy


def _is_applied(conn: psycopg.Connection, version: str) -> bool:
    return conn.execute(_IS_APPLIED, (version,)).fetchone() is not None


def _apply(conn: psycopg.Connection, migration: Migration) -> bool:
    """Apply one migration and its ledger row in a single transaction."""
    try:
        with conn.transaction():
            _take_lock(conn)
            # Re-read the ledger *under the lock*: a concurrent runner may have
            # applied this migration since the plan above was drawn up, and
            # applying it twice would at best duplicate work and at worst
            # duplicate a row the second layer cannot catch.
            if _is_applied(conn, migration.version):
                return False
            _run_body(conn, migration.up_path)
            conn.execute(_INSERT_LEDGER_ROW, (migration.version,))
    except MigrationError:
        raise
    except Exception as exc:
        raise MigrationError(f"{migration.up_path.name} failed: {exc}") from exc

    return True


def up(conn: psycopg.Connection, migrations: Sequence[Migration] | None = None) -> list[str]:
    """Apply every unapplied migration. Returns the versions applied this run."""
    plan = discover_migrations() if migrations is None else migrations

    ensure_ledger(conn)
    already = set(applied_versions(conn))

    newly_applied: list[str] = []
    for migration in plan:
        if migration.version in already:
            continue
        if _apply(conn, migration):
            newly_applied.append(migration.version)

    return newly_applied


def down(conn: psycopg.Connection, migrations: Sequence[Migration] | None = None) -> str | None:
    """Revert the most recently applied migration. Returns its version, or None.

    "Most recently applied" is read from `applied_at`, not from where the
    version sorts — see `_SELECT_LAST_APPLIED`.
    """
    plan = discover_migrations() if migrations is None else migrations
    by_version = {migration.version: migration for migration in plan}

    ensure_ledger(conn)

    down_name = "the down migration"
    try:
        with conn.transaction():
            _take_lock(conn)
            # Read the ledger *under the lock*, for the same reason `_apply`
            # re-reads it. Two concurrent `down` runs that both read first would
            # serialise here and then both revert the same version — the second
            # running a down body against a shape already restored, and deleting
            # a ledger row that is no longer there.
            last = conn.execute(_SELECT_LAST_APPLIED).fetchone()
            if last is None:
                return None

            version = str(last[0])
            migration = by_version.get(version)
            if migration is None:
                raise MigrationError(
                    f"{version} is recorded as applied but has no files in "
                    f"{MIGRATIONS_DIR.name}/. Restore them before stepping down."
                )

            down_name = migration.down_path.name
            _run_body(conn, migration.down_path)
            conn.execute(_DELETE_LEDGER_ROW, (version,))
    except MigrationError:
        raise
    except Exception as exc:
        raise MigrationError(f"{down_name} failed: {exc}") from exc

    return version


def status(
    conn: psycopg.Connection, migrations: Sequence[Migration] | None = None
) -> list[tuple[str, bool]]:
    """Every migration and whether the ledger records it as applied."""
    plan = discover_migrations() if migrations is None else migrations

    ensure_ledger(conn)
    already = set(applied_versions(conn))

    return [(migration.version, migration.version in already) for migration in plan]


def reseed_admin(conn: psycopg.Connection) -> None:
    """Reissue the seeded Administrator's temporary credential. See `seed.py`.

    Under the migration lock, like everything else that writes here: two
    concurrent reseeds would both pass the "still unclaimed, still the only
    one" guard and both write, and the operator holding the first password
    would be told it works when it no longer does.
    """
    with conn.transaction():
        _take_lock(conn)
        seed.reseed_administrator(conn)


def describe_target(url: str) -> str:
    """`host:port/dbname` for the console — never the password.

    Every command here is destructive in proportion to which database it is
    pointed at, and `DATABASE_URL` is deliberately never defaulted for exactly
    that reason. Saying nothing about the target made two URLs in a shell
    history produce identical output.
    """
    try:
        info = conninfo_to_dict(url)
    except psycopg.Error:
        return "the configured database"

    host = str(info.get("host") or "localhost")
    dbname = str(info.get("dbname") or "?")
    port = info.get("port")
    return f"{host}:{port}/{dbname}" if port else f"{host}/{dbname}"


def _report_up(applied: list[str]) -> None:
    if not applied:
        print("migrate: nothing to apply; the database is up to date.")
        return
    for version in applied:
        print(f"migrate: applied {version}")


def _report_credential(conn: psycopg.Connection) -> None:
    """Say who the unclaimed credential belongs to and when it dies.

    The 72-hour window is the most time-critical fact about the seeded
    Administrator and the address is what the operator has to type; neither
    reached the console before, so both had to be read out of the database.
    """
    record = seed.unclaimed_administrator(conn)
    if record is None:
        return
    email, expires_at = record
    # `reseed-admin` refuses once a second Administrator exists, so advising it
    # where it would refuse sends the operator at a command that cannot help:
    # on an already-migrated database the unclaimed row this reads may be one an
    # Administrator created, not the seeded one.
    remedy = (
        " — after that, `make reseed-admin`."
        if seed.administrator_count(conn) == 1
        else ". Once it expires, another Administrator can reissue it."
    )
    print(
        f"migrate: {email} must sign in and set a password before "
        f"{expires_at.astimezone(UTC):%Y-%m-%d %H:%M UTC}{remedy}"
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Dispatch one command. Returns the process exit code."""
    args = list(sys.argv[1:] if argv is None else argv)
    command = args[0] if args else "up"
    flags = args[1:]

    if command in {"-h", "--help", "help"}:
        print(USAGE)
        return 0
    if command not in COMMANDS:
        print(USAGE, file=sys.stderr)
        return 2
    if flags and not (command == "down" and flags == [CONFIRM_FLAG]):
        print(USAGE, file=sys.stderr)
        return 2

    # `down` runs the migration's own down SQL, and two of them drop `users`
    # with every account in it. It is documented as an ordinary operator
    # command, so it must not be one keystroke away from destroying a live
    # database.
    if command == "down" and flags != [CONFIRM_FLAG]:
        print(
            f"migrate: refusing to step down without {CONFIRM_FLAG}. `down` runs the "
            f"migration's own down SQL, which drops what the `up` created — against a "
            f"live database that is every account in it. Re-run: "
            f"python -m rocell_infra.migrate down {CONFIRM_FLAG}",
            file=sys.stderr,
        )
        return 1

    try:
        url = database_url()
        plan = discover_migrations()

        # autocommit, so the ledger DDL lands immediately and every migration
        # body runs inside an explicit `conn.transaction()` block of its own.
        # Flushed: stdout is block-buffered when piped, and without this the
        # target line lands *after* an unbuffered stderr refusal, so a captured
        # log reads as though the command failed before it chose a database.
        print(f"migrate: target {describe_target(url)}", flush=True)

        with psycopg.connect(url, autocommit=True, connect_timeout=CONNECT_TIMEOUT_SECONDS) as conn:
            if command == "up":
                _report_up(up(conn, plan))
                _report_credential(conn)
            elif command == "down":
                reverted = down(conn, plan)
                print(
                    "migrate: nothing to revert."
                    if reverted is None
                    else f"migrate: reverted {reverted}"
                )
            elif command == "status":
                for version, is_applied in status(conn, plan):
                    print(f"{'applied' if is_applied else 'pending':>8}  {version}")
            else:
                reseed_admin(conn)
                print("migrate: reissued the seeded Administrator's temporary credential.")
                _report_credential(conn)
    except (ConfigurationError, MigrationError, SeedRefused) as exc:
        print(f"migrate: {exc}", file=sys.stderr)
        return 1
    except psycopg.Error as exc:
        print(f"migrate: database error: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":  # pragma: no cover - the console entry point
    raise SystemExit(main())
