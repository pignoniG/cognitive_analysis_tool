"""How directions map onto a scene video: a pinhole with its centre and focal length, in normalised video coordinates.

A point at tangents (X, Y) from the camera's straight ahead (right, down) is at

    x = cx + fx · X,    y = cy + fy · Y

in the video (0–1 from the top left). A field of view (h × v) centred in the picture is the special case
``fx = 1 / (2 tan(h / 2))``, ``cx = 0.5``, and so on: what every device but the Quest's capture assumes. The Quest's capture
over Link is a crop of one eye's view that is not centred on the head's straight ahead (open issue 61); the calibration's
gaze check measures it, since its dots are at known directions from the head.

Angles come in two forms. **Picture angles** (right, down) are ``atan(X)`` and ``atan(Y)``: an offset added to them moves the
gaze by the same angle anywhere in the picture, which is how the session's gaze offset is applied. **Directions** (azimuth
right, elevation up), as an eye tracker or the VR presenter gives them, are the same point as ``X = tan(az)``,
``Y = −tan(el) / cos(az)``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class Projection:
    cx: float
    cy: float
    fx: float       # normalised video widths per unit tangent
    fy: float       # normalised video heights per unit tangent

    @classmethod
    def from_fov(cls, fov: tuple) -> "Projection":
        """A pinhole of field ``fov`` (deg, h × v) centred in the picture."""
        return cls(0.5, 0.5, 1 / (2 * math.tan(math.radians(fov[0] / 2))), 1 / (2 * math.tan(math.radians(fov[1] / 2))))

    @classmethod
    def from_tuple(cls, values) -> "Projection":
        cx, cy, fx, fy = (float(v) for v in values)
        return cls(cx, cy, fx, fy)

    def as_tuple(self) -> tuple:
        return (self.cx, self.cy, self.fx, self.fy)

    @property
    def field_of_view(self) -> tuple:
        """The field (deg, h × v) the picture covers, from edge to edge."""
        h = math.degrees(math.atan(self.cx / self.fx) + math.atan((1 - self.cx) / self.fx))
        v = math.degrees(math.atan(self.cy / self.fy) + math.atan((1 - self.cy) / self.fy))
        return (h, v)

    def to_angles(self, xy) -> np.ndarray:
        """Picture angles (deg; right, down) of normalised video points (..., 2)."""
        xy = np.asarray(xy, dtype=float)
        return np.degrees(np.stack([np.arctan((xy[..., 0] - self.cx) / self.fx),
                                    np.arctan((xy[..., 1] - self.cy) / self.fy)], axis=-1))

    def from_angles(self, angles) -> np.ndarray:
        """Normalised video points of picture angles (deg; right, down)."""
        a = np.radians(np.asarray(angles, dtype=float))
        return np.stack([self.cx + self.fx * np.tan(a[..., 0]), self.cy + self.fy * np.tan(a[..., 1])], axis=-1)

    def from_direction(self, azimuth, elevation) -> np.ndarray:
        """Normalised video points (N, 2) of directions (deg; azimuth right, elevation up)."""
        return self.from_angles(direction_to_angles(azimuth, elevation))

    def describe(self) -> str:
        h, v = self.field_of_view
        return f"{h:.0f}° × {v:.0f}°, straight ahead at ({self.cx:.3f}, {self.cy:.3f}) of the picture"


def direction_to_angles(azimuth, elevation) -> np.ndarray:
    """Picture angles (deg; right, down; N × 2) of directions (deg; azimuth right, elevation up)."""
    az, el = np.radians(np.asarray(azimuth, dtype=float)), np.radians(np.asarray(elevation, dtype=float))
    return np.degrees(np.column_stack([np.atleast_1d(az), np.arctan(-np.tan(np.atleast_1d(el)) / np.cos(np.atleast_1d(az)))]))


def of_profile(profile) -> Projection:
    """The projection of a device profile: its own when it has one, else its field of view centred."""
    own = getattr(profile, "projection", None)
    return Projection.from_tuple(own) if own is not None else Projection.from_fov(profile.field_of_view)


def fit(directions, points) -> tuple[Projection, float]:
    """The projection that puts ``directions`` (N × 2 deg; azimuth right, elevation up) at the video ``points`` (N × 2,
    normalised), by least squares on each axis, and its residual (median distance, normalised widths)."""
    d = direction_to_angles(np.asarray(directions)[:, 0], np.asarray(directions)[:, 1])
    tx, ty = np.tan(np.radians(d[:, 0])), np.tan(np.radians(d[:, 1]))
    p = np.asarray(points, dtype=float)
    fx, cx = np.polyfit(tx, p[:, 0], 1)
    fy, cy = np.polyfit(ty, p[:, 1], 1)
    proj = Projection(float(cx), float(cy), float(fx), float(fy))
    residual = float(np.median(np.hypot(*(proj.from_angles(d) - p).T)))
    return proj, residual
