"""HTTP API consumed by the mobile app.

Run:  uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
Set DATA_SOURCE=sample to use bundled demo data instead of Yahoo Finance.
"""

from __future__ import annotations

import os
import re
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from .models import Rating
from .providers import Provider, ProviderError, SampleProvider, TickerNotFound, YahooProvider
from .scoring import rate

TICKER_RE = re.compile(r"^[A-Z0-9^][A-Z0-9.\-^=]{0,14}$")
CACHE_TTL_SECONDS = 15 * 60
CACHE_MAX_ENTRIES = 500
MAX_BATCH = 25
BATCH_WORKERS = 6


def _make_provider() -> Provider:
    return SampleProvider() if os.getenv("DATA_SOURCE", "yahoo").lower() == "sample" else YahooProvider()


class RatingService:
    """Rates tickers through a provider, caching results for `ttl` seconds."""

    def __init__(self, provider: Provider, ttl: float = CACHE_TTL_SECONDS, max_entries: int = CACHE_MAX_ENTRIES):
        self.provider = provider
        self.ttl = ttl
        self.max_entries = max_entries
        self._cache: OrderedDict[str, tuple[float, Rating]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, ticker: str) -> Rating:
        with self._lock:
            hit = self._cache.get(ticker)
            if hit and time.monotonic() - hit[0] < self.ttl:
                self._cache.move_to_end(ticker)
                return hit[1]
        rating = rate(self.provider.fetch(ticker), source=self.provider.name)
        with self._lock:
            self._cache[ticker] = (time.monotonic(), rating)
            self._cache.move_to_end(ticker)
            while len(self._cache) > self.max_entries:
                self._cache.popitem(last=False)
        return rating


def parse_ticker(raw: str) -> str | None:
    ticker = raw.strip().upper()
    return ticker if TICKER_RE.match(ticker) else None


app = FastAPI(title="Stock Rating API", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET"], allow_headers=["*"])
service = RatingService(_make_provider())


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "source": service.provider.name}


@app.get("/api/rating/{ticker}", response_model=Rating)
def get_rating(ticker: str) -> Rating:
    symbol = parse_ticker(ticker)
    if symbol is None:
        raise HTTPException(status_code=400, detail=f"{ticker.strip()!r} is not a valid ticker symbol")
    try:
        return service.get(symbol)
    except TickerNotFound:
        raise HTTPException(status_code=404, detail=f"No data found for {symbol}")
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@app.get("/api/ratings", response_model=list[Rating])
def get_ratings(tickers: str = Query(..., description="Comma-separated tickers, e.g. AAPL,MSFT")) -> list[Rating]:
    """Batch endpoint for the watchlist, in request order.

    Invalid, unknown and failing tickers are skipped so one bad entry
    doesn't blank out the whole watchlist.
    """
    parsed = (parse_ticker(t) for t in tickers.split(","))
    symbols = list(dict.fromkeys(s for s in parsed if s))
    if len(symbols) > MAX_BATCH:
        raise HTTPException(status_code=400, detail=f"At most {MAX_BATCH} tickers per request")

    def fetch(symbol: str) -> Rating | None:
        try:
            return service.get(symbol)
        except (TickerNotFound, ProviderError):
            return None

    with ThreadPoolExecutor(max_workers=BATCH_WORKERS) as pool:
        results = list(pool.map(fetch, symbols))
    return [r for r in results if r is not None]
