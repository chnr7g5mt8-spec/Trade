import json

import pytest

from app import benchmarks
from app.benchmarks import Distribution, MIN_PEERS, norm

DIST = Distribution(count=50, points=((0.05, 5.0), (0.1, 8.0), (0.25, 12.0), (0.5, 20.0), (0.75, 30.0),
                                      (0.9, 45.0), (0.95, 60.0)))


def test_norm_matches_yahoo_spellings():
    assert norm("Software—Infrastructure") == norm("Software - Infrastructure") == "softwareinfrastructure"
    assert norm("REIT—Hotel & Motel") == "reithotelmotel"
    assert norm(None) == ""


@pytest.mark.parametrize("value, expected", [
    (20.0, 0.5), (12.0, 0.25), (16.0, 0.375), (60.0, 0.95), (1.0, 0.025), (100.0, 0.975), (45.0, 0.9)])
def test_percentile_interpolates(value, expected):
    assert DIST.percentile(value) == pytest.approx(expected)


def test_percentile_is_monotonic():
    values = [x / 2 for x in range(0, 200)]
    ranks = [DIST.percentile(v) for v in values]
    assert ranks == sorted(ranks)
    assert all(0 < r < 1 for r in ranks)


def test_flat_distribution_does_not_divide_by_zero():
    flat = Distribution(count=20, points=tuple((q, 1.0) for q in benchmarks.QUANTILES))
    assert flat.percentile(0.5) == pytest.approx(0.025)
    assert flat.percentile(1.0) == pytest.approx(0.5)  # everyone tied: middle
    assert flat.percentile(2.0) == pytest.approx(0.975)


def _group(name, level, metrics):
    return {"name": name, "level": level, "companies": 40,
            "metrics": {k: {"count": n, "q": [[q, v] for q, v in DIST.points]} for k, n in metrics.items()}}


def test_lookup_prefers_industry_and_falls_back_to_sector(tmp_path):
    data = {"generated_at": "2026-10-01", "groups": {
        "industry:" + norm("Software—Infrastructure"): _group("Software - Infrastructure", "industry",
                                                              {"pe_ratio": 30, "debt_to_equity": MIN_PEERS - 1}),
        "sector:technology": _group("Technology", "sector", {"pe_ratio": 300, "debt_to_equity": 280}),
    }}
    path = tmp_path / "b.json"
    path.write_text(json.dumps(data))
    b = benchmarks.load(str(path))
    ind, sec = b.lookup("Software - Infrastructure", "Technology")
    assert ind.name == "Software - Infrastructure" and sec.name == "Technology"
    assert b.for_metric("pe_ratio", ind, sec)[0].level == "industry"
    # Too few industry peers with this metric: use the sector instead.
    assert b.for_metric("debt_to_equity", ind, sec)[0].level == "sector"
    assert b.for_metric("unknown_metric", ind, sec) is None
    assert b.lookup("Unknown industry", None) == (None, None)
    assert b.generated_at == "2026-10-01"


def test_missing_file_means_no_benchmarks(tmp_path):
    assert benchmarks.load(str(tmp_path / "nope.json")).groups == {}
