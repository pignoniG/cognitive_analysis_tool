"""Helpers shared by device readers."""

from __future__ import annotations

import csv
import math
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from cwtool.recording import Event


def find(folder: Path, name: str) -> Path | None:
    """First file in ``folder`` whose name contains ``name`` (as the 1.x reader did)."""
    matches = sorted(p for p in folder.iterdir() if p.is_file() and name in p.name)
    return matches[0] if matches else None


def read_event_log(folder: Path, epoch_start: float, utc_offset: float | None = None) -> list[Event]:
    """Read ``*event_log*.csv``: one row per event with columns label, start time, end time, duration (s),
    and from ``tools/event_logger.py`` also the start as Unix time.

    Each event starts at its own time, taken from the Unix column when present (unambiguous), else from
    the ISO start time. ISO times without a zone (logs from the old logger) are read at ``utc_offset``
    (seconds east of UTC, the zone of the computer that recorded, when the device reveals it), else in
    the analysing computer's zone. A row whose start cannot be read follows the previous event."""
    path = find(folder, "event_log")
    if path is None:
        return []
    with open(path, newline="") as f:
        rows = [r for r in csv.reader(f) if r]
    if not rows:
        return []
    header = [h.strip().lower() for h in rows[0]]
    unix_col = next((i for i, h in enumerate(header) if "unix" in h and "start" in h), None)
    zone = timezone(timedelta(seconds=utc_offset)) if utc_offset is not None else None

    def start_of(r) -> float:
        if unix_col is not None and unix_col < len(r) and r[unix_col].strip():
            return float(r[unix_col])
        when = datetime.fromisoformat(r[1].strip())
        if when.tzinfo is None and zone is not None:
            when = when.replace(tzinfo=zone)
        return when.timestamp()

    events = []
    t = None
    for r in rows[1:]:
        try:
            t = start_of(r) - epoch_start
        except (ValueError, IndexError):
            if t is None:
                continue          # no start time to count from yet
        duration = float(r[3])
        events.append(Event(label=r[0], start=t, end=t + duration))
        t += duration
    return events


def utc_offset_from_name(local_name: str, fmt: str, epoch: float) -> float | None:
    """UTC offset (s) of the computer that named a file with its local time ``local_name`` (parsed with
    ``fmt``) at Unix time ``epoch``, rounded to 15 minutes; None if the name does not parse or the
    offset is implausible."""
    try:
        local = datetime.strptime(local_name, fmt).replace(tzinfo=timezone.utc).timestamp()
    except ValueError:
        return None
    offset = round((local - epoch) / 900) * 900
    return float(offset) if abs(offset) <= 14 * 3600 else None


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


def lens_fov(camera_matrix, dist_coefs, resolution: tuple[int, int], fisheye: bool = False):
    """Field of view (deg, h × v) of the whole frame with the lens distortion: the angle between the rays through
    the middle of opposite edges, along the principal point's row and column (OpenCV's radial model, 5 or 8
    coefficients, or the fisheye model). Unlike :func:`pinhole_fov` it covers the edges of a wide-angle lens, and
    for a distortion of zero it is the same. None if the coefficients do not give a usable result."""
    import cv2

    k = np.asarray(camera_matrix, dtype=np.float64).reshape(3, 3)
    d = np.asarray(dist_coefs, dtype=np.float64).ravel()
    w, h = resolution
    cx, cy = float(k[0, 2]), float(k[1, 2])
    pts = np.array([[[0, cy]], [[w, cy]], [[cx, 0]], [[cx, h]]], dtype=np.float64)
    try:
        if fisheye:
            rays = cv2.fisheye.undistortPoints(pts, k, d[:4].reshape(4, 1)).reshape(-1, 2)
        else:
            rays = cv2.undistortPoints(pts, k, d).reshape(-1, 2)
    except cv2.error:
        return None
    if not np.isfinite(rays).all():
        return None
    ray = lambda i: np.array([rays[i, 0], rays[i, 1], 1.0])   # noqa: E731
    angle = lambda a, b: math.degrees(math.acos(np.clip(a @ b / np.linalg.norm(a) / np.linalg.norm(b), -1, 1)))  # noqa: E731
    fov = (angle(ray(0), ray(1)), angle(ray(2), ray(3)))
    return fov if all(1.0 < v < 179.0 for v in fov) else None


def video_resolution(path: Path) -> tuple[int, int]:
    import cv2

    cap = cv2.VideoCapture(str(path))
    size = (int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)))
    cap.release()
    return size
