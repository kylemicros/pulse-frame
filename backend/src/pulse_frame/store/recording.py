from collections.abc import Callable, Generator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass

import psycopg
from psycopg import sql
from psycopg.rows import TupleRow

from pulse_frame.store import STORE_SCHEMA
from pulse_frame.store.connection import connect
from pulse_frame.store.errors import StoreError
from pulse_frame.store.sessions import (
    SESSIONS,
    query_errors,
    session_exists,
    session_not_found,
)

type Colour = tuple[float, float, float]
type Connection = psycopg.Connection[TupleRow]
type RowValues = tuple[object, ...]
type ErrorFor = Callable[[int, str | None], StoreError]

SESSION_KEY = "session_id"
REGIONS = ("forehead", "left_cheek", "right_cheek")
CHANNELS = ("r", "g", "b")
COLOUR_COLUMNS = tuple(
    f"{region}_{channel}" for region in REGIONS for channel in CHANNELS
)
SAMPLE_COLUMNS = ("t_ms", *COLOUR_COLUMNS, "moving")
BEAT_COLUMNS = ("t_ms",)
INTERVAL_COLUMNS = ("t_ms", "interval_ms", "flag")
HRV_COLUMNS = ("t_ms", "rmssd_ms", "sdnn_ms", "window_ms", "accepted_count")
SESSION_COLUMNS = ("started_wall_ns", "started_monotonic_ns", "counted_monotonic_ns")
CLOCK_COLUMNS = ("started_monotonic_ns", "counted_monotonic_ns")
NS_PER_MS = 1_000_000
REPLAY_TABLES = ("beats", "intervals", "hrv_readings")


@dataclass(frozen=True)
class FrameSample:
    t_ms: int
    forehead: Colour
    left_cheek: Colour
    right_cheek: Colour
    moving: bool


@dataclass(frozen=True)
class IntervalRow:
    t_ms: int
    interval_ms: float
    flag: int


@dataclass(frozen=True)
class HrvRow:
    t_ms: int
    rmssd_ms: float
    sdnn_ms: float
    window_ms: float
    accepted_count: int


@dataclass(frozen=True)
class SessionClock:
    anchor_ns: int
    counted_ns: int

    @property
    def counted_ms(self) -> int:
        return self.counted_ns // NS_PER_MS

    @property
    def warmed_up(self) -> bool:
        return self.counted_ns > self.anchor_ns


def store_table(name: str) -> sql.Identifier:
    return sql.Identifier(STORE_SCHEMA, name)


def column_list(columns: Sequence[str]) -> sql.Composed:
    return sql.SQL(", ").join(sql.Identifier(name) for name in columns)


def insert_statement(table: str, columns: Sequence[str]) -> sql.Composed:
    names = (SESSION_KEY, *columns)
    return sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
        store_table(table),
        column_list(names),
        sql.SQL(", ").join([sql.Placeholder()] * len(names)),
    )


def capture_session_gone(session_id: int, sqlstate: str | None = None) -> StoreError:
    return StoreError(
        "SESSION_NOT_FOUND",
        f"Session {session_id} is no longer in the store: it was deleted while"
        " the capture was running, so the capture stopped recording.",
        "The samples not yet written were dropped. Run the capture again to"
        " record a new session.",
        sqlstate,
    )


def capture_duplicate(session_id: int, sqlstate: str | None) -> StoreError:
    return StoreError(
        "DUPLICATE_ROWS",
        f"Session {session_id} already holds a frame sample at one of the times"
        " in this batch, so the capture stopped and wrote none of the batch.",
        "The samples already stored are kept, so nothing written before was"
        " lost; only this batch was dropped. Run the capture again to record a"
        " new session.",
        sqlstate,
    )


def replay_session_gone(session_id: int, sqlstate: str | None = None) -> StoreError:
    error = session_not_found(session_id)
    error.sqlstate = sqlstate
    return error


def replay_duplicate(session_id: int, sqlstate: str | None) -> StoreError:
    return StoreError(
        "DUPLICATE_ROWS",
        f"The replay of session {session_id} produced two rows at the same time"
        " in one table, so nothing from this replay was written.",
        "The session keeps the rows of its earlier replay. This is a fault in"
        " the replay, not in the recording: report the code and the session ID.",
        sqlstate,
    )


@contextmanager
def write_errors(
    session_id: int, gone: ErrorFor, duplicate: ErrorFor
) -> Generator[None]:
    try:
        yield
    except psycopg.errors.ForeignKeyViolation as error:
        raise gone(session_id, error.sqlstate) from None
    except psycopg.errors.UniqueViolation as error:
        raise duplicate(session_id, error.sqlstate) from None


def insert_rows(
    conn: Connection,
    table: str,
    columns: Sequence[str],
    session_id: int,
    rows: Sequence[RowValues],
) -> None:
    if not rows:
        return
    with conn.cursor() as cursor:
        cursor.executemany(
            insert_statement(table, columns), [(session_id, *row) for row in rows]
        )


def sample_values(sample: FrameSample) -> RowValues:
    return (
        sample.t_ms,
        *sample.forehead,
        *sample.left_cheek,
        *sample.right_cheek,
        sample.moving,
    )


def sample_from_row(row: TupleRow) -> FrameSample:
    t_ms, fr, fg, fb, lr, lg, lb, rr, rg, rb, moving = row
    return FrameSample(
        t_ms=t_ms,
        forehead=(fr, fg, fb),
        left_cheek=(lr, lg, lb),
        right_cheek=(rr, rg, rb),
        moving=moving,
    )


def interval_values(interval: IntervalRow) -> RowValues:
    return (interval.t_ms, interval.interval_ms, interval.flag)


def hrv_values(reading: HrvRow) -> RowValues:
    return (
        reading.t_ms,
        reading.rmssd_ms,
        reading.sdnn_ms,
        reading.window_ms,
        reading.accepted_count,
    )


class SessionWriter:
    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def create_session(
        self, started_wall_ns: int, started_monotonic_ns: int, counted_monotonic_ns: int
    ) -> int:
        statement = sql.SQL(
            "INSERT INTO {} ({}) VALUES (%s, %s, %s) RETURNING id"
        ).format(SESSIONS, column_list(SESSION_COLUMNS))
        with query_errors(), self._conn.transaction():
            row = self._conn.execute(
                statement, [started_wall_ns, started_monotonic_ns, counted_monotonic_ns]
            ).fetchone()
        if row is None:
            raise StoreError(
                "STORE_QUERY_FAILED",
                "The session store accepted the new session but returned no ID for it.",
                "Check that the local database is running and migrated, then run"
                " the capture again.",
            )
        return row[0]

    def add_frame_samples(
        self, session_id: int, samples: Sequence[FrameSample]
    ) -> None:
        rows = [sample_values(sample) for sample in samples]
        with (
            query_errors(),
            write_errors(session_id, capture_session_gone, capture_duplicate),
            self._conn.transaction(),
        ):
            if not session_exists(self._conn, session_id):
                raise capture_session_gone(session_id) from None
            insert_rows(self._conn, "frame_samples", SAMPLE_COLUMNS, session_id, rows)


@contextmanager
def open_writer() -> Generator[SessionWriter]:
    with query_errors(), connect() as conn:
        conn.autocommit = True
        yield SessionWriter(conn)


def frame_samples(session_id: int) -> list[FrameSample]:
    statement = sql.SQL("SELECT {} FROM {} WHERE {} = %s ORDER BY {}").format(
        column_list(SAMPLE_COLUMNS),
        store_table("frame_samples"),
        sql.Identifier(SESSION_KEY),
        sql.Identifier("t_ms"),
    )
    with query_errors(), connect() as conn:
        if not session_exists(conn, session_id):
            raise session_not_found(session_id) from None
        rows = conn.execute(statement, [session_id], binary=True).fetchall()
    return [sample_from_row(row) for row in rows]


def session_clock(session_id: int) -> SessionClock:
    statement = sql.SQL("SELECT {} FROM {} WHERE id = %s").format(
        column_list(CLOCK_COLUMNS), SESSIONS
    )
    with query_errors(), connect() as conn:
        row = conn.execute(statement, [session_id]).fetchone()
    if row is None:
        raise session_not_found(session_id) from None
    anchor_ns, counted_ns = row
    return SessionClock(anchor_ns=anchor_ns, counted_ns=counted_ns)


def delete_replay_rows(conn: Connection, session_id: int) -> None:
    for table in REPLAY_TABLES:
        conn.execute(
            sql.SQL("DELETE FROM {} WHERE {} = %s").format(
                store_table(table), sql.Identifier(SESSION_KEY)
            ),
            [session_id],
        )


def replace_replay(
    session_id: int,
    beats_ms: Sequence[int],
    intervals: Sequence[IntervalRow],
    readings: Sequence[HrvRow],
) -> None:
    with (
        query_errors(),
        write_errors(session_id, replay_session_gone, replay_duplicate),
        connect() as conn,
    ):
        if not session_exists(conn, session_id, lock=True):
            raise session_not_found(session_id) from None
        delete_replay_rows(conn, session_id)
        insert_rows(
            conn, "beats", BEAT_COLUMNS, session_id, [(t_ms,) for t_ms in beats_ms]
        )
        insert_rows(
            conn,
            "intervals",
            INTERVAL_COLUMNS,
            session_id,
            [interval_values(interval) for interval in intervals],
        )
        insert_rows(
            conn,
            "hrv_readings",
            HRV_COLUMNS,
            session_id,
            [hrv_values(reading) for reading in readings],
        )
