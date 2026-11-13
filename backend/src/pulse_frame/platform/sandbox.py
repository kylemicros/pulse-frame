import ctypes
import sys
import threading
from dataclasses import dataclass
from typing import Literal

from pulse_frame.platform.errors import SandboxError

LIBSYSTEM = "/usr/lib/libSystem.B.dylib"
RAW_PROFILE_FLAGS = 0
LOOPBACK_ONLY_PROFILE = b"""
(version 1)
(allow default)
(deny network*)
(allow network-bind network-inbound (local ip "localhost:*"))
(allow network-outbound (remote ip "localhost:*"))
(allow network-outbound (control-name "com.apple.network.statistics"))
(deny mach-lookup
  (global-name "com.apple.nsurlsessiond")
  (global-name "com.apple.nsurlsessiond-launchondemand"))
"""
FAILED_ACTION = (
    "Outbound network could not be limited to this machine, so MediaPipe usage"
    " logging is not blocked and nothing was started. Check that this is macOS"
    " with /usr/lib/libSystem.B.dylib present; if a macOS update broke"
    " sandbox_init, block outbound traffic from Python with LuLu instead and"
    " report the code."
)

SandboxCode = Literal["SANDBOX_APPLIED", "SANDBOX_UNSUPPORTED"]


@dataclass(frozen=True)
class SandboxStatus:
    applied: bool
    code: SandboxCode
    reason: str


_lock = threading.Lock()
_applied: SandboxStatus | None = None


def sandbox_status() -> SandboxStatus | None:
    return _applied


def apply_loopback_sandbox() -> SandboxStatus:
    global _applied  # noqa: PLW0603
    with _lock:
        if _applied is not None:
            return _applied
        status = enter_sandbox()
        _applied = status
        return status


def enter_sandbox() -> SandboxStatus:
    platform = sys.platform
    if platform != "darwin":
        return SandboxStatus(
            False,
            "SANDBOX_UNSUPPORTED",
            f"The loopback-only network sandbox needs macOS (sandbox_init); this"
            f" platform is {platform}, so outbound network is not blocked here.",
        )
    library = load_libsystem()
    init_sandbox(library)
    return SandboxStatus(
        True,
        "SANDBOX_APPLIED",
        "macOS sandbox_init blocks this process and its children from connecting"
        " off this machine.",
    )


def load_libsystem() -> ctypes.CDLL:
    try:
        return ctypes.CDLL(LIBSYSTEM)
    except OSError as error:
        raise SandboxError(
            "SANDBOX_FAILED", f"libSystem could not be loaded: {error}.", FAILED_ACTION
        ) from error


def library_function(library: ctypes.CDLL, name: str) -> ctypes._CFuncPtr:
    try:
        return getattr(library, name)
    except AttributeError as error:
        raise SandboxError(
            "SANDBOX_FAILED",
            f"macOS no longer provides {name} ({error}).",
            FAILED_ACTION,
        ) from error


def init_sandbox(library: ctypes.CDLL) -> None:
    sandbox_init = library_function(library, "sandbox_init")
    sandbox_init.argtypes = [
        ctypes.c_char_p,
        ctypes.c_uint64,
        ctypes.POINTER(ctypes.c_char_p),
    ]
    sandbox_init.restype = ctypes.c_int
    errorbuf = ctypes.c_char_p()
    result = sandbox_init(
        LOOPBACK_ONLY_PROFILE, RAW_PROFILE_FLAGS, ctypes.byref(errorbuf)
    )
    if result != 0:
        detail = take_error_text(library, errorbuf)
        raise SandboxError(
            "SANDBOX_FAILED",
            "macOS refused the loopback-only network sandbox"
            f" (sandbox_init returned {result}: {detail}).",
            FAILED_ACTION,
        )


def take_error_text(library: ctypes.CDLL, errorbuf: ctypes.c_char_p) -> str:
    raw = errorbuf.value
    if raw is None:
        return "macOS gave no error text"
    text = raw.decode("utf-8", "replace")
    free_error_text(library, errorbuf)
    return first_line(text) or "macOS gave an empty error text"


def free_error_text(library: ctypes.CDLL, errorbuf: ctypes.c_char_p) -> None:
    sandbox_free_error = library_function(library, "sandbox_free_error")
    sandbox_free_error.argtypes = [ctypes.c_char_p]
    sandbox_free_error.restype = None
    sandbox_free_error(errorbuf)


def first_line(text: str) -> str:
    lines = text.splitlines()
    line = lines[0].strip() if lines else ""
    return line.removesuffix(".")
