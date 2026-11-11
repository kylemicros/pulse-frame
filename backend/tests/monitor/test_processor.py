import math
from collections.abc import Callable, Iterator
from pathlib import Path

import cv2
import numpy as np
import pytest
from numpy.typing import NDArray

from pulse_frame.monitor.processor import FrameProcessor, FrameResult
from pulse_frame.signal.tracker import MAX_GAP_MS, UPDATE_INTERVAL_MS, Reading
from pulse_frame.vision.landmarks import FaceTracker
from pulse_frame.vision.motion import MOVING_SHARE_OF_FACE_WIDTH
from pulse_frame.vision.regions import named_region_polygons
from tests.frames import (
    PULSE_STEP_MS,
    REFERENCE_FRAME_MS,
    SEED,
    SHIFT_SAFETY,
    TRUE_BPM,
    FrameClock,
    pulse_timestamps,
    pulsed_frame,
    shifted_right,
)
from tests.signal.synthetic import PULSE_SIGNATURE
from tests.signal.tracking import assert_ok_within_one_bpm
from tests.vision.faces import (
    crop_above_brows,
    crop_to_a_face_without_usable_regions,
    detect_face,
    face_width_px,
)

FRAME_COUNT = 30
SETTLED_BY_MS = 19_900
OK_FROM_MS = 21_000
PULSE_S = 22.0
FOLLOW_S = 1.5
RESTART_WITHIN_MS = MAX_GAP_MS + PULSE_STEP_MS
NO_REGION_STEP_PX = 3
STILL_BEFORE_CHANGE = int(UPDATE_INTERVAL_MS / 2 / PULSE_STEP_MS)
FOREHEAD_FLICKER_BPM = 120.0
FOREHEAD_FLICKER_DEPTH = 0.03
FLICKER_WITHIN_BPM = 10.0

type Trace = list[tuple[int, FrameResult]]
type Transform = Callable[[NDArray[np.uint8]], NDArray[np.uint8]]
type TimedTransform = Callable[[NDArray[np.uint8], int], NDArray[np.uint8]]


@pytest.fixture(scope="module")
def fixture_face_width_px(face_model: Path, astronaut_rgb: NDArray[np.uint8]) -> float:
    with FaceTracker(face_model) as tracker:
        return face_width_px(detect_face(tracker, astronaut_rgb, 0))


@pytest.fixture(scope="module")
def forehead_cropped(face_model: Path, astronaut_rgb: NDArray[np.uint8]) -> Transform:
    with FaceTracker(face_model) as tracker:
        face = detect_face(tracker, astronaut_rgb, 0)
    return lambda rgb: crop_above_brows(rgb, face)


@pytest.fixture(scope="module")
def forehead_mask(
    face_model: Path, astronaut_rgb: NDArray[np.uint8]
) -> NDArray[np.bool_]:
    with FaceTracker(face_model) as tracker:
        face = detect_face(tracker, astronaut_rgb, 0)
    polygon = named_region_polygons(face)["forehead"]
    height, width = astronaut_rgb.shape[:2]
    corners = np.round(polygon * np.array([width, height])).astype(np.int32)
    mask = np.zeros((height, width), dtype=np.uint8)
    cv2.fillPoly(mask, [corners], 1)
    return mask.astype(np.bool_)


@pytest.fixture
def processor(face_model: Path) -> Iterator[FrameProcessor]:
    with FrameProcessor(face_model) as fresh:
        yield fresh


class PulsedFace:
    def __init__(self, rgb: NDArray[np.uint8], seed: int) -> None:
        self.rgb = rgb
        self.rng = np.random.default_rng(seed)
        self.phase = float(self.rng.uniform(0.0, 2.0 * np.pi))

    def frames(
        self,
        processor: FrameProcessor,
        timestamps: list[int],
        transform: Transform | None = None,
        timed: TimedTransform | None = None,
    ) -> Trace:
        trace = []
        for timestamp_ms in timestamps:
            frame = pulsed_frame(
                self.rgb, self.rng, TRUE_BPM, self.phase, timestamp_ms / 1000.0
            )
            if transform is not None:
                frame = transform(frame)
            if timed is not None:
                frame = timed(frame, timestamp_ms)
            trace.append((timestamp_ms, processor.process(frame, timestamp_ms)))
        return trace


def steps_after(last_ms: int, seconds: float) -> list[int]:
    count = int(seconds * 1000 / PULSE_STEP_MS)
    return [last_ms + PULSE_STEP_MS * k for k in range(1, count + 1)]


def assert_not_ok_and_blank(reading: Reading) -> None:
    assert reading.state != "ok"
    assert reading.bpm is None
    assert reading.quality_db is None


def settled_pulse(
    processor: FrameProcessor, astronaut_rgb: NDArray[np.uint8], seed: int
) -> tuple[PulsedFace, Trace]:
    face = PulsedFace(astronaut_rgb, seed)
    timestamps = pulse_timestamps(np.random.default_rng(seed + 100), PULSE_S)
    trace = face.frames(processor, timestamps)
    assert_ok_within_one_bpm(trace[-1][1].reading, TRUE_BPM)
    return face, trace


def test_fixture_repeated_reports_face_three_regions_still_and_acquiring(
    processor: FrameProcessor, astronaut_rgb: NDArray[np.uint8]
) -> None:
    clock = FrameClock()

    results = [
        processor.process(astronaut_rgb, clock.next_ms()) for _ in range(FRAME_COUNT)
    ]

    assert len(results) == FRAME_COUNT
    for result in results:
        assert isinstance(result, FrameResult)
        assert result.face is True
        assert len(result.regions) == 3
        assert all(
            region.ndim == 2 and region.shape[0] >= 3 and region.shape[1] == 2
            for region in result.regions
        )
        assert result.moving is False
        assert isinstance(result.reading, Reading)
        assert result.reading.state == "acquiring"
        assert result.reading.bpm is None


def test_blank_frame_reports_no_face_and_the_stream_continues(
    processor: FrameProcessor, astronaut_rgb: NDArray[np.uint8]
) -> None:
    clock = FrameClock()
    processor.process(astronaut_rgb, clock.next_ms())

    blank = processor.process(np.zeros_like(astronaut_rgb), clock.next_ms())
    after = processor.process(astronaut_rgb, clock.next_ms())

    assert blank.face is False
    assert blank.regions == []
    assert blank.moving is False
    assert blank.reading.state == "acquiring"
    assert after.face is True
    assert len(after.regions) == 3


@pytest.mark.parametrize("seed", [SEED, SEED + 1])
def test_pulsed_fixture_reads_ok_within_one_bpm_after_the_settle_time(
    processor: FrameProcessor, astronaut_rgb: NDArray[np.uint8], seed: int
) -> None:
    _, trace = settled_pulse(processor, astronaut_rgb, seed)

    first_ms = trace[0][0]
    settling = [result for t, result in trace if t - first_ms < SETTLED_BY_MS]
    settled = [result for t, result in trace if t - first_ms >= OK_FROM_MS]

    assert all(result.face for _, result in trace)
    assert all(not result.moving for _, result in trace)
    assert all(result.reading.state == "acquiring" for result in settling)
    assert settled
    for result in settled:
        assert_ok_within_one_bpm(result.reading, TRUE_BPM)


def test_blank_frames_after_an_ok_pulse_restart_to_acquiring_within_the_gap(
    processor: FrameProcessor, astronaut_rgb: NDArray[np.uint8]
) -> None:
    _, trace = settled_pulse(processor, astronaut_rgb, SEED)
    last_face_ms, last = trace[-1]
    assert_ok_within_one_bpm(last.reading, TRUE_BPM)
    blank = np.zeros_like(astronaut_rgb)

    blanks = [
        (t, processor.process(blank, t)) for t in steps_after(last_face_ms, FOLLOW_S)
    ]

    for _, result in blanks:
        assert result.face is False
        assert result.regions == []
        assert result.moving is False
    past_gap = [result for t, result in blanks if t - last_face_ms >= RESTART_WITHIN_MS]
    assert past_gap
    for result in past_gap:
        assert result.reading.state == "acquiring"
        assert result.reading.bpm is None
        assert result.reading.quality_db is None


def test_face_shifted_after_an_ok_pulse_is_moving_then_low_quality(
    processor: FrameProcessor,
    astronaut_rgb: NDArray[np.uint8],
    fixture_face_width_px: float,
) -> None:
    face, trace = settled_pulse(processor, astronaut_rgb, SEED)
    last_still_ms, last = trace[-1]
    assert_ok_within_one_bpm(last.reading, TRUE_BPM)
    shift_px = moving_shift_px(fixture_face_width_px)

    shifted = face.frames(
        processor,
        steps_after(last_still_ms, FOLLOW_S),
        transform=lambda rgb: shifted_right(rgb, shift_px),
    )

    first_shift_ms, first_shift = shifted[0]
    assert first_shift.face is True
    assert first_shift.moving is True
    later = [result for t, result in shifted if t - first_shift_ms >= RESTART_WITHIN_MS]
    assert later
    for result in later:
        assert result.reading.state == "low_quality"
        assert result.reading.bpm is None


def test_face_cut_off_above_the_brows_keeps_two_cheek_regions_without_raising(
    processor: FrameProcessor, face_model: Path, astronaut_rgb: NDArray[np.uint8]
) -> None:
    with FaceTracker(face_model) as tracker:
        cropped = crop_above_brows(
            astronaut_rgb, detect_face(tracker, astronaut_rgb, 0)
        )
    clock = FrameClock()

    results = [processor.process(cropped, clock.next_ms()) for _ in range(5)]

    for result in results:
        assert result.face is True
        assert len(result.regions) == 2
        for region in result.regions:
            assert np.all((region >= 0.0) & (region <= 1.0))
            assert np.all(region[:, 1] > 0.0)
        assert result.moving is False


def test_blank_frames_after_an_ok_pulse_read_low_quality_until_the_gap_passes(
    processor: FrameProcessor, astronaut_rgb: NDArray[np.uint8]
) -> None:
    _, trace = settled_pulse(processor, astronaut_rgb, SEED)
    last_face_ms = trace[-1][0]
    blank = np.zeros_like(astronaut_rgb)

    blanks = [
        (t, processor.process(blank, t)) for t in steps_after(last_face_ms, FOLLOW_S)
    ]

    for _, result in blanks:
        assert result.face is False
        assert_not_ok_and_blank(result.reading)
    within_gap = [result for t, result in blanks if t - last_face_ms <= MAX_GAP_MS]
    assert within_gap
    assert all(result.reading.state == "low_quality" for result in within_gap)


def face_results(trace: Trace) -> Trace:
    return [(t, result) for t, result in trace if result.face]


def is_sample(result: FrameResult) -> bool:
    return result.face and len(result.regions) == 3


def forehead_flicker(mask: NDArray[np.bool_]) -> TimedTransform:
    def flicker(rgb: NDArray[np.uint8], timestamp_ms: int) -> NDArray[np.uint8]:
        angle = 2.0 * np.pi * FOREHEAD_FLICKER_BPM / 60.0 * timestamp_ms / 1000.0
        gain = 1.0 + FOREHEAD_FLICKER_DEPTH * np.sin(angle) * PULSE_SIGNATURE
        flickered = rgb.astype(np.float64)
        flickered[mask] *= gain
        return np.clip(np.round(flickered), 0, 255).astype(np.uint8)

    return flicker


def moving_shift_px(face_width: float) -> int:
    return math.ceil(
        SHIFT_SAFETY
        * MOVING_SHARE_OF_FACE_WIDTH
        * face_width
        * PULSE_STEP_MS
        / REFERENCE_FRAME_MS
    )


def test_face_without_usable_regions_after_an_ok_pulse_never_reads_ok(
    processor: FrameProcessor, astronaut_rgb: NDArray[np.uint8]
) -> None:
    face, trace = settled_pulse(processor, astronaut_rgb, SEED)
    last_full_ms = trace[-1][0]

    boxed = face.frames(
        processor,
        steps_after(last_full_ms, FOLLOW_S),
        transform=crop_to_a_face_without_usable_regions,
    )

    faces = face_results(boxed)
    assert len(faces) >= len(boxed) - 1
    assert faces[-1] == boxed[-1]
    for _, result in boxed:
        assert result.regions == []
        assert_not_ok_and_blank(result.reading)
    within_gap = [result for t, result in boxed if t - last_full_ms <= MAX_GAP_MS]
    past_gap = [result for t, result in faces if t - last_full_ms >= RESTART_WITHIN_MS]
    assert within_gap
    assert past_gap
    assert all(result.reading.state == "low_quality" for result in within_gap)
    assert all(result.reading.state == "acquiring" for result in past_gap)


def test_forehead_leaving_the_frame_after_an_ok_pulse_never_reads_ok(
    processor: FrameProcessor,
    astronaut_rgb: NDArray[np.uint8],
    forehead_cropped: Transform,
) -> None:
    face, trace = settled_pulse(processor, astronaut_rgb, SEED)
    last_full_ms = trace[-1][0]

    cropped = face.frames(
        processor, steps_after(last_full_ms, FOLLOW_S), transform=forehead_cropped
    )

    faces = face_results(cropped)
    assert len(faces) >= len(cropped) - 1
    assert all(len(result.regions) == 2 for _, result in faces)
    for _, result in cropped:
        assert result.moving is False
        assert_not_ok_and_blank(result.reading)
    within_gap = [result for t, result in cropped if t - last_full_ms <= MAX_GAP_MS]
    past_gap = [result for t, result in faces if t - last_full_ms >= RESTART_WITHIN_MS]
    assert within_gap
    assert past_gap
    assert all(result.reading.state == "low_quality" for result in within_gap)
    assert all(result.reading.state == "acquiring" for result in past_gap)


def test_two_region_frames_between_full_faces_move_nothing(
    processor: FrameProcessor,
    astronaut_rgb: NDArray[np.uint8],
    forehead_cropped: Transform,
) -> None:
    clock = FrameClock()
    cropped = forehead_cropped(astronaut_rgb)
    frames = [astronaut_rgb] * 3 + [cropped] * 4 + [astronaut_rgb] * 3

    results = [processor.process(frame, clock.next_ms()) for frame in frames]

    middle = [result for result in results[3:7] if result.face]
    assert middle
    assert all(len(result.regions) == 2 for result in middle)
    samples = [result for result in results if is_sample(result)]
    assert len(samples) >= len(frames) - len(middle) - 2
    assert all(result.moving is False for result in results)


@pytest.mark.parametrize("seed", [SEED, SEED + 1])
def test_flicker_on_the_forehead_alone_leaves_the_shared_pulse_ok(
    processor: FrameProcessor,
    astronaut_rgb: NDArray[np.uint8],
    forehead_mask: NDArray[np.bool_],
    seed: int,
) -> None:
    face = PulsedFace(astronaut_rgb, seed)
    timestamps = pulse_timestamps(np.random.default_rng(seed + 100), PULSE_S)

    trace = face.frames(processor, timestamps, timed=forehead_flicker(forehead_mask))

    first_ms = trace[0][0]
    shown = [result.reading for _, result in trace if result.reading.state == "ok"]
    near_flicker = [
        reading
        for reading in shown
        if reading.bpm is not None
        and abs(reading.bpm - FOREHEAD_FLICKER_BPM) <= FLICKER_WITHIN_BPM
    ]
    assert all(is_sample(result) for _, result in trace)
    assert near_flicker == []
    settled = [result for t, result in trace if t - first_ms >= OK_FROM_MS]
    assert settled
    for result in settled:
        assert_ok_within_one_bpm(result.reading, TRUE_BPM)


def test_one_blank_frame_between_full_faces_leaves_the_next_face_still_and_ok(
    processor: FrameProcessor, astronaut_rgb: NDArray[np.uint8]
) -> None:
    face, trace = settled_pulse(processor, astronaut_rgb, SEED)
    blank_ms, *face_ms = steps_after(trace[-1][0], FOLLOW_S)

    blank = processor.process(np.zeros_like(astronaut_rgb), blank_ms)
    after = face.frames(processor, face_ms)

    assert blank.face is False
    assert blank.moving is False
    for _, result in after:
        assert result.face is True
        assert len(result.regions) == 3
        assert result.moving is False
        assert_ok_within_one_bpm(result.reading, TRUE_BPM)


def test_gate_step_on_a_frame_without_regions_makes_the_next_face_moving(
    processor: FrameProcessor, astronaut_rgb: NDArray[np.uint8]
) -> None:
    clock = FrameClock()
    boxed = crop_to_a_face_without_usable_regions(astronaut_rgb)
    before = [astronaut_rgb] * 3 + [boxed] * 3
    frames = [*before, shifted_right(boxed, NO_REGION_STEP_PX)] + [astronaut_rgb] * 4
    stepped_at = len(before)

    results = [processor.process(frame, clock.next_ms()) for frame in frames]

    stepped = results[stepped_at]
    assert stepped.face is True
    assert stepped.regions == []
    assert stepped.moving is True
    samples = [result for result in results[stepped_at + 1 :] if is_sample(result)]
    assert len(samples) >= 2
    assert len(samples[0].regions) == 3
    assert samples[0].moving is True
    assert all(result.moving is False for result in samples[1:])


def test_face_without_regions_between_full_faces_moves_nothing(
    processor: FrameProcessor, astronaut_rgb: NDArray[np.uint8]
) -> None:
    clock = FrameClock()
    boxed = crop_to_a_face_without_usable_regions(astronaut_rgb)
    frames = [astronaut_rgb] * 3 + [boxed] * 3 + [astronaut_rgb] * 4

    results = [processor.process(frame, clock.next_ms()) for frame in frames]

    middle = results[3:6]
    assert any(result.face for result in middle)
    for result in middle:
        assert result.regions == []
        assert result.moving is False
    samples = [result for result in results if is_sample(result)]
    assert len(samples) >= len(frames) - len(middle) - 2
    assert all(len(result.regions) == 3 for result in samples)
    assert all(result.moving is False for result in results)


def test_shift_after_an_ok_pulse_reads_low_quality_on_the_same_frame(
    processor: FrameProcessor,
    astronaut_rgb: NDArray[np.uint8],
    fixture_face_width_px: float,
) -> None:
    face, trace = settled_pulse(processor, astronaut_rgb, SEED)
    shift_px = moving_shift_px(fixture_face_width_px)
    follow = steps_after(trace[-1][0], FOLLOW_S)
    still = face.frames(processor, follow[:STILL_BEFORE_CHANGE])
    assert_ok_within_one_bpm(still[-1][1].reading, TRUE_BPM)

    changed = face.frames(
        processor,
        follow[STILL_BEFORE_CHANGE:],
        transform=lambda rgb: shifted_right(rgb, shift_px),
    )

    first = face_results(changed)[0][1]
    assert first.moving is True
    assert first.reading.state == "low_quality"
    assert first.reading.bpm is None


def test_still_frames_without_regions_after_a_gate_step_are_not_moving(
    processor: FrameProcessor, astronaut_rgb: NDArray[np.uint8]
) -> None:
    clock = FrameClock()
    boxed = crop_to_a_face_without_usable_regions(astronaut_rgb)
    stepped = shifted_right(boxed, NO_REGION_STEP_PX)
    before = [astronaut_rgb] * 3 + [boxed] * 3
    frames = [*before, stepped] + [stepped] * 3 + [astronaut_rgb] * 4
    stepped_at = len(before)

    results = [processor.process(frame, clock.next_ms()) for frame in frames]

    assert results[stepped_at].face is True
    assert results[stepped_at].regions == []
    assert results[stepped_at].moving is True
    still = results[stepped_at + 1 : stepped_at + 4]
    assert any(result.face for result in still)
    for result in still:
        assert result.regions == []
        assert result.moving is False
    samples = [result for result in results[stepped_at + 4 :] if is_sample(result)]
    assert len(samples) >= 2
    assert len(samples[0].regions) == 3
    assert samples[0].moving is True
    assert all(result.moving is False for result in samples[1:])
