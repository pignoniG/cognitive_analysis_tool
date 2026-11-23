"""The steps of opening a recording, shown in the plot area until the first result: each step ticked with a line on what
it found, the video analysis with its percentage, frames, elapsed time and time left, and a failure at its step."""

from __future__ import annotations

import time

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QGridLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout, QWidget

from cwtool import palette

STEPS = (("read", "Reading the recording"),
         ("video", "Finding the scene video"),
         ("analyse", "Analysing the video"),
         ("align", "Aligning and checking the gaze"),
         ("result", "Computing the result"))
MARKS = {"pending": "·", "running": "▸", "done": "✓", "failed": "✗", "skipped": "–", "cancelled": "■"}
OK_COLOUR = "#4b9a2a"


def clock(seconds: float) -> str:
    """m:ss, or h:mm:ss from an hour."""
    s = int(round(max(seconds, 0)))
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"


class OpenProgress(QWidget):
    """The steps of opening a recording. ``cancel_requested`` is emitted by its Cancel button."""

    cancel_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.addStretch(1)
        box = QWidget()
        box.setMaximumWidth(620)
        layout = QVBoxLayout(box)
        self.title = QLabel()
        self.title.setWordWrap(True)
        self.title.setStyleSheet("font-size: 15px; font-weight: bold;")
        layout.addWidget(self.title)
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(6)
        self.marks, self.names, self.details = {}, {}, {}
        for row, (key, name) in enumerate(STEPS):
            mark, label, detail = QLabel(), QLabel(name), QLabel()
            mark.setFixedWidth(16)
            mark.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
            detail.setWordWrap(True)
            detail.setTextInteractionFlags(Qt.TextSelectableByMouse)
            grid.addWidget(mark, 2 * row, 0)
            grid.addWidget(label, 2 * row, 1)
            if key == "analyse":                 # the bar above its line
                self.bar = QProgressBar()
                self.bar.setRange(0, 1000)
                self.bar.setTextVisible(False)
                below = QWidget()
                column = QVBoxLayout(below)
                column.setContentsMargins(0, 0, 0, 0)
                column.addWidget(self.bar)
                column.addWidget(detail)
                grid.addWidget(below, 2 * row + 1, 1)
            else:
                grid.addWidget(detail, 2 * row + 1, 1)
            self.marks[key], self.names[key], self.details[key] = mark, label, detail
        grid.setColumnStretch(1, 1)
        layout.addLayout(grid)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.cancel_requested)
        layout.addWidget(self.cancel_button, 0, Qt.AlignLeft)
        outer.addWidget(box, 0, Qt.AlignHCenter)
        outer.addStretch(2)
        self.states: dict = {}
        self._started = time.monotonic()
        self._frames = None
        self.begin("")

    # Steps

    def begin(self, title: str, done: tuple = ()) -> None:
        """Start again with every step pending, except those in ``done`` (key, detail), already ticked."""
        self.title.setText(title)
        self.states = {}
        for key, _ in STEPS:
            self._set(key, "pending", "")
        for key, detail in done:
            self._set(key, "done", detail)
        self.bar.hide()
        self.cancel_button.hide()
        self._frames = None

    def start(self, key: str, detail: str = "", cancellable: bool = False) -> None:
        self._set(key, "running", detail)
        self.cancel_button.setVisible(cancellable)
        self._started = time.monotonic()

    def done(self, key: str, detail: str = "") -> None:
        self._set(key, "done", detail)
        if key == "analyse":
            self.bar.hide()
        self.cancel_button.hide()

    def failed(self, key: str, detail: str) -> None:
        self._set(key, "failed", detail)
        for k, _ in STEPS:                       # what came after it does not happen
            if self.states.get(k) in ("pending", "running") and k != key:
                self._set(k, "skipped", "")
        self.bar.hide()
        self.cancel_button.hide()

    def cancelled(self, detail: str) -> None:
        """The running step was cancelled."""
        for key, _ in STEPS:
            if self.states.get(key) == "running":
                self._set(key, "cancelled", detail)
            elif self.states.get(key) == "pending":
                self._set(key, "skipped", "")
        self.bar.hide()
        self.cancel_button.hide()

    def running(self) -> str | None:
        """The key of the step running now."""
        return next((k for k, _ in STEPS if self.states.get(k) == "running"), None)

    # The video analysis

    def start_analysis(self, frames: int | None) -> None:
        """The video analysis started; ``frames`` is the video's frame count when known."""
        self._frames = frames if frames and frames > 0 else None
        self.start("analyse", "starting…", cancellable=True)
        self.bar.setValue(0)
        self.bar.show()

    def set_fraction(self, fraction: float) -> None:
        """Progress of the video analysis (0–1): the bar, and the percentage, frames, elapsed time and time left."""
        fraction = min(max(fraction, 0.0), 1.0)
        self.bar.setValue(int(fraction * 1000))
        elapsed = time.monotonic() - self._started
        parts = [f"{fraction:.0%}"]
        if self._frames:
            parts.append(f"{int(fraction * self._frames):,} of {self._frames:,} frames".replace(",", " "))
        parts.append(f"{clock(elapsed)} elapsed")
        if fraction >= 0.03 and elapsed > 2:
            parts.append(f"about {clock(elapsed * (1 - fraction) / fraction)} left")
        self.details["analyse"].setText(" · ".join(parts))
        self.details["analyse"].show()
        self.names["analyse"].setText(f"Analysing the video ({fraction:.0%})")

    def _set(self, key: str, state: str, detail: str) -> None:
        self.states[key] = state
        colour = {"done": OK_COLOUR, "failed": palette.WARNING, "cancelled": palette.WARNING}.get(state, "")
        self.marks[key].setText(MARKS[state])
        self.marks[key].setStyleSheet(f"color: {colour}; font-weight: bold;" if colour else "")
        self.names[key].setStyleSheet("font-weight: bold;" if state == "running" else
                                      ("color: gray;" if state in ("pending", "skipped") else ""))
        if key == "analyse" and state != "running":
            self.names[key].setText(dict(STEPS)[key])
        self.details[key].setText(detail)
        self.details[key].setStyleSheet(f"color: {palette.WARNING};" if state == "failed" else "color: gray;")
        self.details[key].setVisible(bool(detail))
