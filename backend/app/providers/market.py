"""Live market data: routes each symbol to the stock or crypto provider."""

from __future__ import annotations

import logging

from ..models import CryptoData, NewsItem, SearchResult, StockData
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
        self._news = TTLCache(900, max_entries=500)

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


    def news(self, ticker: str, name: str | None = None) -> list[NewsItem]:
        """Yahoo finds news by plain symbols and names, not always by listing symbols like ENB.TO or BTC-USD."""
        queries = list(dict.fromkeys(q for q in (ticker, base_symbol(ticker), keyword(name)) if q))
        try:
            for q in queries:
                items = self._news.get(q, lambda: self.client.news(q, 12))
                found = to_news(items, ticker, name)
                if found:
                    return found
        except yahoo.YahooError as exc:
            raise _user_error(ticker, exc) from exc
        return []


def base_symbol(ticker: str) -> str:
    """'ENB.TO' -> 'ENB', 'BTC-USD' -> 'BTC'."""
    return ticker.upper().split(".")[0].removesuffix("-USD")


_NAME_NOISE = {"the", "inc", "inc.", "corp", "corp.", "corporation", "company", "co.", "ltd", "ltd.", "plc", "sa",
               "s.a.", "ag", "group", "holdings", "trust", "etf", "fund", "&"}


def keyword(name: str | None) -> str | None:
    """The distinctive first word of a name: 'The Coca-Cola Company' -> 'Coca-Cola'."""
    words = [w.strip(",") for w in (name or "").split() if w.strip(",").lower() not in _NAME_NOISE]
    return words[0] if words and len(words[0]) >= 3 else None


def to_news(items: list[dict], ticker: str, name: str | None = None, limit: int = 8) -> list[NewsItem]:
    """Stories about the ticker, newest first, those mainly about it first; web links only."""
    base = base_symbol(ticker)
    word = (keyword(name) or "").lower()

    def related(n: dict) -> list[str]:
        return [base_symbol(str(t)) for t in n.get("relatedTickers") or []]

    def about(n: dict) -> bool:
        return base in related(n) or (bool(word) and word in str(n.get("title", "")).lower())

    def mainly(n: dict) -> bool:
        tags = related(n)
        title = str(n.get("title", "")).lower()
        return (bool(tags) and tags[0] == base) or (bool(word) and word in title) or base.lower() in title.split()

    def thumb(n: dict) -> str | None:
        sizes = ((n.get("thumbnail") or {}).get("resolutions")) or []
        small = [r for r in sizes if isinstance(r, dict) and str(r.get("url", "")).startswith("https://")]
        small.sort(key=lambda r: r.get("width") or 0)
        return small[0]["url"] if small else None

    usable = [n for n in items if str(n.get("link", "")).startswith("https://")]
    tagged = [n for n in usable if about(n)]
    chosen = tagged if tagged else usable
    chosen.sort(key=lambda n: (not mainly(n), -(n.get("providerPublishTime") or 0)))
    seen: set[str] = set()
    out: list[NewsItem] = []
    for n in chosen:
        title = " ".join(str(n["title"]).split())
        if title.lower() in seen:
            continue
        seen.add(title.lower())
        published = n.get("providerPublishTime")
        out.append(NewsItem(title=title, publisher=n.get("publisher"), link=n["link"],
                            published=int(published) if isinstance(published, (int, float)) else None,
                            thumbnail=thumb(n)))
        if len(out) == limit:
            break
    return out


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
