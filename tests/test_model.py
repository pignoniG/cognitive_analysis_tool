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
