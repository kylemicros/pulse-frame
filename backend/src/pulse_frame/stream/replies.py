import json
import math

import numpy as np
from numpy.typing import NDArray

from pulse_frame.monitor.processor import FrameResult, Patch
from pulse_frame.signal.summary import NoReading, Summary
from pulse_frame.signal.tracker import Reading
from pulse_frame.stream.errors import WIRE_ERRORS, WireCode

type Message = dict[str, object]

OUTLINE_PLACES = 4
PULSE_TIME_PLACES = 1
PULSE_VALUE_PLACES = 4
BPM_PLACES = 1
QUALITY_PLACES = 2
HRV_PLACES = 1


def encoded(message: Message) -> str:
    return json.dumps(message, allow_nan=False, separators=(",", ":"))


def frame_message(capture_ms: int, result: FrameResult) -> Message:
    return {
        "type": "frame",
        "t": capture_ms,
        "face": bool(result.face),
        "moving": bool(result.moving),
        "patches": {
            name: patch_message(patch) for name, patch in result.patches.items()
        },
    }


def patch_message(patch: Patch) -> Message:
    if not patch.usable or patch.outline is None:
        return {"usable": False, "outline": None}
    return {"usable": True, "outline": outline_points(patch.outline)}


def outline_points(outline: NDArray[np.float64]) -> list[list[float]]:
    return [
        [round(float(x), OUTLINE_PLACES), round(float(y), OUTLINE_PLACES)]
        for x, y in outline.tolist()
    ]


def pulse_message(waveform: list[tuple[float, float]]) -> Message:
    return {
        "type": "pulse",
        "samples": [
            [float(round(t, PULSE_TIME_PLACES)), float(round(v, PULSE_VALUE_PLACES))]
            for t, v in waveform
        ],
    }


def bpm_message(capture_ms: int, reading: Reading) -> Message:
    return {
        "type": "bpm",
        "t": capture_ms,
        "bpm": rounded(reading.bpm, BPM_PLACES) if reading.state == "ok" else None,
        "quality_db": rounded(reading.quality_db, QUALITY_PLACES),
        "state": reading.state,
    }


def hrv_message(
    capture_ms: int, summary: Summary, no_reading: NoReading | None
) -> Message:
    decision = sendable(no_reading)
    return {
        "type": "hrv",
        "t": capture_ms,
        "rmssd_ms": rounded(finite(summary.rmssd_ms), HRV_PLACES),
        "sdnn_ms": rounded(finite(summary.sdnn_ms), HRV_PLACES),
        "minute_bpm": rounded(finite(summary.bpm), BPM_PLACES),
        "minute_count": summary.count,
        "bpm_low": None,
        "bpm_high": None,
        "no_reading": None if decision is None else decision.code,
        "why": None if decision is None else decision.why,
        "clear_percent": None if decision is None else decision.clear_percent,
    }


def sendable(no_reading: NoReading | None) -> NoReading | None:
    if no_reading is None:
        return None
    if no_reading.why == "faint_pulse" and finite(no_reading.clear_percent) is None:
        return None
    return no_reading


def finite(value: float | None) -> float | None:
    return value if value is not None and math.isfinite(value) else None


def rounded(value: float | None, places: int) -> float | None:
    return None if value is None else float(round(value, places))


def error_message(code: WireCode) -> Message:
    entry = WIRE_ERRORS[code]
    return {
        "type": "error",
        "code": code,
        "message": entry.message,
        "action": entry.action,
    }
