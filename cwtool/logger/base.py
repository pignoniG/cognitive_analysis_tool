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

    def __init__(self, name: str):
        self.name = name
        self.columns: list[str] = ["unix time (s)"]
        self.settings: dict = {}

    def open(self) -> None:
        """Connect to the device and set ``columns``. Blocking; raises on failure."""

    def run(self, emit: Emit, stopped: threading.Event) -> None:
        """Deliver rows with ``emit`` until ``stopped`` is set. Runs in its own thread."""
        stopped.wait()

    def close(self) -> None:
        """Disconnect."""

    def signals(self) -> list[str]:
        """Names of the numeric signals shown on the live plot."""
        return self.columns[1:]

    def signal_values(self, row: tuple) -> Iterator[tuple[str, float]]:
        """(signal, value) pairs of a row, for the live plot. Wide rows: one value per column."""
        for name, v in zip(self.columns[1:], row[1:]):
            yield name, v

    def sink(self, folder: Path):
        from cwtool.logger.sinks import CsvSink

        return CsvSink(Path(folder) / f"{self.name}.csv", self.columns)


class ClockMapper:
    """Maps a device clock onto the computer's Unix time.

    Samples arrive in bursts (Bluetooth), so the receive time is late by a variable delay, while the device
    clock is regular but unrelated to Unix time and drifts. The offset ``host - device`` is smallest when the
    delay is smallest, so the offset is taken as the minimum over the last ``window`` seconds: it follows the
    drift without inheriting the jitter.
    """

    def __init__(self, window: float = 60.0, bucket: float = 1.0):
        self.window, self.bucket = window, bucket
        self._buckets: deque = deque()  # (bucket index, minimum offset)

    def update(self, device_time: float, host_time: float) -> float:
        """Feed one sample; returns the current offset (add it to device time to get Unix time)."""
        offset = host_time - device_time
        index = int(device_time // self.bucket)
        if self._buckets and self._buckets[-1][0] == index:
            self._buckets[-1] = (index, min(self._buckets[-1][1], offset))
        else:
            self._buckets.append((index, offset))
        while self._buckets and index - self._buckets[0][0] > self.window / self.bucket:
            self._buckets.popleft()
        return min(o for _, o in self._buckets)
