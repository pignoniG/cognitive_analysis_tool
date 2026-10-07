"""Tests of the display photometry fit: sensitivity, channel weights, black level and the photometry and participant
files.
"""

import json

import numpy as np
import pytest

from cwtool import calibration, devices, luminance, model
from cwtool.devices import varjo
from cwtool.params import DisplayPhotometry, Parameters, VideoSettings
from cwtool.photometry import fit_light_response, step_level
from cwtool.video import analyse_video
from conftest import write_varjo_recording

STEP = 10.0          # s, as in the April 2026 Varjo recording
LEAD = 20.0          # s of black before the sequence
RATE = 100


def _participant_recording(folder, sensitivity, gains, k=1.0, b=0.3, noise=0.02, seed=0):
    """Varjo recording of the 20-step staircase (10 s steps, as in April 2026) watched by a participant with the given
    light sensitivity and channel weights, on a display matching the default photometry."""
    p = Parameters()
    seq = calibration.scaled(calibration.STAIRCASE_20, STEP / calibration.STEP_SECONDS)
    colours = [(0, 0, 0)] * int(LEAD / STEP) + [s.rgb for s in seq.steps]
    t = np.arange(len(colours) * STEP * RATE) / RATE
    rgb = np.array([colours[min(int(x // STEP), len(colours) - 1)] for x in t], dtype=float)
    L = luminance.absolute_luminance(luminance.to_linear(rgb, p.gamma), p.l_min, p.l_max, gains)
    pd = model.watson_yellott(L * sensitivity, p.age, varjo.PROFILE.field_area)
    pd = model.attack_release(model.delay(pd, RATE, 0.3), RATE, 4.0, 0.4)
    pd = pd + np.random.default_rng(seed).normal(0, noise, len(pd))
    reported = (pd - b) / k / 2          # the device misreports scale and offset (radius units); k is undone by hand
    folder = write_varjo_recording(folder, colours, seconds_per_level=STEP,
                                   pupil_mm=lambda x: reported[min(int(x * RATE), len(t) - 1)])
    rec = devices.load(folder)
    video = analyse_video(rec.scene_video, rec.time, rec.gaze, VideoSettings().for_recording(rec))
    return rec, video, seq


TRUE_GAINS = np.array([1.5, 0.7, 0.8])


@pytest.fixture(scope="module")
def participant(tmp_path_factory):
    return _participant_recording(tmp_path_factory.mktemp("photometry") / "p", sensitivity=3.0, gains=TRUE_GAINS)


def test_recovers_sensitivity_and_channel_weights(participant):
    true_gains = TRUE_GAINS
    rec, video, seq = participant
    fit = fit_light_response(rec, video, Parameters(), start=LEAD, sequence=seq, fit_offset=True)
    # Dilation (τ 4 s) has not finished by the end of the 10 s darker steps, and step levels are not
    # extrapolated (open issue 40), so the dark steps read small: the sensitivity, which the sequence
    # determines only loosely, comes out about a third high (4.0), with the true value inside its interval.
    assert fit.sensitivity_range[0] < 3.0 < fit.sensitivity_range[1]
    assert fit.sensitivity == pytest.approx(3.0, rel=0.4)
    assert np.array(fit.gains) == pytest.approx(true_gains / true_gains.mean(), rel=0.05)
    assert fit.pupil_correction == 1.0                      # the scale is not fitted
    assert fit.pupil_offset == pytest.approx(0.3, abs=0.25)
    assert sum(not s.settled for s in fit.steps) == 2      # the two steps after a brighter one that dilate
    assert fit.rms_after < fit.rms_before / 2 and fit.rms_after < 0.1
    assert len(fit.steps) == 20
    assert fit.params.sensitivity == fit.sensitivity and fit.params.l_max == Parameters().l_max


def test_the_scale_is_set_by_hand_not_fitted(tmp_path):
    """A device that misreports the scale by 0.9: the fit uses the correction given and does not change it."""
    rec, video, seq = _participant_recording(tmp_path / "p", sensitivity=3.0, gains=TRUE_GAINS, k=0.9)
    by_hand = fit_light_response(rec, video, Parameters(pupil_correction=0.9), start=LEAD, sequence=seq,
                                fit_offset=True)
    ignored = fit_light_response(rec, video, Parameters(), start=LEAD, sequence=seq, fit_offset=True)
    assert by_hand.pupil_correction == 0.9 and by_hand.params.pupil_correction == 0.9
    assert ignored.pupil_correction == 1.0                    # no attempt to find the 0.9 by itself
    assert by_hand.rms_after < 0.1 and by_hand.rms_after < ignored.rms_after
    # A wrong scale is mostly absorbed by the sensitivity and the offset (the trade-off that makes it unfittable):
    assert ignored.rms_after < 0.2


def test_offset_is_left_alone_unless_asked(participant):
    rec, video, seq = participant
    p = Parameters(pupil_offset=0.5, alignment="recording")
    fit = fit_light_response(rec, video, p, start=LEAD, sequence=seq)
    assert fit.pupil_offset == 0.5 and fit.params.alignment == "recording"
    assert fit.params.l_min == p.l_min and fit.l_max == p.l_max


def test_black_level_is_fitted_with_white_held(tmp_path):
    """A display whose black is 50x brighter than nominal: Lmin is recovered, Lmax is not touched."""
    rec, video, seq = _participant_recording(tmp_path / "p", sensitivity=1.0, gains=np.ones(3), b=0.0, seed=3)
    # the recording is made at the default photometry; fit from a nominal black that is 50x too dark
    p = Parameters(l_min=Parameters().l_min / 50)
    fit = fit_light_response(rec, video, p, start=LEAD, sequence=seq, fit_gains=False, fit_black=True)
    assert fit.l_max == p.l_max and fit.params.l_max == p.l_max
    assert fit.l_min > p.l_min * 5
    assert any("black level" in n for n in fit.notes)


def test_display_notes_check_the_photometry():
    from cwtool.luminance import display_notes
    assert display_notes(0.01, 100.0, varjo.PROFILE) == []
    assert display_notes(0.01, 215.0, varjo.PROFILE) == []                 # within 10 % of 200 cd/m²
    assert "peak luminance" in display_notes(0.01, 250.0, varjo.PROFILE)[0]
    assert "not below" in display_notes(100.0, 100.0, varjo.PROFILE)[0]
    assert "implausibly low" in display_notes(5.0, 100.0, varjo.PROFILE)[0]


def test_display_error_is_absorbed_by_the_sensitivity(participant):
    """A datasheet luminance twice the real one gives half the sensitivity and the same predictions."""
    rec, video, seq = participant
    right = fit_light_response(rec, video, Parameters(), start=LEAD, sequence=seq)
    wrong = fit_light_response(rec, video, Parameters(l_min=0.02, l_max=200.0), start=LEAD, sequence=seq)
    assert wrong.sensitivity == pytest.approx(right.sensitivity / 2, rel=0.05)
    assert wrong.expected_after == pytest.approx(right.expected_after, abs=0.02)


def test_step_level_is_the_end_of_the_step_without_extrapolation():
    t = np.arange(0, 9.5, 0.01)
    dilating = 5.0 + (3.0 - 5.0) * np.exp(-t / 5.0)    # τ = 5 s: 85 % of the way after 9.5 s
    tail = dilating[t >= 0.7 * t[-1]].mean()
    value, se, settled = step_level(t, dilating, after_darker=True)
    assert value == pytest.approx(tail) and not settled   # short of 5 mm, flagged
    value2, se2, settled2 = step_level(t, dilating, after_darker=False)
    assert value2 == value and settled2 and se2 < se      # a trend after brightening is not flagged
    value, _, settled = step_level(t, 3.0 + np.exp(-t / 0.3), after_darker=True)
    assert value == pytest.approx(3.0, abs=0.01) and settled


def test_display_photometry_file_and_participant_file(tmp_path):
    p = Parameters(l_max=180.0, gamma=2.4, sensitivity=2.5, age=40)
    DisplayPhotometry.from_params(p, "varjo", "XR-4 datasheet").save(tmp_path / "xr4.json")
    display = DisplayPhotometry.load(tmp_path / "xr4.json")
    assert (display.device, display.l_max, display.gamma, display.source) == ("varjo", 180.0, 2.4, "XR-4 datasheet")
    p.save(tmp_path / "full.json")
    with pytest.raises(ValueError):          # a parameter file is not a display photometry file
        DisplayPhotometry.load(tmp_path / "full.json")

    # Participant files leave the display out; loading one keeps the current display values.
    p.save(tmp_path / "participant.json", participant_only=True)
    assert "l_max" not in json.loads((tmp_path / "participant.json").read_text())
    current = display.apply(Parameters(l_max=90.0))
    loaded = Parameters.load(tmp_path / "participant.json", base=current)
    assert loaded.l_max == 180.0 and loaded.sensitivity == 2.5 and loaded.age == 40

