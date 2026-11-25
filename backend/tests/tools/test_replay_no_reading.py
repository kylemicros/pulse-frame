import math
import re

import pytest

from pulse_frame.signal.hrv import READING_FLOOR_DB, HrvTracker, WindowCheck
from pulse_frame.signal.summary import Summary
from pulse_frame.store.recording import HrvRow, frame_samples
from pulse_frame.tools import replay
from pulse_frame.tools.sessions import SANDBOX_UNSUPPORTED_ACTION
from tests.counted_runs import NEAR_FLOOR_SD, TOO_WEAK_SD, UNDER_FLOOR_SD, noisy
from tests.database import WALL_NS, insert_recording, rows_under
from tests.platform.support import after_sandbox_notice
from tests.signal.synthetic import Recording
from tests.tools.replay_support import (
    COUNTED_SUMMARY_LINE,
    NS_PER_MS,
    NS_PER_S,
    SUMMARY_LINE,
    anchor_ns,
    assert_everyday_words,
    assert_face_loss_line,
    assert_faint_pulse_line,
    assert_no_reading_line,
    beside_holes,
    face_left_view,
    face_lost_recording,
    median_snr_db,
    no_reading_lines,
    plain_words,
    region_colours,
    sample_rows,
    share_at_or_above_floor,
    still,
)

WEAK_CODE = "SIGNAL_TOO_WEAK"
NO_COUNTED_CODE = "NO_COUNTED_SAMPLES"
WARM_UP_S = 60.0
COUNTED_S = 90.0
CLEAN_SD = 0.1
JUST_CLEARING_SD = 0.17
SUMMARY_SPAN_MS = 60_000.0
COUNTED_LABEL = "counted 90 seconds"
WEAK_ACTION = (
    "Light the face evenly and brightly, for example facing a window or a lamp,"
    " keep still, and turn off the camera's auto exposure if it has that"
    " setting, then record a new session with"
    " `uv run python -m pulse_frame.tools.capture`."
)
WEAK_WHY = (
    "The pulse in the face colour did not repeat clearly enough across the face"
    " regions to time beats."
)
NO_WARM_UP = ["column_default", "zero", "anchor"]
LATE_COUNTED_S = 200.0
FACE_LOSS_EVERY_S = 15.0
UNDER_FLOOR_RUNS = [
    pytest.param(NEAR_FLOOR_SD, id="some_windows_clear"),
    pytest.param(UNDER_FLOOR_SD, id="no_window_clears"),
]
CHECK_STEP_MS = 1_000.0
UNDER_DB = 1.0
CLEAR_DB = 5.0
TINY_SHARE_UNDER = 250
NAN = float("nan")
HAND_ROW = HrvRow(
    t_ms=60_000, rmssd_ms=40.0, sdnn_ms=50.0, window_ms=60_000, accepted_count=60
)
HAND_RMSSD_MS = 40.0


def stored_session(
    url: str,
    recording: Recording,
    counted_ns: int | None,
    moving: bool = False,
) -> tuple[int, int]:
    flags = ~still(recording) if moving else still(recording)
    session_id = insert_recording(
        url, WALL_NS, anchor_ns(recording), sample_rows(recording, flags), counted_ns
    )
    return session_id, 0 if counted_ns is None else counted_ns // NS_PER_MS


def warmed_up(url: str, recording: Recording, moving: bool = False) -> tuple[int, int]:
    counted_ns = anchor_ns(recording) + round(WARM_UP_S * NS_PER_S)
    return stored_session(url, recording, counted_ns, moving)


def warmed_up_session(url: str, noise_sd: float) -> tuple[int, int]:
    return warmed_up(url, noisy(noise_sd, WARM_UP_S + COUNTED_S))


def face_lost_session(url: str) -> tuple[int, int]:
    recording = face_lost_recording(WARM_UP_S + COUNTED_S, FACE_LOSS_EVERY_S)
    return warmed_up(url, recording)


def no_warm_up_session(url: str, noise_sd: float, counted: str) -> int:
    recording = noisy(noise_sd, WARM_UP_S + COUNTED_S)
    anchor = anchor_ns(recording)
    counted_ns = {"column_default": None, "zero": 0, "anchor": anchor}[counted]
    session_id, _ = stored_session(url, recording, counted_ns)
    return session_id


def replay_output(
    session_id: int, capsys: pytest.CaptureFixture[str], exit_code: int = 0
) -> tuple[list[str], list[str]]:
    assert replay.main([str(session_id)]) == exit_code
    output = capsys.readouterr()
    err = after_sandbox_notice(output.err, action=SANDBOX_UNSUPPORTED_ACTION)
    return output.out.splitlines(), err.splitlines()


def counted_checks(session_id: int, counted_ms: int) -> list[WindowCheck]:
    samples = frame_samples(session_id)
    tracker = HrvTracker()
    for sample, low_quality in zip(samples, beside_holes(samples), strict=True):
        tracker.add(
            sample.t_ms,
            region_colours(sample),
            moving=sample.moving,
            low_quality=bool(low_quality),
        )
    return [check for check in tracker.window_checks() if check.t_ms >= counted_ms]


def coded(lines: list[str], code: str) -> list[str]:
    return [line for line in lines if line.startswith(f"{code}: ")]


def hand_result(
    snrs: list[float], readings: list[HrvRow] | None = None
) -> replay.ReplayResult:
    checks = [
        WindowCheck(t_ms=index * CHECK_STEP_MS, snr_db=snr)
        for index, snr in enumerate(snrs)
    ]
    return replay.ReplayResult(
        intervals=[],
        readings=readings or [],
        newest_ms=round(len(snrs) * CHECK_STEP_MS),
        window_checks=checks,
    )


def hand_summary(rmssd_ms: float | None = None) -> Summary:
    return Summary(
        bpm=None, rmssd_ms=rmssd_ms, sdnn_ms=None, count=0, accepted_percent=None
    )


def hand_notice(snrs: list[float]) -> str:
    notice = replay.no_reading_notice(hand_result(snrs), hand_summary())
    assert notice is not None, "no line for a counted part under the floor"
    assert_everyday_words(notice)
    return notice


@pytest.mark.parametrize("noise_sd", UNDER_FLOOR_RUNS)
def test_a_counted_part_under_the_reading_floor_gives_one_faint_pulse_line(
    store_url: str, capsys: pytest.CaptureFixture[str], noise_sd: float
) -> None:
    session_id, counted_ms = warmed_up_session(store_url, noise_sd)
    checks = counted_checks(session_id, counted_ms)
    assert median_snr_db(checks) < READING_FLOOR_DB, "the counted part clears"
    assert not face_left_view(checks), "the face left the view"

    _, notices = replay_output(session_id, capsys)

    assert rows_under(store_url, session_id)["hrv_readings"] == 0
    assert len(notices) == 1, f"replay printed {len(notices)} notice lines"
    assert_faint_pulse_line(notices[0], share_at_or_above_floor(checks))


@pytest.mark.parametrize(
    "noise_sd",
    [
        pytest.param(CLEAN_SD, id="clean"),
        pytest.param(JUST_CLEARING_SD, id="just_clearing"),
    ],
)
def test_a_counted_part_that_clears_the_reading_floor_gives_no_notice(
    store_url: str, capsys: pytest.CaptureFixture[str], noise_sd: float
) -> None:
    session_id, counted_ms = warmed_up_session(store_url, noise_sd)
    checks = counted_checks(session_id, counted_ms)
    assert median_snr_db(checks) >= READING_FLOOR_DB, "the counted part never clears"

    lines, notices = replay_output(session_id, capsys)

    assert len(lines) == 1
    assert re.fullmatch(COUNTED_SUMMARY_LINE, lines[0]) is not None
    assert notices == []
    assert rows_under(store_url, session_id)["hrv_readings"] > 0


def test_a_run_too_weak_for_beats_gives_only_the_unchanged_weak_notice(
    store_url: str, capsys: pytest.CaptureFixture[str]
) -> None:
    session_id, counted_ms = warmed_up_session(store_url, TOO_WEAK_SD)
    checks = counted_checks(session_id, counted_ms)
    newest_ms = float(frame_samples(session_id)[-1].t_ms)
    newest = [c for c in checks if newest_ms - SUMMARY_SPAN_MS <= c.t_ms <= newest_ms]
    assert all(check.measured for check in newest)
    under = sum(1 for check in newest if check.under_floor)
    expected = (
        f"{WEAK_CODE}: The newest minute has no accepted beat: {under} of"
        f" {len(newest)} analysis windows were under the pulse quality floor of"
        f" 0 dB, median {median_snr_db(newest):.1f} dB. {WEAK_WHY} {WEAK_ACTION}"
    )

    _, notices = replay_output(session_id, capsys)

    assert notices == [expected]


def test_a_run_under_the_reading_floor_with_accepted_beats_gives_no_weak_notice(
    store_url: str, capsys: pytest.CaptureFixture[str]
) -> None:
    session_id, _ = warmed_up_session(store_url, UNDER_FLOOR_SD)

    lines, notices = replay_output(session_id, capsys)

    found = re.fullmatch(COUNTED_SUMMARY_LINE, lines[0])
    assert found is not None
    assert int(found["count"]) > 0, "no beat was accepted in the newest minute"
    assert coded(notices, WEAK_CODE) == []
    assert len(no_reading_lines(notices)) == 1


@pytest.mark.parametrize("noise_sd", UNDER_FLOOR_RUNS)
def test_a_run_with_no_reading_keeps_the_one_unchanged_summary_line_on_stdout(
    store_url: str, capsys: pytest.CaptureFixture[str], noise_sd: float
) -> None:
    session_id, counted_ms = warmed_up_session(store_url, noise_sd)
    samples = frame_samples(session_id)
    expected = replay.summary_line(
        session_id,
        replay.summarise(replay.replay_samples(samples, counted_ms)),
        COUNTED_LABEL,
    )

    lines, notices = replay_output(session_id, capsys)

    assert lines == [expected]
    found = re.fullmatch(COUNTED_SUMMARY_LINE, lines[0])
    assert found is not None
    assert (found["amount"], found["unit"]) == ("90", "seconds")
    assert found["rmssd"] == "-"
    assert found["unset_sdnn"] == "-"
    assert len(no_reading_lines(notices)) == 1


@pytest.mark.parametrize("kind", ["some_windows_clear", "no_window_clears", "face"])
def test_the_no_reading_line_is_everyday_words_with_no_value_but_its_share(
    store_url: str, capsys: pytest.CaptureFixture[str], kind: str
) -> None:
    session_id, _ = {
        "some_windows_clear": lambda: warmed_up_session(store_url, NEAR_FLOOR_SD),
        "no_window_clears": lambda: warmed_up_session(store_url, UNDER_FLOOR_SD),
        "face": lambda: face_lost_session(store_url),
    }[kind]()

    _, notices = replay_output(session_id, capsys)

    lines = no_reading_lines(notices)
    assert len(lines) == 1
    assert_everyday_words(lines[0], session_id)


@pytest.mark.parametrize("counted", NO_WARM_UP)
def test_a_session_with_no_warm_up_that_never_clears_counts_all_of_it_in_one_line(
    store_url: str, capsys: pytest.CaptureFixture[str], counted: str
) -> None:
    session_id = no_warm_up_session(store_url, NEAR_FLOOR_SD, counted)
    checks = counted_checks(session_id, 0)
    assert median_snr_db(checks) < READING_FLOOR_DB, "the session clears"

    lines, notices = replay_output(session_id, capsys)

    assert len(lines) == 1
    found = re.fullmatch(SUMMARY_LINE, lines[0])
    assert found is not None
    assert found["rmssd"] == "-"
    assert len(notices) == 1, f"replay printed {len(notices)} notice lines"
    assert_no_reading_line(notices[0], checks)


@pytest.mark.parametrize("counted", NO_WARM_UP)
def test_a_session_with_no_warm_up_that_clears_gives_no_notice(
    store_url: str, capsys: pytest.CaptureFixture[str], counted: str
) -> None:
    session_id = no_warm_up_session(store_url, CLEAN_SD, counted)
    checks = counted_checks(session_id, 0)
    assert median_snr_db(checks) >= READING_FLOOR_DB, "the session never clears"

    lines, notices = replay_output(session_id, capsys)

    assert len(lines) == 1
    assert re.fullmatch(SUMMARY_LINE, lines[0]) is not None
    assert notices == []


def test_a_face_that_keeps_leaving_the_view_gives_the_face_loss_line(
    store_url: str, capsys: pytest.CaptureFixture[str]
) -> None:
    session_id, counted_ms = face_lost_session(store_url)
    checks = counted_checks(session_id, counted_ms)
    assert any(not check.measured for check in checks), "every window was measured"
    assert median_snr_db(checks) < READING_FLOOR_DB, "the counted part clears"
    assert face_left_view(checks), "the face did not leave the view often enough"

    _, notices = replay_output(session_id, capsys)

    assert len(notices) == 1, f"replay printed {len(notices)} notice lines"
    assert_face_loss_line(notices[0])


def test_a_counted_part_that_clears_but_moves_throughout_gives_no_notice(
    store_url: str, capsys: pytest.CaptureFixture[str]
) -> None:
    recording = noisy(CLEAN_SD, WARM_UP_S + COUNTED_S)
    session_id, counted_ms = warmed_up(store_url, recording, moving=True)
    checks = counted_checks(session_id, counted_ms)
    assert median_snr_db(checks) >= READING_FLOOR_DB, "the counted part never clears"

    lines, notices = replay_output(session_id, capsys)

    assert rows_under(store_url, session_id)["hrv_readings"] == 0
    found = re.fullmatch(COUNTED_SUMMARY_LINE, lines[0])
    assert found is not None
    assert found["rmssd"] == "-"
    assert notices == []


def test_a_session_with_no_counted_samples_gives_only_the_no_counted_samples_line(
    store_url: str, capsys: pytest.CaptureFixture[str]
) -> None:
    recording = noisy(NEAR_FLOOR_SD, WARM_UP_S + COUNTED_S)
    counted_ns = anchor_ns(recording) + round(LATE_COUNTED_S * NS_PER_S)
    session_id, _ = stored_session(store_url, recording, counted_ns)

    lines, notices = replay_output(session_id, capsys, exit_code=1)

    assert lines == []
    assert len(notices) == 1
    assert notices[0].startswith(f"{NO_COUNTED_CODE}: ")
    assert rows_under(store_url, session_id)["hrv_readings"] == 0


def test_a_counted_part_with_hrv_readings_gives_no_line_even_under_the_floor() -> None:
    result = hand_result([UNDER_DB] * 4, readings=[HAND_ROW])

    assert replay.no_reading_notice(result, hand_summary()) is None


def test_a_summary_with_rmssd_gives_no_line_even_under_the_floor() -> None:
    result = hand_result([UNDER_DB] * 4)

    assert replay.no_reading_notice(result, hand_summary(HAND_RMSSD_MS)) is None


def test_a_counted_part_with_no_checks_gives_no_line() -> None:
    assert replay.no_reading_notice(hand_result([]), hand_summary()) is None


def test_a_counted_part_whose_median_clears_gives_no_line() -> None:
    result = hand_result([CLEAR_DB, CLEAR_DB, UNDER_DB])

    assert replay.no_reading_notice(result, hand_summary()) is None


def test_a_check_at_exactly_the_floor_counts_as_showing_clearly() -> None:
    notice = hand_notice([READING_FLOOR_DB, UNDER_DB, UNDER_DB, UNDER_DB])

    assert_faint_pulse_line(notice, 25)


def test_plus_infinity_counts_as_clear_and_minus_infinity_and_nan_do_not() -> None:
    notice = hand_notice([math.inf, UNDER_DB, UNDER_DB, -math.inf, NAN])

    assert_faint_pulse_line(notice, 20)


def test_an_even_count_with_the_median_under_the_floor_prints_exactly_half() -> None:
    notice = hand_notice([UNDER_DB, 2.0, READING_FLOOR_DB, 3.5])

    assert_faint_pulse_line(notice, 50)


def test_a_share_of_twelve_and_a_half_percent_rounds_half_up_to_thirteen() -> None:
    notice = hand_notice([CLEAR_DB] + [UNDER_DB] * 7)

    assert_faint_pulse_line(notice, 12.5)


def test_a_zero_share_says_the_pulse_never_showed_clearly() -> None:
    notice = hand_notice([UNDER_DB] * 4)

    assert_faint_pulse_line(notice, 0)


def test_a_share_that_rounds_to_zero_says_under_one_percent_not_never() -> None:
    notice = hand_notice([CLEAR_DB] + [UNDER_DB] * TINY_SHARE_UNDER)

    text = plain_words(notice).lower()
    assert "under 1%" in text
    assert text.count("%") == 1
    assert "never" not in text
    assert "0%" not in text
    assert_faint_pulse_line(notice, 100.0 / (TINY_SHARE_UNDER + 1))


@pytest.mark.parametrize(
    ("snrs", "share"),
    [
        pytest.param(
            [-math.inf, NAN, UNDER_DB, 2.0, CLEAR_DB], 20, id="as_many_unmeasured"
        ),
        pytest.param(
            [math.inf, math.inf, -math.inf, UNDER_DB, 2.0],
            40,
            id="plus_infinity_is_not_unmeasured",
        ),
    ],
)
def test_unmeasured_checks_no_more_than_those_measured_under_give_the_faint_line(
    snrs: list[float], share: int
) -> None:
    notice = hand_notice(snrs)

    assert_faint_pulse_line(notice, share)


def test_one_more_unmeasured_check_than_those_measured_under_gives_face_loss() -> None:
    notice = hand_notice([-math.inf, NAN, -math.inf, UNDER_DB, 2.0, CLEAR_DB])

    assert_face_loss_line(notice)
