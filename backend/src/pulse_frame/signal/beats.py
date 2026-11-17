from dataclasses import dataclass
from typing import Literal

import numpy as np
from numpy.typing import NDArray
from scipy.interpolate import CubicSpline
from scipy.ndimage import median_filter
from scipy.signal import find_peaks

from pulse_frame.signal.checks import (
    check_sample_flags,
    check_signal,
    check_timestamp,
    check_timestamp_array,
)
from pulse_frame.signal.resample import resample_uniform
from pulse_frame.signal.tracker import MAX_GAP_MS

type IntervalFlag = Literal[
    "ok", "motion", "gap", "low_quality", "edge", "out_of_range", "off_median"
]

MIN_IBI_MS = 300.0
MAX_IBI_MS = 2000.0
OFF_MEDIAN_SHARE = 0.3
MEDIAN_SPAN = 11
MIN_PROMINENCE_SD = 0.5
FLAG_GUARD_MS = 1_600.0
REJECTION_ORDER: tuple[IntervalFlag, ...] = (
    "gap",
    "motion",
    "low_quality",
    "edge",
    "out_of_range",
    "off_median",
)


@dataclass(frozen=True)
class Interval:
    start_ms: float
    end_ms: float
    flag: IntervalFlag

    @property
    def ibi_ms(self) -> float:
        return self.end_ms - self.start_ms

    @property
    def accepted(self) -> bool:
        return self.flag == "ok"


def detect_beats(
    timestamps_ms: NDArray[np.float64], pulse: NDArray[np.float64], fs_hz: float = 30.0
) -> NDArray[np.float64]:
    samples = np.asarray(pulse, dtype=np.float64)
    check_signal(samples)
    grid, rows = resample_uniform(timestamps_ms, samples[:, None], fs_hz)
    values = rows[:, 0]
    if values.size < 3 or not np.ptp(values) > 0.0:
        return np.empty(0)
    peaks, properties = find_peaks(
        values, prominence=MIN_PROMINENCE_SD * values.std(), plateau_size=1
    )
    left = properties["left_edges"]
    right = properties["right_edges"]
    refined = spline_peak_times(grid, values, peaks)
    return np.where(right > left, 0.5 * (grid[left] + grid[right]), refined)


def spline_peak_times(
    grid: NDArray[np.float64], values: NDArray[np.float64], peaks: NDArray[np.intp]
) -> NDArray[np.float64]:
    spline = CubicSpline(grid, values)
    turns = spline.derivative().roots(extrapolate=False)
    times = grid[peaks].astype(np.float64)
    last = grid.size - 1
    for index, peak in enumerate(peaks):
        low_ms = grid[max(peak - 1, 0)]
        high_ms = grid[min(peak + 1, last)]
        inside = turns[(turns >= low_ms) & (turns <= high_ms)]
        if inside.size:
            times[index] = inside[np.argmax(spline(inside))]
    return times


def label_intervals(
    beat_times_ms: NDArray[np.float64],
    *,
    sample_times_ms: NDArray[np.float64],
    moving: NDArray[np.bool_],
    low_quality: NDArray[np.bool_],
    stable_until_ms: float,
) -> list[Interval]:
    beats = np.asarray(beat_times_ms, dtype=np.float64)
    times = np.asarray(sample_times_ms, dtype=np.float64)
    moving_at = np.asarray(moving, dtype=np.bool_)
    low_at = np.asarray(low_quality, dtype=np.bool_)
    check_timestamp_array(beats)
    check_timestamp_array(times)
    check_sample_flags(times, moving_at, "moving")
    check_sample_flags(times, low_at, "low_quality")
    check_timestamp(stable_until_ms)
    if beats.size < 2:
        return []
    starts = beats[:-1]
    ends = beats[1:]
    ibis = ends - starts
    rejections = [
        spans_gap(starts, ends, times),
        near_flagged_sample(starts, ends, times[moving_at]),
        near_flagged_sample(starts, ends, times[low_at]),
        ends > stable_until_ms,
        (ibis < MIN_IBI_MS) | (ibis > MAX_IBI_MS),
        off_local_median(ibis),
    ]
    codes = np.select(rejections, range(1, len(rejections) + 1), default=0)
    flags: tuple[IntervalFlag, ...] = ("ok", *REJECTION_ORDER)
    return [
        Interval(start_ms=float(start), end_ms=float(end), flag=flags[code])
        for start, end, code in zip(starts, ends, codes, strict=True)
    ]


def near_flagged_sample(
    starts: NDArray[np.float64], ends: NDArray[np.float64], flagged: NDArray[np.float64]
) -> NDArray[np.bool_]:
    ordered = np.sort(flagged)
    first = np.searchsorted(ordered, starts - FLAG_GUARD_MS, side="left")
    after_last = np.searchsorted(ordered, ends + FLAG_GUARD_MS, side="right")
    return after_last > first


def spans_gap(
    starts: NDArray[np.float64], ends: NDArray[np.float64], times: NDArray[np.float64]
) -> NDArray[np.bool_]:
    wide = np.diff(times) > MAX_GAP_MS
    gap_from = times[:-1][wide]
    gap_to = times[1:][wide]
    crossing = (starts[:, None] < gap_to[None, :]) & (ends[:, None] > gap_from[None, :])
    return crossing.any(axis=1)


def off_local_median(ibis: NDArray[np.float64]) -> NDArray[np.bool_]:
    local = median_filter(ibis, size=MEDIAN_SPAN, mode="nearest")
    return np.abs(ibis - local) > OFF_MEDIAN_SHARE * local
