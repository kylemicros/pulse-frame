from pathlib import Path

import cv2
import numpy as np
import pytest
from numpy.typing import NDArray

from pulse_frame.platform.sandbox import apply_loopback_sandbox
from pulse_frame.vision.model import ensure_model

SESSION_SANDBOX = apply_loopback_sandbox()
FIXTURES = Path(__file__).parent / "fixtures"


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
