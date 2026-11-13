import math

import numpy as np
from numpy.typing import NDArray

from pulse_frame.signal.errors import SignalError

RGB_CHANNELS = 3


def check_sample_rate(fs_hz: float) -> None:
    if not math.isfinite(fs_hz) or fs_hz <= 0.0:
        raise SignalError(
            "BAD_SAMPLE_RATE",
            f"The sample rate must be a positive finite number, got {fs_hz}.",
            "Pass a sample rate in hertz greater than zero.",
        )


def check_band(fs_hz: float, low_hz: float, high_hz: float) -> None:
    if not 0.0 < low_hz < high_hz < fs_hz / 2.0:
        raise SignalError(
            "BAD_BAND",
            f"The band {low_hz} to {high_hz} Hz must be finite with low below high"
            f" and inside 0 to fs/2 ({fs_hz / 2.0} Hz).",
            "Pass finite edges with 0 < low_hz < high_hz < fs_hz / 2.",
        )


def check_min_samples(count: int, minimum: int, purpose: str) -> None:
    if count < minimum:
        raise SignalError(
            "NOT_ENOUGH_SAMPLES",
            f"{purpose} needs at least {minimum} samples, got {count}.",
            "Collect more samples before calling it again.",
        )


def check_positive_seconds(name: str, seconds: float) -> None:
    if not math.isfinite(seconds) or seconds <= 0.0:
        raise SignalError(
            "BAD_WINDOW",
            f"{name} must be a positive finite number of seconds, got {seconds}.",
            f"Pass {name} in seconds greater than zero.",
        )


def check_tracker_sample_rate(fs_hz: float, low_hz: float, high_hz: float) -> None:
    lowest_hz = 2.0 * high_hz
    if not fs_hz > lowest_hz:
        raise SignalError(
            "BAD_SAMPLE_RATE",
            f"fs_hz ({fs_hz} Hz) must be above {lowest_hz:g} Hz so the {low_hz} to"
            f" {high_hz} Hz band-pass fits below fs/2.",
            f"Pass an fs_hz above {lowest_hz:g} Hz, for example 30.",
        )


def check_tracker_windows(window_s: float, min_seconds: float, floor_s: float) -> None:
    if not floor_s <= window_s < math.inf:
        raise SignalError(
            "BAD_WINDOW",
            f"window_s ({window_s} s) must be a finite number of seconds of at least"
            f" {floor_s:g} s; the rate gates compare two {floor_s / 2.0:g} s halves"
            f" and were measured on {floor_s:g} s windows.",
            f"Pass window_s of at least {floor_s:g} s, for example {floor_s:g}.",
        )
    if min_seconds != window_s:
        raise SignalError(
            "BAD_WINDOW",
            f"min_seconds ({min_seconds:g} s) must equal window_s ({window_s:g} s) so"
            " the rate gates only ever run on a full window.",
            "Pass min_seconds equal to window_s, or leave both at their defaults.",
        )


def check_signal(samples: NDArray[np.float64]) -> None:
    if samples.ndim != 1:
        raise SignalError(
            "BAD_VALUES",
            f"The signal must be one-dimensional, got shape {samples.shape}.",
            "Pass one value per sample with shape (n,).",
        )
    if not np.all(np.isfinite(samples)):
        raise SignalError(
            "BAD_VALUES",
            "Some signal values are not finite numbers.",
            "Pass finite signal values.",
        )


def check_timestamp_array(timestamps: NDArray[np.float64]) -> None:
    if timestamps.ndim != 1:
        raise SignalError(
            "BAD_TIMESTAMPS",
            f"Timestamps must be one-dimensional, got shape {timestamps.shape}.",
            "Pass timestamps in milliseconds with shape (n,).",
        )
    if not np.all(np.isfinite(timestamps)):
        raise SignalError(
            "BAD_TIMESTAMPS",
            "Some timestamps are not finite numbers.",
            "Pass finite timestamps in milliseconds.",
        )


def check_value_rows(values: NDArray[np.float64], channels: int | None) -> None:
    rows_of_channels = values.ndim == 2 and values.shape[1] >= 1
    if not rows_of_channels or channels not in {None, values.shape[1]}:
        wanted = "channels" if channels is None else str(channels)
        raise SignalError(
            "BAD_VALUES",
            f"Values must have shape (n, {wanted}), got {values.shape}.",
            f"Pass one row of {wanted} channel values per sample.",
        )
    if not np.all(np.isfinite(values)):
        raise SignalError(
            "BAD_VALUES",
            "Some values are not finite numbers.",
            "Pass finite channel values.",
        )


def check_rows_match(
    timestamps: NDArray[np.float64], values: NDArray[np.float64]
) -> None:
    if timestamps.size != values.shape[0]:
        raise SignalError(
            "BAD_TIMESTAMPS",
            f"Got {timestamps.size} timestamps for {values.shape[0]} rows of values.",
            "Pass exactly one timestamp per row of values.",
        )


def check_timestamp(timestamp_ms: float) -> None:
    if not math.isfinite(timestamp_ms):
        raise SignalError(
            "BAD_TIMESTAMPS",
            f"The timestamp {timestamp_ms} is not a finite number.",
            "Pass a finite timestamp in milliseconds.",
        )


def check_region_colour(region: str, rgb: tuple[float, ...]) -> None:
    if len(rgb) != RGB_CHANNELS or not all(math.isfinite(c) for c in rgb):
        raise SignalError(
            "BAD_VALUES",
            f"The {region} colour sample must hold three finite channel means.",
            f"Pass the {region} (red, green, blue) means as finite numbers.",
        )


def check_region_pulses(pulses: NDArray[np.float64]) -> None:
    if pulses.ndim != 2:
        raise SignalError(
            "BAD_VALUES",
            f"Region pulses must have shape (regions, n), got {pulses.shape}.",
            "Pass one row of pulse values per face region.",
        )
    if not np.all(np.isfinite(pulses)):
        raise SignalError(
            "BAD_VALUES",
            "Some region pulse values are not finite numbers.",
            "Pass finite pulse values.",
        )
