import math

import numpy as np
import pytest
from numpy.typing import NDArray

from pulse_frame.signal.errors import SignalError
from pulse_frame.signal.pos import pos_pulse
from tests.signal.synthetic import (
    NOISE_SD,
    PULSE_DEPTH,
    PULSE_SIGNATURE,
    SKIN_DC,
    dominant_frequency_hz,
    skin_rgb,
)

FS_HZ = 30.0
GREEN_CAST_DC = np.array([100.0, 140.0, 90.0])
FLICKER_DEPTH = 0.02
COLOUR_LEVELS = np.array([[1.0, 1.0, 1.0], [1.2, 1.0, 1.0], [1.0, 1.0, 1.2]])


def uniform_skin_rgb(
    bpm: float, seed: int, duration_s: float = 20.0
) -> NDArray[np.float64]:
    rng = np.random.default_rng(seed)
    timestamps = 1000.0 * np.arange(int(duration_s * FS_HZ)) / FS_HZ
    return skin_rgb(rng, timestamps, bpm, motion_step=False)


def flickering_green_cast_rgb(
    bpm: float, flicker_hz: float, seed: int, duration_s: float = 20.0
) -> NDArray[np.float64]:
    rng = np.random.default_rng(seed)
    t = np.arange(int(duration_s * FS_HZ)) / FS_HZ
    wave = np.sin(2.0 * np.pi * bpm / 60.0 * t + rng.uniform(0.0, 2.0 * np.pi))
    flicker = 1.0 + FLICKER_DEPTH * np.sin(2.0 * np.pi * flicker_hz * t)
    clean = (
        GREEN_CAST_DC
        * (1.0 + PULSE_DEPTH * np.outer(wave, PULSE_SIGNATURE))
        * flicker[:, None]
    )
    return clean + rng.normal(0.0, NOISE_SD, clean.shape)


def three_colour_level_skin_rgb(seed: int, duration_s: float) -> NDArray[np.float64]:
    rng = np.random.default_rng(seed)
    t = np.arange(int(duration_s * FS_HZ)) / FS_HZ
    wave = np.sin(2.0 * np.pi * 1.2 * t + rng.uniform(0.0, 2.0 * np.pi))
    level = np.minimum((t / duration_s * len(COLOUR_LEVELS)).astype(int), 2)
    clean = (
        SKIN_DC
        * COLOUR_LEVELS[level]
        * (1.0 + PULSE_DEPTH * np.outer(wave, PULSE_SIGNATURE))
    )
    return clean + rng.normal(0.0, NOISE_SD, clean.shape)


def test_pos_output_has_one_value_per_input_sample() -> None:
    rgb = uniform_skin_rgb(75.0, seed=3)

    pulse = pos_pulse(rgb, FS_HZ)

    assert pulse.shape == (rgb.shape[0],)
    assert np.all(np.isfinite(pulse))


@pytest.mark.parametrize("bpm", [54.0, 75.0, 132.0])
def test_pos_recovers_pulse_frequency_from_skin_rgb(bpm: float) -> None:
    pulse = pos_pulse(uniform_skin_rgb(bpm, seed=5), FS_HZ)

    assert dominant_frequency_hz(pulse, FS_HZ) == pytest.approx(bpm / 60.0, abs=0.05)


@pytest.mark.parametrize("flicker_hz", [1.0, 1.7, 2.0])
@pytest.mark.parametrize("seed", [21, 22])
def test_pos_rejects_white_light_flicker_that_beats_the_green_channel(
    flicker_hz: float, seed: int
) -> None:
    rgb = flickering_green_cast_rgb(72.0, flicker_hz, seed)
    assert dominant_frequency_hz(rgb[:, 1], FS_HZ) == pytest.approx(
        flicker_hz, abs=0.02
    )

    pulse = pos_pulse(rgb, FS_HZ)

    assert dominant_frequency_hz(pulse, FS_HZ) == pytest.approx(1.2, abs=0.02)


@pytest.mark.parametrize("fs_hz", [0.0, -30.0, math.nan, math.inf])
def test_pos_rejects_bad_sample_rate(fs_hz: float) -> None:
    with pytest.raises(SignalError) as caught:
        pos_pulse(uniform_skin_rgb(72.0, seed=1, duration_s=3.0), fs_hz)

    assert caught.value.code == "BAD_SAMPLE_RATE"
    assert caught.value.message
    assert caught.value.action


@pytest.mark.parametrize(
    "shape", [(90,), (90, 2), (90, 4), (90, 3, 1)], ids=["1d", "2ch", "4ch", "3d"]
)
def test_pos_rejects_values_that_are_not_rows_of_three_channels(
    shape: tuple[int, ...],
) -> None:
    with pytest.raises(SignalError) as caught:
        pos_pulse(np.full(shape, 120.0), FS_HZ)

    assert caught.value.code == "BAD_VALUES"
    assert caught.value.message
    assert caught.value.action


@pytest.mark.parametrize("value", [math.nan, math.inf], ids=["nan", "inf"])
def test_pos_rejects_values_that_are_not_finite(value: float) -> None:
    rgb = uniform_skin_rgb(72.0, seed=1, duration_s=3.0)
    rgb[40, 1] = value

    with pytest.raises(SignalError) as caught:
        pos_pulse(rgb, FS_HZ)

    assert caught.value.code == "BAD_VALUES"
    assert caught.value.message
    assert caught.value.action


@pytest.mark.parametrize("window_s", [0.0, -1.6, math.nan, math.inf])
def test_pos_rejects_window_that_is_not_positive_and_finite(window_s: float) -> None:
    with pytest.raises(SignalError) as caught:
        pos_pulse(uniform_skin_rgb(72.0, seed=1, duration_s=3.0), FS_HZ, window_s)

    assert caught.value.code == "BAD_WINDOW"
    assert caught.value.message
    assert caught.value.action


@pytest.mark.filterwarnings("error")
@pytest.mark.parametrize("count", [0, 1, 10])
def test_pos_short_input_keeps_its_length_without_raising(count: int) -> None:
    rgb = uniform_skin_rgb(72.0, seed=4, duration_s=1.0)[:count]

    pulse = pos_pulse(rgb, FS_HZ)

    assert pulse.shape == (count,)
    assert np.all(np.isfinite(pulse))


@pytest.mark.parametrize("seed", [31, 32, 33])
def test_short_pos_window_recovers_pulse_through_skin_colour_changes(
    seed: int,
) -> None:
    duration_s = 20.0
    rgb = three_colour_level_skin_rgb(seed, duration_s)
    one_window = pos_pulse(rgb, FS_HZ, window_s=duration_s)
    assert dominant_frequency_hz(one_window, FS_HZ) != pytest.approx(1.2, abs=0.1)

    pulse = pos_pulse(rgb, FS_HZ)

    assert dominant_frequency_hz(pulse, FS_HZ) == pytest.approx(1.2, abs=0.02)
