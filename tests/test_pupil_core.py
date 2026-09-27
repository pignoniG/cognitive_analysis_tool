import numpy as np
import pytest

from cwtool import devices, lux, pipeline
from cwtool.devices import pupil_core
from cwtool.params import Parameters, VideoSettings
from cwtool.video import analyse_video
from conftest import write_core_recording

# 30 frames, with a 0.5 s capture gap after frame 4 (as at the start of the real sample).
FRAME_TIMES = np.r_[np.arange(5) / 30, 0.5 + 5 / 30 + np.arange(25) / 30]
GRAYS = [40] * 5 + [220] * 25


def _video(rec):
    return analyse_video(rec.scene_video, rec.time, rec.gaze, VideoSettings().for_recording(rec),
                         frame_times=rec.scene_frame_times)


def test_reader(tmp_path):
    folder = write_core_recording(tmp_path / "core", GRAYS, FRAME_TIMES, low_confidence=[(0.3, 0.4)])
    assert devices.detect(folder) == "pupil_core"
    rec = devices.load(folder)
    p = rec.profile
    assert p.pupil_unit == "mm" and p.pupil_scale == 1.0 and p.native_rate == 200
    assert p.luminance_source == "lux_sensor" and not p.circular_scene
    assert p.adapting_field == (200.0, 135.0)
    assert rec.epoch_start == pytest.approx(1_700_000_000.5)
    assert rec.scene_frame_times[0] == 0 and rec.scene_frame_times[5] == pytest.approx(0.5 + 5 / 30)
    assert np.nanmedian(rec.pupil_left) == pytest.approx(6.0)
    low = (rec.time > 0.31) & (rec.time < 0.39)
    assert np.isnan(rec.pupil_left[low]).all() and np.isnan(rec.gaze[low]).all()
    assert np.allclose(rec.gaze[~low & np.isfinite(rec.gaze[:, 0])], 0.5)   # y flipped: 1 - 0.5
    assert rec.lux_values is None


def test_uneven_frames_are_matched_by_timestamp(tmp_path):
    rec = devices.load(write_core_recording(tmp_path / "core", GRAYS, FRAME_TIMES))
    res = _video(rec)
    level = lambda t: res.fixation_rgb[np.argmin(np.abs(res.time - t)), 0]
    # Between 0.2 and 0.6 s the camera captured nothing: frame 4 (dark) is nearest until
    # halfway into the gap. A fixed 30 fps clock would show the bright frames from 0.17 s.
    assert level(0.25) == pytest.approx(40, abs=4)
    assert level(0.75) == pytest.approx(220, abs=4)


def test_cache_depends_on_frame_times(tmp_path):
    from cwtool.video import VideoResult
    rec = devices.load(write_core_recording(tmp_path / "core", GRAYS, FRAME_TIMES))
    s = VideoSettings().for_recording(rec)
    _video(rec).save(rec.folder, s, rec.scene_video, rec.scene_frame_times)
    assert VideoResult.load_cached(rec.folder, s, rec.scene_video, rec.scene_frame_times) is not None
    assert VideoResult.load_cached(rec.folder, s, rec.scene_video, None) is None
    assert VideoResult.load_cached(rec.folder, s, rec.scene_video, rec.scene_frame_times + 0.01) is None
    _video(rec).save(rec.folder, s, rec.scene_video, rec.scene_frame_times, rec.gaze)
    assert VideoResult.load_cached(rec.folder, s, rec.scene_video, rec.scene_frame_times, rec.gaze) is not None
    assert VideoResult.load_cached(rec.folder, s, rec.scene_video, rec.scene_frame_times, rec.gaze + 0.01) is None


def test_2d_pixels_fall_back_to_fitted_scale(tmp_path):
    folder = write_core_recording(tmp_path / "core", GRAYS, FRAME_TIMES)
    rec = pupil_core.load(folder, pupil_measure="2d")
    assert rec.profile.pupil_unit == "px" and rec.profile.pupil_scale is None
    assert np.nanmedian(rec.pupil_left) == pytest.approx(48.0)


def test_lux_log_reading_and_calibration(tmp_path):
    folder = write_core_recording(tmp_path / "core", GRAYS, FRAME_TIMES, lux=lambda t: 100.0 + 10 * t)
    assert lux.find_lux_folder(folder) == folder
    rec = devices.load(folder)
    assert rec.lux_values is not None
    assert rec.lux_time[0] == pytest.approx(-1.0, abs=0.01)
    assert rec.lux_values[np.argmin(np.abs(rec.lux_time - 0.5))] == pytest.approx(105.0, abs=0.1)
    assert lux.average_luminance(np.array([100.0]), 1.706061, 0.66935, 2.2)[0] == pytest.approx(77.85, abs=0.01)


def test_pipeline_with_lux_sensor(tmp_path):
    folder = write_core_recording(tmp_path / "core", GRAYS, FRAME_TIMES, lux=lambda t: 200.0)
    rec = devices.load(folder)
    video = _video(rec)
    params = Parameters(delay=0.0)
    r = pipeline.run(rec, video, params)
    avg = lux.average_luminance(np.array([200.0]), params.lux_gain, params.lux_offset, params.lux_solid_angle)[0]
    # A uniform frame: the gaze-weighted and whole-frame relative luminance are equal, so L = avgL.
    assert np.nanmedian(r.luminance) == pytest.approx(avg, rel=0.02)
    assert np.isnan(r.expected_black) and not r.warnings
    sensor_only = pipeline.run(rec, video, Parameters(delay=0.0, lux_use_video=False))
    assert np.allclose(sensor_only.luminance, avg, rtol=0.02)


def test_without_lux_the_camera_is_used_with_a_warning(tmp_path):
    rec = devices.load(write_core_recording(tmp_path / "core", GRAYS, FRAME_TIMES))
    r = pipeline.run(rec, _video(rec), Parameters())
    assert r.warnings and "lux" in r.warnings[0].lower()
    assert np.isfinite(r.expected_black)
