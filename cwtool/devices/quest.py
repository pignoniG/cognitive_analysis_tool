"""Meta Quest video captures, as the scene video of an eye tracker worn inside the headset (a Pupil Labs Neon in its Quest 3
frame, open issue 61).

The Neon's own scene camera does not see the headset's displays; what the eye sees is in the Quest's video capture. The
Quest names a capture after the app that recorded it and the local time the capture started, to the second:

    com.oculus.vrshell-20261116-113807-0.mp4             (the headset's own view, e.g. passthrough)
    com.meta.pclinkservice.server-20261116-112913-0.mp4  (a PC app over Link)

Checked on two recordings of 16 November 2026, whose names fit the Neon's times: the start, in the headset's local time,
truncated to the second. The capture holds one eye's view (1920 × 1080, H.264) at a variable frame rate of about 30 fps
(frames 28 to 42 ms apart), so frames are timed from their presentation timestamps, never from a nominal rate.

The capture's clock is the headset's and is known only to a second from the name; :mod:`cwtool.alignment` refines it from
the presenter's log or from the pupil's response to the picture.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import numpy as np

NAME_PATTERN = re.compile(r"^(?P<app>com\.(?:oculus|meta)\.[\w.]+)-(?P<date>\d{8})-(?P<time>\d{6})-\d+\.mp4$", re.IGNORECASE)
# Field of the capture (deg, h × v). The Quest 3 shows about 110° × 96° per eye (Meta); the capture is a 16:9 crop of one
# eye's view whose exact field Meta does not give: with the eye's horizontal field kept, a 16:9 crop of the same focal length
# spans about 78° vertically. Nominal, used to place the gaze and size its circle (open issue 61).
CAPTURE_FOV = (110.0, 78.0)
HEADSET_FOV = (110.0, 96.0)       # the field the eye adapts to: the headset's, as for the Varjo's own field of view
NEON_XR_FRAMES = ("quest",)       # words in the Neon's frame name (info.json "frame_name") that mean a headset frame
SEARCH_BEFORE = 600.0             # s: a capture may start this long before the eye tracker's recording


def is_capture(path: Path) -> bool:
    """True if ``path`` is named like a Quest video capture."""
    return bool(NAME_PATTERN.match(Path(path).name)) and not Path(path).name.startswith(".")


def capture_start(path: Path, utc_offset: Optional[float]) -> Optional[float]:
    """Unix time (s) of the capture's start from its name, read in the zone ``utc_offset`` (s east of UTC), or in the
    analysing computer's zone when it is None; None if the name is not a capture's. Exact to a second at best."""
    m = NAME_PATTERN.match(Path(path).name)
    if not m:
        return None
    try:
        local = datetime.strptime(m["date"] + m["time"], "%Y%m%d%H%M%S")
    except ValueError:
        return None
    if utc_offset is None:
        return local.timestamp()
    return local.replace(tzinfo=timezone(timedelta(seconds=utc_offset))).timestamp()


def app_of(path: Path) -> str:
    """The app that made the capture (``com.oculus.vrshell``, ``com.meta.pclinkservice.server``...), or ""."""
    m = NAME_PATTERN.match(Path(path).name)
    return m["app"] if m else ""


def frame_times(video: Path) -> np.ndarray:
    """Presentation time (s) of every frame, from the first, in display order."""
    import av

    with av.open(str(video)) as container:
        stream = container.streams.video[0]
        base = float(stream.time_base)
        pts = sorted(p.pts for p in container.demux(stream) if p.pts is not None)
    t = np.asarray(pts, dtype=float) * base
    return t - t[0] if len(t) else t


def find_capture(folders, start: float, end: float, utc_offset: Optional[float]) -> Optional[Path]:
    """The capture in ``folders`` that overlaps the span ``start``–``end`` (Unix s) the most, or None. Captures that start
    more than SEARCH_BEFORE s before ``start`` or after ``end`` are not considered; the overlap uses each one's duration."""
    best, best_overlap = None, 0.0
    seen = set()
    for folder in folders:
        folder = Path(folder)
        if not folder.is_dir():
            continue
        for path in sorted(folder.iterdir()):
            if path in seen or not path.is_file() or not is_capture(path):
                continue
            seen.add(path)
            t0 = capture_start(path, utc_offset)
            if t0 is None or t0 < start - SEARCH_BEFORE or t0 > end:
                continue
            try:
                duration = float(frame_times(path)[-1])
            except Exception:      # an unreadable file is not the capture
                continue
            overlap = min(end, t0 + duration) - max(start, t0)
            if overlap > best_overlap:
                best, best_overlap = path, overlap
    return best


def gaze_to_capture(azimuth: np.ndarray, elevation: np.ndarray, fov=CAPTURE_FOV) -> np.ndarray:
    """Gaze directions (deg; azimuth right, elevation up) as normalised capture coordinates (0–1, origin top left), for a
    pinhole view of field ``fov`` looking along the tracker's straight ahead. The rotation between the tracker's frame and
    the headset's view is not known: the operator's gaze offset corrects what it leaves (open issue 61)."""
    az, el = np.radians(np.asarray(azimuth, dtype=float)), np.radians(np.asarray(elevation, dtype=float))
    half_w, half_h = np.tan(np.radians(fov[0] / 2)), np.tan(np.radians(fov[1] / 2))
    x = 0.5 + np.tan(az) / (2 * half_w)
    y = 0.5 - np.tan(el) / np.cos(az) / (2 * half_h)
    return np.column_stack([x, y])
