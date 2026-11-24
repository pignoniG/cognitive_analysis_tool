"""Tests of the lux estimated from the AS7341's bands (cwtool.spectral): the weights, the estimate on the datasheet's test
light, and each glasses reader (Pupil Core, Neon, Tobii Pro Glasses 3) taking it when there is no TSL2591 log, with the
same result as the TSL2591's for the same lux."""

import csv
import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest

from cwtool import devices, lux, pipeline, spectral
from cwtool.params import Parameters, VideoSettings
from cwtool.video import analyse_video
from conftest import write_core_recording, write_neon_recording, write_tobii_g3_recording

TOOL = Path(__file__).resolve().parent.parent / "tools" / "as7341_weights.py"
# the bands of the datasheet's warm white test light (typical counts at 64x, 27.8 ms, in basic counts), scaled to 1 lux
WARM = np.array([55, 110, 210, 390, 590, 840, 1350, 1070]) / (64 * 27.8)
PER_LUX = WARM / float(WARM @ np.asarray(spectral.WEIGHTS))
HEADER = (["unix time (s)", "device time (s)"] + list(spectral.BAND_COLUMNS)
          + ["clear", "nir", "gain", "integration (ms)", "saturated"])


def _tool():
    spec = importlib.util.spec_from_file_location("as7341_weights", TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def as7341_from_lux_log(folder: Path, keep_tsl: bool = False, saturated_after: float = np.inf) -> None:
    """Write the fixture's lux log (1_1_1.csv) as an AS7341 file whose bands give the same lux, as the logger does
    (with its session.json), and remove the lux log unless ``keep_tsl``."""
    tsl = folder / "1_1_1.csv"
    rows = [(float(r[0]) / 1000, float(r[4])) for r in csv.reader(open(tsl))]
    with open(folder / spectral.FILE_NAME, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(HEADER)
        for i, (unix, value) in enumerate(rows):
            sat = int(unix - rows[0][0] > saturated_after)
            w.writerow([f"{unix:.6f}", f"{i * 0.1:.3f}"] + [f"{b:.9g}" for b in PER_LUX * value]
                       + ["0.1", "0", "512", "50.04", sat])
    (folder / "session.json").write_text(json.dumps({"clock mapping": "lower envelope", "sources": {
        "as7341": {"file": spectral.FILE_NAME, "kind": "as7341"}}}))
    if not keep_tsl:
        tsl.unlink()


def test_weights_are_the_tools_fit():
    assert _tool().fit() == pytest.approx(np.asarray(spectral.WEIGHTS), rel=1e-5)


def test_the_datasheets_test_light_is_estimated_within_a_few_percent():
    tool = _tool()
    led = tool._column("as7341_test_leds.csv", "warm white 2700 K")
    led = led / led.sum() * tool.TEST_IRRADIANCE
    true_lux = float(led @ tool.photopic())
    bands = led @ tool.responsivities().T
    assert bands == pytest.approx(WARM, rel=1e-6)                     # the model gives the datasheet's typical counts
    assert spectral.photopic_lux(bands[None])[0] == pytest.approx(true_lux, rel=0.03)
    assert true_lux == pytest.approx(273, rel=0.02)


def test_saturated_spectra_are_left_out_and_tsl2591_comes_first(tmp_path):
    folder = write_core_recording(tmp_path / "core", [128] * 30, np.arange(30) / 30, lux=lambda t: 50.0)
    as7341_from_lux_log(folder, keep_tsl=True, saturated_after=2.0)
    rec = devices.load(folder)
    assert rec.lux_sensor == "TSL2591" and "lux sensor" in rec.route
    (folder / "1_1_1.csv").unlink()
    rec = devices.load(folder)
    assert rec.lux_sensor == "AS7341" and "AS7341" in rec.route and any("AS7341" in n for n in rec.notes)
    assert np.allclose(rec.lux_values, 50.0) and rec.lux_time.max() < 1.05     # the saturated ones are gone
    t, v = spectral.read(folder, rec.epoch_start, 3.0)
    assert len(t) == len(rec.lux_time)


def _pupil_core(folder, value):
    return write_core_recording(folder, [40] * 45 + [220] * 45, np.arange(90) / 30, lux=value)


def _neon(folder, value):
    return write_neon_recording(folder, [40] * 45 + [220] * 45, np.arange(90) / 30, lux=value)


def _tobii(folder, value):
    return write_tobii_g3_recording(folder, [40] * 50 + [220] * 50, lux=value)


@pytest.mark.parametrize("write", [_pupil_core, _neon, _tobii], ids=["pupil_core", "neon", "tobii_g3"])
def test_every_glasses_reader_gives_the_same_result_from_either_sensor(tmp_path, write):
    def ramp(t):
        return 100.0 + 40.0 * t

    results = {}
    for sensor in ("TSL2591", "AS7341"):
        folder = write(tmp_path / sensor, ramp)
        if sensor == "AS7341":
            as7341_from_lux_log(folder)
        rec = devices.load(folder)
        assert rec.lux_sensor == sensor
        video = analyse_video(rec.scene_video, rec.time, rec.gaze, VideoSettings().for_recording(rec),
                              frame_times=rec.scene_frame_times)
        results[sensor] = pipeline.run(rec, video, Parameters(analysis_rate=0))
    a, b = results["TSL2591"], results["AS7341"]
    assert a.luminance_mode == b.luminance_mode == "lux sensor"
    assert np.allclose(a.luminance, b.luminance, rtol=1e-6, equal_nan=True)
    assert np.allclose(a.cw, b.cw, rtol=1e-6, atol=1e-9, equal_nan=True)


def test_the_running_median_is_shorter_for_the_as7341():
    assert lux.smoothing("AS7341") == 3 and lux.smoothing("TSL2591") == lux.smoothing("") == 5
    spike = np.array([1.0, 1, 1, 9, 9, 1, 1, 1])                      # two spectra of a brief light
    assert lux.smooth(spike, 3)[3:5].tolist() == [9.0, 9.0] and lux.smooth(spike, 5).max() == 1.0


def test_export_names_the_estimate(tmp_path):
    folder = _pupil_core(tmp_path / "core", lambda t: 80.0)
    as7341_from_lux_log(folder)
    rec = devices.load(folder)
    video = analyse_video(rec.scene_video, rec.time, rec.gaze, VideoSettings().for_recording(rec),
                          frame_times=rec.scene_frame_times)
    res = pipeline.run(rec, video, Parameters())
    paths = pipeline.export(res, rec, Parameters(), tmp_path / "out")
    header = next(csv.reader(open(next(p for p in paths if p.name.endswith("_lux.csv")))))
    assert header[-1] == "lux (AS7341 estimate)"
