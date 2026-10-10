"""Helpers for loading the recorded Yahoo responses in tests."""

from app.sources import recorded
from app.sources.yahoo import parse_chart, parse_timeseries


def chart(symbol: str):
    return parse_chart(symbol, recorded.load(f"chart_{symbol}")["chart"]["result"][0])


def timeseries(symbol: str):
    return parse_timeseries(recorded.load(f"timeseries_{symbol}"))


def profile(symbol: str) -> dict:
    for q in recorded.load(f"search_{symbol}")["quotes"]:
        if q["symbol"] == symbol:
            return q
    return {}


# The moment the recordings were made (Saturday 10 Oct 2026, markets closed),
# so time-dependent results are reproducible.
RECORDED_AT = chart("AAPL").meta["regularMarketTime"] + 18 * 3600
