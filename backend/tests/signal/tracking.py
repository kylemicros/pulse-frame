import pytest

from pulse_frame.signal.tracker import PulseTracker, Reading
from tests.signal.synthetic import Recording


def feed(tracker: PulseTracker, recording: Recording) -> None:
    for timestamp_ms, rgb in recording.samples():
        tracker.add(timestamp_ms, rgb)


def reading_trace(
    tracker: PulseTracker, recording: Recording
) -> list[tuple[float, Reading]]:
    start_ms = float(recording.timestamps_ms[0])
    trace = []
    for timestamp_ms, rgb in recording.samples():
        tracker.add(timestamp_ms, rgb)
        trace.append(((timestamp_ms - start_ms) / 1000.0, tracker.reading()))
    return trace


def readings_by_second(
    tracker: PulseTracker, recording: Recording
) -> dict[int, Reading]:
    return {
        int((elapsed_s + 0.5) // 1.0): reading
        for elapsed_s, reading in reading_trace(tracker, recording)
    }


def assert_ok_within_one_bpm(reading: Reading, true_bpm: float) -> None:
    assert reading.state == "ok"
    assert reading.bpm is not None
    assert reading.bpm == pytest.approx(true_bpm, abs=1.0)
