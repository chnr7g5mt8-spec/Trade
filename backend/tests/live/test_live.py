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


def test_fund_not_rated(market):
    r = to_rating(market.fetch("SPY"), "yahoo")
    assert r.asset_type == "fund" and r.score is None


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
    for key in ["top", "value", "growth", "dividends", "low_risk", "momentum", "crypto"]:
        assert len(lists[key]["items"]) == 20, key
    assert sum(lst["group"] == "sector" for lst in body["lists"]) >= 10
    first = lists["top"]["items"][0]
    status, rating = get(f"/api/rating/{first['ticker']}")
    assert status == 200 and rating["score"] is not None
