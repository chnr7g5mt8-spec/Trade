import pytest
from fastapi.testclient import TestClient

from app import main, profiles
from app.benchmarks import EMPTY
from app.funds import FundStore
from app.models import CategoryScore, Rating
from app.providers.market import MarketData
from app.sources.recorded import RecordedClient

KEYS = ["valuation", "profitability", "growth", "health", "consistency", "momentum", "risk", "income"]


def stock(score=60.0, **cats):
    categories = [CategoryScore(key=k, label=k, weight=0.1, score=cats.get(k, 50.0), metrics=[],
                                optional=(k == "income")) for k in KEYS]
    return Rating(ticker="X", symbol="X", asset_type="stock", name="X", score=score, label="Hold", coverage=1.0,
                  categories=categories, source="t")


def test_weights_add_up_and_cover_known_categories():
    for p in profiles.PROFILES.values():
        if p.weights:
            assert sum(p.weights.values()) == pytest.approx(1.0)
            assert set(p.weights) <= set(KEYS)


def test_balanced_and_non_stocks_are_unchanged():
    r = stock()
    assert profiles.apply(r, None) is r and profiles.apply(r, "balanced") is r and profiles.apply(r, "nope") is r
    coin = r.model_copy(update={"asset_type": "crypto"})
    assert profiles.apply(coin, "dividend") is coin
    unrated = r.model_copy(update={"score": None})
    assert profiles.apply(unrated, "growth") is unrated


def test_profile_reweights_the_overall_score():
    r = stock(growth=100.0, momentum=100.0, income=0.0)
    growth = profiles.apply(r, "growth")
    assert growth.score == round(0.35 * 100 + 0.20 * 100 + 0.45 * 50) and growth.profile == "growth"
    assert {c.key: c.weight for c in growth.categories}["income"] == 0.0
    assert growth.label == "Buy"


def test_dividend_profile_counts_a_missing_dividend_as_zero():
    payer = stock(income=90.0)
    non_payer = stock()
    non_payer.categories[-1] = non_payer.categories[-1].model_copy(update={"score": None})
    a, b = profiles.apply(payer, "dividend"), profiles.apply(non_payer, "dividend")
    assert a.score == round(0.30 * 90 + 0.70 * 50) and b.score == round(0.70 * 50)
    assert {c.key: c.optional for c in a.categories}["income"] is False


@pytest.fixture
def client(monkeypatch):
    market = MarketData(RecordedClient())
    market.name = "sample"
    monkeypatch.setattr(main, "service", main.RatingService(market, benchmarks=EMPTY, funds=FundStore()))
    monkeypatch.setattr(main, "_sample_explore", None)
    return TestClient(main.app)


def test_api_profiles(client):
    base = client.get("/api/rating/KO").json()
    div = client.get("/api/rating/KO?profile=dividend").json()
    assert base["profile"] is None and div["profile"] == "dividend" and div["score"] != base["score"]
    batch = client.get("/api/ratings?tickers=KO,BTC-USD&profile=dividend").json()
    assert batch[0]["score"] == div["score"] and batch[1]["profile"] is None
    explore = client.get("/api/explore?profile=growth").json()
    assert explore["profile"] == "growth" and "profiles" not in explore
    assert "profiles" not in client.get("/api/explore").json()
    names = [p["key"] for p in client.get("/api/methodology").json()["profiles"]]
    assert names == ["balanced", "dividend", "growth", "value", "safety"]
