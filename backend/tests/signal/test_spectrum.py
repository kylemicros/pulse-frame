import math

import numpy as np
import pytest
from numpy.typing import NDArray

from pulse_frame.signal.errors import SignalError
from pulse_frame.signal.spectrum import RateEstimate, estimate_rate
from pulse_frame.signal.tracker import MIN_SNR_DB

FS_HZ = 30.0


def clean_sine(freq_hz: float, duration_s: float = 10.0) -> NDArray[np.float64]:
    t = np.arange(int(duration_s * FS_HZ)) / FS_HZ
    return np.sin(2.0 * np.pi * freq_hz * t + 0.4)


@pytest.mark.parametrize(("freq_hz", "bpm"), [(1.5, 90.0), (1.23, 73.8)])
def test_clean_sine_gives_its_rate_within_half_bpm(freq_hz: float, bpm: float) -> None:
    estimate = estimate_rate(clean_sine(freq_hz), FS_HZ)

    assert isinstance(estimate, RateEstimate)
    assert estimate.bpm == pytest.approx(bpm, abs=0.5)
    assert estimate.snr_db > 0.0


@pytest.mark.parametrize(
    "bpm", [47.31, 61.17, 72.61, 73.37, 88.81, 101.43, 133.9, 166.66]
)
def test_sine_between_fft_bins_gives_its_rate_within_five_hundredths_bpm(
    bpm: float,
) -> None:
    estimate = estimate_rate(clean_sine(bpm / 60.0), FS_HZ)

    assert estimate.bpm == pytest.approx(bpm, abs=0.05)


def test_white_noise_scores_lower_snr_than_clean_sine() -> None:
    noise = np.random.default_rng(11).normal(0.0, 1.0, int(10.0 * FS_HZ))

    assert (
        estimate_rate(noise, FS_HZ).snr_db
        < estimate_rate(clean_sine(1.5), FS_HZ).snr_db
    )


@pytest.mark.parametrize("duration_s", [10.0, 15.0, 20.0])
def test_sine_below_the_band_is_not_a_good_estimate_at_the_band_edge(
    duration_s: float,
) -> None:
    estimate = estimate_rate(clean_sine(0.5, duration_s), FS_HZ)

    assert estimate.snr_db < MIN_SNR_DB


@pytest.mark.parametrize("count", [0, 1, 2])
def test_fewer_than_three_samples_raises_not_enough_samples(count: int) -> None:
    with pytest.raises(SignalError) as caught:
        estimate_rate(np.ones(count), FS_HZ)

    assert caught.value.code == "NOT_ENOUGH_SAMPLES"
    assert caught.value.message
    assert caught.value.action


def test_exactly_three_samples_give_a_finite_estimate() -> None:
    estimate = estimate_rate(np.array([0.0, 1.0, 0.0]), FS_HZ)

    assert math.isfinite(estimate.bpm)
    assert math.isfinite(estimate.snr_db)


@pytest.mark.filterwarnings("error")
def test_all_zero_signal_gives_a_finite_rate_below_the_quality_threshold() -> None:
    estimate = estimate_rate(np.zeros(300), FS_HZ)

    assert math.isfinite(estimate.bpm)
    assert math.isfinite(estimate.snr_db)
    assert estimate.snr_db < MIN_SNR_DB


def test_short_clean_sine_whose_lobes_cover_the_band_scores_the_clean_snr() -> None:
    t = np.arange(48) / FS_HZ
    estimate = estimate_rate(np.sin(2.0 * np.pi * 1.5 * t), FS_HZ)

    assert estimate.snr_db == 100.0


@pytest.mark.parametrize(
    ("fs_hz", "low_hz", "high_hz", "code"),
    [
        (0.0, 0.7, 4.0, "BAD_SAMPLE_RATE"),
        (-30.0, 0.7, 4.0, "BAD_SAMPLE_RATE"),
        (math.nan, 0.7, 4.0, "BAD_SAMPLE_RATE"),
        (math.inf, 0.7, 4.0, "BAD_SAMPLE_RATE"),
        (FS_HZ, 0.0, 4.0, "BAD_BAND"),
        (FS_HZ, -1.0, 4.0, "BAD_BAND"),
        (FS_HZ, 2.0, 1.0, "BAD_BAND"),
        (FS_HZ, 1.0, 1.0, "BAD_BAND"),
        (FS_HZ, 0.7, 15.0, "BAD_BAND"),
        (FS_HZ, 0.7, 20.0, "BAD_BAND"),
        (FS_HZ, math.nan, 4.0, "BAD_BAND"),
        (FS_HZ, 0.7, math.inf, "BAD_BAND"),
    ],
)
def test_bad_rate_or_band_raises_a_coded_error(
    fs_hz: float, low_hz: float, high_hz: float, code: str
) -> None:
    with pytest.raises(SignalError) as caught:
        estimate_rate(clean_sine(1.2), fs_hz, low_hz, high_hz)

    assert caught.value.code == code
    assert caught.value.message
    assert caught.value.action


@pytest.mark.parametrize("freq_hz", [4.3, 5.0, 6.0])
def test_sine_above_the_band_is_not_a_good_estimate_at_the_band_edge(
    freq_hz: float,
) -> None:
    estimate = estimate_rate(clean_sine(freq_hz), FS_HZ)

    assert estimate.snr_db < MIN_SNR_DB


def test_band_narrower_than_one_frequency_bin_raises_bad_band() -> None:
    with pytest.raises(SignalError) as caught:
        estimate_rate(clean_sine(1.2), FS_HZ, 1.0, 1.001)

    assert caught.value.code == "BAD_BAND"
    assert caught.value.message
    assert caught.value.action


def with_sample(signal: NDArray[np.float64], value: float) -> NDArray[np.float64]:
    changed = signal.copy()
    changed[17] = value
    return changed


BAD_SIGNALS = {
    "nan": with_sample(clean_sine(1.2), math.nan),
    "inf": with_sample(clean_sine(1.2), math.inf),
    "two_columns": np.column_stack((clean_sine(1.2), clean_sine(1.2))),
}


@pytest.mark.parametrize("signal", list(BAD_SIGNALS.values()), ids=list(BAD_SIGNALS))
def test_signal_that_is_not_one_dimensional_and_finite_raises_bad_values(
    signal: NDArray[np.float64],
) -> None:
    with pytest.raises(SignalError) as caught:
        estimate_rate(signal, FS_HZ)

    assert caught.value.code == "BAD_VALUES"
    assert caught.value.message
    assert caught.value.action
