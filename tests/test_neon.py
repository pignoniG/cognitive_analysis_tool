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
