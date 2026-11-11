from collections.abc import Iterator
from pathlib import Path

import numpy as np
import pytest
from numpy.typing import NDArray

from pulse_frame.vision.landmarks import FaceLandmarks, FaceTracker
from pulse_frame.vision.motion import MOVING_SHARE_OF_FACE_WIDTH, MotionGate
from tests.frames import REFERENCE_FRAME_MS, SEED
from tests.vision.faces import detect_face, face_from_pixels, face_width

WIDE_FRAME = (1280, 720)
SQUARE_FRAME = (1024, 1024)
FACE_WIDTHS_PX = [200.0, 80.0]
EXACT_WIDTH_PX = 100.0
PINNED_THRESHOLD = 0.01
LARGEST_STILL_JITTER = 0.0032
SHORT_INTERVAL_JITTER = 0.006
SHORT_INTERVAL_MOVE = 0.012
SHORT_INTERVALS_MS = [8, 16]
STRETCH = 3.0
FRAME_MS = 33
START_MS = 10_000
JITTER_SHARE_OF_THRESHOLD = 0.2
SHIFT_SHARE = 0.05
STILL_FRAMES = 60
DIRECTIONS = [(1.0, 0.0), (0.0, 1.0), (-1.0, 0.0), (0.0, -1.0), (0.6, 0.8)]
AXES = {"x": (1.0, 0.0), "y": (0.0, 1.0)}
BELOW = 0.8
ABOVE = 1.2
OUTLIER_SHARE = 0.1
OUTLIER_JUMP = 20.0
MAJORITY_SHARE = 0.6
DROPPED_LANDMARKS = 10


@pytest.fixture(scope="module")
def astronaut_points(
    face_model: Path, astronaut_rgb: NDArray[np.uint8]
) -> Iterator[NDArray[np.float64]]:
    with FaceTracker(face_model) as tracker:
        yield detect_face(tracker, astronaut_rgb, 0).points


def face_pixels(
    points: NDArray[np.float64], width_px: float, frame: tuple[int, int] = WIDE_FRAME
) -> NDArray[np.float64]:
    centred = (points - points.mean(axis=0)) / face_width(points)
    return np.array(frame, dtype=np.float64) / 2.0 + centred * width_px


def threshold_px(pixels: NDArray[np.float64]) -> float:
    return MOVING_SHARE_OF_FACE_WIDTH * face_width(pixels)


def framed(
    pixels: NDArray[np.float64], frame: tuple[int, int] = WIDE_FRAME
) -> FaceLandmarks:
    return face_from_pixels(pixels, frame[0], frame[1])


def jittered(pixels: NDArray[np.float64], rng: np.random.Generator) -> FaceLandmarks:
    limit = JITTER_SHARE_OF_THRESHOLD * threshold_px(pixels)
    return framed(pixels + rng.uniform(-limit, limit, pixels.shape))


def moved(
    pixels: NDArray[np.float64], distance_px: float, direction: tuple[float, float]
) -> NDArray[np.float64]:
    return pixels + distance_px * np.asarray(direction)


def second_frame_moving(
    before: FaceLandmarks, after: FaceLandmarks, interval_ms: int
) -> bool:
    gate = MotionGate()
    assert gate.update(before, START_MS) is False
    return gate.update(after, START_MS + interval_ms)


def test_first_frame_is_still(astronaut_points: NDArray[np.float64]) -> None:
    gate = MotionGate()

    assert gate.update(framed(face_pixels(astronaut_points, 200.0)), START_MS) is False


@pytest.mark.parametrize("width_px", FACE_WIDTHS_PX)
def test_landmark_jitter_of_a_fifth_of_the_threshold_is_still(
    astronaut_points: NDArray[np.float64], width_px: float
) -> None:
    rng = np.random.default_rng(SEED)
    pixels = face_pixels(astronaut_points, width_px)
    gate = MotionGate()

    flags = [
        gate.update(jittered(pixels, rng), START_MS + index * FRAME_MS)
        for index in range(STILL_FRAMES)
    ]

    assert flags == [False] * STILL_FRAMES


@pytest.mark.parametrize("direction", DIRECTIONS)
@pytest.mark.parametrize("width_px", FACE_WIDTHS_PX)
def test_shift_of_five_percent_of_face_width_in_one_frame_is_moving(
    astronaut_points: NDArray[np.float64],
    direction: tuple[float, float],
    width_px: float,
) -> None:
    rng = np.random.default_rng(SEED + 1)
    pixels = face_pixels(astronaut_points, width_px)
    gate = MotionGate()
    for index in range(10):
        gate.update(jittered(pixels, rng), START_MS + index * FRAME_MS)

    shifted = jittered(moved(pixels, SHIFT_SHARE * width_px, direction), rng)

    assert gate.update(shifted, START_MS + 10 * FRAME_MS) is True


@pytest.mark.parametrize("width_px", FACE_WIDTHS_PX)
def test_face_that_stops_after_a_shift_is_still_again_on_the_next_frame(
    astronaut_points: NDArray[np.float64], width_px: float
) -> None:
    rng = np.random.default_rng(SEED + 2)
    pixels = face_pixels(astronaut_points, width_px)
    shifted = moved(pixels, SHIFT_SHARE * width_px, DIRECTIONS[0])
    gate = MotionGate()
    for index in range(10):
        gate.update(jittered(pixels, rng), START_MS + index * FRAME_MS)
    gate.update(jittered(shifted, rng), START_MS + 10 * FRAME_MS)

    flags = [
        gate.update(jittered(shifted, rng), START_MS + index * FRAME_MS)
        for index in range(11, 21)
    ]

    assert flags == [False] * 10


@pytest.mark.parametrize(
    ("share_of_threshold", "expected"), [(BELOW, False), (ABOVE, True)]
)
@pytest.mark.parametrize("axis", list(AXES))
@pytest.mark.parametrize("width_px", FACE_WIDTHS_PX)
def test_pixel_shift_in_a_wide_frame_gives_the_same_decision_along_x_and_y(
    astronaut_points: NDArray[np.float64],
    share_of_threshold: float,
    expected: bool,
    axis: str,
    width_px: float,
) -> None:
    pixels = face_pixels(astronaut_points, width_px)
    distance_px = share_of_threshold * threshold_px(pixels)

    moving = second_frame_moving(
        framed(pixels), framed(moved(pixels, distance_px, AXES[axis])), FRAME_MS
    )

    assert moving is expected


@pytest.mark.parametrize(
    ("share_of_threshold", "expected"), [(BELOW, False), (ABOVE, True)]
)
@pytest.mark.parametrize("interval_ms", [33, 66, 100])
def test_same_pixel_speed_gives_the_same_decision_at_any_frame_interval(
    astronaut_points: NDArray[np.float64],
    share_of_threshold: float,
    expected: bool,
    interval_ms: int,
) -> None:
    pixels = face_pixels(astronaut_points, 200.0)
    speed_px_per_ms = share_of_threshold * threshold_px(pixels) / REFERENCE_FRAME_MS
    distance_px = speed_px_per_ms * interval_ms

    moving = second_frame_moving(
        framed(pixels),
        framed(moved(pixels, distance_px, DIRECTIONS[0])),
        interval_ms,
    )

    assert moving is expected


def test_a_few_landmarks_jumping_while_most_stay_still_is_still(
    astronaut_points: NDArray[np.float64],
) -> None:
    rng = np.random.default_rng(SEED + 3)
    pixels = face_pixels(astronaut_points, 200.0)
    jumpers = rng.choice(
        pixels.shape[0], int(OUTLIER_SHARE * pixels.shape[0]), replace=False
    )
    after = jittered(pixels, rng).points * np.array(WIDE_FRAME, dtype=np.float64)
    after[jumpers] += OUTLIER_JUMP * threshold_px(pixels) * np.array([1.0, 0.0])

    assert second_frame_moving(framed(pixels), framed(after), FRAME_MS) is False


def test_most_landmarks_moving_while_some_stay_still_is_moving(
    astronaut_points: NDArray[np.float64],
) -> None:
    rng = np.random.default_rng(SEED + 4)
    pixels = face_pixels(astronaut_points, 200.0)
    movers = rng.choice(
        pixels.shape[0], int(MAJORITY_SHARE * pixels.shape[0]), replace=False
    )
    after = pixels.copy()
    after[movers] += 2.0 * threshold_px(pixels) * np.array([1.0, 0.0])

    assert second_frame_moving(framed(pixels), framed(after), FRAME_MS) is True


def test_change_in_landmark_count_is_still(
    astronaut_points: NDArray[np.float64],
) -> None:
    pixels = face_pixels(astronaut_points, 200.0)
    fewer = moved(pixels, SHIFT_SHARE * 200.0, DIRECTIONS[0])[:-DROPPED_LANDMARKS]

    assert second_frame_moving(framed(pixels), framed(fewer), FRAME_MS) is False


def exact_face(
    points: NDArray[np.float64], width_px: float, height_scale: float = 1.0
) -> NDArray[np.float64]:
    centred = (points - points.min(axis=0)) / face_width(points)
    centred[:, 1] *= height_scale
    corner = np.array(SQUARE_FRAME, dtype=np.float64) / 2.0 - width_px
    pixels = np.round(corner + centred * width_px)
    assert face_width(pixels) == width_px
    return pixels


def square(pixels: NDArray[np.float64]) -> FaceLandmarks:
    return framed(pixels, SQUARE_FRAME)


def alternating_flags(
    pixels: NDArray[np.float64], step_px: float, interval_ms: int
) -> list[bool]:
    gate = MotionGate()
    flags = []
    for index in range(STILL_FRAMES):
        direction = DIRECTIONS[(index // 2) % len(DIRECTIONS)]
        offset = step_px * (index % 2)
        frame = square(moved(pixels, offset, direction))
        flags.append(gate.update(frame, START_MS + index * interval_ms))
    return flags


def test_moving_threshold_is_one_percent_of_the_face_width() -> None:
    assert MOVING_SHARE_OF_FACE_WIDTH == PINNED_THRESHOLD


def test_jitter_of_the_largest_measured_still_share_stays_still(
    astronaut_points: NDArray[np.float64],
) -> None:
    pixels = exact_face(astronaut_points, EXACT_WIDTH_PX)

    flags = alternating_flags(pixels, LARGEST_STILL_JITTER * EXACT_WIDTH_PX, FRAME_MS)

    assert flags == [False] * STILL_FRAMES


@pytest.mark.parametrize(
    ("share_of_width", "expected"),
    [(0.0099, False), (PINNED_THRESHOLD, False), (0.0101, True)],
    ids=["just_below", "exactly_at", "just_above"],
)
def test_one_frame_step_is_moving_only_when_strictly_above_one_percent_of_width(
    astronaut_points: NDArray[np.float64], share_of_width: float, expected: bool
) -> None:
    pixels = exact_face(astronaut_points, EXACT_WIDTH_PX)
    gate = MotionGate()
    gate.update(square(pixels), START_MS)

    moving = gate.update(
        square(moved(pixels, share_of_width * EXACT_WIDTH_PX, DIRECTIONS[0])),
        START_MS + FRAME_MS,
    )

    assert gate.share == pytest.approx(share_of_width, rel=1e-9)
    assert moving is expected


def test_step_of_exactly_one_percent_measures_exactly_the_threshold(
    astronaut_points: NDArray[np.float64],
) -> None:
    pixels = exact_face(astronaut_points, EXACT_WIDTH_PX)
    gate = MotionGate()
    gate.update(square(pixels), START_MS)

    gate.update(
        square(moved(pixels, PINNED_THRESHOLD * EXACT_WIDTH_PX, DIRECTIONS[0])),
        START_MS + FRAME_MS,
    )

    assert gate.share == PINNED_THRESHOLD


@pytest.mark.parametrize(
    ("height_scale", "share_of_width", "expected"),
    [(STRETCH, 0.0105, True), (1.0 / STRETCH, 0.0095, False)],
    ids=["tall_face_just_above", "flat_face_just_below"],
)
@pytest.mark.parametrize("direction", [(1.0, 0.0), (0.0, 1.0)], ids=["x", "y"])
def test_threshold_follows_the_face_width_not_its_height(
    astronaut_points: NDArray[np.float64],
    height_scale: float,
    share_of_width: float,
    expected: bool,
    direction: tuple[float, float],
) -> None:
    pixels = exact_face(astronaut_points, EXACT_WIDTH_PX, height_scale)
    stretched_height = float(np.ptp(pixels[:, 1]))
    assert abs(stretched_height - EXACT_WIDTH_PX) > EXACT_WIDTH_PX / 2.0

    moving = second_frame_moving(
        square(pixels),
        square(moved(pixels, share_of_width * EXACT_WIDTH_PX, direction)),
        FRAME_MS,
    )

    assert moving is expected


@pytest.mark.parametrize("interval_ms", SHORT_INTERVALS_MS)
def test_sub_threshold_jitter_at_frame_intervals_shorter_than_33_ms_stays_still(
    astronaut_points: NDArray[np.float64], interval_ms: int
) -> None:
    pixels = exact_face(astronaut_points, EXACT_WIDTH_PX)

    flags = alternating_flags(
        pixels, SHORT_INTERVAL_JITTER * EXACT_WIDTH_PX, interval_ms
    )

    assert flags == [False] * STILL_FRAMES


@pytest.mark.parametrize("interval_ms", SHORT_INTERVALS_MS)
def test_step_above_the_threshold_at_a_frame_interval_shorter_than_33_ms_is_moving(
    astronaut_points: NDArray[np.float64], interval_ms: int
) -> None:
    pixels = exact_face(astronaut_points, EXACT_WIDTH_PX)

    moving = second_frame_moving(
        square(pixels),
        square(moved(pixels, SHORT_INTERVAL_MOVE * EXACT_WIDTH_PX, DIRECTIONS[0])),
        interval_ms,
    )

    assert moving is True


def test_change_of_frame_resolution_is_still_with_a_zero_share(
    astronaut_points: NDArray[np.float64],
) -> None:
    face = framed(face_pixels(astronaut_points, 200.0))
    half = FaceLandmarks(
        points=face.points,
        width=WIDE_FRAME[0] // 2,
        height=WIDE_FRAME[1] // 2,
        in_frame=face.in_frame,
    )
    gate = MotionGate()
    gate.update(face, START_MS)

    moving = gate.update(half, START_MS + FRAME_MS)

    assert moving is False
    assert gate.share == 0.0
