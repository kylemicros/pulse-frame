import os
import time
import uuid
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.rows import TupleRow

from pulse_frame import store

TEST_DATABASE = "pulse_frame_test"
URL_VARIABLE = "PULSE_FRAME_DATABASE_URL"
_SERVER_URL = os.environ.pop(URL_VARIABLE, "")
RUN_LOCK_WAIT_S = 10.0
RUN_LOCK_RETRY_S = 0.1
UNREACHABLE_URL = "postgresql://probe@127.0.0.1:1/probe"
MALFORMED_URL = "postgresql://probe@127.0.0.1:1/probe?bogus_option=on"
MALFORMED_MARKER = "bogus_option"
READ_ONLY_TRANSACTION = "25006"
SUPABASE_IGNORED_FOLDERS = frozenset({".temp", ".branches"})
PUBLIC_DEFAULT_PRIVILEGES = (
    "ALTER DEFAULT PRIVILEGES FOR ROLE current_user GRANT ALL ON TABLES TO PUBLIC",
    "ALTER DEFAULT PRIVILEGES FOR ROLE current_user GRANT ALL ON SEQUENCES TO PUBLIC",
    "ALTER DEFAULT PRIVILEGES FOR ROLE current_user GRANT USAGE ON SCHEMAS TO PUBLIC",
)
PUBLIC_DEFAULT_ACL = """
SELECT DISTINCT defaults.defaclobjtype::text FROM pg_default_acl AS defaults
CROSS JOIN LATERAL aclexplode(defaults.defaclacl) AS privilege
WHERE defaults.defaclrole = current_user::regrole AND privilege.grantee = 0
"""
PUBLIC_SCHEMA = "public"
HIDDEN_SUFFIX = "_hidden"
RUN_LOCK = 55_322_001
REPO = Path(__file__).resolve().parents[2]
MIGRATIONS = REPO / "supabase" / "migrations"
SESSION_TABLE = "sessions"
SESSION_ID = "id"
SESSION_KEY = "session_id"
CHILD_TABLES = (
    "frame_samples",
    "beats",
    "intervals",
    "hrv_readings",
    "watch_ecg_samples",
    "watch_optical_beats",
)
STORE_TABLES = (SESSION_TABLE, *CHILD_TABLES)
SYNTHETIC_VALUES: dict[str, object] = {
    "smallint": 1,
    "integer": 1,
    "bigint": 1,
    "real": 0.5,
    "double precision": 0.5,
    "numeric": 0.5,
    "boolean": False,
    "timestamp with time zone": datetime(2026, 1, 1, tzinfo=UTC),
    "uuid": uuid.UUID(int=1),
}

WALL_NS = 1_794_787_200_123_456_789
MONOTONIC_NS = 734_512_345_678_901
START_MS = WALL_NS // 1_000_000
FRAME_STEP_MS = 33
ECG_LAST_SAMPLE = 15_359

type Row = dict[str, object]


def frame_sample(step: int) -> Row:
    return {
        "t_ms": START_MS + step * FRAME_STEP_MS,
        "forehead_r": 168.25 + step,
        "forehead_g": 121.5 + step,
        "forehead_b": 98.75 + step,
        "left_cheek_r": 172.0 + step,
        "left_cheek_g": 118.25 + step,
        "left_cheek_b": 101.5 + step,
        "right_cheek_r": 170.5 + step,
        "right_cheek_g": 119.75 + step,
        "right_cheek_b": 100.0 + step,
        "moving": step == 2,
    }


SEEDED_ROWS: dict[str, tuple[Row, ...]] = {
    "sessions": ({"started_wall_ns": WALL_NS, "started_monotonic_ns": MONOTONIC_NS},),
    "frame_samples": tuple(frame_sample(step) for step in range(3)),
    "beats": (
        {"t_ms": START_MS + 412},
        {"t_ms": START_MS + 1_236},
        {"t_ms": START_MS + 2_049},
    ),
    "intervals": (
        {"t_ms": START_MS + 1_236, "interval_ms": 824.0, "flagged": False},
        {"t_ms": START_MS + 2_049, "interval_ms": 813.0, "flagged": False},
        {"t_ms": START_MS + 3_418, "interval_ms": 1_369.0, "flagged": True},
    ),
    "hrv_readings": (
        {"t_ms": START_MS + 30_000, "rmssd_ms": 42.7, "sdnn_ms": 51.3},
        {"t_ms": START_MS + 60_000, "rmssd_ms": 39.2, "sdnn_ms": 48.9},
        {"t_ms": START_MS + 90_000, "rmssd_ms": 44.1, "sdnn_ms": 53.6},
    ),
    "watch_ecg_samples": tuple(
        {"recording": recording, "sample_index": index, "microvolts": microvolts}
        for recording in (1, 2)
        for index, microvolts in (
            (0, -84.2),
            (7_680, 1_204.6),
            (ECG_LAST_SAMPLE, 312.9),
        )
    ),
    "watch_optical_beats": (
        {"t_ms": START_MS + 405},
        {"t_ms": START_MS + 1_228},
        {"t_ms": START_MS + 2_061},
    ),
}
SEEDED_COUNTS = {table: len(rows) for table, rows in SEEDED_ROWS.items()}
NONE_LEFT = dict.fromkeys(STORE_TABLES, 0)


class RefusedDatabaseError(ValueError):
    pass


@dataclass(frozen=True)
class Column:
    table: str
    name: str
    data_type: str
    nullable: bool
    filled_by_database: bool


def require_test_database(name: str) -> str:
    if name != TEST_DATABASE:
        raise RefusedDatabaseError(
            f"REFUSED_DATABASE: the store tests create, fill and drop only "
            f"`{TEST_DATABASE}`, and were asked for another database. "
            f"Pass `{TEST_DATABASE}`; the session data never takes part in a test."
        )
    return name


def require_test_url(url: str) -> str:
    require_test_database(str(conninfo_to_dict(url).get("dbname", "")))
    return url


def parses_as_conninfo(url: str) -> bool:
    try:
        conninfo_to_dict(url)
    except psycopg.ProgrammingError:
        return False
    return True


def server_url() -> str:
    url = _SERVER_URL.strip()
    if not url:
        pytest.fail(
            f"DATABASE_URL_MISSING: the store tests need a running Postgres and "
            f"`{URL_VARIABLE}` is not set. Start the local database and set the "
            "variable for this command; the tests make and drop their own "
            f"`{TEST_DATABASE}` beside it.",
            pytrace=False,
        )
    if not parses_as_conninfo(url):
        pytest.fail(
            f"DATABASE_URL_INVALID: the store tests could not read `{URL_VARIABLE}`"
            " as a connection URL. Set it to the form"
            " postgresql://user@127.0.0.1:port/dbname, then run the tests again.",
            pytrace=False,
        )
    return url


def with_database_url(url: str) -> dict[str, str]:
    return {**os.environ, URL_VARIABLE: url}


def open_server(server: str) -> psycopg.Connection[TupleRow] | None:
    try:
        return psycopg.connect(server, autocommit=True)
    except psycopg.OperationalError:
        return None


def take_run_lock(holder: psycopg.Connection[TupleRow], wait_s: float) -> bool:
    deadline = time.monotonic() + wait_s
    while True:
        row = holder.execute("SELECT pg_try_advisory_lock(%s)", [RUN_LOCK]).fetchone()
        if row == (True,):
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(RUN_LOCK_RETRY_S)


@contextmanager
def run_lock(server: str, wait_s: float = RUN_LOCK_WAIT_S) -> Generator[None]:
    holder = open_server(server)
    if holder is None:
        pytest.fail(
            f"DATABASE_UNAVAILABLE: the store tests could not reach the database"
            f" in `{URL_VARIABLE}`. Start it with `supabase start --workdir <repo>"
            " --network-id pulse-frame-local` (see"
            " pulse-frame-wiki/ecosystem/store.md), then run the tests again.",
            pytrace=False,
        )
    with holder:
        if not take_run_lock(holder, wait_s):
            pytest.fail(
                f"TEST_DATABASE_BUSY: another test run held the store test lock for"
                f" {wait_s:g} s, so `{TEST_DATABASE}` was left alone. Let that run"
                " finish or stop it, then run the tests again.",
                pytrace=False,
            )
        yield
        holder.execute("SELECT pg_advisory_unlock(%s)", [RUN_LOCK])


def scoped_url(server: str, name: str) -> str:
    return make_conninfo(server, dbname=require_test_database(name))


def drop_database(server: str, name: str) -> None:
    require_test_database(name)
    with psycopg.connect(server, autocommit=True) as admin:
        admin.execute(
            sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                sql.Identifier(name)
            )
        )


def recreate_database(server: str, name: str) -> str:
    drop_database(server, name)
    with psycopg.connect(server, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    return scoped_url(server, name)


def migration_files() -> list[Path]:
    return sorted(MIGRATIONS.glob("*.sql"))


def apply_migrations(url: str) -> None:
    require_test_url(url)
    files = migration_files()
    if not files:
        pytest.fail(
            "MIGRATION_MISSING: supabase/migrations holds no .sql file, so the "
            "test database has no tables. Write the session store migration there.",
            pytrace=False,
        )
    with psycopg.connect(url) as conn:
        for path in files:
            conn.execute(sql.SQL(path.read_text(encoding="utf-8")))


def store_table(table: str) -> sql.Identifier:
    return sql.Identifier(store.STORE_SCHEMA, table)


def tables_in(url: str, schema: str) -> list[str]:
    with psycopg.connect(url) as conn:
        rows = conn.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = %s ORDER BY tablename",
            [schema],
        ).fetchall()
    return [row[0] for row in rows]


def store_tables(url: str) -> list[str]:
    return tables_in(url, store.STORE_SCHEMA)


def empty_tables(url: str) -> None:
    require_test_url(url)
    names = store_tables(url)
    if not names:
        return
    with psycopg.connect(url) as conn:
        conn.execute(
            sql.SQL("TRUNCATE {} RESTART IDENTITY CASCADE").format(
                sql.SQL(", ").join(store_table(name) for name in names)
            )
        )


def store_columns(url: str) -> list[Column]:
    with psycopg.connect(url) as conn:
        rows = conn.execute(
            "SELECT table_name, column_name, data_type, is_nullable = 'YES',"
            " column_default IS NOT NULL OR is_identity = 'YES'"
            " OR is_generated = 'ALWAYS'"
            " FROM information_schema.columns WHERE table_schema = %s"
            " ORDER BY table_name, ordinal_position",
            [store.STORE_SCHEMA],
        ).fetchall()
    return [Column(*row) for row in rows]


def synthetic_value(column: Column) -> object:
    if column.data_type not in SYNTHETIC_VALUES:
        pytest.fail(
            f"NON_NUMERIC_COLUMN: `{column.table}.{column.name}` has type "
            f"`{column.data_type}`, which is not a number, flag or time; the "
            "store holds numbers only.",
            pytrace=False,
        )
    return SYNTHETIC_VALUES[column.data_type]


def insert_row(
    conn: psycopg.Connection,
    columns: list[Column],
    table: str,
    seeded: Row,
    session_id: object,
) -> object:
    values: Row = {
        column.name: synthetic_value(column)
        for column in columns
        if column.table == table
        and not column.nullable
        and not column.filled_by_database
        and column.name != SESSION_KEY
    }
    values.update(seeded)
    if table != SESSION_TABLE:
        values[SESSION_KEY] = session_id
    returned = sql.Identifier(SESSION_ID) if table == SESSION_TABLE else sql.SQL("1")
    statement = sql.SQL("INSERT INTO {} ({}) VALUES ({}) RETURNING {}").format(
        store_table(table),
        sql.SQL(", ").join(sql.Identifier(name) for name in values),
        sql.SQL(", ").join(sql.Placeholder() for _ in values),
        returned,
    )
    row = conn.execute(statement, list(values.values())).fetchone()
    assert row is not None, f"inserting a seeded row into `{table}` returned nothing"
    return row[0]


def seed_session(url: str) -> int:
    require_test_url(url)
    columns = store_columns(url)
    with psycopg.connect(url) as conn:
        (session,) = SEEDED_ROWS[SESSION_TABLE]
        session_id = insert_row(conn, columns, SESSION_TABLE, session, None)
        for table in CHILD_TABLES:
            for seeded in SEEDED_ROWS[table]:
                insert_row(conn, columns, table, seeded, session_id)
    assert isinstance(session_id, int), f"session IDs are numbers, got {session_id!r}"
    return session_id


def rows_under(url: str, session_id: object) -> dict[str, int]:
    counts: dict[str, int] = {}
    with psycopg.connect(url) as conn:
        for table in STORE_TABLES:
            key = SESSION_ID if table == SESSION_TABLE else SESSION_KEY
            row = conn.execute(
                sql.SQL("SELECT count(*) FROM {} WHERE {} = %s").format(
                    store_table(table), sql.Identifier(key)
                ),
                [session_id],
            ).fetchone()
            assert row is not None
            counts[table] = row[0]
    return counts


def rename_schema(url: str, old: str, new: str) -> None:
    require_test_url(url)
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(
            sql.SQL("ALTER SCHEMA {} RENAME TO {}").format(
                sql.Identifier(old), sql.Identifier(new)
            )
        )


def hide_store(url: str) -> None:
    require_test_url(url)
    rename_schema(url, store.STORE_SCHEMA, store.STORE_SCHEMA + HIDDEN_SUFFIX)


def restore_store(url: str) -> None:
    require_test_url(url)
    rename_schema(url, store.STORE_SCHEMA + HIDDEN_SUFFIX, store.STORE_SCHEMA)


def set_read_only(url: str, read_only: bool) -> None:
    require_test_url(url)
    setting = sql.SQL(
        "SET default_transaction_read_only = on"
        if read_only
        else "RESET default_transaction_read_only"
    )
    with psycopg.connect(
        url, autocommit=True, options="-c default_transaction_read_only=off"
    ) as conn:
        conn.execute(
            sql.SQL("ALTER DATABASE {} {}").format(
                sql.Identifier(TEST_DATABASE), setting
            )
        )


def plant_public_default_privileges(url: str) -> set[str]:
    require_test_url(url)
    with psycopg.connect(url, autocommit=True) as conn:
        for statement in PUBLIC_DEFAULT_PRIVILEGES:
            conn.execute(sql.SQL(statement))
        rows = conn.execute(PUBLIC_DEFAULT_ACL).fetchall()
    return {row[0] for row in rows}


def make_read_only(url: str) -> None:
    set_read_only(url, read_only=True)


def make_writable(url: str) -> None:
    set_read_only(url, read_only=False)
