import numpy as np
import pytest

from pulse_frame.signal.hrv import alternates, hrv_reading
from tests.frames import SEED, TRUE_BPM
from tests.signal.beat_synthetic import chain, jittered_ibis, period_ms

BEATS = 75
JITTER_SEEDS = 1000
MAX_JITTER_FIRE_SHARE = 0.02
POWER_SEEDS = 200
MIN_POWER = 0.9
DETECTABLE_OFFSET_MS = 150.0
POWER_JITTER_MS = 40.0
FIXED_OFFSET_MS = 25.0
UNDER_FLOOR_OFFSET_MS = 8.0
OFFSET_SEED = SEED + 7


def fires(seed: int, bpm: float, jitter_ms: float, offset_ms: float) -> bool:
    rng = np.random.default_rng(seed)
    ibis = jittered_ibis(rng, BEATS - 1, period_ms(bpm), jitter_ms, offset_ms)
    assert min(ibis) > 0.0
    return alternates(chain(ibis))


@pytest.mark.parametrize("bpm", [TRUE_BPM, 50.0])
@pytest.mark.parametrize("jitter_ms", [20.0, 40.0, 80.0, 120.0])
def test_white_beat_time_jitter_fires_the_alternation_gate_in_at_most_two_percent(
    jitter_ms: float, bpm: float
) -> None:
    fired = sum(fires(SEED + seed, bpm, jitter_ms, 0.0) for seed in range(JITTER_SEEDS))

    assert fired <= MAX_JITTER_FIRE_SHARE * JITTER_SEEDS, (
        f"{fired} of {JITTER_SEEDS} jitter-only runs fired the gate"
    )


@pytest.mark.parametrize(
    "offset_ms",
    [FIXED_OFFSET_MS, -FIXED_OFFSET_MS],
    ids=["long_first", "short_first"],
)
def test_a_fixed_25_ms_long_short_offset_without_jitter_fires_the_gate(
    offset_ms: float,
) -> None:
    assert fires(OFFSET_SEED, TRUE_BPM, 0.0, offset_ms)


@pytest.mark.parametrize(
    "offset_ms",
    [UNDER_FLOOR_OFFSET_MS, -UNDER_FLOOR_OFFSET_MS],
    ids=["long_first", "short_first"],
)
def test_an_exact_8_ms_long_short_difference_is_under_the_size_floor(
    offset_ms: float,
) -> None:
    rng = np.random.default_rng(OFFSET_SEED)
    ibis = jittered_ibis(
        rng, BEATS - 1, period_ms(TRUE_BPM), 0.0, offset_ms, swing_ms=0.0
    )

    assert not alternates(chain(ibis))


@pytest.mark.parametrize(
    ("offset_ms", "shown"),
    [(0.0, True), (FIXED_OFFSET_MS, False), (-FIXED_OFFSET_MS, False)],
    ids=["no_offset", "long_first", "short_first"],
)
def test_a_reading_shows_without_an_offset_and_is_null_with_a_25_ms_offset(
    offset_ms: float, shown: bool
) -> None:
    rng = np.random.default_rng(OFFSET_SEED)
    ibis = jittered_ibis(rng, BEATS - 1, period_ms(TRUE_BPM), 0.0, offset_ms)

    reading = hrv_reading(chain(ibis))

    assert (reading.rmssd_ms is not None) is shown
    assert (reading.sdnn_ms is not None) is shown


def test_a_150_ms_offset_fires_the_gate_in_nine_of_ten_runs_at_40_ms_jitter() -> None:
    fired = sum(
        fires(SEED + seed, TRUE_BPM, POWER_JITTER_MS, DETECTABLE_OFFSET_MS)
        for seed in range(POWER_SEEDS)
    )

    assert fired >= MIN_POWER * POWER_SEEDS, (
        f"only {fired} of {POWER_SEEDS} offset runs fired the gate"
    )
