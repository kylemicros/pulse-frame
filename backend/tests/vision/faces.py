import numpy as np
from mediapipe.tasks.python.vision import FaceLandmarksConnections
from numpy.typing import NDArray

from pulse_frame.vision.landmarks import FaceLandmarks, FaceTracker

type OutlinePoint = int | tuple[int, int]


def landmark_indices(
    connections: list[FaceLandmarksConnections.Connection],
) -> tuple[int, ...]:
    return tuple(sorted({i for c in connections for i in (c.start, c.end)}))


EXCLUDED_FEATURES: dict[str, tuple[int, ...]] = {
    "left_eye": landmark_indices(FaceLandmarksConnections.FACE_LANDMARKS_LEFT_EYE),
    "right_eye": landmark_indices(FaceLandmarksConnections.FACE_LANDMARKS_RIGHT_EYE),
    "left_eyebrow": landmark_indices(
        FaceLandmarksConnections.FACE_LANDMARKS_LEFT_EYEBROW
    ),
    "right_eyebrow": landmark_indices(
        FaceLandmarksConnections.FACE_LANDMARKS_RIGHT_EYEBROW
    ),
    "lips": landmark_indices(FaceLandmarksConnections.FACE_LANDMARKS_LIPS),
}

FEATURE_AREAS: dict[str, tuple[int, ...]] = EXCLUDED_FEATURES | {
    "nose": landmark_indices(FaceLandmarksConnections.FACE_LANDMARKS_NOSE),
}

EYES = EXCLUDED_FEATURES["left_eye"] + EXCLUDED_FEATURES["right_eye"]
EYEBROWS = EXCLUDED_FEATURES["left_eyebrow"] + EXCLUDED_FEATURES["right_eyebrow"]
FACE_OVAL = landmark_indices(FaceLandmarksConnections.FACE_LANDMARKS_FACE_OVAL)
NOSE_TIP = 1
MID_FOREHEAD: tuple[OutlinePoint, ...] = (
    104,
    69,
    108,
    151,
    337,
    299,
    333,
    9,
    (151, 10),
    (108, 109),
    (337, 338),
    (69, 67),
    (299, 297),
)
BIG_LEFT_CHEEK: tuple[OutlinePoint, ...] = (
    345,
    346,
    347,
    348,
    329,
    277,
    355,
    371,
    266,
    425,
    411,
    352,
    280,
    330,
    376,
    427,
    426,
    423,
    433,
    416,
    434,
    436,
    432,
)
BIG_RIGHT_CHEEK: tuple[OutlinePoint, ...] = (
    116,
    117,
    118,
    119,
    100,
    47,
    126,
    142,
    36,
    205,
    187,
    123,
    50,
    101,
    147,
    207,
    206,
    203,
    213,
    192,
    214,
    216,
    212,
)
EXPECTED_OUTLINES: dict[str, tuple[OutlinePoint, ...]] = {
    "forehead": MID_FOREHEAD,
    "left_cheek": BIG_LEFT_CHEEK,
    "right_cheek": BIG_RIGHT_CHEEK,
}
CHEEKS_CUT_AT_ROW = 59
LEFT_CHEEK_CUT_AT_COLUMN = 130
NO_REGION_TOP_ROW = 45
NO_REGION_COLUMNS = (95, 130)


def outline_landmarks(outline: tuple[OutlinePoint, ...]) -> tuple[int, ...]:
    return tuple(
        index
        for item in outline
        for index in ((item,) if isinstance(item, int) else item)
    )


def outline_points(
    face: FaceLandmarks, outline: tuple[OutlinePoint, ...]
) -> NDArray[np.float64]:
    return np.array(
        [
            face.points[item]
            if isinstance(item, int)
            else face.points[list(item)].mean(axis=0)
            for item in outline
        ],
        dtype=np.float64,
    )


def detect_face(
    tracker: FaceTracker, rgb: NDArray[np.uint8], timestamp_ms: int
) -> FaceLandmarks:
    face = tracker.detect(rgb, timestamp_ms)
    assert face is not None, "No face found in the astronaut fixture."
    return face


def face_width(points: NDArray[np.float64]) -> float:
    return float(np.ptp(points[:, 0]))


def face_width_px(face: FaceLandmarks) -> float:
    return face_width(face.points) * face.width


def face_from_pixels(
    pixels: NDArray[np.float64], width: int, height: int
) -> FaceLandmarks:
    return FaceLandmarks(
        points=pixels / np.array([width, height], dtype=np.float64),
        width=width,
        height=height,
        in_frame=np.ones(pixels.shape[0], dtype=np.bool_),
    )


def crop_above_brows(rgb: NDArray[np.uint8], face: FaceLandmarks) -> NDArray[np.uint8]:
    brow_top_px = face.points[list(EYEBROWS), 1].min() * face.height
    rows = int(np.ceil(brow_top_px)) + 2
    return np.ascontiguousarray(rgb[rows:])


def crop_through_both_cheeks_from_below(rgb: NDArray[np.uint8]) -> NDArray[np.uint8]:
    return np.ascontiguousarray(rgb[:CHEEKS_CUT_AT_ROW])


def crop_through_left_cheek_from_the_right(
    rgb: NDArray[np.uint8],
) -> NDArray[np.uint8]:
    return np.ascontiguousarray(rgb[:, :LEFT_CHEEK_CUT_AT_COLUMN])


def crop_to_a_face_without_usable_regions(
    rgb: NDArray[np.uint8],
) -> NDArray[np.uint8]:
    left, right = NO_REGION_COLUMNS
    return np.ascontiguousarray(rgb[NO_REGION_TOP_ROW:, left:right])
