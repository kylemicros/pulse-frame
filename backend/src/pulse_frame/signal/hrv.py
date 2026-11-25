import math
from collections import defaultdict, deque
from collections.abc import Sequence
from dataclasses import dataclass, replace
from itertools import pairwise

import numpy as np
from numpy.typing import NDArray
from scipy import stats

from pulse_frame.signal.beats import (
    REJECTION_ORDER,
    SNR_FLOOR_DB,
    Interval,
    IntervalFlag,
    cross_region_snr_db,
    label_intervals,
    near_flagged_sample,
    rate_band,
    rate_guided_beats,
)
from pulse_frame.signal.checks import (
    check_region_colour,
    check_sample_rate,
    check_timestamp,
    check_tracker_sample_rate,
)
from pulse_frame.signal.cross import (
    band_peak_index,
    estimate_cross_rate,
    parabolic_peak_hz,
    region_spectra,
    unit_variance,
)
from pulse_frame.signal.filters import PASS_HIGH_HZ, PASS_LOW_HZ, bandpass
from pulse_frame.signal.pos import pos_pulse
from pulse_frame.signal.resample import resample_uniform
from pulse_frame.signal.spectrum import MAIN_LOBE_BINS, SEARCH_LOW_HZ
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
BLOCK_MS = 25_000.0
MIN_BLOCK_RUNS = 8
MIN_ALTERNATION_MS = 5.0
ALTERNATION_ALPHA = 0.002
JITTER_DF_DIVISOR = 2.5
PAIRED_VARIANCE_SCALE = 64.0 / 70.0
MIN_SEGMENT_MS = 10_000.0
MIN_REGION_CORRELATION = 0.5
MIN_KEPT_REGIONS = 2
FALLBACK_LOW_HZ = 0.55
FALLBACK_HIGH_HZ = 3.5
HALF_RATE_SHARE = 0.2
PLAUSIBLE_PERIOD_SHARES = (0.6, 1.4)
READING_FLOOR_DB = 3.0
OUTRANKED_BY_LOW_QUALITY: frozenset[IntervalFlag] = frozenset(
    ("ok", *REJECTION_ORDER[REJECTION_ORDER.index("low_quality") + 1 :])
)


@dataclass(frozen=True)
class HrvReading:
    rmssd_ms: float | None
    sdnn_ms: float | None
    window_ms: float | None = None
    accepted_count: int | None = None


NO_HRV = HrvReading(rmssd_ms=None, sdnn_ms=None)


@dataclass(frozen=True)
class WindowCheck:
    t_ms: float
    snr_db: float

    @property
    def under_floor(self) -> bool:
        return self.snr_db < SNR_FLOOR_DB

    @property
    def measured(self) -> bool:
        return math.isfinite(self.snr_db)


def clears_reading_floor(checks: Sequence[WindowCheck]) -> bool:
    if not checks:
        return False
    return float(np.median([check.snr_db for check in checks])) >= READING_FLOOR_DB


def checks_between(
    checks: Sequence[WindowCheck], first_ms: float, last_ms: float
) -> list[WindowCheck]:
    return [check for check in checks if first_ms <= check.t_ms <= last_ms]


def hrv_reading(
    intervals: Sequence[Interval],
    newest_sample_ms: float | None = None,
    window_checks: Sequence[WindowCheck] | None = None,
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
    if window_checks is not None and not clears_reading_floor(
        checks_between(window_checks, min(i.start_ms for i in window), newest_ms)
    ):
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


def numbered_runs(
    window: Sequence[Interval], length: int
) -> list[tuple[int, Sequence[Interval]]]:
    return [
        (k, run)
        for k, run in (
            (k, window[k : k + length]) for k in range(len(window) - length + 1)
        )
        if all(i.accepted for i in run)
        and all(a.end_ms == b.start_ms for a, b in pairwise(run))
    ]


def accepted_runs(window: Sequence[Interval], length: int) -> list[Sequence[Interval]]:
    return [run for _, run in numbered_runs(window, length)]


def run_ibis(runs: Sequence[Sequence[Interval]], length: int) -> NDArray[np.float64]:
    ibis = [[i.ibi_ms for i in run] for run in runs]
    return np.array(ibis, dtype=np.float64).reshape(-1, length)


def touching_runs(window: Sequence[Interval], length: int) -> NDArray[np.float64]:
    return run_ibis(accepted_runs(window, length), length)


def alternates(window: Sequence[Interval]) -> bool:
    newest_end_ms = max(i.end_ms for i in window)
    blocks: defaultdict[int, list[tuple[int, Sequence[Interval]]]] = defaultdict(list)
    for k, run in numbered_runs(window, 3):
        blocks[int((newest_end_ms - run[-1].end_ms) // BLOCK_MS)].append((k, run))
    return any(
        swings_back_and_forth(
            np.array([k for k, _ in runs]), run_ibis([run for _, run in runs], 3)
        )
        for runs in blocks.values()
    )


def swings_back_and_forth(starts: NDArray[np.int_], ibis: NDArray[np.float64]) -> bool:
    if starts.size < MIN_BLOCK_RUNS:
        return False
    values = alternation_values(starts, ibis)
    size = abs(float(values.mean()))
    return size >= MIN_ALTERNATION_MS and size >= significance_limit(
        values.size
    ) * alternation_error(values)


def alternation_values(
    starts: NDArray[np.int_], ibis: NDArray[np.float64]
) -> NDArray[np.float64]:
    signs = np.where(starts % 2 == 0, 1.0, -1.0)
    return signs * (ibis[:, 0] - 2.0 * ibis[:, 1] + ibis[:, 2]) / 4.0


def alternation_error(values: NDArray[np.float64]) -> float:
    paired = values[:-1] + values[1:]
    variance = PAIRED_VARIANCE_SCALE * float(np.var(paired, ddof=1))
    return math.sqrt(variance / values.size)


def significance_limit(run_count: int) -> float:
    degrees = (run_count - 1) / JITTER_DF_DIVISOR
    return float(stats.t.ppf(1.0 - ALTERNATION_ALPHA / 2.0, degrees))


def too_many_rejected(window: Sequence[Interval], accepted_count: int) -> bool:
    settled = sum(1 for i in window if i.flag != "edge")
    return (settled - accepted_count) / settled > MAX_REJECTED_SHARE


def is_stale(window: Sequence[Interval], newest_ms: float) -> bool:
    ends = [i.end_ms for i in window if i.accepted]
    return not ends or newest_ms - max(ends) > STALE_MS


@dataclass(frozen=True)
class SegmentBeats:
    first_ms: float
    last_ms: float
    beats_ms: NDArray[np.float64]
    period_ms: float
    snr_db: float

    @property
    def is_open(self) -> bool:
        return math.isinf(self.last_ms)


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
        self._checks: deque[WindowCheck] = deque()
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

    def mark_newest_low_quality(self) -> None:
        if not self._low:
            return
        self._low[-1] = True
        newest_ms = self._times[-1]
        self._pending = low_quality_near(self._pending, newest_ms)

    def intervals(self) -> list[Interval]:
        return [*self._committed, *self._pending]

    def settled_intervals(self) -> list[Interval]:
        return list(self._committed)

    def window_checks(self) -> list[WindowCheck]:
        return list(self._checks)

    def reading(self) -> HrvReading:
        newest_ms = self._times[-1] if self._times else None
        return hrv_reading(self.intervals(), newest_ms, self.window_checks())

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
        while self._checks and self._checks[0].t_ms < oldest_kept:
            self._checks.popleft()

    def _update(self) -> None:
        times = np.array(self._times)
        known = list(self._beats)
        segments = segment_beats(times, np.array(self._colours), self._fs_hz)
        self._record_checks(float(times[-1]), segments)
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
        fresh = flag_implausible(labelled[max(len(known) - 1, 0) :], segments)
        settled = [i for i in fresh if i.end_ms <= stable_until_ms]
        self._commit(settled)
        self._pending = fresh[len(settled) :]

    def _record_checks(self, newest_ms: float, segments: list[SegmentBeats]) -> None:
        for segment in segments:
            if segment.is_open:
                self._checks.append(WindowCheck(t_ms=newest_ms, snr_db=segment.snr_db))

    def _commit(self, settled: list[Interval]) -> None:
        for interval in settled:
            if not self._beats or self._beats[-1] != interval.start_ms:
                self._beats.append(interval.start_ms)
            self._beats.append(interval.end_ms)
            self._committed.append(interval)


def low_quality_near(intervals: list[Interval], sample_ms: float) -> list[Interval]:
    if not intervals:
        return []
    near = near_flagged_sample(
        np.array([i.start_ms for i in intervals]),
        np.array([i.end_ms for i in intervals]),
        np.array([sample_ms]),
    )
    return [
        replace(i, flag="low_quality")
        if hit and i.flag in OUTRANKED_BY_LOW_QUALITY
        else i
        for i, hit in zip(intervals, near.tolist(), strict=True)
    ]


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
        agreeing = agreeing_regions(regions, beat_rate_hz(regions, fs_hz), fs_hz)
        rate_hz = beat_rate_hz(agreeing, fs_hz)
        snr_db = cross_region_snr_db(agreeing, rate_hz, fs_hz)
        beats = (
            rate_guided_beats(grid, agreeing.mean(axis=0), rate_hz, fs_hz)
            if snr_db >= SNR_FLOOR_DB
            else np.empty(0)
        )
        closed = number < len(bounds) - 1
        first_ms = float(span[0]) + EDGE_MS
        last_ms = float(span[-1]) - EDGE_MS if closed else math.inf
        segments.append(
            SegmentBeats(
                first_ms=first_ms,
                last_ms=last_ms,
                beats_ms=beats[(beats >= first_ms) & (beats <= last_ms)],
                period_ms=1000.0 / rate_hz,
                snr_db=snr_db,
            )
        )
    return segments


def agreeing_regions(
    regions: NDArray[np.float64], rate_hz: float, fs_hz: float = 30.0
) -> NDArray[np.float64]:
    banded = np.stack([rate_band(region, rate_hz, fs_hz) for region in regions])
    agrees = np.array(
        [
            correlation(region, np.delete(banded, index, axis=0).mean(axis=0))
            >= MIN_REGION_CORRELATION
            for index, region in enumerate(banded)
        ]
    )
    if np.count_nonzero(agrees) < MIN_KEPT_REGIONS:
        return regions
    return regions[agrees]


def correlation(first: NDArray[np.float64], second: NDArray[np.float64]) -> float:
    with np.errstate(invalid="ignore", divide="ignore"):
        return float(np.corrcoef(first, second)[0, 1])


def beat_rate_hz(regions: NDArray[np.float64], fs_hz: float) -> float:
    fallback_hz = spectral_rate_hz(regions.mean(axis=0), fs_hz)
    estimate = estimate_cross_rate(regions, fs_hz)
    if estimate is None:
        return fallback_hz
    if fallback_hz < SEARCH_LOW_HZ and estimate.flank:
        return fallback_hz
    return estimate.bpm / 60.0


def spectral_rate_hz(pulse: NDArray[np.float64], fs_hz: float) -> float:
    freqs, spectra = region_spectra(pulse[None, :], fs_hz)
    power = np.abs(spectra[0]) ** 2
    band = (freqs >= FALLBACK_LOW_HZ) & (freqs <= FALLBACK_HIGH_HZ)
    peak = band_peak_index(power, band)
    half_width_hz = MAIN_LOBE_BINS * fs_hz / pulse.size
    near_half = band & (np.abs(freqs - freqs[peak] / 2.0) <= half_width_hz)
    if near_half.any() and power[near_half].max() >= HALF_RATE_SHARE * power[peak]:
        peak = band_peak_index(power, near_half)
    return parabolic_peak_hz(freqs, power, peak)


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


def flag_implausible(
    intervals: list[Interval], segments: Sequence[SegmentBeats]
) -> list[Interval]:
    return [
        replace(i, flag="low_quality")
        if i.accepted and not is_plausible(i, segments)
        else i
        for i in intervals
    ]


def is_plausible(interval: Interval, segments: Sequence[SegmentBeats]) -> bool:
    shortest, longest = PLAUSIBLE_PERIOD_SHARES
    for segment in segments:
        if segment.first_ms <= interval.end_ms <= segment.last_ms:
            period_ms = segment.period_ms
            return shortest * period_ms <= interval.ibi_ms <= longest * period_ms
    return True
