"""Varjo XR-4 recordings made with Varjo Base's eye tracking recorder.

A recording folder holds ``varjo_gaze_output_*.csv`` and the scene video
``varjo_capture_*``, plus an optional ``*event_log*.csv``.

Columns are found by their header names (checked against a Varjo Base export
from April 2026), falling back to the positions of that export for files
without a header.
"""

from __future__ import annotations

import csv
from pathlib import Path

import numpy as np

from cwtool.devices.common import find as _find, read_event_log
from cwtool.recording import DeviceProfile, Recording

NAME = "varjo"

PROFILE = DeviceProfile(
    name=NAME,
    pupil_unit="mm",
    # Varjo Base reports the pupil radius in its diameter columns (confirmed by Varjo by email).
    pupil_scale=2.0,
    luminance_source="display",
    field_of_view=(120.0, 105.0),  # XR-4 nominal
    circular_scene=True,
    native_rate=200.0,
)

# Columns by header name, with the positions of the Varjo Base export used for the pilot
# study as a fallback for files without a header.
COLUMNS = {
    "epoch_ns": ("relative_to_unix_epoch_timestamp", 1),
    "relative_ns": ("relative_to_video_first_frame_timestamp", 2),  # scene video clock
    "status": ("status", 6),
    "left_status": ("left_status", 24),
    "left_x": ("left_projected_x", 25),
    "left_y": ("left_projected_y", 26),
    "right_status": ("right_status", 34),
    "right_x": ("right_projected_x", 35),
    "right_y": ("right_projected_y", 36),
    "combined_x": ("gaze_projected_to_left_view_x", 13),
    "combined_y": ("gaze_projected_to_left_view_y", 14),
    "left_pupil": ("left_pupil_diameter_in_mm", 39),
    "right_pupil": ("right_pupil_diameter_in_mm", 43),
}

# Tracking statuses above this are valid (Varjo Base writes 0 = lost, 2 = tracked).
MIN_STATUS = 1


def _number(text: str) -> float:
    """Parse a CSV value; Varjo Base on Windows writes missing values as "-nan(ind)"."""
    try:
        return float(text)
    except ValueError:
        return float("nan")


def detect(folder: Path) -> bool:
    return folder.is_dir() and _find(folder, "varjo_gaze_output_") is not None


def load(folder: Path, gaze_eye: str = "combined") -> Recording:
    """Load a Varjo recording. ``gaze_eye`` picks which gaze locates the fixation area in the
    scene video, which shows the left eye's view: "combined" (both eyes' gaze projected to the
    left view, the default), "left" (the left eye's projection), or "right" (the right eye's
    projection, which is in the right view and so offset from the capture)."""
    folder = Path(folder)
    gaze_file = _find(folder, "varjo_gaze_output_")
    if gaze_file is None:
        raise FileNotFoundError(f"No varjo_gaze_output_* file in {folder}")

    with open(gaze_file, newline="") as f:
        rows = list(csv.reader(f))
    header = rows[0] if rows and not _looks_numeric(rows[0]) else None
    rows = rows[1:] if header else rows
    index = {h.strip(): k for k, h in enumerate(header)} if header else {}
    cols = {key: index.get(name, fallback) for key, (name, fallback) in COLUMNS.items()}
    width = max(cols.values()) + 1
    rows = [r for r in rows if len(r) >= width]
    if not rows:
        raise ValueError(f"{gaze_file.name} has no data rows")

    def col(key: str) -> np.ndarray:
        i = cols[key]
        return np.array([_number(r[i]) for r in rows])

    epoch_ns = col("epoch_ns")
    relative_ns = col("relative_ns")
    tracked = (col("status") > MIN_STATUS) & (col("left_status") > MIN_STATUS) & (col("right_status") > MIN_STATUS)

    def pupil(key: str) -> np.ndarray:
        d = col(key)
        with np.errstate(invalid="ignore"):
            ok = tracked & (d > 0)  # the plausible range is checked in mm by the pipeline
        return np.where(ok, d, np.nan)

    prefix = {"right": "right", "combined": "combined"}.get(gaze_eye, "left")
    px, py = col(f"{prefix}_x"), col(f"{prefix}_y")
    # Projected gaze is in [-1, 1] with y up; convert to [0, 1] with y down.
    gaze = np.column_stack([(px + 1) / 2, 1 - (py + 1) / 2])
    gaze[~tracked] = np.nan

    time = relative_ns / 1e9
    epoch_start = epoch_ns[0] / 1e9 - time[0]

    return Recording(
        name=folder.name,
        profile=PROFILE,
        folder=folder,
        time=time,
        epoch_start=epoch_start,
        pupil_left=pupil("left_pupil"),
        pupil_right=pupil("right_pupil"),
        gaze=gaze,
        scene_video=_find(folder, "varjo_capture_"),
        events=read_event_log(folder, epoch_start),
    )


def _looks_numeric(row: list[str]) -> bool:
    return bool(row) and all(_number(x) == _number(x) or x.strip().lower().startswith(("-nan", "nan"))
                             for x in row[:3])
