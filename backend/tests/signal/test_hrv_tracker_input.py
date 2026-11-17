import math

import pytest

from pulse_frame.signal.errors import SignalError
from pulse_frame.signal.hrv import HrvTracker
from pulse_frame.signal.tracker import RegionColours
from tests.frames import SEED, TRUE_BPM
from tests.signal.beat_synthetic import TRACKER_NOISE_SD, physical_recording
from tests.signal.hrv_tracking import accepted, is_null, tracked
from tests.signal.synthetic import same_colour_everywhere

INPUT_RECORDING_S = 40.0
SKIN = (145.0, 115.0, 100.0)
REPEAT_EVERY = 7
OLDER_BY_MS = 1_500.0
REGIONS = ["forehead", "left_cheek", "right_cheek"]


def same_colour_except(name: str, odd: tuple[float, ...]) -> RegionColours:
    colours: dict[str, tuple[float, ...]] = dict.fromkeys(REGIONS, SKIN)
    colours[name] = odd
    return RegionColours(**colours)


def test_repeated_and_older_timestamps_are_ignored() -> None:
    recording, _ = physical_recording(
        TRUE_BPM, SEED, INPUT_RECORDING_S, noise_sd=TRACKER_NOISE_SD
    )
    clean = tracked(recording)
    noisy = HrvTracker()

    for index, (timestamp_ms, regions) in enumerate(recording.samples()):
        noisy.add(timestamp_ms, regions)
        if index % REPEAT_EVERY == 3:
            noisy.add(
                timestamp_ms,
                same_colour_everywhere((255.0, 0.0, 0.0)),
                moving=True,
                low_quality=True,
            )
            noisy.add(
                timestamp_ms - OLDER_BY_MS,
                same_colour_everywhere((0.0, 255.0, 0.0)),
                moving=True,
                low_quality=True,
            )

    assert len(accepted(clean.intervals())) > 20
    assert noisy.intervals() == clean.intervals()
    assert noisy.reading() == clean.reading()


@pytest.mark.parametrize(
    "fs_hz", [math.nan, math.inf, 0.0, -30.0], ids=["nan", "inf", "zero", "negative"]
)
def test_a_rate_that_is_not_a_positive_finite_number_raises_bad_sample_rate(
    fs_hz: float,
) -> None:
    with pytest.raises(SignalError) as caught:
        HrvTracker(fs_hz)

    assert caught.value.code == "BAD_SAMPLE_RATE"
    assert "positive finite" in caught.value.message
    assert caught.value.action


@pytest.mark.parametrize("fs_hz", [5.0, 9.0])
def test_a_rate_too_low_for_the_band_pass_raises_bad_sample_rate(fs_hz: float) -> None:
    with pytest.raises(SignalError) as caught:
        HrvTracker(fs_hz)

    assert caught.value.code == "BAD_SAMPLE_RATE"
    assert "band-pass" in caught.value.message
    assert caught.value.action


def test_a_rate_just_above_the_band_pass_floor_is_accepted() -> None:
    assert is_null(HrvTracker(9.5).reading())


@pytest.mark.parametrize(
    "timestamp_ms", [math.nan, math.inf, -math.inf], ids=["nan", "inf", "minus_inf"]
)
def test_add_with_a_timestamp_that_is_not_finite_raises_bad_timestamps(
    timestamp_ms: float,
) -> None:
    tracker = HrvTracker()
    tracker.add(1_000.0, same_colour_everywhere(SKIN))

    with pytest.raises(SignalError) as caught:
        tracker.add(timestamp_ms, same_colour_everywhere(SKIN))

    assert caught.value.code == "BAD_TIMESTAMPS"
    assert caught.value.action


@pytest.mark.parametrize("region", REGIONS)
@pytest.mark.parametrize(
    "odd",
    [(145.0, math.nan, 100.0), (145.0, 115.0, math.inf), (145.0, 115.0)],
    ids=["nan", "inf", "two_channels"],
)
def test_add_with_a_bad_region_colour_raises_bad_values_naming_the_region(
    region: str, odd: tuple[float, ...]
) -> None:
    tracker = HrvTracker()

    with pytest.raises(SignalError) as caught:
        tracker.add(1_000.0, same_colour_except(region, odd))

    assert caught.value.code == "BAD_VALUES"
    assert region in caught.value.message
    assert all(other not in caught.value.message for other in set(REGIONS) - {region})
