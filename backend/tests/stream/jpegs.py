import struct

import cv2
import numpy as np
from numpy.typing import NDArray

SOI = b"\xff\xd8"
EOI = b"\xff\xd9"
SOS = 0xDA
DHT = 0xC4
SOF_MARKERS = frozenset(
    {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}
)
SOF_HEIGHT_AT = 5
SOF_WIDTH_AT = 7
SOF_CUT_AT = 6
DHT_COUNTS_AT = 5
EXIF_ORIENTATION_TAG = 0x0112
EXIF_SHORT = 3
GREY = (120, 120, 120)
APP0 = b"\xff\xe0"
EMPTY_SEGMENT_LENGTH = 2


def encode_jpeg(
    rgb: NDArray[np.uint8], quality: int = 90, progressive: bool = False
) -> bytes:
    params = [cv2.IMWRITE_JPEG_QUALITY, quality]
    if progressive:
        params += [cv2.IMWRITE_JPEG_PROGRESSIVE, 1]
    ok, encoded = cv2.imencode(".jpg", cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR), params)
    assert ok, "OpenCV could not encode the test frame as JPEG."
    return encoded.tobytes()


def encode_png(rgb: NDArray[np.uint8]) -> bytes:
    ok, encoded = cv2.imencode(".png", cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
    assert ok, "OpenCV could not encode the test frame as PNG."
    return encoded.tobytes()


def solid_jpeg(width: int, height: int, rgb: tuple[int, int, int] = GREY) -> bytes:
    return encode_jpeg(np.full((height, width, 3), rgb, dtype=np.uint8))


def header_segments(jpeg: bytes) -> tuple[list[bytes], bytes]:
    segments: list[bytes] = []
    at = len(SOI)
    while jpeg[at + 1] != SOS:
        length = int.from_bytes(jpeg[at + 2 : at + 4], "big")
        segments.append(jpeg[at : at + 2 + length])
        at += 2 + length
    return segments, jpeg[at:]


def rebuilt(segments: list[bytes], scan: bytes) -> bytes:
    return SOI + b"".join(segments) + scan


def is_sof(segment: bytes) -> bool:
    return segment[1] in SOF_MARKERS


def without_sof(jpeg: bytes) -> bytes:
    segments, scan = header_segments(jpeg)
    return rebuilt([s for s in segments if not is_sof(s)], scan)


def huffman_tables_before_sof(jpeg: bytes) -> bytes:
    segments, scan = header_segments(jpeg)
    tables = [s for s in segments if s[1] == DHT]
    others = [s for s in segments if s[1] != DHT]
    first_sof = next(i for i, s in enumerate(others) if is_sof(s))
    return rebuilt([*others[:first_sof], *tables, *others[first_sof:]], scan)


def with_sof_size(jpeg: bytes, width: int, height: int) -> bytes:
    segments, scan = header_segments(jpeg)
    changed = []
    for segment in segments:
        if is_sof(segment):
            body = bytearray(segment)
            body[SOF_HEIGHT_AT : SOF_HEIGHT_AT + 2] = height.to_bytes(2, "big")
            body[SOF_WIDTH_AT : SOF_WIDTH_AT + 2] = width.to_bytes(2, "big")
            segment = bytes(body)
        changed.append(segment)
    return rebuilt(changed, scan)


def cut_inside_sof(jpeg: bytes) -> bytes:
    segments, _ = header_segments(jpeg)
    first_sof = next(i for i, s in enumerate(segments) if is_sof(s))
    before = SOI + b"".join(segments[:first_sof])
    return before + segments[first_sof][:SOF_CUT_AT]


def first_segment_then_eoi(jpeg: bytes) -> bytes:
    segments, _ = header_segments(jpeg)
    return SOI + segments[0] + EOI


def with_corrupt_huffman_table(jpeg: bytes) -> bytes:
    segments, scan = header_segments(jpeg)
    changed = []
    corrupted = False
    for segment in segments:
        if segment[1] == DHT and not corrupted:
            segment = segment[:DHT_COUNTS_AT] + b"\xff" * (len(segment) - DHT_COUNTS_AT)
            corrupted = True
        changed.append(segment)
    return rebuilt(changed, scan)


def with_exif_orientation(jpeg: bytes, orientation: int) -> bytes:
    entry = struct.pack("<HHIHH", EXIF_ORIENTATION_TAG, EXIF_SHORT, 1, orientation, 0)
    tiff = b"II*\x00" + struct.pack("<IH", 8, 1) + entry + struct.pack("<I", 0)
    payload = b"Exif\x00\x00" + tiff
    app1 = b"\xff\xe1" + struct.pack(">H", len(payload) + 2) + payload
    return SOI + app1 + jpeg[len(SOI) :]


def empty_app_segments_only(total_bytes: int) -> bytes:
    segment = APP0 + EMPTY_SEGMENT_LENGTH.to_bytes(2, "big")
    count = (total_bytes - len(SOI) - len(EOI)) // len(segment)
    return SOI + segment * count + EOI
