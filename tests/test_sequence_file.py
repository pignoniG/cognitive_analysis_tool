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
    seq = calibration.STAIRCASE_20               # 6 s steps
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
    assert calibration.locate(t, np.full((len(t), 3), 100.0), calibration.STAIRCASE_20) is None


def test_locate_ignores_tracking_gaps_and_windows_past_the_end():
    # Calibration recording e (September 2026): tracking, and so the video analysis, is missing
    # during most red and blue steps, and the recording ends soon after the sequence. A start near
    # the end used to win, scored on the few seconds of its window inside the recording.
    import numpy as np
    seq = calibration.STAIRCASE_20
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


# The presenter's default sequence in the orders its own JavaScript gives (docs/calibration-tool/index.html, run in
# Node in October 2026): the preset (seed "calibration") and a run scrambled for participant "P01".
PRESET_ORDER = ['Gray 255', 'Gray 219', 'Black', 'Blue 255', 'Black', 'Green 191', 'Black', 'Red 191', 'Black',
                'Blue 191', 'Black', 'Red 64', 'Gray 182', 'Black', 'Green 128', 'Gray 36', 'Gray 146', 'Black',
                'Red 128', 'Gray 0', 'Black', 'Green 255', 'Black', 'Blue 64', 'Gray 73 (repeat)', 'Black', 'Red 255',
                'Gray 73', 'Black', 'Blue 128', 'Gray 182 (repeat)', 'Black', 'Green 64', 'Gray 109']
P01_ORDER = ['Black', 'Green 64', 'Gray 73', 'Black', 'Blue 64', 'Black', 'Red 255', 'Gray 219', 'Gray 146',
             'Gray 182 (repeat)', 'Gray 73 (repeat)', 'Gray 36', 'Black', 'Green 191', 'Gray 255', 'Black', 'Red 64',
             'Black', 'Red 128', 'Gray 109', 'Black', 'Blue 191', 'Black', 'Blue 128', 'Black', 'Red 191', 'Black',
             'Green 128', 'Black', 'Green 255', 'Gray 0', 'Gray 182', 'Black', 'Blue 255']


def test_default_is_the_presenters_full_calibration():
    seq = calibration.DEFAULT
    assert [s.label for s in seq.steps] == PRESET_ORDER
    assert len(seq.steps) == 34 and seq.duration == 291
    lengths = {s.label: s.end - s.start for s in seq.steps}
    assert lengths["Gray 0"] == 20 and lengths["Gray 255"] == 12 and lengths["Blue 64"] == 8
    # Every colour follows its own black step, which moves with it.
    for prev, step in zip(seq.steps, seq.steps[1:]):
        assert step.linked == (step.label.split()[0] in ("Red", "Green", "Blue"))
        if step.linked:
            assert prev.label == "Black"
    assert all(a.end == b.start for a, b in zip(seq.steps, seq.steps[1:]))


def test_participant_order_matches_the_presenter():
    seq = calibration.scrambled(calibration.DEFAULT, "P01")
    assert [s.label for s in seq.steps] == P01_ORDER
    assert seq.duration == calibration.DEFAULT.duration
    assert calibration.scrambled(calibration.DEFAULT, "P01").steps == seq.steps      # reproducible


def test_sequence_file_keeps_the_links(tmp_path):
    lines = ["time,r,g,b,label,duration,keep"]
    t = 0.0
    for s in calibration.DEFAULT.steps:
        lines.append(f"{t:g},{s.rgb[0]},{s.rgb[1]},{s.rgb[2]},{s.label},{s.end - s.start:g},{int(s.linked)}")
        t += s.end - s.start
    seq = calibration.load_sequence(write(tmp_path, "\n".join(lines) + "\n"))
    assert seq.steps == calibration.DEFAULT.steps


def test_locate_finds_the_default_sequence():
    import numpy as np
    start = 7.4
    t = np.arange(0, 320, 0.01)
    rgb = np.full((len(t), 3), 128.0)                 # the presenter's grey lead-in and a grey scene after
    for s in calibration.DEFAULT.steps:
        sel = (t >= start + s.start) & (t < start + s.end)
        rgb[sel] = np.array(s.rgb) * 0.9
    loc = calibration.locate(t, rgb, calibration.DEFAULT)
    assert loc.start == pytest.approx(start, abs=0.05) and loc.error < 0.05
