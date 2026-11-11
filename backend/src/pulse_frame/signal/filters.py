from functools import lru_cache

import numpy as np
from numpy.typing import NDArray
from scipy.signal import butter, sosfiltfilt

from pulse_frame.signal.checks import check_band, check_sample_rate, check_signal

BUTTERWORTH_ORDER = 4
PASS_LOW_HZ = 0.5
PASS_HIGH_HZ = 4.5


def bandpass(
    x: NDArray[np.float64],
    fs_hz: float,
    low_hz: float = PASS_LOW_HZ,
    high_hz: float = PASS_HIGH_HZ,
) -> NDArray[np.float64]:
    samples = np.asarray(x, dtype=np.float64)
    sos = bandpass_sections(fs_hz, low_hz, high_hz)
    check_signal(samples)
    if samples.size < 2:
        return samples - samples.mean() if samples.size else samples.copy()
    padlen = min(3 * (2 * sos.shape[0] + 1), samples.size - 1)
    return sosfiltfilt(sos, samples, padlen=padlen)


@lru_cache(maxsize=8)
def bandpass_sections(
    fs_hz: float, low_hz: float, high_hz: float
) -> NDArray[np.float64]:
    check_sample_rate(fs_hz)
    check_band(fs_hz, low_hz, high_hz)
    return butter(
        BUTTERWORTH_ORDER, [low_hz, high_hz], btype="bandpass", fs=fs_hz, output="sos"
    )
