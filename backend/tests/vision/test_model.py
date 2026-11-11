import hashlib
import http.client
import io
import ssl
import stat
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from pulse_frame.vision import model
from pulse_frame.vision.errors import VisionError
from pulse_frame.vision.model import ensure_model
from tests.vision.support import assert_coded

GOOD_BYTES = b"face landmarker test model " * 64
SAME_SIZE_OTHER_BYTES = b"F" + GOOD_BYTES[1:]
SHOWN_PATH = "backend/models/face_landmarker.task"
SHOWN_PARTIAL = "backend/models/face_landmarker.part"
SHOWN_FOLDER = "backend/models"
READ_ONLY = stat.S_IRUSR | stat.S_IXUSR
READ_WRITE = stat.S_IRWXU
NO_ACCESS = 0
FILE_READ_WRITE = stat.S_IRUSR | stat.S_IWUSR


class FailingBody(io.BytesIO):
    def __init__(self, error: BaseException) -> None:
        super().__init__(b"")
        self._error = error

    def read(self, *args: object) -> bytes:
        raise self._error


class FakeServer:
    def __init__(self) -> None:
        self.body: bytes | None = None
        self.error: BaseException | None = None
        self.read_error: BaseException | None = None
        self.urls: list[object] = []
        self.on_request: Callable[[], None] | None = None

    def urlopen(self, url: object, *args: object, **kwargs: object) -> io.BytesIO:
        self.urls.append(url)
        if self.on_request is not None:
            self.on_request()
        if self.error is not None:
            raise self.error
        if self.read_error is not None:
            return FailingBody(self.read_error)
        assert self.body is not None, "The test reached the network unexpectedly."
        return io.BytesIO(self.body)


@pytest.fixture
def target(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "models" / "face_landmarker.task"
    monkeypatch.setattr(model, "model_path", lambda: path)
    monkeypatch.setattr(model, "MODEL_SIZE", len(GOOD_BYTES))
    monkeypatch.setattr(model, "MODEL_SHA256", hashlib.sha256(GOOD_BYTES).hexdigest())
    return path


@pytest.fixture
def server(monkeypatch: pytest.MonkeyPatch) -> FakeServer:
    fake = FakeServer()
    monkeypatch.setattr(urllib.request, "urlopen", fake.urlopen)
    return fake


@pytest.fixture(params=["folder_is_a_file", "read_only_folder"])
def unwritable(request: pytest.FixtureRequest, target: Path) -> Iterator[Path]:
    folder = target.parent
    if request.param == "folder_is_a_file":
        folder.write_bytes(b"")
        yield folder
    else:
        folder.mkdir()
        folder.chmod(READ_ONLY)
        yield folder
        folder.chmod(READ_WRITE)


def files_under(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*") if p.is_file())


def assert_shows_the_repo_path_only(error: VisionError, absolute: Path) -> None:
    text = f"{error.message} {error.action}"
    assert SHOWN_PATH in text
    assert str(absolute) not in text


def write_model(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True)
    path.write_bytes(content)


def assert_says_delete_the_model_then_fetch(error: VisionError) -> None:
    action = error.action.lower()
    assert f"delete {SHOWN_PATH}" in action
    assert model.FETCH_COMMAND in error.action


def assert_says_fix_the_folder_then_fetch_without_deleting(error: VisionError) -> None:
    action = error.action.lower()
    assert SHOWN_FOLDER in error.action
    assert "open" in action
    assert "write" in action
    assert model.FETCH_COMMAND in error.action
    assert "again" in action
    assert "delete" not in action


def test_good_download_is_renamed_into_place_and_leaves_no_partial_file(
    tmp_path: Path, target: Path, server: FakeServer
) -> None:
    server.body = GOOD_BYTES

    path = ensure_model()

    assert path == target
    assert target.read_bytes() == GOOD_BYTES
    assert files_under(tmp_path) == [target]
    assert server.urls == [model.MODEL_URL]


def test_model_is_downloaded_once_and_reused_afterwards(
    target: Path, server: FakeServer
) -> None:
    server.body = GOOD_BYTES

    first = ensure_model()
    second = ensure_model()

    assert first == second == target
    assert len(server.urls) == 1


@pytest.mark.parametrize("download", [True, False])
def test_existing_good_model_is_returned_without_network(
    target: Path, server: FakeServer, download: bool
) -> None:
    write_model(target, GOOD_BYTES)

    assert ensure_model(download=download) == target
    assert server.urls == []


def test_absent_model_without_download_is_model_missing(
    tmp_path: Path, target: Path, server: FakeServer
) -> None:
    with pytest.raises(VisionError) as raised:
        ensure_model(download=False)

    assert_coded(raised.value, "MODEL_MISSING")
    assert server.urls == []
    assert files_under(tmp_path) == []


@pytest.mark.parametrize(
    "content",
    [GOOD_BYTES[:-1], GOOD_BYTES + b"x", SAME_SIZE_OTHER_BYTES],
    ids=["too_short", "too_long", "wrong_hash"],
)
@pytest.mark.parametrize("download", [True, False])
def test_existing_model_with_wrong_size_or_hash_is_model_corrupt(
    target: Path, server: FakeServer, content: bytes, download: bool
) -> None:
    write_model(target, content)

    with pytest.raises(VisionError) as raised:
        ensure_model(download=download)

    assert_coded(raised.value, "MODEL_CORRUPT")
    assert server.urls == []


@pytest.mark.parametrize(
    "content",
    [GOOD_BYTES[:-1], GOOD_BYTES + b"x", SAME_SIZE_OTHER_BYTES],
    ids=["too_short", "too_long", "wrong_hash"],
)
def test_downloaded_model_with_wrong_size_or_hash_is_model_corrupt_and_not_kept(
    tmp_path: Path, target: Path, server: FakeServer, content: bytes
) -> None:
    server.body = content

    with pytest.raises(VisionError) as raised:
        ensure_model()

    assert_coded(raised.value, "MODEL_CORRUPT")
    assert files_under(tmp_path) == []


@pytest.mark.parametrize(
    "network_error",
    [urllib.error.URLError("offline"), TimeoutError("timed out")],
    ids=["url_error", "timeout"],
)
def test_network_error_is_model_download_failed_with_the_cause_chained(
    tmp_path: Path, target: Path, server: FakeServer, network_error: Exception
) -> None:
    server.error = network_error

    with pytest.raises(VisionError) as raised:
        ensure_model()

    assert_coded(raised.value, "MODEL_DOWNLOAD_FAILED")
    assert raised.value.__cause__ is network_error
    assert files_under(tmp_path) == []


@pytest.mark.parametrize(
    "read_error",
    [ConnectionResetError("reset by peer"), http.client.IncompleteRead(b"x", 100)],
    ids=["connection_reset", "incomplete_read"],
)
def test_error_while_reading_the_download_is_model_download_failed(
    tmp_path: Path, target: Path, server: FakeServer, read_error: Exception
) -> None:
    server.read_error = read_error

    with pytest.raises(VisionError) as raised:
        ensure_model()

    assert_coded(raised.value, "MODEL_DOWNLOAD_FAILED")
    assert raised.value.__cause__ is read_error
    assert files_under(tmp_path) == []


def test_model_that_cannot_be_written_is_model_write_failed(
    tmp_path: Path, target: Path, server: FakeServer, unwritable: Path
) -> None:
    server.body = GOOD_BYTES
    before = files_under(tmp_path)

    with pytest.raises(VisionError) as raised:
        ensure_model()

    assert_coded(raised.value, "MODEL_WRITE_FAILED")
    assert isinstance(raised.value.__cause__, OSError)
    assert files_under(tmp_path) == before
    assert not target.exists()


def test_missing_model_message_shows_the_repo_path_not_the_absolute_one(
    target: Path, server: FakeServer
) -> None:
    with pytest.raises(VisionError) as raised:
        ensure_model(download=False)

    assert_shows_the_repo_path_only(raised.value, target)
    assert_shows_the_repo_path_only(raised.value, target.parent)


@pytest.mark.parametrize(
    "content", [GOOD_BYTES[:-1], SAME_SIZE_OTHER_BYTES], ids=["size", "hash"]
)
def test_corrupt_model_message_shows_the_repo_path_not_the_absolute_one(
    target: Path, server: FakeServer, content: bytes
) -> None:
    write_model(target, content)

    with pytest.raises(VisionError) as raised:
        ensure_model(download=False)

    assert_coded(raised.value, "MODEL_CORRUPT")
    assert_shows_the_repo_path_only(raised.value, target)
    assert_shows_the_repo_path_only(raised.value, target.parent)


def test_unwritable_model_message_shows_the_repo_path_not_the_absolute_one(
    target: Path, server: FakeServer, unwritable: Path
) -> None:
    server.body = GOOD_BYTES

    with pytest.raises(VisionError) as raised:
        ensure_model()

    assert_shows_the_repo_path_only(raised.value, target)
    assert_shows_the_repo_path_only(raised.value, unwritable)


def test_real_model_location_is_shown_relative_to_the_repo(
    monkeypatch: pytest.MonkeyPatch, server: FakeServer
) -> None:
    real = model.model_path()
    monkeypatch.setattr(model, "MODEL_SIZE", real.stat().st_size + 1)

    with pytest.raises(VisionError) as raised:
        ensure_model(download=False)

    assert_coded(raised.value, "MODEL_CORRUPT")
    assert_shows_the_repo_path_only(raised.value, real)
    assert_shows_the_repo_path_only(raised.value, real.parents[1])
    assert real.stat().st_size == model.MODEL_SIZE - 1


@pytest.mark.parametrize(
    ("failure", "code"),
    [
        ("offline", "MODEL_DOWNLOAD_FAILED"),
        ("connection_reset", "MODEL_DOWNLOAD_FAILED"),
        ("folder_is_a_file", "MODEL_WRITE_FAILED"),
    ],
)
def test_main_exits_one_with_the_code_on_stderr(
    tmp_path: Path,
    target: Path,
    server: FakeServer,
    capsys: pytest.CaptureFixture[str],
    failure: str,
    code: str,
) -> None:
    server.body = GOOD_BYTES
    if failure == "offline":
        server.error = urllib.error.URLError("offline")
    elif failure == "connection_reset":
        server.read_error = ConnectionResetError("reset by peer")
    else:
        target.parent.write_bytes(b"")

    with pytest.raises(SystemExit) as exited:
        model.main()

    output = capsys.readouterr()
    assert exited.value.code == 1
    assert output.err.startswith(f"{code}: ")
    assert output.out == ""
    assert str(tmp_path) not in output.err


@pytest.fixture
def restore_modes() -> Iterator[list[tuple[Path, int]]]:
    changed: list[tuple[Path, int]] = []
    yield changed
    for path, mode in reversed(changed):
        path.chmod(mode)


def lock(changed: list[tuple[Path, int]], path: Path, mode: int, back: int) -> None:
    path.chmod(mode)
    changed.append((path, back))


def partial_files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*.part"))


@pytest.mark.parametrize("download", [True, False])
def test_existing_model_that_cannot_be_read_is_model_load_failed(
    target: Path,
    server: FakeServer,
    restore_modes: list[tuple[Path, int]],
    download: bool,
) -> None:
    write_model(target, GOOD_BYTES)
    lock(restore_modes, target, NO_ACCESS, FILE_READ_WRITE)

    with pytest.raises(VisionError) as raised:
        ensure_model(download=download)

    assert_coded(raised.value, "MODEL_LOAD_FAILED")
    assert_shows_the_repo_path_only(raised.value, target)
    assert_shows_the_repo_path_only(raised.value, target.parent)
    assert server.urls == []
    assert_says_delete_the_model_then_fetch(raised.value)


@pytest.mark.parametrize("download", [True, False])
def test_directory_in_place_of_the_model_is_model_load_failed(
    target: Path, server: FakeServer, download: bool
) -> None:
    target.mkdir(parents=True)

    with pytest.raises(VisionError) as raised:
        ensure_model(download=download)

    assert_coded(raised.value, "MODEL_LOAD_FAILED")
    assert_shows_the_repo_path_only(raised.value, target)
    assert_shows_the_repo_path_only(raised.value, target.parent)
    assert server.urls == []
    assert_says_delete_the_model_then_fetch(raised.value)
    assert target.is_dir()


def test_existing_model_of_the_wrong_size_is_rejected_without_being_read(
    target: Path, server: FakeServer, restore_modes: list[tuple[Path, int]]
) -> None:
    write_model(target, GOOD_BYTES + b"x")
    lock(restore_modes, target, NO_ACCESS, FILE_READ_WRITE)

    with pytest.raises(VisionError) as raised:
        ensure_model(download=False)

    assert_coded(raised.value, "MODEL_CORRUPT")
    assert str(len(GOOD_BYTES) + 1) in raised.value.message
    assert_shows_the_repo_path_only(raised.value, target)


def test_certificate_failure_says_the_secure_connection_could_not_be_verified(
    tmp_path: Path, target: Path, server: FakeServer
) -> None:
    server.error = urllib.error.URLError(
        ssl.SSLCertVerificationError(1, "certificate verify failed")
    )

    with pytest.raises(VisionError) as raised:
        ensure_model()

    assert_coded(raised.value, "MODEL_DOWNLOAD_FAILED")
    message = raised.value.message.lower()
    assert "secure connection" in message
    assert "verif" in message
    assert "could not be reached" not in message
    assert "certificate" in raised.value.action.lower()
    assert raised.value.__cause__ is server.error
    assert files_under(tmp_path) == []


def test_model_path_taken_by_a_directory_during_download_leaves_no_partial_file(
    tmp_path: Path, target: Path, server: FakeServer
) -> None:
    server.body = GOOD_BYTES

    def directory_appears() -> None:
        target.mkdir(parents=True)
        (target / "keep").write_bytes(b"")

    server.on_request = directory_appears

    with pytest.raises(VisionError) as raised:
        ensure_model()

    assert_coded(raised.value, "MODEL_WRITE_FAILED")
    assert isinstance(raised.value.__cause__, OSError)
    assert partial_files(tmp_path) == []
    assert files_under(tmp_path) == [target / "keep"]
    assert SHOWN_PARTIAL not in raised.value.action


def test_write_failure_is_still_model_write_failed_when_the_partial_cannot_be_removed(
    target: Path, server: FakeServer, restore_modes: list[tuple[Path, int]]
) -> None:
    server.body = GOOD_BYTES
    folder = target.parent
    folder.mkdir()
    partial = target.with_suffix(".part")
    partial.write_bytes(b"")
    lock(restore_modes, folder, READ_ONLY, READ_WRITE)

    with pytest.raises(VisionError) as raised:
        ensure_model()

    assert_coded(raised.value, "MODEL_WRITE_FAILED")
    assert isinstance(raised.value.__cause__, OSError)
    assert partial.read_bytes() == GOOD_BYTES
    assert not target.exists()
    assert_shows_the_repo_path_only(raised.value, target)
    assert_shows_the_repo_path_only(raised.value, folder)
    assert SHOWN_PARTIAL in raised.value.action


def test_bare_ssl_error_says_the_secure_connection_failed_and_names_certificates(
    tmp_path: Path, target: Path, server: FakeServer
) -> None:
    server.error = ssl.SSLError(1, "handshake failure")

    with pytest.raises(VisionError) as raised:
        ensure_model()

    assert_coded(raised.value, "MODEL_DOWNLOAD_FAILED")
    message = raised.value.message.lower()
    assert "secure connection" in message
    assert "could not be reached" not in message
    assert "broke" not in message
    assert "certificate" in raised.value.action.lower()
    assert raised.value.__cause__ is server.error
    assert files_under(tmp_path) == []


@pytest.mark.parametrize("download", [True, False])
@pytest.mark.parametrize("model_inside", [True, False], ids=["model", "empty"])
def test_model_folder_that_cannot_be_searched_is_model_load_failed(
    target: Path,
    server: FakeServer,
    restore_modes: list[tuple[Path, int]],
    download: bool,
    model_inside: bool,
) -> None:
    server.body = GOOD_BYTES
    folder = target.parent
    folder.mkdir()
    if model_inside:
        target.write_bytes(GOOD_BYTES)
    lock(restore_modes, folder, NO_ACCESS, READ_WRITE)

    with pytest.raises(VisionError) as raised:
        ensure_model(download=download)

    assert_coded(raised.value, "MODEL_LOAD_FAILED")
    assert_shows_the_repo_path_only(raised.value, target)
    assert_shows_the_repo_path_only(raised.value, folder)
    assert server.urls == []
    assert_says_fix_the_folder_then_fetch_without_deleting(raised.value)


@pytest.mark.parametrize("already_present", [True, False], ids=["present", "fetched"])
def test_main_prints_only_the_repo_path_and_the_hash_on_success(
    tmp_path: Path,
    target: Path,
    server: FakeServer,
    capsys: pytest.CaptureFixture[str],
    already_present: bool,
) -> None:
    server.body = GOOD_BYTES
    if already_present:
        write_model(target, GOOD_BYTES)

    model.main()

    output = capsys.readouterr()
    digest = hashlib.sha256(GOOD_BYTES).hexdigest()
    assert output.out == f"{SHOWN_PATH} sha256={digest}\n"
    assert output.err == ""
    assert str(tmp_path) not in output.out
    assert target.read_bytes() == GOOD_BYTES
