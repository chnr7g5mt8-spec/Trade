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
