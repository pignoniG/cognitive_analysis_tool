"""AMS AS7341 spectral sensor on an Arduino Nano over USB serial (firmware in
``Lux Sensor/Arduino Nano/AS7341_spectral_nano``).

The firmware sends one spectrum per line, ``AS7341,<sent ms>,<mid ms>,<gain code>,<ATIME>,<ASTEP>,<saturated>`` and the
raw counts of its two integrations (F1-F4, clear, NIR, then F5-F8, clear, NIR). The file gets the channels in **basic
counts**, AMS's normalisation that removes the gain and the integration time:

    basic counts = raw counts / (gain × integration time in ms)

so readings taken at different gains compare directly. The clear and NIR channels, measured in both integrations,
are the mean of the two. The counts are the sensor's, not radiometric units: turning them into irradiance or lux
needs a calibration of this sensor (open issue 58).

Times: the board stamps each spectrum with its own clock at the middle of the two integrations. The clock is mapped
onto the computer's with :class:`ClockMapper` from the board's time when the line was sent and the time it arrived,
so the USB delay's jitter does not enter, and the stamp is the measurement's, not the arrival's.
"""

from __future__ import annotations

import time

from cwtool.logger.base import ClockMapper, Source

BAUD = 250000
TAG = "AS7341"
BANNER = "# AS7341 spectral logger"   # then the firmware's version
# (column, peak wavelength in nm) of the eight spectral channels, from the datasheet
BANDS = (("F1 415 nm", 415), ("F2 445 nm", 445), ("F3 480 nm", 480), ("F4 515 nm", 515),
         ("F5 555 nm", 555), ("F6 590 nm", 590), ("F7 630 nm", 630), ("F8 680 nm", 680))
CHANNELS = [name for name, _ in BANDS] + ["clear", "nir"]
STEP_MS = 2.78e-3                 # one integration step (ASTEP + 1 of them per ATIME + 1)
WRAP_MS = 2**32                   # millis() on the board wraps after 49.7 days
OPEN_WAIT = 5.0                   # s: the board restarts when the port opens, then prints its banner
MAX_LINE = 4096                   # bytes without a line end: not this firmware (another device at another baud)
# USB vendor IDs of the Nano's USB chips (Arduino, WCH CH340, FTDI), tried first when looking for the board
LIKELY_VENDORS = (0x2341, 0x2A03, 0x1A86, 0x0403)


def gain_of(code: int) -> float:
    """The gain of an AGAIN code: 0 is 0.5x, 1 is 1x, ... 10 is 512x."""
    return 0.5 * 2.0 ** code


def integration_ms(atime: int, astep: int) -> float:
    """Integration time of one measurement in ms."""
    return (atime + 1) * (astep + 1) * STEP_MS


def parse_line(text: str):
    """The fields of a spectrum line as a dict, or None for anything else (messages, partial lines).

    Keys: ``sent`` and ``mid`` (board time, ms), ``gain``, ``integration (ms)``, ``saturated`` and the
    basic counts of :data:`CHANNELS`.
    """
    parts = text.strip().split(",")
    if len(parts) != 19 or parts[0] != TAG:
        return None
    try:
        sent, mid, code, atime, astep, saturated = (int(p) for p in parts[1:7])
        a = [int(p) for p in parts[7:13]]
        b = [int(p) for p in parts[13:19]]
    except ValueError:
        return None
    gain, tint = gain_of(code), integration_ms(atime, astep)
    scale = 1.0 / (gain * tint)
    raw = a[:4] + b[:4] + [(a[4] + b[4]) / 2, (a[5] + b[5]) / 2]
    out = {"sent": sent, "mid": mid, "gain": gain, "integration (ms)": tint, "saturated": saturated}
    out.update({name: v * scale for name, v in zip(CHANNELS, raw)})
    return out


class MillisUnwrapper:
    """The board's 32-bit millisecond clock as seconds that keep increasing across its wrap."""

    def __init__(self):
        self._last = None
        self._wraps = 0

    def __call__(self, ms: int) -> float:
        if self._last is not None and ms < self._last - WRAP_MS // 2:
            self._wraps += 1
        self._last = ms
        return (ms + self._wraps * WRAP_MS) / 1000.0


class SpectralSerialSource(Source):
    """The AS7341 on a serial port: one spectrum per line, stamped by the board's clock mapped onto the computer's."""

    kind = "as7341"
    stall_seconds = 5.0       # 7.5 spectra a second; the board says when the sensor is missing, but sends no spectra

    def __init__(self, port: str | None = None, baud: int = BAUD, name: str = "as7341"):
        super().__init__(name)
        self.port, self.baud = port, baud
        self._auto = port is None  # looked for again on every reconnection: the port's name can change
        self._opened = False
        self.columns = ["unix time (s)", "device time (s)", *CHANNELS, "gain", "integration (ms)", "saturated"]
        self._ser = None
        self._sent = MillisUnwrapper()
        self._mid = MillisUnwrapper()
        self._clock = ClockMapper()
        self._pending: list = []          # spectrum lines read while opening, emitted first
        self._buffer = b""

    def open(self) -> None:
        """Open the port and wait for the firmware to answer; with no port given, try the USB serial ports until one
        does. Raises with the firmware's own message if it cannot find the sensor."""
        import serial
        import serial.tools.list_ports

        # a clean start: the board restarts when its port opens, so its clock starts again at zero
        self._sent, self._mid, self._clock = MillisUnwrapper(), MillisUnwrapper(), ClockMapper()
        self._buffer, self._pending, self.message = b"", [], None
        gone = self._opened and self.port not in {p.device for p in serial.tools.list_ports.comports()}
        if not self._auto and not gone:
            self._ser = serial.Serial(port=self.port, baudrate=self.baud, timeout=0.3, exclusive=True)
            try:
                self._handshake()
            except Exception:
                self._ser.close()
                raise
        else:                     # automatic, or the chosen port has gone since (back under another name)
            usb = sorted((p for p in serial.tools.list_ports.comports() if p.vid is not None),
                         key=lambda p: p.vid not in LIKELY_VENDORS)
            errors = []
            # every port is opened exclusively (here and by the lux sensor): a port another sensor is reading is
            # busy and skipped, not read by two at once
            for device in (p.device for p in usb):
                self._buffer = b""
                try:
                    self._ser = serial.Serial(port=device, baudrate=self.baud, timeout=0.3, exclusive=True)
                except serial.SerialException as e:
                    errors.append(f"{device}: {e}")
                    continue
                try:
                    self._handshake()
                except RuntimeError as e:
                    self._ser.close()
                    errors.append(f"{device}: {e}")
                    continue
                self.port = device
                break
            else:
                self._ser = None
                raise RuntimeError("No AS7341 board answered on the USB serial ports"
                                   + (" (" + "; ".join(errors) + ")" if errors else "") + ". Is the firmware flashed?")
        self._opened = True
        self.settings = {"port": self.port, "baud": self.baud, "firmware": self.settings.get("firmware", ""),
                         "channels": "basic counts: raw counts / (gain × integration time in ms)",
                         "peak wavelengths (nm)": {name: nm for name, nm in BANDS}}

    def _handshake(self) -> None:
        """Read until the firmware's banner or a spectrum arrives (the board restarts when the port opens)."""
        end, junk, firmware = time.time() + OPEN_WAIT, 0, False
        self._junk = False
        while time.time() < end and junk <= 20 and not self._junk:  # bad lines or no line ends: another device
            host, lines = self._read_lines()
            for line in lines:
                text = line.decode("utf-8", "replace").strip()
                if text.startswith("# ERROR"):
                    raise RuntimeError(text[2:])
                if text.startswith(BANNER):
                    self.settings["firmware"] = text[2:]
                    firmware = True
                if text.startswith("#") or not text:                # the firmware's messages
                    continue
                fields = parse_line(text)
                if fields is not None:
                    self._pending.append((host, fields))
                    return
                junk += 0 if firmware else 1
        raise RuntimeError("no answer from the AS7341 firmware" if not (junk or self._junk)
                           else "not the AS7341 firmware")

    _junk = False

    def _read_lines(self) -> tuple[float, list[bytes]]:
        """(arrival time, complete lines) of what the port has, waiting at most the port's timeout for it. Not
        ``readline``: a device that never ends a line (another device at another baud rate) would block it."""
        chunk = self._ser.read(max(1, self._ser.in_waiting))
        host = time.time()
        if not chunk:
            return host, []
        *lines, self._buffer = (self._buffer + chunk).split(b"\n")
        if len(self._buffer) > MAX_LINE:
            self._buffer, self._junk = b"", True
        return host, lines

    def row(self, host: float, fields: dict) -> tuple:
        """The file's row for a spectrum that arrived at ``host`` (Unix s): the clock mapping is updated with it."""
        offset = self._clock.update(self._sent(fields["sent"]), host)
        device = self._mid(fields["mid"])
        return (device + offset, device, *(fields[c] for c in CHANNELS),
                fields["gain"], fields["integration (ms)"], fields["saturated"])

    def run(self, emit, stopped) -> None:
        """Read lines until stopped and emit a row for each spectrum; messages are skipped."""
        for host, fields in self._pending:
            emit([self.row(host, fields)])
        self._pending.clear()
        while not stopped.is_set():
            host, lines = self._read_lines()
            rows = []
            for line in lines:
                text = line.decode("utf-8", "replace").strip()
                if text.startswith("# ERROR"):          # the board is there, the sensor is not: shown in the table
                    self.message = text[2:]
                elif (fields := parse_line(text)) is not None:
                    rows.append(self.row(host, fields))
            if rows:
                self.message = None
                emit(rows)

    def signals(self) -> list[str]:
        """What the live plot can show: the clear channel first, the spectral channels, NIR and the gain."""
        return ["clear", *CHANNELS[:8], "nir", "gain"]

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
