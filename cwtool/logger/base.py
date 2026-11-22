"""What a sensor source is, and the clock mapping shared by the ones that carry their own clock."""

from __future__ import annotations

import threading
from collections import deque
from pathlib import Path
from typing import Callable, Iterator

Rows = list  # of tuples: (unix time in s, value, value, ...)
Emit = Callable[[Rows], None]


class Source:
    """One sensor stream, written to its own file.

    Subclasses set ``name`` (file stem, unique in a session) and ``kind``, fill ``columns`` in :meth:`open`
    (first column is always the Unix time in seconds), and implement :meth:`run`.
    """

    kind = "source"
    # Seconds without a row after which the logger takes the device as lost and reconnects; None: never (a device
    # that may legitimately go quiet, or one that recovers by itself, as LSL does).
    stall_seconds: float | None = None

    def __init__(self, name: str):
        self.name = name
        self.columns: list[str] = ["unix time (s)"]
        self.settings: dict = {}
        self.message: str | None = None   # what the device says is wrong while it is still connected, for the table

    def open(self) -> None:
        """Connect to the device and set ``columns``. Blocking; raises on failure. Called again to reconnect after
        :meth:`close`, so it must start from a clean state (the device may have restarted)."""

    def run(self, emit: Emit, stopped: threading.Event) -> None:
        """Deliver rows with ``emit`` until ``stopped`` is set. Runs in its own thread. Raise if the device is lost:
        the logger closes the source and reconnects."""
        stopped.wait()

    def close(self) -> None:
        """Disconnect. May be called more than once, and after a lost connection."""

    def signals(self) -> list[str]:
        """Names of the numeric signals shown on the live plot."""
        return self.columns[1:]

    def signal_values(self, row: tuple) -> Iterator[tuple[str, float]]:
        """(signal, value) pairs of a row, for the live plot. Wide rows: one value per column."""
        for name, v in zip(self.columns[1:], row[1:]):
            yield name, v

    @property
    def filename(self) -> str:
        """Name of the sensor's data file: the sensor's name with .csv."""
        return f"{self.name}.csv"

    def sink(self, folder: Path):
        """A CSV writer for this sensor's file in ``folder``."""
        from cwtool.logger.sinks import CsvSink

        return CsvSink(Path(folder) / self.filename, self.columns)


# Written to session.json ("clock mapping"): files without it come from loggers whose mapping lagged a drifting clock
# (open issue 62) and are repaired when cwtool reads them (cwtool.sensors.repair_lagging_clock).
CLOCK_MAPPING = "lower envelope line over 60 s (2)"


class ClockMapper:
    """Maps a device clock onto the computer's Unix time.

    Samples arrive late by a variable delay (USB, Bluetooth bursts), while the device clock is regular but unrelated
    to Unix time and runs at its own rate (a Nano clone's resonator: 0.3 % slow). The offset ``host - device`` is
    smallest when the delay is smallest, so the offset is taken from the lower envelope of the offsets: the minimum
    of each ``bucket`` seconds over the last ``window`` seconds, and the line below all of them that is closest to
    them (it lies on the lower convex hull, on the edge over the minima's mean device time; Moon et al. 1999). The
    line is evaluated at the current device time, so the drift is followed without lag and without the jitter.

    Until the minima span ``min_span`` seconds the smallest offset so far is used. The minimum over the window alone
    (the first version) was behind a drifting clock by window × drift, 0.19 s for the Nano (open issue 62).
    """

    def __init__(self, window: float = 60.0, bucket: float = 1.0, min_span: float = 5.0):
        self.window, self.bucket, self.min_span = window, bucket, min_span
        self._buckets: deque = deque()  # (bucket index, device time of the minimum, minimum offset)

    def update(self, device_time: float, host_time: float) -> float:
        """Feed one sample; returns the current offset (add it to device time to get Unix time)."""
        offset = host_time - device_time
        index = int(device_time // self.bucket)
        if self._buckets and self._buckets[-1][0] == index:
            if offset < self._buckets[-1][2]:
                self._buckets[-1] = (index, device_time, offset)
        else:
            self._buckets.append((index, device_time, offset))
        while self._buckets and index - self._buckets[0][0] > self.window / self.bucket:
            self._buckets.popleft()
        points = sorted((x, o) for _, x, o in self._buckets)
        if len(points) < 3 or points[-1][0] - points[0][0] < self.min_span:
            return min(o for _, o in points)
        slope, intercept = lower_line(points)
        # never later than this sample's arrival (the line is below every minimum, but not always below this sample
        # when it is not its bucket's minimum)
        return min(intercept + slope * device_time, offset)


def lower_line(points: list) -> tuple[float, float]:
    """(slope, intercept) of the line below all ``points`` (x, y), sorted by x, with the smallest summed distance to
    them: the edge of their lower convex hull over the mean x."""
    hull: list = []
    for p in points:
        while len(hull) >= 2 and _cross(hull[-2], hull[-1], p) <= 0:
            hull.pop()
        hull.append(p)
    if len(hull) == 1:
        return 0.0, hull[0][1]
    mean_x = sum(x for x, _ in points) / len(points)
    for a, b in zip(hull, hull[1:]):
        if b[0] >= mean_x:
            break
    slope = (b[1] - a[1]) / (b[0] - a[0])
    return slope, a[1] - slope * a[0]


def _cross(o, a, b) -> float:
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
