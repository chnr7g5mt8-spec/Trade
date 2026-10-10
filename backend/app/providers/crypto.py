"""Cryptocurrency data from Yahoo Finance.

Prices and history come from the chart endpoint. Market cap, supply and
volume come from Yahoo's "all cryptocurrencies" screener (8,000+ coins,
largest first), which is paged through and cached.
"""

from __future__ import annotations

import logging
import re
import time

from .. import stats
from ..models import CryptoData, Fact
from ..sources import yahoo
from ..sources.yahoo import Chart
from .cache import TTLCache
from .stocks import build_quote

log = logging.getLogger(__name__)

SCREENER_ID = "all_cryptocurrencies_us"
PAGE_SIZE = 250
MAX_PAGES = 40  # ~10,000 coins


def is_crypto_symbol(ticker: str) -> bool:
    return ticker.upper().endswith("-USD")


def _days_back(chart: Chart, days: int) -> float | None:
    """Close `days` before the latest one."""
    if not chart.timestamps:
        return None
    cutoff = chart.timestamps[-1] - days * 86400
    best = None
    for t, c in zip(chart.timestamps, chart.closes):
        if t <= cutoff:
            best = c
        else:
            break
    return best


def pegged_to(price: float | None, volatility: float | None, name: str | None) -> str | None:
    """What a coin is designed to track (stablecoins, gold tokens), or None for a free-floating coin.

    Free-floating coins swing far more than 15% a year, so anything steadier
    is pegged to something: the dollar when it trades near $1, otherwise
    another currency (euro stablecoins). Gold tokens move like gold, which is
    steadier than any free-floating coin.
    """
    if not price or volatility is None:
        return None
    if 0.95 <= price <= 1.05 and volatility < 0.15:
        return "the US dollar ($1)"
    if volatility < 0.12:
        return "a traditional currency"
    if name and re.search(r"\bgold\b", name, re.IGNORECASE) and volatility < 0.5:
        return "the price of gold"
    return None


def build_crypto(ticker: str, chart: Chart, listing: dict | None = None, rank: int | None = None,
                 now: float | None = None) -> CryptoData:
    now = time.time() if now is None else now
    listing = listing or {}
    meta = chart.meta
    quote = build_quote(chart, None, now)
    price = quote.price
    year_start = chart.timestamps[-1] - 365 * 86400 if chart.timestamps else 0
    year = [c for t, c in zip(chart.timestamps, chart.closes) if t >= year_start]

    symbol = listing.get("fromCurrency") or ticker.upper().removesuffix("-USD").split("-")[0]
    # Yahoo tells apart coins that share a symbol with a numeric id (HYPE32196); show the symbol.
    symbol = re.sub(r"^([A-Z]{2,})\d{4,}$", r"\1", symbol)
    name = listing.get("longName") or listing.get("shortName") or meta.get("longName") or meta.get("shortName")
    if name and name.endswith(" USD"):
        name = name[:-4]

    market_cap = stats.num(listing.get("marketCap"))
    volume = stats.num(listing.get("volume24Hr")) or stats.num(listing.get("volumeAllCurrencies"))
    circulating = stats.num(listing.get("circulatingSupply"))
    max_supply = stats.num(listing.get("maxSupply"))  # 0 means no fixed maximum
    started = stats.epoch(listing.get("startDate")) or stats.epoch(meta.get("firstTradeDate"))

    data: dict = dict(ticker=ticker, symbol=symbol, name=name, quote=quote, market_cap=market_cap,
                      volume_24h=volume, circulating_supply=circulating,
                      max_supply=max_supply if max_supply and max_supply > 0 else None)
    if market_cap and volume is not None and market_cap > 0:
        data["turnover"] = volume / market_cap
    if circulating and max_supply and max_supply > 0:
        data["supply_ratio"] = min(1.0, circulating / max_supply)
    m = stats.momentum(year)
    data["return_1y"] = m["return_1y"]
    data["price_vs_sma50"] = m["price_vs_sma50"]
    data["price_vs_sma200"] = m["price_vs_sma200"]
    month_ago = _days_back(chart, 30)
    if month_ago and price:
        data["return_30d"] = price / month_ago - 1
    data["volatility_1y"] = stats.annualized_volatility(year, 365)
    data["max_drawdown_1y"] = stats.max_drawdown(year)
    if chart.closes and price:
        data["from_all_time_high"] = min(0.0, price / max(max(chart.closes), price) - 1)
    if started:
        data["age_years"] = max(0.0, (now - started) / (365.25 * 86400))

    notes: list[str] = []
    pegged = pegged_to(price, data.get("volatility_1y"), name)
    if pegged:
        data["is_stablecoin"] = True
        notes.append(f"This is a stablecoin or token designed to track {pegged}, so it isn't rated "
                     "as an investment.")
    if not listing:
        notes.append("Market cap and supply aren't available for this coin, so the rating uses price data only.")

    facts: list[Fact] = []
    if rank:
        facts.append(Fact(label="Rank by market cap", value=f"#{rank}"))
    if market_cap:
        facts.append(Fact(label="Market cap", value=_usd(market_cap)))
    if volume:
        facts.append(Fact(label="24h volume", value=_usd(volume)))
    if circulating:
        supply = f"{circulating:,.0f} {symbol}"
        if data.get("max_supply"):
            supply += f" of {data['max_supply']:,.0f} max"
        facts.append(Fact(label="Circulating supply", value=supply))
    return CryptoData(**data, notes=notes, facts=facts)


def _usd(v: float) -> str:
    for unit, size in (("T", 1e12), ("B", 1e9), ("M", 1e6), ("K", 1e3)):
        if abs(v) >= size:
            return f"${v / size:.2f}{unit}"
    return f"${v:,.2f}"


class CryptoDirectory:
    """Yahoo's crypto listings, largest first, fetched a page at a time and cached."""

    TTL = 15 * 60

    def __init__(self, client: yahoo.Client):
        self.client = client
        self._pages = TTLCache(self.TTL, max_entries=MAX_PAGES)

    def page(self, n: int) -> list[dict]:
        def load() -> list[dict]:
            quotes, _total = self.client.screener(SCREENER_ID, PAGE_SIZE, n * PAGE_SIZE)
            return quotes
        return self._pages.get(str(n), load)

    def find(self, ticker: str) -> tuple[dict | None, int | None]:
        """The coin's listing and market-cap rank, if Yahoo lists it."""
        target = ticker.upper()
        for n in range(MAX_PAGES):
            try:
                quotes = self.page(n)
            except yahoo.YahooError as exc:
                log.warning("crypto listing page %d failed: %s", n, exc)
                return None, None
            for i, q in enumerate(quotes):
                if str(q.get("symbol", "")).upper() == target:
                    return q, n * PAGE_SIZE + i + 1
            if len(quotes) < PAGE_SIZE:
                break
        return None, None

    def top(self, count: int = 100) -> list[dict]:
        out: list[dict] = []
        for n in range((count + PAGE_SIZE - 1) // PAGE_SIZE):
            out.extend(self.page(n))
        return out[:count]


class CryptoProvider:
    name = "yahoo"

    def __init__(self, client: yahoo.Client):
        self.client = client
        self.directory = CryptoDirectory(client)

    def fetch(self, ticker: str, chart: Chart) -> CryptoData:
        """`chart` is ten years of daily prices, which covers every major coin's all-time high."""
        listing, rank = self.directory.find(ticker)
        return build_crypto(ticker, chart, listing, rank)
