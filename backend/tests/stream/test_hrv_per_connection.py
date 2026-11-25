from dataclasses import dataclass

from pulse_frame.signal.live import COUNTED_AFTER_MS, LiveHrv
from pulse_frame.signal.tracker import RegionColours
from pulse_frame.stream.app import create_app
from tests.stream.wire import (
    FakeClock,
    ProcessorFactory,
    event_loop_running,
    open_stream,
)

FIRST_STARTS_MS = 1_000
SECOND_STARTS_MS = 50_000
STEP_MS = 100
WIRE_FRAMES = 25
DUE_TURNS = 3
SENT_TYPES = {"frame", "pulse", "bpm", "hrv", "error"}


@dataclass(frozen=True)
class Fed:
    t_ms: float
    regions: RegionColours | None
    moving: bool
    on_event_loop: bool


class RecordingLiveHrv(LiveHrv):
    def __init__(self) -> None:
        super().__init__()
        self.fed: list[Fed] = []

    def add(
        self, timestamp_ms: float, regions: RegionColours | None, moving: bool = False
    ) -> None:
        self.fed.append(Fed(timestamp_ms, regions, moving, event_loop_running()))
        super().add(timestamp_ms, regions, moving=moving)


class HrvFactory:
    def __init__(self) -> None:
        self.built: list[RecordingLiveHrv] = []

    def __call__(self) -> RecordingLiveHrv:
        live = RecordingLiveHrv()
        self.built.append(live)
        return live


def test_each_connection_gets_its_own_hrv_tracker_fed_every_frame_off_the_loop(
    factory: ProcessorFactory,
    clock: FakeClock,
    astronaut_jpeg: bytes,
    blank_jpeg: bytes,
) -> None:
    hrv = HrvFactory()
    app = create_app(processor_factory=factory, clock=clock, hrv_factory=hrv)
    first = [(FIRST_STARTS_MS + k * STEP_MS, astronaut_jpeg) for k in range(3)]
    first.append((FIRST_STARTS_MS + 3 * STEP_MS, blank_jpeg))
    second = [(SECOND_STARTS_MS + k * STEP_MS, astronaut_jpeg) for k in range(2)]

    for frames in (first, second):
        with open_stream(app, clock) as stream:
            for t_ms, jpeg in frames:
                stream.send_frame(t_ms, jpeg)

    assert len(hrv.built) == 2
    assert hrv.built[0] is not hrv.built[1]
    for live, frames, processor in zip(
        hrv.built, (first, second), factory.built, strict=True
    ):
        assert [fed.t_ms for fed in live.fed] == [t_ms for t_ms, _ in frames]
        assert [fed.regions for fed in live.fed] == [
            result.colours for result in processor.results
        ]
        assert [fed.moving for fed in live.fed] == [
            result.moving for result in processor.results
        ]
        assert not any(fed.on_event_loop for fed in live.fed)
        assert live.counted_from_ms == frames[0][0] + COUNTED_AFTER_MS
    assert hrv.built[0].fed[-1].regions is None
    assert hrv.built[0].fed[0].regions is not None


def test_the_stream_sends_one_hrv_reply_after_bpm_on_every_due_frame(
    factory: ProcessorFactory, clock: FakeClock, astronaut_jpeg: bytes
) -> None:
    hrv = HrvFactory()
    app = create_app(processor_factory=factory, clock=clock, hrv_factory=hrv)

    with open_stream(app, clock) as stream:
        turns = [
            stream.send_frame(FIRST_STARTS_MS + k * STEP_MS, astronaut_jpeg)
            for k in range(WIRE_FRAMES)
        ]

    sent = {kind for turn in turns for kind in turn.types}
    assert sent <= SENT_TYPES
    assert len(hrv.built[0].fed) == WIRE_FRAMES
    due = [turn.find("bpm") is not None for turn in turns]
    assert due[0]
    assert sum(due) == DUE_TURNS
    for turn, is_due in zip(turns, due, strict=True):
        if not is_due:
            assert turn.types == ["frame"], turn.types
            continue
        assert turn.types == ["pulse", "bpm", "hrv", "frame"], turn.types
        reply = turn.find("hrv")
        assert reply is not None
        assert reply["t"] == turn.reply["t"]
