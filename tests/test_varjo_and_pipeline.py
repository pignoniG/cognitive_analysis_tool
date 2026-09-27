import json

import numpy as np
import pytest

from cwtool import calibration, cli, devices, pipeline
from cwtool.devices import varjo
from cwtool.params import Parameters, VideoSettings
from cwtool.video import analyse_video
from conftest import write_varjo_recording


def test_varjo_reader(varjo_folder):
    assert devices.detect(varjo_folder) == "varjo"
    rec = devices.load(varjo_folder)
    assert rec.profile.native_rate == 200
    assert rec.measured_rate == pytest.approx(100)
    assert len(rec.time) == 400
    assert rec.time[1] == pytest.approx(0.01)
    assert rec.epoch_start == pytest.approx(1_700_000_000)
    assert np.allclose(rec.gaze, 0.5)  # projected (0, 0) is the frame centre
    assert np.allclose(rec.pupil_left, 2.0)  # device units (radius); the pipeline doubles it
    assert rec.luminance_source == "display"
    assert rec.circular_scene


def test_pipeline_zero_cw_when_pupil_follows_model(tmp_path):
    params = Parameters(delay=0.0)
    grays = [0, 60, 120, 180, 240, 90]

    def lum_of(t):
        g = grays[min(int(t), len(grays) - 1)]
        from cwtool import luminance
        lin = luminance.to_linear([g, g, g], params.gamma)
        return luminance.absolute_luminance(lin, params.l_min, params.l_max)

    from cwtool import model
    area = varjo.PROFILE.field_area
    pupil = lambda t: float(model.watson_yellott(lum_of(t), params.age, area)) / 2  # Varjo writes the radius
    folder = write_varjo_recording(tmp_path / "rec", grays, pupil_mm=pupil)
    rec = devices.load(folder)
    video = analyse_video(rec.scene_video, rec.time, rec.gaze, VideoSettings().for_recording(rec))
    result = pipeline.run(rec, video, params)
    # Savitzky-Golay smoothing blurs the steps, so compare away from transitions.
    steady = np.array([(t % 1) > 0.4 and (t % 1) < 0.6 for t in result.cw_time])
    assert np.abs(result.cw[steady]).max() < 0.05
    assert result.expected_black > result.expected_white


def test_pipeline_detects_added_dilation(tmp_path):
    params = Parameters(alignment="none")
    folder = write_varjo_recording(tmp_path / "rec", [128] * 6,
                                   pupil_mm=lambda t: 2.0 + (0.25 if 2 <= t < 4 else 0.0))
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
    seq = calibration.DEFAULT
    assert len(seq.steps) == 20
    assert seq.duration == 120
    assert seq.steps[8].rgb == (64, 0, 0)
    assert seq.steps[-1].rgb == (0, 0, 255)


def test_cli_end_to_end(varjo_folder, capsys):
    assert cli.main([str(varjo_folder)]) == 0
    out = varjo_folder / "cwtool_export"
    assert (out / "rec1_pupil.csv").exists() and (out / "rec1_cw.csv").exists()
    assert (varjo_folder / "cwtool_video.csv").exists()
    assert cli.main([str(varjo_folder)]) == 0  # second run uses the cache
    assert "Analysing" not in capsys.readouterr().out.split("ΔPD")[-1]


def test_version1_params_convert_to_identical_expected_pupil(tmp_path):
    from cwtool import model
    old = {"age": 33, "field": 160.0, "l_min": 1.0, "l_max": 5000.0, "pupil_scale": 2.2, "gain_b": 3}
    p = Parameters.from_dict(old, varjo.PROFILE)
    assert p.version == 2 and p.pupil_correction == pytest.approx(1.1)
    assert p.l_max == pytest.approx(5000 * 160 / varjo.PROFILE.field_area)
    L = np.logspace(-1, 3, 9)
    before = model.watson_yellott(L * 5000 / 200, 33, 160)
    after = model.watson_yellott(L * p.l_max / 200, 33, varjo.PROFILE.field_area)
    assert np.allclose(before, after)
    p.save(tmp_path / "p.json")
    assert Parameters.load(tmp_path / "p.json", varjo.PROFILE) == p  # version 2 is not converted again


def test_pupil_range_and_scale_warning(tmp_path):
    folder = write_varjo_recording(tmp_path / "rec", [128] * 4,
                                   pupil_mm=lambda t: 6.0 if 1 <= t < 1.2 else 2.0)  # 12 mm spike
    rec = devices.load(folder)
    video = analyse_video(rec.scene_video, rec.time, rec.gaze, VideoSettings().for_recording(rec))
    r = pipeline.run(rec, video, Parameters(alignment="none"))
    assert r.pupil_scale == 2.0
    assert np.nanmax(r.measured) < 4.5 and not r.warnings
    r = pipeline.run(rec, video, Parameters(alignment="none", pupil_correction=0.4))
    assert r.warnings and "pupil scale" in r.warnings[0]


def test_varjo_reader_uses_header_names_and_tolerates_nan(tmp_path):
    from conftest import VARJO_HEADER
    folder = tmp_path / "shuffled"
    folder.mkdir()
    # Columns in a different order than the pilot export, with a Windows NaN in a used column.
    order = list(reversed(VARJO_HEADER))
    col = {h: i for i, h in enumerate(order)}
    rows = []
    for i in range(3):
        r = ["0"] * len(order)
        r[col["relative_to_unix_epoch_timestamp"]] = str(1_700_000_000 * 10**9 + i * 5_000_000)
        r[col["relative_to_video_first_frame_timestamp"]] = str(i * 5_000_000)
        for c in ("status", "left_status", "right_status"):
            r[col[c]] = "2"
        r[col["left_pupil_diameter_in_mm"]] = "-nan(ind)" if i == 1 else "1.5"
        r[col["right_pupil_diameter_in_mm"]] = "1.6"
        rows.append(r)
    import csv as _csv
    with open(folder / "varjo_gaze_output_x.csv", "w", newline="") as f:
        w = _csv.writer(f)
        w.writerow(order)
        w.writerows(rows)
    rec = devices.load(folder)
    assert rec.pupil_right.tolist() == [1.6, 1.6, 1.6]
    assert rec.pupil_left[0] == 1.5 and np.isnan(rec.pupil_left[1])
    assert rec.time[1] == pytest.approx(0.005)
