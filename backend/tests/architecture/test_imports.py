from pathlib import Path

from tests.architecture.allowed_imports import PACKAGES
from tests.architecture.import_check import DATA_MODULE, import_violations

REPO = Path(__file__).resolve().parents[3]
SOURCE_PACKAGE = REPO / "backend" / "src" / "pulse_frame"


def test_real_source_tree_follows_the_import_tables() -> None:
    violations = import_violations(SOURCE_PACKAGE, REPO)
    assert violations == [], "\n".join(violation.message for violation in violations)


def test_every_source_package_is_in_the_table() -> None:
    folders = {
        path.name
        for path in SOURCE_PACKAGE.iterdir()
        if path.is_dir() and path.name != "__pycache__"
    }
    assert folders == set(PACKAGES), (
        f"the packages under backend/src/pulse_frame are {sorted(folders)}, "
        f"but `PACKAGES` lists {sorted(PACKAGES)}. Make `PACKAGES` and the "
        f"`ALLOWED_IMPORTS` rows in {DATA_MODULE} match the folders, "
        "or move the stray folder's modules into an existing package."
    )
