from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
from numpy.typing import NDArray

from pulse_frame.monitor import processor as processor_module
from pulse_frame.monitor.processor import FrameProcessor, FrameResult, Patch
from pulse_frame.signal.tracker import Reading
from pulse_frame.vision.landmarks import FaceLandmarks, FaceTracker
from pulse_frame.vision.regions import (
    FOREHEAD,
    named_region_polygons,
    outline_landmarks,
)
from tests.frames import (
    FRAME_STEP_MS,
    SEED,
    TRUE_BPM,
    FrameClock,
    pulsed_frame,
)

PATCH_NAMES = {"forehead", "left_cheek", "right_cheek"}
CHEEK_NAMES = ("left_cheek", "right_cheek")
FIRST_MS = 1000
CORNER_INSET_PX = 0.25
CORNER_RADIUS_PX = 0.15
SHORT_FRAMES = 30
LONG_FRAMES = 80
GRID_STEP_MS = 1000.0 / 30.0
GRID_TOLERANCE_MS = 1e-6


def test_frame_result_patches_default_to_an_empty_mapping() -> None:
    result = FrameResult(
        face=False,
        regions=[],
        moving=False,
        motion_share=0.0,
        reading=Reading(state="acquiring", bpm=None, quality_db=None),
    )

    assert result.patches == {}


def test_processor_fills_all_three_patches_with_and_without_a_face(
    face_model: Path, astronaut_rgb: NDArray[np.uint8]
) -> None:
    with FrameProcessor(face_model) as processor:
        face = processor.process(astronaut_rgb, FIRST_MS)
        blank = processor.process(np.zeros_like(astronaut_rgb), FIRST_MS + 33)

    assert set(face.patches) == PATCH_NAMES
    assert set(blank.patches) == PATCH_NAMES
    assert face.regions
    assert blank.regions == []


def test_processor_waveform_is_empty_until_the_tracker_spans_a_pos_window(
    face_model: Path, astronaut_rgb: NDArray[np.uint8]
) -> None:
    rng = np.random.default_rng(SEED)
    clock = FrameClock(start_ms=FIRST_MS, step_ms=FRAME_STEP_MS)

    with FrameProcessor(face_model) as processor:
        for _ in range(SHORT_FRAMES):
            t = clock.next_ms()
            frame = pulsed_frame(astronaut_rgb, rng, TRUE_BPM, 0.0, t / 1000)
            processor.process(frame, t)
        short = processor.waveform()
        newest = FIRST_MS
        for _ in range(LONG_FRAMES - SHORT_FRAMES):
            newest = clock.next_ms()
            frame = pulsed_frame(astronaut_rgb, rng, TRUE_BPM, 0.0, newest / 1000)
            processor.process(frame, newest)
        long = processor.waveform()

    assert short == []
    assert long
    times = np.array([t for t, _ in long])
    assert np.all(np.abs(np.diff(times) - GRID_STEP_MS) <= GRID_TOLERANCE_MS)
    assert times[0] >= FIRST_MS
    assert newest - GRID_STEP_MS <= times[-1] <= newest
    assert all(np.isfinite(value) for _, value in long)


class ScriptedFaces:
    def __init__(self, face: FaceLandmarks) -> None:
        self.face = face

    def detect(self, rgb: NDArray[np.uint8], timestamp_ms: int) -> FaceLandmarks:
        return self.face

    def close(self) -> None:
        return None


def forehead_inside_the_last_pixel_corner(face: FaceLandmarks) -> FaceLandmarks:
    indices = sorted(set(outline_landmarks(FOREHEAD)))
    angles = np.linspace(0.0, 2.0 * np.pi, len(indices), endpoint=False)
    corner = np.array([face.width, face.height], dtype=np.float64) - CORNER_INSET_PX
    ring = np.stack([np.cos(angles), np.sin(angles)], axis=1) * CORNER_RADIUS_PX
    points = face.points.copy()
    points[indices] = (corner + ring) / np.array([face.width, face.height])
    return replace(face, points=points, in_frame=np.ones(len(points), dtype=np.bool_))


def test_patch_whose_hull_covers_no_pixel_is_unusable_while_the_face_is_present(
    face_model: Path,
    astronaut_rgb: NDArray[np.uint8],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with FaceTracker(face_model) as tracker:
        detected = tracker.detect(astronaut_rgb, FIRST_MS)
    assert detected is not None
    tucked = forehead_inside_the_last_pixel_corner(detected)
    hulls = named_region_polygons(tucked)
    assert set(hulls) == PATCH_NAMES
    monkeypatch.setattr(
        processor_module, "FaceTracker", lambda model: ScriptedFaces(tucked)
    )

    with FrameProcessor(face_model) as processor:
        result = processor.process(astronaut_rgb, FIRST_MS)

    assert result.face is True
    assert result.patches["forehead"] == Patch(usable=False, outline=None)
    for name in CHEEK_NAMES:
        patch = result.patches[name]
        assert patch.usable is True
        assert patch.outline is not None
        assert np.array_equal(patch.outline, hulls[name])
