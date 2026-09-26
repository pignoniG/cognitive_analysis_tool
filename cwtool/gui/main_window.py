"""Main window: load a recording, analyse its video, tune parameters live, export."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings, Qt, QTimer
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (QCheckBox, QDockWidget, QDoubleSpinBox, QFileDialog, QFormLayout, QGroupBox,
                               QHBoxLayout, QLabel, QMainWindow, QMessageBox, QProgressBar,
                               QPushButton, QScrollArea, QSplitter, QVBoxLayout, QWidget)

from cwtool import __version__, calibration, devices, pipeline
from cwtool.fit import fit_calibration
from cwtool.gui.param_panel import ParameterPanel
from cwtool.gui.plots import ResultPlots, rms_in
from cwtool.gui.video_preview import VideoPreview
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
        self._restore_sequence()
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

        self.view_menu = self.menuBar().addMenu("&View")

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
        self.sequence = calibration.DEFAULT
        self.sequence_label = QLabel()
        self.sequence_label.setWordWrap(True)
        sequence_buttons = QHBoxLayout()
        load_sequence = QPushButton("Load sequence…")
        load_sequence.setToolTip("The timestamped RGB CSV played by the calibration scene")
        load_sequence.clicked.connect(self.choose_sequence)
        default_sequence = QPushButton("Built-in")
        default_sequence.clicked.connect(lambda: self.set_sequence(calibration.DEFAULT))
        sequence_buttons.addWidget(load_sequence)
        sequence_buttons.addWidget(default_sequence)
        cal_layout.addRow(self.sequence_label)
        cal_layout.addRow(sequence_buttons)
        cal_layout.addRow(self.sequence_check)
        cal_layout.addRow("Start", self.sequence_start)
        cal_layout.addRow("ΔPD RMS in sequence", self.sequence_rms)
        self.fit_dynamics_check = QCheckBox("Include dilation/constriction time constants")
        self.fit_dynamics_check.setChecked(True)
        self.fit_button = QPushButton("Fit latency, scale and offset")
        self.fit_button.setToolTip("Fits the pupil parameters on the sequence, given the current photometric "
                                   "calibration. Adjust Lmin, Lmax, gains and gamma first.")
        self.fit_button.clicked.connect(self.fit_sequence)
        cal_layout.addRow(self.fit_dynamics_check)
        cal_layout.addRow(self.fit_button)
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

        self.preview = VideoPreview()
        self.preview.time_changed.connect(self.plots.set_cursor)
        self.plots.cursor_changed.connect(self.preview.show_time)
        dock = QDockWidget("Video preview", self)
        dock.setObjectName("video_preview")
        dock.setWidget(self.preview)
        self.addDockWidget(Qt.RightDockWidgetArea, dock)
        self.resizeDocks([dock], [420], Qt.Horizontal)
        self.view_menu.addAction(dock.toggleViewAction())

    def _restore_sequence(self) -> None:
        path = self._settings.value("last_sequence", "")
        sequence = calibration.DEFAULT
        if path and Path(path).exists():
            try:
                sequence = calibration.load_sequence(path)
            except Exception:
                pass
        self.set_sequence(sequence)

    def _update_state(self) -> None:
        busy = self._task is not None and self._task.isRunning()
        has_rec = self.recording is not None
        self.analyse_button.setEnabled(has_rec and not busy and self.recording.scene_video is not None)
        self.cancel_button.setEnabled(busy)
        self.open_action.setEnabled(not busy)
        self.export_action.setEnabled(self.result is not None)
        self.fit_button.setEnabled(self.result is not None and self.sequence_check.isChecked() and not busy)
        if self.result is None:
            self.summary_label.setText("Open a recording to start." if not has_rec else "")
        else:
            r = self.result
            gaps = f" &nbsp;&nbsp; gaps {r.gap_fraction:.0%}" if r.gap_fraction >= 0.005 else ""
            warn = "".join(f"<br><span style='color:#c00'>⚠ {w}</span>" for w in r.warnings)
            self.summary_label.setText(
                f"<b>ΔPD RMS</b> {r.cw_rms:.3f} mm &nbsp; <b>SD</b> {r.cw_sd:.3f} mm &nbsp;&nbsp; "
                f"expected PD at black {r.expected_black:.2f} mm, white {r.expected_white:.2f} mm &nbsp;&nbsp; "
                f"pupil ×{r.pupil_scale:.3g}, offset {r.offset:+.2f} mm &nbsp;&nbsp; "
                f"{r.measured_rate:.0f} Hz → {r.rate:.0f} Hz{gaps}{warn}")
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
        prof = rec.profile
        scale = f"×{prof.pupil_scale:g}" if prof.pupil_scale else "scale fitted"
        self.recording_label.setText(
            f"<b>{rec.name}</b><br>{rec.device}, {len(rec.time)} samples, {duration:.1f} s, "
            f"{rec.measured_rate:.0f} Hz<br>field of view {prof.field_of_view[0]:g}° × "
            f"{prof.field_of_view[1]:g}° ({prof.field_area:,.0f} deg²), pupil {prof.pupil_unit} {scale}"
            f"<br>video: {video}<br>events: {len(rec.events)}")
        self.plots.clear_result()
        self.plots.show_events(rec.events)
        self.params_panel.set_video_settings(self.params_panel.video_settings().for_recording(rec))
        self.preview.set_recording(rec, self.params_panel.video_settings())
        if len(rec.time):
            self.plots.set_cursor(float(rec.time[0]))
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
        if self.recording is not None:
            self.preview.set_settings(self.params_panel.video_settings().for_recording(self.recording))
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
        self.preview.set_analysis(self.video, self.result)
        self._update_state()

    def _sequence_changed(self) -> None:
        self.plots.set_sequence(self.sequence_check.isChecked(), self.sequence_start.value(), self.sequence)
        self._update_sequence_rms()
        self._update_state()

    def fit_sequence(self) -> None:
        rec, video, params = self.recording, self.video, self.params_panel.params()
        start, dynamics = self.sequence_start.value(), self.fit_dynamics_check.isChecked()
        end = start + self.sequence.duration

        def work(progress, cancelled):
            return fit_calibration(rec, video, params, start, end, fit_dynamics=dynamics, cancelled=cancelled)

        self._start_task(work, self._fit_done, "Fitting on the calibration sequence…")

    def _fit_done(self, fit) -> None:
        dyn = (f"<br>dilation τ {fit.attack:.2f} s, constriction τ {fit.release:.2f} s"
               if fit.params.dynamics else "")
        notes = "".join(f"<br><span style='color:#c00'>⚠ {n}</span>" for n in fit.notes)
        box = QMessageBox(QMessageBox.Question, "Calibration fit",
                          f"<b>ΔPD RMS in sequence: {fit.rms_before:.3f} → {fit.rms_after:.3f} mm</b><br><br>"
                          f"latency {fit.delay:.2f} s{dyn}<br>"
                          f"pupil scale correction {fit.pupil_correction:.3f}, offset {fit.pupil_offset:+.3f} mm"
                          f"{notes}<br><br>Apply? Alignment will be set to 'fixed' so these values carry over "
                          f"to this participant's other recordings.",
                          QMessageBox.Apply | QMessageBox.Cancel, self)
        if box.exec() == QMessageBox.Apply:
            self.params_panel.set_params(fit.params)

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
        self.sequence_rms.setText(f"{rms_in(self.result, s, s + self.sequence.duration):.3f} mm")

    def choose_sequence(self) -> None:
        start = self._settings.value("last_sequence_dir", str(Path.home()))
        path, _ = QFileDialog.getOpenFileName(self, "Load calibration sequence", start, "CSV (*.csv *.txt)")
        if not path:
            return
        try:
            sequence = calibration.load_sequence(path)
        except Exception as e:
            self._error("Cannot read the sequence", str(e))
            return
        self._settings.setValue("last_sequence_dir", str(Path(path).parent))
        self._settings.setValue("last_sequence", path)
        self.set_sequence(sequence)

    def set_sequence(self, sequence: calibration.Sequence) -> None:
        self.sequence = sequence
        self.sequence_label.setText(f"{sequence.name}: {len(sequence.steps)} steps, {sequence.duration:.0f} s")
        self._sequence_changed()

    def choose_params(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Load parameters", self._params_dir(), "Parameters (*.json)")
        if path:
            try:
                profile = self.recording.profile if self.recording is not None else None
                self.params_panel.set_params(Parameters.load(path, profile))
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
