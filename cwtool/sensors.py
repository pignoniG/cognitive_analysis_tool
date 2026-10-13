"""Sensor files written by the sensor logger (:mod:`cwtool.logger`): the Shimmer, the EmotiBit, and any other
sensor with a CSV that starts with the Unix time.

A logger session folder holds one file per sensor. The analysis does not use these signals; they are read to be
shown next to ΔPD and to be exported together with it, trimmed to the same time span, as one package.

    unix time (s), <channel>, ...             wide: one column per channel (the Shimmer)
    unix time (s), signal, value              long: one row per sample (the EmotiBit's streams of different rates)
"""

from __future__ import annotations

import csv
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np

TIME_COLUMN = "unix time (s)"
NOT_SENSORS = ("lux",)   # the lux log is read by the analysis itself (cwtool.lux)


@dataclass
class Sensor:
    """The rows of one sensor file that were read (a time span of it), on the Unix clock."""

    name: str                          # file stem, e.g. "shimmer"
    kind: str                          # "shimmer", "emotibit", ... (from session.json, else the name)
    path: Path
    header: list
    unix: np.ndarray                   # s, one per row
    data: dict                         # wide: column -> values; long: "signal" (strings) and "value"
    settings: dict = field(default_factory=dict)   # what the logger saved for the sensor in session.json

    @property
    def long(self) -> bool:
        """True for the long layout of the file (one row per sample with a signal name), as the EmotiBit's."""
        return self.header[1:] == ["signal", "value"]

    def signals(self) -> list[str]:
        """The names to choose from for a plot: the channels, or the signals of a long file in first-seen order."""
        if not self.long:
            return list(self.header[1:])
        return list(dict.fromkeys(self.data["signal"].tolist()))

    def series(self, signal: str):
        """(Unix time, values) of one signal."""
        if self.long:
            sel = self.data["signal"] == signal
            return self.unix[sel], self.data["value"][sel]
        return self.unix, self.data[signal]

    def select(self, mask) -> "Sensor":
        """The sensor with only the rows where ``mask`` is True."""
        mask = np.asarray(mask, dtype=bool)
        return Sensor(self.name, self.kind, self.path, self.header, self.unix[mask],
                      {k: v[mask] for k, v in self.data.items()}, self.settings)

    def __len__(self) -> int:
        return len(self.unix)

    def write_csv(self, path: Path, epoch_start: float) -> None:
        """The rows as an export file: the Unix time, the time from the recording's start, then the file's own
        columns (raw values, as logged)."""
        cols = [self.data[c] for c in (["signal", "value"] if self.long else self.header[1:])]
        with open(path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["timestamp_unix", "timestamp_relative"] + self.header[1:])
            for i, t in enumerate(self.unix):
                w.writerow([f"{t:.6f}", f"{t - epoch_start:.6f}"]
                           + [c[i] if isinstance(c[i], str) else f"{c[i]:.9g}" for c in cols])


def read_sensor(path: Path, kind: str = "", t_from: float = -math.inf, t_to: float = math.inf) -> Sensor:
    """Read the rows of a logger file with Unix times in [``t_from``, ``t_to``]. Raises ``ValueError`` if it
    does not look like one."""
    path = Path(path)
    with open(path, newline="") as f:
        reader = csv.reader(f)
        header = next(reader, None)
        if not header or header[0].strip() != TIME_COLUMN:
            raise ValueError(f"{path.name} is not a sensor logger file (it must start with '{TIME_COLUMN}')")
        header = [h.strip() for h in header]
        long = header[1:] == ["signal", "value"]
        times, rows, signals = [], [], []
        for row in reader:
            try:
                t = float(row[0])
            except (ValueError, IndexError):
                continue
            if not t_from <= t <= t_to:
                continue
            times.append(t)
            if long:
                signals.append(row[1])
                rows.append(_number(row[2]) if len(row) > 2 else math.nan)
            else:
                rows.append([_number(v) for v in row[1:len(header)]] + [math.nan] * (len(header) - len(row)))
    unix = np.asarray(times, dtype=float)
    if long:
        data = {"signal": np.asarray(signals, dtype=object), "value": np.asarray(rows, dtype=float)}
    else:
        table = np.asarray(rows, dtype=float).reshape(len(times), len(header) - 1)
        data = {name: table[:, i] for i, name in enumerate(header[1:])}
    return Sensor(path.stem, kind or _kind_from_name(path.stem), path, header, unix, data)


def _number(text: str) -> float:
    try:
        return float(text)
    except ValueError:
        return math.nan


def _kind_from_name(name: str) -> str:
    for kind in ("shimmer", "emotibit"):
        if name.lower().startswith(kind):
            return kind
    return "sensor"


def find_sensor_files(folder: Path) -> list[tuple[Path, str]]:
    """(file, kind) of the sensor files in a logger session folder, or in any folder with such files. The
    session's ``session.json`` names them; without it the CSVs that start with the Unix time column are taken.
    The lux log is left out (the analysis reads it)."""
    folder = Path(folder)
    manifest = folder / "session.json"
    found: list[tuple[Path, str]] = []
    if manifest.exists():
        try:
            sources = json.loads(manifest.read_text()).get("sources", {})
            for name, info in sources.items():
                path = folder / info.get("file", f"{name}.csv")
                if info.get("kind") not in NOT_SENSORS and path.exists():
                    found.append((path, info.get("kind", "")))
        except (OSError, ValueError, AttributeError):
            found = []
    if not found and folder.is_dir():
        for path in sorted(folder.glob("*.csv")):
            if path.stem in NOT_SENSORS:
                continue
            try:
                with open(path, newline="") as f:
                    first = next(csv.reader(f), [""])
            except OSError:
                continue
            if first and first[0].strip() == TIME_COLUMN:
                found.append((path, ""))
    return found


def sensor_settings(folder: Path) -> dict:
    """The settings the logger saved for each sensor in the session's ``session.json`` (sampling rate, the ECG's gain
    ...), by the sensor's file name stem; empty without a manifest."""
    try:
        sources = json.loads((Path(folder) / "session.json").read_text()).get("sources", {})
        return {Path(info.get("file", f"{name}.csv")).stem: info.get("settings", {}) for name, info in sources.items()}
    except (OSError, ValueError, AttributeError):
        return {}


def _file_span(path: Path) -> Optional[tuple[float, float]]:
    """(first, last) Unix time of a sensor file, from its first row and its last (read from the end of the file, so a
    long file costs nothing); None if it has no rows or does not start with the time column."""
    try:
        with open(path, "rb") as f:
            header = f.readline().decode("utf-8", "replace").split(",")
            if header[0].strip() != TIME_COLUMN:
                return None
            first = f.readline().decode("utf-8", "replace").split(",")[0]
            f.seek(0, 2)
            f.seek(max(f.tell() - 4096, 0))
            tail = f.read().decode("utf-8", "replace").strip().splitlines()
        return float(first), float(tail[-1].split(",")[0])
    except (OSError, ValueError, IndexError):
        return None


def session_span(folder: Path) -> Optional[tuple[float, float]]:
    """The Unix time a logger session folder covers: ``start`` and ``end`` of its ``session.json``, or, if it has no
    end (the logger was stopped by a crash) or no manifest, the first and last rows of its sensor files; None if it has
    neither."""
    folder = Path(folder)
    start = end = None
    try:
        info = json.loads((folder / "session.json").read_text())
        start, end = info.get("start (unix s)"), info.get("end (unix s)")
    except (OSError, ValueError, AttributeError):
        pass
    if not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
        spans = [s for s in (_file_span(path) for path, _ in find_sensor_files(folder)) if s]
        if not spans:
            return (float(start), float(start)) if isinstance(start, (int, float)) else None
        start = min(s[0] for s in spans) if not isinstance(start, (int, float)) else start
        end = max(s[1] for s in spans)
    return float(start), float(end)


def is_session(folder: Path) -> bool:
    """True if the folder is one logger session (it holds sensor files); False for the logger's recordings folder, which
    holds the sessions."""
    return bool(find_sensor_files(Path(folder)))


def resolve_session(folder: Path, epoch_start: float, duration: float) -> tuple[Optional[Path], float]:
    """The logger session to use for a recording that starts at Unix time ``epoch_start`` and lasts ``duration`` seconds,
    and how many seconds of it the session covers. ``folder`` is a session itself (it is used as it is) or the logger's
    recordings folder: the session in it that overlaps the recording most is chosen, so that one folder can be given for
    all recordings. (None, 0.0) if no session overlaps."""
    folder = Path(folder)
    if is_session(folder):
        span = session_span(folder)
        overlap = max(0.0, min(span[1], epoch_start + duration) - max(span[0], epoch_start)) if span else 0.0
        return folder, overlap
    best, best_overlap = None, 0.0
    try:
        candidates = sorted(p for p in folder.iterdir() if p.is_dir())
    except OSError:
        return None, 0.0
    for candidate in candidates:
        span = session_span(candidate) if is_session(candidate) else None
        if span is None:
            continue
        overlap = min(span[1], epoch_start + duration) - max(span[0], epoch_start)
        if overlap > best_overlap:
            best, best_overlap = candidate, overlap
    return best, best_overlap


def load_sensors(folder: Path, epoch_start: float, duration: float, margin: float = 30.0) -> list[Sensor]:
    """The sensors of a session folder, cut to a recording that starts at Unix time ``epoch_start`` and lasts
    ``duration`` seconds (with ``margin`` on both sides). ``folder`` may be the logger's recordings folder instead of one
    session: the session that overlaps the recording is used (:func:`resolve_session`). Sensors with no rows in that
    span are left out."""
    resolved, _ = resolve_session(folder, epoch_start, duration)
    if resolved is None:
        return []
    folder = resolved
    t0, t1 = epoch_start - margin, epoch_start + duration + margin
    settings = sensor_settings(folder)
    out = []
    for path, kind in find_sensor_files(folder):
        try:
            sensor = read_sensor(path, kind, t0, t1)
        except ValueError:
            continue
        if len(sensor):
            sensor.settings = settings.get(sensor.name, {})
            out.append(sensor)
    return out
