import logging
import threading
from pathlib import Path

import numpy as np
import pytest
from numpy.typing import NDArray
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from pulse_frame.stream.app import create_app
from pulse_frame.vision.errors import VisionError
from tests.stream.wire import (
    ALLOWED_ORIGINS,
    DEV_ORIGIN,
    ENDPOINT,
    FakeClock,
    ProcessorFactory,
    RecordingProcessor,
    Stream,
    assert_landmarker_closed,
    frame_message,
    frame_reply,
    open_stream,
    origin_header,
)

POLICY_VIOLATION = 1008
TRY_AGAIN_LATER = 1013
INTERNAL_ERROR = 1011
NOT_FOUND = 404
START_MS = 1000
START_WAIT_S = 10.0
RELEASE_AFTER_S = 0.2
BURST_MS = (1000, 1033, 1066)
REJECTED_ORIGINS = [
    pytest.param("http://evil.example", id="other-host"),
    pytest.param("http://127.0.0.1:8000", id="backend-port"),
    pytest.param("http://127.0.0.1:5174", id="other-port"),
    pytest.param("https://127.0.0.1:5173", id="https"),
    pytest.param("http://localhost", id="no-port"),
    pytest.param("http://127.0.0.1:5173.evil.example", id="suffix"),
    pytest.param("null", id="null"),
    pytest.param("", id="empty"),
    pytest.param(None, id="missing"),
]
HTTP_PATHS = [
    "/docs",
    "/redoc",
    "/openapi.json",
    "/docs/oauth2-redirect",
    "/",
    ENDPOINT,
]
BUILD_FAILURES = [
    pytest.param(
        VisionError("MODEL_LOAD_FAILED", "load detail 5521", "load action 5521"),
        id="model-load-failed",
    ),
    pytest.param(
        VisionError("MODEL_MISSING", "missing detail 5521", "missing action 5521"),
        id="model-missing",
    ),
]


class FailingFirstBuild:
    def __init__(self, failure: VisionError, model: Path) -> None:
        self.failure: VisionError | None = failure
        self.model = model

    def __call__(self, events: list[str]) -> RecordingProcessor:
        failure, self.failure = self.failure, None
        if failure is not None:
            raise failure
        return RecordingProcessor(self.model, events)


def held_factory(
    model: Path, release: threading.Event, started: threading.Event
) -> ProcessorFactory:
    def build(events: list[str]) -> RecordingProcessor:
        return RecordingProcessor(model, events, release=release, started=started)

    return ProcessorFactory(build)


@pytest.mark.parametrize("origin", ALLOWED_ORIGINS)
def test_allowed_origin_is_accepted_and_served(
    origin: str, factory: ProcessorFactory, clock: FakeClock, astronaut_jpeg: bytes
) -> None:
    app = create_app(processor_factory=factory, clock=clock)

    with open_stream(app, clock, origin=origin) as stream:
        turn = stream.send_frame(START_MS, astronaut_jpeg)

    assert frame_reply(turn)["face"] is True


@pytest.mark.parametrize("origin", REJECTED_ORIGINS)
def test_disallowed_or_missing_origin_is_closed_with_1008_before_accept(
    origin: str | None, factory: ProcessorFactory, clock: FakeClock
) -> None:
    app = create_app(processor_factory=factory, clock=clock)

    with (
        TestClient(app) as client,
        pytest.raises(WebSocketDisconnect) as refused,
        client.websocket_connect(ENDPOINT, headers=origin_header(origin)),
    ):
        pass

    assert refused.value.code == POLICY_VIOLATION
    assert factory.calls == []


def test_second_connection_is_closed_with_1013_and_a_new_one_is_accepted_later(
    factory: ProcessorFactory, clock: FakeClock, astronaut_jpeg: bytes
) -> None:
    app = create_app(processor_factory=factory, clock=clock)
    dev = origin_header(DEV_ORIGIN)

    with TestClient(app) as client:
        with client.websocket_connect(ENDPOINT, headers=dev) as first_socket:
            first = Stream(first_socket, clock)
            frame_reply(first.send_frame(START_MS, astronaut_jpeg))
            with (
                client.websocket_connect(ENDPOINT, headers=dev) as second,
                pytest.raises(WebSocketDisconnect) as busy,
            ):
                second.send_bytes(frame_message(START_MS + 50, astronaut_jpeg))
                second.receive_text()
            with (
                pytest.raises(WebSocketDisconnect) as foreign,
                client.websocket_connect(ENDPOINT, headers=origin_header("null")),
            ):
                pass
            still_open = first.send_frame(START_MS + 100, astronaut_jpeg)
        first_processor = factory.built[0]
        with client.websocket_connect(ENDPOINT, headers=dev) as third_socket:
            third = Stream(third_socket, clock).send_frame(START_MS, astronaut_jpeg)

    assert busy.value.code == TRY_AGAIN_LATER
    assert busy.value.reason == "ANOTHER_CONNECTION_OPEN"
    assert foreign.value.code == POLICY_VIOLATION
    assert frame_reply(still_open)["t"] == START_MS + 100
    assert frame_reply(third)["face"] is True
    assert len(factory.calls) == 2
    assert first_processor.closed
    builds = [i for i, event in enumerate(factory.events) if event == "build"]
    assert factory.events.index("close") < builds[1]


@pytest.mark.parametrize("failure", BUILD_FAILURES)
def test_processor_that_cannot_be_built_closes_with_1011_and_frees_the_slot(
    failure: VisionError,
    face_model: Path,
    clock: FakeClock,
    astronaut_jpeg: bytes,
    log_records: list[logging.LogRecord],
) -> None:
    factory = ProcessorFactory(FailingFirstBuild(failure, face_model))
    app = create_app(processor_factory=factory, clock=clock)
    dev = origin_header(DEV_ORIGIN)

    with TestClient(app) as client:
        with (
            client.websocket_connect(ENDPOINT, headers=dev) as socket,
            pytest.raises(WebSocketDisconnect) as closed,
        ):
            socket.receive_text()
        with client.websocket_connect(ENDPOINT, headers=dev) as socket:
            turn = Stream(socket, clock).send_frame(START_MS, astronaut_jpeg)

    assert closed.value.code == INTERNAL_ERROR
    assert closed.value.reason == "MODEL_LOAD_FAILED"
    assert frame_reply(turn)["face"] is True
    assert len(factory.calls) == 2
    assert not [r for r in log_records if "5521" in r.getMessage()]


def test_processor_is_built_off_the_event_loop_with_no_client_arguments(
    stream: Stream, factory: ProcessorFactory, astronaut_jpeg: bytes
) -> None:
    frame_reply(stream.send_frame(START_MS, astronaut_jpeg))

    assert factory.calls == [((), {})]
    assert factory.on_event_loop == [False]


def test_frames_are_processed_off_the_event_loop_one_at_a_time_in_order(
    stream: Stream, factory: ProcessorFactory, astronaut_jpeg: bytes
) -> None:
    for timestamp_ms in BURST_MS:
        stream.socket.send_bytes(frame_message(timestamp_ms, astronaut_jpeg))
    turns = [stream.receive_turn() for _ in BURST_MS]

    assert [frame_reply(turn)["t"] for turn in turns] == list(BURST_MS)
    processor = factory.latest
    assert processor.timestamps == list(BURST_MS)
    assert processor.on_event_loop == [False, False, False]
    assert processor.most_active == 1


def test_client_closing_the_socket_closes_its_processor(
    factory: ProcessorFactory,
    clock: FakeClock,
    astronaut_jpeg: bytes,
    astronaut_rgb: NDArray[np.uint8],
) -> None:
    app = create_app(processor_factory=factory, clock=clock)

    with open_stream(app, clock) as stream:
        frame_reply(stream.send_frame(START_MS, astronaut_jpeg))
        stream.socket.close(1000)

    processor = factory.latest
    assert processor.closed
    assert_landmarker_closed(processor, astronaut_rgb)


def test_client_leaving_mid_process_closes_the_processor_after_the_call_quietly(
    face_model: Path,
    clock: FakeClock,
    astronaut_jpeg: bytes,
    astronaut_rgb: NDArray[np.uint8],
    log_records: list[logging.LogRecord],
) -> None:
    release = threading.Event()
    started = threading.Event()
    factory = held_factory(face_model, release, started)
    app = create_app(processor_factory=factory, clock=clock)
    releaser = threading.Timer(RELEASE_AFTER_S, release.set)

    with open_stream(app, clock) as stream:
        stream.socket.send_bytes(frame_message(START_MS, astronaut_jpeg))
        assert started.wait(START_WAIT_S)
        releaser.start()
    releaser.join()

    processor = factory.latest
    assert processor.events[-1] == "close"
    assert processor.events.index("processed") < processor.events.index("close")
    assert_landmarker_closed(processor, astronaut_rgb)
    assert [r for r in log_records if r.levelno >= logging.WARNING] == []
    assert [r for r in log_records if r.exc_info is not None] == []


@pytest.mark.parametrize("path", HTTP_PATHS)
def test_no_http_route_is_served(
    path: str, factory: ProcessorFactory, clock: FakeClock
) -> None:
    with TestClient(create_app(processor_factory=factory, clock=clock)) as client:
        response = client.get(path, headers=origin_header(DEV_ORIGIN))

    assert response.status_code == NOT_FOUND
    assert "access-control-allow-origin" not in response.headers


def test_no_cors_preflight_is_allowed_for_the_dev_origin(
    factory: ProcessorFactory, clock: FakeClock
) -> None:
    with TestClient(create_app(processor_factory=factory, clock=clock)) as client:
        response = client.options(
            ENDPOINT,
            headers={
                "origin": DEV_ORIGIN,
                "access-control-request-method": "GET",
            },
        )

    assert "access-control-allow-origin" not in response.headers
    assert factory.calls == []
