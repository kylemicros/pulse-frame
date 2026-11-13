import logging
import tomllib
from pathlib import Path

import pytest
from opentelemetry import _logs, metrics, trace  # noqa: PLC2701
from opentelemetry.util.types import Attributes
from starlette.testclient import TestClient

from pulse_frame.stream.app import create_app
from tests.platform.sandboxed import BACKEND
from tests.stream.wire import (
    FakeClock,
    ProcessorFactory,
    frame_reply,
    open_stream,
)

LOCK_FILE = BACKEND / "uv.lock"
START_MS = 1000
LOCAL_COLLECTOR = "http://127.0.0.1:4318"
DOCS_PATH = "/docs"
NOT_FOUND = 404
FORBIDDEN_PACKAGES = ("opentelemetry-sdk",)
FORBIDDEN_PREFIXES = ("opentelemetry-exporter",)
AUTO_CONFIGURE = [
    pytest.param(None, id="environment-silent"),
    pytest.param("true", id="environment-auto-configure"),
]


class RecordingTracerProvider(trace.TracerProvider):
    def __init__(self, asked: list[str]) -> None:
        self.asked = asked

    def get_tracer(self, *args: object, **kwargs: object) -> trace.Tracer:
        self.asked.append("tracer")
        return trace.NoOpTracer()


class RecordingMeterProvider(metrics.MeterProvider):
    def __init__(self, asked: list[str]) -> None:
        self.asked = asked

    def get_meter(self, name: str, *args: object, **kwargs: object) -> metrics.Meter:
        self.asked.append("meter")
        return metrics.NoOpMeter(name)


class RecordingLoggerProvider(_logs.LoggerProvider):
    def __init__(self, asked: list[str]) -> None:
        self.asked = asked

    def get_logger(
        self,
        name: str,
        version: str | None = None,
        schema_url: str | None = None,
        attributes: Attributes = None,
    ) -> _logs.Logger:
        self.asked.append("logger")
        return _logs.NoOpLogger(name)


@pytest.fixture
def telemetry_asked(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    asked: list[str] = []
    tracers = RecordingTracerProvider(asked)
    meters = RecordingMeterProvider(asked)
    loggers = RecordingLoggerProvider(asked)

    def get_logger(name: str, *args: object, **kwargs: object) -> _logs.Logger:
        return loggers.get_logger(name)

    monkeypatch.setattr(trace, "get_tracer_provider", lambda: tracers)
    monkeypatch.setattr(metrics, "get_meter_provider", lambda: meters)
    monkeypatch.setattr(_logs, "get_logger_provider", lambda: loggers)
    monkeypatch.setattr(_logs, "get_logger", get_logger)
    return asked


def locked_package_names(lock_file: Path) -> list[str]:
    lock = tomllib.loads(lock_file.read_text(encoding="utf-8"))
    return [str(package["name"]) for package in lock["package"]]


@pytest.mark.parametrize("auto_configure", AUTO_CONFIGURE)
def test_fastapi_telemetry_stays_off_even_with_providers_and_environment_set(
    auto_configure: str | None,
    factory: ProcessorFactory,
    clock: FakeClock,
    astronaut_jpeg: bytes,
    telemetry_asked: list[str],
    log_records: list[logging.LogRecord],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OTEL_SDK_DISABLED", raising=False)
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", LOCAL_COLLECTOR)
    if auto_configure is None:
        monkeypatch.delenv("FASTAPI_OTEL_AUTO_CONFIGURE", raising=False)
    else:
        monkeypatch.setenv("FASTAPI_OTEL_AUTO_CONFIGURE", auto_configure)
    app = create_app(processor_factory=factory, clock=clock)

    with TestClient(app) as client:
        not_found = client.get(DOCS_PATH).status_code
    with open_stream(app, clock) as stream:
        reply = frame_reply(stream.send_frame(START_MS, astronaut_jpeg))

    assert not_found == NOT_FOUND
    assert reply["face"] is True
    assert telemetry_asked == []
    assert [r.getMessage() for r in log_records if r.name.startswith("fastapi")] == []


def test_lock_holds_no_opentelemetry_sdk_or_exporter() -> None:
    names = locked_package_names(LOCK_FILE)

    assert "opentelemetry-api" in names
    assert [name for name in names if name in FORBIDDEN_PACKAGES] == []
    assert [name for name in names if name.startswith(FORBIDDEN_PREFIXES)] == []
