import numpy as np
import pytest

from cwtool import devices, pipeline
from cwtool.devices import tobii_g3
from cwtool.params import Parameters, VideoSettings
from cwtool.video import analyse_video
from conftest import write_tobii_g3_recording

GRAYS = [40] * 50 + [220] * 50          # 4 s at 25 fps


def test_reader(tmp_path):
    folder = write_tobii_g3_recording(tmp_path / "g3", GRAYS, untracked=[(1.0, 1.2)], left_only=[(2.0, 2.4)],
                                      events=[(0.5, "Task.begin"), (3.0, "Task.end")])
    assert devices.detect(folder) == "tobii_g3"
    rec = devices.load(folder)
    p = rec.profile
    assert p.experimental and p.pupil_unit == "mm" and p.pupil_scale == 1.0 and p.native_rate == 50
    assert p.luminance_source == "lux_sensor" and not p.circular_scene and p.adapting_field == (200.0, 135.0)
    assert p.field_of_view[0] == pytest.approx(90.0)                 # from the camera calibration
    assert rec.epoch_start == pytest.approx(1790589600.0)            # 2026-09-28T10:00:00Z
    assert np.nanmedian(rec.pupil_left) == pytest.approx(4.0) and np.nanmedian(rec.pupil_right) == pytest.approx(4.2)
    untracked = (rec.time > 1.01) & (rec.time < 1.19)
    assert np.isnan(rec.pupil_left[untracked]).all() and np.isnan(rec.gaze[untracked]).all()
    one_eye = (rec.time > 2.05) & (rec.time < 2.35)
    assert np.isfinite(rec.pupil_left[one_eye]).all() and np.isnan(rec.pupil_right[one_eye]).all()
    ok = np.isfinite(rec.gaze[:, 0])
    assert np.allclose(rec.gaze[ok], [0.25, 0.75])                    # origin top left, as recorded
    assert [(e.label, e.start, e.end) for e in rec.events] == [("Task", 0.5, 3.0)]   # syncport ignored
    assert rec.scene_video.name == "scenevideo.mp4" and rec.scene_frame_times is None


def test_gaze_flip_and_nominal_field_of_view(tmp_path):
    folder = write_tobii_g3_recording(tmp_path / "g3", GRAYS, calibration=False)
    rec = tobii_g3.load(folder, flip_gaze_y=True)
    ok = np.isfinite(rec.gaze[:, 0])
    assert np.allclose(rec.gaze[ok], [0.25, 0.25])
    assert rec.profile.field_of_view == tobii_g3.SCENE_FOV


def test_pipeline_with_lux_and_experimental_warning(tmp_path):
    folder = write_tobii_g3_recording(tmp_path / "g3", GRAYS, lux=lambda t: 300.0)
    rec = devices.load(folder)
    assert rec.lux_values is not None and np.allclose(rec.lux_values, 300.0)
    video = analyse_video(rec.scene_video, rec.time, rec.gaze, VideoSettings().for_recording(rec))
    # The video is dark (grey 40) for its first 2 s, timed by its frame rate.
    assert video.fixation_rgb[video.time < 1.5, 0].mean() == pytest.approx(40, abs=5)
    res = pipeline.run(rec, video, Parameters())
    assert res.luminance_mode == "lux sensor" and np.isfinite(res.cw).any()
    assert res.warnings[0].startswith("Experimental support for tobii_g3")


def test_neon_is_flagged_experimental_and_others_are_not(tmp_path, varjo_folder):
    from conftest import write_neon_recording
    assert devices.load(write_neon_recording(tmp_path / "n", [40] * 30, np.arange(30) / 30)).profile.experimental
    assert not devices.load(varjo_folder).profile.experimental
