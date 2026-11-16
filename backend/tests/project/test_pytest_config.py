import os
import subprocess
import sys
from pathlib import Path

PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"

PLANTED_TEST = """import warnings


def test_warns() -> None:
    warnings.warn("x", DeprecationWarning, stacklevel=1)
"""


def test_runtime_deprecation_warning_fails_the_run(tmp_path: Path) -> None:
    planted = tmp_path / "test_planted.py"
    planted.write_text(PLANTED_TEST, encoding="utf-8")
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in {"PYTEST_ADDOPTS", "PYTHONWARNINGS"}
    }
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-c",
            str(PYPROJECT),
            "--rootdir",
            str(tmp_path),
            "-p",
            "no:cacheprovider",
            "-q",
            str(planted),
        ],
        capture_output=True,
        text=True,
        check=False,
        cwd=tmp_path,
        env=env,
    )
    assert result.returncode == 1
    assert "1 failed" in result.stdout
    assert "DeprecationWarning: x" in result.stdout
