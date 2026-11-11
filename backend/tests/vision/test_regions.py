from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
from numpy.typing import NDArray
from scipy.spatial import ConvexHull

from pulse_frame.vision.landmarks import FaceLandmarks, FaceTracker
from pulse_frame.vision.regions import (
    FOREHEAD,
    LEFT_CHEEK,
    RIGHT_CHEEK,
    named_region_polygons,
    region_mask,
    region_polygons,
    skin_mean,
)
from tests.vision.faces import (
    EXCLUDED_FEATURES,
    EXPECTED_OUTLINES,
    EYEBROWS,
    EYES,
    FACE_OVAL,
    FEATURE_AREAS,
    NOSE_TIP,
    OutlinePoint,
    crop_above_brows,
    crop_through_both_cheeks_from_below,
    crop_through_left_cheek_from_the_right,
    detect_face,
    outline_landmarks,
    outline_points,
)

REGIONS = {"forehead": FOREHEAD, "left_cheek": LEFT_CHEEK, "right_cheek": RIGHT_CHEEK}
BASE_OUTLINES: dict[str, tuple[int, ...]] = {
    "forehead": (104, 69, 108, 151, 337, 299, 333),
    "left_cheek": (
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
    ),
    "right_cheek": (
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
    ),
}
AREA_RATIO_OVER_BASE = {
    "forehead": (8.18, 0.25),
    "left_cheek": (1.348, 0.008),
    "right_cheek": (1.348, 0.008),
}
PAIR_ONLY_FOREHEAD_LANDMARKS = (10, 109, 338, 67, 297)
VERTEX_TOLERANCE = 1e-9
SKIN = (200, 120, 90)
BACKGROUND = (0, 0, 255)
LANDMARK_COUNT = 478
MIN_MASK_PIXELS = {"forehead": 165, "left_cheek": 183, "right_cheek": 176}
EDGE_CROPS = {
    "bottom": (crop_through_both_cheeks_from_below, 1, ["forehead"]),
    "right": (crop_through_left_cheek_from_the_right, 0, ["forehead", "right_cheek"]),
}


@pytest.fixture(scope="module")
def face(face_model: Path, astronaut_rgb: NDArray[np.uint8]) -> Iterator[FaceLandmarks]:
    with FaceTracker(face_model) as tracker:
        yield detect_face(tracker, astronaut_rgb, 0)


@pytest.fixture(scope="module")
def polygons(face: FaceLandmarks) -> list[NDArray[np.float64]]:
    return region_polygons(face)


def edge_crosses(polygon: NDArray[np.float64], point: NDArray[np.float64]) -> NDArray:
    starts = polygon
    ends = np.roll(polygon, -1, axis=0)
    edge = ends - starts
    to_point = point - starts
    return edge[:, 0] * to_point[:, 1] - edge[:, 1] * to_point[:, 0]


def inside_or_on_edge(polygon: NDArray[np.float64], point: NDArray[np.float64]) -> bool:
    crosses = edge_crosses(polygon, point)
    return bool(
        np.all(crosses >= -VERTEX_TOLERANCE) or np.all(crosses <= VERTEX_TOLERANCE)
    )


def turn_signs(polygon: NDArray[np.float64]) -> NDArray[np.float64]:
    edge = np.roll(polygon, -1, axis=0) - polygon
    following = np.roll(edge, -1, axis=0)
    return edge[:, 0] * following[:, 1] - edge[:, 1] * following[:, 0]


def pixel_area(face: FaceLandmarks, polygon: NDArray[np.float64]) -> float:
    return shoelace_area(to_pixels(face, polygon))


def shoelace_area(polygon: NDArray[np.float64]) -> float:
    x, y = polygon[:, 0], polygon[:, 1]
    return 0.5 * abs(float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))))


def centroid(polygon: NDArray[np.float64]) -> NDArray[np.float64]:
    return polygon.mean(axis=0)


def built_from(
    polygon: NDArray[np.float64], region_points: NDArray[np.float64]
) -> bool:
    distances = np.linalg.norm(polygon[:, None, :] - region_points[None, :, :], axis=2)
    return bool(np.all(distances.min(axis=1) <= VERTEX_TOLERANCE))


def regions_built_from(
    face: FaceLandmarks, polygons: list[NDArray[np.float64]]
) -> list[str]:
    return sorted(
        name
        for name, outline in REGIONS.items()
        for polygon in polygons
        if built_from(polygon, outline_points(face, outline))
    )


def to_pixels(face: FaceLandmarks, points: NDArray[np.float64]) -> NDArray:
    return points * np.array([face.width, face.height], dtype=np.float64)


def hull_vertex_landmark(face: FaceLandmarks, outline: tuple[OutlinePoint, ...]) -> int:
    hull = ConvexHull(outline_points(face, outline))
    return outline_landmarks((outline[int(hull.vertices[0])],))[0]


def region_named(
    face: FaceLandmarks, polygons: list[NDArray[np.float64]], name: str
) -> NDArray[np.float64]:
    region_points = outline_points(face, REGIONS[name])
    matches = [p for p in polygons if built_from(p, region_points)]
    assert len(matches) == 1
    return matches[0]


def feature_mask(face: FaceLandmarks, indices: tuple[int, ...]) -> NDArray[np.uint8]:
    points = face.points[list(indices)]
    return region_mask(face.height, face.width, [points[ConvexHull(points).vertices]])


def test_region_polygons_are_three_non_empty_convex_polygons_inside_the_image(
    polygons: list[NDArray[np.float64]],
) -> None:
    assert len(polygons) == 3
    for polygon in polygons:
        assert polygon.dtype == np.float64
        assert polygon.ndim == 2
        assert polygon.shape[1] == 2
        assert polygon.shape[0] >= 3
        assert np.all((polygon >= 0.0) & (polygon <= 1.0))
        assert shoelace_area(polygon) > 0.0
        turns = turn_signs(polygon)
        assert np.all(turns >= -VERTEX_TOLERANCE) or np.all(turns <= VERTEX_TOLERANCE)


@pytest.mark.parametrize("region_name", list(REGIONS))
def test_each_region_is_the_convex_hull_of_its_outline_points(
    face: FaceLandmarks, polygons: list[NDArray[np.float64]], region_name: str
) -> None:
    outline = REGIONS[region_name]
    assert all(
        isinstance(item, int)
        or (len(item) == 2 and all(isinstance(i, int) for i in item))
        for item in outline
    )
    assert all(0 <= i < face.points.shape[0] for i in outline_landmarks(outline))
    region_points = outline_points(face, outline)
    hull_area = ConvexHull(region_points).volume

    matches = [p for p in polygons if built_from(p, region_points)]
    assert len(matches) == 1
    assert shoelace_area(matches[0]) == pytest.approx(hull_area, rel=1e-9)


@pytest.mark.parametrize("feature", list(EXCLUDED_FEATURES))
def test_no_eye_eyebrow_or_lip_landmark_lies_inside_any_region(
    face: FaceLandmarks, polygons: list[NDArray[np.float64]], feature: str
) -> None:
    inside = [
        index
        for index in EXCLUDED_FEATURES[feature]
        for polygon in polygons
        if inside_or_on_edge(polygon, face.points[index])
    ]

    assert inside == []


def test_no_face_oval_landmark_lies_inside_or_on_the_forehead(
    face: FaceLandmarks,
) -> None:
    forehead_points = outline_points(face, FOREHEAD)
    forehead = forehead_points[ConvexHull(forehead_points).vertices]

    on_or_inside = [
        index for index in FACE_OVAL if inside_or_on_edge(forehead, face.points[index])
    ]

    assert on_or_inside == []


def test_regions_are_a_forehead_above_the_brows_and_cheeks_either_side_of_the_nose(
    face: FaceLandmarks, polygons: list[NDArray[np.float64]]
) -> None:
    by_height = sorted(polygons, key=lambda p: centroid(p)[1])
    forehead, cheeks = by_height[0], by_height[1:]
    brow_y = face.points[list(EYEBROWS), 1].min()
    eye_y = face.points[list(EYES), 1].mean()
    nose_x = face.points[NOSE_TIP, 0]

    assert centroid(forehead)[1] < brow_y
    assert all(centroid(cheek)[1] > eye_y for cheek in cheeks)
    cheek_xs = sorted(centroid(cheek)[0] for cheek in cheeks)
    assert cheek_xs[0] < nose_x < cheek_xs[1]


@pytest.mark.parametrize("region_name", list(REGIONS))
def test_region_with_a_landmark_outside_the_frame_is_dropped_and_others_kept(
    face: FaceLandmarks, region_name: str
) -> None:
    in_frame = np.ones(face.points.shape[0], dtype=np.bool_)
    in_frame[hull_vertex_landmark(face, REGIONS[region_name])] = False
    partly_outside = replace(face, in_frame=in_frame)

    polygons = region_polygons(partly_outside)

    assert len(polygons) == 2
    assert regions_built_from(face, polygons) == sorted(
        name for name in REGIONS if name != region_name
    )


def test_face_cut_off_above_the_brows_keeps_both_cheeks_and_drops_the_forehead(
    face_model: Path, face: FaceLandmarks, astronaut_rgb: NDArray[np.uint8]
) -> None:
    cropped = crop_above_brows(astronaut_rgb, face)
    with FaceTracker(face_model) as tracker:
        cut = detect_face(tracker, cropped, 0)

    polygons = region_polygons(cut)

    assert regions_built_from(cut, polygons) == ["left_cheek", "right_cheek"]
    assert len(polygons) == 2
    assert all(shoelace_area(polygon) > 0.0 for polygon in polygons)


@pytest.mark.parametrize("layout", ["one_point", "one_line"])
def test_regions_without_area_are_dropped(layout: str) -> None:
    if layout == "one_point":
        points = np.full((LANDMARK_COUNT, 2), 0.5)
    else:
        points = np.column_stack(
            (np.linspace(0.2, 0.8, LANDMARK_COUNT), np.full(LANDMARK_COUNT, 0.5))
        )
    flat = FaceLandmarks(
        points=points,
        width=256,
        height=256,
        in_frame=np.ones(LANDMARK_COUNT, dtype=np.bool_),
    )

    assert region_polygons(flat) == []


def test_skin_mean_on_the_fixture_is_finite_and_skin_like(
    astronaut_rgb: NDArray[np.uint8], polygons: list[NDArray[np.float64]]
) -> None:
    mean = skin_mean(astronaut_rgb, polygons)

    assert mean is not None
    assert len(mean) == 3
    assert all(isinstance(value, float) for value in mean)
    assert np.all(np.isfinite(mean))
    assert all(0.0 <= value <= 255.0 for value in mean)
    red, _, blue = mean
    assert red > blue


def test_skin_mean_averages_only_pixels_inside_the_polygons() -> None:
    image = np.empty((100, 100, 3), dtype=np.uint8)
    image[:, :] = BACKGROUND
    image[10:70, 10:70] = SKIN
    square = np.array([[0.2, 0.2], [0.6, 0.2], [0.6, 0.6], [0.2, 0.6]])

    mean = skin_mean(image, [square])

    assert mean is not None
    assert mean == pytest.approx(SKIN, abs=1e-6)


def test_skin_mean_maps_x_to_width_and_y_to_height_on_a_wide_image() -> None:
    image = np.empty((80, 160, 3), dtype=np.uint8)
    image[:, :] = BACKGROUND
    image[15:46, 30:91] = SKIN
    square = np.array([[0.25, 0.25], [0.5, 0.25], [0.5, 0.5], [0.25, 0.5]])

    mean = skin_mean(image, [square])

    assert mean is not None
    assert mean == pytest.approx(SKIN, abs=1e-6)


def test_skin_mean_of_a_polygon_wholly_outside_the_image_is_none() -> None:
    image = np.full((100, 100, 3), 128, dtype=np.uint8)
    outside = np.array([[1.2, 1.2], [1.6, 1.2], [1.6, 1.6], [1.2, 1.6]])

    assert skin_mean(image, [outside]) is None


def test_skin_mean_without_polygons_is_none() -> None:
    image = np.full((100, 100, 3), 128, dtype=np.uint8)

    assert skin_mean(image, []) is None


@pytest.mark.parametrize("edge", list(EDGE_CROPS))
def test_face_cut_at_the_bottom_or_right_edge_marks_those_points_outside(
    face_model: Path, astronaut_rgb: NDArray[np.uint8], edge: str
) -> None:
    crop, axis, kept = EDGE_CROPS[edge]
    with FaceTracker(face_model) as tracker:
        cut = detect_face(tracker, crop(astronaut_rgb), 0)

    polygons = region_polygons(cut)

    outside = ~cut.in_frame
    assert bool(np.any(outside))
    assert bool(np.any(cut.in_frame))
    assert np.all(cut.points[outside, axis] == 1.0)
    assert regions_built_from(cut, polygons) == kept
    assert len(polygons) == len(kept)


@pytest.mark.parametrize("region_name", list(REGIONS))
def test_each_region_on_the_fixture_covers_at_least_its_pinned_pixel_count(
    face: FaceLandmarks, polygons: list[NDArray[np.float64]], region_name: str
) -> None:
    region = region_named(face, polygons, region_name)

    mask = region_mask(face.height, face.width, [region])

    assert np.count_nonzero(mask) >= MIN_MASK_PIXELS[region_name]


@pytest.mark.parametrize("region_name", list(EXPECTED_OUTLINES))
def test_each_named_region_on_the_fixture_is_the_hull_of_its_larger_outline(
    face: FaceLandmarks, region_name: str
) -> None:
    expected_points = outline_points(face, EXPECTED_OUTLINES[region_name])
    expected = expected_points[ConvexHull(expected_points).vertices]

    region = named_region_polygons(face)[region_name]

    assert region.shape == expected.shape
    assert built_from(region, expected)
    assert shoelace_area(region) == pytest.approx(shoelace_area(expected), rel=1e-9)


@pytest.mark.parametrize("region_name", list(AREA_RATIO_OVER_BASE))
def test_each_region_covers_its_measured_multiple_of_the_base_outline_area(
    face: FaceLandmarks, region_name: str
) -> None:
    base_points = face.points[list(BASE_OUTLINES[region_name])]
    base = base_points[ConvexHull(base_points).vertices]
    ratio, tolerance = AREA_RATIO_OVER_BASE[region_name]

    region = named_region_polygons(face)[region_name]

    assert pixel_area(face, region) / pixel_area(face, base) == pytest.approx(
        ratio, abs=tolerance
    )


@pytest.mark.parametrize("feature", list(FEATURE_AREAS))
def test_no_region_mask_shares_a_pixel_with_an_eye_brow_lip_or_nose_area(
    face: FaceLandmarks, feature: str
) -> None:
    feature_pixels = feature_mask(face, FEATURE_AREAS[feature]) > 0

    shared = {
        name: int(
            np.count_nonzero(
                feature_pixels & (region_mask(face.height, face.width, [region]) > 0)
            )
        )
        for name, region in named_region_polygons(face).items()
    }

    assert len(shared) == 3
    assert shared == {"forehead": 0, "left_cheek": 0, "right_cheek": 0}


@pytest.mark.parametrize("landmark", PAIR_ONLY_FOREHEAD_LANDMARKS)
def test_forehead_pair_point_out_of_frame_drops_only_the_forehead(
    face: FaceLandmarks, landmark: int
) -> None:
    in_frame = np.ones(face.points.shape[0], dtype=np.bool_)
    in_frame[landmark] = False
    partly_outside = replace(face, in_frame=in_frame)

    named = named_region_polygons(partly_outside)

    assert sorted(named) == ["left_cheek", "right_cheek"]
