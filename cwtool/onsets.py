"""The response latency from the constriction onsets at a calibration sequence's brightening steps.

Onsets are sharp, unlike the shape of the whole response, which depends on the participant's light response and
re-dilation, so they pin the latency far better than a fit of the whole trace. Used by the calibration fit
(:mod:`cwtool.calfit`) and by the earlier timing fit (:mod:`cwtool.fit`).
"""

from __future__ import annotations

from functools import lru_cache
from typing import Optional

import numpy as np

from cwtool import calibration, model
from cwtool.params import Parameters
from cwtool.pipeline import Prepared
from cwtool.video import VideoResult

DELAY_RANGE = (0.0, 1.5)       # s
MIN_ONSETS = 3            # brightening steps needed to measure the latency from onsets
MIN_CONSTRICTION = 0.3    # mm, smallest constriction whose onset is measured
ONSET_SEARCH = (-0.2, 1.5)  # s around the video change searched for the constriction
# s; shorter onsets are not a reflex to the change (the shortest reported pupil latencies are about
# 0.2 s): on the calibration recordings they were constrictions starting before the display changed,
# probably in anticipation of the regular steps (open issue 41). They are left out of the latency.
MIN_ONSET = 0.1


def onset_latency(prep: Prepared, video: VideoResult, params: Parameters, start: float,
                  sequence: calibration.Sequence) -> list[float]:
    """Response latencies (s) at the sequence's brightening steps, from the video change to the onset
    of the constriction: the line through the points where the pupil has made 20 % and 50 % of its
    constriction, extended back to the level of the second before the change. Only constrictions of
    at least MIN_CONSTRICTION count. Onsets are sharp, unlike the shape of the whole response, which
    depends on the participant's light response and re-dilation, so they pin the latency far better
    than a fit of the whole trace."""
    vt = video.time - params.timelag
    vy = video.fixation_rgb.mean(axis=1)
    mm = prep.pupil_fast * (prep.scale or 1.0)
    t = prep.time
    out = []
    for before, step in zip(sequence.steps[:-1], sequence.steps[1:]):
        if sum(step.rgb) <= 1.2 * sum(before.rgb) + 5:      # only clearly brighter steps constrict
            continue
        nominal = start + step.start
        near = np.flatnonzero((vt > nominal - 1.0) & (vt < nominal + 1.0))
        jumps = near[:-1][np.abs(np.diff(vy[near])) > 4] if len(near) > 1 else []
        if not len(jumps):
            continue
        change = vt[jumps[0] + 1]
        base = (t > change - 1.0) & (t < change) & np.isfinite(mm)
        after = (t >= change + ONSET_SEARCH[0]) & (t < change + ONSET_SEARCH[1]) & np.isfinite(mm)
        if base.sum() < 10 or after.sum() < 10:
            continue
        level = mm[base].mean()
        ta, drop = t[after], level - mm[after]
        lowest = int(np.argmax(drop))
        total = drop[lowest]
        if total < MIN_CONSTRICTION:
            continue
        i20 = np.flatnonzero(drop[:lowest + 1] >= 0.2 * total)
        i50 = np.flatnonzero(drop[:lowest + 1] >= 0.5 * total)
        if not len(i20) or not len(i50) or ta[i50[0]] <= ta[i20[0]]:
            continue
        t20, t50 = ta[i20[0]], ta[i50[0]]
        out.append(float(t20 - (t50 - t20) * 0.2 / 0.3 - change))
    return out


@lru_cache(maxsize=4096)
def _onset_bias(release: float, stages: int, window: float) -> float:
    """Where :func:`onset_latency`'s construction puts the onset of the model's own constriction, relative to
    its true start (the latency): about −0.09 τ for one stage, which starts at full speed, and +0.26 τ for two,
    which start gradually. ``window`` is how long after the start the constriction is searched."""
    fs = 1000.0
    x = np.concatenate([np.ones(int(fs)), np.zeros(int(4 * fs))])
    y = model.attack_release(x, fs, 1e3, release, stages)[int(fs):int(fs) + int(max(window, 0.1) * fs)]
    drop = 1.0 - y
    lowest = int(np.argmax(drop))
    total = drop[lowest]
    t = np.arange(len(y)) / fs
    t20 = t[np.flatnonzero(drop[:lowest + 1] >= 0.2 * total)[0]]
    t50 = t[np.flatnonzero(drop[:lowest + 1] >= 0.5 * total)[0]]
    return float(t20 - (t50 - t20) * 0.2 / 0.3)


def latency_from_onset(onset: float, release: Optional[float], stages: int) -> float:
    """The model's latency (``delay``) that puts its constriction onset at the measured ``onset``."""
    if release is None:           # no filter: the response starts at full size
        return float(np.clip(onset, *DELAY_RANGE))
    bias = _onset_bias(round(float(release), 4), int(stages), round(ONSET_SEARCH[1] - onset, 2))
    return float(np.clip(onset - bias, *DELAY_RANGE))
