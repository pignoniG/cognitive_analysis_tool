"""Building blocks of the analysis window's left column: the rail of workflow tabs, the pills inside a tab, the
numbered steps of the calibration, and the holder that lets the video preview collapse or float."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QButtonGroup, QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy,
                               QStackedWidget, QToolButton, QVBoxLayout, QWidget)

RAIL_STYLE = (
    "QToolButton { border: none; border-radius: 6px; padding: 8px 2px; font-size: 12px; }"
    "QToolButton:hover { background: palette(midlight); }"
    "QToolButton:checked { background: palette(highlight); color: palette(highlighted-text); font-weight: bold; }"
    "QToolButton[alert=\"true\"] { color: #E32400; }"
    "QToolButton[alert=\"true\"]:checked { color: palette(highlighted-text); }")

PILL_STYLE = (
    "QPushButton { border: 1px solid transparent; border-radius: 12px; padding: 4px 4px; font-size: 12px; }"
    "QPushButton:hover { background: palette(midlight); }"
    "QPushButton:checked { background: palette(base); border: 1px solid palette(highlight); font-weight: bold; }")


class Rail(QWidget):
    """A vertical column of exclusive buttons, one per workflow tab."""

    changed = Signal(int)

    def __init__(self, titles, parent=None):
        super().__init__(parent)
        self.setFixedWidth(70)
        self._titles = list(titles)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 6, 4, 6)
        layout.setSpacing(4)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons: list[QToolButton] = []
        for i, title in enumerate(self._titles):
            button = QToolButton()
            button.setText(title)
            button.setCheckable(True)
            button.setToolButtonStyle(Qt.ToolButtonTextOnly)
            button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            button.setMinimumHeight(54)
            button.setStyleSheet(RAIL_STYLE)
            button.setToolTip(f"{title} (Ctrl+{i + 1})")
            self._group.addButton(button, i)
            layout.addWidget(button)
            self._buttons.append(button)
        layout.addStretch(1)
        self._buttons[0].setChecked(True)
        self._group.idClicked.connect(self.changed)

    def current(self) -> int:
        return self._group.checkedId()

    def set_current(self, index: int) -> None:
        if 0 <= index < len(self._buttons) and index != self.current():
            self._buttons[index].setChecked(True)
            self.changed.emit(index)

    def mark(self, index: int, on: bool, tip: str = "") -> None:
        """Flag a tab that needs attention: a red dot under its name and a tip."""
        button = self._buttons[index]
        button.setText(self._titles[index] + ("\n●" if on else ""))
        button.setProperty("alert", on)
        button.style().unpolish(button)
        button.style().polish(button)
        button.setToolTip(f"{self._titles[index]} (Ctrl+{index + 1})" + (f"\n{tip}" if on and tip else ""))


class Pills(QWidget):
    """A row of pill buttons choosing one of several pages (the second level of a tab)."""

    changed = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._row = QHBoxLayout()
        self._row.setSpacing(2)
        self._stack = QStackedWidget()
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._titles: list[str] = []
        self._buttons: list[QPushButton] = []
        layout.addLayout(self._row)
        layout.addWidget(self._stack, 1)
        self._group.idClicked.connect(self._chosen)

    def add(self, title: str, page: QWidget) -> int:
        index = len(self._buttons)
        button = QPushButton(title)
        button.setCheckable(True)
        button.setStyleSheet(PILL_STYLE)
        button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._group.addButton(button, index)
        self._row.addWidget(button)
        self._stack.addWidget(page)
        self._titles.append(title)
        self._buttons.append(button)
        if index == 0:
            button.setChecked(True)
        return index

    def _chosen(self, index: int) -> None:
        self._stack.setCurrentIndex(index)
        self.changed.emit(index)

    def current(self) -> int:
        return self._stack.currentIndex()

    def set_current(self, index: int) -> None:
        if 0 <= index < len(self._buttons):
            self._buttons[index].setChecked(True)
            self._stack.setCurrentIndex(index)

    def mark(self, index: int, on: bool) -> None:
        """A dot after the name: something in this page differs from the defaults."""
        self._buttons[index].setText(self._titles[index] + (" •" if on else ""))
        self._buttons[index].setToolTip("Differs from the defaults" if on else "")

    def page(self, index: int) -> QWidget:
        return self._stack.widget(index)


class Step(QFrame):
    """A numbered, collapsible step with a one-line result under its title once it has been done."""

    def __init__(self, number: int, title: str, content: QWidget, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.StyledPanel)
        self.header = QToolButton()
        self.header.setText(f"{number}.  {title}")
        self.header.setCheckable(True)
        self.header.setChecked(True)
        self.header.setArrowType(Qt.DownArrow)
        self.header.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.header.setStyleSheet("QToolButton { border: none; font-weight: bold; padding: 2px 0; }")
        self.header.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.header.toggled.connect(self.set_expanded)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.summary.setStyleSheet("color: palette(dark);")
        self.summary.hide()
        self.content = content
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 8)
        layout.addWidget(self.header)
        layout.addWidget(self.summary)
        layout.addWidget(content)

    def set_expanded(self, expanded: bool) -> None:
        self.header.blockSignals(True)
        self.header.setChecked(expanded)
        self.header.blockSignals(False)
        self.header.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
        self.content.setVisible(expanded)

    def set_summary(self, text: str) -> None:
        self.summary.setText(text)
        self.summary.setVisible(bool(text))


class PreviewHolder(QWidget):
    """The video preview under the tabs: a title bar with Values, Pop out and Hide, and the preview itself. Hidden
    or popped out, it takes no room in the column."""

    open_changed = Signal(bool)

    def __init__(self, preview: QWidget, parent=None):
        super().__init__(parent)
        self.preview = preview
        self._window: QDialog | None = None
        title = QLabel("Video preview")
        title.setStyleSheet("font-weight: bold;")
        self.values_button = QToolButton()
        self.values_button.setText("Values")
        self.values_button.setCheckable(True)
        self.values_button.setToolTip("Show the colours and luminance measured at the cursor")
        self.pop_button = QToolButton()
        self.pop_button.setText("Pop out")
        self.pop_button.setToolTip("Show the preview in a window of its own")
        self.hide_button = QToolButton()
        self.hide_button.setText("Hide")
        self.hide_button.setToolTip("Hide the preview (P)")
        header = QHBoxLayout()
        header.setContentsMargins(6, 2, 6, 0)
        header.addWidget(title)
        header.addStretch(1)
        for b in (self.values_button, self.pop_button, self.hide_button):
            b.setToolButtonStyle(Qt.ToolButtonTextOnly)
            b.setStyleSheet("QToolButton { border: none; padding: 2px 6px; }")
            header.addWidget(b)
        self.body = QWidget()
        self._body_layout = QVBoxLayout(self.body)
        self._body_layout.setContentsMargins(0, 0, 0, 0)
        self._body_layout.addWidget(preview)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addLayout(header)
        layout.addWidget(self.body, 1)
        self.values_button.toggled.connect(self._values_toggled)
        self.pop_button.clicked.connect(self.toggle_pop_out)
        self.hide_button.clicked.connect(lambda: self.set_open(not self._open))
        self._open = True
        self._values_toggled(False)

    def _values_toggled(self, on: bool) -> None:
        self.preview.info.setVisible(on)

    def is_open(self) -> bool:
        return self._open

    def set_open(self, open_: bool) -> None:
        """Show or hide the preview in the column (ignored while it is in its own window)."""
        if self._window is not None:
            return
        self._open = open_
        self.body.setVisible(open_)
        self.hide_button.setText("Hide" if open_ else "Show")
        self.hide_button.setToolTip("Hide the preview (P)" if open_ else "Show the preview (P)")
        self.open_changed.emit(open_)

    def toggle_pop_out(self) -> None:
        if self._window is not None:
            self._window.close()
            return
        window = QDialog(self.window())
        window.setWindowTitle("Video preview")
        window.setWindowFlag(Qt.Tool, True)
        window.resize(900, 640)
        layout = QVBoxLayout(window)
        layout.addWidget(self.preview)
        window.finished.connect(self._dock_back)
        self._window = window
        self.body.hide()
        self.pop_button.setText("Dock back")
        self.hide_button.setEnabled(False)
        self.open_changed.emit(False)
        window.show()

    def _dock_back(self) -> None:
        self._window = None
        self._body_layout.addWidget(self.preview)
        self.body.setVisible(self._open)
        self.pop_button.setText("Pop out")
        self.hide_button.setEnabled(True)
        self.open_changed.emit(self._open)
