"""Pupil Labs Neon recordings.

Written from the published data format, before any real recording was available
(Pupil Labs documentation and pl-neon-recording, September 2026). Two layouts are read:

**Pupil Cloud "Timeseries Data" export** (with or without the scene video): a folder
per recording with ``info.json``, ``3d_eye_states.csv`` (pupil diameter per eye, mm),
``gaze.csv`` (gaze in scene camera pixels, ``worn`` flag), ``blinks.csv``,
``events.csv``, ``world_timestamps.csv``, ``scene_camera.json`` and the scene video
``<section id>_<start>-<end>.mp4``. All timestamps are UTC nanoseconds.

**Native recording format** (Pupil Cloud "Native Recording Data", or copied from the
Companion phone over USB): ``info.json``, binary streams ``<name> ps<n>.raw`` with
``<name> ps<n>.time`` (int64 UTC ns), ``gaze_200hz.raw`` when gaze was recomputed at
200 Hz, ``event.txt`` / ``event.time``, ``calibration.bin`` and the scene video
``Neon Scene Camera v1 ps<n>.mp4`` with its ``.time`` file. Pupil diameters exist only
if eye state estimation was enabled in the Companion app during the recording.
Blinks are in ``blinks ps<n>.raw`` (data format 2.5, checked on a real recording, open
issue 32); older recordings without that file rely on the pipeline's speed filter, which
removes the blink edges.

Neon reports the physical pupil diameter in mm for each eye. Samples where Neon
was not worn, and blinks (widened by BLINK_PADDING), are removed. Like the Pupil
Core, the Neon is a glasses-type tracker used with the external lux sensor.
"""

from __future__ import annotations

import ast
import csv
import json
import re
from pathlib import Path
from typing import Optional

import numpy as np

from cwtool import lux
from cwtool.devices import quest
from cwtool.devices.common import (bin_samples, events_from_markers, pinhole_fov, read_event_log, sample_rate,
                                   utc_offset_from_name, video_resolution)
from cwtool.recording import DeviceProfile, Event, Recording
from cwtool.video import video_info

NAME = "pupil_neon"
XR_NAME = "pupil_neon_xr"         # a Neon inside a headset, the luminance from the headset's capture
RATE = 200.0                        # Hz, eye cameras
SCENE_SIZE = (1600, 1200)           # px, scene camera
SCENE_FOV = (103.0, 77.0)           # deg, nominal (distorted) scene camera field of view
ADAPTING_FIELD = (200.0, 135.0)     # deg, binocular visual field, as for the Pupil Core
BLINK_PADDING = 0.1                 # s removed before and after each blink
# Events Neon adds to every recording; they carry no protocol information.
AUTOMATIC_EVENTS = ("recording.begin", "recording.end")
SCENE_VIDEO = "Neon Scene Camera v1"


def _layout(folder: Path) -> Optional[str]:
    if not (folder / "info.json").exists():
        return None
    if (folder / "3d_eye_states.csv").exists() or (folder / "gaze.csv").exists():
        return "cloud"
    if (folder / "gaze_200hz.raw").exists() or any(folder.glob("gaze ps*.raw")) \
            or any(folder.glob("eye_state ps*.raw")):
        return "native"
    return None


def detect(folder: Path) -> bool:
    """True if the folder has a Neon recording (either layout)."""
    return _layout(Path(folder)) is not None


# Pupil Cloud CSV export

def _key(header: str) -> str:
    return " ".join(header.replace("\xa0", " ").strip().lower().split())


def _read_csv(path: Path) -> dict[str, list[str]]:
    """Columns of a CSV by normalised header name (lower case, single spaces)."""
    if not path.exists():
        return {}
    with open(path, newline="") as f:
        rows = list(csv.reader(f))
    if not rows:
        return {}
    header = [_key(h) for h in rows[0]]
    cols = {h: [] for h in header}
    for r in rows[1:]:
        for h, v in zip(header, r):
            cols[h].append(v)
    return cols


def _ns(values) -> np.ndarray:
    return np.array([int(v) for v in values], dtype=np.int64)


def _floats(values) -> np.ndarray:
    out = np.full(len(values), np.nan)
    for i, v in enumerate(values):
        try:
            out[i] = float(v)
        except ValueError:
            pass
    return out


def _column(cols: dict, *names: str) -> Optional[list[str]]:
    for n in names:
        if n in cols:
            return cols[n]
    return None


def _scene_videos(folder: Path) -> list[Path]:
    """The videos of a Cloud export that can be the Neon's scene video: not hidden, not a Quest capture (a capture copied
    into the folder was once taken as the scene video and given the Neon camera's timestamps, open issue 32)."""
    return sorted(v for v in folder.glob("*.mp4") if not v.name.startswith(".") and not quest.is_capture(v))


def _cloud_video(folder: Path, frames: dict) -> tuple[Optional[Path], Optional[np.ndarray]]:
    """Scene video and its frame timestamps (ns). With several sections, the longest is used. A single video is taken only
    if its frame count is that of ``world_timestamps.csv`` (within 2 %) or its name is the export's
    (``<section id start>_<start>-<end>.mp4``)."""
    videos = _scene_videos(folder)
    if not frames:
        return (videos[0] if len(videos) == 1 else None), None
    ts = _ns(frames["timestamp [ns]"])
    sections = frames.get("section id")
    if sections is None or len(set(sections)) == 1:
        video = videos[0] if len(videos) == 1 else next(
            (v for v in videos if sections and str(sections[0]).startswith(v.name.split("_")[0])), None)
        if video is not None and not _matches_frames(video, len(ts), sections):
            video = None
        return video, ts
    ids, counts = np.unique(np.array(sections), return_counts=True)
    best = str(ids[np.argmax(counts)])
    match = [v for v in videos if best.startswith(v.name.split("_")[0])]
    return (match[0] if match else None), ts[np.array(sections) == best]


def _matches_frames(video: Path, n_frames: int, sections) -> bool:
    """Whether ``video`` is the scene video with ``n_frames`` frames: by its export name, else by its frame count."""
    if sections and re.match(r"^[0-9a-f]{8}_\d+-\d+\.mp4$", video.name) and str(sections[0]).startswith(video.name[:8]):
        return True
    try:
        _, count = video_info(video)
    except (IOError, OSError):
        return False
    return abs(count - n_frames) <= max(2, 0.02 * n_frames)


def _load_cloud(folder: Path):
    """Streams of a Pupil Cloud Timeseries export, in the tuple :func:`load` unpacks for both layouts."""
    eyes = _read_csv(folder / "3d_eye_states.csv")
    if not eyes:
        raise FileNotFoundError(f"No 3d_eye_states.csv (pupil diameters) in {folder}")
    eye_ts = _ns(eyes["timestamp [ns]"])
    left = _column(eyes, "pupil diameter left [mm]", "pupil diameter [mm]")
    right = _column(eyes, "pupil diameter right [mm]", "pupil diameter [mm]")
    if left is None or right is None:
        raise ValueError(f"3d_eye_states.csv in {folder} has no pupil diameter columns")
    pupils = np.stack([_floats(left), _floats(right)], axis=1)

    gaze_cols = _read_csv(folder / "gaze.csv")
    gaze_ts = _ns(gaze_cols["timestamp [ns]"]) if gaze_cols else np.empty(0, np.int64)
    gaze_px = np.stack([_floats(gaze_cols["gaze x [px]"]), _floats(gaze_cols["gaze y [px]"])], axis=1) \
        if gaze_cols else np.empty((0, 2))
    worn = _floats(gaze_cols["worn"]) if gaze_cols and "worn" in gaze_cols else np.ones(len(gaze_ts))

    blinks = _read_csv(folder / "blinks.csv")
    blink_spans = np.stack([_ns(blinks["start timestamp [ns]"]), _ns(blinks["end timestamp [ns]"])], axis=1) \
        if blinks else np.empty((0, 2), np.int64)

    events = _read_csv(folder / "events.csv")
    markers = (_ns(events["timestamp [ns]"]), events["name"]) if events else (np.empty(0, np.int64), [])

    video, frame_ts = _cloud_video(folder, _read_csv(folder / "world_timestamps.csv"))
    matrix = None
    if (folder / "scene_camera.json").exists():
        matrix = json.loads((folder / "scene_camera.json").read_text()).get("camera_matrix")
    return eye_ts, pupils, gaze_ts, gaze_px, worn, blink_spans, markers, video, frame_ts, matrix


# Native recording format

def _parts(folder: Path, base: str, time_base: Optional[str] = None, ext: str = ".raw"):
    """(data file, time file) pairs of a multipart stream, in part order."""
    pairs = []
    for f in folder.glob(f"{base} ps*{ext}"):
        part = f.stem[len(base) + 3:]
        if not part.isdigit():
            continue
        t = folder / f"{time_base or base} ps{part}.time"
        if t.exists():
            pairs.append((int(part), f, t))
    return [(f, t) for _, f, t in sorted(pairs)]


def _records(pairs, n_fields: int, fields_dtype=None) -> tuple[np.ndarray, np.ndarray]:
    """Timestamps (ns) and float records (N, fields) of a stream. The record size is taken
    from the stream's ``.dtype`` file when given, otherwise from the file size, so streams
    that gained fields in newer app versions still load."""
    ts_all, rec_all = [], []
    for data, tfile in pairs:
        ts = np.fromfile(tfile, dtype="<i8")
        raw = np.fromfile(data, dtype="<f4")
        width = len(fields_dtype) if fields_dtype else (len(raw) // len(ts) if len(ts) else n_fields)
        width = max(width, n_fields)
        n = min(len(ts), len(raw) // width)
        ts_all.append(ts[:n])
        rec_all.append(raw[: n * width].reshape(n, width))
    if not ts_all:
        return np.empty(0, np.int64), np.empty((0, n_fields))
    return np.concatenate(ts_all), np.concatenate(rec_all).astype(float)


BLINK_RECORD = np.dtype([("event_type", "<i4"), ("start", "<i8"), ("end", "<i8")])   # packed, as blinks.dtype


def _native_blinks(folder: Path) -> np.ndarray:
    """(start, end) ns of the blinks in ``blinks ps*.raw``, empty when the recording has none."""
    spans = []
    for data, _ in _parts(folder, "blinks"):
        raw = data.read_bytes()
        n = len(raw) // BLINK_RECORD.itemsize
        rec = np.frombuffer(raw[: n * BLINK_RECORD.itemsize], dtype=BLINK_RECORD)
        spans.append(np.stack([rec["start"], rec["end"]], axis=1))
    return np.concatenate(spans) if spans else np.empty((0, 2), np.int64)


def _dtype_names(folder: Path, base: str) -> Optional[list[str]]:
    path = folder / f"{base}.dtype"
    if not path.exists():
        return None
    try:
        return [str(d[0]) for d in ast.literal_eval(path.read_text())]
    except (ValueError, SyntaxError, IndexError, TypeError):
        return None


def _load_native(folder: Path):
    """Streams of a native recording (``.raw`` / ``.time`` pairs), as :func:`_load_cloud`."""
    names = _dtype_names(folder, "eye_state")
    eye_ts, eye = _records(_parts(folder, "eye_state"), 14, names)
    if not len(eye_ts):
        raise FileNotFoundError(
            f"No pupil data (eye_state ps*.raw) in {folder}: eye state estimation was off in the Companion app. "
            "Upload the recording to Pupil Cloud and download the Timeseries Data, which include pupil diameters.")
    if names and "pupil_diameter_left_mm" in names and "pupil_diameter_right_mm" in names:
        cols = [names.index("pupil_diameter_left_mm"), names.index("pupil_diameter_right_mm")]
    else:
        cols = [0, 7]   # layout of pl-neon-recording: left eye's 7 values, then the right eye's
    pupils = eye[:, cols]

    if (folder / "gaze_200hz.raw").exists() and (folder / "gaze_200hz.time").exists():
        gaze_pairs = [(folder / "gaze_200hz.raw", folder / "gaze_200hz.time")]
        worn_pairs = [(folder / "worn_200hz.raw", folder / "gaze_200hz.time")]
    else:
        gaze_pairs = _parts(folder, "gaze")
        worn_pairs = _parts(folder, "worn", time_base="gaze")
    gaze_ts, gaze = _records(gaze_pairs, 2, _dtype_names(folder, "gaze"))
    gaze_px = gaze[:, :2]
    worn = np.ones(len(gaze_ts))
    worn_values = [np.fromfile(f, dtype="u1") for f, _ in worn_pairs if f.exists()]
    if worn_values and sum(len(w) for w in worn_values) >= len(gaze_ts):
        worn = np.concatenate(worn_values)[: len(gaze_ts)].astype(float)

    markers = (np.empty(0, np.int64), [])
    if (folder / "event.txt").exists() and (folder / "event.time").exists():
        names_ = (folder / "event.txt").read_text(encoding="utf-8").splitlines()
        ts = np.fromfile(folder / "event.time", dtype="<i8")
        n = min(len(ts), len(names_))
        markers = (ts[:n], names_[:n])

    video = frame_ts = None
    parts = _parts(folder, SCENE_VIDEO, ext=".mp4")
    if parts:
        # Recordings split into several parts: only the longest part is analysed.
        sizes = [len(np.fromfile(t, dtype="<i8")) for _, t in parts]
        video, tfile = parts[int(np.argmax(sizes))]
        frame_ts = np.fromfile(tfile, dtype="<i8")

    matrix = None
    calib = folder / "calibration.bin"
    if calib.exists() and calib.stat().st_size >= 7 + 72:
        matrix = np.frombuffer(calib.read_bytes()[7:7 + 72], dtype="<f8").reshape(3, 3)
    return eye_ts, pupils, gaze_ts, gaze_px, worn, _native_blinks(folder), markers, video, frame_ts, matrix


def _phone_utc_offset(folder: Path, info: dict) -> Optional[float]:
    """The Companion phone's UTC offset (s), from the recording's name (its local start time) and its UTC start; None if
    neither the name in ``info.json`` nor the export folder's name parses."""
    start = (info.get("start_time") or 0) / 1e9
    name = str((info.get("template_data") or {}).get("recording_name") or "")
    for text, fmt in ((name[:19], "%Y-%m-%d_%H:%M:%S"), (folder.name[:19], "%Y-%m-%d_%H-%M-%S")):
        if start and text:
            offset = utc_offset_from_name(text, fmt, start)
            if offset is not None:
                return offset
    return None


def _gaze_angles(gaze_px: np.ndarray, matrix, size: tuple[int, int]) -> tuple[np.ndarray, np.ndarray]:
    """Azimuth and elevation (deg; right and up) of gaze in scene camera pixels, through the camera matrix (a pinhole: the
    lens distortion is left out, as for the field of view, open issue 33). Without a matrix, the nominal field is used."""
    if matrix is not None:
        k = np.asarray(matrix, dtype=float).reshape(3, 3)
        fx, fy, cx, cy = k[0, 0], k[1, 1], k[0, 2], k[1, 2]
    else:
        fx = size[0] / 2 / np.tan(np.radians(SCENE_FOV[0] / 2))
        fy = size[1] / 2 / np.tan(np.radians(SCENE_FOV[1] / 2))
        cx, cy = size[0] / 2, size[1] / 2
    x = (gaze_px[:, 0] - cx) / fx
    y = (gaze_px[:, 1] - cy) / fy
    return np.degrees(np.arctan(x)), np.degrees(np.arctan2(-y, np.sqrt(1 + x * x)))


def is_xr(info: dict) -> bool:
    """Whether the Neon was in a headset frame (``frame_name`` in ``info.json``, e.g. "Quest3 XR")."""
    name = str(info.get("frame_name") or "").lower()
    return any(word in name for word in quest.NEON_XR_FRAMES)


def load(folder: Path, lux_folder: Optional[Path] = None) -> Recording:
    """Load a Neon recording in either layout: per-eye pupils (mm) and gaze binned onto a grid at the measured rate.

    Two routes, named in ``Recording.route``. **Glasses**: time zero at the first scene frame, the scene camera's video,
    lux logs from ``lux_folder`` or the recording. **XR** (a Neon in a Quest frame, or a Quest capture next to the
    recording that overlaps it): the scene video is the Quest's capture, found in the recording's folder or the one above;
    time zero is the capture's start from its name, the luminance is the display's, and the gaze is placed in the capture
    by its direction (open issue 61)."""
    folder = Path(folder)
    layout = _layout(folder)
    if layout is None:
        raise FileNotFoundError(f"No Neon recording (info.json with Neon data) in {folder}")
    info = json.loads((folder / "info.json").read_text())
    eye_ts, pupils, gaze_ts, gaze_px, worn, blinks, markers, video, frame_ts, matrix = \
        (_load_cloud if layout == "cloud" else _load_native)(folder)
    if video is not None and not Path(video).exists():
        video = None

    utc_offset = _phone_utc_offset(folder, info)
    span = (eye_ts[0] / 1e9, eye_ts[-1] / 1e9) if len(eye_ts) else (0.0, 0.0)
    capture = quest.find_capture([folder, folder.parent], span[0], span[1], utc_offset)
    xr = capture is not None or is_xr(info)
    notes: list[str] = []

    if xr:
        captured_at = quest.capture_start(capture, utc_offset) if capture is not None else None
        t_zero = int(round(captured_at * 1e9)) if captured_at is not None else int(info.get("start_time") or eye_ts[0])
    elif frame_ts is not None and len(frame_ts):
        t_zero = int(frame_ts[0])        # glasses: the first scene frame (the video clock)
    else:
        t_zero = int(info.get("start_time") or eye_ts[0])
    rel = lambda ns: (np.asarray(ns, dtype=np.int64) - t_zero) / 1e9

    t_eye = rel(eye_ts)
    rate = sample_rate(t_eye, RATE)
    t0 = float(t_eye.min())
    n = int(round((t_eye.max() - t0) * rate)) + 1
    time = t0 + np.arange(n) / rate

    pupils = np.where(pupils > 0, pupils, np.nan)
    left = bin_samples(t_eye, pupils[:, 0], t0, rate, n)
    right = bin_samples(t_eye, pupils[:, 1], t0, rate, n)

    width, height = video_resolution(video) if video is not None else SCENE_SIZE
    if not width or not height:
        width, height = SCENE_SIZE
    t_gaze = rel(gaze_ts)
    if xr:
        azimuth, elevation = _gaze_angles(gaze_px, matrix, (width, height))
        gaze_norm = quest.gaze_to_capture(azimuth, elevation)
    else:
        gaze_norm = gaze_px / np.array([width, height], dtype=float)
    gaze = bin_samples(t_gaze, gaze_norm, t0, rate, n)
    outside = ~((gaze >= -0.05) & (gaze <= 1.05)).all(axis=1)
    gaze[outside] = np.nan

    # Not worn: no pupil or gaze. Gaze and eye state share the eye camera's timestamps.
    if len(t_gaze):
        not_worn = bin_samples(t_gaze, (np.asarray(worn) < 0.5).astype(float), t0, rate, n) > 0
        for a in (left, right):
            a[not_worn] = np.nan
        gaze[not_worn] = np.nan
    for start, end in rel(blinks.reshape(-1, 2)) if len(blinks) else ():
        inside = (time >= start - BLINK_PADDING) & (time <= end + BLINK_PADDING)
        left[inside] = right[inside] = np.nan

    if xr:
        scene_video, scene_times = capture, None
        if capture is not None:
            scene_times = quest.frame_times(capture)
            route = f"XR: Meta Quest capture ({quest.app_of(capture)}), luminance from the headset's picture"
            notes.append(f"Neon inside a headset: the luminance comes from the Quest capture {capture.name}, placed on the "
                         "pupil's clock by its name (to a second); align it with the presenter's run file or the pupil's "
                         "response. The gaze is placed in the capture by its direction, without a calibration in the "
                         "headset: check it, and set the gaze offset if it is off (open issue 61).")
            if utc_offset is None:
                notes.append("The phone's time zone could not be read from the recording's name: the capture's name was read "
                             "in this computer's zone.")
        else:
            route = "XR: no Quest capture found, nothing to take the luminance from"
            notes.append("The Neon was in a headset frame (" + str(info.get("frame_name")) + "), whose scene camera does "
                         "not see the displays, and no Quest capture (com.oculus.* or com.meta.*.mp4) overlapping the "
                         "recording was found in its folder or the one above.")
        profile = DeviceProfile(
            name=XR_NAME,
            pupil_unit="mm",
            pupil_scale=1.0,
            luminance_source="display",
            field_of_view=quest.CAPTURE_FOV,
            circular_scene=False,
            native_rate=rate,
            adapting_field=quest.HEADSET_FOV,
            experimental=True,          # open issue 61
        )
        lux_time = lux_values = None
    else:
        scene_video = Path(video) if video is not None else None
        scene_times = rel(frame_ts) if frame_ts is not None else None
        fov = SCENE_FOV
        if matrix is not None:
            try:
                fov = pinhole_fov(matrix, (width, height))
            except (ValueError, ZeroDivisionError):
                pass
        profile = DeviceProfile(
            name=NAME,
            pupil_unit="mm",
            pupil_scale=1.0,
            luminance_source="lux_sensor",
            field_of_view=fov,
            circular_scene=False,
            native_rate=rate,
            adapting_field=ADAPTING_FIELD,
            experimental=True,          # open issue 32
        )
        lux_time, lux_values, lux_notes = lux.load_log(folder, lux_folder, t_zero / 1e9,
                                                       float(time[-1] - min(time[0], 0.0)))
        notes += lux_notes
        route = "glasses: Neon scene camera and " + ("lux sensor" if lux_values is not None else "no lux log")

    epoch_start = t_zero / 1e9
    events: list[Event] = events_from_markers(rel(markers[0]), markers[1], end=float(time[-1]),
                                              ignore=AUTOMATIC_EVENTS)
    events += read_event_log(folder, epoch_start)

    return Recording(
        name=folder.name,
        profile=profile,
        folder=folder,
        time=time,
        epoch_start=epoch_start,
        pupil_left=left,
        pupil_right=right,
        gaze=gaze,
        scene_video=scene_video,
        scene_frame_times=scene_times,
        lux_time=lux_time,
        lux_values=lux_values,
        events=sorted(events, key=lambda e: e.start),
        notes=notes,
        route=route,
        separate_video_clock=xr and capture is not None,
    )
