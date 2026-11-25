import math
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

import numpy as np
from numpy.typing import NDArray

from pulse_frame.signal.beats import Interval
from pulse_frame.signal.hrv import (
    READING_FLOOR_DB,
    HrvReading,
    HrvTracker,
    WindowCheck,
    alternates,
    checks_between,
    clears_reading_floor,
    hrv_reading,
    is_stale,
    newest_window,
    too_many_rejected,
)
from pulse_frame.signal.spectrum import SEARCH_LOW_HZ

type NoReadingCode = Literal["SIGNAL_TOO_WEAK", "READING_FLOOR_NOT_CLEARED"]
type NoReadingWhy = Literal["face_left_view", "faint_pulse"]

SAMPLE_HOLE_MS = 100.0
SUMMARY_SPAN_MS = 60_000.0
SUMMARY_MIN_ACCEPTED_MS = 45_000.0
MIN_MINUTE_INTERVALS = 2
WEAK_WINDOW_SHARE = 0.5
MS_PER_MINUTE = 60_000.0
MIN_MINUTE_BPM = SEARCH_LOW_HZ * 60.0


@dataclass(frozen=True)
class Summary:
    bpm: float | None
    rmssd_ms: float | None
    sdnn_ms: float | None
    count: int
    accepted_percent: float | None
    sdnn_minutes: tuple[int, ...] = ()


@dataclass(frozen=True)
class NoReading:
    code: NoReadingCode
    why: NoReadingWhy | None
    clear_percent: float | None


@dataclass(frozen=True)
class EarlierIntervals:
    settled: int
    accepted: int


NO_EARLIER = EarlierIntervals(settled=0, accepted=0)
NO_SUMMARY = Summary(
    bpm=None, rmssd_ms=None, sdnn_ms=None, count=0, accepted_percent=None
)
TOO_WEAK = NoReading(code="SIGNAL_TOO_WEAK", why=None, clear_percent=None)
FACE_LEFT_VIEW = NoReading(
    code="READING_FLOOR_NOT_CLEARED", why="face_left_view", clear_percent=None
)


def beside_holes(times_ms: Sequence[float]) -> NDArray[np.bool_]:
    times = np.asarray(times_ms, dtype=np.float64)
    holes = np.diff(times) > SAMPLE_HOLE_MS
    low = np.zeros(times.size, dtype=np.bool_)
    low[:-1] |= holes
    low[1:] |= holes
    return low


def counted_intervals(
    intervals: Sequence[Interval], counted_ms: float
) -> list[Interval]:
    return [i for i in intervals if i.start_ms >= counted_ms]


def counted_checks(
    checks: Sequence[WindowCheck], counted_ms: float
) -> list[WindowCheck]:
    return [check for check in checks if check.t_ms >= counted_ms]


def newest_span(intervals: Sequence[Interval], newest_ms: float) -> list[Interval]:
    oldest_ms = newest_ms - SUMMARY_SPAN_MS
    return [i for i in intervals if oldest_ms <= round(i.end_ms) <= newest_ms]


def summarise(
    intervals: Sequence[Interval],
    newest_ms: float,
    window_checks: Sequence[WindowCheck],
    earlier: EarlierIntervals = NO_EARLIER,
) -> Summary:
    span = newest_span(intervals, newest_ms)
    accepted = np.array([i.ibi_ms for i in span if i.accepted], dtype=np.float64)
    share = accepted_percent(intervals, earlier)
    bpm = (
        minute_bpm(accepted)
        if accepted.sum() >= SUMMARY_MIN_ACCEPTED_MS
        and passes_gates(span, int(accepted.size), newest_ms)
        else None
    )
    if bpm is None:
        return Summary(
            bpm=None,
            rmssd_ms=None,
            sdnn_ms=None,
            count=int(accepted.size),
            accepted_percent=share,
        )
    reading = hrv_reading(intervals, newest_ms, window_checks)
    sdnns = {} if reading.sdnn_ms is None else minute_sdnns(intervals, newest_ms)
    return Summary(
        bpm=bpm,
        rmssd_ms=reading.rmssd_ms,
        sdnn_ms=mean_sdnn(sdnns),
        count=int(accepted.size),
        accepted_percent=share,
        sdnn_minutes=tuple(sorted(sdnns)),
    )


def minute_bpm(accepted_ibis_ms: NDArray[np.float64]) -> float | None:
    bpm = float(MS_PER_MINUTE / accepted_ibis_ms.mean())
    return None if bpm < MIN_MINUTE_BPM else bpm


def counted_reading(
    tracker: HrvTracker, newest_ms: float, counted_ms: float
) -> HrvReading:
    return hrv_reading(
        counted_intervals(tracker.intervals(), counted_ms),
        newest_ms,
        tracker.window_checks(),
    )


def mean_sdnn(sdnns: dict[int, float]) -> float | None:
    return float(np.mean(list(sdnns.values()))) if sdnns else None


def minute_sdnns(intervals: Sequence[Interval], newest_ms: float) -> dict[int, float]:
    minutes: defaultdict[int, list[float]] = defaultdict(list)
    for interval in newest_window(intervals, newest_ms):
        if interval.accepted:
            minute = int((newest_ms - interval.end_ms) // SUMMARY_SPAN_MS)
            minutes[minute].append(interval.ibi_ms)
    return {
        minute: float(np.std(ibis, ddof=1))
        for minute, ibis in minutes.items()
        if len(ibis) >= MIN_MINUTE_INTERVALS and sum(ibis) >= SUMMARY_MIN_ACCEPTED_MS
    }


def passes_gates(
    span: Sequence[Interval], accepted_count: int, newest_ms: float
) -> bool:
    return not (
        alternates(span)
        or too_many_rejected(span, accepted_count)
        or is_stale(span, newest_ms)
    )


def accepted_percent(
    intervals: Sequence[Interval], earlier: EarlierIntervals = NO_EARLIER
) -> float | None:
    total = added(earlier, tally(intervals))
    if total.settled == 0:
        return None
    return 100.0 * total.accepted / total.settled


def tally(intervals: Sequence[Interval]) -> EarlierIntervals:
    return EarlierIntervals(
        settled=sum(1 for i in intervals if i.flag != "edge"),
        accepted=sum(1 for i in intervals if i.accepted),
    )


def added(first: EarlierIntervals, second: EarlierIntervals) -> EarlierIntervals:
    return EarlierIntervals(
        settled=first.settled + second.settled,
        accepted=first.accepted + second.accepted,
    )


def newest_minute_checks(
    checks: Sequence[WindowCheck], newest_ms: float
) -> list[WindowCheck]:
    return checks_between(checks, newest_ms - SUMMARY_SPAN_MS, newest_ms)


def measured_under_floor(checks: Sequence[WindowCheck]) -> int:
    return sum(1 for check in checks if check.measured and check.under_floor)


def is_too_weak(checks: Sequence[WindowCheck]) -> bool:
    under = measured_under_floor(checks)
    return bool(checks) and under > WEAK_WINDOW_SHARE * len(checks)


def is_unmeasured(check: WindowCheck) -> bool:
    return math.isnan(check.snr_db) or check.snr_db == -math.inf


def is_measured_under_reading_floor(check: WindowCheck) -> bool:
    return check.measured and check.snr_db < READING_FLOOR_DB


def face_left_view(checks: Sequence[WindowCheck]) -> bool:
    unmeasured = sum(1 for check in checks if is_unmeasured(check))
    under = sum(1 for check in checks if is_measured_under_reading_floor(check))
    return unmeasured > under


def clear_percent(checks: Sequence[WindowCheck]) -> float:
    clear = sum(1 for check in checks if check.snr_db >= READING_FLOOR_DB)
    return 100.0 * clear / len(checks)


def too_weak_decision(
    result: Summary, checks: Sequence[WindowCheck], newest_ms: float
) -> NoReading | None:
    if result.count > 0 or not is_too_weak(newest_minute_checks(checks, newest_ms)):
        return None
    return TOO_WEAK


def floor_decision(
    result: Summary, checks: Sequence[WindowCheck], had_reading: bool
) -> NoReading | None:
    if (
        had_reading
        or result.rmssd_ms is not None
        or not checks
        or clears_reading_floor(checks)
    ):
        return None
    if face_left_view(checks):
        return FACE_LEFT_VIEW
    return NoReading(
        code="READING_FLOOR_NOT_CLEARED",
        why="faint_pulse",
        clear_percent=clear_percent(checks),
    )


def decide_no_reading(
    result: Summary,
    checks: Sequence[WindowCheck],
    newest_ms: float,
    had_reading: bool,
) -> NoReading | None:
    weak = too_weak_decision(result, checks, newest_ms)
    if weak is not None:
        return weak
    return floor_decision(result, checks, had_reading)
