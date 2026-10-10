import pytest
from fastapi.testclient import TestClient

from app import main
from app.providers import ProviderError, SampleProvider


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(main, "service", main.RatingService(SampleProvider()))
    return TestClient(main.app)


def test_health(client):
    assert client.get("/health").json() == {"status": "ok", "source": "sample"}


def test_rating(client):
    body = client.get("/api/rating/msft").json()
    assert body["ticker"] == "MSFT"
    assert 0 <= body["score"] <= 100
    assert body["label"] in {"Strong Buy", "Buy", "Hold", "Sell", "Strong Sell"}
    assert [c["key"] for c in body["categories"]] == ["valuation", "profitability", "growth", "health", "momentum"]
    assert len(body["price_history"]) == 60


def test_unknown_ticker_404(client):
    assert client.get("/api/rating/NOPE").status_code == 404


def test_invalid_ticker_400(client):
    assert client.get("/api/rating/bad$ticker").status_code == 400


def test_batch_skips_unknown_and_dedupes(client):
    body = client.get("/api/ratings", params={"tickers": "AAPL, nope,aapl,KO"}).json()
    assert [r["ticker"] for r in body] == ["AAPL", "KO"]


def test_provider_error_502(client, monkeypatch):
    class Broken:
        name = "broken"

        def fetch(self, ticker):
            raise ProviderError("upstream down")

    monkeypatch.setattr(main, "service", main.RatingService(Broken()))
    assert client.get("/api/rating/AAPL").status_code == 502


def test_cache_avoids_refetch():
    calls = []

    class Counting(SampleProvider):
        def fetch(self, ticker):
            calls.append(ticker)
            return super().fetch(ticker)

    svc = main.RatingService(Counting())
    svc.get("KO")
    svc.get("KO")
    assert calls == ["KO"]
