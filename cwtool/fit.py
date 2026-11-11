"""Fit a participant's pupil parameters on their calibration sequence.

Run after the light response fit (:mod:`cwtool.photometry`). Given the display photometry
and the participant's light sensitivity and channel weights, this fits:

- the response latency (``delay``), from the timing of the sequence's steps,
- the dilation and constriction time constants (``attack``, ``release``),
- optionally the transient constriction after brightening and its escape time constant
  (``transient``, ``escape``),
- optionally the pupil offset (``fit_offset``): the mean of expected minus measured. It is off by default:
  the model's absolute level is set by the sensitivity and the display's black and white, and an offset
  hides an error of those. The pupil scale (``pupil_correction``) is not fitted either: one sequence does
  not determine it (it trades off with the light sensitivity and the black point, open issues 1 and 36),
  so it stays the value set by hand.

The result is meant to be saved with the participant's parameters and applied unchanged to their other
recordings (with the offset, alignment "fixed").
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Callable, Optional

import numpy as np
from scipy.optimize import minimize

from cwtool import calibration
from cwtool.calfit import (ATTACK_RANGE, ESCAPE_RANGE, MIN_TRANSIENT, PRE_ROLL, RELEASE_RANGE,  # noqa: F401
                           TRANSIENT_RANGE)
from cwtool.onsets import (DELAY_RANGE, MIN_ONSET, MIN_ONSETS, latency_from_onset, onset_latency)  # noqa: F401
from cwtool.params import Parameters
from cwtool.pipeline import Prepared, dynamic_pupil, prepare, residual_rms, run, steady_pupil
from cwtool.recording import Recording
from cwtool.video import VideoResult

@dataclass
class FitResult:
    """Result of a parameter fit: the parameters with the fitted values applied, and the residual before and after."""
    params: Parameters          # input parameters with the fitted values applied
    delay: float
    attack: float
    release: float
    transient: float            # mm, 0 when not fitted and not in the input parameters
    escape: float
    pupil_correction: float
    pupil_offset: float
    rms_before: float           # mm, residual RMS of ΔPD in the window with the input parameters (as run gives it,
    rms_after: float            # mm, same with the fitted parameters                           with its alignment)
    window: tuple[float, float]
    notes: list
    # mm, what the fit minimises: RMS of measured (+ offset with fit_offset) − expected in the window, on the
    # lightly smoothed pupil, without the alignment of ``run``.
    fit_rms_before: float = float("nan")
    fit_rms_after: float = float("nan")


class _Problem:
    """Measured vs expected pupil inside the window, for candidate dynamics."""

    def __init__(self, prep: Prepared, params: Parameters, field_area: float, start: float, end: float,
                 fit_offset: bool = False):
        self.fit_offset = fit_offset
        t = prep.time
        lo = np.searchsorted(t, start - PRE_ROLL)
        hi = np.searchsorted(t, end, side="right")
        self.fs = prep.fs
        self.offset_in = np.searchsorted(t, start) - lo
        self.luminance = prep.luminance[lo:hi]
        self.stages = params.constriction_stages
        self.fast = (params.dilation_fast_share, params.dilation_fast)
        self.base = steady_pupil(self.luminance, params, field_area)
        seg = slice(lo + self.offset_in, hi)
        scale = prep.scale if prep.scale is not None else 1.0
        # The lightly smoothed signal keeps the step edges that carry latency and constriction speed.
        measured = prep.pupil_fast[seg] * scale
        self.use = np.isfinite(measured)
        if self.use.sum() < 10:
            raise ValueError("Not enough valid pupil samples inside the calibration window")
        self.measured = measured[self.use]
        # samples at the tracker's ceiling say only that the pupil is at least this large (see ``solve``)
        self.censored = prep.censored[seg][self.use] if prep.censored is not None else np.zeros(self.use.sum(), bool)

    def expected(self, delay: float, attack: Optional[float], release: Optional[float],
                 transient: float = 0.0, escape: float = 2.0) -> np.ndarray:
        """The expected pupil in the fit window for these dynamics parameters."""
        pd = dynamic_pupil(self.base, self.luminance, self.fs, delay, attack, release, transient, escape,
                           self.stages, *self.fast)
        return pd[self.offset_in:][self.use]

    def solve(self, delay, attack, release, transient=0.0, escape=2.0) -> tuple[float, float]:
        """Returns (rms, b), the RMS in millimetres. With ``fit_offset``, b is the best offset with
        measured + b ≈ expected, in the measured pupil's own scale; otherwise it is 0."""
        e = self.expected(delay, attack, release, transient, escape)
        b = float(np.mean(e - self.measured)) if self.fit_offset else 0.0
        r = self.measured + b - e
        r = np.where(self.censored & (r <= 0), 0.0, r)      # a model above a lower bound is no error
        return float(np.sqrt(np.mean(r ** 2))), b


def _best_delay(problem: _Problem, attack, release, transient, escape, step: float) -> float:
    delays = np.arange(DELAY_RANGE[0], DELAY_RANGE[1] + step / 2, step)
    costs = [problem.solve(d, attack, release, transient, escape)[0] for d in delays]
    return float(delays[int(np.argmin(costs))])


def fit_calibration(rec: Recording, video: VideoResult, params: Parameters, start: float,
                    end: Optional[float] = None, fit_dynamics: bool = True,
                    cancelled: Optional[Callable[[], bool]] = None,
                    sequence: Optional[calibration.Sequence] = None,
                    fit_transient: bool = False, fit_offset: bool = False) -> FitResult:
    """Fit on the window [start, end] (default: the sequence's duration). With the ``sequence``, the
    latency is measured from the constriction onsets at its brightening steps and held fixed;
    otherwise (or with too few onsets) it is fitted with the time constants. ``fit_transient`` also
    fits the transient constriction after brightening and its escape time constant. The pupil offset
    is left as it is unless ``fit_offset``: the model's absolute level is set by the sensitivity and the
    display's black and white, and an offset would hide an error of those."""
    end = start + (sequence or calibration.DEFAULT).duration if end is None else end
    prep = prepare(rec, video, params)
    if prep.scale is None:
        raise ValueError("The calibration fit needs a device with a known pupil scale (not pixel data)")
    problem = _Problem(prep, params, rec.profile.field_area, start, end, fit_offset)
    step = max(1 / prep.fs, 0.02)

    attack = params.attack if (params.dynamics or fit_dynamics) else None
    release = params.release if attack is not None else None
    # The transient belongs to the dynamics: without them it is neither applied nor fitted.
    fit_transient = fit_transient and attack is not None
    transient, escape = (params.transient if attack is not None else 0.0), params.escape
    measured = onset_latency(prep, video, params, start, sequence) if sequence is not None else []
    onsets = [o for o in measured if o >= MIN_ONSET]
    early = len(measured) - len(onsets)
    fixed_delay = len(onsets) >= MIN_ONSETS
    stages = params.constriction_stages
    onset = float(np.median(onsets)) if fixed_delay else float("nan")
    # The measured onset is held fixed; the latency that reproduces it depends on the constriction's shape.
    delay = (latency_from_onset(onset, release, stages) if fixed_delay
             else _best_delay(problem, attack, release, transient, escape, step))

    # Free values, searched together by Nelder–Mead (on log scales except the latency). Without measured
    # onsets, latency and constriction speed trade off (a late fast response looks like an early slow
    # one), so the latency joins the search rather than being fitted first.
    free = []
    if fit_dynamics and not fixed_delay:
        free.append(("delay", DELAY_RANGE, False))
    if fit_dynamics:
        free += [("attack", ATTACK_RANGE, True), ("release", RELEASE_RANGE, True)]
    if fit_transient:
        free += [("transient", TRANSIENT_RANGE, True), ("escape", ESCAPE_RANGE, True)]
    current = dict(delay=delay, attack=attack, release=release, transient=transient, escape=escape)

    def unpack(x):
        """Map the optimiser's vector to parameter values: undo the log scale, clip to the range, tie the delay to the
        onset if fixed.
        """
        values = dict(current)
        for (name, (lo, hi), log), v in zip(free, x):
            values[name] = float(np.clip(np.exp(v) if log else v, lo, hi))
        if fixed_delay:
            values["delay"] = latency_from_onset(onset, values["release"], stages)
        return values

    def cost(x):
        """Residual RMS of the model for the optimiser's vector; stops the search when the task is cancelled."""
        if cancelled and cancelled():
            raise InterruptedError("fit cancelled")
        return problem.solve(**unpack(x))[0]

    if free:
        # Two starts: fast and slow constriction (and a short, small or a long, larger transient).
        starts = [dict(release=0.3, transient=0.5, escape=2.0), dict(release=1.0, transient=1.0, escape=5.0)]
        names = {n for n, _, _ in free}
        best = None
        for s0 in starts:
            guess = {**current, **{k: v for k, v in s0.items() if k in names}}
            x0 = [np.log(np.clip(guess[n], lo, hi)) if log else guess[n] for n, (lo, hi), log in free]
            res = minimize(cost, x0, method="Nelder-Mead",
                           options={"xatol": 1e-3, "fatol": 1e-6, "maxiter": 300 * len(free)})
            if best is None or res.fun < best.fun:
                best = res
        current = unpack(best.x)
    delay, attack, release = current["delay"], current["attack"], current["release"]
    transient, escape = current["transient"], current["escape"]

    if fit_transient and transient < MIN_TRANSIENT:
        # Too small to be a transient: it only reshapes the steps and pulls the other values with it, so
        # they are fitted again without it.
        refit = fit_calibration(rec, video, replace(params, transient=0.0), start, end, fit_dynamics, cancelled,
                                sequence, fit_transient=False, fit_offset=fit_offset)
        refit.notes.insert(0, f"No transient constriction after brightening was found (the fit gave "
                              f"{transient:.2f} mm, below {MIN_TRANSIENT:g} mm); the transient is off and the "
                              "other values are fitted without it.")
        return refit
    notes = []
    _, b = problem.solve(delay, attack, release, transient, escape)
    at_limit = []
    if fixed_delay:
        notes.append(f"Latency {delay:.2f} s from {len(onsets)} constriction onsets (median onset {onset:.2f} s, "
                     f"interquartile range {np.percentile(onsets, 25):.2f}–{np.percentile(onsets, 75):.2f} s).")
    if early:
        notes.append(f"{early} constriction{'s' if early > 1 else ''} started less than {MIN_ONSET:g} s after the "
                     "change (or before it), too early for a reflex, and "
                     f"{'were' if early > 1 else 'was'} left out of the latency: the participant may have "
                     "anticipated the regular steps.")
    for name, value, (lo, hi) in (("latency", None if fixed_delay else delay, DELAY_RANGE),
                                  ("dilation τ", attack if attack is not None else None, ATTACK_RANGE),
                                  ("constriction τ", release if release is not None else None, RELEASE_RANGE)):
        if value is not None and (value <= lo * 1.02 + 1e-3 or value >= hi * 0.98):
            at_limit.append(name)
    if fit_transient:
        limits = [name for name, value, (lo, hi) in (("transient", transient, TRANSIENT_RANGE),
                                                     ("escape τ", escape, ESCAPE_RANGE))
                  if value <= lo * 1.02 + 1e-3 or value >= hi * 0.98]
        if limits:
            notes.append(f"The {' and '.join(limits)} reached the limit of the search range: this participant "
                         "shows little constriction beyond the steady state followed by re-dilation, and the "
                         "transient may only be reshaping the constriction. Consider leaving it off.")
    if at_limit:
        notes.append(f"{', '.join(at_limit)} reached the limit of the search range: the model probably does "
                     "not match the measured pupil yet. Fit the light sensitivity on the sequence first (and "
                     "check the sequence start and display photometry), then fit again.")
    fitted = replace(params, delay=delay)
    if fit_offset:
        fitted = replace(fitted, pupil_offset=b, alignment="fixed")
    if attack is not None:
        fitted = replace(fitted, dynamics=True, attack=attack, release=release)
    if fit_transient:
        fitted = replace(fitted, transient=transient, escape=escape)

    def window_rms(p: Parameters) -> float:
        """RMS of ΔPD inside the fit window for these parameters, from a full pipeline run."""
        r = run(rec, video, p)
        sel = (r.cw_time >= start) & (r.cw_time <= end)
        return residual_rms(r.cw[sel])

    dyn_in = params.dynamics
    fit_before = problem.solve(params.delay, params.attack if dyn_in else None, params.release if dyn_in else None,
                               params.transient if dyn_in else 0.0, params.escape)[0]
    fit_after = problem.solve(delay, attack, release, transient, escape)[0]
    return FitResult(params=fitted, delay=delay, attack=fitted.attack, release=fitted.release,
                     transient=fitted.transient, escape=fitted.escape,
                     pupil_correction=fitted.pupil_correction, pupil_offset=fitted.pupil_offset,
                     rms_before=window_rms(params), rms_after=window_rms(fitted), window=(start, end),
                     notes=notes, fit_rms_before=fit_before, fit_rms_after=fit_after)
