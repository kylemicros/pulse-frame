import os
import subprocess
import sys
from pathlib import Path

import pytest

from pulse_frame.tools.sessions import SANDBOX_UNSUPPORTED_ACTION
from tests.database import (
    UNREACHABLE_URL,
    rows_under,
    stored_session_ids,
    with_database_url,
)
from tests.platform.sandboxed import BACKEND
from tests.platform.support import (
    ON_MACOS,
    PROBE_MODULE,
    PROBE_TIMEOUT_S,
    assert_sandbox_status_for_this_platform,
    missing_symbol_message,
    read_probe_record,
    refused_message,
    run_probe,
    sandbox_lines,
)

LIBRARY_FAILURES = [
    pytest.param(
        "init-fails-with-text",
        refused_message("the test library refused this profile"),
        id="init-fails-with-text",
    ),
    pytest.param(
        "init-missing",
        missing_symbol_message("sandbox_init"),
        id="init-missing",
    ),
]


def test_capture_applies_the_sandbox_before_mediapipe_and_before_the_store(
    store_url: str, tmp_path: Path
) -> None:
    probe = run_probe("capture", tmp_path, env=with_database_url(store_url))

    assert probe.returncode == 0, f"capture exited {probe.returncode}"
    imports = probe.record["mediapipe_imports"]
    assert len(imports) == 1, f"mediapipe import was seen {len(imports)} times"
    assert_sandbox_status_for_this_platform(imports[0])
    statuses = probe.record.get("connect_statuses")
    assert statuses, "capture never connected to the store"
    for status in statuses:
        assert_sandbox_status_for_this_platform(status)
    assert probe.record["camera_opened"] == [0]
    assert probe.stdout.startswith("Session ")
    assert len(stored_session_ids(store_url)) == 1
    if ON_MACOS:
        assert sandbox_lines(probe.stderr) == []


@pytest.mark.parametrize(("mode", "message"), LIBRARY_FAILURES)
def test_capture_stops_with_sandbox_failed_before_mediapipe_the_camera_or_the_store(
    tmp_path: Path, mode: str, message: str
) -> None:
    probe = run_probe(
        "capture-broken", tmp_path, mode, env=with_database_url(UNREACHABLE_URL)
    )

    assert probe.returncode == 1
    assert probe.stdout == ""
    lines = probe.stderr.splitlines()
    assert len(lines) == 1, f"expected one stderr line, got {len(lines)}"
    opening = f"SANDBOX_FAILED: {message} "
    assert lines[0].startswith(opening)
    assert lines[0].removeprefix(opening).strip(), "no action after the sandbox failure"
    assert probe.record["mediapipe_imports"] == 0
    assert probe.record["camera_opened"] == []
    assert probe.record.get("connect_statuses") == []


def test_capture_off_macos_prints_sandbox_unsupported_with_the_store_action(
    store_url: str, tmp_path: Path
) -> None:
    probe = run_probe("capture-unsupported", tmp_path, env=with_database_url(store_url))

    assert probe.returncode == 0, f"capture exited {probe.returncode}"
    unsupported = probe.record["unsupported"]
    assert sandbox_lines(probe.stderr) == [
        f"SANDBOX_UNSUPPORTED: {unsupported['reason']} {SANDBOX_UNSUPPORTED_ACTION}"
    ]
    assert probe.stderr.splitlines()[0] == sandbox_lines(probe.stderr)[0]


def test_capture_into_a_reader_that_closed_early_still_stores_and_exits_cleanly(
    store_url: str, tmp_path: Path
) -> None:
    record = tmp_path / "capture.json"
    reader, writer = os.pipe()
    os.close(reader)

    done = subprocess.run(
        [sys.executable, "-m", PROBE_MODULE, "capture", str(record)],
        cwd=BACKEND,
        env=with_database_url(store_url),
        stdout=writer,
        stderr=subprocess.PIPE,
        text=True,
        timeout=PROBE_TIMEOUT_S,
        check=False,
    )
    os.close(writer)

    read_probe_record(record, done.returncode, done.stderr)
    assert done.returncode == 0, f"capture exited {done.returncode}"
    assert "Traceback" not in done.stderr
    assert "BrokenPipeError" not in done.stderr
    (session_id,) = stored_session_ids(store_url)
    assert rows_under(store_url, session_id)["frame_samples"] > 0
