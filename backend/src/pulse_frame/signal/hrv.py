import math
from collections import defaultdict, deque
from collections.abc import Sequence
from dataclasses import dataclass, replace
from itertools import pairwise

import numpy as np
from numpy.typing import NDArray

from pulse_frame.signal.beats import (
    MAX_IBI_MS,
    Interval,
    detect_beats,
    label_intervals,
)
from pulse_frame.signal.checks import (
    check_region_colour,
    check_sample_rate,
    check_timestamp,
    check_tracker_sample_rate,
)
from pulse_frame.signal.cross import unit_variance
from pulse_frame.signal.filters import PASS_HIGH_HZ, PASS_LOW_HZ, bandpass
from pulse_frame.signal.pos import pos_pulse
from pulse_frame.signal.resample import resample_uniform
from pulse_frame.signal.tracker import (
    MAX_GAP_MS,
    MAX_INPUT_FPS,
    POS_WINDOW_S,
    REGION_COUNT,
    REGION_NAMES,
    UPDATE_INTERVAL_MS,
    RegionColours,
)

WINDOW_MS = 300_000.0
MIN_ACCEPTED_MS = 60_000.0
MAX_REJECTED_SHARE = 0.2
ANALYSIS_MS = 20_000.0
EDGE_MS = 3_000.0
SAME_BEAT_MS = 150.0
STALE_MS = 10_000.0
ALTERNATION_LIMIT = 0.15
BLOCK_MS = 25_000.0
MIN_BLOCK_RUNS = 8
MIN_SEGMENT_MS = 10_000.0
SPREAD_LIMIT_MS = 30.0


@dataclass(frozen=True)
class HrvReading:
    rmssd_ms: float | None
    sdnn_ms: float | None
    window_ms: float | None = None
    accepted_count: int | None = None


NO_HRV = HrvReading(rmssd_ms=None, sdnn_ms=None)


def hrv_reading(
    intervals: Sequence[Interval], newest_sample_ms: float | None = None
) -> HrvReading:
    if newest_sample_ms is not None:
        check_timestamp(newest_sample_ms)
    if not intervals:
        return NO_HRV
    newest_ms = newest_time_ms(intervals, newest_sample_ms)
    window = newest_window(intervals, newest_ms)
    accepted = np.array([i.ibi_ms for i in window if i.accepted])
    if is_stale(window, newest_ms) or too_many_rejected(window, accepted.size):
        return NO_HRV
    if accepted.size < 2 or accepted.sum() < MIN_ACCEPTED_MS:
        return NO_HRV
    successive = np.diff(touching_runs(window, 2), axis=1)
    if successive.size == 0 or alternates(window):
        return NO_HRV
    return HrvReading(
        rmssd_ms=float(np.sqrt(np.mean(np.square(successive)))),
        sdnn_ms=float(np.std(accepted, ddof=1)),
        window_ms=window_span_ms(window),
        accepted_count=int(accepted.size),
    )


def window_span_ms(window: Sequence[Interval]) -> float:
    return max(i.end_ms for i in window) - min(i.start_ms for i in window)


def newest_time_ms(
    intervals: Sequence[Interval], newest_sample_ms: float | None
) -> float:
    if newest_sample_ms is None:
        return max(i.end_ms for i in intervals)
    return newest_sample_ms


def newest_window(intervals: Sequence[Interval], newest_ms: float) -> list[Interval]:
    oldest_start_ms = newest_ms - WINDOW_MS
    return [i for i in intervals if i.start_ms >= oldest_start_ms]


def accepted_runs(window: Sequence[Interval], length: int) -> list[Sequence[Interval]]:
    return [
        run
        for run in (window[k : k + length] for k in range(len(window) - length + 1))
        if all(i.accepted for i in run)
        and all(a.end_ms == b.start_ms for a, b in pairwise(run))
    ]


def run_ibis(runs: Sequence[Sequence[Interval]], length: int) -> NDArray[np.float64]:
    ibis = [[i.ibi_ms for i in run] for run in runs]
    return np.array(ibis, dtype=np.float64).reshape(-1, length)


def touching_runs(window: Sequence[Interval], length: int) -> NDArray[np.float64]:
    return run_ibis(accepted_runs(window, length), length)


def alternates(window: Sequence[Interval]) -> bool:
    newest_end_ms = max(i.end_ms for i in window)
    blocks: defaultdict[int, list[Sequence[Interval]]] = defaultdict(list)
    for run in accepted_runs(window, 3):
        blocks[int((newest_end_ms - run[-1].end_ms) // BLOCK_MS)].append(run)
    return any(
        len(runs) >= MIN_BLOCK_RUNS and swings_back_and_forth(run_ibis(runs, 3))
        for runs in blocks.values()
    )


def swings_back_and_forth(ibis: NDArray[np.float64]) -> bool:
    steps = np.diff(ibis, axis=1)
    together = float(np.sum(np.square(steps[:, 0] + steps[:, 1])))
    apart = float(np.sum(np.square(steps[:, 0] - steps[:, 1])))
    return together < ALTERNATION_LIMIT * apart


def too_many_rejected(window: Sequence[Interval], accepted_count: int) -> bool:
    settled = sum(1 for i in window if i.flag != "edge")
    return (settled - accepted_count) / settled > MAX_REJECTED_SHARE


def is_stale(window: Sequence[Interval], newest_ms: float) -> bool:
    ends = [i.end_ms for i in window if i.accepted]
    return not ends or newest_ms - max(ends) > STALE_MS


class HrvTracker:
    def __init__(self, fs_hz: float = 30.0) -> None:
        check_sample_rate(fs_hz)
        check_tracker_sample_rate(fs_hz, PASS_LOW_HZ, PASS_HIGH_HZ)
        self._fs_hz = fs_hz
        capacity = math.ceil(ANALYSIS_MS / 1000.0 * MAX_INPUT_FPS) + 1
        self._times: deque[float] = deque(maxlen=capacity)
        self._colours: deque[tuple[float, ...]] = deque(maxlen=capacity)
        self._moving: deque[bool] = deque(maxlen=capacity)
        self._low: deque[bool] = deque(maxlen=capacity)
        self._beats: deque[float] = deque()
        self._committed: deque[Interval] = deque()
        self._pending: list[Interval] = []
        self._next_update_ms: float | None = None

    def add(
        self,
        timestamp_ms: float,
        regions: RegionColours,
        moving: bool = False,
        low_quality: bool = False,
    ) -> None:
        check_timestamp(timestamp_ms)
        for name, colour in zip(REGION_NAMES, regions.triples(), strict=True):
            check_region_colour(name, colour)
        if self._times and timestamp_ms <= self._times[-1]:
            return
        self._times.append(float(timestamp_ms))
        self._colours.append(
            tuple(float(value) for colour in regions.triples() for value in colour)
        )
        self._moving.append(moving)
        self._low.append(low_quality)
        self._drop_older_than_analysis()
        if self._next_update_ms is None:
            self._next_update_ms = timestamp_ms + UPDATE_INTERVAL_MS
        elif timestamp_ms >= self._next_update_ms:
            self._next_update_ms = timestamp_ms + UPDATE_INTERVAL_MS
            self._update()

    def intervals(self) -> list[Interval]:
        return [*self._committed, *self._pending]

    def settled_intervals(self) -> list[Interval]:
        return list(self._committed)

    def reading(self) -> HrvReading:
        newest_ms = self._times[-1] if self._times else None
        return hrv_reading(self.intervals(), newest_ms)

    def _drop_older_than_analysis(self) -> None:
        oldest_allowed = self._times[-1] - ANALYSIS_MS
        while self._times[0] < oldest_allowed:
            self._times.popleft()
            self._colours.popleft()
            self._moving.popleft()
            self._low.popleft()
        while self._beats and self._beats[0] < self._times[0]:
            self._beats.popleft()
        oldest_kept = self._times[-1] - WINDOW_MS
        while self._committed and self._committed[0].start_ms < oldest_kept:
            self._committed.popleft()

    def _update(self) -> None:
        times = np.array(self._times)
        known = list(self._beats)
        segments = segment_beats(times, np.array(self._colours), self._fs_hz)
        found = np.concatenate([np.empty(0), *(s.beats_ms for s in segments)])
        if known:
            found = found[found > known[-1] + SAME_BEAT_MS]
        stable_until_ms = float(times[-1]) - EDGE_MS
        labelled = label_intervals(
            np.array([*known, *found]),
            sample_times_ms=times,
            moving=np.array(self._moving),
            low_quality=np.array(self._low),
            stable_until_ms=stable_until_ms,
        )
        fresh = reject_region_disagreement(labelled[max(len(known) - 1, 0) :], segments)
        settled = [i for i in fresh if i.end_ms <= stable_until_ms]
        self._commit(settled)
        self._pending = fresh[len(settled) :]

    def _commit(self, settled: list[Interval]) -> None:
        for interval in settled:
            if not self._beats or self._beats[-1] != interval.start_ms:
                self._beats.append(interval.start_ms)
            self._beats.append(interval.end_ms)
            self._committed.append(interval)


@dataclass(frozen=True)
class SegmentBeats:
    first_ms: float
    last_ms: float
    beats_ms: NDArray[np.float64]
    region_beats_ms: tuple[NDArray[np.float64], ...]


def segment_beats(
    times: NDArray[np.float64], colours: NDArray[np.float64], fs_hz: float
) -> list[SegmentBeats]:
    breaks = np.flatnonzero(np.diff(times) > MAX_GAP_MS) + 1
    bounds = list(pairwise([0, *breaks.tolist(), times.size]))
    segments: list[SegmentBeats] = []
    for number, (first, stop) in enumerate(bounds):
        span = times[first:stop]
        if span[-1] - span[0] <= MIN_SEGMENT_MS:
            continue
        pulses = region_pulses(span, colours[first:stop], fs_hz)
        if pulses is None:
            continue
        grid, regions = pulses
        beats = detect_beats(grid, -regions.mean(axis=0), fs_hz)
        closed = number < len(bounds) - 1
        first_ms = float(span[0]) + EDGE_MS
        last_ms = float(span[-1]) - EDGE_MS if closed else math.inf
        segments.append(
            SegmentBeats(
                first_ms=first_ms,
                last_ms=last_ms,
                beats_ms=beats[(beats >= first_ms) & (beats <= last_ms)],
                region_beats_ms=tuple(detect_beats(grid, -r, fs_hz) for r in regions),
            )
        )
    return segments


def region_pulses(
    times: NDArray[np.float64], colours: NDArray[np.float64], fs_hz: float
) -> tuple[NDArray[np.float64], NDArray[np.float64]] | None:
    grid, rows = resample_uniform(times, colours, fs_hz)
    pulses = np.stack(
        [
            bandpass(pos_pulse(rgb, fs_hz, POS_WINDOW_S), fs_hz)
            for rgb in np.split(rows, REGION_COUNT, axis=1)
        ]
    )
    normalised = unit_variance(pulses)
    if normalised is None:
        return None
    return grid, normalised


def reject_region_disagreement(
    intervals: list[Interval], segments: Sequence[SegmentBeats]
) -> list[Interval]:
    starts = np.array([i.start_ms for i in intervals], dtype=np.float64)
    ends = np.array([i.end_ms for i in intervals], dtype=np.float64)
    spread = (beat_spreads(starts, segments) > SPREAD_LIMIT_MS) | (
        beat_spreads(ends, segments) > SPREAD_LIMIT_MS
    )
    return [
        replace(i, flag="low_quality") if i.accepted and wide else i
        for i, wide in zip(intervals, spread, strict=True)
    ]


def beat_spreads(
    beats_ms: NDArray[np.float64], segments: Sequence[SegmentBeats]
) -> NDArray[np.float64]:
    spreads = np.zeros(beats_ms.size)
    for segment in segments:
        inside = (beats_ms >= segment.first_ms) & (beats_ms <= segment.last_ms)
        offsets = [
            nearest_offsets(beats_ms[inside], region)
            for region in segment.region_beats_ms
        ]
        spreads[inside] = np.std(offsets, axis=0)
    return spreads


def nearest_offsets(
    beats_ms: NDArray[np.float64], candidates_ms: NDArray[np.float64]
) -> NDArray[np.float64]:
    padded = np.concatenate(([-np.inf], candidates_ms, [np.inf]))
    after = np.searchsorted(padded, beats_ms)
    later = padded[after] - beats_ms
    earlier = padded[after - 1] - beats_ms
    nearest = np.where(later < -earlier, later, earlier)
    return np.clip(nearest, -MAX_IBI_MS, MAX_IBI_MS)
