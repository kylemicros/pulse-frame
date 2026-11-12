from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal, TypeGuard, get_args

WireCode = Literal[
    "DETECTION_FAILED",
    "TRACKER_CLOSED",
    "BAD_FRAME",
    "BAD_TIMESTAMP",
    "BAD_TIMESTAMPS",
    "BAD_VALUES",
    "NOT_ENOUGH_SAMPLES",
    "BAD_SAMPLE_RATE",
    "BAD_BAND",
    "BAD_WINDOW",
    "FRAME_TOO_LARGE",
    "RATE_LIMITED",
]


@dataclass(frozen=True)
class WireError:
    message: str
    action: str


RESTART_ACTION = (
    "Restart the backend and reconnect; if it happens again, report the code."
)

WIRE_ERRORS: Mapping[WireCode, WireError] = MappingProxyType(
    {
        "DETECTION_FAILED": WireError(
            "The face detector failed while reading this frame.",
            "Keep the camera running; if it happens on every frame, restart the"
            " backend and reconnect.",
        ),
        "TRACKER_CLOSED": WireError(
            "The face tracker for this connection has already been closed.",
            "Reconnect to start a new session.",
        ),
        "BAD_FRAME": WireError(
            "The frame could not be read as a capture time followed by a JPEG"
            " image of at most 1920 x 1080.",
            "Send each frame as one binary message: the capture time as a little"
            " endian float64, then the JPEG image.",
        ),
        "BAD_TIMESTAMP": WireError(
            "The frame's capture time was not a valid time, was not after the"
            " previous frame, or ran too far ahead of it.",
            "Send the performance.now() time at capture with each frame, rising"
            " from frame to frame.",
        ),
        "BAD_TIMESTAMPS": WireError(
            "The pulse tracker could not use the frame times it was given.",
            "Keep the capture times rising from frame to frame; if it happens"
            " again, reconnect.",
        ),
        "BAD_VALUES": WireError(
            "The pulse tracker got skin colours it cannot use.",
            "Make sure the face is lit and the camera image is not blank, then"
            " keep going; if it happens again, reconnect.",
        ),
        "NOT_ENOUGH_SAMPLES": WireError(
            "The pulse tracker does not have enough frames to read a pulse yet.",
            "Keep the face in view; the reading fills in as frames arrive.",
        ),
        "BAD_SAMPLE_RATE": WireError(
            "The pulse tracker's sample rate setting is not valid.",
            RESTART_ACTION,
        ),
        "BAD_BAND": WireError(
            "The pulse filter's frequency band setting is not valid.",
            RESTART_ACTION,
        ),
        "BAD_WINDOW": WireError(
            "The pulse tracker's window setting is not valid.",
            RESTART_ACTION,
        ),
        "FRAME_TOO_LARGE": WireError(
            "The frame was larger than the 200 KiB limit.",
            "Send JPEG frames at 640 x 480 and quality 0.8 or lower.",
        ),
        "RATE_LIMITED": WireError(
            "The frame came too soon: 30 frames were already taken in the last"
            " second, so this one was dropped.",
            "Send frames at least 34 ms apart.",
        ),
    }
)


WIRE_CODES: frozenset[str] = frozenset(get_args(WireCode))


def is_wire_code(code: str) -> TypeGuard[WireCode]:
    return code in WIRE_CODES


RejectReason = Literal[
    "text_message",
    "too_short",
    "no_soi",
    "no_sof",
    "bad_marker",
    "truncated",
    "bad_length",
    "short_sof",
    "dimensions",
    "decode_failed",
    "shape_mismatch",
    "out_of_range",
    "not_increasing",
    "too_far_ahead",
    "too_large",
    "rate",
]


class FrameRejectedError(Exception):
    def __init__(self, code: WireCode, reason: RejectReason) -> None:
        super().__init__(code, reason)
        self.code: WireCode = code
        self.reason: RejectReason = reason
