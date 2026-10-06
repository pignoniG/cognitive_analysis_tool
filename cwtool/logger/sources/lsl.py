"""Lab Streaming Layer streams, used for the EmotiBit (Oscilloscope's LSL output) and any other LSL device.

All matching streams go into one file in long format, so streams of different rates share it:

    unix time (s), signal, value

with ``signal`` = ``<stream>.<channel>``. LSL timestamps are put on the computer's Unix time through LSL's own
clock synchronisation (``time_correction`` and de-jittering).
"""

from __future__ import annotations

import time

from cwtool.logger.base import Source


def discover_streams(wait: float = 2.0) -> list[tuple[str, str, int, float]]:
    """(name, type, channels, nominal rate) of the LSL streams on the network."""
    import pylsl

    return [(i.name(), i.type(), i.channel_count(), i.nominal_srate()) for i in pylsl.resolve_streams(wait)]


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


class LslSource(Source):
    kind = "lsl"

    def __init__(self, match: str = "emotibit", name: str = "emotibit", wait: float = 3.0):
        super().__init__(name)
        self.match, self.wait = match.lower(), wait
        self.columns = ["unix time (s)", "signal", "value"]
        self._inlets = []  # (inlet, [signal names])

    def open(self) -> None:
        import pylsl

        infos = [i for i in pylsl.resolve_streams(self.wait) if self.match in i.name().lower()]
        if not infos:
            raise RuntimeError(f"No LSL stream with {self.match!r} in its name; is the device streaming?")
        flags = pylsl.proc_clocksync | pylsl.proc_dejitter
        for info in infos:
            signals = [f"{info.name()}.{c}" for c in channel_labels(info)]
            self._inlets.append((pylsl.StreamInlet(info, max_buflen=60, processing_flags=flags), signals))
        self.settings = {"streams": [i.name() for i in infos], "match": self.match}

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
