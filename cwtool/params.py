"""Analysis parameters, saved per participant as JSON."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields, replace
from pathlib import Path


PARAMS_VERSION = 2


@dataclass
class VideoSettings:
    """Geometry of the two-area estimate. Changing these requires re-running
    the video analysis; everything in :class:`Parameters` does not."""

    circular_mask: bool = False          # set from the recording: scene is a circle with black corners
    vertical_fov: float = 105.0          # deg spanned by the frame height; set from the recording's device
    field_radius: float = 0.8            # scene circle radius, fraction of half the frame height
    # Gaze circle radius in degrees of visual angle (converted with vertical_fov, assuming a linear
    # lens mapping). 5.25° equals the earlier default of 1/8 of the scene circle on the Varjo XR-4.
    fixation_radius_deg: float = 5.25
    background_excludes_fixation: bool = True   # background = rest of the scene, as in the paper and Eckert et al.
    analysis_width: int = 500            # frames are downscaled to this width

    def for_recording(self, rec) -> "VideoSettings":
        return replace(self, circular_mask=rec.circular_scene, vertical_fov=rec.profile.field_of_view[1])


@dataclass
class Parameters:
    # Participant / Watson & Yellott
    age: float = 25.0
    reference_age: float = 28.58
    eyes: int = 2
    eye: str = "both"                    # pupil used: "left", "right" or "both"

    # Photometric calibration
    # Real luminances: the adapting field area comes from the device's field of view.
    # Default l_max is the mean of the Varjo pilot calibrations (4250 cd/m² at field 160),
    # converted to the XR-4 field area.
    l_min: float = 0.02                  # cd/m², panel black point
    l_max: float = 70.0                  # cd/m², panel white point
    gain_r: float = 1.0
    gain_g: float = 1.0
    gain_b: float = 1.0
    gamma: float = 2.2
    fixation_weight: float = 0.65        # background weight is 1 - fixation_weight

    # Sampling
    analysis_rate: float = 100.0         # Hz, uniform analysis grid; 0 = device's native rate
    max_gap: float = 0.5                 # s, longer gaps (not blinks) are left out of ΔPD
    max_pupil_speed: float = 10.0        # mm/s, faster changes are artefacts (blinks); 0 disables
    artefact_padding: float = 0.05       # s removed around each artefact

    # Pupil signal
    pupil_correction: float = 1.0        # participant multiplier on the device's pupil scale
    # How the measured PD is offset onto the expected PD:
    #   "recording": median difference over the whole recording (1.x behaviour, ΔPD centred on zero)
    #   "baseline":  median difference over the events named in baseline_events
    #   "fixed":     pupil_offset, e.g. fitted on the participant's calibration sequence
    #   "none":      no offset
    alignment: str = "recording"
    baseline_events: str = "Riposo, Rest, Baseline"
    pupil_offset: float = 0.0            # mm, used by alignment "fixed"
    timelag: float = 0.0                 # s, subtracted from luminance timestamps

    # Dynamics
    delay: float = 0.5                   # s, always applied
    dynamics: bool = False
    attack: float = 6.0                  # s, dilation
    release: float = 0.5                 # s, constriction

    # ΔPD
    cw_window: float = 0.2               # s, averaging window
    cw_smoothing: int = 1                # Savitzky-Golay half-window, in windows

    version: int = PARAMS_VERSION

    @property
    def gains(self) -> tuple[float, float, float]:
        return (self.gain_r, self.gain_g, self.gain_b)

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(asdict(self), indent=2))

    @classmethod
    def load(cls, path: str | Path, profile=None) -> "Parameters":
        return cls.from_dict(json.loads(Path(path).read_text()), profile)

    @classmethod
    def from_dict(cls, data: dict, profile=None) -> "Parameters":
        """Build parameters, converting files written before version 2.

        Version 1 files carry ``field`` (used directly as the flux-density area) and an
        absolute ``pupil_scale``. The expected pupil depends only on luminance × field, so
        l_min/l_max are rescaled to the device's field area, which gives identical results;
        ``pupil_scale`` becomes a correction relative to the device's scale. ``profile`` is
        the recording's DeviceProfile (default: Varjo, the only device with version 1 files).
        """
        data = dict(data)
        if "align_mean" in data:  # replaced by alignment
            data.setdefault("alignment", "recording" if data.pop("align_mean") else "none")
        if data.get("version", 1) < 2:
            if profile is None:
                from cwtool.devices.varjo import PROFILE as profile
            factor = float(data.pop("field", 160.0)) / profile.field_area
            for key in ("l_min", "l_max"):
                if key in data:
                    data[key] = data[key] * factor
            if "pupil_scale" in data and profile.pupil_scale:
                data["pupil_correction"] = data.pop("pupil_scale") / profile.pupil_scale
            data["version"] = PARAMS_VERSION
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})
