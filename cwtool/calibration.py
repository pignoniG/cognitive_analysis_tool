"""Full-field calibration sequences: the built-in 20-step sequence or one read
from the timestamped RGB CSV that drives the Unity calibration scene."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

import numpy as np

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


def scaled(sequence: Sequence, factor: float) -> Sequence:
    """The sequence with every step's timing multiplied by ``factor``."""
    if abs(factor - 1.0) < 1e-6:
        return sequence
    steps = tuple(Step(s.start * factor, s.end * factor, s.rgb, s.label) for s in sequence.steps)
    return Sequence(steps, f"{sequence.name} ×{factor:.3g}")


@dataclass(frozen=True)
class Location:
    start: float          # s, recording time of the sequence start
    sequence: Sequence    # possibly rescaled to the recording's step length
    error: float          # relative RMS error of the colour match (0 = perfect)


def _change_points(time, rgb, threshold=8.0, min_gap=0.3):
    jumps = np.flatnonzero(np.abs(np.diff(rgb, axis=0)).max(axis=1) > threshold)
    out = []
    for i in jumps:
        if not out or time[i + 1] - out[-1] > min_gap:
            out.append(time[i + 1])
    return np.asarray(out)


def locate(time: np.ndarray, rgb: np.ndarray, sequence: Sequence, gamma: float = 2.2) -> Location | None:
    """Find ``sequence`` in a recording from the measured scene colour ``rgb`` (N, 3, code
    values) at ``time`` (s). Step changes in the colour give candidate starts and the step
    length; each candidate is scored by how well the sequence's colours, with one gain per
    channel (recorded levels are lower than nominal), explain the measured colours."""
    order = np.argsort(time)
    t, c = np.asarray(time)[order], np.asarray(rgb, dtype=float)[order]
    changes = _change_points(t, c)
    if len(changes) < 3 or not sequence.steps:
        return None
    lengths = np.array([s.end - s.start for s in sequence.steps])
    factors = {1.0}
    if np.allclose(lengths, lengths[0], rtol=0.02):
        gaps = np.diff(changes)
        typical = np.median(gaps[gaps > 0.5]) if (gaps > 0.5).any() else lengths[0]
        factors.add(round(float(typical / lengths[0]), 3))

    grid = np.arange(t[0], t[-1], 0.1)
    measured = (np.stack([np.interp(grid, t, c[:, k]) for k in range(3)], axis=1) / 255.0) ** gamma
    best = None
    for factor in factors:
        seq = scaled(sequence, factor)
        starts_rel = np.array([s.start for s in seq.steps])
        colours = (np.array([s.rgb for s in seq.steps], dtype=float) / 255.0) ** gamma
        for change in changes:
            for rel in starts_rel:
                start = change - rel
                inside = (grid >= start) & (grid < start + seq.duration)
                if inside.sum() < 10:
                    continue
                # Skip the first half second of every step: the video changes a frame late.
                phase = grid[inside] - start
                k = np.clip(np.searchsorted(starts_rel, phase, side="right") - 1, 0, len(starts_rel) - 1)
                settled = phase - starts_rel[k] > 0.5
                exp, mea = colours[k][settled], measured[inside][settled]
                if len(exp) < 10:
                    continue
                gain = (exp * mea).sum(axis=0) / np.maximum((exp * exp).sum(axis=0), 1e-9)
                err = np.sqrt(np.mean((mea - exp * gain) ** 2)) / max(np.sqrt(np.mean(mea ** 2)), 1e-9)
                if best is None or err < best.error:
                    best = Location(float(start), seq, float(err))
    return best
