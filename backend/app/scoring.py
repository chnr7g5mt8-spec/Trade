"""Turns raw StockData into a 0-100 score and a Buy/Hold/Sell style label.

Each metric is mapped linearly between a "bad" threshold (score 0) and a
"good" threshold (score 100), clamped at both ends. A category's score is the
average of its available metrics; the overall score is the weighted average of
available categories, so missing data shrinks the denominator rather than
dragging the score down. `coverage` reports how much data the score rests on,
and below MIN_COVERAGE the stock is left unrated rather than given a label
backed by a handful of numbers (e.g. an ETF with only price momentum).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .models import CategoryScore, MetricScore, Rating, StockData


@dataclass(frozen=True)
class MetricSpec:
    key: str
    label: str
    bad: float
    good: float
    fmt: Callable[[float], str]
    # Optional override, e.g. a negative P/E means losses and scores 0.
    special: Callable[[float], float | None] | None = None


@dataclass(frozen=True)
class CategorySpec:
    key: str
    label: str
    weight: float
    metrics: tuple[MetricSpec, ...]


def _pct(v: float) -> str:
    return f"{v * 100:.1f}%"


def _ratio(v: float) -> str:
    return f"{v:.2f}"


def _times(v: float) -> str:
    return f"{v:.1f}x"


def _negative_is_zero(v: float) -> float | None:
    return 0.0 if v <= 0 else None


def _negative_equity_is_zero(v: float) -> float | None:
    # Debt/equity is only negative when shareholder equity is negative.
    return 0.0 if v < 0 else None


CATEGORIES: tuple[CategorySpec, ...] = (
    CategorySpec(
        "valuation",
        "Valuation",
        0.25,
        (
            MetricSpec("trailing_pe", "P/E (trailing)", bad=40, good=10, fmt=_times, special=_negative_is_zero),
            MetricSpec("forward_pe", "P/E (forward)", bad=35, good=10, fmt=_times, special=_negative_is_zero),
            MetricSpec("peg_ratio", "PEG ratio", bad=3, good=1, fmt=_ratio, special=_negative_is_zero),
            MetricSpec("price_to_book", "Price / Book", bad=8, good=1, fmt=_times, special=_negative_is_zero),
        ),
    ),
    CategorySpec(
        "profitability",
        "Profitability",
        0.25,
        (
            MetricSpec("return_on_equity", "Return on equity", bad=0, good=0.25, fmt=_pct),
            MetricSpec("profit_margin", "Net margin", bad=0, good=0.25, fmt=_pct),
            MetricSpec("operating_margin", "Operating margin", bad=0, good=0.30, fmt=_pct),
        ),
    ),
    CategorySpec(
        "growth",
        "Growth",
        0.20,
        (
            MetricSpec("revenue_growth", "Revenue growth (YoY)", bad=-0.05, good=0.20, fmt=_pct),
            MetricSpec("earnings_growth", "Earnings growth (YoY)", bad=-0.10, good=0.25, fmt=_pct),
        ),
    ),
    CategorySpec(
        "health",
        "Financial health",
        0.15,
        (
            MetricSpec("debt_to_equity", "Debt / Equity", bad=200, good=30, fmt=lambda v: f"{v / 100:.2f}x",
                       special=_negative_equity_is_zero),
            MetricSpec("current_ratio", "Current ratio", bad=0.8, good=2.0, fmt=_ratio),
            MetricSpec("fcf_yield", "Free cash flow yield", bad=0, good=0.06, fmt=_pct),
        ),
    ),
    CategorySpec(
        "momentum",
        "Momentum",
        0.15,
        (
            MetricSpec("return_1y", "1-year return", bad=-0.20, good=0.30, fmt=_pct),
            MetricSpec("price_vs_sma200", "Price vs 200-day avg", bad=-0.10, good=0.10, fmt=_pct),
            MetricSpec("price_vs_sma50", "Price vs 50-day avg", bad=-0.05, good=0.05, fmt=_pct),
        ),
    ),
)

MIN_COVERAGE = 0.4

# Lower bound (inclusive) of each label, highest first.
LABELS: tuple[tuple[float, str], ...] = (
    (80, "Strong Buy"),
    (65, "Buy"),
    (45, "Hold"),
    (30, "Sell"),
    (0, "Strong Sell"),
)


def label_for(score: float | None) -> str:
    if score is None:
        return "Not rated"
    for threshold, label in LABELS:
        if score >= threshold:
            return label
    return LABELS[-1][1]


def score_metric(value: float | None, spec: MetricSpec) -> float | None:
    if value is None:
        return None
    if spec.special is not None:
        override = spec.special(value)
        if override is not None:
            return override
    fraction = (value - spec.bad) / (spec.good - spec.bad)
    return round(max(0.0, min(1.0, fraction)) * 100, 1)


def _metric_values(data: StockData) -> dict[str, float | None]:
    values = data.model_dump()
    fcf_yield = None
    if data.free_cash_flow is not None and data.market_cap:
        fcf_yield = data.free_cash_flow / data.market_cap
    values["fcf_yield"] = fcf_yield
    return values


def rate(data: StockData, source: str) -> Rating:
    values = _metric_values(data)
    categories: list[CategoryScore] = []
    total_metrics = 0
    available_metrics = 0

    for cat in CATEGORIES:
        metrics: list[MetricScore] = []
        for spec in cat.metrics:
            value = values.get(spec.key)
            score = score_metric(value, spec)
            total_metrics += 1
            if score is not None:
                available_metrics += 1
            metrics.append(
                MetricScore(
                    key=spec.key,
                    label=spec.label,
                    value=value,
                    display=spec.fmt(value) if value is not None else "n/a",
                    score=score,
                )
            )
        scored = [m.score for m in metrics if m.score is not None]
        cat_score = round(sum(scored) / len(scored), 1) if scored else None
        categories.append(CategoryScore(key=cat.key, label=cat.label, weight=cat.weight, score=cat_score, metrics=metrics))

    coverage = round(available_metrics / total_metrics, 2) if total_metrics else 0.0
    weighted = [(c.score, c.weight) for c in categories if c.score is not None]
    weight_sum = sum(w for _, w in weighted)
    overall: float | None = None
    if weight_sum and coverage >= MIN_COVERAGE:
        # Whole number, so the score shown and the label derived from it always agree.
        overall = float(round(sum(s * w for s, w in weighted) / weight_sum))

    return Rating(
        ticker=data.ticker,
        name=data.name,
        sector=data.sector,
        currency=data.currency,
        price=data.price,
        score=overall,
        label=label_for(overall),
        coverage=coverage,
        categories=categories,
        analyst_target_price=data.analyst_target_price,
        analyst_recommendation=data.analyst_recommendation,
        fifty_two_week_high=data.fifty_two_week_high,
        fifty_two_week_low=data.fifty_two_week_low,
        price_history=data.price_history,
        source=source,
    )
