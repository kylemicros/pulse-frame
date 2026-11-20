import inspect
import itertools
import math
import os
import re
import subprocess
import sys
import typing
from collections.abc import Callable
from pathlib import Path

import numpy as np
import psycopg
import pytest
from numpy.typing import NDArray
from psycopg import sql

from pulse_frame.signal.beats import SNR_FLOOR_DB, Interval, IntervalFlag
from pulse_frame.signal.hrv import (
    READING_FLOOR_DB,
    WINDOW_MS,
    HrvTracker,
    WindowCheck,
    alternates,
)
from pulse_frame.signal.tracker import UPDATE_INTERVAL_MS
from pulse_frame.store.recording import frame_samples
from pulse_frame.tools import replay
from pulse_frame.tools.sessions import SANDBOX_UNSUPPORTED_ACTION
from tests.database import (
    COLOUR_COLUMNS,
    SAMPLE_COLUMNS,
    WALL_NS,
    Row,
    insert_recording,
    rows_under,
    stored_rows,
    with_database_url,
)
from tests.frames import SEED, TRUE_BPM
from tests.platform.sandboxed import BACKEND, REPLAY_MODULE
from tests.platform.support import (
    PROBE_TIMEOUT_S,
    after_sandbox_notice,
    assert_sandbox_status_for_this_platform,
    missing_symbol_message,
    refused_message,
    run_probe,
    sandbox_lines,
)
from tests.signal.beat_synthetic import (
    TRACKER_NOISE_SD,
    beat_recording,
    chain,
    cycle_at,
    late_wave_blood_volume,
    nearest_errors,
    physical_recording,
    respiring_ibis,
    rmssd,
    rounded_blood_volume,
    sdnn,
    systolic_midpoints,
)
from tests.signal.face_synthetic import realistic_face
from tests.signal.hrv_tracking import seconds_of, true_ibis_inside
from tests.signal.synthetic import REGION_DC, Recording, region_colours

DURATION_S = 90.0
SHORT_S = 30.0
LONG_S = 330.0
PROBE_S = 5.0
NS_PER_MS = 1_000_000
ANCHOR_LEAD_MS = 250
SUMMARY_SPAN_MS = 60_000.0
EDGE_MS = 3_000.0
HRV_TOLERANCE_MS = 3.0
PRINTED_MS = 0.1
BPM_TOLERANCE = 1.0
COUNT_TOLERANCE = 1
MIN_ACCEPTED_PERCENT = 90.0
SHARE_TOLERANCE_PERCENT = 0.5
BEAT_ERROR_MS = 20.0
BEAT_SHARE = 0.9
ROUNDING_MS = 2.0
WINDOW_SLACK_MS = 50.0
MIN_ACCEPTED_MS = 60_000.0
MAX_WINDOW_MS = 300_000.0
EARLY_END_S = 20.0
MOTION_FROM_S = 45.0
MOTION_TO_S = 46.0
FLAG_REACH_S = 1.6 + 2.0
FAST_BPM = 150.0
FAST_FROM_S = 62.0
FAST_TO_S = 64.0
FAR_OFF_SHARE = 0.5
SAMPLE_HOLE_MS = 100.0
SUMMARY_MIN_ACCEPTED_MS = 45_000.0
SWEEP_TOLERANCE_MS = {50.0: 5.0, 72.0: 3.0, 110.0: 3.0}
WAVE_S = 120.0
WAVE_FROM_S = 90.0
WAVE_RATES_BPM = [72.0]
WAVE_SEEDS = [0, 1, 2]
DIASTOLIC_HEIGHT = 0.5
DIASTOLIC_AT = 0.45
LAST_SECOND_S = 1.0
STALE_MS = 10_000.0
STALE_TAIL_S = 12.0
MAX_REJECTED_SHARE = 0.2
MIN_FAR_OFF = 1
TRUE_IBI_MS = 60_000.0 / TRUE_BPM
SHARE_LEAD_COUNT = 28
SHARE_TAIL_COUNT = 28
SHARE_REJECTED_COUNT = 16
SHORT_REJECTED_IBI_MS = 400.0
SHARE_NEWEST_AFTER_MS = 1_000.0
WEAK_CODE = "SIGNAL_TOO_WEAK"
WEAK_NOISE_SD = 1.0
WEAK_FROM_S = 60.0
WEAK_TAIL_S = 130.0
TOO_SHORT_S = 8.0
FLOOR_MINUTE_IBIS = 80
READING_MARGIN_DB = 1.0
UNDER_READING_BPM = 66.0
UNDER_READING_SNR_DB = 0.0
UNDER_READING_SEED = SEED + 2
UNDER_READING_S = 80.0
MOST_UNMEASURED = 40
MEASURED_UNDER = 6
SOME_UNMEASURED = 4
UNMEASURED_WORDING = "not measured"
FACE_LOSS_BPM = 60.0
FACE_LOSS_SESSION_S = 120.0
FACE_LOSS_EVERY_S = 14.0
FACE_LOSS_S = 1.5
WEAK_ACTION_WORDS = ("light", "still", "exposure")
AGGREGATE_LIMIT = 1_000.0
NUMBER = r"-?\d+(?:\.\d+)?"
NOTICE_WORDING = "under the pulse quality floor"
OLD_WORDING = "too weak against the noise"
CHECK_STEP_MS = 1_000.0
CHECK_SESSION_MS = 200_000.0
CHECK_MARGIN_DB = 5.0
WEAK_DB = SNR_FLOOR_DB - CHECK_MARGIN_DB
STRONG_DB = SNR_FLOOR_DB + CHECK_MARGIN_DB
BOUNDARY_CHECKS = 100
ACCEPTED_IN_MINUTE = 3
AGGREGATE_NUMBER = r"-?\d+(?:\.\d)?"
SLOW_START_BPM = 50.0
SLOW_UNTIL_S = 25.0
HOLE_S = 0.4
HOLES_AT_S = (50.0, 70.0)
MOTION_CODE = 1
LOW_QUALITY_CODE = 3
EDGE_CODE = 4
OK_CODE = 0
INTERRUPTED_EXIT = 130
FLAG_CODES = {
    "ok": 0,
    "motion": 1,
    "gap": 2,
    "low_quality": 3,
    "edge": 4,
    "out_of_range": 5,
    "off_median": 6,
}
REPLAY_TABLES = ("beats", "intervals", "hrv_readings")
HRV_COLUMNS = ["t_ms", "rmssd_ms", "sdnn_ms", "window_ms", "accepted_count"]
INTERVAL_COLUMNS = ["t_ms", "interval_ms", "flag"]
PRINTED_VALUE = r"-|\d+\.\d"
SUMMARY_LINE = (
    rf"Session (?P<session>\d+) replayed,"
    rf" newest minute: bpm=(?P<bpm>{PRINTED_VALUE}) count=(?P<count>\d+);"
    rf" last 5 minutes: rmssd=(?P<rmssd>{PRINTED_VALUE})(?: ms)?"
    rf" sdnn=(?P<sdnn>{PRINTED_VALUE})(?: ms)?;"
    rf" whole session: accepted=(?P<accepted>{PRINTED_VALUE})%?$"
)
FIELD_NAMES = ("bpm", "count", "rmssd", "sdnn", "accepted")
SESSION_TOKEN = r"\b[Ss]ession (\d+)\b"
MAX_LINES = 3
FRAME_WRITERS = [
    "imwrite",
    "VideoWriter",
    "imencode",
    "write_bytes",
    "tofile",
    "np.save",
]
SHARED_DEFINITIONS = [
    "def report(",
    "def report_sandbox",
    "def write_out",
    "INTERRUPTED_EXIT =",
]
LIBRARY_FAILURES = [
    pytest.param(
        "init-fails-with-text",
        refused_message("the test library refused this profile"),
        id="init-fails-with-text",
    ),
    pytest.param(
        "init-missing",
        missing_symbol_message("sandbox_init"),
        id="init-missing",
    ),
]

type Session = tuple[int, Recording, NDArray[np.float64]]


def sample_rows(recording: Recording, moving: NDArray[np.bool_]) -> list[Row]:
    times = np.round(recording.timestamps_ms).astype(np.int64)
    return [
        {
            "t_ms": int(t_ms),
            **dict(
                zip(COLOUR_COLUMNS, (float(v) for v in frame.reshape(9)), strict=True)
            ),
            "moving": bool(is_moving),
        }
        for t_ms, frame, is_moving in zip(times, recording.regions, moving, strict=True)
    ]


def stored_recording(
    url: str, recording: Recording, moving: NDArray[np.bool_] | None = None
) -> int:
    flags = (
        np.zeros(recording.timestamps_ms.size, dtype=np.bool_)
        if moving is None
        else moving
    )
    first_ms = round(float(recording.timestamps_ms[0]))
    monotonic_ns = (first_ms - ANCHOR_LEAD_MS) * NS_PER_MS
    return insert_recording(url, WALL_NS, monotonic_ns, sample_rows(recording, flags))


def summary(out: str) -> dict[str, str]:
    matches = list(re.finditer(SUMMARY_LINE, out, re.MULTILINE))
    assert len(matches) == 1, f"the summary line appears {len(matches)} times"
    return {name: matches[0][name] for name in FIELD_NAMES}


def lines_with_other_numbers(out: str) -> int:
    stripped = re.sub(
        SESSION_TOKEN, "", re.sub(SUMMARY_LINE, "", out, flags=re.MULTILINE)
    )
    return sum(1 for line in stripped.splitlines() if re.search(r"\d", line))


def beat_times(url: str, session_id: int) -> NDArray[np.float64]:
    return np.array(
        [row[0] for row in stored_rows(url, "beats", session_id, ["t_ms"])],
        dtype=float,
    )


def interval_rows(url: str, session_id: int) -> list[tuple[object, ...]]:
    return stored_rows(url, "intervals", session_id, INTERVAL_COLUMNS)


def newest_sample_ms(recording: Recording) -> float:
    return float(round(float(recording.timestamps_ms[-1])))


def true_ibis_in_summary_span(
    recording: Recording, beats: NDArray[np.float64]
) -> NDArray[np.float64]:
    newest_ms = newest_sample_ms(recording)
    midpoints = systolic_midpoints(beats, rounded_blood_volume)
    ends = midpoints[1:]
    inside = (ends >= newest_ms - SUMMARY_SPAN_MS) & (ends <= newest_ms - EDGE_MS)
    return np.diff(midpoints)[inside]


def touching_ok_steps(rows: list[tuple[object, ...]]) -> list[float]:
    return [
        float(str(later[1])) - float(str(earlier[1]))
        for earlier, later in itertools.pairwise(rows)
        if earlier[2] == OK_CODE
        and later[2] == OK_CODE
        and abs(float(str(later[0])) - float(str(later[1])) - float(str(earlier[0])))
        <= ROUNDING_MS
    ]


def accepted_in_summary_span(
    url: str, session_id: int, recording: Recording
) -> list[tuple[object, ...]]:
    newest_ms = newest_sample_ms(recording)
    return [
        row
        for row in interval_rows(url, session_id)
        if row[2] == OK_CODE
        and newest_ms - SUMMARY_SPAN_MS <= float(str(row[0])) <= newest_ms
    ]


def minute_rows(
    url: str, session_id: int, recording: Recording
) -> list[tuple[object, ...]]:
    newest_ms = newest_sample_ms(recording)
    return [
        row
        for row in interval_rows(url, session_id)
        if newest_ms - SUMMARY_SPAN_MS <= float(str(row[0])) <= newest_ms
    ]


def assert_floor_holds(url: str, session_id: int, recording: Recording) -> None:
    accepted_ms = sum(
        float(str(row[1]))
        for row in accepted_in_summary_span(url, session_id, recording)
    )
    assert accepted_ms >= replay.SUMMARY_MIN_ACCEPTED_MS, (
        f"the minute holds {accepted_ms / 1000:.1f} s accepted, under the floor"
    )


def assert_rejected_share_holds(
    url: str, session_id: int, recording: Recording
) -> None:
    flags = [row[2] for row in minute_rows(url, session_id, recording)]
    settled = len(flags) - flags.count(EDGE_CODE)
    rejected = (settled - flags.count(OK_CODE)) / settled
    assert rejected <= MAX_REJECTED_SHARE, (
        f"the minute rejects {rejected:.0%}, over the rejected-share gate"
    )


def newest_accepted_gap_ms(url: str, session_id: int, recording: Recording) -> float:
    ends = [
        float(str(row[0]))
        for row in accepted_in_summary_span(url, session_id, recording)
    ]
    assert ends, "the minute holds no accepted interval"
    return newest_sample_ms(recording) - max(ends)


def assert_minute_does_not_alternate(
    url: str, session_id: int, recording: Recording
) -> None:
    replayed = replay.replay_samples(frame_samples(session_id))
    span = replay.newest_span(replayed.intervals, replayed.newest_ms)
    assert as_rows(span) == minute_rows(url, session_id, recording), (
        "the rebuilt minute differs from the stored minute"
    )
    assert not alternates(span), "the minute alternates, so that gate may blank it"


def update_times(sample_times: list[int]) -> set[int]:
    updates: set[int] = set()
    next_ms = sample_times[0] + UPDATE_INTERVAL_MS
    for t_ms in sample_times[1:]:
        if t_ms >= next_ms:
            updates.add(t_ms)
            next_ms = t_ms + UPDATE_INTERVAL_MS
    return updates


def committed_history_and_pending(url: str, session_id: int) -> list[Interval]:
    tracker = HrvTracker()
    committed: dict[float, Interval] = {}
    for row in stored_rows(url, "frame_samples", session_id, SAMPLE_COLUMNS):
        colours = np.array(row[1:10], dtype=float).reshape(3, 3)
        tracker.add(int(str(row[0])), region_colours(colours), moving=bool(row[10]))
        for interval in tracker.settled_intervals():
            committed[interval.start_ms] = interval
    settled = tracker.settled_intervals()
    pending = tracker.intervals()[len(settled) :]
    history = [committed[start] for start in sorted(committed)]
    return [*history, *pending]


def as_rows(intervals: list[Interval]) -> list[tuple[object, ...]]:
    return [
        (round(i.end_ms), i.end_ms - i.start_ms, FLAG_CODES[i.flag]) for i in intervals
    ]


@pytest.fixture
def clean_session(store_url: str) -> Session:
    recording, beats = beat_recording(TRUE_BPM, SEED, DURATION_S)
    return stored_recording(store_url, recording), recording, beats


def test_flag_codes_cover_every_tracker_flag_with_ok_as_zero() -> None:
    tracker_flags = set(typing.get_args(IntervalFlag.__value__))

    assert set(replay.FLAG_CODES) == tracker_flags
    assert replay.FLAG_CODES == FLAG_CODES


def test_the_stored_time_hole_threshold_is_one_hundred_ms() -> None:
    assert replay.SAMPLE_HOLE_MS == SAMPLE_HOLE_MS


@pytest.mark.parametrize("frame_writer", FRAME_WRITERS)
def test_replay_has_no_call_that_writes_a_frame_or_image(frame_writer: str) -> None:
    assert frame_writer not in inspect.getsource(replay)


@pytest.mark.parametrize("shared", SHARED_DEFINITIONS)
def test_replay_reuses_the_output_helpers_of_the_sessions_tool(shared: str) -> None:
    assert shared not in inspect.getsource(replay)


@pytest.mark.parametrize("bpm", list(SWEEP_TOLERANCE_MS))
def test_summary_gives_the_minutes_bpm_and_the_hrv_windows_rmssd_and_sdnn_near_truth(
    store_url: str,
    capsys: pytest.CaptureFixture[str],
    bpm: float,
) -> None:
    recording, beats = beat_recording(bpm, SEED, DURATION_S)
    session_id = stored_recording(store_url, recording)
    minute_truth = true_ibis_in_summary_span(recording, beats)
    window_truth = true_ibis_inside(recording, beats, rounded_blood_volume)
    assert DURATION_S * 1000.0 < WINDOW_MS
    assert DURATION_S * 1000.0 - SUMMARY_SPAN_MS < SUMMARY_MIN_ACCEPTED_MS

    assert replay.main([str(session_id)]) == 0

    output = capsys.readouterr()
    fields = summary(output.out)
    tolerance = SWEEP_TOLERANCE_MS[bpm]
    assert float(fields["bpm"]) == pytest.approx(
        60_000.0 / minute_truth.mean(), abs=BPM_TOLERANCE
    )
    assert float(fields["rmssd"]) == pytest.approx(rmssd(window_truth), abs=tolerance)
    assert float(fields["sdnn"]) == pytest.approx(sdnn(minute_truth), abs=tolerance)
    assert float(fields["accepted"]) >= MIN_ACCEPTED_PERCENT
    assert after_sandbox_notice(output.err, action=SANDBOX_UNSUPPORTED_ACTION) == ""


@pytest.mark.parametrize("bpm", WAVE_RATES_BPM)
@pytest.mark.parametrize("seed", WAVE_SEEDS)
def test_a_minute_that_alternates_prints_no_bpm_rmssd_or_sdnn(
    store_url: str, capsys: pytest.CaptureFixture[str], bpm: float, seed: int
) -> None:
    shape = late_wave_blood_volume(
        DIASTOLIC_HEIGHT, DIASTOLIC_AT, cycle_at(bpm, WAVE_FROM_S)
    )
    recording, _ = physical_recording(
        bpm, SEED + seed, WAVE_S, noise_sd=TRACKER_NOISE_SD, shape=shape
    )
    session_id = stored_recording(store_url, recording)

    assert replay.main([str(session_id)]) == 0

    fields = summary(capsys.readouterr().out)
    assert_floor_holds(store_url, session_id, recording)
    assert_rejected_share_holds(store_url, session_id, recording)
    assert newest_accepted_gap_ms(store_url, session_id, recording) <= STALE_MS
    assert fields["bpm"] == "-"
    assert fields["rmssd"] == "-"
    assert fields["sdnn"] == "-"


def test_a_minute_gone_stale_prints_no_bpm_rmssd_or_sdnn(
    store_url: str, capsys: pytest.CaptureFixture[str]
) -> None:
    recording, _ = beat_recording(TRUE_BPM, SEED, DURATION_S)
    seconds = seconds_of(recording)
    regions = recording.regions.copy()
    regions[seconds >= seconds[-1] - STALE_TAIL_S] = REGION_DC
    session_id = stored_recording(
        store_url, Recording(recording.timestamps_ms, regions)
    )

    assert replay.main([str(session_id)]) == 0

    fields = summary(capsys.readouterr().out)
    assert_floor_holds(store_url, session_id, recording)
    assert_rejected_share_holds(store_url, session_id, recording)
    assert newest_accepted_gap_ms(store_url, session_id, recording) > STALE_MS
    assert_minute_does_not_alternate(store_url, session_id, recording)
    assert fields["bpm"] == "-"
    assert fields["rmssd"] == "-"
    assert fields["sdnn"] == "-"


def minute_of_row(row: tuple[object, ...], newest_ms: float) -> int:
    return int((newest_ms - float(str(row[0]))) // SUMMARY_SPAN_MS)


def root_mean_square(steps: list[float]) -> float:
    return float(np.sqrt(np.mean(np.square(steps))))


def test_summary_rmssd_pools_the_whole_short_session_and_sdnn_takes_its_full_minute(
    store_url: str, capsys: pytest.CaptureFixture[str]
) -> None:
    recording, _ = beat_recording(TRUE_BPM, SEED, DURATION_S)
    slow, _ = beat_recording(SLOW_START_BPM, SEED, DURATION_S)
    early = seconds_of(recording) < SLOW_UNTIL_S
    regions = recording.regions.copy()
    regions[early] = slow.regions[early]
    session_id = stored_recording(
        store_url, Recording(recording.timestamps_ms, regions)
    )
    newest_ms = newest_sample_ms(recording)
    assert DURATION_S * 1000.0 < WINDOW_MS

    assert replay.main([str(session_id)]) == 0

    fields = summary(capsys.readouterr().out)
    rows = interval_rows(store_url, session_id)
    newest_rows = [row for row in rows if minute_of_row(row, newest_ms) == 0]
    older_ok_ms = sum(
        float(str(row[1]))
        for row in rows
        if row[2] == OK_CODE and minute_of_row(row, newest_ms) > 0
    )
    newest_ok = [float(str(row[1])) for row in newest_rows if row[2] == OK_CODE]
    whole_ok = [float(str(row[1])) for row in rows if row[2] == OK_CODE]
    whole_rmssd = root_mean_square(touching_ok_steps(rows))
    assert abs(sdnn(whole_ok) - sdnn(newest_ok)) > HRV_TOLERANCE_MS
    assert older_ok_ms < SUMMARY_MIN_ACCEPTED_MS
    assert sum(newest_ok) >= SUMMARY_MIN_ACCEPTED_MS
    assert all(
        abs(newest_ms - float(str(row[0])) - SUMMARY_SPAN_MS) > ROUNDING_MS
        for row in rows
    )
    assert abs(whole_rmssd - root_mean_square(touching_ok_steps(newest_rows))) > (
        HRV_TOLERANCE_MS
    )
    assert float(fields["rmssd"]) == pytest.approx(whole_rmssd, abs=PRINTED_MS)
    assert float(fields["sdnn"]) == pytest.approx(sdnn(newest_ok), abs=PRINTED_MS)


def test_summary_count_is_the_accepted_intervals_of_the_newest_minute(
    store_url: str,
    clean_session: Session,
    capsys: pytest.CaptureFixture[str],
) -> None:
    session_id, recording, _ = clean_session

    assert replay.main([str(session_id)]) == 0

    count = int(summary(capsys.readouterr().out)["count"])
    expected = len(accepted_in_summary_span(store_url, session_id, recording))
    assert abs(count - expected) <= COUNT_TOLERANCE


def stored_fast_splice(
    url: str, recording: Recording, from_s: float, to_s: float
) -> int:
    fast, _ = beat_recording(FAST_BPM, SEED, DURATION_S)
    seconds = seconds_of(recording)
    span = (seconds >= from_s) & (seconds < to_s)
    regions = recording.regions.copy()
    regions[span] = fast.regions[span]
    return stored_recording(url, Recording(recording.timestamps_ms, regions), span)


def test_a_minute_over_the_rejected_share_prints_no_bpm_rmssd_or_sdnn() -> None:
    before = chain(respiring_ibis(SHARE_LEAD_COUNT, TRUE_IBI_MS))
    rejected = chain(
        [SHORT_REJECTED_IBI_MS] * SHARE_REJECTED_COUNT,
        before[-1].end_ms,
        ["motion"] * SHARE_REJECTED_COUNT,
    )
    after = chain(respiring_ibis(SHARE_TAIL_COUNT, TRUE_IBI_MS), rejected[-1].end_ms)
    intervals = [*before, *rejected, *after]
    newest_ms = round(after[-1].end_ms + SHARE_NEWEST_AFTER_MS)
    span = replay.newest_span(intervals, newest_ms)
    accepted_ms = sum(i.ibi_ms for i in span if i.accepted)
    assert len(span) == len(intervals)
    assert accepted_ms >= replay.SUMMARY_MIN_ACCEPTED_MS
    assert SHARE_REJECTED_COUNT / len(span) > MAX_REJECTED_SHARE
    assert newest_ms - after[-1].end_ms <= STALE_MS
    assert not alternates(span)

    result = replay.summarise(
        replay.ReplayResult(
            intervals=intervals, readings=[], newest_ms=newest_ms, window_checks=[]
        )
    )

    assert result.bpm is None
    assert result.rmssd_ms is None
    assert result.sdnn_ms is None


def test_summary_bpm_ignores_rejected_intervals_however_far_off_they_are(
    store_url: str, capsys: pytest.CaptureFixture[str]
) -> None:
    recording, beats = beat_recording(TRUE_BPM, SEED, DURATION_S)
    session_id = stored_fast_splice(store_url, recording, FAST_FROM_S, FAST_TO_S)
    truth = true_ibis_in_summary_span(recording, beats)

    assert replay.main([str(session_id)]) == 0

    fields = summary(capsys.readouterr().out)
    true_ibi_ms = float(truth.mean())
    far_off = [
        row
        for row in minute_rows(store_url, session_id, recording)
        if row[2] not in {OK_CODE, EDGE_CODE}
        and abs(float(str(row[1])) - true_ibi_ms) > FAR_OFF_SHARE * true_ibi_ms
    ]
    settled_ms = [
        float(str(row[1]))
        for row in minute_rows(store_url, session_id, recording)
        if row[2] != EDGE_CODE
    ]
    assert len(far_off) >= MIN_FAR_OFF, (
        f"the spliced span gave {len(far_off)} far-off rejected intervals"
    )
    assert 60_000.0 / np.mean(settled_ms) != pytest.approx(
        60_000.0 / truth.mean(), abs=BPM_TOLERANCE
    )
    assert float(fields["bpm"]) == pytest.approx(
        60_000.0 / truth.mean(), abs=BPM_TOLERANCE
    )


def test_replay_prints_per_session_aggregates_only_and_no_row_values(
    store_url: str,
    clean_session: Session,
    capsys: pytest.CaptureFixture[str],
) -> None:
    session_id, _, _ = clean_session

    assert replay.main([str(session_id)]) == 0

    out = capsys.readouterr().out
    lines = out.splitlines()
    assert 1 <= len(lines) <= MAX_LINES, f"replay printed {len(lines)} lines"
    assert lines_with_other_numbers(out) == 0, (
        "replay printed numbers beyond the aggregates"
    )
    beats = beat_times(store_url, session_id)
    assert beats.size > 0
    shown = sum(1 for beat in beats if str(int(beat)) in out)
    assert shown == 0, f"{shown} stored beat times appear in the output"


def share_without_edges(url: str, session_id: int) -> float:
    flags = [row[2] for row in interval_rows(url, session_id)]
    assert EDGE_CODE in flags, "the session stored no edge interval"
    return 100.0 * flags.count(OK_CODE) / (len(flags) - flags.count(EDGE_CODE))


def test_accepted_share_leaves_the_edge_intervals_out_of_its_denominator(
    store_url: str,
    clean_session: Session,
    capsys: pytest.CaptureFixture[str],
) -> None:
    session_id, _, _ = clean_session

    assert replay.main([str(session_id)]) == 0

    printed = float(summary(capsys.readouterr().out)["accepted"])
    assert printed == pytest.approx(
        share_without_edges(store_url, session_id), abs=SHARE_TOLERANCE_PERCENT
    )


def test_accepted_share_leaves_out_edge_intervals_followed_by_motion_at_the_end(
    store_url: str, capsys: pytest.CaptureFixture[str]
) -> None:
    recording, _ = beat_recording(TRUE_BPM, SEED, DURATION_S)
    seconds = seconds_of(recording)
    moving = seconds >= seconds[-1] - LAST_SECOND_S
    session_id = stored_recording(store_url, recording, moving)

    assert replay.main([str(session_id)]) == 0

    printed = float(summary(capsys.readouterr().out)["accepted"])
    flags = [row[2] for row in interval_rows(store_url, session_id)]
    assert flags[-1] == MOTION_CODE, "the last pending interval is not motion"
    assert printed == pytest.approx(
        share_without_edges(store_url, session_id), abs=SHARE_TOLERANCE_PERCENT
    )


def test_replay_stores_beats_on_the_systolic_midpoints_and_intervals_between_them(
    store_url: str, clean_session: Session
) -> None:
    session_id, recording, beats = clean_session

    assert replay.main([str(session_id)]) == 0

    found = beat_times(store_url, session_id)
    truth = true_ibis_inside(recording, beats, rounded_blood_volume)
    assert found.size >= BEAT_SHARE * (truth.size + 1)
    midpoints = systolic_midpoints(beats, rounded_blood_volume)
    assert float(np.median(np.abs(nearest_errors(midpoints, found)))) <= BEAT_ERROR_MS
    intervals = interval_rows(store_url, session_id)
    assert len(intervals) >= BEAT_SHARE * truth.size
    for t_ms, interval_ms, flag in intervals:
        assert flag in FLAG_CODES.values()
        end = float(str(t_ms))
        start = end - float(str(interval_ms))
        assert np.abs(found - end).min() <= ROUNDING_MS
        assert np.abs(found - start).min() <= ROUNDING_MS


def test_replay_stores_hrv_readings_only_when_set_with_their_window_and_count(
    store_url: str, clean_session: Session
) -> None:
    session_id, recording, beats = clean_session
    truth = true_ibis_inside(recording, beats, rounded_blood_volume)
    first_ms = float(recording.timestamps_ms[0])
    last_ms = float(recording.timestamps_ms[-1])

    assert replay.main([str(session_id)]) == 0

    readings = stored_rows(store_url, "hrv_readings", session_id, HRV_COLUMNS)
    assert readings, "a 90 s clean session stored no HRV reading"
    for t_ms, _, _, window_ms, accepted_count in readings:
        at_ms = float(str(t_ms))
        window = float(str(window_ms))
        count = int(str(accepted_count))
        assert first_ms - ROUNDING_MS <= at_ms <= last_ms + ROUNDING_MS
        assert (
            MIN_ACCEPTED_MS
            <= window
            <= min(MAX_WINDOW_MS, at_ms - first_ms + ROUNDING_MS)
        )
        assert count * truth.max() >= MIN_ACCEPTED_MS
        assert count * truth.min() <= window + WINDOW_SLACK_MS
    _, newest_rmssd, newest_sdnn, _, _ = readings[-1]
    assert float(str(newest_rmssd)) == pytest.approx(rmssd(truth), abs=HRV_TOLERANCE_MS)
    assert float(str(newest_sdnn)) == pytest.approx(sdnn(truth), abs=HRV_TOLERANCE_MS)


def test_hrv_rows_sit_on_the_tracker_update_times_at_least_one_update_apart(
    store_url: str, clean_session: Session
) -> None:
    session_id, _, _ = clean_session
    sample_times = [
        int(str(row[0]))
        for row in stored_rows(store_url, "frame_samples", session_id, ["t_ms"])
    ]

    assert replay.main([str(session_id)]) == 0

    times = [
        int(str(row[0]))
        for row in stored_rows(store_url, "hrv_readings", session_id, ["t_ms"])
    ]
    assert times, "a 90 s clean session stored no HRV reading"
    off_update = sorted(set(times) - update_times(sample_times))
    assert off_update == [], f"{len(off_update)} HRV rows sit off an update time"
    assert all(np.diff(times) >= UPDATE_INTERVAL_MS)


def test_the_summary_floor_is_forty_five_seconds_of_accepted_ibi_in_the_minute() -> (
    None
):
    assert replay.SUMMARY_MIN_ACCEPTED_MS == SUMMARY_MIN_ACCEPTED_MS


def test_a_minute_below_the_accepted_floor_prints_no_bpm_rmssd_or_sdnn(
    store_url: str, capsys: pytest.CaptureFixture[str]
) -> None:
    recording, _ = beat_recording(TRUE_BPM, SEED, SHORT_S)
    session_id = stored_recording(store_url, recording)

    assert replay.main([str(session_id)]) == 0

    fields = summary(capsys.readouterr().out)
    assert fields["bpm"] == "-"
    assert fields["rmssd"] == "-"
    assert fields["sdnn"] == "-"
    counts = rows_under(store_url, session_id)
    assert counts["hrv_readings"] == 0
    assert counts["beats"] > 0
    assert counts["intervals"] > 0


def test_stored_sample_holes_keep_hrv_near_the_truth_off_every_accepted_interval(
    store_url: str, capsys: pytest.CaptureFixture[str]
) -> None:
    whole, beats = beat_recording(TRUE_BPM, SEED, DURATION_S)
    seconds = seconds_of(whole)
    in_hole = np.zeros(seconds.size, dtype=np.bool_)
    for at_s in HOLES_AT_S:
        in_hole |= (seconds >= at_s) & (seconds < at_s + HOLE_S)
    holed = Recording(whole.timestamps_ms[~in_hole], whole.regions[~in_hole])
    session_id = stored_recording(store_url, holed)
    times = np.round(holed.timestamps_ms)
    holes = [
        (float(times[k]), float(times[k + 1]))
        for k in np.flatnonzero(np.diff(times) > SAMPLE_HOLE_MS)
    ]
    assert len(holes) == len(HOLES_AT_S)
    truth = true_ibis_inside(whole, beats, rounded_blood_volume)

    assert replay.main([str(session_id)]) == 0

    fields = summary(capsys.readouterr().out)
    assert float(fields["rmssd"]) == pytest.approx(rmssd(truth), abs=HRV_TOLERANCE_MS)
    touching = [
        (row[0], hole)
        for row in interval_rows(store_url, session_id)
        if row[2] == OK_CODE
        for hole in holes
        if float(str(row[0])) - float(str(row[1])) <= hole[1]
        and float(str(row[0])) >= hole[0]
    ]
    assert touching == [], f"{len(touching)} accepted intervals touch a hole"
    low_quality = [
        row
        for row in interval_rows(store_url, session_id)
        if row[2] == LOW_QUALITY_CODE
    ]
    assert low_quality, "no interval near a hole was marked low quality"


def test_replay_stores_the_motion_code_for_intervals_near_stored_motion(
    store_url: str,
) -> None:
    recording, _ = beat_recording(TRUE_BPM, SEED, DURATION_S)
    seconds = seconds_of(recording)
    moving = (seconds >= MOTION_FROM_S) & (seconds < MOTION_TO_S)
    session_id = stored_recording(store_url, recording, moving)
    first_ms = float(recording.timestamps_ms[0])

    assert replay.main([str(session_id)]) == 0

    marked = [
        (float(str(t_ms)) - first_ms) / 1000.0
        for t_ms, _, flag in interval_rows(store_url, session_id)
        if flag == MOTION_CODE
    ]
    assert marked, "no stored interval carries the motion code"
    reach = (MOTION_FROM_S - FLAG_REACH_S, MOTION_TO_S + FLAG_REACH_S)
    assert all(reach[0] <= t <= reach[1] for t in marked)


def test_replay_past_three_hundred_seconds_stores_committed_and_pending_intervals(
    store_url: str,
) -> None:
    recording, _ = beat_recording(TRUE_BPM, SEED, LONG_S)
    session_id = stored_recording(store_url, recording)
    first_ms = float(recording.timestamps_ms[0])
    expected = as_rows(committed_history_and_pending(store_url, session_id))

    assert replay.main([str(session_id)]) == 0

    stored = interval_rows(store_url, session_id)
    assert stored == expected
    assert (float(str(stored[0][0])) - first_ms) / 1000.0 <= EARLY_END_S
    assert stored[-1][2] == EDGE_CODE


def test_running_replay_twice_replaces_its_rows_instead_of_doubling_them(
    store_url: str, clean_session: Session
) -> None:
    session_id, recording, _ = clean_session
    assert replay.main([str(session_id)]) == 0
    first = {
        table: stored_rows(store_url, table, session_id, ["t_ms"])
        for table in REPLAY_TABLES
    }

    assert replay.main([str(session_id)]) == 0

    second = {
        table: stored_rows(store_url, table, session_id, ["t_ms"])
        for table in REPLAY_TABLES
    }
    assert second == first
    counts = rows_under(store_url, session_id)
    assert counts["frame_samples"] == recording.timestamps_ms.size
    assert counts["sessions"] == 1


def test_ctrl_c_during_a_replay_exits_130_and_keeps_the_earlier_rows(
    store_url: str,
    clean_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    session_id, _, _ = clean_session
    assert replay.main([str(session_id)]) == 0
    capsys.readouterr()
    before = {
        table: stored_rows(store_url, table, session_id, ["t_ms"])
        for table in REPLAY_TABLES
    }
    real_execute = psycopg.Cursor.execute
    real_executemany = psycopg.Cursor.executemany
    interrupted = [0]

    def interrupt_inserts(statement: object, cursor: psycopg.Cursor) -> None:
        text = (
            statement.as_string(cursor)
            if isinstance(statement, sql.Composable)
            else str(statement)
        )
        if interrupted == [0] and text.lstrip().upper().startswith("INSERT"):
            interrupted[0] = 1
            raise KeyboardInterrupt

    def execute(
        cursor: psycopg.Cursor, statement: object, *args: object, **kwargs: object
    ) -> object:
        interrupt_inserts(statement, cursor)
        return real_execute(cursor, statement, *args, **kwargs)

    def executemany(
        cursor: psycopg.Cursor, statement: object, *args: object, **kwargs: object
    ) -> object:
        interrupt_inserts(statement, cursor)
        return real_executemany(cursor, statement, *args, **kwargs)

    monkeypatch.setattr(psycopg.Cursor, "execute", execute)
    monkeypatch.setattr(psycopg.Cursor, "executemany", executemany)

    assert replay.main([str(session_id)]) == INTERRUPTED_EXIT

    monkeypatch.setattr(psycopg.Cursor, "execute", real_execute)
    monkeypatch.setattr(psycopg.Cursor, "executemany", real_executemany)
    err = capsys.readouterr().err
    assert interrupted == [1]
    assert "REPLAY_INTERRUPTED" in err
    assert "Traceback" not in err
    after = {
        table: stored_rows(store_url, table, session_id, ["t_ms"])
        for table in REPLAY_TABLES
    }
    assert after == before


def test_replay_of_a_session_without_frame_samples_says_so_and_writes_nothing(
    store_url: str, capsys: pytest.CaptureFixture[str]
) -> None:
    session_id = insert_recording(store_url, WALL_NS, ANCHOR_LEAD_MS * NS_PER_MS, [])

    assert replay.main([str(session_id)]) == 1

    output = capsys.readouterr()
    line = after_sandbox_notice(output.err, action=SANDBOX_UNSUPPORTED_ACTION)
    assert line.startswith("NO_FRAME_SAMPLES: ")
    assert "pulse_frame.tools.sessions delete" in line
    assert "capture" in line
    assert "Traceback" not in output.err
    assert output.out == ""
    assert rows_under(store_url, session_id) == {
        "sessions": 1,
        "frame_samples": 0,
        "beats": 0,
        "intervals": 0,
        "hrv_readings": 0,
    }


def test_replay_of_an_unknown_session_exits_one_with_session_not_found(
    store_url: str,
    clean_session: Session,
    capsys: pytest.CaptureFixture[str],
) -> None:
    session_id, _, _ = clean_session
    unknown = session_id + 1_000

    assert replay.main([str(unknown)]) == 1

    err = capsys.readouterr().err
    assert "SESSION_NOT_FOUND" in err
    assert "pulse_frame.tools.sessions list" in err
    assert "Traceback" not in err
    assert rows_under(store_url, session_id)["beats"] == 0


def test_replay_without_the_database_url_exits_one_with_the_coded_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert replay.main(["1"]) == 1

    assert "DATABASE_URL_MISSING" in capsys.readouterr().err


def test_replay_into_a_reader_that_closed_early_still_stores_and_exits_zero(
    store_url: str, clean_session: Session
) -> None:
    session_id, _, _ = clean_session
    reader, writer = os.pipe()
    os.close(reader)

    done = subprocess.run(
        [sys.executable, "-m", REPLAY_MODULE, str(session_id)],
        cwd=BACKEND,
        env=with_database_url(store_url),
        stdout=writer,
        stderr=subprocess.PIPE,
        text=True,
        timeout=PROBE_TIMEOUT_S,
        check=False,
    )
    os.close(writer)

    assert done.returncode == 0, f"replay exited {done.returncode}"
    assert "Traceback" not in done.stderr
    assert "BrokenPipeError" not in done.stderr
    assert rows_under(store_url, session_id)["intervals"] > 0


def test_replay_applies_the_sandbox_before_connecting_to_the_store(
    store_url: str, tmp_path: Path
) -> None:
    recording, _ = beat_recording(TRUE_BPM, SEED, PROBE_S)
    session_id = stored_recording(store_url, recording)

    probe = run_probe(
        "replay", tmp_path, str(session_id), env=with_database_url(store_url)
    )

    assert probe.returncode == 0, f"replay exited {probe.returncode}"
    statuses = probe.record.get("connect_statuses")
    assert statuses, "replay never connected to the store"
    for status in statuses:
        assert_sandbox_status_for_this_platform(status)


def test_replay_off_macos_prints_sandbox_unsupported_with_the_store_action(
    store_url: str, tmp_path: Path
) -> None:
    recording, _ = beat_recording(TRUE_BPM, SEED, PROBE_S)
    session_id = stored_recording(store_url, recording)

    probe = run_probe(
        "replay-unsupported",
        tmp_path,
        str(session_id),
        env=with_database_url(store_url),
    )

    assert probe.returncode == 0, f"replay exited {probe.returncode}"
    unsupported = probe.record["unsupported"]
    assert sandbox_lines(probe.stderr) == [
        f"SANDBOX_UNSUPPORTED: {unsupported['reason']} {SANDBOX_UNSUPPORTED_ACTION}"
    ]


@pytest.mark.parametrize(("mode", "message"), LIBRARY_FAILURES)
def test_replay_stops_with_sandbox_failed_and_a_store_only_action(
    tmp_path: Path, mode: str, message: str
) -> None:
    probe = run_probe("replay-broken", tmp_path, mode)

    assert probe.returncode == 1
    assert probe.stdout == ""
    lines = probe.stderr.splitlines()
    assert len(lines) == 1, f"expected one stderr line, got {len(lines)}"
    opening = f"SANDBOX_FAILED: {message} "
    assert lines[0].startswith(opening)
    action = lines[0].removeprefix(opening)
    assert "store" in action
    assert "mediapipe" not in action.lower()
    assert "camera" not in action.lower()
    assert probe.record.get("connect_statuses") == []


def weak_recording(duration_s: float, weak_from_s: float = 0.0) -> Recording:
    recording, _ = beat_recording(TRUE_BPM, SEED, duration_s)
    rng = np.random.default_rng(SEED)
    weak = seconds_of(recording) >= weak_from_s
    regions = recording.regions.copy()
    regions[weak] += rng.normal(0.0, WEAK_NOISE_SD, regions[weak].shape)
    return Recording(recording.timestamps_ms, regions)


def weak_notices(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.startswith(f"{WEAK_CODE}: ")]


def expected_summary_line(session_id: int) -> str:
    result = replay.replay_samples(frame_samples(session_id))
    line = replay.summary_line(session_id, replay.summarise(result))
    assert re.fullmatch(SUMMARY_LINE, line), "the summary line lost its layout"
    return line


def replay_lines(session_id: int, capsys: pytest.CaptureFixture[str]) -> list[str]:
    assert replay.main([str(session_id)]) == 0
    output = capsys.readouterr()
    rest = after_sandbox_notice(output.err, action=SANDBOX_UNSUPPORTED_ACTION)
    return [*output.out.splitlines(), *rest.splitlines()]


def assert_one_weak_notice_after_an_unchanged_summary(
    session_id: int, lines: list[str]
) -> str:
    notices = weak_notices("\n".join(lines))
    assert len(notices) == 1, f"replay printed {len(notices)} {WEAK_CODE} lines"
    assert lines[0] == expected_summary_line(session_id)
    assert lines[1:] == notices
    return notices[0]


@pytest.mark.parametrize(
    "weak_from_s", [0.0, WEAK_FROM_S], ids=["whole_session", "newest_minute"]
)
def test_a_minute_under_the_snr_floor_adds_one_coded_notice_after_the_summary(
    store_url: str, capsys: pytest.CaptureFixture[str], weak_from_s: float
) -> None:
    session_id = stored_recording(store_url, weak_recording(WEAK_TAIL_S, weak_from_s))

    lines = replay_lines(session_id, capsys)

    notice = assert_one_weak_notice_after_an_unchanged_summary(session_id, lines)
    fields = summary(lines[0])
    assert fields["bpm"] == "-"
    assert fields["rmssd"] == "-"
    assert fields["sdnn"] == "-"
    assert fields["count"] == "0"
    assert all(word in notice.lower() for word in WEAK_ACTION_WORDS)
    assert NOTICE_WORDING in notice
    assert OLD_WORDING not in notice


def test_the_weak_signal_notice_prints_aggregates_only(
    store_url: str, capsys: pytest.CaptureFixture[str]
) -> None:
    session_id = stored_recording(store_url, weak_recording(WEAK_TAIL_S))

    lines = replay_lines(session_id, capsys)

    notice = assert_one_weak_notice_after_an_unchanged_summary(session_id, lines)
    numbers = re.findall(NUMBER, notice.removeprefix(f"{WEAK_CODE}: "))
    assert all(re.fullmatch(AGGREGATE_NUMBER, number) for number in numbers)
    assert all(abs(float(number)) < AGGREGATE_LIMIT for number in numbers)


def test_the_weak_signal_notice_follows_the_summary_line_in_the_merged_output(
    store_url: str,
) -> None:
    session_id = stored_recording(store_url, weak_recording(WEAK_TAIL_S))

    done = subprocess.run(
        [sys.executable, "-m", REPLAY_MODULE, str(session_id)],
        cwd=BACKEND,
        env=with_database_url(store_url),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=PROBE_TIMEOUT_S,
        check=False,
    )

    sandbox = sandbox_lines(done.stdout)
    lines = [line for line in done.stdout.splitlines() if line not in sandbox]
    assert done.returncode == 0, f"replay exited {done.returncode}"
    assert len(lines) == 2
    assert lines[0] == expected_summary_line(session_id)
    assert lines[1].startswith(f"{WEAK_CODE}: ")


def clean_recording() -> Recording:
    recording, _ = beat_recording(TRUE_BPM, SEED, DURATION_S)
    return recording


def too_short_recording() -> Recording:
    recording, _ = beat_recording(TRUE_BPM, SEED, TOO_SHORT_S)
    return recording


@pytest.mark.parametrize(
    ("build", "moving"),
    [(clean_recording, False), (too_short_recording, False), (clean_recording, True)],
    ids=["clean_face", "too_short", "moving_throughout"],
)
def test_no_weak_signal_notice_when_the_snr_floor_is_not_the_reason(
    store_url: str,
    capsys: pytest.CaptureFixture[str],
    build: Callable[[], Recording],
    moving: bool,
) -> None:
    recording = build()
    flags = np.full(recording.timestamps_ms.size, moving, dtype=np.bool_)
    session_id = stored_recording(store_url, recording, flags)

    lines = replay_lines(session_id, capsys)

    assert lines == [expected_summary_line(session_id)]


def checks_over(first_ms: float, last_ms: float, snr_db: float) -> list[WindowCheck]:
    return [
        WindowCheck(t_ms=float(t_ms), snr_db=snr_db)
        for t_ms in np.arange(first_ms, last_ms, CHECK_STEP_MS)
    ]


def checked_result(checks: list[WindowCheck]) -> replay.ReplayResult:
    return replay.ReplayResult(
        intervals=[],
        readings=[],
        newest_ms=round(CHECK_SESSION_MS),
        window_checks=checks,
    )


def weak_minute_summary(count: int) -> replay.Summary:
    return replay.Summary(
        bpm=None, rmssd_ms=None, sdnn_ms=None, count=count, accepted_percent=None
    )


def test_older_weak_windows_before_a_strong_newest_minute_give_no_notice() -> None:
    newest_from_ms = CHECK_SESSION_MS - SUMMARY_SPAN_MS
    result = checked_result(
        [
            *checks_over(0.0, newest_from_ms, WEAK_DB),
            *checks_over(newest_from_ms, CHECK_SESSION_MS + 1.0, STRONG_DB),
        ]
    )
    assert replay.is_too_weak(result.window_checks)

    newest = replay.newest_checks(result)

    assert newest
    assert not replay.is_too_weak(newest)
    assert replay.weak_notice(result, weak_minute_summary(0)) is None


@pytest.mark.parametrize(
    ("under", "too_weak"), [(50, False), (51, True)], ids=["half", "over_half"]
)
def test_the_notice_needs_more_than_half_the_newest_windows_under_the_floor(
    under: int, too_weak: bool
) -> None:
    checks = [
        WindowCheck(
            t_ms=CHECK_SESSION_MS - index * 100.0,
            snr_db=WEAK_DB if index < under else STRONG_DB,
        )
        for index in range(BOUNDARY_CHECKS)
    ]

    weak = replay.is_too_weak(checks)

    assert weak is too_weak


def test_a_weak_minute_with_some_accepted_beats_gives_no_notice() -> None:
    result = checked_result(
        checks_over(CHECK_SESSION_MS - SUMMARY_SPAN_MS, CHECK_SESSION_MS + 1.0, WEAK_DB)
    )
    assert replay.is_too_weak(replay.newest_checks(result))

    with_beats = replay.weak_notice(result, weak_minute_summary(ACCEPTED_IN_MINUTE))
    without_beats = replay.weak_notice(result, weak_minute_summary(0))

    assert with_beats is None
    assert without_beats is not None
    assert NOTICE_WORDING in without_beats
    assert OLD_WORDING not in without_beats


def floor_session(offset_db: float) -> replay.ReplayResult:
    intervals = chain(respiring_ibis(FLOOR_MINUTE_IBIS, TRUE_IBI_MS))
    newest_ms = round(intervals[-1].end_ms + SHARE_NEWEST_AFTER_MS)
    first_ms = newest_ms - SUMMARY_SPAN_MS
    checks = [
        WindowCheck(t_ms=float(t_ms), snr_db=READING_FLOOR_DB + offset_db)
        for t_ms in np.arange(first_ms, newest_ms + 1.0, CHECK_STEP_MS)
    ]
    return replay.ReplayResult(
        intervals=intervals, readings=[], newest_ms=newest_ms, window_checks=checks
    )


def test_a_67_s_window_with_every_check_under_the_floor_keeps_bpm_but_drops_hrv() -> (
    None
):
    under_result = floor_session(-READING_MARGIN_DB)
    intervals = under_result.intervals
    oldest_ms = under_result.newest_ms - WINDOW_MS
    assert all(i.start_ms >= oldest_ms for i in intervals)
    assert all(
        intervals[0].start_ms <= c.t_ms <= under_result.newest_ms
        for c in under_result.window_checks
    )
    assert all(c.snr_db < READING_FLOOR_DB for c in under_result.window_checks)

    under = replay.summarise(under_result)
    over = replay.summarise(floor_session(READING_MARGIN_DB))

    assert over.rmssd_ms is not None
    assert over.sdnn_ms is not None
    assert under.rmssd_ms is None
    assert under.sdnn_ms is None
    assert under.bpm == pytest.approx(over.bpm)
    assert under.count == over.count


def test_a_face_under_the_reading_floor_stores_no_hrv_reading_and_prints_none(
    store_url: str, capsys: pytest.CaptureFixture[str]
) -> None:
    face = realistic_face(
        UNDER_READING_BPM, UNDER_READING_SNR_DB, UNDER_READING_SEED, UNDER_READING_S
    )
    session_id = stored_recording(store_url, face.recording)

    lines = replay_lines(session_id, capsys)

    fields = summary(lines[0])
    assert int(fields["count"]) > 0
    assert fields["rmssd"] == "-"
    assert fields["sdnn"] == "-"
    assert stored_rows(store_url, "hrv_readings", session_id, HRV_COLUMNS) == []


def test_windows_too_short_to_measure_are_never_counted_under_the_floor() -> None:
    unmeasured = [
        WindowCheck(t_ms=CHECK_SESSION_MS - index * CHECK_STEP_MS, snr_db=-math.inf)
        for index in range(MOST_UNMEASURED)
    ]
    result = checked_result(unmeasured)

    weak = replay.is_too_weak(replay.newest_checks(result))
    notice = replay.weak_notice(result, weak_minute_summary(0))

    assert not weak
    assert notice is None


def test_the_notice_names_unmeasured_windows_apart_from_those_under_the_floor() -> None:
    checks = [
        WindowCheck(
            t_ms=CHECK_SESSION_MS - index * CHECK_STEP_MS,
            snr_db=WEAK_DB if index < MEASURED_UNDER else -math.inf,
        )
        for index in range(MEASURED_UNDER + SOME_UNMEASURED)
    ]

    notice = replay.weak_notice(checked_result(checks), weak_minute_summary(0))

    assert notice is not None
    assert UNMEASURED_WORDING in notice


def face_loss_recording() -> Recording:
    recording, _ = beat_recording(FACE_LOSS_BPM, SEED, FACE_LOSS_SESSION_S)
    seconds = seconds_of(recording)
    lost = np.mod(seconds, FACE_LOSS_EVERY_S) >= FACE_LOSS_EVERY_S - FACE_LOSS_S
    return Recording(recording.timestamps_ms[~lost], recording.regions[~lost])


def test_a_clean_face_lost_every_fourteen_seconds_prints_no_weak_signal_notice(
    store_url: str, capsys: pytest.CaptureFixture[str]
) -> None:
    session_id = stored_recording(store_url, face_loss_recording())

    lines = replay_lines(session_id, capsys)

    assert lines == [expected_summary_line(session_id)]


def test_newest_checks_keep_exactly_the_newest_minute_ends_included() -> None:
    newest_ms = CHECK_SESSION_MS
    oldest_ms = newest_ms - SUMMARY_SPAN_MS
    times = [oldest_ms - 1.0, oldest_ms, newest_ms - 1.0, newest_ms, newest_ms + 1.0]
    checks = [WindowCheck(t_ms=t_ms, snr_db=STRONG_DB) for t_ms in times]

    kept = replay.newest_checks(checked_result(checks))

    assert [check.t_ms for check in kept] == [oldest_ms, newest_ms - 1.0, newest_ms]
