"""Checks which upstream data services are reachable from this server.

Yahoo treats cloud hosts differently, so the only way to know what works
from a given host is to try each service from it. Results are cached so the
endpoint can't be used to hammer Yahoo.
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from .sources import yahoo

CACHE_SECONDS = 300
_lock = threading.Lock()
_cached: tuple[float, dict] | None = None


def _check(fn: Callable[[], str]) -> dict:
    start = time.monotonic()
    try:
        detail = fn()
        ok = True
    except Exception as exc:  # report every failure mode, it's a diagnostic
        detail = f"{type(exc).__name__}: {exc}"[:300]
        ok = False
    return {"ok": ok, "detail": detail, "seconds": round(time.monotonic() - start, 2)}


def _chart() -> str:
    c = yahoo.Client().chart("AAPL", "5d")
    if not c.closes:
        raise RuntimeError("empty price history")
    return f"{len(c.closes)} closes, price {c.meta.get('regularMarketPrice')}"


def _timeseries() -> str:
    ts = yahoo.Client().timeseries("KO", ["annualTotalRevenue", "trailingPeRatio"])
    if not ts:
        raise RuntimeError("no statement data")
    return ", ".join(f"{k}: {len(v)} points" for k, v in ts.items())


def _search() -> str:
    quotes = yahoo.Client().search("toyota", 5)
    if not quotes:
        raise RuntimeError("no search results")
    q = quotes[0]
    return f"{len(quotes)} results; first: {q.get('symbol')} industry={q.get('industry')}"


def _crypto_screener() -> str:
    quotes, total = yahoo.Client().screener("all_cryptocurrencies_us", 5)
    if not quotes:
        raise RuntimeError("no crypto listings")
    return f"{total} coins listed; first: {quotes[0].get('symbol')}"


def _quote_summary() -> str:
    # Not used by the app (it needs a crumb some hosts are refused); reported for reference.
    import yfinance as yf

    info = yf.Ticker("MSFT").info or {}
    if not info.get("shortName"):
        raise RuntimeError(f"no company data ({len(info)} keys)")
    return f"{len(info)} keys"


CHECKS: dict[str, Callable[[], str]] = {
    "yahoo_chart": _chart,
    "yahoo_statements": _timeseries,
    "yahoo_search": _search,
    "yahoo_crypto_screener": _crypto_screener,
    "yahoo_quote_summary_unused": _quote_summary,
}


def run() -> dict:
    global _cached
    with _lock:
        if _cached and time.monotonic() - _cached[0] < CACHE_SECONDS:
            return _cached[1]
    with ThreadPoolExecutor(max_workers=5) as pool:
        results = dict(zip(CHECKS, pool.map(_check, CHECKS.values())))
    report = {"checked_at": int(time.time()), "checks": results}
    with _lock:
        _cached = (time.monotonic(), report)
    return report
