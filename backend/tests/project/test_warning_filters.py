import tomllib
from pathlib import Path

import pytest

PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"


def filter_entries(pyproject: Path) -> list[str]:
    with pyproject.open("rb") as handle:
        config = tomllib.load(handle)
    return list(config["tool"]["pytest"]["ini_options"]["filterwarnings"])


def unpinned_ignores(entries: list[str]) -> list[str]:
    bad = []
    for entry in entries:
        parts = entry.split(":")
        if parts[0] != "ignore":
            continue
        fields = [*parts[1:4], "", "", ""][:3]
        if len(parts) > 5 or not all(field.strip() for field in fields):
            bad.append(entry)
    return bad


def test_warnings_are_errors_first() -> None:
    assert filter_entries(PYPROJECT)[0] == "error"


def weakening_entries(entries: list[str]) -> list[str]:
    return [entry for entry in entries[1:] if not entry.startswith("ignore:")]


def test_every_entry_after_error_is_an_ignore() -> None:
    assert weakening_entries(filter_entries(PYPROJECT)) == []


@pytest.mark.parametrize(
    "entry",
    [
        "default::DeprecationWarning",
        "always::DeprecationWarning",
        "i::DeprecationWarning",
        "ign:x:DeprecationWarning",
        " ignore::DeprecationWarning",
        "::DeprecationWarning",
        "ignore",
    ],
)
def test_entry_that_is_not_an_ignore_is_flagged(tmp_path: Path, entry: str) -> None:
    copy = tmp_path / "pyproject.toml"
    original = PYPROJECT.read_text(encoding="utf-8")
    copy.write_text(
        original.replace('    "error",\n', f"    \"error\",\n    '{entry}',\n", 1),
        encoding="utf-8",
    )
    entries = filter_entries(copy)
    assert entry in entries
    assert weakening_entries(entries) == [entry]


def test_every_ignore_names_message_category_and_module() -> None:
    entries = filter_entries(PYPROJECT)
    assert any(entry.startswith("ignore:") for entry in entries)
    assert unpinned_ignores(entries) == []


@pytest.mark.parametrize(
    "entry",
    [
        "ignore::DeprecationWarning",
        "ignore:some message:DeprecationWarning",
        "ignore:some message::tests\\.stream\\.",
        "ignore::DeprecationWarning:tests\\.stream\\.",
        "ignore",
    ],
)
def test_unpinned_ignore_is_flagged(tmp_path: Path, entry: str) -> None:
    copy = tmp_path / "pyproject.toml"
    original = PYPROJECT.read_text(encoding="utf-8")
    copy.write_text(
        original.replace('    "error",\n', f"    \"error\",\n    '{entry}',\n", 1),
        encoding="utf-8",
    )
    entries = filter_entries(copy)
    assert entry in entries
    assert unpinned_ignores(entries) == [entry]
