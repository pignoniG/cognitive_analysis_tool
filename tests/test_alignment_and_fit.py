import csv

import numpy as np
import pytest

from cwtool import devices, luminance, model, pipeline
from cwtool.devices import varjo
from cwtool.fit import fit_calibration
from cwtool.params import Parameters, VideoSettings
from cwtool.recording import Event
from cwtool.video import analyse_video
from conftest import write_varjo_recording


def _load(folder):
    rec = devices.load(folder)
    return rec, analyse_video(rec.scene_video, rec.time, rec.gaze, VideoSettings().for_recording(rec))


def test_alignment_modes(tmp_path):
    # Constant light; the pupil dilates by 0.5 mm (diameter) during a "Task" after a "Rest".
    folder = write_varjo_recording(tmp_path / "rec", [128] * 8,
                                   pupil_mm=lambda t: 2.0 + (0.25 if t >= 4 else 0.0))
    rec, video = _load(folder)
    rec.events = [Event("Rest", 0.0, 4.0), Event("Task", 4.0, 8.0)]
    mean_in = lambda r, a, b: np.nanmean(r.cw[(r.cw_time > a) & (r.cw_time < b)])

    whole = pipeline.run(rec, video, Parameters(alignment="recording"))
    base = pipeline.run(rec, video, Parameters(alignment="baseline", baseline_events="rest"))
    fixed = pipeline.run(rec, video, Parameters(alignment="fixed", pupil_offset=0.123))
    none = pipeline.run(rec, video, Parameters(alignment="none"))

    assert mean_in(base, 0.5, 3.5) == pytest.approx(0.0, abs=0.02)      # rest is the zero
    assert mean_in(base, 4.5, 7.5) == pytest.approx(0.5, abs=0.03)
    assert mean_in(whole, 4.5, 7.5) - mean_in(whole, 0.5, 3.5) == pytest.approx(0.5, abs=0.03)
    assert fixed.offset == 0.123 and none.offset == 0.0
    assert not base.warnings

    missing = pipeline.run(rec, video, Parameters(alignment="baseline", baseline_events="Nothing"))
    assert missing.warnings and missing.offset == pytest.approx(whole.offset)


def test_export_has_sd_units(varjo_folder, tmp_path):
    rec, video = _load(varjo_folder)
    rec.events = [Event("A", 0.0, 2.0)]
    r = pipeline.run(rec, video, Parameters())
    pipeline.export(r, rec, Parameters(), tmp_path)
    row = next(csv.DictReader(open(tmp_path / "rec1_cw.csv")))
    assert float(row["delta_pd_sd"]) == pytest.approx(float(row["delta_pd_mm"]) / r.cw_sd, rel=1e-3)
    ev = next(csv.DictReader(open(tmp_path / "rec1_events.csv")))
    assert "mean_delta_pd_sd" in ev


def test_old_align_mean_key_is_converted():
    assert Parameters.from_dict({"align_mean": False, "version": 2}).alignment == "none"
    assert Parameters.from_dict({"align_mean": True, "version": 2}).alignment == "recording"


def test_fit_recovers_latency_dynamics_scale_and_offset(tmp_path):
    true = dict(delay=0.3, attack=3.0, release=0.4, k=0.9, b=0.35)
    params = Parameters()   # operator's photometric calibration assumed correct
    colours = [0] * 10 + [0, 255, 40, 200, 0, 128, 255, 60, 0, 180] * 2  # 6 s steps below
    step = 6
    rate = 100
    area = varjo.PROFILE.field_area
    t = np.arange(len(colours) * step * rate) / rate
    level = np.array([colours[min(int(x // step), len(colours) - 1)] for x in t])
    lin = luminance.to_linear(np.stack([level] * 3, axis=1), params.gamma)
    L = luminance.absolute_luminance(lin, params.l_min, params.l_max)
    pd = model.watson_yellott(L, params.age, area)
    pd = model.attack_release(model.delay(pd, rate, true["delay"]), rate, true["attack"], true["release"])
    # The participant's true diameter is pd; the device misreports it by k and b (in radius units).
    reported = (pd - true["b"]) / true["k"] / 2
    folder = write_varjo_recording(tmp_path / "cal", [colours[i] for i in range(len(colours))],
                                   seconds_per_level=step, pupil_mm=lambda x: reported[min(int(x * rate), len(t) - 1)])
    rec, video = _load(folder)
    fit = fit_calibration(rec, video, params, start=0.0, end=t[-1])
    assert fit.delay == pytest.approx(true["delay"], abs=0.05)
    assert fit.attack == pytest.approx(true["attack"], rel=0.25)
    assert fit.release == pytest.approx(true["release"], rel=0.35)
    assert fit.pupil_correction == pytest.approx(true["k"], rel=0.03)
    assert fit.pupil_offset == pytest.approx(true["b"], abs=0.1)
    assert fit.rms_after < fit.rms_before / 3
    assert fit.params.alignment == "fixed" and fit.params.dynamics
    assert not fit.notes


def test_fit_on_flat_pupil_fits_offset_only(varjo_folder):
    rec, video = _load(varjo_folder)   # constant pupil
    fit = fit_calibration(rec, video, Parameters(), start=0.0, fit_dynamics=False)
    assert fit.pupil_correction == 1.0 and fit.notes
    assert np.isfinite(fit.rms_after)


def test_fit_warns_when_a_parameter_hits_its_limit(tmp_path):
    # No response delay at all in the synthetic participant: latency ends on the lower limit.
    params = Parameters()
    colours = [0, 255, 40, 200, 0, 128] * 2
    rate, step = 100, 6
    t = np.arange(len(colours) * step * rate) / rate
    level = np.array([colours[int(x // step)] for x in t])
    L = luminance.absolute_luminance(luminance.to_linear(np.stack([level] * 3, axis=1), params.gamma),
                                     params.l_min, params.l_max)
    pd = model.watson_yellott(L, params.age, varjo.PROFILE.field_area)
    folder = write_varjo_recording(tmp_path / "cal", colours, seconds_per_level=step,
                                   pupil_mm=lambda x: pd[min(int(x * rate), len(t) - 1)] / 2)
    rec, video = _load(folder)
    fit = fit_calibration(rec, video, params, start=0.0, end=t[-1], fit_dynamics=False)
    assert fit.delay < 0.05 and fit.notes and "limit" in fit.notes[0]


def test_latency_from_constriction_onsets(tmp_path):
    """With the sequence, the latency comes from the onsets at brightening steps, even when the
    pupil re-dilates after constricting (which the model does not describe)."""
    from cwtool import calibration
    params = Parameters()
    colours = [0, 36, 73, 109, 146, 182, 219, 255, 0, 128, 255, 64, 191]
    step, rate, true_delay = 6, 100, 0.35
    t = np.arange(len(colours) * step * rate) / rate
    level = np.array([colours[min(int(x // step), len(colours) - 1)] for x in t])
    L = luminance.absolute_luminance(luminance.to_linear(np.stack([level] * 3, axis=1), params.gamma),
                                     params.l_min, params.l_max)
    pd = model.watson_yellott(L, params.age, varjo.PROFILE.field_area)
    pd = model.attack_release(model.delay(pd, rate, true_delay), rate, 3.0, 0.3)
    since = (t - true_delay) % step          # time since the pupil started responding to the step
    pd = pd + 0.25 * (1 - np.exp(-np.clip(since - 1.5, 0, None) / 2.0))   # re-dilation after each change
    folder = write_varjo_recording(tmp_path / "cal", colours, seconds_per_level=step,
                                   pupil_mm=lambda x: pd[min(int(x * rate), len(t) - 1)] / 2)
    rec, video = _load(folder)
    seq = calibration.Sequence(tuple(calibration.Step(i * step, (i + 1) * step, (c, c, c), str(c))
                                     for i, c in enumerate(colours)), "test")
    fit = fit_calibration(rec, video, params, start=0.0, sequence=seq)
    assert fit.delay == pytest.approx(true_delay, abs=0.06)
    assert any("constriction onsets" in n for n in fit.notes)


def test_fit_recovers_the_transient(tmp_path):
    """A participant who constricts beyond the steady state after each brightening step and re-dilates
    (pupillary escape): the transient and its escape time constant are recovered, and fitting them
    lowers the error."""
    from cwtool import calibration
    params = Parameters()
    colours = [0, 36, 73, 109, 146, 182, 219, 255, 0, 128, 255, 64, 191, 20, 230]
    step, rate = 8, 100
    true = dict(delay=0.3, attack=3.0, release=0.3, transient=0.6, escape=2.0)
    t = np.arange(len(colours) * step * rate) / rate
    level = np.array([colours[min(int(x // step), len(colours) - 1)] for x in t])
    L = luminance.absolute_luminance(luminance.to_linear(np.stack([level] * 3, axis=1), params.gamma),
                                     params.l_min, params.l_max)
    pd = pipeline.dynamic_pupil(model.watson_yellott(L, params.age, varjo.PROFILE.field_area), L, rate, **true)
    folder = write_varjo_recording(tmp_path / "cal", colours, seconds_per_level=step,
                                   pupil_mm=lambda x: pd[min(int(x * rate), len(t) - 1)] / 2)
    rec, video = _load(folder)
    seq = calibration.Sequence(tuple(calibration.Step(i * step, (i + 1) * step, (c, c, c), str(c))
                                     for i, c in enumerate(colours)), "test")
    without = fit_calibration(rec, video, params, start=0.0, sequence=seq)
    fit = fit_calibration(rec, video, params, start=0.0, sequence=seq, fit_transient=True)
    assert fit.transient == pytest.approx(true["transient"], rel=0.2)
    assert fit.escape == pytest.approx(true["escape"], rel=0.3)
    assert fit.params.transient == fit.transient and fit.params.escape == fit.escape
    assert fit.rms_after < without.rms_after / 2
    assert without.transient == 0.0 and without.params.transient == 0.0


def test_fit_turns_the_transient_off_when_there_is_none(tmp_path):
    params = Parameters()
    colours = [0, 73, 146, 255, 0, 128, 255, 64]
    step, rate = 8, 100
    t = np.arange(len(colours) * step * rate) / rate
    level = np.array([colours[min(int(x // step), len(colours) - 1)] for x in t])
    L = luminance.absolute_luminance(luminance.to_linear(np.stack([level] * 3, axis=1), params.gamma),
                                     params.l_min, params.l_max)
    pd = pipeline.dynamic_pupil(model.watson_yellott(L, params.age, varjo.PROFILE.field_area), L, rate,
                                0.3, 3.0, 0.3)
    folder = write_varjo_recording(tmp_path / "cal", colours, seconds_per_level=step,
                                   pupil_mm=lambda x: pd[min(int(x * rate), len(t) - 1)] / 2)
    rec, video = _load(folder)
    fit = fit_calibration(rec, video, params, start=0.0, end=t[-1], fit_transient=True)
    assert fit.transient == 0.0 and any("No transient" in n for n in fit.notes)
