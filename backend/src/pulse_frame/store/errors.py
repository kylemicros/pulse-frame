from typing import Literal

StoreErrorCode = Literal[
    "DATABASE_URL_MISSING",
    "DATABASE_URL_INVALID",
    "DATABASE_UNAVAILABLE",
    "STORE_NOT_MIGRATED",
    "STORE_QUERY_FAILED",
    "SESSION_NOT_FOUND",
]


class StoreError(Exception):
    def __init__(
        self,
        code: StoreErrorCode,
        message: str,
        action: str,
        sqlstate: str | None = None,
    ) -> None:
        super().__init__(f"{code}: {message} {action}")
        self.code: StoreErrorCode = code
        self.message = message
        self.action = action
        self.sqlstate = sqlstate
