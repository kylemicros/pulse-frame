import math

import numpy as np
import pytest

from pulse_frame.signal.beats import Interval, IntervalFlag
from pulse_frame.signal.errors import SignalError
from pulse_frame.signal.hrv import (
    HrvReading,
    SegmentBeats,
    beat_spreads,
    hrv_reading,
    nearest_offsets,
)
from tests.frames import SEED
from tests.signal.beat_synthetic import chain, respiring_ibis, rmssd, sdnn

FORMULA_TOLERANCE_MS = 0.1
WINDOW_TOLERANCE_MS = 0.5
WINDOW_S = 300.0
MIN_ACCEPTED_S = 60.0
MAX_REJECTED_SHARE = 0.2
STEADY_IBI_MS = 800.0
WINDOW_FILLING_IBIS = 376
SETTLED_IBIS = 100
MOTION_IBIS = 18
EDGE_IBIS = 5
MAX_IBI_MS = 2_000.0
ALTERNATING_PAIR_MS = (700.0, 900.0)
QUIET_BEFORE_ALTERNATION_MS = 30_000.0
BLOCK_MS = 25_000.0


def flagged(count: int, rejected: int) -> list[IntervalFlag]:
    marks: list[IntervalFlag] = ["ok"] * count
    for index in np.linspace(2, count - 3, rejected).round().astype(int):
        marks[index] = "motion"
    return marks


def assert_null(reading: HrvReading) -> None:
    assert reading.rmssd_ms is None
    assert reading.sdnn_ms is None


def test_rmssd_and_sdnn_match_the_formulas_on_a_known_ibi_series() -> None:
    rng = np.random.default_rng(SEED)
    ibis = list(850.0 + rng.normal(0.0, 40.0, 120))

    reading = hrv_reading(chain(ibis))

    assert reading.rmssd_ms == pytest.approx(rmssd(ibis), abs=FORMULA_TOLERANCE_MS)
    assert reading.sdnn_ms == pytest.approx(sdnn(ibis), abs=FORMULA_TOLERANCE_MS)


def test_rejected_intervals_are_left_out_and_never_bridged() -> None:
    rng = np.random.default_rng(SEED + 1)
    ibis = list(800.0 + rng.normal(0.0, 30.0, 110))
    marks = flagged(len(ibis), 10)
    accepted = [ibi for ibi, mark in zip(ibis, marks, strict=True) if mark == "ok"]
    pairs = [
        ibis[i + 1] - ibis[i]
        for i in range(len(ibis) - 1)
        if marks[i] == "ok" and marks[i + 1] == "ok"
    ]

    reading = hrv_reading(chain(ibis, flags=marks))

    expected_rmssd = float(np.sqrt(np.mean(np.square(pairs))))
    assert reading.rmssd_ms == pytest.approx(expected_rmssd, abs=FORMULA_TOLERANCE_MS)
    assert reading.sdnn_ms == pytest.approx(sdnn(accepted), abs=FORMULA_TOLERANCE_MS)


def test_successive_differences_never_span_a_time_gap_between_chains() -> None:
    first = chain([STEADY_IBI_MS] * 40)
    second = chain([1_000.0] * 40, start_ms=first[-1].end_ms + 5_000.0)
    ibis = [i.ibi_ms for i in first + second]

    reading = hrv_reading(first + second)

    assert reading.rmssd_ms == pytest.approx(0.0, abs=FORMULA_TOLERANCE_MS)
    assert reading.sdnn_ms == pytest.approx(sdnn(ibis), abs=FORMULA_TOLERANCE_MS)


def test_successive_differences_never_span_a_rejected_gap_interval() -> None:
    ibis = [STEADY_IBI_MS] * 40 + [1_400.0] + [1_000.0] * 40
    marks: list[IntervalFlag] = ["ok"] * 40 + ["gap"] + ["ok"] * 40

    reading = hrv_reading(chain(ibis, flags=marks))

    assert reading.rmssd_ms == pytest.approx(0.0, abs=FORMULA_TOLERANCE_MS)
    assert reading.sdnn_ms == pytest.approx(
        sdnn([STEADY_IBI_MS] * 40 + [1_000.0] * 40), abs=FORMULA_TOLERANCE_MS
    )


@pytest.mark.parametrize("count", [0, 1, 2, 74])
def test_null_under_sixty_seconds_of_accepted_beats(count: int) -> None:
    assert_null(hrv_reading(chain(respiring_ibis(count))))


def test_values_from_just_over_sixty_seconds_of_accepted_beats() -> None:
    ibis = respiring_ibis(76)
    assert sum(ibis) > MIN_ACCEPTED_S * 1000.0

    reading = hrv_reading(chain(ibis))

    assert reading.rmssd_ms == pytest.approx(rmssd(ibis), abs=FORMULA_TOLERANCE_MS)
    assert reading.sdnn_ms == pytest.approx(sdnn(ibis), abs=FORMULA_TOLERANCE_MS)


def test_rejected_intervals_do_not_count_toward_the_sixty_seconds() -> None:
    ibis = [STEADY_IBI_MS] * 80
    marks = flagged(len(ibis), 8)
    assert sum(ibis) > MIN_ACCEPTED_S * 1000.0
    assert marks.count("ok") * STEADY_IBI_MS < MIN_ACCEPTED_S * 1000.0

    assert_null(hrv_reading(chain(ibis, flags=marks)))


@pytest.mark.parametrize(
    ("rejected", "is_null"),
    [(20, False), (21, True), (30, True)],
    ids=["at_the_limit", "just_over", "far_over"],
)
def test_null_when_over_a_fifth_of_the_intervals_are_rejected(
    rejected: int, is_null: bool
) -> None:
    ibis = respiring_ibis(100, base_ms=1_000.0)
    marks = flagged(len(ibis), rejected)
    assert marks.count("ok") * 900.0 > MIN_ACCEPTED_S * 1000.0
    assert len(ibis) - marks.count("ok") == rejected

    reading = hrv_reading(chain(ibis, flags=marks))

    assert (reading.rmssd_ms is None) is is_null
    assert (reading.sdnn_ms is None) is is_null


def test_only_about_the_newest_three_hundred_seconds_count() -> None:
    wild = [600.0, 1_000.0] * 60
    calm = respiring_ibis(200, swing_ms=20.0)
    lively = respiring_ibis(200, swing_ms=60.0)
    intervals = chain(wild + calm + lively)
    cutoff_ms = intervals[-1].end_ms - WINDOW_S * 1000.0
    window = [i.ibi_ms for i in intervals if i.start_ms >= cutoff_ms]

    reading = hrv_reading(intervals)

    assert reading.rmssd_ms == pytest.approx(rmssd(window), abs=WINDOW_TOLERANCE_MS)
    assert reading.sdnn_ms == pytest.approx(sdnn(window), abs=WINDOW_TOLERANCE_MS)


def test_intervals_starting_before_the_newest_three_hundred_s_are_left_out() -> None:
    lively = respiring_ibis(WINDOW_FILLING_IBIS, swing_ms=60.0)
    wild = [600.0, 1_000.0] * 12
    calm = respiring_ibis(100, swing_ms=20.0)
    intervals = chain(calm + wild + lively)
    cutoff_ms = intervals[-1].end_ms - WINDOW_S * 1000.0
    window = [i.ibi_ms for i in intervals if i.start_ms >= cutoff_ms]
    assert sum(lively) > WINDOW_S * 1000.0
    assert sum(lively) - WINDOW_S * 1000.0 < STEADY_IBI_MS + 60.0

    reading = hrv_reading(intervals)

    assert reading.rmssd_ms == pytest.approx(rmssd(window), abs=WINDOW_TOLERANCE_MS)
    assert reading.sdnn_ms == pytest.approx(sdnn(window), abs=WINDOW_TOLERANCE_MS)


def test_unsettled_edge_intervals_are_left_out_of_the_rejected_share() -> None:
    ibis = respiring_ibis(SETTLED_IBIS + EDGE_IBIS, base_ms=1_000.0)
    unsettled: list[IntervalFlag] = ["edge"] * EDGE_IBIS
    marks = flagged(SETTLED_IBIS, MOTION_IBIS) + unsettled
    accepted = [ibi for ibi, mark in zip(ibis, marks, strict=True) if mark == "ok"]
    pairs = [
        ibis[i + 1] - ibis[i]
        for i in range(len(ibis) - 1)
        if marks[i] == "ok" and marks[i + 1] == "ok"
    ]
    assert MOTION_IBIS / SETTLED_IBIS <= MAX_REJECTED_SHARE
    assert (MOTION_IBIS + EDGE_IBIS) / len(ibis) > MAX_REJECTED_SHARE

    reading = hrv_reading(chain(ibis, flags=marks))

    expected_rmssd = float(np.sqrt(np.mean(np.square(pairs))))
    assert reading.rmssd_ms == pytest.approx(expected_rmssd, abs=FORMULA_TOLERANCE_MS)
    assert reading.sdnn_ms == pytest.approx(sdnn(accepted), abs=FORMULA_TOLERANCE_MS)


@pytest.mark.parametrize("after_ms", [None, 2_000.0], ids=["no_sample_time", "later"])
def test_a_chain_of_only_edge_intervals_reads_null(after_ms: float | None) -> None:
    unsettled: list[IntervalFlag] = ["edge"] * 100
    intervals = chain([STEADY_IBI_MS] * 100, flags=unsettled)
    newest_ms = None if after_ms is None else intervals[-1].end_ms + after_ms

    assert_null(hrv_reading(intervals, newest_sample_ms=newest_ms))


@pytest.mark.parametrize("age_ms", [7_000.0, 8_000.0, 9_000.0])
def test_a_reading_stays_while_the_newest_accepted_interval_is_under_ten_s_old(
    age_ms: float,
) -> None:
    ibis = respiring_ibis(100)
    intervals = chain(ibis)

    reading = hrv_reading(intervals, newest_sample_ms=intervals[-1].end_ms + age_ms)

    assert reading.rmssd_ms == pytest.approx(rmssd(ibis), abs=FORMULA_TOLERANCE_MS)
    assert reading.sdnn_ms == pytest.approx(sdnn(ibis), abs=FORMULA_TOLERANCE_MS)


@pytest.mark.parametrize("count", [100, 0], ids=["intervals", "no_intervals"])
@pytest.mark.parametrize(
    "newest_sample_ms",
    [math.nan, math.inf, np.array([1_000.0, 2_000.0])],
    ids=["nan", "inf", "array"],
)
def test_a_bad_newest_sample_time_raises_bad_timestamps(
    newest_sample_ms: float, count: int
) -> None:
    intervals = chain([STEADY_IBI_MS] * count)

    with pytest.raises(SignalError) as caught:
        hrv_reading(intervals, newest_sample_ms=newest_sample_ms)

    assert caught.value.code == "BAD_TIMESTAMPS"
    assert caught.value.action


def alternating_after_quiet(count: int) -> tuple[list[Interval], list[float]]:
    steady = respiring_ibis(100)
    first = chain(steady)
    swinging = [ALTERNATING_PAIR_MS[k % 2] for k in range(count)]
    start_ms = first[-1].end_ms + QUIET_BEFORE_ALTERNATION_MS
    second = chain(swinging, start_ms=start_ms)
    pairs = [*np.diff(steady), *np.diff(swinging)]
    return first + second, pairs


def test_an_alternating_stretch_of_seven_runs_of_three_does_not_null() -> None:
    intervals, pairs = alternating_after_quiet(9)
    ibis = [i.ibi_ms for i in intervals]
    assert intervals[-1].end_ms - intervals[-9].start_ms < BLOCK_MS
    assert QUIET_BEFORE_ALTERNATION_MS > BLOCK_MS

    reading = hrv_reading(intervals)

    expected_rmssd = float(np.sqrt(np.mean(np.square(pairs))))
    assert reading.rmssd_ms == pytest.approx(expected_rmssd, abs=FORMULA_TOLERANCE_MS)
    assert reading.sdnn_ms == pytest.approx(sdnn(ibis), abs=FORMULA_TOLERANCE_MS)


def test_an_alternating_stretch_of_eight_runs_of_three_nulls() -> None:
    intervals, _ = alternating_after_quiet(10)

    assert_null(hrv_reading(intervals))


@pytest.mark.parametrize(
    ("candidates_ms", "expected_ms"),
    [([], -MAX_IBI_MS), ([7_000.0], MAX_IBI_MS), ([-4_000.0], -MAX_IBI_MS)],
    ids=["no_beats", "far_later", "far_earlier"],
)
def test_nearest_offsets_are_clipped_to_the_longest_interval(
    candidates_ms: list[float], expected_ms: float
) -> None:
    beats = np.array([0.0, 500.0, 1_000.0])

    offsets = nearest_offsets(beats, np.array(candidates_ms, dtype=np.float64))

    assert offsets.tolist() == [expected_ms] * 3


def test_a_region_with_no_beats_gives_a_finite_spread_at_the_clip() -> None:
    beats = np.array([10_000.0, 10_800.0, 11_600.0])
    segment = SegmentBeats(
        first_ms=5_000.0,
        last_ms=math.inf,
        beats_ms=beats,
        region_beats_ms=(beats, beats + 6.0, np.empty(0)),
    )

    spreads = beat_spreads(beats, [segment])

    expected = float(np.std([0.0, 6.0, -MAX_IBI_MS]))
    assert np.isfinite(spreads).all()
    assert spreads.tolist() == pytest.approx([expected] * 3, abs=1e-9)


def test_reading_reports_the_span_and_the_accepted_count_it_used() -> None:
    ibis = respiring_ibis(SETTLED_IBIS)
    marks = flagged(len(ibis), 10)

    reading = hrv_reading(chain(ibis, flags=marks))

    assert reading.window_ms == pytest.approx(sum(ibis), abs=WINDOW_TOLERANCE_MS)
    assert reading.accepted_count == marks.count("ok")


def test_reading_window_never_spans_more_than_three_hundred_seconds() -> None:
    ibis = respiring_ibis(WINDOW_FILLING_IBIS)
    intervals = chain(ibis)
    newest_ms = intervals[-1].end_ms
    inside = [i for i in intervals if i.start_ms >= newest_ms - WINDOW_S * 1000.0]

    reading = hrv_reading(intervals)

    assert reading.window_ms is not None
    assert reading.window_ms <= WINDOW_S * 1000.0
    assert reading.window_ms == pytest.approx(
        newest_ms - inside[0].start_ms, abs=WINDOW_TOLERANCE_MS
    )
    assert reading.accepted_count == len(inside)


def test_no_reading_carries_no_window_and_no_accepted_count() -> None:
    reading = hrv_reading(chain(respiring_ibis(EDGE_IBIS)))

    assert_null(reading)
    assert reading.window_ms is None
    assert reading.accepted_count is None
