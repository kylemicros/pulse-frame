import math

import numpy as np
import pytest

from pulse_frame.signal.errors import SignalError
from pulse_frame.signal.tracker import PulseTracker, Reading, RegionColours
from tests.signal.synthetic import (
    constant_recording,
    dominant_frequency_hz,
    piecewise_wave,
    ramp_bpm,
    ramp_wave,
    reported_jitter_recording,
    same_colour_everywhere,
    sine_amplitude,
    variable_rate_recording,
    wave_recording,
    webcam_recording,
)
from tests.signal.tracking import (
    assert_ok_within_one_bpm,
    feed,
    reading_trace,
    readings_by_second,
)

SEED = 20261111
TRUE_RATES_BPM = [45.0, 60.0, 72.0, 90.0, 120.0, 150.0, 180.0]
FULL_WINDOW_S = 20.0
FIRST_OK_S = FULL_WINDOW_S + 0.05
FIRST_LOOK_S = FULL_WINDOW_S + 0.5
NOISE_SEEDS = [SEED, SEED + 1, SEED + 2]
RAMP_START_S = 22.0
RAMP_END_S = 32.0
RAMP_FROM_BPM = 70.0
RAMP_TO_BPM = 120.0
RAMP_SLACK_BPM = 10.0
RAMP_RECOVERED_S = 53.0
STEP_AT_S = 5.5
STEP_SETTLED_SECONDS = range(26, 31)
QUIET_FROM_S = 22.0
RESUMED_AT_S = 28.0
RESUMED_SETTLED_SECONDS = range(49, 53)
OK_BEFORE_S = 22.0


def assert_acquiring(reading: Reading) -> None:
    assert reading.state == "acquiring"
    assert reading.bpm is None


def same_colour_except(
    rgb: tuple[float, float, float], name: str, odd: tuple[float, ...]
) -> RegionColours:
    colours = {"forehead": rgb, "left_cheek": rgb, "right_cheek": rgb}
    colours[name] = odd
    return RegionColours(**colours)


@pytest.mark.parametrize("true_bpm", TRUE_RATES_BPM)
def test_rate_within_one_bpm_at_twenty_and_twenty_five_seconds_of_webcam_signal(
    true_bpm: float,
) -> None:
    recording = webcam_recording(true_bpm, seed=SEED + int(true_bpm))
    tracker = PulseTracker()

    feed(tracker, recording.until(FIRST_LOOK_S))
    assert_ok_within_one_bpm(tracker.reading(), true_bpm)

    feed(tracker, recording.after(FIRST_LOOK_S))
    assert_ok_within_one_bpm(tracker.reading(), true_bpm)


@pytest.mark.parametrize("true_bpm", [45.0, 72.0, 150.0])
def test_rate_within_one_bpm_when_reported_timestamps_carry_jitter_but_capture_does_not(
    true_bpm: float,
) -> None:
    recording = reported_jitter_recording(true_bpm, seed=SEED + 3 * int(true_bpm))
    tracker = PulseTracker()

    feed(tracker, recording.until(FIRST_LOOK_S))
    assert_ok_within_one_bpm(tracker.reading(), true_bpm)

    feed(tracker, recording.after(FIRST_LOOK_S))
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

    feed(tracker, recording.until(FIRST_LOOK_S))
    assert_ok_within_one_bpm(tracker.reading(), true_bpm)

    tracker = PulseTracker()
    feed(tracker, recording)
    assert_ok_within_one_bpm(tracker.reading(), true_bpm)


@pytest.mark.parametrize("true_bpm", [42.0, 45.0])
@pytest.mark.parametrize("seed", [SEED + 40, SEED + 41, SEED + 42])
def test_low_rates_within_one_bpm_at_twenty_and_twenty_five_seconds(
    true_bpm: float, seed: int
) -> None:
    by_second = readings_by_second(
        PulseTracker(), webcam_recording(true_bpm, seed=seed, duration_s=25.4)
    )

    assert_ok_within_one_bpm(by_second[20], true_bpm)
    assert_ok_within_one_bpm(by_second[25], true_bpm)


def test_new_tracker_is_acquiring_without_bpm() -> None:
    assert_acquiring(PulseTracker().reading())


@pytest.mark.parametrize("true_bpm", [45.0, 72.0, 150.0])
def test_clean_pulse_is_acquiring_until_a_full_window_then_ok_within_one_bpm(
    true_bpm: float,
) -> None:
    recording = webcam_recording(
        true_bpm, seed=SEED + 70 + int(true_bpm), duration_s=25.4, motion_step=False
    )

    trace = reading_trace(PulseTracker(), recording)

    assert trace[-1][0] >= FIRST_OK_S
    for elapsed_s, reading in trace:
        if elapsed_s < FULL_WINDOW_S:
            assert_acquiring(reading)
        elif elapsed_s >= FIRST_OK_S:
            assert_ok_within_one_bpm(reading, true_bpm)


@pytest.mark.parametrize("seed", NOISE_SEEDS)
def test_noise_is_acquiring_until_a_full_window_then_low_quality(seed: int) -> None:
    trace = reading_trace(PulseTracker(), webcam_recording(None, seed=seed))

    assert trace[-1][0] >= FIRST_OK_S
    for elapsed_s, reading in trace:
        if elapsed_s < FULL_WINDOW_S:
            assert_acquiring(reading)
        elif elapsed_s >= FIRST_OK_S:
            assert reading.state == "low_quality"
            assert reading.bpm is None


def ok_tracker_at_twenty_two_seconds() -> tuple[PulseTracker, float, RegionColours]:
    recording = webcam_recording(72.0, seed=SEED + 80, motion_step=False)
    tracker = PulseTracker()
    feed(tracker, recording.until(OK_BEFORE_S))
    assert_ok_within_one_bpm(tracker.reading(), 72.0)
    last_ms = float(recording.until(OK_BEFORE_S).timestamps_ms[-1])
    _, next_regions = recording.after(OK_BEFORE_S).samples()[0]
    return tracker, last_ms, next_regions


@pytest.mark.parametrize("gap_ms", [1100.0, 1500.0])
def test_gap_over_one_second_restarts_to_acquiring_with_empty_waveform(
    gap_ms: float,
) -> None:
    tracker, last_ms, next_regions = ok_tracker_at_twenty_two_seconds()

    tracker.add(last_ms + gap_ms, next_regions)

    reading = tracker.reading()
    assert_acquiring(reading)
    assert reading.quality_db is None
    assert tracker.waveform() == []


@pytest.mark.parametrize("gap_ms", [900.0, 1000.0])
def test_gap_of_at_most_one_second_keeps_the_reading(gap_ms: float) -> None:
    tracker, last_ms, next_regions = ok_tracker_at_twenty_two_seconds()

    tracker.add(last_ms + gap_ms, next_regions)

    assert_ok_within_one_bpm(tracker.reading(), 72.0)
    assert len(tracker.waveform()) > 0


def test_after_a_long_gap_the_tracker_waits_for_a_full_window_again() -> None:
    tracker, last_ms, _ = ok_tracker_at_twenty_two_seconds()
    resumed = webcam_recording(72.0, seed=SEED + 81, duration_s=22.0, motion_step=False)
    resumed = resumed.shifted(last_ms + 1500.0 - float(resumed.timestamps_ms[0]))

    trace = reading_trace(tracker, resumed)

    assert trace[-1][0] >= FIRST_OK_S
    for elapsed_s, reading in trace:
        if elapsed_s < FULL_WINDOW_S:
            assert_acquiring(reading)
        elif elapsed_s >= FIRST_OK_S:
            assert_ok_within_one_bpm(reading, 72.0)


def test_restart_after_a_gap_forgets_the_rate_before_it() -> None:
    before = webcam_recording(60.0, seed=SEED + 150, duration_s=22.0)
    after = webcam_recording(90.0, seed=SEED + 151, duration_s=22.4)
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
def test_constant_colour_camera_is_low_quality_without_bpm(
    rgb: tuple[float, float, float],
) -> None:
    recording = constant_recording(rgb, seed=SEED + 160, duration_s=22.0)

    trace = reading_trace(PulseTracker(), recording)

    after_window = [reading for elapsed_s, reading in trace if elapsed_s >= FIRST_OK_S]
    assert after_window
    for reading in after_window:
        assert reading.state == "low_quality"
        assert reading.bpm is None
        assert reading.quality_db is None


def test_reading_changes_at_most_once_per_second_of_signal_time() -> None:
    recording = webcam_recording(72.0, seed=SEED + 170, duration_s=30.4)

    trace = reading_trace(PulseTracker(), recording)

    changed_at = [
        elapsed_s
        for (elapsed_s, reading), (_, previous) in zip(trace[1:], trace, strict=False)
        if reading != previous
    ]
    for second in range(21, 30):
        assert len([t for t in changed_at if second <= t < second + 1]) <= 1
    assert len([t for t in changed_at if 21 <= t < 30]) >= 5


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
        duration_s=RAMP_RECOVERED_S + 2.4,
    )

    trace = reading_trace(PulseTracker(), recording)

    before_ramp = [
        reading
        for elapsed_s, reading in trace
        if FIRST_OK_S <= elapsed_s < RAMP_START_S
    ]
    assert_ok_within_one_bpm(before_ramp[-1], RAMP_FROM_BPM)
    assert trace[-1][0] >= RAMP_RECOVERED_S
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
        lambda seconds: piecewise_wave(seconds, [(0.0, 60.0), (STEP_AT_S, 90.0)]),
        seed=seed,
        duration_s=30.4,
    )

    by_second = readings_by_second(PulseTracker(), recording)

    for reading in by_second.values():
        if reading.state == "ok":
            assert reading.bpm is not None
            assert min(abs(reading.bpm - 60.0), abs(reading.bpm - 90.0)) <= 2.5
    for second in STEP_SETTLED_SECONDS:
        assert_ok_within_one_bpm(by_second[second], 90.0)


@pytest.mark.parametrize("seed", [SEED + 100, SEED + 101])
def test_rate_after_a_low_quality_stretch_does_not_return_the_old_rate(
    seed: int,
) -> None:
    recording = wave_recording(
        lambda seconds: piecewise_wave(
            seconds, [(0.0, 60.0), (QUIET_FROM_S, None), (RESUMED_AT_S, 90.0)]
        ),
        seed=seed,
        duration_s=RESUMED_SETTLED_SECONDS[-1] + 0.4,
    )

    by_second = readings_by_second(PulseTracker(), recording)

    assert_ok_within_one_bpm(by_second[21], 60.0)
    low_seconds = [s for s, r in by_second.items() if r.state == "low_quality"]
    assert low_seconds
    for second, reading in by_second.items():
        if second > low_seconds[0] and reading.state == "ok":
            assert reading.bpm is not None
            assert reading.bpm > 80.0
    for second in RESUMED_SETTLED_SECONDS:
        assert_ok_within_one_bpm(by_second[second], 90.0)


def test_duplicate_and_out_of_order_samples_added_are_ignored() -> None:
    recording = webcam_recording(72.0, seed=SEED + 110, duration_s=22.0)
    clean = PulseTracker()
    feed(clean, recording)
    noisy = PulseTracker()

    for index, (timestamp_ms, regions) in enumerate(recording.samples()):
        noisy.add(timestamp_ms, regions)
        if index % 7 == 3:
            noisy.add(timestamp_ms, same_colour_everywhere((255.0, 0.0, 0.0)))
            noisy.add(timestamp_ms - 50.0, same_colour_everywhere((0.0, 255.0, 0.0)))

    assert noisy.reading() == clean.reading()
    assert_ok_within_one_bpm(noisy.reading(), 72.0)
    waveform = np.array(noisy.waveform(), dtype=np.float64)
    np.testing.assert_array_equal(waveform, np.array(clean.waveform()))
    assert np.all(np.diff(waveform[:, 0]) > 0)


def test_sample_far_older_than_the_last_is_ignored() -> None:
    recording = webcam_recording(72.0, seed=SEED + 140, duration_s=22.0)
    clean = PulseTracker()
    feed(clean, recording)
    noisy = PulseTracker()
    stale_index = int(21.0 * 30.0)

    for index, (timestamp_ms, regions) in enumerate(recording.samples()):
        noisy.add(timestamp_ms, regions)
        if index == stale_index:
            noisy.add(timestamp_ms - 1500.0, same_colour_everywhere((0.0, 255.0, 0.0)))

    assert_ok_within_one_bpm(noisy.reading(), 72.0)
    assert noisy.reading() == clean.reading()
    np.testing.assert_array_equal(
        np.array(noisy.waveform()), np.array(clean.waveform())
    )


def test_waveform_ends_at_the_newest_sample_and_holds_the_band_passed_pulse() -> None:
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
    assert times[0] >= last_input_ms - FULL_WINDOW_S * 1000.0 - frame_ms
    assert times[0] <= last_input_ms - (FULL_WINDOW_S - 1.0) * 1000.0
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
        duration_s=22.0,
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
    "nan_min_seconds": ({"window_s": 20.0, "min_seconds": math.nan}, "BAD_WINDOW"),
    "min_seconds_one": ({"window_s": 20.0, "min_seconds": 1.0}, "BAD_WINDOW"),
    "min_seconds_over_window": (
        {"window_s": 20.0, "min_seconds": 22.0},
        "BAD_WINDOW",
    ),
    "window_one": ({"window_s": 1.0, "min_seconds": 1.0}, "BAD_WINDOW"),
    "rate_nine": ({"fs_hz": 9.0}, "BAD_SAMPLE_RATE"),
    "rate_five": ({"fs_hz": 5.0}, "BAD_SAMPLE_RATE"),
    "window_two": ({"window_s": 2.0, "min_seconds": 2.0}, "BAD_WINDOW"),
    "window_ten": ({"window_s": 10.0, "min_seconds": 10.0}, "BAD_WINDOW"),
    "window_just_under_twenty": (
        {"window_s": 19.9, "min_seconds": 19.9},
        "BAD_WINDOW",
    ),
    "min_seconds_ten": ({"min_seconds": 10.0}, "BAD_WINDOW"),
    "min_seconds_just_under_twenty": ({"min_seconds": 19.9}, "BAD_WINDOW"),
    "min_seconds_under_a_longer_window": (
        {"window_s": 25.0, "min_seconds": 20.0},
        "BAD_WINDOW",
    ),
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


def test_window_under_twenty_seconds_is_reported_before_min_seconds_mismatch() -> None:
    with pytest.raises(SignalError) as caught:
        PulseTracker(window_s=1.0, min_seconds=5.0)

    assert caught.value.code == "BAD_WINDOW"
    assert "window_s (1.0 s)" in caught.value.message
    assert "min_seconds (" not in caught.value.message


def test_tracker_accepts_the_twenty_second_window_it_gates_on() -> None:
    assert_acquiring(PulseTracker(window_s=20.0, min_seconds=20.0).reading())


def test_tracker_accepts_min_seconds_equal_to_a_longer_window() -> None:
    assert_acquiring(PulseTracker(window_s=25.0, min_seconds=25.0).reading())


@pytest.mark.parametrize("fs_hz", [9.5, 10.0])
def test_tracker_accepts_a_sample_rate_just_above_the_floor(fs_hz: float) -> None:
    assert_acquiring(PulseTracker(fs_hz=fs_hz).reading())


SKIN = (145.0, 115.0, 100.0)


@pytest.mark.parametrize(
    ("timestamp_ms", "regions", "code"),
    [
        (math.nan, same_colour_everywhere(SKIN), "BAD_TIMESTAMPS"),
        (math.inf, same_colour_everywhere(SKIN), "BAD_TIMESTAMPS"),
        (
            1000.0,
            same_colour_except(SKIN, "forehead", (145.0, math.nan, 100.0)),
            "BAD_VALUES",
        ),
        (
            1000.0,
            same_colour_except(SKIN, "left_cheek", (145.0, 115.0, math.inf)),
            "BAD_VALUES",
        ),
        (1000.0, same_colour_except(SKIN, "right_cheek", (145.0, 115.0)), "BAD_VALUES"),
    ],
    ids=["nan_time", "inf_time", "nan_forehead", "inf_left_cheek", "short_right_cheek"],
)
def test_add_rejects_bad_samples_with_a_coded_error(
    timestamp_ms: float, regions: RegionColours, code: str
) -> None:
    tracker = PulseTracker()

    with pytest.raises(SignalError) as caught:
        tracker.add(timestamp_ms, regions)

    assert caught.value.code == code
    assert caught.value.message
    assert caught.value.action


@pytest.mark.parametrize("region", ["forehead", "left_cheek", "right_cheek"])
def test_bad_values_from_add_name_the_failing_region(region: str) -> None:
    tracker = PulseTracker()

    with pytest.raises(SignalError) as caught:
        tracker.add(1000.0, same_colour_except(SKIN, region, (145.0, math.nan, 100.0)))

    assert caught.value.code == "BAD_VALUES"
    assert region in caught.value.message
    others = {"forehead", "left_cheek", "right_cheek"} - {region}
    assert all(other not in caught.value.message for other in others)
