"""Aligning the presenter's log to the scene video.

The presenter (the calibration presenter and the validation task) logs when it changed what it showed, on the computer's
clock. The scene video shows what was actually displayed, on the tracker's clock. The two can differ by a fraction of a
second (0.34 s on the first Varjo run), which matters for anything matched by time: the event markers, the placement of
the calibration sequence, and the sensor files the logger wrote on the computer's clock.

For each logged change of the picture, the video's own change is found (where its luminance crosses the middle of the two
levels), and the offset is the median difference over many changes, with its spread. The log's clock is then moved onto the
video's: :func:`align` returns the recording with its time zero re-expressed on the log's clock, so that everything written
by the computer (events, the logger's sensors, the exported Unix times) lines up with the pupil and the video.

Only devices whose events come from the presenter's computer are aligned (:func:`applicable`): the Varjo.
"""

from __future__ import annotations

import csv
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Optional

import numpy as np
from scipy.stats import theilslopes

from cwtool import calibration
from cwtool.recording import Event, Recording
from cwtool.video import VideoResult

# Weights of the colour channels for the luminance of 8-bit codes (as the calibration presenter orders its colours).
LUMA = np.array([0.2125, 0.7154, 0.072])
COARSE_RANGE = 5.0       # s, how far the video may be from the log (searched in steps of COARSE_STEP; the smaller on a tie)
COARSE_STEP = 0.02
COARSE_MATCH = 0.12      # s, a video change this close to a logged one counts as the same change
FINE_SEARCH = 0.5        # s, around the coarse offset, where each change is looked for
LEVEL_FAR, LEVEL_NEAR = 3.0, 0.8     # s before and after a change where the two levels are measured (median)
MIN_LEVEL_SAMPLES = 20
MIN_JUMP = 10.0          # code values of luminance: a change smaller than this is not used
MIN_STEPS = 5            # changes needed for an estimate
MIN_SHARE = 0.25         # share of the logged changes that the coarse offset must explain
OUTLIER_SD = 5.0         # per-change offsets further than this many robust SDs from the median are dropped
DRIFT_NOTE_S = 0.05      # a drift of more than this over the recording is mentioned
MIN_UNCERTAINTY = 0.005  # s, below the video's own time resolution (a frame) nothing can be claimed
APPLICABLE = ("varjo",)


@dataclass(frozen=True)
class LogAlignment:
    """How far the video's clock is from the log's."""

    offset: float                # s: video time = log time + offset (negative: the video shows a change before the log says)
    uncertainty: float           # s, the standard error of the median over the changes used
    sd: float                    # s, spread of the per-change offsets (robust)
    n: int                       # changes used
    candidates: int              # logged changes tried
    drift_per_min: float         # s per minute (Theil–Sen over the changes), informational: the offset used is constant
    span: float                  # s between the first and last change used
    source: str                  # the log files the changes came from

    @property
    def drift(self) -> float:
        """The drift over the span of the changes (s)."""
        return self.drift_per_min * self.span / 60.0

    def as_dict(self) -> dict:
        return {k: (round(v, 6) if isinstance(v, float) else v) for k, v in asdict(self).items()}

    def summary(self) -> str:
        side = "leads" if self.offset < 0 else "lags behind"
        return (f"log aligned to the video: the video {side} the log by {abs(self.offset):.3f} s "
                f"(±{self.uncertainty:.3f} s, {self.n} changes)")

    def notes(self) -> list[str]:
        notes = [self.summary() + "; the log's clock (events, sensors, exported Unix times) is moved onto the video's."]
        if abs(self.drift) > DRIFT_NOTE_S:
            notes.append(f"The offset drifts by {self.drift:+.2f} s over {self.span / 60:.0f} min; the constant median is used.")
        return notes


def applicable(rec: Recording) -> bool:
    """Whether the recording's events and logs are on the presenter's computer clock, so that the alignment can move them."""
    return bool(rec.device in APPLICABLE and np.isfinite(rec.epoch_start))


def log_onsets(folder: str | Path) -> tuple[np.ndarray, str]:
    """The Unix times (s) at which the presenter logged a change of the picture, and the files they come from: the visual log
    of the validation task (``Start (unix s)``) and the calibration presenter's run file (``onset_unix_ms``)."""
    folder = Path(folder)
    times, sources = [], []
    for path in sorted(folder.glob("*visual_log*.csv")) if folder.is_dir() else []:
        if path.name.startswith("."):
            continue
        try:
            with open(path, newline="", encoding="utf-8") as f:
                rows = [r for r in csv.reader(f) if r and not r[0].lstrip().startswith("#")]
            column = [h.strip() for h in rows[0]].index("Start (unix s)")
            times += [float(r[column]) for r in rows[1:] if len(r) > column]
            sources.append(path.name)
        except (OSError, UnicodeDecodeError, ValueError, IndexError):
            continue
    run = calibration.find_run_file(folder)
    if run is not None:
        try:
            with open(run, newline="", encoding="utf-8") as f:
                rows = [r for r in csv.reader(f) if r and not r[0].lstrip().startswith("#")]
            column = [h.strip().lower() for h in rows[0]].index("onset_unix_ms")
            times += [float(r[column]) / 1000.0 for r in rows[1:] if len(r) > column and r[column].strip()]
            sources.append(run.name)
        except (OSError, UnicodeDecodeError, ValueError, IndexError):
            pass
    if not times:
        return np.zeros(0), ""
    times = np.unique(np.round(np.asarray(times, dtype=float), 3))
    keep = np.concatenate([[True], np.diff(times) > 0.05])           # the same change in two logs counts once
    return times[keep], ", ".join(sources)


def _luma(video: VideoResult) -> tuple[np.ndarray, np.ndarray]:
    """The video's time and the luminance code of its background area, in time order."""
    order = np.argsort(video.time)
    t = np.asarray(video.time, dtype=float)[order]
    return t, np.asarray(video.background_rgb, dtype=float)[order] @ LUMA


def _coarse_offset(t: np.ndarray, rgb: np.ndarray, onsets: np.ndarray) -> Optional[float]:
    """The offset (s) at which most logged changes have a video change next to them, searched over ±COARSE_RANGE."""
    points = calibration._change_points(t, rgb, threshold=MIN_JUMP / 2)
    if len(points) < MIN_STEPS:
        return None
    candidates = np.arange(-COARSE_RANGE, COARSE_RANGE + COARSE_STEP / 2, COARSE_STEP)
    best, best_score = None, 0.0
    for d in candidates:
        x = onsets + d
        i = np.clip(np.searchsorted(points, x), 1, len(points) - 1)
        gap = np.minimum(np.abs(points[i] - x), np.abs(points[i - 1] - x))
        matched = gap < COARSE_MATCH
        score = matched.sum() - 0.01 * abs(d) - (gap[matched].mean() if matched.any() else 0.0)
        if score > best_score:
            best, best_score = d, score
    if best is None:
        return None
    x = onsets + best
    i = np.clip(np.searchsorted(points, x), 1, len(points) - 1)
    matched = np.minimum(np.abs(points[i] - x), np.abs(points[i - 1] - x)) < COARSE_MATCH
    return float(best) if matched.sum() >= max(MIN_STEPS, MIN_SHARE * len(onsets)) else None


def _crossing(t: np.ndarray, y: np.ndarray, x: float, lo: float, hi: float) -> Optional[float]:
    """When the luminance ``y`` crosses the middle of the levels before and after a change expected near ``x``: the
    levels are the medians over the stretch before ``lo`` ... ``x - LEVEL_NEAR`` and ``x + LEVEL_NEAR`` ... ``hi``."""
    a, b = np.searchsorted(t, [max(x - LEVEL_FAR, lo), x - LEVEL_NEAR])
    c, d = np.searchsorted(t, [x + LEVEL_NEAR, min(x + LEVEL_FAR, hi)])
    if b - a < MIN_LEVEL_SAMPLES or d - c < MIN_LEVEL_SAMPLES:
        return None
    pre, post = float(np.median(y[a:b])), float(np.median(y[c:d]))
    if abs(post - pre) < MIN_JUMP:
        return None
    sign, mid = np.sign(post - pre), (pre + post) / 2
    i, j = np.searchsorted(t, [x - FINE_SEARCH, x + FINE_SEARCH])
    seg = y[i:j]
    if len(seg) < 5:
        return None
    smooth = np.convolve(np.pad(seg, 2, mode="edge"), np.ones(5) / 5, mode="valid")
    beyond = sign * (smooth - mid) >= 0
    for k in np.flatnonzero(beyond):
        if k == 0:
            return None                       # already past the middle at the start of the window: not this change
        if beyond[k:k + 10].mean() >= 0.8:     # and it stays there
            y0, y1 = smooth[k - 1], smooth[k]
            frac = (mid - y0) / (y1 - y0) if y1 != y0 else 0.0
            return float(t[i + k - 1] + frac * (t[i + k] - t[i + k - 1]))
    return None


def estimate(rec: Recording, video: VideoResult, onsets: Optional[np.ndarray] = None,
             source: str = "") -> tuple[Optional[LogAlignment], str]:
    """The alignment of the log to the video, and a message (why there is none, when it is None). ``onsets`` are the
    logged change times in Unix seconds (default: the logs in the recording's folder, :func:`log_onsets`)."""
    if onsets is None:
        onsets, source = log_onsets(rec.folder)
    if len(onsets) == 0:
        return None, "no presenter log (visual log or calibration run file) in the recording's folder"
    if not np.isfinite(rec.epoch_start):
        return None, "the recording does not give its Unix start time"
    if len(video.time) < 100:
        return None, "the video has too few analysed samples"
    t, y = _luma(video)
    rgb = np.asarray(video.background_rgb, dtype=float)[np.argsort(video.time)]
    rel = np.sort(np.asarray(onsets, dtype=float) - rec.epoch_start)
    coarse = _coarse_offset(t, rgb, rel)
    if coarse is None:
        return None, (f"the log's changes were not found in the video (searched ±{COARSE_RANGE:g} s): the log may belong "
                      "to another recording")
    offsets, at = [], []
    for k, onset in enumerate(rel):
        x = onset + coarse
        lo = rel[k - 1] + coarse + 0.1 if k > 0 else -np.inf              # the levels stay within the neighbouring steps
        hi = rel[k + 1] + coarse - 0.1 if k + 1 < len(rel) else np.inf
        crossing = _crossing(t, y, x, lo, hi)
        if crossing is not None:
            offsets.append(crossing - onset)
            at.append(onset)
    offsets, at = np.asarray(offsets), np.asarray(at)
    if len(offsets) < MIN_STEPS:
        return None, f"only {len(offsets)} of {len(rel)} logged changes could be found in the video (at least {MIN_STEPS})"
    centre = float(np.median(offsets))
    mad = 1.4826 * float(np.median(np.abs(offsets - centre)))
    keep = np.abs(offsets - centre) <= OUTLIER_SD * max(mad, 0.01)
    offsets, at = offsets[keep], at[keep]
    if len(offsets) < MIN_STEPS:
        return None, "the offsets of the logged changes do not agree"
    centre = float(np.median(offsets))
    sd = 1.4826 * float(np.median(np.abs(offsets - centre)))
    slope = float(theilslopes(offsets, at)[0]) if len(offsets) >= 10 and np.ptp(at) > 60 else 0.0
    return LogAlignment(offset=centre, uncertainty=max(sd / np.sqrt(len(offsets)), MIN_UNCERTAINTY), sd=sd, n=len(offsets),
                        candidates=len(rel), drift_per_min=slope * 60.0, span=float(np.ptp(at)), source=source), "aligned"


def find(rec: Recording, video: VideoResult) -> tuple[Optional[LogAlignment], str]:
    """:func:`estimate` for a recording the alignment applies to (:func:`applicable`), with the logs in its folder."""
    if not applicable(rec):
        return None, f"not offered for {rec.device} recordings"
    return estimate(rec, video)


def align(rec: Recording, alignment: LogAlignment) -> Recording:
    """The recording with the log's clock moved onto the video's: the Unix time of time zero becomes the log clock's, so
    that the logger's files, the events and the exported Unix times (all on the computer's clock) fall where the video and
    the pupil are; the events and the lux log, stored relative to the old zero, move by the offset."""
    shift = alignment.offset
    lux = None if rec.lux_time is None else np.asarray(rec.lux_time, dtype=float) + shift
    return replace(rec, epoch_start=rec.epoch_start - shift, lux_time=lux,
                   events=[Event(e.label, e.start + shift, e.end + shift) for e in rec.events],
                   notes=list(rec.notes) + alignment.notes(), log_alignment=alignment.as_dict())
