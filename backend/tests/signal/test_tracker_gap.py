import math

import pytest

from pulse_frame.signal.errors import SignalError
from pulse_frame.signal.tracker import MAX_GAP_MS, PulseTracker, Reading
from tests.frames import SEED, TRUE_BPM
from tests.signal.synthetic import webcam_recording
from tests.signal.tracking import assert_ok_within_one_bpm, feed

SETTLE_S = 10.0


def assert_acquiring(reading: Reading) -> None:
    assert reading.state == "acquiring"
    assert reading.bpm is None
    assert reading.quality_db is None


def ok_tracker() -> tuple[PulseTracker, float]:
    recording = webcam_recording(TRUE_BPM, seed=SEED, duration_s=15.0)
    tracker = PulseTracker()
    feed(tracker, recording)
    assert_ok_within_one_bpm(tracker.reading(), TRUE_BPM)
    return tracker, float(recording.timestamps_ms[-1])


def test_tick_more_than_the_gap_after_the_newest_sample_restarts_to_acquiring() -> None:
    tracker, newest_ms = ok_tracker()

    tracker.tick(newest_ms + MAX_GAP_MS + 1.0)

    assert_acquiring(tracker.reading())
    assert tracker.waveform() == []


@pytest.mark.parametrize("offset_ms", [-100.0, 0.0, 1.0, MAX_GAP_MS / 2.0, MAX_GAP_MS])
def test_tick_within_the_gap_keeps_the_reading(offset_ms: float) -> None:
    tracker, newest_ms = ok_tracker()
    before = tracker.reading()

    tracker.tick(newest_ms + offset_ms)

    assert tracker.reading() == before


def test_tick_on_an_empty_tracker_stays_acquiring() -> None:
    tracker = PulseTracker()

    tracker.tick(5_000.0)

    assert_acquiring(tracker.reading())


def test_tracker_settles_again_on_fresh_samples_after_a_tick_restart() -> None:
    tracker, newest_ms = ok_tracker()
    tracker.tick(newest_ms + MAX_GAP_MS + 1.0)
    resumed = webcam_recording(TRUE_BPM, seed=SEED + 1, duration_s=15.0)
    resumed = resumed.shifted(newest_ms + 2.0 * MAX_GAP_MS - resumed.timestamps_ms[0])

    feed(tracker, resumed.until(SETTLE_S - 0.5))
    settling = tracker.reading()
    feed(tracker, resumed.after(SETTLE_S - 0.5))

    assert_acquiring(settling)
    assert_ok_within_one_bpm(tracker.reading(), TRUE_BPM)


@pytest.mark.parametrize("bad_ms", [math.nan, math.inf, -math.inf])
def test_tick_with_a_timestamp_that_is_not_finite_raises_a_coded_error(
    bad_ms: float,
) -> None:
    tracker, _ = ok_tracker()
    before = tracker.reading()

    with pytest.raises(SignalError) as raised:
        tracker.tick(bad_ms)

    assert raised.value.code == "BAD_TIMESTAMPS"
    assert raised.value.message
    assert raised.value.action
    assert tracker.reading() == before
