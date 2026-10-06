"""Shimmer3 (ECG, GSR, ...) over Bluetooth or the USB dock, through pyshimmer.

The Shimmer is streaming-configured: the sensors enabled on the device (in Consensys, or ``sensors`` here) are
logged as raw ADC values, one column per channel, plus the device's own clock. Calibration to mV or µS is
done in the analysis, as the raw values are what the device sends.
"""

from __future__ import annotations

import threading
import time

from cwtool.logger.base import ClockMapper, Source

TICKS_PER_SECOND = 32768.0
WRAP = 2**24  # the timestamp is 24 bits: it wraps every 512 s


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
    kind = "shimmer"

    def __init__(self, port: str, name: str = "shimmer", sampling_rate: float | None = None, sensors=None,
                 timeout: float = 10.0):
        super().__init__(name)
        self.timeout = timeout
        self.port, self.sampling_rate, self.sensors = port, sampling_rate, sensors
        self._dev = None
        self._channels = []
        self._emit = None
        self._unwrap = TimestampUnwrapper()
        self._clock = ClockMapper()
        self._t0_host = None

    def open(self) -> None:
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
        if self.sensors:
            self._dev.set_sensors(self.sensors)
        if self.sampling_rate:
            self._dev.set_sampling_rate(self.sampling_rate)
        self.sampling_rate = self._dev.get_sampling_rate()
        from pyshimmer import EChannelType

        self._channels = [c for c in self._dev.get_data_types() if c != EChannelType.TIMESTAMP]
        self.columns = (["unix time (s)", "device time (s)"] + [c.name.lower() for c in self._channels])
        self.settings = {"port": self.port, "sampling rate (Hz)": self.sampling_rate,
                         "device": self._dev.get_device_name(), "values": "raw ADC counts"}

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
        return self.columns[2:]

    def signal_values(self, row):
        for name, v in zip(self.columns[2:], row[2:]):
            yield name, v

    def run(self, emit, stopped: threading.Event) -> None:
        from pyshimmer import EChannelType

        def on_packet(pkt):
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
        if self._dev is not None:
            self._dev.shutdown()
