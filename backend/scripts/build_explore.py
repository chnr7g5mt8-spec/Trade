"""Rank stocks and coins for the app's Explore page.

Rates every US-listed company worth over $1B (which includes many foreign
companies' US listings) and the largest coins with exactly the code the app
uses for a single rating, then stores the top 20 per category in
app/data/explore.json (see app/explore.py for the lists).

Runs on GitHub Actions each weekday after the US close (.github/workflows/explore.yml).
Usage: python scripts/build_explore.py [--limit-industries N] [--coins 250]
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

from app import benchmarks as benchmarks_module  # noqa: E402
from app import explore  # noqa: E402
from app import outlook  # noqa: E402
from app.models import Rating  # noqa: E402
from app.providers.crypto import CryptoDirectory, build_crypto  # noqa: E402
from app.providers.stocks import TIMESERIES_TYPES, StockProvider, build_stock  # noqa: E402
from app.ratings import to_rating  # noqa: E402
from app.sources import yahoo  # noqa: E402
from build_benchmarks import US_EXCHANGES  # noqa: E402

OUT = explore.DEFAULT_PATH
MIN_STOCK_MARKET_CAP = 1_000_000_000
MIN_COIN_MARKET_CAP = 100_000_000
PER_INDUSTRY = 250  # Yahoo's largest page; no industry has more US companies over $1B

log = logging.getLogger("explore")


def industry_companies(industry: str) -> list[dict]:
    """Screener rows (symbol, names, market cap) for an industry's US-listed companies over $1B."""
    import yfinance as yf
    from yfinance import EquityQuery

    query = EquityQuery("and", [
        EquityQuery("eq", ["industry", industry]),
        EquityQuery("is-in", ["exchange", *US_EXCHANGES]),
        EquityQuery("gt", ["intradaymarketcap", MIN_STOCK_MARKET_CAP]),
    ])
    for attempt in range(5):
        try:
            result = yf.screen(query, size=PER_INDUSTRY, sortField="intradaymarketcap", sortAsc=False)
            return [q for q in result.get("quotes", []) if q.get("quoteType") == "EQUITY" and q.get("symbol")]
        except Exception as exc:  # yfinance raises several types for timeouts and throttling
            if attempt == 4:
                raise
            wait = 20 * 2 ** attempt
            log.warning("screen %s failed (%s); retrying in %ss", industry, exc, wait)
            time.sleep(wait)
    return []


def with_retries(label: str, fn):
    for attempt in range(4):
        try:
            return fn()
        except yahoo.YahooNotFound:
            return None
        except yahoo.YahooRateLimited:
            wait = 30 * 2 ** attempt
            log.warning("rate limited on %s; waiting %ss", label, wait)
            time.sleep(wait)
        except yahoo.YahooError as exc:
            if attempt == 3:
                log.warning("%s failed: %s", label, exc)
                return None
            time.sleep(5)
    return None


def rate_stock(provider: StockProvider, benchmarks, row: dict, sector: str, industry: str) -> Rating | None:
    symbol = row["symbol"]

    def fetch() -> Rating:
        # The same inputs the app uses for a rating; the profile comes from the
        # screener instead of a search, which saves a request per company.
        chart = provider.client.chart(symbol, "10y")
        ts = provider.client.timeseries(symbol, TIMESERIES_TYPES)
        profile = {"sector": sector, "industry": industry,
                   "longname": row.get("longName"), "shortname": row.get("shortName")}
        data = build_stock(symbol, chart, ts, profile=profile,
                           index_chart=provider.index_chart(chart.meta.get("exchangeName")), fx=provider.fx)
        return to_rating(data, "yahoo", benchmarks)

    return with_retries(symbol, fetch)


def rate_coin(client: yahoo.Client, listing: dict, rank: int) -> Rating | None:
    symbol = listing["symbol"]
    return with_retries(symbol, lambda: to_rating(build_crypto(symbol, client.chart(symbol, "10y"), listing, rank),
                                                  "yahoo"))


QUOTE_SUMMARY_URL = "https://query2.finance.yahoo.com/v10/finance/quoteSummary/"


def fetch_outlook(symbol: str) -> dict | None:
    """Analysts' forecasts for a stock. Yahoo only serves these with a login crumb, which yfinance handles."""
    from yfinance.data import YfData

    params = {"modules": "financialData,earningsTrend", "formatted": "false", "symbol": symbol,
              "corsDomain": "finance.yahoo.com"}
    for attempt in range(4):
        try:
            body = YfData().get_raw_json(QUOTE_SUMMARY_URL + symbol, params=params)
            result = ((body or {}).get("quoteSummary") or {}).get("result") or []
            return outlook.parse(result[0]) if result else None
        except Exception as exc:  # yfinance raises several types; 404 = no forecasts for this symbol
            text = str(exc)
            if "404" in text or "Not Found" in text:
                return None
            wait = 15 * 2 ** attempt
            log.warning("forecasts for %s failed (%s); retrying in %ss", symbol, text[:120], wait)
            time.sleep(wait)
    return None


def main() -> None:
    from yfinance.const import EQUITY_SCREENER_EQ_MAP

    parser = argparse.ArgumentParser()
    parser.add_argument("--limit-industries", type=int, default=0, help="for quick test runs")
    parser.add_argument("--coins", type=int, default=250)
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    benchmarks = benchmarks_module.load()
    provider = StockProvider()
    pairs = [(sector, industry) for sector, industries in EQUITY_SCREENER_EQ_MAP["industry"].items()
             for industry in industries]
    if args.limit_industries:
        pairs = pairs[:args.limit_industries]

    ratings: list[Rating] = []
    seen: set[str] = set()
    for i, (sector, industry) in enumerate(pairs, 1):
        rows = [r for r in industry_companies(industry) if r["symbol"] not in seen]
        seen.update(r["symbol"] for r in rows)
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            got = [r for r in pool.map(lambda row: rate_stock(provider, benchmarks, row, sector, industry), rows)
                   if r is not None and r.asset_type == "stock"]
        ratings.extend(got)
        log.info("[%d/%d] %s / %s: %d of %d companies", i, len(pairs), sector, industry, len(got), len(rows))

    directory = CryptoDirectory(provider.client)
    listings = [(q, rank) for rank, q in enumerate(directory.top(args.coins), 1)
                if (q.get("marketCap") or 0) >= MIN_COIN_MARKET_CAP]
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        coins = [r for r in pool.map(lambda x: rate_coin(provider.client, *x), listings) if r is not None]
    ratings.extend(coins)
    log.info("%d coins of %d listed over $%dM", len(coins), len(listings), MIN_COIN_MARKET_CAP // 1_000_000)

    generated_at = datetime.now(tz=timezone.utc).isoformat(timespec="minutes")
    stocks = [r for r in ratings if r.asset_type == "stock" and explore.eligible(r)]
    with ThreadPoolExecutor(max_workers=4) as pool:
        forecasts = dict(zip((r.ticker for r in stocks), pool.map(lambda r: fetch_outlook(r.ticker), stocks)))
    forecasts = {t: f for t, f in forecasts.items() if f}
    stored = {"generated_at": generated_at, "distributions": outlook.distributions(forecasts), "stocks": forecasts}
    store = outlook.OutlookStore(stored)
    for r in stocks:
        r.outlook = store.get(r.ticker, r.price)
    log.info("analyst forecasts for %d of %d stocks; outlook scores for %d", len(forecasts), len(stocks),
             sum(r.outlook is not None for r in stocks))
    if args.limit_industries or len(forecasts) >= len(stocks) / 2:
        outlook.DEFAULT_PATH.write_text(json.dumps(stored, indent=0, sort_keys=True))
    else:
        log.warning("too few forecasts; keeping the previous outlook.json")

    stocks_rated = sum(r.asset_type == "stock" and explore.eligible(r) for r in ratings)
    coins_rated = sum(r.asset_type == "crypto" and explore.eligible(r) for r in ratings)
    if not args.limit_industries and (stocks_rated < 1000 or coins_rated < 50):
        sys.exit(f"only {stocks_rated} stocks and {coins_rated} coins rated; refusing to publish thin rankings")

    lists = explore.build(ratings)
    for lst in lists:
        log.info("%s: %s", lst["title"], ", ".join(f"{i['symbol']} {i['score']:.0f}/{i['category_score']}"
                                                  for i in lst["items"][:8]))
    OUT.write_text(json.dumps({
        "generated_at": generated_at,
        "universe": f"US-listed companies worth over ${MIN_STOCK_MARKET_CAP // 1_000_000_000}B (including foreign "
                    f"companies' US listings) and coins worth over ${MIN_COIN_MARKET_CAP // 1_000_000}M",
        "stocks_rated": stocks_rated,
        "coins_rated": coins_rated,
        "lists": lists,
    }, indent=1))
    log.info("wrote %s: %d stocks and %d coins rated", OUT, stocks_rated, coins_rated)


if __name__ == "__main__":
    main()
