#!/usr/bin/env python3
"""Log readings from the TSL2591 lux sensor logger over USB serial.

Use this when the sensor is connected to a computer instead of logging to its
SD card. Each line received from the microcontroller is one reading; readings
are appended to one CSV per hour in the output folder, named
``<month>_<day>_<hour>.csv`` (local time), with rows:

    unix time (ms), day, hour, minute, value

This is the format written by the 1.x application and read by the Pupil Core /
Neon lux import.

    python tools/lux_logger.py OUTPUT_FOLDER [--port PORT] [--baud 250000]
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from datetime import datetime
from pathlib import Path

try:
    import serial
    import serial.tools.list_ports
except ImportError:
    sys.exit("pyserial is required: pip install pyserial")

# Substrings of the USB description of the supported boards.
KNOWN_BOARDS = ("USB2.0-Serial", "Adafruit", "Arduino", "IOUSBHostDevice")


def find_port() -> str | None:
    for port in serial.tools.list_ports.comports():
        if any(name in (port.description or "") for name in KNOWN_BOARDS):
            return port.device
    return None


def append_reading(folder: Path, value: float) -> None:
    now = datetime.now()
    path = folder / f"{now.month}_{now.day}_{now.hour}.csv"
    with open(path, "a", newline="") as f:
        csv.writer(f).writerow([time.time() * 1000, now.day, now.hour, now.minute, value])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("folder", type=Path, help="output folder")
    ap.add_argument("--port", help="serial port (default: first known board)")
    ap.add_argument("--baud", type=int, default=250000)
    args = ap.parse_args()

    port = args.port or find_port()
    if port is None:
        print("No sensor board found. Available ports:", file=sys.stderr)
        for p in serial.tools.list_ports.comports():
            print(f"  {p.device}: {p.description}", file=sys.stderr)
        return 1
    args.folder.mkdir(parents=True, exist_ok=True)
    print(f"Logging {port} to {args.folder} (Ctrl+C to stop)")

    with serial.Serial(port=port, baudrate=args.baud, parity=serial.PARITY_NONE,
                       stopbits=serial.STOPBITS_ONE, bytesize=serial.EIGHTBITS, timeout=0.3) as ser:
        try:
            while True:
                line = ser.readline()
                if not line:
                    continue
                try:
                    value = float(line.decode("utf-8").strip())
                except ValueError:
                    print(f"ignored: {line!r}", file=sys.stderr)
                    continue
                append_reading(args.folder, value)
                print(f"\r{value:10.3f}", end="", flush=True)
        except KeyboardInterrupt:
            print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
