"""Main window: load a recording, analyse its video, tune parameters live, export."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import numpy as np
from PySide6.QtCore import QSettings, Qt, QTimer
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (QCheckBox, QDockWidget, QDoubleSpinBox, QFileDialog, QFormLayout, QGroupBox,
                               QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMainWindow, QMenu, QMessageBox,
                               QProgressBar, QPushButton, QScrollArea, QSplitter, QVBoxLayout, QWidget)

from cwtool import __version__, calibration, devices, palette, pipeline, sensors
from cwtool.fit import fit_calibration
from cwtool.gui.param_panel import ParameterPanel
from cwtool.gui.photometry_dialog import PhotometryDialog
from cwtool.gui.trim_panel import TrimPanel
from cwtool.gui.plots import ResultPlots, rms_in
from cwtool.gui.video_preview import VideoPreview
from cwtool.gui.workers import Task
from cwtool.params import DisplayPhotometry, Parameters
from cwtool.photometry import fit_light_response, fit_lux_response
from cwtool.trim import TRIM_FILE, Trim
from cwtool.video import VideoResult, analyse_video

RECOMPUTE_DELAY_MS = 150
# Signals shown when sensor data is imported (the ECG channel of a Shimmer, the EmotiBit's EDA and PPG), the first
# channel of a sensor with none of these; at most MAX_SHOWN at once, as each is a plot.
PREFERRED_SIGNALS = ("exg_ads1292r_1_ch1_24bit", "EDA", "PPG_IR")
MAX_SHOWN = 6


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
        # The folder with the lux logs, remembered between sessions: one folder for all recordings, so the
        # logs need not be copied into each.
        saved = str(self._settings.value("lux_folder", ""))
        self._lux_folder: Path | None = Path(saved) if saved and Path(saved).is_dir() else None
        self._display_path: Path | None = None
        self._base_sequence: calibration.Sequence | None = None

        self._recompute_timer = QTimer(self, singleShot=True, interval=RECOMPUTE_DELAY_MS)
        self._recompute_timer.timeout.connect(self.recompute)
        self.sensors: list[sensors.Sensor] = []     # the logger's sensor files, cut to this recording
        self._sensor_task: Task | None = None       # reads them, alongside the video analysis
        self._trim_save_timer = QTimer(self, singleShot=True, interval=400)
        self._trim_save_timer.timeout.connect(self._save_trim)

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
        self.lux_action = action("Choose lux folder…", self.choose_lux_folder)
        self.lux_action.setToolTip("The folder with the lux sensor logs (its subfolders are searched too), "
                                   "remembered for the next recordings and sessions")
        self.clear_lux_action = action("Use the recording's own lux logs", self.clear_lux_folder)
        self.load_params_action = action("Load parameters…", self.choose_params)
        self.save_params_action = action("Save parameters", self.save_params, QKeySequence.Save)
        self.save_params_as_action = action("Save parameters as…", self.save_params_as, QKeySequence.SaveAs)
        self.load_display_action = action("Load display photometry…", self.choose_display)
        self.save_display_action = action("Save display photometry…", self.save_display)
        self.sensors_action = action("Import sensor data…", self.choose_sensors)
        self.sensors_action.setToolTip("Shimmer and EmotiBit files from the sensor logger: shown under ΔPD and "
                                       "exported with the results, trimmed the same way")
        self.export_action = action("Export results…", self.export)
        quit_action = action("Quit", self.close, QKeySequence.Quit)

        file_menu = self.menuBar().addMenu("&File")
        for a in (self.open_action, self.lux_action, self.clear_lux_action, self.sensors_action, None,
                  self.load_params_action, self.save_params_action,
                  self.save_params_as_action, None, self.load_display_action, self.save_display_action, None,
                  self.export_action, None, quit_action):
            file_menu.addSeparator() if a is None else file_menu.addAction(a)

        self.fit_action = action("Reset view", lambda: self.plots.fit_to_data(), QKeySequence("Ctrl+0"))
        self.fit_action.setToolTip("Show all the data again (Ctrl+0, or double-click the plots)")
        self.view_menu = self.menuBar().addMenu("&View")
        self.view_menu.addAction(self.fit_action)
        self.view_menu.addSeparator()

        toolbar = self.addToolBar("Main")
        toolbar.setMovable(False)
        toolbar.setToolButtonStyle(Qt.ToolButtonTextOnly)
        # Framed, padded buttons: plain text actions are easy to miss.
        toolbar.setStyleSheet(
            "QToolBar { spacing: 8px; padding: 6px; }"
            "QToolButton { font-size: 14px; padding: 7px 16px; border: 1px solid palette(mid);"
            " border-radius: 6px; background: palette(button); }"
            f"QToolButton:hover {{ background: palette(light); border-color: {palette.ACCENT}; }}"
            "QToolButton:pressed { background: palette(midlight); }"
            "QToolButton:disabled { color: palette(mid); }")
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

        sensor_box = QGroupBox("Sensor data (optional)")
        sensor_layout = QVBoxLayout(sensor_box)
        self.sensors_label = QLabel("Shimmer and EmotiBit files from the sensor logger can be shown under ΔPD and "
                                    "exported with it, as one package.")
        self.sensors_label.setWordWrap(True)
        self.sensors_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        sensor_buttons = QHBoxLayout()
        self.import_sensors_button = QPushButton("Import…")
        self.import_sensors_button.setToolTip("Choose a sensor logger session folder (it is looked for in the "
                                              "recording's own folder when the recording is opened)")
        self.import_sensors_button.clicked.connect(self.choose_sensors)
        self.remove_sensors_button = QPushButton("Remove")
        self.remove_sensors_button.clicked.connect(self.remove_sensors)
        sensor_buttons.addWidget(self.import_sensors_button)
        sensor_buttons.addWidget(self.remove_sensors_button)
        self.signal_list = QListWidget()
        self.signal_list.setMaximumHeight(150)
        self.signal_list.setToolTip(f"The signals to show under ΔPD (at most {MAX_SHOWN}). All of them are exported")
        self.signal_list.itemChanged.connect(self._show_sensors)
        sensor_layout.addWidget(self.sensors_label)
        sensor_layout.addLayout(sensor_buttons)
        sensor_layout.addWidget(self.signal_list)
        side_layout.addWidget(sensor_box)
        self.trim_panel = TrimPanel()
        self.trim_panel.sequence_span = self._sequence_span
        self.trim_panel.changed.connect(self._trim_changed)
        side_layout.addWidget(self.trim_panel)

        self.params_panel = ParameterPanel()
        self.params_panel.params_changed.connect(self._params_edited)
        self.params_panel.video_settings_changed.connect(self._video_settings_edited)

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
        self.camera_button = QPushButton("Calibrate camera from lux")
        self.camera_button.setToolTip("For recordings made with a fixed camera exposure and a lux log: find the "
                                      "luminance that saturates the camera, for recordings of the same exposure "
                                      "without a lux log")
        self.camera_button.clicked.connect(self.calibrate_camera)
        video_layout.addWidget(self.camera_button)
        video_layout.addWidget(self.params_panel.video_section)
        side_layout.addWidget(video_box)

        # Sequence controls (display devices) and, for every device, the dynamics settings.
        self.cal_box = cal_box = QGroupBox("Calibration sequence")
        cal_box_layout = QVBoxLayout(cal_box)
        self.sequence_controls = QWidget()
        cal_layout = QFormLayout(self.sequence_controls)
        cal_layout.setContentsMargins(0, 0, 0, 0)
        cal_box_layout.addWidget(self.sequence_controls)
        self.cal_note = QLabel()
        self.cal_note.setWordWrap(True)
        self.cal_note.setStyleSheet("font-style: italic;")
        self.cal_note.setVisible(False)
        cal_box_layout.addWidget(self.cal_note)
        cal_box_layout.addWidget(self.params_panel.dynamics_section)
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
        load_sequence.clicked.connect(self.choose_sequence)
        default_sequence = QPushButton("Built-in")
        builtin = QMenu(default_sequence)
        builtin.addAction("Full calibration (the presenter's default, preset order)",
                          lambda: self.set_sequence(calibration.DEFAULT))
        builtin.addAction("20-step staircase (before October 2026)",
                          lambda: self.set_sequence(calibration.STAIRCASE_20))
        default_sequence.setMenu(builtin)
        default_sequence.setToolTip("Built-in sequences. A participant's run is usually scrambled with their ID: "
                                    "load the run file the presenter saved, which records the order played")
        sequence_buttons.addWidget(load_sequence)
        sequence_buttons.addWidget(default_sequence)
        load_sequence.setToolTip("The sequence CSV, or a run file saved by the calibration presenter: its "
                                 "onset times place the start in the recording")
        self.find_sequence_button = QPushButton("Find in recording")
        self.find_sequence_button.setToolTip("Locate the sequence in the analysed video and adapt its step "
                                             "length if the recording used different timing")
        self.find_sequence_button.clicked.connect(self.find_sequence)
        cal_layout.addRow(self.sequence_label)
        cal_layout.addRow(sequence_buttons)
        cal_layout.addRow(self.find_sequence_button)
        cal_layout.addRow(self.sequence_check)
        cal_layout.addRow("Start", self.sequence_start)
        cal_layout.addRow("ΔPD RMS in sequence", self.sequence_rms)
        self.fit_gamma_check = QCheckBox("Also fit gamma")
        self.fit_gamma_check.setToolTip("Fit the display gamma from the spacing of the grey steps (usually "
                                        "weakly determined; keep the datasheet value unless it clearly fails)")
        self.fit_black_check = QCheckBox("Also fit the black level (Lmin)")
        self.fit_black_check.setToolTip("Fit the display's black level with the white held at its nominal value. "
                                        "Needs steps long enough to dark-adapt; otherwise the black looks "
                                        "brighter than it is. Compare the contrast with the datasheet's")
        self.light_button = QPushButton("1. Fit light sensitivity")
        self.light_button.setToolTip("Fits the participant's light sensitivity and channel weights from the "
                                     "steady-state pupil on each step, given the display photometry")
        self.light_button.clicked.connect(self.fit_light)
        cal_layout.addRow(self.fit_gamma_check)
        cal_layout.addRow(self.fit_black_check)
        cal_layout.addRow(self.light_button)
        self.fit_dynamics_check = QCheckBox("Include dynamics (time constants and transient)")
        self.fit_dynamics_check.setChecked(True)
        self.fit_dynamics_check.setToolTip("Also fit the dilation and constriction time constants and the "
                                           "transient constriction after brightening (pupillary escape), and "
                                           "turn the dynamics on")
        self.fit_button = QPushButton("2. Fit latency and offset")
        self.fit_button.setToolTip("Fits the participant's latency, dilation/constriction time constants and pupil "
                                   "offset on the sequence. The pupil scale is not fitted (set it by hand). Fit the "
                                   "light sensitivity first.")
        self.fit_button.clicked.connect(self.fit_sequence)
        cal_layout.addRow(self.fit_dynamics_check)
        cal_layout.addRow(self.fit_button)
        self.fit_weight_check = QCheckBox("Also fit the fixation weight")
        self.fit_weight_check.setToolTip("Also fit the gaze circle's share of the weighted colour (open issue 47). It "
                                         "needs a scene where the gaze area and the background differ, such as a "
                                         "screen in a room; on a uniform field it cannot be determined. Check the "
                                         "result on other recordings before relying on it")
        cal_layout.addRow(self.fit_weight_check)
        self.lux_fit_button = QPushButton("Fit sensitivity and offset")
        self.lux_fit_button.setToolTip("Glasses with a lux sensor: fits the light sensitivity and the pupil offset "
                                       "by least squares on ΔPD over the sequence, with the luminance the analysis "
                                       "builds from the sensor (and the video)")
        self.lux_fit_button.clicked.connect(self.fit_lux)
        cal_layout.addRow(self.lux_fit_button)
        self._cal_layout = cal_layout
        self._sequence_buttons = sequence_buttons
        side_layout.addWidget(cal_box)
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
        self.summary_label.setWordWrap(True)     # long warnings must not set the window's minimum width
        self.plots = ResultPlots()
        self.plots.sequence_start_changed.connect(self._sequence_dragged)
        self.plots.trim_dragged.connect(self._trim_dragged)
        self.trim_panel.cursor_time = self.plots.cursor_time
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
        self.plots.cursor_changed.connect(self.preview.request_time)
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

    def _show_sequence_controls(self, mode: str) -> None:
        """The calibration box for a display device (both fits), a glasses recording with a lux log (the
        sensitivity and offset fit) or neither (only the dynamics)."""
        layout = self._cal_layout
        layout.setRowVisible(self._sequence_buttons, True)
        for widget in (self.find_sequence_button, self.fit_gamma_check, self.fit_black_check, self.light_button, self.fit_dynamics_check,
                       self.fit_button):
            layout.setRowVisible(widget, mode == "display")
        layout.setRowVisible(self.lux_fit_button, mode == "lux")
        layout.setRowVisible(self.fit_weight_check, mode == "lux")
        self.sequence_controls.setVisible(mode != "none")
        self.cal_box.setTitle("Calibration sequence" if mode != "none" else "Pupil dynamics")
        self.cal_note.setText({
            "lux": "Glasses have no display photometry, so the light comes from the lux sensor. Load the "
                   "presenter's run file: its onset times place the start. The fit sets the light sensitivity "
                   "and the pupil offset; set the dynamics by hand.",
            "none": "The calibration sequence and its fits need the display photometry (Varjo) or a lux sensor "
                    "log (glasses). Set the dynamics by hand here.",
        }.get(mode, ""))
        self.cal_note.setVisible(mode != "display")

    def _update_state(self) -> None:
        busy = self._task is not None and self._task.isRunning()
        has_rec = self.recording is not None
        self.analyse_button.setEnabled(has_rec and not busy and self.recording.scene_video is not None)
        self.analyse_button.setText("Reanalyse video" if self.video is not None else "Analyse video")
        self.analyse_button.setToolTip("Analyse the scene video again, ignoring the saved analysis"
                                       if self.video is not None else "Analyse the scene video")
        self.cancel_button.setVisible(busy)   # only while an analysis or fit runs
        self.open_action.setEnabled(not busy)
        self.clear_lux_action.setEnabled(self._lux_folder is not None and not busy)
        self.export_action.setEnabled(self.result is not None)
        self.fit_button.setEnabled(self.result is not None and self.sequence_check.isChecked() and not busy)
        self.light_button.setEnabled(self.fit_button.isEnabled())
        self.lux_fit_button.setEnabled(self.fit_button.isEnabled())
        self.find_sequence_button.setEnabled(self.video is not None and not busy)
        has_lux = has_rec and self.recording.lux_values is not None
        self.camera_button.setVisible(has_rec and self.recording.luminance_source == "lux_sensor")
        self.camera_button.setEnabled(has_lux and self.video is not None and not busy)
        if self.result is None:
            self.summary_label.setText("Open a recording to start." if not has_rec else "")
        else:
            r = self.result
            gaps = f" &nbsp;&nbsp; gaps {r.gap_fraction:.0%}" if r.gap_fraction >= 0.005 else ""
            leak = (f" &nbsp;&nbsp; <b>light left</b> R² {r.leak_r2:.2f} ({r.leak_slope:+.2f} mm/decade)"
                    if np.isfinite(r.leak_r2) else "")
            warn = "".join(f"<br><span style='color:{palette.WARNING}'>⚠ {w}</span>" for w in r.warnings)
            ends = (f"expected PD at black {r.expected_black:.2f} mm, white {r.expected_white:.2f} mm &nbsp;&nbsp; "
                    if np.isfinite(r.expected_black) else self._route_text(r) + " &nbsp;&nbsp; ")
            self.summary_label.setText(
                f"<b>ΔPD RMS</b> {r.cw_rms:.3f} mm &nbsp; <b>SD</b> {r.cw_sd:.3f} mm{leak} &nbsp;&nbsp; {ends}"
                f"pupil ×{r.pupil_scale:.3g}, offset {r.offset:+.2f} mm &nbsp;&nbsp; "
                f"{r.measured_rate:.0f} Hz → {r.rate:.0f} Hz{gaps}{warn}")
        name = self._params_path.name if self._params_path else "unsaved parameters"
        if has_rec and self.recording.luminance_source == "display":
            name += ", display " + (self._display_path.name if self._display_path else "defaults")
        rec = f": {self.recording.name}" if has_rec else ""
        self.setWindowTitle(f"Cognitive Workload Tool {__version__}{rec} ({name})")

    @staticmethod
    def _route_text(r) -> str:
        """Where the luminance comes from, with the typical values of the lux sensor route (medians over the
        recording; the range is the 10th to 90th percentile of the video ratio)."""
        route = pipeline.luminance_route(r)
        if route is None:
            return f"luminance from {r.luminance_mode}"
        text = f"luminance: lux sensor {route['sensor']:.1f} cd/m² (median)"
        if route["ratio"] is not None:
            med, lo, hi = route["ratio"]
            text += f" × video ratio {med:.2f} (10–90 %: {lo:.2f}–{hi:.2f})"
        else:
            text += ", video not used"
        return text

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

    def choose_lux_folder(self) -> None:
        start = str(self._lux_folder or self._settings.value("last_recording_dir", str(Path.home())))
        folder = QFileDialog.getExistingDirectory(self, "Folder with the lux sensor logs", start)
        if folder:
            self.set_lux_folder(Path(folder))

    def set_lux_folder(self, folder: Path | None) -> None:
        """Use ``folder`` for the lux logs of this and the next recordings (None: the recording's own),
        remember it, and reload the open recording with it."""
        self._lux_folder = folder
        self._settings.setValue("lux_folder", str(folder) if folder else "")
        if self.recording is not None:
            self.open_recording(self.recording.folder)
        self._update_state()

    def clear_lux_folder(self) -> None:
        self.set_lux_folder(None)

    def open_recording(self, folder: Path) -> None:
        lux_folder = self._lux_folder

        def load(progress, cancelled):
            return devices.load(folder, lux_folder=lux_folder)

        self._start_task(load, self._recording_loaded, f"Loading {folder.name}…")

    def _recording_loaded(self, rec) -> None:
        self.recording, self.video, self.result = rec, None, None
        duration = rec.time[-1] - rec.time[0] if len(rec.time) else 0
        video = rec.scene_video.name if rec.scene_video else "none"
        prof = rec.profile
        scale = f"×{prof.pupil_scale:g}" if prof.pupil_scale else "scale fitted"
        self.recording_label.setText(
            f"<b>{rec.name}</b><br>{rec.device}, {len(rec.time)} samples, {duration:.1f} s, "
            f"{rec.measured_rate:.0f} Hz<br>camera {prof.field_of_view[0]:.0f}° × {prof.field_of_view[1]:.0f}°, "
            f"adapting field {prof.field_area:,.0f} deg², pupil {prof.pupil_unit} {scale}"
            f"<br>video: {video}<br>events: {len(rec.events)}"
            + (f"<br>lux sensor: {len(rec.lux_values)} readings" if rec.lux_values is not None
               else ("<br>lux sensor: none found" if rec.luminance_source == "lux_sensor" else ""))
            + (f"<br>lux folder: {self._lux_folder}" if self._lux_folder and rec.luminance_source == "lux_sensor" else ""))
        self.plots.clear_result()
        self.plots.show_events(rec.events)
        self._recording_sensors_and_trim(rec)
        self.params_panel.set_video_settings(self.params_panel.video_settings().for_recording(rec))
        # Hide what does not apply to this device: the calibration sequence is shown on a display.
        self.params_panel.set_recording(rec)
        on_display = rec.luminance_source == "display"
        remembered = self._settings.value(f"display_photometry/{rec.device}", "")
        if on_display and remembered and Path(remembered).exists() and Path(remembered) != self._display_path:
            self.load_display(Path(remembered), quiet=True)   # the last photometry used with this device
        if not on_display:
            self.sequence_check.setChecked(False)
        # Without a display there is no calibration sequence, but the dynamics still apply.
        with_lux = rec.luminance_source == "lux_sensor" and rec.lux_values is not None
        self._show_sequence_controls("display" if on_display else ("lux" if with_lux else "none"))
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
            cached = VideoResult.load_cached(rec.folder, settings, rec.scene_video, rec.scene_frame_times,
                                             rec.gaze)
            if cached is not None:
                self._video_ready(cached, "cached analysis")
                return

        def work(progress, cancelled):
            res = analyse_video(rec.scene_video, rec.time, rec.gaze, settings, progress, cancelled,
                                frame_times=rec.scene_frame_times)
            if cancelled():
                return None
            res.save(rec.folder, settings, rec.scene_video, rec.scene_frame_times, rec.gaze)
            return res

        self._start_task(work, lambda res: res and self._video_ready(res, "analysed"),
                         f"Analysing {rec.scene_video.name}…", show_progress=True)

    def _video_ready(self, video: VideoResult, how: str) -> None:
        self.video = video
        self.video_label.setText(f"{self.recording.scene_video.name}: {len(video.time)} samples ({how})")
        self.recompute()
        self._update_state()

    def _video_settings_edited(self) -> None:
        if self.recording is not None:
            self.preview.set_settings(self.params_panel.video_settings().for_recording(self.recording))
        if self.video is not None:
            self.video_label.setText("Video settings changed: press Reanalyse video to apply.")

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
        self.trim_panel.refresh_buttons()
        self._update_sequence_rms()
        self._update_state()

    def fit_light(self) -> None:
        rec, video, params = self.recording, self.video, self.params_panel.params()
        start, sequence, gamma = self.sequence_start.value(), self.sequence, self.fit_gamma_check.isChecked()
        black = self.fit_black_check.isChecked()

        def work(progress, cancelled):
            return fit_light_response(rec, video, params, start, sequence, fit_gamma=gamma, fit_black=black)

        self._start_task(work, self._light_done, "Fitting the light response on the calibration sequence…")

    def _light_done(self, fit) -> None:
        if PhotometryDialog(fit, self).exec():
            self.params_panel.set_params(fit.params)

    def fit_lux(self) -> None:
        rec, video, params = self.recording, self.video, self.params_panel.params()
        start, sequence = self.sequence_start.value(), self.sequence
        weight = self.fit_weight_check.isChecked()

        def work(progress, cancelled):
            return fit_lux_response(rec, video, params, start, sequence, fit_fixation=weight)

        self._start_task(work, self._lux_done, "Fitting the light sensitivity and offset on the sequence…")

    def _lux_done(self, fit) -> None:
        lo, hi = fit.sensitivity_range
        notes = "".join(f"<br><span style='color:{palette.WARNING}'>⚠ {n}</span>" for n in fit.notes)
        box = QMessageBox(QMessageBox.Question, "Light sensitivity and offset",
                          f"<b>ΔPD RMS in sequence: {fit.rms_before:.3f} → {fit.rms_after:.3f} mm</b> "
                          f"(before: the current parameters with their best offset)<br><br>"
                          f"light sensitivity ×{fit.sensitivity:.3g} (95 % {lo:.3g}–{hi:.3g})<br>"
                          + (f"fixation weight {fit.fixation_weight:.2f}<br>" if fit.weight_fitted else "") +
                          f"pupil offset {fit.offset:+.3f} mm &nbsp; correlation with the expected pupil "
                          f"{fit.correlation:.2f}<br>"
                          f"{fit.steps} steps with pupil data, {fit.seconds:.0f} s{notes}<br><br>"
                          f"Apply? Alignment will be set to 'fixed' so the offset carries over to this "
                          f"participant's other recordings.", QMessageBox.Apply | QMessageBox.Cancel, self)
        if box.exec() == QMessageBox.Apply:
            self.params_panel.set_params(fit.params)

    def fit_sequence(self) -> None:
        rec, video, params = self.recording, self.video, self.params_panel.params()
        start, dynamics = self.sequence_start.value(), self.fit_dynamics_check.isChecked()
        sequence = self.sequence
        end = start + sequence.duration

        def work(progress, cancelled):
            return fit_calibration(rec, video, params, start, end, fit_dynamics=dynamics, cancelled=cancelled,
                                   sequence=sequence, fit_transient=dynamics)

        self._start_task(work, self._fit_done, "Fitting on the calibration sequence…")

    def _fit_done(self, fit) -> None:
        dyn = (f"<br>dilation τ {fit.attack:.2f} s, constriction τ {fit.release:.2f} s"
               if fit.params.dynamics else "")
        if fit.transient > 0:
            dyn += f"<br>transient {fit.transient:.2f} mm, escape τ {fit.escape:.2f} s"
        notes = "".join(f"<br><span style='color:{palette.WARNING}'>⚠ {n}</span>" for n in fit.notes)
        box = QMessageBox(QMessageBox.Question, "Calibration fit",
                          f"<b>Fit error: {fit.fit_rms_before:.3f} → {fit.fit_rms_after:.3f} mm</b> (what the fit "
                          f"minimises: measured − expected in the sequence, without an offset)<br>"
                          f"ΔPD RMS in sequence with alignment '{fit.params.alignment}': {fit.rms_before:.3f} → "
                          f"{fit.rms_after:.3f} mm<br><br>"
                          f"latency {fit.delay:.2f} s{dyn}<br>"
                          f"(the pupil scale stays ×{fit.pupil_correction:.3g}, as set by hand; the pupil "
                          f"offset is not fitted)"
                          f"{notes}<br><br>Apply? These values carry over to this participant's other "
                          f"recordings.",
                          QMessageBox.Apply | QMessageBox.Cancel, self)
        if box.exec() == QMessageBox.Apply:
            self.params_panel.set_params(fit.params)

    def calibrate_camera(self) -> None:
        params = self.params_panel.params()
        try:
            cal = pipeline.calibrate_camera(self.recording, self.video, params)
        except ValueError as e:
            self._error("Camera calibration", str(e))
            return
        exposure = (f" at {params.camera_exposure_ms:g} ms" if params.camera_exposure_ms > 0
                    else " (enter the recording exposure first to reuse it at other exposures)")
        notes = "".join(f"<br><span style='color:{palette.WARNING}'>⚠ {n}</span>" for n in cal.notes)
        box = QMessageBox(QMessageBox.Question, "Camera calibration",
                          f"<b>Full scale: {cal.white:.0f} cd/m²</b>{exposure}<br>"
                          f"from {cal.samples} video samples, spread ×{cal.spread:.2f} (90th / 10th percentile)"
                          f"{notes}<br><br>Apply? Recordings without a lux log will use it when camera exposure "
                          f"is 'fixed'. Save the parameters to keep it.",
                          QMessageBox.Apply | QMessageBox.Cancel, self)
        if box.exec() == QMessageBox.Apply:
            self.params_panel.set_params(replace(params, camera_white=cal.white,
                                                 camera_reference_ms=params.camera_exposure_ms))

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
        self._place_from_run(path, sequence)

    def _place_from_run(self, path: str, sequence: calibration.Sequence) -> None:
        """A run file from the calibration presenter carries the onset of each step on the computer's clock:
        that puts the sequence in the recording without searching for it."""
        unix = calibration.run_start_unix(path)
        rec = self.recording
        if unix is None or rec is None or not np.isfinite(rec.epoch_start) or not len(rec.time):
            return
        start = unix - rec.epoch_start
        if not rec.time[0] - sequence.duration <= start <= rec.time[-1]:
            self.statusBar().showMessage(f"The run starts {start:.0f} s from this recording's start, outside it: "
                                         "it was played for another recording.", 8000)
            return
        self.sequence_start.setValue(start)
        self.sequence_check.setChecked(True)
        self.statusBar().showMessage(f"Sequence placed at {start:.2f} s from the run file's onset times", 6000)

    def find_sequence(self) -> None:
        if self.video is None:
            return
        base = self._base_sequence or self.sequence
        loc = calibration.locate(self.video.time, self.video.background_rgb, base)
        if loc is None or loc.error > 0.35:
            self._error("Sequence not found", "Could not match the calibration sequence to this recording's "
                                              "scene colours. Place it by dragging the start line.")
            return
        self.set_sequence(loc.sequence, keep_base=True)
        self.sequence_start.setValue(loc.start)
        self.sequence_check.setChecked(True)
        gaps = f", {1 - loc.coverage:.0%} of it in tracking gaps" if loc.coverage < 0.95 else ""
        self.statusBar().showMessage(f"Sequence found at {loc.start:.2f} s "
                                     f"(colour match error {loc.error:.0%}{gaps})", 5000)

    def set_sequence(self, sequence: calibration.Sequence, keep_base: bool = False) -> None:
        if not keep_base:
            self._base_sequence = sequence
        self.sequence = sequence
        self.sequence_label.setText(f"{sequence.name}: {len(sequence.steps)} steps, {sequence.duration:.0f} s")
        self._sequence_changed()

    def choose_params(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Load parameters", self._params_dir(), "Parameters (*.json)")
        if path:
            try:
                profile = self.recording.profile if self.recording is not None else None
                # Participant files hold no display photometry: the current one is kept.
                self.params_panel.set_params(Parameters.load(path, profile, base=self.params_panel.params()))
            except Exception as e:
                self._error("Cannot load parameters", str(e))
                return
            self._params_path = Path(path)
            self._update_state()

    def save_params(self) -> None:
        if self._params_path is None:
            self.save_params_as()
        else:
            self.params_panel.params().save(self._params_path, participant_only=True)
            self.statusBar().showMessage(f"Saved {self._params_path} (display photometry is saved separately)", 4000)

    def save_params_as(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Save parameters", self._params_dir(), "Parameters (*.json)")
        if path:
            if not path.endswith(".json"):
                path += ".json"
            self._params_path = Path(path)
            self._settings.setValue("last_params_dir", str(self._params_path.parent))
            self.save_params()
            self._update_state()

    def _device(self) -> str:
        return self.recording.device if self.recording is not None else ""

    def choose_display(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Load display photometry", self._params_dir(),
                                              "Display photometry (*.json)")
        if path:
            self.load_display(Path(path))

    def load_display(self, path: Path, quiet: bool = False) -> None:
        try:
            display = DisplayPhotometry.load(path)
        except Exception as e:
            if not quiet:
                self._error("Cannot load display photometry", str(e))
            return
        self.params_panel.set_params(display.apply(self.params_panel.params()))
        self._display_path = path
        if display.device:
            self._settings.setValue(f"display_photometry/{display.device}", str(path))
        self.statusBar().showMessage(f"Display photometry: {path.name}"
                                     + (f" ({display.source})" if display.source else ""), 5000)
        self._update_state()

    def save_display(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Save display photometry", self._params_dir(),
                                              "Display photometry (*.json)")
        if not path:
            return
        if not path.endswith(".json"):
            path += ".json"
        DisplayPhotometry.from_params(self.params_panel.params(), self._device()).save(path)
        self._display_path = Path(path)
        if self._device():
            self._settings.setValue(f"display_photometry/{self._device()}", path)
        self.statusBar().showMessage(f"Saved {path}", 3000)
        self._update_state()

    # Sensor data and the export range

    def choose_sensors(self) -> None:
        if self.recording is None:
            self._error("Import sensor data", "Open a recording first: the sensor data is placed on its time axis.")
            return
        start = self._settings.value("last_sensor_dir", str(self.recording.folder))
        folder = QFileDialog.getExistingDirectory(self, "Sensor logger session folder", start)
        if folder:
            self._settings.setValue("last_sensor_dir", str(Path(folder).parent))
            self.import_sensors(Path(folder))

    def _recording_sensors_and_trim(self, rec) -> None:
        """A recording was opened: forget the sensor data of the previous one, look for the logger's files in the
        recording's own folder, and bring back the export range saved with it."""
        self.sensors = []
        self.signal_list.clear()
        self.plots.set_sensors([])
        self._update_sensors_label()
        if len(rec.time):
            lo, hi = float(rec.time[0]), float(rec.time[-1])
        else:
            lo = hi = 0.0
        self.trim_panel.set_bounds(lo, hi)
        trim = Trim.load(rec.folder / TRIM_FILE)
        self.trim_panel.set_trim(trim, quiet=True)
        self.plots.show_trim(trim, lo, hi)
        if sensors.find_sensor_files(rec.folder):
            self.import_sensors(rec.folder, quiet=True)

    def import_sensors(self, folder: Path, quiet: bool = False) -> None:
        rec = self.recording
        if rec is None or not len(rec.time):
            return
        if not np.isfinite(rec.epoch_start):
            if not quiet:
                self._error("Import sensor data", "This recording does not say when it started, so the sensor "
                                                  "data cannot be placed on its time axis.")
            return
        if self._sensor_task is not None and self._sensor_task.isRunning():
            return
        start, span = rec.epoch_start + float(rec.time[0]), float(rec.time[-1] - rec.time[0])

        def load(progress, cancelled):
            return sensors.load_sensors(folder, start, span)

        self.statusBar().showMessage(f"Reading the sensor data in {folder.name}…")
        self._sensor_task = Task(load, self)
        self._sensor_task.succeeded.connect(lambda found: self._sensors_loaded(found, folder, quiet))
        self._sensor_task.failed.connect(lambda msg: self._error("Import sensor data", msg))
        self._sensor_task.finished.connect(lambda: self.statusBar().clearMessage())
        self._sensor_task.start()

    def _sensors_loaded(self, found, folder: Path, quiet: bool) -> None:
        if not found:
            if not quiet:
                self._error("Import sensor data", f"No sensor data in {folder} overlaps this recording. The files "
                                                  "must come from the sensor logger (their first column is the "
                                                  "Unix time) and cover the same time as the recording.")
            return
        self.sensors = found
        self.signal_list.blockSignals(True)
        self.signal_list.clear()
        shown = 0
        for i, sensor in enumerate(found):
            names = [n for n in sensor.signals() if n != "device time (s)"]
            wanted = [n for n in names if n in PREFERRED_SIGNALS] or names[:1]
            for name in names:
                item = QListWidgetItem(f"{sensor.name}: {name}")
                item.setData(Qt.UserRole, (i, name))
                on = name in wanted and shown < MAX_SHOWN
                shown += on
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(Qt.Checked if on else Qt.Unchecked)
                self.signal_list.addItem(item)
        self.signal_list.blockSignals(False)
        self._update_sensors_label(folder)
        self._show_sensors()

    def remove_sensors(self) -> None:
        self.sensors = []
        self.signal_list.clear()
        self.plots.set_sensors([])
        self._update_sensors_label()

    def _update_sensors_label(self, folder: Path | None = None) -> None:
        if not self.sensors:
            self.sensors_label.setText("Shimmer and EmotiBit files from the sensor logger can be shown under ΔPD "
                                       "and exported with it, as one package.")
        else:
            parts = ", ".join(f"{s.name} ({len(s):,} rows)" for s in self.sensors)
            self.sensors_label.setText(f"{parts}" + (f"<br>from {folder}" if folder else ""))
        self.remove_sensors_button.setEnabled(bool(self.sensors))

    def _show_sensors(self, *_) -> None:
        rec = self.recording
        specs = []
        for row in range(self.signal_list.count()):
            item = self.signal_list.item(row)
            if item.checkState() != Qt.Checked:
                continue
            index, name = item.data(Qt.UserRole)
            t, v = self.sensors[index].series(name)
            specs.append((f"{self.sensors[index].name}: {name}", t - rec.epoch_start, v))
        if len(specs) > MAX_SHOWN:
            self.statusBar().showMessage(f"Showing the first {MAX_SHOWN} of {len(specs)} selected signals", 4000)
            specs = specs[:MAX_SHOWN]
        self.plots.set_sensors(specs)

    def _sequence_span(self):
        """The calibration sequence on the plots, for the export range's "leave out calibration" button."""
        if self.sequence_check.isChecked():
            start = self.sequence_start.value()
            return start, start + self.sequence.duration
        return None

    def _trim_changed(self, trim: Trim) -> None:
        """The user edited the export range in the sidebar."""
        rec = self.recording
        if rec is not None and len(rec.time):
            self.plots.show_trim(trim, float(rec.time[0]), float(rec.time[-1]))
        self._trim_save_timer.start()

    def _trim_dragged(self, trim: Trim) -> None:
        """The user dragged the export range on the plots."""
        self.trim_panel.set_trim(trim, quiet=True)
        self._trim_save_timer.start()

    def _save_trim(self) -> None:
        """Keep the export range with the recording, so it comes back when it is opened again."""
        if self.recording is None:
            return
        path = self.recording.folder / TRIM_FILE
        trim = self.trim_panel.trim()
        try:
            if trim.active:
                trim.save(path)
            elif path.exists():
                path.unlink()
        except OSError:
            self.statusBar().showMessage("Could not save the export range next to the recording", 4000)

    def _params_dir(self) -> str:
        return self._settings.value("last_params_dir", str(Path.home()))

    def export(self) -> None:
        if self.result is None:
            return
        default = str(self.recording.folder / "cwtool_export")
        folder = QFileDialog.getExistingDirectory(self, "Export to folder", default)
        if not folder:
            return
        trim = self.trim_panel.trim()
        try:
            paths = pipeline.export(self.result, self.recording, self.params_panel.params(), Path(folder),
                                    trim=trim, sensors=self.sensors)
        except OSError as e:
            self._error("Cannot export", str(e))
            return
        try:
            from cwtool.plot import plot_result
            p = Path(folder) / f"{self.recording.name}_plot.pdf"
            plot_result(self.result, self.recording, trim).savefig(p, bbox_inches="tight")
            paths.append(p)
        except ImportError:
            pass
        extra = ""
        if self.sensors:
            extra += f", {len(self.sensors)} sensor file{'s' if len(self.sensors) != 1 else ''}"
        if trim.active:
            extra += ", trimmed"
        self.statusBar().showMessage(f"Exported {len(paths)} files{extra} to {folder}", 6000)

    def closeEvent(self, event) -> None:
        if self._task is not None and self._task.isRunning():
            self._task.cancel()
            self._task.wait(5000)
        super().closeEvent(event)
