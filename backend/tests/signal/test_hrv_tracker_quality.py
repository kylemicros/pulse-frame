import numpy as np
import pytest

from pulse_frame.signal.hrv import HrvReading, HrvTracker
from tests.frames import SEED
from tests.signal.beat_synthetic import (
    TRACKER_NOISE_SD,
    physical_recording,
    two_peak_blood_volume,
)
from tests.signal.hrv_tracking import (
    accepted,
    assert_null_or_near,
    is_null,
    seconds_of,
    tracked,
    true_ibis_inside,
)
from tests.signal.synthetic import Recording, webcam_recording

STALE_BPM = 60.0
STALE_RECORDING_S = 140.0
PULSE_UNTIL_S = 90.0
STALE_AFTER_MS = 10_000.0
TWO_PEAK_S = 120.0
TWO_PEAK_TOLERANCE_MS = {50.0: 5.0, 72.0: 3.0}
DIASTOLIC_HEIGHTS = [0.2, 0.35, 0.5]
DIASTOLIC_AT_CYCLE = [0.25, 0.45]
SUITE_NOISE_SD = 0.05
NOISY_TWO_PEAK_AT_CYCLE = 0.45
NOISE_DOMINATED_TOLERANCE_MS = 15.0
NOISE_ONLY_S = 90.0
NOISE_SEEDS = [0, 1, 2]
TWO_PEAK_SEEDS = [0, 1, 2]


def held_after(recording: Recording, regions: list[int]) -> Recording:
    seconds = seconds_of(recording)
    colours = recording.regions.copy()
    first_held = int(np.argmax(seconds >= PULSE_UNTIL_S))
    colours[first_held:, regions] = colours[first_held - 1, regions]
    return Recording(recording.timestamps_ms, colours)


def stale_readings(recording: Recording) -> list[HrvReading]:
    seconds = seconds_of(recording)
    tracker = HrvTracker()
    stale = []
    for second, (timestamp_ms, regions) in zip(
        seconds, recording.samples(), strict=True
    ):
        tracker.add(timestamp_ms, regions)
        if PULSE_UNTIL_S - 1.0 <= second < PULSE_UNTIL_S:
            assert tracker.reading().rmssd_ms is not None
        if second < PULSE_UNTIL_S:
            continue
        newest_ok = accepted(tracker.intervals())[-1].end_ms
        if timestamp_ms - newest_ok > STALE_AFTER_MS:
            stale.append(tracker.reading())
    return stale


def test_constant_colours_after_a_clean_pulse_null_the_reading_ten_seconds_on() -> None:
    clean, _ = physical_recording(
        STALE_BPM, SEED, STALE_RECORDING_S, noise_sd=TRACKER_NOISE_SD
    )

    stale = stale_readings(held_after(clean, [0, 1, 2]))

    assert len(stale) > 0
    assert [reading for reading in stale if not is_null(reading)] == []


def test_a_zero_spread_region_never_leaves_a_reading_from_beats_over_ten_s_old() -> (
    None
):
    clean, _ = physical_recording(
        STALE_BPM, SEED, STALE_RECORDING_S, noise_sd=TRACKER_NOISE_SD
    )

    stale = stale_readings(held_after(clean, [0]))

    assert [reading for reading in stale if not is_null(reading)] == []


@pytest.mark.parametrize("seed", TWO_PEAK_SEEDS)
@pytest.mark.parametrize("bpm", list(TWO_PEAK_TOLERANCE_MS))
@pytest.mark.parametrize("at", DIASTOLIC_AT_CYCLE)
@pytest.mark.parametrize("height", DIASTOLIC_HEIGHTS)
def test_a_two_peak_pulse_gives_no_reading_or_one_near_the_truth(
    bpm: float, at: float, height: float, seed: int
) -> None:
    recording, beats = physical_recording(
        bpm,
        SEED + seed,
        TWO_PEAK_S,
        noise_sd=TRACKER_NOISE_SD,
        shape=two_peak_blood_volume(height, at),
    )

    reading = tracked(recording).reading()

    assert_null_or_near(
        reading, true_ibis_inside(recording, beats), TWO_PEAK_TOLERANCE_MS[bpm]
    )


@pytest.mark.parametrize("seed", TWO_PEAK_SEEDS)
@pytest.mark.parametrize("bpm", list(TWO_PEAK_TOLERANCE_MS))
@pytest.mark.parametrize("height", DIASTOLIC_HEIGHTS)
def test_a_two_peak_pulse_at_suite_noise_gives_no_reading_or_one_near_the_truth(
    bpm: float, height: float, seed: int
) -> None:
    recording, beats = physical_recording(
        bpm,
        SEED + seed,
        TWO_PEAK_S,
        noise_sd=SUITE_NOISE_SD,
        shape=two_peak_blood_volume(height, NOISY_TWO_PEAK_AT_CYCLE),
    )

    reading = tracked(recording).reading()

    assert_null_or_near(
        reading, true_ibis_inside(recording, beats), NOISE_DOMINATED_TOLERANCE_MS
    )


@pytest.mark.parametrize("seed", NOISE_SEEDS)
def test_ninety_seconds_of_noise_without_a_pulse_give_no_reading(seed: int) -> None:
    recording = webcam_recording(None, SEED + seed, NOISE_ONLY_S, motion_step=False)

    assert is_null(tracked(recording).reading())
