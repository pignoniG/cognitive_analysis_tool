"""Tobii Pro Glasses 3 recordings (experimental).

Written from the 1.x Tobii branch (``develop-for-Tobii-Pro-III``, 2022) and Tobii's recording format,
without a sample recording to check it against; see open issue 45 for what a real recording must confirm.

A recording folder, as copied from the recording unit's SD card, holds:

- ``recording.g3``: JSON with ``created`` (UTC start, ISO 8601), ``duration`` (s) and, per stream, the file
  names; the scene camera entry may carry its calibration (focal length, resolution);
- ``gazedata.gz``: one JSON object per line, ``{"type": "gaze", "timestamp": s, "data": {...}}``, with
  ``gaze2d`` (normalised scene video coordinates) and ``eyeleft`` / ``eyeright`` each carrying
  ``pupildiameter`` (mm). Samples without tracking have empty ``data``;
- ``scenevideo.mp4``: the scene camera;
- ``eventdata.gz`` (optional): events, one JSON object per line.

Timestamps are seconds from the start of the recording, which is taken as the start of the scene video.
Like the other glasses trackers, the Glasses 3 is used with the external lux sensor.
"""

from __future__ import annotations

import gzip
import json
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from pathlib import Path
from typing import Optional

import numpy as np

from cwtool import lux
from cwtool.devices.common import (bin_samples, events_from_markers, pinhole_fov, read_event_log, sample_rate,
                                   video_resolution)
from cwtool.recording import DeviceProfile, Recording

NAME = "tobii_g3"
RATE = 50.0                         # Hz, default gaze rate (100 Hz is optional)
SCENE_SIZE = (1920, 1080)           # px, scene camera
# Nominal scene camera field of view (deg), used when recording.g3 has no camera calibration.
SCENE_FOV = (95.0, 63.0)
ADAPTING_FIELD = (200.0, 135.0)     # deg, binocular visual field, as for the other glasses
SCENE_VIDEO = "scenevideo.mp4"


def detect(folder: Path) -> bool:
    """A Glasses 3 recording has ``recording.g3`` and ``gazedata.gz``."""
    folder = Path(folder)
    return (folder / "recording.g3").exists() and (folder / "gazedata.gz").exists()


def _json_lines(path: Path) -> list[dict]:
    """Objects of a gzipped JSON-lines file; unreadable lines are skipped."""
    if not path.exists():
        return []
    out = []
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def _number(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float("nan")


def _created(info: dict) -> Optional[float]:
    """Unix time (s) of the recording start from ``created``."""
    text = info.get("created")
    if not text:
        return None
    try:
        return datetime.fromisoformat(str(text).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _utc_offset(info: dict, epoch: float) -> Optional[float]:
    """UTC offset (s) of the recording unit's ``timezone`` (an IANA name) at ``epoch``, as 1.x used it;
    None if absent or unknown."""
    name = info.get("timezone")
    if not name:
        return None
    try:
        offset = datetime.fromtimestamp(epoch, ZoneInfo(str(name))).utcoffset()
    except (ZoneInfoNotFoundError, ValueError, OSError):
        return None
    return offset.total_seconds() if offset is not None else None


def _stream_file(info: dict, key: str, default: str) -> str:
    entry = info.get(key)
    return entry.get("file", default) if isinstance(entry, dict) else default


def _camera_fov(info: dict, size: tuple[int, int]) -> tuple[float, float]:
    """Field of view from the scene camera calibration in recording.g3, else the nominal one."""
    camera = info.get("scenecamera")
    calib = camera.get("camera-calibration") if isinstance(camera, dict) else None
    if not isinstance(calib, dict):
        return SCENE_FOV
    try:
        fx, fy = (float(v) for v in calib["focal-length"])
        w, h = (int(v) for v in calib.get("resolution", size))
        matrix = [[fx, 0, w / 2], [0, fy, h / 2], [0, 0, 1]]
        return pinhole_fov(matrix, (w, h))
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        return SCENE_FOV


def _event_name(data) -> str:
    """Label of an event's ``data``: its tag (or name, label, event), else the data as JSON."""
    if isinstance(data, dict):
        for key in ("tag", "name", "label", "event"):
            if data.get(key) not in (None, ""):
                return str(data[key])
        return json.dumps(data, sort_keys=True)
    return str(data)


def load(folder: Path, lux_folder: Optional[Path] = None, flip_gaze_y: bool = False) -> Recording:
    """Load a Glasses 3 recording. ``flip_gaze_y`` turns gaze y upside down, as the 1.x Tobii branch did;
    by default ``gaze2d`` is taken as origin top left, y down (open issue 45)."""
    folder = Path(folder)
    if not detect(folder):
        raise FileNotFoundError(f"No Tobii Pro Glasses 3 recording (recording.g3, gazedata.gz) in {folder}")
    info = json.loads((folder / "recording.g3").read_text(encoding="utf-8"))

    ts, left_d, right_d, gaze = [], [], [], []
    for obj in _json_lines(folder / _stream_file(info, "gaze", "gazedata.gz")):
        if obj.get("type", "gaze") != "gaze":
            continue
        t = _number(obj.get("timestamp"))
        if not np.isfinite(t):
            continue
        data = obj.get("data") or {}
        eye_l, eye_r = data.get("eyeleft") or {}, data.get("eyeright") or {}
        g = data.get("gaze2d") or [None, None]
        ts.append(t)
        left_d.append(_number(eye_l.get("pupildiameter")))
        right_d.append(_number(eye_r.get("pupildiameter")))
        gaze.append((_number(g[0]), _number(g[1])) if len(g) >= 2 else (np.nan, np.nan))
    if len(ts) < 2:
        raise ValueError(f"No gaze samples in {folder / 'gazedata.gz'}")
    ts = np.asarray(ts)
    rate = sample_rate(ts, RATE)
    t0 = float(ts.min())
    n = int(round((ts.max() - t0) * rate)) + 1
    time = t0 + np.arange(n) / rate

    # Each eye separately: a sample with one eye tracked still counts for that eye.
    pupils = np.asarray([left_d, right_d], dtype=float).T
    pupils = np.where(pupils > 0, pupils, np.nan)
    left = bin_samples(ts, pupils[:, 0], t0, rate, n)
    right = bin_samples(ts, pupils[:, 1], t0, rate, n)
    gxy = np.asarray(gaze, dtype=float)
    if flip_gaze_y:
        gxy[:, 1] = 1.0 - gxy[:, 1]
    gaze_grid = bin_samples(ts, gxy, t0, rate, n)
    outside = ~((gaze_grid >= -0.05) & (gaze_grid <= 1.05)).all(axis=1)
    gaze_grid[outside] = np.nan

    video = folder / _stream_file(info, "scenecamera", SCENE_VIDEO)
    video = video if video.exists() else None
    size = video_resolution(video) if video is not None else SCENE_SIZE
    if not size[0] or not size[1]:
        size = SCENE_SIZE
    profile = DeviceProfile(
        name=NAME,
        pupil_unit="mm",
        pupil_scale=1.0,
        luminance_source="lux_sensor",
        field_of_view=_camera_fov(info, size),
        circular_scene=False,
        native_rate=rate,
        adapting_field=ADAPTING_FIELD,
        experimental=True,
    )

    # The start time matches the lux log and event logs to the recording. There is no fallback: a file's
    # modification time is the copy time after an SD card transfer, and would match them silently at the
    # wrong time (open issue 45).
    epoch_start = _created(info)
    notes = []
    lux_dir = Path(lux_folder) if lux_folder else lux.find_lux_folder(folder)
    lux_time = lux_values = None
    if epoch_start is None:
        notes.append("recording.g3 has no start time ('created'): the lux log and event logs cannot be matched "
                     "to the recording and were not read; exported Unix times are empty.")
    elif lux_dir is not None:
        lux_time, lux_values = lux.read_lux(lux_dir, epoch_start, float(time[-1] - min(time[0], 0.0)))
        if not len(lux_time):
            lux_time = lux_values = None

    marks = [(_number(o.get("timestamp")), _event_name(o.get("data")))
             for o in _json_lines(folder / _stream_file(info, "events", "eventdata.gz"))
             if o.get("type", "event") == "event"]
    marks = [(t, name) for t, name in marks if np.isfinite(t)]
    events = events_from_markers([t for t, _ in marks], [name for _, name in marks], end=float(time[-1]))
    if epoch_start is not None:
        # Event logs without a zone are read in the recording unit's zone (open issue 22).
        events += read_event_log(folder, epoch_start, _utc_offset(info, epoch_start))

    return Recording(
        name=folder.name,
        profile=profile,
        folder=folder,
        time=time,
        epoch_start=float(epoch_start) if epoch_start is not None else float("nan"),
        pupil_left=left,
        pupil_right=right,
        gaze=gaze_grid,
        scene_video=video,
        scene_frame_times=None,        # constant frame rate from the video (1.x did the same)
        lux_time=lux_time,
        lux_values=lux_values,
        events=sorted(events, key=lambda e: e.start),
        notes=notes,
    )
