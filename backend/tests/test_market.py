import pytest

from app.providers import NotSupported, ProviderError, TickerNotFound
from app.providers.market import MarketData, to_results
from app.sources import yahoo
from app.sources.recorded import RecordedClient


@pytest.fixture
def market():
    return MarketData(RecordedClient())


def test_routes_each_asset_type(market):
    assert market.fetch("AAPL").asset_type == "stock"
    assert market.fetch("SPY").asset_type == "fund"
    btc = market.fetch("BTC-USD")
    assert btc.symbol == "BTC" and btc.market_cap > 0


def test_unknown_symbol(market):
    with pytest.raises(TickerNotFound):
        market.fetch("NOSUCH")


def test_index_is_not_supported(market):
    with pytest.raises(NotSupported, match="index"):
        market.fetch("^GSPC")


class FailingClient(RecordedClient):
    def __init__(self, exc):
        super().__init__()
        self.exc = exc

    def _get(self, path, params):
        raise self.exc


def test_rate_limit_message(market):
    m = MarketData(FailingClient(yahoo.YahooRateLimited("429")))
    with pytest.raises(ProviderError, match="rate-limiting"):
        m.fetch("AAPL")


def test_other_failures_have_a_plain_message():
    m = MarketData(FailingClient(yahoo.YahooError("curl: (6) Could not resolve host")))
    with pytest.raises(ProviderError) as err:
        m.fetch("AAPL")
    assert "curl" not in str(err.value)
    assert "Try again" in str(err.value)


def test_search_maps_and_filters_real_results(market):
    results = market.search("apple")
    symbols = [r.ticker for r in results]
    assert symbols[0] == "AAPL"
    assert not any(s.endswith("=F") for s in symbols)  # futures are dropped
    assert results[0].asset_type == "stock" and results[0].exchange == "NASDAQ"


def test_search_crypto_display(market):
    results = market.search("bitcoin")
    btc = next(r for r in results if r.ticker == "BTC-USD")
    assert btc.symbol == "BTC" and btc.asset_type == "crypto" and btc.name == "Bitcoin"
    assert btc.exchange is None


def test_to_results_dedupes_and_limits():
    quotes = [{"symbol": "A", "quoteType": "EQUITY", "longname": "A Inc"}] * 3 + [
        {"symbol": f"S{i}", "quoteType": "EQUITY"} for i in range(20)] + [{"symbol": "I", "quoteType": "INDEX"}]
    out = to_results(quotes)
    assert len(out) == 12 and [r.ticker for r in out].count("A") == 1
    assert out[1].name == "S0"  # falls back to the symbol
