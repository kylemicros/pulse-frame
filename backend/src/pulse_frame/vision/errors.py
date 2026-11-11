from typing import Literal

VisionErrorCode = Literal[
    "MODEL_MISSING",
    "MODEL_DOWNLOAD_FAILED",
    "MODEL_CORRUPT",
    "MODEL_WRITE_FAILED",
    "MODEL_LOAD_FAILED",
    "BAD_FRAME",
    "BAD_TIMESTAMP",
    "TRACKER_CLOSED",
    "DETECTION_FAILED",
    "CAMERA_UNAVAILABLE",
    "CAMERA_READ_FAILED",
]


class VisionError(Exception):
    def __init__(self, code: VisionErrorCode, message: str, action: str) -> None:
        super().__init__(f"{code}: {message} {action}")
        self.code: VisionErrorCode = code
        self.message = message
        self.action = action
