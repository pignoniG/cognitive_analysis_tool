"""Varjo XR-4 recordings made with Varjo Base's eye tracking recorder.

A recording folder holds ``varjo_gaze_output_*.csv`` and the scene video
``varjo_capture_*``, plus an optional ``*event_log*.csv``.

Columns are found by their header names (checked against a Varjo Base export
from April 2026), falling back to the positions of that export for files
without a header.
"""

from __future__ import annotations

import csv
from dataclasses import replace
from pathlib import Path

import numpy as np

from cwtool.devices.common import find as _find, read_event_log, utc_offset_from_name
from cwtool.recording import DeviceProfile, Recording

NAME = "varjo"

# The pupil columns held the radius in older Varjo Base exports (confirmed by Varjo by email), and the iris
# diameter column read a constant half of a typical iris (6.04 mm). A later Varjo Base writes diameters, and
# an iris of 12.2 mm: the reader tells the two apart by the iris (see ``pupil_scale``).
RADIUS_SCALE, DIAMETER_SCALE = 2.0, 1.0
IRIS_DIAMETER_MM = 9.0      # a median iris above this: the file holds diameters, below: radii

PROFILE = DeviceProfile(
    name=NAME,
    pupil_unit="mm",
    pupil_scale=RADIUS_SCALE,       # the older export; each recording sets its own (see ``pupil_scale``)
    luminance_source="display",
    field_of_view=(120.0, 105.0),  # XR-4 nominal
    circular_scene=True,
    native_rate=200.0,
    max_luminance=200.0,            # datasheet: 200 nits
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
    "left_iris": ("left_iris_diameter_in_mm", 38),
    "right_iris": ("right_iris_diameter_in_mm", 42),
}

# The pupil/iris ratio a tracker may stop at: on one recording with dark steps it rose normally to 0.48 and ended at
# 0.50 (about 6.0 mm of the fixed 12 mm iris), with almost nothing above 0.52, in both eyes; another sample (September 2026)
# reached ratios of 0.52 to 0.62. So the cap is not assumed: it is looked for in each recording (:func:`ceiling_found`), and
# only then is a sample at or above CEILING_RATIO a lower bound of the pupil (open issue 52).
CEILING_RATIO = 0.49
CAP_BAND = (0.47, 0.52)          # ratios where a cap shows as a pile-up
ABOVE_BAND = (0.52, 0.62)        # ratios a capped recording does not reach
CAP_MIN_SAMPLES = 100            # samples in the pile-up band below which nothing can be said
CAP_ABOVE_SHARE = 0.02           # a cap: samples above it are at most this share of those at it
# An iris column that varies less than this (mm) over the recording is a constant, not a measurement.
IRIS_CONSTANT_MM = 0.05

# Tracking statuses above this are valid (Varjo Base writes 0 = lost, 2 = tracked).
MIN_STATUS = 1


def _number(text: str) -> float:
    """Parse a CSV value; Varjo Base on Windows writes missing values as "-nan(ind)"."""
    try:
        return float(text)
    except ValueError:
        return float("nan")


def pupil_scale(left_iris: np.ndarray, right_iris: np.ndarray) -> float:
    """The factor from the reported pupil to a diameter in mm, from the iris diameter column: about 6 mm
    (half a typical iris) in exports that hold radii, about 12 mm in those that hold diameters. Without a
    readable iris the older export is assumed."""
    iris = np.concatenate([left_iris, right_iris])
    iris = iris[np.isfinite(iris) & (iris > 0)]
    if len(iris) and float(np.median(iris)) > IRIS_DIAMETER_MM:
        return DIAMETER_SCALE
    return RADIUS_SCALE


def ceiling_found(ratio: np.ndarray) -> bool:
    """Whether the pupil/iris ratios of a recording show a cap: many samples just below CAP_BAND's top and almost none above.
    A recording whose pupil never gets that large, or whose ratios go beyond, has none to speak of."""
    ratio = np.asarray(ratio, dtype=float)
    ratio = ratio[np.isfinite(ratio)]
    at = int(((ratio >= CAP_BAND[0]) & (ratio < CAP_BAND[1])).sum())
    above = int(((ratio >= ABOVE_BAND[0]) & (ratio < ABOVE_BAND[1])).sum())
    return at >= CAP_MIN_SAMPLES and above <= CAP_ABOVE_SHARE * at


def detect(folder: Path) -> bool:
    """True if the folder has a Varjo gaze output file."""
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
        """A column of the gaze file as floats (NaN where a value is missing)."""
        i = cols[key]
        return np.array([_number(r[i]) for r in rows])

    epoch_ns = col("epoch_ns")
    relative_ns = col("relative_ns")
    # Each eye counts where it is tracked itself (a sample with one eye lost keeps the other; the pipeline
    # bridges the missing eye), and only while the gaze as a whole is valid.
    valid = col("status") > MIN_STATUS
    tracked = {eye: valid & (col(f"{eye}_status") > MIN_STATUS) for eye in ("left", "right")}

    def pupil(eye: str) -> np.ndarray:
        """Pupil size of one eye, NaN where the eye is not tracked or the size is not positive."""
        d = col(f"{eye}_pupil")
        with np.errstate(invalid="ignore"):
            ok = tracked[eye] & (d > 0)  # the plausible range is checked in mm by the pipeline
        return np.where(ok, d, np.nan)

    iris = {eye: col(f"{eye}_iris")[tracked[eye]] for eye in ("left", "right")}
    scale = pupil_scale(iris["left"], iris["right"])
    all_iris = np.concatenate(list(iris.values()))
    all_iris = all_iris[np.isfinite(all_iris) & (all_iris > 0)]
    # A constant iris means the pupil in mm is the ratio times that constant: a participant's own iris can rescale it.
    fixed_iris = float(np.median(all_iris)) * scale if len(all_iris) and np.ptp(all_iris) < IRIS_CONSTANT_MM else None

    def ratios(eye: str, size: np.ndarray):
        """The eye's pupil/iris ratio where it has a pupil (NaN elsewhere); None when the file has no ratio column."""
        i = index.get(f"{eye}_pupil_iris_diameter_ratio")
        if i is None:
            return None
        ratio = np.array([_number(r[i]) if i < len(r) else float("nan") for r in rows])
        return np.where(np.isfinite(size), ratio, np.nan)

    prefix = {"right": "right", "combined": "combined"}.get(gaze_eye, "left")
    px, py = col(f"{prefix}_x"), col(f"{prefix}_y")
    # Projected gaze is in [-1, 1] with y up; convert to [0, 1] with y down.
    gaze = np.column_stack([(px + 1) / 2, 1 - (py + 1) / 2])
    gaze_ok = tracked[prefix] if prefix in tracked else tracked["left"] | tracked["right"]
    gaze[~gaze_ok] = np.nan

    time = relative_ns / 1e9
    epoch_start = epoch_ns[0] / 1e9 - time[0]
    # Varjo Base names the file with the recording computer's local time of the first video frame, and
    # the timestamps inside are UTC: together they give that computer's zone, so event logs without a
    # zone read the same wherever they are analysed (open issue 22).
    stamp = gaze_file.stem.replace("varjo_gaze_output_", "")[:19]
    utc_offset = utc_offset_from_name(stamp, "%Y-%m-%d_%H-%M-%S", epoch_start)

    pupil_left, pupil_right = pupil("left"), pupil("right")
    ratio_left, ratio_right = ratios("left", pupil_left), ratios("right", pupil_right)
    known = [r for r in (ratio_left, ratio_right) if r is not None]
    capped = bool(known) and ceiling_found(np.concatenate(known))

    def at_ceiling(ratio):
        if not capped or ratio is None:
            return None
        with np.errstate(invalid="ignore"):
            return np.isfinite(ratio) & (ratio >= CEILING_RATIO)

    return Recording(
        name=folder.name,
        profile=replace(PROFILE, pupil_scale=scale, assumed_iris=fixed_iris),
        folder=folder,
        time=time,
        epoch_start=epoch_start,
        pupil_left=pupil_left,
        pupil_right=pupil_right,
        gaze=gaze,
        scene_video=_find(folder, "varjo_capture_"),
        events=read_event_log(folder, epoch_start, utc_offset),
        censored_left=at_ceiling(ratio_left),
        censored_right=at_ceiling(ratio_right),
    )


def _looks_numeric(row: list[str]) -> bool:
    return bool(row) and all(_number(x) == _number(x) or x.strip().lower().startswith(("-nan", "nan"))
                             for x in row[:3])
