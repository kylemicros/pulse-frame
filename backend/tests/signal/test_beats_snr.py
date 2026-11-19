import math

import numpy as np
import pytest
from numpy.typing import NDArray

from pulse_frame.signal.beats import SNR_FLOOR_DB, cross_region_snr_db
from pulse_frame.signal.hrv import beat_rate_hz, region_pulses, segment_beats
from tests.frames import SEED
from tests.signal.beat_synthetic import (
    asymmetric_blood_volume,
    beat_cycles,
    frame_times,
    in_band_noise,
    known_beats,
    reflected_light_wave,
)
from tests.signal.synthetic import FPS, Recording, in_band, red_noise_recording

WINDOW_S = 20.0
ANALYSIS_S = 20.5
STEADY_BPM = 72.0
REGIONS = 3
TRUTH_SNRS_DB = [-3.0, 0.0, 3.0, 6.0, 10.0]
ESTIMATE_TOLERANCE_DB = 3.0
ESTIMATE_SEEDS = [0, 1, 2]
FLOOR_MARGIN_DB = 3.0
NULL_WINDOWS = 120
NULL_SHARE_BOUND = 0.01
NULL_SEED = SEED + 5_000


def steady_regions(rng: np.random.Generator, snr_db: float) -> NDArray[np.float64]:
    times = frame_times(WINDOW_S)
    beats = known_beats(STEADY_BPM, WINDOW_S, swing_ms=0.0)
    pulse = reflected_light_wave(asymmetric_blood_volume(beat_cycles(times, beats)))
    sd = math.sqrt(float(in_band(pulse).var()) / 10.0 ** (snr_db / 10.0))
    return np.stack(
        [pulse + in_band_noise(rng, pulse.size, sd) for _ in range(REGIONS)]
    )


def window_pulses(recording: Recording) -> NDArray[np.float64]:
    times = recording.timestamps_ms
    pulses = region_pulses(times, recording.regions.reshape(times.size, 9), FPS)
    assert pulses is not None
    return pulses[1]


@pytest.mark.parametrize("seed", ESTIMATE_SEEDS)
@pytest.mark.parametrize("snr_db", TRUTH_SNRS_DB)
def test_the_cross_region_snr_reads_each_regions_snr_within_three_db(
    snr_db: float, seed: int
) -> None:
    regions = steady_regions(np.random.default_rng(SEED + seed), snr_db)

    estimate_db = cross_region_snr_db(regions, STEADY_BPM / 60.0, FPS)

    assert estimate_db == pytest.approx(snr_db, abs=ESTIMATE_TOLERANCE_DB)


@pytest.mark.parametrize("seed", ESTIMATE_SEEDS)
def test_regions_three_db_either_side_of_the_floor_read_on_that_side(
    seed: int,
) -> None:
    rng = np.random.default_rng(SEED + seed)
    under = steady_regions(rng, SNR_FLOOR_DB - FLOOR_MARGIN_DB)
    over = steady_regions(rng, SNR_FLOOR_DB + FLOOR_MARGIN_DB)

    under_db = cross_region_snr_db(under, STEADY_BPM / 60.0, FPS)
    over_db = cross_region_snr_db(over, STEADY_BPM / 60.0, FPS)

    assert under_db < SNR_FLOOR_DB < over_db


def test_red_noise_without_a_pulse_almost_never_reaches_the_floor() -> None:
    estimates = []
    for window in range(NULL_WINDOWS):
        regions = window_pulses(red_noise_recording(None, NULL_SEED + window))
        rate_hz = beat_rate_hz(regions, FPS)
        estimates.append(cross_region_snr_db(regions, rate_hz, FPS))

    reaching = float(np.mean(np.array(estimates) >= SNR_FLOOR_DB))

    assert reaching <= NULL_SHARE_BOUND


def test_a_red_noise_window_gives_no_beats_and_carries_its_snr_under_the_floor() -> (
    None
):
    recording = red_noise_recording(None, NULL_SEED, duration_s=ANALYSIS_S)
    times = recording.timestamps_ms

    segments = segment_beats(times, recording.regions.reshape(times.size, 9), FPS)

    assert len(segments) == 1
    assert segments[0].beats_ms.size == 0
    assert segments[0].snr_db < SNR_FLOOR_DB
