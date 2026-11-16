import re
import subprocess

import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict

from pulse_frame.store.connection import connect, database_url
from pulse_frame.store.errors import StoreError
from tests.database import (
    MALFORMED_MARKER,
    MALFORMED_URL,
    REPO,
    SUPABASE_IGNORED_FOLDERS,
    TEST_DATABASE,
    UNREACHABLE_URL,
    URL_VARIABLE,
)

STORE_SOURCE = REPO / "backend" / "src" / "pulse_frame" / "store"
REFUSAL_TEXT = "the probe driver refused this connection"
PASSWORD_URL = re.compile(r"postgres(?:ql)?://[^\s/@:]*:[^\s/@]*@", re.IGNORECASE)
PASSWORD_SETTING = re.compile(r"\bpassword\s*=", re.IGNORECASE)
LOCAL_ENDPOINT = re.compile(r"127\.0\.0\.1|localhost|\b5[45]32\d\b", re.IGNORECASE)


def repo_text_files() -> list[str]:
    listed = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=REPO,
        capture_output=True,
        check=True,
    ).stdout.decode("utf-8")
    return sorted(
        path
        for path in listed.split("\0")
        if path
        and not SUPABASE_IGNORED_FOLDERS & set(path.split("/"))
        and (REPO / path).is_file()
        and b"\0" not in (REPO / path).read_bytes()
    )


def psycopg_text(url: str) -> str:
    with pytest.raises(psycopg.ProgrammingError) as parsed:
        conninfo_to_dict(url)
    return str(parsed.value)


@pytest.mark.parametrize("value", [None, "", "   "], ids=["unset", "empty", "blank"])
def test_database_url_without_the_variable_raises_the_coded_error(
    monkeypatch: pytest.MonkeyPatch, value: str | None
) -> None:
    if value is None:
        monkeypatch.delenv(URL_VARIABLE, raising=False)
    else:
        monkeypatch.setenv(URL_VARIABLE, value)

    with pytest.raises(StoreError) as raised:
        database_url()

    assert raised.value.code == "DATABASE_URL_MISSING"
    assert URL_VARIABLE in str(raised.value)
    assert raised.value.action


def test_database_url_returns_the_variable_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(URL_VARIABLE, "host=store.invalid dbname=elsewhere")

    assert database_url() == "host=store.invalid dbname=elsewhere"


def test_connect_reaches_the_database_named_in_the_variable(store_url: str) -> None:
    with connect() as conn:
        assert conn.info.dbname == TEST_DATABASE


def test_connect_without_the_variable_raises_before_connecting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(URL_VARIABLE, raising=False)

    with pytest.raises(StoreError) as raised:
        connect()

    assert raised.value.code == "DATABASE_URL_MISSING"


def test_connect_to_a_malformed_url_raises_url_invalid_without_psycopg_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(URL_VARIABLE, MALFORMED_URL)
    hidden = psycopg_text(MALFORMED_URL)

    with pytest.raises(StoreError) as raised:
        connect()

    error = raised.value
    assert error.code == "DATABASE_URL_INVALID"
    assert error.action
    shown = f"{error} {error.message} {error.action}"
    assert hidden not in shown
    assert MALFORMED_MARKER not in shown
    assert error.__cause__ is None
    assert error.__suppress_context__ is True
    assert error.sqlstate is None


def test_connect_to_an_unreachable_server_raises_database_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(URL_VARIABLE, UNREACHABLE_URL)

    with pytest.raises(StoreError) as raised:
        connect()

    assert raised.value.code == "DATABASE_UNAVAILABLE"
    assert raised.value.action
    assert "--workdir" in raised.value.action
    assert "--network-id pulse-frame-local" in raised.value.action
    assert "pulse-frame-wiki/ecosystem/store.md" in raised.value.action


def test_unavailable_error_drops_the_psycopg_chain_and_shows_sqlstate_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(URL_VARIABLE, UNREACHABLE_URL)

    with pytest.raises(StoreError) as raised:
        connect()

    error = raised.value
    assert error.code == "DATABASE_UNAVAILABLE"
    assert error.__cause__ is None
    assert error.__suppress_context__ is True
    assert error.sqlstate is None
    assert "SQLSTATE none" in error.message


@pytest.mark.parametrize(
    ("refusal", "sqlstate"),
    [
        (psycopg.errors.InvalidPassword(REFUSAL_TEXT), "28P01"),
        (psycopg.errors.TooManyConnections(REFUSAL_TEXT), "53300"),
        (psycopg.InterfaceError(REFUSAL_TEXT), None),
    ],
    ids=["refused-login", "too-many-connections", "interface-error"],
)
def test_connect_refused_by_the_driver_raises_database_unavailable_with_its_sqlstate(
    monkeypatch: pytest.MonkeyPatch, refusal: psycopg.Error, sqlstate: str | None
) -> None:
    def refuse(*args: object, **kwargs: object) -> object:
        raise refusal

    monkeypatch.setenv(URL_VARIABLE, UNREACHABLE_URL)
    monkeypatch.setattr(psycopg, "connect", refuse)

    with pytest.raises(StoreError) as raised:
        connect()

    error = raised.value
    assert error.code == "DATABASE_UNAVAILABLE"
    assert error.sqlstate == sqlstate
    assert f"SQLSTATE {sqlstate or 'none'}" in error.message
    assert error.action
    shown = f"{error} {error.message} {error.action}"
    assert REFUSAL_TEXT not in shown
    assert UNREACHABLE_URL not in shown
    assert error.__cause__ is None
    assert error.__suppress_context__ is True


def test_store_package_holds_no_host_or_port() -> None:
    modules = sorted(STORE_SOURCE.glob("*.py"))
    assert modules, "backend/src/pulse_frame/store holds no module"
    holding = [
        path.relative_to(REPO).as_posix()
        for path in modules
        if LOCAL_ENDPOINT.search(path.read_text(encoding="utf-8"))
    ]
    assert holding == [], f"store modules naming a host or port: {holding}"


def test_no_file_in_the_repo_holds_a_password_url_or_setting() -> None:
    files = repo_text_files()
    assert "supabase/config.toml" in files
    assert "backend/src/pulse_frame/store/connection.py" in files
    assert ".github/workflows/backend.yml" in files
    holding = [
        path
        for path in files
        if PASSWORD_URL.search(
            text := (REPO / path).read_text(encoding="utf-8", errors="replace")
        )
        or PASSWORD_SETTING.search(text)
    ]
    assert holding == [], f"files holding a password URL or setting: {holding}"
