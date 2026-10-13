"""Shimmer3 (ECG, GSR, ...) over Bluetooth or the USB dock, through pyshimmer.

The Shimmer is streaming-configured: the sensors enabled on the device (in Consensys, or ``sensors`` here) are
logged as raw ADC values, one column per channel, plus the device's own clock. Calibration to mV or µS is
done in the analysis, as the raw values are what the device sends.

On connecting, the device's real-time clock is set to the computer's time (``set_clock``), as Consensys does. The
streamed samples are stamped by a different clock (ticks since power-on, mapped onto Unix time by
:class:`ClockMapper`), so this does not change the logger's files; it makes the device's own SD card recordings
and its "RTC not set" light agree with the computer. The clock is lost when the unit is switched off.

The sampling rate (``sampling_rate``) is set on the device if given. For the ECG unit the two ExG chips sample
at a rate of their own (125, 250, 500 ... per second); when the rate is set here they are set to the lowest of those
that is not below it, so every streamed sample is a new ECG sample. At the default 51.2 Hz the ECG is too coarse for
heart rate variability (see :mod:`cwtool.hrv`): 256 Hz or more is needed. The ExG gains and data rates are saved in
the session's ``session.json``, which the conversion to millivolts needs.
"""

from __future__ import annotations

import threading
import time

from cwtool.logger.base import ClockMapper, Source

TICKS_PER_SECOND = 32768.0
WRAP = 2**24  # the timestamp is 24 bits: it wraps every 512 s
EXG_RATES = (125, 250, 500, 1000, 2000)   # samples/s of the ADS1292R chips; the code is the index (CONFIG1 bits DR2..DR0)
EXG_REFERENCE_V = 2.42                    # V, the chips' internal reference: counts × this / (2^23 − 1) / gain = volts


def exg_rate_code(stream_rate: float) -> int:
    """Index in :data:`EXG_RATES` of the lowest ExG rate that is not below ``stream_rate`` (the highest if none)."""
    for code, rate in enumerate(EXG_RATES):
        if rate >= stream_rate - 1e-6:
            return code
    return len(EXG_RATES) - 1


def call_with_timeout(fn, *args, timeout: float = 5.0):
    """Call a device function in a thread and give up with TimeoutError if it does not answer in time (pyshimmer
    waits for an answer forever). An error of the call is raised in the caller."""
    out = {}

    def run():
        try:
            out["value"] = fn(*args)
        except Exception as e:      # raised again in the caller's thread
            out["error"] = e

    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        raise TimeoutError(f"no answer within {timeout:.0f} s")
    if "error" in out:
        raise out["error"]
    return out.get("value")


class TimestampUnwrapper:
    """Device ticks (24 bit, 32768 Hz, wrapping) → seconds since the first sample."""

    def __init__(self):
        self._last = None
        self._wraps = 0
        self._first = None

    def __call__(self, ticks: int) -> float:
        if self._last is not None and ticks < self._last - WRAP // 2:
            self._wraps += 1
        self._last = ticks
        total = ticks + self._wraps * WRAP
        if self._first is None:
            self._first = total
        return (total - self._first) / TICKS_PER_SECOND


class ShimmerSource(Source):
    """A Shimmer3 (LogAndStream firmware) over Bluetooth, through pyshimmer: raw values with the device's clock mapped
    onto the computer's.
    """
    kind = "shimmer"

    def __init__(self, port: str, name: str = "shimmer", sampling_rate: float | None = None, sensors=None,
                 timeout: float = 10.0, set_clock: bool = True):
        super().__init__(name)
        self.timeout = timeout
        self.set_clock = set_clock
        self.port, self.sampling_rate, self.sensors = port, sampling_rate, sensors
        self._dev = None
        self._channels = []
        self._emit = None
        self._unwrap = TimestampUnwrapper()
        self._clock = ClockMapper()
        self._t0_host = None

    def open(self) -> None:
        """Connect and initialise the device (with a time limit), set its clock, read its channels and set the sampling
        rate.
        """
        from pyshimmer import ShimmerBluetooth

        ser = self._link()
        self._dev = ShimmerBluetooth(ser)
        # initialize() waits for the device's answer forever; give up after a while instead.
        init = threading.Thread(target=self._dev.initialize, daemon=True)
        init.start()
        init.join(self.timeout)
        if init.is_alive():
            ser.cancel_read()  # ends pyshimmer's read loop quietly
            init.join(2)
            ser.close()
            self._dev = None
            raise RuntimeError(
                f"The Shimmer on {self.port} did not answer within {self.timeout:.0f} s. Check that it is on "
                "and not in its dock, that no other program (Consensys) is connected, and that it runs the "
                "LogAndStream firmware.")
        if self.set_clock:
            self.settings["real-time clock"] = self.sync_clock(self._dev)
        if self.sensors:
            self._dev.set_sensors(self.sensors)
        set_rate = bool(self.sampling_rate)
        if set_rate:
            self._dev.set_sampling_rate(self.sampling_rate)
        self.sampling_rate = self._dev.get_sampling_rate()
        from pyshimmer import EChannelType

        self._channels = [c for c in self._dev.get_data_types() if c != EChannelType.TIMESTAMP]
        self.columns = (["unix time (s)", "device time (s)"] + [c.name.lower() for c in self._channels])
        self.settings.update({"port": self.port, "sampling rate (Hz)": self.sampling_rate,
                              "device": self._dev.get_device_name(), "values": "raw ADC counts"})
        if any(name.startswith("exg_") for name in self.columns):
            self.settings["exg"] = self.configure_exg(self._dev, self.sampling_rate if set_rate else None)

    @staticmethod
    def configure_exg(dev, stream_rate: float | None, timeout: float = 5.0) -> dict:
        """Read the ExG chips' gains and data rates for ``session.json`` and, given ``stream_rate``, set their data
        rate to the lowest one not below it (only those bits of CONFIG1 change). A failure is reported in the result;
        the stream still works."""
        info: dict = {"reference voltage (V)": EXG_REFERENCE_V}
        try:
            for chip in (0, 1):
                reg = call_with_timeout(dev.get_exg_register, chip, timeout=timeout)
                if stream_rate is not None:
                    code = exg_rate_code(stream_rate)
                    config1 = bytearray(reg.binary)[0]
                    if config1 & 0b111 != code:
                        call_with_timeout(dev.set_exg_register, chip, 0, bytes([(config1 & ~0b111) | code]),
                                          timeout=timeout)
                        reg = call_with_timeout(dev.get_exg_register, chip, timeout=timeout)
                info[f"chip {chip + 1}"] = {"data rate (Hz)": reg.data_rate, "gain ch1": reg.ch1_gain,
                                            "gain ch2": reg.ch2_gain}
        except Exception as e:
            info["error"] = f"{type(e).__name__}: {e}"
        return info

    @staticmethod
    def sync_clock(dev, timeout: float = 5.0) -> dict:
        """Set the device's real-time clock to the computer's Unix time and read it back. Returns what happened
        for ``session.json``: the offset (device minus computer, s) after setting, which includes the Bluetooth
        round trip, or why it failed. Each call has a timeout, as pyshimmer waits for an answer forever."""
        def call(fn, *args):
            """Call a device function, giving up after ``timeout`` s."""
            return call_with_timeout(fn, *args, timeout=timeout)

        try:
            before = call(dev.get_rtc)
            asked = time.time()
            call(dev.set_rtc, asked)
            after = call(dev.get_rtc)
            now = time.time()
            return {"set": True, "offset before (s)": round(before - asked, 3),
                    "offset after (s)": round(after - now, 3)}
        except Exception as e:  # an old firmware without the command, a lost link: the stream still works
            return {"set": False, "error": f"{type(e).__name__}: {e}"}

    def _link(self):
        """A serial port, or, for a Bluetooth address (macOS), a direct RFCOMM channel to the paired Shimmer."""
        from pyshimmer import DEFAULT_BAUDRATE
        from serial import Serial

        from cwtool.logger.sources import rfcomm_mac

        if rfcomm_mac.is_address(self.port):
            if not rfcomm_mac.bluetooth_allowed():
                raise RuntimeError(
                    "This app may not use Bluetooth. Start the logger from Terminal and allow Bluetooth when "
                    "macOS asks (System Settings → Privacy & Security → Bluetooth).")
            return rfcomm_mac.RfcommSerial(self.port)
        return Serial(self.port, DEFAULT_BAUDRATE)

    def signals(self) -> list[str]:
        """Names of the channels being logged."""
        return self.columns[2:]

    def signal_values(self, row):
        """The (channel, value) pairs of a row, for the live plot."""
        for name, v in zip(self.columns[2:], row[2:]):
            yield name, v

    def run(self, emit, stopped: threading.Event) -> None:
        """Start streaming and emit each packet with its device time mapped onto Unix time, until stopped."""
        from pyshimmer import EChannelType

        def on_packet(pkt):
            """Callback for each packet: unwrap the device's clock, update the clock mapping and emit the row."""
            host = time.time()
            dev_t = self._unwrap(pkt[EChannelType.TIMESTAMP])
            offset = self._clock.update(dev_t, host)
            emit([(dev_t + offset, dev_t, *(pkt[c] for c in self._channels))])

        self._dev.add_stream_callback(on_packet)
        self._dev.start_streaming()
        try:
            stopped.wait()
        finally:
            self._dev.stop_streaming()
            self._dev.remove_stream_callback(on_packet)

    def close(self) -> None:
        """Shut the device's connection down."""
        if self._dev is not None:
            self._dev.shutdown()
