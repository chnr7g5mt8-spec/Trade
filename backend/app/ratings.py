"""Turns provider data into the `Rating` the app displays."""

from __future__ import annotations

from .benchmarks import Benchmarks
from .models import CryptoData, Rating, StockData
from .scoring.common import MIN_COVERAGE
from .scoring.crypto import rate_crypto
from .scoring.stock import rate_stock


def to_rating(data: StockData | CryptoData, source: str, benchmarks: Benchmarks | None = None) -> Rating:
    notes = list(data.notes)
    if isinstance(data, CryptoData):
        scored = rate_crypto(data)
        ident = dict(ticker=data.ticker, symbol=data.symbol, asset_type="crypto", name=data.name)
        rated_kind = not data.is_stablecoin
    else:
        scored = rate_stock(data, benchmarks)
        ident = dict(ticker=data.ticker, symbol=data.ticker, asset_type=data.asset_type, name=data.name,
                     exchange=data.exchange, sector=data.sector, industry=data.industry)
        rated_kind = data.asset_type == "stock"
        if rated_kind and scored.peer is None:
            if not benchmarks or not benchmarks.groups:
                notes.append("Industry benchmarks aren't available yet, so every measure is judged on a "
                             "fixed scale rather than against similar companies.")
            elif data.industry or data.sector:
                notes.append("There isn't enough data on similar companies to compare against, so every "
                             "measure is judged on a fixed scale.")
            else:
                notes.append("Yahoo doesn't list an industry for this company, so it can't be compared with "
                             "similar companies.")

    if rated_kind and scored.score is None:
        notes.append(f"Not enough data to give a rating: only {round(scored.coverage * 100)}% of the measures "
                     f"are available ({round(MIN_COVERAGE * 100)}% needed).")

    notes.extend(scored.notes)
    return Rating(
        **data.quote.model_dump(),
        **ident,
        score=scored.score,
        label=scored.label,
        coverage=scored.coverage,
        categories=scored.categories,
        peer_group=scored.peer,
        facts=data.facts,
        notes=notes,
        source=source,
    )
