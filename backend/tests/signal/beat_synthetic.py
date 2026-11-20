from collections.abc import Callable, Sequence
from itertools import pairwise

import numpy as np
from numpy.typing import NDArray
from scipy.interpolate import PchipInterpolator

from pulse_frame.signal.beats import Interval, IntervalFlag
from tests.signal.synthetic import (
    CLOCK_START_MS,
    FPS,
    HARMONIC_RATIO,
    MOTION_STEP_GAIN,
    NOISE_SD,
    REGION_DC,
    Recording,
    in_band,
    skin_rgb_from_wave,
    webcam_timestamps,
)

type BloodVolume = Callable[[NDArray[np.float64]], NDArray[np.float64]]

RESPIRATION_HZ = 0.25
RESPIRATION_SWING_MS = 50.0
SWING_SHARE = 0.06
BEAT_LEAD_MS = 3_000.0
SECOND_HARMONIC = 0.2
FRAME_MS = 1000.0 / FPS
TRACKER_NOISE_SD = 0.01
UPSTROKE_SHARE = 0.18
DECAY_SHARE = 0.3
DIASTOLIC_BUMP = 0.15
DIASTOLIC_BUMP_AT = 0.45
DIASTOLIC_BUMP_WIDTH = 0.12
SYSTOLIC_WIDTH = 0.07
DIASTOLIC_WAVE_WIDTH = 0.1
MIDPOINT_GRID_MS = 0.25
SUITE_PULSE_SD = float(np.sqrt(0.5 * (1.0 + HARMONIC_RATIO**2)))


def known_beats(
    bpm: float,
    duration_s: float,
    start_ms: float = CLOCK_START_MS,
    swing_ms: float = RESPIRATION_SWING_MS,
) -> NDArray[np.float64]:
    base_ms = 60_000.0 / bpm
    end_ms = start_ms + duration_s * 1000.0 + BEAT_LEAD_MS
    beats = [start_ms - BEAT_LEAD_MS]
    while beats[-1] < end_ms:
        since_s = (beats[-1] - start_ms) / 1000.0
        beats.append(
            beats[-1]
            + base_ms
            + swing_ms * np.sin(2.0 * np.pi * RESPIRATION_HZ * since_s)
        )
    return np.array(beats)


def frame_times(
    duration_s: float, start_ms: float = CLOCK_START_MS
) -> NDArray[np.float64]:
    return start_ms + np.arange(int(duration_s * FPS)) * FRAME_MS


def beats_inside(
    beats_ms: NDArray[np.float64], first_ms: float, last_ms: float
) -> NDArray[np.float64]:
    return beats_ms[(beats_ms > first_ms) & (beats_ms < last_ms)]


def nearest_errors(
    found_ms: NDArray[np.float64], truth_ms: NDArray[np.float64]
) -> NDArray[np.float64]:
    nearest = np.abs(found_ms[None, :] - truth_ms[:, None]).argmin(axis=1)
    return found_ms[nearest] - truth_ms


def period_ms(bpm: float) -> float:
    return 60_000.0 / bpm


def rmssd(ibis_ms: Sequence[float]) -> float:
    return float(np.sqrt(np.mean(np.diff(np.asarray(ibis_ms)) ** 2)))


def sdnn(ibis_ms: Sequence[float]) -> float:
    return float(np.std(np.asarray(ibis_ms), ddof=1))


def chain(
    ibis_ms: Sequence[float],
    start_ms: float = CLOCK_START_MS,
    flags: Sequence[IntervalFlag] | None = None,
) -> list[Interval]:
    edges = start_ms + np.concatenate(([0.0], np.cumsum(ibis_ms)))
    marks = flags or ["ok"] * len(ibis_ms)
    return [
        Interval(start_ms=float(s), end_ms=float(e), flag=f)
        for s, e, f in zip(edges[:-1], edges[1:], marks, strict=True)
    ]


def in_band_noise(
    rng: np.random.Generator, count: int, sd: float
) -> NDArray[np.float64]:
    noise = in_band(rng.standard_normal(count))
    return sd * noise / noise.std()


def respiring_ibis(
    count: int, base_ms: float = 800.0, swing_ms: float = 40.0
) -> list[float]:
    elapsed_s = np.cumsum(np.full(count, base_ms)) / 1000.0
    return list(base_ms + swing_ms * np.sin(2.0 * np.pi * RESPIRATION_HZ * elapsed_s))


def jittered_ibis(
    rng: np.random.Generator,
    count: int,
    base_ms: float,
    jitter_ms: float,
    offset_ms: float = 0.0,
    swing_ms: float = 40.0,
) -> list[float]:
    halves = np.where(np.arange(count) % 2 == 0, 0.5, -0.5)
    breathing = respiring_ibis(count, base_ms=base_ms, swing_ms=swing_ms)
    true_ibis = np.asarray(breathing) + offset_ms * halves
    beats = np.concatenate(([0.0], np.cumsum(true_ibis)))
    return list(np.diff(beats + rng.normal(0.0, jitter_ms, beats.size)))


def beat_cycles(
    times_ms: NDArray[np.float64], beats_ms: NDArray[np.float64]
) -> NDArray[np.float64]:
    return PchipInterpolator(beats_ms, np.arange(beats_ms.size, dtype=np.float64))(
        times_ms
    )


def asymmetric_blood_volume(cycles: NDArray[np.float64]) -> NDArray[np.float64]:
    since = np.mod(cycles + UPSTROKE_SHARE, 1.0)
    floor = np.exp(-(1.0 - UPSTROKE_SHARE) / DECAY_SHARE)
    rise = floor + (1.0 - floor) * 0.5 * (1.0 - np.cos(np.pi * since / UPSTROKE_SHARE))
    decay = np.exp(-(since - UPSTROKE_SHARE) / DECAY_SHARE)
    bump = DIASTOLIC_BUMP * np.exp(
        -0.5 * ((since - DIASTOLIC_BUMP_AT) / DIASTOLIC_BUMP_WIDTH) ** 2
    )
    return np.where(since < UPSTROKE_SHARE, rise, decay) + bump


def rounded_blood_volume(cycles: NDArray[np.float64]) -> NDArray[np.float64]:
    angle = 2.0 * np.pi * cycles
    return np.cos(angle) + SECOND_HARMONIC * np.cos(2.0 * angle)


def two_peak_blood_volume(diastolic: float, at: float) -> BloodVolume:
    def shape(cycles: NDArray[np.float64]) -> NDArray[np.float64]:
        since = np.mod(cycles + 0.5, 1.0) - 0.5
        systolic = np.exp(-0.5 * (since / SYSTOLIC_WIDTH) ** 2)
        later = np.mod(since - at + 0.5, 1.0) - 0.5
        wave = diastolic * np.exp(-0.5 * (later / DIASTOLIC_WAVE_WIDTH) ** 2)
        return systolic + wave

    return shape


def late_wave_blood_volume(
    diastolic: float, at: float, from_cycle: float
) -> BloodVolume:
    single = two_peak_blood_volume(0.0, at)
    double = two_peak_blood_volume(diastolic, at)

    def shape(cycles: NDArray[np.float64]) -> NDArray[np.float64]:
        return np.where(cycles >= from_cycle, double(cycles), single(cycles))

    return shape


def cycle_at(bpm: float, seconds: float) -> float:
    return (seconds * 1000.0 + BEAT_LEAD_MS) * bpm / 60_000.0


def reflected_light_wave(blood: NDArray[np.float64]) -> NDArray[np.float64]:
    centred = blood - blood.mean()
    return -SUITE_PULSE_SD * centred / centred.std()


def rate_scaled_swing_ms(bpm: float) -> float:
    return SWING_SHARE * 60_000.0 / bpm


def physical_recording(
    bpm: float,
    seed: int,
    duration_s: float,
    noise_sd: float = NOISE_SD,
    shape: BloodVolume = asymmetric_blood_volume,
    gain_steps: Sequence[tuple[float, float]] = (),
) -> tuple[Recording, NDArray[np.float64]]:
    rng = np.random.default_rng(seed)
    timestamps = webcam_timestamps(rng, duration_s)
    beats = known_beats(
        bpm,
        duration_s,
        start_ms=float(timestamps[0]),
        swing_ms=rate_scaled_swing_ms(bpm),
    )
    seconds = (timestamps - timestamps[0]) / 1000.0
    wave = reflected_light_wave(shape(beat_cycles(timestamps, beats)))
    regions = np.stack(
        [
            skin_rgb_from_wave(
                rng, seconds, wave, noise_sd=noise_sd, motion_step=False, skin_dc=dc
            )
            for dc in REGION_DC
        ],
        axis=1,
    )
    for from_s, to_s in gain_steps:
        stepped = (seconds >= from_s) & (seconds < to_s)
        regions[stepped] *= MOTION_STEP_GAIN
    return Recording(timestamps, regions), beats


def beat_recording(
    bpm: float, seed: int, duration_s: float, noise_sd: float = TRACKER_NOISE_SD
) -> tuple[Recording, NDArray[np.float64]]:
    return physical_recording(
        bpm, seed, duration_s, noise_sd=noise_sd, shape=rounded_blood_volume
    )


def systolic_midpoints(
    beats_ms: NDArray[np.float64], shape: BloodVolume
) -> NDArray[np.float64]:
    grid = np.arange(beats_ms[0], beats_ms[-1] + MIDPOINT_GRID_MS, MIDPOINT_GRID_MS)
    blood = shape(beat_cycles(grid, beats_ms))
    midpoints = []
    for previous_ms, beat_ms in pairwise(beats_ms):
        rising = (grid >= 0.5 * (previous_ms + beat_ms)) & (grid <= beat_ms)
        times = grid[rising]
        values = blood[rising]
        foot = int(np.argmin(values))
        level = 0.5 * (values[foot] + values[foot:].max())
        above = foot + int(np.argmax(values[foot:] >= level))
        midpoints.append(
            np.interp(
                level, values[above - 1 : above + 1], times[above - 1 : above + 1]
            ),
        )
    return np.array(midpoints)
