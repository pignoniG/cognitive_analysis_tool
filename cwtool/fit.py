"""Fit a participant's pupil parameters on their calibration sequence.

Run after the light response fit (:mod:`cwtool.photometry`). Given the display photometry
and the participant's light sensitivity and channel weights, this fits:

- the response latency (``delay``), from the timing of the sequence's steps,
- the dilation and constriction time constants (``attack``, ``release``),
- the pupil scale correction and offset, by least squares of measured on expected.

The result is meant to be saved with the participant's parameters and applied
unchanged to their other recordings (alignment "fixed").
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Callable, Optional

import numpy as np
from scipy.optimize import minimize

from cwtool import calibration, model
from cwtool.params import Parameters
from cwtool.pipeline import Prepared, prepare, residual_rms, run, steady_pupil
from cwtool.recording import Recording
from cwtool.video import VideoResult

DELAY_RANGE = (0.0, 1.5)       # s
ATTACK_RANGE = (0.3, 30.0)     # s, dilation
RELEASE_RANGE = (0.05, 5.0)    # s, constriction
PRE_ROLL = 30.0                # s of signal before the window, so the filter state has settled
SCALE_RANGE = (0.5, 2.0)       # plausible pupil scale corrections; outside, only the offset is fitted
MIN_PUPIL_SD = 0.05            # mm; a flatter pupil cannot constrain the scale


@dataclass
class FitResult:
    params: Parameters          # input parameters with the fitted values applied
    delay: float
    attack: float
    release: float
    pupil_correction: float
    pupil_offset: float
    rms_before: float           # mm, residual RMS of ΔPD in the window with the input parameters
    rms_after: float            # mm, same with the fitted parameters
    window: tuple[float, float]
    notes: list


class _Problem:
    """Measured vs expected pupil inside the window, for candidate dynamics."""

    def __init__(self, prep: Prepared, params: Parameters, field_area: float, start: float, end: float):
        t = prep.time
        lo = np.searchsorted(t, start - PRE_ROLL)
        hi = np.searchsorted(t, end, side="right")
        self.fs = prep.fs
        self.offset_in = np.searchsorted(t, start) - lo
        self.base = steady_pupil(prep.luminance[lo:hi], params, field_area)
        seg = slice(lo + self.offset_in, hi)
        scale = prep.scale if prep.scale is not None else 1.0
        # The lightly smoothed signal keeps the step edges that carry latency and constriction speed.
        measured = prep.pupil_fast[seg] * scale
        self.use = np.isfinite(measured)
        if self.use.sum() < 10:
            raise ValueError("Not enough valid pupil samples inside the calibration window")
        self.measured = measured[self.use]
        self.fit_scale = float(np.std(self.measured)) >= MIN_PUPIL_SD

    def expected(self, delay: float, attack: Optional[float], release: Optional[float]) -> np.ndarray:
        pd = model.delay(self.base, self.fs, delay)
        if attack is not None:
            pd = model.attack_release(pd, self.fs, attack, release)
        return pd[self.offset_in:][self.use]

    def solve(self, delay, attack, release) -> tuple[float, float, float]:
        """Best k, b with k·measured + b ≈ expected; returns (rms, k, b).

        The noisy side is the measurement, so the model is mapped onto it (measured ≈ c·expected + d,
        k = 1/c, b = −d/c) and the RMS is in measured millimetres. Regressing the model on the
        measurement instead would bias k towards zero whenever the pupil varies in ways the model
        does not (re-dilation, fluctuations)."""
        e = self.expected(delay, attack, release)
        k, b = 1.0, float(np.mean(e - self.measured))
        if self.fit_scale and np.std(e) > 1e-6:
            A = np.column_stack([e, np.ones_like(e)])
            (c, d), *_ = np.linalg.lstsq(A, self.measured, rcond=None)
            if c > 0 and SCALE_RANGE[0] <= 1 / c <= SCALE_RANGE[1]:
                k, b = float(1 / c), float(-d / c)
        rms = float(np.sqrt(np.mean((self.measured - (e - b) / k) ** 2)))
        return rms, float(k), float(b)


def _best_delay(problem: _Problem, attack, release, step: float) -> float:
    delays = np.arange(DELAY_RANGE[0], DELAY_RANGE[1] + step / 2, step)
    costs = [problem.solve(d, attack, release)[0] for d in delays]
    return float(delays[int(np.argmin(costs))])


MIN_ONSETS = 3            # brightening steps needed to measure the latency from onsets
MIN_CONSTRICTION = 0.3    # mm, smallest constriction whose onset is measured
ONSET_SEARCH = (-0.2, 1.5)  # s around the video change searched for the constriction


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


def fit_calibration(rec: Recording, video: VideoResult, params: Parameters, start: float,
                    end: Optional[float] = None, fit_dynamics: bool = True,
                    cancelled: Optional[Callable[[], bool]] = None,
                    sequence: Optional[calibration.Sequence] = None) -> FitResult:
    """Fit on the window [start, end] (default: the sequence's duration). With the ``sequence``, the
    latency is measured from the constriction onsets at its brightening steps and held fixed;
    otherwise (or with too few onsets) it is fitted with the time constants."""
    end = start + (sequence or calibration.DEFAULT).duration if end is None else end
    prep = prepare(rec, video, params)
    if prep.scale is None:
        raise ValueError("The calibration fit needs a device with a known pupil scale (not pixel data)")
    problem = _Problem(prep, params, rec.profile.field_area, start, end)
    step = max(1 / prep.fs, 0.02)

    attack = params.attack if (params.dynamics or fit_dynamics) else None
    release = params.release if attack is not None else None
    onsets = onset_latency(prep, video, params, start, sequence) if sequence is not None else []
    fixed_delay = len(onsets) >= MIN_ONSETS
    delay = float(np.clip(np.median(onsets), *DELAY_RANGE)) if fixed_delay else _best_delay(problem, attack, release, step)

    if fit_dynamics and fixed_delay:
        def cost(x):
            if cancelled and cancelled():
                raise InterruptedError("fit cancelled")
            return problem.solve(delay, float(np.clip(np.exp(x[0]), *ATTACK_RANGE)),
                                 float(np.clip(np.exp(x[1]), *RELEASE_RANGE)))[0]

        best = None
        for release0 in (0.3, 1.0):
            res = minimize(cost, [np.log(np.clip(params.attack, *ATTACK_RANGE)), np.log(release0)],
                           method="Nelder-Mead", options={"xatol": 1e-3, "fatol": 1e-6, "maxiter": 400})
            if best is None or res.fun < best.fun:
                best = res
        attack = float(np.clip(np.exp(best.x[0]), *ATTACK_RANGE))
        release = float(np.clip(np.exp(best.x[1]), *RELEASE_RANGE))
    elif fit_dynamics:
        # Latency and constriction speed trade off, so fit them jointly (starting from
        # the grid-search latency) rather than one after the other.
        def unpack(x):
            return (float(np.clip(x[0], *DELAY_RANGE)),
                    float(np.clip(np.exp(x[1]), *ATTACK_RANGE)),
                    float(np.clip(np.exp(x[2]), *RELEASE_RANGE)))

        def cost(x):
            if cancelled and cancelled():
                raise InterruptedError("fit cancelled")
            return problem.solve(*unpack(x))[0]

        best = None
        for release0 in (0.3, 1.0):  # two starts: fast and slow constriction
            x0 = [delay, np.log(np.clip(params.attack, *ATTACK_RANGE)), np.log(release0)]
            res = minimize(cost, x0, method="Nelder-Mead",
                           options={"xatol": 1e-3, "fatol": 1e-6, "maxiter": 600})
            if best is None or res.fun < best.fun:
                best = res
        delay, attack, release = unpack(best.x)

    _, k, b = problem.solve(delay, attack, release)
    notes = []
    at_limit = []
    if fixed_delay:
        notes.append(f"Latency {delay:.2f} s measured from {len(onsets)} constriction onsets "
                     f"(interquartile range {np.percentile(onsets, 25):.2f}–{np.percentile(onsets, 75):.2f} s).")
    for name, value, (lo, hi) in (("latency", None if fixed_delay else delay, DELAY_RANGE),
                                  ("dilation τ", attack if attack is not None else None, ATTACK_RANGE),
                                  ("constriction τ", release if release is not None else None, RELEASE_RANGE)):
        if value is not None and (value <= lo * 1.02 + 1e-3 or value >= hi * 0.98):
            at_limit.append(name)
    if at_limit:
        notes.append(f"{', '.join(at_limit)} reached the limit of the search range: the model probably does "
                     "not match the measured pupil yet. Fit the light sensitivity on the sequence first (and "
                     "check the sequence start and display photometry), then fit again.")
    if not problem.fit_scale:
        notes.append("The pupil barely varies in the window, so only the offset was fitted.")
    elif k == 1.0:
        notes.append(f"The fitted scale was outside {SCALE_RANGE[0]:g}–{SCALE_RANGE[1]:g}, "
                     "so only the offset was fitted. Check the light sensitivity fit and the window.")
    fitted = replace(params, delay=delay, pupil_correction=params.pupil_correction * k,
                     pupil_offset=b, alignment="fixed")
    if attack is not None:
        fitted = replace(fitted, dynamics=True, attack=attack, release=release)

    def window_rms(p: Parameters) -> float:
        r = run(rec, video, p)
        sel = (r.cw_time >= start) & (r.cw_time <= end)
        return residual_rms(r.cw[sel])

    return FitResult(params=fitted, delay=delay, attack=fitted.attack, release=fitted.release,
                     pupil_correction=fitted.pupil_correction, pupil_offset=b,
                     rms_before=window_rms(params), rms_after=window_rms(fitted), window=(start, end),
                     notes=notes)
