"""Tests of the tracking quality report, the tracker's ceiling on large pupils (Varjo), the participant's iris, and the
calibration fit that treats a step at the ceiling as a lower bound.
"""

import csv
import json
from dataclasses import replace

import numpy as np
import pytest

from cwtool import calibration, devices, luminance, model, pipeline, quality
from cwtool.devices import varjo
from cwtool.params import Parameters, VideoSettings
from cwtool.photometry import fit_light_response
from cwtool.recording import Recording
from cwtool.video import analyse_video
from conftest import VARJO_HEADER, write_varjo_recording

RATE = 100


def _recording(left, right, censored_left=None, censored_right=None, profile=varjo.PROFILE):
    return Recording(name="synthetic", profile=profile, folder=None, time=np.arange(len(left)) / RATE, epoch_start=0.0,
                     pupil_left=np.asarray(left, float), pupil_right=np.asarray(right, float),
                     gaze=np.full((len(left), 2), 0.5), censored_left=censored_left, censored_right=censored_right)


def test_quality_counts_valid_samples_and_dropouts():
    n = 2000                                              # 20 s at 100 Hz
    left, right = np.full(n, 3.0), np.full(n, 3.1)
    left[200:230] = right[200:230] = np.nan               # a 0.3 s blink, both eyes
    left[500:700] = right[500:700] = np.nan               # a 2 s loss, both eyes
    left[1000:1100] = np.nan                              # the left eye alone for 1 s: not a dropout of the pupil
    q = quality.assess(_recording(left, right))
    assert q.samples == n and q.duration_s == pytest.approx(19.99)
    assert q.blinks == 1 and q.long_dropouts == 1
    assert q.longest_dropout_s == pytest.approx(2.0, abs=0.02) and q.lost_s == pytest.approx(2.3, abs=0.03)
    assert q.valid_either == pytest.approx(1 - 230 / n) and q.valid_left == pytest.approx(1 - 330 / n)
    assert q.ceiling is None and q.assumed_iris_mm == varjo.PROFILE.assumed_iris
    assert not q.notes()                                  # nothing here limits the data
    assert any("tracking" in line for line in q.lines())
    assert q.as_dict()["blinks"] == 1


def test_quality_notes_name_what_limits_the_data():
    n = 1000
    left, right = np.full(n, 6.0), np.full(n, 6.0)
    left[:300] = right[:300] = np.nan                     # 30 % lost: 70 % valid, in one 3 s stretch
    flag = np.zeros(n, bool)
    flag[400:430] = True                                  # 30 of the 700 pupil samples at the ceiling (4.3 %)
    q = quality.assess(_recording(left, right, flag, flag))
    assert q.ceiling == pytest.approx(30 / 700)
    text = " ".join(q.notes())
    assert "only 70%" in text and "ceiling" in text
    assert q.lines()[-1].startswith("at the tracker's ceiling") or any("ceiling" in line for line in q.lines())


def _with_ratio(folder, ratio_of):
    """Rewrite the Varjo gaze file's pupil/iris ratio columns: ``ratio_of(pupil value)`` per row."""
    path = next(folder.glob("varjo_gaze_output_*.csv"))
    rows = list(csv.reader(open(path, newline="")))
    col = {h: i for i, h in enumerate(rows[0])}
    for r in rows[1:]:
        for eye in ("left", "right"):
            r[col[f"{eye}_pupil_iris_diameter_ratio"]] = str(ratio_of(float(r[col[f"{eye}_pupil_diameter_in_mm"]])))
    with open(path, "w", newline="") as f:
        csv.writer(f).writerows(rows)


def test_varjo_reader_flags_the_tracker_ceiling(tmp_path):
    # a pupil of 5.0 mm for 5 s, then 6.2 mm (the tracker's ratio stops at 0.5: 6.0 mm of a 12 mm iris) for 5 s
    folder = write_varjo_recording(tmp_path / "rec", [128] * 10, seconds_per_level=1.0, iris_mm=12.0,
                                   pupil_mm=lambda t: 5.0 if t < 5 else 6.2)
    _with_ratio(folder, lambda mm: min(mm / 12.0, 0.5))
    rec = devices.load(folder)
    assert rec.profile.pupil_scale == 1.0 and rec.profile.assumed_iris == pytest.approx(12.0)
    assert rec.censored_left is not None and rec.censored_right is not None
    assert rec.censored_left[: 5 * RATE].sum() == 0 and rec.censored_left[5 * RATE:].all()
    q = quality.assess(rec)
    assert q.ceiling == pytest.approx(0.5) and any("ceiling" in n for n in q.notes())


def test_a_recording_whose_ratios_go_beyond_the_band_has_no_ceiling(tmp_path):
    # large pupils (up to 7.5 mm, ratio 0.62) as in a September 2026 sample: nothing stops at 0.5
    folder = write_varjo_recording(tmp_path / "rec", [128] * 12, seconds_per_level=1.0, iris_mm=12.0,
                                   pupil_mm=lambda t: 5.0 + 2.5 * t / 12)
    _with_ratio(folder, lambda mm: mm / 12.0)
    rec = devices.load(folder)
    assert rec.censored_left is None and rec.censored_right is None
    assert quality.assess(rec).ceiling is None
    # too few samples near the band to say anything, and a pile-up with many samples beyond it is not a cap
    assert not varjo.ceiling_found(np.full(50, 0.5)) and varjo.ceiling_found(np.full(500, 0.5))
    assert not varjo.ceiling_found(np.concatenate([np.full(500, 0.5), np.full(100, 0.58)]))


def test_a_file_without_ratio_columns_or_with_a_measured_iris_has_neither_flag(tmp_path):
    folder = write_varjo_recording(tmp_path / "rec", [128] * 4, iris_mm=12.0)
    path = next(folder.glob("varjo_gaze_output_*.csv"))
    rows = list(csv.reader(open(path, newline="")))
    drop = {i for i, h in enumerate(rows[0]) if h.endswith("pupil_iris_diameter_ratio")}
    with open(path, "w", newline="") as f:
        csv.writer(f).writerows([[v for i, v in enumerate(r) if i not in drop] for r in rows])
    rec = devices.load(folder)                            # an export that does not have the columns still loads
    assert rec.censored_left is None and rec.censored_right is None
    # an iris that varies is measured: the pupil is not a ratio to a constant
    folder = write_varjo_recording(tmp_path / "rec2", [128] * 4, iris_mm=12.0)
    path = next(folder.glob("varjo_gaze_output_*.csv"))
    rows = list(csv.reader(open(path, newline="")))
    col = {h: i for i, h in enumerate(rows[0])}
    for k, r in enumerate(rows[1:]):
        r[col["left_iris_diameter_in_mm"]] = r[col["right_iris_diameter_in_mm"]] = str(11.0 + (k % 100) / 50)
    with open(path, "w", newline="") as f:
        csv.writer(f).writerows(rows)
    assert devices.load(folder).profile.assumed_iris is None


def _load(folder):
    rec = devices.load(folder)
    return rec, analyse_video(rec.scene_video, rec.time, rec.gaze, VideoSettings().for_recording(rec))


def test_a_measured_iris_rescales_the_pupil(tmp_path):
    folder = write_varjo_recording(tmp_path / "rec", [64, 200, 64, 200], seconds_per_level=5.0, iris_mm=12.0,
                                   pupil_mm=3.0)
    rec, video = _load(folder)
    assert pipeline.iris_factor(rec.profile, Parameters()) == 1.0
    assert pipeline.iris_factor(rec.profile, Parameters(iris_diameter=11.0)) == pytest.approx(11.0 / 12.0)
    base = pipeline.prepare(rec, video, Parameters())
    scaled = pipeline.prepare(rec, video, Parameters(iris_diameter=11.0, pupil_correction=1.1))
    assert scaled.scale == pytest.approx(base.scale * 1.1 * 11.0 / 12.0)          # on top of the hand correction
    assert any("scaled ×0.917" in n for n in scaled.notes)
    # a device that measures the pupil itself ignores it, and says so
    neon_like = replace(rec, profile=replace(rec.profile, assumed_iris=None))
    ignored = pipeline.prepare(neon_like, video, Parameters(iris_diameter=11.0))
    assert ignored.scale == base.scale and any("not used" in n for n in ignored.notes)


def test_the_ceiling_reaches_the_result_and_the_export(tmp_path):
    folder = write_varjo_recording(tmp_path / "rec", [128] * 20, seconds_per_level=1.0, iris_mm=12.0,
                                   pupil_mm=lambda t: 6.2 if 8 <= t < 12 else 3.0)
    _with_ratio(folder, lambda mm: min(mm / 12.0, 0.5))
    rec, video = _load(folder)
    r = pipeline.run(rec, video, Parameters())
    assert r.censored_fraction == pytest.approx(0.2, abs=0.03)
    assert r.cw_censored is not None and r.cw_censored.sum() == pytest.approx(0.2 * len(r.cw_time), rel=0.2)
    assert any("ceiling" in w for w in r.warnings)
    out = pipeline.export(r, rec, Parameters(), tmp_path / "out", hrv=False)
    cw = next(p for p in out if p.name.endswith("_cw.csv")).read_text().splitlines()
    assert cw[0].split(",")[-1] == "at_tracker_ceiling" and {line.split(",")[-1] for line in cw[1:]} == {"0", "1"}
    info = json.loads(next(p for p in out if p.name.endswith("_export.json")).read_text())
    assert info["tracking quality"]["ceiling_left"] == pytest.approx(0.2, abs=0.02)


# ---- the calibration fit with steps at the ceiling -------------------------------------------------------------------

STEP, LEAD, CEILING_MM = 10.0, 20.0, 5.0


def _clipped_participant(folder, flag_ceiling: bool):
    """The 20-step staircase for a participant of sensitivity 3, whose tracker stops at 5 mm (the dark steps are larger)."""
    p = Parameters()
    gains = np.array([1.5, 0.7, 0.8])
    seq = calibration.scaled(calibration.STAIRCASE_20, STEP / calibration.STEP_SECONDS)
    colours = [(0, 0, 0)] * int(LEAD / STEP) + [s.rgb for s in seq.steps]
    t = np.arange(len(colours) * STEP * RATE) / RATE
    rgb = np.array([colours[min(int(x // STEP), len(colours) - 1)] for x in t], dtype=float)
    L = luminance.absolute_luminance(luminance.to_linear(rgb, p.gamma), p.l_min, p.l_max, gains)
    pd = model.watson_yellott(L * 3.0, p.age, varjo.PROFILE.field_area)
    pd = model.attack_release(model.delay(pd, RATE, 0.3), RATE, 4.0, 0.4)
    pd = pd + np.random.default_rng(0).normal(0, 0.02, len(pd))
    assert pd.max() > CEILING_MM + 0.5                    # the dark steps do exceed the ceiling
    shown = np.minimum(pd, CEILING_MM)
    write_varjo_recording(folder, colours, seconds_per_level=STEP, iris_mm=12.0,
                          pupil_mm=lambda x: float(shown[min(int(x * RATE), len(t) - 1)]))
    _with_ratio(folder, lambda mm: 0.5 if (flag_ceiling and mm >= CEILING_MM - 1e-6) else mm / 12.0 * 0.99)
    return _load(folder) + (seq,)


def test_steps_at_the_ceiling_are_lower_bounds_in_the_light_fit(tmp_path):
    rec, video, seq = _clipped_participant(tmp_path / "flagged", True)
    flagged = fit_light_response(rec, video, Parameters(), start=LEAD, sequence=seq)
    assert any(s.censored for s in flagged.steps) and not all(s.censored for s in flagged.steps)
    assert any("ceiling" in n for n in flagged.notes)
    rec2, video2, _ = _clipped_participant(tmp_path / "plain", False)
    plain = fit_light_response(rec2, video2, Parameters(), start=LEAD, sequence=seq)
    assert not any(s.censored for s in plain.steps)
    # the clipped dark steps pull a fit that takes them as measured; as lower bounds they only forbid a smaller model
    err = lambda fit: abs(np.log(fit.sensitivity / 3.0))
    assert err(flagged) < err(plain)
    assert flagged.rms_after <= plain.rms_after + 0.02
