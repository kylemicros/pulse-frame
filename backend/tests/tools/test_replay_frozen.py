import pytest

from pulse_frame.store.recording import SessionClock
from pulse_frame.tools import replay
from tests.counted_runs import (
    HOLED_RUN_S,
    WARM_UP_S,
    WARMED_UP_RUNS,
    frame_samples,
    holed,
)
from tests.signal.synthetic import Recording
from tests.tools.replay_support import NS_PER_S, anchor_ns

SESSION_ID = 7
CAPTURE_TAIL = (
    " then record a new session with `uv run python -m pulse_frame.tools.capture`."
)
NO_READING_REF = " Ref: READING_FLOOR_NOT_CLEARED\n"
FAINT_ACTION = (
    " Give your face more even light, for example facing a window, and hold still,"
)
FROZEN = {
    "clean": (
        "Session 7 replayed, newest minute: bpm=72.1 count=68 sdnn=34.7 ms;"
        " counted 90 seconds: rmssd=41.6 ms; counted part: accepted=100.0%\n",
        "",
    ),
    "clean_two_counted_minutes": (
        "Session 7 replayed, newest minute: bpm=72.1 count=67; counted 140 seconds:"
        " rmssd=42.8 ms sdnn=35.5 ms over 2 minutes; counted part: accepted=100.0%\n",
        "",
    ),
    "some_windows_clear": (
        "Session 7 replayed, newest minute: bpm=72.1 count=68; counted 90 seconds:"
        " rmssd=- sdnn=-; counted part: accepted=100.0%\n",
        "No reading this time: your pulse showed clearly in only 26% of the run."
        f"{FAINT_ACTION}{CAPTURE_TAIL}{NO_READING_REF}",
    ),
    "no_window_clears": (
        "Session 7 replayed, newest minute: bpm=- count=19; counted 90 seconds:"
        " rmssd=- sdnn=-; counted part: accepted=96.3%\n",
        "No reading this time: your pulse never showed clearly during the run."
        f"{FAINT_ACTION}{CAPTURE_TAIL}{NO_READING_REF}",
    ),
    "too_weak": (
        "Session 7 replayed, newest minute: bpm=- count=0; counted 90 seconds:"
        " rmssd=- sdnn=-; counted part: accepted=-\n",
        "SIGNAL_TOO_WEAK: The newest minute has no accepted beat: 59 of 59 analysis"
        " windows were under the pulse quality floor of 0 dB, median -4.6 dB."
        " The pulse in the face colour did not repeat clearly enough across the face"
        " regions to time beats. Light the face evenly and brightly, for example"
        " facing a window or a lamp, keep still, and turn off the camera's auto"
        f" exposure if it has that setting,{CAPTURE_TAIL}\n",
    ),
    "face_left_view": (
        "Session 7 replayed, newest minute: bpm=- count=24; counted 89 seconds:"
        " rmssd=- sdnn=-; counted part: accepted=87.8%\n",
        "No reading this time: your face kept leaving the camera's view, so your"
        " pulse could not be read. Sit facing the camera and keep your face in view,"
        f"{CAPTURE_TAIL}{NO_READING_REF}",
    ),
    "holes_in_the_counted_part": (
        "Session 7 replayed, newest minute: bpm=72.1 count=62 sdnn=34.7 ms;"
        " counted 90 seconds: rmssd=41.4 ms; counted part: accepted=88.3%\n",
        "",
    ),
    "holes_without_warm_up": (
        "Session 7 replayed, newest minute: bpm=72.0 count=57; last 5 minutes:"
        " rmssd=41.8 ms sdnn=34.8 ms; whole session: accepted=88.9%\n",
        "",
    ),
}


def session_clock(recording: Recording, warmed_up: bool) -> SessionClock:
    anchor = anchor_ns(recording)
    counted = anchor + round(WARM_UP_S * NS_PER_S) if warmed_up else anchor
    return SessionClock(anchor_ns=anchor, counted_ns=counted)


@pytest.mark.parametrize("kind", list(FROZEN), ids=list(FROZEN))
def test_replay_prints_the_same_bytes_as_before_the_logic_moved_into_signal(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], kind: str
) -> None:
    warmed_up = kind in WARMED_UP_RUNS
    recording = WARMED_UP_RUNS[kind]() if warmed_up else holed(HOLED_RUN_S)
    samples = frame_samples(recording)
    clock = session_clock(recording, warmed_up)
    written: list[int] = []
    monkeypatch.setattr(replay, "frame_samples", lambda session_id: samples)
    monkeypatch.setattr(replay, "session_clock", lambda session_id: clock)
    monkeypatch.setattr(
        replay, "replace_replay", lambda session_id, *rows: written.append(session_id)
    )

    assert replay.replay(SESSION_ID) == 0

    output = capsys.readouterr()
    assert written == [SESSION_ID]
    assert (output.out, output.err) == FROZEN[kind]
