"""The icon system: every icon the app names has its file, and draws in the colour it is asked for."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6.QtSvg")
pytest.importorskip("PySide6.QtWidgets")
pytestmark = pytest.mark.usefixtures("isolated_qsettings")

from PySide6.QtWidgets import QApplication  # noqa: E402

from cwtool.gui import icons  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def drawn_colours(pixmap):
    """The colour of the strokes of a pixmap: the mean of its mostly opaque pixels, as (r, g, b)."""
    image = pixmap.toImage()
    pixels = [image.pixelColor(x, y) for x in range(image.width()) for y in range(image.height())]
    solid = [(c.red(), c.green(), c.blue()) for c in pixels if c.alpha() > 200]
    assert solid, "nothing was drawn"
    return tuple(round(sum(ch) / len(solid)) for ch in zip(*solid))


def close(a, b, tolerance=6):
    return all(abs(x - y) <= tolerance for x, y in zip(a, b))


def test_every_named_icon_has_a_clean_svg_file():
    assert len(set(icons.NAMES)) == len(icons.NAMES)
    for name in icons.NAMES:
        text = (icons.ICON_DIR / f"{name}.svg").read_text()
        assert "currentColor" in text and "<svg" in text, name           # recolourable
        assert "<script" not in text and "href" not in text, name         # nothing but shapes
    assert (icons.ICON_DIR / "LICENSE-tabler-icons.txt").read_text().startswith("MIT License")
    stray = {p.stem for p in icons.ICON_DIR.glob("*.svg")} - set(icons.NAMES)
    assert not stray, f"icon files nobody names: {stray}"


def test_an_icon_is_drawn_in_the_colour_asked_for_and_in_high_resolution(app):
    pm = icons.pixmap("database", "#E32400", 24)
    assert (pm.width(), pm.height()) == (48, 48) and pm.devicePixelRatio() == 2.0   # twice the size, for high-DPI
    assert close(drawn_colours(pm), (0xE3, 0x24, 0x00))
    assert close(drawn_colours(icons.pixmap("database", "#222222", 24)), (0x22, 0x22, 0x22))
    assert icons.pixmap("database", "#222222", 24) is icons.pixmap("database", "#222222", 24)    # cached


def test_icon_states_and_unknown_names(app):
    from PySide6.QtCore import QSize
    from PySide6.QtGui import QIcon

    ic = icons.icon("target", 24, checked_on_highlight=True)
    off = ic.pixmap(QSize(24, 24), QIcon.Normal, QIcon.Off)
    on = ic.pixmap(QSize(24, 24), QIcon.Normal, QIcon.On)
    assert not close(drawn_colours(off), drawn_colours(on), 20)      # a selected tab's icon takes the highlighted colour
    assert not close(drawn_colours(ic.pixmap(QSize(24, 24), QIcon.Disabled, QIcon.Off)), drawn_colours(off), 20)
    with pytest.raises(FileNotFoundError, match="No icon named 'nope'"):
        icons.icon("nope")


def test_the_windows_use_the_icons(app):
    from cwtool.gui.main_window import MainWindow
    from cwtool.logger.gui import LoggerWindow

    w = MainWindow()
    assert all(not b.icon().isNull() for b in w.rail._buttons) and len(w.rail._buttons) == 4
    assert all(not a.icon().isNull() for a in (w.open_action, w.load_params_action, w.save_params_action,
                                              w.export_action))
    assert not w.preview_holder.pop_button.icon().isNull() and not w.preview_holder.hide_button.icon().isNull()
    w.preview_holder.set_open(False)
    assert w.preview_holder.hide_button.text() == "Show"
    w.close()
    lw = LoggerWindow()
    adds = [b for b in lw.findChildren(type(w.analyse_button)) if b.toolTip().startswith("Add a")]
    assert len(adds) == 4 and all(not b.icon().isNull() for b in adds)
    lw.close()
