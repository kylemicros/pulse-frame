from __future__ import annotations

import argparse
import math
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from time import monotonic_ns, time_ns
from typing import TYPE_CHECKING

import cv2

from pulse_frame.platform.errors import SandboxError
from pulse_frame.platform.sandbox import apply_loopback_sandbox
from pulse_frame.signal.errors import SignalError
from pulse_frame.store.errors import StoreError
from pulse_frame.store.recording import (
    NS_PER_MS,
    FrameSample,
    SessionClock,
    SessionWriter,
    open_writer,
)
from pulse_frame.store.sessions import SESSIONS_COMMAND
from pulse_frame.tools.live_check import (
    LINE_INTERVAL_MS,
    Interval,
    open_camera,
    read_frame,
    yes_no,
)
from pulse_frame.tools.sessions import report, report_sandbox, write_out
from pulse_frame.vision.errors import VisionError
from pulse_frame.vision.model import ensure_model

if TYPE_CHECKING:
    from pulse_frame.monitor.processor import FrameProcessor, FrameResult

CAPTURE_COMMAND = "uv run python -m pulse_frame.tools.capture"
CAPTURE_TOOL = "the capture"
NO_SESSION_STARTED = "No session was started."
SAMPLES_KEPT = "The samples read before it stopped are written to the session."
STOPPED = "Stopped."
BEL = "\a"
DEFAULT_SECONDS = 180.0
DEFAULT_WARM_UP = 120.0
MAX_SECONDS = 86_400.0
NS_PER_S = 1e9


@dataclass(frozen=True)
class CapturePlan:
    clock: SessionClock
    end_ns: int
    seconds: float


class StoppedInWarmUp(KeyboardInterrupt):
    def __init__(self, session_id: int) -> None:
        super().__init__(session_id)
        self.session_id = session_id


def capture_plan(anchor_ns: int, warm_up: float, seconds: float) -> CapturePlan:
    counted_ns = anchor_ns + round(warm_up * NS_PER_S)
    return CapturePlan(
        clock=SessionClock(anchor_ns=anchor_ns, counted_ns=counted_ns),
        end_ns=counted_ns + round(seconds * NS_PER_S),
        seconds=seconds,
    )


def phase_line(seconds: float) -> str:
    return f"{BEL}Warm-up done, counting {seconds:g} s from now."


def no_counted_part_line(session_id: int) -> str:
    return (
        f"NO_COUNTED_SAMPLES: Session {session_id} has no counted part: it was"
        " stopped during the warm-up, so the replay will refuse it. Delete it"
        f" with `{SESSIONS_COMMAND} delete {session_id}` in backend/ if you no"
        " longer need it, then run the capture again past the warm-up bell."
    )


def seconds_number(text: str) -> float:
    try:
        return float(text)
    except ValueError as error:
        raise argparse.ArgumentTypeError(f"{text!r} is not a number") from error


def warm_up_seconds(text: str) -> float:
    seconds = seconds_number(text)
    if not (math.isfinite(seconds) and 0.0 <= seconds <= MAX_SECONDS):
        raise argparse.ArgumentTypeError(
            f"must be finite, at least 0 and at most {MAX_SECONDS:g}, got {text}"
        )
    return seconds


def counted_seconds(text: str) -> float:
    seconds = seconds_number(text)
    if not (math.isfinite(seconds) and 0.0 < seconds <= MAX_SECONDS):
        raise argparse.ArgumentTypeError(
            f"must be finite, above 0 and at most {MAX_SECONDS:g}, got {text}"
        )
    return seconds


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog=CAPTURE_COMMAND,
        description=(
            "Read the webcam and store, for each frame with a usable face, its"
            " time, the mean colour of the forehead and both cheeks, and whether"
            " the head moved, as one new session in the local store. Prints the"
            " session ID and one status line a second. The first --warm-up seconds"
            " let the camera and the face settle; a bell and one line mark the"
            " counted start, and a bell marks the end. Frames stay in memory;"
            " no frame, image or video is ever written."
        ),
    )
    parser.add_argument(
        "--camera", type=int, default=0, help="camera index for OpenCV (default 0)"
    )
    parser.add_argument(
        "--seconds",
        type=counted_seconds,
        default=DEFAULT_SECONDS,
        help="counted seconds after the warm-up, finite, above 0 and at most"
        f" {MAX_SECONDS:g} (default {DEFAULT_SECONDS:g})",
    )
    parser.add_argument(
        "--warm-up",
        type=warm_up_seconds,
        default=DEFAULT_WARM_UP,
        help="seconds recorded before the counted part, finite, at least 0 and"
        f" at most {MAX_SECONDS:g} (default {DEFAULT_WARM_UP:g})",
    )
    return parser.parse_args(argv)


def report_later_errors(first: BaseException) -> bool:
    later: list[str] = getattr(first, "__notes__", [])
    for line in later:
        print(line, file=sys.stderr)
    return bool(later)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        report_sandbox(apply_loopback_sandbox())
        run(args.camera, args.warm_up, args.seconds)
    except (SandboxError, VisionError, SignalError, StoreError) as error:
        report(error.code, error.message, error.action)
        report_later_errors(error)
        return 1
    except KeyboardInterrupt as stop:
        write_out(STOPPED)
        if isinstance(stop, StoppedInWarmUp):
            write_out(no_counted_part_line(stop.session_id))
        return 1 if report_later_errors(stop) else 0
    return 0


def run(camera_index: int, warm_up: float, seconds: float) -> None:
    from pulse_frame.monitor.processor import FrameProcessor

    model = ensure_model(download=False)
    with open_writer() as writer:
        camera = open_camera(
            camera_index, tool=CAPTURE_TOOL, outcome=NO_SESSION_STARTED
        )
        try:
            with FrameProcessor(model) as processor:
                wall_ns = time_ns()
                plan = capture_plan(monotonic_ns(), warm_up, seconds)
                session_id = writer.create_session(
                    wall_ns, plan.clock.anchor_ns, plan.clock.counted_ns
                )
                write_out(f"Session {session_id} started, press Ctrl-C to stop.")
                record(writer, session_id, camera, processor, plan)
        finally:
            camera.release()


def now_ms() -> int:
    return monotonic_ns() // NS_PER_MS


def frame_sample(t_ms: int, result: FrameResult) -> FrameSample | None:
    colours = result.colours
    if colours is None:
        return None
    forehead, left_cheek, right_cheek = (
        (float(r), float(g), float(b)) for r, g, b in colours.triples()
    )
    return FrameSample(
        t_ms=t_ms,
        forehead=forehead,
        left_cheek=left_cheek,
        right_cheek=right_cheek,
        moving=bool(result.moving),
    )


def flush(writer: SessionWriter, session_id: int, pending: list[FrameSample]) -> int:
    batch = list(pending)
    pending.clear()
    if batch:
        writer.add_frame_samples(session_id, batch)
    return len(batch)


def flush_after(
    first: BaseException,
    writer: SessionWriter,
    session_id: int,
    pending: list[FrameSample],
) -> None:
    try:
        flush(writer, session_id, pending)
    except StoreError as later:
        first.add_note(f"{later.code}: {later.message} {later.action}")


def record(
    writer: SessionWriter,
    session_id: int,
    camera: cv2.VideoCapture,
    processor: FrameProcessor,
    plan: CapturePlan,
) -> None:
    start_ms = plan.clock.anchor_ns // NS_PER_MS
    next_line_ms = start_ms + LINE_INTERVAL_MS
    last_ms = start_ms - 1
    interval = Interval(start_ms)
    pending: list[FrameSample] = []
    stored = 0
    announced = not plan.clock.warmed_up
    try:
        while monotonic_ns() < plan.end_ns:
            rgb = read_frame(camera, tool=CAPTURE_TOOL, outcome=SAMPLES_KEPT)
            timestamp_ms = now_ms()
            if timestamp_ms <= last_ms:
                continue
            last_ms = timestamp_ms
            result = processor.process(rgb, timestamp_ms)
            interval.count(result)
            sample = frame_sample(timestamp_ms, result)
            if sample is not None:
                pending.append(sample)
            if not announced and timestamp_ms >= plan.clock.counted_ms:
                write_out(phase_line(plan.seconds))
                announced = True
            if timestamp_ms >= next_line_ms:
                stored += flush(writer, session_id, pending)
                elapsed_ms = timestamp_ms - start_ms
                write_out(
                    status_line(elapsed_ms, stored, result, interval, timestamp_ms)
                )
                next_line_ms += LINE_INTERVAL_MS * (
                    (timestamp_ms - next_line_ms) // LINE_INTERVAL_MS + 1
                )
                interval = Interval(timestamp_ms)
    except BaseException as first:
        flush_after(first, writer, session_id, pending)
        if isinstance(first, KeyboardInterrupt) and not announced:
            raise stopped_in_warm_up(first, session_id) from None
        raise
    flush(writer, session_id, pending)
    write_out(BEL)


def stopped_in_warm_up(first: KeyboardInterrupt, session_id: int) -> StoppedInWarmUp:
    stopped = StoppedInWarmUp(session_id)
    for note in getattr(first, "__notes__", []):
        stopped.add_note(note)
    return stopped


def status_line(
    elapsed_ms: int, stored: int, result: FrameResult, interval: Interval, end_ms: int
) -> str:
    return (
        f"{elapsed_ms / 1000:7.1f} s  samples={stored}  face={yes_no(result.face)}"
        f"  moving={yes_no(interval.moved)}  fps={interval.fps(end_ms):.1f}"
    )


if __name__ == "__main__":
    raise SystemExit(main())
