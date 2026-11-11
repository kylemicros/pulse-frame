import pytest

from pulse_frame.signal.tracker import PulseTracker, Reading
from tests.frames import SEED
from tests.signal.synthetic import (
    Recording,
    piecewise_wave,
    wave_recording,
    webcam_recording,
)
from tests.signal.tracking import assert_ok_within_one_bpm

TRUE_RATES_BPM = [60.0, 72.0, 120.0]
WINDOW_S = 10.0
UPDATE_S = 1.0
FIRST_MOTION_S = 15.0
SECOND_MOTION_S = 20.0
MID_UPDATE_MOTION_S = 15.5
FIRST_UPDATE_AFTER_S = UPDATE_S + 0.1
LEAVES_WINDOW_MARGIN_S = 0.1
RECOVERY_SLACK_S = 2.0
SETTLE_S = 10.0
SETTLE_MOTION_S = 5.0
RATE_BEFORE_BPM = 60.0
RATE_AFTER_BPM = 90.0


def trace_with_motion(
    tracker: PulseTracker, recording: Recording, motion_at_s: list[float]
) -> tuple[list[tuple[float, Reading]], list[float]]:
    start_ms = float(recording.timestamps_ms[0])
    pending = sorted(motion_at_s)
    flagged_at: list[float] = []
    trace = []
    for timestamp_ms, rgb in recording.samples():
        elapsed_s = (timestamp_ms - start_ms) / 1000.0
        moving = bool(pending) and elapsed_s > pending[0]
        if moving:
            pending.pop(0)
            flagged_at.append(elapsed_s)
        tracker.add(timestamp_ms, rgb, moving=moving)
        trace.append((elapsed_s, tracker.reading()))
    return trace, flagged_at


def readings_between(
    trace: list[tuple[float, Reading]], from_s: float, to_s: float
) -> list[Reading]:
    return [reading for elapsed_s, reading in trace if from_s <= elapsed_s < to_s]


def last_reading_before(trace: list[tuple[float, Reading]], at_s: float) -> Reading:
    return [reading for elapsed_s, reading in trace if elapsed_s < at_s][-1]


@pytest.mark.parametrize("true_bpm", TRUE_RATES_BPM)
def test_samples_marked_still_keep_a_clean_pulse_ok(true_bpm: float) -> None:
    recording = webcam_recording(true_bpm, seed=SEED + int(true_bpm), duration_s=20.0)
    tracker = PulseTracker()

    trace, flagged_at = trace_with_motion(tracker, recording, [])

    assert flagged_at == []
    assert_ok_within_one_bpm(last_reading_before(trace, 15.0), true_bpm)
    assert_ok_within_one_bpm(trace[-1][1], true_bpm)


@pytest.mark.parametrize("true_bpm", TRUE_RATES_BPM)
def test_one_motion_sample_makes_ok_low_quality_until_it_leaves_the_window(
    true_bpm: float,
) -> None:
    recording = webcam_recording(true_bpm, seed=SEED + int(true_bpm), duration_s=32.0)
    tracker = PulseTracker()

    trace, flagged_at = trace_with_motion(tracker, recording, [FIRST_MOTION_S])
    motion_s = flagged_at[0]
    inside_window = readings_between(
        trace,
        motion_s + FIRST_UPDATE_AFTER_S,
        motion_s + WINDOW_S - LEAVES_WINDOW_MARGIN_S,
    )
    recovered = readings_between(
        trace, motion_s + WINDOW_S + RECOVERY_SLACK_S, float("inf")
    )

    assert_ok_within_one_bpm(last_reading_before(trace, motion_s), true_bpm)
    assert inside_window
    assert all(r.state == "low_quality" for r in inside_window)
    assert all(r.bpm is None for r in inside_window)
    assert recovered
    for reading in recovered:
        assert_ok_within_one_bpm(reading, true_bpm)


def test_latest_motion_in_the_window_keeps_the_reading_low_quality() -> None:
    true_bpm = 72.0
    recording = webcam_recording(true_bpm, seed=SEED + 7, duration_s=34.0)
    tracker = PulseTracker()

    trace, flagged_at = trace_with_motion(
        tracker, recording, [FIRST_MOTION_S, SECOND_MOTION_S]
    )
    first_s, second_s = flagged_at
    inside_window = readings_between(
        trace,
        first_s + FIRST_UPDATE_AFTER_S,
        second_s + WINDOW_S - LEAVES_WINDOW_MARGIN_S,
    )
    recovered = readings_between(
        trace, second_s + WINDOW_S + RECOVERY_SLACK_S, float("inf")
    )

    assert inside_window
    assert all(r.state == "low_quality" for r in inside_window)
    assert all(r.bpm is None for r in inside_window)
    assert recovered
    for reading in recovered:
        assert_ok_within_one_bpm(reading, true_bpm)


def test_motion_during_the_settle_time_reads_acquiring_then_low_quality() -> None:
    true_bpm = 72.0
    recording = webcam_recording(true_bpm, seed=SEED + 11, duration_s=20.0)
    tracker = PulseTracker()

    trace, flagged_at = trace_with_motion(tracker, recording, [SETTLE_MOTION_S])
    motion_s = flagged_at[0]
    settling = readings_between(trace, 0.0, SETTLE_S - LEAVES_WINDOW_MARGIN_S)
    motion_in_window = readings_between(
        trace,
        SETTLE_S + FIRST_UPDATE_AFTER_S,
        motion_s + WINDOW_S - LEAVES_WINDOW_MARGIN_S,
    )
    recovered = readings_between(
        trace, motion_s + WINDOW_S + RECOVERY_SLACK_S, float("inf")
    )

    assert settling
    assert all(r.state == "acquiring" for r in settling)
    assert motion_in_window
    assert all(r.state == "low_quality" for r in motion_in_window)
    assert all(r.bpm is None for r in motion_in_window)
    assert recovered
    for reading in recovered:
        assert_ok_within_one_bpm(reading, true_bpm)


def test_first_ok_after_motion_reflects_only_the_rate_after_the_motion() -> None:
    recording = wave_recording(
        lambda seconds: piecewise_wave(
            seconds, [(0.0, RATE_BEFORE_BPM), (FIRST_MOTION_S, RATE_AFTER_BPM)]
        ),
        seed=SEED + 12,
        duration_s=30.0,
    )
    tracker = PulseTracker()

    trace, flagged_at = trace_with_motion(tracker, recording, [FIRST_MOTION_S])
    motion_s = flagged_at[0]
    after_motion = [
        reading
        for elapsed_s, reading in trace
        if elapsed_s > motion_s and reading.state == "ok"
    ]

    assert_ok_within_one_bpm(last_reading_before(trace, motion_s), RATE_BEFORE_BPM)
    assert after_motion
    assert_ok_within_one_bpm(after_motion[0], RATE_AFTER_BPM)


@pytest.mark.parametrize("true_bpm", TRUE_RATES_BPM)
def test_motion_sample_turns_an_ok_reading_low_quality_on_the_same_call(
    true_bpm: float,
) -> None:
    recording = webcam_recording(true_bpm, seed=SEED + int(true_bpm), duration_s=17.0)
    tracker = PulseTracker()

    trace, flagged_at = trace_with_motion(tracker, recording, [MID_UPDATE_MOTION_S])
    motion_s = flagged_at[0]
    at_motion = [reading for elapsed_s, reading in trace if elapsed_s == motion_s]

    assert_ok_within_one_bpm(last_reading_before(trace, motion_s), true_bpm)
    assert len(at_motion) == 1
    assert at_motion[0].state == "low_quality"
    assert at_motion[0].bpm is None
