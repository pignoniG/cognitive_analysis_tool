import csv
import json
import threading
import time

import pytest

from cwtool import lux
from cwtool.logger import ClockMapper, Logger
from cwtool.logger.sources import SimulatedSource
from cwtool.logger.sources.lsl import LslSource
from cwtool.logger.sources.lux import LuxSerialSource
from cwtool.logger.sources.shimmer import TICKS_PER_SECOND, WRAP, TimestampUnwrapper


def wait(cond, timeout=5):
    end = time.time() + timeout
    while not cond() and time.time() < end:
        time.sleep(0.01)
    return cond()


class FakeLux(LuxSerialSource):
    go = threading.Event()

    def open(self):
        self.settings = {"port": "fake"}

    def run(self, emit, stopped):
        self.go.wait(5)
        for v in (100.0, 200.0, 300.0):
            emit([(time.time(), v)])
        stopped.wait()


def test_session_writes_one_file_per_source_and_lux_in_analysis_format(tmp_path):
    log = Logger()
    log.add(FakeLux())
    log.add(SimulatedSource("shimmer_sim", rate=100, channels=2))
    session = log.start_recording(tmp_path, label="p 01")
    FakeLux.go.set()
    assert session.name.endswith("_p_01")
    assert wait(lambda: log.counts["shimmer_sim"] > 20 and log.counts["lux"] == 3)
    log.mark("Task")
    time.sleep(0.05)
    log.mark("Rest")
    log.stop_recording()
    log.shutdown()

    rows = list(csv.reader(open(session / "shimmer_sim.csv")))
    assert rows[0] == ["unix time (s)", "ch1", "ch2"] and len(rows) > 21
    # the hourly lux files are what cwtool.lux reads
    assert lux.find_lux_folder(session) == session / "lux"
    t0 = float(rows[1][0])
    t, v = lux.read_lux(session / "lux", epoch_start=t0, duration=10)
    assert list(v) == [100.0, 200.0, 300.0]
    events = list(csv.reader(open(session / "event_log.csv")))
    assert [e[0] for e in events[1:]] == ["Task", "Rest"]
    info = json.loads((session / "session.json").read_text())
    assert info["sources"]["lux"]["rows"] == 3 and info["end (unix s)"] >= info["start (unix s)"]


def test_live_buffer_without_recording(tmp_path):
    log = Logger()
    log.add(SimulatedSource("s", rate=100))
    assert wait(lambda: len(log.live("s", "ch1")[0]) > 10)
    assert not log.recording and not list(tmp_path.iterdir())
    log.shutdown()


def test_source_added_while_recording_gets_a_file(tmp_path):
    log = Logger()
    session = log.start_recording(tmp_path)
    log.add(SimulatedSource("late", rate=100))
    assert wait(lambda: log.counts["late"] > 5)
    log.shutdown()
    assert (session / "late.csv").exists()


def test_duplicate_name_rejected():
    log = Logger()
    log.add(SimulatedSource("a"))
    with pytest.raises(ValueError):
        log.add(SimulatedSource("a"))
    log.shutdown()


def test_timestamp_unwrap():
    u = TimestampUnwrapper()
    ticks = [WRAP - 100, WRAP - 10, 5, 100]  # wraps once
    out = [u(t) for t in ticks]
    assert out == sorted(out)
    assert out[-1] == pytest.approx((100 + WRAP - (WRAP - 100)) / TICKS_PER_SECOND)


def test_clock_mapper_ignores_late_bursts_and_follows_drift():
    m = ClockMapper(window=10)
    offset = None
    for i in range(100):
        t = i * 0.1
        delay = 0.5 if i % 10 else 0.0  # bursts: most samples arrive late
        offset = m.update(t, 1000.0 + t * 1.0001 + delay)
    # the true offset at the end is 1000 + 9.9 * 0.0001; the delay of the late samples (0.5 s) is not in it
    assert offset == pytest.approx(1000.0, abs=0.01)


def test_lsl_without_stream_gives_clear_error():
    pytest.importorskip("pylsl")
    with pytest.raises(RuntimeError, match="No LSL stream"):
        LslSource("no-such-device-xyz", wait=0.5).open()


def test_window_records_a_protocol(tmp_path):
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6.QtWidgets")
    pytest.importorskip("pyqtgraph")
    from PySide6.QtWidgets import QApplication

    from cwtool.logger.gui import LoggerWindow

    app = QApplication.instance() or QApplication([])
    proto = tmp_path / "p.csv"
    proto.write_text("# c\nA,0.2\nB,\n")
    w = LoggerWindow()
    w.logger.add(SimulatedSource("sim", rate=100))
    w._connected("sim")
    w.folder.setText(str(tmp_path / "out"))
    w.toggle_recording()
    from cwtool.logger.protocol import read_protocol

    w._protocol = read_protocol(proto)
    w.start_protocol()
    end = time.time() + 1
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)
    assert w.phase_label.text().startswith("Phase 2/2: B")
    w.toggle_recording()
    session = next((tmp_path / "out").iterdir())
    names = [r[0] for r in csv.reader(open(session / "event_log.csv"))][1:]
    assert names == ["A", "B"]
    assert w.table.rowCount() == 1
    w.close()


def test_rfcomm_link_buffers_and_cancels():
    from cwtool.logger.sources.rfcomm_mac import BufferedLink, is_address

    assert is_address("00:06:66:B9:87:3A") and is_address("00-06-66-b9-87-3a")
    assert not is_address("/dev/cu.Shimmer3-873A") and not is_address(None)

    link = BufferedLink()
    assert link.timeout is None
    got = []
    t = threading.Thread(target=lambda: got.append(link.read(5)))
    t.start()
    link.feed(b"ab")
    link.feed(b"cdefg")
    t.join(2)
    assert got == [b"abcde"] and link.read(2) == b"fg"
    # a blocked read returns what it has when cancelled (pyshimmer treats a short read as the end)
    t = threading.Thread(target=lambda: got.append(link.read(4)))
    t.start()
    time.sleep(0.1)
    link.cancel_read()
    t.join(2)
    assert got[-1] == b"" and not t.is_alive()
