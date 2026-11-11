import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from pulse_frame.platform.sandbox import SandboxStatus, sandbox_status
from tests.platform.sandboxed import (
    BACKEND,
    FAILED_SANDBOX_INIT,
    Record,
    symbol_not_found,
)

ON_MACOS = sys.platform == "darwin"
PROBE_TIMEOUT_S = 40


@dataclass(frozen=True)
class Probe:
    returncode: int
    stdout: str
    stderr: str
    record: Record


def run_probe(scenario: str, folder: Path, *args: str) -> Probe:
    record_path = folder / f"{scenario}.json"
    done = subprocess.run(
        [
            sys.executable,
            "-m",
            "tests.platform.sandboxed",
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
        f" Stderr tail: {done.stderr[-2000:]}"
    )
    return Probe(
        done.returncode, done.stdout, done.stderr, json.loads(record_path.read_text())
    )


def assert_sandbox_status_for_this_platform(status: object) -> None:
    assert isinstance(status, dict), f"No sandbox status was recorded: {status!r}"
    assert status["reason"]
    if ON_MACOS:
        assert status["applied"] is True
        assert status["code"] == "SANDBOX_APPLIED"
    else:
        assert status["applied"] is False
        assert status["code"] == "SANDBOX_UNSUPPORTED"
        assert "macOS" in status["reason"]


def refused_message(detail: str) -> str:
    return (
        "macOS refused the loopback-only network sandbox"
        f" (sandbox_init returned {FAILED_SANDBOX_INIT}: {detail})."
    )


def missing_symbol_message(name: str) -> str:
    return f"macOS no longer provides {name} ({symbol_not_found(name)})."


def sandbox_lines(stderr: str) -> list[str]:
    return [line for line in stderr.splitlines() if line.startswith("SANDBOX_")]


def sandbox_notice(status: SandboxStatus) -> str:
    return "" if status.applied else f"{status.code}: {status.reason}\n"


def after_sandbox_notice(err: str, status: SandboxStatus | None = None) -> str:
    shown = sandbox_status() if status is None else status
    assert shown is not None, "The session sandbox status was never cached."
    notice = sandbox_notice(shown)
    assert err.startswith(notice), (
        f"Stderr should open with the sandbox notice {notice!r}, got {err[:300]!r}"
    )
    return err.removeprefix(notice)
