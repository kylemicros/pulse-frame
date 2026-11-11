import math

import numpy as np
import pytest
from numpy.typing import NDArray

from pulse_frame.signal.errors import SignalError
from pulse_frame.signal.filters import bandpass

FS_HZ = 30.0
DURATION_S = 30.0
EDGE_S = 5.0


def sine(freq_hz: float) -> NDArray[np.float64]:
    t = np.arange(int(DURATION_S * FS_HZ)) / FS_HZ
    return np.sin(2.0 * np.pi * freq_hz * t)


def steady_gain(freq_hz: float) -> float:
    x = sine(freq_hz)
    y = bandpass(x, FS_HZ)
    edge = int(EDGE_S * FS_HZ)
    return float(np.sqrt(np.mean(y[edge:-edge] ** 2) / np.mean(x[edge:-edge] ** 2)))


def test_bandpass_keeps_length() -> None:
    x = sine(1.2)
    assert bandpass(x, FS_HZ).shape == x.shape


def test_bandpass_passes_in_band_pulse_with_near_unit_gain() -> None:
    assert steady_gain(1.2) == pytest.approx(1.0, abs=0.1)


@pytest.mark.parametrize("freq_hz", [0.1, 8.0])
def test_bandpass_strongly_attenuates_out_of_band(freq_hz: float) -> None:
    assert steady_gain(freq_hz) < 0.1


@pytest.mark.parametrize(
    ("fs_hz", "low_hz", "high_hz", "code"),
    [
        (0.0, 0.7, 4.0, "BAD_SAMPLE_RATE"),
        (math.nan, 0.7, 4.0, "BAD_SAMPLE_RATE"),
        (FS_HZ, 0.0, 4.0, "BAD_BAND"),
        (FS_HZ, 4.0, 0.7, "BAD_BAND"),
        (FS_HZ, 0.7, 15.0, "BAD_BAND"),
    ],
)
def test_bad_rate_or_band_raises_a_coded_error(
    fs_hz: float, low_hz: float, high_hz: float, code: str
) -> None:
    with pytest.raises(SignalError) as caught:
        bandpass(sine(1.2), fs_hz, low_hz, high_hz)

    assert caught.value.code == code
    assert caught.value.message
    assert caught.value.action


@pytest.mark.filterwarnings("error")
@pytest.mark.parametrize("count", [0, 1, 10])
def test_short_input_keeps_its_length_without_raising(count: int) -> None:
    x = sine(1.2)[:count]

    y = bandpass(x, FS_HZ)

    assert y.shape == (count,)
    assert np.all(np.isfinite(y))


def test_single_sample_is_returned_without_its_mean() -> None:
    np.testing.assert_array_equal(bandpass(np.array([5.0]), FS_HZ), [0.0])


def with_sample(signal: NDArray[np.float64], value: float) -> NDArray[np.float64]:
    changed = signal.copy()
    changed[17] = value
    return changed


BAD_SIGNALS = {
    "nan": with_sample(sine(1.2), math.nan),
    "inf": with_sample(sine(1.2), -math.inf),
    "two_columns": np.column_stack((sine(1.2), sine(1.2))),
}


@pytest.mark.parametrize("signal", list(BAD_SIGNALS.values()), ids=list(BAD_SIGNALS))
def test_signal_that_is_not_one_dimensional_and_finite_raises_bad_values(
    signal: NDArray[np.float64],
) -> None:
    with pytest.raises(SignalError) as caught:
        bandpass(signal, FS_HZ)

    assert caught.value.code == "BAD_VALUES"
    assert caught.value.message
    assert caught.value.action
