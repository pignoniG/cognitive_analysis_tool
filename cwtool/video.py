"""Two-area scene video analysis.

For every gaze sample, the pixels inside a small circle centred on the gaze
(fixation area) and over the background are measured. The background is the
whole frame, or, for videos whose scene is a circle with black corners
(Varjo), a centred circle that excludes the corners.

Pixels are linearised before averaging (the mean of (C/255)^γ, not the mean
code value raised to γ), which matters for textured areas. So that γ can still
change without re-reading the video, each area's per-channel histogram is
turned into linear means for a grid of γ values; :meth:`VideoResult.linear`
interpolates between them (error below 0.001 of full scale). Luminance
weighting and photometric calibration are applied later by the pipeline.
"""

from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Optional

import cv2
import numpy as np

from cwtool.params import VideoSettings

CACHE_CSV = "cwtool_video.csv"
CACHE_JSON = "cwtool_video.json"
CACHE_FORMAT = 2

GAMMA_GRID = np.round(np.arange(1.4, 3.0001, 0.2), 2)   # γ values the linear means are stored for
GAMMA_RANGE = (float(GAMMA_GRID[0]), float(GAMMA_GRID[-1]))
_CODES = np.arange(256, dtype=float)
_LUT = (_CODES / 255.0)[None, :] ** GAMMA_GRID[:, None]   # (G, 256)


def _histograms(pixels: np.ndarray) -> np.ndarray:
    """Per-channel 256-bin histograms of (n, 3) uint8 pixels -> (3, 256)."""
    return np.stack([np.bincount(pixels[:, c], minlength=256) for c in range(3)]).astype(float)


def _means(hist: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Mean code value (3,) and mean linear value per γ in the grid (G, 3) from (3, 256) histograms."""
    n = max(hist[0].sum(), 1.0)
    return hist @ _CODES / n, (hist @ _LUT.T / n).T


@dataclass
class VideoResult:
    time: np.ndarray            # s, relative clock, one row per analysed gaze sample
    fixation_rgb: np.ndarray    # (N, 3) mean 8-bit R, G, B (for display)
    background_rgb: np.ndarray  # (N, 3)
    fixation_lin: np.ndarray    # (N, G, 3) mean of (C/255)^γ for each γ in GAMMA_GRID
    background_lin: np.ndarray  # (N, G, 3)

    def linear(self, gamma: float) -> tuple[np.ndarray, np.ndarray]:
        """Per-pixel-linearised mean R, G, B (N, 3) of the fixation and background areas.
        ``gamma`` is clipped to GAMMA_RANGE; values in between are interpolated in log space."""
        g = float(np.clip(gamma, *GAMMA_RANGE))
        i = int(np.clip(np.searchsorted(GAMMA_GRID, g) - 1, 0, len(GAMMA_GRID) - 2))
        f = (g - GAMMA_GRID[i]) / (GAMMA_GRID[i + 1] - GAMMA_GRID[i])

        def interp(x):
            lo, hi = np.log(x[:, i] + 1e-12), np.log(x[:, i + 1] + 1e-12)
            return np.clip(np.exp(lo + f * (hi - lo)) - 1e-12, 0.0, 1.0)

        return interp(self.fixation_lin), interp(self.background_lin)

    @classmethod
    def empty(cls) -> "VideoResult":
        g = len(GAMMA_GRID)
        return cls(np.empty(0), np.empty((0, 3)), np.empty((0, 3)), np.empty((0, g, 3)), np.empty((0, g, 3)))

    def save(self, folder: Path, settings: VideoSettings, video: Path) -> None:
        lin_cols = [f"{area}_lin{g:.1f}_{c}" for area in ("fix", "bg") for g in GAMMA_GRID for c in "rgb"]
        n = len(self.time)
        with open(folder / CACHE_CSV, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["time", "fix_r", "fix_g", "fix_b", "bg_r", "bg_g", "bg_b"] + lin_cols)
            table = np.column_stack([self.time, self.fixation_rgb, self.background_rgb,
                                     self.fixation_lin.reshape(n, -1), self.background_lin.reshape(n, -1)])
            for row in table:
                w.writerow([f"{v:.6g}" for v in row])
        meta = {"format": CACHE_FORMAT, "gammas": GAMMA_GRID.tolist(), "settings": asdict(settings),
                "video": video.name}
        (folder / CACHE_JSON).write_text(json.dumps(meta, indent=2))

    @classmethod
    def load_cached(cls, folder: Path, settings: VideoSettings, video: Path) -> Optional["VideoResult"]:
        """Return the cached result if it was made from the same video, settings and format."""
        meta_path, csv_path = folder / CACHE_JSON, folder / CACHE_CSV
        if not (meta_path.exists() and csv_path.exists()):
            return None
        meta = json.loads(meta_path.read_text())
        if (meta.get("format") != CACHE_FORMAT or meta.get("gammas") != GAMMA_GRID.tolist()
                or meta.get("settings") != asdict(settings) or meta.get("video") != video.name):
            return None
        data = np.loadtxt(csv_path, delimiter=",", skiprows=1, ndmin=2)
        g = len(GAMMA_GRID)
        lin = data[:, 7:].reshape(len(data), 2, g, 3)
        return cls(time=data[:, 0], fixation_rgb=data[:, 1:4], background_rgb=data[:, 4:7],
                   fixation_lin=lin[:, 0], background_lin=lin[:, 1])


def _circle_mask(shape: tuple[int, int], center: tuple[int, int], radius: int) -> np.ndarray:
    mask = np.zeros(shape, dtype=np.uint8)
    cv2.circle(mask, center, max(radius, 1), 255, -1)
    return mask


def radii(frame_height: int, settings: VideoSettings) -> tuple[int, int]:
    """Scene circle and fixation circle radii (px) for a frame of this height."""
    field_r = int(frame_height / 2 * settings.field_radius)
    fix_r = max(int(settings.fixation_radius_deg / settings.vertical_fov * frame_height), 1)
    return field_r, fix_r


def frame_index(t, fps: float):
    """Video frame shown at time ``t`` (s, video clock)."""
    return (np.asarray(t) * fps).astype(int)


def prepare_frame(frame_bgr: np.ndarray, settings: VideoSettings) -> np.ndarray:
    """Downscale a decoded frame to the analysis width and convert to RGB."""
    scale = settings.analysis_width / frame_bgr.shape[1]
    size = (settings.analysis_width, max(int(frame_bgr.shape[0] * scale), 1))
    small = cv2.resize(frame_bgr, size, interpolation=cv2.INTER_AREA)
    return cv2.cvtColor(small, cv2.COLOR_BGR2RGB)


def field_mask(shape: tuple[int, int], settings: VideoSettings) -> np.ndarray:
    """Background area: the centred scene circle for circular-mask videos
    (Varjo), otherwise the whole frame."""
    h, w = shape
    if not settings.circular_mask:
        return np.full((h, w), 255, dtype=np.uint8)
    return _circle_mask((h, w), (w // 2, h // 2), radii(h, settings)[0])


def analyse_frame(frame_rgb: np.ndarray, gaze_px: np.ndarray, settings: VideoSettings,
                  mask: Optional[np.ndarray] = None):
    """Measure one frame. ``gaze_px`` is (M, 2) pixel coordinates in the frame.

    Returns (fix_rgb, bg_rgb, fix_lin, bg_lin): mean code values (M, 3) and
    per-pixel-linearised means for each γ in GAMMA_GRID (M, G, 3).
    """
    h, w = frame_rgb.shape[:2]
    fix_r = radii(h, settings)[1]
    if mask is None:
        mask = field_mask((h, w), settings)
    frame_rgb = np.ascontiguousarray(frame_rgb, dtype=np.uint8)

    field_hist = _histograms(frame_rgb[mask > 0])
    bg_rgb_all, bg_lin_all = _means(field_hist)

    m = len(gaze_px)
    fix_rgb, bg_rgb = np.empty((m, 3)), np.empty((m, 3))
    fix_lin, bg_lin = np.empty((m, len(GAMMA_GRID), 3)), np.empty((m, len(GAMMA_GRID), 3))
    yy, xx = np.ogrid[:h, :w]
    for i, (gx, gy) in enumerate(gaze_px):
        gx, gy = int(np.clip(gx, 0, w - 1)), int(np.clip(gy, 0, h - 1))
        x0, x1 = max(gx - fix_r, 0), min(gx + fix_r + 1, w)
        y0, y1 = max(gy - fix_r, 0), min(gy + fix_r + 1, h)
        disc = (xx[:, x0:x1] - gx) ** 2 + (yy[y0:y1, :] - gy) ** 2 <= fix_r ** 2
        crop = frame_rgb[y0:y1, x0:x1]
        fix_rgb[i], fix_lin[i] = _means(_histograms(crop[disc]))

        if settings.background_excludes_fixation:
            overlap = disc & (mask[y0:y1, x0:x1] > 0)
            bg_rgb[i], bg_lin[i] = _means(field_hist - _histograms(crop[overlap]))
        else:
            bg_rgb[i], bg_lin[i] = bg_rgb_all, bg_lin_all
    return fix_rgb, bg_rgb, fix_lin, bg_lin


def analyse_video(video: Path, time: np.ndarray, gaze: np.ndarray, settings: VideoSettings,
                  progress: Optional[Callable[[float], None]] = None,
                  cancelled: Optional[Callable[[], bool]] = None) -> VideoResult:
    """Analyse ``video`` at each gaze sample. ``time`` is on the video clock (s),
    ``gaze`` is normalised (N, 2) with NaN for invalid samples, which are skipped."""
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise IOError(f"Cannot open video {video}")
    fps = cap.get(cv2.CAP_PROP_FPS)
    n_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if fps <= 0:
        raise IOError(f"Video {video} reports no frame rate")

    valid = np.isfinite(gaze).all(axis=1) & np.isfinite(time)
    idx = np.flatnonzero(valid)
    frame_of = frame_index(time[idx], fps)
    order = np.argsort(frame_of, kind="stable")
    idx, frame_of = idx[order], frame_of[order]

    times, fixes, bgs, fix_lins, bg_lins = [], [], [], [], []
    mask = None
    pos, frame_no = 0, 0
    last_frame = frame_of[-1] if len(frame_of) else -1
    while pos < len(idx) and frame_no <= last_frame:
        ok, frame = cap.read()
        if not ok:
            break
        if frame_of[pos] == frame_no:
            end = pos
            while end < len(idx) and frame_of[end] == frame_no:
                end += 1
            small = prepare_frame(frame, settings)
            h, w = small.shape[:2]
            if mask is None:
                mask = field_mask((h, w), settings)
            sample = idx[pos:end]
            gaze_px = gaze[sample] * [w, h]
            fix, bg, fix_lin, bg_lin = analyse_frame(small, gaze_px, settings, mask)
            times.append(time[sample])
            fixes.append(fix)
            bgs.append(bg)
            fix_lins.append(fix_lin)
            bg_lins.append(bg_lin)
            pos = end
        # Skip samples pointing at frames already passed (should not happen with sorted input).
        while pos < len(idx) and frame_of[pos] < frame_no:
            pos += 1
        frame_no += 1
        if progress and n_frames:
            progress(min(frame_no / max(last_frame + 1, 1), 1.0))
        if cancelled and cancelled():
            break
    cap.release()

    if not times:
        return VideoResult.empty()
    return VideoResult(np.concatenate(times), np.vstack(fixes), np.vstack(bgs),
                       np.concatenate(fix_lins), np.concatenate(bg_lins))
