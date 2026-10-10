import pytest

from app.benchmarks import Distribution, PeerGroup, Benchmarks, norm
from app.models import CryptoData, StockData
from app.scoring import common, crypto, stock
from app.scoring.common import CategorySpec, MetricSpec, label_for, score_categories, score_metric


def spec(key, cats=stock.CATEGORIES):
    return next(m for c in cats for m in c.metrics if m.key == key)


DIST = Distribution(count=40, points=((0.05, 10.0), (0.1, 12.0), (0.25, 15.0), (0.5, 20.0), (0.75, 26.0),
                                      (0.9, 35.0), (0.95, 45.0)))


def test_absolute_scale_interpolates_and_clamps():
    roe = spec("return_on_equity")  # 0 -> 0 points, 25% -> 100
    assert score_metric(0.125, roe) == 50.0
    assert score_metric(-1.0, roe) == 0.0
    assert score_metric(2.0, roe) == 100.0
    assert score_metric(None, roe) is None


def test_lower_is_better():
    pe = spec("pe_ratio")  # 40 -> 0, 10 -> 100
    assert score_metric(25, pe) == 50.0
    assert score_metric(-1.0, pe) == 0.0  # loss-making


def test_relative_blend_is_70_percent_peer_rank():
    pe = spec("pe_ratio")
    # At the industry median (20x): peer rank 50 -> 0.7*50 + 0.3*absolute(20x = 66.7)
    assert score_metric(20.0, pe, DIST) == pytest.approx(0.7 * 50 + 0.3 * (40 - 20) / 30 * 100, abs=0.1)
    # Cheaper than 95% of peers
    assert score_metric(9.0, pe, DIST) > 95
    # Loss-making still scores 0 whatever the peers look like
    assert score_metric(-1.0, pe, DIST) == 0.0


def test_relative_flag_is_ignored_without_peers():
    pe = spec("pe_ratio")
    assert score_metric(20.0, pe) == pytest.approx((40 - 20) / 30 * 100, abs=0.1)


def test_labels():
    assert [label_for(s) for s in (85, 80, 65, 64, 45, 30, 29, 0, None)] == [
        "Strong Buy", "Strong Buy", "Buy", "Hold", "Hold", "Sell", "Strong Sell", "Strong Sell", "Not rated"]


CATS = (
    CategorySpec("a", "A", 0.5, (MetricSpec("x", "X", bad=0, good=1, fmt=common.ratio),
                                 MetricSpec("y", "Y", bad=0, good=1, fmt=common.ratio))),
    CategorySpec("b", "B", 0.5, (MetricSpec("z", "Z", bad=0, good=1, fmt=common.ratio),)),
    CategorySpec("o", "Optional", 0.5, (MetricSpec("w", "W", bad=0, good=1, fmt=common.ratio),), optional=True),
)


def test_weighted_score_and_whole_number():
    s = score_categories({"x": 1.0, "y": 0.0, "z": 0.333}, CATS)
    assert s.categories[0].score == 50.0
    assert s.score == round(0.5 * 50 + 0.5 * 33.3)
    assert s.coverage == 1.0  # optional metrics don't count towards coverage


def test_optional_category_counts_only_when_present():
    without = score_categories({"x": 1.0, "y": 1.0, "z": 1.0}, CATS)
    with_low = score_categories({"x": 1.0, "y": 1.0, "z": 1.0, "w": 0.0}, CATS)
    assert without.score == 100.0
    assert with_low.score == round((100 * 0.5 + 100 * 0.5 + 0 * 0.5) / 1.5)


def test_too_little_data_is_not_rated():
    s = score_categories({"z": 1.0}, CATS)  # 1 of 3 core metrics
    assert s.coverage == pytest.approx(0.33)
    assert s.score is None and s.label == "Not rated"


def test_peer_group_reported_and_benchmark_text():
    b = Benchmarks(groups={
        "industry:" + norm("Semiconductors"): PeerGroup("Semiconductors", "industry", 45, {"pe_ratio": DIST}),
    })
    s = score_categories({"pe_ratio": 20.0}, stock.CATEGORIES, b, "Semiconductors", "Technology")
    assert s.peer.name == "Semiconductors" and s.peer.level == "industry" and s.peer.companies == 45
    pe = next(m for c in s.categories for m in c.metrics if m.key == "pe_ratio")
    assert pe.benchmark == "Industry median 20.0x"
    roe = next(m for c in s.categories for m in c.metrics if m.key == "return_on_equity")
    assert roe.benchmark is None


def test_stock_weights_and_relative_choices():
    core = [c for c in stock.CATEGORIES if not c.optional]
    assert sum(c.weight for c in core) == pytest.approx(1.0)
    assert spec("pe_ratio").relative and not spec("return_1y").relative and not spec("beta").relative


def test_fund_is_not_rated_but_shows_price_categories():
    s = stock.rate_stock(StockData(ticker="SPY", asset_type="fund", return_1y=0.2, volatility_1y=0.15))
    assert s.score is None and s.label == "Not rated"
    assert [c.key for c in s.categories] == ["momentum", "risk", "income"]


def test_dividend_yield_trap():
    y = spec("dividend_yield")
    assert score_metric(0.15, y) == 30.0
    assert score_metric(0.05, y) == 100.0


def test_crypto_weights_and_stablecoin():
    assert sum(c.weight for c in crypto.CATEGORIES) == pytest.approx(1.0)
    data = CryptoData(ticker="USDT-USD", symbol="USDT", market_cap=1e11, turnover=0.2, return_30d=0.0,
                      return_1y=0.0, volatility_1y=0.01, max_drawdown_1y=-0.01, age_years=10, is_stablecoin=True)
    s = crypto.rate_crypto(data)
    assert s.score is None and s.label == "Not rated"
    assert crypto.COMPARISON_NOTE not in s.notes


def test_crypto_market_cap_log_scale():
    mc = spec("market_cap", crypto.CATEGORIES)
    assert score_metric(1e7, mc) == 0.0
    assert score_metric(1e9, mc) == 50.0
    assert score_metric(1e11, mc) == 100.0
    assert score_metric(1e13, mc) == 100.0


def test_crypto_rating_carries_comparison_note():
    s = crypto.rate_crypto(CryptoData(ticker="X-USD", symbol="X", market_cap=1e9, turnover=0.01, return_30d=0.1,
                                      return_1y=0.2, price_vs_sma50=0.0, price_vs_sma200=0.0, volatility_1y=0.8,
                                      max_drawdown_1y=-0.5, from_all_time_high=-0.5, age_years=4))
    assert s.score is not None
    assert crypto.COMPARISON_NOTE in s.notes
