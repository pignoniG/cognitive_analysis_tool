"""Measured vs expected pupil and ΔPD plots, with calibration and event overlays."""

from __future__ import annotations

from functools import partial

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QPointF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QToolButton

from cwtool import calibration, palette
from cwtool.gui.icons import pixmap
from cwtool.pipeline import Result, residual_rms
from cwtool.trim import Trim

pg.setConfigOptions(background="w", foreground="k", antialias=True)


class LogAxis(pg.AxisItem):
    """Left axis of the luminance plot, which is logarithmic: ticks and labels at 1, 2 and 5 times a power of ten.
    pyqtgraph's own log ticks (every multiple, 1 to 9) print overlapping labels on a short plot."""

    def tickValues(self, minVal, maxVal, size):   # the range is in log10 units
        """Ticks at every power of ten and at 2 and 5 times it (the axis is in log10 units)."""
        first, last = int(np.floor(minVal)) - 1, int(np.ceil(maxVal)) + 1
        decades = [float(n) for n in range(first, last + 1) if minVal <= n <= maxVal]
        halves = [n + np.log10(k) for n in range(first, last + 1) for k in (2, 5) if minVal <= n + np.log10(k) <= maxVal]
        return [(1.0, decades), (0.5, halves)]

    def tickStrings(self, values, scale, spacing):
        """Tick labels as luminances (the axis holds their logarithm)."""
        return [f"{10 ** v:.3g}" for v in values]


AXIS_WIDTH = 74     # pixels of every plot's left axis (tick labels and label), so that the plot areas line up


class TimeViewBox(pg.ViewBox):
    """View box that moves and zooms along the time axis; the plots fit the value axis to the data.

    Drag with the left button to pan in time (the middle button does too). In *zoom mode* (the Zoom button) the left
    button draws a rectangle instead and zooms to it, in time and in value (:attr:`sigValueZoomed`). A right click zooms
    out; the wheel zooms in time around the pointer, a horizontal scroll pans."""

    sigValueZoomed = Signal(object, float, float)    # this box, the low and high of the value range zoomed to
    sigValueReset = Signal(object)                   # this box: its value axis is fitted to the data again

    ZOOM_OUT = 2.0      # factor of a right click
    MIN_BAND_PX = 4     # a drag shorter than this is a click, not a zoom

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setMouseEnabled(x=True, y=False)
        self.setMenuEnabled(False)
        self.zoom_mode = False
        self.rbScaleBox.setPen(pg.mkPen((90, 90, 90), width=1))          # the zoom rectangle is a neutral gray
        self.rbScaleBox.setBrush(pg.mkBrush(110, 110, 110, 60))

    def set_zoom_mode(self, on: bool) -> None:
        """Left drag draws a rectangle to zoom to (on) or pans (off)."""
        self.zoom_mode = bool(on)
        self.setCursor(Qt.CrossCursor if on else Qt.ArrowCursor)

    def _manual(self) -> None:
        self.sigRangeChangedManually.emit([True, False])

    def mouseDragEvent(self, ev, axis=None) -> None:
        """Left drag: pan, or in zoom mode zoom to the rectangle; middle drag: pan; right drag: nothing."""
        ev.accept()
        button = ev.button()
        if button == Qt.LeftButton and self.zoom_mode:
            if ev.isFinish():
                self.rbScaleBox.hide()
                p0, p1 = ev.buttonDownScenePos(), ev.scenePos()
                if abs(p1.x() - p0.x()) >= self.MIN_BAND_PX and abs(p1.y() - p0.y()) >= self.MIN_BAND_PX:
                    a, b = self.mapSceneToView(p0), self.mapSceneToView(p1)
                    self.setXRange(min(a.x(), b.x()), max(a.x(), b.x()), padding=0)
                    self.sigValueZoomed.emit(self, min(a.y(), b.y()), max(a.y(), b.y()))
                    self._manual()
            else:     # the rectangle is placed in the view box's own coordinates
                self.updateScaleBox(ev.buttonDownPos(), ev.pos())
        elif button in (Qt.LeftButton, Qt.MiddleButton):
            moved = self.mapSceneToView(ev.scenePos()).x() - self.mapSceneToView(ev.lastScenePos()).x()
            self.translateBy(x=-moved)
            self._manual()

    def mouseClickEvent(self, ev) -> None:
        """Right click: zoom out around the pointer, and fit the value axis to the data again."""
        if ev.button() == Qt.RightButton:
            ev.accept()
            self.scaleBy(x=self.ZOOM_OUT, center=self.mapSceneToView(ev.scenePos()))
            self.sigValueReset.emit(self)
            self._manual()
        else:
            super().mouseClickEvent(ev)

    def wheelEvent(self, ev, axis=None) -> None:
        """Wheel: zoom around the pointer; a horizontal scroll (a trackpad swipe) pans."""
        ev.accept()
        if getattr(ev, "orientation", lambda: Qt.Vertical)() == Qt.Horizontal:
            span = self.viewRange()[0]
            self.translateBy(x=-ev.delta() / 1200.0 * (span[1] - span[0]))
        else:
            self.scaleBy(x=1.02 ** (-ev.delta() / 8.0), center=self.mapSceneToView(ev.scenePos()))
        self._manual()


class ResultPlots(pg.GraphicsLayoutWidget):
    """Stacked plots sharing the time axis: pupil, luminance, the video ratio (lux route only) and ΔPD.
    The calibration sequence start is a draggable vertical line on the pupil plot.

    The view follows the data (:meth:`fit_to_data`) until the user pans or zooms; after
    that it stays put until :meth:`fit_to_data` is called again (double-click, or the
    Reset view button in the top right corner). Overlays never enter the fitted range."""

    sequence_start_changed = Signal(float)
    cursor_changed = Signal(float)
    trim_dragged = Signal(object)    # the export range (cwtool.trim.Trim) after the user dragged a line or segment

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pupil = self.addPlot(row=0, col=0, viewBox=TimeViewBox())
        self.lum = self.addPlot(row=1, col=0, viewBox=TimeViewBox(), axisItems={"left": LogAxis("left")})
        self.ratio = self.addPlot(row=2, col=0, viewBox=TimeViewBox())
        self.cw = self.addPlot(row=3, col=0, viewBox=TimeViewBox())
        self._plots = (self.pupil, self.lum, self.ratio, self.cw)
        self._base_plots = self._plots
        self.PLOT_KEYS = ("pupil", "lum", "ratio", "cw")
        self._shown = {"pupil": True, "lum": False, "ratio": False, "cw": True}    # which of the four the user wants
        self._ratio_available = False          # the video ratio exists only on the lux route with the video
        self._y_sources: dict = {}             # plot -> [(time, values, trim %)] the value axis is fitted to
        self._y_zoomed: set = set()            # the plots whose value axis the user zoomed: it stays as they set it
        self._zoom_mode = False
        self._sensor_plots: list = []
        self._sensor_labels: list = []        # the label of each sensor plot, as set_sensors was given it
        self._x_limits = None                  # (first, last) time of the recording: the time axis stays inside it
        self._beats: dict = {}                 # label -> (times, values, trusted) of the beats drawn on that plot
        self._beat_items: list = []
        self._series_items: dict = {}          # label -> (curve, red points, plot) of each sensor plot
        self._sensor_cursors: list = []
        self._events: list = []
        self._cursor_time = 0.0
        self._trim = Trim()
        self._trim_span = (0.0, 0.0)
        self._trim_items: list = []        # (plot, item) of everything drawn for the export range
        self._start_line = self._end_line = None
        self._start_shades: list = []
        self._end_shades: list = []
        self._exclusion_shades: list = []  # per excluded segment: its region on every plot, the pupil plot's first
        self._stretch = (3, 1.6, 1.1, 2)
        for row, stretch in enumerate(self._stretch):
            self.ci.layout.setRowStretchFactor(row, stretch)
        for p in (self.lum, self.ratio, self.cw):
            p.setXLink(self.pupil)
        for p in self._plots:
            p.showGrid(x=True, y=True, alpha=0.2)
            p.setClipToView(True)
            p.setDownsampling(auto=True, mode="peak")
            for side in ("left", "bottom"):
                p.getAxis(side).enableAutoSIPrefix(False)  # keep values in mm and s
            p.getAxis("left").setWidth(AXIS_WIDTH)
        self._follow = True
        self._data = (None, None, None)    # time, pupil values, ΔPD values the view is fitted to
        for p in self._plots:
            p.vb.sigRangeChangedManually.connect(self._moved_by_user)
            p.hideButtons()   # pyqtgraph's own auto-range button would include the overlays
        for p in self._plots:
            self._watch_box(p)
        self.pupil.vb.sigXRangeChanged.connect(self._fit_y_all)    # the value axes show the data of the time span in view
        self.pupil.setLabel("left", "Pupil diameter (mm)")
        self.cw.setLabel("left", "ΔPD (mm)")
        self.lum.setLabel("left", "Luminance (cd/m²)")
        self.lum.setLogMode(x=False, y=True)      # luminance spans decades (the display's black to its white)
        self.ratio.setLabel("left", "Video ratio")
        self.cw.setLabel("bottom", "Time (s)")
        for p in (self.pupil, self.lum, self.ratio):
            p.getAxis("bottom").setStyle(showValues=False)     # the time axis is at the bottom of the stack
        self.pupil.addLegend(offset=(-10, 44), brush=pg.mkBrush(255, 255, 255, 210))   # below Reset view

        button_style = ("QToolButton { padding: 0; border: 1px solid #999; border-radius: 5px;"
                        " background: rgba(255, 255, 255, 230); }"
                        f"QToolButton:hover {{ background: #fff1eb; border-color: {palette.ACCENT}; }}"
                        f"QToolButton:checked {{ background: {palette.ACCENT}; border-color: {palette.ACCENT}; }}")
        self.reset_button = QToolButton(self)
        self.reset_button.setIcon(self._button_icon("arrows-maximize"))
        self.reset_button.setToolTip("Reset view: show all the data again (Ctrl+0, or double-click the plots)")
        self.reset_button.setStyleSheet(button_style)
        self.reset_button.clicked.connect(self.fit_to_data)
        self.zoom_button = QToolButton(self)
        self.zoom_button.setIcon(self._button_icon("zoom-in"))
        self.zoom_button.setCheckable(True)
        self.zoom_button.setToolTip("Zoom mode: drag a rectangle on a plot to zoom to it, in time and in value. "
                                    "Off: dragging pans in time. Right-click zooms out")
        self.zoom_button.setStyleSheet(button_style)
        for button in (self.reset_button, self.zoom_button):     # square, the icon in the middle
            button.setIconSize(QSize(18, 18))
            button.setFixedSize(32, 32)
        self.zoom_button.toggled.connect(self.set_zoom_mode)

        self.raw_curve = self.pupil.plot(pen=pg.mkPen((160, 160, 160), width=1), name="Measured (raw)", connect="finite")
        self.measured_curve = self.pupil.plot(pen=pg.mkPen("k", width=1.5), name="Measured", connect="finite")
        self.expected_curve = self.pupil.plot(pen=pg.mkPen(palette.EXPECTED, width=2), name="Expected")
        dash = pg.mkPen(palette.EXPECTED, width=1.5, style=pg.QtCore.Qt.DashLine)
        self.black_line = pg.InfiniteLine(angle=0, pen=dash, label="black point",     # its label to the right of the
                                          labelOpts={"position": 0.28, "color": palette.rgb(palette.EXPECTED)})   # white's
        self.white_line = pg.InfiniteLine(angle=0, pen=dash, label="white point",
                                          labelOpts={"position": 0.08, "color": palette.rgb(palette.EXPECTED)})
        self.pupil.addItem(self.black_line, ignoreBounds=True)
        self.pupil.addItem(self.white_line, ignoreBounds=True)

        self.lum.addLegend(offset=(-10, 10), brush=pg.mkBrush(255, 255, 255, 210))
        self.lum_curve = self.lum.plot(pen=pg.mkPen(palette.ACCENT, width=1.8), name="Luminance used",
                                       connect="finite")
        self.sensor_curve = self.lum.plot(pen=pg.mkPen((120, 120, 120), width=1.5, style=pg.QtCore.Qt.DashLine),
                                          name="Sensor average", connect="finite")
        self.ratio_curve = self.ratio.plot(pen=pg.mkPen(palette.ACCENT, width=1.2), connect="finite")
        self.ratio.addItem(pg.InfiniteLine(angle=0, pos=1, pen=pg.mkPen((120, 120, 120), width=1)), ignoreBounds=True)
        self.ratio.setToolTip("Y_gaze / Y_frame: how much brighter the gazed area is than the whole frame. "
                              "1 = the same; it should stay near 1 on a uniform view")
        for p in (self.lum, self.ratio):
            p.setDownsampling(auto=False)          # decimated once in show_result
        self.set_lux_route(False, False)
        self.cw_curve = self.cw.plot(pen=pg.mkPen(palette.DELTA_PD, width=1.5), connect="finite")
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
        red = palette.rgb(palette.CURSOR)
        self._moving_cursor = False
        self.cursors = [pg.InfiniteLine(angle=90, movable=True, pen=pg.mkPen(red, width=2),
                                        hoverPen=pg.mkPen(red, width=4)) for _ in self._plots]
        self.cursors[0].label = pg.InfLineLabel(self.cursors[0], text="{value:.2f} s", position=0.97,
                                                anchors=[(0, 0), (0, 0)], color=red,
                                                fill=pg.mkBrush(255, 255, 255, 200))
        for plot, line in zip(self._plots, self.cursors):
            line.setZValue(20)                  # above the curves and overlays, so it can always be grabbed
            line.setCursor(pg.QtCore.Qt.SizeHorCursor)
            plot.addItem(line, ignoreBounds=True)
            line.sigPositionChanged.connect(self._cursor_dragged)
        self.scene().sigMouseClicked.connect(self._clicked)

    def resizeEvent(self, event) -> None:
        """Keep the reset-view button in the top right corner."""
        super().resizeEvent(event)
        if not hasattr(self, "reset_button"):     # resized while the base class is being built
            return
        self.reset_button.adjustSize()
        self.zoom_button.adjustSize()
        self.reset_button.move(self.width() - self.reset_button.width() - 12, 8)
        self.zoom_button.move(self.reset_button.x() - self.zoom_button.width() - 8, 8)

    @staticmethod
    def _button_icon(name: str) -> QIcon:
        """The icon of a button over the plots: dark on the light button, white when it is pressed (the plots are always
        light, so the palette's text colour is not used)."""
        icon = QIcon()
        icon.addPixmap(pixmap(name, "#222222", 18), QIcon.Normal, QIcon.Off)
        icon.addPixmap(pixmap(name, "#ffffff", 18), QIcon.Normal, QIcon.On)
        return icon

    def set_zoom_mode(self, on: bool) -> None:
        """Dragging draws a rectangle to zoom to, in time and in value (on), or pans in time (off)."""
        self._zoom_mode = bool(on)
        if self.zoom_button.isChecked() != self._zoom_mode:
            self.zoom_button.setChecked(self._zoom_mode)
        for plot in self._plots:
            plot.vb.set_zoom_mode(self._zoom_mode)

    def _watch_box(self, plot) -> None:
        plot.vb.sigValueZoomed.connect(self._value_zoomed)
        plot.vb.sigValueReset.connect(self._value_reset)
        plot.vb.set_zoom_mode(self._zoom_mode)

    def _value_zoomed(self, box, lo: float, hi: float) -> None:
        """The user zoomed a plot to a rectangle: its value axis keeps that range until the view is reset."""
        for plot in self._plots:
            if plot.vb is box:
                self._y_zoomed.add(plot)
                plot.setYRange(lo, hi, padding=0)

    def _value_reset(self, box) -> None:
        for plot in self._plots:
            if plot.vb is box:
                self._y_zoomed.discard(plot)
                self._fit_y(plot)

    def cursor_time(self) -> float:
        """Time (s) of the red cursor."""
        return self._cursor_time

    def set_cursor(self, t: float) -> None:
        """Move the bar without reporting it (the caller already knows the time)."""
        self._cursor_time = t
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
        for plot in self._plots:
            if plot.isVisible() and plot.sceneBoundingRect().contains(event.scenePos()):
                t = float(plot.vb.mapSceneToView(event.scenePos()).x())
                self.set_cursor(t)
                self.cursor_changed.emit(t)
                return

    @staticmethod
    def _log10(values) -> np.ndarray:
        v = np.asarray(values, dtype=float)
        return np.log10(np.where(v > 0, v, np.nan))

    def clear_result(self) -> None:
        """Empty the curves; the next result is fitted to the view."""
        for c in (self.raw_curve, self.measured_curve, self.expected_curve, self.cw_curve, self.lum_curve,
                  self.sensor_curve, self.ratio_curve):
            c.setData([], [])
        self._follow = True   # the next result (a new recording) is fitted

    def _moved_by_user(self, *_) -> None:
        self._follow = False

    def _apply_x_limits(self) -> None:
        """Keep the time axis of every plot inside the recording: it can be zoomed in and moved along the recording, but
        not scrolled off the data (which a swipe on a trackpad or a drag that misses the cursor would do), and not zoomed
        out beyond it. The sensor files reach a little past the recording; that part is not shown."""
        if self._x_limits is None:
            return
        lo, hi = self._x_limits
        for plot in self._plots:
            plot.vb.setLimits(xMin=lo, xMax=hi)

    def fit_to_data(self) -> None:
        """Show all the recording: its time span, and the value axes fitted to the data. The view then follows parameter
        changes again."""
        self._follow = True
        self._y_zoomed.clear()
        t = self._data[0]
        if t is None:
            return
        finite_t = t[np.isfinite(t)]
        if len(finite_t):
            self.pupil.setXRange(float(finite_t[0]), float(finite_t[-1]), padding=0.02)
        self._fit_y_all()

    # The value axes: they cannot be dragged, they always show all the data of the time span in view

    def _set_y_source(self, plot, sources) -> None:
        """Fit ``plot``'s value axis to ``sources``, a list of ``(time, values, trim)``: the finite values between the
        ``trim`` and 100 - ``trim`` percentiles of every curve (artefacts are already removed from the smoothed ones; the
        noisier raw curve may extend beyond)."""
        self._y_sources[plot] = [(np.asarray(t, dtype=float), np.asarray(v, dtype=float), trim) for t, v, trim in sources]
        self._fit_y(plot)

    def _fit_y_all(self, *_) -> None:
        for plot in self._y_sources:
            self._fit_y(plot)

    def _fit_y(self, plot) -> None:
        if plot in self._y_zoomed:
            return
        lo_x, hi_x = self.pupil.vb.viewRange()[0]
        lows, highs = [], []
        for t, v, trim in self._y_sources.get(plot, ()):
            if len(t) != len(v):
                continue
            lo, hi = data_range(v[(t >= lo_x) & (t <= hi_x)], trim)
            if lo is not None:
                lows.append(lo)
                highs.append(hi)
        if lows:
            lo, hi = min(lows), max(highs)
            margin = 0.08 * (hi - lo)
            plot.setYRange(lo - margin, hi + margin, padding=0)

    def _restore_x(self, view) -> None:
        try:
            self.pupil.setXRange(*view, padding=0)
        except RuntimeError:     # the widget is gone
            pass

    def _fit_if_following(self) -> None:
        if self._follow:
            self.fit_to_data()

    def show_result(self, r: Result) -> None:
        """Draw the pupil, ΔPD and luminance curves of a result."""
        self.raw_curve.setData(r.time, r.measured_raw)
        self.measured_curve.setData(r.time, r.measured)
        self.expected_curve.setData(r.time, r.expected)
        self.cw_curve.setData(r.cw_time, r.cw)
        has_sensor = r.luminance_sensor is not None
        has_ratio = has_sensor and r.luminance_ratio is not None
        # The luminance curves are dense and jagged: decimate them once, keeping each bin's extremes, so
        # that repainting on every cursor move and pan stays fast.
        self.lum_curve.setData(*peak_decimate(r.time, r.luminance))
        self.sensor_curve.setData(*(peak_decimate(r.time, r.luminance_sensor) if has_sensor else ([], [])))
        self.ratio_curve.setData(*(peak_decimate(r.time, r.luminance_ratio) if has_ratio else ([], [])))
        self.set_lux_route(has_sensor, has_ratio)
        self.lum.setLabel("left", "Luminance (cd/m², relative)" if r.luminance_mode == "camera, relative"
                          else "Luminance (cd/m²)")
        self._data = (np.asarray(r.time), np.concatenate([r.measured, r.expected]), np.asarray(r.cw))
        finite_time = np.asarray(r.time)[np.isfinite(r.time)]
        self._x_limits = (float(finite_time.min()), float(finite_time.max())) if len(finite_time) else None
        self._apply_x_limits()
        self._set_y_source(self.pupil, [(r.time, r.measured, 0.0), (r.time, r.expected, 0.0)])
        self._set_y_source(self.cw, [(r.cw_time, r.cw, 0.0)])
        logs = [(r.time, self._log10(r.luminance), 0.0)]      # the luminance plot is logarithmic
        if has_sensor:
            logs.append((r.time, self._log10(r.luminance_sensor), 0.0))
        self._set_y_source(self.lum, logs)
        self._set_y_source(self.ratio, [(r.time, r.luminance_ratio, 0.0)] if has_ratio else [])
        if self._follow:
            self.fit_to_data()
            QTimer.singleShot(0, self._fit_if_following)     # and again once the layout has settled
        markers = np.isfinite(r.expected_black)   # not defined when luminance comes from a lux sensor
        self.black_line.setVisible(bool(markers))
        self.white_line.setVisible(bool(markers))
        if markers:
            self.black_line.setValue(r.expected_black)
            self.white_line.setValue(r.expected_white)

    def set_lux_route(self, sensor: bool, ratio: bool) -> None:
        """Show the sensor curve (lux route) and make the video ratio plot available (lux route with the video)."""
        self.sensor_curve.setVisible(sensor)
        self._ratio_available = ratio
        self._apply_rows()

    # Which of the four plots are shown (the others are hidden and their room goes to the rest)

    def ratio_available(self) -> bool:
        """Whether the video ratio plot has anything to show (lux route with the video)."""
        return self._ratio_available

    def plot_shown(self, key: str) -> bool:
        """Whether the plot ``key`` ("pupil", "lum", "ratio" or "cw") is shown."""
        return self._shown[key] and (key != "ratio" or self._ratio_available)

    def set_plot_shown(self, key: str, on: bool) -> None:
        """Show or hide the pupil, luminance, video ratio or ΔPD plot."""
        self._shown[key] = bool(on)
        self._apply_rows()

    def _apply_rows(self) -> None:
        for row, (key, plot) in enumerate(zip(self.PLOT_KEYS, self._base_plots)):
            on = self.plot_shown(key)
            plot.setVisible(on)
            self.ci.layout.setRowStretchFactor(row, self._stretch[row] if on else 0)
            self.ci.layout.setRowMaximumHeight(row, 16777215 if on else 0)
        self._arrange_axes()

    def show_events(self, events) -> None:
        """Shade the events (phases of the experiment) on every plot."""
        self._events = list(events)
        for plot, item in self._event_items:
            plot.removeItem(item)
        self._event_items = []
        for e in events:
            for plot in self._plots:
                region = pg.LinearRegionItem((e.start, e.end), movable=False,
                                             brush=pg.mkBrush(*palette.rgb(palette.EVENT), 35), pen=pg.mkPen(None))
                region.setZValue(-20)
                plot.addItem(region, ignoreBounds=True)
                self._event_items.append((plot, region))
            label = pg.TextItem(e.label, color=palette.rgb(palette.EVENT_TEXT), anchor=(0, 0))
            label.setPos(e.start, 0)
            self.cw.addItem(label, ignoreBounds=True)
            self._event_items.append((self.cw, label))

    # Sensor signals (the logger's Shimmer and EmotiBit files), one plot each under ΔPD

    def set_sensors(self, specs) -> None:
        """Show ``specs``, a list of ``(label, time, values)`` or ``(label, time, values, options)`` (time in the
        recording's relative seconds), as plots under ΔPD on the shared time axis; an empty list removes them. The options
        are a dictionary: ``colour`` (r, g, b) of the curve, ``axis`` (the axis label; by default the label cut short) and
        ``weak`` = (times, values) of points to mark in red."""
        for plot, line in self._sensor_cursors:
            self.cursors.remove(line)
        for row in range(4, 4 + len(self._sensor_plots)):
            self.ci.layout.setRowStretchFactor(row, 0)
        for plot in self._sensor_plots:
            self._y_sources.pop(plot, None)
            self._y_zoomed.discard(plot)
            self.removeItem(plot)
        self._sensor_plots, self._sensor_cursors, self._sensor_labels = [], [], []
        self._series_items = {}
        red = palette.rgb(palette.CURSOR)
        view = self.pupil.vb.viewRange()[0]
        for i, spec in enumerate(specs):
            label, t, v = spec[:3]
            options = spec[3] if len(spec) > 3 else {}
            box = TimeViewBox()
            box.setXRange(*view, padding=0)     # a new view starts at 0 to 1 s, and would pull the others to it
            plot = self.addPlot(row=4 + i, col=0, viewBox=box)
            self._watch_box(plot)
            plot.getAxis("left").setWidth(AXIS_WIDTH)
            plot.setLabel("left", options.get("axis") or short_label(label))
            plot.setXLink(self.pupil)
            plot.showGrid(x=True, y=True, alpha=0.2)
            plot.setClipToView(True)
            plot.setDownsampling(auto=False)       # decimated once, below
            for side in ("left", "bottom"):
                plot.getAxis(side).enableAutoSIPrefix(False)
            plot.vb.sigRangeChangedManually.connect(self._moved_by_user)
            plot.hideButtons()
            plot.disableAutoRange()   # the sensor files reach a little past the recording: they do not set the view
            plot.setTitle(label, size="8pt")
            curve = plot.plot(*peak_decimate(t, v), pen=pg.mkPen(options.get("colour", (40, 90, 150)), width=1.2),
                              connect="finite")
            weak = pg.ScatterPlotItem(*(options.get("weak") or ([], [])), symbol="o", size=6, pen=pg.mkPen(None),
                                      brush=pg.mkBrush(*palette.rgb(palette.RED)))
            weak.setZValue(10)
            plot.addItem(weak, ignoreBounds=True)
            self._series_items[label] = (curve, weak, plot)
            self._set_y_source(plot, [(t, v, 0.5)])     # without the outermost 0.5 % of the values
            line = pg.InfiniteLine(angle=90, movable=True, pen=pg.mkPen(red, width=2),
                                   hoverPen=pg.mkPen(red, width=4))
            line.setZValue(20)
            line.setCursor(pg.QtCore.Qt.SizeHorCursor)
            line.setValue(self._cursor_time)
            line.sigPositionChanged.connect(self._cursor_dragged)
            plot.addItem(line, ignoreBounds=True)
            self.ci.layout.setRowStretchFactor(4 + i, 1.6)
            self._sensor_plots.append(plot)
            self._sensor_labels.append(label)
            self._sensor_cursors.append((plot, line))
            self.cursors.append(line)
        self._plots = self._base_plots + tuple(self._sensor_plots)
        self._arrange_axes()
        self.show_events(self._events)
        self._redraw_trim()
        self._draw_beats()
        self._apply_x_limits()
        self.pupil.setXRange(*view, padding=0)      # new plots must not move the time axis the others show
        QTimer.singleShot(0, partial(self._restore_x, view))

    def update_series(self, label: str, t, v, weak=None) -> bool:
        """Replace the data of the sensor plot titled ``label`` (and its red points) without rebuilding the plots, and
        fit its value axis again. Returns False if no such plot is shown."""
        if label not in self._series_items:
            return False
        curve, marks, plot = self._series_items[label]
        curve.setData(*peak_decimate(t, v), connect="finite")
        marks.setData(*(weak or ([], [])))
        self._set_y_source(plot, [(t, v, 0.5)])
        return True

    def set_beats(self, label: str, times, values, trusted) -> None:
        """Mark the heartbeats found in an ECG on the sensor plot titled ``label``: at ``times`` (relative seconds) and
        height ``values`` (the ECG there): green circles where the interval before the beat is trusted, red crosses where
        it is not."""
        self._beats[label] = (np.asarray(times, dtype=float), np.asarray(values, dtype=float),
                              np.asarray(trusted, dtype=bool))
        self._draw_beats()

    def clear_beats(self) -> None:
        """Remove the beat markers."""
        self._beats = {}
        self._draw_beats()

    def _draw_beats(self) -> None:
        """(Re)draw the beat markers on the plots that are shown; markers of a plot that is not shown wait."""
        for plot, item in self._beat_items:
            plot.removeItem(item)
        self._beat_items = []
        for plot, label in zip(self._sensor_plots, self._sensor_labels):
            if label not in self._beats:
                continue
            t, v, ok = self._beats[label]
            for flag, colour, symbol in ((True, palette.rgb(palette.GREEN), "o"),
                                         (False, palette.rgb(palette.RED), "x")):
                sel = ok == flag
                if sel.any():
                    item = pg.ScatterPlotItem(t[sel], v[sel], symbol=symbol, size=8,
                                              pen=pg.mkPen(colour, width=2) if symbol == "x" else pg.mkPen(None),
                                              brush=pg.mkBrush(*colour))
                    item.setZValue(10)
                    plot.addItem(item, ignoreBounds=True)
                    self._beat_items.append((plot, item))

    def _arrange_axes(self) -> None:
        """The time axis (values and label) is on the last plot of the stack that is shown."""
        shown = [p for key, p in zip(self.PLOT_KEYS, self._base_plots) if self.plot_shown(key)] + self._sensor_plots
        if not shown:
            return
        for plot in self._plots:
            last = plot is shown[-1]
            plot.getAxis("bottom").setStyle(showValues=last)
            plot.getAxis("bottom").setLabel("Time (s)" if last else "")

    # Export range: where the export starts and ends and what it leaves out (cwtool.trim.Trim)

    SHADE = (90, 90, 90, 80)
    FAR = 1e7    # shading runs far past the data on the open side

    def show_trim(self, trim: Trim, lo: float, hi: float) -> None:
        """Draw the export range over the plots; ``lo``, ``hi`` is the recording's time span."""
        self._trim, self._trim_span = trim, (lo, hi)
        self._redraw_trim()

    def _add_trim_item(self, plot, item, z: float) -> None:
        item.setZValue(z)
        plot.addItem(item, ignoreBounds=True)
        self._trim_items.append((plot, item))

    def _redraw_trim(self) -> None:
        for plot, item in self._trim_items:
            if item.scene() is not None:
                plot.removeItem(item)
        self._trim_items = []
        self._start_line = self._end_line = None
        self._start_shades, self._end_shades, self._exclusion_shades = [], [], []
        trim = self._trim
        brush = pg.mkBrush(*self.SHADE)
        edge = pg.mkPen((60, 60, 60), width=2, style=pg.QtCore.Qt.DashLine)
        if trim.start is not None:
            for plot in self._plots:
                shade = pg.LinearRegionItem((-self.FAR, trim.start), movable=False, brush=brush, pen=pg.mkPen(None))
                self._add_trim_item(plot, shade, -15)
                self._start_shades.append(shade)
            self._start_line = pg.InfiniteLine(trim.start, angle=90, movable=True, pen=edge, label="export starts",
                                               labelOpts={"position": 0.9, "color": (60, 60, 60)})
            self._start_line.sigPositionChanged.connect(self._edge_moved)
            self._add_trim_item(self.pupil, self._start_line, 15)
        if trim.end is not None:
            for plot in self._plots:
                shade = pg.LinearRegionItem((trim.end, self.FAR), movable=False, brush=brush, pen=pg.mkPen(None))
                self._add_trim_item(plot, shade, -15)
                self._end_shades.append(shade)
            self._end_line = pg.InfiniteLine(trim.end, angle=90, movable=True, pen=edge, label="export ends",
                                             labelOpts={"position": 0.9, "color": (60, 60, 60)})
            self._end_line.sigPositionChanged.connect(self._edge_moved)
            self._add_trim_item(self.pupil, self._end_line, 15)
        for k, (a, b) in enumerate(trim.exclude):
            regions = []
            for plot in self._plots:   # the pupil plot's region can be dragged; the others follow it
                region = pg.LinearRegionItem((a, b), movable=plot is self.pupil, brush=brush, pen=edge)
                self._add_trim_item(plot, region, 12 if plot is self.pupil else -14)
                regions.append(region)
            regions[0].sigRegionChanged.connect(partial(self._exclusion_moved, k))
            regions[0].sigRegionChangeFinished.connect(self._drag_finished)
            self._exclusion_shades.append(regions)

    def _current_trim(self) -> Trim:
        start = float(self._start_line.value()) if self._start_line is not None else None
        end = float(self._end_line.value()) if self._end_line is not None else None
        return Trim(start, end, [tuple(regions[0].getRegion()) for regions in self._exclusion_shades])

    def _edge_moved(self, *_) -> None:
        if self._start_line is not None:
            for shade in self._start_shades:
                shade.setRegion((-self.FAR, float(self._start_line.value())))
        if self._end_line is not None:
            for shade in self._end_shades:
                shade.setRegion((float(self._end_line.value()), self.FAR))
        self._emit_dragged()

    def _exclusion_moved(self, k: int, *_) -> None:
        regions = self._exclusion_shades[k]
        span = regions[0].getRegion()
        for region in regions[1:]:
            region.setRegion(span)
        self._emit_dragged()

    def _emit_dragged(self) -> None:
        self._trim = self._current_trim()
        self.trim_dragged.emit(self._trim)

    def _drag_finished(self, *_) -> None:
        # Segments dragged over each other merge: draw the normalised ones, after this signal has returned.
        QTimer.singleShot(0, self._redraw_trim)

    # Calibration sequence overlay

    def set_sequence(self, visible: bool, start: float, sequence: calibration.Sequence | None = None) -> None:
        """Show or hide the calibration sequence's overlay, with its start time and (optionally) a new sequence."""
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


DECIMATED_BINS = 1500


def short_label(label: str, limit: int = 13) -> str:
    """The text of a plot's title cut to what fits beside a short plot as an axis label: after the sensor's name, with an
    ellipsis."""
    text = label.split(": ", 1)[-1]
    return text if len(text) <= limit else text[:limit - 1] + "…"


def peak_decimate(x, y, bins: int = DECIMATED_BINS):
    """``x`` and ``y`` reduced to the minimum and the maximum of each of ``bins`` consecutive bins, in time
    order, so peaks survive. Bins without finite values give NaN (a gap in the curve). Short signals are
    returned as they are."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    if len(y) <= 2 * bins:
        return x, y
    edges = np.linspace(0, len(y), bins + 1).astype(int)
    xs, ys = [], []
    for a, b in zip(edges[:-1], edges[1:]):
        seg = y[a:b]
        if not np.isfinite(seg).any():
            xs.append(x[a]); ys.append(np.nan)
            continue
        i_lo, i_hi = int(np.nanargmin(seg)), int(np.nanargmax(seg))
        for i in sorted({i_lo, i_hi}):
            xs.append(x[a + i]); ys.append(seg[i])
    return np.asarray(xs), np.asarray(ys)


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
