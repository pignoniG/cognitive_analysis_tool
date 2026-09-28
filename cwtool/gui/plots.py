"""Measured vs expected pupil and ΔPD plots, with calibration and event overlays."""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QToolButton

from cwtool import calibration
from cwtool.pipeline import Result, residual_rms

pg.setConfigOptions(background="w", foreground="k", antialias=True)


class ResultPlots(pg.GraphicsLayoutWidget):
    """Two stacked plots sharing the time axis. The calibration sequence start
    is a draggable vertical line on the pupil plot.

    The view follows the data (:meth:`fit_to_data`) until the user pans or zooms; after
    that it stays put until :meth:`fit_to_data` is called again (double-click, or the
    Reset view button in the top right corner). Overlays never enter the fitted range."""

    sequence_start_changed = Signal(float)
    cursor_changed = Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pupil = self.addPlot(row=0, col=0)
        self.cw = self.addPlot(row=1, col=0)
        self.ci.layout.setRowStretchFactor(0, 3)
        self.ci.layout.setRowStretchFactor(1, 2)
        self.cw.setXLink(self.pupil)
        for p in (self.pupil, self.cw):
            p.showGrid(x=True, y=True, alpha=0.2)
            p.setClipToView(True)
            p.setDownsampling(auto=True, mode="peak")
            for side in ("left", "bottom"):
                p.getAxis(side).enableAutoSIPrefix(False)  # keep values in mm and s
        self._follow = True
        self._data = (None, None, None)    # time, pupil values, ΔPD values the view is fitted to
        for p in (self.pupil, self.cw):
            p.vb.sigRangeChangedManually.connect(self._moved_by_user)
            p.hideButtons()   # pyqtgraph's own auto-range button would include the overlays
        self.pupil.setLabel("left", "Pupil diameter (mm)")
        self.cw.setLabel("left", "ΔPD (mm)")
        self.cw.setLabel("bottom", "Time (s)")
        self.pupil.addLegend(offset=(-10, 44), brush=pg.mkBrush(255, 255, 255, 210))   # below Reset view

        self.reset_button = QToolButton(self)
        self.reset_button.setText("Reset view")
        self.reset_button.setToolTip("Show all the data again (Ctrl+0, or double-click the plots)")
        self.reset_button.setStyleSheet(
            "QToolButton { font-size: 13px; padding: 5px 12px; border: 1px solid #999; border-radius: 5px;"
            " background: rgba(255, 255, 255, 230); color: #222; }"
            "QToolButton:hover { background: #eef3fa; }")
        self.reset_button.clicked.connect(self.fit_to_data)

        self.raw_curve = self.pupil.plot(pen=pg.mkPen((160, 160, 160), width=1), name="Measured (raw)", connect="finite")
        self.measured_curve = self.pupil.plot(pen=pg.mkPen("k", width=1.5), name="Measured", connect="finite")
        self.expected_curve = self.pupil.plot(pen=pg.mkPen((31, 119, 180), width=1.5), name="Expected")
        dash = pg.mkPen((31, 119, 180), width=1, style=pg.QtCore.Qt.DashLine)
        self.black_line = pg.InfiniteLine(angle=0, pen=dash, label="black point",
                                          labelOpts={"position": 0.08, "color": (31, 119, 180)})
        self.white_line = pg.InfiniteLine(angle=0, pen=dash, label="white point",
                                          labelOpts={"position": 0.08, "color": (31, 119, 180)})
        self.pupil.addItem(self.black_line, ignoreBounds=True)
        self.pupil.addItem(self.white_line, ignoreBounds=True)

        self.cw_curve = self.cw.plot(pen=pg.mkPen((214, 39, 40), width=1.5), connect="finite")
        self.cw.addItem(pg.InfiniteLine(angle=0, pos=0, pen=pg.mkPen((120, 120, 120), width=1)), ignoreBounds=True)

        self._event_items: list = []
        self._sequence_items: list = []
        self.sequence_line = pg.InfiniteLine(angle=90, movable=True,
                                             pen=pg.mkPen((90, 90, 90), width=2),
                                             label="calibration start",
                                             labelOpts={"position": 0.95, "color": (60, 60, 60)})
        self.sequence_line.sigPositionChanged.connect(self._line_moved)
        self._sequence_start = 0.0
        self._sequence_visible = False
        self._sequence = calibration.DEFAULT

        # Current frame: a red bar on both plots. Click on either plot to place it, or drag it to scrub
        # the video; the time is shown at the top of the pupil plot.
        red = (214, 39, 40)
        self._moving_cursor = False
        self.cursors = [pg.InfiniteLine(angle=90, movable=True, pen=pg.mkPen(red, width=2),
                                        hoverPen=pg.mkPen(red, width=4)) for _ in range(2)]
        self.cursors[0].label = pg.InfLineLabel(self.cursors[0], text="{value:.2f} s", position=0.97,
                                                anchors=[(0, 0), (0, 0)], color=red,
                                                fill=pg.mkBrush(255, 255, 255, 200))
        for plot, line in zip((self.pupil, self.cw), self.cursors):
            line.setZValue(20)                  # above the curves and overlays, so it can always be grabbed
            line.setCursor(pg.QtCore.Qt.SizeHorCursor)
            plot.addItem(line, ignoreBounds=True)
            line.sigPositionChanged.connect(self._cursor_dragged)
        self.scene().sigMouseClicked.connect(self._clicked)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if not hasattr(self, "reset_button"):     # resized while the base class is being built
            return
        self.reset_button.adjustSize()
        self.reset_button.move(self.width() - self.reset_button.width() - 12, 8)

    def set_cursor(self, t: float) -> None:
        """Move the bar without reporting it (the caller already knows the time)."""
        self._moving_cursor = True
        try:
            for line in self.cursors:
                line.setValue(t)
        finally:
            self._moving_cursor = False

    def _cursor_dragged(self, line) -> None:
        if self._moving_cursor:
            return
        t = float(line.value())
        self.set_cursor(t)
        self.cursor_changed.emit(t)

    def _clicked(self, event) -> None:
        if event.button() != pg.QtCore.Qt.LeftButton:
            return
        if event.double():
            self.fit_to_data()
            return
        for plot in (self.pupil, self.cw):
            if plot.sceneBoundingRect().contains(event.scenePos()):
                t = float(plot.vb.mapSceneToView(event.scenePos()).x())
                self.set_cursor(t)
                self.cursor_changed.emit(t)
                return

    def clear_result(self) -> None:
        for c in (self.raw_curve, self.measured_curve, self.expected_curve, self.cw_curve):
            c.setData([], [])
        self._follow = True   # the next result (a new recording) is fitted

    def _moved_by_user(self, *_) -> None:
        self._follow = False

    def fit_to_data(self) -> None:
        """Show all the data: the time span of the signals and the full range of the smoothed
        measured, expected and ΔPD curves (artefacts are already removed from them; the noisier
        raw curve may extend beyond). The view then follows parameter changes again."""
        self._follow = True
        t, pupil, cw = self._data
        if t is None:
            return
        finite_t = t[np.isfinite(t)]
        if len(finite_t):
            self.pupil.setXRange(float(finite_t[0]), float(finite_t[-1]), padding=0.02)
        for plot, values in ((self.pupil, pupil), (self.cw, cw)):
            lo, hi = data_range(values)
            if lo is not None:
                plot.setYRange(lo, hi, padding=0.08)

    def show_result(self, r: Result) -> None:
        self.raw_curve.setData(r.time, r.measured_raw)
        self.measured_curve.setData(r.time, r.measured)
        self.expected_curve.setData(r.time, r.expected)
        self.cw_curve.setData(r.cw_time, r.cw)
        self._data = (np.asarray(r.time), np.concatenate([r.measured, r.expected]), np.asarray(r.cw))
        if self._follow:
            self.fit_to_data()
        markers = np.isfinite(r.expected_black)   # not defined when luminance comes from a lux sensor
        self.black_line.setVisible(bool(markers))
        self.white_line.setVisible(bool(markers))
        if markers:
            self.black_line.setValue(r.expected_black)
            self.white_line.setValue(r.expected_white)

    def show_events(self, events) -> None:
        for plot, item in self._event_items:
            plot.removeItem(item)
        self._event_items = []
        for e in events:
            for plot in (self.pupil, self.cw):
                region = pg.LinearRegionItem((e.start, e.end), movable=False,
                                             brush=pg.mkBrush(255, 165, 0, 30), pen=pg.mkPen(None))
                region.setZValue(-20)
                plot.addItem(region, ignoreBounds=True)
                self._event_items.append((plot, region))
            label = pg.TextItem(e.label, color=(180, 100, 0), anchor=(0, 0))
            label.setPos(e.start, 0)
            self.cw.addItem(label, ignoreBounds=True)
            self._event_items.append((self.cw, label))

    # Calibration sequence overlay

    def set_sequence(self, visible: bool, start: float, sequence: calibration.Sequence | None = None) -> None:
        self._sequence_visible = visible
        self._sequence_start = start
        if sequence is not None:
            self._sequence = sequence
        self._draw_sequence()

    def _draw_sequence(self) -> None:
        for item in self._sequence_items:
            self.pupil.removeItem(item)
        self._sequence_items = []
        if self.sequence_line.scene() is not None:
            self.pupil.removeItem(self.sequence_line)
        if not self._sequence_visible:
            return
        s = self._sequence_start
        for step in self._sequence.steps:
            region = pg.LinearRegionItem((s + step.start, s + step.end),
                                         movable=False, brush=pg.mkBrush(*step.rgb, 70),
                                         pen=pg.mkPen((200, 200, 200)))
            region.setZValue(-10)
            region.setToolTip(step.label)
            self.pupil.addItem(region, ignoreBounds=True)
            self._sequence_items.append(region)
        self.sequence_line.blockSignals(True)
        self.sequence_line.setValue(s)
        self.sequence_line.blockSignals(False)
        self.pupil.addItem(self.sequence_line, ignoreBounds=True)

    def _line_moved(self) -> None:
        self._sequence_start = float(self.sequence_line.value())
        # Move the regions without rebuilding them while dragging.
        for region, step in zip(self._sequence_items, self._sequence.steps):
            region.setRegion((self._sequence_start + step.start, self._sequence_start + step.end))
        self.sequence_start_changed.emit(self._sequence_start)


def rms_in(result: Result, start: float, end: float) -> float:
    """Residual RMS of ΔPD between ``start`` and ``end``."""
    sel = (result.cw_time >= start) & (result.cw_time <= end)
    return residual_rms(result.cw[sel])


def data_range(values, trim: float = 0.0):
    """(low, high) of the finite values between the ``trim`` and 100 - ``trim`` percentiles,
    or (None, None) without data. A flat signal gets a small range around its value."""
    v = np.asarray(values, dtype=float)
    v = v[np.isfinite(v)]
    if not len(v):
        return None, None
    lo, hi = (float(x) for x in np.percentile(v, [trim, 100 - trim]))
    if hi - lo < 1e-6:
        lo, hi = lo - 0.1, hi + 0.1
    return lo, hi
