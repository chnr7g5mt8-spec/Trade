import json
import math

import pytest

from app import explore, funds, main
from app.benchmarks import EMPTY
from app.models import CategoryScore, Rating, StockData
from app.providers.market import MarketData
from app.providers.stocks import build_stock
from app.ratings import to_rating
from app.sources.recorded import RecordedClient
from tests.recordings import RECORDED_AT, chart

# The shape of Yahoo's quoteSummary result for an ETF.
SUMMARY = {
    "fundProfile": {"categoryName": "Large Blend", "family": "SPDR State Street Global Advisors",
                    "feesExpensesInvestment": {"annualReportExpenseRatio": {"raw": 0.000945}}},
    "summaryDetail": {"totalAssets": {"raw": 6.5e11}},
    "defaultKeyStatistics": {},
    "assetProfile": {"longBusinessSummary": "  The trust seeks to provide investment results that correspond to the "
                                            "price and yield of the S&P 500 Index. "},
    "topHoldings": {
        "stockPosition": {"raw": 0.9971}, "cashPosition": {"raw": 0.0029}, "bondPosition": {"raw": 0.0},
        "holdings": [{"symbol": "AAPL", "holdingName": "Apple Inc", "holdingPercent": {"raw": 0.0662}},
                     {"symbol": "NVDA", "holdingName": "NVIDIA Corp", "holdingPercent": {"raw": 0.0751}}],
        "sectorWeightings": [{"realestate": {"raw": 0.0201}}, {"technology": {"raw": 0.3402}},
                             {"utilities": {"raw": 0.0021}}],
    },
}


def spy() -> StockData:
    return build_stock("SPY", chart("SPY"), {}, {"longname": "SPDR S&P 500 ETF Trust"}, now=RECORDED_AT)


def store_with(ticker="SPY", info=None, peers=()):
    """A fund store with `ticker` plus Large Blend peers with the given 1-year returns."""
    data = {"generated_at": "2026-10-10T22:30+00:00", "funds": {ticker: info or funds.parse(SUMMARY)}}
    peer_data = [("Large Blend", StockData(ticker=f"P{i}", asset_type="fund", return_1y=r))
                 for i, r in enumerate(peers)]
    data["categories"] = funds.category_stats(peer_data)
    return funds.FundStore(data)


def test_parse():
    assert funds.parse(SUMMARY) == {
        "expense_ratio": 0.000945, "net_assets": 6.5e11, "category": "Large Blend",
        "family": "SPDR State Street Global Advisors",
        "summary": "The trust seeks to provide investment results that correspond to the price and yield of the "
                   "S&P 500 Index.",
        "holdings": [["NVDA", "NVIDIA Corp", 0.0751], ["AAPL", "Apple Inc", 0.0662]],
        "sectors": [["Technology", 0.3402], ["Real estate", 0.0201]],  # under 0.5% left out
        "mix": [["Stocks", 0.9971]],
    }
    assert funds.parse({"defaultKeyStatistics": {"annualReportExpenseRatio": 0.002, "totalAssets": 1e9}}) == {
        "expense_ratio": 0.002, "net_assets": 1e9}
    assert funds.parse({}) is None


@pytest.mark.parametrize("category, name, trading", [
    ("Trading--Leveraged Equity", "ProShares UltraPro QQQ", True),
    ("Trading--Inverse Equity", "ProShares Short S&P500", True),
    (None, "Direxion Daily Semiconductor Bull 3X Shares", True),
    (None, "ProShares Ultra S&P500", True),
    (None, "ProShares UltraShort 20+ Year Treasury", True),
    ("Ultrashort Bond", "JPMorgan Ultra-Short Income ETF", False),
    ("Short-Term Bond", "Vanguard Short-Term Bond ETF", False),
    ("Large Blend", "SPDR S&P 500 ETF Trust", False),
])
def test_leveraged_and_inverse_funds(category, name, trading):
    assert funds.is_trading_fund(category, name) is trading


def test_etf_is_rated_on_cost_performance_risk_size_and_dividends():
    r = to_rating(spy(), "sample", funds=store_with(peers=[0.05 + i / 100 for i in range(20)]))
    assert r.asset_type == "fund" and r.score is not None and r.label != "Not rated"
    assert r.industry == "Large Blend" and r.peer_group.name == "Large Blend" and r.peer_group.level == "category"
    cats = {c.key: c for c in r.categories}
    assert list(cats) == ["cost", "performance", "risk", "size", "income"]
    assert cats["cost"].score == pytest.approx(100 * (0.0075 - 0.000945) / (0.0075 - 0.0003), abs=0.1)
    assert cats["size"].score == 100  # $650B
    one_year = cats["performance"].metrics[0]
    assert one_year.key == "return_1y" and one_year.benchmark.startswith("Category median")
    facts = {f.label: f.value for f in r.facts}
    assert facts["Yearly fee"] == "0.09% a year" and facts["Fund size"] == "$650.0B"
    assert facts["Category"] == "Large Blend"
    assert not any("isn't" in n for n in r.notes)
    assert cats["cost"].description.startswith("The yearly fee")
    p = r.fund_profile
    assert p.summary.startswith("The trust seeks") and p.as_of == "2026-10-10T22:30+00:00"
    assert [(h.symbol, h.weight) for h in p.holdings] == [("NVDA", 0.0751), ("AAPL", 0.0662)]
    assert [w.name for w in p.sectors] == ["Technology", "Real estate"] and p.asset_mix[0].name == "Stocks"


def test_long_fund_descriptions_are_cut_at_a_sentence():
    text = "First sentence of the description goes here. " * 20
    cut = funds._summary(text)
    assert len(cut) <= funds.MAX_SUMMARY and cut.endswith("goes here.")
    assert funds._summary("x" * 700).endswith("…") and funds._summary("  ") is None


def test_risk_tells_cash_from_bonds_from_stocks():
    def risk(vol, drop, beta):
        d = StockData(ticker="X", asset_type="fund", volatility_1y=vol, max_drawdown_1y=drop, beta=beta)
        return {c.key: c.score for c in funds.rate_fund(d, store_with("X"))[0].categories}["risk"]

    assert risk(0.003, -0.001, 0.0) > risk(0.06, -0.04, 0.1) > risk(0.15, -0.12, 1.0) > risk(0.35, -0.3, 1.4)


def test_fund_without_daily_data_is_shown_but_not_rated():
    r = to_rating(spy(), "sample", funds=funds.FundStore())
    assert r.score is None and r.label == "Not rated"
    assert any("ETFs worth over $500M" in n for n in r.notes)
    assert {c.key for c in r.categories if c.score is not None} >= {"performance", "risk"}


def test_leveraged_etf_is_not_rated():
    info = {"expense_ratio": 0.0084, "net_assets": 2.5e10, "category": "Trading--Leveraged Equity"}
    r = to_rating(spy(), "sample", funds=store_with(info=info))
    assert r.score is None and any("Leveraged" in n for n in r.notes)


def test_category_stats_need_enough_funds():
    stats = funds.category_stats([("Large Blend", StockData(ticker=f"A{i}", asset_type="fund", return_1y=0.1 * i,
                                                            return_3y=0.05))
                                  for i in range(8)] + [("Small", StockData(ticker="B", return_1y=0.1))])
    assert set(stats) == {"Large Blend"} and stats["Large Blend"]["funds"] == 8
    assert set(stats["Large Blend"]["metrics"]) == {"return_1y", "return_3y"}


def test_store_round_trip_and_service(tmp_path):
    path = tmp_path / "funds.json"
    path.write_text(json.dumps({"generated_at": "x", "funds": {"SPY": funds.parse(SUMMARY)}, "categories": {}}))
    service = main.RatingService(MarketData(RecordedClient()), benchmarks=EMPTY, funds=funds.load(path))
    assert service.get("SPY").score is not None
    assert funds.load(tmp_path / "missing.json").get("SPY") is None


def etf(ticker, score, **cats):
    categories = [CategoryScore(key=k, label=k, weight=0.1, score=v, metrics=[]) for k, v in cats.items()]
    return Rating(ticker=ticker, symbol=ticker, asset_type="fund", name=ticker, industry="Large Blend",
                  score=score, label="x", coverage=1.0, categories=categories, source="t")


def test_explore_etf_lists():
    ratings = [etf("VOO", 70.0, cost=100.0, performance=60.0, risk=50.0, income=40.0),
               etf("IVV", 72.0, cost=100.0, performance=61.0, risk=50.0, income=40.0),
               etf("ARKK", 40.0, cost=10.0, performance=99.0),  # Sell: only in Top ETFs
               etf("SGOV", 60.0, cost=80.0, performance=40.0, risk=100.0, income=90.0)]
    lists = {lst["key"]: lst for lst in explore.build(ratings)}
    assert [i["ticker"] for i in lists["etf_top"]["items"]] == ["IVV", "VOO", "SGOV", "ARKK"]
    assert [i["ticker"] for i in lists["etf_cost"]["items"]] == ["IVV", "VOO", "SGOV"]  # ties: higher score first
    assert [i["ticker"] for i in lists["etf_low_risk"]["items"]][0] == "SGOV"
    assert all(lst["group"] == "etf" for k, lst in lists.items() if k.startswith("etf_"))
    assert "top" not in lists  # no stocks in this test
    assert math.isclose(lists["etf_cost"]["items"][0]["category_score"], 100.0)
