"""Minimal Yahoo Finance client using only endpoints that need no session crumb.

Yahoo's quote-summary service (yfinance's `.info`) requires a "crumb" that
Yahoo refuses to hand out to some cloud hosts, which leaves `.info` empty.
These three endpoints work without one:

- chart:      prices, dividends, currency, exchange, trading hours
- timeseries: financial statements and Yahoo's own valuation ratios
- search:     names, sector and industry
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from ..stats import epoch, num

log = logging.getLogger(__name__)

BASE = "https://query2.finance.yahoo.com"
SCREENER_URL = "https://query1.finance.yahoo.com/v1/finance/screener/predefined/saved"
TIMEOUT = 20


class YahooError(Exception):
    """Yahoo could not be reached or returned an error."""


class YahooNotFound(YahooError):
    """Yahoo has no such symbol."""


class YahooRateLimited(YahooError):
    """Yahoo is throttling this server."""


@dataclass
class Chart:
    symbol: str
    meta: dict
    timestamps: list[int]
    closes: list[float]  # dividend-adjusted closes, aligned with timestamps; gaps removed
    raw_closes: list[float] = field(default_factory=list)  # actual traded closes, same alignment
    dividends: list[tuple[int, float]] = field(default_factory=list)  # (unix seconds, amount per share)

    @property
    def currency(self) -> str | None:
        return self.meta.get("currency")


@dataclass(frozen=True)
class Point:
    as_of: str  # ISO date the figure relates to (period end, or day for valuation ratios)
    value: float
    currency: str | None
    period: str | None  # "12M", "3M", "TTM"...


class Client:
    def __init__(self, session=None):
        if session is None:
            from curl_cffi import requests as curl_requests

            # Browser-like TLS fingerprint, as yfinance uses; plain clients get blocked more often.
            session = curl_requests.Session(impersonate="chrome")
        self._session = session

    def _get(self, path: str, params: dict) -> dict:
        """GET a path under BASE (or a full URL) and return the decoded JSON."""
        url = path if path.startswith("https://") else BASE + path
        try:
            r = self._session.get(url, params=params, timeout=TIMEOUT)
        except Exception as exc:
            raise YahooError(f"network error: {exc}") from exc
        if r.status_code == 429:
            raise YahooRateLimited("rate limited (HTTP 429)")
        if r.status_code == 404:
            raise YahooNotFound(path)
        try:
            data = r.json()
        except Exception as exc:
            raise YahooError(f"HTTP {r.status_code}: not JSON") from exc
        if r.status_code >= 400:
            # Chart reports unknown symbols as 404 with an error body; others vary.
            desc = str(_error_description(data) or f"HTTP {r.status_code}")
            if "No data found" in desc or "delisted" in desc or "Not Found" in desc:
                raise YahooNotFound(desc)
            raise YahooError(desc)
        return data

    # --- chart -----------------------------------------------------------------
    def chart(self, symbol: str, range_: str = "10y", interval: str = "1d", prepost: bool = False) -> Chart:
        data = self._get(f"/v8/finance/chart/{symbol}", {
            "range": range_, "interval": interval, "includePrePost": str(prepost).lower(),
            "events": "div,split", "includeAdjustedClose": "true",
        })
        results = (data.get("chart") or {}).get("result") or []
        if not results:
            desc = _error_description(data)
            raise YahooNotFound(desc or symbol)
        return parse_chart(symbol, results[0])

    # --- fundamentals timeseries ------------------------------------------------
    def timeseries(self, symbol: str, types: list[str], years: int = 6) -> dict[str, list[Point]]:
        """Fetch several series at once, e.g. ["annualTotalRevenue", "trailingPeRatio"]."""
        now = int(time.time())
        out: dict[str, list[Point]] = {}
        # Keep each URL comfortably short; some networks drop very long URLs.
        for i in range(0, len(types), 40):
            chunk = types[i:i + 40]
            data = self._get(f"/ws/fundamentals-timeseries/v1/finance/timeseries/{symbol}", {
                "symbol": symbol, "type": ",".join(chunk),
                "period1": now - years * 366 * 86400, "period2": now + 86400,
            })
            out.update(parse_timeseries(data))
        return out

    # --- predefined screeners (e.g. "all_cryptocurrencies_us") -----------------
    def screener(self, scr_id: str, count: int = 250, start: int = 0) -> tuple[list[dict], int]:
        """One page of a Yahoo predefined screener; returns (quotes, total available)."""
        data = self._get(SCREENER_URL, {"scrIds": scr_id, "count": count, "start": start, "formatted": "false"})
        result = ((data.get("finance") or {}).get("result") or [{}])[0] or {}
        return [q for q in result.get("quotes") or [] if isinstance(q, dict)], int(result.get("total") or 0)

    # --- search -----------------------------------------------------------------
    def search(self, query: str, count: int = 10) -> list[dict]:
        data = self._get("/v1/finance/search", {
            "q": query, "quotesCount": count, "newsCount": 0, "listsCount": 0,
            "enableFuzzyQuery": "false", "quotesQueryId": "tss_match_phrase_query",
        })
        return [q for q in data.get("quotes") or [] if isinstance(q, dict) and q.get("symbol")]


    def news(self, query: str, count: int = 10) -> list[dict]:
        """Recent news stories Yahoo links to a symbol or name."""
        data = self._get("/v1/finance/search", {
            "q": query, "quotesCount": 0, "newsCount": count, "listsCount": 0, "enableFuzzyQuery": "false",
        })
        return [n for n in data.get("news") or [] if isinstance(n, dict) and n.get("title") and n.get("link")]


def _error_description(data: object) -> str | None:
    if not isinstance(data, dict):
        return None
    for key in ("chart", "finance", "timeseries"):
        err = (data.get(key) or {}).get("error") if isinstance(data.get(key), dict) else None
        if err:
            return err.get("description") or err.get("code")
    return None


def parse_chart(symbol: str, result: dict) -> Chart:
    meta = result.get("meta") or {}
    stamps = result.get("timestamp") or []
    indicators = result.get("indicators") or {}
    adj = ((indicators.get("adjclose") or [{}])[0] or {}).get("adjclose")
    raw = ((indicators.get("quote") or [{}])[0] or {}).get("close")
    series = adj if adj and any(v is not None for v in adj) else raw or []
    raw = raw or series
    timestamps, closes, raw_closes = [], [], []
    for t, c, r in zip(stamps, series, raw):
        c, r = num(c), num(r)
        if c is not None and c > 0 and t:
            timestamps.append(int(t))
            closes.append(c)
            raw_closes.append(r if r is not None and r > 0 else c)
    divs = ((result.get("events") or {}).get("dividends") or {}).values()
    dividends = sorted((int(d["date"]), float(d["amount"])) for d in divs
                       if isinstance(d, dict) and num(d.get("amount")) and epoch(d.get("date")))
    return Chart(symbol=meta.get("symbol") or symbol, meta=meta, timestamps=timestamps, closes=closes,
                 raw_closes=raw_closes, dividends=dividends)


def parse_timeseries(data: dict) -> dict[str, list[Point]]:
    out: dict[str, list[Point]] = {}
    for item in ((data.get("timeseries") or {}).get("result") or []):
        if not isinstance(item, dict):
            continue
        types = (item.get("meta") or {}).get("type") or []
        for t in types:
            points = []
            for x in item.get(t) or []:
                if not isinstance(x, dict):
                    continue
                value = num((x.get("reportedValue") or {}).get("raw"))
                if value is None or not x.get("asOfDate"):
                    continue
                points.append(Point(as_of=x["asOfDate"], value=value, currency=x.get("currencyCode"),
                                    period=x.get("periodType")))
            if points:
                out[t] = sorted(points, key=lambda p: p.as_of)
    return out


def market_state(meta: dict, now: float | None = None) -> str | None:
    """"open", "pre", "post" or "closed" from the chart's current trading periods."""
    periods = meta.get("currentTradingPeriod") or {}
    now = time.time() if now is None else now
    for name, state in (("regular", "open"), ("pre", "pre"), ("post", "post")):
        p = periods.get(name) or {}
        start, end = epoch(p.get("start")), epoch(p.get("end"))
        if start and end and start <= now < end:
            return state
    return "closed" if periods else None


def iso_date(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat()
