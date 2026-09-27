"""Editable form for :class:`Parameters` and :class:`VideoSettings`."""

from __future__ import annotations

from dataclasses import fields, replace

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QGroupBox,
                               QLineEdit, QSpinBox, QVBoxLayout, QWidget)

from cwtool.params import Parameters, VideoSettings

# name: (label, min, max, step, decimals, tooltip)
NUMBERS = {
    "age": ("Age (years)", 1, 120, 1, 0, "Participant age"),
    "reference_age": ("Reference age", 1, 120, 0.1, 2, "Watson & Yellott reference age"),
    "l_min": ("Lmin (cd/m²)", 0, 1000, 0.1, 3, "Panel black point"),
    "l_max": ("Lmax (cd/m²)", 0.1, 100000, 50, 1, "Panel white point"),
    "gain_r": ("Red gain", 0, 100, 0.1, 2, "Relative gain of the red channel"),
    "gain_g": ("Green gain", 0, 100, 0.1, 2, "Relative gain of the green channel"),
    "gain_b": ("Blue gain", 0, 100, 0.1, 2, "Relative gain of the blue channel"),
    "gamma": ("Gamma", 1.4, 3.0, 0.1, 2, "Display gamma: code values are decoded as (C/255)^γ"),
    "fixation_weight": ("Fixation weight", 0, 1, 0.05, 2, "Weight of the gaze area; the background gets the rest"),
    "pupil_offset": ("Pupil offset (mm)", -10, 10, 0.01, 3, "Offset used by alignment 'fixed' (set by the calibration fit)"),
    "pupil_correction": ("Pupil scale correction", 0.1, 10, 0.01, 3,
                         "Participant multiplier on the device's pupil scale (1 = device default)"),
    "timelag": ("Time lag (s)", -60, 60, 0.05, 2, "Shift of the luminance signal"),
    "delay": ("Delay (s)", 0, 5, 0.05, 2, "Pupil response latency"),
    "attack": ("Dilation τ (s)", 0.01, 60, 0.5, 2, "Attack time constant"),
    "release": ("Constriction τ (s)", 0.01, 60, 0.1, 2, "Release time constant"),
    "analysis_rate": ("Analysis rate (Hz)", 0, 1000, 10, 0, "Uniform resampling rate; 0 uses the device's native rate"),
    "max_gap": ("Max gap (s)", 0, 60, 0.1, 2, "Gaps longer than this are excluded from ΔPD; shorter ones are interpolated"),
    "max_pupil_speed": ("Max pupil speed (mm/s)", 0, 200, 1, 1,
                        "Faster changes are treated as artefacts (blink edges); 0 disables the filter"),
    "artefact_padding": ("Artefact padding (s)", 0, 1, 0.01, 2, "Removed on each side of an artefact"),
    "lux_gain": ("Lux gain", 0, 100, 0.01, 6, "Sensor calibration: average luminance = (gain·lux + offset) / solid angle"),
    "lux_offset": ("Lux offset", -1000, 1000, 0.01, 5, "Sensor calibration offset"),
    "lux_solid_angle": ("Sensor solid angle (sr)", 0.01, 12.6, 0.1, 3, "Solid angle seen by the lux sensor"),
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
    "dynamics": "Pupil dynamics (attack/release)",
    "background_excludes_fixation": "Background excludes gaze area",
    "lux_use_video": "Distribute sensor luminance with the scene video",
}
CHOICES = {
    "eye": ("Pupil", ["both", "left", "right"]),
    "eyes": ("Eyes viewing", [2, 1]),
    "alignment": ("Alignment", ["recording", "baseline", "fixed", "none"]),
}
TEXTS = {
    "baseline_events": ("Baseline events", "Comma-separated event labels used by alignment 'baseline'"),
}

GROUPS = [
    ("Participant", ["age", "reference_age", "eyes", "eye"]),
    ("Photometric calibration", ["l_min", "l_max", "gain_r", "gain_g", "gain_b", "gamma", "fixation_weight"]),
    ("Pupil signal", ["pupil_correction", "alignment", "baseline_events", "pupil_offset",
                      "timelag", "analysis_rate", "max_gap", "max_pupil_speed", "artefact_padding"]),
    ("Lux sensor (Pupil devices)", ["lux_gain", "lux_offset", "lux_solid_angle", "lux_use_video"]),
    ("Dynamics", ["delay", "dynamics", "attack", "release"]),
    ("ΔPD", ["cw_window", "cw_smoothing"]),
]
VIDEO_GROUP = ("Video analysis (re-run to apply)",
               ["fixation_radius_deg", "field_radius", "background_excludes_fixation", "analysis_width"])


class _Form(QWidget):
    """Builds editors for the named fields of a dataclass instance."""

    changed = Signal()

    def __init__(self, groups, value, parent=None):
        super().__init__(parent)
        self._value = value
        self._editors = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        for title, names in groups:
            box = QGroupBox(title)
            form = QFormLayout(box)
            for name in names:
                editor, label = self._make(name)
                self._editors[name] = editor
                if label is None:
                    form.addRow(editor)
                else:
                    form.addRow(label, editor)
            layout.addWidget(box)
        self.set_value(value)

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
    params_changed = Signal()
    video_settings_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._params = _Form(GROUPS, Parameters())
        self._video = _Form([VIDEO_GROUP], VideoSettings())
        self._params.changed.connect(self.params_changed)
        self._video.changed.connect(self.video_settings_changed)
        layout.addWidget(self._params)
        layout.addWidget(self._video)
        layout.addStretch(1)
        covered = {n for _, names in GROUPS for n in names}
        missing = {f.name for f in fields(Parameters)} - covered - {"version"}
        assert not missing, f"Parameters without an editor: {missing}"

    def params(self) -> Parameters:
        return self._params.value()

    def set_params(self, p: Parameters) -> None:
        self._params.set_value(p)
        self.params_changed.emit()

    def video_settings(self) -> VideoSettings:
        return self._video.value()

    def set_video_settings(self, s: VideoSettings) -> None:
        self._video.set_value(s)
