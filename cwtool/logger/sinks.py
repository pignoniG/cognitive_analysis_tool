"""Writers: one CSV per source; the lux logger's hourly files."""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path


class CsvSink:
    """A CSV with a header, flushed at least once a second so a crash loses little."""

    def __init__(self, path: Path, columns: list[str]):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._f = open(self.path, "w", newline="")
        self._w = csv.writer(self._f)
        self._w.writerow(columns)
        self._last_flush = 0.0
        self.count = 0

    def write(self, rows) -> None:
        for row in rows:
            self._w.writerow([f"{row[0]:.6f}"] + [_fmt(v) for v in row[1:]])
        self.count += len(rows)
        self._flush(rows[-1][0] if rows else 0.0)

    def _flush(self, now: float) -> None:
        if now - self._last_flush >= 1.0:
            self._f.flush()
            self._last_flush = now

    def close(self) -> None:
        if not self._f.closed:
            self._f.close()


class HourlyLuxSink:
    """The lux log format of 1.x and the SD card logger, read by :mod:`cwtool.lux`: one CSV per hour named
    ``<month>_<day>_<hour>.csv`` (local time) with rows ``unix time (ms), day, hour, minute, lux``."""

    def __init__(self, folder: Path):
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        self._name = None
        self._f = None
        self._w = None
        self._last_flush = 0.0
        self.count = 0

    def write(self, rows) -> None:
        for t, lux in ((r[0], r[1]) for r in rows):
            when = datetime.fromtimestamp(t)
            name = f"{when.month}_{when.day}_{when.hour}.csv"
            if name != self._name:
                if self._f:
                    self._f.close()
                self._f = open(self.folder / name, "a", newline="")
                self._w = csv.writer(self._f)
                self._name = name
            self._w.writerow([f"{t * 1000:.0f}", when.day, when.hour, when.minute, _fmt(lux)])
        self.count += len(rows)
        if rows and self._f and rows[-1][0] - self._last_flush >= 1.0:
            self._f.flush()
            self._last_flush = rows[-1][0]

    def close(self) -> None:
        if self._f and not self._f.closed:
            self._f.close()


def _fmt(v) -> str:
    if isinstance(v, float):
        return f"{v:.9g}"
    return str(v)
