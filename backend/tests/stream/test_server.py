import logging

from pulse_frame.stream.errors import WIRE_ERRORS
from tests.platform.support import Probe
from tests.stream.probes import labels
from tests.stream.served import (
    PROTOCOL_CAP_BYTES,
    QUIET_LOGGERS,
    served_frame,
)
from tests.stream.wire import byte_needles, leaked_points

LOOPBACK = "127.0.0.1"
CONFIGURED_PORT = 8000
MESSAGE_TOO_BIG = 1009
HTTP_FORBIDDEN = 403


def served_outline_points(served: Probe) -> list[list[float]]:
    patches = served.record["replies"][-1]["patches"]
    return [
        point
        for patch in patches.values()
        if patch["usable"]
        for point in patch["outline"]
    ]


def test_server_is_configured_for_127_0_0_1_on_port_8000(served: Probe) -> None:
    configured = served.record["configured"]

    assert configured["host"] == LOOPBACK
    assert configured["port"] == CONFIGURED_PORT
    assert configured["uds"] is None
    assert configured["fd"] is None
    assert configured["reload"] is False


def test_server_listens_on_127_0_0_1_only_and_answers_there(served: Probe) -> None:
    binds = [event[1] for event in served.record["events"] if event[0] == "bind"]
    listening = served.record["listening"]

    assert binds == [[LOOPBACK, 0]]
    assert len(listening) == 1
    assert listening[0][0] == LOOPBACK
    assert listening[0][1] > 0
    assert served.record["replies"][-1]["type"] == "frame"


def test_server_transport_has_deflate_off_and_names_the_sansio_websockets_protocol(
    served: Probe,
) -> None:
    configured = served.record["configured"]

    assert configured["ws"] == "websockets-sansio"
    assert configured["ws_per_message_deflate"] is False
    assert configured["ws_max_size"] == PROTOCOL_CAP_BYTES
    assert served.record["extensions"] is None


def test_server_runs_clean_with_warnings_as_errors(served: Probe) -> None:
    assert served.returncode == 0, served.stderr[-3000:]
    assert "Warning" not in served.stderr
    assert "Traceback" not in served.stderr
    assert "client_error" not in served.record


def test_server_sets_uvicorn_and_websockets_loggers_to_info(served: Probe) -> None:
    assert served.record["logger_levels"] == dict.fromkeys(QUIET_LOGGERS, logging.INFO)


def test_frame_through_the_real_server_at_debug_logs_no_frame_bytes_or_outlines(
    served: Probe,
) -> None:
    records = served.record["log_records"]
    needles = byte_needles(served_frame())
    points = served_outline_points(served)

    assert records, "The probe caught no log record at all."
    assert points, "The served frame had no usable patch outline."
    for line in [*records, served.stderr, served.stdout]:
        assert not [needle for needle in needles if needle in line], line[:300]
        assert leaked_points(line, points) == [], line[:300]
        assert "array(" not in line


def test_message_at_the_protocol_cap_is_too_large_and_one_byte_more_closes_with_1009(
    served: Probe,
) -> None:
    at_cap = served.record["at_cap_replies"]

    assert len(at_cap) == 1
    assert at_cap[0] == {
        "type": "error",
        "code": "FRAME_TOO_LARGE",
        "message": WIRE_ERRORS["FRAME_TOO_LARGE"].message,
        "action": WIRE_ERRORS["FRAME_TOO_LARGE"].action,
    }
    assert served.record["over_cap_raised"] == "ConnectionClosedError"
    assert served.record["over_cap_close"] == MESSAGE_TOO_BIG


def test_protocol_close_closes_the_connection_processor(served: Probe) -> None:
    assert served.record["processor_closed"] is True
    assert served.record["processor_closes"] >= 1
    assert labels(served.record["events"]).count("landmarker") == 1


def test_missing_origin_on_the_real_server_is_refused_with_http_403(
    served: Probe,
) -> None:
    assert served.record["missing_origin_status"] == HTTP_FORBIDDEN
