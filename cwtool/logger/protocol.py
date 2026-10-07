"""Protocol files: one ``name,duration`` per line; a blank duration means the phase ends when the operator
moves on. Lines starting with ``#`` are comments. Same format as ``tools/example_protocol.csv``."""

from __future__ import annotations

import csv
from pathlib import Path


def read_protocol(path: Path) -> list[tuple[str, float | None]]:
    """Read a protocol file: a list of (phase name, duration in s or None for until the next phase is called)."""
    events = []
    with open(path, newline="") as f:
        for row in csv.reader(f):
            if not row or not row[0].strip() or row[0].startswith("#"):
                continue
            duration = row[1].strip() if len(row) > 1 else ""
            events.append((row[0].strip(), float(duration) if duration else None))
    return events
