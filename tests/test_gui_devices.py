"""Every eye tracker through the app: the opening steps finish, the side column's pages fit it (nothing clipped on the
right, since the column does not scroll sideways) and the gaze correction opens."""

import time

import pytest
from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QAbstractButton, QApplication, QLabel, QWidget

from cwtool.gui.main_window import MainWindow


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def wait_for(app, condition, timeout=60):
    end = time.time() + timeout
    while not condition() and time.time() < end:
        app.processEvents()
        time.sleep(0.01)
    return condition()


def _recording(device, tmp_path):
    from conftest import write_core_recording, write_neon_recording, write_tobii_g3_recording, write_varjo_recording
    from test_neon import FRAME_TIMES, GRAYS
    if device == "varjo":
        return write_varjo_recording(tmp_path / "v", [128, 255, 0, 128, 64, 200, 90, 128], pupil_mm=3.0)
    if device == "pupil_core":
        return write_core_recording(tmp_path / "c", GRAYS, FRAME_TIMES)
    if device == "pupil_neon":
        return write_neon_recording(tmp_path / "n", GRAYS, FRAME_TIMES)
    if device == "tobii_g3":
        return write_tobii_g3_recording(tmp_path / "t", GRAYS)
    from test_neon_xr import _xr_recording
    return _xr_recording(tmp_path)[0]


def _clipped(page: QWidget, viewport: QWidget) -> list[str]:
    """Visible buttons and labels whose right edge is past the column's."""
    out = []
    for child in page.findChildren(QWidget):
        if not child.isVisibleTo(page) or not isinstance(child, (QAbstractButton, QLabel)):
            continue
        right = child.mapTo(viewport, QPoint(child.width(), 0)).x()
        if right > viewport.width() + 1:
            text = child.text() if hasattr(child, "text") else ""
            out.append(f"{type(child).__name__} {text[:40]!r} ends at {right} > {viewport.width()}")
    return out


@pytest.mark.parametrize("device", ["varjo", "pupil_core", "pupil_neon", "tobii_g3", "pupil_neon_xr"])
def test_each_tracker_opens_fits_its_column_and_has_the_gaze_correction(app, tmp_path, device):
    w = MainWindow()
    w.resize(1400, 900)
    w.show()
    w.main_split.setSizes([1, 1000])                    # the side column as narrow as the window allows
    try:
        w.open_recording(_recording(device, tmp_path))
        assert wait_for(app, lambda: w.open_panel.running() is None and w.recording is not None
                        and (w.result is not None or "failed" in w.open_panel.states.values()))
        assert w.recording.device == device
        assert w.result is not None, w.open_panel.states
        assert all(w.open_panel.states[k] == "done" for k in ("read", "video", "gaze", "analyse", "align", "result"))
        assert not w.open_panel.isVisibleTo(w) and w.gaze_window is None   # no gaze check: not asked
        for i in range(w.pages.count()):
            w.rail.set_current(i)
            app.processEvents()
            scroll = w.pages.widget(i)
            assert scroll.widget().minimumSizeHint().width() <= scroll.viewport().width(), f"page {i}"
            assert not _clipped(scroll.widget(), scroll.viewport()), (i, _clipped(scroll.widget(), scroll.viewport()))
        w.rail.set_current(0)
        assert w.gaze_window_button.isEnabled()
        w.gaze_window_button.click()
        assert wait_for(app, lambda: w.gaze_window is not None)
        g = w.gaze_window
        app.processEvents()
        assert g.minimumSizeHint().width() <= g.width() and g.minimumSizeHint().height() <= g.height()
        assert g.image.pixmap() is not None and not g.image.pixmap().isNull()      # a frame is drawn
        g.reject()
        app.processEvents()
        assert w.gaze_window is None and w.result is not None                     # cancelled: nothing changes
    finally:
        w.close()
