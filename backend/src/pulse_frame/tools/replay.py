import argparse
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from pulse_frame.platform.errors import SandboxError
from pulse_frame.platform.sandbox import apply_loopback_sandbox
from pulse_frame.signal.beats import (
    MIN_SNR_CYCLES,
    SNR_FLOOR_DB,
    Interval,
    IntervalFlag,
)
from pulse_frame.signal.errors import SignalError
from pulse_frame.signal.hrv import (
    WINDOW_MS,
    HrvReading,
    HrvTracker,
    WindowCheck,
    alternates,
    checks_between,
    hrv_reading,
    is_stale,
    newest_window,
    too_many_rejected,
)
from pulse_frame.signal.tracker import UPDATE_INTERVAL_MS, RegionColours
from pulse_frame.store.errors import StoreError
from pulse_frame.store.recording import (
    FrameSample,
    HrvRow,
    IntervalRow,
    frame_samples,
    replace_replay,
)
from pulse_frame.store.sessions import SESSIONS_COMMAND
from pulse_frame.tools.sessions import (
    INTERRUPTED_EXIT,
    report,
    report_sandbox,
    write_out,
)

REPLAY_COMMAND = "uv run python -m pulse_frame.tools.replay"
CAPTURE_COMMAND = "uv run python -m pulse_frame.tools.capture"
FLAG_CODES: dict[IntervalFlag, int] = {
    "ok": 0,
    "motion": 1,
    "gap": 2,
    "low_quality": 3,
    "edge": 4,
    "out_of_range": 5,
    "off_median": 6,
}
SAMPLE_HOLE_MS = 100.0
SUMMARY_SPAN_MS = 60_000.0
SUMMARY_MIN_ACCEPTED_MS = 45_000.0
MIN_MINUTE_INTERVALS = 2
HRV_WINDOW_LABEL = f"last {round(WINDOW_MS / 60_000.0)} minutes"
UNSET = "-"
WEAK_WINDOW_SHARE = 0.5
WEAK_SIGNAL_ACTION = (
    "Light the face evenly and brightly, for example facing a window or a lamp,"
    " keep still, and turn off the camera's auto exposure if it has that"
    f" setting, then record a new session with `{CAPTURE_COMMAND}`."
)
SANDBOX_FAILED_ACTION = (
    "Outbound network could not be limited to this machine, so the store was"
    " not opened and nothing was read or written. Check that this is macOS with"
    " /usr/lib/libSystem.B.dylib present, then run the replay again; if a macOS"
    " update broke sandbox_init, report the code."
)


@dataclass(frozen=True)
class ReplayResult:
    intervals: list[Interval]
    readings: list[HrvRow]
    newest_ms: int
    window_checks: list[WindowCheck]


@dataclass(frozen=True)
class Summary:
    bpm: float | None
    rmssd_ms: float | None
    sdnn_ms: float | None
    count: int
    accepted_percent: float | None


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog=REPLAY_COMMAND,
        description=(
            "Replay one stored session's frame samples through the HRV tracker,"
            " replace its beats, intervals and HRV readings in the local store,"
            " and print per-session aggregates only: BPM and its accepted interval"
            " count over the newest minute, RMSSD and SDNN over the"
            f" {HRV_WINDOW_LABEL}, and the accepted share of intervals."
        ),
    )
    parser.add_argument("session_id", type=int, help="the ID printed by the capture")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        report_sandbox(apply_loopback_sandbox())
        return replay(args.session_id)
    except SandboxError as error:
        report(error.code, error.message, SANDBOX_FAILED_ACTION)
        return 1
    except (SignalError, StoreError) as error:
        report(error.code, error.message, error.action)
        return 1
    except KeyboardInterrupt:
        report(
            "REPLAY_INTERRUPTED",
            f"Stopped by Ctrl-C during the replay of session {args.session_id}."
            " The replay writes in one transaction, so the session keeps its"
            " earlier beats, intervals and HRV readings unless the write had"
            " already committed.",
            f"Run `{REPLAY_COMMAND} {args.session_id}` in backend/ again.",
        )
        return INTERRUPTED_EXIT


def replay(session_id: int) -> int:
    samples = frame_samples(session_id)
    if not samples:
        report(
            "NO_FRAME_SAMPLES",
            f"Session {session_id} holds no frame samples, so there is nothing to"
            " replay and nothing was written. The capture saw no usable face, or"
            " stopped before its first write.",
            f"Delete the empty session with `{SESSIONS_COMMAND} delete"
            f" {session_id}` in backend/ if you no longer need it, then record a"
            f" new one with `{CAPTURE_COMMAND}`.",
        )
        return 1
    result = replay_samples(samples)
    replace_replay(
        session_id,
        beat_times(result.intervals),
        [interval_row(interval) for interval in result.intervals],
        result.readings,
    )
    summary = summarise(result)
    write_out(summary_line(session_id, summary))
    notice = weak_notice(result, summary)
    if notice is not None:
        report("SIGNAL_TOO_WEAK", notice, WEAK_SIGNAL_ACTION)
    return 0


def weak_notice(result: ReplayResult, summary: Summary) -> str | None:
    checks = newest_checks(result)
    if summary.count > 0 or not is_too_weak(checks):
        return None
    return weak_signal_message(checks)


def newest_checks(result: ReplayResult) -> list[WindowCheck]:
    return checks_between(
        result.window_checks, result.newest_ms - SUMMARY_SPAN_MS, result.newest_ms
    )


def measured_under_floor(checks: Sequence[WindowCheck]) -> int:
    return sum(1 for check in checks if check.measured and check.under_floor)


def is_too_weak(checks: Sequence[WindowCheck]) -> bool:
    under = measured_under_floor(checks)
    return bool(checks) and under > WEAK_WINDOW_SHARE * len(checks)


def weak_signal_message(checks: Sequence[WindowCheck]) -> str:
    under = measured_under_floor(checks)
    measured = [check.snr_db for check in checks if check.measured]
    unmeasured = len(checks) - len(measured)
    median = f", median {float(np.median(measured)):.1f} dB" if measured else ""
    skipped = (
        f" {unmeasured} were not measured, being too short to hold"
        f" {MIN_SNR_CYCLES} beats."
        if unmeasured
        else ""
    )
    return (
        f"The newest minute has no accepted beat: {under} of {len(checks)} analysis"
        f" windows were under the pulse quality floor of {SNR_FLOOR_DB:g} dB"
        f"{median}.{skipped} The pulse in the face colour did not repeat clearly"
        " enough across the face regions to time beats."
    )


def region_colours(sample: FrameSample) -> RegionColours:
    return RegionColours(
        forehead=sample.forehead,
        left_cheek=sample.left_cheek,
        right_cheek=sample.right_cheek,
    )


def beside_holes(samples: Sequence[FrameSample]) -> NDArray[np.bool_]:
    times = np.array([sample.t_ms for sample in samples], dtype=np.float64)
    holes = np.diff(times) > SAMPLE_HOLE_MS
    low = np.zeros(times.size, dtype=np.bool_)
    low[:-1] |= holes
    low[1:] |= holes
    return low


def replay_samples(samples: Sequence[FrameSample]) -> ReplayResult:
    tracker = HrvTracker()
    settled: dict[float, Interval] = {}
    readings: list[HrvRow] = []
    next_update_ms: float | None = None
    for sample, low_quality in zip(samples, beside_holes(samples), strict=True):
        tracker.add(
            sample.t_ms,
            region_colours(sample),
            moving=sample.moving,
            low_quality=bool(low_quality),
        )
        if next_update_ms is None:
            next_update_ms = sample.t_ms + UPDATE_INTERVAL_MS
        elif sample.t_ms >= next_update_ms:
            next_update_ms = sample.t_ms + UPDATE_INTERVAL_MS
            keep(settled, tracker.settled_intervals())
            row = hrv_row(sample.t_ms, tracker.reading())
            if row is not None:
                readings.append(row)
    keep(settled, tracker.intervals())
    return ReplayResult(
        intervals=[settled[start] for start in sorted(settled)],
        readings=readings,
        newest_ms=samples[-1].t_ms,
        window_checks=tracker.window_checks(),
    )


def keep(settled: dict[float, Interval], intervals: Sequence[Interval]) -> None:
    for interval in intervals:
        settled[interval.start_ms] = interval


def hrv_row(t_ms: int, reading: HrvReading) -> HrvRow | None:
    if (
        reading.rmssd_ms is None
        or reading.sdnn_ms is None
        or reading.window_ms is None
        or reading.accepted_count is None
    ):
        return None
    return HrvRow(
        t_ms=t_ms,
        rmssd_ms=reading.rmssd_ms,
        sdnn_ms=reading.sdnn_ms,
        window_ms=reading.window_ms,
        accepted_count=reading.accepted_count,
    )


def beat_times(intervals: Sequence[Interval]) -> list[int]:
    return sorted({round(edge) for i in intervals for edge in (i.start_ms, i.end_ms)})


def interval_row(interval: Interval) -> IntervalRow:
    return IntervalRow(
        t_ms=round(interval.end_ms),
        interval_ms=interval.ibi_ms,
        flag=FLAG_CODES[interval.flag],
    )


def newest_span(intervals: Sequence[Interval], newest_ms: int) -> list[Interval]:
    oldest_ms = newest_ms - SUMMARY_SPAN_MS
    return [i for i in intervals if oldest_ms <= round(i.end_ms) <= newest_ms]


def summarise(result: ReplayResult) -> Summary:
    span = newest_span(result.intervals, result.newest_ms)
    accepted = np.array([i.ibi_ms for i in span if i.accepted], dtype=np.float64)
    if accepted.sum() < SUMMARY_MIN_ACCEPTED_MS or not passes_gates(
        span, int(accepted.size), result.newest_ms
    ):
        return Summary(
            bpm=None,
            rmssd_ms=None,
            sdnn_ms=None,
            count=int(accepted.size),
            accepted_percent=accepted_percent(result.intervals),
        )
    reading = hrv_reading(result.intervals, result.newest_ms, result.window_checks)
    return Summary(
        bpm=float(60_000.0 / accepted.mean()),
        rmssd_ms=reading.rmssd_ms,
        sdnn_ms=None
        if reading.sdnn_ms is None
        else mean_minute_sdnn(result.intervals, result.newest_ms),
        count=int(accepted.size),
        accepted_percent=accepted_percent(result.intervals),
    )


def mean_minute_sdnn(intervals: Sequence[Interval], newest_ms: int) -> float | None:
    minutes: defaultdict[int, list[float]] = defaultdict(list)
    for interval in newest_window(intervals, newest_ms):
        if interval.accepted:
            minute = int((newest_ms - interval.end_ms) // SUMMARY_SPAN_MS)
            minutes[minute].append(interval.ibi_ms)
    sdnns = [
        float(np.std(ibis, ddof=1))
        for ibis in minutes.values()
        if len(ibis) >= MIN_MINUTE_INTERVALS and sum(ibis) >= SUMMARY_MIN_ACCEPTED_MS
    ]
    return float(np.mean(sdnns)) if sdnns else None


def passes_gates(span: Sequence[Interval], accepted_count: int, newest_ms: int) -> bool:
    return not (
        alternates(span)
        or too_many_rejected(span, accepted_count)
        or is_stale(span, newest_ms)
    )


def accepted_percent(intervals: Sequence[Interval]) -> float | None:
    settled = sum(1 for i in intervals if i.flag != "edge")
    if settled == 0:
        return None
    return 100.0 * sum(1 for i in intervals if i.accepted) / settled


def shown(value: float | None, unit: str = "") -> str:
    return UNSET if value is None else f"{value:.1f}{unit}"


def summary_line(session_id: int, summary: Summary) -> str:
    return (
        f"Session {session_id} replayed, newest minute:"
        f" bpm={shown(summary.bpm)}"
        f" count={summary.count};"
        f" {HRV_WINDOW_LABEL}:"
        f" rmssd={shown(summary.rmssd_ms, ' ms')}"
        f" sdnn={shown(summary.sdnn_ms, ' ms')};"
        f" whole session: accepted={shown(summary.accepted_percent, '%')}"
    )


if __name__ == "__main__":
    raise SystemExit(main())
