from pathlib import Path

import pytest

from pulse_frame.platform.sandbox import FAILED_ACTION
from pulse_frame.vision import model
from pulse_frame.vision.errors import VisionError
from tests.platform.support import (
    Probe,
    assert_sandbox_status_for_this_platform,
    missing_symbol_message,
    refused_message,
    sandbox_lines,
)
from tests.stream.probes import (
    coded_lines,
    first_event,
    labels,
    notice_lines,
    run_stream_probe,
    sandbox_event_status,
)
from tests.stream.served import APP_MODULE, PROCESSOR_MODULE, WATCHED_IMPORTS

SANDBOX_FAILURES = [
    pytest.param(
        "init-fails-with-text",
        refused_message("the test library refused this profile"),
        id="init-fails-with-text",
    ),
    pytest.param(
        "init-missing", missing_symbol_message("sandbox_init"), id="init-missing"
    ),
]
NOTHING_IMPORTED = dict.fromkeys(WATCHED_IMPORTS, False)


def missing_model_line(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> str:
    monkeypatch.setattr(model, "model_path", lambda: tmp_path / "absent.task")
    with pytest.raises(VisionError) as caught:
        model.ensure_model(download=False)
    error = caught.value
    assert error.code == "MODEL_MISSING"
    return f"{error.code}: {error.message} {error.action}"


def test_server_applies_the_sandbox_before_mediapipe_and_the_app_are_imported(
    served: Probe,
) -> None:
    events = served.record["events"]

    sandbox = first_event(events, "sandbox")
    mediapipe = first_event(events, "import mediapipe")
    assert sandbox < first_event(events, "import pulse_frame.vision.landmarks")
    assert sandbox < first_event(events, f"import {PROCESSOR_MODULE}")
    assert sandbox < first_event(events, f"import {APP_MODULE}")
    assert sandbox < mediapipe
    assert_sandbox_status_for_this_platform(sandbox_event_status(events))
    assert_sandbox_status_for_this_platform(events[mediapipe][1])


def test_server_has_the_sandbox_applied_before_the_first_landmarker_is_created(
    served: Probe,
) -> None:
    events = served.record["events"]

    landmarker = first_event(events, "landmarker")

    assert first_event(events, "sandbox") < landmarker
    assert_sandbox_status_for_this_platform(events[landmarker][1])
    assert served.record["replies"][-1]["face"] is True


def test_server_checks_the_model_without_download_before_importing_the_app(
    served: Probe,
) -> None:
    events = served.record["events"]

    model_check = first_event(events, "ensure_model")

    assert events[model_check][1] is False
    assert first_event(events, "sandbox") < model_check
    assert model_check < first_event(events, f"import {APP_MODULE}")
    assert model_check < first_event(events, f"import {PROCESSOR_MODULE}")
    assert model_check < first_event(events, "bind")


def test_server_prints_its_sandbox_notice_only_off_macos(served: Probe) -> None:
    status = sandbox_event_status(served.record["events"])

    assert sandbox_lines(served.stderr) == notice_lines(status)


def test_server_off_macos_prints_sandbox_unsupported_once_and_carries_on(
    tmp_path: Path,
) -> None:
    probe = run_stream_probe("serve-unsupported", tmp_path)

    assert probe.returncode == 0, probe.stderr[-3000:]
    unsupported = probe.record["unsupported"]
    assert unsupported["code"] == "SANDBOX_UNSUPPORTED"
    assert sandbox_lines(probe.stderr) == [
        f"SANDBOX_UNSUPPORTED: {unsupported['reason']}"
    ]
    assert probe.record["replies"][-1]["type"] == "frame"
    assert probe.record["replies"][-1]["face"] is True
    assert "client_error" not in probe.record


@pytest.mark.parametrize(("mode", "message"), SANDBOX_FAILURES)
def test_sandbox_failure_prints_sandbox_failed_exits_1_and_binds_nothing(
    tmp_path: Path, mode: str, message: str
) -> None:
    probe = run_stream_probe("broken-sandbox", tmp_path, mode)

    assert probe.returncode == 1
    assert probe.stderr == f"SANDBOX_FAILED: {message} {FAILED_ACTION}\n"
    assert probe.stdout == ""
    assert "bind" not in labels(probe.record["events"])
    assert "ensure_model" not in labels(probe.record["events"])
    assert probe.record["modules"] == NOTHING_IMPORTED


def test_missing_model_prints_model_missing_exits_1_and_binds_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    expected = missing_model_line(monkeypatch, tmp_path)

    probe = run_stream_probe("model-missing", tmp_path)

    assert probe.returncode == 1
    status = sandbox_event_status(probe.record["events"])
    assert coded_lines(probe.stderr) == [*notice_lines(status), expected]
    assert probe.stderr.splitlines()[-1] == expected
    assert probe.stdout == ""
    assert "bind" not in labels(probe.record["events"])
    assert probe.record["modules"][APP_MODULE] is False
    assert probe.record["modules"][PROCESSOR_MODULE] is False
    assert probe.record["modules"]["mediapipe"] is False


def test_importing_the_stream_package_loads_neither_app_nor_processor_nor_mediapipe(
    tmp_path: Path,
) -> None:
    probe = run_stream_probe("import-package", tmp_path)

    assert probe.returncode == 0, probe.stderr[-3000:]
    assert probe.record["modules"] == NOTHING_IMPORTED
