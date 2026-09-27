"""Result window of the light response fit: steady-state pupil per step, measured vs model."""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QVBoxLayout

from cwtool.gui import plots  # noqa: F401  (the app's white plot style)
from cwtool.photometry import PhotometryFit


class PhotometryDialog(QDialog):
    def __init__(self, fit: PhotometryFit, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Participant light response")
        self.resize(760, 560)
        layout = QVBoxLayout(self)

        g = fit.gains
        lo, hi = fit.sensitivity_range
        notes = "".join(f"<br><span style='color:#c00'>⚠ {n}</span>" for n in fit.notes)
        summary = QLabel(
            f"<b>Steady-state RMS: {fit.rms_before:.3f} → {fit.rms_after:.3f} mm</b><br>"
            f"light sensitivity ×{fit.sensitivity:.3g} (95 % {lo:.3g}–{hi:.3g}) &nbsp; "
            f"channel weights R {g[0]:.2f}, G {g[1]:.2f}, B {g[2]:.2f} &nbsp; gamma {fit.gamma:.2f}<br>"
            f"pupil scale correction {fit.pupil_correction:.3f}, offset {fit.pupil_offset:+.3f} mm{notes}")
        summary.setWordWrap(True)
        layout.addWidget(summary)

        plot = pg.PlotWidget()
        plot.showGrid(x=True, y=True, alpha=0.2)
        plot.setLabel("left", "Steady-state pupil (mm)")
        plot.setLabel("bottom", "Calibration step")
        for side in ("left", "bottom"):
            plot.getAxis(side).enableAutoSIPrefix(False)
        plot.addLegend(offset=(-10, 10), brush=pg.mkBrush(255, 255, 255, 210))
        x = np.arange(len(fit.steps))
        plot.getAxis("bottom").setTicks([[(i, s.label) for i, s in enumerate(fit.steps)][::2],
                                         [(i, s.label) for i, s in enumerate(fit.steps)]])
        offset = float(np.mean(fit.measured_after - fit.expected_before))
        plot.plot(x, fit.expected_before + offset, pen=pg.mkPen((150, 150, 150), width=1.5,
                                                               style=pg.QtCore.Qt.DashLine), name="Model, before")
        plot.plot(x, fit.expected_after, pen=pg.mkPen((31, 119, 180), width=2), name="Model, fitted")
        brushes = [pg.mkBrush(*s.rgb) for s in fit.steps]
        pens = [pg.mkPen("k", width=1.5 if s.settled else 1, style=pg.QtCore.Qt.SolidLine if s.settled
                         else pg.QtCore.Qt.DotLine) for s in fit.steps]
        plot.addItem(pg.ScatterPlotItem(x, fit.measured_after, size=12, brush=brushes, pen=pens, name="Measured"))
        plot.addItem(pg.ErrorBarItem(x=x, y=fit.measured_after, height=2 * fit.uncertainty_after,
                                     pen=pg.mkPen((90, 90, 90))))
        layout.addWidget(plot, 1)

        hint = QLabel("Markers show the measured steady state of each step in its colour (dotted outline: "
                      "the pupil had not settled, value extrapolated). Apply sets the sensitivity, channel "
                      "weights, scale and offset; then fit latency, scale and offset.")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        buttons = QDialogButtonBox(QDialogButtonBox.Apply | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Apply).clicked.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
