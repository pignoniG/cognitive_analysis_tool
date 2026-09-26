"""Two-area scene video analysis.

For every gaze sample, the mean RGB inside a small circle centred on the gaze
(fixation area) and over the background is measured. The background is the
whole frame, or, for videos whose scene is a circle with black corners
(Varjo), a centred circle that excludes the corners. Luminance weighting is applied later by the
pipeline, so the fixation weight and photometric calibration can change
without re-reading the video.
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


@dataclass
class VideoResult:
    time: np.ndarray        # s, relative clock, one row per analysed gaze sample
    fixation_rgb: np.ndarray  # (N, 3) mean 8-bit R, G, B
    background_rgb: np.ndarray  # (N, 3)

    def save(self, folder: Path, settings: VideoSettings, video: Path) -> None:
        with open(folder / CACHE_CSV, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["time", "fix_r", "fix_g", "fix_b", "bg_r", "bg_g", "bg_b"])
            for row in np.column_stack([self.time, self.fixation_rgb, self.background_rgb]):
                w.writerow([f"{v:.6f}" for v in row])
        meta = {"settings": asdict(settings), "video": video.name}
        (folder / CACHE_JSON).write_text(json.dumps(meta, indent=2))

    @classmethod
    def load_cached(cls, folder: Path, settings: VideoSettings, video: Path) -> Optional["VideoResult"]:
        """Return the cached result if it was made from the same video and settings."""
        meta_path, csv_path = folder / CACHE_JSON, folder / CACHE_CSV
        if not (meta_path.exists() and csv_path.exists()):
            return None
        meta = json.loads(meta_path.read_text())
        if meta.get("settings") != asdict(settings) or meta.get("video") != video.name:
            return None
        data = np.loadtxt(csv_path, delimiter=",", skiprows=1, ndmin=2)
        return cls(time=data[:, 0], fixation_rgb=data[:, 1:4], background_rgb=data[:, 4:7])


def _circle_mask(shape: tuple[int, int], center: tuple[int, int], radius: int) -> np.ndarray:
    mask = np.zeros(shape, dtype=np.uint8)
    cv2.circle(mask, center, max(radius, 1), 255, -1)
    return mask


def radii(frame_height: int, settings: VideoSettings) -> tuple[int, int]:
    """Scene circle and fixation circle radii (px) for a frame of this height."""
    field_r = int(frame_height / 2 * settings.field_radius)
    fix_r = max(int(frame_height / 2 * settings.field_radius * settings.fixation_ratio), 1)
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
                  mask: Optional[np.ndarray] = None) -> tuple[np.ndarray, np.ndarray]:
    """Measure one frame. ``gaze_px`` is (M, 2) pixel coordinates in the frame.
    Returns (M, 3) fixation and background mean RGB."""
    h, w = frame_rgb.shape[:2]
    fix_r = radii(h, settings)[1]
    if mask is None:
        mask = field_mask((h, w), settings)

    pixels = frame_rgb.reshape(-1, 3).astype(np.float64)
    in_field = mask.reshape(-1) > 0
    field_sum = pixels[in_field].sum(axis=0)
    field_n = int(in_field.sum())

    fix_out = np.empty((len(gaze_px), 3))
    bg_out = np.empty((len(gaze_px), 3))
    yy, xx = np.ogrid[:h, :w]
    for i, (gx, gy) in enumerate(gaze_px):
        gx, gy = int(np.clip(gx, 0, w - 1)), int(np.clip(gy, 0, h - 1))
        x0, x1 = max(gx - fix_r, 0), min(gx + fix_r + 1, w)
        y0, y1 = max(gy - fix_r, 0), min(gy + fix_r + 1, h)
        disc = (xx[:, x0:x1] - gx) ** 2 + (yy[y0:y1, :] - gy) ** 2 <= fix_r ** 2
        crop = frame_rgb[y0:y1, x0:x1].reshape(-1, 3).astype(np.float64)
        sel = disc.reshape(-1)
        fix_out[i] = crop[sel].mean(axis=0)

        if settings.background_excludes_fixation:
            overlap = sel & (mask[y0:y1, x0:x1].reshape(-1) > 0)
            n = field_n - int(overlap.sum())
            bg_out[i] = (field_sum - crop[overlap].sum(axis=0)) / max(n, 1)
        else:
            bg_out[i] = field_sum / max(field_n, 1)
    return fix_out, bg_out


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

    times, fixes, bgs = [], [], []
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
            fix, bg = analyse_frame(small, gaze_px, settings, mask)
            times.append(time[sample])
            fixes.append(fix)
            bgs.append(bg)
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
        return VideoResult(np.empty(0), np.empty((0, 3)), np.empty((0, 3)))
    return VideoResult(np.concatenate(times), np.vstack(fixes), np.vstack(bgs))
