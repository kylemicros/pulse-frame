import argparse
import os
import sys
from collections.abc import Sequence

from pulse_frame.platform.errors import SandboxError
from pulse_frame.platform.sandbox import SandboxStatus, apply_loopback_sandbox
from pulse_frame.store.connection import URL_VARIABLE
from pulse_frame.store.errors import StoreError
from pulse_frame.store.sessions import (
    LIST_COMMAND,
    SESSIONS_COMMAND,
    delete_session,
    require_session,
    session_ids,
)

INTERRUPTED_EXIT = 130
SANDBOX_UNSUPPORTED_ACTION = (
    f"The command carries on without that limit, so point {URL_VARIABLE} at"
    " 127.0.0.1 only."
)
SANDBOX_FAILED_ACTION = (
    "Outbound network could not be limited to this machine, so the store was"
    " not opened and nothing was read or deleted. Check that this is macOS with"
    " /usr/lib/libSystem.B.dylib present, then run the command again; if a macOS"
    " update broke sandbox_init, report the code."
)


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog=SESSIONS_COMMAND,
        description=(
            "List the sessions in the local store, or delete one with every row"
            " under it. Run it in backend/. The database is read from"
            f" {URL_VARIABLE}."
        ),
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list", help="print one session ID per line")
    delete = commands.add_parser(
        "delete",
        help="delete one session and every row under it, after you type its ID again",
    )
    delete.add_argument("session_id", type=int, help="the ID shown by `list`")
    return parser.parse_args(argv)


def report(code: str, message: str, action: str) -> None:
    print(f"{code}: {message} {action}", file=sys.stderr)


def report_sandbox(status: SandboxStatus) -> None:
    if not status.applied:
        report(status.code, status.reason, SANDBOX_UNSUPPORTED_ACTION)


def silence_stdout() -> None:
    devnull = os.open(os.devnull, os.O_WRONLY)
    os.dup2(devnull, sys.stdout.fileno())
    os.close(devnull)


def write_out(text: str, end: str = "\n") -> bool:
    if sys.stdout is None:
        return False
    try:
        print(text, end=end, flush=True)
    except BrokenPipeError:
        silence_stdout()
        return False
    return True


def list_sessions() -> int:
    ids = session_ids()
    if not ids:
        write_out("No sessions in the store.")
    for session_id in ids:
        if not write_out(str(session_id)):
            break
    return 0


def has_terminal_input() -> bool:
    return sys.stdin is not None and sys.stdin.isatty()


def show_prompt(session_id: int) -> bool:
    return write_out(
        f"Deleting session {session_id} removes it and every row under it, and"
        f" cannot be undone. Type the session ID {session_id} again to delete it: ",
        end="",
    )


def typed_id() -> str | None:
    try:
        typed = sys.stdin.readline()
    except KeyboardInterrupt:
        typed = None
    write_out("")
    return typed


def delete_and_confirm(session_id: int) -> int:
    try:
        delete_session(session_id)
        write_out(f"Deleted session {session_id} and every row under it.")
    except KeyboardInterrupt:
        report(
            "SESSIONS_INTERRUPTED",
            f"Stopped by Ctrl-C during the delete of session {session_id}. If it"
            " stopped before the commit, the database rolled it back; if not, the"
            " session is gone.",
            f"Run `{LIST_COMMAND}` in backend/ to check whether session"
            f" {session_id} is still there.",
        )
        return INTERRUPTED_EXIT
    return 0


def delete(session_id: int) -> int:
    if not has_terminal_input():
        report(
            "DELETE_NEEDS_TERMINAL",
            "Delete reads the retyped session ID from a terminal only, and its"
            " input is piped, redirected or closed, so nothing was deleted.",
            f"Run `{SESSIONS_COMMAND} delete {session_id}` yourself in a terminal"
            " in backend/ and type the ID when asked.",
        )
        return 1
    require_session(session_id)
    if not show_prompt(session_id):
        report(
            "DELETE_NOT_CONFIRMED",
            "The output closed before the prompt could be shown, so nothing was"
            " deleted.",
            f"Run `{SESSIONS_COMMAND} delete {session_id}` again with its output"
            " on the terminal and type the ID when asked.",
        )
        return 1
    typed = typed_id()
    if typed is None or typed.strip() != str(session_id):
        report(
            "DELETE_NOT_CONFIRMED",
            f"The ID {session_id} was not typed back, so nothing was deleted.",
            "Run the delete again and type the session ID exactly.",
        )
        return 1
    return delete_and_confirm(session_id)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        report_sandbox(apply_loopback_sandbox())
        if args.command == "list":
            return list_sessions()
        return delete(args.session_id)
    except SandboxError as error:
        report(error.code, error.message, SANDBOX_FAILED_ACTION)
        return 1
    except StoreError as error:
        report(error.code, error.message, error.action)
        return 1
    except KeyboardInterrupt:
        report(
            "SESSIONS_INTERRUPTED",
            "Stopped by Ctrl-C before anything was deleted, so nothing was changed.",
            "Run the command again when you are ready.",
        )
        return INTERRUPTED_EXIT


if __name__ == "__main__":
    raise SystemExit(main())
