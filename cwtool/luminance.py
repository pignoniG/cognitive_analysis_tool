"""RGB to absolute luminance, following the per-channel extension of the
WCAG 2.1 relative luminance definition described in the Varjo paper.

Code values are decoded with a plain power law, C_lin = C'^γ. At the default
γ = 2.2 this is the standard approximation of the sRGB curve (within 1 % of full
scale), and unlike the piecewise sRGB formula it stays continuous for any γ,
which is adjustable because headset tone mapping is undocumented."""

from __future__ import annotations

import numpy as np

# BT.709 / sRGB photopic weights for R, G, B.
SRGB_WEIGHTS = np.array([0.2126, 0.7152, 0.0722])


def to_linear(rgb8, gamma: float = 2.2) -> np.ndarray:
    """Decode 8-bit code values (0-255) to linear values in [0, 1]: (C / 255)^γ."""
    return (np.asarray(rgb8, dtype=float) / 255.0) ** gamma


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
