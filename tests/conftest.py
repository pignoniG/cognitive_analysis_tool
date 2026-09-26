import csv
from pathlib import Path

import cv2
import numpy as np
import pytest

from cwtool.devices import varjo


def write_varjo_recording(folder: Path, grays, seconds_per_level=1.0, fps=10, size=(64, 48),
                          gaze=(0.0, 0.0), pupil_mm=4.0, rate=100):
    """Synthetic Varjo recording: a full-frame gray level per step and a constant gaze."""
    folder.mkdir(parents=True, exist_ok=True)
    w, h = size
    writer = cv2.VideoWriter(str(folder / "varjo_capture_test.avi"), cv2.VideoWriter_fourcc(*"MJPG"), fps, (w, h))
    for g in grays:
        for _ in range(int(seconds_per_level * fps)):
            writer.write(np.full((h, w, 3), g, dtype=np.uint8))
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
