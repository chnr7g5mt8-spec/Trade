"""Scoring machinery shared by stocks and crypto.

Each metric maps linearly from a "bad" value (0 points) to a "good" value
(100 points), clamped. Metrics marked `relative` are also ranked against the
company's industry (or sector) peers when benchmarks are available: the score
is then 70% peer percentile and 30% the absolute scale, so a whole industry
that is expensive doesn't look cheap just because it is in line with peers.

A category's score is the average of its available metrics. The overall
score is the weighted average of available categories. Optional categories
(e.g. dividends) only count when they apply. Below MIN_COVERAGE of the core
metrics the asset is left unrated rather than labelled on thin evidence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from ..benchmarks import Benchmarks, PeerGroup
from ..models import CategoryScore, MetricScore, PeerInfo

RELATIVE_WEIGHT = 0.7
MIN_COVERAGE = 0.4

# Lower bound (inclusive) of each label, highest first.
LABELS: tuple[tuple[float, str], ...] = (
    (80, "Strong Buy"),
    (65, "Buy"),
    (45, "Hold"),
    (30, "Sell"),
    (0, "Strong Sell"),
)


@dataclass(frozen=True)
class MetricSpec:
    key: str
    label: str
    bad: float
    good: float
    fmt: Callable[[float], str]
    # Optional override, e.g. a negative P/E means losses and scores 0.
    special: Callable[[float], float | None] | None = None
    relative: bool = False  # rank against industry peers when benchmarks exist

    @property
    def higher_is_better(self) -> bool:
        return self.good > self.bad


@dataclass(frozen=True)
class CategorySpec:
    key: str
    label: str
    weight: float
    metrics: tuple[MetricSpec, ...]
    optional: bool = False  # only counted when at least one metric has data


@dataclass
class Scored:
    score: float | None
    label: str
    coverage: float
    categories: list[CategoryScore]
    peer: PeerInfo | None = None
    notes: list[str] = field(default_factory=list)


def label_for(score: float | None) -> str:
    if score is None:
        return "Not rated"
    for threshold, label in LABELS:
        if score >= threshold:
            return label
    return LABELS[-1][1]


def absolute_score(value: float, spec: MetricSpec) -> float:
    fraction = (value - spec.bad) / (spec.good - spec.bad)
    return max(0.0, min(1.0, fraction)) * 100


def score_metric(value: float | None, spec: MetricSpec, peers=None) -> float | None:
    """Score one metric; `peers` is an optional benchmarks.Distribution."""
    if value is None:
        return None
    if spec.special is not None:
        override = spec.special(value)
        if override is not None:
            return round(override, 1)
    absolute = absolute_score(value, spec)
    if spec.relative and peers is not None:
        pct = peers.percentile(value)
        relative = (pct if spec.higher_is_better else 1 - pct) * 100
        return round(RELATIVE_WEIGHT * relative + (1 - RELATIVE_WEIGHT) * absolute, 1)
    return round(absolute, 1)


def score_categories(values: dict[str, float | None], categories: tuple[CategorySpec, ...],
                     benchmarks: Benchmarks | None = None, industry: str | None = None,
                     sector: str | None = None) -> Scored:
    industry_group, sector_group = (benchmarks.lookup(industry, sector) if benchmarks else (None, None))
    used_groups: dict[str, PeerGroup] = {}
    out: list[CategoryScore] = []
    core_total = core_available = 0

    for cat in categories:
        metrics: list[MetricScore] = []
        for spec in cat.metrics:
            value = values.get(spec.key)
            peers = benchmark_text = None
            if spec.relative and benchmarks is not None:
                found = benchmarks.for_metric(spec.key, industry_group, sector_group)
                if found:
                    group, peers = found
                    used_groups[group.level] = group
                    benchmark_text = f"{group.level.capitalize()} median {spec.fmt(peers.median)}"
            score = score_metric(value, spec, peers)
            if not cat.optional:
                core_total += 1
                core_available += score is not None
            metrics.append(MetricScore(key=spec.key, label=spec.label, value=value,
                                       display=spec.fmt(value) if value is not None else "n/a",
                                       score=score, benchmark=benchmark_text))
        scored = [m.score for m in metrics if m.score is not None]
        cat_score = round(sum(scored) / len(scored), 1) if scored else None
        out.append(CategoryScore(key=cat.key, label=cat.label, weight=cat.weight, score=cat_score,
                                 metrics=metrics, optional=cat.optional))

    coverage = round(core_available / core_total, 2) if core_total else 0.0
    weighted = [(c.score, c.weight) for c in out if c.score is not None]
    weight_sum = sum(w for _, w in weighted)
    overall: float | None = None
    if weight_sum and coverage >= MIN_COVERAGE:
        # Whole number, so the score shown and the label derived from it always agree.
        overall = float(round(sum(s * w for s, w in weighted) / weight_sum))

    # Report the most specific peer group actually used.
    group = used_groups.get("industry") or used_groups.get("sector") or next(iter(used_groups.values()), None)
    peer = PeerInfo(name=group.name, level=group.level, companies=group.companies) if group else None
    return Scored(score=overall, label=label_for(overall), coverage=coverage, categories=out, peer=peer)


# Formatters
def pct(v: float) -> str:
    return f"{v * 100:.1f}%"


def ratio(v: float) -> str:
    return f"{v:.2f}"


def times(v: float) -> str:
    return f"{v:.1f}x"


def years(v: float) -> str:
    return f"{v:.0f} yr" if round(v) == 1 else f"{v:.0f} yrs"


def money_compact(v: float) -> str:
    for unit, size in (("T", 1e12), ("B", 1e9), ("M", 1e6), ("K", 1e3)):
        if abs(v) >= size:
            return f"${v / size:.1f}{unit}"
    return f"${v:,.0f}"


def negative_is_zero(v: float) -> float | None:
    return 0.0 if v <= 0 else None
