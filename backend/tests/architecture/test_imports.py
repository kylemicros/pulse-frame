import ast
from pathlib import Path

import pytest

from tests.architecture.allowed_imports import PACKAGES
from tests.architecture.import_check import DATA_MODULE, import_violations

REPO = Path(__file__).resolve().parents[3]
SOURCE_PACKAGE = REPO / "backend" / "src" / "pulse_frame"


def psycopg_importers(package_root: Path) -> list[str]:
    importers = []
    for path in sorted(package_root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                names = [node.module or ""]
            else:
                continue
            if any(name.split(".")[0] == "psycopg" for name in names):
                importers.append(path.relative_to(package_root).as_posix())
    return importers


STORE_WRITERS = ("tools/capture.py", "tools/replay.py")
STORE_MODULE = "pulse_frame.store.recording"
RECORDING_MODULE = "store/recording.py"


def imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            names.add(node.module or "")
    return names


def test_the_recording_module_lives_in_the_store_package() -> None:
    assert (SOURCE_PACKAGE / RECORDING_MODULE).is_file(), (
        f"backend/src/pulse_frame/{RECORDING_MODULE} does not exist"
    )


@pytest.mark.parametrize("module", STORE_WRITERS)
def test_capture_and_replay_reach_the_database_only_through_the_store(
    module: str,
) -> None:
    path = SOURCE_PACKAGE / module
    assert path.is_file(), f"backend/src/pulse_frame/{module} does not exist"
    names = imported_modules(path)
    assert STORE_MODULE in names, f"{module} does not import {STORE_MODULE}"
    direct = sorted(name for name in names if name.split(".")[0] == "psycopg")
    assert direct == [], f"{module} imports the database driver directly: {direct}"


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


def test_only_the_store_package_imports_psycopg_in_the_real_source() -> None:
    importers = psycopg_importers(SOURCE_PACKAGE)
    assert importers, "no module under backend/src/pulse_frame imports psycopg"
    outside = [path for path in importers if not path.startswith("store/")]
    assert outside == [], f"psycopg is imported outside the store package: {outside}"
