"""Tests of the gaze check: the dot of each place is found in the scene video, the gaze is compared with it, and the
offset that moves the gaze onto the dots is recovered."""

import cv2
import numpy as np
import pytest

from cwtool import gazecheck
from cwtool.recording import DeviceProfile, Recording

EPOCH = 1_700_000_000.0
FPS = 30
SIZE = (320, 240)
FOV = (100.0, 75.0)
PLACES = [(0, 0), (-1, -1), (0, -1), (1, -1), (1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0)]
FIRST = 5.0          # s: the first place's onset


def _dot_xy(u, v):
    return 0.5 + 0.3 * u, 0.5 + 0.3 * v


def _write(folder, offset=(2.0, -1.5), lost=(), noise=0.004, moving=False):
    """A recording whose video shows the gaze check's dot and whose gaze is the dot turned back by ``offset`` (deg; right,
    down), as a tracker turned on the head would see it. Places in ``lost`` show no dot."""
    folder.mkdir(parents=True, exist_ok=True)
    w, h = SIZE
    total = FIRST + 2 * len(PLACES) + 2
    writer = cv2.VideoWriter(str(folder / "scene.avi"), cv2.VideoWriter_fourcc(*"MJPG"), FPS, (w, h))
    rng = np.random.default_rng(0)
    for n in range(int(total * FPS)):
        t = n / FPS
        frame = np.full((h, w, 3), 128, np.uint8)
        frame[:, : w // 6] = 90                       # something in the background that does not move
        k = int((t - FIRST) // 2)
        if 0 <= k < len(PLACES) and k not in lost:
            x, y = _dot_xy(*PLACES[k])
            if moving:
                x += 0.05 * np.sin(t * 3)
            cv2.circle(frame, (int(x * w), int(y * h)), 6, (0, 0, 0), -1)
            cv2.circle(frame, (int(x * w), int(y * h)), 2, (255, 255, 255), -1)
        writer.write(frame)
    writer.release()
    rows = ["# tool: test", "time,duration,r,g,b,label,onset_unix_ms,phase,target_u,target_v,target_x,target_y,target_az_deg,"
            "target_el_deg", f"0,{FIRST},128,128,128,Gray,{EPOCH * 1000:.0f},light,,,,,,"]
    for k, (u, v) in enumerate(PLACES):
        rows.append(f"{FIRST + 2 * k},2,128,128,128,Gaze target {k + 1},{(EPOCH + FIRST + 2 * k) * 1000:.0f},gaze,{u},{v},,,"
                    f"{u * 15},{-v * 12}")
    (folder / "calibration_run_test.csv").write_text("\n".join(rows) + "\n")
    time = np.arange(0, total, 1 / 100)
    gaze = np.full((len(time), 2), np.nan)
    for k, (u, v) in enumerate(PLACES):
        inside = (time >= FIRST + 2 * k + 0.3) & (time < FIRST + 2 * k + 2)
        seen = gazecheck.shift_gaze(np.array([_dot_xy(u, v)]), (-offset[0], -offset[1]), FOV)[0]
        gaze[inside] = seen + rng.normal(0, noise, (inside.sum(), 2))
    profile = DeviceProfile(name="varjo", pupil_unit="mm", pupil_scale=1.0, luminance_source="display", field_of_view=FOV)
    return Recording(name="t", profile=profile, folder=folder, time=time, epoch_start=EPOCH,
                     pupil_left=np.full(len(time), 4.0), pupil_right=np.full(len(time), 4.0), gaze=gaze,
                     scene_video=folder / "scene.avi")


def test_the_offset_is_recovered(tmp_path):
    rec = _write(tmp_path / "rec", offset=(2.0, -1.5))
    result, message = gazecheck.check(rec)
    assert result is not None, message
    assert result.found == 9 and result.source == "calibration_run_test.csv"
    for p in result.places:
        assert p.dot == pytest.approx(_dot_xy(p.u, p.v), abs=0.01)
    assert result.offset_deg == pytest.approx((2.0, -1.5), abs=0.3)          # right and up
    assert result.offset[0] > 0 and result.offset[1] < 0
    assert result.error_before_deg > 3 * result.error_after_deg
    assert result.spread_deg < 1.0 and not result.notes
    assert "9 of 9 places" in result.summary()
    import json
    saved = json.loads(json.dumps(result.as_dict()))                       # goes into the export as it is
    assert saved["found"] == 9 and len(saved["places"]) == 9


def test_places_without_a_dot_are_left_out(tmp_path):
    rec = _write(tmp_path / "rec", lost=(2, 5))
    result, _ = gazecheck.check(rec)
    assert result.found == 7 and [p.index for p in result.places if p.dot is None] == [3, 6]
    assert any("not clear" in n for n in result.notes)
    assert result.offset_deg == pytest.approx((2.0, -1.5), abs=0.3)


def test_no_run_file_no_check(tmp_path):
    rec = _write(tmp_path / "rec")
    (tmp_path / "rec" / "calibration_run_test.csv").unlink()
    result, message = gazecheck.check(rec)
    assert result is None and "no calibration run file" in message


def test_a_run_file_without_a_gaze_check_is_not_used(tmp_path):
    rec = _write(tmp_path / "rec")
    (tmp_path / "rec" / "calibration_run_test.csv").write_text(
        f"time,r,g,b,label,onset_unix_ms\n0,128,128,128,Gray,{EPOCH * 1000:.0f}\n")
    assert gazecheck.check(rec)[0] is None



def test_the_offset_found_puts_the_gaze_on_the_dots(tmp_path):
    rec = _write(tmp_path / "rec", offset=(2.0, -1.5))
    first, _ = gazecheck.check(rec)
    total = first.total_offset_deg()
    moved = gazecheck.apply_offset(rec, total)
    assert moved.gaze_offset == pytest.approx(total) and any("gaze offset" in n for n in moved.notes)
    again, _ = gazecheck.check(moved)
    assert again.applied_deg == pytest.approx(total)
    assert again.error_before_deg < 0.5 and max(abs(v) for v in again.offset_deg) < 0.3
    assert again.total_offset_deg() == pytest.approx(total, abs=0.3)
    assert "applied" in again.summary()


def test_the_session_offset_is_saved_with_the_recording_and_applied_on_reading(tmp_path):
    from cwtool import devices
    from conftest import write_varjo_recording
    folder = write_varjo_recording(tmp_path / "varjo", [128] * 4)
    plain = devices.load(folder)
    assert plain.gaze_offset is None and gazecheck.load_offset(folder) is None
    gazecheck.save_offset(folder, (2.0, -1.0))
    assert (folder / gazecheck.OFFSET_FILE).exists() and gazecheck.load_offset(folder) == (2.0, -1.0)
    moved = devices.load(folder)
    assert moved.gaze_offset == (2.0, -1.0)
    ok = np.isfinite(plain.gaze[:, 0])
    assert (moved.gaze[ok, 0] > plain.gaze[ok, 0]).all() and (moved.gaze[ok, 1] < plain.gaze[ok, 1]).all()
    # the same angle is the same shift at the centre: 2° of a 120° field is about 1.4 % of the width there
    assert np.allclose(gazecheck.shift_gaze(np.array([[0.5, 0.5]]), (2.0, 0.0), (120.0, 105.0))[0, 0], 0.5 + np.tan(np.radians(2)) / (2 * np.tan(np.radians(60))))
    assert devices.load(folder, gaze_offset=(0.0, 0.0)).gaze_offset is None            # overridden for one reading
    gazecheck.save_offset(folder, None)
    assert not (folder / gazecheck.OFFSET_FILE).exists()
