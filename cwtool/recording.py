"""Device-independent representation of one recording."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Optional

import numpy as np

LuminanceSource = Literal["display", "lux_sensor"]
PupilUnit = Literal["mm", "px"]


@dataclass(frozen=True)
class DeviceProfile:
    """What the analysis needs to know about a device, as opposed to a participant."""

    name: str
    pupil_unit: PupilUnit
    pupil_scale: Optional[float]       # reported value × scale = diameter in mm; None: must be fitted (px)
    luminance_source: LuminanceSource
    field_of_view: tuple[float, float]  # deg (horizontal, vertical) covered by the scene video
    circular_scene: bool = False       # scene video is a circle with black corners that must be masked out
    native_rate: float = 100.0         # Hz, nominal pupil sampling rate
    # Field the eye adapts to (deg, h × v), if larger than the scene video: e.g. the whole binocular
    # visual field for glasses-type trackers. Defaults to field_of_view (headsets).
    adapting_field: Optional[tuple[float, float]] = None
    # Reader written from the manufacturer's documentation and not yet checked on a real recording:
    # every result carries a warning saying so.
    experimental: bool = False

    @property
    def field_area(self) -> float:
        """Adapting field area in deg² (Watson & Yellott), treating the field as an ellipse."""
        w, h = self.adapting_field or self.field_of_view
        return math.pi / 4 * w * h


@dataclass
class Event:
    label: str
    start: float  # seconds, on the recording's relative clock
    end: float


@dataclass
class Recording:
    """One recording, as returned by every device reader.

    All arrays share the same length and are sampled on ``time``, which may be
    irregular. Invalid samples are NaN. Pupil values are as reported by the
    device, in ``profile.pupil_unit``; the pipeline converts them to mm.
    """

    name: str
    profile: DeviceProfile
    folder: Path
    time: np.ndarray            # s, relative to the scene video start
    epoch_start: float          # unix time (s) of time == 0
    pupil_left: np.ndarray      # device units
    pupil_right: np.ndarray     # device units
    gaze: np.ndarray            # (N, 2), normalised [0, 1], origin top-left of the scene video
    scene_video: Optional[Path] = None
    # Timestamp (s, relative clock) of each scene video frame, when the device records them
    # (frames may not be evenly spaced); None: frames are timed from the video's frame rate.
    scene_frame_times: Optional[np.ndarray] = None
    lux_time: Optional[np.ndarray] = None    # s, relative clock
    lux_values: Optional[np.ndarray] = None  # lux
    events: list[Event] = field(default_factory=list)

    def __post_init__(self) -> None:
        n = len(self.time)
        for name in ("pupil_left", "pupil_right", "gaze"):
            if len(getattr(self, name)) != n:
                raise ValueError(f"{name} has {len(getattr(self, name))} samples, time has {n}")

    @property
    def device(self) -> str:
        return self.profile.name

    @property
    def luminance_source(self) -> LuminanceSource:
        return self.profile.luminance_source

    @property
    def circular_scene(self) -> bool:
        return self.profile.circular_scene

    @property
    def measured_rate(self) -> float:
        """Sampling rate estimated from the timestamps (Hz)."""
        dt = np.diff(self.time)
        dt = dt[dt > 0]
        return float(1 / np.median(dt)) if len(dt) else float("nan")
