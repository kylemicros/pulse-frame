import time
from pathlib import Path

import pytest
from mediapipe.tasks.python.vision import FaceLandmarker

from pulse_frame.vision.errors import VisionError
from pulse_frame.vision.landmarks import FaceTracker
from tests.vision.support import assert_coded

SHOWN_MODEL = "backend/models/face_landmarker.task"
FETCH_COMMAND = "uv run python -m pulse_frame.vision.model"
LINUX_MISSING = "libEGL.so.1: cannot open shared object file: No such file or directory"
LINUX_DENIED = "libEGL.so.1: cannot open shared object file: Permission denied"
MAC_MISSING = (
    "dlopen(/abs/path/libfoo.dylib, 0x0001): Library not loaded: @rpath/libbar.dylib"
)
MAC_SPACED = (
    "dlopen(/x/a.dylib, 0x0001): Library not loaded:"
    " /Users/x/Personal Projects/lib/libbar.dylib"
)
NO_MATCH_LIMIT_SECONDS = 0.5


def load_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, error: Exception
) -> VisionError:
    def fail(options: object) -> object:
        raise error

    monkeypatch.setattr(FaceLandmarker, "create_from_options", fail)
    with pytest.raises(VisionError) as raised:
        FaceTracker(tmp_path / "face_landmarker.task")
    return raised.value


def test_unopenable_linux_system_library_is_named_with_an_install_action(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    error = OSError(LINUX_MISSING)

    failure = load_failure(monkeypatch, tmp_path, error)

    assert_coded(failure, "MODEL_LOAD_FAILED")
    assert failure.__cause__ is error
    assert "could not open the system library libEGL.so.1" in failure.message
    assert "missing" not in failure.message.lower()
    assert "libEGL.so.1" in failure.action
    assert "install" in failure.action.lower()
    assert "delete" not in failure.action.lower()
    assert SHOWN_MODEL not in failure.action


def test_linux_library_denied_permission_is_named_without_calling_it_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    error = OSError(LINUX_DENIED)

    failure = load_failure(monkeypatch, tmp_path, error)

    assert_coded(failure, "MODEL_LOAD_FAILED")
    assert failure.__cause__ is error
    assert "could not open the system library libEGL.so.1" in failure.message
    assert "missing" not in failure.message.lower()
    assert "libEGL.so.1" in failure.action
    action = failure.action.lower()
    assert "install" in action or "repair" in action
    assert "delete" not in action
    assert SHOWN_MODEL not in failure.action


def test_unopenable_macos_library_is_named_without_any_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    error = OSError(MAC_MISSING)

    failure = load_failure(monkeypatch, tmp_path, error)

    assert_coded(failure, "MODEL_LOAD_FAILED")
    assert failure.__cause__ is error
    assert "could not open the system library libbar.dylib" in failure.message
    assert "missing" not in failure.message.lower()
    text = str(failure)
    assert "/abs/path" not in text
    assert "@rpath" not in text
    assert "install" in failure.action.lower()
    assert "delete" not in failure.action.lower()


def test_macos_library_path_with_a_space_is_named_without_any_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    error = OSError(MAC_SPACED)

    failure = load_failure(monkeypatch, tmp_path, error)

    assert_coded(failure, "MODEL_LOAD_FAILED")
    assert failure.__cause__ is error
    assert "could not open the system library libbar.dylib" in failure.message
    text = str(failure)
    assert "Personal Projects" not in text
    assert "/Users" not in text
    assert "install" in failure.action.lower()
    assert "delete" not in failure.action.lower()


@pytest.mark.parametrize(
    "text",
    [".so.1" * 8000, "a" * 40000],
    ids=["repeated_so_suffix", "plain_letters"],
)
def test_long_unmatched_error_builds_its_failure_quickly(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, text: str
) -> None:
    error = OSError(text)

    started = time.perf_counter()
    failure = load_failure(monkeypatch, tmp_path, error)
    elapsed = time.perf_counter() - started

    assert elapsed < NO_MATCH_LIMIT_SECONDS
    assert_coded(failure, "MODEL_LOAD_FAILED")
    assert failure.action.startswith(f"Delete {SHOWN_MODEL}")


@pytest.mark.parametrize(
    "error",
    [
        OSError("Unable to open file at /abs/path/face_landmarker.task"),
        OSError(),
        RuntimeError("Failed to parse the model flatbuffer"),
    ],
    ids=["oserror_open_file", "oserror_empty", "runtimeerror_corrupt"],
)
def test_other_load_errors_keep_the_delete_then_fetch_action(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, error: Exception
) -> None:
    failure = load_failure(monkeypatch, tmp_path, error)

    assert_coded(failure, "MODEL_LOAD_FAILED")
    assert failure.__cause__ is error
    assert f"({type(error).__name__})" in failure.message
    assert failure.action.startswith(f"Delete {SHOWN_MODEL}")
    assert FETCH_COMMAND in failure.action
    assert "/abs/path" not in str(failure)
