import math
import time
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
import pytest
from numpy.typing import NDArray

from pulse_frame.monitor.processor import Patch
from pulse_frame.signal.tracker import Reading
from pulse_frame.stream.app import create_app
from pulse_frame.stream.replies import bpm_message, encoded, patch_message
from pulse_frame.vision.landmarks import FaceTracker
from pulse_frame.vision.regions import named_region_polygons
from tests.frames import SEED, TRUE_BPM, pulse_timestamps, pulsed_frame, shifted_right
from tests.stream.jpegs import encode_jpeg
from tests.stream.wire import (
    FRAME_REPLY_LIMIT_BYTES,
    OUTLINE_LIMITS,
    PATCH_NAMES,
    PULSE_MAX_PAIRS,
    PULSE_MAX_SPAN_MS,
    PULSE_REPLY_LIMIT_BYTES,
    ROUNDING_SLACK_MS,
    FakeClock,
    Message,
    ProcessorFactory,
    RecordingProcessor,
    Turn,
    bpm_reply,
    frame_reply,
    open_stream,
    pulse_samples,
    recording_factory,
    strict_json,
)

START_MS = 1000
NEXT_MS = 1100
PULSE_S = 23.0
PULSE_PHASE = 0.3
HEADER_FRACTION = 0.75
SESSION_CLOCK_STEP_S = 0.125
SESSION_STEP_MS = 100
MOTION_FRAMES = 15
MOTION_SHIFT_PX = 12
BLANK_FRAMES = 25
JPEG_QUALITY = 90
SETTLE_MS = 20_000
READING_INTERVAL_MS = 1000
GRID_STEP_MS = 1000.0 / 30.0
GRID_TOLERANCE_MS = 0.15
MIN_FULL_SPAN_MS = 19_000.0
OUTLINE_TOLERANCE = 2e-4
DECODE_FLAGS = cv2.IMREAD_COLOR | cv2.IMREAD_IGNORE_ORIENTATION
HINTED_PATH = "/ws/stream?fs_hz=60&window_s=5&min_seconds=1"
HINTED_HEADERS = {"x-sample-rate": "60", "x-window-seconds": "5"}
REAL_DELAYS_S = (0.02, 0.04, 0.03)
REAL_HEADERS = (0.0, 33.0, 66.0, 99.9)
REAL_EXPECTED = [0, 33, 66, 99]


@dataclass(frozen=True)
class Session:
    turns: list[Turn]
    phases: list[str]
    sent_ms: list[int]
    processor: RecordingProcessor
    factory: ProcessorFactory


def session_schedule(
    rgb: NDArray[np.uint8],
) -> list[tuple[str, int, bytes]]:
    rng = np.random.default_rng(SEED)
    times = pulse_timestamps(rng, PULSE_S)
    schedule = []
    for t in times:
        frame = pulsed_frame(rgb, rng, TRUE_BPM, PULSE_PHASE, t / 1000)
        schedule.append(("pulse", t, encode_jpeg(frame, JPEG_QUALITY)))
    last = times[-1]
    for i in range(MOTION_FRAMES):
        t = last + (i + 1) * SESSION_STEP_MS
        frame = pulsed_frame(rgb, rng, TRUE_BPM, PULSE_PHASE, t / 1000)
        moved = shifted_right(frame, MOTION_SHIFT_PX * ((i + 1) % 2))
        schedule.append(("motion", t, encode_jpeg(moved, JPEG_QUALITY)))
    last = schedule[-1][1]
    blank = encode_jpeg(np.zeros_like(rgb), JPEG_QUALITY)
    for i in range(BLANK_FRAMES):
        schedule.append(("blank", last + (i + 1) * SESSION_STEP_MS, blank))
    return schedule


@pytest.fixture(scope="module")
def session(face_model: Path, astronaut_rgb: NDArray[np.uint8]) -> Session:
    clock = FakeClock()
    factory = recording_factory(face_model)
    app = create_app(processor_factory=factory, clock=clock)
    schedule = session_schedule(astronaut_rgb)
    with open_stream(app, clock, path=HINTED_PATH, headers=HINTED_HEADERS) as stream:
        turns = [
            stream.send_frame(t + HEADER_FRACTION, jpeg, SESSION_CLOCK_STEP_S)
            for _, t, jpeg in schedule
        ]
    return Session(
        turns=turns,
        phases=[phase for phase, _, _ in schedule],
        sent_ms=[t for _, t, _ in schedule],
        processor=factory.latest,
        factory=factory,
    )


def due_readings(times: list[int]) -> list[bool]:
    due: list[bool] = []
    last: int | None = None
    for t in times:
        is_due = last is None or t - last >= READING_INTERVAL_MS
        if is_due:
            last = t
        due.append(is_due)
    return due


def rounded_or_none(value: float | None, places: int) -> float | None:
    return None if value is None else round(value, places)


def bpm_messages(session: Session) -> list[tuple[int, Message]]:
    found = []
    for index, turn in enumerate(session.turns):
        message = turn.find("bpm")
        if message is not None:
            found.append((index, bpm_reply(message)))
    return found


def pulse_messages(session: Session) -> list[list[list[float]]]:
    return [
        pulse_samples(message)
        for turn in session.turns
        if (message := turn.find("pulse")) is not None
    ]


def decoded_rgb(jpeg: bytes) -> NDArray[np.uint8]:
    bgr = cv2.imdecode(np.frombuffer(jpeg, np.uint8), DECODE_FLAGS)
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)


def matched_within(
    wire: list[list[float]], expected: NDArray[np.float64], tolerance: float
) -> bool:
    remaining = [tuple(point) for point in np.round(expected, 4).tolist()]
    for point in wire:
        close = [
            other
            for other in remaining
            if abs(other[0] - point[0]) <= tolerance
            and abs(other[1] - point[1]) <= tolerance
        ]
        if not close:
            return False
        remaining.remove(close[0])
    return not remaining


def test_fixture_frame_gets_its_reading_then_one_frame_reply_with_usable_patches(
    face_model: Path, astronaut_jpeg: bytes
) -> None:
    clock = FakeClock()
    app = create_app(clock=clock)

    with open_stream(app, clock) as stream:
        first = stream.send_frame(START_MS, astronaut_jpeg)
        second = stream.send_frame(NEXT_MS, astronaut_jpeg)
    with FaceTracker(face_model) as tracker:
        face = tracker.detect(decoded_rgb(astronaut_jpeg), START_MS)
    assert face is not None
    expected = named_region_polygons(face)

    assert sorted(first.types[:2]) == ["bpm", "pulse"]
    assert first.types[2:] == ["frame"]
    assert second.types == ["frame"]
    reply = frame_reply(first)
    assert reply["t"] == START_MS
    assert reply["face"] is True
    for name in PATCH_NAMES:
        patch = reply["patches"][name]
        assert patch["usable"] is True
        assert len(patch["outline"]) <= OUTLINE_LIMITS[name]
        assert matched_within(patch["outline"], expected[name], OUTLINE_TOLERANCE)


def test_blank_frame_gets_a_frame_reply_without_face_or_usable_patches(
    blank_jpeg: bytes,
) -> None:
    clock = FakeClock()

    with open_stream(create_app(clock=clock), clock) as stream:
        turn = stream.send_frame(START_MS, blank_jpeg)

    reply = frame_reply(turn)
    assert reply["face"] is False
    assert reply["moving"] is False
    assert reply["patches"] == {
        name: {"usable": False, "outline": None} for name in PATCH_NAMES
    }


def test_processor_gets_the_header_capture_time_rounded_down_never_arrival_time(
    face_model: Path, astronaut_jpeg: bytes
) -> None:
    factory = recording_factory(face_model)
    app = create_app(processor_factory=factory)
    stream_turns = []

    with open_stream(app, FakeClock()) as stream:
        stream_turns.append(stream.send_frame(REAL_HEADERS[0], astronaut_jpeg, 0.0))
        for delay_s, sent in zip(REAL_DELAYS_S, REAL_HEADERS[1:], strict=True):
            time.sleep(delay_s)
            stream_turns.append(stream.send_frame(sent, astronaut_jpeg, 0.0))

    assert factory.latest.timestamps == REAL_EXPECTED
    assert all(type(t) is int for t in factory.latest.timestamps)
    assert [frame_reply(turn)["t"] for turn in stream_turns] == REAL_EXPECTED


def test_every_session_frame_is_answered_with_a_frame_reply(session: Session) -> None:
    replies = [frame_reply(turn) for turn in session.turns]

    assert [reply["t"] for reply in replies] == session.sent_ms
    assert session.processor.timestamps == session.sent_ms
    assert [reply["face"] for reply in replies] == [
        result.face for result in session.processor.results
    ]
    assert [reply["moving"] for reply in replies] == [
        result.moving for result in session.processor.results
    ]


def test_client_values_never_change_the_sample_rate_or_window(
    session: Session,
) -> None:
    pulses = [samples for samples in pulse_messages(session) if samples]
    acquiring_until = session.sent_ms[0] + SETTLE_MS

    assert session.factory.calls == [((), {})]
    latest = pulses[-1]
    steps = np.diff([pair[0] for pair in latest])
    assert np.all(np.abs(steps - GRID_STEP_MS) <= GRID_TOLERANCE_MS)
    longest = max(samples[-1][0] - samples[0][0] for samples in pulses)
    assert longest >= MIN_FULL_SPAN_MS
    assert longest <= PULSE_MAX_SPAN_MS + ROUNDING_SLACK_MS
    for _, message in bpm_messages(session):
        if message["t"] < acquiring_until:
            assert message["state"] == "acquiring"


def test_bpm_values_follow_the_state_and_pass_the_reading_through(
    session: Session,
) -> None:
    found = bpm_messages(session)

    states = {message["state"] for _, message in found}
    assert {"acquiring", "ok", "low_quality"} <= states
    for index, message in found:
        reading = session.processor.results[index].reading
        assert message == {
            "type": "bpm",
            "t": session.sent_ms[index],
            "bpm": rounded_or_none(reading.bpm, 1),
            "quality_db": rounded_or_none(reading.quality_db, 2),
            "state": reading.state,
        }
        if message["state"] == "acquiring":
            assert message["bpm"] is None
            assert message["quality_db"] is None


def test_quality_is_null_for_motion_and_for_frames_without_skin(
    session: Session,
) -> None:
    found = bpm_messages(session)
    motion = [m for i, m in found if session.phases[i] == "motion"]
    blank = [m for i, m in found if session.phases[i] == "blank"]

    assert motion
    assert any(m["state"] == "low_quality" and m["quality_db"] is None for m in motion)
    assert all(m["state"] != "ok" for m in motion)
    assert blank
    assert all(m["bpm"] is None and m["quality_db"] is None for m in blank)
    assert blank[-1]["state"] == "acquiring"


def test_reading_and_pulse_come_on_the_first_frame_then_once_a_second(
    session: Session,
) -> None:
    due = due_readings(session.sent_ms)

    for turn, is_due in zip(session.turns, due, strict=True):
        if is_due:
            assert sorted(turn.types[:2]) == ["bpm", "pulse"]
            assert turn.types[2:] == ["frame"]
        else:
            assert turn.types == ["frame"]
    assert len(session.processor.waveforms) == sum(due)


def test_pulse_samples_are_the_processor_waveform_rounded(session: Session) -> None:
    pulses = pulse_messages(session)

    assert len(pulses) == len(session.processor.waveforms)
    for samples, waveform in zip(pulses, session.processor.waveforms, strict=True):
        assert samples == [[round(t, 1), round(v, 4)] for t, v in waveform]


def test_ok_reading_is_rounded_to_one_decimal_bpm_and_two_decimal_quality(
    session: Session,
) -> None:
    ok = [
        (message, session.processor.results[index].reading)
        for index, message in bpm_messages(session)
        if message["state"] == "ok"
    ]

    assert ok, "The pulsed session never reached an ok reading."
    assert any(reading.bpm != round(reading.bpm, 1) for _, reading in ok)
    assert any(reading.quality_db != round(reading.quality_db, 2) for _, reading in ok)
    for message, reading in ok:
        assert message["bpm"] == round(reading.bpm, 1)
        assert message["quality_db"] == round(reading.quality_db, 2)


def test_pulse_is_empty_at_first_then_spans_at_most_twenty_seconds_and_601_pairs(
    session: Session,
) -> None:
    pulses = pulse_messages(session)

    assert pulses[0] == []
    assert max(len(samples) for samples in pulses) <= PULSE_MAX_PAIRS
    assert max(len(samples) for samples in pulses) > PULSE_MAX_PAIRS // 2


def test_frame_and_pulse_replies_stay_within_their_size_bounds(
    session: Session,
) -> None:
    frame_sizes = [len(turn.text_of("frame").encode()) for turn in session.turns]
    pulse_sizes = [
        len(turn.text_of("pulse").encode())
        for turn in session.turns
        if turn.find("pulse") is not None
    ]

    assert max(frame_sizes) <= FRAME_REPLY_LIMIT_BYTES
    assert max(pulse_sizes) <= PULSE_REPLY_LIMIT_BYTES
    assert min(pulse_sizes) > 0


def test_every_reply_is_strict_json(session: Session) -> None:
    texts = [text for turn in session.turns for text in turn.texts]

    assert texts
    for text in texts:
        strict_json(text)
        assert "NaN" not in text
        assert "Infinity" not in text


def test_bpm_is_null_whenever_the_state_is_not_ok() -> None:
    message = bpm_message(
        START_MS, Reading(state="low_quality", bpm=70.0, quality_db=3.0)
    )

    assert message == {
        "type": "bpm",
        "t": START_MS,
        "bpm": None,
        "quality_db": 3.0,
        "state": "low_quality",
    }


def test_unusable_patch_never_carries_its_outline() -> None:
    outline = np.array([[0.1, 0.1], [0.4, 0.1], [0.2, 0.3]], dtype=np.float64)

    assert patch_message(Patch(usable=False, outline=outline)) == {
        "usable": False,
        "outline": None,
    }


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_encoding_refuses_values_that_are_not_strict_json(value: float) -> None:
    with pytest.raises(ValueError, match="JSON compliant"):
        encoded({"x": value})
