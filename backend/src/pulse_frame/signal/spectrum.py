import numpy as np
from numpy.typing import NDArray

SEARCH_LOW_HZ = 0.7
SEARCH_HIGH_HZ = 4.0
FFT_GRID_BPM = 0.25
MAIN_LOBE_BINS = 2.0
EDGE_TOLERANCE_HZ = 0.02
OUTSIDE_REACH_HZ = 0.3


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
