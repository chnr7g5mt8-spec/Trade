import pytest

from app.providers.crypto import CryptoDirectory, PAGE_SIZE, build_crypto, is_crypto_symbol, pegged_to
from app.sources import recorded
from tests.recordings import RECORDED_AT, chart


def listing(symbol):
    quotes = recorded.load("screener_crypto")["finance"]["result"][0]["quotes"]
    for i, q in enumerate(quotes):
        if q["symbol"] == symbol:
            return q, i + 1
    return None, None


def test_bitcoin_from_real_recordings():
    q, rank = listing("BTC-USD")
    d = build_crypto("BTC-USD", chart("BTC-USD"), q, rank, now=RECORDED_AT)
    assert d.symbol == "BTC" and d.name == "Bitcoin"
    assert rank == 1
    assert d.market_cap > 5e11
    assert d.max_supply == 21_000_000
    assert 0.9 < d.supply_ratio <= 1.0
    assert 0.2 < d.volatility_1y < 1.5  # daily data, not monthly
    assert len(d.quote.price_history) == 60
    assert d.from_all_time_high <= 0
    assert d.age_years > 15
    assert d.quote.market_state == "open"  # crypto trades around the clock
    assert not d.is_stablecoin
    labels = [f.label for f in d.facts]
    assert labels[:2] == ["Rank by market cap", "Market cap"]


def test_unlimited_supply_has_no_supply_ratio():
    q, rank = listing("ETH-USD")
    d = build_crypto("ETH-USD", chart("ETH-USD"), q, rank, now=RECORDED_AT)
    assert d.max_supply is None and d.supply_ratio is None


def test_stablecoin_is_detected():
    q, rank = listing("USDT-USD")
    d = build_crypto("USDT-USD", chart("USDT-USD"), q, rank, now=RECORDED_AT)
    assert d.is_stablecoin
    assert any("stablecoin" in n for n in d.notes)


def test_coin_missing_from_listings_still_gets_price_data():
    d = build_crypto("BTC-USD", chart("BTC-USD"), None, None, now=RECORDED_AT)
    assert d.market_cap is None and d.turnover is None
    assert d.volatility_1y is not None
    assert any("price data only" in n for n in d.notes)


def test_is_crypto_symbol():
    assert is_crypto_symbol("btc-usd") and is_crypto_symbol("PEPE24478-USD")
    assert not is_crypto_symbol("AAPL") and not is_crypto_symbol("VOD.L")


class PagedClient:
    def __init__(self, total):
        self.total = total
        self.calls = []

    def screener(self, scr_id, count, start):
        self.calls.append(start)
        n = max(0, min(count, self.total - start))
        return [{"symbol": f"C{start + i}-USD"} for i in range(n)], self.total


def test_directory_pages_until_found_and_caches_pages():
    c = PagedClient(total=PAGE_SIZE * 3 + 10)
    d = CryptoDirectory(c)
    q, rank = d.find(f"C{PAGE_SIZE + 5}-USD")
    assert rank == PAGE_SIZE + 6
    assert c.calls == [0, PAGE_SIZE]
    d.find("C3-USD")
    assert c.calls == [0, PAGE_SIZE]  # cached
    assert d.find("NOPE-USD") == (None, None)
    assert c.calls[-1] == PAGE_SIZE * 3  # stopped at the short last page


def test_directory_failure_is_not_fatal():
    class Broken:
        def screener(self, *a):
            from app.sources.yahoo import YahooError
            raise YahooError("down")

    assert CryptoDirectory(Broken()).find("BTC-USD") == (None, None)


@pytest.mark.parametrize("price, vol, name, expected", [
    (1.0004, 0.01, "Tether USDt", "the US dollar ($1)"),
    (0.998, 0.11, "crvUSD", "the US dollar ($1)"),  # wobbles more, still pegged
    (1.16, 0.07, "EURC", "a traditional currency"),
    (4010.0, 0.22, "PAX Gold", "the price of gold"),
    (3990.0, 0.21, "Tether Gold", "the price of gold"),
    (1.02, 0.85, "Some Coin", None),  # trades near $1 but floats freely
    (67000.0, 0.45, "Bitcoin", None),
    (0.31, 0.95, "Goldfinch", None),  # "gold" only as a whole word
    (None, 0.01, "x", None),
    (1.0, None, "x", None),
])
def test_pegged_coins(price, vol, name, expected):
    assert pegged_to(price, vol, name) == expected


def test_yahoo_numeric_symbol_ids_are_shown_as_the_symbol():
    q, rank = listing("BTC-USD")
    c = chart("BTC-USD")
    d = build_crypto("HYPE32196-USD", c, {**q, "fromCurrency": "HYPE32196"}, rank, now=RECORDED_AT)
    assert d.symbol == "HYPE"
    assert build_crypto("1INCH-USD", c, {**q, "fromCurrency": "1INCH"}, rank, now=RECORDED_AT).symbol == "1INCH"
