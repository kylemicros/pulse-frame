import math
import struct

import cv2
import numpy as np
from numpy.typing import NDArray

from pulse_frame.stream.errors import FrameRejectedError

HEADER_BYTES = 8
JPEG_CAP_BYTES = 200 * 1024
FRAME_CAP_BYTES = HEADER_BYTES + JPEG_CAP_BYTES
MIN_FRAME_BYTES = HEADER_BYTES + 1
MAX_SAFE_MS = 2**53 - 1
MAX_WIDTH_PX = 1920
MAX_HEIGHT_PX = 1080
RGB_CHANNELS = 3
SOI = b"\xff\xd8"
MARKER_PREFIX = 0xFF
STUFFED_ZERO = 0x00
SOI_MARKER = 0xD8
EOI_MARKER = 0xD9
SOS_MARKER = 0xDA
STANDALONE_MARKERS = frozenset({0x01, *range(0xD0, 0xD8)})
SOF_MARKERS = frozenset(
    {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}
)
LENGTH_BYTES = 2
SOF_SIZE_BYTES = 5
DECODE_FLAGS = cv2.IMREAD_COLOR | cv2.IMREAD_IGNORE_ORIENTATION


def check_frame_size(message: bytes) -> None:
    if len(message) > FRAME_CAP_BYTES:
        raise FrameRejectedError("FRAME_TOO_LARGE", "too_large")
    if len(message) < MIN_FRAME_BYTES:
        raise FrameRejectedError("BAD_FRAME", "too_short")


def capture_ms(message: bytes) -> int:
    (value,) = struct.unpack_from("<d", message)
    if not (math.isfinite(value) and 0.0 <= value <= MAX_SAFE_MS):
        raise FrameRejectedError("BAD_TIMESTAMP", "out_of_range")
    return math.floor(value)


def jpeg_of(message: bytes) -> bytes:
    return message[HEADER_BYTES:]


def jpeg_rgb(jpeg: bytes) -> NDArray[np.uint8]:
    width, height = jpeg_size(jpeg)
    return decode_rgb(jpeg, width, height)


def jpeg_size(jpeg: bytes) -> tuple[int, int]:
    if not jpeg.startswith(SOI):
        raise FrameRejectedError("BAD_FRAME", "no_soi")
    at = len(SOI)
    while True:
        marker, at = next_marker(jpeg, at)
        if marker in (SOS_MARKER, EOI_MARKER):
            raise FrameRejectedError("BAD_FRAME", "no_sof")
        if marker in (SOI_MARKER, STUFFED_ZERO):
            raise FrameRejectedError("BAD_FRAME", "bad_marker")
        if marker in STANDALONE_MARKERS:
            continue
        body, at = segment_body(jpeg, at)
        if marker in SOF_MARKERS:
            return frame_dimensions(body)


def next_marker(jpeg: bytes, at: int) -> tuple[int, int]:
    if at >= len(jpeg):
        raise FrameRejectedError("BAD_FRAME", "truncated")
    if jpeg[at] != MARKER_PREFIX:
        raise FrameRejectedError("BAD_FRAME", "bad_marker")
    while at < len(jpeg) and jpeg[at] == MARKER_PREFIX:
        at += 1
    if at >= len(jpeg):
        raise FrameRejectedError("BAD_FRAME", "truncated")
    return jpeg[at], at + 1


def segment_body(jpeg: bytes, at: int) -> tuple[bytes, int]:
    if at + LENGTH_BYTES > len(jpeg):
        raise FrameRejectedError("BAD_FRAME", "truncated")
    length = int.from_bytes(jpeg[at : at + LENGTH_BYTES], "big")
    if length < LENGTH_BYTES:
        raise FrameRejectedError("BAD_FRAME", "bad_length")
    end = at + length
    if end > len(jpeg):
        raise FrameRejectedError("BAD_FRAME", "truncated")
    return jpeg[at + LENGTH_BYTES : end], end


def frame_dimensions(sof_body: bytes) -> tuple[int, int]:
    if len(sof_body) < SOF_SIZE_BYTES:
        raise FrameRejectedError("BAD_FRAME", "short_sof")
    height = int.from_bytes(sof_body[1:3], "big")
    width = int.from_bytes(sof_body[3:5], "big")
    if not (0 < width <= MAX_WIDTH_PX and 0 < height <= MAX_HEIGHT_PX):
        raise FrameRejectedError("BAD_FRAME", "dimensions")
    return width, height


def decode_rgb(jpeg: bytes, width: int, height: int) -> NDArray[np.uint8]:
    buffer = np.frombuffer(jpeg, dtype=np.uint8)
    try:
        bgr = cv2.imdecode(buffer, DECODE_FLAGS)
    except cv2.error as error:
        raise FrameRejectedError("BAD_FRAME", "decode_failed") from error
    if bgr is None:
        raise FrameRejectedError("BAD_FRAME", "decode_failed")
    if not is_colour_image(bgr, width, height):
        raise FrameRejectedError("BAD_FRAME", "shape_mismatch")
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)


def is_colour_image(image: object, width: int, height: int) -> bool:
    return (
        isinstance(image, np.ndarray)
        and image.dtype == np.uint8
        and image.shape == (height, width, RGB_CHANNELS)
    )
