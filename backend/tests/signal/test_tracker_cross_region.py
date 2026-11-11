import numpy as np
import pytest
from numpy.typing import NDArray

from pulse_frame.signal.tracker import PulseTracker, Reading
from tests.signal.synthetic import (
    RED_HARMONIC_RATIOS,
    Recording,
    WaveBuilder,
    red_noise_recording,
    tone,
    wave_recording,
    webcam_recording,
)
from tests.signal.tracking import (
    assert_ok_within_one_bpm,
    first_settled_reading,
    ok_readings,
    reading_trace,
    readings_by_second,
)

SEED = 20261111
SHARED_BPM = 72.0
SETTLED_S = 20.0
TRACE_S = 25.4
REGRESSION_TRACE_S = 30.4
REGRESSION_NOISE_SEEDS = range(66_000, 66_008)
REGRESSION_PULSE_SEEDS = range(66_100, 66_110)
REGRESSION_PULSE_BPM = 80.0
REGRESSION_DEPTHS = [0.0025, 0.005]
HUMP_LOW_BPM = 45.0
HUMP_HIGH_BPM = 50.0
SHARE_RATES_BPM = [45.0, 55.0, 65.0, 75.0, 85.0, 95.0, 110.0, 130.0, 160.0]
SHARE_SEEDS_PER_RATE = 30
SHARE_SEED_BASE = 55_000
SHARE_DEPTH = 0.005
SHOWN_SHARE_LOW = 0.20
SHOWN_SHARE_HIGH = 0.49
WRONG_SHARE_HIGH = 0.009
WRONG_BY_BPM = 5.0
NOISE_SEEDS = range(88_000, 88_180)
NOISE_SHOWN_SHARE_HIGH = 0.017
LOCAL_TONE_AMPLITUDE = 3.0
LOCAL_TONES_BPM = (100.0, 118.0, 136.0)
RIVAL_BPM = 100.0
CLOSE_RIVAL_AMPLITUDE = 0.714
FAR_RIVAL_AMPLITUDE = 0.34
HALF_S = 10.0
FIRST_HALF_BPM = 70.0
SPLIT_SECOND_HALF_BPM = 80.0
SPLIT_SECOND_HALF_AMPLITUDE = 0.6
CLOSE_SECOND_HALF_BPM = 73.0
HARMONIC_TRAP_RATES_BPM = [42.0, 45.0, 60.0, 75.0, 90.0]
STRONG_HARMONIC_RATIOS = [0.8, 1.0, 1.3]
READABLE_HARMONIC_RATIO = 0.6
READABLE_SHOWN_SHARE = 0.9
EQUAL_HARMONIC_RATIO = 1.0
BELOW_BAND_RATES_BPM = [30.0, 36.0, 39.0]
BELOW_BAND_HARMONIC_RATIOS = [0.25, 0.6, 0.8, 1.0]
HARMONIC_SEEDS_PER_CASE = 3
WHITE_HARMONIC_SEED_BASE = 71_000
BELOW_BAND_SEED_BASE = 72_000
RED_HARMONIC_SEED_BASE = 73_000
RED_HARMONIC_SEEDS_PER_RATE = 20
RED_DOUBLED_SHARE_HIGH = 0.03
WHOLE_SECONDS = range(20, 26)
DOUBLE_WITHIN_BPM = 5.0
TRUE_WITHIN_BPM = 2.0
LOUD_TONE_AMPLITUDE = 40.0


def pure_pulse(bpm: float) -> WaveBuilder:
    return lambda seconds: tone(seconds, bpm, 1.0)


def silent(seconds: NDArray[np.float64]) -> NDArray[np.float64]:
    return np.zeros_like(seconds)


def local_tone(bpm: float) -> WaveBuilder:
    return lambda seconds: tone(seconds, bpm, LOCAL_TONE_AMPLITUDE)


def loud_tone(bpm: float) -> WaveBuilder:
    return lambda seconds: tone(seconds, bpm, LOUD_TONE_AMPLITUDE)


def two_tones(rival_amplitude: float) -> WaveBuilder:
    return lambda seconds: (
        tone(seconds, SHARED_BPM, 1.0) + tone(seconds, RIVAL_BPM, rival_amplitude)
    )


def rate_change_at_half(second_bpm: float, second_amplitude: float) -> WaveBuilder:
    def build(seconds: NDArray[np.float64]) -> NDArray[np.float64]:
        before = np.minimum(seconds, HALF_S)
        after = np.maximum(seconds - HALF_S, 0.0)
        angle = 2.0 * np.pi * (FIRST_HALF_BPM * before + second_bpm * after) / 60.0
        amplitude = np.where(seconds < HALF_S, 1.0, second_amplitude)
        return amplitude * np.sin(angle)

    return build


def ok_bpms(trace: list[tuple[float, Reading]]) -> list[float]:
    return [reading.bpm for reading in ok_readings(trace) if reading.bpm is not None]


@pytest.mark.parametrize("seed", REGRESSION_NOISE_SEEDS)
def test_red_noise_without_a_pulse_never_reads_ok_in_the_regression_case(
    seed: int,
) -> None:
    recording = red_noise_recording(None, seed=seed, duration_s=REGRESSION_TRACE_S)

    trace = reading_trace(PulseTracker(), recording)

    assert [reading for _, reading in trace if reading.state != "acquiring"]
    assert ok_readings(trace) == []


@pytest.mark.parametrize("depth", REGRESSION_DEPTHS)
def test_eighty_bpm_pulse_in_red_noise_never_reads_45_to_50_bpm(depth: float) -> None:
    shown = []
    for seed in REGRESSION_PULSE_SEEDS:
        recording = red_noise_recording(
            REGRESSION_PULSE_BPM, seed=seed, depth=depth, duration_s=REGRESSION_TRACE_S
        )
        shown.extend(ok_bpms(reading_trace(PulseTracker(), recording)))

    assert [bpm for bpm in shown if HUMP_LOW_BPM <= bpm <= HUMP_HIGH_BPM] == []
    assert all(abs(bpm - REGRESSION_PULSE_BPM) <= WRONG_BY_BPM for bpm in shown)


def test_half_percent_pulse_in_red_noise_shows_a_share_and_almost_none_wrong() -> None:
    readings: list[tuple[float, Reading]] = []
    for true_bpm in SHARE_RATES_BPM:
        for index in range(SHARE_SEEDS_PER_RATE):
            recording = red_noise_recording(
                true_bpm,
                seed=SHARE_SEED_BASE + 1000 * int(true_bpm) + index,
                depth=SHARE_DEPTH,
                harmonic_ratio=RED_HARMONIC_RATIOS[index % 2],
            )
            readings.append((true_bpm, first_settled_reading(recording)))

    assert all(reading.state != "acquiring" for _, reading in readings)
    shown = [(true_bpm, r) for true_bpm, r in readings if r.state == "ok"]
    wrong = [
        (true_bpm, r)
        for true_bpm, r in shown
        if r.bpm is None or abs(r.bpm - true_bpm) > WRONG_BY_BPM
    ]
    shown_share = len(shown) / len(readings)
    assert SHOWN_SHARE_LOW <= shown_share <= SHOWN_SHARE_HIGH
    assert len(wrong) <= WRONG_SHARE_HIGH * len(shown)


def test_red_noise_without_a_pulse_shows_at_most_a_small_share() -> None:
    readings = [
        first_settled_reading(red_noise_recording(None, seed=seed))
        for seed in NOISE_SEEDS
    ]

    assert all(reading.state != "acquiring" for reading in readings)
    shown = [reading for reading in readings if reading.state == "ok"]
    assert len(shown) <= NOISE_SHOWN_SHARE_HIGH * len(readings)


def test_tone_local_to_every_region_is_never_ok_though_a_pulse_is_shared() -> None:
    recording = wave_recording(
        pure_pulse(SHARED_BPM),
        seed=SEED + 300,
        duration_s=TRACE_S,
        local_waves_for=[local_tone(bpm) for bpm in LOCAL_TONES_BPM],
    )

    trace = reading_trace(PulseTracker(), recording)

    settled = [reading for elapsed_s, reading in trace if elapsed_s >= SETTLED_S]
    assert settled
    assert all(reading.state == "low_quality" for reading in settled)
    assert all(reading.bpm is None for reading in settled)


@pytest.mark.parametrize("noisy_region", [0, 1, 2])
def test_tone_local_to_one_region_leaves_the_shared_pulse_ok(noisy_region: int) -> None:
    locals_for = [silent, silent, silent]
    locals_for[noisy_region] = local_tone(LOCAL_TONES_BPM[noisy_region])
    recording = wave_recording(
        pure_pulse(SHARED_BPM),
        seed=SEED + 310 + noisy_region,
        duration_s=TRACE_S,
        local_waves_for=locals_for,
    )

    trace = reading_trace(PulseTracker(), recording)

    settled = [reading for elapsed_s, reading in trace if elapsed_s >= SETTLED_S + 0.1]
    assert settled
    for reading in settled:
        assert_ok_within_one_bpm(reading, SHARED_BPM)


def test_shared_rival_within_three_db_of_the_peak_is_never_ok() -> None:
    recording = wave_recording(
        two_tones(CLOSE_RIVAL_AMPLITUDE), seed=SEED + 320, duration_s=TRACE_S
    )

    trace = reading_trace(PulseTracker(), recording)

    settled = [reading for elapsed_s, reading in trace if elapsed_s >= SETTLED_S]
    assert settled
    assert all(reading.state == "low_quality" for reading in settled)


def test_shared_rival_well_below_the_peak_leaves_the_pulse_ok() -> None:
    recording = wave_recording(
        two_tones(FAR_RIVAL_AMPLITUDE), seed=SEED + 321, duration_s=TRACE_S
    )

    trace = reading_trace(PulseTracker(), recording)

    settled = [reading for elapsed_s, reading in trace if elapsed_s >= SETTLED_S + 0.1]
    assert settled
    for reading in settled:
        assert_ok_within_one_bpm(reading, SHARED_BPM)


@pytest.mark.parametrize("seed", [SEED + 330, SEED + 331, SEED + 332])
def test_halves_of_the_window_ten_bpm_apart_are_not_ok(seed: int) -> None:
    recording = wave_recording(
        rate_change_at_half(SPLIT_SECOND_HALF_BPM, SPLIT_SECOND_HALF_AMPLITUDE),
        seed=seed,
        duration_s=SETTLED_S + 0.5,
    )

    reading = first_settled_reading(recording)

    assert reading.state == "low_quality"
    assert reading.bpm is None


@pytest.mark.parametrize("seed", [SEED + 340, SEED + 341, SEED + 342])
def test_halves_of_the_window_three_bpm_apart_read_ok_between_them(seed: int) -> None:
    recording = wave_recording(
        rate_change_at_half(CLOSE_SECOND_HALF_BPM, 1.0),
        seed=seed,
        duration_s=SETTLED_S + 0.5,
    )

    reading = first_settled_reading(recording)

    assert reading.state == "ok"
    assert reading.bpm is not None
    assert FIRST_HALF_BPM - 1.0 <= reading.bpm <= CLOSE_SECOND_HALF_BPM + 1.0


def whole_second_readings(recording: Recording) -> list[Reading]:
    by_second = readings_by_second(PulseTracker(), recording)
    return [by_second[second] for second in WHOLE_SECONDS]


def harmonic_seed(
    base: int, true_bpm: float, harmonic_ratio: float, offset: int
) -> int:
    return base + 1000 * round(100 * harmonic_ratio) + 10 * int(true_bpm) + offset


def white_harmonic_readings(true_bpm: float, harmonic_ratio: float) -> list[Reading]:
    readings = []
    for offset in range(HARMONIC_SEEDS_PER_CASE):
        recording = webcam_recording(
            true_bpm,
            seed=harmonic_seed(
                WHITE_HARMONIC_SEED_BASE, true_bpm, harmonic_ratio, offset
            ),
            duration_s=TRACE_S,
            harmonic_ratio=harmonic_ratio,
        )
        readings.extend(whole_second_readings(recording))
    return readings


def doubled(bpms: list[float], true_bpm: float) -> list[float]:
    return [bpm for bpm in bpms if abs(bpm - 2.0 * true_bpm) <= DOUBLE_WITHIN_BPM]


def shown_bpms(readings: list[Reading]) -> list[float]:
    return [r.bpm for r in readings if r.state == "ok" and r.bpm is not None]


@pytest.mark.parametrize("true_bpm", HARMONIC_TRAP_RATES_BPM)
@pytest.mark.parametrize("harmonic_ratio", STRONG_HARMONIC_RATIOS)
def test_strong_second_harmonic_never_reads_double_and_shows_only_the_true_rate(
    true_bpm: float, harmonic_ratio: float
) -> None:
    readings = white_harmonic_readings(true_bpm, harmonic_ratio)

    assert len(readings) == HARMONIC_SEEDS_PER_CASE * len(WHOLE_SECONDS)
    shown = shown_bpms(readings)
    assert doubled(shown, true_bpm) == []
    assert all(abs(bpm - true_bpm) <= TRUE_WITHIN_BPM for bpm in shown)


@pytest.mark.parametrize("true_bpm", HARMONIC_TRAP_RATES_BPM)
def test_harmonic_at_six_tenths_reads_the_true_rate_in_nine_of_ten_readings(
    true_bpm: float,
) -> None:
    readings = white_harmonic_readings(true_bpm, READABLE_HARMONIC_RATIO)

    assert len(readings) == HARMONIC_SEEDS_PER_CASE * len(WHOLE_SECONDS)
    shown = shown_bpms(readings)
    assert doubled(shown, true_bpm) == []
    assert all(abs(bpm - true_bpm) <= TRUE_WITHIN_BPM for bpm in shown)
    assert len(shown) >= READABLE_SHOWN_SHARE * len(readings)


@pytest.mark.parametrize("true_bpm", BELOW_BAND_RATES_BPM)
@pytest.mark.parametrize("harmonic_ratio", BELOW_BAND_HARMONIC_RATIOS)
def test_pulse_below_the_band_is_never_ok_whatever_its_harmonic(
    true_bpm: float, harmonic_ratio: float
) -> None:
    for offset in range(HARMONIC_SEEDS_PER_CASE):
        recording = webcam_recording(
            true_bpm,
            seed=harmonic_seed(BELOW_BAND_SEED_BASE, true_bpm, harmonic_ratio, offset),
            duration_s=TRACE_S,
            harmonic_ratio=harmonic_ratio,
        )

        trace = reading_trace(PulseTracker(), recording)

        assert [reading for _, reading in trace if reading.state != "acquiring"]
        assert ok_readings(trace) == []


def test_harmonic_equal_to_the_fundamental_in_red_noise_rarely_reads_double() -> None:
    readings: list[tuple[float, Reading]] = []
    for true_bpm in HARMONIC_TRAP_RATES_BPM:
        for offset in range(RED_HARMONIC_SEEDS_PER_RATE):
            recording = red_noise_recording(
                true_bpm,
                seed=RED_HARMONIC_SEED_BASE + 100 * int(true_bpm) + offset,
                harmonic_ratio=EQUAL_HARMONIC_RATIO,
                duration_s=TRACE_S,
            )
            readings.extend(
                (true_bpm, reading) for reading in whole_second_readings(recording)
            )

    assert len(readings) == (
        len(HARMONIC_TRAP_RATES_BPM) * RED_HARMONIC_SEEDS_PER_RATE * len(WHOLE_SECONDS)
    )
    doubled_ok = [
        reading
        for true_bpm, reading in readings
        if reading.state == "ok"
        and reading.bpm is not None
        and abs(reading.bpm - 2.0 * true_bpm) <= DOUBLE_WITHIN_BPM
    ]
    assert len(doubled_ok) <= RED_DOUBLED_SHARE_HIGH * len(readings)


@pytest.mark.parametrize("loud_region", [0, 1, 2])
def test_one_region_far_louder_than_the_others_leaves_the_shared_pulse_ok(
    loud_region: int,
) -> None:
    locals_for = [silent, silent, silent]
    locals_for[loud_region] = loud_tone(LOCAL_TONES_BPM[loud_region])
    recording = wave_recording(
        pure_pulse(SHARED_BPM),
        seed=SEED + 360 + loud_region,
        duration_s=TRACE_S,
        local_waves_for=locals_for,
    )

    trace = reading_trace(PulseTracker(), recording)

    settled = [reading for elapsed_s, reading in trace if elapsed_s >= SETTLED_S + 0.1]
    assert settled
    for reading in settled:
        assert_ok_within_one_bpm(reading, SHARED_BPM)
