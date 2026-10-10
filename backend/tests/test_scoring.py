from app.models import StockData
from app.providers import SampleProvider, momentum_from_closes
from app.scoring import CATEGORIES, label_for, rate, score_metric


def _spec(key):
    return next(m for c in CATEGORIES for m in c.metrics if m.key == key)


def test_score_metric_interpolates_and_clamps():
    roe = _spec("return_on_equity")  # bad 0, good 0.25
    assert score_metric(0.125, roe) == 50.0
    assert score_metric(-1.0, roe) == 0.0
    assert score_metric(2.0, roe) == 100.0
    assert score_metric(None, roe) is None


def test_lower_is_better_metrics():
    pe = _spec("trailing_pe")  # bad 40, good 10
    assert score_metric(10, pe) == 100.0
    assert score_metric(25, pe) == 50.0
    assert score_metric(60, pe) == 0.0


def test_negative_pe_means_losses_and_scores_zero():
    assert score_metric(-15, _spec("trailing_pe")) == 0.0


def test_labels():
    assert label_for(85) == "Strong Buy"
    assert label_for(65) == "Buy"
    assert label_for(50) == "Hold"
    assert label_for(30) == "Sell"
    assert label_for(5) == "Strong Sell"
    assert label_for(None) == "Not rated"


def test_weights_sum_to_one():
    assert abs(sum(c.weight for c in CATEGORIES) - 1.0) < 1e-9


def test_missing_data_is_ignored_not_penalised():
    only_profit = StockData(ticker="X", return_on_equity=0.25, profit_margin=0.25, operating_margin=0.30)
    r = rate(only_profit, source="test")
    assert r.score == 100.0
    assert r.label == "Strong Buy"
    assert 0 < r.coverage < 0.3


def test_no_data_is_not_rated():
    r = rate(StockData(ticker="X"), source="test")
    assert r.score is None
    assert r.label == "Not rated"
    assert r.coverage == 0.0


def test_fcf_yield_derived_from_market_cap():
    r = rate(StockData(ticker="X", free_cash_flow=3e9, market_cap=1e11), source="test")
    health = next(c for c in r.categories if c.key == "health")
    fcf = next(m for m in health.metrics if m.key == "fcf_yield")
    assert fcf.value == 0.03
    assert fcf.score == 50.0


def test_momentum_from_closes():
    closes = [100.0] * 199 + [110.0]
    m = momentum_from_closes(closes)
    assert abs(m["return_1y"] - 0.10) < 1e-9
    assert m["price_vs_sma200"] > 0
    assert momentum_from_closes([5.0]) == {"return_1y": None, "price_vs_sma50": None, "price_vs_sma200": None}


def test_sample_data_ranks_sensibly():
    p = SampleProvider()
    scores = {t: rate(p.fetch(t), "sample").score for t in p.tickers()}
    assert scores["MSFT"] > scores["F"]
    assert scores["MSFT"] > scores["XYZQ"]
    assert all(0 <= s <= 100 for s in scores.values())
