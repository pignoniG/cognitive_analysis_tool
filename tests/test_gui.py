"""Tests of the analysis window: opening and analysing a recording, the parameter panel, the video preview, the fits
and the plots.
"""

from dataclasses import replace
import os
import time

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6.QtWidgets")
pytest.importorskip("pyqtgraph")

pytestmark = pytest.mark.usefixtures("isolated_qsettings")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QCloseEvent  # noqa: E402
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
    assert not w.step_lux.isHidden() and w.step_light.isHidden() and w.step_timing.isHidden()
    assert shown("attack")
    assert not shown("l_max") and not shown("camera_exposure") and not shown("field_radius")

    w.open_recording(write_neon_recording(tmp_path / "nolux", GRAYS, FRAME_TIMES))
    assert wait_for(app, lambda: w.result is not None and w.recording.lux_values is None)
    assert w.sequence_controls.isHidden() and w.step_lux.isHidden()      # no lux log: nothing to fit, a note says why
    assert not w.cal_note.isHidden()
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
    assert b.isVisible() and b.x() + b.width() > w.plots.width() - 40 and b.y() + b.height() <= w.plots.BUTTON_BAR + 2      # top right, in the bar above the plots
    w.close()


def test_video_and_dynamics_settings_are_drop_downs_next_to_their_controls(app, varjo_folder):
    w = MainWindow()
    panel = w.params_panel
    video, dynamics = panel.video_section, panel.dynamics_section
    assert video.parent() is not None and video.parentWidget().title() == "Scene video"
    assert panel.pills.page(0).isAncestorOf(dynamics)        # the dynamics are fitted per participant: Participant pill
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
    assert wait_for(app, lambda: w.result is not None)       # (the old result is there until the new one replaces it)
    assert wait_for(app, lambda: "frame 0" in preview.time_label.text())
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
    assert not plots.plot_shown("ratio") and plots.ratio_available()      # the video ratio is off until asked for
    plots.set_plot_shown("ratio", True)
    plots.set_plot_shown("lum", True)        # the sensor curve is on the luminance plot
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
    w._show_sequence_controls("lux")
    assert not w.sequence_controls.isHidden() and not w.step_lux.isHidden()
    assert w.step_light.isHidden() and w.step_timing.isHidden() and w.find_sequence_button.isHidden()
    w._show_sequence_controls("display")
    assert not w.step_light.isHidden() and not w.step_timing.isHidden() and w.step_lux.isHidden()
    assert not w.find_sequence_button.isHidden()
    w._show_sequence_controls("none")
    assert w.sequence_controls.isHidden() and w.step_lux.isHidden() and not w.cal_note.isHidden()

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


def test_the_logger_folder_is_remembered(app, tmp_path, monkeypatch):
    """One folder, the sensor logger's, gives the lux log and the sensor files; it is kept between sessions."""
    from PySide6.QtCore import QSettings
    from cwtool.gui import main_window as mw

    QSettings.setPath(QSettings.NativeFormat, QSettings.UserScope, str(tmp_path / "settings"))
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path / "settings"))
    folder = tmp_path / "logs"
    folder.mkdir()
    w = mw.MainWindow()
    w._settings.remove("sensor_logs_folder")
    w._settings.remove("lux_folder")
    w.set_logs_folder(folder)
    assert w._logs_folder == folder and w.forget_logs_action.isEnabled()
    again = mw.MainWindow()                       # the next session
    assert again._logs_folder == folder
    again.forget_logger_folder()
    assert again._logs_folder is None and not again.forget_logs_action.isEnabled()
    assert mw.MainWindow()._logs_folder is None
    w.set_logs_folder(folder)                     # a folder that later disappears is not used
    folder.rmdir()
    assert mw.MainWindow()._logs_folder is None
    # the folder that was remembered for the lux log alone is still honoured
    old = tmp_path / "old_lux"
    old.mkdir()
    w._settings.setValue("lux_folder", str(old))
    assert mw.MainWindow()._logs_folder == old


def test_the_time_axis_cannot_be_scrolled_off_the_recording(app, tmp_path):
    """A swipe or a drag that misses the cursor must not slide the plots away from their data."""
    from conftest import write_varjo_recording

    w = MainWindow()
    w.open_recording(write_varjo_recording(tmp_path / "rec", [128, 255, 0, 128, 64, 200, 90, 128], pupil_mm=3.0))
    assert wait_for(app, lambda: w.result is not None)
    lo, hi = float(w.result.time[0]), float(w.result.time[-1])
    vb = w.plots.pupil.vb
    vb.translateBy(x=1000.0)                                                  # scrolled far to the right
    x0, x1 = vb.viewRange()[0]
    assert x1 <= hi + 1e-6 and x0 >= lo - 1e-6
    vb.translateBy(x=-5000.0)                                                 # and to the left
    x0, x1 = vb.viewRange()[0]
    assert x0 >= lo - 1e-6 and x1 <= hi + 1e-6
    vb.scaleBy((100.0, 1.0))                                                  # zoomed out far beyond the recording
    x0, x1 = vb.viewRange()[0]
    assert x0 >= lo - 1e-6 and x1 <= hi + 1e-6
    vb.setXRange(lo + 2.0, lo + 4.0, padding=0)                               # zooming in and moving within it still works
    vb.translateBy(x=1.0)
    x0, x1 = vb.viewRange()[0]
    assert x1 - x0 == pytest.approx(2.0, abs=0.05) and x0 > lo + 2.5
    # the other plots, linked in time, follow and the sensor plots have the same limits
    assert all(p.vb.viewRange()[0][0] >= lo - 1e-6 for p in w.plots._plots)
    w.close()


class FakeMouseEvent:
    """Just what TimeViewBox reads from a pyqtgraph mouse event."""

    def __init__(self, button, down, pos, last=None, finish=False, modifiers=None, vb=None):
        self._vb = vb
        self._button, self._down, self._pos, self._last, self._finish = button, down, pos, last or pos, finish
        self._modifiers = modifiers or Qt.NoModifier

    def accept(self): pass
    def button(self): return self._button
    def modifiers(self): return self._modifiers
    def isFinish(self): return self._finish
    def buttonDownScenePos(self): return self._down
    def scenePos(self): return self._pos
    def lastScenePos(self): return self._last
    def buttonDownPos(self): return self._vb.mapFromScene(self._down) if self._vb else self._down
    def pos(self): return self._vb.mapFromScene(self._pos) if self._vb else self._pos


def test_plots_pan_in_time_and_the_zoom_button_zooms_to_a_rectangle(app, tmp_path):
    """Drag pans in time; in zoom mode a rectangle zooms in time and value; right-click zooms out."""
    from conftest import write_varjo_recording
    from PySide6.QtCore import QPointF

    w = MainWindow()
    w.resize(1400, 900)
    w.show()
    w.open_recording(write_varjo_recording(tmp_path / "rec", [128, 255, 0, 128, 64, 200, 90, 128] * 6, pupil_mm=3.0))
    assert wait_for(app, lambda: w.result is not None, 60)
    plots, vb = w.plots, w.plots.pupil.vb
    assert all(p.vb.state["mouseEnabled"] == [True, False] for p in plots._plots)
    full_x, full_y = vb.viewRange()
    rect = vb.sceneBoundingRect()
    mid, centre = rect.center().y(), rect.center().x()
    # not in zoom mode, a left drag pans in time only and the value axis stays where it is
    vb.setXRange(full_x[0] + 10, full_x[0] + 20, padding=0)
    before = vb.viewRange()
    a = QPointF(centre, mid)
    vb.mouseDragEvent(FakeMouseEvent(Qt.LeftButton, a, QPointF(a.x() - 60, mid + 40), last=a))
    x, y = vb.viewRange()
    assert x[0] > before[0][0] and x[1] - x[0] == pytest.approx(before[0][1] - before[0][0])
    assert y == pytest.approx(before[1])
    plots.fit_to_data()
    # zoom mode: the rectangle is drawn from where the button went down, and zooms in time and in value
    plots.zoom_button.click()
    assert plots.zoom_button.isChecked() and all(p.vb.zoom_mode for p in plots._plots)
    d0, d1 = QPointF(centre - 50, mid - 30), QPointF(centre + 80, mid + 30)
    vb.mouseDragEvent(FakeMouseEvent(Qt.LeftButton, d0, d1, vb=vb))
    band = vb.rbScaleBox.mapRectToScene(vb.rbScaleBox.rect())
    assert band.left() == pytest.approx(d0.x(), abs=1.5) and band.right() == pytest.approx(d1.x(), abs=1.5)
    vb.rbScaleBox.hide()
    a, b = QPointF(centre - rect.width() / 10, mid - rect.height() / 4), QPointF(centre + rect.width() / 10, mid + rect.height() / 4)
    vb.mouseDragEvent(FakeMouseEvent(Qt.LeftButton, a, b, finish=True))
    x, y = vb.viewRange()
    assert (x[1] - x[0]) == pytest.approx(0.2 * (full_x[1] - full_x[0]), rel=0.2)
    assert (y[1] - y[0]) < 0.7 * (full_y[1] - full_y[0])                          # zoomed in value as well
    assert plots.pupil in plots._y_zoomed and plots.cw not in plots._y_zoomed
    vb.setXRange(x[0] + 1, x[1] + 1, padding=0)                                      # moving along: the zoomed value axis stays
    assert vb.viewRange()[1] == pytest.approx(y)
    # a click-sized drag does not zoom
    before = vb.viewRange()[0]
    vb.mouseDragEvent(FakeMouseEvent(Qt.LeftButton, a, QPointF(a.x() + 1, a.y() + 1), finish=True))
    assert vb.viewRange()[0] == pytest.approx(before)
    # right click zooms out and fits the value axis to the data again
    vb.mouseClickEvent(FakeMouseEvent(Qt.RightButton, a, QPointF(centre, mid)))
    wider = vb.viewRange()[0]
    assert (wider[1] - wider[0]) > 1.8 * (before[1] - before[0]) and plots.pupil not in plots._y_zoomed
    assert all(p.vb.viewRange()[0] == pytest.approx(wider) for p in plots._plots)
    # the reset button shows it all again, and a drag pans once zoom mode is off
    plots.fit_to_data()
    assert vb.viewRange()[0][1] - vb.viewRange()[0][0] > 0.95 * (full_x[1] - full_x[0])
    plots.zoom_button.click()
    assert not any(p.vb.zoom_mode for p in plots._plots)
    w.close()


def test_every_plot_can_be_switched_and_the_axes_line_up(app, tmp_path):
    from conftest import write_varjo_recording

    w = MainWindow()
    w.resize(1400, 900)
    w.show()
    w.open_recording(write_varjo_recording(tmp_path / "rec", [128, 255, 0, 128, 64, 200, 90, 128], pupil_mm=3.0))
    assert wait_for(app, lambda: w.result is not None)
    plots = w.plots
    # by default: the pupil diameter and ΔPD; luminance and the video ratio (not available here) are off
    assert [k for k in plots.PLOT_KEYS if plots.plot_shown(k)] == ["pupil", "cw"]
    assert w.plot_checks["pupil"].isChecked() and w.plot_checks["cw"].isChecked() and not w.plot_checks["lum"].isChecked()
    assert not w.plot_checks["ratio"].isEnabled()
    w.plot_checks["lum"].setChecked(True)
    app.processEvents()
    assert plots.lum.isVisible()
    # the left axes are as wide and start at the same place, whatever their numbers are
    widths = {p.getAxis("left").width() for p in plots._plots}
    assert len(widths) == 1
    lefts = {round(p.vb.sceneBoundingRect().left()) for p in plots._plots if p.isVisible()}
    rights = {round(p.vb.sceneBoundingRect().right()) for p in plots._plots if p.isVisible()}
    assert len(lefts) == 1 and len(rights) == 1
    # hiding the last plot moves the time axis up to the last one shown
    w.plot_checks["cw"].setChecked(False)
    app.processEvents()
    assert not plots.cw.isVisible()
    assert plots.lum.getAxis("bottom").style["showValues"] and not plots.pupil.getAxis("bottom").style["showValues"]
    w.close()


def test_the_left_pages_never_scroll_sideways(app):
    w = MainWindow()
    w.resize(1400, 900)
    w.show()
    w.main_split.setSizes([1, 1000])                                              # as narrow as the window allows
    for i in range(w.pages.count()):
        w.rail.set_current(i)
        app.processEvents()
        scroll = w.pages.widget(i)
        assert scroll.horizontalScrollBar().maximum() == 0, f"page {i} is wider than its column"
    w.close()


def test_bars_are_dragged_by_the_handles_under_the_plots_and_not_on_the_plots(app, tmp_path):
    from conftest import write_varjo_recording
    from PySide6.QtCore import QEvent, QPointF
    from PySide6.QtGui import QMouseEvent

    from cwtool.trim import Trim

    w = MainWindow()
    w.resize(1400, 900)
    w.show()
    w.open_recording(write_varjo_recording(tmp_path / "rec", [128, 255, 0, 128, 64, 200, 90, 128] * 6, pupil_mm=3.0))
    assert wait_for(app, lambda: w.result is not None, 60)
    plots = w.plots
    w.trim_panel.set_trim(Trim(5.0, 40.0, [(15.0, 20.0)]))
    plots.set_cursor(10.0)
    app.processEvents()
    ids = [g[0] for g in plots.grips()]
    assert ids == ["cursor", "start", "end", ("band", 0, "a"), ("band", 0, "b"), ("band", 0, "mid")]
    # nothing on the plots themselves can be dragged
    assert not any(line.movable for line in plots.cursors) and not plots._start_line.movable
    assert not plots._end_line.movable and not plots._exclusion_shades[0][0].movable
    # the handle strip is right under the first plot (pupil diameter), outside the plots; the time axis is repeated above it
    strip = plots.handles
    below = plots.mapFromScene(plots.pupil.vb.sceneBoundingRect().bottomLeft()).y()
    assert below <= strip.geometry().top() + 1 and strip.geometry().bottom() <= plots.mapFromScene(plots.cw.vb.sceneBoundingRect().topLeft()).y()
    assert plots.pupil.getAxis("top").isVisible() and plots.pupil.getAxis("top").style["showValues"]
    assert not plots.cw.getAxis("top").isVisible() and plots.cw.getAxis("bottom").style["showValues"]

    def drag(t_from, dx):
        x = strip._x(t_from)
        for kind, px in ((QEvent.MouseButtonPress, x), (QEvent.MouseMove, x + dx), (QEvent.MouseButtonRelease, x + dx)):
            event = QMouseEvent(kind, QPointF(px, 9), QPointF(px, 9), Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
            {QEvent.MouseButtonPress: strip.mousePressEvent, QEvent.MouseMove: strip.mouseMoveEvent,
             QEvent.MouseButtonRelease: strip.mouseReleaseEvent}[kind](event)

    seen = []
    plots.cursor_changed.connect(seen.append)
    drag(10.0, 60)
    assert plots.cursor_time() > 11.0 and seen                                   # the video follows the handle
    drag(5.0, 40)
    assert plots._current_trim().start > 5.5                                      # the export start moved
    drag(40.0, -40)
    assert plots._current_trim().end < 39.5
    drag(17.5, 40)                                                                # the middle of the band moves all of it
    a, b = plots._exclusion_shades[0][0].getRegion()
    assert a > 15.5 and b - a == pytest.approx(5.0)
    w.close()


def test_a_recording_opens_on_its_whole_span_even_when_the_sensor_plots_were_reset_just_before(app, tmp_path):
    """Opening a recording clears the sensor plots, then (with the video analysis cached) shows the result in the same
    turn of the event loop: the clearing must not bring back the empty 0-1 s view afterwards."""
    from conftest import write_varjo_recording
    from cwtool import devices, pipeline
    from cwtool.params import Parameters, VideoSettings
    from cwtool.video import analyse_video

    rec = devices.load(write_varjo_recording(tmp_path / "rec", [128, 255, 0, 128, 64, 200, 90, 128] * 6, pupil_mm=3.0))
    video = analyse_video(rec.scene_video, rec.time, rec.gaze, VideoSettings().for_recording(rec),
                          frame_times=rec.scene_frame_times)
    result = pipeline.run(rec, video, Parameters())
    w = MainWindow()
    w.resize(1400, 900)
    w.show()
    app.processEvents()
    w.plots.set_sensors([])                      # what opening a recording does first
    w.plots.show_result(result)                  # the cached analysis: no event loop in between
    for _ in range(5):
        app.processEvents()
    lo, hi = float(result.time[0]), float(result.time[-1])
    for plot in w.plots._plots:
        x0, x1 = plot.vb.viewRange()[0]
        assert x1 - x0 > 0.95 * (hi - lo), x1 - x0
    # a restore queued before the view was fitted is dropped, whatever span it holds
    before = w.plots.pupil.vb.viewRange()[0]
    w.plots._restore_x([0.0, 1.0], w.plots._view_changes - 1)
    assert w.plots.pupil.vb.viewRange()[0] == before
    w.close()


def test_the_restore_button_sits_right_under_the_last_block_of_its_pill(app):
    from cwtool.gui.param_panel import ParameterPanel

    panel = ParameterPanel()
    panel.resize(420, 900)
    panel.show()
    app.processEvents()
    for index, button in enumerate(panel.reset_buttons):
        panel.pills._chosen(index)
        panel.pills._buttons[index].setChecked(True)
        app.processEvents()
        page = panel.pills._stack.widget(index)
        blocks = [c for c in page.children() if hasattr(c, "geometry") and c is not button and c.isWidgetType()
                  and c.isVisible()]
        last = max(b.geometry().bottom() for b in blocks)
        assert 0 <= button.geometry().top() - last <= 24, (index, button.geometry().top() - last)   # not pushed to the bottom
    panel.close()


def test_changed_parameters_are_flagged_reverted_and_asked_about(app, tmp_path, monkeypatch):
    from conftest import write_varjo_recording
    from PySide6.QtWidgets import QMessageBox

    folder = write_varjo_recording(tmp_path / "rec", [128, 255, 0, 128, 64, 200, 90, 128], pupil_mm=3.0)
    other = write_varjo_recording(tmp_path / "rec2", [128, 255, 0, 128, 64, 200, 90, 128], pupil_mm=3.0)
    w = MainWindow()
    w.open_recording(folder)
    assert wait_for(app, lambda: w.result is not None)
    assert not w.params_dirty() and not w.revert_button.isEnabled() and "changed" not in w.windowTitle()
    start = w.params_panel.params()
    w.params_panel.set_params(replace(start, age=start.age + 10))
    w._update_state()
    assert w.params_dirty() and w.revert_button.isEnabled() and "changed" in w.windowTitle()
    # Revert asks, and puts the starting values back
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.No))
    w.revert_params()
    assert w.params_dirty()
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Yes))
    w.revert_params()
    assert not w.params_dirty() and w.params_panel.params().age == start.age
    # opening another recording with changed parameters asks; Cancel stays on this recording
    w.params_panel.set_params(replace(start, age=start.age + 5))
    asked = []
    monkeypatch.setattr(type(w), "_ask_unsaved", lambda self, what: asked.append(what) or QMessageBox.Cancel)
    w.open_recording(other)
    assert asked == ["opening another recording"] and w.recording.folder == folder
    # Save writes the file and the changes are then the saved state; the other recording opens
    saved = tmp_path / "p.json"
    w._params_path = saved
    monkeypatch.setattr(type(w), "_ask_unsaved", lambda self, what: QMessageBox.Save)
    w.open_recording(other)
    assert saved.exists() and not w.params_dirty()
    assert wait_for(app, lambda: w.recording is not None and w.recording.folder == other)
    # closing with changes and Cancel keeps the window open
    w.params_panel.set_params(replace(w.params_panel.params(), age=start.age + 1))
    monkeypatch.setattr(type(w), "_ask_unsaved", lambda self, what: QMessageBox.Cancel)
    event = QCloseEvent()
    w.closeEvent(event)
    assert not event.isAccepted()
    monkeypatch.setattr(type(w), "_ask_unsaved", lambda self, what: QMessageBox.Discard)
    w.close()


def test_cancel_stops_a_long_task_quietly_and_is_offered_only_when_it_can_work(app, tmp_path, monkeypatch):
    from conftest import write_varjo_recording

    w = MainWindow()
    w.open_recording(write_varjo_recording(tmp_path / "rec", [128, 255, 0, 128, 64, 200, 90, 128], pupil_mm=3.0))
    assert wait_for(app, lambda: w.result is not None)
    errors = []
    monkeypatch.setattr(w, "_error", lambda *a, **k: errors.append(a))

    def slow(progress, cancelled):
        while not cancelled():
            time.sleep(0.01)
        raise InterruptedError("fit cancelled")           # what the fit does when it is stopped

    w._start_task(slow, lambda r: None, "Fitting…", cancellable=True)
    app.processEvents()
    assert not w.cancel_button.isHidden()                  # the fit can be cancelled
    w.cancel_button.click()
    assert wait_for(app, lambda: not w._task.isRunning())
    assert wait_for(app, lambda: "Cancelled" in w.statusBar().currentMessage())
    assert errors == []                                      # no error box for a cancelled task
    w._start_task(lambda p, c: time.sleep(0.2), lambda r: None, "Exporting…")      # not cancellable
    app.processEvents()
    assert w.cancel_button.isHidden()
    assert wait_for(app, lambda: not w._task.isRunning())
    w.close()
