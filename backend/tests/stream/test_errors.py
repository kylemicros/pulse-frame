import logging
import math
import tempfile
from pathlib import Path

import cv2
import numpy as np
import pytest
from numpy.typing import NDArray

from pulse_frame.signal.errors import SignalError
from pulse_frame.stream.app import create_app
from pulse_frame.stream.errors import WIRE_ERRORS
from pulse_frame.vision.errors import VisionError
from pulse_frame.vision.landmarks import FaceTracker
from tests.platform.sandboxed import BACKEND
from tests.stream.jpegs import solid_jpeg
from tests.stream.wire import (
    FRAME_CAP_BYTES,
    WIRE_CODES,
    FakeClock,
    ProcessorFactory,
    Stream,
    Turn,
    assert_error,
    byte_needles,
    frame_message,
    frame_reply,
    header,
    leaked_points,
    open_stream,
    padded_to,
    recording_factory,
    rendered,
)

START_MS = 1000
FAILED_MS = 2000
BETWEEN_MS = 1500
AFTER_MS = 2033
ONE_SECOND_S = 1.0
SECRET = "developer-only detail 7731"
SECRET_ACTION = "developer-only action 7731"
CLIENT_TEXT = "client-text-4417"
CLIENT_MS = 4417.25
SKIPPED_DIRECTORIES = frozenset(
    {".venv", "__pycache__", ".pytest_cache", ".ruff_cache"}
)
DASHES = (chr(0x2013), chr(0x2014))
LANDMARKS_CHECKED = 40
NOT_ENOUGH_SAMPLES_MESSAGE = (
    "The pulse tracker does not have enough frames to read a pulse yet."
)
PROCESSING_ERRORS = [
    pytest.param(VisionError("DETECTION_FAILED", SECRET, SECRET_ACTION), id="detect"),
    pytest.param(VisionError("TRACKER_CLOSED", SECRET, SECRET_ACTION), id="closed"),
    pytest.param(VisionError("BAD_FRAME", SECRET, SECRET_ACTION), id="vision-frame"),
    pytest.param(VisionError("BAD_TIMESTAMP", SECRET, SECRET_ACTION), id="vision-ts"),
    pytest.param(SignalError("NOT_ENOUGH_SAMPLES", SECRET, SECRET_ACTION), id="few"),
    pytest.param(SignalError("BAD_TIMESTAMPS", SECRET, SECRET_ACTION), id="times"),
    pytest.param(SignalError("BAD_VALUES", SECRET, SECRET_ACTION), id="values"),
    pytest.param(SignalError("BAD_SAMPLE_RATE", SECRET, SECRET_ACTION), id="rate"),
    pytest.param(SignalError("BAD_BAND", SECRET, SECRET_ACTION), id="band"),
    pytest.param(SignalError("BAD_WINDOW", SECRET, SECRET_ACTION), id="window"),
]


def backend_files() -> set[Path]:
    found: set[Path] = set()
    for folder, directories, files in BACKEND.walk():
        directories[:] = [d for d in directories if d not in SKIPPED_DIRECTORIES]
        found.update(folder / name for name in files)
    return found


def landmark_texts(face_model: Path, rgb: NDArray[np.uint8]) -> list[str]:
    with FaceTracker(face_model) as tracker:
        face = tracker.detect(rgb, START_MS)
    assert face is not None
    return [repr(float(v)) for v in face.points[:LANDMARKS_CHECKED].ravel()]


def outline_points(turns: list[Turn]) -> list[list[float]]:
    points: list[list[float]] = []
    for turn in turns:
        if turn.reply["type"] == "frame":
            for patch in turn.reply["patches"].values():
                if patch["usable"]:
                    points.extend(patch["outline"])
    return points


def test_wire_table_covers_exactly_the_contract_codes_with_fixed_text() -> None:
    assert set(WIRE_ERRORS) == WIRE_CODES
    for code, entry in WIRE_ERRORS.items():
        assert entry.message.strip(), code
        assert entry.action.strip(), code
        for text in (entry.message, entry.action):
            assert "{" not in text
            assert "%" not in text
            assert not any(dash in text for dash in DASHES)


@pytest.mark.parametrize("failure", PROCESSING_ERRORS)
def test_processing_error_replies_with_the_wire_entry_and_logs_no_developer_text(
    stream: Stream,
    factory: ProcessorFactory,
    astronaut_jpeg: bytes,
    failure: VisionError | SignalError,
    log_records: list[logging.LogRecord],
) -> None:
    frame_reply(stream.send_frame(START_MS, astronaut_jpeg))
    factory.latest.failures[1] = failure

    failed = stream.send_frame(FAILED_MS, astronaut_jpeg, ONE_SECOND_S)

    assert_error(failed, failure.code)
    text = failed.texts[0]
    for leak in (SECRET, SECRET_ACTION, "Traceback", type(failure).__name__):
        assert leak not in text
    lines = [rendered(record) for record in log_records]
    assert any(failure.code in line for line in lines)
    assert not [line for line in lines if SECRET in line or SECRET_ACTION in line]
    assert not [line for line in lines if "Traceback" in line]
    assert [record for record in log_records if record.exc_info is not None] == []


def test_not_enough_samples_reply_says_the_tracker_needs_more_frames_for_a_pulse(
    stream: Stream, factory: ProcessorFactory, astronaut_jpeg: bytes
) -> None:
    frame_reply(stream.send_frame(START_MS, astronaut_jpeg))
    factory.latest.failures[1] = SignalError(
        "NOT_ENOUGH_SAMPLES", SECRET, SECRET_ACTION
    )

    failed = stream.send_frame(FAILED_MS, astronaut_jpeg, ONE_SECOND_S)

    assert failed.types == ["error"]
    assert failed.reply["code"] == "NOT_ENOUGH_SAMPLES"
    assert failed.reply["message"] == NOT_ENOUGH_SAMPLES_MESSAGE


@pytest.mark.parametrize(
    "failure",
    [
        pytest.param(VisionError("MODEL_CORRUPT", SECRET, SECRET_ACTION), id="corrupt"),
        pytest.param(
            VisionError("CAMERA_READ_FAILED", SECRET, SECRET_ACTION), id="camera"
        ),
    ],
)
def test_processing_error_with_an_unlisted_code_replies_with_detection_failed(
    stream: Stream,
    factory: ProcessorFactory,
    astronaut_jpeg: bytes,
    failure: VisionError,
) -> None:
    frame_reply(stream.send_frame(START_MS, astronaut_jpeg))
    factory.latest.failures[1] = failure

    failed = stream.send_frame(FAILED_MS, astronaut_jpeg, ONE_SECOND_S)
    after = stream.send_frame(AFTER_MS, astronaut_jpeg)

    assert_error(failed, "DETECTION_FAILED")
    assert failure.code not in failed.texts[0]
    assert SECRET not in failed.texts[0]
    assert frame_reply(after)["t"] == AFTER_MS


@pytest.mark.parametrize("failure", PROCESSING_ERRORS[:: len(PROCESSING_ERRORS) - 1])
def test_processing_error_moves_the_reference_and_keeps_the_connection_open(
    stream: Stream,
    factory: ProcessorFactory,
    astronaut_jpeg: bytes,
    failure: VisionError | SignalError,
) -> None:
    frame_reply(stream.send_frame(START_MS, astronaut_jpeg))
    factory.latest.failures[1] = failure

    failed = stream.send_frame(FAILED_MS, astronaut_jpeg, ONE_SECOND_S)
    between = stream.send_frame(BETWEEN_MS, astronaut_jpeg)
    after = stream.send_frame(AFTER_MS, astronaut_jpeg)

    assert_error(failed, failure.code)
    assert_error(between, "BAD_TIMESTAMP")
    assert frame_reply(after)["t"] == AFTER_MS
    assert factory.latest.timestamps == [START_MS, FAILED_MS, AFTER_MS]


def test_full_session_at_debug_logs_and_writes_no_frame_data(
    face_model: Path,
    astronaut_jpeg: bytes,
    astronaut_rgb: NDArray[np.uint8],
    blank_jpeg: bytes,
    log_records: list[logging.LogRecord],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    temp_folder = tmp_path / "temp"
    temp_folder.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(temp_folder))
    monkeypatch.setenv("TMPDIR", str(temp_folder))
    writes: list[str] = []
    monkeypatch.setattr(cv2, "imwrite", lambda *args, **kwargs: writes.append("w"))
    monkeypatch.setattr(cv2, "VideoWriter", lambda *args, **kwargs: writes.append("v"))
    before = backend_files()
    clock = FakeClock()
    factory = recording_factory(face_model)
    sent: list[bytes | str] = [
        frame_message(START_MS, astronaut_jpeg),
        frame_message(START_MS + 33, astronaut_jpeg),
        CLIENT_TEXT,
        padded_to(frame_message(CLIENT_MS, astronaut_jpeg), FRAME_CAP_BYTES + 1),
        header(math.nan) + astronaut_jpeg,
        header(CLIENT_MS) + b"\xff\xd8" + bytes(32),
        frame_message(START_MS, astronaut_jpeg),
        frame_message(START_MS + 66, blank_jpeg),
        frame_message(START_MS + 99, solid_jpeg(1921, 16)),
        frame_message(START_MS + 132, astronaut_jpeg),
    ]

    with open_stream(create_app(processor_factory=factory, clock=clock), clock) as s:
        turns = [s.send(message) for message in sent]

    assert backend_files() == before
    assert list(temp_folder.iterdir()) == []
    assert writes == []
    assert [turn.reply["type"] for turn in turns] == [
        "frame",
        "frame",
        "error",
        "error",
        "error",
        "error",
        "error",
        "frame",
        "error",
        "frame",
    ]
    for turn in turns:
        for leak in (CLIENT_TEXT, "4417", "204809", "NaN"):
            assert leak not in turn.texts[-1]
    lines = [rendered(record) for record in log_records]
    assert lines, "No log record was caught for the whole session."
    needles = [n for m in sent if isinstance(m, bytes) for n in byte_needles(m)]
    points = outline_points(turns)
    assert points
    landmarks = landmark_texts(face_model, astronaut_rgb)
    for line in lines:
        assert not [needle for needle in needles if needle in line], line[:300]
        assert leaked_points(line, points) == [], line[:300]
        assert not [value for value in landmarks if value in line], line[:300]
        assert "array(" not in line
        assert CLIENT_TEXT not in line
