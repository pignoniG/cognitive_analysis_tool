"""TSL2591 lux sensor logger over USB serial (the firmware in ``Lux Sensor/`` prints one reading per line)."""

from __future__ import annotations

import time

from cwtool.logger.base import Source

# Substrings of the USB description of the supported boards.
KNOWN_BOARDS = ("USB2.0-Serial", "Adafruit", "Arduino", "IOUSBHostDevice")


def list_ports() -> list[tuple[str, str]]:
    """(device, description) of the serial ports; the likely sensor boards first."""
    import serial.tools.list_ports

    ports = [(p.device, p.description or "") for p in serial.tools.list_ports.comports()]
    return sorted(ports, key=lambda p: not any(k in p[1] for k in KNOWN_BOARDS))


class LuxSerialSource(Source):
    kind = "lux"

    def __init__(self, port: str | None = None, baud: int = 250000, name: str = "lux"):
        super().__init__(name)
        self.port, self.baud = port, baud
        self.columns = ["unix time (s)", "lux"]  # the file cwtool.lux reads: lux.csv
        self._ser = None

    def open(self) -> None:
        import serial

        if self.port is None:
            ports = [p for p, d in list_ports() if any(k in d for k in KNOWN_BOARDS)]
            if not ports:
                raise RuntimeError("No sensor board found; choose the serial port")
            self.port = ports[0]
        self._ser = serial.Serial(port=self.port, baudrate=self.baud, timeout=0.3)
        self.settings = {"port": self.port, "baud": self.baud}

    def run(self, emit, stopped) -> None:
        while not stopped.is_set():
            line = self._ser.readline()
            if not line:
                continue
            now = time.time()
            try:
                lux = float(line.decode("utf-8").strip())
            except ValueError:  # the firmware prints its start-up messages on the same port
                continue
            emit([(now, lux)])

    def close(self) -> None:
        if self._ser is not None:
            self._ser.close()
