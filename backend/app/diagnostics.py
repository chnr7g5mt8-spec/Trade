"""Checks which upstream data services are reachable from this server.

Yahoo Finance and CoinGecko treat cloud hosts differently, so the only way to
know what works from a given host is to try each service from it. Results are
cached so the endpoint can't be used to hammer the upstreams.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

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


def _yahoo_chart() -> str:
    import yfinance as yf

    t = yf.Ticker("AAPL")
    h = t.history(period="5d")
    if h.empty:
        raise RuntimeError("empty price history")
    meta = t.history_metadata or {}
    return f"{len(h)} rows; meta keys: {sorted(meta)[:40]}"


def _yahoo_info() -> str:
    import yfinance as yf

    info = yf.Ticker("MSFT").info or {}
    if not info.get("shortName"):
        raise RuntimeError(f"no company data ({len(info)} keys: {sorted(info)[:10]})")
    return f"{len(info)} keys"


def _yahoo_statements() -> str:
    import yfinance as yf

    inc = yf.Ticker("KO").income_stmt
    if inc is None or inc.empty:
        raise RuntimeError("empty income statement")
    return f"{inc.shape[1]} years, {inc.shape[0]} rows"


def _yahoo_quarterly() -> str:
    import yfinance as yf

    t = yf.Ticker("KO")
    q = t.quarterly_income_stmt
    cf = t.ttm_cashflow
    if q is None or q.empty:
        raise RuntimeError("empty quarterly income statement")
    return f"{q.shape[1]} quarters; ttm cashflow rows: {0 if cf is None else cf.shape[0]}"


def _yahoo_search() -> str:
    import yfinance as yf

    s = yf.Search("toyota", max_results=5, news_count=0, lists_count=0)
    if not s.quotes:
        raise RuntimeError("no search results")
    q = s.quotes[0]
    return f"{len(s.quotes)} results; first: {q.get('symbol')} sector={q.get('sector')} industry={q.get('industry')}"


def _yahoo_screener() -> str:
    import yfinance as yf

    r = yf.screen("most_actives", count=5)
    quotes = r.get("quotes", [])
    if not quotes:
        raise RuntimeError("no screener results")
    return f"{len(quotes)} results"


def _get_json(url: str):
    req = urllib.request.Request(url, headers={"accept": "application/json", "user-agent": "stock-rater"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())


def _coingecko_markets() -> str:
    data = _get_json("https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&ids=bitcoin")
    return f"bitcoin ${data[0]['current_price']}"


def _coingecko_chart() -> str:
    data = _get_json("https://api.coingecko.com/api/v3/coins/bitcoin/market_chart?vs_currency=usd&days=30&interval=daily")
    return f"{len(data['prices'])} points"


CHECKS: dict[str, Callable[[], str]] = {
    "yahoo_chart": _yahoo_chart,
    "yahoo_info": _yahoo_info,
    "yahoo_statements": _yahoo_statements,
    "yahoo_quarterly_ttm": _yahoo_quarterly,
    "yahoo_search": _yahoo_search,
    "yahoo_screener": _yahoo_screener,
    "coingecko_markets": _coingecko_markets,
    "coingecko_chart": _coingecko_chart,
}


def run() -> dict:
    global _cached
    with _lock:
        if _cached and time.monotonic() - _cached[0] < CACHE_SECONDS:
            return _cached[1]
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = dict(zip(CHECKS, pool.map(_check, CHECKS.values())))
    report = {"checked_at": int(time.time()), "checks": results}
    with _lock:
        _cached = (time.monotonic(), report)
    return report
