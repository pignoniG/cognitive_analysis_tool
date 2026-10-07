import csv
from pathlib import Path

import cv2
import numpy as np
import pytest



# Header of a Varjo Base eye tracking export (April 2026).
VARJO_HEADER = (
    "raw_timestamp,relative_to_unix_epoch_timestamp,relative_to_video_first_frame_timestamp,focus_distance,"
    "frame_number,stability,status,gaze_forward_x,gaze_forward_y,gaze_forward_z,gaze_origin_x,gaze_origin_y,"
    "gaze_origin_z,gaze_projected_to_left_view_x,gaze_projected_to_left_view_y,gaze_projected_to_right_view_x,"
    "gaze_projected_to_right_view_y,left_forward_x,left_forward_y,left_forward_z,left_origin_x,left_origin_y,"
    "left_origin_z,left_pupil_size,left_status,left_projected_x,left_projected_y,right_forward_x,right_forward_y,"
    "right_forward_z,right_origin_x,right_origin_y,right_origin_z,right_pupil_size,right_status,right_projected_x,"
    "right_projected_y,inter_pupillary_distance_in_mm,left_iris_diameter_in_mm,left_pupil_diameter_in_mm,"
    "left_pupil_iris_diameter_ratio,left_eye_openness,right_iris_diameter_in_mm,right_pupil_diameter_in_mm,"
    "right_pupil_iris_diameter_ratio,right_eye_openness").split(",")


def write_varjo_recording(folder: Path, grays, seconds_per_level=1.0, fps=10, size=(64, 48),
                          gaze=(0.0, 0.0), pupil_mm=2.0, rate=100, iris_mm=None):
    """Synthetic Varjo recording: a full-frame gray level or RGB colour per step and a constant gaze.
    ``pupil_mm`` is the value written to the CSV, which older Varjo Base versions report as a radius (×2 =
    diameter). ``iris_mm`` is written to the iris diameter columns (6 mm in those exports, 12 mm in the later
    ones that report diameters); by default they hold missing values."""
    folder.mkdir(parents=True, exist_ok=True)
    w, h = size
    writer = cv2.VideoWriter(str(folder / "varjo_capture_test.avi"), cv2.VideoWriter_fourcc(*"MJPG"), fps, (w, h))
    for g in grays:
        bgr = (g, g, g) if np.isscalar(g) else tuple(reversed(g))  # a level or an (R, G, B) colour
        for _ in range(int(seconds_per_level * fps)):
            writer.write(np.full((h, w, 3), bgr, dtype=np.uint8))
    writer.release()

    n = int(len(grays) * seconds_per_level * rate)
    col = {h: i for i, h in enumerate(VARJO_HEADER)}
    with open(folder / "varjo_gaze_output_test.csv", "w", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(VARJO_HEADER)
        for i in range(n):
            row = ["0"] * len(VARJO_HEADER)
            row[col["left_iris_diameter_in_mm"]] = "-nan(ind)"   # as Varjo Base writes missing values
            if iris_mm is not None:
                row[col["left_iris_diameter_in_mm"]] = row[col["right_iris_diameter_in_mm"]] = str(iris_mm)
            t_ns = int(i * 1e9 / rate)
            row[col["relative_to_unix_epoch_timestamp"]] = str(1_700_000_000 * 10**9 + t_ns)
            row[col["relative_to_video_first_frame_timestamp"]] = str(t_ns)
            for c in ("status", "left_status", "right_status"):
                row[col[c]] = "2"
            for c in ("left_projected_x", "right_projected_x", "gaze_projected_to_left_view_x"):
                row[col[c]] = str(gaze[0])
            for c in ("left_projected_y", "right_projected_y", "gaze_projected_to_left_view_y"):
                row[col[c]] = str(gaze[1])
            p = pupil_mm(i / rate) if callable(pupil_mm) else pupil_mm
            row[col["left_pupil_diameter_in_mm"]] = row[col["right_pupil_diameter_in_mm"]] = str(p)
            wr.writerow(row)
    return folder


@pytest.fixture
def varjo_folder(tmp_path):
    return write_varjo_recording(tmp_path / "rec1", grays=[0, 128, 255, 64])


def write_core_recording(folder: Path, grays, frame_times, pupil_mm=6.0, rate=200, gaze=(0.5, 0.5),
                         low_confidence=(), lux=None, size=(64, 36), synced_start=1000.0,
                         system_start=1_700_000_000.0):
    """Synthetic Pupil Core recording with a Pupil Player export.

    ``grays[i]`` is the level of scene frame i captured at ``frame_times[i]`` (s, Pupil clock
    relative to the first frame, may be uneven). Pupil and gaze samples cover the same span at
    ``rate`` Hz per eye; samples at times in ``low_confidence`` (list of (start, end)) get
    confidence 0.2. ``lux(t)`` optionally writes a lux log in the recording folder.
    """
    import json
    folder.mkdir(parents=True, exist_ok=True)
    export = folder / "exports" / "000"
    export.mkdir(parents=True)
    t_first = synced_start + 0.5
    (folder / "info.player.json").write_text(json.dumps({
        "start_time_synced_s": synced_start, "start_time_system_s": system_start, "duration_s": 10}))
    np.save(folder / "world_timestamps.npy", t_first + np.asarray(frame_times, dtype=float))
    w, h = size
    writer = cv2.VideoWriter(str(folder / "world.mp4"), cv2.VideoWriter_fourcc(*"mp4v"), 30, (w, h))
    for g in grays:
        writer.write(np.full((h, w, 3), g, dtype=np.uint8))
    writer.release()

    span = frame_times[-1]
    times = np.arange(0, span, 1 / rate)
    bad = lambda t: any(a <= t < b for a, b in low_confidence)
    with open(export / "pupil_positions.csv", "w", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(["pupil_timestamp", "world_index", "eye_id", "confidence", "norm_pos_x", "norm_pos_y",
                     "diameter", "method", "diameter_3d"])
        for t in times:
            d = pupil_mm(t) if callable(pupil_mm) else pupil_mm
            for eye, dt in ((0, 0.0), (1, 0.002)):   # eyes sampled independently
                wr.writerow([t_first + t + dt, 0, eye, 0.2 if bad(t) else 0.95, 0.5, 0.5, d * 8.0, "3d c++", d])
    with open(export / "gaze_positions.csv", "w", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(["gaze_timestamp", "world_index", "confidence", "norm_pos_x", "norm_pos_y"])
        for t in times:
            wr.writerow([t_first + t + 0.001, 0, 0.2 if bad(t) else 0.95, gaze[0], gaze[1]])
    if lux is not None:
        epoch0 = system_start + 0.5
        with open(folder / "1_1_1.csv", "w", newline="") as f:
            wr = csv.writer(f)
            for t in np.arange(-1, span + 1, 0.1):
                wr.writerow([f"{(epoch0 + t) * 1000:.0f}", 1, 1, 1, lux(t)])
    return folder


NEON_EYE_HEADER = (
    "section id,recording id,timestamp [ns],pupil diameter left [mm],pupil diameter right [mm],"
    "eye ball center left x [mm],eye ball center left y [mm],eye ball center left z [mm],"
    "eye ball center right x [mm],eye ball center right y [mm],eye ball center right z [mm],"
    "optical axis left x,optical axis left y,optical axis left z,optical axis right x,optical axis right y,"
    "optical axis right z,eyelid angle top left,eyelid angle bottom left,eyelid angle top right,"
    "eyelid angle bottom right,eyelid aperture left [mm],eyelid aperture right [mm]").split(",")
NEON_GAZE_HEADER = ("section id,recording id,timestamp [ns],gaze x [px],gaze y [px],worn,fixation id,blink id,"
                    "azimuth [deg],elevation [deg]").split(",")


def write_neon_recording(folder: Path, grays, frame_times, layout="cloud", pupil_mm=5.0, rate=200,
                         gaze_px=(80, 30), size=(160, 120), not_worn=(), blinks=(), events=(), lux=None,
                         start_ns=1_700_000_000_000_000_000, video_delay=0.25):
    """Synthetic Neon recording in the Pupil Cloud Timeseries export ("cloud") or the native
    format ("native"). Eye samples start ``video_delay`` s before the first scene frame, as the
    eye cameras start first. ``not_worn`` and ``blinks`` are (start, end) spans in s relative to
    the first frame; ``events`` are (time, name) markers. ``pupil_mm`` may be a function of time."""
    import json
    folder.mkdir(parents=True, exist_ok=True)
    first_frame = start_ns + int(video_delay * 1e9)
    ns = lambda t: first_frame + int(round(t * 1e9))
    frame_ns = [ns(t) for t in frame_times]
    (folder / "info.json").write_text(json.dumps({
        "start_time": start_ns, "duration": int((frame_times[-1] + video_delay + 0.1) * 1e9),
        "recording_id": "a1b2c3d4-0000", "gaze_mode": "binocular", "data_format_version": "2.3"}))
    times = np.arange(-video_delay, frame_times[-1], 1 / rate)
    inside = lambda t, spans: any(a <= t < b for a, b in spans)
    diam = [pupil_mm(t) if callable(pupil_mm) else pupil_mm for t in times]

    w, h = size
    video_name = "a1b2c3d4_0-10.mp4" if layout == "cloud" else "Neon Scene Camera v1 ps1.mp4"
    writer = cv2.VideoWriter(str(folder / video_name), cv2.VideoWriter_fourcc(*"mp4v"), 30, (w, h))
    for g in grays:
        writer.write(np.full((h, w, 3), g, dtype=np.uint8))
    writer.release()
    fx = w / 2 / np.tan(np.radians(45))          # pinhole with a 90° horizontal field

    if layout == "cloud":
        def table(name, header, rows):
            with open(folder / name, "w", newline="") as f:
                wr = csv.writer(f)
                wr.writerow(header)
                wr.writerows(rows)
        eye_rows, gaze_rows = [], []
        for t, d in zip(times, diam):
            eye = ["s1", "r1", ns(t), d, d + 0.2] + [0.0] * (len(NEON_EYE_HEADER) - 5)
            eye_rows.append(eye)
            gaze_rows.append(["s1", "r1", ns(t), gaze_px[0], gaze_px[1], 0.0 if inside(t, not_worn) else 1.0,
                              "", "", 0.0, 0.0])
        table("3d_eye_states.csv", NEON_EYE_HEADER, eye_rows)
        table("gaze.csv", NEON_GAZE_HEADER, gaze_rows)
        table("world_timestamps.csv", ["section id", "recording id", "timestamp [ns]"],
              [["s1", "r1", t] for t in frame_ns])
        table("blinks.csv", ["section id", "recording id", "blink id", "start timestamp [ns]",
                             "end timestamp [ns]", "duration [ms]"],
              [["s1", "r1", i + 1, ns(a), ns(b), (b - a) * 1000] for i, (a, b) in enumerate(blinks)])
        table("events.csv", ["recording id", "timestamp [ns]", "name", "type"],
              [["r1", start_ns, "recording.begin", "recording"]]
              + [["r1", ns(t), name, "cloud"] for t, name in events])
        (folder / "scene_camera.json").write_text(json.dumps({
            "camera_matrix": [[fx, 0, w / 2], [0, fx, h / 2], [0, 0, 1]], "dist_coefs": [0.0] * 8,
            "serial_number": "abc123", "version": 1}))
    else:
        eye_ts = np.array([ns(t) for t in times], dtype="<i8")
        eye = np.zeros((len(times), 14), dtype="<f4")
        eye[:, 0] = diam
        eye[:, 7] = np.asarray(diam) + 0.2
        eye_ts.tofile(folder / "eye_state ps1.time")
        eye.tofile(folder / "eye_state ps1.raw")
        eye_ts.tofile(folder / "gaze ps1.time")
        np.tile(np.asarray(gaze_px, dtype="<f4"), (len(times), 1)).tofile(folder / "gaze ps1.raw")
        np.array([0 if inside(t, not_worn) else 1 for t in times], dtype="u1").tofile(folder / "worn ps1.raw")
        np.array(frame_ns, dtype="<i8").tofile(folder / "Neon Scene Camera v1 ps1.time")
        marks = [(start_ns, "recording.begin")] + [(ns(t), name) for t, name in events]
        (folder / "event.txt").write_text("\n".join(name for _, name in marks) + "\n")
        np.array([t for t, _ in marks], dtype="<i8").tofile(folder / "event.time")
        k = np.array([[fx, 0, w / 2], [0, fx, h / 2], [0, 0, 1]], dtype="<f8")
        (folder / "calibration.bin").write_bytes(b"\x01" + b"abc123" + k.tobytes() + bytes(600))
    if lux is not None:
        epoch0 = first_frame / 1e9
        with open(folder / "1_1_1.csv", "w", newline="") as f:
            wr = csv.writer(f)
            for t in np.arange(-1, frame_times[-1] + 1, 0.1):
                wr.writerow([f"{(epoch0 + t) * 1000:.0f}", 1, 1, 1, lux(t)])
    return folder


def write_tobii_g3_recording(folder: Path, grays, fps=25, pupil_mm=4.0, rate=50, gaze=(0.25, 0.75),
                             size=(96, 54), untracked=(), left_only=(), events=(), lux=None,
                             calibration=True, created="2026-09-28T10:00:00.000Z", timezone=None):
    """Synthetic Tobii Pro Glasses 3 recording: a scene video of full-frame grey levels (one per frame),
    gaze samples at ``rate`` Hz with both pupils (right = left + 0.2 mm), untracked spans with empty
    data and spans with only the left eye tracked; ``events`` are (time, tag) markers."""
    import gzip
    import json
    from datetime import datetime
    folder.mkdir(parents=True, exist_ok=True)
    w, h = size
    writer = cv2.VideoWriter(str(folder / "scenevideo.mp4"), cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
    for g in grays:
        writer.write(np.full((h, w, 3), g, dtype=np.uint8))
    writer.release()
    duration = len(grays) / fps
    info = {"duration": duration, "name": "test",
            "gaze": {"file": "gazedata.gz", "samples": 0}, "events": {"file": "eventdata.gz"},
            "scenecamera": {"file": "scenevideo.mp4"}}
    if created is not None:
        info["created"] = created
    if timezone is not None:
        info["timezone"] = timezone
    if calibration:
        fx = w / 2 / np.tan(np.radians(45))          # pinhole with a 90° horizontal field
        info["scenecamera"]["camera-calibration"] = {"focal-length": [fx, fx], "principal-point": [w / 2, h / 2],
                                                     "resolution": [w, h]}
    inside = lambda t, spans: any(a <= t < b for a, b in spans)
    with gzip.open(folder / "gazedata.gz", "wt") as f:
        for t in np.arange(0, duration, 1 / rate):
            if inside(t, untracked):
                f.write(json.dumps({"type": "gaze", "timestamp": round(float(t), 4), "data": {}}) + "\n")
                continue
            d = pupil_mm(t) if callable(pupil_mm) else pupil_mm
            data = {"gaze2d": list(gaze), "eyeleft": {"pupildiameter": d}}
            if not inside(t, left_only):
                data["eyeright"] = {"pupildiameter": d + 0.2}
            f.write(json.dumps({"type": "gaze", "timestamp": round(float(t), 4), "data": data}) + "\n")
    with gzip.open(folder / "eventdata.gz", "wt") as f:
        for t, tag in events:
            f.write(json.dumps({"type": "event", "timestamp": t, "data": {"tag": tag, "object": None}}) + "\n")
        f.write(json.dumps({"type": "syncport", "timestamp": 1.0, "data": {"direction": "in", "value": 1}}) + "\n")
    (folder / "recording.g3").write_text(json.dumps(info))
    if lux is not None:
        epoch0 = datetime.fromisoformat((created or "2026-09-28T10:00:00Z").replace("Z", "+00:00")).timestamp()
        with open(folder / "1_1_1.csv", "w", newline="") as f:
            wr = csv.writer(f)
            for t in np.arange(-1, duration + 1, 0.1):
                wr.writerow([f"{(epoch0 + t) * 1000:.0f}", 1, 1, 1, lux(t)])
    return folder


@pytest.fixture
def isolated_qsettings(tmp_path_factory, monkeypatch):
    """The analysis window's saved settings (last folders, layout, sequence) in a temporary file, so a test neither
    reads nor changes the user's own."""
    from PySide6.QtCore import QSettings

    import cwtool.gui.main_window as main_window

    path = str(tmp_path_factory.mktemp("qsettings") / "settings.ini")
    monkeypatch.setattr(main_window, "QSettings", lambda *a, **k: QSettings(path, QSettings.IniFormat))
