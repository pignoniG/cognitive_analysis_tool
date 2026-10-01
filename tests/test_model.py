import numpy as np
import pytest

from cwtool import model


def legacy_watson_yellott(L, a, y, y0, e):
    # Formula as implemented in the 1.x colour_tools.py.
    F = L * a * {1: 0.1, 2: 1}.get(e, 0)
    Dsd = 7.75 - 5.75 * ((F / 846) ** 0.41 / ((F / 846) ** 0.41 + 2))
    return Dsd + (y - y0) * (0.02132 - 0.009562 * Dsd)


@pytest.mark.parametrize("L", [0.01, 1, 50, 200, 5000])
def test_matches_legacy_implementation(L):
    assert model.watson_yellott(L, 25, 160, 2) == pytest.approx(legacy_watson_yellott(L, 160, 25, 28.58, 2))


def test_pupil_shrinks_with_luminance_and_stays_in_range():
    d = model.watson_yellott(np.logspace(-3, 4, 50), 30, 160)
    assert np.all(np.diff(d) < 0)
    assert d.max() < 8 and d.min() > 2


def test_delay_pads_with_first_value():
    out = model.delay([1, 2, 3, 4], fs=10, seconds=0.2)
    assert out.tolist() == [1, 1, 1, 2]


def test_delay_is_exact_on_samples_and_interpolates_between():
    x = np.arange(10, dtype=float)
    assert model.delay(x, fs=100, seconds=0.03).tolist() == [0, 0, 0, 0, 1, 2, 3, 4, 5, 6]
    assert model.delay(np.arange(100.0), fs=100, seconds=0.29)[50] == 21     # not 22: 0.29 · 100 = 28.999…
    assert model.delay(x, fs=100, seconds=0.025)[5] == pytest.approx(2.5)
    assert model.delay(x, fs=10, seconds=5).tolist() == [0.0] * 10


def test_attack_release_asymmetry():
    fs = 100
    up = np.r_[np.zeros(10), np.ones(300)]
    down = 1 - up
    rise = model.attack_release(up, fs, attack=6, release=0.5)
    fall = model.attack_release(down, fs, attack=6, release=0.5)
    # After 1 s, the fast release has almost settled; the slow attack has not.
    assert fall[110] < 0.2
    assert rise[110] < 0.2
    assert fall[0] == 1 and rise[0] == 0


def test_attack_release_starts_at_input():
    out = model.attack_release([5.0, 5.0, 5.0], fs=100, attack=6, release=0.5)
    assert out.tolist() == [5.0, 5.0, 5.0]


def test_escape_transient_follows_brightening_only():
    fs = 100
    t = np.arange(0, 30, 1 / fs)
    up = np.where(t < 10, 1.0, 10.0)                   # one log unit brighter at 10 s
    tr = model.escape_transient(up, fs, escape=2.0)
    assert np.all(tr[t < 10] == 0)
    peak = tr[np.searchsorted(t, 10)]
    assert peak == pytest.approx(1 / (1 + model.TRANSIENT_HALF), rel=0.01)   # saturating in the step
    h = lambda x: x / (1 - x) * model.TRANSIENT_HALF   # back to the log increase
    assert h(tr[np.searchsorted(t, 12)]) == pytest.approx(np.exp(-1), rel=0.02)   # decays with escape
    assert tr[-1] < 0.01
    down = model.escape_transient(up[::-1], fs, escape=2.0)
    assert np.all(down == 0)                           # darkening gives none
    small = model.escape_transient(np.where(t < 10, 1.0, 10 ** 0.2), fs, escape=2.0)
    assert small.max() == pytest.approx(0.5, rel=0.01)  # half at the half-saturation step


def test_lowpass_starts_at_the_first_value():
    out = model.lowpass([5.0, 5.0, 5.0], fs=100, tau=0.5)
    assert out == pytest.approx([5.0, 5.0, 5.0])


def test_two_stage_constriction_starts_gradually_and_dilates_as_one():
    fs = 1000
    down = np.concatenate([np.ones(fs), np.zeros(3 * fs)])
    one = model.attack_release(down, fs, attack=3.0, release=0.2)
    two = model.attack_release(down, fs, attack=3.0, release=0.2, stages=2)
    speed = lambda y: -np.diff(y[fs:fs + 21]) * fs
    assert speed(one)[0] == pytest.approx(1 / 0.2, rel=0.01)     # full speed at once
    assert speed(two)[0] < 0.1 * speed(one)[0] and speed(two)[-1] > speed(two)[0]   # S-shaped
    assert two[fs + int(0.2 * fs)] == pytest.approx(1 - (1 - (1 + 1) * np.exp(-1)), abs=0.01)
    up = 1 - down
    assert model.attack_release(up, fs, 3.0, 0.2, stages=2) == pytest.approx(model.attack_release(up, fs, 3.0, 0.2))


def test_the_transient_is_switched_with_the_dynamics():
    from cwtool import pipeline
    from cwtool.params import Parameters
    fs = 100
    lum = np.where(np.arange(0, 20, 1 / fs) < 10, 1.0, 50.0)
    on = pipeline.expected_pupil(lum, fs, Parameters(dynamics=True, transient=1.0), 9896)
    no_transient = pipeline.expected_pupil(lum, fs, Parameters(dynamics=True), 9896)
    off = pipeline.expected_pupil(lum, fs, Parameters(dynamics=False, transient=1.0), 9896)
    assert (on < no_transient - 0.1).any()
    assert off == pytest.approx(pipeline.expected_pupil(lum, fs, Parameters(dynamics=False), 9896))
