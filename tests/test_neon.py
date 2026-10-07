"""Tests of the Pupil Labs Neon reader and of the pipeline with a lux sensor or a fixed-exposure camera."""

import numpy as np
import pytest

from cwtool import devices, pipeline
from cwtool.devices.common import events_from_markers
from cwtool.params import Parameters, VideoSettings
from cwtool.video import analyse_video
from conftest import write_neon_recording

FRAME_TIMES = np.arange(90) / 30          # 3 s of scene video at 30 fps
GRAYS = [40] * 45 + [220] * 45


@pytest.mark.parametrize("layout", ["cloud", "native"])
def test_reader(tmp_path, layout):
    folder = write_neon_recording(tmp_path / "neon", GRAYS, FRAME_TIMES, layout=layout,
                                  not_worn=[(1.0, 1.2)], events=[(0.5, "Task.begin"), (2.0, "Task.end")],
                                  blinks=[(2.4, 2.5)])
    assert devices.detect(folder) == "pupil_neon"
    rec = devices.load(folder)
    p = rec.profile
    assert p.pupil_unit == "mm" and p.pupil_scale == 1.0 and p.native_rate == 200
    assert p.luminance_source == "lux_sensor" and not p.circular_scene
    assert p.adapting_field == (200.0, 135.0)
    assert p.field_of_view[0] == pytest.approx(90.0)          # from the camera matrix
    assert rec.epoch_start == pytest.approx(1_700_000_000.25)  # the first scene frame
    assert rec.time[0] == pytest.approx(-0.25) and rec.scene_frame_times[0] == 0
    assert np.nanmedian(rec.pupil_left) == pytest.approx(5.0)
    assert np.nanmedian(rec.pupil_right) == pytest.approx(5.2)
    not_worn = (rec.time > 1.01) & (rec.time < 1.19)
    assert np.isnan(rec.pupil_left[not_worn]).all() and np.isnan(rec.gaze[not_worn]).all()
    ok = np.isfinite(rec.gaze[:, 0])
    assert np.allclose(rec.gaze[ok], [0.5, 0.25])            # px / scene size, origin top left
    assert [(e.label, round(e.start, 3), round(e.end, 3)) for e in rec.events] == [("Task", 0.5, 2.0)]
    in_blink = (rec.time > 2.35) & (rec.time < 2.55)
    assert np.isnan(rec.pupil_left[in_blink]).all() == (layout == "cloud")   # blinks: Cloud export only


def test_pipeline_with_lux_sensor(tmp_path):
    folder = write_neon_recording(tmp_path / "neon", GRAYS, FRAME_TIMES, lux=lambda t: 300.0)
    rec = devices.load(folder)
    assert rec.lux_values is not None and np.allclose(rec.lux_values, 300.0)
    video = analyse_video(rec.scene_video, rec.time, rec.gaze, VideoSettings().for_recording(rec),
                          frame_times=rec.scene_frame_times)
    res = pipeline.run(rec, video, Parameters(analysis_rate=0))
    assert res.rate == 200 and np.isnan(res.expected_black)
    assert np.isfinite(res.cw).any()


def test_native_without_eye_state_explains_what_to_do(tmp_path):
    folder = write_neon_recording(tmp_path / "neon", GRAYS, FRAME_TIMES, layout="native")
    for f in folder.glob("eye_state*"):
        f.unlink()
    with pytest.raises(FileNotFoundError, match="eye state estimation was off"):
        devices.load(folder)


def test_markers_become_events():
    ev = events_from_markers([0, 1, 2, 3, 5, 6], ["recording.begin", "Rest", "Task_start", "Task_stop",
                                                  "Recall", "Rest"], end=8, ignore=("recording.begin",))
    assert [(e.label, e.start, e.end) for e in ev] == [
        ("Rest", 1, 5), ("Task", 2, 3), ("Recall", 5, 6), ("Rest", 6, 8)]


def _analysed(folder):
    rec = devices.load(folder)
    video = analyse_video(rec.scene_video, rec.time, rec.gaze, VideoSettings().for_recording(rec),
                          frame_times=rec.scene_frame_times)
    return rec, video


def _level(res, t):
    return res.luminance[np.argmin(np.abs(res.time - t))]


def test_fixed_exposure_camera_without_lux(tmp_path):
    rec, video = _analysed(write_neon_recording(tmp_path / "neon", GRAYS, FRAME_TIMES))
    assert rec.lux_values is None
    res = pipeline.run(rec, video, Parameters(camera_exposure="fixed", camera_white=1000.0))
    assert res.luminance_mode == "camera, fixed exposure" and np.isnan(res.expected_black)
    assert not any("lux" in w for w in res.warnings)
    # Uniform frames: luminance = full scale × decoded code value (MPEG-4 shifts levels slightly).
    assert _level(res, 0.8) == pytest.approx(1000 * (40 / 255) ** 2.2, rel=0.15)
    assert _level(res, 2.5) == pytest.approx(1000 * (220 / 255) ** 2.2, rel=0.05)
    # Twice the exposure time saturates at half the luminance.
    half = pipeline.run(rec, video, Parameters(camera_exposure="fixed", camera_white=1000.0,
                                               camera_reference_ms=10, camera_exposure_ms=20))
    assert _level(half, 2.5) == pytest.approx(_level(res, 2.5) / 2, rel=1e-6)


def test_automatic_exposure_without_lux_suggests_fixed(tmp_path):
    rec, video = _analysed(write_neon_recording(tmp_path / "neon", GRAYS, FRAME_TIMES))
    res = pipeline.run(rec, video, Parameters())
    assert res.luminance_mode == "camera, relative"
    assert any("'fixed'" in w for w in res.warnings)


def test_saturated_gaze_area_is_reported(tmp_path):
    rec, video = _analysed(write_neon_recording(tmp_path / "neon", [255] * 90, FRAME_TIMES))
    res = pipeline.run(rec, video, Parameters(camera_exposure="fixed"))
    assert any("saturated" in w for w in res.warnings)


def test_camera_calibration_from_lux(tmp_path):
    white, p = 800.0, Parameters()
    level = lambda t: (40 if t < 1.5 else 220) / 255
    # A fixed-exposure camera: the sensor's average luminance is proportional to the frame's.
    lux = lambda t: (white * level(t) ** 2.2 * p.lux_solid_angle - p.lux_offset) / p.lux_gain
    rec, video = _analysed(write_neon_recording(tmp_path / "neon", GRAYS, FRAME_TIMES, lux=lux))
    cal = pipeline.calibrate_camera(rec, video, p)
    assert cal.white == pytest.approx(white, rel=0.1)
    # The MPEG-4 test video decodes grey 40 as 37 and 220 as 216, so the halves differ by ~15 %.
    assert cal.spread < 2 and not cal.notes

    # With automatic exposure the frame stays mid-grey while the light changes: flagged.
    rec, video = _analysed(write_neon_recording(tmp_path / "auto", [128] * 90, FRAME_TIMES,
                                                lux=lambda t: 50 if t < 1.5 else 800))
    assert pipeline.calibrate_camera(rec, video, p).notes


def test_unused_parameters_per_device(tmp_path, varjo_folder):
    from cwtool.params import unused_parameters
    varjo = devices.load(varjo_folder)
    with_lux = devices.load(write_neon_recording(tmp_path / "a", GRAYS, FRAME_TIMES, lux=lambda t: 300.0))
    without = devices.load(write_neon_recording(tmp_path / "b", GRAYS, FRAME_TIMES))
    p = Parameters()
    assert unused_parameters(None, p) == set()
    assert {"lux_gain", "camera_exposure"} <= unused_parameters(varjo, p)
    assert "l_max" not in unused_parameters(varjo, p) and "field_radius" not in unused_parameters(varjo, p)
    assert {"l_min", "l_max", "camera_exposure", "field_radius"} <= unused_parameters(with_lux, p)
    assert "lux_gain" not in unused_parameters(with_lux, p)
    assert {"lux_gain", "camera_white"} <= unused_parameters(without, p)
    assert {"lux_gain", "l_max"} <= unused_parameters(without, Parameters(camera_exposure="fixed"))
    assert "camera_white" not in unused_parameters(without, Parameters(camera_exposure="fixed"))
