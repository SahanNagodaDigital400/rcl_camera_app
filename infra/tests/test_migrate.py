"""The migration runner against a real PostgreSQL.

Every password here is generated at runtime with `secrets`. AGENTS.md Policy
forbids a committed credential including in test fixtures, and a literal in
this file would be one — `make migrate`'s own acceptance criteria say the
seeded password must appear in no source file, test, fixture or migration.
"""

from __future__ import annotations

import secrets
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path

import psycopg
import pytest
from psycopg import errors as pg_errors
from rocell_infra import migrate, seed
from rocell_infra.config import (
    SEED_ADMIN_EMAIL,
    SEED_ADMIN_NAME,
    SEED_ADMIN_PASSWORD,
    ConfigurationError,
)
from rocell_infra.migrate import MigrationError, discover_migrations, down, status, up
from shared_schema.passwords import (
    ARGON2ID_PREFIX,
    MAX_PASSWORD_LENGTH,
    MIN_PASSWORD_LENGTH,
    verify_password,
)

SEED_VERSION = "20260917T1210_seed_administrator"
CREATE_USERS_VERSION = "20260917T1200_create_users"
CREATE_SESSIONS_VERSION = "20260917T1300_create_sessions"
TRACK_ACTIVITY_VERSION = "20260917T1400_track_session_activity"
LOGIN_THROTTLING_VERSION = "20260918T1000_add_login_throttling"
AUDIT_LOG_VERSION = "20260921T1000_create_audit_log"
CATALOGUE_VERSION = "20260921T1500_create_catalogue"
SCAN_VERSION = "20260922T1900_create_scan"
SCAN_RATE_LIMIT_VERSION = "20260922T2000_create_scan_rate_limit"
ANOMALY_BASELINE_VERSION = "20260923T1000_create_anomaly_baseline"
AUDIT_LOG_FLAGGED_INDEX_VERSION = "20260923T1010_add_audit_log_flagged_index"

#: Every migration in `infra/migrations`, in the order the runner applies
#: them. Listed once so adding a migration is one edit here rather than a
#: sweep through every assertion in this file.
ALL_VERSIONS = [
    CREATE_USERS_VERSION,
    SEED_VERSION,
    CREATE_SESSIONS_VERSION,
    TRACK_ACTIVITY_VERSION,
    LOGIN_THROTTLING_VERSION,
    AUDIT_LOG_VERSION,
    CATALOGUE_VERSION,
    SCAN_VERSION,
    SCAN_RATE_LIMIT_VERSION,
    ANOMALY_BASELINE_VERSION,
    AUDIT_LOG_FLAGGED_INDEX_VERSION,
]

SEED_EMAIL = "ruwan@rocell.lk"


def a_password(length: int = MIN_PASSWORD_LENGTH + 8) -> str:
    """A password of exactly `length` characters, never the same one twice."""
    return secrets.token_urlsafe(length * 2)[:length]


@pytest.fixture
def seed_password(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """Set the seed environment for one test and return its password."""
    password = a_password()
    monkeypatch.setenv(SEED_ADMIN_EMAIL, SEED_EMAIL)
    monkeypatch.setenv(SEED_ADMIN_PASSWORD, password)
    monkeypatch.setenv(SEED_ADMIN_NAME, "Ruwan Perera")
    yield password


def administrator_count(conn: psycopg.Connection) -> int:
    row = conn.execute("SELECT count(*) FROM users WHERE role = %s", ("admin",)).fetchone()
    assert row is not None
    return int(row[0])


def the_administrator(conn: psycopg.Connection) -> dict[str, object]:
    cursor = conn.execute(
        """
        SELECT id, name, email, password_hash, role, active, must_change_password,
               temp_credential_expires_at, last_login_at, created_at, updated_at
          FROM users
         WHERE role = %s
        """,
        ("admin",),
    )
    row = cursor.fetchone()
    assert row is not None
    assert cursor.description is not None
    return {column.name: value for column, value in zip(cursor.description, row, strict=True)}


def table_columns(conn: psycopg.Connection, table: str) -> set[str]:
    rows = conn.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name = %s",
        (table,),
    ).fetchall()
    return {row[0] for row in rows}


def ledger_versions(conn: psycopg.Connection) -> list[str]:
    return [row[0] for row in conn.execute(migrate._SELECT_APPLIED).fetchall()]


# --- First run ---------------------------------------------------------------


def test_a_clean_database_gets_the_user_table(conn: psycopg.Connection, seed_password: str) -> None:
    applied = up(conn)

    assert applied == ALL_VERSIONS

    columns = table_columns(conn, "users")
    assert {"role", "active", "must_change_password", "temp_credential_expires_at"} <= columns
    assert {"id", "name", "email", "password_hash", "last_login_at"} <= columns
    assert table_columns(conn, "schema_migrations") == {"version", "applied_at"}


def test_exactly_one_administrator_is_seeded(conn: psycopg.Connection, seed_password: str) -> None:
    up(conn)

    assert administrator_count(conn) == 1

    administrator = the_administrator(conn)
    assert administrator["must_change_password"] is True
    assert administrator["active"] is True
    assert administrator["email"] == SEED_EMAIL
    assert administrator["name"] == "Ruwan Perera"
    assert administrator["last_login_at"] is None


def test_the_seeded_password_verifies_through_the_shared_helper(
    conn: psycopg.Connection, seed_password: str
) -> None:
    # The whole point of one shared hasher: what the seed wrote is what Story
    # 1.3's verifier will read.
    up(conn)
    stored = str(the_administrator(conn)["password_hash"])

    assert stored.startswith(ARGON2ID_PREFIX)
    assert verify_password(stored, seed_password) is True
    assert verify_password(stored, a_password()) is False


def test_the_seeded_credential_expires_in_72_hours(
    conn: psycopg.Connection, seed_password: str
) -> None:
    up(conn)

    row = conn.execute(
        """
        SELECT temp_credential_expires_at - created_at
          FROM users
         WHERE role = %s
        """,
        ("admin",),
    ).fetchone()
    assert row is not None
    assert row[0].total_seconds() == pytest.approx(
        seed.TEMP_CREDENTIAL_LIFETIME_HOURS * 3600, abs=5
    )


def test_ids_are_uuids(conn: psycopg.Connection, seed_password: str) -> None:
    up(conn)

    row = conn.execute("SELECT id::text FROM users WHERE role = %s", ("admin",)).fetchone()
    assert row is not None
    # UUIDv4: the version nibble is 4.
    assert row[0][14] == "4"


# --- Idempotency -------------------------------------------------------------


def test_a_second_run_applies_nothing(conn: psycopg.Connection, seed_password: str) -> None:
    up(conn)

    assert up(conn) == []
    assert administrator_count(conn) == 1


def test_a_truncated_ledger_still_yields_one_administrator(
    conn: psycopg.Connection, seed_password: str
) -> None:
    # The second idempotency layer, independent of the ledger: an operator who
    # resets `schema_migrations` re-runs the seed body, and it inserts nothing.
    up(conn)
    conn.execute("TRUNCATE schema_migrations")

    assert up(conn) == ALL_VERSIONS
    assert administrator_count(conn) == 1


def test_a_truncated_ledger_does_not_rewrite_the_credential(
    conn: psycopg.Connection, seed_password: str
) -> None:
    up(conn)
    before = the_administrator(conn)
    conn.execute("TRUNCATE schema_migrations")
    up(conn)
    after = the_administrator(conn)

    assert after["id"] == before["id"]
    assert after["password_hash"] == before["password_hash"]


def test_a_second_run_never_adds_an_administrator_for_a_different_email(
    conn: psycopg.Connection, seed_password: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    up(conn)
    monkeypatch.setenv(SEED_ADMIN_EMAIL, "someone.else@rocell.lk")
    monkeypatch.setenv(SEED_ADMIN_PASSWORD, a_password())
    conn.execute("TRUNCATE schema_migrations")

    up(conn)

    assert administrator_count(conn) == 1
    assert the_administrator(conn)["email"] == SEED_EMAIL


# --- The seed environment ----------------------------------------------------


@pytest.mark.parametrize("missing", [SEED_ADMIN_PASSWORD, SEED_ADMIN_EMAIL])
def test_a_missing_seed_variable_fails_naming_it(
    conn: psycopg.Connection, seed_password: str, monkeypatch: pytest.MonkeyPatch, missing: str
) -> None:
    monkeypatch.delenv(missing)

    with pytest.raises(MigrationError, match=missing):
        up(conn)


def test_a_missing_seed_variable_leaves_nothing_partially_applied(
    conn: psycopg.Connection, seed_password: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(SEED_ADMIN_PASSWORD)

    with pytest.raises(MigrationError):
        up(conn)

    # The migration before it committed on its own; the failing one wrote
    # neither a row nor a ledger entry.
    assert ledger_versions(conn) == [CREATE_USERS_VERSION]
    assert administrator_count(conn) == 0


def test_a_missing_seed_variable_is_irrelevant_once_an_administrator_exists(
    conn: psycopg.Connection, seed_password: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The guard short-circuits before the environment is read at all, so an
    # already-seeded database migrates on a machine that has no seed
    # credentials anywhere near it.
    up(conn)
    conn.execute("TRUNCATE schema_migrations")
    for name in (SEED_ADMIN_EMAIL, SEED_ADMIN_PASSWORD, SEED_ADMIN_NAME):
        monkeypatch.delenv(name)

    assert up(conn) == ALL_VERSIONS
    assert administrator_count(conn) == 1


def test_a_weak_seed_password_fails_naming_the_rule(
    conn: psycopg.Connection, seed_password: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(SEED_ADMIN_PASSWORD, a_password(MIN_PASSWORD_LENGTH - 1))

    with pytest.raises(MigrationError, match=f"at least {MIN_PASSWORD_LENGTH} characters"):
        up(conn)

    assert ledger_versions(conn) == [CREATE_USERS_VERSION]
    assert administrator_count(conn) == 0


def test_an_over_long_seed_password_fails_naming_the_rule(
    conn: psycopg.Connection, seed_password: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The ceiling was enforced in `config.py` and tested nowhere. Deleting that
    # branch kept every test green, and on the *reseed* path — which is not
    # wrapped by `_apply` — the `ValueError` from `hash_password` is not one of
    # the four exceptions `main` handles, so it would reach the operator as a
    # traceback instead of a named refusal.
    monkeypatch.setenv(SEED_ADMIN_PASSWORD, a_password(MAX_PASSWORD_LENGTH + 1))

    with pytest.raises(MigrationError, match=f"at most {MAX_PASSWORD_LENGTH} characters"):
        up(conn)

    assert ledger_versions(conn) == [CREATE_USERS_VERSION]
    assert administrator_count(conn) == 0


def test_an_over_long_password_is_refused_on_the_reseed_path(
    conn: psycopg.Connection, seed_password: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    up(conn)
    stored = the_administrator(conn)["password_hash"]
    monkeypatch.setenv(SEED_ADMIN_PASSWORD, a_password(MAX_PASSWORD_LENGTH + 1))

    with pytest.raises(ConfigurationError, match=f"at most {MAX_PASSWORD_LENGTH} characters"):
        migrate.reseed_admin(conn)

    assert the_administrator(conn)["password_hash"] == stored


def test_a_malformed_seed_email_is_refused(
    conn: psycopg.Connection, seed_password: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(SEED_ADMIN_EMAIL, "not-an-address")

    with pytest.raises(MigrationError, match="email address"):
        up(conn)


def test_the_seed_name_is_optional(
    conn: psycopg.Connection, seed_password: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(SEED_ADMIN_NAME)

    up(conn)

    assert the_administrator(conn)["name"] == "Rocell Administrator"


def test_the_config_error_never_repeats_the_password(monkeypatch: pytest.MonkeyPatch) -> None:
    from rocell_infra.config import seed_admin_config

    password = a_password(MIN_PASSWORD_LENGTH - 1)
    monkeypatch.setenv(SEED_ADMIN_EMAIL, SEED_EMAIL)
    monkeypatch.setenv(SEED_ADMIN_PASSWORD, password)

    with pytest.raises(ConfigurationError) as raised:
        seed_admin_config()

    assert password not in str(raised.value)


# --- The table's own constraints ---------------------------------------------


def test_an_email_differing_only_by_case_is_rejected(
    conn: psycopg.Connection, seed_password: str
) -> None:
    up(conn)

    # An integrity error, surfaced rather than swallowed. It is the CHECK that
    # catches this one, because the canonical stored form is lowercase — which
    # is precisely what keeps a case-differing duplicate from existing.
    with pytest.raises(pg_errors.IntegrityError):
        conn.execute(
            "INSERT INTO users (name, email, password_hash, role) VALUES (%s, %s, %s, %s)",
            ("Ruwan Again", SEED_EMAIL.upper(), "$argon2id$placeholder", "staff"),
        )

    assert administrator_count(conn) == 1


def test_a_duplicate_email_is_rejected_by_the_unique_index(
    conn: psycopg.Connection, seed_password: str
) -> None:
    up(conn)

    with pytest.raises(pg_errors.UniqueViolation):
        conn.execute(
            "INSERT INTO users (name, email, password_hash, role) VALUES (%s, %s, %s, %s)",
            ("Ruwan Again", SEED_EMAIL, "$argon2id$placeholder", "staff"),
        )


def test_a_duplicate_session_token_is_rejected_by_the_unique_index(
    conn: psycopg.Connection, seed_password: str
) -> None:
    # The migration's own comment makes this uniqueness load-bearing: two rows
    # sharing a hash make "which session is this" unanswerable, and both
    # `lookup_session` and `delete_session` are written assuming at most one.
    # Downgrading the index to a plain one changes no test anywhere else.
    up(conn)
    administrator = conn.execute("SELECT id FROM users LIMIT 1").fetchone()
    assert administrator is not None
    insert = (
        "INSERT INTO sessions (user_id, token_hash, expires_at) "
        "VALUES (%s, %s, now() + interval '1 day')"
    )

    conn.execute(insert, (administrator[0], "a-token-digest"))

    with pytest.raises(pg_errors.UniqueViolation):
        conn.execute(insert, (administrator[0], "a-token-digest"))


def test_the_session_indexes_the_login_path_relies_on_exist(
    conn: psycopg.Connection, seed_password: str
) -> None:
    # Both of these are load-bearing on the one endpoint reachable without a
    # credential, and both were assertable only by eye. `expires_at` is scanned
    # by the sweep that runs on every sign-in; `user_id` backs the cascade that
    # ends a deleted user's sessions. Delete either from the migration and every
    # other test stays green, because a sequential scan returns the same rows.
    up(conn)

    indexes = {
        row[0]
        for row in conn.execute(
            "SELECT indexname FROM pg_indexes WHERE tablename = %s", ("sessions",)
        ).fetchall()
    }

    assert {"sessions_token_hash_key", "sessions_user_id_idx", "sessions_expires_at_idx"} <= indexes


def test_the_audit_index_story_1_13_will_page_on_exists(
    conn: psycopg.Connection, seed_password: str
) -> None:
    # `(created_at DESC, id DESC)` is the audit log's only index, and it is
    # there for a read surface that does not exist yet — so nothing in the
    # suite would notice it missing. Delete the `CREATE INDEX` and both
    # `DROP INDEX IF EXISTS` in the down and `DROP TABLE IF EXISTS` stay
    # silent, every audit test still passes, and Story 1.13's chronological
    # page quietly becomes a sequential scan over a table nothing may prune.
    up(conn)

    indexes = {
        row[0]
        for row in conn.execute(
            "SELECT indexname FROM pg_indexes WHERE tablename = %s", ("audit_log",)
        ).fetchall()
    }

    assert "audit_log_created_at_idx" in indexes


def test_the_catalogue_vector_index_is_hnsw_over_the_inner_product_operator(
    conn: psycopg.Connection, seed_password: str
) -> None:
    """AD-5's index, its access method and its operator class.

    Nothing else in the suite can see this. `find_candidates` is a grouped scan
    that returns identical rows with no index at all, and would return them
    silently mis-ranked under `vector_l2_ops` — the embeddings are unit-norm,
    so L2 and inner product agree on order today and would stop agreeing the
    day anything stores a vector that is not. Delete the `CREATE INDEX`, or
    swap its operator class, and every catalogue, searchable and audit test
    stays green.
    """
    up(conn)

    row = conn.execute(
        """
        SELECT am.amname AS method, opc.opcname AS operator_class
          FROM pg_class i
          JOIN pg_index ix ON ix.indexrelid = i.oid
          JOIN pg_am am ON am.oid = i.relam
          JOIN pg_opclass opc ON opc.oid = ix.indclass[0]
         WHERE i.relname = %s
        """,
        ("reference_embedding_hnsw_idx",),
    ).fetchone()

    assert row is not None, "the HNSW index AD-5 requires is not there"
    assert row[0] == "hnsw"
    assert row[1] == "vector_ip_ops"


def _holds(conn: psycopg.Connection, table: str, privilege: str) -> bool:
    """Whether `rocell_app` holds `privilege` on `table` in this database."""
    row = conn.execute(
        "SELECT has_table_privilege('rocell_app', %s, %s) AS held", (table, privilege)
    ).fetchone()
    assert row is not None
    return bool(row[0])


def _is_a_member(conn: psycopg.Connection) -> bool:
    """Whether the migrating role is a member of `rocell_app`, per the catalog."""
    row = conn.execute(
        """
        SELECT EXISTS (
                 SELECT 1
                   FROM pg_auth_members AS membership
                   JOIN pg_roles AS granted ON granted.oid = membership.roleid
                   JOIN pg_roles AS grantee ON grantee.oid = membership.member
                  WHERE granted.rolname = 'rocell_app'
                    AND grantee.rolname = current_user
               ) AS is_member
        """
    ).fetchone()
    assert row is not None
    return bool(row[0])


def test_the_audit_down_takes_back_the_grants_and_the_membership(
    conn: psycopg.Connection, seed_password: str
) -> None:
    # **Two thirds of the down migration is observed by nothing else.** Its
    # `DROP INDEX`/`DROP TABLE` are covered by the column-set assertions the
    # other down tests make; its `REVOKE` block is not, because no test in
    # either suite looks at a privilege *after* a revert —
    # `test_audit_immutability.py`'s whole matrix runs against a database that
    # has just been migrated up. Delete the entire `DO $$ ... REVOKE ... $$`
    # block and every existing test stays green while a reverted database is
    # left with `rocell_app` holding full DML on `users`, `sessions` and
    # `login_attempts` and the owner still a member of a cluster-scoped role —
    # which is the opposite of what this file's header and `infra/README.md`
    # tell an operator the revert restores.
    up(conn)

    assert _holds(conn, "users", "SELECT")
    assert _holds(conn, "sessions", "DELETE")
    assert _holds(conn, "login_attempts", "UPDATE")
    assert _is_a_member(conn)

    assert down(conn) == AUDIT_LOG_FLAGGED_INDEX_VERSION
    assert down(conn) == ANOMALY_BASELINE_VERSION
    assert down(conn) == SCAN_RATE_LIMIT_VERSION
    assert down(conn) == SCAN_VERSION
    assert down(conn) == CATALOGUE_VERSION
    assert down(conn) == AUDIT_LOG_VERSION

    for table in ("users", "sessions", "login_attempts"):
        for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
            assert not _holds(conn, table, privilege), (
                f"after the revert rocell_app still holds {privilege} on {table}"
            )
    assert not _is_a_member(conn), (
        "after the revert the migrating role is still a member of rocell_app"
    )

    # And the pair round-trips: re-applying restores both, so a revert is not
    # a one-way door for the deployment that has to go forward again.
    assert up(conn) == [
        AUDIT_LOG_VERSION,
        CATALOGUE_VERSION,
        SCAN_VERSION,
        SCAN_RATE_LIMIT_VERSION,
        ANOMALY_BASELINE_VERSION,
        AUDIT_LOG_FLAGGED_INDEX_VERSION,
    ]
    assert _holds(conn, "users", "SELECT")
    assert _is_a_member(conn)


def test_the_table_refuses_an_address_that_is_not_lowercased(
    conn: psycopg.Connection, seed_password: str
) -> None:
    # Without this, every lookup from Story 1.3 on has to remember
    # `lower(email) = lower(...)`, and nothing catches the first one that does
    # not — it just silently fails to find the account.
    up(conn)

    with pytest.raises(pg_errors.CheckViolation):
        conn.execute(
            "INSERT INTO users (name, email, password_hash, role) VALUES (%s, %s, %s, %s)",
            ("Mixed Case", "Someone@Rocell.LK", "$argon2id$placeholder", "staff"),
        )


def test_the_seeded_address_is_stored_lowercased(
    conn: psycopg.Connection, seed_password: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(SEED_ADMIN_EMAIL, "RUWAN@Rocell.LK")

    up(conn)

    assert the_administrator(conn)["email"] == "ruwan@rocell.lk"


def test_an_unknown_role_is_rejected(conn: psycopg.Connection, seed_password: str) -> None:
    up(conn)

    with pytest.raises(pg_errors.CheckViolation):
        conn.execute(
            "INSERT INTO users (name, email, password_hash, role) VALUES (%s, %s, %s, %s)",
            ("A Manager", "manager@rocell.lk", "$argon2id$placeholder", "manager"),
        )


@pytest.mark.parametrize("role", ["staff", "admin"])
def test_both_roles_are_accepted(conn: psycopg.Connection, seed_password: str, role: str) -> None:
    up(conn)

    conn.execute(
        "INSERT INTO users (name, email, password_hash, role) VALUES (%s, %s, %s, %s)",
        ("Someone", f"{role}.someone@rocell.lk", "$argon2id$placeholder", role),
    )

    row = conn.execute(
        "SELECT active, must_change_password FROM users WHERE email = %s",
        (f"{role}.someone@rocell.lk",),
    ).fetchone()
    assert row is not None
    # The defaults the ERD names: active, and gated by a password change.
    assert row == (True, True)


def test_the_activity_migration_upgrades_a_database_that_already_holds_sessions(
    conn: psycopg.Connection, seed_password: str
) -> None:
    """The one path `20260917T1400_track_session_activity` exists for.

    Every other test in this file applies the whole plan to an empty database
    in one go, so the `ALTER TABLE` only ever meets a `sessions` table with no
    rows — which is not the table any deployed system has. Two plausible
    versions of that migration pass the entire suite and fail in production:

    * without `DEFAULT now()`, `ADD COLUMN ... NOT NULL` raises
      `NotNullViolation` against any existing row and `make migrate` stops
      halfway through a deploy;
    * with a `last_seen_at = issued_at` backfill, every session issued more
      than 12 hours before the deploy is idle-dead the moment the code lands,
      and every user holding one is signed out by the upgrade itself.

    So the plan is applied in two halves with a real session row written in
    between, and both properties are asserted on that pre-existing row.
    """
    plan = discover_migrations()
    cut = [m.version for m in plan].index(CREATE_SESSIONS_VERSION) + 1

    # Everything up to and including the `sessions` table — the shape a
    # database deployed before this story is in.
    assert up(conn, plan[:cut]) == [m.version for m in plan[:cut]]

    # A live session on that older shape. `issued_at` is pushed well past the
    # idle window so a backfill from it would be visibly wrong.
    conn.execute(
        "INSERT INTO users (name, email, password_hash, role) VALUES (%s, %s, %s, %s)",
        ("Nimal Silva", "nimal@rocell.lk", "$argon2id$placeholder", "staff"),
    )
    conn.execute(
        """
        INSERT INTO sessions (user_id, token_hash, issued_at, expires_at)
        VALUES ((SELECT id FROM users WHERE email = %s), %s, now() - %s, now() + %s)
        """,
        ("nimal@rocell.lk", "a" * 64, timedelta(days=3), timedelta(days=4)),
    )

    # The upgrade itself, against a populated table, and only it — the plan is
    # cut again so a migration added after this one does not silently ride
    # along and make the assertion below about somebody else's DDL.
    activity = plan[: [m.version for m in plan].index(TRACK_ACTIVITY_VERSION) + 1]
    assert up(conn, activity) == [TRACK_ACTIVITY_VERSION]

    row = conn.execute(
        "SELECT last_seen_at, issued_at, now() - last_seen_at AS idle_for FROM sessions"
    ).fetchone()
    assert row is not None
    last_seen_at, issued_at, idle_for = row

    # Non-null, or the NOT NULL constraint is a lie the table is not holding.
    assert last_seen_at is not None
    # And *not* backfilled from `issued_at`: this session was issued three days
    # ago, so a backfill would hand it an idle age of three days and the very
    # next request would sign its holder out. The upgrade starts the idle
    # window at the migration, which is the safe direction — a known instant,
    # not an invented history.
    assert last_seen_at > issued_at
    # 12 hours is `api.sessions.SESSION_IDLE_TIMEOUT`, spelled out because
    # `infra` does not import `apps/api`. Shorten that constant and this bound
    # has to come with it, or the assertion keeps passing while no longer
    # testing that a migrated session survives its first request.
    assert idle_for < timedelta(hours=12)


def test_the_throttling_migration_upgrades_a_database_that_already_holds_users(
    conn: psycopg.Connection, seed_password: str
) -> None:
    """The one path `20260918T1000_add_login_throttling`'s `ALTER TABLE` exists for.

    Every other test in this file applies the whole plan to an empty database in
    one go, so the `ADD COLUMN` only ever meets a `users` table with no rows —
    which is not the table any deployed system has. The failure this guards is
    the same one the activity migration guards, with a different cause: added
    `NOT NULL` with no default, or with a backfill, the column either refuses
    every existing row or declares live accounts locked. A nullable column with
    no default is the only shape that means "this account has never been
    locked" for a row that predates the feature.

    So the plan is applied in two halves with real users written in between —
    the seeded Administrator among them — and both properties are asserted on
    those pre-existing rows.
    """
    plan = discover_migrations()
    cut = [m.version for m in plan].index(TRACK_ACTIVITY_VERSION) + 1

    # Everything up to and including the session-activity column: the shape a
    # database deployed before this story is in.
    assert up(conn, plan[:cut]) == [m.version for m in plan[:cut]]

    conn.execute(
        "INSERT INTO users (name, email, password_hash, role) VALUES (%s, %s, %s, %s)",
        ("Nimal Silva", "nimal@rocell.lk", "$argon2id$placeholder", "staff"),
    )

    # The upgrade itself, against a populated table. This is the assertion that
    # fails outright — not merely reports a different value — if the column is
    # added `NOT NULL` with no default.
    #
    # Cut at this migration rather than run to the end of the plan, for the same
    # reason the activity test above is: a later story's migration would
    # otherwise ride along in the return value and fail this test for a reason
    # that has nothing to do with the `ADD COLUMN` it exists to prove.
    through = [m.version for m in plan].index(LOGIN_THROTTLING_VERSION) + 1
    assert up(conn, plan[:through]) == [LOGIN_THROTTLING_VERSION]

    rows = conn.execute("SELECT email, locked_until FROM users ORDER BY email").fetchall()
    # Both the seeded Administrator and the account written above, and neither
    # of them locked by the migration that introduced the column.
    assert len(rows) == 2
    assert all(row[1] is None for row in rows), rows

    # The counter table arrives empty, with its own constraints in force.
    empty = conn.execute("SELECT count(*) FROM login_attempts").fetchone()
    assert empty is not None
    assert empty[0] == 0
    assert table_columns(conn, "login_attempts") == {
        "email_key",
        "failure_count",
        "locked_until",
        "last_failure_at",
    }


def test_a_negative_failure_count_is_refused_by_the_database(
    conn: psycopg.Connection, seed_password: str
) -> None:
    # The CHECK is the database's own copy of a rule the one statement that
    # writes this table already keeps. It is here for the next statement
    # somebody adds, which is exactly the statement no test will have been
    # written for.
    up(conn)

    with pytest.raises(pg_errors.CheckViolation):
        conn.execute(
            "INSERT INTO login_attempts (email_key, failure_count) VALUES (%s, %s)",
            ("someone@rocell.lk", -1),
        )


def test_the_throttling_pair_round_trips(conn: psycopg.Connection, seed_password: str) -> None:
    # Up, down, up. A `down` that drops the table but forgets the column leaves
    # the second `up` running `ADD COLUMN IF NOT EXISTS` against a column that
    # is still there — green, and a revert that did not revert. Asserted on the
    # way back up rather than only on the way down, because that is the
    # direction a deployment actually takes after a rollback.
    up(conn)
    assert "locked_until" in table_columns(conn, "users")

    # The flagged-index step sits on top of the anomaly baseline table, which
    # sits on top of the scan rate limit table, which sits on top of the scan
    # table, which sits on top of the catalogue pair, which sits on top of the
    # audit pair, which sits on top of the throttling pair, so six steps come
    # off before this one. Asserted rather than skipped past: a `down` that
    # reverted more than its own file would show up right here.
    assert down(conn) == AUDIT_LOG_FLAGGED_INDEX_VERSION
    assert down(conn) == ANOMALY_BASELINE_VERSION
    assert down(conn) == SCAN_RATE_LIMIT_VERSION
    assert down(conn) == SCAN_VERSION
    assert down(conn) == CATALOGUE_VERSION
    assert down(conn) == AUDIT_LOG_VERSION
    assert table_columns(conn, "login_attempts") != set()

    assert down(conn) == LOGIN_THROTTLING_VERSION
    assert table_columns(conn, "login_attempts") == set()
    assert "locked_until" not in table_columns(conn, "users")
    assert ledger_versions(conn) == ALL_VERSIONS[:-7]

    assert up(conn) == [
        LOGIN_THROTTLING_VERSION,
        AUDIT_LOG_VERSION,
        CATALOGUE_VERSION,
        SCAN_VERSION,
        SCAN_RATE_LIMIT_VERSION,
        ANOMALY_BASELINE_VERSION,
        AUDIT_LOG_FLAGGED_INDEX_VERSION,
    ]
    assert "locked_until" in table_columns(conn, "users")
    assert table_columns(conn, "login_attempts") != set()
    assert ledger_versions(conn) == ALL_VERSIONS


def test_the_scan_rate_limit_pair_round_trips(conn: psycopg.Connection, seed_password: str) -> None:
    """Story 3.6's migration: up, down, up. A brand-new table, so there is no
    existing-row upgrade case to prove — `login_attempts` and `scan` already
    cover that shape for an `ALTER TABLE` and for a fresh `CREATE TABLE`
    respectively, and this table is the latter with nothing preceding it to
    upgrade.
    """
    up(conn)
    assert table_columns(conn, "scan_rate_limit") == {
        "user_id",
        "submission_count",
        "window_started_at",
    }
    assert _holds(conn, "scan_rate_limit", "SELECT")
    assert _holds(conn, "scan_rate_limit", "INSERT")
    assert _holds(conn, "scan_rate_limit", "UPDATE")
    assert _holds(conn, "scan_rate_limit", "DELETE")

    # Two Story 3.7 migrations now sit on top of this one and must come off
    # first — the flagged index and the anomaly baseline table.
    assert down(conn) == AUDIT_LOG_FLAGGED_INDEX_VERSION
    assert down(conn) == ANOMALY_BASELINE_VERSION
    assert down(conn) == SCAN_RATE_LIMIT_VERSION
    assert table_columns(conn, "scan_rate_limit") == set()
    # `scan` itself survives this one step — proof the revert is this file's
    # own table and not "everything on top".
    assert table_columns(conn, "scan") != set()

    assert up(conn) == [
        SCAN_RATE_LIMIT_VERSION,
        ANOMALY_BASELINE_VERSION,
        AUDIT_LOG_FLAGGED_INDEX_VERSION,
    ]
    assert table_columns(conn, "scan_rate_limit") == {
        "user_id",
        "submission_count",
        "window_started_at",
    }
    assert _holds(conn, "scan_rate_limit", "SELECT")


def test_the_anomaly_baseline_pair_round_trips(
    conn: psycopg.Connection, seed_password: str
) -> None:
    """Story 3.7's migration: up, down, up. A brand-new table, so there is no
    existing-row upgrade case to prove — the same reasoning
    `test_the_scan_rate_limit_pair_round_trips` gives for its own table.
    """
    up(conn)
    assert table_columns(conn, "anomaly_baseline") == {
        "user_id",
        "signal",
        "window_started_at",
        "window_count",
        "baseline_average",
    }
    assert _holds(conn, "anomaly_baseline", "SELECT")
    assert _holds(conn, "anomaly_baseline", "INSERT")
    assert _holds(conn, "anomaly_baseline", "UPDATE")
    assert _holds(conn, "anomaly_baseline", "DELETE")

    # The flagged index sits on top of this table's migration (by timestamp,
    # not by a real dependency — it names `audit_log`, not `anomaly_baseline`)
    # and must come off first.
    assert down(conn) == AUDIT_LOG_FLAGGED_INDEX_VERSION
    assert down(conn) == ANOMALY_BASELINE_VERSION
    assert table_columns(conn, "anomaly_baseline") == set()
    # `scan_rate_limit` itself survives this one step.
    assert table_columns(conn, "scan_rate_limit") != set()

    assert up(conn) == [ANOMALY_BASELINE_VERSION, AUDIT_LOG_FLAGGED_INDEX_VERSION]
    assert table_columns(conn, "anomaly_baseline") == {
        "user_id",
        "signal",
        "window_started_at",
        "window_count",
        "baseline_average",
    }
    assert _holds(conn, "anomaly_baseline", "SELECT")


def test_a_negative_window_count_is_refused_by_the_database(
    conn: psycopg.Connection, seed_password: str
) -> None:
    up(conn)
    account = conn.execute("SELECT id FROM users LIMIT 1").fetchone()
    assert account is not None

    with pytest.raises(pg_errors.CheckViolation):
        conn.execute(
            "INSERT INTO anomaly_baseline (user_id, signal, window_count) VALUES (%s, %s, %s)",
            (account[0], "login", -1),
        )


def test_an_unrecognised_signal_is_refused_by_the_database(
    conn: psycopg.Connection, seed_password: str
) -> None:
    up(conn)
    account = conn.execute("SELECT id FROM users LIMIT 1").fetchone()
    assert account is not None

    with pytest.raises(pg_errors.CheckViolation):
        conn.execute(
            "INSERT INTO anomaly_baseline (user_id, signal) VALUES (%s, %s)",
            (account[0], "not-a-real-signal"),
        )


def test_a_deleted_user_takes_their_anomaly_baseline_rows_with_them(
    conn: psycopg.Connection, seed_password: str
) -> None:
    # `user_id` is a real foreign key, `ON DELETE CASCADE` — `scan_rate_limit.
    # user_id`'s own precedent.
    up(conn)
    conn.execute(
        "INSERT INTO users (name, email, password_hash, role) VALUES (%s, %s, %s, %s)",
        ("Kamal Fernando", "kamal@rocell.lk", "$argon2id$placeholder", "staff"),
    )
    user_id = conn.execute("SELECT id FROM users WHERE email = %s", ("kamal@rocell.lk",)).fetchone()
    assert user_id is not None
    conn.execute(
        "INSERT INTO anomaly_baseline (user_id, signal) VALUES (%s, %s)", (user_id[0], "login")
    )
    conn.execute(
        "INSERT INTO anomaly_baseline (user_id, signal) VALUES (%s, %s)", (user_id[0], "scan")
    )

    conn.execute("DELETE FROM users WHERE id = %s", (user_id[0],))

    remaining = conn.execute(
        "SELECT count(*) FROM anomaly_baseline WHERE user_id = %s", (user_id[0],)
    ).fetchone()
    assert remaining is not None
    assert remaining[0] == 0


def test_the_flagged_index_pair_round_trips(conn: psycopg.Connection, seed_password: str) -> None:
    """Story 3.7's second migration: a partial index over an existing table
    (`audit_log`), read-side only. `down`/`up` here touch no row and no grant
    — only the index's existence.
    """
    up(conn)

    def _has_index() -> bool:
        row = conn.execute(
            "SELECT 1 FROM pg_indexes WHERE indexname = %s", ("audit_log_flagged_idx",)
        ).fetchone()
        return row is not None

    assert _has_index()

    assert down(conn) == AUDIT_LOG_FLAGGED_INDEX_VERSION
    assert not _has_index()
    # `audit_log` itself survives this one step.
    assert table_columns(conn, "audit_log") != set()

    assert up(conn) == [AUDIT_LOG_FLAGGED_INDEX_VERSION]
    assert _has_index()


def test_a_negative_submission_count_is_refused_by_the_database(
    conn: psycopg.Connection, seed_password: str
) -> None:
    # The CHECK is the database's own copy of a rule the one statement that
    # writes this table already keeps — `login_attempts`'s own precedent, for
    # the next statement somebody adds against this one.
    up(conn)
    account = conn.execute("SELECT id FROM users LIMIT 1").fetchone()
    assert account is not None

    with pytest.raises(pg_errors.CheckViolation):
        conn.execute(
            "INSERT INTO scan_rate_limit (user_id, submission_count) VALUES (%s, %s)",
            (account[0], -1),
        )


def test_a_deleted_user_takes_their_scan_rate_limit_row_with_them(
    conn: psycopg.Connection, seed_password: str
) -> None:
    # `user_id` is a real foreign key, `ON DELETE CASCADE` — `scan.user_id`'s
    # own precedent, and the opposite of `login_attempts.email_key`, which is
    # deliberately not one.
    up(conn)
    conn.execute(
        "INSERT INTO users (name, email, password_hash, role) VALUES (%s, %s, %s, %s)",
        ("Nimal Silva", "nimal@rocell.lk", "$argon2id$placeholder", "staff"),
    )
    user_id = conn.execute("SELECT id FROM users WHERE email = %s", ("nimal@rocell.lk",)).fetchone()
    assert user_id is not None
    conn.execute("INSERT INTO scan_rate_limit (user_id) VALUES (%s)", (user_id[0],))

    conn.execute("DELETE FROM users WHERE id = %s", (user_id[0],))

    remaining = conn.execute(
        "SELECT count(*) FROM scan_rate_limit WHERE user_id = %s", (user_id[0],)
    ).fetchone()
    assert remaining is not None
    assert remaining[0] == 0


# --- down --------------------------------------------------------------------


def test_down_reverts_one_step(conn: psycopg.Connection, seed_password: str) -> None:
    up(conn)

    # One step is one migration: the most recently applied, and nothing behind
    # it. The flagged index goes first, the anomaly baseline table next, then
    # the scan rate limit table, the scan table, the catalogue pair and the
    # audit pair, and the throttling objects below them are untouched by any
    # of the six steps — proof each step really is one file and not
    # "everything on top".
    assert down(conn) == AUDIT_LOG_FLAGGED_INDEX_VERSION
    assert table_columns(conn, "scan_rate_limit") != set()

    assert down(conn) == ANOMALY_BASELINE_VERSION
    assert table_columns(conn, "anomaly_baseline") == set()
    assert table_columns(conn, "scan_rate_limit") != set()

    assert down(conn) == SCAN_RATE_LIMIT_VERSION
    assert table_columns(conn, "scan_rate_limit") == set()
    assert table_columns(conn, "scan") != set()

    assert down(conn) == SCAN_VERSION
    assert table_columns(conn, "scan") == set()
    assert table_columns(conn, "tile") != set()

    assert down(conn) == CATALOGUE_VERSION
    assert table_columns(conn, "tile") == set()
    assert table_columns(conn, "audit_log") != set()

    assert down(conn) == AUDIT_LOG_VERSION
    assert table_columns(conn, "audit_log") == set()
    assert table_columns(conn, "login_attempts") != set()

    assert down(conn) == LOGIN_THROTTLING_VERSION
    assert table_columns(conn, "login_attempts") == set()
    assert "locked_until" not in table_columns(conn, "users")
    assert "last_seen_at" in table_columns(conn, "sessions")

    # Then the activity column, and `sessions` itself survives that step.
    assert down(conn) == TRACK_ACTIVITY_VERSION
    assert ledger_versions(conn) == [CREATE_USERS_VERSION, SEED_VERSION, CREATE_SESSIONS_VERSION]
    assert "last_seen_at" not in table_columns(conn, "sessions")
    assert "expires_at" in table_columns(conn, "sessions")

    # Then `sessions` goes, and the seeded Administrator is still there.
    assert down(conn) == CREATE_SESSIONS_VERSION
    assert ledger_versions(conn) == [CREATE_USERS_VERSION, SEED_VERSION]
    assert administrator_count(conn) == 1
    assert table_columns(conn, "sessions") == set()

    assert down(conn) == SEED_VERSION
    assert ledger_versions(conn) == [CREATE_USERS_VERSION]
    assert administrator_count(conn) == 0
    assert table_columns(conn, "users") != set()


def test_stepping_all_the_way_down_restores_the_previous_shape(
    conn: psycopg.Connection, seed_password: str
) -> None:
    up(conn)
    for _ in range(len(ALL_VERSIONS) - 1):
        down(conn)

    assert down(conn) == CREATE_USERS_VERSION
    assert ledger_versions(conn) == []
    assert table_columns(conn, "users") == set()
    assert table_columns(conn, "sessions") == set()
    assert table_columns(conn, "login_attempts") == set()
    assert table_columns(conn, "audit_log") == set()
    assert table_columns(conn, "tile") == set()
    assert table_columns(conn, "reference_embedding") == set()
    assert table_columns(conn, "scan_rate_limit") == set()
    assert table_columns(conn, "anomaly_baseline") == set()


def test_down_refuses_a_ledger_version_whose_files_are_gone(
    conn: psycopg.Connection, tmp_path: Path
) -> None:
    # A version recorded as applied whose `.sql` files were deleted or renamed.
    # Without the guard, `down` reaches for `.down_path` on nothing and the
    # operator gets an AttributeError traceback instead of the guided message —
    # and no test noticed, because none of the `down` cases staged this state.
    write_plain_pair(tmp_path, "20260101T0900_create_widgets", "widgets")
    plan = discover_migrations(tmp_path)
    assert up(conn, plan) == ["20260101T0900_create_widgets"]

    for path in tmp_path.glob("20260101T0900_create_widgets.*"):
        path.unlink()

    with pytest.raises(MigrationError, match="recorded as applied but has no files"):
        down(conn, discover_migrations(tmp_path))

    assert ledger_versions(conn) == ["20260101T0900_create_widgets"]


def test_down_on_an_unmigrated_database_reverts_nothing(conn: psycopg.Connection) -> None:
    assert down(conn) is None


def test_up_after_down_reseeds(conn: psycopg.Connection, seed_password: str) -> None:
    up(conn)
    for _ in ALL_VERSIONS:
        down(conn)

    assert up(conn) == ALL_VERSIONS
    assert administrator_count(conn) == 1


def test_down_leaves_a_claimed_administrator_alone(
    conn: psycopg.Connection, seed_password: str
) -> None:
    # A `down` must restore the previous shape, not take a live system's last
    # way in with it.
    up(conn)
    conn.execute(
        "UPDATE users SET must_change_password = false, last_login_at = now() WHERE role = %s",
        ("admin",),
    )

    assert down(conn) == AUDIT_LOG_FLAGGED_INDEX_VERSION
    assert down(conn) == ANOMALY_BASELINE_VERSION
    assert down(conn) == SCAN_RATE_LIMIT_VERSION
    assert down(conn) == SCAN_VERSION
    assert down(conn) == CATALOGUE_VERSION
    assert down(conn) == AUDIT_LOG_VERSION
    assert down(conn) == LOGIN_THROTTLING_VERSION
    assert down(conn) == TRACK_ACTIVITY_VERSION
    assert down(conn) == CREATE_SESSIONS_VERSION
    assert down(conn) == SEED_VERSION
    assert administrator_count(conn) == 1


def test_down_leaves_an_administrator_who_has_signed_in_alone(
    conn: psycopg.Connection, seed_password: str
) -> None:
    # `must_change_password` is set and `last_login_at` is not null: the state
    # an admin-issued credential reset produces on an account that has been
    # used. The claimed-account test above sets *both* flags in one UPDATE, so
    # it passes with either predicate deleted — and with `last_login_at IS
    # NULL` gone, `down --yes` would take a live system's last way in.
    up(conn)
    conn.execute("UPDATE users SET last_login_at = now() WHERE role = %s", ("admin",))

    assert down(conn) == AUDIT_LOG_FLAGGED_INDEX_VERSION
    assert down(conn) == ANOMALY_BASELINE_VERSION
    assert down(conn) == SCAN_RATE_LIMIT_VERSION
    assert down(conn) == SCAN_VERSION
    assert down(conn) == CATALOGUE_VERSION
    assert down(conn) == AUDIT_LOG_VERSION
    assert down(conn) == LOGIN_THROTTLING_VERSION
    assert down(conn) == TRACK_ACTIVITY_VERSION
    assert down(conn) == CREATE_SESSIONS_VERSION
    assert down(conn) == SEED_VERSION
    assert administrator_count(conn) == 1


def test_down_leaves_an_administrator_who_set_their_own_password_alone(
    conn: psycopg.Connection, seed_password: str
) -> None:
    # The mirror image: the password has been set but no sign-in is recorded.
    up(conn)
    conn.execute(
        "UPDATE users SET must_change_password = false WHERE role = %s",
        ("admin",),
    )

    assert down(conn) == AUDIT_LOG_FLAGGED_INDEX_VERSION
    assert down(conn) == ANOMALY_BASELINE_VERSION
    assert down(conn) == SCAN_RATE_LIMIT_VERSION
    assert down(conn) == SCAN_VERSION
    assert down(conn) == CATALOGUE_VERSION
    assert down(conn) == AUDIT_LOG_VERSION
    assert down(conn) == LOGIN_THROTTLING_VERSION
    assert down(conn) == TRACK_ACTIVITY_VERSION
    assert down(conn) == CREATE_SESSIONS_VERSION
    assert down(conn) == SEED_VERSION
    assert administrator_count(conn) == 1


def test_down_leaves_staff_accounts_alone(conn: psycopg.Connection, seed_password: str) -> None:
    # No `down` case had a non-admin row in the table, so deleting `role =
    # 'admin'` from the down SQL passed the whole suite while taking every
    # unclaimed Staff account with the seeded Administrator.
    up(conn)
    conn.execute(
        "INSERT INTO users (name, email, password_hash, role) VALUES (%s, %s, %s, %s)",
        ("Nimal Silva", "nimal@rocell.lk", "$argon2id$placeholder", "staff"),
    )

    assert down(conn) == AUDIT_LOG_FLAGGED_INDEX_VERSION
    assert down(conn) == ANOMALY_BASELINE_VERSION
    assert down(conn) == SCAN_RATE_LIMIT_VERSION
    assert down(conn) == SCAN_VERSION
    assert down(conn) == CATALOGUE_VERSION
    assert down(conn) == AUDIT_LOG_VERSION
    assert down(conn) == LOGIN_THROTTLING_VERSION
    assert down(conn) == TRACK_ACTIVITY_VERSION
    assert down(conn) == CREATE_SESSIONS_VERSION
    assert down(conn) == SEED_VERSION

    remaining = conn.execute("SELECT role FROM users").fetchall()
    assert [row[0] for row in remaining] == ["staff"]


def test_down_leaves_a_second_administrator_alone(
    conn: psycopg.Connection, seed_password: str
) -> None:
    up(conn)
    conn.execute(
        "INSERT INTO users (name, email, password_hash, role) VALUES (%s, %s, %s, %s)",
        ("Second Admin", "second@rocell.lk", "$argon2id$placeholder", "admin"),
    )

    assert down(conn) == AUDIT_LOG_FLAGGED_INDEX_VERSION
    assert down(conn) == ANOMALY_BASELINE_VERSION
    assert down(conn) == SCAN_RATE_LIMIT_VERSION
    assert down(conn) == SCAN_VERSION
    assert down(conn) == CATALOGUE_VERSION
    assert down(conn) == AUDIT_LOG_VERSION
    assert down(conn) == LOGIN_THROTTLING_VERSION
    assert down(conn) == TRACK_ACTIVITY_VERSION
    assert down(conn) == CREATE_SESSIONS_VERSION
    assert down(conn) == SEED_VERSION
    assert administrator_count(conn) == 2


# --- status ------------------------------------------------------------------


def test_status_reports_pending_then_applied(conn: psycopg.Connection, seed_password: str) -> None:
    assert status(conn) == [(version, False) for version in ALL_VERSIONS]

    up(conn)

    assert status(conn) == [(version, True) for version in ALL_VERSIONS]


# --- A migration that fails --------------------------------------------------


def test_a_failing_migration_writes_no_ledger_row(conn: psycopg.Connection, tmp_path: Path) -> None:
    (tmp_path / "20260101T0900_create_thing.up.sql").write_text(
        "CREATE TABLE thing (id int);\nSELECT 1 / 0;\n", encoding="utf-8"
    )
    (tmp_path / "20260101T0900_create_thing.down.sql").write_text(
        "DROP TABLE IF EXISTS thing;\n", encoding="utf-8"
    )
    plan = discover_migrations(tmp_path)

    with pytest.raises(MigrationError, match="20260101T0900_create_thing.up.sql failed"):
        up(conn, plan)

    # The whole file rolled back — the table the first statement created is
    # gone too — and nothing was recorded as applied.
    assert ledger_versions(conn) == []
    assert table_columns(conn, "thing") == set()


def test_a_failing_migration_preserves_the_database_error_text(
    conn: psycopg.Connection, tmp_path: Path
) -> None:
    (tmp_path / "20260101T0900_break_things.up.sql").write_text("SELECT 1 / 0;\n", encoding="utf-8")
    (tmp_path / "20260101T0900_break_things.down.sql").write_text("SELECT 1;\n", encoding="utf-8")

    with pytest.raises(MigrationError, match="division by zero"):
        up(conn, discover_migrations(tmp_path))


def test_an_unknown_python_step_is_refused(conn: psycopg.Connection, tmp_path: Path) -> None:
    (tmp_path / "20260101T0900_do_magic.up.sql").write_text(
        "-- rocell:python conjure_something\n", encoding="utf-8"
    )
    (tmp_path / "20260101T0900_do_magic.down.sql").write_text("SELECT 1;\n", encoding="utf-8")

    with pytest.raises(MigrationError, match="conjure_something"):
        up(conn, discover_migrations(tmp_path))

    assert ledger_versions(conn) == []


# --- reseed-admin ------------------------------------------------------------


def test_reseed_reissues_the_credential_while_unclaimed(
    conn: psycopg.Connection, seed_password: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    up(conn)
    before = the_administrator(conn)

    replacement = a_password()
    monkeypatch.setenv(SEED_ADMIN_PASSWORD, replacement)
    migrate.reseed_admin(conn)

    after = the_administrator(conn)
    assert after["id"] == before["id"]
    assert verify_password(str(after["password_hash"]), replacement) is True
    assert verify_password(str(after["password_hash"]), seed_password) is False
    assert after["must_change_password"] is True
    assert administrator_count(conn) == 1


def test_reseed_restarts_the_seventy_two_hour_clock(
    conn: psycopg.Connection, seed_password: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The command exists *because* the credential expires: if nobody claims the
    # account inside 72 hours there is no Administrator left to reissue it. No
    # test read `temp_credential_expires_at` after a reseed, so deleting that
    # line from `_REISSUE_CREDENTIAL` kept the suite green while handing the
    # operator a working password against an already-dead deadline.
    up(conn)
    conn.execute(
        """
        UPDATE users
           SET temp_credential_expires_at = now() - interval '1 hour',
               updated_at = now() - interval '4 days'
         WHERE role = %s
        """,
        ("admin",),
    )
    before = the_administrator(conn)

    monkeypatch.setenv(SEED_ADMIN_PASSWORD, a_password())
    migrate.reseed_admin(conn)

    after = the_administrator(conn)
    assert after["temp_credential_expires_at"] > before["temp_credential_expires_at"]
    assert after["updated_at"] > before["updated_at"]

    row = conn.execute(
        "SELECT temp_credential_expires_at - now() FROM users WHERE role = %s",
        ("admin",),
    ).fetchone()
    assert row is not None
    assert (
        timedelta(hours=71, minutes=59)
        < row[0]
        <= timedelta(hours=seed.TEMP_CREDENTIAL_LIFETIME_HOURS)
    )


def test_reseed_refuses_once_the_account_is_claimed(
    conn: psycopg.Connection, seed_password: str
) -> None:
    up(conn)
    conn.execute(
        "UPDATE users SET must_change_password = false WHERE role = %s",
        ("admin",),
    )

    with pytest.raises(seed.SeedRefused, match="already been claimed"):
        migrate.reseed_admin(conn)


def test_reseed_refuses_once_the_account_has_signed_in(
    conn: psycopg.Connection, seed_password: str
) -> None:
    up(conn)
    conn.execute("UPDATE users SET last_login_at = now() WHERE role = %s", ("admin",))

    with pytest.raises(seed.SeedRefused, match="already been claimed"):
        migrate.reseed_admin(conn)


def test_reseed_refuses_once_a_second_administrator_exists(
    conn: psycopg.Connection, seed_password: str
) -> None:
    up(conn)
    conn.execute(
        "INSERT INTO users (name, email, password_hash, role) VALUES (%s, %s, %s, %s)",
        ("Second Admin", "second@rocell.lk", "$argon2id$placeholder", "admin"),
    )

    with pytest.raises(seed.SeedRefused, match="2 Administrators"):
        migrate.reseed_admin(conn)


def test_reseed_refuses_when_there_is_no_administrator(
    conn: psycopg.Connection, seed_password: str
) -> None:
    up(conn)
    conn.execute("DELETE FROM users WHERE role = %s", ("admin",))

    with pytest.raises(seed.SeedRefused, match="No Administrator exists"):
        migrate.reseed_admin(conn)


def test_reseed_leaves_a_deactivated_administrator_deactivated(
    conn: psycopg.Connection, seed_password: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Reissuing a credential is not a reactivation. An Administrator
    # deactivated on purpose must not come back because someone ran a console
    # command that advertises itself as narrow.
    up(conn)
    conn.execute("UPDATE users SET active = false WHERE role = %s", ("admin",))

    monkeypatch.setenv(SEED_ADMIN_PASSWORD, a_password())
    migrate.reseed_admin(conn)

    assert the_administrator(conn)["active"] is False


def test_reseed_without_a_users_table_refuses_with_guidance(conn: psycopg.Connection) -> None:
    with pytest.raises(seed.SeedRefused, match="no `users` table"):
        migrate.reseed_admin(conn)


# --- Concurrency -------------------------------------------------------------


def test_a_concurrent_runner_waits_for_the_migration_lock(
    conn: psycopg.Connection,
    database_url: str,
    seed_password: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The third layer behind the ledger and the seed guard: two runners that
    # both observe an empty `users` table would both insert, and with different
    # SEED_ADMIN_EMAIL values the unique index does not catch it either.
    #
    # The runner sets its own `lock_timeout`, so this waits on the real one —
    # turned down to keep the test quick. Matching the message matters: a bare
    # `raises(MigrationError)` is satisfied by any planning failure, so it would
    # still pass with the advisory lock deleted outright.
    monkeypatch.setattr(migrate, "LOCK_TIMEOUT_MS", 400)

    with psycopg.connect(database_url, autocommit=True) as other:
        other.execute("SELECT pg_advisory_lock(%s)", (migrate.MIGRATION_LOCK_ID,))

        with pytest.raises(MigrationError, match="held the lock on this database"):
            up(conn)

        assert ledger_versions(conn) == []
        other.execute("SELECT pg_advisory_unlock(%s)", (migrate.MIGRATION_LOCK_ID,))

    assert up(conn) == ALL_VERSIONS
    assert administrator_count(conn) == 1


def test_a_concurrent_reseed_waits_for_the_migration_lock(
    conn: psycopg.Connection,
    database_url: str,
    seed_password: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # `reseed_admin` takes the same lock, and for the same reason: two reseeds
    # that both pass the "still unclaimed, still the only one" guard both write,
    # and the operator holding the first password is told it works. The only
    # lock test drove `up`, so removing `_take_lock` from `reseed_admin` left
    # every reseed test green.
    up(conn)
    stored = the_administrator(conn)["password_hash"]
    monkeypatch.setattr(migrate, "LOCK_TIMEOUT_MS", 400)
    monkeypatch.setenv(SEED_ADMIN_PASSWORD, a_password())

    with psycopg.connect(database_url, autocommit=True) as other:
        other.execute("SELECT pg_advisory_lock(%s)", (migrate.MIGRATION_LOCK_ID,))

        with pytest.raises(MigrationError, match="held the lock on this database"):
            migrate.reseed_admin(conn)

        assert the_administrator(conn)["password_hash"] == stored
        other.execute("SELECT pg_advisory_unlock(%s)", (migrate.MIGRATION_LOCK_ID,))

    migrate.reseed_admin(conn)
    assert the_administrator(conn)["password_hash"] != stored


def test_a_migration_already_applied_under_the_lock_is_not_applied_twice(
    conn: psycopg.Connection, database_url: str, seed_password: str
) -> None:
    # The re-read under the lock: a plan drawn up before a concurrent runner
    # committed must not replay what that runner already applied.
    plan = discover_migrations()
    with psycopg.connect(database_url, autocommit=True) as other:
        up(other, plan)

    assert up(conn, plan) == []
    assert administrator_count(conn) == 1


def test_apply_declines_a_version_that_became_applied_after_the_plan(
    conn: psycopg.Connection, database_url: str, seed_password: str
) -> None:
    # `up` filters against a ledger snapshot taken *before* any lock is held,
    # so the test above never reaches `_apply` at all — deleting the re-read
    # inside the lock left the whole suite green. This is the race it exists
    # for: the snapshot is empty, the other runner commits, and this runner
    # then arrives at `_apply` for a version already applied. Replaying the
    # seed migration here would run its body a second time.
    plan = discover_migrations()
    migrate.ensure_ledger(conn)
    assert set(migrate.applied_versions(conn)) == set()

    with psycopg.connect(database_url, autocommit=True) as other:
        up(other, plan)

    assert [migrate._apply(conn, migration) for migration in plan] == [False] * len(ALL_VERSIONS)
    assert ledger_versions(conn) == ALL_VERSIONS
    assert administrator_count(conn) == 1


def test_reseed_refuses_an_email_that_is_not_the_seeded_one(
    conn: psycopg.Connection, seed_password: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Reissuing changes the password and the expiry and nothing else, so an
    # operator who supplies a different address would be told the credential
    # was reissued and then find nothing accepts what they typed.
    assert up(conn) == ALL_VERSIONS
    before = the_administrator(conn)

    monkeypatch.setenv(SEED_ADMIN_EMAIL, "someone.else@rocell.lk")
    monkeypatch.setenv(SEED_ADMIN_PASSWORD, a_password())

    with pytest.raises(seed.SeedRefused, match="does not change the address"):
        migrate.reseed_admin(conn)

    after = the_administrator(conn)
    assert after["password_hash"] == before["password_hash"]
    assert after["email"] == SEED_EMAIL
    assert verify_password(str(after["password_hash"]), seed_password)


def test_reseed_names_the_address_that_would_have_worked(
    conn: psycopg.Connection, seed_password: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert up(conn) == ALL_VERSIONS
    monkeypatch.setenv(SEED_ADMIN_EMAIL, "someone.else@rocell.lk")

    with pytest.raises(seed.SeedRefused, match=SEED_EMAIL):
        migrate.reseed_admin(conn)


def test_the_unclaimed_credential_is_reportable(
    conn: psycopg.Connection, seed_password: str
) -> None:
    # What the runner prints after seeding: the address to type and the
    # deadline to type it by. Both had to be queried out of the database before.
    assert up(conn) == ALL_VERSIONS

    record = seed.unclaimed_administrator(conn)
    assert record is not None
    email, expires_at = record
    assert email == SEED_EMAIL
    assert expires_at == the_administrator(conn)["temp_credential_expires_at"]


def test_a_claimed_credential_is_not_reported(conn: psycopg.Connection, seed_password: str) -> None:
    assert up(conn) == ALL_VERSIONS
    conn.execute("UPDATE users SET must_change_password = false WHERE role = %s", ("admin",))

    assert seed.unclaimed_administrator(conn) is None


def test_the_reseed_remedy_is_only_offered_where_it_would_work(
    conn: psycopg.Connection, seed_password: str, capsys: pytest.CaptureFixture[str]
) -> None:
    # `reseed-admin` refuses once a second Administrator exists, and the row
    # this reads is the *earliest* unclaimed one — on an already-migrated
    # database that may be an account an Administrator created. Pointing the
    # operator at a command that will refuse is worse than saying nothing.
    assert up(conn) == ALL_VERSIONS

    migrate._report_credential(conn)
    assert "make reseed-admin" in capsys.readouterr().out

    conn.execute(
        "INSERT INTO users (name, email, password_hash, role) VALUES (%s, %s, %s, %s)",
        ("Second Admin", "second@rocell.lk", "$argon2id$placeholder", "admin"),
    )

    migrate._report_credential(conn)
    out = capsys.readouterr().out
    assert "make reseed-admin" not in out
    assert "another Administrator can reissue it" in out


# --- A directive file that also carries SQL ----------------------------------


def test_a_directive_file_carrying_sql_is_refused(conn: psycopg.Connection, tmp_path: Path) -> None:
    # The SQL would never run, and the ledger row would still be written: the
    # migration would read as applied and have done nothing.
    (tmp_path / "20260101T0900_seed_and_more.up.sql").write_text(
        "-- rocell:python seed_administrator\nCREATE TABLE extra (id int);\n", encoding="utf-8"
    )
    (tmp_path / "20260101T0900_seed_and_more.down.sql").write_text(
        "DROP TABLE IF EXISTS extra;\n", encoding="utf-8"
    )

    with pytest.raises(MigrationError, match="both a `rocell:python` directive and SQL"):
        up(conn, discover_migrations(tmp_path))

    assert ledger_versions(conn) == []


def test_a_commented_out_directive_does_not_run_its_step(
    conn: psycopg.Connection, tmp_path: Path, seed_password: str
) -> None:
    # `/* ... */` is a comment. The directive match read the raw body while
    # `has_sql` stripped block comments, so the two halves of the guard read the
    # same file differently: a marker disabled by wrapping it in a block comment
    # still called `seed_administrator`. Now it names no step — and a body that
    # holds neither SQL nor a directive is refused rather than applied as a
    # no-op with a ledger row to show for it.
    (tmp_path / "20260101T0900_seed_later.up.sql").write_text(
        "/* Not yet — enable this when the table exists.\n"
        "-- rocell:python seed_administrator\n"
        "*/\n",
        encoding="utf-8",
    )
    (tmp_path / "20260101T0900_seed_later.down.sql").write_text("SELECT 1;\n", encoding="utf-8")

    with pytest.raises(MigrationError, match="holds no SQL and names no `rocell:python` step"):
        up(conn, discover_migrations(tmp_path))

    assert ledger_versions(conn) == []


def test_a_directive_quoted_in_a_block_comment_does_not_refuse_real_sql(
    conn: psycopg.Connection, tmp_path: Path
) -> None:
    # The other side of the same asymmetry: a plain SQL migration whose header
    # merely *quotes* the directive while explaining it was refused with
    # "carries both a `rocell:python` directive and SQL", which was untrue.
    (tmp_path / "20260101T0900_create_widgets.up.sql").write_text(
        "/* Unlike the seed, which uses\n"
        "-- rocell:python seed_administrator\n"
        "this one is ordinary SQL. */\n"
        "CREATE TABLE widgets (id int);\n",
        encoding="utf-8",
    )
    (tmp_path / "20260101T0900_create_widgets.down.sql").write_text(
        "DROP TABLE IF EXISTS widgets;\n", encoding="utf-8"
    )

    assert up(conn, discover_migrations(tmp_path)) == ["20260101T0900_create_widgets"]
    assert table_columns(conn, "widgets") == {"id"}


# --- down reverts what happened last, not what sorts last --------------------


def write_plain_pair(directory: Path, version: str, table: str) -> None:
    (directory / f"{version}.up.sql").write_text(
        f"CREATE TABLE {table} (id int);\n", encoding="utf-8"
    )
    (directory / f"{version}.down.sql").write_text(
        f"DROP TABLE IF EXISTS {table};\n", encoding="utf-8"
    )


def test_down_reverts_the_most_recently_applied_not_the_last_sorted(
    conn: psycopg.Connection, tmp_path: Path
) -> None:
    # A migration merged from a branch can carry an earlier timestamp than what
    # is already applied. Stepping down by version order would revert the wrong
    # one — and `down` must undo what happened last.
    write_plain_pair(tmp_path, "20260601T0900_create_alpha", "alpha")
    assert up(conn, discover_migrations(tmp_path)) == ["20260601T0900_create_alpha"]

    write_plain_pair(tmp_path, "20260101T0900_create_beta", "beta")
    plan = discover_migrations(tmp_path)
    assert up(conn, plan) == ["20260101T0900_create_beta"]

    assert down(conn, plan) == "20260101T0900_create_beta"
    assert table_columns(conn, "beta") == set()
    assert table_columns(conn, "alpha") != set()


# --- The command-line entry point --------------------------------------------


@pytest.fixture
def cli_env(database_url: str, monkeypatch: pytest.MonkeyPatch) -> str:
    """Point `main()` at this test's database, as `make migrate` would."""
    monkeypatch.setenv("DATABASE_URL", database_url)
    return database_url


def test_main_defaults_to_up(
    cli_env: str, seed_password: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert migrate.main([]) == 0

    out = capsys.readouterr().out
    for version in ALL_VERSIONS:
        assert version in out


def test_main_up_is_idempotent(
    cli_env: str, seed_password: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert migrate.main(["up"]) == 0
    capsys.readouterr()

    assert migrate.main(["up"]) == 0
    assert "nothing to apply" in capsys.readouterr().out


def test_main_status_lists_every_migration(
    cli_env: str, seed_password: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert migrate.main(["up"]) == 0
    capsys.readouterr()

    assert migrate.main(["status"]) == 0
    out = capsys.readouterr().out
    assert out.count("applied") == len(ALL_VERSIONS)
    assert "pending" not in out


def test_main_reseed_admin_succeeds(
    cli_env: str, seed_password: str, capsys: pytest.CaptureFixture[str]
) -> None:
    # `make reseed-admin` exiting 2 with a usage message would otherwise leave
    # the suite green.
    assert migrate.main(["up"]) == 0
    capsys.readouterr()

    assert migrate.main(["reseed-admin"]) == 0
    assert "reissued" in capsys.readouterr().out


def test_main_surfaces_a_seed_refusal(
    cli_env: str, seed_password: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert migrate.main(["up"]) == 0
    with psycopg.connect(cli_env, autocommit=True) as other:
        other.execute("UPDATE users SET must_change_password = false WHERE role = %s", ("admin",))
    capsys.readouterr()

    assert migrate.main(["reseed-admin"]) == 1
    assert "already been claimed" in capsys.readouterr().err


def test_main_surfaces_a_migration_failure(
    cli_env: str,
    seed_password: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv(SEED_ADMIN_PASSWORD)

    assert migrate.main(["up"]) == 1
    assert SEED_ADMIN_PASSWORD in capsys.readouterr().err


def test_main_without_a_database_url_exits_non_zero_naming_it(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)

    assert migrate.main(["status"]) == 1
    assert "DATABASE_URL" in capsys.readouterr().err


def test_main_refuses_down_without_the_confirmation_flag(
    cli_env: str, seed_password: str, capsys: pytest.CaptureFixture[str]
) -> None:
    # `down` twice drops `users` with every account in it, and it is documented
    # as an ordinary operator command.
    assert migrate.main(["up"]) == 0
    capsys.readouterr()

    assert migrate.main(["down"]) == 1
    assert migrate.CONFIRM_FLAG in capsys.readouterr().err

    with psycopg.connect(cli_env, autocommit=True) as other:
        assert administrator_count(other) == 1


def test_main_steps_down_with_the_confirmation_flag(
    cli_env: str, seed_password: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert migrate.main(["up"]) == 0
    capsys.readouterr()

    assert migrate.main(["down", migrate.CONFIRM_FLAG]) == 0
    assert AUDIT_LOG_FLAGGED_INDEX_VERSION in capsys.readouterr().out

    assert migrate.main(["down", migrate.CONFIRM_FLAG]) == 0
    assert ANOMALY_BASELINE_VERSION in capsys.readouterr().out

    assert migrate.main(["down", migrate.CONFIRM_FLAG]) == 0
    assert SCAN_RATE_LIMIT_VERSION in capsys.readouterr().out

    assert migrate.main(["down", migrate.CONFIRM_FLAG]) == 0
    assert SCAN_VERSION in capsys.readouterr().out

    assert migrate.main(["down", migrate.CONFIRM_FLAG]) == 0
    assert CATALOGUE_VERSION in capsys.readouterr().out

    assert migrate.main(["down", migrate.CONFIRM_FLAG]) == 0
    assert AUDIT_LOG_VERSION in capsys.readouterr().out

    assert migrate.main(["down", migrate.CONFIRM_FLAG]) == 0
    assert LOGIN_THROTTLING_VERSION in capsys.readouterr().out

    assert migrate.main(["down", migrate.CONFIRM_FLAG]) == 0
    assert TRACK_ACTIVITY_VERSION in capsys.readouterr().out

    assert migrate.main(["down", migrate.CONFIRM_FLAG]) == 0
    assert CREATE_SESSIONS_VERSION in capsys.readouterr().out

    assert migrate.main(["down", migrate.CONFIRM_FLAG]) == 0
    assert SEED_VERSION in capsys.readouterr().out

    with psycopg.connect(cli_env, autocommit=True) as other:
        assert administrator_count(other) == 0


def test_main_reports_nothing_to_revert(cli_env: str, capsys: pytest.CaptureFixture[str]) -> None:
    assert migrate.main(["down", migrate.CONFIRM_FLAG]) == 0
    assert "nothing to revert" in capsys.readouterr().out


@pytest.mark.parametrize(
    "args", [["frobnicate"], ["up", "--yes"], ["status", "extra"], ["--force"]]
)
def test_main_rejects_an_unknown_invocation(
    args: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    assert migrate.main(args) == 2
    assert "usage:" in capsys.readouterr().err


@pytest.mark.parametrize("flag", ["-h", "--help", "help"])
def test_main_prints_usage_for_help(flag: str, capsys: pytest.CaptureFixture[str]) -> None:
    assert migrate.main([flag]) == 0
    assert "usage:" in capsys.readouterr().out
