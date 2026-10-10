"""Data providers: live Yahoo Finance data via yfinance, or bundled demo data."""

from __future__ import annotations

import math
from typing import Protocol

from .models import StockData


class TickerNotFound(Exception):
    pass


class ProviderError(Exception):
    pass


class Provider(Protocol):
    name: str

    def fetch(self, ticker: str) -> StockData: ...


def _num(value: object) -> float | None:
    """Coerce Yahoo's loosely-typed values to a finite float, else None."""
    if value is None or isinstance(value, bool):
        return None
    try:
        f = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def momentum_from_closes(closes: list[float]) -> dict[str, float | None]:
    """1-year return and price vs 50/200-day simple moving averages."""
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


def _downsample(closes: list[float], points: int = 60) -> list[float]:
    # 4 decimals keeps penny-stock charts meaningful.
    if len(closes) <= points:
        return [round(c, 4) for c in closes]
    step = (len(closes) - 1) / (points - 1)
    return [round(closes[round(i * step)], 4) for i in range(points)]


class YahooProvider:
    name = "yahoo"

    def fetch(self, ticker: str) -> StockData:
        import yfinance as yf
        from yfinance.exceptions import YFRateLimitError

        # With yfinance's default settings an unknown ticker does not raise: info
        # comes back (nearly) empty and history comes back as an empty frame.
        # Network failures and rate limiting do raise, and are reported as such.
        try:
            t = yf.Ticker(ticker)
            info = t.info
            history = t.history(period="1y", auto_adjust=True)
        except YFRateLimitError as exc:
            raise ProviderError("Yahoo Finance is rate-limiting requests. Try again in a minute.") from exc
        except Exception as exc:  # yfinance raises a wide variety of errors
            raise ProviderError(f"Could not fetch data for {ticker}: {exc}") from exc

        if not isinstance(info, dict):
            info = {}
        closes: list[float] = []
        if history is not None and not history.empty and "Close" in history:
            closes = [c for c in (_num(v) for v in history["Close"].tolist()) if c is not None and c > 0]
        if not closes and _num(info.get("regularMarketPrice")) is None and _num(info.get("currentPrice")) is None:
            raise TickerNotFound(ticker)

        price = _num(info.get("currentPrice")) or _num(info.get("regularMarketPrice")) or (closes[-1] if closes else None)
        rec = info.get("recommendationKey")

        return StockData(
            ticker=ticker,
            name=info.get("shortName") or info.get("longName"),
            sector=info.get("sector"),
            currency=info.get("currency"),
            price=price,
            market_cap=_num(info.get("marketCap")),
            trailing_pe=_num(info.get("trailingPE")),
            forward_pe=_num(info.get("forwardPE")),
            peg_ratio=_num(info.get("trailingPegRatio")) or _num(info.get("pegRatio")),
            price_to_book=_num(info.get("priceToBook")),
            return_on_equity=_num(info.get("returnOnEquity")),
            profit_margin=_num(info.get("profitMargins")),
            operating_margin=_num(info.get("operatingMargins")),
            revenue_growth=_num(info.get("revenueGrowth")),
            earnings_growth=_num(info.get("earningsGrowth")),
            debt_to_equity=_num(info.get("debtToEquity")),
            current_ratio=_num(info.get("currentRatio")),
            free_cash_flow=_num(info.get("freeCashflow")),
            analyst_target_price=_num(info.get("targetMeanPrice")),
            analyst_recommendation=rec.replace("_", " ").title() if isinstance(rec, str) and rec != "none" else None,
            fifty_two_week_high=_num(info.get("fiftyTwoWeekHigh")),
            fifty_two_week_low=_num(info.get("fiftyTwoWeekLow")),
            price_history=_downsample(closes),
            **momentum_from_closes(closes),
        )


def _synthetic_closes(start: float, end: float, wobble: float, seed: int) -> list[float]:
    """Deterministic, smooth-ish 252-day price path for demo data."""
    n = 252
    closes = []
    for i in range(n):
        trend = start + (end - start) * i / (n - 1)
        noise = math.sin(i / 9 + seed) * wobble + math.sin(i / 3.7 + seed * 2) * wobble * 0.4
        closes.append(trend * (1 + noise))
    closes[-1] = end
    return closes


# Illustrative demo values only -- not real or current market data.
_SAMPLES: dict[str, dict] = {
    "AAPL": dict(name="Apple Inc. (demo)", sector="Technology", market_cap=3.4e12, trailing_pe=33.0, forward_pe=29.0,
                 peg_ratio=2.4, price_to_book=48.0, return_on_equity=1.4, profit_margin=0.24, operating_margin=0.31,
                 revenue_growth=0.05, earnings_growth=0.08, debt_to_equity=150.0, current_ratio=0.9, free_cash_flow=1.0e11,
                 analyst_target_price=245.0, analyst_recommendation="Buy", path=(190, 228, 0.04)),
    "MSFT": dict(name="Microsoft Corp. (demo)", sector="Technology", market_cap=3.2e12, trailing_pe=35.0, forward_pe=30.0,
                 peg_ratio=2.1, price_to_book=11.0, return_on_equity=0.35, profit_margin=0.36, operating_margin=0.45,
                 revenue_growth=0.15, earnings_growth=0.11, debt_to_equity=33.0, current_ratio=1.3, free_cash_flow=7.0e10,
                 analyst_target_price=500.0, analyst_recommendation="Strong Buy", path=(380, 430, 0.03)),
    "KO": dict(name="Coca-Cola Co. (demo)", sector="Consumer Defensive", market_cap=2.7e11, trailing_pe=25.0, forward_pe=22.0,
               peg_ratio=3.5, price_to_book=10.0, return_on_equity=0.40, profit_margin=0.23, operating_margin=0.29,
               revenue_growth=0.02, earnings_growth=-0.02, debt_to_equity=160.0, current_ratio=1.1, free_cash_flow=9.0e9,
               analyst_target_price=72.0, analyst_recommendation="Buy", path=(60, 63, 0.02)),
    "F": dict(name="Ford Motor Co. (demo)", sector="Consumer Cyclical", market_cap=4.3e10, trailing_pe=11.5, forward_pe=6.5,
              peg_ratio=0.9, price_to_book=1.0, return_on_equity=0.09, profit_margin=0.02, operating_margin=0.03,
              revenue_growth=0.01, earnings_growth=-0.25, debt_to_equity=350.0, current_ratio=1.15, free_cash_flow=6.0e9,
              analyst_target_price=11.5, analyst_recommendation="Hold", path=(13.5, 10.8, 0.05)),
    "XYZQ": dict(name="Unprofitable Growth Co. (demo)", sector="Technology", market_cap=5.0e9, trailing_pe=-20.0,
                 forward_pe=-45.0, peg_ratio=None, price_to_book=9.0, return_on_equity=-0.30, profit_margin=-0.25,
                 operating_margin=-0.20, revenue_growth=0.35, earnings_growth=None, debt_to_equity=80.0, current_ratio=3.0,
                 free_cash_flow=-4.0e8, analyst_target_price=30.0, analyst_recommendation="Hold", path=(40, 22, 0.08)),
    # Funds have no company fundamentals, so this one is left unrated.
    "QQQ": dict(name="Invesco QQQ Trust (demo)", path=(430, 510, 0.03)),
}


class SampleProvider:
    name = "sample"

    def fetch(self, ticker: str) -> StockData:
        sample = _SAMPLES.get(ticker)
        if sample is None:
            raise TickerNotFound(ticker)
        fields = dict(sample)
        start, end, wobble = fields.pop("path")
        closes = _synthetic_closes(start, end, wobble, seed=sum(map(ord, ticker)) % 17)
        return StockData(
            ticker=ticker,
            currency="USD",
            price=round(closes[-1], 2),
            fifty_two_week_high=round(max(closes), 2),
            fifty_two_week_low=round(min(closes), 2),
            price_history=_downsample(closes),
            **momentum_from_closes(closes),
            **fields,
        )

    @staticmethod
    def tickers() -> list[str]:
        return list(_SAMPLES)
