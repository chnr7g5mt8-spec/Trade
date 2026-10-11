"""Investor profiles: the same category scores, weighted for a style of investing.

The rating's categories are measured once; a profile only changes how much
each counts toward a stock's overall score (ETFs and coins are unaffected).
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import Rating
from .scoring.common import label_for


@dataclass(frozen=True)
class Profile:
    key: str
    label: str
    description: str
    weights: dict[str, float]  # stock category key -> weight; categories left out don't count
    # Whether a stock without a dividend counts as scoring 0 on dividends
    # (rather than leaving the category out, as the balanced rating does).
    dividends_required: bool = False


BALANCED = "balanced"
PROFILES: dict[str, Profile] = {p.key: p for p in (
    Profile(BALANCED, "Balanced", "The standard rating: every category counts.", {}),
    Profile("dividend", "Dividend investor",
            "Reliable, growing income: dividends and financial health count most; non-payers score 0 on dividends.",
            {"income": 0.30, "health": 0.20, "consistency": 0.15, "valuation": 0.15, "profitability": 0.10,
             "risk": 0.05, "momentum": 0.03, "growth": 0.02}, dividends_required=True),
    Profile("growth", "Growth investor", "Fast-growing companies with rising share prices.",
            {"growth": 0.35, "momentum": 0.20, "profitability": 0.15, "valuation": 0.10, "health": 0.10,
             "consistency": 0.05, "risk": 0.05}),
    Profile("value", "Value investor", "Cheap shares in sound, profitable companies.",
            {"valuation": 0.40, "profitability": 0.15, "health": 0.15, "consistency": 0.10, "growth": 0.10,
             "momentum": 0.05, "risk": 0.05}),
    Profile("safety", "Safety first", "Steady prices, strong finances and dependable profits.",
            {"risk": 0.30, "health": 0.25, "consistency": 0.15, "profitability": 0.15, "valuation": 0.10,
             "momentum": 0.05}),
)}


def get(key: str | None) -> Profile:
    return PROFILES.get(key or BALANCED, PROFILES[BALANCED])


def apply(rating: Rating, key: str | None) -> Rating:
    """The rating as seen by an investor with this profile."""
    profile = get(key)
    if profile.key == BALANCED or rating.asset_type != "stock" or rating.score is None:
        return rating
    total = weighted = 0.0
    categories = []
    for c in rating.categories:
        weight = profile.weights.get(c.key, 0.0)
        score = c.score
        if score is None and c.key == "income" and profile.dividends_required:
            score = 0.0
        if score is not None and weight:
            total += weight
            weighted += weight * score
        optional = c.optional and not (c.key == "income" and profile.dividends_required)
        categories.append(c.model_copy(update={"weight": weight, "optional": optional}))
    if not total:
        return rating
    score = float(round(weighted / total))
    return rating.model_copy(update={"score": score, "label": label_for(score), "categories": categories,
                                     "profile": profile.key})


def describe() -> list[dict]:
    return [{"key": p.key, "label": p.label, "description": p.description, "weights": p.weights,
             "dividends_required": p.dividends_required} for p in PROFILES.values()]
