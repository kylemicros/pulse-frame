import numpy as np
from numpy.typing import NDArray

from pulse_frame.signal.beats import Interval
from pulse_frame.signal.hrv import HrvReading, HrvTracker
from tests.signal.beat_synthetic import (
    BloodVolume,
    beat_cycles,
    beats_inside,
    rmssd,
    sdnn,
    systolic_midpoints,
)
from tests.signal.synthetic import Recording

CYCLE_GRID_MS = 0.5
TRUTH_MARGIN_MS = 3_000.0


def feed(
    tracker: HrvTracker,
    recording: Recording,
    moving: NDArray[np.bool_] | None = None,
    low_quality: NDArray[np.bool_] | None = None,
) -> None:
    count = recording.timestamps_ms.size
    moving_flags = np.zeros(count, dtype=np.bool_) if moving is None else moving
    low_flags = np.zeros(count, dtype=np.bool_) if low_quality is None else low_quality
    for (timestamp_ms, regions), is_moving, is_low in zip(
        recording.samples(), moving_flags, low_flags, strict=True
    ):
        tracker.add(
            timestamp_ms, regions, moving=bool(is_moving), low_quality=bool(is_low)
        )


def tracked(recording: Recording) -> HrvTracker:
    tracker = HrvTracker()
    feed(tracker, recording)
    return tracker


def accepted(intervals: list[Interval]) -> list[Interval]:
    return [interval for interval in intervals if interval.accepted]


def elapsed_ms(recording: Recording, seconds: float) -> float:
    return float(recording.timestamps_ms[0]) + seconds * 1000.0


def seconds_of(recording: Recording) -> NDArray[np.float64]:
    return (recording.timestamps_ms - recording.timestamps_ms[0]) / 1000.0


def beat_times(intervals: list[Interval]) -> NDArray[np.float64]:
    return np.unique([edge for i in intervals for edge in (i.start_ms, i.end_ms)])


def cycle_locked_ibi_errors(
    intervals: list[Interval], beats_ms: NDArray[np.float64]
) -> NDArray[np.float64]:
    grid = np.arange(beats_ms[0], beats_ms[-1], CYCLE_GRID_MS)
    cycles = beat_cycles(grid, beats_ms)
    starts = np.array([i.start_ms for i in intervals])
    ends = np.array([i.end_ms for i in intervals])
    true_ends = np.interp(beat_cycles(starts, beats_ms) + 1.0, cycles, grid)
    return ends - true_ends


def true_ibis_inside(
    recording: Recording, beats_ms: NDArray[np.float64], shape: BloodVolume
) -> NDArray[np.float64]:
    first_ms = float(recording.timestamps_ms[0]) + TRUTH_MARGIN_MS
    last_ms = float(recording.timestamps_ms[-1]) - TRUTH_MARGIN_MS
    midpoints = systolic_midpoints(beats_ms, shape)
    return np.diff(beats_inside(midpoints, first_ms, last_ms))


def is_null(reading: HrvReading) -> bool:
    return reading.rmssd_ms is None and reading.sdnn_ms is None


def assert_null_or_near(
    reading: HrvReading, truth_ibis_ms: NDArray[np.float64], tolerance_ms: float
) -> None:
    if is_null(reading):
        return
    rmssd_error, sdnn_error = hrv_errors(reading, truth_ibis_ms)
    assert rmssd_error <= tolerance_ms
    assert sdnn_error <= tolerance_ms


def hrv_errors(
    reading: HrvReading, truth_ibis_ms: NDArray[np.float64]
) -> tuple[float, float]:
    assert reading.rmssd_ms is not None
    assert reading.sdnn_ms is not None
    return (
        abs(reading.rmssd_ms - rmssd(truth_ibis_ms)),
        abs(reading.sdnn_ms - sdnn(truth_ibis_ms)),
    )
