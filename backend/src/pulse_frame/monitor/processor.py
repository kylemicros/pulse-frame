from dataclasses import dataclass, field
from pathlib import Path
from types import TracebackType
from typing import Self

import numpy as np
from numpy.typing import NDArray

from pulse_frame.signal.tracker import PulseTracker, Reading, RegionColours, Rgb
from pulse_frame.vision.landmarks import FaceTracker
from pulse_frame.vision.motion import MotionGate
from pulse_frame.vision.regions import REGION_NAMES, named_region_polygons, skin_mean

NO_SKIN_READING = Reading(state="low_quality", bpm=None, quality_db=None)


@dataclass(frozen=True)
class Patch:
    usable: bool
    outline: NDArray[np.float64] | None


UNUSABLE_PATCH = Patch(usable=False, outline=None)


@dataclass(frozen=True)
class FrameResult:
    face: bool
    regions: list[NDArray[np.float64]]
    moving: bool
    motion_share: float
    reading: Reading
    patches: dict[str, Patch] = field(default_factory=dict)


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

    def waveform(self) -> list[tuple[float, float]]:
        return self._pulse.waveform()

    def process(self, rgb: NDArray[np.uint8], timestamp_ms: int) -> FrameResult:
        face = self._faces.detect(rgb, timestamp_ms)
        if face is None:
            return self._without_skin(
                timestamp_ms, face=False, moving=False, patches=unusable_patches()
            )
        named = named_region_polygons(face)
        moved = self._motion.update(face, timestamp_ms)
        means = region_means(rgb, named)
        patches = region_patches(named, means)
        colours = colours_from_means(means)
        if colours is None:
            self._latched_motion = self._latched_motion or moved
            return self._without_skin(
                timestamp_ms,
                face=True,
                moving=moved,
                patches=patches,
                regions=list(named.values()),
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
            patches=patches,
        )

    def _without_skin(
        self,
        timestamp_ms: int,
        face: bool,
        moving: bool,
        patches: dict[str, Patch],
        regions: list[NDArray[np.float64]] | None = None,
    ) -> FrameResult:
        self._pulse.tick(timestamp_ms)
        return FrameResult(
            face=face,
            regions=regions or [],
            moving=moving,
            motion_share=self._motion.share if face else 0.0,
            reading=never_ok(self._pulse.reading()),
            patches=patches,
        )


def region_means(
    rgb: NDArray[np.uint8], named: dict[str, NDArray[np.float64]]
) -> dict[str, Rgb | None]:
    return {name: region_mean(rgb, named.get(name)) for name in REGION_NAMES}


def region_patches(
    named: dict[str, NDArray[np.float64]], means: dict[str, Rgb | None]
) -> dict[str, Patch]:
    return {
        name: UNUSABLE_PATCH
        if means[name] is None
        else Patch(usable=True, outline=named[name])
        for name in REGION_NAMES
    }


def unusable_patches() -> dict[str, Patch]:
    return dict.fromkeys(REGION_NAMES, UNUSABLE_PATCH)


def colours_from_means(means: dict[str, Rgb | None]) -> RegionColours | None:
    forehead, left_cheek, right_cheek = (means[name] for name in REGION_NAMES)
    if forehead is None or left_cheek is None or right_cheek is None:
        return None
    return RegionColours(
        forehead=forehead, left_cheek=left_cheek, right_cheek=right_cheek
    )


def region_mean(
    rgb: NDArray[np.uint8], polygon: NDArray[np.float64] | None
) -> Rgb | None:
    return None if polygon is None else skin_mean(rgb, [polygon])


def never_ok(reading: Reading) -> Reading:
    if reading.state == "ok":
        return NO_SKIN_READING
    return reading
