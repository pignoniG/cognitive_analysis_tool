import numpy as np
import pytest

from cwtool import luminance


def test_srgb_endpoints_and_linear_segment():
    lin = luminance.srgb_to_linear([0, 255, 10], gamma=2.4)
    assert lin[0] == 0
    assert lin[1] == pytest.approx(1.0)
    assert lin[2] == pytest.approx(10 / 255 / 12.92)


def test_srgb_standard_mid_gray():
    # sRGB 128 decodes to ~0.2159 with the standard 2.4 exponent.
    assert luminance.srgb_to_linear(128, 2.4) == pytest.approx(0.2159, abs=1e-4)


def test_absolute_luminance_endpoints_unit_gains():
    lum = luminance.absolute_luminance([[0, 0, 0], [1, 1, 1]], l_min=0.5, l_max=300)
    assert lum == pytest.approx([0.5, 300])


def test_unit_gains_equal_linear_mapping_of_relative_luminance():
    lin = np.array([0.2, 0.5, 0.9])
    y = luminance.relative_luminance(lin)
    expected = 300 * y + 0.5 * (1 - y)
    assert luminance.absolute_luminance(lin, 0.5, 300) == pytest.approx(expected)


def test_gains_rebalance_channels():
    blue = [0, 0, 1]
    base = luminance.absolute_luminance(blue, 0, 1000)
    boosted = luminance.absolute_luminance(blue, 0, 1000, gains=(1, 1, 10))
    assert base == pytest.approx(1000 * 0.0722)
    assert boosted == pytest.approx(1000 * 10 * 0.0722 / 4)
