import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6.QtWidgets")
pytest.importorskip("pyqtgraph")

from PySide6.QtWidgets import QApplication  # noqa: E402

from cwtool.gui.main_window import MainWindow  # noqa: E402
from cwtool.params import Parameters  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def wait_for(app, condition, timeout=30):
    end = time.time() + timeout
    while not condition() and time.time() < end:
        app.processEvents()
        time.sleep(0.01)
    return condition()


def test_open_analyse_and_retune(app, varjo_folder, tmp_path):
    w = MainWindow()
    w.open_recording(varjo_folder)
    assert wait_for(app, lambda: w.result is not None)
    assert (varjo_folder / "cwtool_video.csv").exists()

    before = w.result.expected_white
    p = w.params_panel.params()
    p.l_max = 2000
    w.params_panel.set_params(p)
    assert wait_for(app, lambda: w.result.expected_white < before)

    w.sequence_check.setChecked(True)
    w.sequence_start.setValue(0)
    assert w.sequence_rms.text().endswith("mm")

    w._params_path = tmp_path / "p.json"
    w.save_params()
    assert Parameters.load(tmp_path / "p.json").l_max == 2000
    w.close()


def test_panel_round_trips_parameters(app):
    from cwtool.gui.param_panel import ParameterPanel
    panel = ParameterPanel()
    p = Parameters(age=41, l_max=4250, gain_b=11.3, eye="right", eyes=1, dynamics=True)
    panel.set_params(p)
    assert panel.params() == p


def test_video_preview_follows_cursor(app, varjo_folder):
    w = MainWindow()
    w.open_recording(varjo_folder)
    assert wait_for(app, lambda: w.result is not None)
    w.plots.cursor_changed.emit(1.5)
    assert "frame 15" in w.preview.time_label.text()  # 10 fps test video
    import re
    fixation_r = int(re.search(r"fixation</span> RGB (\d+)", w.preview.info.text()).group(1))
    assert fixation_r == pytest.approx(128, abs=4)  # MJPG compression
    w.preview.next_button.click()
    assert "frame 16" in w.preview.time_label.text()
    assert w.plots.cursors[0].value() == pytest.approx(1.65)
    w.close()


def test_fit_button_applies_fitted_parameters(app, varjo_folder, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "exec", lambda self: QMessageBox.Apply)
    w = MainWindow()
    w.open_recording(varjo_folder)
    assert wait_for(app, lambda: w.result is not None)
    assert not w.fit_button.isEnabled()          # needs the sequence overlay
    w.sequence_check.setChecked(True)
    w.sequence_start.setValue(0)
    assert w.fit_button.isEnabled()
    w.fit_dynamics_check.setChecked(False)
    w.fit_button.click()
    assert wait_for(app, lambda: w.params_panel.params().alignment == "fixed")
    w.close()
