import math

import numpy as np
import pytest

from pulse_frame.signal.errors import SignalError
from pulse_frame.signal.tracker import MIN_SNR_DB, PulseTracker, Reading
from tests.signal.synthetic import (
    constant_recording,
    dominant_frequency_hz,
    piecewise_wave,
    ramp_bpm,
    ramp_wave,
    reported_jitter_recording,
    sine_amplitude,
    variable_rate_recording,
    wave_recording,
    webcam_recording,
)
from tests.signal.tracking import feed, reading_trace, readings_by_second

SEED = 20261111
TRUE_RATES_BPM = [45.0, 60.0, 72.0, 90.0, 120.0, 150.0, 180.0]
FULL_WINDOW_S = 10.0
FIRST_OK_S = FULL_WINDOW_S + 0.05
NOISE_SEEDS = [SEED, SEED + 1, SEED + 2]
NOISE_QUALITY_CEILING_DB = 3.5
RAMP_START_S = 12.0
RAMP_END_S = 22.0
RAMP_FROM_BPM = 70.0
RAMP_TO_BPM = 120.0
RAMP_SLACK_BPM = 10.0
RAMP_RECOVERED_S = 31.0


def assert_ok_within_one_bpm(reading: Reading, true_bpm: float) -> None:
    assert isinstance(reading, Reading)
    assert reading.state == "ok"
    assert reading.bpm is not None
    assert reading.bpm == pytest.approx(true_bpm, abs=1.0)
    assert reading.quality_db is not None


def assert_acquiring(reading: Reading) -> None:
    assert reading.state == "acquiring"
    assert reading.bpm is None


@pytest.mark.parametrize("true_bpm", TRUE_RATES_BPM)
def test_rate_within_one_bpm_after_fifteen_seconds_of_webcam_signal(
    true_bpm: float,
) -> None:
    recording = webcam_recording(true_bpm, seed=SEED + int(true_bpm))
    first_fifteen = recording.until(15.0)
    tracker = PulseTracker()

    feed(tracker, first_fifteen)
    assert_ok_within_one_bpm(tracker.reading(), true_bpm)

    feed(tracker, recording.after(15.0))
    assert_ok_within_one_bpm(tracker.reading(), true_bpm)


@pytest.mark.parametrize("true_bpm", [45.0, 72.0, 150.0])
def test_rate_within_one_bpm_when_reported_timestamps_carry_jitter_but_capture_does_not(
    true_bpm: float,
) -> None:
    recording = reported_jitter_recording(true_bpm, seed=SEED + 3 * int(true_bpm))
    tracker = PulseTracker()

    feed(tracker, recording.until(15.0))
    assert_ok_within_one_bpm(tracker.reading(), true_bpm)

    feed(tracker, recording.after(15.0))
    assert_ok_within_one_bpm(tracker.reading(), true_bpm)


@pytest.mark.parametrize("true_bpm", [60.0, 90.0, 150.0])
def test_rate_within_one_bpm_when_frame_rate_varies_between_25_and_35_fps(
    true_bpm: float,
) -> None:
    recording = variable_rate_recording(true_bpm, seed=SEED + 7 * int(true_bpm))
    intervals_ms = np.diff(recording.timestamps_ms)
    assert intervals_ms.min() >= 1000.0 / 35.0
    assert intervals_ms.max() <= 1000.0 / 25.0
    tracker = PulseTracker()

    feed(tracker, recording.until(15.0))
    assert_ok_within_one_bpm(tracker.reading(), true_bpm)

    tracker = PulseTracker()
    feed(tracker, recording)
    assert_ok_within_one_bpm(tracker.reading(), true_bpm)


@pytest.mark.parametrize("true_bpm", [42.0, 45.0])
@pytest.mark.parametrize("seed", [SEED + 40, SEED + 41, SEED + 42])
def test_low_rates_within_one_bpm_at_ten_and_fifteen_seconds(
    true_bpm: float, seed: int
) -> None:
    by_second = readings_by_second(
        PulseTracker(), webcam_recording(true_bpm, seed=seed, duration_s=15.4)
    )

    assert_ok_within_one_bpm(by_second[10], true_bpm)
    assert_ok_within_one_bpm(by_second[15], true_bpm)


@pytest.mark.parametrize("true_bpm", [45.0, 60.0])
@pytest.mark.parametrize("harmonic_ratio", [0.6, 0.8])
def test_strong_second_harmonic_never_reported_as_double_rate(
    true_bpm: float, harmonic_ratio: float
) -> None:
    recording = webcam_recording(
        true_bpm, seed=SEED + 50, duration_s=20.4, harmonic_ratio=harmonic_ratio
    )

    by_second = readings_by_second(PulseTracker(), recording)

    for second in range(10, 21):
        assert_ok_within_one_bpm(by_second[second], true_bpm)


@pytest.mark.parametrize("seed", [SEED + 60, SEED + 61, SEED + 62])
def test_pulse_below_the_band_is_never_ok(seed: int) -> None:
    recording = webcam_recording(30.0, seed=seed, duration_s=20.4)

    trace = reading_trace(PulseTracker(), recording)

    assert [reading for _, reading in trace if reading.state == "ok"] == []


def test_new_tracker_is_acquiring_without_bpm() -> None:
    assert_acquiring(PulseTracker().reading())


def test_under_five_seconds_of_clean_pulse_is_acquiring_without_bpm() -> None:
    tracker = PulseTracker()
    feed(tracker, webcam_recording(72.0, seed=SEED, motion_step=False).until(4.8))

    assert_acquiring(tracker.reading())


@pytest.mark.parametrize("true_bpm", [45.0, 72.0, 150.0])
def test_clean_pulse_is_acquiring_until_a_full_window_then_ok_within_one_bpm(
    true_bpm: float,
) -> None:
    recording = webcam_recording(
        true_bpm, seed=SEED + 70 + int(true_bpm), duration_s=20.4, motion_step=False
    )

    trace = reading_trace(PulseTracker(), recording)

    for elapsed_s, reading in trace:
        if elapsed_s < FULL_WINDOW_S:
            assert_acquiring(reading)
        elif elapsed_s >= FIRST_OK_S:
            assert_ok_within_one_bpm(reading, true_bpm)


@pytest.mark.parametrize("seed", NOISE_SEEDS)
def test_noise_is_acquiring_until_a_full_window_then_low_quality(seed: int) -> None:
    trace = reading_trace(PulseTracker(), webcam_recording(None, seed=seed))

    for elapsed_s, reading in trace:
        if elapsed_s < FULL_WINDOW_S:
            assert_acquiring(reading)
        elif elapsed_s >= FIRST_OK_S:
            assert reading.state == "low_quality"
            assert reading.bpm is None


@pytest.mark.parametrize("seed", NOISE_SEEDS)
def test_noise_without_pulse_is_low_quality_with_quality_below_threshold(
    seed: int,
) -> None:
    recording = webcam_recording(None, seed=seed)
    tracker = PulseTracker()

    feed(tracker, recording.until(15.0))
    at_fifteen = tracker.reading()
    tracker = PulseTracker()
    feed(tracker, recording)
    at_twenty = tracker.reading()

    for reading in (at_fifteen, at_twenty):
        assert reading.state == "low_quality"
        assert reading.bpm is None
        assert isinstance(reading.quality_db, float)
        assert math.isfinite(reading.quality_db)
        assert reading.quality_db < MIN_SNR_DB
        assert reading.quality_db < NOISE_QUALITY_CEILING_DB


def ok_tracker_at_twelve_seconds() -> tuple[
    PulseTracker, float, tuple[float, float, float]
]:
    recording = webcam_recording(72.0, seed=SEED + 80, motion_step=False)
    tracker = PulseTracker()
    feed(tracker, recording.until(12.0))
    assert_ok_within_one_bpm(tracker.reading(), 72.0)
    last_ms = float(recording.until(12.0).timestamps_ms[-1])
    _, next_rgb = recording.after(12.0).samples()[0]
    return tracker, last_ms, next_rgb


@pytest.mark.parametrize("gap_ms", [1100.0, 1500.0])
def test_gap_over_one_second_restarts_to_acquiring_with_empty_waveform(
    gap_ms: float,
) -> None:
    tracker, last_ms, next_rgb = ok_tracker_at_twelve_seconds()

    tracker.add(last_ms + gap_ms, next_rgb)

    reading = tracker.reading()
    assert_acquiring(reading)
    assert reading.quality_db is None
    assert tracker.waveform() == []


@pytest.mark.parametrize("gap_ms", [900.0, 1000.0])
def test_gap_of_at_most_one_second_keeps_the_reading(gap_ms: float) -> None:
    tracker, last_ms, next_rgb = ok_tracker_at_twelve_seconds()

    tracker.add(last_ms + gap_ms, next_rgb)

    assert_ok_within_one_bpm(tracker.reading(), 72.0)
    assert len(tracker.waveform()) > 0


def test_after_a_long_gap_the_tracker_waits_for_a_full_window_again() -> None:
    tracker, last_ms, _ = ok_tracker_at_twelve_seconds()
    resumed = webcam_recording(72.0, seed=SEED + 81, duration_s=12.0, motion_step=False)
    resumed = resumed.shifted(last_ms + 1500.0 - float(resumed.timestamps_ms[0]))

    trace = reading_trace(tracker, resumed)

    for elapsed_s, reading in trace:
        if elapsed_s < FULL_WINDOW_S:
            assert_acquiring(reading)
        elif elapsed_s >= FIRST_OK_S:
            assert_ok_within_one_bpm(reading, 72.0)


def test_restart_after_a_gap_forgets_the_rate_before_it() -> None:
    before = webcam_recording(60.0, seed=SEED + 150, duration_s=12.0)
    after = webcam_recording(90.0, seed=SEED + 151, duration_s=12.4)
    resume_ms = float(before.timestamps_ms[-1]) + 1500.0
    after = after.shifted(resume_ms - float(after.timestamps_ms[0]))
    tracker = PulseTracker()
    feed(tracker, before)
    assert_ok_within_one_bpm(tracker.reading(), 60.0)

    trace = reading_trace(tracker, after)

    shown = [reading for _, reading in trace if reading.state == "ok"]
    assert shown
    assert_ok_within_one_bpm(shown[0], 90.0)
    for reading in shown:
        assert reading.bpm is not None
        assert abs(reading.bpm - 60.0) > 10.0


@pytest.mark.parametrize(
    "rgb", [(140.0, 110.0, 95.0), (0.0, 0.0, 0.0)], ids=["frozen", "black"]
)
def test_constant_colour_camera_is_low_quality_with_finite_quality(
    rgb: tuple[float, float, float],
) -> None:
    recording = constant_recording(rgb, seed=SEED + 160, duration_s=12.0)

    trace = reading_trace(PulseTracker(), recording)

    after_window = [reading for elapsed_s, reading in trace if elapsed_s >= FIRST_OK_S]
    assert after_window
    for reading in after_window:
        assert reading.state == "low_quality"
        assert reading.bpm is None
        assert isinstance(reading.quality_db, float)
        assert math.isfinite(reading.quality_db)


def test_reading_changes_at_most_once_per_second_of_signal_time() -> None:
    recording = webcam_recording(72.0, seed=SEED + 170, duration_s=20.4)

    trace = reading_trace(PulseTracker(), recording)

    changed_at = [
        elapsed_s
        for (elapsed_s, reading), (_, previous) in zip(trace[1:], trace, strict=False)
        if reading != previous
    ]
    for second in range(11, 20):
        assert len([t for t in changed_at if second <= t < second + 1]) <= 1
    assert len([t for t in changed_at if 11 <= t < 20]) >= 5


def test_waveform_is_empty_until_the_pos_window_is_filled() -> None:
    recording = webcam_recording(72.0, seed=SEED + 180, duration_s=2.0)
    tracker = PulseTracker()

    feed(tracker, recording.until(1.0))
    assert tracker.waveform() == []

    feed(tracker, recording.after(1.0))
    assert len(tracker.waveform()) > 0


@pytest.mark.parametrize("seed", [SEED + 200, SEED + 209, SEED + 216])
def test_rate_ramp_shows_no_stale_rate_and_recovers_after_it_settles(
    seed: int,
) -> None:
    recording = wave_recording(
        lambda seconds: ramp_wave(
            seconds, RAMP_START_S, RAMP_END_S, RAMP_FROM_BPM, RAMP_TO_BPM
        ),
        seed=seed,
        duration_s=40.4,
    )

    trace = reading_trace(PulseTracker(), recording)

    at_eleven = [reading for elapsed_s, reading in trace if 11.0 <= elapsed_s < 12.0]
    assert_ok_within_one_bpm(at_eleven[-1], RAMP_FROM_BPM)
    for elapsed_s, reading in trace:
        if reading.state == "ok":
            assert reading.bpm is not None
            oldest_bpm = ramp_bpm(
                elapsed_s - FULL_WINDOW_S,
                RAMP_START_S,
                RAMP_END_S,
                RAMP_FROM_BPM,
                RAMP_TO_BPM,
            )
            newest_bpm = ramp_bpm(
                elapsed_s, RAMP_START_S, RAMP_END_S, RAMP_FROM_BPM, RAMP_TO_BPM
            )
            assert reading.bpm >= oldest_bpm - RAMP_SLACK_BPM
            assert reading.bpm <= newest_bpm + RAMP_SLACK_BPM
        if elapsed_s >= RAMP_RECOVERED_S:
            assert_ok_within_one_bpm(reading, RAMP_TO_BPM)


@pytest.mark.parametrize("seed", [SEED + 90, SEED + 91])
def test_sustained_step_in_rate_is_shown_without_inventing_values_between(
    seed: int,
) -> None:
    recording = wave_recording(
        lambda seconds: piecewise_wave(seconds, [(0.0, 60.0), (5.5, 90.0)]),
        seed=seed,
        duration_s=20.4,
    )

    by_second = readings_by_second(PulseTracker(), recording)

    for reading in by_second.values():
        if reading.state == "ok":
            assert reading.bpm is not None
            assert min(abs(reading.bpm - 60.0), abs(reading.bpm - 90.0)) <= 2.5
    for second in range(16, 21):
        assert_ok_within_one_bpm(by_second[second], 90.0)


@pytest.mark.parametrize("seed", [SEED + 100, SEED + 101])
def test_rate_after_a_low_quality_stretch_does_not_return_the_old_rate(
    seed: int,
) -> None:
    recording = wave_recording(
        lambda seconds: piecewise_wave(
            seconds, [(0.0, 60.0), (12.0, None), (24.0, 90.0)]
        ),
        seed=seed,
        duration_s=40.4,
    )

    by_second = readings_by_second(PulseTracker(), recording)

    assert_ok_within_one_bpm(by_second[11], 60.0)
    low_seconds = [s for s, r in by_second.items() if r.state == "low_quality"]
    assert low_seconds
    for second, reading in by_second.items():
        if second > low_seconds[0] and reading.state == "ok":
            assert reading.bpm is not None
            assert reading.bpm > 80.0
    for second in range(35, 41):
        assert_ok_within_one_bpm(by_second[second], 90.0)


def test_duplicate_and_out_of_order_samples_added_are_ignored() -> None:
    recording = webcam_recording(72.0, seed=SEED + 110, duration_s=15.0)
    clean = PulseTracker()
    feed(clean, recording)
    noisy = PulseTracker()

    for index, (timestamp_ms, rgb) in enumerate(recording.samples()):
        noisy.add(timestamp_ms, rgb)
        if index % 7 == 3:
            noisy.add(timestamp_ms, (255.0, 0.0, 0.0))
            noisy.add(timestamp_ms - 50.0, (0.0, 255.0, 0.0))

    assert noisy.reading() == clean.reading()
    assert_ok_within_one_bpm(noisy.reading(), 72.0)
    waveform = np.array(noisy.waveform(), dtype=np.float64)
    np.testing.assert_array_equal(waveform, np.array(clean.waveform()))
    assert np.all(np.diff(waveform[:, 0]) > 0)


def test_sample_far_older_than_the_last_is_ignored() -> None:
    recording = webcam_recording(72.0, seed=SEED + 140, duration_s=15.0)
    clean = PulseTracker()
    feed(clean, recording)
    noisy = PulseTracker()
    stale_index = int(12.0 * 30.0)

    for index, (timestamp_ms, rgb) in enumerate(recording.samples()):
        noisy.add(timestamp_ms, rgb)
        if index == stale_index:
            noisy.add(timestamp_ms - 1500.0, (0.0, 255.0, 0.0))

    assert_ok_within_one_bpm(noisy.reading(), 72.0)
    assert noisy.reading() == clean.reading()
    np.testing.assert_array_equal(
        np.array(noisy.waveform()), np.array(clean.waveform())
    )


def test_waveform_holds_last_ten_seconds_of_band_passed_pulse() -> None:
    recording = webcam_recording(72.0, seed=SEED)
    tracker = PulseTracker()
    feed(tracker, recording)
    last_input_ms = recording.timestamps_ms[-1]
    frame_ms = 1000.0 / 30.0

    waveform = tracker.waveform()

    assert len(waveform) > 0
    samples = np.array(waveform, dtype=np.float64)
    times, values = samples[:, 0], samples[:, 1]
    assert np.all(np.diff(times) > 0)
    assert times[0] >= last_input_ms - 10_000.0 - frame_ms
    assert times[0] <= last_input_ms - 9_000.0
    assert times[-1] <= last_input_ms
    assert times[-1] >= last_input_ms - 2.0 * frame_ms
    assert np.all(np.isfinite(values))
    assert abs(values.mean()) < 0.2 * values.std()
    fs_hz = 1000.0 / float(np.median(np.diff(times)))
    assert dominant_frequency_hz(values, fs_hz) == pytest.approx(72.0 / 60.0, abs=0.1)


@pytest.mark.parametrize("out_of_band_hz", [0.1, 8.0])
def test_waveform_strongly_attenuates_out_of_band_components(
    out_of_band_hz: float,
) -> None:
    pulse_hz = 1.2
    recording = wave_recording(
        lambda seconds: (
            np.sin(2.0 * np.pi * pulse_hz * seconds)
            + np.sin(2.0 * np.pi * out_of_band_hz * seconds + 0.3)
        ),
        seed=SEED + 120,
        duration_s=20.0,
    )
    tracker = PulseTracker()
    feed(tracker, recording)

    samples = np.array(tracker.waveform(), dtype=np.float64)

    seconds = (samples[:, 0] - recording.timestamps_ms[0]) / 1000.0
    pulse_amplitude = sine_amplitude(seconds, samples[:, 1], pulse_hz)
    leak_amplitude = sine_amplitude(seconds, samples[:, 1], out_of_band_hz)
    assert pulse_amplitude > 0.0
    assert leak_amplitude < 0.1 * pulse_amplitude


BAD_SETTINGS = {
    "zero_rate": ({"fs_hz": 0.0}, "BAD_SAMPLE_RATE"),
    "nan_rate": ({"fs_hz": math.nan}, "BAD_SAMPLE_RATE"),
    "inf_window": ({"window_s": math.inf, "min_seconds": 5.0}, "BAD_WINDOW"),
    "nan_window": ({"window_s": math.nan, "min_seconds": 5.0}, "BAD_WINDOW"),
    "nan_min_seconds": ({"window_s": 10.0, "min_seconds": math.nan}, "BAD_WINDOW"),
    "min_seconds_one": ({"window_s": 10.0, "min_seconds": 1.0}, "BAD_WINDOW"),
    "min_seconds_under_pos_window": (
        {"window_s": 10.0, "min_seconds": 1.5},
        "BAD_WINDOW",
    ),
    "min_seconds_over_window": (
        {"window_s": 10.0, "min_seconds": 12.0},
        "BAD_WINDOW",
    ),
    "window_under_pos_window": ({"window_s": 1.0, "min_seconds": 1.0}, "BAD_WINDOW"),
    "rate_nine": ({"fs_hz": 9.0}, "BAD_SAMPLE_RATE"),
    "rate_five": ({"fs_hz": 5.0}, "BAD_SAMPLE_RATE"),
    "window_two": ({"window_s": 2.0, "min_seconds": 2.0}, "BAD_WINDOW"),
    "window_five": ({"window_s": 5.0, "min_seconds": 5.0}, "BAD_WINDOW"),
    "window_just_under_ten": ({"window_s": 9.9, "min_seconds": 9.9}, "BAD_WINDOW"),
}


@pytest.mark.parametrize(
    ("kwargs", "code"), list(BAD_SETTINGS.values()), ids=list(BAD_SETTINGS)
)
def test_tracker_rejects_bad_settings_with_a_coded_error(
    kwargs: dict[str, float], code: str
) -> None:
    with pytest.raises(SignalError) as caught:
        PulseTracker(**kwargs)

    assert caught.value.code == code
    assert caught.value.message
    assert caught.value.action


def test_window_under_pos_window_is_reported_against_window_s_first() -> None:
    with pytest.raises(SignalError) as caught:
        PulseTracker(window_s=1.0, min_seconds=1.0)

    assert caught.value.code == "BAD_WINDOW"
    assert "window_s (1.0 s)" in caught.value.message
    assert "min_seconds (" not in caught.value.message


@pytest.mark.parametrize(
    ("window_s", "min_seconds"), [(10.0, 1.6), (10.0, 10.0), (12.0, 12.0)]
)
def test_tracker_accepts_min_seconds_from_pos_window_up_to_window(
    window_s: float, min_seconds: float
) -> None:
    assert_acquiring(PulseTracker(window_s=window_s, min_seconds=min_seconds).reading())


@pytest.mark.parametrize("fs_hz", [9.5, 10.0])
def test_tracker_accepts_a_sample_rate_just_above_the_floor(fs_hz: float) -> None:
    assert_acquiring(PulseTracker(fs_hz=fs_hz).reading())


@pytest.mark.parametrize(
    ("timestamp_ms", "rgb", "code"),
    [
        (math.nan, (145.0, 115.0, 100.0), "BAD_TIMESTAMPS"),
        (math.inf, (145.0, 115.0, 100.0), "BAD_TIMESTAMPS"),
        (1000.0, (145.0, math.nan, 100.0), "BAD_VALUES"),
        (1000.0, (145.0, 115.0, math.inf), "BAD_VALUES"),
        (1000.0, (145.0, 115.0), "BAD_VALUES"),
    ],
)
def test_add_rejects_bad_samples_with_a_coded_error(
    timestamp_ms: float, rgb: tuple[float, ...], code: str
) -> None:
    tracker = PulseTracker()

    with pytest.raises(SignalError) as caught:
        tracker.add(timestamp_ms, rgb)

    assert caught.value.code == code
    assert caught.value.message
    assert caught.value.action
