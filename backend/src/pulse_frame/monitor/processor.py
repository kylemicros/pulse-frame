from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Self

import numpy as np
from numpy.typing import NDArray

from pulse_frame.signal.tracker import PulseTracker, Reading, RegionColours
from pulse_frame.vision.landmarks import FaceTracker
from pulse_frame.vision.motion import MotionGate
from pulse_frame.vision.regions import REGION_NAMES, named_region_polygons, skin_mean

NO_SKIN_READING = Reading(state="low_quality", bpm=None, quality_db=None)


@dataclass(frozen=True)
class FrameResult:
    face: bool
    regions: list[NDArray[np.float64]]
    moving: bool
    motion_share: float
    reading: Reading


class FrameProcessor:
    def __init__(self, model: Path) -> None:
        self._faces = FaceTracker(model)
        self._motion = MotionGate()
        self._pulse = PulseTracker()
        self._latched_motion = False

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
        self._faces.close()

    def process(self, rgb: NDArray[np.uint8], timestamp_ms: int) -> FrameResult:
        face = self._faces.detect(rgb, timestamp_ms)
        if face is None:
            return self._without_skin(timestamp_ms, face=False, moving=False)
        named = named_region_polygons(face)
        moved = self._motion.update(face, timestamp_ms)
        colours = region_colours(rgb, named)
        if colours is None:
            self._latched_motion = self._latched_motion or moved
            return self._without_skin(
                timestamp_ms, face=True, moving=moved, regions=list(named.values())
            )
        moving = moved or self._latched_motion
        self._latched_motion = False
        self._pulse.add(timestamp_ms, colours, moving=moving)
        return FrameResult(
            face=True,
            regions=list(named.values()),
            moving=moving,
            motion_share=self._motion.share,
            reading=self._pulse.reading(),
        )

    def _without_skin(
        self,
        timestamp_ms: int,
        face: bool,
        moving: bool,
        regions: list[NDArray[np.float64]] | None = None,
    ) -> FrameResult:
        self._pulse.tick(timestamp_ms)
        return FrameResult(
            face=face,
            regions=regions or [],
            moving=moving,
            motion_share=self._motion.share if face else 0.0,
            reading=never_ok(self._pulse.reading()),
        )


def region_colours(
    rgb: NDArray[np.uint8], named: dict[str, NDArray[np.float64]]
) -> RegionColours | None:
    means = [region_mean(rgb, named.get(name)) for name in REGION_NAMES]
    forehead, left_cheek, right_cheek = means
    if forehead is None or left_cheek is None or right_cheek is None:
        return None
    return RegionColours(
        forehead=forehead, left_cheek=left_cheek, right_cheek=right_cheek
    )


def region_mean(
    rgb: NDArray[np.uint8], polygon: NDArray[np.float64] | None
) -> tuple[float, float, float] | None:
    return None if polygon is None else skin_mean(rgb, [polygon])


def never_ok(reading: Reading) -> Reading:
    if reading.state == "ok":
        return NO_SKIN_READING
    return reading
