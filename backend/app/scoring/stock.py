"""Stock rating: eight categories, industry-relative where that is meaningful.

Valuation, profitability, growth and leverage norms differ a lot between
industries (a P/E of 30 is ordinary for software and expensive for a bank),
so those metrics are ranked against industry peers when benchmarks exist.
Momentum, risk and consistency are judged on absolute scales.
"""

from __future__ import annotations

from ..benchmarks import Benchmarks
from ..models import StockData
from .common import (CategorySpec, MetricSpec, Scored, negative_is_zero, pct, ratio, score_categories, times)


def _pe_fmt(v: float) -> str:
    return "Loss-making" if v <= 0 else f"{v:.1f}x"


def _de_fmt(v: float) -> str:
    return "Negative equity" if v < 0 else f"{v:.2f}x"


def _share_fmt(v: float) -> str:
    return f"{v * 100:.0f}% of years"


def _streak_fmt(v: float) -> str:
    return "1 year" if round(v) == 1 else f"{v:.0f} years"


def _negative_equity_is_zero(v: float) -> float | None:
    return 0.0 if v < 0 else None


def _yield_trap(v: float) -> float | None:
    # Very high yields usually mean the market expects a cut.
    return 30.0 if v > 0.12 else None


CATEGORIES: tuple[CategorySpec, ...] = (
    CategorySpec("valuation", "Valuation", 0.20, (
        MetricSpec("pe_ratio", "P/E (trailing)", bad=40, good=10, fmt=_pe_fmt, special=negative_is_zero, relative=True),
        MetricSpec("forward_pe", "P/E (forward)", bad=35, good=10, fmt=_pe_fmt, special=negative_is_zero, relative=True),
        MetricSpec("peg_ratio", "PEG ratio", bad=3, good=1, fmt=ratio, special=negative_is_zero, relative=True),
        MetricSpec("price_to_book", "Price / Book", bad=8, good=1, fmt=times, special=negative_is_zero, relative=True),
        MetricSpec("price_to_sales", "Price / Sales", bad=10, good=1, fmt=times, special=negative_is_zero, relative=True),
        MetricSpec("ev_to_ebitda", "EV / EBITDA", bad=25, good=6, fmt=times, special=negative_is_zero, relative=True),
        MetricSpec("fcf_yield", "Free cash flow yield", bad=0, good=0.07, fmt=pct, relative=True),
    )),
    CategorySpec("profitability", "Profitability", 0.20, (
        MetricSpec("return_on_equity", "Return on equity", bad=0, good=0.25, fmt=pct, relative=True),
        MetricSpec("return_on_assets", "Return on assets", bad=0, good=0.12, fmt=pct, relative=True),
        MetricSpec("gross_margin", "Gross margin", bad=0.10, good=0.60, fmt=pct, relative=True),
        MetricSpec("operating_margin", "Operating margin", bad=0, good=0.30, fmt=pct, relative=True),
        MetricSpec("net_margin", "Net margin", bad=0, good=0.25, fmt=pct, relative=True),
    )),
    CategorySpec("growth", "Growth", 0.15, (
        MetricSpec("revenue_growth", "Revenue growth (YoY)", bad=-0.05, good=0.20, fmt=pct, relative=True),
        MetricSpec("earnings_growth", "EPS growth (YoY)", bad=-0.10, good=0.25, fmt=pct, relative=True),
        MetricSpec("revenue_cagr_3y", "Revenue growth (3-yr avg)", bad=-0.02, good=0.15, fmt=pct, relative=True),
    )),
    CategorySpec("health", "Financial health", 0.15, (
        MetricSpec("debt_to_equity", "Debt / Equity", bad=2.0, good=0.3, fmt=_de_fmt,
                   special=_negative_equity_is_zero, relative=True),
        MetricSpec("current_ratio", "Current ratio", bad=0.8, good=2.0, fmt=ratio, relative=True),
        MetricSpec("quick_ratio", "Quick ratio", bad=0.5, good=1.5, fmt=ratio, relative=True),
        MetricSpec("interest_coverage", "Interest coverage", bad=1.5, good=12, fmt=times),
    )),
    CategorySpec("consistency", "Earnings consistency", 0.10, (
        MetricSpec("profitable_years", "Profitable years", bad=0.5, good=1.0, fmt=_share_fmt),
        MetricSpec("revenue_up_years", "Years revenue grew", bad=0.0, good=1.0, fmt=_share_fmt),
        MetricSpec("eps_up_years", "Years EPS grew", bad=0.0, good=1.0, fmt=_share_fmt),
    )),
    CategorySpec("momentum", "Momentum", 0.10, (
        MetricSpec("return_1y", "1-year return", bad=-0.20, good=0.30, fmt=pct),
        MetricSpec("price_vs_sma200", "Price vs 200-day avg", bad=-0.10, good=0.10, fmt=pct),
        MetricSpec("price_vs_sma50", "Price vs 50-day avg", bad=-0.05, good=0.05, fmt=pct),
    )),
    CategorySpec("risk", "Risk", 0.10, (
        MetricSpec("volatility_1y", "Volatility (1 yr)", bad=0.60, good=0.15, fmt=pct),
        MetricSpec("max_drawdown_1y", "Largest drop (1 yr)", bad=-0.50, good=-0.10, fmt=pct),
        MetricSpec("beta", "Beta vs market (5 yr)", bad=2.0, good=0.6, fmt=ratio),
    )),
    # Only counted for dividend payers, so non-payers aren't penalised.
    CategorySpec("income", "Dividends", 0.10, (
        MetricSpec("dividend_yield", "Dividend yield", bad=0, good=0.05, fmt=pct, special=_yield_trap, relative=True),
        MetricSpec("payout_ratio", "Payout ratio", bad=1.0, good=0.35, fmt=pct),
        MetricSpec("dividend_growth_5y", "Dividend growth (5-yr)", bad=-0.05, good=0.08, fmt=pct),
        # Measured over the 10 years of history fetched, i.e. at most 8 year-on-year increases.
        MetricSpec("dividend_streak", "Years of increases", bad=0, good=8, fmt=_streak_fmt),
    ), optional=True),
)


def rate_stock(data: StockData, benchmarks: Benchmarks | None = None) -> Scored:
    values = data.model_dump()
    if data.asset_type == "fund":
        # Show price-based categories for reference, but don't rate a basket of companies.
        shown = tuple(c for c in CATEGORIES if c.key in ("momentum", "risk", "income"))
        scored = score_categories(values, shown)
        scored.score, scored.label = None, "Not rated"
        return scored
    return score_categories(values, CATEGORIES, benchmarks, data.industry, data.sector)
