"""Tests of the calibration fit on the pupil's time course (:mod:`cwtool.calfit`): one fit for the display route (Varjo)
and the lux sensor and camera routes (glasses), stable where the sequence is placed, with steps that have not settled and
steps at the tracker's ceiling."""

from dataclasses import replace

import numpy as np
import pytest

from cwtool import calfit, calibration, devices, luminance, model, pipeline
from cwtool.devices import varjo
from cwtool.params import Parameters, VideoSettings
from cwtool.photometry import fit_light_response
from cwtool.video import analyse_video
from conftest import write_core_recording, write_varjo_recording
import test_lux_fit as LUX
import test_photometry as PHOTO
import test_quality as QUALITY

ONE_TAU = Parameters(dilation_fast_share=0.0)      # the synthetic participants dilate with one time constant
TRUTH = dict(sensitivity=3.0, gains=PHOTO.TRUE_GAINS / PHOTO.TRUE_GAINS.mean(), offset=0.3, attack=4.0)


@pytest.fixture(scope="module")
def participant(tmp_path_factory):
    """The 20-step staircase watched by a participant of sensitivity 3 (photometry tests): latency 0.3 s, dilation τ 4 s,
    constriction τ 0.4 s, and a device that reads 0.3 mm small."""
    return PHOTO._participant_recording(tmp_path_factory.mktemp("calfit") / "p", sensitivity=3.0, gains=PHOTO.TRUE_GAINS)


def test_the_display_route_recovers_the_participant_and_does_not_move_with_the_start(participant):
    rec, video, seq = participant
    fit = calfit.fit_calibration(rec, video, ONE_TAU, PHOTO.LEAD, seq, fit_offset=True)
    assert fit.route == "display"
    assert fit.values["sensitivity"] == pytest.approx(TRUTH["sensitivity"], rel=0.1)
    assert [fit.values[k] for k in ("gain_r", "gain_g", "gain_b")] == pytest.approx(TRUTH["gains"], rel=0.05)
    assert fit.values["pupil_offset"] == pytest.approx(TRUTH["offset"], abs=0.05)
    assert fit.values["attack"] == pytest.approx(TRUTH["attack"], rel=0.2)
    assert fit.fit_rms_after < 0.05 < fit.fit_rms_before and fit.correlation > 0.99
    assert fit.onsets >= 3 and "transient" not in fit.values                     # the transient is opt-in
    p = fit.params
    assert p.dynamics and p.sensitivity == fit.values["sensitivity"] and p.alignment == "fixed"
    assert p.l_max == Parameters().l_max and p.pupil_correction == 1.0             # neither the display nor the scale
    assert any("effective" in n for n in fit.notes)
    # placed 0.3 s late, the step-level fit moves by half; this one does not
    late = calfit.fit_calibration(rec, video, ONE_TAU, PHOTO.LEAD + 0.3, seq, fit_offset=True)
    assert late.values["sensitivity"] == pytest.approx(fit.values["sensitivity"], rel=0.02)
    old = [fit_light_response(rec, video, ONE_TAU, PHOTO.LEAD + d, seq, fit_offset=True).sensitivity for d in (0, 0.3)]
    assert abs(np.log(old[1] / old[0])) > 5 * abs(np.log(late.values["sensitivity"] / fit.values["sensitivity"]))


def test_steps_that_have_not_settled_are_followed_not_read_as_levels(tmp_path):
    """A slow dilation (τ 10 s) on 10 s steps: the darker steps end short of their level. The step-level fit reads them as
    levels; the time course does not."""
    p = ONE_TAU
    seq = calibration.scaled(calibration.STAIRCASE_20, PHOTO.STEP / calibration.STEP_SECONDS)
    colours = [(0, 0, 0)] * int(PHOTO.LEAD / PHOTO.STEP) + [s.rgb for s in seq.steps]
    rate = PHOTO.RATE
    t = np.arange(len(colours) * PHOTO.STEP * rate) / rate
    rgb = np.array([colours[min(int(x // PHOTO.STEP), len(colours) - 1)] for x in t], dtype=float)
    L = luminance.absolute_luminance(luminance.to_linear(rgb, p.gamma), p.l_min, p.l_max, (1.0, 1.0, 1.0))
    pd = model.attack_release(model.delay(model.watson_yellott(L * 3.0, p.age, varjo.PROFILE.field_area), rate, 0.3),
                              rate, 10.0, 0.4)
    pd = pd + np.random.default_rng(1).normal(0, 0.02, len(pd))
    folder = write_varjo_recording(tmp_path / "slow", colours, seconds_per_level=PHOTO.STEP, iris_mm=12.0,
                                   pupil_mm=lambda x: float(pd[min(int(x * rate), len(t) - 1)]))
    rec = devices.load(folder)
    video = analyse_video(rec.scene_video, rec.time, rec.gaze, VideoSettings().for_recording(rec))
    fit = calfit.fit_calibration(rec, video, p, PHOTO.LEAD, seq, fit_gains=False)
    old = fit_light_response(rec, video, p, PHOTO.LEAD, seq, fit_gains=False)
    assert fit.values["sensitivity"] == pytest.approx(3.0, rel=0.15)
    assert fit.values["attack"] == pytest.approx(10.0, rel=0.25)
    assert abs(np.log(fit.values["sensitivity"] / 3.0)) < abs(np.log(old.sensitivity / 3.0))


def test_steps_at_the_tracker_ceiling_are_lower_bounds(tmp_path):
    rec, video, seq = QUALITY._clipped_participant(tmp_path / "flagged", True)
    flagged = calfit.fit_calibration(rec, video, Parameters(), QUALITY.LEAD, seq, fit_gains=False, fit_dynamics=False)
    rec2, video2, _ = QUALITY._clipped_participant(tmp_path / "plain", False)
    plain = calfit.fit_calibration(rec2, video2, Parameters(), QUALITY.LEAD, seq, fit_gains=False, fit_dynamics=False)
    assert any("ceiling" in n for n in flagged.notes)
    err = lambda f: abs(np.log(f.values["sensitivity"] / 3.0))
    assert err(flagged) < err(plain) and err(flagged) < np.log(1.25)


def test_the_lux_route_fits_the_sensitivity_and_the_offset(tmp_path):
    params = Parameters(delay=0.0, dynamics=False, alignment="none")
    rec, video = LUX.synthetic(tmp_path, sensitivity=0.4, offset=0.35, params=params)
    fit = calfit.fit_calibration(rec, video, params, 0.0, LUX.STEPS, fit_dynamics=False)
    assert fit.route == "lux sensor"
    assert fit.values["sensitivity"] == pytest.approx(0.4, rel=0.1)
    assert fit.values["pupil_offset"] == pytest.approx(0.35, abs=0.05)
    assert "gain_r" not in fit.values                                     # the colour weights stay as they are
    assert fit.params.alignment == "fixed" and fit.params.pupil_offset == fit.values["pupil_offset"]
    assert fit.fit_rms_after < 0.05


def _values(p: Parameters) -> dict:
    return dict(sensitivity=p.sensitivity, gain_r=p.gain_r, gain_g=p.gain_g, gain_b=p.gain_b, gamma=p.gamma,
                l_min=p.l_min, fixation_weight=p.fixation_weight)


@pytest.mark.parametrize("route", ["display", "lux sensor", "lux sensor without video", "camera, fixed exposure",
                                   "camera, relative"])
def test_the_fit_builds_the_luminance_as_the_analysis_does(tmp_path, route):
    if route == "display":
        folder = write_varjo_recording(tmp_path / "v", [0, 255, 60, (200, 40, 90), 128], seconds_per_level=2.0)
        params = Parameters(gain_r=1.4, gain_g=0.8, gain_b=1.1, gamma=2.0, fixation_weight=0.4)
    else:
        lux = None if route == "camera, relative" else LUX.lux
        folder = write_core_recording(tmp_path / "c", LUX.GRAYS, LUX.FRAME_TIMES, lux=lux)
        params = Parameters(lux_use_video=route != "lux sensor without video",
                            camera_exposure="fixed" if route == "camera, fixed exposure" else "auto")
    rec = devices.load(folder)
    video = analyse_video(rec.scene_video, rec.time, rec.gaze, VideoSettings().for_recording(rec),
                          frame_times=rec.scene_frame_times)
    if route == "camera, fixed exposure":
        rec = replace(rec, lux_values=None, lux_time=None)
    prep = pipeline.prepare(rec, video, params)
    assert prep.mode == route.replace(" without video", "")
    t = prep.time[(prep.time > prep.time[0] + 1) & (prep.time < prep.time[-1] - 1)]
    built = calfit._luminance_model(rec, video, params, prep.mode, t)(_values(params))
    assert built == pytest.approx(np.interp(t, prep.time, prep.luminance), rel=0.02)


def test_a_fit_can_be_cancelled_and_the_transient_is_opt_in(participant):
    rec, video, seq = participant
    with pytest.raises(InterruptedError):
        calfit.fit_calibration(rec, video, Parameters(), PHOTO.LEAD, seq, cancelled=lambda: True)
    # the participant has no transient: asked for, it is found too small and left off, with a note
    fit = calfit.fit_calibration(rec, video, ONE_TAU, PHOTO.LEAD, seq, fit_offset=True, fit_transient=True)
    assert fit.params.transient == 0.0 and "transient" not in fit.values
    assert any("No transient" in n for n in fit.notes)
    # without the dynamics the time constants are neither fitted nor switched on
    still = calfit.fit_calibration(rec, video, Parameters(dynamics=False), PHOTO.LEAD, seq, fit_dynamics=False,
                                   fit_offset=True)
    assert not still.params.dynamics and "attack" not in still.values


def test_a_two_part_dilation_is_followed(tmp_path):
    """A participant who re-dilates with a fast part (60 %, 1 s) and a slow one (20 s): with the two-part dilation the fit
    finds the slow part and follows the pupil; with one time constant it does worse."""
    p = Parameters()
    seq = calibration.scaled(calibration.STAIRCASE_20, PHOTO.STEP / calibration.STEP_SECONDS)
    colours = [(0, 0, 0)] * int(PHOTO.LEAD / PHOTO.STEP) + [s.rgb for s in seq.steps]
    rate = PHOTO.RATE
    t = np.arange(len(colours) * PHOTO.STEP * rate) / rate
    rgb = np.array([colours[min(int(x // PHOTO.STEP), len(colours) - 1)] for x in t], dtype=float)
    L = luminance.absolute_luminance(luminance.to_linear(rgb, p.gamma), p.l_min, p.l_max, (1.0, 1.0, 1.0))
    pd = model.attack_release(model.delay(model.watson_yellott(L * 3.0, p.age, varjo.PROFILE.field_area), rate, 0.3),
                              rate, 20.0, 0.4, 1, fast_share=0.6, fast_attack=1.0)
    pd = pd + np.random.default_rng(2).normal(0, 0.02, len(pd))
    folder = write_varjo_recording(tmp_path / "two", colours, seconds_per_level=PHOTO.STEP, iris_mm=12.0,
                                   pupil_mm=lambda x: float(pd[min(int(x * rate), len(t) - 1)]))
    rec = devices.load(folder)
    video = analyse_video(rec.scene_video, rec.time, rec.gaze, VideoSettings().for_recording(rec))
    two = calfit.fit_calibration(rec, video, replace(p, constriction_stages=1), PHOTO.LEAD, seq, fit_gains=False)
    one = calfit.fit_calibration(rec, video, replace(p, constriction_stages=1, dilation_fast_share=0.0), PHOTO.LEAD, seq,
                                 fit_gains=False)
    assert two.values["attack"] == pytest.approx(20.0, rel=0.3)
    assert two.values["sensitivity"] == pytest.approx(3.0, rel=0.15)
    assert two.fit_rms_after < 0.05 and two.fit_rms_after < one.fit_rms_after / 2
    assert two.params.dilation_fast_share == 0.6                      # fixed, not fitted
