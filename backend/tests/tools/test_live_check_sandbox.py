from pathlib import Path

import pytest

from pulse_frame.platform.sandbox import FAILED_ACTION, SandboxStatus
from tests.platform.sandboxed import TRACKED_FRAMES
from tests.platform.support import (
    ON_MACOS,
    after_sandbox_notice,
    assert_sandbox_status_for_this_platform,
    missing_symbol_message,
    refused_message,
    run_probe,
    sandbox_lines,
)

CODE_PREFIXES = ("SANDBOX_", "CAMERA_")


def coded_lines(stderr: str) -> list[str]:
    return [line for line in stderr.splitlines() if line.startswith(CODE_PREFIXES)]


LIBRARY_FAILURES = [
    pytest.param(
        "init-fails-with-text",
        refused_message("the test library refused this profile"),
        id="init-fails-with-text",
    ),
    pytest.param(
        "init-missing",
        missing_symbol_message("sandbox_init"),
        id="init-missing",
    ),
]


def test_live_check_applies_the_sandbox_before_mediapipe_is_imported(
    tmp_path: Path,
) -> None:
    probe = run_probe("live-check", tmp_path)

    assert probe.returncode == 0, probe.stderr[-2000:]
    imports = probe.record["mediapipe_imports"]
    assert len(imports) == 1, f"mediapipe import was seen {len(imports)} times"
    status = imports[0]
    assert_sandbox_status_for_this_platform(status)
    assert probe.record["camera_opened"] == [0]
    assert "face=yes" in probe.stdout
    if ON_MACOS:
        assert sandbox_lines(probe.stderr) == []
    else:
        assert sandbox_lines(probe.stderr) == [
            f"SANDBOX_UNSUPPORTED: {status['reason']}"
        ]


def test_live_check_off_macos_prints_sandbox_unsupported_once_and_carries_on(
    tmp_path: Path,
) -> None:
    probe = run_probe("live-check-unsupported", tmp_path)

    assert probe.returncode == 0, probe.stderr[-2000:]
    unsupported = probe.record["unsupported"]
    assert unsupported["code"] == "SANDBOX_UNSUPPORTED"
    assert sandbox_lines(probe.stderr) == [
        f"SANDBOX_UNSUPPORTED: {unsupported['reason']}"
    ]
    assert probe.record["mediapipe_imports"] == [unsupported]
    assert probe.record["camera_opened"] == [0]
    assert "face=yes" in probe.stdout


@pytest.mark.parametrize(("mode", "message"), LIBRARY_FAILURES)
def test_live_check_stops_with_sandbox_failed_before_mediapipe_or_the_camera(
    tmp_path: Path, mode: str, message: str
) -> None:
    probe = run_probe("live-check-broken", tmp_path, mode)

    assert probe.returncode == 1
    assert probe.stderr == f"SANDBOX_FAILED: {message} {FAILED_ACTION}\n"
    assert probe.stdout == ""
    assert probe.record["mediapipe_imports"] == 0
    assert probe.record["camera_opened"] == []


@pytest.mark.parametrize(
    ("failure", "code", "reads"),
    [
        pytest.param("unavailable", "CAMERA_UNAVAILABLE", 0, id="unavailable"),
        pytest.param(
            "read-failed", "CAMERA_READ_FAILED", TRACKED_FRAMES, id="read-failed"
        ),
    ],
)
def test_live_check_unsupported_prints_the_notice_before_the_camera_error(
    tmp_path: Path, failure: str, code: str, reads: int
) -> None:
    probe = run_probe("live-check-camera-fails", tmp_path, failure)

    assert probe.returncode == 1, probe.stderr[-2000:]
    unsupported = probe.record["unsupported"]
    assert unsupported["code"] == "SANDBOX_UNSUPPORTED"
    assert_sandbox_status_for_this_platform(probe.record["underneath"])
    notice = f"SANDBOX_UNSUPPORTED: {unsupported['reason']}"
    assert probe.stderr.splitlines()[0] == notice
    coded = coded_lines(probe.stderr)
    assert len(coded) == 2, probe.stderr[-2000:]
    assert coded[0] == notice
    assert coded[1].startswith(f"{code}: ")
    rest = after_sandbox_notice(probe.stderr, SandboxStatus(**unsupported))
    assert coded_lines(rest) == coded[1:]
    assert rest.splitlines()[-1] == coded[1]
    assert probe.stdout == ""
    assert probe.record["camera_opened"] == [0]
    assert probe.record["reads"] == reads
    assert probe.record["released"] == 1
