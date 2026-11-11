import math
from collections import deque
from dataclasses import dataclass
from typing import Literal

import numpy as np
from numpy.typing import NDArray

from pulse_frame.signal.checks import (
    check_region_colour,
    check_sample_rate,
    check_timestamp,
    check_tracker_sample_rate,
    check_tracker_windows,
)
from pulse_frame.signal.cross import estimate_cross_rate, is_reliable, unit_variance
from pulse_frame.signal.filters import PASS_HIGH_HZ, PASS_LOW_HZ, bandpass
from pulse_frame.signal.pos import pos_pulse
from pulse_frame.signal.resample import resample_uniform

ReadingState = Literal["acquiring", "ok", "low_quality"]

UPDATE_INTERVAL_MS = 1000.0
MAX_GAP_MS = 1000.0
MAX_INPUT_FPS = 120.0
POS_WINDOW_S = 1.6
MIN_WINDOW_S = 20.0
REGION_NAMES = ("forehead", "left_cheek", "right_cheek")
REGION_COUNT = len(REGION_NAMES)

Rgb = tuple[float, float, float]


@dataclass(frozen=True)
class Reading:
    state: ReadingState
    bpm: float | None
    quality_db: float | None


@dataclass(frozen=True)
class RegionColours:
    forehead: Rgb
    left_cheek: Rgb
    right_cheek: Rgb

    def triples(self) -> tuple[Rgb, Rgb, Rgb]:
        return (self.forehead, self.left_cheek, self.right_cheek)


ACQUIRING = Reading(state="acquiring", bpm=None, quality_db=None)
MOTION_IN_WINDOW = Reading(state="low_quality", bpm=None, quality_db=None)
NO_PULSE = Reading(state="low_quality", bpm=None, quality_db=None)


class PulseTracker:
    def __init__(
        self, fs_hz: float = 30.0, window_s: float = 20.0, min_seconds: float = 20.0
    ) -> None:
        check_sample_rate(fs_hz)
        check_tracker_sample_rate(fs_hz, PASS_LOW_HZ, PASS_HIGH_HZ)
        check_tracker_windows(window_s, min_seconds, MIN_WINDOW_S)
        self._fs_hz = fs_hz
        self._window_ms = window_s * 1000.0
        self._settle_ms = min_seconds * 1000.0
        capacity = math.ceil(window_s * MAX_INPUT_FPS) + 1
        self._times: deque[float] = deque(maxlen=capacity)
        self._colours: deque[tuple[float, ...]] = deque(maxlen=capacity)
        self._started_ms: float | None = None
        self._next_update_ms: float | None = None
        self._last_motion_ms: float | None = None
        self._reading = ACQUIRING

    def add(
        self,
        timestamp_ms: float,
        regions: RegionColours,
        moving: bool = False,
    ) -> None:
        check_timestamp(timestamp_ms)
        for name, colour in zip(REGION_NAMES, regions.triples(), strict=True):
            check_region_colour(name, colour)
        if self._times and timestamp_ms <= self._times[-1]:
            return
        if self._times and timestamp_ms - self._times[-1] > MAX_GAP_MS:
            self._restart()
        self._times.append(float(timestamp_ms))
        self._colours.append(
            tuple(float(value) for colour in regions.triples() for value in colour)
        )
        if moving:
            self._mark_motion(float(timestamp_ms))
        self._drop_older_than_window()
        if self._started_ms is None or self._next_update_ms is None:
            self._started_ms = float(timestamp_ms)
            self._next_update_ms = timestamp_ms + UPDATE_INTERVAL_MS
        if timestamp_ms >= self._next_update_ms:
            self._next_update_ms += UPDATE_INTERVAL_MS * math.floor(
                (timestamp_ms - self._next_update_ms) / UPDATE_INTERVAL_MS + 1.0
            )
            self._reading = self._estimate(timestamp_ms - self._started_ms)

    def _mark_motion(self, timestamp_ms: float) -> None:
        self._last_motion_ms = timestamp_ms
        if self._reading.state == "ok":
            self._reading = MOTION_IN_WINDOW

    def tick(self, timestamp_ms: float) -> None:
        check_timestamp(timestamp_ms)
        if self._times and timestamp_ms - self._times[-1] > MAX_GAP_MS:
            self._restart()

    def reading(self) -> Reading:
        return self._reading

    def waveform(self) -> list[tuple[float, float]]:
        processed = self._region_pulses()
        if processed is None:
            return []
        times, pulses = processed
        normalised = unit_variance(pulses)
        combined = (pulses if normalised is None else normalised).mean(axis=0)
        return [(float(t), float(v)) for t, v in zip(times, combined, strict=True)]

    def _restart(self) -> None:
        self._times.clear()
        self._colours.clear()
        self._started_ms = None
        self._next_update_ms = None
        self._last_motion_ms = None
        self._reading = ACQUIRING

    def _drop_older_than_window(self) -> None:
        oldest_allowed = self._times[-1] - self._window_ms
        while self._times[0] < oldest_allowed:
            self._times.popleft()
            self._colours.popleft()

    def _span_ms(self) -> float:
        return self._times[-1] - self._times[0] if self._times else 0.0

    def _region_pulses(
        self,
    ) -> tuple[NDArray[np.float64], NDArray[np.float64]] | None:
        if self._span_ms() < POS_WINDOW_S * 1000.0:
            return None
        times, rows = resample_uniform(
            np.array(self._times), np.array(self._colours), self._fs_hz
        )
        pulses = np.stack(
            [
                bandpass(pos_pulse(rgb, self._fs_hz, POS_WINDOW_S), self._fs_hz)
                for rgb in np.split(rows, REGION_COUNT, axis=1)
            ]
        )
        return times, pulses

    def _estimate(self, elapsed_ms: float) -> Reading:
        if elapsed_ms < self._settle_ms:
            return ACQUIRING
        if self._motion_in_window():
            return MOTION_IN_WINDOW
        processed = self._region_pulses()
        if processed is None:
            return ACQUIRING
        pulses = unit_variance(processed[1])
        if pulses is None:
            return NO_PULSE
        return gated_reading(pulses, self._fs_hz)

    def _motion_in_window(self) -> bool:
        return (
            self._last_motion_ms is not None and self._last_motion_ms >= self._times[0]
        )


def gated_reading(pulses: NDArray[np.float64], fs_hz: float) -> Reading:
    full = estimate_cross_rate(pulses, fs_hz)
    if full is None:
        return NO_PULSE
    first_half, second_half = np.array_split(pulses, 2, axis=1)
    if is_reliable(
        full,
        estimate_cross_rate(first_half, fs_hz),
        estimate_cross_rate(second_half, fs_hz),
    ):
        return Reading(state="ok", bpm=full.bpm, quality_db=full.prominence_db)
    return Reading(state="low_quality", bpm=None, quality_db=full.prominence_db)
