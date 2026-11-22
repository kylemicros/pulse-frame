import numpy as np
from numpy.typing import NDArray

from tests.database import COLOUR_COLUMNS, Row, stored_rows
from tests.signal.synthetic import Recording

ANCHOR_LEAD_MS = 250
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
COUNTED_SUMMARY_LINE = (
    rf"Session (?P<session>\d+) replayed,"
    rf" newest minute: bpm=(?P<bpm>{PRINTED_VALUE}) count=(?P<count>\d+);"
    rf" counted (?P<amount>\d+) (?P<unit>minutes|minute|seconds):"
    rf" rmssd=(?P<rmssd>{PRINTED_VALUE})(?: ms)?"
    rf" sdnn=(?P<sdnn>{PRINTED_VALUE})(?: ms)?;"
    rf" counted part: accepted=(?P<accepted>{PRINTED_VALUE})%?"
)


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
