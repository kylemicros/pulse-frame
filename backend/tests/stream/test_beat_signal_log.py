import logging
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pytest
from fastapi import WebSocket, WebSocketDisconnect
from numpy.typing import NDArray

from pulse_frame.signal.live import COUNTED_AFTER_MS
from pulse_frame.stream.__main__ import APP_LOGGER, log_config
from pulse_frame.stream.app import create_app
from pulse_frame.vision.errors import VisionError
from tests.frames import SEED, shifted_right
from tests.platform.support import Probe
from tests.signal.face_synthetic import realistic_face
from tests.stream.beat_signal import (
    CLOSE_EVENT,
    EVENT,
    GAP_OVER_MS,
    PulsedHrvFactory,
    PulsedLiveHrv,
    Second,
    assert_allowed_values,
    assert_close_values,
    assert_lines_on_their_frames,
    beat_signal_records,
    capture_times,
    caught_app_records,
    close_records,
    counted_of,
    expected_close,
    expected_signal,
    jittered_steps,
    line_fields,
    measure_of,
    mismatches,
    received_before,
    seconds_of,
    send_counting_lines,
    whole_of,
)
from tests.stream.jpegs import encode_jpeg
from tests.stream.probes import labels, run_stream_probe
from tests.stream.served import BEAT_SIGNAL_FRAMES, FRAME_TIME_MS, PACE_MS
from tests.stream.wire import (
    STANDARD_RECORD_FIELDS,
    FakeClock,
    ProcessorFactory,
    RecordingProcessor,
    assert_error,
    byte_needles,
    event_names,
    frame_message,
    is_number,
    leaked_points,
    open_stream,
    outline_points,
    recording_factory,
    rendered,
)

BPM = 72.0
FACE_SNR_DB = 10.0
FACE_RUN_S = 130.0
FAST_STEP_MS = 36
SLOW_STEP_MS = 66
STRETCHES = (
    (105.0, SLOW_STEP_MS),
    (8.0, FAST_STEP_MS),
    (3.0, SLOW_STEP_MS),
    (7.0, FAST_STEP_MS),
)
GAPS_AT_S = ((108.5, 150), (110.5, 130), (110.8, 210), (118.2, 120))
LEAD_MS = 500
STEP_SLACK_MS = 0.5
FPS_SLACK = 0.051
SLOW_FPS_RANGE = (13.0, 17.0)
FAST_FPS_RANGE = (25.0, 30.0)
SHORT_FRAMES = 45
UNDER_A_SECOND_FRAMES = 28
FIRST_SESSION_STEPS = (36,) * 30 + (150, 36, 36)
SECOND_SESSION_START_MS = 60_000
SECOND_SESSION_STEP_MS = 50
SECOND_SESSION_FRAMES = 25
COLOUR_PLACES = 4
SHIFT_PX = 12
SHIFTED_FRAMES = frozenset({6, 8, 10, 12})
BLANK_FRAMES = frozenset(range(16, 21))
REJECTED_AFTER = 10
FAILED_CALL = 15
DIAGNOSTICS_ARGS = ("--diagnostics",)
MISTYPED_ARGS = ("--diagnostic",)
GOING_AWAY = 1001
QUIET_FRAMES = 1850
SHORT_COUNTED_FRAMES = 1215
COUNTED_MINUTE_MS = 60_000
SHORT_COUNTED_MS = (15_000, 25_000)
FAILING_RUN_S = 22.0
FAILING_RUN_FRAMES = 460
FAILING_FROM_MS = 14_000
FAILING_TO_MS = 15_600


@dataclass(frozen=True)
class PacedSession:
    times: list[int]
    seconds: list[Second]
    lines: list[dict[str, str]]
    records: list[logging.LogRecord]
    every_record: list[logging.LogRecord]
    counts: list[int]
    live: PulsedLiveHrv
    processor: RecordingProcessor


def paced_steps() -> list[int]:
    rng = np.random.default_rng(SEED)
    steps = [
        step
        for seconds, mean_ms in STRETCHES
        for step in jittered_steps(rng, seconds, mean_ms)
    ]
    elapsed = np.cumsum(steps)
    for at_s, gap_ms in GAPS_AT_S:
        steps[int(np.searchsorted(elapsed, at_s * 1000.0))] = gap_ms
    return steps


@pytest.fixture(scope="module")
def paced(face_model: Path, blank_jpeg: bytes) -> PacedSession:
    face = realistic_face(BPM, FACE_SNR_DB, SEED, FACE_RUN_S).recording
    times = capture_times(int(face.timestamps_ms[0]) + LEAD_MS, paced_steps())
    seconds = seconds_of(times)
    kept_ms = frozenset({times[-1], *(times[s.frame] for s in seconds)})
    hrv = PulsedHrvFactory(face, kept_ms)
    factory = recording_factory(face_model)
    clock = FakeClock()
    app = create_app(
        processor_factory=factory, clock=clock, hrv_factory=hrv, diagnostics=True
    )
    with caught_app_records() as records, open_stream(app, clock) as stream:
        jpegs = [blank_jpeg] * len(times)
        counts = send_counting_lines(stream, times, jpegs, records)
    found = beat_signal_records(records)
    return PacedSession(
        times=times,
        seconds=seconds,
        lines=[line_fields(record.getMessage()) for record in found],
        records=found,
        every_record=list(records),
        counts=counts,
        live=hrv.built[0],
        processor=factory.latest,
    )


def percentile_bounds(steps: list[int], share: float) -> tuple[float, float]:
    low = float(np.percentile(steps, share, method="lower"))
    high = float(np.percentile(steps, share, method="higher"))
    return low - STEP_SLACK_MS, high + STEP_SLACK_MS


def assert_frame_timing(fields: dict[str, str], second: Second) -> None:
    shown = f"second ending at frame {second.frame}: {fields}"
    gaps = sum(step > GAP_OVER_MS for step in second.steps)
    assert whole_of(fields, "gaps_over_100ms") == gaps, shown
    low, high = percentile_bounds(second.steps, 50)
    assert low <= measure_of(fields, "step_p50_ms") <= high, shown
    low, high = percentile_bounds(second.steps, 95)
    assert low <= measure_of(fields, "step_p95_ms") <= high, shown
    rate = len(second.steps) * 1000.0 / second.elapsed_ms
    assert abs(measure_of(fields, "fps") - rate) <= FPS_SLACK, shown


def sample_counts(
    processor: RecordingProcessor, calls: list[int | None]
) -> tuple[int, int]:
    results = [processor.results[call] for call in calls if call is not None]
    return (
        sum(result.colours is not None for result in results),
        sum(result.moving for result in results),
    )


def test_one_beat_signal_line_comes_per_second_of_session_time(
    paced: PacedSession,
) -> None:
    assert len(paced.seconds) >= 115
    assert len(paced.lines) == len(paced.seconds), (
        f"{len(paced.lines)} lines for {len(paced.seconds)} seconds of frames"
    )
    assert_lines_on_their_frames(paced.counts, paced.seconds)


def test_each_line_reports_the_frame_timing_of_its_second(
    paced: PacedSession,
) -> None:
    gaps = sum(sum(s > GAP_OVER_MS for s in second.steps) for second in paced.seconds)
    assert gaps == len(GAPS_AT_S)
    assert len(paced.lines) == len(paced.seconds)
    for fields, second in zip(paced.lines, paced.seconds, strict=True):
        assert_frame_timing(fields, second)
        calls: list[int | None] = list(second.frames)
        assert (
            whole_of(fields, "sample_frames"),
            whole_of(fields, "moving_frames"),
        ) == sample_counts(paced.processor, calls), fields


def test_the_frames_per_second_follow_the_pace_frames_arrive_at(
    paced: PacedSession,
) -> None:
    assert len(paced.lines) == len(paced.seconds)
    slow_steps = set(range(SLOW_STEP_MS - 4, SLOW_STEP_MS + 5))
    slow = [
        measure_of(fields, "fps")
        for fields, second in zip(paced.lines, paced.seconds, strict=True)
        if set(second.steps) <= slow_steps
    ]
    fast = [
        measure_of(fields, "fps")
        for fields, second in zip(paced.lines, paced.seconds, strict=True)
        if max(second.steps) <= FAST_STEP_MS + 4
    ]
    assert slow
    assert fast
    assert all(SLOW_FPS_RANGE[0] <= fps <= SLOW_FPS_RANGE[1] for fps in slow), slow
    assert all(FAST_FPS_RANGE[0] <= fps <= FAST_FPS_RANGE[1] for fps in fast), fast


def test_each_line_reports_the_checks_and_decisions_the_live_tracker_holds(
    paced: PacedSession,
) -> None:
    snapshots = [
        paced.live.snapshots[paced.times[second.frame]] for second in paced.seconds
    ]
    truths = [expected_signal(snapshot) for snapshot in snapshots]
    assert any(not counted_of(snapshot) for snapshot in snapshots)
    assert any(counted_of(snapshot) for snapshot in snapshots)
    assert any(math.isfinite(float(truth["snr_db"])) for truth in truths)
    assert any(float(truth["checks"]) > 0 for truth in truths)
    assert len(paced.lines) == len(paced.seconds)
    for fields, second, truth in zip(paced.lines, paced.seconds, truths, strict=True):
        wrong = mismatches(fields, truth)
        assert wrong == [], (
            f"second ending at frame {second.frame}: {wrong} in {fields};"
            f" expected {truth}"
        )


def test_the_close_line_comes_once_after_the_last_line_with_the_counted_shares(
    paced: PacedSession,
) -> None:
    truth = expected_close(paced.live.snapshots[paced.times[-1]])
    assert truth is not None
    assert any(math.isfinite(float(value)) for value in truth.values())
    names = [
        name for name in event_names(paced.every_record) if name in {EVENT, CLOSE_EVENT}
    ]

    assert names == [EVENT] * len(paced.seconds) + [CLOSE_EVENT], names[-3:]
    (record,) = close_records(paced.every_record)
    fields = line_fields(record.getMessage(), CLOSE_EVENT)
    assert_close_values(fields)
    assert set(record.__dict__) <= STANDARD_RECORD_FIELDS, record.__dict__
    assert mismatches(fields, truth) == [], (fields, truth)


def test_each_line_holds_only_the_allowed_numeric_fields(
    paced: PacedSession,
) -> None:
    assert paced.records, "No beat_signal line was logged."
    for record, fields in zip(paced.records, paced.lines, strict=True):
        assert_allowed_values(fields)
        assert set(record.__dict__) <= STANDARD_RECORD_FIELDS, record.__dict__
        assert record.exc_info is None
        assert record.stack_info is None
        args = record.args if isinstance(record.args, tuple) else ()
        assert all(is_number(arg) or isinstance(arg, str) for arg in args), args
        assert all(len(str(arg).split()) == 1 for arg in args), args


def test_the_line_goes_where_the_server_sends_its_events_on_stderr(
    paced: PacedSession,
) -> None:
    config = log_config()
    logger = config["loggers"][APP_LOGGER]
    handlers = config["handlers"]
    stderr_level = logging.getLevelNamesMapping()[logger["level"]]

    assert paced.records, "No beat_signal line was logged."
    for record in paced.records:
        assert record.name.split(".")[0] == APP_LOGGER, record.name
        assert record.levelno >= stderr_level, record.levelname
    streams = [handlers[name]["stream"] for name in logger["handlers"]]
    assert [stream.partition(":")[0] for stream in streams] == ["ext"], streams
    assert [stream.rpartition("/")[2] for stream in streams] == ["sys.stderr"], streams


def test_a_session_counted_for_about_20_seconds_logs_no_close_line(
    factory: ProcessorFactory,
    clock: FakeClock,
    blank_jpeg: bytes,
    log_records: list[logging.LogRecord],
) -> None:
    times = [1_000 + k * SLOW_STEP_MS for k in range(SHORT_COUNTED_FRAMES)]
    app = create_app(processor_factory=factory, clock=clock, diagnostics=True)

    with open_stream(app, clock) as stream:
        send_counting_lines(stream, times, [blank_jpeg] * len(times), log_records)

    counted_for_ms = times[-1] - times[0] - COUNTED_AFTER_MS
    assert SHORT_COUNTED_MS[0] <= counted_for_ms <= SHORT_COUNTED_MS[1]
    assert len(beat_signal_records(log_records)) == len(seconds_of(times))
    assert "connection_closed" in event_names(log_records)
    assert close_records(log_records) == []


def test_no_line_is_logged_unless_diagnostics_are_turned_on(
    factory: ProcessorFactory,
    clock: FakeClock,
    blank_jpeg: bytes,
    log_records: list[logging.LogRecord],
) -> None:
    times = [1_000 + k * SLOW_STEP_MS for k in range(QUIET_FRAMES)]
    app = create_app(processor_factory=factory, clock=clock)

    with open_stream(app, clock) as stream:
        send_counting_lines(stream, times, [blank_jpeg] * len(times), log_records)

    assert times[-1] - times[0] > COUNTED_AFTER_MS + COUNTED_MINUTE_MS
    assert "connection_closed" in event_names(log_records)
    assert beat_signal_records(log_records) == []
    assert close_records(log_records) == []


def test_a_face_session_line_carries_no_frame_bytes_landmarks_or_colours(
    factory: ProcessorFactory,
    clock: FakeClock,
    astronaut_jpeg: bytes,
    log_records: list[logging.LogRecord],
) -> None:
    times = [1_000 + k * FAST_STEP_MS for k in range(SHORT_FRAMES)]
    app = create_app(processor_factory=factory, clock=clock, diagnostics=True)

    with open_stream(app, clock) as stream:
        jpegs = [astronaut_jpeg] * len(times)
        send_counting_lines(stream, times, jpegs, log_records)
        turns = stream.turns

    found = beat_signal_records(log_records)
    assert len(found) == 1, [record.getMessage() for record in found]
    record = found[0]
    assert_allowed_values(line_fields(record.getMessage()))
    line = rendered(record)
    sent_points = outline_points(turns)
    raw_points = [
        [float(value) for value in point]
        for result in factory.latest.results
        for patch in result.patches.values()
        if patch.outline is not None
        for point in patch.outline
    ]
    assert sent_points, "The astronaut session found no face to leak."
    assert leaked_points(line, sent_points) == [], line
    assert leaked_points(line, raw_points) == [], line
    colours = [
        value
        for result in factory.latest.results
        if result.colours is not None
        for triple in result.colours.triples()
        for value in triple
    ]
    assert colours, "The astronaut session measured no colour to leak."
    for value in colours:
        assert repr(value) not in line, line
        assert f"{value:.{COLOUR_PLACES}f}" not in line, line
    needles = [
        needle
        for t_ms in times[:2]
        for needle in byte_needles(frame_message(t_ms, astronaut_jpeg))
    ]
    assert not [needle for needle in needles if needle in line], line
    assert "array(" not in line
    assert "[" not in record.getMessage()


def test_each_line_counts_the_frames_that_gave_colours_and_the_frames_flagged_moving(
    factory: ProcessorFactory,
    clock: FakeClock,
    astronaut_jpeg: bytes,
    astronaut_rgb: NDArray[np.uint8],
    blank_jpeg: bytes,
    log_records: list[logging.LogRecord],
) -> None:
    shifted = encode_jpeg(shifted_right(astronaut_rgb, SHIFT_PX))
    times = [1_000 + k * FAST_STEP_MS for k in range(SHORT_FRAMES)]
    jpegs = [
        blank_jpeg
        if k in BLANK_FRAMES
        else shifted
        if k in SHIFTED_FRAMES
        else astronaut_jpeg
        for k in range(len(times))
    ]
    app = create_app(processor_factory=factory, clock=clock, diagnostics=True)

    with open_stream(app, clock) as stream:
        send_counting_lines(stream, times, jpegs, log_records)

    (second,) = seconds_of(times)
    samples, moving = sample_counts(factory.latest, list(second.frames))
    assert 0 < samples < len(second.frames)
    assert moving > 0
    found = beat_signal_records(log_records)
    assert len(found) == 1, [record.getMessage() for record in found]
    fields = line_fields(found[0].getMessage())
    assert whole_of(fields, "sample_frames") == samples, fields
    assert whole_of(fields, "moving_frames") == moving, fields


def test_a_failed_frame_counts_in_the_timing_and_a_rejected_frame_counts_nowhere(
    factory: ProcessorFactory,
    clock: FakeClock,
    astronaut_jpeg: bytes,
    log_records: list[logging.LogRecord],
) -> None:
    times = [1_000 + k * FAST_STEP_MS for k in range(SHORT_FRAMES)]
    app = create_app(processor_factory=factory, clock=clock, diagnostics=True)

    with open_stream(app, clock) as stream:
        stream.send_frame(times[0], astronaut_jpeg, 0.0)
        factory.latest.failures[FAILED_CALL] = VisionError(
            "DETECTION_FAILED", "detail", "action"
        )
        for k in range(1, len(times)):
            turn = stream.send_frame(times[k], astronaut_jpeg, FAST_STEP_MS / 1000.0)
            if k == FAILED_CALL:
                assert_error(turn, "DETECTION_FAILED")
            else:
                assert turn.reply["type"] == "frame", turn.texts
            if k == REJECTED_AFTER:
                assert_error(
                    stream.send_frame(times[k], astronaut_jpeg, 0.0), "BAD_TIMESTAMP"
                )

    (second,) = seconds_of(times)
    calls = [None if k == FAILED_CALL else k for k in second.frames]
    samples, moving = sample_counts(factory.latest, calls)
    found = beat_signal_records(log_records)
    assert len(found) == 1, [record.getMessage() for record in found]
    fields = line_fields(found[0].getMessage())
    assert_frame_timing(fields, second)
    assert whole_of(fields, "sample_frames") == samples, fields
    assert samples == len(second.frames) - 1
    assert whole_of(fields, "moving_frames") == moving, fields


def test_no_line_comes_before_the_session_has_a_second_of_frames(
    factory: ProcessorFactory,
    clock: FakeClock,
    blank_jpeg: bytes,
    log_records: list[logging.LogRecord],
) -> None:
    times = [5_000 + k * FAST_STEP_MS for k in range(UNDER_A_SECOND_FRAMES + 20)]
    app = create_app(processor_factory=factory, clock=clock, diagnostics=True)

    with open_stream(app, clock) as stream:
        jpegs = [blank_jpeg] * len(times)
        counts = send_counting_lines(stream, times, jpegs, log_records)

    seconds = seconds_of(times)
    assert [second.frame for second in seconds] == [UNDER_A_SECOND_FRAMES]
    assert len(beat_signal_records(log_records)) == 1
    assert_lines_on_their_frames(counts, seconds)


def test_lines_stop_when_the_session_closes_and_the_next_session_starts_fresh(
    factory: ProcessorFactory,
    clock: FakeClock,
    blank_jpeg: bytes,
    log_records: list[logging.LogRecord],
) -> None:
    first = capture_times(1_000, FIRST_SESSION_STEPS)
    second = [
        SECOND_SESSION_START_MS + k * SECOND_SESSION_STEP_MS
        for k in range(SECOND_SESSION_FRAMES)
    ]
    app = create_app(processor_factory=factory, clock=clock, diagnostics=True)

    with open_stream(app, clock) as stream:
        send_counting_lines(stream, first, [blank_jpeg] * len(first), log_records)
    with open_stream(app, clock):
        pass
    with open_stream(app, clock) as stream:
        send_counting_lines(stream, second, [blank_jpeg] * len(second), log_records)

    names = [
        name
        for name in event_names(log_records)
        if name in {"connection_opened", "connection_closed", EVENT}
    ]
    assert names == [
        "connection_opened",
        *[EVENT] * len(seconds_of(first)),
        "connection_closed",
        "connection_opened",
        "connection_closed",
        "connection_opened",
        *[EVENT] * len(seconds_of(second)),
        "connection_closed",
    ], names
    fields = line_fields(beat_signal_records(log_records)[-1].getMessage())
    assert_frame_timing(fields, seconds_of(second)[0])
    assert close_records(log_records) == []


def test_a_session_cut_off_by_a_failed_send_still_logs_its_close_line_once(
    factory: ProcessorFactory,
    clock: FakeClock,
    blank_jpeg: bytes,
    log_records: list[logging.LogRecord],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    times = [1_000 + k * SLOW_STEP_MS for k in range(QUIET_FRAMES)]
    last_ms = times[-1] + SLOW_STEP_MS
    cut = {"armed": False}
    send_text = WebSocket.send_text

    async def cut_off_send(socket: WebSocket, data: str) -> None:
        if cut["armed"]:
            raise WebSocketDisconnect(code=GOING_AWAY)
        await send_text(socket, data)

    monkeypatch.setattr(WebSocket, "send_text", cut_off_send)
    app = create_app(processor_factory=factory, clock=clock, diagnostics=True)

    with open_stream(app, clock) as stream:
        send_counting_lines(stream, times, [blank_jpeg] * len(times), log_records)
        cut["armed"] = True
        clock.advance(SLOW_STEP_MS / 1000.0)
        stream.socket.send_bytes(frame_message(last_ms, blank_jpeg))

    assert times[-1] - times[0] > COUNTED_AFTER_MS + COUNTED_MINUTE_MS
    names = [
        name
        for name in event_names(log_records)
        if name in {EVENT, CLOSE_EVENT, "client_gone", "connection_closed"}
    ]
    assert names[-3:] == [CLOSE_EVENT, "client_gone", "connection_closed"], names[-4:]
    assert names.count(CLOSE_EVENT) == 1, names[-4:]
    assert names[:-3] == [EVENT] * len(seconds_of([*times, last_ms])), names[-5:]
    (record,) = close_records(log_records)
    assert_close_values(line_fields(record.getMessage(), CLOSE_EVENT))


def test_a_failed_frame_run_does_not_move_the_clock_of_the_signal_fields(
    face_model: Path, blank_jpeg: bytes, log_records: list[logging.LogRecord]
) -> None:
    face = realistic_face(BPM, FACE_SNR_DB, SEED, FAILING_RUN_S).recording
    start_ms = int(face.timestamps_ms[0]) + LEAD_MS
    times = [start_ms + k * FAST_STEP_MS for k in range(FAILING_RUN_FRAMES)]
    failing = frozenset(
        k
        for k, t in enumerate(times)
        if FAILING_FROM_MS <= t - start_ms < FAILING_TO_MS
    )
    seconds = seconds_of(times)
    received = [received_before(second.frame, failing) for second in seconds]
    hrv = PulsedHrvFactory(face, frozenset(times[k] for k in received))
    factory = recording_factory(face_model)
    clock = FakeClock()
    app = create_app(
        processor_factory=factory, clock=clock, hrv_factory=hrv, diagnostics=True
    )

    with open_stream(app, clock) as stream:
        stream.send_frame(times[0], blank_jpeg, 0.0)
        for k in failing:
            factory.latest.failures[k] = VisionError("DETECTION_FAILED", "d", "a")
        for k in range(1, len(times)):
            turn = stream.send_frame(times[k], blank_jpeg, FAST_STEP_MS / 1000.0)
            if k in failing:
                assert_error(turn, "DETECTION_FAILED")
            else:
                assert turn.reply["type"] == "frame", turn.texts

    stalled = [
        (second, frame)
        for second, frame in zip(seconds, received, strict=True)
        if frame != second.frame
    ]
    assert stalled
    snapshots = hrv.built[0].snapshots
    assert all(snapshots[times[frame]].checks for _, frame in stalled)
    lines = [line_fields(r.getMessage()) for r in beat_signal_records(log_records)]
    assert len(lines) == len(seconds)
    for fields, second, frame in zip(lines, seconds, received, strict=True):
        assert_frame_timing(fields, second)
        truth = expected_signal(snapshots[times[frame]])
        assert mismatches(fields, truth) == [], (second.frame, fields, truth)


def served_times() -> list[int]:
    return [math.floor(FRAME_TIME_MS + k * PACE_MS) for k in range(BEAT_SIGNAL_FRAMES)]


def served_lines(stderr: str) -> list[str]:
    return [
        line[line.index(f"event={EVENT}") :]
        for line in stderr.splitlines()
        if f"event={EVENT} " in line
    ]


def assert_served_cleanly(probe: Probe) -> list[list[float]]:
    record = probe.record
    replies = record["beat_signal_replies"]
    assert probe.returncode == 0, probe.stderr[-3000:]
    assert record.get("client_error") is None, record["client_error"]
    assert [turn[-1]["type"] for turn in replies] == ["frame"] * BEAT_SIGNAL_FRAMES
    assert record["written"] == [], record["written"]
    assert record["store_modules"] == {"psycopg": False, "pulse_frame.store": False}
    return [
        point
        for turn in replies
        for patch in turn[-1]["patches"].values()
        if patch["usable"]
        for point in patch["outline"]
    ]


@pytest.fixture(scope="module")
def served_diagnostics(tmp_path_factory: pytest.TempPathFactory) -> Probe:
    return run_stream_probe(
        "serve-beat-signal",
        tmp_path_factory.mktemp("served-diagnostics"),
        *DIAGNOSTICS_ARGS,
        warnings_as_errors=True,
    )


@pytest.fixture(scope="module")
def served_quiet(tmp_path_factory: pytest.TempPathFactory) -> Probe:
    return run_stream_probe(
        "serve-beat-signal",
        tmp_path_factory.mktemp("served-quiet"),
        warnings_as_errors=True,
    )


def test_a_served_session_with_diagnostics_writes_its_lines_to_stderr_only(
    served_diagnostics: Probe,
) -> None:
    points = assert_served_cleanly(served_diagnostics)
    lines = served_lines(served_diagnostics.stderr)

    assert len(lines) == len(seconds_of(served_times())), served_diagnostics.stderr
    for line in lines:
        assert_allowed_values(line_fields(line))
        assert leaked_points(line, points) == [], line
    assert points
    assert f"event={CLOSE_EVENT}" not in served_diagnostics.stderr


@pytest.fixture(scope="module")
def bad_argument(tmp_path_factory: pytest.TempPathFactory) -> Probe:
    return run_stream_probe(
        "bad-argument",
        tmp_path_factory.mktemp("bad-argument"),
        *MISTYPED_ARGS,
        warnings_as_errors=True,
    )


def test_an_unknown_flag_prints_one_coded_line_and_exits_2_before_anything_starts(
    bad_argument: Probe,
) -> None:
    lines = [line for line in bad_argument.stderr.splitlines() if line.strip()]

    assert bad_argument.returncode == 2, bad_argument.stderr[-3000:]
    assert len(lines) == 1, bad_argument.stderr[-3000:]
    assert lines[0].startswith("BAD_ARGUMENT: "), lines
    assert DIAGNOSTICS_ARGS[0] in lines[0].removeprefix("BAD_ARGUMENT: "), lines
    assert f"unrecognized arguments: {MISTYPED_ARGS[0]}" in lines[0], lines
    assert "Traceback" not in bad_argument.stderr
    assert bad_argument.stdout == ""
    happened = labels(bad_argument.record["events"])
    assert "sandbox" not in happened, happened
    assert "ensure_model" not in happened, happened
    assert "listening" not in bad_argument.record


def test_a_served_session_without_diagnostics_writes_no_beat_signal_line(
    served_quiet: Probe,
) -> None:
    assert_served_cleanly(served_quiet)

    assert len(seconds_of(served_times())) == 1
    assert served_lines(served_quiet.stderr) == [], served_quiet.stderr[-3000:]
