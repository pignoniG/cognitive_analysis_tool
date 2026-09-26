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
