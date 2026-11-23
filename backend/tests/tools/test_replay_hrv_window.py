from collections.abc import Callable

import numpy as np
import pytest

from pulse_frame.signal.beats import Interval, IntervalFlag
from pulse_frame.signal.hrv import (
    MIN_ACCEPTED_MS,
    READING_FLOOR_DB,
    WINDOW_MS,
    WindowCheck,
    alternates,
    hrv_reading,
)
from pulse_frame.tools import replay
from tests.frames import TRUE_BPM
from tests.signal.beat_synthetic import chain, period_ms, respiring_ibis, rmssd, sdnn

FORMULA_TOLERANCE_MS = 0.1
APART_MS = 3.0
SUMMARY_SPAN_MS = 60_000.0
SUMMARY_MIN_ACCEPTED_MS = 45_000.0
MINUTE_EDGE_CLEARANCE_MS = 1.0
NEWEST_AFTER_MS = 1_000.0
CHECK_STEP_MS = 1_000.0
CHECK_MARGIN_DB = 1.0
STRONG_DB = READING_FLOOR_DB + 5.0
CALM_SWING_MS = 20.0
LIVELY_SWING_MS = 60.0
LIVELY_IBI_MS = 800.0
MAX_REJECTED_SHARE = 0.2
TRUE_IBI_MS = period_ms(TRUE_BPM)
ALTERNATING_PAIR_MS = (700.0, 900.0)
ALTERNATING_COUNT = 50
GATE_LEAD_COUNT = 80
GATE_TAIL_COUNT = 90
REJECTED_LEAD_COUNT = 150
FLOOR_SESSION_COUNT = 240
SHORT_SESSIONS = {"ninety_s": (40, 70), "two_hundred_s": (150, 90)}
LONG_SESSION = (400, 200)
SHORT_ACCEPTED_COUNT = 60
REJECTED_MINUTE_LEAD_COUNT = 250
REJECTED_MINUTE_COUNT = 72
REJECTED_IN_MINUTE = 16
DRIFT_COUNT = 370
DRIFT_FROM_MS = 950.0
DRIFT_TO_MS = 750.0
THIN_MINUTE = 2
LOUD_SWING_MS = 80.0
SPARSE_EVERY = 3
PRINTED_SESSION = 7
PRINTED = replay.Summary(
    bpm=72.0, rmssd_ms=34.5, sdnn_ms=41.5, count=70, accepted_percent=96.5
)
BLANK = replay.Summary(
    bpm=None, rmssd_ms=None, sdnn_ms=None, count=3, accepted_percent=None
)


def calm_then_lively(calm_count: int, lively_count: int) -> list[float]:
    calm = respiring_ibis(calm_count, TRUE_IBI_MS, swing_ms=CALM_SWING_MS)
    lively = respiring_ibis(lively_count, LIVELY_IBI_MS, swing_ms=LIVELY_SWING_MS)
    return calm + lively


def drifting_ibis(count: int) -> list[float]:
    breathing = np.asarray(respiring_ibis(count, TRUE_IBI_MS, swing_ms=CALM_SWING_MS))
    drift = np.linspace(DRIFT_FROM_MS, DRIFT_TO_MS, count)
    return list(drift + breathing - TRUE_IBI_MS)


def newest_after(intervals: list[Interval]) -> int:
    return round(intervals[-1].end_ms + NEWEST_AFTER_MS)


def checks_between(first_ms: float, last_ms: float, snr_db: float) -> list[WindowCheck]:
    return [
        WindowCheck(t_ms=float(t_ms), snr_db=snr_db)
        for t_ms in np.arange(first_ms, last_ms + 1.0, CHECK_STEP_MS)
    ]


def strong_result(intervals: list[Interval]) -> replay.ReplayResult:
    newest_ms = newest_after(intervals)
    return replay.ReplayResult(
        intervals=intervals,
        readings=[],
        newest_ms=newest_ms,
        window_checks=checks_between(intervals[0].start_ms, newest_ms, STRONG_DB),
    )


def in_hrv_window(intervals: list[Interval], newest_ms: int) -> list[Interval]:
    return [i for i in intervals if i.start_ms >= newest_ms - WINDOW_MS]


def minute(intervals: list[Interval], newest_ms: int) -> list[Interval]:
    return [
        i
        for i in intervals
        if newest_ms - SUMMARY_SPAN_MS <= round(i.end_ms) <= newest_ms
    ]


def minute_ibis(intervals: list[Interval], newest_ms: int) -> list[float]:
    return [i.ibi_ms for i in minute(intervals, newest_ms) if i.accepted]


def minute_number(interval: Interval, newest_ms: int) -> int:
    return int((newest_ms - interval.end_ms) // SUMMARY_SPAN_MS)


def accepted_by_minute(
    intervals: list[Interval], newest_ms: int
) -> dict[int, list[float]]:
    minutes: dict[int, list[float]] = {}
    for interval in in_hrv_window(intervals, newest_ms):
        if interval.accepted:
            minutes.setdefault(minute_number(interval, newest_ms), []).append(
                interval.ibi_ms
            )
    return minutes


def full_minute_sdnns(intervals: list[Interval], newest_ms: int) -> list[float]:
    return [
        sdnn(ibis)
        for ibis in accepted_by_minute(intervals, newest_ms).values()
        if sum(ibis) >= SUMMARY_MIN_ACCEPTED_MS
    ]


def assert_clear_of_minute_edges(intervals: list[Interval], newest_ms: int) -> None:
    for interval in in_hrv_window(intervals, newest_ms):
        into_minute_ms = (newest_ms - interval.end_ms) % SUMMARY_SPAN_MS
        assert into_minute_ms > MINUTE_EDGE_CLEARANCE_MS
        assert into_minute_ms < SUMMARY_SPAN_MS - MINUTE_EDGE_CLEARANCE_MS


def assert_window_values(summary: replay.Summary, intervals: list[Interval]) -> None:
    newest_ms = newest_after(intervals)
    window = [i.ibi_ms for i in in_hrv_window(intervals, newest_ms)]
    assert_clear_of_minute_edges(intervals, newest_ms)
    assert abs(rmssd(window) - rmssd(minute_ibis(intervals, newest_ms))) > APART_MS
    assert summary.rmssd_ms == pytest.approx(rmssd(window), abs=FORMULA_TOLERANCE_MS)
    assert summary.sdnn_ms == pytest.approx(
        np.mean(full_minute_sdnns(intervals, newest_ms)), abs=FORMULA_TOLERANCE_MS
    )


def test_summary_rmssd_and_sdnn_cover_the_newest_three_hundred_seconds() -> None:
    ibis = calm_then_lively(*LONG_SESSION)
    intervals = chain(ibis)
    result = strong_result(intervals)
    window = [i.ibi_ms for i in in_hrv_window(intervals, result.newest_ms)]
    assert intervals[-1].end_ms - intervals[0].start_ms > WINDOW_MS
    assert abs(rmssd(window) - rmssd(ibis)) > APART_MS
    assert abs(sdnn(window) - sdnn(ibis)) > APART_MS

    summary = replay.summarise(result)

    assert_window_values(summary, intervals)


@pytest.mark.parametrize("counts", list(SHORT_SESSIONS.values()), ids=SHORT_SESSIONS)
def test_a_session_under_300_s_pools_rmssd_and_averages_its_full_minutes_sdnn(
    counts: tuple[int, int],
) -> None:
    intervals = chain(calm_then_lively(*counts))
    result = strong_result(intervals)
    assert result.newest_ms - intervals[0].start_ms < WINDOW_MS
    assert in_hrv_window(intervals, result.newest_ms) == intervals

    summary = replay.summarise(result)

    assert_window_values(summary, intervals)


@pytest.mark.parametrize(
    "counts",
    [*SHORT_SESSIONS.values(), LONG_SESSION],
    ids=[*SHORT_SESSIONS, "four_hundred_ninety_s"],
)
def test_summary_bpm_and_count_stay_on_the_newest_minute(
    counts: tuple[int, int],
) -> None:
    intervals = chain(calm_then_lively(*counts))
    result = strong_result(intervals)
    newest_minute = minute_ibis(intervals, result.newest_ms)
    window = [i.ibi_ms for i in in_hrv_window(intervals, result.newest_ms)]
    assert abs(np.mean(window) - np.mean(newest_minute)) > FORMULA_TOLERANCE_MS

    summary = replay.summarise(result)

    assert summary.bpm == pytest.approx(60_000.0 / np.mean(newest_minute))
    assert summary.count == len(newest_minute)


def test_summary_sdnn_is_the_mean_of_per_minute_sdnns_while_rmssd_stays_pooled() -> (
    None
):
    intervals = chain(drifting_ibis(DRIFT_COUNT))
    result = strong_result(intervals)
    window = [i.ibi_ms for i in in_hrv_window(intervals, result.newest_ms)]
    per_minute = full_minute_sdnns(intervals, result.newest_ms)
    assert_clear_of_minute_edges(intervals, result.newest_ms)
    assert len(per_minute) > 1
    assert abs(np.mean(per_minute) - sdnn(window)) > APART_MS

    summary = replay.summarise(result)

    assert summary.sdnn_ms == pytest.approx(
        np.mean(per_minute), abs=FORMULA_TOLERANCE_MS
    )
    assert summary.rmssd_ms == pytest.approx(rmssd(window), abs=FORMULA_TOLERANCE_MS)


def in_thin_minute(intervals: list[Interval]) -> list[bool]:
    newest_ms = newest_after(intervals)
    return [minute_number(i, newest_ms) == THIN_MINUTE for i in intervals]


def thin_loud_minute() -> list[Interval]:
    ibis = np.asarray(drifting_ibis(DRIFT_COUNT))
    loud = np.asarray(respiring_ibis(DRIFT_COUNT, TRUE_IBI_MS, LOUD_SWING_MS))
    louder = np.where(in_thin_minute(chain(list(ibis))), loud - TRUE_IBI_MS, 0.0)
    final = list(ibis + louder)
    thin = in_thin_minute(chain(final))
    flags: list[IntervalFlag] = [
        "motion" if is_thin and k % 2 else "ok" for k, is_thin in enumerate(thin)
    ]
    return chain(final, flags=flags)


def test_a_minute_under_forty_five_seconds_accepted_is_left_out_of_the_sdnn() -> None:
    intervals = thin_loud_minute()
    result = strong_result(intervals)
    minutes = accepted_by_minute(intervals, result.newest_ms)
    window = in_hrv_window(intervals, result.newest_ms)
    every_minute = np.mean([sdnn(ibis) for ibis in minutes.values()])
    full_minutes = np.mean(full_minute_sdnns(intervals, result.newest_ms))
    assert_clear_of_minute_edges(intervals, result.newest_ms)
    assert sum(minutes[THIN_MINUTE]) < SUMMARY_MIN_ACCEPTED_MS
    assert abs(every_minute - full_minutes) > FORMULA_TOLERANCE_MS
    assert sum(1 for i in window if not i.accepted) / len(window) <= MAX_REJECTED_SHARE

    summary = replay.summarise(result)

    assert summary.sdnn_ms == pytest.approx(full_minutes, abs=FORMULA_TOLERANCE_MS)


def sparse_flags(count: int) -> list[IntervalFlag]:
    return ["motion" if k % SPARSE_EVERY == 0 else "ok" for k in range(count)]


@pytest.mark.parametrize(
    ("flags", "has_sdnn"),
    [(sparse_flags(DRIFT_COUNT), False), (["ok"] * DRIFT_COUNT, True)],
    ids=["no_full_minute", "full_minutes"],
)
def test_the_mean_of_minute_sdnns_is_none_without_a_minute_of_forty_five_s_accepted(
    flags: list[IntervalFlag], has_sdnn: bool
) -> None:
    intervals = chain(drifting_ibis(DRIFT_COUNT), flags=flags)
    newest_ms = newest_after(intervals)
    per_minute = full_minute_sdnns(intervals, newest_ms)
    assert_clear_of_minute_edges(intervals, newest_ms)
    assert (per_minute != []) is has_sdnn
    expected = (
        pytest.approx(np.mean(per_minute), abs=FORMULA_TOLERANCE_MS)
        if per_minute
        else None
    )

    sdnn = replay.mean_sdnn(replay.minute_sdnns(intervals, newest_ms))

    assert (sdnn is not None) is has_sdnn
    assert sdnn == expected


def older_alternation() -> replay.ReplayResult:
    swinging = [ALTERNATING_PAIR_MS[k % 2] for k in range(ALTERNATING_COUNT)]
    lead = respiring_ibis(GATE_LEAD_COUNT, TRUE_IBI_MS)
    tail = respiring_ibis(GATE_TAIL_COUNT, TRUE_IBI_MS)
    return strong_result(chain(lead + swinging + tail))


def older_rejections() -> replay.ReplayResult:
    lead: list[IntervalFlag] = [
        "motion" if k % 2 else "ok" for k in range(REJECTED_LEAD_COUNT)
    ]
    tail: list[IntervalFlag] = ["ok"] * GATE_TAIL_COUNT
    ibis = respiring_ibis(REJECTED_LEAD_COUNT + GATE_TAIL_COUNT, TRUE_IBI_MS)
    return strong_result(chain(ibis, flags=lead + tail))


def split_checks(older_db: float, newest_db: float) -> replay.ReplayResult:
    intervals = chain(respiring_ibis(FLOOR_SESSION_COUNT, TRUE_IBI_MS))
    newest_ms = newest_after(intervals)
    minute_starts_ms = newest_ms - SUMMARY_SPAN_MS
    checks = checks_between(
        intervals[0].start_ms, minute_starts_ms - CHECK_STEP_MS, older_db
    ) + checks_between(minute_starts_ms, newest_ms, newest_db)
    return replay.ReplayResult(
        intervals=intervals, readings=[], newest_ms=newest_ms, window_checks=checks
    )


def older_checks_under_the_floor() -> replay.ReplayResult:
    return split_checks(
        READING_FLOOR_DB - CHECK_MARGIN_DB, READING_FLOOR_DB + CHECK_MARGIN_DB
    )


def newest_checks_under_the_floor() -> replay.ReplayResult:
    return split_checks(
        READING_FLOOR_DB + CHECK_MARGIN_DB, READING_FLOOR_DB - CHECK_MARGIN_DB
    )


def clean_session() -> replay.ReplayResult:
    return strong_result(
        chain(respiring_ibis(GATE_LEAD_COUNT + GATE_TAIL_COUNT, TRUE_IBI_MS))
    )


def median_db(checks: list[WindowCheck]) -> float:
    return float(np.median([c.snr_db for c in checks]))


def window_checks(result: replay.ReplayResult) -> list[WindowCheck]:
    window = in_hrv_window(result.intervals, result.newest_ms)
    return [
        c
        for c in result.window_checks
        if window[0].start_ms <= c.t_ms <= result.newest_ms
    ]


def assert_minute_passes(result: replay.ReplayResult) -> None:
    span = minute(result.intervals, result.newest_ms)
    assert all(i.accepted for i in span)
    assert not alternates(span)
    assert median_db(replay.newest_checks(result)) >= READING_FLOOR_DB


def window_fails_a_gate(result: replay.ReplayResult) -> bool:
    window = in_hrv_window(result.intervals, result.newest_ms)
    settled = [i for i in window if i.flag != "edge"]
    rejected = sum(1 for i in settled if not i.accepted) / len(settled)
    return (
        alternates(window)
        or rejected > MAX_REJECTED_SHARE
        or median_db(window_checks(result)) < READING_FLOOR_DB
    )


@pytest.mark.parametrize(
    ("session", "shown"),
    [
        (clean_session, True),
        (older_alternation, False),
        (older_rejections, False),
        (older_checks_under_the_floor, False),
    ],
    ids=["clean", "alternates", "too_rejected", "under_the_reading_floor"],
)
def test_a_failing_hrv_window_drops_rmssd_and_sdnn_but_keeps_the_minutes_bpm(
    session: Callable[[], replay.ReplayResult], shown: bool
) -> None:
    result = session()
    newest_minute = minute_ibis(result.intervals, result.newest_ms)
    assert_minute_passes(result)
    assert window_fails_a_gate(result) is not shown

    summary = replay.summarise(result)

    assert summary.bpm == pytest.approx(60_000.0 / np.mean(newest_minute))
    assert summary.count == len(newest_minute)
    assert (summary.rmssd_ms is not None) is shown
    assert (summary.sdnn_ms is not None) is shown


def test_a_weak_newest_minute_in_a_passing_window_prints_bpm_rmssd_and_sdnn() -> None:
    result = newest_checks_under_the_floor()
    newest_minute = minute_ibis(result.intervals, result.newest_ms)
    assert median_db(replay.newest_checks(result)) < READING_FLOOR_DB
    assert median_db(window_checks(result)) >= READING_FLOOR_DB

    summary = replay.summarise(result)

    assert summary.bpm == pytest.approx(60_000.0 / np.mean(newest_minute))
    assert summary.rmssd_ms is not None
    assert summary.sdnn_ms is not None


def test_under_sixty_seconds_accepted_keeps_the_minutes_bpm_but_no_rmssd_or_sdnn() -> (
    None
):
    ibis = respiring_ibis(SHORT_ACCEPTED_COUNT, TRUE_IBI_MS)
    intervals = chain(ibis)
    result = strong_result(intervals)
    newest_minute = minute_ibis(intervals, result.newest_ms)
    assert sum(newest_minute) >= SUMMARY_MIN_ACCEPTED_MS
    assert sum(ibis) < MIN_ACCEPTED_MS

    summary = replay.summarise(result)

    assert summary.bpm == pytest.approx(60_000.0 / np.mean(newest_minute))
    assert summary.count == len(newest_minute)
    assert summary.rmssd_ms is None
    assert summary.sdnn_ms is None


def rejected_minute() -> replay.ReplayResult:
    count = REJECTED_MINUTE_LEAD_COUNT + REJECTED_MINUTE_COUNT
    marks: list[IntervalFlag] = ["ok"] * count
    spots = np.linspace(2, REJECTED_MINUTE_COUNT - 3, REJECTED_IN_MINUTE)
    for spot in spots.round().astype(int):
        marks[REJECTED_MINUTE_LEAD_COUNT + spot] = "motion"
    return strong_result(chain(respiring_ibis(count, TRUE_IBI_MS), flags=marks))


def test_a_minute_that_fails_its_gates_blanks_all_three_even_if_the_window_passes() -> (
    None
):
    result = rejected_minute()
    span = minute(result.intervals, result.newest_ms)
    accepted_ms = sum(i.ibi_ms for i in span if i.accepted)
    rejected = sum(1 for i in span if not i.accepted) / len(span)
    window = hrv_reading(result.intervals, result.newest_ms, result.window_checks)
    assert accepted_ms >= SUMMARY_MIN_ACCEPTED_MS
    assert rejected > MAX_REJECTED_SHARE
    assert window.rmssd_ms is not None
    assert window.sdnn_ms is not None

    summary = replay.summarise(result)

    assert summary.bpm is None
    assert summary.rmssd_ms is None
    assert summary.sdnn_ms is None


@pytest.mark.parametrize(
    ("values", "line"),
    [
        (
            PRINTED,
            "Session 7 replayed, newest minute: bpm=72.0 count=70;"
            " last 5 minutes: rmssd=34.5 ms sdnn=41.5 ms;"
            " whole session: accepted=96.5%",
        ),
        (
            BLANK,
            "Session 7 replayed, newest minute: bpm=- count=3;"
            " last 5 minutes: rmssd=- sdnn=-;"
            " whole session: accepted=-",
        ),
    ],
    ids=["values", "blank"],
)
def test_the_summary_line_puts_bpm_and_count_on_the_minute_and_hrv_on_five_minutes(
    values: replay.Summary, line: str
) -> None:
    assert replay.summary_line(PRINTED_SESSION, values) == line
