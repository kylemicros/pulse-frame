import math
from collections import deque
from dataclasses import dataclass
from typing import Literal

import numpy as np
from numpy.typing import NDArray

from pulse_frame.signal.checks import (
    check_sample,
    check_sample_rate,
    check_timestamp,
    check_tracker_sample_rate,
    check_tracker_windows,
)
from pulse_frame.signal.filters import PASS_HIGH_HZ, PASS_LOW_HZ, bandpass
from pulse_frame.signal.pos import pos_pulse
from pulse_frame.signal.resample import resample_uniform
from pulse_frame.signal.spectrum import RateEstimate, estimate_rate

ReadingState = Literal["acquiring", "ok", "low_quality"]

MIN_SNR_DB = 4.5
UPDATE_INTERVAL_MS = 1000.0
SMOOTHING_COUNT = 3
MAX_BPM_PER_S = 5.0
MAX_GAP_MS = 1000.0
MAX_INPUT_FPS = 120.0
POS_WINDOW_S = 1.6
MIN_WINDOW_S = 10.0


@dataclass(frozen=True)
class Reading:
    state: ReadingState
    bpm: float | None
    quality_db: float | None


ACQUIRING = Reading(state="acquiring", bpm=None, quality_db=None)
MOTION_IN_WINDOW = Reading(state="low_quality", bpm=None, quality_db=None)


@dataclass(frozen=True)
class TimedRate:
    timestamp_ms: float
    bpm: float

    def leads_to(self, later: "TimedRate") -> bool:
        elapsed_s = (later.timestamp_ms - self.timestamp_ms) / 1000.0
        return abs(later.bpm - self.bpm) <= MAX_BPM_PER_S * elapsed_s


class RateSmoother:
    def __init__(self) -> None:
        self._accepted: deque[TimedRate] = deque(maxlen=SMOOTHING_COUNT)
        self._held: TimedRate | None = None
        self._shown: Reading | None = None

    def update(self, timestamp_ms: float, estimate: RateEstimate) -> Reading:
        if estimate.snr_db < MIN_SNR_DB:
            self.reset()
            return Reading(state="low_quality", bpm=None, quality_db=estimate.snr_db)
        rate = TimedRate(timestamp_ms, estimate.bpm)
        if self._shown is None or self._accepted[-1].leads_to(rate):
            self._accepted.append(rate)
        elif self._held is not None and self._held.leads_to(rate):
            self._accepted.clear()
            self._accepted.extend((self._held, rate))
        elif self._held is not None:
            self.reset()
            return Reading(state="low_quality", bpm=None, quality_db=estimate.snr_db)
        else:
            self._held = rate
            return self._shown
        self._held = None
        self._shown = Reading(
            state="ok",
            bpm=float(np.median([r.bpm for r in self._accepted])),
            quality_db=estimate.snr_db,
        )
        return self._shown

    def reset(self) -> None:
        self._accepted.clear()
        self._held = None
        self._shown = None


class PulseTracker:
    def __init__(
        self, fs_hz: float = 30.0, window_s: float = 10.0, min_seconds: float = 10.0
    ) -> None:
        check_sample_rate(fs_hz)
        check_tracker_sample_rate(fs_hz, PASS_LOW_HZ, PASS_HIGH_HZ)
        check_tracker_windows(
            window_s, min_seconds, POS_WINDOW_S, MIN_WINDOW_S, MIN_SNR_DB
        )
        self._fs_hz = fs_hz
        self._window_ms = window_s * 1000.0
        self._settle_ms = min_seconds * 1000.0
        capacity = math.ceil(window_s * MAX_INPUT_FPS) + 1
        self._times: deque[float] = deque(maxlen=capacity)
        self._colours: deque[tuple[float, float, float]] = deque(maxlen=capacity)
        self._smoother = RateSmoother()
        self._started_ms: float | None = None
        self._next_update_ms: float | None = None
        self._last_motion_ms: float | None = None
        self._reading = ACQUIRING

    def add(
        self,
        timestamp_ms: float,
        rgb: tuple[float, float, float],
        moving: bool = False,
    ) -> None:
        check_sample(timestamp_ms, rgb)
        if self._times and timestamp_ms <= self._times[-1]:
            return
        if self._times and timestamp_ms - self._times[-1] > MAX_GAP_MS:
            self._restart()
        self._times.append(float(timestamp_ms))
        self._colours.append((float(rgb[0]), float(rgb[1]), float(rgb[2])))
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
            self._smoother.reset()
            self._reading = MOTION_IN_WINDOW

    def tick(self, timestamp_ms: float) -> None:
        check_timestamp(timestamp_ms)
        if self._times and timestamp_ms - self._times[-1] > MAX_GAP_MS:
            self._restart()

    def reading(self) -> Reading:
        return self._reading

    def waveform(self) -> list[tuple[float, float]]:
        processed = self._filtered_pulse()
        if processed is None:
            return []
        times, pulse = processed
        return [(float(t), float(v)) for t, v in zip(times, pulse, strict=True)]

    def _restart(self) -> None:
        self._times.clear()
        self._colours.clear()
        self._smoother.reset()
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

    def _filtered_pulse(self) -> tuple[NDArray[np.float64], NDArray[np.float64]] | None:
        if self._span_ms() < POS_WINDOW_S * 1000.0:
            return None
        times, rgb = resample_uniform(
            np.array(self._times), np.array(self._colours), self._fs_hz
        )
        pulse = pos_pulse(rgb, self._fs_hz, POS_WINDOW_S)
        return times, bandpass(pulse, self._fs_hz)

    def _estimate(self, elapsed_ms: float) -> Reading:
        if elapsed_ms < self._settle_ms:
            return ACQUIRING
        if self._motion_in_window():
            self._smoother.reset()
            return MOTION_IN_WINDOW
        processed = self._filtered_pulse()
        if processed is None:
            return ACQUIRING
        estimate = estimate_rate(processed[1], self._fs_hz)
        return self._smoother.update(self._times[-1], estimate)

    def _motion_in_window(self) -> bool:
        return (
            self._last_motion_ms is not None and self._last_motion_ms >= self._times[0]
        )
