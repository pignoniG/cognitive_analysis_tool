"""Opening a recording sets up what its folder already holds (the presenter's calibration run file, a display photometry
file), shows the tracking quality, and takes the participant's iris diameter."""

import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6.QtWidgets")
pytest.importorskip("pyqtgraph")

pytestmark = pytest.mark.usefixtures("isolated_qsettings")

from PySide6.QtWidgets import QApplication  # noqa: E402

from cwtool import calibration  # noqa: E402
from cwtool.gui.main_window import MainWindow  # noqa: E402
from cwtool.params import DisplayPhotometry, Parameters, unused_parameters  # noqa: E402
from conftest import write_varjo_recording  # noqa: E402

EPOCH = 1_700_000_000.0


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def wait_for(app, condition, timeout=30):
    end = time.time() + timeout
    while not condition() and time.time() < end:
        app.processEvents()
        time.sleep(0.01)
    return condition()


def write_run_file(path, start_unix):
    """A run file in the calibration presenter's layout: four steps, one second each."""
    rows = [("time", "duration", "r", "g", "b", "label", "onset_unix_ms")]
    for i, (g, label) in enumerate([(0, "Black"), (128, "Gray 128"), (255, "Gray 255"), (0, "Black")]):
        rows.append((float(i), 1.0, g, g, g, label, round((start_unix + i) * 1000)))
    path.write_text("# tool: test\n# status: completed\n" + "\n".join(",".join(map(str, r)) for r in rows) + "\n")


def test_the_folders_run_file_and_photometry_set_up_the_recording(app, tmp_path):
    folder = write_varjo_recording(tmp_path / "rec", [128, 255, 0, 128, 64, 200, 90, 128], pupil_mm=3.0, iris_mm=12.0)
    write_run_file(folder / "session__calibration_run_x.csv", EPOCH + 2.0)
    (folder / "._session__calibration_run_x.csv").write_bytes(b"\x00\x05\x16\x07\xb0")      # macOS's companion file
    DisplayPhotometry("varjo", 0.05, 140.0, 2.2, "measured").save(folder / "display_photometry.json")
    w = MainWindow()
    try:
        w.open_recording(folder)
        assert wait_for(app, lambda: w.recording is not None)
        assert len(w.sequence.steps) == 4
        assert w.sequence_check.isChecked() and w.sequence_start.value() == pytest.approx(2.0, abs=0.02)
        params = w.params_panel.params()
        assert (params.l_min, params.l_max) == (0.05, 140.0)
        text = w.recording_label.text()
        assert "tracking:" in text and "fixed iris of 12.0 mm" in text
    finally:
        w.close()


def test_a_recording_without_them_keeps_the_manual_steps(app, tmp_path):
    folder = write_varjo_recording(tmp_path / "rec", [128, 255, 0, 128], pupil_mm=3.0)
    w = MainWindow()
    try:
        w.open_recording(folder)
        assert wait_for(app, lambda: w.recording is not None)
        assert not w.sequence_check.isChecked()
        assert "tracking:" in w.recording_label.text()
    finally:
        w.close()


def test_the_finders_ignore_other_files(tmp_path):
    (tmp_path / "events.csv").write_text("a,b\n1,2\n")
    (tmp_path / "notes.json").write_text('{"kind": "something else"}')
    (tmp_path / "bad.json").write_text("not json")
    (tmp_path / "._run.csv").write_bytes(b"\xb0\x00")
    assert calibration.find_run_file(tmp_path) is None and DisplayPhotometry.find(tmp_path) is None
    # another log with onset times (the n-back log has them, and sorts after the run file) is not a calibration run
    (tmp_path / "x__nback_log.csv").write_text("block,n,item,digit,onset_unix_ms\n1,2,1,5,1700000001000\n")
    assert calibration.find_run_file(tmp_path) is None
    write_run_file(tmp_path / "a_calibration_run_1.csv", EPOCH)
    write_run_file(tmp_path / "b_calibration_run_2.csv", EPOCH)
    assert calibration.find_run_file(tmp_path).name == "b_calibration_run_2.csv"        # the last by name
    DisplayPhotometry("varjo", 0.01, 100.0).save(tmp_path / "photometry.json")
    assert DisplayPhotometry.find(tmp_path).name == "photometry.json"
    assert calibration.find_run_file(tmp_path / "missing") is None


def test_the_iris_field_is_for_devices_that_assume_an_iris(tmp_path):
    from cwtool import devices
    rec = devices.load(write_varjo_recording(tmp_path / "a", [128] * 4, iris_mm=12.0))
    assert "iris_diameter" not in unused_parameters(rec, Parameters())
    rec = devices.load(write_varjo_recording(tmp_path / "b", [128] * 4))               # no iris in the file
    assert "iris_diameter" in unused_parameters(rec, Parameters())


def test_the_log_is_aligned_to_the_video_in_the_window_and_in_the_export(app, tmp_path):
    """A Varjo recording whose visual log is 0.3 s behind its video: the window aligns it when the video is ready, moves the
    events and the sequence start, and the export says so; the switch undoes it."""
    from cwtool import devices
    colours = [0, 255, 0, 200, 0, 120, 255, 0, 90, 180, 0, 255]
    folder = write_varjo_recording(tmp_path / "rec", colours, seconds_per_level=5.0, fps=30, pupil_mm=3.0)
    epoch = devices.load(folder).epoch_start
    rows = ["Event,Start Time,End Time,Duration (s),Start (unix s),End (unix s)"]
    rows += [f"step,a,b,5,{epoch + 5.0 * i + 0.3:.3f},0" for i in range(len(colours))]
    (folder / "x__visual_log.csv").write_text("\n".join(rows) + "\n")
    (folder / "x_event_log.csv").write_text("Event,Start Time,End Time,Duration (s),Start (unix s),End (unix s)\n"
                                            f"Task,2026-01-01T00:00:00,2026-01-01T00:00:10,10,{epoch + 10.3:.3f},{epoch + 20.3:.3f}\n")
    w = MainWindow()
    try:
        w.open_recording(folder)
        assert wait_for(app, lambda: w.result is not None)
        assert w.log_alignment is not None and w.log_alignment.offset == pytest.approx(-0.3, abs=0.04)
        assert "log aligned to the video" in w.video_label.text()
        assert w.recording.epoch_start == pytest.approx(epoch + 0.3, abs=0.04)
        assert w._raw_recording.epoch_start == epoch and w.recording is not w._raw_recording
        assert w.recording.events and w.recording.events[0].start == pytest.approx(10.0, abs=0.04)
        # exported: the alignment is in the package's description and the events are on the video's clock
        import json
        paths = pipeline_export(w, tmp_path / "out")
        info = json.loads(next(p for p in paths if p.name.endswith("_export.json")).read_text())
        assert info["log alignment"]["n"] >= 8 and info["time"]["unix time of time zero"] == pytest.approx(epoch + 0.3, abs=0.04)
        # the switch undoes it
        w.align_check.setChecked(False)
        assert w.log_alignment is None and w.recording is w._raw_recording
        assert w.recording.events[0].start == pytest.approx(10.3, abs=0.01)
    finally:
        w.close()


def pipeline_export(w, out):
    from cwtool import pipeline
    return pipeline.export(w.result, w.recording, w.params_panel.params(), out, hrv=False)
