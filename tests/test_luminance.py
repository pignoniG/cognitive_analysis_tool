import numpy as np
import pytest

from cwtool import luminance


def test_power_curve_endpoints_and_mid_gray():
    lin = luminance.to_linear([0, 255, 128], gamma=2.2)
    assert lin[0] == 0
    assert lin[1] == pytest.approx(1.0)
    assert lin[2] == pytest.approx((128 / 255) ** 2.2)


def test_power_22_approximates_srgb_and_is_continuous():
    c = np.arange(256)
    srgb = np.where(c / 255 <= 0.04045, c / 255 / 12.92, ((c / 255 + 0.055) / 1.055) ** 2.4)
    assert np.abs(luminance.to_linear(c, 2.2) - srgb).max() < 0.01
    for gamma in (1.8, 2.2, 2.6):
        assert np.all(np.diff(luminance.to_linear(np.linspace(0, 255, 2000), gamma)) >= 0)
        assert np.abs(np.diff(luminance.to_linear(np.linspace(0, 255, 2000), gamma))).max() < 0.01


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
