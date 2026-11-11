import numpy as np
from numpy.typing import NDArray

from pulse_frame.signal.checks import (
    check_min_samples,
    check_rows_match,
    check_sample_rate,
    check_timestamp_array,
    check_value_rows,
)


def resample_uniform(
    timestamps_ms: NDArray[np.float64], values: NDArray[np.float64], fs_hz: float
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    timestamps = np.asarray(timestamps_ms, dtype=np.float64)
    samples = np.asarray(values, dtype=np.float64)
    check_sample_rate(fs_hz)
    check_timestamp_array(timestamps)
    check_value_rows(samples, channels=None)
    check_rows_match(timestamps, samples)
    keep = strictly_increasing_mask(timestamps)
    kept_times = timestamps[keep]
    kept_values = samples[keep]
    check_min_samples(kept_times.size, 2, "Resampling with increasing timestamps")
    grid = uniform_grid(kept_times[0], kept_times[-1], fs_hz)
    resampled = np.column_stack(
        [
            np.interp(grid, kept_times, kept_values[:, channel])
            for channel in range(kept_values.shape[1])
        ]
    )
    return grid, resampled


def strictly_increasing_mask(timestamps: NDArray[np.float64]) -> NDArray[np.bool_]:
    if timestamps.size == 0:
        return np.zeros(0, dtype=np.bool_)
    largest_before = np.maximum.accumulate(timestamps)[:-1]
    return np.concatenate(([True], timestamps[1:] > largest_before))


def uniform_grid(first_ms: float, last_ms: float, fs_hz: float) -> NDArray[np.float64]:
    span_ms = last_ms - first_ms
    count = int(np.floor(span_ms * fs_hz / 1000.0)) + 1
    grid = first_ms + np.arange(count) * (1000.0 / fs_hz)
    return np.minimum(grid, last_ms)
