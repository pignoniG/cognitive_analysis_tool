"""Checks of the timestamps in a recorded logger session (open issue 49).

    python -m cwtool.logger.clockcheck SESSION_FOLDER

* **Regularity** of each file (lux, Shimmer, EmotiBit signals): the rate, and how much the time between samples
  varies. The lux sensor is stamped when its line arrives over USB, so this is its timestamp jitter.
* **The Shimmer's clock against the computer's:** its own clock (``device time (s)``) is regular but drifts; the file's
  ``unix time (s)`` maps it onto the computer's. How fast the clock runs (ppm), and how far the mapping wanders around a
  straight line, say how good that mapping is.
* **Shimmer against EmotiBit:** the offset between their timestamps, from a motion both feel (taps with the two units
  fixed together): the lag that best matches the movement of their accelerometers. A positive value means the second
  device's timestamps are late with respect to the first's.

The offset is only as good as the shared movement: record about a minute with the units taped together and knock the
table five or six times, a few seconds apart.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

from cwtool import sensors

GRID_HZ = 200.0


def interval_stats(t) -> dict:
    """Rate and regularity of a series of times (s)."""
    t = np.sort(np.asarray(t, dtype=float))
    d = np.diff(t)
    d = d[d > 0]
    if len(d) < 3:
        return {"samples": int(len(t))}
    med = float(np.median(d))
    return {"samples": int(len(t)), "seconds": round(float(t[-1] - t[0]), 2), "rate_hz": round(1 / med, 3),
            "interval_median_ms": round(med * 1e3, 2), "interval_std_ms": round(float(d.std()) * 1e3, 2),
            "interval_p1_p99_ms": [round(float(np.percentile(d, 1)) * 1e3, 1),
                                   round(float(np.percentile(d, 99)) * 1e3, 1)],
            "longest_gap_ms": round(float(d.max()) * 1e3, 1), "gaps_over_3x_median": int((d > 3 * med).sum())}


def shimmer_clock(unix, device) -> dict:
    """The mapping of the Shimmer's clock onto the computer's: how fast its clock runs (ppm, positive = fast) and the
    wander of the mapping about a straight line."""
    unix, device = np.asarray(unix, dtype=float), np.asarray(device, dtype=float)
    ok = np.isfinite(unix) & np.isfinite(device)
    unix, device = unix[ok], device[ok]
    if len(unix) < 100 or device[-1] - device[0] < 5:
        return {}
    slope, intercept = np.polyfit(device, unix, 1)
    residual = unix - (slope * device + intercept)
    offset = unix - device
    # unix = slope * device: a device clock that runs fast by e ppm has a slope of about 1 - e
    return {"drift_ppm": round((1 / slope - 1) * 1e6, 1),
            "wander_std_ms": round(float(residual.std()) * 1e3, 2),
            "wander_p1_p99_ms": [round(float(np.percentile(residual, 1)) * 1e3, 1),
                                 round(float(np.percentile(residual, 99)) * 1e3, 1)],
            "offset_range_ms": round(float(offset.max() - offset.min()) * 1e3, 1)}


def _activity(t, xyz, grid) -> np.ndarray:
    """How fast the acceleration changes (|d/dt| of the vector, smoothed over 20 ms), on a common time grid,
    normalised: taps and knocks show as bursts whatever the units and the gravity offset of each device."""
    interp = np.column_stack([np.interp(grid, t, c) for c in xyz])
    jerk = np.linalg.norm(np.diff(interp, axis=0), axis=1)
    jerk = np.append(jerk, jerk[-1])
    width = max(int(0.02 * GRID_HZ), 1)
    jerk = np.convolve(jerk, np.ones(width) / width, mode="same")
    return (jerk - jerk.mean()) / (jerk.std() or 1.0)


def movement_offset(a, b, max_lag: float = 2.0) -> dict:
    """Offset (s) of device ``b``'s timestamps with respect to ``a``'s from the movement both measured: ``a`` and
    ``b`` are ``(time, [x, y, z])`` with the time in seconds on one clock. Positive: ``b`` is late. Also the
    strength of the match and how clearly the best lag stands out from the second best."""
    t0, t1 = max(a[0][0], b[0][0]), min(a[0][-1], b[0][-1])
    if t1 - t0 < 5:
        return {}
    grid = np.arange(t0, t1, 1 / GRID_HZ)
    xa, xb = _activity(a[0], a[1], grid), _activity(b[0], b[1], grid)
    n = len(grid)
    corr = np.correlate(xb, xa, mode="full") / n          # lag k: b(t) ≈ a(t - k / GRID_HZ)
    lags = np.arange(-n + 1, n) / GRID_HZ
    keep = np.abs(lags) <= max_lag
    c, lag = corr[keep], lags[keep]
    i = int(np.argmax(c))
    if 0 < i < len(c) - 1:  # refine the peak with a parabola through its neighbours
        y0, y1, y2 = c[i - 1], c[i], c[i + 1]
        shift = 0.5 * (y0 - y2) / (y0 - 2 * y1 + y2) if (y0 - 2 * y1 + y2) != 0 else 0.0
    else:
        shift = 0.0
    far = np.abs(lag - lag[i]) > 0.25                      # the best match away from the peak
    second = float(c[far].max()) if far.any() else 0.0
    # No other lag matches at all (the second best is not above zero): the peak is unambiguous, ratio None.
    return {"offset_s": round(float(lag[i] + shift / GRID_HZ), 4), "match": round(float(c[i]), 3),
            "peak_over_second_best": round(float(c[i] / second), 2) if second > 0 else None}


def is_clear(cross: dict) -> bool:
    """Whether an offset from :func:`movement_offset` can be trusted: a real match, and a peak that stands out."""
    ratio = cross.get("peak_over_second_best")
    return cross.get("match", 0) >= 0.2 and (ratio is None or ratio >= 1.3)


def _xyz_wide(sensor, names):
    return sensor.unix, [sensor.data[n] for n in names]


def _xyz_long(sensor, names):
    series = [sensor.series(n) for n in names]
    t = series[0][0]
    return t, [np.interp(t, s[0], s[1]) for s in series]


def check_session(folder: Path, max_lag: float = 2.0) -> dict:
    """Run the checks on the files of a logger session folder; a dictionary of what was measured."""
    folder = Path(folder)
    report: dict = {"regularity": {}}
    lux = folder / "lux.csv"
    if lux.exists():
        t = [float(line.split(",")[0]) for line in lux.read_text().splitlines()[1:] if line.strip()]
        report["regularity"]["lux"] = interval_stats(t)
    found = {s.kind or s.name: s for s in (sensors.read_sensor(p, k) for p, k in sensors.find_sensor_files(folder))}
    shimmer, emotibit = found.get("shimmer"), found.get("emotibit")
    if shimmer is not None:
        report["regularity"]["shimmer"] = interval_stats(shimmer.unix)
        if "device time (s)" in shimmer.data:
            report["shimmer_clock"] = shimmer_clock(shimmer.unix, shimmer.data["device time (s)"])
    if emotibit is not None:
        for name in emotibit.signals():
            t, _ = emotibit.series(name)
            if len(t) > 20:
                report["regularity"][f"emotibit {name}"] = interval_stats(t)
    if shimmer is not None and emotibit is not None:
        accel_s = [c for c in shimmer.header[1:] if c.startswith("accel_ln_")][:3]
        accel_e = ["ACC_X", "ACC_Y", "ACC_Z"]
        if len(accel_s) == 3 and all(n in emotibit.signals() for n in accel_e):
            report["shimmer_vs_emotibit"] = movement_offset(_xyz_wide(shimmer, accel_s),
                                                            _xyz_long(emotibit, accel_e), max_lag)
    return report


def format_report(report: dict) -> str:
    """The report of :func:`check_session` as text for the terminal."""
    lines = ["Regularity (interval between samples):"]
    for name, s in report["regularity"].items():
        if "rate_hz" in s:
            lines.append(f"  {name:22s} {s['rate_hz']:7.2f} Hz   interval median {s['interval_median_ms']:.1f} ms, "
                         f"std {s['interval_std_ms']:.1f} ms, 1-99 % {s['interval_p1_p99_ms'][0]:.0f}-"
                         f"{s['interval_p1_p99_ms'][1]:.0f} ms, longest gap {s['longest_gap_ms']:.0f} ms")
        else:
            lines.append(f"  {name:22s} too few samples")
    clock = report.get("shimmer_clock")
    if clock:
        lines += ["", "Shimmer clock against the computer's:",
                  f"  the Shimmer's clock runs {clock['drift_ppm']:+.1f} ppm fast (negative: slow), wander about a straight line: std {clock['wander_std_ms']:.2f} ms, "
                  f"1-99 % {clock['wander_p1_p99_ms'][0]:.1f} to {clock['wander_p1_p99_ms'][1]:.1f} ms; the offset "
                  f"moved by {clock['offset_range_ms']:.1f} ms in all"]
    cross = report.get("shimmer_vs_emotibit")
    if cross:
        verdict = "" if is_clear(cross) else "   (weak: not enough shared movement, repeat with clear knocks)"
        lines += ["", "Shimmer against EmotiBit (movement of the accelerometers):",
                  f"  EmotiBit's timestamps are {cross['offset_s'] * 1e3:+.0f} ms late with respect to the Shimmer's "
                  f"(match {cross['match']:.2f}, "
                  + ("no other lag matches" if cross["peak_over_second_best"] is None
                     else f"peak {cross['peak_over_second_best']}x the second best") + f"){verdict}"]
    elif "shimmer" in report["regularity"] and any(k.startswith("emotibit") for k in report["regularity"]):
        lines += ["", "Shimmer against EmotiBit: not possible (needs the Shimmer's accel_ln channels and the "
                      "EmotiBit's ACC_X, ACC_Y, ACC_Z)."]
    return "\n".join(lines)


def main(argv=None) -> int:
    """Command line: check a session folder and print (and with --save, write) the report."""
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("session", type=Path, help="logger session folder")
    ap.add_argument("--max-lag", type=float, default=2.0, help="largest offset looked for between devices (s)")
    ap.add_argument("--save", action="store_true", help="also write clock_check.json into the session folder")
    args = ap.parse_args(argv)
    report = check_session(args.session, args.max_lag)
    print(format_report(report))
    if args.save:
        (args.session / "clock_check.json").write_text(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
