"""Helper process of :mod:`rfcomm_mac`: owns one RFCOMM channel and relays bytes over stdin/stdout.

IOBluetooth delivers incoming data to the main thread's run loop, so the channel is opened and serviced on this
process's main thread, whatever the program that uses it is doing. Protocol:

    stdin   bytes to send to the device (EOF closes the channel and ends the process)
    stdout  bytes received from the device
    stderr  lines: ``READY`` once open, ``ERROR <text>``, ``TRACE <text>``

Run as ``python rfcomm_helper.py ADDRESS [CHANNEL]``. Must be started from an app that may use Bluetooth.
"""

from __future__ import annotations

import os
import queue
import sys
import threading
import time

ATTEMPTS = 3
tx: queue.Queue = queue.Queue()
TRACE = bool(os.environ.get("CWTOOL_BT_DEBUG"))


def say(text: str) -> None:
    """Write a line to the parent process (stderr)."""
    sys.stderr.write(text + "\n")
    sys.stderr.flush()


def trace(*args) -> None:
    """Write a debug line when tracing is on."""
    if TRACE:
        say("TRACE " + " ".join(str(a) for a in args))


def read_stdin() -> None:
    """Queue what the parent sends, to be written to the device; None when the parent closes the pipe."""
    while True:
        data = os.read(0, 4096)
        tx.put(data or None)
        if not data:
            return


def main(address: str, channel_id: int | None) -> int:
    """Open the RFCOMM channel to the device and pass bytes between it and the parent's pipes until either closes."""
    from Foundation import NSDate, NSObject, NSRunLoop
    import IOBluetooth as bt

    state = {"sdp": None}

    class Delegate(NSObject):
        """Receives IOBluetooth's callbacks: the service search result, data from the device and the channel closing."""
        def sdpQueryComplete_status_(self, dev, status):
            """Callback: the service search finished with this status."""
            state["sdp"] = status

        def rfcommChannelData_data_length_(self, ch, data, length):
            """Callback: bytes arrived from the device; pass them to the parent."""
            chunk = bytes(data)[:length]
            trace("rx", chunk.hex(" "))
            os.write(1, chunk)

        def rfcommChannelClosed_(self, ch):
            """Callback: the device closed the channel; tell the writer to stop."""
            trace("channel closed by the device")
            tx.put(None)

    def spin(seconds, until=None):
        """Run the macOS run loop (which delivers the Bluetooth callbacks) for ``seconds``, or until ``until()`` is
        true.
        """
        end = time.time() + seconds
        while time.time() < end and not (until and until()):
            NSRunLoop.currentRunLoop().runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(0.02))

    delegate = Delegate.alloc().init()
    dev = bt.IOBluetoothDevice.deviceWithAddressString_(address.replace(":", "-").upper())
    if dev is None or not dev.isPaired():
        say(f"ERROR {address} is not paired with this Mac")
        return 1

    channel, attempts, cid = None, [], channel_id
    for attempt in range(1, ATTEMPTS + 1):
        # A connection left over from an earlier attempt or process blocks the channel (status 0xE00002BC):
        # drop it, give macOS time to release it, bring the link up, then open.
        dev.closeConnection()
        spin(2.0 * attempt)
        link_status = dev.openConnection()
        spin(1.0)
        if cid is None:
            dev.performSDPQuery_(delegate)
            spin(10, lambda: state["sdp"] is not None or bool(dev.services()))
            for rec in dev.services() or []:
                status, found = rec.getRFCOMMChannelID_(None)
                if status == 0:
                    cid = found
                    break
            cid = cid or 1
        status, channel = dev.openRFCOMMChannelSync_withChannelID_delegate_(None, cid, delegate)
        attempts.append(f"link {link_status}, channel {cid}: {status}")
        if status == 0 and channel is not None:
            break
        channel = None
    if channel is None:
        say("ERROR Could not open the Bluetooth channel (" + "; ".join(attempts) + "). Is the Shimmer on, in "
            "standby (slow blue blink), and not connected to another computer?")
        return 1

    trace("channel open", attempts)
    threading.Thread(target=read_stdin, daemon=True).start()
    say("READY")
    try:
        while True:
            spin(0.02)
            try:
                while True:
                    data = tx.get_nowait()
                    if data is None:
                        return 0
                    trace("tx", data.hex(" "), "->", channel.writeSync_length_(data, len(data)))
            except queue.Empty:
                pass
    finally:
        channel.closeChannel()
        dev.closeConnection()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else None))
