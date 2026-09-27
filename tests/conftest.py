import csv
from pathlib import Path

import cv2
import numpy as np
import pytest

from cwtool.devices import varjo


def write_varjo_recording(folder: Path, grays, seconds_per_level=1.0, fps=10, size=(64, 48),
                          gaze=(0.0, 0.0), pupil_mm=2.0, rate=100):
    """Synthetic Varjo recording: a full-frame gray level or RGB colour per step and a constant gaze.
    ``pupil_mm`` is the value written to the CSV, which Varjo reports as a radius (×2 = diameter)."""
    folder.mkdir(parents=True, exist_ok=True)
    w, h = size
    writer = cv2.VideoWriter(str(folder / "varjo_capture_test.avi"), cv2.VideoWriter_fourcc(*"MJPG"), fps, (w, h))
    for g in grays:
        bgr = (g, g, g) if np.isscalar(g) else tuple(reversed(g))  # a level or an (R, G, B) colour
        for _ in range(int(seconds_per_level * fps)):
            writer.write(np.full((h, w, 3), bgr, dtype=np.uint8))
    writer.release()

    n = int(len(grays) * seconds_per_level * rate)
    with open(folder / "varjo_gaze_output_test.csv", "w", newline="") as f:
        wr = csv.writer(f)
        wr.writerow([f"c{i}" for i in range(varjo.COL_RIGHT_PUPIL_MM + 2)])
        for i in range(n):
            row = ["0"] * (varjo.COL_RIGHT_PUPIL_MM + 2)
            t_ns = int(i * 1e9 / rate)
            row[varjo.COL_EPOCH_NS] = str(1_700_000_000 * 10**9 + t_ns)
            row[varjo.COL_RELATIVE_NS] = str(t_ns)
            for c in (varjo.COL_STATUS, varjo.COL_LEFT_STATUS, varjo.COL_RIGHT_STATUS):
                row[c] = "3"
            row[varjo.COL_LEFT_PROJ_X] = row[varjo.COL_RIGHT_PROJ_X] = str(gaze[0])
            row[varjo.COL_LEFT_PROJ_Y] = row[varjo.COL_RIGHT_PROJ_Y] = str(gaze[1])
            p = pupil_mm(i / rate) if callable(pupil_mm) else pupil_mm
            row[varjo.COL_LEFT_PUPIL_MM] = row[varjo.COL_RIGHT_PUPIL_MM] = str(p)
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
