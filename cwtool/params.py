"""Analysis parameters, saved per participant as JSON."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields, replace
from pathlib import Path


PARAMS_VERSION = 3


@dataclass
class VideoSettings:
    """Geometry of the two-area estimate. Changing these requires re-running
    the video analysis; everything in :class:`Parameters` does not."""

    circular_mask: bool = False          # set from the recording: scene is a circle with black corners
    vertical_fov: float = 105.0          # deg spanned by the frame height; set from the recording's device
    field_radius: float = 0.8            # scene circle radius, fraction of half the frame height
    # Gaze circle radius in degrees of visual angle (converted with vertical_fov, assuming a linear
    # lens mapping). 16.35° and the weight 0.26 below are Eckert et al. (2022, sec. 2.6 and 3.2.1): a radius of
    # 14.8 % of the display diagonal (110.48° diagonal field of view), weights from a grid search (MAE 0.31 mm).
    # 1.x used 5.25°, 1/8 of the Varjo scene circle, with weight 0.65.
    fixation_radius_deg: float = 16.35
    background_excludes_fixation: bool = True   # background = rest of the scene, as in the Varjo manuscript and Eckert et al.
    analysis_width: int = 500            # frames are downscaled to this width

    def for_recording(self, rec) -> "VideoSettings":
        return replace(self, circular_mask=rec.circular_scene, vertical_fov=rec.profile.field_of_view[1])


@dataclass
class Parameters:
    """Every analysis setting: participant, display photometry, light response, lux sensor,
    camera, pupil signal, dynamics and ΔPD. See docs/reference/parameters.md for each field."""

    # Participant / Watson & Yellott
    age: float = 25.0
    eyes: int = 2
    eye: str = "both"                    # pupil used: "left", "right" or "both"

    # Display photometry (display devices): the headset's nominal values, e.g. from its datasheet.
    # Kept in their own file (DisplayPhotometry), not in participant files, since they belong to
    # the device and its settings. Real luminances: the adapting field area comes from the device.
    # Defaults: white 100 cd/m² (the headset's nominal; the measured Varjo values are 60–80, Zaman et al.
    # 2023) and black from the datasheet's 10000:1 contrast.
    l_min: float = 0.01                  # cd/m², panel black point
    l_max: float = 100.0                 # cd/m², panel white point
    gamma: float = 2.2

    # Participant light response, fitted on the calibration sequence. The sensitivity multiplies
    # the luminance entering Watson & Yellott, so it also absorbs any common error of the
    # display photometry (e.g. a datasheet luminance that does not match the headset's settings).
    sensitivity: float = 1.0
    gain_r: float = 1.0                  # channel weights for the pupil (relative balance)
    gain_g: float = 1.0
    gain_b: float = 1.0
    fixation_weight: float = 0.26        # background weight is 1 - fixation_weight (Eckert et al. 2022)

    # Lux sensor (glasses): average luminance = (gain · lux + offset) / lux_solid_angle.
    # 2.2 is the ratio of illuminance to average luminance for the TSL2591 in its printed housing (its
    # near-cosine response over the 55° half-angle field), not a solid angle, despite the 1.x name kept for
    # compatibility. Gain and offset default to the chip's own lux; 1.x used 1.706061 and 0.66935, a
    # correction for the field-of-view mismatch in one projector test, not a sensor calibration (open issue 23).
    lux_gain: float = 1.0
    lux_offset: float = 0.0
    lux_solid_angle: float = 2.2
    lux_use_video: bool = True           # distribute the sensor's average with the scene video (2021 eq. 5-8)
    # The video ratio Y_w / Y_frame is kept between 1/limit and limit (0 = no bound): in a nearly black frame it
    # divides by a small, noisy value, and with automatic exposure a black pixel means "below the captured
    # range", not no light (open issue 29).
    lux_ratio_limit: float = 10.0

    # Scene camera alone, when a Pupil recording has no lux log:
    #   "auto":  automatic exposure; the video gives only relative luminance, mapped onto Lmin-Lmax
    #   "fixed": the exposure was fixed (e.g. Neon manual exposure), so pixel values are proportional to
    #            luminance: L = white · relative luminance, with white the luminance that saturates the camera
    camera_exposure: str = "auto"
    camera_white: float = 1000.0         # cd/m² at full scale (code 255), for an exposure of camera_reference_ms
    camera_reference_ms: float = 0.0     # exposure time camera_white was calibrated at; 0 = the recording's
    camera_exposure_ms: float = 0.0      # the recording's exposure time; 0 = the same as camera_reference_ms

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
    # One switch for everything below: the attack/release filter, its constriction stages and the transient.
    # On by default with two stages, the combination that behaved best on the Varjo calibration recordings
    # (open issues 26 and 43); the calibration fit sets the time constants per participant.
    dynamics: bool = True
    attack: float = 6.0                  # s, dilation
    release: float = 0.5                 # s, constriction (per stage)
    # 1: constriction starts at full speed (one-pole); 2: it starts gradually (two poles, S-shaped),
    # so ``delay`` is the latency to the first movement rather than absorbing the slow start.
    constriction_stages: int = 2
    # Transient constriction after brightening ("pupillary escape"): the pupil constricts beyond its new
    # steady state and re-dilates within seconds. Applied with the dynamics when transient > 0.
    transient: float = 0.0               # mm, largest transient constriction (saturating in the step size)
    escape: float = 2.0                  # s, re-dilation time constant of the transient

    # ΔPD
    cw_window: float = 0.2               # s, averaging window
    cw_smoothing: int = 1                # Savitzky-Golay half-window, in windows

    version: int = PARAMS_VERSION

    @property
    def gains(self) -> tuple[float, float, float]:
        return (self.gain_r, self.gain_g, self.gain_b)

    @property
    def camera_full_scale(self) -> float:
        """cd/m² at full scale for the recording's exposure: saturation luminance scales inversely
        with exposure time."""
        if self.camera_reference_ms > 0 and self.camera_exposure_ms > 0:
            return self.camera_white * self.camera_reference_ms / self.camera_exposure_ms
        return self.camera_white

    def save(self, path: str | Path, participant_only: bool = False) -> None:
        """Write the parameters as JSON. ``participant_only`` leaves out the display photometry,
        which is saved separately (:class:`DisplayPhotometry`); exports keep everything used."""
        data = asdict(self)
        if participant_only:
            for key in DISPLAY_FIELDS:
                data.pop(key)
        Path(path).write_text(json.dumps(data, indent=2))

    @classmethod
    def load(cls, path: str | Path, profile=None, base: "Parameters | None" = None) -> "Parameters":
        return cls.from_dict(json.loads(Path(path).read_text()), profile, base)

    @classmethod
    def from_dict(cls, data: dict, profile=None, base: "Parameters | None" = None) -> "Parameters":
        """Build parameters, converting files written before version 2. Fields the file does not
        have (e.g. the display photometry, absent from participant files) come from ``base``.

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
        # Files written before the constriction stages existed were fitted with one.
        data.setdefault("constriction_stages", 1)
        data["version"] = PARAMS_VERSION   # versions 2 and 3 differ only in which fields a file holds
        known = {f.name for f in fields(cls)}
        values = asdict(base) if base is not None else {}
        values.update({k: v for k, v in data.items() if k in known})
        return cls(**values)


# Parameters that describe the display rather than the participant.
DISPLAY_FIELDS = ("l_min", "l_max", "gamma")


@dataclass
class DisplayPhotometry:
    """Nominal photometry of a display device, supplied by the user (e.g. from the datasheet) and
    saved on its own, since firmware or settings changes alter it independently of participants.
    Errors common to all participants are absorbed by each participant's fitted sensitivity."""

    device: str = ""
    l_min: float = 0.01      # cd/m², black
    l_max: float = 100.0     # cd/m², white
    gamma: float = 2.2
    source: str = ""         # where the values come from, e.g. "Varjo XR-4 datasheet"

    KIND = "cwtool display photometry"

    @classmethod
    def from_params(cls, p: Parameters, device: str = "", source: str = "") -> "DisplayPhotometry":
        return cls(device, p.l_min, p.l_max, p.gamma, source)

    def apply(self, p: Parameters) -> Parameters:
        return replace(p, l_min=self.l_min, l_max=self.l_max, gamma=self.gamma)

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps({"kind": self.KIND, **asdict(self)}, indent=2))

    @classmethod
    def load(cls, path: str | Path) -> "DisplayPhotometry":
        data = json.loads(Path(path).read_text())
        if data.get("kind") != cls.KIND:
            raise ValueError(f"{Path(path).name} is not a display photometry file")
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})


_LUX = ("lux_gain", "lux_offset", "lux_solid_angle", "lux_use_video", "lux_ratio_limit")
_CAMERA = ("camera_exposure", "camera_white", "camera_reference_ms", "camera_exposure_ms")
_PANEL = ("l_min", "l_max")


def unused_parameters(rec, params: Parameters) -> set[str]:
    """Names of the parameters and video settings that have no effect on ``rec`` with ``params``
    (e.g. the lux sensor calibration for a Varjo recording), for interfaces to hide. None if no
    recording is loaded: everything may matter."""
    if rec is None:
        return set()
    unused = set()
    if not rec.circular_scene:
        unused.add("field_radius")
    if rec.luminance_source != "lux_sensor":
        return unused | set(_LUX) | set(_CAMERA)
    if rec.lux_values is not None and len(rec.lux_values) >= 2:
        return unused | set(_PANEL) | set(_CAMERA)
    unused |= set(_LUX)
    if params.camera_exposure == "fixed":
        return unused | set(_PANEL)
    return unused | set(_CAMERA[1:])
