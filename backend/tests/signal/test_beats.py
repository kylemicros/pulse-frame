import numpy as np
import pytest
from scipy.signal import find_peaks

from pulse_frame.signal.beats import detect_beats
from pulse_frame.signal.errors import SignalError
from tests.frames import SEED
from tests.signal.beat_synthetic import (
    FRAME_MS,
    RESPIRATION_HZ,
    beat_cycles,
    beats_inside,
    frame_times,
    ibi_rmse,
    in_band_noise,
    known_beats,
    late_labels,
    nearest_errors,
    ppg_wave,
)

DURATION_S = 60.0
EDGE_MS = 1_500.0
RATES_BPM = [40.0, 60.0, 72.0, 100.0, 140.0, 180.0]
BEAT_TOLERANCE_MS = 2.0
EXACT_IBI_RMSE_MS = 1.0
LATE_LABEL_IBI_RMSE_MS = 3.0
NOISE_SD = 0.05
NOISY_IBI_RMSE_MS = 20.0
SUB_SAMPLE_TOLERANCE_MS = 0.5
STEADY_BPM = 77.0
PLATEAU_BPM = 60.0
PLATEAU_TOLERANCE_MS = 20.0
JITTER_SEEDS = [0, 1, 2]
PLATEAU_RISE_TOP = 0.9
PLATEAU_RISE_SAMPLES = 13
EVEN_PLATEAU_SAMPLES = 4
PLATEAU_MIDPOINT_MS = 1.0
HEIGHT_SWING = 0.5
TROUGH_BUMP = 0.2
TROUGH_BUMP_WIDTH = 0.05


def interior_truth(beats_ms: np.ndarray, times_ms: np.ndarray) -> np.ndarray:
    return beats_inside(beats_ms, times_ms[0] + EDGE_MS, times_ms[-1] - EDGE_MS)


def found_near(found_ms: np.ndarray, truth_ms: np.ndarray, bpm: float) -> np.ndarray:
    half_ibi_ms = 0.5 * (60_000.0 / bpm - 50.0)
    return beats_inside(found_ms, truth_ms[0] - half_ibi_ms, truth_ms[-1] + half_ibi_ms)


@pytest.mark.parametrize("bpm", RATES_BPM)
def test_every_beat_found_once_within_two_ms_with_exact_frame_labels(
    bpm: float,
) -> None:
    times = frame_times(DURATION_S)
    beats = known_beats(bpm, DURATION_S)
    truth = interior_truth(beats, times)

    found = detect_beats(times, ppg_wave(times, beats))

    errors = nearest_errors(found, truth)
    assert found_near(found, truth, bpm).size == truth.size
    assert np.max(np.abs(errors)) <= BEAT_TOLERANCE_MS
    assert ibi_rmse(errors) <= EXACT_IBI_RMSE_MS


@pytest.mark.parametrize("seed", JITTER_SEEDS)
def test_labels_up_to_one_frame_late_give_a_clearly_larger_ibi_error(
    seed: int,
) -> None:
    rng = np.random.default_rng(SEED + seed)
    times = frame_times(DURATION_S)
    beats = known_beats(72.0, DURATION_S)
    wave = ppg_wave(times, beats)
    truth = interior_truth(beats, times)

    exact = ibi_rmse(nearest_errors(detect_beats(times, wave), truth))
    late = ibi_rmse(nearest_errors(detect_beats(late_labels(rng, times), wave), truth))

    assert exact <= EXACT_IBI_RMSE_MS
    assert late >= LATE_LABEL_IBI_RMSE_MS


@pytest.mark.parametrize("bpm", [72.0, 100.0])
@pytest.mark.parametrize("seed", JITTER_SEEDS)
def test_in_band_noise_still_gives_every_beat_once_with_bounded_ibi_error(
    bpm: float, seed: int
) -> None:
    rng = np.random.default_rng(SEED + seed)
    times = frame_times(DURATION_S)
    beats = known_beats(bpm, DURATION_S)
    noisy = ppg_wave(times, beats) + in_band_noise(rng, times.size, NOISE_SD)
    truth = interior_truth(beats, times)

    found = detect_beats(times, noisy)

    assert found_near(found, truth, bpm).size == truth.size
    assert ibi_rmse(nearest_errors(found, truth)) <= NOISY_IBI_RMSE_MS


def test_beats_between_frames_are_placed_well_inside_one_frame() -> None:
    times = frame_times(DURATION_S)
    beats = known_beats(STEADY_BPM, DURATION_S, swing_ms=0.0)
    truth = interior_truth(beats, times)
    offsets = ((truth - times[0]) % FRAME_MS) / FRAME_MS

    found = detect_beats(times, ppg_wave(times, beats))

    assert np.ptp(offsets) > 0.8
    assert np.max(np.abs(nearest_errors(found, truth))) <= SUB_SAMPLE_TOLERANCE_MS


@pytest.mark.parametrize("ceiling", [0.7, 0.8, 0.9])
def test_flat_topped_peaks_give_one_beat_at_the_middle_of_each_plateau(
    ceiling: float,
) -> None:
    times = frame_times(DURATION_S)
    beats = known_beats(PLATEAU_BPM, DURATION_S, swing_ms=0.0) + 0.37 * FRAME_MS
    clipped = np.minimum(np.cos(2.0 * np.pi * (times - beats[0]) / 1000.0), ceiling)
    truth = interior_truth(beats, times)
    assert np.count_nonzero(clipped == ceiling) >= 3 * truth.size

    found = detect_beats(times, clipped)

    assert np.all(np.isfinite(found))
    assert found_near(found, truth, PLATEAU_BPM).size == truth.size
    assert np.max(np.abs(nearest_errors(found, truth))) <= PLATEAU_TOLERANCE_MS


@pytest.mark.parametrize(
    ("values", "middle"),
    [([0.0, 1.0, 3.0, 3.0, 3.0, 1.0, 0.0], 3), ([0.0, 2.0, 2.0, 2.0, 2.0, 0.0], 2)],
    ids=["odd_plateau", "even_plateau"],
)
def test_scipy_find_peaks_reports_a_plateau_once_at_its_middle_rounded_down(
    values: list[float], middle: int
) -> None:
    peaks, properties = find_peaks(np.array(values), plateau_size=1)

    assert peaks.tolist() == [middle]
    assert properties["left_edges"][0] <= middle <= properties["right_edges"][0]


def test_a_flat_pulse_has_no_beats() -> None:
    times = frame_times(DURATION_S)

    found = detect_beats(times, np.zeros(times.size))

    assert found.size == 0


def test_a_non_finite_pulse_value_raises_bad_values() -> None:
    times = frame_times(DURATION_S)
    pulse = ppg_wave(times, known_beats(72.0, DURATION_S))
    pulse[100] = np.nan

    with pytest.raises(SignalError) as raised:
        detect_beats(times, pulse)

    assert raised.value.code == "BAD_VALUES"


def test_a_pulse_longer_than_its_timestamps_raises_bad_timestamps() -> None:
    times = frame_times(DURATION_S)
    pulse = ppg_wave(times, known_beats(72.0, DURATION_S))

    with pytest.raises(SignalError) as raised:
        detect_beats(times[:-1], pulse)

    assert raised.value.code == "BAD_TIMESTAMPS"


def test_an_even_plateau_gives_its_midpoint_not_the_sample_left_of_middle() -> None:
    period = np.concatenate(
        (
            np.linspace(0.0, PLATEAU_RISE_TOP, PLATEAU_RISE_SAMPLES),
            np.ones(EVEN_PLATEAU_SAMPLES),
            np.linspace(PLATEAU_RISE_TOP, 0.0, PLATEAU_RISE_SAMPLES),
        )
    )
    times = frame_times(DURATION_S)
    pulse = np.resize(period, times.size)
    first_flat = np.flatnonzero(np.diff(np.concatenate(([0.0], pulse == 1.0))) == 1)
    midpoints = times[first_flat] + 0.5 * (EVEN_PLATEAU_SAMPLES - 1) * FRAME_MS
    truth = midpoints[1:-1]

    found = detect_beats(times, pulse)

    assert found.size == midpoints.size
    assert np.max(np.abs(nearest_errors(found, truth))) <= PLATEAU_MIDPOINT_MS


@pytest.mark.parametrize("seed", JITTER_SEEDS)
def test_beats_still_found_once_when_breathing_swings_their_height(seed: int) -> None:
    rng = np.random.default_rng(SEED + seed)
    times = frame_times(DURATION_S)
    beats = known_beats(72.0, DURATION_S)
    seconds = (times - times[0]) / 1000.0
    phase = rng.uniform(0.0, 2.0 * np.pi)
    swing = 1.0 + HEIGHT_SWING * np.sin(2.0 * np.pi * RESPIRATION_HZ * seconds + phase)
    truth = interior_truth(beats, times)

    found = detect_beats(times, swing * ppg_wave(times, beats))

    assert found_near(found, truth, 72.0).size == truth.size


def test_a_small_bump_in_each_trough_is_not_counted_as_a_beat() -> None:
    times = frame_times(DURATION_S)
    beats = known_beats(72.0, DURATION_S)
    since = np.mod(beat_cycles(times, beats), 1.0)
    bump = TROUGH_BUMP * np.exp(-0.5 * ((since - 0.5) / TROUGH_BUMP_WIDTH) ** 2)
    truth = interior_truth(beats, times)

    found = detect_beats(times, ppg_wave(times, beats) + bump)

    assert found_near(found, truth, 72.0).size == truth.size
    assert np.max(np.abs(nearest_errors(found, truth))) <= BEAT_TOLERANCE_MS
