import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

import numpy as np

from pulse_frame.signal.beats import REJECTION_ORDER, Interval, IntervalFlag
from pulse_frame.signal.hrv import (
    MIN_ACCEPTED_MS,
    WindowCheck,
    alternates,
    checks_between,
    clears_reading_floor,
    is_stale,
    newest_window,
    too_many_rejected,
    touching_runs,
)
from pulse_frame.signal.live import LiveHrv
from pulse_frame.signal.summary import (
    SAMPLE_HOLE_MS,
    SUMMARY_MIN_ACCEPTED_MS,
    SUMMARY_SPAN_MS,
    NoReading,
    clear_percent,
    counted_checks,
    counted_intervals,
    is_unmeasured,
    measured_under_floor,
    newest_minute_checks,
    newest_span,
)

type Gate = Literal["unchecked", "alternates", "too_many_rejected", "stale", "none"]
type HrvGate = Literal[
    "unchecked",
    "stale",
    "too_many_rejected",
    "too_short",
    "no_successive",
    "alternates",
    "floor",
    "none",
]

LINE_INTERVAL_MS = 1000
STEP_PERCENTILES = (50, 95)
CLOSE_STEP = 10.0
SHARE_FLAGS: tuple[IntervalFlag, ...] = tuple(
    flag for flag in REJECTION_ORDER if flag != "edge"
)
SIGNAL_FIELDS = (
    "snr_db",
    "snr_age_ms",
    "checks",
    "under_floor_share",
    "clear_share",
    "unmeasured_share",
    "median_snr_db",
    "code",
    "bpm_shown",
    "had_reading",
    "gate",
    "hrv_gate",
)
FRAME_FIELDS = (
    "sample_frames",
    "moving_frames",
    "gaps_over_100ms",
    "step_p50_ms",
    "step_p95_ms",
    "fps",
)
CLOSE_FIELDS = (
    "accepted_share",
    *(f"rejected_share_{flag}" for flag in SHARE_FLAGS),
)
FIELDS = (*SIGNAL_FIELDS, *FRAME_FIELDS)
BEAT_SIGNAL_FORMAT = " ".join(("event=beat_signal", *(f"{name}=%s" for name in FIELDS)))
BEAT_SIGNAL_CLOSE_FORMAT = " ".join(
    ("event=beat_signal_close", *(f"{name}=%s" for name in CLOSE_FIELDS))
)


@dataclass(frozen=True)
class FramePace:
    steps_ms: tuple[int, ...]
    elapsed_ms: int
    sample_frames: int
    moving_frames: int

    @property
    def gaps(self) -> int:
        return sum(step > SAMPLE_HOLE_MS for step in self.steps_ms)

    @property
    def fps(self) -> float:
        return len(self.steps_ms) * 1000.0 / self.elapsed_ms

    def step_percentiles(self) -> tuple[float, float]:
        low, high = np.percentile(self.steps_ms, STEP_PERCENTILES)
        return float(low), float(high)


class FramePacer:
    def __init__(self) -> None:
        self._line_ms: int | None = None
        self._previous_ms: int | None = None
        self._steps: list[int] = []
        self._samples = 0
        self._moving = 0

    def add(self, timestamp_ms: int, sampled: bool, moving: bool) -> FramePace | None:
        if self._line_ms is None or self._previous_ms is None:
            self._line_ms = self._previous_ms = timestamp_ms
            return None
        self._steps.append(timestamp_ms - self._previous_ms)
        self._samples += sampled
        self._moving += moving
        self._previous_ms = timestamp_ms
        elapsed_ms = timestamp_ms - self._line_ms
        if elapsed_ms < LINE_INTERVAL_MS:
            return None
        pace = FramePace(tuple(self._steps), elapsed_ms, self._samples, self._moving)
        self._line_ms = timestamp_ms
        self._steps = []
        self._samples = 0
        self._moving = 0
        return pace


def number(value: float, places: int) -> str:
    return f"{value:.{places}f}"


def flag_word(value: bool) -> str:
    return str(int(value))


def share(part: int, whole: int) -> float:
    return math.nan if whole == 0 else 100.0 * part / whole


def to_tens(value: float) -> float:
    return value if math.isnan(value) else CLOSE_STEP * round(value / CLOSE_STEP)


def counted_of(
    intervals: Sequence[Interval], counted_ms: float | None
) -> list[Interval]:
    return [] if counted_ms is None else counted_intervals(intervals, counted_ms)


def counted_checks_of(
    checks: Sequence[WindowCheck], counted_ms: float | None
) -> list[WindowCheck]:
    return [] if counted_ms is None else counted_checks(checks, counted_ms)


def bpm_gate(minute: Sequence[Interval], newest_ms: float) -> Gate:
    accepted = [interval for interval in minute if interval.accepted]
    if sum(interval.ibi_ms for interval in accepted) < SUMMARY_MIN_ACCEPTED_MS:
        return "unchecked"
    if alternates(minute):
        return "alternates"
    if too_many_rejected(minute, len(accepted)):
        return "too_many_rejected"
    if is_stale(minute, newest_ms):
        return "stale"
    return "none"


def hrv_gate(
    counted: Sequence[Interval], checks: Sequence[WindowCheck], newest_ms: float
) -> HrvGate:
    if not counted:
        return "unchecked"
    window = newest_window(counted, newest_ms)
    accepted = [interval.ibi_ms for interval in window if interval.accepted]
    if is_stale(window, newest_ms):
        return "stale"
    if too_many_rejected(window, len(accepted)):
        return "too_many_rejected"
    if len(accepted) < 2 or sum(accepted) < MIN_ACCEPTED_MS:
        return "too_short"
    if touching_runs(window, 2).size == 0:
        return "no_successive"
    if alternates(window):
        return "alternates"
    first_ms = min(interval.start_ms for interval in window)
    if not clears_reading_floor(checks_between(checks, first_ms, newest_ms)):
        return "floor"
    return "none"


def newest_check_fields(
    checks: Sequence[WindowCheck], newest_ms: float
) -> dict[str, str]:
    if not checks:
        return {"snr_db": number(math.nan, 2), "snr_age_ms": number(math.nan, 1)}
    newest = checks[-1]
    return {
        "snr_db": number(newest.snr_db, 2),
        "snr_age_ms": number(newest_ms - newest.t_ms, 1),
    }


def check_fields(
    counted: Sequence[WindowCheck], minute: Sequence[WindowCheck]
) -> dict[str, str]:
    unmeasured = sum(is_unmeasured(check) for check in counted)
    snrs = [check.snr_db for check in counted]
    return {
        "checks": str(len(minute)),
        "under_floor_share": number(
            share(measured_under_floor(minute), len(minute)), 2
        ),
        "clear_share": number(clear_percent(counted) if counted else math.nan, 2),
        "unmeasured_share": number(share(unmeasured, len(counted)), 2),
        "median_snr_db": number(float(np.median(snrs)) if snrs else math.nan, 2),
    }


def decision_fields(
    no_reading: NoReading | None, bpm_shown: bool, had_reading: bool
) -> dict[str, str]:
    return {
        "code": "none" if no_reading is None else no_reading.code,
        "bpm_shown": flag_word(bpm_shown),
        "had_reading": flag_word(had_reading),
    }


def signal_fields(
    intervals: Sequence[Interval],
    checks: Sequence[WindowCheck],
    newest_ms: float,
    counted_ms: float | None,
    *,
    no_reading: NoReading | None,
    bpm_shown: bool,
    had_reading: bool,
) -> dict[str, str]:
    counted = counted_of(intervals, counted_ms)
    counted_window_checks = counted_checks_of(checks, counted_ms)
    fields = {
        **newest_check_fields(checks, newest_ms),
        **check_fields(
            counted_window_checks,
            newest_minute_checks(counted_window_checks, newest_ms),
        ),
        **decision_fields(no_reading, bpm_shown, had_reading),
        "gate": bpm_gate(newest_span(counted, newest_ms), newest_ms),
        "hrv_gate": hrv_gate(counted, checks, newest_ms),
    }
    return {name: fields[name] for name in SIGNAL_FIELDS}


def close_fields(
    intervals: Sequence[Interval], newest_ms: float, counted_ms: float | None
) -> dict[str, str] | None:
    if counted_ms is None or newest_ms - counted_ms < SUMMARY_SPAN_MS:
        return None
    counted = counted_intervals(intervals, counted_ms)
    settled = [interval for interval in counted if interval.flag != "edge"]
    shares = {
        "accepted_share": share(
            sum(interval.accepted for interval in settled), len(settled)
        ),
        **{
            f"rejected_share_{flag}": share(
                sum(interval.flag == flag for interval in settled), len(settled)
            )
            for flag in SHARE_FLAGS
        },
    }
    return {name: number(to_tens(shares[name]), 0) for name in CLOSE_FIELDS}


def frame_fields(pace: FramePace) -> dict[str, str]:
    p50_ms, p95_ms = pace.step_percentiles()
    return {
        "sample_frames": str(pace.sample_frames),
        "moving_frames": str(pace.moving_frames),
        "gaps_over_100ms": str(pace.gaps),
        "step_p50_ms": number(p50_ms, 1),
        "step_p95_ms": number(p95_ms, 1),
        "fps": number(pace.fps, 2),
    }


def second_line_args(pace: FramePace, live: LiveHrv, frame_ms: int) -> tuple[str, ...]:
    newest_ms = live.newest_ms
    fields = {
        **signal_fields(
            live.intervals(),
            live.window_checks(),
            frame_ms if newest_ms is None else newest_ms,
            live.counted_from_ms,
            no_reading=live.no_reading(),
            bpm_shown=live.summary().bpm is not None,
            had_reading=live.had_reading,
        ),
        **frame_fields(pace),
    }
    return tuple(fields[name] for name in FIELDS)


def close_line_args(live: LiveHrv) -> tuple[str, ...] | None:
    newest_ms = live.newest_ms
    if newest_ms is None:
        return None
    fields = close_fields(live.intervals(), newest_ms, live.counted_from_ms)
    if fields is None:
        return None
    return tuple(fields[name] for name in CLOSE_FIELDS)
