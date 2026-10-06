"""The clock checks of a recorded logger session, on synthetic sessions with known answers."""

import csv
import json

import numpy as np
import pytest

from cwtool.logger import clockcheck

TAPS = [5.0, 12.0, 19.0, 27.0, 33.0, 41.0, 48.0]
EPOCH = 1_700_000_000.0


def knocks(t, scale=1.0):
    """A burst of acceleration at each tap: a short pulse, slow enough for the EmotiBit's 25 Hz."""
    out = np.zeros_like(t)
    for tap in TAPS:
        d = t - tap
        out += np.where(d >= 0, np.exp(-d / 0.07) * np.sin(2 * np.pi * 6 * d), 0.0)
    return out * scale


def write_session(folder, emotibit_late=0.25, drift_ppm=100.0, seconds=60, seed=1):
    rng = np.random.default_rng(seed)
    folder.mkdir(parents=True, exist_ok=True)
    # Shimmer, 51.2 Hz, its device clock 100 ppm fast; unix time = the computer's clock (with a little jitter)
    t = np.arange(0, seconds, 1 / 51.2)
    device = t * (1 + drift_ppm * 1e-6)
    with open(folder / "shimmer.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["unix time (s)", "device time (s)", "accel_ln_x", "accel_ln_y", "accel_ln_z"])
        a = knocks(t, 400)
        for i in range(len(t)):
            w.writerow([f"{EPOCH + t[i] + rng.normal(0, 0.0005):.6f}", f"{device[i]:.5f}",
                        2000 + a[i] + rng.normal(0, 3), 2050 + 0.3 * a[i] + rng.normal(0, 3), 1230 + rng.normal(0, 3)])
    # EmotiBit, 25 Hz, in g, long format; its timestamps are late by `emotibit_late`
    te = np.arange(0, seconds, 1 / 25)
    b = knocks(te, 0.5)
    with open(folder / "emotibit.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["unix time (s)", "signal", "value"])
        for i in range(len(te)):
            stamp = f"{EPOCH + te[i] + emotibit_late:.6f}"
            w.writerow([stamp, "ACC_X", 0.02 + b[i] + rng.normal(0, 0.003)])
            w.writerow([stamp, "ACC_Y", 0.98 + 0.2 * b[i] + rng.normal(0, 0.003)])
            w.writerow([stamp, "ACC_Z", 0.05 + rng.normal(0, 0.003)])
    (folder / "lux.csv").write_text("unix time (s),lux\n" + "".join(
        f"{EPOCH + i * 0.122 + rng.normal(0, 0.002):.4f},5.0\n" for i in range(int(seconds / 0.122))))
    (folder / "session.json").write_text(json.dumps({"sources": {
        "lux": {"file": "lux.csv", "kind": "lux"}, "shimmer": {"file": "shimmer.csv", "kind": "shimmer"},
        "emotibit": {"file": "emotibit.csv", "kind": "emotibit"}}}))
    return folder


def test_offset_between_shimmer_and_emotibit_is_found(tmp_path):
    for late in (0.25, -0.4, 0.0):
        report = clockcheck.check_session(write_session(tmp_path / f"s{late}", emotibit_late=late))
        cross = report["shimmer_vs_emotibit"]
        assert cross["offset_s"] == pytest.approx(late, abs=0.03), late
        assert cross["match"] > 0.3 and clockcheck.is_clear(cross)


def test_shimmer_drift_and_regularity(tmp_path):
    report = clockcheck.check_session(write_session(tmp_path / "s", drift_ppm=100.0))
    clock = report["shimmer_clock"]
    assert clock["drift_ppm"] == pytest.approx(100.0, abs=15)   # the device clock runs 100 ppm fast
    assert clock["wander_std_ms"] < 1.5
    reg = report["regularity"]
    assert reg["shimmer"]["rate_hz"] == pytest.approx(51.2, abs=0.3)
    assert reg["lux"]["rate_hz"] == pytest.approx(8.2, abs=0.2) and reg["lux"]["interval_std_ms"] < 5
    assert reg["emotibit ACC_X"]["rate_hz"] == pytest.approx(25.0, abs=0.2)


def test_no_shared_movement_is_flagged_as_weak(tmp_path, capsys):
    folder = write_session(tmp_path / "s")
    # the EmotiBit sat still: noise only
    rng = np.random.default_rng(3)
    rows = list(csv.reader(open(folder / "emotibit.csv")))
    with open(folder / "emotibit.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(rows[0])
        for r in rows[1:]:
            w.writerow([r[0], r[1], float(r[2]) * 0 + rng.normal(0, 0.01)])
    cross = clockcheck.check_session(folder)["shimmer_vs_emotibit"]
    assert not clockcheck.is_clear(cross)
    assert "weak" in clockcheck.format_report(clockcheck.check_session(folder))


def test_command_line_prints_and_saves(tmp_path, capsys):
    folder = write_session(tmp_path / "s")
    assert clockcheck.main([str(folder), "--save"]) == 0
    out = capsys.readouterr().out
    assert "EmotiBit's timestamps are +250 ms late" in out or "ms late with respect to the Shimmer" in out
    assert json.loads((folder / "clock_check.json").read_text())["shimmer_vs_emotibit"]["offset_s"] == pytest.approx(0.25, abs=0.03)
