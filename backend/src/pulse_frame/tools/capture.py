from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from time import monotonic_ns, time_ns
from typing import TYPE_CHECKING

import cv2

from pulse_frame.platform.errors import SandboxError
from pulse_frame.platform.sandbox import apply_loopback_sandbox
from pulse_frame.signal.errors import SignalError
from pulse_frame.store.errors import StoreError
from pulse_frame.store.recording import FrameSample, SessionWriter, open_writer
from pulse_frame.tools.live_check import (
    LINE_INTERVAL_MS,
    Interval,
    open_camera,
    positive_seconds,
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
NS_PER_MS = 1_000_000
STOPPED = "Stopped."


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog=CAPTURE_COMMAND,
        description=(
            "Read the webcam and store, for each frame with a usable face, its"
            " time, the mean colour of the forehead and both cheeks, and whether"
            " the head moved, as one new session in the local store. Prints the"
            " session ID and one status line a second. Frames stay in memory;"
            " no frame, image or video is ever written."
        ),
    )
    parser.add_argument(
        "--camera", type=int, default=0, help="camera index for OpenCV (default 0)"
    )
    parser.add_argument(
        "--seconds",
        type=positive_seconds,
        default=None,
        help="stop after this many seconds, finite and above 0 (default: until Ctrl-C)",
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
        run(args.camera, args.seconds)
    except (SandboxError, VisionError, SignalError, StoreError) as error:
        report(error.code, error.message, error.action)
        report_later_errors(error)
        return 1
    except KeyboardInterrupt as stop:
        write_out(STOPPED)
        return 1 if report_later_errors(stop) else 0
    return 0


def run(camera_index: int, seconds: float | None) -> None:
    from pulse_frame.monitor.processor import FrameProcessor

    model = ensure_model(download=False)
    with open_writer() as writer:
        camera = open_camera(
            camera_index, tool=CAPTURE_TOOL, outcome=NO_SESSION_STARTED
        )
        try:
            with FrameProcessor(model) as processor:
                session_id = writer.create_session(time_ns(), monotonic_ns())
                write_out(f"Session {session_id} started, press Ctrl-C to stop.")
                record(writer, session_id, camera, processor, seconds)
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
    seconds: float | None,
) -> None:
    start_ms = now_ms()
    next_line_ms = start_ms + LINE_INTERVAL_MS
    last_ms = start_ms - 1
    interval = Interval(start_ms)
    pending: list[FrameSample] = []
    stored = 0
    try:
        while seconds is None or now_ms() - start_ms < seconds * 1000:
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
        raise
    flush(writer, session_id, pending)


def status_line(
    elapsed_ms: int, stored: int, result: FrameResult, interval: Interval, end_ms: int
) -> str:
    return (
        f"{elapsed_ms / 1000:7.1f} s  samples={stored}  face={yes_no(result.face)}"
        f"  moving={yes_no(interval.moved)}  fps={interval.fps(end_ms):.1f}"
    )


if __name__ == "__main__":
    raise SystemExit(main())
