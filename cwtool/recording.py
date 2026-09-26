"""Device-independent representation of one recording."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Optional

import numpy as np

LuminanceSource = Literal["display", "lux_sensor"]


@dataclass
class Event:
    label: str
    start: float  # seconds, on the recording's relative clock
    end: float


@dataclass
class Recording:
    """One recording, as returned by every device reader.

    All arrays share the same length and are sampled on ``time``.
    Invalid samples are NaN.
    """

    name: str
    device: str
    folder: Path
    time: np.ndarray            # s, relative to the scene video start
    epoch_start: float          # unix time (s) of time == 0
    pupil_left: np.ndarray      # mm
    pupil_right: np.ndarray     # mm
    gaze: np.ndarray            # (N, 2), normalised [0, 1], origin top-left of the scene video
    sample_rate: float          # Hz, nominal
    luminance_source: LuminanceSource
    scene_video: Optional[Path] = None
    lux_time: Optional[np.ndarray] = None    # s, relative clock
    lux_values: Optional[np.ndarray] = None  # lux
    events: list[Event] = field(default_factory=list)

    def __post_init__(self) -> None:
        n = len(self.time)
        for name in ("pupil_left", "pupil_right", "gaze"):
            if len(getattr(self, name)) != n:
                raise ValueError(f"{name} has {len(getattr(self, name))} samples, time has {n}")
