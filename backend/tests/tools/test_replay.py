import inspect
import os
import re
import subprocess
import sys
import typing
from pathlib import Path

import numpy as np
import psycopg
import pytest
from numpy.typing import NDArray
from psycopg import sql

from pulse_frame.signal.beats import Interval, IntervalFlag
from pulse_frame.signal.hrv import HrvTracker
from pulse_frame.signal.tracker import UPDATE_INTERVAL_MS
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
    cycle_at,
    late_wave_blood_volume,
    nearest_errors,
    physical_recording,
    rmssd,
    sdnn,
)
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
WIDE_FROM_S = 60.0
WIDE_TO_S = 66.0
FAR_OFF_IBI_MS = 600.0
SAMPLE_HOLE_MS = 100.0
SUMMARY_MIN_ACCEPTED_MS = 45_000.0
SWEEP_TOLERANCE_MS = {50.0: 5.0, 72.0: 3.0, 110.0: 3.0}
WAVE_S = 120.0
WAVE_FROM_S = 90.0
WAVE_RATES_BPM = [50.0, 72.0]
WAVE_SEEDS = [0, 1, 2]
DIASTOLIC_HEIGHT = 0.5
DIASTOLIC_AT = 0.45
LAST_SECOND_S = 1.0
STALE_MS = 10_000.0
STALE_TAIL_S = 12.0
MAX_REJECTED_SHARE = 0.2
MIN_FAR_OFF = 3
SLOW_START_BPM = 50.0
SLOW_UNTIL_S = 25.0
SESSION_APART_FACTOR = 10.0
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
FIELDS = {
    "bpm": r"\bbpm=(-|\d+(?:\.\d+)?)",
    "rmssd": r"\brmssd=(-|\d+(?:\.\d+)?)(?: ms)?",
    "sdnn": r"\bsdnn=(-|\d+(?:\.\d+)?)(?: ms)?",
    "count": r"\bcount=(-|\d+)",
    "accepted": r"\baccepted=(-|\d+(?:\.\d+)?)%?",
}
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
    found = {}
    for name, pattern in FIELDS.items():
        matches = re.findall(pattern, out)
        assert len(matches) == 1, f"`{name}=` appears {len(matches)} times"
        found[name] = matches[0]
    return found


def lines_with_other_numbers(out: str) -> int:
    stripped = out
    for pattern in [*FIELDS.values(), SESSION_TOKEN]:
        stripped = re.sub(pattern, "", stripped)
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
    ends = beats[1:]
    inside = (ends >= newest_ms - SUMMARY_SPAN_MS) & (ends <= newest_ms - EDGE_MS)
    return np.diff(beats)[inside]


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
def test_summary_gives_bpm_rmssd_and_sdnn_of_the_newest_minute_near_the_truth(
    store_url: str,
    capsys: pytest.CaptureFixture[str],
    bpm: float,
) -> None:
    recording, beats = beat_recording(bpm, SEED, DURATION_S)
    session_id = stored_recording(store_url, recording)
    truth = true_ibis_in_summary_span(recording, beats)

    assert replay.main([str(session_id)]) == 0

    output = capsys.readouterr()
    fields = summary(output.out)
    tolerance = SWEEP_TOLERANCE_MS[bpm]
    assert float(fields["bpm"]) == pytest.approx(
        60_000.0 / truth.mean(), abs=BPM_TOLERANCE
    )
    assert float(fields["rmssd"]) == pytest.approx(rmssd(truth), abs=tolerance)
    assert float(fields["sdnn"]) == pytest.approx(sdnn(truth), abs=tolerance)
    assert float(fields["accepted"]) >= MIN_ACCEPTED_PERCENT
    assert after_sandbox_notice(output.err, action=SANDBOX_UNSUPPORTED_ACTION) == ""


@pytest.mark.parametrize("bpm", WAVE_RATES_BPM)
@pytest.mark.parametrize("seed", WAVE_SEEDS)
def test_a_minute_failing_the_tracker_gates_prints_no_bpm_rmssd_or_sdnn(
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
    assert fields["bpm"] == "-"
    assert fields["rmssd"] == "-"
    assert fields["sdnn"] == "-"


def test_summary_rmssd_and_sdnn_come_from_the_newest_minute_not_the_whole_session(
    store_url: str, capsys: pytest.CaptureFixture[str]
) -> None:
    recording, beats = beat_recording(TRUE_BPM, SEED, DURATION_S)
    slow, _ = beat_recording(SLOW_START_BPM, SEED, DURATION_S)
    early = seconds_of(recording) < SLOW_UNTIL_S
    regions = recording.regions.copy()
    regions[early] = slow.regions[early]
    session_id = stored_recording(
        store_url, Recording(recording.timestamps_ms, regions)
    )
    truth = true_ibis_in_summary_span(recording, beats)

    assert replay.main([str(session_id)]) == 0

    fields = summary(capsys.readouterr().out)
    whole = [
        float(str(row[1]))
        for row in interval_rows(store_url, session_id)
        if row[2] == OK_CODE
    ]
    assert abs(sdnn(whole) - sdnn(truth)) > SESSION_APART_FACTOR * HRV_TOLERANCE_MS
    assert float(fields["rmssd"]) == pytest.approx(rmssd(truth), abs=HRV_TOLERANCE_MS)
    assert float(fields["sdnn"]) == pytest.approx(sdnn(truth), abs=HRV_TOLERANCE_MS)


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


def test_a_minute_over_the_rejected_share_prints_no_bpm_rmssd_or_sdnn(
    store_url: str, capsys: pytest.CaptureFixture[str]
) -> None:
    recording, _ = beat_recording(TRUE_BPM, SEED, DURATION_S)
    session_id = stored_fast_splice(store_url, recording, WIDE_FROM_S, WIDE_TO_S)

    assert replay.main([str(session_id)]) == 0

    fields = summary(capsys.readouterr().out)
    assert_floor_holds(store_url, session_id, recording)
    assert newest_accepted_gap_ms(store_url, session_id, recording) <= STALE_MS
    assert fields["bpm"] == "-"
    assert fields["rmssd"] == "-"
    assert fields["sdnn"] == "-"


def test_summary_bpm_ignores_rejected_intervals_however_far_off_they_are(
    store_url: str, capsys: pytest.CaptureFixture[str]
) -> None:
    recording, beats = beat_recording(TRUE_BPM, SEED, DURATION_S)
    session_id = stored_fast_splice(store_url, recording, FAST_FROM_S, FAST_TO_S)
    truth = true_ibis_in_summary_span(recording, beats)

    assert replay.main([str(session_id)]) == 0

    fields = summary(capsys.readouterr().out)
    far_off = [
        row
        for row in interval_rows(store_url, session_id)
        if row[2] != OK_CODE and float(str(row[1])) < FAR_OFF_IBI_MS
    ]
    assert len(far_off) >= MIN_FAR_OFF, (
        f"the spliced span gave {len(far_off)} far-off rejected intervals"
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


def test_replay_stores_beats_on_the_true_beats_and_intervals_between_them(
    store_url: str, clean_session: Session
) -> None:
    session_id, recording, beats = clean_session

    assert replay.main([str(session_id)]) == 0

    found = beat_times(store_url, session_id)
    truth = true_ibis_inside(recording, beats)
    assert found.size >= BEAT_SHARE * (truth.size + 1)
    assert float(np.median(np.abs(nearest_errors(beats, found)))) <= BEAT_ERROR_MS
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
    truth = true_ibis_inside(recording, beats)
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
    truth = true_ibis_in_summary_span(whole, beats)

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
