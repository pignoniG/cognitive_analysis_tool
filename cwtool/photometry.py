"""Fit a participant's light response on the calibration sequence.

The display photometry (Lmin, Lmax, gamma) is the user's nominal description of the device, e.g.
from its datasheet. Given it, this fits what makes the participant's steady-state pupil on each
step match the model:

- the light sensitivity, a factor on the luminance entering Watson & Yellott. It also absorbs any
  error of the display photometry common to all participants (a single sequence cannot tell a
  dimmer headset from a less sensitive participant);
- the channel weights (red, green, blue gains), from the colour steps;
- optionally gamma, from the spacing of the grey steps;
- optionally the display's black level Lmin (``fit_black``), with the white Lmax held at its nominal value;
- optionally a pupil offset (``fit_offset``). It is off by default: with the sensitivity and the display's
  black and white fitted, an offset would hide an error of them.
  The pupil scale is not fitted: one sequence does not determine it (it trades off with the sensitivity and
  the black point), so ``pupil_correction`` stays the value set by hand.

Each step contributes its level, the mean pupil over its last 30 %, and its colour as measured in the
video, so the calibration sees exactly what the analysis sees. Steps are not extrapolated: on real
recordings the apparent trend at the end of a step is mostly the pupil's own fluctuation (open issue
40). Weak priors keep poorly constrained values near sensible ones: gains around 1, gamma around 2.2. The sensitivity has none:
a prior centred on 1 would mean "the datasheet is right", making the fit depend on the datasheet
luminance beyond the exact trade-off between the two (open issue 42).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import numpy as np
from scipy.optimize import least_squares, minimize_scalar

from cwtool import calibration, luminance
from cwtool.params import Parameters
from cwtool.pipeline import expected_pupil, prepare, steady_pupil
from cwtool.recording import Recording
from cwtool.video import GAMMA_RANGE, VideoResult, at_gamma

COLOUR_SETTLE = 0.5         # s after a step change before the video colour is used
MIN_STEP_SAMPLES = 20       # pupil samples a step needs to be used
NOISE_MM = 0.1              # mm, floor on a step's uncertainty (pupil fluctuations, model error)
SETTLED_MM = 0.1            # mm, change over the last 30 % of a step below which it has settled
TAIL = 0.3                  # share of the step (after the latency) whose mean is the step's level
# Prior standard deviations (natural log units for factors). None on the sensitivity (see the module text).
PRIOR_LOG_GAIN = 1.5         # wide: the pupil's colour weighting departs strongly from photopic (blue)
PRIOR_GAMMA = 0.2
SENSITIVITY_RANGE = (1e-3, 1e3)
GAIN_RANGE = (0.05, 20.0)
BLACK_RANGE = (1e-4, 10.0)     # cd/m², Lmin when it is fitted


@dataclass
class StepLevel:
    label: str
    rgb: tuple               # nominal colour
    start: float             # s, recording time
    end: float
    measured: float          # mm, mean pupil over the step's end, with the input scale correction (set by hand)
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
    pupil_correction: float              # the input's, not fitted
    pupil_offset: float
    steps: list                          # StepLevel
    expected_before: np.ndarray          # mm per step, input parameters (best offset)
    expected_after: np.ndarray           # mm per step, fitted parameters
    measured_after: np.ndarray           # mm per step, with the fitted offset
    uncertainty_after: np.ndarray        # mm per step, on the same scale
    rms_before: float                    # mm, steady-state levels
    rms_after: float
    notes: list
    l_min: float = 0.0                   # cd/m², the input's or, with fit_black, the fitted
    l_max: float = 0.0


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
    weighted = video.weighted_lin(params.fixation_weight)     # (N, G, 3)
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


def _expected(levels, params: Parameters, field_area: float, sensitivity, gains, gamma,
              l_min=None) -> np.ndarray:
    colours = at_gamma(np.array([lv.colour for lv in levels]), gamma)
    l_min = params.l_min if l_min is None else l_min
    lum = luminance.absolute_luminance(colours, l_min, params.l_max, gains)
    return steady_pupil(lum, replace(params, sensitivity=sensitivity), field_area)


def fit_light_response(rec: Recording, video: VideoResult, params: Parameters, start: float,
                       sequence: calibration.Sequence = calibration.DEFAULT, fit_gains: bool = True,
                       fit_gamma: bool = False, fit_black: bool = False,
                       fit_offset: bool = False) -> PhotometryFit:
    """Fit the participant's light sensitivity (and channel weights, optionally gamma, the display's black
    level and the pupil offset) on the calibration sequence starting at ``start``, given the display
    photometry in ``params``."""
    levels = step_levels(rec, video, params, start, sequence)
    if len(levels) < 4:
        raise ValueError("Fewer than four calibration steps have enough pupil data")
    area = rec.profile.field_area
    m = np.array([lv.measured for lv in levels])
    sigma = np.hypot([lv.uncertainty for lv in levels], NOISE_MM)
    gains0 = np.asarray(params.gains, dtype=float)

    def unpack(x):
        """Free values x = [log s, (log gains ×3), (log Lmin), (d), (gamma)] -> (s, gains, l_min, d, gamma)."""
        sens = np.exp(x[0])
        i = 1
        gains = gains0
        if fit_gains:
            gains, i = np.exp(x[1:4]), 4
        l_min = params.l_min
        if fit_black:
            l_min, i = np.exp(x[i]), i + 1
        d = 0.0
        if fit_offset:
            d, i = x[i], i + 1
        gamma = x[i] if fit_gamma else params.gamma
        return sens, gains, l_min, d, gamma

    # The model is mapped onto the measurement (measured ≈ expected + d), so residuals are in measured
    # millimetres, at the scale set by hand.
    def residuals(x):
        sens, gains, l_min, d, gamma = unpack(x)
        r = [(m - (_expected(levels, params, area, sens, gains, gamma, l_min) + d)) / sigma]
        if fit_gains:
            r.append(np.log(gains) / PRIOR_LOG_GAIN)
        if fit_gamma:
            r.append([(gamma - 2.2) / PRIOR_GAMMA])
        return np.concatenate([np.ravel(v) for v in r])

    lo = [np.log(SENSITIVITY_RANGE[0])] + ([np.log(GAIN_RANGE[0])] * 3 if fit_gains else [])
    hi = [np.log(SENSITIVITY_RANGE[1])] + ([np.log(GAIN_RANGE[1])] * 3 if fit_gains else [])
    if fit_black:
        lo.append(np.log(BLACK_RANGE[0]))
        hi.append(np.log(BLACK_RANGE[1]))
    if fit_offset:
        lo.append(-10)
        hi.append(10)
    if fit_gamma:
        lo.append(GAMMA_RANGE[0])
        hi.append(GAMMA_RANGE[1])
    best = None
    # The pupil curve is S-shaped in log luminance: start from several sensitivities (and black levels).
    blacks = np.log([params.l_min, params.l_min * 20]) if fit_black else [None]
    for log_s in np.log([0.03, 0.3, 1.0, 3.0, 30.0]):
        for log_b in blacks:
            x0 = [log_s] + (list(np.log(np.clip(gains0, *GAIN_RANGE))) if fit_gains else [])
            if fit_black:
                x0.append(float(np.clip(log_b, np.log(BLACK_RANGE[0]), np.log(BLACK_RANGE[1]))))
            if fit_offset:
                x0.append(0.0)
            if fit_gamma:
                x0.append(float(np.clip(params.gamma, *GAMMA_RANGE)))
            res = least_squares(residuals, x0, bounds=(lo, hi))
            if best is None or res.cost < best.cost:
                best = res
    sens, gains, l_min, d, gamma = unpack(best.x)
    gains = gains / gains.mean()
    b = -d                        # measured ≈ expected + d, so measured + b ≈ expected, as the pipeline applies it

    # Approximate 95 % interval of the sensitivity from the curvature at the solution.
    try:
        cov = np.linalg.inv(best.jac.T @ best.jac)
        half = 1.96 * float(np.sqrt(cov[0, 0]))
    except np.linalg.LinAlgError:
        half = float("inf")
    s_range = (float(sens * np.exp(-half)), float(sens * np.exp(half)))

    before = _expected(levels, params, area, params.sensitivity, gains0, params.gamma)
    before_offset = float(np.mean(before - m)) if fit_offset else 0.0
    after = _expected(levels, params, area, sens, gains, gamma, l_min)
    measured_after = m + b
    notes = luminance.display_notes(l_min, params.l_max, rec.profile)
    if fit_black:
        ratio = params.l_max / l_min
        nominal = params.l_max / params.l_min
        notes.append(f"Fitted black level {l_min:.3g} cd/m² (contrast {ratio:.0f}:1 against {nominal:.0f}:1 "
                     f"nominal); effective black s·Lmin {sens * l_min:.3g}, white s·Lmax {sens * params.l_max:.3g} "
                     "cd/m². Steps too short to dark-adapt make the black look brighter than it is.")
        if np.isclose(l_min, BLACK_RANGE, rtol=0.05).any():
            notes.append("The black level reached the limit of its range.")
    if s_range[1] / s_range[0] > 4:
        notes.append(f"The sensitivity is weakly determined ({s_range[0]:.3g}–{s_range[1]:.3g}): the steps "
                     "may not reach the range where the pupil stops shrinking, or the pupil data are noisy.")
    if np.isclose(sens, SENSITIVITY_RANGE, rtol=0.05).any():
        notes.append("The sensitivity reached the limit of its range: check the display photometry and the "
                     "sequence start.")
    unsettled = sum(not lv.settled for lv in levels)
    if unsettled:
        notes.append(f"{unsettled} of {len(levels)} steps were still dilating at their end after a darker step, "
                     "so their level is short of the steady state. Longer steps, or dimmer steps between "
                     "bright ones, would make the fit more reliable.")
    if len(levels) < len(sequence.steps):
        notes.append(f"{len(sequence.steps) - len(levels)} steps had too little pupil data and were skipped.")

    fitted = replace(params, sensitivity=float(sens), gamma=float(gamma), l_min=float(l_min))
    if fit_offset:
        fitted = replace(fitted, pupil_offset=float(b), alignment="fixed")
    if fit_gains:
        fitted = replace(fitted, gain_r=float(gains[0]), gain_g=float(gains[1]), gain_b=float(gains[2]))
    return PhotometryFit(
        params=fitted, sensitivity=float(sens), sensitivity_range=s_range, gains=tuple(float(g) for g in gains),
        gamma=float(gamma), pupil_correction=fitted.pupil_correction, pupil_offset=fitted.pupil_offset,
        l_min=float(l_min), l_max=float(params.l_max), steps=levels,
        expected_before=before, expected_after=after, measured_after=measured_after,
        uncertainty_after=np.array([lv.uncertainty for lv in levels]),
        rms_before=float(np.sqrt(np.mean((m + before_offset - before) ** 2))),
        rms_after=float(np.sqrt(np.mean((measured_after - after) ** 2))), notes=notes)


# ---------------------------------------------------------------------------------------------------
# Glasses with a lux sensor: light sensitivity and offset on the calibration sequence

MIN_LUX_SAMPLES = 100        # analysis samples the calibration window needs
MIN_EXPECTED_SD = 0.1        # mm; below this the model's pupil barely moves, so the sensitivity is not determined
MIN_CORRELATION = 0.3        # measured against expected; below this the model does not follow the pupil
INDEPENDENT_PER_SECOND = 2.0  # the smoothed pupil carries about two independent values per second


WEIGHT_RANGE = (0.05, 1.0)   # gaze circle's share of the weighted colour when it is fitted
WEIGHT_GRID = 8              # values tried before refining
WEIGHT_FLAT = 0.02           # relative change of the cost across the weights below which it is "not determined"


@dataclass
class LuxFit:
    params: Parameters              # input parameters with the fitted values applied, alignment 'fixed'
    sensitivity: float
    sensitivity_range: tuple        # approximate 95 % interval
    offset: float                   # mm added to the measured pupil (the alignment offset)
    rms_before: float               # mm, ΔPD RMS in the window: input parameters, best offset
    rms_after: float
    correlation: float              # measured against expected, fitted
    steps: int                      # calibration steps with pupil data in the window
    seconds: float                  # length of the window
    time: np.ndarray                # s, samples of the window
    measured: np.ndarray            # mm, with the fitted offset
    expected_before: np.ndarray     # mm, input parameters
    expected_after: np.ndarray      # mm, fitted
    notes: list
    fixation_weight: float = 0.65   # the fitted one with ``fit_fixation``, else the input's
    weight_fitted: bool = False


def _search_sensitivity(expected, m: np.ndarray, points: int = 49):
    """Best log sensitivity for ``expected(s)`` against ``m``, each with its best offset (the mean of
    expected − measured): a grid over the sensitivity range, then a bounded refinement. Returns
    (log s, cost function, cost)."""
    def sse(log_s: float) -> float:
        e = expected(float(np.exp(log_s)))
        return float(np.sum((m + np.mean(e - m) - e) ** 2))

    grid = np.linspace(np.log(SENSITIVITY_RANGE[0]), np.log(SENSITIVITY_RANGE[1]), points)
    costs = np.array([sse(g) for g in grid])
    k = int(np.argmin(costs))
    bracket = (grid[max(k - 1, 0)], grid[min(k + 1, len(grid) - 1)])
    log_s = float(minimize_scalar(sse, bounds=bracket, method="bounded", options={"xatol": 1e-3}).x)
    return log_s, sse, sse(log_s)


def fit_lux_response(rec: Recording, video: VideoResult, params: Parameters, start: float,
                     sequence: calibration.Sequence = calibration.DEFAULT, fit_fixation: bool = False) -> LuxFit:
    """Fit the participant's light sensitivity and the pupil offset on a calibration sequence played to
    a glasses tracker with a lux sensor, by least squares on ΔPD over the sequence.

    The luminance is whatever the analysis builds from the sensor (and the video) with the current
    parameters, and the expected pupil includes the current latency and dynamics. The sensitivity
    multiplies that luminance; for each value the best offset is the mean of expected − measured, so
    only the sensitivity is searched (a grid over its range, then refined). The pupil scale is the
    device's (millimetres), not fitted: with the luminance uncertain, scale and sensitivity cannot be
    told apart on one sequence (open issue 36). Use it on a segment where light drives the pupil;
    fitting a whole task recording would remove the workload signal.

    With ``fit_fixation`` the gaze circle's weight in the weighted colour (``fixation_weight``, open
    issue 47) is fitted too: a search over its range around the sensitivity search. It needs a scene
    where the gaze area and the background differ (a screen in a room), not a uniform field, and the
    video route (``lux_use_video``).
    """
    if rec.luminance_source != "lux_sensor" or rec.lux_values is None or len(rec.lux_values) < 2:
        raise ValueError("This fit is for glasses recordings with a lux sensor log")
    if fit_fixation and not params.lux_use_video:
        raise ValueError("Fitting the fixation weight needs the video route (turn on 'Distribute with the "
                         "scene video')")
    end = start + sequence.duration
    area = rec.profile.field_area
    state = {}

    def setup(weight: float):
        p = replace(params, fixation_weight=weight)
        prep = prepare(rec, video, p)
        if prep.scale is None:
            raise ValueError("The fit needs a device with a known pupil scale (not pixel data)")
        measured = prep.pupil * prep.scale
        window = (prep.time >= start) & (prep.time <= end) & np.isfinite(measured) & prep.valid
        if window.sum() < MIN_LUX_SAMPLES:
            raise ValueError("Too little pupil data inside the calibration sequence: check its start")
        m = measured[window]

        def expected(sensitivity: float) -> np.ndarray:
            return expected_pupil(prep.luminance, prep.fs, replace(p, sensitivity=sensitivity), area)[window]
        return p, prep, window, m, expected

    weight_costs = None
    weight = params.fixation_weight
    if fit_fixation:
        def cost_at(w: float) -> float:
            _, _, _, m_w, exp_w = setup(w)
            return _search_sensitivity(exp_w, m_w)[2]

        grid = np.linspace(WEIGHT_RANGE[0], WEIGHT_RANGE[1], WEIGHT_GRID)
        weight_costs = np.array([cost_at(w) for w in grid])
        k = int(np.argmin(weight_costs))
        bracket = (grid[max(k - 1, 0)], grid[min(k + 1, len(grid) - 1)])
        weight = float(minimize_scalar(cost_at, bounds=bracket, method="bounded", options={"xatol": 0.002}).x)

    p, prep, window, m, expected = setup(weight)
    log_s, sse, cost = _search_sensitivity(expected, m)
    s_fit = float(np.exp(log_s))
    t = prep.time[window]
    p0, _, _, m0, expected_before_fn = setup(params.fixation_weight) if fit_fixation else (p, None, None, m, expected)

    e_fit, e_before = expected(s_fit), expected_before_fn(params.sensitivity)
    offset = float(np.mean(e_fit - m))
    off_before = float(np.mean(e_before - m0))
    rms_after = float(np.sqrt(np.mean((m + offset - e_fit) ** 2)))
    rms_before = float(np.sqrt(np.mean((m0 + off_before - e_before) ** 2)))
    seconds = float(t[-1] - t[0])
    corr = float(np.corrcoef(m, e_fit)[0, 1]) if np.std(e_fit) > 1e-9 and np.std(m) > 1e-9 else 0.0

    # Approximate 95 % interval of the sensitivity from the curvature of the cost at the solution.
    n_eff = max(seconds * INDEPENDENT_PER_SECOND, 4.0)
    h = 0.15
    curvature = (sse(log_s + h) - 2 * sse(log_s) + sse(log_s - h)) / h ** 2
    if curvature > 0:
        half = 1.96 * float(np.sqrt(2 * (cost / (n_eff - 2)) / curvature))
    else:
        half = float("inf")
    s_range = (float(s_fit * np.exp(-half)), float(s_fit * np.exp(half)))

    steps = sum(1 for st in sequence.steps
                if ((prep.time >= start + st.start) & (prep.time < start + st.end) & window).sum() >= MIN_STEP_SAMPLES)
    notes = []
    if steps < 4:
        notes.append(f"Only {steps} calibration steps have pupil data in the window: too few to fit reliably.")
    if np.std(e_fit) < MIN_EXPECTED_SD:
        notes.append(f"The expected pupil varies by only {np.std(e_fit):.2f} mm (SD) in the window: the luminance "
                     "barely changes, so the sensitivity is not determined. Check that the sensor sees the screen "
                     "and the sequence start.")
    elif corr < MIN_CORRELATION:
        notes.append(f"The expected pupil follows the measured one poorly (correlation {corr:.2f}): the luminance "
                     "may not describe what the eye saw, or the sequence start is wrong.")
    if np.isclose(s_fit, SENSITIVITY_RANGE, rtol=0.05).any():
        notes.append("The sensitivity reached the limit of its range: check the luminance and the sequence start.")
    elif s_range[1] / s_range[0] > 4:
        notes.append(f"The sensitivity is weakly determined ({s_range[0]:.3g}–{s_range[1]:.3g}).")
    if prep.mode != "lux sensor":
        notes.append("The luminance does not come from the lux sensor.")
    if fit_fixation:
        spread = (weight_costs.max() - weight_costs.min()) / max(weight_costs.min(), 1e-12)
        if spread < WEIGHT_FLAT:
            notes.append(f"The fit hardly depends on the fixation weight (the cost changes by {spread:.1%} across "
                         "its range): the gaze area and the background are too alike in this scene to fit it.")
        elif weight > WEIGHT_RANGE[1] - 0.02 or weight < WEIGHT_RANGE[0] + 0.02:
            notes.append(f"The fixation weight reached the limit of its range ({weight:.2f}).")
        notes.append("The fixation weight is fitted on one recording: check it on others before relying on it "
                     "(open issue 47).")

    fitted = replace(params, sensitivity=s_fit, alignment="fixed", pupil_offset=offset, fixation_weight=weight)
    return LuxFit(params=fitted, sensitivity=s_fit, sensitivity_range=s_range, offset=offset,
                  rms_before=rms_before, rms_after=rms_after, correlation=corr, steps=steps, seconds=seconds,
                  time=t, measured=m + offset, expected_before=e_before, expected_after=e_fit, notes=notes,
                  fixation_weight=weight, weight_fitted=fit_fixation)
