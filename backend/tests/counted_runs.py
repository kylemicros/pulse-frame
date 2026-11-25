from collections.abc import Callable, Sequence
from functools import cache

import numpy as np
from numpy.typing import NDArray

from pulse_frame.signal.beats import Interval, IntervalFlag
from pulse_frame.signal.hrv import WindowCheck
from pulse_frame.signal.tracker import RegionColours
from pulse_frame.store.recording import FrameSample
from pulse_frame.tools import replay
from pulse_frame.tools.replay import ReplayResult
from tests.frames import SEED, TRUE_BPM
from tests.signal.beat_synthetic import beat_recording
from tests.signal.beat_synthetic import chain as beat_chain
from tests.signal.hrv_tracking import seconds_of
from tests.signal.synthetic import Recording
from tests.tools.replay_support import face_lost_recording

WARM_UP_S = 60.0
NOISE_SEED = SEED + 7
CLEAN_SD = 0.0
NEAR_FLOOR_SD = 0.185
UNDER_FLOOR_SD = 0.3
TOO_WEAK_SD = 0.5
RUN_S = 150.0
TWO_MINUTES_RUN_S = 200.0
HOLED_RUN_S = 90.0
HOLE_S = 0.4
HOLES_AT_S = (50.0, 70.0)
COUNTED_HOLES_AT_S = (80.0, 100.0)
LONG_RUN_S = 340.0
LONG_HOLES_AT_S = (100.0, 200.0, 300.0)
CLEAR_UNTIL_S = 170.0
FADING_RUN_S = 300.0
FACE_LOSS_EVERY_S = 15.0
CHECK_STEP_MS = 1_000.0
HALF_RATE_IBI_MS = 2.0 * 60_000.0 / TRUE_BPM
RAMP_SWING_MS = 20.0
RAMP_SPAN_MS = 120_000.0
STRONG_CHECK_DB = 10.0
BETWEEN_FLOORS_DB = 1.5
BETWEEN_FLOORS_IBI_MS = 1_000.0
BETWEEN_FLOORS_BEATS = 70
BETWEEN_FLOORS_END_MS = 400_000.0


def noisy(noise_sd: float, duration_s: float) -> Recording:
    recording, _ = beat_recording(TRUE_BPM, SEED, duration_s)
    rng = np.random.default_rng(NOISE_SEED)
    noise = rng.normal(0.0, noise_sd, recording.regions.shape)
    return Recording(recording.timestamps_ms, recording.regions + noise)


def fading(clear_s: float, noise_sd: float, duration_s: float) -> Recording:
    recording = noisy(noise_sd, duration_s)
    clean = noisy(CLEAN_SD, duration_s)
    clear = seconds_of(recording) < clear_s
    regions = np.where(clear[:, None, None], clean.regions, recording.regions)
    return Recording(recording.timestamps_ms, regions)


def without(recording: Recording, drop: NDArray[np.bool_]) -> Recording:
    return Recording(recording.timestamps_ms[~drop], recording.regions[~drop])


def holed(duration_s: float, holes_at_s: Sequence[float] = HOLES_AT_S) -> Recording:
    recording = noisy(CLEAN_SD, duration_s)
    seconds = seconds_of(recording)
    in_hole = np.zeros(seconds.size, dtype=np.bool_)
    for at_s in holes_at_s:
        in_hole |= (seconds >= at_s) & (seconds < at_s + HOLE_S)
    return without(recording, in_hole)


WARMED_UP_RUNS: dict[str, Callable[[], Recording]] = {
    "clean": lambda: noisy(CLEAN_SD, RUN_S),
    "clean_two_counted_minutes": lambda: noisy(CLEAN_SD, TWO_MINUTES_RUN_S),
    "some_windows_clear": lambda: noisy(NEAR_FLOOR_SD, RUN_S),
    "no_window_clears": lambda: noisy(UNDER_FLOOR_SD, RUN_S),
    "too_weak": lambda: noisy(TOO_WEAK_SD, RUN_S),
    "face_left_view": lambda: face_lost_recording(RUN_S, FACE_LOSS_EVERY_S),
    "holes_in_the_counted_part": lambda: holed(RUN_S, COUNTED_HOLES_AT_S),
    "over_the_window_with_holes": lambda: holed(LONG_RUN_S, LONG_HOLES_AT_S),
    "reading_then_under_the_floor": lambda: fading(
        CLEAR_UNTIL_S, UNDER_FLOOR_SD, FADING_RUN_S
    ),
}


def whole_ms(recording: Recording) -> list[int]:
    return [int(t) for t in np.round(recording.timestamps_ms).astype(np.int64)]


def frame_samples(recording: Recording) -> list[FrameSample]:
    return [
        FrameSample(
            t_ms=t_ms,
            forehead=colours.forehead,
            left_cheek=colours.left_cheek,
            right_cheek=colours.right_cheek,
            moving=False,
        )
        for t_ms, colours in frames_of(recording)
    ]


def counted_from_ms(recording: Recording) -> int:
    return whole_ms(recording)[0] + round(WARM_UP_S * 1000.0)


def chain(
    ibis_ms: Sequence[float], end_ms: float, flag: IntervalFlag = "ok"
) -> list[Interval]:
    start_ms = end_ms - float(np.sum(ibis_ms))
    return beat_chain(ibis_ms, start_ms, [flag] * len(ibis_ms))


def hand_checks(snrs: Sequence[float], first_ms: float = 0.0) -> list[WindowCheck]:
    return [
        WindowCheck(t_ms=first_ms + index * CHECK_STEP_MS, snr_db=snr)
        for index, snr in enumerate(snrs)
    ]


@cache
def replayed(kind: str) -> ReplayResult:
    recording = WARMED_UP_RUNS[kind]()
    return replay.replay_samples(frame_samples(recording), counted_from_ms(recording))


def frames_of(recording: Recording) -> list[tuple[int, RegionColours]]:
    return [
        (t_ms, colours)
        for t_ms, (_, colours) in zip(
            whole_ms(recording), recording.samples(), strict=True
        )
    ]


def ramped(ibi_ms: float, end_ms: float) -> tuple[list[Interval], list[WindowCheck]]:
    count = int(RAMP_SPAN_MS // ibi_ms)
    ibis = np.linspace(ibi_ms - RAMP_SWING_MS, ibi_ms + RAMP_SWING_MS, count)
    check_count = int(RAMP_SPAN_MS // CHECK_STEP_MS) + 1
    checks = hand_checks([STRONG_CHECK_DB] * check_count, end_ms - RAMP_SPAN_MS)
    return chain(ibis.tolist(), end_ms), checks


def heart_rate_under_the_reading_floor() -> tuple[
    list[Interval], list[WindowCheck], float
]:
    ibis = np.linspace(
        BETWEEN_FLOORS_IBI_MS - RAMP_SWING_MS,
        BETWEEN_FLOORS_IBI_MS + RAMP_SWING_MS,
        BETWEEN_FLOORS_BEATS,
    )
    intervals = chain(ibis.tolist(), BETWEEN_FLOORS_END_MS)
    first_ms = intervals[0].start_ms
    count = int((BETWEEN_FLOORS_END_MS - first_ms) // CHECK_STEP_MS) + 1
    checks = hand_checks([BETWEEN_FLOORS_DB] * count, first_ms)
    return intervals, checks, checks[-1].t_ms
