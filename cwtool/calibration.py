"""Full-field calibration sequences: the calibration presenter's default (``DEFAULT``), the 20-step staircase
used before October 2026 (``STAIRCASE_20``), or one read from a sequence CSV or a presenter run file."""

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
    linked: bool = False  # moves with the previous step when the order is scrambled (presenter's "keep")


@dataclass(frozen=True)
class Sequence:
    steps: tuple[Step, ...]
    name: str

    @property
    def duration(self) -> float:
        return self.steps[-1].end if self.steps else 0.0


def _build_staircase() -> Sequence:
    colours = [(f"Gray {v}", (v, v, v)) for v in (0, 36, 73, 109, 146, 182, 219, 255)]
    for name, axis in (("Red", 0), ("Green", 1), ("Blue", 2)):
        for v in (64, 128, 191, 255):
            rgb = [0, 0, 0]
            rgb[axis] = v
            colours.append((f"{name} {v}", tuple(rgb)))
    steps = tuple(Step(i * STEP_SECONDS, (i + 1) * STEP_SECONDS, rgb, label)
                  for i, (label, rgb) in enumerate(colours))
    return Sequence(steps, "20-step staircase (before October 2026)")


# The ascending staircase that cwtool used until October 2026 (the seven Varjo calibration recordings of April 2026,
# played with 10 s steps). Its fixed ascending order confounds luminance with time (open issues 36, 41, 43).
STAIRCASE_20 = _build_staircase()


# ---------------------------------------------------------------------------------------------------
# The calibration presenter's sequences (docs/calibration-tool/index.html), ported exactly: the same seed gives the
# same order in the presenter and here, so a participant's run can be regenerated from its seed.

_M32 = 0xFFFFFFFF


def _imul(a: int, b: int) -> int:
    return (a * b) & _M32


def _xmur3(text: str):
    units = memoryview(text.encode("utf-16-le")).cast("H")      # JavaScript's charCodeAt
    h = (1779033703 ^ len(units)) & _M32
    for c in units:
        h = _imul(h ^ c, 3432918353)
        h = ((h << 13) & _M32) | (h >> 19)

    def next_hash() -> int:
        nonlocal h
        h = _imul(h ^ (h >> 16), 2246822507)
        h = _imul(h ^ (h >> 13), 3266489909)
        h ^= h >> 16
        return h
    return next_hash


def _mulberry32(a: int):
    def rng() -> float:
        nonlocal a
        a = (a + 0x6D2B79F5) & _M32
        t = _imul(a ^ (a >> 15), 1 | a)
        t = ((t + _imul(t ^ (t >> 7), 61 | t)) & _M32) ^ t
        return ((t ^ (t >> 14)) & _M32) / 4294967296
    return rng


def _rng(seed) -> callable:
    return _mulberry32(_xmur3(str(seed))())


def _srgb_luminance(rgb) -> float:
    """Y of an sRGB colour (Eckert et al. 2022, eq. 1), as the presenter orders brightness."""
    def lin(c):
        c = c / 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = rgb
    return 0.2125 * lin(r) + 0.7154 * lin(g) + 0.072 * lin(b)


def _scramble(items: list, linked: list, seed, avoid: bool = True) -> list:
    """The presenter's ``scrambleIndices``: indices of ``items`` (each an RGB) in a seeded pseudo-random order,
    linked items moving with their predecessor; with ``avoid``, no two consecutive groups neighbours in
    brightness rank (Eckert et al. 2022), the first of 4000 shuffles that achieves it, else the best."""
    groups = []
    for i, keep in enumerate(linked):
        if keep and groups:
            groups[-1].append(i)
        else:
            groups.append([i])
    n, rng = len(groups), _rng(seed)
    ranked = sorted(range(n), key=lambda g: (_srgb_luminance(items[groups[g][-1]]), g))
    rank = [0] * n
    for k, g in enumerate(ranked):
        rank[g] = k
    best, best_bad = None, float("inf")
    for _ in range(4000):
        order = list(range(n))
        for i in range(n - 1, 0, -1):
            j = int(rng() * (i + 1))
            order[i], order[j] = order[j], order[i]
        bad = sum(abs(rank[order[i]] - rank[order[i - 1]]) == 1 for i in range(1, n)) if avoid and n >= 4 else 0
        if bad == 0:
            best = order
            break
        if bad < best_bad:
            best, best_bad = order, bad
    return [i for g in best for i in groups[g]]


def _sequence(items, name: str) -> Sequence:
    """Sequence from (label, rgb, seconds, linked) items played back to back."""
    steps, t = [], 0.0
    for label, rgb, seconds, linked in items:
        steps.append(Step(t, t + seconds, tuple(rgb), label, linked))
        t += seconds
    return Sequence(tuple(steps), name)


PRESET_SEED = "calibration"    # the presenter's seed for its presets


def full_calibration(seed=PRESET_SEED) -> Sequence:
    """The presenter's default sequence ("Full calibration"): the 8 grays of Eckert et al. (2022), longer the
    darker (20, 15, 10, 8, 6, 6, 6 and 12 s); R, G, B at 64, 128, 191 and 255 for 8 s, each after a linked 8 s
    black step; grays 73 and 182 repeated for 8 s. 34 steps, 291 s, in the presenter's pseudo-random order for
    ``seed`` (no two consecutive levels next to each other in brightness)."""
    lengths = {0: 20, 36: 15, 73: 10, 109: 8, 146: 6, 182: 6, 219: 6, 255: 12}
    items = [(f"Gray {v}", (v, v, v), lengths[v], False) for v in lengths]
    for name, axis in (("Red", 0), ("Green", 1), ("Blue", 2)):
        for v in (64, 128, 191, 255):
            rgb = [0, 0, 0]
            rgb[axis] = v
            items += [("Black", (0, 0, 0), 8, False), (f"{name} {v}", tuple(rgb), 8, True)]
    items += [(f"Gray {v} (repeat)", (v, v, v), 8, False) for v in (73, 182)]
    order = _scramble([it[1] for it in items], [it[3] for it in items], seed)
    return _sequence([items[i] for i in order], "full calibration (presenter default)")


def scrambled(sequence: Sequence, seed, avoid: bool = True) -> Sequence:
    """``sequence`` in the order the presenter plays it with the given seed ("Scrambled, seeded by participant":
    the seed is the participant ID unless one is typed). A run file saved by the presenter records the order
    played and is the safer source."""
    steps = sequence.steps
    order = _scramble([st.rgb for st in steps], [st.linked for st in steps], seed, avoid)
    return _sequence([(steps[i].label, steps[i].rgb, steps[i].end - steps[i].start, steps[i].linked)
                      for i in order], f"{sequence.name}, order {seed}")


# The default: the presenter's default sequence in its preset order. A participant's run is usually scrambled
# again with their ID (load the run file, or use ``scrambled(DEFAULT, participant_id)``).
DEFAULT = full_calibration()

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
    keep_col = None
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
        keep_col = _column(header, ("keep", "linked"))

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
        linked = keep_col is not None and keep_col < len(rows[i]) and \
            rows[i][keep_col].strip().lower() in ("1", "true", "yes")
        steps.append(Step(s, e, rgb, label, linked))
    return Sequence(tuple(steps), path.name)


def run_start_unix(path: str | Path) -> float | None:
    """Unix time (s) of the first step of a calibration presenter run file (its ``onset_unix_ms`` column,
    on the presenting computer's clock), or None for a file without one."""
    with open(path, newline="") as f:
        rows = [r for r in csv.reader(f) if r and r[0].strip() and not r[0].lstrip().startswith("#")]
    if len(rows) < 2:
        return None
    header = [h.strip().lower() for h in rows[0]]
    if "onset_unix_ms" not in header:
        return None
    try:
        return float(rows[1][header.index("onset_unix_ms")]) / 1000.0
    except (ValueError, IndexError):
        return None


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
    coverage: float = 1.0  # fraction of the sequence with analysed video (tracking gaps have none)


MAX_VIDEO_GAP = 0.5     # s; farther from an analysed video sample, the colour is unknown
MIN_COVERAGE = 0.5      # fraction of a candidate window that must have analysed video


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
    channel (recorded levels are lower than nominal), explain the measured colours.

    Only times with analysed video are scored: the video is analysed at valid gaze samples, so
    tracking gaps have no colour, and interpolating across them would invent one. A candidate
    must lie within the recording (give or take its first and last step, which may have begun
    before the recording or been cut short) and have video for at least MIN_COVERAGE of its
    duration; otherwise a start near the end, scored on the few seconds inside, could win."""
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

    def analysed(times):
        i = np.clip(np.searchsorted(t, times), 1, len(t) - 1)
        nearest = np.minimum(np.abs(times - t[i - 1]), np.abs(t[i] - times))
        return (times >= t[0]) & (times <= t[-1]) & (nearest <= MAX_VIDEO_GAP)

    best = None
    for factor in factors:
        seq = scaled(sequence, factor)
        starts_rel = np.array([s.start for s in seq.steps])
        colours = (np.array([s.rgb for s in seq.steps], dtype=float) / 255.0) ** gamma
        first, last = seq.steps[0].end - seq.steps[0].start, seq.steps[-1].end - seq.steps[-1].start
        phase = np.arange(0.0, seq.duration, 0.1)
        k = np.clip(np.searchsorted(starts_rel, phase, side="right") - 1, 0, len(starts_rel) - 1)
        # Skip the first half second of every step: the video changes a frame late.
        settled = phase - starts_rel[k] > 0.5
        phase, k = phase[settled], k[settled]
        for change in changes:
            for rel in starts_rel:
                start = change - rel
                if start < t[0] - first or start + seq.duration > t[-1] + last:
                    continue
                have = analysed(start + phase)
                coverage = float(have.mean()) if len(have) else 0.0
                if coverage < MIN_COVERAGE or have.sum() < 10:
                    continue
                times = start + phase[have]
                mea = (np.stack([np.interp(times, t, c[:, j]) for j in range(3)], axis=1) / 255.0) ** gamma
                exp = colours[k[have]]
                gain = (exp * mea).sum(axis=0) / np.maximum((exp * exp).sum(axis=0), 1e-9)
                err = np.sqrt(np.mean((mea - exp * gain) ** 2)) / max(np.sqrt(np.mean(mea ** 2)), 1e-9)
                if best is None or err < best.error:
                    best = Location(float(start), seq, float(err), coverage)
    return best
