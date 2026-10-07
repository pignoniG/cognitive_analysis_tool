"""CSV writer for a source."""

from __future__ import annotations

import csv
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
        """Append rows (the time in the first column) and flush the file if a second has passed."""
        for row in rows:
            self._w.writerow([f"{row[0]:.6f}"] + [_fmt(v) for v in row[1:]])
        self.count += len(rows)
        self._flush(rows[-1][0] if rows else 0.0)

    def _flush(self, now: float) -> None:
        if now - self._last_flush >= 1.0:
            self._f.flush()
            self._last_flush = now

    def close(self) -> None:
        """Close the file."""
        if not self._f.closed:
            self._f.close()


def _fmt(v) -> str:
    if isinstance(v, float):
        return f"{v:.9g}"
    return str(v)
