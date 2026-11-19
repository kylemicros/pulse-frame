from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from pulse_frame.signal.beats import Interval
from tests.signal.synthetic import (
    MOTION_STEP_GAIN,
    PULSE_DEPTH,
    PULSE_SIGNATURE,
    RED_NOISE_SHARED,
    REGION_DC,
    Recording,
    in_band,
    red_noise,
    webcam_timestamps,
)

FACE_LEAD_MS = 4_000.0
SDNN_RANGE_MS = (32.0, 93.0)
RSA_HZ_RANGE = (0.15, 0.4)
RSA_VARIANCE_SHARE = 0.7
RISE_MS_RANGE = (130.0, 190.0)
RISE_VARIATION = 0.08
SYSTOLIC_POWER = 2.0
TEMPLATE_SPAN_MS = 1_600.0
DICROTIC_HEIGHT_RANGE = (0.2, 0.8)
DICROTIC_DELAY_MS_RANGE = (200.0, 320.0)
DICROTIC_WIDTH_MS_RANGE = (55.0, 90.0)
DICROTIC_VARIATION = 0.5
AMPLITUDE_VARIATION = 0.06
BREATH_AMPLITUDE_SWING = 0.1
REGION_OFFSET_LIMIT_MS = 20.0
REGION_SNR_OFFSETS_DB = (2.0, 0.0, -6.0)
WHITE_NOISE_SHARE = 0.3
SENSOR_NOISE_SD = 0.02
LIGHT_SWING = 0.03
LIGHT_SWING_HZ = 0.05
LIGHT_DRIFT_PER_S = 0.0005


@dataclass(frozen=True)
class Face:
    recording: Recording
    beats_ms: NDArray[np.float64]


@dataclass(frozen=True)
class BeatShapes:
    rise_ms: NDArray[np.float64]
    amplitude: NDArray[np.float64]


@dataclass(frozen=True)
class RegionShape:
    offset_ms: float
    dicrotic_height: float
    dicrotic_delay_ms: float
    dicrotic_width_ms: float


def unit_in_band(values: NDArray[np.float64]) -> NDArray[np.float64]:
    passed = in_band(values)
    return passed / passed.std()


def true_ibis(
    rng: np.random.Generator, bpm: float, count: int, sdnn_ms: float | None
) -> NDArray[np.float64]:
    drawn_ms = rng.uniform(*SDNN_RANGE_MS)
    spread_ms = drawn_ms if sdnn_ms is None else sdnn_ms
    breath_hz = rng.uniform(*RSA_HZ_RANGE)
    elapsed_s = np.arange(count) * 60.0 / bpm
    breathing = np.sqrt(2.0 * RSA_VARIANCE_SHARE) * np.sin(
        2.0 * np.pi * breath_hz * elapsed_s + rng.uniform(0.0, 2.0 * np.pi)
    )
    jitter = np.sqrt(1.0 - RSA_VARIANCE_SHARE) * rng.standard_normal(count)
    swings = breathing + jitter
    return 60_000.0 / bpm + spread_ms * (swings - swings.mean()) / swings.std(ddof=1)


def true_beats(
    rng: np.random.Generator,
    bpm: float,
    first_ms: float,
    last_ms: float,
    sdnn_ms: float | None,
) -> NDArray[np.float64]:
    span_ms = last_ms - first_ms + 2.0 * FACE_LEAD_MS
    count = int(np.ceil(span_ms * bpm / 60_000.0))
    ibis = true_ibis(rng, bpm, count, sdnn_ms)
    return first_ms - FACE_LEAD_MS + np.concatenate(([0.0], np.cumsum(ibis)))


def beat_shapes(rng: np.random.Generator, beats_ms: NDArray[np.float64]) -> BeatShapes:
    breath_hz = rng.uniform(*RSA_HZ_RANGE)
    seconds = (beats_ms - beats_ms[0]) / 1000.0
    breathing = BREATH_AMPLITUDE_SWING * np.sin(
        2.0 * np.pi * breath_hz * seconds + rng.uniform(0.0, 2.0 * np.pi)
    )
    rise_ms = rng.uniform(*RISE_MS_RANGE)
    return BeatShapes(
        rise_ms=rise_ms * (1.0 + RISE_VARIATION * rng.standard_normal(beats_ms.size)),
        amplitude=1.0
        + breathing
        + AMPLITUDE_VARIATION * rng.standard_normal(beats_ms.size),
    )


def region_shape(rng: np.random.Generator) -> RegionShape:
    return RegionShape(
        offset_ms=rng.uniform(-REGION_OFFSET_LIMIT_MS, REGION_OFFSET_LIMIT_MS),
        dicrotic_height=rng.uniform(*DICROTIC_HEIGHT_RANGE),
        dicrotic_delay_ms=rng.uniform(*DICROTIC_DELAY_MS_RANGE),
        dicrotic_width_ms=rng.uniform(*DICROTIC_WIDTH_MS_RANGE),
    )


def systolic_wave(since_ms: NDArray[np.float64], rise_ms: float) -> NDArray[np.float64]:
    share = np.clip(since_ms / rise_ms, 0.0, None)
    return share**SYSTOLIC_POWER * np.exp(SYSTOLIC_POWER * (1.0 - share))


def dicrotic_wave(
    since_ms: NDArray[np.float64], at_ms: float, width_ms: float
) -> NDArray[np.float64]:
    return np.exp(-0.5 * ((since_ms - at_ms) / width_ms) ** 2)


def blood_volume(
    rng: np.random.Generator,
    times_ms: NDArray[np.float64],
    beats_ms: NDArray[np.float64],
    shapes: BeatShapes,
    region: RegionShape,
) -> NDArray[np.float64]:
    blood = np.zeros(times_ms.size)
    heights = region.dicrotic_height * (
        1.0 + DICROTIC_VARIATION * rng.standard_normal(beats_ms.size)
    )
    for beat_ms, rise_ms, amplitude, height in zip(
        beats_ms, shapes.rise_ms, shapes.amplitude, heights, strict=True
    ):
        start_ms = beat_ms + region.offset_ms
        near = (times_ms >= start_ms) & (times_ms < start_ms + TEMPLATE_SPAN_MS)
        since_ms = times_ms[near] - start_ms
        dicrotic_at_ms = rise_ms + region.dicrotic_delay_ms
        blood[near] += amplitude * (
            systolic_wave(since_ms, rise_ms)
            + height * dicrotic_wave(since_ms, dicrotic_at_ms, region.dicrotic_width_ms)
        )
    return blood


def red_in_band_noise(rng: np.random.Generator, count: int) -> NDArray[np.float64]:
    red = unit_in_band(red_noise(rng, count))
    white = unit_in_band(rng.standard_normal(count))
    return np.sqrt(1.0 - WHITE_NOISE_SHARE) * red + np.sqrt(WHITE_NOISE_SHARE) * white


def skin_colours(
    rng: np.random.Generator,
    seconds: NDArray[np.float64],
    light: NDArray[np.float64],
    dc: NDArray[np.float64],
) -> NDArray[np.float64]:
    lighting = (
        1.0
        + LIGHT_SWING * np.sin(2.0 * np.pi * LIGHT_SWING_HZ * seconds)
        + LIGHT_DRIFT_PER_S * seconds
    )
    modulation = 1.0 + PULSE_DEPTH * np.outer(light, PULSE_SIGNATURE)
    clean = dc * modulation * lighting[:, None]
    return clean + rng.normal(0.0, SENSOR_NOISE_SD, clean.shape)


def region_noise(rng: np.random.Generator, count: int) -> list[NDArray[np.float64]]:
    shared = red_in_band_noise(rng, count)
    return [
        np.sqrt(1.0 - RED_NOISE_SHARED) * red_in_band_noise(rng, count)
        + np.sqrt(RED_NOISE_SHARED) * shared
        for _ in REGION_DC
    ]


def realistic_face(
    bpm: float,
    face_snr_db: float,
    seed: int,
    duration_s: float,
    pulseless_regions: tuple[int, ...] = (),
    sdnn_ms: float | None = None,
    step_at_s: float | None = None,
) -> Face:
    rng = np.random.default_rng(seed)
    timestamps = webcam_timestamps(rng, duration_s)
    seconds = (timestamps - timestamps[0]) / 1000.0
    beats = true_beats(rng, bpm, float(timestamps[0]), float(timestamps[-1]), sdnn_ms)
    shapes = beat_shapes(rng, beats)
    snrs = face_snr_db + rng.permutation(REGION_SNR_OFFSETS_DB)
    noises = region_noise(rng, timestamps.size)
    colours = []
    for index, (snr, dc, noise) in enumerate(zip(snrs, REGION_DC, noises, strict=True)):
        blood = blood_volume(rng, timestamps, beats, shapes, region_shape(rng))
        light = -(blood - blood.mean()) / blood.std()
        scaled = noise * np.sqrt(in_band(light).var() / 10.0 ** (snr / 10.0))
        pulse = np.zeros_like(light) if index in pulseless_regions else light
        colours.append(skin_colours(rng, seconds, pulse + scaled, dc))
    regions = np.stack(colours, axis=1)
    if step_at_s is not None:
        regions[seconds >= step_at_s] *= MOTION_STEP_GAIN
    return Face(recording=Recording(timestamps, regions), beats_ms=beats)


def nearest_indices(
    times_ms: NDArray[np.float64], truth_ms: NDArray[np.float64]
) -> NDArray[np.intp]:
    return np.abs(times_ms[:, None] - truth_ms[None, :]).argmin(axis=1)


def matched_ibi_errors(
    intervals: list[Interval], truth_ms: NDArray[np.float64]
) -> NDArray[np.float64]:
    if not intervals:
        return np.empty(0)
    starts = np.array([i.start_ms for i in intervals])
    ends = np.array([i.end_ms for i in intervals])
    edges = np.concatenate((starts, ends))
    offset_ms = float(np.median(edges - truth_ms[nearest_indices(edges, truth_ms)]))
    first = nearest_indices(starts - offset_ms, truth_ms)
    return (ends - starts) - (truth_ms[first + 1] - truth_ms[first])
