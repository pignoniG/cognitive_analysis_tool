"""A stand-in sensor for trying the logger without hardware, and for the tests."""

from __future__ import annotations

import math
import time

from cwtool.logger.base import Source


class SimulatedSource(Source):
    """Sine waves at a fixed rate, to try the logger without hardware."""
    kind = "simulated"

    def __init__(self, name: str = "simulated", rate: float = 50.0, channels: int = 2):
        super().__init__(name)
        self.rate = rate
        self.columns = ["unix time (s)"] + [f"ch{i + 1}" for i in range(channels)]
        self.settings = {"rate (Hz)": rate}

    def run(self, emit, stopped) -> None:
        """Emit the sine samples that are due, at the set rate."""
        n, start = 0, time.time()
        while not stopped.is_set():
            due = int((time.time() - start) * self.rate)
            rows = []
            while n < due:
                t = start + n / self.rate
                rows.append((t, *(math.sin(2 * math.pi * (i + 1) * 0.2 * (t - start)) for i in range(len(self.columns) - 1))))
                n += 1
            if rows:
                emit(rows)
            stopped.wait(0.02)
