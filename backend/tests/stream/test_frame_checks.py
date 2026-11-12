import math
from collections.abc import Awaitable, Callable

import anyio.to_thread
import cv2
import numpy as np
import pytest
from numpy.typing import NDArray

from tests.stream import jpegs
from tests.stream.wire import (
    FRAME_CAP_BYTES,
    MAX_SAFE_MS,
    PROTOCOL_CAP_BYTES,
    ProcessorFactory,
    Stream,
    assert_error,
    frame_message,
    frame_reply,
    header,
    padded_to,
)

START_MS = 1000
FOLLOW_MS = 1100
FAULT_MS = 1500
ONE_SECOND_S = 1.0
PAUSE_S = 5.0
SLACK_MS = 2000
RATE_LIMIT = 30
RATE_STEP_S = 1.0 / 32.0
QUICK_STEP_S = 1.0 / 128.0
FRAME_STEP_MS = 33
STALE_FRAMES = 40
UNDECODABLE = jpegs.SOI + bytes(64)
DECODE_FLAGS = cv2.IMREAD_COLOR | cv2.IMREAD_IGNORE_ORIENTATION
RED = (220, 30, 30)
EXIF_ROTATE_90 = 6
CROP_ROWS = slice(16, 216)
JPEG_CAP_BYTES = FRAME_CAP_BYTES - 8

type Fault = Callable[[bytes], bytes | str]


class DecodeSpy:
    def __init__(
        self,
        real: Callable[..., object],
        returns: NDArray[np.uint8] | None = None,
        raises: Exception | None = None,
    ) -> None:
        self.real = real
        self.returns = returns
        self.raises = raises
        self.flags: list[object] = []

    def __call__(self, buf: object, flags: object) -> object:
        self.flags.append(flags)
        if self.raises is not None:
            raise self.raises
        if self.returns is not None:
            return self.returns
        return self.real(buf, flags)


class WorkerSpy:
    def __init__(self, real: Callable[..., Awaitable[object]]) -> None:
        self.real = real
        self.calls = 0

    async def __call__(self, *args: object, **kwargs: object) -> object:
        self.calls += 1
        return await self.real(*args, **kwargs)


@pytest.fixture
def worker_spy(monkeypatch: pytest.MonkeyPatch) -> WorkerSpy:
    spy = WorkerSpy(anyio.to_thread.run_sync)
    monkeypatch.setattr(anyio.to_thread, "run_sync", spy)
    return spy


@pytest.fixture
def decode_spy(monkeypatch: pytest.MonkeyPatch) -> DecodeSpy:
    spy = DecodeSpy(cv2.imdecode)
    monkeypatch.setattr(cv2, "imdecode", spy)
    return spy


def start(stream: Stream, jpeg: bytes) -> None:
    frame_reply(stream.send_frame(START_MS, jpeg))


def blank_png() -> bytes:
    return jpegs.encode_png(np.zeros((16, 16, 3), dtype=np.uint8))


CHECK_ORDER: list[object] = [
    pytest.param(lambda jpeg: "hello", "BAD_FRAME", id="text"),
    pytest.param(
        lambda jpeg: "x" * (FRAME_CAP_BYTES + 1),
        "BAD_FRAME",
        id="text-over-the-cap",
    ),
    pytest.param(
        lambda jpeg: padded_to(header(math.nan) + jpeg, FRAME_CAP_BYTES + 1),
        "FRAME_TOO_LARGE",
        id="over-the-cap-with-bad-time",
    ),
    pytest.param(
        lambda jpeg: padded_to(frame_message(FAULT_MS, jpeg), FRAME_CAP_BYTES + 1),
        "FRAME_TOO_LARGE",
        id="over-the-cap",
    ),
    pytest.param(
        lambda jpeg: padded_to(frame_message(FAULT_MS, jpeg), PROTOCOL_CAP_BYTES),
        "FRAME_TOO_LARGE",
        id="at-the-protocol-cap",
    ),
    pytest.param(lambda jpeg: b"", "BAD_FRAME", id="empty"),
    pytest.param(lambda jpeg: header(FAULT_MS), "BAD_FRAME", id="header-only"),
    pytest.param(lambda jpeg: header(math.nan), "BAD_FRAME", id="short-with-bad-time"),
    pytest.param(
        lambda jpeg: header(FAULT_MS)[:5], "BAD_FRAME", id="shorter-than-a-header"
    ),
    pytest.param(
        lambda jpeg: header(math.nan) + UNDECODABLE,
        "BAD_TIMESTAMP",
        id="bad-time-on-undecodable",
    ),
    pytest.param(
        lambda jpeg: frame_message(-1.0, jpeg), "BAD_TIMESTAMP", id="negative-time"
    ),
    pytest.param(
        lambda jpeg: frame_message(math.inf, jpeg), "BAD_TIMESTAMP", id="infinite"
    ),
    pytest.param(
        lambda jpeg: frame_message(MAX_SAFE_MS + 1, jpeg),
        "BAD_TIMESTAMP",
        id="above-max-safe",
    ),
    pytest.param(
        lambda jpeg: header(START_MS) + UNDECODABLE,
        "BAD_TIMESTAMP",
        id="repeated-time-on-undecodable",
    ),
    pytest.param(
        lambda jpeg: header(START_MS + 1000 + SLACK_MS + 1) + UNDECODABLE,
        "BAD_TIMESTAMP",
        id="far-ahead-on-undecodable",
    ),
    pytest.param(
        lambda jpeg: header(FAULT_MS) + blank_png(), "BAD_FRAME", id="not-a-jpeg"
    ),
    pytest.param(
        lambda jpeg: header(FAULT_MS) + jpegs.with_corrupt_huffman_table(jpeg),
        "BAD_FRAME",
        id="undecodable",
    ),
]

FIRST_FRAME_TIMES = [
    pytest.param(0.0, 0, id="zero"),
    pytest.param(0.25, 0, id="fraction-of-a-ms"),
    pytest.param(123_456.75, 123_456, id="fractional"),
    pytest.param(50_000_000.0, 50_000_000, id="late-start"),
    pytest.param(float(MAX_SAFE_MS), MAX_SAFE_MS, id="max-safe-integer"),
]

BAD_FIRST_TIMES = [
    pytest.param(math.nan, id="nan"),
    pytest.param(math.inf, id="inf"),
    pytest.param(-math.inf, id="minus-inf"),
    pytest.param(-1.0, id="minus-one"),
    pytest.param(-0.25, id="just-below-zero"),
    pytest.param(float(MAX_SAFE_MS + 1), id="above-max-safe"),
    pytest.param(1e300, id="huge"),
]

NOT_AFTER_LAST = [
    pytest.param(float(START_MS), id="same"),
    pytest.param(START_MS + 0.5, id="same-whole-ms"),
    pytest.param(START_MS - 1.0, id="earlier"),
    pytest.param(0.0, id="zero"),
]

HEADER_FAULTS: list[object] = [
    pytest.param(lambda jpeg: blank_png(), id="no-soi"),
    pytest.param(lambda jpeg: b"\x00\x00" + jpeg[2:], id="zeroed-soi"),
    pytest.param(lambda jpeg: jpegs.SOI, id="soi-only"),
    pytest.param(lambda jpeg: jpegs.SOI + jpegs.EOI, id="eoi-before-sof"),
    pytest.param(jpegs.first_segment_then_eoi, id="segment-then-eoi"),
    pytest.param(jpegs.without_sof, id="sos-before-sof"),
    pytest.param(lambda jpeg: jpegs.SOI + b"\x00\x11\x22\x33", id="not-a-marker"),
    pytest.param(lambda jpeg: jpegs.SOI + b"\xff\xe0\x00", id="cut-in-length"),
    pytest.param(lambda jpeg: jpegs.SOI + b"\xff\xe0\x00\x10JFIF", id="cut-in-segment"),
    pytest.param(jpegs.cut_inside_sof, id="cut-in-sof"),
    pytest.param(lambda jpeg: jpegs.with_sof_size(jpeg, 0, 256), id="zero-width"),
    pytest.param(lambda jpeg: jpegs.with_sof_size(jpeg, 256, 0), id="zero-height"),
    pytest.param(lambda jpeg: jpegs.solid_jpeg(1921, 16), id="width-1921"),
    pytest.param(lambda jpeg: jpegs.solid_jpeg(16, 1081), id="height-1081"),
    pytest.param(lambda jpeg: jpegs.solid_jpeg(1080, 1920), id="portrait-full-hd"),
]

ACCEPTED_LAYOUTS: list[object] = [
    pytest.param(
        lambda rgb, jpeg: jpegs.encode_jpeg(rgb, progressive=True),
        True,
        id="progressive-sof2",
    ),
    pytest.param(
        lambda rgb, jpeg: jpegs.huffman_tables_before_sof(jpeg),
        True,
        id="huffman-tables-before-sof",
    ),
    pytest.param(
        lambda rgb, jpeg: jpegs.solid_jpeg(1920, 1080), False, id="full-hd-limit"
    ),
]


@pytest.mark.parametrize(("fault", "code"), CHECK_ORDER)
def test_each_check_answers_its_code_without_processing_or_moving_the_reference(
    stream: Stream,
    factory: ProcessorFactory,
    astronaut_jpeg: bytes,
    fault: Fault,
    code: str,
) -> None:
    start(stream, astronaut_jpeg)

    rejected = stream.send(fault(astronaut_jpeg), ONE_SECOND_S)
    follow = stream.send_frame(FOLLOW_MS, astronaut_jpeg)

    assert_error(rejected, code)
    assert frame_reply(follow)["t"] == FOLLOW_MS
    assert factory.latest.timestamps == [START_MS, FOLLOW_MS]


def test_frame_exactly_at_the_cap_is_processed(
    stream: Stream, factory: ProcessorFactory, astronaut_jpeg: bytes
) -> None:
    message = padded_to(frame_message(START_MS, astronaut_jpeg), FRAME_CAP_BYTES)

    reply = frame_reply(stream.send(message))

    assert reply["face"] is True
    assert factory.latest.timestamps == [START_MS]


@pytest.mark.parametrize(("sent", "expected"), FIRST_FRAME_TIMES)
def test_first_frame_is_accepted_at_any_valid_time(
    stream: Stream,
    factory: ProcessorFactory,
    astronaut_jpeg: bytes,
    sent: float,
    expected: int,
) -> None:
    reply = frame_reply(stream.send_frame(sent, astronaut_jpeg))

    assert reply["t"] == expected
    assert factory.latest.timestamps == [expected]


@pytest.mark.parametrize("sent", BAD_FIRST_TIMES)
def test_header_time_outside_the_safe_range_is_a_bad_timestamp(
    stream: Stream, factory: ProcessorFactory, astronaut_jpeg: bytes, sent: float
) -> None:
    rejected = stream.send_frame(sent, astronaut_jpeg)
    follow = stream.send_frame(0.0, astronaut_jpeg)

    assert_error(rejected, "BAD_TIMESTAMP")
    assert frame_reply(follow)["t"] == 0
    assert factory.latest.timestamps == [0]


@pytest.mark.parametrize("sent", NOT_AFTER_LAST)
def test_frame_at_or_before_the_last_capture_time_is_a_bad_timestamp(
    stream: Stream, factory: ProcessorFactory, astronaut_jpeg: bytes, sent: float
) -> None:
    start(stream, astronaut_jpeg)

    rejected = stream.send_frame(sent, astronaut_jpeg)
    follow = stream.send_frame(START_MS + 1, astronaut_jpeg)

    assert_error(rejected, "BAD_TIMESTAMP")
    assert frame_reply(follow)["t"] == START_MS + 1
    assert factory.latest.timestamps == [START_MS, START_MS + 1]


def test_after_a_pause_capture_time_may_lead_by_the_pause_plus_two_seconds(
    stream: Stream, factory: ProcessorFactory, astronaut_jpeg: bytes
) -> None:
    start(stream, astronaut_jpeg)
    limit_ms = START_MS + int(PAUSE_S * 1000) + SLACK_MS

    too_far = stream.send_frame(limit_ms + 1, astronaut_jpeg, PAUSE_S)
    at_limit = stream.send_frame(limit_ms, astronaut_jpeg, 0.0)
    resumed = stream.send_frame(limit_ms + int(PAUSE_S * 1000), astronaut_jpeg, PAUSE_S)

    assert_error(too_far, "BAD_TIMESTAMP")
    assert frame_reply(at_limit)["t"] == limit_ms
    assert frame_reply(resumed)["t"] == limit_ms + int(PAUSE_S * 1000)
    assert factory.latest.timestamps == [
        START_MS,
        limit_ms,
        limit_ms + int(PAUSE_S * 1000),
    ]


def test_lead_is_measured_from_the_arrival_of_the_last_processed_frame(
    stream: Stream, factory: ProcessorFactory, astronaut_jpeg: bytes
) -> None:
    start(stream, astronaut_jpeg)
    pause_s = 3.0
    limit_ms = START_MS + int(pause_s * 1000) + SLACK_MS

    rejected = stream.send(header(START_MS + 1000) + UNDECODABLE, pause_s)
    at_limit = stream.send_frame(limit_ms, astronaut_jpeg, 0.0)

    assert_error(rejected, "BAD_FRAME")
    assert frame_reply(at_limit)["t"] == limit_ms
    assert factory.latest.timestamps == [START_MS, limit_ms]


def admit_thirty(stream: Stream, jpeg: bytes) -> list[int]:
    times = [START_MS + i * FRAME_STEP_MS for i in range(RATE_LIMIT)]
    for timestamp_ms in times:
        frame_reply(stream.send_frame(timestamp_ms, jpeg, RATE_STEP_S))
    return times


def test_thirty_first_frame_within_a_second_is_rate_limited_until_the_window_passes(
    stream: Stream, factory: ProcessorFactory, astronaut_jpeg: bytes
) -> None:
    times = admit_thirty(stream, astronaut_jpeg)
    next_ms = times[-1] + FRAME_STEP_MS

    limited = stream.send_frame(next_ms, astronaut_jpeg, RATE_STEP_S)
    after_window = stream.send_frame(next_ms, astronaut_jpeg, ONE_SECOND_S)

    assert_error(limited, "RATE_LIMITED")
    assert frame_reply(after_window)["t"] == next_ms
    assert factory.latest.timestamps == [*times, next_ms]


def test_frame_exactly_one_second_after_the_first_admission_is_admitted(
    stream: Stream, factory: ProcessorFactory, astronaut_jpeg: bytes
) -> None:
    times = admit_thirty(stream, astronaut_jpeg)
    first_admitted_s = stream.clock.now - (RATE_LIMIT - 1) * RATE_STEP_S
    next_ms = times[-1] + FRAME_STEP_MS
    step_to_boundary_s = first_admitted_s + ONE_SECOND_S - stream.clock.now

    at_boundary = stream.send_frame(next_ms, astronaut_jpeg, step_to_boundary_s)

    assert stream.clock.now - first_admitted_s == ONE_SECOND_S
    assert frame_reply(at_boundary)["t"] == next_ms
    assert factory.latest.timestamps == [*times, next_ms]


def test_rate_check_comes_before_the_jpeg_check(
    stream: Stream, factory: ProcessorFactory, astronaut_jpeg: bytes
) -> None:
    times = admit_thirty(stream, astronaut_jpeg)

    limited = stream.send(header(times[-1] + FRAME_STEP_MS) + UNDECODABLE, RATE_STEP_S)

    assert_error(limited, "RATE_LIMITED")
    assert factory.latest.timestamps == times


@pytest.mark.parametrize(
    "sent",
    [pytest.param(math.nan, id="nan"), pytest.param(float(START_MS), id="stale")],
)
def test_timestamp_checks_come_before_the_rate_check(
    stream: Stream, factory: ProcessorFactory, astronaut_jpeg: bytes, sent: float
) -> None:
    times = admit_thirty(stream, astronaut_jpeg)

    rejected = stream.send_frame(sent, astronaut_jpeg, RATE_STEP_S)

    assert_error(rejected, "BAD_TIMESTAMP")
    assert factory.latest.timestamps == times


def test_frames_rejected_before_the_rate_check_do_not_use_up_the_rate(
    stream: Stream, factory: ProcessorFactory, astronaut_jpeg: bytes
) -> None:
    start(stream, astronaut_jpeg)
    for _ in range(STALE_FRAMES):
        assert_error(
            stream.send_frame(START_MS, astronaut_jpeg, QUICK_STEP_S), "BAD_TIMESTAMP"
        )
    times = [START_MS + (i + 1) * FRAME_STEP_MS for i in range(RATE_LIMIT - 2)]

    replies = [stream.send_frame(t, astronaut_jpeg, QUICK_STEP_S) for t in times]

    assert [frame_reply(turn)["t"] for turn in replies] == times
    assert factory.latest.timestamps == [START_MS, *times]


def test_frames_failing_after_the_rate_check_still_count_as_admitted(
    stream: Stream, factory: ProcessorFactory, astronaut_jpeg: bytes
) -> None:
    times = [START_MS + i * FRAME_STEP_MS for i in range(RATE_LIMIT - 1)]
    for timestamp_ms in times:
        frame_reply(stream.send_frame(timestamp_ms, astronaut_jpeg, RATE_STEP_S))
    bad_ms = times[-1] + FRAME_STEP_MS

    bad = stream.send(header(bad_ms) + UNDECODABLE, RATE_STEP_S)
    limited = stream.send_frame(bad_ms + FRAME_STEP_MS, astronaut_jpeg, RATE_STEP_S)

    assert_error(bad, "BAD_FRAME")
    assert_error(limited, "RATE_LIMITED")
    assert factory.latest.timestamps == times


@pytest.mark.parametrize("fault", HEADER_FAULTS)
def test_jpeg_header_fault_is_a_bad_frame_without_decoding(
    stream: Stream,
    factory: ProcessorFactory,
    astronaut_jpeg: bytes,
    fault: Callable[[bytes], bytes],
    decode_spy: DecodeSpy,
) -> None:
    rejected = stream.send(header(START_MS) + fault(astronaut_jpeg))
    decodes_before_follow = list(decode_spy.flags)
    follow = stream.send_frame(START_MS, astronaut_jpeg)

    assert_error(rejected, "BAD_FRAME")
    assert decodes_before_follow == []
    assert frame_reply(follow)["face"] is True
    assert factory.latest.timestamps == [START_MS]


@pytest.mark.parametrize(
    "fault",
    [
        pytest.param(lambda jpeg: b"\x00\x00" + jpeg[2:], id="zeroed-soi"),
        pytest.param(lambda jpeg: jpegs.SOI + b"\x00\x11\x22\x33", id="not-a-marker"),
        pytest.param(lambda jpeg: jpegs.solid_jpeg(1921, 16), id="width-1921"),
        pytest.param(
            lambda jpeg: jpegs.empty_app_segments_only(JPEG_CAP_BYTES),
            id="app-segments-only",
        ),
    ],
)
def test_jpeg_header_walk_runs_in_the_worker_call_that_would_decode(
    stream: Stream,
    factory: ProcessorFactory,
    astronaut_jpeg: bytes,
    fault: Callable[[bytes], bytes],
    worker_spy: WorkerSpy,
) -> None:
    start(stream, astronaut_jpeg)
    before_fault = worker_spy.calls
    rejected = stream.send(header(FOLLOW_MS) + fault(astronaut_jpeg))
    fault_calls = worker_spy.calls - before_fault
    before_valid = worker_spy.calls
    accepted = stream.send_frame(FOLLOW_MS, astronaut_jpeg)
    valid_calls = worker_spy.calls - before_valid

    assert_error(rejected, "BAD_FRAME")
    assert fault_calls == 1
    assert frame_reply(accepted)["t"] == FOLLOW_MS
    assert valid_calls == 1
    assert factory.latest.timestamps == [START_MS, FOLLOW_MS]


@pytest.mark.parametrize(("layout", "face"), ACCEPTED_LAYOUTS)
def test_valid_jpeg_layouts_are_decoded_once_and_processed(
    stream: Stream,
    factory: ProcessorFactory,
    astronaut_jpeg: bytes,
    astronaut_rgb: NDArray[np.uint8],
    layout: Callable[[NDArray[np.uint8], bytes], bytes],
    face: bool,
    decode_spy: DecodeSpy,
) -> None:
    jpeg = layout(astronaut_rgb, astronaut_jpeg)

    reply = frame_reply(stream.send_frame(START_MS, jpeg))

    assert reply["face"] is face
    assert decode_spy.flags == [DECODE_FLAGS]
    assert factory.latest.timestamps == [START_MS]


def test_exif_orientation_is_ignored_so_the_decoded_shape_matches_the_header(
    stream: Stream,
    factory: ProcessorFactory,
    astronaut_rgb: NDArray[np.uint8],
) -> None:
    cropped = np.ascontiguousarray(astronaut_rgb[CROP_ROWS])
    jpeg = jpegs.with_exif_orientation(jpegs.encode_jpeg(cropped), EXIF_ROTATE_90)

    reply = frame_reply(stream.send_frame(START_MS, jpeg))

    assert reply["face"] is True
    assert factory.latest.shapes == [cropped.shape]


def test_decoded_frame_reaches_the_processor_as_rgb(
    stream: Stream, factory: ProcessorFactory
) -> None:
    frame_reply(stream.send_frame(START_MS, jpegs.solid_jpeg(64, 48, RED)))

    red, green, blue = factory.latest.channel_means[0]
    assert factory.latest.shapes == [(48, 64, 3)]
    assert red > RED[0] - 20
    assert blue < RED[2] + 20
    assert green < RED[1] + 20


def test_jpeg_that_opencv_cannot_decode_is_a_bad_frame(
    stream: Stream,
    factory: ProcessorFactory,
    astronaut_jpeg: bytes,
    decode_spy: DecodeSpy,
) -> None:
    broken = jpegs.with_corrupt_huffman_table(astronaut_jpeg)

    rejected = stream.send_frame(START_MS, broken)
    follow = stream.send_frame(START_MS, astronaut_jpeg)

    assert_error(rejected, "BAD_FRAME")
    assert decode_spy.flags == [DECODE_FLAGS, DECODE_FLAGS]
    assert frame_reply(follow)["face"] is True
    assert factory.latest.timestamps == [START_MS]


@pytest.mark.parametrize(
    "spy",
    [
        pytest.param(
            DecodeSpy(cv2.imdecode, raises=cv2.error("decoder refused")),
            id="opencv-error",
        ),
        pytest.param(
            DecodeSpy(cv2.imdecode, returns=np.zeros((128, 128, 3), np.uint8)),
            id="shape-differs-from-header",
        ),
        pytest.param(
            DecodeSpy(cv2.imdecode, returns=np.zeros((256, 256), np.uint8)),
            id="no-colour-channels",
        ),
    ],
)
def test_decoder_error_or_shape_mismatch_is_a_bad_frame(
    stream: Stream,
    factory: ProcessorFactory,
    astronaut_jpeg: bytes,
    spy: DecodeSpy,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spy.flags.clear()
    monkeypatch.setattr(cv2, "imdecode", spy)

    rejected = stream.send_frame(START_MS, astronaut_jpeg)
    monkeypatch.setattr(cv2, "imdecode", spy.real)
    follow = stream.send_frame(START_MS, astronaut_jpeg)

    assert_error(rejected, "BAD_FRAME")
    assert spy.flags == [DECODE_FLAGS]
    assert frame_reply(follow)["face"] is True
    assert factory.latest.timestamps == [START_MS]
