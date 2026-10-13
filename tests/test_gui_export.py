"""The main window: sensor data under ΔPD, the export range, and the packaged export."""

import csv
import os
import time

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6.QtWidgets")
pytest.importorskip("pyqtgraph")

pytestmark = pytest.mark.usefixtures("isolated_qsettings")

from PySide6.QtWidgets import QApplication, QFileDialog  # noqa: E402

from cwtool.gui.main_window import MainWindow  # noqa: E402
from cwtool.trim import TRIM_FILE, Trim  # noqa: E402
from conftest import write_varjo_recording  # noqa: E402
from test_export_package import write_session  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def wait_for(app, condition, timeout=30):
    end = time.time() + timeout
    while not condition() and time.time() < end:
        app.processEvents()
        time.sleep(0.01)
    return condition()


@pytest.fixture
def window(app, tmp_path):
    folder = write_varjo_recording(tmp_path / "rec", [128, 255, 0, 128, 64, 200, 90, 128], pupil_mm=3.0)
    w = MainWindow()
    w.open_recording(folder)
    assert wait_for(app, lambda: w.result is not None)
    yield w, folder, tmp_path
    w.close()


def rows(path):
    return list(csv.DictReader(open(path)))


def test_sensor_data_is_shown_under_delta_pd_and_can_be_chosen(app, window):
    w, folder, tmp = window
    rec = w.recording
    session = write_session(tmp / "session", rec.epoch_start + float(rec.time[0]))
    w.import_sensors(session)
    assert wait_for(app, lambda: len(w.sensors) == 2)
    # the default signals: the ECG channel of the Shimmer and the EmotiBit's EDA
    assert len(w.plots._sensor_plots) == 2
    from PySide6.QtCore import Qt
    shown = [w.signal_list.item(i).text() for i in range(w.signal_list.count())
             if w.signal_list.item(i).checkState() == Qt.Checked]
    assert shown == ["shimmer: exg_ads1292r_1_ch1_24bit", "emotibit: EDA"]
    # the time axis is on the last plot only; every plot has its own cursor
    last = w.plots._plots[-1]
    assert [p.getAxis("bottom").style["showValues"] for p in w.plots._plots].count(True) == 1
    assert w.plots._plots[-1] is last and len(w.plots.cursors) == len(w.plots._plots)
    # choose another signal
    from PySide6.QtCore import Qt
    for i in range(w.signal_list.count()):
        if w.signal_list.item(i).text() == "shimmer: accel_ln_x":
            w.signal_list.item(i).setCheckState(Qt.Checked)
    assert len(w.plots._sensor_plots) == 3
    w.remove_sensors()
    assert w.sensors == [] and w.plots._sensor_plots == [] and w.plots._plots == w.plots._base_plots


def test_sensors_are_found_in_the_recordings_own_folder(app, tmp_path):
    folder = write_varjo_recording(tmp_path / "rec", [128, 255, 0, 128, 64, 200, 90, 128], pupil_mm=3.0)
    from cwtool import devices
    rec = devices.load(folder)
    write_session(folder, rec.epoch_start + float(rec.time[0]))   # the logger's files copied next to it
    w = MainWindow()
    w.open_recording(folder)
    assert wait_for(app, lambda: len(w.sensors) == 2)
    w.close()


def test_export_range_is_edited_dragged_saved_and_restored(app, window):
    w, folder, tmp = window
    panel, plots = w.trim_panel, w.plots
    assert panel.isEnabled() and not panel.trim().active

    panel.set_trim(Trim(1.0, 7.0, [(3.0, 5.0)]))     # as if edited in the panel
    assert plots._start_line is not None and plots._end_line is not None and len(plots._exclusion_shades) == 1
    assert "6.0" in panel.summary.text() or "4.0" in panel.summary.text()   # 6 s range minus 2 s left out = 4 s
    assert panel.segments.count() == 1

    plots._start_line.setValue(2.0)                  # dragged on the plot: the panel follows
    assert panel.trim().start == pytest.approx(2.0) and panel.start_spin.value() == pytest.approx(2.0)

    plots._exclusion_shades[0][0].setRegion((4.0, 6.0))
    assert panel.trim().exclude == [(4.0, 6.0)]
    for region in plots._exclusion_shades[0][1:]:     # the other plots follow
        assert region.getRegion() == pytest.approx((4.0, 6.0))

    # buttons: leave out from the cursor, the calibration sequence, remove
    plots.set_cursor(6.5)
    panel.add_button.click()
    assert len(panel.trim().exclude) == 2
    panel.segments.setCurrentRow(1)
    panel.remove_button.click()
    assert len(panel.trim().exclude) == 1
    assert not panel.sequence_button.isEnabled()
    w.sequence_check.setChecked(True)
    w.sequence_start.setValue(0.5)
    assert panel.sequence_button.isEnabled()

    # saved with the recording, and back when it is opened again
    assert wait_for(app, lambda: (folder / TRIM_FILE).exists(), 5)
    saved = Trim.load(folder / TRIM_FILE)
    assert saved.start == pytest.approx(2.0) and saved.exclude == [(4.0, 6.0)]
    old = w.recording
    w.open_recording(folder)
    assert wait_for(app, lambda: w.recording is not old and w.result is not None)
    assert w.trim_panel.trim().start == pytest.approx(2.0)
    assert w.trim_panel.trim().exclude == [(4.0, 6.0)] and w.plots._start_line is not None
    # clearing it removes the file
    w.trim_panel.set_trim(Trim())
    assert wait_for(app, lambda: not (folder / TRIM_FILE).exists(), 5)


def test_the_window_exports_one_package(app, window, monkeypatch):
    w, folder, tmp = window
    rec = w.recording
    session = write_session(tmp / "session", rec.epoch_start + float(rec.time[0]))
    w.import_sensors(session)
    assert wait_for(app, lambda: len(w.sensors) == 2)
    w.trim_panel.set_trim(Trim(1.0, 7.0, [(3.0, 5.0)]))
    out = tmp / "package"
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *a, **k: str(out))
    w.export()
    assert wait_for(app, lambda: not w.export_result.isHidden())                 # exported in the background
    names = sorted(p.name for p in out.iterdir())
    assert {"rec_pupil.csv", "rec_cw.csv", "rec_shimmer.csv", "rec_emotibit.csv", "rec_export.json",
            "rec_params.json"} <= set(names)
    t = np.array([float(r["timestamp_relative"]) for r in rows(out / "rec_shimmer.csv")])
    assert t.min() >= 1.0 and t.max() <= 7.0 and not ((t >= 3.0) & (t < 5.0)).any()
    assert "trimmed" in w.statusBar().currentMessage() and "sensor file" in w.statusBar().currentMessage()
    assert "Last export" in w.export_result.text() and str(out) in w.export_result.text()    # kept in the Export tab
    assert w.export_progress.isHidden()


def write_ecg_session(folder, epoch, seconds=40.0):
    """A logger session folder with a Shimmer whose ECG is sampled at 256 Hz (a synthetic one with a heart rate of 60)."""
    from test_hrv import GAIN, rr_series, synthetic_ecg
    import json as _json

    from cwtool import hrv

    t, mv, _ = synthetic_ecg(rr_series(int(seconds) + 5, depth=0.05))
    counts = np.round(mv / (hrv.REFERENCE_V * 1000.0 / hrv.ADC_FULL_SCALE / GAIN) + 2000.0)
    folder.mkdir(parents=True, exist_ok=True)
    with open(folder / "shimmer.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["unix time (s)", "device time (s)", "exg_ads1292r_1_ch1_24bit"])
        keep = t < seconds + 4
        for ti, ci in zip(t[keep], counts[keep]):
            w.writerow([f"{epoch + ti - 2:.6f}", f"{ti:.5f}", int(ci)])
    (folder / "session.json").write_text(_json.dumps({"sources": {"shimmer": {
        "file": "shimmer.csv", "kind": "shimmer",
        "settings": {"exg": {"chip 1": {"gain ch1": 4, "gain ch2": 4, "data rate (Hz)": 500}}}}}}))
    return folder


def test_the_hrv_button_needs_an_ecg_and_a_low_rate_ecg_is_flagged(app, window):
    w, folder, tmp = window
    rec = w.recording
    assert not w.hrv_button.isEnabled()                                   # no sensors: nothing to compute from
    session = write_session(tmp / "session", rec.epoch_start + float(rec.time[0]))
    w.import_sensors(session)
    assert wait_for(app, lambda: len(w.sensors) == 2)
    # the test session's Shimmer is sampled at 50 Hz: too coarse for HRV, and the window says so; the button is there
    assert w.hrv_button.isEnabled() and "too coarse" in w.sensors_label.text() and "50 Hz" in w.sensors_label.text()
    assert not w.hrv_table.isVisible() and "HRV" not in w.export_summary.text()
    w.remove_sensors()
    assert not w.hrv_button.isEnabled()


def test_compute_hrv_shows_the_table_and_the_beats_and_the_export_uses_them(app, window, monkeypatch):
    from cwtool import hrv, pipeline
    from cwtool.recording import Event
    from cwtool.trim import Trim

    w, folder, tmp = window
    long = write_varjo_recording(tmp / "long" / "rec", [128, 255, 0, 128, 64, 200, 90, 128] * 6, pupil_mm=3.0)   # 48 s
    w.open_recording(long)
    assert wait_for(app, lambda: w.recording.folder == long and w.result is not None, timeout=60)
    rec = w.recording
    rec.events = [Event("Rest", 0.0, 20.0), Event("Task", 20.0, 48.0)]
    w._update_state()
    session = write_ecg_session(tmp / "session", rec.epoch_start + float(rec.time[0]), seconds=float(rec.time[-1]))
    w.import_sensors(session)
    assert wait_for(app, lambda: len(w.sensors) == 1)
    assert w.hrv_button.isEnabled() and w.hrv_button.text() == "Compute HRV" and not w.hrv_beats
    # exporting before computing leaves the HRV out
    paths = pipeline.export(w.result, rec, w.params_panel.params(), tmp / "first", sensors=w.sensors, hrv=bool(w.hrv_beats),
                            hrv_beats=w.hrv_beats)
    assert not any("hrv" in p.name for p in paths)

    calls = []
    real = hrv.beats_of
    monkeypatch.setattr(hrv, "beats_of", lambda *a, **k: calls.append(1) or real(*a, **k))
    w.hrv_button.click()
    assert wait_for(app, lambda: bool(w.hrv_beats) and w.hrv_table.rowCount() == 3)
    assert w.hrv_button.text() == "Recompute HRV" and "shimmer + HRV" in w.export_summary.text()
    names = [w.hrv_table.item(i, 0).text().rstrip(" *") for i in range(3)]
    assert names == ["recording", "Rest", "Task"]
    assert 55 <= float(w.hrv_table.item(0, 2).text()) <= 65 and w.hrv_table.item(0, 5).text() == "–"   # HR 60 bpm, no spectrum
    assert w.plots._beat_items and len(w.plots._beats) == 1               # the ECG plot is shown by default: marked
    n_beats = sum(len(item.data) for _, item in w.plots._beat_items)
    assert n_beats >= 6

    # the plots of the heart rate and of the moving RMSSD, with their checkboxes under the plots (RMSSD on by default)
    assert not w.hrv_bar.isHidden() and not w.hr_check.isChecked() and w.rmssd_check.isChecked()
    titles = list(w.plots._sensor_labels)
    assert titles[-1] == "RMSSD (ms), moving 30 s window" and len(titles) == 2
    assert w.plots._sensor_plots[-1].titleLabel.text is None or not w.plots._sensor_plots[-1].titleLabel.isVisible()   # no title: the axis label says it
    assert w.plots._sensor_plots[-1].getAxis("left").labelText == "RMSSD (ms)"
    w.hr_check.setChecked(True)
    assert list(w.plots._sensor_labels)[-2:] == ["Heart rate (bpm)", titles[-1]]
    w.rmssd_check.setChecked(False)
    w.hr_check.setChecked(False)
    assert len(w.plots._sensor_plots) == 1                                    # only the ECG signal
    w.hr_check.setChecked(True)
    w.rmssd_check.setChecked(True)
    w.rmssd_window.setValue(20.0)                                             # the window is in the title
    assert wait_for(app, lambda: w.plots._sensor_labels[-1] == "RMSSD (ms), moving 20 s window")
    assert w.hrv_series.window == 20.0
    # the red points and the table follow the export range without rebuilding the plots
    kept = list(w.plots._sensor_plots)
    w.trim_panel.set_trim(Trim(exclude=[(5.0, 6.0)]))
    w._refresh_hrv()
    assert list(w.plots._sensor_plots) == kept

    # the table follows the export range without finding the beats again
    total = float(rec.time[-1] - rec.time[0])
    w.trim_panel.set_trim(Trim(exclude=[(2.0, 6.0)]))
    w._refresh_hrv()
    assert abs(float(w.hrv_table.item(0, 1).text()) - (total - 4.0)) <= 0.51 and len(calls) == 1

    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: str(tmp / "out")))
    w.export()
    assert wait_for(app, lambda: not w.export_result.isHidden())
    assert (tmp / "out/rec_shimmer_hrv.csv").exists() and (tmp / "out/rec_shimmer_beats.csv").exists()
    assert len(calls) == 1                                                  # the export did not look for the beats again
    rows_out = rows(tmp / "out/rec_shimmer_hrv.csv")
    assert [r["window"] for r in rows_out] == ["recording", "Rest", "Task"] and float(rows_out[0]["kept_seconds"]) == pytest.approx(total - 4.0, abs=0.01)

    # the cut at the export range: on the data beyond it by default; the box turns that off
    assert w.hrv_edges_check.isChecked() and w._hrv_edges() == "beyond"
    w.hrv_edges_check.setChecked(False)
    assert w._hrv_edges() == "inside"
    w.hrv_edges_check.setChecked(True)

    # changing the sensors forgets the beats, the plots and their checkboxes
    w.remove_sensors()
    assert not w.hrv_beats and not w.hrv_table.isVisible() and w.plots._beats == {}
    assert w.hrv_bar.isHidden() and w.hrv_series is None and w.plots._sensor_plots == []


def test_the_logger_folder_is_remembered_and_every_recording_finds_its_session(app, window, monkeypatch):
    from PySide6.QtCore import QSettings

    w, folder, tmp = window
    rec = w.recording
    start = rec.epoch_start + float(rec.time[0])
    logs = tmp / "logs"
    write_session(logs / "2026-10-01_08-00-00", epoch=start - 7200)               # an earlier session
    write_session(logs / "2026-10-01_10-00-00", epoch=start)                       # the recording's
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: str(logs)))
    w.choose_sensors()                                                             # pointed at the logger's folder
    assert wait_for(app, lambda: len(w.sensors) == 2)
    assert all(s.path.parent.name == "2026-10-01_10-00-00" for s in w.sensors)
    assert "2026-10-01_10-00-00" in w.sensors_label.text()
    assert str(w._settings.value("sensor_logs_folder")) == str(logs)

    # another recording, opened later: its session is found without asking
    other = write_varjo_recording(tmp / "rec2", [128, 255, 0, 128, 64, 200, 90, 128], pupil_mm=3.0)
    w.open_recording(other)
    assert wait_for(app, lambda: w.result is not None and len(w.sensors) == 2, timeout=60)
    assert w.sensors[0].path.parent.name == "2026-10-01_10-00-00"
    # a recording of another time finds nothing and says nothing
    w.remove_sensors()
    assert "Logger folder" in w.sensors_label.text()
    assert w.sensors == []
    # one session folder given directly does not replace the remembered logger folder
    monkeypatch.setattr(QFileDialog, "getExistingDirectory",
                        staticmethod(lambda *a, **k: str(logs / "2026-10-01_10-00-00")))
    w.choose_sensors()
    assert wait_for(app, lambda: len(w.sensors) == 2)
    assert str(w._settings.value("sensor_logs_folder")) == str(logs)


def test_one_logger_folder_gives_a_glasses_recording_its_lux_log_and_its_sensor_files(app, tmp_path, monkeypatch):
    """The lux log and the Shimmer and EmotiBit files are written by the same logger session: pointing the window at the
    logger's folder once finds both, without a second folder to choose."""
    from conftest import write_core_recording
    from test_pupil_core import FRAME_TIMES, GRAYS

    folder = write_core_recording(tmp_path / "core", GRAYS, FRAME_TIMES)           # no lux log in the recording
    w = MainWindow()
    w.open_recording(folder)
    assert wait_for(app, lambda: w.result is not None and w.recording.lux_values is None)
    start = w.recording.epoch_start + float(w.recording.time[0])
    logs = tmp_path / "logs"
    write_session(logs / "2026-10-01_07-00-00", epoch=start - 9000)                # an earlier session, with its own lux.csv
    write_session(logs / "2026-10-01_09-00-00", epoch=start)                        # the recording's session
    assert "lux sensor: no readings" in w.sensors_label.text() and w.sensors == []     # one box for the lux log and the sensors
    assert not hasattr(w, "lux_box")
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: str(logs)))
    w.choose_sensors()                                                              # the one chooser, in the sensor box
    assert wait_for(app, lambda: w.recording.lux_values is not None and len(w.sensors) == 2, timeout=60)
    assert len(w.recording.lux_values) > 10                                         # the lux log of the matching session
    assert "lux sensor: " in w.sensors_label.text() and "readings (" in w.sensors_label.text()
    assert "shimmer" in w.sensors_label.text()                                      # listed with the other sensors
    assert all(s.path.parent.name == "2026-10-01_09-00-00" for s in w.sensors)
    assert w.forget_logs_action.isEnabled() and w._logs_folder == logs
    # forgetting it: the recording's own folder again (no lux, no sensors)
    w.forget_logger_folder()
    assert wait_for(app, lambda: w.recording.lux_values is None and w.sensors == [] and w._logs_folder is None, timeout=60)
    w.close()


def test_the_sensor_signals_can_be_switched_from_under_the_plots(app, window):
    from PySide6.QtCore import Qt

    w, folder, tmp = window
    rec = w.recording
    assert w.signals_button.isHidden()
    shown = w.plots.pupil.vb.viewRange()[0]
    w.import_sensors(write_session(tmp / "session", rec.epoch_start + float(rec.time[0])))
    assert wait_for(app, lambda: len(w.sensors) == 2)
    assert not w.signals_button.isHidden() and len(w.plots._sensor_plots) == 2
    app.processEvents()
    assert all(p.vb.viewRange()[0] == pytest.approx(shown) for p in w.plots._plots)    # new plots keep the time span
    actions = {a.text(): a for a in w.signals_button.menu().actions()}
    assert actions["shimmer: exg_ads1292r_1_ch1_24bit"].isChecked() and not actions["shimmer: accel_ln_x"].isChecked()
    actions["shimmer: exg_ads1292r_1_ch1_24bit"].setChecked(False)           # switched off from under the plots
    assert len(w.plots._sensor_plots) == 1
    actions["shimmer: accel_ln_x"].setChecked(True)
    assert len(w.plots._sensor_plots) == 2
    # a tick in the list is shown in the menu
    for i in range(w.signal_list.count()):
        if w.signal_list.item(i).text() == "shimmer: accel_ln_x":
            w.signal_list.item(i).setCheckState(Qt.Unchecked)
    assert not [a for a in w.signals_button.menu().actions() if a.text() == "shimmer: accel_ln_x"][0].isChecked()
    w.remove_sensors()
    assert w.signals_button.isHidden()


def test_recent_recordings_are_listed_in_the_file_menu(app, window, tmp_path):
    w, folder, tmp = window
    w._fill_recent_menu()
    names = [a.text() for a in w.recent_menu.actions() if a.text() and "Clear" not in a.text()]
    assert len(names) == 1 and names[0].startswith("rec")                      # the recording opened by the fixture
    other = write_varjo_recording(tmp / "second", [128, 255, 0, 128, 64, 200, 90, 128], pupil_mm=3.0)
    w.open_recording(other)
    assert wait_for(app, lambda: w.recording.folder == other and w.result is not None, 60)
    assert w._recent_recordings()[0] == str(other) and len(w._recent_recordings()) == 2    # newest first
    w.recent_menu.actions()                                                      # (filled when the menu is shown)
    w._fill_recent_menu()
    assert w.recent_menu.actions()[0].toolTip() == str(other)
    w.recent_menu.actions()[-1].trigger()                                        # Clear the list
    assert w._recent_recordings() == []


def test_a_remembered_logger_folder_without_a_matching_session_says_so(app, window, monkeypatch):
    w, folder, tmp = window
    start = w.recording.epoch_start + float(w.recording.time[0])
    logs = tmp / "logs"
    write_session(logs / "2026-10-01_05-00-00", epoch=start - 20000)                # a session of another time
    w._logs_folder = logs                         # remembered earlier (setting it now would ask about this recording)
    other = write_varjo_recording(tmp / "later", [128, 255, 0, 128, 64, 200, 90, 128], pupil_mm=3.0)
    w.open_recording(other)
    assert wait_for(app, lambda: w.recording.folder == other and w.result is not None, 60)
    assert wait_for(app, lambda: "No session in" in w.sensors_label.text())
    assert w.sensors == []
