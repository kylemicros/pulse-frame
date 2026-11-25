import numpy as np
import pytest
from numpy.typing import NDArray

from pulse_frame.stream.frames import JPEG_CAP_BYTES
from tests.frames import SEED
from tests.signal.face_synthetic import realistic_face
from tests.signal.synthetic import REGION_DC
from tests.stream.jpegs import encode_jpeg
from tests.stream.painted_faces import (
    BROWSER_QUALITY,
    PIXEL_NOISE_SD,
    FacePainter,
    HrvScore,
    RoundTrip,
    round_trip,
)

BPM = 72.0
FACE_SNR_DB = 10.0
RUN_S = 80.0
MAX_SNR_LOSS_DB = 1.5
MAX_ACCEPTED_SHARE_LOSS = 0.05
MAX_IBI_P90_GROWTH_MS = 10.0
MAX_HRV_ERROR_GROWTH_MS = 3.0
OLD_BROWSER_QUALITY = 80
CAP_SHARE = 0.5
ROOM_DARK = 60.0
ROOM_BRIGHT = 200.0


@pytest.fixture(scope="module")
def trip() -> RoundTrip:
    return round_trip(realistic_face(BPM, FACE_SNR_DB, SEED, RUN_S), SEED)


@pytest.fixture(scope="module")
def old_trip() -> RoundTrip:
    face = realistic_face(BPM, FACE_SNR_DB, SEED, RUN_S)
    return round_trip(face, SEED, OLD_BROWSER_QUALITY)


def shown_ms(value: float | None) -> str:
    return "no reading" if value is None else f"{value:.1f} ms"


def shown(score: HrvScore) -> str:
    return (
        f"snr {score.median_snr_db:.2f} dB, accepted {score.accepted_share:.2f},"
        f" ibi p90 {score.ibi_error_p90_ms:.1f} ms,"
        f" rmssd error {shown_ms(score.rmssd_error_ms)},"
        f" sdnn error {shown_ms(score.sdnn_error_ms)}"
    )


def error_growth(raw: float | None, jpeg: float | None) -> float:
    assert raw is not None, "the raw frames gave no HRV reading to compare against"
    return float("inf") if jpeg is None else jpeg - raw


def harms(trip: RoundTrip) -> dict[str, bool]:
    raw, jpeg = trip.raw, trip.jpeg
    return {
        "window_snr": raw.median_snr_db - jpeg.median_snr_db > MAX_SNR_LOSS_DB,
        "accepted_share": raw.accepted_share - jpeg.accepted_share
        > MAX_ACCEPTED_SHARE_LOSS,
        "ibi_error": jpeg.ibi_error_p90_ms - raw.ibi_error_p90_ms
        > MAX_IBI_P90_GROWTH_MS,
        "rmssd_error": error_growth(raw.rmssd_error_ms, jpeg.rmssd_error_ms)
        > MAX_HRV_ERROR_GROWTH_MS,
        "sdnn_error": error_growth(raw.sdnn_error_ms, jpeg.sdnn_error_ms)
        > MAX_HRV_ERROR_GROWTH_MS,
    }


def test_browser_jpeg_frames_give_hrv_like_the_raw_frames(trip: RoundTrip) -> None:
    harmed = [name for name, hurt in harms(trip).items() if hurt]

    assert harmed == [], f"raw: {shown(trip.raw)}; jpeg: {shown(trip.jpeg)}"


def lit_room(rng: np.random.Generator, face: NDArray[np.uint8]) -> NDArray[np.uint8]:
    light = np.linspace(ROOM_DARK, ROOM_BRIGHT, face.shape[1])[None, :, None]
    room = light + rng.normal(0.0, PIXEL_NOISE_SD, face.shape)
    background = np.all(face == face[0, 0], axis=2, keepdims=True)
    return np.where(background, np.clip(np.rint(room), 0, 255), face).astype(np.uint8)


def test_a_browser_quality_frame_stays_well_under_the_jpeg_cap() -> None:
    face = FacePainter(SEED).paint(REGION_DC)
    room = lit_room(np.random.default_rng(SEED), face)

    sizes = [len(encode_jpeg(frame, BROWSER_QUALITY)) for frame in (face, room)]

    assert max(sizes) < CAP_SHARE * JPEG_CAP_BYTES, sizes


def test_the_gate_sees_the_harm_the_old_quality_did(old_trip: RoundTrip) -> None:
    harmed = [name for name, hurt in harms(old_trip).items() if hurt]

    assert harmed != [], f"raw: {shown(old_trip.raw)}; jpeg: {shown(old_trip.jpeg)}"
