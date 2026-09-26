"""Full-field calibration sequences: the built-in 20-step sequence or one read
from the timestamped RGB CSV that drives the Unity calibration scene."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

STEP_SECONDS = 6.0


@dataclass(frozen=True)
class Step:
    start: float        # s from sequence start
    end: float
    rgb: tuple[int, int, int]
    label: str


@dataclass(frozen=True)
class Sequence:
    steps: tuple[Step, ...]
    name: str

    @property
    def duration(self) -> float:
        return self.steps[-1].end if self.steps else 0.0


def _build_default() -> Sequence:
    colours = [(f"Gray {v}", (v, v, v)) for v in (0, 36, 73, 109, 146, 182, 219, 255)]
    for name, axis in (("Red", 0), ("Green", 1), ("Blue", 2)):
        for v in (64, 128, 191, 255):
            rgb = [0, 0, 0]
            rgb[axis] = v
            colours.append((f"{name} {v}", tuple(rgb)))
    steps = tuple(Step(i * STEP_SECONDS, (i + 1) * STEP_SECONDS, rgb, label)
                  for i, (label, rgb) in enumerate(colours))
    return Sequence(steps, "built-in 20 steps")


DEFAULT = _build_default()

_TIME_NAMES = ("time", "t", "timestamp", "start", "seconds", "onset")
_CHANNELS = (("r", "red"), ("g", "green"), ("b", "blue"))


def _column(header: list[str], names) -> int | None:
    for i, h in enumerate(header):
        key = h.strip().lower().split("(")[0].strip().replace("_s", "").replace("_ms", "")
        if key in names:
            return i
    return None


def load_sequence(path: str | Path) -> Sequence:
    """Read a sequence CSV: one row per step with its start time and colour.

    Accepted layouts: a header with a time column (time/t/timestamp/start/onset, in s,
    or ms if the header says "ms") and R, G, B columns (r/red, ...), optionally
    ``duration`` and ``label``; or four unlabelled columns time, R, G, B. Colours may
    be 0-255 or 0-1. A step lasts until the next one starts; the last one uses its
    duration column, or the median step length.
    """
    path = Path(path)
    with open(path, newline="") as f:
        rows = [r for r in csv.reader(f) if r and r[0].strip() and not r[0].lstrip().startswith("#")]
    if not rows:
        raise ValueError(f"{path.name} has no rows")

    def numeric(row):
        try:
            [float(x) for x in row[:4]]
            return True
        except ValueError:
            return False

    ms = False
    if numeric(rows[0]):
        t_col, rgb_cols, dur_col, label_col = 0, (1, 2, 3), None, None
    else:
        header, rows = rows[0], rows[1:]
        t_col = _column(header, _TIME_NAMES)
        rgb_cols = tuple(_column(header, names) for names in _CHANNELS)
        if t_col is None or None in rgb_cols:
            raise ValueError(f"{path.name}: need a time column and R, G, B columns, got {header}")
        ms = "ms" in header[t_col].lower()
        dur_col = _column(header, ("duration", "dur", "length"))
        label_col = _column(header, ("label", "name", "colour", "color"))

    starts = [float(r[t_col]) / (1000 if ms else 1) for r in rows]
    colours = [[float(r[c]) for c in rgb_cols] for r in rows]
    if colours and max(max(c) for c in colours) <= 1.0:
        colours = [[v * 255 for v in c] for c in colours]
    colours = [tuple(int(round(v)) for v in c) for c in colours]
    t0 = starts[0]
    starts = [s - t0 for s in starts]
    if any(b <= a for a, b in zip(starts, starts[1:])):
        raise ValueError(f"{path.name}: step times must increase")

    lengths = [b - a for a, b in zip(starts, starts[1:])]
    if dur_col is not None and rows[-1][dur_col].strip():
        last = float(rows[-1][dur_col]) / (1000 if ms else 1)
    else:
        last = sorted(lengths)[len(lengths) // 2] if lengths else STEP_SECONDS
    ends = starts[1:] + [starts[-1] + last]

    steps = []
    for i, (s, e, rgb) in enumerate(zip(starts, ends, colours)):
        label = rows[i][label_col].strip() if label_col is not None and rows[i][label_col].strip() \
            else f"RGB {rgb[0]}, {rgb[1]}, {rgb[2]}"
        steps.append(Step(s, e, rgb, label))
    return Sequence(tuple(steps), path.name)
