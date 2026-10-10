"""Analyst outlook: what Wall Street analysts expect for a stock.

Kept apart from the rating: the rating is built from reported results and
prices, while this is built from forecasts (next year's earnings and sales
growth, the average price target and the buy/sell consensus). Yahoo only
serves these to logged-in sessions, which Render's servers can't get, so the
daily Explore job (scripts/build_explore.py) collects them for every stock it
rates and stores them in app/data/outlook.json.
"""

from __future__ import annotations

import json
from pathlib import Path

from .benchmarks import Benchmarks, Distribution, PeerGroup
from .models import Outlook
from .scoring.common import CategorySpec, MetricSpec, pct, score_categories

DEFAULT_PATH = Path(__file__).parent / "data" / "outlook.json"
MIN_ANALYSTS = 3
MIN_METRICS = 2
# Each forecast is ranked against every stock with forecasts (70% of its
# points, like the rating's peer comparison), on a fine grid so the best
# outlooks don't all tie at the top of a fixed scale.
QUANTILES = tuple(round(i / 100, 2) for i in range(1, 100))
MARKET = "market"


def _consensus(v: float) -> str:
    for limit, word in ((1.5, "Strong Buy"), (2.5, "Buy"), (3.5, "Hold"), (4.5, "Sell")):
        if v < limit:
            return f"{v:.1f} ({word})"
    return f"{v:.1f} (Strong Sell)"


SPEC = CategorySpec("outlook", "Analyst outlook", 1.0, (
    MetricSpec("eps_growth_next_year", "Forecast EPS growth, next year", bad=-0.05, good=0.25, fmt=pct,
               relative=True),
    MetricSpec("revenue_growth_next_year", "Forecast sales growth, next year", bad=0.0, good=0.20, fmt=pct,
               relative=True),
    MetricSpec("target_upside", "Average price target vs price", bad=-0.05, good=0.30, fmt=pct, relative=True),
    MetricSpec("recommendation", "Analyst consensus (1 = Strong Buy, 5 = Sell)", bad=3.5, good=1.5,
               fmt=_consensus, relative=True),
))


def _raw(v) -> float | None:
    if isinstance(v, dict):
        v = v.get("raw")
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def parse(summary: dict) -> dict | None:
    """The forecast figures from a Yahoo quoteSummary result (financialData and earningsTrend modules)."""
    fd = summary.get("financialData") or {}
    trend = {t.get("period"): t for t in (summary.get("earningsTrend") or {}).get("trend", [])}
    analysts = _raw(fd.get("numberOfAnalystOpinions"))
    if not analysts:
        return None
    out: dict = {"analysts": int(analysts), "target_mean": _raw(fd.get("targetMeanPrice")),
                 "price": _raw(fd.get("currentPrice")), "recommendation": _raw(fd.get("recommendationMean"))}
    next_year = trend.get("+1y") or {}
    eps = next_year.get("earningsEstimate") or {}
    this_year_eps = _raw(eps.get("yearAgoEps"))
    # Growth from a loss (or from zero) isn't a meaningful percentage.
    if this_year_eps is not None and this_year_eps > 0:
        out["eps_growth_next_year"] = _raw(eps.get("growth"))
    out["revenue_growth_next_year"] = _raw((next_year.get("revenueEstimate") or {}).get("growth"))
    return {k: v for k, v in out.items() if v is not None}


def _values(raw: dict, price: float | None = None) -> dict:
    values = dict(raw)
    reference = price or raw.get("price")
    if raw.get("target_mean") and reference:
        values["target_upside"] = raw["target_mean"] / reference - 1
    return values


def _quantiles(values: list[float]) -> list[list[float]]:
    xs = sorted(values)
    out = []
    for q in QUANTILES:
        pos = q * (len(xs) - 1)
        lo = int(pos)
        hi = min(lo + 1, len(xs) - 1)
        out.append([q, round(xs[lo] + (xs[hi] - xs[lo]) * (pos - lo), 6)])
    return out


def distributions(stocks: dict[str, dict]) -> dict:
    """Quantiles of each forecast across every stock with enough analysts."""
    covered = [_values(raw) for raw in stocks.values() if raw.get("analysts", 0) >= MIN_ANALYSTS]
    out = {}
    for spec in SPEC.metrics:
        values = [v[spec.key] for v in covered if v.get(spec.key) is not None]
        if len(values) >= 100:
            out[spec.key] = {"count": len(values), "q": _quantiles(values)}
    return out


def market_benchmarks(dists: dict) -> Benchmarks | None:
    if not dists:
        return None
    metrics = {k: Distribution(count=d["count"], points=tuple((float(q), float(v)) for q, v in d["q"]))
               for k, d in dists.items()}
    companies = max(d.count for d in metrics.values())
    group = PeerGroup(name="all US-listed stocks with forecasts", level=MARKET, companies=companies, metrics=metrics)
    return Benchmarks(groups={"industry:" + MARKET: group})


def build(raw: dict | None, price: float | None, as_of: str | None,
          benchmarks: Benchmarks | None = None) -> Outlook | None:
    """Score stored forecast figures; the price target is compared with the current price."""
    if not raw or raw.get("analysts", 0) < MIN_ANALYSTS:
        return None
    scored = score_categories(_values(raw, price), (SPEC,), benchmarks, industry=MARKET)
    category = scored.categories[0]
    for m in category.metrics:
        if m.benchmark:
            m.benchmark = m.benchmark.replace("Market median", "vs all US stocks · median")
    if sum(m.score is not None for m in category.metrics) < MIN_METRICS:
        return None
    return Outlook(score=category.score, analysts=raw["analysts"], as_of=as_of, category=category)


class OutlookStore:
    def __init__(self, data: dict | None = None):
        data = data or {}
        self.as_of: str | None = data.get("generated_at")
        self.stocks: dict[str, dict] = data.get("stocks", {})
        self.benchmarks = market_benchmarks(data.get("distributions") or {})

    def get(self, ticker: str, price: float | None) -> Outlook | None:
        return build(self.stocks.get(ticker), price, self.as_of, self.benchmarks)


def load(path: Path | None = None) -> OutlookStore:
    try:
        return OutlookStore(json.loads((path or DEFAULT_PATH).read_text()))
    except FileNotFoundError:
        return OutlookStore()
