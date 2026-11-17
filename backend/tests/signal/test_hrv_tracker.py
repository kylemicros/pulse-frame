import numpy as np
import pytest
from numpy.typing import NDArray

from pulse_frame.signal.beats import Interval
from pulse_frame.signal.hrv import HrvTracker
from tests.frames import SEED, TRUE_BPM
from tests.signal.beat_synthetic import (
    RESPIRATION_HZ,
    TRACKER_NOISE_SD,
    beat_recording,
    beats_inside,
    nearest_errors,
    physical_recording,
    rmssd,
    sdnn,
)
from tests.signal.hrv_tracking import (
    accepted,
    beat_times,
    elapsed_ms,
    feed,
    hrv_errors,
    is_null,
    seconds_of,
    tracked,
    true_ibis_inside,
)
from tests.signal.synthetic import Recording

DURATION_S = 90.0
SHORT_S = 50.0
HRV_TOLERANCE_MS = 3.0
ACCEPTED_SHARE = 0.8
BEAT_MATCH_MS = 100.0
MOTION_AT_S = 45.35
LOW_FROM_S = 30.0
LOW_TO_S = 33.0
GAP_FROM_S = 45.0
GAP_S = 2.0
EARLY_S = 70.0
LATER_S = 80.0
STABLE_MS = 1.0
TRACKER_SEEDS = [0, 1, 2]
PHYSICAL_S = 120.0
SIGN_RATES_BPM = [50.0, 60.0]
SUITE_NOISE_SD = 0.05
NOISE_DOMINATED_TOLERANCE_MS = 15.0
SWEEP_TOLERANCE_MS = {50.0: 5.0, 60.0: 3.0, 110.0: 3.0}
PEAK_OFFSET_LIMIT_MS = 40.0
TOO_FAST_BPM = 200.0
EDGE_MS = 3_000.0
UPDATE_MS = 1_000.0
SETTLED_DEVIATION_MS = 8.0
SETTLING_BPM = 50.0
SETTLING_NOISE_SD = 0.005
WINDOW_MS = 300_000.0
LONG_S = 330.0
SLOW_BPM = 40.0
QUARTER_HZ = 0.25
SLOW_TOLERANCE_MS = 8.0
WARM_UP_MS = 30_000.0
LATEST_SETTLED_MS = 100.0
EARLIEST_SETTLED_MS = 1_400.0
YOUNG_SEGMENT_S = 14.0
BEFORE_GAP_S = 30.0
YOUNG_SEGMENT_MIN_ACCEPTED = 5


def true_ibis_over(
    beats: NDArray[np.float64], kept: list[Interval]
) -> NDArray[np.float64]:
    span = beats_inside(
        beats, kept[0].start_ms - BEAT_MATCH_MS, kept[-1].end_ms + BEAT_MATCH_MS
    )
    return np.diff(span)


@pytest.mark.parametrize("seed", TRACKER_SEEDS)
def test_ninety_seconds_of_clean_pulse_give_rmssd_and_sdnn_near_the_truth(
    seed: int,
) -> None:
    recording, beats = beat_recording(TRUE_BPM, SEED + seed, DURATION_S)
    tracker = HrvTracker()

    feed(tracker, recording)

    kept = accepted(tracker.intervals())
    truth = true_ibis_over(beats, kept)
    reading = tracker.reading()
    assert len(kept) >= ACCEPTED_SHARE * truth.size
    assert reading.rmssd_ms == pytest.approx(rmssd(truth), abs=HRV_TOLERANCE_MS)
    assert reading.sdnn_ms == pytest.approx(sdnn(truth), abs=HRV_TOLERANCE_MS)


@pytest.mark.parametrize("bpm", SIGN_RATES_BPM)
@pytest.mark.parametrize("seed", TRACKER_SEEDS)
def test_more_blood_less_light_pulse_at_suite_noise_gives_hrv_near_the_truth(
    bpm: float, seed: int
) -> None:
    recording, beats = physical_recording(
        bpm, SEED + seed, PHYSICAL_S, noise_sd=SUITE_NOISE_SD
    )

    reading = tracked(recording).reading()

    rmssd_error, sdnn_error = hrv_errors(reading, true_ibis_inside(recording, beats))
    assert rmssd_error <= NOISE_DOMINATED_TOLERANCE_MS
    assert sdnn_error <= NOISE_DOMINATED_TOLERANCE_MS


@pytest.mark.parametrize("bpm", SIGN_RATES_BPM)
def test_beats_sit_on_the_blood_volume_peak_not_the_pulse_foot(bpm: float) -> None:
    recording, beats = physical_recording(
        bpm, SEED, PHYSICAL_S, noise_sd=TRACKER_NOISE_SD
    )

    found = beat_times(accepted(tracked(recording).intervals()))

    assert found.size > 0.8 * PHYSICAL_S * bpm / 60.0
    assert abs(np.median(nearest_errors(beats, found))) <= PEAK_OFFSET_LIMIT_MS


@pytest.mark.parametrize("bpm", list(SWEEP_TOLERANCE_MS))
@pytest.mark.parametrize("seed", TRACKER_SEEDS)
def test_rmssd_and_sdnn_near_the_truth_from_fifty_to_one_hundred_ten_bpm(
    bpm: float, seed: int
) -> None:
    recording, beats = physical_recording(
        bpm, SEED + seed, PHYSICAL_S, noise_sd=TRACKER_NOISE_SD
    )

    reading = tracked(recording).reading()

    rmssd_error, sdnn_error = hrv_errors(reading, true_ibis_inside(recording, beats))
    assert rmssd_error <= SWEEP_TOLERANCE_MS[bpm]
    assert sdnn_error <= SWEEP_TOLERANCE_MS[bpm]


@pytest.mark.parametrize("seed", TRACKER_SEEDS)
def test_forty_bpm_breathing_at_a_quarter_hertz_still_gives_a_reading(
    seed: int,
) -> None:
    recording, beats = physical_recording(
        SLOW_BPM, SEED + seed, PHYSICAL_S, noise_sd=TRACKER_NOISE_SD
    )
    assert RESPIRATION_HZ == QUARTER_HZ

    reading = tracked(recording).reading()

    rmssd_error, sdnn_error = hrv_errors(reading, true_ibis_inside(recording, beats))
    assert rmssd_error <= SLOW_TOLERANCE_MS
    assert sdnn_error <= SLOW_TOLERANCE_MS


def test_no_reading_above_about_one_hundred_ninety_bpm() -> None:
    recording, _ = physical_recording(
        TOO_FAST_BPM, SEED, DURATION_S, noise_sd=TRACKER_NOISE_SD
    )

    assert is_null(tracked(recording).reading())


def test_fifty_seconds_of_clean_pulse_are_not_enough_for_a_reading() -> None:
    recording, _ = beat_recording(TRUE_BPM, SEED, SHORT_S)
    tracker = HrvTracker()

    feed(tracker, recording)

    assert len(accepted(tracker.intervals())) > 0
    assert tracker.reading().rmssd_ms is None
    assert tracker.reading().sdnn_ms is None


def test_a_new_tracker_has_no_intervals_and_a_null_reading() -> None:
    tracker = HrvTracker()

    assert tracker.intervals() == []
    assert tracker.reading().rmssd_ms is None
    assert tracker.reading().sdnn_ms is None


def test_a_motion_flagged_frame_rejects_only_the_beats_around_it() -> None:
    recording, _ = beat_recording(TRUE_BPM, SEED, DURATION_S)
    moving = np.zeros(recording.timestamps_ms.size, dtype=np.bool_)
    motion_index = int(
        np.argmin(np.abs(recording.timestamps_ms - elapsed_ms(recording, MOTION_AT_S)))
    )
    moving[motion_index] = True
    motion_ms = float(recording.timestamps_ms[motion_index])
    tracker = HrvTracker()

    feed(tracker, recording, moving=moving)

    intervals = tracker.intervals()
    touching = [i for i in intervals if i.start_ms <= motion_ms <= i.end_ms]
    assert [i.flag for i in touching] == ["motion"]
    assert len(accepted(intervals)) >= ACCEPTED_SHARE * (len(intervals) - 1)
    assert tracker.reading().rmssd_ms is not None


def test_a_low_quality_span_rejects_every_beat_that_touches_it() -> None:
    recording, _ = beat_recording(TRUE_BPM, SEED, DURATION_S)
    seconds = seconds_of(recording)
    low = (seconds >= LOW_FROM_S) & (seconds <= LOW_TO_S)
    low_from = float(recording.timestamps_ms[low][0])
    low_to = float(recording.timestamps_ms[low][-1])
    tracker = HrvTracker()

    feed(tracker, recording, low_quality=low)

    touching = [
        i for i in tracker.intervals() if i.start_ms <= low_to and i.end_ms >= low_from
    ]
    assert len(touching) >= 3
    assert {i.flag for i in touching} == {"low_quality"}


def gapped_recording(
    whole: Recording, gap_from_s: float
) -> tuple[Recording, float, float]:
    seconds = seconds_of(whole)
    keep = (seconds < gap_from_s) | (seconds >= gap_from_s + GAP_S)
    recording = Recording(whole.timestamps_ms[keep], whole.regions[keep])
    gap_from = float(whole.timestamps_ms[seconds < gap_from_s][-1])
    gap_to = float(whole.timestamps_ms[seconds >= gap_from_s + GAP_S][0])
    return recording, gap_from, gap_to


def ninety_seconds_with_a_gap() -> tuple[Recording, float, float]:
    whole, _ = beat_recording(TRUE_BPM, SEED, DURATION_S + GAP_S)
    return gapped_recording(whole, GAP_FROM_S)


def test_no_accepted_interval_spans_a_gap_and_beats_either_side_still_count() -> None:
    recording, gap_from, gap_to = ninety_seconds_with_a_gap()
    tracker = HrvTracker()

    feed(tracker, recording)

    kept = accepted(tracker.intervals())
    assert not [i for i in kept if i.start_ms < gap_to and i.end_ms > gap_from]
    assert [i for i in kept if i.end_ms <= gap_from]
    assert [i for i in kept if i.start_ms >= gap_to]
    assert tracker.reading().rmssd_ms is not None


def test_no_beat_is_kept_within_three_seconds_either_side_of_a_gap() -> None:
    recording, gap_from, gap_to = ninety_seconds_with_a_gap()

    beats = beat_times(tracked(recording).intervals())

    before_gap = (beats > gap_from - EDGE_MS) & (beats <= gap_from)
    after_gap = (beats >= gap_to) & (beats < gap_to + EDGE_MS)
    assert beats[beats < gap_from - EDGE_MS].size > 0
    assert beats[beats > gap_to + EDGE_MS].size > 0
    assert beats[before_gap | after_gap].tolist() == []


def test_accepted_beats_do_not_move_when_newer_frames_arrive() -> None:
    whole, _ = beat_recording(TRUE_BPM, SEED, LATER_S)
    tracker = HrvTracker()
    feed(tracker, whole.until(EARLY_S))
    early = accepted(tracker.intervals())

    feed(tracker, whole.after(EARLY_S))

    later = accepted(tracker.intervals())
    later_starts = np.array([i.start_ms for i in later])
    later_ends = np.array([i.end_ms for i in later])
    assert len(early) > 50
    for interval in early:
        nearest = int(np.argmin(np.abs(later_starts - interval.start_ms)))
        assert later_starts[nearest] == pytest.approx(interval.start_ms, abs=STABLE_MS)
        assert later_ends[nearest] == pytest.approx(interval.end_ms, abs=STABLE_MS)


def test_intervals_ending_in_the_newest_three_seconds_are_not_accepted() -> None:
    recording, _ = physical_recording(
        TRUE_BPM, SEED, DURATION_S, noise_sd=TRACKER_NOISE_SD
    )

    intervals = tracked(recording).intervals()

    newest_ms = float(recording.timestamps_ms[-1])
    late = [i for i in intervals if i.end_ms > newest_ms - EDGE_MS]
    assert late
    assert accepted(late) == []


def test_intervals_ending_three_to_five_s_before_an_update_are_accepted() -> None:
    recording, _ = physical_recording(
        TRUE_BPM, SEED, DURATION_S, noise_sd=TRACKER_NOISE_SD
    )
    first_ms = float(recording.timestamps_ms[0])
    tracker = HrvTracker()
    previous = tracker.intervals()
    settled_after_updates: list[Interval] = []

    for timestamp_ms, regions in recording.samples():
        tracker.add(timestamp_ms, regions)
        current = tracker.intervals()
        if current != previous and timestamp_ms - first_ms > WARM_UP_MS:
            settled_after_updates.extend(
                i
                for i in current
                if timestamp_ms - EDGE_MS - EARLIEST_SETTLED_MS
                <= i.end_ms
                <= timestamp_ms - EDGE_MS - LATEST_SETTLED_MS
            )
        previous = current

    assert len(settled_after_updates) >= 30
    assert [i for i in settled_after_updates if not i.accepted] == []


def test_every_accepted_beat_sits_where_the_settled_signal_puts_it() -> None:
    recording, beats = physical_recording(
        SETTLING_BPM, SEED, DURATION_S, noise_sd=SETTLING_NOISE_SD
    )

    found = beat_times(accepted(tracked(recording).intervals()))

    errors = nearest_errors(beats, found)
    deviation = np.abs(errors - np.median(errors))
    assert found.size > 0.8 * DURATION_S * SETTLING_BPM / 60.0
    assert float(deviation.max()) <= SETTLED_DEVIATION_MS


def test_intervals_older_than_three_hundred_seconds_are_dropped() -> None:
    recording, _ = physical_recording(TRUE_BPM, SEED, LONG_S, noise_sd=TRACKER_NOISE_SD)

    intervals = tracked(recording).intervals()

    newest_ms = float(recording.timestamps_ms[-1])
    starts = np.array([i.start_ms for i in intervals])
    assert starts.min() >= newest_ms - WINDOW_MS
    assert starts.min() <= newest_ms - WINDOW_MS + 5_000.0


@pytest.mark.parametrize("seed", TRACKER_SEEDS)
def test_beats_are_accepted_within_fourteen_seconds_of_the_start(seed: int) -> None:
    recording, _ = physical_recording(
        TRUE_BPM, SEED + seed, YOUNG_SEGMENT_S, noise_sd=TRACKER_NOISE_SD
    )

    kept = accepted(tracked(recording).intervals())

    assert recording.timestamps_ms[-1] - recording.timestamps_ms[0] < 15_000.0
    assert len(kept) >= YOUNG_SEGMENT_MIN_ACCEPTED


@pytest.mark.parametrize("seed", TRACKER_SEEDS)
def test_beats_are_accepted_within_fourteen_seconds_after_a_gap(seed: int) -> None:
    whole, _ = physical_recording(
        TRUE_BPM,
        SEED + seed,
        BEFORE_GAP_S + GAP_S + YOUNG_SEGMENT_S,
        noise_sd=TRACKER_NOISE_SD,
    )
    recording, _, gap_to = gapped_recording(whole, BEFORE_GAP_S)

    kept = accepted(tracked(recording).intervals())

    after_gap = [i for i in kept if i.start_ms >= gap_to]
    assert recording.timestamps_ms[-1] - gap_to < 15_000.0
    assert len(after_gap) >= YOUNG_SEGMENT_MIN_ACCEPTED


def test_settled_intervals_are_the_committed_head_of_intervals_before_the_edge() -> (
    None
):
    recording, _ = beat_recording(TRUE_BPM, SEED, DURATION_S)
    tracker = tracked(recording)
    newest_ms = float(recording.timestamps_ms[-1])

    settled = tracker.settled_intervals()
    every = tracker.intervals()

    assert 0 < len(settled) < len(every)
    assert every[: len(settled)] == settled
    assert all(i.end_ms <= newest_ms - EDGE_MS for i in settled)
    assert all(i.flag != "edge" for i in settled)
    assert all(
        i.end_ms > newest_ms - EDGE_MS - UPDATE_MS for i in every[len(settled) :]
    )
