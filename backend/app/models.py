"""Data shapes shared by the data providers, the scoring engine and the API."""

from __future__ import annotations

from pydantic import BaseModel


class StockData(BaseModel):
    """Raw inputs needed to rate a stock. Any metric may be missing (None)."""

    ticker: str
    name: str | None = None
    sector: str | None = None
    currency: str | None = None
    price: float | None = None
    market_cap: float | None = None

    # Valuation
    trailing_pe: float | None = None
    forward_pe: float | None = None
    peg_ratio: float | None = None
    price_to_book: float | None = None

    # Profitability (fractions, e.g. 0.25 == 25%)
    return_on_equity: float | None = None
    profit_margin: float | None = None
    operating_margin: float | None = None

    # Growth (year-over-year fractions)
    revenue_growth: float | None = None
    earnings_growth: float | None = None

    # Financial health
    debt_to_equity: float | None = None  # percent, as Yahoo reports it (150 == 1.5x)
    current_ratio: float | None = None
    free_cash_flow: float | None = None

    # Momentum (derived from price history)
    return_1y: float | None = None
    price_vs_sma50: float | None = None  # (price / SMA50) - 1
    price_vs_sma200: float | None = None  # (price / SMA200) - 1

    # Informational only, not used in the score
    analyst_target_price: float | None = None
    analyst_recommendation: str | None = None
    fifty_two_week_high: float | None = None
    fifty_two_week_low: float | None = None
    price_history: list[float] = []


class MetricScore(BaseModel):
    key: str
    label: str
    value: float | None
    display: str
    score: float | None  # 0-100, None when the metric is unavailable


class CategoryScore(BaseModel):
    key: str
    label: str
    weight: float
    score: float | None
    metrics: list[MetricScore]


class Rating(BaseModel):
    ticker: str
    name: str | None
    sector: str | None
    currency: str | None
    price: float | None
    score: float | None
    label: str
    coverage: float  # fraction of metrics that had data
    categories: list[CategoryScore]
    analyst_target_price: float | None = None
    analyst_recommendation: str | None = None
    fifty_two_week_high: float | None = None
    fifty_two_week_low: float | None = None
    price_history: list[float] = []
    source: str
