"""Analysis parameters, saved per participant as JSON."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields
from pathlib import Path


@dataclass
class VideoSettings:
    """Geometry of the two-area estimate. Changing these requires re-running
    the video analysis; everything in :class:`Parameters` does not."""

    field_radius: float = 0.5            # scene circle radius, fraction of half the frame height
    fixation_ratio: float = 0.125        # fixation circle radius, fraction of the field radius
    background_excludes_fixation: bool = False
    analysis_width: int = 500            # frames are downscaled to this width


@dataclass
class Parameters:
    # Participant / Watson & Yellott
    age: float = 25.0
    reference_age: float = 28.58
    field: float = 160.0
    eyes: int = 2
    eye: str = "both"                    # pupil used: "left", "right" or "both"

    # Photometric calibration
    l_min: float = 0.02                  # cd/m², panel black point
    l_max: float = 200.0                 # cd/m², panel white point
    gain_r: float = 1.0
    gain_g: float = 1.0
    gain_b: float = 1.0
    gamma: float = 2.2
    fixation_weight: float = 0.65        # background weight is 1 - fixation_weight

    # Pupil signal
    pupil_scale: float = 2.0             # measured diameter multiplier
    align_mean: bool = True              # shift measured PD so its mean matches the expected PD
    timelag: float = 0.0                 # s, subtracted from luminance timestamps

    # Dynamics
    delay: float = 0.5                   # s, always applied
    dynamics: bool = False
    attack: float = 6.0                  # s, dilation
    release: float = 0.5                 # s, constriction

    # ΔPD
    cw_window: float = 0.2               # s, averaging window
    cw_smoothing: int = 1                # Savitzky-Golay half-window, in windows

    @property
    def gains(self) -> tuple[float, float, float]:
        return (self.gain_r, self.gain_g, self.gain_b)

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(asdict(self), indent=2))

    @classmethod
    def load(cls, path: str | Path) -> "Parameters":
        data = json.loads(Path(path).read_text())
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})
