from itertools import count

import numpy as np
from numpy.typing import NDArray

from tests.signal.synthetic import PULSE_DEPTH, PULSE_SIGNATURE, harmonic_wave

SEED = 20261111
TRUE_BPM = 72.0
REFERENCE_FRAME_MS = 1000.0 / 30.0
SHIFT_SAFETY = 4.0
FRAME_STEP_MS = 33
PULSE_STEP_MS = 100
PULSE_JITTER_MS = 10
PULSE_START_MS = 1_000
PIXEL_NOISE_SD = 1.0


class FrameClock:
    def __init__(self, start_ms: int = 0, step_ms: int = FRAME_STEP_MS) -> None:
        self._ticks = count(start=start_ms, step=step_ms)

    def next_ms(self) -> int:
        return next(self._ticks)


def pulse_timestamps(
    rng: np.random.Generator, duration_s: float, start_ms: int = PULSE_START_MS
) -> list[int]:
    steps = np.arange(int(duration_s * 1000 / PULSE_STEP_MS)) * PULSE_STEP_MS
    jitter = rng.integers(-PULSE_JITTER_MS, PULSE_JITTER_MS + 1, steps.size)
    return [int(start_ms + t) for t in steps + jitter]


def pulsed_frame(
    rgb: NDArray[np.uint8],
    rng: np.random.Generator,
    bpm: float,
    phase: float,
    seconds: float,
) -> NDArray[np.uint8]:
    wave = harmonic_wave(np.array([2.0 * np.pi * bpm / 60.0 * seconds + phase]))[0]
    gain = 1.0 + PULSE_DEPTH * wave * PULSE_SIGNATURE
    noisy = rgb * gain + rng.normal(0.0, PIXEL_NOISE_SD, rgb.shape)
    return np.clip(np.round(noisy), 0, 255).astype(np.uint8)


def shifted_right(rgb: NDArray[np.uint8], pixels: int) -> NDArray[np.uint8]:
    return np.roll(rgb, pixels, axis=1)
