"""The analysis window's left column: the rail of tabs, the pills, the steps and the video preview."""

import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6.QtWidgets")
pytest.importorskip("pyqtgraph")

pytestmark = pytest.mark.usefixtures("isolated_qsettings")

from dataclasses import replace  # noqa: E402

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

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


def test_rail_switches_the_pages_and_has_shortcuts(app):
    w = MainWindow()
    assert w.tab_titles == ("Data", "Params", "Calibrate", "Export") and w.rail.current() == 0
    for i in (1, 2, 3, 0):
        w.rail.set_current(i)
        assert w.pages.currentIndex() == i
    actions = {a.text(): a.shortcut().toString() for a in w.view_menu.actions() if a.text().endswith(" tab")}
    assert actions == {"Data tab": "Ctrl+1", "Params tab": "Ctrl+2", "Calibrate tab": "Ctrl+3", "Export tab": "Ctrl+4"}
    w.view_menu.actions()[[a.text() for a in w.view_menu.actions()].index("Calibrate tab")].trigger()
    assert w.rail.current() == 2 and w.pages.currentIndex() == 2
    w.close()


def test_params_pills_group_the_settings_and_mark_what_changed(app, monkeypatch):
    w = MainWindow()
    pills = w.params_panel.pills
    assert pills._titles == ["Participant", "Light", "Signal"]
    page = lambda i: pills.page(i)  # noqa: E731
    shown = w.params_panel.is_shown
    # dynamics sit with the participant; ΔPD with the pupil signal
    assert page(0).isAncestorOf(w.params_panel.dynamics_section)
    assert page(2).isAncestorOf(w.params_panel._pages[2]) and shown("cw_window") and shown("alignment")
    assert page(2).isAncestorOf(w.params_panel._forms[2]._editors["cw_window"])
    assert page(1).isAncestorOf(w.params_panel._forms[1]._editors["l_max"])

    assert all(not b.text().endswith("•") for b in pills._buttons)           # the defaults: no dots
    w.params_panel.set_params(replace(w.params_panel.params(), alignment="none", sensitivity=2.5))
    assert pills._buttons[2].text().endswith("•") and pills._buttons[1].text().endswith("•")
    assert not pills._buttons[0].text().endswith("•")

    # restoring one pill's defaults leaves the others as they are
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    pills.set_current(2)
    w.params_panel.reset_current()
    p = w.params_panel.params()
    assert p.alignment == Parameters().alignment and p.sensitivity == 2.5
    assert not pills._buttons[2].text().endswith("•") and pills._buttons[1].text().endswith("•")
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.No)
    pills.set_current(1)
    w.params_panel.reset_current()
    assert w.params_panel.params().sensitivity == 2.5                         # declined: unchanged
    w.close()


def test_preview_can_be_hidden_and_popped_out(app, varjo_folder):
    w = MainWindow()
    w.resize(1400, 900)
    w.show()
    w.open_recording(varjo_folder)
    assert wait_for(app, lambda: w.result is not None)
    holder = w.preview_holder
    assert holder.is_open() and w.left_split.sizes()[1] > 150
    w.preview_action.setChecked(False)                                      # the P shortcut's action
    app.processEvents()
    assert not holder.is_open() and holder.body.isHidden() and w.left_split.sizes()[1] <= 40
    assert w.preview_action.shortcut().toString() == "P"
    w.preview_action.setChecked(True)
    assert holder.is_open() and w.left_split.sizes()[1] > 150

    holder.toggle_pop_out()                                                  # its own window
    assert holder._window is not None and w.preview.parentWidget() is holder._window
    assert w.left_split.sizes()[1] <= 40
    holder._window.close()
    assert holder._window is None and holder.body.isAncestorOf(w.preview) and holder.is_open()
    assert w.left_split.sizes()[1] > 150
    w.close()


def test_values_toggle_shows_the_measured_values(app, varjo_folder):
    w = MainWindow()
    w.open_recording(varjo_folder)
    assert wait_for(app, lambda: w.result is not None)
    assert w.preview.info.isHidden()
    w.preview_holder.values_button.setChecked(True)
    assert not w.preview.info.isHidden()
    w.close()


def test_warnings_collapse_into_a_badge(app, varjo_folder):
    w = MainWindow()
    w.open_recording(varjo_folder)
    assert wait_for(app, lambda: w.result is not None)
    w.result.warnings[:] = ["First problem.", "Second problem."]
    w._update_state()
    assert not w.warnings_button.isHidden() and w.warnings_button.text() == "2 warnings"
    assert w.warnings_label.isHidden() and "First problem." in w.warnings_label.text()
    assert "First problem" not in w.summary_label.text()                     # the strip stays one short line
    w.warnings_button.setChecked(True)
    assert not w.warnings_label.isHidden()
    w.result.warnings[:] = []
    w._update_state()
    assert w.warnings_button.isHidden() and w.warnings_label.isHidden()
    w.close()


def test_steps_show_what_was_applied(app):
    w = MainWindow()
    w.step_light.set_summary("Applied: light sensitivity ×40")
    assert not w.step_light.summary.isHidden() and "×40" in w.step_light.summary.text()
    w.step_light.set_summary("")
    assert w.step_light.summary.isHidden()
    w.step_sequence.header.click()                                           # a step collapses
    assert w.step_sequence.content.isHidden()
    w.step_sequence.header.click()
    assert not w.step_sequence.content.isHidden()
    w.close()


def test_the_layout_comes_back(app):
    w = MainWindow()
    w.rail.set_current(2)
    w.params_panel.pills.set_current(1)
    w.preview_holder.set_open(False)
    w.close()
    again = MainWindow()
    assert again.rail.current() == 2 and again.pages.currentIndex() == 2
    assert again.params_panel.pills.current() == 1
    assert not again.preview_holder.is_open()
    again.close()


def test_a_missing_lux_log_flags_the_data_tab(app, tmp_path):
    from conftest import write_neon_recording
    from test_neon import FRAME_TIMES, GRAYS

    w = MainWindow()
    w.open_recording(write_neon_recording(tmp_path / "nolux", GRAYS, FRAME_TIMES))
    assert wait_for(app, lambda: w.result is not None and w.recording.lux_values is None)
    assert w.rail._buttons[0].property("alert") is True and "●" in w.rail._buttons[0].text()
    assert not w.lux_box.isHidden()                                           # a glasses recording: lux log buttons
    w.close()
