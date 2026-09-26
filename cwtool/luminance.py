"""RGB to absolute luminance, following the per-channel extension of the
WCAG 2.1 relative luminance definition described in the Varjo paper."""

from __future__ import annotations

import numpy as np

# BT.709 / sRGB photopic weights for R, G, B.
SRGB_WEIGHTS = np.array([0.2126, 0.7152, 0.0722])


def srgb_to_linear(rgb8, gamma: float = 2.2) -> np.ndarray:
    """Decode 8-bit sRGB code values (0-255) to linear values in [0, 1]."""
    c = np.asarray(rgb8, dtype=float) / 255.0
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** gamma)


def relative_luminance(linear_rgb) -> np.ndarray:
    return np.asarray(linear_rgb, dtype=float) @ SRGB_WEIGHTS


def absolute_luminance(linear_rgb, l_min: float, l_max: float, gains=(1.0, 1.0, 1.0)) -> np.ndarray:
    """Map linear RGB (..., 3) to cd/m² between the panel black point
    ``l_min`` and white point ``l_max``.

    Each channel is interpolated black-to-full-colour, scaled by its gain and
    photopic weight; the sum is normalised by the mean gain so that gains act
    as a relative channel balance. With unit gains this reduces to a linear
    mapping of relative luminance onto [l_min, l_max].
    """
    lin = np.asarray(linear_rgb, dtype=float)
    gains = np.asarray(gains, dtype=float)
    per_channel = (l_max * gains * lin + l_min * (1 - lin)) * SRGB_WEIGHTS
    return per_channel.sum(axis=-1) / gains.mean()
