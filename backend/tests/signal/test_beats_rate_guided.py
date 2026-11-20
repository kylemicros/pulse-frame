import math

import numpy as np
import pytest
from numpy.typing import NDArray
from scipy.signal import find_peaks

from pulse_frame.signal.beats import (
    GUIDE_HALF_WIDTH_HZ,
    HIGHEST_RATE_HZ,
    rate_guided_beats,
    spaced_beats,
)
from pulse_frame.signal.errors import SignalError
from pulse_frame.signal.filters import PASS_HIGH_HZ
from tests.signal.beat_synthetic import (
    BloodVolume,
    asymmetric_blood_volume,
    beat_cycles,
    beats_inside,
    frame_times,
    in_band_noise,
    known_beats,
    nearest_errors,
    period_ms,
    reflected_light_wave,
    systolic_midpoints,
    two_peak_blood_volume,
)
from tests.signal.synthetic import in_band

WINDOW_S = 20.0
EDGE_MS = 1_500.0
STEADY_BPM = 72.0
FIDUCIAL_RATES_BPM = [40.0, 50.0, 60.0, 72.0, 90.0, 120.0, 150.0, 180.0]
MIDPOINT_TOLERANCE_MS = 15.0
STEADY_DEVIATION_MS = 5.0
APEX_CLEARANCE_SHARE = 0.5
HEIGHT_SWING = 0.5
SWING_HZ = 0.25
TROUGH_BUMP = 0.2
TROUGH_BUMP_AT_CYCLE = 0.5
TROUGH_BUMP_WIDTH = 0.05
MIN_DISTANCE_SHARE = 0.6
DIASTOLIC_WAVES = [(0.6, 0.3), (0.8, 0.35)]
RESPIRING_SWING_MS = 50.0
TWO_PEAK_SNR_DB = 10.0
TODAYS_PROMINENCE_SD = 0.5
ARTEFACT_CYCLE = 10
ARTEFACT_AT_CYCLE = -0.09
ARTEFACT_WIDTH_MS = 25.0
ARTEFACT_SNR_DB = 25.0
ARTEFACT_REACH_SHARE = 0.3
TWO_PEAK_RECALL = 0.9
SEED = 20261119
RATE_STEP_HZ = 0.01
SWING_SEEDS = [0, 1, 2]
SPACING_MS = 500.0
RESPACED_NOISE_SEEDS = [11, 39]
RESPACED_DIASTOLIC_WAVE = (0.8, 0.35)
RESPACED_SNR_DB = 0.0


def light_pulse(
    bpm: float, shape: BloodVolume = asymmetric_blood_volume, swing_ms: float = 0.0
) -> tuple[NDArray[np.float64], NDArray[np.float64], NDArray[np.float64]]:
    times = frame_times(WINDOW_S)
    beats = known_beats(bpm, WINDOW_S, swing_ms=swing_ms)
    return times, beats, reflected_light_wave(shape(beat_cycles(times, beats)))


def with_in_band_noise(
    rng: np.random.Generator, pulse: NDArray[np.float64], snr_db: float
) -> NDArray[np.float64]:
    sd = math.sqrt(float(in_band(pulse).var()) / 10.0 ** (snr_db / 10.0))
    return pulse + in_band_noise(rng, pulse.size, sd)


def interior(
    truth_ms: NDArray[np.float64], times_ms: NDArray[np.float64]
) -> NDArray[np.float64]:
    return beats_inside(truth_ms, times_ms[0] + EDGE_MS, times_ms[-1] - EDGE_MS)


def found_around(
    found_ms: NDArray[np.float64], truth_ms: NDArray[np.float64], bpm: float
) -> NDArray[np.float64]:
    half_ms = 0.5 * period_ms(bpm)
    return beats_inside(found_ms, truth_ms[0] - half_ms, truth_ms[-1] + half_ms)


@pytest.mark.parametrize("bpm", FIDUCIAL_RATES_BPM)
def test_each_beat_is_timed_once_at_the_middle_of_the_systolic_upstroke(
    bpm: float,
) -> None:
    times, beats, pulse = light_pulse(bpm)
    midpoints = interior(systolic_midpoints(beats, asymmetric_blood_volume), times)

    found = found_around(rate_guided_beats(times, pulse, bpm / 60.0), midpoints, bpm)

    assert found.size == midpoints.size
    offsets = nearest_errors(found, midpoints)
    assert abs(float(np.median(offsets))) <= MIDPOINT_TOLERANCE_MS
    assert float(np.max(np.abs(offsets - np.median(offsets)))) <= STEADY_DEVIATION_MS
    lead_ms = float(np.median(nearest_errors(beats, midpoints)))
    apex_gap_ms = float(np.median(np.abs(nearest_errors(beats, found))))
    assert apex_gap_ms >= APEX_CLEARANCE_SHARE * lead_ms


@pytest.mark.parametrize(("height", "at"), DIASTOLIC_WAVES)
def test_beats_are_never_closer_than_six_tenths_of_the_spectral_period(
    height: float, at: float
) -> None:
    rng = np.random.default_rng(SEED)
    shape = two_peak_blood_volume(height, at)
    times, beats, pulse = light_pulse(STEADY_BPM, shape, RESPIRING_SWING_MS)
    noisy = with_in_band_noise(rng, pulse, TWO_PEAK_SNR_DB)
    midpoints = interior(systolic_midpoints(beats, shape), times)
    blood_side = -in_band(noisy)
    peaks, _ = find_peaks(
        blood_side, prominence=TODAYS_PROMINENCE_SD * blood_side.std()
    )
    shortest_ms = MIN_DISTANCE_SHARE * period_ms(STEADY_BPM)
    assert float(np.diff(times[peaks]).min()) < shortest_ms

    found = rate_guided_beats(times, noisy, STEADY_BPM / 60.0)

    assert found_around(found, midpoints, STEADY_BPM).size >= TWO_PEAK_RECALL * (
        midpoints.size
    )
    assert float(np.diff(found).min()) >= shortest_ms


def test_a_beat_whose_shape_differs_from_the_others_is_dropped() -> None:
    rng = np.random.default_rng(SEED)
    times = frame_times(WINDOW_S)
    beats = known_beats(STEADY_BPM, WINDOW_S, swing_ms=0.0)
    cycles = beat_cycles(times, beats)
    blood = asymmetric_blood_volume(cycles)
    odd = np.abs(cycles - ARTEFACT_CYCLE) < 0.5
    odd_at_ms = float(np.interp(ARTEFACT_CYCLE + ARTEFACT_AT_CYCLE, cycles, times))
    spike = np.exp(-0.5 * ((times[odd] - odd_at_ms) / ARTEFACT_WIDTH_MS) ** 2)
    blood[odd] = blood.min() + np.ptp(blood) * spike
    pulse = with_in_band_noise(rng, reflected_light_wave(blood), ARTEFACT_SNR_DB)
    midpoints = interior(systolic_midpoints(beats, asymmetric_blood_volume), times)
    assert midpoints[0] < odd_at_ms < midpoints[-1]

    found = rate_guided_beats(times, pulse, STEADY_BPM / 60.0)

    reach_ms = ARTEFACT_REACH_SHARE * period_ms(STEADY_BPM)
    assert found_around(found, midpoints, STEADY_BPM).size == midpoints.size - 1
    assert np.abs(found - odd_at_ms).min() > reach_ms


def test_a_flat_pulse_has_no_beats() -> None:
    times = frame_times(WINDOW_S)

    found = rate_guided_beats(times, np.zeros(times.size), STEADY_BPM / 60.0)

    assert found.size == 0


def test_a_non_finite_pulse_value_raises_bad_values() -> None:
    times, _, pulse = light_pulse(STEADY_BPM)
    pulse[100] = np.nan

    with pytest.raises(SignalError) as raised:
        rate_guided_beats(times, pulse, STEADY_BPM / 60.0)

    assert raised.value.code == "BAD_VALUES"


def test_a_pulse_longer_than_its_timestamps_raises_bad_timestamps() -> None:
    times, _, pulse = light_pulse(STEADY_BPM)

    with pytest.raises(SignalError) as raised:
        rate_guided_beats(times[:-1], pulse, STEADY_BPM / 60.0)

    assert raised.value.code == "BAD_TIMESTAMPS"


@pytest.mark.parametrize(
    "rate_hz", [math.nan, math.inf, 0.0, -1.2], ids=["nan", "inf", "zero", "negative"]
)
def test_a_rate_that_is_not_a_positive_finite_number_raises_bad_rate(
    rate_hz: float,
) -> None:
    times, _, pulse = light_pulse(STEADY_BPM)

    with pytest.raises(SignalError) as raised:
        rate_guided_beats(times, pulse, rate_hz)

    assert raised.value.code == "BAD_RATE"
    assert raised.value.action


def test_a_rate_whose_guide_band_would_pass_the_band_pass_raises_bad_rate() -> None:
    times, _, pulse = light_pulse(STEADY_BPM)
    assert HIGHEST_RATE_HZ + GUIDE_HALF_WIDTH_HZ <= PASS_HIGH_HZ

    with pytest.raises(SignalError) as raised:
        rate_guided_beats(times, pulse, HIGHEST_RATE_HZ + RATE_STEP_HZ)

    assert raised.value.code == "BAD_RATE"
    assert raised.value.action


def test_a_pulse_at_the_highest_rate_gives_each_beat_once() -> None:
    bpm = HIGHEST_RATE_HZ * 60.0
    times, beats, pulse = light_pulse(bpm)
    midpoints = interior(systolic_midpoints(beats, asymmetric_blood_volume), times)

    found = found_around(
        rate_guided_beats(times, pulse, HIGHEST_RATE_HZ), midpoints, bpm
    )

    assert found.size == midpoints.size
    offsets = nearest_errors(found, midpoints)
    assert abs(float(np.median(offsets))) <= MIDPOINT_TOLERANCE_MS


@pytest.mark.parametrize("seed", SWING_SEEDS)
def test_each_beat_is_still_timed_once_when_breathing_swings_its_height(
    seed: int,
) -> None:
    rng = np.random.default_rng(SEED + seed)
    times, beats, pulse = light_pulse(STEADY_BPM)
    seconds = (times - times[0]) / 1000.0
    phase = rng.uniform(0.0, 2.0 * np.pi)
    swing = 1.0 + HEIGHT_SWING * np.sin(2.0 * np.pi * SWING_HZ * seconds + phase)
    midpoints = interior(systolic_midpoints(beats, asymmetric_blood_volume), times)

    found = rate_guided_beats(times, swing * pulse, STEADY_BPM / 60.0)

    near = found_around(found, midpoints, STEADY_BPM)
    assert near.size == midpoints.size
    assert abs(float(np.median(nearest_errors(near, midpoints)))) <= (
        MIDPOINT_TOLERANCE_MS
    )


def test_a_small_bump_in_each_trough_is_not_timed_as_a_beat() -> None:
    times = frame_times(WINDOW_S)
    beats = known_beats(STEADY_BPM, WINDOW_S, swing_ms=0.0)
    cycles = beat_cycles(times, beats)
    since = np.mod(cycles, 1.0)
    bump = TROUGH_BUMP * np.exp(
        -0.5 * ((since - TROUGH_BUMP_AT_CYCLE) / TROUGH_BUMP_WIDTH) ** 2
    )
    pulse = reflected_light_wave(asymmetric_blood_volume(cycles) + bump)
    midpoints = interior(systolic_midpoints(beats, asymmetric_blood_volume), times)

    found = rate_guided_beats(times, pulse, STEADY_BPM / 60.0)

    near = found_around(found, midpoints, STEADY_BPM)
    assert near.size == midpoints.size
    assert abs(float(np.median(nearest_errors(near, midpoints)))) <= (
        MIDPOINT_TOLERANCE_MS
    )


def test_spacing_keeps_the_earlier_of_two_close_beats_and_every_spaced_one() -> None:
    times_ms = np.array([1_300.0, 0.0, 650.0, 100.0, 600.0])

    kept = spaced_beats(times_ms, SPACING_MS)

    assert kept.tolist() == [0.0, 600.0, 1_300.0]
    assert float(np.diff(kept).min()) >= SPACING_MS


@pytest.mark.parametrize("noise_seed", RESPACED_NOISE_SEEDS)
def test_two_candidates_closer_than_the_spacing_never_both_come_out(
    noise_seed: int,
) -> None:
    rng = np.random.default_rng(noise_seed)
    shape = two_peak_blood_volume(*RESPACED_DIASTOLIC_WAVE)
    times, _, pulse = light_pulse(STEADY_BPM, shape, RESPIRING_SWING_MS)
    noisy = with_in_band_noise(rng, pulse, RESPACED_SNR_DB)

    found = rate_guided_beats(times, noisy, STEADY_BPM / 60.0)

    assert found.size > 1
    assert float(np.diff(found).min()) >= MIN_DISTANCE_SHARE * period_ms(STEADY_BPM)
