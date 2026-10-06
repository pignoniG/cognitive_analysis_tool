"""Sidebar panel for the export range: where the export starts and ends, and the segments it leaves out."""

from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QGridLayout,
                               QGroupBox, QHBoxLayout, QLabel, QListWidget, QPushButton, QVBoxLayout)

from cwtool.trim import Trim

DEFAULT_SEGMENT = 10.0   # s, length of a segment added at the cursor


def _spin(minimum: float = -1e7, maximum: float = 1e7) -> QDoubleSpinBox:
    spin = QDoubleSpinBox()
    spin.setRange(minimum, maximum)
    spin.setDecimals(2)
    spin.setSingleStep(0.5)
    spin.setSuffix(" s")
    spin.setKeyboardTracking(False)
    return spin


class SegmentDialog(QDialog):
    """Edit the start and end of a left-out segment."""

    def __init__(self, start: float, end: float, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Left-out segment")
        form = QFormLayout(self)
        self.start, self.end = _spin(), _spin()
        self.start.setValue(start)
        self.end.setValue(end)
        form.addRow("From", self.start)
        form.addRow("To", self.end)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def segment(self) -> tuple[float, float]:
        a, b = self.start.value(), self.end.value()
        return (a, b) if a <= b else (b, a)


class TrimPanel(QGroupBox):
    """Edits a :class:`cwtool.trim.Trim`. Times are seconds on the recording's relative clock (the axis of the
    plots). :attr:`changed` is emitted when the user edits it here; changes made on the plots are passed in with
    :meth:`set_trim` (``quiet``) so they are not echoed back."""

    changed = Signal(object)

    def __init__(self, parent=None):
        super().__init__("Export range", parent)
        self._trim = Trim()
        self._lo = self._hi = 0.0
        self.cursor_time: Callable[[], float] = lambda: 0.0
        self.sequence_span: Callable[[], Optional[tuple[float, float]]] = lambda: None

        self.start_check = QCheckBox("Start at")
        self.start_spin = _spin()
        self.start_cursor = QPushButton("Cursor")
        self.end_check = QCheckBox("End at")
        self.end_spin = _spin()
        self.end_cursor = QPushButton("Cursor")
        for button in (self.start_cursor, self.end_cursor):
            button.setToolTip("Use the time of the red cursor on the plots")
        grid = QGridLayout()
        grid.addWidget(self.start_check, 0, 0)
        grid.addWidget(self.start_spin, 0, 1)
        grid.addWidget(self.start_cursor, 0, 2)
        grid.addWidget(self.end_check, 1, 0)
        grid.addWidget(self.end_spin, 1, 1)
        grid.addWidget(self.end_cursor, 1, 2)

        self.segments = QListWidget()
        self.segments.setMaximumHeight(90)
        self.segments.setToolTip("Left out of the export, as the grey bands on the plots. Drag a band's edges or "
                                 "the band itself on the pupil plot, or double-click here to type the times")
        self.add_button = QPushButton("Leave out from cursor")
        self.add_button.setToolTip(f"Leave out {DEFAULT_SEGMENT:g} s from the red cursor: adjust it on the plot")
        self.sequence_button = QPushButton("Leave out calibration")
        self.sequence_button.setToolTip("Leave out the calibration sequence (turn on its overlay to place it)")
        self.edit_button = QPushButton("Edit…")
        self.remove_button = QPushButton("Remove")
        buttons = QHBoxLayout()
        for b in (self.add_button, self.sequence_button):
            buttons.addWidget(b)
        buttons2 = QHBoxLayout()
        for b in (self.edit_button, self.remove_button):
            buttons2.addWidget(b)
        self.summary = QLabel()
        self.summary.setWordWrap(True)

        layout = QVBoxLayout(self)
        note = QLabel("What the export leaves out: a calibration, a break, a test run. The analysis and the plots "
                      "always use the whole recording.")
        note.setWordWrap(True)
        note.setStyleSheet("font-style: italic;")
        layout.addWidget(note)
        layout.addLayout(grid)
        layout.addWidget(QLabel("Left out:"))
        layout.addWidget(self.segments)
        layout.addLayout(buttons)
        layout.addLayout(buttons2)
        layout.addWidget(self.summary)

        self.start_check.toggled.connect(self._start_toggled)
        self.end_check.toggled.connect(self._end_toggled)
        self.start_spin.valueChanged.connect(self._edge_edited)
        self.end_spin.valueChanged.connect(self._edge_edited)
        self.start_cursor.clicked.connect(lambda: self.start_spin.setValue(self._clamped(self.cursor_time())))
        self.end_cursor.clicked.connect(lambda: self.end_spin.setValue(self._clamped(self.cursor_time())))
        self.add_button.clicked.connect(self._add_at_cursor)
        self.sequence_button.clicked.connect(self._add_sequence)
        self.edit_button.clicked.connect(self._edit_selected)
        self.remove_button.clicked.connect(self._remove_selected)
        self.segments.itemDoubleClicked.connect(lambda _: self._edit_selected())
        self.segments.itemSelectionChanged.connect(self._update_buttons)
        self.set_bounds(0.0, 0.0)

    # state

    def trim(self) -> Trim:
        return self._trim

    def set_bounds(self, lo: float, hi: float) -> None:
        """The recording's time span: the range the times can take. Nothing to edit without a recording."""
        self._lo, self._hi = lo, hi
        for spin in (self.start_spin, self.end_spin):
            spin.blockSignals(True)
            spin.setRange(lo, hi)
            spin.blockSignals(False)
        self.setEnabled(hi > lo)
        self._refresh()

    def set_trim(self, trim: Trim, quiet: bool = False) -> None:
        self._trim = trim
        self._refresh()
        if not quiet:
            self.changed.emit(self._trim)

    def _clamped(self, t: float) -> float:
        return min(max(t, self._lo), self._hi)

    def _refresh(self) -> None:
        trim = self._trim
        for check, spin, value, default in ((self.start_check, self.start_spin, trim.start, self._lo),
                                            (self.end_check, self.end_spin, trim.end, self._hi)):
            for w in (check, spin):
                w.blockSignals(True)
            check.setChecked(value is not None)
            spin.setValue(self._clamped(value) if value is not None else default)
            spin.setEnabled(value is not None)
            for w in (check, spin):
                w.blockSignals(False)
        self.start_cursor.setEnabled(trim.start is not None)
        self.end_cursor.setEnabled(trim.end is not None)
        selected = self.segments.currentRow()
        self.segments.blockSignals(True)
        self.segments.clear()
        for a, b in trim.exclude:
            self.segments.addItem(f"{a:.2f} – {b:.2f} s   ({b - a:.1f} s)")
        if 0 <= selected < self.segments.count():
            self.segments.setCurrentRow(selected)
        self.segments.blockSignals(False)
        if trim.active and self._hi > self._lo:
            kept = sum(b - a for a, b in trim.kept_spans(self._lo, self._hi))
            self.summary.setText(f"<b>Exports {kept:.1f} s</b> of the recording's {self._hi - self._lo:.1f} s")
        else:
            self.summary.setText("Exports the whole recording.")
        self._update_buttons()

    def _update_buttons(self) -> None:
        has = self.segments.currentRow() >= 0
        self.edit_button.setEnabled(has)
        self.remove_button.setEnabled(has)
        self.sequence_button.setEnabled(self.sequence_span() is not None)

    def refresh_buttons(self) -> None:
        """Call when the calibration overlay is turned on or off."""
        self._update_buttons()

    def _emit(self, trim: Trim) -> None:
        self.set_trim(trim)

    # edits

    def _start_toggled(self, on: bool) -> None:
        trim = self._trim
        self._emit(Trim(self._clamped(self.cursor_time()) if on else None, trim.end, trim.exclude))

    def _end_toggled(self, on: bool) -> None:
        trim = self._trim
        self._emit(Trim(trim.start, self._clamped(self.cursor_time()) if on else None, trim.exclude))

    def _edge_edited(self) -> None:
        trim = self._trim
        start = self.start_spin.value() if self.start_check.isChecked() else None
        end = self.end_spin.value() if self.end_check.isChecked() else None
        self._emit(Trim(start, end, trim.exclude))

    def _with_segment(self, a: float, b: float) -> None:
        trim = self._trim
        self._emit(Trim(trim.start, trim.end, list(trim.exclude) + [(a, b)]))

    def _add_at_cursor(self) -> None:
        a = self._clamped(self.cursor_time())
        b = self._clamped(a + DEFAULT_SEGMENT)
        if b - a < 0.5:   # at the end of the recording: leave out the stretch before the cursor
            a = self._clamped(b - DEFAULT_SEGMENT)
        self._with_segment(a, b)

    def _add_sequence(self) -> None:
        span = self.sequence_span()
        if span is not None:
            self._with_segment(self._clamped(span[0]), self._clamped(span[1]))

    def _edit_selected(self) -> None:
        row = self.segments.currentRow()
        if not 0 <= row < len(self._trim.exclude):
            return
        a, b = self._trim.exclude[row]
        dialog = SegmentDialog(a, b, self)
        if dialog.exec() == QDialog.Accepted:
            segments = list(self._trim.exclude)
            segments[row] = dialog.segment()
            self._emit(Trim(self._trim.start, self._trim.end, segments))

    def _remove_selected(self) -> None:
        row = self.segments.currentRow()
        if 0 <= row < len(self._trim.exclude):
            segments = list(self._trim.exclude)
            del segments[row]
            self._emit(Trim(self._trim.start, self._trim.end, segments))
