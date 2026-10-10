import math

import pytest

from app import stats


def test_num_cleans_api_values():
    assert stats.num("3.5") == 3.5
    assert stats.num(2) == 2.0
    for bad in [None, True, "x", float("nan"), float("inf"), {}, []]:
        assert stats.num(bad) is None


def test_epoch():
    assert stats.epoch(1791576000) == 1791576000
    assert stats.epoch(1791576000.7) == 1791576000
    assert stats.epoch("4:00PM EDT") is None
    assert stats.epoch(0) is None
    assert stats.epoch(-5) is None


def test_momentum():
    closes = [100.0] * 199 + [110.0]
    m = stats.momentum(closes)
    assert m["return_1y"] == pytest.approx(0.10)
    assert m["price_vs_sma200"] == pytest.approx(110 / (100 * 199 / 200 + 110 / 200) - 1)
    assert m["price_vs_sma50"] == pytest.approx(110 / (100 * 49 / 50 + 110 / 50) - 1)
    assert stats.momentum([5.0]) == {"return_1y": None, "price_vs_sma50": None, "price_vs_sma200": None}


def test_volatility_of_constant_growth_is_zero_and_alternating_is_high():
    steady = [100 * 1.001 ** i for i in range(100)]
    assert stats.annualized_volatility(steady, 252) == pytest.approx(0, abs=1e-9)
    zigzag = [100 if i % 2 else 110 for i in range(100)]
    vol = stats.annualized_volatility(zigzag, 252)
    assert vol > 1.0  # about 10% daily swings
    assert stats.annualized_volatility(steady[:10], 252) is None  # too little data


def test_volatility_scales_with_sqrt_of_periods():
    zigzag = [100 if i % 2 else 102 for i in range(100)]
    assert stats.annualized_volatility(zigzag, 365) / stats.annualized_volatility(zigzag, 252) == pytest.approx(
        math.sqrt(365 / 252))


def test_max_drawdown():
    assert stats.max_drawdown([100, 120, 60, 90, 130]) == pytest.approx(-0.5)
    assert stats.max_drawdown([1, 2, 3]) == 0.0
    assert stats.max_drawdown([5]) is None


def test_downsample_keeps_endpoints():
    series = [float(i) for i in range(1000)]
    out = stats.downsample(series, 60)
    assert len(out) == 60
    assert out[0] == 0.0 and out[-1] == 999.0
    assert stats.downsample([1.23456, 2.0]) == [1.2346, 2.0]
