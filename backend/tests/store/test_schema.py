import re
from collections.abc import Generator

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
    "sessions": {"id", "started_wall_ns", "started_monotonic_ns"},
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
    "intervals": {"session_id", "t_ms", "interval_ms", "flagged"},
    "hrv_readings": {"session_id", "t_ms", "rmssd_ms", "sdnn_ms"},
    "watch_ecg_samples": {"session_id", "recording", "sample_index", "microvolts"},
    "watch_optical_beats": {"session_id", "t_ms"},
}
CLOCK_COLUMNS = {
    ("sessions", "started_wall_ns"),
    ("sessions", "started_monotonic_ns"),
    ("frame_samples", "t_ms"),
    ("beats", "t_ms"),
    ("intervals", "t_ms"),
    ("hrv_readings", "t_ms"),
    ("watch_optical_beats", "t_ms"),
}
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


def test_migration_creates_exactly_the_seven_session_tables_in_the_store_schema(
    store_url: str,
) -> None:
    assert set(store_tables(store_url)) == set(STORE_TABLES)


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
def test_each_table_has_its_listed_columns(store_url: str, table: str) -> None:
    present = {
        column.name for column in store_columns(store_url) if column.table == table
    }
    missing = sorted(LISTED_COLUMNS[table] - present)
    assert missing == [], f"`{table}` lacks the columns {missing}"


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
