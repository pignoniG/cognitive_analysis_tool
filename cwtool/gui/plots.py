"""Measured vs expected pupil and ΔPD plots, with calibration and event overlays."""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Signal

from cwtool import calibration
from cwtool.pipeline import Result

pg.setConfigOptions(background="w", foreground="k", antialias=True)


class ResultPlots(pg.GraphicsLayoutWidget):
    """Two stacked plots sharing the time axis. The calibration sequence start
    is a draggable vertical line on the pupil plot."""

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
        self.pupil.setLabel("left", "Pupil diameter (mm)")
        self.cw.setLabel("left", "ΔPD (mm)")
        self.cw.setLabel("bottom", "Time (s)")
        self.pupil.addLegend(offset=(-10, 10))

        self.raw_curve = self.pupil.plot(pen=pg.mkPen((160, 160, 160), width=1), name="Measured (raw)")
        self.measured_curve = self.pupil.plot(pen=pg.mkPen("k", width=1.5), name="Measured")
        self.expected_curve = self.pupil.plot(pen=pg.mkPen((31, 119, 180), width=1.5), name="Expected")
        dash = pg.mkPen((31, 119, 180), width=1, style=pg.QtCore.Qt.DashLine)
        self.black_line = pg.InfiniteLine(angle=0, pen=dash, label="black point",
                                          labelOpts={"position": 0.08, "color": (31, 119, 180)})
        self.white_line = pg.InfiniteLine(angle=0, pen=dash, label="white point",
                                          labelOpts={"position": 0.08, "color": (31, 119, 180)})
        self.pupil.addItem(self.black_line)
        self.pupil.addItem(self.white_line)

        self.cw_curve = self.cw.plot(pen=pg.mkPen((214, 39, 40), width=1.5))
        self.cw.addItem(pg.InfiniteLine(angle=0, pos=0, pen=pg.mkPen((120, 120, 120), width=1)))

        self._event_items: list = []
        self._sequence_items: list = []
        self.sequence_line = pg.InfiniteLine(angle=90, movable=True,
                                             pen=pg.mkPen((90, 90, 90), width=2),
                                             label="calibration start",
                                             labelOpts={"position": 0.95, "color": (60, 60, 60)})
        self.sequence_line.sigPositionChanged.connect(self._line_moved)
        self._sequence_start = 0.0
        self._sequence_visible = False

        # Preview cursor: click on either plot to place it, or drag it.
        cursor_pen = pg.mkPen((214, 39, 40), width=1, style=pg.QtCore.Qt.DotLine)
        self.cursors = [pg.InfiniteLine(angle=90, movable=True, pen=cursor_pen) for _ in range(2)]
        for plot, line in zip((self.pupil, self.cw), self.cursors):
            plot.addItem(line)
            line.sigPositionChanged.connect(self._cursor_dragged)
        self.scene().sigMouseClicked.connect(self._clicked)

    def set_cursor(self, t: float) -> None:
        for line in self.cursors:
            line.blockSignals(True)
            line.setValue(t)
            line.blockSignals(False)

    def _cursor_dragged(self, line) -> None:
        t = float(line.value())
        self.set_cursor(t)
        self.cursor_changed.emit(t)

    def _clicked(self, event) -> None:
        if event.button() != pg.QtCore.Qt.LeftButton or event.double():
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

    def show_result(self, r: Result) -> None:
        self.raw_curve.setData(r.time, r.measured_raw)
        self.measured_curve.setData(r.time, r.measured)
        self.expected_curve.setData(r.time, r.expected)
        self.cw_curve.setData(r.cw_time, r.cw)
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
                plot.addItem(region)
                self._event_items.append((plot, region))
            label = pg.TextItem(e.label, color=(180, 100, 0), anchor=(0, 0))
            label.setPos(e.start, 0)
            self.cw.addItem(label)
            self._event_items.append((self.cw, label))

    # Calibration sequence overlay

    def set_sequence(self, visible: bool, start: float) -> None:
        self._sequence_visible = visible
        self._sequence_start = start
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
        for step in calibration.SEQUENCE:
            region = pg.LinearRegionItem((s + step.start, s + step.start + calibration.STEP_SECONDS),
                                         movable=False, brush=pg.mkBrush(*step.rgb, 70),
                                         pen=pg.mkPen((200, 200, 200)))
            region.setZValue(-10)
            region.setToolTip(step.label)
            self.pupil.addItem(region)
            self._sequence_items.append(region)
        self.sequence_line.blockSignals(True)
        self.sequence_line.setValue(s)
        self.sequence_line.blockSignals(False)
        self.pupil.addItem(self.sequence_line)

    def _line_moved(self) -> None:
        self._sequence_start = float(self.sequence_line.value())
        # Move the regions without rebuilding them while dragging.
        for region, step in zip(self._sequence_items, calibration.SEQUENCE):
            a = self._sequence_start + step.start
            region.setRegion((a, a + calibration.STEP_SECONDS))
        self.sequence_start_changed.emit(self._sequence_start)


def rms_in(result: Result, start: float, end: float) -> float:
    sel = (result.cw_time >= start) & (result.cw_time <= end)
    if not sel.any():
        return float("nan")
    d = result.cw[sel]
    return float(np.sqrt(np.mean((d - d.mean()) ** 2)))
