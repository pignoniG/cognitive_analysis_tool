"""TSL2591 lux sensor logs, as written by tools/lux_logger.py (computer) or the
Arduino SD-card logger.

Both write one CSV per hour, named ``<month>_<day>_<hour>.csv``, with rows

    unix time (ms), ..., ..., ..., lux

(the middle columns are day/hour/minute or hour/minute/second). The SD-card
logger uses the board's real-time clock, which does not know about time zones
and drifts; compensate with the time lag parameter, as in 1.x.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Optional

import numpy as np
from scipy.signal import savgol_filter

FILE_PATTERN = re.compile(r"^\d{1,2}_\d{1,2}_\d{1,2}\.csv$")


def lux_files(folder: Path, recursive: bool = False) -> list[Path]:
    """The lux log files of ``folder`` (and of its subfolders with ``recursive``, e.g. one folder per day)."""
    folder = Path(folder)
    if not folder.is_dir():
        return []
    found = folder.rglob("*.csv") if recursive else folder.iterdir()
    return sorted(p for p in found if p.is_file() and FILE_PATTERN.match(p.name))


def _span(path: Path):
    """(first, last) time in seconds of a lux log from its first and last rows without reading the file, or
    None if they cannot be read (the caller then reads the whole file)."""
    try:
        with open(path, "rb") as f:
            first = f.readline().decode("utf-8", "ignore").split(",")
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(size - 512, 0))
            tail = [ln for ln in f.read().decode("utf-8", "ignore").splitlines() if ln.strip()]
        last = tail[-1].split(",")
        a, b = float(first[0]) / 1000.0, float(last[0]) / 1000.0
    except (OSError, ValueError, IndexError):
        return None
    return (a, b) if a <= b else None


def find_lux_folder(recording_folder: Path) -> Optional[Path]:
    """A folder with lux logs inside the recording, or its "lux" subfolder."""
    for candidate in (Path(recording_folder), Path(recording_folder) / "lux"):
        if lux_files(candidate):
            return candidate
    return None


def read_lux(folder: Path, epoch_start: float, duration: float, margin: float = 60.0, recursive: bool = False):
    """Lux readings overlapping a recording, on its relative clock (s).
    Returns (time, lux) sorted by time; empty arrays if none overlap. Files whose first and last rows lie
    outside the recording are not read, so a folder with many logs stays fast."""
    t0, t1 = epoch_start - margin, epoch_start + duration + margin
    times, values = [], []
    for path in lux_files(folder, recursive):
        span = _span(path)
        if span is not None and (span[1] < t0 or span[0] > t1):
            continue
        with open(path, newline="") as f:
            for row in csv.reader(f):
                if len(row) < 5:
                    continue
                try:
                    unix = float(row[0]) / 1000.0
                    lux = float(row[4])
                except ValueError:
                    continue
                if t0 <= unix <= t1:
                    times.append(unix - epoch_start)
                    values.append(lux)
    order = np.argsort(times)
    return np.asarray(times, dtype=float)[order], np.asarray(values, dtype=float)[order]


def smooth(values: np.ndarray) -> np.ndarray:
    """Light smoothing of the ~10 Hz log (Savitzky-Golay, 11 samples, order 6, as in 1.x)."""
    if len(values) < 11:
        return values
    return savgol_filter(values, 11, 6)


def average_luminance(lux: np.ndarray, gain: float, offset: float, solid_angle: float) -> np.ndarray:
    """Average luminance (cd/m²) in the sensor's field of view: illuminance, optionally recalibrated
    (gain, offset), divided by the ratio of illuminance to luminance for the sensor in its housing
    (``solid_angle``, 2.2 for the TSL2591 kit; 1.x also applied gain 1.706061 and offset 0.66935)."""
    return (gain * np.asarray(lux, dtype=float) + offset) / solid_angle


def load_log(recording_folder: Path, lux_folder: Optional[Path], epoch_start: float, duration: float):
    """The lux readings for a recording: from ``lux_folder`` (searched with its subfolders) when one is given,
    else from a log in the recording folder or its ``lux`` subfolder. Returns (time, lux, notes), the arrays
    None if there are no readings; the notes say why when a given folder yields none."""
    notes: list[str] = []
    if lux_folder:
        folder = Path(lux_folder)
        if not folder.is_dir():
            return None, None, [f"The lux folder {folder} does not exist."]
        recursive = True
    else:
        folder, recursive = find_lux_folder(recording_folder), False
        if folder is None:
            return None, None, notes
    t, v = read_lux(folder, epoch_start, duration, recursive=recursive)
    if len(t):
        return t, v, notes
    if lux_folder:
        n = len(lux_files(folder, recursive=True))
        notes.append(f"No lux readings in {folder} overlap this recording ({n} log files found): check the folder "
                     "and that the logger's clock matches the tracker's.")
    return None, None, notes
