"""YahooProvider tests against a fake yfinance.Ticker (no network access)."""

import math

import pandas as pd
import pytest
import yfinance
from yfinance.exceptions import YFRateLimitError

from app.providers import ProviderError, TickerNotFound, YahooProvider
from app.scoring import rate

AAPL_INFO = {
    "shortName": "Apple Inc.",
    "sector": "Technology",
    "currency": "USD",
    "currentPrice": 230.5,
    "marketCap": 3.5e12,
    "trailingPE": 35.1,
    "forwardPE": 29.8,
    "trailingPegRatio": 2.2,
    "priceToBook": 52.0,
    "returnOnEquity": 1.5,
    "profitMargins": 0.24,
    "operatingMargins": 0.31,
    "revenueGrowth": 0.06,
    "earningsGrowth": 0.11,
    "debtToEquity": 151.9,
    "currentRatio": 0.87,
    "freeCashflow": 1.1e11,
    "targetMeanPrice": 250.0,
    "recommendationKey": "strong_buy",
    "fiftyTwoWeekHigh": 260.1,
    "fiftyTwoWeekLow": 164.1,
}


def make_ticker(info=None, closes=None, info_exc=None, history_exc=None):
    class FakeTicker:
        def __init__(self, symbol):
            self.symbol = symbol

        @property
        def info(self):
            if info_exc:
                raise info_exc
            return info

        def history(self, period, auto_adjust):
            assert period == "1y" and auto_adjust is True
            if history_exc:
                raise history_exc
            if closes is None:
                return pd.DataFrame()
            return pd.DataFrame({"Close": closes})

    return FakeTicker


def use(monkeypatch, **kwargs):
    monkeypatch.setattr(yfinance, "Ticker", make_ticker(**kwargs))


def test_maps_yahoo_fields(monkeypatch):
    closes = [200.0 + i * 0.12 for i in range(250)]
    use(monkeypatch, info=AAPL_INFO, closes=closes)
    data = YahooProvider().fetch("AAPL")

    assert data.name == "Apple Inc."
    assert data.price == 230.5
    assert data.peg_ratio == 2.2
    assert data.debt_to_equity == 151.9
    assert data.analyst_recommendation == "Strong Buy"
    assert math.isclose(data.return_1y, closes[-1] / closes[0] - 1)
    assert data.price_vs_sma50 > 0 and data.price_vs_sma200 > 0
    assert len(data.price_history) == 60
    assert data.price_history[0] == closes[0] and data.price_history[-1] == round(closes[-1], 4)

    r = rate(data, "yahoo")
    assert r.coverage == 1.0
    assert r.score is not None


def test_falls_back_to_pegratio_and_last_close(monkeypatch):
    info = {"shortName": "X", "pegRatio": 1.5, "recommendationKey": "none"}
    use(monkeypatch, info=info, closes=[10.0, 11.0, 12.0])
    data = YahooProvider().fetch("X")
    assert data.peg_ratio == 1.5
    assert data.price == 12.0
    assert data.analyst_recommendation is None


def test_cleans_bad_values(monkeypatch):
    info = {"currentPrice": 5.0, "trailingPE": "Infinity", "forwardPE": float("nan"), "marketCap": True,
            "priceToBook": "3.5"}
    use(monkeypatch, info=info, closes=[4.0, float("nan"), 5.0])
    data = YahooProvider().fetch("X")
    assert data.trailing_pe is None
    assert data.forward_pe is None
    assert data.market_cap is None
    assert data.price_to_book == 3.5
    assert data.price_history == [4.0, 5.0]


def test_unknown_ticker(monkeypatch):
    # What yfinance returns by default for a symbol Yahoo doesn't know.
    use(monkeypatch, info={"trailingPegRatio": None}, closes=None)
    with pytest.raises(TickerNotFound):
        YahooProvider().fetch("NOPE")


def test_none_info_treated_as_empty(monkeypatch):
    use(monkeypatch, info=None, closes=None)
    with pytest.raises(TickerNotFound):
        YahooProvider().fetch("NOPE")


def test_info_only_without_history_still_rates(monkeypatch):
    use(monkeypatch, info=AAPL_INFO, closes=None)
    data = YahooProvider().fetch("AAPL")
    assert data.price == 230.5
    assert data.return_1y is None
    assert data.price_history == []


def test_network_error_is_provider_error_not_404(monkeypatch, caplog):
    use(monkeypatch, info_exc=ConnectionError("curl: (6) Could not resolve host"))
    with pytest.raises(ProviderError) as err:
        YahooProvider().fetch("AAPL")
    # Plain message for the user; technical detail only in the server log.
    assert str(err.value) == "Couldn't get data for AAPL from Yahoo Finance. Try again in a minute."
    assert "curl" not in str(err.value)
    assert "Could not resolve host" in caplog.text


def test_rate_limit_has_friendly_message(monkeypatch):
    use(monkeypatch, info=AAPL_INFO, history_exc=YFRateLimitError())
    with pytest.raises(ProviderError, match="rate-limiting"):
        YahooProvider().fetch("AAPL")


# --- Live quote: price freshness, market state, pre/after-hours -------------

from app.providers import quote_fields  # noqa: E402

FRI_CLOSE = 1_791_576_000  # Fri Oct 9 2026, 4:00 PM New York: a regular-session close
LATER = FRI_CLOSE + 4 * 3600


def test_live_quote_price_wins_over_financial_snapshot():
    q = quote_fields({"currentPrice": 225.0, "regularMarketPrice": 231.4, "regularMarketTime": FRI_CLOSE,
                      "marketState": "REGULAR"})
    assert q["price"] == 231.4
    assert q["price_time"] == FRI_CLOSE
    assert q["market_state"] == "open"
    assert q["extended_price"] is None


def test_snapshot_price_is_only_a_fallback():
    assert quote_fields({"currentPrice": 225.0})["price"] == 225.0


def test_after_hours_price_when_closed():
    q = quote_fields({"regularMarketPrice": 231.4, "regularMarketTime": FRI_CLOSE, "marketState": "CLOSED",
                      "postMarketPrice": 233.0, "postMarketTime": LATER})
    assert q["market_state"] == "closed"
    assert (q["extended_price"], q["extended_session"]) == (233.0, "post")


def test_stale_after_hours_price_is_ignored():
    # An after-hours quote older than the latest regular trade is out of date.
    q = quote_fields({"regularMarketPrice": 231.4, "regularMarketTime": LATER, "marketState": "REGULAR",
                      "postMarketPrice": 233.0, "postMarketTime": FRI_CLOSE})
    assert q["extended_price"] is None


def test_pre_market_price():
    q = quote_fields({"regularMarketPrice": 231.4, "regularMarketTime": FRI_CLOSE, "marketState": "PREPRE",
                      "preMarketPrice": 229.9, "preMarketTime": LATER})
    assert q["market_state"] == "pre"
    assert (q["extended_price"], q["extended_session"]) == (229.9, "pre")


def test_unknown_state_and_formatted_times_are_ignored():
    q = quote_fields({"regularMarketPrice": 10.0, "regularMarketTime": "4:00PM EDT", "marketState": "WEIRD"})
    assert q["price_time"] is None
    assert q["market_state"] is None


def test_quote_fields_reach_stock_data(monkeypatch):
    info = dict(AAPL_INFO, regularMarketPrice=231.4, regularMarketTime=FRI_CLOSE, marketState="POST",
                postMarketPrice=232.1, postMarketTime=LATER)
    use(monkeypatch, info=info, closes=[200.0, 210.0])
    data = YahooProvider().fetch("AAPL")
    assert data.price == 231.4
    assert data.price_time == FRI_CLOSE
    assert data.market_state == "post"
    assert data.extended_price == 232.1


# --- History is reused across quote refreshes ------------------------------

def counting_ticker(closes_seq):
    calls = []

    class FakeTicker:
        def __init__(self, symbol):
            pass

        @property
        def info(self):
            return {"regularMarketPrice": 10.0}

        def history(self, period, auto_adjust):
            calls.append(period)
            closes = closes_seq[min(len(calls), len(closes_seq)) - 1]
            return pd.DataFrame({"Close": closes}) if closes else pd.DataFrame()

    return FakeTicker, calls


def test_history_is_cached_between_fetches(monkeypatch):
    fake, calls = counting_ticker([[1.0, 2.0]])
    monkeypatch.setattr(yfinance, "Ticker", fake)
    p = YahooProvider()
    p.fetch("X")
    p.fetch("X")
    assert len(calls) == 1


def test_empty_history_is_not_cached(monkeypatch):
    fake, calls = counting_ticker([[], [1.0, 2.0]])
    monkeypatch.setattr(yfinance, "Ticker", fake)
    p = YahooProvider()
    assert p.fetch("X").price_history == []
    assert p.fetch("X").price_history == [1.0, 2.0]
    assert len(calls) == 2


def test_history_cache_expires(monkeypatch):
    import app.providers as providers

    fake, calls = counting_ticker([[1.0, 2.0]])
    monkeypatch.setattr(yfinance, "Ticker", fake)
    now = [1000.0]
    monkeypatch.setattr(providers.time, "monotonic", lambda: now[0])
    p = YahooProvider()
    p.fetch("X")
    now[0] += YahooProvider.HISTORY_TTL_SECONDS + 1
    p.fetch("X")
    assert len(calls) == 2
