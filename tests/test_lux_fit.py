from dataclasses import replace

import numpy as np
import pytest

from cwtool import calibration, devices, pipeline
from cwtool.params import Parameters, VideoSettings
from cwtool.photometry import fit_lux_response
from cwtool.pipeline import expected_pupil, prepare
from cwtool.video import analyse_video
from conftest import write_core_recording

FRAME_TIMES = np.arange(300) / 30          # 10 s
GRAYS = [128] * 300
STEPS = calibration.Sequence(tuple(calibration.Step(3.0 * i, 3.0 * (i + 1), (g, g, g), f"Gray {g}")
                                   for i, g in enumerate((30, 200, 90))), "test")


def lux(t):
    return 40.0 if t < 3.0 else (400.0 if t < 6.0 else 120.0)


def _video(rec):
    return analyse_video(rec.scene_video, rec.time, rec.gaze, VideoSettings().for_recording(rec),
                         frame_times=rec.scene_frame_times)


def synthetic(tmp_path, sensitivity, offset, params):
    """A Pupil Core recording whose pupil is the model's, at ``sensitivity``, minus ``offset``."""
    rec = devices.load(write_core_recording(tmp_path / "core", GRAYS, FRAME_TIMES, lux=lux))
    video = _video(rec)
    prep = prepare(rec, video, params)
    exp = expected_pupil(prep.luminance, prep.fs, replace(params, sensitivity=sensitivity), rec.profile.field_area)
    pupil = np.interp(rec.time, prep.time, exp) - offset
    return replace(rec, pupil_left=pupil, pupil_right=pupil.copy()), video


def test_recovers_sensitivity_and_offset(tmp_path):
    params = Parameters(delay=0.0, dynamics=False, alignment="none")
    rec, video = synthetic(tmp_path, sensitivity=0.4, offset=0.35, params=params)
    fit = fit_lux_response(rec, video, params, 0.0, STEPS)
    assert fit.sensitivity == pytest.approx(0.4, rel=0.1)
    assert fit.offset == pytest.approx(0.35, abs=0.03)
    assert fit.rms_after < 0.05 and fit.rms_after <= fit.rms_before      # the pupil is smoothed at the steps
    assert fit.correlation > 0.99 and fit.steps == 3
    assert fit.params.alignment == "fixed" and fit.params.pupil_offset == fit.offset
    assert fit.params.sensitivity == fit.sensitivity
    # Applying it: ΔPD over the sequence is what the fit reported.
    r = pipeline.run(rec, video, fit.params)
    inside = (r.cw_time >= 0.5) & (r.cw_time <= 9.0) & np.isfinite(r.cw)
    assert np.sqrt(np.mean(r.cw[inside] ** 2)) < 0.05


def test_flat_luminance_is_flagged(tmp_path):
    params = Parameters(delay=0.0, dynamics=False, alignment="none")
    rec = devices.load(write_core_recording(tmp_path / "flat", GRAYS, FRAME_TIMES, lux=lambda t: 100.0))
    fit = fit_lux_response(rec, _video(rec), params, 0.0, STEPS)
    assert any("barely" in n for n in fit.notes)


def test_needs_a_lux_log_and_data_in_the_window(tmp_path):
    params = Parameters()
    rec = devices.load(write_core_recording(tmp_path / "nolux", GRAYS, FRAME_TIMES))
    with pytest.raises(ValueError, match="lux sensor"):
        fit_lux_response(rec, _video(rec), params, 0.0, STEPS)
    rec = devices.load(write_core_recording(tmp_path / "lux", GRAYS, FRAME_TIMES, lux=lux))
    with pytest.raises(ValueError, match="sequence"):
        fit_lux_response(rec, _video(rec), params, 500.0, STEPS)      # a start far outside the recording


def test_run_start_from_the_presenter_file(tmp_path):
    run = tmp_path / "run.csv"
    run.write_text("# tool: cwtool calibration page 1\n# participant: 1\n"
                   "time,duration,r,g,b,label,onset_unix_ms\n0,8,73,73,73,Gray 73,1790758675713.000\n"
                   "8,8,0,0,0,Black,1790758683713.000\n")
    assert calibration.run_start_unix(run) == pytest.approx(1790758675.713)
    seq = calibration.load_sequence(run)
    assert len(seq.steps) == 2 and seq.duration == 16
    plain = tmp_path / "plain.csv"
    plain.write_text("time,r,g,b\n0,0,0,0\n6,255,255,255\n")
    assert calibration.run_start_unix(plain) is None


def scene(gaze_levels, background_levels):
    """A VideoResult of 10 s at 30 Hz whose gaze area and background take the given linear grey levels in
    three 3 s blocks (the whole frame is 10 % gaze area, 90 % background)."""
    from cwtool.video import GAMMA_GRID, VideoResult
    n, g = 300, len(GAMMA_GRID)
    block = np.minimum(np.arange(n) // 90, 2)
    gaze = np.asarray(gaze_levels, dtype=float)[block]
    bg = np.asarray(background_levels, dtype=float)[block]

    def lin(v):
        return np.repeat(v[:, None, None], g, axis=1) * np.ones(3)

    return VideoResult(np.arange(n) / 30.0, np.zeros((n, 3)), np.zeros((n, 3)), lin(gaze), lin(bg),
                       lin(0.1 * gaze + 0.9 * bg))


def synthetic_scene(tmp_path, video, weight, sensitivity, offset, params):
    rec = devices.load(write_core_recording(tmp_path / "core", GRAYS, FRAME_TIMES, lux=lux))
    p = replace(params, fixation_weight=weight)
    prep = prepare(rec, video, p)
    exp = expected_pupil(prep.luminance, prep.fs, replace(p, sensitivity=sensitivity), rec.profile.field_area)
    pupil = np.interp(rec.time, prep.time, exp) - offset
    return replace(rec, pupil_left=pupil, pupil_right=pupil.copy())


def test_recovers_the_fixation_weight(tmp_path):
    params = Parameters(delay=0.0, dynamics=False, alignment="none")
    video = scene([0.05, 0.8, 0.3], [0.6, 0.1, 0.5])       # gaze and background move against each other
    rec = synthetic_scene(tmp_path, video, weight=0.85, sensitivity=0.5, offset=0.3, params=params)
    fit = fit_lux_response(rec, video, params, 0.0, STEPS, fit_fixation=True)
    assert fit.weight_fitted and fit.fixation_weight == pytest.approx(0.85, abs=0.08)
    assert fit.sensitivity == pytest.approx(0.5, rel=0.3)
    assert fit.rms_after < 0.2        # the pipeline's smoothing blurs these large steps: about 0.145 even at the true values
    assert fit.params.fixation_weight == fit.fixation_weight
    fixed = fit_lux_response(rec, video, params, 0.0, STEPS)         # the weight is not fitted by default
    assert not fixed.weight_fitted and fixed.fixation_weight == params.fixation_weight
    assert fixed.rms_after > fit.rms_after


def test_fixation_weight_is_flagged_on_a_uniform_scene(tmp_path):
    params = Parameters(delay=0.0, dynamics=False, alignment="none")
    video = scene([0.05, 0.8, 0.3], [0.05, 0.8, 0.3])       # gaze area and background alike
    rec = synthetic_scene(tmp_path, video, weight=0.65, sensitivity=0.5, offset=0.3, params=params)
    fit = fit_lux_response(rec, video, params, 0.0, STEPS, fit_fixation=True)
    assert any("hardly depends" in n for n in fit.notes)


def test_fixation_fit_needs_the_video_route(tmp_path):
    params = Parameters(delay=0.0, dynamics=False, lux_use_video=False)
    rec = devices.load(write_core_recording(tmp_path / "core", GRAYS, FRAME_TIMES, lux=lux))
    with pytest.raises(ValueError, match="video route"):
        fit_lux_response(rec, _video(rec), params, 0.0, STEPS, fit_fixation=True)
