import re
from collections import defaultdict

import numpy as np
import pytest
from numpy.typing import NDArray

from pulse_frame.signal.beats import Interval
from pulse_frame.signal.hrv import HrvTracker, WindowCheck
from pulse_frame.signal.tracker import UPDATE_INTERVAL_MS
from pulse_frame.store.recording import FrameSample, HrvRow, frame_samples
from pulse_frame.tools import replay
from pulse_frame.tools.sessions import SANDBOX_UNSUPPORTED_ACTION
from tests.database import WALL_NS, insert_recording, rows_under, stored_rows
from tests.frames import SEED, TRUE_BPM
from tests.platform.support import after_sandbox_notice
from tests.signal.beat_synthetic import (
    beat_recording,
    beats_inside,
    rmssd,
    rounded_blood_volume,
    systolic_midpoints,
)
from tests.signal.hrv_tracking import seconds_of
from tests.signal.synthetic import Recording
from tests.tools.replay_support import (
    COUNTED_SUMMARY_LINE,
    FLAG_CODES,
    HRV_COLUMNS,
    NO_READING_CODE,
    NS_PER_MS,
    NS_PER_S,
    SUMMARY_LINE,
    anchor_ns,
    beside_holes,
    interval_rows,
    notice_code,
    region_colours,
    sample_rows,
    still,
)

WARM_UP_S = 100.0
COUNTED_S = 80.0
NOISY_WARM_UP_SD = 0.1
WEAK_WARM_UP_SD = 0.2
WARM_UP_MOTION_FROM_S = 20.0
WARM_UP_MOTION_TO_S = 30.0
LABEL_WARM_UP_S = 60.0
LABEL_COUNTED = [(180.0, "3", "minutes"), (120.0, "2", "minutes")]
THREE_MINUTES = 3
DEFAULT_COUNTED_S = 90.0
LABEL_LEAD_S = 10.0
LABEL_SPANS = [
    pytest.param(400, "0", "seconds", id="under_half_a_second_reads_zero_seconds"),
    pytest.param(45_400, "45", "seconds", id="under_a_minute_in_seconds"),
    pytest.param(44_500, "45", "seconds", id="seconds_round_half_up"),
    pytest.param(59_600, "1", "minute", id="whole_seconds_reach_a_minute"),
    pytest.param(60_000, "1", "minute", id="one_minute_singular"),
    pytest.param(60_500, "61", "seconds", id="past_a_whole_minute_in_seconds"),
    pytest.param(89_400, "89", "seconds", id="just_under_ninety_rounds_down"),
    pytest.param(89_970, "90", "seconds", id="a_frame_short_of_ninety_seconds"),
    pytest.param(90_000, "90", "seconds", id="the_default_counted_part"),
    pytest.param(120_000, "2", "minutes", id="two_whole_minutes"),
    pytest.param(149_999, "150", "seconds", id="two_and_a_half_minutes_in_seconds"),
    pytest.param(179_500, "3", "minutes", id="whole_seconds_reach_three_minutes"),
    pytest.param(330_000, "5", "minutes", id="over_the_hrv_window"),
]
SHORT_WARM_UP_S = 60.0
SHORT_COUNTED_S = 50.0
WEAK_COUNTED_SD = 1.0
WEAK_CODE = "SIGNAL_TOO_WEAK"
WINDOW_COUNTS = re.compile(r"(\d+) of (\d+) analysis windows")
SUMMARY_SPAN_MS = 60_000.0
SUMMARY_MIN_ACCEPTED_MS = 45_000.0
MIN_MINUTE_INTERVALS = 2
PRINTED_MS = 0.1
INTERRUPTED_WARM_UP_S = 120.0
INTERRUPTED_AFTER_S = 20.0
OLD_SESSION_S = 90.0
OLD_MOTION_FROM_S = 45.0
OLD_MOTION_TO_S = 46.0
TRUTH_MARGIN_MS = 3_000.0
HRV_TOLERANCE_MS = 3.0
SHARE_TOLERANCE_PERCENT = 0.5
MIN_SHARE_DROP_PERCENT = 5.0
BOUNDARY_CLEARANCE_MS = 1.0
WINDOW_SLACK_MS = 1.0
OK_CODE = 0
EDGE_CODE = 4
NO_COUNTED_CODE = "NO_COUNTED_SAMPLES"
NO_COUNTED_CAUSES = (
    "The capture stopped before the warm-up ended, or saw no usable face after it."
)
NO_COUNTED_ACTION_WORDS = "keep your face in view"
COUNTED_FIELDS = (
    "bpm",
    "count",
    "newest_sdnn",
    "amount",
    "unit",
    "rmssd",
    "counted_sdnn",
    "sdnn_minutes",
    "unset_sdnn",
    "accepted",
)
TODAYS_FIELDS = ("bpm", "count", "rmssd", "sdnn", "accepted")


class WarmUpSession:
    def __init__(
        self, noise_sd: float, warm_up_s: float, counted_s: float, motion: bool
    ) -> None:
        recording, beats = beat_recording(TRUE_BPM, SEED, warm_up_s + counted_s)
        seconds = seconds_of(recording)
        in_warm_up = seconds < warm_up_s
        regions = recording.regions.copy()
        rng = np.random.default_rng(SEED + 1)
        regions[in_warm_up] += rng.normal(0.0, noise_sd, regions[in_warm_up].shape)
        self.recording = Recording(recording.timestamps_ms, regions)
        self.beats = beats
        self.moving = (
            (seconds >= WARM_UP_MOTION_FROM_S) & (seconds < WARM_UP_MOTION_TO_S)
            if motion
            else np.zeros(seconds.size, dtype=np.bool_)
        )
        self.anchor_ns = anchor_ns(self.recording)
        self.counted_ns = self.anchor_ns + round(warm_up_s * NS_PER_S)
        self.counted_ms = self.counted_ns // NS_PER_MS

    def store(self, url: str, counted: bool = True) -> int:
        return insert_recording(
            url,
            WALL_NS,
            self.anchor_ns,
            sample_rows(self.recording, self.moving),
            self.counted_ns if counted else None,
        )

    def counted_truth_rmssd(self) -> float:
        midpoints = systolic_midpoints(self.beats, rounded_blood_volume)
        last_ms = float(self.recording.timestamps_ms[-1])
        inside = beats_inside(
            midpoints, self.counted_ms + TRUTH_MARGIN_MS, last_ms - TRUTH_MARGIN_MS
        )
        return rmssd(np.diff(inside))


def replay_output(
    session_id: int, capsys: pytest.CaptureFixture[str]
) -> tuple[list[str], str]:
    assert replay.main([str(session_id)]) == 0
    output = capsys.readouterr()
    return output.out.splitlines(), after_sandbox_notice(
        output.err, action=SANDBOX_UNSUPPORTED_ACTION
    )


def summary_fields(line: str, pattern: str, fields: tuple[str, ...]) -> dict[str, str]:
    found = re.fullmatch(pattern, line)
    assert found is not None, "the summary line does not have the expected wording"
    return {name: found[name] or "" for name in fields}


def printed(
    session_id: int,
    capsys: pytest.CaptureFixture[str],
    pattern: str,
    fields: tuple[str, ...],
    notice_codes: tuple[str, ...] = (),
) -> dict[str, str]:
    lines, err = replay_output(session_id, capsys)
    assert [notice_code(line) for line in err.splitlines()] == list(notice_codes)
    assert len(lines) == 1, f"replay printed {len(lines)} lines"
    return summary_fields(lines[0], pattern, fields)


def counted_summary(
    session_id: int, capsys: pytest.CaptureFixture[str]
) -> dict[str, str]:
    return printed(session_id, capsys, COUNTED_SUMMARY_LINE, COUNTED_FIELDS)


def printed_sdnn(fields: dict[str, str]) -> str:
    return fields["newest_sdnn"] or fields["counted_sdnn"] or fields["unset_sdnn"]


def todays_summary(
    session_id: int,
    capsys: pytest.CaptureFixture[str],
    notice_codes: tuple[str, ...] = (),
) -> dict[str, str]:
    return printed(session_id, capsys, SUMMARY_LINE, TODAYS_FIELDS, notice_codes)


def row_start_ms(row: tuple[object, ...]) -> float:
    return float(str(row[0])) - float(str(row[1]))


def share_without_edges(rows: list[tuple[object, ...]]) -> float:
    flags = [row[2] for row in rows]
    return 100.0 * flags.count(OK_CODE) / (len(flags) - flags.count(EDGE_CODE))


def mean_minute_sdnn(
    rows: list[tuple[object, ...]], newest_ms: float
) -> tuple[float, int]:
    minutes: defaultdict[int, list[float]] = defaultdict(list)
    for t_ms, interval_ms, flag in rows:
        if flag == OK_CODE:
            minute = int((newest_ms - float(str(t_ms))) // SUMMARY_SPAN_MS)
            minutes[minute].append(float(str(interval_ms)))
    sdnns = [
        float(np.std(ibis, ddof=1))
        for ibis in minutes.values()
        if len(ibis) >= MIN_MINUTE_INTERVALS and sum(ibis) >= SUMMARY_MIN_ACCEPTED_MS
    ]
    return float(np.mean(sdnns)), len(sdnns)


def todays_replay(samples: list[FrameSample]) -> replay.ReplayResult:
    tracker = HrvTracker()
    settled: dict[float, Interval] = {}
    readings: list[HrvRow] = []
    next_update_ms: float | None = None
    for sample, low_quality in zip(samples, beside_holes(samples), strict=True):
        tracker.add(
            sample.t_ms,
            region_colours(sample),
            moving=sample.moving,
            low_quality=bool(low_quality),
        )
        if next_update_ms is None:
            next_update_ms = sample.t_ms + UPDATE_INTERVAL_MS
        elif sample.t_ms >= next_update_ms:
            next_update_ms = sample.t_ms + UPDATE_INTERVAL_MS
            for interval in tracker.settled_intervals():
                settled[interval.start_ms] = interval
            reading = tracker.reading()
            if (
                reading.rmssd_ms is not None
                and reading.sdnn_ms is not None
                and reading.window_ms is not None
                and reading.accepted_count is not None
            ):
                readings.append(
                    HrvRow(
                        t_ms=sample.t_ms,
                        rmssd_ms=reading.rmssd_ms,
                        sdnn_ms=reading.sdnn_ms,
                        window_ms=reading.window_ms,
                        accepted_count=reading.accepted_count,
                    )
                )
    for interval in tracker.intervals():
        settled[interval.start_ms] = interval
    return replay.ReplayResult(
        intervals=[settled[start] for start in sorted(settled)],
        readings=readings,
        newest_ms=samples[-1].t_ms,
        window_checks=tracker.window_checks(),
    )


def todays_rows(result: replay.ReplayResult) -> dict[str, list[tuple[object, ...]]]:
    beats = sorted(
        {round(edge) for i in result.intervals for edge in (i.start_ms, i.end_ms)}
    )
    return {
        "beats": [(beat,) for beat in beats],
        "intervals": [
            (round(i.end_ms), i.ibi_ms, FLAG_CODES[i.flag]) for i in result.intervals
        ],
        "hrv_readings": [
            (r.t_ms, r.rmssd_ms, r.sdnn_ms, r.window_ms, r.accepted_count)
            for r in result.readings
        ],
    }


def replayed_rows(url: str, session_id: int) -> dict[str, list[tuple[object, ...]]]:
    return {
        "beats": stored_rows(url, "beats", session_id, ["t_ms"]),
        "intervals": interval_rows(url, session_id),
        "hrv_readings": stored_rows(url, "hrv_readings", session_id, HRV_COLUMNS),
    }


def window_counts(checks: list[WindowCheck]) -> tuple[int, int]:
    under = sum(1 for check in checks if check.measured and check.under_floor)
    return under, len(checks)


@pytest.fixture(scope="module")
def noisy_warm_up() -> WarmUpSession:
    return WarmUpSession(NOISY_WARM_UP_SD, WARM_UP_S, COUNTED_S, motion=True)


@pytest.fixture(scope="module")
def weak_warm_up() -> WarmUpSession:
    return WarmUpSession(WEAK_WARM_UP_SD, WARM_UP_S, COUNTED_S, motion=True)


def test_the_summary_rmssd_comes_from_the_counted_part_not_the_noisy_warm_up(
    store_url: str,
    capsys: pytest.CaptureFixture[str],
    noisy_warm_up: WarmUpSession,
) -> None:
    whole_id = noisy_warm_up.store(store_url, counted=False)
    counted_id = noisy_warm_up.store(store_url)
    truth = noisy_warm_up.counted_truth_rmssd()
    whole = todays_summary(whole_id, capsys)
    assert whole["rmssd"] != "-", "the whole session prints no RMSSD to compare"
    assert abs(float(whole["rmssd"]) - truth) > HRV_TOLERANCE_MS, (
        "the noisy warm-up does not move the RMSSD, so it cannot show the skip"
    )

    counted = counted_summary(counted_id, capsys)

    assert counted["rmssd"] != "-"
    assert float(counted["rmssd"]) == pytest.approx(truth, abs=HRV_TOLERANCE_MS)


def test_a_weak_warm_up_never_holds_the_counted_part_under_the_reading_floor(
    store_url: str,
    capsys: pytest.CaptureFixture[str],
    weak_warm_up: WarmUpSession,
) -> None:
    whole_id = weak_warm_up.store(store_url, counted=False)
    counted_id = weak_warm_up.store(store_url)
    whole = todays_summary(whole_id, capsys, (NO_READING_CODE,))
    assert whole["rmssd"] == "-", "the weak warm-up does not reach the reading floor"
    assert rows_under(store_url, whole_id)["hrv_readings"] == 0

    counted = counted_summary(counted_id, capsys)

    assert counted["rmssd"] != "-"
    assert printed_sdnn(counted) != "-"
    assert float(counted["rmssd"]) == pytest.approx(
        weak_warm_up.counted_truth_rmssd(), abs=HRV_TOLERANCE_MS
    )
    assert rows_under(store_url, counted_id)["hrv_readings"] > 0


def test_the_accepted_share_covers_the_counted_part_only(
    store_url: str,
    capsys: pytest.CaptureFixture[str],
    weak_warm_up: WarmUpSession,
) -> None:
    whole_id = weak_warm_up.store(store_url, counted=False)
    counted_id = weak_warm_up.store(store_url)
    whole = float(todays_summary(whole_id, capsys, (NO_READING_CODE,))["accepted"])
    counted_only = [
        row
        for row in interval_rows(store_url, whole_id)
        if row_start_ms(row) >= weak_warm_up.counted_ms
    ]
    assert share_without_edges(counted_only) - whole > MIN_SHARE_DROP_PERCENT, (
        "the warm-up rejects too few intervals to show the skip"
    )

    counted = float(counted_summary(counted_id, capsys)["accepted"])

    assert counted == pytest.approx(
        share_without_edges(counted_only), abs=SHARE_TOLERANCE_PERCENT
    )


def test_stored_intervals_and_beats_are_the_counted_part_of_one_tracker_run(
    store_url: str,
    capsys: pytest.CaptureFixture[str],
    weak_warm_up: WarmUpSession,
) -> None:
    whole_id = weak_warm_up.store(store_url, counted=False)
    counted_id = weak_warm_up.store(store_url)
    assert replay.main([str(whole_id)]) == 0
    whole_rows = interval_rows(store_url, whole_id)
    assert any(row_start_ms(row) < weak_warm_up.counted_ms for row in whole_rows)
    assert all(
        abs(row_start_ms(row) - weak_warm_up.counted_ms) > BOUNDARY_CLEARANCE_MS
        for row in whole_rows
    )

    assert replay.main([str(counted_id)]) == 0

    capsys.readouterr()
    assert interval_rows(store_url, counted_id) == [
        row for row in whole_rows if row_start_ms(row) >= weak_warm_up.counted_ms
    ]
    beats = [
        int(str(row[0]))
        for row in stored_rows(store_url, "beats", counted_id, ["t_ms"])
    ]
    whole_beats = {
        int(str(row[0])) for row in stored_rows(store_url, "beats", whole_id, ["t_ms"])
    }
    assert beats, "the counted part stored no beat"
    assert min(beats) >= weak_warm_up.counted_ms
    assert set(beats) <= whole_beats


def test_stored_hrv_readings_have_windows_inside_the_counted_part(
    store_url: str,
    capsys: pytest.CaptureFixture[str],
    noisy_warm_up: WarmUpSession,
) -> None:
    whole_id = noisy_warm_up.store(store_url, counted=False)
    counted_id = noisy_warm_up.store(store_url)
    counted_ms = noisy_warm_up.counted_ms
    assert replay.main([str(whole_id)]) == 0
    whole = stored_rows(store_url, "hrv_readings", whole_id, HRV_COLUMNS)
    assert any(
        float(str(window_ms)) > float(str(t_ms)) - counted_ms
        for t_ms, _, _, window_ms, _ in whole
    ), "no whole-session reading reaches into the warm-up"

    assert replay.main([str(counted_id)]) == 0

    capsys.readouterr()
    readings = stored_rows(store_url, "hrv_readings", counted_id, HRV_COLUMNS)
    assert readings, "the counted part stored no HRV reading"
    for t_ms, _, _, window_ms, _ in readings:
        assert float(str(t_ms)) >= counted_ms
        assert float(str(window_ms)) <= float(str(t_ms)) - counted_ms + WINDOW_SLACK_MS
    _, newest_rmssd, _, _, _ = readings[-1]
    assert float(str(newest_rmssd)) == pytest.approx(
        noisy_warm_up.counted_truth_rmssd(), abs=HRV_TOLERANCE_MS
    )


def strong_warm_up_then_weak_counted_part() -> tuple[Recording, int]:
    recording, _ = beat_recording(TRUE_BPM, SEED, SHORT_WARM_UP_S + SHORT_COUNTED_S)
    seconds = seconds_of(recording)
    weak = seconds >= SHORT_WARM_UP_S
    regions = recording.regions.copy()
    rng = np.random.default_rng(SEED + 1)
    regions[weak] += rng.normal(0.0, WEAK_COUNTED_SD, regions[weak].shape)
    weakened = Recording(recording.timestamps_ms, regions)
    return weakened, anchor_ns(weakened) + round(SHORT_WARM_UP_S * NS_PER_S)


def test_the_weak_signal_notice_counts_only_the_windows_of_a_short_counted_part(
    store_url: str, capsys: pytest.CaptureFixture[str]
) -> None:
    recording, counted_ns = strong_warm_up_then_weak_counted_part()
    rows = sample_rows(recording, still(recording))
    anchor = anchor_ns(recording)
    whole_id = insert_recording(store_url, WALL_NS, anchor, rows)
    counted_id = insert_recording(store_url, WALL_NS, anchor, rows, counted_ns)
    counted_ms = counted_ns // NS_PER_MS
    before = todays_replay(frame_samples(whole_id))
    newest_minute = [
        check
        for check in before.window_checks
        if before.newest_ms - SUMMARY_SPAN_MS <= check.t_ms <= before.newest_ms
    ]
    counted_windows = window_counts(
        [check for check in newest_minute if check.t_ms >= counted_ms]
    )
    assert window_counts(newest_minute)[1] != counted_windows[1]
    whole_lines, whole_err = replay_output(whole_id, capsys)
    assert len(whole_lines) == 1
    assert whole_err == "", "the whole session already gives a notice"

    lines, err = replay_output(counted_id, capsys)

    assert len(lines) == 1
    fields = summary_fields(lines[0], COUNTED_SUMMARY_LINE, COUNTED_FIELDS)
    assert (fields["amount"], fields["unit"]) == (
        str(int((before.newest_ms - counted_ms) / 1000.0 + 0.5)),
        "seconds",
    )
    assert fields["count"] == "0"
    assert fields["unset_sdnn"] == "-"
    notices = err.splitlines()
    assert len(notices) == 1
    assert notices[0].startswith(f"{WEAK_CODE}: ")
    found = WINDOW_COUNTS.search(notices[0])
    assert found is not None, "the notice gives no window counts"
    assert (int(found[1]), int(found[2])) == counted_windows


def old_session_recording() -> tuple[Recording, NDArray[np.bool_]]:
    recording, _ = beat_recording(TRUE_BPM, SEED, OLD_SESSION_S)
    seconds = seconds_of(recording)
    moving = (seconds >= OLD_MOTION_FROM_S) & (seconds < OLD_MOTION_TO_S)
    return recording, moving


@pytest.mark.parametrize("counted", ["column_default", "zero", "anchor"])
def test_a_session_with_no_warm_up_replays_exactly_as_before(
    store_url: str, capsys: pytest.CaptureFixture[str], counted: str
) -> None:
    recording, moving = old_session_recording()
    anchor = anchor_ns(recording)
    counted_ns = {"column_default": None, "zero": 0, "anchor": anchor}[counted]
    session_id = insert_recording(
        store_url, WALL_NS, anchor, sample_rows(recording, moving), counted_ns
    )
    before = todays_replay(frame_samples(session_id))
    expected_line = replay.summary_line(session_id, replay.summarise(before))
    assert re.fullmatch(SUMMARY_LINE, expected_line)

    assert replay.main([str(session_id)]) == 0

    output = capsys.readouterr()
    assert output.out.splitlines() == [expected_line]
    assert replayed_rows(store_url, session_id) == todays_rows(before)


def test_ctrl_c_during_the_warm_up_then_replay_gives_the_no_counted_samples_notice(
    store_url: str, capsys: pytest.CaptureFixture[str]
) -> None:
    recording, _ = beat_recording(TRUE_BPM, SEED, INTERRUPTED_AFTER_S)
    anchor = anchor_ns(recording)
    rows = sample_rows(recording, still(recording))
    session_id = insert_recording(
        store_url,
        WALL_NS,
        anchor,
        rows,
        anchor + round(INTERRUPTED_WARM_UP_S * NS_PER_S),
    )

    assert replay.main([str(session_id)]) == 1

    output = capsys.readouterr()
    line = after_sandbox_notice(output.err, action=SANDBOX_UNSUPPORTED_ACTION)
    assert line.startswith(f"{NO_COUNTED_CODE}: ")
    assert len(line.splitlines()) == 1
    assert f"Session {session_id}" in line
    assert NO_COUNTED_CAUSES in line
    assert NO_COUNTED_ACTION_WORDS in line.lower()
    assert f"pulse_frame.tools.sessions delete {session_id}" in line
    assert "pulse_frame.tools.capture" in line
    assert "Traceback" not in output.err
    assert output.out == ""
    assert rows_under(store_url, session_id) == {
        "sessions": 1,
        "frame_samples": len(rows),
        "beats": 0,
        "intervals": 0,
        "hrv_readings": 0,
    }


@pytest.mark.parametrize(
    ("counted_s", "amount", "unit"),
    LABEL_COUNTED,
    ids=["three_minutes", "two_minutes"],
)
def test_a_whole_minute_counted_part_names_its_minutes_and_its_sdnn_minute_count(
    store_url: str,
    capsys: pytest.CaptureFixture[str],
    counted_s: float,
    amount: str,
    unit: str,
) -> None:
    session = WarmUpSession(WEAK_WARM_UP_SD, LABEL_WARM_UP_S, counted_s, motion=False)
    session_id = session.store(store_url)

    fields = counted_summary(session_id, capsys)

    assert (fields["amount"], fields["unit"]) == (amount, unit)
    assert fields["bpm"] != "-"
    assert fields["rmssd"] != "-"
    assert fields["newest_sdnn"] == ""
    assert fields["counted_sdnn"] != ""
    assert fields["sdnn_minutes"] == amount
    assert float(fields["accepted"]) == pytest.approx(
        share_without_edges(interval_rows(store_url, session_id)),
        abs=SHARE_TOLERANCE_PERCENT,
    )


def test_the_three_minute_counted_sdnn_is_the_mean_over_all_three_minutes(
    store_url: str, capsys: pytest.CaptureFixture[str]
) -> None:
    session = WarmUpSession(WEAK_WARM_UP_SD, LABEL_WARM_UP_S, 180.0, motion=False)
    session_id = session.store(store_url)
    newest_ms = float(round(float(session.recording.timestamps_ms[-1])))

    fields = counted_summary(session_id, capsys)

    expected, minutes = mean_minute_sdnn(
        interval_rows(store_url, session_id), newest_ms
    )
    assert minutes == THREE_MINUTES, f"only {minutes} minutes hold enough beats"
    assert (fields["amount"], fields["unit"]) == ("3", "minutes")
    assert fields["newest_sdnn"] == ""
    assert fields["sdnn_minutes"] == str(THREE_MINUTES)
    assert float(fields["counted_sdnn"]) == pytest.approx(expected, abs=PRINTED_MS)


def test_a_ninety_second_counted_part_prints_its_one_minute_sdnn_in_the_newest_minute(
    store_url: str, capsys: pytest.CaptureFixture[str]
) -> None:
    session = WarmUpSession(
        WEAK_WARM_UP_SD, LABEL_WARM_UP_S, DEFAULT_COUNTED_S, motion=False
    )
    session_id = session.store(store_url)
    newest_ms = float(round(float(session.recording.timestamps_ms[-1])))

    fields = counted_summary(session_id, capsys)

    expected, minutes = mean_minute_sdnn(
        interval_rows(store_url, session_id), newest_ms
    )
    assert minutes == 1, f"{minutes} minutes hold enough beats, not only the newest"
    assert (fields["amount"], fields["unit"]) == ("90", "seconds")
    assert fields["bpm"] != "-"
    assert fields["rmssd"] != "-"
    assert (fields["counted_sdnn"], fields["sdnn_minutes"]) == ("", "")
    assert fields["unset_sdnn"] == ""
    assert float(fields["newest_sdnn"]) == pytest.approx(expected, abs=PRINTED_MS)


@pytest.mark.parametrize(("span_ms", "amount", "unit"), LABEL_SPANS)
def test_the_counted_label_is_whole_seconds_unless_whole_minutes_capped_at_the_window(
    store_url: str,
    capsys: pytest.CaptureFixture[str],
    span_ms: int,
    amount: str,
    unit: str,
) -> None:
    recording, _ = beat_recording(TRUE_BPM, SEED, span_ms / 1000.0 + LABEL_LEAD_S)
    newest_ms = round(float(recording.timestamps_ms[-1]))
    session_id = insert_recording(
        store_url,
        WALL_NS,
        anchor_ns(recording),
        sample_rows(recording, still(recording)),
        (newest_ms - span_ms) * NS_PER_MS,
    )

    lines, _ = replay_output(session_id, capsys)

    fields = summary_fields(lines[0], COUNTED_SUMMARY_LINE, COUNTED_FIELDS)
    assert (fields["amount"], fields["unit"]) == (amount, unit)
