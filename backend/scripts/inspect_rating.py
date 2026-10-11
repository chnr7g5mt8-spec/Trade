"""Print the full rating breakdown for tickers, from live Yahoo data.

Runs on GitHub Actions (.github/workflows/inspect.yml), which can reach Yahoo.
Usage: python scripts/inspect_rating.py ENB ENB.TO
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.main import RatingService  # noqa: E402
from app.providers.market import MarketData  # noqa: E402


def main() -> None:
    service = RatingService(MarketData())
    if sys.argv[1:2] == ["--news-json"]:
        # Raw Yahoo news responses, e.g. to record demo data.
        import json

        for ticker in sys.argv[2:]:
            body = service.market.client._get("/v1/finance/search", {
                "q": ticker, "quotesCount": 0, "newsCount": 12, "listsCount": 0, "enableFuzzyQuery": "false"})
            print(f"NEWS {ticker} " + json.dumps({"news": body.get("news") or []}))
        return
    for ticker in sys.argv[1:]:
        r = service.get(ticker.upper())
        print(f"\n=== {r.ticker} {r.name} ({r.exchange}, {r.currency}) price {r.price}")
        print(f"score {r.score} {r.label}; industry {r.industry}; peers {r.peer_group}")
        for c in r.categories:
            print(f"  {c.label}: {c.score}")
            for m in c.metrics:
                print(f"    {m.label}: {m.display} -> {m.score}  {m.benchmark or ''}")
        for f in r.facts:
            print(f"  fact {f.label}: {f.value}")
        for n in r.notes:
            print(f"  note: {n}")
        data = service.market.stocks.chart(r.ticker)
        print("  dividends (last 12):", [(round(t / 86400 / 365.25 + 1970, 2), round(a, 4))
                                         for t, a in data.dividends[-12:]])


if __name__ == "__main__":
    main()
