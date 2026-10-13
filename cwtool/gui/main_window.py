"""Main window: load a recording, analyse its video, tune parameters live, export."""

from __future__ import annotations

import traceback
from dataclasses import asdict, replace
from functools import partial
from pathlib import Path

import numpy as np
from PySide6.QtCore import QSettings, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QColor, QDesktopServices, QKeySequence, QPalette
from PySide6.QtWidgets import QWidgetAction
from PySide6.QtWidgets import (QCheckBox, QDoubleSpinBox, QFileDialog, QFormLayout, QFrame, QGroupBox,
                               QHBoxLayout, QHeaderView, QLabel, QListWidget, QListWidgetItem, QMainWindow, QMenu,
                               QMessageBox, QProgressBar, QPushButton, QScrollArea, QSplitter, QStackedWidget,
                               QTableWidget, QTableWidgetItem, QToolButton, QVBoxLayout, QWidget)

from cwtool import __version__, calibration, devices, hrv, palette, pipeline, sensors
from cwtool.fit import fit_calibration
from cwtool.gui import errors
from cwtool.gui.param_panel import ParameterPanel
from cwtool.gui.icons import icon, tinted
from cwtool.gui.photometry_dialog import PhotometryDialog
from cwtool.gui.side_panel import PreviewHolder, Rail, Step
from cwtool.gui.trim_panel import TrimPanel
from cwtool.gui.plots import ResultPlots, rms_in
from cwtool.gui.video_preview import VideoPreview
from cwtool.gui.workers import Task
from cwtool.params import DISPLAY_FIELDS, DeviceMismatch, DisplayPhotometry, Parameters
from cwtool.photometry import fit_light_response, fit_lux_response
from cwtool.trim import TRIM_FILE, Trim
from cwtool.video import VideoResult, analyse_video

RECOMPUTE_DELAY_MS = 150
# Signals shown when sensor data is imported (the ECG channel of a Shimmer, the EmotiBit's EDA and PPG), the first
# channel of a sensor with none of these; at most MAX_SHOWN at once, as each is a plot.
PREFERRED_SIGNALS = ("exg_ads1292r_1_ch1_24bit", "EDA", "PPG_IR")
MAX_SHOWN = 6
DROP_DOWN_STYLE = "QPushButton::menu-indicator { image: none; width: 0px; }"      # no separate arrow: "▾" is in the text
# the columns of the HRV table: header, the field of the result, the format (the full set is in the exported file)
HRV_COLUMNS = (("Window", "label", "{}"), ("s", "seconds", "{:.0f}"), ("HR", "mean_hr", "{:.0f}"),
               ("RMSSD", "rmssd", "{:.0f}"), ("SDNN", "sdnn", "{:.0f}"), ("LF/HF", "lf_hf", "{:.1f}"))


class MainWindow(QMainWindow):
    """The analysis window: the tabs on the left (Data, Params, Calibrate, Export) with the video preview under them,
    the plots on the right, and the status strip. It owns the open recording, its video analysis and its result, and
    recomputes the result when a parameter changes.
    """
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"Cognitive Workload Tool {__version__}")
        self.resize(1400, 900)
        self._settings = QSettings("cwtool", "cwtool")
        self.recording = None
        self.video = None
        self.result = None
        self._task: Task | None = None
        self._no_session: str | None = None         # why the remembered logger folder gave nothing, if it did not
        self._params_note: str | None = None          # why the parameters were reset, shown in the Set-up box
        self._params_device: str | None = None       # the device the parameters in the panel were set for
        self._last_failure: str | None = None       # the analysis error already shown in a box
        self._params_path: Path | None = None
        # The sensor logger's recordings folder, remembered between sessions: one folder for all recordings, which holds
        # the lux log and the Shimmer and EmotiBit files of each session, so nothing is copied into the recordings.
        # (It was "lux_folder" before the lux log and the sensor data shared it.)
        saved = [str(self._settings.value(key, "") or "") for key in ("sensor_logs_folder", "lux_folder")]
        self._logs_folder: Path | None = next((Path(s) for s in saved if s and Path(s).is_dir()), None)
        self._logs_override: Path | None = None     # one session chosen for the open recording, not remembered
        self._display_path: Path | None = None
        self._base_sequence: calibration.Sequence | None = None

        self._recompute_timer = QTimer(self, singleShot=True, interval=RECOMPUTE_DELAY_MS)
        self._recompute_timer.timeout.connect(self.recompute)
        self.sensors: list[sensors.Sensor] = []     # the logger's sensor files, cut to this recording
        self.hrv_beats: dict[str, hrv.Beats] = {}   # the beats found in each ECG by Compute HRV (exported when present)
        self.hrv_series: hrv.TimeSeries | None = None   # the heart rate and moving RMSSD of the first ECG, for the plots
        self._sensor_task: Task | None = None       # reads them, alongside the video analysis
        self._trim_save_timer = QTimer(self, singleShot=True, interval=400)
        self._trim_save_timer.timeout.connect(self._save_trim)
        self._hrv_timer = QTimer(self, singleShot=True, interval=150)    # the HRV table follows the export range
        self._hrv_timer.timeout.connect(self._refresh_hrv)

        self._build_actions()
        self._build_ui()
        self._restore_sequence()
        self._restore_layout()
        self._update_state()

    # UI

    def _build_actions(self) -> None:
        def action(text, slot, shortcut=None):
            """A menu or toolbar action with its slot and optional shortcut."""
            a = QAction(text, self)
            a.triggered.connect(slot)
            if shortcut:
                a.setShortcut(shortcut)
            return a

        self.open_action = action("Open recording…", self.choose_recording, QKeySequence.Open)
        self.forget_logs_action = action("Forget the logger folder", self.forget_logger_folder)
        self.forget_logs_action.setToolTip("Look for the lux log and the sensor files in the recording's own folder again")
        self.load_params_action = action("Load parameters…", self.choose_params)
        self.save_params_action = action("Save parameters", self.save_params, QKeySequence.Save)
        self.save_params_as_action = action("Save parameters as…", self.save_params_as, QKeySequence.SaveAs)
        self.load_display_action = action("Load display photometry…", self.choose_display)
        self.save_display_action = action("Save display photometry…", self.save_display)
        self.sensors_action = action("Logger folder… (lux and sensor data)", self.choose_sensors)
        self.sensors_action.setToolTip("The sensor logger's recordings folder, or one of its sessions: the lux log and "
                                       "the Shimmer and EmotiBit files of the recording are found in it by their time. "
                                       "The folder is remembered for every recording")
        self.export_action = action("Export results…", self.export, QKeySequence("Ctrl+E"))
        quit_action = action("Quit", self.close, QKeySequence.Quit)

        file_menu = self.menuBar().addMenu("&File")
        self.recent_menu = QMenu("Open recent", self)
        self.recent_menu.aboutToShow.connect(self._fill_recent_menu)
        for a in (self.open_action, self.recent_menu.menuAction(), self.sensors_action, self.forget_logs_action, None,
                  self.load_params_action, self.save_params_action,
                  self.save_params_as_action, None, self.load_display_action, self.save_display_action, None,
                  self.export_action, None, quit_action):
            file_menu.addSeparator() if a is None else file_menu.addAction(a)

        self.help_menu = self.menuBar().addMenu("&Help")
        for a in (action("Gestures and shortcuts…", self.show_gestures),
                  action("Documentation (opens the web page)", lambda: QDesktopServices.openUrl(QUrl(errors.DOCS_URL))),
                  action("About", self.show_about)):
            self.help_menu.addAction(a)

        self.fit_action = action("Reset view", lambda: self.plots.fit_to_data(), QKeySequence("Ctrl+0"))
        self.fit_action.setToolTip("Show all the data again (Ctrl+0, or double-click the plots)")
        self.view_menu = self.menuBar().addMenu("&View")
        self.view_menu.addAction(self.fit_action)
        self.view_menu.addSeparator()

        toolbar = self.addToolBar("Main")
        toolbar.setMovable(False)
        toolbar.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        toolbar.setIconSize(QSize(20, 20))
        # Framed, padded buttons: plain text actions are easy to miss.
        toolbar.setStyleSheet(
            "QToolBar { spacing: 8px; padding: 6px; }"
            "QToolButton { font-size: 14px; padding: 7px 16px; border: 1px solid palette(mid);"
            " border-radius: 6px; background: palette(button); }"
            f"QToolButton:hover {{ background: palette(light); border-color: {palette.ACCENT}; }}"
            "QToolButton:pressed { background: palette(midlight); }"
            "QToolButton:disabled { color: palette(mid); }")
        for a, name in ((self.open_action, "folder-open"), (self.load_params_action, "file-import"),
                        (self.save_params_action, "device-floppy"), (self.export_action, "file-export")):
            a.setIcon(icon(name, 20))
            toolbar.addAction(a)

    def _build_ui(self) -> None:
        self.params_panel = ParameterPanel()
        self.params_panel.params_changed.connect(self._params_edited)
        self.params_panel.video_settings_changed.connect(self._video_settings_edited)

        # --- Data: what is loaded
        rec_box = QGroupBox("Recording")
        rec_layout = QVBoxLayout(rec_box)
        self.recording_label = QLabel("No recording loaded")
        self.recording_label.setWordWrap(True)
        self.recording_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        rec_layout.addWidget(self.recording_label)
        self.setup_box = QGroupBox("Set-up: what is still missing")
        setup_layout = QVBoxLayout(self.setup_box)
        self.setup_label = QLabel()
        self.setup_label.setWordWrap(True)
        self.setup_label.setTextFormat(Qt.RichText)
        self.setup_label.linkActivated.connect(self._setup_link)
        link_palette = self.setup_label.palette()
        link_palette.setColor(QPalette.Link, QColor(palette.WARNING))      # a missing item is red, as its mark
        self.setup_label.setPalette(link_palette)
        setup_layout.addWidget(self.setup_label)
        self.setup_box.hide()
        self.fits_done = {"light": False, "timing": False, "lux": False}     # fits applied in this session

        self.own_folder_button = QPushButton("Use the recording's own folder")
        self.own_folder_button.setToolTip(self.forget_logs_action.toolTip())
        self.own_folder_button.clicked.connect(self.forget_logger_folder)

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

        sensor_box = QGroupBox("Sensor data: lux log, Shimmer, EmotiBit")
        sensor_layout = QVBoxLayout(sensor_box)
        self.sensors_label = QLabel("The sensor logger's files (the lux log, Shimmer, EmotiBit) can be shown under ΔPD "
                                    "and exported with it, as one package.")
        self.sensors_label.setWordWrap(True)
        self.sensors_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        sensor_buttons = QHBoxLayout()
        self.import_sensors_button = QPushButton("Logger folder…")
        self.import_sensors_button.setToolTip("Choose the sensor logger's recordings folder (the session that overlaps "
                                              "this recording is found, and the folder is remembered for every "
                                              "recording) or one session folder. The logger's files in the recording's "
                                              "own folder are used when it is opened")
        self.import_sensors_button.clicked.connect(self.choose_sensors)
        self.remove_sensors_button = QPushButton("Remove")
        self.remove_sensors_button.clicked.connect(self.remove_sensors)
        self.hrv_button = QPushButton("Compute HRV")
        self.hrv_button.setToolTip("Find the heartbeats in the Shimmer's ECG (lead II) and compute the heart rate "
                                   "variability of the whole recording and of each event. The beats are drawn on the "
                                   "ECG plot, the measures are shown below, and both go into the export package")
        self.hrv_button.clicked.connect(self.compute_hrv)
        self.hrv_button.setShortcut(QKeySequence("Ctrl+H"))
        self.hrv_button.setEnabled(False)
        sensor_buttons.addWidget(self.import_sensors_button)
        sensor_buttons.addWidget(self.remove_sensors_button)
        sensor_buttons.addWidget(self.hrv_button)
        self.signal_list = QListWidget()
        self.signal_list.setMaximumHeight(150)
        self.signal_list.setToolTip(f"The signals to show under ΔPD (at most {MAX_SHOWN}). All of them are exported")
        self.signal_list.itemChanged.connect(self._show_sensors)
        self.hrv_status = QLabel()
        self.hrv_status.setWordWrap(True)
        self.hrv_status.hide()
        self.hrv_table = QTableWidget(0, len(HRV_COLUMNS))
        self.hrv_table.setHorizontalHeaderLabels([c[0] for c in HRV_COLUMNS])
        self.hrv_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.hrv_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.hrv_table.verticalHeader().hide()
        self.hrv_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.hrv_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.hrv_table.setMaximumHeight(170)
        self.hrv_table.setStyleSheet("QTableWidget { font-size: 11px; } QHeaderView::section { font-size: 10px; padding: 1px; }")
        self.hrv_table.setToolTip("One row per window: the whole recording and each event. HR in bpm; RMSSD and SDNN in "
                                  "ms. The exported file has more (pNN50, pNN20, SD1, SD2, CV, MAD, LF, HF ...). Select a "
                                  "row to read its notes")
        self.hrv_table.itemSelectionChanged.connect(self._hrv_row_selected)
        self.hrv_table.hide()
        self.hrv_notes = QLabel()
        self.hrv_notes.setWordWrap(True)
        self.hrv_notes.hide()
        sensor_layout.addWidget(self.sensors_label)
        sensor_layout.addLayout(sensor_buttons)
        folder_row = QHBoxLayout()
        folder_row.addWidget(self.own_folder_button)
        folder_row.addStretch(1)
        sensor_layout.addLayout(folder_row)
        sensor_layout.addWidget(self.hrv_status)         # the HRV result sits right under its button
        sensor_layout.addWidget(self.hrv_table)
        sensor_layout.addWidget(self.hrv_notes)
        sensor_layout.addWidget(self.signal_list)

        data_page = QWidget()
        data_layout = QVBoxLayout(data_page)
        for box in (rec_box, self.setup_box, video_box, sensor_box):
            data_layout.addWidget(box)
        data_layout.addStretch(1)

        # --- Params: the parameters in pills, with the files they are saved in
        params_page = QWidget()
        params_layout = QVBoxLayout(params_page)
        file_row = QHBoxLayout()
        for text, action in (("Load…", self.load_params_action), ("Save", self.save_params_action),
                             ("Save as…", self.save_params_as_action)):
            button = QPushButton(text)
            button.setToolTip(action.text().replace("&", ""))
            button.clicked.connect(action.trigger)
            file_row.addWidget(button)
        self.revert_button = QPushButton("Revert")
        self.revert_button.setToolTip("Put the parameters back to what they were when they were last loaded or saved")
        self.revert_button.clicked.connect(self.revert_params)
        self.revert_button.setEnabled(False)
        file_row.addWidget(self.revert_button)
        params_layout.addLayout(file_row)
        params_layout.addWidget(self.params_panel, 1)

        # --- Calibrate: numbered steps
        self.cal_note = QLabel()
        self.cal_note.setWordWrap(True)
        self.cal_note.setStyleSheet("font-style: italic;")
        self.cal_note.setVisible(False)
        self.sequence_check = QCheckBox("Show sequence overlay")
        self.sequence_check.toggled.connect(self._sequence_changed)
        self.sequence_start = QDoubleSpinBox()
        self.sequence_start.setRange(-1e6, 1e6)
        self.sequence_start.setDecimals(2)
        self.sequence_start.setSingleStep(0.5)
        self.sequence_start.setSuffix(" s")
        self.sequence_start.setToolTip("Drag its handle under the plots or type a value")
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

        sequence_content = QWidget()
        sequence_form = QFormLayout(sequence_content)
        sequence_form.setContentsMargins(0, 0, 0, 0)
        sequence_form.addRow(self.sequence_label)
        sequence_form.addRow(sequence_buttons)
        sequence_form.addRow(self.find_sequence_button)
        sequence_form.addRow(self.sequence_check)
        sequence_form.addRow("Start", self.sequence_start)
        sequence_form.addRow("ΔPD RMS in sequence", self.sequence_rms)
        self.step_sequence = Step(1, "Sequence", sequence_content)
        self.sequence_controls = self.step_sequence

        self.fit_gamma_check = QCheckBox("Also fit gamma")
        self.fit_gamma_check.setToolTip("Fit the display gamma from the spacing of the grey steps (usually "
                                        "weakly determined; keep the datasheet value unless it clearly fails)")
        self.fit_black_check = QCheckBox("Also fit the black level (Lmin)")
        self.fit_black_check.setToolTip("Fit the display's black level with the white held at its nominal value. "
                                        "Needs steps long enough to dark-adapt; otherwise the black looks "
                                        "brighter than it is. Compare the contrast with the datasheet's")
        self.light_button = QPushButton("Fit light sensitivity")
        self.light_button.setToolTip("Fits the participant's light sensitivity and channel weights from the "
                                     "steady-state pupil on each step, given the display photometry")
        self.light_button.clicked.connect(self.fit_light)
        light_content = QWidget()
        light_form = QFormLayout(light_content)
        light_form.setContentsMargins(0, 0, 0, 0)
        light_form.addRow(self.fit_gamma_check)
        light_form.addRow(self.fit_black_check)
        light_form.addRow(self.light_button)
        self.step_light = Step(2, "Fit light sensitivity", light_content)

        self.fit_dynamics_check = QCheckBox("Include dynamics (time constants and transient)")
        self.fit_dynamics_check.setChecked(True)
        self.fit_dynamics_check.setToolTip("Also fit the dilation and constriction time constants and the "
                                           "transient constriction after brightening (pupillary escape), and "
                                           "turn the dynamics on")
        self.fit_button = QPushButton("Fit latency and offset")
        self.fit_button.setToolTip("Fits the participant's latency, dilation/constriction time constants and pupil "
                                   "offset on the sequence. The pupil scale is not fitted (set it by hand). Fit the "
                                   "light sensitivity first.")
        self.fit_button.clicked.connect(self.fit_sequence)
        timing_content = QWidget()
        timing_form = QFormLayout(timing_content)
        timing_form.setContentsMargins(0, 0, 0, 0)
        timing_form.addRow(self.fit_dynamics_check)
        timing_form.addRow(self.fit_button)
        self.step_timing = Step(3, "Fit latency and offset", timing_content)

        self.fit_weight_check = QCheckBox("Also fit the fixation weight")
        self.fit_weight_check.setToolTip("Also fit the gaze circle's weight of the weighted colour (open issue 47). It "
                                         "needs a scene where the gaze area and the background differ, such as a "
                                         "screen in a room; on a uniform field it cannot be determined. Check the "
                                         "result on other recordings before relying on it")
        self.lux_fit_button = QPushButton("Fit sensitivity and offset")
        self.lux_fit_button.setToolTip("Glasses with a lux sensor: fits the light sensitivity and the pupil offset "
                                       "by least squares on ΔPD over the sequence, with the luminance the analysis "
                                       "builds from the sensor (and the video)")
        self.lux_fit_button.clicked.connect(self.fit_lux)
        lux_content = QWidget()
        lux_form = QFormLayout(lux_content)
        lux_form.setContentsMargins(0, 0, 0, 0)
        lux_form.addRow(self.fit_weight_check)
        lux_form.addRow(self.lux_fit_button)
        self.step_lux = Step(2, "Fit sensitivity and offset", lux_content)

        cal_page = QWidget()
        cal_layout = QVBoxLayout(cal_page)
        cal_layout.addWidget(self.cal_note)
        for step in (self.step_sequence, self.step_light, self.step_timing, self.step_lux):
            cal_layout.addWidget(step)
        cal_layout.addStretch(1)

        # --- Export: the range and the package
        self.trim_panel = TrimPanel()
        self.trim_panel.sequence_span = self._sequence_span
        self.trim_panel.changed.connect(self._trim_changed)
        self.export_summary = QLabel()
        self.export_summary.setWordWrap(True)
        self.export_button = QPushButton("Export results…")
        self.export_button.setMinimumHeight(40)
        self.export_button.setToolTip("One package: the results, the lux and sensor files, the parameters, a manifest "
                                      "and a PDF plot, all cut to the export range")
        self.export_button.clicked.connect(self.export_action.trigger)
        export_page = QWidget()
        export_layout = QVBoxLayout(export_page)
        export_layout.addWidget(self.trim_panel)
        export_layout.addWidget(self.export_summary)
        export_layout.addWidget(self.export_button)
        self.export_progress = QProgressBar()
        self.export_progress.setRange(0, 1000)
        self.export_progress.setTextVisible(False)
        self.export_progress.hide()
        export_layout.addWidget(self.export_progress)
        self.export_result = QLabel()          # what the last export wrote, and where
        self.export_result.setWordWrap(True)
        self.export_result.setOpenExternalLinks(True)
        self.export_result.hide()
        export_layout.addWidget(self.export_result)
        export_layout.addStretch(1)

        # --- the left column: a rail of tabs, their pages, and the preview under them
        self.tab_titles = ("Data", "Params", "Calibrate", "Export")
        self.rail = Rail(self.tab_titles, ("database", "adjustments-horizontal", "target", "file-export"))
        self.pages = QStackedWidget()
        for page in (data_page, params_page, cal_page, export_page):
            scroll = QScrollArea()
            scroll.setWidget(page)
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.NoFrame)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            scroll.horizontalScrollBar().valueChanged.connect(lambda _, bar=scroll.horizontalScrollBar(): bar.setValue(0))
            self.pages.addWidget(scroll)         # the pages only scroll vertically, also by a trackpad swipe
        self.rail.changed.connect(self.pages.setCurrentIndex)

        self.preview = VideoPreview()
        self.preview_holder = PreviewHolder(self.preview)
        self.preview_holder.open_changed.connect(self._preview_toggled)
        self.left_split = QSplitter(Qt.Vertical)
        self.left_split.addWidget(self.pages)
        self.left_split.addWidget(self.preview_holder)
        self.left_split.setStretchFactor(0, 1)
        self.left_split.setChildrenCollapsible(False)
        self.preview_holder.setMinimumHeight(150)
        self.left_split.setSizes([620, 270])      # the preview a little over a third of the column
        self._preview_height = 270
        left = QWidget()
        left_layout = QHBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(0)
        left_layout.addWidget(self.rail)
        left_layout.addWidget(self.left_split, 1)
        left.setMinimumWidth(470)     # the widest page (the export range) needs 455 with its scroll bar

        # --- the right: a status strip over the plots
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(6, 4, 6, 4)
        strip = QHBoxLayout()
        self.summary_label = QLabel()
        self.summary_label.setStyleSheet("font-size: 14px; padding: 2px;")
        self.summary_label.setToolTip(
            "ΔPD RMS and SD: the size of the cognitive-workload signal (measured minus expected pupil), in mm.\n"
            "light left: how much of ΔPD still follows the light (R², and mm per tenfold change of luminance); near 0 is good.\n"
            "expected PD at black and white: the pupil the model predicts at the display's darkest and brightest.\n"
            "pupil ×, offset: the scale and offset applied to the measured pupil.\n"
            "Hz: the recording's sampling rate and the rate it is analysed at; gaps: the share of the recording with no data.")
        self.summary_label.setWordWrap(True)     # a long text must not set the window's minimum width
        self.warnings_button = QToolButton()
        self.warnings_button.setCheckable(True)
        self.warnings_button.setIcon(tinted("alert-triangle", palette.WARNING, 18))
        self.warnings_button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.warnings_button.setStyleSheet(f"QToolButton {{ color: {palette.WARNING}; font-weight: bold; }}")
        self.warnings_button.toggled.connect(lambda on: self.warnings_label.setVisible(on))
        self.warnings_button.hide()
        self.details_label = QLabel()          # the rest of what the strip used to say, in a popover
        self.details_label.setContentsMargins(10, 8, 10, 8)
        self.details_label.setTextFormat(Qt.RichText)
        self.details_button = QPushButton("Details ▾")
        self.details_button.setStyleSheet(DROP_DOWN_STYLE)
        self.details_button.setToolTip("The expected pupil at the display's black and white (or where the luminance comes "
                                       "from), the scale and offset applied, the sampling rates and the gaps")
        self.details_button.setMenu(QMenu(self.details_button))
        holder = QWidgetAction(self.details_button)
        holder.setDefaultWidget(self.details_label)
        self.details_button.menu().addAction(holder)
        self.details_button.hide()
        strip.addWidget(self.summary_label, 1)
        strip.addWidget(self.details_button, 0, Qt.AlignTop)
        strip.addWidget(self.warnings_button, 0, Qt.AlignTop)
        self.warnings_label = QLabel()
        self.warnings_label.setWordWrap(True)
        self.warnings_label.hide()
        self.plots = ResultPlots()
        self.plots.sequence_start_changed.connect(self._sequence_dragged)
        self.plots.trim_dragged.connect(self._trim_dragged)
        self.trim_panel.cursor_time = self.plots.cursor_time
        right_layout.addLayout(strip)
        right_layout.addWidget(self.warnings_label)
        right_layout.addWidget(self.plots, 1)
        # the plots are switched on and off from three drop-downs under them; the choices are checkable actions
        self.plots_bar = QWidget()
        bar = QHBoxLayout(self.plots_bar)
        bar.setContentsMargins(0, 0, 0, 0)

        def drop_down(text: str, tip: str) -> QPushButton:
            button = QPushButton(f"{text} ▾")          # the arrow is part of the text: centred with it
            button.setStyleSheet(DROP_DOWN_STYLE)
            button.setToolTip(tip)
            button.setMenu(QMenu(button))
            return button

        def choice(button: QPushButton, text: str, tip: str, on: bool) -> QAction:
            act = button.menu().addAction(text)
            act.setCheckable(True)
            act.setChecked(on)
            act.setToolTip(tip)
            return act

        self.plots_button = drop_down("Plots", "Choose which plots are shown")
        self.plot_checks = {}
        for key, text, tip, on in (
                ("pupil", "Pupil diameter", "Measured and expected pupil diameter", True),
                ("lum", "Luminance", "The luminance used to predict the pupil (and the lux sensor's average, when there is one)", False),
                ("ratio", "Video ratio", "Y_gaze / Y_frame, only with a lux sensor and the scene video", False),
                ("cw", "ΔPD", "The cognitive-workload signal: measured minus expected pupil diameter", True)):
            check = choice(self.plots_button, text, tip, on)
            check.toggled.connect(partial(self.plots.set_plot_shown, key))
            self.plots.set_plot_shown(key, on)
            self.plot_checks[key] = check
        self.plot_checks["ratio"].setEnabled(False)
        bar.addWidget(self.plots_button)
        self.plots.zoom_button.setShortcut(QKeySequence("Z"))
        self.signals_button = drop_down("Sensor signals", "Show or hide the imported sensor signals under ΔPD")
        self.signals_button.hide()
        self.hrv_bar = QWidget()                # the HRV preview plots, once the HRV is computed
        hrv_layout = QHBoxLayout(self.hrv_bar)
        hrv_layout.setContentsMargins(0, 0, 0, 0)
        self.hrv_button_menu = drop_down("Heart rate variability", "The heart rate and the moving RMSSD, under ΔPD")
        self.hr_check = choice(self.hrv_button_menu, "Heart rate", "The heart rate (bpm) from the trusted intervals, under "
                               "ΔPD on the same time axis", False)
        self.rmssd_check = choice(self.hrv_button_menu, "RMSSD", "The RMSSD (ms) of the trusted intervals of a moving "
                                  "window: a preview of how the vagal part of the variability changes. Not what the "
                                  "export holds (that is per window of the table). Red points: more than 10 % of the "
                                  "intervals were not trusted", True)
        self.rmssd_window = QDoubleSpinBox()
        self.rmssd_window.setRange(10.0, 120.0)
        self.rmssd_window.setSingleStep(5.0)
        self.rmssd_window.setValue(hrv.MOVING_WINDOW_S)
        self.rmssd_window.setSuffix(" s window")
        self.rmssd_window.setKeyboardTracking(False)
        self.rmssd_window.setToolTip("Length of the moving window of the RMSSD (10 to 30 s is the least that is "
                                     "reported as usable)")
        for w in (self.hr_check, self.rmssd_check):
            w.toggled.connect(self._hrv_plots_changed)
        self.rmssd_window.valueChanged.connect(self._hrv_plots_changed)
        hrv_layout.addWidget(self.hrv_button_menu)
        hrv_layout.addWidget(self.rmssd_window)
        self.hrv_bar.hide()
        bar.addWidget(self.hrv_bar)
        bar.addWidget(self.signals_button)
        bar.addStretch(1)
        right_layout.addWidget(self.plots_bar)

        splitter = QSplitter()
        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([480, 1080])
        self.setCentralWidget(splitter)
        self.main_split = splitter

        self.preview.time_changed.connect(self.plots.set_cursor)
        self.plots.cursor_changed.connect(self.preview.request_time)
        self.preview_action = QAction("Show video preview", self, checkable=True, checked=True)
        self.preview_action.setShortcut(QKeySequence("P"))
        self.preview_action.toggled.connect(self.preview_holder.set_open)
        self.view_menu.addAction(self.preview_action)
        self.view_menu.addSeparator()
        for i, title in enumerate(self.tab_titles):
            tab_action = QAction(f"{title} tab", self)
            tab_action.setShortcut(QKeySequence(f"Ctrl+{i + 1}"))
            tab_action.triggered.connect(lambda _=False, i=i: self.rail.set_current(i))
            self.view_menu.addAction(tab_action)

    def _preview_toggled(self, open_: bool) -> None:
        """The preview was hidden, shown or popped out: give its room to the page above, or back."""
        sizes = self.left_split.sizes()
        total = sum(sizes)
        self.preview_holder.setMinimumHeight(150 if open_ else 0)     # only an open preview needs room
        if open_:
            self.left_split.setSizes([max(total - self._preview_height, 100), self._preview_height])
        else:
            if sizes[1] > 40:
                self._preview_height = sizes[1]
            self.left_split.setSizes([total, 0])
        self.preview_action.blockSignals(True)
        self.preview_action.setChecked(open_)
        self.preview_action.blockSignals(False)

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
        """The calibration steps for a display device (the sequence and both fits), a glasses recording with a lux
        log (the sequence and the sensitivity and offset fit) or neither (nothing to fit, a note says why)."""
        self.step_sequence.setVisible(mode != "none")
        self.find_sequence_button.setVisible(mode == "display")
        self.step_light.setVisible(mode == "display")
        self.step_timing.setVisible(mode == "display")
        self.step_lux.setVisible(mode == "lux")
        self.cal_note.setText({
            "lux": "Glasses have no display photometry, so the light comes from the lux sensor. Load the "
                   "presenter's run file: its onset times place the start. The fit sets the light sensitivity "
                   "and the pupil offset; set the dynamics by hand (Params, Participant).",
            "none": "The calibration sequence and its fits need the display photometry (Varjo) or a lux sensor "
                    "log (glasses). Set the dynamics by hand in Params, Participant.",
        }.get(mode, ""))
        self.cal_note.setVisible(mode != "display")

    def _update_state(self) -> None:
        busy = self._task is not None and self._task.isRunning()
        has_rec = self.recording is not None
        self.analyse_button.setEnabled(has_rec and not busy and self.recording.scene_video is not None)
        self.analyse_button.setText("Reanalyse video" if self.video is not None else "Analyse video")
        self.analyse_button.setToolTip("Analyse the scene video again, ignoring the saved analysis"
                                       if self.video is not None else "Analyse the scene video")
        self.cancel_button.setVisible(busy and getattr(self, "_task_cancellable", False))   # the video analysis and the fit
        self.open_action.setEnabled(not busy)
        self.forget_logs_action.setEnabled(self._logs_for_recording() is not None and not busy)
        self.export_action.setEnabled(self.result is not None)
        self.fit_button.setEnabled(self.result is not None and self.sequence_check.isChecked() and not busy)
        self.light_button.setEnabled(self.fit_button.isEnabled())
        self.lux_fit_button.setEnabled(self.fit_button.isEnabled())
        self.find_sequence_button.setEnabled(self.video is not None and not busy)
        has_lux = has_rec and self.recording.lux_values is not None
        self.camera_button.setVisible(has_rec and self.recording.luminance_source == "lux_sensor")
        self.camera_button.setEnabled(has_lux and self.video is not None and not busy)
        warnings = [] if self.result is None else list(self.result.warnings)
        self.warnings_button.setVisible(bool(warnings))
        self.warnings_button.setText(f"{len(warnings)} warning{'s' if len(warnings) != 1 else ''}")
        self.warnings_button.setToolTip("Show or hide the warnings")
        self.warnings_label.setText("".join(f"<span style='color:{palette.WARNING}'>⚠ {w}</span><br>"
                                            for w in warnings))
        if not warnings:
            self.warnings_button.setChecked(False)
        if self.result is None:
            self.summary_label.setText("Open a recording to start." if not has_rec else "")
            self.details_label.setText("")
        else:
            r = self.result
            gaps = f", gaps {r.gap_fraction:.0%}" if r.gap_fraction >= 0.005 else ""
            leak = (f" &nbsp;&nbsp; <b>light left</b> R² {r.leak_r2:.2f} ({r.leak_slope:+.2f} mm/decade)"
                    if np.isfinite(r.leak_r2) else "")
            ends = (f"expected PD at black {r.expected_black:.2f} mm, white {r.expected_white:.2f} mm &nbsp;&nbsp; "
                    if np.isfinite(r.expected_black) else self._route_text(r) + " &nbsp;&nbsp; ")
            self.summary_label.setText(f"<b>ΔPD RMS</b> {r.cw_rms:.3f} mm &nbsp; <b>SD</b> {r.cw_sd:.3f} mm{leak}")
            self.details_label.setText(
                f"{ends.replace(' &nbsp;&nbsp; ', '')}<br>pupil ×{r.pupil_scale:.3g}, offset {r.offset:+.2f} mm<br>"
                f"{r.measured_rate:.0f} Hz → {r.rate:.0f} Hz{gaps}")
        self.details_button.setVisible(self.result is not None)
        self.own_folder_button.setEnabled(self._logs_for_recording() is not None and not busy)
        missing_lux = has_rec and self.recording.luminance_source == "lux_sensor" and self.recording.lux_values is None
        self.rail.mark(0, bool(missing_lux), "No lux sensor readings found for this recording")
        self.export_button.setEnabled(self.result is not None)
        self._update_export_summary()
        name = self._params_path.name if self._params_path else "unsaved parameters"
        if has_rec and self.recording.luminance_source == "display":
            name += ", display " + (self._display_path.name if self._display_path else "defaults")
        rec = f": {self.recording.name}" if has_rec else ""
        changed = self.params_dirty()
        self._update_setup()
        self.revert_button.setEnabled(changed and not busy)
        self.setWindowTitle(f"Cognitive Workload Tool {__version__}{rec} ({name}{', changed' if changed else ''})")

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

    RECENT_MAX = 10

    def _recent_recordings(self) -> list[str]:
        """The recordings opened last (newest first) that still exist."""
        value = self._settings.value("recent_recordings", [])
        folders = [value] if isinstance(value, str) else list(value or [])
        return [f for f in folders if Path(f).is_dir()]

    def _remember_recording(self, folder: Path) -> None:
        """Put ``folder`` at the top of the recent recordings."""
        folders = [str(folder)] + [f for f in self._recent_recordings() if f != str(folder)]
        self._settings.setValue("recent_recordings", folders[:self.RECENT_MAX])

    def _fill_recent_menu(self) -> None:
        """File → Open recent: the last recordings, each opened by a click."""
        self.recent_menu.clear()
        folders = self._recent_recordings()
        for folder in folders:
            act = self.recent_menu.addAction(f"{Path(folder).name}   ({Path(folder).parent})")
            act.setToolTip(folder)
            act.triggered.connect(lambda _=False, f=folder: self.open_recording(Path(f)))
            act.setEnabled(not (self._task is not None and self._task.isRunning()))
        if not folders:
            self.recent_menu.addAction("No recordings yet").setEnabled(False)
        else:
            self.recent_menu.addSeparator()
            self.recent_menu.addAction("Clear the list").triggered.connect(
                lambda: self._settings.setValue("recent_recordings", []))

    def _error(self, title: str, message: str, hint: bool = True) -> None:
        """Tell the user what went wrong in a sentence, what to try (for the errors we know), and the details."""
        head, details = errors.split_message(message)
        box = QMessageBox(QMessageBox.Warning, title, head, parent=self)
        if hint:
            box.setInformativeText(errors.advice(message))
        if details:
            box.setDetailedText(details)
        box.exec()

    def show_gestures(self) -> None:
        """Help: the mouse gestures of the plots and the keyboard shortcuts."""
        box = QMessageBox(QMessageBox.NoIcon, "Gestures and shortcuts", errors.gestures_html(), parent=self)
        box.setTextFormat(Qt.RichText)
        box.exec()

    def show_about(self) -> None:
        """Help: the version and where the documentation is."""
        QMessageBox.about(self, "About", f"<b>Cognitive Workload Tool {__version__}</b><br>Pupil-based cognitive "
                          f"workload from eye-tracking recordings, with the sensor logger's data.<br>"
                          f"<a href='{errors.DOCS_URL}'>{errors.DOCS_URL}</a>")

    # Recording and video

    def choose_recording(self) -> None:
        """Ask for a recording folder and open it."""
        start = self._settings.value("last_recording_dir", str(Path.home()))
        folder = QFileDialog.getExistingDirectory(self, "Open recording folder", start)
        if folder:
            self._settings.setValue("last_recording_dir", str(Path(folder).parent))
            self._logs_override = None               # a session chosen for the last recording is not for this one
            self.open_recording(Path(folder))

    def _logs_for_recording(self) -> Path | None:
        """The logger folder to look in for the open recording's lux log and sensor files: the session chosen for it, else
        the remembered recordings folder, else None (the recording's own folder)."""
        return self._logs_override or self._logs_folder

    def set_logs_folder(self, folder: Path | None, remember: bool = True) -> None:
        """Use ``folder`` (the logger's recordings folder, or one session) for the lux log and the sensor files. A
        recordings folder is remembered for every recording; one session is used for the open recording only. The lux log
        is read when the recording is loaded, so a glasses recording is loaded again; the sensor files are imported."""
        if folder is not None and sensors.is_session(folder):
            self._logs_override = folder
            self._settings.setValue("last_sensor_dir", str(folder.parent))
        else:
            self._logs_override = None
            self._logs_folder = folder
            if remember:
                self._settings.setValue("sensor_logs_folder", str(folder) if folder else "")
                self._settings.setValue("lux_folder", "")
                if folder:
                    self._settings.setValue("last_sensor_dir", str(folder))
        rec = self.recording
        if rec is None:
            self._update_state()
            return
        if rec.luminance_source == "lux_sensor":
            self.open_recording(rec.folder)          # reads the lux log again, then imports the sensor files
        elif self._logs_for_recording() is not None:
            self.import_sensors(self._logs_for_recording())
        self._update_state()

    def forget_logger_folder(self) -> None:
        """Go back to looking for the lux log and the sensor files in the recording's own folder."""
        self.set_logs_folder(None)

    def open_recording(self, folder: Path) -> None:
        """Load a recording in the background, then set up the plots, the preview and the controls for its device."""
        same = self.recording is not None and Path(folder) == self.recording.folder     # a reload of the open one
        if not same and not self._confirm_params("opening another recording"):
            return
        lux_folder = self._logs_for_recording()

        def load(progress, cancelled):
            """Background task: read the recording."""
            return devices.load(folder, lux_folder=lux_folder)

        self._start_task(load, self._recording_loaded, f"Loading {folder.name}…")

    def _recording_loaded(self, rec) -> None:
        previous_device = self._params_device
        self._params_note = None
        self.recording, self.video, self.result = rec, None, None
        if previous_device and previous_device != rec.device:
            self._forget_params_of(previous_device, rec.device)
        self._remember_recording(rec.folder)
        duration = rec.time[-1] - rec.time[0] if len(rec.time) else 0
        video = rec.scene_video.name if rec.scene_video else "none"
        prof = rec.profile
        scale = f"×{prof.pupil_scale:g}" if prof.pupil_scale else "scale fitted"
        self.recording_label.setText(
            f"<b>{rec.name}</b><br>{rec.device}, {len(rec.time)} samples, {duration:.1f} s, "
            f"{rec.measured_rate:.0f} Hz<br>camera {prof.field_of_view[0]:.0f}° × {prof.field_of_view[1]:.0f}°, "
            f"adapting field {prof.field_area:,.0f} deg², pupil {prof.pupil_unit} {scale}"
            f"<br>video: {video}<br>events: {len(rec.events)}"
)
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
        self._params_device = rec.device
        if getattr(self, "_params_baseline", None) is None:
            self._mark_params_saved()              # the starting parameters: changes are measured from them
        if len(rec.time):
            self.plots.set_cursor(float(rec.time[0]))
        self._update_state()
        if rec.scene_video is None:
            self.video_label.setText("No scene video found in this recording.")
        else:
            self.analyse(use_cache=True)

    def analyse(self, use_cache: bool) -> None:
        """Analyse the scene video in the background (or take the cached analysis if ``use_cache`` and one matches) and
        then compute the result.
        """
        rec = self.recording
        settings = self.params_panel.video_settings().for_recording(rec)
        if use_cache:
            cached = VideoResult.load_cached(rec.folder, settings, rec.scene_video, rec.scene_frame_times,
                                             rec.gaze)
            if cached is not None:
                self._video_ready(cached, "cached analysis")
                return

        def work(progress, cancelled):
            """Background task: analyse the video and save the analysis next to the recording."""
            res = analyse_video(rec.scene_video, rec.time, rec.gaze, settings, progress, cancelled,
                                frame_times=rec.scene_frame_times)
            if cancelled():
                return None
            res.save(rec.folder, settings, rec.scene_video, rec.scene_frame_times, rec.gaze)
            return res

        self._start_task(work, lambda res: res and self._video_ready(res, "analysed"),
                         f"Analysing {rec.scene_video.name}…", show_progress=True, cancellable=True)

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

    def _start_task(self, fn, on_success, message: str, show_progress: bool = False, bar=None,
                    cancellable: bool = False) -> None:
        """Run ``fn(progress, cancelled)`` in the background; ``bar`` is the progress bar to drive (default: the video
        analysis' one in the Data tab). The Cancel button is offered only for a task that checks ``cancelled``."""
        if self._task is not None and self._task.isRunning():
            return
        self.statusBar().showMessage(message)
        self._task_message = message
        self._task_cancellable = cancellable
        self.cancel_button.setEnabled(True)
        self._task = Task(fn, self)
        self._bar = bar or self.progress
        self._task.progressed.connect(lambda p: self._bar.setValue(int(p * 1000)))
        self._task.succeeded.connect(on_success)
        self._task.failed.connect(self._task_failed)
        self._task.finished.connect(self._task_finished)
        self._bar.setValue(0)
        self._bar.setVisible(show_progress)
        self._task.start()
        self._update_state()

    def _task_failed(self, message: str) -> None:
        """A background task raised: tell the user, except when it only stopped because they cancelled it."""
        if self._task is not None and self._task.is_cancelled():
            return
        self._error("Error", message)

    def _task_finished(self) -> None:
        if self._task is not None and self._task.is_cancelled():
            self.statusBar().showMessage("Cancelled.", 4000)
            self._task_message = None
        self.progress.hide()
        self.export_progress.hide()
        if self.statusBar().currentMessage() == getattr(self, "_task_message", None):
            self.statusBar().clearMessage()      # the task's own message; not the result it reported meanwhile
        self._update_state()

    def cancel_task(self) -> None:
        """Stop the running background task."""
        if self._task is not None:
            self._task.cancel()
            self.cancel_button.setEnabled(False)
            self.statusBar().showMessage("Cancelling…")
            self._task_message = "Cancelling…"

    # Parameters and results

    def _params_edited(self) -> None:
        self._recompute_timer.start()

    def recompute(self) -> None:
        """Run the pipeline with the current parameters and show the result; the status shows the error if it fails."""
        if self.recording is None or self.video is None:
            return
        try:
            self.result = pipeline.run(self.recording, self.video, self.params_panel.params())
        except Exception as e:
            self.result = None
            self.statusBar().showMessage(f"Analysis failed: {e}")
            self.plots.clear_result()
            if str(e) != self._last_failure:       # one box per cause, not one per edit of the parameters
                self._last_failure = str(e)
                self._error("The analysis failed", f"{e}\n\n{traceback.format_exc()}")
        else:
            self._last_failure = None
            self.plots.show_result(self.result)
            self.plot_checks["ratio"].setEnabled(self.plots.ratio_available())
            self._update_sequence_rms()
        self.preview.set_analysis(self.video, self.result)
        self._update_state()

    def _sequence_changed(self) -> None:
        self.plots.set_sequence(self.sequence_check.isChecked(), self.sequence_start.value(), self.sequence)
        self.trim_panel.refresh_buttons()
        self._update_sequence_rms()
        self._update_state()

    def fit_light(self) -> None:
        """Fit the display photometry (sensitivity, gains, gamma, black level) on the calibration sequence, in the
        background.
        """
        rec, video, params = self.recording, self.video, self.params_panel.params()
        start, sequence, gamma = self.sequence_start.value(), self.sequence, self.fit_gamma_check.isChecked()
        black = self.fit_black_check.isChecked()

        def work(progress, cancelled):
            """Background task: the display photometry fit."""
            return fit_light_response(rec, video, params, start, sequence, fit_gamma=gamma, fit_black=black)

        self._start_task(work, self._light_done, "Fitting the light response on the calibration sequence…")

    def _light_done(self, fit) -> None:
        if PhotometryDialog(fit, self).exec():
            self.params_panel.set_params(fit.params)
            self.fits_done["light"] = True
            self.step_light.set_summary(f"Applied: light sensitivity ×{fit.params.sensitivity:.3g}")
            self._update_state()

    def fit_lux(self) -> None:
        """Fit the sensitivity and pupil offset of a glasses recording on the calibration sequence, in the background.
        """
        rec, video, params = self.recording, self.video, self.params_panel.params()
        start, sequence = self.sequence_start.value(), self.sequence
        weight = self.fit_weight_check.isChecked()

        def work(progress, cancelled):
            """Background task: the lux sensor fit."""
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
            self.fits_done["lux"] = True
            self.step_lux.set_summary(f"Applied: sensitivity ×{fit.sensitivity:.3g}, offset {fit.offset:+.3f} mm, "
                                      f"ΔPD RMS in sequence {fit.rms_after:.3f} mm")

    def fit_sequence(self) -> None:
        """Fit latency, dynamics and pupil scale on the calibration sequence, in the background."""
        rec, video, params = self.recording, self.video, self.params_panel.params()
        start, dynamics = self.sequence_start.value(), self.fit_dynamics_check.isChecked()
        sequence = self.sequence
        end = start + sequence.duration

        def work(progress, cancelled):
            """Background task: the calibration sequence fit."""
            return fit_calibration(rec, video, params, start, end, fit_dynamics=dynamics, cancelled=cancelled,
                                   sequence=sequence, fit_transient=dynamics)

        self._start_task(work, self._fit_done, "Fitting on the calibration sequence…", cancellable=True)

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
            self.fits_done["timing"] = True
            self.step_timing.set_summary(f"Applied: latency {fit.delay:.2f} s, ΔPD RMS in sequence "
                                         f"{fit.rms_after:.3f} mm")

    def calibrate_camera(self) -> None:
        """Calibrate the camera's full-scale luminance against the lux sensor and put it in the parameters."""
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
        """Load a sequence file; a presenter run file also places it in the recording from its onset times."""
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
        """Find the calibration sequence in the recording from the colours the video saw, and place it."""
        if self.video is None:
            return
        base = self._base_sequence or self.sequence
        loc = calibration.locate(self.video.time, self.video.background_rgb, base)
        if loc is None or loc.error > 0.35:
            self._error("Sequence not found", "Could not match the calibration sequence to this recording's "
                                              "scene colours. Place it by dragging its handle under the plots.")
            return
        self.set_sequence(loc.sequence, keep_base=True)
        self.sequence_start.setValue(loc.start)
        self.sequence_check.setChecked(True)
        gaps = f", {1 - loc.coverage:.0%} of it in tracking gaps" if loc.coverage < 0.95 else ""
        self.statusBar().showMessage(f"Sequence found at {loc.start:.2f} s "
                                     f"(colour match error {loc.error:.0%}{gaps})", 5000)

    def set_sequence(self, sequence: calibration.Sequence, keep_base: bool = False) -> None:
        """Use this sequence for the overlay and the fits (``keep_base`` keeps the unscaled one to search with)."""
        if not keep_base:
            self._base_sequence = sequence
        self.sequence = sequence
        self.sequence_label.setText(f"{sequence.name}: {len(sequence.steps)} steps, {sequence.duration:.0f} s")
        self._sequence_changed()

    # The set-up checklist at the top of the Data tab

    OK_COLOUR = "#4b9a2a"

    def _setup_items(self) -> list:
        """``(done, text, link)`` of what the open recording needs before its ΔPD can be trusted: for a display device the
        display photometry, the calibration sequence and the participant's two fits; for glasses with a lux sensor the lux
        readings, the sequence and the fit of the sensitivity and offset. Empty for a device that needs none of it."""
        rec = self.recording
        if rec is None:
            return []

        def fit(name: str, key: str) -> tuple:
            """A fit counts as done when it was applied in this session or the participant's file was loaded."""
            if self.fits_done[key]:
                return True, f"{name} fitted", "tab:2"
            if self._params_path is not None:
                return True, f"{name} fitted (from {self._params_path.name})", "tab:2"
            return False, f"{name} not fitted", "tab:2"

        placed = self.sequence_check.isChecked()
        sequence = (placed, "Calibration sequence placed" if placed
                    else "Calibration sequence not placed: show its overlay and set its start", "tab:2")
        if rec.luminance_source == "display":
            if self._display_path is not None:
                photometry = (True, f"Display photometry loaded ({self._display_path.name})", "action:display")
            else:
                photometry = (False, "Display photometry not loaded: the nominal defaults are used", "action:display")
            return [photometry, sequence, fit("Light sensitivity", "light"), fit("Latency and offset", "timing")]
        if rec.luminance_source == "lux_sensor":
            if rec.lux_values is not None:
                lux = (True, f"Lux readings found ({len(rec.lux_values):,})", "action:logs")
            else:
                lux = (False, "Lux readings not found: choose the logger folder", "action:logs")
            return [lux, sequence, fit("Sensitivity and offset", "lux")]
        return []

    def _update_setup(self) -> None:
        items = self._setup_items()
        self.setup_box.setVisible(bool(items) or bool(self._params_note))
        lines = []
        for done, text, link in items:
            mark = f"<span style='color:{self.OK_COLOUR}'>✓</span>" if done else f"<span style='color:{palette.WARNING}'>✗</span>"
            lines.append(f"{mark} " + (text if done else f"<a href='{link}' style='color:{palette.WARNING}'>{text}</a>"))
        if self._params_note:
            lines.append(f"<i>{self._params_note}</i>")
        self.setup_label.setText("<br>".join(lines))

    def _setup_link(self, link: str) -> None:
        """A line of the checklist was clicked: go to where it is done."""
        kind, _, value = link.partition(":")
        if kind == "tab":
            self.rail.set_current(int(value))
        elif value == "display":
            self.choose_display()
        elif value == "logs":
            self.choose_sensors()

    def _forget_params_of(self, old: str, new: str) -> None:
        """A recording of another device was opened: the calibration and the parameters depend on the hardware, so the
        participant's parameters of the previous device are not carried over; the defaults are used and the file is let go."""
        self.params_panel.set_params(Parameters())
        self._params_path = None
        self._display_path = None
        self.fits_done = {key: False for key in self.fits_done}
        self._mark_params_saved()
        self._params_note = (f"The parameters were set for a {old} recording: back to the defaults for this {new} recording "
                             "(the calibration and the parameters depend on the hardware).")

    def _participant_dict(self) -> dict:
        """The parameters as the participant's file holds them (without the display photometry)."""
        data = asdict(self.params_panel.params())
        for key in DISPLAY_FIELDS:
            data.pop(key, None)
        return data

    def _mark_params_saved(self) -> None:
        """The parameters now are the ones on disk (just loaded or saved), or the starting ones: changes are measured
        from here."""
        self._params_baseline = self.params_panel.params()

    def params_dirty(self) -> bool:
        """True if the participant's parameters differ from the last loaded or saved state."""
        base = getattr(self, "_params_baseline", None)
        if base is None:
            return False
        saved = asdict(base)
        for key in DISPLAY_FIELDS:
            saved.pop(key, None)
        return saved != self._participant_dict()

    def revert_params(self) -> None:
        """Put the parameters back to the last loaded or saved state, after asking (the display photometry stays)."""
        if not self.params_dirty():
            return
        name = self._params_path.name if self._params_path else "the starting values"
        if QMessageBox.question(self, "Revert parameters", f"Discard the changes and go back to {name}?") \
                != QMessageBox.Yes:
            return
        self._restore_baseline()

    def _restore_baseline(self) -> None:
        current = self.params_panel.params()
        self.params_panel.set_params(replace(self._params_baseline, **{k: getattr(current, k) for k in DISPLAY_FIELDS}))
        self._update_state()

    def _ask_unsaved(self, what: str):
        """Ask what to do with changed parameters before ``what`` ("opening another recording", "closing")."""
        saved = f"since {self._params_path.name} was saved or loaded" if self._params_path else "since the start"
        return QMessageBox.question(
            self, "Parameters changed", f"The parameters have changed {saved}. Save them before {what}?",
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel, QMessageBox.Save)

    def _confirm_params(self, what: str) -> bool:
        """True if it is fine to go on (``what``): the parameters are unchanged, or were saved or discarded; False if the
        user cancelled."""
        if not self.params_dirty():
            return True
        choice = self._ask_unsaved(what)
        if choice == QMessageBox.Save:
            self.save_params()
            return not self.params_dirty()          # the file dialog may have been cancelled
        if choice == QMessageBox.Discard:
            self._restore_baseline()
            return True
        return False

    def choose_params(self) -> None:
        """Ask for a participant parameter file and load it (the display photometry is kept)."""
        path, _ = QFileDialog.getOpenFileName(self, "Load parameters", self._params_dir(), "Parameters (*.json)")
        if path:
            try:
                profile = self.recording.profile if self.recording is not None else None
                # Participant files hold no display photometry: the current one is kept.
                self.params_panel.set_params(Parameters.load(path, profile, base=self.params_panel.params(),
                                                             device=self._device() or None))
            except DeviceMismatch as e:
                self._error("Parameters of another device", str(e), hint=False)
                return
            except Exception as e:
                self._error("Cannot load parameters", str(e))
                return
            self._params_path = Path(path)
            self._params_note = None
            self._params_device = self._device() or self._params_device
            self._mark_params_saved()
            self._update_state()

    def save_params(self) -> None:
        """Save the participant parameters to the current file, or ask for one."""
        if self._params_path is None:
            self.save_params_as()
        else:
            self.params_panel.params().save(self._params_path, participant_only=True, device=self._device())
            self._mark_params_saved()
            self._update_state()
            self.statusBar().showMessage(f"Saved {self._params_path} (display photometry is saved separately)", 4000)

    def save_params_as(self) -> None:
        """Ask for a file and save the participant parameters there."""
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
        """Ask for a display photometry file and load it."""
        path, _ = QFileDialog.getOpenFileName(self, "Load display photometry", self._params_dir(),
                                              "Display photometry (*.json)")
        if path:
            self.load_display(Path(path))

    def load_display(self, path: Path, quiet: bool = False) -> None:
        """Load a display photometry file (black, white, gamma) into the parameters."""
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
        """Save the display photometry in the parameters to a file."""
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

    def _update_export_summary(self) -> None:
        self._update_hrv_controls()
        rec = self.recording
        if rec is None or self.result is None:
            self.export_summary.setText("")
            return
        parts = ["pupil", "ΔPD"]
        if rec.events:
            parts.append(f"{len(rec.events)} event{'s' if len(rec.events) != 1 else ''}")
        if rec.lux_values is not None:
            parts.append("lux")
        parts += [f"{s.name} + HRV" if s.name in self.hrv_beats else s.name for s in self.sensors]
        parts += ["parameters", "manifest", "PDF plot"]
        self.export_summary.setText("The package holds: " + ", ".join(parts) + ".")

    def _restore_layout(self) -> None:
        """The tab, the pill and the preview as they were left."""
        st = self._settings
        self.rail.set_current(int(st.value("ui/tab", 0)))
        self.pages.setCurrentIndex(self.rail.current())
        self.params_panel.pills.set_current(int(st.value("ui/pill", 0)))
        if str(st.value("ui/preview_open", "true")) == "false":
            self.preview_holder.set_open(False)
        self.preview_holder.values_button.setChecked(str(st.value("ui/values", "false")) == "true")
        sizes = st.value("ui/main_sizes")
        if sizes:
            self.main_split.setSizes([int(v) for v in sizes])

    def _save_layout(self) -> None:
        st = self._settings
        st.setValue("ui/tab", self.rail.current())
        st.setValue("ui/pill", self.params_panel.pills.current())
        st.setValue("ui/preview_open", "true" if self.preview_holder.is_open() else "false")
        st.setValue("ui/values", "true" if self.preview_holder.values_button.isChecked() else "false")
        st.setValue("ui/main_sizes", self.main_split.sizes())

    # Sensor data and the export range

    def choose_sensors(self) -> None:
        """Ask for a sensor logger session folder and import its sensor data."""
        if self.recording is None:
            self._error("Import sensor data", "Open a recording first: the sensor data is placed on its time axis.")
            return
        start = str(self._logs_folder or self._settings.value("last_sensor_dir", str(self.recording.folder)))
        folder = QFileDialog.getExistingDirectory(self, "Sensor logger folder: its recordings folder, or one session", start)
        if folder:
            self.set_logs_folder(Path(folder))

    def _recording_sensors_and_trim(self, rec) -> None:
        """A recording was opened: forget the sensor data of the previous one, look for the logger's files in the
        recording's own folder, and bring back the export range saved with it."""
        self.sensors = []
        self._no_session = None
        self._clear_hrv()
        self.signal_list.clear()
        self._rebuild_signal_menu()
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
        logs = self._logs_for_recording()
        if sensors.find_sensor_files(rec.folder):
            self.import_sensors(rec.folder, quiet=True)
        elif logs is not None:                       # the logger's recordings folder, given once for all recordings
            self.import_sensors(logs, quiet=True)

    def import_sensors(self, folder: Path, quiet: bool = False) -> None:
        """Load the Shimmer and EmotiBit files of a logger session, cut to the recording's span and placed on its time
        axis.
        """
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
            """Background task: find the session of the recording (in the logger's folder, if that is what was given) and
            read its sensor files."""
            session, _ = sensors.resolve_session(folder, start, span)
            return sensors.load_sensors(folder, start, span), session or folder

        self.statusBar().showMessage(f"Reading the sensor data in {folder.name}…")
        self._sensor_task = Task(load, self)
        self._sensor_task.succeeded.connect(lambda result: self._sensors_loaded(result[0], result[1], quiet, folder))
        self._sensor_task.failed.connect(lambda msg: self._error("Import sensor data", msg))
        self._sensor_task.finished.connect(lambda: self.statusBar().clearMessage())
        self._sensor_task.start()

    def _sensors_loaded(self, found, folder: Path, quiet: bool, given: Path | None = None) -> None:
        """The sensor files were read: ``folder`` is the session they come from, ``given`` the folder that was asked for
        (the logger's recordings folder, when that is what it was)."""
        if not found:
            if not quiet:
                self._error("Import sensor data", f"No sensor data in {given or folder} overlaps this recording. The "
                                                  "files must come from the sensor logger (their first column is the "
                                                  "Unix time) and cover the same time as the recording; if the folder "
                                                  "is the logger's recordings folder, none of its sessions does.")
            elif given is not None and given == self._logs_for_recording():     # the remembered folder gave nothing
                self._no_session = (f"No session in {given or folder} overlaps this recording. Check that the logger's "
                                    "computer clock and the eye tracker's agree, or choose another folder.")
                self._update_sensors_label()
            return
        self._no_session = None
        self.sensors = found
        self._clear_hrv()
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
        """Forget the imported sensor data."""
        self.sensors = []
        self._clear_hrv()
        self.signal_list.clear()
        self._rebuild_signal_menu()
        self.plots.set_sensors([])
        self._update_sensors_label()

    def _rebuild_signal_menu(self) -> None:
        """The menu under the plots lists the signals of the list (ticked = shown); a tick in either changes the other."""
        menu = self.signals_button.menu()
        items = [self.signal_list.item(row) for row in range(self.signal_list.count())]
        if [a.text() for a in menu.actions()] == [i.text() for i in items]:     # the same signals: only the ticks
            for action, item in zip(menu.actions(), items):
                action.blockSignals(True)
                action.setChecked(item.checkState() == Qt.Checked)
                action.blockSignals(False)
            return
        menu.clear()
        for row in range(self.signal_list.count()):
            item = self.signal_list.item(row)
            action = menu.addAction(item.text())
            action.setCheckable(True)
            action.setChecked(item.checkState() == Qt.Checked)
            action.toggled.connect(lambda on, item=item: item.setCheckState(Qt.Checked if on else Qt.Unchecked))
        self.signals_button.setVisible(self.signal_list.count() > 0)

    def _lux_line(self) -> str:
        """The lux log as one of the sensor inputs: for a glasses recording, how many readings it has (or that none were
        found); nothing for a device that takes its light from the display."""
        rec = self.recording
        if rec is None or rec.luminance_source != "lux_sensor":
            return ""
        if rec.lux_values is None:
            return (f"<span style='color:{palette.WARNING}'>lux sensor: no readings found for this recording. Choose the "
                    f"logger folder (or put the lux log in the recording's folder)</span>")
        return f"lux sensor: {len(rec.lux_values):,} readings (drawn with the luminance, exported)"

    def _update_sensors_label(self, folder: Path | None = None) -> None:
        """What the Sensor data box says: the lux log, the imported sensor files, and where they come from."""
        lines = [self._lux_line()]
        logs = self._logs_for_recording()
        if not self.sensors:
            lines.append("The sensor logger's folder gives the lux log and the Shimmer and EmotiBit files, which can be "
                         "shown under ΔPD and exported with it, as one package.")
            self.sensors_label.setToolTip("")
        else:
            lines.append(", ".join(f"{s.name} ({len(s):,} rows)" for s in self.sensors)
                         + (f" from {folder.name}" if folder else ""))
            lines += [f"<span style='color:{palette.WARNING}'>{s.name}: {note}</span>"
                      for s in self.sensors if hrv.has_ecg(s) for note in self._ecg_notes(s)]
            self.sensors_label.setToolTip(str(folder) if folder else "")
        if logs:
            lines.append(f"Logger folder: {logs} (the session of each recording is found in it)")
        if self._no_session and not self.sensors:
            lines.append(f"<span style='color:{palette.WARNING}'>{self._no_session}</span>")
        self.sensors_label.setText("<br>".join(line for line in lines if line))
        self.remove_sensors_button.setEnabled(bool(self.sensors))
        self._update_export_summary()

    def _ecg_sensors(self) -> list:
        """The imported sensors that hold a Shimmer ECG."""
        return [s for s in self.sensors if hrv.has_ecg(s)]

    def _update_hrv_controls(self) -> None:
        """The Compute HRV button is on with an ECG imported and no other task running."""
        busy = self._task is not None and self._task.isRunning()
        self.hrv_button.setEnabled(bool(self._ecg_sensors()) and not busy)
        self.hrv_button.setText("Recompute HRV" if self.hrv_beats else "Compute HRV")

    def compute_hrv(self) -> None:
        """Find the heartbeats in the Shimmer's ECG in the background, then show the HRV of the whole recording and of
        each event, draw the beats on the ECG plot and keep them for the export."""
        ecg = self._ecg_sensors()
        if not ecg or self.recording is None:
            return
        self.hrv_status.setText("Finding the heartbeats…")
        self.hrv_status.show()

        def work(progress, cancelled):
            """Background task: the beats of each ECG."""
            return {s.name: hrv.beats_of(s) for s in ecg}

        self._start_task(work, self._hrv_done, "Finding the heartbeats…")

    def _hrv_done(self, found: dict) -> None:
        """The beats were found: keep them, and show the measures and the beats."""
        self.hrv_beats = {name: beats for name, beats in found.items() if beats is not None}
        if not self.hrv_beats:
            self.hrv_status.setText("No ECG lead was found in the sensor data.")
        self._refresh_hrv()
        self._update_export_summary()

    def _clear_hrv(self) -> None:
        """Forget the beats and the table (the recording or the sensor data changed)."""
        self.hrv_beats, self.hrv_series = {}, None
        self.hrv_table.setRowCount(0)
        for w in (self.hrv_table, self.hrv_status, self.hrv_notes, self.hrv_bar):
            w.hide()
        self.plots.clear_beats()
        self._update_hrv_controls()

    def _refresh_hrv(self) -> None:
        """The table and the beat markers from the beats found, for the current export range: only the windows and the
        trusted intervals are worked out again, not the detection, so this follows the range as it is edited."""
        rec = self.recording
        if not self.hrv_beats or rec is None:
            return
        trim, windows = self.trim_panel.trim(), pipeline.hrv_windows(rec)
        several = len(self.hrv_beats) > 1
        rows, beats_total, untrusted, series = [], 0, 0, None
        for s in self.sensors:
            beats = self.hrv_beats.get(s.name)
            if beats is None:
                continue
            results, adjusted = hrv.analyse(s, rec.epoch_start, windows, trim, beats=beats)
            if series is None:                       # the plots show the first ECG
                series = hrv.time_series(adjusted, rec.epoch_start, self.rmssd_window.value())
            t, v = s.series(hrv.LEAD_II)
            self.plots.set_beats(f"{s.name}: {hrv.LEAD_II}", adjusted.unix - rec.epoch_start,
                                 self._beat_heights(t, v, adjusted.unix), adjusted.ok)
            rows += [(f"{s.name}: {r.label}" if several else r.label, r) for r in results]
            beats_total += results[0].beats
            untrusted += int((np.isfinite(adjusted.rr) & ~adjusted.ok).sum())
        self.hrv_table.setRowCount(len(rows))
        for i, (label, r) in enumerate(rows):
            for j, (_, field, fmt) in enumerate(HRV_COLUMNS):
                value = label if field == "label" else getattr(r, field)
                text = value if field == "label" else ("–" if not np.isfinite(value) else fmt.format(value))
                item = QTableWidgetItem((text + " *") if j == 0 and r.notes else text)
                item.setData(Qt.UserRole, r.notes)
                if j:
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.hrv_table.setItem(i, j, item)
        self.hrv_table.show()
        self.hrv_status.setText(f"{beats_total} beats; {untrusted} intervals not trusted (red crosses on the ECG plot). "
                                "The table follows the export range, and goes into the package. * = a note: select "
                                "the row.")
        self.hrv_status.show()
        self._hrv_row_selected()
        self._update_hrv_controls()
        before = [spec[0] for spec in self._hrv_specs()]
        self.hrv_series = series
        self.hrv_bar.setVisible(series is not None)
        specs = self._hrv_specs()
        if [spec[0] for spec in specs] == before and all(
                self.plots.update_series(s[0], s[1], s[2], s[3].get("weak")) for s in specs):
            return                                   # the same plots with new data: they are not built again
        self._show_sensors()

    def _hrv_specs(self) -> list:
        """The plots of the heart rate and of the moving RMSSD that are switched on, as specs for the sensor plots (after
        the signals chosen in the list, which have their own limit)."""
        series = self.hrv_series
        if series is None:
            return []
        specs = []
        if self.hr_check.isChecked() and len(series.hr):
            specs.append(("Heart rate (bpm)", series.hr_time, series.hr, {"colour": (190, 70, 60), "axis": "HR (bpm)"}))
        if self.rmssd_check.isChecked() and len(series.rmssd):
            weak = series.weak & np.isfinite(series.rmssd)
            specs.append((f"RMSSD (ms), moving {series.window:g} s window", series.rmssd_time, series.rmssd,
                          {"colour": (50, 130, 90), "axis": "RMSSD (ms)", "weak": (series.rmssd_time[weak], series.rmssd[weak])}))
        return specs

    def _hrv_plots_changed(self, *_) -> None:
        """A checkbox or the window of the moving RMSSD changed: the plots under ΔPD are built again."""
        if self.hrv_series is None:
            return
        if abs(self.hrv_series.window - self.rmssd_window.value()) > 1e-9:
            self._refresh_hrv()                      # a new window: the series, and the plots if their titles changed
        else:
            self._show_sensors()

    @staticmethod
    def _beat_heights(t: np.ndarray, v: np.ndarray, beats: np.ndarray) -> np.ndarray:
        """Where to put the marker of each beat on the ECG plot: the sample of the ECG furthest from its median within
        three samples of the beat (a beat is refined below one sample, and the R wave is a few samples wide)."""
        if not len(beats) or not len(t):
            return np.zeros(len(beats))
        centre = np.nanmedian(v)
        index = np.clip(np.searchsorted(t, beats), 0, len(t) - 1)
        offsets = np.arange(-3, 4)
        window = np.clip(index[:, None] + offsets[None, :], 0, len(t) - 1)
        values = v[window]
        return values[np.arange(len(beats)), np.nanargmax(np.abs(values - centre), axis=1)]

    def _hrv_row_selected(self) -> None:
        """Show the notes of the selected window of the HRV table (why a measure is rough or missing)."""
        rows = self.hrv_table.selectionModel().selectedRows() if self.hrv_table.isVisible() else []
        notes = self.hrv_table.item(rows[0].row(), 0).data(Qt.UserRole) if rows else None
        self.hrv_notes.setText("<br>".join(f"<span style='color:{palette.WARNING}'>{n}</span>" for n in notes)
                               if notes else "")
        self.hrv_notes.setVisible(bool(notes))

    @staticmethod
    def _ecg_notes(sensor) -> list[str]:
        """What is wrong with a Shimmer's ECG for HRV, from its sampling rate (the cheap check, no beat detection)."""
        device = sensor.data[hrv.DEVICE_TIME]
        if len(device) < 3 or device[-1] <= device[0]:
            return []
        rate = (len(device) - 1) / (device[-1] - device[0])
        if rate < hrv.MIN_RATE:
            return [f"ECG sampled at {rate:.0f} Hz: too coarse for heart rate variability (256 Hz or more is needed)"]
        return []

    def _show_sensors(self, *_) -> None:
        self._rebuild_signal_menu()
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
        self.plots.set_sensors(specs + self._hrv_specs())

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
        if self.hrv_beats:
            self._hrv_timer.start()

    def _trim_dragged(self, trim: Trim) -> None:
        """The user dragged the export range on the plots."""
        self.trim_panel.set_trim(trim, quiet=True)
        self._trim_save_timer.start()
        if self.hrv_beats:
            self._hrv_timer.start()

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
        """Ask for a folder and export the results (trimmed as set in the Export tab) with the sensor data and the
        manifest.
        """
        if self.result is None:
            return
        default = str(self.recording.folder / "cwtool_export")
        folder = QFileDialog.getExistingDirectory(self, "Export to folder", default)
        if not folder:
            return
        trim = self.trim_panel.trim()
        result, rec, params = self.result, self.recording, self.params_panel.params()
        sensors_, use_hrv, beats = list(self.sensors), bool(self.hrv_beats), dict(self.hrv_beats)
        self.export_result.hide()

        def work(progress, cancelled):
            return pipeline.export(result, rec, params, Path(folder), trim=trim, sensors=sensors_, hrv=use_hrv,
                                   hrv_beats=beats, progress=progress)

        self._export_trim = trim
        self._start_task(work, lambda paths: self._exported(paths, Path(folder), trim), "Exporting…",
                         show_progress=True, bar=self.export_progress)

    def _exported(self, paths: list, folder: Path, trim) -> None:
        """The files are written: add the PDF plot (drawn here, matplotlib is not for other threads) and say where."""
        try:
            from cwtool.plot import plot_result
            p = folder / f"{self.recording.name}_plot.pdf"
            plot_result(self.result, self.recording, trim).savefig(p, bbox_inches="tight")
            paths = list(paths) + [p]
        except ImportError:
            pass
        extra = ""
        if self.sensors:
            extra += f", {len(self.sensors)} sensor file{'s' if len(self.sensors) != 1 else ''}"
        if trim.active:
            extra += ", trimmed"
        self.statusBar().showMessage(f"Exported {len(paths)} files{extra} to {folder}", 6000)
        # the Export tab keeps what the status bar shows for a few seconds
        self.export_result.setText(f"Last export: {len(paths)} files{extra}<br>"
                                   f"<a href='{QUrl.fromLocalFile(str(folder)).toString()}'>{folder}</a>")
        self.export_result.show()

    def closeEvent(self, event) -> None:
        """Offer to save changed parameters, stop the running task and save the layout before closing."""
        if not self._confirm_params("closing"):
            event.ignore()
            return
        if self._task is not None and self._task.isRunning():
            self._task.cancel()
            self._task.wait(5000)
        self._save_layout()
        super().closeEvent(event)
