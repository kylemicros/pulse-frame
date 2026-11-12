import json
import subprocess
import sys
from pathlib import Path

from tests.platform.sandboxed import BACKEND
from tests.platform.support import Probe

PROBE_TIMEOUT_S = 40
CODE_PREFIXES = ("SANDBOX_", "MODEL_")


def run_stream_probe(
    scenario: str, folder: Path, *args: str, warnings_as_errors: bool = False
) -> Probe:
    record_path = folder / f"{scenario}.json"
    flags = ["-W", "error"] if warnings_as_errors else []
    done = subprocess.run(
        [
            sys.executable,
            *flags,
            "-m",
            "tests.stream.served",
            scenario,
            str(record_path),
            *args,
        ],
        cwd=BACKEND,
        capture_output=True,
        text=True,
        timeout=PROBE_TIMEOUT_S,
        check=False,
    )
    assert record_path.exists(), (
        f"The {scenario} probe wrote no record. Exit {done.returncode}."
        f" Stderr tail: {done.stderr[-3000:]}"
    )
    return Probe(
        done.returncode, done.stdout, done.stderr, json.loads(record_path.read_text())
    )


def coded_lines(stderr: str) -> list[str]:
    return [line for line in stderr.splitlines() if line.startswith(CODE_PREFIXES)]


def notice_lines(status: dict[str, object]) -> list[str]:
    return [] if status["applied"] else [f"{status['code']}: {status['reason']}"]


def labels(events: list[list[object]]) -> list[str]:
    return [str(event[0]) for event in events]


def first_event(events: list[list[object]], label: str) -> int:
    names = labels(events)
    assert label in names, f"{label} never happened; events: {names}"
    return names.index(label)


def sandbox_event_status(events: list[list[object]]) -> dict[str, object]:
    status = events[first_event(events, "sandbox")][1]
    assert isinstance(status, dict), status
    return status
