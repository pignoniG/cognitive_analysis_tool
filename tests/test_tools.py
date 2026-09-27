import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from cwtool.devices import varjo

TOOLS = Path(__file__).resolve().parent.parent / "tools"


def load_tool(name):
    spec = importlib.util.spec_from_file_location(name, TOOLS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_example_protocol_parses():
    events = load_tool("event_logger").read_protocol(TOOLS / "example_protocol.csv")
    assert events[0] == ("Riposo", 60.0)
    assert events[1] == ("Briefing", None)
    assert len(events) == 16


def test_event_log_with_utc_offset_is_zone_independent(tmp_path):
    # Written by tools/event_logger.py: ISO times with offset.
    start = datetime(2026, 2, 10, 10, 0, 0, tzinfo=timezone(timedelta(hours=1)))
    (tmp_path / "2026-Feb-10_10-00-00_event_log.csv").write_text(
        "Event,Start Time,End Time,Duration (s)\n"
        f"Riposo,{start.isoformat()},x,60.000\n"
        f"Task,{(start + timedelta(seconds=60)).isoformat()},x,30.000\n")
    events = varjo.read_event_log(tmp_path, epoch_start=start.timestamp() - 5)
    assert [(e.label, e.start, e.end) for e in events] == [("Riposo", 5, 65), ("Task", 65, 95)]


def test_event_log_keeps_gaps_between_events(tmp_path):
    # A pause between two phases (e.g. the operator pressed Enter late) is kept, not closed up.
    start = datetime(2026, 2, 10, 10, 0, 0, tzinfo=timezone(timedelta(hours=1)))
    (tmp_path / "x_event_log.csv").write_text(
        "Event,Start Time,End Time,Duration (s)\n"
        f"Riposo,{start.isoformat()},x,60.000\n"
        f"Task,{(start + timedelta(seconds=75)).isoformat()},x,30.000\n"
        "Recovery,not a time,x,10.000\n")
    events = varjo.read_event_log(tmp_path, epoch_start=start.timestamp())
    assert [(e.label, e.start, e.end) for e in events] == [("Riposo", 0, 60), ("Task", 75, 105),
                                                          ("Recovery", 105, 115)]


def test_event_log_prefers_unix_time_and_reads_old_logs_in_the_recording_zone(tmp_path):
    # The current logger also writes Unix time, which wins over a (here deliberately wrong) ISO time.
    (tmp_path / "x_event_log.csv").write_text(
        "Event,Start Time,End Time,Duration (s),Start (unix s),End (unix s)\n"
        "Rest,1999-01-01T00:00:00,x,10.000,1000010.000,1000020.000\n")
    events = varjo.read_event_log(tmp_path, epoch_start=1_000_000.0)
    assert (events[0].start, events[0].end) == (10, 20)
    # Old logs have naive local times: read at the recording computer's UTC offset when known.
    (tmp_path / "x_event_log.csv").write_text("Event,Start Time,End Time,Duration (s)\nRest,2026-04-14T12:14:29,x,5\n")
    epoch = datetime(2026, 4, 14, 10, 14, 19, tzinfo=timezone.utc).timestamp()   # 12:14:19 at UTC+2
    events = varjo.read_event_log(tmp_path, epoch_start=epoch, utc_offset=2 * 3600)
    assert events[0].start == pytest.approx(10)


def test_varjo_recording_zone_comes_from_its_file_name(tmp_path):
    from conftest import write_varjo_recording
    from cwtool import devices
    folder = write_varjo_recording(tmp_path / "rec", [128] * 4)
    # The fixture's first sample is at 1.7e9 s = 2023-11-14 22:13:20 UTC; name the file in UTC+1.
    (folder / "varjo_gaze_output_test.csv").rename(folder / "varjo_gaze_output_2023-11-14_23-13-20-000.csv")
    (folder / "old_event_log.csv").write_text("Event,Start Time,End Time,Duration (s)\nTask,2023-11-14T23:13:22,x,1\n")
    rec = devices.load(folder)
    assert rec.events[0].start == pytest.approx(2.0, abs=0.05)


def test_lux_logger_imports_only_with_pyserial():
    pytest.importorskip("serial")
    assert load_tool("lux_logger").KNOWN_BOARDS
