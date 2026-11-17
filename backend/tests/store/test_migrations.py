import re

from tests.database import MIGRATIONS, REPO, migration_files

MIGRATION_NAME = re.compile(r"[0-9]{14}_[a-z0-9_]+\.sql")
DATA_STATEMENTS = re.compile(
    r"\bINSERT\b|\bCOPY\b|\\copy\b|\bVALUES\b|Dumped from database version",
    re.IGNORECASE,
)


def test_migrations_folder_holds_only_cli_named_migrations() -> None:
    entries = sorted(MIGRATIONS.iterdir()) if MIGRATIONS.is_dir() else []
    assert entries, "supabase/migrations holds no migration"
    odd = [
        entry.relative_to(REPO).as_posix()
        for entry in entries
        if not entry.is_file() or not MIGRATION_NAME.fullmatch(entry.name)
    ]
    assert odd == [], f"entries not named <14 digits>_<lowercase name>.sql: {odd}"


def test_migrations_hold_schema_only() -> None:
    files = migration_files()
    assert files, "supabase/migrations holds no migration"
    carrying = [
        path.relative_to(REPO).as_posix()
        for path in files
        if DATA_STATEMENTS.search(path.read_text(encoding="utf-8"))
    ]
    assert carrying == [], f"migrations carrying data or a dump header: {carrying}"


CREATED = re.compile(r"\bcreate\s+table\s+private\.(\w+)", re.IGNORECASE)
RLS_ENABLED = re.compile(
    r"\balter\s+table\s+private\.(\w+)\s+enable\s+row\s+level\s+security",
    re.IGNORECASE,
)
REVOKE = re.compile(r"\brevoke\b", re.IGNORECASE)


def test_later_migrations_enable_row_security_only_on_tables_they_create() -> None:
    later = migration_files()[1:]
    restated = sorted(
        f"{path.name}: {table}"
        for path in later
        for table in set(RLS_ENABLED.findall(path.read_text(encoding="utf-8")))
        - set(CREATED.findall(path.read_text(encoding="utf-8")))
    )
    assert restated == [], f"row level security restated on existing tables: {restated}"


def test_later_migrations_revoke_only_when_they_create_a_table() -> None:
    later = migration_files()[1:]
    restated = sorted(
        path.name
        for path in later
        if REVOKE.search(path.read_text(encoding="utf-8"))
        and not CREATED.search(path.read_text(encoding="utf-8"))
    )
    assert restated == [], f"revokes restated without a new table: {restated}"
