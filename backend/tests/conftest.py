import os
from pathlib import Path

from pulse_frame.platform.sandbox import apply_loopback_sandbox

SESSION_SANDBOX = apply_loopback_sandbox()

import cv2  # noqa: E402
import numpy as np  # noqa: E402
import pytest  # noqa: E402
from numpy.typing import NDArray  # noqa: E402

from pulse_frame.vision.model import ensure_model  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"
UNSANDBOXED_ACTION = (
    "Run the backend tests on macOS, where the loopback-only sandbox applies;"
    " only GitHub Actions on Linux may run them unsandboxed."
)


def is_linux_ci() -> bool:
    return (
        os.environ.get("GITHUB_ACTIONS") == "true"
        and os.environ.get("RUNNER_OS") == "Linux"
    )


def pytest_configure() -> None:
    if not SESSION_SANDBOX.applied and not is_linux_ci():
        pytest.exit(
            f"{SESSION_SANDBOX.code}: {SESSION_SANDBOX.reason} {UNSANDBOXED_ACTION}",
            returncode=pytest.ExitCode.USAGE_ERROR,
        )


def pytest_report_header() -> str:
    return f"network sandbox: {SESSION_SANDBOX.code} ({SESSION_SANDBOX.reason})"


def load_rgb(path: Path) -> NDArray[np.uint8]:
    bgr = cv2.imread(str(path))
    assert bgr is not None, f"Could not read the test image {path}."
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)


@pytest.fixture(scope="session")
def face_model() -> Path:
    return ensure_model(download=False)


@pytest.fixture(scope="module")
def astronaut_rgb() -> NDArray[np.uint8]:
    rgb = load_rgb(FIXTURES / "astronaut.jpg")
    rgb.setflags(write=False)
    return rgb
