"""The calibration's gaze check: where the dot was in the scene video against where the eye tracker says the gaze was.

The calibration presenter (and the validation task's calibration) ends with a dot moving through 9 places, 2 s each, on the
lead-in grey; its run file logs each place's onset (``phase`` = ``gaze``, :func:`cwtool.calibration.gaze_targets`). For each
place this module

1. finds the dot in the scene video: the frames of the place's window (after the eyes have had time to get there) are
   averaged, the average over all the places' windows is the background (the dot is elsewhere in each), and the dot is
   the strongest blob of the difference; its contrast against the difference's noise says how sure that is;
2. takes the gaze in the same window (the median of the tracker's gaze, normalised to the video);
3. gives the difference, dot minus gaze.

The median difference over the places found, as an angle, is the offset that would move the gaze onto the dots; its spread
and the residual after removing it say whether one offset is enough. Nothing is applied here: the operator decides (open
issue 61).

In VR the presenter logs each place's direction from the head (``target_az_deg``, ``target_el_deg``) and the dot is fixed to
the head, so (open issue 61, 23 November 2026):

- the offset is measured in the head's degrees, between those directions and the gaze's, without going through the
  video's assumed field of view (the gaze needs no dot found in the video);
- the dots found in the video, at known directions, measure the video's projection (``cwtool.projection``): a Quest
  capture over Link covers 79° × 50°, not centred on the head's straight ahead. It is reported, and saved with the
  recording on request (``cwtool.devices.quest.save_projection``), so the gaze is placed through it from then on.

This works when the dot is the only thing that changes between the places: a head-fixed dot in a headset's capture (Varjo,
Quest), or a monitor seen by glasses' scene camera with the head still. A moving head shifts the background and lowers
the dots' contrast; places whose dot is not clear are left out and said.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

from cwtool import calibration
from cwtool.projection import Projection, direction_to_angles, fit, of_profile
from cwtool.recording import Recording
from cwtool.video import FrameClock

SETTLE = 0.6            # s after a place's onset before its window starts: the saccade and the eyes' settling
END_MARGIN = 0.2        # s before the next place
FRAMES_PER_PLACE = 6    # frames averaged in a window
WIDTH = 320             # px, width the frames are scaled to
MIN_CONTRAST = 6.0      # the dot's peak against the difference's robust noise (MADs) below which it is not found
MIN_GAZE_SAMPLES = 20   # gaze samples a window needs
MIN_PLACES = 3          # places needed for an offset
NOISE_FLOOR = 1.0       # grey levels: the noise is never taken as smaller (a clean synthetic or static picture)
MIN_PROJECTION_DOTS = 5         # dots at known directions needed to measure the video's projection
MAX_PROJECTION_RESIDUAL = 0.01  # normalised widths: a projection that leaves the dots further off is not trusted
PROJECTION_NOTE = (2.0, 0.01)   # deg of field, normalised centre: a measured projection this far from the one in use is news


@dataclass
class Place:
    """One place of the gaze check."""
    index: int                         # 1-based, as the run file's label
    u: float                           # grid place (right, down)
    v: float
    start: float                       # s, recording time of the analysed window
    end: float
    dot: Optional[tuple]               # (x, y) normalised video coordinates of the dot found, None if not found
    contrast: float                    # the dot's peak in robust noise units
    gaze: Optional[tuple]              # (x, y) median gaze in the window, None without enough samples
    gaze_spread: float                 # normalised: median distance of the gaze samples from their median
    samples: int
    target_deg: Optional[tuple] = None  # picture angles (deg; right, down) of the place's logged direction (VR runs)
    gaze_deg: Optional[tuple] = None    # picture angles of the median gaze, through the video's projection

    @property
    def difference(self) -> Optional[tuple]:
        """Dot minus gaze (normalised), when both are known."""
        if self.dot is None or self.gaze is None:
            return None
        return (self.dot[0] - self.gaze[0], self.dot[1] - self.gaze[1])


@dataclass
class GazeCheck:
    """The gaze check's result."""
    places: list
    offset: Optional[tuple]            # (dx, dy) normalised, at the video's centre: the offset below there
    offset_deg: Optional[tuple]        # deg (right, down): the angle that moves the gaze onto the dots; None if too few
    spread_deg: float                  # median distance (deg) of the places' differences from the offset
    error_before_deg: float            # median distance (deg) between gaze and dot, as recorded
    error_after_deg: float             # the same with the offset added
    source: str                        # the run file
    notes: list = field(default_factory=list)
    applied_deg: Optional[tuple] = None   # the session's gaze offset already applied to the gaze compared
    reference: str = "dots"            # what the gaze is compared with: "dots" (found in the video) or "directions" (logged)
    projection: Optional[tuple] = None  # the video's projection measured from the dots (cx, cy, fx, fy), when it could be
    projection_residual: float = float("nan")   # normalised: the dots' median distance from the fitted projection
    projection_used: Optional[tuple] = None     # the projection the gaze was placed with

    @property
    def found(self) -> int:
        if self.reference == "directions":
            return sum(p.gaze is not None for p in self.places)
        return sum(p.difference is not None for p in self.places)


    def summary(self) -> str:
        applied = (f" (with the session's offset of {self.applied_deg[0]:+.1f}° right, {self.applied_deg[1]:+.1f}° down "
                   "applied)") if self.applied_deg else ""
        if self.offset_deg is None:
            return f"gaze check{applied}: {self.found} of {len(self.places)} places usable, too few for an offset"
        dx, dy = self.offset_deg
        against = "the dots' directions" if self.reference == "directions" else "the dots"
        text = (f"gaze check{applied}: {self.found} of {len(self.places)} places; gaze off {against} by "
                f"{self.error_before_deg:.1f}° (median); a further {dx:+.1f}° right, {dy:+.1f}° down would leave "
                f"{self.error_after_deg:.1f}° (places' spread {self.spread_deg:.1f}°)")
        if self.projection_differs():
            text += f"; the video's projection measured: {Projection.from_tuple(self.projection).describe()}"
        return text

    def projection_differs(self) -> bool:
        """Whether the projection measured from the dots differs from the one the gaze was placed with."""
        if self.projection is None:
            return False
        if self.projection_used is None:
            return True
        new, old = Projection.from_tuple(self.projection), Projection.from_tuple(self.projection_used)
        field = max(abs(a - b) for a, b in zip(new.field_of_view, old.field_of_view))
        return field > PROJECTION_NOTE[0] or max(abs(new.cx - old.cx), abs(new.cy - old.cy)) > PROJECTION_NOTE[1]

    def total_offset_deg(self) -> Optional[tuple]:
        """The session's offset that would put the gaze on the dots: the one applied plus the one found."""
        if self.offset_deg is None:
            return None
        a = self.applied_deg or (0.0, 0.0)
        return (a[0] + self.offset_deg[0], a[1] + self.offset_deg[1])

    def as_dict(self) -> dict:
        out = asdict(self)
        out["found"] = self.found
        out["summary"] = self.summary()
        return out


def _run_file(rec: Recording) -> Optional[Path]:
    folders = [rec.folder]
    if rec.scene_video is not None and Path(rec.scene_video).parent != Path(rec.folder):
        folders.append(Path(rec.scene_video).parent)
    for folder in folders:
        found = calibration.find_run_file(folder) if folder is not None else None
        if found is not None and calibration.gaze_targets(found):
            return found
    return None


def _window_frames(cap, clock: FrameClock, start: float, end: float, n_frames: int) -> Optional[np.ndarray]:
    """The mean of up to FRAMES_PER_PLACE frames between ``start`` and ``end`` (video clock), grey, scaled to WIDTH."""
    first, last = (int(i) for i in clock.index(np.array([start, end])))
    if first < 0 or last < 0 or last < first or first >= n_frames:
        return None
    wanted = set(np.linspace(first, min(last, n_frames - 1), FRAMES_PER_PLACE).round().astype(int))
    cap.set(cv2.CAP_PROP_POS_FRAMES, first)
    frames = []
    for i in range(first, min(last, n_frames - 1) + 1):
        ok = cap.grab()
        if not ok:
            break
        if i in wanted:
            ok, frame = cap.retrieve()
            if ok:
                h, w = frame.shape[:2]
                small = cv2.resize(frame, (WIDTH, max(1, round(h * WIDTH / w))), interpolation=cv2.INTER_AREA)
                frames.append(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY).astype(float))
    return np.mean(frames, axis=0) if frames else None


def _find_dot(diff: np.ndarray, radius_px: float) -> tuple[Optional[tuple], float]:
    """The strongest blob of ``diff`` (normalised x, y) and its peak in robust noise units."""
    k = max(3, int(round(radius_px)) * 2 + 1)
    blurred = cv2.GaussianBlur(diff, (k, k), 0)
    noise = max(1.4826 * float(np.median(np.abs(blurred - np.median(blurred)))), NOISE_FLOOR)
    base = float(np.median(blurred))
    y, x = np.unravel_index(int(np.argmax(blurred)), blurred.shape)
    contrast = float((blurred[y, x] - base) / noise)
    # the blob's weighted centre above half its peak (the peak itself sits anywhere on a flat top)
    above = (blurred > base + 0.5 * (blurred[y, x] - base)).astype(np.uint8)
    _, labels = cv2.connectedComponents(above)
    blob = labels == labels[y, x]
    weights = (blurred - base) * blob
    ys, xs = np.indices(blurred.shape)
    total = float(weights.sum())
    cx, cy = (float((weights * xs).sum() / total), float((weights * ys).sum() / total)) if total > 0 else (float(x), float(y))
    h, w = diff.shape
    return ((cx + 0.5) / w, (cy + 0.5) / h), contrast


def check(rec: Recording, run_file: Optional[Path] = None, dot_deg: float = 1.6) -> tuple[Optional[GazeCheck], str]:
    """The gaze check of ``rec`` from the run file in its folder (or its scene video's), and a message (why there is none
    when it is None). ``rec`` must already be aligned to its video (the run file's Unix times are placed by its
    ``epoch_start``). ``dot_deg`` is the dot's diameter, which sizes the blob looked for."""
    run_file = run_file or _run_file(rec)
    if run_file is None:
        return None, "no calibration run file with a gaze check next to the recording"
    if rec.scene_video is None:
        return None, "no scene video"
    if not np.isfinite(rec.epoch_start):
        return None, "the recording does not give its Unix start time"
    targets = calibration.gaze_targets(run_file)
    cap = cv2.VideoCapture(str(rec.scene_video))
    if not cap.isOpened():
        return None, f"cannot open {Path(rec.scene_video).name}"
    try:
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        n_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        clock = FrameClock(fps, rec.scene_frame_times)
        windows = []
        for k, t in enumerate(targets):
            start = t.onset_unix - rec.epoch_start + SETTLE
            end = t.onset_unix - rec.epoch_start + max(t.duration, SETTLE + 0.4) - END_MARGIN
            windows.append((k, t, start, end, _window_frames(cap, clock, start, end, n_frames)))
    finally:
        cap.release()
    means = [w[4] for w in windows if w[4] is not None]
    directions = all(t.direction is not None for t in targets)
    if len(means) < MIN_PLACES and not directions:
        return None, f"the video covers only {len(means)} of the gaze check's {len(targets)} places"
    background = np.median(np.stack(means), axis=0) if len(means) >= MIN_PLACES else None
    proj = of_profile(rec.profile)
    fov = proj.field_of_view
    radius_px = background.shape[1] * (dot_deg / 2) / fov[0] if background is not None else 0.0

    places, notes = [], []
    gaze = np.asarray(rec.gaze, dtype=float)
    time = np.asarray(rec.time, dtype=float)
    for k, t, start, end, mean in windows:
        dot, contrast = (None, 0.0)
        if mean is not None and background is not None:
            dot, contrast = _find_dot(np.abs(mean - background), radius_px)
            if contrast < MIN_CONTRAST:
                dot = None
        inside = (time >= start) & (time <= end) & np.isfinite(gaze).all(axis=1)
        g, spread, g_deg = None, float("nan"), None
        if inside.sum() >= MIN_GAZE_SAMPLES:
            g = tuple(float(v) for v in np.median(gaze[inside], axis=0))
            spread = float(np.median(np.hypot(*(gaze[inside] - g).T)))
            g_deg = tuple(float(v) for v in proj.to_angles(np.array(g)))
        target = tuple(float(v) for v in direction_to_angles(*t.direction)[0]) if t.direction is not None else None
        places.append(Place(k + 1, t.u, t.v, float(start), float(end), dot, contrast, g, spread, int(inside.sum()),
                            target, g_deg))

    lost = [p.index for p in places if p.dot is None]
    if lost:
        notes.append(f"The dot was not clear in the video at places {', '.join(map(str, lost))} (a moving head, or the "
                     "video does not show it there).")
    no_gaze = [p.index for p in places if p.gaze is None]
    if no_gaze:
        notes.append(f"Too little gaze at places {', '.join(map(str, no_gaze))}.")

    # The video's projection from the dots at known directions (VR): where the head's directions fall in the video.
    measured, residual = None, float("nan")
    with_dot = [(t.direction, p.dot) for t, p in zip(targets, places) if t.direction is not None and p.dot is not None]
    if len(with_dot) >= MIN_PROJECTION_DOTS:
        dirs = np.array([d for d, _ in with_dot])
        if len(np.unique(dirs[:, 0])) >= 2 and len(np.unique(dirs[:, 1])) >= 2:
            fitted, residual = fit(dirs, np.array([p for _, p in with_dot]))
            if fitted.fx > 0 and fitted.fy > 0 and residual <= MAX_PROJECTION_RESIDUAL:
                measured = fitted.as_tuple()
            else:
                notes.append(f"The dots do not fit one projection (median {residual:.3f} of the width off): the video's "
                             "projection was not measured.")

    # The offset is an angle (a tracker turned on the head, or in a headset, shifts the gaze by the same angle everywhere):
    # each place's difference in picture angles, their median, and the error left when the gaze is moved by it as the
    # session's offset would move it (:func:`shift_gaze`, an addition in picture angles). In VR the places' logged
    # directions are the reference, in the head's degrees; otherwise the dots found, through the video's projection.
    if directions:
        usable = [p for p in places if p.gaze is not None]
        reference = np.array([p.target_deg for p in usable]) if usable else np.zeros((0, 2))
    else:
        usable = [p for p in places if p.difference is not None]
        reference = proj.to_angles(np.array([p.dot for p in usable])) if usable else np.zeros((0, 2))
    kind = "directions" if directions else "dots"
    if len(usable) < MIN_PLACES:
        return GazeCheck(places, None, None, float("nan"), float("nan"), float("nan"), run_file.name, notes,
                         applied_deg=rec.gaze_offset, reference=kind, projection=measured,
                         projection_residual=residual, projection_used=proj.as_tuple()), f"only {len(usable)} places usable"
    seen = np.array([p.gaze_deg for p in usable])
    diffs_deg = reference - seen
    offset_deg = tuple(float(v) for v in np.median(diffs_deg, axis=0))
    before = float(np.median(np.hypot(*diffs_deg.T)))
    after = float(np.median(np.hypot(*(diffs_deg - offset_deg).T)))
    centre = np.array([[proj.cx, proj.cy]])
    offset = tuple(float(v) for v in (shift_gaze(centre, offset_deg, proj) - centre)[0])
    return GazeCheck(places, offset, offset_deg, after, before, after, run_file.name, notes,
                     applied_deg=rec.gaze_offset, reference=kind, projection=measured, projection_residual=residual,
                     projection_used=proj.as_tuple()), "checked"


# The operator's gaze offset, per recording (session): how a tracker sits on the head, or in a headset, changes between
# sessions, so the offset is saved next to the recording, as the trim is, and applied when it is read.
OFFSET_FILE = "cwtool_gaze_offset.json"


def load_offset(folder: Optional[Path]) -> Optional[tuple]:
    """The gaze offset (deg; right, down) saved with the recording in ``folder``, or None."""
    import json
    path = Path(folder) / OFFSET_FILE if folder is not None else None
    if path is None or not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        dx, dy = float(data["right_deg"]), float(data["down_deg"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return (dx, dy) if (dx, dy) != (0.0, 0.0) else None


def save_offset(folder: Path, offset_deg: Optional[tuple], source: str = "operator") -> Path:
    """Save the gaze offset (deg; right, down) with the recording; None or zero removes it."""
    import json
    from datetime import datetime
    path = Path(folder) / OFFSET_FILE
    if offset_deg is None or tuple(offset_deg) == (0.0, 0.0):
        path.unlink(missing_ok=True)
        return path
    path.write_text(json.dumps({"right_deg": round(float(offset_deg[0]), 3), "down_deg": round(float(offset_deg[1]), 3),
                                "source": source, "saved": datetime.now().isoformat(timespec="seconds")}, indent=2))
    return path


def shift_gaze(gaze: np.ndarray, offset_deg: tuple, projection) -> np.ndarray:
    """Gaze in normalised video coordinates moved by ``offset_deg`` (deg; right, down) in picture angles, through
    ``projection`` (a :class:`~cwtool.projection.Projection`, or a field of view centred), so the same offset is the same
    angle anywhere in the picture."""
    proj = projection if isinstance(projection, Projection) else Projection.from_fov(projection)
    gaze = np.asarray(gaze, dtype=float)
    out = proj.from_angles(proj.to_angles(gaze.reshape(-1, 2)) + np.asarray(offset_deg, dtype=float))
    return out.reshape(gaze.shape)


def apply_offset(rec: Recording, offset_deg: Optional[tuple] = None) -> Recording:
    """``rec`` with the gaze offset applied: ``offset_deg`` when given, else the one saved with it (none: unchanged)."""
    from dataclasses import replace
    offset = offset_deg if offset_deg is not None else load_offset(rec.folder)
    if offset is None or tuple(offset) == (0.0, 0.0):
        return rec
    dx, dy = offset
    return replace(rec, gaze=shift_gaze(rec.gaze, offset, of_profile(rec.profile)), gaze_offset=(float(dx), float(dy)),
                   notes=list(rec.notes) + [f"The gaze is moved by {dx:+.2f}° right, {dy:+.2f}° down (the session's gaze "
                                            f"offset, {OFFSET_FILE})."])
