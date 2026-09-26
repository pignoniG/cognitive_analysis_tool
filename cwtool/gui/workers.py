"""Background work for the GUI."""

from __future__ import annotations

import traceback

from PySide6.QtCore import QThread, Signal


class Task(QThread):
    """Runs ``fn(progress, cancelled)`` in a thread. ``progress`` takes a
    fraction in [0, 1]; ``cancelled`` returns True once :meth:`cancel` is called."""

    progressed = Signal(float)
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self._fn = fn
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def is_cancelled(self) -> bool:
        return self._cancel

    def run(self) -> None:
        try:
            result = self._fn(self.progressed.emit, self.is_cancelled)
        except Exception as e:  # reported to the user, not raised in the thread
            self.failed.emit(f"{e}\n\n{traceback.format_exc()}")
        else:
            self.succeeded.emit(result)
