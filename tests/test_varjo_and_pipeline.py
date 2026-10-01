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
    params = Parameters(delay=0.0, dynamics=False)   # the pupil follows the steady state instantly
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
    black = result.cw_time < 1
    assert np.abs(result.cw[steady & ~black]).max() < 0.05
    # The test video's codec writes black as code 2 in green, and near Lmin the model is steep: at Lmin 0.01
    # that one code value moves the expected pupil by about 0.03 mm.
    assert np.abs(result.cw[steady & black]).max() < 0.1
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


def test_cli_applies_display_photometry(varjo_folder, tmp_path):
    from cwtool.params import DisplayPhotometry
    DisplayPhotometry("varjo", l_min=0.5, l_max=150.0, gamma=2.4).save(tmp_path / "display.json")
    out = tmp_path / "out"
    assert cli.main([str(varjo_folder), "--display", str(tmp_path / "display.json"), "--out", str(out)]) == 0
    saved = Parameters.load(out / "rec1_params.json", varjo.PROFILE)
    assert (saved.l_min, saved.l_max, saved.gamma) == (0.5, 150.0, 2.4)


def test_version1_params_convert_to_identical_expected_pupil(tmp_path):
    from cwtool import model
    old = {"age": 33, "field": 160.0, "l_min": 1.0, "l_max": 5000.0, "pupil_scale": 2.2, "gain_b": 3}
    p = Parameters.from_dict(old, varjo.PROFILE)
    assert p.version == 3 and p.pupil_correction == pytest.approx(1.1)
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


def test_new_participants_have_dynamics_but_old_files_keep_one_stage(tmp_path):
    # Open issue 26: dynamics on with two constriction stages by default; files written before the stages
    # existed were fitted with one and keep it.
    assert Parameters().dynamics and Parameters().constriction_stages == 2
    import json
    (tmp_path / "old.json").write_text(json.dumps({"version": 3, "dynamics": True, "release": 0.2}))
    assert Parameters.load(tmp_path / "old.json").constriction_stages == 1
    Parameters(constriction_stages=2).save(tmp_path / "new.json", participant_only=True)
    assert Parameters.load(tmp_path / "new.json").constriction_stages == 2


def test_pupil_scale_follows_the_iris_column(tmp_path):
    """Older Varjo Base exports hold the pupil radius (iris column about 6 mm); a later one holds diameters
    (iris about 12 mm), so the reader must not double them."""
    from conftest import write_varjo_recording
    radius = devices.load(write_varjo_recording(tmp_path / "old", [128, 128], pupil_mm=1.6, iris_mm=6.04))
    diameter = devices.load(write_varjo_recording(tmp_path / "new", [128, 128], pupil_mm=3.2, iris_mm=12.3))
    unknown = devices.load(write_varjo_recording(tmp_path / "none", [128, 128], pupil_mm=1.6))    # iris missing
    assert radius.profile.pupil_scale == 2.0 and diameter.profile.pupil_scale == 1.0
    assert unknown.profile.pupil_scale == 2.0
    scaled = lambda r: np.nanmedian(r.pupil_left) * r.profile.pupil_scale
    assert scaled(radius) == pytest.approx(3.2) and scaled(diameter) == pytest.approx(3.2)
    assert varjo.pupil_scale(np.array([np.nan]), np.array([])) == 2.0
