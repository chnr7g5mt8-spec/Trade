"""Number cleaning and price-series statistics shared by stocks and crypto."""

from __future__ import annotations

import math
import statistics


def num(value: object) -> float | None:
    """Coerce loosely-typed API values to a finite float, else None."""
    if value is None or isinstance(value, bool):
        return None
    try:
        f = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def epoch(value: object) -> int | None:
    """Unix seconds from a numeric timestamp field; anything else is ignored."""
    v = num(value)
    return int(v) if v is not None and v > 0 else None


def momentum(closes: list[float]) -> dict[str, float | None]:
    """Return over the series and price vs its 50/200-period simple moving averages."""
    out: dict[str, float | None] = {"return_1y": None, "price_vs_sma50": None, "price_vs_sma200": None}
    if len(closes) < 2:
        return out
    last = closes[-1]
    if closes[0]:
        out["return_1y"] = last / closes[0] - 1
    if len(closes) >= 50:
        out["price_vs_sma50"] = last / (sum(closes[-50:]) / 50) - 1
    if len(closes) >= 200:
        out["price_vs_sma200"] = last / (sum(closes[-200:]) / 200) - 1
    return out


def annualized_volatility(closes: list[float], periods_per_year: int) -> float | None:
    """Standard deviation of period returns, scaled to a year. Needs ~2 months of data."""
    if len(closes) < 40:
        return None
    returns = [b / a - 1 for a, b in zip(closes, closes[1:]) if a > 0]
    if len(returns) < 2:
        return None
    return statistics.stdev(returns) * math.sqrt(periods_per_year)


def max_drawdown(closes: list[float]) -> float | None:
    """Largest peak-to-trough fall, as a negative fraction (e.g. -0.35)."""
    if len(closes) < 2:
        return None
    peak = closes[0]
    worst = 0.0
    for c in closes:
        peak = max(peak, c)
        if peak > 0:
            worst = min(worst, c / peak - 1)
    return worst


def downsample(closes: list[float], points: int = 60) -> list[float]:
    """Evenly spaced points for a sparkline; 4 decimals keeps penny prices meaningful."""
    if len(closes) <= points:
        return [round(c, 4) for c in closes]
    step = (len(closes) - 1) / (points - 1)
    return [round(closes[round(i * step)], 4) for i in range(points)]
