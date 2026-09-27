"""Helpers shared by device readers."""

from __future__ import annotations

import csv
import math
import re
from datetime import datetime
from pathlib import Path

import numpy as np

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


# "<label>.begin" / "<label>.end", "<label>_start" / "<label>_stop", "<label> onset" / ...
_BOUNDARY = re.compile(r"^(?P<label>.*?)[\s._-]*(?P<edge>begin|start|onset|end|stop|offset)$", re.IGNORECASE)
_OPENS = {"begin", "start", "onset"}


def events_from_markers(times, names, end: float, ignore=()) -> list[Event]:
    """Turn point markers (time, name) into events.

    A pair of markers named ``<label>.begin`` and ``<label>.end`` (or start/stop,
    onset/offset, separated by ".", "_", "-" or a space) becomes one event. Every
    other marker starts an event that lasts until the next marker, or until ``end``,
    as consecutive protocol phases do. Names in ``ignore`` are skipped.
    """
    skip = {n.lower() for n in ignore}
    marks = sorted((float(t), str(n).strip()) for t, n in zip(times, names) if str(n).strip().lower() not in skip)
    events, open_pairs, points = [], {}, []
    for t, name in marks:
        m = _BOUNDARY.match(name)
        label = m.group("label").strip() if m else ""
        if m and label:
            key = label.lower()
            if m.group("edge").lower() in _OPENS:
                open_pairs[key] = (label, t)
                continue
            if key in open_pairs:
                label, start = open_pairs.pop(key)
                events.append(Event(label, start, t))
                continue
        points.append((t, name))
    points += [(start, label) for label, start in open_pairs.values()]  # begin without end
    points.sort()
    boundaries = [t for t, _ in points] + [end]
    for (t, name), nxt in zip(points, boundaries[1:]):
        events.append(Event(name, t, max(nxt, t)))
    return sorted(events, key=lambda e: e.start)


def bin_samples(times: np.ndarray, values: np.ndarray, t0: float, rate: float, n: int) -> np.ndarray:
    """Average ``values`` (N, ...) into ``n`` bins of 1/rate s starting at t0; empty bins are NaN."""
    values = np.asarray(values, dtype=float)
    shape = (n,) + values.shape[1:]
    out = np.full(shape, np.nan)
    if not len(values):
        return out
    idx = np.round((np.asarray(times) - t0) * rate).astype(int)
    ok = (idx >= 0) & (idx < n) & np.all(np.isfinite(values.reshape(len(values), -1)), axis=1)
    if not ok.any():
        return out
    idx, vals = idx[ok], values[ok].reshape(ok.sum(), -1)
    sums = np.zeros((n, vals.shape[1]))
    counts = np.zeros(n)
    np.add.at(sums, idx, vals)
    np.add.at(counts, idx, 1)
    filled = counts > 0
    out.reshape(n, -1)[filled] = sums[filled] / counts[filled, None]
    return out


def sample_rate(times: np.ndarray, default: float) -> float:
    """Nominal rate (Hz, rounded) from the median sample interval."""
    t = np.sort(np.asarray(times, dtype=float))
    d = np.diff(t)
    d = d[d > 0]
    return float(round(1 / np.median(d))) if len(d) > 10 else default


def pinhole_fov(camera_matrix, resolution: tuple[int, int]) -> tuple[float, float]:
    """Field of view (deg, h × v) of a pinhole camera with ``camera_matrix`` at ``resolution``.
    For a wide-angle lens this is the view near the image centre, narrower than the
    nominal (distorted) field of view."""
    k = np.asarray(camera_matrix, dtype=float).reshape(3, 3)
    w, h = resolution
    return (2 * math.degrees(math.atan(w / 2 / k[0, 0])), 2 * math.degrees(math.atan(h / 2 / k[1, 1])))


def video_resolution(path: Path) -> tuple[int, int]:
    import cv2

    cap = cv2.VideoCapture(str(path))
    size = (int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)))
    cap.release()
    return size
