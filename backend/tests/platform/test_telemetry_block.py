import plistlib
from pathlib import Path

from tests.platform.sandboxed import (
    ABSENT_SERVICE,
    CONTROL_SERVICE,
    NSURLSESSIOND_SERVICES,
    TRACKED_FRAMES,
)
from tests.platform.support import (
    ON_MACOS,
    assert_sandbox_status_for_this_platform,
    run_probe,
)

FLOW_ARROW = "<->"
LOOPBACK_PREFIXES = ("127.", "::1.", "localhost")
UNBOUND_PREFIX = "*"
NSURLSESSIOND_AGENT = Path("/System/Library/LaunchAgents/com.apple.nsurlsessiond.plist")
KERN_SUCCESS = 0
BOOTSTRAP_NOT_PRIVILEGED = 1100
BOOTSTRAP_UNKNOWN_SERVICE = 1102


def nettop_flows(stdout: str) -> list[str]:
    flows = []
    for line in stdout.splitlines()[1:]:
        fields = line.split(",")
        if len(fields) > 1 and FLOW_ARROW in fields[1]:
            flows.append(fields[1])
    return flows


def remote_endpoint(flow: str) -> str:
    return flow.split(FLOW_ARROW, 1)[1]


def is_remote(endpoint: str) -> bool:
    return not endpoint.startswith((*LOOPBACK_PREFIXES, UNBOUND_PREFIX))


def test_nettop_shows_no_remote_endpoint_after_the_landmarker_runs_and_closes(
    tmp_path: Path,
) -> None:
    probe = run_probe("nettop", tmp_path)

    assert probe.returncode == 0, probe.stderr[-2000:]
    assert_sandbox_status_for_this_platform(probe.record["status"])
    assert probe.record["faces"] == TRACKED_FRAMES
    if ON_MACOS:
        assert probe.record["nettop_returncode"] == 0, probe.record["nettop_stderr"]
        flows = nettop_flows(probe.record["nettop_stdout"])
        server_port, client_port = probe.record["loopback_ports"]
        held_open = [
            flow
            for flow in flows
            if f":{server_port}" in flow and f":{client_port}" in flow
        ]
        assert held_open, f"nettop did not list the open loopback pair: {flows}"
        remote = [flow for flow in flows if is_remote(remote_endpoint(flow))]
        assert remote == []
    else:
        assert "nettop_returncode" not in probe.record


def test_nsurlsessiond_cannot_be_reached_by_mach_lookup_inside_the_sandbox(
    tmp_path: Path,
) -> None:
    probe = run_probe("mach-lookup", tmp_path)

    assert probe.returncode == 0, probe.stderr[-2000:]
    assert_sandbox_status_for_this_platform(probe.record["status"])
    if ON_MACOS:
        registered = plistlib.loads(NSURLSESSIOND_AGENT.read_bytes())["MachServices"]
        assert set(NSURLSESSIOND_SERVICES) <= set(registered)
        assert probe.record["lookups"] == {
            **dict.fromkeys(NSURLSESSIOND_SERVICES, BOOTSTRAP_NOT_PRIVILEGED),
            CONTROL_SERVICE: KERN_SUCCESS,
            ABSENT_SERVICE: BOOTSTRAP_UNKNOWN_SERVICE,
        }
    else:
        assert "lookups" not in probe.record
