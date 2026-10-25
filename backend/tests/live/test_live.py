"""Live checks against real Yahoo Finance and the deployed site.

Skipped unless LIVE=1 (they need network access). Run daily on GitHub
Actions by .github/workflows/live-check.yml.
"""

import json
import os
import time
from datetime import datetime, timedelta, timezone
import urllib.error
import urllib.request

import pytest

from app.benchmarks import load as load_benchmarks
from app.providers.market import MarketData
from app.funds import load as load_funds
from app.ratings import to_rating

pytestmark = pytest.mark.skipif(os.getenv("LIVE") != "1", reason="live network checks; set LIVE=1")

SITE = os.getenv("SITE_URL", "").rstrip("/")


@pytest.fixture(scope="module")
def market():
    return MarketData()


@pytest.mark.parametrize("ticker, currency", [
    ("AAPL", "USD"), ("MSFT", "USD"), ("JPM", "USD"), ("TSM", "USD"), ("KO", "USD"),
    ("7203.T", "JPY"), ("VOD.L", "GBp"), ("SAP.DE", "EUR"), ("0700.HK", "HKD"), ("RELIANCE.NS", "INR"),
    ("SHOP.TO", "CAD"), ("BHP.AX", "AUD"),
])
def test_large_companies_worldwide_are_rated(market, ticker, currency):
    r = to_rating(market.fetch(ticker), "yahoo", load_benchmarks())
    assert r.asset_type == "stock" and r.currency == currency
    assert r.name and r.price and r.price > 0
    assert r.price_time and time.time() - r.price_time < 7 * 86400, "price older than a week"
    assert r.coverage >= 0.6, f"only {r.coverage:.0%} of measures available"
    assert r.score is not None and 0 <= r.score <= 100
    assert len(r.price_history) >= 50
    assert any(f.label == "Market cap" for f in r.facts)


@pytest.mark.parametrize("ticker", ["BTC-USD", "ETH-USD", "SOL-USD", "XRP-USD"])
def test_major_coins_are_rated(market, ticker):
    r = to_rating(market.fetch(ticker), "yahoo")
    assert r.asset_type == "crypto" and r.score is not None
    facts = {f.label for f in r.facts}
    assert {"Rank by market cap", "Market cap"} <= facts


def test_stablecoin_not_rated(market):
    r = to_rating(market.fetch("USDT-USD"), "yahoo")
    assert r.score is None and r.label == "Not rated"


@pytest.mark.parametrize("ticker", ["ENB", "ENB.TO"])
def test_cross_listed_dividend_payer_keeps_its_record(market, ticker):
    # Enbridge pays in Canadian dollars and has raised its dividend every year for decades; in New York its
    # payments move with the exchange rate (and Yahoo misses some), which once read as cuts.
    r = to_rating(market.fetch(ticker), "yahoo", load_benchmarks())
    income = {m.key: m for c in r.categories if c.key == "income" for m in c.metrics}
    assert 0.04 < income["dividend_yield"].value < 0.09
    assert income["dividend_streak"].value >= 6 and income["dividend_growth_5y"].value > 0
    assert income["payout_ratio"].value < 1.0  # of operating cash flow, as for pipelines
    assert any("operating cash flow" in n for n in r.notes)


def test_etfs_are_rated_from_the_daily_fund_data(market):
    store = load_funds()
    r = to_rating(market.fetch("SPY"), "yahoo", funds=store)
    assert r.asset_type == "fund" and r.score is not None and r.industry == "Large Blend"
    facts = {f.label: f.value for f in r.facts}
    assert facts["Yearly fee"].startswith("0.0") and "Fund size" in facts
    assert r.peer_group and r.peer_group.level == "category"
    leveraged = to_rating(market.fetch("TQQQ"), "yahoo", funds=store)
    assert leveraged.score is None and any("Leveraged" in n for n in leveraged.notes)


def test_peer_comparison_used_when_benchmarks_exist(market):
    b = load_benchmarks()
    if not b.groups:
        pytest.skip("benchmarks not generated yet")
    r = to_rating(market.fetch("NVDA"), "yahoo", b)
    assert r.peer_group is not None
    assert any(m.benchmark for c in r.categories for m in c.metrics)


@pytest.mark.parametrize("query, expected", [("apple", "AAPL"), ("toyota", "7203.T"), ("bitcoin", "BTC-USD"),
                                             ("nestle", "NESN.SW")])
def test_search(market, query, expected):
    assert expected in [r.ticker for r in market.search(query)]


# --- the deployed site -----------------------------------------------------

def get(path: str):
    req = urllib.request.Request(SITE + path, headers={"user-agent": "live-check"})
    for attempt in range(6):  # the free tier sleeps; waking takes up to a minute
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode(errors="replace")
        except Exception:
            time.sleep(20)
    pytest.fail(f"{SITE}{path} unreachable")


site = pytest.mark.skipif(not SITE, reason="SITE_URL not set")


@site
def test_site_rates_stocks_with_full_data():
    status, body = get("/api/rating/AAPL")
    assert status == 200, body
    assert body["name"] == "Apple Inc."
    assert body["score"] is not None and body["coverage"] >= 0.6
    assert body["market_state"] in {"open", "pre", "post", "closed"}


@site
def test_site_rates_crypto_and_searches():
    status, body = get("/api/rating/BTC-USD")
    assert status == 200 and body["asset_type"] == "crypto" and body["score"] is not None, body
    status, body = get("/api/search?q=toyota")
    assert status == 200 and any(r["ticker"] == "7203.T" for r in body), body


@site
def test_site_data_sources_reachable_from_server():
    status, body = get("/api/diagnostics")
    assert status == 200
    checks = body["checks"]
    failed = {k: v["detail"] for k, v in checks.items() if not v["ok"]}
    assert not failed, failed


@site
def test_site_explore_lists_are_full_and_recent():
    status, body = get("/api/explore")
    assert status == 200, body
    ranked = datetime.fromisoformat(body["generated_at"])
    assert datetime.now(timezone.utc) - ranked < timedelta(days=5), "Explore rankings are stale"
    assert body["stocks_rated"] >= 1000 and body["coins_rated"] >= 50
    lists = {lst["key"]: lst for lst in body["lists"]}
    for key in ["top", "today_and_ahead", "outlook", "garp", "value", "growth", "dividends", "low_risk", "momentum",
                "crypto", "etf_stock", "etf_bond", "etf_cost", "etf_performance", "etf_dividends", "etf_low_risk"]:
        assert len(lists[key]["items"]) == 20, key
    assert sum(lst["group"] == "sector" for lst in body["lists"]) >= 10
    first = lists["top"]["items"][0]
    status, rating = get(f"/api/rating/{first['ticker']}")
    assert status == 200 and rating["score"] is not None


@site
def test_site_shows_analyst_outlook_for_us_stocks():
    status, body = get("/api/rating/MSFT")
    assert status == 200, body
    outlook = body["outlook"]
    assert outlook["analysts"] >= 10 and 0 <= outlook["score"] <= 100
    assert all(m["score"] is not None and m["benchmark"] for m in outlook["category"]["metrics"])
    status, body = get("/api/rating/BTC-USD")
    assert status == 200 and body["outlook"] is None


@site
def test_site_news_for_us_canadian_and_crypto_listings():
    for ticker in ("AAPL", "ENB.TO", "BTC-USD"):
        status, body = get(f"/api/news/{ticker}")
        # Yahoo sometimes has no crypto stories at all (e.g. Monday mornings); the app then hides the card.
        assert status == 200 and (len(body) >= 3 or ticker == "BTC-USD"), (ticker, body)
        assert all(n["link"].startswith("https://") and n["title"] for n in body)


@site
def test_site_fx_and_dividend_schedule():
    status, body = get("/api/fx?pairs=USDCAD,CADUSD")
    assert status == 200 and 1.0 < body["rates"]["USDCAD"] < 2.0 and 0.5 < body["rates"]["CADUSD"] < 1.0
    status, body = get("/api/rating/ENB.TO")
    d = body["dividend"]
    assert d["per_year"] == 4 and d["currency"] == "CAD" and d["next_ex_date"] > time.time() - 86400


@site
def test_site_canadian_lists_styles_and_history():
    status, body = get("/api/explore")
    assert status == 200 and body["canadian_rated"] >= 100
    keys = {lst["key"] for lst in body["lists"]}
    assert {"ca_top", "ca_dividends"} <= keys
    status, dividend = get("/api/explore?profile=dividend")
    assert dividend["profile"] == "dividend"
    status, rating = get("/api/rating/KO?profile=dividend")
    assert rating["profile"] == "dividend"
    status, history = get("/api/history/AAPL")
    assert status == 200 and history["points"], "no score history recorded yet"
