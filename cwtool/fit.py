"""Fit a participant's pupil parameters on their calibration sequence.

Photometric parameters (Lmin, Lmax, gains, gamma) stay with the operator. Given
those, this fits what the operator would otherwise guess:

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
from cwtool.pipeline import Prepared, prepare, residual_rms, run
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
        self.base = model.watson_yellott(prep.luminance[lo:hi], params.age, field_area,
                                         params.eyes, params.reference_age)
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
        """Best k, b with k·measured + b ≈ expected; returns (rms, k, b)."""
        e = self.expected(delay, attack, release)
        k = 1.0
        if self.fit_scale:
            A = np.column_stack([self.measured, np.ones_like(self.measured)])
            (k, _), *_ = np.linalg.lstsq(A, e, rcond=None)
            if not SCALE_RANGE[0] <= k <= SCALE_RANGE[1]:
                k = 1.0  # implausible: keep the device scale, fit the offset only
        b = float(np.mean(e - k * self.measured))
        rms = float(np.sqrt(np.mean((k * self.measured + b - e) ** 2)))
        return rms, float(k), float(b)


def _best_delay(problem: _Problem, attack, release, step: float) -> float:
    delays = np.arange(DELAY_RANGE[0], DELAY_RANGE[1] + step / 2, step)
    costs = [problem.solve(d, attack, release)[0] for d in delays]
    return float(delays[int(np.argmin(costs))])


def fit_calibration(rec: Recording, video: VideoResult, params: Parameters, start: float,
                    end: Optional[float] = None, fit_dynamics: bool = True,
                    cancelled: Optional[Callable[[], bool]] = None) -> FitResult:
    """Fit on the window [start, end] (default: the standard sequence duration)."""
    end = start + calibration.DURATION if end is None else end
    prep = prepare(rec, video, params)
    if prep.scale is None:
        raise ValueError("The calibration fit needs a device with a known pupil scale (not pixel data)")
    problem = _Problem(prep, params, rec.profile.field_area, start, end)
    step = max(1 / prep.fs, 0.02)

    attack = params.attack if (params.dynamics or fit_dynamics) else None
    release = params.release if attack is not None else None
    delay = _best_delay(problem, attack, release, step)

    if fit_dynamics:
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
    if not problem.fit_scale:
        notes.append("The pupil barely varies in the window, so only the offset was fitted.")
    elif k == 1.0:
        notes.append(f"The fitted scale was outside {SCALE_RANGE[0]:g}–{SCALE_RANGE[1]:g}, "
                     "so only the offset was fitted. Check the photometric calibration and the window.")
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
