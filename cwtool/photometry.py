"""Fit a participant's light response on the calibration sequence.

The display photometry (Lmin, Lmax, gamma) is the user's nominal description of the device, e.g.
from its datasheet. Given it, this fits what makes the participant's steady-state pupil on each
step match the model:

- the light sensitivity, a factor on the luminance entering Watson & Yellott. It also absorbs any
  error of the display photometry common to all participants (a single sequence cannot tell a
  dimmer headset from a less sensitive participant);
- the channel weights (red, green, blue gains), from the colour steps;
- optionally gamma, from the spacing of the grey steps;
- a pupil scale correction and offset, which the latency fit (:mod:`cwtool.fit`) refines next.

Each step contributes its steady-state pupil, the asymptote of an exponential fitted to the step
(dilation can take longer than a step to settle), and its colour as measured in the video, so the
calibration sees exactly what the analysis sees. Weak priors keep poorly constrained values near
sensible ones: gains around 1, scale correction around 1, gamma around 2.2. The sensitivity has none:
a prior centred on 1 would mean "the datasheet is right", making the fit depend on the datasheet
luminance beyond the exact trade-off between the two (open issue 42).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Optional

import numpy as np
from scipy.optimize import curve_fit, least_squares

from cwtool import calibration, luminance
from cwtool.params import Parameters
from cwtool.pipeline import prepare, steady_pupil
from cwtool.recording import Recording
from cwtool.video import GAMMA_RANGE, VideoResult, at_gamma

COLOUR_SETTLE = 0.5         # s after a step change before the video colour is used
MIN_STEP_SAMPLES = 20       # pupil samples a step needs to be used
NOISE_MM = 0.1              # mm, floor on a step's uncertainty (pupil fluctuations, model error)
SETTLED_MM = 0.1            # mm, change over the last 30 % of a step below which it has settled
MAX_EXTRAPOLATION = 1.0     # mm, beyond the last second of a step
# Prior standard deviations (natural log units for factors). None on the sensitivity (see the module text).
PRIOR_LOG_GAIN = 1.5         # wide: the pupil's colour weighting departs strongly from photopic (blue)
PRIOR_SCALE = 0.25
PRIOR_GAMMA = 0.2
SENSITIVITY_RANGE = (1e-3, 1e3)
GAIN_RANGE = (0.05, 20.0)
SCALE_RANGE = (0.5, 2.0)


@dataclass
class StepLevel:
    label: str
    rgb: tuple               # nominal colour
    start: float             # s, recording time
    end: float
    measured: float          # mm, steady-state pupil (asymptote), with the input scale correction
    uncertainty: float       # mm
    settled: bool            # the exponential reached its asymptote within the step
    colour: np.ndarray       # (G, 3) mean weighted linear colour per gamma of the video's grid


@dataclass
class PhotometryFit:
    params: Parameters                   # input parameters with the fitted values applied
    sensitivity: float
    sensitivity_range: tuple             # approximate 95 % interval
    gains: tuple                         # normalised to a mean of 1
    gamma: float
    pupil_correction: float
    pupil_offset: float
    steps: list                          # StepLevel
    expected_before: np.ndarray          # mm per step, input parameters (best offset)
    expected_after: np.ndarray           # mm per step, fitted parameters
    measured_after: np.ndarray           # mm per step, with the fitted scale and offset
    uncertainty_after: np.ndarray        # mm per step, on the same scale
    rms_before: float                    # mm, steady-state levels
    rms_after: float
    notes: list


def step_asymptote(t: np.ndarray, y: np.ndarray) -> tuple[float, float, bool]:
    """Steady-state value of a step response ``y(t)``. Returns (value, uncertainty, settled).

    If the last 30 % of the step is flat, its mean is the steady state. Otherwise the pupil is still
    moving (slow dilation, or re-dilation after the initial constriction, "pupillary escape"): an
    exponential y = A + (y0 − A)·e^(−(t−t0)/τ) is fitted from the turning point (the extreme value
    before the final trend) to the end, and its asymptote is used. The extrapolation is limited to
    MAX_EXTRAPOLATION beyond the last values, in the direction of the trend, and half of it is added to
    the uncertainty, so extrapolated steps count less in the fit.
    """
    t = t - t[0]
    span = t[-1] if len(t) > 1 else 0.0
    tail_mask = t >= 0.7 * span if span > 0 else np.ones(len(t), bool)
    tail_t, tail = t[tail_mask], y[tail_mask]
    late = float(np.mean(tail))
    # Samples are strongly autocorrelated: count about two independent values per second.
    n_eff = max((tail_t[-1] - tail_t[0]) * 2.0, 1.0) if len(tail_t) > 1 else 1.0
    noise = float(np.std(tail) / np.sqrt(n_eff))
    slope = float(np.polyfit(tail_t, tail, 1)[0]) if len(tail_t) > 2 and np.ptp(tail_t) > 0 else 0.0
    drift = slope * max(0.3 * span, 1e-9)            # change over the tail
    if abs(drift) < SETTLED_MM:
        return late, noise, True

    rising = slope > 0
    turn = int(np.argmin(y) if rising else np.argmax(y))
    seg_t, seg = t[turn:] - t[turn], y[turn:]
    value, se = late, float("inf")
    if len(seg) >= MIN_STEP_SAMPLES and seg_t[-1] > 0:
        try:
            (a, _, _), cov = curve_fit(lambda x, a, y0, tau: a + (y0 - a) * np.exp(-x / tau), seg_t, seg,
                                       p0=(late + drift, float(seg[0]), max(seg_t[-1] / 3, 0.2)),
                                       bounds=((0.5, 0.5, 0.05), (10.0, 10.0, 60.0)), maxfev=5000)
            value, se = float(a), float(np.sqrt(cov[0, 0])) if np.all(np.isfinite(cov)) else float("inf")
        except (RuntimeError, ValueError):
            pass
    last = float(np.mean(y[t >= span - 1.0]))        # the last second
    if not np.isfinite(se):                          # no usable fit: continue the late trend a little
        value = last + drift
    # The steady state lies beyond the last values in the direction of the trend, not too far.
    lo, hi = (last, last + MAX_EXTRAPOLATION) if rising else (last - MAX_EXTRAPOLATION, last)
    value = float(np.clip(value, lo, hi))
    se = float(np.hypot(se if np.isfinite(se) else abs(drift), abs(value - last) / 2))
    return value, float(np.hypot(se, noise)), False


def step_levels(rec: Recording, video: VideoResult, params: Parameters, start: float,
                sequence: calibration.Sequence) -> list[StepLevel]:
    """Steady-state pupil and measured colour of each step of ``sequence`` starting at ``start``."""
    prep = prepare(rec, video, params)
    if prep.scale is None:
        raise ValueError("The light response fit needs a device with a known pupil scale (not pixel data)")
    mm = prep.pupil_fast * prep.scale
    vt = video.time - params.timelag
    w = params.fixation_weight
    weighted = w * video.fixation_lin + (1 - w) * video.background_lin     # (N, G, 3)
    skip = params.delay + 0.1           # latency before the pupil starts to respond
    levels = []
    for step in sequence.steps:
        a, b = start + step.start, start + step.end
        inside = (prep.time >= a + skip) & (prep.time < b) & np.isfinite(mm)
        colour = (vt >= a + COLOUR_SETTLE) & (vt < b)
        if inside.sum() < MIN_STEP_SAMPLES or not colour.any():
            continue
        value, se, settled = step_asymptote(prep.time[inside], mm[inside])
        levels.append(StepLevel(step.label, step.rgb, a, b, value, se, settled, weighted[colour].mean(axis=0)))
    return levels


def _expected(levels, params: Parameters, field_area: float, sensitivity, gains, gamma) -> np.ndarray:
    colours = at_gamma(np.array([lv.colour for lv in levels]), gamma)
    lum = luminance.absolute_luminance(colours, params.l_min, params.l_max, gains)
    return steady_pupil(lum, replace(params, sensitivity=sensitivity), field_area)


def fit_light_response(rec: Recording, video: VideoResult, params: Parameters, start: float,
                       sequence: calibration.Sequence = calibration.DEFAULT, fit_gains: bool = True,
                       fit_gamma: bool = False) -> PhotometryFit:
    """Fit the participant's light sensitivity (and channel weights, optionally gamma) on the
    calibration sequence starting at ``start``, given the display photometry in ``params``."""
    levels = step_levels(rec, video, params, start, sequence)
    if len(levels) < 4:
        raise ValueError("Fewer than four calibration steps have enough pupil data")
    area = rec.profile.field_area
    m = np.array([lv.measured for lv in levels])
    sigma = np.hypot([lv.uncertainty for lv in levels], NOISE_MM)
    gains0 = np.asarray(params.gains, dtype=float)

    def unpack(x):
        i = 0
        sens = np.exp(x[i]); i += 1
        gains = np.exp(x[i:i + 3]) if fit_gains else gains0
        i += 3 if fit_gains else 0
        c, d = np.exp(x[i]), x[i + 1]; i += 2
        gamma = x[i] if fit_gamma else params.gamma
        return sens, gains, c, d, gamma

    # The model is mapped onto the measurement (measured ≈ c·expected + d), so residuals are in
    # measured millimetres: compressing the model's range (e.g. an extreme sensitivity that puts
    # every step at the smallest pupil) cannot shrink them. The pupil scale correction is 1/c.
    def residuals(x):
        sens, gains, c, d, gamma = unpack(x)
        r = [(m - (c * _expected(levels, params, area, sens, gains, gamma) + d)) / sigma,
             [np.log(c) / PRIOR_SCALE]]
        if fit_gains:
            r.append(np.log(gains) / PRIOR_LOG_GAIN)
        if fit_gamma:
            r.append([(gamma - 2.2) / PRIOR_GAMMA])
        return np.concatenate([np.ravel(v) for v in r])

    # c = 1 / scale correction, so its range is the inverse of SCALE_RANGE.
    lo = [np.log(SENSITIVITY_RANGE[0])] + ([np.log(GAIN_RANGE[0])] * 3 if fit_gains else []) + [-np.log(SCALE_RANGE[1]), -10]
    hi = [np.log(SENSITIVITY_RANGE[1])] + ([np.log(GAIN_RANGE[1])] * 3 if fit_gains else []) + [-np.log(SCALE_RANGE[0]), 10]
    if fit_gamma:
        lo.append(GAMMA_RANGE[0])
        hi.append(GAMMA_RANGE[1])
    best = None
    # The pupil curve is S-shaped in log luminance: start from several sensitivities.
    for log_s in np.log([0.03, 0.3, 1.0, 3.0, 30.0]):
        x0 = [log_s] + (list(np.log(np.clip(gains0, *GAIN_RANGE))) if fit_gains else []) + [0.0, 0.0]
        if fit_gamma:
            x0.append(float(np.clip(params.gamma, *GAMMA_RANGE)))
        res = least_squares(residuals, x0, bounds=(lo, hi))
        if best is None or res.cost < best.cost:
            best = res
    sens, gains, c, d, gamma = unpack(best.x)
    gains = gains / gains.mean()
    k, b = 1 / c, -d / c          # measured · k + b ≈ expected, as the pipeline applies it

    # Approximate 95 % interval of the sensitivity from the curvature at the solution.
    try:
        cov = np.linalg.inv(best.jac.T @ best.jac)
        half = 1.96 * float(np.sqrt(cov[0, 0]))
    except np.linalg.LinAlgError:
        half = float("inf")
    s_range = (float(sens * np.exp(-half)), float(sens * np.exp(half)))

    before = _expected(levels, params, area, params.sensitivity, gains0, params.gamma)
    before_offset = float(np.mean(before - m))
    after = _expected(levels, params, area, sens, gains, gamma)
    measured_after = k * m + b
    notes = []
    if s_range[1] / s_range[0] > 4:
        notes.append(f"The sensitivity is weakly determined ({s_range[0]:.3g}–{s_range[1]:.3g}): the steps "
                     "may not reach the range where the pupil stops shrinking, or the pupil data are noisy.")
    if np.isclose(sens, SENSITIVITY_RANGE, rtol=0.05).any():
        notes.append("The sensitivity reached the limit of its range: check the display photometry and the "
                     "sequence start.")
    if np.isclose(k, SCALE_RANGE, rtol=0.02).any():
        notes.append("The pupil scale correction reached the limit of its range.")
    unsettled = sum(not lv.settled for lv in levels)
    if unsettled > len(levels) / 3:
        notes.append(f"The pupil had not settled by the end of {unsettled} of {len(levels)} steps; their "
                     "steady state is extrapolated. Longer steps would make the fit more reliable.")
    if len(levels) < len(sequence.steps):
        notes.append(f"{len(sequence.steps) - len(levels)} steps had too little pupil data and were skipped.")

    fitted = replace(params, sensitivity=float(sens), gamma=float(gamma),
                     pupil_correction=params.pupil_correction * float(k), pupil_offset=float(b))
    if fit_gains:
        fitted = replace(fitted, gain_r=float(gains[0]), gain_g=float(gains[1]), gain_b=float(gains[2]))
    return PhotometryFit(
        params=fitted, sensitivity=float(sens), sensitivity_range=s_range, gains=tuple(float(g) for g in gains),
        gamma=float(gamma), pupil_correction=fitted.pupil_correction, pupil_offset=float(b), steps=levels,
        expected_before=before, expected_after=after, measured_after=measured_after,
        uncertainty_after=float(k) * np.array([lv.uncertainty for lv in levels]),
        rms_before=float(np.sqrt(np.mean((m + before_offset - before) ** 2))),
        rms_after=float(np.sqrt(np.mean((measured_after - after) ** 2))), notes=notes)
