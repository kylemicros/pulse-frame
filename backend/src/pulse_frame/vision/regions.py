import cv2
import numpy as np
from numpy.typing import NDArray
from scipy.spatial import ConvexHull, QhullError

from pulse_frame.vision.landmarks import FaceLandmarks

FOREHEAD: tuple[int, ...] = (104, 69, 108, 151, 337, 299, 333)
RIGHT_CHEEK: tuple[int, ...] = (
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
)
LEFT_CHEEK: tuple[int, ...] = (
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
)
REGIONS = (FOREHEAD, LEFT_CHEEK, RIGHT_CHEEK)
REGION_NAMES = ("forehead", "left_cheek", "right_cheek")
MASK_ON = 255


def region_polygons(face: FaceLandmarks) -> list[NDArray[np.float64]]:
    return list(named_region_polygons(face).values())


def named_region_polygons(face: FaceLandmarks) -> dict[str, NDArray[np.float64]]:
    hulls = {
        name: region_hull(face, indices)
        for name, indices in zip(REGION_NAMES, REGIONS, strict=True)
    }
    return {name: hull for name, hull in hulls.items() if hull is not None}


def region_hull(
    face: FaceLandmarks, indices: tuple[int, ...]
) -> NDArray[np.float64] | None:
    chosen = list(indices)
    if not bool(np.all(face.in_frame[chosen])):
        return None
    return hull_polygon(face.points[chosen])


def hull_polygon(points: NDArray[np.float64]) -> NDArray[np.float64] | None:
    try:
        hull = ConvexHull(points)
    except QhullError:
        return None
    if hull.volume <= 0.0:
        return None
    return points[hull.vertices]


def skin_mean(
    rgb: NDArray[np.uint8], polygons: list[NDArray[np.float64]]
) -> tuple[float, float, float] | None:
    if not polygons:
        return None
    mask = region_mask(rgb.shape[0], rgb.shape[1], polygons)
    if cv2.countNonZero(mask) == 0:
        return None
    red, green, blue, _ = cv2.mean(rgb, mask=mask)
    return float(red), float(green), float(blue)


def region_mask(
    height: int, width: int, polygons: list[NDArray[np.float64]]
) -> NDArray[np.uint8]:
    mask = np.zeros((height, width), dtype=np.uint8)
    scale = np.array([width, height], dtype=np.float64)
    for polygon in polygons:
        corners = np.round(polygon * scale).astype(np.int32)
        cv2.fillPoly(mask, [corners], MASK_ON)
    return mask
