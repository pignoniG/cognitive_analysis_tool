"""Which part of a recording an export keeps.

A recording often holds more than the analysis is wanted for: the calibration sequence, a break, a test run before
the participant. :class:`Trim` says what to leave out of the export: everything before ``start`` and after ``end``,
and any number of excluded segments in between. Times are seconds on the recording's relative clock (the one of
``timestamp_relative`` in the exports); the analysis itself always runs on the whole recording, so trimming only
decides what is written.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np

TRIM_FILE = "cwtool_trim.json"   # next to the recording, so the choice comes back when it is reopened


def _merged(segments) -> list[tuple[float, float]]:
    """Sorted segments with overlaps merged; empty, reversed or non-finite ones dropped."""
    good = sorted((float(a), float(b)) for a, b in segments
                  if math.isfinite(float(a)) and math.isfinite(float(b)) and float(b) > float(a))
    out: list[tuple[float, float]] = []
    for a, b in good:
        if out and a <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


@dataclass
class Trim:
    """What an export keeps of a recording: from ``start`` to ``end`` (seconds, relative clock), minus the ``exclude``
    segments.
    """
    start: Optional[float] = None      # keep from here (None: from the start of the recording)
    end: Optional[float] = None        # keep up to here (None: to the end)
    exclude: list = field(default_factory=list)   # (start, end) segments left out, in seconds

    def __post_init__(self) -> None:
        self.exclude = _merged(self.exclude)

    @property
    def active(self) -> bool:
        """True if the trim removes anything."""
        return self.start is not None or self.end is not None or bool(self.exclude)

    def keep_mask(self, t, lo: Optional[float] = None, hi: Optional[float] = None) -> np.ndarray:
        """Boolean mask of the times in ``t`` that are kept. ``lo`` and ``hi`` are further limits (the span of
        the recording, for data that extends beyond it). A segment includes its start and excludes its end."""
        t = np.asarray(t, dtype=float)
        keep = np.isfinite(t)
        for limit, upper in ((self.start, False), (lo, False), (self.end, True), (hi, True)):
            if limit is not None:
                keep &= (t <= limit) if upper else (t >= limit)
        for a, b in self.exclude:
            keep &= ~((t >= a) & (t < b))
        return keep

    def kept_spans(self, lo: float, hi: float) -> list[tuple[float, float]]:
        """The stretches of [``lo``, ``hi``] that are kept."""
        a0 = lo if self.start is None else max(lo, self.start)
        b0 = hi if self.end is None else min(hi, self.end)
        spans, cursor = [], a0
        for a, b in self.exclude:
            if b <= cursor or a >= b0:
                continue
            if a > cursor:
                spans.append((cursor, min(a, b0)))
            cursor = max(cursor, b)
        if cursor < b0:
            spans.append((cursor, b0))
        return [(a, b) for a, b in spans if b > a]

    def left_out_spans(self, lo: float, hi: float) -> list[tuple[float, float]]:
        """The stretches of [``lo``, ``hi``] that are not kept."""
        out, cursor = [], lo
        for a, b in self.kept_spans(lo, hi):
            if a > cursor:
                out.append((cursor, a))
            cursor = b
        if cursor < hi:
            out.append((cursor, hi))
        return out

    def to_dict(self) -> dict:
        """The trim as a JSON-ready dictionary."""
        return {"start": self.start, "end": self.end, "exclude": [list(s) for s in self.exclude]}

    @classmethod
    def from_dict(cls, d: dict) -> "Trim":
        """A trim from a dictionary written by :meth:`to_dict`; missing or non-finite values mean no limit."""
        def number(v):
            """The value as a float, or None if it is missing or not finite."""
            return float(v) if v is not None and math.isfinite(float(v)) else None
        return cls(number(d.get("start")), number(d.get("end")),
                   [(s[0], s[1]) for s in d.get("exclude", []) if len(s) == 2])

    def save(self, path: Path) -> None:
        """Write the trim to a JSON file."""
        Path(path).write_text(json.dumps({"version": 1, **self.to_dict()}, indent=2))

    @classmethod
    def load(cls, path: Path) -> "Trim":
        """The trim in ``path``; an empty one when the file is missing or unreadable."""
        try:
            return cls.from_dict(json.loads(Path(path).read_text()))
        except (OSError, ValueError, TypeError, KeyError):
            return cls()
