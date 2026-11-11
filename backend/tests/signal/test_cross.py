import math
import warnings

import numpy as np
import pytest
from numpy.typing import NDArray

from pulse_frame.signal.cross import (
    FULL_SUBHARMONIC_LIMIT,
    HALF_SUBHARMONIC_LIMIT,
    estimate_cross_rate,
    is_reliable,
)
from pulse_frame.signal.errors import SignalError
from pulse_frame.signal.spectrum import SEARCH_HIGH_HZ, SEARCH_LOW_HZ

FS_HZ = 30.0
SHARED_BPM = 72.0
SAMPLES = 600
HUGE_SCALE = 1e200
TONE_AMPLITUDE = 3.0
WEAK_PULSE_AMPLITUDE = 0.3
OUTSIDE_TONES_HZ = [0.55, 4.3]
INSIDE_TONES_HZ = [1.5, 3.0]
BETWEEN_BINS_SAMPLES = 1200
BETWEEN_BINS_BPM = 73.28


def shared_pulse_regions(seed: int = 7) -> NDArray[np.float64]:
    rng = np.random.default_rng(seed)
    seconds = np.arange(SAMPLES) / FS_HZ
    return np.stack(
        [
            np.sin(2.0 * np.pi * SHARED_BPM / 60.0 * seconds + phase)
            + 0.1 * rng.standard_normal(SAMPLES)
            for phase in (0.0, 0.4, 0.9)
        ]
    )


def with_nan(pulses: NDArray[np.float64]) -> NDArray[np.float64]:
    changed = pulses.copy()
    changed[1, 17] = math.nan
    return changed


BAD_SHAPES = {
    "one_dimensional": shared_pulse_regions()[0],
    "three_dimensional": shared_pulse_regions()[None],
}


@pytest.mark.parametrize("pulses", list(BAD_SHAPES.values()), ids=list(BAD_SHAPES))
def test_pulses_not_shaped_regions_by_samples_raise_bad_values_naming_the_shape(
    pulses: NDArray[np.float64],
) -> None:
    with pytest.raises(SignalError) as caught:
        estimate_cross_rate(pulses, FS_HZ)

    assert caught.value.code == "BAD_VALUES"
    assert "(regions, n)" in caught.value.message
    assert caught.value.action


def test_pulses_holding_nan_raise_bad_values() -> None:
    with pytest.raises(SignalError) as caught:
        estimate_cross_rate(with_nan(shared_pulse_regions()), FS_HZ)

    assert caught.value.code == "BAD_VALUES"
    assert caught.value.message
    assert caught.value.action


@pytest.mark.parametrize("fs_hz", [0.0, -30.0, math.nan, math.inf])
def test_bad_sample_rate_raises_bad_sample_rate(fs_hz: float) -> None:
    with pytest.raises(SignalError) as caught:
        estimate_cross_rate(shared_pulse_regions(), fs_hz)

    assert caught.value.code == "BAD_SAMPLE_RATE"
    assert caught.value.message
    assert caught.value.action


@pytest.mark.parametrize("fs_hz", [1e-3, 1e-6])
def test_sample_rate_too_small_to_hold_the_search_band_gives_no_estimate(
    fs_hz: float,
) -> None:
    assert estimate_cross_rate(shared_pulse_regions(), fs_hz) is None


def test_huge_finite_pulses_give_none_where_unit_ones_read_the_rate() -> None:
    pulses = shared_pulse_regions()

    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)
        estimate = estimate_cross_rate(pulses, FS_HZ)
        huge_estimate = estimate_cross_rate(pulses * HUGE_SCALE, FS_HZ)

    assert estimate is not None
    assert estimate.bpm == pytest.approx(SHARED_BPM, abs=0.5)
    assert huge_estimate is None


def tone_with_weak_pulse_regions(tone_hz: float) -> NDArray[np.float64]:
    rng = np.random.default_rng(11)
    seconds = np.arange(SAMPLES) / FS_HZ
    return np.stack(
        [
            TONE_AMPLITUDE * np.sin(2.0 * np.pi * tone_hz * seconds + 0.3 * index)
            + WEAK_PULSE_AMPLITUDE
            * np.sin(2.0 * np.pi * SHARED_BPM / 60.0 * seconds + phase)
            + 0.05 * rng.standard_normal(SAMPLES)
            for index, phase in enumerate((0.0, 0.4, 0.9))
        ]
    )


@pytest.mark.parametrize("tone_hz", OUTSIDE_TONES_HZ)
def test_strong_shared_tone_just_outside_the_band_flags_flank_and_never_passes(
    tone_hz: float,
) -> None:
    assert not SEARCH_LOW_HZ <= tone_hz <= SEARCH_HIGH_HZ

    estimate = estimate_cross_rate(tone_with_weak_pulse_regions(tone_hz), FS_HZ)

    assert estimate is not None
    assert estimate.flank is True
    assert not estimate.passes(FULL_SUBHARMONIC_LIMIT)
    assert not estimate.passes(HALF_SUBHARMONIC_LIMIT)
    assert not is_reliable(estimate, estimate, estimate)


@pytest.mark.parametrize("tone_hz", INSIDE_TONES_HZ)
def test_strong_shared_tone_inside_the_band_is_read_without_flank(
    tone_hz: float,
) -> None:
    assert SEARCH_LOW_HZ <= tone_hz <= SEARCH_HIGH_HZ

    estimate = estimate_cross_rate(tone_with_weak_pulse_regions(tone_hz), FS_HZ)

    assert estimate is not None
    assert estimate.flank is False
    assert estimate.bpm == pytest.approx(tone_hz * 60.0, abs=0.5)
    assert estimate.passes(FULL_SUBHARMONIC_LIMIT)


def test_shared_sine_between_fft_bins_reads_within_five_hundredths_of_a_bpm() -> None:
    seconds = np.arange(BETWEEN_BINS_SAMPLES) / FS_HZ
    pulses = np.stack(
        [
            np.sin(2.0 * np.pi * BETWEEN_BINS_BPM / 60.0 * seconds + phase)
            for phase in (0.0, 0.4, 0.9)
        ]
    )

    estimate = estimate_cross_rate(pulses, FS_HZ)

    assert estimate is not None
    assert estimate.bpm == pytest.approx(BETWEEN_BINS_BPM, abs=0.05)
