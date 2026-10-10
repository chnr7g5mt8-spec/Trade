"""HTTP API consumed by the mobile app.

Run:  uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
Set DATA_SOURCE=sample to replay recorded market data instead of calling Yahoo.
Set WEB_DIR to a web export of the mobile app (`npx expo export --platform web`)
to serve the app itself from the same server, as the Docker image does.
"""

from __future__ import annotations

import os
import re
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from . import benchmarks as benchmarks_module
from . import explore, methodology
from .models import Rating, SearchResult
from .providers import NotSupported, ProviderError, TickerNotFound
from .providers.market import MarketData
from .ratings import to_rating

TICKER_RE = re.compile(r"^[A-Z0-9^][A-Z0-9.\-^=]{0,19}$")
CACHE_TTL_SECONDS = 15 * 60
# While a market is trading (incl. pre-market, after hours, and crypto all the
# time) prices move, so ratings are refreshed much sooner.
LIVE_CACHE_TTL_SECONDS = 60
LIVE_MARKET_STATES = {"open", "pre", "post"}
CACHE_MAX_ENTRIES = 500
MAX_BATCH = 25
BATCH_WORKERS = 6


def _make_market():
    if os.getenv("DATA_SOURCE", "yahoo").lower() == "sample":
        from .sources.recorded import RecordedClient

        market = MarketData(RecordedClient())
        market.name = "sample"
        return market
    return MarketData()


class RatingService:
    """Rates tickers through a market data provider, caching results.

    Results are kept for `live_ttl` seconds while the asset's market is
    trading and for `ttl` seconds otherwise.
    """

    def __init__(self, market, ttl: float = CACHE_TTL_SECONDS, live_ttl: float = LIVE_CACHE_TTL_SECONDS,
                 max_entries: int = CACHE_MAX_ENTRIES, benchmarks=None):
        self.market = market
        self.ttl = ttl
        self.live_ttl = live_ttl
        self.max_entries = max_entries
        self.benchmarks = benchmarks if benchmarks is not None else benchmarks_module.load()
        self._cache: OrderedDict[str, tuple[float, Rating]] = OrderedDict()  # ticker -> (expires_at, rating)
        self._lock = threading.Lock()

    @property
    def source(self) -> str:
        return self.market.name

    def get(self, ticker: str) -> Rating:
        with self._lock:
            hit = self._cache.get(ticker)
            if hit and time.monotonic() < hit[0]:
                self._cache.move_to_end(ticker)
                return hit[1]
        rating = to_rating(self.market.fetch(ticker), self.source, self.benchmarks)
        ttl = self.live_ttl if rating.market_state in LIVE_MARKET_STATES else self.ttl
        with self._lock:
            self._cache[ticker] = (time.monotonic() + ttl, rating)
            self._cache.move_to_end(ticker)
            while len(self._cache) > self.max_entries:
                self._cache.popitem(last=False)
        return rating


def parse_ticker(raw: str) -> str | None:
    ticker = raw.strip().upper()
    return ticker if TICKER_RE.match(ticker) else None


app = FastAPI(title="Stock Rating API", version="2.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET"], allow_headers=["*"])
service = RatingService(_make_market())


@app.middleware("http")
async def no_store_api_responses(request: Request, call_next):
    # Prices must never be served from a browser or CDN cache.
    response = await call_next(request)
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "source": service.source}


@app.get("/api/diagnostics")
def diagnostics() -> dict:
    """Which upstream data services work from this server (cached for 5 minutes)."""
    from . import diagnostics as diag

    return diag.run()


@app.get("/api/search", response_model=list[SearchResult])
def search(q: str = Query(..., min_length=1, max_length=60)) -> list[SearchResult]:
    """Stocks, funds and cryptocurrencies matching a name or symbol, worldwide."""
    try:
        return service.market.search(q)
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@app.get("/api/rating/{ticker}", response_model=Rating)
def get_rating(ticker: str) -> Rating:
    symbol = parse_ticker(ticker)
    if symbol is None:
        raise HTTPException(status_code=400, detail=f"{ticker.strip()!r} is not a valid ticker symbol")
    try:
        return service.get(symbol)
    except TickerNotFound:
        raise HTTPException(status_code=404, detail=f"No data found for {symbol}")
    except NotSupported as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@app.get("/api/ratings", response_model=list[Rating])
def get_ratings(tickers: str = Query(..., description="Comma-separated tickers, e.g. AAPL,BTC-USD")) -> list[Rating]:
    """Batch endpoint for the watchlist, in request order.

    Invalid, unknown and failing tickers are skipped so one bad entry
    doesn't blank out the whole watchlist. If nothing could be fetched
    because the data source is failing, that is reported as an error.
    """
    parsed = (parse_ticker(t) for t in tickers.split(","))
    symbols = list(dict.fromkeys(s for s in parsed if s))
    if len(symbols) > MAX_BATCH:
        raise HTTPException(status_code=400, detail=f"At most {MAX_BATCH} tickers per request")

    def fetch(symbol: str) -> Rating | ProviderError | None:
        try:
            return service.get(symbol)
        except (TickerNotFound, NotSupported):
            return None
        except ProviderError as exc:
            return exc

    with ThreadPoolExecutor(max_workers=BATCH_WORKERS) as pool:
        results = list(pool.map(fetch, symbols))
    ratings = [r for r in results if isinstance(r, Rating)]
    failures = [r for r in results if isinstance(r, ProviderError)]
    if failures and not ratings:
        raise HTTPException(status_code=502, detail=str(failures[0]))
    return ratings


@app.get("/api/methodology")
def get_methodology() -> dict:
    """How ratings are computed, and how well they have done historically."""
    return methodology.describe(service.benchmarks)


_sample_explore: dict | None = None


def sample_explore() -> dict:
    """Explore lists for the demo mode, built from the recorded assets."""
    global _sample_explore
    if _sample_explore is None:
        from .sources import recorded

        tickers = sorted(set(recorded.available("chart_")) & set(recorded.available("search_")))
        ratings = [service.get(t) for t in tickers]
        _sample_explore = {
            "generated_at": None,
            "universe": "Recorded sample data only",
            "stocks_rated": sum(r.asset_type == "stock" and r.score is not None for r in ratings),
            "coins_rated": sum(r.asset_type == "crypto" and r.score is not None for r in ratings),
            "lists": explore.build(ratings),
        }
    return _sample_explore


@app.get("/api/explore")
def get_explore() -> dict:
    """The best-rated stocks and coins per category, ranked once a day."""
    data = sample_explore() if service.source == "sample" else explore.load()
    if data is None:
        raise HTTPException(status_code=503, detail="The Explore rankings are being prepared. Check back later today.")
    return data


def mount_web_app(web_dir: str) -> None:
    """Serve the exported web app, falling back to index.html for app routes.

    Registered last so /api and /health always take precedence.
    """
    root = Path(web_dir).resolve()
    index = root / "index.html"
    if not index.is_file():
        raise RuntimeError(f"WEB_DIR={web_dir!r} has no index.html; run `npx expo export --platform web` first")

    @app.get("/{path:path}", include_in_schema=False)
    def web_app(path: str) -> FileResponse:
        if path == "api" or path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not found")
        candidate = (root / path).resolve()
        if path and candidate.is_relative_to(root) and candidate.is_file():
            return FileResponse(candidate)
        # Client-side route such as /stock/AAPL: let the app's router handle it.
        return FileResponse(index, headers={"Cache-Control": "no-cache"})


if os.getenv("WEB_DIR"):
    mount_web_app(os.environ["WEB_DIR"])
