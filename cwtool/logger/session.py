"""The logger: owns the sources, the live buffers, and the session folder being recorded."""

from __future__ import annotations

import csv
import json
import platform
import threading
import time
from collections import defaultdict, deque
from datetime import datetime
from pathlib import Path

from cwtool.logger.base import Source

LIVE_SECONDS = 60.0
LIVE_POINTS = 6000


class EventLog:
    """Phases of the experiment, written in the ``event_log`` format the analysis reads (the same columns as
    ``tools/event_logger.py``). A phase is appended when it ends, so a crash loses only the running one."""

    HEADER = ["Event", "Start Time", "End Time", "Duration (s)", "Start (unix s)", "End (unix s)"]

    def __init__(self, path: Path):
        self.path = Path(path)
        self._f = open(self.path, "w", newline="")
        self._w = csv.writer(self._f)
        self._w.writerow(self.HEADER)
        self._f.flush()
        self.current: tuple[str, float] | None = None

    def begin(self, label: str, now: float | None = None) -> None:
        """Start a phase; the running one, if any, ends at the same instant."""
        now = time.time() if now is None else now
        self.end(now)
        self.current = (label, now)

    def end(self, now: float | None = None) -> None:
        if self.current is None:
            return
        now = time.time() if now is None else now
        label, start = self.current
        self.current = None
        iso = lambda t: datetime.fromtimestamp(t).astimezone().isoformat()  # noqa: E731
        self._w.writerow([label, iso(start), iso(now), f"{now - start:.3f}", f"{start:.3f}", f"{now:.3f}"])
        self._f.flush()

    def close(self) -> None:
        self.end()
        self._f.close()


class Logger:
    """Sources feed live buffers all the time (so the signal can be checked before recording); while a session
    is recording they are also written to its folder:

        <folder>/<date>_<time>[_<label>]/
            lux/<month>_<day>_<hour>.csv     hourly files, as read by cwtool.lux
            <source>.csv                     one file per other source
            event_log.csv                    phases, if any were marked
            session.json                     sources, columns, start/end, clock

    The analysis takes the time span it needs from each file.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self.sources: dict[str, Source] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._stops: dict[str, threading.Event] = {}
        self.errors: dict[str, str] = {}
        self.counts: dict[str, int] = defaultdict(int)
        self.last_time: dict[str, float] = {}
        self._live: dict[tuple[str, str], deque] = {}
        self._sinks: dict[str, object] = {}
        self.session_folder: Path | None = None
        self.events: EventLog | None = None
        self._started = 0.0

    # sources

    def add(self, source: Source) -> None:
        """Connect a source (blocking) and start receiving its rows."""
        if source.name in self.sources:
            raise ValueError(f"A source named {source.name!r} already exists")
        source.open()
        with self._lock:
            self.sources[source.name] = source
            for sig in source.signals():
                self._live[(source.name, sig)] = deque(maxlen=LIVE_POINTS)
            self.counts[source.name] = 0
            if self.recording:  # connected while recording: its file starts now
                self._sinks[source.name] = self._make_sink(source)
        stop = threading.Event()
        self._stops[source.name] = stop
        t = threading.Thread(target=self._run, args=(source, stop), daemon=True, name=f"source-{source.name}")
        self._threads[source.name] = t
        t.start()

    def remove(self, name: str) -> None:
        stop = self._stops.pop(name, None)
        if stop:
            stop.set()
        t = self._threads.pop(name, None)
        if t:
            t.join(timeout=5)
        src = self.sources.pop(name, None)
        if src:
            src.close()
        with self._lock:
            sink = self._sinks.pop(name, None)
            if sink:
                sink.close()
            for key in [k for k in self._live if k[0] == name]:
                del self._live[key]

    def _run(self, source: Source, stop: threading.Event) -> None:
        try:
            source.run(lambda rows: self._on_rows(source, rows), stop)
        except Exception as e:  # shown by the window, the other sources keep going
            self.errors[source.name] = f"{type(e).__name__}: {e}"

    def _on_rows(self, source: Source, rows) -> None:
        if not rows:
            return
        with self._lock:
            self.counts[source.name] += len(rows)
            self.last_time[source.name] = rows[-1][0]
            for row in rows:
                for sig, v in source.signal_values(row):
                    buf = self._live.get((source.name, sig))
                    if buf is not None:
                        buf.append((row[0], v))
            sink = self._sinks.get(source.name)
            if sink is not None:
                sink.write(rows)

    def live(self, name: str, signal: str, seconds: float = 30.0):
        """(times, values) of the last ``seconds`` of a signal, for plotting."""
        with self._lock:
            data = list(self._live.get((name, signal), ()))
        if not data:
            return [], []
        end = data[-1][0]
        data = [d for d in data if d[0] >= end - seconds]
        return [d[0] for d in data], [d[1] for d in data]

    # recording

    @property
    def recording(self) -> bool:
        return self.session_folder is not None

    def start_recording(self, folder: Path, label: str = "") -> Path:
        if self.recording:
            raise RuntimeError("Already recording")
        now = time.time()
        stem = datetime.fromtimestamp(now).strftime("%Y-%m-%d_%H-%M-%S")
        label = "".join(c if c.isalnum() or c in "-_" else "_" for c in label.strip())
        session = Path(folder) / (f"{stem}_{label}" if label else stem)
        session.mkdir(parents=True, exist_ok=False)
        with self._lock:
            self._started = now
            self.session_folder = session
            self.events = EventLog(session / "event_log.csv")
            for name, src in self.sources.items():
                self._sinks[name] = self._make_sink(src)
                self.counts[name] = 0
        self._write_manifest(ended=None)
        return session

    def _make_sink(self, source: Source):
        return source.sink(self.session_folder / "lux" if source.kind == "lux" else self.session_folder)

    def stop_recording(self) -> Path | None:
        if not self.recording:
            return None
        with self._lock:
            session = self.session_folder
            for sink in self._sinks.values():
                sink.close()
            self._sinks.clear()
            if self.events:
                self.events.close()
            self.session_folder = None
            self.events = None
        self._write_manifest(ended=time.time(), folder=session)
        return session

    def mark(self, label: str) -> None:
        """Begin an experiment phase (ends the running one)."""
        if self.events:
            self.events.begin(label)

    def end_mark(self) -> None:
        if self.events:
            self.events.end()

    def _write_manifest(self, ended, folder: Path | None = None) -> None:
        folder = folder or self.session_folder
        start = datetime.fromtimestamp(self._started).astimezone()
        info = {
            "start (unix s)": self._started,
            "start": start.isoformat(),
            "end (unix s)": ended,
            "utc offset (s)": start.utcoffset().total_seconds(),
            "host": platform.node(),
            "time source": "unix time of the computer running this logger; device clocks are mapped onto it",
            "sources": {
                name: {"kind": s.kind, "columns": s.columns, "settings": s.settings,
                       "rows": self.counts.get(name, 0)}
                for name, s in self.sources.items()
            },
        }
        (folder / "session.json").write_text(json.dumps(info, indent=2))

    def shutdown(self) -> None:
        self.stop_recording()
        for name in list(self.sources):
            self.remove(name)
