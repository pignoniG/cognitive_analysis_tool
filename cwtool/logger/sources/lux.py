"""TSL2591 lux sensor logger over USB serial (the firmware in ``Lux Sensor/`` prints one reading per line).

Firmware 2 (November 2026, open issue 64) sends

    TSL2591,<sent ms>,<mid ms>,<clock ms>,<gain>,<integration ms>,<full>,<ir>,<saturated>,<lux>

with the board's ``millis()`` when the line was sent and at the middle of the integration, and the Unix time (ms) of
``millis() = 0`` on the board's real-time clock, which stamps the board's own SD-card file. The reading is stamped
at the middle of its integration, mapped onto the computer's clock with :class:`ClockMapper` as for the AS7341, and
``lux.csv`` gets the raw counts and the gain after the lux. The offset between the SD file's clock and the
computer's, at the start and the end, goes into ``session.json``, so the board's SD file can be aligned without a
time lag set by hand.

Earlier firmware sends only the lux, one number per line: those readings are stamped when they arrive and
``lux.csv`` has the time and the lux only.
"""

from __future__ import annotations

import time

from cwtool.logger.base import ClockMapper, Source
from cwtool.logger.sources.spectral import MillisUnwrapper

# Substrings of the USB description of the supported boards.
KNOWN_BOARDS = ("USB2.0-Serial", "Adafruit", "Arduino", "IOUSBHostDevice")
TAG = "TSL2591"
BANNER = "# TSL2591 lux logger"         # then the firmware's version
OPEN_WAIT = 5.0                         # s: a Nano restarts when its port opens, finds its clock and SD card
LEGACY_COLUMNS = ["unix time (s)", "lux"]
COLUMNS = ["unix time (s)", "lux", "device time (s)", "full", "ir", "gain", "saturated"]
SETTLE = 10.0                           # s of readings before the SD clock's starting offset is taken


def list_ports() -> list[tuple[str, str]]:
    """(device, description) of the serial ports; the likely sensor boards first."""
    import serial.tools.list_ports

    ports = [(p.device, p.description or "") for p in serial.tools.list_ports.comports()]
    return sorted(ports, key=lambda p: not any(k in p[1] for k in KNOWN_BOARDS))


def parse_line(text: str):
    """A reading as a dict: ``lux`` alone for the earlier firmware's lines; with ``sent``, ``mid``, ``clock`` (ms),
    ``gain``, ``integration (ms)``, ``full``, ``ir`` and ``saturated`` for firmware 2. None for anything else."""
    text = text.strip()
    parts = text.split(",")
    if parts[0] == TAG:
        if len(parts) != 10:
            return None
        try:
            sent, mid, clock, gain, integration, full, ir, saturated = (int(p) for p in parts[1:9])
            lux = float(parts[9])
        except ValueError:
            return None
        return {"sent": sent, "mid": mid, "clock": clock, "gain": gain, "integration (ms)": integration,
                "full": full, "ir": ir, "saturated": saturated, "lux": lux}
    if len(parts) != 1 or not text or text.startswith("#"):
        return None
    try:
        return {"lux": float(text)}
    except ValueError:  # the earlier firmware's start-up messages
        return None


class LuxSerialSource(Source):
    """The TSL2591 lux logger on a serial port: firmware 2's readings stamped by the board's clock, the earlier
    firmware's when they arrive."""
    kind = "lux"
    stall_seconds = 5.0       # about 8 readings a second

    def __init__(self, port: str | None = None, baud: int = 250000, name: str = "lux"):
        super().__init__(name)
        self.port, self.baud = port, baud
        self._auto = port is None  # found by the board's name, again on every reconnection (the name can change)
        self.columns = list(LEGACY_COLUMNS)  # the file cwtool.lux reads: lux.csv
        self._ser = None
        self._pending: list = []
        self._reset()

    def _reset(self) -> None:
        self._sent, self._mid, self._clock = MillisUnwrapper(), MillisUnwrapper(), ClockMapper()
        self._first_device = None
        self._pending = []

    def open(self) -> None:
        """Open the serial port, choosing the board by its name if no port was given, and wait for the first reading
        to know the firmware's format."""
        import serial

        if self._auto:
            ports = [p for p, d in list_ports() if any(k in d for k in KNOWN_BOARDS)]
            if not ports:
                raise RuntimeError("No sensor board found; choose the serial port")
            self.port = ports[0]
        self._reset()
        self._ser = serial.Serial(port=self.port, baudrate=self.baud, timeout=0.3, exclusive=True)
        self.settings = {"port": self.port, "baud": self.baud}
        try:
            self._handshake()
        except Exception:
            self._ser.close()
            self._ser = None
            raise

    def _handshake(self) -> None:
        end = time.time() + OPEN_WAIT
        while time.time() < end:
            line = self._ser.readline()
            host = time.time()
            text = line.decode("utf-8", "replace").strip()
            if text.startswith(BANNER):
                self.settings["firmware"] = text[2:]
            if text.startswith("# ERROR"):
                self.message = text[2:]
            fields = parse_line(text) if text else None
            if fields is None:
                continue
            if "sent" in fields:
                self.columns = list(COLUMNS)
                self.settings.setdefault("firmware", "TSL2591 lux logger 2")
                self.settings["times"] = "the board's clock at the middle of each 100 ms integration, mapped"
            else:
                self.columns = list(LEGACY_COLUMNS)
                self.settings["firmware"] = "lux only (before November 2026)"
                self.settings["times"] = "arrival of each line (the firmware sends no time)"
            self._pending.append((host, fields))
            return
        raise RuntimeError("No readings from the lux sensor board")

    def row(self, host: float, fields: dict):
        """The file's row for a reading that arrived at ``host`` (Unix s), or None for a reading in the other
        firmware's format (the board was reflashed while connected: the logger reconnects)."""
        if "sent" not in fields:
            return (host, fields["lux"]) if len(self.columns) == 2 else None
        if len(self.columns) == 2:
            return None
        offset = self._clock.update(self._sent(fields["sent"]), host)
        device = self._mid(fields["mid"])
        self._note_sd_clock(device, offset, fields["clock"])
        return (device + offset, fields["lux"], device, fields["full"], fields["ir"], fields["gain"],
                fields["saturated"])

    def _note_sd_clock(self, device: float, offset: float, clock_ms: int) -> None:
        """The offset between the SD file's clock (``clock ms`` + millis) and the computer's, for session.json."""
        if clock_ms <= 0:
            self.settings["SD file clock"] = "not set (the board found no real-time clock)"
            return
        sd_offset = round(offset - clock_ms / 1000.0, 4)    # computer time − SD file time, s
        if self._first_device is None:
            self._first_device = device
        info = self.settings.get("SD file clock")
        if not isinstance(info, dict) or device - self._first_device < SETTLE:
            info = {"computer − SD file time at start (s)": sd_offset, "start (board s)": round(device, 3)}
        info["computer − SD file time at end (s)"] = sd_offset
        span = device - info["start (board s)"]
        if span > 0:
            drift = (sd_offset - info["computer − SD file time at start (s)"]) / span
            info["board clock drift (ppm)"] = round(drift * 1e6, 1)
        self.settings["SD file clock"] = info

    def run(self, emit, stopped) -> None:
        """Read lines and emit a row for each reading; messages are skipped."""
        for host, fields in self._pending:
            row = self.row(host, fields)
            if row is not None:
                emit([row])
        self._pending.clear()
        while not stopped.is_set():
            line = self._ser.readline()
            if not line:
                continue
            host = time.time()
            text = line.decode("utf-8", "replace").strip()
            if text.startswith("# ERROR"):
                self.message = text[2:]
                continue
            fields = parse_line(text)
            if fields is None:
                continue
            row = self.row(host, fields)
            if row is None:
                raise RuntimeError("the lux sensor's firmware changed while connected")
            emit([row])

    def signals(self) -> list[str]:
        """What the live plot can show: the lux, then firmware 2's counts and gain."""
        return ["lux", "full", "ir", "gain"] if len(self.columns) > 2 else ["lux"]

    def signal_values(self, row):
        """(signal, value) pairs of a row for the live plot."""
        values = dict(zip(self.columns, row))
        for name in self.signals():
            yield name, values[name]

    def close(self) -> None:
        """Close the serial port."""
        if self._ser is not None:
            self._ser.close()
            self._ser = None
