import io
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from pulse_frame.tools import sessions
from tests.database import (
    MALFORMED_MARKER,
    MALFORMED_URL,
    NONE_LEFT,
    READ_ONLY_TRANSACTION,
    SEEDED_COUNTS,
    UNREACHABLE_URL,
    URL_VARIABLE,
    rows_under,
    seed_session,
    with_database_url,
)
from tests.platform.sandboxed import BACKEND, SESSIONS_MODULE
from tests.platform.support import (
    PROBE_MODULE,
    PROBE_TIMEOUT_S,
    read_probe_record,
    run_probe,
)

SKIP_FLAGS = ["--yes", "-y", "--force", "-f", "--no-confirm", "--no-input"]
EMPTY_STORE = "No sessions in the store."
LIST_HINT = "uv run python -m pulse_frame.tools.sessions list"
INTERRUPTED_EXIT = 130
NOTHING_CHANGED = "nothing was changed"
STDOUT_CLOSED = 'exec "$@" >&-'


class TerminalInput(io.StringIO):
    def isatty(self) -> bool:
        return True


def answer(monkeypatch: pytest.MonkeyPatch, typed: str) -> None:
    monkeypatch.setattr("sys.stdin", TerminalInput(typed))


def piped(monkeypatch: pytest.MonkeyPatch, typed: str) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO(typed))


def shows_id(text: str, session_id: object) -> bool:
    return (
        re.search(rf"(?<![\w-]){re.escape(str(session_id))}(?![\w-])", text) is not None
    )


def listed_ids(out: str) -> list[str]:
    return re.findall(r"^\s*(\d+)\b", out, re.MULTILINE)


def interrupted_line(stderr: str) -> str:
    lines = [
        line
        for line in stderr.splitlines()
        if line.startswith("SESSIONS_INTERRUPTED: ")
    ]
    assert len(lines) == 1, f"expected one SESSIONS_INTERRUPTED line, got {len(lines)}"
    return lines[0]


def list_into_a_closed_pipe(url: str) -> subprocess.CompletedProcess[str]:
    return into_a_closed_pipe([SESSIONS_MODULE, "list"], url)


def into_a_closed_pipe(
    module_args: list[str], url: str
) -> subprocess.CompletedProcess[str]:
    reader, writer = os.pipe()
    os.close(reader)
    done = subprocess.run(
        [sys.executable, "-m", *module_args],
        cwd=BACKEND,
        env=with_database_url(url),
        stdout=writer,
        stderr=subprocess.PIPE,
        text=True,
        timeout=PROBE_TIMEOUT_S,
        check=False,
    )
    os.close(writer)
    return done


def with_stdout_closed(
    module_args: list[str], url: str
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["/bin/sh", "-c", STDOUT_CLOSED, "sh", sys.executable, "-m", *module_args],
        cwd=BACKEND,
        env=with_database_url(url),
        stderr=subprocess.PIPE,
        text=True,
        timeout=PROBE_TIMEOUT_S,
        check=False,
    )


def test_list_shows_every_session_id_and_no_empty_store_line(
    store_url: str, capsys: pytest.CaptureFixture[str]
) -> None:
    first = seed_session(store_url)
    second = seed_session(store_url)

    assert sessions.main(["list"]) == 0

    out = capsys.readouterr().out
    listed = listed_ids(out)
    assert sorted(listed) == sorted([str(first), str(second)]), (
        f"expected one line starting with each of the 2 session IDs, "
        f"found {len(listed)} such lines"
    )
    assert EMPTY_STORE not in out


def test_list_of_an_empty_store_says_so_and_shows_no_id(
    store_url: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert sessions.main(["list"]) == 0

    out = capsys.readouterr().out
    assert out.splitlines() == [EMPTY_STORE]
    assert listed_ids(out) == []


def test_list_into_a_reader_that_closed_early_exits_cleanly(store_url: str) -> None:
    seed_session(store_url)
    seed_session(store_url)

    done = list_into_a_closed_pipe(store_url)

    assert done.returncode == 0, f"sessions list exited {done.returncode}"
    assert "Traceback" not in done.stderr
    assert "BrokenPipeError" not in done.stderr


def test_delete_with_the_id_retyped_removes_the_session_and_every_row_under_it(
    store_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    doomed = seed_session(store_url)
    kept = seed_session(store_url)
    assert rows_under(store_url, doomed) == SEEDED_COUNTS
    answer(monkeypatch, f"{doomed}\n")

    assert sessions.main(["delete", str(doomed)]) == 0

    assert rows_under(store_url, doomed) == NONE_LEFT
    assert rows_under(store_url, kept) == SEEDED_COUNTS


def test_delete_asks_for_the_session_id_again(
    store_url: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    target = seed_session(store_url)
    answer(monkeypatch, "")

    sessions.main(["delete", str(target)])

    out = capsys.readouterr().out
    assert shows_id(out, target), "the delete prompt does not name the session ID"
    assert re.search(r"\btype\b", out, re.IGNORECASE), (
        "the delete prompt does not ask the user to type the ID"
    )


@pytest.mark.parametrize(
    "typed", ["\n", "wrong\n", ""], ids=["blank", "different", "end-of-input"]
)
def test_delete_without_the_matching_id_deletes_nothing(
    store_url: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    typed: str,
) -> None:
    target = seed_session(store_url)
    answer(monkeypatch, typed)

    assert sessions.main(["delete", str(target)]) != 0

    captured = capsys.readouterr()
    assert "DELETE_NOT_CONFIRMED" in captured.out + captured.err
    assert rows_under(store_url, target) == SEEDED_COUNTS


def test_delete_from_a_pipe_is_refused_and_deletes_nothing(
    store_url: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    target = seed_session(store_url)
    piped(monkeypatch, f"{target}\n")

    assert sessions.main(["delete", str(target)]) == 1

    captured = capsys.readouterr()
    assert "DELETE_NEEDS_TERMINAL" in captured.err
    assert rows_under(store_url, target) == SEEDED_COUNTS


def test_delete_of_an_unknown_session_reports_it_and_keeps_the_others(
    store_url: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    kept = seed_session(store_url)
    unknown = kept + 1000
    answer(monkeypatch, f"{unknown}\n")

    assert sessions.main(["delete", str(unknown)]) != 0

    captured = capsys.readouterr()
    assert "SESSION_NOT_FOUND" in captured.err
    assert LIST_HINT in captured.err
    assert rows_under(store_url, kept) == SEEDED_COUNTS


def test_delete_refused_by_the_database_shows_its_sqlstate_and_keeps_the_session(
    store_url: str,
    read_only_session: int,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    answer(monkeypatch, f"{read_only_session}\n")

    assert sessions.main(["delete", str(read_only_session)]) == 1

    err = capsys.readouterr().err
    assert "STORE_QUERY_FAILED" in err
    assert READ_ONLY_TRANSACTION in err
    assert LIST_HINT in err
    assert rows_under(store_url, read_only_session) == SEEDED_COUNTS


@pytest.mark.parametrize("flag", SKIP_FLAGS)
def test_delete_has_no_flag_that_skips_the_retyped_id(
    store_url: str, monkeypatch: pytest.MonkeyPatch, flag: str
) -> None:
    target = seed_session(store_url)
    answer(monkeypatch, "")

    with pytest.raises(SystemExit) as stopped:
        sessions.main(["delete", str(target), flag])

    assert stopped.value.code == 2
    assert rows_under(store_url, target) == SEEDED_COUNTS


@pytest.mark.parametrize("argv", [["list"], ["delete", "1"]], ids=["list", "delete"])
def test_command_without_the_database_url_reports_the_coded_error(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    argv: list[str],
) -> None:
    answer(monkeypatch, "1\n")

    assert sessions.main(argv) != 0

    captured = capsys.readouterr()
    assert "DATABASE_URL_MISSING" in captured.out + captured.err


def test_list_against_an_unreachable_server_reports_database_unavailable(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv(URL_VARIABLE, UNREACHABLE_URL)

    assert sessions.main(["list"]) == 1

    assert "DATABASE_UNAVAILABLE" in capsys.readouterr().err


def test_list_with_a_malformed_url_reports_url_invalid_without_psycopg_text(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv(URL_VARIABLE, MALFORMED_URL)

    assert sessions.main(["list"]) == 1

    captured = capsys.readouterr()
    assert "DATABASE_URL_INVALID" in captured.err
    assert MALFORMED_MARKER not in captured.out + captured.err


def test_list_before_the_migration_reports_store_not_migrated(
    unmigrated_store: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert sessions.main(["list"]) == 1

    assert "STORE_NOT_MIGRATED" in capsys.readouterr().err


def test_ctrl_c_at_the_retype_prompt_deletes_nothing_and_says_not_confirmed(
    store_url: str, tmp_path: os.PathLike[str]
) -> None:
    target = seed_session(store_url)

    probe = run_probe(
        "sessions-interrupted",
        tmp_path,
        "at-prompt",
        str(target),
        env=with_database_url(store_url),
    )

    assert probe.record["prompted"] is True
    assert probe.returncode == 1
    assert "DELETE_NOT_CONFIRMED" in probe.stderr
    assert "nothing was" in probe.stderr.lower()
    assert "rolled back" not in probe.stderr.lower()
    assert "Traceback" not in probe.stderr
    assert rows_under(store_url, target) == SEEDED_COUNTS


@pytest.mark.parametrize("moment", ["during-list", "before-prompt"])
def test_ctrl_c_before_anything_is_deleted_exits_130_and_says_nothing_was_changed(
    store_url: str, tmp_path: os.PathLike[str], moment: str
) -> None:
    target = seed_session(store_url)

    probe = run_probe(
        "sessions-interrupted",
        tmp_path,
        moment,
        str(target),
        env=with_database_url(store_url),
    )

    assert probe.record["interrupted_connects"] == 1
    assert probe.record["prompted"] is False
    assert probe.returncode == INTERRUPTED_EXIT
    line = interrupted_line(probe.stderr).lower()
    assert NOTHING_CHANGED in line
    assert "rolled back" not in line
    assert "Traceback" not in probe.stderr
    assert rows_under(store_url, target) == SEEDED_COUNTS


def test_ctrl_c_after_the_delete_executes_rolls_it_back_and_says_so_honestly(
    store_url: str, tmp_path: os.PathLike[str]
) -> None:
    target = seed_session(store_url)

    probe = run_probe(
        "sessions-interrupted",
        tmp_path,
        "after-retype",
        str(target),
        env=with_database_url(store_url),
    )

    assert probe.record["prompted"] is True
    assert probe.record["deletes_executed"] == 1
    assert probe.record["deleted_rows"] == 1
    assert probe.returncode == INTERRUPTED_EXIT
    line = interrupted_line(probe.stderr)
    assert re.search(rf"\bsession {target}\b", line), (
        "the interrupted delete does not name the session"
    )
    assert "commit" in line.lower()
    assert "rolled" in line.lower()
    assert NOTHING_CHANGED not in line.lower()
    assert LIST_HINT in line
    assert "Traceback" not in probe.stderr
    assert rows_under(store_url, target) == SEEDED_COUNTS


def test_delete_with_no_stdin_at_all_is_refused_and_deletes_nothing(
    store_url: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    target = seed_session(store_url)
    monkeypatch.setattr("sys.stdin", None)

    assert sessions.main(["delete", str(target)]) == 1

    captured = capsys.readouterr()
    assert "DELETE_NEEDS_TERMINAL" in captured.err
    assert rows_under(store_url, target) == SEEDED_COUNTS


def test_delete_into_a_reader_that_closed_early_deletes_nothing_and_says_not_confirmed(
    store_url: str, tmp_path: Path
) -> None:
    target = seed_session(store_url)
    record = tmp_path / "sessions-delete.json"

    done = into_a_closed_pipe(
        [PROBE_MODULE, "sessions-delete", str(record), str(target)], store_url
    )

    seen = read_probe_record(record, done.returncode, done.stderr)
    assert seen["prompted"] is False
    assert done.returncode == 1, f"sessions delete exited {done.returncode}"
    assert "DELETE_NOT_CONFIRMED" in done.stderr
    assert "Traceback" not in done.stderr
    assert "BrokenPipeError" not in done.stderr
    assert rows_under(store_url, target) == SEEDED_COUNTS


def test_list_with_stdout_closed_at_start_exits_cleanly(
    store_url: str, tmp_path: Path
) -> None:
    seed_session(store_url)
    seed_session(store_url)
    record = tmp_path / "sessions.json"

    done = with_stdout_closed([PROBE_MODULE, "sessions", str(record)], store_url)

    seen = read_probe_record(record, done.returncode, done.stderr)
    assert seen["stdout_is_none"] is True
    assert "Traceback" not in done.stderr
    assert done.returncode == 0, f"sessions list exited {done.returncode}"


def test_delete_with_stdout_closed_at_start_deletes_nothing_and_says_not_confirmed(
    store_url: str, tmp_path: Path
) -> None:
    target = seed_session(store_url)
    record = tmp_path / "sessions-delete.json"

    done = with_stdout_closed(
        [PROBE_MODULE, "sessions-delete", str(record), str(target)], store_url
    )

    seen = read_probe_record(record, done.returncode, done.stderr)
    assert seen["stdout_is_none"] is True
    assert seen["prompted"] is False, "the ID was read without the prompt being shown"
    assert done.returncode == 1, f"sessions delete exited {done.returncode}"
    assert "DELETE_NOT_CONFIRMED" in done.stderr
    assert "Traceback" not in done.stderr
    assert rows_under(store_url, target) == SEEDED_COUNTS
