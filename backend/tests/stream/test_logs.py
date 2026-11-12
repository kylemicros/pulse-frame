import logging
import math
from collections.abc import Callable

import cv2
import numpy as np
import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from pulse_frame.signal.errors import SignalError
from pulse_frame.signal.tracker import Reading
from pulse_frame.stream.app import create_app
from pulse_frame.vision.errors import VisionError
from tests.stream import jpegs
from tests.stream.wire import (
    ENDPOINT,
    FRAME_CAP_BYTES,
    MAX_SAFE_MS,
    STANDARD_RECORD_FIELDS,
    FakeClock,
    ProcessorFactory,
    Stream,
    app_records,
    assert_error,
    event_names,
    frame_message,
    frame_reply,
    header,
    logged_events,
    open_stream,
    origin_header,
    padded_to,
    rendered,
)

START_MS = 1000
FAULT_MS = 1500.75
STEP_MS = 100
ONE_SECOND_S = 1.0
SLACK_MS = 2000
RATE_LIMIT = 30
RATE_STEP_S = 1.0 / 32.0
FRAME_STEP_MS = 33
CLIENT_TEXT = "client-words-6029"
CLIENT_ORIGIN = "http://client-origin-6029.example"
CLIENT_VALUES = ("6029", "1500", "4417")
SHORT_SOF = jpegs.SOI + b"\xff\xc0\x00\x04\x08\x00"
REJECT_REASONS = {
    "BAD_FRAME": frozenset(
        {
            "text_message",
            "too_short",
            "no_soi",
            "no_sof",
            "bad_marker",
            "bad_length",
            "truncated",
            "short_sof",
            "dimensions",
            "decode_failed",
            "shape_mismatch",
        }
    ),
    "BAD_TIMESTAMP": frozenset({"out_of_range", "not_increasing", "too_far_ahead"}),
    "FRAME_TOO_LARGE": frozenset({"too_large"}),
    "RATE_LIMITED": frozenset({"rate"}),
}
OK_READING = Reading(state="ok", bpm=72.0, quality_db=4.5)
LOW_READING = Reading(state="low_quality", bpm=None, quality_db=None)
ACQUIRING_READING = Reading(state="acquiring", bpm=None, quality_db=None)
SCRIPTED_READINGS = {
    1: OK_READING,
    2: OK_READING,
    3: LOW_READING,
    4: ACQUIRING_READING,
    5: ACQUIRING_READING,
}

type Fault = Callable[[bytes], bytes | str]


def at_fault(jpeg: bytes) -> bytes:
    return frame_message(FAULT_MS, jpeg)


REJECTIONS: list[object] = [
    pytest.param(lambda jpeg: CLIENT_TEXT, "BAD_FRAME", "text_message", id="text"),
    pytest.param(lambda jpeg: b"", "BAD_FRAME", "too_short", id="empty"),
    pytest.param(
        lambda jpeg: header(FAULT_MS)[:5], "BAD_FRAME", "too_short", id="five-bytes"
    ),
    pytest.param(
        lambda jpeg: header(FAULT_MS), "BAD_FRAME", "too_short", id="header-only"
    ),
    pytest.param(
        lambda jpeg: padded_to(at_fault(jpeg), FRAME_CAP_BYTES + 1),
        "FRAME_TOO_LARGE",
        "too_large",
        id="over-the-cap",
    ),
    pytest.param(
        lambda jpeg: frame_message(math.nan, jpeg),
        "BAD_TIMESTAMP",
        "out_of_range",
        id="nan",
    ),
    pytest.param(
        lambda jpeg: frame_message(-1.0, jpeg),
        "BAD_TIMESTAMP",
        "out_of_range",
        id="negative",
    ),
    pytest.param(
        lambda jpeg: frame_message(MAX_SAFE_MS + 1, jpeg),
        "BAD_TIMESTAMP",
        "out_of_range",
        id="above-max-safe",
    ),
    pytest.param(
        lambda jpeg: frame_message(START_MS, jpeg),
        "BAD_TIMESTAMP",
        "not_increasing",
        id="repeated",
    ),
    pytest.param(
        lambda jpeg: frame_message(START_MS - 1, jpeg),
        "BAD_TIMESTAMP",
        "not_increasing",
        id="earlier",
    ),
    pytest.param(
        lambda jpeg: frame_message(START_MS + 1000 + SLACK_MS + 1, jpeg),
        "BAD_TIMESTAMP",
        "too_far_ahead",
        id="far-ahead",
    ),
    pytest.param(
        lambda jpeg: (
            header(FAULT_MS) + jpegs.encode_png(np.zeros((16, 16, 3), np.uint8))
        ),
        "BAD_FRAME",
        "no_soi",
        id="png",
    ),
    pytest.param(
        lambda jpeg: header(FAULT_MS) + b"\x00\x00" + jpeg[2:],
        "BAD_FRAME",
        "no_soi",
        id="zeroed-soi",
    ),
    pytest.param(
        lambda jpeg: header(FAULT_MS) + jpegs.without_sof(jpeg),
        "BAD_FRAME",
        "no_sof",
        id="sos-before-sof",
    ),
    pytest.param(
        lambda jpeg: header(FAULT_MS) + jpegs.SOI + jpegs.EOI,
        "BAD_FRAME",
        "no_sof",
        id="eoi-before-sof",
    ),
    pytest.param(
        lambda jpeg: header(FAULT_MS) + jpegs.SOI + b"\x00\x11\x22\x33",
        "BAD_FRAME",
        "bad_marker",
        id="not-a-marker",
    ),
    pytest.param(
        lambda jpeg: header(FAULT_MS) + jpegs.SOI + b"\xff\xd8" + jpeg[2:],
        "BAD_FRAME",
        "bad_marker",
        id="second-soi",
    ),
    pytest.param(
        lambda jpeg: header(FAULT_MS) + jpegs.SOI + b"\xff\x00" + jpeg[2:],
        "BAD_FRAME",
        "bad_marker",
        id="stuffed-zero",
    ),
    pytest.param(
        lambda jpeg: header(FAULT_MS) + jpegs.SOI + b"\xff\xe0\x00\x00" + jpeg[2:],
        "BAD_FRAME",
        "bad_length",
        id="app-length-zero",
    ),
    pytest.param(
        lambda jpeg: header(FAULT_MS) + jpegs.SOI + b"\xff\xe0\x00\x01" + jpeg[2:],
        "BAD_FRAME",
        "bad_length",
        id="app-length-one",
    ),
    pytest.param(
        lambda jpeg: header(FAULT_MS) + jpegs.SOI + b"\xff\xc0\x00\x00" + jpeg[2:],
        "BAD_FRAME",
        "bad_length",
        id="sof-length-zero",
    ),
    pytest.param(
        lambda jpeg: header(FAULT_MS) + jpegs.SOI + b"\xff\xe0\x00",
        "BAD_FRAME",
        "truncated",
        id="cut-in-length",
    ),
    pytest.param(
        lambda jpeg: header(FAULT_MS) + jpegs.SOI + b"\xff\xe0\x00\x10JFIF",
        "BAD_FRAME",
        "truncated",
        id="cut-in-segment",
    ),
    pytest.param(
        lambda jpeg: header(FAULT_MS) + jpegs.cut_inside_sof(jpeg),
        "BAD_FRAME",
        "truncated",
        id="cut-in-sof",
    ),
    pytest.param(
        lambda jpeg: header(FAULT_MS) + SHORT_SOF,
        "BAD_FRAME",
        "short_sof",
        id="short-sof",
    ),
    pytest.param(
        lambda jpeg: header(FAULT_MS) + jpegs.solid_jpeg(1921, 16),
        "BAD_FRAME",
        "dimensions",
        id="width-1921",
    ),
    pytest.param(
        lambda jpeg: header(FAULT_MS) + jpegs.with_sof_size(jpeg, 0, 256),
        "BAD_FRAME",
        "dimensions",
        id="zero-width",
    ),
    pytest.param(
        lambda jpeg: header(FAULT_MS) + jpegs.with_corrupt_huffman_table(jpeg),
        "BAD_FRAME",
        "decode_failed",
        id="undecodable",
    ),
]

DECODER_REJECTIONS = [
    pytest.param(cv2.error("decoder refused 6029"), None, "decode_failed", id="raises"),
    pytest.param(
        None, np.zeros((128, 128, 3), np.uint8), "shape_mismatch", id="other-size"
    ),
    pytest.param(None, np.zeros((256, 256), np.uint8), "shape_mismatch", id="grey"),
]

PROCESSING_FAILURES = [
    pytest.param(
        VisionError("MODEL_CORRUPT", "detail 6029", "action 6029"),
        "DETECTION_FAILED",
        id="unlisted-vision-code",
    ),
    pytest.param(
        VisionError("DETECTION_FAILED", "detail 6029", "action 6029"),
        "DETECTION_FAILED",
        id="detection-failed",
    ),
    pytest.param(
        SignalError("BAD_VALUES", "detail 6029", "action 6029"),
        "BAD_VALUES",
        id="signal-code",
    ),
]


def only_record(log_records: list[logging.LogRecord], event: str) -> logging.LogRecord:
    found = app_records(log_records, event)
    assert len(found) == 1, [record.getMessage() for record in found]
    return found[0]


def assert_no_client_values(record: logging.LogRecord) -> None:
    assert set(record.__dict__) <= STANDARD_RECORD_FIELDS, record.__dict__
    line = rendered(record)
    for value in (*CLIENT_VALUES, CLIENT_TEXT, CLIENT_ORIGIN):
        assert value not in line, line
    assert record.exc_info is None


def assert_rejection_logged(
    log_records: list[logging.LogRecord], code: str, reason: str
) -> None:
    record = only_record(log_records, "frame_rejected")
    assert reason in REJECT_REASONS[code]
    assert record.getMessage() == f"event=frame_rejected code={code} reason={reason}"
    assert_no_client_values(record)


def test_connection_open_and_close_are_logged_once_each_around_the_session(
    factory: ProcessorFactory,
    clock: FakeClock,
    astronaut_jpeg: bytes,
    log_records: list[logging.LogRecord],
) -> None:
    app = create_app(processor_factory=factory, clock=clock)

    with open_stream(app, clock) as stream:
        frame_reply(stream.send_frame(START_MS, astronaut_jpeg))
        opened_while_live = event_names(log_records)

    names = event_names(log_records)
    assert opened_while_live.count("connection_opened") == 1
    assert "connection_closed" not in opened_while_live
    assert names.count("connection_opened") == 1
    assert names.count("connection_closed") == 1
    assert names.index("connection_opened") < names.index("connection_closed")
    for event in ("connection_opened", "connection_closed"):
        assert_no_client_values(only_record(log_records, event))


@pytest.mark.parametrize("origin", [CLIENT_ORIGIN, None])
def test_rejected_origin_is_logged_without_the_origin_and_opens_nothing(
    origin: str | None,
    factory: ProcessorFactory,
    clock: FakeClock,
    log_records: list[logging.LogRecord],
) -> None:
    app = create_app(processor_factory=factory, clock=clock)

    with (
        TestClient(app) as client,
        pytest.raises(WebSocketDisconnect),
        client.websocket_connect(ENDPOINT, headers=origin_header(origin)),
    ):
        pass

    names = event_names(log_records)
    assert names.count("origin_rejected") == 1
    assert "connection_opened" not in names
    assert_no_client_values(only_record(log_records, "origin_rejected"))


@pytest.mark.parametrize(("fault", "code", "reason"), REJECTIONS)
def test_frame_rejection_logs_its_code_and_a_fixed_reason_and_no_client_value(
    stream: Stream,
    astronaut_jpeg: bytes,
    log_records: list[logging.LogRecord],
    fault: Fault,
    code: str,
    reason: str,
) -> None:
    frame_reply(stream.send_frame(START_MS, astronaut_jpeg))

    rejected = stream.send(fault(astronaut_jpeg), ONE_SECOND_S)
    follow = stream.send_frame(START_MS + ONE_SECOND_S * 1000 + STEP_MS, astronaut_jpeg)

    assert_error(rejected, code)
    frame_reply(follow)
    assert_rejection_logged(log_records, code, reason)


@pytest.mark.parametrize(("raises", "returns", "reason"), DECODER_REJECTIONS)
def test_decoder_rejection_logs_whether_decoding_failed_or_the_shape_differed(
    stream: Stream,
    astronaut_jpeg: bytes,
    log_records: list[logging.LogRecord],
    monkeypatch: pytest.MonkeyPatch,
    raises: Exception | None,
    returns: np.ndarray | None,
    reason: str,
) -> None:
    real = cv2.imdecode

    def decode(buf: object, flags: object) -> object:
        if raises is not None:
            raise raises
        return returns

    monkeypatch.setattr(cv2, "imdecode", decode)
    rejected = stream.send_frame(START_MS, astronaut_jpeg)
    monkeypatch.setattr(cv2, "imdecode", real)
    follow = stream.send_frame(START_MS, astronaut_jpeg)

    assert_error(rejected, "BAD_FRAME")
    frame_reply(follow)
    assert_rejection_logged(log_records, "BAD_FRAME", reason)


def test_rate_limited_frame_logs_the_rate_reason(
    stream: Stream, astronaut_jpeg: bytes, log_records: list[logging.LogRecord]
) -> None:
    times = [START_MS + i * FRAME_STEP_MS for i in range(RATE_LIMIT)]
    for timestamp_ms in times:
        frame_reply(stream.send_frame(timestamp_ms, astronaut_jpeg, RATE_STEP_S))

    limited = stream.send_frame(times[-1] + FRAME_STEP_MS, astronaut_jpeg, RATE_STEP_S)

    assert_error(limited, "RATE_LIMITED")
    assert_rejection_logged(log_records, "RATE_LIMITED", "rate")


@pytest.mark.parametrize(("failure", "sent"), PROCESSING_FAILURES)
def test_processing_failure_logs_the_original_code_and_the_code_sent(
    stream: Stream,
    factory: ProcessorFactory,
    astronaut_jpeg: bytes,
    log_records: list[logging.LogRecord],
    failure: VisionError | SignalError,
    sent: str,
) -> None:
    frame_reply(stream.send_frame(START_MS, astronaut_jpeg))
    factory.latest.failures[1] = failure

    failed = stream.send_frame(START_MS + STEP_MS, astronaut_jpeg)

    assert_error(failed, sent)
    record = only_record(log_records, "frame_failed")
    assert record.getMessage() == f"event=frame_failed code={failure.code} sent={sent}"
    assert_no_client_values(record)


def test_reading_state_changes_and_the_tracker_restart_are_logged(
    stream: Stream,
    factory: ProcessorFactory,
    astronaut_jpeg: bytes,
    log_records: list[logging.LogRecord],
) -> None:
    frame_reply(stream.send_frame(START_MS, astronaut_jpeg))
    factory.latest.readings.update(SCRIPTED_READINGS)

    for index in sorted(SCRIPTED_READINGS):
        frame_reply(stream.send_frame(START_MS + index * STEP_MS, astronaut_jpeg))

    events = logged_events(log_records)
    changes = [e["state"] for e in events if e["event"] == "reading_state_changed"]
    names = [e["event"] for e in events]
    assert changes == ["ok", "low_quality", "acquiring"]
    assert names.count("tracker_restarted") == 1
    low_at = next(
        i
        for i, e in enumerate(events)
        if e["event"] == "reading_state_changed" and e["state"] == "low_quality"
    )
    assert names.index("tracker_restarted") > low_at
    for event in ("reading_state_changed", "tracker_restarted"):
        for record in app_records(log_records, event):
            assert_no_client_values(record)
