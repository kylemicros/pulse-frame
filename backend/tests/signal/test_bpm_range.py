import math

import numpy as np
import pytest
from numpy.typing import NDArray
from scipy import stats

from pulse_frame.signal import summary
from pulse_frame.signal.beats import Interval, IntervalFlag
from pulse_frame.signal.bpm_range import (
    BREATH_BEATS,
    BpmRange,
    block_length,
    bpm_range,
    minute_bpm,
)
from pulse_frame.signal.hrv import STALE_MS
from tests.counted_runs import HALF_RATE_IBI_MS, chain, ramped

TRUE_BPM = 72.0
TRUE_IBI_MS = 60_000.0 / TRUE_BPM
MINUTE_BEATS = 72
DRIFT_PHI = 0.8
DRIFT_SD_MS = 30.0
RSA_AMPLITUDE_MS = 20.0
BEATS_PER_BREATH = 4.8
WHITE_SD_MS = 5.0
CLEANER_SCALE = 0.5
MINUTE_SEEDS = [11, 23, 37, 41, 53, 67, 79, 83]
IID_SEED = 2_026
IID_RESAMPLES = 2_000
COVERAGE_MINUTES = 400
COVERAGE_FIRST_SEED = 1_000
SPREAD_RATES_BPM = (55.0, 95.0)
RAW_COVERAGE_FLOOR = 0.65
SHOWN_COVERAGE_FLOOR = 0.82
UNEVEN_LAST_PLACE_BASE_MS = 455.0
UNEVEN_LAST_PLACE_STEPS = [
    1,
    -2,
    1,
    -2,
    1,
    1,
    2,
    1,
    -1,
    -1,
    1,
    -1,
    -2,
    2,
    2,
    1,
    -2,
    -2,
    1,
    0,
]
BLOCKS_WIDER_BY = 1.15
CLEANER_NARROWER_BY = 0.75
SANE_WIDTH_BPM = (1.0, 6.0)
NEWEST_MS = 400_000.0
GATE_BEATS = 60
GATE_IBI_MS = 800.0
SHORT_REJECTED_MS = 200.0
TOO_MANY_REJECTED = 16
FEW_ENOUGH_REJECTED = 14
STALE_GAP_MS = STALE_MS + 1_000.0
UNDER_FLOOR_BEATS = 30
SLOWER_THAN_FLOOR_IBI_MS = 1_500.0
SLOW_BEATS = 40
ANY_SEEDS = [1, 2, 3, 4, 5]


def rsa_minute(
    seed: int,
    scale: float = 1.0,
    centred: bool = True,
    rate_bpm: float = TRUE_BPM,
) -> NDArray[np.float64]:
    rng = np.random.default_rng(seed)
    drift = np.empty(MINUTE_BEATS)
    drift[0] = rng.normal(0.0, DRIFT_SD_MS)
    shocks = rng.normal(0.0, DRIFT_SD_MS * math.sqrt(1.0 - DRIFT_PHI**2), MINUTE_BEATS)
    for k in range(1, MINUTE_BEATS):
        drift[k] = DRIFT_PHI * drift[k - 1] + shocks[k]
    phase = rng.uniform(0.0, 2.0 * np.pi)
    beats = np.arange(MINUTE_BEATS)
    rsa = RSA_AMPLITUDE_MS * np.sin(2.0 * np.pi * beats / BEATS_PER_BREATH + phase)
    white = rng.normal(0.0, WHITE_SD_MS, MINUTE_BEATS)
    wobble = scale * (drift + rsa + white)
    centre = wobble.mean() if centred else 0.0
    return 60_000.0 / rate_bpm + wobble - centre


def iid_width_bpm(ibis_ms: NDArray[np.float64]) -> float:
    found = stats.bootstrap(
        (ibis_ms,),
        np.mean,
        n_resamples=IID_RESAMPLES,
        method="percentile",
        rng=np.random.default_rng(IID_SEED),
    )
    interval = found.confidence_interval
    return float(60_000.0 / interval.low - 60_000.0 / interval.high)


def covers(found: BpmRange | None, rate: float) -> bool:
    assert found is not None
    return found.low <= rate <= found.high


def rounded_outward(found: BpmRange | None) -> BpmRange:
    assert found is not None
    return BpmRange(
        low=math.floor(round(found.low, 1)), high=math.ceil(round(found.high, 1))
    )


def width(found: BpmRange | None) -> float:
    assert found is not None
    return found.high - found.low


def any_minute(kind: str, seed: int) -> NDArray[np.float64]:
    rng = np.random.default_rng(seed)
    if kind == "iid":
        return rng.normal(TRUE_IBI_MS, 40.0, MINUTE_BEATS)
    if kind == "skewed":
        return 600.0 + rng.lognormal(4.5, 0.9, MINUTE_BEATS)
    if kind == "one_outlier":
        ibis = rng.normal(TRUE_IBI_MS, 10.0, MINUTE_BEATS)
        ibis[seed] = 1_400.0
        return ibis
    if kind == "shortest":
        return rng.normal(TRUE_IBI_MS, 60.0, BREATH_BEATS + 1)
    if kind == "long":
        return rng.normal(700.0, 50.0, 344)
    return rsa_minute(seed)


@pytest.mark.parametrize("seed", MINUTE_SEEDS)
def test_the_range_of_a_breathing_minute_is_sane_and_wider_than_iid_resampling(
    seed: int,
) -> None:
    ibis = rsa_minute(seed)

    found = bpm_range(ibis)

    assert SANE_WIDTH_BPM[0] < width(found) < SANE_WIDTH_BPM[1]
    assert width(found) > BLOCKS_WIDER_BY * iid_width_bpm(ibis)


def spread_rates() -> NDArray[np.float64]:
    slowest, fastest = SPREAD_RATES_BPM
    middles = (np.arange(COVERAGE_MINUTES) + 0.5) / COVERAGE_MINUTES
    return slowest + (fastest - slowest) * middles


def test_breathing_minutes_at_spread_rates_are_covered_as_often_as_measured() -> None:
    rates = spread_rates()
    ranges = [
        bpm_range(rsa_minute(COVERAGE_FIRST_SEED + k, centred=False, rate_bpm=rate))
        for k, rate in enumerate(rates)
    ]

    raw = np.mean([covers(f, r) for f, r in zip(ranges, rates, strict=True)])
    shown = np.mean(
        [covers(rounded_outward(f), r) for f, r in zip(ranges, rates, strict=True)]
    )

    assert raw >= RAW_COVERAGE_FLOOR, raw
    assert shown >= SHOWN_COVERAGE_FLOOR, shown


@pytest.mark.parametrize("seed", MINUTE_SEEDS)
def test_a_cleaner_minute_gives_a_narrower_range(seed: int) -> None:
    noisy = bpm_range(rsa_minute(seed))
    cleaner = bpm_range(rsa_minute(seed, CLEANER_SCALE))

    assert width(cleaner) < CLEANER_NARROWER_BY * width(noisy)


@pytest.mark.parametrize(
    ("count", "expected"),
    [(6, 5), (27, 5), (72, 5), (126, 6), (344, 8)],
)
def test_the_block_is_a_breath_of_beats_or_the_cube_root_if_longer(
    count: int, expected: int
) -> None:
    assert block_length(count) == expected


def test_the_same_minute_always_gives_the_same_range() -> None:
    ibis = rsa_minute(MINUTE_SEEDS[0])

    first = bpm_range(ibis)
    second = bpm_range(ibis.copy())
    third = bpm_range(np.asarray(ibis.tolist()))

    assert first is not None
    assert first == second == third


@pytest.mark.parametrize("count", [0, 1, BREATH_BEATS - 1, BREATH_BEATS])
def test_fewer_beats_than_one_block_plus_one_give_no_range(count: int) -> None:
    assert bpm_range(np.full(count, TRUE_IBI_MS)) is None


def test_one_beat_more_than_a_block_gives_a_range() -> None:
    assert bpm_range(any_minute("shortest", ANY_SEEDS[0])) is not None


def test_a_minute_slower_than_the_minute_floor_gives_no_range() -> None:
    rng = np.random.default_rng(ANY_SEEDS[0])
    ibis = rng.normal(SLOWER_THAN_FLOOR_IBI_MS, 20.0, SLOW_BEATS)

    assert minute_bpm(ibis) is None
    assert bpm_range(ibis) is None


@pytest.mark.parametrize("seed", ANY_SEEDS)
@pytest.mark.parametrize(
    "kind", ["iid", "skewed", "one_outlier", "shortest", "long", "breathing"]
)
def test_the_range_always_holds_the_minute_bpm(kind: str, seed: int) -> None:
    ibis = any_minute(kind, seed)
    bpm = minute_bpm(ibis)

    found = bpm_range(ibis)

    assert bpm is not None
    assert found is not None
    assert math.isfinite(found.low)
    assert math.isfinite(found.high)
    assert found.low <= bpm <= found.high


def test_a_steady_minute_gives_a_range_of_its_one_rate() -> None:
    ibis = np.full(MINUTE_BEATS, 800.0)

    found = bpm_range(ibis)

    assert found == BpmRange(low=75.0, high=75.0)


@pytest.mark.parametrize("sign", [1, -1], ids=["low_end", "high_end"])
def test_a_range_rounding_past_its_minute_bpm_is_held_to_it(sign: int) -> None:
    base_ms = UNEVEN_LAST_PLACE_BASE_MS
    steps = sign * np.array(UNEVEN_LAST_PLACE_STEPS)
    ibis = base_ms + steps * np.spacing(base_ms)
    bpm = minute_bpm(ibis)

    found = bpm_range(ibis)

    assert bpm is not None
    assert found is not None
    assert found.low <= bpm <= found.high


def newest_accepted_ibis(intervals: list[Interval]) -> NDArray[np.float64]:
    span = summary.newest_span(intervals, NEWEST_MS)
    return np.array([i.ibi_ms for i in span if i.accepted], dtype=np.float64)


def test_the_summary_carries_the_range_of_its_newest_minute() -> None:
    intervals, checks = ramped(TRUE_IBI_MS, NEWEST_MS)

    result = summary.summarise(intervals, NEWEST_MS, checks)

    expected = bpm_range(newest_accepted_ibis(intervals))
    assert result.bpm is not None
    assert expected is not None
    assert (result.bpm_low, result.bpm_high) == (expected.low, expected.high)
    assert result.bpm_low <= result.bpm <= result.bpm_high


def test_a_summary_built_without_a_range_has_none() -> None:
    assert summary.NO_SUMMARY.bpm_low is None
    assert summary.NO_SUMMARY.bpm_high is None


def interleaved(rejected: int) -> list[Interval]:
    ibis = [GATE_IBI_MS] * GATE_BEATS + [SHORT_REJECTED_MS] * rejected
    flags: list[IntervalFlag] = ["ok"] * GATE_BEATS + ["motion"] * rejected
    places = np.r_[np.arange(GATE_BEATS), np.linspace(0, GATE_BEATS, rejected)]
    order = np.argsort(places, kind="stable")
    start_ms = NEWEST_MS - float(np.sum(ibis))
    edges = start_ms + np.concatenate(([0.0], np.cumsum(np.array(ibis)[order])))
    return [
        Interval(float(s), float(e), flags[k])
        for s, e, k in zip(edges[:-1], edges[1:], order, strict=True)
    ]


def gated(case: str, passes: bool) -> list[Interval]:
    if case == "stale":
        end_ms = NEWEST_MS if passes else NEWEST_MS - STALE_GAP_MS
        return chain([GATE_IBI_MS] * GATE_BEATS, end_ms)
    if case == "too_many_rejected":
        return interleaved(FEW_ENOUGH_REJECTED if passes else TOO_MANY_REJECTED)
    if case == "under_the_45_second_floor":
        beats = GATE_BEATS if passes else UNDER_FLOOR_BEATS
        return chain([GATE_IBI_MS] * beats, NEWEST_MS)
    ibi_ms = TRUE_IBI_MS if passes else HALF_RATE_IBI_MS
    return ramped(ibi_ms, NEWEST_MS)[0]


@pytest.mark.parametrize(
    "case",
    ["stale", "too_many_rejected", "under_the_45_second_floor", "half_rate"],
)
def test_no_minute_bpm_means_no_range(case: str) -> None:
    passing = summary.summarise(gated(case, True), NEWEST_MS, [])
    failing = summary.summarise(gated(case, False), NEWEST_MS, [])

    assert passing.bpm is not None
    assert passing.bpm_low is not None
    assert passing.bpm_high is not None
    assert failing.bpm is None
    assert failing.count > 0
    assert failing.bpm_low is None
    assert failing.bpm_high is None
