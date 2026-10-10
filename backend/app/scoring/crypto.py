"""Crypto rating.

Coins have no earnings or balance sheets, so they're judged on how
established and liquid they are, their price trend, how risky they have
been, and how mature they are. Stablecoins are designed to hold a fixed
price, so rating them as investments would be meaningless.
"""

from __future__ import annotations

import math

from ..models import CryptoData
from .common import CategorySpec, MetricSpec, Scored, money_compact, pct, score_categories


def _log_market_cap(v: float) -> float | None:
    # $10M scores 0, $100B scores 100, on a log scale: size matters by orders of magnitude.
    if v <= 0:
        return 0.0
    return max(0.0, min(1.0, (math.log10(v) - 7) / 4)) * 100


def _years(v: float) -> str:
    return f"{v:.1f} years"


CATEGORIES: tuple[CategorySpec, ...] = (
    CategorySpec("market", "Market strength", 0.25, (
        MetricSpec("market_cap", "Market cap", bad=1e7, good=1e11, fmt=money_compact, special=_log_market_cap),
        MetricSpec("turnover", "24h volume / market cap", bad=0.002, good=0.03, fmt=pct),
    )),
    CategorySpec("momentum", "Momentum", 0.30, (
        MetricSpec("return_30d", "30-day return", bad=-0.30, good=0.30, fmt=pct),
        MetricSpec("return_1y", "1-year return", bad=-0.60, good=1.0, fmt=pct),
        MetricSpec("price_vs_sma200", "Price vs 200-day avg", bad=-0.30, good=0.30, fmt=pct),
        MetricSpec("price_vs_sma50", "Price vs 50-day avg", bad=-0.15, good=0.15, fmt=pct),
    )),
    CategorySpec("risk", "Risk", 0.35, (
        MetricSpec("volatility_1y", "Volatility (1 yr)", bad=1.5, good=0.4, fmt=pct),
        MetricSpec("max_drawdown_1y", "Largest drop (1 yr)", bad=-0.80, good=-0.20, fmt=pct),
        MetricSpec("from_all_time_high", "Below all-time high", bad=-0.95, good=-0.10, fmt=pct),
    )),
    CategorySpec("maturity", "Maturity & supply", 0.10, (
        MetricSpec("age_years", "Trading history", bad=0.5, good=8, fmt=_years),
        MetricSpec("supply_ratio", "Supply already issued", bad=0.2, good=1.0, fmt=pct),
    )),
)


COMPARISON_NOTE = ("Crypto scores compare coins with other coins. Even the highest-rated coins are far more "
                   "volatile than most stocks.")


def rate_crypto(data: CryptoData) -> Scored:
    scored = score_categories(data.model_dump(), CATEGORIES)
    if data.is_stablecoin:
        scored.score, scored.label = None, "Not rated"
    else:
        scored.notes.append(COMPARISON_NOTE)
    return scored
