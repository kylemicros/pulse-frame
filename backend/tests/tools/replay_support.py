import math
import re
from collections.abc import Sequence

import numpy as np
from numpy.typing import NDArray

from pulse_frame.signal.hrv import READING_FLOOR_DB, WindowCheck
from pulse_frame.signal.tracker import RegionColours
from pulse_frame.store.recording import FrameSample
from tests.database import COLOUR_COLUMNS, Row, stored_rows
from tests.frames import SEED
from tests.signal.beat_synthetic import beat_recording
from tests.signal.hrv_tracking import seconds_of
from tests.signal.synthetic import Recording

ANCHOR_LEAD_MS = 250
NS_PER_MS = 1_000_000
NS_PER_S = 1_000_000_000
SAMPLE_HOLE_MS = 100.0
FACE_LOSS_BPM = 60.0
FACE_LOSS_S = 1.5
FLAG_CODES = {
    "ok": 0,
    "motion": 1,
    "gap": 2,
    "low_quality": 3,
    "edge": 4,
    "out_of_range": 5,
    "off_median": 6,
}
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
SDNN_VALUE = r"\d+\.\d"
COUNTED_SUMMARY_LINE = (
    rf"Session (?P<session>\d+) replayed,"
    rf" newest minute: bpm=(?P<bpm>{PRINTED_VALUE}) count=(?P<count>\d+)"
    rf"(?: sdnn=(?P<newest_sdnn>{SDNN_VALUE}) ms)?;"
    rf" counted (?P<amount>\d+) (?P<unit>minutes|minute|seconds):"
    rf" rmssd=(?P<rmssd>{PRINTED_VALUE})(?: ms)?"
    rf"(?(newest_sdnn)| sdnn=(?:(?P<counted_sdnn>{SDNN_VALUE}) ms"
    rf" over (?P<sdnn_minutes>\d+) (?:minutes|minute)|(?P<unset_sdnn>-)));"
    rf" counted part: accepted=(?P<accepted>{PRINTED_VALUE})%?"
)
NO_READING_CODE = "READING_FLOOR_NOT_CLEARED"
NO_READING_REF = f" Ref: {NO_READING_CODE}"
NO_READING_START = "No reading this time"
CAPTURE_COMMAND = "`uv run python -m pulse_frame.tools.capture`"
TRAILING_REF = re.compile(r" Ref: ([A-Z][A-Z_]*)$")
PERCENT = re.compile(r"(\d+)%")
NUMBER = re.compile(r"\d+(?:\.\d+)?")
JARGON = re.compile(
    r"\b(?:db|floor|windows\b|median|hrv|snr|region|analysis|exposure)", re.IGNORECASE
)
CODE_WORD = re.compile(r"\b\w*_\w*\b|\b[A-Z]{2,}\b")
LIGHT_WORD = re.compile(r"\blight\b", re.IGNORECASE)
LIGHT_ADVICE = "more even light"
STILL_ADVICE = "hold still"
NEVER_CLEAR = "your pulse never showed clearly during the run"
NEVER_WORD = "never"
UNDER_ONE_PERCENT = "under 1%"
LEFT_VIEW = "leaving the camera's view"
FACE_ADVICE = "keep your face in view"


def anchor_ns(recording: Recording) -> int:
    first_ms = round(float(recording.timestamps_ms[0]))
    return (first_ms - ANCHOR_LEAD_MS) * NS_PER_MS


def still(recording: Recording) -> NDArray[np.bool_]:
    return np.zeros(recording.timestamps_ms.size, dtype=np.bool_)


def region_colours(sample: FrameSample) -> RegionColours:
    return RegionColours(
        forehead=sample.forehead,
        left_cheek=sample.left_cheek,
        right_cheek=sample.right_cheek,
    )


def beside_holes(samples: Sequence[FrameSample]) -> NDArray[np.bool_]:
    times = np.array([sample.t_ms for sample in samples], dtype=np.float64)
    holes = np.diff(times) > SAMPLE_HOLE_MS
    low = np.zeros(times.size, dtype=np.bool_)
    low[:-1] |= holes
    low[1:] |= holes
    return low


def face_lost_recording(duration_s: float, every_s: float) -> Recording:
    recording, _ = beat_recording(FACE_LOSS_BPM, SEED, duration_s)
    seconds = seconds_of(recording)
    lost = np.mod(seconds, every_s) >= every_s - FACE_LOSS_S
    return Recording(recording.timestamps_ms[~lost], recording.regions[~lost])


def median_snr_db(checks: Sequence[WindowCheck]) -> float:
    return float(np.median([check.snr_db for check in checks]))


def share_at_or_above_floor(checks: Sequence[WindowCheck]) -> float:
    above = sum(1 for check in checks if check.snr_db >= READING_FLOOR_DB)
    return 100.0 * above / len(checks)


def half_up(percent: float) -> int:
    return math.floor(percent + 0.5)


def face_left_view(checks: Sequence[WindowCheck]) -> bool:
    unmeasured = sum(1 for c in checks if math.isnan(c.snr_db) or c.snr_db == -math.inf)
    measured_under = sum(
        1 for c in checks if math.isfinite(c.snr_db) and c.snr_db < READING_FLOOR_DB
    )
    return unmeasured > measured_under


def notice_code(line: str) -> str:
    found = TRAILING_REF.search(line)
    return found[1] if found else line.partition(": ")[0]


def no_reading_lines(lines: list[str]) -> list[str]:
    return [line for line in lines if notice_code(line) == NO_READING_CODE]


def plain_words(line: str) -> str:
    assert line.startswith(NO_READING_START), "the line does not open in plain words"
    assert line.endswith(NO_READING_REF), "the line does not end with its Ref"
    assert line.count("`") == 2, "the line holds other backticked text"
    assert CAPTURE_COMMAND in line, "the line does not give the capture command"
    return line.removesuffix(NO_READING_REF).replace(CAPTURE_COMMAND, "")


def printed_share(line: str) -> int:
    percents = PERCENT.findall(plain_words(line))
    assert len(percents) == 1, f"the line holds {len(percents)} percent figures"
    return int(percents[0])


def assert_faint_pulse_line(line: str, share_percent: float) -> None:
    text = plain_words(line).lower()
    if share_percent == 0:
        assert NEVER_CLEAR in text, "a zero share does not say the pulse never showed"
        assert "%" not in text
    elif half_up(share_percent) == 0:
        assert UNDER_ONE_PERCENT in text, "a tiny share does not say under 1%"
        assert printed_share(line) == 1
        assert NEVER_WORD not in text
    else:
        assert printed_share(line) == half_up(share_percent)
    assert LIGHT_ADVICE in text
    assert STILL_ADVICE in text
    assert LEFT_VIEW not in text


def assert_face_loss_line(line: str) -> None:
    text = plain_words(line).lower()
    assert LEFT_VIEW in text, "the line does not say the face kept leaving the view"
    assert FACE_ADVICE in text
    assert "%" not in text
    assert LIGHT_WORD.search(text) is None, "the face loss line gives light advice"


def assert_no_reading_line(line: str, checks: Sequence[WindowCheck]) -> None:
    if face_left_view(checks):
        assert_face_loss_line(line)
    else:
        assert_faint_pulse_line(line, share_at_or_above_floor(checks))


def assert_everyday_words(line: str, session_id: int | None = None) -> None:
    text = plain_words(line)
    assert JARGON.findall(text) == []
    assert CODE_WORD.findall(text) == []
    numbers = NUMBER.findall(text)
    percents = PERCENT.findall(text)
    assert len(percents) <= 1, f"the line holds {len(percents)} percent figures"
    for percent in percents:
        numbers.remove(percent)
    allowed = set() if session_id is None else {str(session_id)}
    assert [number for number in numbers if number not in allowed] == []


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


def interval_rows(url: str, session_id: int) -> list[tuple[object, ...]]:
    return stored_rows(url, "intervals", session_id, INTERVAL_COLUMNS)
