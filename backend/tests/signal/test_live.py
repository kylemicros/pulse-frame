import numpy as np
import pytest

from pulse_frame.signal import summary
from pulse_frame.signal.beats import FLAG_GUARD_MS
from pulse_frame.signal.live import COUNTED_AFTER_MS, LiveHrv
from pulse_frame.signal.tracker import UPDATE_INTERVAL_MS
from pulse_frame.tools import replay
from tests.counted_runs import (
    CLEAN_SD,
    TOO_WEAK_SD,
    WARMED_UP_RUNS,
    counted_from_ms,
    frame_samples,
    frames_of,
    noisy,
    replayed,
    whole_ms,
)
from tests.frames import TRUE_BPM
from tests.signal.synthetic import Recording

FIRST_MS = 1_000
FRAME_MS = 33
FACELESS_LEAD_FRAMES = 150
SHORT_COUNTED_RUN_S = 100.0
COUNTED_BEATS_LIMIT = 40.0 * TRUE_BPM / 60.0 + 1.0
FLOOR_CLEARED_RUN_S = 110.0
BPM_TOLERANCE = 1.0
STALE_RUN_S = 140.0
FACE_GONE_S = 12.0
WARM_UP_ONLY_S = 55.0
TICK_AFTER_S = 120.0
TICK_HOLE_MS = 400
TICK_RUN_S = 130.0
LONG_HOLE_RUN_S = 150.0
LONG_HOLE_AT_S = 100.0
LONG_HOLE_MS = 900


def fed(recording: Recording) -> LiveHrv:
    live = LiveHrv()
    for t_ms, colours in frames_of(recording):
        live.add(t_ms, colours, moving=False)
    return live


def test_counting_starts_sixty_seconds_after_the_first_frame_even_without_a_face() -> (
    None
):
    recording = noisy(CLEAN_SD, 10.0)
    live = LiveHrv()
    before = live.counted_from_ms

    for index in range(FACELESS_LEAD_FRAMES):
        live.add(FIRST_MS + index * FRAME_MS, None, moving=False)
    lead_ms = FIRST_MS + FACELESS_LEAD_FRAMES * FRAME_MS
    first_face_ms = whole_ms(recording)[0]
    for t_ms, colours in frames_of(recording):
        live.add(t_ms - first_face_ms + lead_ms, colours, moving=False)

    assert COUNTED_AFTER_MS == 60_000.0
    assert before is None
    assert live.counted_from_ms == FIRST_MS + COUNTED_AFTER_MS


@pytest.mark.parametrize("kind", list(WARMED_UP_RUNS), ids=list(WARMED_UP_RUNS))
def test_the_live_summary_and_decision_equal_the_replay_of_the_same_frames(
    kind: str,
) -> None:
    live = fed(WARMED_UP_RUNS[kind]())
    result = replayed(kind)
    replayed_summary = replay.summarise(result)

    assert live.summary() == replayed_summary
    assert live.no_reading() == summary.decide_no_reading(
        replayed_summary,
        result.window_checks,
        result.newest_ms,
        bool(result.readings),
    )


def test_warm_up_beats_never_enter_the_minute_summary() -> None:
    recording = noisy(CLEAN_SD, SHORT_COUNTED_RUN_S)
    uncounted = replay.summarise(replay.replay_samples(frame_samples(recording), 0))

    counted = fed(recording).summary()

    assert uncounted.bpm is not None
    assert counted.bpm is None
    assert 0 < counted.count <= COUNTED_BEATS_LIMIT


def test_a_counted_part_past_the_forty_five_second_floor_gives_the_minute_bpm() -> None:
    counted = fed(noisy(CLEAN_SD, FLOOR_CLEARED_RUN_S)).summary()

    assert counted.bpm == pytest.approx(TRUE_BPM, abs=BPM_TOLERANCE)


def test_a_face_gone_for_the_last_twelve_seconds_leaves_no_minute_bpm() -> None:
    recording = noisy(CLEAN_SD, STALE_RUN_S)
    live = fed(recording)
    with_face = live.summary()
    last_ms = whole_ms(recording)[-1]

    for t_ms in np.arange(1, int(FACE_GONE_S * 1000 / FRAME_MS)) * FRAME_MS:
        live.add(last_ms + int(t_ms), None, moving=False)

    gone = live.summary()
    assert with_face.bpm is not None
    assert gone.bpm is None
    assert gone.rmssd_ms is None
    assert live.no_reading() is None


def test_the_warm_up_alone_gives_no_no_reading_decision_however_weak() -> None:
    live = fed(noisy(TOO_WEAK_SD, WARM_UP_ONLY_S))

    assert live.no_reading() is None
    assert live.summary().count == 0


def update_indices(times_ms: list[int]) -> list[int]:
    ticks: list[int] = []
    next_ms = times_ms[0] + UPDATE_INTERVAL_MS
    for index, t_ms in enumerate(times_ms[1:], start=1):
        if t_ms >= next_ms:
            ticks.append(index)
            next_ms = t_ms + UPDATE_INTERVAL_MS
    return ticks


def cut_after_hole(recording: Recording, last_ms: int, hole_ms: int) -> Recording:
    times = np.array(whole_ms(recording))
    after = int(np.flatnonzero(times > last_ms + hole_ms)[0])
    keep = (times <= last_ms) | (np.arange(times.size) == after)
    keep[after + 1 :] = False
    return Recording(recording.timestamps_ms[keep], recording.regions[keep])


def holed_after(recording: Recording, at_s: float, hole_ms: int) -> Recording:
    times = np.array(whole_ms(recording))
    start = times[0] + at_s * 1000.0
    keep = (times < start) | (times > start + hole_ms)
    return Recording(recording.timestamps_ms[keep], recording.regions[keep])


def test_a_hole_just_after_an_update_tick_labels_as_the_replay_does() -> None:
    recording = noisy(CLEAN_SD, TICK_RUN_S)
    times = whole_ms(recording)
    tick_from_ms = times[0] + TICK_AFTER_S * 1000.0
    tick = next(i for i in update_indices(times) if times[i] >= tick_from_ms)
    cut = cut_after_hole(recording, times[tick], TICK_HOLE_MS)
    result = replay.replay_samples(frame_samples(cut), counted_from_ms(cut))
    replayed_summary = replay.summarise(result)

    live = fed(cut)

    assert live.summary() == replayed_summary
    assert live.no_reading() == summary.decide_no_reading(
        replayed_summary,
        result.window_checks,
        result.newest_ms,
        bool(result.readings),
    )


def test_both_samples_beside_a_hole_flag_the_intervals_near_them_low_quality() -> None:
    clean = noisy(CLEAN_SD, LONG_HOLE_RUN_S)
    recording = holed_after(clean, LONG_HOLE_AT_S, LONG_HOLE_MS)
    times = np.array(whole_ms(recording))
    after = int(np.flatnonzero(np.diff(times) > summary.SAMPLE_HOLE_MS)[0]) + 1
    before_ms, after_ms = float(times[after - 1]), float(times[after])

    intervals = fed(recording).intervals()

    near_before_only = [
        i
        for i in intervals
        if before_ms - FLAG_GUARD_MS <= i.end_ms < after_ms - FLAG_GUARD_MS
    ]
    touching = [
        i
        for i in intervals
        if i.start_ms <= after_ms + FLAG_GUARD_MS
        and i.end_ms >= before_ms - FLAG_GUARD_MS
    ]
    assert near_before_only
    assert {i.flag for i in near_before_only} == {"low_quality"}
    assert not any(i.accepted for i in touching)


def test_a_reading_that_came_out_keeps_a_later_sub_floor_stretch_from_a_decision() -> (
    None
):
    result = replayed("reading_then_under_the_floor")
    replayed_summary = replay.summarise(result)

    live = fed(WARMED_UP_RUNS["reading_then_under_the_floor"]())

    assert result.readings
    assert live.no_reading() is None
    assert (
        summary.decide_no_reading(
            replayed_summary, result.window_checks, result.newest_ms, False
        )
        is not None
    )
