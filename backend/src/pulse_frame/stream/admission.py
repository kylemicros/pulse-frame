from collections import deque
from dataclasses import dataclass

from pulse_frame.stream.errors import FrameRejectedError

LEAD_SLACK_MS = 2000.0
RATE_LIMIT = 30
RATE_WINDOW_S = 1.0


@dataclass(frozen=True)
class Reference:
    last_ms: int
    last_arrival_s: float


class FrameAdmission:
    def __init__(self) -> None:
        self._reference: Reference | None = None
        self._admitted: deque[float] = deque()

    def check_order(self, capture_ms: int, arrival_s: float) -> None:
        reference = self._reference
        if reference is None:
            return
        lead_ms = capture_ms - reference.last_ms
        allowed_ms = (arrival_s - reference.last_arrival_s) * 1000.0 + LEAD_SLACK_MS
        if lead_ms <= 0:
            raise FrameRejectedError("BAD_TIMESTAMP", "not_increasing")
        if lead_ms > allowed_ms:
            raise FrameRejectedError("BAD_TIMESTAMP", "too_far_ahead")

    def admit(self, arrival_s: float) -> None:
        admitted = self._admitted
        while admitted and arrival_s - admitted[0] >= RATE_WINDOW_S:
            admitted.popleft()
        if len(admitted) >= RATE_LIMIT:
            raise FrameRejectedError("RATE_LIMITED", "rate")
        admitted.append(arrival_s)

    def hand_over(self, capture_ms: int, arrival_s: float) -> None:
        self._reference = Reference(capture_ms, arrival_s)
