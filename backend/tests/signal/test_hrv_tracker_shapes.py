import pytest

from tests.frames import SEED
from tests.signal.beat_synthetic import (
    TRACKER_NOISE_SD,
    cycle_at,
    late_wave_blood_volume,
    physical_recording,
    rounded_blood_volume,
    two_peak_blood_volume,
)
from tests.signal.hrv_tracking import assert_null_or_near, tracked, true_ibis_inside

SHAPE_SEEDS = [0, 1, 2]
LATE_WAVE_RECORDING_S = 180.0
LATE_WAVE_AT_CYCLE = 0.45
LATE_WAVE_HEIGHTS = [0.35, 0.5]
LATE_WAVE_LAST_S = [30.0, 60.0]
LATE_WAVE_TOLERANCE_MS = {50.0: 5.0, 72.0: 3.0}
SUITE_NOISE_SD = 0.05
NOISY_RECORDING_S = 120.0
NOISE_DOMINATED_TOLERANCE_MS = 15.0
CLOSE_WAVE_RATES_BPM = [50.0, 90.0]
CLOSE_WAVE_AT_CYCLE = [0.25, 0.3]
CLOSE_WAVE_HEIGHTS = [0.2, 0.35, 0.5]
ROUNDED_RATES_BPM = [40.0, 50.0, 72.0]


@pytest.mark.parametrize("seed", SHAPE_SEEDS)
@pytest.mark.parametrize("last_s", LATE_WAVE_LAST_S)
@pytest.mark.parametrize("height", LATE_WAVE_HEIGHTS)
@pytest.mark.parametrize("bpm", list(LATE_WAVE_TOLERANCE_MS))
def test_a_diastolic_wave_in_only_the_newest_seconds_gives_no_reading_or_a_near_one(
    bpm: float, height: float, last_s: float, seed: int
) -> None:
    first_cycle = cycle_at(bpm, LATE_WAVE_RECORDING_S - last_s)
    recording, beats = physical_recording(
        bpm,
        SEED + seed,
        LATE_WAVE_RECORDING_S,
        noise_sd=TRACKER_NOISE_SD,
        shape=late_wave_blood_volume(height, LATE_WAVE_AT_CYCLE, first_cycle),
    )

    reading = tracked(recording).reading()

    assert_null_or_near(
        reading, true_ibis_inside(recording, beats), LATE_WAVE_TOLERANCE_MS[bpm]
    )


@pytest.mark.parametrize("seed", SHAPE_SEEDS)
@pytest.mark.parametrize("height", CLOSE_WAVE_HEIGHTS)
@pytest.mark.parametrize("at", CLOSE_WAVE_AT_CYCLE)
@pytest.mark.parametrize("bpm", CLOSE_WAVE_RATES_BPM)
def test_a_close_diastolic_wave_at_suite_noise_gives_no_reading_or_one_within_15_ms(
    bpm: float, at: float, height: float, seed: int
) -> None:
    recording, beats = physical_recording(
        bpm,
        SEED + seed,
        NOISY_RECORDING_S,
        noise_sd=SUITE_NOISE_SD,
        shape=two_peak_blood_volume(height, at),
    )

    reading = tracked(recording).reading()

    assert_null_or_near(
        reading, true_ibis_inside(recording, beats), NOISE_DOMINATED_TOLERANCE_MS
    )


@pytest.mark.parametrize("seed", SHAPE_SEEDS)
@pytest.mark.parametrize("bpm", ROUNDED_RATES_BPM)
def test_a_rounded_pulse_at_suite_noise_gives_no_reading_or_one_within_15_ms(
    bpm: float, seed: int
) -> None:
    recording, beats = physical_recording(
        bpm,
        SEED + seed,
        NOISY_RECORDING_S,
        noise_sd=SUITE_NOISE_SD,
        shape=rounded_blood_volume,
    )

    reading = tracked(recording).reading()

    assert_null_or_near(
        reading, true_ibis_inside(recording, beats), NOISE_DOMINATED_TOLERANCE_MS
    )
