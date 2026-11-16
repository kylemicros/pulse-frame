from pathlib import Path

import pytest

from tests.database import UNREACHABLE_URL, URL_VARIABLE, with_database_url
from tests.platform.support import (
    ON_MACOS,
    assert_sandbox_status_for_this_platform,
    missing_symbol_message,
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


def assert_line_carries_an_action_for_this_command(line: str, opening: str) -> None:
    assert line.startswith(f"{opening} "), (
        f"expected {opening!r} followed by an action, got {line!r}"
    )
    assert line.removeprefix(f"{opening} ").strip(), f"no action after {opening!r}"
    assert "mediapipe" not in line.lower(), f"MediaPipe named for sessions: {line!r}"


def test_sessions_applies_the_sandbox_before_connecting_to_the_store(
    store_url: str, tmp_path: Path
) -> None:
    probe = run_probe("sessions", tmp_path, env=with_database_url(store_url))

    assert probe.returncode == 0, f"sessions list exited {probe.returncode}"
    statuses = probe.record.get("connect_statuses")
    assert statuses, "sessions list never connected to the store"
    for status in statuses:
        assert_sandbox_status_for_this_platform(status)
    lines = sandbox_lines(probe.stderr)
    if ON_MACOS:
        assert lines == []
    else:
        assert len(lines) == 1, lines
        assert_line_carries_an_action_for_this_command(
            lines[0], f"SANDBOX_UNSUPPORTED: {statuses[0]['reason']}"
        )


def test_sessions_off_macos_prints_sandbox_unsupported_with_an_action_and_carries_on(
    store_url: str, tmp_path: Path
) -> None:
    probe = run_probe(
        "sessions-unsupported", tmp_path, env=with_database_url(store_url)
    )

    assert probe.returncode == 0, f"sessions list exited {probe.returncode}"
    unsupported = probe.record["unsupported"]
    assert unsupported["code"] == "SANDBOX_UNSUPPORTED"
    lines = sandbox_lines(probe.stderr)
    assert len(lines) == 1, lines
    assert probe.stderr.splitlines()[0] == lines[0]
    assert_line_carries_an_action_for_this_command(
        lines[0], f"SANDBOX_UNSUPPORTED: {unsupported['reason']}"
    )
    statuses = probe.record.get("connect_statuses")
    assert statuses, "sessions list never connected to the store"
    assert statuses == [unsupported] * len(statuses)


def test_sessions_unsupported_action_points_the_url_at_this_machine_without_claiming_it(
    store_url: str, tmp_path: Path
) -> None:
    probe = run_probe(
        "sessions-unsupported", tmp_path, env=with_database_url(store_url)
    )

    lines = sandbox_lines(probe.stderr)
    assert len(lines) == 1, lines
    action = lines[0].removeprefix(
        f"SANDBOX_UNSUPPORTED: {probe.record['unsupported']['reason']} "
    )
    assert "since the store is on this machine" not in action
    assert URL_VARIABLE in action
    assert "127.0.0.1" in action


@pytest.mark.parametrize(("mode", "message"), LIBRARY_FAILURES)
def test_sessions_stops_with_sandbox_failed_before_connecting(
    tmp_path: Path, mode: str, message: str
) -> None:
    probe = run_probe(
        "sessions-broken", tmp_path, mode, env=with_database_url(UNREACHABLE_URL)
    )

    assert probe.record.get("connect_statuses") == []
    assert probe.returncode == 1
    assert probe.stdout == ""
    assert probe.stderr.endswith("\n")
    lines = probe.stderr.splitlines()
    assert len(lines) == 1, lines
    assert_line_carries_an_action_for_this_command(
        lines[0], f"SANDBOX_FAILED: {message}"
    )
