"""Tests of the AS7341 spectral sensor source: the firmware's line format, basic counts, the board's clock, opening a
port (handshake, the firmware's error messages) and the file a session gets."""

import csv
import threading
import time

import pytest

from cwtool import lux, sensors
from cwtool.logger import Logger
from cwtool.logger.sources import spectral
from cwtool.logger.sources.spectral import CHANNELS, MillisUnwrapper, SpectralSerialSource, parse_line

# a spectrum as the firmware prints it: sent, mid, gain code 6 (32x), ATIME 29, ASTEP 599, not saturated, then
# F1-F4 CLEAR NIR and F5-F8 CLEAR NIR
LINE = "AS7341,10125,10070,6,29,599,0,100,200,300,400,1000,50,500,600,700,800,1100,70\r\n"


def test_a_line_gives_basic_counts():
    f = parse_line(LINE)
    tint = 30 * 600 * 2.78e-3                                   # 50.04 ms
    assert f["integration (ms)"] == pytest.approx(tint)
    assert f["gain"] == 32.0 and f["saturated"] == 0 and (f["sent"], f["mid"]) == (10125, 10070)
    assert f["F1 415 nm"] == pytest.approx(100 / (32 * tint))
    assert f["F5 555 nm"] == pytest.approx(500 / (32 * tint))
    assert f["F8 680 nm"] == pytest.approx(800 / (32 * tint))
    assert f["clear"] == pytest.approx(1050 / (32 * tint))      # the mean of the two integrations
    assert f["nir"] == pytest.approx(60 / (32 * tint))
    # the same light at another gain gives the same basic counts
    other = parse_line(LINE.replace(",6,29,", ",10,29,").replace(",100,", ",1600,"))
    assert other["gain"] == 512.0 and other["F1 415 nm"] == pytest.approx(f["F1 415 nm"])


@pytest.mark.parametrize("text", ["# AS7341 spectral logger 1", "", "AS7341,1,2,3", "1234.5",
                                  LINE.replace("100", "x"), "\x00\x00AS7341" + LINE[6:]])
def test_anything_else_is_not_a_spectrum(text):
    assert parse_line(text) is None


def test_the_boards_clock_keeps_increasing_across_its_wrap():
    u = MillisUnwrapper()
    out = [u(ms) for ms in (2**32 - 200, 2**32 - 100, 0, 100)]
    assert out == sorted(out) and out[-1] - out[0] == pytest.approx(0.3)


def test_the_stamp_is_the_measurement_mapped_onto_the_computers_clock():
    s = SpectralSerialSource("fake")
    rows = [s.row(1000.0 + d + 0.1 * i, parse_line(LINE.replace("10125,10070", f"{10125 + 100 * i},{10070 + 100 * i}")))
            for i, d in enumerate([0.004, 0.030, 0.004, 0.012])]
    # the line leaves the board at 10.125 s and arrives 4 ms later at best; the spectrum was measured 55 ms before
    assert rows[-1][0] == pytest.approx(1000.0 + 0.3 + 0.004 - 0.055)
    assert rows[0][1] == pytest.approx(10.070)
    assert len(rows[0]) == len(s.columns) and s.columns[2:12] == CHANNELS
    assert dict(s.signal_values(rows[0]))["clear"] == rows[0][s.columns.index("clear")]


class FakeSerial:
    """A serial port that gives these lines, then nothing."""

    def __init__(self, lines, **kwargs):
        self.lines = [ln.encode() if isinstance(ln, str) else ln for ln in lines]
        self.closed = False

    in_waiting = 0

    def read(self, n=1):
        if self.lines:
            return self.lines.pop(0)
        time.sleep(0.01)
        return b""

    def close(self):
        self.closed = True


def _port(monkeypatch, lines):
    import serial

    made = []

    def factory(**kwargs):
        made.append(FakeSerial(list(lines), **kwargs))
        return made[-1]

    monkeypatch.setattr(serial, "Serial", factory)
    monkeypatch.setattr(spectral, "OPEN_WAIT", 0.5)
    return made


def test_opening_waits_for_the_firmware_and_keeps_the_first_spectrum(monkeypatch):
    pytest.importorskip("serial")
    _port(monkeypatch, [b"\xff\x00garbage\n", "# AS7341 spectral logger 1\r\n", "# AS7341 found\r\n", LINE, LINE])
    s = SpectralSerialSource("/dev/fake")
    s.open()
    assert s.settings["firmware"] == "AS7341 spectral logger 1"
    assert s.settings["port"] == "/dev/fake" and "basic counts" in s.settings["channels"]
    got, stop = [], threading.Event()
    t = threading.Thread(target=s.run, args=(got.extend, stop))
    t.start()
    assert _wait(lambda: len(got) == 2)
    stop.set()
    t.join(2)
    s.close()


def test_the_firmwares_error_is_shown_when_the_sensor_is_missing(monkeypatch):
    pytest.importorskip("serial")
    made = _port(monkeypatch, ["# AS7341 spectral logger 1\r\n",
                               "# ERROR AS7341 not found: check VIN, GND, SDA = A4, SCL = A5\r\n"])
    with pytest.raises(RuntimeError, match="not found: check VIN"):
        SpectralSerialSource("/dev/fake").open()
    assert made[0].closed


def test_a_device_that_never_ends_a_line_is_not_taken_for_the_sensor(monkeypatch):
    pytest.importorskip("serial")
    _port(monkeypatch, [b"\x00" * 1000] * 200)                   # another device, read at the wrong baud rate
    start = time.time()
    with pytest.raises(RuntimeError, match="not the AS7341"):
        SpectralSerialSource("/dev/fake").open()
    assert time.time() - start < 2


def test_a_silent_port_is_not_taken_for_the_sensor(monkeypatch):
    pytest.importorskip("serial")
    _port(monkeypatch, [])
    with pytest.raises(RuntimeError, match="no answer"):
        SpectralSerialSource("/dev/fake").open()


def test_a_session_file_is_a_sensor_file_and_not_a_lux_log(tmp_path):
    class Fake(SpectralSerialSource):
        def open(self):
            self.settings = {"port": "fake"}

        def run(self, emit, stopped):
            for i in range(3):
                emit([self.row(time.time(), parse_line(LINE))])
            stopped.wait()

    log = Logger()
    session = log.start_recording(tmp_path)
    log.add(Fake())
    assert _wait(lambda: log.counts["as7341"] == 3)
    log.shutdown()
    header = next(csv.reader(open(session / "as7341.csv")))
    assert header[:3] == ["unix time (s)", "device time (s)", "F1 415 nm"] and header[-3:] == [
        "gain", "integration (ms)", "saturated"]
    assert not lux.lux_files(session)                                      # not read as lux
    found = sensors.find_sensor_files(session)
    assert [(p.name, k) for p, k in found] == [("as7341.csv", "as7341")]   # shown and exported by the analysis app
    s = sensors.read_sensor(*found[0])
    assert len(s) == 3 and s.data["gain"][0] == 32.0


def test_the_dialog_makes_a_spectral_source():
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6.QtWidgets")
    pytest.importorskip("pyqtgraph")
    from PySide6.QtWidgets import QApplication

    from cwtool.logger.gui import AddSourceDialog

    QApplication.instance() or QApplication([])
    d = AddSourceDialog("as7341", set())
    source = d.source()
    assert isinstance(source, SpectralSerialSource) and source.port is None and source.name == "as7341"
    assert AddSourceDialog("as7341", {"as7341"}).source().name == "as7341_2"


def _wait(cond, timeout=5):
    end = time.time() + timeout
    while not cond() and time.time() < end:
        time.sleep(0.01)
    return cond()


def test_the_boards_sensor_message_is_shown_and_cleared(monkeypatch):
    pytest.importorskip("serial")
    _port(monkeypatch, ["# AS7341 spectral logger 1\r\n", LINE, "# ERROR lost the AS7341, reconnecting\r\n"])
    s = SpectralSerialSource("/dev/fake")
    s.open()
    got, stop = [], threading.Event()
    t = threading.Thread(target=s.run, args=(got.extend, stop))
    t.start()
    assert _wait(lambda: s.message == "ERROR lost the AS7341, reconnecting") and len(got) == 1
    s._ser.lines.append(LINE.encode())
    assert _wait(lambda: s.message is None and len(got) == 2)
    stop.set()
    t.join(2)


def test_reopening_starts_the_boards_clock_afresh(monkeypatch):
    pytest.importorskip("serial")
    later = LINE.replace("10125,10070", "600125,600070")
    _port(monkeypatch, ["# AS7341 spectral logger 1\r\n", later])
    s = SpectralSerialSource("/dev/fake")
    s.open()
    first = s.row(5000.0, parse_line(later))
    s.close()
    _port(monkeypatch, ["# AS7341 spectral logger 1\r\n", LINE])        # the board restarted: its clock is back at 10 s
    monkeypatch.setattr("serial.tools.list_ports.comports", lambda: [type("P", (), {"device": "/dev/fake"})()])
    s.open()
    second = s.row(5010.0, parse_line(LINE))
    assert second[0] - first[0] == pytest.approx(10.0)                 # on the computer's clock, not 590 s back
    assert s.port == "/dev/fake"


def test_a_chosen_port_that_is_gone_is_looked_for_on_reconnecting(monkeypatch):
    pytest.importorskip("serial")
    _port(monkeypatch, ["# AS7341 spectral logger 1\r\n", LINE] * 3)
    s = SpectralSerialSource("/dev/old")
    s.open()
    s.close()
    port = type("P", (), {"device": "/dev/new", "vid": 0x1A86})()
    monkeypatch.setattr("serial.tools.list_ports.comports", lambda: [port])
    s.open()
    assert s.port == "/dev/new"


def test_the_search_skips_a_port_another_sensor_is_reading(monkeypatch):
    serial = pytest.importorskip("serial")
    asked = []

    def factory(port, exclusive=False, **kwargs):
        asked.append((port, exclusive))
        if port == "/dev/lux":                      # the lux sensor holds its port
            raise serial.SerialException("Could not exclusively lock port /dev/lux")
        return FakeSerial(["# AS7341 spectral logger 1\r\n", LINE])

    monkeypatch.setattr(serial, "Serial", factory)
    ports = [type("P", (), {"device": d, "vid": v})() for d, v in (("/dev/lux", 0x2341), ("/dev/nano", 0x1A86))]
    monkeypatch.setattr("serial.tools.list_ports.comports", lambda: ports)
    s = SpectralSerialSource()
    s.open()
    assert s.port == "/dev/nano" and all(exclusive for _, exclusive in asked)
