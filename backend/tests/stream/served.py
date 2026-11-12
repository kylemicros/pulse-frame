import atexit
import base64
import http.client
import importlib
import inspect
import json
import logging
import runpy
import struct
import sys
import threading
from collections.abc import Callable
from pathlib import Path

import pytest

from tests.platform.sandboxed import (
    ASTRONAUT,
    SANDBOX_MODULE,
    Record,
    apply_sandbox_on,
    as_record,
    break_libsystem,
    current_status,
    faked_platform,
    watch_import,
    write,
    write_at_exit,
)

STREAM_MODULE = "pulse_frame.stream"
APP_MODULE = "pulse_frame.stream.app"
PROCESSOR_MODULE = "pulse_frame.monitor.processor"
LANDMARKS_MODULE = "pulse_frame.vision.landmarks"
MODEL_MODULE = "pulse_frame.vision.model"
WATCHED_IMPORTS = ("mediapipe", LANDMARKS_MODULE, PROCESSOR_MODULE, APP_MODULE)
QUIET_LOGGERS = ("uvicorn", "uvicorn.error", "websockets")
ENDPOINT = "/ws/stream"
ALLOWED_ORIGIN = "http://127.0.0.1:5173"
FRAME_TIME_MS = 33.0
PROTOCOL_CAP_BYTES = 262_144
REPLY_WAIT_S = 20.0
CLOSE_WAIT_S = 10.0
TURN_TYPES = ("frame", "error")
MAX_TURN_MESSAGES = 3
WEBSOCKET_KEY_BYTES = 16
PROCESSOR_CLOSED = threading.Event()


def served_frame() -> bytes:
    return struct.pack("<d", FRAME_TIME_MS) + ASTRONAUT.read_bytes()


def note(events: list[object], label: str) -> None:
    events.append([label, current_status()])


def watch_binds(events: list[object]) -> None:
    def audit(event: str, args: tuple[object, ...]) -> None:
        if event == "socket.bind":
            address = args[1]
            shown = list(address[:2]) if isinstance(address, tuple) else str(address)
            events.append(["bind", shown])

    sys.addaudithook(audit)


def watch_sandbox(events: list[object]) -> None:
    sandbox = importlib.import_module(SANDBOX_MODULE)
    original = sandbox.apply_loopback_sandbox

    def apply() -> object:
        status = original()
        events.append(["sandbox", as_record(status)])
        return status

    sandbox.apply_loopback_sandbox = apply


def watch_model_check(events: list[object], missing: Path | None) -> None:
    model = importlib.import_module(MODEL_MODULE)
    original = model.ensure_model
    signature = inspect.signature(original)
    if missing is not None:
        model.model_path = lambda: missing

    def ensure(*args: object, **kwargs: object) -> object:
        bound = signature.bind(*args, **kwargs)
        bound.apply_defaults()
        events.append(["ensure_model", bound.arguments["download"]])
        return original(*args, **kwargs)

    model.ensure_model = ensure


def startup_record(path: Path) -> Record:
    events: list[object] = []
    record: Record = {"events": events}
    for name in WATCHED_IMPORTS:
        watch_import(name, lambda name=name: note(events, f"import {name}"))
    watch_binds(events)
    write_at_exit(path, record)
    return record


def finish_modules(record: Record) -> None:
    record["modules"] = {name: name in sys.modules for name in WATCHED_IMPORTS}


def run_entry_point(record: Record) -> None:
    sys.argv = [STREAM_MODULE]
    atexit.register(finish_modules, record)
    runpy.run_module(STREAM_MODULE, run_name="__main__", alter_sys=True)


def receive_turn(connection: object) -> list[object]:
    replies: list[object] = []
    while not replies or replies[-1].get("type") not in TURN_TYPES:
        if len(replies) >= MAX_TURN_MESSAGES:
            return replies
        replies.append(json.loads(connection.recv(timeout=REPLY_WAIT_S)))
    return replies


def upgrade_status(port: int) -> int:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=REPLY_WAIT_S)
    key = base64.b64encode(bytes(range(WEBSOCKET_KEY_BYTES))).decode()
    connection.request(
        "GET",
        ENDPOINT,
        headers={
            "Upgrade": "websocket",
            "Connection": "Upgrade",
            "Sec-WebSocket-Key": key,
            "Sec-WebSocket-Version": "13",
        },
    )
    status = connection.getresponse().status
    connection.close()
    return status


def full_client(record: Record) -> None:
    from websockets.exceptions import ConnectionClosedError
    from websockets.sync.client import connect

    port = record["listening"][0][1]
    uri = f"ws://127.0.0.1:{port}{ENDPOINT}"
    with connect(
        uri,
        origin=ALLOWED_ORIGIN,
        max_size=None,
        open_timeout=REPLY_WAIT_S,
        close_timeout=CLOSE_WAIT_S,
    ) as connection:
        record["extensions"] = connection.response.headers.get(
            "Sec-WebSocket-Extensions"
        )
        connection.send(served_frame())
        record["replies"] = receive_turn(connection)
        at_cap = struct.pack("<d", FRAME_TIME_MS + 33)
        connection.send(at_cap + bytes(PROTOCOL_CAP_BYTES - len(at_cap)))
        record["at_cap_replies"] = receive_turn(connection)
        over_cap = struct.pack("<d", FRAME_TIME_MS + 66)
        with pytest.raises(ConnectionClosedError) as over_cap_closed:
            connection.send(over_cap + bytes(PROTOCOL_CAP_BYTES + 1 - len(over_cap)))
            connection.recv(timeout=REPLY_WAIT_S)
        record["over_cap_raised"] = type(over_cap_closed.value).__name__
        record["over_cap_close"] = connection.close_code
    record["processor_closed"] = PROCESSOR_CLOSED.wait(CLOSE_WAIT_S)
    record["missing_origin_status"] = upgrade_status(port)


def frame_only_client(record: Record) -> None:
    from websockets.sync.client import connect

    port = record["listening"][0][1]
    uri = f"ws://127.0.0.1:{port}{ENDPOINT}"
    with connect(uri, origin=ALLOWED_ORIGIN, open_timeout=REPLY_WAIT_S) as connection:
        connection.send(served_frame())
        record["replies"] = receive_turn(connection)


def stop_at_once(record: Record) -> None:
    record["served_anyway"] = True


def watch_processor_close(record: Record) -> None:
    processor = sys.modules[PROCESSOR_MODULE]
    original = processor.FrameProcessor.close
    record["processor_closes"] = 0

    def close(self: object) -> None:
        original(self)
        record["processor_closes"] += 1
        PROCESSOR_CLOSED.set()

    processor.FrameProcessor.close = close


def watch_landmarker(events: list[object]) -> None:
    landmarks = sys.modules[LANDMARKS_MODULE]
    original = landmarks.open_landmarker

    def open_landmarker(model: Path) -> object:
        note(events, "landmarker")
        return original(model)

    landmarks.open_landmarker = open_landmarker


def configured(config: object) -> Record:
    return {
        "host": config.host,
        "port": config.port,
        "uds": config.uds,
        "fd": config.fd,
        "ws": config.ws,
        "ws_max_size": config.ws_max_size,
        "ws_per_message_deflate": config.ws_per_message_deflate,
        "reload": config.reload,
    }


def record_client_errors(record: Record) -> None:
    def hook(args: threading.ExceptHookArgs) -> None:
        record["client_error"] = f"{args.exc_type.__name__}: {args.exc_value}"

    threading.excepthook = hook


def run_client(
    server: object, record: Record, client: Callable[[Record], None]
) -> None:
    try:
        client(record)
    finally:
        server.should_exit = True


def instrument_server(record: Record, client: Callable[[Record], None]) -> None:
    import uvicorn

    original = uvicorn.Server.startup

    async def startup(server: uvicorn.Server, sockets: object = None) -> None:
        record["configured"] = configured(server.config)
        record["logger_levels"] = {
            name: logging.getLogger(name).level for name in QUIET_LOGGERS
        }
        server.config.port = 0
        await original(server, sockets=sockets)
        record["listening"] = [
            list(sock.getsockname()[:2])
            for listener in server.servers
            for sock in listener.sockets
        ]
        watch_processor_close(record)
        watch_landmarker(record["events"])
        threading.Thread(
            target=run_client, args=(server, record, client), daemon=True
        ).start()

    uvicorn.Server.startup = startup


class RecordCatcher:
    def __init__(self, record: Record) -> None:
        self.lines: list[str] = []
        record["log_records"] = self.lines

    def install(self) -> None:
        original = logging.Logger.handle
        lines = self.lines

        def handle(logger: logging.Logger, entry: logging.LogRecord) -> None:
            lines.append(
                f"{entry.name} {entry.levelname} {entry.getMessage()} {entry.args!r}"
            )
            original(logger, entry)

        logging.Logger.handle = handle
        logging.getLogger().setLevel(logging.DEBUG)
        for name in QUIET_LOGGERS:
            logging.getLogger(name).setLevel(logging.DEBUG)


def scenario_serve(path: Path) -> None:
    record = startup_record(path)
    RecordCatcher(record).install()
    record_client_errors(record)
    watch_sandbox(record["events"])
    watch_model_check(record["events"], None)
    instrument_server(record, full_client)
    run_entry_point(record)


def scenario_serve_unsupported(path: Path) -> None:
    record = startup_record(path)
    record["unsupported"] = apply_sandbox_on("linux")
    record_client_errors(record)
    watch_sandbox(record["events"])
    watch_model_check(record["events"], None)
    instrument_server(record, frame_only_client)
    run_entry_point(record)


def scenario_broken_sandbox(path: Path, mode: str) -> None:
    record = startup_record(path)
    watch_model_check(record["events"], None)
    instrument_server(record, stop_at_once)
    break_libsystem(mode)
    with faked_platform("darwin"):
        run_entry_point(record)


def scenario_model_missing(path: Path) -> None:
    record = startup_record(path)
    watch_sandbox(record["events"])
    watch_model_check(record["events"], path.parent / "absent" / "model.task")
    instrument_server(record, stop_at_once)
    run_entry_point(record)


def scenario_import_package(path: Path) -> None:
    importlib.import_module(STREAM_MODULE)
    write(path, {"modules": {name: name in sys.modules for name in WATCHED_IMPORTS}})


SCENARIOS: dict[str, Callable[..., None]] = {
    "serve": scenario_serve,
    "serve-unsupported": scenario_serve_unsupported,
    "broken-sandbox": scenario_broken_sandbox,
    "model-missing": scenario_model_missing,
    "import-package": scenario_import_package,
}


if __name__ == "__main__":
    SCENARIOS[sys.argv[1]](Path(sys.argv[2]), *sys.argv[3:])
