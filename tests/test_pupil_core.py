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


def test_result_keeps_the_sensor_average_and_the_video_ratio(tmp_path):
    rec = devices.load(write_core_recording(tmp_path / "core", GRAYS, FRAME_TIMES, lux=lambda t: 200.0))
    video = _video(rec)
    r = pipeline.run(rec, video, Parameters(delay=0.0))
    assert np.allclose(r.luminance, r.luminance_sensor * r.luminance_ratio)
    assert np.nanmedian(r.luminance_ratio) == pytest.approx(1.0, abs=0.02)      # a uniform frame
    route = pipeline.luminance_route(r)
    assert route["sensor"] == pytest.approx(np.nanmedian(r.luminance_sensor)) and route["ratio"][0] == pytest.approx(1, abs=0.02)
    sensor_only = pipeline.run(rec, video, Parameters(delay=0.0, lux_use_video=False))
    assert sensor_only.luminance_ratio is None and pipeline.luminance_route(sensor_only)["ratio"] is None
    without_lux = pipeline.run(devices.load(write_core_recording(tmp_path / "nolux", GRAYS, FRAME_TIMES)),
                               video, Parameters())
    assert without_lux.luminance_sensor is None and pipeline.luminance_route(without_lux) is None


def test_ratio_spread():
    assert pipeline.ratio_spread(np.ones(50)) == pytest.approx(1.0)
    assert pipeline.ratio_spread(np.r_[np.full(50, 0.5), np.full(50, 2.0)]) == pytest.approx(4.0)
    assert pipeline.ratio_spread(np.ones(3)) == 0.0             # too few samples to judge


def test_unstable_video_ratio_is_flagged(tmp_path, monkeypatch):
    rec = devices.load(write_core_recording(tmp_path / "core", GRAYS, FRAME_TIMES, lux=lambda t: 200.0))
    video = _video(rec)
    y_w, y_frame = pipeline.relative_luminances(video, Parameters())
    swing = np.where(np.arange(len(y_w)) % 2, 0.4, 2.5)
    monkeypatch.setattr(pipeline, "relative_luminances", lambda v, p: (y_frame * swing, y_frame))
    r = pipeline.run(rec, video, Parameters(delay=0.0))
    assert any("video ratio" in w for w in r.warnings)
    r = pipeline.run(rec, video, Parameters(delay=0.0, lux_use_video=False))
    assert not any("video ratio" in w for w in r.warnings)


def test_without_lux_the_camera_is_used_with_a_warning(tmp_path):
    rec = devices.load(write_core_recording(tmp_path / "core", GRAYS, FRAME_TIMES))
    r = pipeline.run(rec, _video(rec), Parameters())
    assert r.warnings and "lux" in r.warnings[0].lower()
    assert np.isfinite(r.expected_black)


def test_lux_folder_outside_the_recording(tmp_path):
    """One lux folder for all recordings: logs need not be copied into each, nested folders are searched, and
    files that do not overlap the recording are skipped."""
    import shutil
    folder = write_core_recording(tmp_path / "core", GRAYS, FRAME_TIMES, lux=lambda t: 100.0 + 10 * t)
    logs = tmp_path / "lux_logs" / "2026-09"
    logs.mkdir(parents=True)
    shutil.move(str(folder / "1_1_1.csv"), logs / "1_1_1.csv")               # the log leaves the recording
    (logs / "9_9_9.csv").write_text("1500000000000,1,1,1,999\n1500003600000,1,1,1,999\n")   # another day
    rec = devices.load(folder)
    assert rec.lux_values is None                                             # nothing in the recording
    rec = devices.load(folder, lux_folder=tmp_path / "lux_logs")               # found in a subfolder
    assert rec.lux_values is not None and rec.lux_values.max() < 200 and not rec.notes
    assert lux.read_lux(logs, 1_700_000_000.5, 1.0, recursive=False)[0].size > 0
    stale = devices.load(folder, lux_folder=tmp_path / "elsewhere")
    assert stale.lux_values is None and "does not exist" in stale.notes[0]
    (tmp_path / "other").mkdir()
    (tmp_path / "other" / "9_9_9.csv").write_text("1500000000000,1,1,1,999\n1500003600000,1,1,1,999\n")
    none = devices.load(folder, lux_folder=tmp_path / "other")
    assert none.lux_values is None and "No lux readings" in none.notes[0] and "1 log files" in none.notes[0]


def test_lux_files_are_skipped_by_their_time_span(tmp_path):
    from cwtool import lux
    old = tmp_path / "1_1_1.csv"
    old.write_text("1000000000000,1,1,1,5\n1000003600000,1,1,1,6\n")
    new = tmp_path / "1_1_2.csv"
    new.write_text("2000000000000,1,1,1,7\n2000000060000,1,1,1,8\n")
    t, v = lux.read_lux(tmp_path, 2_000_000_000.0, 30.0)
    assert list(v) == [7.0, 8.0] and lux._span(old) == (1_000_000_000.0, 1_000_003_600.0)
    assert lux._span(tmp_path / "missing.csv") is None


def _trim_lux_log(folder, keep):
    import csv
    path = folder / "1_1_1.csv"
    rows = list(csv.reader(open(path, newline="")))
    with open(path, "w", newline="") as f:
        csv.writer(f).writerows(rows[:keep])


def test_delta_pd_is_left_out_where_the_lux_log_ends(tmp_path):
    """A lux log that stops before the recording does not hold its last value: ΔPD is left out after it,
    with a note."""
    frames = np.arange(0, 20, 1 / 30)
    folder = write_core_recording(tmp_path / "core", [128] * len(frames), frames, lux=lambda t: 200.0)
    _trim_lux_log(folder, 60)                       # readings from -1 to 4.9 s
    rec = devices.load(folder)
    r = pipeline.run(rec, _video(rec), Parameters())
    assert np.isfinite(r.cw[r.cw_time < 4]).all()
    assert np.isnan(r.cw[r.cw_time > 6]).all()
    assert r.gap_fraction > 0.6
    assert any("luminance is unknown" in w for w in r.warnings)


def test_delta_pd_is_left_out_without_analysed_video(tmp_path):
    """With the gaze lost for 3 s (no analysed video) but the pupil tracked, the luminance there is unknown."""
    import csv
    frames = np.arange(0, 10, 1 / 30)
    folder = write_core_recording(tmp_path / "core", [128] * len(frames), frames, lux=lambda t: 200.0)
    path = next(folder.glob("exports/*/gaze_positions.csv"))
    rows = list(csv.reader(open(path, newline="")))
    for r in rows[1:]:
        if 4.0 <= float(r[0]) - 1000.5 < 7.0:
            r[2] = "0.2"                               # low confidence: no gaze
    with open(path, "w", newline="") as f:
        csv.writer(f).writerows(rows)
    rec = devices.load(folder)
    assert np.isfinite(rec.pupil_left[(rec.time > 4.5) & (rec.time < 6.5)]).all()
    r = pipeline.run(rec, _video(rec), Parameters())
    assert np.isnan(r.cw[(r.cw_time > 4.5) & (r.cw_time < 6.5)]).all()
    assert np.isfinite(r.cw[(r.cw_time > 1) & (r.cw_time < 3.5)]).all()
    # Without the video the sensor alone gives the luminance, which is known throughout.
    r = pipeline.run(rec, _video(rec), Parameters(lux_use_video=False))
    assert np.isfinite(r.cw[(r.cw_time > 1) & (r.cw_time < 9)]).all()


def test_covered():
    t = np.array([0.0, 0.4, 1.0, 2.0, 3.6, 5.0])
    assert pipeline.covered(t, [0.2, 0.6, 1.0, 3.0, 3.5], 0.5).tolist() == [True, True, True, False, True, False]
    assert not pipeline.covered(t, [], 0.5).any()


def test_video_ratio_is_bounded(tmp_path):
    """A gaze area far brighter than a nearly black frame cannot multiply the sensor's luminance without bound."""
    frames = np.arange(0, 6, 1 / 30)
    folder = write_core_recording(tmp_path / "core", [128] * len(frames), frames, lux=lambda t: 200.0)
    rec = devices.load(folder)
    video = _video(rec)
    video.frame_lin[:] = video.frame_lin / 50          # whole frame 50× darker than the gaze area
    r = pipeline.run(rec, video, Parameters(fixation_weight=1.0))
    assert np.nanmax(r.luminance_ratio) == pytest.approx(10.0)
    assert any("reached its bound" in w for w in r.warnings)
    free = pipeline.run(rec, video, Parameters(fixation_weight=1.0, lux_ratio_limit=0))
    assert np.nanmax(free.luminance_ratio) == pytest.approx(50.0, rel=0.05)


def test_lens_field_of_view_includes_the_distortion():
    from cwtool.devices.common import lens_fov, pinhole_fov

    # world.intrinsics of the 29 and 30 September 2026 recordings (1280x720, "radial", 8 coefficients)
    k = [[794.3311, 0.0, 633.0104], [0.0, 793.529, 397.3693], [0.0, 0.0, 1.0]]
    d = [-0.375863, 0.164333, 0.000122, 0.000134, 0.033437, 0.082352, -0.082258, 0.144634]
    h, v = lens_fov(k, d, (1280, 720))
    # Pupil Labs list 103° × 54° for the wide-angle lens at this resolution; the pinhole value is 78° × 49°
    assert h == pytest.approx(103.0, abs=1.0) and v == pytest.approx(54.0, abs=1.0)
    assert pinhole_fov(k, (1280, 720))[0] < 80
    # no distortion: the pinhole value
    assert lens_fov(k, [0, 0, 0, 0, 0], (1280, 720)) == pytest.approx(pinhole_fov(k, (1280, 720)), abs=0.1)
    # unusable coefficients give None, not a wrong number
    assert lens_fov(k, [50.0, 0, 0, 0, 0], (1280, 720)) is None or lens_fov(k, [50.0, 0, 0, 0, 0], (1280, 720))[0] < 179


def test_core_reader_uses_the_lens_field_of_view(tmp_path):
    import msgpack
    from cwtool.devices import pupil_core

    k = [[794.3311, 0.0, 633.0104], [0.0, 793.529, 397.3693], [0.0, 0.0, 1.0]]
    d = [-0.375863, 0.164333, 0.000122, 0.000134, 0.033437, 0.082352, -0.082258, 0.144634]
    (tmp_path / "world.intrinsics").write_bytes(msgpack.packb(
        {"version": 1, "(1280, 720)": {"camera_matrix": k, "dist_coefs": [d], "resolution": [1280, 720],
                                       "cam_type": "radial"}}))
    h, v = pupil_core.camera_fov(tmp_path, (1280, 720))
    assert h == pytest.approx(103.0, abs=1.0) and v == pytest.approx(54.0, abs=1.0)
    assert pupil_core.camera_fov(tmp_path / "missing", (1280, 720)) == pupil_core.DEFAULT_CAMERA_FOV
