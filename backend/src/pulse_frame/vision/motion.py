from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from pulse_frame.vision.landmarks import FaceLandmarks

MOVING_SHARE_OF_FACE_WIDTH = 0.01
REFERENCE_FRAME_MS = 1000.0 / 30.0


@dataclass(frozen=True)
class PixelFace:
    points: NDArray[np.float64]
    frame_size: tuple[int, int]
    timestamp_ms: float


class MotionGate:
    def __init__(self) -> None:
        self._previous: PixelFace | None = None
        self._share = 0.0

    @property
    def share(self) -> float:
        return self._share

    def update(self, face: FaceLandmarks, timestamp_ms: float) -> bool:
        current = pixel_face(face, timestamp_ms)
        previous, self._previous = self._previous, current
        self._share = motion_share(previous, current)
        return self._share > MOVING_SHARE_OF_FACE_WIDTH


def pixel_face(face: FaceLandmarks, timestamp_ms: float) -> PixelFace:
    scale = np.array([face.width, face.height], dtype=np.float64)
    return PixelFace(
        points=face.points * scale,
        frame_size=(face.width, face.height),
        timestamp_ms=float(timestamp_ms),
    )


def motion_share(previous: PixelFace | None, current: PixelFace) -> float:
    if previous is None or not comparable(previous, current):
        return 0.0
    width_px = face_width_px(current.points)
    if width_px <= 0.0:
        return 0.0
    interval_ms = current.timestamp_ms - previous.timestamp_ms
    step_px = median_displacement(previous.points, current.points)
    return step_px / width_px * interval_scale(interval_ms)


def interval_scale(interval_ms: float) -> float:
    if interval_ms <= REFERENCE_FRAME_MS:
        return 1.0
    return REFERENCE_FRAME_MS / interval_ms


def comparable(previous: PixelFace, current: PixelFace) -> bool:
    return (
        previous.points.shape == current.points.shape
        and previous.frame_size == current.frame_size
        and current.timestamp_ms > previous.timestamp_ms
    )


def median_displacement(
    before: NDArray[np.float64], after: NDArray[np.float64]
) -> float:
    return float(np.median(np.linalg.norm(after - before, axis=1)))


def face_width_px(points: NDArray[np.float64]) -> float:
    return float(np.ptp(points[:, 0]))
