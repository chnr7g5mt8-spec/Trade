"""Describes the rating rules, straight from the scoring code, plus the track record."""

from __future__ import annotations

import json
from pathlib import Path

from . import funds
from .benchmarks import Benchmarks, MIN_PEERS
from .scoring import crypto, stock
from .scoring.common import LABELS, MIN_COVERAGE, RELATIVE_WEIGHT, CategorySpec

TRACK_RECORD_PATH = Path(__file__).parent / "data" / "backtest.json"


def _categories(specs: tuple[CategorySpec, ...]) -> list[dict]:
    total = sum(c.weight for c in specs if not c.optional)
    return [{
        "key": c.key,
        "label": c.label,
        "weight": round(c.weight / total, 3),
        "optional": c.optional,
        "metrics": [{"key": m.key, "label": m.label, "relative": m.relative,
                     "higher_is_better": m.higher_is_better} for m in c.metrics],
    } for c in specs]


def track_record(path: Path = TRACK_RECORD_PATH) -> dict | None:
    if not path.is_file():
        return None
    return json.loads(path.read_text())


def describe(benchmarks: Benchmarks) -> dict:
    return {
        "labels": [{"label": label, "min_score": threshold} for threshold, label in LABELS],
        "min_coverage": MIN_COVERAGE,
        "relative_weight": RELATIVE_WEIGHT,
        "min_peers": MIN_PEERS,
        "stock_categories": _categories(stock.CATEGORIES),
        "crypto_categories": _categories(crypto.CATEGORIES),
        "fund_categories": _categories(funds.CATEGORIES),
        "benchmarks": {
            "generated_at": benchmarks.generated_at,
            "industries": sum(1 for g in benchmarks.groups.values() if g.level == "industry"),
            "sectors": sum(1 for g in benchmarks.groups.values() if g.level == "sector"),
        },
        "track_record": track_record(),
    }
