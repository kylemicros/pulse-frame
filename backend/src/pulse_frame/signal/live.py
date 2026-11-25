import math
from collections import deque

from pulse_frame.signal.beats import Interval
from pulse_frame.signal.checks import check_timestamp
from pulse_frame.signal.hrv import WINDOW_MS, HrvTracker, WindowCheck
from pulse_frame.signal.summary import (
    NO_EARLIER,
    NO_SUMMARY,
    SAMPLE_HOLE_MS,
    NoReading,
    Summary,
    added,
    counted_checks,
    counted_intervals,
    counted_reading,
    decide_no_reading,
    summarise,
    tally,
)
from pulse_frame.signal.tracker import UPDATE_INTERVAL_MS, RegionColours

COUNTED_AFTER_MS = 60_000


class LiveHrv:
    def __init__(self) -> None:
        self._tracker = HrvTracker()
        self._first_ms: float | None = None
        self._newest_ms: float | None = None
        self._last_sample_ms: float | None = None
        self._next_update_ms: float | None = None
        self._kept: deque[Interval] = deque()
        self._kept_until_ms = -math.inf
        self._earlier = NO_EARLIER
        self._had_reading = False
        self._summary: Summary | None = None

    @property
    def counted_from_ms(self) -> float | None:
        if self._first_ms is None:
            return None
        return self._first_ms + COUNTED_AFTER_MS

    def add(
        self, timestamp_ms: float, regions: RegionColours | None, moving: bool = False
    ) -> None:
        check_timestamp(timestamp_ms)
        if self._newest_ms is not None and timestamp_ms <= self._newest_ms:
            return
        if self._first_ms is None:
            self._first_ms = timestamp_ms
        self._newest_ms = timestamp_ms
        self._summary = None
        if regions is not None:
            self._add_sample(timestamp_ms, regions, moving)
        self._drop_older_than_window(timestamp_ms)

    def summary(self) -> Summary:
        if self._summary is None:
            self._summary = self._summarised()
        return self._summary

    def intervals(self) -> list[Interval]:
        unkept = [
            interval
            for interval in self._tracker.intervals()
            if interval.start_ms > self._kept_until_ms
        ]
        return [*self._kept, *unkept]

    def no_reading(self) -> NoReading | None:
        if self._newest_ms is None:
            return None
        return decide_no_reading(
            self.summary(), self._counted_checks(), self._newest_ms, self._had_reading
        )

    def _add_sample(
        self, timestamp_ms: float, regions: RegionColours, moving: bool
    ) -> None:
        after_hole = (
            self._last_sample_ms is not None
            and timestamp_ms - self._last_sample_ms > SAMPLE_HOLE_MS
        )
        if after_hole:
            self._tracker.mark_newest_low_quality()
        self._tracker.add(timestamp_ms, regions, moving=moving, low_quality=after_hole)
        self._last_sample_ms = timestamp_ms
        if self._next_update_ms is None:
            self._next_update_ms = timestamp_ms + UPDATE_INTERVAL_MS
        elif timestamp_ms >= self._next_update_ms:
            self._next_update_ms = timestamp_ms + UPDATE_INTERVAL_MS
            self._keep_settled()
            self._note_reading(timestamp_ms)

    def _keep_settled(self) -> None:
        fresh = [
            interval
            for interval in self._tracker.settled_intervals()
            if interval.start_ms > self._kept_until_ms
        ]
        if fresh:
            self._kept.extend(fresh)
            self._kept_until_ms = fresh[-1].start_ms

    def _note_reading(self, timestamp_ms: float) -> None:
        counted_ms = self.counted_from_ms
        if self._had_reading or counted_ms is None or timestamp_ms < counted_ms:
            return
        reading = counted_reading(self._tracker, timestamp_ms, counted_ms)
        self._had_reading = reading.rmssd_ms is not None and reading.sdnn_ms is not None

    def _drop_older_than_window(self, newest_ms: float) -> None:
        oldest_ms = newest_ms - WINDOW_MS
        dropped: list[Interval] = []
        while self._kept and self._kept[0].end_ms < oldest_ms:
            dropped.append(self._kept.popleft())
        counted_ms = self.counted_from_ms
        if dropped and counted_ms is not None:
            self._earlier = added(
                self._earlier, tally(counted_intervals(dropped, counted_ms))
            )

    def _counted_checks(self) -> list[WindowCheck]:
        counted_ms = self.counted_from_ms
        if counted_ms is None:
            return []
        return counted_checks(self._tracker.window_checks(), counted_ms)

    def _summarised(self) -> Summary:
        counted_ms = self.counted_from_ms
        if self._newest_ms is None or counted_ms is None:
            return NO_SUMMARY
        return summarise(
            counted_intervals(self.intervals(), counted_ms),
            self._newest_ms,
            self._counted_checks(),
            self._earlier,
        )
