import pytest

from pulse_frame.signal.spectrum import RateEstimate
from pulse_frame.signal.tracker import MIN_SNR_DB, RateSmoother, Reading

GOOD_DB = MIN_SNR_DB + 8.0
POOR_DB = MIN_SNR_DB - 3.0
START_MS = 50_000.0
UPDATE_MS = 1000.0


def run(bpms: list[float | None], interval_ms: float = UPDATE_MS) -> list[Reading]:
    smoother = RateSmoother()
    return [
        smoother.update(
            START_MS + index * interval_ms,
            RateEstimate(bpm=72.0, snr_db=POOR_DB)
            if bpm is None
            else RateEstimate(bpm=bpm, snr_db=GOOD_DB),
        )
        for index, bpm in enumerate(bpms)
    ]


def assert_shows(reading: Reading, bpm: float, tolerance: float = 1e-9) -> None:
    assert reading.state == "ok"
    assert reading.bpm is not None
    assert reading.bpm == pytest.approx(bpm, abs=tolerance)


def test_first_good_estimate_is_shown() -> None:
    (reading,) = run([72.0])

    assert_shows(reading, 72.0)
    assert reading.quality_db == pytest.approx(GOOD_DB)


def test_poor_estimate_is_low_quality_with_its_snr() -> None:
    (reading,) = run([None])

    assert reading.state == "low_quality"
    assert reading.bpm is None
    assert reading.quality_db == pytest.approx(POOR_DB)


def test_single_outlier_after_steady_history_does_not_change_shown_bpm() -> None:
    readings = run([71.0, 72.0, 73.0, 150.0, 72.5])

    shown_before = readings[2].bpm
    assert shown_before is not None
    assert_shows(readings[3], shown_before)
    assert_shows(readings[4], 72.0, tolerance=1.0)


@pytest.mark.parametrize("outlier_bpm", [150.0, 102.0, 42.0])
def test_one_update_jump_right_after_first_reading_is_not_shown(
    outlier_bpm: float,
) -> None:
    readings = run([72.0, outlier_bpm, 72.4])

    assert_shows(readings[1], 72.0)
    assert_shows(readings[2], 72.0, tolerance=0.5)


def test_second_unrelated_jump_after_a_held_one_resets_to_low_quality() -> None:
    readings = run([72.0, 72.2, 150.0, 110.0, 72.1])

    assert_shows(readings[0], 72.0)
    assert_shows(readings[1], 72.1)
    assert_shows(readings[2], 72.1)
    assert readings[3].state == "low_quality"
    assert readings[3].bpm is None
    assert_shows(readings[4], 72.1)


def test_alternating_outliers_are_never_shown() -> None:
    readings = run([72.0, 150.0, 72.2, 150.3, 72.1])

    for reading in readings:
        assert_shows(reading, 72.0, tolerance=1.0)


@pytest.mark.parametrize(
    ("bpms", "shown"),
    [
        ([72.0, 74.0, 73.0], 73.0),
        ([72.0, 72.5, 74.0], 72.5),
        ([72.0, 72.0, 74.0, 74.5, 75.0], 74.5),
    ],
)
def test_shown_rate_is_the_median_of_the_last_three_estimates(
    bpms: list[float | None], shown: float
) -> None:
    readings = run(bpms)

    assert_shows(readings[-1], shown)


def test_change_of_four_bpm_per_second_is_followed() -> None:
    readings = run([72.0, 76.0, 80.0, 84.0])

    for reading, shown in zip(readings, [72.0, 74.0, 76.0, 80.0], strict=True):
        assert_shows(reading, shown)


def test_change_of_seven_bpm_in_one_second_is_held_once() -> None:
    readings = run([72.0, 79.0, 79.2])

    assert_shows(readings[1], 72.0)
    assert readings[2].state == "ok"
    assert readings[2].bpm is not None
    assert readings[2].bpm >= 75.5


def test_change_of_seven_bpm_over_two_seconds_is_followed() -> None:
    readings = run([72.0, 79.0], interval_ms=2 * UPDATE_MS)

    assert_shows(readings[1], 75.5)


def test_sustained_step_is_shown_once_it_repeats() -> None:
    readings = run([72.0, 72.3, 120.0, 120.4, 120.2])

    shown_before = readings[1].bpm
    assert shown_before is not None
    assert_shows(readings[2], shown_before)
    assert_shows(readings[3], 120.2)
    assert_shows(readings[4], 120.2)


def test_sustained_step_right_after_first_reading_is_shown_once_it_repeats() -> None:
    readings = run([72.0, 120.0, 120.4])

    assert_shows(readings[1], 72.0)
    assert_shows(readings[2], 120.2)


def test_confirmed_jump_shows_the_median_of_the_held_and_confirming_estimates() -> None:
    readings = run([72.0, 72.0, 120.0, 124.0])

    assert_shows(readings[2], 72.0)
    assert_shows(readings[3], 122.0)


def test_gradual_change_is_followed_without_holding() -> None:
    readings = run([72.0, 73.0, 74.0, 75.0, 76.0, 77.0])

    for reading in readings:
        assert reading.state == "ok"
    assert_shows(readings[-1], 76.0, tolerance=1.0)


def test_low_quality_estimate_clears_history() -> None:
    readings = run([72.0, 72.0, 72.0, None, 90.0])

    assert readings[3].state == "low_quality"
    assert readings[3].bpm is None
    assert_shows(readings[4], 90.0)


def test_reset_forgets_shown_rate() -> None:
    smoother = RateSmoother()
    for index in range(3):
        smoother.update(START_MS + index * UPDATE_MS, RateEstimate(72.0, GOOD_DB))

    smoother.reset()
    reading = smoother.update(START_MS + 3 * UPDATE_MS, RateEstimate(150.0, GOOD_DB))

    assert_shows(reading, 150.0)
