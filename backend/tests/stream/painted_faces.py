from dataclasses import dataclass

import cv2
import numpy as np
from numpy.typing import NDArray

from pulse_frame.stream.frames import jpeg_rgb
from pulse_frame.vision.regions import skin_mean
from tests.signal.beat_synthetic import beats_inside, rmssd, sdnn
from tests.signal.face_synthetic import Face, matched_ibi_errors
from tests.signal.hrv_tracking import TRUTH_MARGIN_MS, accepted, tracked
from tests.signal.synthetic import REGION_DC, Recording
from tests.stream.jpegs import encode_jpeg

FRAME_WIDTH_PX = 640
FRAME_HEIGHT_PX = 480
BROWSER_QUALITY = 95
PIXEL_NOISE_SD = 2.0
SHADING_SWING = 0.08
SIDE_LIGHT_SHARE = 0.6
BROW_TO_CHIN_SHARE = 0.4
TEXTURE_SD = 0.03
BACKGROUND = (120, 120, 120)
FACE_BOX = (192, 96, 448, 416)
REGION_POLYGONS = (
    np.array([[0.40, 0.25], [0.60, 0.25], [0.60, 0.33], [0.40, 0.33]]),
    np.array([[0.36, 0.50], [0.45, 0.50], [0.45, 0.62], [0.36, 0.62]]),
    np.array([[0.55, 0.50], [0.64, 0.50], [0.64, 0.62], [0.55, 0.62]]),
)


@dataclass(frozen=True)
class HrvScore:
    median_snr_db: float
    accepted_share: float
    ibi_error_p90_ms: float
    rmssd_error_ms: float | None
    sdnn_error_ms: float | None


@dataclass(frozen=True)
class RoundTrip:
    raw: HrvScore
    jpeg: HrvScore


class FacePainter:
    def __init__(self, seed: int) -> None:
        self._rng = np.random.default_rng(seed)
        self._base = np.full(
            (FRAME_HEIGHT_PX, FRAME_WIDTH_PX, 3), BACKGROUND, dtype=np.uint8
        )
        left, top, right, bottom = FACE_BOX
        self._box = (slice(top, bottom), slice(left, right))
        self._palette = np.vstack([REGION_DC.mean(axis=0), REGION_DC])
        self._index = np.zeros((bottom - top, right - left), dtype=np.intp)
        for number, polygon in enumerate(REGION_POLYGONS, start=1):
            self._index[box_mask(polygon)] = number
        self._shading = skin_shading(self._rng, bottom - top, right - left)

    def paint(self, colours: NDArray[np.float64]) -> NDArray[np.uint8]:
        self._palette[1:] = colours
        box = self._palette[self._index].astype(np.float32) * self._shading
        box += self._rng.standard_normal(box.shape, dtype=np.float32) * np.float32(
            PIXEL_NOISE_SD
        )
        frame = self._base.copy()
        frame[self._box] = np.clip(np.rint(box), 0, 255).astype(np.uint8)
        return frame


def skin_shading(
    rng: np.random.Generator, height: int, width: int
) -> NDArray[np.float32]:
    across = np.linspace(-1.0, 1.0, width)[None, :]
    down = np.linspace(-1.0, 1.0, height)[:, None]
    gradient = SHADING_SWING * (
        SIDE_LIGHT_SHARE * across + BROW_TO_CHIN_SHARE * down * down
    )
    texture = TEXTURE_SD * rng.standard_normal((height, width))
    return (1.0 + gradient + texture).astype(np.float32)[:, :, None]


def box_mask(polygon: NDArray[np.float64]) -> NDArray[np.bool_]:
    left, top, right, bottom = FACE_BOX
    full = np.zeros((FRAME_HEIGHT_PX, FRAME_WIDTH_PX), dtype=np.uint8)
    scale = np.array([FRAME_WIDTH_PX, FRAME_HEIGHT_PX], dtype=np.float64)
    cv2.fillPoly(full, [np.round(polygon * scale).astype(np.int32)], 1)
    return full[top:bottom, left:right].astype(np.bool_)


def region_means(rgb: NDArray[np.uint8]) -> list[tuple[float, float, float]]:
    means = [skin_mean(rgb, [polygon]) for polygon in REGION_POLYGONS]
    assert all(mean is not None for mean in means), "a fixed polygon covers no pixel"
    return [mean for mean in means if mean is not None]


def round_trip_recordings(
    face: Face, seed: int, quality: int
) -> tuple[Recording, Recording]:
    painter = FacePainter(seed)
    raw_rows = []
    jpeg_rows = []
    for colours in face.recording.regions:
        frame = painter.paint(colours)
        raw_rows.append(region_means(frame))
        decoded = jpeg_rgb(encode_jpeg(frame, quality))
        jpeg_rows.append(region_means(decoded))
    times = face.recording.timestamps_ms
    return (
        Recording(times, np.array(raw_rows, dtype=np.float64)),
        Recording(times, np.array(jpeg_rows, dtype=np.float64)),
    )


def true_face_ibis(face: Face) -> NDArray[np.float64]:
    first_ms = float(face.recording.timestamps_ms[0]) + TRUTH_MARGIN_MS
    last_ms = float(face.recording.timestamps_ms[-1]) - TRUTH_MARGIN_MS
    return np.diff(beats_inside(face.beats_ms, first_ms, last_ms))


def hrv_score(recording: Recording, face: Face) -> HrvScore:
    tracker = tracked(recording)
    kept = accepted(tracker.intervals())
    truth = true_face_ibis(face)
    errors = np.abs(matched_ibi_errors(kept, face.beats_ms))
    reading = tracker.reading()
    snrs = [check.snr_db for check in tracker.window_checks() if check.measured]
    return HrvScore(
        median_snr_db=float(np.median(snrs)),
        accepted_share=len(kept) / truth.size,
        ibi_error_p90_ms=float(np.percentile(errors, 90)) if errors.size else np.inf,
        rmssd_error_ms=None
        if reading.rmssd_ms is None
        else abs(reading.rmssd_ms - rmssd(truth)),
        sdnn_error_ms=None
        if reading.sdnn_ms is None
        else abs(reading.sdnn_ms - sdnn(truth)),
    )


def round_trip(face: Face, seed: int, quality: int = BROWSER_QUALITY) -> RoundTrip:
    raw, jpeg = round_trip_recordings(face, seed, quality)
    return RoundTrip(raw=hrv_score(raw, face), jpeg=hrv_score(jpeg, face))
