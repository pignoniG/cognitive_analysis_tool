"""Plain-language advice for errors, the gestures list, and the Help menu."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

from cwtool.gui import errors  # noqa: E402


@pytest.mark.parametrize("text, word", [
    ("No module named 'neurokit2'", "installed"),
    ("[Errno 2] No such file or directory: 'x.mp4'", "missing"),
    ("PermissionError: [Errno 13] Permission denied: '/x'", "permission"),
    ("cv2.error: could not open video", "video"),
    ("numpy.core._exceptions._ArrayMemoryError: Unable to allocate 4 GiB", "memory"),
    ("json.decoder.JSONDecodeError: Expecting value", "format"),
    ("OSError: [Errno 28] No space left on device", "disk"),
])
def test_known_errors_get_advice(text, word):
    assert word in errors.advice(text).lower()


def test_an_unknown_error_gets_the_general_advice_and_the_message_is_split_from_its_traceback():
    assert errors.advice("something odd") == errors.FALLBACK
    assert errors.split_message("It broke\n\nTraceback…\nline 2") == ("It broke", "Traceback…\nline 2")
    assert errors.split_message("Only a headline") == ("Only a headline", "")


def test_the_gestures_list_names_every_gesture_and_shortcut_the_window_has():
    html = errors.gestures_html()
    for word in ("Pan", "Zoom to a rectangle", "right-click", "Ctrl+0", "Ctrl+E", "Ctrl+H", "Ctrl+1"):
        assert word in html


def test_the_help_menu_and_the_shortcuts_exist(isolated_qsettings):
    from PySide6.QtGui import QKeySequence
    from PySide6.QtWidgets import QApplication

    from cwtool.gui.main_window import MainWindow

    QApplication.instance() or QApplication([])
    w = MainWindow()
    assert [a.text() for a in w.help_menu.actions()][0].startswith("Gestures")
    assert w.export_action.shortcut() == QKeySequence("Ctrl+E")
    assert w.hrv_button.shortcut() == QKeySequence("Ctrl+H") and w.plots.zoom_button.shortcut() == QKeySequence("Z")
    w.close()
