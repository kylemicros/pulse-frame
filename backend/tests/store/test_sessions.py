import pytest

from pulse_frame.store.errors import StoreError
from pulse_frame.store.sessions import LIST_COMMAND, delete_session, session_ids
from tests.database import (
    READ_ONLY_TRANSACTION,
    SEEDED_COUNTS,
    rows_under,
    seed_session,
)

UNDEFINED_TABLE = "42P01"


def test_session_ids_without_the_store_tables_raises_store_not_migrated(
    unmigrated_store: str,
) -> None:
    with pytest.raises(StoreError) as raised:
        session_ids()

    error = raised.value
    assert error.code == "STORE_NOT_MIGRATED"
    assert error.sqlstate == UNDEFINED_TABLE
    assert error.__cause__ is None
    assert error.__suppress_context__ is True


def test_delete_refused_by_the_database_raises_query_failed_with_its_sqlstate(
    store_url: str, read_only_session: int
) -> None:
    with pytest.raises(StoreError) as raised:
        delete_session(read_only_session)

    error = raised.value
    assert error.code == "STORE_QUERY_FAILED"
    assert error.sqlstate == READ_ONLY_TRANSACTION
    assert f"SQLSTATE {READ_ONLY_TRANSACTION}" in error.message
    assert error.__cause__ is None
    assert error.__suppress_context__ is True
    assert rows_under(store_url, read_only_session) == SEEDED_COUNTS


def test_delete_of_a_missing_session_raises_session_not_found_and_keeps_the_others(
    store_url: str,
) -> None:
    kept = seed_session(store_url)

    with pytest.raises(StoreError) as raised:
        delete_session(kept + 1000)

    assert raised.value.code == "SESSION_NOT_FOUND"
    assert LIST_COMMAND in raised.value.action
    assert rows_under(store_url, kept) == SEEDED_COUNTS
