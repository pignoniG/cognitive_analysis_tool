"""Editable form for :class:`Parameters` and :class:`VideoSettings`."""

from __future__ import annotations

from dataclasses import fields, replace

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QGroupBox, QLabel,
                               QLineEdit, QSizePolicy, QSpinBox, QToolButton, QVBoxLayout, QWidget)

from cwtool.params import Parameters, VideoSettings, unused_parameters

# name: (label, min, max, step, decimals, tooltip)
NUMBERS = {
    "age": ("Age (years)", 1, 120, 1, 0, "Participant age"),
    "l_min": ("Lmin (cd/m²)", 0, 1000, 0.1, 3, "Panel black point"),
    "l_max": ("Lmax (cd/m²)", 0.1, 100000, 50, 1, "Panel white point"),
    "sensitivity": ("Light sensitivity (×)", 0.001, 1000, 0.1, 3,
                    "Participant factor on the luminance entering the pupil model; it also absorbs any "
                    "common error of the display photometry. Fitted on the calibration sequence"),
    "gain_r": ("Red weight", 0, 100, 0.1, 2, "Relative weight of the red channel for the pupil"),
    "gain_g": ("Green weight", 0, 100, 0.1, 2, "Relative weight of the green channel for the pupil"),
    "gain_b": ("Blue weight", 0, 100, 0.1, 2, "Relative weight of the blue channel for the pupil"),
    "gamma": ("Gamma", 1.4, 3.0, 0.1, 2, "Display gamma: code values are decoded as (C/255)^γ"),
    "fixation_weight": ("Fixation weight", 0, 1, 0.05, 2, "Weight of the gaze area; the background gets the rest"),
    "pupil_offset": ("Pupil offset (mm)", -10, 10, 0.01, 3, "Offset used by alignment 'fixed' (set by the calibration fit)"),
    "pupil_correction": ("Pupil scale correction", 0.1, 10, 0.01, 3,
                         "Participant multiplier on the device's pupil scale (1 = device default)"),
    "timelag": ("Time lag (s)", -60, 60, 0.05, 2, "Shift of the luminance signal"),
    "delay": ("Delay (s)", 0, 5, 0.05, 2, "Pupil response latency"),
    "attack": ("Dilation τ (s)", 0.01, 60, 0.5, 2, "Attack time constant"),
    "release": ("Constriction τ (s)", 0.01, 60, 0.1, 2, "Release time constant"),
    "transient": ("Transient (mm)", 0, 5, 0.05, 2,
                  "Largest constriction beyond the steady state after a brightening step, which then "
                  "re-dilates (pupillary escape); 0 = off. Fitted on the calibration sequence"),
    "escape": ("Escape τ (s)", 0.1, 60, 0.5, 2, "Re-dilation time constant of the transient"),
    "analysis_rate": ("Analysis rate (Hz)", 0, 1000, 10, 0, "Uniform resampling rate; 0 uses the device's native rate"),
    "max_gap": ("Max gap (s)", 0, 60, 0.1, 2, "Gaps longer than this are excluded from ΔPD; shorter ones are interpolated"),
    "max_pupil_speed": ("Max pupil speed (mm/s)", 0, 200, 1, 1,
                        "Faster changes are treated as artefacts (blink edges); 0 disables the filter"),
    "artefact_padding": ("Artefact padding (s)", 0, 1, 0.01, 2, "Removed on each side of an artefact"),
    "lux_gain": ("Lux gain", 0, 100, 0.01, 6,
                 "Recalibration of the sensor's lux (1 = as reported): average luminance = (gain·lux + offset) / "
                 "field factor. 1.x used 1.706061"),
    "lux_offset": ("Lux offset", -1000, 1000, 0.01, 5, "Recalibration offset in lux (1.x used 0.66935)"),
    "lux_solid_angle": ("Sensor field factor", 0.01, 12.6, 0.1, 3,
                        "Illuminance / average luminance for the sensor in its housing: the sensor's angular "
                        "response integrated over its field (2.2 for the TSL2591 kit; π for a bare cosine sensor)"),
    "camera_white": ("Camera full scale (cd/m²)", 0.1, 1e7, 50, 1,
                     "Luminance that saturates the scene camera (code 255) at the reference exposure; "
                     "set it with 'Calibrate camera from lux' on a recording made with the same exposure"),
    "camera_reference_ms": ("Reference exposure (ms)", 0, 10000, 1, 2,
                            "Exposure time the full-scale value was calibrated at; 0 = same as the recording"),
    "camera_exposure_ms": ("Recording exposure (ms)", 0, 10000, 1, 2,
                           "This recording's exposure time; the full scale is scaled by reference / recording. "
                           "0 = same as the reference"),
    "cw_window": ("ΔPD window (s)", 0.01, 10, 0.05, 2, "Averaging window for ΔPD"),
    "field_radius": ("Scene circle radius", 0.05, 1, 0.05, 2, "Fraction of half the frame height (circular videos)"),
    "fixation_radius_deg": ("Gaze circle radius (°)", 0.5, 60, 0.25, 2,
                            "Radius of the gaze circle in degrees of visual angle"),
}
INTS = {
    "cw_smoothing": ("ΔPD smoothing", 1, 100, "Savitzky-Golay half-window, in ΔPD windows"),
    "analysis_width": ("Analysis width (px)", 100, 4000, "Frames are downscaled to this width"),
}
BOOLS = {
    "dynamics": "Dynamics on (time constants, constriction stages, transient)",
    "background_excludes_fixation": "Background excludes gaze area",
    "lux_use_video": "Distribute sensor luminance with the scene video",
}
CHOICES = {
    "eye": ("Pupil", ["both", "left", "right"]),
    "eyes": ("Eyes viewing", [2, 1]),
    "constriction_stages": ("Constriction stages", [1, 2]),
    "alignment": ("Alignment", ["recording", "baseline", "fixed", "none"]),
    "camera_exposure": ("Camera exposure", ["auto", "fixed"]),
}
TEXTS = {
    "baseline_events": ("Baseline events", "Comma-separated event labels used by alignment 'baseline'"),
}

GROUPS = [
    ("Participant", ["age", "eyes", "eye"]),
    ("Display photometry (datasheet)", ["l_min", "l_max", "gamma"]),
    ("Participant light response", ["sensitivity", "gain_r", "gain_g", "gain_b", "fixation_weight"]),
    ("Pupil signal", ["pupil_correction", "alignment", "baseline_events", "pupil_offset",
                      "timelag", "analysis_rate", "max_gap", "max_pupil_speed", "artefact_padding"]),
    ("Lux sensor (Pupil devices)", ["lux_gain", "lux_offset", "lux_solid_angle", "lux_use_video"]),
    ("Scene camera without lux log (Pupil devices)",
     ["camera_exposure", "camera_white", "camera_reference_ms", "camera_exposure_ms"]),
    ("ΔPD", ["cw_window", "cw_smoothing"]),
]
# Shown in drop-down sections next to the controls they belong to (see ParameterPanel).
DYNAMICS_GROUP = (None, ["delay", "dynamics", "attack", "release", "constriction_stages", "transient", "escape"])
DYNAMICS_SWITCHED = ("attack", "release", "constriction_stages", "transient", "escape")
VIDEO_GROUP = (None, ["fixation_radius_deg", "field_radius", "background_excludes_fixation", "analysis_width"])


class Collapsible(QWidget):
    """A header button that shows or hides its content (collapsed by default)."""

    def __init__(self, title: str, content: QWidget, parent=None):
        super().__init__(parent)
        self.header = QToolButton()
        self.header.setText(title)
        self.header.setCheckable(True)
        self.header.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.header.setArrowType(Qt.RightArrow)
        self.header.setStyleSheet("QToolButton { border: none; font-weight: bold; padding: 2px 0; }")
        self.header.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.header.toggled.connect(self.set_expanded)
        self.content = content
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.addWidget(self.header)
        layout.addWidget(content)
        content.setVisible(False)

    def set_expanded(self, expanded: bool) -> None:
        self.header.blockSignals(True)
        self.header.setChecked(expanded)
        self.header.blockSignals(False)
        self.header.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
        self.content.setVisible(expanded)

    def is_expanded(self) -> bool:
        return self.header.isChecked()


class _Form(QWidget):
    """Builds editors for the named fields of a dataclass instance."""

    changed = Signal()

    def __init__(self, groups, value, parent=None):
        super().__init__(parent)
        self._value = value
        self._editors = {}
        self._boxes = []   # (group box, its form layout, field names)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        for title, names in groups:
            box = QGroupBox(title) if title else QWidget()    # untitled: inside a drop-down section
            form = QFormLayout(box)
            if not title:
                form.setContentsMargins(0, 0, 0, 0)
            for name in names:
                editor, label = self._make(name)
                self._editors[name] = editor
                if label is None:
                    form.addRow(editor)
                else:
                    form.addRow(label, editor)
            layout.addWidget(box)
            self._boxes.append((box, form, names))
        self.set_value(value)

    def hide_fields(self, hidden: set[str]) -> None:
        """Hide the rows of ``hidden`` fields, and groups left empty. Hidden fields keep their values."""
        for box, form, names in self._boxes:
            for name in names:
                form.setRowVisible(self._editors[name], name not in hidden)
            box.setVisible(any(name not in hidden for name in names))

    def is_shown(self, name: str) -> bool:
        box = next(b for b, _, names in self._boxes if name in names)
        return not box.isHidden() and not self._editors[name].isHidden()

    def updates(self) -> dict:
        return {name: getattr(self.value(), name) for name in self._editors}

    def _make(self, name):
        if name in NUMBERS:
            label, lo, hi, step, dec, tip = NUMBERS[name]
            w = QDoubleSpinBox()
            w.setRange(lo, hi)
            w.setSingleStep(step)
            w.setDecimals(dec)
            w.setKeyboardTracking(False)
            w.setToolTip(tip)
            w.valueChanged.connect(self.changed)
            return w, label
        if name in INTS:
            label, lo, hi, tip = INTS[name]
            w = QSpinBox()
            w.setRange(lo, hi)
            w.setKeyboardTracking(False)
            w.setToolTip(tip)
            w.valueChanged.connect(self.changed)
            return w, label
        if name in TEXTS:
            label, tip = TEXTS[name]
            w = QLineEdit()
            w.setToolTip(tip)
            w.editingFinished.connect(self.changed)
            return w, label
        if name in BOOLS:
            w = QCheckBox(BOOLS[name])
            w.toggled.connect(self.changed)
            return w, None
        label, options = CHOICES[name]
        w = QComboBox()
        for o in options:
            w.addItem(str(o), o)
        w.currentIndexChanged.connect(self.changed)
        return w, label

    def set_value(self, value) -> None:
        self._value = value
        for name, w in self._editors.items():
            v = getattr(value, name)
            w.blockSignals(True)
            if isinstance(w, QLineEdit):
                w.setText(str(v))
            elif isinstance(w, QCheckBox):
                w.setChecked(bool(v))
            elif isinstance(w, QComboBox):
                w.setCurrentIndex(max(w.findData(v), 0))
            else:
                w.setValue(v)
            w.blockSignals(False)

    def value(self):
        updates = {}
        for name, w in self._editors.items():
            if isinstance(w, QLineEdit):
                updates[name] = w.text()
            elif isinstance(w, QCheckBox):
                updates[name] = w.isChecked()
            elif isinstance(w, QComboBox):
                updates[name] = w.currentData()
            else:
                updates[name] = w.value()
        return replace(self._value, **updates)


class ParameterPanel(QWidget):
    """All editable settings. Most are laid out in the panel itself; the video analysis settings
    and the dynamics are drop-down sections (``video_section``, ``dynamics_section``) that the
    window places next to the controls they belong to."""

    params_changed = Signal()
    video_settings_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._params = _Form(GROUPS, Parameters())
        self._dynamics = _Form([DYNAMICS_GROUP], Parameters())
        self._video = _Form([VIDEO_GROUP], VideoSettings())
        self._recording = None
        for form in (self._params, self._dynamics):
            form.changed.connect(self._update_visible)
            form.changed.connect(self.params_changed)
        self._video.changed.connect(self.video_settings_changed)
        layout.addWidget(self._params)
        layout.addStretch(1)

        video = QWidget()
        video_layout = QVBoxLayout(video)
        video_layout.setContentsMargins(0, 0, 0, 0)
        note = QLabel("Reanalyse the video to apply changes; the preview shows them at once.")
        note.setWordWrap(True)
        note.setStyleSheet("font-style: italic;")
        video_layout.addWidget(self._video)
        video_layout.addWidget(note)
        self.video_section = Collapsible("Video analysis settings", video)
        self.dynamics_section = Collapsible("Dynamics", self._dynamics)
        covered = {n for _, names in GROUPS + [DYNAMICS_GROUP] for n in names}
        missing = {f.name for f in fields(Parameters)} - covered - {"version"}
        assert not missing, f"Parameters without an editor: {missing}"

    def params(self) -> Parameters:
        return replace(self._params.value(), **self._dynamics.updates())

    def set_params(self, p: Parameters) -> None:
        self._params.set_value(p)
        self._dynamics.set_value(p)
        self._update_visible()
        self.params_changed.emit()

    def set_recording(self, rec) -> None:
        """Show only the options that affect ``rec`` (all of them when None)."""
        self._recording = rec
        self._update_visible()

    def is_shown(self, name: str) -> bool:
        """Whether the option applies to the loaded recording (a collapsed section counts as shown)."""
        form = next(f for f in (self._video, self._dynamics, self._params) if name in f._editors)
        return form.is_shown(name)

    def _update_visible(self) -> None:
        params = self.params()
        hidden = unused_parameters(self._recording, params)
        for form in (self._params, self._dynamics, self._video):
            form.hide_fields(hidden)
        # One switch: the dynamics settings apply only with it on (the delay always applies).
        for name in DYNAMICS_SWITCHED:
            self._dynamics._editors[name].setEnabled(params.dynamics)

    def video_settings(self) -> VideoSettings:
        return self._video.value()

    def set_video_settings(self, s: VideoSettings) -> None:
        self._video.set_value(s)
