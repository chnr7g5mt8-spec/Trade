import json

import pytest

from app import explore, main, outlook
from app.benchmarks import EMPTY
from app.models import CategoryScore, MetricScore, Outlook, Rating
from app.providers.market import MarketData
from app.sources.recorded import RecordedClient

# The shape of Yahoo's quoteSummary result (financialData + earningsTrend),
# with numbers both bare and wrapped in {"raw": ...} as Yahoo sends them.
SUMMARY = {
    "financialData": {"currentPrice": 200.0, "targetMeanPrice": {"raw": 240.0, "fmt": "240.00"},
                      "recommendationMean": 1.9, "numberOfAnalystOpinions": {"raw": 40}},
    "earningsTrend": {"trend": [
        {"period": "0y", "earningsEstimate": {"growth": {"raw": 0.08}, "yearAgoEps": {"raw": 6.0}}},
        {"period": "+1y", "earningsEstimate": {"growth": {"raw": 0.12}, "yearAgoEps": {"raw": 6.5}},
         "revenueEstimate": {"growth": {"raw": 0.07}}},
    ]},
}


def test_parse():
    assert outlook.parse(SUMMARY) == {"analysts": 40, "target_mean": 240.0, "price": 200.0, "recommendation": 1.9,
                                      "eps_growth_next_year": 0.12, "revenue_growth_next_year": 0.07}


def test_parse_skips_growth_from_a_loss_and_unknown_coverage():
    loss = json.loads(json.dumps(SUMMARY))
    loss["earningsTrend"]["trend"][1]["earningsEstimate"]["yearAgoEps"] = {"raw": -0.4}
    assert "eps_growth_next_year" not in outlook.parse(loss)
    assert outlook.parse({"financialData": {"numberOfAnalystOpinions": 0}}) is None
    assert outlook.parse({}) is None


def test_build_scores_against_the_live_price():
    raw = outlook.parse(SUMMARY)
    o = outlook.build(raw, price=240.0, as_of="2026-10-10T22:30+00:00")
    metrics = {m.key: m for m in o.category.metrics}
    assert metrics["target_upside"].value == pytest.approx(0.0)  # price has reached the target
    assert metrics["eps_growth_next_year"].score == pytest.approx(56.7, abs=0.1)
    assert metrics["recommendation"].display == "1.9 (Buy)"
    assert o.analysts == 40 and o.as_of == "2026-10-10T22:30+00:00"
    assert o.score == pytest.approx(sum(m.score for m in metrics.values()) / 4, abs=0.1)
    # Without a live price, the price stored with the forecasts is used.
    assert {m.key: m.value for m in outlook.build(raw, None, None).category.metrics}["target_upside"] == \
        pytest.approx(0.2)


def test_build_needs_enough_analysts_and_measures():
    assert outlook.build({"analysts": 2, "recommendation": 1.0, "revenue_growth_next_year": 0.3}, 10.0, None) is None
    assert outlook.build({"analysts": 9, "recommendation": 1.0}, 10.0, None) is None
    assert outlook.build(None, 10.0, None) is None
    assert outlook.build({"analysts": 9, "recommendation": 1.0, "revenue_growth_next_year": 0.3}, 10.0, None).score == 100


def test_store_and_rating_service(tmp_path):
    path = tmp_path / "outlook.json"
    stored = {"generated_at": "2026-10-10T22:30+00:00", "stocks": {"AAPL": outlook.parse(SUMMARY)}}
    path.write_text(json.dumps(stored))
    store = outlook.load(path)
    assert outlook.load(tmp_path / "missing.json").get("AAPL", 1.0) is None

    market = MarketData(RecordedClient())
    service = main.RatingService(market, benchmarks=EMPTY, outlook=store)
    aapl = service.get("AAPL")
    assert aapl.outlook.analysts == 40 and aapl.outlook.as_of == "2026-10-10T22:30+00:00"
    upside = {m.key: m.value for m in aapl.outlook.category.metrics}["target_upside"]
    assert upside == pytest.approx(240.0 / aapl.price - 1)
    assert aapl.score is not None  # the outlook doesn't change the rating
    assert service.get("MSFT").outlook is None  # no forecasts stored
    assert service.get("BTC-USD").outlook is None


def stock(ticker, score, ahead=None, analysts=20, **cats):
    categories = [CategoryScore(key=k, label=k, weight=0.1, score=v, metrics=[]) for k, v in cats.items()]
    o = None if ahead is None else Outlook(score=ahead, analysts=analysts, as_of=None,
                                           category=CategoryScore(key="outlook", label="o", weight=1, score=ahead,
                                                                  metrics=[]))
    return Rating(ticker=ticker, symbol=ticker, asset_type="stock", name=ticker, sector="Technology", score=score,
                  label="x", coverage=1.0, categories=categories, source="t", outlook=o)


def test_outlook_and_blended_lists():
    ratings = [
        stock("A", 70.0, ahead=60.0, growth=80.0, valuation=50.0),
        stock("B", 50.0, ahead=95.0, growth=90.0, valuation=40.0),  # value below 50: not "fair price"
        stock("C", 40.0, ahead=99.0),  # rated Sell: left out of every list but Top rated
        stock("D", 80.0, ahead=50.0, analysts=4, growth=60.0, valuation=70.0),  # too few analysts to rank
        stock("E", 60.0),
    ]
    lists = {lst["key"]: lst for lst in explore.build(ratings)}
    assert [(i["ticker"], i["category_score"]) for i in lists["outlook"]["items"]] == [("B", 95.0), ("A", 60.0)]
    assert [(i["ticker"], i["category_score"]) for i in lists["today_and_ahead"]["items"]] == [
        ("B", 72.5), ("A", 65.0)]
    assert [(i["ticker"], i["category_score"]) for i in lists["garp"]["items"]] == [("D", 65.0), ("A", 65.0)]
    assert lists["outlook"]["category_label"] == "Outlook score"
    assert [lst["key"] for lst in explore.build(ratings)][:4] == ["top", "today_and_ahead", "outlook", "garp"]


def test_forecasts_are_ranked_against_all_stocks():
    # 200 stocks with forecast sales growth 0%..19.9%; analysts' targets 0..39.8% above the price.
    stocks = {f"S{i}": {"analysts": 10, "price": 100.0, "target_mean": 100.0 + i / 5, "recommendation": 2.0,
                        "revenue_growth_next_year": i / 1000} for i in range(200)}
    dists = outlook.distributions(stocks)
    assert set(dists) == {"revenue_growth_next_year", "target_upside", "recommendation"}  # EPS: too few
    assert dists["target_upside"]["count"] == 200 and len(dists["target_upside"]["q"]) == 99
    store = outlook.OutlookStore({"generated_at": "x", "distributions": dists, "stocks": stocks})
    top, middle = store.get("S199", 100.0), store.get("S100", 100.0)
    metrics = {m.key: m for m in top.category.metrics}
    assert metrics["revenue_growth_next_year"].benchmark == "vs all US stocks · median 10.0%"
    # 70% rank among all stocks + 30% fixed scale.
    assert metrics["revenue_growth_next_year"].score == pytest.approx(0.7 * 99.5 + 0.3 * 99.5, abs=0.5)
    assert top.score > middle.score
    # Distinct forecasts get distinct scores near the top instead of tying at 100.
    assert store.get("S190", 100.0).score < store.get("S199", 100.0).score < 100


def test_future_outlook_list_needs_every_forecast():
    def with_metrics(ticker, ahead, keys):
        r = stock(ticker, 60.0, ahead=ahead)
        metrics = [MetricScore(key=k, label=k, value=1.0, display="", score=None if k not in keys else 50.0)
                   for k in ("eps_growth_next_year", "revenue_growth_next_year", "target_upside", "recommendation")]
        r.outlook.category.metrics = metrics
        return r

    all_four = ("eps_growth_next_year", "revenue_growth_next_year", "target_upside", "recommendation")
    ratings = [with_metrics("FULL", 70.0, all_four), with_metrics("LOSS", 90.0, all_four[1:])]
    assert [i["ticker"] for i in {l["key"]: l for l in explore.build(ratings)}["outlook"]["items"]] == ["FULL"]


def test_sample_mode_uses_recorded_forecasts():
    # Real forecasts recorded with the demo data (scripts/build_explore.py output for these stocks).
    market = MarketData(RecordedClient())
    market.name = "sample"
    service = main.RatingService(market, benchmarks=EMPTY)
    nvda = service.get("NVDA").outlook
    assert nvda.analysts >= 20 and all(m.benchmark for m in nvda.category.metrics)
    assert service.get("VOD.L").outlook is None  # not US-listed
