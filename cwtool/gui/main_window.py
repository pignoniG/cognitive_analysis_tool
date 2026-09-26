"""Main window: load a recording, analyse its video, tune parameters live, export."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings, Qt, QTimer
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (QCheckBox, QDoubleSpinBox, QFileDialog, QFormLayout, QGroupBox,
                               QHBoxLayout, QLabel, QMainWindow, QMessageBox, QProgressBar,
                               QPushButton, QScrollArea, QSplitter, QVBoxLayout, QWidget)

from cwtool import __version__, calibration, devices, pipeline
from cwtool.gui.param_panel import ParameterPanel
from cwtool.gui.plots import ResultPlots, rms_in
from cwtool.gui.workers import Task
from cwtool.params import Parameters
from cwtool.video import VideoResult, analyse_video

RECOMPUTE_DELAY_MS = 150


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"Cognitive Workload Tool {__version__}")
        self.resize(1400, 900)
        self._settings = QSettings("cwtool", "cwtool")
        self.recording = None
        self.video = None
        self.result = None
        self._task: Task | None = None
        self._params_path: Path | None = None

        self._recompute_timer = QTimer(self, singleShot=True, interval=RECOMPUTE_DELAY_MS)
        self._recompute_timer.timeout.connect(self.recompute)

        self._build_actions()
        self._build_ui()
        self._update_state()

    # UI

    def _build_actions(self) -> None:
        def action(text, slot, shortcut=None):
            a = QAction(text, self)
            a.triggered.connect(slot)
            if shortcut:
                a.setShortcut(shortcut)
            return a

        self.open_action = action("Open recording…", self.choose_recording, QKeySequence.Open)
        self.load_params_action = action("Load parameters…", self.choose_params)
        self.save_params_action = action("Save parameters", self.save_params, QKeySequence.Save)
        self.save_params_as_action = action("Save parameters as…", self.save_params_as, QKeySequence.SaveAs)
        self.export_action = action("Export results…", self.export)
        quit_action = action("Quit", self.close, QKeySequence.Quit)

        file_menu = self.menuBar().addMenu("&File")
        for a in (self.open_action, None, self.load_params_action, self.save_params_action,
                  self.save_params_as_action, None, self.export_action, None, quit_action):
            file_menu.addSeparator() if a is None else file_menu.addAction(a)

        toolbar = self.addToolBar("Main")
        toolbar.setMovable(False)
        for a in (self.open_action, self.load_params_action, self.save_params_action, self.export_action):
            toolbar.addAction(a)

    def _build_ui(self) -> None:
        # Left: recording, video, calibration and parameters.
        side = QWidget()
        side_layout = QVBoxLayout(side)

        rec_box = QGroupBox("Recording")
        rec_layout = QVBoxLayout(rec_box)
        self.recording_label = QLabel("No recording loaded")
        self.recording_label.setWordWrap(True)
        self.recording_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        rec_layout.addWidget(self.recording_label)
        side_layout.addWidget(rec_box)

        video_box = QGroupBox("Scene video")
        video_layout = QVBoxLayout(video_box)
        self.video_label = QLabel("–")
        self.video_label.setWordWrap(True)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setTextVisible(False)
        self.progress.hide()
        buttons = QHBoxLayout()
        self.analyse_button = QPushButton("Analyse video")
        self.analyse_button.clicked.connect(lambda: self.analyse(use_cache=False))
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.cancel_task)
        buttons.addWidget(self.analyse_button)
        buttons.addWidget(self.cancel_button)
        video_layout.addWidget(self.video_label)
        video_layout.addWidget(self.progress)
        video_layout.addLayout(buttons)
        side_layout.addWidget(video_box)

        cal_box = QGroupBox("Calibration sequence")
        cal_layout = QFormLayout(cal_box)
        self.sequence_check = QCheckBox("Show sequence overlay")
        self.sequence_check.toggled.connect(self._sequence_changed)
        self.sequence_start = QDoubleSpinBox()
        self.sequence_start.setRange(-1e6, 1e6)
        self.sequence_start.setDecimals(2)
        self.sequence_start.setSingleStep(0.5)
        self.sequence_start.setSuffix(" s")
        self.sequence_start.setToolTip("Drag the grey line on the plot or type a value")
        self.sequence_start.valueChanged.connect(self._sequence_changed)
        self.sequence_rms = QLabel("–")
        cal_layout.addRow(self.sequence_check)
        cal_layout.addRow("Start", self.sequence_start)
        cal_layout.addRow("ΔPD RMS in sequence", self.sequence_rms)
        side_layout.addWidget(cal_box)

        self.params_panel = ParameterPanel()
        self.params_panel.params_changed.connect(self._params_edited)
        self.params_panel.video_settings_changed.connect(self._video_settings_edited)
        side_layout.addWidget(self.params_panel)

        scroll = QScrollArea()
        scroll.setWidget(side)
        scroll.setWidgetResizable(True)
        scroll.setMinimumWidth(360)

        # Right: summary line and plots.
        right = QWidget()
        right_layout = QVBoxLayout(right)
        self.summary_label = QLabel()
        self.summary_label.setStyleSheet("font-size: 14px; padding: 4px;")
        self.plots = ResultPlots()
        self.plots.sequence_start_changed.connect(self._sequence_dragged)
        right_layout.addWidget(self.summary_label)
        right_layout.addWidget(self.plots, 1)

        splitter = QSplitter()
        splitter.addWidget(scroll)
        splitter.addWidget(right)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([380, 1020])
        self.setCentralWidget(splitter)

    def _update_state(self) -> None:
        busy = self._task is not None and self._task.isRunning()
        has_rec = self.recording is not None
        self.analyse_button.setEnabled(has_rec and not busy and self.recording.scene_video is not None)
        self.cancel_button.setEnabled(busy)
        self.open_action.setEnabled(not busy)
        self.export_action.setEnabled(self.result is not None)
        if self.result is None:
            self.summary_label.setText("Open a recording to start." if not has_rec else "")
        else:
            r = self.result
            self.summary_label.setText(
                f"<b>ΔPD RMS</b> {r.cw_rms:.3f} mm &nbsp;&nbsp; "
                f"expected PD at black {r.expected_black:.2f} mm, white {r.expected_white:.2f} mm &nbsp;&nbsp; "
                f"measured offset {r.offset:+.2f} mm")
        name = self._params_path.name if self._params_path else "unsaved parameters"
        rec = f" — {self.recording.name}" if has_rec else ""
        self.setWindowTitle(f"Cognitive Workload Tool {__version__}{rec} ({name})")

    def _error(self, title: str, message: str) -> None:
        box = QMessageBox(QMessageBox.Warning, title, message.split("\n\n")[0], parent=self)
        if "\n\n" in message:
            box.setDetailedText(message.split("\n\n", 1)[1])
        box.exec()

    # Recording and video

    def choose_recording(self) -> None:
        start = self._settings.value("last_recording_dir", str(Path.home()))
        folder = QFileDialog.getExistingDirectory(self, "Open recording folder", start)
        if folder:
            self._settings.setValue("last_recording_dir", str(Path(folder).parent))
            self.open_recording(Path(folder))

    def open_recording(self, folder: Path) -> None:
        def load(progress, cancelled):
            return devices.load(folder)

        self._start_task(load, self._recording_loaded, f"Loading {folder.name}…")

    def _recording_loaded(self, rec) -> None:
        self.recording, self.video, self.result = rec, None, None
        duration = rec.time[-1] - rec.time[0] if len(rec.time) else 0
        video = rec.scene_video.name if rec.scene_video else "none"
        self.recording_label.setText(
            f"<b>{rec.name}</b><br>{rec.device}, {len(rec.time)} samples, {duration:.1f} s"
            f"<br>video: {video}<br>events: {len(rec.events)}")
        self.plots.clear_result()
        self.plots.show_events(rec.events)
        self.params_panel.set_video_settings(self.params_panel.video_settings().for_recording(rec))
        self._update_state()
        if rec.scene_video is None:
            self.video_label.setText("No scene video found in this recording.")
        else:
            self.analyse(use_cache=True)

    def analyse(self, use_cache: bool) -> None:
        rec = self.recording
        settings = self.params_panel.video_settings().for_recording(rec)
        if use_cache:
            cached = VideoResult.load_cached(rec.folder, settings, rec.scene_video)
            if cached is not None:
                self._video_ready(cached, "cached analysis")
                return

        def work(progress, cancelled):
            res = analyse_video(rec.scene_video, rec.time, rec.gaze, settings, progress, cancelled)
            if cancelled():
                return None
            res.save(rec.folder, settings, rec.scene_video)
            return res

        self._start_task(work, lambda res: res and self._video_ready(res, "analysed"),
                         f"Analysing {rec.scene_video.name}…", show_progress=True)

    def _video_ready(self, video: VideoResult, how: str) -> None:
        self.video = video
        self.video_label.setText(f"{self.recording.scene_video.name}: {len(video.time)} samples ({how})")
        self.recompute()

    def _video_settings_edited(self) -> None:
        if self.video is not None:
            self.video_label.setText("Video settings changed: press Analyse video to apply.")

    # Tasks

    def _start_task(self, fn, on_success, message: str, show_progress: bool = False) -> None:
        if self._task is not None and self._task.isRunning():
            return
        self.statusBar().showMessage(message)
        self._task = Task(fn, self)
        self._task.progressed.connect(lambda p: self.progress.setValue(int(p * 1000)))
        self._task.succeeded.connect(on_success)
        self._task.failed.connect(lambda msg: self._error("Error", msg))
        self._task.finished.connect(self._task_finished)
        self.progress.setValue(0)
        self.progress.setVisible(show_progress)
        self._task.start()
        self._update_state()

    def _task_finished(self) -> None:
        self.progress.hide()
        self.statusBar().clearMessage()
        self._update_state()

    def cancel_task(self) -> None:
        if self._task is not None:
            self._task.cancel()

    # Parameters and results

    def _params_edited(self) -> None:
        self._recompute_timer.start()

    def recompute(self) -> None:
        if self.recording is None or self.video is None:
            return
        try:
            self.result = pipeline.run(self.recording, self.video, self.params_panel.params())
        except Exception as e:
            self.result = None
            self.statusBar().showMessage(f"Analysis failed: {e}")
            self.plots.clear_result()
        else:
            self.plots.show_result(self.result)
            self._update_sequence_rms()
        self._update_state()

    def _sequence_changed(self) -> None:
        self.plots.set_sequence(self.sequence_check.isChecked(), self.sequence_start.value())
        self._update_sequence_rms()

    def _sequence_dragged(self, start: float) -> None:
        self.sequence_start.blockSignals(True)
        self.sequence_start.setValue(start)
        self.sequence_start.blockSignals(False)
        self._update_sequence_rms()

    def _update_sequence_rms(self) -> None:
        if self.result is None or not self.sequence_check.isChecked():
            self.sequence_rms.setText("–")
            return
        s = self.sequence_start.value()
        self.sequence_rms.setText(f"{rms_in(self.result, s, s + calibration.DURATION):.3f} mm")

    def choose_params(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Load parameters", self._params_dir(), "Parameters (*.json)")
        if path:
            try:
                self.params_panel.set_params(Parameters.load(path))
            except Exception as e:
                self._error("Cannot load parameters", str(e))
                return
            self._params_path = Path(path)
            self._update_state()

    def save_params(self) -> None:
        if self._params_path is None:
            self.save_params_as()
        else:
            self.params_panel.params().save(self._params_path)
            self.statusBar().showMessage(f"Saved {self._params_path}", 3000)

    def save_params_as(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Save parameters", self._params_dir(), "Parameters (*.json)")
        if path:
            if not path.endswith(".json"):
                path += ".json"
            self._params_path = Path(path)
            self._settings.setValue("last_params_dir", str(self._params_path.parent))
            self.save_params()
            self._update_state()

    def _params_dir(self) -> str:
        return self._settings.value("last_params_dir", str(Path.home()))

    def export(self) -> None:
        if self.result is None:
            return
        default = str(self.recording.folder / "cwtool_export")
        folder = QFileDialog.getExistingDirectory(self, "Export to folder", default)
        if not folder:
            return
        paths = pipeline.export(self.result, self.recording, self.params_panel.params(), Path(folder))
        try:
            from cwtool.plot import plot_result
            p = Path(folder) / f"{self.recording.name}_plot.pdf"
            plot_result(self.result, self.recording).savefig(p, bbox_inches="tight")
            paths.append(p)
        except ImportError:
            pass
        self.statusBar().showMessage(f"Exported {len(paths)} files to {folder}", 5000)

    def closeEvent(self, event) -> None:
        if self._task is not None and self._task.isRunning():
            self._task.cancel()
            self._task.wait(5000)
        super().closeEvent(event)
