"""Replays recorded Yahoo Finance responses (app/data/recorded).

Used by the offline demo mode (DATA_SOURCE=sample) and the tests, so both
exercise exactly the same parsing and scoring code as live data. The files
are real responses captured by scripts/capture_fixtures.py.
"""

from __future__ import annotations

import gzip
import json
from functools import lru_cache
from pathlib import Path

from . import yahoo

DIR = Path(__file__).resolve().parents[1] / "data" / "recorded"


@lru_cache(maxsize=None)
def load(name: str) -> dict | None:
    path = DIR / f"{name}.json.gz"
    if not path.is_file():
        return None
    return json.loads(gzip.decompress(path.read_bytes()))


def available(prefix: str) -> list[str]:
    """Recorded names with a prefix, e.g. available("chart_") -> ["AAPL", ...]."""
    return sorted(p.name[len(prefix):-len(".json.gz")] for p in DIR.glob(f"{prefix}*.json.gz"))


class RecordedClient(yahoo.Client):
    """A yahoo.Client whose network is the recorded files."""

    def __init__(self):
        super().__init__(session=object())  # never used: _get is replaced below

    def _get(self, path: str, params: dict) -> dict:
        if path.startswith("/v8/finance/chart/"):
            symbol = path.rsplit("/", 1)[1]
            if params.get("interval") == "5m":
                data = load(f"chart_{symbol}_prepost")
            else:
                data = load(f"chart_{symbol}")
            if data is None:
                raise yahoo.YahooNotFound(f"no recording for {symbol}")
            return data
        if path.startswith("/ws/fundamentals-timeseries/"):
            symbol = path.rsplit("/", 1)[1]
            wanted = set(str(params.get("type", "")).split(","))
            data = load(f"timeseries_{symbol}") or {"timeseries": {"result": []}}
            # Return only the requested types, as Yahoo does.
            result = [r for r in data["timeseries"]["result"]
                      if set((r.get("meta") or {}).get("type") or []) & wanted]
            return {"timeseries": {"result": result, "error": None}}
        if path == "/v1/finance/search":
            if int(params.get("newsCount") or 0) > 0:
                return load(f"news_{params.get('q', '')}") or {"news": []}
            return self._search(str(params.get("q", "")))
        if path == yahoo.SCREENER_URL:
            data = load("screener_crypto") or {"finance": {"result": [{"quotes": [], "total": 0}]}}
            if int(params.get("start", 0)) > 0:  # only the first page was recorded
                return {"finance": {"result": [{"quotes": [], "total": 0}]}}
            return data
        raise yahoo.YahooError(f"nothing recorded for {path}")

    @staticmethod
    def _search(query: str) -> dict:
        exact = load(f"search_{query}") or load(f"search_{query.lower()}") or load(f"search_{query.upper()}")
        if exact:
            return exact
        # Otherwise match the query against every recorded search result.
        q = query.strip().lower()
        seen, quotes = set(), []
        for name in available("search_"):
            for item in (load(f"search_{name}") or {}).get("quotes", []):
                text = f"{item.get('symbol', '')} {item.get('longname', '')} {item.get('shortname', '')}".lower()
                if q and q in text and item.get("symbol") not in seen:
                    seen.add(item.get("symbol"))
                    quotes.append(item)
        return {"quotes": quotes}
