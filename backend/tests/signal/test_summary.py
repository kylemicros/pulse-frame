import inspect
import math
import re
from pathlib import Path

import numpy as np
import pytest

from pulse_frame.signal import summary
from pulse_frame.signal.beats import Interval
from pulse_frame.signal.hrv import READING_FLOOR_DB
from pulse_frame.signal.spectrum import SEARCH_LOW_HZ
from pulse_frame.tools import replay
from tests.counted_runs import (
    HALF_RATE_IBI_MS,
    WARMED_UP_RUNS,
    chain,
    hand_checks,
    heart_rate_under_the_reading_floor,
    ramped,
    replayed,
)

NEWEST_MS = 400_000.0
ONE_S_MS = 1_000.0
MINUTE_MS = 60_000.0
UNDER_DB = 1.0
CLEAR_DB = 5.0
WEAK_DB = -5.0
STRONG_DB = 10.0
NAN = float("nan")
FLOOR_BEATS = 45
TINY_SHARE_UNDER = 2_500
SOME_WINDOWS_CLEAR = "some_windows_clear"
SOME_WINDOWS_CLEAR_PERCENT = 26
MOVED_DEFINITIONS = [
    "def beside_holes",
    "def counted_intervals",
    "def counted_checks",
    "def newest_span",
    "def minute_sdnns",
    "def mean_sdnn",
    "def passes_gates",
    "def accepted_percent",
    "def is_too_weak",
    "def measured_under_floor",
    "def face_left_view",
    "def is_unmeasured",
    "def is_measured_under_reading_floor",
    "class Summary",
    "SAMPLE_HOLE_MS =",
    "SUMMARY_SPAN_MS =",
    "SUMMARY_MIN_ACCEPTED_MS =",
    "MIN_MINUTE_INTERVALS =",
    "WEAK_WINDOW_SHARE =",
]
RUNS_WITH_A_READING = [
    "clean",
    "clean_two_counted_minutes",
    "holes_in_the_counted_part",
    "over_the_window_with_holes",
    "reading_then_under_the_floor",
]
DECISIONS: dict[str, tuple[str, str | None, int | None]] = {
    "no_window_clears": ("READING_FLOOR_NOT_CLEARED", "faint_pulse", 0),
    "too_weak": ("SIGNAL_TOO_WEAK", None, None),
    "face_left_view": ("READING_FLOOR_NOT_CLEARED", "face_left_view", None),
}
BACKEND = Path(__file__).resolve().parents[2]
SCANNED = ("src", "tests")
MOVED_NAMES = {
    "Summary",
    "SAMPLE_HOLE_MS",
    "SUMMARY_MIN_ACCEPTED_MS",
    "beside_holes",
    "counted_checks",
    "counted_intervals",
    "is_too_weak",
    "mean_sdnn",
    "minute_sdnns",
    "newest_span",
}
SLOWEST_MINUTE_BPM = SEARCH_LOW_HZ * 60.0
UNDER_SLOWEST_IBI_MS = 1_450.0
OVER_SLOWEST_IBI_MS = 1_400.0


def replayed_decision(kind: str) -> summary.NoReading | None:
    result = replayed(kind)
    return summary.decide_no_reading(
        replay.summarise(result),
        result.window_checks,
        result.newest_ms,
        bool(result.readings),
    )


def half_up(percent: float) -> int:
    return math.floor(percent + 0.5)


def counted_seconds(count: int) -> list[Interval]:
    return chain([ONE_S_MS] * count, NEWEST_MS)


def nothing_measured() -> summary.Summary:
    return summary.Summary(
        bpm=None, rmssd_ms=None, sdnn_ms=None, count=0, accepted_percent=None
    )


def decided(
    snrs: list[float],
    result: summary.Summary | None = None,
    had_reading: bool = False,
) -> summary.NoReading | None:
    checks = hand_checks(snrs, NEWEST_MS - MINUTE_MS)
    newest_ms = checks[-1].t_ms if checks else NEWEST_MS
    return summary.decide_no_reading(
        nothing_measured() if result is None else result,
        checks,
        newest_ms,
        had_reading,
    )


def test_the_hole_rule_marks_both_samples_beside_a_gap_over_one_hundred_ms() -> None:
    times = [0.0, 33.0, 66.0, 167.0, 200.0, 300.0, 400.0]

    marked = summary.beside_holes(times)

    assert summary.SAMPLE_HOLE_MS == 100.0
    assert marked.tolist() == [False, False, True, True, False, False, False]


def test_a_single_sample_is_never_beside_a_hole() -> None:
    assert summary.beside_holes([5.0]).tolist() == [False]


def test_counted_filters_keep_what_starts_at_or_after_the_counted_start() -> None:
    intervals = chain([ONE_S_MS] * 4, 10_000.0)
    checks = hand_checks([STRONG_DB] * 4, 7_000.0)

    kept = summary.counted_intervals(intervals, 7_000)
    kept_checks = summary.counted_checks(checks, 8_000)

    assert [i.start_ms for i in kept] == [7_000.0, 8_000.0, 9_000.0]
    assert [c.t_ms for c in kept_checks] == [8_000.0, 9_000.0, 10_000.0]


def test_the_summary_floor_is_forty_five_seconds_of_accepted_beats() -> None:
    at_floor = summary.summarise(counted_seconds(FLOOR_BEATS), NEWEST_MS, [])
    under = summary.summarise(counted_seconds(FLOOR_BEATS - 1), NEWEST_MS, [])

    assert summary.SUMMARY_MIN_ACCEPTED_MS == 45_000.0
    assert summary.SUMMARY_SPAN_MS == 60_000.0
    assert at_floor == summary.Summary(
        bpm=60.0,
        rmssd_ms=None,
        sdnn_ms=None,
        count=FLOOR_BEATS,
        accepted_percent=100.0,
        bpm_low=60.0,
        bpm_high=60.0,
    )
    assert under == summary.Summary(
        bpm=None,
        rmssd_ms=None,
        sdnn_ms=None,
        count=FLOOR_BEATS - 1,
        accepted_percent=100.0,
    )


def test_the_minute_bpm_is_from_the_mean_accepted_interval_of_the_newest_minute() -> (
    None
):
    older = chain([1_500.0] * 20, NEWEST_MS - MINUTE_MS - 2 * ONE_S_MS)
    newest = chain(np.linspace(900.0, 1_100.0, 60).tolist(), NEWEST_MS)
    rejected = [
        Interval(i.start_ms, i.end_ms, "motion") if k % 10 == 0 else i
        for k, i in enumerate(newest)
    ]

    result = summary.summarise([*older, *rejected], NEWEST_MS, [])

    kept = [i.ibi_ms for k, i in enumerate(newest) if k % 10]
    assert result.count == len(kept)
    assert result.bpm == pytest.approx(60_000.0 / float(np.mean(kept)), abs=1e-9)


def test_the_newest_span_keeps_intervals_ending_inside_the_minute_ends_included() -> (
    None
):
    intervals = [
        Interval(NEWEST_MS - MINUTE_MS - 900.0, NEWEST_MS - MINUTE_MS - 1.0, "ok"),
        Interval(NEWEST_MS - MINUTE_MS - 900.0, NEWEST_MS - MINUTE_MS, "ok"),
        Interval(NEWEST_MS - 900.0, NEWEST_MS, "ok"),
    ]

    assert summary.newest_span(intervals, NEWEST_MS) == intervals[1:]


def test_a_minute_sdnn_needs_forty_five_seconds_accepted_in_that_minute() -> None:
    newest = chain([950.0, 1_050.0] * 30, NEWEST_MS)
    second = chain([1_000.0] * 40, newest[0].start_ms - 10_000.0)
    third = chain([900.0, 1_100.0] * 25, second[0].start_ms - 10_000.0)

    sdnns = summary.minute_sdnns([*third, *second, *newest], NEWEST_MS)

    assert set(sdnns) == {0, 2}
    assert sdnns[0] == pytest.approx(float(np.std([950.0, 1_050.0] * 30, ddof=1)))
    assert sdnns[2] == pytest.approx(float(np.std([900.0, 1_100.0] * 25, ddof=1)))
    assert summary.mean_sdnn(sdnns) == pytest.approx((sdnns[0] + sdnns[2]) / 2.0)
    assert summary.mean_sdnn({}) is None


def test_the_accepted_share_leaves_edge_intervals_out_of_its_denominator() -> None:
    intervals = [
        *chain([ONE_S_MS] * 3, 10_000.0),
        Interval(10_000.0, 11_000.0, "motion"),
        Interval(11_000.0, 12_000.0, "edge"),
    ]

    assert summary.accepted_percent(intervals) == 75.0
    assert summary.accepted_percent([Interval(0.0, 1_000.0, "edge")]) is None


@pytest.mark.parametrize("kind", list(WARMED_UP_RUNS), ids=list(WARMED_UP_RUNS))
def test_signal_summarise_matches_the_replay_summary_of_the_same_counted_run(
    kind: str,
) -> None:
    result = replayed(kind)

    summarised = summary.summarise(
        result.intervals, result.newest_ms, result.window_checks
    )

    assert summarised == replay.summarise(result)


def test_a_newest_minute_without_beats_and_mostly_under_the_floor_is_too_weak() -> None:
    decision = decided([WEAK_DB] * 40 + [STRONG_DB] * 19)

    assert decision == summary.NoReading(
        code="SIGNAL_TOO_WEAK", why=None, clear_percent=None
    )


def test_too_weak_needs_more_than_half_of_the_newest_windows_under_the_floor() -> None:
    assert summary.WEAK_WINDOW_SHARE == 0.5
    assert summary.is_too_weak(hand_checks([WEAK_DB] * 3 + [STRONG_DB] * 2))
    assert not summary.is_too_weak(hand_checks([WEAK_DB] * 2 + [STRONG_DB] * 2))
    assert not summary.is_too_weak([])


def test_too_weak_reads_the_newest_minute_while_the_floor_reads_the_counted_part() -> (
    None
):
    older = hand_checks([WEAK_DB] * 100, NEWEST_MS - 3 * MINUTE_MS)
    newest = hand_checks([STRONG_DB] * 60, NEWEST_MS - MINUTE_MS + ONE_S_MS)

    decision = summary.decide_no_reading(
        nothing_measured(), [*older, *newest], NEWEST_MS, False
    )

    assert decision == summary.NoReading(
        code="READING_FLOOR_NOT_CLEARED", why="faint_pulse", clear_percent=37.5
    )


def test_a_minute_with_accepted_beats_is_never_too_weak() -> None:
    some_beats = summary.Summary(
        bpm=None, rmssd_ms=None, sdnn_ms=None, count=3, accepted_percent=50.0
    )

    decision = decided([WEAK_DB] * 60, some_beats)

    assert decision is not None
    assert decision.code == "READING_FLOOR_NOT_CLEARED"


@pytest.mark.parametrize(
    ("snrs", "share"),
    [
        pytest.param([CLEAR_DB] + [UNDER_DB] * 3, 25.0, id="a_quarter"),
        pytest.param([CLEAR_DB] + [UNDER_DB] * 7, 12.5, id="an_eighth"),
        pytest.param([UNDER_DB] * 4, 0.0, id="never"),
        pytest.param([READING_FLOOR_DB] + [UNDER_DB] * 3, 25.0, id="at_the_floor"),
        pytest.param(
            [math.inf, UNDER_DB, UNDER_DB, -math.inf, NAN], 20.0, id="plus_infinity"
        ),
        pytest.param(
            [CLEAR_DB] + [UNDER_DB] * TINY_SHARE_UNDER,
            100.0 / (TINY_SHARE_UNDER + 1),
            id="under_one_percent",
        ),
    ],
)
def test_a_run_under_the_reading_floor_gives_faint_pulse_with_its_exact_clear_share(
    snrs: list[float], share: float
) -> None:
    decision = decided(snrs)

    assert decision == summary.NoReading(
        code="READING_FLOOR_NOT_CLEARED", why="faint_pulse", clear_percent=share
    )


def test_more_unmeasured_windows_than_measured_under_gives_face_left_view() -> None:
    decision = decided([-math.inf, NAN, -math.inf, UNDER_DB, 2.0, CLEAR_DB])

    assert decision == summary.NoReading(
        code="READING_FLOOR_NOT_CLEARED", why="face_left_view", clear_percent=None
    )


def test_as_many_unmeasured_as_measured_under_still_gives_faint_pulse() -> None:
    decision = decided([-math.inf, NAN, UNDER_DB, 2.0, CLEAR_DB])

    assert decision is not None
    assert decision.why == "faint_pulse"


@pytest.mark.parametrize(
    ("snrs", "rmssd_ms", "had_reading"),
    [
        pytest.param([CLEAR_DB, CLEAR_DB, UNDER_DB], None, False, id="median_clears"),
        pytest.param([], None, False, id="no_checks"),
        pytest.param([UNDER_DB] * 4, 40.0, False, id="summary_has_rmssd"),
        pytest.param([UNDER_DB] * 4, None, True, id="a_reading_came_out"),
    ],
)
def test_no_decision_while_a_reading_exists_or_the_floor_is_cleared(
    snrs: list[float], rmssd_ms: float | None, had_reading: bool
) -> None:
    result = summary.Summary(
        bpm=None, rmssd_ms=rmssd_ms, sdnn_ms=None, count=10, accepted_percent=90.0
    )

    assert decided(snrs, result, had_reading) is None


@pytest.mark.parametrize("kind", RUNS_WITH_A_READING, ids=RUNS_WITH_A_READING)
def test_a_counted_run_the_replay_reads_gets_no_decision(kind: str) -> None:
    assert replayed_decision(kind) is None


@pytest.mark.parametrize("kind", list(DECISIONS), ids=list(DECISIONS))
def test_the_decision_on_a_counted_run_is_the_one_the_replay_prints(kind: str) -> None:
    decision = replayed_decision(kind)

    code, why, printed_percent = DECISIONS[kind]
    assert decision is not None
    assert (decision.code, decision.why) == (code, why)
    shown = None if decision.clear_percent is None else half_up(decision.clear_percent)
    assert shown == printed_percent


def test_a_counted_run_with_a_minute_bpm_gets_no_decision_but_the_replay_share() -> (
    None
):
    result = replayed(SOME_WINDOWS_CLEAR)
    counted = replay.summarise(result)

    assert counted.bpm is not None
    assert replayed_decision(SOME_WINDOWS_CLEAR) is None
    printed = summary.floor_decision(
        counted, result.window_checks, bool(result.readings)
    )
    assert printed is not None
    assert (printed.code, printed.why) == ("READING_FLOOR_NOT_CLEARED", "faint_pulse")
    assert printed.clear_percent is not None
    assert half_up(printed.clear_percent) == SOME_WINDOWS_CLEAR_PERCENT


def test_replay_keeps_no_copy_of_the_logic_moved_into_signal() -> None:
    source = inspect.getsource(replay)

    kept = [definition for definition in MOVED_DEFINITIONS if definition in source]

    assert kept == []


def test_no_code_reaches_a_moved_name_through_replay() -> None:
    names = "|".join(sorted(MOVED_NAMES))
    through_replay = re.compile(rf"\breplay\.(?:{names})\b")
    imported = re.compile(
        rf"from pulse_frame\.tools\.replay import[^\n]*\b(?:{names})\b"
    )

    found = [
        f"{path.relative_to(BACKEND)}:{number}"
        for folder in SCANNED
        for path in sorted((BACKEND / folder).rglob("*.py"))
        for number, line in enumerate(path.read_text().splitlines(), start=1)
        if through_replay.search(line) or imported.search(line)
    ]

    assert found == []


def minute_of(ibi_ms: float) -> summary.Summary:
    count = int(MINUTE_MS // ibi_ms)
    return summary.summarise(chain([ibi_ms] * count, NEWEST_MS), NEWEST_MS, [])


def test_a_minute_slower_than_the_search_band_gives_no_bpm_but_keeps_its_count() -> (
    None
):
    under = minute_of(UNDER_SLOWEST_IBI_MS)
    over = minute_of(OVER_SLOWEST_IBI_MS)

    assert pytest.approx(42.0) == SLOWEST_MINUTE_BPM
    assert under.bpm is None
    assert under.count == int(MINUTE_MS // UNDER_SLOWEST_IBI_MS)
    assert over.bpm == pytest.approx(60_000.0 / OVER_SLOWEST_IBI_MS)
    assert over.bpm > SLOWEST_MINUTE_BPM


def test_a_half_rate_minute_shows_no_minute_bpm() -> None:
    half_rate = minute_of(HALF_RATE_IBI_MS)

    assert half_rate.bpm is None
    assert half_rate.count == int(MINUTE_MS // HALF_RATE_IBI_MS)


def hrv_minutes(ibi_ms: float) -> summary.Summary:
    intervals, checks = ramped(ibi_ms, NEWEST_MS)
    return summary.summarise(intervals, NEWEST_MS, checks)


def test_a_minute_under_the_floor_drops_its_hrv_but_keeps_count_and_share() -> None:
    readable = hrv_minutes(OVER_SLOWEST_IBI_MS)
    half_rate = hrv_minutes(HALF_RATE_IBI_MS)

    assert readable.rmssd_ms is not None
    assert readable.sdnn_ms is not None
    assert readable.sdnn_minutes
    assert half_rate.bpm is None
    assert half_rate.rmssd_ms is None
    assert half_rate.sdnn_ms is None
    assert half_rate.sdnn_minutes == ()
    assert half_rate.count == span_count(HALF_RATE_IBI_MS)
    assert half_rate.accepted_percent == 100.0


def span_count(ibi_ms: float) -> int:
    intervals, _ = ramped(ibi_ms, NEWEST_MS)
    return len(summary.newest_span(intervals, NEWEST_MS))


def test_a_minute_bpm_under_the_reading_floor_is_a_reading_with_no_decision() -> None:
    intervals, checks, newest_ms = heart_rate_under_the_reading_floor()

    result = summary.summarise(intervals, newest_ms, checks)

    assert result.bpm is not None
    assert (result.rmssd_ms, result.sdnn_ms) == (None, None)
    assert summary.decide_no_reading(result, checks, newest_ms, False) is None


def test_the_replay_floor_decision_for_a_bpm_without_variation_is_unchanged() -> None:
    intervals, checks, newest_ms = heart_rate_under_the_reading_floor()
    result = summary.summarise(intervals, newest_ms, checks)

    decision = summary.floor_decision(result, checks, False)

    assert decision == summary.NoReading(
        code="READING_FLOOR_NOT_CLEARED", why="faint_pulse", clear_percent=0.0
    )
