import json
import subprocess
import sys
from collections.abc import Mapping
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
PROBE_MODULE = "tests.platform.sandboxed"


@dataclass(frozen=True)
class Probe:
    returncode: int
    stdout: str
    stderr: str
    record: Record


def read_probe_record(record_path: Path, returncode: int, stderr: str) -> Record:
    assert record_path.exists(), (
        f"The {record_path.stem} probe wrote no record. Exit {returncode}."
        f" Stderr tail: {stderr[-2000:]}"
    )
    return json.loads(record_path.read_text(encoding="utf-8"))


def run_probe(
    scenario: str, folder: Path, *args: str, env: Mapping[str, str] | None = None
) -> Probe:
    record_path = folder / f"{scenario}.json"
    done = subprocess.run(
        [
            sys.executable,
            "-m",
            PROBE_MODULE,
            scenario,
            str(record_path),
            *args,
        ],
        cwd=BACKEND,
        env=env,
        capture_output=True,
        text=True,
        timeout=PROBE_TIMEOUT_S,
        check=False,
    )
    return Probe(
        done.returncode,
        done.stdout,
        done.stderr,
        read_probe_record(record_path, done.returncode, done.stderr),
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


def sandbox_notice(status: SandboxStatus, action: str = "") -> str:
    if status.applied:
        return ""
    tail = f" {action}" if action else ""
    return f"{status.code}: {status.reason}{tail}\n"


def after_sandbox_notice(
    err: str, status: SandboxStatus | None = None, action: str = ""
) -> str:
    shown = sandbox_status() if status is None else status
    assert shown is not None, "The session sandbox status was never cached."
    notice = sandbox_notice(shown, action)
    assert err.startswith(notice), (
        f"Stderr should open with the sandbox notice {notice!r}, got {err[:300]!r}"
    )
    return err.removeprefix(notice)
