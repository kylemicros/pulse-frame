import re
from collections.abc import Generator
from pathlib import Path

import psycopg
import pytest

from pulse_frame import store
from tests import database
from tests.database import (
    CHILD_TABLES,
    PUBLIC_SCHEMA,
    SESSION_ID,
    SESSION_KEY,
    SESSION_TABLE,
    STORE_TABLES,
    SYNTHETIC_VALUES,
    store_columns,
    store_tables,
    tables_in,
)

LISTED_COLUMNS = {
    "sessions": {
        "id",
        "started_wall_ns",
        "started_monotonic_ns",
        "counted_monotonic_ns",
    },
    "frame_samples": {
        "session_id",
        "t_ms",
        "forehead_r",
        "forehead_g",
        "forehead_b",
        "left_cheek_r",
        "left_cheek_g",
        "left_cheek_b",
        "right_cheek_r",
        "right_cheek_g",
        "right_cheek_b",
        "moving",
    },
    "beats": {"session_id", "t_ms"},
    "intervals": {"session_id", "t_ms", "interval_ms", "flag"},
    "hrv_readings": {
        "session_id",
        "t_ms",
        "rmssd_ms",
        "sdnn_ms",
        "window_ms",
        "accepted_count",
    },
}
CLOCK_COLUMNS = {
    ("sessions", "started_wall_ns"),
    ("sessions", "started_monotonic_ns"),
    ("sessions", "counted_monotonic_ns"),
    ("frame_samples", "t_ms"),
    ("beats", "t_ms"),
    ("intervals", "t_ms"),
    ("hrv_readings", "t_ms"),
}
PINNED_TYPES = {
    ("intervals", "flag"): "smallint",
    ("hrv_readings", "window_ms"): "double precision",
    ("hrv_readings", "accepted_count"): "integer",
    ("hrv_readings", "rmssd_ms"): "double precision",
    ("hrv_readings", "sdnn_ms"): "double precision",
}
FLAG_CODES = range(7)
OUT_OF_RANGE_FLAGS = [-1, 7]
DUPLICATE_KEY = {SESSION_KEY, "t_ms"}
WATCH_PREFIX = "watch_"
INDEXES = """
SELECT relation.relname, array_agg(attribute.attname::text), index_row.indisprimary
FROM pg_index AS index_row
JOIN pg_class AS relation ON relation.oid = index_row.indrelid
JOIN pg_namespace AS space ON space.oid = relation.relnamespace
JOIN pg_attribute AS attribute
  ON attribute.attrelid = index_row.indrelid
 AND attribute.attnum = ANY (index_row.indkey)
WHERE space.nspname = %s
GROUP BY relation.relname, index_row.indexrelid, index_row.indisprimary
"""
FORBIDDEN_WORDS = {
    "image",
    "images",
    "picture",
    "photo",
    "jpeg",
    "jpg",
    "png",
    "pixel",
    "pixels",
    "landmark",
    "landmarks",
    "name",
    "names",
    "birth",
    "birthday",
    "dob",
}
FOREIGN_KEYS = """
SELECT child.relname, child_column.attname, parent.relname, parent_column.attname,
       constraint_row.confdeltype
FROM pg_constraint AS constraint_row
JOIN pg_class AS child ON child.oid = constraint_row.conrelid
JOIN pg_class AS parent ON parent.oid = constraint_row.confrelid
JOIN pg_namespace AS space ON space.oid = child.relnamespace
JOIN pg_attribute AS child_column
  ON child_column.attrelid = constraint_row.conrelid
 AND child_column.attnum = ANY (constraint_row.conkey)
JOIN pg_attribute AS parent_column
  ON parent_column.attrelid = constraint_row.confrelid
 AND parent_column.attnum = ANY (constraint_row.confkey)
WHERE constraint_row.contype = 'f' AND space.nspname = %s
"""
ROW_SECURITY = """
SELECT relation.relname, relation.relrowsecurity
FROM pg_class AS relation
JOIN pg_namespace AS space ON space.oid = relation.relnamespace
WHERE space.nspname = %s AND relation.relkind IN ('r', 'p')
"""
RELATION_GRANTS = """
SELECT relation.relname, coalesce(grantee.rolname, 'PUBLIC'), privilege.privilege_type
FROM pg_class AS relation
JOIN pg_namespace AS space ON space.oid = relation.relnamespace
CROSS JOIN LATERAL aclexplode(relation.relacl) AS privilege
LEFT JOIN pg_roles AS grantee ON grantee.oid = privilege.grantee
WHERE space.nspname = %s AND privilege.grantee <> relation.relowner
"""
SCHEMA_GRANTS = """
SELECT space.nspname, coalesce(grantee.rolname, 'PUBLIC'), privilege.privilege_type
FROM pg_namespace AS space
CROSS JOIN LATERAL aclexplode(space.nspacl) AS privilege
LEFT JOIN pg_roles AS grantee ON grantee.oid = privilege.grantee
WHERE space.nspname = %s AND privilege.grantee <> space.nspowner
"""
CASCADE = "c"
PLANTED_OBJECT_TYPES = {"r", "S", "n"}
COUNTED_COLUMN = "counted_monotonic_ns"
LAST_MIGRATION_WITHOUT_THE_COUNTED_START = "20261117150000_capture_and_replay.sql"
COUNTED_DEFAULT = """
SELECT column_default FROM information_schema.columns
WHERE table_schema = %s
  AND table_name = 'sessions'
  AND column_name = 'counted_monotonic_ns'
"""


@pytest.fixture
def store_without_the_counted_start(store_database: str) -> Generator[str]:
    server = database.server_url()
    url = database.recreate_database(server, database.TEST_DATABASE)
    database.apply_migration_files(url, migrations_up_to_the_counted_start())
    yield url
    database.recreate_database(server, database.TEST_DATABASE)
    database.apply_migrations(store_database)


def migrations_up_to_the_counted_start() -> list[Path]:
    return [
        path
        for path in database.migration_files()
        if path.name <= LAST_MIGRATION_WITHOUT_THE_COUNTED_START
    ]


def migrations_from_the_counted_start() -> list[Path]:
    return [
        path
        for path in database.migration_files()
        if path.name > LAST_MIGRATION_WITHOUT_THE_COUNTED_START
    ]


@pytest.fixture
def hostile_store(store_database: str) -> Generator[str]:
    server = database.server_url()
    url = database.recreate_database(server, database.TEST_DATABASE)
    planted = database.plant_public_default_privileges(url)
    assert planted.issuperset(PLANTED_OBJECT_TYPES), (
        f"default privileges to PUBLIC landed only for object types {sorted(planted)}"
    )
    database.apply_migrations(url)
    yield url
    database.recreate_database(server, database.TEST_DATABASE)
    database.apply_migrations(store_database)


def query(url: str, statement: str) -> list[tuple[object, ...]]:
    with psycopg.connect(url) as conn:
        return conn.execute(statement, [store.STORE_SCHEMA]).fetchall()


def test_migrations_leave_exactly_the_five_session_tables_in_the_store_schema(
    store_url: str,
) -> None:
    tables = store_tables(store_url)
    assert len(tables) == 5
    assert set(tables) == set(STORE_TABLES)


def test_no_watch_table_is_left_in_the_store_schema(store_url: str) -> None:
    watch = [
        table for table in store_tables(store_url) if table.startswith(WATCH_PREFIX)
    ]
    assert watch == [], f"watch tables still in the store: {watch}"


def test_public_schema_holds_no_table(store_url: str) -> None:
    assert tables_in(store_url, PUBLIC_SCHEMA) == []


def test_row_level_security_is_on_for_every_store_table(store_url: str) -> None:
    flags = dict(query(store_url, ROW_SECURITY))
    assert set(flags) == set(STORE_TABLES)
    off = sorted(table for table, enabled in flags.items() if not enabled)
    assert off == [], f"store tables without row level security: {off}"


def test_the_migration_grants_store_tables_to_no_role_but_their_owner(
    store_url: str,
) -> None:
    grants = sorted(
        f"{table} to {role}: {kind}"
        for table, role, kind in query(store_url, RELATION_GRANTS)
    )
    assert grants == [], f"store relations granted to other roles: {grants}"


def test_the_migration_grants_the_store_schema_to_no_role_but_its_owner(
    store_url: str,
) -> None:
    grants = sorted(
        f"{schema} to {role}: {kind}"
        for schema, role, kind in query(store_url, SCHEMA_GRANTS)
    )
    assert grants == [], f"the store schema is granted to other roles: {grants}"


@pytest.mark.parametrize(
    "statement",
    [RELATION_GRANTS, SCHEMA_GRANTS],
    ids=["tables-and-sequences", "schema"],
)
def test_the_migration_grants_nothing_to_public_under_hostile_default_privileges(
    hostile_store: str, statement: str
) -> None:
    grants = sorted(
        f"{name} to {role}: {kind}"
        for name, role, kind in query(hostile_store, statement)
    )
    assert grants == [], (
        f"with every new table, sequence and schema granted to PUBLIC by default,"
        f" the migration left these grants: {grants}"
    )


@pytest.mark.parametrize("table", STORE_TABLES)
def test_each_table_has_exactly_its_listed_columns(store_url: str, table: str) -> None:
    present = {
        column.name for column in store_columns(store_url) if column.table == table
    }
    missing = sorted(LISTED_COLUMNS[table] - present)
    extra = sorted(present - LISTED_COLUMNS[table])
    assert missing == [], f"`{table}` lacks the columns {missing}"
    assert extra == [], f"`{table}` has unlisted columns {extra}"


def test_interval_flag_hrv_window_and_accepted_count_have_their_pinned_types(
    store_url: str,
) -> None:
    types = {
        (column.table, column.name): column.data_type
        for column in store_columns(store_url)
    }
    wrong = sorted(
        f"{table}.{name}: {types.get((table, name))}, expected {expected}"
        for (table, name), expected in PINNED_TYPES.items()
        if types.get((table, name)) != expected
    )
    assert wrong == [], wrong


def test_every_store_column_is_not_null_so_hrv_rows_are_written_only_when_set(
    store_url: str,
) -> None:
    nullable = sorted(
        f"{column.table}.{column.name}"
        for column in store_columns(store_url)
        if column.nullable
    )
    assert nullable == [], f"columns that allow NULL: {nullable}"


@pytest.mark.parametrize("flag", FLAG_CODES)
def test_intervals_accept_every_tracker_flag_code(store_url: str, flag: int) -> None:
    session_id = database.seed_session(store_url)
    columns = store_columns(store_url)
    row = {"t_ms": database.START_MS + 9_000, "interval_ms": 801.5, "flag": flag}

    with psycopg.connect(store_url) as conn:
        database.insert_row(conn, columns, "intervals", row, session_id)

    stored = database.stored_rows(store_url, "intervals", session_id, ["t_ms", "flag"])
    assert (row["t_ms"], flag) in stored


@pytest.mark.parametrize("flag", OUT_OF_RANGE_FLAGS)
def test_intervals_refuse_a_flag_code_outside_the_tracker_flags(
    store_url: str, flag: int
) -> None:
    session_id = database.seed_session(store_url)
    columns = store_columns(store_url)
    row = {"t_ms": database.START_MS + 9_000, "interval_ms": 801.5, "flag": flag}

    with (
        pytest.raises(psycopg.errors.CheckViolation),
        psycopg.connect(store_url) as conn,
    ):
        database.insert_row(conn, columns, "intervals", row, session_id)

    counts = database.rows_under(store_url, session_id)
    assert counts["intervals"] == database.SEEDED_COUNTS["intervals"]


def child_indexes(url: str, table: str) -> list[tuple[set[str], bool]]:
    return [
        (set(columns), primary)
        for name, columns, primary in query(url, INDEXES)
        if name == table
    ]


@pytest.mark.parametrize("table", CHILD_TABLES)
def test_every_child_table_is_keyed_by_its_session_and_time(
    store_url: str, table: str
) -> None:
    primary = [
        columns for columns, is_primary in child_indexes(store_url, table) if is_primary
    ]
    assert primary == [DUPLICATE_KEY], (
        f"`{table}` primary key is {[sorted(key) for key in primary]},"
        f" expected {sorted(DUPLICATE_KEY)}"
    )


@pytest.mark.parametrize("table", CHILD_TABLES)
def test_a_child_tables_only_index_is_its_primary_key(
    store_url: str, table: str
) -> None:
    others = sorted(
        sorted(columns)
        for columns, is_primary in child_indexes(store_url, table)
        if not is_primary
    )
    assert others == [], f"`{table}` keeps indexes beside its primary key: {others}"


@pytest.mark.parametrize("table", CHILD_TABLES)
def test_a_duplicate_child_row_is_refused_by_the_database(
    store_url: str, table: str
) -> None:
    session_id = database.seed_session(store_url)
    columns = store_columns(store_url)
    (first, *_) = database.SEEDED_ROWS[table]

    with (
        pytest.raises(psycopg.errors.UniqueViolation),
        psycopg.connect(store_url) as conn,
    ):
        database.insert_row(conn, columns, table, first, session_id)

    assert database.rows_under(store_url, session_id) == database.SEEDED_COUNTS


def test_every_column_holds_a_number_flag_or_time(store_url: str) -> None:
    other = sorted(
        f"{column.table}.{column.name}: {column.data_type}"
        for column in store_columns(store_url)
        if column.data_type not in SYNTHETIC_VALUES
    )
    assert other == [], f"columns that could hold more than a number: {other}"


def test_clock_columns_are_bigint(store_url: str) -> None:
    clocks = {
        (column.table, column.name): column.data_type
        for column in store_columns(store_url)
        if column.name.endswith("_ns") or column.name == "t_ms"
    }
    assert set(clocks) >= CLOCK_COLUMNS, sorted(CLOCK_COLUMNS - set(clocks))
    narrow = sorted(
        f"{table}.{name}: {data_type}"
        for (table, name), data_type in clocks.items()
        if data_type != "bigint"
    )
    assert narrow == [], f"clock columns too narrow for ns or epoch ms: {narrow}"


def test_no_column_is_named_for_a_frame_image_landmark_name_or_birth_date(
    store_url: str,
) -> None:
    named = sorted(
        f"{column.table}.{column.name}"
        for column in store_columns(store_url)
        if FORBIDDEN_WORDS & set(re.split(r"[^a-z]+", column.name.lower()))
        or "frame" in column.name.lower()
    )
    assert named == [], f"columns named for data the store never holds: {named}"


@pytest.mark.parametrize("table", CHILD_TABLES)
def test_every_child_table_belongs_to_its_session_and_goes_with_it(
    store_url: str, table: str
) -> None:
    keys = set(query(store_url, FOREIGN_KEYS))
    assert (table, SESSION_KEY, SESSION_TABLE, SESSION_ID, CASCADE) in keys, (
        f"`{table}.{SESSION_KEY}` is not a foreign key to "
        f"`{SESSION_TABLE}.{SESSION_ID}` with ON DELETE CASCADE"
    )
    session_key = next(
        column
        for column in store_columns(store_url)
        if column.table == table and column.name == SESSION_KEY
    )
    assert not session_key.nullable, f"`{table}.{SESSION_KEY}` may be NULL"


def test_the_counted_start_defaults_to_zero_so_a_session_without_one_counts_it_all(
    store_url: str,
) -> None:
    session_id = database.insert_recording(
        store_url, database.WALL_NS, database.MONOTONIC_NS, []
    )

    defaults = query(store_url, COUNTED_DEFAULT)

    assert defaults == [("0",)], f"the counted start defaults to {defaults}"
    assert database.stored_rows(
        store_url, SESSION_TABLE, session_id, [COUNTED_COLUMN]
    ) == [(0,)]


def test_sessions_stored_before_the_counted_start_migration_read_zero_after_it(
    store_without_the_counted_start: str,
) -> None:
    url = store_without_the_counted_start
    later = migrations_from_the_counted_start()
    assert later, "no migration after the capture and replay one adds the counted start"
    session_id = database.insert_recording(
        url, database.WALL_NS, database.MONOTONIC_NS, []
    )

    database.apply_migration_files(url, later)

    assert database.stored_rows(
        url, SESSION_TABLE, session_id, ["started_monotonic_ns", COUNTED_COLUMN]
    ) == [(database.MONOTONIC_NS, 0)]
