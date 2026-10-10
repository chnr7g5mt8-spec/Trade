"""HTTP API consumed by the mobile app.

Run:  uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
Set DATA_SOURCE=sample to use bundled demo data instead of Yahoo Finance.
"""

from __future__ import annotations

import os
import re
import threading
import time

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from .models import Rating
from .providers import Provider, ProviderError, SampleProvider, TickerNotFound, YahooProvider
from .scoring import rate

TICKER_RE = re.compile(r"^[A-Z0-9][A-Z0-9.\-^=]{0,14}$")
CACHE_TTL_SECONDS = 15 * 60
MAX_BATCH = 25


def _make_provider() -> Provider:
    return SampleProvider() if os.getenv("DATA_SOURCE", "yahoo").lower() == "sample" else YahooProvider()


class RatingService:
    def __init__(self, provider: Provider, ttl: float = CACHE_TTL_SECONDS):
        self.provider = provider
        self.ttl = ttl
        self._cache: dict[str, tuple[float, Rating]] = {}
        self._lock = threading.Lock()

    def get(self, ticker: str) -> Rating:
        now = time.monotonic()
        with self._lock:
            hit = self._cache.get(ticker)
            if hit and now - hit[0] < self.ttl:
                return hit[1]
        rating = rate(self.provider.fetch(ticker), source=self.provider.name)
        with self._lock:
            self._cache[ticker] = (now, rating)
        return rating


def normalize_ticker(raw: str) -> str:
    ticker = raw.strip().upper()
    if not TICKER_RE.match(ticker):
        raise HTTPException(status_code=400, detail=f"Invalid ticker: {raw!r}")
    return ticker


app = FastAPI(title="Stock Rating API", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET"], allow_headers=["*"])
service = RatingService(_make_provider())


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "source": service.provider.name}


@app.get("/api/rating/{ticker}", response_model=Rating)
def get_rating(ticker: str) -> Rating:
    symbol = normalize_ticker(ticker)
    try:
        return service.get(symbol)
    except TickerNotFound:
        raise HTTPException(status_code=404, detail=f"No data found for {symbol}")
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@app.get("/api/ratings", response_model=list[Rating])
def get_ratings(tickers: str = Query(..., description="Comma-separated tickers, e.g. AAPL,MSFT")) -> list[Rating]:
    """Batch endpoint for the watchlist. Tickers that fail are skipped."""
    symbols = list(dict.fromkeys(normalize_ticker(t) for t in tickers.split(",") if t.strip()))
    if len(symbols) > MAX_BATCH:
        raise HTTPException(status_code=400, detail=f"At most {MAX_BATCH} tickers per request")
    results = []
    for symbol in symbols:
        try:
            results.append(service.get(symbol))
        except (TickerNotFound, ProviderError):
            continue
    return results


@app.get("/api/sample-tickers")
def sample_tickers() -> list[str]:
    return SampleProvider.tickers()
