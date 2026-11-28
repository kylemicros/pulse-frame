import math
from collections.abc import Sequence

import pytest

from pulse_frame.signal.beats import Interval, IntervalFlag
from pulse_frame.signal.hrv import NO_HRV, WindowCheck, hrv_reading
from pulse_frame.signal.summary import NoReading
from pulse_frame.stream.beat_signal import close_fields, signal_fields
from tests.signal.beat_synthetic import chain
from tests.stream.beat_signal import (
    CLOSE_FIELDS,
    SIGNAL_FIELDS,
    Expected,
    SignalSnapshot,
    expected_close,
    expected_signal,
    mismatches,
)

NEWEST_MS = 300_000.0
BEAT_MS = 1_000.0
NOT_YET = math.nan
QUIET = {"no_reading": None, "bpm_shown": False, "had_reading": False}
CLOSE_FLAGS: tuple[IntervalFlag, ...] = (
    ("ok",) * 24
    + ("motion",) * 3
    + ("low_quality",) * 2
    + ("out_of_range",)
    + ("edge",) * 2
)
CLOSE_SHARES = {
    "accepted_share": 80.0,
    "rejected_share_gap": 0.0,
    "rejected_share_motion": 10.0,
    "rejected_share_low_quality": 10.0,
    "rejected_share_out_of_range": 0.0,
    "rejected_share_off_median": 0.0,
}
CHECK_STEP_MS = 3_000.0
LOW_CHECKS = 30
HIGH_CHECKS = 20
LOW_DB = -1.0
HIGH_DB = 6.0
COUNTED_MS = 100_000.0
SLOW_IBI_MS = 1_017.0
FAST_IBI_MS = 845.0
SLOW_PHASE_MS = 600.0
FAST_PHASE_MS = 700.0
SLIDE_SECONDS = 95
SLIDE_CHAIN_MS = 200_000.0
MOTION_EVERY_MS = 25_000.0
MOTION_FOR_MS = 1_500.0
PENDING_MS = 3_000.0
STEADY_DB = 5.0


def even(flags: Sequence[IntervalFlag], start_ms: float) -> list[Interval]:
    return chain([BEAT_MS] * len(flags), start_ms, flags)


def steady(count: int, end_ms: float) -> list[Interval]:
    return even(("ok",) * count, end_ms - count * BEAT_MS)


def clear_checks(first_ms: float = 0.0) -> list[WindowCheck]:
    count = int((NEWEST_MS - first_ms) // BEAT_MS)
    return [
        WindowCheck(t_ms=first_ms + k * BEAT_MS, snr_db=STEADY_DB) for k in range(count)
    ]


def fields_of(
    intervals: Sequence[Interval],
    checks: Sequence[WindowCheck],
    newest_ms: float = NEWEST_MS,
    counted_ms: float | None = 0.0,
    no_reading: NoReading | None = None,
    bpm_shown: bool = False,
    had_reading: bool = False,
) -> dict[str, str]:
    fields = signal_fields(
        intervals,
        checks,
        newest_ms,
        counted_ms,
        no_reading=no_reading,
        bpm_shown=bpm_shown,
        had_reading=had_reading,
    )
    assert set(fields) == SIGNAL_FIELDS, sorted(set(fields) ^ SIGNAL_FIELDS)
    return fields


def floor_checks() -> list[WindowCheck]:
    snrs = [LOW_DB] * LOW_CHECKS + [HIGH_DB] * HIGH_CHECKS
    return [
        WindowCheck(t_ms=k * CHECK_STEP_MS, snr_db=snr) for k, snr in enumerate(snrs)
    ]


def test_floor_fields_cover_every_counted_check_and_checks_the_minute() -> None:
    checks = floor_checks()
    newest_ms = checks[-1].t_ms + 500.0

    fields = fields_of([], checks, newest_ms, 0.0)

    assert (
        mismatches(
            fields,
            {
                "checks": float(HIGH_CHECKS),
                "under_floor_share": 0.0,
                "clear_share": 40.0,
                "unmeasured_share": 0.0,
                "median_snr_db": LOW_DB,
                "snr_db": HIGH_DB,
                "snr_age_ms": 500.0,
            },
        )
        == []
    ), fields


def test_checks_before_counting_began_are_left_out_of_every_check_field() -> None:
    checks = floor_checks()
    newest_ms = checks[-1].t_ms + 500.0
    counted_ms = checks[LOW_CHECKS].t_ms

    fields = fields_of([], checks, newest_ms, counted_ms)

    assert (
        mismatches(
            fields,
            {
                "clear_share": 100.0,
                "median_snr_db": HIGH_DB,
                "checks": float(HIGH_CHECKS),
            },
        )
        == []
    ), fields


def test_an_unmeasured_check_makes_the_median_nan_as_the_floor_rule_does() -> None:
    checks = [
        WindowCheck(t_ms=1_000.0 * k, snr_db=snr)
        for k, snr in enumerate((math.nan, -math.inf, -2.0, 4.0, 6.5))
    ]

    fields = fields_of([], checks, 5_000.0, 0.0)

    assert (
        mismatches(
            fields,
            {
                "median_snr_db": math.nan,
                "unmeasured_share": 40.0,
                "under_floor_share": 20.0,
                "clear_share": 40.0,
                "checks": 5.0,
                "snr_db": 6.5,
                "snr_age_ms": 1_000.0,
            },
        )
        == []
    ), fields


@pytest.mark.parametrize(
    "counted_ms",
    [
        pytest.param(None, id="no_frames"),
        pytest.param(NEWEST_MS + 1.0, id="first_minute"),
    ],
)
def test_before_counting_begins_only_the_snr_and_its_age_are_reported(
    counted_ms: float | None,
) -> None:
    fields = fields_of(steady(55, NEWEST_MS), clear_checks(), NEWEST_MS, counted_ms)

    assert (
        mismatches(
            fields,
            {
                "snr_db": STEADY_DB,
                "snr_age_ms": 1_000.0,
                "checks": 0.0,
                "under_floor_share": NOT_YET,
                "clear_share": NOT_YET,
                "unmeasured_share": NOT_YET,
                "median_snr_db": NOT_YET,
                "gate": "unchecked",
                "hrv_gate": "unchecked",
            },
        )
        == []
    ), fields


def test_without_any_check_the_snr_and_its_age_are_not_a_number() -> None:
    fields = fields_of([], [], NEWEST_MS, 0.0)

    assert (
        mismatches(fields, {"snr_db": NOT_YET, "snr_age_ms": NOT_YET, "checks": 0.0})
        == []
    ), fields


@pytest.mark.parametrize(
    ("no_reading", "bpm_shown", "had_reading", "expected"),
    [
        pytest.param(
            None,
            True,
            True,
            {"code": "none", "bpm_shown": 1.0, "had_reading": 1.0},
            id="shown",
        ),
        pytest.param(
            NoReading(code="SIGNAL_TOO_WEAK", why=None, clear_percent=None),
            False,
            False,
            {"code": "SIGNAL_TOO_WEAK", "bpm_shown": 0.0, "had_reading": 0.0},
            id="too_weak",
        ),
        pytest.param(
            NoReading(
                code="READING_FLOOR_NOT_CLEARED", why="faint_pulse", clear_percent=25.0
            ),
            False,
            True,
            {"code": "READING_FLOOR_NOT_CLEARED", "bpm_shown": 0.0, "had_reading": 1.0},
            id="floor",
        ),
    ],
)
def test_the_decisions_are_logged_as_the_live_tracker_made_them(
    no_reading: NoReading | None, bpm_shown: bool, had_reading: bool, expected: Expected
) -> None:
    fields = fields_of(
        [],
        [],
        no_reading=no_reading,
        bpm_shown=bpm_shown,
        had_reading=had_reading,
    )

    assert mismatches(fields, expected) == [], fields


def alternating(count: int, end_ms: float) -> list[Interval]:
    ibis = [900.0 if k % 2 == 0 else 1_100.0 for k in range(count)]
    return chain(ibis, end_ms - sum(ibis), ("ok",) * count)


def crowded(end_ms: float, accepted: int, rejected: int) -> list[Interval]:
    flags: tuple[IntervalFlag, ...] = ("motion",) * rejected + ("ok",) * accepted
    return chain([900.0] * len(flags), end_ms - 900.0 * len(flags), flags)


def apart(count: int, end_ms: float) -> list[Interval]:
    step = BEAT_MS + 10.0
    first = end_ms - count * step
    return [
        Interval(
            start_ms=first + k * step, end_ms=first + k * step + BEAT_MS, flag="ok"
        )
        for k in range(count)
    ]


GATE_CASES = [
    pytest.param(steady(55, NEWEST_MS - 500.0), "none", id="none"),
    pytest.param(alternating(56, NEWEST_MS), "alternates", id="alternates"),
    pytest.param(
        crowded(NEWEST_MS, 52, 14), "too_many_rejected", id="too_many_rejected"
    ),
    pytest.param(steady(48, NEWEST_MS - 10_500.0), "stale", id="stale"),
    pytest.param(steady(44, NEWEST_MS), "unchecked", id="under_45_seconds"),
]


@pytest.mark.parametrize(("intervals", "gate"), GATE_CASES)
def test_the_gate_names_the_first_bpm_gate_that_fails_once_45_seconds_are_accepted(
    intervals: list[Interval], gate: str
) -> None:
    snapshot = SignalSnapshot(tuple(intervals), (), NEWEST_MS, 0.0)
    assert expected_signal(snapshot)["gate"] == gate

    fields = fields_of(intervals, [])

    assert fields["gate"] == gate, fields


HRV_GATE_CASES = [
    pytest.param(steady(70, NEWEST_MS), clear_checks(), "none", id="none"),
    pytest.param(steady(70, NEWEST_MS - 11_000.0), clear_checks(), "stale", id="stale"),
    pytest.param(
        crowded(NEWEST_MS, 70, 20),
        clear_checks(),
        "too_many_rejected",
        id="too_many_rejected",
    ),
    pytest.param(steady(50, NEWEST_MS), clear_checks(), "too_short", id="too_short"),
    pytest.param(
        apart(65, NEWEST_MS), clear_checks(), "no_successive", id="no_successive"
    ),
    pytest.param(
        alternating(70, NEWEST_MS), clear_checks(), "alternates", id="alternates"
    ),
    pytest.param(
        steady(70, NEWEST_MS),
        [WindowCheck(t_ms=c.t_ms, snr_db=1.0) for c in clear_checks()],
        "floor",
        id="floor",
    ),
    pytest.param([], clear_checks(), "unchecked", id="nothing_counted"),
]


@pytest.mark.parametrize(("intervals", "checks", "hrv_gate"), HRV_GATE_CASES)
def test_the_hrv_gate_names_the_first_variation_step_that_fails(
    intervals: list[Interval], checks: list[WindowCheck], hrv_gate: str
) -> None:
    snapshot = SignalSnapshot(tuple(intervals), tuple(checks), NEWEST_MS, 0.0)
    assert expected_signal(snapshot)["hrv_gate"] == hrv_gate
    reading = hrv_reading(intervals, NEWEST_MS, checks)
    assert (reading == NO_HRV) == (hrv_gate != "none")

    fields = fields_of(intervals, checks)

    assert fields["hrv_gate"] == hrv_gate, fields


def test_the_hrv_gate_ignores_intervals_from_before_counting_began() -> None:
    intervals = steady(70, NEWEST_MS)

    fields = fields_of(intervals, clear_checks(), NEWEST_MS, NEWEST_MS - 50_000.0)

    assert fields["hrv_gate"] == "too_short", fields


def close_minute(start_ms: float) -> list[Interval]:
    return even(CLOSE_FLAGS, start_ms)


@pytest.mark.parametrize(
    ("leading", "counted_ms"),
    [
        pytest.param([], 0.0, id="all_counted"),
        pytest.param(
            even(("gap",) * 5, NEWEST_MS - 70_000.0),
            NEWEST_MS - 65_000.0,
            id="before_counting_began",
        ),
    ],
)
def test_the_close_line_rounds_counted_interval_shares_to_the_nearest_ten(
    leading: list[Interval], counted_ms: float
) -> None:
    intervals = [*leading, *close_minute(NEWEST_MS - 55_000.0)]

    fields = close_fields(intervals, NEWEST_MS, counted_ms)

    assert fields is not None
    assert set(fields) == CLOSE_FIELDS, sorted(set(fields) ^ CLOSE_FIELDS)
    assert mismatches(fields, CLOSE_SHARES) == [], fields


@pytest.mark.parametrize(
    "counted_ms",
    [
        pytest.param(None, id="no_frames"),
        pytest.param(NEWEST_MS + 1.0, id="first_minute"),
        pytest.param(NEWEST_MS - 20_000.0, id="counted_for_20_seconds"),
        pytest.param(NEWEST_MS - 59_999.0, id="just_under_a_counted_minute"),
    ],
)
def test_there_is_no_close_line_before_a_full_counted_minute(
    counted_ms: float | None,
) -> None:
    assert (
        close_fields(close_minute(NEWEST_MS - 55_000.0), NEWEST_MS, counted_ms) is None
    )


def test_a_counted_session_without_intervals_closes_with_shares_not_a_number() -> None:
    fields = close_fields([], NEWEST_MS, 0.0)

    assert fields is not None
    assert mismatches(fields, dict.fromkeys(CLOSE_FIELDS, NOT_YET)) == [], fields


def in_motion(since_counted_ms: float) -> bool:
    return (
        since_counted_ms >= MOTION_EVERY_MS
        and since_counted_ms % MOTION_EVERY_MS < MOTION_FOR_MS
    )


def paced_chain(ibi_ms: float, phase_ms: float) -> list[Interval]:
    start_ms = COUNTED_MS + phase_ms
    count = int(SLIDE_CHAIN_MS // ibi_ms)
    flags: list[IntervalFlag] = [
        "motion" if in_motion(start_ms + k * ibi_ms - COUNTED_MS) else "ok"
        for k in range(count)
    ]
    return chain([ibi_ms] * count, start_ms, flags)


def known_at(intervals: list[Interval], newest_ms: float) -> tuple[Interval, ...]:
    return tuple(
        Interval(
            i.start_ms,
            i.end_ms,
            "edge" if i.end_ms > newest_ms - PENDING_MS else i.flag,
        )
        for i in intervals
        if i.end_ms <= newest_ms
    )


def steady_checks(newest_ms: float) -> tuple[WindowCheck, ...]:
    first_ms = COUNTED_MS - 5_000.0
    count = int((newest_ms - first_ms) // BEAT_MS) + 1
    return tuple(
        WindowCheck(t_ms=first_ms + k * BEAT_MS, snr_db=STEADY_DB) for k in range(count)
    )


def slide(ibi_ms: float, phase_ms: float) -> list[SignalSnapshot]:
    intervals = paced_chain(ibi_ms, phase_ms)
    snapshots = []
    for second in range(1, SLIDE_SECONDS + 1):
        newest_ms = COUNTED_MS + second * BEAT_MS
        snapshots.append(
            SignalSnapshot(
                known_at(intervals, newest_ms),
                steady_checks(newest_ms),
                newest_ms,
                COUNTED_MS,
            )
        )
    return snapshots


def logged_series(snapshots: list[SignalSnapshot]) -> list[dict[str, str]]:
    return [
        fields_of(s.intervals, s.checks, s.newest_ms, s.counted_ms, **QUIET)
        for s in snapshots
    ]


def test_no_line_changes_when_only_the_heart_rate_changes() -> None:
    slow, fast = slide(SLOW_IBI_MS, SLOW_PHASE_MS), slide(FAST_IBI_MS, FAST_PHASE_MS)
    truths = [[expected_signal(s) for s in series] for series in (slow, fast)]
    assert truths[0] == truths[1]
    assert {truth["gate"] for truth in truths[0]} >= {"unchecked", "none"}
    assert {truth["hrv_gate"] for truth in truths[0]} >= {"too_short", "none"}
    assert expected_close(slow[-1]) == expected_close(fast[-1])

    slow_lines, fast_lines = logged_series(slow), logged_series(fast)
    slow_close = close_fields(slow[-1].intervals, slow[-1].newest_ms, COUNTED_MS)
    fast_close = close_fields(fast[-1].intervals, fast[-1].newest_ms, COUNTED_MS)

    differing = [
        (second, name)
        for second, (a, b) in enumerate(zip(slow_lines, fast_lines, strict=True), 1)
        for name in a
        if a[name] != b[name]
    ]
    assert differing == []
    assert slow_close == fast_close
    assert slow_close is not None
