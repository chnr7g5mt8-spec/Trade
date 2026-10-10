"""Build industry and sector peer benchmarks from real Yahoo Finance data.

For every Yahoo industry, takes the largest US-listed companies (which include
many foreign companies' US listings), computes each relative metric with the
very same code the app uses to rate a stock, and stores quantiles per
industry and per sector in app/data/benchmarks.json.

Runs on GitHub Actions (see .github/workflows/benchmarks.yml).
Usage: python scripts/build_benchmarks.py [--per-industry 50] [--limit-industries N]
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.benchmarks import QUANTILES, norm  # noqa: E402
from app.models import StockData  # noqa: E402
from app.providers.stocks import TIMESERIES_TYPES, StockProvider, build_stock  # noqa: E402
from app.scoring.stock import CATEGORIES  # noqa: E402
from app.sources import yahoo  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "app" / "data" / "benchmarks.json"
US_EXCHANGES = ["NMS", "NYQ", "NGM", "NCM", "ASE"]
MIN_MARKET_CAP = 300_000_000
RELATIVE_SPECS = [m for c in CATEGORIES for m in c.metrics if m.relative]

log = logging.getLogger("benchmarks")


def quantiles(values: list[float]) -> list[list[float]]:
    """Linear-interpolated quantiles, as numpy.percentile(method='linear')."""
    xs = sorted(values)
    out = []
    for q in QUANTILES:
        pos = q * (len(xs) - 1)
        lo = int(pos)
        hi = min(lo + 1, len(xs) - 1)
        out.append([q, round(xs[lo] + (xs[hi] - xs[lo]) * (pos - lo), 6)])
    return out


def usable(spec, value: float | None) -> bool:
    # Values a special rule scores directly (e.g. a negative P/E = losses) say
    # nothing about what's normal for the industry, so they're left out.
    return value is not None and (spec.special is None or spec.special(value) is None)


def group_stats(name: str, level: str, companies: list[StockData]) -> dict:
    metrics = {}
    for spec in RELATIVE_SPECS:
        values = [getattr(c, spec.key) for c in companies]
        values = [v for v in values if usable(spec, v)]
        if len(values) >= 3:
            metrics[spec.key] = {"count": len(values), "q": quantiles(values)}
    return {"name": name, "level": level, "companies": len(companies), "metrics": metrics}


def compute_groups(records: list[tuple[str, str, StockData]]) -> dict[str, dict]:
    """records: (sector, industry, data) -> benchmark groups keyed like app.benchmarks expects."""
    by_industry: dict[str, tuple[str, list[StockData]]] = {}
    by_sector: dict[str, tuple[str, list[StockData]]] = {}
    for sector, industry, data in records:
        by_industry.setdefault(norm(industry), (industry, []))[1].append(data)
        by_sector.setdefault(norm(sector), (sector, []))[1].append(data)
    groups = {}
    for key, (name, items) in by_industry.items():
        groups["industry:" + key] = group_stats(name, "industry", items)
    for key, (name, items) in by_sector.items():
        groups["sector:" + key] = group_stats(name, "sector", items)
    return groups


def industry_universe(sector: str, industry: str, per_industry: int) -> list[str]:
    import yfinance as yf
    from yfinance import EquityQuery

    query = EquityQuery("and", [
        EquityQuery("eq", ["industry", industry]),
        EquityQuery("is-in", ["exchange", *US_EXCHANGES]),
        EquityQuery("gt", ["intradaymarketcap", MIN_MARKET_CAP]),
    ])
    for attempt in range(4):
        try:
            result = yf.screen(query, size=per_industry, sortField="intradaymarketcap", sortAsc=False)
            return [q["symbol"] for q in result.get("quotes", []) if q.get("quoteType") == "EQUITY"]
        except Exception as exc:  # yfinance raises several types for throttling
            wait = 30 * 2 ** attempt
            log.warning("screen %s failed (%s); retrying in %ss", industry, exc, wait)
            time.sleep(wait)
    return []


def fetch_company(provider: StockProvider, symbol: str, sector: str, industry: str) -> StockData | None:
    for attempt in range(4):
        try:
            chart = provider.client.chart(symbol, "2y")
            ts = provider.client.timeseries(symbol, TIMESERIES_TYPES)
            return build_stock(symbol, chart, ts, profile={"sector": sector, "industry": industry}, fx=provider.fx)
        except yahoo.YahooNotFound:
            return None
        except yahoo.YahooRateLimited:
            wait = 30 * 2 ** attempt
            log.warning("rate limited on %s; waiting %ss", symbol, wait)
            time.sleep(wait)
        except yahoo.YahooError as exc:
            log.warning("%s failed: %s", symbol, exc)
            return None
    return None


def main() -> None:
    from yfinance.const import EQUITY_SCREENER_EQ_MAP

    parser = argparse.ArgumentParser()
    parser.add_argument("--per-industry", type=int, default=50)
    parser.add_argument("--limit-industries", type=int, default=0, help="for quick test runs")
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    pairs = [(sector, industry) for sector, industries in EQUITY_SCREENER_EQ_MAP["industry"].items()
             for industry in industries]
    if args.limit_industries:
        pairs = pairs[:args.limit_industries]
    log.info("%d industries", len(pairs))

    provider = StockProvider()
    records: list[tuple[str, str, StockData]] = []
    seen: set[str] = set()
    for i, (sector, industry) in enumerate(pairs, 1):
        symbols = [s for s in industry_universe(sector, industry, args.per_industry) if s not in seen]
        seen.update(symbols)
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            results = list(pool.map(lambda s: fetch_company(provider, s, sector, industry), symbols))
        got = [r for r in results if r is not None and r.asset_type == "stock"]
        records.extend((sector, industry, r) for r in got)
        log.info("[%d/%d] %s / %s: %d of %d companies", i, len(pairs), sector, industry, len(got), len(symbols))

    groups = compute_groups(records)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "generated_at": datetime.now(tz=timezone.utc).date().isoformat(),
        "universe": f"Up to {args.per_industry} largest US-listed companies per Yahoo industry "
                    f"(market cap over ${MIN_MARKET_CAP / 1e6:.0f}M)",
        "companies": len(records),
        "groups": groups,
    }, indent=1, sort_keys=True))
    log.info("wrote %s: %d companies, %d groups", OUT, len(records), len(groups))
    if len(records) < 500 and not args.limit_industries:
        sys.exit(f"only {len(records)} companies fetched; refusing to publish thin benchmarks")


if __name__ == "__main__":
    main()
