"""Pupil models: Watson & Yellott steady-state size and the dynamic filter."""

from __future__ import annotations

import numpy as np
from scipy.signal import lfilter


def stanley_davies(flux) -> np.ndarray:
    """Stanley & Davies (1995) pupil diameter (mm) for corneal flux density (cd m⁻² deg²)."""
    x = (np.asarray(flux, dtype=float) / 846) ** 0.41
    return 7.75 - 5.75 * (x / (x + 2))


def eyes_attenuation(eyes: int) -> float:
    """Watson & Yellott's monocular effect: flux is divided by 10 with one eye viewing."""
    try:
        return {1: 0.1, 2: 1.0}[int(eyes)]
    except (KeyError, TypeError, ValueError):
        raise ValueError(f"eyes must be 1 or 2, not {eyes!r}") from None


# Mean age of the observers behind the Stanley & Davies formula: a constant of Watson & Yellott's
# age correction, not a participant setting.
REFERENCE_AGE = 28.58


def watson_yellott(luminance, age: float, field: float, eyes: int = 2,
                   reference_age: float = REFERENCE_AGE) -> np.ndarray:
    """Watson & Yellott (2012) unified formula for light-adapted pupil size (mm).

    ``luminance`` in cd/m², ``field`` the adapting field area in deg² (the area term of the
    corneal flux density, luminance × area), ``age`` in years, ``eyes`` the number of eyes viewing.
    """
    flux = np.asarray(luminance, dtype=float) * field * eyes_attenuation(eyes)
    d_sd = stanley_davies(flux)
    return d_sd + (age - reference_age) * (0.02132 - 0.009562 * d_sd)


def delay(signal, fs: float, seconds: float) -> np.ndarray:
    """Shift right by ``seconds``, padding with the first value. A delay between samples is interpolated
    linearly, so the result changes smoothly with ``seconds`` (as the calibration fit needs)."""
    x = np.asarray(signal, dtype=float)
    d = max(float(seconds) * fs, 0.0)
    if len(x) == 0 or d == 0:
        return x.copy()
    k = int(np.floor(d + 1e-9))          # whole samples, robust to 0.29 · 100 = 28.999…
    f = d - k if d - k > 1e-9 else 0.0

    def shifted(n: int) -> np.ndarray:
        n = min(n, len(x))
        return np.concatenate([np.full(n, x[0]), x[:len(x) - n]])

    out = shifted(k)
    return out if f == 0.0 else (1 - f) * out + f * shifted(k + 1)


def attack_release(signal, fs: float, attack: float, release: float, stages: int = 1) -> np.ndarray:
    """One-pole filter with time constant ``attack`` (s) while the input rises
    above the output and ``release`` (s) while it falls.

    Applied to the expected pupil diameter: a rising diameter is a dilation
    (slow), a falling diameter a constriction (fast). With ``stages`` = 2 a second
    stage with time constant ``release`` acts during constriction only (it follows
    the first stage directly while that rises), so a constriction starts gradually
    (S-shaped) instead of at full speed, and dilation is unchanged.
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
    for _ in range(stages - 1):
        x, y = y, np.empty_like(y)
        y[0] = x[0]
        for n in range(1, len(x)):
            y[n] = x[n] if x[n] >= y[n - 1] else a_rel * y[n - 1] + (1 - a_rel) * x[n]
    return y


# Half-saturation of the transient, in log10 units of luminance increase. On the seven Varjo calibration
# recordings (September 2026) the re-dilation after a brightening step grew from 0.25 mm for a 0.1 log
# unit step to 0.52 mm for a 1 log unit step; a fitted half-saturation varied between participants
# without improving the fit, so it is fixed.
TRANSIENT_HALF = 0.2


def lowpass(signal, fs: float, tau: float) -> np.ndarray:
    """One-pole low-pass with time constant ``tau`` (s), starting from the first value."""
    x = np.asarray(signal, dtype=float)
    if len(x) == 0:
        return x.copy()
    a = np.exp(-1 / (fs * tau))
    return lfilter([1 - a], [1, -a], x, zi=[a * x[0]])[0]


def escape_transient(luminance, fs: float, escape: float, half: float = TRANSIENT_HALF) -> np.ndarray:
    """Share (0–1) of the maximum transient constriction ("pupillary escape").

    After a brightening step the pupil constricts beyond its new steady state and re-dilates towards
    it within seconds. The drive is the increase of log luminance over its recent level, a low-pass
    with time constant ``escape``: it jumps at a brightening step and decays with ``escape``. Only
    increases count (darkening gives no transient), and it saturates as ``h / (h + half)``.
    """
    log_l = np.log10(np.maximum(np.asarray(luminance, dtype=float), 1e-4))
    if len(log_l) == 0:
        return log_l
    h = np.clip(log_l - lowpass(log_l, fs, escape), 0, None)
    return h / (h + half)
