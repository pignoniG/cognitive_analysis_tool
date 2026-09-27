import os
import time

import numpy as np
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

    p = w.params_panel.params()
    p.sensitivity = 2.5
    w.params_panel.set_params(p)
    w._params_path = tmp_path / "p.json"
    w.save_params()
    import json
    saved = json.loads((tmp_path / "p.json").read_text())
    assert saved["sensitivity"] == 2.5 and "l_max" not in saved     # display photometry is separate

    from cwtool.params import DisplayPhotometry
    DisplayPhotometry("varjo", 0.05, 150.0, 2.4, "test datasheet").save(tmp_path / "xr4.json")
    w.load_display(tmp_path / "xr4.json")
    assert w.params_panel.params().l_max == 150.0 and w.params_panel.params().sensitivity == 2.5
    w.params_panel.set_params(Parameters(l_max=10.0))
    w.params_panel.set_params(Parameters.load(tmp_path / "p.json", base=w.params_panel.params()))
    assert w.params_panel.params().l_max == 10.0 and w.params_panel.params().sensitivity == 2.5
    w._settings.remove("display_photometry/varjo")
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


def test_loaded_sequence_drives_overlay_and_rms(app, varjo_folder, tmp_path):
    from cwtool import calibration
    w = MainWindow()
    w.open_recording(varjo_folder)
    assert wait_for(app, lambda: w.result is not None)
    (tmp_path / "s.csv").write_text("time,r,g,b\n0,0,0,0\n1,128,128,128\n2,255,255,255\n")
    w.set_sequence(calibration.load_sequence(tmp_path / "s.csv"))
    w.sequence_check.setChecked(True)
    w.sequence_start.setValue(0)
    assert len(w.plots._sequence_items) == 3
    assert "3 steps" in w.sequence_label.text() and w.sequence_rms.text().endswith("mm")
    w.close()


def test_options_follow_the_recording(app, varjo_folder, tmp_path):
    from conftest import write_neon_recording
    from test_neon import FRAME_TIMES, GRAYS
    w = MainWindow()
    shown = w.params_panel.is_shown
    assert shown("lux_gain") and shown("l_max")          # nothing loaded: everything

    w.open_recording(varjo_folder)
    assert wait_for(app, lambda: w.result is not None)
    assert shown("l_max") and shown("field_radius") and not w.cal_box.isHidden()
    assert not shown("lux_gain") and not shown("camera_exposure")

    w.open_recording(write_neon_recording(tmp_path / "lux", GRAYS, FRAME_TIMES, lux=lambda t: 300.0))
    assert wait_for(app, lambda: w.result is not None and w.recording.device == "pupil_neon")
    assert shown("lux_gain") and shown("gamma") and w.cal_box.isHidden()
    assert not shown("l_max") and not shown("camera_exposure") and not shown("field_radius")

    w.open_recording(write_neon_recording(tmp_path / "nolux", GRAYS, FRAME_TIMES))
    assert wait_for(app, lambda: w.result is not None and w.recording.lux_values is None)
    assert shown("camera_exposure") and shown("l_max") and not shown("camera_white") and not shown("lux_gain")
    p = w.params_panel.params()
    p.camera_exposure = "fixed"
    w.params_panel.set_params(p)
    assert shown("camera_white") and not shown("l_max")
    w.close()


def test_view_fits_the_data(app, varjo_folder, tmp_path):
    from conftest import write_neon_recording
    from test_neon import FRAME_TIMES, GRAYS
    from cwtool.gui.plots import data_range
    w = MainWindow()
    w.open_recording(varjo_folder)
    assert wait_for(app, lambda: w.result is not None)
    vb = w.plots.pupil.vb
    in_view = lambda: (vb.viewRange()[0][0] <= w.result.time[0] and vb.viewRange()[0][1] >= w.result.time[-1]
                       and vb.viewRange()[1][0] <= np.nanmedian(w.result.measured) <= vb.viewRange()[1][1])
    assert in_view()

    # Overlays far from the data do not stretch the view.
    w.sequence_check.setChecked(True)
    w.sequence_start.setValue(500)
    w.fit_action.trigger()
    assert vb.viewRange()[0][1] < 100 and in_view()

    # Once the user pans away, parameter changes keep the view; Fit view brings the data back.
    vb.translateBy(x=1000, y=50)
    w.plots._moved_by_user()
    w.params_panel.set_params(Parameters(l_max=500))
    assert wait_for(app, lambda: w.result.expected_white != 0) and not in_view()
    w.fit_action.trigger()
    assert in_view()

    # A new recording is always fitted, even after panning.
    vb.translateBy(x=1000)
    w.plots._moved_by_user()
    w.open_recording(write_neon_recording(tmp_path / "neon", GRAYS, FRAME_TIMES))
    assert wait_for(app, lambda: w.result is not None and w.recording.device == "pupil_neon")
    assert in_view() and vb.viewRange()[0][1] < 10
    w.close()

    assert data_range([1.0, np.nan, 3.0]) == pytest.approx((1.0, 3.0))
    assert data_range([np.nan]) == (None, None)
    assert data_range(np.r_[np.full(999, 3.0), 50.0], trim=0.5) == pytest.approx((2.9, 3.1))  # trimmed spike


def test_light_response_dialog(app):
    import numpy as np
    from cwtool.gui.photometry_dialog import PhotometryDialog
    from cwtool.photometry import PhotometryFit, StepLevel
    steps = [StepLevel(f"Gray {v}", (v, v, v), i * 10.0, i * 10.0 + 10, 6 - v / 60, 0.03, i % 3 > 0,
                       np.zeros((9, 3))) for i, v in enumerate((0, 73, 146, 255))]
    fit = PhotometryFit(Parameters(sensitivity=2.0), 2.0, (1.5, 2.7), (1.2, 0.9, 0.9), 2.2, 0.95, 0.2, steps,
                        np.linspace(6, 3, 4), np.linspace(6.1, 2.9, 4), np.linspace(6, 3, 4), np.full(4, 0.03),
                        0.3, 0.05, ["example note"])
    dialog = PhotometryDialog(fit)
    assert "×2" in dialog.findChildren(type(dialog.layout().itemAt(0).widget()))[0].text()
    dialog.close()


def test_light_sensitivity_button_applies_the_fit(app, varjo_folder, monkeypatch):
    from cwtool import calibration
    from cwtool.gui import photometry_dialog
    monkeypatch.setattr(photometry_dialog.PhotometryDialog, "exec", lambda self: True)
    w = MainWindow()
    w.open_recording(varjo_folder)
    assert wait_for(app, lambda: w.result is not None)
    steps = tuple(calibration.Step(i, i + 1.0, (g, g, g), f"Gray {g}") for i, g in enumerate((0, 128, 255, 64)))
    w.set_sequence(calibration.Sequence(steps, "test"))
    w.sequence_check.setChecked(True)
    w.sequence_start.setValue(0)
    assert w.light_button.isEnabled()
    before = w.params_panel.params()
    w.light_button.click()
    assert wait_for(app, lambda: w.params_panel.params() != before)
    assert w.params_panel.params().l_max == before.l_max     # the display photometry is not fitted
    w.close()
