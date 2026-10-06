"""The main window: sensor data under ΔPD, the export range, and the packaged export."""

import csv
import os
import time

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6.QtWidgets")
pytest.importorskip("pyqtgraph")

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
    names = sorted(p.name for p in out.iterdir())
    assert {"rec_pupil.csv", "rec_cw.csv", "rec_shimmer.csv", "rec_emotibit.csv", "rec_export.json",
            "rec_params.json"} <= set(names)
    t = np.array([float(r["timestamp_relative"]) for r in rows(out / "rec_shimmer.csv")])
    assert t.min() >= 1.0 and t.max() <= 7.0 and not ((t >= 3.0) & (t < 5.0)).any()
    assert "trimmed" in w.statusBar().currentMessage() and "sensor file" in w.statusBar().currentMessage()
