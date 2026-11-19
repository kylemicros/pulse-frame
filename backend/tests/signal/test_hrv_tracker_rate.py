from collections.abc import Callable

import numpy as np
import pytest
from numpy.typing import NDArray

from pulse_frame.signal.hrv import HrvTracker
from tests.frames import SEED
from tests.signal.beat_synthetic import beats_inside, nearest_errors
from tests.signal.face_synthetic import realistic_face
from tests.signal.hrv_tracking import TRUTH_MARGIN_MS, accepted, beat_times, tracked
from tests.signal.synthetic import in_band, red_noise_recording, wave_recording

NULL_S = 120.0
NULL_SEEDS = [0, 1, 2, 3, 4]
MOSTLY_SHARED = 0.6
FAST_BPM = 100.0
CLEAN_SNR_DB = 60.0
WIDE_SDNN_MS = 93.0
FAST_S = 80.0
FAST_SEEDS = [0, 1, 2, 3]
FAST_RECALL = 0.9
BEAT_REACH_MS = 150.0
HALF_TONE_BPM = 75.0
HALF_SHARES = [0.7, 0.8, 0.9]
HALF_NOISE_SD = 0.3
HALF_SEEDS = [0, 1, 2]
HALF_S = 90.0
LONGEST_PERIOD_SHARE = 1.5


@pytest.mark.parametrize("seed", NULL_SEEDS)
def test_red_noise_shared_between_regions_without_a_pulse_accepts_no_interval(
    seed: int,
) -> None:
    recording = red_noise_recording(None, SEED + seed, duration_s=NULL_S)

    kept = accepted(tracked(recording).intervals())

    assert kept == []


@pytest.mark.parametrize("seed", FAST_SEEDS)
def test_a_clean_fast_pulse_with_a_varying_dicrotic_wave_keeps_most_beats(
    seed: int,
) -> None:
    face = realistic_face(
        FAST_BPM, CLEAN_SNR_DB, SEED + seed, FAST_S, sdnn_ms=WIDE_SDNN_MS
    )
    first_ms = float(face.recording.timestamps_ms[0]) + TRUTH_MARGIN_MS
    last_ms = float(face.recording.timestamps_ms[-1]) - TRUTH_MARGIN_MS
    truth = beats_inside(face.beats_ms, first_ms, last_ms)

    found = beat_times(tracked(face.recording).intervals())

    reached = np.abs(nearest_errors(found, truth)) <= BEAT_REACH_MS
    assert float(np.mean(reached)) >= FAST_RECALL


def half_tone_wave(
    share: float, seed: int
) -> Callable[[NDArray[np.float64]], NDArray[np.float64]]:
    rng = np.random.default_rng(SEED + seed)
    phase = rng.uniform(0.0, 2.0 * np.pi)
    rate_hz = HALF_TONE_BPM / 60.0

    def wave(seconds: NDArray[np.float64]) -> NDArray[np.float64]:
        noise = in_band(rng.standard_normal(seconds.size))
        return (
            np.sin(2.0 * np.pi * rate_hz * seconds)
            + share * np.sin(np.pi * rate_hz * seconds + phase)
            + HALF_NOISE_SD * noise / noise.std()
        )

    return wave


@pytest.mark.parametrize("seed", HALF_SEEDS)
@pytest.mark.parametrize("share", HALF_SHARES)
def test_a_strong_half_rate_tone_never_gives_an_accepted_half_rate_interval(
    share: float, seed: int
) -> None:
    recording = wave_recording(half_tone_wave(share, seed), SEED + seed, HALF_S)

    kept = accepted(tracked(recording).intervals())

    longest_ms = LONGEST_PERIOD_SHARE * 60_000.0 / HALF_TONE_BPM
    assert [i.ibi_ms for i in kept if i.ibi_ms > longest_ms] == []


@pytest.mark.parametrize("seed", NULL_SEEDS)
def test_red_noise_mostly_shared_between_regions_never_gives_a_reading(
    seed: int,
) -> None:
    recording = red_noise_recording(
        None, SEED + seed, duration_s=NULL_S, shared_share=MOSTLY_SHARED
    )
    tracker = HrvTracker()
    shown = []

    for timestamp_ms, regions in recording.samples():
        tracker.add(timestamp_ms, regions)
        reading = tracker.reading()
        if reading.rmssd_ms is not None or reading.sdnn_ms is not None:
            shown.append(timestamp_ms)

    assert shown == []
