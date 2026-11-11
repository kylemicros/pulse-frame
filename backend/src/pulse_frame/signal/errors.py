from typing import Literal

SignalErrorCode = Literal[
    "NOT_ENOUGH_SAMPLES",
    "BAD_TIMESTAMPS",
    "BAD_VALUES",
    "BAD_SAMPLE_RATE",
    "BAD_BAND",
    "BAD_WINDOW",
]


class SignalError(Exception):
    def __init__(self, code: SignalErrorCode, message: str, action: str) -> None:
        super().__init__(f"{code}: {message} {action}")
        self.code: SignalErrorCode = code
        self.message = message
        self.action = action
