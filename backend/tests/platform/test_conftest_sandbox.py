import os
import sys
from pathlib import Path

import pytest

from tests.platform.support import run_probe

CI_KEYS = ("GITHUB_ACTIONS", "RUNNER_OS")
LINUX_CI = {"GITHUB_ACTIONS": "true", "RUNNER_OS": "Linux"}
FIRST_PARTY = {"pulse_frame", "tests"}
NATIVE_IMPORTS = {"cv2", "numpy"}
COLLECTED = "tests/platform/test_conftest_sandbox.py"
OUTSIDE_LINUX_CI = [
    pytest.param({}, id="not-in-ci"),
    pytest.param({"GITHUB_ACTIONS": "true", "RUNNER_OS": "macOS"}, id="ci-on-macos"),
    pytest.param(
        {"GITHUB_ACTIONS": "true", "RUNNER_OS": "Windows"}, id="ci-on-windows"
    ),
    pytest.param({"RUNNER_OS": "Linux"}, id="linux-runner-name-only"),
    pytest.param({"GITHUB_ACTIONS": "false", "RUNNER_OS": "Linux"}, id="actions-false"),
]


def environment_with(ci: dict[str, str]) -> dict[str, str]:
    env = {key: value for key, value in os.environ.items() if key not in CI_KEYS}
    env.update(ci)
    return env


def is_third_party(name: str) -> bool:
    return name not in sys.stdlib_module_names and name not in FIRST_PARTY


def test_conftest_applies_the_sandbox_before_any_third_party_import(
    tmp_path: Path,
) -> None:
    probe = run_probe("conftest-imports", tmp_path, env=environment_with(LINUX_CI))

    assert probe.returncode == 0, probe.stderr[-2000:]
    third_party = {
        name: status for name, status in probe.record["imports"] if is_third_party(name)
    }
    assert third_party.keys() >= NATIVE_IMPORTS, sorted(third_party)
    unsandboxed = sorted(name for name, status in third_party.items() if status is None)
    assert unsandboxed == [], f"Imported before the sandbox was applied: {unsandboxed}"


@pytest.mark.parametrize("ci", OUTSIDE_LINUX_CI)
def test_conftest_stops_the_session_when_the_sandbox_is_unsupported_outside_linux_ci(
    tmp_path: Path, ci: dict[str, str]
) -> None:
    probe = run_probe(
        "conftest-unsupported", tmp_path, COLLECTED, env=environment_with(ci)
    )

    assert probe.record["unsupported"]["code"] == "SANDBOX_UNSUPPORTED"
    assert probe.returncode == pytest.ExitCode.USAGE_ERROR, probe.stdout[-2000:]
    assert "SANDBOX_UNSUPPORTED" in probe.stdout + probe.stderr


def test_conftest_lets_github_actions_on_linux_run_with_the_sandbox_unsupported(
    tmp_path: Path,
) -> None:
    probe = run_probe(
        "conftest-unsupported", tmp_path, COLLECTED, env=environment_with(LINUX_CI)
    )

    assert probe.record["unsupported"]["code"] == "SANDBOX_UNSUPPORTED"
    assert probe.returncode == 0, probe.stdout[-2000:] + probe.stderr[-2000:]
