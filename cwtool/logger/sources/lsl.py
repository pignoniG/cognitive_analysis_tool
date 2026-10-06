"""Lab Streaming Layer streams, used for the EmotiBit (Oscilloscope's LSL output) and any other LSL device.

The EmotiBit Oscilloscope publishes one single-channel stream per signal (EDA, PPG_RED, ACC_X, HR, ...), all
with the device ID (``MD-V7-0000188``) as source ID. The streams matching a device go into one file in long
format, so signals of different rates share it:

    unix time (s), signal, value

with ``signal`` = the stream name (``<stream>.<channel>`` for multi-channel streams). LSL timestamps are put on
the computer's Unix time through LSL's own clock synchronisation (``time_correction`` and de-jittering).
"""

from __future__ import annotations

import time

from cwtool.logger.base import Source


def discover_streams(wait: float = 2.0) -> list[tuple[str, str, int, float]]:
    """(name, type, channels, nominal rate) of the LSL streams on the network."""
    import pylsl

    return [(i.name(), i.type(), i.channel_count(), i.nominal_srate()) for i in pylsl.resolve_streams(wait)]


def discover_devices(wait: float = 2.0) -> dict[str, list[str]]:
    """Stream names per source ID (the device) on the network, e.g. {"MD-V7-0000188": ["EDA", "HR", ...]}."""
    import pylsl

    devices: dict[str, list[str]] = {}
    for info in pylsl.resolve_streams(wait):
        devices.setdefault(info.source_id() or info.name(), []).append(info.name())
    return devices


def matches(info, text: str) -> bool:
    """Whether a stream belongs to ``text``: found in its source ID, name or type, ignoring case."""
    text = text.lower()
    return any(text in (field or "").lower() for field in (info.source_id(), info.name(), info.type()))


def channel_labels(info) -> list[str]:
    labels = []
    try:
        ch = info.desc().child("channels").child("channel")
        while ch.name() == "channel":
            labels.append(ch.child_value("label"))
            ch = ch.next_sibling()
    except Exception:
        labels = []
    n = info.channel_count()
    return labels if len(labels) == n and all(labels) else [str(i + 1) for i in range(n)]


def signal_names(info) -> list[str]:
    """Names of a stream's signals in the file: the stream name alone for a single channel."""
    if info.channel_count() == 1:
        return [info.name()]
    return [f"{info.name()}.{c}" for c in channel_labels(info)]


class LslSource(Source):
    kind = "lsl"

    def __init__(self, match: str = "", name: str = "emotibit", wait: float = 3.0):
        super().__init__(name)
        self.match, self.wait = match.lower(), wait
        self.columns = ["unix time (s)", "signal", "value"]
        self._inlets = []  # (inlet, [signal names])

    def open(self) -> None:
        import pylsl

        infos = [i for i in pylsl.resolve_streams(self.wait) if matches(i, self.match)]
        if not infos:
            raise RuntimeError(
                f"No LSL stream matching {self.match!r} (device ID, name or type). Is the device streaming and "
                "its LSL output enabled in the Oscilloscope?")
        flags = pylsl.proc_clocksync | pylsl.proc_dejitter
        for info in infos:
            self._inlets.append((pylsl.StreamInlet(info, max_buflen=60, processing_flags=flags), signal_names(info)))
        self.settings = {"match": self.match, "source ids": sorted({i.source_id() for i in infos}),
                         "streams": {i.name(): i.nominal_srate() for i in infos}}

    def signals(self) -> list[str]:
        return [s for _, sigs in self._inlets for s in sigs]

    def signal_values(self, row):
        yield row[1], row[2]

    def run(self, emit, stopped) -> None:
        import pylsl

        # LSL's clock is arbitrary (seconds since boot); this offset makes it Unix time.
        offset = time.time() - pylsl.local_clock()
        while not stopped.is_set():
            got = False
            for inlet, signals in self._inlets:
                samples, stamps = inlet.pull_chunk(timeout=0.0)
                if not stamps:
                    continue
                got = True
                emit([(ts + offset, sig, v) for ts, sample in zip(stamps, samples) for sig, v in zip(signals, sample)])
            if not got:
                stopped.wait(0.02)

    def close(self) -> None:
        for inlet, _ in self._inlets:
            inlet.close_stream()
        self._inlets = []
