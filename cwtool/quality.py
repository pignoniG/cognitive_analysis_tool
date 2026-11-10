"""How good the tracking of a recording is, from the recording alone (before any analysis).

The report is what a reader of the data needs to judge it: how much of the pupil signal exists, how it is lost (blinks
or long dropouts), and whether the tracker limits it (a ceiling on large pupils, a pupil that is a ratio to an iris it
does not measure). The window shows it next to the recording's details, the export keeps it, and the notes of every
result carry the parts that matter.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Optional

import numpy as np

from cwtool.recording import Recording

BLINK_MAX_S = 0.5            # a dropout shorter than this is taken for a blink, a longer one is a loss of tracking
LOW_VALID = 0.8              # share of samples with a pupil below which a note says so
CEILING_NOTE = 0.005         # share of samples at the tracker's ceiling above which a note says so
LONG_DROPOUT_NOTE_S = 5.0    # a dropout this long is mentioned


@dataclass
class Quality:
    """The tracking quality of one recording. Shares are of all samples; ``ceiling_*`` are shares of the samples with a
    pupil, None when the device reports no ceiling."""

    samples: int
    duration_s: float
    rate_hz: float
    valid_left: float
    valid_right: float
    valid_either: float                 # a pupil from at least one eye
    blinks: int                         # dropouts (both eyes missing) shorter than BLINK_MAX_S
    long_dropouts: int
    longest_dropout_s: float
    lost_s: float                       # total time with no pupil from either eye
    ceiling_left: Optional[float] = None
    ceiling_right: Optional[float] = None
    assumed_iris_mm: Optional[float] = None     # the iris the pupil's millimetres are derived from, if the device fixes one

    @property
    def ceiling(self) -> Optional[float]:
        """The larger of the two eyes' ceiling shares, None when neither is known."""
        known = [c for c in (self.ceiling_left, self.ceiling_right) if c is not None]
        return max(known) if known else None

    def as_dict(self) -> dict:
        """The report as plain numbers, for the export."""
        return {k: (None if v is None else (round(v, 6) if isinstance(v, float) else v)) for k, v in asdict(self).items()}

    def lines(self) -> list[str]:
        """The report as short lines of text."""
        out = [f"tracking: a pupil in {self.valid_either:.1%} of samples (left {self.valid_left:.1%}, right {self.valid_right:.1%})"]
        if self.blinks or self.long_dropouts:
            out.append(f"dropouts: {self.blinks} short (blinks), {self.long_dropouts} longer than {BLINK_MAX_S:g} s"
                       f"{f', longest {self.longest_dropout_s:.1f} s' if self.long_dropouts else ''}; {self.lost_s:.0f} s lost")
        if self.ceiling is not None:
            out.append(f"at the tracker's ceiling: {self.ceiling:.1%} of the pupil samples")
        if self.assumed_iris_mm is not None:
            out.append(f"the pupil in mm is a ratio × a fixed iris of {self.assumed_iris_mm:.1f} mm")
        return out

    def notes(self) -> list[str]:
        """Warnings for what limits the data (empty when nothing does)."""
        notes = []
        if self.valid_either < LOW_VALID:
            notes.append(f"The pupil is tracked in only {self.valid_either:.0%} of the recording.")
        if self.long_dropouts and self.longest_dropout_s >= LONG_DROPOUT_NOTE_S:
            notes.append(f"Tracking was lost for up to {self.longest_dropout_s:.0f} s ({self.long_dropouts} dropouts "
                         f"longer than {BLINK_MAX_S:g} s).")
        if self.ceiling is not None and self.ceiling >= CEILING_NOTE:
            notes.append(f"{self.ceiling:.1%} of the pupil samples are at the tracker's ceiling: the pupil is at least "
                         "that large there (the values are lower bounds), as in a long dark step. The calibration fit "
                         "treats them so; ΔPD is not reliable in those stretches.")
        return notes


def _runs(missing: np.ndarray, step: float) -> np.ndarray:
    """Durations (s) of the stretches of True in ``missing``, samples ``step`` seconds apart."""
    if not len(missing):
        return np.zeros(0)
    edges = np.diff(np.concatenate([[0], missing.astype(np.int8), [0]]))
    return (np.flatnonzero(edges == -1) - np.flatnonzero(edges == 1)) * step


def assess(rec: Recording) -> Quality:
    """The tracking quality of ``rec`` (a pupil that is NaN is missing, as the readers write it)."""
    left, right = np.isfinite(rec.pupil_left), np.isfinite(rec.pupil_right)
    n = len(left)
    rate = rec.measured_rate if n > 1 else float("nan")
    step = 1.0 / rate if np.isfinite(rate) and rate > 0 else 0.0
    runs = _runs(~(left | right), step)

    def share(censored: Optional[np.ndarray], valid: np.ndarray) -> Optional[float]:
        if censored is None or not valid.any():
            return None
        return float((np.asarray(censored, bool) & valid).sum() / valid.sum())

    return Quality(
        samples=n,
        duration_s=float(rec.time[-1] - rec.time[0]) if n > 1 else 0.0,
        rate_hz=float(rate),
        valid_left=float(left.mean()) if n else 0.0,
        valid_right=float(right.mean()) if n else 0.0,
        valid_either=float((left | right).mean()) if n else 0.0,
        blinks=int((runs < BLINK_MAX_S).sum()),
        long_dropouts=int((runs >= BLINK_MAX_S).sum()),
        longest_dropout_s=float(runs.max()) if len(runs) else 0.0,
        lost_s=float(runs.sum()),
        ceiling_left=share(rec.censored_left, left),
        ceiling_right=share(rec.censored_right, right),
        assumed_iris_mm=rec.profile.assumed_iris,
    )
