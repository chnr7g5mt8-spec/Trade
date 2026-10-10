"""ETF ratings: cost, performance against similar ETFs, risk, size and dividends.

A fund holds many companies, so it can't be rated on one company's results.
It is rated on what matters for a fund instead. Yahoo serves a fund's fee,
size and category only to logged-in sessions, which Render's servers can't
get, so the daily Explore job (scripts/build_explore.py) collects them for
every US-listed ETF worth over $500M into app/data/funds.json, together with
the spread of returns in each Yahoo fund category.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path

from .benchmarks import Benchmarks, Distribution, PeerGroup, norm
from .models import Fact, FundProfile, Holding, StockData, Weight
from .scoring.common import CategorySpec, MetricSpec, Scored, describe, money_compact, pct, ratio, score_categories

DEFAULT_PATH = Path(__file__).parent / "data" / "funds.json"
MIN_FUND_ASSETS = 500_000_000
# Category peer groups need this many ETFs with data for a measure.
MIN_CATEGORY_FUNDS = 8
PERFORMANCE_KEYS = ("return_1y", "return_3y", "return_5y")
# A fine grid, so funds near the top of a category don't all tie.
QUANTILES = tuple(round(i / 100, 2) for i in range(1, 100))

# Leveraged and inverse ETFs reset daily and are built for short-term trading;
# held for long they drift from the multiple they promise, so they aren't rated.
# ("Ultra-Short" bond funds are neither.)
TRADING_NAME_RE = re.compile(r"\b(\d(\.\d)?x|ultrapro|ultrashort|inverse|leveraged)\b|\bultra\b(?![- ]short)",
                             re.IGNORECASE)


def _expense_fmt(v: float) -> str:
    return f"{v * 100:.2f}% a year"


def _assets_fmt(v: float) -> str:
    return money_compact(10 ** v)


CATEGORIES: tuple[CategorySpec, ...] = (
    CategorySpec("cost", "Cost", 0.25, (
        MetricSpec("expense_ratio", "Yearly fee (expense ratio)", bad=0.0075, good=0.0003, fmt=_expense_fmt),
    )),
    # Compared with ETFs in the same Yahoo category, so a bond fund isn't
    # judged against a tech fund; 30% still comes from a fixed scale.
    CategorySpec("performance", "Performance", 0.35, (
        MetricSpec("return_1y", "1-year return", bad=-0.10, good=0.20, fmt=pct, relative=True),
        MetricSpec("return_3y", "3-year return (a year)", bad=-0.05, good=0.15, fmt=pct, relative=True),
        MetricSpec("return_5y", "5-year return (a year)", bad=-0.05, good=0.15, fmt=pct, relative=True),
    )),
    # Scales wide enough to tell cash-like funds from bond funds from stock funds.
    CategorySpec("risk", "Risk", 0.20, (
        MetricSpec("volatility_1y", "Volatility (1 yr)", bad=0.45, good=0.02, fmt=pct),
        MetricSpec("max_drawdown_1y", "Largest drop (1 yr)", bad=-0.45, good=-0.01, fmt=pct),
        MetricSpec("beta", "Beta vs market (5 yr)", bad=1.8, good=0.0, fmt=ratio),
    )),
    CategorySpec("size", "Size", 0.10, (
        # log10 of net assets: $100M scores 0, $20B scores 100.
        MetricSpec("assets_log", "Fund size (net assets)", bad=8.0, good=math.log10(2e10), fmt=_assets_fmt),
    )),
    CategorySpec("income", "Dividends", 0.10, (
        MetricSpec("dividend_yield", "Dividend yield", bad=0, good=0.07, fmt=pct),
    ), optional=True),
)
CATEGORIES = describe(CATEGORIES, {
    "cost": "The yearly fee the fund takes from your investment. Lower fees leave more of the return for you.",
    "performance": "Its total return, dividends included, compared with ETFs that invest in the same kind of things.",
    "risk": "How much the fund's price swings and how far it has fallen.",
    "size": "How much money the fund manages. Bigger funds are cheaper to trade and less likely to close.",
    "income": "How much the fund pays out in dividends or interest.",
})


def _raw(v) -> float | None:
    if isinstance(v, dict):
        v = v.get("raw")
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


SECTOR_NAMES = {
    "realestate": "Real estate", "consumer_cyclical": "Consumer cyclical", "basic_materials": "Basic materials",
    "consumer_defensive": "Consumer defensive", "technology": "Technology",
    "communication_services": "Communication services", "financial_services": "Financial services",
    "utilities": "Utilities", "industrials": "Industrials", "energy": "Energy", "healthcare": "Healthcare",
}
MIX_NAMES = {"stockPosition": "Stocks", "bondPosition": "Bonds", "cashPosition": "Cash", "preferredPosition":
             "Preferred shares", "convertiblePosition": "Convertibles", "otherPosition": "Other"}
MIN_WEIGHT = 0.005
MAX_SUMMARY = 600


def _summary(text: str | None) -> str | None:
    """Yahoo's description of the fund, cut at a sentence end if it is long."""
    text = " ".join((text or "").split())
    if len(text) <= MAX_SUMMARY:
        return text or None
    cut = text.rfind(". ", 0, MAX_SUMMARY)
    return text[:cut + 1] if cut > 100 else text[:MAX_SUMMARY].rsplit(" ", 1)[0] + "…"


def _holdings(top: dict) -> list[list]:
    out = []
    for h in top.get("holdings") or []:
        weight = _raw(h.get("holdingPercent"))
        name = h.get("holdingName") or h.get("symbol")
        if weight and name:
            out.append([h.get("symbol") or None, name, round(weight, 5)])
    return sorted(out, key=lambda h: -h[2])[:10]


def _weights(pairs, names: dict[str, str]) -> list[list]:
    out = [[names[k], round(w, 4)] for k, w in pairs if k in names and w is not None and w >= MIN_WEIGHT]
    return sorted(out, key=lambda x: -x[1])


def parse(summary: dict) -> dict | None:
    """Fee, size and category from a Yahoo quoteSummary result (fundProfile, summaryDetail, defaultKeyStatistics)."""
    profile = summary.get("fundProfile") or {}
    stats = summary.get("defaultKeyStatistics") or {}
    detail = summary.get("summaryDetail") or {}
    fees = profile.get("feesExpensesInvestment") or {}
    expense = _raw(fees.get("annualReportExpenseRatio"))
    if expense is None:
        expense = _raw(stats.get("annualReportExpenseRatio"))
    if expense is None:
        expense = _raw(detail.get("expenseRatio"))
    assets = _raw(detail.get("totalAssets")) or _raw(stats.get("totalAssets"))
    top = summary.get("topHoldings") or {}
    sectors = [(k, _raw(v)) for item in top.get("sectorWeightings") or [] for k, v in item.items()]
    out = {"expense_ratio": expense, "net_assets": assets, "category": profile.get("categoryName") or None,
           "family": profile.get("family") or None,
           "summary": _summary((summary.get("assetProfile") or {}).get("longBusinessSummary")),
           "holdings": _holdings(top) or None,
           "sectors": _weights(sectors, SECTOR_NAMES) or None,
           "mix": _weights([(k, _raw(top.get(k))) for k in MIX_NAMES], MIX_NAMES) or None}
    out = {k: v for k, v in out.items() if v is not None}
    return out or None


def is_trading_fund(category: str | None, name: str | None) -> bool:
    return bool(category and category.lower().startswith("trading")) or bool(TRADING_NAME_RE.search(name or ""))


def _quantiles(values: list[float]) -> list[list[float]]:
    xs = sorted(values)
    out = []
    for q in QUANTILES:
        pos = q * (len(xs) - 1)
        lo = int(pos)
        hi = min(lo + 1, len(xs) - 1)
        out.append([q, round(xs[lo] + (xs[hi] - xs[lo]) * (pos - lo), 6)])
    return out


def category_stats(funds: list[tuple[str, StockData]]) -> dict:
    """Return quantiles per Yahoo category: funds is (category, data) for each ETF."""
    by_cat: dict[str, list[StockData]] = {}
    for cat, data in funds:
        if cat:
            by_cat.setdefault(cat, []).append(data)
    out = {}
    for cat, items in by_cat.items():
        metrics = {}
        for key in PERFORMANCE_KEYS:
            values = [getattr(d, key) for d in items if getattr(d, key) is not None]
            if len(values) >= MIN_CATEGORY_FUNDS:
                metrics[key] = {"count": len(values), "q": _quantiles(values)}
        if metrics:
            out[cat] = {"funds": len(items), "metrics": metrics}
    return out


class FundStore:
    def __init__(self, data: dict | None = None):
        data = data or {}
        self.as_of: str | None = data.get("generated_at")
        self.funds: dict[str, dict] = data.get("funds", {})
        groups = {}
        for cat, g in (data.get("categories") or {}).items():
            metrics = {k: Distribution(count=m["count"], points=tuple((float(q), float(v)) for q, v in m["q"]))
                       for k, m in g["metrics"].items()}
            groups["industry:" + norm(cat)] = PeerGroup(name=cat, level="category", companies=g["funds"],
                                                         metrics=metrics)
        self.benchmarks = Benchmarks(groups=groups)

    def get(self, ticker: str) -> dict | None:
        return self.funds.get(ticker)


def profile(info: dict | None, as_of: str | None) -> FundProfile | None:
    if not info or not (info.get("summary") or info.get("holdings") or info.get("sectors") or info.get("mix")):
        return None
    return FundProfile(
        summary=info.get("summary"),
        holdings=[Holding(symbol=sym, name=name, weight=w) for sym, name, w in info.get("holdings") or []],
        sectors=[Weight(name=n, weight=w) for n, w in info.get("sectors") or []],
        asset_mix=[Weight(name=n, weight=w) for n, w in info.get("mix") or []],
        as_of=as_of,
    )


def rate_fund(data: StockData, store: FundStore | None) -> tuple[Scored, list[Fact], list[str]]:
    """The rating, extra key facts and notes for a fund."""
    info = store.get(data.ticker) if store else None
    values = data.model_dump()
    facts: list[Fact] = []
    notes: list[str] = []
    if info:
        values["expense_ratio"] = info.get("expense_ratio")
        if info.get("net_assets"):
            values["assets_log"] = math.log10(info["net_assets"])
            facts.append(Fact(label="Fund size", value=money_compact(info["net_assets"])))
        if info.get("expense_ratio") is not None:
            facts.append(Fact(label="Yearly fee", value=_expense_fmt(info["expense_ratio"])))
        if info.get("category"):
            facts.append(Fact(label="Category", value=info["category"]))
        if info.get("family"):
            facts.append(Fact(label="Fund family", value=info["family"]))
    category = (info or {}).get("category")
    scored = score_categories(values, CATEGORIES, store.benchmarks if store else None, industry=category)

    if not info:
        scored.score, scored.label = None, "Not rated"
        notes.append("Fund ratings cover US-listed ETFs worth over $500M, collected daily; this fund isn't "
                     "among them, so price trend, risk and dividends are shown for reference.")
    elif is_trading_fund(category, data.name):
        scored.score, scored.label = None, "Not rated"
        notes.append("Leveraged and inverse ETFs reset every day and are built for short-term trading; held for "
                     "longer they drift from the multiple they promise, so they aren't rated.")
    elif scored.score is None:
        notes.append(f"Not enough data to give a rating: only {round(scored.coverage * 100)}% of the measures "
                     f"are available.")
    return scored, facts, notes


def load(path: Path | None = None) -> FundStore:
    try:
        return FundStore(json.loads((path or DEFAULT_PATH).read_text()))
    except FileNotFoundError:
        return FundStore()
