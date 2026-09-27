"""Helpers shared by device readers."""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

from cwtool.recording import Event


def find(folder: Path, name: str) -> Path | None:
    """First file in ``folder`` whose name contains ``name`` (as the 1.x reader did)."""
    matches = sorted(p for p in folder.iterdir() if p.is_file() and name in p.name)
    return matches[0] if matches else None


def read_event_log(folder: Path, epoch_start: float) -> list[Event]:
    """Read ``*event_log*.csv``: one row per consecutive event with columns
    id, start time (only the first row's is used), -, duration (s)."""
    path = find(folder, "event_log")
    if path is None:
        return []
    with open(path, newline="") as f:
        rows = [r for r in list(csv.reader(f))[1:] if r]
    if not rows:
        return []
    t = datetime.fromisoformat(rows[0][1]).timestamp() - epoch_start
    events = []
    for r in rows:
        duration = float(r[3])
        events.append(Event(label=r[0], start=t, end=t + duration))
        t += duration
    return events
