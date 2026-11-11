import math
from dataclasses import dataclass
from itertools import combinations

import numpy as np
from numpy.typing import NDArray

from pulse_frame.signal.checks import check_region_pulses, check_sample_rate
from pulse_frame.signal.filters import (
    PASS_HIGH_HZ,
    PASS_LOW_HZ,
    zero_phase_cross_gain,
)
from pulse_frame.signal.spectrum import (
    FFT_GRID_BPM,
    MAIN_LOBE_BINS,
    SEARCH_HIGH_HZ,
    SEARCH_LOW_HZ,
    is_flank_of_outside_peak,
)

MIN_PROMINENCE_DB = 3.0
REGION_AGREEMENT_BPM = 3.0
MIN_AGREEING_REGIONS = 2
HALVES_AGREEMENT_BPM = 5.0
CLEAN_PROMINENCE_DB = 100.0
SUBHARMONIC_FLOOR_HZ = 0.3
FULL_SUBHARMONIC_LIMIT = 0.25
HALF_SUBHARMONIC_LIMIT = 0.4


@dataclass(frozen=True)
class CrossEstimate:
    bpm: float
    prominence_db: float
    region_bpms: tuple[float, ...]
    flank: bool
    subharmonic_ratio: float

    def regions_agree(self) -> bool:
        agreeing = [
            bpm
            for bpm in self.region_bpms
            if abs(bpm - self.bpm) <= REGION_AGREEMENT_BPM
        ]
        return len(agreeing) >= MIN_AGREEING_REGIONS

    def is_prominent(self) -> bool:
        return self.prominence_db >= MIN_PROMINENCE_DB

    def is_unambiguous(self, subharmonic_limit: float) -> bool:
        return self.subharmonic_ratio < subharmonic_limit

    def passes(self, subharmonic_limit: float) -> bool:
        return (
            self.regions_agree()
            and self.is_prominent()
            and not self.flank
            and self.is_unambiguous(subharmonic_limit)
        )


def is_reliable(
    full: CrossEstimate | None,
    first_half: CrossEstimate | None,
    second_half: CrossEstimate | None,
) -> bool:
    if full is None or first_half is None or second_half is None:
        return False
    halves_agree = abs(first_half.bpm - second_half.bpm) <= HALVES_AGREEMENT_BPM
    return (
        full.passes(FULL_SUBHARMONIC_LIMIT)
        and first_half.passes(HALF_SUBHARMONIC_LIMIT)
        and second_half.passes(HALF_SUBHARMONIC_LIMIT)
        and halves_agree
    )


def unit_variance(pulses: NDArray[np.float64]) -> NDArray[np.float64] | None:
    spread = pulses.std(axis=1, keepdims=True)
    if not bool(np.all(spread > 0.0)):
        return None
    return (pulses - pulses.mean(axis=1, keepdims=True)) / spread


def estimate_cross_rate(
    pulses: NDArray[np.float64], fs_hz: float
) -> CrossEstimate | None:
    samples = np.asarray(pulses, dtype=np.float64)
    check_sample_rate(fs_hz)
    check_region_pulses(samples)
    if samples.shape[0] < 2 or samples.shape[1] < 3 or fs_hz <= 2.0 * PASS_HIGH_HZ:
        return None
    with np.errstate(over="ignore", invalid="ignore"):
        freqs, spectra = region_spectra(samples, fs_hz)
        cross = whitened_cross_power(freqs, spectra)
        own = np.abs(spectra) ** 2 * freqs
    band = (freqs >= SEARCH_LOW_HZ) & (freqs <= SEARCH_HIGH_HZ)
    if not band.any() or not np.all(np.isfinite(cross)) or not np.all(np.isfinite(own)):
        return None
    peak_index = band_peak_index(cross, band)
    if cross[peak_index] <= 0.0:
        return None
    half_width_hz = MAIN_LOBE_BINS * fs_hz / samples.shape[1]
    subharmonic = subharmonic_ratio(freqs, cross, peak_index, half_width_hz, fs_hz)
    if not math.isfinite(subharmonic):
        return None
    return CrossEstimate(
        bpm=parabolic_peak_hz(freqs, cross, peak_index) * 60.0,
        prominence_db=prominence_db(freqs, cross, band, peak_index, half_width_hz),
        region_bpms=tuple(
            parabolic_peak_hz(freqs, power, band_peak_index(power, band)) * 60.0
            for power in own
        ),
        flank=is_flank_of_outside_peak(
            freqs, cross, (SEARCH_LOW_HZ, SEARCH_HIGH_HZ), peak_index
        ),
        subharmonic_ratio=subharmonic,
    )


def subharmonic_ratio(
    freqs: NDArray[np.float64],
    cross: NDArray[np.float64],
    peak_index: int,
    half_width_hz: float,
    fs_hz: float,
) -> float:
    inner = np.zeros(freqs.size, dtype=np.bool_)
    inner[1:-1] = True
    near_half = np.flatnonzero(
        inner
        & (np.abs(freqs - freqs[peak_index] / 2.0) <= half_width_hz)
        & (freqs >= SUBHARMONIC_FLOOR_HZ)
    )
    is_lobe = (cross[near_half] > cross[near_half - 1]) & (
        cross[near_half] >= cross[near_half + 1]
    )
    held = near_half[(freqs[near_half] >= PASS_LOW_HZ) | is_lobe]
    if held.size == 0:
        return 0.0
    corrected = gain_corrected(freqs, cross, np.append(held, peak_index), fs_hz)
    return float(corrected[:-1].max() / corrected[-1])


def gain_corrected(
    freqs: NDArray[np.float64],
    cross: NDArray[np.float64],
    indices: NDArray[np.intp],
    fs_hz: float,
) -> NDArray[np.float64]:
    return cross[indices] / zero_phase_cross_gain(freqs[indices], fs_hz)


def region_spectra(
    pulses: NDArray[np.float64], fs_hz: float
) -> tuple[NDArray[np.float64], NDArray[np.complex128]]:
    count = pulses.shape[1]
    exponent = max(0, math.ceil(math.log2(fs_hz * 60.0 / FFT_GRID_BPM)))
    n_fft = max(count, 1 << exponent)
    centred = pulses - pulses.mean(axis=1, keepdims=True)
    spectra = np.fft.rfft(centred * np.hanning(count), n_fft, axis=1)
    return np.fft.rfftfreq(n_fft, 1.0 / fs_hz), spectra


def whitened_cross_power(
    freqs: NDArray[np.float64], spectra: NDArray[np.complex128]
) -> NDArray[np.float64]:
    cross = np.zeros(freqs.size)
    for first, second in combinations(range(spectra.shape[0]), 2):
        cross += np.real(spectra[first] * np.conj(spectra[second]))
    return cross * freqs


def band_peak_index(values: NDArray[np.float64], band: NDArray[np.bool_]) -> int:
    band_indices = np.flatnonzero(band)
    return int(band_indices[np.argmax(values[band])])


def parabolic_peak_hz(
    freqs: NDArray[np.float64], values: NDArray[np.float64], index: int
) -> float:
    if index == 0 or index == values.size - 1:
        return float(freqs[index])
    left, centre, right = values[index - 1 : index + 2]
    curvature = left - 2.0 * centre + right
    if curvature >= 0.0:
        return float(freqs[index])
    offset = min(max(0.5 * (left - right) / curvature, -0.5), 0.5)
    return float(freqs[index] + offset * (freqs[1] - freqs[0]))


def prominence_db(
    freqs: NDArray[np.float64],
    values: NDArray[np.float64],
    band: NDArray[np.bool_],
    peak_index: int,
    half_width_hz: float,
) -> float:
    rival = strongest_rival(freqs, values, band, peak_index, half_width_hz)
    if rival <= 0.0:
        return CLEAN_PROMINENCE_DB
    return 10.0 * math.log10(values[peak_index] / rival)


def strongest_rival(
    freqs: NDArray[np.float64],
    values: NDArray[np.float64],
    band: NDArray[np.bool_],
    peak_index: int,
    half_width_hz: float,
) -> float:
    inner = values[1:-1]
    local_max = np.zeros(values.size, dtype=np.bool_)
    local_max[1:-1] = (inner > values[:-2]) & (inner >= values[2:])
    outside_lobe = np.abs(freqs - freqs[peak_index]) > half_width_hz
    outside_harmonic = np.abs(freqs - 2.0 * freqs[peak_index]) > half_width_hz
    candidates = values[band & local_max & outside_lobe & outside_harmonic]
    return float(candidates.max()) if candidates.size else 0.0
