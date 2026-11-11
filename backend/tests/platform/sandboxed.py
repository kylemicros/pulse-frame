import atexit
import ctypes
import errno
import importlib
import json
import logging
import os
import runpy
import socket
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, is_dataclass
from importlib.abc import MetaPathFinder
from importlib.machinery import ModuleSpec
from pathlib import Path
from types import TracebackType

BACKEND = Path(__file__).resolve().parents[2]
ASTRONAUT = BACKEND / "tests" / "fixtures" / "astronaut.jpg"
SANDBOX_MODULE = "pulse_frame.platform.sandbox"
LIVE_CHECK_MODULE = "pulse_frame.tools.live_check"
LIBSYSTEM = "/usr/lib/libSystem.B.dylib"
PUBLIC_ENDPOINTS = (
    (socket.AF_INET, ("1.1.1.1", 443)),
    (socket.AF_INET6, ("2001:4860:4860::8888", 443, 0, 0)),
)
NETTOP = "/usr/bin/nettop"
NETTOP_TIMEOUT_S = 15
FLUSH_WAIT_S = 1.0
TRACKED_FRAMES = 5
FRAME_STEP_MS = 33
ECHO = b"pulse"
LIVE_CHECK_SECONDS = "1.1"
NETWORK_AUDIT_EVENTS = ("socket.connect", "socket.getaddrinfo", "socket.sendto")
LIBRARY_LOAD_REFUSAL = "dlopen(/usr/lib/libSystem.B.dylib): image not found"
FAILED_SANDBOX_INIT = -1
REFUSAL_FIRST_LINE = "the test library refused this profile."
REFUSAL_TEXT = (
    REFUSAL_FIRST_LINE + "\nsecond line: (deny network*) is not allowed here.\n"
).encode()
NSURLSESSIOND_SERVICES = (
    "com.apple.nsurlsessiond",
    "com.apple.nsurlsessiond-launchondemand",
)
CONTROL_SERVICE = "com.apple.cfprefsd.daemon"
ABSENT_SERVICE = "com.example.pulse-frame.absent"

Record = dict[str, object]


def outbound_errno(family: socket.AddressFamily, address: tuple[object, ...]) -> str:
    with socket.socket(family, socket.SOCK_STREAM) as probe:
        probe.setblocking(False)
        return errno.errorcode.get(probe.connect_ex(address), "connected")


def outbound_errnos() -> list[str]:
    return [outbound_errno(family, address) for family, address in PUBLIC_ENDPOINTS]


def as_record(status: object) -> Record | None:
    if status is None:
        return None
    assert is_dataclass(status) and not isinstance(status, type)
    return asdict(status)


def current_status() -> Record | None:
    sandbox = sys.modules.get(SANDBOX_MODULE)
    if sandbox is None:
        return None
    return as_record(sandbox.sandbox_status())


def write(path: Path, record: Record) -> None:
    path.write_text(json.dumps(record))


def write_at_exit(path: Path, record: Record) -> None:
    atexit.register(lambda: write(path, record))


def apply_sandbox() -> Record | None:
    sandbox = importlib.import_module(SANDBOX_MODULE)
    return as_record(sandbox.apply_loopback_sandbox())


LIBRARY_CALLS: list[str] = []
FREED_TEXTS: list[str] = []


@dataclass(frozen=True)
class Breakage:
    loads: bool = True
    error_text: bytes | None = None
    missing: tuple[str, ...] = ()


BROKEN_LIBRARIES: dict[str, Breakage] = {
    "load-fails": Breakage(loads=False),
    "init-missing": Breakage(missing=("sandbox_init",)),
    "init-fails-no-text": Breakage(),
    "init-fails-empty-text": Breakage(error_text=b""),
    "init-fails-with-text": Breakage(error_text=REFUSAL_TEXT),
    "free-missing": Breakage(error_text=REFUSAL_TEXT, missing=("sandbox_free_error",)),
}


def symbol_not_found(name: str) -> str:
    return f"dlsym(RTLD_DEFAULT, {name}): symbol not found"


def error_slot(errorbuf: object) -> ctypes.c_char_p:
    slot = getattr(errorbuf, "_obj", None)
    return getattr(errorbuf, "contents", None) if slot is None else slot


class FakeSandboxInit:
    def __init__(self, error_text: bytes | None) -> None:
        self.error_text = error_text

    def __call__(self, profile: object, flags: object, errorbuf: object) -> int:
        LIBRARY_CALLS.append("sandbox_init")
        if self.error_text is not None:
            error_slot(errorbuf).value = self.error_text
        return FAILED_SANDBOX_INIT


class FakeFreeError:
    def __call__(self, text: object) -> None:
        LIBRARY_CALLS.append("sandbox_free_error")
        value = getattr(text, "value", text)
        FREED_TEXTS.append(value.decode() if isinstance(value, bytes) else repr(value))


class FakeLibSystem:
    breakage = Breakage()

    def __init__(self, name: object = None, *args: object, **kwargs: object) -> None:
        LIBRARY_CALLS.append("load")
        if not self.breakage.loads:
            raise OSError(LIBRARY_LOAD_REFUSAL)

    def __getattr__(self, name: str) -> FakeSandboxInit | FakeFreeError:
        if name in self.breakage.missing:
            raise AttributeError(symbol_not_found(name))
        if name == "sandbox_init":
            return FakeSandboxInit(self.breakage.error_text)
        if name == "sandbox_free_error":
            return FakeFreeError()
        raise AttributeError(name)


def break_libsystem(mode: str) -> None:
    FakeLibSystem.breakage = BROKEN_LIBRARIES[mode]
    sys.platform = "darwin"
    ctypes.CDLL = FakeLibSystem


def qualified_name(kind: type[BaseException]) -> str:
    return f"{kind.__module__}.{kind.__qualname__}"


def record_uncaught(path: Path, record: Record) -> None:
    original = sys.excepthook

    def hook(
        kind: type[BaseException], error: BaseException, trace: TracebackType | None
    ) -> None:
        cause = error.__cause__
        record["error_type"] = qualified_name(kind)
        record["cause_type"] = None if cause is None else qualified_name(type(cause))
        record["code"] = getattr(error, "code", None)
        record["message"] = getattr(error, "message", None)
        record["action"] = getattr(error, "action", None)
        record["status_after"] = current_status()
        write(path, record)
        original(kind, error, trace)

    sys.excepthook = hook


class ImportWatcher(MetaPathFinder):
    def __init__(self, name: str, on_import: Callable[[], None]) -> None:
        self.name = name
        self.on_import = on_import

    def find_spec(
        self, fullname: str, path: object = None, target: object = None
    ) -> ModuleSpec | None:
        if fullname == self.name:
            self.on_import()
        return None


def watch_import(name: str, on_import: Callable[[], None]) -> None:
    sys.meta_path.insert(0, ImportWatcher(name, on_import))


class SteppingClock:
    def __init__(self) -> None:
        self.now = 0

    def ms(self) -> int:
        return self.now


class FakeCamera:
    def __init__(
        self, bgr: object, clock: SteppingClock, opened: list[object], index: object
    ) -> None:
        self.bgr = bgr
        self.clock = clock
        self.isOpened = self.is_opened
        opened.append(index)

    def is_opened(self) -> bool:
        return True

    def read(self) -> tuple[bool, object]:
        self.clock.now += FRAME_STEP_MS
        return True, self.bgr.copy()

    def release(self) -> None:
        return None


class RecordCatcher(logging.Handler):
    def __init__(self, records: list[str]) -> None:
        super().__init__(logging.NOTSET)
        self.records = records

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(f"{record.name} {record.levelname} {record.getMessage()}")


def catch_every_log_record() -> list[str]:
    records: list[str] = []
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.addHandler(RecordCatcher(records))
    return records


def mach_lookup(name: str) -> int:
    libsystem = ctypes.CDLL(LIBSYSTEM)
    bootstrap_port = ctypes.c_uint32.in_dll(libsystem, "bootstrap_port")
    look_up = libsystem.bootstrap_look_up
    look_up.argtypes = [
        ctypes.c_uint32,
        ctypes.c_char_p,
        ctypes.POINTER(ctypes.c_uint32),
    ]
    look_up.restype = ctypes.c_int
    service_port = ctypes.c_uint32(0)
    return look_up(bootstrap_port.value, name.encode(), ctypes.byref(service_port))


def astronaut_rgb() -> object:
    import cv2

    return cv2.cvtColor(cv2.imread(str(ASTRONAUT)), cv2.COLOR_BGR2RGB)


def loopback_echo(host: str, family: socket.AddressFamily) -> str:
    with socket.socket(family, socket.SOCK_STREAM) as server:
        server.bind((host, 0))
        server.listen(1)
        with socket.create_connection(server.getsockname()[:2], timeout=5) as client:
            accepted, _ = server.accept()
            with accepted:
                client.sendall(ECHO)
                accepted.sendall(accepted.recv(len(ECHO)))
                return client.recv(len(ECHO)).decode()


def detected_points() -> list[list[float]] | None:
    from pulse_frame.vision.landmarks import FaceTracker
    from pulse_frame.vision.model import ensure_model

    with FaceTracker(ensure_model(download=False)) as tracker:
        face = tracker.detect(astronaut_rgb(), 0)
    return None if face is None else face.points.tolist()


def live_check_record(path: Path) -> Record:
    imports: list[object] = []
    record: Record = {"camera_opened": [], "mediapipe_imports": imports}
    watch_import("mediapipe", lambda: imports.append(current_status()))
    write_at_exit(path, record)
    return record


def run_live_check_on_the_astronaut(record: Record) -> None:
    import cv2

    bgr = cv2.imread(str(ASTRONAUT))
    clock = SteppingClock()
    opened = record["camera_opened"]
    cv2.VideoCapture = lambda index, *args: FakeCamera(bgr, clock, opened, index)
    live_check = importlib.import_module(LIVE_CHECK_MODULE)
    live_check.now_ms = clock.ms
    sys.argv = ["live_check", "--seconds", LIVE_CHECK_SECONDS]
    live_check.main()


def scenario_apply(path: Path) -> None:
    first = apply_sandbox()
    second = apply_sandbox()
    outbound = outbound_errnos() if sys.platform == "darwin" else []
    write(
        path,
        {
            "first": first,
            "second": second,
            "status": current_status(),
            "outbound": outbound,
        },
    )


def scenario_linux(path: Path) -> None:
    sys.platform = "linux"
    write(path, {"returned": apply_sandbox(), "status": current_status()})


def scenario_broken_library(path: Path, mode: str) -> None:
    break_libsystem(mode)
    record: Record = {"library_calls": LIBRARY_CALLS, "freed_texts": FREED_TEXTS}
    record_uncaught(path, record)
    apply_sandbox()
    record["status_after"] = current_status()
    write(path, record)


def scenario_log_records(path: Path, platform: str) -> None:
    records = catch_every_log_record()
    if platform == "linux":
        sys.platform = "linux"
    write(path, {"status": apply_sandbox(), "records": records})


def scenario_mach_lookup(path: Path) -> None:
    record: Record = {"status": apply_sandbox()}
    if sys.platform == "darwin":
        names = (*NSURLSESSIOND_SERVICES, CONTROL_SERVICE, ABSENT_SERVICE)
        record["lookups"] = {name: mach_lookup(name) for name in names}
    write(path, record)


def scenario_loopback_and_detect(path: Path) -> None:
    status = apply_sandbox()
    write(
        path,
        {
            "status": status,
            "echo_v4": loopback_echo("127.0.0.1", socket.AF_INET),
            "echo_v6": loopback_echo("::1", socket.AF_INET6),
            "points": detected_points(),
        },
    )


def scenario_nettop(path: Path) -> None:
    status = apply_sandbox()
    from pulse_frame.vision.landmarks import FaceTracker
    from pulse_frame.vision.model import ensure_model

    rgb = astronaut_rgb()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        with socket.create_connection(server.getsockname(), timeout=5) as client:
            accepted, _ = server.accept()
            with accepted:
                tracker = FaceTracker(ensure_model(download=False))
                faces = sum(
                    tracker.detect(rgb, frame * FRAME_STEP_MS) is not None
                    for frame in range(TRACKED_FRAMES)
                )
                tracker.close()
                time.sleep(FLUSH_WAIT_S)
                record: Record = {
                    "status": status,
                    "faces": faces,
                    "loopback_ports": [
                        server.getsockname()[1],
                        client.getsockname()[1],
                    ],
                }
                if sys.platform == "darwin":
                    shown = subprocess.run(
                        [NETTOP, "-n", "-L", "1", "-p", str(os.getpid())],
                        capture_output=True,
                        text=True,
                        timeout=NETTOP_TIMEOUT_S,
                        check=False,
                    )
                    record["nettop_returncode"] = shown.returncode
                    record["nettop_stdout"] = shown.stdout
                    record["nettop_stderr"] = shown.stderr
                write(path, record)


def scenario_session(path: Path) -> None:
    importlib.import_module("tests.conftest")
    write(
        path,
        {
            "status": current_status(),
            "mediapipe_loaded": "mediapipe" in sys.modules,
        },
    )


def scenario_live_check(path: Path) -> None:
    run_live_check_on_the_astronaut(live_check_record(path))


def scenario_live_check_unsupported(path: Path) -> None:
    record = live_check_record(path)
    platform = sys.platform
    sys.platform = "linux"
    record["unsupported"] = apply_sandbox()
    sys.platform = platform
    run_live_check_on_the_astronaut(record)


CAMERA_FAILURES = {"unavailable": None, "read-failed": TRACKED_FRAMES}


class FailingCamera:
    def __init__(
        self, record: Record, clock: SteppingClock, fail_on_read: int | None
    ) -> None:
        self.record = record
        self.clock = clock
        self.fail_on_read = fail_on_read
        self.isOpened = self.is_opened
        self.bgr = None if fail_on_read is None else astronaut_rgb()[:, :, ::-1]

    def is_opened(self) -> bool:
        return self.fail_on_read is not None

    def read(self) -> tuple[bool, object]:
        self.record["reads"] += 1
        self.clock.now += FRAME_STEP_MS
        if self.record["reads"] >= self.fail_on_read:
            return False, None
        return True, self.bgr.copy()

    def release(self) -> None:
        self.record["released"] += 1


def scenario_live_check_camera_fails(path: Path, failure: str) -> None:
    import cv2

    record: Record = {"camera_opened": [], "reads": 0, "released": 0}
    sandbox = importlib.import_module(SANDBOX_MODULE)
    record["underneath"] = as_record(sandbox.enter_sandbox())
    platform = sys.platform
    sys.platform = "linux"
    record["unsupported"] = apply_sandbox()
    sys.platform = platform
    clock = SteppingClock()
    camera = FailingCamera(record, clock, CAMERA_FAILURES[failure])
    opened = record["camera_opened"]
    cv2.VideoCapture = lambda index, *args: opened.append(index) or camera
    write_at_exit(path, record)
    live_check = importlib.import_module(LIVE_CHECK_MODULE)
    live_check.now_ms = clock.ms
    sys.argv = ["live_check", "--seconds", LIVE_CHECK_SECONDS]
    live_check.main()


def scenario_live_check_broken(path: Path, mode: str) -> None:
    import cv2

    record: Record = {"camera_opened": [], "mediapipe_imports": 0}
    opened = record["camera_opened"]
    cv2.VideoCapture = lambda index, *args: opened.append(index)

    def refuse_mediapipe() -> None:
        record["mediapipe_imports"] = 1
        raise ImportError("mediapipe was imported after the sandbox failed")

    break_libsystem(mode)
    watch_import("mediapipe", refuse_mediapipe)
    write_at_exit(path, record)
    sys.argv = ["live_check", "--seconds", LIVE_CHECK_SECONDS]
    importlib.import_module(LIVE_CHECK_MODULE).main()


def scenario_model_main(path: Path) -> None:
    network: list[str] = []

    def audit(event: str, args: tuple[object, ...]) -> None:
        if event in NETWORK_AUDIT_EVENTS:
            network.append(event)

    sys.addaudithook(audit)
    record: Record = {"network_events": network}

    def finish() -> None:
        importlib.import_module(SANDBOX_MODULE)
        record["status"] = current_status()
        write(path, record)

    atexit.register(finish)
    sys.argv = ["model"]
    runpy.run_module("pulse_frame.vision.model", run_name="__main__")


SCENARIOS: dict[str, Callable[..., None]] = {
    "apply": scenario_apply,
    "linux": scenario_linux,
    "broken-library": scenario_broken_library,
    "log-records": scenario_log_records,
    "mach-lookup": scenario_mach_lookup,
    "loopback-and-detect": scenario_loopback_and_detect,
    "nettop": scenario_nettop,
    "session": scenario_session,
    "live-check": scenario_live_check,
    "live-check-unsupported": scenario_live_check_unsupported,
    "live-check-broken": scenario_live_check_broken,
    "live-check-camera-fails": scenario_live_check_camera_fails,
    "model-main": scenario_model_main,
}


if __name__ == "__main__":
    SCENARIOS[sys.argv[1]](Path(sys.argv[2]), *sys.argv[3:])
