import math
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from pulse_frame.signal.spectrum import SEARCH_LOW_HZ

MS_PER_MINUTE = 60_000.0
MIN_MINUTE_BPM = SEARCH_LOW_HZ * 60.0
BREATH_BEATS = 5
RESAMPLES = 2_000
RANGE_SEED = 20_261_125
PERCENTILES = (2.5, 97.5)


@dataclass(frozen=True)
class BpmRange:
    low: float
    high: float


def minute_bpm(accepted_ibis_ms: NDArray[np.float64]) -> float | None:
    bpm = float(MS_PER_MINUTE / accepted_ibis_ms.mean())
    return None if bpm < MIN_MINUTE_BPM else bpm


def block_length(count: int) -> int:
    return max(math.ceil(count ** (1.0 / 3.0)), BREATH_BEATS)


def bpm_range(accepted_ibis_ms: NDArray[np.float64]) -> BpmRange | None:
    ibis = np.asarray(accepted_ibis_ms, dtype=np.float64)
    length = block_length(ibis.size)
    if ibis.size < length + 1:
        return None
    bpm = minute_bpm(ibis)
    if bpm is None:
        return None
    low_ms, high_ms = np.percentile(resampled_means(ibis, length), PERCENTILES)
    return BpmRange(
        low=min(float(MS_PER_MINUTE / high_ms), bpm),
        high=max(float(MS_PER_MINUTE / low_ms), bpm),
    )


def resampled_means(ibis: NDArray[np.float64], length: int) -> NDArray[np.float64]:
    rng = np.random.default_rng(RANGE_SEED)
    blocks = math.ceil(ibis.size / length)
    starts = rng.integers(0, ibis.size, size=(RESAMPLES, blocks))
    picks = (starts[:, :, None] + np.arange(length)).reshape(RESAMPLES, -1)
    return ibis[picks[:, : ibis.size] % ibis.size].mean(axis=1)
