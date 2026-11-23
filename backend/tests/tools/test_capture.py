import inspect
import logging
import math
import re
from collections.abc import Callable, Sequence
from pathlib import Path

import cv2
import numpy as np
import psycopg
import pytest
from numpy.typing import NDArray

from pulse_frame.store.recording import FrameSample, SessionWriter
from pulse_frame.store.sessions import delete_session
from pulse_frame.tools import capture
from pulse_frame.tools.sessions import SANDBOX_UNSUPPORTED_ACTION
from pulse_frame.vision.landmarks import FaceTracker
from pulse_frame.vision.motion import MOVING_SHARE_OF_FACE_WIDTH
from pulse_frame.vision.regions import named_region_polygons, skin_mean
from tests.database import (
    COLOUR_COLUMNS,
    MONOTONIC_NS,
    SAMPLE_COLUMNS,
    WALL_NS,
    Row,
    insert_samples,
    stored_rows,
    stored_session_ids,
)
from tests.frames import SHIFT_SAFETY, shifted_right
from tests.platform.support import after_sandbox_notice
from tests.vision.faces import detect_face, face_width_px

FRAME_NS = 33_333_333
NS_PER_MS = 1_000_000
RUN_SECONDS = "3.5"
STATUS_LINES = 3
RUN_WITHOUT_WARM_UP = ["--warm-up", "0", "--seconds", RUN_SECONDS]
WARM_UP_SECONDS = "1.5"
COUNTED_SECONDS = "2"
RUN_WITH_WARM_UP = ["--warm-up", WARM_UP_SECONDS, "--seconds", COUNTED_SECONDS]
DEFAULT_WARM_UP_S = 60.0
DEFAULT_COUNTED_S = 90.0
HELP_OPTION = re.compile(r"(?=\s--[a-z])")
HELP_DEFAULT = re.compile(r"^--([a-z-]+) .*\(default ([^)]+)\)$")
BEL = "\x07"
PHASE_LINE = f"{BEL}Warm-up done, counting {COUNTED_SECONDS} s from now."
GREY_FROM_READ = 61
GREY_UNTIL_READ = 90
GREY_LEVEL = 128
SHIFT_AT_S = 1.5
MOTION_SPAN_S = 1.0
FAILING_READ = 10
INTERRUPTED_READ = 40
COUNTED_INTERRUPTED_READ = 60
OVER_A_DAY = ["1e300", "1e10", "86400.5"]
A_DAY = "86400"
NO_COUNTED_CODE = "NO_COUNTED_SAMPLES"
NO_COUNTED_PART = "no counted part"
DELETE_READ = 35
REPEATED_READ = 20
COLOUR_TOLERANCE = 2.0
CLOCK_TOLERANCE_MS = 1
FRAME_REACH_MS = FRAME_NS // NS_PER_MS + CLOCK_TOLERANCE_MS + 1
PLANT_READ = 20
CLASH_READ = 25
PLANTED_COLOUR = 100.0
CODED_LINE = re.compile(r"[A-Z][A-Z_]+: ")
SHARED_DEFINITIONS = [
    "def open_camera",
    "def read_frame",
    "def report(",
    "def report_sandbox",
    "def write_out",
    "INTERRUPTED_EXIT =",
]
SESSION_LINE = re.compile(r"Session (\d+)\D*")
STATUS_LINE = re.compile(
    r"\s*\d+\.\d s\s+samples=(\d+)\s+face=(?:yes|no)\s+moving=(?:yes|no)"
    r"\s+fps=\d+\.\d"
)
STOPPED = "Stopped."
FRAME_WRITERS = [
    "imwrite",
    "VideoWriter",
    "imencode",
    "write_bytes",
    "tofile",
    "np.save",
]

type FrameSource = Callable[[int, float], NDArray[np.uint8]]


class FakeClock:
    def __init__(self) -> None:
        self.elapsed_ns = 0

    def monotonic_ns(self) -> int:
        return MONOTONIC_NS + self.elapsed_ns

    def time_ns(self) -> int:
        return WALL_NS + self.elapsed_ns

    def ms(self) -> int:
        return self.monotonic_ns() // NS_PER_MS

    def elapsed_s(self) -> float:
        return self.elapsed_ns / 1e9


class FakeCamera:
    def __init__(
        self,
        clock: FakeClock,
        frame_at: FrameSource,
        opens: bool = True,
        fail_on_read: int | None = None,
        interrupt_on_read: int | None = None,
        repeat_on_read: int | None = None,
        on_read: dict[int, Callable[[], None]] | None = None,
    ) -> None:
        self.clock = clock
        self.on_read = on_read or {}
        self.frame_at = frame_at
        self.opens = opens
        self.fail_on_read = fail_on_read
        self.interrupt_on_read = interrupt_on_read
        self.repeat_on_read = repeat_on_read
        self.reads = 0
        self.released = 0
        self.read_ms: list[int] = []
        self.isOpened = self.is_opened

    def is_opened(self) -> bool:
        return self.opens

    def read(self) -> tuple[bool, NDArray[np.uint8] | None]:
        self.reads += 1
        if self.reads == self.interrupt_on_read:
            raise KeyboardInterrupt
        if self.reads != self.repeat_on_read:
            self.clock.elapsed_ns += FRAME_NS
        self.read_ms.append(self.clock.ms())
        if self.reads in self.on_read:
            self.on_read[self.reads]()
        if self.fail_on_read is not None and self.reads >= self.fail_on_read:
            return False, None
        return True, self.frame_at(self.reads, self.clock.elapsed_s()).copy()

    def release(self) -> None:
        self.released += 1


def forbidden_writer(*args: object, **kwargs: object) -> None:
    raise AssertionError("capture tried to write a frame")


class Harness:
    def __init__(
        self, monkeypatch: pytest.MonkeyPatch, frame_at: FrameSource, **camera: object
    ) -> None:
        self.clock = FakeClock()
        self.camera = FakeCamera(self.clock, frame_at, **camera)
        self.opened: list[object] = []
        monkeypatch.setattr(capture, "monotonic_ns", self.clock.monotonic_ns)
        monkeypatch.setattr(capture, "time_ns", self.clock.time_ns)
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
def astronaut_colours(
    face_model: Path, astronaut_rgb: NDArray[np.uint8]
) -> tuple[float, ...]:
    with FaceTracker(face_model) as tracker:
        face = detect_face(tracker, astronaut_rgb, 0)
    means = [
        skin_mean(astronaut_rgb, [polygon])
        for polygon in named_region_polygons(face).values()
    ]
    assert all(mean is not None for mean in means)
    return tuple(value for mean in means if mean is not None for value in mean)


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


def still(bgr: NDArray[np.uint8]) -> FrameSource:
    return lambda read, elapsed_s: bgr


def grey_between(bgr: NDArray[np.uint8]) -> FrameSource:
    grey = np.full_like(bgr, GREY_LEVEL)

    def frame_at(read: int, elapsed_s: float) -> NDArray[np.uint8]:
        return grey if GREY_FROM_READ <= read <= GREY_UNTIL_READ else bgr

    return frame_at


def shifted_after(bgr: NDArray[np.uint8], pixels: int) -> FrameSource:
    shifted = shifted_right(bgr, pixels)
    return lambda read, elapsed_s: shifted if elapsed_s >= SHIFT_AT_S else bgr


def face_read_ms(camera: FakeCamera) -> list[int]:
    return [
        ms
        for read, ms in enumerate(camera.read_ms, start=1)
        if not GREY_FROM_READ <= read <= GREY_UNTIL_READ
    ]


def coded_lines(err: str) -> list[str]:
    return [line for line in err.splitlines() if CODED_LINE.match(line)]


def planted_sample(t_ms: int) -> Row:
    return {
        "t_ms": t_ms,
        **dict.fromkeys(COLOUR_COLUMNS, PLANTED_COLOUR),
        "moving": False,
    }


def files_under(root: Path) -> list[Path]:
    return sorted(root.rglob("*"))


def only_session(url: str) -> int:
    ids = stored_session_ids(url)
    assert len(ids) == 1, f"expected one stored session, found {len(ids)}"
    return ids[0]


def stored_samples(url: str, session_id: int) -> list[tuple[object, ...]]:
    return stored_rows(url, "frame_samples", session_id, SAMPLE_COLUMNS)


def sample_times(url: str, session_id: int) -> list[int]:
    return [int(str(row[0])) for row in stored_samples(url, session_id)]


def seconds_into_run(t_ms: int) -> float:
    return (t_ms * NS_PER_MS - MONOTONIC_NS) / 1e9


def line_kind(line: str) -> str:
    if SESSION_LINE.fullmatch(line):
        return "session"
    if STATUS_LINE.fullmatch(line):
        return "status"
    if line == PHASE_LINE:
        return "phase"
    if line == BEL:
        return "bell"
    if line == STOPPED:
        return "stopped"
    return "other"


def line_kinds(out: str) -> list[str]:
    return [line_kind(line) for line in out.splitlines()]


def status_counts(out: str) -> list[int]:
    return [
        int(match.group(1))
        for line in out.splitlines()
        if (match := STATUS_LINE.fullmatch(line))
    ]


def stored_anchor_and_counted_start(url: str, session_id: int) -> tuple[int, int]:
    ((anchor_ns, counted_ns),) = stored_rows(
        url, "sessions", session_id, ["started_monotonic_ns", "counted_monotonic_ns"]
    )
    return int(str(anchor_ns)), int(str(counted_ns))


def seconds_ns(text: str) -> int:
    return round(float(text) * 1e9)


class OutputClock:
    def __init__(self, monkeypatch: pytest.MonkeyPatch, clock: FakeClock) -> None:
        self.clock = clock
        self.written: list[tuple[int, str]] = []
        self.real_write_out = capture.write_out
        monkeypatch.setattr(capture, "write_out", self.write_out)

    def write_out(self, text: str, end: str = "\n") -> bool:
        self.written.append((self.clock.ms(), text))
        return self.real_write_out(text, end)

    def written_at(self, text: str) -> list[int]:
        return [ms for ms, line in self.written if line == text]


def test_help_exits_zero_without_opening_a_camera(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    astronaut_bgr: NDArray[np.uint8],
) -> None:
    harness = Harness(monkeypatch, still(astronaut_bgr))

    with pytest.raises(SystemExit) as exited:
        capture.main(["--help"])

    assert exited.value.code == 0
    assert capsys.readouterr().out.startswith("usage:")
    assert harness.opened == []


@pytest.mark.parametrize("frame_writer", FRAME_WRITERS)
def test_capture_has_no_call_that_writes_a_frame_or_image(frame_writer: str) -> None:
    assert frame_writer not in inspect.getsource(capture)


def test_writes_one_frame_sample_per_frame_with_colours_and_none_without(
    store_url: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
    quiet_folder: Path,
    astronaut_bgr: NDArray[np.uint8],
) -> None:
    harness = Harness(monkeypatch, grey_between(astronaut_bgr))

    assert capture.main(RUN_WITHOUT_WARM_UP) == 0

    session_id = only_session(store_url)
    times = sample_times(store_url, session_id)
    expected = face_read_ms(harness.camera)
    assert len(times) == len(expected)
    assert np.allclose(times, expected, atol=CLOCK_TOLERANCE_MS)
    grey_ms = set(harness.camera.read_ms[GREY_FROM_READ - 1 : GREY_UNTIL_READ])
    assert not grey_ms & set(times)
    assert harness.camera.released == 1
    assert (
        after_sandbox_notice(capsys.readouterr().err, action=SANDBOX_UNSUPPORTED_ACTION)
        == ""
    )
    assert files_under(quiet_folder) == []
    assert caplog.records == []


def test_each_frame_sample_holds_the_nine_region_colours_of_the_face(
    store_url: str,
    monkeypatch: pytest.MonkeyPatch,
    quiet_folder: Path,
    astronaut_bgr: NDArray[np.uint8],
    astronaut_colours: tuple[float, ...],
) -> None:
    Harness(monkeypatch, still(astronaut_bgr))

    assert capture.main(RUN_WITHOUT_WARM_UP) == 0

    rows = stored_samples(store_url, only_session(store_url))
    assert rows, "no frame sample was stored"
    colours = np.array([row[1 : 1 + len(COLOUR_COLUMNS)] for row in rows], dtype=float)
    assert colours.shape[1] == 9
    assert np.abs(colours - np.array(astronaut_colours)).max() <= COLOUR_TOLERANCE
    assert [row[-1] for row in rows] == [False] * len(rows)


def test_session_anchor_is_one_wall_and_monotonic_pair_and_t_ms_is_monotonic_ms(
    store_url: str,
    monkeypatch: pytest.MonkeyPatch,
    quiet_folder: Path,
    astronaut_bgr: NDArray[np.uint8],
) -> None:
    harness = Harness(monkeypatch, still(astronaut_bgr))

    assert capture.main(RUN_WITHOUT_WARM_UP) == 0

    session_id = only_session(store_url)
    ((wall_ns, monotonic_ns),) = stored_rows(
        store_url, "sessions", session_id, ["started_wall_ns", "started_monotonic_ns"]
    )
    assert isinstance(wall_ns, int)
    assert isinstance(monotonic_ns, int)
    assert wall_ns - monotonic_ns == WALL_NS - MONOTONIC_NS
    times = sample_times(store_url, session_id)
    assert MONOTONIC_NS <= monotonic_ns <= times[0] * NS_PER_MS
    assert times == sorted(set(times))
    assert np.allclose(times, harness.camera.read_ms, atol=CLOCK_TOLERANCE_MS)
    run_s = float(RUN_SECONDS) + 0.1
    assert all(0.0 <= seconds_into_run(t) <= run_s for t in times)


def test_motion_flag_is_stored_for_the_frames_around_a_head_move(
    store_url: str,
    monkeypatch: pytest.MonkeyPatch,
    quiet_folder: Path,
    astronaut_bgr: NDArray[np.uint8],
    shift_px: int,
) -> None:
    Harness(monkeypatch, shifted_after(astronaut_bgr, shift_px))

    assert capture.main(RUN_WITHOUT_WARM_UP) == 0

    rows = stored_samples(store_url, only_session(store_url))
    flags = [(seconds_into_run(int(str(row[0]))), row[-1]) for row in rows]
    moving_at = [t for t, moving in flags if moving is True]
    before_move = [moving for t, moving in flags if t < SHIFT_AT_S]
    assert moving_at, "no stored frame sample is marked moving"
    assert all(SHIFT_AT_S <= t < SHIFT_AT_S + MOTION_SPAN_S for t in moving_at)
    assert before_move, "no frame sample was stored before the move"
    assert before_move == [False] * len(before_move)


def test_without_a_warm_up_prints_the_session_id_status_lines_and_a_closing_bell(
    store_url: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    quiet_folder: Path,
    astronaut_bgr: NDArray[np.uint8],
) -> None:
    Harness(monkeypatch, still(astronaut_bgr))

    assert capture.main(RUN_WITHOUT_WARM_UP) == 0

    output = capsys.readouterr()
    session_id = only_session(store_url)
    lines = output.out.splitlines()
    kinds = line_kinds(output.out)
    assert "other" not in kinds, f"{kinds.count('other')} printed lines are unknown"
    assert kinds == ["session", *["status"] * STATUS_LINES, "bell"]
    found = SESSION_LINE.fullmatch(lines[0])
    assert found is not None
    assert int(found.group(1)) == session_id
    counts = status_counts(output.out)
    assert counts == sorted(counts)
    assert counts[-1] <= len(sample_times(store_url, session_id))
    assert output.out.count(BEL) == 1
    assert after_sandbox_notice(output.err, action=SANDBOX_UNSUPPORTED_ACTION) == ""


def test_a_warm_up_prints_one_phase_line_and_bell_at_the_counted_start_and_a_bell_last(
    store_url: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    quiet_folder: Path,
    astronaut_bgr: NDArray[np.uint8],
) -> None:
    harness = Harness(monkeypatch, still(astronaut_bgr))
    output_clock = OutputClock(monkeypatch, harness.clock)

    assert capture.main(RUN_WITH_WARM_UP) == 0

    output = capsys.readouterr()
    session_id = only_session(store_url)
    kinds = line_kinds(output.out)
    assert "other" not in kinds, f"{kinds.count('other')} printed lines are unknown"
    assert kinds[0] == "session"
    assert kinds[-1] == "bell"
    assert kinds.count("session") == 1
    assert kinds.count("phase") == 1
    assert kinds.count("bell") == 1
    assert "stopped" not in kinds
    phase_at = kinds.index("phase")
    assert "status" in kinds[1:phase_at], "no status line during the warm-up"
    assert "status" in kinds[phase_at + 1 : -1], "no status line in the counted part"
    assert output.out.count(BEL) == 2
    anchor_ns, _ = stored_anchor_and_counted_start(store_url, session_id)
    counted_ms = (anchor_ns + seconds_ns(WARM_UP_SECONDS)) // NS_PER_MS
    phase_ms = output_clock.written_at(PHASE_LINE)
    assert len(phase_ms) == 1, "the phase line was not written once through write_out"
    assert counted_ms <= phase_ms[0] < counted_ms + FRAME_REACH_MS
    assert after_sandbox_notice(output.err, action=SANDBOX_UNSUPPORTED_ACTION) == ""


@pytest.mark.parametrize(
    ("argv", "warm_up_ns"),
    [
        (RUN_WITH_WARM_UP, seconds_ns(WARM_UP_SECONDS)),
        (RUN_WITHOUT_WARM_UP, 0),
    ],
    ids=["warm_up", "no_warm_up"],
)
def test_the_session_stores_its_counted_start_as_the_anchor_plus_the_warm_up(
    store_url: str,
    monkeypatch: pytest.MonkeyPatch,
    quiet_folder: Path,
    astronaut_bgr: NDArray[np.uint8],
    argv: list[str],
    warm_up_ns: int,
) -> None:
    Harness(monkeypatch, still(astronaut_bgr))

    assert capture.main(argv) == 0

    anchor_ns, counted_ns = stored_anchor_and_counted_start(
        store_url, only_session(store_url)
    )
    assert anchor_ns == MONOTONIC_NS
    assert counted_ns == anchor_ns + warm_up_ns


def test_seconds_is_the_counted_length_after_a_stored_warm_up(
    store_url: str,
    monkeypatch: pytest.MonkeyPatch,
    quiet_folder: Path,
    astronaut_bgr: NDArray[np.uint8],
) -> None:
    Harness(monkeypatch, still(astronaut_bgr))

    assert capture.main(RUN_WITH_WARM_UP) == 0

    session_id = only_session(store_url)
    anchor_ns, _ = stored_anchor_and_counted_start(store_url, session_id)
    counted_ms = (anchor_ns + seconds_ns(WARM_UP_SECONDS)) // NS_PER_MS
    end_ms = (
        anchor_ns + seconds_ns(WARM_UP_SECONDS) + seconds_ns(COUNTED_SECONDS)
    ) // NS_PER_MS
    times = sample_times(store_url, session_id)
    warm_up = [t for t in times if t < counted_ms]
    counted = [t for t in times if t >= counted_ms]
    assert warm_up, "no frame sample of the warm-up was stored"
    assert counted, "no frame sample of the counted part was stored"
    assert end_ms - FRAME_REACH_MS <= times[-1] <= end_ms + FRAME_REACH_MS


def test_the_warm_up_defaults_to_sixty_seconds_and_the_counted_part_to_ninety() -> None:
    args = capture.parse_args([])

    assert args.seconds == DEFAULT_COUNTED_S
    assert args.warm_up == DEFAULT_WARM_UP_S


def test_the_help_names_sixty_and_ninety_seconds_as_the_defaults(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exited:
        capture.parse_args(["--help"])

    assert exited.value.code == 0
    text = " ".join(capsys.readouterr().out.split())
    options = text.split("options:", 1)[1]
    found = [HELP_DEFAULT.match(part.strip()) for part in HELP_OPTION.split(options)]
    defaults = {match[1]: match[2] for match in found if match}
    assert defaults["warm-up"] == "60"
    assert defaults["seconds"] == "90"


def test_a_warm_up_of_zero_is_accepted_as_no_warm_up() -> None:
    args = capture.parse_args(["--warm-up", "0"])

    assert args.warm_up == 0.0


@pytest.mark.parametrize("warm_up", ["-1", "-0.5", "inf", "nan", "soon", *OVER_A_DAY])
def test_warm_up_outside_zero_up_to_a_day_is_rejected_before_opening_a_camera(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    astronaut_bgr: NDArray[np.uint8],
    warm_up: str,
) -> None:
    harness = Harness(monkeypatch, still(astronaut_bgr))

    with pytest.raises(SystemExit) as exited:
        capture.main(["--warm-up", warm_up])

    err = capsys.readouterr().err
    assert exited.value.code == 2
    assert "argument --warm-up:" in err
    assert "unrecognized arguments" not in err
    assert harness.opened == []


def test_a_day_is_the_longest_warm_up_and_counted_part_accepted() -> None:
    args = capture.parse_args(["--warm-up", A_DAY, "--seconds", A_DAY])

    assert args.warm_up == float(A_DAY)
    assert args.seconds == float(A_DAY)


def test_ctrl_c_in_the_warm_up_stops_rings_no_bell_and_says_there_is_no_counted_part(
    store_url: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    quiet_folder: Path,
    astronaut_bgr: NDArray[np.uint8],
) -> None:
    harness = Harness(
        monkeypatch, still(astronaut_bgr), interrupt_on_read=INTERRUPTED_READ
    )

    assert capture.main([]) == 0

    output = capsys.readouterr()
    session_id = only_session(store_url)
    lines = output.out.splitlines()
    assert lines[-2] == STOPPED
    notice = lines[-1]
    assert NO_COUNTED_PART in notice
    assert NO_COUNTED_CODE in notice
    assert f"Session {session_id}" in notice
    assert f"pulse_frame.tools.sessions delete {session_id}" in notice
    assert BEL not in output.out
    assert "Traceback" not in output.err
    assert after_sandbox_notice(output.err, action=SANDBOX_UNSUPPORTED_ACTION) == ""
    times = sample_times(store_url, session_id)
    assert len(times) == INTERRUPTED_READ - 1
    anchor_ns, counted_ns = stored_anchor_and_counted_start(store_url, session_id)
    assert counted_ns == anchor_ns + round(DEFAULT_WARM_UP_S * 1e9)
    assert times[-1] < counted_ns // NS_PER_MS
    assert harness.camera.released == 1
    assert files_under(quiet_folder) == []


def test_ctrl_c_after_the_counted_start_stops_with_no_missing_counted_part_line(
    store_url: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    quiet_folder: Path,
    astronaut_bgr: NDArray[np.uint8],
) -> None:
    Harness(
        monkeypatch, still(astronaut_bgr), interrupt_on_read=COUNTED_INTERRUPTED_READ
    )

    assert capture.main(RUN_WITH_WARM_UP) == 0

    output = capsys.readouterr()
    session_id = only_session(store_url)
    kinds = line_kinds(output.out)
    assert kinds[-1] == "stopped"
    assert kinds.count("phase") == 1
    assert NO_COUNTED_CODE not in output.out
    assert NO_COUNTED_PART not in output.out
    assert output.out.count(BEL) == 1
    anchor_ns, counted_ns = stored_anchor_and_counted_start(store_url, session_id)
    assert counted_ns == anchor_ns + seconds_ns(WARM_UP_SECONDS)
    assert sample_times(store_url, session_id)[-1] >= counted_ns // NS_PER_MS
    assert after_sandbox_notice(output.err, action=SANDBOX_UNSUPPORTED_ACTION) == ""


def test_a_repeated_clock_millisecond_is_skipped_so_no_sample_time_repeats(
    store_url: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    quiet_folder: Path,
    astronaut_bgr: NDArray[np.uint8],
) -> None:
    harness = Harness(monkeypatch, still(astronaut_bgr), repeat_on_read=REPEATED_READ)

    assert capture.main(RUN_WITHOUT_WARM_UP) == 0

    times = sample_times(store_url, only_session(store_url))
    assert len(times) == len(set(times))
    assert len(times) == harness.camera.reads - 1
    assert (
        after_sandbox_notice(capsys.readouterr().err, action=SANDBOX_UNSUPPORTED_ACTION)
        == ""
    )


def test_camera_that_cannot_open_exits_one_with_camera_unavailable_and_no_session(
    store_url: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
    quiet_folder: Path,
    astronaut_bgr: NDArray[np.uint8],
) -> None:
    harness = Harness(monkeypatch, still(astronaut_bgr), opens=False)

    assert capture.main(RUN_WITHOUT_WARM_UP) == 1

    output = capsys.readouterr()
    line = after_sandbox_notice(output.err, action=SANDBOX_UNSUPPORTED_ACTION)
    assert line.startswith("CAMERA_UNAVAILABLE: ")
    assert "capture" in line
    assert "live_check" not in line
    assert output.out == ""
    assert stored_session_ids(store_url) == []
    assert harness.camera.reads == 0
    assert harness.camera.released == 1
    assert files_under(quiet_folder) == []
    assert caplog.records == []


def test_camera_that_stops_delivering_frames_keeps_the_samples_read_before_it(
    store_url: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    quiet_folder: Path,
    astronaut_bgr: NDArray[np.uint8],
) -> None:
    harness = Harness(monkeypatch, still(astronaut_bgr), fail_on_read=FAILING_READ)

    assert capture.main(RUN_WITHOUT_WARM_UP) == 1

    output = capsys.readouterr()
    line = after_sandbox_notice(output.err, action=SANDBOX_UNSUPPORTED_ACTION)
    assert line.startswith("CAMERA_READ_FAILED: ")
    assert "capture" in line
    assert "live_check" not in line
    assert "Traceback" not in output.err
    assert harness.camera.reads == FAILING_READ
    assert harness.camera.released == 1
    assert len(sample_times(store_url, only_session(store_url))) == FAILING_READ - 1
    assert files_under(quiet_folder) == []


def test_a_flush_error_after_a_camera_error_never_replaces_the_camera_error(
    store_url: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    quiet_folder: Path,
    astronaut_bgr: NDArray[np.uint8],
) -> None:
    harness = Harness(
        monkeypatch,
        still(astronaut_bgr),
        fail_on_read=FAILING_READ,
        on_read={FAILING_READ: lambda: delete_session(only_session(store_url))},
    )

    assert capture.main(RUN_WITHOUT_WARM_UP) == 1

    output = capsys.readouterr()
    coded = coded_lines(
        after_sandbox_notice(output.err, action=SANDBOX_UNSUPPORTED_ACTION)
    )
    assert len(coded) == 2, f"expected two coded lines, got {len(coded)}"
    assert coded[0].startswith("CAMERA_READ_FAILED: ")
    assert coded[1].startswith("SESSION_NOT_FOUND: ")
    assert "Traceback" not in output.err
    assert harness.camera.released == 1


def test_ctrl_c_after_the_session_was_deleted_stops_and_reports_the_lost_flush(
    store_url: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    quiet_folder: Path,
    astronaut_bgr: NDArray[np.uint8],
) -> None:
    harness = Harness(
        monkeypatch,
        still(astronaut_bgr),
        interrupt_on_read=INTERRUPTED_READ,
        on_read={DELETE_READ: lambda: delete_session(only_session(store_url))},
    )

    assert capture.main(["--warm-up", "0"]) == 1

    output = capsys.readouterr()
    assert output.out.splitlines()[-1] == STOPPED
    coded = coded_lines(
        after_sandbox_notice(output.err, action=SANDBOX_UNSUPPORTED_ACTION)
    )
    assert len(coded) == 1, f"expected one coded line, got {len(coded)}"
    assert coded[0].startswith("SESSION_NOT_FOUND: ")
    assert "Traceback" not in output.err
    assert stored_session_ids(store_url) == []
    assert harness.camera.released == 1


def test_a_session_deleted_during_capture_stops_it_with_session_not_found(
    store_url: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    quiet_folder: Path,
    astronaut_bgr: NDArray[np.uint8],
) -> None:
    harness = Harness(
        monkeypatch,
        still(astronaut_bgr),
        on_read={INTERRUPTED_READ: lambda: delete_session(only_session(store_url))},
    )

    assert capture.main(RUN_WITHOUT_WARM_UP) == 1

    output = capsys.readouterr()
    coded = coded_lines(
        after_sandbox_notice(output.err, action=SANDBOX_UNSUPPORTED_ACTION)
    )
    assert len(coded) == 1, f"expected one coded line, got {len(coded)}"
    assert coded[0].startswith("SESSION_NOT_FOUND: ")
    assert "stopped recording" in coded[0]
    assert "Traceback" not in output.err
    assert stored_session_ids(store_url) == []
    assert harness.camera.released == 1


def test_a_flush_that_meets_rows_already_stored_says_nothing_was_lost(
    store_url: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    quiet_folder: Path,
    astronaut_bgr: NDArray[np.uint8],
) -> None:
    clash_ms = (MONOTONIC_NS + CLASH_READ * FRAME_NS) // NS_PER_MS
    harness = Harness(
        monkeypatch,
        still(astronaut_bgr),
        on_read={
            PLANT_READ: lambda: insert_samples(
                store_url, only_session(store_url), [planted_sample(clash_ms)]
            )
        },
    )

    assert capture.main(RUN_WITHOUT_WARM_UP) == 1

    output = capsys.readouterr()
    coded = coded_lines(
        after_sandbox_notice(output.err, action=SANDBOX_UNSUPPORTED_ACTION)
    )
    assert len(coded) == 1, f"expected one coded line, got {len(coded)}"
    assert coded[0].startswith("DUPLICATE_ROWS: ")
    assert "already stored" in coded[0]
    assert "lost" in coded[0]
    assert "Traceback" not in output.err
    assert harness.camera.released == 1


def test_without_the_database_url_exits_one_before_opening_the_camera(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    quiet_folder: Path,
    astronaut_bgr: NDArray[np.uint8],
) -> None:
    harness = Harness(monkeypatch, still(astronaut_bgr))

    assert capture.main(RUN_WITHOUT_WARM_UP) == 1

    output = capsys.readouterr()
    line = after_sandbox_notice(output.err, action=SANDBOX_UNSUPPORTED_ACTION)
    assert line.startswith("DATABASE_URL_MISSING: ")
    assert "Traceback" not in output.err
    assert harness.opened == []
    assert files_under(quiet_folder) == []


def test_capture_holds_one_database_connection_for_its_whole_run(
    store_url: str,
    monkeypatch: pytest.MonkeyPatch,
    quiet_folder: Path,
    astronaut_bgr: NDArray[np.uint8],
) -> None:
    Harness(monkeypatch, still(astronaut_bgr))
    real_connect = psycopg.connect
    opened = [0]

    def counting_connect(*args: object, **kwargs: object) -> object:
        opened[0] += 1
        return real_connect(*args, **kwargs)

    monkeypatch.setattr(psycopg, "connect", counting_connect)

    assert capture.main(RUN_WITHOUT_WARM_UP) == 0

    assert opened == [1]
    assert sample_times(store_url, only_session(store_url))


def test_ctrl_c_right_after_a_committed_flush_never_sends_it_again(
    store_url: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    quiet_folder: Path,
    astronaut_bgr: NDArray[np.uint8],
) -> None:
    Harness(monkeypatch, still(astronaut_bgr))
    real_add = SessionWriter.add_frame_samples
    flushed: list[int] = []

    def add_then_interrupt(
        writer: SessionWriter, session_id: int, samples: Sequence[FrameSample]
    ) -> None:
        real_add(writer, session_id, samples)
        flushed.append(len(samples))
        if len(flushed) == 1:
            raise KeyboardInterrupt

    monkeypatch.setattr(SessionWriter, "add_frame_samples", add_then_interrupt)

    assert capture.main(RUN_WITHOUT_WARM_UP) == 0

    output = capsys.readouterr()
    assert output.out.splitlines()[-1] == STOPPED
    assert "DUPLICATE_ROWS" not in output.err
    assert "Traceback" not in output.err
    assert flushed[0] > 0
    assert len(sample_times(store_url, only_session(store_url))) == flushed[0]


@pytest.mark.parametrize("shared", SHARED_DEFINITIONS)
def test_capture_reuses_the_camera_and_output_helpers_it_shares(shared: str) -> None:
    assert shared not in inspect.getsource(capture)


@pytest.mark.parametrize("seconds", ["0", "-1", "inf", "nan", *OVER_A_DAY])
def test_seconds_outside_above_zero_up_to_a_day_is_rejected_before_opening_a_camera(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    astronaut_bgr: NDArray[np.uint8],
    seconds: str,
) -> None:
    harness = Harness(monkeypatch, still(astronaut_bgr))

    with pytest.raises(SystemExit) as exited:
        capture.main(["--seconds", seconds])

    assert exited.value.code == 2
    assert "--seconds" in capsys.readouterr().err
    assert harness.opened == []
