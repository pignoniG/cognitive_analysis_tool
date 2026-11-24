"""The weights that turn the AS7341's eight bands (basic counts) into an estimate of photopic illuminance (lux),
from the datasheet's typical curves (open issue 58). Prints the weights for ``cwtool/spectral.py``.

    python tools/as7341_weights.py

Model of the typical sensor:
- each band's spectral responsivity has the shape of Figure 19 of the datasheet (DS000504 v3-00), scaled so that the
  datasheet's warm white test LED (Figure 16, 107.67 µW/cm²) gives the typical counts of Figures 8-15 (at 64x and
  27.8 ms, so basic counts = counts / (64 × 27.8));
- photopic illuminance is 683 lm/W × ∫ V(λ) E(λ) dλ (CIE 018:2019), from 380 to 780 nm.

The weights are fitted by least squares to a fixed set of spectra: blackbodies (incandescent to daylight), phosphor
white LEDs, mixes of display primaries, single coloured LEDs and three-band fluorescents, each error relative to the
spectrum's illuminance (floored at 5 % of that of a flat spectrum of the same power, so that a deep red or violet LED
does not dominate). The clear and NIR channels are not used: the clear channel helps only a sensor whose own curves
were measured, and both see an eye tracker's infrared illuminators.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

DATA = Path(__file__).resolve().parent.parent / "docs" / "hardware" / "data"
BANDS = ("F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8")
TYPICAL_COUNTS = (55, 110, 210, 390, 590, 840, 1350, 1070)   # DS000504 Figures 8-15: warm white, 64x, 27.8 ms
TEST_IRRADIANCE = 107.67                                     # µW/cm² of the warm white test LED
TEST_GAIN, TEST_MS = 64.0, 27.8
KM = 683.0                                                   # lm/W
WAVELENGTHS = np.arange(380.0, 781.0)                        # nm


def _table(name: str) -> tuple[list[str], np.ndarray]:
    lines = [ln for ln in (DATA / name).read_text().splitlines() if ln and not ln.startswith("#")]
    header = [h.strip() for h in lines[0].split(",")]
    rows = np.array([[float(v) for v in ln.split(",")] for ln in lines[1:]])
    return header, rows


def _column(name: str, column: str) -> np.ndarray:
    header, rows = _table(name)
    return np.interp(WAVELENGTHS, rows[:, 0], rows[:, header.index(column)], left=0.0, right=0.0)


def responsivities() -> np.ndarray:
    """(8, wavelengths): basic counts per µW/cm² per nm of each band, for the typical sensor."""
    led = _column("as7341_test_leds.csv", "warm white 2700 K")
    led = led / led.sum() * TEST_IRRADIANCE                  # µW/cm² per nm (1 nm steps)
    out = []
    for band, counts in zip(BANDS, TYPICAL_COUNTS):
        shape = np.clip(_column("as7341_responsivity.csv", band), 0.0, None)
        out.append(shape * (counts / (TEST_GAIN * TEST_MS)) / float(shape @ led))
    return np.array(out)


def photopic() -> np.ndarray:
    """lux per µW/cm² per nm: 683 lm/W × V(λ), with 1 µW/cm² = 0.01 W/m²."""
    return KM * 0.01 * _column("cie_v_lambda.csv", "V")


def _gauss(centre: float, fwhm: float) -> np.ndarray:
    return np.exp(-0.5 * ((WAVELENGTHS - centre) / (fwhm / 2.3548)) ** 2)


def _planck(kelvin: float) -> np.ndarray:
    m = WAVELENGTHS * 1e-9
    return 1.0 / (m ** 5 * np.expm1(1.4388e-2 / (m * kelvin)))


def spectra() -> np.ndarray:
    """The fitting set, each normalised to its peak (the fit is scale-free)."""
    out = [_planck(t) for t in np.arange(2000.0, 10001.0, 250.0)]
    for blue in (445.0, 452.0, 460.0):
        for phosphor in (550.0, 570.0, 590.0, 610.0):
            for share in (0.3, 0.6, 1.0):
                out.append(share * _gauss(blue, 20.0) + _gauss(phosphor, 120.0))
    primaries = [(_gauss(450, 20), _gauss(530, 40), _gauss(615, 30)),     # LCD
                 (_gauss(460, 25), _gauss(530, 30), _gauss(625, 28)),     # OLED
                 (_gauss(455, 20), _gauss(540, 45), _gauss(631, 8))]      # LCD with a narrow red phosphor
    levels = (0.0, 0.25, 0.5, 1.0)
    for r_, g_, b_ in primaries:
        for wr in levels:
            for wg in levels:
                for wb in levels:
                    if wr or wg or wb:
                        out.append(wr * r_ + wg * g_ + wb * b_)
    for centre in np.arange(430.0, 671.0, 10.0):
        for fwhm in (20.0, 30.0):
            out.append(_gauss(centre, fwhm))
    for red in (0.6, 1.0, 1.5):
        out.append(_gauss(436, 4) * 0.6 + _gauss(546, 6) + _gauss(611, 8) * red + 0.05 * _planck(4000) / _planck(4000).max())
    return np.array([s / s.max() for s in out])


def fit(responsivity: np.ndarray | None = None) -> np.ndarray:
    """lux per basic count of each band."""
    r = responsivities() if responsivity is None else responsivity
    v = photopic()
    s = spectra()
    counts = s @ r.T                                          # basic counts per unit of each spectrum
    lux = s @ v
    floor = np.maximum(lux, 0.05 * s.sum(axis=1) * v.mean())
    a = counts / floor[:, None]
    scale = np.linalg.norm(a, axis=0)
    w, *_ = np.linalg.lstsq(a / scale, lux / floor, rcond=None)
    return w / scale


def errors(weights: np.ndarray) -> np.ndarray:
    """Relative error of the estimate on the fitting set, as fitted (floored as in the fit)."""
    r, v, s = responsivities(), photopic(), spectra()
    lux = s @ v
    floor = np.maximum(lux, 0.05 * s.sum(axis=1) * v.mean())
    return (s @ r.T @ weights - lux) / floor


if __name__ == "__main__":
    weights = fit()
    e = errors(weights)
    print("WEIGHTS = (" + ", ".join(f"{w:.6g}" for w in weights) + ")   # lux per basic count, F1-F8")
    print(f"on the fitting set: RMS {np.sqrt(np.mean(e ** 2)):.1%}, 95th percentile {np.quantile(abs(e), 0.95):.1%}, "
          f"max {abs(e).max():.1%}")
    warm = _column("as7341_test_leds.csv", "warm white 2700 K")
    warm = warm / warm.sum() * TEST_IRRADIANCE
    print(f"the datasheet's warm white test LED: {float(warm @ photopic()):.1f} lx, "
          f"estimated {float(warm @ responsivities().T @ weights):.1f} lx")
