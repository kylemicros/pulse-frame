import numpy as np
import pytest
from numpy.typing import NDArray

from pulse_frame.signal.beats import Interval, label_intervals
from pulse_frame.signal.errors import SignalError
from tests.signal.beat_synthetic import frame_times
from tests.signal.synthetic import CLOCK_START_MS

DURATION_S = 60.0
STEADY_IBI_MS = 800.0
FIRST_BEAT_MS = CLOCK_START_MS + 400.0
MOTION_AT_MS = CLOCK_START_MS + 20_350.0
LOW_QUALITY_FROM_MS = CLOCK_START_MS + 30_250.0
LOW_QUALITY_TO_MS = CLOCK_START_MS + 33_480.0
FLAG_GUARD_MS = 1_600.0
OTHER_GUARDS_MS = [1_000.0, 2_000.0]
GAP_FROM_MS = CLOCK_START_MS + 40_200.0
EDGE_MS = 2_500.0
MIN_IBI_MS = 300.0
MAX_IBI_MS = 2_000.0
MEDIAN_SHARE = 0.3
OUTLIER_INDEX = 30
RUN_SHARE = 1.5


def beats_from(ibis_ms: list[float]) -> NDArray[np.float64]:
    return FIRST_BEAT_MS + np.concatenate(([0.0], np.cumsum(ibis_ms)))


def steady_beats(ibi_ms: float = STEADY_IBI_MS) -> NDArray[np.float64]:
    count = int((DURATION_S * 1000.0 - 800.0) // ibi_ms)
    return beats_from([ibi_ms] * count)


def label(
    beats_ms: NDArray[np.float64],
    sample_times_ms: NDArray[np.float64] | None = None,
    moving_at: NDArray[np.bool_] | None = None,
    low_at: NDArray[np.bool_] | None = None,
    stable_until_ms: float | None = None,
) -> list[Interval]:
    samples = frame_times(DURATION_S) if sample_times_ms is None else sample_times_ms
    no_flags = np.zeros(samples.size, dtype=np.bool_)
    return label_intervals(
        beats_ms,
        sample_times_ms=samples,
        moving=no_flags if moving_at is None else moving_at,
        low_quality=no_flags if low_at is None else low_at,
        stable_until_ms=samples[-1] + 1.0
        if stable_until_ms is None
        else stable_until_ms,
    )


def flags(intervals: list[Interval]) -> list[str]:
    return [interval.flag for interval in intervals]


def guarded_flags(
    intervals: list[Interval],
    flagged_ms: NDArray[np.float64],
    flag: str,
    guard_ms: float,
) -> list[str]:
    return [
        flag
        if bool(
            np.any(
                (flagged_ms >= i.start_ms - guard_ms)
                & (flagged_ms <= i.end_ms + guard_ms)
            )
        )
        else "ok"
        for i in intervals
    ]


def test_clean_beats_give_one_accepted_interval_per_consecutive_pair() -> None:
    beats = steady_beats()

    intervals = label(beats)

    assert len(intervals) == beats.size - 1
    assert [i.start_ms for i in intervals] == pytest.approx(beats[:-1].tolist())
    assert [i.end_ms for i in intervals] == pytest.approx(beats[1:].tolist())
    assert [i.ibi_ms for i in intervals] == pytest.approx(
        [STEADY_IBI_MS] * (beats.size - 1)
    )
    assert all(i.accepted for i in intervals)
    assert set(flags(intervals)) == {"ok"}


def test_intervals_within_the_flag_guard_of_a_motion_flagged_sample_are_rejected() -> (
    None
):
    beats = steady_beats()
    samples = frame_times(DURATION_S)
    moving = np.zeros(samples.size, dtype=np.bool_)
    moving[np.argmin(np.abs(samples - MOTION_AT_MS))] = True
    clean = label(beats)
    expected = guarded_flags(clean, samples[moving], "motion", FLAG_GUARD_MS)
    for other_ms in OTHER_GUARDS_MS:
        assert guarded_flags(clean, samples[moving], "motion", other_ms) != expected

    intervals = label(beats, moving_at=moving)

    assert expected.count("motion") >= 4
    assert flags(intervals) == expected


def test_intervals_within_the_flag_guard_of_a_low_quality_span_are_rejected() -> None:
    beats = steady_beats()
    samples = frame_times(DURATION_S)
    low = (samples >= LOW_QUALITY_FROM_MS) & (samples <= LOW_QUALITY_TO_MS)
    clean = label(beats)
    expected = guarded_flags(clean, samples[low], "low_quality", FLAG_GUARD_MS)
    for other_ms in OTHER_GUARDS_MS:
        assert guarded_flags(clean, samples[low], "low_quality", other_ms) != expected

    intervals = label(beats, low_at=low)

    assert expected.count("low_quality") >= 8
    assert flags(intervals) == expected


def test_intervals_across_a_sample_gap_over_one_second_are_rejected() -> None:
    beats = steady_beats()
    samples = frame_times(DURATION_S)
    gap_to_ms = GAP_FROM_MS + 1_300.0
    kept = samples[(samples <= GAP_FROM_MS) | (samples >= gap_to_ms)]
    flags_off = np.zeros(kept.size, dtype=np.bool_)

    intervals = label(
        beats, sample_times_ms=kept, moving_at=flags_off, low_at=flags_off
    )

    last_before = float(kept[kept <= GAP_FROM_MS][-1])
    first_after = float(kept[kept >= gap_to_ms][0])
    hit = [i.start_ms < first_after and i.end_ms > last_before for i in intervals]
    assert sum(hit) >= 2
    assert flags(intervals) == ["gap" if h else "ok" for h in hit]


def test_a_sample_gap_under_one_second_keeps_every_interval() -> None:
    beats = steady_beats()
    samples = frame_times(DURATION_S)
    kept = samples[(samples <= GAP_FROM_MS) | (samples >= GAP_FROM_MS + 900.0)]
    flags_off = np.zeros(kept.size, dtype=np.bool_)

    intervals = label(
        beats, sample_times_ms=kept, moving_at=flags_off, low_at=flags_off
    )

    assert set(flags(intervals)) == {"ok"}


def test_intervals_ending_in_the_unsettled_newest_edge_are_rejected() -> None:
    beats = steady_beats()
    samples = frame_times(DURATION_S)
    stable_until = float(samples[-1]) - EDGE_MS

    intervals = label(beats, stable_until_ms=stable_until)

    late = [i.end_ms > stable_until for i in intervals]
    assert sum(late) >= 2
    assert flags(intervals) == ["edge" if is_late else "ok" for is_late in late]


@pytest.mark.parametrize(
    ("ibi_ms", "flag"),
    [
        (MIN_IBI_MS - 10.0, "out_of_range"),
        (MIN_IBI_MS + 10.0, "ok"),
        (MAX_IBI_MS - 50.0, "ok"),
        (MAX_IBI_MS + 100.0, "out_of_range"),
    ],
    ids=["too_short", "shortest_kept", "longest_kept", "too_long"],
)
def test_intervals_outside_three_hundred_to_two_thousand_ms_are_rejected(
    ibi_ms: float, flag: str
) -> None:
    intervals = label(steady_beats(ibi_ms))

    assert len(intervals) >= 20
    assert set(flags(intervals)) == {flag}


@pytest.mark.parametrize(
    ("outlier_share", "flag"),
    [
        (2.0, "off_median"),
        (1.0 + MEDIAN_SHARE + 0.05, "off_median"),
        (1.0 - MEDIAN_SHARE - 0.05, "off_median"),
        (1.0 + MEDIAN_SHARE - 0.05, "ok"),
        (1.0 - MEDIAN_SHARE + 0.05, "ok"),
    ],
    ids=[
        "missed_beat",
        "long_past_limit",
        "short_past_limit",
        "long_inside",
        "short_inside",
    ],
)
def test_an_interval_more_than_thirty_percent_from_its_local_median_is_rejected(
    outlier_share: float, flag: str
) -> None:
    ibis = [STEADY_IBI_MS] * 60
    ibis[OUTLIER_INDEX] = STEADY_IBI_MS * outlier_share

    intervals = label(beats_from(ibis))

    expected = ["ok"] * len(ibis)
    expected[OUTLIER_INDEX] = flag
    assert flags(intervals) == expected


@pytest.mark.parametrize("run", [2, 3])
def test_a_short_run_of_long_intervals_is_rejected_against_the_wider_median(
    run: int,
) -> None:
    ibis = [STEADY_IBI_MS] * 60
    for index in range(OUTLIER_INDEX, OUTLIER_INDEX + run):
        ibis[index] = STEADY_IBI_MS * RUN_SHARE

    intervals = label(beats_from(ibis))

    expected = ["ok"] * len(ibis)
    expected[OUTLIER_INDEX : OUTLIER_INDEX + run] = ["off_median"] * run
    assert flags(intervals) == expected


@pytest.mark.parametrize(
    ("keyword", "which"), [("moving_at", "moving"), ("low_at", "low_quality")]
)
def test_one_flag_too_few_raises_bad_values(keyword: str, which: str) -> None:
    samples = frame_times(DURATION_S)
    short = np.zeros(samples.size - 1, dtype=np.bool_)

    with pytest.raises(SignalError) as caught:
        label(steady_beats(), **{keyword: short})

    assert caught.value.code == "BAD_VALUES"
    assert which in caught.value.message
    assert caught.value.action


def with_nan(values: NDArray[np.float64], index: int) -> NDArray[np.float64]:
    broken = values.copy()
    broken[index] = np.nan
    return broken


@pytest.mark.parametrize(
    "case",
    ["nan_beat", "two_d_beats", "nan_sample_time", "two_d_sample_times", "nan_stable"],
)
def test_bad_beat_or_sample_times_raise_bad_timestamps(case: str) -> None:
    beats = steady_beats()
    samples = frame_times(DURATION_S)
    no_flags = np.zeros(samples.size, dtype=np.bool_)
    arguments = {
        "nan_beat": (with_nan(beats, 5), samples, samples[-1]),
        "two_d_beats": (beats[:, None], samples, samples[-1]),
        "nan_sample_time": (beats, with_nan(samples, 100), samples[-1]),
        "two_d_sample_times": (beats, samples[:, None], samples[-1]),
        "nan_stable": (beats, samples, np.nan),
    }
    beat_times, sample_times, stable_until = arguments[case]

    with pytest.raises(SignalError) as caught:
        label_intervals(
            beat_times,
            sample_times_ms=sample_times,
            moving=no_flags,
            low_quality=no_flags,
            stable_until_ms=float(stable_until),
        )

    assert caught.value.code == "BAD_TIMESTAMPS"
    assert caught.value.action
