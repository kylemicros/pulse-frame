from pathlib import Path

import pytest

from pulse_frame.monitor.processor import FrameProcessor
from pulse_frame.signal.live import LiveHrv
from pulse_frame.signal.summary import NoReading, Summary, summarise
from pulse_frame.stream.app import process_frame
from pulse_frame.stream.replies import encoded, hrv_message
from tests.counted_runs import HALF_RATE_IBI_MS, WARMED_UP_RUNS, frames_of, ramped
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
TINY_SHARE = 100.0 / 2_501
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
    for name in ("rmssd_ms", "sdnn_ms", "minute_bpm"):
        assert message[name] is None or has_places(message[name], 1), message
    assert message["bpm_low"] is None
    assert message["bpm_high"] is None
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


def test_a_clear_share_under_one_percent_reaches_the_page_above_zero() -> None:
    decision = NoReading(
        code="READING_FLOOR_NOT_CLEARED", why="faint_pulse", clear_percent=TINY_SHARE
    )

    message = assert_contract(hrv_message(CAPTURE_MS, NOTHING, decision))

    assert message["clear_percent"] == TINY_SHARE
    assert 0.0 < message["clear_percent"] < 1.0


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
