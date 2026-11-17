import inspect

import psycopg
import pytest

from pulse_frame.store import recording
from pulse_frame.store.errors import StoreError
from pulse_frame.store.recording import (
    FrameSample,
    HrvRow,
    IntervalRow,
    frame_samples,
    open_writer,
    replace_replay,
)
from pulse_frame.store.sessions import LIST_COMMAND
from tests import database
from tests.database import (
    MONOTONIC_NS,
    READ_ONLY_TRANSACTION,
    SAMPLE_COLUMNS,
    START_MS,
    WALL_NS,
    rows_under,
    seed_session,
    stored_rows,
    stored_session_ids,
)

UNIQUE_VIOLATION = "23505"
CHECK_VIOLATION = "23514"
UNDEFINED_TABLE = "42P01"
BATCH_SIZE = 1_000
DUPLICATE_T_MS = START_MS + 987_654
MISSING_OFFSET = 1_000
DROPPED_WRITERS = ["add_beats", "add_intervals", "add_hrv_readings"]
EMPTY = {"frame_samples": 0, "beats": 0, "intervals": 0, "hrv_readings": 0}


def sample(step: int, moving: bool = False) -> FrameSample:
    return FrameSample(
        t_ms=START_MS + step * 33,
        forehead=(150.25 + step * 0.001, 118.5, 102.125),
        left_cheek=(145.75, 115.0 + step * 0.002, 100.5),
        right_cheek=(141.0, 112.25, 97.875 + step * 0.003),
        moving=moving,
    )


def samples(count: int, first: int = 0) -> list[FrameSample]:
    return [sample(step, moving=step % 50 == 7) for step in range(first, first + count)]


def sample_row(item: FrameSample) -> tuple[object, ...]:
    return (
        item.t_ms,
        *item.forehead,
        *item.left_cheek,
        *item.right_cheek,
        item.moving,
    )


BEATS = [START_MS + 412, START_MS + 1_236, START_MS + 2_049, START_MS + 2_861]
INTERVALS = [
    IntervalRow(t_ms=START_MS + 1_236, interval_ms=824.25, flag=0),
    IntervalRow(t_ms=START_MS + 2_049, interval_ms=812.75, flag=1),
    IntervalRow(t_ms=START_MS + 2_861, interval_ms=812.0, flag=4),
]
READINGS = [
    HrvRow(
        t_ms=START_MS + 70_000,
        rmssd_ms=31.5,
        sdnn_ms=44.25,
        window_ms=66_812.5,
        accepted_count=81,
    ),
    HrvRow(
        t_ms=START_MS + 71_000,
        rmssd_ms=30.75,
        sdnn_ms=43.5,
        window_ms=67_620.0,
        accepted_count=82,
    ),
]


def interval_row(item: IntervalRow) -> tuple[object, ...]:
    return (item.t_ms, item.interval_ms, item.flag)


def hrv_row(item: HrvRow) -> tuple[object, ...]:
    return (item.t_ms, item.rmssd_ms, item.sdnn_ms, item.window_ms, item.accepted_count)


def new_session() -> int:
    with open_writer() as writer:
        return writer.create_session(WALL_NS, MONOTONIC_NS)


def write_samples(session_id: int, items: list[FrameSample]) -> None:
    with open_writer() as writer:
        writer.add_frame_samples(session_id, items)


def assert_coded_without_psycopg_text(error: StoreError) -> None:
    assert error.__cause__ is None
    assert error.__suppress_context__ is True
    text = str(error)
    assert "DETAIL" not in text
    assert "Key (" not in text


def test_create_session_stores_the_wall_and_monotonic_pair_and_returns_its_id(
    store_url: str,
) -> None:
    session_id = new_session()

    assert isinstance(session_id, int)
    assert stored_session_ids(store_url) == [session_id]
    assert stored_rows(
        store_url,
        "sessions",
        session_id,
        ["started_wall_ns", "started_monotonic_ns"],
    ) == [(WALL_NS, MONOTONIC_NS)]


def test_each_new_session_gets_its_own_id(store_url: str) -> None:
    with open_writer() as writer:
        first = writer.create_session(WALL_NS, MONOTONIC_NS)
        second = writer.create_session(WALL_NS + 5, MONOTONIC_NS + 5)

    assert first != second
    assert stored_session_ids(store_url) == sorted([first, second])


def test_one_writer_holds_one_connection_for_the_session_and_every_batch(
    store_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_connect = psycopg.connect
    opened = [0]

    def counting_connect(*args: object, **kwargs: object) -> object:
        opened[0] += 1
        return real_connect(*args, **kwargs)

    monkeypatch.setattr(psycopg, "connect", counting_connect)
    batches = [samples(BATCH_SIZE), samples(BATCH_SIZE, first=BATCH_SIZE)]

    with open_writer() as writer:
        session_id = writer.create_session(WALL_NS, MONOTONIC_NS)
        for batch in batches:
            writer.add_frame_samples(session_id, batch)

    assert opened == [1]
    stored = stored_rows(store_url, "frame_samples", session_id, SAMPLE_COLUMNS)
    assert stored == [sample_row(item) for batch in batches for item in batch]


def test_each_batch_is_committed_before_the_writer_closes(store_url: str) -> None:
    batch = samples(20)

    with open_writer() as writer:
        session_id = writer.create_session(WALL_NS, MONOTONIC_NS)
        writer.add_frame_samples(session_id, batch)
        seen_while_open = stored_rows(
            store_url, "frame_samples", session_id, SAMPLE_COLUMNS
        )

    assert stored_session_ids(store_url) == [session_id]
    assert seen_while_open == [sample_row(item) for item in batch]


def test_frame_samples_read_back_in_time_order_exactly_as_written(
    store_url: str,
) -> None:
    session_id = new_session()
    written = samples(40)

    write_samples(session_id, list(reversed(written)))

    assert frame_samples(session_id) == written


def test_frame_samples_of_another_session_are_not_read_back(store_url: str) -> None:
    mine = new_session()
    other = new_session()
    write_samples(other, samples(5))

    assert frame_samples(mine) == []


def test_reading_frame_samples_of_a_missing_session_raises_session_not_found(
    store_url: str,
) -> None:
    kept = seed_session(store_url)

    with pytest.raises(StoreError) as raised:
        frame_samples(kept + MISSING_OFFSET)

    assert raised.value.code == "SESSION_NOT_FOUND"
    assert LIST_COMMAND in raised.value.action


@pytest.mark.parametrize("count", [3, 0], ids=["samples", "empty"])
def test_samples_under_a_missing_session_raise_session_not_found_saying_capture_stopped(
    store_url: str, count: int
) -> None:
    kept = seed_session(store_url)
    missing = kept + MISSING_OFFSET

    with pytest.raises(StoreError) as raised:
        write_samples(missing, samples(count))

    error = raised.value
    assert error.code == "SESSION_NOT_FOUND"
    assert "stopped recording" in f"{error.message} {error.action}"
    assert_coded_without_psycopg_text(error)
    assert rows_under(store_url, missing) == {"sessions": 0, **EMPTY}
    assert rows_under(store_url, kept) == database.SEEDED_COUNTS


def test_samples_written_twice_raise_duplicate_rows_saying_they_are_already_stored(
    store_url: str,
) -> None:
    session_id = new_session()
    write_samples(session_id, samples(3))

    with pytest.raises(StoreError) as raised:
        write_samples(session_id, [*samples(2, first=10), *samples(1)])

    error = raised.value
    assert error.code == "DUPLICATE_ROWS"
    assert error.sqlstate == UNIQUE_VIOLATION
    assert "already stored" in error.action
    assert "lost" in error.action
    assert_coded_without_psycopg_text(error)
    assert rows_under(store_url, session_id)["frame_samples"] == 3


def test_the_writer_writes_beats_intervals_and_hrv_only_through_replace_replay() -> (
    None
):
    present = [name for name in DROPPED_WRITERS if hasattr(recording, name)]

    assert present == [], f"product-unused writers still in the store: {present}"


def test_replace_replay_stores_beats_intervals_and_hrv_readings_as_given(
    store_url: str,
) -> None:
    session_id = new_session()

    replace_replay(session_id, BEATS, INTERVALS, READINGS)

    assert stored_rows(store_url, "beats", session_id, ["t_ms"]) == [
        (beat,) for beat in BEATS
    ]
    assert stored_rows(
        store_url, "intervals", session_id, ["t_ms", "interval_ms", "flag"]
    ) == [interval_row(item) for item in INTERVALS]
    assert stored_rows(
        store_url,
        "hrv_readings",
        session_id,
        ["t_ms", "rmssd_ms", "sdnn_ms", "window_ms", "accepted_count"],
    ) == [hrv_row(item) for item in READINGS]


@pytest.mark.parametrize(
    ("beats", "intervals", "readings"),
    [(BEATS, INTERVALS, READINGS), ([], [], [])],
    ids=["rows", "empty"],
)
def test_replace_replay_under_a_missing_session_raises_session_not_found(
    store_url: str,
    beats: list[int],
    intervals: list[IntervalRow],
    readings: list[HrvRow],
) -> None:
    kept = seed_session(store_url)
    missing = kept + MISSING_OFFSET

    with pytest.raises(StoreError) as raised:
        replace_replay(missing, beats, intervals, readings)

    error = raised.value
    assert error.code == "SESSION_NOT_FOUND"
    assert LIST_COMMAND in error.action
    assert_coded_without_psycopg_text(error)
    assert rows_under(store_url, missing) == {"sessions": 0, **EMPTY}
    assert rows_under(store_url, kept) == database.SEEDED_COUNTS


def test_a_replay_with_a_repeated_beat_raises_duplicate_rows_as_a_fault_to_report(
    store_url: str,
) -> None:
    session_id = new_session()
    replace_replay(session_id, BEATS, INTERVALS, READINGS)
    before = rows_under(store_url, session_id)

    with pytest.raises(StoreError) as raised:
        replace_replay(
            session_id, [*BEATS, DUPLICATE_T_MS, DUPLICATE_T_MS], INTERVALS, READINGS
        )

    error = raised.value
    assert error.code == "DUPLICATE_ROWS"
    assert error.sqlstate == UNIQUE_VIOLATION
    assert "replay" in error.action.lower()
    assert "report" in error.action.lower()
    assert str(DUPLICATE_T_MS) not in str(error)
    assert_coded_without_psycopg_text(error)
    assert rows_under(store_url, session_id) == before


def test_an_interval_flag_code_outside_the_tracker_flags_raises_query_failed(
    store_url: str,
) -> None:
    session_id = new_session()

    with pytest.raises(StoreError) as raised:
        replace_replay(
            session_id,
            [],
            [IntervalRow(t_ms=START_MS + 900, interval_ms=800.0, flag=7)],
            [],
        )

    error = raised.value
    assert error.code == "STORE_QUERY_FAILED"
    assert error.sqlstate == CHECK_VIOLATION
    assert_coded_without_psycopg_text(error)
    assert rows_under(store_url, session_id)["intervals"] == 0


def test_replacing_a_replay_twice_leaves_one_copy_of_its_rows(store_url: str) -> None:
    session_id = new_session()
    write_samples(session_id, samples(10))

    replace_replay(session_id, BEATS, INTERVALS, READINGS)
    replace_replay(session_id, BEATS, INTERVALS, READINGS)

    assert rows_under(store_url, session_id) == {
        "sessions": 1,
        "frame_samples": 10,
        "beats": len(BEATS),
        "intervals": len(INTERVALS),
        "hrv_readings": len(READINGS),
    }


def test_replacing_a_replay_drops_the_rows_of_the_run_before(store_url: str) -> None:
    session_id = new_session()
    replace_replay(session_id, BEATS, INTERVALS, READINGS)

    replace_replay(session_id, BEATS[:2], INTERVALS[:1], [])

    assert stored_rows(store_url, "beats", session_id, ["t_ms"]) == [
        (beat,) for beat in BEATS[:2]
    ]
    assert stored_rows(
        store_url, "intervals", session_id, ["t_ms", "interval_ms", "flag"]
    ) == [interval_row(INTERVALS[0])]
    assert rows_under(store_url, session_id)["hrv_readings"] == 0


def test_replacing_a_replay_leaves_other_sessions_alone(store_url: str) -> None:
    kept = seed_session(store_url)
    session_id = new_session()

    replace_replay(session_id, BEATS, INTERVALS, READINGS)

    assert rows_under(store_url, kept) == database.SEEDED_COUNTS


def test_a_replay_that_fails_part_way_keeps_the_previous_run(store_url: str) -> None:
    session_id = new_session()
    replace_replay(session_id, BEATS, INTERVALS, READINGS)
    before = rows_under(store_url, session_id)
    broken = [*INTERVALS, IntervalRow(t_ms=START_MS + 9_999, interval_ms=1.0, flag=9)]

    with pytest.raises(StoreError) as raised:
        replace_replay(session_id, BEATS, broken, READINGS)

    assert raised.value.code == "STORE_QUERY_FAILED"
    assert rows_under(store_url, session_id) == before


def test_opening_a_writer_without_the_database_url_raises_database_url_missing() -> (
    None
):
    with pytest.raises(StoreError) as raised, open_writer():
        pass

    assert raised.value.code == "DATABASE_URL_MISSING"


def test_create_session_before_the_migration_raises_store_not_migrated(
    unmigrated_store: str,
) -> None:
    with pytest.raises(StoreError) as raised:
        new_session()

    assert raised.value.code == "STORE_NOT_MIGRATED"
    assert raised.value.sqlstate == UNDEFINED_TABLE


def test_samples_refused_by_the_database_raise_query_failed_with_its_sqlstate(
    store_url: str, read_only_session: int
) -> None:
    with pytest.raises(StoreError) as raised:
        write_samples(read_only_session, samples(3, first=50))

    error = raised.value
    assert error.code == "STORE_QUERY_FAILED"
    assert error.sqlstate == READ_ONLY_TRANSACTION
    assert f"SQLSTATE {READ_ONLY_TRANSACTION}" in error.message
    assert_coded_without_psycopg_text(error)
    assert rows_under(store_url, read_only_session) == database.SEEDED_COUNTS


def test_a_replay_refused_by_the_database_raises_query_failed_and_keeps_the_rows(
    store_url: str, read_only_session: int
) -> None:
    with pytest.raises(StoreError) as raised:
        replace_replay(read_only_session, BEATS, INTERVALS, READINGS)

    assert raised.value.code == "STORE_QUERY_FAILED"
    assert raised.value.sqlstate == READ_ONLY_TRANSACTION
    assert rows_under(store_url, read_only_session) == database.SEEDED_COUNTS


def test_create_session_refused_by_the_database_raises_query_failed(
    store_url: str, read_only_session: int
) -> None:
    with pytest.raises(StoreError) as raised:
        new_session()

    assert raised.value.code == "STORE_QUERY_FAILED"
    assert raised.value.sqlstate == READ_ONLY_TRANSACTION
    assert stored_session_ids(store_url) == [read_only_session]


def test_the_session_check_lives_once_in_the_sessions_module() -> None:
    assert "def require_session" not in inspect.getsource(recording)
