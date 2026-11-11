from dataclasses import asdict
from pathlib import Path

import numpy as np
import pytest
from numpy.typing import NDArray

from pulse_frame.platform.sandbox import FAILED_ACTION, sandbox_status
from pulse_frame.vision.landmarks import FaceTracker
from tests.platform.sandboxed import (
    LIBRARY_LOAD_REFUSAL,
    REFUSAL_TEXT,
    outbound_errnos,
)
from tests.platform.support import (
    ON_MACOS,
    assert_sandbox_status_for_this_platform,
    missing_symbol_message,
    refused_message,
    run_probe,
)
from tests.vision.faces import NOSE_TIP, detect_face

LANDMARK_COUNT = 478
UNSANDBOXED_NOSE_TIP_PX = (111.46, 64.69)
UNSANDBOXED_FACE_BOX_PX = (89.86, 135.05, 35.47, 87.99)
BASELINE_TOLERANCE_PX = 1.0
SAME_PROCESS_TOLERANCE = 1e-6
SANDBOX_ERROR = "pulse_frame.platform.errors.SandboxError"
OS_ERROR = "builtins.OSError"
ATTRIBUTE_ERROR = "builtins.AttributeError"
LIBRARY_FAILURES = [
    pytest.param(
        "load-fails",
        f"libSystem could not be loaded: {LIBRARY_LOAD_REFUSAL}.",
        OS_ERROR,
        id="load-fails",
    ),
    pytest.param(
        "init-missing",
        missing_symbol_message("sandbox_init"),
        ATTRIBUTE_ERROR,
        id="init-missing",
    ),
    pytest.param(
        "free-missing",
        missing_symbol_message("sandbox_free_error"),
        ATTRIBUTE_ERROR,
        id="free-missing",
    ),
    pytest.param(
        "init-fails-no-text",
        refused_message("macOS gave no error text"),
        None,
        id="init-fails-no-text",
    ),
    pytest.param(
        "init-fails-empty-text",
        refused_message("macOS gave an empty error text"),
        None,
        id="init-fails-empty-text",
    ),
    pytest.param(
        "init-fails-with-text",
        refused_message("the test library refused this profile"),
        None,
        id="init-fails-with-text",
    ),
]
ERROR_TEXT_HANDLING = [
    pytest.param("init-fails-no-text", ["load", "sandbox_init"], [], id="null"),
    pytest.param(
        "init-fails-empty-text",
        ["load", "sandbox_init", "sandbox_free_error"],
        [""],
        id="empty",
    ),
    pytest.param(
        "init-fails-with-text",
        ["load", "sandbox_init", "sandbox_free_error"],
        [REFUSAL_TEXT.decode()],
        id="multi-line",
    ),
]


def face_box_px(pixels: NDArray[np.float64]) -> list[float]:
    return [
        float(pixels[:, 0].min()),
        float(pixels[:, 0].max()),
        float(pixels[:, 1].min()),
        float(pixels[:, 1].max()),
    ]


def test_applying_the_sandbox_twice_returns_the_same_status_both_times(
    tmp_path: Path,
) -> None:
    probe = run_probe("apply", tmp_path)

    assert probe.returncode == 0, probe.stderr[-2000:]
    assert_sandbox_status_for_this_platform(probe.record["first"])
    assert probe.record["second"] == probe.record["first"]
    assert probe.record["status"] == probe.record["first"]


def test_outbound_connect_to_a_public_address_fails_with_eperm_inside_the_sandbox(
    tmp_path: Path,
) -> None:
    probe = run_probe("apply", tmp_path)

    assert probe.returncode == 0, probe.stderr[-2000:]
    assert_sandbox_status_for_this_platform(probe.record["status"])
    if ON_MACOS:
        assert probe.record["outbound"] == ["EPERM", "EPERM"]
    else:
        assert probe.record["outbound"] == []


def test_sandbox_off_macos_is_a_coded_no_op_that_names_the_platform(
    tmp_path: Path,
) -> None:
    probe = run_probe("linux", tmp_path)

    assert probe.returncode == 0, probe.stderr[-2000:]
    returned = probe.record["returned"]
    assert returned["applied"] is False
    assert returned["code"] == "SANDBOX_UNSUPPORTED"
    assert "macOS" in returned["reason"]
    assert probe.record["status"] == returned


@pytest.mark.parametrize(("mode", "message", "cause_type"), LIBRARY_FAILURES)
def test_libsystem_failure_raises_sandbox_failed_with_a_plain_message_and_no_status(
    tmp_path: Path, mode: str, message: str, cause_type: str | None
) -> None:
    probe = run_probe("broken-library", tmp_path, mode)

    assert probe.returncode == 1
    assert probe.record["error_type"] == SANDBOX_ERROR
    assert probe.record["code"] == "SANDBOX_FAILED"
    assert probe.record["message"] == message
    assert probe.record["action"] == FAILED_ACTION
    assert probe.record["cause_type"] == cause_type
    assert probe.record["status_after"] is None
    assert probe.record["library_calls"][0] == "load"


@pytest.mark.parametrize(("mode", "library_calls", "freed_texts"), ERROR_TEXT_HANDLING)
def test_macos_error_text_is_freed_exactly_once_and_a_null_text_is_not_freed(
    tmp_path: Path, mode: str, library_calls: list[str], freed_texts: list[str]
) -> None:
    probe = run_probe("broken-library", tmp_path, mode)

    assert probe.returncode == 1
    assert probe.record["code"] == "SANDBOX_FAILED"
    assert probe.record["library_calls"] == library_calls
    assert probe.record["freed_texts"] == freed_texts


@pytest.mark.parametrize("platform", ["native", "linux"])
def test_applying_the_sandbox_in_a_fresh_process_emits_no_log_record(
    tmp_path: Path, platform: str
) -> None:
    probe = run_probe("log-records", tmp_path, platform)

    assert probe.returncode == 0, probe.stderr[-2000:]
    if platform == "native":
        assert_sandbox_status_for_this_platform(probe.record["status"])
    else:
        assert probe.record["status"]["code"] == "SANDBOX_UNSUPPORTED"
    assert probe.record["records"] == []


def test_loopback_server_accepts_connections_inside_the_sandbox(
    tmp_path: Path,
) -> None:
    probe = run_probe("loopback-and-detect", tmp_path)

    assert probe.returncode == 0, probe.stderr[-2000:]
    assert_sandbox_status_for_this_platform(probe.record["status"])
    assert probe.record["echo_v4"] == "pulse"
    assert probe.record["echo_v6"] == "pulse"


def test_face_detection_inside_the_sandbox_matches_this_process_and_the_baseline(
    tmp_path: Path, face_model: Path, astronaut_rgb: NDArray[np.uint8]
) -> None:
    probe = run_probe("loopback-and-detect", tmp_path)
    with FaceTracker(face_model) as tracker:
        here = detect_face(tracker, astronaut_rgb, 0)

    assert probe.returncode == 0, probe.stderr[-2000:]
    assert_sandbox_status_for_this_platform(probe.record["status"])
    assert probe.record["points"] is not None, "No face found inside the sandbox."
    sandboxed = np.array(probe.record["points"], dtype=np.float64)
    assert sandboxed.shape == (LANDMARK_COUNT, 2)
    np.testing.assert_allclose(sandboxed, here.points, atol=SAME_PROCESS_TOLERANCE)
    height, width = astronaut_rgb.shape[:2]
    pixels = sandboxed * np.array([width, height], dtype=np.float64)
    np.testing.assert_allclose(
        pixels[NOSE_TIP], UNSANDBOXED_NOSE_TIP_PX, atol=BASELINE_TOLERANCE_PX
    )
    np.testing.assert_allclose(
        face_box_px(pixels), UNSANDBOXED_FACE_BOX_PX, atol=BASELINE_TOLERANCE_PX
    )


def test_this_test_session_is_sandboxed_before_any_test_runs() -> None:
    status = sandbox_status()

    assert status is not None
    assert_sandbox_status_for_this_platform(asdict(status))
    if ON_MACOS:
        assert outbound_errnos() == ["EPERM", "EPERM"]


def test_importing_the_test_conftest_applies_the_sandbox_before_mediapipe(
    tmp_path: Path,
) -> None:
    probe = run_probe("session", tmp_path)

    assert probe.returncode == 0, probe.stderr[-2000:]
    assert_sandbox_status_for_this_platform(probe.record["status"])
    assert probe.record["mediapipe_loaded"] is False
