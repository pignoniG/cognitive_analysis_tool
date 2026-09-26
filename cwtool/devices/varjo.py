"""Varjo XR-4 recordings made with Varjo Base's eye tracking recorder.

A recording folder holds ``varjo_gaze_output_*.csv`` and the scene video
``varjo_capture_*``, plus an optional ``event_log*.csv``.

Columns are read by position, matching the Varjo Base export used for the
pilot study. Check them against a current export before trusting a new
Varjo Base version.
"""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

import numpy as np

from cwtool.recording import Event, Recording

NAME = "varjo"
SAMPLE_RATE = 100.0

COL_EPOCH_NS = 1
COL_RELATIVE_NS = 2  # scene video clock
COL_STATUS = 6
COL_LEFT_STATUS = 24
COL_LEFT_PROJ_X = 25
COL_LEFT_PROJ_Y = 26
COL_RIGHT_STATUS = 34
COL_RIGHT_PROJ_X = 35
COL_RIGHT_PROJ_Y = 36
COL_LEFT_PUPIL_MM = 39
COL_RIGHT_PUPIL_MM = 43

# Tracking statuses above this are valid.
MIN_STATUS = 1
# Pupil diameters outside this range (mm) are treated as tracking errors.
PUPIL_RANGE = (1.0, 9.0)


def _find(folder: Path, prefix: str) -> Path | None:
    matches = sorted(p for p in folder.iterdir() if p.name.startswith(prefix))
    return matches[0] if matches else None


def detect(folder: Path) -> bool:
    return folder.is_dir() and _find(folder, "varjo_gaze_output_") is not None


def load(folder: Path, gaze_eye: str = "left") -> Recording:
    """Load a Varjo recording. ``gaze_eye`` picks which eye's projected gaze
    locates the fixation area in the scene video ("left" or "right")."""
    folder = Path(folder)
    gaze_file = _find(folder, "varjo_gaze_output_")
    if gaze_file is None:
        raise FileNotFoundError(f"No varjo_gaze_output_* file in {folder}")

    with open(gaze_file, newline="") as f:
        rows = list(csv.reader(f))[1:]
    rows = [r for r in rows if len(r) > COL_RIGHT_PUPIL_MM]
    if not rows:
        raise ValueError(f"{gaze_file.name} has no data rows")

    def col(i: int) -> np.ndarray:
        return np.array([float(r[i]) for r in rows])

    epoch_ns = col(COL_EPOCH_NS)
    relative_ns = col(COL_RELATIVE_NS)
    status = col(COL_STATUS)
    left_status = col(COL_LEFT_STATUS)
    right_status = col(COL_RIGHT_STATUS)
    tracked = (status > MIN_STATUS) & (left_status > MIN_STATUS) & (right_status > MIN_STATUS)

    def pupil(i: int) -> np.ndarray:
        d = col(i)
        ok = tracked & (d > PUPIL_RANGE[0]) & (d < PUPIL_RANGE[1])
        return np.where(ok, d, np.nan)

    if gaze_eye == "right":
        px, py = col(COL_RIGHT_PROJ_X), col(COL_RIGHT_PROJ_Y)
    else:
        px, py = col(COL_LEFT_PROJ_X), col(COL_LEFT_PROJ_Y)
    # Projected gaze is in [-1, 1] with y up; convert to [0, 1] with y down.
    gaze = np.column_stack([(px + 1) / 2, 1 - (py + 1) / 2])
    gaze[~tracked] = np.nan

    time = relative_ns / 1e9
    epoch_start = epoch_ns[0] / 1e9 - time[0]

    return Recording(
        name=folder.name,
        device=NAME,
        folder=folder,
        time=time,
        epoch_start=epoch_start,
        pupil_left=pupil(COL_LEFT_PUPIL_MM),
        pupil_right=pupil(COL_RIGHT_PUPIL_MM),
        gaze=gaze,
        sample_rate=SAMPLE_RATE,
        luminance_source="display",
        scene_video=_find(folder, "varjo_capture_"),
        circular_scene=True,
        events=read_event_log(folder, epoch_start),
    )


def read_event_log(folder: Path, epoch_start: float) -> list[Event]:
    """Read ``event_log*.csv``: one row per consecutive event with columns
    id, start time (only the first row's is used), -, duration (s)."""
    path = _find(folder, "event_log")
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
