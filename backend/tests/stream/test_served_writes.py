import os

import pytest

from tests.stream.served import opens_for_writing

FILE = "/srv/example/beat.log"
CACHE = "/srv/example/backend/src/pulse_frame/__pycache__/app.cpython-313.pyc"
READ_ONLY = os.O_RDONLY


@pytest.mark.parametrize(
    ("args", "writes"),
    [
        pytest.param((FILE, "w", READ_ONLY), True, id="open_w"),
        pytest.param((FILE, "a", READ_ONLY), True, id="open_a"),
        pytest.param((FILE, "r+", READ_ONLY), True, id="open_r_plus"),
        pytest.param((FILE, "xb", READ_ONLY), True, id="open_x"),
        pytest.param((FILE, "r", READ_ONLY), False, id="open_r"),
        pytest.param((FILE, "rb", READ_ONLY), False, id="open_rb"),
        pytest.param((FILE, None, os.O_WRONLY | os.O_CREAT), True, id="os_open_create"),
        pytest.param((FILE, None, os.O_RDWR), True, id="os_open_read_write"),
        pytest.param(
            (FILE, None, os.O_WRONLY | os.O_APPEND), True, id="os_open_append"
        ),
        pytest.param((FILE, None, READ_ONLY), False, id="os_open_read"),
        pytest.param((os.devnull, "w", READ_ONLY), False, id="devnull"),
        pytest.param((os.devnull, None, os.O_WRONLY), False, id="os_open_devnull"),
        pytest.param((CACHE, "wb", READ_ONLY), False, id="pycache"),
        pytest.param(
            (CACHE, None, os.O_WRONLY | os.O_CREAT), False, id="os_open_pycache"
        ),
        pytest.param((7, "w", READ_ONLY), False, id="file_descriptor"),
    ],
)
def test_the_probe_counts_only_opens_that_could_write_a_file(
    args: tuple[object, ...], writes: bool
) -> None:
    assert opens_for_writing(args) is writes
