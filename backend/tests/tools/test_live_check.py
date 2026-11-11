import inspect
import logging
import math
import re
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest
from numpy.typing import NDArray

from pulse_frame.monitor.processor import FrameResult
from pulse_frame.signal.tracker import Reading
from pulse_frame.tools import live_check
from pulse_frame.vision.landmarks import FaceTracker
from pulse_frame.vision.motion import MOVING_SHARE_OF_FACE_WIDTH
from tests.frames import SHIFT_SAFETY, shifted_right
from tests.vision.faces import detect_face, face_width_px

CAMERA_FPS = 30.0
CLOCK_START_MS = 50_000.0
RUN_SECONDS = "3.5"
SHIFT_AT_S = 1.5
FAILING_READ = 10
FPS_TOLERANCE = 2.0
REPEATED_READ = 20
INTERRUPTED_READ = 40
STALLED_READ = 45
STALL_MS = 2_500.0
STALL_RUN_SECONDS = "5.5"
BLUE_BGR = (255, 0, 0)
FIELDS = {
    "time": r"^\s*(\d+(?:\.\d+)?) s\b",
    "state": r"\bstate=(\S+)",
    "bpm": r"\bbpm=\s*(\S+)",
    "quality": r"\bquality=\s*(-|-?\d+(?:\.\d+)? dB)",
    "face": r"\bface=(yes|no)\b",
    "moving": r"\bmoving=(yes|no)\b",
    "motion": r"\bmotion=(\d+(?:\.\d+)?)\b",
    "fps": r"\bfps=(\d+(?:\.\d+)?)\b",
}


class FakeClock:
    def __init__(self) -> None:
        self.now = CLOCK_START_MS

    def ms(self) -> int:
        return int(self.now)

    def elapsed_s(self) -> float:
        return (self.now - CLOCK_START_MS) / 1000.0


class FakeCamera:
    def __init__(
        self,
        clock: FakeClock,
        bgr: NDArray[np.uint8],
        opens: bool = True,
        fail_on_read: int | None = None,
        shift_px: int = 0,
        repeat_on_read: int | None = None,
        interrupt_on_read: int | None = None,
        stall_on_read: int | None = None,
    ) -> None:
        self.clock = clock
        self.bgr = bgr
        self.opens = opens
        self.fail_on_read = fail_on_read
        self.shift_px = shift_px
        self.repeat_on_read = repeat_on_read
        self.interrupt_on_read = interrupt_on_read
        self.stall_on_read = stall_on_read
        self.reads = 0
        self.released = 0
        self.isOpened = self.is_opened

    def is_opened(self) -> bool:
        return self.opens

    def read(self) -> tuple[bool, NDArray[np.uint8] | None]:
        self.reads += 1
        if self.reads == self.interrupt_on_read:
            raise KeyboardInterrupt
        if self.reads != self.repeat_on_read:
            self.clock.now += 1000.0 / CAMERA_FPS
        if self.reads == self.stall_on_read:
            self.clock.now += STALL_MS
        if self.fail_on_read is not None and self.reads >= self.fail_on_read:
            return False, None
        if self.shift_px and self.clock.elapsed_s() >= SHIFT_AT_S:
            return True, shifted_right(self.bgr, self.shift_px)
        return True, self.bgr.copy()

    def release(self) -> None:
        self.released += 1


def forbidden_writer(*args: object, **kwargs: object) -> None:
    raise AssertionError("live_check tried to write a frame")


class Harness:
    def __init__(
        self,
        monkeypatch: pytest.MonkeyPatch,
        bgr: NDArray[np.uint8],
        **camera: object,
    ) -> None:
        self.clock = FakeClock()
        self.camera = FakeCamera(self.clock, bgr, **camera)
        self.opened: list[object] = []
        monkeypatch.setattr(live_check, "now_ms", self.clock.ms)
        monkeypatch.setattr(cv2, "VideoCapture", self.open)
        monkeypatch.setattr(cv2, "imwrite", forbidden_writer)
        monkeypatch.setattr(cv2, "VideoWriter", forbidden_writer)

    def open(self, index: object, *args: object) -> FakeCamera:
        self.opened.append(index)
        return self.camera


@pytest.fixture
def astronaut_bgr(astronaut_rgb: NDArray[np.uint8]) -> NDArray[np.uint8]:
    return cv2.cvtColor(astronaut_rgb, cv2.COLOR_RGB2BGR)


@pytest.fixture(scope="module")
def shift_px(face_model: Path, astronaut_rgb: NDArray[np.uint8]) -> int:
    with FaceTracker(face_model) as tracker:
        width_px = face_width_px(detect_face(tracker, astronaut_rgb, 0))
    return math.ceil(SHIFT_SAFETY * MOVING_SHARE_OF_FACE_WIDTH * width_px)


@pytest.fixture
def quiet_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> Path:
    monkeypatch.chdir(tmp_path)
    caplog.set_level(logging.DEBUG)
    return tmp_path


def run_tool(monkeypatch: pytest.MonkeyPatch, *args: str) -> None:
    monkeypatch.setattr(sys, "argv", ["live_check", *args])
    live_check.main()


def parse(line: str) -> dict[str, str]:
    fields = {}
    for name, pattern in FIELDS.items():
        found = re.search(pattern, line)
        assert found is not None, f"Field {name} is missing from: {line!r}"
        fields[name] = found.group(1)
    return fields


def files_under(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*"))


def test_help_exits_zero_and_prints_usage_without_opening_a_camera(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    opened: list[tuple[object, ...]] = []
    monkeypatch.setattr(cv2, "VideoCapture", lambda *args: opened.append(args))

    with pytest.raises(SystemExit) as exited:
        run_tool(monkeypatch, "--help")

    assert exited.value.code == 0
    assert capsys.readouterr().out.startswith("usage:")
    assert opened == []


@pytest.mark.parametrize("frame_writer", ["imwrite", "VideoWriter"])
def test_tool_has_no_call_that_writes_frames_to_disk(frame_writer: str) -> None:
    assert frame_writer not in inspect.getsource(live_check)


def test_prints_one_status_line_per_second_with_every_field(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
    quiet_folder: Path,
    astronaut_bgr: NDArray[np.uint8],
    shift_px: int,
) -> None:
    harness = Harness(monkeypatch, astronaut_bgr, shift_px=shift_px)

    run_tool(monkeypatch, "--seconds", RUN_SECONDS)

    output = capsys.readouterr()
    lines = output.out.splitlines()
    assert len(lines) == 3
    fields = [parse(line) for line in lines]
    for second, line in enumerate(fields, start=1):
        assert float(line["time"]) == pytest.approx(second, abs=0.1)
        assert line["state"] == "acquiring"
        assert line["bpm"] == "-"
        assert line["quality"] == "-"
        assert line["face"] == "yes"
        assert float(line["fps"]) == pytest.approx(CAMERA_FPS, abs=FPS_TOLERANCE)
    assert [line["moving"] for line in fields] == ["no", "yes", "no"]
    assert float(fields[0]["motion"]) < MOVING_SHARE_OF_FACE_WIDTH
    assert float(fields[1]["motion"]) > MOVING_SHARE_OF_FACE_WIDTH
    assert float(fields[2]["motion"]) < MOVING_SHARE_OF_FACE_WIDTH
    assert harness.opened == [0]
    assert harness.camera.released == 1
    assert files_under(quiet_folder) == []
    assert caplog.records == []


def test_camera_that_cannot_open_exits_one_with_camera_unavailable(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
    quiet_folder: Path,
    astronaut_bgr: NDArray[np.uint8],
) -> None:
    harness = Harness(monkeypatch, astronaut_bgr, opens=False)

    with pytest.raises(SystemExit) as exited:
        run_tool(monkeypatch, "--seconds", RUN_SECONDS)

    output = capsys.readouterr()
    assert exited.value.code == 1
    assert output.err.startswith("CAMERA_UNAVAILABLE: ")
    assert output.out == ""
    assert harness.camera.reads == 0
    assert harness.camera.released == 1
    assert files_under(quiet_folder) == []
    assert caplog.records == []


def test_camera_that_stops_delivering_frames_exits_one_with_camera_read_failed(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
    quiet_folder: Path,
    astronaut_bgr: NDArray[np.uint8],
) -> None:
    harness = Harness(monkeypatch, astronaut_bgr, fail_on_read=FAILING_READ)

    with pytest.raises(SystemExit) as exited:
        run_tool(monkeypatch, "--seconds", RUN_SECONDS)

    output = capsys.readouterr()
    assert exited.value.code == 1
    assert output.err.startswith("CAMERA_READ_FAILED: ")
    assert harness.camera.reads == FAILING_READ
    assert harness.camera.released == 1
    assert files_under(quiet_folder) == []
    assert caplog.records == []


@pytest.mark.parametrize("seconds", ["0", "-1", "inf"])
def test_seconds_not_finite_and_above_zero_are_rejected_before_opening_a_camera(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    astronaut_bgr: NDArray[np.uint8],
    seconds: str,
) -> None:
    harness = Harness(monkeypatch, astronaut_bgr, fail_on_read=FAILING_READ)

    with pytest.raises(SystemExit) as exited:
        run_tool(monkeypatch, "--seconds", seconds)

    output = capsys.readouterr()
    assert exited.value.code == 2
    assert "--seconds" in output.err
    assert output.out == ""
    assert harness.opened == []


class SingleFrameCamera:
    def __init__(self, bgr: NDArray[np.uint8]) -> None:
        self.bgr = bgr

    def read(self) -> tuple[bool, NDArray[np.uint8]]:
        return True, self.bgr.copy()


def frame_result(face: bool, moving: bool, reading: Reading) -> FrameResult:
    return FrameResult(
        face=face, regions=[], moving=moving, motion_share=0.0, reading=reading
    )


def test_status_line_shows_an_ok_reading_with_bpm_and_quality_in_db() -> None:
    result = frame_result(True, False, Reading(state="ok", bpm=72.4, quality_db=6.3))
    interval = live_check.Interval(start_ms=1_000, frames=30, largest_share=0.0021)

    fields = parse(live_check.status_line(2_000, result, interval, 2_000))

    assert fields == {
        "time": "2.0",
        "state": "ok",
        "bpm": "72.4",
        "quality": "6.3 dB",
        "face": "yes",
        "moving": "no",
        "motion": "0.0021",
        "fps": "30.0",
    }


def test_status_line_shows_no_face_low_quality_and_motion_in_the_interval() -> None:
    result = frame_result(
        False, False, Reading(state="low_quality", bpm=None, quality_db=None)
    )
    interval = live_check.Interval(
        start_ms=4_000, frames=15, largest_share=0.0532, moved=True
    )

    fields = parse(live_check.status_line(5_000, result, interval, 5_000))

    assert fields == {
        "time": "5.0",
        "state": "low_quality",
        "bpm": "-",
        "quality": "-",
        "face": "no",
        "moving": "yes",
        "motion": "0.0532",
        "fps": "15.0",
    }


def test_read_frame_turns_the_camera_bgr_frame_into_rgb() -> None:
    bgr = np.empty((4, 6, 3), dtype=np.uint8)
    bgr[:, :] = BLUE_BGR

    rgb = live_check.read_frame(SingleFrameCamera(bgr))

    assert rgb.shape == bgr.shape
    assert rgb.dtype == np.uint8
    assert np.all(rgb[:, :, 0] == 0)
    assert np.all(rgb[:, :, 1] == 0)
    assert np.all(rgb[:, :, 2] == 255)


def test_a_repeated_clock_millisecond_is_skipped_and_the_run_goes_on(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    quiet_folder: Path,
    astronaut_bgr: NDArray[np.uint8],
) -> None:
    harness = Harness(monkeypatch, astronaut_bgr, repeat_on_read=REPEATED_READ)

    run_tool(monkeypatch, "--seconds", RUN_SECONDS)

    output = capsys.readouterr()
    assert output.err == ""
    lines = [parse(line) for line in output.out.splitlines()]
    assert [round(float(line["time"])) for line in lines] == [1, 2, 3]
    assert all(line["face"] == "yes" for line in lines)
    assert harness.camera.reads > REPEATED_READ
    assert harness.camera.released == 1
    assert files_under(quiet_folder) == []


def test_ctrl_c_during_a_camera_read_prints_stopped_and_releases_the_camera(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    quiet_folder: Path,
    astronaut_bgr: NDArray[np.uint8],
) -> None:
    harness = Harness(monkeypatch, astronaut_bgr, interrupt_on_read=INTERRUPTED_READ)

    run_tool(monkeypatch)

    output = capsys.readouterr()
    lines = output.out.splitlines()
    assert lines[-1] == "Stopped."
    assert len(lines) == 2
    parse(lines[0])
    assert output.err == ""
    assert harness.camera.reads == INTERRUPTED_READ
    assert harness.camera.released == 1
    assert files_under(quiet_folder) == []


def test_camera_stalling_over_two_seconds_prints_one_line_and_keeps_the_schedule(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    quiet_folder: Path,
    astronaut_bgr: NDArray[np.uint8],
) -> None:
    harness = Harness(monkeypatch, astronaut_bgr, stall_on_read=STALLED_READ)

    run_tool(monkeypatch, "--seconds", STALL_RUN_SECONDS)

    output = capsys.readouterr()
    assert output.err == ""
    times = [float(parse(line)["time"]) for line in output.out.splitlines()]
    assert times == pytest.approx([1.0, 4.0, 5.0], abs=0.1)
    assert harness.camera.released == 1
    assert files_under(quiet_folder) == []
