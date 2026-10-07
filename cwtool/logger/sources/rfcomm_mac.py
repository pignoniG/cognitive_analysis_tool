"""A serial-like link to a Bluetooth device over macOS's IOBluetooth, without the ``/dev/cu.*`` serial port.

macOS's Bluetooth serial ports often stay silent (the port exists but its link never comes up). Opening the
RFCOMM channel directly works. This class gives pyshimmer the few calls it needs from a ``serial.Serial``.

macOS aborts a process that uses Bluetooth when the app it was started from has no Bluetooth permission, and
that cannot be caught, so :func:`bluetooth_allowed` tests it in a throwaway subprocess first. Start the logger
from Terminal (or another app that may use Bluetooth) and allow the prompt the first time.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

ADDRESS = re.compile(r"^[0-9A-Fa-f]{2}([:-][0-9A-Fa-f]{2}){5}$")
SPP_UUID = 0x1101
TRACE = bool(os.environ.get("CWTOOL_BT_DEBUG"))


def trace(*args) -> None:
    """Debug output of the link (set CWTOOL_BT_DEBUG=1)."""
    if TRACE:
        print(f"[bt {time.time() % 1000:8.3f}]", *args, file=sys.stderr, flush=True)



def is_address(text: str | None) -> bool:
    """True if the text is a Bluetooth address (six hex pairs)."""
    return bool(text and ADDRESS.match(text))


def bluetooth_allowed(timeout: float = 20.0) -> bool:
    """Whether this process's app may use Bluetooth. Asks in a subprocess because a refusal kills the caller."""
    if sys.platform != "darwin":
        return False
    code = "import IOBluetooth as b; b.IOBluetoothDevice.pairedDevices()"
    try:
        return subprocess.run([sys.executable, "-c", code], capture_output=True, timeout=timeout).returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def paired_devices(prefix: str = "") -> list[tuple[str, str]]:
    """(name, address) of the paired Bluetooth devices whose name starts with ``prefix``. Empty without
    permission or off macOS."""
    if sys.platform != "darwin":
        return []
    code = ("import IOBluetooth as b;"
            "[print(d.name() or '', d.addressString(), sep='|') for d in b.IOBluetoothDevice.pairedDevices() or []]")
    try:
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=20)
    except (subprocess.TimeoutExpired, OSError):
        return []
    if r.returncode != 0:
        return []
    out = [tuple(line.split("|", 1)) for line in r.stdout.splitlines() if "|" in line]
    return [(n, a) for n, a in out if n.startswith(prefix)]


class BufferedLink:
    """Received bytes with a blocking read that can be cancelled: the part of a serial port pyshimmer relies on."""

    timeout = None  # reads block until satisfied or cancelled

    def __init__(self):
        self._buf = bytearray()
        self._cond = threading.Condition()
        self._cancelled = False

    def feed(self, data: bytes) -> None:
        """Add bytes received from the helper to the read buffer and wake the reader."""
        with self._cond:
            self._buf += data
            self._cond.notify_all()

    def read(self, n: int = 1) -> bytes:
        """``n`` bytes; fewer only if the read was cancelled or the link closed."""
        with self._cond:
            while len(self._buf) < n and not self._cancelled:
                self._cond.wait(0.2)
            out = bytes(self._buf[:n])
            del self._buf[:n]
            return out

    def cancel_read(self) -> None:
        """Make blocked and later reads return at once (the link is closing)."""
        with self._cond:
            self._cancelled = True
            self._cond.notify_all()

    def reset_input_buffer(self) -> None:
        """Discard what has been received and not read."""
        with self._cond:
            self._buf.clear()


class RfcommSerial(BufferedLink):
    """RFCOMM channel to a paired device, through :mod:`rfcomm_helper` running as a subprocess."""

    def __init__(self, address: str, channel: int | None = None, open_timeout: float = 60.0):
        super().__init__()
        cmd = [sys.executable, str(Path(__file__).with_name("rfcomm_helper.py")), address]
        if channel is not None:
            cmd.append(str(channel))
        self._proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                      bufsize=0)
        self._ready = threading.Event()
        self._error: str | None = None
        threading.Thread(target=self._read_stdout, daemon=True, name="rfcomm-rx").start()
        threading.Thread(target=self._read_stderr, daemon=True, name="rfcomm-status").start()
        if not self._ready.wait(open_timeout) or self._error:
            error = self._error or f"Could not open Bluetooth channel to {address} in {open_timeout:.0f} s"
            self.close()
            raise RuntimeError(error)

    def _read_stdout(self) -> None:
        while True:
            data = os.read(self._proc.stdout.fileno(), 4096)
            if not data:
                break
            self.feed(data)
        self.cancel_read()  # the helper ended: the link is closed
        self._ready.set()

    def _read_stderr(self) -> None:
        for raw in iter(self._proc.stderr.readline, b""):
            line = raw.decode("utf-8", "replace").strip()
            if line == "READY":
                self._ready.set()
            elif line.startswith("ERROR "):
                self._error = line[6:]
                self._ready.set()
            elif line.startswith("TRACE "):
                trace(line[6:])

    def write(self, data: bytes) -> int:
        """Send bytes to the device through the helper; a broken pipe ends the reads and is raised."""
        try:
            self._proc.stdin.write(bytes(data))
        except (BrokenPipeError, OSError):
            self.cancel_read()
            raise
        return len(data)

    def close(self) -> None:
        """Close the channel: end the helper's input, wait for it to exit, kill it if it does not."""
        self.cancel_read()
        try:
            self._proc.stdin.close()  # EOF: the helper closes the channel and exits
        except OSError:
            pass
        try:
            self._proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self._proc.kill()
