"""Tests of the heart rate variability from a Shimmer's ECG: R-peak detection on a synthetic ECG with known beat
times, the trusted intervals, the measures, the spectrum, the export trim and the files written."""

import csv
import json
from pathlib import Path

import numpy as np
import pytest

from cwtool import hrv, pipeline
from cwtool.hrv import DEVICE_TIME, LEAD_II
from cwtool.params import Parameters
from cwtool.recording import Event
from cwtool.sensors import Sensor
from cwtool.trim import Trim

EPOCH = 1_700_000_000.0
GAIN = 4.0


def synthetic_ecg(rr, fs=256.0, noise=0.02, flip=False, seed=1, lead_in=1.0):
    """(times, mV, true R times) of an ECG with a P, Q, R, S and T wave per beat, beats ``rr`` seconds apart (the first
    at ``lead_in``), baseline wander and noise."""
    rng = np.random.default_rng(seed)
    beats = lead_in + np.concatenate([[0.0], np.cumsum(rr)])
    t = np.arange(0, beats[-1] + 1.5, 1.0 / fs)
    x = np.zeros_like(t)
    for b in beats:
        for centre, amp, width in ((-0.16, 0.12, 0.025), (-0.025, -0.10, 0.010), (0.0, 1.0, 0.010),
                                   (0.025, -0.20, 0.012), (0.25, 0.30, 0.050)):
            x += amp * np.exp(-0.5 * ((t - b - centre) / width) ** 2)
    x += 0.15 * np.sin(2 * np.pi * 0.2 * t) + noise * rng.standard_normal(len(t))
    return t, (-x if flip else x), beats


def to_sensor(t, mv, drop=None, settings=None, offset=27.0):
    """A Shimmer sensor holding the ECG as raw counts at gain 4; ``drop`` is a boolean mask of rows that were lost."""
    counts = np.round(mv / (hrv.REFERENCE_V * 1000.0 / hrv.ADC_FULL_SCALE / GAIN) + offset * 1000)
    keep = np.ones(len(t), bool) if drop is None else ~drop
    unix = EPOCH + 0.3 + t[keep]
    return Sensor("shimmer", "shimmer", Path("shimmer.csv"), ["unix time (s)", DEVICE_TIME, LEAD_II], unix,
                  {DEVICE_TIME: t[keep], LEAD_II: counts[keep]}, settings or {})


def rr_series(n=120, mean=1.0, depth=0.08, freq=0.25, seed=2):
    """Beat to beat intervals modulated at ``freq`` Hz (breathing) with a little jitter."""
    rng = np.random.default_rng(seed)
    t = np.cumsum(np.full(n, mean))
    return mean + depth * np.sin(2 * np.pi * freq * t) + 0.005 * rng.standard_normal(n)


def test_counts_become_millivolts_with_the_gain():
    one_mv_counts = hrv.ADC_FULL_SCALE / (hrv.REFERENCE_V * 1000.0) * GAIN
    assert hrv.millivolts([one_mv_counts], 4.0)[0] == pytest.approx(1.0)
    assert hrv.millivolts([one_mv_counts], 8.0)[0] == pytest.approx(0.5)


def test_the_gain_comes_from_the_session_or_a_note_says_it_was_assumed():
    s = to_sensor(*synthetic_ecg(rr_series(20))[:2], settings={"exg": {"chip 1": {"gain ch1": 6}}})
    assert hrv.ecg_gain(s) == (6.0, [])
    gain, notes = hrv.ecg_gain(to_sensor(*synthetic_ecg(rr_series(20))[:2]))
    assert gain == 4.0 and "assumed" in notes[0]


def test_r_peaks_are_found_within_a_few_ms_and_the_intervals_are_recovered():
    rr = rr_series()
    t, mv, truth = synthetic_ecg(rr)
    beats = hrv.beats_of(to_sensor(t, mv))
    assert len(beats.device) == len(truth)
    assert np.abs(beats.device - truth).max() < 0.006                        # within 6 ms, at 256 Hz
    assert beats.ok[1:].all()
    est = np.diff(beats.device)
    assert np.sqrt(np.mean(np.diff(est) ** 2)) == pytest.approx(np.sqrt(np.mean(np.diff(rr) ** 2)), rel=0.1)
    # the Unix time of a beat is its device time plus the offset of the clock mapping
    assert np.allclose(beats.unix - beats.device, EPOCH + 0.3, atol=1e-5)


def test_beats_that_are_half_as_tall_as_the_largest_are_still_found():
    """Breathing and posture change the height of the R wave by a factor of two within a minute. The detector must not
    depend on the squared slope of the tallest beats (a beat of half the height has a quarter of its energy)."""
    rr = rr_series(200)
    t, mv, truth = synthetic_ecg(rr, noise=0.015)
    beat_index = np.round((truth * 256)).astype(int)
    gain = np.ones(len(t))
    height = 0.85 + 0.35 * np.sin(2 * np.pi * 0.07 * truth)           # R amplitude 0.5 .. 1.2 times the normal
    # scale each beat's QRS by its own height (the P and T waves stay: the baseline keeps its look)
    qrs = np.zeros_like(t)
    for b, h in zip(truth, height):
        qrs += (h - 1.0) * (np.exp(-0.5 * ((t - b + 0.025) / 0.010) ** 2) * -0.10 + np.exp(-0.5 * ((t - b) / 0.010) ** 2)
                            + np.exp(-0.5 * ((t - b - 0.025) / 0.012) ** 2) * -0.20)
    beats = hrv.beats_of(to_sensor(t, mv + qrs))
    found = np.array([np.min(np.abs(beats.device - b)) < 0.02 for b in truth])
    assert found.mean() > 0.99, f"{(~found).sum()} of {len(truth)} beats missed"
    assert len(beats.device) <= len(truth) + 1                          # and no T waves taken for beats


def test_an_inverted_ecg_gives_the_same_beats():
    t, mv, truth = synthetic_ecg(rr_series(60), flip=True)
    beats = hrv.beats_of(to_sensor(t, mv))
    assert len(beats.device) == len(truth) and np.abs(beats.device - truth).max() < 0.006


def test_short_gaps_are_bridged_and_long_ones_end_the_stretch():
    t, mv, truth = synthetic_ecg(rr_series(60))
    lost = np.zeros(len(t), bool)
    lost[3000:3006] = True                                                    # six packets lost: 23 ms
    beats = hrv.beats_of(to_sensor(t, mv, drop=lost))
    assert len(beats.device) == len(truth) and len(set(beats.block)) == 1 and beats.ok[1:].all()
    lost[:] = False
    gap = (t > 20.0) & (t < 23.0)                                              # three seconds without data
    beats = hrv.beats_of(to_sensor(t, mv, drop=gap))
    assert len(set(beats.block)) == 2
    first_after = np.flatnonzero(beats.block == 1)[0]
    assert np.isnan(beats.rr[first_after]) and not beats.ok[first_after]       # nothing is measured across the gap


def test_a_missed_beat_and_an_extra_one_are_not_trusted():
    rr = rr_series(100)
    t, mv, truth = synthetic_ecg(rr)
    mv = mv.copy()
    miss = int(np.argmin(np.abs(t - truth[40])))
    a, b = miss - 40, miss + 40
    mv[a:b] = np.linspace(mv[a], mv[b], b - a)                                 # the QRS of one beat is gone, smoothly
    beats = hrv.beats_of(to_sensor(t, mv))
    assert len(beats.device) == len(truth) - 1
    long_one = np.flatnonzero(np.nan_to_num(beats.rr) > 1.7)
    assert len(long_one) == 1 and not beats.ok[long_one[0]]
    assert beats.ok[1:].sum() >= len(beats.device) - 3                         # only the interval round it is lost


def test_measures_of_known_intervals():
    n = 60
    rel = np.cumsum(np.full(n, 1.0))
    even = hrv.window_metrics("w", 0, 60, 60, rel, np.r_[np.nan, np.full(n - 1, 1.0)], np.r_[False, np.ones(n - 1, bool)])
    assert even.mean_hr == pytest.approx(60.0) and even.sdnn == pytest.approx(0.0) and even.rmssd == pytest.approx(0.0)
    alt = np.r_[np.nan, np.tile([0.9, 1.1], (n - 1) // 2 + 1)[:n - 1]]
    res = hrv.window_metrics("w", 0, 60, 60, np.cumsum(np.nan_to_num(alt, nan=1.0)), alt, np.isfinite(alt))
    assert res.rmssd == pytest.approx(200.0) and res.pnn50 == pytest.approx(100.0)
    assert res.sd1 == pytest.approx(200.0 / np.sqrt(2), rel=0.02) and res.mean_nn == pytest.approx(1000.0, rel=0.01)
    assert np.isfinite(res.lf) and np.isfinite(res.hf) and any("few cycles" in x for x in res.notes)   # 60 s: a spectrum
    assert res.pnn20 == pytest.approx(100.0)
    three = np.r_[np.nan, np.tile([0.9, 1.0, 1.1], 20)]                      # the median 1000 ms, the median deviation 100 ms
    mad = hrv.window_metrics("w", 0, 60, 60, np.cumsum(np.nan_to_num(three, nan=1.0)), three, np.isfinite(three))
    assert mad.madnn == pytest.approx(1.4826 * 100.0, rel=0.01)
    assert res.cvnn == pytest.approx(res.sdnn / res.mean_nn)
    assert res.sd2 == pytest.approx(0.0, abs=1e-6) and np.isnan(res.sd1_sd2)          # alternating: all on the anti-diagonal
    assert mad.sd1_sd2 == pytest.approx(mad.sd1 / mad.sd2) and mad.cvnn == pytest.approx(mad.sdnn / mad.mean_nn)
    assert res.lfn + res.hfn == pytest.approx(1.0) and res.lnhf == pytest.approx(np.log(res.hf))


def test_untrusted_intervals_do_not_enter_and_the_differences_skip_them():
    rr = np.array([np.nan, 1.0, 1.0, 5.0, 1.0, 1.0])
    ok = np.array([False, True, True, False, True, True])
    res = hrv.window_metrics("w", 0, 10, 10, np.arange(6.0), rr, ok)
    assert res.intervals == 4 and res.rmssd == pytest.approx(0.0) and res.sdnn == pytest.approx(0.0)
    assert res.artefact_share == pytest.approx(1 / 5)


def test_the_spectrum_puts_breathing_in_hf_and_slow_waves_in_lf():
    for freq, high in ((0.25, "hf"), (0.09, "lf")):
        rr = 1.0 + 0.05 * np.sin(2 * np.pi * freq * np.cumsum(np.full(400, 1.0)))
        times = np.cumsum(rr)
        lf, hf = hrv.spectrum(times, rr * 1000.0)
        assert (hf > 5 * lf) if high == "hf" else (lf > 5 * hf)
    # a modulation of ±50 ms at 0.25 Hz has a power of 50²/2 ms² (all in HF)
    assert hf < 50 ** 2 / 2 * 1.5 and lf > 50 ** 2 / 2 * 0.5
    assert all(np.isnan(v) for v in hrv.spectrum(times[:30], rr[:30] * 1000.0))     # 30 s: too short


def test_a_short_window_is_flagged_and_has_no_spectrum():
    t, mv, _ = synthetic_ecg(rr_series(50))
    results, beats = hrv.analyse(to_sensor(t, mv), EPOCH + 0.3, [("whole", 0.0, 50.0)])
    r = results[0]
    assert np.isnan(r.lf) and np.isnan(r.hfn) and any("RMSSD, pNN50 and SD1 are usable" in n for n in r.notes)
    assert 55 < r.mean_hr < 65 and np.isfinite(r.rmssd)
    # the notes follow the window length (Pham et al. 2021): under 30 s, under 1 min, under 2 min, and enough
    def notes_for(seconds):
        return " ".join(hrv.window_metrics("w", 0, seconds, seconds, np.arange(100.0), np.r_[np.nan, np.ones(99)],
                                           np.r_[False, np.ones(99, bool)]).notes)
    assert "even RMSSD is rough" in notes_for(20) and "need minutes" in notes_for(45)
    assert "few cycles" in notes_for(90) and notes_for(300) == ""


def test_a_low_sampling_rate_gets_a_note():
    t, mv, _ = synthetic_ecg(rr_series(40), fs=51.2)
    beats = hrv.beats_of(to_sensor(t, mv))
    assert any("too coarse" in n for n in beats.notes)


def test_windows_and_the_trim_decide_which_intervals_count():
    rr = rr_series(200)
    t, mv, truth = synthetic_ecg(rr)
    sensor = to_sensor(t, mv)
    windows = [("all", 0.0, 200.0), ("first", 0.0, 100.0), ("second", 100.0, 200.0)]
    results, _ = hrv.analyse(sensor, EPOCH + 0.3, windows)
    assert results[1].beats + results[2].beats == results[0].beats and results[0].intervals > 190
    trim = Trim(exclude=[(50.0, 150.0)])
    cut, beats = hrv.analyse(sensor, EPOCH + 0.3, windows, trim)
    assert cut[0].seconds == pytest.approx(100.0) and cut[1].seconds == pytest.approx(50.0)
    # no beat or interval inside the left-out part, and none that spans it
    rel = beats.unix - (EPOCH + 0.3)
    inside = (rel >= 50.0) & (rel < 150.0)
    assert not beats.ok[inside].any()
    after = np.flatnonzero(rel >= 150.0)[0]
    assert not beats.ok[after] and np.isnan(beats.rr[after])


def test_the_files_have_the_measures_and_the_beats(tmp_path):
    t, mv, _ = synthetic_ecg(rr_series(130))
    sensor = to_sensor(t, mv)
    results, beats = hrv.analyse(sensor, EPOCH + 0.3, [("recording", 0.0, 130.0), ("Task", 20.0, 45.0)])
    summary, listing = hrv.write_files(results, beats, tmp_path, "rec_shimmer", EPOCH + 0.3)
    rows = list(csv.DictReader(open(summary)))
    assert [r["window"] for r in rows] == ["recording", "Task"] and float(rows[0]["mean_hr_bpm"]) == pytest.approx(60, abs=3)
    assert rows[0]["lf_ms2"] != "" and rows[1]["lf_ms2"] == ""            # the spectrum needs a minute: only the whole recording
    assert float(rows[0]["lfn"]) + float(rows[0]["hfn"]) == pytest.approx(1.0, abs=0.002) and rows[1]["lnhf"] == ""
    assert {"cvnn", "madnn_ms", "pnn20_percent", "sd1_sd2"} <= set(rows[0]) and rows[1]["rmssd_ms"] != ""
    beat_rows = list(csv.DictReader(open(listing)))
    assert len(beat_rows) == len(beats.device) and beat_rows[0]["rr_ms"] == "" and beat_rows[1]["rr_trusted"] == "1"
    assert float(beat_rows[1]["timestamp_unix"]) - float(beat_rows[1]["timestamp_relative"]) == pytest.approx(EPOCH + 0.3)


def test_export_adds_the_hrv_files_for_a_shimmer_with_an_ecg(tmp_path, monkeypatch):
    from test_export_package import _load
    from conftest import write_varjo_recording

    folder = write_varjo_recording(tmp_path / "rec", [128, 255, 0, 128, 64, 200, 90, 128], pupil_mm=3.0)
    rec, video = _load(folder)
    rec.events = [Event("Rest", 0.0, 4.0), Event("Task", 4.0, 8.0)]
    result = pipeline.run(rec, video, Parameters())
    t, mv, _ = synthetic_ecg(rr_series(30))
    sensor = to_sensor(t, mv, settings={"exg": {"chip 1": {"gain ch1": 4}}})
    sensor.unix = sensor.unix - 0.3 + rec.epoch_start + float(rec.time[0]) - 1.0     # the ECG starts a second early
    paths = pipeline.export(result, rec, Parameters(), tmp_path / "out", sensors=[sensor])
    names = {p.name for p in paths}
    assert {"rec_shimmer.csv", "rec_shimmer_hrv.csv", "rec_shimmer_beats.csv"} <= names
    rows = list(csv.DictReader(open(tmp_path / "out/rec_shimmer_hrv.csv")))
    assert [r["window"] for r in rows] == ["recording", "Rest", "Task"]
    manifest = json.loads((tmp_path / "out/rec_export.json").read_text())
    info = manifest["sensors"][0]["hrv"]
    assert info["files"] == ["rec_shimmer_hrv.csv", "rec_shimmer_beats.csv"] and info["ecg gain"] == 4.0
    assert "rec_shimmer_hrv.csv" in manifest["files"]
    # and it can be left out
    none = pipeline.export(result, rec, Parameters(), tmp_path / "out2", sensors=[sensor], hrv=False)
    assert not any("hrv" in p.name or "beats" in p.name for p in none)


def test_without_neurokit2_the_export_skips_the_hrv_and_says_why(tmp_path, monkeypatch):
    import builtins

    from conftest import write_varjo_recording
    from test_export_package import _load

    real_import = builtins.__import__

    def refuse(name, *args, **kwargs):
        if name.startswith("neurokit2"):
            raise ImportError("No module named 'neurokit2'")
        return real_import(name, *args, **kwargs)

    folder = write_varjo_recording(tmp_path / "rec", [128, 255, 0, 128, 64, 200, 90, 128], pupil_mm=3.0)
    rec, video = _load(folder)
    result = pipeline.run(rec, video, Parameters())
    t, mv, _ = synthetic_ecg(rr_series(30))
    sensor = to_sensor(t, mv)
    sensor.unix = sensor.unix - 0.3 + rec.epoch_start + float(rec.time[0])
    monkeypatch.setattr(builtins, "__import__", refuse)
    with pytest.warns(UserWarning, match="NeuroKit2"):
        paths = pipeline.export(result, rec, Parameters(), tmp_path / "out", sensors=[sensor])
    monkeypatch.setattr(builtins, "__import__", real_import)
    assert "rec_shimmer.csv" in {p.name for p in paths} and not any("hrv" in p.name for p in paths)
    manifest = json.loads((tmp_path / "out/rec_export.json").read_text())
    assert "NeuroKit2" in manifest["sensors"][0]["hrv"]["skipped"]
    with pytest.raises(ImportError, match="cwtool\\[hrv\\]"):
        monkeypatch.setattr(builtins, "__import__", refuse)
        hrv.detect_r_peaks(np.zeros(2000), np.arange(2000) / 256.0)


def _beats_of_intervals(rr_ms, ok=None):
    t = np.cumsum(np.asarray(rr_ms, float) / 1000.0)
    rr = np.r_[np.nan, np.diff(t)]
    ok = np.isfinite(rr) if ok is None else np.asarray(ok, bool)
    return hrv.Beats(t, t + EPOCH, np.ones(len(t)), np.zeros(len(t), int), rr, ok, 256.0, 4.0)


def test_the_heart_rate_and_the_moving_rmssd_of_known_intervals():
    beats = _beats_of_intervals(np.tile([900.0, 1100.0], 100))                 # RMSSD 200 ms, 54.5 and 66.7 bpm
    series = hrv.time_series(beats, EPOCH, window=30.0)
    assert set(np.round(series.hr, 1)) == {54.5, 66.7} and len(series.hr) == len(beats.device) - 1
    assert np.allclose(series.rmssd, 200.0, atol=0.5) and not series.weak.any()
    assert series.rmssd_time[0] == pytest.approx(beats.device[0] - 0.0 + 30.0, abs=1.0)    # one window after the first beat
    # a window with too few trusted successive differences gives no value, and one with many untrusted is weak
    ok = np.ones(len(beats.device), bool)
    ok[60:140] = False
    hole = hrv.time_series(_beats_of_intervals(np.tile([900.0, 1100.0], 100), ok), EPOCH, window=30.0)
    assert np.isnan(hole.rmssd).any() and hole.weak.any() and np.isfinite(hole.rmssd[0])
    assert len(hole.hr) == 100 + 99 - 80 + 0 - 19 or len(hole.hr) < len(series.hr)           # untrusted intervals have no heart rate
    # too few beats: empty
    assert len(hrv.time_series(_beats_of_intervals([1000.0, 1000.0]), EPOCH).hr) == 0
