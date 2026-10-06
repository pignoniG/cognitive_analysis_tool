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
from dataclasses import dataclass
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

    @property
    def long(self) -> bool:
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
        mask = np.asarray(mask, dtype=bool)
        return Sensor(self.name, self.kind, self.path, self.header, self.unix[mask],
                      {k: v[mask] for k, v in self.data.items()})

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


def load_sensors(folder: Path, epoch_start: float, duration: float, margin: float = 30.0) -> list[Sensor]:
    """The sensors of a session folder, cut to a recording that starts at Unix time ``epoch_start`` and lasts
    ``duration`` seconds (with ``margin`` on both sides). Sensors with no rows in that span are left out."""
    t0, t1 = epoch_start - margin, epoch_start + duration + margin
    out = []
    for path, kind in find_sensor_files(folder):
        try:
            sensor = read_sensor(path, kind, t0, t1)
        except ValueError:
            continue
        if len(sensor):
            out.append(sensor)
    return out
