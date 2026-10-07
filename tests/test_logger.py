"""Tests of the sensor logger: the session folder and files, the live buffers, the clock mapping, the LSL, Shimmer and
RFCOMM sources, the watchdog and the window.
"""

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


def test_session_is_one_flat_folder_with_one_file_per_source(tmp_path):
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
    assert sorted(p.name for p in session.iterdir()) == ["event_log.csv", "lux.csv", "session.json",
                                                         "shimmer_sim.csv"]
    # lux.csv is read by the analysis as it is, from the recording folder itself
    assert lux.find_lux_folder(session) == session
    t0 = float(rows[1][0])
    t, v = lux.read_lux(session, epoch_start=t0, duration=10)
    assert list(v) == [100.0, 200.0, 300.0]
    assert list(csv.reader(open(session / "lux.csv")))[0] == ["unix time (s)", "lux"]
    events = list(csv.reader(open(session / "event_log.csv")))
    assert [e[0] for e in events[1:]] == ["Task", "Rest"]
    info = json.loads((session / "session.json").read_text())
    assert info["sources"]["lux"]["rows"] == 3 and info["sources"]["lux"]["file"] == "lux.csv"
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


def test_lux_reader_takes_the_time_span_from_lux_csv_and_still_reads_hourly_files(tmp_path):
    new = tmp_path / "new"
    new.mkdir()
    (new / "lux.csv").write_text("unix time (s),lux\n" + "".join(f"{1000 + i / 10:.3f},{i}\n" for i in range(600)))
    assert lux.lux_files(new) == [new / "lux.csv"]
    t, v = lux.read_lux(new, epoch_start=1010.0, duration=5.0, margin=0.0)
    assert t[0] == pytest.approx(0.0, abs=0.11) and t[-1] == pytest.approx(5.0, abs=0.11)
    assert v[0] == pytest.approx(100, abs=1)
    # a file outside the span is skipped without being read
    assert len(lux.read_lux(new, epoch_start=5000.0, duration=5.0, margin=0.0)[0]) == 0

    old = tmp_path / "old"
    old.mkdir()
    (old / "10_6_15.csv").write_text("".join(f"{(2000 + i) * 1000},6,15,0,{i}\n" for i in range(10)))
    t, v = lux.read_lux(old, epoch_start=2000.0, duration=9.0, margin=0.0)
    assert list(v) == list(range(10))


def test_plot_range_fits_the_data():
    pytest.importorskip("pyqtgraph")
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6.QtWidgets")
    from cwtool.logger.gui import plot_range

    assert plot_range([]) == (None, None)
    lo, hi = plot_range([0.0, 1.0, 2.0, 3.0, 4.0])
    assert lo < 0 < 4 < hi and hi - lo < 5   # the data span plus a margin, not a fixed scale
    lo, hi = plot_range([5000.0 + i % 3 for i in range(200)])  # near-flat at a large level
    assert lo < 5000 < hi and hi - lo >= 50 * 0.99
    lo, hi = plot_range(list(range(1000)) + [1e6])  # one spike in a full buffer does not flatten the signal
    assert hi < 1100
    lo, hi = plot_range([2.53] * 50)  # exactly flat
    assert lo < 2.53 < hi and hi - lo < 1


class _Info:
    """The parts of a pylsl StreamInfo the matching uses."""

    def __init__(self, name, type_="", source_id="", channels=1, labels=()):
        self._n, self._t, self._s, self._c, self._l = name, type_, source_id, channels, labels

    name = lambda self: self._n  # noqa: E731
    type = lambda self: self._t  # noqa: E731
    source_id = lambda self: self._s  # noqa: E731
    channel_count = lambda self: self._c  # noqa: E731


def test_lsl_matches_on_device_id_name_or_type():
    from cwtool.logger.sources.lsl import matches, signal_names

    eda = _Info("EDA", "EDA", "MD-V7-0000188")
    assert matches(eda, "MD-V7-0000188") and matches(eda, "md-v7") and matches(eda, "eda")
    assert not matches(eda, "MD-V7-0000999") and not matches(_Info("EDA", "EDA", ""), "MD-V7")
    assert matches(eda, "")  # no filter: every stream
    assert signal_names(eda) == ["EDA"]  # one channel: the stream name alone


def test_slow_disk_does_not_block_the_sources_or_the_reader(tmp_path):
    from cwtool.logger import sinks

    class SlowSink(sinks.CsvSink):
        def write(self, rows):
            time.sleep(0.02)  # slower than the source delivers: a backlog builds up
            super().write(rows)

    class HundredRows(SimulatedSource):
        def run(self, emit, stopped):
            for i in range(100):
                emit([(time.time(), float(i))])
                stopped.wait(0.005)

        def sink(self, folder):
            return SlowSink(folder / self.filename, self.columns)

    log = Logger()
    session = log.start_recording(tmp_path)
    log.add(HundredRows("slow", channels=1))
    worst = 0.0
    for _ in range(30):  # what the window does every 100 ms: it never waits for the disk
        t = time.perf_counter()
        log.live("slow", "ch1")
        worst = max(worst, time.perf_counter() - t)
        time.sleep(0.02)
    assert log.counts["slow"] == 100 and worst < 0.05
    log.stop_recording()  # waits for the backlog, so nothing is lost
    rows = list(csv.reader(open(session / "slow.csv")))[1:]
    assert [float(r[1]) for r in rows] == [float(i) for i in range(100)]
    log.shutdown()


def test_watchdog_reports_where_a_frozen_window_is_stuck(tmp_path):
    pytest.importorskip("PySide6.QtWidgets")
    pytest.importorskip("pyqtgraph")
    from cwtool.logger.gui import StallWatchdog

    wd = StallWatchdog(tmp_path / "stall.log", limit=0.6)
    wd.start()
    wd.beat()
    time.sleep(1.8)  # no beats: the window is frozen
    wd.stop()
    text = (tmp_path / "stall.log").read_text()
    assert "window not responding" in text and "Thread" in text
    ok = StallWatchdog(tmp_path / "ok.log", limit=0.6)
    ok.start()
    for _ in range(12):
        ok.beat()
        time.sleep(0.1)
    ok.stop()
    assert not (tmp_path / "ok.log").exists()


class _FakeShimmer:
    """The two clock calls of pyshimmer's ShimmerBluetooth, with a device clock that starts 100 s late."""

    def __init__(self, hang=False):
        self.offset, self.hang = -100.0, hang

    def get_rtc(self):
        if self.hang:
            time.sleep(60)
        return time.time() + self.offset

    def set_rtc(self, t):
        self.offset = t - time.time()


def test_shimmer_clock_is_set_and_reported():
    from cwtool.logger.sources.shimmer import ShimmerSource

    dev = _FakeShimmer()
    r = ShimmerSource.sync_clock(dev)
    assert r["set"] and r["offset before (s)"] == pytest.approx(-100.0, abs=0.1)
    assert abs(r["offset after (s)"]) < 0.1


def test_shimmer_clock_failure_does_not_stop_the_connection():
    from cwtool.logger.sources.shimmer import ShimmerSource

    t = time.time()
    r = ShimmerSource.sync_clock(_FakeShimmer(hang=True), timeout=0.3)  # a device that never answers
    assert not r["set"] and "no answer" in r["error"] and time.time() - t < 2
