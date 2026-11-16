import os
from collections.abc import Generator
from pathlib import Path

from pulse_frame.platform.sandbox import apply_loopback_sandbox

SESSION_SANDBOX = apply_loopback_sandbox()

import cv2  # noqa: E402
import numpy as np  # noqa: E402
import pytest  # noqa: E402
from numpy.typing import NDArray  # noqa: E402

from pulse_frame.vision.model import ensure_model  # noqa: E402
from tests import database  # noqa: E402

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


@pytest.fixture(autouse=True)
def no_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(database.URL_VARIABLE, raising=False)


@pytest.fixture(scope="session")
def store_database() -> Generator[str]:
    server = database.server_url()
    with database.run_lock(server):
        url = database.recreate_database(server, database.TEST_DATABASE)
        database.apply_migrations(url)
        yield url
        database.drop_database(server, database.TEST_DATABASE)


@pytest.fixture
def store_url(store_database: str, monkeypatch: pytest.MonkeyPatch) -> str:
    database.empty_tables(store_database)
    monkeypatch.setenv(database.URL_VARIABLE, store_database)
    return store_database


@pytest.fixture
def unmigrated_store(store_url: str) -> Generator[str]:
    database.hide_store(store_url)
    yield store_url
    database.restore_store(store_url)


@pytest.fixture
def read_only_session(store_url: str) -> Generator[int]:
    session_id = database.seed_session(store_url)
    database.make_read_only(store_url)
    yield session_id
    database.make_writable(store_url)


@pytest.fixture(scope="module")
def astronaut_rgb() -> NDArray[np.uint8]:
    rgb = load_rgb(FIXTURES / "astronaut.jpg")
    rgb.setflags(write=False)
    return rgb
