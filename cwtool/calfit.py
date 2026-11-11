"""The participant's calibration fit, on the pupil's time course.

One fit for every device and luminance route (a display such as the Varjo, glasses with a lux sensor, a fixed-exposure
scene camera): the expected pupil (Watson & Yellott, delayed and filtered by the dilation and constriction time constants)
is compared with the measured pupil sample by sample over the calibration sequence, and everything that shapes it is
fitted together: the light sensitivity, the colour weights, the latency and the time constants (and, as options, the
transient constriction, the gamma, the display's black, the gaze circle's weight and the pupil offset).

It replaces the two-step fit of :mod:`cwtool.photometry` (the level at the end of each step) followed by
:mod:`cwtool.fit` (the timing). A step that has not settled by its end (a black step after a bright one: the pupil
dilates with a time constant of several seconds, and an 8 s step is too short) was read as a level, so the sensitivity
depended on how the steps were cut: on the first Varjo run it went from 3.75 to 28 when the sequence moved by 0.34 s
(open issue 55). On the time course a step that is still dilating is simply part of the curve the model must follow.

The display's values are effective, not physical: the sensitivity multiplies the luminance and the colour weights the
display's primaries, so a dimmer headset and a less sensitive participant are the same fit, as are the display's
primaries and the eye's colour weighting. No photometry is needed for ΔPD; the fitted values hold for this headset model
and its settings (open issue 55).

Samples at the tracker's ceiling (:mod:`cwtool.quality`) are lower bounds: a model above them is no error. Each sample
counts as if there were about two independent ones per second (the pupil is smooth), so the weak priors on the colour
weights and the gamma keep their weight against a long sequence.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Callable, Optional

import numpy as np
from scipy.optimize import least_squares

from cwtool import calibration, luminance, model
from cwtool.onsets import DELAY_RANGE, MIN_ONSET, MIN_ONSETS, latency_from_onset, onset_latency
from cwtool.params import Parameters
from cwtool.pipeline import luminance_from_lux, prepare, residual_rms, run
from cwtool.recording import Recording
from cwtool.video import GAMMA_RANGE, VideoResult, at_gamma

# Search ranges, and the weak priors (standard deviations; natural log units for factors) that keep poorly constrained
# values near sensible ones. The sensitivity has no prior: one centred on 1 would mean "the nominal luminance is right"
# (open issue 42).
SENSITIVITY_RANGE = (1e-3, 1e3)
GAIN_RANGE = (0.05, 20.0)
PRIOR_LOG_GAIN = 1.5         # wide: the pupil's colour weighting departs strongly from photopic (blue)
PRIOR_GAMMA = 0.2
BLACK_RANGE = (1e-4, 10.0)   # cd/m², Lmin when it is fitted
ATTACK_RANGE = (0.3, 30.0)     # s, dilation
RELEASE_RANGE = (0.05, 5.0)    # s, constriction
TRANSIENT_RANGE = (0.01, 3.0)  # mm, largest transient constriction
# mm; a fitted transient below this is taken as none. It is under the pupil's own fluctuation within a step
# (0.08–0.24 mm RMS on the Varjo calibration recordings, open issue 43), and the transients fitted there were
# 0.35–1.7 mm; a smaller one only reshapes the steps (on synthetic data without a transient the fit found
# 0.06 mm and moved the latency by 0.08 s with it).
MIN_TRANSIENT = 0.1
ESCAPE_RANGE = (0.3, 30.0)     # s, re-dilation of the transient
PRE_ROLL = 30.0                # s of signal before the window, so the filter state has settled

FIT_RATE = 50.0              # Hz, the grid of the fit (the pupil carries nothing faster)
NOISE_MM = 0.15              # mm, the pupil's own fluctuation within a step (0.08-0.24 mm on the Varjo recordings)
INDEPENDENT_PER_SECOND = 2.0  # the smoothed pupil carries about two independent values per second
OFFSET_RANGE = (-5.0, 5.0)   # mm
FIXATION_RANGE = (0.05, 1.0)
MIN_SAMPLES = 200            # valid samples the window needs
SLOW_ATTACK_MAX = 120.0      # s, the dilation's slow part
WEAK_RATIO = 4.0             # a 95 % interval of the sensitivity wider than this factor: weakly determined
MIN_CORRELATION = 0.3        # measured against expected; below this the model does not follow the pupil
CEILING_NOTE = 0.01          # share of the window at the tracker's ceiling above which a note says so

# name: (range, on a log scale)
RANGES = {
    "sensitivity": (SENSITIVITY_RANGE, True),
    "gain_r": (GAIN_RANGE, True), "gain_g": (GAIN_RANGE, True), "gain_b": (GAIN_RANGE, True),
    "gamma": (GAMMA_RANGE, False),
    "l_min": (BLACK_RANGE, True),
    "fixation_weight": (FIXATION_RANGE, False),
    "pupil_offset": (OFFSET_RANGE, False),
    "delay": (DELAY_RANGE, False),
    # the slow part of a two-part dilation can be very slow (the pupil stays small for tens of seconds after bright light):
    # on the first Varjo run it settled at 76 s, against the 30 s limit of a single time constant
    "attack": ((ATTACK_RANGE[0], SLOW_ATTACK_MAX), True), "release": (RELEASE_RANGE, True),
    "transient": (TRANSIENT_RANGE, True), "escape": (ESCAPE_RANGE, True),
    "dilation_fast_share": ((0.0, 0.95), False), "dilation_fast": ((0.2, 5.0), True),
}
LABELS = {"sensitivity": "light sensitivity", "gain_r": "red weight", "gain_g": "green weight", "gain_b": "blue weight",
          "gamma": "gamma", "l_min": "black (Lmin)", "fixation_weight": "fixation weight", "pupil_offset": "pupil offset",
          "delay": "latency", "attack": "dilation τ", "release": "constriction τ", "transient": "transient",
          "escape": "escape τ", "dilation_fast_share": "fast dilation share", "dilation_fast": "fast dilation τ"}


@dataclass
class CalibrationFit:
    """The calibration fit: the parameters with the fitted values applied, how well the model follows the pupil before
    and after, and the time courses for a plot."""

    params: Parameters
    route: str                     # how the luminance is built: "display", "lux sensor", "camera, fixed exposure", ...
    values: dict                   # the fitted values
    intervals: dict                # approximate 95 % intervals of the fitted values
    fit_rms_before: float          # mm, measured − expected in the window with the best constant offset: input parameters
    fit_rms_after: float           # the same, fitted
    rms_before: float              # mm, ΔPD RMS in the window from the whole analysis: input parameters
    rms_after: float
    correlation: float             # measured against expected, fitted
    window: tuple
    time: np.ndarray               # s, the fit's grid inside the window
    measured: np.ndarray           # mm, with the fitted (or best) offset
    expected_before: np.ndarray    # mm
    expected_after: np.ndarray
    notes: list = field(default_factory=list)
    onsets: int = 0                # constriction onsets the latency was taken from (0: fitted with the rest)

    def summary(self) -> str:
        """The fitted values as one line of text."""
        parts = []
        for name in ("sensitivity", "gain_r", "gain_g", "gain_b", "gamma", "l_min", "fixation_weight", "pupil_offset",
                     "delay", "attack", "release", "transient", "escape"):
            if name in self.values:
                unit = {"delay": " s", "attack": " s", "release": " s", "escape": " s", "pupil_offset": " mm",
                        "transient": " mm", "l_min": " cd/m²"}.get(name, "")
                parts.append(f"{LABELS[name]} {self.values[name]:.3g}{unit}")
        return ", ".join(parts)


def _luminance_model(rec: Recording, video: VideoResult, params: Parameters, mode: str, t: np.ndarray):
    """A function of the candidate values giving the luminance (cd/m²) at the times ``t``, built as
    :func:`cwtool.pipeline.prepare` builds it for this recording's route (``mode``)."""
    vt = np.asarray(video.time, dtype=float) - params.timelag
    order = np.argsort(vt)
    vt = vt[order]

    def on_t(a: np.ndarray) -> np.ndarray:
        """Video samples (N, G, 3) on the fit's times, linearly interpolated."""
        a = np.asarray(a, dtype=float)[order]
        flat = a.reshape(len(a), -1)
        out = np.column_stack([np.interp(t, vt, flat[:, j]) for j in range(flat.shape[1])])
        return out.reshape(len(t), *a.shape[1:])

    fix, bg = on_t(video.fixation_lin), on_t(video.background_lin)
    last = {}

    def weighted(v: dict) -> np.ndarray:
        """The gaze-weighted colour; kept while the weight and the gamma do not change (they are rarely fitted)."""
        key = (v["fixation_weight"], v["gamma"])
        if last.get("key") != key:
            w = v["fixation_weight"]
            last.update(key=key, value=at_gamma(w * fix + (1 - w) * bg, v["gamma"]))
        return last["value"]

    def gains(v: dict) -> np.ndarray:
        return np.array([v["gain_r"], v["gain_g"], v["gain_b"]], dtype=float)

    if mode in ("display", "camera, relative"):
        return lambda v: luminance.absolute_luminance(weighted(v), v["l_min"], params.l_max, gains(v))

    def relative(v: dict) -> tuple[np.ndarray, Optional[np.ndarray]]:
        g = gains(v)
        weights = luminance.SRGB_WEIGHTS * g / g.mean()
        return weighted(v) @ weights, None

    if mode == "camera, fixed exposure":
        return lambda v: params.camera_full_scale * relative(v)[0]

    # the lux sensor's average luminance, distributed with the video when asked (Pignoni et al. 2021, eq. 5-8)
    avg = luminance_from_lux(rec, params, t)
    if not params.lux_use_video:
        return lambda v: avg
    frame = on_t(video.frame_lin)
    limit = params.lux_ratio_limit

    def lux(v: dict) -> np.ndarray:
        g = gains(v)
        weights = luminance.SRGB_WEIGHTS * g / g.mean()
        y_w, y_frame = weighted(v) @ weights, at_gamma(frame, v["gamma"]) @ weights
        ratio = np.where(y_frame > 1e-4, y_w / np.maximum(y_frame, 1e-4), 1.0)
        if limit > 0:
            ratio = np.clip(ratio, 1 / max(limit, 1.0), max(limit, 1.0))
        return avg * ratio
    return lux


def fit_calibration(rec: Recording, video: VideoResult, params: Parameters, start: float,
                    sequence: calibration.Sequence, fit_dynamics: bool = True, fit_transient: bool = False,
                    fit_gains: Optional[bool] = None, fit_gamma: bool = False, fit_black: bool = False,
                    fit_fixation: bool = False, fit_offset: Optional[bool] = None, fit_dilation_parts: bool = False,
                    cancelled: Optional[Callable[[], bool]] = None) -> CalibrationFit:
    """Fit the participant's light response and timing together on the calibration ``sequence`` starting at ``start``.

    Defaults follow the route: on a display (and a camera mapped onto its range) the colour weights are fitted and the
    offset is not (the model's absolute level is the sensitivity's); with a lux sensor or a fixed-exposure camera the
    offset is fitted (the sensor's luminance is not absolute enough) and the weights are not. The transient constriction
    after brightening (``fit_transient``) is off unless asked: on the first Varjo run, with it free, the transient and a
    dilation time constant at the end of its range explained the slow dilation after the black steps and made the session's
    ΔPD worse (replicate blocks 0.41 mm apart against 0.26 without it, open issue 55). The latency comes from the constriction onsets at the sequence's brightening steps when there are
    enough (it is sharper than the whole response), else it is fitted with the rest. ``fit_dilation_parts`` also fits the
    share and the time constant of the dilation's fast part, which only a sequence that dims after moderate as well as after
    bright light determines (the time-course calibration, :data:`cwtool.calibration.TIME_COURSE`)."""
    end = start + sequence.duration
    prep = prepare(rec, video, params)
    if prep.scale is None:
        raise ValueError("The calibration fit needs a device with a known pupil scale (not pixel data)")
    mode = prep.mode
    photometric = prep.photometric
    fit_gains = photometric if fit_gains is None else fit_gains
    fit_offset = (not photometric) if fit_offset is None else fit_offset
    fit_transient = fit_transient and fit_dynamics
    fit_black = fit_black and photometric
    dynamics = fit_dynamics or params.dynamics
    area = rec.profile.field_area
    stages = params.constriction_stages

    # the fit's grid: the window, with a stretch before it so that the filters have settled
    t = np.arange(max(start - PRE_ROLL, float(prep.time[0])), min(end, float(prep.time[-1])), 1 / FIT_RATE)
    if len(t) < 10:
        raise ValueError("The calibration sequence is not inside the recording: check its start")
    mm = prep.pupil_fast * prep.scale
    good = np.isfinite(mm) & prep.valid
    m = np.interp(t, prep.time, np.where(good, mm, 0.0))
    ok = np.interp(t, prep.time, good.astype(float)) > 0.99
    censored = (np.interp(t, prep.time, prep.censored.astype(float)) > 0.5 if prep.censored is not None
                else np.zeros(len(t), bool))
    window = (t >= start) & (t <= end) & ok
    n = int(window.sum())
    if n < MIN_SAMPLES:
        raise ValueError("Too little pupil data inside the calibration sequence: check its start")
    seconds = float(t[window][-1] - t[window][0])
    n_eff = max(seconds * INDEPENDENT_PER_SECOND, 4.0)
    weight = 1.0 / (NOISE_MM * np.sqrt(n / n_eff))
    lum = _luminance_model(rec, video, params, mode, t)

    measured_onsets = onset_latency(prep, video, params, start, sequence)
    onsets = [o for o in measured_onsets if o >= MIN_ONSET]
    early = len(measured_onsets) - len(onsets)
    fixed_delay = len(onsets) >= MIN_ONSETS
    onset = float(np.median(onsets)) if fixed_delay else float("nan")

    base = dict(sensitivity=params.sensitivity, gain_r=params.gain_r, gain_g=params.gain_g, gain_b=params.gain_b,
                gamma=params.gamma, l_min=params.l_min, fixation_weight=params.fixation_weight,
                pupil_offset=params.pupil_offset if fit_offset else 0.0, delay=params.delay, attack=params.attack,
                release=params.release, transient=params.transient if dynamics else 0.0, escape=params.escape,
                dilation_fast_share=params.dilation_fast_share, dilation_fast=params.dilation_fast)
    free = ["sensitivity"]
    if fit_gains:
        free += ["gain_r", "gain_g", "gain_b"]
    if fit_gamma:
        free.append("gamma")
    if fit_black:
        free.append("l_min")
    if fit_fixation:
        free.append("fixation_weight")
    if fit_offset:
        free.append("pupil_offset")
    if not fixed_delay:
        free.append("delay")
    if fit_dynamics:
        free += ["attack", "release"]
    if fit_transient:
        free += ["transient", "escape"]
    fit_dilation_parts = fit_dilation_parts and fit_dynamics
    if fit_dilation_parts:
        free += ["dilation_fast_share", "dilation_fast"]

    def to_x(v: dict) -> np.ndarray:
        out = []
        for name in free:
            (lo, hi), log = RANGES[name]
            value = float(np.clip(v[name], lo, hi))
            out.append(np.log(value) if log else value)
        return np.array(out)

    lo_x = np.array([np.log(RANGES[n][0][0]) if RANGES[n][1] else RANGES[n][0][0] for n in free])
    hi_x = np.array([np.log(RANGES[n][0][1]) if RANGES[n][1] else RANGES[n][0][1] for n in free])

    def unpack(x) -> dict:
        v = dict(base)
        for name, value in zip(free, x):
            v[name] = float(np.exp(value) if RANGES[name][1] else value)
        if fixed_delay:
            v["delay"] = latency_from_onset(onset, v["release"] if dynamics else None, stages)
        return v

    def expected(v: dict) -> np.ndarray:
        L = lum(v)
        steady = model.watson_yellott(L * v["sensitivity"], params.age, area, params.eyes)
        pd = model.delay(steady, FIT_RATE, v["delay"])
        if not dynamics:
            return pd
        pd = model.attack_release(pd, FIT_RATE, v["attack"], v["release"], stages, v["dilation_fast_share"],
                                  v["dilation_fast"])
        if v["transient"] > 0:
            tr = model.delay(model.escape_transient(L, FIT_RATE, v["escape"]), FIT_RATE, v["delay"])
            for _ in range(stages):
                tr = model.lowpass(tr, FIT_RATE, v["release"])
            pd = pd - v["transient"] * tr
        return pd

    mw, cw = m[window], censored[window]

    def one_sided(r: np.ndarray) -> np.ndarray:
        """measured − expected, where a sample at the tracker's ceiling is a lower bound: a model above it is no error."""
        return np.where(cw & (r <= 0), 0.0, r)

    def residuals(x) -> np.ndarray:
        if cancelled and cancelled():
            raise InterruptedError("fit cancelled")
        v = unpack(x)
        r = [one_sided(mw + v["pupil_offset"] - expected(v)[window]) * weight]
        if fit_gains:
            r.append(np.log([v["gain_r"], v["gain_g"], v["gain_b"]]) / PRIOR_LOG_GAIN)
        if fit_gamma:
            r.append([(v["gamma"] - 2.2) / PRIOR_GAMMA])
        return np.concatenate([np.ravel(a) for a in r])

    # Several starts: the pupil curve is S-shaped in log luminance, and fast or slow constriction trade off with the
    # latency. The best end point is kept.
    starts = []
    for s in (0.5, 5.0):
        for release in ((0.3, 1.0) if fit_dynamics else (base["release"],)):
            starts.append({**base, "sensitivity": s, "release": release})
    best = None
    for guess in starts:
        res = least_squares(residuals, to_x(guess), bounds=(lo_x, hi_x), x_scale="jac", diff_step=1e-3,
                            max_nfev=60 * (len(free) + 1))
        if best is None or res.cost < best.cost:
            best = res
    values = unpack(best.x)

    if fit_transient and values["transient"] < MIN_TRANSIENT:
        # Too small to be a transient: it only reshapes the steps and pulls the other values with it.
        refit = fit_calibration(rec, video, replace(params, transient=0.0), start, sequence, fit_dynamics,
                                fit_transient=False, fit_gains=fit_gains, fit_gamma=fit_gamma, fit_black=fit_black,
                                fit_fixation=fit_fixation, fit_offset=fit_offset,
                                fit_dilation_parts=fit_dilation_parts, cancelled=cancelled)
        refit.notes.insert(0, f"No transient constriction after brightening was found (the fit gave "
                              f"{values['transient']:.2f} mm, below {MIN_TRANSIENT:g} mm): it is left off.")
        return refit

    # approximate 95 % intervals, from the curvature at the solution scaled by the actual residual
    e_after = expected(values)
    resid = one_sided(mw + values["pupil_offset"] - e_after[window])
    noise = float(np.sqrt(np.mean(resid ** 2)))
    intervals = {}
    try:
        cov = np.linalg.inv(best.jac.T @ best.jac) * (noise / NOISE_MM) ** 2
        half = 1.96 * np.sqrt(np.clip(np.diag(cov), 0, None))
    except np.linalg.LinAlgError:
        half = np.full(len(free), np.inf)
    for name, x, h in zip(free, best.x, half):
        if RANGES[name][1]:
            intervals[name] = (float(np.exp(x - h)), float(np.exp(x + h)))
        else:
            intervals[name] = (float(x - h), float(x + h))
    if fit_gains:
        mean_gain = np.mean([values["gain_r"], values["gain_g"], values["gain_b"]])
        for name in ("gain_r", "gain_g", "gain_b"):                     # a relative balance: mean 1
            values[name] /= mean_gain
            intervals[name] = (intervals[name][0] / mean_gain, intervals[name][1] / mean_gain)

    # what changes: the fitted values applied to the input parameters
    fitted = replace(params, sensitivity=values["sensitivity"], delay=values["delay"])
    if fit_gains:
        fitted = replace(fitted, gain_r=values["gain_r"], gain_g=values["gain_g"], gain_b=values["gain_b"])
    if fit_gamma:
        fitted = replace(fitted, gamma=values["gamma"])
    if fit_black:
        fitted = replace(fitted, l_min=values["l_min"])
    if fit_fixation:
        fitted = replace(fitted, fixation_weight=values["fixation_weight"])
    if fit_offset:
        fitted = replace(fitted, pupil_offset=values["pupil_offset"], alignment="fixed")
    if fit_dilation_parts:
        fitted = replace(fitted, dilation_fast_share=values["dilation_fast_share"], dilation_fast=values["dilation_fast"])
    if fit_dynamics:
        fitted = replace(fitted, dynamics=True, attack=values["attack"], release=values["release"],
                         transient=values["transient"] if fit_transient else 0.0,
                         escape=values["escape"] if fit_transient else params.escape)

    # before and after: the fit's own measure (best constant offset, so they compare), and ΔPD from the whole analysis
    v_before = {**base, "pupil_offset": 0.0, "transient": params.transient if params.dynamics else 0.0}
    if params.dynamics:
        e_before = expected(v_before)
    else:                                   # the input parameters without dynamics: the steady pupil, delayed
        e_before = model.delay(model.watson_yellott(lum(v_before) * params.sensitivity, params.age, area, params.eyes),
                               FIT_RATE, params.delay)
    off_before = float(np.mean(e_before[window] - mw))
    off_after = values["pupil_offset"] if fit_offset else float(np.mean(e_after[window] - mw))
    fit_before = float(np.sqrt(np.mean(one_sided(mw + off_before - e_before[window]) ** 2)))
    fit_after = float(np.sqrt(np.mean(one_sided(mw + off_after - e_after[window]) ** 2)))
    corr = float(np.corrcoef(mw, e_after[window])[0, 1]) if np.std(e_after[window]) > 1e-9 and np.std(mw) > 1e-9 else 0.0

    def window_rms(p: Parameters) -> float:
        r = run(rec, video, p)
        sel = (r.cw_time >= start) & (r.cw_time <= end)
        return residual_rms(r.cw[sel])

    notes = []
    if fixed_delay:
        notes.append(f"Latency {values['delay']:.2f} s from {len(onsets)} constriction onsets (median onset {onset:.2f} s, "
                     f"interquartile range {np.percentile(onsets, 25):.2f}–{np.percentile(onsets, 75):.2f} s).")
    if early:
        notes.append(f"{early} constriction{'s' if early > 1 else ''} started less than {MIN_ONSET:g} s after the change "
                     f"(or before it), too early for a reflex, and {'were' if early > 1 else 'was'} left out of the "
                     "latency: the participant may have anticipated the regular steps.")
    lo_s, hi_s = intervals["sensitivity"]
    if not lo_s > 0 or hi_s / lo_s > WEAK_RATIO:
        notes.append(f"The light sensitivity is weakly determined ({lo_s:.3g}–{hi_s:.3g}): the sequence does not "
                     "reach far enough into the range where the pupil stops changing, or the pupil is noisy.")
    at_limit = [LABELS[name] for name in free if name not in ("gain_r", "gain_g", "gain_b")
                and np.isclose(values[name], RANGES[name][0], rtol=0.02, atol=1e-3).any()]
    if at_limit:
        notes.append(f"{', '.join(at_limit)} reached the limit of the search range: check the sequence's start and that "
                     "the light drives the pupil in it.")
    if corr < MIN_CORRELATION:
        notes.append(f"The model follows the measured pupil poorly (correlation {corr:.2f}): the luminance may not "
                     "describe what the eye saw, or the sequence start is wrong.")
    share = float(cw.mean())
    if share >= CEILING_NOTE:
        notes.append(f"{share:.0%} of the sequence is at the tracker's ceiling: those samples are lower bounds (the model "
                     "is only required to be at least as large there).")
    if photometric:
        notes.append("The display's values are effective: the sensitivity and the colour weights absorb the display's real "
                     "luminance and primaries, so they hold for this headset model and its settings.")

    reported = {name: values[name] for name in free}
    if fixed_delay:
        reported["delay"] = values["delay"]            # from the onsets, not among the free values
    return CalibrationFit(params=fitted, route=mode, values=reported, intervals=intervals, fit_rms_before=fit_before, fit_rms_after=fit_after,
                          rms_before=window_rms(params), rms_after=window_rms(fitted), correlation=corr,
                          window=(start, end), time=t[window], measured=mw + off_after,
                          expected_before=e_before[window], expected_after=e_after[window], notes=notes,
                          onsets=len(onsets) if fixed_delay else 0)

