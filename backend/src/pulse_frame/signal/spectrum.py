import math
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from pulse_frame.signal.checks import (
    check_band,
    check_min_samples,
    check_sample_rate,
    check_signal,
)
from pulse_frame.signal.errors import SignalError

SEARCH_LOW_HZ = 0.7
SEARCH_HIGH_HZ = 4.0
FFT_GRID_BPM = 0.25
MAIN_LOBE_BINS = 2.0
NOT_A_PULSE_SNR_DB = -100.0
CLEAN_SNR_DB = 100.0
EDGE_TOLERANCE_HZ = 0.02
OUTSIDE_REACH_HZ = 0.3


@dataclass(frozen=True)
class RateEstimate:
    bpm: float
    snr_db: float


def estimate_rate(
    pulse: NDArray[np.float64],
    fs_hz: float,
    low_hz: float = SEARCH_LOW_HZ,
    high_hz: float = SEARCH_HIGH_HZ,
) -> RateEstimate:
    samples = np.asarray(pulse, dtype=np.float64)
    check_sample_rate(fs_hz)
    check_band(fs_hz, low_hz, high_hz)
    check_signal(samples)
    check_min_samples(samples.size, 3, "A rate estimate")
    freqs, power = hann_power_spectrum(samples, fs_hz)
    band = (freqs >= low_hz) & (freqs <= high_hz)
    band_indices = np.flatnonzero(band)
    if band_indices.size == 0:
        raise SignalError(
            "BAD_BAND",
            f"The band {low_hz} to {high_hz} Hz holds no frequency bin.",
            f"Widen the band to at least {FFT_GRID_BPM / 60.0:.4f} Hz.",
        )
    peak_index = int(band_indices[np.argmax(power[band])])
    peak_hz = interpolated_peak_hz(freqs, power, peak_index)
    if is_flank_of_outside_peak(freqs, power, (low_hz, high_hz), peak_index):
        return RateEstimate(bpm=peak_hz * 60.0, snr_db=NOT_A_PULSE_SNR_DB)
    half_width_hz = MAIN_LOBE_BINS * fs_hz / samples.size
    return RateEstimate(
        bpm=peak_hz * 60.0, snr_db=snr_db(freqs, power, band, peak_hz, half_width_hz)
    )


def hann_power_spectrum(
    samples: NDArray[np.float64], fs_hz: float
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    centred = samples - samples.mean()
    n_fft = max(samples.size, 1 << math.ceil(math.log2(fs_hz * 60.0 / FFT_GRID_BPM)))
    power = np.abs(np.fft.rfft(centred * np.hanning(samples.size), n_fft)) ** 2
    return np.fft.rfftfreq(n_fft, 1.0 / fs_hz), power


def is_flank_of_outside_peak(
    freqs: NDArray[np.float64],
    power: NDArray[np.float64],
    band_hz: tuple[float, float],
    peak_index: int,
) -> bool:
    low_hz, high_hz = band_hz
    below = (freqs >= low_hz - OUTSIDE_REACH_HZ) & (freqs <= low_hz - EDGE_TOLERANCE_HZ)
    above = (freqs >= high_hz + EDGE_TOLERANCE_HZ) & (
        freqs <= high_hz + OUTSIDE_REACH_HZ
    )
    outside = power[(below | above) & (freqs > 0.0)]
    return bool(outside.size and outside.max() > power[peak_index])


def interpolated_peak_hz(
    freqs: NDArray[np.float64], power: NDArray[np.float64], index: int
) -> float:
    if index == 0 or index == power.size - 1:
        return float(freqs[index])
    floor = np.finfo(np.float64).tiny
    left, centre, right = np.log(np.maximum(power[index - 1 : index + 2], floor))
    curvature = left - 2.0 * centre + right
    if curvature >= 0.0:
        return float(freqs[index])
    offset = 0.5 * (left - right) / curvature
    return float(freqs[index] + offset * (freqs[1] - freqs[0]))


def snr_db(
    freqs: NDArray[np.float64],
    power: NDArray[np.float64],
    band: NDArray[np.bool_],
    peak_hz: float,
    half_width_hz: float,
) -> float:
    near_peak = (np.abs(freqs - peak_hz) <= half_width_hz) | (
        np.abs(freqs - 2.0 * peak_hz) <= half_width_hz
    )
    signal_power = float(power[band & near_peak].sum())
    noise_power = float(power[band & ~near_peak].sum())
    if signal_power <= 0.0:
        return NOT_A_PULSE_SNR_DB
    if noise_power <= 0.0:
        return CLEAN_SNR_DB
    return 10.0 * math.log10(signal_power / noise_power)
