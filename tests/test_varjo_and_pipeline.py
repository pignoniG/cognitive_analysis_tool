import json

import numpy as np
import pytest

from cwtool import calibration, cli, devices, pipeline
from cwtool.params import Parameters, VideoSettings
from cwtool.video import analyse_video
from conftest import write_varjo_recording


def test_varjo_reader(varjo_folder):
    assert devices.detect(varjo_folder) == "varjo"
    rec = devices.load(varjo_folder)
    assert rec.profile.native_rate == 100
    assert rec.measured_rate == pytest.approx(100)
    assert len(rec.time) == 400
    assert rec.time[1] == pytest.approx(0.01)
    assert rec.epoch_start == pytest.approx(1_700_000_000)
    assert np.allclose(rec.gaze, 0.5)  # projected (0, 0) is the frame centre
    assert np.allclose(rec.pupil_left, 4.0)
    assert rec.luminance_source == "display"
    assert rec.circular_scene


def test_pipeline_zero_cw_when_pupil_follows_model(tmp_path):
    params = Parameters(pupil_scale=1.0, delay=0.0)
    grays = [0, 60, 120, 180, 240, 90]

    def lum_of(t):
        g = grays[min(int(t), len(grays) - 1)]
        from cwtool import luminance
        lin = luminance.srgb_to_linear([g, g, g], params.gamma)
        return luminance.absolute_luminance(lin, params.l_min, params.l_max)

    from cwtool import model
    pupil = lambda t: float(model.watson_yellott(lum_of(t), params.age, params.field))
    folder = write_varjo_recording(tmp_path / "rec", grays, pupil_mm=pupil)
    rec = devices.load(folder)
    video = analyse_video(rec.scene_video, rec.time, rec.gaze, VideoSettings().for_recording(rec))
    result = pipeline.run(rec, video, params)
    # Savitzky-Golay smoothing blurs the steps, so compare away from transitions.
    steady = np.array([(t % 1) > 0.4 and (t % 1) < 0.6 for t in result.cw_time])
    assert np.abs(result.cw[steady]).max() < 0.05
    assert result.expected_black > result.expected_white


def test_pipeline_detects_added_dilation(tmp_path):
    params = Parameters(pupil_scale=1.0, align_mean=False)
    folder = write_varjo_recording(tmp_path / "rec", [128] * 6,
                                   pupil_mm=lambda t: 4.0 + (0.5 if 2 <= t < 4 else 0.0))
    rec = devices.load(folder)
    video = analyse_video(rec.scene_video, rec.time, rec.gaze, VideoSettings().for_recording(rec))
    result = pipeline.run(rec, video, params)
    mid = lambda a, b: result.cw[(result.cw_time > a) & (result.cw_time < b)].mean()
    assert mid(2.5, 3.5) - mid(0.5, 1.5) == pytest.approx(0.5, abs=0.05)


def test_params_roundtrip(tmp_path):
    p = Parameters(l_max=4250, gain_b=11.3)
    p.save(tmp_path / "p.json")
    data = json.loads((tmp_path / "p.json").read_text())
    data["unknown_future_key"] = 1
    (tmp_path / "p.json").write_text(json.dumps(data))
    assert Parameters.load(tmp_path / "p.json") == p


def test_calibration_sequence():
    assert len(calibration.SEQUENCE) == 20
    assert calibration.DURATION == 120
    assert calibration.SEQUENCE[8].rgb == (64, 0, 0)
    assert calibration.SEQUENCE[-1].rgb == (0, 0, 255)


def test_cli_end_to_end(varjo_folder, capsys):
    assert cli.main([str(varjo_folder)]) == 0
    out = varjo_folder / "cwtool_export"
    assert (out / "rec1_pupil.csv").exists() and (out / "rec1_cw.csv").exists()
    assert (varjo_folder / "cwtool_video.csv").exists()
    assert cli.main([str(varjo_folder)]) == 0  # second run uses the cache
    assert "Analysing" not in capsys.readouterr().out.split("ΔPD")[-1]
