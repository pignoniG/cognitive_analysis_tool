"""Qt desktop GUI. Start with ``cwtool-gui`` or ``python -m cwtool.gui``."""

from __future__ import annotations

import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    from PySide6.QtWidgets import QApplication

    from cwtool.gui.main_window import MainWindow

    argv = sys.argv if argv is None else argv
    app = QApplication(argv)
    app.setApplicationName("cwtool")
    window = MainWindow()
    window.show()
    if len(argv) > 1:
        window.open_recording(Path(argv[1]))
    return app.exec()
