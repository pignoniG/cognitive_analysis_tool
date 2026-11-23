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
    # Peak luminance the manufacturer claims for the display (cd/m²); the display's white point cannot be
    # much above it, but can be below, since brightness is adjustable.
    max_luminance: Optional[float] = None
    # The iris diameter (mm) the reader's millimetre values assume, when the device reports the pupil as a ratio to an
    # iris it does not measure (the Varjo's pupil is that ratio times a fixed 12 mm): a participant's measured iris
    # (``Parameters.iris_diameter``) then rescales the pupil. None: the device measures the pupil itself.
    assumed_iris: Optional[float] = None
    # Where directions fall in the scene video when it is not the field of view centred (``cwtool.projection``: centre and
    # focal length, normalised; a Quest capture, open issue 61). None: field_of_view, centred.
    projection: Optional[tuple] = None

    @property
    def field_area(self) -> float:
        """Adapting field area in deg² (Watson & Yellott), treating the field as an ellipse."""
        w, h = self.adapting_field or self.field_of_view
        return math.pi / 4 * w * h


@dataclass
class Event:
    """A labelled time span of the recording (an experiment phase), in seconds on the relative clock."""
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
    epoch_start: float          # unix time (s) of time == 0; NaN if the recording does not tell
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
    notes: list[str] = field(default_factory=list)   # reader's warnings, shown with every result
    # Samples whose pupil the tracker reports at its ceiling (True): the true size is at least that large, so the value is a
    # lower bound. None when the device has no such limit or the file does not say.
    censored_left: Optional[np.ndarray] = None
    censored_right: Optional[np.ndarray] = None
    # How the presenter's log was aligned to the video (:class:`cwtool.alignment.LogAlignment` as a dictionary), when it was
    log_alignment: Optional[dict] = None
    # Where the scene video and the luminance come from, in a few words for the operator (shown prominently by the app):
    # e.g. "glasses: scene camera and lux sensor" or "XR: Meta Quest capture (com.oculus.vrshell)". Empty: the device's
    # only route, nothing to point out.
    route: str = ""
    # True when the scene video runs on another clock than the pupil and the events (a Neon inside a Quest: the capture is on
    # the headset's clock, the pupil on the phone's): aligning then moves the pupil, events and sensors onto the video, and
    # the alignment may also come from the pupil's response to the picture (:mod:`cwtool.alignment`).
    separate_video_clock: bool = False
    # The calibration's gaze check (:class:`cwtool.gazecheck.GazeCheck` as a dictionary), when the run file had one.
    gaze_check: Optional[dict] = None
    # The operator's gaze offset applied to ``gaze`` (deg; right, down), saved with the recording (:mod:`cwtool.gazecheck`).
    gaze_offset: Optional[tuple] = None

    def __post_init__(self) -> None:
        n = len(self.time)
        for name in ("pupil_left", "pupil_right", "gaze"):
            if len(getattr(self, name)) != n:
                raise ValueError(f"{name} has {len(getattr(self, name))} samples, time has {n}")

    @property
    def device(self) -> str:
        """Name of the device that made the recording."""
        return self.profile.name

    @property
    def luminance_source(self) -> LuminanceSource:
        """Where the luminance comes from for this device: the display, a lux sensor or the camera."""
        return self.profile.luminance_source

    @property
    def circular_scene(self) -> bool:
        """True if the scene camera's image is a circle (fisheye), so the corners are not scene."""
        return self.profile.circular_scene

    @property
    def measured_rate(self) -> float:
        """Sampling rate estimated from the timestamps (Hz)."""
        dt = np.diff(self.time)
        dt = dt[dt > 0]
        return float(1 / np.median(dt)) if len(dt) else float("nan")
