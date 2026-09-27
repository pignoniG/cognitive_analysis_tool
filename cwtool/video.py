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
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Optional

import cv2
import numpy as np

from cwtool.params import VideoSettings

CACHE_CSV = "cwtool_video.csv"
CACHE_JSON = "cwtool_video.json"
CACHE_FORMAT = 4
MIN_CHUNK_FRAMES = 150   # frames per parallel chunk, at least

GAMMA_GRID = np.round(np.arange(1.4, 3.0001, 0.2), 2)   # γ values the linear means are stored for
GAMMA_RANGE = (float(GAMMA_GRID[0]), float(GAMMA_GRID[-1]))
_CODES = np.arange(256, dtype=float)
_LUT = (_CODES / 255.0)[None, :] ** GAMMA_GRID[:, None]   # (G, 256)


def _array_key(values: Optional[np.ndarray]) -> str:
    if values is None:
        return ""
    import hashlib
    return hashlib.sha1(np.ascontiguousarray(values, dtype=np.float64).tobytes()).hexdigest()[:16]


def _clock_key(frame_times: Optional[np.ndarray]) -> str:
    """Identifies how gaze samples were matched to frames, for the cache check."""
    return "fps" if frame_times is None else "times:" + _array_key(frame_times)


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
    frame_lin: np.ndarray       # (N, G, 3) whole visible scene (field mask), fixation included

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

    def frame_linear(self, gamma: float) -> np.ndarray:
        """Per-pixel-linearised mean R, G, B (N, 3) of the whole visible scene."""
        return VideoResult(self.time, self.fixation_rgb, self.background_rgb,
                           self.frame_lin, self.frame_lin, self.frame_lin).linear(gamma)[0]

    @classmethod
    def empty(cls) -> "VideoResult":
        g = len(GAMMA_GRID)
        return cls(np.empty(0), np.empty((0, 3)), np.empty((0, 3)), np.empty((0, g, 3)), np.empty((0, g, 3)),
                   np.empty((0, g, 3)))

    def save(self, folder: Path, settings: VideoSettings, video: Path,
             frame_times: Optional[np.ndarray] = None, gaze: Optional[np.ndarray] = None) -> None:
        lin_cols = [f"{area}_lin{g:.1f}_{c}" for area in ("fix", "bg", "frame") for g in GAMMA_GRID for c in "rgb"]
        n = len(self.time)
        with open(folder / CACHE_CSV, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["time", "fix_r", "fix_g", "fix_b", "bg_r", "bg_g", "bg_b"] + lin_cols)
            table = np.column_stack([self.time, self.fixation_rgb, self.background_rgb,
                                     self.fixation_lin.reshape(n, -1), self.background_lin.reshape(n, -1),
                                     self.frame_lin.reshape(n, -1)])
            for row in table:
                w.writerow([f"{v:.6g}" for v in row])
        meta = {"format": CACHE_FORMAT, "gammas": GAMMA_GRID.tolist(), "settings": asdict(settings),
                "video": video.name, "frame_clock": _clock_key(frame_times), "gaze": _array_key(gaze)}
        (folder / CACHE_JSON).write_text(json.dumps(meta, indent=2))

    @classmethod
    def load_cached(cls, folder: Path, settings: VideoSettings, video: Path,
                    frame_times: Optional[np.ndarray] = None,
                    gaze: Optional[np.ndarray] = None) -> Optional["VideoResult"]:
        """Return the cached result if it was made from the same video, settings, frame clock,
        gaze samples and format."""
        meta_path, csv_path = folder / CACHE_JSON, folder / CACHE_CSV
        if not (meta_path.exists() and csv_path.exists()):
            return None
        meta = json.loads(meta_path.read_text())
        if (meta.get("format") != CACHE_FORMAT or meta.get("gammas") != GAMMA_GRID.tolist()
                or meta.get("settings") != asdict(settings) or meta.get("video") != video.name
                or meta.get("frame_clock") != _clock_key(frame_times) or meta.get("gaze") != _array_key(gaze)):
            return None
        data = np.loadtxt(csv_path, delimiter=",", skiprows=1, ndmin=2)
        g = len(GAMMA_GRID)
        lin = data[:, 7:].reshape(len(data), 3, g, 3)
        return cls(time=data[:, 0], fixation_rgb=data[:, 1:4], background_rgb=data[:, 4:7],
                   fixation_lin=lin[:, 0], background_lin=lin[:, 1], frame_lin=lin[:, 2])


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
    """Video frame shown at time ``t`` (s, video clock) for evenly spaced frames."""
    return np.floor(np.asarray(t) * fps).astype(int)


class FrameClock:
    """Which frame belongs to a time. With recorded frame timestamps (capture instants,
    possibly unevenly spaced) the nearest frame is used, as Pupil Player does; otherwise
    frames are evenly spaced at the frame rate and frame n covers [n/fps, (n+1)/fps)."""

    def __init__(self, fps: float, times: Optional[np.ndarray] = None):
        self.fps = fps
        self.times = None if times is None else np.asarray(times, dtype=float)

    def index(self, t):
        if self.times is None:
            return frame_index(t, self.fps)
        t = np.asarray(t, dtype=float)
        i = np.clip(np.searchsorted(self.times, t), 1, len(self.times) - 1)
        nearest = np.where(t - self.times[i - 1] <= self.times[i] - t, i - 1, i)
        # Times well outside the recorded frames belong to no frame.
        half = np.median(np.diff(self.times)) / 2 if len(self.times) > 1 else 0.0
        return np.where((t < self.times[0] - half) | (t > self.times[-1] + half), -1, nearest)

    def time(self, n: int) -> float:
        """Time of frame ``n`` (its timestamp, or its start for evenly spaced frames)."""
        if self.times is None or not 0 <= n < len(self.times):
            return n / self.fps
        return float(self.times[n])


def analysis_height(width: int, height: int, analysis_width: int) -> int:
    return max(int(height * analysis_width / width), 1)


def prepare_frame(frame_bgr: np.ndarray, settings: VideoSettings, smooth: bool = False) -> np.ndarray:
    """Downscale a decoded frame to the analysis width and convert to RGB.

    Analysis uses nearest-neighbour sampling: it keeps real pixel values (blending
    neighbours would average code values before linearisation) and is much faster.
    ``smooth`` uses area averaging instead, for display.
    """
    size = (settings.analysis_width, analysis_height(frame_bgr.shape[1], frame_bgr.shape[0], settings.analysis_width))
    small = cv2.resize(frame_bgr, size, interpolation=cv2.INTER_AREA if smooth else cv2.INTER_NEAREST)
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

    Returns (fix_rgb, bg_rgb, fix_lin, bg_lin, frame_lin): mean code values (M, 3) and
    per-pixel-linearised means for each γ in GAMMA_GRID (M, G, 3); frame_lin is the whole
    visible scene, the same for every sample of the frame.
    """
    h, w = frame_rgb.shape[:2]
    fix_r = radii(h, settings)[1]
    if mask is None:
        mask = field_mask((h, w), settings)
    frame_rgb = np.ascontiguousarray(frame_rgb, dtype=np.uint8)

    field_hist = np.stack([cv2.calcHist([frame_rgb], [c], mask, [256], [0, 256]).ravel() for c in range(3)])
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
    return fix_rgb, bg_rgb, fix_lin, bg_lin, np.broadcast_to(bg_lin_all, bg_lin.shape)


def video_info(video: Path) -> tuple[float, int]:
    """Frame rate and frame count."""
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise IOError(f"Cannot open video {video}")
    fps, n = cap.get(cv2.CAP_PROP_FPS), int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()
    if fps <= 0:
        raise IOError(f"Video {video} reports no frame rate")
    return fps, n


def frame_pts(video: Path) -> list[int]:
    """Presentation timestamps of all frames in display order, read from the container
    without decoding. Frame n is the frame with the n-th smallest timestamp."""
    import av

    with av.open(str(video)) as container:
        stream = container.streams.video[0]
        return sorted(p.pts for p in container.demux(stream) if p.pts is not None)


def _frames_pyav(video: Path, wanted, first: int, last: int, width: int, decode_threads: int,
                 pts_list: list[int]):
    """Yield (frame number, RGB frame or None) for frames first..last, decoding with PyAV and
    converting only wanted frames, scaled to ``width`` and to RGB in one FFmpeg step
    (nearest-neighbour). Frames are numbered by their position in ``pts_list``, so a chunk
    that starts by seeking is aligned exactly with one that decodes from the beginning."""
    import av

    index_of = {p: i for i, p in enumerate(pts_list)}
    with av.open(str(video)) as container:
        stream = container.streams.video[0]
        stream.thread_type = "AUTO"
        stream.thread_count = decode_threads
        if first > 0 and first < len(pts_list):
            # Seek to the keyframe at or before the chunk's first frame, then decode forward.
            container.seek(pts_list[first], stream=stream, backward=True, any_frame=False)
        n = first - 1 if first == 0 else None
        for frame in container.decode(stream):
            if frame.pts is not None and frame.pts in index_of:
                n = index_of[frame.pts]
            elif n is not None:
                n += 1
            else:
                continue
            if n < first:
                continue
            if n > last:
                break
            if n in wanted:
                h = analysis_height(frame.width, frame.height, width)
                yield n, frame.to_ndarray(width=width, height=h, format="rgb24", interpolation="POINT")
            else:
                yield n, None


def _frames_opencv(video: Path, wanted, first: int, last: int, settings: VideoSettings):
    """Yield (frame number, RGB frame or None) for frames first..last with OpenCV,
    converting only wanted frames."""
    cap = cv2.VideoCapture(str(video))
    try:
        if first > 0:
            cap.set(cv2.CAP_PROP_POS_FRAMES, first)
        for n in range(first, last + 1):
            if not cap.grab():
                break
            if n in wanted:
                ok, frame = cap.retrieve()
                yield n, prepare_frame(frame, settings) if ok else None
            else:
                yield n, None
    finally:
        cap.release()


def decoder_backend() -> str:
    try:
        import av  # noqa: F401
        return "pyav"
    except ImportError:
        return "opencv"


def default_workers() -> int:
    return max(os.cpu_count() or 1, 1)


def analyse_video(video: Path, time: np.ndarray, gaze: np.ndarray, settings: VideoSettings,
                  progress: Optional[Callable[[float], None]] = None,
                  cancelled: Optional[Callable[[], bool]] = None,
                  backend: str = "auto", workers: int = 0,
                  frame_times: Optional[np.ndarray] = None) -> VideoResult:
    """Analyse ``video`` at each gaze sample. ``time`` is on the video clock (s),
    ``gaze`` is normalised (N, 2) with NaN for invalid samples, which are skipped.

    Every frame is decoded (compressed video needs it), but only frames with gaze samples
    are converted and analysed. The frame range is split into ``workers`` chunks (0: one per
    CPU core) decoded in parallel threads; FFmpeg and OpenCV release the interpreter lock
    while decoding, so the threads run concurrently. ``backend`` is "pyav" (fast), "opencv",
    or "auto" (PyAV when installed). The result does not depend on the number of workers.
    ``frame_times`` are the recorded frame start times on the same clock as ``time``, for
    devices whose frames are not evenly spaced (see :class:`FrameClock`).
    """
    fps, _ = video_info(video)
    clock = FrameClock(fps, frame_times)
    valid = np.isfinite(gaze).all(axis=1) & np.isfinite(time)
    idx = np.flatnonzero(valid)
    frame_of = clock.index(time[idx])
    keep = frame_of >= 0
    idx, frame_of = idx[keep], frame_of[keep]
    order = np.argsort(frame_of, kind="stable")
    idx, frame_of = idx[order], frame_of[order]
    if not len(idx):
        return VideoResult.empty()

    frames, starts = np.unique(frame_of, return_index=True)
    ends = np.r_[starts[1:], len(frame_of)]
    samples_of = {int(f): idx[a:b] for f, a, b in zip(frames, starts, ends)}
    first_frame, last_frame = int(frames[0]), int(frames[-1])
    total = last_frame - first_frame + 1

    workers = workers or default_workers()
    # Short videos are not worth splitting: each chunk pays for a seek and a keyframe decode.
    workers = int(max(1, min(workers, total // MIN_CHUNK_FRAMES)))
    bounds = np.linspace(first_frame, last_frame + 1, workers + 1).astype(int)
    backend = decoder_backend() if backend == "auto" else backend
    decode_threads = max(1, default_workers() // workers)
    pts_list = frame_pts(video) if backend == "pyav" else []

    done = [0]
    lock = threading.Lock()

    def run_chunk(a: int, b: int):
        source = (_frames_pyav(video, samples_of, a, b, settings.analysis_width, decode_threads, pts_list)
                  if backend == "pyav" else _frames_opencv(video, samples_of, a, b, settings))
        out, mask, counted = [], None, 0
        for n, small in source:
            if small is not None:
                h, w = small.shape[:2]
                if mask is None:
                    mask = field_mask((h, w), settings)
                sample = samples_of[n]
                out.append((sample,) + analyse_frame(small, gaze[sample] * [w, h], settings, mask))
            counted += 1
            if counted % 10 == 0:
                with lock:
                    done[0] += 10
                    if progress:
                        progress(min(done[0] / total, 1.0))
            if cancelled and cancelled():
                break
        return out

    chunks = [(int(a), int(b) - 1) for a, b in zip(bounds[:-1], bounds[1:]) if b > a]
    if len(chunks) == 1:
        parts = [run_chunk(*chunks[0])]
    else:
        with ThreadPoolExecutor(max_workers=len(chunks)) as pool:
            parts = list(pool.map(lambda c: run_chunk(*c), chunks))
    if progress:
        progress(1.0)

    rows = [r for part in parts for r in part]
    if not rows:
        return VideoResult.empty()
    sample = np.concatenate([r[0] for r in rows])
    return VideoResult(time[sample], np.vstack([r[1] for r in rows]), np.vstack([r[2] for r in rows]),
                       np.concatenate([r[3] for r in rows]), np.concatenate([r[4] for r in rows]),
                       np.concatenate([r[5] for r in rows]))
