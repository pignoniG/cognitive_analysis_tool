"""The app's icons: Tabler outline icons (MIT, see icons/LICENSE-tabler-icons.txt), stored as SVG files.

``icon("database")`` is a QIcon drawn in the text colour of the current palette, crisp at any scale (it is
rendered at twice the size for high-DPI screens), with the colours of the disabled state and, for checkable
buttons on a highlighted background, of the checked state. Each icon is a file in ``icons/``; to add one, copy its
SVG there from https://tabler.io/icons (outline style) and name it in :data:`NAMES`.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QIcon, QPainter, QPalette, QPixmap
from PySide6.QtSvg import QSvgRenderer

ICON_DIR = Path(__file__).with_name("icons")
# Every icon the app uses (a test checks that each has its file).
NAMES = (
    "database", "adjustments-horizontal", "target", "file-export",              # the tabs: Data, Params, Calibrate, Export
    "folder-open", "file-import", "device-floppy",                              # open, load, save
    "eye", "eye-off", "external-link", "list-details",                          # the preview: show, hide, pop out, values
    "alert-triangle",                                                           # warnings
    "sun", "heartbeat", "activity", "flask", "plus",                            # the logger: sensors and adding one
)
DEVICE_PIXEL_RATIO = 2.0


@lru_cache(maxsize=None)
def _svg(name: str) -> str:
    path = ICON_DIR / f"{name}.svg"
    if not path.exists():
        raise FileNotFoundError(f"No icon named {name!r}: expected {path}")
    return path.read_text(encoding="utf-8")


@lru_cache(maxsize=512)
def pixmap(name: str, colour: str, size: int = 24) -> QPixmap:
    """The icon as a pixmap of ``size`` logical pixels, its stroke in ``colour`` (any Qt colour name)."""
    renderer = QSvgRenderer(QByteArray(_svg(name).replace("currentColor", colour).encode("utf-8")))
    pm = QPixmap(int(size * DEVICE_PIXEL_RATIO), int(size * DEVICE_PIXEL_RATIO))
    pm.fill(Qt.transparent)
    pm.setDevicePixelRatio(DEVICE_PIXEL_RATIO)
    painter = QPainter(pm)
    renderer.render(painter, QRectF(0, 0, size, size))
    painter.end()
    return pm


def icon(name: str, size: int = 24, checked_on_highlight: bool = False) -> QIcon:
    """A QIcon for ``name`` in the colours of the current palette. With ``checked_on_highlight`` the checked
    state uses the colour of text on a highlighted background (a tab button that is selected)."""
    palette = QGuiApplication.palette()
    normal = palette.color(QPalette.Active, QPalette.ButtonText).name()
    disabled = palette.color(QPalette.Disabled, QPalette.ButtonText).name()
    on = palette.color(QPalette.Active, QPalette.HighlightedText).name() if checked_on_highlight else normal
    result = QIcon()
    result.addPixmap(pixmap(name, normal, size), QIcon.Normal, QIcon.Off)
    result.addPixmap(pixmap(name, on, size), QIcon.Normal, QIcon.On)
    result.addPixmap(pixmap(name, on, size), QIcon.Active, QIcon.On)
    result.addPixmap(pixmap(name, disabled, size), QIcon.Disabled, QIcon.Off)
    return result


def tinted(name: str, colour: str, size: int = 24) -> QIcon:
    """The icon in one fixed colour, for a signal such as a warning (the palette's colour is not used)."""
    return QIcon(pixmap(name, QColor(colour).name(), size))
