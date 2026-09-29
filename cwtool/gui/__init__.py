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
    apply_palette(app)
    window = MainWindow()
    window.show()
    if len(argv) > 1:
        window.open_recording(Path(argv[1]))
    return app.exec()


def apply_palette(app) -> None:
    """Project accent for selections, focus, checked controls and links (see cwtool.palette)."""
    from PySide6.QtGui import QColor, QPalette

    from cwtool import palette

    pal = app.palette()
    for group in (QPalette.Active, QPalette.Inactive):
        pal.setColor(group, QPalette.Highlight, QColor(palette.ACCENT))
        pal.setColor(group, QPalette.HighlightedText, QColor("#ffffff"))
    pal.setColor(QPalette.Link, QColor(palette.ORANGE_4))
    pal.setColor(QPalette.LinkVisited, QColor(palette.ORANGE_4))
    app.setPalette(pal)
