"""Tests of the calibration presenter's run file with its gaze check: the light steps are read as the sequence, the gaze
check's rows are not (they change no light) and are read as targets, and the log alignment leaves them out."""

import pytest

from cwtool import alignment, calibration

HEADER = ("time,duration,r,g,b,label,index,source_index,planned_start_s,planned_duration_s,onset_unix_ms,Y,completed,"
          "phase,target_u,target_v,target_x,target_y,target_az_deg,target_el_deg")


def _run_file(path, vr=False):
    rows = ["# tool: test", "# gaze_check: true", HEADER,
            "0,5,200,200,200,Light,1,1,0,5,1700000000000,0.6,true,light,,,,,,",
            "5,5,20,20,20,Dark,2,2,5,5,1700000005000,0.01,true,light,,,,,,"]
    rows.append("10,1,20,20,20,Gaze check cue (tone),3,,10,1,1700000010000,0.01,true,gaze,,,,,,")   # tone: no target
    for k, (u, v) in enumerate([(0, 0), (-1, -1), (1, 1)]):
        place = f",,{u * 15},{-v * 12}" if vr else f"{0.5 + u * 0.35},{0.5 + v * 0.35},,"
        rows.append(f"{11 + 2 * k},2,128,128,128,Gaze target {k + 1},{4 + k},,{11 + 2 * k},2,{1700000011000 + 2000 * k},"
                    f"0.2,true,gaze,{u},{v},{place}")
    path.write_text("\n".join(rows) + "\n")
    return path


def test_the_light_sequence_leaves_the_gaze_check_out(tmp_path):
    seq = calibration.load_sequence(_run_file(tmp_path / "calibration_run_x.csv"))
    assert [s.label for s in seq.steps] == ["Light", "Dark"]
    assert seq.duration == pytest.approx(10.0)            # the last light step keeps its own duration


def test_the_gaze_targets_are_read(tmp_path):
    screen = calibration.gaze_targets(_run_file(tmp_path / "s.csv"))
    assert [(t.u, t.v) for t in screen] == [(0, 0), (-1, -1), (1, 1)]      # the tone's row has no target
    assert screen[1].screen == pytest.approx((0.15, 0.15)) and screen[1].direction is None
    assert screen[0].onset_unix == pytest.approx(1700000011.0) and screen[0].duration == 2
    vr = calibration.gaze_targets(_run_file(tmp_path / "v.csv", vr=True))
    assert vr[2].direction == pytest.approx((15, -12)) and vr[2].screen is None
    old = tmp_path / "old.csv"
    old.write_text("time,r,g,b,label,onset_unix_ms\n0,1,1,1,a,1700000000000\n")
    assert calibration.gaze_targets(old) == []


def test_the_alignment_ignores_the_gaze_check(tmp_path):
    _run_file(tmp_path / "calibration_run_x.csv")
    onsets, source = alignment.log_onsets(tmp_path)
    assert onsets == pytest.approx([1700000000.0, 1700000005.0]) and "calibration_run_x" in source


def _gaze_first_run_file(path):
    """A run file as the presenter writes it from November 2026: the gaze check first, then the light steps."""
    rows = ["# tool: test", "# gaze_check: true", HEADER,
            "0,1,128,128,128,Gaze check cue (tone),1,,0,1,1700000000000,0.2,true,gaze,,,,,,"]
    for k, (u, v) in enumerate([(0, 0), (-1, -1), (1, 1)]):
        rows.append(f"{1 + 2 * k},2,128,128,128,Gaze target {k + 1},{2 + k},,{1 + 2 * k},2,{1700000001000 + 2000 * k},"
                    f"0.2,true,gaze,{u},{v},{0.5 + u * 0.35},{0.5 + v * 0.35},,")
    rows += ["7,5,200,200,200,Light,5,1,7,5,1700000007000,0.6,true,light,,,,,,",
             "12,6,20,20,20,Dark,6,2,12,6,1700000012000,0.01,true,light,,,,,,"]
    path.write_text("\n".join(rows) + "\n")
    return path


def test_a_gaze_check_before_the_light_steps_is_left_out_of_the_sequence_and_its_start(tmp_path):
    path = _gaze_first_run_file(tmp_path / "calibration_run_x.csv")
    seq = calibration.load_sequence(path)
    assert [(s.label, s.start, s.end) for s in seq.steps] == [("Light", 0.0, 5.0), ("Dark", 5.0, 11.0)]
    assert calibration.run_start_unix(path) == pytest.approx(1700000007.0)     # the first light step, not the tone
    assert [t.onset_unix for t in calibration.gaze_targets(path)] == pytest.approx([1700000001.0, 1700000003.0, 1700000005.0])
    onsets, _ = alignment.log_onsets(tmp_path)
    assert onsets == pytest.approx([1700000007.0, 1700000012.0])
    assert calibration.run_start_unix(_run_file(tmp_path / "end.csv")) == pytest.approx(1700000000.0)   # the earlier order
