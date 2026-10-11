import pytest
from fastapi.testclient import TestClient

from app import main
from app.benchmarks import EMPTY
from app.funds import FundStore
from app.providers import ProviderError
from app.providers.market import MarketData
from app.sources.recorded import RecordedClient


def recorded_service(**kw):
    market = MarketData(RecordedClient())
    market.name = "sample"
    kw.setdefault("funds", FundStore())
    return main.RatingService(market, benchmarks=EMPTY, **kw)


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(main, "service", recorded_service())
    return TestClient(main.app)


def test_health(client):
    assert client.get("/health").json() == {"status": "ok", "source": "sample"}


def test_stock_rating(client):
    body = client.get("/api/rating/aapl").json()
    assert body["ticker"] == "AAPL" and body["symbol"] == "AAPL" and body["asset_type"] == "stock"
    assert body["name"] == "Apple Inc." and body["industry"] == "Consumer Electronics"
    assert 0 <= body["score"] <= 100
    assert body["label"] in {"Strong Buy", "Buy", "Hold", "Sell", "Strong Sell"}
    assert [c["key"] for c in body["categories"]] == ["valuation", "profitability", "growth", "health",
                                                       "consistency", "momentum", "risk", "income"]
    assert body["currency"] == "USD" and body["market_state"] in {"open", "pre", "post", "closed"}
    assert len(body["price_history"]) == 60
    assert any(f["label"] == "Market cap" for f in body["facts"])


def test_crypto_rating(client):
    body = client.get("/api/rating/btc-usd").json()
    assert body["asset_type"] == "crypto" and body["symbol"] == "BTC" and body["ticker"] == "BTC-USD"
    assert [c["key"] for c in body["categories"]] == ["market", "momentum", "risk", "maturity"]
    assert body["score"] is not None


def test_fund_and_stablecoin_are_not_rated(client):
    for t in ("SPY", "USDT-USD"):
        body = client.get(f"/api/rating/{t}").json()
        assert body["score"] is None and body["label"] == "Not rated" and body["notes"]


def test_errors(client):
    assert client.get("/api/rating/NOSUCH").status_code == 404
    res = client.get("/api/rating/bad$ticker")
    assert res.status_code == 400 and "not a valid ticker" in res.json()["detail"]
    res = client.get("/api/rating/^GSPC")
    assert res.status_code == 422 and "index" in res.json()["detail"]


def test_batch_mixed_assets_in_order_skipping_bad_ones(client):
    body = client.get("/api/ratings", params={"tickers": "KO, nope,bad$,btc-usd,KO,,^GSPC,MSFT"}).json()
    assert [r["ticker"] for r in body] == ["KO", "BTC-USD", "MSFT"]


def test_batch_limit(client):
    many = ",".join(f"T{i}" for i in range(26))
    assert client.get("/api/ratings", params={"tickers": many}).status_code == 400


def test_batch_reports_outage_only_when_nothing_worked(client, monkeypatch):
    class Down:
        name = "yahoo"

        def fetch(self, ticker):
            raise ProviderError("Yahoo Finance is rate-limiting requests. Try again in a minute.")

    monkeypatch.setattr(main, "service", main.RatingService(Down(), benchmarks=EMPTY))
    res = client.get("/api/ratings", params={"tickers": "AAPL,KO"})
    assert res.status_code == 502 and "rate-limiting" in res.json()["detail"]
    assert client.get("/api/rating/AAPL").status_code == 502


def test_batch_of_unknown_tickers_is_empty(client):
    res = client.get("/api/ratings", params={"tickers": "NOPE,ZZZZ"})
    assert res.status_code == 200 and res.json() == []


def test_search(client):
    body = client.get("/api/search", params={"q": "toyota"}).json()
    assert body[0]["ticker"] in {"TM", "7203.T"}
    assert all(r["asset_type"] in {"stock", "fund", "crypto"} for r in body)
    assert client.get("/api/search", params={"q": ""}).status_code == 422


def test_methodology(client):
    body = client.get("/api/methodology").json()
    assert body["labels"][0] == {"label": "Strong Buy", "min_score": 80}
    stock_weights = [c["weight"] for c in body["stock_categories"] if not c["optional"]]
    assert sum(stock_weights) == pytest.approx(1.0, abs=0.01)
    assert any(m["relative"] for c in body["stock_categories"] for m in c["metrics"])
    assert "track_record" in body and "benchmarks" in body


def test_api_responses_are_never_cached(client):
    for path in ("/api/rating/KO", "/api/ratings?tickers=KO", "/api/rating/NOPE", "/api/search?q=apple"):
        assert client.get(path).headers["cache-control"] == "no-store"


class Counting:
    name = "sample"

    def __init__(self, state="closed"):
        self.calls = []
        self.market = MarketData(RecordedClient())
        self.state = state

    def fetch(self, ticker):
        self.calls.append(ticker)
        data = self.market.fetch(ticker)
        data.quote.market_state = self.state
        return data


@pytest.mark.parametrize("state, ttl", [("open", 60), ("pre", 60), ("post", 60), ("closed", 900), (None, 900)])
def test_cache_is_short_while_market_trades(monkeypatch, state, ttl):
    m = Counting(state)
    now = [1000.0]
    monkeypatch.setattr(main.time, "monotonic", lambda: now[0])
    svc = main.RatingService(m, benchmarks=EMPTY)
    svc.get("KO")
    now[0] += ttl - 1
    svc.get("KO")
    assert len(m.calls) == 1
    now[0] += 2
    svc.get("KO")
    assert len(m.calls) == 2


def test_cache_evicts_least_recently_used():
    svc = main.RatingService(Counting(), benchmarks=EMPTY, max_entries=2)
    svc.get("AAPL")
    svc.get("MSFT")
    svc.get("AAPL")
    svc.get("KO")
    assert list(svc._cache) == ["AAPL", "KO"]


def test_errors_are_not_cached():
    calls = []

    class Failing:
        name = "x"

        def fetch(self, ticker):
            calls.append(ticker)
            raise ProviderError("down")

    svc = main.RatingService(Failing(), benchmarks=EMPTY)
    for _ in range(2):
        with pytest.raises(ProviderError):
            svc.get("KO")
    assert calls == ["KO", "KO"]


def test_unexpected_data_error_is_reported_not_crashed(monkeypatch):
    class Broken(MarketData):
        def fetch(self, ticker):
            if ticker == "BAD":
                raise ZeroDivisionError("odd data")
            return super().fetch(ticker)

    market = Broken(RecordedClient())
    market.name = "sample"
    monkeypatch.setattr(main, "service", main.RatingService(market, benchmarks=EMPTY, funds=FundStore()))
    client = TestClient(main.app)
    res = client.get("/api/rating/BAD")
    assert res.status_code == 502 and "doesn't understand" in res.json()["detail"]
    # One broken ticker doesn't blank out the watchlist.
    assert [r["ticker"] for r in client.get("/api/ratings?tickers=BAD,AAPL").json()] == ["AAPL"]


def test_fx_endpoint(client, monkeypatch):
    monkeypatch.setattr(main.service.market.stocks, "fx", lambda a, b: {"USDCAD": 1.37}.get(a + b))
    assert client.get("/api/fx?pairs=usdcad,CADCAD,EURJPY").json() == {
        "rates": {"USDCAD": 1.37, "CADCAD": 1.0, "EURJPY": None}}
    assert client.get("/api/fx?pairs=USD").status_code == 400
    too_many = ",".join(f"USDAA{chr(65 + i)}" for i in range(21))
    assert client.get(f"/api/fx?pairs={too_many}").status_code == 400


def test_rating_includes_dividend_schedule(client):
    d = client.get("/api/rating/KO").json()["dividend"]
    assert d["per_year"] == 4 and d["amount"] > 0 and d["next_ex_date"] > d["last_ex_date"]
    assert client.get("/api/rating/BTC-USD").json()["dividend"] is None
