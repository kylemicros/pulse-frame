import math

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view
from numpy.typing import NDArray

from pulse_frame.signal.checks import (
    RGB_CHANNELS,
    check_positive_seconds,
    check_sample_rate,
    check_value_rows,
)

POS_PROJECTION = np.array([[0.0, 1.0, -1.0], [-2.0, 1.0, 1.0]])


def pos_pulse(
    rgb: NDArray[np.float64], fs_hz: float, window_s: float = 1.6
) -> NDArray[np.float64]:
    samples = np.asarray(rgb, dtype=np.float64)
    check_sample_rate(fs_hz)
    check_value_rows(samples, channels=RGB_CHANNELS)
    check_positive_seconds("window_s", window_s)
    count = samples.shape[0]
    pulse = np.zeros(count)
    if count == 0:
        return pulse
    length = min(count, max(2, math.ceil(window_s * fs_hz)))
    windows = sliding_window_view(samples, length, axis=0)
    segments = window_pulses(windows)
    starts = np.arange(segments.shape[0])
    positions = starts[:, None] + np.arange(length)[None, :]
    np.add.at(pulse, positions, segments)
    return pulse


def window_pulses(windows: NDArray[np.float64]) -> NDArray[np.float64]:
    means = windows.mean(axis=2, keepdims=True)
    normalised = safe_divide(windows, np.broadcast_to(means, windows.shape))
    projected = np.einsum("pc,wcl->wpl", POS_PROJECTION, normalised)
    s1 = projected[:, 0, :]
    s2 = projected[:, 1, :]
    alpha = safe_divide(s1.std(axis=1), s2.std(axis=1))
    combined = s1 + alpha[:, None] * s2
    return combined - combined.mean(axis=1, keepdims=True)


def safe_divide(
    numerator: NDArray[np.float64], denominator: NDArray[np.float64]
) -> NDArray[np.float64]:
    result = np.zeros(np.broadcast_shapes(numerator.shape, denominator.shape))
    np.divide(numerator, denominator, out=result, where=denominator != 0.0)
    return result
