"""TSL2591 lux sensor logs, in two formats.

The 1.x application, tools/lux_logger.py and the Arduino SD-card logger write one CSV per hour, named
``<month>_<day>_<hour>.csv``, with rows

    unix time (ms), ..., ..., ..., lux

(the middle columns are day/hour/minute or hour/minute/second). The SD-card logger uses the board's real-time
clock, which does not know about time zones and drifts; compensate with the time lag parameter, as in 1.x.

The sensor logger (cwtool.logger) writes a single ``lux.csv`` per recording with a header and rows

    unix time (s), lux

Without a TSL2591 log, the AS7341 spectral sensor's ``as7341.csv`` gives the lux instead, estimated from its eight
bands (:mod:`cwtool.spectral`). The TSL2591 comes first when both are there.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Optional

import numpy as np
from scipy.ndimage import median_filter

from cwtool import spectral

FILE_PATTERN = re.compile(r"^(\d{1,2}_\d{1,2}_\d{1,2}|lux)\.csv$")
SENSOR = "TSL2591"
SMOOTH_SAMPLES = 5   # the running median: 0.5 s at the TSL2591's 10 readings a second


def lux_files(folder: Path, recursive: bool = False) -> list[Path]:
    """The lux log files of ``folder`` (and of its subfolders with ``recursive``, e.g. one folder per day)."""
    folder = Path(folder)
    if not folder.is_dir():
        return []
    found = folder.rglob("*.csv") if recursive else folder.iterdir()
    return sorted(p for p in found if p.is_file() and FILE_PATTERN.match(p.name))


def _columns(path: Path) -> tuple[float, int, int]:
    """(seconds per time unit, time column, lux column) of a lux log: ``lux.csv`` has a header, Unix seconds
    and lux in the second column; the hourly files have Unix milliseconds and lux in the fifth."""
    try:
        with open(path, "rb") as f:
            header = f.readline().decode("utf-8", "ignore")
    except OSError:
        header = ""
    return (1.0, 0, 1) if header.startswith("unix time (s)") else (0.001, 0, 4)


def _span(path: Path):
    """(first, last) time in seconds of a lux log from its first and last rows without reading the file, or
    None if they cannot be read (the caller then reads the whole file)."""
    unit, tcol, _ = _columns(path)
    try:
        with open(path, "rb") as f:
            first = f.readline().decode("utf-8", "ignore").split(",")
            if unit == 1.0:  # skip the header
                first = f.readline().decode("utf-8", "ignore").split(",")
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(size - 512, 0))
            tail = [ln for ln in f.read().decode("utf-8", "ignore").splitlines() if ln.strip()]
        last = tail[-1].split(",")
        a, b = float(first[tcol]) * unit, float(last[tcol]) * unit
    except (OSError, ValueError, IndexError):
        return None
    return (a, b) if a <= b else None


def find_lux_folder(recording_folder: Path) -> Optional[Path]:
    """A folder with lux logs (or an AS7341 file) inside the recording, or its "lux" subfolder."""
    for candidate in (Path(recording_folder), Path(recording_folder) / "lux"):
        if lux_files(candidate) or spectral.files(candidate):
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
        unit, tcol, lcol = _columns(path)
        with open(path, newline="") as f:
            for row in csv.reader(f):
                if len(row) <= lcol:
                    continue
                try:
                    unix = float(row[tcol]) * unit
                    lux = float(row[lcol])
                except ValueError:
                    continue
                if t0 <= unix <= t1:
                    times.append(unix - epoch_start)
                    values.append(lux)
    order = np.argsort(times)
    return np.asarray(times, dtype=float)[order], np.asarray(values, dtype=float)[order]


def smooth(values: np.ndarray, size: int = SMOOTH_SAMPLES) -> np.ndarray:
    """Light smoothing of the log: a running median of ``size`` samples (5 for the TSL2591's ~10 Hz, 3 for the
    AS7341's 2.3-7.5 spectra a second), kept positive.

    A median keeps a step's timing and height and cannot overshoot, so a step into dim light cannot take the
    smoothed lux below zero, which gives NaN in the pupil model (open issue 63; 1.x and 2.0 up to November 2026
    used a Savitzky-Golay filter, 11 samples, order 6, which rings at a step). The result is held at or above
    the smallest positive reading, so a log with zeros (darkness) still gives a positive luminance."""
    values = np.asarray(values, dtype=float)
    if len(values) < size or size < 2:
        out = values.copy()
    else:
        out = median_filter(values, size=size, mode="nearest")
    positive = values[values > 0]
    if len(positive):
        out = np.maximum(out, positive.min())
    return out


def average_luminance(lux: np.ndarray, gain: float, offset: float, solid_angle: float) -> np.ndarray:
    """Average luminance (cd/m²) in the sensor's field of view: illuminance, optionally recalibrated
    (gain, offset), divided by the ratio of illuminance to luminance for the sensor in its housing
    (``solid_angle``, 2.2 for the TSL2591 kit; 1.x also applied gain 1.706061 and offset 0.66935)."""
    return (gain * np.asarray(lux, dtype=float) + offset) / solid_angle


def route(sensor: str) -> str:
    """The light sensor's part of a recording's route, for the operator."""
    if not sensor:
        return "no lux log"
    return "lux sensor" if sensor == SENSOR else f"lux estimated from the {sensor}'s bands"


def smoothing(sensor: str) -> int:
    """The running median's length for a sensor's log."""
    return spectral.SMOOTH_SAMPLES if sensor == spectral.SENSOR else SMOOTH_SAMPLES


def load_log(recording_folder: Path, lux_folder: Optional[Path], epoch_start: float, duration: float):
    """The lux readings for a recording: from ``lux_folder`` (searched with its subfolders) when one is given,
    else from a log in the recording folder or its ``lux`` subfolder. The TSL2591's log is used when it covers the
    recording; otherwise the AS7341's estimate (:mod:`cwtool.spectral`). Returns (time, lux, notes, sensor), the
    arrays None and the sensor empty if there are no readings; the notes say why when a given folder yields none."""
    notes: list[str] = []
    if lux_folder:
        folder = Path(lux_folder)
        if not folder.is_dir():
            return None, None, [f"The lux folder {folder} does not exist."], ""
        recursive = True
    else:
        folder, recursive = find_lux_folder(recording_folder), False
        if folder is None:
            return None, None, notes, ""
    t, v = read_lux(folder, epoch_start, duration, recursive=recursive)
    if len(t):
        return t, v, notes, SENSOR
    t, v = spectral.read(folder, epoch_start, duration, recursive=recursive)
    if len(t):
        notes.append("No TSL2591 lux log: the lux is estimated from the AS7341's spectral bands with the datasheet's "
                     "typical curves (about 10 % for a sensor not calibrated; open issue 58).")
        return t, v, notes, spectral.SENSOR
    if lux_folder:
        n = len(lux_files(folder, recursive=True)) + len(spectral.files(folder, recursive=True))
        notes.append(f"No lux readings in {folder} overlap this recording ({n} log files found): check the folder "
                     "and that the logger's clock matches the tracker's.")
    return None, None, notes, ""
