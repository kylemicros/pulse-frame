import errno
import hashlib
import http.client
import logging
import os
import ssl
import stat
import sys
import urllib.error
import urllib.request
from pathlib import Path

from pulse_frame.vision.errors import VisionError

log = logging.getLogger(__name__)

MODEL_URL = "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task"
MODEL_SIZE = 3_758_596
MODEL_SHA256 = "64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff"
DOWNLOAD_TIMEOUT_S = 60
FETCH_COMMAND = "uv run python -m pulse_frame.vision.model"
SHOWN_PATH = "backend/models/face_landmarker.task"
SHOWN_PARTIAL = "backend/models/face_landmarker.part"
SHOWN_FOLDER = "backend/models"


def model_path() -> Path:
    return Path(__file__).resolve().parents[3] / "models" / "face_landmarker.task"


def ensure_model(download: bool = True) -> Path:
    path = model_path()
    status = model_status(path)
    if status is not None:
        verify_model(path, status)
        return path
    if not download:
        raise VisionError(
            "MODEL_MISSING",
            f"The face model is not at {SHOWN_PATH}.",
            f"Run {FETCH_COMMAND} in backend/ to download it.",
        )
    fetch_model(path)
    return path


def model_status(path: Path) -> os.stat_result | None:
    try:
        return path.stat()
    except (FileNotFoundError, NotADirectoryError):
        return None
    except OSError as error:
        raise folder_not_searchable(error.strerror or type(error).__name__) from error


def folder_not_searchable(reason: str) -> VisionError:
    return VisionError(
        "MODEL_LOAD_FAILED",
        f"Could not read the face model at {SHOWN_PATH} ({reason}).",
        f"Make sure {SHOWN_FOLDER} is a folder you can open and write to, then run"
        f" {FETCH_COMMAND} in backend/ again.",
    )


def fetch_model(path: Path) -> None:
    content = download_model_bytes()
    check_content(
        "The downloaded face model",
        len(content),
        hashlib.sha256(content).hexdigest(),
        f"The download was discarded; run {FETCH_COMMAND} in backend/ again.",
    )
    write_model(path, content)


def download_model_bytes() -> bytes:
    try:
        with urllib.request.urlopen(MODEL_URL, timeout=DOWNLOAD_TIMEOUT_S) as response:
            return response.read(MODEL_SIZE + 1)
    except (OSError, http.client.HTTPException) as error:
        raise VisionError(
            "MODEL_DOWNLOAD_FAILED",
            f"Could not download the face model to {SHOWN_PATH}:"
            f" {download_failure_reason(error)}.",
            download_failure_action(error),
        ) from error


def download_failure_reason(error: OSError | http.client.HTTPException) -> str:
    if isinstance(error, urllib.error.HTTPError):
        return f"the server answered with HTTP status {error.code}"
    if isinstance(error, urllib.error.URLError):
        return url_error_reason(error.reason)
    if isinstance(error, ssl.SSLError):
        return ssl_error_reason(error)
    if isinstance(error, TimeoutError):
        return "the connection timed out"
    if isinstance(error, http.client.IncompleteRead):
        return "the connection closed before the whole file arrived"
    if isinstance(error, http.client.HTTPException):
        return "the server sent a reply that is not valid HTTP"
    return "the connection broke during the download"


def url_error_reason(reason: object) -> str:
    if isinstance(reason, ssl.SSLError):
        return ssl_error_reason(reason)
    if isinstance(reason, TimeoutError):
        return "the connection timed out"
    return "the network could not be reached"


def ssl_error_reason(error: ssl.SSLError) -> str:
    if isinstance(error, ssl.SSLCertVerificationError):
        return "the secure connection to the server could not be verified"
    return "the secure connection to the server could not be set up"


def download_failure_action(error: OSError | http.client.HTTPException) -> str:
    if is_secure_connection_failure(error):
        return (
            "Make sure the system certificates are installed and up to date (on"
            " macOS with the python.org installer, run Install Certificates.command),"
            f" then run {FETCH_COMMAND} in backend/ again."
        )
    return f"Check the internet connection, then run {FETCH_COMMAND} in backend/ again."


def is_secure_connection_failure(error: OSError | http.client.HTTPException) -> bool:
    if isinstance(error, urllib.error.HTTPError):
        return False
    if isinstance(error, urllib.error.URLError):
        return isinstance(error.reason, ssl.SSLError)
    return isinstance(error, ssl.SSLError)


def write_model(path: Path, content: bytes) -> None:
    partial = path.with_suffix(".part")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        partial.write_bytes(content)
        partial.replace(path)
    except OSError as error:
        raise VisionError(
            "MODEL_WRITE_FAILED",
            f"Could not save the face model to {SHOWN_PATH}"
            f" ({error.strerror or type(error).__name__}).",
            write_failure_action(discard_partial(partial)),
        ) from error


def write_failure_action(partial_left: bool) -> str:
    cleanup = f"delete {SHOWN_PARTIAL}, " if partial_left else ""
    return (
        f"Make sure {SHOWN_FOLDER} is a folder you can write to, {cleanup}then run"
        f" {FETCH_COMMAND} in backend/ again."
    )


def discard_partial(partial: Path) -> bool:
    try:
        if partial.is_file():
            partial.unlink()
    except OSError as error:
        log.warning(
            "event=model_partial_not_removed path=%s error=%r",
            SHOWN_PARTIAL,
            error.strerror or type(error).__name__,
        )
        return True
    return False


def verify_model(path: Path, status: os.stat_result) -> None:
    action = (
        f"Delete {SHOWN_PATH}, then run {FETCH_COMMAND} in backend/ to download"
        " it again."
    )
    subject = f"The face model at {SHOWN_PATH}"
    check_size(subject, regular_file_size(status), action)
    check_digest(subject, file_sha256(path), action)


def regular_file_size(status: os.stat_result) -> int:
    if not stat.S_ISREG(status.st_mode):
        raise model_load_failed(os.strerror(errno.EISDIR))
    return status.st_size


def model_load_failed(reason: str) -> VisionError:
    return VisionError(
        "MODEL_LOAD_FAILED",
        f"Could not read the face model at {SHOWN_PATH} ({reason}).",
        f"Delete {SHOWN_PATH}, then run {FETCH_COMMAND} in backend/ to fetch it again.",
    )


def check_content(subject: str, size: int, digest: str, action: str) -> None:
    check_size(subject, size, action)
    check_digest(subject, digest, action)


def check_size(subject: str, size: int, action: str) -> None:
    if size != MODEL_SIZE:
        raise VisionError(
            "MODEL_CORRUPT",
            f"{subject} has {size} bytes, expected {MODEL_SIZE}.",
            action,
        )


def check_digest(subject: str, digest: str, action: str) -> None:
    if digest != MODEL_SHA256:
        raise VisionError(
            "MODEL_CORRUPT",
            f"{subject} has sha256 {digest}, expected {MODEL_SHA256}.",
            action,
        )


def file_sha256(path: Path) -> str:
    try:
        content = path.read_bytes()
    except OSError as error:
        raise model_load_failed(error.strerror or type(error).__name__) from error
    return hashlib.sha256(content).hexdigest()


def main() -> None:
    try:
        ensure_model()
    except VisionError as error:
        print(f"{error.code}: {error.message} {error.action}", file=sys.stderr)
        raise SystemExit(1) from error
    print(f"{SHOWN_PATH} sha256={MODEL_SHA256}")


if __name__ == "__main__":
    main()
