import os
import subprocess
import sys
import time
from collections.abc import Callable

import psycopg
import pytest
from psycopg.conninfo import make_conninfo

from tests import database
from tests.database import (
    MALFORMED_MARKER,
    MALFORMED_URL,
    MONOTONIC_NS,
    RUN_LOCK,
    TEST_DATABASE,
    UNREACHABLE_URL,
    URL_VARIABLE,
    WALL_NS,
    RefusedDatabaseError,
    apply_migration_files,
    apply_migrations,
    drop_database,
    empty_tables,
    hide_store,
    insert_recording,
    insert_samples,
    make_read_only,
    make_writable,
    plant_public_default_privileges,
    recreate_database,
    restore_store,
    run_lock,
    scoped_url,
    seed_session,
    server_url,
    stored_rows,
    stored_session_ids,
    with_database_url,
)
from tests.platform.sandboxed import BACKEND
from tests.platform.support import PROBE_TIMEOUT_S

URL_SEEN_AT_COLLECTION = URL_VARIABLE in os.environ
UNREACHABLE_MARKER = "probe@127.0.0.1:1"
BUSY_WAIT_S = 0.2
BUSY_BOUND_S = 5.0
FIXTURE_TEST = (
    "tests/store/test_test_database.py::"
    "test_store_fixture_connects_to_the_test_database_only"
)
UNREACHABLE_SERVER = "host=store.invalid port=1 connect_timeout=1"
OTHER_NAMES = [
    "postgres",
    "template1",
    "Pulse_Frame_Test",
    "pulse_frame_test_old",
    " pulse_frame_test",
    "",
]
RUN_LOCK_HOLDERS = """
SELECT count(*) FROM pg_locks
WHERE locktype = 'advisory' AND granted
  AND classid = 0 AND objid::bigint = %s AND objsubid = 1
"""


def on_a_url_naming(helper: Callable[[str], object]) -> Callable[[str, str], object]:
    def call(server: str, name: str) -> object:
        return helper(make_conninfo(server, dbname=name))

    call.__name__ = helper.__name__
    return call


def insert_empty_recording(url: str) -> int:
    return insert_recording(url, WALL_NS, MONOTONIC_NS, [])


def insert_counted_recording(url: str) -> int:
    return insert_recording(url, WALL_NS, MONOTONIC_NS, [], MONOTONIC_NS)


def apply_no_migration_files(url: str) -> None:
    apply_migration_files(url, [])


def insert_no_samples(url: str) -> None:
    insert_samples(url, 1, [])


def read_session_rows(url: str) -> object:
    return stored_rows(url, "sessions", 1, ["id"])


HELPERS = [
    drop_database,
    recreate_database,
    scoped_url,
    *(
        on_a_url_naming(helper)
        for helper in (
            empty_tables,
            seed_session,
            apply_migrations,
            apply_no_migration_files,
            hide_store,
            restore_store,
            make_read_only,
            make_writable,
            plant_public_default_privileges,
            insert_empty_recording,
            insert_counted_recording,
            insert_no_samples,
            read_session_rows,
            stored_session_ids,
        )
    ),
]


@pytest.mark.parametrize("helper", HELPERS, ids=lambda helper: helper.__name__)
@pytest.mark.parametrize("name", OTHER_NAMES)
def test_test_database_helpers_refuse_any_other_database(
    helper: Callable[[str, str], object], name: str
) -> None:
    with pytest.raises(RefusedDatabaseError) as refused:
        helper(UNREACHABLE_SERVER, name)

    assert "REFUSED_DATABASE" in str(refused.value)
    assert TEST_DATABASE in str(refused.value)


def test_store_fixture_connects_to_the_test_database_only(store_url: str) -> None:
    with psycopg.connect(store_url) as conn:
        row = conn.execute("SELECT current_database()").fetchone()

    assert row == (TEST_DATABASE,)


def test_a_test_without_the_store_fixture_sees_no_database_url() -> None:
    assert URL_VARIABLE not in os.environ


def test_the_store_fixture_puts_back_only_the_test_database_url(
    store_url: str,
) -> None:
    assert os.environ[URL_VARIABLE] == store_url


def test_the_store_fixture_holds_the_run_lock_against_a_parallel_run(
    store_url: str,
) -> None:
    with psycopg.connect(store_url) as conn:
        row = conn.execute(RUN_LOCK_HOLDERS, [RUN_LOCK]).fetchone()

    assert row == (1,)


@pytest.fixture(scope="session")
def url_seen_by_a_session_fixture() -> bool:
    return URL_VARIABLE in os.environ


def failure_of(call: Callable[[], object]) -> tuple[str, bool]:
    with pytest.raises(pytest.fail.Exception) as failed:
        call()
    return failed.value.msg, failed.value.pytrace


def hold_run_lock(server: str, **options: float) -> None:
    with run_lock(server, **options):
        pass


def test_collection_and_session_fixtures_see_no_database_url(
    store_database: str, url_seen_by_a_session_fixture: bool
) -> None:
    assert URL_SEEN_AT_COLLECTION is False, "a test module saw the URL at collection"
    assert url_seen_by_a_session_fixture is False, "a session fixture saw the URL"


@pytest.mark.parametrize(
    ("url", "code"),
    [
        ("", "DATABASE_URL_MISSING"),
        ("   ", "DATABASE_URL_MISSING"),
        (MALFORMED_URL, "DATABASE_URL_INVALID"),
    ],
    ids=["unset", "blank", "malformed"],
)
def test_server_url_stops_with_a_coded_failure_that_never_shows_the_url(
    monkeypatch: pytest.MonkeyPatch, url: str, code: str
) -> None:
    monkeypatch.setattr(database, "_SERVER_URL", url)

    message, pytrace = failure_of(server_url)

    assert message.startswith(f"{code}: "), message.partition(":")[0]
    assert pytrace is False
    assert MALFORMED_MARKER not in message
    assert URL_VARIABLE in message


def test_run_lock_on_an_unreachable_server_stops_with_database_unavailable() -> None:
    message, pytrace = failure_of(lambda: hold_run_lock(UNREACHABLE_URL))

    assert message.startswith("DATABASE_UNAVAILABLE: "), message.partition(":")[0]
    assert pytrace is False
    assert UNREACHABLE_MARKER not in message
    assert URL_VARIABLE in message
    assert "--workdir" in message
    assert "--network-id pulse-frame-local" in message
    assert "pulse-frame-wiki/ecosystem/store.md" in message


def test_run_lock_held_elsewhere_stops_a_second_run_with_test_database_busy(
    store_url: str,
) -> None:
    started = time.monotonic()

    message, pytrace = failure_of(
        lambda: hold_run_lock(server_url(), wait_s=BUSY_WAIT_S)
    )

    waited = time.monotonic() - started
    assert message.startswith("TEST_DATABASE_BUSY: "), message.partition(":")[0]
    assert pytrace is False
    shows_url = server_url() in message
    assert shows_url is False, "the busy failure printed the database URL"
    assert waited < BUSY_BOUND_S, f"the busy run lock waited {waited:.1f} s"


def test_a_second_connection_cannot_take_the_run_lock_while_the_fixture_holds_it(
    store_url: str,
) -> None:
    with psycopg.connect(server_url(), autocommit=True) as other:
        row = other.execute("SELECT pg_try_advisory_lock(%s)", [RUN_LOCK]).fetchone()

    assert row == (False,)


@pytest.mark.parametrize(
    ("url", "code", "marker"),
    [
        (MALFORMED_URL, "DATABASE_URL_INVALID", MALFORMED_MARKER),
        (UNREACHABLE_URL, "DATABASE_UNAVAILABLE", UNREACHABLE_MARKER),
    ],
    ids=["malformed", "unreachable"],
)
def test_a_run_with_a_bad_database_url_stops_with_its_code_and_never_prints_it(
    url: str, code: str, marker: str
) -> None:
    done = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", FIXTURE_TEST],
        cwd=BACKEND,
        env=with_database_url(url),
        capture_output=True,
        text=True,
        timeout=PROBE_TIMEOUT_S,
        check=False,
    )

    output = done.stdout + done.stderr
    shows_code = code in output
    shows_url = marker in output
    shows_traceback = "Traceback" in output
    assert done.returncode != 0
    assert shows_code, f"no {code} in the run output"
    assert shows_url is False, "the run printed the database URL"
    assert shows_traceback is False
