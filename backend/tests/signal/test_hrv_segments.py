import math

import numpy as np
import pytest
from numpy.typing import NDArray

from pulse_frame.signal.cross import estimate_cross_rate
from pulse_frame.signal.hrv import (
    HALF_RATE_SHARE,
    SegmentBeats,
    agreeing_regions,
    beat_rate_hz,
    flag_implausible,
    region_pulses,
    spectral_rate_hz,
)
from tests.frames import SEED, TRUE_BPM
from tests.signal.beat_synthetic import (
    TRACKER_NOISE_SD,
    chain,
    in_band_noise,
    physical_recording,
)
from tests.signal.face_synthetic import realistic_face
from tests.signal.synthetic import FPS

ANALYSIS_S = 20.5
SLOW_BPM = 40.0
CROSS_FLOOR_BPM = 42.0
RATE_TOLERANCE_BPM = 0.5
RATE_SEEDS = [0, 1, 2]
PULSE_COUNT = 600
NOISE_SD = 1.0
PERIOD_MS = 800.0
SEGMENT_FROM_MS = 1_000.0
SEGMENT_SNR_DB = 10.0
SHARED_NOISE_SNR_DB = 10.0
SHARED_NOISE_SEEDS = list(range(8))
RED_HUMP_BPM = 78.0
RED_HUMP_SNR_DB = 0.0
RED_HUMP_SEEDS = list(range(24))
RED_HUMP_TOLERANCE_BPM = 2.0
SLOW_PULSE_HZ = 0.9
FUNDAMENTAL_SHARES = (0.3, 0.1)
SPECTRUM_S = 20.0
SPECTRUM_TOLERANCE_HZ = 0.02


def analysis_pulses(bpm: float, seed: int) -> NDArray[np.float64]:
    recording, _ = physical_recording(
        bpm, SEED + seed, ANALYSIS_S, noise_sd=TRACKER_NOISE_SD
    )
    times = recording.timestamps_ms
    pulses = region_pulses(times, recording.regions.reshape(times.size, 9), FPS)
    assert pulses is not None
    return pulses[1]


def segment(last_ms: float = math.inf) -> SegmentBeats:
    return SegmentBeats(
        first_ms=SEGMENT_FROM_MS,
        last_ms=last_ms,
        beats_ms=np.empty(0),
        period_ms=PERIOD_MS,
        snr_db=SEGMENT_SNR_DB,
    )


def test_three_regions_that_share_no_pulse_are_all_kept() -> None:
    rng = np.random.default_rng(SEED)
    regions = np.stack([in_band_noise(rng, PULSE_COUNT, NOISE_SD) for _ in range(3)])

    kept = agreeing_regions(regions, TRUE_BPM / 60.0, FPS)

    assert kept.shape == regions.shape
    assert np.array_equal(kept, regions)


def test_a_region_without_the_shared_pulse_is_left_out() -> None:
    rng = np.random.default_rng(SEED)
    regions = analysis_pulses(TRUE_BPM, 0).copy()
    regions[1] = in_band_noise(rng, regions.shape[1], NOISE_SD)

    kept = agreeing_regions(regions, TRUE_BPM / 60.0, FPS)

    assert kept.shape[0] == 2
    assert np.array_equal(kept, regions[[0, 2]])


@pytest.mark.parametrize("seed", RATE_SEEDS)
def test_forty_bpm_takes_the_spectral_fallback_over_a_flank_cross_estimate(
    seed: int,
) -> None:
    regions = analysis_pulses(SLOW_BPM, seed)
    cross = estimate_cross_rate(regions, FPS)
    assert cross is not None
    assert cross.flank
    assert cross.bpm > CROSS_FLOOR_BPM

    rate_bpm = beat_rate_hz(regions, FPS) * 60.0

    assert rate_bpm == pytest.approx(SLOW_BPM, abs=RATE_TOLERANCE_BPM)


@pytest.mark.parametrize("seed", RATE_SEEDS)
def test_above_forty_two_bpm_the_cross_estimate_sets_the_rate(seed: int) -> None:
    regions = analysis_pulses(TRUE_BPM, seed)
    cross = estimate_cross_rate(regions, FPS)
    assert cross is not None
    fallback_bpm = spectral_rate_hz(regions.mean(axis=0), FPS) * 60.0
    assert fallback_bpm != pytest.approx(cross.bpm, abs=1e-6)

    rate_bpm = beat_rate_hz(regions, FPS) * 60.0

    assert rate_bpm == pytest.approx(cross.bpm, abs=1e-9)


def test_with_no_cross_estimate_the_spectral_fallback_sets_the_rate() -> None:
    single = analysis_pulses(TRUE_BPM, 0)[:1]
    assert estimate_cross_rate(single, FPS) is None

    rate_hz = beat_rate_hz(single, FPS)

    assert rate_hz == pytest.approx(spectral_rate_hz(single[0], FPS), abs=1e-12)
    assert rate_hz * 60.0 == pytest.approx(TRUE_BPM, abs=RATE_TOLERANCE_BPM)


def test_an_interval_twice_the_spectral_period_is_turned_low_quality() -> None:
    intervals = chain([PERIOD_MS, 2.0 * PERIOD_MS, PERIOD_MS], SEGMENT_FROM_MS)

    flagged = flag_implausible(intervals, [segment()])

    assert [i.flag for i in flagged] == ["ok", "low_quality", "ok"]


def test_an_interval_under_six_tenths_of_the_period_is_turned_low_quality() -> None:
    intervals = chain([PERIOD_MS, 0.5 * PERIOD_MS, PERIOD_MS], SEGMENT_FROM_MS)

    flagged = flag_implausible(intervals, [segment()])

    assert [i.flag for i in flagged] == ["ok", "low_quality", "ok"]


def test_an_already_rejected_or_unsegmented_interval_keeps_its_flag() -> None:
    rejected = chain([2.0 * PERIOD_MS], SEGMENT_FROM_MS, ["motion"])
    outside = chain([2.0 * PERIOD_MS], SEGMENT_FROM_MS)

    flagged = flag_implausible(
        [*rejected, *outside], [segment(last_ms=SEGMENT_FROM_MS)]
    )

    assert [i.flag for i in flagged] == ["motion", "ok"]


def face_regions(
    bpm: float, snr_db: float, seed: int, pulseless: tuple[int, ...] = ()
) -> NDArray[np.float64]:
    face = realistic_face(bpm, snr_db, SEED + seed, ANALYSIS_S, pulseless)
    times = face.recording.timestamps_ms
    colours = face.recording.regions.reshape(times.size, 9)
    pulses = region_pulses(times, colours, FPS)
    assert pulses is not None
    return pulses[1]


def cross_rate_hz(regions: NDArray[np.float64]) -> float:
    cross = estimate_cross_rate(regions, FPS)
    assert cross is not None
    return cross.bpm / 60.0


@pytest.mark.parametrize("seed", SHARED_NOISE_SEEDS)
def test_a_pulseless_region_is_left_out_when_the_regions_share_noise(
    seed: int,
) -> None:
    regions = face_regions(TRUE_BPM, SHARED_NOISE_SNR_DB, seed, (1,))

    kept = agreeing_regions(regions, cross_rate_hz(regions), FPS)

    assert np.array_equal(kept, regions[[0, 2]])


@pytest.mark.parametrize("seed", SHARED_NOISE_SEEDS)
def test_three_pulsed_regions_are_all_kept_when_they_share_noise(seed: int) -> None:
    regions = face_regions(TRUE_BPM, SHARED_NOISE_SNR_DB, seed)

    kept = agreeing_regions(regions, cross_rate_hz(regions), FPS)

    assert np.array_equal(kept, regions)


@pytest.mark.parametrize("seed", RED_HUMP_SEEDS)
def test_a_red_noise_hump_at_half_the_rate_does_not_halve_the_beat_rate(
    seed: int,
) -> None:
    regions = face_regions(RED_HUMP_BPM, RED_HUMP_SNR_DB, seed)
    cross_bpm = cross_rate_hz(regions) * 60.0

    rate_bpm = beat_rate_hz(regions, FPS) * 60.0

    assert rate_bpm == pytest.approx(cross_bpm, abs=RED_HUMP_TOLERANCE_BPM)


@pytest.mark.parametrize(
    ("fundamental_share", "expected_hz"),
    [
        (FUNDAMENTAL_SHARES[0], SLOW_PULSE_HZ),
        (FUNDAMENTAL_SHARES[1], 2.0 * SLOW_PULSE_HZ),
    ],
    ids=["fundamental_over_the_share", "fundamental_under_the_share"],
)
def test_the_fallback_halves_to_the_fundamental_only_over_its_power_share(
    fundamental_share: float, expected_hz: float
) -> None:
    seconds = np.arange(int(SPECTRUM_S * FPS)) / FPS
    angle = 2.0 * np.pi * SLOW_PULSE_HZ * seconds
    pulse = math.sqrt(fundamental_share) * np.sin(angle) + np.sin(2.0 * angle)
    assert (fundamental_share > HALF_RATE_SHARE) == (expected_hz == SLOW_PULSE_HZ)

    rate_hz = spectral_rate_hz(pulse, FPS)

    assert rate_hz == pytest.approx(expected_hz, abs=SPECTRUM_TOLERANCE_HZ)
