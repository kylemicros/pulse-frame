import logging
import math
from collections.abc import Collection, Generator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from typing import override

import numpy as np

from pulse_frame.signal.beats import Interval
from pulse_frame.signal.hrv import (
    HrvTracker,
    WindowCheck,
    alternates,
    is_stale,
    too_many_rejected,
    touching_runs,
)
from pulse_frame.signal.live import LiveHrv
from pulse_frame.signal.summary import NoReading
from pulse_frame.signal.tracker import RegionColours
from tests.signal.synthetic import Recording, region_colours
from tests.stream.wire import APP_LOGGER, Stream, app_records, assert_error

EVENT = "beat_signal"
CLOSE_EVENT = "beat_signal_close"
SECOND_MS = 1_000
GAP_OVER_MS = 100
MINUTE_MS = 60_000.0
HRV_WINDOW_MS = 300_000.0
NEED_ACCEPTED_MS = 45_000.0
HRV_NEED_ACCEPTED_MS = 60_000.0
FLOOR_DB = 0.0
CLEAR_DB = 3.0
SLACK = 0.051
REJECTED_SHARE_FIELDS = {
    f"rejected_share_{flag}": flag
    for flag in ("gap", "motion", "low_quality", "out_of_range", "off_median")
}
CLOSE_FIELDS = frozenset({"accepted_share", *REJECTED_SHARE_FIELDS})
CLOSE_VALUES = frozenset(range(0, 101, 10))
CHECK_MEASURES = (
    "snr_db",
    "snr_age_ms",
    "under_floor_share",
    "clear_share",
    "unmeasured_share",
    "median_snr_db",
)
SIGNAL_WHOLES = ("checks",)
FLAGS_01 = ("bpm_shown", "had_reading")
NO_READING_CODES = frozenset({"none", "SIGNAL_TOO_WEAK", "READING_FLOOR_NOT_CLEARED"})
GATES = frozenset({"none", "alternates", "too_many_rejected", "stale", "unchecked"})
HRV_GATES = frozenset(
    {
        "none",
        "unchecked",
        "stale",
        "too_many_rejected",
        "too_short",
        "no_successive",
        "alternates",
        "floor",
    }
)
WORDS = {"code": NO_READING_CODES, "gate": GATES, "hrv_gate": HRV_GATES}
SIGNAL_FIELDS = frozenset({*CHECK_MEASURES, *SIGNAL_WHOLES, *FLAGS_01, *WORDS})
FRAME_WHOLES = ("sample_frames", "moving_frames", "gaps_over_100ms")
FRAME_MEASURES = ("step_p50_ms", "step_p95_ms", "fps")
FRAME_FIELDS = frozenset({*FRAME_WHOLES, *FRAME_MEASURES})
ALLOWED_FIELDS = frozenset({"event", *SIGNAL_FIELDS, *FRAME_FIELDS})
JITTER_MS = 4
CHANNELS = 9

type Expected = dict[str, float | str]


@dataclass(frozen=True)
class SignalSnapshot:
    intervals: tuple[Interval, ...]
    checks: tuple[WindowCheck, ...]
    newest_ms: float
    counted_ms: float | None
    no_reading: NoReading | None = None
    bpm_shown: bool = False
    had_reading: bool = False


@dataclass(frozen=True)
class Second:
    start: int
    frame: int
    steps: list[int]
    elapsed_ms: int

    @property
    def frames(self) -> range:
        return range(self.start + 1, self.frame + 1)


class PulsedLiveHrv(LiveHrv):
    def __init__(self, face: Recording, kept_ms: frozenset[int]) -> None:
        super().__init__()
        self._face = face
        self._kept_ms = kept_ms
        self._shadow = HrvTracker()
        self.snapshots: dict[float, SignalSnapshot] = {}

    @override
    def add(
        self, timestamp_ms: float, regions: RegionColours | None, moving: bool = False
    ) -> None:
        assert regions is None, "The blank frame was read as a face."
        pulsed = colours_at(self._face, timestamp_ms)
        super().add(timestamp_ms, pulsed, moving=moving)
        self._shadow.add(timestamp_ms, pulsed, moving=moving)
        if timestamp_ms in self._kept_ms:
            self.snapshots[timestamp_ms] = SignalSnapshot(
                intervals=tuple(self.intervals()),
                checks=tuple(self._shadow.window_checks()),
                newest_ms=timestamp_ms,
                counted_ms=self.counted_from_ms,
                no_reading=self.no_reading(),
                bpm_shown=self.summary().bpm is not None,
                had_reading=self.had_reading,
            )


class PulsedHrvFactory:
    def __init__(self, face: Recording, kept_ms: frozenset[int]) -> None:
        self._face = face
        self._kept_ms = kept_ms
        self.built: list[PulsedLiveHrv] = []

    def __call__(self) -> PulsedLiveHrv:
        live = PulsedLiveHrv(self._face, self._kept_ms)
        self.built.append(live)
        return live


def colours_at(face: Recording, timestamp_ms: float) -> RegionColours:
    flat = face.regions.reshape(-1, CHANNELS)
    values = [
        np.interp(timestamp_ms, face.timestamps_ms, flat[:, channel])
        for channel in range(CHANNELS)
    ]
    return region_colours(np.array(values).reshape(3, 3))


def jittered_steps(rng: np.random.Generator, seconds: float, mean_ms: int) -> list[int]:
    steps: list[int] = []
    while sum(steps) < seconds * SECOND_MS:
        steps.append(mean_ms + int(rng.integers(-JITTER_MS, JITTER_MS + 1)))
    return steps


def capture_times(start_ms: int, steps: Sequence[int]) -> list[int]:
    return [start_ms, *(start_ms + int(t) for t in np.cumsum(steps))]


def seconds_of(times: Sequence[int]) -> list[Second]:
    found: list[Second] = []
    last = 0
    for frame in range(1, len(times)):
        if times[frame] - times[last] >= SECOND_MS:
            steps = [times[k] - times[k - 1] for k in range(last + 1, frame + 1)]
            found.append(Second(last, frame, steps, times[frame] - times[last]))
            last = frame
    return found


def received_before(frame: int, failing: Collection[int]) -> int:
    while frame in failing:
        frame -= 1
    return frame


def share(part: int, whole: int) -> float:
    return math.nan if whole == 0 else 100.0 * part / whole


def counted_of(snapshot: SignalSnapshot) -> list[Interval]:
    counted_ms = snapshot.counted_ms
    if counted_ms is None:
        return []
    return [i for i in snapshot.intervals if i.start_ms >= counted_ms]


def minute_intervals(snapshot: SignalSnapshot) -> list[Interval]:
    newest_ms = snapshot.newest_ms
    return [
        interval
        for interval in counted_of(snapshot)
        if newest_ms - MINUTE_MS <= round(interval.end_ms) <= newest_ms
    ]


def counted_checks_of(snapshot: SignalSnapshot) -> list[WindowCheck]:
    counted_ms = snapshot.counted_ms
    if counted_ms is None:
        return []
    return [check for check in snapshot.checks if check.t_ms >= counted_ms]


def minute_checks_of(snapshot: SignalSnapshot) -> list[WindowCheck]:
    newest_ms = snapshot.newest_ms
    return [
        check
        for check in counted_checks_of(snapshot)
        if newest_ms - MINUTE_MS <= check.t_ms <= newest_ms
    ]


def expected_gate(minute: list[Interval], newest_ms: float) -> str:
    accepted = [interval for interval in minute if interval.accepted]
    if sum(interval.ibi_ms for interval in accepted) < NEED_ACCEPTED_MS:
        return "unchecked"
    if alternates(minute):
        return "alternates"
    if too_many_rejected(minute, len(accepted)):
        return "too_many_rejected"
    if is_stale(minute, newest_ms):
        return "stale"
    return "none"


def floor_clears(checks: Sequence[WindowCheck]) -> bool:
    return bool(checks) and float(np.median([c.snr_db for c in checks])) >= CLEAR_DB


def expected_hrv_gate(snapshot: SignalSnapshot) -> str:
    counted = counted_of(snapshot)
    newest_ms = snapshot.newest_ms
    if not counted:
        return "unchecked"
    window = [i for i in counted if i.start_ms >= newest_ms - HRV_WINDOW_MS]
    accepted = [i.ibi_ms for i in window if i.accepted]
    if is_stale(window, newest_ms):
        return "stale"
    if too_many_rejected(window, len(accepted)):
        return "too_many_rejected"
    if len(accepted) < 2 or sum(accepted) < HRV_NEED_ACCEPTED_MS:
        return "too_short"
    if touching_runs(window, 2).size == 0:
        return "no_successive"
    if alternates(window):
        return "alternates"
    first_ms = min(i.start_ms for i in window)
    between = [c for c in snapshot.checks if first_ms <= c.t_ms <= newest_ms]
    if not floor_clears(between):
        return "floor"
    return "none"


def expected_signal(snapshot: SignalSnapshot) -> Expected:
    minute = minute_checks_of(snapshot)
    counted = [check.snr_db for check in counted_checks_of(snapshot)]
    newest = snapshot.checks[-1] if snapshot.checks else None
    no_reading = snapshot.no_reading
    return {
        "snr_db": math.nan if newest is None else newest.snr_db,
        "snr_age_ms": math.nan if newest is None else snapshot.newest_ms - newest.t_ms,
        "checks": float(len(minute)),
        "under_floor_share": share(
            sum(math.isfinite(c.snr_db) and c.snr_db < FLOOR_DB for c in minute),
            len(minute),
        ),
        "clear_share": share(sum(snr >= CLEAR_DB for snr in counted), len(counted)),
        "unmeasured_share": share(
            sum(math.isnan(snr) or snr == -math.inf for snr in counted), len(counted)
        ),
        "median_snr_db": float(np.median(counted)) if counted else math.nan,
        "code": "none" if no_reading is None else no_reading.code,
        "bpm_shown": float(snapshot.bpm_shown),
        "had_reading": float(snapshot.had_reading),
        "gate": expected_gate(minute_intervals(snapshot), snapshot.newest_ms),
        "hrv_gate": expected_hrv_gate(snapshot),
    }


def tens(value: float) -> float:
    return value if math.isnan(value) else 10.0 * round(value / 10.0)


def expected_close(snapshot: SignalSnapshot) -> Expected | None:
    counted_ms = snapshot.counted_ms
    if counted_ms is None or snapshot.newest_ms - counted_ms < MINUTE_MS:
        return None
    counted = counted_of(snapshot)
    settled = [interval for interval in counted if interval.flag != "edge"]
    return {
        "accepted_share": tens(share(sum(i.accepted for i in settled), len(settled))),
        **{
            name: tens(share(sum(i.flag == flag for i in settled), len(settled)))
            for name, flag in REJECTED_SHARE_FIELDS.items()
        },
    }


def close_to(logged: float, expected: float) -> bool:
    if math.isnan(expected):
        return math.isnan(logged)
    if math.isinf(expected):
        return logged == expected
    return abs(logged - expected) <= SLACK


def mismatches(fields: dict[str, str], expected: Expected) -> list[str]:
    return [
        name
        for name, value in expected.items()
        if (
            fields[name] != value
            if isinstance(value, str)
            else not close_to(float(fields[name]), value)
        )
    ]


def beat_signal_records(records: list[logging.LogRecord]) -> list[logging.LogRecord]:
    return app_records(records, EVENT)


def close_records(records: list[logging.LogRecord]) -> list[logging.LogRecord]:
    return app_records(records, CLOSE_EVENT)


def line_fields(message: str, event: str = EVENT) -> dict[str, str]:
    tokens = message.split()
    assert tokens[:1] == [f"event={event}"], message
    pairs = [token.partition("=") for token in tokens]
    assert all(sep == "=" and key and value for key, sep, value in pairs), message
    keys = [key for key, _, _ in pairs]
    assert len(keys) == len(set(keys)), message
    return {key: value for key, _, value in pairs}


def whole_of(fields: dict[str, str], name: str) -> int:
    text = fields[name]
    assert text.isdigit(), f"{name}={text} is not a whole number"
    return int(text)


def measure_of(fields: dict[str, str], name: str) -> float:
    return float(fields[name])


def assert_allowed_values(fields: dict[str, str]) -> None:
    assert set(fields) == ALLOWED_FIELDS, sorted(set(fields) ^ ALLOWED_FIELDS)
    for name in (*SIGNAL_WHOLES, *FRAME_WHOLES):
        whole_of(fields, name)
    for name in FLAGS_01:
        assert fields[name] in {"0", "1"}, fields
    for name in (*CHECK_MEASURES, *FRAME_MEASURES):
        measure_of(fields, name)
    for name in FRAME_MEASURES:
        assert math.isfinite(measure_of(fields, name)), fields
    for name, words in WORDS.items():
        assert fields[name] in words, fields


def assert_close_values(fields: dict[str, str]) -> None:
    allowed = CLOSE_FIELDS | {"event"}
    assert set(fields) == allowed, sorted(set(fields) ^ allowed)
    for name in CLOSE_FIELDS:
        value = float(fields[name])
        assert math.isnan(value) or value in CLOSE_VALUES, fields


def send_counting_lines(
    stream: Stream,
    times: Sequence[int],
    jpegs: Sequence[bytes],
    records: list[logging.LogRecord],
    failing: Collection[int] = (),
) -> list[int]:
    counts: list[int] = []
    previous = times[0]
    for frame, (t_ms, jpeg) in enumerate(zip(times, jpegs, strict=True)):
        turn = stream.send_frame(t_ms, jpeg, (t_ms - previous) / SECOND_MS)
        if frame in failing:
            assert_error(turn, "DETECTION_FAILED")
        else:
            assert turn.reply["type"] == "frame", turn.texts
        counts.append(len(beat_signal_records(records)))
        previous = t_ms
    return counts


def assert_lines_on_their_frames(
    counts: Sequence[int], seconds: Sequence[Second]
) -> None:
    due = {second.frame for second in seconds}
    owed = 0
    for frame, seen in enumerate(counts):
        owed_before = owed
        owed += frame in due
        assert owed_before <= seen <= owed, (
            f"after frame {frame} there were {seen} lines; expected"
            f" {owed_before} to {owed}"
        )


@contextmanager
def caught_app_records() -> Generator[list[logging.LogRecord]]:
    records: list[logging.LogRecord] = []

    class Catcher(logging.Handler):
        @override
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    logger = logging.getLogger(APP_LOGGER)
    catcher = Catcher(logging.DEBUG)
    level = logger.level
    logger.setLevel(logging.DEBUG)
    logger.addHandler(catcher)
    try:
        yield records
    finally:
        logger.removeHandler(catcher)
        logger.setLevel(level)
