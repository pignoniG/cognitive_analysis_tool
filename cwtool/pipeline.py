"""From a recording, its video analysis and parameters to ΔPD (cognitive workload)."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from scipy.signal import savgol_filter

from cwtool import luminance, model
from cwtool.params import Parameters
from cwtool.recording import Recording
from cwtool.video import VideoResult


@dataclass
class Result:
    time: np.ndarray            # s, relative, pupil sample clock
    luminance: np.ndarray       # cd/m², weighted fixation/background
    measured_raw: np.ndarray    # mm, lightly smoothed, scaled and aligned
    measured: np.ndarray        # mm, smoothed, scaled and aligned
    expected: np.ndarray        # mm, Watson & Yellott with dynamics
    cw_time: np.ndarray         # s, ΔPD window centres
    cw: np.ndarray              # mm, ΔPD = measured - expected, smoothed
    cw_rms: float               # mm, RMS of ΔPD about its mean
    expected_black: float       # mm, expected PD at the panel black point
    expected_white: float       # mm, expected PD at the panel white point
    offset: float               # mm, shift applied to the measured PD


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
    left, right = interp_nan(rec.pupil_left), interp_nan(rec.pupil_right)
    if eye == "left":
        return left
    if eye == "right":
        return right
    return (left + right) / 2


def scene_luminance(video: VideoResult, params: Parameters) -> np.ndarray:
    """Absolute luminance (cd/m²) for each video sample: fixation and background
    are linearised, weighted, then mapped onto [l_min, l_max] with channel gains."""
    fix = luminance.srgb_to_linear(video.fixation_rgb, params.gamma)
    bg = luminance.srgb_to_linear(video.background_rgb, params.gamma)
    w = params.fixation_weight
    return luminance.absolute_luminance(w * fix + (1 - w) * bg, params.l_min, params.l_max, params.gains)


def expected_pupil(lum: np.ndarray, fs: float, params: Parameters) -> np.ndarray:
    pd = model.watson_yellott(lum, params.age, params.field, params.eyes, params.reference_age)
    pd = model.delay(pd, fs, params.delay)
    if params.dynamics:
        pd = model.attack_release(pd, fs, params.attack, params.release)
    return pd


def windowed_difference(time, a, b, window_n: int):
    """Mean of (a - b) over consecutive windows of ``window_n`` samples."""
    n = len(a) // window_n
    if n == 0:
        return np.empty(0), np.empty(0)
    d = (np.asarray(a) - np.asarray(b))[: n * window_n].reshape(n, window_n)
    t = np.asarray(time)[: n * window_n].reshape(n, window_n)
    return t.mean(axis=1), np.nanmean(d, axis=1)


def run(rec: Recording, video: VideoResult, params: Parameters) -> Result:
    if rec.luminance_source != "display":
        raise NotImplementedError("Lux-sensor recordings (Pupil Core / Neon) are not supported yet")
    if len(video.time) < 2:
        raise ValueError("Video analysis has too few samples")

    fs = rec.sample_rate
    pupil = select_pupil(rec, params.eye)
    measured = savgol_filter(pupil, _odd(fs / 2 + 1), 2)
    measured_raw = savgol_filter(pupil, _odd(fs / 4 + 1, 9), 6)

    order = np.argsort(video.time)
    lum_video = scene_luminance(video, params)[order]
    lum = np.interp(rec.time, video.time[order] - params.timelag, lum_video)

    expected = expected_pupil(lum, fs, params)

    measured = measured * params.pupil_scale
    measured_raw = measured_raw * params.pupil_scale
    offset = float(np.mean(expected) - np.mean(measured)) if params.align_mean else 0.0
    measured += offset
    measured_raw += offset

    window_n = max(int(round(params.cw_window * fs)), 1)
    cw_time, cw = windowed_difference(rec.time, measured, expected, window_n)
    if len(cw) >= 3:
        cw = savgol_filter(interp_nan(cw), min(_odd(params.cw_smoothing * 2), _odd(len(cw) - 2)), 1)
    cw_rms = float(np.sqrt(np.mean((cw - cw.mean()) ** 2))) if len(cw) else float("nan")

    ends = model.watson_yellott(np.array([params.l_min, params.l_max]), params.age, params.field,
                                params.eyes, params.reference_age)

    return Result(time=rec.time, luminance=lum, measured_raw=measured_raw, measured=measured,
                  expected=expected, cw_time=cw_time, cw=cw, cw_rms=cw_rms,
                  expected_black=float(ends[0]), expected_white=float(ends[1]), offset=offset)


def event_means(result: Result, events) -> list[tuple[str, float, float, float]]:
    """Mean ΔPD within each event: (label, start, end, mean)."""
    out = []
    for e in events:
        sel = (result.cw_time >= e.start) & (result.cw_time <= e.end)
        out.append((e.label, e.start, e.end, float(np.mean(result.cw[sel])) if sel.any() else float("nan")))
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
