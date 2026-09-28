"""From a recording, its video analysis and parameters to ΔPD (cognitive workload)."""

from __future__ import annotations

import csv
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np
from scipy.signal import savgol_filter

from cwtool import luminance, model
from cwtool import lux as lux_module
from cwtool.params import Parameters
from cwtool.recording import Recording
from cwtool.video import VideoResult


@dataclass
class Result:
    """Output of :func:`run`, on the uniform analysis grid (``time``) and the ΔPD windows (``cw_time``)."""

    time: np.ndarray            # s, relative, uniform analysis grid
    luminance: np.ndarray       # cd/m², weighted fixation/background
    measured_raw: np.ndarray    # mm, lightly smoothed, scaled and aligned; NaN in long gaps
    measured: np.ndarray        # mm, smoothed, scaled and aligned; NaN in long gaps
    expected: np.ndarray        # mm, Watson & Yellott with dynamics
    cw_time: np.ndarray         # s, ΔPD window centres
    cw: np.ndarray              # mm, ΔPD = measured - expected, smoothed; NaN in long gaps
    cw_rms: float               # mm, residual RMS of ΔPD (about zero)
    cw_sd: float                # mm, standard deviation of ΔPD (unit for normalised ΔPD)
    expected_black: float       # mm, expected PD at the panel black point
    expected_white: float       # mm, expected PD at the panel white point
    offset: float               # mm, shift applied to the measured PD
    pupil_scale: float          # device units to mm actually applied (device scale × correction)
    rate: float                 # Hz, analysis rate
    measured_rate: float        # Hz, rate estimated from the recording's timestamps
    gap_fraction: float         # share of the grid inside gaps longer than max_gap
    warnings: list = field(default_factory=list)
    luminance_mode: str = "display"   # see Prepared.mode


def _odd(n: int, minimum: int = 3) -> int:
    n = max(int(n), minimum)
    return n if n % 2 else n + 1


def interp_nan(x: np.ndarray) -> np.ndarray:
    """``x`` with NaN samples linearly interpolated (held at the ends)."""
    x = np.asarray(x, dtype=float).copy()
    bad = ~np.isfinite(x)
    if bad.all():
        raise ValueError("signal has no valid samples")
    if bad.any():
        i = np.arange(len(x))
        x[bad] = np.interp(i[bad], i[~bad], x[~bad])
    return x


# Samples with both eyes needed to estimate the difference between them.
MIN_BOTH_EYES = 20


def combine_eyes(left: np.ndarray, right: np.ndarray, eye: str) -> np.ndarray:
    """"left", "right", or "both": the average, falling back to one eye where the other is missing.

    The eyes often differ by a steady amount (up to 0.26 mm on the Varjo calibration recordings), so
    falling back to one eye would step the average by half of it. Where one eye is missing it is
    therefore taken as the other plus the median difference between the eyes, measured on the samples
    with both (open issue 45); with fewer than MIN_BOTH_EYES such samples, the plain fallback is used."""
    left, right = np.asarray(left, dtype=float), np.asarray(right, dtype=float)
    if eye == "left":
        return left
    if eye == "right":
        return right
    both = np.isfinite(left) & np.isfinite(right)
    if both.sum() >= MIN_BOTH_EYES:
        diff = float(np.median(right[both] - left[both]))
        left, right = np.where(np.isnan(left), right - diff, left), np.where(np.isnan(right), left + diff, right)
    pair = np.vstack([left, right])
    with np.errstate(all="ignore"), warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        return np.nanmean(pair, axis=0)


# Pupil speed is measured over at least this span, so the threshold does not depend on the
# sampling rate (sample-to-sample noise would otherwise read as high speed at 200 Hz).
SPEED_SPAN = 0.04  # s


def artefacts(time: np.ndarray, mm: np.ndarray, max_speed: float, padding: float) -> np.ndarray:
    """Samples to drop: those where the pupil changes faster than ``max_speed`` (mm/s) towards
    the previous or next sample at least SPEED_SPAN away (blink edges, tracking jumps), widened by
    ``padding`` s on each side. Physiological pupil responses stay well below 10 mm/s."""
    drop = np.zeros(len(mm), bool)
    ok = np.flatnonzero(np.isfinite(mm) & np.isfinite(time))
    if max_speed <= 0 or len(ok) < 3:
        return drop
    t, v = time[ok], mm[ok]
    prev = np.searchsorted(t, t - SPEED_SPAN, side="right") - 1
    nxt = np.searchsorted(t, t + SPEED_SPAN, side="left")
    fast = np.zeros(len(t), bool)
    has = prev >= 0
    fast[has] |= np.abs(v[has] - v[prev[has]]) / (t[has] - t[prev[has]]) > max_speed
    has = nxt < len(t)
    fast[has] |= np.abs(v[nxt[has]] - v[has]) / (t[nxt[has]] - t[has]) > max_speed
    if not fast.any():
        return drop
    bad_t = t[fast]
    i = np.clip(np.searchsorted(bad_t, time), 1, len(bad_t) - 1) if len(bad_t) > 1 else np.zeros(len(time), int)
    near = np.minimum(np.abs(time - bad_t[np.maximum(i - 1, 0)]), np.abs(time - bad_t[i]))
    return near <= padding


def resample(time: np.ndarray, values: np.ndarray, rate: float, max_gap: float):
    """Put ``values`` on a uniform grid at ``rate`` Hz spanning the valid samples.

    Returns (grid, filled, valid): ``filled`` is linearly interpolated everywhere
    (so filters can run), ``valid`` is False inside gaps longer than ``max_gap`` s.
    """
    ok = np.isfinite(values) & np.isfinite(time)
    t, v = np.asarray(time)[ok], np.asarray(values)[ok]
    order = np.argsort(t)
    t, v = t[order], v[order]
    if len(t) < 2:
        raise ValueError("signal has fewer than two valid samples")
    grid = np.arange(t[0], t[-1] + 0.5 / rate, 1 / rate)
    filled = np.interp(grid, t, v)
    nxt = np.clip(np.searchsorted(t, grid), 1, len(t) - 1)
    span = t[nxt] - t[nxt - 1]
    exact = np.isclose(grid, t[nxt]) | np.isclose(grid, t[nxt - 1])
    valid = exact | (span <= max_gap)
    return grid, filled, valid


def relative_luminances(video: VideoResult, params: Parameters) -> tuple[np.ndarray, np.ndarray]:
    """Gaze-weighted and whole-scene relative luminance (0-1) per video sample, with the
    channel gains as a relative balance."""
    gains = np.asarray(params.gains, dtype=float)
    weights = luminance.SRGB_WEIGHTS * gains / gains.mean()
    return (video.weighted(params.gamma, params.fixation_weight) @ weights,
            video.frame_linear(params.gamma) @ weights)


def scene_luminance(video: VideoResult, params: Parameters) -> np.ndarray:
    """Absolute luminance (cd/m²) for each video sample: the per-pixel-linearised
    fixation and background means are weighted, then mapped onto [l_min, l_max]
    with channel gains."""
    return luminance.absolute_luminance(video.weighted(params.gamma, params.fixation_weight),
                                        params.l_min, params.l_max, params.gains)


# Scaled pupil diameters outside this range (mm) are treated as tracking errors.
PUPIL_RANGE_MM = (1.0, 9.0)
# A median diameter outside this range (mm) suggests a wrong pupil scale.
PLAUSIBLE_MM = (2.0, 8.0)
# Plausible pupil scale corrections for the calibration fits; outside, only the offset is fitted.
SCALE_RANGE = (0.5, 2.0)


def steady_pupil(lum, params: Parameters, field_area: float) -> np.ndarray:
    """Light-adapted pupil (mm) for luminance ``lum`` (cd/m²): Watson & Yellott with the
    participant's light sensitivity applied to the luminance."""
    return model.watson_yellott(np.asarray(lum, dtype=float) * params.sensitivity, params.age, field_area,
                                params.eyes)


def dynamic_pupil(steady: np.ndarray, lum: np.ndarray, fs: float, delay: float, attack: Optional[float],
                  release: Optional[float], transient: float = 0.0, escape: float = 2.0,
                  stages: int = 1) -> np.ndarray:
    """The steady-state pupil ``steady`` for luminance ``lum``, delayed. With the dynamics (``attack``
    given), it then goes through the attack/release filter with ``stages`` constriction stages, minus
    the transient constriction of ``transient`` mm at most, which has the same latency and
    constriction stages. Without them, the transient is not applied either."""
    pd = model.delay(steady, fs, delay)
    if attack is None:
        return pd
    pd = model.attack_release(pd, fs, attack, release, stages)
    if transient > 0:
        tr = model.delay(model.escape_transient(lum, fs, escape), fs, delay)
        for _ in range(stages):
            tr = model.lowpass(tr, fs, release)
        pd = pd - transient * tr
    return pd


def expected_pupil(lum: np.ndarray, fs: float, params: Parameters, field_area: float) -> np.ndarray:
    """Expected pupil (mm) on a uniform grid at ``fs`` Hz for luminance ``lum`` (cd/m²), with the
    participant's parameters: :func:`steady_pupil`, then :func:`dynamic_pupil`."""
    dyn = params.dynamics
    return dynamic_pupil(steady_pupil(lum, params, field_area), lum, fs, params.delay,
                         params.attack if dyn else None, params.release if dyn else None,
                         params.transient, params.escape, params.constriction_stages)


def windowed_difference(time, a, b, window_n: int):
    """Mean of (a - b) over consecutive windows of ``window_n`` samples, ignoring NaN.
    Windows without valid samples are NaN."""
    n = len(a) // window_n
    if n == 0:
        return np.empty(0), np.empty(0)
    d = (np.asarray(a) - np.asarray(b))[: n * window_n].reshape(n, window_n)
    t = np.asarray(time)[: n * window_n].reshape(n, window_n)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        return t.mean(axis=1), np.nanmean(d, axis=1)


def residual_rms(x: np.ndarray) -> float:
    """Root mean square about zero of the finite values (NaN without any)."""
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    return float(np.sqrt(np.mean(x ** 2))) if len(x) else float("nan")


@dataclass
class Prepared:
    """Signals on the uniform grid before alignment; shared by :func:`run` and the calibration fit."""

    time: np.ndarray
    fs: float
    pupil: np.ndarray           # device units, smoothed, NaN in long gaps
    pupil_fast: np.ndarray      # device units, lightly smoothed, NaN in long gaps
    valid: np.ndarray           # False inside gaps longer than max_gap
    luminance: np.ndarray       # cd/m²
    scale: Optional[float]      # device units to mm, None for pixel data (fitted per recording)
    notes: list = field(default_factory=list)
    # How the luminance was obtained: "display", "lux sensor", "camera, fixed exposure" or
    # "camera, relative" (lux device without lux data, mapped onto Lmin–Lmax like a display)
    mode: str = "display"

    @property
    def photometric(self) -> bool:
        """The luminance comes from the Lmin/Lmax mapping, so Lmin and Lmax have expected pupils."""
        return self.mode in ("display", "camera, relative")


def prepare(rec: Recording, video: VideoResult, params: Parameters) -> Prepared:
    """Pupil and luminance on the uniform analysis grid, before the pupil scale and alignment.

    Pupil (each eye, in device units): with a known scale, samples outside PUPIL_RANGE_MM and fast
    changes (:func:`artefacts`) are removed; pixel data (no scale) skip both filters, which need
    millimetres. The eyes are combined (``params.eye``), resampled at ``analysis_rate`` (0: the
    device's rate) with gaps up to ``max_gap`` interpolated, and smoothed twice: Savitzky-Golay
    order 2 over 0.5 s (``pupil``) and order 6 over 0.25 s (``pupil_fast``, the "raw" curve).

    Luminance (cd/m²), shifted by ``timelag``: from the lux sensor distributed with the video, the
    fixed-exposure camera, or the display photometry (also used, as relative, for a lux device
    without lux data). See ``docs/processing/pipeline.md``.
    """
    if len(video.time) < 2:
        raise ValueError("Video analysis has too few samples")
    profile = rec.profile
    fs = params.analysis_rate or profile.native_rate
    scale = None
    eyes = [np.asarray(rec.pupil_left, dtype=float), np.asarray(rec.pupil_right, dtype=float)]
    if profile.pupil_scale is not None:
        scale = profile.pupil_scale * params.pupil_correction
        for k, raw in enumerate(eyes):
            with np.errstate(invalid="ignore"):
                bad = (raw * scale < PUPIL_RANGE_MM[0]) | (raw * scale > PUPIL_RANGE_MM[1])
            raw = np.where(bad, np.nan, raw)
            eyes[k] = np.where(artefacts(rec.time, raw * scale, params.max_pupil_speed,
                                         params.artefact_padding), np.nan, raw)
    raw = combine_eyes(eyes[0], eyes[1], params.eye)
    time, pupil, valid = resample(rec.time, raw, fs, params.max_gap)
    smooth = savgol_filter(pupil, _odd(fs / 2 + 1), 2)
    fast = savgol_filter(pupil, _odd(fs / 4 + 1, 9), 6)
    smooth[~valid] = np.nan
    fast[~valid] = np.nan

    order = np.argsort(video.time)
    vt = video.time[order] - params.timelag
    notes = []
    if rec.luminance_source == "lux_sensor" and rec.lux_values is not None and len(rec.lux_values) >= 2:
        # Pignoni et al. 2021, eq. 5-8: the sensor gives the average luminance of the view; the
        # video distributes it: L = avgL · rL(gaze-weighted) / rL(whole frame).
        avg = luminance_from_lux(rec, params, time)
        lum = avg
        if params.lux_use_video:
            y_w, y_frame = relative_luminances(video, params)
            ratio = np.where(y_frame[order] > 1e-4, y_w[order] / np.maximum(y_frame[order], 1e-4), 1.0)
            lum = avg * np.interp(time, vt, ratio)
        mode = "lux sensor"
    elif rec.luminance_source == "lux_sensor" and params.camera_exposure == "fixed":
        # Fixed exposure: pixel values are proportional to scene luminance up to saturation.
        y_w, _ = relative_luminances(video, params)
        lum = np.interp(time, vt, params.camera_full_scale * y_w[order])
        clipped = clipped_fraction(video)
        if clipped > CLIPPED_WARNING:
            notes.append(f"The gaze area is saturated in {clipped:.0%} of the video samples: luminance is "
                         "underestimated there. A shorter exposure would avoid it.")
        mode = "camera, fixed exposure"
    else:
        mode = "display"
        if rec.luminance_source == "lux_sensor":
            notes.append("No lux sensor data found: luminance is estimated from the scene camera alone, "
                         "mapped onto Lmin–Lmax. With automatic exposure this is only relative; if the "
                         "exposure was fixed, set camera exposure to 'fixed'.")
            mode = "camera, relative"
        lum = np.interp(time, vt, scene_luminance(video, params)[order])
    return Prepared(time, fs, smooth, fast, valid, lum, scale, notes, mode)


# Mean code value above which an area counts as saturated, and the share of saturated samples
# that triggers a warning.
CLIPPED_CODE = 250
CLIPPED_WARNING = 0.05


def clipped_fraction(video: VideoResult) -> float:
    """Share of video samples whose gaze area is saturated in any channel."""
    if not len(video.time):
        return 0.0
    return float((video.fixation_rgb.max(axis=1) >= CLIPPED_CODE).mean())


@dataclass
class CameraCalibration:
    white: float          # cd/m² at full scale for the recording's exposure
    spread: float         # 90th / 10th percentile of the per-sample estimates (1 = perfectly constant)
    samples: int
    notes: list


def calibrate_camera(rec: Recording, video: VideoResult, params: Parameters) -> CameraCalibration:
    """Full-scale luminance of a fixed-exposure scene camera, from a recording that also has a lux log.

    The sensor's average luminance and the whole frame's relative luminance describe the same view, so
    their ratio is the luminance that saturates the camera. It is estimated per video sample and the
    median is kept. A large spread means the exposure was not fixed (or the sensor and camera saw
    different scenes). Apply it to recordings without a lux log made with the same exposure, or scale
    it with camera_reference_ms / camera_exposure_ms.
    """
    if rec.lux_values is None or len(rec.lux_values) < 2:
        raise ValueError("The recording has no lux sensor data to calibrate the camera with")
    order = np.argsort(video.time)
    t = video.time[order] - params.timelag
    _, y_frame = relative_luminances(video, params)
    y_frame = y_frame[order]
    avg = luminance_from_lux(rec, params, t)
    inside = (t >= rec.lux_time[0] - params.timelag) & (t <= rec.lux_time[-1] - params.timelag)
    usable = inside & (y_frame > 0.005) & (video.background_rgb[order].max(axis=1) < CLIPPED_CODE)
    if usable.sum() < 10:
        raise ValueError("Too few video samples overlap the lux log with a usable (not black, not saturated) frame")
    ratio = avg[usable] / y_frame[usable]
    p10, p50, p90 = np.percentile(ratio, [10, 50, 90])
    spread = float(p90 / p10) if p10 > 0 else float("inf")
    notes = []
    if spread > 2:
        notes.append(f"The estimate varies {spread:.1f}× across the recording: the exposure was probably not "
                     "fixed, or the sensor and the camera saw different parts of the scene.")
    return CameraCalibration(float(p50), spread, int(usable.sum()), notes)


def luminance_from_lux(rec: Recording, params: Parameters, time: np.ndarray) -> np.ndarray:
    """Average luminance (cd/m²) from the lux sensor on the analysis grid."""
    avg = lux_module.average_luminance(lux_module.smooth(rec.lux_values), params.lux_gain,
                                       params.lux_offset, params.lux_solid_angle)
    return np.interp(time, rec.lux_time - params.timelag, avg)


def event_mask(time: np.ndarray, events, labels: str) -> np.ndarray:
    """Samples inside events whose label is in the comma-separated ``labels`` (case-insensitive)."""
    wanted = {x.strip().lower() for x in labels.split(",") if x.strip()}
    mask = np.zeros(len(time), bool)
    for e in events:
        if e.label.strip().lower() in wanted:
            mask |= (time >= e.start) & (time <= e.end)
    return mask


def alignment_offset(expected, measured, valid, params: Parameters, time, events, notes) -> float:
    """Offset (mm) added to the scaled measured PD, according to ``params.alignment``."""
    mode = params.alignment
    if mode == "none":
        return 0.0
    if mode == "fixed":
        return params.pupil_offset
    use = valid & np.isfinite(measured)
    if mode == "baseline":
        base = use & event_mask(time, events, params.baseline_events)
        if base.any():
            return float(np.median(expected[base] - measured[base]))
        notes.append(f"No events labelled '{params.baseline_events}': aligned on the whole recording instead.")
    return float(np.median(expected[use] - measured[use]))


def run(rec: Recording, video: VideoResult, params: Parameters) -> Result:
    """The whole analysis: :func:`prepare`, the expected pupil, the pupil scale (fitted to the expected
    mean for pixel data), the alignment offset, then ΔPD averaged over ``cw_window`` s and smoothed
    (Savitzky-Golay order 1, ``cw_smoothing`` windows each side). Warnings are collected in the result."""
    prep = prepare(rec, video, params)
    profile, fs, time, valid = rec.profile, prep.fs, prep.time, prep.valid
    notes = list(prep.notes)
    if profile.experimental:
        notes.insert(0, f"Experimental support for {profile.name}: the reader has not been checked on a real "
                        "recording yet; check the pupil, gaze and timing before relying on the results.")
    notes += rec.notes
    expected = expected_pupil(prep.luminance, fs, params, profile.field_area)

    scale = prep.scale
    if scale is None:
        # Pixel units: scale so the mean measured PD equals the mean expected PD (2021 method).
        scale = float(np.nanmean(expected[valid]) / np.nanmean(prep.pupil)) * params.pupil_correction
    measured = prep.pupil * scale
    measured_raw = prep.pupil_fast * scale
    offset = alignment_offset(expected, measured, valid, params, time, rec.events, notes)
    measured += offset
    measured_raw += offset
    median = float(np.nanmedian(measured))     # as plotted and exported, after the offset
    if not PLAUSIBLE_MM[0] <= median <= PLAUSIBLE_MM[1]:
        notes.append(f"Median measured pupil is {median:.2f} mm, outside {PLAUSIBLE_MM[0]:g}–"
                     f"{PLAUSIBLE_MM[1]:g} mm: check the pupil scale correction and offset.")

    window_n = max(int(round(params.cw_window * fs)), 1)
    cw_time, cw = windowed_difference(time, measured, expected, window_n)
    good = np.isfinite(cw)
    if good.sum() >= 3:
        smooth = savgol_filter(interp_nan(cw), min(_odd(params.cw_smoothing * 2), _odd(len(cw) - 2)), 1)
        cw = np.where(good, smooth, np.nan)

    if prep.photometric:
        ends = steady_pupil(np.array([params.l_min, params.l_max]), params, profile.field_area)
    else:
        ends = (float("nan"), float("nan"))  # Lmin/Lmax are not used with a lux sensor or fixed exposure

    return Result(time=time, luminance=prep.luminance, measured_raw=measured_raw, measured=measured,
                  expected=expected, cw_time=cw_time, cw=cw, cw_rms=residual_rms(cw),
                  cw_sd=float(np.nanstd(cw)) if good.any() else float("nan"),
                  expected_black=float(ends[0]), expected_white=float(ends[1]), offset=offset,
                  pupil_scale=scale, rate=fs, measured_rate=rec.measured_rate,
                  gap_fraction=float(1 - valid.mean()), warnings=notes, luminance_mode=prep.mode)


def event_means(result: Result, events) -> list[tuple[str, float, float, float]]:
    """Mean ΔPD (mm) within each event: (label, start, end, mean)."""
    out = []
    for e in events:
        sel = (result.cw_time >= e.start) & (result.cw_time <= e.end)
        vals = result.cw[sel]
        vals = vals[np.isfinite(vals)]
        out.append((e.label, e.start, e.end, float(vals.mean()) if len(vals) else float("nan")))
    return out


def export(result: Result, rec: Recording, params: Parameters, out_dir: Path) -> list[Path]:
    """Write ``<name>_pupil.csv``, ``<name>_cw.csv``, ``<name>_events.csv`` (with events) and
    ``<name>_params.json`` to ``out_dir``; returns their paths. See docs/reference/outputs.md."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []

    p = out_dir / f"{rec.name}_pupil.csv"
    with open(p, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["timestamp_unix", "timestamp_relative", "luminance_cdm2",
                    "pupil_measured_mm", "pupil_measured_raw_mm", "pupil_expected_mm"])
        for row in zip(result.time + rec.epoch_start, result.time, result.luminance,
                       result.measured, result.measured_raw, result.expected):
            w.writerow([f"{v:.6f}" for v in row])
    paths.append(p)

    p = out_dir / f"{rec.name}_cw.csv"
    with open(p, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["timestamp_unix", "timestamp_relative", "delta_pd_mm", "delta_pd_sd"])
        for t, v in zip(result.cw_time, result.cw):
            w.writerow([f"{t + rec.epoch_start:.6f}", f"{t:.6f}", f"{v:.6f}", f"{v / result.cw_sd:.6f}"])
    paths.append(p)

    if rec.events:
        p = out_dir / f"{rec.name}_events.csv"
        with open(p, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["event", "start_relative", "end_relative", "mean_delta_pd_mm", "mean_delta_pd_sd"])
            for label, s, e, m in event_means(result, rec.events):
                w.writerow([label, f"{s:.3f}", f"{e:.3f}", f"{m:.6f}", f"{m / result.cw_sd:.6f}"])
        paths.append(p)

    p = out_dir / f"{rec.name}_params.json"
    params.save(p)
    paths.append(p)
    return paths
