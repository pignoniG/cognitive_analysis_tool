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

