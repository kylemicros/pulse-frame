from dataclasses import dataclass

import numpy as np
import pytest
from numpy.typing import NDArray

from pulse_frame.signal.hrv import HrvReading
from tests.frames import SEED
from tests.signal.beat_synthetic import beats_inside, rmssd, sdnn
from tests.signal.face_synthetic import Face, matched_ibi_errors, realistic_face
from tests.signal.hrv_tracking import TRUTH_MARGIN_MS, accepted, tracked

FACE_S = 80.0
STEP_AT_S = 40.0
FACE_RATES_BPM = (52.0, 60.0, 66.0, 72.0, 78.0, 84.0, 92.0, 100.0)
SNR_BANDS_DB = (0.0, 5.0, 10.0, 15.0, 20.0)
READING_BANDS_DB = (5.0, 10.0, 15.0, 20.0)
LOWEST_BAND_DB = 0.0
IBI_P90_BOUND_MS = {0.0: 90.0, 5.0: 55.0, 10.0: 40.0, 15.0: 35.0, 20.0: 30.0}
GROSS_ERROR_MS = 50.0
GROSS_SHARE_BOUND = {0.0: 0.35, 5.0: 0.1, 10.0: 0.03, 15.0: 0.02, 20.0: 0.02}
RMSSD_BOUND_MS = {0.0: 20.0, 5.0: 30.0, 10.0: 20.0, 15.0: 20.0, 20.0: 20.0}
SDNN_BOUND_MS = {0.0: 20.0, 5.0: 25.0, 10.0: 20.0, 15.0: 20.0, 20.0: 20.0}
ACCEPTED_SHARE_FLOOR = {5.0: 0.75, 10.0: 0.85, 15.0: 0.85, 20.0: 0.85}
FACE_SHARE_FLOOR = 0.6
PULSELESS_SNR_DB = 15.0
PULSELESS_SEEDS = (0, 1, 2)
PULSELESS_ACCEPTED_FLOOR = 0.8
PULSELESS_IBI_P90_BOUND_MS = 45.0
PULSELESS_GROSS_SHARE_BOUND = 0.08


@dataclass(frozen=True)
class FaceScore:
    accepted_share: float
    ibi_errors_ms: NDArray[np.float64]
    reading: HrvReading
    truth_ibis_ms: NDArray[np.float64]

    def hrv_errors_ms(self) -> tuple[float, float] | None:
        if self.reading.rmssd_ms is None or self.reading.sdnn_ms is None:
            return None
        return (
            abs(self.reading.rmssd_ms - rmssd(self.truth_ibis_ms)),
            abs(self.reading.sdnn_ms - sdnn(self.truth_ibis_ms)),
        )


@dataclass(frozen=True)
class BandScores:
    snr_db: float
    faces: list[FaceScore]

    def ibi_errors_ms(self) -> NDArray[np.float64]:
        return np.abs(np.concatenate([face.ibi_errors_ms for face in self.faces]))

    def hrv_errors_ms(self) -> list[tuple[float, float]]:
        return [e for e in (face.hrv_errors_ms() for face in self.faces) if e]


def true_face_ibis(face: Face) -> NDArray[np.float64]:
    first_ms = float(face.recording.timestamps_ms[0]) + TRUTH_MARGIN_MS
    last_ms = float(face.recording.timestamps_ms[-1]) - TRUTH_MARGIN_MS
    return np.diff(beats_inside(face.beats_ms, first_ms, last_ms))


def score(face: Face) -> FaceScore:
    tracker = tracked(face.recording)
    kept = accepted(tracker.intervals())
    truth = true_face_ibis(face)
    return FaceScore(
        accepted_share=len(kept) / truth.size,
        ibi_errors_ms=matched_ibi_errors(kept, face.beats_ms),
        reading=tracker.reading(),
        truth_ibis_ms=truth,
    )


def band_faces(snr_db: float) -> list[Face]:
    first_seed = SEED + 100 * SNR_BANDS_DB.index(snr_db)
    return [
        realistic_face(
            bpm,
            snr_db,
            first_seed + index,
            FACE_S,
            step_at_s=STEP_AT_S if index % 2 else None,
        )
        for index, bpm in enumerate(FACE_RATES_BPM)
    ]


@pytest.fixture(scope="module")
def band(request: pytest.FixtureRequest) -> BandScores:
    snr_db = float(request.param)
    return BandScores(snr_db, [score(face) for face in band_faces(snr_db)])


@pytest.mark.parametrize("band", SNR_BANDS_DB, indirect=True)
def test_accepted_ibis_stay_within_the_bands_error_bounds_against_true_beats(
    band: BandScores,
) -> None:
    errors = band.ibi_errors_ms()

    assert errors.size > 0
    assert float(np.percentile(errors, 90)) <= IBI_P90_BOUND_MS[band.snr_db]
    assert float(np.mean(errors > GROSS_ERROR_MS)) <= GROSS_SHARE_BOUND[band.snr_db]


@pytest.mark.parametrize("band", READING_BANDS_DB, indirect=True)
def test_most_faces_at_five_db_and_up_accept_most_true_beats(band: BandScores) -> None:
    floor = ACCEPTED_SHARE_FLOOR[band.snr_db]

    accepting = [face for face in band.faces if face.accepted_share >= floor]

    assert len(accepting) >= FACE_SHARE_FLOOR * len(band.faces)


@pytest.mark.parametrize("band", READING_BANDS_DB, indirect=True)
def test_most_faces_at_five_db_and_up_give_one_minute_readings_near_the_truth(
    band: BandScores,
) -> None:
    errors = band.hrv_errors_ms()

    assert len(errors) >= FACE_SHARE_FLOOR * len(band.faces)
    for rmssd_error, sdnn_error in errors:
        assert rmssd_error <= RMSSD_BOUND_MS[band.snr_db]
        assert sdnn_error <= SDNN_BOUND_MS[band.snr_db]


@pytest.mark.parametrize("seed", PULSELESS_SEEDS)
@pytest.mark.parametrize("region", [0, 1, 2])
def test_a_region_without_a_pulse_leaves_the_others_timing_beats_near_the_truth(
    region: int, seed: int
) -> None:
    face = realistic_face(
        FACE_RATES_BPM[seed], PULSELESS_SNR_DB, SEED + seed, FACE_S, (region,)
    )

    scored = score(face)

    errors = np.abs(scored.ibi_errors_ms)
    hrv_errors = scored.hrv_errors_ms()
    assert scored.accepted_share >= PULSELESS_ACCEPTED_FLOOR
    assert float(np.percentile(errors, 90)) <= PULSELESS_IBI_P90_BOUND_MS
    assert float(np.mean(errors > GROSS_ERROR_MS)) <= PULSELESS_GROSS_SHARE_BOUND
    if hrv_errors is not None:
        assert hrv_errors[0] <= RMSSD_BOUND_MS[PULSELESS_SNR_DB]
        assert hrv_errors[1] <= SDNN_BOUND_MS[PULSELESS_SNR_DB]


@pytest.mark.parametrize("band", [LOWEST_BAND_DB], indirect=True)
def test_a_zero_db_face_gives_no_reading_or_one_capped_at_twenty_ms(
    band: BandScores,
) -> None:
    for rmssd_error, sdnn_error in band.hrv_errors_ms():
        assert rmssd_error <= RMSSD_BOUND_MS[band.snr_db]
        assert sdnn_error <= SDNN_BOUND_MS[band.snr_db]
