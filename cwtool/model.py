"""Pupil models: Watson & Yellott steady-state size and the dynamic filter."""

from __future__ import annotations

import numpy as np


def stanley_davies(flux) -> np.ndarray:
    """Stanley & Davies (1995) pupil diameter (mm) for corneal flux density (cd m⁻² deg²)."""
    x = (np.asarray(flux, dtype=float) / 846) ** 0.41
    return 7.75 - 5.75 * (x / (x + 2))


def eyes_attenuation(eyes: int) -> float:
    return {1: 0.1, 2: 1.0}.get(eyes, 0.0)


def watson_yellott(luminance, age: float, field: float, eyes: int = 2,
                   reference_age: float = 28.58) -> np.ndarray:
    """Watson & Yellott (2012) unified formula for light-adapted pupil size (mm).

    ``luminance`` in cd/m², ``field`` is the adapting field size passed through
    as the area term of the corneal flux density, ``age`` in years.
    """
    flux = np.asarray(luminance, dtype=float) * field * eyes_attenuation(eyes)
    d_sd = stanley_davies(flux)
    return d_sd + (age - reference_age) * (0.02132 - 0.009562 * d_sd)


def delay(signal, fs: float, seconds: float) -> np.ndarray:
    """Shift right by ``seconds``, padding with the first value."""
    x = np.asarray(signal, dtype=float)
    n = min(int(seconds * fs), len(x))
    if n <= 0:
        return x.copy()
    return np.concatenate([np.full(n, x[0]), x[:-n]])


def attack_release(signal, fs: float, attack: float, release: float) -> np.ndarray:
    """One-pole filter with time constant ``attack`` (s) while the input rises
    above the output and ``release`` (s) while it falls.

    Applied to the expected pupil diameter: a rising diameter is a dilation
    (slow), a falling diameter a constriction (fast).
    """
    x = np.asarray(signal, dtype=float)
    y = np.empty_like(x)
    if len(x) == 0:
        return y
    a_att = np.exp(-1 / (fs * attack))
    a_rel = np.exp(-1 / (fs * release))
    y[0] = x[0]
    for n in range(1, len(x)):
        a = a_att if x[n] > y[n - 1] else a_rel
        y[n] = a * y[n - 1] + (1 - a) * x[n]
    return y
