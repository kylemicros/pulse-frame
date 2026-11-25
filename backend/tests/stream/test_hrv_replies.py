import math
from dataclasses import replace
from pathlib import Path

import pytest

from pulse_frame.monitor.processor import FrameProcessor
from pulse_frame.signal.live import LiveHrv
from pulse_frame.signal.summary import (
    NoReading,
    Summary,
    decide_no_reading,
    summarise,
)
from pulse_frame.stream.app import process_frame
from pulse_frame.stream.replies import encoded, hrv_message
from tests.counted_runs import (
    HALF_RATE_IBI_MS,
    WARMED_UP_RUNS,
    frames_of,
    heart_rate_under_the_reading_floor,
    ramped,
)
from tests.stream.wire import Message, has_places, strict_json

CAPTURE_MS = 123_456
HRV_FIELDS = {
    "type",
    "t",
    "rmssd_ms",
    "sdnn_ms",
    "minute_bpm",
    "minute_count",
    "bpm_low",
    "bpm_high",
    "no_reading",
    "why",
    "clear_percent",
}
NO_READING_CODES = {"SIGNAL_TOO_WEAK", "READING_FLOOR_NOT_CLEARED"}
WHY_CODES = {"face_left_view", "faint_pulse"}
MINUTE_BPM = 72.04
RMSSD_MS = 41.62
SDNN_MS = 34.68
MINUTE_COUNT = 68
RANGE_LOW = 70.04
RANGE_HIGH = 74.06
TINY_SHARE = 100.0 / 2_501
TINY_SPAN_SHARE = 100.0 / 36_001
UNDER_HALF_SHARE = 100.0 * 49 / 1_999
NON_FINITE = [
    pytest.param(math.nan, id="nan"),
    pytest.param(math.inf, id="inf"),
    pytest.param(-math.inf, id="minus_inf"),
]
DECISION_FIELDS = ("no_reading", "why", "clear_percent")
WIRE_NAMES = {"rmssd_ms": "rmssd_ms", "sdnn_ms": "sdnn_ms", "bpm": "minute_bpm"}
FRAME_MS = 1_000
NEWEST_MS = 400_000.0
READING = Summary(
    bpm=MINUTE_BPM,
    rmssd_ms=RMSSD_MS,
    sdnn_ms=SDNN_MS,
    count=MINUTE_COUNT,
    accepted_percent=100.0,
)
NOTHING = Summary(bpm=None, rmssd_ms=None, sdnn_ms=None, count=0, accepted_percent=None)
DECISIONS = [
    pytest.param(
        NoReading(code="SIGNAL_TOO_WEAK", why=None, clear_percent=None), id="weak"
    ),
    pytest.param(
        NoReading(
            code="READING_FLOOR_NOT_CLEARED", why="faint_pulse", clear_percent=25.0
        ),
        id="faint_pulse",
    ),
    pytest.param(
        NoReading(
            code="READING_FLOOR_NOT_CLEARED",
            why="face_left_view",
            clear_percent=None,
        ),
        id="face_left_view",
    ),
]


def assert_contract(message: Message) -> Message:
    assert set(message) == HRV_FIELDS, message
    assert message["type"] == "hrv"
    assert isinstance(message["t"], int)
    assert not isinstance(message["t"], bool)
    assert isinstance(message["minute_count"], int)
    assert not isinstance(message["minute_count"], bool)
    for name in ("rmssd_ms", "sdnn_ms", "minute_bpm", "bpm_low", "bpm_high"):
        assert message[name] is None or has_places(message[name], 1), message
    low, high, bpm = message["bpm_low"], message["bpm_high"], message["minute_bpm"]
    if low is None or high is None:
        assert low is None and high is None, message
    else:
        assert bpm is not None, message
        assert low <= bpm <= high, message
    assert message["no_reading"] in {None, *NO_READING_CODES}
    assert message["why"] in {None, *WHY_CODES}
    texts = {value for value in message.values() if isinstance(value, str)}
    assert texts <= {"hrv", *NO_READING_CODES, *WHY_CODES}, texts
    return strict_json(encoded(message))


def test_an_hrv_reply_carries_the_minute_reading_rounded_to_one_place() -> None:
    message = assert_contract(hrv_message(CAPTURE_MS, READING, None))

    assert message == {
        "type": "hrv",
        "t": CAPTURE_MS,
        "rmssd_ms": round(RMSSD_MS, 1),
        "sdnn_ms": round(SDNN_MS, 1),
        "minute_bpm": round(MINUTE_BPM, 1),
        "minute_count": MINUTE_COUNT,
        "bpm_low": None,
        "bpm_high": None,
        "no_reading": None,
        "why": None,
        "clear_percent": None,
    }


def test_an_hrv_reply_without_a_reading_is_all_null_with_a_zero_count() -> None:
    message = assert_contract(hrv_message(CAPTURE_MS, NOTHING, None))

    assert message["minute_count"] == 0
    assert [message[name] for name in ("rmssd_ms", "sdnn_ms", "minute_bpm")] == [
        None,
        None,
        None,
    ]


@pytest.mark.parametrize("decision", DECISIONS)
def test_an_hrv_reply_carries_the_no_reading_decision_as_codes_only(
    decision: NoReading,
) -> None:
    message = assert_contract(hrv_message(CAPTURE_MS, NOTHING, decision))

    assert message["no_reading"] == decision.code
    assert message["why"] == decision.why
    assert message["clear_percent"] == decision.clear_percent


@pytest.mark.parametrize("share", [TINY_SHARE, TINY_SPAN_SHARE, UNDER_HALF_SHARE])
def test_a_clear_share_reaches_the_page_unrounded_so_its_whole_number_holds(
    share: float,
) -> None:
    decision = NoReading(
        code="READING_FLOOR_NOT_CLEARED", why="faint_pulse", clear_percent=share
    )

    message = assert_contract(hrv_message(CAPTURE_MS, NOTHING, decision))

    assert message["clear_percent"] == share
    assert message["clear_percent"] > 0.0


@pytest.mark.parametrize("bad", NON_FINITE)
@pytest.mark.parametrize("field", ["rmssd_ms", "sdnn_ms", "bpm"])
def test_a_non_finite_reading_value_reaches_the_page_as_null(
    field: str, bad: float
) -> None:
    summary = replace(READING, **{field: bad})

    message = hrv_message(CAPTURE_MS, summary, None)

    sent = WIRE_NAMES[field]
    assert message[sent] is None, message
    kept = {name: message[name] for name in WIRE_NAMES.values() if name != sent}
    assert all(value is not None for value in kept.values()), kept
    assert_contract(message)


@pytest.mark.parametrize("bad", NON_FINITE)
def test_a_faint_pulse_without_a_finite_share_sends_no_decision_at_all(
    bad: float,
) -> None:
    decision = NoReading(
        code="READING_FLOOR_NOT_CLEARED", why="faint_pulse", clear_percent=bad
    )

    message = hrv_message(CAPTURE_MS, NOTHING, decision)

    assert [message[name] for name in DECISION_FIELDS] == [None, None, None], message
    assert_contract(message)


def test_a_minute_bpm_without_variation_sends_no_no_reading_decision() -> None:
    intervals, checks, newest_ms = heart_rate_under_the_reading_floor()
    result = summarise(intervals, newest_ms, checks)

    message = assert_contract(
        hrv_message(
            CAPTURE_MS, result, decide_no_reading(result, checks, newest_ms, False)
        )
    )

    assert result.bpm is not None
    assert result.bpm_low is not None
    assert result.bpm_high is not None
    assert message == {
        "type": "hrv",
        "t": CAPTURE_MS,
        "rmssd_ms": None,
        "sdnn_ms": None,
        "minute_bpm": round(result.bpm, 1),
        "minute_count": result.count,
        "bpm_low": round(result.bpm_low, 1),
        "bpm_high": round(result.bpm_high, 1),
        "no_reading": None,
        "why": None,
        "clear_percent": None,
    }


def test_a_too_weak_live_run_builds_an_hrv_reply_with_its_code() -> None:
    live = LiveHrv()
    frames = frames_of(WARMED_UP_RUNS["too_weak"]())
    for t_ms, colours in frames:
        live.add(t_ms, colours, moving=False)

    message = assert_contract(
        hrv_message(frames[-1][0], live.summary(), live.no_reading())
    )

    assert message["t"] == frames[-1][0]
    assert message["no_reading"] == "SIGNAL_TOO_WEAK"
    assert message["minute_bpm"] is None


def test_the_worker_builds_the_hrv_reply_only_when_a_reading_is_due(
    face_model: Path, astronaut_jpeg: bytes
) -> None:
    live = LiveHrv()
    with FrameProcessor(face_model) as processor:
        due = process_frame(processor, live, astronaut_jpeg, FRAME_MS, True)
        not_due = process_frame(processor, live, astronaut_jpeg, 2 * FRAME_MS, False)

    assert due.hrv is not None
    message = assert_contract(due.hrv)
    assert message["t"] == FRAME_MS
    assert not_due.hrv is None
    assert live.counted_from_ms == FRAME_MS + 60_000.0


def test_a_half_rate_minute_sends_no_bpm_rmssd_or_sdnn_but_keeps_its_count() -> None:
    intervals, checks = ramped(HALF_RATE_IBI_MS, NEWEST_MS)
    half_rate = summarise(intervals, NEWEST_MS, checks)

    message = assert_contract(hrv_message(CAPTURE_MS, half_rate, None))

    assert [message[name] for name in ("minute_bpm", "rmssd_ms", "sdnn_ms")] == [
        None,
        None,
        None,
    ]
    assert message["minute_count"] == half_rate.count > 0


def test_an_hrv_reply_sends_the_range_rounded_to_one_place() -> None:
    ranged = replace(READING, bpm_low=RANGE_LOW, bpm_high=RANGE_HIGH)

    message = assert_contract(hrv_message(CAPTURE_MS, ranged, None))

    assert (message["bpm_low"], message["bpm_high"]) == (70.0, 74.1)


@pytest.mark.parametrize("bad", NON_FINITE)
@pytest.mark.parametrize("field", ["bpm_low", "bpm_high", "bpm"])
def test_a_non_finite_range_end_or_minute_bpm_sends_no_range_at_all(
    field: str, bad: float
) -> None:
    ranged = replace(READING, bpm_low=RANGE_LOW, bpm_high=RANGE_HIGH)

    message = hrv_message(CAPTURE_MS, replace(ranged, **{field: bad}), None)

    assert (message["bpm_low"], message["bpm_high"]) == (None, None), message
    assert message["minute_bpm"] == (None if field == "bpm" else round(MINUTE_BPM, 1))
    assert_contract(message)


def test_a_clean_live_run_sends_a_range_around_its_minute_bpm() -> None:
    live = LiveHrv()
    frames = frames_of(WARMED_UP_RUNS["clean"]())
    for t_ms, colours in frames:
        live.add(t_ms, colours, moving=False)

    message = assert_contract(
        hrv_message(frames[-1][0], live.summary(), live.no_reading())
    )

    assert message["minute_bpm"] is not None
    assert message["bpm_low"] is not None
    assert message["bpm_high"] is not None
    assert message["bpm_low"] <= message["minute_bpm"] <= message["bpm_high"]
