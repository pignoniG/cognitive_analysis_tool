from dataclasses import replace
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
    w.plots.cursors[0].setValue(1.5)                    # drag the bar
    assert "frame 15" in w.preview.time_label.text()  # 10 fps test video
    assert w.plots.cursors[1].value() == pytest.approx(1.5)
    assert wait_for(app, lambda: "fixation" in w.preview.info.text() and w.preview._pending is None)
    import re
    fixation_r = int(re.search(r"fixation</\w+> RGB (\d+)", w.preview.info.text()).group(1))
    assert fixation_r == pytest.approx(128, abs=4)  # MJPG compression
    w.preview.next_button.click()
    assert "frame 16" in w.preview.time_label.text()
    assert w.plots.cursors[0].value() == pytest.approx(1.65)
    w.close()


def test_fit_button_applies_fitted_parameters(app, varjo_folder, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    shown = []
    monkeypatch.setattr(QMessageBox, "exec", lambda self: shown.append(self.text()) or QMessageBox.Apply)
    w = MainWindow()
    w.open_recording(varjo_folder)
    assert wait_for(app, lambda: w.result is not None)
    assert not w.fit_button.isEnabled()          # needs the sequence overlay
    w.sequence_check.setChecked(True)
    w.sequence_start.setValue(0)
    assert w.fit_button.isEnabled()
    w.fit_dynamics_check.setChecked(False)
    w.fit_button.click()
    assert wait_for(app, lambda: bool(shown))
    assert "offset is not fitted" in shown[0]
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
    assert shown("l_max") and shown("field_radius") and not w.sequence_controls.isHidden()
    assert not shown("lux_gain") and not shown("camera_exposure")

    w.open_recording(write_neon_recording(tmp_path / "lux", GRAYS, FRAME_TIMES, lux=lambda t: 300.0))
    assert wait_for(app, lambda: w.result is not None and w.recording.device == "pupil_neon")
    assert shown("lux_gain") and shown("gamma") and not w.sequence_controls.isHidden()    # the lux fit
    assert w._cal_layout.isRowVisible(w.lux_fit_button) and not w._cal_layout.isRowVisible(w.light_button)
    assert not w.cal_box.isHidden() and w.cal_box.title() == "Calibration sequence" and shown("attack")
    assert not shown("l_max") and not shown("camera_exposure") and not shown("field_radius")

    w.open_recording(write_neon_recording(tmp_path / "nolux", GRAYS, FRAME_TIMES))
    assert wait_for(app, lambda: w.result is not None and w.recording.lux_values is None)
    assert w.sequence_controls.isHidden() and w.cal_box.title() == "Pupil dynamics"     # no lux log: dynamics only
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

    # Once the user pans away, parameter changes keep the view; Reset view brings the data back.
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


def test_analyse_button_becomes_reanalyse_and_reset_view_is_on_the_plots(app, varjo_folder):
    w = MainWindow()
    assert w.analyse_button.text() == "Analyse video"
    w.open_recording(varjo_folder)
    assert wait_for(app, lambda: w.result is not None)
    assert w.analyse_button.text() == "Reanalyse video" and w.analyse_button.isEnabled()
    assert w.cancel_button.isHidden()                  # nothing running
    w.analyse(use_cache=False)
    assert not w.cancel_button.isHidden()              # shown while the analysis runs
    assert wait_for(app, lambda: not (w._task and w._task.isRunning()))
    app.processEvents()
    assert w.cancel_button.isHidden()
    w.resize(1200, 800)
    w.show()
    app.processEvents()
    b = w.plots.reset_button
    assert b.isVisible() and b.x() + b.width() > w.plots.width() - 40 and b.y() < 30
    w.close()


def test_video_and_dynamics_settings_are_drop_downs_next_to_their_controls(app, varjo_folder):
    w = MainWindow()
    panel = w.params_panel
    video, dynamics = panel.video_section, panel.dynamics_section
    assert video.parent() is not None and video.parentWidget().title() == "Scene video"
    assert dynamics.parentWidget() is w.cal_box
    assert not video.is_expanded() and not dynamics.is_expanded()
    dynamics.header.click()
    assert dynamics.is_expanded() and not dynamics.content.isHidden()
    # Edits in a section reach the parameters like any other.
    p = replace(panel.params(), release=0.25, constriction_stages=2, l_max=80.0)
    panel.set_params(p)
    assert panel.params() == p
    # One switch: the dynamics settings are greyed out while it is off; the delay always applies.
    editors = panel._dynamics._editors
    panel.set_params(replace(p, dynamics=False))
    assert not editors["transient"].isEnabled() and not editors["attack"].isEnabled() and editors["delay"].isEnabled()
    editors["dynamics"].setChecked(True)
    assert editors["transient"].isEnabled() and editors["constriction_stages"].isEnabled()
    assert panel.params().dynamics
    w.close()


def test_preview_reads_the_same_frame_forward_as_by_seeking(app, varjo_folder):
    from cwtool import devices
    from cwtool.gui.video_preview import VideoPreview
    from cwtool.params import VideoSettings
    rec = devices.load(varjo_folder)
    forward, seeking = VideoPreview(), VideoPreview()
    for p in (forward, seeking):
        p.set_recording(rec, VideoSettings().for_recording(rec))
    for idx in (3, 5, 9, 2, 7):            # forward steps, then a step back (seek)
        a = forward._read(idx).copy()
        seeking._frame_cache = None
        assert np.array_equal(a, seeking._read(idx))


def test_a_frame_requested_while_scrubbing_does_not_override_later_actions(app, varjo_folder):
    w = MainWindow()
    w.open_recording(varjo_folder)
    assert wait_for(app, lambda: w.result is not None)
    preview = w.preview
    preview.request_time(1.5)                # dragged to frame 15, not drawn yet
    preview.next_button.click()              # steps from the bar's position, to frame 16
    for _ in range(5):
        app.processEvents()
    assert "frame 16" in preview.time_label.text() and preview._pending is None
    assert w.plots.cursors[0].value() == pytest.approx(1.65)
    preview.request_time(3.5)
    w.open_recording(varjo_folder)           # a new recording starts at its beginning, not at the old request
    assert wait_for(app, lambda: w.result is not None)
    for _ in range(5):
        app.processEvents()
    assert "frame 0" in preview.time_label.text()
    w.close()


def test_a_failed_read_makes_the_preview_seek_next_time(app, varjo_folder):
    from cwtool import devices
    from cwtool.gui.video_preview import VideoPreview
    from cwtool.params import VideoSettings
    rec = devices.load(varjo_folder)
    p = VideoPreview()
    p.set_recording(rec, VideoSettings().for_recording(rec))
    reference = p._read(4).copy()
    assert p._read(10_000) is None and p._frame_cache is None   # past the end: position unknown
    p2 = VideoPreview()
    p2.set_recording(rec, VideoSettings().for_recording(rec))
    p2._read(2)
    p2._read(10_000)
    assert np.array_equal(p2._read(4), reference)                # seeks instead of reading on from 2


def test_lux_route_is_shown(app, tmp_path):
    from conftest import write_core_recording
    from cwtool import devices, pipeline
    from cwtool.gui.plots import ResultPlots
    from cwtool.params import VideoSettings
    from cwtool.video import analyse_video

    frame_times = np.arange(30) / 30
    rec = devices.load(write_core_recording(tmp_path / "core", [40] * 5 + [220] * 25, frame_times,
                                            lux=lambda t: 200.0))
    video = analyse_video(rec.scene_video, rec.time, rec.gaze, VideoSettings().for_recording(rec),
                          frame_times=rec.scene_frame_times)
    plots = ResultPlots()
    r = pipeline.run(rec, video, Parameters(delay=0.0))
    plots.show_result(r)
    assert plots.ratio.isVisible() and plots.sensor_curve.isVisible()
    text = MainWindow._route_text(r)
    assert "lux sensor" in text and "video ratio" in text
    plots.show_result(pipeline.run(rec, video, Parameters(delay=0.0, lux_use_video=False)))
    assert not plots.ratio.isVisible() and plots.sensor_curve.isVisible()     # the sensor alone: no ratio panel
    assert "video not used" in MainWindow._route_text(pipeline.run(rec, video, Parameters(delay=0.0, lux_use_video=False)))


def test_peak_decimate_keeps_extremes_and_gaps():
    from cwtool.gui.plots import peak_decimate
    t = np.arange(20000) / 100.0
    y = np.sin(t)
    y[7000] = 5.0                       # a one-sample peak
    y[9000:9400] = np.nan               # a gap
    x, d = peak_decimate(t, y, bins=500)
    assert len(d) < 1200 and np.nanmax(d) == 5.0 and np.isnan(d).any()
    assert np.all(np.diff(x) >= 0)
    x2, d2 = peak_decimate(t[:100], y[:100], bins=500)
    assert len(d2) == 100                 # short signals are left alone


def test_long_warning_does_not_widen_the_window(app):
    w = MainWindow()
    w.summary_label.setText("⚠ " + "a very long warning " * 30)
    assert w.summary_label.wordWrap() and w.minimumSizeHint().width() < 1200


def test_side_panel_can_shrink(app):
    from PySide6.QtWidgets import QScrollArea
    w = MainWindow()
    side = w.findChildren(QScrollArea)[0].widget()
    assert side.minimumSizeHint().width() <= 360      # no checkbox or label may force a horizontal scrollbar


def test_glasses_calibration_controls_and_run_file(app, tmp_path):
    from conftest import write_core_recording
    from cwtool import calibration, devices

    rec = devices.load(write_core_recording(tmp_path / "core", [128] * 300, np.arange(300) / 30, lux=lambda t: 100.0))
    w = MainWindow()
    w.recording = rec
    layout = w._cal_layout
    w._show_sequence_controls("lux")
    assert w.cal_box.title() == "Calibration sequence" and not w.sequence_controls.isHidden()
    assert layout.isRowVisible(w.lux_fit_button) and layout.isRowVisible(w.fit_weight_check)
    assert not layout.isRowVisible(w.light_button)
    assert not layout.isRowVisible(w.fit_button) and not layout.isRowVisible(w.find_sequence_button)
    w._show_sequence_controls("display")
    assert layout.isRowVisible(w.light_button) and not layout.isRowVisible(w.lux_fit_button)
    assert not layout.isRowVisible(w.fit_weight_check)
    w._show_sequence_controls("none")
    assert w.cal_box.title() == "Pupil dynamics" and w.sequence_controls.isHidden()

    # A presenter run file places the sequence from its onset times on the computer's clock.
    run = tmp_path / "run.csv"
    run.write_text("time,duration,r,g,b,label,onset_unix_ms\n"
                   f"0,3,73,73,73,Gray,{(rec.epoch_start + 2.0) * 1000:.0f}\n3,3,0,0,0,Black,0\n")
    sequence = calibration.load_sequence(run)
    w.set_sequence(sequence)
    w._place_from_run(str(run), sequence)
    assert w.sequence_start.value() == pytest.approx(2.0, abs=0.01) and w.sequence_check.isChecked()
    far = tmp_path / "far.csv"
    far.write_text(f"time,duration,r,g,b,label,onset_unix_ms\n0,3,1,1,1,x,{(rec.epoch_start + 5000) * 1000:.0f}\n")
    w.sequence_check.setChecked(False)
    w._place_from_run(str(far), calibration.load_sequence(far))
    assert not w.sequence_check.isChecked() and "outside" in w.statusBar().currentMessage()


def test_lux_folder_is_remembered(app, tmp_path, monkeypatch):
    from PySide6.QtCore import QSettings
    from cwtool.gui import main_window as mw

    QSettings.setPath(QSettings.NativeFormat, QSettings.UserScope, str(tmp_path / "settings"))
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path / "settings"))
    folder = tmp_path / "lux"
    folder.mkdir()
    w = mw.MainWindow()
    w._settings.remove("lux_folder")
    w.set_lux_folder(folder)
    assert w._lux_folder == folder and w.clear_lux_action.isEnabled()
    again = mw.MainWindow()                       # the next session
    assert again._lux_folder == folder
    again.clear_lux_folder()
    assert again._lux_folder is None and not again.clear_lux_action.isEnabled()
    assert mw.MainWindow()._lux_folder is None
    folder.rmdir()
    w.set_lux_folder(folder)                      # a folder that later disappears is not used
    folder.rmdir() if folder.exists() else None
    assert mw.MainWindow()._lux_folder is None
