import shutil
import stat
from collections.abc import Callable, Iterator
from pathlib import Path

import numpy as np
import pytest
from mediapipe.tasks.python.vision import FaceLandmarker
from numpy.typing import NDArray

from pulse_frame.vision.errors import VisionError
from pulse_frame.vision.landmarks import FaceLandmarks, FaceTracker
from tests.frames import FrameClock
from tests.vision.faces import crop_above_brows, detect_face
from tests.vision.support import assert_coded

FACE_CENTRE_X_RANGE = (0.3, 0.6)
FACE_CENTRE_Y_RANGE = (0.1, 0.4)
WIDE_PADDING_PX = 128
TIMESTAMP_LIMIT_MS = (2**63 - 1) // 1000 + 1
ARRAY_STAMP_VALUE = 987654321
SHOWN_MODEL = "backend/models/face_landmarker.task"
NO_ACCESS = 0
READ_WRITE = stat.S_IRUSR | stat.S_IWUSR


@pytest.fixture(scope="module")
def tracker(face_model: Path) -> Iterator[FaceTracker]:
    with FaceTracker(face_model) as shared:
        yield shared


@pytest.fixture(scope="module")
def clock() -> FrameClock:
    return FrameClock()


@pytest.fixture
def first_detection_raises(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    original: Callable[..., object] = FaceLandmarker.detect_for_video
    calls: list[int] = []

    def fail_first(
        landmarker: FaceLandmarker, image: object, timestamp_ms: int
    ) -> object:
        calls.append(timestamp_ms)
        if len(calls) == 1:
            raise RuntimeError("calculator graph failed")
        return original(landmarker, image, timestamp_ms)

    monkeypatch.setattr(FaceLandmarker, "detect_for_video", fail_first)
    return calls


@pytest.fixture(params=["unreadable_file", "directory"])
def unloadable_model(
    request: pytest.FixtureRequest, tmp_path: Path, face_model: Path
) -> Iterator[Path]:
    path = tmp_path / "models" / "face_landmarker.task"
    path.parent.mkdir()
    if request.param == "directory":
        path.mkdir()
        yield path
        return
    shutil.copyfile(face_model, path)
    path.chmod(NO_ACCESS)
    yield path
    path.chmod(READ_WRITE)


def test_detect_finds_the_face_in_the_fixture_as_normalised_points(
    tracker: FaceTracker, clock: FrameClock, astronaut_rgb: NDArray[np.uint8]
) -> None:
    face = tracker.detect(astronaut_rgb, clock.next_ms())

    assert isinstance(face, FaceLandmarks)
    assert face.points.dtype == np.float64
    assert face.points.ndim == 2
    assert face.points.shape[0] >= 468
    assert face.points.shape[1] == 2
    assert np.all((face.points >= 0.0) & (face.points <= 1.0))
    centre_x, centre_y = face.points.mean(axis=0)
    assert FACE_CENTRE_X_RANGE[0] < centre_x < FACE_CENTRE_X_RANGE[1]
    assert FACE_CENTRE_Y_RANGE[0] < centre_y < FACE_CENTRE_Y_RANGE[1]


def test_face_carries_the_frame_size_and_every_point_inside_the_frame(
    face_model: Path, astronaut_rgb: NDArray[np.uint8]
) -> None:
    wide = np.pad(astronaut_rgb, ((0, 0), (0, WIDE_PADDING_PX), (0, 0)))

    with FaceTracker(face_model) as fresh:
        face = detect_face(fresh, wide, 0)

    assert face.width == astronaut_rgb.shape[1] + WIDE_PADDING_PX
    assert face.height == astronaut_rgb.shape[0]
    assert isinstance(face.width, int)
    assert isinstance(face.height, int)
    assert face.in_frame.dtype == np.bool_
    assert face.in_frame.shape == (face.points.shape[0],)
    assert bool(np.all(face.in_frame))


def test_points_beyond_the_top_edge_are_marked_outside_and_clipped(
    face_model: Path, astronaut_rgb: NDArray[np.uint8]
) -> None:
    with FaceTracker(face_model) as first:
        cropped = crop_above_brows(astronaut_rgb, detect_face(first, astronaut_rgb, 0))
    with FaceTracker(face_model) as fresh:
        face = detect_face(fresh, cropped, 0)

    assert face.height == cropped.shape[0]
    assert face.width == cropped.shape[1]
    assert not bool(np.all(face.in_frame))
    assert bool(np.any(face.in_frame))
    assert np.all((face.points >= 0.0) & (face.points <= 1.0))
    assert np.all(face.points[~face.in_frame, 1] == 0.0)


@pytest.mark.parametrize("level", [0, 128, 255], ids=["black", "grey", "white"])
def test_blank_image_gives_none(
    tracker: FaceTracker, clock: FrameClock, level: int
) -> None:
    blank = np.full((256, 256, 3), level, dtype=np.uint8)

    assert tracker.detect(blank, clock.next_ms()) is None


@pytest.mark.parametrize("second_ms", [500, 499, 0], ids=["repeat", "older", "zero"])
@pytest.mark.parametrize("first_has_face", [True, False])
def test_repeated_or_older_timestamp_raises_bad_timestamp(
    face_model: Path,
    astronaut_rgb: NDArray[np.uint8],
    second_ms: int,
    first_has_face: bool,
) -> None:
    first = astronaut_rgb if first_has_face else np.zeros_like(astronaut_rgb)
    with FaceTracker(face_model) as fresh:
        fresh.detect(first, 500)

        with pytest.raises(VisionError) as raised:
            fresh.detect(astronaut_rgb, second_ms)

    assert_coded(raised.value, "BAD_TIMESTAMP")


def test_stream_continues_after_a_rejected_timestamp(
    face_model: Path, astronaut_rgb: NDArray[np.uint8]
) -> None:
    with FaceTracker(face_model) as fresh:
        fresh.detect(astronaut_rgb, 500)
        with pytest.raises(VisionError):
            fresh.detect(astronaut_rgb, 500)

        face = fresh.detect(astronaut_rgb, 533)

    assert isinstance(face, FaceLandmarks)


@pytest.mark.parametrize(
    ("bad_timestamp", "later_ms"),
    [(150.5, 100), (100.0, 101), (True, 1), (-1, 0), (2**64, 100)],
    ids=["fraction", "whole_float", "bool", "negative", "two_to_the_64"],
)
def test_timestamp_that_is_not_an_int_in_range_raises_bad_timestamp_and_is_not_kept(
    face_model: Path,
    astronaut_rgb: NDArray[np.uint8],
    bad_timestamp: object,
    later_ms: int,
) -> None:
    with FaceTracker(face_model) as fresh:
        with pytest.raises(VisionError) as raised:
            fresh.detect(astronaut_rgb, bad_timestamp)

        face = fresh.detect(astronaut_rgb, later_ms)

    assert_coded(raised.value, "BAD_TIMESTAMP")
    assert isinstance(face, FaceLandmarks)


def test_out_of_range_timestamp_after_a_good_frame_raises_bad_timestamp(
    face_model: Path, astronaut_rgb: NDArray[np.uint8]
) -> None:
    with FaceTracker(face_model) as fresh:
        fresh.detect(astronaut_rgb, 100)
        with pytest.raises(VisionError) as raised:
            fresh.detect(astronaut_rgb, 2**64)

        face = fresh.detect(astronaut_rgb, 133)

    assert_coded(raised.value, "BAD_TIMESTAMP")
    assert isinstance(face, FaceLandmarks)


@pytest.mark.parametrize(
    ("dtype", "shape"),
    [
        (np.float32, (256, 256, 3)),
        (np.float64, (256, 256, 3)),
        (np.uint16, (256, 256, 3)),
        (np.int8, (256, 256, 3)),
        (np.uint8, (256, 256)),
        (np.uint8, (256, 256, 1)),
        (np.uint8, (256, 256, 4)),
        (np.uint8, (1, 256, 256, 3)),
        (np.uint8, (0, 0, 3)),
        (np.uint8, (0, 256, 3)),
        (np.uint8, (256, 0, 3)),
    ],
    ids=[
        "float32",
        "float64",
        "uint16",
        "int8",
        "grey_2d",
        "one_channel",
        "rgba",
        "batch",
        "empty",
        "no_rows",
        "no_columns",
    ],
)
def test_wrong_dtype_or_shape_raises_bad_frame(
    tracker: FaceTracker,
    clock: FrameClock,
    dtype: type[np.generic],
    shape: tuple[int, ...],
) -> None:
    frame = np.full(shape, 100, dtype=dtype)

    with pytest.raises(VisionError) as raised:
        tracker.detect(frame, clock.next_ms())

    assert_coded(raised.value, "BAD_FRAME")


@pytest.mark.parametrize("kind", ["nested_list", "bytes", "none"])
def test_frame_that_is_not_a_numpy_array_raises_bad_frame(
    tracker: FaceTracker,
    clock: FrameClock,
    astronaut_rgb: NDArray[np.uint8],
    kind: str,
) -> None:
    frames: dict[str, object] = {
        "nested_list": astronaut_rgb.tolist(),
        "bytes": astronaut_rgb.tobytes(),
        "none": None,
    }

    with pytest.raises(VisionError) as raised:
        tracker.detect(frames[kind], clock.next_ms())

    assert_coded(raised.value, "BAD_FRAME")


def test_detect_after_close_raises_tracker_closed(
    face_model: Path, astronaut_rgb: NDArray[np.uint8]
) -> None:
    closed = FaceTracker(face_model)
    closed.detect(astronaut_rgb, 0)
    closed.close()

    with pytest.raises(VisionError) as raised:
        closed.detect(astronaut_rgb, 33)

    assert_coded(raised.value, "TRACKER_CLOSED")


def test_detect_after_leaving_the_context_raises_tracker_closed(
    face_model: Path, astronaut_rgb: NDArray[np.uint8]
) -> None:
    with FaceTracker(face_model) as finished:
        finished.detect(astronaut_rgb, 0)

    with pytest.raises(VisionError) as raised:
        finished.detect(astronaut_rgb, 33)

    assert_coded(raised.value, "TRACKER_CLOSED")


def test_model_file_that_is_not_a_model_raises_model_load_failed(
    tmp_path: Path,
) -> None:
    junk = tmp_path / "face_landmarker.task"
    junk.write_bytes(b"not a model " * 100)

    with pytest.raises(VisionError) as raised:
        FaceTracker(junk)

    assert_coded(raised.value, "MODEL_LOAD_FAILED")


def test_timestamp_below_the_limit_is_accepted_and_the_limit_is_bad_timestamp(
    face_model: Path, astronaut_rgb: NDArray[np.uint8]
) -> None:
    with FaceTracker(face_model) as fresh:
        fresh.detect(astronaut_rgb, 100)
        with pytest.raises(VisionError) as raised:
            fresh.detect(astronaut_rgb, TIMESTAMP_LIMIT_MS)

        face = fresh.detect(astronaut_rgb, TIMESTAMP_LIMIT_MS - 1)

    assert_coded(raised.value, "BAD_TIMESTAMP")
    assert isinstance(face, FaceLandmarks)


def test_bad_timestamp_message_for_an_array_names_its_type_but_not_its_values(
    tracker: FaceTracker, astronaut_rgb: NDArray[np.uint8]
) -> None:
    stamp = np.array([ARRAY_STAMP_VALUE])

    with pytest.raises(VisionError) as raised:
        tracker.detect(astronaut_rgb, stamp)

    assert_coded(raised.value, "BAD_TIMESTAMP")
    assert "ndarray" in raised.value.message
    assert str(ARRAY_STAMP_VALUE) not in str(raised.value)


def test_mediapipe_error_is_detection_failed_and_the_same_timestamp_is_accepted_next(
    face_model: Path,
    astronaut_rgb: NDArray[np.uint8],
    first_detection_raises: list[int],
) -> None:
    with FaceTracker(face_model) as fresh:
        with pytest.raises(VisionError) as raised:
            fresh.detect(astronaut_rgb, 500)

        face = fresh.detect(astronaut_rgb, 500)

    assert_coded(raised.value, "DETECTION_FAILED")
    assert isinstance(raised.value.__cause__, RuntimeError)
    assert isinstance(face, FaceLandmarks)
    assert first_detection_raises == [500, 500]


def test_detection_failed_message_says_mediapipe_raised_not_that_no_face_was_found(
    face_model: Path,
    astronaut_rgb: NDArray[np.uint8],
    first_detection_raises: list[int],
) -> None:
    with FaceTracker(face_model) as fresh, pytest.raises(VisionError) as raised:
        fresh.detect(astronaut_rgb, 500)

    message = raised.value.message
    assert "MediaPipe" in message
    assert "raised" in message
    assert "RuntimeError" in message
    assert "find" not in message.lower()
    assert "no face" not in message.lower()


def test_model_that_cannot_be_read_or_is_a_directory_is_model_load_failed(
    unloadable_model: Path,
) -> None:
    with pytest.raises(VisionError) as raised:
        FaceTracker(unloadable_model)

    assert_coded(raised.value, "MODEL_LOAD_FAILED")
    text = f"{raised.value.message} {raised.value.action}"
    assert SHOWN_MODEL in text
    assert str(unloadable_model.parent) not in text


@pytest.mark.parametrize(
    "bad_timestamp", [-1, 2**64], ids=["negative", "two_to_the_64"]
)
def test_bad_timestamp_message_for_an_out_of_range_int_does_not_repeat_the_value(
    tracker: FaceTracker, astronaut_rgb: NDArray[np.uint8], bad_timestamp: int
) -> None:
    with pytest.raises(VisionError) as raised:
        tracker.detect(astronaut_rgb, bad_timestamp)

    assert_coded(raised.value, "BAD_TIMESTAMP")
    assert str(bad_timestamp) not in raised.value.message
    assert str(bad_timestamp) not in str(raised.value)
