from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Self

import mediapipe as mp
import numpy as np
from mediapipe.tasks.python import BaseOptions
from mediapipe.tasks.python.vision import (
    FaceLandmarker,
    FaceLandmarkerOptions,
    FaceLandmarkerResult,
    RunningMode,
)
from numpy.typing import NDArray

from pulse_frame.vision.errors import VisionError
from pulse_frame.vision.model import FETCH_COMMAND, SHOWN_PATH

RGB_CHANNELS = 3
FRAME_DIMENSIONS = 3
TIMESTAMP_LIMIT_MS = (2**63 - 1) // 1000 + 1
MEDIAPIPE_ERRORS = (RuntimeError, ValueError, OSError, IndexError)


@dataclass(frozen=True)
class FaceLandmarks:
    points: NDArray[np.float64]
    width: int
    height: int
    in_frame: NDArray[np.bool_]


class FaceTracker:
    def __init__(self, model: Path) -> None:
        self._landmarker: FaceLandmarker | None = open_landmarker(model)
        self._last_timestamp_ms: int | None = None

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        landmarker, self._landmarker = self._landmarker, None
        if landmarker is not None:
            landmarker.close()

    def detect(self, rgb: NDArray[np.uint8], timestamp_ms: int) -> FaceLandmarks | None:
        landmarker = self._open_landmarker()
        check_frame(rgb)
        check_timestamp_value(timestamp_ms)
        self._check_increasing(timestamp_ms)
        image = mp.Image(
            image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb)
        )
        result = run_detection(landmarker, image, timestamp_ms)
        self._last_timestamp_ms = timestamp_ms
        height, width = rgb.shape[:2]
        return first_face(result, width, height)

    def _open_landmarker(self) -> FaceLandmarker:
        if self._landmarker is None:
            raise VisionError(
                "TRACKER_CLOSED",
                "This face tracker was closed and cannot detect any more frames.",
                "Create a new FaceTracker for the next stream.",
            )
        return self._landmarker

    def _check_increasing(self, timestamp_ms: int) -> None:
        last = self._last_timestamp_ms
        if last is not None and timestamp_ms <= last:
            raise VisionError(
                "BAD_TIMESTAMP",
                f"Frame timestamp {timestamp_ms} ms is not after the previous"
                f" frame's {last} ms.",
                "Pass strictly increasing integer milliseconds, for example from"
                " time.monotonic(), and drop frames that repeat a timestamp.",
            )


def open_landmarker(model: Path) -> FaceLandmarker:
    options = FaceLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=str(model)),
        running_mode=RunningMode.VIDEO,
        num_faces=1,
    )
    try:
        return FaceLandmarker.create_from_options(options)
    except MEDIAPIPE_ERRORS as error:
        raise VisionError(
            "MODEL_LOAD_FAILED",
            f"MediaPipe could not load the face model ({type(error).__name__}).",
            f"Delete {SHOWN_PATH}, then run {FETCH_COMMAND} in backend/ to"
            " download it again.",
        ) from error


def run_detection(
    landmarker: FaceLandmarker, image: mp.Image, timestamp_ms: int
) -> FaceLandmarkerResult:
    try:
        return landmarker.detect_for_video(image, timestamp_ms)
    except MEDIAPIPE_ERRORS as error:
        raise VisionError(
            "DETECTION_FAILED",
            f"MediaPipe raised {type(error).__name__} while processing the frame"
            f" at {timestamp_ms} ms.",
            "Skip this frame and send the next one; if every frame fails, start a"
            " new stream.",
        ) from error


def check_frame(rgb: object) -> None:
    if not isinstance(rgb, np.ndarray):
        raise VisionError(
            "BAD_FRAME",
            f"A frame must be a numpy array, got {type(rgb).__name__}.",
            "Pass the frame as a uint8 numpy array of shape (height, width, 3).",
        )
    shape = rgb.shape
    if (
        rgb.dtype != np.uint8
        or len(shape) != FRAME_DIMENSIONS
        or shape[2] != RGB_CHANNELS
        or shape[0] == 0
        or shape[1] == 0
    ):
        raise VisionError(
            "BAD_FRAME",
            f"A frame must be a non-empty uint8 array of shape (height, width, 3),"
            f" got {rgb.dtype} with shape {shape}.",
            "Convert the frame to 8 bit RGB (cv2.cvtColor with COLOR_BGR2RGB for"
            " OpenCV frames) before passing it.",
        )


def check_timestamp_value(timestamp_ms: object) -> None:
    if (
        not isinstance(timestamp_ms, int)
        or isinstance(timestamp_ms, bool)
        or not 0 <= timestamp_ms < TIMESTAMP_LIMIT_MS
    ):
        raise VisionError(
            "BAD_TIMESTAMP",
            "A frame timestamp must be an int from 0 to"
            f" {TIMESTAMP_LIMIT_MS - 1} milliseconds, got"
            f" {describe_timestamp(timestamp_ms)}.",
            "Pass whole milliseconds as an int, for example"
            " int(time.monotonic() * 1000).",
        )


def describe_timestamp(timestamp_ms: object) -> str:
    if isinstance(timestamp_ms, int) and not isinstance(timestamp_ms, bool):
        return "an int outside that range"
    return f"a value of type {type(timestamp_ms).__name__}"


def first_face(
    result: FaceLandmarkerResult, width: int, height: int
) -> FaceLandmarks | None:
    if not result.face_landmarks:
        return None
    landmarks = result.face_landmarks[0]
    points = np.array([(mark.x, mark.y) for mark in landmarks], dtype=np.float64)
    in_frame = np.all((points >= 0.0) & (points <= 1.0), axis=1)
    return FaceLandmarks(
        points=np.clip(points, 0.0, 1.0),
        width=int(width),
        height=int(height),
        in_frame=in_frame,
    )
