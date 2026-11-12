import copy
import logging
import sys

import uvicorn
from uvicorn.config import LOGGING_CONFIG

from pulse_frame.platform.errors import SandboxError
from pulse_frame.platform.sandbox import apply_loopback_sandbox
from pulse_frame.vision.errors import VisionError
from pulse_frame.vision.model import ensure_model

HOST = "127.0.0.1"
PORT = 8000
WS_IMPLEMENTATION = "websockets-sansio"
PROTOCOL_CAP_BYTES = 256 * 1024
TRANSPORT_LOGGERS = ("uvicorn", "uvicorn.error", "websockets")
APP_LOGGER = "pulse_frame"


def main() -> None:
    try:
        prepare()
    except (SandboxError, VisionError) as error:
        print(f"{error.code}: {error.message} {error.action}", file=sys.stderr)
        raise SystemExit(1) from error
    serve()


def prepare() -> None:
    status = apply_loopback_sandbox()
    if not status.applied:
        print(f"{status.code}: {status.reason}", file=sys.stderr)
    ensure_model(download=False)


def serve() -> None:
    from pulse_frame.stream.app import create_app

    config = uvicorn.Config(
        create_app(),
        host=HOST,
        port=PORT,
        reload=False,
        ws=WS_IMPLEMENTATION,
        ws_max_size=PROTOCOL_CAP_BYTES,
        ws_per_message_deflate=False,
        log_config=log_config(),
        log_level=logging.INFO,
    )
    keep_transport_loggers_at_info()
    uvicorn.Server(config).run()


def log_config() -> dict[str, object]:
    config = copy.deepcopy(LOGGING_CONFIG)
    config["loggers"][APP_LOGGER] = {
        "handlers": ["default"],
        "level": "INFO",
        "propagate": False,
    }
    return config


def keep_transport_loggers_at_info() -> None:
    for name in TRANSPORT_LOGGERS:
        logging.getLogger(name).setLevel(logging.INFO)


if __name__ == "__main__":
    main()
