from __future__ import annotations

import argparse
import math
import sys
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

import cv2
import numpy as np
from numpy.typing import NDArray

from pulse_frame.platform.errors import SandboxError
from pulse_frame.platform.sandbox import apply_loopback_sandbox
from pulse_frame.signal.errors import SignalError
from pulse_frame.vision.errors import VisionError
from pulse_frame.vision.model import ensure_model

if TYPE_CHECKING:
    from pulse_frame.monitor.processor import FrameProcessor, FrameResult

LINE_INTERVAL_MS = 1000


@dataclass
class Interval:
    start_ms: int
    frames: int = 0
    largest_share: float = 0.0
    moved: bool = False

    def count(self, result: FrameResult) -> None:
        self.frames += 1
        self.largest_share = max(self.largest_share, result.motion_share)
        self.moved = self.moved or result.moving

    def fps(self, end_ms: int) -> float:
        span_ms = end_ms - self.start_ms
        return self.frames * 1000.0 / span_ms if span_ms > 0 else 0.0


def positive_seconds(text: str) -> float:
    try:
        seconds = float(text)
    except ValueError as error:
        raise argparse.ArgumentTypeError(f"{text!r} is not a number") from error
    if not (math.isfinite(seconds) and seconds > 0.0):
        raise argparse.ArgumentTypeError(f"must be finite and above 0, got {text}")
    return seconds


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="live_check",
        description=(
            "Read the webcam and print the heart rate reading once a second."
            " Output is printed only, never saved; frames stay in memory and no"
            " frame is written to disk or logged."
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
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        status = apply_loopback_sandbox()
        if not status.applied:
            print(f"{status.code}: {status.reason}", file=sys.stderr)
        run(args.camera, args.seconds)
    except (SandboxError, VisionError, SignalError) as error:
        print(f"{error.code}: {error.message} {error.action}", file=sys.stderr)
        raise SystemExit(1) from error
    except KeyboardInterrupt:
        print("Stopped.")


def run(camera_index: int, seconds: float | None) -> None:
    from pulse_frame.monitor.processor import FrameProcessor

    model = ensure_model(download=False)
    camera = open_camera(camera_index)
    try:
        with FrameProcessor(model) as processor:
            watch(camera, processor, seconds)
    finally:
        camera.release()


def open_camera(index: int) -> cv2.VideoCapture:
    camera = cv2.VideoCapture(index)
    if not camera.isOpened():
        camera.release()
        raise VisionError(
            "CAMERA_UNAVAILABLE",
            f"Camera {index} could not be opened: access was denied, or no camera"
            " has that index.",
            "If macOS just asked for camera access, allow it and run live_check"
            " again. Otherwise allow the app you run the terminal in (Terminal,"
            " iTerm or VS Code) in System Settings, Privacy and Security, Camera,"
            " restart that app, or try another index with --camera.",
        )
    return camera


def read_frame(camera: cv2.VideoCapture) -> NDArray[np.uint8]:
    ok, bgr = camera.read()
    if not ok or bgr is None:
        raise VisionError(
            "CAMERA_READ_FAILED",
            "Camera gave no frame after it opened.",
            "Close other apps that use the camera (video calls, Photo Booth),"
            " check that camera access is still allowed in System Settings,"
            " Privacy and Security, Camera, then run live_check again.",
        )
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)


def now_ms() -> int:
    return int(time.monotonic() * 1000)


def watch(
    camera: cv2.VideoCapture, processor: FrameProcessor, seconds: float | None
) -> None:
    start_ms = now_ms()
    next_line_ms = start_ms + LINE_INTERVAL_MS
    last_ms = start_ms - 1
    interval = Interval(start_ms)
    while seconds is None or now_ms() - start_ms < seconds * 1000:
        rgb = read_frame(camera)
        timestamp_ms = now_ms()
        if timestamp_ms <= last_ms:
            continue
        last_ms = timestamp_ms
        result = processor.process(rgb, timestamp_ms)
        interval.count(result)
        if timestamp_ms >= next_line_ms:
            line = status_line(timestamp_ms - start_ms, result, interval, timestamp_ms)
            print(line, flush=True)
            next_line_ms += LINE_INTERVAL_MS * (
                (timestamp_ms - next_line_ms) // LINE_INTERVAL_MS + 1
            )
            interval = Interval(timestamp_ms)


def status_line(
    elapsed_ms: int, result: FrameResult, interval: Interval, end_ms: int
) -> str:
    reading = result.reading
    bpm = "-" if reading.bpm is None else f"{reading.bpm:.1f}"
    quality = "-" if reading.quality_db is None else f"{reading.quality_db:.1f} dB"
    return (
        f"{elapsed_ms / 1000:7.1f} s  state={reading.state:<11}  bpm={bpm:>5}"
        f"  quality={quality:>8}  face={yes_no(result.face)}"
        f"  moving={yes_no(interval.moved)}  motion={interval.largest_share:.4f}"
        f"  fps={interval.fps(end_ms):.1f}"
    )


def yes_no(flag: bool) -> str:
    return "yes" if flag else "no"


if __name__ == "__main__":
    main()
