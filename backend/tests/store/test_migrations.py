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
