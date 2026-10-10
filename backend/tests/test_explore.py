import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import explore, main
from app.benchmarks import EMPTY
from app.models import CategoryScore, Fact, MetricScore, Rating
from app.providers.market import MarketData
from app.providers.stocks import StockProvider
from app.sources.recorded import RecordedClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import build_explore  # noqa: E402

STOCK_KEYS = ["valuation", "profitability", "growth", "health", "consistency", "momentum", "risk", "income"]


def rating(ticker, score, asset_type="stock", sector="Technology", coverage=1.0, name=None, **cats):
    categories = [CategoryScore(key=k, label=k, weight=0.1, score=cats.get(k), metrics=[]) for k in STOCK_KEYS]
    return Rating(ticker=ticker, symbol=ticker, asset_type=asset_type, name=name or f"{ticker} Inc.",
                  sector=sector, score=score, label="x", coverage=coverage, categories=categories, source="test")


def lists_by_key(ratings):
    return {lst["key"]: lst for lst in explore.build(ratings)}


def test_top_rated_is_sorted_and_capped_at_twenty():
    ratings = [rating(f"T{i:02d}", float(i)) for i in range(30)]
    top = lists_by_key(ratings)["top"]["items"]
    assert [i["ticker"] for i in top] == [f"T{i:02d}" for i in range(29, 9, -1)]
    assert top[0]["score"] == 29 and top[0]["category_score"] is None


def test_category_lists_rank_by_category_among_hold_or_better():
    ratings = [
        rating("CHEAPJUNK", 30.0, valuation=99.0),  # rated Sell: excluded from "best value"
        rating("A", 60.0, valuation=80.0),
        rating("B", 70.0, valuation=80.0),  # same category score: higher overall first
        rating("C", 90.0, valuation=50.0),
        rating("NODIV", 90.0, valuation=10.0),
        rating("DIV", 50.0, valuation=10.0, income=75.0),
    ]
    lists = lists_by_key(ratings)
    value = lists["value"]["items"]
    assert [i["ticker"] for i in value] == ["B", "A", "C", "NODIV", "DIV"]
    assert value[0]["category_score"] == 80.0
    # Only dividend payers have a dividend score.
    assert [i["ticker"] for i in lists["dividends"]["items"]] == ["DIV"]
    # Lists with nothing in them are left out.
    assert "growth" not in lists


def test_unrated_thin_and_unsupported_ratings_are_left_out():
    ratings = [
        rating("GOOD", 60.0),
        rating("THIN", 95.0, coverage=0.5),
        rating("NONE", None),
        rating("SPY", 99.0, asset_type="fund"),
    ]
    assert [i["ticker"] for i in lists_by_key(ratings)["top"]["items"]] == ["GOOD"]


def test_share_classes_of_one_company_appear_once():
    ratings = [rating("GOOGL", 80.0, name="Alphabet Inc."), rating("GOOG", 80.0, name="Alphabet Inc."),
               rating("MSFT", 70.0)]
    assert [i["ticker"] for i in lists_by_key(ratings)["top"]["items"]] == ["GOOG", "MSFT"]


def test_crypto_and_sector_lists():
    ratings = [rating("BTC-USD", 70.0, asset_type="crypto", sector=None),
               rating("ETH-USD", 60.0, asset_type="crypto", sector=None),
               rating("USDT-USD", None, asset_type="crypto", sector=None),
               rating("XOM", 50.0, sector="Energy"),
               rating("AAPL", 60.0), rating("MSFT", 65.0)]
    built = explore.build(ratings)
    lists = {lst["key"]: lst for lst in built}
    assert [i["ticker"] for i in lists["crypto"]["items"]] == ["BTC-USD", "ETH-USD"]
    assert all(i["ticker"] != "BTC-USD" for i in lists["top"]["items"])
    # Sectors come after the featured lists, largest sector first.
    assert [lst["key"] for lst in built if lst["group"] == "sector"] == ["sector:technology", "sector:energy"]
    assert lists["sector:technology"]["title"] == "Technology"
    assert [i["ticker"] for i in lists["sector:technology"]["items"]] == ["MSFT", "AAPL"]


def test_load(tmp_path):
    assert explore.load(tmp_path / "missing.json") is None
    path = tmp_path / "explore.json"
    path.write_text(json.dumps({"generated_at": "2026-10-09T21:30+00:00", "lists": []}))
    assert explore.load(path) is None
    path.write_text(json.dumps({"generated_at": "2026-10-09T21:30+00:00", "lists": [{"key": "top", "items": []}]}))
    assert explore.load(path)["generated_at"] == "2026-10-09T21:30+00:00"


@pytest.fixture
def sample_client(monkeypatch):
    market = MarketData(RecordedClient())
    market.name = "sample"
    monkeypatch.setattr(main, "service", main.RatingService(market, benchmarks=EMPTY))
    monkeypatch.setattr(main, "_sample_explore", None)
    return TestClient(main.app)


def test_endpoint_in_sample_mode_rates_the_recorded_assets(sample_client):
    resp = sample_client.get("/api/explore")
    assert resp.status_code == 200 and resp.headers["cache-control"] == "no-store"
    body = resp.json()
    assert body["coins_rated"] == 3 and body["stocks_rated"] >= 10
    lists = {lst["key"]: lst for lst in body["lists"]}
    assert {"top", "value", "growth", "dividends", "low_risk", "momentum", "crypto"} <= set(lists)
    top = lists["top"]["items"]
    assert len(top) == body["stocks_rated"]
    # Each entry matches the full rating the app shows for it.
    first = sample_client.get(f"/api/rating/{top[0]['ticker']}").json()
    assert (first["score"], first["label"], first["name"]) == (top[0]["score"], top[0]["label"], top[0]["name"])
    assert "SPY" not in {i["ticker"] for lst in body["lists"] for i in lst["items"]}
    assert "USDT-USD" not in {i["ticker"] for i in lists["crypto"]["items"]}


def test_endpoint_serves_the_daily_file(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "service", main.RatingService(MarketData(RecordedClient()), benchmarks=EMPTY))
    client = TestClient(main.app)
    monkeypatch.setattr(explore, "DEFAULT_PATH", tmp_path / "explore.json")
    resp = client.get("/api/explore")
    assert resp.status_code == 503
    (tmp_path / "explore.json").write_text(json.dumps({"generated_at": "2026-10-09T21:30+00:00",
                                                       "lists": [{"key": "top", "items": []}]}))
    assert client.get("/api/explore").json()["generated_at"] == "2026-10-09T21:30+00:00"


def test_script_rates_like_the_app():
    client = RecordedClient()
    provider = StockProvider(client)
    row = {"symbol": "AAPL", "longName": "Apple Inc.", "shortName": "Apple Inc."}
    r = build_explore.rate_stock(provider, EMPTY, row, "Technology", "Consumer Electronics")
    market = MarketData(client)
    market.name = "yahoo"
    app_rating = main.RatingService(market, benchmarks=EMPTY).get("AAPL")
    assert r.name == app_rating.name and r.industry == app_rating.industry
    assert r.score == app_rating.score and r.categories == app_rating.categories

    listing, rank = market.crypto.directory.find("BTC-USD")
    coin = build_explore.rate_coin(client, listing, rank)
    app_coin = main.RatingService(market, benchmarks=EMPTY).get("BTC-USD")
    assert (coin.symbol, coin.name, coin.score) == (app_coin.symbol, app_coin.name, app_coin.score)


def test_script_skips_unknown_symbols():
    provider = StockProvider(RecordedClient())
    assert build_explore.rate_stock(provider, EMPTY, {"symbol": "NOPE"}, "Technology", "Software") is None


def test_preferred_shares_and_closed_end_funds_are_left_out():
    def am(ticker, name, score):
        r = rating(ticker, score, sector="Financial Services", name=name)
        return r.model_copy(update={"industry": "Asset Management"})

    ratings = [
        rating("KIM-PM", 90.0, name="Kimco Realty Corporation"),
        rating("TRTN-PA", 90.0, name="Triton International Limited"),
        am("BSTZ", "BlackRock Science and Technology Term Trust", 90.0),
        am("AOD", "Abrdn Total Dynamic Dividend Fund", 90.0),
        am("GAM", "General American Investors Company, Inc.", 90.0),
        am("BLK", "BlackRock, Inc.", 70.0),  # an asset manager is a company
        rating("BRK-B", 60.0, name="Berkshire Hathaway Inc."),  # share classes stay
        rating("PBR-A", 55.0, name="Petróleo Brasileiro S.A. - Petrobras"),
    ]
    assert [i["ticker"] for i in lists_by_key(ratings)["top"]["items"]] == ["BLK", "BRK-B", "PBR-A"]


def test_wrapped_and_staked_coins_are_left_out():
    def coin(ticker, name, score):
        return rating(ticker, score, asset_type="crypto", sector=None, name=name).model_copy(
            update={"symbol": ticker.removesuffix("-USD")})

    ratings = [coin("BTC-USD", "Bitcoin", 60.0), coin("WBTC-USD", "Wrapped Bitcoin", 61.0),
               coin("ETH-USD", "Ethereum", 55.0), coin("WETH-USD", "WETH", 56.0),
               coin("STETH-USD", "Lido Staked ETH", 57.0), coin("WIF-USD", "dogwifhat", 50.0),
               coin("W-USD", "Wormhole", 45.0)]
    assert [i["ticker"] for i in lists_by_key(ratings)["crypto"]["items"]] == ["BTC-USD", "ETH-USD", "WIF-USD", "W-USD"]


def test_coins_trading_as_copies_of_a_larger_coin_are_left_out():
    def coin(ticker, rank, price, ret, score):
        r = rating(ticker, score, asset_type="crypto", sector=None, name=ticker)
        cats = [CategoryScore(key="momentum", label="m", weight=0.3, score=50.0,
                              metrics=[MetricScore(key="return_1y", label="r", value=ret, display="", score=50.0)])]
        return r.model_copy(update={"price": price, "categories": cats,
                                    "facts": [Fact(label="Rank by market cap", value=f"#{rank}")]})

    ratings = [coin("BTCB-USD", 40, 121_300.0, 0.452, 70.0), coin("BTC-USD", 1, 121_000.0, 0.45, 60.0),
               coin("OTHER-USD", 30, 121_500.0, -0.20, 50.0),  # same price by chance, different year
               coin("SMALL-USD", 50, 0.301, 0.10, 55.0), coin("TINY-USD", 60, 0.30, 0.10, 54.0)]  # cheap: no test
    assert [i["ticker"] for i in lists_by_key(ratings)["crypto"]["items"]] == [
        "BTC-USD", "SMALL-USD", "TINY-USD", "OTHER-USD"]
