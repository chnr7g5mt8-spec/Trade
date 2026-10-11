"""Turns provider data into the `Rating` the app displays."""

from __future__ import annotations

from .benchmarks import Benchmarks
from .funds import FundStore, profile, rate_fund
from .models import CryptoData, Rating, StockData
from .scoring.common import MIN_COVERAGE
from .scoring.crypto import rate_crypto
from .scoring.stock import rate_stock


def to_rating(data: StockData | CryptoData, source: str, benchmarks: Benchmarks | None = None,
              funds: FundStore | None = None) -> Rating:
    notes = list(data.notes)
    facts = list(data.facts)
    fund_profile = None
    if isinstance(data, CryptoData):
        scored = rate_crypto(data)
        ident = dict(ticker=data.ticker, symbol=data.symbol, asset_type="crypto", name=data.name)
        rated_kind = not data.is_stablecoin
    elif data.asset_type == "fund":
        scored, fund_facts, fund_notes = rate_fund(data, funds)
        category = (funds.get(data.ticker) or {}).get("category") if funds else None
        # The fund's category (e.g. "Large Blend") plays the part of a company's industry.
        ident = dict(ticker=data.ticker, symbol=data.ticker, asset_type="fund", name=data.name,
                     exchange=data.exchange, industry=category)
        facts = fund_facts + facts
        notes.extend(fund_notes)
        fund_profile = profile(funds.get(data.ticker), funds.as_of) if funds else None
        rated_kind = False  # a fund's own notes explain when it isn't rated
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
        facts=facts,
        notes=notes,
        source=source,
        fund_profile=fund_profile,
        dividend=getattr(data, "dividend", None),
    )
