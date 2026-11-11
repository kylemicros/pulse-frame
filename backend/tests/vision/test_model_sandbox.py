from pathlib import Path

from pulse_frame.vision.model import MODEL_SHA256
from tests.platform.support import run_probe


def test_model_command_verifies_the_model_without_network_or_applying_the_sandbox(
    tmp_path: Path,
) -> None:
    probe = run_probe("model-main", tmp_path)

    assert probe.returncode == 0, probe.stderr[-2000:]
    assert f"sha256={MODEL_SHA256}" in probe.stdout
    assert probe.record["network_events"] == []
    assert probe.record["status"] is None
