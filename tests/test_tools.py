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


def test_lux_logger_imports_only_with_pyserial():
    pytest.importorskip("serial")
    assert load_tool("lux_logger").KNOWN_BOARDS
