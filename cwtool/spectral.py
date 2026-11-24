"""Photopic illuminance (lux) estimated from the AS7341 spectral sensor's eight bands, for recordings without the
TSL2591's lux log (open issue 58).

The estimate is a weighted sum of the bands F1-F8 in basic counts (the logger's ``as7341.csv``):

    lux ≈ Σ wᵢ · Fᵢ

with weights fitted to the datasheet's typical responsivity curves and the CIE photopic curve V(λ)
(``tools/as7341_weights.py``, from ``docs/hardware/data``). The clear and NIR channels are not used: an eye tracker's
infrared illuminators reach them, and the clear channel only helps a sensor whose own curves were measured.

It is the typical sensor's estimate. A unit's bands sit up to 10 nm from the typical ones, so the estimate is within
about 10 % (RMS over many kinds of light) for a unit that was not measured; its scale under a diffuser dome is not known
either, and the calibration's fitted sensitivity absorbs a constant scale. Saturated spectra are left out.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from cwtool import sensors

FILE_NAME = "as7341.csv"
SENSOR = "AS7341"
# lux per basic count of F1-F8 (tools/as7341_weights.py; a test checks that they match it)
WEIGHTS = (-4.56603, 14.947, 35.7836, 225.607, 338.899, 178.119, 56.4148, -22.9339)
BAND_COLUMNS = ("F1 415 nm", "F2 445 nm", "F3 480 nm", "F4 515 nm", "F5 555 nm", "F6 590 nm", "F7 630 nm", "F8 680 nm")
SMOOTH_SAMPLES = 3   # the running median: 0.4-1.3 s at the sensor's 2.3-7.5 spectra a second


def photopic_lux(bands) -> np.ndarray:
    """The estimate (lux) from the eight bands, an (N, 8) array of basic counts, kept at or above zero."""
    return np.maximum(np.asarray(bands, dtype=float) @ np.asarray(WEIGHTS), 0.0)


def files(folder: Path, recursive: bool = False) -> list[Path]:
    """The AS7341 files of ``folder`` (and of its subfolders with ``recursive``: one folder per logger session)."""
    folder = Path(folder)
    if not folder.is_dir():
        return []
    found = folder.rglob(FILE_NAME) if recursive else [folder / FILE_NAME]
    return sorted(p for p in found if p.is_file())


def read(folder: Path, epoch_start: float, duration: float, margin: float = 60.0, recursive: bool = False):
    """The estimate over a recording, on its relative clock (s): (time, lux) sorted by time, empty arrays if no file
    overlaps. Files written by a logger whose clock mapping lagged the board's drift are repaired as the other
    sensors' are (:func:`cwtool.sensors.repair_lagging_clock`, open issue 62)."""
    t0, t1 = epoch_start - margin, epoch_start + duration + margin
    times, values = [], []
    for path in files(folder, recursive):
        span = sensors._file_span(path)
        if span is not None and (span[1] < t0 or span[0] > t1):
            continue
        lagging = sensors.clock_lagged(path.parent)
        try:
            sensor = sensors.read_sensor(path, "as7341", t0 - 1.0, t1 + sensors.OLD_WINDOW + 5.0) if lagging else \
                sensors.read_sensor(path, "as7341", t0, t1)
        except ValueError:
            continue
        if not len(sensor) or any(c not in sensor.data for c in BAND_COLUMNS):
            continue
        unix = sensor.unix
        if lagging and sensors.DEVICE_COLUMN in sensor.data:
            unix, _ = sensors.repair_lagging_clock(unix, sensor.data[sensors.DEVICE_COLUMN])
        bands = np.column_stack([sensor.data[c] for c in BAND_COLUMNS])
        saturated = sensor.data.get("saturated", np.zeros(len(unix)))
        keep = (unix >= t0) & (unix <= t1) & np.isfinite(bands).all(axis=1) & (np.nan_to_num(saturated) == 0)
        times.extend((unix[keep] - epoch_start).tolist())
        values.extend(photopic_lux(bands[keep]).tolist())
    order = np.argsort(times)
    return np.asarray(times, dtype=float)[order], np.asarray(values, dtype=float)[order]

