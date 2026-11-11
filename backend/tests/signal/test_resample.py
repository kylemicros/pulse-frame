import math

import numpy as np
import pytest
from numpy.typing import NDArray

from pulse_frame.signal.errors import SignalError
from pulse_frame.signal.resample import resample_uniform


def linear_rgb(timestamps_ms: NDArray[np.float64]) -> NDArray[np.float64]:
    relative = timestamps_ms - timestamps_ms[0]
    return np.column_stack(
        (relative / 10.0, relative / 5.0, 3.0 * relative / 10.0 + 50.0)
    )


def test_duplicate_and_out_of_order_timestamps_are_dropped() -> None:
    start = 5000.0
    timestamps = start + np.array([0.0, 100.0, 100.0, 230.0, 200.0, 300.0, 430.0])
    values = np.array(
        [
            [0.0, 0.0, 50.0],
            [10.0, 20.0, 80.0],
            [999.0, 999.0, 999.0],
            [23.0, 46.0, 119.0],
            [999.0, 999.0, 999.0],
            [30.0, 60.0, 140.0],
            [43.0, 86.0, 179.0],
        ]
    )

    times, resampled = resample_uniform(timestamps, values, 10.0)

    np.testing.assert_allclose(
        times, [5000.0, 5100.0, 5200.0, 5300.0, 5400.0], atol=1e-9
    )
    np.testing.assert_allclose(
        resampled,
        [
            [0.0, 0.0, 50.0],
            [10.0, 20.0, 80.0],
            [20.0, 40.0, 110.0],
            [30.0, 60.0, 140.0],
            [40.0, 80.0, 170.0],
        ],
        atol=1e-9,
    )


def test_consecutive_samples_behind_the_latest_timestamp_are_dropped() -> None:
    start = 8000.0
    timestamps = start + np.array([0.0, 100.0, 300.0, 200.0, 250.0, 400.0])
    values = np.array(
        [
            [0.0, 0.0, 50.0],
            [10.0, 20.0, 80.0],
            [30.0, 60.0, 140.0],
            [999.0, 999.0, 999.0],
            [-999.0, -999.0, -999.0],
            [40.0, 80.0, 170.0],
        ]
    )

    times, resampled = resample_uniform(timestamps, values, 10.0)

    np.testing.assert_allclose(
        times, [8000.0, 8100.0, 8200.0, 8300.0, 8400.0], atol=1e-9
    )
    np.testing.assert_allclose(
        resampled,
        [
            [0.0, 0.0, 50.0],
            [10.0, 20.0, 80.0],
            [20.0, 40.0, 110.0],
            [30.0, 60.0, 140.0],
            [40.0, 80.0, 170.0],
        ],
        atol=1e-9,
    )


def test_irregular_timestamps_are_interpolated_onto_a_uniform_grid() -> None:
    rng = np.random.default_rng(7)
    timestamps = 1000.0 + np.cumsum(rng.uniform(1000.0 / 35.0, 1000.0 / 25.0, 120))
    values = linear_rgb(timestamps)
    fs_hz = 30.0

    times, resampled = resample_uniform(timestamps, values, fs_hz)

    span_ms = timestamps[-1] - timestamps[0]
    assert times.size == int(np.floor(span_ms * fs_hz / 1000.0)) + 1
    np.testing.assert_allclose(np.diff(times), 1000.0 / fs_hz)
    assert times[0] >= timestamps[0]
    assert times[-1] <= timestamps[-1]
    expected = np.column_stack(
        (
            (times - timestamps[0]) / 10.0,
            (times - timestamps[0]) / 5.0,
            3.0 * (times - timestamps[0]) / 10.0 + 50.0,
        )
    )
    np.testing.assert_allclose(resampled, expected, atol=1e-9)


def test_exactly_two_samples_are_resampled() -> None:
    timestamps = np.array([1000.0, 1100.0])
    values = np.array([[10.0, 20.0, 30.0], [20.0, 40.0, 60.0]])

    times, resampled = resample_uniform(timestamps, values, 10.0)

    np.testing.assert_allclose(times, [1000.0, 1100.0], atol=1e-9)
    np.testing.assert_allclose(resampled, values, atol=1e-9)


@pytest.mark.parametrize("count", [0, 1])
def test_fewer_than_two_samples_raises_not_enough_samples(count: int) -> None:
    timestamps = 1000.0 + 33.3 * np.arange(count, dtype=np.float64)
    values = np.full((count, 3), 120.0)

    with pytest.raises(SignalError) as caught:
        resample_uniform(timestamps, values, 30.0)

    assert caught.value.code == "NOT_ENOUGH_SAMPLES"
    assert caught.value.message
    assert caught.value.action


def good_timestamps() -> NDArray[np.float64]:
    return 1000.0 + 33.3 * np.arange(6, dtype=np.float64)


def with_value(
    array: NDArray[np.float64], index: tuple[int, ...], value: float
) -> NDArray[np.float64]:
    changed = array.copy()
    changed[index] = value
    return changed


GOOD_VALUES = np.full((6, 3), 120.0)


BAD_INPUTS = {
    "nan_timestamp": (
        with_value(good_timestamps(), (2,), math.nan),
        GOOD_VALUES,
        30.0,
        "BAD_TIMESTAMPS",
    ),
    "inf_timestamp": (
        with_value(good_timestamps(), (5,), math.inf),
        GOOD_VALUES,
        30.0,
        "BAD_TIMESTAMPS",
    ),
    "timestamps_2d": (
        good_timestamps().reshape(6, 1),
        GOOD_VALUES,
        30.0,
        "BAD_TIMESTAMPS",
    ),
    "length_mismatch": (good_timestamps()[:5], GOOD_VALUES, 30.0, "BAD_TIMESTAMPS"),
    "values_1d": (good_timestamps(), np.full(6, 120.0), 30.0, "BAD_VALUES"),
    "no_channels": (good_timestamps(), np.full((6, 0), 120.0), 30.0, "BAD_VALUES"),
    "values_3d": (good_timestamps(), np.full((6, 3, 1), 120.0), 30.0, "BAD_VALUES"),
    "nan_value": (
        good_timestamps(),
        with_value(GOOD_VALUES, (3, 1), math.nan),
        30.0,
        "BAD_VALUES",
    ),
    "inf_value": (
        good_timestamps(),
        with_value(GOOD_VALUES, (0, 2), -math.inf),
        30.0,
        "BAD_VALUES",
    ),
    "zero_rate": (good_timestamps(), GOOD_VALUES, 0.0, "BAD_SAMPLE_RATE"),
    "nan_rate": (good_timestamps(), GOOD_VALUES, math.nan, "BAD_SAMPLE_RATE"),
}


@pytest.mark.parametrize(
    ("timestamps", "values", "fs_hz", "code"),
    list(BAD_INPUTS.values()),
    ids=list(BAD_INPUTS),
)
def test_bad_input_raises_a_coded_error(
    timestamps: NDArray[np.float64],
    values: NDArray[np.float64],
    fs_hz: float,
    code: str,
) -> None:
    with pytest.raises(SignalError) as caught:
        resample_uniform(timestamps, values, fs_hz)

    assert caught.value.code == code
    assert caught.value.message
    assert caught.value.action
