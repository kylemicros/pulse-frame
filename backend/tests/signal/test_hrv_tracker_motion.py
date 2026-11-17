import numpy as np
import pytest

from pulse_frame.signal.hrv import HrvTracker
from tests.frames import SEED
from tests.signal.beat_synthetic import physical_recording, rounded_blood_volume
from tests.signal.hrv_tracking import (
    accepted,
    cycle_locked_ibi_errors,
    feed,
    seconds_of,
)

STEP_BPM = 60.0
STEP_RECORDING_S = 100.0
STEP_NOISE_SD = 0.005
STEP_UP_NEAR_S = 40.0
STEP_DOWN_NEAR_S = 70.0
NEAR_STEP_S = 5.0
STEP_IBI_TOLERANCE_MS = 15.0
STEP_AFTER_BEAT_SHARES = [-0.05, 0.0, 0.05]


def beat_near(beats_ms: np.ndarray, first_ms: float, seconds: float) -> float:
    since_s = (beats_ms - first_ms) / 1000.0
    return float(since_s[np.argmin(np.abs(since_s - seconds))])


@pytest.mark.parametrize("flag", ["moving", "low_quality"])
@pytest.mark.parametrize("share", STEP_AFTER_BEAT_SHARES)
def test_no_accepted_interval_near_a_colour_step_is_more_than_fifteen_ms_off(
    flag: str, share: float
) -> None:
    plain, beats = physical_recording(
        STEP_BPM,
        SEED,
        STEP_RECORDING_S,
        noise_sd=STEP_NOISE_SD,
        shape=rounded_blood_volume,
    )
    first_ms = float(plain.timestamps_ms[0])
    ibi_s = 60.0 / STEP_BPM
    up_s = beat_near(beats, first_ms, STEP_UP_NEAR_S) + share * ibi_s
    down_s = beat_near(beats, first_ms, STEP_DOWN_NEAR_S) + share * ibi_s
    recording, _ = physical_recording(
        STEP_BPM,
        SEED,
        STEP_RECORDING_S,
        noise_sd=STEP_NOISE_SD,
        shape=rounded_blood_volume,
        gain_steps=[(up_s, down_s)],
    )
    seconds = seconds_of(recording)
    flagged = np.zeros(seconds.size, dtype=np.bool_)
    flagged[np.argmax(seconds >= up_s)] = True
    flagged[np.argmax(seconds >= down_s)] = True
    tracker = HrvTracker()

    feed(tracker, recording, **{flag: flagged})

    near = [
        interval
        for interval in accepted(tracker.intervals())
        if any(
            (interval.start_ms - first_ms) / 1000.0 <= step_s + NEAR_STEP_S
            and (interval.end_ms - first_ms) / 1000.0 >= step_s - NEAR_STEP_S
            for step_s in (up_s, down_s)
        )
    ]
    assert near
    assert tracker.reading().rmssd_ms is not None
    errors = np.abs(cycle_locked_ibi_errors(near, beats))
    assert float(errors.max()) <= STEP_IBI_TOLERANCE_MS
