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

Each step contributes its level, the mean pupil over its last 30 %, and its colour as measured in the
video, so the calibration sees exactly what the analysis sees. Steps are not extrapolated: on real
recordings the apparent trend at the end of a step is mostly the pupil's own fluctuation (open issue 40). Weak priors keep poorly constrained values near
sensible ones: gains around 1, scale correction around 1, gamma around 2.2. The sensitivity has none:
a prior centred on 1 would mean "the datasheet is right", making the fit depend on the datasheet
luminance beyond the exact trade-off between the two (open issue 42).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Optional

import numpy as np
from scipy.optimize import least_squares

from cwtool import calibration, luminance
from cwtool.params import Parameters
from cwtool.pipeline import prepare, steady_pupil
from cwtool.recording import Recording
from cwtool.video import GAMMA_RANGE, VideoResult, at_gamma

COLOUR_SETTLE = 0.5         # s after a step change before the video colour is used
MIN_STEP_SAMPLES = 20       # pupil samples a step needs to be used
NOISE_MM = 0.1              # mm, floor on a step's uncertainty (pupil fluctuations, model error)
SETTLED_MM = 0.1            # mm, change over the last 30 % of a step below which it has settled
TAIL = 0.3                  # share of the step (after the latency) whose mean is the step's level
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
    measured: float          # mm, mean pupil over the step's end, with the input scale correction
    uncertainty: float       # mm
    settled: bool            # False: still dilating at its end after a darker step, so short of steady state
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


def step_level(t: np.ndarray, y: np.ndarray, after_darker: bool) -> tuple[float, float, bool]:
    """Level of a step response ``y(t)``: the mean of its last TAIL. Returns (value, uncertainty, settled).

    The end of a step is not extrapolated. On the Varjo calibration recordings a trend of more than
    SETTLED_MM over the step's end was as often a constriction as a dilation after brightening, i.e.
    mostly the pupil's own fluctuation, and extrapolating it moved levels by 0.34 mm (median) and made
    the fit worse (open issue 40). The one trend expected from the physiology is slow dilation after a
    darker step (``after_darker``), which can outlast a step: such a step is flagged as not settled
    (its level is short of the steady state) and half of the trend is added to its uncertainty.
    """
    t = t - t[0]
    span = t[-1] if len(t) > 1 else 0.0
    tail_mask = t >= (1 - TAIL) * span if span > 0 else np.ones(len(t), bool)
    tail_t, tail = t[tail_mask], y[tail_mask]
    value = float(np.mean(tail))
    # Samples are strongly autocorrelated: count about two independent values per second.
    n_eff = max((tail_t[-1] - tail_t[0]) * 2.0, 1.0) if len(tail_t) > 1 else 1.0
    se = float(np.std(tail) / np.sqrt(n_eff))
    slope = float(np.polyfit(tail_t, tail, 1)[0]) if len(tail_t) > 2 and np.ptp(tail_t) > 0 else 0.0
    drift = slope * max(TAIL * span, 1e-9)            # change over the tail
    if after_darker and drift > SETTLED_MM:
        return value, float(np.hypot(se, drift / 2)), False
    return value, se, True


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
    previous = None
    for step in sequence.steps:
        # The first step follows whatever was shown before the sequence (the built-in one starts black, so
        # the pupil dilates from the room): count it as after a darker one.
        after_darker = sum(step.rgb) < sum(previous.rgb) if previous is not None else True
        previous = step
        a, b = start + step.start, start + step.end
        inside = (prep.time >= a + skip) & (prep.time < b) & np.isfinite(mm)
        colour = (vt >= a + COLOUR_SETTLE) & (vt < b)
        if inside.sum() < MIN_STEP_SAMPLES or not colour.any():
            continue
        value, se, settled = step_level(prep.time[inside], mm[inside], after_darker)
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
    if unsettled:
        notes.append(f"{unsettled} of {len(levels)} steps were still dilating at their end after a darker step, "
                     "so their level is short of the steady state. Longer steps, or dimmer steps between "
                     "bright ones, would make the fit more reliable.")
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
