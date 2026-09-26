"""From a recording, its video analysis and parameters to ΔPD (cognitive workload)."""

from __future__ import annotations

import csv
import warnings
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from scipy.signal import savgol_filter

from cwtool import luminance, model
from cwtool.params import Parameters
from cwtool.recording import Recording
from cwtool.video import VideoResult


@dataclass
class Result:
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


def _odd(n: int, minimum: int = 3) -> int:
    n = max(int(n), minimum)
    return n if n % 2 else n + 1


def interp_nan(x: np.ndarray) -> np.ndarray:
    x = np.asarray(x, dtype=float).copy()
    bad = ~np.isfinite(x)
    if bad.all():
        raise ValueError("signal has no valid samples")
    if bad.any():
        i = np.arange(len(x))
        x[bad] = np.interp(i[bad], i[~bad], x[~bad])
    return x


def select_pupil(rec: Recording, eye: str) -> np.ndarray:
    """Pupil in device units on the recording's own clock; NaN where invalid.
    "both" averages the eyes, falling back to one eye where the other is missing."""
    if eye == "left":
        return np.asarray(rec.pupil_left, dtype=float)
    if eye == "right":
        return np.asarray(rec.pupil_right, dtype=float)
    pair = np.vstack([rec.pupil_left, rec.pupil_right]).astype(float)
    with np.errstate(all="ignore"), warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        return np.nanmean(pair, axis=0)


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


def scene_luminance(video: VideoResult, params: Parameters) -> np.ndarray:
    """Absolute luminance (cd/m²) for each video sample: fixation and background
    are linearised, weighted, then mapped onto [l_min, l_max] with channel gains."""
    fix = luminance.srgb_to_linear(video.fixation_rgb, params.gamma)
    bg = luminance.srgb_to_linear(video.background_rgb, params.gamma)
    w = params.fixation_weight
    return luminance.absolute_luminance(w * fix + (1 - w) * bg, params.l_min, params.l_max, params.gains)


# Scaled pupil diameters outside this range (mm) are treated as tracking errors.
PUPIL_RANGE_MM = (1.0, 9.0)
# A median diameter outside this range (mm) suggests a wrong pupil scale.
PLAUSIBLE_MM = (2.0, 8.0)


def expected_pupil(lum: np.ndarray, fs: float, params: Parameters, field_area: float) -> np.ndarray:
    pd = model.watson_yellott(lum, params.age, field_area, params.eyes, params.reference_age)
    pd = model.delay(pd, fs, params.delay)
    if params.dynamics:
        pd = model.attack_release(pd, fs, params.attack, params.release)
    return pd


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
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    return float(np.sqrt(np.mean(x ** 2))) if len(x) else float("nan")


def run(rec: Recording, video: VideoResult, params: Parameters) -> Result:
    if rec.luminance_source != "display":
        raise NotImplementedError("Lux-sensor recordings (Pupil Core / Neon) are not supported yet")
    if len(video.time) < 2:
        raise ValueError("Video analysis has too few samples")

    profile = rec.profile
    notes = []
    fs = params.analysis_rate or profile.native_rate
    raw = select_pupil(rec, params.eye)
    if profile.pupil_scale is not None:
        scale = profile.pupil_scale * params.pupil_correction
        with np.errstate(invalid="ignore"):
            outside = (raw * scale < PUPIL_RANGE_MM[0]) | (raw * scale > PUPIL_RANGE_MM[1])
        raw = np.where(outside, np.nan, raw)
    time, pupil, valid = resample(rec.time, raw, fs, params.max_gap)
    measured = savgol_filter(pupil, _odd(fs / 2 + 1), 2)
    measured_raw = savgol_filter(pupil, _odd(fs / 4 + 1, 9), 6)
    measured[~valid] = np.nan
    measured_raw[~valid] = np.nan

    order = np.argsort(video.time)
    lum_video = scene_luminance(video, params)[order]
    lum = np.interp(time, video.time[order] - params.timelag, lum_video)

    expected = expected_pupil(lum, fs, params, profile.field_area)

    if profile.pupil_scale is None:
        # Pixel units: scale so the mean measured PD equals the mean expected PD (2021 method).
        scale = float(np.nanmean(expected[valid]) / np.nanmean(measured)) * params.pupil_correction
    measured = measured * scale
    measured_raw = measured_raw * scale
    median = float(np.nanmedian(measured))
    if not PLAUSIBLE_MM[0] <= median <= PLAUSIBLE_MM[1]:
        notes.append(f"Median measured pupil is {median:.2f} mm, outside {PLAUSIBLE_MM[0]:g}–"
                     f"{PLAUSIBLE_MM[1]:g} mm: check the pupil scale correction.")
    offset = float(np.nanmean(expected[valid]) - np.nanmean(measured)) if params.align_mean else 0.0
    measured += offset
    measured_raw += offset

    window_n = max(int(round(params.cw_window * fs)), 1)
    cw_time, cw = windowed_difference(time, measured, expected, window_n)
    good = np.isfinite(cw)
    if good.sum() >= 3:
        smooth = savgol_filter(interp_nan(cw), min(_odd(params.cw_smoothing * 2), _odd(len(cw) - 2)), 1)
        cw = np.where(good, smooth, np.nan)

    ends = model.watson_yellott(np.array([params.l_min, params.l_max]), params.age, profile.field_area,
                                params.eyes, params.reference_age)

    return Result(time=time, luminance=lum, measured_raw=measured_raw, measured=measured,
                  expected=expected, cw_time=cw_time, cw=cw, cw_rms=residual_rms(cw),
                  cw_sd=float(np.nanstd(cw)) if good.any() else float("nan"),
                  expected_black=float(ends[0]), expected_white=float(ends[1]), offset=offset,
                  pupil_scale=scale, rate=fs, measured_rate=rec.measured_rate,
                  gap_fraction=float(1 - valid.mean()), warnings=notes)


def event_means(result: Result, events) -> list[tuple[str, float, float, float]]:
    """Mean ΔPD within each event: (label, start, end, mean)."""
    out = []
    for e in events:
        sel = (result.cw_time >= e.start) & (result.cw_time <= e.end)
        vals = result.cw[sel]
        vals = vals[np.isfinite(vals)]
        out.append((e.label, e.start, e.end, float(vals.mean()) if len(vals) else float("nan")))
    return out


def export(result: Result, rec: Recording, params: Parameters, out_dir: Path) -> list[Path]:
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
        w.writerow(["timestamp_unix", "timestamp_relative", "delta_pd_mm"])
        for t, v in zip(result.cw_time, result.cw):
            w.writerow([f"{t + rec.epoch_start:.6f}", f"{t:.6f}", f"{v:.6f}"])
    paths.append(p)

    if rec.events:
        p = out_dir / f"{rec.name}_events.csv"
        with open(p, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["event", "start_relative", "end_relative", "mean_delta_pd_mm"])
            for label, s, e, m in event_means(result, rec.events):
                w.writerow([label, f"{s:.3f}", f"{e:.3f}", f"{m:.6f}"])
        paths.append(p)

    p = out_dir / f"{rec.name}_params.json"
    params.save(p)
    paths.append(p)
    return paths
