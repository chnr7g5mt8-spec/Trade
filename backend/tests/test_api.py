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
    res = client.get("/api/rating/bad$ticker")
    assert res.status_code == 400
    assert "not a valid ticker" in res.json()["detail"]


def test_index_and_class_share_tickers_are_valid_syntax(client):
    # Not in the demo data, but must get past validation (404, not 400).
    for symbol in ["^GSPC", "BRK-B", "EURUSD=X", "RY.TO"]:
        assert client.get(f"/api/rating/{symbol}").status_code == 404


def test_batch_skips_unknown_invalid_and_dedupes_in_order(client):
    body = client.get("/api/ratings", params={"tickers": "KO, nope,bad$,aapl,KO,,MSFT"}).json()
    assert [r["ticker"] for r in body] == ["KO", "AAPL", "MSFT"]


def test_batch_limit(client):
    many = ",".join(f"T{i}" for i in range(26))
    assert client.get("/api/ratings", params={"tickers": many}).status_code == 400


def test_batch_skips_provider_errors(client, monkeypatch):
    class Flaky(SampleProvider):
        def fetch(self, ticker):
            if ticker == "AAPL":
                raise ProviderError("upstream down")
            return super().fetch(ticker)

    monkeypatch.setattr(main, "service", main.RatingService(Flaky()))
    body = client.get("/api/ratings", params={"tickers": "AAPL,KO"}).json()
    assert [r["ticker"] for r in body] == ["KO"]


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


def test_cache_expires(monkeypatch):
    calls = []

    class Counting(SampleProvider):
        def fetch(self, ticker):
            calls.append(ticker)
            return super().fetch(ticker)

    now = [1000.0]
    monkeypatch.setattr(main.time, "monotonic", lambda: now[0])
    svc = main.RatingService(Counting(), ttl=60)
    svc.get("KO")
    now[0] += 59
    svc.get("KO")
    now[0] += 2
    svc.get("KO")
    assert calls == ["KO", "KO"]


def test_cache_evicts_least_recently_used():
    svc = main.RatingService(SampleProvider(), max_entries=2)
    svc.get("AAPL")
    svc.get("MSFT")
    svc.get("AAPL")  # refresh AAPL, so MSFT is the oldest
    svc.get("KO")
    assert list(svc._cache) == ["AAPL", "KO"]


def test_errors_are_not_cached():
    calls = []

    class Failing(SampleProvider):
        def fetch(self, ticker):
            calls.append(ticker)
            raise ProviderError("down")

    svc = main.RatingService(Failing())
    for _ in range(2):
        with pytest.raises(ProviderError):
            svc.get("KO")
    assert calls == ["KO", "KO"]
