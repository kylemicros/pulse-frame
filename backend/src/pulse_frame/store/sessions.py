from collections.abc import Generator
from contextlib import contextmanager

import psycopg
from psycopg import sql
from psycopg.rows import TupleRow

from pulse_frame.store import STORE_SCHEMA
from pulse_frame.store.connection import connect
from pulse_frame.store.errors import StoreError

SESSIONS_COMMAND = "uv run python -m pulse_frame.tools.sessions"
LIST_COMMAND = f"{SESSIONS_COMMAND} list"
SESSIONS = sql.Identifier(STORE_SCHEMA, "sessions")
QUERY_FAILED_ACTION = (
    "Check that the local database is running and migrated, then run the command again."
)


def delete_failed_action(session_id: int) -> str:
    return (
        f"Run `{LIST_COMMAND}` in backend/ to check whether session {session_id}"
        " is still there; if it is, check that the local database is running and"
        " writable, then run the delete again."
    )


def query_failed_message(error: psycopg.Error) -> str:
    return (
        f"The session store refused or lost the query ({type(error).__name__},"
        f" SQLSTATE {error.sqlstate or 'none'})."
    )


@contextmanager
def query_errors(failed_action: str = QUERY_FAILED_ACTION) -> Generator[None]:
    try:
        yield
    except psycopg.errors.UndefinedTable as error:
        raise StoreError(
            "STORE_NOT_MIGRATED",
            f"The database has no session tables in the `{STORE_SCHEMA}` schema yet.",
            "Apply the migrations in supabase/migrations with `supabase migration"
            " up` and the pulse-frame workdir, then run the command again.",
            error.sqlstate,
        ) from None
    except psycopg.Error as error:
        raise StoreError(
            "STORE_QUERY_FAILED",
            query_failed_message(error),
            failed_action,
            error.sqlstate,
        ) from None


def session_not_found(session_id: int) -> StoreError:
    return StoreError(
        "SESSION_NOT_FOUND",
        f"No session has the ID {session_id}.",
        f"Run `{LIST_COMMAND}` in backend/ to see the session IDs, then try again"
        " with one of them.",
    )


def session_ids() -> list[int]:
    statement = sql.SQL("SELECT id FROM {} ORDER BY id").format(SESSIONS)
    with query_errors(), connect() as conn:
        rows = conn.execute(statement).fetchall()
    return [row[0] for row in rows]


def session_exists(
    conn: psycopg.Connection[TupleRow], session_id: int, lock: bool = False
) -> bool:
    statement = sql.SQL("SELECT 1 FROM {} WHERE id = %s{}").format(
        SESSIONS, sql.SQL(" FOR NO KEY UPDATE" if lock else "")
    )
    return conn.execute(statement, [session_id]).fetchone() is not None


def require_session(session_id: int) -> None:
    with query_errors(), connect() as conn:
        found = session_exists(conn, session_id)
    if not found:
        raise session_not_found(session_id)


def delete_session(session_id: int) -> None:
    statement = sql.SQL("DELETE FROM {} WHERE id = %s").format(SESSIONS)
    with query_errors(delete_failed_action(session_id)), connect() as conn:
        deleted = conn.execute(statement, [session_id]).rowcount
    if deleted == 0:
        raise session_not_found(session_id)
