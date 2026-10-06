"""Trimming the export and packing the logger's sensor data with it."""

import csv
import json

import numpy as np
import pytest

from cwtool import cli, devices, pipeline, sensors
from cwtool.params import Parameters, VideoSettings
from cwtool.recording import Event
from cwtool.trim import TRIM_FILE, Trim
from cwtool.video import analyse_video
from conftest import write_varjo_recording


def rows(path):
    return list(csv.DictReader(open(path)))


# --- Trim

def test_trim_keeps_range_and_leaves_out_segments():
    t = Trim(start=5, end=100, exclude=[(10, 20), (15, 30), (50, 51), (70, 70)])
    assert t.exclude == [(10.0, 30.0), (50.0, 51.0)]  # merged, empty one dropped
    x = np.array([0, 5, 9.9, 10, 25, 30, 49, 50, 51, 100, 101, np.nan])
    #                F  T   T    F   F   T   T   F   T    T    F    F   (a segment keeps its start, not its end)
    assert t.keep_mask(x).tolist() == [False, True, True, False, False, True, True, False, True, True, False, False]
    assert t.kept_spans(0, 120) == [(5, 10.0), (30.0, 50.0), (51.0, 100)]
    assert Trim().active is False and Trim().keep_mask([1, 2]).all() and Trim().kept_spans(0, 9) == [(0, 9)]
    assert Trim(exclude=[(2, 4)]).keep_mask([1, 2, 3, 4], lo=1.5).tolist() == [False, False, False, True]


def test_trim_file_round_trip_and_bad_files(tmp_path):
    t = Trim(2.0, None, [(5, 9)])
    t.save(tmp_path / TRIM_FILE)
    back = Trim.load(tmp_path / TRIM_FILE)
    assert (back.start, back.end, back.exclude) == (2.0, None, [(5.0, 9.0)])
    assert not Trim.load(tmp_path / "missing.json").active
    (tmp_path / "bad.json").write_text("{not json")
    assert not Trim.load(tmp_path / "bad.json").active


# --- sensor files

def write_session(folder, epoch, seconds=12):
    """A logger session folder: a Shimmer (wide), an EmotiBit (long), a lux log and an event log."""
    folder.mkdir(parents=True, exist_ok=True)
    with open(folder / "shimmer.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["unix time (s)", "device time (s)", "accel_ln_x", "exg_ads1292r_1_ch1_24bit"])
        for i in range(int(seconds * 50)):
            t = i / 50
            w.writerow([f"{epoch + t - 2:.6f}", f"{t:.4f}", 2000 + i % 7, 1000 * np.sin(t)])
    with open(folder / "emotibit.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["unix time (s)", "signal", "value"])
        for i in range(int(seconds * 15)):
            t = i / 15
            w.writerow([f"{epoch + t - 2:.6f}", "EDA", 0.03 + t / 100])
            if i % 2 == 0:
                w.writerow([f"{epoch + t - 2:.6f}", "TEMP1", 31.5])
    (folder / "lux.csv").write_text("unix time (s),lux\n" + "".join(f"{epoch + i / 10:.3f},{i}\n" for i in range(100)))
    (folder / "session.json").write_text(json.dumps({"sources": {
        "lux": {"file": "lux.csv", "kind": "lux"},
        "shimmer": {"file": "shimmer.csv", "kind": "shimmer"},
        "emotibit": {"file": "emotibit.csv", "kind": "emotibit"}}}))
    return folder


def test_sensor_files_are_found_read_and_cut(tmp_path):
    session = write_session(tmp_path / "session", epoch=1_700_000_000.0)
    found = sensors.find_sensor_files(session)
    assert [(p.name, k) for p, k in found] == [("shimmer.csv", "shimmer"), ("emotibit.csv", "emotibit")]  # no lux

    loaded = sensors.load_sensors(session, 1_700_000_000.0, 4.0, margin=0.0)
    shimmer, emotibit = loaded
    assert shimmer.unix[0] >= 1_700_000_000.0 and shimmer.unix[-1] <= 1_700_000_004.0
    assert shimmer.signals() == ["device time (s)", "accel_ln_x", "exg_ads1292r_1_ch1_24bit"]
    assert emotibit.long and emotibit.signals() == ["EDA", "TEMP1"]
    t, v = emotibit.series("TEMP1")
    assert (v == 31.5).all() and len(t) < len(emotibit)
    # without a manifest the files are found by their first column
    (session / "session.json").unlink()
    assert [p.name for p, _ in sensors.find_sensor_files(session)] == ["emotibit.csv", "shimmer.csv"]
    # a file that is no sensor file is refused
    (tmp_path / "x.csv").write_text("a,b\n1,2\n")
    with pytest.raises(ValueError):
        sensors.read_sensor(tmp_path / "x.csv")


# --- the export package

def _load(folder):
    rec = devices.load(folder)
    return rec, analyse_video(rec.scene_video, rec.time, rec.gaze, VideoSettings().for_recording(rec))


@pytest.fixture
def analysed(tmp_path):
    folder = write_varjo_recording(tmp_path / "rec", [128, 255, 0, 128, 64, 200, 90, 128], pupil_mm=3.0)
    rec, video = _load(folder)
    rec.events = [Event("Rest", 0.0, 3.0), Event("Calibration", 3.0, 5.0), Event("Task", 5.0, 8.0)]
    return rec, pipeline.run(rec, video, Parameters()), tmp_path


def test_export_without_trim_is_unchanged_and_has_a_manifest(analysed):
    rec, result, tmp = analysed
    paths = pipeline.export(result, rec, Parameters(), tmp / "out")
    names = sorted(p.name for p in paths)
    assert names == ["rec_cw.csv", "rec_events.csv", "rec_export.json", "rec_params.json", "rec_pupil.csv"]
    assert len(rows(tmp / "out/rec_pupil.csv")) == len(result.time)
    manifest = json.loads((tmp / "out/rec_export.json").read_text())
    assert manifest["trim"] is None and manifest["delta_pd_sd"] == "recording"
    assert sorted(manifest["files"]) == names


def test_export_trim_cuts_every_file_and_events(analysed):
    rec, result, tmp = analysed
    session = write_session(tmp / "session", rec.epoch_start + float(rec.time[0]))
    found = sensors.load_sensors(session, rec.epoch_start + float(rec.time[0]), float(rec.time[-1] - rec.time[0]))
    trim = Trim(start=1.0, end=7.0, exclude=[(3.0, 5.0)])
    paths = pipeline.export(result, rec, Parameters(), tmp / "out", trim=trim, sensors=found)
    assert {"rec_shimmer.csv", "rec_emotibit.csv", "rec_export.json"} <= {p.name for p in paths}

    for name, col in (("pupil", "timestamp_relative"), ("cw", "timestamp_relative"),
                      ("shimmer", "timestamp_relative"), ("emotibit", "timestamp_relative")):
        t = np.array([float(r[col]) for r in rows(tmp / f"out/rec_{name}.csv")])
        assert len(t) and t.min() >= 1.0 and t.max() <= 7.0, name
        assert not ((t >= 3.0) & (t < 5.0)).any(), name   # the calibration is left out
    # the unix and relative times agree
    r = rows(tmp / "out/rec_shimmer.csv")[0]
    assert float(r["timestamp_unix"]) - float(r["timestamp_relative"]) == pytest.approx(rec.epoch_start, abs=1e-3)
    assert rows(tmp / "out/rec_shimmer.csv")[0]["exg_ads1292r_1_ch1_24bit"] != ""
    assert set(rows(tmp / "out/rec_emotibit.csv")[0]) == {"timestamp_unix", "timestamp_relative", "signal", "value"}

    # events: the excluded one is dropped, the others are clipped to the range
    ev = {r["event"]: r for r in rows(tmp / "out/rec_events.csv")}
    assert set(ev) == {"Rest", "Task"} and float(ev["Rest"]["start_relative"]) == 1.0
    assert float(ev["Task"]["end_relative"]) == 7.0

    # SD units use the kept data
    kept = np.array([float(r["delta_pd_mm"]) for r in rows(tmp / "out/rec_cw.csv")])
    sd = np.array([float(r["delta_pd_sd"]) for r in rows(tmp / "out/rec_cw.csv")])
    assert np.allclose(sd, kept / kept.std(), atol=1e-4)
    manifest = json.loads((tmp / "out/rec_export.json").read_text())
    assert manifest["delta_pd_sd"] == "kept data" and manifest["kept seconds"] == pytest.approx(4.0)
    assert manifest["trim"]["exclude"] == [[3.0, 5.0]]
    assert {s["kind"] for s in manifest["sensors"]} == {"shimmer", "emotibit"}


def test_export_includes_the_lux_log_when_there_is_one(analysed):
    rec, result, tmp = analysed
    rec.lux_time, rec.lux_values = np.linspace(-1, 9, 101), np.arange(101.0)
    pipeline.export(result, rec, Parameters(), tmp / "out", trim=Trim(exclude=[(2, 4)]))
    t = np.array([float(r["timestamp_relative"]) for r in rows(tmp / "out/rec_lux.csv")])
    assert t.min() >= 0.0 and t.max() <= float(rec.time[-1]) and not ((t >= 2) & (t < 4)).any()


def test_cli_trims_and_packs_sensors(tmp_path, capsys):
    folder = write_varjo_recording(tmp_path / "rec", [128, 255, 0, 128, 64, 200, 90, 128], pupil_mm=3.0)
    rec = devices.load(folder)
    session = write_session(tmp_path / "session", rec.epoch_start + float(rec.time[0]))
    out = tmp_path / "out"
    assert cli.main([str(folder), "--out", str(out), "--sensors", str(session), "--start", "1", "--end", "7",
                     "--exclude", "3", "5"]) == 0
    assert (out / "rec_shimmer.csv").exists() and (out / "rec_export.json").exists()
    t = np.array([float(r["timestamp_relative"]) for r in rows(out / "rec_cw.csv")])
    assert t.min() >= 1.0 and t.max() <= 7.0 and not ((t >= 3) & (t < 5)).any()


def test_cli_uses_the_trim_saved_with_the_recording(tmp_path, capsys):
    folder = write_varjo_recording(tmp_path / "rec", [128, 255, 0, 128, 64, 200, 90, 128], pupil_mm=3.0)
    Trim(start=2.0, end=6.0).save(folder / TRIM_FILE)
    assert cli.main([str(folder), "--out", str(tmp_path / "out")]) == 0
    assert "saved with the recording" in capsys.readouterr().out
    t = np.array([float(r["timestamp_relative"]) for r in rows(tmp_path / "out/rec_cw.csv")])
    assert t.min() >= 2.0 and t.max() <= 6.0
