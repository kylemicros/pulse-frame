import asyncio
import json
import logging
import math
import re
import struct
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np
import pytest
from fastapi import FastAPI
from numpy.typing import NDArray
from starlette.testclient import TestClient, WebSocketTestSession

from pulse_frame.monitor.processor import FrameProcessor, FrameResult
from pulse_frame.signal.tracker import Reading
from pulse_frame.stream.errors import WIRE_ERRORS
from pulse_frame.vision.errors import VisionError

ENDPOINT = "/ws/stream"
DEV_ORIGIN = "http://127.0.0.1:5173"
ALLOWED_ORIGINS = (
    "http://127.0.0.1:5173",
    "http://localhost:5173",
    "http://127.0.0.1:4173",
    "http://localhost:4173",
)
FRAME_CAP_BYTES = 204_808
PROTOCOL_CAP_BYTES = 262_144
MAX_SAFE_MS = 9_007_199_254_740_991
FRAME_REPLY_LIMIT_BYTES = 2_048
PULSE_REPLY_LIMIT_BYTES = 32_768
PULSE_MAX_PAIRS = 601
PULSE_MAX_SPAN_MS = 20_000.0
ROUNDING_SLACK_MS = 0.1
OUTLINE_LIMITS = {"forehead": 13, "left_cheek": 23, "right_cheek": 23}
PATCH_NAMES = tuple(OUTLINE_LIMITS)
MIN_HULL_POINTS = 3
READING_STATES = frozenset({"acquiring", "ok", "low_quality"})
TURN_TYPES = frozenset({"frame", "error"})
MAX_TURN_MESSAGES = 3
CLOCK_START_S = 1000.0
CLOCK_STEP_S = 0.0625
HOLD_LIMIT_S = 10.0
LATE_MS = 10**12
APP_LOGGER = "pulse_frame"
WIRE_CODES = frozenset(
    {
        "DETECTION_FAILED",
        "TRACKER_CLOSED",
        "BAD_FRAME",
        "BAD_TIMESTAMP",
        "BAD_TIMESTAMPS",
        "BAD_VALUES",
        "NOT_ENOUGH_SAMPLES",
        "BAD_SAMPLE_RATE",
        "BAD_BAND",
        "BAD_WINDOW",
        "FRAME_TOO_LARGE",
        "RATE_LIMITED",
    }
)
STANDARD_RECORD_FIELDS = frozenset(
    logging.LogRecord("", logging.INFO, "", 0, "", None, None).__dict__
) | {"message", "asctime"}

type Message = dict[str, object]


class FakeClock:
    def __init__(self, start_s: float = CLOCK_START_S) -> None:
        self.now = start_s

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def header(timestamp_ms: float) -> bytes:
    return struct.pack("<d", timestamp_ms)


def frame_message(timestamp_ms: float, jpeg: bytes) -> bytes:
    return header(timestamp_ms) + jpeg


def padded_to(message: bytes, size: int) -> bytes:
    assert len(message) <= size, f"The message is already {len(message)} bytes."
    return message + bytes(size - len(message))


def reject_constant(name: str) -> object:
    raise ValueError(f"A reply carried the non-standard JSON constant {name}.")


def strict_json(text: str) -> Message:
    parsed = json.loads(text, parse_constant=reject_constant)
    assert isinstance(parsed, dict), f"A reply is not a JSON object: {text[:200]}"
    return parsed


@dataclass(frozen=True)
class Turn:
    texts: list[str]

    @property
    def messages(self) -> list[Message]:
        return [strict_json(text) for text in self.texts]

    @property
    def types(self) -> list[str]:
        return [str(message["type"]) for message in self.messages]

    @property
    def reply(self) -> Message:
        return self.messages[-1]

    def find(self, kind: str) -> Message | None:
        found = [message for message in self.messages if message["type"] == kind]
        assert len(found) <= 1, f"More than one {kind} message in one turn."
        return found[0] if found else None

    def text_of(self, kind: str) -> str:
        found = [text for text in self.texts if strict_json(text)["type"] == kind]
        assert len(found) == 1, f"Expected one {kind} message, got {len(found)}."
        return found[0]


class Stream:
    def __init__(self, socket: WebSocketTestSession, clock: FakeClock) -> None:
        self.socket = socket
        self.clock = clock
        self.turns: list[Turn] = []

    def send(self, message: bytes | str, advance_s: float = CLOCK_STEP_S) -> Turn:
        self.clock.advance(advance_s)
        if isinstance(message, str):
            self.socket.send_text(message)
        else:
            self.socket.send_bytes(message)
        return self.receive_turn()

    def send_frame(
        self, timestamp_ms: float, jpeg: bytes, advance_s: float = CLOCK_STEP_S
    ) -> Turn:
        return self.send(frame_message(timestamp_ms, jpeg), advance_s)

    def receive_turn(self) -> Turn:
        texts: list[str] = []
        while not texts or strict_json(texts[-1])["type"] not in TURN_TYPES:
            assert len(texts) < MAX_TURN_MESSAGES, (
                f"No frame or error reply after {len(texts)} messages: {texts}"
            )
            texts.append(self.socket.receive_text())
        turn = Turn(texts)
        self.turns.append(turn)
        return turn


def origin_header(origin: str | None) -> dict[str, str]:
    return {} if origin is None else {"origin": origin}


@contextmanager
def open_stream(
    app: FastAPI,
    clock: FakeClock,
    origin: str | None = DEV_ORIGIN,
    path: str = ENDPOINT,
    headers: dict[str, str] | None = None,
) -> Iterator[Stream]:
    sent = origin_header(origin) | (headers or {})
    with TestClient(app) as client, client.websocket_connect(path, headers=sent) as ws:
        yield Stream(ws, clock)


def event_loop_running() -> bool:
    return asyncio._get_running_loop() is not None


BUILT_PROCESSORS: list[FrameProcessor] = []


class RecordingProcessor(FrameProcessor):
    def __init__(
        self,
        model: Path,
        events: list[str] | None = None,
        release: threading.Event | None = None,
        started: threading.Event | None = None,
    ) -> None:
        super().__init__(model)
        BUILT_PROCESSORS.append(self)
        self.events = [] if events is None else events
        self.release = release
        self.started = threading.Event() if started is None else started
        self.timestamps: list[object] = []
        self.shapes: list[tuple[int, ...]] = []
        self.channel_means: list[tuple[float, float, float]] = []
        self.results: list[FrameResult] = []
        self.waveforms: list[list[tuple[float, float]]] = []
        self.on_event_loop: list[bool] = []
        self.failures: dict[int, Exception] = {}
        self.readings: dict[int, Reading] = {}
        self.closed = False
        self.most_active = 0
        self._active = 0
        self._lock = threading.Lock()

    def process(self, rgb: NDArray[np.uint8], timestamp_ms: int) -> FrameResult:
        call = len(self.timestamps)
        self.timestamps.append(timestamp_ms)
        self.shapes.append(tuple(rgb.shape))
        red, green, blue = (float(v) for v in rgb.reshape(-1, 3).mean(axis=0))
        self.channel_means.append((red, green, blue))
        self.on_event_loop.append(event_loop_running())
        self.events.append("process")
        with self._lock:
            self._active += 1
            self.most_active = max(self.most_active, self._active)
        self.started.set()
        if self.release is not None:
            self.release.wait(HOLD_LIMIT_S)
        result = super().process(rgb, timestamp_ms)
        scripted = self.readings.get(call)
        if scripted is not None:
            result = replace(result, reading=scripted)
        with self._lock:
            self._active -= 1
        self.events.append("processed")
        self.results.append(result)
        failure = self.failures.get(call)
        if failure is not None:
            raise failure
        return result

    def waveform(self) -> list[tuple[float, float]]:
        samples = super().waveform()
        self.waveforms.append(samples)
        self.events.append("waveform")
        return samples

    def close(self) -> None:
        self.events.append("close")
        super().close()
        self.closed = True


class ProcessorFactory:
    def __init__(
        self,
        build: Callable[[list[str]], RecordingProcessor],
    ) -> None:
        self.build = build
        self.events: list[str] = []
        self.calls: list[tuple[tuple[object, ...], dict[str, object]]] = []
        self.on_event_loop: list[bool] = []
        self.built: list[RecordingProcessor] = []

    def __call__(self, *args: object, **kwargs: object) -> RecordingProcessor:
        self.calls.append((args, kwargs))
        self.on_event_loop.append(event_loop_running())
        self.events.append("build")
        processor = self.build(self.events)
        self.built.append(processor)
        return processor

    @property
    def latest(self) -> RecordingProcessor:
        assert self.built, "No processor was built for this connection."
        return self.built[-1]


def close_built_processors() -> None:
    while BUILT_PROCESSORS:
        FrameProcessor.close(BUILT_PROCESSORS.pop())


def recording_factory(model: Path) -> ProcessorFactory:
    return ProcessorFactory(lambda events: RecordingProcessor(model, events))


def assert_landmarker_closed(processor: FrameProcessor, rgb: NDArray[np.uint8]) -> None:
    with pytest.raises(VisionError) as caught:
        FrameProcessor.process(processor, rgb, LATE_MS)
    assert caught.value.code == "TRACKER_CLOSED"


def is_number(value: object) -> bool:
    return (
        isinstance(value, int | float)
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def has_places(value: object, places: int) -> bool:
    return is_number(value) and round(float(value), places) == value


def assert_error(turn: Turn, code: str) -> None:
    assert turn.types == ["error"], f"Expected one error reply, got {turn.texts}"
    reply = turn.reply
    assert set(reply) == {"type", "code", "message", "action"}, reply
    assert reply["code"] == code, reply
    entry = WIRE_ERRORS[code]
    assert reply["message"] == entry.message
    assert reply["action"] == entry.action


def check_patch(name: str, patch: object) -> None:
    assert isinstance(patch, dict), f"{name} is not an object: {patch!r}"
    assert set(patch) == {"usable", "outline"}, patch
    assert isinstance(patch["usable"], bool)
    outline = patch["outline"]
    if not patch["usable"]:
        assert outline is None, f"{name} is unusable but has an outline."
        return
    assert isinstance(outline, list), f"{name} outline is {outline!r}"
    assert MIN_HULL_POINTS <= len(outline) <= OUTLINE_LIMITS[name], len(outline)
    for point in outline:
        assert isinstance(point, list), point
        assert len(point) == 2, point
        for coordinate in point:
            assert has_places(coordinate, 4), coordinate
            assert 0.0 <= coordinate <= 1.0, coordinate


def frame_reply(turn: Turn) -> Message:
    reply = turn.reply
    assert reply["type"] == "frame", f"Expected a frame reply, got {turn.texts}"
    assert set(reply) == {"type", "t", "face", "moving", "patches"}, reply
    assert isinstance(reply["t"], int)
    assert not isinstance(reply["t"], bool)
    assert isinstance(reply["face"], bool)
    assert isinstance(reply["moving"], bool)
    patches = reply["patches"]
    assert isinstance(patches, dict), patches
    assert set(patches) == set(PATCH_NAMES), patches
    for name in PATCH_NAMES:
        check_patch(name, patches[name])
    return reply


def bpm_reply(message: Message) -> Message:
    assert set(message) == {"type", "t", "bpm", "quality_db", "state"}, message
    assert message["state"] in READING_STATES, message
    assert isinstance(message["t"], int)
    if message["bpm"] is not None:
        assert message["state"] == "ok", message
        assert has_places(message["bpm"], 1), message
    if message["quality_db"] is not None:
        assert has_places(message["quality_db"], 2), message
    return message


def pulse_samples(message: Message) -> list[list[float]]:
    assert set(message) == {"type", "samples"}, message
    samples = message["samples"]
    assert isinstance(samples, list)
    assert len(samples) <= PULSE_MAX_PAIRS, len(samples)
    for pair in samples:
        assert isinstance(pair, list), pair
        assert len(pair) == 2, pair
        assert has_places(pair[0], 1), pair
        assert has_places(pair[1], 4), pair
    times = [pair[0] for pair in samples]
    assert times == sorted(set(times)), "Pulse times are not strictly increasing."
    if samples:
        span = times[-1] - times[0]
        assert span <= PULSE_MAX_SPAN_MS + ROUNDING_SLACK_MS, span
    return samples


def logged_events(records: list[logging.LogRecord]) -> list[dict[str, str]]:
    events = []
    for record in records:
        if not record.name.startswith(APP_LOGGER):
            continue
        tokens = record.getMessage().split()
        fields = {key: value for key, _, value in (t.partition("=") for t in tokens)}
        if "event" in fields:
            events.append(fields)
    return events


def event_names(records: list[logging.LogRecord]) -> list[str]:
    return [fields["event"] for fields in logged_events(records)]


def app_records(
    records: list[logging.LogRecord], event: str
) -> list[logging.LogRecord]:
    return [
        record
        for record in records
        if record.name.startswith(APP_LOGGER)
        and record.getMessage().split()[:1] == [f"event={event}"]
    ]


def rendered(record: logging.LogRecord) -> str:
    extras = " ".join(
        f"{key}={value!r}"
        for key, value in record.__dict__.items()
        if key not in STANDARD_RECORD_FIELDS
    )
    return f"{record.name} {record.levelname} {record.getMessage()} {extras}"


def number_pattern(value: float) -> re.Pattern[str]:
    return re.compile(rf"(?<![\d.]){re.escape(str(value))}(?!\d)")


def leaked_points(text: str, points: list[list[float]]) -> list[list[float]]:
    return [
        point
        for point in points
        if all(number_pattern(coordinate).search(text) for coordinate in point)
    ]


def byte_needles(message: bytes) -> list[str]:
    needles = []
    for chunk in (message[:12], message[8:20]):
        needles += [
            chunk.hex(" "),
            chunk.hex(),
            chunk.hex(" ").upper(),
            repr(chunk)[2:-1],
        ]
    return needles
