import numpy as np
import pytest

from cwtool import devices, pipeline
from cwtool.params import Parameters, VideoSettings
from cwtool.video import analyse_video
from conftest import write_varjo_recording


def test_resample_irregular_and_gaps():
    t = np.array([0.0, 0.011, 0.019, 0.031, 0.04, 1.0, 1.01, 1.02])  # jitter, then a 0.96 s gap
    v = t * 10
    grid, filled, valid = pipeline.resample(t, v, rate=100, max_gap=0.5)
    assert grid[0] == 0 and grid[-1] == pytest.approx(1.02)
    assert np.allclose(np.diff(grid), 0.01)
    assert np.allclose(filled, grid * 10)          # linear signal survives interpolation
    assert valid[grid <= 0.04].all()
    assert not valid[(grid > 0.05) & (grid < 0.99)].any()
    assert valid[grid >= 1.0].all()


def test_short_gaps_are_bridged():
    t = np.r_[np.arange(0, 1, 0.01), np.arange(1.3, 2, 0.01)]  # 0.3 s blink
    _, _, valid = pipeline.resample(t, np.ones_like(t), rate=100, max_gap=0.5)
    assert valid.all()


def test_both_eyes_fall_back_to_one():
    class Rec:
        pupil_left = np.array([3.0, np.nan, 3.0])
        pupil_right = np.array([5.0, 5.0, np.nan])
    assert pipeline.select_pupil(Rec, "both").tolist() == [4.0, 5.0, 3.0]


def test_residual_rms_vs_sd():
    x = np.array([1.0, 1.0, 1.0, np.nan])
    assert pipeline.residual_rms(x) == pytest.approx(1.0)
    assert np.nanstd(x) == 0


def _run(folder, **kw):
    rec = devices.load(folder)
    video = analyse_video(rec.scene_video, rec.time, rec.gaze, VideoSettings().for_recording(rec))
    return rec, pipeline.run(rec, video, Parameters(**kw))


def test_long_tracking_loss_is_excluded(tmp_path):
    lost = lambda t: np.nan if 2.0 <= t < 3.5 else 3.0
    folder = write_varjo_recording(tmp_path / "rec", [128] * 5, pupil_mm=lost)
    rec, r = _run(folder)
    inside = (r.time > 2.1) & (r.time < 3.4)
    assert np.isnan(r.measured[inside]).all()
    assert np.isfinite(r.expected[inside]).all()
    assert np.isnan(r.cw[(r.cw_time > 2.2) & (r.cw_time < 3.3)]).all()
    assert r.gap_fraction == pytest.approx(0.3, abs=0.03)
    assert np.isfinite(r.cw_rms)


def test_analysis_rate_is_independent_of_device_rate(tmp_path):
    folder = write_varjo_recording(tmp_path / "rec", [60, 200, 60], rate=200)
    rec, r100 = _run(folder, analysis_rate=100)
    _, r200 = _run(folder, analysis_rate=0)   # native (nominal 100 for Varjo)
    assert rec.measured_rate == pytest.approx(200)
    assert np.diff(r100.time).mean() == pytest.approx(0.01)
    assert r100.expected_white == r200.expected_white
