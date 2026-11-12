import logging
from collections.abc import Iterator
from pathlib import Path

import numpy as np
import pytest

from pulse_frame.stream.app import create_app
from tests.platform.support import Probe
from tests.stream.jpegs import encode_jpeg
from tests.stream.probes import run_stream_probe
from tests.stream.served import ASTRONAUT
from tests.stream.wire import (
    FakeClock,
    ProcessorFactory,
    Stream,
    close_built_processors,
    open_stream,
    recording_factory,
)

BLANK_SIDE_PX = 256


@pytest.fixture(autouse=True)
def built_processors_closed() -> Iterator[None]:
    yield
    close_built_processors()


@pytest.fixture(scope="session")
def astronaut_jpeg() -> bytes:
    return ASTRONAUT.read_bytes()


@pytest.fixture(scope="session")
def blank_jpeg() -> bytes:
    return encode_jpeg(np.zeros((BLANK_SIDE_PX, BLANK_SIDE_PX, 3), dtype=np.uint8))


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def factory(face_model: Path) -> ProcessorFactory:
    return recording_factory(face_model)


@pytest.fixture
def stream(factory: ProcessorFactory, clock: FakeClock) -> Iterator[Stream]:
    app = create_app(processor_factory=factory, clock=clock)
    with open_stream(app, clock) as opened:
        yield opened


@pytest.fixture
def log_records(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> list[logging.LogRecord]:
    caplog.set_level(logging.DEBUG)
    records: list[logging.LogRecord] = []
    original = logging.Logger.handle

    def handle(logger: logging.Logger, record: logging.LogRecord) -> None:
        records.append(record)
        original(logger, record)

    monkeypatch.setattr(logging.Logger, "handle", handle)
    return records


@pytest.fixture(scope="session")
def served(tmp_path_factory: pytest.TempPathFactory) -> Probe:
    return run_stream_probe(
        "serve", tmp_path_factory.mktemp("served"), warnings_as_errors=True
    )
