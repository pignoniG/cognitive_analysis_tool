import pytest

from cwtool import calibration


def write(tmp_path, text, name="seq.csv"):
    p = tmp_path / name
    p.write_text(text)
    return p


def test_header_with_names_and_labels(tmp_path):
    seq = calibration.load_sequence(write(tmp_path, (
        "# pseudo-random grey\n"
        "Time (s),Red,Green,Blue,Label\n"
        "0,0,0,0,black\n"
        "6,219,219,219,light\n"
        "12,73,73,73,dark\n")))
    assert [s.label for s in seq.steps] == ["black", "light", "dark"]
    assert [(s.start, s.end) for s in seq.steps] == [(0, 6), (6, 12), (12, 18)]  # last: median length
    assert seq.duration == 18 and seq.name == "seq.csv"


def test_headerless_unit_colours_and_offset_times(tmp_path):
    seq = calibration.load_sequence(write(tmp_path, "10,0,0,0\n13,1,0,0\n16,0,0.5,0\n"))
    assert seq.steps[0].start == 0 and seq.steps[-1].end == 9
    assert seq.steps[1].rgb == (255, 0, 0) and seq.steps[2].rgb == (0, 128, 0)


def test_milliseconds_and_duration_column(tmp_path):
    seq = calibration.load_sequence(write(tmp_path, (
        "t_ms,r,g,b,duration_ms\n0,10,10,10,6000\n6000,200,200,200,10000\n")))
    assert [(s.start, s.end) for s in seq.steps] == [(0, 6), (6, 16)]


def test_bad_files_are_rejected(tmp_path):
    with pytest.raises(ValueError):
        calibration.load_sequence(write(tmp_path, "when,colour\n0,red\n"))
    with pytest.raises(ValueError):
        calibration.load_sequence(write(tmp_path, "0,0,0,0\n0,1,1,1\n"))


def test_locate_finds_start_and_step_length():
    import numpy as np
    seq = calibration.DEFAULT                    # 6 s steps
    start, factor = 12.3, 10 / 6                 # recording used 10 s steps
    t = np.arange(0, 230, 0.01)
    rgb = np.full((len(t), 3), 30.0)             # a dim scene before and after
    for s in calibration.scaled(seq, factor).steps:
        sel = (t >= start + s.start) & (t < start + s.end)
        rgb[sel] = np.array(s.rgb) * 0.9         # recorded levels are lower than nominal
    loc = calibration.locate(t, rgb, seq)
    assert loc.start == pytest.approx(start, abs=0.05)
    assert loc.sequence.duration == pytest.approx(200, abs=0.5)
    assert loc.error < 0.05


def test_locate_gives_up_without_changes():
    import numpy as np
    t = np.arange(0, 10, 0.1)
    assert calibration.locate(t, np.full((len(t), 3), 100.0), calibration.DEFAULT) is None


def test_locate_ignores_tracking_gaps_and_windows_past_the_end():
    # Calibration recording e (September 2026): tracking, and so the video analysis, is missing
    # during most red and blue steps, and the recording ends soon after the sequence. A start near
    # the end used to win, scored on the few seconds of its window inside the recording.
    import numpy as np
    seq = calibration.DEFAULT
    start, factor = 1.8, 10 / 6
    t = np.arange(0, 206, 0.005)
    rgb = np.full((len(t), 3), 45.0)
    for s in calibration.scaled(seq, factor).steps:
        sel = (t >= start + s.start) & (t < start + s.end)
        rgb[sel] = np.array(s.rgb) * 0.9
    lost = ((t > 95) & (t < 120)) | ((t > 158) & (t < 200))
    loc = calibration.locate(t[~lost], rgb[~lost], seq)
    assert loc.start == pytest.approx(start, abs=0.1)
    assert loc.sequence.duration == pytest.approx(200, abs=0.5)
    assert 0.5 < loc.coverage < 0.9
