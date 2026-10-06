"""Window of the multi-sensor logger. Start with ``cwtool-logger`` or ``python -m cwtool.logger``."""

from __future__ import annotations

import faulthandler
import os
import sys
import threading
import time
from pathlib import Path

# pyqtgraph takes whichever Qt binding it finds first; with PyQt6 also installed, two Qt copies in one process
# crash. Make it use the PySide6 the rest of the app uses.
os.environ.setdefault("PYQTGRAPH_QT_LIB", "PySide6")

from PySide6.QtCore import QSettings, Qt, QTimer
from PySide6.QtWidgets import (QApplication, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
                               QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox,
                               QPushButton, QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

import pyqtgraph as pg  # noqa: E402

from cwtool import palette
from cwtool.gui.plots import data_range
from cwtool.gui.workers import Task
from cwtool.logger.protocol import read_protocol
from cwtool.logger.session import Logger

REFRESH_MS = 100
PLOT_SECONDS = 30.0

# The recording button: green to start, red to stop (project colours; the light green gets dark text).
RECORD_STYLES = {
    False: f"QPushButton {{ background: {palette.GREEN}; color: #1b2b0e; }}"
           f"QPushButton:hover {{ background: #86c350; }}"
           f"QPushButton:pressed {{ background: #76b340; }}",
    True: f"QPushButton {{ background: {palette.RED}; color: white; }}"
          f"QPushButton:hover {{ background: #c92000; }}"
          f"QPushButton:pressed {{ background: #b01c00; }}",
}
RECORD_BASE = "QPushButton { font-size: 20px; font-weight: bold; border: none; border-radius: 8px; padding: 14px; }"


class StallWatchdog(threading.Thread):
    """Writes the stack of every thread to a file when the window stops answering for ``limit`` seconds, so a
    freeze can be traced to the call it is stuck in. The window calls :meth:`beat` from its refresh timer."""

    def __init__(self, path: Path, limit: float = 2.0):
        super().__init__(daemon=True, name="stall-watchdog")
        self.path, self.limit = Path(path), limit
        self._beat = time.monotonic()
        self._reported = False
        self._stop = threading.Event()

    def beat(self) -> None:
        self._beat = time.monotonic()
        self._reported = False

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        while not self._stop.wait(0.5):
            if not self._reported and time.monotonic() - self._beat > self.limit:
                self._reported = True
                try:
                    self.path.parent.mkdir(parents=True, exist_ok=True)
                    with open(self.path, "a") as f:
                        f.write(f"\n=== window not responding for over {self.limit:.0f} s, "
                                f"{time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
                        f.flush()
                        faulthandler.dump_traceback(file=f, all_threads=True)
                except OSError:
                    pass


def find_devices(kind: str):
    """What the add dialog lists: paired Shimmers (macOS) or the devices streaming over LSL. Slow (a subprocess,
    a network scan), so it runs in a background task, never in the window's thread."""
    try:
        if kind == "shimmer":
            from cwtool.logger.sources.rfcomm_mac import paired_devices

            return paired_devices("Shimmer")
        if kind == "emotibit":
            from cwtool.logger.sources import discover_devices

            return discover_devices(2.0)
    except ImportError:
        pass
    return None


class AddSourceDialog(QDialog):
    """Settings of a new source: ``kind`` is lux, shimmer, emotibit or simulated."""

    def __init__(self, kind: str, taken: set[str], found=None, parent=None):
        super().__init__(parent)
        self.kind = kind
        self.setWindowTitle({"lux": "Lux sensor", "shimmer": "Shimmer", "emotibit": "EmotiBit (LSL)",
                             "simulated": "Simulated sensor"}[kind])
        form = QFormLayout(self)
        default = kind if kind not in taken else next(f"{kind}_{i}" for i in range(2, 99) if f"{kind}_{i}" not in taken)
        self.name = QLineEdit(default)
        form.addRow("File name", self.name)
        self.port = QComboBox(editable=True)
        self.match = QComboBox(editable=True)
        if kind in ("lux", "shimmer"):
            if kind == "lux":
                self.port.addItem("Automatic", None)
            if kind == "shimmer":  # paired over Bluetooth (macOS): connected directly, not through a serial port
                for name, address in found or []:
                    self.port.addItem(f"{name}  (Bluetooth {address})", address)
            try:
                from cwtool.logger.sources import list_ports

                for device, desc in list_ports():
                    self.port.addItem(f"{device}  {desc}", device)
            except ImportError:
                pass
            form.addRow("Serial port" if kind == "lux" else "Serial port (Bluetooth or USB dock)", self.port)
        if kind == "emotibit":
            for device, streams in (found or {}).items():  # the devices streaming over LSL right now
                self.match.addItem(f"{device}  ({len(streams)} streams)", device)
            form.addRow("Device ID (LSL source)", self.match)
            form.addRow(QLabel("Start the EmotiBit Oscilloscope and enable its LSL output first."))
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def source(self):
        from cwtool.logger import sources

        name = self.name.text().strip() or self.kind
        port = self.port.currentData() or (self.port.currentText().split()[0] if self.port.currentText() not in
                                           ("", "Automatic") else None)
        if self.kind == "lux":
            return sources.LuxSerialSource(port, name=name)
        if self.kind == "shimmer":
            return sources.ShimmerSource(port, name=name)
        if self.kind == "emotibit":
            device = self.match.currentData() or self.match.currentText().split()[0:1] and self.match.currentText().split()[0]
            return sources.LslSource(device or "", name=name)
        return sources.SimulatedSource(name)


def plot_range(values, pad: float = 0.08, trim: float = 0.5):
    """(low, high) for the value axis of a live plot: the span of the data, without the outer ``trim`` percent
    so a single spike does not flatten the signal, plus ``pad`` of the span on both sides. A flat signal gets a
    range of 1 % of its level (at least 0.1), so noise of one count is not magnified to the full plot height."""
    lo, hi = data_range(values, trim)
    if lo is None:
        return None, None
    min_span = max(0.01 * max(abs(lo), abs(hi)), 0.1)
    if hi - lo < min_span:
        mid = (lo + hi) / 2
        lo, hi = mid - min_span / 2, mid + min_span / 2
    margin = pad * (hi - lo)
    return lo - margin, hi + margin


class SourcePlot(pg.PlotWidget):
    """Live view of one signal of one source."""

    def __init__(self, logger: Logger, name: str):
        super().__init__()
        self.logger, self.name = logger, name
        self.setMinimumHeight(110)
        self.setBackground(None)
        self.showGrid(x=True, y=True, alpha=0.2)
        self.setLabel("bottom", "s")
        self.setMouseEnabled(x=False, y=False)  # the view follows the data
        self.enableAutoRange(x=False, y=False)
        self.setXRange(-PLOT_SECONDS, 0, padding=0)
        self.signal = QComboBox()
        self.curve = self.plot(pen=pg.mkPen(palette.ACCENT, width=1.5))
        self.setTitle(name)
        self._signals = []

    def refresh(self) -> None:
        signals = self.logger.sources[self.name].signals() if self.name in self.logger.sources else []
        if signals != self._signals:
            current = self.signal.currentText()
            self._signals = signals
            self.signal.blockSignals(True)
            self.signal.clear()
            self.signal.addItems(signals)
            if current in signals:
                self.signal.setCurrentText(current)
            self.signal.blockSignals(False)
        t, v = self.logger.live(self.name, self.signal.currentText(), PLOT_SECONDS)
        if t:
            self.curve.setData([x - t[-1] for x in t], v)
            lo, hi = plot_range(v)
            if lo is not None:
                self.setYRange(lo, hi, padding=0)


class LoggerWindow(QMainWindow):
    def __init__(self, logger: Logger | None = None):
        super().__init__()
        self.setWindowTitle("Cognitive Workload Tool: sensor logger")
        self.resize(1200, 800)
        self.logger = logger or Logger()
        self._settings = QSettings("cwtool", "cwtool-logger")
        self._tasks: list[Task] = []
        self._plots: dict[str, SourcePlot] = {}
        self._rec_start = 0.0
        self._protocol: list[tuple[str, float | None]] = []
        self._phase = -1
        self._phase_end: float | None = None

        left = QWidget()
        lv = QVBoxLayout(left)
        lv.addWidget(self._build_sources())
        lv.addWidget(self._build_session())
        lv.addWidget(self._build_events())
        lv.addStretch(1)
        self.plots_layout = QVBoxLayout()
        right = QWidget()
        right.setLayout(self.plots_layout)
        split = QSplitter()
        split.addWidget(left)
        split.addWidget(right)
        split.setStretchFactor(1, 1)
        self.setCentralWidget(split)
        self.statusBar().showMessage("Add the sensors, check the signals, then press Record.")

        self._watchdog = StallWatchdog(Path(str(self._settings.value("folder", str(Path.home() / "cwtool_logs"))))
                                       / "stall.log")
        self._watchdog.start()
        self._timer = QTimer(self, interval=REFRESH_MS)
        self._timer.timeout.connect(self._refresh)
        self._timer.start()

    # building

    def _build_sources(self) -> QGroupBox:
        box = QGroupBox("Sensors")
        v = QVBoxLayout(box)
        row = QHBoxLayout()
        for kind, text in (("lux", "Lux"), ("shimmer", "Shimmer"), ("emotibit", "EmotiBit"), ("simulated", "Simulated")):
            b = QPushButton(f"+ {text}")
            b.clicked.connect(lambda _=False, k=kind: self.add_source(k))
            row.addWidget(b)
        v.addLayout(row)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Sensor", "Status", "Rows", "Last"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().hide()
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        v.addWidget(self.table)
        rm = QPushButton("Remove selected")
        rm.clicked.connect(self.remove_selected)
        v.addWidget(rm)
        return box

    def _build_session(self) -> QGroupBox:
        box = QGroupBox("Recording")
        f = QFormLayout(box)
        self.folder = QLineEdit(str(self._settings.value("folder", str(Path.home() / "cwtool_logs"))))
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)
        row = QHBoxLayout()
        row.addWidget(self.folder)
        row.addWidget(browse)
        f.addRow("Folder", row)
        self.record = QPushButton()
        self.record.setMinimumHeight(64)
        self.record.setCursor(Qt.PointingHandCursor)
        self.record.clicked.connect(self.toggle_recording)
        self._style_record(False)
        self.elapsed = QLabel("")
        self.elapsed.setStyleSheet("font-size: 18px;")
        self.elapsed.setMinimumWidth(64)  # reserved, so the button does not resize when the timer appears
        row = QHBoxLayout()
        row.addWidget(self.record, 1)
        row.addWidget(self.elapsed)
        f.addRow(row)
        return box

    def _build_events(self) -> QGroupBox:
        box = QGroupBox("Events")
        v = QVBoxLayout(box)
        row = QHBoxLayout()
        self.event_label = QLineEdit()
        self.event_label.setPlaceholderText("event name")
        self.event_label.returnPressed.connect(self.begin_event)
        begin = QPushButton("Begin")
        begin.clicked.connect(self.begin_event)
        end = QPushButton("End")
        end.clicked.connect(self.logger.end_mark)
        for w in (self.event_label, begin, end):
            row.addWidget(w)
        v.addLayout(row)
        row = QHBoxLayout()
        load = QPushButton("Load protocol…")
        load.clicked.connect(self.load_protocol)
        self.run_protocol = QPushButton("Start protocol")
        self.run_protocol.clicked.connect(self.start_protocol)
        self.next_phase = QPushButton("Next phase")
        self.next_phase.clicked.connect(self.advance_protocol)
        for w in (load, self.run_protocol, self.next_phase):
            row.addWidget(w)
        v.addLayout(row)
        self.phase_label = QLabel("No protocol loaded")
        v.addWidget(self.phase_label)
        return box

    # sources

    def add_source(self, kind: str) -> None:
        if kind in ("shimmer", "emotibit"):  # looking for devices takes seconds: not in the window's thread
            self.statusBar().showMessage("Looking for devices…")
            task = Task(lambda progress, cancelled: find_devices(kind), self)
            task.succeeded.connect(lambda found: self._ask_source(kind, found))
            task.failed.connect(lambda _msg: self._ask_source(kind, None))
            self._tasks.append(task)
            task.start()
        else:
            self._ask_source(kind, None)

    def _ask_source(self, kind: str, found) -> None:
        self.statusBar().clearMessage()
        dlg = AddSourceDialog(kind, set(self.logger.sources), found, self)
        if dlg.exec() != QDialog.Accepted:
            return
        source = dlg.source()
        self.statusBar().showMessage(f"Connecting {source.name}…")
        task = Task(lambda progress, cancelled: self.logger.add(source) or source.name, self)
        task.succeeded.connect(self._connected)
        task.failed.connect(lambda msg: QMessageBox.warning(self, "Could not connect", msg.split("\n\n")[0]))
        self._tasks.append(task)
        task.start()

    def _connected(self, name: str) -> None:
        plot = SourcePlot(self.logger, name)
        row = QHBoxLayout()
        row.addWidget(QLabel(name))
        row.addWidget(plot.signal)
        row.addStretch(1)
        holder = QWidget()
        lay = QVBoxLayout(holder)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addLayout(row)
        lay.addWidget(plot)
        plot.holder = holder
        self._plots[name] = plot
        self.plots_layout.addWidget(holder)
        self.statusBar().showMessage(f"{name} connected")

    def remove_selected(self) -> None:
        item = self.table.currentItem()
        if item is None:
            return
        name = self.table.item(item.row(), 0).text()
        self.logger.remove(name)
        plot = self._plots.pop(name, None)
        if plot:
            plot.holder.deleteLater()

    # recording

    def _browse(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Folder for the recordings", self.folder.text())
        if d:
            self.folder.setText(d)

    def toggle_recording(self) -> None:
        if self.logger.recording:
            session = self.logger.stop_recording()
            self._stop_protocol()
            self.statusBar().showMessage(f"Saved to {session}")
            return
        if not self.logger.sources:
            QMessageBox.information(self, "Nothing to record", "Add a sensor first.")
            return
        self._settings.setValue("folder", self.folder.text())
        try:
            session = self.logger.start_recording(Path(self.folder.text()))
        except OSError as e:
            QMessageBox.warning(self, "Cannot record", str(e))
            return
        self._rec_start = time.time()
        self.statusBar().showMessage(f"Recording to {session}")

    def _style_record(self, recording: bool) -> None:
        self.record.setText("Stop recording" if recording else "Start recording")
        self.record.setStyleSheet(RECORD_BASE + RECORD_STYLES[recording])

    # events

    def begin_event(self) -> None:
        label = self.event_label.text().strip()
        if label and self.logger.recording:
            self.logger.mark(label)

    def load_protocol(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Protocol", "", "CSV (*.csv)")
        if not path:
            return
        try:
            self._protocol = read_protocol(Path(path))
        except (OSError, ValueError) as e:
            QMessageBox.warning(self, "Protocol", str(e))
            return
        self._phase = -1
        self.phase_label.setText(f"{len(self._protocol)} phases loaded from {Path(path).name}")

    def start_protocol(self) -> None:
        if not self._protocol or not self.logger.recording:
            self.statusBar().showMessage("Load a protocol and start recording first.")
            return
        self._phase = -1
        self.advance_protocol()

    def advance_protocol(self) -> None:
        if not self.logger.recording or not self._protocol:
            return
        self._phase += 1
        if self._phase >= len(self._protocol):
            self._stop_protocol()
            self.phase_label.setText("Protocol finished")
            return
        name, duration = self._protocol[self._phase]
        self.logger.mark(name)
        self._phase_end = time.time() + duration if duration is not None else None

    def _stop_protocol(self) -> None:
        self._phase, self._phase_end = -1, None
        self.logger.end_mark()

    # refresh

    def _refresh(self) -> None:
        self._watchdog.beat()
        now = time.time()
        sources = self.logger.sources
        self.table.setRowCount(len(sources))
        for r, (name, src) in enumerate(sources.items()):
            err = self.logger.errors.get(name)
            last = self.logger.last_time.get(name)
            age = None if last is None else now - last
            status = err or ("waiting for data" if age is None else "ok" if age < 3 else f"silent {age:.0f} s")
            for c, text in enumerate([name, status, str(self.logger.counts.get(name, 0)),
                                      "" if age is None else f"{age:.1f} s"]):
                self.table.setItem(r, c, QTableWidgetItem(text))
        if "disk" in self.logger.errors:  # a write failed (full disk, ...): the recording goes on without those rows
            self.statusBar().showMessage(f"Could not write to disk: {self.logger.errors['disk']}")
        for plot in self._plots.values():
            if plot.name in sources:
                plot.refresh()
        if self.logger.recording:
            if self.record.text() != "Stop recording":
                self._style_record(True)
            self.elapsed.setText(f"{int(now - self._rec_start) // 60:02d}:{int(now - self._rec_start) % 60:02d}")
        else:
            if self.record.text() != "Start recording":
                self._style_record(False)
            self.elapsed.setText("")
        if self._phase_end is not None and now >= self._phase_end:
            self.advance_protocol()
        if self._phase >= 0 and self._phase < len(self._protocol):
            name, duration = self._protocol[self._phase]
            left = "" if self._phase_end is None else f" ({max(self._phase_end - now, 0):.0f} s left)"
            self.phase_label.setText(f"Phase {self._phase + 1}/{len(self._protocol)}: {name}{left}")

    def closeEvent(self, event) -> None:
        if self.logger.recording and QMessageBox.question(
                self, "Recording", "Stop recording and quit?") != QMessageBox.Yes:
            event.ignore()
            return
        self._timer.stop()
        self._watchdog.stop()
        self.logger.shutdown()
        event.accept()


def main(argv: list[str] | None = None) -> int:
    from cwtool.gui import apply_palette

    app = QApplication(sys.argv if argv is None else argv)
    app.setApplicationName("cwtool-logger")
    apply_palette(app)
    window = LoggerWindow()
    window.show()
    return app.exec()
