"""Explore: the best-rated stocks and coins in a few categories.

Rating thousands of companies takes far too long for a web request, so a
daily GitHub Action (scripts/build_explore.py) rates every US-listed company
worth over $1B plus the largest coins and stores the lists made by `build`
in app/data/explore.json.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .models import Rating

DEFAULT_PATH = Path(__file__).parent / "data" / "explore.json"
LIST_SIZE = 20
# A rating built from few measures can land at the extremes by chance, so
# the lists only include ratings backed by most of the measures.
MIN_COVERAGE = 0.6
# Lists by category rank on that category alone, so they only include
# companies rated Hold or better: a cheap stock with failing finances is not
# "best value".
MIN_OVERALL_FOR_CATEGORY = 45


@dataclass(frozen=True)
class ListSpec:
    key: str
    title: str
    description: str
    asset_type: str  # "stock" or "crypto"
    category: str | None = None  # rank by this category's score; None = overall score
    category_label: str | None = None  # how the app labels that score


HOLD_OR_BETTER = "among stocks rated Hold or better"
FEATURED = [
    ListSpec("top", "Top rated", "Highest overall score.", "stock"),
    ListSpec("value", "Best value", f"Cheapest compared with similar companies, {HOLD_OR_BETTER}.",
             "stock", "valuation", "Value score"),
    ListSpec("growth", "Strongest growth", f"Fastest-growing sales and earnings, {HOLD_OR_BETTER}.",
             "stock", "growth", "Growth score"),
    ListSpec("dividends", "Best dividends", f"Best dividend yield, growth and safety, {HOLD_OR_BETTER}.",
             "stock", "income", "Dividend score"),
    ListSpec("low_risk", "Lowest risk", f"Steadiest share prices, {HOLD_OR_BETTER}.",
             "stock", "risk", "Low-risk score"),
    ListSpec("momentum", "Strongest momentum", f"Strongest price trend, {HOLD_OR_BETTER}.",
             "stock", "momentum", "Momentum score"),
    ListSpec("crypto", "Top crypto", "Highest-rated coins. Stablecoins aren't rated.", "crypto"),
]


def _category_score(r: Rating, key: str) -> float | None:
    return next((c.score for c in r.categories if c.key == key), None)


def _item(r: Rating, category: str | None) -> dict:
    return {
        "ticker": r.ticker,
        "symbol": r.symbol,
        "name": r.name or r.symbol,
        "score": r.score,
        "label": r.label,
        "category_score": None if category is None else round(_category_score(r, category), 1),
        "sector": r.sector,
        "industry": r.industry,
        "exchange": r.exchange,
    }


def _ranked(pool: list[Rating], category: str | None) -> list[Rating]:
    if category is None:
        candidates = pool
        def key(r: Rating):
            return (-r.score, r.ticker)
    else:
        candidates = [r for r in pool if r.score >= MIN_OVERALL_FOR_CATEGORY
                      and _category_score(r, category) is not None]
        def key(r: Rating):
            return (-_category_score(r, category), -r.score, r.ticker)
    out: list[Rating] = []
    names: set[str] = set()
    for r in sorted(candidates, key=key):
        # Share classes of one company (GOOG/GOOGL, BRK-A/BRK-B) appear once.
        name = (r.name or r.ticker).strip().lower()
        if name in names:
            continue
        names.add(name)
        out.append(r)
        if len(out) == LIST_SIZE:
            break
    return out


def _make_list(spec: ListSpec, pool: list[Rating], group: str) -> dict:
    return {
        "key": spec.key,
        "title": spec.title,
        "description": spec.description,
        "group": group,
        "asset_type": spec.asset_type,
        "category": spec.category,
        "category_label": spec.category_label,
        "items": [_item(r, spec.category) for r in _ranked(pool, spec.category)],
    }


def eligible(r: Rating) -> bool:
    return r.asset_type in ("stock", "crypto") and r.score is not None and r.coverage >= MIN_COVERAGE


def build(ratings: list[Rating]) -> list[dict]:
    """The Explore lists: featured categories, then one per sector (largest first)."""
    rated = [r for r in ratings if eligible(r)]
    stocks = [r for r in rated if r.asset_type == "stock"]
    coins = [r for r in rated if r.asset_type == "crypto"]
    lists = [_make_list(spec, coins if spec.asset_type == "crypto" else stocks, "featured") for spec in FEATURED]

    by_sector: dict[str, list[Rating]] = {}
    for r in stocks:
        if r.sector:
            by_sector.setdefault(r.sector, []).append(r)
    for sector in sorted(by_sector, key=lambda s: (-len(by_sector[s]), s)):
        spec = ListSpec("sector:" + sector.lower().replace(" ", "-"), sector,
                        f"Highest overall score among {sector.lower()} companies.", "stock")
        lists.append(_make_list(spec, by_sector[sector], "sector"))
    return [lst for lst in lists if lst["items"]]


def load(path: Path | None = None) -> dict | None:
    try:
        data = json.loads((path or DEFAULT_PATH).read_text())
    except FileNotFoundError:
        return None
    return data if data.get("lists") else None
