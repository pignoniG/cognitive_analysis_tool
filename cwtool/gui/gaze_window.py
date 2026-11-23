"""The gaze correction: the scene video with the gaze on it and the gaze check's places, the session's offset (right, down)
redrawn live, and each place's error left. Confirming it saves the offset (and a Quest capture's projection measured from
the dots) with the recording; the app analyses the video only then (open issue 61)."""

from __future__ import annotations

from typing import Optional

import cv2
import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout,
                               QHBoxLayout, QHeaderView, QLabel, QPushButton, QSizePolicy, QSlider, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from cwtool import palette
from cwtool.gazecheck import GazeCheck
from cwtool.projection import Projection, of_profile
from cwtool.recording import Recording
from cwtool.video import FrameClock

DISPLAY_WIDTH = 960
MARGIN = 3.0            # s shown before the first place and after the last
GAZE_SPAN = 0.1         # s: the gaze samples drawn around the frame's time
TARGET_COLOUR = palette.rgb(palette.GREEN)
OTHER_COLOUR = (150, 150, 150)
GAZE_COLOUR = palette.rgb(palette.ORANGE_1)
SLIDER_STEPS = 2000


class GazeCorrection(QDialog):
    """The scene video of ``rec`` (aligned to its pupil, gaze with the session's offset applied) with its gaze and the
    places of the gaze check ``check`` (None: the video and the gaze only), and the offset to confirm."""

    def __init__(self, rec: Recording, check: Optional[GazeCheck], parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Gaze correction: {rec.name}")
        self.rec, self.check = rec, check
        self.applied = tuple(rec.gaze_offset or (0.0, 0.0))
        self.used = of_profile(rec.profile)
        self.measured = Projection.from_tuple(check.projection) if check is not None and check.projection_differs() \
            else None
        self.shown = self.measured or self.used          # where directions fall once confirmed
        self.places = list(check.places) if check is not None else []
        self.reference = [self._reference_deg(p) for p in self.places]
        self._gaze = np.asarray(rec.gaze, dtype=float)
        self._time = np.asarray(rec.time, dtype=float)
        self._gaze_deg = self.used.to_angles(self._gaze)        # the gaze's picture angles as recorded (offset applied)

        self._cap = cv2.VideoCapture(str(rec.scene_video))
        fps = self._cap.get(cv2.CAP_PROP_FPS) or 30.0
        self._clock = FrameClock(fps, rec.scene_frame_times)
        self._n_frames = int(self._cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self._frame: tuple[int, np.ndarray] | None = None
        self.t = 0.0

        # The video, its time slider and the places' span
        self.image = QLabel()
        self.image.setAlignment(Qt.AlignCenter)
        self.image.setMinimumSize(480, 270)
        self.image.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, SLIDER_STEPS)
        self.slider.valueChanged.connect(lambda v: self.show_time(self._slider_time(v)))
        self.time_label = QLabel()
        self.whole = QCheckBox("Whole recording")
        self.whole.setToolTip("Scroll through the whole recording rather than the gaze check")
        self.whole.setChecked(not self.places)
        self.whole.setEnabled(bool(self.places))
        under = QHBoxLayout()
        under.addWidget(self.time_label, 1)
        under.addWidget(self.whole)
        left = QVBoxLayout()
        left.addWidget(self.image, 1)
        left.addWidget(self.slider)
        left.addLayout(under)

        # The offset, the places and their errors
        self.dx, self.dy = QDoubleSpinBox(), QDoubleSpinBox()
        for box, name in ((self.dx, "right"), (self.dy, "down")):
            box.setRange(-30.0, 30.0)
            box.setDecimals(2)
            box.setSingleStep(0.1)
            box.setSuffix(f"° {name}")
            box.setKeyboardTracking(False)
        self.dx.setValue(self.applied[0])
        self.dy.setValue(self.applied[1])
        self.dx.valueChanged.connect(self._offset_changed)
        self.dy.valueChanged.connect(self._offset_changed)
        found = check.total_offset_deg() if check is not None else None
        self.from_check = QPushButton("Use the gaze check's offset")
        self.from_check.setEnabled(found is not None)
        self.from_check.setToolTip("The offset that puts the gaze on the places (their median)" if found is not None else
                                   "The gaze check found too few places for an offset")
        self.from_check.clicked.connect(lambda: self.set_offset(found))
        self.zero = QPushButton("No offset")
        self.zero.clicked.connect(lambda: self.set_offset((0.0, 0.0)))
        form = QFormLayout()
        form.addRow("Offset", self.dx)
        form.addRow("", self.dy)
        offset_buttons = QHBoxLayout()
        offset_buttons.addWidget(self.from_check)
        offset_buttons.addWidget(self.zero)

        self.table = QTableWidget(len(self.places), 2)
        self.table.setHorizontalHeaderLabels(["Place", "Error left"])
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setToolTip("Click a place to see it")
        for row, p in enumerate(self.places):
            self.table.setItem(row, 0, QTableWidgetItem(f"{p.index}  ({p.u:+.0f}, {p.v:+.0f})"))
            self.table.setItem(row, 1, QTableWidgetItem("–"))
        self.table.cellClicked.connect(lambda row, _: self.go_to_place(row))
        self.median = QLabel()
        self.median.setWordWrap(True)
        notes = []
        if check is None:
            notes.append("No gaze check: judge the gaze by the video alone.")
        else:
            notes.append(check.summary())
            notes += check.notes
        if self.measured is not None:
            notes.append(f"The capture's projection measured from the dots ({self.measured.describe()}) is drawn here and "
                         "saved on confirming.")
        self.notes = QLabel("<br>".join(notes))
        self.notes.setWordWrap(True)
        self.notes.setStyleSheet("color: gray; font-size: 11px;")
        right = QVBoxLayout()
        right.addLayout(form)
        right.addLayout(offset_buttons)
        right.addWidget(self.table, 1)
        right.addWidget(self.median)
        right.addWidget(self.notes)
        side = QWidget()
        side.setLayout(right)
        side.setFixedWidth(320)

        self.buttons = QDialogButtonBox()
        self.confirm_button = self.buttons.addButton("Confirm and analyse", QDialogButtonBox.AcceptRole)
        self.buttons.addButton(QDialogButtonBox.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)

        body = QHBoxLayout()
        body.addLayout(left, 1)
        body.addWidget(side)
        layout = QVBoxLayout(self)
        layout.addLayout(body, 1)
        layout.addWidget(self.buttons)
        self.resize(1300, 780)

        self.whole.toggled.connect(self._range_changed)
        self._range_changed()
        self._offset_changed()
        if self.places:
            self.go_to_place(0)

    # What the operator chose

    def offset(self) -> tuple:
        """The session's offset to save (deg; right, down)."""
        return (round(self.dx.value(), 3), round(self.dy.value(), 3))

    def projection(self) -> Optional[Projection]:
        """The capture's projection measured from the dots, to save with the offset; None to keep the one in use."""
        return self.measured

    def set_offset(self, offset) -> None:
        if offset is None:
            return
        self.dx.blockSignals(True)
        self.dx.setValue(offset[0])
        self.dx.blockSignals(False)
        self.dy.setValue(offset[1])
        self._offset_changed()

    # Errors

    def _reference_deg(self, place) -> Optional[np.ndarray]:
        """Where the gaze should be at a place (picture angles): its logged direction, else the dot found."""
        if place.target_deg is not None:
            return np.asarray(place.target_deg, dtype=float)
        if place.dot is not None:
            return self.used.to_angles(np.asarray(place.dot, dtype=float))
        return None

    def delta(self) -> np.ndarray:
        """The offset added to the gaze as recorded."""
        return np.array(self.offset()) - np.array(self.applied)

    def errors(self) -> list[Optional[float]]:
        """Each place's distance (deg) between its reference and its median gaze moved by the offset."""
        out = []
        for p, ref in zip(self.places, self.reference):
            if ref is None or p.gaze_deg is None:
                out.append(None)
            else:
                out.append(float(np.hypot(*(ref - (np.asarray(p.gaze_deg) + self.delta())))))
        return out

    def _offset_changed(self) -> None:
        errors = self.errors()
        for row, e in enumerate(errors):
            item = self.table.item(row, 1)
            item.setText("–" if e is None else f"{e:.1f}°")
        known = [e for e in errors if e is not None]
        self.median.setText(f"<b>Median error left: {np.median(known):.1f}°</b> over {len(known)} places" if known else
                            "No place to measure the error at.")
        self.refresh()

    # The video

    def _range(self) -> tuple:
        t0, t1 = (float(self._time[0]), float(self._time[-1])) if len(self._time) else (0.0, 1.0)
        if self.places and not self.whole.isChecked():
            return max(t0, min(p.start for p in self.places) - MARGIN), min(t1, max(p.end for p in self.places) + MARGIN)
        return t0, t1

    def _slider_time(self, value: int) -> float:
        a, b = self._range()
        return a + (b - a) * value / SLIDER_STEPS

    def _range_changed(self) -> None:
        a, b = self._range()
        t = min(max(self.t, a), b)
        self.slider.blockSignals(True)
        self.slider.setValue(int(round((t - a) / max(b - a, 1e-9) * SLIDER_STEPS)))
        self.slider.blockSignals(False)
        self.show_time(t)

    def go_to_place(self, row: int) -> None:
        """Show the middle of a place's window."""
        p = self.places[row]
        self.table.selectRow(row)
        t = (p.start + p.end) / 2
        a, b = self._range()
        if not a <= t <= b:
            self.whole.setChecked(True)
            a, b = self._range()
        self.slider.blockSignals(True)
        self.slider.setValue(int(round((t - a) / max(b - a, 1e-9) * SLIDER_STEPS)))
        self.slider.blockSignals(False)
        self.show_time(t)

    def _read(self, idx: int) -> Optional[np.ndarray]:
        if self._frame is not None and self._frame[0] == idx:
            return self._frame[1]
        self._cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ok, frame = self._cap.read()
        if not ok:
            return None
        self._frame = (idx, frame)
        return frame

    def refresh(self) -> None:
        self.show_time(self.t)

    def _place_at(self, t: float) -> Optional[int]:
        """The place shown at ``t``: the one whose window holds it, or the nearest within a second."""
        best, distance = None, 1.0
        for row, p in enumerate(self.places):
            d = 0.0 if p.start <= t <= p.end else min(abs(t - p.start), abs(t - p.end))
            if d <= distance:
                best, distance = row, d
        return best

    def gaze_at(self, t: float) -> np.ndarray:
        """The gaze samples within GAZE_SPAN of ``t``, moved by the offset and placed through the projection shown
        (normalised video coordinates, M × 2)."""
        near = (np.abs(self._time - t) <= GAZE_SPAN) & np.isfinite(self._gaze).all(axis=1)
        if not near.any():
            return np.zeros((0, 2))
        return self.shown.from_angles(self._gaze_deg[near] + self.delta())

    def show_time(self, t: float) -> None:
        """Draw the frame at ``t`` with the places and the gaze moved by the offset."""
        self.t = t
        if not self._cap.isOpened():
            self.image.setText("Cannot open the scene video.")
            return
        idx = int(np.clip(self._clock.index(t), 0, max(self._n_frames - 1, 0)))
        current = self._place_at(t)
        place = f"  ·  place {self.places[current].index}" if current is not None else ""
        self.time_label.setText(f"{t:.2f} s  ·  frame {idx}{place}")
        frame = self._read(idx)
        if frame is None:
            self.image.setText(f"Cannot read frame {idx}")
            return
        h0, w0 = frame.shape[:2]
        w = min(DISPLAY_WIDTH, w0)
        h = int(round(h0 * w / w0))
        disp = cv2.cvtColor(cv2.resize(frame, (w, h), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2RGB)
        thick = max(2, w // 400)
        ring = max(6, w // 60)
        for row, ref in enumerate(self.reference):
            if ref is None:
                continue
            x, y = self.shown.from_angles(ref)
            centre = (int(x * w), int(y * h))
            colour = TARGET_COLOUR if row == current else OTHER_COLOUR
            cv2.circle(disp, centre, ring, colour, thick if row == current else 1)
            cv2.putText(disp, str(self.places[row].index), (centre[0] + ring + 2, centre[1] - ring), cv2.FONT_HERSHEY_SIMPLEX,
                        0.4 + w / 3000, colour, 1, cv2.LINE_AA)
        points = self.gaze_at(t)
        for x, y in points:
            cv2.circle(disp, (int(x * w), int(y * h)), max(2, thick), GAZE_COLOUR, -1)
        if len(points):
            mx, my = np.median(points, axis=0)
            cv2.drawMarker(disp, (int(mx * w), int(my * h)), GAZE_COLOUR, cv2.MARKER_CROSS, 3 * ring, thick)
        img = QImage(disp.data, w, h, disp.strides[0], QImage.Format_RGB888).copy()
        self.image.setPixmap(QPixmap.fromImage(img).scaled(self.image.size(), Qt.KeepAspectRatio,
                                                           Qt.SmoothTransformation))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.refresh()

    def done(self, result: int) -> None:
        self._cap.release()
        super().done(result)
