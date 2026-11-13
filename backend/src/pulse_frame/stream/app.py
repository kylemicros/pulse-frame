import logging
import time
from collections.abc import Callable
from dataclasses import dataclass

import anyio
import anyio.to_thread
from fastapi import FastAPI, WebSocket
from fastapi.telemetry import TelemetryConfig
from starlette.types import Message as AsgiMessage
from starlette.websockets import WebSocketDisconnect

from pulse_frame.monitor.processor import FrameProcessor, FrameResult
from pulse_frame.signal.errors import SignalError
from pulse_frame.signal.tracker import ReadingState
from pulse_frame.stream.admission import FrameAdmission
from pulse_frame.stream.errors import FrameRejectedError, WireCode, is_wire_code
from pulse_frame.stream.frames import (
    capture_ms,
    check_frame_size,
    jpeg_of,
    jpeg_rgb,
)
from pulse_frame.stream.replies import (
    Message,
    bpm_message,
    encoded,
    error_message,
    frame_message,
    pulse_message,
)
from pulse_frame.vision.errors import VisionError
from pulse_frame.vision.model import ensure_model

log = logging.getLogger(__name__)

ENDPOINT = "/ws/stream"
ALLOWED_ORIGINS = frozenset(
    {
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "http://127.0.0.1:4173",
        "http://localhost:4173",
    }
)
POLICY_VIOLATION = 1008
INTERNAL_ERROR = 1011
TRY_AGAIN_LATER = 1013
BUSY_REASON = "ANOTHER_CONNECTION_OPEN"
BUILD_FAILED_REASON = "MODEL_LOAD_FAILED"
READING_INTERVAL_MS = 1000
FALLBACK_PROCESSING_CODE: WireCode = "DETECTION_FAILED"
TELEMETRY_OFF: TelemetryConfig = {
    "tracing": False,
    "metrics": False,
    "logs": False,
    "operation_spans": False,
    "auto_configure": False,
}

type ProcessorFactory = Callable[[], FrameProcessor]
type Clock = Callable[[], float]


def default_processor() -> FrameProcessor:
    return FrameProcessor(ensure_model(download=False))


class ConnectionSlot:
    def __init__(self) -> None:
        self._busy = False

    def claim(self) -> bool:
        if self._busy:
            return False
        self._busy = True
        return True

    def release(self) -> None:
        self._busy = False


@dataclass(frozen=True)
class Processed:
    result: FrameResult
    waveform: list[tuple[float, float]] | None


def process_frame(
    processor: FrameProcessor,
    jpeg: bytes,
    timestamp_ms: int,
    reading_due: bool,
) -> Processed:
    rgb = jpeg_rgb(jpeg)
    result = processor.process(rgb, timestamp_ms)
    return Processed(result, processor.waveform() if reading_due else None)


def wire_code(error: VisionError | SignalError) -> WireCode:
    code = error.code
    return code if is_wire_code(code) else FALLBACK_PROCESSING_CODE


class StreamSession:
    def __init__(
        self, websocket: WebSocket, processor: FrameProcessor, clock: Clock
    ) -> None:
        self._socket = websocket
        self._processor = processor
        self._clock = clock
        self._admission = FrameAdmission()
        self._last_reading_ms: int | None = None
        self._last_state: ReadingState | None = None

    async def run(self) -> None:
        while True:
            message = await self._socket.receive()
            if message["type"] == "websocket.disconnect":
                return
            for reply in await self._answer(message):
                await self._socket.send_text(encoded(reply))

    async def _answer(self, message: AsgiMessage) -> list[Message]:
        arrival_s = self._clock()
        try:
            return await self._accepted(message, arrival_s)
        except FrameRejectedError as rejected:
            log.info(
                "event=frame_rejected code=%s reason=%s",
                rejected.code,
                rejected.reason,
            )
            return [error_message(rejected.code)]

    async def _accepted(self, message: AsgiMessage, arrival_s: float) -> list[Message]:
        data = message.get("bytes")
        if not isinstance(data, bytes):
            raise FrameRejectedError("BAD_FRAME", "text_message")
        check_frame_size(data)
        timestamp_ms = capture_ms(data)
        self._admission.check_order(timestamp_ms, arrival_s)
        self._admission.admit(arrival_s)
        reading_due = self._reading_due(timestamp_ms)
        try:
            processed = await anyio.to_thread.run_sync(
                process_frame,
                self._processor,
                jpeg_of(data),
                timestamp_ms,
                reading_due,
            )
        except (VisionError, SignalError) as error:
            self._admission.hand_over(timestamp_ms, arrival_s)
            code = wire_code(error)
            log.info("event=frame_failed code=%s sent=%s", error.code, code)
            return [error_message(code)]
        self._admission.hand_over(timestamp_ms, arrival_s)
        return self._replies(timestamp_ms, processed)

    def _reading_due(self, timestamp_ms: int) -> bool:
        last = self._last_reading_ms
        return last is None or timestamp_ms - last >= READING_INTERVAL_MS

    def _replies(self, timestamp_ms: int, processed: Processed) -> list[Message]:
        result = processed.result
        self._note_state(result.reading.state)
        replies: list[Message] = []
        if processed.waveform is not None:
            self._last_reading_ms = timestamp_ms
            replies.extend(
                (
                    pulse_message(processed.waveform),
                    bpm_message(timestamp_ms, result.reading),
                )
            )
        replies.append(frame_message(timestamp_ms, result))
        return replies

    def _note_state(self, state: ReadingState) -> None:
        previous, self._last_state = self._last_state, state
        if previous is None or previous == state:
            return
        if state == "acquiring":
            log.info("event=tracker_restarted")
        log.info("event=reading_state_changed state=%s", state)


async def build_processor(factory: ProcessorFactory) -> FrameProcessor:
    with anyio.CancelScope(shield=True):
        return await anyio.to_thread.run_sync(factory)


async def close_processor(processor: FrameProcessor) -> None:
    with anyio.CancelScope(shield=True):
        await anyio.to_thread.run_sync(processor.close)


async def serve_connection(
    websocket: WebSocket, factory: ProcessorFactory, clock: Clock
) -> None:
    try:
        processor = await build_processor(factory)
    except (VisionError, SignalError) as error:
        log.warning("event=processor_build_failed code=%s", error.code)
        await websocket.close(code=INTERNAL_ERROR, reason=BUILD_FAILED_REASON)
        return
    log.info("event=connection_opened")
    try:
        await StreamSession(websocket, processor, clock).run()
    except WebSocketDisconnect:
        log.info("event=client_gone")
    finally:
        await close_processor(processor)
        log.info("event=connection_closed")


def create_app(
    processor_factory: ProcessorFactory | None = None,
    clock: Clock = time.monotonic,
) -> FastAPI:
    factory = default_processor if processor_factory is None else processor_factory
    slot = ConnectionSlot()
    app = FastAPI(
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        telemetry=TELEMETRY_OFF,
    )

    @app.websocket(ENDPOINT)
    async def stream(websocket: WebSocket) -> None:
        if websocket.headers.get("origin") not in ALLOWED_ORIGINS:
            log.info("event=origin_rejected")
            await websocket.close(code=POLICY_VIOLATION)
            return
        if not slot.claim():
            log.info("event=connection_refused reason=%s", BUSY_REASON)
            await websocket.accept()
            await websocket.close(code=TRY_AGAIN_LATER, reason=BUSY_REASON)
            return
        try:
            await websocket.accept()
            await serve_connection(websocket, factory, clock)
        finally:
            slot.release()

    return app
