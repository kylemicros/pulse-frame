import time

import numpy as np
import pytest

from pulse_frame.signal.live import LiveHrv
from pulse_frame.signal.summary import SAMPLE_HOLE_MS
from pulse_frame.stream.replies import hrv_message
from tests.frames import SEED
from tests.signal.face_synthetic import realistic_face
from tests.signal.synthetic import Recording

RUN_S = 150.0
READING_INTERVAL_MS = 1_000
HRV_SHARE_OF_BUDGET = 0.5
CASES = [
    pytest.param(72.0, 10.0, id="72_bpm_at_10_db"),
    pytest.param(72.0, 5.0, id="72_bpm_at_5_db"),
    pytest.param(50.0, 5.0, id="50_bpm_at_5_db"),
]


def per_frame_ms(recording: Recording) -> list[float]:
    live = LiveHrv()
    costs: list[float] = []
    last_reading_ms: int | None = None
    for timestamp, colours in recording.samples():
        t_ms = round(timestamp)
        due = last_reading_ms is None or t_ms - last_reading_ms >= READING_INTERVAL_MS
        started = time.thread_time()
        live.add(t_ms, colours, moving=False)
        if due:
            hrv_message(t_ms, live.summary(), live.no_reading())
        costs.append((time.thread_time() - started) * 1_000.0)
        if due:
            last_reading_ms = t_ms
    return costs


@pytest.mark.parametrize(("bpm", "snr_db"), CASES)
def test_live_hrv_keeps_every_frame_well_inside_the_sample_hole_budget(
    bpm: float, snr_db: float
) -> None:
    face = realistic_face(bpm, snr_db, SEED, RUN_S)

    costs = per_frame_ms(face.recording)

    worst = max(costs)
    p99 = float(np.percentile(costs, 99))
    shown = f"{bpm:g} BPM at {snr_db:g} dB: p99 {p99:.2f} ms, max {worst:.2f} ms"
    print(shown)
    assert worst < HRV_SHARE_OF_BUDGET * SAMPLE_HOLE_MS, shown
