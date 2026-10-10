"""Explore: the best-rated stocks and coins in a few categories.

Rating thousands of companies takes far too long for a web request, so a
daily GitHub Action (scripts/build_explore.py) rates every US-listed company
worth over $1B plus the largest coins and stores the lists made by `build`
in app/data/explore.json.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Callable
from pathlib import Path

from .models import Rating

DEFAULT_PATH = Path(__file__).parent / "data" / "explore.json"
LIST_SIZE = 20
# A rating built from few measures can land at the extremes by chance, so
# the lists only include ratings backed by most of the measures.
MIN_COVERAGE = 0.6
# Lists by a single category or measure only include companies rated Hold or
# better: a cheap stock with failing finances is not "best value".
MIN_OVERALL_FOR_CATEGORY = 45


def _category_score(r: Rating, key: str) -> float | None:
    return next((c.score for c in r.categories if c.key == key), None)


def category(key: str) -> Callable[[Rating], float | None]:
    return lambda r: _category_score(r, key)


def outlook_score(r: Rating) -> float | None:
    if r.outlook is None or r.outlook.analysts < MIN_ANALYSTS_FOR_LISTS:
        return None
    return r.outlook.score


def today_and_ahead(r: Rating) -> float | None:
    ahead = outlook_score(r)
    return None if ahead is None or r.score is None else (r.score + ahead) / 2


def growth_at_fair_price(r: Rating) -> float | None:
    growth, value = _category_score(r, "growth"), _category_score(r, "valuation")
    if growth is None or value is None or min(growth, value) < 50:
        return None
    return (growth + value) / 2


@dataclass(frozen=True)
class ListSpec:
    key: str
    title: str
    description: str
    asset_type: str  # "stock" or "crypto"
    measure: Callable[[Rating], float | None] | None = None  # rank by this; None = overall score
    measure_label: str | None = None  # how the app labels that measure


# Forecasts from one or two analysts are too thin to rank on.
MIN_ANALYSTS_FOR_LISTS = 5
HOLD_OR_BETTER = "among stocks rated Hold or better"
FEATURED = [
    ListSpec("top", "Top rated", "Highest overall score.", "stock"),
    ListSpec("today_and_ahead", "Strong today and ahead",
             f"Half the overall score, half the analyst outlook: strong results now and strong forecasts, "
             f"{HOLD_OR_BETTER}.", "stock", today_and_ahead, "Combined score"),
    ListSpec("outlook", "Future outlook",
             f"Best analyst outlook: forecast earnings and sales growth, price targets and buy ratings, "
             f"{HOLD_OR_BETTER}. Analysts' forecasts are often too optimistic.", "stock", outlook_score,
             "Outlook score"),
    ListSpec("garp", "Growth at a fair price",
             f"Scores at least 50 on both growth and value: growing fast without being expensive, "
             f"{HOLD_OR_BETTER}.", "stock", growth_at_fair_price, "Growth + value score"),
    ListSpec("value", "Best value", f"Cheapest compared with similar companies, {HOLD_OR_BETTER}.",
             "stock", category("valuation"), "Value score"),
    ListSpec("growth", "Strongest growth", f"Fastest-growing sales and earnings, {HOLD_OR_BETTER}.",
             "stock", category("growth"), "Growth score"),
    ListSpec("dividends", "Best dividends", f"Best dividend yield, growth and safety, {HOLD_OR_BETTER}.",
             "stock", category("income"), "Dividend score"),
    ListSpec("low_risk", "Lowest risk", f"Steadiest share prices, {HOLD_OR_BETTER}.",
             "stock", category("risk"), "Low-risk score"),
    ListSpec("momentum", "Strongest momentum", f"Strongest price trend, {HOLD_OR_BETTER}.",
             "stock", category("momentum"), "Momentum score"),
    ListSpec("crypto", "Top crypto",
             "Highest-rated coins. Stablecoins, gold tokens and wrapped copies of other coins are left out.", "crypto"),
]


def _item(r: Rating, value: float | None) -> dict:
    return {
        "ticker": r.ticker,
        "symbol": r.symbol,
        "name": r.name or r.symbol,
        "score": r.score,
        "label": r.label,
        "category_score": None if value is None else round(value, 1),
        "sector": r.sector,
        "industry": r.industry,
        "exchange": r.exchange,
    }


def _ranked(pool: list[Rating], measure) -> list[tuple[Rating, float | None]]:
    if measure is None:
        scored = sorted(((r, None) for r in pool), key=lambda x: (-x[0].score, x[0].ticker))
    else:
        # Lists by another measure only include companies rated Hold or better.
        candidates = [(r, measure(r)) for r in pool if r.score >= MIN_OVERALL_FOR_CATEGORY]
        scored = sorted(((r, v) for r, v in candidates if v is not None),
                        key=lambda x: (-x[1], -x[0].score, x[0].ticker))
    out: list[tuple[Rating, float | None]] = []
    names: set[str] = set()
    for r, v in scored:
        # Share classes of one company (GOOG/GOOGL, BRK-A/BRK-B) appear once.
        name = (r.name or r.ticker).strip().lower()
        if name in names:
            continue
        names.add(name)
        out.append((r, v))
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
        "category_label": spec.measure_label,
        "items": [_item(r, v) for r, v in _ranked(pool, spec.measure)],
    }


# Preferred shares (TRTN-PA, KIM-PM) trade like bonds but are rated on the
# company's financials, so they'd duplicate the company with a misleadingly
# low risk.
PREFERRED_RE = re.compile(r"-P[A-Z]?$")
# Closed-end funds are listed like companies, in Yahoo's Asset Management
# industry, but are funds: a list of the best companies shouldn't hold them.
FUND_NAME_RE = re.compile(r"\b(fund|funds|trust|investors|portfolio|municipal|income|opportunities)\b", re.IGNORECASE)
# Tokens that are claims on another coin (WBTC, WETH, staked ETH) would repeat it.
DERIVED_COIN_RE = re.compile(r"\b(wrapped|bridged|staked)\b", re.IGNORECASE)


def is_fund_like(r: Rating) -> bool:
    return (r.industry or "").lower() == "asset management" and bool(FUND_NAME_RE.search(r.name or ""))


def eligible(r: Rating) -> bool:
    if r.asset_type not in ("stock", "crypto") or r.score is None or r.coverage < MIN_COVERAGE:
        return False
    return r.asset_type == "crypto" or not (PREFERRED_RE.search(r.ticker) or is_fund_like(r))


def _rank(r: Rating) -> int:
    fact = next((f.value for f in r.facts if f.label == "Rank by market cap"), "")
    return int(fact.lstrip("#")) if fact.lstrip("#").isdigit() else 10**9


def _metric(r: Rating, key: str) -> float | None:
    return next((m.value for c in r.categories for m in c.metrics if m.key == key), None)


def _tracks(a: Rating, b: Rating) -> bool:
    """Whether coin a trades as a copy of coin b (same price and same year)."""
    if not a.price or not b.price or b.price < 10:
        return False
    ra, rb = _metric(a, "return_1y"), _metric(b, "return_1y")
    return abs(a.price / b.price - 1) < 0.01 and ra is not None and rb is not None and abs(ra - rb) < 0.03


def derived_coins(coins: list[Rating]) -> set[str]:
    """Tickers of wrapped, staked or bridged versions of other coins in the list."""
    symbols = {c.symbol for c in coins}
    by_size = sorted(coins, key=_rank)
    derived = set()
    for i, c in enumerate(by_size):
        if (DERIVED_COIN_RE.search(c.name or "") or (c.symbol.startswith("W") and c.symbol[1:] in symbols)
                or any(_tracks(c, bigger) for bigger in by_size[:i])):
            derived.add(c.ticker)
    return derived


def build(ratings: list[Rating]) -> list[dict]:
    """The Explore lists: featured categories, then one per sector (largest first)."""
    rated = [r for r in ratings if eligible(r)]
    stocks = [r for r in rated if r.asset_type == "stock"]
    coins = [r for r in rated if r.asset_type == "crypto"]
    derived = derived_coins(coins)
    coins = [r for r in coins if r.ticker not in derived]
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
