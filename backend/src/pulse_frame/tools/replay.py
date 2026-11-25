import argparse
import math
import sys
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from pulse_frame.platform.errors import SandboxError
from pulse_frame.platform.sandbox import apply_loopback_sandbox
from pulse_frame.signal.beats import (
    MIN_SNR_CYCLES,
    SNR_FLOOR_DB,
    Interval,
    IntervalFlag,
)
from pulse_frame.signal.errors import SignalError
from pulse_frame.signal.hrv import WINDOW_MS, HrvReading, HrvTracker, WindowCheck
from pulse_frame.signal.summary import (
    Summary,
    beside_holes,
    counted_checks,
    counted_intervals,
    counted_reading,
    floor_decision,
    measured_under_floor,
    newest_minute_checks,
    too_weak_decision,
)
from pulse_frame.signal.summary import summarise as summarise_counted
from pulse_frame.signal.tracker import UPDATE_INTERVAL_MS, RegionColours
from pulse_frame.store.errors import StoreError
from pulse_frame.store.recording import (
    FrameSample,
    HrvRow,
    IntervalRow,
    SessionClock,
    frame_samples,
    replace_replay,
    session_clock,
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
MS_PER_S = 1_000.0
SECONDS_PER_MINUTE = 60
NEWEST_MINUTE = 0
HRV_WINDOW_LABEL = f"last {round(WINDOW_MS / 60_000.0)} minutes"
WHOLE_SESSION_LABEL = "whole session"
COUNTED_PART_LABEL = "counted part"
UNSET = "-"
WEAK_SIGNAL_ACTION = (
    "Light the face evenly and brightly, for example facing a window or a lamp,"
    " keep still, and turn off the camera's auto exposure if it has that"
    f" setting, then record a new session with `{CAPTURE_COMMAND}`."
)
NO_READING_CODE = "READING_FLOOR_NOT_CLEARED"
FAINT_PULSE_ACTION = (
    "Give your face more even light, for example facing a window, and hold still,"
)
FACE_LOSS_REASON = (
    "your face kept leaving the camera's view, so your pulse could not be read."
)
FACE_LOSS_ACTION = "Sit facing the camera and keep your face in view,"
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


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog=REPLAY_COMMAND,
        description=(
            "Replay one stored session's frame samples through the HRV tracker,"
            " replace its beats, intervals and HRV readings in the local store,"
            " and print per-session aggregates only: BPM and its accepted interval"
            " count over the newest minute, RMSSD and SDNN over the"
            f" {HRV_WINDOW_LABEL}, and the accepted share of intervals. A session"
            " captured with a warm-up runs the tracker over every sample but keeps"
            " only the counted part after the warm-up for the stored rows and the"
            " aggregates."
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
    clock = session_clock(session_id)
    if not any(sample.t_ms >= clock.counted_ms for sample in samples):
        report_no_counted_samples(session_id)
        return 1
    result = replay_samples(samples, clock.counted_ms)
    replace_replay(
        session_id,
        beat_times(result.intervals),
        [interval_row(interval) for interval in result.intervals],
        result.readings,
    )
    summary = summarise(result)
    write_out(summary_line(session_id, summary, counted_span_label(clock, result)))
    report_notice(result, summary)
    return 0


def report_notice(result: ReplayResult, summary: Summary) -> None:
    weak = weak_notice(result, summary)
    if weak is not None:
        report("SIGNAL_TOO_WEAK", weak, WEAK_SIGNAL_ACTION)
        return
    no_reading = no_reading_notice(result, summary)
    if no_reading is not None:
        print(no_reading, file=sys.stderr)


def report_no_counted_samples(session_id: int) -> None:
    report(
        "NO_COUNTED_SAMPLES",
        f"Session {session_id} holds no frame sample after its warm-up, so there"
        " is no counted part to replay and nothing was written. The capture"
        " stopped before the warm-up ended, or saw no usable face after it.",
        f"Delete the session with `{SESSIONS_COMMAND} delete {session_id}` in"
        " backend/ if you no longer need it, then record a new one with"
        f" `{CAPTURE_COMMAND}`, let it run past the warm-up bell and keep your"
        " face in view until the closing bell.",
    )


def counted_span_label(clock: SessionClock, result: ReplayResult) -> str | None:
    if not clock.warmed_up:
        return None
    span_ms = min(float(result.newest_ms - clock.counted_ms), WINDOW_MS)
    seconds = half_up(span_ms / MS_PER_S)
    if seconds == 0 or seconds % SECONDS_PER_MINUTE:
        return f"counted {seconds} seconds"
    return f"counted {minute_count(seconds // SECONDS_PER_MINUTE)}"


def minute_count(minutes: int) -> str:
    return f"{minutes} minute{'' if minutes == 1 else 's'}"


def half_up(value: float) -> int:
    return math.floor(value + 0.5)


def weak_notice(result: ReplayResult, summary: Summary) -> str | None:
    if too_weak_decision(summary, result.window_checks, result.newest_ms) is None:
        return None
    return weak_signal_message(newest_checks(result))


def newest_checks(result: ReplayResult) -> list[WindowCheck]:
    return newest_minute_checks(result.window_checks, result.newest_ms)


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


def no_reading_notice(result: ReplayResult, summary: Summary) -> str | None:
    decision = floor_decision(summary, result.window_checks, bool(result.readings))
    if decision is None:
        return None
    if decision.why == "faint_pulse" and decision.clear_percent is not None:
        return no_reading_line(
            faint_pulse_reason(decision.clear_percent), FAINT_PULSE_ACTION
        )
    return no_reading_line(FACE_LOSS_REASON, FACE_LOSS_ACTION)


def faint_pulse_reason(clear_percent: float) -> str:
    if clear_percent == 0.0:
        return "your pulse never showed clearly during the run."
    share = half_up(clear_percent)
    shown_share = "under 1%" if share == 0 else f"only {share}%"
    return f"your pulse showed clearly in {shown_share} of the run."


def no_reading_line(reason: str, action: str) -> str:
    return (
        f"No reading this time: {reason} {action} then record a new session with"
        f" `{CAPTURE_COMMAND}`. Ref: {NO_READING_CODE}"
    )


def region_colours(sample: FrameSample) -> RegionColours:
    return RegionColours(
        forehead=sample.forehead,
        left_cheek=sample.left_cheek,
        right_cheek=sample.right_cheek,
    )


def replay_samples(samples: Sequence[FrameSample], counted_ms: int = 0) -> ReplayResult:
    tracker = HrvTracker()
    settled: dict[float, Interval] = {}
    readings: list[HrvRow] = []
    next_update_ms: float | None = None
    holes = beside_holes([sample.t_ms for sample in samples])
    for sample, low_quality in zip(samples, holes, strict=True):
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
            row = hrv_row(
                sample.t_ms, counted_reading(tracker, sample.t_ms, counted_ms)
            )
            if row is not None:
                readings.append(row)
    keep(settled, tracker.intervals())
    return ReplayResult(
        intervals=counted_intervals(
            [settled[start] for start in sorted(settled)], counted_ms
        ),
        readings=readings,
        newest_ms=samples[-1].t_ms,
        window_checks=counted_checks(tracker.window_checks(), counted_ms),
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


def summarise(result: ReplayResult) -> Summary:
    return summarise_counted(result.intervals, result.newest_ms, result.window_checks)


def shown(value: float | None, unit: str = "") -> str:
    return UNSET if value is None else f"{value:.1f}{unit}"


def summary_line(
    session_id: int, summary: Summary, counted_label: str | None = None
) -> str:
    if counted_label is None:
        newest_sdnn = ""
        hrv_label, hrv_sdnn, share_label = (
            HRV_WINDOW_LABEL,
            sdnn_part(summary),
            WHOLE_SESSION_LABEL,
        )
    else:
        newest_only = summary.sdnn_minutes == (NEWEST_MINUTE,)
        newest_sdnn = sdnn_part(summary) if newest_only else ""
        hrv_label, hrv_sdnn, share_label = (
            counted_label,
            "" if newest_only else counted_sdnn_part(summary),
            COUNTED_PART_LABEL,
        )
    return (
        f"Session {session_id} replayed, newest minute:"
        f" bpm={shown(summary.bpm)}"
        f" count={summary.count}{newest_sdnn};"
        f" {hrv_label}:"
        f" rmssd={shown(summary.rmssd_ms, ' ms')}{hrv_sdnn};"
        f" {share_label}: accepted={shown(summary.accepted_percent, '%')}"
    )


def sdnn_part(summary: Summary) -> str:
    return f" sdnn={shown(summary.sdnn_ms, ' ms')}"


def counted_sdnn_part(summary: Summary) -> str:
    if summary.sdnn_ms is None:
        return sdnn_part(summary)
    return f"{sdnn_part(summary)} over {minute_count(len(summary.sdnn_minutes))}"


if __name__ == "__main__":
    raise SystemExit(main())
