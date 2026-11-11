from typing import Literal

SandboxErrorCode = Literal["SANDBOX_FAILED"]


class SandboxError(Exception):
    def __init__(self, code: SandboxErrorCode, message: str, action: str) -> None:
        super().__init__(f"{code}: {message} {action}")
        self.code: SandboxErrorCode = code
        self.message = message
        self.action = action
