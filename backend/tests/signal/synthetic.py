from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Self

import numpy as np
from numpy.typing import NDArray
from scipy.signal import butter, sosfiltfilt

from pulse_frame.signal.tracker import RegionColours

SKIN_DC = np.array([145.0, 115.0, 100.0])
REGION_DC = np.array(
    [[150.0, 118.0, 102.0], [145.0, 115.0, 100.0], [141.0, 112.0, 97.0]]
)
PULSE_SIGNATURE = np.array([0.33, 0.77, 0.53])
PULSE_DEPTH = 0.004
NOISE_SD = 0.05
HARMONIC_RATIO = 0.25
HARMONIC_PHASE = 0.7
CLOCK_START_MS = 123_456.7
MOTION_STEP_AT_S = 8.0
MOTION_STEP_GAIN = np.array([1.05, 1.04, 1.035])
JITTER_SD_MS = 3.0
JITTER_LIMIT_MS = 10.0
FPS = 30.0
REGION_COUNT = 3

RED_SKIN_DC = np.array([160.0, 110.0, 92.0])
RED_PULSE_SIGNATURE = PULSE_SIGNATURE / PULSE_SIGNATURE[1]
RED_NOISE_SLOPE = 3.3
RED_NOISE_SHARED = 0.3
RED_NOISE_LEVEL = 0.003
RED_NOISE_WHITE_SHARE = 0.3
RED_NOISE_LOWEST_HZ = 0.02
RED_HARMONIC_PHASE = 0.8
RED_PHASE_WANDER = 0.004
RED_PULSE_DEPTH = 0.005
RED_HARMONIC_RATIOS = (0.3, 0.5)
BAND_EDGES_HZ = (0.5, 4.5)
BAND_ORDER = 4

type WaveBuilder = Callable[[NDArray[np.float64]], NDArray[np.float64]]


@dataclass(frozen=True)
class Recording:
    timestamps_ms: NDArray[np.float64]
    regions: NDArray[np.float64]

    def until(self, seconds: float) -> Self:
        keep = self.timestamps_ms - self.timestamps_ms[0] <= seconds * 1000.0
        return type(self)(self.timestamps_ms[keep], self.regions[keep])

    def after(self, seconds: float) -> Self:
        keep = self.timestamps_ms - self.timestamps_ms[0] > seconds * 1000.0
        return type(self)(self.timestamps_ms[keep], self.regions[keep])

    def shifted(self, offset_ms: float) -> Self:
        return type(self)(self.timestamps_ms + offset_ms, self.regions)

    def samples(self) -> list[tuple[float, RegionColours]]:
        return [
            (float(t), region_colours(frame))
            for t, frame in zip(self.timestamps_ms, self.regions, strict=True)
        ]


def region_colours(frame: NDArray[np.float64]) -> RegionColours:
    forehead, left_cheek, right_cheek = (
        (float(r), float(g), float(b)) for r, g, b in frame
    )
    return RegionColours(
        forehead=forehead, left_cheek=left_cheek, right_cheek=right_cheek
    )


def same_colour_everywhere(rgb: tuple[float, float, float]) -> RegionColours:
    return RegionColours(forehead=rgb, left_cheek=rgb, right_cheek=rgb)


def clipped_jitter(rng: np.random.Generator, count: int) -> NDArray[np.float64]:
    return np.clip(
        rng.normal(0.0, JITTER_SD_MS, count), -JITTER_LIMIT_MS, JITTER_LIMIT_MS
    )


def webcam_timestamps(
    rng: np.random.Generator, duration_s: float, fps: float = FPS
) -> NDArray[np.float64]:
    count = int(duration_s * fps)
    return CLOCK_START_MS + np.arange(count) * 1000.0 / fps + clipped_jitter(rng, count)


def variable_rate_timestamps(
    rng: np.random.Generator, duration_s: float, min_fps: float, max_fps: float
) -> NDArray[np.float64]:
    intervals = rng.uniform(
        1000.0 / max_fps, 1000.0 / min_fps, int(duration_s * max_fps) + 1
    )
    timestamps = CLOCK_START_MS + np.concatenate(([0.0], np.cumsum(intervals)))
    return timestamps[timestamps - CLOCK_START_MS < duration_s * 1000.0]


def harmonic_wave(
    angle: NDArray[np.float64], harmonic_ratio: float = HARMONIC_RATIO
) -> NDArray[np.float64]:
    return np.sin(angle) + harmonic_ratio * np.sin(2.0 * angle + HARMONIC_PHASE)


def skin_rgb_from_wave(
    rng: np.random.Generator,
    seconds: NDArray[np.float64],
    wave: NDArray[np.float64],
    noise_sd: float = NOISE_SD,
    motion_step: bool = True,
    skin_dc: NDArray[np.float64] = SKIN_DC,
) -> NDArray[np.float64]:
    modulation = 1.0 + PULSE_DEPTH * np.outer(wave, PULSE_SIGNATURE)
    lighting = 1.0 + 0.03 * np.sin(2.0 * np.pi * 0.05 * seconds) + 0.01 * seconds / 20.0
    tint = np.column_stack(
        (
            1.0 + 0.01 * seconds / 20.0,
            np.ones_like(seconds),
            1.0 - 0.01 * seconds / 20.0,
        )
    )
    step = np.ones((seconds.size, 3))
    if motion_step:
        step[seconds >= MOTION_STEP_AT_S] = MOTION_STEP_GAIN
    clean = skin_dc * modulation * lighting[:, None] * tint * step
    return clean + rng.normal(0.0, noise_sd, clean.shape)


def regions_from_wave(
    rng: np.random.Generator,
    seconds: NDArray[np.float64],
    wave: NDArray[np.float64],
    motion_step: bool = True,
    local_waves: Sequence[NDArray[np.float64]] | None = None,
) -> NDArray[np.float64]:
    locals_ = local_waves or [np.zeros_like(seconds)] * REGION_COUNT
    return np.stack(
        [
            skin_rgb_from_wave(
                rng, seconds, wave + local, motion_step=motion_step, skin_dc=dc
            )
            for dc, local in zip(REGION_DC, locals_, strict=True)
        ],
        axis=1,
    )


def skin_rgb(
    rng: np.random.Generator,
    timestamps_ms: NDArray[np.float64],
    bpm: float | None,
    noise_sd: float = NOISE_SD,
    motion_step: bool = True,
    harmonic_ratio: float = HARMONIC_RATIO,
) -> NDArray[np.float64]:
    seconds = (timestamps_ms - timestamps_ms[0]) / 1000.0
    return skin_rgb_from_wave(
        rng,
        seconds,
        pulse_wave(rng, seconds, bpm, harmonic_ratio),
        noise_sd,
        motion_step,
    )


def pulse_wave(
    rng: np.random.Generator,
    seconds: NDArray[np.float64],
    bpm: float | None,
    harmonic_ratio: float = HARMONIC_RATIO,
) -> NDArray[np.float64]:
    if bpm is None:
        return np.zeros_like(seconds)
    phase = rng.uniform(0.0, 2.0 * np.pi)
    return harmonic_wave(2.0 * np.pi * bpm / 60.0 * seconds + phase, harmonic_ratio)


def tone(
    seconds: NDArray[np.float64], bpm: float, amplitude: float
) -> NDArray[np.float64]:
    return amplitude * np.sin(2.0 * np.pi * bpm / 60.0 * seconds)


def piecewise_wave(
    seconds: NDArray[np.float64], segments: Sequence[tuple[float, float | None]]
) -> NDArray[np.float64]:
    angle = np.zeros_like(seconds)
    present = np.zeros(seconds.size, dtype=np.bool_)
    ends = [start for start, _ in segments[1:]] + [np.inf]
    for (start_s, bpm), end_s in zip(segments, ends, strict=True):
        inside = np.clip(seconds, start_s, end_s) - start_s
        if bpm is not None:
            angle += 2.0 * np.pi * bpm / 60.0 * inside
            present |= (seconds >= start_s) & (seconds < end_s)
    return np.where(present, harmonic_wave(angle), 0.0)


def ramp_bpm(
    seconds: float, start_s: float, end_s: float, from_bpm: float, to_bpm: float
) -> float:
    progress = min(max((seconds - start_s) / (end_s - start_s), 0.0), 1.0)
    return from_bpm + (to_bpm - from_bpm) * progress


def ramp_wave(
    seconds: NDArray[np.float64],
    start_s: float,
    end_s: float,
    from_bpm: float,
    to_bpm: float,
) -> NDArray[np.float64]:
    slope = (to_bpm - from_bpm) / (end_s - start_s)
    rising = np.clip(seconds - start_s, 0.0, end_s - start_s)
    after = np.clip(seconds - end_s, 0.0, None)
    beats = (
        from_bpm * seconds + slope * rising**2 / 2.0 + (to_bpm - from_bpm) * after
    ) / 60.0
    return harmonic_wave(2.0 * np.pi * beats)


def webcam_recording(
    bpm: float | None,
    seed: int,
    duration_s: float = 25.0,
    motion_step: bool = True,
    harmonic_ratio: float = HARMONIC_RATIO,
) -> Recording:
    rng = np.random.default_rng(seed)
    timestamps = webcam_timestamps(rng, duration_s)
    seconds = (timestamps - timestamps[0]) / 1000.0
    wave = pulse_wave(rng, seconds, bpm, harmonic_ratio)
    return Recording(timestamps, regions_from_wave(rng, seconds, wave, motion_step))


def wave_recording(
    wave_for: WaveBuilder,
    seed: int,
    duration_s: float,
    motion_step: bool = False,
    local_waves_for: Sequence[WaveBuilder] | None = None,
) -> Recording:
    rng = np.random.default_rng(seed)
    timestamps = webcam_timestamps(rng, duration_s)
    seconds = (timestamps - timestamps[0]) / 1000.0
    local_waves = (
        None
        if local_waves_for is None
        else [local_for(seconds) for local_for in local_waves_for]
    )
    return Recording(
        timestamps,
        regions_from_wave(rng, seconds, wave_for(seconds), motion_step, local_waves),
    )


def constant_recording(
    rgb: tuple[float, float, float], seed: int, duration_s: float
) -> Recording:
    rng = np.random.default_rng(seed)
    timestamps = webcam_timestamps(rng, duration_s)
    colour = np.asarray(rgb, dtype=np.float64)
    return Recording(timestamps, np.tile(colour, (timestamps.size, REGION_COUNT, 1)))


def reported_jitter_recording(
    bpm: float, seed: int, duration_s: float = 25.0
) -> Recording:
    rng = np.random.default_rng(seed)
    count = int(duration_s * FPS)
    true_times = CLOCK_START_MS + np.arange(count) * 1000.0 / FPS
    seconds = (true_times - true_times[0]) / 1000.0
    regions = regions_from_wave(rng, seconds, pulse_wave(rng, seconds, bpm))
    return Recording(true_times + clipped_jitter(rng, count), regions)


def variable_rate_recording(
    bpm: float,
    seed: int,
    duration_s: float = 25.0,
    min_fps: float = 25.0,
    max_fps: float = 35.0,
) -> Recording:
    rng = np.random.default_rng(seed)
    timestamps = variable_rate_timestamps(rng, duration_s, min_fps, max_fps)
    seconds = (timestamps - timestamps[0]) / 1000.0
    return Recording(
        timestamps, regions_from_wave(rng, seconds, pulse_wave(rng, seconds, bpm))
    )


def red_noise(
    rng: np.random.Generator, count: int, slope: float = RED_NOISE_SLOPE
) -> NDArray[np.float64]:
    spectrum = np.fft.rfft(rng.standard_normal(count))
    freqs = np.maximum(np.fft.rfftfreq(count, 1.0 / FPS), RED_NOISE_LOWEST_HZ)
    return np.fft.irfft(spectrum * freqs ** (-slope / 2.0), count)


def red_noise_channels(rng: np.random.Generator, count: int) -> NDArray[np.float64]:
    return np.column_stack([red_noise(rng, count) for _ in range(3)])


def in_band_sd(values: NDArray[np.float64]) -> NDArray[np.float64]:
    sections = butter(BAND_ORDER, BAND_EDGES_HZ, btype="bandpass", fs=FPS, output="sos")
    return np.asarray(sosfiltfilt(sections, values, axis=0).std(axis=0))


def region_red_noise(rng: np.random.Generator, count: int) -> NDArray[np.float64]:
    shared = red_noise_channels(rng, count)
    regions = []
    for _ in range(REGION_COUNT):
        mixed = (
            np.sqrt(1.0 - RED_NOISE_SHARED) * red_noise_channels(rng, count)
            + np.sqrt(RED_NOISE_SHARED) * shared
        )
        scaled = mixed / in_band_sd(mixed) * RED_NOISE_LEVEL
        white = (
            RED_NOISE_WHITE_SHARE * RED_NOISE_LEVEL * rng.standard_normal(mixed.shape)
        )
        regions.append(scaled + white)
    return np.stack(regions, axis=1)


def wandering_pulse(
    rng: np.random.Generator,
    seconds: NDArray[np.float64],
    bpm: float | None,
    harmonic_ratio: float,
) -> NDArray[np.float64]:
    if bpm is None:
        return np.zeros_like(seconds)
    phase = (
        2.0 * np.pi * bpm / 60.0 * seconds
        + rng.uniform(0.0, 2.0 * np.pi)
        + np.cumsum(rng.standard_normal(seconds.size)) * RED_PHASE_WANDER
    )
    return np.sin(phase) + harmonic_ratio * np.sin(2.0 * phase + RED_HARMONIC_PHASE)


def red_noise_recording(
    bpm: float | None,
    seed: int,
    depth: float = RED_PULSE_DEPTH,
    harmonic_ratio: float = RED_HARMONIC_RATIOS[0],
    duration_s: float = 20.4,
) -> Recording:
    rng = np.random.default_rng(seed)
    timestamps = webcam_timestamps(rng, duration_s)
    seconds = (timestamps - timestamps[0]) / 1000.0
    wave = wandering_pulse(rng, seconds, bpm, harmonic_ratio)
    pulse = depth * np.outer(wave, RED_PULSE_SIGNATURE)
    noise = region_red_noise(rng, timestamps.size)
    return Recording(timestamps, RED_SKIN_DC * (1.0 + pulse[:, None, :] + noise))


def dominant_frequency_hz(
    values: NDArray[np.float64], fs_hz: float, low_hz: float = 0.7, high_hz: float = 4.0
) -> float:
    centred = values - values.mean()
    n_fft = 1 << 16
    power = np.abs(np.fft.rfft(centred * np.hanning(centred.size), n_fft)) ** 2
    freqs = np.fft.rfftfreq(n_fft, 1.0 / fs_hz)
    band = (freqs >= low_hz) & (freqs <= high_hz)
    return float(freqs[band][np.argmax(power[band])])


def sine_amplitude(
    times_s: NDArray[np.float64], values: NDArray[np.float64], freq_hz: float
) -> float:
    angle = 2.0 * np.pi * freq_hz * times_s
    design = np.column_stack((np.sin(angle), np.cos(angle), np.ones_like(times_s)))
    coefficients, *_ = np.linalg.lstsq(design, values, rcond=None)
    return float(np.hypot(coefficients[0], coefficients[1]))
