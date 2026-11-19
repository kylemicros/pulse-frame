import math
from dataclasses import dataclass
from typing import Literal

import numpy as np
from numpy.typing import NDArray
from scipy.ndimage import median_filter
from scipy.signal import find_peaks

from pulse_frame.signal.checks import (
    check_rate,
    check_region_pulses,
    check_sample_flags,
    check_sample_rate,
    check_signal,
    check_timestamp,
    check_timestamp_array,
)
from pulse_frame.signal.filters import PASS_HIGH_HZ, bandpass
from pulse_frame.signal.resample import resample_uniform
from pulse_frame.signal.tracker import MAX_GAP_MS

type IntervalFlag = Literal[
    "ok", "motion", "gap", "low_quality", "edge", "out_of_range", "off_median"
]

MIN_IBI_MS = 300.0
MAX_IBI_MS = 2000.0
OFF_MEDIAN_SHARE = 0.3
MEDIAN_SPAN = 11
FLAG_GUARD_MS = 1_600.0
SNR_FLOOR_DB = 0.0
MIN_SNR_REGIONS = 2
BEAT_SPACING_SHARE = 0.6
GUIDE_HALF_WIDTH_HZ = 0.4
GUIDE_FLOOR_HZ = 0.3
RATE_BAND_ORDER = 2
HIGHEST_RATE_HZ = PASS_HIGH_HZ - GUIDE_HALF_WIDTH_HZ
APEX_REACH_SHARE = 0.3
FOOT_REACH_SHARE = 0.6
TEMPLATE_LEAD_SHARE = 0.3
MIN_TEMPLATE_CORRELATION = 0.6
MIN_TEMPLATE_BEATS = 3
MIN_SNR_CYCLES = 12
CYCLE_POINTS = 64
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


def rate_guided_beats(
    timestamps_ms: NDArray[np.float64],
    pulse: NDArray[np.float64],
    rate_hz: float,
    fs_hz: float = 30.0,
) -> NDArray[np.float64]:
    check_rate(rate_hz, HIGHEST_RATE_HZ)
    samples = np.asarray(pulse, dtype=np.float64)
    check_signal(samples)
    grid, rows = resample_uniform(timestamps_ms, samples[:, None], fs_hz)
    blood = rows[:, 0].mean() - rows[:, 0]
    if blood.size < 3 or not np.ptp(blood) > 0.0:
        return np.empty(0)
    period = fs_hz / rate_hz
    peaks = guide_peaks(rate_band(blood, rate_hz, fs_hz), rate_hz, fs_hz)
    times = upstroke_midpoints(grid, blood, peaks, period)
    kept = times[matches_template(grid, blood, times, period)]
    return spaced_beats(kept, BEAT_SPACING_SHARE * 1000.0 / rate_hz)


def rate_band(
    values: NDArray[np.float64], rate_hz: float, fs_hz: float
) -> NDArray[np.float64]:
    low_hz = max(GUIDE_FLOOR_HZ, rate_hz - GUIDE_HALF_WIDTH_HZ)
    high_hz = rate_hz + GUIDE_HALF_WIDTH_HZ
    return bandpass(values, fs_hz, low_hz, high_hz, RATE_BAND_ORDER)


def guide_peaks(
    guide: NDArray[np.float64], rate_hz: float, fs_hz: float
) -> NDArray[np.intp]:
    shortest = math.ceil(BEAT_SPACING_SHARE * fs_hz / rate_hz)
    peaks, _ = find_peaks(guide, distance=max(1, shortest))
    return peaks


def cross_region_snr_db(
    regions: NDArray[np.float64], rate_hz: float, fs_hz: float = 30.0
) -> float:
    check_rate(rate_hz, HIGHEST_RATE_HZ)
    check_sample_rate(fs_hz)
    pulses = np.asarray(regions, dtype=np.float64)
    check_region_pulses(pulses)
    if pulses.shape[0] < MIN_SNR_REGIONS:
        return -math.inf
    blood = -pulses
    return max(
        cycle_snr_db(
            held_out,
            guide_peaks(
                rate_band(np.delete(blood, index, axis=0).mean(axis=0), rate_hz, fs_hz),
                rate_hz,
                fs_hz,
            ),
        )
        for index, held_out in enumerate(blood)
    )


def cycle_snr_db(blood: NDArray[np.float64], peaks: NDArray[np.intp]) -> float:
    if peaks.size < MIN_SNR_CYCLES + 1:
        return -math.inf
    starts = peaks[:-1].astype(np.float64)
    lengths = np.diff(peaks).astype(np.float64)
    phases = np.arange(CYCLE_POINTS) / CYCLE_POINTS
    positions = starts[:, None] + lengths[:, None] * phases[None, :]
    cycles = np.interp(positions, np.arange(blood.size), blood)
    cycles -= cycles.mean(axis=1, keepdims=True)
    template = cycles.mean(axis=0)
    clean = float(template.var())
    noise = float((cycles - template).var())
    if clean <= 0.0:
        return -math.inf
    if noise <= 0.0:
        return math.inf
    return 10.0 * math.log10(clean / noise)


def upstroke_midpoints(
    grid: NDArray[np.float64],
    shape: NDArray[np.float64],
    peaks: NDArray[np.intp],
    period: float,
) -> NDArray[np.float64]:
    last = shape.size - 1
    times: list[float] = []
    for peak in peaks:
        low = max(0, int(peak - APEX_REACH_SHARE * period))
        high = min(last, int(peak + APEX_REACH_SHARE * period))
        apex = low + int(np.argmax(shape[low : high + 1]))
        reach = max(0, int(apex - FOOT_REACH_SHARE * period))
        foot = reach + int(np.argmin(shape[reach : apex + 1]))
        if not shape[apex] > shape[foot]:
            continue
        times.append(level_crossing_ms(grid, shape, foot, apex))
    return np.array(times, dtype=np.float64)


def level_crossing_ms(
    grid: NDArray[np.float64], shape: NDArray[np.float64], foot: int, apex: int
) -> float:
    rise = shape[foot : apex + 1]
    level = 0.5 * (rise[0] + rise[-1])
    below = np.flatnonzero((rise[:-1] < level) & (rise[1:] >= level))
    step = foot + int(below[-1])
    before, after = shape[step], shape[step + 1]
    share = (level - before) / (after - before)
    return float(grid[step] + share * (grid[step + 1] - grid[step]))


def matches_template(
    grid: NDArray[np.float64],
    shape: NDArray[np.float64],
    times_ms: NDArray[np.float64],
    period: float,
) -> NDArray[np.bool_]:
    length = round(period)
    indices = np.arange(shape.size, dtype=np.float64)
    centres = np.interp(times_ms, grid, indices)
    positions = (centres - TEMPLATE_LEAD_SHARE * length)[:, None] + np.arange(length)
    inside = (positions[:, 0] >= 0.0) & (positions[:, -1] <= shape.size - 1)
    if np.count_nonzero(inside) < MIN_TEMPLATE_BEATS:
        return np.ones(times_ms.size, dtype=np.bool_)
    beats = np.interp(positions[inside], indices, shape)
    matches = np.ones(times_ms.size, dtype=np.bool_)
    matches[inside] = template_correlations(beats) >= MIN_TEMPLATE_CORRELATION
    return matches


def template_correlations(beats: NDArray[np.float64]) -> NDArray[np.float64]:
    template = np.median(beats, axis=0)
    centred = beats - beats.mean(axis=1, keepdims=True)
    template_centred = template - template.mean()
    norms = np.linalg.norm(centred, axis=1) * np.linalg.norm(template_centred)
    return np.divide(
        centred @ template_centred,
        norms,
        out=np.zeros(beats.shape[0]),
        where=norms > 0.0,
    )


def spaced_beats(
    times_ms: NDArray[np.float64], shortest_ms: float
) -> NDArray[np.float64]:
    kept: list[float] = []
    for time_ms in np.sort(times_ms):
        if not kept or time_ms - kept[-1] >= shortest_ms:
            kept.append(float(time_ms))
    return np.array(kept, dtype=np.float64)


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
