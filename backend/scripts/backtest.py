"""Track-record check: did higher-rated stocks go on to do better?

For each test date T (quarter ends), the largest companies *at T* (by market
cap then, from a broad pool of today's US-listed companies) are rated using
only information available at T:
  - annual statements published by then (fiscal year end + 75 days),
  - prices and dividends up to T,
  - peer norms computed from the universe at T, by sector.
The rating is then compared with the stock's total return over the next 12
months. Results go to app/data/backtest.json and are shown in the app.

Choosing companies by their size at T matters: picking today's largest
companies would load the test with stocks already known to have soared since
T (look-ahead bias), which were often small, unprofitable and volatile at T.

Limits (also written into the report): Yahoo's free statements reach back
only 4-5 years, so the test window is about two years; companies that have
since been delisted aren't in the pool (survivorship bias); estimates-based
measures (forward P/E, PEG) can't be recreated historically and are left out.

Runs on GitHub Actions (see .github/workflows/backtest.yml).
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import stats  # noqa: E402
from app.benchmarks import Benchmarks, Distribution, PeerGroup, QUANTILES, norm  # noqa: E402
from app.models import StockData  # noqa: E402
from app.providers.stocks import _dividend_metrics, beta, is_financial, NOT_FOR_FINANCIALS  # noqa: E402
from app.scoring.common import label_for, score_categories  # noqa: E402
from app.scoring.stock import CATEGORIES  # noqa: E402
from app.sources import yahoo  # noqa: E402
from app.sources.yahoo import Chart, Point  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "app" / "data" / "backtest.json"
PUBLICATION_LAG_DAYS = 75
HORIZON_DAYS = 365
ANNUAL_ITEMS = ["TotalRevenue", "NetIncomeCommonStockholders", "DilutedEPS", "OperatingIncome", "GrossProfit",
                "EBIT", "InterestExpense", "StockholdersEquity", "TotalDebt", "TotalAssets", "CurrentAssets",
                "CurrentLiabilities", "Inventory", "OrdinarySharesNumber", "FreeCashFlow", "CashDividendsPaid"]
ANNUAL_TYPES = [f"annual{k}" for k in ANNUAL_ITEMS]
# Measures that need analyst estimates or Yahoo's own ratio history aren't recreated.
NOT_BACKTESTED = {"forward_pe", "peg_ratio", "ev_to_ebitda"}

log = logging.getLogger("backtest")


@dataclass
class Company:
    symbol: str
    sector: str
    industry: str
    chart: Chart
    annual: dict[str, list[Point]]


# --- point-in-time reconstruction -------------------------------------------

def _ts(d: date) -> float:
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp()


def truncate(chart: Chart, t: float) -> Chart:
    n = sum(1 for x in chart.timestamps if x <= t)
    return Chart(symbol=chart.symbol, meta=chart.meta, timestamps=chart.timestamps[:n], closes=chart.closes[:n],
                 raw_closes=(chart.raw_closes or chart.closes)[:n], dividends=[d for d in chart.dividends if d[0] <= t])


def published(annual: dict[str, list[Point]], as_of: date) -> dict[str, list[Point]]:
    """Annual figures whose fiscal year ended at least PUBLICATION_LAG_DAYS before as_of."""
    cutoff = (as_of - timedelta(days=PUBLICATION_LAG_DAYS)).isoformat()
    return {k: [p for p in v if p.as_of <= cutoff] for k, v in annual.items()}


def _last(ts: dict[str, list[Point]], item: str) -> float | None:
    pts = ts.get("annual" + item) or []
    return pts[-1].value if pts else None


def _growth(ts: dict[str, list[Point]], item: str) -> float | None:
    pts = ts.get("annual" + item) or []
    if len(pts) < 2 or pts[-2].value <= 0:
        return None
    return pts[-1].value / pts[-2].value - 1


def stock_at(c: Company, as_of: date, index: Chart | None) -> StockData | None:
    t = _ts(as_of)
    ch = truncate(c.chart, t)
    if len(ch.closes) < 200:
        return None
    price = ch.raw_closes[-1]
    ts = published(c.annual, as_of)
    year_start = ch.timestamps[-1] - 365 * 86400
    year = [x for s, x in zip(ch.timestamps, ch.closes) if s >= year_start]
    d: dict = dict(ticker=c.symbol, sector=c.sector, industry=c.industry)
    d.update(stats.momentum(year))
    d["volatility_1y"] = stats.annualized_volatility(year, 252)
    d["max_drawdown_1y"] = stats.max_drawdown(year)
    d["beta"] = beta(ch, truncate(index, t) if index else None, now=t)
    d.update(_dividend_metrics(ch, price, t))

    shares, eps = _last(ts, "OrdinarySharesNumber"), _last(ts, "DilutedEPS")
    ni, revenue = _last(ts, "NetIncomeCommonStockholders"), _last(ts, "TotalRevenue")
    equity, assets = _last(ts, "StockholdersEquity"), _last(ts, "TotalAssets")
    if shares and shares > 0:
        cap = price * shares
        if eps is not None:
            d["pe_ratio"] = price / eps if eps > 0 else -1.0
        if equity:
            d["price_to_book"] = cap / equity if equity > 0 else -1.0
        if revenue and revenue > 0:
            d["price_to_sales"] = cap / revenue
        fcf = _last(ts, "FreeCashFlow")
        if fcf is not None:
            d["fcf_yield"] = fcf / cap
    if ni is not None and equity and equity > 0:
        d["return_on_equity"] = ni / equity
    if ni is not None and assets:
        d["return_on_assets"] = ni / assets
    if revenue and revenue > 0:
        for item, key in (("GrossProfit", "gross_margin"), ("OperatingIncome", "operating_margin"),
                          ("NetIncomeCommonStockholders", "net_margin")):
            v = _last(ts, item)
            if v is not None:
                d[key] = v / revenue
    d["revenue_growth"] = _growth(ts, "TotalRevenue")
    d["earnings_growth"] = _growth(ts, "DilutedEPS")
    debt = _last(ts, "TotalDebt")
    if debt is not None and equity:
        d["debt_to_equity"] = debt / equity if equity > 0 else -1.0
    ca, cl, inv = _last(ts, "CurrentAssets"), _last(ts, "CurrentLiabilities"), _last(ts, "Inventory")
    if ca and cl and cl > 0:
        d["current_ratio"] = ca / cl
        d["quick_ratio"] = (ca - (inv or 0.0)) / cl
    ebit, interest = _last(ts, "EBIT"), _last(ts, "InterestExpense")
    if ebit is not None and interest and interest > 0:
        d["interest_coverage"] = ebit / interest
    nis = ts.get("annualNetIncomeCommonStockholders") or []
    if len(nis) >= 2:
        d["profitable_years"] = sum(p.value > 0 for p in nis) / len(nis)
    paid = _last(ts, "CashDividendsPaid")
    if d.get("dividend_yield") and paid and ni and ni > 0:
        d["payout_ratio"] = abs(paid) / ni
    if is_financial(c.industry):
        for key in NOT_FOR_FINANCIALS:
            d.pop(key, None)
    return StockData(**d)


def market_cap_at(c: Company, as_of: date) -> float | None:
    """Price at as_of times the shares in the latest published annual report."""
    ch = truncate(c.chart, _ts(as_of))
    shares = _last(published(c.annual, as_of), "OrdinarySharesNumber")
    if not ch.raw_closes or not shares or shares <= 0:
        return None
    return ch.raw_closes[-1] * shares


def largest_at(companies: list[Company], as_of: date, n: int) -> list[Company]:
    sized = [(cap, c) for c in companies if (cap := market_cap_at(c, as_of))]
    sized.sort(key=lambda x: x[0], reverse=True)
    return [c for _, c in sized[:n]]


def forward_return(chart: Chart, as_of: date, days: int = HORIZON_DAYS) -> float | None:
    """Total return (dividend-adjusted) from as_of to as_of + days."""
    t0, t1 = _ts(as_of), _ts(as_of + timedelta(days=days))
    start = end = None
    for t, c in zip(chart.timestamps, chart.closes):
        if t <= t0:
            start = c
        if t <= t1:
            end = c
    if not start or not end or chart.timestamps[-1] < t1 - 7 * 86400:
        return None
    return end / start - 1


def sector_benchmarks(stocks: list[StockData]) -> Benchmarks:
    specs = [m for c in CATEGORIES for m in c.metrics if m.relative]
    groups = {}
    by_sector: dict[str, list[StockData]] = {}
    for s in stocks:
        by_sector.setdefault(s.sector or "", []).append(s)
    for sector, items in by_sector.items():
        metrics = {}
        for spec in specs:
            vals = sorted(v for v in (getattr(s, spec.key) for s in items)
                          if v is not None and (spec.special is None or spec.special(v) is None))
            if len(vals) >= 8:
                pts = []
                for q in QUANTILES:
                    pos = q * (len(vals) - 1)
                    lo = int(pos)
                    hi = min(lo + 1, len(vals) - 1)
                    pts.append((q, vals[lo] + (vals[hi] - vals[lo]) * (pos - lo)))
                metrics[spec.key] = Distribution(count=len(vals), points=tuple(pts))
        groups["sector:" + norm(sector)] = PeerGroup(sector, "sector", len(items), metrics)
    return Benchmarks(groups=groups)


# --- evaluation --------------------------------------------------------------

def spearman(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 10:
        return None

    def ranks(v: list[float]) -> list[float]:
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
                j += 1
            for k in range(i, j + 1):
                r[order[k]] = (i + j) / 2
            i = j + 1
        return r

    rx, ry = ranks(xs), ranks(ys)
    mx, my = statistics.fmean(rx), statistics.fmean(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = math.sqrt(sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry))
    return num / den if den else None


def quintile_returns(scored: list[tuple[float, float]], stat=statistics.fmean) -> list[float] | None:
    """Mean (or median) forward return of each fifth of companies, lowest scores first."""
    if len(scored) < 25:
        return None
    ordered = sorted(scored)
    n = len(ordered)
    return [stat([r for _, r in ordered[i * n // 5:(i + 1) * n // 5]]) for i in range(5)]


def evaluate(rows: list[dict], category_keys: list[str]) -> dict:
    """rows: {date, symbol, score, label, categories: {key: score}, forward_return}."""
    by_date: dict[str, list[dict]] = {}
    for r in rows:
        by_date.setdefault(r["date"], []).append(r)
    periods = []
    for d in sorted(by_date):
        rs = [r for r in by_date[d] if r["score"] is not None and r["forward_return"] is not None]
        q = quintile_returns([(r["score"], r["forward_return"]) for r in rs])
        if q is None:
            continue
        qm = quintile_returns([(r["score"], r["forward_return"]) for r in rs], statistics.median)
        cat_ic = {}
        for k in category_keys:
            pairs = [(r["categories"][k], r["forward_return"]) for r in rs if r["categories"].get(k) is not None]
            cat_ic[k] = spearman([p[0] for p in pairs], [p[1] for p in pairs])
        periods.append({
            "date": d, "companies": len(rs), "quintile_returns": [round(x, 4) for x in q],
            "quintile_median_returns": [round(x, 4) for x in qm],
            "top_minus_bottom": round(q[4] - q[0], 4),
            "top_minus_bottom_median": round(qm[4] - qm[0], 4),
            "average_return": round(statistics.fmean(r["forward_return"] for r in rs), 4),
            "rank_correlation": spearman([r["score"] for r in rs], [r["forward_return"] for r in rs]),
            "category_rank_correlation": cat_ic,
        })
    if not periods:
        return {"periods": []}

    def mean(xs):
        xs = [x for x in xs if x is not None]
        return round(statistics.fmean(xs), 4) if xs else None

    labels: dict[str, list[float]] = {}
    for r in rows:
        if r["score"] is not None and r["forward_return"] is not None:
            labels.setdefault(r["label"], []).append(r["forward_return"])
    spreads = [p["top_minus_bottom"] for p in periods]
    ics = [p["rank_correlation"] for p in periods]
    return {
        "periods": periods,
        "summary": {
            "test_dates": len(periods),
            "observations": sum(p["companies"] for p in periods),
            "quintile_returns": [mean([p["quintile_returns"][i] for p in periods]) for i in range(5)],
            "quintile_median_returns": [mean([p["quintile_median_returns"][i] for p in periods]) for i in range(5)],
            "top_minus_bottom": mean(spreads),
            "top_minus_bottom_median": mean([p["top_minus_bottom_median"] for p in periods]),
            "top_beat_bottom_share": round(sum(s > 0 for s in spreads) / len(spreads), 2),
            "rank_correlation": mean(ics),
            "positive_rank_correlation_share": round(sum((x or 0) > 0 for x in ics) / len(ics), 2),
            # The 12-month windows of consecutive quarterly start dates overlap, so the dates
            # aren't independent observations; no significance statistics are reported.
            "independent_years": round(len(periods) / 4 + 0.75, 1),
            "average_return": mean([p["average_return"] for p in periods]),
            "by_label": {k: {"count": len(v), "average_return": round(statistics.fmean(v), 4),
                             "median_return": round(statistics.median(v), 4)}
                         for k, v in labels.items()},
            "category_rank_correlation": {k: mean([p["category_rank_correlation"][k] for p in periods])
                                          for k in category_keys},
            "category_positive_share": {
                k: round(sum((p["category_rank_correlation"][k] or 0) > 0 for p in periods) / len(periods), 2)
                for k in category_keys},
        },
    }


def rate_universe(companies: list[Company], dates: list[date], index: Chart | None, per_date: int) -> list[dict]:
    rows = []
    for d in dates:
        stocks = []
        for c in largest_at(companies, d, per_date):
            s = stock_at(c, d, index)
            if s is not None:
                stocks.append((c, s))
        bench = sector_benchmarks([s for _, s in stocks])
        for c, s in stocks:
            values = s.model_dump()
            for k in NOT_BACKTESTED:
                values[k] = None
            scored = score_categories(values, CATEGORIES, bench, None, s.sector)
            rows.append({"date": d.isoformat(), "symbol": c.symbol, "score": scored.score,
                         "label": label_for(scored.score),
                         "categories": {cat.key: cat.score for cat in scored.categories},
                         "forward_return": forward_return(c.chart, d)})
        log.info("%s: rated %d companies", d, len(stocks))
    return rows


def test_dates(companies: list[Company], today: date) -> list[date]:
    """Quarter ends where two published fiscal years exist and a full year of results has passed."""
    ends = []
    for y in range(today.year - 6, today.year + 1):
        for m, dd in ((3, 31), (6, 30), (9, 30), (12, 31)):
            ends.append(date(y, m, dd))
    latest = today - timedelta(days=HORIZON_DAYS + 7)
    out = []
    for d in ends:
        if d > latest:
            continue
        with_two_years = sum(1 for c in companies
                             if len((published(c.annual, d).get("annualTotalRevenue") or [])) >= 2)
        if with_two_years >= 0.6 * len(companies):
            out.append(d)
    return out


# --- data collection ---------------------------------------------------------

def universe(size: int) -> list[str]:
    """A broad pool of today's US-listed companies; each test date then takes the largest *at that date*."""
    import yfinance as yf
    from yfinance import EquityQuery

    q = EquityQuery("and", [EquityQuery("is-in", ["exchange", "NMS", "NYQ"]),
                            EquityQuery("gt", ["intradaymarketcap", 1_000_000_000])])
    symbols: list[str] = []
    for offset in range(0, size, 250):
        r = yf.screen(q, offset=offset, size=min(250, size - offset), sortField="intradaymarketcap", sortAsc=False)
        symbols.extend(x["symbol"] for x in r.get("quotes", []) if x.get("quoteType") == "EQUITY")
    return list(dict.fromkeys(symbols))


def load_company(client: yahoo.Client, symbol: str) -> Company | None:
    for attempt in range(4):
        try:
            prof = next((q for q in client.search(symbol, 10) if q.get("symbol") == symbol), {})
            if not prof.get("sector"):
                return None
            chart = client.chart(symbol, "10y")
            annual = client.timeseries(symbol, ANNUAL_TYPES, years=8)
            # Statements in another currency than the share price (ADRs) can't be valued without
            # historical FX rates, so those companies are left out.
            cur = next((p.currency for pts in annual.values() for p in pts if p.currency), None)
            if cur and cur != chart.currency:
                return None
            return Company(symbol, prof["sector"], prof.get("industry") or "", chart, annual)
        except yahoo.YahooRateLimited:
            time.sleep(30 * 2 ** attempt)
        except yahoo.YahooError as exc:
            log.warning("%s: %s", symbol, exc)
            return None
    return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pool", type=int, default=2000, help="today's largest companies to draw from")
    parser.add_argument("--size", type=int, default=400, help="companies rated at each test date")
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    client = yahoo.Client()
    symbols = universe(args.pool)
    log.info("universe: %d symbols", len(symbols))
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        companies = [c for c in pool.map(lambda s: load_company(client, s), symbols) if c]
    log.info("loaded %d companies", len(companies))
    index = client.chart("^GSPC", "10y")
    dates = test_dates(companies, datetime.now(tz=timezone.utc).date())
    log.info("test dates: %s", [d.isoformat() for d in dates])
    rows = rate_universe(companies, dates, index, args.size)
    report = evaluate(rows, [c.key for c in CATEGORIES])
    report.update({
        "generated_at": datetime.now(tz=timezone.utc).date().isoformat(),
        "universe": (f"At each start date, the {args.size} largest companies at that time (by market cap then), "
                     f"from a pool of {len(companies)} US-listed companies with usable data"),
        "horizon_days": HORIZON_DAYS,
        "method": ("At each test date, every company is rated using only annual reports published by then "
                   f"(at least {PUBLICATION_LAG_DAYS} days after the fiscal year ended) and prices up to that "
                   "day, with peers compared by sector. The rating is compared with the stock's total return "
                   "over the following 12 months."),
        "limitations": [
            "Yahoo's free financial history reaches back only 4-5 years, so the test covers about two years "
            "of start dates. Results over such a short period can be luck in either direction.",
            "Companies are picked by their size at each start date, but the pool only contains companies still "
            "listed today, so ones that were delisted since are missing (survivorship bias).",
            "Start dates are a quarter apart and returns are measured over a year, so the periods overlap: the "
            "test holds roughly two years of independent evidence.",
            "Forward P/E, PEG and EV/EBITDA need historical analyst estimates or ratios that aren't freely "
            "available, so the tested ratings leave them out.",
            "The weights were adjusted once after an earlier run of this test (momentum up from 10% to 15%, "
            "earnings consistency down from 10% to 5%), so this period isn't an independent check of that change.",
            "Past results don't guarantee future returns.",
        ],
    })
    OUT.write_text(json.dumps(report, indent=1))
    log.info("summary: %s", json.dumps(report.get("summary"), indent=1))
    if len(report["periods"]) < 3:
        sys.exit("fewer than 3 usable test dates; not publishing")


if __name__ == "__main__":
    main()
