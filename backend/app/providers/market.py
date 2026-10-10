"""Live market data: routes each symbol to the stock or crypto provider."""

from __future__ import annotations

import logging

from ..models import CryptoData, SearchResult, StockData
from ..sources import yahoo
from . import NotSupported, ProviderError, TickerNotFound
from .cache import TTLCache
from .crypto import CryptoProvider
from .stocks import FUND_TYPES, StockProvider

log = logging.getLogger(__name__)

SEARCH_TYPES = {"EQUITY": "stock", "ETF": "fund", "MUTUALFUND": "fund", "CRYPTOCURRENCY": "crypto"}


def _user_error(ticker: str, exc: Exception) -> ProviderError:
    if isinstance(exc, yahoo.YahooRateLimited):
        return ProviderError("Yahoo Finance is rate-limiting requests. Try again in a minute.")
    log.warning("Yahoo request for %s failed: %s", ticker, exc)
    return ProviderError(f"Couldn't get data for {ticker} from Yahoo Finance. Try again in a minute.")


class MarketData:
    name = "yahoo"

    def __init__(self, client: yahoo.Client | None = None):
        self.client = client or yahoo.Client()
        self.stocks = StockProvider(self.client)
        self.crypto = CryptoProvider(self.client)
        self._searches = TTLCache(600, max_entries=500)

    def fetch(self, ticker: str) -> StockData | CryptoData:
        try:
            chart = self.stocks.chart(ticker)
            kind = chart.meta.get("instrumentType")
            if kind == "CRYPTOCURRENCY":
                return self.crypto.fetch(ticker, chart)
            if kind == "EQUITY" or kind in FUND_TYPES:
                return self.stocks.fetch(ticker)
        except yahoo.YahooNotFound as exc:
            raise TickerNotFound(ticker) from exc
        except yahoo.YahooError as exc:
            raise _user_error(ticker, exc) from exc
        raise NotSupported(f"{ticker} is a {str(kind).lower()}, not a stock, fund or cryptocurrency.")

    def search(self, query: str) -> list[SearchResult]:
        key = query.strip().lower()
        try:
            quotes = self._searches.get(key, lambda: self.client.search(query, 15))
        except yahoo.YahooError as exc:
            raise _user_error(query, exc) from exc
        return to_results(quotes)


def to_results(quotes: list[dict], limit: int = 12) -> list[SearchResult]:
    out: list[SearchResult] = []
    seen: set[str] = set()
    for q in quotes:
        kind = SEARCH_TYPES.get(str(q.get("quoteType")))
        symbol = str(q.get("symbol") or "")
        if not kind or not symbol or symbol in seen:
            continue
        seen.add(symbol)
        name = q.get("longname") or q.get("shortname") or symbol
        if kind == "crypto" and name.endswith(" USD"):
            name = name[:-4]
        display = symbol.removesuffix("-USD") if kind == "crypto" else symbol
        out.append(SearchResult(ticker=symbol, symbol=display, name=name, asset_type=kind,
                                exchange=None if kind == "crypto" else q.get("exchDisp")))
        if len(out) >= limit:
            break
    return out
