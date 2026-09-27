"""Pupil Labs Pupil Core recordings, after export with Pupil Player.

A recording folder holds ``info.player.json``, ``world.mp4``,
``world_timestamps.npy`` and ``exports/<n>/`` with ``pupil_positions.csv`` and
``gaze_positions.csv`` (the newest export is used). Lux sensor logs are looked
for in the recording folder or a ``lux`` subfolder, or passed as ``lux_folder``.

Pupil diameter: the 3D eye model's ``diameter_3d`` (mm) when present, otherwise
the 2D ``diameter`` in eye-camera pixels, which the pipeline scales to mm by
matching the mean expected pupil (2021 method). Samples below the confidence
threshold recommended by Pupil Labs (0.6) are dropped. eye0 is the right eye,
eye1 the left.
"""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path
from typing import Optional

import numpy as np

from cwtool import lux
from cwtool.devices.common import read_event_log
from cwtool.recording import DeviceProfile, Recording

NAME = "pupil_core"
MIN_CONFIDENCE = 0.6
# The eye adapts to the whole binocular visual field, not just the scene camera's view
# (Pignoni et al. 2021).
ADAPTING_FIELD = (200.0, 135.0)
# Used when world.intrinsics cannot be read: the 1280x720 wide-angle scene camera.
DEFAULT_CAMERA_FOV = (75.0, 48.5)


def _export_dir(folder: Path) -> Optional[Path]:
    exports = folder / "exports"
    if not exports.is_dir():
        return None
    candidates = [p for p in exports.iterdir() if p.is_dir() and (p / "pupil_positions.csv").exists()]
    numbered = sorted((p for p in candidates if p.name.isdigit()), key=lambda p: int(p.name))
    return (numbered or sorted(candidates))[-1] if candidates else None


def detect(folder: Path) -> bool:
    folder = Path(folder)
    return (folder / "info.player.json").exists() and _export_dir(folder) is not None


def camera_fov(folder: Path, resolution: tuple[int, int]) -> tuple[float, float]:
    """Scene camera field of view (deg) from world.intrinsics (pinhole approximation)."""
    try:
        import msgpack

        data = msgpack.unpackb((folder / "world.intrinsics").read_bytes(), raw=False)
        cam = data[str(tuple(resolution))]
        k = cam["camera_matrix"]
        w, h = resolution
        return (2 * math.degrees(math.atan(w / 2 / k[0][0])), 2 * math.degrees(math.atan(h / 2 / k[1][1])))
    except Exception:
        return DEFAULT_CAMERA_FOV


def _video_resolution(path: Path) -> tuple[int, int]:
    import cv2

    cap = cv2.VideoCapture(str(path))
    size = (int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)))
    cap.release()
    return size


def _bin(times: np.ndarray, values: np.ndarray, t0: float, rate: float, n: int) -> np.ndarray:
    """Average ``values`` (N, ...) into ``n`` bins of 1/rate s starting at t0; empty bins are NaN."""
    values = np.asarray(values, dtype=float)
    shape = (n,) + values.shape[1:]
    out = np.full(shape, np.nan)
    idx = np.round((times - t0) * rate).astype(int)
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


def load(folder: Path, lux_folder: Optional[Path] = None, min_confidence: float = MIN_CONFIDENCE,
         pupil_measure: str = "auto") -> Recording:
    """Load a Pupil Core recording. ``pupil_measure`` is "3d" (mm), "2d" (px) or "auto"."""
    folder = Path(folder)
    export = _export_dir(folder)
    if export is None:
        raise FileNotFoundError(f"No Pupil Player export with pupil_positions.csv in {folder / 'exports'}")
    info = json.loads((folder / "info.player.json").read_text())
    world_ts = np.load(folder / "world_timestamps.npy")
    t_zero = float(world_ts[0])       # scene video start, on Pupil's clock
    epoch_start = float(info["start_time_system_s"]) + (t_zero - float(info["start_time_synced_s"]))

    # Pupil
    with open(export / "pupil_positions.csv", newline="") as f:
        rows = list(csv.DictReader(f))
    has_3d = any("3d" in r.get("method", "") and r.get("diameter_3d") not in ("", None) for r in rows)
    use_3d = pupil_measure == "3d" or (pupil_measure == "auto" and has_3d)
    # Pixel diameters: from the 2D detector's rows when the export has them, otherwise from the
    # 3D rows, which carry the 2D ellipse diameter too (older Pupil Player exports).
    has_2d_rows = any("2d" in r.get("method", "") for r in rows)
    wanted = "3d" if use_3d else ("2d" if has_2d_rows else "")
    eyes = {0: ([], []), 1: ([], [])}
    for r in rows:
        if wanted not in r.get("method", ""):
            continue
        try:
            conf = float(r["confidence"])
            d = float(r["diameter_3d"] if use_3d else r["diameter"])
            eye = int(r["eye_id"])
            t = float(r["pupil_timestamp"])
        except (KeyError, ValueError):
            continue
        if conf >= min_confidence and d > 0 and eye in eyes:
            eyes[eye][0].append(t - t_zero)
            eyes[eye][1].append(d)
    all_t = np.concatenate([np.asarray(eyes[e][0]) for e in eyes])
    if len(all_t) < 2:
        raise ValueError(f"No pupil samples with confidence >= {min_confidence} in {export}")
    rates = [1 / np.median(np.diff(np.sort(eyes[e][0]))) for e in eyes if len(eyes[e][0]) > 10]
    rate = float(round(np.median(rates))) if rates else 120.0
    t0 = float(all_t.min())
    n = int(round((all_t.max() - t0) * rate)) + 1
    time = t0 + np.arange(n) / rate
    right = _bin(np.asarray(eyes[0][0]), np.asarray(eyes[0][1]), t0, rate, n)   # eye0 = right
    left = _bin(np.asarray(eyes[1][0]), np.asarray(eyes[1][1]), t0, rate, n)    # eye1 = left

    # Gaze, normalised to the scene video with the origin at the bottom left
    gt, gxy = [], []
    with open(export / "gaze_positions.csv", newline="") as f:
        for r in csv.DictReader(f):
            try:
                if float(r["confidence"]) < min_confidence:
                    continue
                gt.append(float(r["gaze_timestamp"]) - t_zero)
                gxy.append((float(r["norm_pos_x"]), 1.0 - float(r["norm_pos_y"])))
            except (KeyError, ValueError):
                continue
    gaze = _bin(np.asarray(gt), np.asarray(gxy).reshape(-1, 2), t0, rate, n)
    outside = ~((gaze >= -0.05) & (gaze <= 1.05)).all(axis=1)
    gaze[outside] = np.nan

    video = folder / "world.mp4"
    fov = camera_fov(folder, _video_resolution(video)) if video.exists() else DEFAULT_CAMERA_FOV
    profile = DeviceProfile(
        name=NAME,
        pupil_unit="mm" if use_3d else "px",
        pupil_scale=1.0 if use_3d else None,
        luminance_source="lux_sensor",
        field_of_view=fov,
        circular_scene=False,
        native_rate=rate,
        adapting_field=ADAPTING_FIELD,
    )

    lux_dir = Path(lux_folder) if lux_folder else lux.find_lux_folder(folder)
    lux_time = lux_values = None
    if lux_dir is not None:
        duration = float(time[-1] - min(time[0], 0.0))
        lux_time, lux_values = lux.read_lux(lux_dir, epoch_start, duration)
        if not len(lux_time):
            lux_time = lux_values = None

    return Recording(
        name=folder.name,
        profile=profile,
        folder=folder,
        time=time,
        epoch_start=epoch_start,
        pupil_left=left,
        pupil_right=right,
        gaze=gaze,
        scene_video=video if video.exists() else None,
        scene_frame_times=world_ts - t_zero,
        lux_time=lux_time,
        lux_values=lux_values,
        events=read_event_log(folder, epoch_start),
    )
